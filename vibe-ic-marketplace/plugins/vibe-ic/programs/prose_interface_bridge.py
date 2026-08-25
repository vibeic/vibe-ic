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

import re
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


# A port name the PROSE ITSELF delimits: a backticked span (`data_in`,
# `input [7:0] num_in`, `q ([3:0])`) or a `[hi:lo] name` range-prefix bullet.
_BACKTICK_SPAN_RE = re.compile(r"`([^`\n]+)`")
_LEAD_RANGE_NAME_RE = re.compile(
    r"^\s*[-*]\s*\[\s*\d+\s*:\s*\d+\s*\]\s*([A-Za-z_]\w*)", re.M)
_DIR_LEAD_RE = re.compile(r"^\s*(?:input|output|inout)\b\s*", re.I)
_NAME_RE = re.compile(r"\s*(?:\[\s*\d+\s*:\s*\d+\s*\]\s*)?([A-Za-z_]\w*)")


def _delimited_names(text: str) -> frozenset:
    """Every identifier this prose DELIMITS as a port token — backticked, or
    carrying a leading `[hi:lo]` range, or declared in a Verilog module header.

    WHY THE COST CHECK NEEDS THIS. `port_parser`'s bullet reader takes the first
    word of a prose bullet as a port name, so on a real spec it reads ports
    called `When`, `Enables`, `Signals`, `Wishbone`, `Initializes` — the opening
    words of description sentences. The readers in this chain do NOT: each one
    keys on a delimited token precisely so a sentence is never mistaken for a
    port (§4.05, and see `prose_interface_bridge_md._port_name`).

    So the two disagree in BOTH directions, and a cost check that defended every
    name the raw parse produced would defend the fabrications too — refusing a
    reader whose only "loss" was declining to invent a port. MEASURED over the
    302-record CVDP corpus: defending everything refuses 8 readers, 2 of which
    dropped nothing but fabricated names. Defending only what the prose delimits
    separates the two cases without either reader having to be trusted wholesale.
    """
    names = set()
    for span in _BACKTICK_SPAN_RE.findall(text):
        m = _NAME_RE.match(_DIR_LEAD_RE.sub("", span))
        if m:
            names.add(m.group(1))
    names.update(_LEAD_RANGE_NAME_RE.findall(text))
    try:
        import port_parser as _pp
        h_ins, h_outs = _pp._header_ports(text)          # a Verilog module header
        names.update(n for n, _w in list(h_ins) + list(h_outs))
    except Exception:                                    # pragma: no cover
        pass
    return frozenset(names)


def _reads(text: str, defend: frozenset):
    """Which delimited port NAMES the shared parser reads from `text` today.
    This is the yardstick a bridge is judged by, because `parse_ports` is the
    only thing a bridged text is ever fed to.

    NAMES, not (name, width), and not per-direction — the comparison is
    deliberately narrowed to the one property that was violated. The raw bullet
    reader is not authoritative about the other two and the corpus says so: it
    reads `i_temp_feedback` six times, reads `field` at BOTH 1 and 16 bits from
    one spec, and reads `data` as an input AND an output because the prose
    mentions `data[31:16]` in a sentence. Widths and directions are the very
    things these readers exist to settle; a guard that froze the raw reader's
    answer to them would be defending the weaker reading, which is the mistake
    it was written to stop, pointed the other way."""
    try:
        import port_parser as _pp
        ins, outs = _pp.parse_ports(text)
    except Exception:                                    # pragma: no cover
        return None
    return frozenset(n for n, _w in list(ins) + list(outs) if n in defend)


def _claim(text: str):
    """(reader-name, bridged-text) for the first reader that recognises `text`
    without COSTING it a port, or (None, text) when no reader qualifies.

    WHY THE COST CHECK. "Each reader is a no-op on text it does not recognise"
    made trying them in sequence look safe by construction, and it is not: a
    reader can recognise a text PARTIALLY. `parse_ports` documents "bullet form
    wins", so the block a reader prepends does not merge with what the prose
    already said — it REPLACES it. A reader that reads three of a spec's four
    ports therefore hands the caller a spec with one port deleted, and the
    deletion is invisible because the reader did exactly what it promised.

    MEASURED on the grouped-bullet form:

        ### Inputs:
        - i_fb [5:0]: ...            <- range AFTER the name: md reader drops it
        **Heating Control (1-bit each)**
        - `o_heat_hi`                <- width in the GROUP header: dropped
        - `o_state [2:0]`            <- kept

    `parse_ports` reads all four ports out of that prose unaided. The
    markdown-table reader recognises one of them, prepends `- output o_state
    (3 bits)`, and the parse collapses to that single port. The reader is not
    wrong to be conservative — §4.05 forbids it fabricating the two widths the
    prose states only in a group header — but the CHAIN is wrong to prefer a
    partial reading over a complete one that already existed.

    So a reader claims a text only if everything the parser already read
    survives. It may ADD ports and it may not SUBTRACT any; a reader that would
    subtract is skipped and the next one tried, exactly as if it had not
    recognised the text at all.
    """
    defend = _delimited_names(text)
    before = _reads(text, defend)
    for name, fn in BRIDGES:
        try:
            out = fn(text)
        except Exception:
            continue
        if not out or out == text:
            continue
        if before is not None:                # empty <= anything, so a text the
            after = _reads(out, defend)       # parser reads nothing from is free
            if after is None or not before <= after:
                continue                     # lossy: keep the better parse we have
        return name, out
    return None, text


def bridge(text: str) -> str:
    """Prose in, prose out, with a parseable interface block prepended if any
    reader recognised one. Unchanged when none did — and unchanged when the only
    readers that recognise it would read LESS than the prose already yields
    (see `_claim`)."""
    if not (text or "").strip():
        return text
    return _claim(text)[1]


def which_bridged(text: str) -> str | None:
    """Which reader claims this text, or None. For callers that need to say.

    Reads through the same `_claim` as `bridge`, so a reader this names is
    always the reader `bridge` actually applied — a reader skipped for being
    lossy is not "the one that claims the text"."""
    if not (text or "").strip():
        return None
    return _claim(text)[0]


def bridges() -> List[str]:
    return [n for n, _ in BRIDGES]
