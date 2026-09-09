import json
import os
import sys
from pathlib import Path
from livekit.agents import function_tool, RunContext
from tavily import AsyncTavilyClient
import asyncio
import asyncpg
from sentence_transformers import SentenceTransformer

# ---------------------------------------------------------------------------
# Shared infrastructure — loaded once at import time
# ---------------------------------------------------------------------------

_embed_model = SentenceTransformer("all-MiniLM-L6-v2")
_pg_pool = None


async def _get_pg_pool():
    global _pg_pool
    if _pg_pool is None:
        _pg_pool = await asyncpg.create_pool(
            dsn=os.environ.get(
                "PCB_KB_DSN",
                "postgresql://pcb:pcb_password@localhost:5439/pcbcopilot",
            )
        )
    return _pg_pool


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
# Tool: search_debugging_knowledge (pgvector RAG)
# ---------------------------------------------------------------------------

@function_tool()
async def search_debugging_knowledge(context: RunContext, query: str) -> str:
    """Search the electronics Q&A knowledge base for general debugging guidance."""
    embedding = await asyncio.to_thread(_embed_model.encode, [query])
    vector_literal = "[" + ",".join(str(x) for x in embedding[0].tolist()) + "]"

    pool = await _get_pg_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT question, answer
            FROM pcb_knowledge
            ORDER BY embedding <=> $1::vector
            LIMIT 3
            """,
            vector_literal,
        )

    if not rows:
        return "No relevant knowledge base entries found."

    return "\n\n".join(
        f"Q: {r['question'][:200]}\nA: {r['answer'][:400]}" for r in rows
    )


# ---------------------------------------------------------------------------
# Tool: search_component_info (Tavily web search)
# ---------------------------------------------------------------------------

_tavily = AsyncTavilyClient(api_key=os.environ["TAVILY_API_KEY"])


@function_tool()
async def search_component_info(context: RunContext, query: str) -> str:
    """Search the web for datasheet specs or info about a real-world component."""
    await context.update(f"Let me look that up — checking on {query} now.")

    response = await _tavily.search(
        query=query,
        search_depth="fast",
        max_results=3,
        include_answer=True,
    )

    answer = response.get("answer")
    return answer if answer else "I searched but couldn't find a clear answer for that."
