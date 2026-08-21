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
import shlex
import sys
from pathlib import Path

import pytest

from _published_corpus import corpus_root, needs_corpus

PROGRAMS = Path(__file__).resolve().parents[1]
CHECK = PROGRAMS / "step_internal_fail_bubble_up_check.py"
BASELINE = PROGRAMS / "step_internal_fail_bubble_up_baseline.json"
# <repo>/vibe-ic-marketplace/plugins/vibe-ic/programs -> parents[3] is <repo>.
# Spelled by index and ASSERTED below, because the first version used
# parents[2] — one short — and every predicate here then measured an
# empty directory and failed for the wrong reason.
REPO_ROOT = PROGRAMS.parents[3]

# THE CORPUS COMES FROM THE RECORD, NOT FROM THIS FILE (vibe-ic#1223).
#
# It was hardcoded to `benchmark-data` while `tools/ci/repo_hygiene_gates.sh`
# sweeps `benchmark-data/ic`. Under the old NAME-based population the two roots
# happened to answer the same number — nothing outside `ic/` was called
# `clean_run_*` — so the disagreement was invisible and nothing checked it.
# With the population defined by the ARTEFACT they are different questions:
# 22 findings over `benchmark-data/ic`, 45 over `benchmark-data`, same commit.
# A test that measured one while the gate ratchets the other would be grading a
# population the gate never looks at, which is the whole failure class #1015 is
# about. So the baseline names its own population and this reads it back.
_POPULATION = json.loads(
    BASELINE.read_text(encoding="utf-8"))["corpus_population"]

# ...AND WHERE THAT POPULATION NOW LIVES. `corpus_population` is spelled
# relative to the REPOSITORY (`benchmark-data/ic`) because the published cells
# used to be here. They are in vibeic/benchmark-data now, and a clone of THAT
# repository IS the `benchmark-data` directory — so the identical population is
# `ic` inside it. Only the LEADING component moves; the population itself is
# still the one the record names, which is the invariant #1223 is about.
#
# The in-repo spelling stays the fallback so the module still imports where
# there is no corpus at all; every predicate that actually READS the corpus is
# `@needs_corpus` and skips there rather than measuring an empty tree.
def _population_under(root: Path) -> Path:
    p = Path(_POPULATION)
    try:
        return root / p.relative_to("benchmark-data")
    except ValueError:                      # a population named some other way
        return root / p


_CORPUS_ROOT = corpus_root()
CORPUS = (_population_under(_CORPUS_ROOT) if _CORPUS_ROOT is not None
          else REPO_ROOT / _POPULATION)


def _load():
    spec = importlib.util.spec_from_file_location("_sifbu_under_test", CHECK)
    m = importlib.util.module_from_spec(spec)
    sys.modules["_sifbu_under_test"] = m
    spec.loader.exec_module(m)
    return m


def _recorded() -> dict:
    return json.loads(BASELINE.read_text(encoding="utf-8"))


@needs_corpus
def test_the_corpus_this_module_measures_actually_exists():
    """A path that resolves to nothing would make every predicate below fail —
    or, with a laxer assertion, PASS over an empty sweep. Pinned first."""
    assert CORPUS.is_dir(), f"corpus not found at {CORPUS}"
    assert any(CORPUS.iterdir()), f"corpus is empty at {CORPUS}"


def _swept_population(gates: Path) -> str:
    """The value of `--corpus` on the CI gate's own command line.

    READ AS ARGV, NOT AS A SUBSTRING. This used to be
    ``line.split("--corpus", 1)[1].strip().strip('"')``, which silently assumes
    the option's VALUE is the last thing on the line. `bd3c3a4c3` (v1.10.62)
    appended `--corpus-may-be-absent` to it — a correct change, made because the
    corpus moved to vibeic/benchmark-data and the gate must not fail on a
    checkout that has not cloned it — and the chop then returned

        benchmark-data/ic" --corpus-may-be-absent

    so the agreement this module exists to check was reported as a disagreement
    over a population that had not moved at all. `shlex` is the shell's own
    tokenizer: any further flag, in any order, is read correctly rather than
    swallowed into the value.

    The option is matched as a whole TOKEN for the same reason. `"--corpus" in
    line` is true of `--corpus-may-be-absent` as well, so a line carrying only
    the flag would have been selected as an invocation naming a population.
    """
    hits = []
    for raw in gates.read_text(encoding="utf-8").splitlines():
        if "step_internal_fail_bubble_up_check.py" not in raw:
            continue
        argv = shlex.split(raw, comments=True)
        for i, tok in enumerate(argv):
            if tok == "--corpus":
                assert i + 1 < len(argv), (
                    f"`--corpus` is the last token on the gate line, so it "
                    f"names no population: {raw.strip()}")
                hits.append(argv[i + 1])
            elif tok.startswith("--corpus="):
                hits.append(tok.split("=", 1)[1])
    assert len(hits) == 1, (
        f"expected exactly one corpus invocation of the gate in {gates.name}, "
        f"found {len(hits)}: {hits}")
    # `$ROOT` is the repository the script computes for itself; the baseline
    # spells the same population relative to it.
    return hits[0].replace("${ROOT}/", "").replace("$ROOT/", "")


def test_the_recorded_population_is_the_one_the_ci_gate_sweeps():
    """THE AGREEMENT NOTHING CHECKED (vibe-ic#1223).

    `tools/ci/repo_hygiene_gates.sh` is the only caller that runs this gate in
    anger, and it names the corpus root on its own command line. The baseline
    names one too. Nothing compared them: they agreed only because the old
    NAME-based population made every root under `benchmark-data` answer the
    same number, and that accident ended the moment the population became the
    artefact. If they ever disagree the gate is ratcheting a line that was
    measured somewhere else — so this reads BOTH out of the tree and asserts
    they are the same string.
    """
    gates = REPO_ROOT / "tools" / "ci" / "repo_hygiene_gates.sh"
    assert gates.is_file(), f"CI gate script not found at {gates}"
    swept = _swept_population(gates)
    recorded = json.loads(BASELINE.read_text(encoding="utf-8"))["corpus_population"]
    assert swept == recorded, (
        f"the CI gate sweeps '{swept}' and the baseline records its count over "
        f"'{recorded}'. Those are different populations, so the ratchet would "
        f"hold a line nobody measured — see vibe-ic#1223.")


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


@needs_corpus
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
        if not ((CORPUS / rel).is_dir() or (CORPUS / "ic" / rel).is_dir()
                or (CORPUS / run).is_dir()):
            missing.append(run)
    assert not missing, (
        f"the ratchet baseline cites {len(missing)} run tree(s) that are not in "
        f"the corpus: {missing}. Regenerate with "
        f"`step_internal_fail_bubble_up_check.py --corpus benchmark-data "
        f"--write-baseline`.")


@needs_corpus
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


@needs_corpus
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


@needs_corpus
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
