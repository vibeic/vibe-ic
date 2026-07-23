#!/usr/bin/env python3
"""cpu_boot_latency_oracle_tb_gen.py — deterministic golden oracle TB
generator for the RESET-TO-FIRST-BUS-ACTIVITY LATENCY test-case shape
(ORGANIC #778 companion — Step-4/L10 CPU-core interface class).

WHAT THIS CLOSES (chip-AGNOSTIC — a CPU-CORE / clocked-core interface-class
convention, never a per-design literal):

`l10_tb_conformance_check` FAILed Step 4 on a `processor_cpu`-class IC (a
RISC-V bit-serial core reused-IP integration) because every one of its L10
`functional_vector` cases lacked TB evidence — `testbench_gen.py` only ships
the universal SUBSTANCE FLOOR (no-X-after-reset) for a case with no
recognised golden, and `arith_oracle_tb_gen` only recognises the CLOSED-FORM
DATAPATH convention (`p = a OP b`). Neither covers an INSTRUCTION-EXECUTION
class case such as: "N cycles after reset release, the design has fetched
its first instruction" (a common CPU-core / any-clocked-core BOOT-LATENCY
requirement in an L7 verification plan).

This module recognises that SHAPE — purely from the L10 case's OWN
stimulus+expected TEXT GRAMMAR (a reset-release reference + a first-
activity reference + an explicit "N cycle" bound) and the DUT's OWN port
surface (a generic bus-activity output — the WISHBONE-family `cyc`/`stb`/
`req`/`valid` vocabulary, standard bus terminology, never a chip literal) —
and emits a REAL, falsifiable TB: hold reset, release it, count clock edges
until the bus-activity output first asserts, and compare that count against
the DESIGN'S OWN declared N-cycle bound. No instruction semantics are
invented; only the design's own declared latency budget and its own
structurally-detected bus-activity signal are used.

§4.05 FAIL-CLOSED — this generator ONLY emits a TB when BOTH:
  1. the case's own text carries the reset-release + first-activity + N-cycle
     grammar (`is_boot_latency_case`), AND
  2. the DUT's own port surface exposes a recognised bus-activity OUTPUT.
Absent either signal, `emit_case_oracle` returns None and the caller keeps
the honest SUBSTANCE-FLOOR scaffold (testbench_gen's ORACLE_NONE stub) — a
case this module cannot ground is NEVER fabricated a golden.

This is NOT specific to any RISC-V core, SERV, or "subservient" — it is a
general reset-to-first-activity LATENCY convention applicable to any clocked
digital core whose L7/L10 doc states a boot/wake latency bound in this shape.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent))
import _path_layout as _pl  # noqa: E402

# ── shape grammar (chip-AGNOSTIC — grammar only, no design/vendor literal) ──
_RE_RESET_RELEASE = re.compile(
    r"reset\s*(?:解除|release|de-?assert)", re.IGNORECASE)
_RE_FIRST_ACTIVITY = re.compile(
    r"(?:第一\s*條|第一個|first)\s*"
    r"(?:instruction|指令|bus\s*access|access|fetch|activity)",
    re.IGNORECASE)
_RE_CYCLE_BOUND = re.compile(r"(\d+)\s*cycle", re.IGNORECASE)

# ── generic Wishbone-family "a transaction is happening" output vocabulary.
# Structural suffix match (word-boundary via `_`/string-end), never a chip
# literal — `cyc`/`stb`/`req`/`valid` are standard bus-protocol terms used
# across countless unrelated IP cores.
_BUS_ACTIVITY_TOKENS = ("cyc", "stb", "strobe", "req", "valid")
_BUS_ACTIVITY_RES = [
    re.compile(rf"(?:^|_){tok}(?:_o)?$", re.IGNORECASE)
    for tok in _BUS_ACTIVITY_TOKENS
]

_CLOCK_RE = re.compile(r"(?:^|_)(?:clk|clock)(?:$|_)", re.IGNORECASE)
_RESET_RE = re.compile(r"(?:^|_)(?:rst|reset|resetn|rstn)(?:$|_)", re.IGNORECASE)
_ACTIVE_LOW_RE = re.compile(r"(?:_n$|n$|_b$|(?:^|_)(?:rstn|resetn)(?:$|_))",
                            re.IGNORECASE)


def is_boot_latency_case(case: dict) -> bool:
    """chip-AGNOSTIC shape detector: True iff this L10 case's OWN
    stimulus+expected text together describe "within N cycles of reset
    release, a first bus/instruction activity occurs" — the boot-latency
    convention. Keyed purely on grammar; never on a case-name literal (a
    design could name this case anything)."""
    text = f"{case.get('stimulus', '')} {case.get('expected', '')}"
    return bool(
        _RE_RESET_RELEASE.search(text)
        and _RE_FIRST_ACTIVITY.search(text)
        and _RE_CYCLE_BOUND.search(text)
    )


def extract_cycle_bound(case: dict) -> Optional[int]:
    """Best-effort N extracted from the case's own declared text. Returns
    None when no positive integer "N cycle" reference is present — the
    caller must then DEFER (never fabricate a bound)."""
    text = f"{case.get('stimulus', '')} {case.get('expected', '')}"
    m = _RE_CYCLE_BOUND.search(text)
    if not m:
        return None
    try:
        n = int(m.group(1))
    except ValueError:
        return None
    return n if n > 0 else None


def _pick_bus_activity_output(outputs: List[Tuple[str, str]]) -> Optional[str]:
    """First DUT OUTPUT port name matching the generic bus-activity
    vocabulary (structural suffix match). None when no such port exists —
    the design's I/O surface gives this generator nothing to observe."""
    for n, _w in outputs:
        if any(p.search(n) for p in _BUS_ACTIVITY_RES):
            return n
    return None


