"""#637 — a design that was never authored counted as one that answered wrongly.

`pass_at_1.json` carries a dedicated count and a derived rate for every other
way a problem fails to be a real measurement — `skipped_scorer_gap`,
`non_discriminating_tb_passes`, `dataset_defect_count`,
`suspected_defective_golden_count`. The one that means THE RUN WAS NOT FINISHED
had neither, so a headline read as "N of TOTAL designs solved" when it was "N of
the ones that were authored".

MEASURED ON TWO PUBLISHED RUNS, whose summaries say none of this:

    verilogeval_human/run_kimi_k3_20260718   149/156 = 95.51%
                                             2 no_sample -> 149/154 = 96.75%
    verilogeval_v2/run_kimi_k3_20260718      147/156 = 94.23%
                                             4 no_sample -> 147/152 = 96.71%

Six problems across two published numbers counted as submissions that were
wrong, when nothing was submitted. The issue reported it from a live RTLLM run;
these two are the same defect already in the corpus.

WHY IT MISLEADS MOST WHEN IT MATTERS MOST: `no_sample` is the signature of an
INCOMPLETE run — an agent that died, hit a quota, or was stopped — which is
exactly the state someone opens this file to discover. A scorer invocation over
a run that had barely started produced a fully-formed result claiming 2.0%, and
nothing in it said the run was still going.

THE FIX ADDS NO DETECTION. Both shapes already write `reason: "no_sample"`; the
scorer simply never carried the fact up to where the number is read. The rate
EXCLUDES rather than REPLACES the headline, symmetric with the dual reports
already there.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

from _published_corpus import corpus_root, needs_corpus

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
_REPO = _PROGRAMS.parents[3]
_SCORER = _REPO / "vibe-ic-marketplace/plugins/vibe-ic/benchmark/score_iverilog_tb.py"

_spec = importlib.util.spec_from_file_location("score_iverilog_tb", _SCORER)
S = importlib.util.module_from_spec(_spec)
sys.modules["score_iverilog_tb"] = S
try:
    _spec.loader.exec_module(S)
except SystemExit:            # the scorer has a __main__ guard; importing is fine
    pass


# Minimal, non-oracle receipts from the last commit that carried the two legacy
# paths.  benchmark-data d87a472 normalized those runs away; demanding the old
# directories from every later corpus made the regression test permanently red.
# The receipts preserve only the scorer inputs this issue reads: denominator,
# numerator, headline, and the identities classified `no_sample`.  Source blob
# IDs make a coordinated value edit reviewable without copying generated HDL,
# harnesses, golden outputs, or any other benchmark answer.
_HISTORICAL_RUNS = {
    "human": {
        "source_commit": "3a4789541db47403e2d2ed3070d13bac3e10321b",
        "source_blob": "07002556c24a597f26b541213bae8b299d879755",
        "total": 156,
        "passed": 149,
        "pass_at_1_pct": 95.51,
        "no_sample": ["Prob133_2014_q3fsm", "Prob154_fsm_ps2data"],
    },
    "v2": {
        "source_commit": "3a4789541db47403e2d2ed3070d13bac3e10321b",
        "source_blob": "6c091674cd1e10a9000328eb412c635c391dc4a7",
        "total": 156,
        "passed": 147,
        "pass_at_1_pct": 94.23,
        "no_sample": [
            "Prob058_alwaysblock2", "Prob133_2014_q3fsm",
            "Prob149_ece241_2013_q4", "Prob155_lemmings4",
        ],
    },
}


def _receipt_results(receipt):
    return [{"problem": p, "reason": "no_sample"}
            for p in receipt["no_sample"]]


# ── the two published runs it was measured on ──────────────────────────────
#
# ALL THREE CORPUS TESTS BELOW LOST THEIR SUBJECT, not their point: the scored
# runs under `benchmark-data/evaluation/` are published results and moved to
# vibeic/benchmark-data. Two of them used to `return` on a missing file, which
# is the exact failure this whole branch is about — a check that could not look
# reporting that it looked and found nothing wrong. They skip now, naming the
# corpus, and they read it from wherever the caller pointed
# `VIBE_IC_BENCHMARK_DATA`, so the published numbers are measured again the
# moment a clone is available instead of being permanently green and blind.
@needs_corpus
def test_it_reproduces_the_published_human_run():
    f = (corpus_root() / "evaluation/verilogeval_human"
         / "run_kimi_k3_20260718" / "pass_at_1.json")
    d = (json.loads(f.read_text()) if f.is_file()
         else _HISTORICAL_RUNS["human"])
    results = d.get("results") or _receipt_results(d)
    n_ns, probs, pct, partial = S.no_sample_disclosure(
        results, d["total"], d["passed"], "problem")
    assert (n_ns, pct, partial) == (2, 96.75, True)
    assert len(probs) == 2
    assert d["pass_at_1_pct"] == 95.51, "the headline is unchanged by design"


@needs_corpus
def test_it_reproduces_the_published_v2_run():
    f = (corpus_root() / "evaluation/verilogeval_v2"
         / "run_kimi_k3_20260718" / "pass_at_1.json")
    d = (json.loads(f.read_text()) if f.is_file()
         else _HISTORICAL_RUNS["v2"])
    results = d.get("results") or _receipt_results(d)
    n_ns, _probs, pct, partial = S.no_sample_disclosure(
        results, d["total"], d["passed"], "problem")
    assert (n_ns, pct, partial) == (4, 96.71, True)


@needs_corpus
def test_a_complete_run_is_not_flagged():
    """THE ACCEPT CASE, and the one that decides whether this can ship: the
    corpus is mostly complete runs, and every one of them must stay silent."""
    base = corpus_root() / "evaluation"
    checked = 0
    for f in base.rglob("pass_at_1.json"):
        d = json.loads(f.read_text())
        res = d.get("results") or []
        if any(r.get("reason") == "no_sample" for r in res):
            continue
        n_ns, probs, pct, partial = S.no_sample_disclosure(
            res, d.get("total", 0), d.get("passed", 0))
        assert (n_ns, probs, partial) == (0, [], False), f
        checked += 1
    assert checked >= 5, f"only {checked} complete runs seen — is the corpus there?"


# ── the shape of the disclosure ────────────────────────────────────────────
def test_the_rate_excludes_rather_than_replaces():
    """Symmetric with every other dual report in this file. Replacing the
    headline would make our numbers incomparable with the upstream methodology;
    omitting the second one is what #637 is about."""
    res = [{"reason": "no_sample", "design": "a"},
           {"reason": "no_sample", "design": "b"}] + \
          [{"verdict": "PASS", "design": f"p{i}"} for i in range(8)]
    n_ns, probs, pct, partial = S.no_sample_disclosure(res, 10, 8)
    assert n_ns == 2 and probs == ["a", "b"] and partial is True
    assert pct == 100.0, "8 of the 8 authored"


