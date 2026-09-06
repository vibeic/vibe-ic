#!/usr/bin/env python3
"""A simulator that cannot pass a problem's OWN reference is not a qualified judge.

Pins `score_iverilog_tb._primary_tool_disqualified_escalation` and its wiring into
`_score_shape_b`.

WHY THIS EXISTS (measured 2026-09-06, RTLLM @ plugin v1.17.60, image vibeic-eda
0.3.46). The scorer already MEASURED the golden-fails-its-own-TB signal
(`_golden_ref_fails_own_tb_runtime`) and already owned a Verilator escalation rung
(`_verilator_compile_run`), but nothing wired the first to the second: the escalation
trigger `_iverilog_toolgap_signature` reads COMPILE text only ("sorry:", "internal
error", ...) and cannot see a runtime mis-verdict.  So the scorer would disclose "the
shipped golden fails its own testbench" and still charge the FAIL to the model.
Handed each problem's OWN reference implementation as the candidate, the pre-fix
scorer returned FAIL for RTLLM `radix2_div` and `ring_counter`.

THE ANTI-CHEAT IS THE LOAD-BEARING HALF, and it fired during development.  A rung
that passes the golden may still be unable to REJECT a deliberately-wrong design:
RTLLM `ring_counter`'s official TB passes its golden under Verilator AND passes a
constant-0 stub there.  The FIRST version of this fix silently added `ring_counter`
to the zero-stub PASS set (measured: {edge_detect, square_wave} ->
{edge_detect, ring_counter, square_wave}).  `test_no_escalation_when_higher_rung_
cannot_reject_a_wrong_design` is the mutation pin for that guard: delete the guard
and it goes red.

These tests are HERMETIC.  The escalation rung reaches Verilator through
`docker exec`, which is unavailable inside the test container, so the rung helpers
are substituted and the DECISION TABLE is what is pinned.  One test additionally
uses the real host/container `iverilog` (skipped when absent) to pin the TRIGGER on
a real simulator: a testbench whose pass path is unreachable really does make
`_golden_ref_fails_own_tb_runtime` report True.
"""
from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

_BENCH = Path(__file__).resolve().parents[2] / "benchmark"


