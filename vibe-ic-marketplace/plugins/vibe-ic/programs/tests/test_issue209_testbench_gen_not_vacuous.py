#!/usr/bin/env python3
"""Regression for #209 — testbench_gen must never emit a VACUOUS testbench.

The defect: `emit_unit_tb` wrote a portless module that printed
`PASS_PLACEHOLDER (replace with real stimulus)` and left the DUT instantiation
COMMENTED OUT. It drove nothing, checked nothing, and printed a pass. The #209
corpus sweep found 140 such files across every benchmark IC and every run
generation — functional verification across the whole campaign was vacuous.

The fix must clear a bar that a placeholder can also clear ("it has a DUT
instantiation in it") only if the bar is set correctly, so this file sets it in
three independent places:

  1. SUBSTANCE — the emitted TB trips NEITHER `vacuous_testbench_check` nor its
     placeholder markers, and holds a LIVE (uncommented) instantiation.

  2. NEGATIVE CONTROL — the emitted TB is COMPILED AND RUN against a
     deliberately BROKEN DUT (outputs left undriven) and must REPORT FAILURE
     with a non-zero exit. A testbench that cannot fail is the same defect in a
     new coat, and no amount of structural inspection can prove it can; only
     running it against a design known to be wrong can. The same TB against a
     CORRECT DUT must pass, so the check is not merely always-fail.

  3. REFUSAL — when the DUT cannot be resolved, NOTHING is written. The old
     behaviour was to emit the placeholder anyway; "emit nothing and say so" is
     the only honest alternative to a real testbench.

chip-AGNOSTIC: every module, port and case name here is a generic synthetic
placeholder — no chip, vendor, SKU or design-name literal.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import testbench_gen as TBG              # noqa: E402
import vacuous_testbench_check as VTB    # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402


# A correct DUT: registers its input, so every output resolves after reset.
GOOD_DUT = """\
module widget_core (
    input        clk,
    input        reset_n,
    input  [7:0] data_in,
    output reg [7:0] data_out,
    output reg       valid
);
  always @(posedge clk or negedge reset_n) begin
    if (!reset_n) begin
      data_out <= 8'h00;
      valid    <= 1'b0;
    end else begin
      data_out <= data_in;
      valid    <= 1'b1;
    end
  end
endmodule
"""

# The SAME port surface, but `valid` is never assigned — it stays X forever.
# This is the negative control: a real testbench must notice.
BROKEN_DUT = """\
module widget_core (
    input        clk,
    input        reset_n,
    input  [7:0] data_in,
    output reg [7:0] data_out,
    output reg       valid
);
  always @(posedge clk or negedge reset_n) begin
    if (!reset_n) data_out <= 8'h00;
    else          data_out <= data_in;
  end
endmodule
"""

L10 = {
    "test_cases": [
        {"name": "tc_alpha", "opcode_hex": "0x01", "kind": "functional_vector",
         "polarity": "positive", "stimulus": "drive a byte",
         "expected": "byte echoed on the next cycle"},
        {"name": "tc_beta", "opcode_hex": "0x02", "kind": "functional_vector",
         "polarity": "negative", "stimulus": "hold reset",
         "expected": "outputs stay at their reset value"},
    ]
}


def _mkproject(tmp_path: Path, rtl: str | None) -> Path:
    project = tmp_path / "proj"
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L10_TEST_CASES.json").write_text(json.dumps(L10, indent=2))
    if rtl is not None:
        rtl_dir = project / "phase2" / "stage1" / "rtl"
        rtl_dir.mkdir(parents=True, exist_ok=True)
        (rtl_dir / "widget_core.v").write_text(rtl)
    return project


def _tb_dir(project: Path) -> Path:
    return project / "phase2" / "stage1" / "sim" / "tb"


# --------------------------------------------------------------------------
# 1. SUBSTANCE — the emitted TB is not vacuous by any of the #209 detectors
# --------------------------------------------------------------------------
def test_emitted_tb_instantiates_the_dut(tmp_path):
    project = _mkproject(tmp_path, GOOD_DUT)
    report: dict = {}
    assert TBG.emit_unit_tbs(project, "widget_core", report=report) == 2
    assert report["dut_module"] == "widget_core"

    for tb in sorted(_tb_dir(project).glob("*.v")):
        src = tb.read_text()
        # a LIVE instantiation, via the gate's own shared substance primitive
        assert VTB.source_drives_dut(src), f"{tb.name} drives nothing"
        live = VTB.find_live_instantiations(VTB.split_code_and_comments(src)[0])
        assert any(d["module"] == "widget_core" for d in live), live
        # and no placeholder marker of any flavour
        assert "PASS_PLACEHOLDER" not in src
        assert "replace with real stimulus" not in src


def test_emitted_tree_passes_the_vacuous_gate(tmp_path):
    """The whole point: a run built from this generator no longer FAILs #209."""
    project = _mkproject(tmp_path, GOOD_DUT)
    assert TBG.emit_unit_tbs(project, "widget_core") == 2
    res = VTB.check(project)
    assert res["verdict"] == "PASS", json.dumps(res, indent=2)
    assert res["evidence"] == []