def test_zero_authored_does_not_divide_by_zero():
    """A run where NOTHING was authored is the extreme of the case this exists
    for — it must report 0.0 and `partially_authored`, not crash the scorer that
    is trying to tell you the run died."""
    res = [{"reason": "no_sample", "design": f"d{i}"} for i in range(3)]
    n_ns, _p, pct, partial = S.no_sample_disclosure(res, 3, 0)
    assert (n_ns, pct, partial) == (3, 0.0, True)


def test_another_failure_reason_is_not_counted_as_unauthored():
    """LOAD-BEARING. A compile error or a functional mismatch IS an answer, and
    a wrong one. Only the absence of a submission may be excluded — otherwise
    this becomes a way to raise the number."""
    res = [{"reason": "compile_error", "design": "a"},
           {"reason": "functional_mismatch (Mismatches: 3 in 9)", "design": "b"},
           {"reason": "sim_timeout", "design": "c"},
           {"verdict": "PASS", "design": "d"}]
    n_ns, probs, pct, partial = S.no_sample_disclosure(res, 4, 1)
    assert (n_ns, probs, partial) == (0, [], False)
    assert pct == 25.0, "unchanged from the headline when nothing is unauthored"


def test_the_summary_carries_all_four_fields():
    """A disclosure that does not travel with the number is not a disclosure:
    stdout is gone by the time anyone reads the artefact, and the JSON is what
    survives, gets copied and gets quoted. Shape C already warned on stdout and
    that is exactly why nobody saw it."""
    src = _SCORER.read_text(encoding="utf-8")
    body = "\n".join(l for l in src.splitlines()
                     if not l.lstrip().startswith("#"))
    for field in ('"no_sample_count"', '"no_sample_problems"',
                  '"pass_at_1_excluding_no_sample_pct"', '"partially_authored"'):
        assert field in body, field


def test_the_detection_is_the_reason_the_scorer_already_writes():
    """No second detector. Both shapes write `reason: "no_sample"` at their own
    missing-sample sites; a re-derivation (globbing for the sample file, say)
    could disagree with the verdict the scorer recorded."""
    src = _SCORER.read_text(encoding="utf-8")
    seg = src[src.index("def no_sample_disclosure"):]
    seg = seg[:seg.index("\ndef ", 10)]
    body = seg[seg.index('"""', seg.index('"""') + 3) + 3:]
    assert 'r.get("reason") == "no_sample"' in body
    assert "glob" not in body and "is_file" not in body


# ── how the SUMMARY is assembled, not just what the helper returns ─────────
#
# Added after running mutations against the first version of this file: two of
# three passed. The helper was covered and the summary's WIRING was not, so
# replacing the headline with the authored rate, and hardcoding
# `partially_authored` to False, both went undetected. A test that covers the
# computation but not the assignment leaves the whole disclosure disconnectable.
def test_the_headline_is_still_the_headline():
    """MUTATION-DRIVEN. Substituting the authored rate for `pass_at_1_pct`
    would make our number incomparable with the upstream methodology while
    looking like an improvement — the single most tempting wrong move here."""
    src = _SCORER.read_text(encoding="utf-8")
    body = "\n".join(l for l in src.splitlines()
                     if not l.lstrip().startswith("#"))
    assert '"pass_at_1_pct": round(100.0 * npass / n_eff, 2) if n_eff else 0.0,' \
        in body, "the headline rate is no longer computed from n_eff"
    assert '"pass_at_1_pct": pct_authored' not in body


def test_the_four_fields_are_wired_to_the_helper_not_to_constants():
    """MUTATION-DRIVEN. `"partially_authored": False` satisfies a
    key-is-present check forever while disclosing nothing — an absence wearing
    the shape of a record, inside the fix for an absence."""
    src = _SCORER.read_text(encoding="utf-8")
    body = "\n".join(l for l in src.splitlines()
                     if not l.lstrip().startswith("#"))
    for pair in ('"no_sample_count": n_nosamp,',
                 '"no_sample_problems": nosamp_problems,',
                 '"pass_at_1_excluding_no_sample_pct": pct_authored,',
                 '"partially_authored": partially,'):
        assert pair in body, pair
    for dead in ('"partially_authored": False', '"partially_authored": True',
                 '"no_sample_count": 0'):
        assert dead not in body, dead
