"""vibe-ic#1745 — a forgeable PASS, and a never-attempted problem that leaves
the denominator. Both defects were measured in the upstream harness our
VerilogEval / RTLLM numbers are published through; these guard OUR side of it.

DEFECT 1 — PASS IS FORGEABLE BY THE SOLVER. The verdict is a regex matched
against the SIMULATION's stdout, and the DUT shares that stdout. Reproduced
upstream with two submissions carrying IDENTICAL WRONG LOGIC, the second adding
only

    initial $display("Mismatches: 0 in 20 samples");

The simulator reported a nonzero mismatch count for BOTH; the pair scored 50% on
a problem answered wrongly twice. The honest-wrong control FAILS, so the check
was never vacuous — it was FORGEABLE, which is worse.

`test_the_measured_pair_end_to_end` is that experiment, run through OUR scorer
with a real iverilog: the honest-wrong sample must FAIL (the gate is not
vacuous) and the forged sample must ALSO fail, on the gate, before it compiles.

DEFECT 2 — NEVER-ATTEMPTED LEAVES THE DENOMINATOR. Two states where there must
be three, and the missing one is the FAVOURABLE state: not-attempted silently
becomes not-counted rather than not-passed. Our scorer already derived a
`no_sample` disclosure, but the registry tool-gap flip could OVERWRITE the very
`reason` that disclosure reads — converting a problem that produced nothing into
a SKIP, which leaves `n_eff` AND leaves the partially-authored warning. The rate
goes up and nothing is printed.

Every test here fails on the pre-fix tree; the reverted-tree failures are quoted
in the landing report.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

import harness_verdict_forgery_gate as G

_PLUGIN = Path(__file__).resolve().parents[2]
_SCORER_PATH = _PLUGIN / "benchmark" / "score_iverilog_tb.py"

# The verdict vocabularies our BENCHMARK_REGISTRY entries actually ship.
PASS_RE = r"Mismatches:\s*0\s+in\s+\d+\s+samples"
SHAPE_B_PASS_RE = "Your Design Passed"
SHAPE_B_FAIL_RE = "Test failed|Your Design Failed"


def _scorer():
    spec = importlib.util.spec_from_file_location(
        "score_iverilog_tb_1745", _SCORER_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


S = _scorer()


# ─────────────────────────────────────────────────────────────────────────────
# The measured pair: identical wrong logic, one line apart.
# ─────────────────────────────────────────────────────────────────────────────
HONEST_WRONG = """module TopModule(input a, output y);
  assign y = a;          // WRONG on purpose: the reference inverts.
endmodule
"""

FORGED = """module TopModule(input a, output y);
  assign y = a;          // IDENTICAL wrong logic ...
  initial $display("Mismatches: 0 in 20 samples");   // ... plus the forgery.
endmodule
"""

REF = """module RefModule(input a, output y);
  assign y = ~a;