def _load():
    spec = importlib.util.spec_from_file_location(
        "score_iverilog_tb_under_test", _BENCH / "score_iverilog_tb.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


S = _load()

LAYOUT = {
    "prompt_filename": "design_description.txt",
    "tb_filename": "testbench.v",
    "ref_glob": "verified_*.v",
}
ARGS = {
    "pass_regex": "Your Design Passed",
    "fail_regex": "Test failed|Your Design Failed",
    "cwd_design_dir": True,
}
DESIGN = "Cat/Sub/widget"
LEAF = "widget"

# An ANSI-header module so `_build_zero_stub` can synthesise the wrong-design probe.
_SAMPLE = """module widget (
    input  wire clk,
    input  wire rst_n,
    output reg  [7:0] q
);
    always @(posedge clk or negedge rst_n)
        if (!rst_n) q <= 8'd0; else q <= q + 8'd1;
endmodule
"""

_GOLDEN = _SAMPLE.replace("module widget", "module verified_widget")

_TB = """`timescale 1ns/1ps
module testbench;
    reg clk = 0, rst_n = 0;
    wire [7:0] q;
    widget dut(.clk(clk), .rst_n(rst_n), .q(q));
    always #5 clk = ~clk;
    initial begin
        #12 rst_n = 1;
        #100;
        $display("===========Your Design Passed===========");
        $finish;
    end
endmodule
"""


def _mkdataset(tmp_path: Path, *, golden: str = _GOLDEN, extra_ref: bool = False):
    """A minimal Shape-B dataset + a run dir holding one candidate sample."""
    dataset = tmp_path / "ds"
    ddir = dataset / DESIGN
    ddir.mkdir(parents=True)
    (ddir / "design_description.txt").write_text(
        "Please act as a professional verilog designer.\n\nModule name:\n    widget\n")
    (ddir / "testbench.v").write_text(_TB)
    (ddir / "verified_widget.v").write_text(golden)
    if extra_ref:
        (ddir / "verified_widget_helper.v").write_text("module helper; endmodule\n")
    samples = tmp_path / "run" / "samples"
    samples.mkdir(parents=True)
    (samples / f"{LEAF}.v").write_text(_SAMPLE)
    return dataset, samples


def _rungs(monkeypatch, *, golden_built=True, golden_pass=True,
           stub_built=True, stub_pass=False, candidate=None):
    """Substitute the two escalation-rung helpers. Records the tags it was asked for
    so a test can assert the GOLDEN is qualified before the candidate is judged."""
    seen: list[str] = []

    def fake_run_text(text, design, tb, design_dir, pass_re, tag):
        seen.append(tag)
        if tag == "qualify_golden":
            return (golden_built, golden_pass)
        if tag == "qualify_stub":
            return (stub_built, stub_pass)
        raise AssertionError(f"unexpected rung tag {tag!r}")

    def fake_compile_run(design, sample_c, tb, design_dir, pass_re, fail_re):
        seen.append("candidate")
        return candidate

    monkeypatch.setattr(S, "_verilator_run_text", fake_run_text)
    monkeypatch.setattr(S, "_verilator_compile_run", fake_compile_run)
    return seen


# ---------------------------------------------------------------- decision table

def test_escalates_when_higher_rung_accepts_reference_and_rejects_garbage(
        tmp_path, monkeypatch):
    """The radix2_div case: primary tool failed the problem's own reference, the
    higher rung passes that reference AND rejects a constant-0 stub, and the
    candidate passes there -> the verdict is re-decided on the qualified rung."""
    dataset, samples = _mkdataset(tmp_path)
    seen = _rungs(monkeypatch, candidate={"verdict": "PASS",
                                          "reason": "recovered_via_verilator"})
    out = S._primary_tool_disqualified_escalation(
        DESIGN, samples, dataset, LAYOUT, ARGS)
    assert out is not None, "a qualified rung must re-decide the problem"
    assert out["verdict"] == "PASS"
    assert out["tool_escalation"] == "verilator"
    assert out["tool_escalation_trigger"] == "golden_ref_fails_own_tb_runtime"
    # The GOLDEN is qualified BEFORE the candidate is ever judged.
    assert seen.index("qualify_golden") < seen.index("candidate")


def test_no_escalation_when_higher_rung_cannot_reject_a_wrong_design(
        tmp_path, monkeypatch):
    """MUTATION PIN for the anti-cheat guard (RTLLM ring_counter).

    The higher rung passes the golden, but it ALSO passes a deliberately-wrong
    constant-0 stub, so a PASS there certifies nothing.  Escalation must make NO
    determination, leaving the caller's FAIL and its defect disclosure intact.

    Delete the stub guard in `_primary_tool_disqualified_escalation` and this test
    goes red - which is exactly how ring_counter was caught entering the zero-stub
    PASS set during development.
    """
    dataset, samples = _mkdataset(tmp_path)
    seen = _rungs(monkeypatch, stub_pass=True,
                  candidate={"verdict": "PASS", "reason": "should never be reached"})
    out = S._primary_tool_disqualified_escalation(
        DESIGN, samples, dataset, LAYOUT, ARGS)
    assert out is None, (
        "a rung that passes a constant-0 stub is not a valid oracle; escalating "
        "onto it manufactures a meaningless PASS")
    assert "candidate" not in seen, (
        "the candidate must not even be judged on a non-discriminating rung")


def test_no_escalation_when_higher_rung_also_fails_the_reference(
        tmp_path, monkeypatch):
    """If the higher rung cannot pass the golden either, nothing is established."""
    dataset, samples = _mkdataset(tmp_path)
    seen = _rungs(monkeypatch, golden_pass=False,
                  candidate={"verdict": "PASS", "reason": "should never be reached"})
    assert S._primary_tool_disqualified_escalation(
        DESIGN, samples, dataset, LAYOUT, ARGS) is None
    assert "candidate" not in seen


def test_no_escalation_when_higher_rung_is_unavailable(tmp_path, monkeypatch):
    """Verilator/container absent -> no determination, never an invented verdict."""
    dataset, samples = _mkdataset(tmp_path)
    _rungs(monkeypatch, golden_built=False,
           candidate={"verdict": "PASS", "reason": "should never be reached"})
    assert S._primary_tool_disqualified_escalation(
        DESIGN, samples, dataset, LAYOUT, ARGS) is None


def test_escalation_does_not_launder_a_wrong_candidate(tmp_path, monkeypatch):
    """The rung is qualified, but the candidate fails there: it STAYS a FAIL.
    Escalation re-decides who judges, never what the answer is."""
    dataset, samples = _mkdataset(tmp_path)
    _rungs(monkeypatch, candidate={"verdict": "FAIL",
                                   "reason": "functional_mismatch (verilator)"})
    out = S._primary_tool_disqualified_escalation(
        DESIGN, samples, dataset, LAYOUT, ARGS)
    assert out is not None and out["verdict"] == "FAIL"


def test_multi_file_golden_makes_no_determination(tmp_path, monkeypatch):
    """`_verilator_run_text` stages ONE text; a multi-file golden cannot be replayed
    through it, so we report no determination rather than a partial one."""
    dataset, samples = _mkdataset(tmp_path, extra_ref=True)
    _rungs(monkeypatch, candidate={"verdict": "PASS", "reason": "unreachable"})
    assert S._primary_tool_disqualified_escalation(
        DESIGN, samples, dataset, LAYOUT, ARGS) is None


# ------------------------------------------------------------------- the wiring

def test_score_shape_b_wires_the_trigger_to_the_escalation(tmp_path, monkeypatch):
    """END-TO-END pin, and the RED-on-unfixed-sources one.

    Before the fix, `_score_shape_b` computed `_golden_ref_fails_own_tb_runtime`,
    annotated the result as a suspected defect, and returned the FAIL unchanged.
    Now a qualified rung replaces that verdict.  On unfixed sources
    `_primary_tool_disqualified_escalation` does not exist at all, so every test in
    this module fails at attribute lookup.
    """
    dataset, samples = _mkdataset(tmp_path)
    monkeypatch.setattr(S, "_score_shape_b_impl",
                        lambda *a, **k: {"design": DESIGN, "verdict": "FAIL",
                                         "reason": "no_pass_marker"})
    # the primary tool cannot pass this problem's own reference
    monkeypatch.setattr(S, "_golden_ref_fails_own_tb_runtime",
                        lambda *a, **k: True)
    _rungs(monkeypatch, candidate={"verdict": "PASS",
                                   "reason": "recovered_via_verilator"})
    out = S._score_shape_b(DESIGN, samples, dataset, LAYOUT, ARGS)
    assert out["verdict"] == "PASS"
    assert out.get("tool_escalation") == "verilator"


def test_score_shape_b_keeps_the_disclosure_when_nothing_qualifies(
        tmp_path, monkeypatch):
    """No qualified rung -> the pre-existing suspected-defect disclosure and the
    FAIL both survive untouched. The score is never inflated."""
    dataset, samples = _mkdataset(tmp_path)
    monkeypatch.setattr(S, "_score_shape_b_impl",
                        lambda *a, **k: {"design": DESIGN, "verdict": "FAIL",
                                         "reason": "no_pass_marker"})
    monkeypatch.setattr(S, "_golden_ref_fails_own_tb_runtime",
                        lambda *a, **k: True)
    _rungs(monkeypatch, stub_pass=True)          # rung cannot reject garbage
    out = S._score_shape_b(DESIGN, samples, dataset, LAYOUT, ARGS)
    assert out["verdict"] == "FAIL"
    assert out.get("dataset_defect_suspected") is True
    assert out.get("dataset_defect_reason") == "golden_ref_fails_own_tb_runtime"


def test_a_passing_verdict_never_reaches_the_escalation(tmp_path, monkeypatch):
    """The trigger is the GOLDEN failing, and it is only consulted for a FAIL.
    A PASS is returned untouched, so the escalation can never affect a pass."""
    dataset, samples = _mkdataset(tmp_path)
    monkeypatch.setattr(S, "_score_shape_b_impl",
                        lambda *a, **k: {"design": DESIGN, "verdict": "PASS"})

    def _boom(*a, **k):                      # pragma: no cover - must not run
        raise AssertionError("escalation consulted for a PASS")

    monkeypatch.setattr(S, "_primary_tool_disqualified_escalation", _boom)
    assert S._score_shape_b(DESIGN, samples, dataset, LAYOUT, ARGS)["verdict"] == "PASS"


# --------------------------------------------------------- trigger, on real tools

@pytest.mark.skipif(not shutil.which("iverilog") or not shutil.which("vvp"),
                    reason="needs a real iverilog/vvp to pin the trigger")
def test_trigger_fires_on_a_tb_whose_pass_path_is_unreachable(tmp_path):
    """Pin the TRIGGER itself against a real simulator.

    This is the RTLLM ring_counter shape reduced to its essence: a testbench whose
    pass marker is unreachable.  The golden compiles and runs, prints no pass
    marker, and `_golden_ref_fails_own_tb_runtime` must report True - that is the
    signal the scorer already had and was not acting on.
    """
    unreachable_tb = _TB.replace(
        '$display("===========Your Design Passed===========");',
        'if (0) $display("===========Your Design Passed===========");')
    dataset, _samples = _mkdataset(tmp_path)
    (dataset / DESIGN / "testbench.v").write_text(unreachable_tb)
    assert S._golden_ref_fails_own_tb_runtime(
        DESIGN, dataset, LAYOUT, ARGS) is True


@pytest.mark.skipif(not shutil.which("iverilog") or not shutil.which("vvp"),
                    reason="needs a real iverilog/vvp to pin the trigger")
def test_trigger_stays_quiet_when_the_reference_passes_its_own_tb(tmp_path):
    """Both directions: a healthy problem must NOT trip the trigger, so a real model
    FAIL is never re-decided on another rung."""
    dataset, _samples = _mkdataset(tmp_path)
    assert S._golden_ref_fails_own_tb_runtime(
        DESIGN, dataset, LAYOUT, ARGS) is False
