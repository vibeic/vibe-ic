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
        # "+ PLACED ( X Y ) ...", and its two synonyms. DEF gives a PIN
        # three placement statuses -- PLACED, FIXED and COVER -- and all
        # three carry a coordinate. Reading only PLACED made a FIXED pin
        # INVISIBLE, and an invisible pin is not a violation: MEASURED on one
        # chip-path run whose pads were placed FIXED, this check reported
        # `VACUOUS_PASS: no DEF pins matched its patterns` over 36 pins it
        # could not see, where the same design with PLACED pins had reported
        # 36 constrained and on the correct side. A gate that stops seeing
        # its subject must not keep saying PASS.
        m_placed = re.search(
            r"\+\s+(?:PLACED|FIXED|COVER)\s+\(\s*(-?\d+)\s+(-?\d+)\s*\)", s)
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

# A pin name is `<base>[<index>]<tail>`; `tail` is normally empty and only
# non-empty when the L-doc cell held trailing prose the splitter could not
# separate (that pattern then matches nothing, which is the correct
# behaviour for an unparseable token).
_BRACKET_RE = re.compile(r"^(?P<base>[^\[\]]*)\[(?P<idx>[^\[\]]*)\](?P<tail>.*)$")

# Widest numeric bus range still expanded index-by-index. Beyond this the
# range degrades to the unbounded `\d+` form — the bound buys nothing on a
# 1k-wide bus and the alternation would be gratuitous.
_MAX_ENUMERATED_BUS = 1024


def _literal(s: str) -> str:
    """Escape `s` for use inside a regex, keeping an explicit ``.*`` glob."""
    return re.escape(s).replace(r"\.\*", r".*")


def _bus_range(idx: str):
    """Return (lo, hi) when `idx` is a NUMERIC range like ``7:0`` / ``0:7``.

    Returns None for a symbolic range (``size-1:0``, ``N-1:0``) or anything
    that is not a range at all.
    """
    m = re.match(r"^\s*(\d+)\s*:\s*(\d+)\s*$", idx)
    if m is None:
        return None
    a, b = int(m.group(1)), int(m.group(2))
    return (min(a, b), max(a, b))


def _index_regex(idx: str) -> str:
    """Regex FRAGMENT matching the bracketed index of an L-doc pattern.

    ``0`` / ``12``      → that index and NO other. This is the load-bearing
                          case: a pad table that splits a bus across two
                          edges (``data[0],data[1]`` North, ``data[2],data[3]``
                          South — routine on a real pad ring) declares single
                          bits, and rewriting them all to "any index" made
                          every bit match BOTH edges. The later edge then
                          overwrote the expectation for all of them and a
                          CONFORMING design was reported as FAIL.
    ``7:0``             → exactly the indices 0..7 (bounded), so ``data[7:0]``
                          North + ``data[15:8]`` South is likewise exact.
    ``size-1:0`` / ``i``→ symbolic: any index (the pre-existing behaviour;
                          the width is not knowable from the document).
    """
    idx = idx.strip()
    if re.match(r"^\d+$", idx):
        return re.escape(idx)
    rng = _bus_range(idx)
    if rng is not None and (rng[1] - rng[0] + 1) <= _MAX_ENUMERATED_BUS:
        return "(?:" + "|".join(str(i) for i in range(rng[0], rng[1] + 1)) + ")"
    return r"\d+"


def _pattern_to_regex(pattern: str) -> re.Pattern:
    """Convert an L-doc signal pattern to a compiled, fully-anchored regex.

    ``x[size-1:0]``  →  x[0] … x[N]      (symbolic bus range: any index)
    ``x[7:0]``       →  x[0] … x[7]      (numeric bus range: BOUNDED)
    ``x[0]``         →  x[0] and nothing else
    ``x.*``          →  glob
    ``rst``          →  exactly `rst`
    Chip-AGNOSTIC: no signal names hard-coded.
    """
    pat = pattern.strip()
    m = _BRACKET_RE.match(pat)
    if m is None:
        return re.compile(r"^" + _literal(pat) + r"$")
    return re.compile(
        r"^" + _literal(m.group("base"))
        + r"\[" + _index_regex(m.group("idx")) + r"\]"
        + _literal(m.group("tail")) + r"$")


