"""ORGANIC #615 [MEDIUM/enh] — reset_dependency_check rglob'd EVERY *.v/*.sv
under the run dir with no exclusion, so it parsed multi-MB flat gate-level
netlists (post-synth/post-PnR) on every invocation (~380s on a 26MB run dir
whose two largest files are 12MB synth netlists), and it runs at least twice
per phase2+3 cycle (live step + flow_compliance_check re-run).

Fix: circular-reset is a STRUCTURAL-RTL concern; a flat gate-level netlist
instantiates library leaf cells, not the design's reset-graph modules, and the
design RTL already holds the full reset hierarchy. So skip synth/PnR-output
files (backend-stage dirs `synth`/`pnr`/`cts`, netlist-named files) and any
machine-generated multi-MB file (>2MB). Skips are LOGGED in the summary
(`files_skipped` + `skipped[]`), never silent.

POSITIVE (#615): the 12MB synth netlists (netlist.v / netlist_yosys.v /
chip_top_synth.v) are skipped — they are no longer parsed.

NEGATIVE no-leak (the load-bearing half, §4.05):
  - a REAL circular reset in the design RTL (rtl/top.v) is STILL detected.
  - a normal project with only small design RTL skips NOTHING (all scanned).
  - a file is skipped ONLY for being a synth/PnR output or >2MB — a small
    hand-written design file is never skipped.

chip-AGNOSTIC: flow-stage dir names + netlist filename conventions + a byte
size floor; no chip-specific literal.
"""
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import reset_dependency_check as R  # noqa: E402

_CIRCULAR_TOP = (
    "module top;\n"
    "  blkA a ( .rstn(sig_from_b), .done(sig_from_a) );\n"
    "  blkB b ( .rstn(sig_from_a), .done(sig_from_b) );\n"
    "endmodule\n")


def _design_rtl(proj):
    rtl = proj / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    return rtl


def test_predicate_classifies_outputs_vs_design(tmp_path):
    root = tmp_path
    # synth/pnr/cts backend-stage dirs → output
    for d, fn in (("phase2/stage2/synth", "netlist.v"),
                  ("phase3/stage3/pnr", "top_pnr.v"),
                  ("phase3/stage3/cts", "clk.v")):
        p = root / d / fn
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("// x\n")
        assert R._is_synth_or_pnr_output(p, root) is True, p
    # netlist-named files anywhere → output
    for fn in ("netlist.v", "netlist_yosys.v", "chip_top_synth.v",
               "chip_top_sv2v.v", "top_routed.v"):
        p = root / "phase2" / "stage1" / "rtl" / fn
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("// x\n")
        assert R._is_synth_or_pnr_output(p, root) is True, fn
    # hand-written design RTL → NOT an output
    p = root / "phase2" / "stage1" / "rtl" / "alu.v"
    p.write_text("module alu; endmodule\n")
    assert R._is_synth_or_pnr_output(p, root) is False


def test_synth_netlists_skipped_design_rtl_scanned(tmp_path):
    _design_rtl(tmp_path)
    (tmp_path / "phase2/stage1/rtl/top.v").write_text(_CIRCULAR_TOP)
    synth = tmp_path / "phase2/stage2/synth"
    synth.mkdir(parents=True)
    (synth / "netlist.v").write_text("module top; foo u(.rstn(x),.done(y)); endmodule\n")
    (synth / "netlist_yosys.v").write_text("// gate netlist\n")
    res = R.audit(str(tmp_path))
    names_skipped = {Path(s["file"]).name for s in res.summary["skipped"]}
    assert {"netlist.v", "netlist_yosys.v"} <= names_skipped
    assert res.summary["files_scanned"] == 1  # only top.v
    assert res.summary["files_skipped"] == 2


def test_size_floor_skips_large_file(tmp_path):
    rtl = _design_rtl(tmp_path)
    (rtl / "top.v").write_text(_CIRCULAR_TOP)
    big = rtl / "huge_generated.v"
    big.write_text("// pad\n" + ("wire w;\n" * 300_000))  # > 2 MB
    assert big.stat().st_size > R._SIZE_FLOOR_BYTES
    res = R.audit(str(tmp_path))
    skipped = {Path(s["file"]).name: s["reason"] for s in res.summary["skipped"]}
    assert "huge_generated.v" in skipped
    assert "size>" in skipped["huge_generated.v"]


def test_circular_reset_in_design_rtl_still_detected(tmp_path):
    # NO-LEAK: skipping netlists must not lose a real design finding.
    _design_rtl(tmp_path)
    (tmp_path / "phase2/stage1/rtl/top.v").write_text(_CIRCULAR_TOP)
    (tmp_path / "phase2/stage2/synth").mkdir(parents=True)
    (tmp_path / "phase2/stage2/synth/netlist.v").write_text("// netlist\n")
    res = R.audit(str(tmp_path))
    assert res.passed is False
    assert any(f.rule == "CIRCULAR_RESET_DEPENDENCY" for f in res.findings)
    assert all(Path(f.file).name == "top.v" for f in res.findings)


def test_normal_project_skips_nothing(tmp_path):
    # NO-LEAK: only small hand-written design RTL -> nothing skipped.
    rtl = _design_rtl(tmp_path)
    (rtl / "alu.v").write_text("module alu(input clk, input rst_n); endmodule\n")
    (rtl / "fifo.v").write_text("module fifo(input clk, input rst_n); endmodule\n")
    res = R.audit(str(tmp_path))
    assert res.summary["files_scanned"] == 2
    assert res.summary["files_skipped"] == 0
    assert res.passed is True
