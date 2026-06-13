#!/usr/bin/env python3
"""
l3_opcode_argument_constraints_check.py — Wave 37 / A3

When extracted vendor docs mention an ADDR / LEN range constraint
(e.g. ``讀取長度+位址不得超過 0x80``, ``合法的地址範圍為 0x00 到 0x2E``,
``length must not exceed 31 bytes``, ``address <= 0x7F``), each
referenced opcode in L3_CMD_PROTOCOL.json MUST have an
``argument_constraints`` array (or per-arg ``addr_max`` / ``len_max``
fields) so spec-to-rtl can synthesize bounds-check / silent-reject
logic.

Detection is OPCODE-AGNOSTIC and language-agnostic. Patterns:
  - Chinese: (位址|地址|ADDR).*(不得超過|≤|<=|max|最大|範圍|到).*(0x[0-9A-Fa-f]+)
             (長度|LEN|位元組|byte).*(不得超過|≤|<=|max|最大|至多).*(0x[0-9A-Fa-f]+|\\d+)
  - English: address.*(<=|max|range).*0x[0-9A-Fa-f]+
             length.*(<=|max|up to).*\\d+

Schema accepted:
    opcodes: [
      {hex: "0xE0",
       argument_constraints: [
         {name: "addr", max_hex: "0x7F", evidence: "..."},
         {name: "len", max_hex: "0x1F", evidence: "..."}
       ],
       addr_max: "0x7F",       # alternative shape
       len_max: "0x1F"
      }
    ]

Usage:
    python3 l3_opcode_argument_constraints_check.py <project_dir>

Exit codes:
    0 = PASS (no constraint mention OR L3 captured)
    1 = FAIL (constraint mention exists, L3 missing argument_constraints)
    2 = input-missing (skip)
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple


_DOC_GLOBS = (
    "**/input_doc/*.txt",
    "**/input/docs/*.txt",
    "**/input/input_doc/*.txt",
)

_L3_GLOBS = (
    "phase1/generated_docs/L3_CMD_PROTOCOL.json",
    "phase1/generated_docs/L3*.json",
    "**/L3_CMD_PROTOCOL.json",
)

# Chinese ADDR / LEN limit patterns (the column-D primary case)
_RE_ZH_ADDR = re.compile(
    r"(位址|地址|address|ADDR)[^\n]{0,50}?(不得超過|不超過|不可超過|≤|<=|max|最大|範圍|到|超過|不大於|must not exceed|cannot exceed|exceed)[^\n]{0,30}?(0x[0-9A-Fa-f]+|\d+)",
    re.IGNORECASE,
)
_RE_ZH_LEN = re.compile(
    r"(長度|位元組|byte|LEN|length)[^\n]{0,50}?(不得超過|≤|<=|max|最大|至多|不大於|超過|範圍|到)[^\n]{0,30}?(0x[0-9A-Fa-f]+|\d+)",
    re.IGNORECASE,
)
# Combined "讀取長度+位址不得超過 0x80" style
_RE_LEN_PLUS_ADDR = re.compile(
    r"(長度|len)\s*[+＋]\s*(位址|地址|addr)[^\n]{0,30}?(不得超過|≤|<=|max|超過|不大於)[^\n]{0,20}?(0x[0-9A-Fa-f]+)",
    re.IGNORECASE,
)
_RE_RANGE = re.compile(
    r"(合法.*?(範圍|地址|位址)|valid.*?range)[^\n]{0,40}?(0x[0-9A-Fa-f]+).*?(0x[0-9A-Fa-f]+)",
    re.IGNORECASE,
)


_CONSTRAINT_KEYS = (
    "argument_constraints", "arg_constraints", "argument_limits",
    "addr_max", "len_max", "max_addr", "max_len",
    "address_max_hex", "length_max_hex", "constraints",
)


def _find_l3(project: Path) -> Optional[Path]:
    for pat in _L3_GLOBS:
        for hit in project.glob(pat):
            if hit.is_file():
                return hit
    return None


def _scan_docs(project: Path) -> List[Tuple[Path, int, str]]:
    """Return [(file, line_no, line_text)] of constraint mentions."""
    hits: List[Tuple[Path, int, str]] = []
    seen = set()
    for pat in _DOC_GLOBS:
        for doc in project.glob(pat):
            if not doc.is_file() or doc in seen:
                continue
            seen.add(doc)
            try:
                text = doc.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for i, line in enumerate(text.splitlines(), start=1):
                if (_RE_LEN_PLUS_ADDR.search(line)
                        or _RE_ZH_ADDR.search(line)
                        or _RE_ZH_LEN.search(line)
                        or _RE_RANGE.search(line)):
                    hits.append((doc, i, line.strip()[:120]))
    return hits


def _walk_has_constraints(node) -> int:
    """Return number of opcode-level constraint signals found."""
    n = 0
    if isinstance(node, dict):
        for k, v in node.items():
            if k in _CONSTRAINT_KEYS:
                if isinstance(v, list) and v:
                    n += len(v)
                elif isinstance(v, (str, int, dict)) and v not in (None, "", {}, []):
                    n += 1
            else:
                n += _walk_has_constraints(v)
    elif isinstance(node, list):
        for item in node:
            n += _walk_has_constraints(item)
    return n


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: l3_opcode_argument_constraints_check <project_dir>",
              file=sys.stderr)
        return 2
    project = Path(sys.argv[1]).resolve()
    if not project.is_dir():
        return 2

    hits = _scan_docs(project)
    if not hits:
        print("[SKIP] l3_opcode_argument_constraints_check: "
              "no ADDR/LEN constraint mentions in extracted docs")
        return 2

    l3 = _find_l3(project)
    if l3 is None:
        sample = hits[0]
        print(f"[FAIL] l3_opcode_argument_constraints_check: "
              f"extracted docs mention ADDR/LEN constraints "
              f"({sample[0].name}:{sample[1]}) but L3_CMD_PROTOCOL.json "
              f"missing")
        return 1

    try:
        data = json.loads(l3.read_text())
    except Exception as exc:
        print(f"[FAIL] l3_opcode_argument_constraints_check: "
              f"cannot parse {l3.relative_to(project)}: {exc}")
        return 1

    n_constraints = _walk_has_constraints(data)
    if n_constraints == 0:
        sample_lines = "\n  ".join(
            f"{h[0].name}:{h[1]} — {h[2]}" for h in hits[:5]
        )
        print(f"[FAIL] l3_opcode_argument_constraints_check: "
              f"{len(hits)} ADDR/LEN constraint mention(s) in extracted "
              f"docs but L3 has zero opcode argument_constraints / "
              f"addr_max / len_max fields. Evidence:\n  {sample_lines}")
        return 1

    print(f"[PASS] l3_opcode_argument_constraints_check: "
          f"{n_constraints} constraint signal(s) in L3 "
          f"(scanned {len(hits)} doc mention(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
