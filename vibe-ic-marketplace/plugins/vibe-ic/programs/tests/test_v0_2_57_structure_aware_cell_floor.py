"""v0.2.57 structure-aware cell-floor regressions.

Pins the #427 fix (ORGANIC-20260606-min-cells-floor-tiny-designs): the flat
min_cells=10 ERROR false-positived on legitimately tiny correct designs
(an 8-DFF shifter, a 3-cell pulse FSM, a 5-cell edge detector) — a retry
cannot grow a correct design, so the FAIL was unactionable noise. New
resolution order in `synth_netlist_check`:
  (a) PASS when sequential cells >= the RTL's declared register bits
      (TINY_DESIGN_VOUCHED INFO);
  (b) zero cells / outputs tied constant stay hard ERRORs (real stubs);
  (c) otherwise below-threshold is a disclosed WARNING, not a FAIL.

chip-AGNOSTIC: fixtures are generic shifter / detector / stub modules.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import synth_netlist_check as snc  # noqa: E402


def _dff_netlist(n: int) -> str:
    body = "\n".join(
        f"  $_DFF_P_ d{i} (.C(clk), .D(w{i}), .Q(q[{i}]));" for i in range(n))
    return (f"module TopModule(input clk, input din, output [{n-1}:0] q);\n"
            f"{body}\nendmodule\n")


_SHIFTER_RTL = ("module TopModule(input clk, input din, output [7:0] q);\n"
                "  reg [7:0] q;\n"
                "  always @(posedge clk) q <= {q[6:0], din};\n"
                "endmodule\n")


def _run(tmp_path, netlist_text, rtl_text=None, min_cells=10):
    nl = tmp_path / "netlist.v"
    nl.write_text(netlist_text)
    rtl_paths = []
    if rtl_text is not None:
        rtl = tmp_path / "top.v"
        rtl.write_text(rtl_text)
        import os, time
        # keep the netlist newer so the staleness guard stays quiet
        os.utime(rtl, (time.time() - 60, time.time() - 60))
        rtl_paths = [rtl]
    return snc.audit_netlist(nl, min_cells, rtl_paths)


# ── (a) register-bit cover vouches a tiny design ──────────────────────────

def test_eight_dff_shifter_vouched_passes(tmp_path):
    findings, stats = _run(tmp_path, _dff_netlist(8), _SHIFTER_RTL)
    cats = {f.category: f.severity for f in findings}
    assert cats.get("TINY_DESIGN_VOUCHED") == "INFO"
    assert "TOO_FEW_CELLS" not in cats
    assert stats["sequential_cells"] == 8
    assert stats["rtl_register_bits"] == 8
    assert not any(f.severity == "ERROR" for f in findings)


def test_cli_rc0_for_vouched_tiny_design(tmp_path):
    nl = tmp_path / "netlist.v"; nl.write_text(_dff_netlist(8))
    rtl = tmp_path / "top.v"; rtl.write_text(_SHIFTER_RTL)
    import os, time
    os.utime(rtl, (time.time() - 60, time.time() - 60))
    assert snc.main(["--netlist", str(nl), "--rtl", str(rtl)]) == 0


# ── (b) the real stub signatures stay hard FAILs ──────────────────────────

def test_zero_cells_still_hard_fails(tmp_path):
    nl_text = "module TopModule(input clk, output q);\nendmodule\n"
    findings, _ = _run(tmp_path, nl_text)
    assert any(f.category == "EMPTY_NETLIST" and f.severity == "ERROR"
               for f in findings)


def test_outputs_tied_constant_hard_fails(tmp_path):
    nl_text = ("module TopModule(input clk, output q, output r);\n"
               "  $_NOT_ a (.A(clk), .Y(internal_w));\n"
               "  assign q = 1'b0;\n  assign r = 1'b1;\n"
               "endmodule\n")
    findings, stats = _run(tmp_path, nl_text)
    cats = {f.category: f.severity for f in findings}
    assert cats.get("OUTPUTS_TIED_CONSTANT") == "ERROR"
    assert set(stats["outputs_tied_constant"]) == {"q", "r"}


def test_partially_constant_output_is_not_a_stub(tmp_path):
    nl_text = ("module TopModule(input clk, output q, output r);\n"
               "  $_NOT_ a (.A(clk), .Y(r));\n"
               "  assign q = 1'b0;\n  assign r2 = r;\n"
               "endmodule\n")
    findings, _ = _run(tmp_path, nl_text)
    assert "OUTPUTS_TIED_CONSTANT" not in [f.category for f in findings]


# ── (c) unvouchable below-threshold is a WARNING, not a FAIL ──────────────

def test_tiny_comb_design_warns_not_fails(tmp_path):
    nl_text = ("module TopModule(input a, input b, output y);\n"
               "  $_AND_ g1 (.A(a), .B(b), .Y(w));\n"
               "  $_NOT_ g2 (.A(w), .Y(y2));\n"
               "  $_OR_  g3 (.A(w), .B(y2), .Y(y));\n"
               "endmodule\n")
    findings, _ = _run(tmp_path, nl_text)
    tfc = [f for f in findings if f.category == "TOO_FEW_CELLS"]
    assert len(tfc) == 1 and tfc[0].severity == "WARNING"
    assert not any(f.severity == "ERROR" for f in findings)


def test_cli_rc0_on_warning_only(tmp_path):
    nl = tmp_path / "netlist.v"
    nl.write_text("module TopModule(input a, output y);\n"
                  "  $_NOT_ g (.A(a), .Y(y));\nendmodule\n")
    assert snc.main(["--netlist", str(nl)]) == 0


def test_healthy_large_netlist_unchanged(tmp_path):
    findings, stats = _run(tmp_path, _dff_netlist(20))
    assert findings == []
    assert stats["total_cells"] == 20


# ── helper sanity ──────────────────────────────────────────────────────────

def test_rtl_register_bits_counts_assigned_regs_only():
    text = ("reg [7:0] q;\nreg [3:0] unused;\nreg single;\n"
            "always @(posedge clk) begin q <= 0; single <= 1; end\n")
    assert snc.rtl_declared_register_bits([text]) == 9  # 8 + 1, unused skipped
