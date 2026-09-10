import argparse
import uuid
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

BATCH_SIZE = 128
COLLECTION_NAME = "pcb_knowledge"
EMBEDDING_DIM = 384  # Matches "all-MiniLM-L6-v2" output size


def clean_html(raw_html: str) -> str:
    """Strip HTML tags from SE post body, collapse whitespace."""
    text = BeautifulSoup(raw_html, "lxml").get_text(separator=" ")
    return " ".join(text.split())


def load_posts(posts_xml_path: str):
    """
    Stream-parse Posts.xml using iterparse to keep memory usage low.
    """
    questions = {}
    answers = {}

    context = ET.iterparse(posts_xml_path, events=("end",))
    for event, elem in context:
        if elem.tag == "row":
            attrib = elem.attrib
            post_type = attrib.get("PostTypeId")
            post_id = attrib.get("Id")

            if post_type == "1":  # Question
                questions[post_id] = {
                    "title": attrib.get("Title", ""),
                    "body": attrib.get("Body", ""),
                    "tags": attrib.get("Tags", ""),
                    "score": int(attrib.get("Score", 0)),
                    "accepted_answer_id": attrib.get("AcceptedAnswerId"),
                }
            elif post_type == "2":  # Answer
                answers[post_id] = {
                    "body": attrib.get("Body", ""),
                    "parent_id": attrib.get("ParentId"),
                    "score": int(attrib.get("Score", 0)),
                }
            elem.clear()

    return questions, answers


def build_qa_pairs(questions: dict, answers: dict, min_score: int = 1):
    """
    Pair each question with its accepted or highest-scored answer.
    """
    by_parent = {}
    for aid, a in answers.items():
        by_parent.setdefault(a["parent_id"], []).append(a)

    pairs = []
    for qid, q in questions.items():
        answer_text = None

        if q["accepted_answer_id"] and q["accepted_answer_id"] in answers:
            answer_text = answers[q["accepted_answer_id"]]["body"]
        elif qid in by_parent:
            best = max(by_parent[qid], key=lambda a: a["score"])
            if best["score"] >= min_score:
                answer_text = best["body"]

        if not answer_text:
            continue

        question_text = f"{q['title']}\n{clean_html(q['body'])}"
        pairs.append({
            "question": question_text.strip(),
            "answer": clean_html(answer_text),
            "tags": q["tags"].replace("><", ", ").strip("<>"),
            "score": q["score"],
        })

    return pairs


def ensure_collection(client: QdrantClient):
    """Ensure the Qdrant collection exists with Cosine similarity."""
    collections = client.get_collections().collections
    exists = any(c.name == COLLECTION_NAME for c in collections)

    if not exists:
        print(f"Creating collection '{COLLECTION_NAME}' in Qdrant...")
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
        )


def embed_and_upsert(client: QdrantClient, pairs, model_name="all-MiniLM-L6-v2"):
    model = SentenceTransformer(model_name)

    for i in range(0, len(pairs), BATCH_SIZE):
        batch = pairs[i : i + BATCH_SIZE]
        texts = [f"{p['question']}\n{p['answer']}" for p in batch]
        embeddings = model.encode(texts, show_progress_bar=False)

        points = []
        for p, emb in zip(batch, embeddings):
            # Qdrant requires a valid UUID or integer ID
            point_id = str(uuid.uuid4())
            points.append(
                PointStruct(
                    id=point_id,
                    vector=emb.tolist(),
                    payload={
                        "question": p["question"],
                        "answer": p["answer"],
                        "tags": p["tags"],
                        "score": p["score"],
                    },
                )
            )

        client.upsert(collection_name=COLLECTION_NAME, points=points)
        print(f"Upserted {i + len(batch)} / {len(pairs)}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--posts", required=True, help="Path to Posts.xml")
    parser.add_argument(
        "--url",
        default="http://localhost:6333",
        help="Qdrant server URL (defaults to http://localhost:6333)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="API key for Qdrant Cloud (optional)",
    )
    parser.add_argument("--min-score", type=int, default=1)
    args = parser.parse_args()

    print("Parsing dump...")
    questions, answers = load_posts(args.posts)
    print(f"Found {len(questions)} questions, {len(answers)} answers")

    print("Building Q&A pairs...")
    pairs = build_qa_pairs(questions, answers, min_score=args.min_score)
    print(f"Built {len(pairs)} usable Q&A pairs")

    # Connect to Qdrant
    client = QdrantClient(
    url=args.url,
    api_key=args.api_key,
    prefer_grpc=True,  # Enables gRPC transport
    timeout=60.0
)
    ensure_collection(client)

    print("Embedding + upserting to Qdrant...")
    embed_and_upsert(client, pairs)

    print("Done.")


if __name__ == "__main__":
    main()