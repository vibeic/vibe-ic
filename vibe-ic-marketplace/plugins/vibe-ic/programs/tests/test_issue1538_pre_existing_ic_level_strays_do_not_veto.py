"""vibe-ic#1538 — `--changed-since` promises grandfathering and IC_LEVEL_LAYOUT
does not deliver it, so a pre-existing divergence is a VETO on the next push.

THE MEASURED DEFECT
===================
`benchmark_evidence_structure_check.py --tree benchmark-data --changed-since
<base>` is the shape the pre-push hook and `gatekeeper-land.sh` both run, and the
program states its contract for that shape three times:

  * module header — "enforce ONLY the evidence folders this push touched ...
    pre-existing folders are grandfathered (never retroactively failed by an
    unrelated PR)";
  * `--changed-since` CLI help — "pre-existing folders are grandfathered";
  * `_changed_ic_dirs` — "a push that ADDS run output at the IC level is caught,
    and one that merely publishes beside pre-existing strays is not."

The IC-level half did not honour it. `_changed_ic_dirs` used the baseline only to
SELECT which IC directories to inspect, and `check_ic_level_layout` then judged
each selected IC ABSOLUTELY — every stray entry it carries, whoever created it
and whenever. Selecting on "a file under a pre-existing stray changed" and then
judging absolutely means that MODIFYING a file inside legacy run output is
reported as though the change had created that output.

Measured on origin/main `75776dbbb`, a commit that adds ZERO paths (one already
tracked file appended to, nothing added) inside 8 of the 9 ICs that carry run
output:

    IC                           rc   changed/ADDED   finding
    caravel_user_project         1    1/0             IC_LEVEL_LAYOUT: 12 entries
    edge_llm_accel               1    1/0             IC_LEVEL_LAYOUT: 15 entries
    edge_llm_matmul_accel        1    1/0             IC_LEVEL_LAYOUT: 11 entries
    ibex                         1    1/0             IC_LEVEL_LAYOUT:  8 entries
    opentitan_aes                1    1/0             IC_LEVEL_LAYOUT:  8 entries
    sha256                       1    1/0             IC_LEVEL_LAYOUT: 20 entries
    subservient                  1    1/0             IC_LEVEL_LAYOUT: 15 entries
    u_hawaii_adc                 1    1/0             IC_LEVEL_LAYOUT:  3 entries

Nothing was added; every named entry is pre-existing. The consequence is not
tidiness: `test_matrix_d3_outputs_produced` ends every unevidenced verdict with
"Commit (or register in the manifest) a run tree that carries it", and the run
roots it names live inside exactly these IC directories — so the repository
prints a remedy its own pre-push hook then refuses.

WHAT THIS TEST PINS
===================
The DELTA form of the IC-level rule, in both directions:

  * `test_bug_*`  — an entry the change did not create must not veto the change,
    and the entries it did not create must still be DISCLOSED, never silently
    waived. These fail against origin/main's program.
  * `test_guard_*` — the paired guard. A NEW IC-level entry still fails; the
    grandfathered register is read from the baseline COMMIT so no checked-in file
    can widen it; a baseline the gate could not read does NOT grandfather; and
    the full `--tree` form (no `--changed-since`) still reports every legacy
    entry, so migrating or retiring them stays measurable.

None of these recomputes the allowed-entry rule and asserts on its own answer —
each drives the real program over a real git repo.

chip-AGNOSTIC: every name here is synthetic (`ic_alpha`, `pdka`). No design, PDK,
foundry, node or process identifier appears.
"""

import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

import benchmark_evidence_structure_check as besc  # noqa: E402

_TIMEOUT = 60  # every subprocess in this file is bounded well under the cap
_GATE = _PROGRAMS / "benchmark_evidence_structure_check.py"


# --------------------------------------------------------------------------
# Fixtures — a real git repo, because the property under test is a property of
# the diff against a baseline commit.
# --------------------------------------------------------------------------

def _git(repo: Path, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, timeout=_TIMEOUT)


def _commit(repo: Path, msg: str):
    _git(repo, "add", "-A")
    return _git(repo, "-c", "commit.gpgsign=false", "commit", "-qm", msg)


