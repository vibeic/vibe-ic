#!/usr/bin/env python3
"""port_parser.py — the SHARED interface-port reader for the deterministic solvers.

A spec/prompt states the module interface in one of two forms, and the structural
artifact (truth table / FSM table / K-map) is identical across them — only the port
syntax differs (the VerilogEval-v2 twin uses bullets, the VerilogEval-human twin a
Verilog module header). Solvers that parsed only bullets silently SKIPped every
module-header prompt. This one parser reads BOTH, so a solver fires on either twin.

  (a) bullet:  ` - input  clk`  /  ` - output q (4 bits)`  /  ` - input y (3 bits)`
  (b) header:  `module TopModule ( input clk, input [7:0] d, output reg q );`
               (parsed ONLY inside the module-header parens, so prose like
               "the input signal a" never becomes a phantom port).

Returns (ins, outs) as lists of (name, width:int). chip-AGNOSTIC, pure regex.
"""
from __future__ import annotations
import re
from typing import List, Tuple


def _bullet_ports(text: str) -> Tuple[List, List]:
    ins, outs = [], []
    for m in re.finditer(
        r"^\s*-\s*(input|output)\s+(\w+)(\s*\(\s*(\d+)\s*bits?\s*\))?", text, re.M):
        d, name, _, w = m.groups()
        (ins if d == "input" else outs).append((name, int(w) if w else 1))
    return ins, outs


def _header_ports(text: str) -> Tuple[List, List]:
    m = re.search(r"module\s+\w+\s*(?:#\s*\([^)]*\)\s*)?\((.*?)\)\s*;", text, re.S)
    if not m:
        return [], []
    body = m.group(1)
    ins, outs = [], []
    for pm in re.finditer(
        r"\b(input|output)\b\s+(?:wire|reg|logic)?\s*"
        r"(?:\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*)?(\w+)", body):
        d, hi, lo, name = pm.groups()
        w = abs(int(hi) - int(lo)) + 1 if hi is not None and lo is not None else 1
        (ins if d == "input" else outs).append((name, w))
    return ins, outs


def parse_ports(text: str) -> Tuple[List, List]:
    """(ins, outs) as [(name, width)]. Bullet form wins; else the Verilog header."""
    ins, outs = _bullet_ports(text)
    if ins or outs:
        return ins, outs
    return _header_ports(text)