def test_old_placeholder_shape_would_still_be_caught(tmp_path):
    """Control on the CONTROL: the gate that must catch the old output still
    does. If this ever passes silently the substance test above proves nothing,
    because the bar itself would have moved."""
    project = _mkproject(tmp_path, GOOD_DUT)
    tb_dir = _tb_dir(project)
    tb_dir.mkdir(parents=True, exist_ok=True)
    (tb_dir / "tc_legacy.v").write_text(
        "module tc_legacy;\n"
        "  reg clk = 0;\n"
        "  initial begin\n"
        '    #1000 $display("[TB tc_legacy] PASS_PLACEHOLDER '
        '(replace with real stimulus)");\n'
        "    $finish;\n"
        "  end\n"
        "  // widget_core u_dut (.clk(clk), .reset_n(reset_n));\n"
        "endmodule\n")
    res = VTB.check(project)
    assert res["verdict"] == "FAIL"
    assert "placeholder_marker" in res["detectors_tripped"]
    assert "commented_dut_instantiation" in res["detectors_tripped"]


# --------------------------------------------------------------------------
# 2. NEGATIVE CONTROL — the emitted TB must actually FAIL on a broken DUT
# --------------------------------------------------------------------------
def _simulate(tmp_path: Path, rtl: str, tag: str):
    """Emit a TB against `rtl`, then compile+run it. Returns (rc, log)."""
    project = _mkproject(tmp_path / tag, rtl)
    assert TBG.emit_unit_tbs(project, "widget_core") == 2
    tb = _tb_dir(project) / "tc_alpha.v"
    rtl_f = project / "phase2" / "stage1" / "rtl" / "widget_core.v"
    vvp = tmp_path / tag / "sim.vvp"
    build = _pr.run(
        ["iverilog", "-o", str(vvp), "-s", "tc_alpha", str(tb), str(rtl_f)],
        capture_output=True, text=True)
    assert build.returncode == 0, (
        f"emitted TB does not COMPILE against the DUT:\n{build.stderr}\n"
        f"--- TB ---\n{tb.read_text()}")
    run = _pr.run([str(vvp)], capture_output=True, text=True)
    return run.returncode, run.stdout + run.stderr


@pytest.mark.skipif(not (shutil.which("iverilog") and shutil.which("vvp")),
                    reason="iverilog/vvp not available")
def test_negative_control_emitted_tb_fails_on_broken_dut(tmp_path):
    """THE load-bearing test. Feed the emitted TB a DUT whose `valid` output is
    never driven and it must REPORT FAILURE and exit non-zero.

    A testbench that instantiates the DUT but can only ever print a pass is the
    #209 defect in a new coat; the only proof it is not is running it against a
    design that is known to be wrong.
    """
    rc, log = _simulate(tmp_path, BROKEN_DUT, "broken")
    assert rc != 0, f"TB passed a BROKEN DUT — it cannot fail:\n{log}"
    assert "FAIL" in log, log
    assert "valid" in log, f"TB did not name the offending output:\n{log}"
    assert "SUBSTANCE_OK" not in log, f"TB printed a pass AND a fail:\n{log}"


@pytest.mark.skipif(not (shutil.which("iverilog") and shutil.which("vvp")),
                    reason="iverilog/vvp not available")
def test_positive_control_emitted_tb_passes_on_correct_dut(tmp_path):
    """The other half of the control: the check is not always-fail. The SAME
    emitted TB against a CORRECT DUT completes cleanly."""
    rc, log = _simulate(tmp_path, GOOD_DUT, "good")
    assert rc == 0, f"TB failed a CORRECT DUT:\n{log}"
    assert "SUBSTANCE_OK" in log, log
    assert "FAIL" not in log, log


# --------------------------------------------------------------------------
# 3. REFUSAL — no DUT, no testbench. Never a placeholder.
# --------------------------------------------------------------------------
def test_refuses_to_emit_when_no_rtl_exists(tmp_path):
    project = _mkproject(tmp_path, rtl=None)
    report: dict = {}
    assert TBG.emit_unit_tbs(project, "widget_core", report=report) == -2
    assert "refused to emit" in report["reason"]
    assert not _tb_dir(project).exists() or \
        list(_tb_dir(project).glob("*.v")) == []


