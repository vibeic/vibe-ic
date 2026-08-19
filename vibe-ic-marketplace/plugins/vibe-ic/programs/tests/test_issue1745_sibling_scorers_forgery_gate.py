"""vibe-ic#1745 follow-up — the SIBLING scorers the first fix did not reach.

The #1745 landing put the forgery gate in front of `benchmark/score_iverilog_tb.py`
(both shapes) and `programs/verilogeval_tier_pipeline.py:iverilog_score`. Two more
programs run the SAME contract — compile a submitted candidate together with the
benchmark's own testbench, then read the verdict off the SIMULATION's stdout, which
the DUT shares — and neither had the gate:

    programs/verilogeval_human_tier_pipeline.py :: _run_iverilog
    programs/rtllm_tier_pipeline.py            :: iverilog_score

Both feed a PUBLISHED number (the Tier1+Tier2+Tier3 "STABLE BASELINE" printed by
each pipeline's main()), and Tier-1 is asserted precisely on "the emit iverilog-
VERIFIED against the official test" — the one verdict a submission can forge.

RTLLM is the sharper case. Its pass rule is a TOKEN, not a counted comparison, so
the forgery is not even a fake count — it is one `$display("=== Your Design Passed
===")`. And RTLLM accepts SEVERAL alternative pass sentences, so a gate wired to
only one of them would refuse the forgery it was shown and pass the other two.

DEFECT 3 (found wiring the above) — THE ANCHOR DERIVATION SILENTLY DEGRADED.
`verdict_anchors` mined regex GRAMMAR for text: `{3,}` yielded the anchor "3,",
`(?:` yielded ":", and a `[abc]` class yielded "abc". An anchor no output can ever
contain makes the ordered-anchor rule unsatisfiable, so for every benchmark whose
pass regex is not the simple `Mismatches:` shape the gate still ran and still
reported — with two of its three detection arms dead. That is the failure mode the
gate exists to prevent, reproduced inside the gate itself.

Every test here fails on the pre-fix tree; the reverted-tree failures are quoted in
the landing report.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

import _hostpaths
import harness_verdict_forgery_gate as G
import rtllm_tier_pipeline as R
import verilogeval_human_tier_pipeline as H

# ─────────────────────────────────────────────────────────────────────────────
# The verdict vocabularies, derived from patterns that exist on BOTH sides of
# this change, so this module COLLECTS on the pre-fix tree and every assertion
# below observes a VALUE rather than the absence of a new name. (A control that
# dies at import measures nothing — `control_substance_check` grades exactly
# this difference.)
# ─────────────────────────────────────────────────────────────────────────────
VE_PASS_RE = r"Mismatches:\s*0\s+in\s+\d+\s+samples"


def _src(rx, sub=None) -> str:
    """A compiled verdict pattern as a flag-carrying source string."""
    pat = rx.pattern
    if sub:
        pat = pat.replace(sub[0], sub[1], 1)
    letters = "".join(ch for flag, ch in ((re.I, "i"), (re.M, "m"),
                                          (re.S, "s"), (re.X, "x"))
                      if rx.flags & flag)
    return (f"(?{letters})" if letters else "") + pat


def rtllm_pass_forms() -> list:
    """RTLLM's three alternative PASS sentences, from the pipeline's own verdict
    patterns — which ship on the pre-fix tree too."""
    return [_src(R._BANNER_PASS_RE), _src(R._LINE_PASS_RE),
            _src(R._COUNTED_VERDICT_RE, (r"(\d+)", "0"))]


REFUSED = (False, "harness_verdict_forgery")


def outcome(passed, log: str):
    """`(passed, reason_head)` — a small value an assertion can pin an EXPECTED
    value against, so the pre-fix control reports WHAT IT OBSERVED rather than a
    bare `assert not x`. `control_substance_check` credits only the former."""
    head = (log or "").split(" —")[0].split(":")[0].strip()
    return (bool(passed), head)


def _blocks(rtl: str, patterns) -> bool:
    """True iff ANY of `patterns` makes the gate refuse `rtl`.

    Scans one pattern per call, so this helper works against the pre-fix
    single-pattern `gate()` as well as the post-fix multi-pattern one.
    """
    return any(G.gate(rtl, p)["verdict"] == G.FORGERY for p in patterns)

_NEEDS_SIM = pytest.mark.skipif(
    not shutil.which("iverilog") or not shutil.which("vvp"),
    reason="needs iverilog+vvp to run the measured pair end to end")


# ─────────────────────────────────────────────────────────────────────────────
# Synthesized neutral fixtures. No design, PDK or vendor literal appears here:
# a one-bit inverter and the two benchmarks' own verdict GRAMMAR, nothing else.
# ─────────────────────────────────────────────────────────────────────────────
VE_REF = ("module RefModule(input a, output y);\n"
          "  assign y = ~a;\n"
          "endmodule\n")

# The official VerilogEval testbench shape: drive both, count disagreements, and
# print the summary line the scorer greps for.
VE_TEST = """
module tb;
  reg a; wire y_dut, y_ref; integer bad = 0; integer n = 0; integer i;
  TopModule dut(.a(a), .y(y_dut));
  RefModule  rf(.a(a), .y(y_ref));
  initial begin
    for (i = 0; i < 20; i = i + 1) begin
      a = i[0]; #1;
      n = n + 1;
      if (y_dut !== y_ref) bad = bad + 1;
    end
    $display("Mismatches: %0d in %0d samples", bad, n);
    $finish;
  end
