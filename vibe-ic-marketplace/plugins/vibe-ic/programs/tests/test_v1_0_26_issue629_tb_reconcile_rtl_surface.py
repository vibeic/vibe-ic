"""Regression for ORGANIC #629 — step_full_stack_tb_gen builds the DUT
instance from L9.top_ports verbatim instead of reconciling against the parsed
synthesizable RTL surface, so a mis-extracted parameter is bound as a port (and
real ports dropped) → false reference_tb compile FAIL.

現象 (round-2 v1.0.22 6-IC clean-room): for a datapath-multiplier IC whose L9
extraction promoted a width-cell `parameter size` as a port and dropped the
real short ports x/y/p (the #627 upstream defect), step_full_stack_tb_gen
emitted `<top> u_dut (.clk(clk),.rst(rst),.size(size));` with `reg size = 0;`
and omitted x/y/p. iverilog against the CORRECT RTL (declares parameter size +
ports clk/rst/x/y/p) failed "port `size' is not a port of u_dut" (rc=1), and
the reference_tb step reported `reference_tb FAIL — real structural defect` — a
FALSE attribution (the RTL is correct; the defect is the TB generator's port
binding). The chip_top wrapper gen does the opposite (parses the RTL header,
separates parameters from ports) so chip_top.v stayed correct.

Fix: step_full_stack_tb_gen reconciles its DUT binding against the parsed RTL
top surface (reusing reset_clock_variant_alias.parse_module_ports, which reads
the `(...)` port list AFTER the `#(...)` parameter block — a parameter is
structurally excluded). It binds only RTL ports, never a parameter, recovers
dropped ports, and emits a loud diagnostic pointing at the upstream L9
extraction when the two disagree. Falls back to L9.top_ports only when the RTL
top is absent / non-ANSI (no regression).

NEGATIVE no-leak: (a) a non-ANSI RTL top (bare-name port list) falls back to
L9 verbatim; (b) an absent rtl/ falls back to L9; (c) when L9 already matches
the RTL surface the binding is unchanged and NO reconcile diagnostic is emitted.

chip-AGNOSTIC: structural RTL parse; no IC-class / token literals.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))


_HAS_IVERILOG = shutil.which("iverilog") is not None

# correct RTL: parameter `size` in the #() block + ports clk/rst/x/y/p.
_RTL_DATAPATH = (
    "module mul_top #(parameter size = 8) (\n"
    "  input clk, input rst,\n"
    "  input  [size-1:0] x,\n"
    "  input  [size-1:0] y,\n"
    "  output [2*size-1:0] p\n"
    ");\n  assign p = x * y;\nendmodule\n")

# the #627-corrupted L9: width-cell parameter promoted, real ports dropped.
_L9_CORRUPT = [
    {"name": "clk", "direction": "input"},
    {"name": "rst", "direction": "input"},
    {"name": "size", "direction": "input"},
]






# ── (1) the fix: TB binds RTL ports, NOT the L9 parameter ────────────────────





@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog not on this host")
def test_original_l9_only_tb_would_fail_verbatim(tmp_path):
    """Anchors the 現象: a hand-built TB that binds the corrupted L9 verbatim
    (`.size(size)`, omits x/y/p) does NOT compile against the correct RTL — the
    exact defect the reconciliation removes."""
    rtl = tmp_path / "mul_top.v"
    rtl.write_text(_RTL_DATAPATH)
    bad_tb = tmp_path / "bad_tb.v"
    bad_tb.write_text(
        "`timescale 1ns/1ps\nmodule tb;\n reg clk=0; reg rst=0; reg size=0;\n"
        " mul_top u_dut (.clk(clk),.rst(rst),.size(size));\nendmodule\n")
    r = subprocess.run(
        ["iverilog", "-g2012", "-o", str(tmp_path / "bad.out"),
         str(bad_tb), str(rtl)], capture_output=True, text=True)
    assert r.returncode != 0 and "size" in r.stderr


# ── (2) NEGATIVE no-leak ─────────────────────────────────────────────────────







# ── (3) helper unit ──────────────────────────────────────────────────────────





if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
