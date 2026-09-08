import json
import os
from pathlib import Path
from livekit.agents import function_tool, RunContext
from tavily import AsyncTavilyClient

DATA_PATH = Path(__file__).parent / "data" / "power_supply.json"

with open(DATA_PATH, "r", encoding="utf-8-sig") as f:
    PCB_DATA = json.load(f)

_tavily = AsyncTavilyClient(api_key=os.environ["TAVILY_API_KEY"])

_measurements = {}


@function_tool()
async def get_component(context: RunContext, component_id: str) -> dict:
    """Look up information about a specific PCB component by its reference
    designator (e.g. U1, R1, C2).

    Args:
        component_id: The component's reference designator, e.g. "U1", "R1".
    """
    component_id = component_id.upper()
    component = PCB_DATA["components"].get(component_id)
    if not component:
        return {"error": f"No component named {component_id} found on this board."}
    return component


@function_tool()
async def get_test_point(context: RunContext, point_id: str) -> dict:
    """Look up a test point's location and expected voltage (e.g. TP1, TP3).

    Args:
        point_id: The test point identifier, e.g. "TP1", "TP3".
    """
    point_id = point_id.upper()
    point = PCB_DATA["test_points"].get(point_id)
    if not point:
        return {"error": f"No test point named {point_id} found on this board."}
    return point


@function_tool()
async def record_measurement(context: RunContext, point_id: str, voltage: float) -> dict:
    """Record a voltage measurement the user just took at a test point, and
    compare it to the expected value for that point.

    Args:
        point_id: The test point where the measurement was taken, e.g. "TP3".
        voltage: The measured voltage value, e.g. 1.8.
    """
    point_id = point_id.upper()
    _measurements[point_id] = voltage
    expected = PCB_DATA["test_points"].get(point_id, {}).get("expected_voltage", "unknown")
    return {"point": point_id, "measured_voltage": voltage, "expected_voltage": expected}


@function_tool()
async def get_measurement(context: RunContext, point_id: str) -> dict:
    """Recall a previously recorded measurement at a test point.

    Args:
        point_id: The test point to recall, e.g. "TP3".
    """
    point_id = point_id.upper()
    if point_id not in _measurements:
        return {"error": f"No measurement has been recorded yet at {point_id}."}
    return {"point": point_id, "measured_voltage": _measurements[point_id]}


@function_tool()
async def search_component_info(context: RunContext, query: str) -> str:
    """Search the web for real, current information about an electronic
    component not found in the local PCB data — e.g. datasheet specs,
    max voltages, or pin configurations for real-world parts.

    Args:
        query: What to search for, e.g. "LM7805 max input voltage".
    """
    await context.update(f"Let me look that up — checking on {query} now.")

    response = await _tavily.search(
        query=query,
        search_depth="fast",
        max_results=3,
        include_answer=True,
    )

    answer = response.get("answer")
    return answer if answer else "I searched but couldn't find a clear answer for that."
