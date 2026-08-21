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

# `steps` and `oracle_run` are the two names this set was missing relative to
# `rtl_scan_scope.EXCLUDED_DIR_NAMES`, the tree's other RTL-scope contract.
#
# `steps/` is the flow's own PUBLICATION VIEW: `step_canonicalize_artefacts`
# re-publishes each stage's output under a directory named for the flow STEP,
# so the same emitted gate-level netlist appears there under two different step
# names. `synth` is already excluded here, but the publication view does not
# contain the token `synth` in its path, so the entry never matched and the
# netlist was read anyway — twice.
#
# MEASURED, edge_llm_accel x nangate45, the three collectors run over the SAME
# project at the SAME moment (imported from disk and executed, not read):
#
#     rtl_scan_scope.authoritative_rtl_files      6 files       51,587 bytes
#     gate_utils.find_rtl_files                  11 files  696,685,033 bytes
#     dispatch_..._check.collect_files           35 files  1,735,802,924 bytes
#
# 696 MB of the 696.7 MB here is ONE 348 MB netlist counted twice, via
# `steps/phase2/stage2/9_synthesis_yosys_mapped_netlist/netlist.v` and
# `steps/phase2/stage2/14_synthesis_handoff_gate_pre_pnr_yosys_script_netl/netlist.v`
# — a factor of 13,506 over the authoritative scope. Three gates driven by this
# collector TIMED OUT under the phase-2 umbrella's per-gate budget, the umbrella
# FAILed, and the flow halted at phase 2 before place-and-route ever started.
#
# `input` is deliberately NOT added. `rtl_scan_scope` excludes it because staged
# vendor/PDK enablement is not the design's authoritative RTL; these lint gates
# legitimately want to see a staged macro stub, and it is small. Adding it would
# be a silent coverage change, not a performance fix. The two names added here
# are exactly the ones whose contents are the flow's OWN output.
EXCLUDED_DIRS: frozenset[str] = frozenset({
    "db", "incremental_db", "output_files", "build", "sim", "synth",
    "formal", "dft", "pnr", "gds", "reports", ".git", "__pycache__",
    "node_modules", "steps", "oracle_run",
})

#: Directory components excluded by SUFFIX rather than by exact name, imported
#: from the shared scan-scope policy so the two collectors that read this module
#: cannot drift from it. Currently the `<rtl_dir>_out_of_cone/` sidecar that
#: `rtl_transitive_cone.prune_to_cone` moves non-build sources into: a file in
#: there has been declared NOT PART OF THE BUILD SET, so linting it as
#: authoritative RTL contradicts the move (vibe-ic#781 L8).
try:
    from rtl_scan_scope import EXCLUDED_DIR_SUFFIXES
except ImportError:      # pragma: no cover — standalone/vendored use
    EXCLUDED_DIR_SUFFIXES = ("_out_of_cone",)


def dir_parts_excluded(parts) -> bool:
    """True when any DIRECTORY component of a path marks it out of RTL scope.

    The one place the exact-name set and the suffix rule are combined. Three
    collectors with three different policies is how the `steps` defect survived
    the fix that added it to only one of them; there is no fourth private copy.
    """
    parts = list(parts)
    if set(parts) & EXCLUDED_DIRS:
        return True
    return any(p.endswith(s) for p in parts for s in EXCLUDED_DIR_SUFFIXES)


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
            if dir_parts_excluded(f.relative_to(project).parts[:-1]):
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
