"""Step-2.7 §4.05 hardening of PR #48's verilator_timing_fallback_check
(gatekeeper remediation). The guard decides FLOOR-vs-recoverable by running the
dataset's own golden through the TB under Verilator: a clean golden PASS -> rc 0
FAITHFUL (recover the floor + score under Verilator); else FLOOR stands. The
DANGEROUS direction is FALSE-FAITHFUL (declare an actually-failing/crashed golden
a pass -> recover a NON-real floor -> inflate the published number).

Step-2.7 reproduced four FALSE-FAITHFUL vectors; all remediated:
  (token)      substring pass-match: "successful" in "unsuccessful", "PASS" in
               "bypass" -> WORD-BOUNDARY matching.
  (default)    generic default tokens "PASS"/"Passed"/"successful" matched benign
               status lines ("Reset successful") -> default tightened to the
               SPECIFIC RTLLM verdict phrase only.
  (exit code)  a pass token then $fatal/crash (non-zero exit) -> require exit 0.
  (fail veto)  an unconditional/degenerate-pass TB that also prints a mismatch ->
               veto FAITHFUL on any co-occurring failure token.
  (timeout)    a hanging TB -> bounded subprocess timeouts (build 300s / sim 120s).
"""
import re
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import verilator_timing_fallback_check as V  # noqa: E402

_HAVE = V.verilator_available()


def _has(out, tokens):
    res = [re.compile(r"\b" + re.escape(t) + r"\b", re.IGNORECASE) for t in tokens]
    return any(r.search(out) for r in res)


# ── unit: default pass token is the SPECIFIC verdict, not a generic status word ─
def test_default_pass_token_is_specific_not_generic():
    assert V._DEFAULT_PASS == ("Your Design Passed",)
    assert _has("===Your Design Passed===", V._DEFAULT_PASS)
    # benign status lines must NOT register as a pass via the default token
    for benign in ("Reset successful, beginning vectors", "Compilation successful",
                   "bypass mode", "all vectors PASS through the pipe"):
        assert not _has(benign, V._DEFAULT_PASS), benign


def test_rename_top_touches_only_the_declaration_not_strings_or_comments():
    # Step-2.7 LOW: the blanket whole-word rename also rewrote the name inside
    # string literals / comments; the declaration-only rename must not.
    src = ('module refmod(input clk, output reg q);\n'
           '  // refmod note: keep this refmod text\n'
           '  initial $display("refmod start");\n'
           '  always @(posedge clk) q <= 1;\nendmodule\n')
    out = V._rename_top(src, "refmod", "dut")
    assert "module dut(" in out
    assert "refmod note: keep this refmod text" in out   # comment untouched
    assert '"refmod start"' in out                       # string untouched
    assert V._rename_top("module a;\nendmodule\n", "a", "a") == "module a;\nendmodule\n"


def test_word_boundary_protects_operator_supplied_generic_tokens():
    # even when an operator widens to generic tokens, word-boundary stops a FAIL
    # word from substring-matching a pass word.
    toks = ["successful", "PASS", "Passed"]
    for fail_out in ("Test unsuccessful", "bypass mode\nFailed", "surpassed tolerance"):
        assert not _has(fail_out, toks), fail_out
    for pass_out in ("Test successful", "Simulation PASS", "Design Passed"):
        assert _has(pass_out, toks), pass_out


# ── E2E: the verdict hardening (needs verilator) ──────────────────────────────
_GOK = "module dut(input clk, output reg [3:0] q);\n initial q=4'd5;\n always @(posedge clk) q<=4'd5;\nendmodule\n"
_GBAD = "module dut(input clk, output reg [3:0] q);\n initial q=4'd6;\n always @(posedge clk) q<=4'd6;\nendmodule\n"
_TB_CANON = (
    "module tb;\n reg clk=0; wire [3:0] q; reg [3:0] expq [0:1]; integer err=0;\n"
    " dut uut(.clk(clk),.q(q));\n always #5 clk=~clk;\n initial begin\n  expq='{4'd5,4'd5}; #20;\n"
    "  if (q!==expq[0]) begin err=err+1; $display(\"Failed at 0: got %d\",q); end\n"
    "  if (err==0) $display(\"===========Your Design Passed===========\");"
    " else $display(\"===========Failed===========\");\n  $finish;\n end\nendmodule\n")
