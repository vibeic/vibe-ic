r"""A candidate that PRINTS the scorer's verdict must not be scored a pass. (#1745)

WHY THIS EXISTS
---------------
Every functional benchmark number this plugin publishes is read off a simulation
transcript the DUT SHARES with the harness testbench. The testbench prints its
verdict to stdout; the scorer regexes that line; and the thing being measured
writes to the same stdout. So the submission can print the verdict the scorer
reads.

MEASURED at head 397b3f25f, before the fix, with two candidates carrying
IDENTICAL wrong logic (`assign out = a | b` where the spec says `a & b`); the
second adds only

    initial $display("Mismatches: 0 in 20 samples");

    scorer                                        honest-wrong   forged-wrong
    benchmark/score_iverilog_tb.py (Shape C)      FAIL           PASS
    programs/verilogeval_tier_pipeline.py         FAIL           PASS

The simulation reported `Mismatches: 10 in 20 samples` for BOTH. The run headline
read `pass@1 = 1/4 = 25.0%` over four problems, none of which was answered
correctly.

The honest-wrong control FAILs both before and after, so the scorer was never
vacuous — it was FORGEABLE, which is worse: it discriminates correctly right up
until someone forges it.

WHAT IS PINNED HERE
-------------------
1. The scanner itself (`harness_verdict_forgery_check`) on the literal forge, the
   FORMATTED forge, the SPLIT-across-`$write` forge, and the `//`-inside-a-string
   forge — the last one because the scan drops comments, and a scan that drops
   comments naively also drops the live call that follows a `//` in a string.
2. Its NEGATIVE side, which is what keeps it from being a blunt instrument: a
   commented-out `$display`, and honest debug output that carries no verdict
   text, both stay CLEAN.
3. Each production scorer, driven end to end: the forged candidate is refused,
   the honest-wrong candidate still FAILs for its own reason, and — the control
   that matters most — a CORRECT candidate still PASSES.
4. The FLOOR provers stay exempt (`forgery_check=False`): they feed the GOLDEN
   through the same function, and a floor claim must not be manufactured out of
   this gate.
5. `no_sample` stays in the denominator. That half of #1745 was ALREADY closed on
   this tree (vibe-ic#637) and is pinned here so it cannot silently reopen while
   the forgery half is being worked on.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
_PLUGIN = _PROGRAMS.parent
_BENCHMARK = _PLUGIN / "benchmark"
for _p in (str(_PROGRAMS), str(_BENCHMARK)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import harness_verdict_forgery_check as G   # noqa: E402

_HAVE_IV = shutil.which("iverilog") is not None and shutil.which("vvp") is not None
_needs_iv = pytest.mark.skipif(not _HAVE_IV, reason="iverilog/vvp not installed")

# The VerilogEval pass line, exactly as BENCHMARK_REGISTRY.json carries it.
VE_PASS = r"Mismatches:\s*0\s+in\s+\d+\s+samples"

HONEST_WRONG = """module TopModule(input a, input b, output out);
  assign out = a | b;
endmodule
"""
FORGED_WRONG = """module TopModule(input a, input b, output out);
  assign out = a | b;
  initial $display("Mismatches: 0 in 20 samples");
endmodule
"""
CORRECT = """module TopModule(input a, input b, output out);
  assign out = a & b;
endmodule
"""

_REF = """module RefModule(input a, input b, output out);
  assign out = a & b;