endmodule
"""

VE_RIGHT = "module TopModule(input a, output y);\n  assign y = ~a;\nendmodule\n"
VE_WRONG = "module TopModule(input a, output y);\n  assign y = a;\nendmodule\n"
VE_FORGED = (
    "module TopModule(input a, output y);\n"
    "  assign y = a;\n"
    '  initial $display("Mismatches: 0 in 20 samples");\n'
    "endmodule\n")

# RTLLM's shape: the design's own testbench.v, printing RTLLM's banner verdict.
RT_TB = """
module testbench;
  reg a; wire y; integer bad = 0; integer i;
  dut u(.a(a), .y(y));
  initial begin
    for (i = 0; i < 8; i = i + 1) begin
      a = i[0]; #1;
      if (y !== ~a) bad = bad + 1;
    end
    if (bad == 0) $display("===========Your Design Passed===========");
    else          $display("===========Error===========");
    $finish;
  end
endmodule
"""
# The shape that actually INFLATES. `testbench_verdict` is fail-safe — "no
# recognisable verdict is NOT a pass" — which means a testbench that announces
# SUCCESS but reports failure only as per-vector diagnostics leaves the pass
# sentence as the ONLY verdict token in the transcript. A wrong design then scores
# "no recognisable verdict" (not a pass), and the same wrong design plus one
# $display scores PASS. RTLLM ships testbenches of this shape; the fail-safe
# branch in the verdict contract exists precisely because they do.
RT_TB_QUIET = """
module testbench;
  reg a; wire y; integer i;
  dut u(.a(a), .y(y));
  initial begin
    for (i = 0; i < 8; i = i + 1) begin
      a = i[0]; #1;
      if (y !== ~a) $display("mismatch at i=%0d, y=%b", i, y);
    end
    if (y === ~a) $display("===========Your Design Passed===========");
    $finish;
  end
