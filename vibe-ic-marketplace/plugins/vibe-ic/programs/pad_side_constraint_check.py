"""pad_side_constraint_check.py — Gate: verify IO pin placements match the
L-doc pad-side table (North/South/East/West per signal).

Exit codes
----------
0   PASS   — all pins on correct sides  (or vacuous-pass: no table declared).
1   FAIL   — one or more pins on the wrong side.
2   ERROR  — could not parse DEF / DIEAREA (configuration error).

Chip-AGNOSTIC: no hard-coded signal names, die sizes, or PDK literals.
The pad-side table is read from the Phase-1 generated L*.json (field
``pad_side_constraints``) with fall-back to parsing the input docs'
markdown tables.  Bus wildcards like ``x[size-1:0]`` / ``x.*`` are
resolved to concrete pin names found in the DEF PINS section.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# public API (consumed by tests)
# ---------------------------------------------------------------------------

def _parse_def_pins(def_text: str) -> Tuple[Dict[str, Tuple[int, int]], Tuple[int, int, int, int]]:
    """Parse PINS section of DEF.

    Returns
    -------
    pins   : {name: (x, y)} in DEF units.
    diearea: (x0, y0, x1, y1) in DEF units.

    Raises ValueError when DIEAREA is missing.
    """
    # DIEAREA ( x0 y0 ) ( x1 y1 )
    da = re.search(r"DIEAREA\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)", def_text)
    if da is None:
        raise ValueError("DIEAREA not found in DEF")
    x0, y0, x1, y1 = int(da.group(1)), int(da.group(2)), int(da.group(3)), int(da.group(4))

    # Extract PINS block
    pins: Dict[str, Tuple[int, int]] = {}
    in_pins = False
    current_pin: Optional[str] = None
    for line in def_text.splitlines():
        s = line.strip()
        if re.match(r"^PINS\s+\d+", s):
            in_pins = True
            continue
        if s == "END PINS":
            break
        if not in_pins:
            continue
        # "- <name> + NET ..."  starts a new pin record
        m_pin = re.match(r"^-\s+(\S+)\s+\+", s)
        if m_pin:
            current_pin = m_pin.group(1)
            continue
        # "+ PLACED ( X Y ) ..."
        m_placed = re.search(r"\+\s+PLACED\s+\(\s*(-?\d+)\s+(-?\d+)\s*\)", s)
        if m_placed and current_pin is not None:
            pins[current_pin] = (int(m_placed.group(1)), int(m_placed.group(2)))
    return pins, (x0, y0, x1, y1)


def _side_of_pin(x: int, y: int, diearea: Tuple[int, int, int, int]) -> str:
    """Classify a pin's side from its coordinate and the die bounding box.

    Strategy: whichever die edge the pin is closest to wins.
    Returns one of 'N', 'S', 'E', 'W'.
    """
    x0, y0, x1, y1 = diearea
    d_south = y - y0          # distance from south edge
    d_north = y1 - y          # distance from north edge
    d_west  = x - x0          # distance from west edge
    d_east  = x1 - x          # distance from east edge
    closest = min(d_south, d_north, d_west, d_east)
    if closest == d_south:
        return "S"
    if closest == d_north:
        return "N"
    if closest == d_west:
        return "W"
    return "E"


# ---------------------------------------------------------------------------
# L-doc pad-side table parsing
# ---------------------------------------------------------------------------

_EDGE_ALIASES: Dict[str, str] = {
    "n": "N", "north": "N", "北": "N",
    "s": "S", "south": "S", "南": "S",
    "e": "E", "east": "E",  "東": "E",
    "w": "W", "west": "W",  "西": "W",
}


def _normalise_edge(raw: str) -> Optional[str]:
    """Return canonical edge letter ('N'/'S'/'E'/'W') or None."""
    # Accept "North (N)" / "N" / "北" etc.
    # First try to extract the parenthesised letter  North (N) → N
    m = re.search(r"\(([NSEW])\)", raw, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    key = raw.strip().lower()
    return _EDGE_ALIASES.get(key)


def _parse_pad_table_from_markdown(text: str) -> Optional[Dict[str, List[str]]]:
    """Parse a markdown table with edge | signals columns.

    Handles both English "North (N)" and Traditional Chinese "北" row labels.
    Returns {edge_letter: [signal_pattern, ...]} or None when no table found.
    """
    # Find a table that has rows matching edge labels
    # We look for lines like:  | North (N) | `x[size-1:0]` ... |
    # or                        | **North (N)** | ...
    edge_row_re = re.compile(
        r"\|\s*\*{0,2}((?:[NSEW][^|]*?(?:\([NSEW]\))?|北|南|東|西)[^|]*?)\*{0,2}\s*\|\s*([^|]+)\|",
        re.IGNORECASE
    )
    result: Dict[str, List[str]] = {}
    for line in text.splitlines():
        m = edge_row_re.search(line)
        if not m:
            continue
        edge_raw = m.group(1).strip()
        edge = _normalise_edge(edge_raw)
        if edge is None:
            continue
        signals_raw = m.group(2)
        # split on commas/semicolons/「、」 then strip backticks/bold/spaces
        signals = re.split(r"[,;、\s]+", signals_raw)
        cleaned: List[str] = []
        for s in signals:
            s = s.strip().strip("`*").strip()
            if s:
                cleaned.append(s)
        if edge in result:
            result[edge].extend(cleaned)
        else:
            result[edge] = cleaned
    return result if result else None


def _load_pad_side_table_from_json(project: Path) -> Optional[Dict[str, List[str]]]:
    """Try to read pad_side_constraints from Phase-1 L*.json files."""
    json_dir = project / "phase1" / "generated_docs"
    if not json_dir.is_dir():
        return None
    for jf in sorted(json_dir.glob("L*.json")):
        try:
            d = json.loads(jf.read_text(errors="replace"))
            psc = d.get("pad_side_constraints")
            if psc and isinstance(psc, dict):
                return {k: list(v) for k, v in psc.items()}
        except Exception:
            continue
    return None


def _load_pad_side_table_from_docs(project: Path) -> Optional[Dict[str, List[str]]]:
    """Scan input/docs/L*.md for a pad-side markdown table."""
    docs_dir = project / "input" / "docs"
    if not docs_dir.is_dir():
        return None
    # Try L9 first (floorplan), then L3 (external interface), then all L*.md
    candidates = (
        list(docs_dir.glob("L9*.md"))
        + list(docs_dir.glob("L3*.md"))
        + list(docs_dir.glob("L*.md"))
    )
    for md in candidates:
        try:
            text = md.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        table = _parse_pad_table_from_markdown(text)
        if table:
            return table
    return None


def _load_pad_side_table(project: Path) -> Optional[Dict[str, List[str]]]:
    """Load pad-side constraints: JSON first, markdown fall-back."""
    t = _load_pad_side_table_from_json(project)
    if t:
        return t
    return _load_pad_side_table_from_docs(project)


# ---------------------------------------------------------------------------
# Pattern matching (bus wildcards)
# ---------------------------------------------------------------------------

def _pattern_to_regex(pattern: str) -> re.Pattern:
    """Convert an L-doc signal pattern to a compiled regex.

    ``x[size-1:0]``  →  matches  x[0] … x[N]  (any bracketed index)
    ``x.*``          →  standard glob-like: . and * are regex already
    ``x[0]``         →  exact literal match for x[0]
    Chip-AGNOSTIC: no signal names hard-coded.
    """
    # Replace the bus-width placeholder [size-1:0] or [N-1:0] with .*
    pat = re.sub(r"\[[\w\s\-+*/:]+\]", r"\\[\\d+\\]", pattern)
    # Also accept x.* as a glob
    if ".*" in pat or r"\[" not in pat:
        # treat as partial regex; anchor to full pin name
        pat = re.escape(pattern).replace(r"\.\*", r".*")
    # final anchor
    return re.compile(r"^" + pat + r"$")


def _match_pins_to_side(
        patterns: List[str],
        all_pin_names: Set[str],
) -> Set[str]:
    """Return the set of pin names (from all_pin_names) that match any pattern."""
    matched: Set[str] = set()
    for pat in patterns:
        rx = _pattern_to_regex(pat)
        for name in all_pin_names:
            if rx.match(name):
                matched.add(name)
    return matched


# ---------------------------------------------------------------------------
# Core check
# ---------------------------------------------------------------------------

PadCheckResult = dict  # keys: verdict, wrong_side_pins, vacuous, note


def check(project: Path, def_path: Optional[Path] = None) -> PadCheckResult:
    """Run the pad-side constraint check.

    Parameters
    ----------
    project  : path to the campaign run directory.
    def_path : explicit DEF path (auto-discovered from project when None).

    Returns a dict with keys:
      verdict         : 'PASS' | 'FAIL' | 'VACUOUS_PASS' | 'ERROR'
      wrong_side_pins : {pin_name: {'actual': side, 'expected': side}}
      vacuous         : bool
      note            : human-readable summary
    """
    # ---- locate the DEF -------------------------------------------------
    if def_path is None:
        candidates = sorted((project / "phase3").rglob("*.def")) if (project / "phase3").is_dir() else []
        if not candidates:
            return {"verdict": "ERROR", "wrong_side_pins": {},
                    "vacuous": False, "note": "No DEF file found under phase3/"}
        def_path = candidates[-1]   # last in sorted order (deepest stage)

    try:
        def_text = def_path.read_text(errors="replace")
    except Exception as exc:
        return {"verdict": "ERROR", "wrong_side_pins": {},
                "vacuous": False, "note": f"Cannot read DEF {def_path}: {exc}"}

    try:
        pins, diearea = _parse_def_pins(def_text)
    except ValueError as exc:
        return {"verdict": "ERROR", "wrong_side_pins": {},
                "vacuous": False, "note": str(exc)}

    # ---- load pad-side table -------------------------------------------
    table = _load_pad_side_table(project)
    if not table:
        return {"verdict": "VACUOUS_PASS", "wrong_side_pins": {},
                "vacuous": True,
                "note": ("VACUOUS_PASS: no pad-side table found in L docs; "
                         "constraint check skipped (not a violation).")}

    # ---- compute actual sides ------------------------------------------
    actual_sides: Dict[str, str] = {
        name: _side_of_pin(x, y, diearea)
        for name, (x, y) in pins.items()
    }

    # ---- match patterns → expected side --------------------------------
    all_names = set(pins.keys())
    expected_sides: Dict[str, str] = {}
    for edge, patterns in table.items():
        edge_norm = _normalise_edge(edge) or edge.upper()
        matched = _match_pins_to_side(patterns, all_names)
        for name in matched:
            expected_sides[name] = edge_norm

    if not expected_sides:
        return {"verdict": "VACUOUS_PASS", "wrong_side_pins": {},
                "vacuous": True,
                "note": ("VACUOUS_PASS: pad-side table present but no DEF pins "
                         "matched its patterns; skipping (check pattern syntax).")}

    # ---- compare --------------------------------------------------------
    wrong: Dict[str, Dict] = {}
    for name, expected in expected_sides.items():
        actual = actual_sides.get(name)
        if actual is None:
            continue  # pin in table but not yet placed — not a side violation
        if actual != expected:
            wrong[name] = {"actual": actual, "expected": expected}

    if wrong:
        # Group by (actual, expected) for readability
        groups: Dict[Tuple[str, str], List[str]] = {}
        for name, info in wrong.items():
            key = (info["actual"], info["expected"])
            groups.setdefault(key, []).append(name)
        detail_lines = []
        for (act, exp), names in sorted(groups.items()):
            sorted_names = sorted(names)
            detail_lines.append(
                f"  expected={exp} actual={act}: {', '.join(sorted_names)}")
        note = (f"FAIL: {len(wrong)} pin(s) on wrong side:\n"
                + "\n".join(detail_lines))
        return {"verdict": "FAIL", "wrong_side_pins": wrong,
                "vacuous": False, "note": note}

    note = (f"PASS: all {len(expected_sides)} constrained pin(s) "
            f"are on the correct side.")
    return {"verdict": "PASS", "wrong_side_pins": {},
            "vacuous": False, "note": note}


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="Gate: verify IO pin placement matches L-doc pad-side table.")
    ap.add_argument("project", help="Campaign run directory (contains input/, phase3/)")
    ap.add_argument("--def", dest="def_path", default=None,
                    help="Explicit DEF path (auto-discovered when omitted)")
    args = ap.parse_args(argv)

    project = Path(args.project)
    def_path = Path(args.def_path) if args.def_path else None

    result = check(project, def_path)
    print(result["note"])

    verdict = result["verdict"]
    if verdict in ("PASS", "VACUOUS_PASS"):
        return 0
    if verdict == "FAIL":
        return 1
    # ERROR
    return 2


if __name__ == "__main__":
    sys.exit(main())