def _pick_clock(inputs: List[Tuple[str, str]]) -> Optional[str]:
    for n, w in inputs:
        if not w and _CLOCK_RE.search(n):
            return n
    return None


def _pick_reset(inputs: List[Tuple[str, str]]) -> Tuple[Optional[str], bool]:
    for n, w in inputs:
        if not w and _RESET_RE.search(n):
            return n, bool(_ACTIVE_LOW_RE.search(n))
    return None, False


def emit_case_oracle_from_ports(
    case: dict,
    dut: str,
    inputs: List[Tuple[str, str]],
    outputs: List[Tuple[str, str]],
    inouts: List[Tuple[str, str]],
) -> Optional[str]:
    """Core, project-I/O-free emitter (unit-testable without a project tree
    or iverilog). Returns the TB source text, or None when this case /
    DUT-surface pair is not a boot-latency oracle this generator can ground
    (fail-closed)."""
    name = case.get("name", "")
    if not is_boot_latency_case(case):
        return None
    bound = extract_cycle_bound(case)
    if bound is None:
        return None
    activity = _pick_bus_activity_output(outputs)
    if activity is None:
        return None
    clk = _pick_clock(inputs)
    if clk is None:
        return None  # no clock to count edges against — cannot ground a
                     # cycle-count oracle
    rst, rst_active_low = _pick_reset(inputs)

    checkable = [(n, w) for n, w in outputs]
    margin = bound + 2  # a couple of extra edges of slack before declaring
                        # "never observed" — avoids an off-by-one false FAIL
                        # right at the boundary while still bounding the loop

    lines: List[str] = []
    lines.append(f"// Auto-generated CPU-core BOOT-LATENCY oracle TB for case={name}")
    lines.append("// kind=functional_vector (reset-to-first-bus-activity latency)")
    lines.append(f"// stimulus: {case.get('stimulus', '')}")
    lines.append(f"// expected: {case.get('expected', '')}")
    lines.append("//")
    lines.append(f"// REAL ORACLE (ORGANIC #778 companion, cpu_boot_latency_oracle_tb_gen):")
    lines.append(f"// the design's OWN declared text states the first bus-activity")
    lines.append(f"// ('{activity}') must assert within {bound} clock cycle(s) of reset")
    lines.append(f"// release. This TB counts clock edges from reset release and FAILs")
    lines.append(f"// if '{activity}' never asserts within the measurement window, or")
    lines.append(f"// asserts later than the declared bound. No instruction semantics")
    lines.append(f"// are invented — only the design's own declared N-cycle bound and")
    lines.append(f"// its own structurally-detected bus-activity output are used.")
    lines.append("`timescale 1ns/1ps")
    lines.append(f"module {name};")
    for n, w in inputs:
        lines.append(f"  reg {w + ' ' if w else ''}{n} = 0;")
    for n, w in outputs:
        lines.append(f"  wire {w + ' ' if w else ''}{n};")
    for n, w in inouts:
        lines.append(f"  wire {w + ' ' if w else ''}{n};")
    lines.append("  integer errors = 0;")
    lines.append("  integer _cycle_i;")
    lines.append("  integer _first_activity_cycle;")
    lines.append("")
    conns = ", ".join(f".{n}({n})" for n, _w in (inputs + outputs + inouts))
    lines.append(f"  {dut} u_dut ({conns});")
    lines.append("")
    lines.append(f"  always #5 {clk} = ~{clk};")
    lines.append("")
    lines.append("  initial begin")
    lines.append(
        f'    $display("[TB {name}] BEGIN — reset-to-first-bus-activity '
        f'latency oracle (max_cycles={bound})");'
    )
    if rst:
        asserted, released = ("0", "1") if rst_active_low else ("1", "0")
        lines.append(f"    {rst} = 1'b{asserted};")
        lines.append(f"    #100 {rst} = 1'b{released};")
    else:
        lines.append("    #100;   // no reset port on this DUT surface")
    lines.append("    _first_activity_cycle = -1;")
    lines.append(f"    for (_cycle_i = 1; _cycle_i <= {margin}; "
                 f"_cycle_i = _cycle_i + 1) begin")
    lines.append(f"      @(posedge {clk});")
    lines.append(f"      if (({activity}) === 1'b1 && _first_activity_cycle < 0)")
    lines.append(f"        _first_activity_cycle = _cycle_i;")
    lines.append("    end")
    lines.append("    if (_first_activity_cycle < 0) begin")
    lines.append("      errors = errors + 1;")
    lines.append(
        f'      $display("[TB {name}] FAIL: no bus-activity (\'{activity}\') '
        f'observed within %0d cycles of reset release", {margin});'
    )
    lines.append(f"    end else if (_first_activity_cycle > {bound}) begin")
    lines.append("      errors = errors + 1;")
    lines.append(
        f'      $display("[TB {name}] FAIL: first bus-activity (\'{activity}\') '
        f'at cycle %0d exceeds the design-declared max %0d", '
        f'_first_activity_cycle, {bound});'
    )
    lines.append("    end")
    lines.append("    if (errors != 0) begin")
    lines.append(f'      $display("[TB {name}] FAIL — %0d check(s) failed", errors);')
    lines.append("      $fatal(1);")
    lines.append("    end")
    lines.append(
        f'    $display("[TB {name}] PASS — first bus-activity (\'{activity}\') '
        f'observed at cycle %0d (<= design-declared max %0d)", '
        f'_first_activity_cycle, {bound});'
    )
    lines.append("    $finish;")
    lines.append("  end")
    lines.append("endmodule")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# Standalone/CLI path — independent DUT resolution (mirrors arith_oracle_tb_gen
