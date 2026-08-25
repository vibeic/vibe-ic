#!/usr/bin/env python3
r"""prose_interface_bridge.py — try every prose-interface reader, in order.

A spec states its ports in whatever form its author liked: an indented bullet
list, a markdown table, a Verilog module header. `port_parser.parse_ports`
reads some of those; the bridges translate the rest into a form it does read.

WHY A CHAIN AND NOT TWO IMPORTS. The bridges have identical contracts —
`bridge_prompt(text) -> str`, prose in, prose out, and a NO-OP return when the
form is not recognised — so trying them in sequence is safe by construction:
each one either recognises its shape or hands the text on untouched.

Left as separate imports, they were adopted separately. `prose_port_block_read`
(indented-bullet form) had 13 importers. `prose_interface_bridge_md`
(markdown-table form) had ZERO — not because it does less, but because it
shipped under a benchmark prefix where nothing outside that benchmark looked.
Zero importers on a capability is a description of the WIRING, never of the
capability, and deleting on that basis throws away the thing and keeps the bug.

Add a reader here and every caller gets it, which is the property the two
separate imports did not have.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable, List, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))


def _bullet(text: str) -> str:
    from prose_port_block_read import bridge_prompt as _b
    return _b(text)


def _md_table(text: str) -> str:
    from prose_interface_bridge_md import bridge_prompt as _b
    return _b(text)


def _signal_table(text: str) -> str:
    from prose_interface_table_read import bridge_prompt as _b
    return _b(text)


# Order is by specificity of the pattern each recognises, most specific first.
# Every one is a no-op on text it does not recognise, so order affects only
# which reader claims a text both could read — and no two currently overlap.
BRIDGES: List[Tuple[str, Callable[[str], str]]] = [
    ("indented_bullets", _bullet),
    ("markdown_table", _md_table),
    ("signal_direction_table", _signal_table),
]


def bridge(text: str) -> str:
    """Prose in, prose out, with a parseable interface block prepended if any
    reader recognised one. Unchanged when none did."""
    if not (text or "").strip():
        return text
    for _name, fn in BRIDGES:
        try:
            out = fn(text)
        except Exception:
            continue
        if out and out != text:
            return out
    return text


def which_bridged(text: str) -> str | None:
    """Which reader claims this text, or None. For callers that need to say."""
    for name, fn in BRIDGES:
        try:
            if fn(text) != text:
                return name
        except Exception:
            continue
    return None


def bridges() -> List[str]:
    return [n for n, _ in BRIDGES]
