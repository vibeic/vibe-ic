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

from _published_corpus import corpus_root, needs_corpus

PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN_ROOT / "programs"
REPO_ROOT = PLUGIN_ROOT.parent.parent.parent
BASELINE = PROGRAMS / "step_internal_fail_bubble_up_baseline.json"
# THE POPULATION IS READ OUT OF THE RECORD (vibe-ic#1223), not hardcoded here.
# This said `benchmark-data` while the CI gate sweeps `benchmark-data/ic`; with
# the population defined by the artefact rather than by a directory NAME those
# are 117 run trees / 45 findings and 16 / 22 respectively, so a hardcoded root
# would validate the baseline against a set the ratchet never holds.
_POPULATION = json.loads(
    BASELINE.read_text(encoding="utf-8"))["corpus_population"]


# ...AND THE ROOT IT HANGS OFF IS NO LONGER THIS REPOSITORY. The published run
# trees moved to vibeic/benchmark-data, and a clone of that repository IS the
# `benchmark-data` directory — so `benchmark-data/ic` and `<clone>/ic` name the
# SAME population. Only the leading component changes; the population is still
# the one the record declares, which is the whole point of #1223.
def _population_under(root: Path) -> Path:
    p = Path(_POPULATION)
    try:
        return root / p.relative_to("benchmark-data")
    except ValueError:                      # a population named some other way
        return root / p


_CORPUS_ROOT = corpus_root()
CORPUS = (_population_under(_CORPUS_ROOT) if _CORPUS_ROOT is not None
          else REPO_ROOT / _POPULATION)

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


@needs_corpus
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


@needs_corpus
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


def test_the_recorded_total_is_the_sum_of_its_own_entries():
    """`findings_total` must not drift from `per_run`.

    Cheap, and it is the invariant that makes the two tests above sufficient:
    with entries validated and the sum pinned, the ceiling cannot be inflated
    by editing only the scalar.

    DELIBERATELY UNGUARDED. This reads the RECORD and nothing else — no corpus
    is opened — so a corpus-presence skip here would be a check declining to
    run when it can in fact measure, which is the same dishonesty as a check
    reporting a measurement it never made. It carried
    `skipif(not CORPUS.is_dir())` by copy-paste from its two neighbours.
    """
    base = _baseline()
    per_run = base.get("per_run", {})
    assert base.get("findings_total") == sum(per_run.values()), (
        f"findings_total={base.get('findings_total')} but per_run sums to "
        f"{sum(per_run.values())}")