# so this generator is usable/testable outside testbench_gen's own pipeline).
# --------------------------------------------------------------------------
def _load_case(project: Path, case_name: str) -> Optional[dict]:
    l10_path = _pl.generated_docs_dir(project) / "L10_TEST_CASES.json"
    if not l10_path.is_file():
        return None
    try:
        l10 = json.loads(l10_path.read_text())
    except Exception:
        return None
    cases = l10.get("test_cases") or l10.get("cases") or []
    for c in cases:
        if isinstance(c, dict) and c.get("name") == case_name:
            return c
    return None


def emit_case_oracle(project: Path, case_name: str, top: str = "chip_top"
                     ) -> Optional[str]:
    """Project-level convenience wrapper: resolve the case + DUT from the
    project tree (reusing testbench_gen's own DUT-resolution logic so the
    port surface always matches what the runner compiles against), then
    delegate to the pure emitter."""
    case = _load_case(project, case_name)
    if case is None:
        return None
    try:
        import testbench_gen as _tbg  # type: ignore
    except Exception:
        return None
    dut_module, ports, _reason = _tbg.resolve_dut(project, top)
    if dut_module is None:
        return None
    inputs, outputs, inouts = _tbg._classify(ports)
    return emit_case_oracle_from_ports(case, dut_module, inputs, outputs, inouts)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project", type=Path)
    ap.add_argument("--case", required=True, help="L10 case name")
    ap.add_argument("--top", default="chip_top")
    args = ap.parse_args(argv)
    text = emit_case_oracle(args.project.resolve(), args.case, args.top)
    if text is None:
        print(f"DEFER — {args.case!r} is not a groundable boot-latency oracle")
        return 2
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