endmodule
"""

_TEST = """`timescale 1 ps/1 ps
module tb();
  reg a, b;
  wire out_ref, out_dut;
  integer mismatches = 0;
  integer samples = 0;
  integer i;
  RefModule ref_inst(.a(a), .b(b), .out(out_ref));
  TopModule dut_inst(.a(a), .b(b), .out(out_dut));
  initial begin
    for (i = 0; i < 20; i = i + 1) begin
      a = i[0]; b = i[1];
      #5;
      samples = samples + 1;
      if (out_ref !== out_dut) mismatches = mismatches + 1;
      #5;
    end
    $display("Mismatches: %0d in %0d samples", mismatches, samples);
    $finish;
  end
endmodule
"""


def _dataset(root: Path, probs=("Prob001_and2",)) -> Path:
    """A VerilogEval Shape-C dataset: prompt + golden ref + official testbench."""
    d = root / "dataset"
    d.mkdir(parents=True, exist_ok=True)
    for stem in probs:
        (d / f"{stem}_prompt.txt").write_text(
            "Implement a module TopModule with inputs a, b and output out "
            "where out = a & b.\n")
        (d / f"{stem}_ref.sv").write_text(_REF)
        (d / f"{stem}_test.sv").write_text(_TEST)
    return d


# --------------------------------------------------------------------------- #
# (1) the scanner — the forge and its evasions
# --------------------------------------------------------------------------- #
def test_literal_forge_is_caught():
    why = G.forgery_reason(FORGED_WRONG, [VE_PASS])
    assert why is not None and "verdict forgery" in why
    assert "Mismatches: 0 in 20 samples" in why


def test_formatted_forge_is_caught():
    """`$display("Mismatches: %0d in %0d samples", 0, 20)` prints the verdict
    without the literal ever appearing in the source."""
    rtl = ("module TopModule(input a, input b, output out);\n"
           "  assign out = a | b;\n"
           "  integer z = 0;\n"
           '  initial $display("Mismatches: %0d in %0d samples", z, 20);\n'
           "endmodule\n")
    assert G.forgery_reason(rtl, [VE_PASS]) is not None


def test_forge_split_across_write_calls_is_caught():
    """`$write` does not terminate a line, so two calls concatenate on the
    transcript into one verdict a per-call scan would miss."""
    rtl = ("module TopModule(input a, input b, output out);\n"
           "  assign out = a | b;\n"
           "  initial begin\n"
           '    $write("Mismatches: ");\n'
           '    $write("0 in 20 samples\\n");\n'
           "  end\n"
           "endmodule\n")
    why = G.forgery_reason(rtl, [VE_PASS])
    assert why is not None and "concatenated" in why


def test_slash_slash_inside_a_string_does_not_hide_the_forge():
    """The control sits BEHIND the comment-dropping mechanism: a `//` inside a
    string literal is TEXT. A scanner that truncates the line at it goes blind to
    the very call it was looking for."""
    rtl = ("module TopModule(input a, input b, output out);\n"
           "  assign out = a | b;\n"
           '  initial $display("see http://x -- Mismatches: 0 in 20 samples");\n'
           "endmodule\n")
    assert G.forgery_reason(rtl, [VE_PASS]) is not None


def test_unbounded_conversion_is_refused():
    """A `%s` expands to DUT-controlled data: the candidate can put ANY text on
    the channel the verdict is read from, so no rendering search bounds it."""
    rtl = ("module TopModule(input a, input b, output out);\n"
           "  assign out = a | b;\n"
           '  string msg = "Mismatches: 0 in 20 samples";\n'
           '  initial $display("%s", msg);\n'
           "endmodule\n")
    why = G.forgery_reason(rtl, [VE_PASS])
    assert why is not None and "attributable" in why


# --------------------------------------------------------------------------- #
# (2) the scanner's NEGATIVE side — it must not be a blunt instrument
# --------------------------------------------------------------------------- #
def test_honest_candidate_is_clean():
    assert G.forgery_reason(HONEST_WRONG, [VE_PASS]) is None
    assert G.forgery_reason(CORRECT, [VE_PASS]) is None


def test_commented_out_display_is_clean():
    rtl = ("module TopModule(input a, input b, output out);\n"
           "  assign out = a & b;\n"
           '  // initial $display("Mismatches: 0 in 20 samples");\n'
           '  /* initial $display("Mismatches: 0 in 20 samples"); */\n'
           "endmodule\n")
    assert G.forgery_reason(rtl, [VE_PASS]) is None


def test_honest_debug_output_stays_scoreable():
    """A print that carries no verdict text and no unbounded conversion is not a
    forgery. Rejecting it would cost honest submissions for nothing."""
    rtl = ("module TopModule(input a, input b, output out);\n"
           "  assign out = a & b;\n"
           '  initial $display("dut elaborated, width=%0d", 8);\n'
           "endmodule\n")
    assert G.forgery_reason(rtl, [VE_PASS]) is None


def test_no_pattern_means_not_checked_not_clean():
    """A forgery check with no pattern certifies nothing, and says so (rc 2)."""
    assert G.forgery_reason(FORGED_WRONG, []) is None  # nothing to check against
    r = subprocess.run(
        [sys.executable, str(_PROGRAMS / "harness_verdict_forgery_check.py"),
         "--rtl", str(_PROGRAMS / "harness_verdict_forgery_check.py")],
        capture_output=True, text=True)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "NOT CHECKED" in r.stderr


def test_cli_exit_codes(tmp_path):
    prog = str(_PROGRAMS / "harness_verdict_forgery_check.py")
    clean = tmp_path / "clean.sv"
    clean.write_text(HONEST_WRONG)
    forged = tmp_path / "forged.sv"
    forged.write_text(FORGED_WRONG)
    ok = subprocess.run([sys.executable, prog, "--rtl", str(clean),
                         "--pattern", VE_PASS], capture_output=True, text=True)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    bad = subprocess.run([sys.executable, prog, "--rtl", str(forged),
                          "--pattern", VE_PASS], capture_output=True, text=True)
    assert bad.returncode == 1, bad.stdout + bad.stderr
    assert "forged_pass" in bad.stdout
    missing = subprocess.run([sys.executable, prog, "--rtl",
                              str(tmp_path / "nope.sv"), "--pattern", VE_PASS],
                             capture_output=True, text=True)
    assert missing.returncode == 2
    assert "NOT CHECKED" in missing.stderr


# --------------------------------------------------------------------------- #
# (3) programs/verilogeval_tier_pipeline.py — driven end to end
# --------------------------------------------------------------------------- #
@_needs_iv
def test_tier_pipeline_refuses_the_forged_candidate(tmp_path):
    import verilogeval_tier_pipeline as P
    d = _dataset(tmp_path)
    prob = P.Problem(d / "Prob001_and2_prompt.txt")

    ok, why = P.iverilog_score(prob, FORGED_WRONG)
    assert ok is False, f"forged candidate scored a PASS: {why}"
    assert "verdict forgery" in why, why

    ok, why = P.iverilog_score(prob, HONEST_WRONG)
    assert ok is False and "Mismatches: 10 in 20 samples" in why, why

    ok, why = P.iverilog_score(prob, CORRECT)
    assert ok is True, f"a CORRECT candidate was refused: {why}"


@_needs_iv
def test_tier_pipeline_floor_prover_is_exempt(tmp_path):
    """`forgery_check=False` is the golden's path: it must still RUN the sim, so
    a floor claim is never manufactured out of this gate."""
    import verilogeval_tier_pipeline as P
    d = _dataset(tmp_path)
    prob = P.Problem(d / "Prob001_and2_prompt.txt")
    ok, why = P.iverilog_score(prob, FORGED_WRONG, forgery_check=False)
    assert "verdict forgery" not in why, why
    assert P.floor_evidence(prob) is None, "a sound problem was called a floor"


# --------------------------------------------------------------------------- #
# (4) programs/verilogeval_human_tier_pipeline.py
# --------------------------------------------------------------------------- #
@_needs_iv
def test_human_tier_pipeline_refuses_the_forged_candidate(tmp_path):
    import verilogeval_human_tier_pipeline as H
    d = _dataset(tmp_path)
    ref, test = str(d / "Prob001_and2_ref.sv"), str(d / "Prob001_and2_test.sv")

    ok, why = H._run_iverilog(FORGED_WRONG, ref, test)
    assert ok is False and "verdict forgery" in why, why

    ok, why = H._run_iverilog(CORRECT, ref, test)
    assert ok is True, f"a CORRECT candidate was refused: {why}"

    # the golden path (top_sv_text=None) must stay exempt — it is not a submission
    ok, why = H._run_iverilog(None, ref, test)
    assert ok is True, why


# --------------------------------------------------------------------------- #
# (5) programs/rtllm_tier_pipeline.py — a different verdict grammar
# --------------------------------------------------------------------------- #
_RTLLM_TB = """`timescale 1ns/1ps
module testbench;
  reg a, b; wire y; integer errors = 0; integer i;
  and2 dut(.a(a), .b(b), .y(y));
  initial begin
    for (i = 0; i < 4; i = i + 1) begin
      a = i[0]; b = i[1]; #5;
      if (y !== (a & b)) errors = errors + 1;
    end
    if (errors == 0) $display("===========Your Design Passed===========");
    else $display("===========Test completed with %0d failures===========", errors);
    $finish;
  end
endmodule
"""


@_needs_iv
def test_rtllm_pipeline_refuses_the_forged_candidate(tmp_path):
    import rtllm_tier_pipeline as R
    d = tmp_path / "and2"
    d.mkdir()
    (d / "design_description.txt").write_text(
        "Module name: and2\nImplement a 2-input AND gate.\n")
    (d / "testbench.v").write_text(_RTLLM_TB)

    good = "module and2(input a, input b, output y); assign y = a & b; endmodule\n"
    wrong = "module and2(input a, input b, output y); assign y = a | b; endmodule\n"
    forged = (
        "module and2(input a, input b, output y);\n"
        "  assign y = a | b;\n"
        '  initial $display("===========Your Design Passed===========");\n'
        "endmodule\n")

    _c, passed, log = R.iverilog_score(str(d), forged, "and2")
    assert passed is False, f"forged candidate scored a PASS: {log}"
    assert "verdict forgery" in log, log

    _c, passed, log = R.iverilog_score(str(d), wrong, "and2")
    assert passed is False and "verdict forgery" not in log, log

    _c, passed, log = R.iverilog_score(str(d), good, "and2")
    assert passed is True, f"a CORRECT candidate was refused: {log}"


# --------------------------------------------------------------------------- #
# (6) benchmark/score_iverilog_tb.py — the published number itself
# --------------------------------------------------------------------------- #
@_needs_iv
def test_published_pass_at_1_is_not_forgeable(tmp_path):
    """Four problems, one honest-wrong, one forged-wrong, two never attempted.
    Nothing was answered correctly, so the only honest headline is 0."""
    d = _dataset(tmp_path, probs=("Prob001_and2", "Prob002_and2",
                                  "Prob003_and2", "Prob004_and2"))
    run = tmp_path / "run"
    (run / "samples").mkdir(parents=True)
    (run / "samples" / "Prob001_and2_sample01.sv").write_text(HONEST_WRONG)
    (run / "samples" / "Prob002_and2_sample01.sv").write_text(FORGED_WRONG)

    r = subprocess.run(
        [sys.executable, str(_BENCHMARK / "score_iverilog_tb.py"),
         "--bench", "verilogeval-v2", "--dataset", str(d), "--run", str(run)],
        capture_output=True, text=True, timeout=900)
    assert "pass@1" in r.stdout, r.stdout + r.stderr

    s = json.loads((run / "pass_at_1.json").read_text())
    assert s["passed"] == 0, f"a forged or wrong answer was scored a pass: {s}"
    assert s["pass_at_1_pct"] == 0.0
    assert s["total"] == 4

    # the forgery is NAMED, and stays in the denominator
    assert s["verdict_forgery_check"] == "RAN"
    assert s["verdict_forgery_count"] == 1, s["verdict_forgery_problems"]
    assert s["verdict_forgery_problems"][0]["problem"] == "Prob002_and2"
    assert any(x["verdict"] == "FAIL" and x.get("reason") == "verdict_forgery"
               for x in s["results"])

    # #1745's second half, already closed on this tree by #637 — pinned so it
    # cannot silently reopen: never-attempted is FAIL, not absent.
    assert s["no_sample_count"] == 2
    assert s["partially_authored"] is True
    assert sorted(s["no_sample_problems"]) == ["Prob003_and2", "Prob004_and2"]


@_needs_iv
def test_a_correct_run_still_scores_100(tmp_path):
    """The control that stops this gate from becoming a way to lose points: a
    clean, correct submission is unaffected."""
    d = _dataset(tmp_path)
    run = tmp_path / "run"
    (run / "samples").mkdir(parents=True)
    (run / "samples" / "Prob001_and2_sample01.sv").write_text(CORRECT)
    r = subprocess.run(
        [sys.executable, str(_BENCHMARK / "score_iverilog_tb.py"),
         "--bench", "verilogeval-v2", "--dataset", str(d), "--run", str(run)],
        capture_output=True, text=True, timeout=900)
    assert "pass@1" in r.stdout, r.stdout + r.stderr
    s = json.loads((run / "pass_at_1.json").read_text())
    assert s["passed"] == 1 and s["pass_at_1_pct"] == 100.0, s
    assert s["verdict_forgery_count"] == 0