endmodule
"""

RT_RIGHT = "module dut(input a, output y);\n  assign y = ~a;\nendmodule\n"
RT_WRONG = "module dut(input a, output y);\n  assign y = a;\nendmodule\n"


def _rt_forged(sentence: str) -> str:
    return ("module dut(input a, output y);\n"
            "  assign y = a;\n"
            f'  initial $display("{sentence}");\n'
            "endmodule\n")


def _ve_dataset(tmp: Path) -> tuple[str, str]:
    tmp.mkdir(parents=True, exist_ok=True)
    ref, test = tmp / "ref.sv", tmp / "test.sv"
    ref.write_text(VE_REF)
    test.write_text(VE_TEST)
    return str(ref), str(test)


def _rt_design(tmp: Path, tb: str = RT_TB) -> str:
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / "testbench.v").write_text(tb)
    return str(tmp)


# ─────────────────────────────────────────────────────────────────────────────
# DEFECT 3 — the anchor derivation must not mine regex grammar for text
# ─────────────────────────────────────────────────────────────────────────────
def test_repeat_count_is_grammar_not_an_anchor():
    """`{3,}` is a repeat count. Mining it for the anchor "3," demanded a string
    no simulator prints, which silently disabled the ordered-anchor arm."""
    assert G.verdict_anchors(r"={3,}OK={3,}") == ["OK"]
    assert G.verdict_anchors(r"={3,}\s*Your\s+Design\s+Passed\s*={3,}") == [
        "Your", "Design", "Passed"]


def test_non_capturing_group_prefix_is_not_an_anchor():
    """`(?:` must not contribute ":" — which then glued itself onto the front of
    the next fragment, producing anchors like ':all' and ':failure'."""
    assert G.verdict_anchors(r"(?:all\s+)?(?:tests?)\s*done") == [
        "all", "test", "done"]
    assert ":" not in "".join(G.verdict_anchors(r"(?i)(?:a)done"))


def test_character_class_members_are_not_anchors():
    """`[abc]` matches ONE character; none of its members is text the forger
    must print. Treating the members as a literal run invented 'abc'."""
    assert "abc" not in G.verdict_anchors(r"[abc]+done")
    assert G.verdict_anchors(r"^[\s=*-]*PASSED[\s=*-]*$") == ["PASSED"]


def test_the_landed_mismatch_vocabulary_is_unchanged():
    """The grammar fix must not perturb the pattern the first #1745 fix shipped."""
    assert G.verdict_anchors(r"Mismatches:\s*0\s+in\s+\d+\s+samples") == [
        "Mismatches:", "in", "samples"]


def test_inert_anchor_patterns_are_disclosed_not_hidden():
    """§6 degrade loudly: a pattern that yields no usable anchors still gets
    scanned, but only by its exact-regex arm. The gate must NAME it rather than
    quietly narrow itself."""
    res = G.gate("module m; endmodule", [r"\d+", r"Mismatches:\s*0"])
    assert res["inert_anchor_patterns"] == [r"\d+"]


def test_every_alternative_pass_sentence_is_caught():
    """RTLLM accepts SEVERAL pass sentences, so each is a separate thing a forger
    can print. `PASSED` is the one that measured the flag defect: the harness
    decides with re.IGNORECASE, so a gate built from the bare `.pattern` refused
    `Passed` and let `PASSED` through — weaker than the rule it protects."""
    forms = rtllm_pass_forms()
    for sentence in ("===========Your Design Passed===========",
                     "PASSED",
                     "Test completed with 0 failures"):
        assert _blocks(_rt_forged(sentence), forms), sentence


def test_the_pipeline_ships_those_same_pass_forms():
    """The wiring assertion: the pipeline must hand the gate every pass sentence
    its own verdict rule accepts, flags included."""
    assert list(R._PASS_FORGERY_REGEXES) == rtllm_pass_forms()
    assert H._MISMATCH_PASS_REGEX == VE_PASS_RE


def test_the_gate_accepts_several_patterns_in_one_call():
    forms = rtllm_pass_forms()
    assert G.gate(_rt_forged("PASSED"), forms)["verdict"] == G.FORGERY
    assert G.gate(RT_RIGHT, forms)["verdict"] == G.CLEAN


# ─────────────────────────────────────────────────────────────────────────────
# VerilogEval-Human tier pipeline — the gate is in front of _run_iverilog
# ─────────────────────────────────────────────────────────────────────────────
@_NEEDS_SIM
def test_ve_human_the_measured_pair_end_to_end(tmp_path):
    """The issue's own experiment through the VE-Human pipeline's scorer.

    Both candidates carry the SAME wrong logic, so the simulator reports a
    nonzero mismatch count for both. The honest-wrong control failing is what
    makes this a forgery finding rather than a vacuous check.
    """
    ref, test = _ve_dataset(tmp_path / "ds")

    ok, log_ok = H._run_iverilog(VE_RIGHT, ref, test)
    assert ok, log_ok                                  # the gate blocks nothing real

    honest, log_h = H._run_iverilog(VE_WRONG, ref, test)
    # the non-vacuity control: the simulator really did see 20 wrong samples
    assert (honest, log_h) == (False, "Mismatches: 20 in 20 samples"), log_h

    forged, log_f = H._run_iverilog(VE_FORGED, ref, test)
    assert outcome(forged, log_f) == REFUSED, log_f


