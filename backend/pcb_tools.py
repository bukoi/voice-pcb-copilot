import json
import os
import sys
from pathlib import Path

# Add backend directory to sys.path so local imports work from any working directory
sys.path.insert(0, str(Path(__file__).parent.resolve()))

from dotenv import load_dotenv

load_dotenv()

from livekit.agents import function_tool, RunContext
from tavily import AsyncTavilyClient
import asyncio
from qdrant_client import AsyncQdrantClient
from sentence_transformers import SentenceTransformer

# ---------------------------------------------------------------------------
# Shared infrastructure — loaded once at import time
# ---------------------------------------------------------------------------

_embed_model = None
_qdrant_client = None
_tavily = None


def _get_embed_model():
    global _embed_model
    if _embed_model is None:
        _embed_model = SentenceTransformer("all-MiniLM-L6-v2")
    return _embed_model


def _get_tavily_client() -> AsyncTavilyClient:
    global _tavily
    if _tavily is None:
        api_key = os.environ.get("TAVILY_API_KEY", "")
        _tavily = AsyncTavilyClient(api_key=api_key)
    return _tavily


def _get_qdrant_client() -> AsyncQdrantClient:
    global _qdrant_client
    if _qdrant_client is None:
        url = os.environ.get("CLUSTER_URL_QDRANT") or os.environ.get("QDRANT_URL", "http://localhost:6333")
        api_key = os.environ.get("CLUSTER_KEY_QDRANT") or os.environ.get("QDRANT_API_KEY", None)
        _qdrant_client = AsyncQdrantClient(
            url=url,
            api_key=api_key,
        )
    return _qdrant_client


# ---------------------------------------------------------------------------
# Board data — per-session store with hardcoded fallback
# ---------------------------------------------------------------------------

# Default board: the hand-crafted power supply used before uploads existed.
_DEFAULT_DATA_PATH = Path(__file__).parent / "data" / "power_supply.json"
with open(_DEFAULT_DATA_PATH, "r", encoding="utf-8-sig") as _f:
    _DEFAULT_PCB_DATA: dict = json.load(_f)

# Maps room_name -> parsed board dict for every active session that has
# uploaded its own board. Falls back to _DEFAULT_PCB_DATA if absent.
_session_boards: dict[str, dict] = {}


def _get_board(room_name: str) -> dict:
    """Return the board data for this room, or the default if none uploaded."""
    return _session_boards.get(room_name, _DEFAULT_PCB_DATA)


# ---------------------------------------------------------------------------
# Parser import — reuse the same parser that generated parsed_board.json
# ---------------------------------------------------------------------------

# Allow the parser to be found whether we run from the backend/ directory or
# the project root.
_backend_dir = Path(__file__).parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

from parse_kicad_schematics import (
    parse_kicad_schematic,
    parse_kicad_pcb,
    merge_board_data,
)

# Temp directory for uploaded files (created on first use)
_TMP_DIR = _backend_dir / "tmp"


# ---------------------------------------------------------------------------
# Tool: load_board_file
# ---------------------------------------------------------------------------

@function_tool()
async def load_board_file(
    context: RunContext,
    sch_path: str | None,
    pcb_path: str | None,
) -> dict:
    """Load a KiCad .kicad_sch (sch_path) and/or .kicad_pcb (pcb_path) into this session. Pass None for files not provided."""
    if not sch_path and not pcb_path:
        return {"error": "Provide at least one of sch_path or pcb_path."}

    try:
        sch_data = (
            await asyncio.to_thread(parse_kicad_schematic, sch_path)
            if sch_path
            else None
        )
        pcb_data = (
            await asyncio.to_thread(parse_kicad_pcb, pcb_path)
            if pcb_path
            else None
        )
        merged = merge_board_data(sch_data, pcb_data)
    except Exception as exc:
        return {"error": f"Failed to parse files: {exc}"}

    room_name = context.room.name
    _session_boards[room_name] = merged

    return {
        "loaded": True,
        "components": len(merged.get("components", {})),
        "test_points": len(merged.get("test_points", {})),
        "nets": len(merged.get("nets", {})),
        "component_ids": sorted(merged.get("components", {}).keys()),
    }