def test_refuses_when_top_is_absent_and_root_is_ambiguous(tmp_path):
    """L9.top_module is often a product/SKU name, not an RTL module (#661).
    With two unrelated roots there is no honest guess — emit nothing."""
    project = _mkproject(tmp_path, GOOD_DUT)
    rtl_dir = project / "phase2" / "stage1" / "rtl"
    (rtl_dir / "other_core.v").write_text(
        "module other_core (input a, output b);\n  assign b = a;\nendmodule\n")
    report: dict = {}
    assert TBG.emit_unit_tbs(project, "a_name_that_is_not_a_module",
                             report=report) == -2
    assert "ambiguous" in report["dut_resolution"]
    assert list(_tb_dir(project).glob("*.v")) == []


def test_refuses_when_dut_has_no_observable_output(tmp_path):
    """A TB over an output-less DUT has nothing to check, so it could not fail.
    Emitting one would reintroduce the defect with a live instantiation."""
    project = _mkproject(tmp_path, rtl=None)
    rtl_dir = project / "phase2" / "stage1" / "rtl"
    rtl_dir.mkdir(parents=True, exist_ok=True)
    (rtl_dir / "sink.v").write_text(
        "module sink (input clk, input reset_n, input [3:0] d);\n"
        "endmodule\n")
    report: dict = {}
    assert TBG.emit_unit_tbs(project, "sink", report=report) == -2
    assert "no non-power output" in report["reason"]
    assert list(_tb_dir(project).glob("*.v")) == []


# --------------------------------------------------------------------------
# 4. NO SMUGGLED COVERAGE — a real TB with no oracle must not credit the case
# --------------------------------------------------------------------------
def test_generated_tb_does_not_manufacture_l10_coverage_credit(tmp_path):
    """The trap this fix had to avoid.

    `l10_tb_conformance_check` credits a case when the case id appears anywhere
    in the testbench text, and the #206 evidence suppression only fires when
    NOTHING in the tree drives the DUT. The generated TB now DOES drive the DUT
    and is named after the case — so, left alone, it would lift the suppression
    and mark every previously-uncovered case as covered, having verified only
    that no output is X. That is the same lie one layer up.

    The generated TB therefore declares `VIBEIC_TB_ORACLE: NONE` and the gate
    excludes it from the evidence blob. It counts as a driver (the tree is not
    vacuous) but credits nothing.
    """
    import l10_tb_conformance_check as L10   # noqa: E402

    project = _mkproject(tmp_path, GOOD_DUT)
    assert TBG.emit_unit_tbs(project, "widget_core") == 2
    tb_dir = _tb_dir(project)

    per_file, blob = L10.read_all_tb_text(str(tb_dir))
    assert len(per_file) == 2, per_file            # both seen as testbenches
    assert VTB.any_source_drives_dut(per_file.values())   # tree is NOT vacuous
    assert blob == "", "oracle-less scaffold leaked into the evidence blob"
    assert "tc_alpha" not in blob and "tc_beta" not in blob

    # And once a real oracle is written (marker removed), the file DOES count.
    tb = tb_dir / "tc_alpha.v"
    tb.write_text(tb.read_text().replace(TBG.ORACLE_NONE_MARKER,
                                         "oracle: checked against golden"))
    _pf, blob2 = L10.read_all_tb_text(str(tb_dir))
    assert "tc_alpha" in blob2
    assert "tc_beta" not in blob2      # still marked, still not credited


def test_resolves_root_when_top_name_is_not_a_module(tmp_path):
    """No regression on the #661 shape: an unambiguous instantiation-graph root
    is still bound (and really instantiated), so a project whose L9.top_module
    is a SKU name still gets a real TB."""
    project = _mkproject(tmp_path, GOOD_DUT)
    rtl_dir = project / "phase2" / "stage1" / "rtl"
    (rtl_dir / "wrapper.v").write_text(
        "module wrapper (input clk, input reset_n, input [7:0] data_in,\n"
        "                output [7:0] data_out, output valid);\n"
        "  widget_core u_core (.clk(clk), .reset_n(reset_n),\n"
        "                      .data_in(data_in), .data_out(data_out),\n"
        "                      .valid(valid));\n"
        "endmodule\n")
    report: dict = {}
    assert TBG.emit_unit_tbs(project, "product_sku_name", report=report) == 2
    assert report["dut_module"] == "wrapper"
    src = (_tb_dir(project) / "tc_alpha.v").read_text()
    assert VTB.source_drives_dut(src)
    assert "wrapper u_dut" in src