def test_ve_human_refuses_the_forged_candidate_before_compiling_it(tmp_path):
    """The gate is IN FRONT: no ref, no test, no simulator on disk — and the
    forged candidate is still refused, which is only possible if nothing ran."""
    try:
        got = outcome(*H._run_iverilog(VE_FORGED, str(tmp_path / "absent_ref.sv"),
                                       str(tmp_path / "absent_test.sv")))
    except OSError as exc:      # pre-fix: it reached for the ref before deciding
        got = ("reached the filesystem", type(exc).__name__)
    assert got == REFUSED, got


@_NEEDS_SIM
def test_ve_human_floor_probe_is_exempt(tmp_path):
    """`top_sv_text is None` grades the dataset's OWN golden against its own
    test. That candidate is not an answer to the question, so the gate has
    nothing to protect — and gating it would FALSE-FLOOR a sound problem by
    reporting 'golden fails its own test'."""
    ref, test = _ve_dataset(tmp_path / "ds")
    Path(ref).write_text(
        VE_REF.replace("assign y = ~a;",
                       'assign y = ~a;\n  initial $display("Mismatches: 0 in 20 samples");'))
    passed, log = H._run_iverilog(None, ref, test)
    assert passed, log
    assert not log.startswith("harness_verdict_forgery"), log


# ─────────────────────────────────────────────────────────────────────────────
# RTLLM tier pipeline — the gate is in front of iverilog_score
# ─────────────────────────────────────────────────────────────────────────────
@_NEEDS_SIM
def test_rtllm_the_measured_pair_end_to_end(tmp_path):
    """RTLLM's pass rule is a TOKEN, so the forgery is a single $display."""
    d = _rt_design(tmp_path / "d")

    compiled, ok, log = R.iverilog_score(d, RT_RIGHT, "dut")
    assert compiled and ok, log                        # the gate blocks nothing real

    compiled, honest, log_h = R.iverilog_score(d, RT_WRONG, "dut")
    assert compiled and not honest, log_h              # the non-vacuity control

    _, forged, log_f = R.iverilog_score(d, _rt_forged("=== Your Design Passed ==="),
                                        "dut")
    assert outcome(forged, log_f) == REFUSED, log_f


@_NEEDS_SIM
def test_rtllm_forged_candidate_actually_inflated_the_verdict(tmp_path):
    """The INFLATION control — a forged PASS that the pre-fix scorer accepted.

    Same wrong logic in both candidates. Against a testbench that reports failure
    only as per-vector diagnostics, the honest-wrong one leaves no recognisable
    verdict (correctly, not a pass) and the forged one supplies the only verdict
    token in the transcript. This is the measured defect, in RTLLM's shape: one
    `$display` turns a wrong answer into a published PASS.
    """
    d = _rt_design(tmp_path / "q", RT_TB_QUIET)

    _, ok, log = R.iverilog_score(d, RT_RIGHT, "dut")
    assert ok, log                                     # the gate blocks nothing real

    _, honest, log_h = R.iverilog_score(d, RT_WRONG, "dut")
    assert not honest, log_h                           # the non-vacuity control

    _, forged, log_f = R.iverilog_score(
        d, _rt_forged("===========Your Design Passed==========="), "dut")
    assert outcome(forged, log_f) == REFUSED, log_f


def test_rtllm_refuses_the_forged_candidate_before_compiling_it(tmp_path):
    """No testbench.v on disk at all — the pre-gate code returned
    'no testbench.v' here, so reaching the forgery verdict proves the gate runs
    ahead of every filesystem and compiler step."""
    empty = tmp_path / "nodesign"
    empty.mkdir()
    _, forged, log = R.iverilog_score(str(empty),
                                      _rt_forged("=== Your Design Passed ==="), "dut")
    assert outcome(forged, log) == REFUSED, log


