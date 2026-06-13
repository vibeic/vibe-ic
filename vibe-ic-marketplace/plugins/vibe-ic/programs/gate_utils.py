"""gate_utils.py — Shared helpers for v0.117+ structural-RTL gates.

Centralises the file-discovery / module-parsing primitives that were
previously copy-pasted across BACKLOG-v11 P0.1-P0.6 gates
(protocol_fsm_topology, clock_divider_period, cross_module_1cycle_handshake,
frame_end_detection, crc_oracle_vector, arbiter_starvation).

Public API:
    EXCLUDED_DIRS                  frozenset[str] — build/sim dirs to skip
    read_text(path) -> str         tolerant file read (errors='replace')
    find_rtl_files(project) -> list[Path]
    find_modules(rtl) -> list[ModuleSpan]
    parse_io_ports(header) -> (inputs, outputs, inouts)

`find_modules` uses paren-balance — handles multi-line port lists with
nested brackets (e.g., `output logic [WIDTH-1:0]`). Replaces the
fragile `[\\s\\S]*?\\)` regex used in v0.117 release.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

EXCLUDED_DIRS: frozenset[str] = frozenset({
    "db", "incremental_db", "output_files", "build", "sim", "synth",
    "formal", "dft", "pnr", "gds", "reports", ".git", "__pycache__",
    "node_modules",
})


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def find_rtl_files(project: Path) -> list[Path]:
    out: list[Path] = []
    for ext in ("*.v", "*.sv"):
        for f in project.rglob(ext):
            if not f.is_file():
                continue
            parts = set(f.relative_to(project).parts[:-1])
            if parts & EXCLUDED_DIRS:
                continue
            out.append(f)
    return out


@dataclass
class ModuleSpan:
    name: str
    header: str       # text inside `module name(...)` parens
    body: str         # text from `module` keyword through matching `endmodule`
    start: int        # offset in source where `module` keyword starts
    end: int          # offset just past `endmodule`


_MODULE_KW_RE = re.compile(r"^\s*module\s+(\w+)\b", re.MULTILINE)


def find_modules(rtl: str) -> list[ModuleSpan]:
    """Return every module in `rtl` with header (paren-balanced) and body
    (through matching `endmodule`).

    Uses depth counting for `(` `)` so multi-line port lists with
    `[WIDTH-1:0]` brackets parse correctly. The body span runs from the
    `module` keyword through the next `endmodule` (no nested-module
    support — Verilog doesn't allow nested module definitions anyway).
    """
    spans: list[ModuleSpan] = []
    for m in _MODULE_KW_RE.finditer(rtl):
        name = m.group(1)
        # Find opening `(` of port list. Skip optional `#( ... )` parameter
        # port list first.
        i = m.end()
        # Skip whitespace
        while i < len(rtl) and rtl[i] in " \t\n\r":
            i += 1
        # If we hit `#(` paramater list, balance through it then continue
        if i < len(rtl) and rtl[i] == "#":
            i += 1
            while i < len(rtl) and rtl[i] in " \t\n\r":
                i += 1
            if i < len(rtl) and rtl[i] == "(":
                depth = 1
                i += 1
                while i < len(rtl) and depth:
                    if rtl[i] == "(":
                        depth += 1
                    elif rtl[i] == ")":
                        depth -= 1
                    i += 1
        # Now find port-list `(`
        while i < len(rtl) and rtl[i] != "(":
            if rtl[i] == ";":
                break
            i += 1
        if i >= len(rtl) or rtl[i] != "(":
            continue
        header_start = i + 1
        depth = 1
        j = header_start
        while j < len(rtl) and depth:
            c = rtl[j]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            j += 1
        if depth:
            continue  # unbalanced — skip
        header = rtl[header_start:j - 1]
        # Find matching endmodule
        end_m = re.search(r"\bendmodule\b", rtl[j:])
        if not end_m:
            continue
        body_end = j + end_m.end()
        spans.append(ModuleSpan(
            name=name,
            header=header,
            body=rtl[m.start():body_end],
            start=m.start(),
            end=body_end,
        ))
    return spans


_PORT_DECL_RE = re.compile(
    r"\b(input|output|inout)\b"
    r"(?:\s+(?:logic|wire|reg|tri|bit))*"
    r"(?:\s*signed)?"
    r"(?:\s*\[[^\]]+\])*"
    r"\s+(\w+)",
)


def parse_io_ports(header: str) -> tuple[set[str], set[str], set[str]]:
    """Return (inputs, outputs, inouts) parsed from a module port header.

    Handles ANSI-style port declarations:
        input  logic        clk
        output logic [7:0]  data
        inout  wire  signed [WIDTH-1:0]  bus
    """
    inputs: set[str] = set()
    outputs: set[str] = set()
    inouts: set[str] = set()
    for kind, name in _PORT_DECL_RE.findall(header):
        if kind == "input":
            inputs.add(name)
        elif kind == "output":
            outputs.add(name)
        elif kind == "inout":
            inouts.add(name)
    return inputs, outputs, inouts


def module_body(rtl: str, name: str) -> str:
    """Return the body span of module `name`, or empty string if not found."""
    for spec in find_modules(rtl):
        if spec.name == name:
            return spec.body
    return ""
