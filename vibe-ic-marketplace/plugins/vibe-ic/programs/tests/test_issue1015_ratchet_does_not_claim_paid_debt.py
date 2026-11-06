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

import json
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




def _recorded() -> dict:
    return json.loads(BASELINE.read_text(encoding="utf-8"))


@needs_corpus
def test_the_corpus_this_module_measures_actually_exists():
    """A path that resolves to nothing would make every predicate below fail —
    or, with a laxer assertion, PASS over an empty sweep. Pinned first."""
    assert CORPUS.is_dir(), f"corpus not found at {CORPUS}"
    assert any(CORPUS.iterdir()), f"corpus is empty at {CORPUS}"








@pytest.mark.consistency
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