def pin_order_cfg_tokens(pattern: str) -> List[str]:
    """Render an L-doc signal pattern as ``pin_order.cfg`` pin token(s).

    Shared with ``phase3_one_shot_runner.step_pnr`` so the CORRECTIVE half
    (the derived cfg fed to OpenROAD ``set_io_pin_constraint``) constrains
    exactly the pins the DISCLOSURE half (``check``) verifies — the two
    halves cannot drift apart into "constrain the whole bus to one edge
    while failing the design for obeying the document".

    ``x[size-1:0]`` → ``['x\\[.*\\]']``       (symbolic width: whole bus)
    ``x[3:0]``      → ``['x\\[0\\]', … 'x\\[3\\]']``  (bounded: per bit)
    ``x[0]``        → ``['x\\[0\\]']``        (that bit ONLY)
    ``rst``         → ``['rst']``
    """
    pat = pattern.strip()
    m = _BRACKET_RE.match(pat)
    if m is None:
        return [pat] if pat else []
    base, idx, tail = m.group("base"), m.group("idx").strip(), m.group("tail")
    esc_tail = tail.replace("[", r"\[").replace("]", r"\]")

    def _tok(inner: str) -> str:
        return f"{base}\\[{inner}\\]{esc_tail}"

    if re.match(r"^\d+$", idx):
        return [_tok(idx)]
    rng = _bus_range(idx)
    if rng is not None and (rng[1] - rng[0] + 1) <= _MAX_ENUMERATED_BUS:
        return [_tok(str(i)) for i in range(rng[0], rng[1] + 1)]
    return [_tok(".*")]


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

# Canonical routed-PnR output directory (flow path constant, chip-AGNOSTIC).
_PNR_DIR_REL = ("phase3", "stage3", "pnr")


def _discover_def(project: Path) -> Optional[Path]:
    """Pick the DEF to check when the caller did not name one.

    Order: the canonical routed DEF, then the NEWEST DEF in the canonical
    PnR dir, then the newest DEF anywhere under ``phase3/``. Ties break
    lexicographically so the choice is deterministic.

    (The previous rule was ``sorted(rglob("*.def"))[-1]`` with the comment
    "deepest stage". That is alphabetical, not staged — it picks whichever
    path sorts LAST, e.g. ``phase3/stage4/scratch.def`` over
    ``phase3/stage3/pnr/routed.def``. The comment described a guarantee the
    code did not provide.)
    """
    pnr_dir = project.joinpath(*_PNR_DIR_REL)
    routed = pnr_dir / "routed.def"
    if routed.is_file():
        return routed

    def _newest(paths: List[Path]) -> Optional[Path]:
        files = [p for p in paths if p.is_file()]
        if not files:
            return None
        return sorted(files, key=lambda p: (-p.stat().st_mtime, str(p)))[0]

    if pnr_dir.is_dir():
        hit = _newest(list(pnr_dir.glob("*.def")))
        if hit is not None:
            return hit
    ph3 = project / "phase3"
    if ph3.is_dir():
        return _newest(list(ph3.rglob("*.def")))
    return None


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
        def_path = _discover_def(project)
        if def_path is None:
            return {"verdict": "ERROR", "wrong_side_pins": {},
                    "vacuous": False, "note": "No DEF file found under phase3/"}

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
    # A pin claimed by TWO edges is a defect in the DOCUMENT, not in the
    # layout. Silently letting the last dict key win manufactures a
    # wrong-side verdict against a design that placed the pin exactly where
    # the (self-contradictory) table said — so ambiguity is reported as
    # ambiguity and NOTHING is claimed about the placement.
    all_names = set(pins.keys())
    claims: Dict[str, Set[str]] = {}
    for edge, patterns in table.items():
        edge_norm = _normalise_edge(edge) or edge.upper()
        for name in _match_pins_to_side(patterns, all_names):
            claims.setdefault(name, set()).add(edge_norm)

    ambiguous = {n: sorted(e) for n, e in claims.items() if len(e) > 1}
    if ambiguous:
        detail = "; ".join(f"{n} -> {'/'.join(e)}"
                           for n, e in sorted(ambiguous.items())[:10])
        return {"verdict": "ERROR", "wrong_side_pins": {}, "vacuous": False,
                "note": (f"ERROR: the pad-side table is AMBIGUOUS — "
                         f"{len(ambiguous)} pin(s) are claimed by more than "
                         f"one edge: {detail}"
                         f"{' ...' if len(ambiguous) > 10 else ''}. "
                         f"Fix the L-doc table; no placement verdict is "
                         f"claimed.")}

    expected_sides: Dict[str, str] = {n: next(iter(e))
                                      for n, e in claims.items()}

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
