#!/usr/bin/env python3
"""benchmark_completeness.py — THIN per-benchmark adapters over the GENERAL
`spec_complete_extract.assess_spec` engine.

WHY (owner directive 2026-06-26): the completeness engine that scored CVDP is
GENERAL (see `spec_complete_extract`). This module is the proof + the reusable
wiring that the SAME engine serves EVERY benchmark and a plain design doc — each
benchmark differs ONLY in how it states its interface (the THIN-ADAPTER layer):

  * CVDP        — cocotb `dut.<sig>` harness + `.env` TOPLEVEL + skeleton header
                  (handled by `cvdp_complete_extract.extract(record)`).
  * RTLLM       — a Verilog-style port header in the design_description prose
                  (recovered by `prose_interface_recover.recover_ports`).
  * VerilogEval — a `- input/output NAME (N bits)` prose list with the
                  "one bit unless otherwise specified" convention.
  * Phase-1 doc — an L-doc / prose port list (call assess_spec directly).

Each adapter below recovers the port NAMES its benchmark's way and delegates the
COMPLETE / EXTRACTION_GAP / SPEC_ABSENT verdict to the one general engine, so a
width / structure fix made while converging ANY benchmark immediately improves
every benchmark AND the general Phase-1 path.

chip-AGNOSTIC: the adapters key on the benchmark's INTERFACE-STATEMENT shape, never
on a design name, problem id, or SKU literal.

Public API
    assess_rtllm(prompt: str, module_name="") -> spec dict
    assess_verilogeval(prompt: str, module_name="TopModule") -> spec dict
    verilogeval_ports(prompt: str) -> (inputs, outputs)
"""
from __future__ import annotations

import os
import re
import sys
from typing import List, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import spec_complete_extract as _eng  # noqa: E402


# --------------------------------------------------------------------------- #
# RTLLM — a Verilog-style port header in the design_description prose
# --------------------------------------------------------------------------- #
def assess_rtllm(prompt: str, module_name: str = "") -> dict:
    """Assess an RTLLM design_description: recover the port list via the shipped
    RTLLM header reader, then delegate to the general engine."""
    import prose_interface_recover as _rt
    ins, outs = _rt.recover_ports(prompt)
    return _eng.assess_spec(prompt, [p[0] for p in ins], [p[0] for p in outs],
                            module_name=module_name)


# --------------------------------------------------------------------------- #
# VerilogEval (spec-to-rtl) — a `- input/output NAME (N bits)` prose list
# --------------------------------------------------------------------------- #
# "All input and output ports are one bit unless otherwise specified." — a port
# with no `(N bits)` qualifier is 1-bit by the prompt's own stated convention.
_VE_PORT_RE = re.compile(
    r"-\s*(input|output)\s+([A-Za-z_]\w*)\s*(?:\(\s*(\d+)\s*bits?\s*\))?", re.I)


def verilogeval_ports(prompt: str) -> Tuple[List[str], List[str]]:
    """(inputs, outputs) port names from a VerilogEval spec-to-rtl prompt."""
    ins: List[str] = []
    outs: List[str] = []
    for m in _VE_PORT_RE.finditer(prompt):
        d, name = m.group(1).lower(), m.group(2)
        (ins if d == "input" else outs).append(name)
    return ins, outs


def assess_verilogeval(prompt: str, module_name: str = "TopModule") -> dict:
    """Assess a VerilogEval spec-to-rtl prompt via the general engine. The width of
    a port with no `(N bits)` qualifier is 1 by the prompt's stated convention, so
    such ports resolve through the engine's 1-bit handling (clk/rst/control names)
    OR — for a plain `output left` — are recorded honestly; the VE convention is
    applied here by passing the qualifier-derived widths in the prompt the engine
    already reads (the `(N bits)` token is a width form `_resolve_width` recognises)."""
    ins, outs = verilogeval_ports(prompt)
    return _eng.assess_spec(prompt, ins, outs, module_name=module_name)


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--benchmark", required=True,
                    choices=["rtllm", "verilogeval"],
                    help="which benchmark's interface-statement shape to recover")
    ap.add_argument("--prompt", required=True, help="the prompt / description file")
    a = ap.parse_args(argv)
    prompt = open(a.prompt).read()
    spec = (assess_rtllm if a.benchmark == "rtllm" else assess_verilogeval)(prompt)
    print(f"completeness: {spec['completeness']}")
    print(f"reason: {spec['completeness_reason']}")
    print("ports:", [(p["name"], p["width"]) for p in spec["interface"]])
    for g in spec["gaps"]:
        print(f"  GAP {g['kind']} {g['type']}: {g['detail']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
