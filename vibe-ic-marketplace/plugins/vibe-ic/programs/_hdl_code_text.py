#!/usr/bin/env python3
"""One OFFSET-PRESERVING blanker for HDL comments and string literals.

WHY THIS MODULE EXISTS
======================
`// This module controls the round counter` matches `\\bmodule\\s+(\\w+)` and
mints a module that does not exist. `hdl_declaration_scan_strips_comments_check`
(vibe-ic#731) reads the DATAFLOW into every declaration scan and blocks on a new
call site that scans text no stripper touched; the defect it was written from is
measured — 24 phantom modules across one cell's staged RTL (#729).

Three call sites reached that gate together and none of them could use the
delete-style stripper this tree already had:

  * `_runner_measurement._verilog_netlist`   — the `module` tell that decides
    whether a file is a Verilog netlist at all, read out of a bounded prefix.
  * `benchmark_io_adapter.cvdp_package_response` — packages the EXACT accepted
    RTL bytes for CVDP's scorer, sliced by `match.span()`.
  * `design_one_shot_runner._v1956_dut_instance_conns` — walks parentheses from
    a match offset to find the DUT connection list.

THE OFFSETS ARE THE POINT, AND THEY ARE WHY THIS IS NOT
`_design_module_set.strip_comments`
====================================================================
That function DELETES its comments, and says so: "the caller uses the result for
name scanning, so exact offsets do not matter". For two of the three sites above
they matter completely. A span taken from deleted-comment text indexes the wrong
bytes of the original, so `cvdp_package_response` would ship RTL cut at a
shifted offset — a worse defect than the one being fixed, and a silent one. So
this module BLANKS: every non-code character becomes a space, newlines are kept,
and `len(blank(t)) == len(t)` for every `t`. A caller may scan the blanked text
and slice the ORIGINAL with the same offsets.

The two functions are therefore not duplicates of one another; they answer
different questions and only one of them can be indexed back. Neither delegates
to the other, because making the delete-style one blank would change the BODIES
`module_bodies_in_text` returns to every one of its consumers, which is a
measurement this change did not make.

STRINGS TOO, AND IN ONE ALTERNATION
===================================
A Verilog string literal mints declarations exactly as a comment does —
`$display("module %s", n)` carries `module ` in code the scanner would read.
Blanking comments and strings in ONE left-to-right alternation is what makes the
nesting come out right without a second pass deciding which won: at any offset
the earliest opener wins and consumes the rest, so a `//` inside a string is not
a comment and a `"` inside a comment is not a string opener. Two sequential
passes get exactly those two cases backwards.

HONEST LIMITS, both in the direction of leaving code alone
----------------------------------------------------------
  * An UNTERMINATED block comment (`/*` with no `*/`) or an unterminated string
    is left as-is. Blanking to end-of-file on an unclosed opener would let one
    stray `/*` erase a whole design, and a scanner that reads a little too much
    is recoverable where one that reads nothing is not.
  * Verilog's `\\`-escaped identifiers may contain `/` and `"`; an escaped
    identifier ends at whitespace, so `\\a/*b` is one identifier and this module
    reads its `/*` as a block-comment opener. Measured on this tree: no staged
    source uses one. Named here rather than handled, because the handling would
    need a real lexer and the failure mode is the recoverable direction above.

chip-AGNOSTIC: HDL lexical structure only. No design, PDK or vendor literal.
"""
from __future__ import annotations

import re

__all__ = ["HDL_NONCODE_RE", "strip_hdl_comments_and_strings"]

#: The three non-code spans, in ONE alternation — see the docstring. Order
#: inside the alternation only decides ties at the SAME offset (there are none:
#: `//`, `/*` and `"` cannot all start at one character), so what makes the
#: nesting right is that `re.sub` scans left to right and each match consumes
#: its whole span.
HDL_NONCODE_RE = re.compile(
    r"//[^\n]*"                       # line comment, to end of line
    r"|/\*.*?\*/"                     # block comment (DOTALL, non-greedy)
    r"|\"(?:[^\"\\\n]|\\.)*\"",       # string literal, with escapes
    re.DOTALL,
)


def _blank(match: "re.Match[str]") -> str:
    """The matched span, every character replaced by a space, newlines kept.

    Keeping the newlines keeps LINE NUMBERS as well as offsets: a caller that
    reports `text.count("\\n", 0, match.start())` gets the same line it would
    have got from the original.
    """
    span = match.group(0)
    if "\n" not in span:
        return " " * len(span)
    return "".join("\n" if ch == "\n" else " " for ch in span)


def strip_hdl_comments_and_strings(text: str) -> str:
    """``text`` with comments and string literals BLANKED, offsets preserved.

    ``len(result) == len(text)`` and ``result[i]`` is either ``text[i]`` or a
    space (or the newline it already was), so ``result`` may be scanned and
    ``text`` sliced with the same indices.
    """
    return HDL_NONCODE_RE.sub(_blank, text)
