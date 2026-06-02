#!/usr/bin/env python3
"""
hold_buffer_cell_picker.py — rank PDK library cells for hold-fix insertion.

From `skills/hold-fix/SKILL.md` Step 2 "Buffer selection from library":
  - Prefer minimum-drive buffers (smallest area, most delay per area).
  - Prefer delay cells if available in the PDK (e.g. `*__dlygate*`).
  - Avoid high-drive buffers — they add LESS delay per area, so they are a
    poor choice for the "slow down the short path" hold fix.

This is a deterministic library-cell ranking keyed on the Liberty cell-name
list — NOT an LLM judgment. The drive strength is encoded in the standard
cell-name suffix (`..._1`, `..._2`, `..._4`, ...; or `bufx1`, `bufx16`, etc.),
and the cell ROLE (buffer / delay-gate / clock-buffer / inverter / other) is
encoded in the cell base name. Both are extracted by general regex, so the
ranker works for ANY PDK that follows the conventional `<lib>__<cell><drive>`
naming (sky130, gf180, tsmc-style bufxN, etc.).

Ranking key (best hold-fix candidate first):
  1. cell ROLE rank:   delay-gate (0) < plain buffer (1) < everything-else
     (delay gates are purpose-built for adding delay; plain buffers next;
     clock buffers / inverters / logic cells are rejected — see below).
  2. drive strength:   smallest drive first (a x1 buffer adds the most delay
     per unit area, exactly the SKILL preference).
  3. cell name:        lexical tie-break for determinism.

Rejected (never a hold-fix candidate, reported as `excluded`):
  - clock-tree buffers (`clkbuf`, `clk_buf`, `clkdly`...): hold fixing must
    not insert cells onto the clock network.
  - inverters / logic gates: changing logic polarity/function is not a hold
    fix (an even chain of inverters could pad delay, but the SKILL calls for
    buffers/delay cells, and a lone inverter would invert the data — unsafe).

HARD honesty rules:
  - Empty / missing / unparseable cell list  => FAIL (rc=1). Never a vacuous
    PASS: a hold fix with no candidate cell cannot proceed.
  - A list that parses but contains NO usable buffer/delay cell (only clock
    buffers, inverters, logic) => FAIL (rc=1): there is nothing safe to insert.
  - PASS (rc=0) only when at least one delay-gate or plain buffer is found and
    ranked; the top pick is the SKILL-preferred minimum-drive delay/buffer.

chip-AGNOSTIC: no specific PDK / vendor cell is hard-coded as "the answer";
the cell list is supplied by the caller (a real Liberty `.lib` cell dump or a
JSON list). Role/drive are inferred from naming conventions, not a lookup of
named cells.

Usage
-----
    # cells from a newline / comma list file, or a JSON array
    python3 hold_buffer_cell_picker.py <cells_file> [--json <out>]
    python3 hold_buffer_cell_picker.py --cells "buf_1,buf_4,dlygate_2,clkbuf_1"
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional, Tuple


_TOOL = "hold_buffer_cell_picker"

# Role classification (lower rank == more preferred for hold fixing).
ROLE_DELAY = "delay_gate"
ROLE_BUFFER = "buffer"
ROLE_CLOCK = "clock_buffer"   # excluded
ROLE_INVERTER = "inverter"    # excluded
ROLE_OTHER = "other"          # excluded

_ROLE_RANK = {ROLE_DELAY: 0, ROLE_BUFFER: 1}

# --- name-fragment matchers (case-insensitive, conventional std-cell names) ---
# Order matters: clock buffers must be matched BEFORE plain buffers so that a
# `clkbuf` is not mis-ranked as a usable hold buffer.
_RE_CLOCK = re.compile(r"(?:^|[_\W])(?:clk|clock)[a-z]*?(?:buf|dly|delay)", re.I)
_RE_CLOCK2 = re.compile(r"\bclkbuf\b|\bclk_buf\b|\bclkdly\b", re.I)
_RE_DELAY = re.compile(r"(?:^|[_\W])(?:dly|delay)(?:gate|cell|buf|line)?", re.I)
_RE_BUFFER = re.compile(r"(?:^|[_\W])buf(?:fer)?(?:[_\dx]|$)", re.I)
_RE_INVERTER = re.compile(r"(?:^|[_\W])(?:inv|clkinv)(?:[_\dx]|$)", re.I)

# Drive-strength suffix: trailing `_<n>` or `x<n>` (sky130 `..._4`, tsmc `bufx16`).
_RE_DRIVE = re.compile(r"(?:_|x)(\d+)\s*$", re.I)


@dataclass
class CellRank:
    name: str
    role: str
    drive: Optional[int]   # parsed drive strength, None if not encoded
    usable: bool           # True iff role is delay_gate or buffer
    reason: str            # why excluded (empty when usable)


def classify_role(name: str) -> str:
    """Infer the cell's role from its name. Clock buffers are checked first."""
    n = name.strip()
    if not n:
        return ROLE_OTHER
    if _RE_CLOCK.search(n) or _RE_CLOCK2.search(n):
        return ROLE_CLOCK
    if _RE_DELAY.search(n):
        return ROLE_DELAY
    if _RE_INVERTER.search(n):
        return ROLE_INVERTER
    if _RE_BUFFER.search(n):
        return ROLE_BUFFER
    return ROLE_OTHER


