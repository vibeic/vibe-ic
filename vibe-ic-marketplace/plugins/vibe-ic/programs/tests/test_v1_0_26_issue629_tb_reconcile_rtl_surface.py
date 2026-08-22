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
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import design_one_shot_runner as P2  # noqa: E402

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


def _seed(tmp_path, l9_ports, rtl_text=None, top="mul_top"):
    """Defect-artifact fixture: seed a project with the given L9.top_ports and
    (optionally) an RTL top, exactly as the round-2 rundir was shaped."""
    proj = tmp_path / "proj"
    gd = P2._pl.generated_docs_dir(proj)
    gd.mkdir(parents=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": top, "top_ports": l9_ports}))
    if rtl_text is not None:
        rtl = P2._pl.rtl_dir(proj)
        rtl.mkdir(parents=True)
        (rtl / f"{top}.v").write_text(rtl_text)
    return proj


def _binding(proj, top="mul_top"):
    body = (P2._pl.sim_full_stack_dir(proj) / f"tb_{top}_full.v").read_text()
    m = re.search(rf"{re.escape(top)} u_dut[\s\S]*?\);", body)
    return m.group(0) if m else ""


# ── (1) the fix: TB binds RTL ports, NOT the L9 parameter ────────────────────

def test_tb_binds_rtl_ports_not_l9_parameter(tmp_path):
    proj = _seed(tmp_path, _L9_CORRUPT, _RTL_DATAPATH)
    res = P2.step_full_stack_tb_gen(proj, "chip_top")
    bind = _binding(proj)
    # real ports recovered ...
    for port in ("clk", "rst", "x", "y", "p"):
        assert f".{port}(" in bind, f"port {port!r} not bound: {bind}"
    # ... and the parameter is NEVER bound as a port
    assert ".size(" not in bind, f"parameter 'size' bound as a port: {bind}"
    # a loud diagnostic points at the upstream L9 extraction
    assert "RECONCILED" in res.detail and "size" in res.detail


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog not on this host")
def test_reconciled_tb_compiles_against_correct_rtl(tmp_path):
    """The end state: the reconciled TB compiles clean against the correct RTL
    — the false 'reference_tb FAIL — real structural defect' is gone."""
    proj = _seed(tmp_path, _L9_CORRUPT, _RTL_DATAPATH)
    P2.step_full_stack_tb_gen(proj, "chip_top")
    tb = P2._pl.sim_full_stack_dir(proj) / "tb_mul_top_full.v"
    rtl = P2._pl.rtl_dir(proj) / "mul_top.v"
    r = subprocess.run(
        ["iverilog", "-g2012", "-o", str(tmp_path / "a.out"),
         str(tb), str(rtl)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


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

def test_non_ansi_rtl_falls_back_to_l9_NOLEAK(tmp_path):
    """A non-ANSI RTL top (bare-name port list, directions in the body) is not
    parseable by the ANSI surface parser → fall back to L9.top_ports verbatim
    (no reconcile, no regression)."""
    l9 = [{"name": "a", "direction": "input"},
          {"name": "z", "direction": "output"}]
    proj = _seed(tmp_path, l9,
                 "module mul_top(a, z);\n input a; output z; assign z=a;\n"
                 "endmodule\n")
    res = P2.step_full_stack_tb_gen(proj, "chip_top")
    bind = _binding(proj)
    assert ".a(" in bind and ".z(" in bind
    assert "RECONCILED" not in res.detail


def test_absent_rtl_falls_back_to_l9_NOLEAK(tmp_path):
    l9 = [{"name": "a", "direction": "input"},
          {"name": "z", "direction": "output"}]
    proj = _seed(tmp_path, l9, rtl_text=None)  # no rtl/ dir
    res = P2.step_full_stack_tb_gen(proj, "chip_top")
    bind = _binding(proj)
    assert ".a(" in bind and ".z(" in bind
    assert "RECONCILED" not in res.detail


def test_l9_matches_rtl_no_reconcile_diagnostic_NOLEAK(tmp_path):
    """When L9 already matches the RTL surface the binding is unchanged and NO
    reconcile diagnostic is emitted (the relaxation only speaks up on a real
    divergence)."""
    l9 = [{"name": "clk", "direction": "input"},
          {"name": "q", "direction": "output"}]
    proj = _seed(tmp_path, l9,
                 "module mul_top (input clk, output q);\n assign q=clk;\n"
                 "endmodule\n")
    res = P2.step_full_stack_tb_gen(proj, "chip_top")
    bind = _binding(proj)
    assert ".clk(" in bind and ".q(" in bind
    assert "RECONCILED" not in res.detail


# ── (3) helper unit ──────────────────────────────────────────────────────────

def test_rtl_top_ports_helper_excludes_parameter(tmp_path):
    proj = _seed(tmp_path, _L9_CORRUPT, _RTL_DATAPATH)
    ports = P2._v629_rtl_top_ports(proj, "mul_top")
    # ORGANIC #643 — the helper now returns (direction, name, width) triples
    # (the width is needed so the TB declares a multi-bit bus at its real
    # width); the name is the 2nd element.
    names = [t[1] for t in ports]
    assert names == ["clk", "rst", "x", "y", "p"]
    assert "size" not in names


def test_rtl_top_ports_helper_parses_non_ansi(tmp_path):
    # ORGANIC #766 — the shared parse_module_ports now falls back to a NON-ANSI
    # body scan, so the helper recovers the real DUT port surface of a non-ANSI
    # top (`module mul_top(a, z); input a; output z;`) instead of returning [].
    # (Before #766 the shared parser dropped every bare header name and this
    # helper returned [] on the entire non-ANSI class — a documented limitation
    # that the #766 fix removes; the TB reconcile now sees the true port list.)
    proj = _seed(tmp_path, _L9_CORRUPT,
                 "module mul_top(a, z);\n input a; output z;\nendmodule\n")
    ports = P2._v629_rtl_top_ports(proj, "mul_top")
    names = [t[1] for t in ports]
    dirs = [t[0] for t in ports]
    assert names == ["a", "z"], ports
    assert dirs == ["input", "output"], ports


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
