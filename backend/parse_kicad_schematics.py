"""
Parse a KiCad schematic (.kicad_sch) file into the same JSON shape as
power_supply.json, so get_component() / get_test_point() can read a
user-uploaded board instead of the hardcoded one.

--------------------------------------------------------------------------
SCOPE (read this before relying on it)
--------------------------------------------------------------------------
What this DOES extract, reliably:
  - Every component (symbol) on the schematic: reference designator
    (R1, U1, ...), value (1k, LM7805, ...), footprint, lib_id
  - Every label on the schematic (local + global + hierarchical) —
    used as a stand-in for "test points", since test points in a real
    design are usually just labeled nets (TP1, TP2, ...) rather than
    a distinct symbol type

Now ALSO parses .kicad_pcb (the physical board layout), which adds:
  - Each footprint's physical position/layer/rotation on the board
  - Real pin-to-net connectivity, straight from each pad's (net ...)
    entry — this is the one piece the schematic-only version couldn't
    give you, because PCB pads declare their net directly, no wire-
    tracing needed like on the schematic side

What this still does NOT extract:
  - Copper trace routing itself (just connectivity, not the physical
    path a trace takes across the board)
  - Anything if you only have a schematic and no PCB layout yet, or
    vice versa — merge_board_data() below handles either input being
    missing, but you obviously only get what you feed it

If/when you need trace-level routing info too, that's a further step
beyond this — nets/positions cover "what's connected to what and
where it sits," not "how the copper physically gets there."
--------------------------------------------------------------------------

Requires: pip install sexpdata
"""

import json
import sys
from pathlib import Path
import sexpdata


def _sym(x):
    """sexpdata parses bare words as Symbol objects; normalize to str."""
    return str(x.value()) if isinstance(x, sexpdata.Symbol) else x


def _find_all(tree, tag):
    """Recursively find every list node in the tree whose first element
    matches `tag` (e.g. every '(symbol ...)' block)."""
    results = []
    if isinstance(tree, list) and tree:
        if _sym(tree[0]) == tag:
            results.append(tree)
        for item in tree:
            if isinstance(item, list):
                results.extend(_find_all(item, tag))
    return results


def _get_property(symbol_node, prop_name):
    """Pull a named property value out of a (symbol ...) block, e.g.
    (property "Reference" "R1" ...) -> "R1" """
    for prop in _find_all(symbol_node, "property"):
        # prop looks like: [Symbol('property'), 'Reference', 'R1', ...]
        if len(prop) >= 3 and prop[1] == prop_name:
            return prop[2]
    return None


def _get_position(node):
    """Pull (at x y [angle]) out of a node, if present."""
    for item in node:
        if isinstance(item, list) and item and _sym(item[0]) == "at":
            coords = [x for x in item[1:] if isinstance(x, (int, float))]
            if len(coords) >= 2:
                return {"x": coords[0], "y": coords[1]}
    return None


def parse_kicad_schematic(sch_path: str) -> dict:
    """
    Parse a .kicad_sch file into:
      {
        "components": {
          "R1": {"value": "1k", "footprint": "...", "lib_id": "Device:R", "position": {...}},
          ...
        },
        "test_points": {
          "TP1": {"position": {...}},
          ...
        }
      }
    """
    raw = Path(sch_path).read_text(encoding="utf-8")
    tree = sexpdata.loads(raw)

    components = {}
    for symbol_node in _find_all(tree, "symbol"):
        ref = _get_property(symbol_node, "Reference")
        if not ref or ref.startswith("#"):  # '#PWR01' etc are power symbols, not real refs
            continue

        # skip the library-definition copies that appear inside
        # (lib_symbols ...) — those aren't placed components
        lib_id = None
        for item in symbol_node:
            if isinstance(item, list) and item and _sym(item[0]) == "lib_id":
                lib_id = item[1]
                break

        components[ref] = {
            "value": _get_property(symbol_node, "Value"),
            "footprint": _get_property(symbol_node, "Footprint"),
            "lib_id": lib_id,
            "position": _get_position(symbol_node),
        }

    test_points = {}
    label_tags = ("label", "global_label", "hierarchical_label")
    for tag in label_tags:
        for label_node in _find_all(tree, tag):
            # label_node looks like: [Symbol('label'), "TP1", (at ...), ...]
            name = label_node[1] if len(label_node) > 1 else None
            if isinstance(name, str) and name.upper().startswith("TP"):
                test_points[name.upper()] = {
                    "position": _get_position(label_node),
                }

    return {"components": components, "test_points": test_points}


