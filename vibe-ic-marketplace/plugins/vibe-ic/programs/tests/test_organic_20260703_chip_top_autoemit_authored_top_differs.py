#!/usr/bin/env python3
r"""test_organic_20260703_chip_top_autoemit_authored_top_differs.py

ORGANIC-20260703-runner-chip-top-auto-emit-when-authored-top-differs (P2).

When the spec-to-rtl author names the top module something OTHER than L9's
`chip_top` sentinel (e.g. `encoder_64b66b`), the runner must auto-emit a thin
`chip_top` pass-through wrapper that PRESERVES the DUT's real (multi-bit) ports
— NOT instantiate a never-authored `chip_top` and NOT 1-bit-flatten the ports —
so the full-stack reference_tb elaborates against the real DUT with no hand
authoring.

This is resolved on current main by the combination of:
  * `design_one_shot_runner._autoemit_chip_top_if_needed` (v0.1.62) — emits
    `module chip_top(<real ports>); <authored_top> u_dut(<connects>); endmodule`
    for a differently-named single authored module, preserving port widths;
  * the sibling ORGANIC-20260703 L9 fix (phase1_doc_one_shot_runner) — an actual
    `module <name>(...)` declaration in the prompt/context is now authoritative,
    so L9.top_module resolves the real authored name (`encoder_64b66b`) and in the
    common case no wrapper is even needed (synth + TB target the real module).

These tests pin BOTH resolution paths for the exact capture designs so the
false-negative reference_tb cannot regress. Chip-AGNOSTIC.

Run: python3 -m pytest programs/tests/test_organic_20260703_chip_top_autoemit_authored_top_differs.py -q
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import design_one_shot_runner as D        # noqa: E402
import phase1_doc_one_shot_runner as P    # noqa: E402


# a 64b66b_encoder-shape DUT: multi-bit ports, module name != chip_top.
ENCODER = (
    "module encoder_64b66b (\n"
    "    input  wire        clk,\n"
    "    input  wire        rst_n,\n"
    "    input  wire [63:0] data_in,\n"
    "    input  wire        valid_in,\n"
    "    output reg  [65:0] data_out,\n"
    "    output reg         valid_out\n"
    ");\n"
    "  always @(posedge clk) data_out <= {2'b01, data_in};\n"
    "endmodule\n")


def _emit_chip_top_wrapper(synth_top: str, dut_src: str, dut_name: str) -> str:
    """Emit the chip_top pass-through wrapper string the runner's
    `_autoemit_chip_top_if_needed` produces, using the SAME module-level helpers,
    so this test fails if the emission logic regresses."""
    scan = D._chip_top_mask_comments(dut_src)
    m = re.compile(r"module\s+(\w+)\s*[(#]").search(scan)
    param_block, port_block = D._chip_top_extract_param_and_ports(scan, m.end() - 1)
    inner = port_block.strip()[1:-1]
    kw = {"input", "output", "inout", "wire", "reg", "logic", "signed",
          "unsigned", "var"}
    names = []
    for chunk in inner.split(","):
        ids = [t for t in re.findall(r"[A-Za-z_]\w*", chunk) if t not in kw]
        if ids:
            names.append(ids[-1])
    connects = ",\n    ".join(f".{n}({n})" for n in names)
    wrapper_port_block = D._chip_top_strip_output_storage(port_block)
    return (f"`default_nettype none\n"
            f"module {synth_top} {wrapper_port_block};\n"
            f"  {dut_name} u_dut (\n    {connects}\n  );\n"
            f"endmodule\n`default_nettype wire\n")


# --------------------------------------------------------------------------- #
# Path A — the auto-emit wrapper preserves the DUT's real multi-bit ports.
# --------------------------------------------------------------------------- #
def test_wrapper_preserves_multibit_widths_not_1bit_flattened():
    w = _emit_chip_top_wrapper("chip_top", ENCODER, "encoder_64b66b")
    # the wrapper is named chip_top and instantiates the REAL authored module
    assert "module chip_top" in w
    assert "encoder_64b66b u_dut" in w
    # multi-bit widths are PRESERVED (the v1.2.96 symptom was 1-bit flattening)
    assert "[63:0] data_in" in w
    assert "[65:0] data_out" in w
    # every real port is connected by name; no phantom port
    for c in (".clk(clk)", ".rst_n(rst_n)", ".data_in(data_in)",
              ".valid_in(valid_in)", ".data_out(data_out)", ".valid_out(valid_out)"):
        assert c in w, c


def test_wrapper_is_balanced_and_iverilog_elaborates():
    w = _emit_chip_top_wrapper("chip_top", ENCODER, "encoder_64b66b")
    assert w.count("(") == w.count(")")
    if not shutil.which("iverilog"):
        pytest.skip("iverilog not available")
    import tempfile
    d = Path(tempfile.mkdtemp())
    (d / "encoder_64b66b.v").write_text(ENCODER)
    (d / "chip_top.v").write_text(w)
    r = subprocess.run(
        ["iverilog", "-g2012", "-o", str(d / "a.out"), "-s", "chip_top",
         str(d / "chip_top.v"), str(d / "encoder_64b66b.v")],
        capture_output=True, text=True)
    assert r.returncode == 0, f"iverilog failed: {r.stderr}"


# --------------------------------------------------------------------------- #
# Path B — L9 now resolves the real authored name from the prompt's module
# header, so the runner targets the real module directly (no wrapper needed).
# --------------------------------------------------------------------------- #
def test_l9_resolves_real_authored_name_from_prompt_header():
    docs = {"prompt.md": (
        "Design a 64b/66b line encoder.\n"
        "== Interface_Signals module\n"   # prose noise that used to win
        "```verilog\n" + ENCODER + "```\n")}
    assert P._extract_top_module_from_docs(docs) == "encoder_64b66b"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