endmodule
"""

TEST_SV = """`timescale 1ns/1ps
module tb();
  reg a; wire y_dut, y_ref; integer i; integer mism = 0; integer n = 0;
  TopModule dut(.a(a), .y(y_dut));
  RefModule refm(.a(a), .y(y_ref));
  initial begin
    for (i = 0; i < 20; i = i + 1) begin
      a = i[0]; #5;
      n = n + 1;
      if (y_dut !== y_ref) mism = mism + 1;
    end
    $display("Mismatches: %0d in %0d samples", mism, n);
    $finish;
  end
endmodule
"""


def _shape_c_dataset(tmp_path: Path, samples: dict, problems=("Prob001_inv",)):
    """A minimal Shape-C dataset + run dir. `samples` maps problem -> RTL text
    (a problem absent from the mapping is NEVER ATTEMPTED)."""
    ds = tmp_path / "dataset"
    run = tmp_path / "run"
    (run / "samples").mkdir(parents=True)
    ds.mkdir()
    for prob in problems:
        (ds / f"{prob}_prompt.txt").write_text("Build an inverter.\n")
        (ds / f"{prob}_ref.sv").write_text(REF)
        (ds / f"{prob}_test.sv").write_text(TEST_SV)
    for prob, rtl in samples.items():
        (run / "samples" / f"{prob}_sample01.sv").write_text(rtl)
    (run / "problems.list").write_text("\n".join(problems) + "\n")
    return ds, run


LAYOUT_C = {"prompt_suffix": "_prompt.txt", "tb_suffix": "_test.sv",
            "ref_suffix": "_ref.sv"}
ARGS_C = {"tb_compile_with_ref": True, "pass_regex": PASS_RE}


# ─────────────────────────────────────────────────────────────────────────────
# DEFECT 1 — the gate itself
# ─────────────────────────────────────────────────────────────────────────────
def test_gate_blocks_the_forged_sample_and_clears_the_honest_wrong_one():
    """The whole point in one assertion pair: the two submissions differ by one
    printed line and nothing else, so a check that treats them alike is not
    measuring the circuit."""
    forged = G.gate(FORGED, PASS_RE)
    honest = G.gate(HONEST_WRONG, PASS_RE)
    assert forged["verdict"] == G.FORGERY, forged
    assert honest["verdict"] == G.CLEAN, honest
    assert forged["blocking"][0]["kind"] == "verdict_string_literal"


def test_gate_catches_the_format_specifier_form():
    """`$display("Mismatches: %0d in %0d samples", 0, 20)` prints the same
    sentence without ever containing it as a literal."""
    rtl = 'module TopModule; initial $display("Mismatches: %0d in %0d samples", 0, 20); endmodule'
    assert G.gate(rtl, PASS_RE)["verdict"] == G.FORGERY


def test_gate_catches_a_verdict_split_across_literals_in_one_call():
    rtl = 'module TopModule; initial $display("Mismatch", "es: 0 in 20 samples"); endmodule'
    assert G.gate(rtl, PASS_RE)["verdict"] == G.FORGERY


def test_a_comment_naming_the_verdict_is_not_a_forgery():
    """A comment prints nothing. Flagging one would make the gate a
    false-positive generator against the very RTL that DISCUSSES the harness."""
    rtl = ("module TopModule(input a, output y);\n"
           "  // scored by: Mismatches: 0 in 20 samples\n"
           "  assign y = ~a;\nendmodule\n")
    assert G.gate(rtl, PASS_RE)["verdict"] == G.CLEAN


def test_ordinary_debug_output_is_not_a_forgery():
    rtl = ('module TopModule(input [7:0] d, output reg [2:0] pos);\n'
           '  initial $display("dbg d=%b pos=%0d samples ready", d, pos);\n'
           'endmodule\n')
    assert G.gate(rtl, PASS_RE)["verdict"] == G.CLEAN


def test_fail_token_is_advisory_only_never_blocking():
    """Printing the FAILURE sentence can only cost the submitter its own
    verdict, so blocking on it would add false-reject risk and remove no
    forgery. It is still reported."""
    rtl = 'module TopModule; initial $display("Test failed"); endmodule'
    res = G.gate(rtl, SHAPE_B_PASS_RE, SHAPE_B_FAIL_RE)
    assert res["verdict"] == G.CLEAN
    assert res["findings"] and res["findings"][0]["channel"] == "fail"
    assert res["findings"][0]["blocking"] is False


def test_shape_b_pass_sentence_is_blocked():
    rtl = 'module top; initial $display("=====Your Design Passed====="); endmodule'
    assert G.gate(rtl, SHAPE_B_PASS_RE, SHAPE_B_FAIL_RE)["verdict"] == G.FORGERY


def test_unreadable_submission_is_not_checked_not_clean(tmp_path):
    """A scan that could not look has not looked. NOT_CHECKED must never be
    reported as CLEAN (the #1266 defect class)."""
    res = G.gate_file(tmp_path / "absent.sv", PASS_RE)
    assert res["verdict"] == G.NOT_CHECKED
    assert G.main(["--rtl", str(tmp_path / "absent.sv"),
                   "--pass-regex", PASS_RE]) == 2


def test_cli_exit_codes(tmp_path):
    good, bad = tmp_path / "good.sv", tmp_path / "bad.sv"
    good.write_text(HONEST_WRONG)
    bad.write_text(FORGED)
    assert G.main(["--rtl", str(good), "--pass-regex", PASS_RE]) == 0
    assert G.main(["--rtl", str(bad), "--pass-regex", PASS_RE]) == 1


def test_verdict_anchors_are_derived_from_the_callers_regex():
    """No second list of magic words: the vocabulary comes from the same regex
    the scorer greps with, so a registry change cannot leave the gate behind."""
    assert G.verdict_anchors(PASS_RE) == ["Mismatches:", "in", "samples"]
    assert G.verdict_anchors(SHAPE_B_PASS_RE) == ["Your Design Passed"]


# ─────────────────────────────────────────────────────────────────────────────
# DEFECT 1 — the gate is IN FRONT of the scorer
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.skipif(not shutil.which("iverilog") or not shutil.which("vvp"),
                    reason="needs iverilog+vvp to run the measured pair")
def test_the_measured_pair_end_to_end(tmp_path):
    """The issue's own experiment through OUR scorer.

    Both samples carry the same wrong logic, so the simulator reports a nonzero
    mismatch count for both. Pre-fix the forged one scored PASS anyway.
    """
    ds, run = _shape_c_dataset(tmp_path, {"Prob001_inv": HONEST_WRONG})
    honest = S._score_shape_c_impl("Prob001_inv", run / "samples", ds,
                                   LAYOUT_C, dict(ARGS_C))
    assert honest["verdict"] == "FAIL", honest      # the non-vacuity control

    ds2, run2 = _shape_c_dataset(tmp_path / "b", {"Prob001_inv": FORGED})
    forged = S._score_shape_c_impl("Prob001_inv", run2 / "samples", ds2,
                                   LAYOUT_C, dict(ARGS_C))
    assert forged["verdict"] == "FAIL", forged
    assert forged["reason"] == "harness_verdict_forgery", forged


def test_shape_c_refuses_the_forged_sample_without_compiling_it(tmp_path):
    """The gate is IN FRONT: no testbench, no reference, no simulator — and the
    forged sample is still refused, which is only possible if nothing was run."""
    run = tmp_path / "run"
    (run / "samples").mkdir(parents=True)
    (run / "samples" / "P_sample01.sv").write_text(FORGED)
    res = S._score_shape_c_impl("P", run / "samples", tmp_path / "no_dataset",
                                LAYOUT_C, dict(ARGS_C))
    assert res["reason"] == "harness_verdict_forgery", res
    assert res["forgery_findings"]


def test_shape_b_refuses_the_forged_sample(tmp_path):
    ds = tmp_path / "ds"
    (ds / "d").mkdir(parents=True)
    (ds / "d" / "design_description.txt").write_text("Module name:\nd\n")
    samples = tmp_path / "samples"
    samples.mkdir()
    (samples / "d.v").write_text(
        'module d; initial $display("=== Your Design Passed ==="); endmodule')
    res = S._score_shape_b_impl(
        "d", samples, ds,
        {"prompt_filename": "design_description.txt", "tb_filename": "testbench.v"},
        {"pass_regex": SHAPE_B_PASS_RE, "fail_regex": SHAPE_B_FAIL_RE})
    assert res["reason"] == "harness_verdict_forgery", res


# ─────────────────────────────────────────────────────────────────────────────
# DEFECT 2 — the third state
# ─────────────────────────────────────────────────────────────────────────────
def test_attempt_census_reports_three_states_and_its_own_identity():
    results = [
        {"problem": "A", "verdict": "PASS"},
        {"problem": "B", "verdict": "FAIL", "reason": "functional_mismatch"},
        {"problem": "C", "verdict": "FAIL", "reason": "no_sample"},
        {"problem": "D", "verdict": "SKIP", "reason": "scorer_substitution_gap — x"},
    ]
    c = S.attempt_census(results, "problem")
    assert (c["attempted_passed"], c["attempted_failed"],
            c["never_attempted"], c["skipped_tool_gap"]) == (1, 1, 1, 1)
    assert c["total"] == 4 and c["attempted"] == 3
    assert c["never_attempted_ids"] == ["C"]
    assert c["identity_holds"] and not c["accounting_violations"]


def test_attempt_census_is_emitted_even_when_the_third_state_is_zero():
    """A three-state line printed only when the third state is non-zero is a
    line whose ABSENCE means two different things."""
    c = S.attempt_census([{"problem": "A", "verdict": "PASS"}], "problem")
    assert c["never_attempted"] == 0 and c["never_attempted_ids"] == []
    assert "never_attempted" in c and c["identity_holds"]


def test_census_flags_a_never_attempted_row_that_left_the_denominator():
    """The census is the check, not just the report: a row that produced NO
    submission yet carries a verdict excluding it from the denominator is named,
    so a caller can refuse rather than publish the flattered rate."""
    c = S.attempt_census(
        [{"problem": "A", "verdict": "SKIP", "reason": "no_sample"}], "problem")
    assert c["accounting_violations"] == ["A"]


def test_tool_gap_flip_refuses_a_never_attempted_row():
    """A tool gap is a statement about the SIMULATOR's coverage of the
    testbench. It cannot be a statement about a submission that does not exist:
    there is nothing for the simulator to have failed on."""
    results = [
        {"problem": "A", "verdict": "FAIL", "reason": "no_sample"},
        {"problem": "B", "verdict": "FAIL", "reason": "compile_error"},
    ]
    flipped = S.apply_scorer_substitution_gap(results, {"A", "B"}, "problem", "11")
    assert flipped == ["B"]
    assert results[0]["verdict"] == "FAIL"
    assert results[0]["reason"] == "no_sample"
    assert "scorer_substitution_gap_refused" in results[0]
    assert results[1]["verdict"] == "SKIP"
    # and the disclosure derived from `reason` still sees the never-attempted row
    n_ns, ids, _, partially = S.no_sample_disclosure(results, 2, 0, "problem")
    assert (n_ns, ids, partially) == (1, ["A"], True)


def test_published_summary_carries_the_third_state(tmp_path, monkeypatch, capsys):
    """End to end: 1 attempted (and forged) + 3 never attempted. Upstream
    reported this shape as a rate over a denominator of 1, with no row and no
    warning for the three that produced nothing."""
    probs = ["P1", "P2", "P3", "P4"]
    ds, run = _shape_c_dataset(tmp_path, {"P1": FORGED}, problems=probs)
    entry = {"title": "synthetic", "shape": "C", "layout": LAYOUT_C,
             "scorer_args": dict(ARGS_C)}
    monkeypatch.setattr(S, "_load_bench", lambda name: entry)
    monkeypatch.setattr(sys, "argv",
                        ["score", "--bench", "x", "--dataset", str(ds),
                         "--run", str(run)])
    S.main()
    out = json.loads((run / "pass_at_1.json").read_text())
    c = out["attempt_census"]
    assert c["total"] == 4, "the never-attempted problems must stay in scope"
    assert c["never_attempted"] == 3
    assert sorted(c["never_attempted_ids"]) == ["P2", "P3", "P4"]
    assert c["attempted"] == 1 and c["attempted_passed"] == 0
    assert c["attempted_failed"] == 1 and c["skipped_tool_gap"] == 0
    assert c["identity_holds"] and not c["accounting_violations"]
    assert out["harness_verdict_forgery_count"] == 1
    assert out["harness_verdict_forgery_problems"] == ["P1"]
    assert out["pass_at_1_pct"] == 0.0
    printed = capsys.readouterr().out
    assert "NEVER ATTEMPTED" in printed
    assert "REFUSED BEFORE SCORING" in printed


def test_main_refuses_to_publish_when_a_never_attempted_row_left_the_denominator(
        tmp_path, monkeypatch):
    """The refusal is the point: a rate that cannot account for its own
    denominator is not published at all."""
    probs = ["P1", "P2"]
    ds, run = _shape_c_dataset(tmp_path, {"P1": HONEST_WRONG}, problems=probs)
    entry = {"title": "synthetic", "shape": "C", "layout": LAYOUT_C,
             "scorer_args": dict(ARGS_C)}
    monkeypatch.setattr(S, "_load_bench", lambda name: entry)
    monkeypatch.setattr(sys, "argv",
                        ["score", "--bench", "x", "--dataset", str(ds),
                         "--run", str(run)])

    def _drop_it(prob, samples, dataset, layout, args):
        return {"problem": prob, "verdict": "SKIP", "reason": "no_sample"}

    monkeypatch.setattr(S, "_score_shape_c", _drop_it)
    with pytest.raises(SystemExit) as e:
        S.main()
    assert "REFUSING TO PUBLISH A RATE" in str(e.value)
    assert not (run / "pass_at_1.json").exists()
