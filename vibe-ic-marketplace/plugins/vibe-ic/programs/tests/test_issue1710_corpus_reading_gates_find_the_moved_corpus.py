#!/usr/bin/env python3
"""The four corpus-READING hygiene gates after the corpus moved out (#1710).

WHY THIS FILE EXISTS
====================
v1.10.56 moved `benchmark-data/` to `vibeic/benchmark-data`. Four gates in
`tools/ci/repo_hygiene_gates.sh` were aimed at what it held, and every one of
them then refused:

    L-doc field producer      [SKIP] no corpus (benchmark-data/ic not found)   rc 2
    evidence citation resolves[SKIP] no scan root (benchmark-data/ic not found)rc 2
    citation routing is true  [CANNOT DETERMINE] no tracked CITATION_ROUTING.txt rc 2
    L4 -> SystemRDL disposition [SKIP] no L4_REGMAP.json under <repo>          rc 2

Every refusal was CORRECT for what the gate was asked — a check that could not
look has not passed, and `run` in `_gate_dispatch.sh` maps rc 2 to FAIL. What was
wrong is WHERE they were told to look.

WHERE EACH SUBJECT WENT, because "the gate is broken" and "its subject moved" are
different diagnoses and only one of them is true here:

    L-doc field producer        its corpus (`benchmark-data/ic`) moved.
    evidence citation resolves  its corpus AND its debt register moved — the
                                register lives beside the data it describes.
    citation routing is true    ITS SUBJECT moved. Every CITATION_ROUTING.txt
                                ships INSIDE a published cell; the four that
                                existed were deleted by the same commits.
    L4 -> SystemRDL disposition ITS SUBJECT moved. All 199 tracked
                                `L4_REGMAP.json` were under `benchmark-data/`.

THE FOUR OUTCOMES, WHICH MUST NOT COLLAPSE INTO FEWER
=====================================================
    pointer set + unreadable        -> UNDETERMINED (rc 2). Never excused, with
                                       or without --corpus-may-be-absent.
    pointer set + present but NOT a
      git checkout                  -> UNDETERMINED (rc 2), for the gates that
                                       read git's INDEX. An empty `ls-files` is
                                       "I could not look", not "there are none".
    nothing anywhere + the CALL SITE
      opted in                      -> NO_CORPUS (rc 0). Nothing scanned, and
                                       NOTHING CLAIMED to have been scanned.
    nothing anywhere + nobody said  -> UNDETERMINED (rc 2). Unchanged.

EVERY CASE HERE IS PAIRED, and the pairing that matters most is the last group:
a corpus with a PLANTED DEFECT is supplied through $VIBE_IC_BENCHMARK_DATA with
`--corpus-may-be-absent` set, and every gate must still return rc 1. A change
that only proved "the gates stopped blocking" would pass just as well against
gates that had been deleted.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures("landing_corpus_binding_is_test_local")

import _corpus_location as _corpus_loc
import repo_hygiene_parallel as _parallel

PROGRAMS = Path(__file__).resolve().parents[1]
REPO = PROGRAMS.parents[3]
L_DOC = PROGRAMS / "l_doc_field_producer_check.py"
EVIDENCE = PROGRAMS / "evidence_citation_resolves_check.py"
ROUTING = PROGRAMS / "citation_routing_is_true_check.py"
L4 = PROGRAMS / "l4_systemrdl_export.py"
ENV = "VIBE_IC_BENCHMARK_DATA"
OWNED = PROGRAMS / "_owned_process_supervisor.py"


def _atomic_owned(argv, *, env):
    """Run one intentionally indivisible fixture operation to final zero."""
    rc, body, problem = _parallel._run(
        list(argv), REPO, env, stall_grace_s=float("inf"), atomic=True)
    if problem:
        raise AssertionError(
            "OWNED_CHILD_NORECORD: " + problem + "\n" + body[-5000:])
    return rc, body














def test_atomic_child_preserves_a_natural_nonzero_result():
    rc, body = _atomic_owned(
        [sys.executable, "-c",
         "import sys; print('MEASURED_CHILD_RED'); sys.exit(7)"],
        env=dict(os.environ))
    assert rc == 7
    assert "MEASURED_CHILD_RED" in body


def test_atomic_child_with_live_descendant_is_norecord_after_cleanup(tmp_path):
    """Natural root exit cannot erase unfinished owned work."""
    pid_file = tmp_path / "escaped.pid"
    grandchild = "import time; time.sleep(30)"
    child = (
        "import pathlib,subprocess,sys\n"
        f"p=subprocess.Popen([sys.executable,'-c',{grandchild!r}], "
        "start_new_session=True)\n"
        f"pathlib.Path({str(pid_file)!r}).write_text(str(p.pid))\n")
    with pytest.raises(AssertionError, match="OWNED_CHILD_NORECORD"):
        _atomic_owned([sys.executable, "-c", child], env=dict(os.environ))
    escaped_pid = int(pid_file.read_text(encoding="utf-8"))
    with pytest.raises(ProcessLookupError):
        os.kill(escaped_pid, 0)


def test_atomic_policy_rejects_a_progress_log_before_launch(tmp_path):
    marker = tmp_path / "child-launched"
    result_path = tmp_path / "owned-result.json"
    progress_path = tmp_path / "progress.log"
    progress_path.touch()
    proc = subprocess.run(
        [sys.executable, str(OWNED), "--result", str(result_path),
         "--cwd", str(REPO), "--stall-grace", "1", "--poll", ".1",
         "--atomic", "--progress", str(progress_path), "--",
         sys.executable, "-c",
         f"from pathlib import Path; Path({str(marker)!r}).touch()"],
        cwd=str(REPO), capture_output=True, text=True)
    assert proc.returncode == 2
    assert "not allowed with argument" in proc.stderr
    assert not marker.exists() and not result_path.exists()


def test_atomic_api_rejects_a_progress_log_before_launch(tmp_path):
    import _owned_process_supervisor as owned  # noqa: PLC0415

    marker = tmp_path / "api-child-launched"
    progress_path = tmp_path / "progress.log"
    progress_path.touch()
    record = owned.run_owned(
        [sys.executable, "-c",
         f"from pathlib import Path; Path({str(marker)!r}).touch()"],
        REPO, dict(os.environ), progress_path=progress_path,
        stall_grace_s=1, poll_s=.1, output_progress=False)
    assert record.rc == 2
    assert record.launched is False
    assert record.outcome == "policy_refused"
    assert "INVALID_PROGRESS_POLICY" in str(record.problem)
    assert not marker.exists()




# ---------------------------------------------------------------------------
# corpora. Each carries ONE planted defect of the shape its gate exists for,
# and each has a byte-identical CLEAN twin — without the twin, "the gate
# failed" is compatible with a gate that fails on every corpus it is handed.
# ---------------------------------------------------------------------------
_L4_DOC = {
    "schema_version": 2, "doc_class": "regmap", "ic_name": "unit_under_test",
    "register_map_present": True,
    "registers": [{
        "name": "CTRL", "address": "0x00", "address_int": 0, "width_bits": 32,
        "access": "RW", "description": "control",
        "fields": [{"field_name": "EN", "bits": "0", "msb": 0, "lsb": 0,
                    "access": "RW", "description": "enable"}],
    }],
}








# ===========================================================================
# 1. THE LOAD-BEARING PAIR: a planted defect in a SUPPLIED corpus still FAILS,
#    with the opt-in set. If the rc 2 -> rc 0 widening had been bought by
#    weakening the gates, these four are the tests that would have gone green
#    with it.
# ===========================================================================








# ===========================================================================
# 2. THE CONTROLS. The same shape with nothing wrong with it passes, so the
#    four FAILs above are about the defect and not about the corpus being
#    somewhere unusual.
# ===========================================================================










# ===========================================================================
# 3. NOTHING ANYWHERE + the caller said so -> NO_CORPUS, rc 0, and it SAYS
#    nothing was scanned. This is the case that unblocks the removal.
# ===========================================================================


# ===========================================================================
# 4. …AND WITHOUT THE FLAG THEY ALL STILL BLOCK. The half that makes case 3
#    mean something: the relaxation is OPT-IN AT THE CALL SITE, never a new
#    default.
# ===========================================================================


# ===========================================================================
# 5. A BROKEN POINTER IS NEVER EXCUSED — not even with the flag. "Somebody said
#    where the corpus is and was wrong" is a different event from "there is
#    none", and a mistyped path or a no-op CI fetch step must not go green.
# ===========================================================================


# ===========================================================================
# 6. A DIRECTORY IS NOT A CHECKOUT — the fatal an adversarial reviewer found in
#    the first version of the v1.10.60 fix, pinned here for the two gates in
#    this set that read git's INDEX.
#
#    The corpus lives in its own repository now, so a tarball fetch, an archive
#    export, a dead `git clone` or a worktree without `.git` all produce a tree
#    that is PRESENT and has no index. Over it `git ls-files` returns nothing,
#    and reading that as "there are none" is a FAILED FETCH CERTIFYING A TREE —
#    strictly worse than NO_CORPUS, which at least states nothing was scanned.
#
#    BOTH ARMS, built byte-identically except for `git init`.
# ===========================================================================








# ===========================================================================
# 7. AN EMPTY RESULT IS NOT A ZERO. Each gate is handed a corpus that IS there
#    and holds nothing it can read, and must refuse rather than roll a verdict
#    up over an empty population.
# ===========================================================================










# ===========================================================================
# 8. THE OVERRIDE IS ANNOUNCED. A gate that scans a tree other than the one on
#    its command line must say so — that silence is how a mis-aimed `--tree`
#    once reported "13/28 conformant" over a tree an absolute path found 8
#    failures in.
# ===========================================================================


# ===========================================================================
# 9. THE SHIPPED CALL SITES CARRY THE FLAG. Everything above tests the
#    programs; this tests the only lines that ever invoke them in production.
#    Without it all four programs could be perfect and all four gates still red.
# ===========================================================================


# ── vibe-ic#1710 — the resolution must be a fact about the REPOSITORY ───────
def _fake_repo(tmp_path: Path) -> Path:
    """A checkout-shaped tree, with a corpus sitting ABOVE it."""
    outer = tmp_path / "outer"
    (outer / "benchmark-data" / "ic").mkdir(parents=True)     # the stranger
    repo = outer / "checkout"
    (repo / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs").mkdir(
        parents=True)
    return repo


def test_default_named_never_leaves_the_repository(tmp_path):
    """THE HOST-DEPENDENCE THIS FILE IS NAMED FOR.

    The three corpus-reading gates resolved their default root with an
    UNBOUNDED `here.parents` walk, which does not stop at the checkout. On a
    machine whose $HOME happens to carry a `benchmark-data/`, the gate scanned
    THAT tree and `resolve()` then declined the caller's pointer in favour of
    it — so the same commit produced different verdicts on different machines.
    MEASURED on main a4caccefe, same host, two clones: 15 failed under a
    checkout below $HOME (which carried a benchmark-data/) and 42 passed under
    one below /var/tmp (which did not).

    Bounded at the repository root, the stranger above the checkout is
    invisible and the answer depends only on the repository.
    """
    repo = _fake_repo(tmp_path)
    start = repo / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
    got = _corpus_loc.default_named(start, "benchmark-data/ic")
    assert not got.is_absolute() or repo in got.parents, (
        f"resolution escaped the repository: {got}")
    assert (tmp_path / "outer" / "benchmark-data" / "ic") != got, (
        "the corpus ABOVE the checkout was adopted — this is the host "
        "dependence the bound exists to remove")
    assert got == Path("benchmark-data/ic"), (
        "a repo that carries no corpus must return the LITERAL relative path, "
        "so resolve() follows the pointer and refuse() can name what it looked "
        f"for; got {got}")


def test_default_named_prefers_the_repositorys_OWN_corpus(tmp_path):
    """The bound must not break the in-repo case: a checkout that DOES carry
    the tree resolves to its own copy, not to the stranger above it."""
    repo = _fake_repo(tmp_path)
    (repo / "benchmark-data" / "ic").mkdir(parents=True)
    start = repo / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
    got = _corpus_loc.default_named(start, "benchmark-data/ic")
    assert got == repo / "benchmark-data" / "ic", got


def test_repo_root_stops_at_the_marker(tmp_path):
    """`vibe-ic-marketplace/` is the marker, not `.git` — a tarball export and
    a worktree without its gitdir are still the tree the gate is about."""
    repo = _fake_repo(tmp_path)
    start = repo / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
    assert _corpus_loc.repo_root(start) == repo
    assert _corpus_loc.repo_root(tmp_path) is None


# ===========================================================================
# 6. THE REPOSITORY IS NOT THE CORPUS.
#
# v1.16.32 (37a46c00ca) excluded this plugin's own `programs/tests/` from the
# walk, which closed the seven fixtures 4ce74e03b (v1.13.37) had landed. The
# assertions below are about the PROPERTY that exclusion is an instance of,
# because an exclusion answers only for the directories somebody has already
# thought of. MEASURED at bcedcdf25d9c with one cell-shaped document planted
# at `docs/campaigns/<run>/phase1/generated_docs/L4_REGMAP.json` — the
# directory v1.15.79 MOVED THE CAMPAIGN TREES TO:
#
#     root <repo>: 1 on disk, 1 published
#     [FAIL] 1 L4 key(s) have NO recorded SystemRDL disposition.
#
# The pair is: THE SAME DOCUMENT BYTES, in two places in one repository, must
# get opposite answers. A test that only asserted "the plant is skipped" would
# also pass against a gate that had stopped auditing anything at all, which is
# why the second arm carries a real defect and must still be REFUSED.
# ===========================================================================


_PUBLISHED_REL = ("benchmark-data/ic/spm/v1.9.96_pdkX/phase1/generated_docs/"
                  "L4_REGMAP.json")

#: Two addresses in this repository that are NOT where a cell is published.
#: The first is the one v1.16.32 excluded by name; the second is the one that
#: exclusion does not reach, and is where v1.15.79 moved the campaign trees.
_UNPUBLISHED_RELS = (
    ("vibe-ic-marketplace/plugins/vibe-ic/programs/tests/fixtures/"
     "stage_phase1_on_pass_review/reject_x/phase1/generated_docs/"
     "L4_REGMAP.json"),
    "docs/campaigns/2026-09-run/phase1/generated_docs/L4_REGMAP.json",
)