@_NEEDS_SIM
def test_rtllm_forgery_reason_survives_to_tier1_emit_verified(tmp_path):
    """§6 degrade loudly: a REFUSAL TO SCORE is neither a compile failure nor a
    run that produced no pass. Collapsing it into 'compile-fail' would hide the
    only reason a reader needs."""
    d = Path(_rt_design(tmp_path / "d"))
    (d / "makefile").write_text("TEST_DESIGN = dut\n")
    monkey = _rt_forged("=== Your Design Passed ===")
    R_emit = R.deterministic_emit
    try:
        R.deterministic_emit = lambda design_dir, top: ("stub", monkey)
        kind, rtl, log = R.tier1_emit_verified(str(d))
    finally:
        R.deterministic_emit = R_emit
    assert (kind, rtl, outcome(False, log)) == (None, None, REFUSED), log


def test_rtllm_floor_probe_is_exempt(tmp_path):
    """REGRESSION GUARD, explicitly NOT a pre-fix control: before this change no
    gate existed anywhere, so the floor probe was trivially un-gated and this
    could not have failed for the right reason. It exists to stop a later edit
    from gating the probe — which could only MANUFACTURE a floor (a
    benchmark-DEFECT claim) out of a sound design."""
    d = _rt_design(tmp_path / "d")
    _, _, log = R.iverilog_score(d, _rt_forged("=== Your Design Passed ==="),
                                 "dut", submitted=False)
    assert not log.startswith("harness_verdict_forgery"), log


# ─────────────────────────────────────────────────────────────────────────────
# Corpus sweep as a guard — real checked-in RTL, not a fixture authored here
# ─────────────────────────────────────────────────────────────────────────────
def _suites() -> list:
    return [[VE_PASS_RE], rtllm_pass_forms()]


# A TESTBENCH is never handed to the gate: the scorers scan the SUBMITTED
# candidate, while the testbench comes from the dataset. Printing the verdict is
# a testbench's JOB, so sweeping them would measure the wrong population.
_TB_MODULE_RE = re.compile(r"^\s*module\s+(\w*tb\w*|testbench\w*)\b", re.M | re.I)


def _is_testbench(path: Path, text: str) -> bool:
    base = path.name.lower()
    return (base.startswith(("tb_", "testbench")) or "_tb." in base
            or bool(_TB_MODULE_RE.search(text)))


def _sweep(files) -> list:
    hits = []
    for f in files:
        text = f.read_text(errors="ignore")
        if _is_testbench(f, text):
            continue
        for pats in _suites():
            if _blocks(text, pats):
                hits.append(str(f))
    return hits


def test_no_false_positive_on_the_checked_in_benchmark_rtl():
    """§2 corpus sweep over REAL in-repo artefacts — the canonical benchmark
    samples and the real_benchmark fixtures — rather than RTL authored beside
    the gate. A gate that fires on legitimate RTL is a bug in the gate, and
    RTLLM's token-shaped pass rule is where that risk lives.

    This is the sweep that runs EVERYWHERE: these files ship with the plugin.
    """
    roots = [_hostpaths.require_repo("vibe-ic-marketplace", "plugins", "vibe-ic",
                                     "benchmark", "canonical_samples"),
             _hostpaths.require_repo("vibe-ic-marketplace", "plugins", "vibe-ic",
                                     "programs", "tests", "fixtures",
                                     "real_benchmark")]
    files = [f for r in roots for f in r.rglob("*") if f.suffix in (".v", ".sv")]
    assert files, f"no real RTL under {roots} — the sweep would be vacuous"
    assert not _sweep(files), f"false positives on real RTL: {_sweep(files)[:10]}"


def test_no_false_positive_on_the_large_run_corpus():
    """The same sweep at scale, where the checkout carries the published-run
    corpus. Skipped rather than faked when it is absent — `benchmark-data` is
    not on every branch, and a sweep that did not run is not a sweep that found
    nothing (§6)."""
    root = _hostpaths.require_repo("benchmark-data")
    files = [f for f in root.rglob("*") if f.suffix in (".v", ".sv")]
    if len(files) < 200:
        pytest.skip(f"checkout carries only {len(files)} RTL files under "
                    "benchmark-data; not a corpus this claim can rest on")
    assert not _sweep(files), f"false positives on real RTL: {_sweep(files)[:10]}"