def parse_drive(name: str) -> Optional[int]:
    """Extract the drive strength encoded in the cell-name suffix, if any."""
    # use the *cell* token (drop the lib prefix `<lib>__<cell>`)
    cell = name.split("__")[-1]
    m = _RE_DRIVE.search(cell)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    return None


def _exclude_reason(role: str) -> str:
    if role == ROLE_CLOCK:
        return "clock-tree buffer — hold fix must not touch the clock network"
    if role == ROLE_INVERTER:
        return "inverter — would change data polarity; not a buffer/delay cell"
    return "not a buffer or delay cell"


def rank_cell(name: str) -> CellRank:
    role = classify_role(name)
    drive = parse_drive(name)
    usable = role in _ROLE_RANK
    reason = "" if usable else _exclude_reason(role)
    return CellRank(name=name.strip(), role=role, drive=drive,
                    usable=usable, reason=reason)


def _sort_key(c: CellRank) -> Tuple[int, int, str]:
    # role rank, then smallest drive first (None drive sorts as +inf == worst
    # of the encoded ones but still better than an excluded cell, which never
    # reaches here), then lexical for determinism.
    drive = c.drive if c.drive is not None else 1_000_000
    return (_ROLE_RANK[c.role], drive, c.name)


def rank_cells(names: List[str]) -> Tuple[List[CellRank], List[CellRank]]:
    """Return (usable_ranked_best_first, excluded)."""
    ranked = [rank_cell(n) for n in names if n and n.strip()]
    usable = sorted((c for c in ranked if c.usable), key=_sort_key)
    excluded = [c for c in ranked if not c.usable]
    return usable, excluded


def _parse_cells_text(text: str) -> List[str]:
    text = text.strip()
    if not text:
        return []
    # JSON array of strings?
    if text.lstrip().startswith("["):
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return [str(x) for x in data]
        except json.JSONDecodeError:
            pass
    # newline / comma / whitespace separated
    parts = re.split(r"[,\n\r]+", text)
    return [p.strip() for p in parts if p.strip()]


def evaluate(names: List[str]) -> Tuple[str, int, dict]:
    """Return (verdict, rc, report)."""
    if not names:
        return "FAIL", 1, {
            "tool": _TOOL,
            "verdict": "FAIL",
            "reason": "EMPTY_CELL_LIST",
            "message": "no library cells supplied — cannot pick a hold-fix "
                       "buffer (missing/garbage input is an honest FAIL, never "
                       "a vacuous pass)",
            "usable": [],
            "excluded": [],
            "recommended": None,
        }
    usable, excluded = rank_cells(names)
    report = {
        "tool": _TOOL,
        "usable": [asdict(c) for c in usable],
        "excluded": [asdict(c) for c in excluded],
        "n_input": len([n for n in names if n and n.strip()]),
    }
    if not usable:
        report["verdict"] = "FAIL"
        report["reason"] = "NO_USABLE_HOLD_CELL"
        report["recommended"] = None
        report["message"] = (
            "library has no buffer or delay cell safe for hold insertion "
            "(only clock buffers / inverters / logic cells found) — nothing "
            "to insert")
        return "FAIL", 1, report
    best = usable[0]
    report["verdict"] = "PASS"
    report["recommended"] = asdict(best)
    report["message"] = (
        f"recommended hold-fix cell: '{best.name}' "
        f"(role={best.role}, drive={best.drive}) — SKILL-preferred "
        f"minimum-drive {best.role.replace('_', ' ')}")
    return "PASS", 0, report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Rank PDK cells for hold-fix buffer/delay insertion")
    ap.add_argument("cells_file", nargs="?",
                    help="file with cell names (newline/comma list OR JSON array)")
    ap.add_argument("--cells", help="inline comma/space separated cell names")
    ap.add_argument("--json", help="write JSON report to this path")
    args = ap.parse_args(argv)

    names: List[str] = []
    if args.cells:
        names = _parse_cells_text(args.cells)
    elif args.cells_file:
        p = Path(args.cells_file)
        if not p.is_file():
            print(f"[{_TOOL}] cells file not found: {p}", file=sys.stderr)
            # missing input file is an honest FAIL, not a crash-skip
            verdict, rc, report = evaluate([])
            report["reason"] = "CELLS_FILE_MISSING"
            report["message"] = f"cells file not found: {p}"
            if args.json:
                Path(args.json).write_text(json.dumps(report, indent=2) + "\n")
            return rc
        try:
            names = _parse_cells_text(p.read_text(errors="replace"))
        except OSError as e:
            print(f"[{_TOOL}] cannot read {p}: {e}", file=sys.stderr)
            return 1
    else:
        print(f"[{_TOOL}] supply <cells_file> or --cells", file=sys.stderr)
        return 1

    verdict, rc, report = evaluate(names)
    if args.json:
        outp = Path(args.json)
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_text(json.dumps(report, indent=2) + "\n")
    print(f"=== {_TOOL} ===")
    print(f"  verdict: {verdict}")
    if report.get("recommended"):
        r = report["recommended"]
        print(f"  recommended: {r['name']} (role={r['role']}, drive={r['drive']})")
    for c in report.get("excluded", []):
        print(f"  excluded: {c['name']} — {c['reason']}")
    if verdict == "FAIL":
        print(f"  FAIL: {report.get('message')}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
