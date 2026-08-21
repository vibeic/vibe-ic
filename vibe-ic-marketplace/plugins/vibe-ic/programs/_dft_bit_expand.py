#!/usr/bin/env python3
"""_dft_bit_expand.py — bit-level elaboration of a cut netlist's continuous
assignments, so the AU classifier sees per-bit connectivity (#603 item 2).

WHY THIS EXISTS
===============
`atpg_untestable_fault_classify` models a continuous assignment as ONE edge
between whole-bus nets: ``assign \\mprj.la_data_in = la_data_in`` becomes a
single ``la_data_in -> \\mprj.la_data_in`` edge. That is enough to keep the
backward-observability closure connected, but it cannot tell
``la_data_in[100]`` (a fault site the counter never reads) from
``la_data_in[58]`` (a fault site it does): both collapse into the base name
``la_data_in``. On a design whose pad frame is far wider than its core — the
whole point of vibe-ic#603 — that is exactly the distinction that decides which
frame faults are ATPG-untestable.

This module expands each assignment into per-BIT identity gates so the classifier
resolves ``la_data_in[100]`` as unobservable (it reaches no gate) while
``la_data_in[58]`` stays observable (it feeds the counter). A constant / don't-
care source bit (``2'hx``, ``22'hxxxxxx``, ``1'b0``) is modelled as a synthetic
CONSTANT DRIVER, so the classifier's existing uncontrollable-propagation marks a
port bit driven only by constants (an unused output frame bit) uncontrollable.

SOUNDNESS — every fallback errs toward NOT excluding
====================================================
A false PASS (marking a testable fault untestable) is the failure mode this
whole feature guards against. So any assignment this module cannot elaborate
bit-exactly is kept as the classifier's original WHOLE-BUS edge — never dropped.
Dropping an edge could isolate a net that is actually connected and make a
testable fault read untestable; keeping the coarse edge only leaves the number
conservative. ``expand_assignments`` counts the assignments it fell back on
(``opaque``) so a consumer can audit how much of the netlist was elaborated
exactly vs. kept coarse.

chip-AGNOSTIC: Verilog-2001 structural forms only (bus, part-select, concat,
replication, sized/based constants). No PDK, vendor or design name appears.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

# A cell master with NO input pin — the classifier's `constant_cells()` treats
# any such master as a tie source. Registered by the caller in the liberty
# direction table exactly like the synthetic identity master.
CONST_DRIVER_CELL = "__const_drv__"

_WIDTH_RE = re.compile(
    r'^\s*(?:input|output|inout|wire|reg)\s+'
    r'(?:\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*)?'
    r'(\\?[^\s;,]+)\s*;', re.M)
_ASSIGN_RE = re.compile(r'^\s*assign\s+([^=]+?)\s*=\s*(.+?);\s*$', re.M)
_PARTSEL_RE = re.compile(r'^(.*?)\s*\[\s*(\d+)\s*:\s*(\d+)\s*\]$')
_BITSEL_RE = re.compile(r'^(.*?)\s*\[\s*(\d+)\s*\]$')
_CONST_RE = re.compile(r"^\d+'[bBoOdDhH][0-9a-fA-FxXzZ_]+$|^\d+$")
_REPL_RE = re.compile(r'^(\d+)\s*\{(.*)\}$', re.S)
_IDENT_RE = re.compile(r'\\[^\s,{}]+|[A-Za-z_][\w$]*(?:\s*\[[^\]]*\])?')


def parse_widths(text: str) -> Dict[str, Tuple[int, int]]:
    """``{net_base: (hi, lo)}`` from wire/port declarations. A scalar declares
    (0, 0)."""
    out: Dict[str, Tuple[int, int]] = {}
    for m in _WIDTH_RE.finditer(text):
        hi, lo, nm = m.group(1), m.group(2), m.group(3).strip().lstrip("\\").rstrip()
        out[nm] = (int(hi), int(lo)) if hi is not None else (0, 0)
    return out


def _const_width(tok: str) -> int:
    m = re.match(r"^(\d+)'", tok)
    return int(m.group(1)) if m else 1


def lhs_bits(name: str, widths: Dict[str, Tuple[int, int]]) -> Optional[List[str]]:
    """Ordered MSB→LSB bit names for an assignment LHS, or None if the width is
    unknown (an un-declared bare bus — kept coarse by the caller)."""
    name = name.strip().lstrip("\\").rstrip()
    m = _PARTSEL_RE.match(name)
    if m:
        b, h, l = m.group(1).strip(), int(m.group(2)), int(m.group(3))
        rng = range(h, l - 1, -1) if h >= l else range(h, l + 1)
        return [f"{b}[{i}]" for i in rng]
    m = _BITSEL_RE.match(name)
    if m:
        return [f"{m.group(1).strip()}[{m.group(2)}]"]
    w = widths.get(name)
    if w is not None and w != (0, 0):
        h, l = w
        return [f"{name}[{i}]" for i in range(h, l - 1, -1)]
    if w == (0, 0):
        return [name]
    return None


def rhs_bits(expr: str, widths: Dict[str, Tuple[int, int]]) -> Optional[List[str]]:
    """Ordered MSB→LSB source-bit names for an assignment RHS. A constant /
    don't-care bit is the sentinel ``None`` inside the list (the caller models
    it as a constant driver). Returns None for the WHOLE expr if any part cannot
    be elaborated bit-exactly (the caller then keeps the coarse edge)."""
    expr = expr.strip()
    if expr.startswith("{") and expr.endswith("}"):
        out: List[Optional[str]] = []
        for part in _split_top_commas(expr[1:-1]):
            part = part.strip()
            rr = _REPL_RE.match(part)
            if rr:
                sub = rhs_bits(rr.group(2).strip(), widths)
                if sub is None:
                    return None
                out += sub * int(rr.group(1))
                continue
            sub = rhs_bits(part, widths)
            if sub is None:
                return None
            out += sub
        return out
    if _CONST_RE.match(expr):
        return [None] * _const_width(expr)
    return lhs_bits(expr, widths)


def _split_top_commas(s: str) -> List[str]:
    out: List[str] = []
    depth = 0
    cur = ""
    for ch in s:
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur)
    return out


def _coarse_edge(lhs: str, rhs: str, assign_cell: str, tag: str) -> Tuple[str, str, dict]:
    """The classifier's original whole-bus modelling of one assignment: rhs
    identifiers drive lhs. Used verbatim as the sound fallback."""
    conns = {"Y": lhs.strip().lstrip("\\").rstrip()}
    srcs = [x.strip().lstrip("\\").rstrip() for x in _IDENT_RE.findall(rhs)
            if x.strip() and not x.strip().isdigit()]
    for k, s in enumerate(srcs):
        conns[f"A{k}"] = s
    return (assign_cell, f"__op_{tag}", conns)


def expand_assignments(text: str, widths: Dict[str, Tuple[int, int]],
                       assign_cell: str) -> Tuple[List[tuple], int]:
    """Return (extra_instances, opaque_count).

    ``extra_instances`` is the per-bit identity gates + constant drivers that
    REPLACE the classifier's whole-bus assign instances. ``opaque_count`` is the
    number of assignments kept as a coarse whole-bus edge because they could not
    be elaborated bit-exactly.
    """
    extra: List[tuple] = []
    opaque = 0
    idx = 0
    for m in _ASSIGN_RE.finditer(text):
        lhs_txt, rhs_txt = m.group(1), m.group(2)
        lb = lhs_bits(lhs_txt, widths)
        rb = rhs_bits(rhs_txt, widths) if lb is not None else None
        if lb is None or rb is None or len(lb) != len(rb):
            opaque += 1
            extra.append(_coarse_edge(lhs_txt, rhs_txt, assign_cell, str(idx)))
            idx += 1
            continue
        for d, s in zip(lb, rb):
            if s is None:  # constant / don't-care source → constant driver
                extra.append((CONST_DRIVER_CELL, f"__cd_{idx}", {"Y": d}))
            else:
                extra.append((assign_cell, f"__ba_{idx}", {"Y": d, "A0": s}))
            idx += 1
    return extra, opaque
