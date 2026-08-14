"""The ratchet's baseline must name run trees that are actually published.

vibe-ic#1025, part 3. The baseline recorded four `per_run` entries; two of them
(`u_hawaii_adc/clean_run_v1422_20260715`, `.../v1427_20260715`) named run trees
that no longer exist in the tree — one of them had already been absent from
`main` when the issue was filed. It also declared `runs_swept: 17` against a
published population of 13.

Nothing caught that, because nothing compared the baseline to the tree. The
gate itself cannot: its `MAY ONLY SHRINK` rule is satisfied by a baseline that
overstates, so a stale entry makes the ratchet *looser* and never redder — the
failure is silent by construction.

WHY THIS IS A SEPARATE GUARD, not an assertion inside the gate. The gate reads
the corpus to produce `per_run`; asking it to also validate the baseline against
the same read would be one instrument grading its own homework. This asserts the
two agree, from the tree, and would have failed on `main` from the moment the
first `u_hawaii_adc` run was withdrawn.

DERIVED, NOT ENUMERATED. The published population is recomputed here with the
gate's OWN `_published_run_trees`, so a run published tomorrow needs no edit.
No run name is written down in this file.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN_ROOT / "programs"
REPO_ROOT = PLUGIN_ROOT.parent.parent.parent
CORPUS = REPO_ROOT / "benchmark-data"
BASELINE = PROGRAMS / "step_internal_fail_bubble_up_baseline.json"

if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

# Plain import, deliberately. Loading this module by
# `spec_from_file_location` leaves it out of `sys.modules`, and its
# `@dataclass BubbleFinding` uses string annotations — which `dataclasses`
# resolves through `sys.modules`, so the hand-loaded form dies with an
# AttributeError inside the stdlib before any assertion here runs. The
# neighbouring suites import gate modules exactly this way.
import step_internal_fail_bubble_up_check as SIFBU  # noqa: E402


def _published_keys() -> set[str]:
    """Every published run tree, keyed the way the baseline keys them."""
    trees = SIFBU._published_run_trees(CORPUS)
    return {t.relative_to(CORPUS).as_posix() for t in trees}


def _baseline() -> dict:
    return json.loads(BASELINE.read_text(encoding="utf-8"))


@pytest.mark.skipif(not CORPUS.is_dir(), reason="no benchmark-data corpus here")
def test_every_baseline_entry_names_a_published_run():
    """A `per_run` key that names nothing is debt recorded against a ghost.

    This is the exact drift #1025 reported: entries survive a withdrawal, the
    total they sum to stays high, and the ratchet silently stops being a
    ceiling on anything real.
    """
    published = _published_keys()
    assert published, (
        "the gate's own `_published_run_trees` resolved ZERO published run "
        "trees, so this test would pass vacuously — that is the #1025 reach "
        "defect, not a clean tree")
    stale = sorted(k for k in _baseline().get("per_run", {}) if k not in published)
    assert not stale, (
        f"{len(stale)} baseline entr(ies) name run trees that are not "
        f"published: {stale}\n"
        f"  The ratchet's ceiling is the SUM of these, so a stale entry keeps "
        f"the ceiling high and the gate can never redden on a real regression "
        f"of that size. Re-derive with `--write-baseline` (only ever from a "
        f"sweep with proven reach — see #1025)."
    )


@pytest.mark.skipif(not CORPUS.is_dir(), reason="no benchmark-data corpus here")
def test_declared_population_matches_the_tree():
    """`runs_swept` / `runs_with_reports` must describe THIS tree.

    The filed state declared 17 swept against 13 published. A population field
    that overstates is how a reader concludes the sweep is broad when it is not.
    """
    rep = SIFBU.check_corpus(CORPUS)
    base = _baseline()
    assert base.get("runs_swept") == rep["runs_swept"], (
        f"baseline declares runs_swept={base.get('runs_swept')} but the tree "
        f"holds {rep['runs_swept']}")
    assert base.get("runs_with_reports") == rep["runs_with_reports"], (
        f"baseline declares runs_with_reports={base.get('runs_with_reports')} "
        f"but the tree holds {rep['runs_with_reports']}")


@pytest.mark.skipif(not CORPUS.is_dir(), reason="no benchmark-data corpus here")
def test_the_recorded_total_is_the_sum_of_its_own_entries():
    """`findings_total` must not drift from `per_run`.

    Cheap, and it is the invariant that makes the two tests above sufficient:
    with entries validated and the sum pinned, the ceiling cannot be inflated
    by editing only the scalar.
    """
    base = _baseline()
    per_run = base.get("per_run", {})
    assert base.get("findings_total") == sum(per_run.values()), (
        f"findings_total={base.get('findings_total')} but per_run sums to "
        f"{sum(per_run.values())}")
