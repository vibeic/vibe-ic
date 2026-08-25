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


def _already_parses(text: str) -> bool:
    """Does `port_parser` already read a BOTH-SIDED interface out of the raw
    text? If so, no reader may touch it.

    THE MEASURED REASON THIS GUARD EXISTS. Every reader here PREPENDS a bullet
    block, and `parse_ports` reads the first interface it finds. When the raw
    prose already parses, a prepended block does not add to it — it SHADOWS it.
    Measured over 302 real CVDP prompts without this guard: 13 gained and 13
    LOST, e.g. a converter prompt going from 4 in / 1 out to 1 in / 0 out. The
    aggregate was identical either way (217 both times), so the regression was
    invisible in the total and only a per-record diff found it.

    A bridge exists to make an UNPARSEABLE form parseable. Handing it a form
    that already parses can only make things worse, so it is refused."""
    try:
        import port_parser as _pp                        # noqa: PLC0415
        ins, outs = _pp.parse_ports(text)
        return bool(ins) and bool(outs)
    except Exception:
        return False


def bridge(text: str) -> str:
    """Prose in, prose out, with a parseable interface block prepended if any
    reader recognised one. Unchanged when none did, and unchanged when the raw
    text already yields a both-sided parse — see `_already_parses`."""
    if not (text or "").strip():
        return text
    if _already_parses(text):
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