def _make_cell(cell: Path) -> None:
    """A cell complete enough that the PER-CELL rules pass, so any failure this
    test observes is attributable to the IC-LEVEL rule and nothing else."""
    (cell / "phase1" / "generated_docs").mkdir(parents=True, exist_ok=True)
    (cell / "phase1" / "generated_docs" / "L1.json").write_text("{}", encoding="utf-8")
    (cell / "phase2" / "stage2" / "synth").mkdir(parents=True, exist_ok=True)
    (cell / "phase2" / "stage2" / "synth" / "stats.json").write_text("{}", encoding="utf-8")
    (cell / "reports" / "phase3").mkdir(parents=True, exist_ok=True)
    (cell / "reports" / "phase3" / "drc.rpt").write_text("clean\n", encoding="utf-8")
    gds = cell / "phase3" / "stage4" / "gds"
    gds.mkdir(parents=True, exist_ok=True)
    (gds / "GDS_MANIFEST.txt").write_text(
        "top.gds 1234B sha256:" + ("a" * 64) + "\n", encoding="utf-8")
    (cell / "RESULT.md").write_text("VERDICT: PASS\n", encoding="utf-8")


@pytest.fixture()
def legacy_repo(tmp_path):
    """A repo whose FIRST commit already carries IC-level strays.

    Shaped like the real corpus: the shared `input/`, one conforming cell, and
    run output that landed beside the cell instead of inside it — two stray
    directories and a loose file.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    ic = repo / "benchmark-data" / "ic" / "ic_alpha"
    (ic / "input" / "docs").mkdir(parents=True)
    (ic / "input" / "docs" / "spec.md").write_text("spec\n", encoding="utf-8")
    _make_cell(ic / "v1.2.3_pdka")
    for s in ("phase1", "reports"):
        (ic / s).mkdir(parents=True)
        (ic / s / "out.json").write_text("{}\n", encoding="utf-8")
    (ic / "provenance.jsonl").write_text('{"n":1}\n', encoding="utf-8")
    _commit(repo, "legacy layout, predating the v<ver>_<PDK> convention")
    return repo


def _run_changed_since(repo: Path, base: str = "HEAD~1"):
    out = subprocess.run(
        [sys.executable, str(_GATE), "--tree", str(repo / "benchmark-data"),
         "--changed-since", base],
        capture_output=True, text=True, timeout=_TIMEOUT, cwd=str(repo))
    return out.returncode, out.stdout + out.stderr


def _run_absolute(repo: Path):
    out = subprocess.run(
        [sys.executable, str(_GATE), "--tree", str(repo / "benchmark-data")],
        capture_output=True, text=True, timeout=_TIMEOUT, cwd=str(repo))
    return out.returncode, out.stdout + out.stderr


def _added_count(repo: Path, base: str = "HEAD~1") -> int:
    out = _git(repo, "diff", "--name-only", "--diff-filter=A", f"{base}...HEAD")
    return len([ln for ln in out.stdout.splitlines() if ln.strip()])


# --------------------------------------------------------------------------
# THE BUG ARM — these fail against origin/main 75776dbbb.
# --------------------------------------------------------------------------

def test_bug_touching_a_file_inside_a_pre_existing_stray_does_not_veto(legacy_repo):
    """The reproduction, reduced: a commit that ADDS NOTHING is refused.

    Appending to a file inside legacy run output creates no IC-level entry, so
    the IC-level layout finding is identical before and after. Failing the push
    for it reports the baseline as if it were the change.
    """
    repo = legacy_repo
    p = repo / "benchmark-data" / "ic" / "ic_alpha" / "phase1" / "out.json"
    p.write_text('{"touched": true}\n', encoding="utf-8")
    _commit(repo, "modify a file inside pre-existing run output")

    assert _added_count(repo) == 0, "control invalid: the commit added a path"

    rc, out = _run_changed_since(repo)
    assert rc == 0, (
        "a commit that added ZERO paths was refused by pre-existing IC-level "
        f"entries it did not create\n{out}")


def test_bug_the_grandfathered_entries_are_disclosed_not_silently_waived(legacy_repo):
    """Grandfathering must be a RECORD, not an amnesty you cannot see.

    A waiver that prints nothing is indistinguishable from a rule that was met,
    which is the reading this whole program exists to prevent. The pre-existing
    entries must be named, counted, and stated as excluded from THIS change.
    """
    repo = legacy_repo
    p = repo / "benchmark-data" / "ic" / "ic_alpha" / "reports" / "out.json"
    p.write_text('{"touched": true}\n', encoding="utf-8")
    _commit(repo, "modify a file inside pre-existing run output")

    rc, out = _run_changed_since(repo)
    assert rc == 0, out
    assert "3" in out and "grandfathered" in out.lower(), (
        f"the 3 pre-existing IC-level entries were not disclosed\n{out}")
    for name in ("phase1", "reports", "provenance.jsonl"):
        assert name in out, f"pre-existing entry {name!r} was not named\n{out}"


def test_bug_a_new_conforming_cell_beside_a_touched_stray_still_lands(legacy_repo):
    """The #1457 shape: publish new evidence AND touch the legacy tree.

    The push does both, so `_changed_ic_dirs` selects the IC. Before the fix that
    selection alone was fatal.
    """
    repo = legacy_repo
    ic = repo / "benchmark-data" / "ic" / "ic_alpha"
    _make_cell(ic / "v1.4.0_pdka")
    (ic / "phase1" / "out.json").write_text('{"touched": true}\n', encoding="utf-8")
    _commit(repo, "publish a conforming cell and touch the legacy tree")

    rc, out = _run_changed_since(repo)
    assert rc == 0, (
        f"a conforming publish was failed by pre-existing strays beside it\n{out}")


# --------------------------------------------------------------------------
# THE GUARD ARM — behaviour that must NOT change. The fix is worthless if it is
# bought by making the rule unable to fail.
# --------------------------------------------------------------------------

def test_guard_a_newly_added_stray_directory_still_fails(legacy_repo):
    """The regression the rule exists to stop. Grandfathering must not become a
    blanket amnesty for the IC directory it applies to."""
    repo = legacy_repo
    new = repo / "benchmark-data" / "ic" / "ic_alpha" / "phase3"
    new.mkdir(parents=True)
    (new / "out.json").write_text("{}", encoding="utf-8")
    _commit(repo, "dump run output at the IC level")

    rc, out = _run_changed_since(repo)
    assert rc == 1, f"newly-added IC-level run output was not caught\n{out}"
    assert "IC_LEVEL_LAYOUT" in out and "phase3/" in out, out


def test_guard_a_newly_added_stray_file_still_fails(legacy_repo):
    """A loose FILE at the IC level is the same violation as a directory, and it
    is the shape a repair PR reaches for when it follows the corpus convention."""
    repo = legacy_repo
    ic = repo / "benchmark-data" / "ic" / "ic_alpha"
    (ic / "SOURCE_MANIFEST.md").write_text("sources\n", encoding="utf-8")
    _commit(repo, "add a loose file at the IC level")

    rc, out = _run_changed_since(repo)
    assert rc == 1, f"a newly-added loose IC-level file was not caught\n{out}"
    assert "SOURCE_MANIFEST.md" in out, out


def test_guard_the_failure_names_the_added_entry_not_the_carried_ones(legacy_repo):
    """A finding that re-lists the whole baseline every time is the noise that
    makes a gate get ignored — and it is what made this one unreadable. The
    FAILURE line names what the change added; the carried set is a separate,
    clearly-labelled disclosure."""
    repo = legacy_repo
    new = repo / "benchmark-data" / "ic" / "ic_alpha" / "phase3"
    new.mkdir(parents=True)
    (new / "out.json").write_text("{}", encoding="utf-8")
    _commit(repo, "dump run output at the IC level")

    rc, out = _run_changed_since(repo)
    assert rc == 1, out
    fail_lines = [ln for ln in out.splitlines() if ln.strip().startswith("x ")]
    assert fail_lines, out
    finding = " ".join(fail_lines)
    assert "phase3/" in finding, finding
    assert "1 entry" in finding, (
        f"the finding counted more than the entry this change added\n{finding}")


def test_guard_the_register_is_read_from_the_baseline_commit_only(legacy_repo):
    """No file in the working tree may widen the grandfathered set.

    The register is derived from `git ls-tree <base>`, so it cannot be edited
    into standing permission the way a checked-in allowlist can. Adding an entry
    to the tree does not add it to the baseline — that is the ratchet.
    """
    repo = legacy_repo
    ic = repo / "benchmark-data" / "ic" / "ic_alpha"
    (ic / "phase3").mkdir()
    (ic / "phase3" / "out.json").write_text("{}", encoding="utf-8")
    _commit(repo, "dump run output at the IC level")

    base_strays, why = besc._baseline_ic_strays("HEAD~1", ic)
    assert base_strays is not None, why
    assert base_strays == {"phase1", "reports", "provenance.jsonl"}, base_strays
    assert "phase3" not in base_strays, (
        "an entry present only in the working tree entered the register")


def test_guard_the_register_shrinks_when_an_entry_is_retired(legacy_repo):
    """A pre-existing entry that is removed leaves the register — it does not
    linger as permission for a future entry of the same name to reappear."""
    repo = legacy_repo
    ic = repo / "benchmark-data" / "ic" / "ic_alpha"
    _git(repo, "rm", "-r", "-q", str(ic / "reports"))
    _commit(repo, "retire one legacy entry")

    # From the NEW head, `reports` is gone from the tree and from the register.
    base_strays, why = besc._baseline_ic_strays("HEAD", ic)
    assert base_strays is not None, why
    assert base_strays == {"phase1", "provenance.jsonl"}, base_strays


def test_guard_an_unreadable_baseline_does_not_grandfather(legacy_repo):
    """"No baseline" must never mean "everything is allowed".

    This is the way the fix goes wrong quietly, and it is the failure mode this
    repo already removed from `gate_host_independence_check`. With no baseline
    the rule falls back to its ABSOLUTE form and says why.
    """
    ic = legacy_repo / "benchmark-data" / "ic" / "ic_alpha"
    res = besc.check_ic_level_layout(
        ic, baseline=None, baseline_why="git ls-tree against the base failed")
    assert res.conforms is False, res
    assert any("IC_LEVEL_LAYOUT" in f for f in res.failures), res.failures
    joined = " ".join(res.failures)
    for name in ("phase1", "reports", "provenance.jsonl"):
        assert name in joined, joined
    assert "absolutely" in joined.lower(), (
        f"the fallback to the absolute form was not disclosed\n{joined}")


def test_guard_the_full_tree_form_still_reports_every_legacy_entry(legacy_repo):
    """Migrating or retiring the legacy entries stays MEASURABLE.

    `--changed-since` scopes what a push is answerable for; it must not change
    what the repository can see about itself. Option (1) and option (3) in #1538
    both depend on this number staying whole.
    """
    rc, out = _run_absolute(legacy_repo)
    assert rc == 1, f"the full-tree form stopped reporting the legacy divergence\n{out}"
    assert "IC_LEVEL_LAYOUT: 3 entries" in out, out
    for name in ("phase1/", "reports/", "provenance.jsonl"):
        assert name in out, out


def test_guard_an_ic_with_no_strays_is_unaffected(tmp_path):
    """A conforming IC still passes with its denominator stated, and gains no
    grandfathering note it did not earn."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    ic = repo / "benchmark-data" / "ic" / "ic_alpha"
    (ic / "input").mkdir(parents=True)
    (ic / "input" / "spec.md").write_text("spec\n", encoding="utf-8")
    _make_cell(ic / "v1.2.3_pdka")
    _commit(repo, "a conforming IC")

    res = besc.check_ic_level_layout(ic, baseline=set())
    assert res.conforms is True, res
    assert res.grandfathered in (0, None), res.grandfathered
    assert not res.notes, res.notes


def test_guard_the_zero_denominator_skip_survives(tmp_path):
    """#967's distinction is upstream of this change and must be untouched: an IC
    that published NOTHING is still SKIPped, not grandfathered into a pass."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    ic = repo / "benchmark-data" / "ic" / "ic_alpha"
    ic.mkdir(parents=True)
    res = besc.check_ic_level_layout(ic, baseline=set())
    assert res.skipped is True, res
    assert res.conforms is None, res
