"""vibe-ic#1015 — the ratchet recorded debt that had already been paid, and
cited two run trees, one of which no longer exists.

`step_internal_fail_bubble_up_check --corpus` carries a SHRINK-ONLY baseline of
unacknowledged step-internal FAILs across the published run trees. Measured on
`a38902d1` (v1.10.35):

    recorded : findings_total 7, runs_swept 17, runs_with_reports 5
    live     : findings_total 5, runs_swept 13, runs_with_reports 3

The gap is the withdrawal (#1028/#1015) removing published runs. The checker
already NOTICES — it prints `[PASS] 7 -> 5; lower the baseline so the recorded
number stops claiming debt that is paid` — and then exits 0, so nothing made
anyone do it. Its `per_run` map still named
`u_hawaii_adc/clean_run_v1427_20260715`, which is **not in the tree at all**:
a citation that outlived its cell, which is the shape `retention.json` and
`benchmark_evidence_index` exist to prevent one directory over.

NOTHING READ THIS FILE. `grep -rl step_internal_fail_bubble_up_baseline` over
`programs/tests/` and `tools/` returned nothing before this module, which is
why the drift was free: the number is only ever compared against itself, inside
a gate that passes either way.

WHY THE TEST AND NOT ONLY THE DATA. Regenerating the baseline fixes today's
number and nothing else — the next withdrawal re-opens the same gap silently.
These two predicates are what make the record self-correcting.

WHAT THIS DELIBERATELY DOES NOT DO. It does not touch the five findings that
remain, and it does not soften the gate. #1015 is explicit that what happens to
published runs carrying a real failure is a PUBLISHING decision for the owner —
re-run, withdraw, or publish with the failure disclosed — and this module takes
none of those. It only stops the record claiming a debt the tree no longer has.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
CHECK = PROGRAMS / "step_internal_fail_bubble_up_check.py"
BASELINE = PROGRAMS / "step_internal_fail_bubble_up_baseline.json"
# <repo>/vibe-ic-marketplace/plugins/vibe-ic/programs -> parents[3] is <repo>.
# Spelled by index and ASSERTED below, because the first version used
# parents[2] — one short — and every predicate here then measured an
# empty directory and failed for the wrong reason.
CORPUS = PROGRAMS.parents[3] / "benchmark-data"


def _load():
    spec = importlib.util.spec_from_file_location("_sifbu_under_test", CHECK)
    m = importlib.util.module_from_spec(spec)
    sys.modules["_sifbu_under_test"] = m
    spec.loader.exec_module(m)
    return m


def _recorded() -> dict:
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def test_the_corpus_this_module_measures_actually_exists():
    """A path that resolves to nothing would make every predicate below fail —
    or, with a laxer assertion, PASS over an empty sweep. Pinned first."""
    assert CORPUS.is_dir(), f"corpus not found at {CORPUS}"
    assert (CORPUS / "ic").is_dir(), f"no ic/ tree under {CORPUS}"


def _live() -> dict:
    """The checker's OWN corpus sweep, imported rather than reimplemented.

    Deliberately NOT guarded by a `pytest.skip` if the entry point moves: a
    skip is green, and a green that means "I could not ask" is the shape #1128
    is about. If `check_corpus` is renamed, this raises and says so.
    """
    m = _load()
    assert hasattr(m, "check_corpus"), (
        "step_internal_fail_bubble_up_check no longer exposes `check_corpus`; "
        "this module measures nothing until it is repointed — which is a "
        "failure, not a skip.")
    return m.check_corpus(CORPUS)


def test_the_baseline_cites_no_run_tree_that_is_gone():
    """A citation that outlives its cell.

    `u_hawaii_adc/clean_run_v1427_20260715` was recorded as carrying one
    unacknowledged FAIL and is not in the tree; the withdrawal removed it. A
    shrink-only register naming a directory nobody can open is a record of a
    debt nobody can pay or dispute.

    Keys are matched against the corpus BOTH ways, because the writer's key
    format changed under this same change (`sha256/…` -> `ic/sha256/…`) and a
    test that pinned one spelling would report drift that is only formatting.
    """
    assert CORPUS.is_dir(), f"corpus not present at {CORPUS}"
    missing = []
    for run in sorted(_recorded().get("per_run", {})):
        rel = run[3:] if run.startswith("ic/") else run
        if not ((CORPUS / "ic" / rel).is_dir() or (CORPUS / run).is_dir()):
            missing.append(run)
    assert not missing, (
        f"the ratchet baseline cites {len(missing)} run tree(s) that are not in "
        f"the corpus: {missing}. Regenerate with "
        f"`step_internal_fail_bubble_up_check.py --corpus benchmark-data "
        f"--write-baseline`.")


def test_the_baseline_does_not_claim_debt_that_is_paid():
    """The recorded total must equal the live one.

    The gate ALLOWS `live < recorded` — it passes and prints "lower the
    baseline". That is the correct runtime behaviour (a shrink is not a
    regression) and it is exactly why the number drifts: nothing ever makes the
    lowering happen. This is the thing that does.

    It fails LOUD in the direction that matters too: `live > recorded` is a real
    new unacknowledged FAIL, and the gate already refuses that at runtime.
    """
    rec = _recorded()
    live = _live()
    assert live["findings_total"] == rec["findings_total"], (
        f"recorded findings_total={rec['findings_total']} but the corpus now "
        f"carries {live['findings_total']}. "
        + ("A shrink is good news and the record must follow it — regenerate "
           "with --write-baseline."
           if live["findings_total"] < rec["findings_total"] else
           "This is a NEW unacknowledged step-internal FAIL; do not raise the "
           "baseline to accommodate it."))


def test_the_denominator_is_recorded_too_not_just_the_numerator():
    """`findings_total` alone cannot tell "the failures were fixed" from "the
    runs carrying them were withdrawn". The swept/with-reports counts are what
    make the number readable, and they drifted 17->13 and 5->3 unnoticed."""
    rec, live = _recorded(), _live()
    assert (rec.get("runs_swept"), rec.get("runs_with_reports")) == \
           (live["runs_swept"], live["runs_with_reports"]), (
        f"recorded denominator {(rec.get('runs_swept'), rec.get('runs_with_reports'))} "
        f"!= live {(live['runs_swept'], live['runs_with_reports'])} — the "
        f"population moved and the record did not follow it.")


def test_a_zero_population_is_refused_rather_than_recorded_as_clean():
    """The anti-starvation guard, and it is not hypothetical: #1025 is exactly
    this checker returning VACUOUS_PASS over zero published run trees. If the
    sweep ever reaches nothing, these tests must not read that as a baseline of
    zero findings honestly earned."""
    live = _live()
    assert live["runs_with_reports"] > 0, (
        "the corpus sweep found NO published run tree with a reports/ "
        "directory, so every number above is a measurement of nothing — see "
        "vibe-ic#1025. This is not a clean baseline.")