# prints the pass token then aborts non-zero (a Verilator crash where VCS would not)
_TB_FATAL = (
    "module tb;\n reg clk=0; wire [3:0] q; dut uut(.clk(clk),.q(q)); always #5 clk=~clk;\n"
    " initial begin #20;\n  $display(\"===========Your Design Passed===========\");\n"
    "  $fatal(1,\"boom\");\n end\nendmodule\n")
# a PASSING golden whose TB prints a benign ZERO-count summary alongside the pass
# marker — the official RTLLM scorer (score_rtllm.py) TOLERATES this; the guard
# must too (must NOT over-floor it).
_TB_PASS_ZEROCOUNT = (
    "module tb;\n reg clk=0; wire [3:0] q; integer err=0; dut uut(.clk(clk),.q(q)); always #5 clk=~clk;\n"
    " initial begin #20;\n  if (q!==4'd5) err=err+1;\n"
    "  $display(\"%0d/100 failures\", err);\n  $display(\"Error count: %0d\", err);\n"
    "  $display(\"No mismatch detected.\");\n"
    "  if (err==0) $display(\"===========Your Design Passed===========\");"
    " else $display(\"===========Test failed===========\");\n $finish;\n end\nendmodule\n")


def _adj(tmp, golden, tb, pass_t=None, fail_t=None):
    g = tmp / "g.v"; g.write_text(golden)
    t = tmp / "t.v"; t.write_text(tb)
    return V.adjudicate(t, g, "tb", "dut", "dut", None,
                        pass_t or list(V._DEFAULT_PASS),
                        fail_t or list(V._DEFAULT_FAIL))


def test_default_fail_tokens_are_the_real_failure_markers():
    # mirror the official scorer: veto only on a real failure verdict, NOT on the
    # generic words "failures"/"Error"/"mismatch" (those appear in tolerated
    # zero-count summary lines).
    assert V._DEFAULT_FAIL == ("Test failed", "Your Design Failed")


@pytest.mark.skipif(not _HAVE, reason="verilator absent")
def test_canonical_recovery_preserved(tmp_path):
    rc, _ = _adj(tmp_path, _GOK, _TB_CANON)
    assert rc == 0           # a clean passing golden is still recovered
    rc2, _ = _adj(tmp_path, _GBAD, _TB_CANON)
    assert rc2 == 1          # a failing golden still floors (no pass marker)


@pytest.mark.skipif(not _HAVE, reason="verilator absent")
def test_pass_token_then_fatal_is_not_faithful(tmp_path):
    rc, msg = _adj(tmp_path, _GOK, _TB_FATAL)
    assert rc == 1, msg      # non-zero exit after a pass token => floor stands


@pytest.mark.skipif(not _HAVE, reason="verilator absent")
def test_benign_zero_count_summary_on_pass_is_faithful(tmp_path):
    # the over-correction fix: a genuinely-passing golden whose TB prints
    # "0/100 failures" / "Error count: 0" / "No mismatch" must NOT be floored
    # (matches the official scorer, which tolerates these).
    rc, msg = _adj(tmp_path, _GOK, _TB_PASS_ZEROCOUNT)
    assert rc == 0, msg
    # ...while the SAME TB on a BROKEN golden prints "Test failed" (no pass marker)
    # → floor stands.
    rc2, _ = _adj(tmp_path, _GBAD, _TB_PASS_ZEROCOUNT)
    assert rc2 == 1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