def parse_kicad_pcb(pcb_path: str) -> dict:
    """
    Parse a .kicad_pcb file into:
      {
        "components": {
          "R1": {
            "layer": "F.Cu",
            "position": {"x": 100, "y": 50},
            "footprint": "Resistor_SMD:R_0603",
            "nets": {"1": "+5V", "2": "+3V3"}   # pad number -> net name
          },
          ...
        },
        "nets": {"1": "+5V", "2": "GND", "3": "+3V3"}   # net number -> name, board-wide
      }

    Unlike the schematic side, PCB pads state their net directly — no
    wire-tracing required — so "nets" per component here is real
    connectivity, not just a label's position.
    """
    raw = Path(pcb_path).read_text(encoding="utf-8")
    tree = sexpdata.loads(raw)

    # board-wide net table: (net 1 "+5V") -> {"1": "+5V"}
    board_nets = {}
    for net_node in _find_all(tree, "net"):
        if len(net_node) >= 3:
            net_num, net_name = str(net_node[1]), net_node[2]
            if net_name:  # net 0 is usually the unconnected/no-net entry, name ""
                board_nets[net_num] = net_name

    components = {}
    for fp_node in _find_all(tree, "footprint"):
        ref = _get_property(fp_node, "Reference")
        if not ref:
            continue

        layer = None
        for item in fp_node:
            if isinstance(item, list) and item and _sym(item[0]) == "layer":
                layer = item[1]
                break

        footprint_name = fp_node[1] if len(fp_node) > 1 else None

        pad_nets = {}
        for pad_node in _find_all(fp_node, "pad"):
            pad_num = pad_node[1] if len(pad_node) > 1 else None
            for item in pad_node:
                if isinstance(item, list) and item and _sym(item[0]) == "net":
                    if len(item) >= 3 and pad_num is not None:
                        pad_nets[str(pad_num)] = item[2]

        components[ref] = {
            "layer": layer,
            "position": _get_position(fp_node),
            "footprint": footprint_name,
            "nets": pad_nets,
        }

    return {"components": components, "nets": board_nets}


def merge_board_data(sch_data: dict | None, pcb_data: dict | None) -> dict:
    """
    Combine schematic + PCB parses into one components dict, keyed by
    reference designator. Either input can be None if you only have one
    of the two files — you just get whichever fields that file provides.
    """
    sch_components = (sch_data or {}).get("components", {})
    pcb_components = (pcb_data or {}).get("components", {})

    all_refs = set(sch_components) | set(pcb_components)
    merged = {}
    for ref in all_refs:
        merged[ref] = {**sch_components.get(ref, {}), **pcb_components.get(ref, {})}
        # both sides can have "position" and "footprint" — PCB values win
        # since they reflect actual physical placement, not schematic
        # drawing-canvas position

    return {
        "components": merged,
        "test_points": (sch_data or {}).get("test_points", {}),
        "nets": (pcb_data or {}).get("nets", {}),
    }


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--sch", help="Path to .kicad_sch file")
    parser.add_argument("--pcb", help="Path to .kicad_pcb file")
    parser.add_argument("--out", required=True, help="Output JSON path")
    args = parser.parse_args()

    if not args.sch and not args.pcb:
        print("Provide at least one of --sch or --pcb")
        sys.exit(1)

    sch_data = parse_kicad_schematic(args.sch) if args.sch else None
    pcb_data = parse_kicad_pcb(args.pcb) if args.pcb else None
    result = merge_board_data(sch_data, pcb_data)

    Path(args.out).write_text(json.dumps(result, indent=2))
    print(f"Parsed {len(result['components'])} components, "
          f"{len(result['test_points'])} test point labels, "
          f"{len(result['nets'])} nets -> {args.out}")


if __name__ == "__main__":
    main()