# ---------------------------------------------------------------------------
# Tool: list_components
# ---------------------------------------------------------------------------

@function_tool()
async def list_components(context: RunContext) -> dict:
    """List all component reference designators and test points on the current board."""
    board = _get_board(context.room.name)
    components = board.get("components", {})
    test_points = board.get("test_points", {})
    nets = board.get("nets", {})

    return {
        "component_ids": sorted(components.keys()),
        "test_point_ids": sorted(test_points.keys()),
        "net_count": len(nets),
    }


# ---------------------------------------------------------------------------
# Tool: get_component
# ---------------------------------------------------------------------------

@function_tool()
async def get_component(context: RunContext, component_id: str) -> dict:
    """Get info about a board component by reference designator (e.g. U1, R1, C2)."""
    component_id = component_id.upper()
    board = _get_board(context.room.name)
    component = board["components"].get(component_id)
    if not component:
        available = sorted(board["components"].keys())
        return {
            "error": f"No component named {component_id} found on this board.",
            "available_components": available,
        }
    return component


# ---------------------------------------------------------------------------
# Tool: get_test_point
# ---------------------------------------------------------------------------

@function_tool()
async def get_test_point(context: RunContext, point_id: str) -> dict:
    """Get a test point's location and expected voltage by ID (e.g. TP1, TP3)."""
    point_id = point_id.upper()
    board = _get_board(context.room.name)
    point = board.get("test_points", {}).get(point_id)
    if not point:
        return {"error": f"No test point named {point_id} found on this board."}
    return point


# ---------------------------------------------------------------------------
# Measurements — per-session, in-memory
# ---------------------------------------------------------------------------

_measurements: dict[str, dict[str, float]] = {}  # room_name -> {point_id: voltage}


@function_tool()
async def record_measurement(context: RunContext, point_id: str, voltage: float) -> dict:
    """Record a voltage reading at a test point and compare to expected value."""
    point_id = point_id.upper()
    room = context.room.name
    _measurements.setdefault(room, {})[point_id] = voltage
    board = _get_board(room)
    expected = board.get("test_points", {}).get(point_id, {}).get("expected_voltage", "unknown")
    return {"point": point_id, "measured_voltage": voltage, "expected_voltage": expected}


@function_tool()
async def get_measurement(context: RunContext, point_id: str) -> dict:
    """Recall a previously recorded voltage measurement at a test point."""
    point_id = point_id.upper()
    room = context.room.name
    room_measurements = _measurements.get(room, {})
    if point_id not in room_measurements:
        return {"error": f"No measurement has been recorded yet at {point_id}."}
    return {"point": point_id, "measured_voltage": room_measurements[point_id]}


# ---------------------------------------------------------------------------
# Tool: search_debugging_knowledge (Qdrant vector RAG)
# ---------------------------------------------------------------------------

@function_tool()
async def search_debugging_knowledge(context: RunContext, query: str) -> str:
    """Search the electronics Q&A knowledge base for general debugging guidance."""
    embed_model = _get_embed_model()
    embedding = await asyncio.to_thread(embed_model.encode, query)
    client = _get_qdrant_client()

    try:
        response = await client.query_points(
            collection_name="pcb_knowledge",
            query=embedding.tolist(),
            limit=3,
        )
        points = response.points
    except Exception as exc:
        return f"Knowledge base search error: {exc}"

    if not points:
        return "No relevant knowledge base entries found."

    formatted = []
    for p in points:
        payload = p.payload or {}
        q = payload.get("question", "")[:200]
        a = payload.get("answer", "")[:400]
        formatted.append(f"Q: {q}\nA: {a}")

    return "\n\n".join(formatted)


# ---------------------------------------------------------------------------
# Tool: search_component_info (Tavily web search)
# ---------------------------------------------------------------------------


@function_tool()
async def search_component_info(context: RunContext, query: str) -> str:
    """Search the web for datasheet specs or info about a real-world component."""
    await context.update(f"Let me look that up — checking on {query} now.")
    tavily_client = _get_tavily_client()

    response = await tavily_client.search(
        query=query,
        search_depth="fast",
        max_results=3,
        include_answer=True,
    )

    answer = response.get("answer")
    return answer if answer else "I searched but couldn't find a clear answer for that."
