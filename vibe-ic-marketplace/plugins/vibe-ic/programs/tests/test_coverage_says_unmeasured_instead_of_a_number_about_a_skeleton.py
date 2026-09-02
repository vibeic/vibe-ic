#!/usr/bin/env python3
"""A percentage measured on a testbench that moves nothing is not the RTL's.

MEASURED — sha256 x sky130A, plugin 1.15.94, frozen tree c3584d0aa:

    reports/phase2/coverage/coverage_verilator.json
      "testbench": "phase2/stage1/sim_full_stack/tb_sha256_full.v"
    -> [check] below threshold(s): line 16.48% < 70.0%;
                                   toggle 2.34% < 60.0%; branch 13.46% < 70.0%

That testbench declares `cs`, `we`, `address`, `write_data`, wires them to the
DUT, initialises them at declaration and never assigns them again — the only
signals it drives are the clock and the reset. 16.48% is the coverage of
releasing reset and waiting. The same run held a cocotb testbench that had just
driven 1020 NIST vectors through the whole design.

"I did not measure the design" and "I measured the design at 16.48%" are two
different facts, and the verdict compressed them into one, pointing the reader
at the RTL for a defect that is in the coverage build.

The REVERSE half is what keeps this from becoming "everything is now
NOT_MEASURED", and most of the cases below are it: a build with real functional
stimulus must still be graded as a percentage, an undecidable audit must fall
through untouched, and a no-functional-stimulus build must still BLOCK — never
pass. Those cases hold on BOTH trees by construction.

Every fixture is synthetic (`gizmo`, `pulse_shaper`); nothing keys on a
filename, so a fix that pattern-matched `*_full.v` could not pass.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import verilator_coverage_measure as VCM   # noqa: E402


# --- a testbench that binds the DUT and drives only clock + reset ----------
_INERT_TB = """
// Auto-generated skeleton. CONNECTIVITY-ONLY (it closes no functional
// coverage on its own): add stimulus here.
`timescale 1ns/1ps
module tb_gizmo_full;
  reg clk = 0;
  reg reset_n = 0;
  reg enable = 0;
  reg [7:0] cmd = 0;
  wire [7:0] result;
  always #10 clk = ~clk;
  gizmo u_dut (.clk(clk), .reset_n(reset_n), .enable(enable), .cmd(cmd),
               .result(result));
  initial begin
    reset_n = 0; #100;
    reset_n = 1; #100;
    repeat (2000) @(posedge clk);
    $display("DONE");
    $finish;
  end
endmodule
"""

# --- the same shape, but it actually moves the design's inputs ------------
_LIVE_TB = """
`timescale 1ns/1ps
module tb_pulse_shaper_full;
  reg clk = 0;
  reg reset_n = 0;
  reg enable = 0;
  reg [7:0] cmd = 0;
  wire [7:0] result;
  always #10 clk = ~clk;
  pulse_shaper u_dut (.clk(clk), .reset_n(reset_n), .enable(enable),
                      .cmd(cmd), .result(result));
  initial begin
    reset_n = 0; #100;
    reset_n = 1; #100;
    enable <= 1'b1;
    cmd    <= 8'h5a;
    repeat (40) @(posedge clk);
    cmd = 8'ha5;
    repeat (40) @(posedge clk);
    $display("DONE");
    $finish;
  end
