#!/usr/bin/env python3
"""Design-declared input transitions and Liberty group helpers."""

from __future__ import annotations
import math
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import _path_layout as _pl

_DESIGN_TIER = "design doc "


def _design_input_transition(project: Path) -> Optional[Tuple[str, str]]:
    """A design-declared off-chip input transition (ns): a strict L9 key/value
    row `set_input_transition | <ns>`, the same grammar as every R8 key."""
    for root in (project / "input" / "docs", _pl.generated_docs_dir(project)):
        if not root.is_dir():
            continue
        for path in sorted(root.glob("L9*")):
            try:
                lines = path.read_text(errors="replace").splitlines()
            except OSError:
                continue
            for lineno, line in enumerate(lines, 1):
                m = re.match(r"\s*\|\s*`?set_input_transition`?\s*\|"
                             r"\s*\*{0,2}\s*([^|]+?)\s*\*{0,2}\s*\|", line)
                if not m:
                    continue
                try:
                    number = float(m.group(1).strip().strip("*` "))
                except ValueError:
                    continue
                if math.isfinite(number) and number > 0:
                    return f"{number:g}", f"{_DESIGN_TIER}{path}:{lineno}"
    return None


def _liberty_blocks(text: str, kind: str) -> List[Tuple[str, str]]:
    """Every ``kind ("name") { ... }`` group directly inside ``text``, with its
    body, found by brace matching (Liberty groups nest; a regex cannot)."""
    out: List[Tuple[str, str]] = []
    for m in re.finditer(r"\b%s\s*\(\s*\"?([^\"()]*?)\"?\s*\)\s*\{" % kind, text):
        depth, i = 1, m.end()
        while depth and i < len(text):
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            i += 1
        out.append((m.group(1).strip(), text[m.end():i - 1]))
    return out


def _own_attrs(body: str) -> str:
    """A group's own simple attributes: its body with every nested group cut."""
    out, depth = [], 0
    for ch in body:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        elif depth == 0:
            out.append(ch)
    return "".join(out)