endmodule
"""


def _build(tmp_path: Path, tb_text: str, tb_name: str,
           line=16.48, toggle=2.34, branch=13.46) -> Path:
    """A project with a coverage record naming its own testbench."""
    proj = tmp_path / "proj"
    fs = proj / "phase2" / "stage1" / "sim_full_stack"
    fs.mkdir(parents=True, exist_ok=True)
    tb = fs / tb_name
    tb.write_text(tb_text, encoding="utf-8")
    rtl = proj / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "dut.v").write_text("module dut; endmodule\n", encoding="utf-8")
    dat = proj / "phase2" / "stage1" / "sim" / "cov_build" / "coverage.dat"
    dat.parent.mkdir(parents=True, exist_ok=True)
    dat.write_text("C '\\x01f' 1\n", encoding="utf-8")
    rec = proj / "coverage_verilator.json"
    rec.write_text(json.dumps({
        "tool": "verilator",
        "measurement_mode": "measure-tb",
        "coverage_dat": str(dat),
        "testbench": str(tb),
        "rtl_sources": [str(rtl / "dut.v")],
        "totals": {
            "line":   {"covered": 15, "total": 91, "pct": line},
            "toggle": {"covered": 67, "total": 2862, "pct": toggle},
            "branch": {"covered": 7, "total": 52, "pct": branch},
        },
    }), encoding="utf-8")
    return rec


def _check(rec: Path, capsys) -> "tuple[int, str]":
    rc = VCM.build_parser().parse_args(
        ["check", "--coverage-json", str(rec)]).func(
            VCM.build_parser().parse_args(
                ["check", "--coverage-json", str(rec)]))
    cap = capsys.readouterr()
    return rc, cap.out + cap.err


# ===========================================================================
# forward — an inert build must say so, and must not report a number
# ===========================================================================
def test_a_build_with_no_functional_stimulus_says_so(tmp_path, capsys):
    rec = _build(tmp_path, _INERT_TB, "tb_gizmo_full.v")
    rc, out = _check(rec, capsys)
    assert "NO FUNCTIONAL STIMULUS" in out.upper(), (
        f"the verdict did not say the coverage build had no stimulus: {out}")


def test_the_percentage_is_not_reported_as_a_threshold_failure(
        tmp_path, capsys):
    """16.48% describes the skeleton; grading it sends the reader to the RTL."""
    rec = _build(tmp_path, _INERT_TB, "tb_gizmo_full.v")
    _rc, out = _check(rec, capsys)
    assert "below threshold" not in out.lower(), (
        f"an inert build was still graded as a coverage shortfall: {out}")


def test_the_verdict_names_the_inert_signals(tmp_path, capsys):
    rec = _build(tmp_path, _INERT_TB, "tb_gizmo_full.v")
    _rc, out = _check(rec, capsys)
    for sig in ("enable", "cmd"):
        assert sig in out, (
            f"the verdict did not name the undriven design input {sig!r}: "
            f"{out}")


def test_it_still_blocks(tmp_path, capsys):
    """Unmeasured is not verified — this must never become a pass."""
    rec = _build(tmp_path, _INERT_TB, "tb_gizmo_full.v")
    rc, _out = _check(rec, capsys)
    assert rc != 0, "a run with no functional stimulus was allowed to pass"


# ===========================================================================
# reverse controls — these hold on BOTH trees
# ===========================================================================
def test_a_real_stimulus_build_is_still_graded_as_a_percentage(
        tmp_path, capsys):
    """WITHOUT this, the change would just relabel all coverage NOT_MEASURED."""
    rec = _build(tmp_path, _LIVE_TB, "tb_pulse_shaper_full.v")
    rc, out = _check(rec, capsys)
    assert "NO FUNCTIONAL STIMULUS" not in out.upper(), (
        f"a testbench that drives `enable` and `cmd` was called inert: {out}")
    assert "below threshold" in out.lower(), (
        f"a real measurement below the floor stopped being graded: {out}")
    assert rc != 0


def test_a_real_stimulus_build_above_the_floor_still_passes(
        tmp_path, capsys):
    rec = _build(tmp_path, _LIVE_TB, "tb_pulse_shaper_full.v",
                 line=95.0, toggle=90.0, branch=92.0)
    rc, out = _check(rec, capsys)
    assert rc == 0, f"a genuine high-coverage measurement was refused: {out}"
    assert "PASS" in out


def test_a_record_naming_no_testbench_falls_through(tmp_path, capsys):
    """`measure` mode records no testbench; nothing to audit, behave as before."""
    rec = _build(tmp_path, _INERT_TB, "tb_gizmo_full.v")
    data = json.loads(rec.read_text())
    data.pop("testbench")
    rec.write_text(json.dumps(data), encoding="utf-8")
    rc, out = _check(rec, capsys)
    assert "NO FUNCTIONAL STIMULUS" not in out.upper()
    assert "below threshold" in out.lower() and rc != 0


def test_an_unreadable_testbench_is_not_grounds_for_a_verdict(
        tmp_path, capsys):
    """An audit that cannot see must never be the reason a run is judged."""
    rec = _build(tmp_path, _INERT_TB, "tb_gizmo_full.v")
    data = json.loads(rec.read_text())
    data["testbench"] = str(tmp_path / "gone.v")
    rec.write_text(json.dumps(data), encoding="utf-8")
    rc, out = _check(rec, capsys)
    assert "NO FUNCTIONAL STIMULUS" not in out.upper(), (
        f"a missing testbench was reported as an inert one: {out}")
    assert "below threshold" in out.lower() and rc != 0


def test_a_testbench_with_no_port_bindings_falls_through(tmp_path, capsys):
    rec = _build(tmp_path, "module tb_x; initial $finish; endmodule\n",
                 "tb_x_full.v")
    rc, out = _check(rec, capsys)
    assert "NO FUNCTIONAL STIMULUS" not in out.upper()
    assert "below threshold" in out.lower() and rc != 0


# ===========================================================================
# the criterion itself — behaviour, never a filename
# ===========================================================================
def test_the_criterion_does_not_depend_on_the_filename(tmp_path, capsys):
    """The same inert body under an oracle-shaped name is still inert; the
    same live body under a skeleton-shaped name is still live."""
    inert_named_oracle = _build(tmp_path / "a", _INERT_TB, "tb_gizmo_oracle.v")
    _rc, out = _check(inert_named_oracle, capsys)
    assert "NO FUNCTIONAL STIMULUS" in out.upper(), (
        "an inert testbench escaped by being named like an oracle")
    live_named_skeleton = _build(tmp_path / "b", _LIVE_TB,
                                 "tb_pulse_shaper_full.v")
    _rc2, out2 = _check(live_named_skeleton, capsys)
    assert "NO FUNCTIONAL STIMULUS" not in out2.upper(), (
        "a live testbench was condemned by its filename")


def test_the_header_self_description_alone_does_not_decide(tmp_path, capsys):
    """A comment can be deleted while the testbench stays inert; the drive
    count is what decides, and the self-description only corroborates."""
    stripped = _INERT_TB.replace(
        "// Auto-generated skeleton. CONNECTIVITY-ONLY (it closes no functional\n"
        "// coverage on its own): add stimulus here.\n", "")
    assert "connectivity" not in stripped.lower()
    rec = _build(tmp_path, stripped, "tb_gizmo_full.v")
    _rc, out = _check(rec, capsys)
    assert "NO FUNCTIONAL STIMULUS" in out.upper(), (
        f"deleting the header comment hid an inert testbench: {out}")


def test_the_audit_reports_what_it_examined(tmp_path):
    """The record is auditable on its own, not only through the message."""
    rec = _build(tmp_path, _INERT_TB, "tb_gizmo_full.v")
    tb = Path(json.loads(rec.read_text())["testbench"])
    audit = VCM.functional_stimulus_audit(tb)
    assert audit["decidable"] is True
    assert sorted(audit["clock_reset"]) == ["clk", "reset_n"]
    assert sorted(audit["inert"]) == ["cmd", "enable"]
    assert audit["driven"] == []
    assert audit["self_declared_connectivity_only"] is True


# ===========================================================================
# the verdict has to REACH the consumer, not merely be printed
# ===========================================================================
#
# MEASURED, sha256 x sky130A on v1.16.41: this block first shipped writing all
# five lines to stderr, and the sentence it exists to say never reached the
# step record. `flow_compliance_check.output_snippet` keeps
# `_head_and_tail(stdout)` but only `_grown_tail(stderr, 300)` — a deliberate
# asymmetry, because stderr is the crash channel and a crash's evidence is its
# tail. stdout was 0 bytes, stderr 859, so the headline was cut before the
# caller's `out[:200]` ran and the record showed line 4. Widening the 200 does
# not help: at that point the sentence is not in the 344-byte snippet at all.
def _step_record_output(rec_path) -> str:
    """What `flow_compliance_check` would put after `output:` for this run.

    Routed through the CONSUMER's own reader so the test cannot pass by
    agreeing with a private notion of what a snippet is.
    """
    import subprocess
    sys.path.insert(0, str(_PROGRAMS))
    import flow_compliance_check as FCC
    r = subprocess.run(
        [sys.executable, str(_PROGRAMS / "verilator_coverage_measure.py"),
         "check", "--coverage-json", str(rec_path)],
        capture_output=True, text=True)
    return FCC.output_snippet(r.stdout, r.stderr)[:200]


def test_the_load_bearing_sentence_reaches_the_step_record(tmp_path):
    """Forward: the assertion the rule exists to make must be readable in the
    artefact a reader actually reads, not only in the program's own output."""
    rec = _build(tmp_path, _INERT_TB, "tb_gizmo_full.v")
    shown = _step_record_output(rec)
    assert "NO FUNCTIONAL STIMULUS" in shown, (
        "the rule's headline is printed by the program but does not survive "
        f"into the step record; the record would show: {shown!r}")


def test_a_real_stimulus_build_never_carries_that_sentence(tmp_path):
    """Reverse: doing only the forward half would be a sentence stapled on
    unconditionally. A build with real stimulus must reach the consumer with a
    percentage verdict and no trace of the no-stimulus claim."""
    rec = _build(tmp_path, _LIVE_TB, "tb_pulse_shaper_full.v")
    shown = _step_record_output(rec)
    assert "NO FUNCTIONAL STIMULUS" not in shown, (
        f"a build that drives the design was told it measured nothing: "
        f"{shown!r}")
    assert "below threshold" in shown.lower(), (
        f"the real measurement's verdict did not reach the record: {shown!r}")


def test_a_passing_build_reaches_the_record_unchanged(tmp_path):
    """Reverse: the channel move must not disturb the PASS path."""
    rec = _build(tmp_path, _LIVE_TB, "tb_pulse_shaper_full.v",
                 line=95.0, toggle=90.0, branch=92.0)
    shown = _step_record_output(rec)
    assert "NO FUNCTIONAL STIMULUS" not in shown
    assert "PASS" in shown, f"a passing measurement lost its verdict: {shown!r}"
