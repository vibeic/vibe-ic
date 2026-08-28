"""vibe-ic#905 — the `ic/<IC>/` layout contract is ENFORCED, not just written down.

THE MEASURED DEFECT
===================
`benchmark-data/ic/<IC>/` permits exactly two kinds of entry: the shared
`input/`, and one `v<major>.<minor>.<patch>_<PDK>` directory per converged cell.
The rule was documented in `benchmark-data/PUBLISHING.md` and enforced by
nothing.

`benchmark_evidence_structure_check.py` walked CELLS, and `_discover_evidence_folders`
keeps a child of an IC directory only when it (a) matches the version-y name,
(b) carries a rejected prefix, or (c) holds a `RESULT.md`. Bare run output at the
IC level — `phase1/`, `phase3/`, `reports/`, `steps/`, a loose `provenance.jsonl` —
matches none of the three, so it was not merely un-failed, it was never
ENUMERATED. The tree printed "N/N conformant" over a directory that broke the
contract, which is the exact reading the gate exists to prevent: a MISNAMED
publish was named, an UNNAMED one was invisible.

WHAT THIS TEST PINS
===================
The tests below drive the PROGRAM (`check_ic_level_layout` / `main`) over a
synthetic tree. None of them recomputes the allowed-entry rule and asserts on
its own answer — a test shaped that way passes against the unfixed program,
because the rule it checks is the one it just implemented.

TWO-ARM CONTROL: every `test_bug_*` below FAILS against origin/main's program
(AttributeError: the symbol does not exist / a tree with strays reports 0
nonconformant) and PASSES against the fixed one. The `test_guard_*` tests are
the paired guard — behaviour that must NOT change, so the fix cannot be bought
by making the existing cell rules stricter or by failing everything.

chip-AGNOSTIC: every name here is synthetic (`ic_alpha`, `pdka`). No design,
PDK, foundry or process identifier appears.
"""

import json
import os
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

import benchmark_evidence_structure_check as besc  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

# --------------------------------------------------------------------------
# Fixture: a synthetic benchmark-data tree, built on the filesystem so the
# program is exercised through its real path handling.
# --------------------------------------------------------------------------

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


def _tree(root: Path, strays=(), stray_files=()) -> Path:
    """`root/ic/ic_alpha/` with input/, one conforming cell, and the given strays."""
    ic = root / "ic" / "ic_alpha"
    (ic / "input" / "docs").mkdir(parents=True, exist_ok=True)
    (ic / "input" / "docs" / "spec.md").write_text("spec\n", encoding="utf-8")
    _make_cell(ic / "v1.2.3_pdka")
    for s in strays:
        d = ic / s
        d.mkdir(parents=True, exist_ok=True)
        (d / "out.json").write_text("{}", encoding="utf-8")
    for f in stray_files:
        (ic / f).write_text("x\n", encoding="utf-8")
    return ic


@pytest.fixture()
def clean_tree(tmp_path):
    root = tmp_path / "benchmark-data"
    _tree(root)
    return root


@pytest.fixture()
def stray_tree(tmp_path):
    """The #905 shape: run output beside the cell instead of inside it."""
    root = tmp_path / "benchmark-data"
    _tree(root, strays=("phase1", "phase3", "reports"),
          stray_files=("provenance.jsonl",))
    return root


def _run(*args):
    out = _pr.run(
        [sys.executable, str(_PROGRAMS / "benchmark_evidence_structure_check.py"),
         *args],
        capture_output=True, text=True)
    return out.returncode, out.stdout + out.stderr


# --------------------------------------------------------------------------
# THE BUG ARM — these fail against origin/main.
# --------------------------------------------------------------------------

def test_bug_stray_run_output_at_the_ic_level_is_a_named_nonconformance():
    """The rule exists and NAMES the offending entries.

    Against origin/main this raises AttributeError — `check_ic_level_layout` is
    not a symbol, because the IC level was never checked at all."""
    assert hasattr(besc, "check_ic_level_layout"), (
        "the IC-level layout contract has no enforcing function")


def test_bug_the_tree_walk_fails_an_ic_carrying_stray_run_output(stray_tree):
    """End-to-end through main(): exit 1, and the message names each entry.

    Against origin/main the same tree exits 0 — the strays are not enumerated,
    so the walk reports every discovered folder conformant and says nothing
    about the directory that broke the contract."""
    rc, out = _run("--tree", str(stray_tree))
    assert rc == 1, f"stray run output at the IC level did not fail the gate\n{out}"
    assert "IC_LEVEL_LAYOUT" in out, out
    for name in ("phase1/", "phase3/", "reports/", "provenance.jsonl"):
        assert name in out, f"{name!r} was not named as a stray\n{out}"


def test_bug_a_stray_directory_is_reported_against_the_ic_not_a_phantom_cell(stray_tree):
    """The finding is attributed to the IC directory, with kind='ic-root'.

    This is what distinguishes RECORDING the divergence from mis-reporting the
    stray as a malformed cell: `phase1/` is not a cell that lost its RESULT.md,
    it is run output at the wrong level, and a reader must be told which."""
    ic = stray_tree / "ic" / "ic_alpha"
    res = besc.check_ic_level_layout(ic)
    assert res.kind == "ic-root", res
    assert res.conforms is False
    assert list(res.checks) == ["IC_LEVEL_LAYOUT"], res.checks
    assert Path(res.path).name == "ic_alpha"


def test_bug_the_json_summary_carries_the_ic_level_finding(stray_tree, tmp_path):
    """A machine consumer can see it too — a finding only a human can read is
    not one CI can gate on."""
    out_json = tmp_path / "summary.json"
    rc, _ = _run("--tree", str(stray_tree), "--json", str(out_json))
    assert rc == 1
    data = json.loads(out_json.read_text(encoding="utf-8"))
    ic_roots = [f for f in data["folders"] if f.get("kind") == "ic-root"]
    assert len(ic_roots) == 1, data["folders"]
    assert any("IC_LEVEL_LAYOUT" in f for f in ic_roots[0]["failures"]), ic_roots


# --------------------------------------------------------------------------
# THE PAIRED GUARD — behaviour that must NOT change.
# A fix bought by failing everything, or by tightening the cell rules, breaks
# these.
# --------------------------------------------------------------------------

def test_guard_a_conforming_ic_still_passes(clean_tree):
    """input/ + one v<ver>_<PDK> cell and nothing else: exit 0, no finding.

    This is the rule's other half. A check that fires on the conforming
    reference layout would be indistinguishable from one that fires on
    everything, and would prove nothing about the divergent tree above."""
    rc, out = _run("--tree", str(clean_tree))
    assert rc == 0, f"the conforming reference layout was failed\n{out}"
    assert "IC_LEVEL_LAYOUT" not in out, out


def test_guard_the_shared_input_dir_is_never_a_stray(clean_tree):
    ic = clean_tree / "ic" / "ic_alpha"
    assert besc.ic_level_strays(ic) == []
    assert besc.check_ic_level_layout(ic).conforms is True


def test_guard_the_cell_itself_is_still_validated_by_the_cell_rules(clean_tree):
    """The IC-level rule is ADDITIVE. The per-cell checks still run and still
    pass on a complete cell — the new rule must not have displaced them.

    Deliberately asserts on NOTHING the fix introduced, so it holds in BOTH
    arms: it is the guard, and a guard that only exists after the fix cannot
    witness the fix breaking something."""
    cell = clean_tree / "ic" / "ic_alpha" / "v1.2.3_pdka"
    res = besc.check_folder(cell)
    assert res.conforms, res.failures
    for rule in ("NAMING", "RESULT_PRESENT", "CONVERGED", "PHASE1_DOCS",
                 "PHASE2", "PHASE3_REPORTS", "GDS_MANIFEST"):
        assert res.checks.get(rule) is True, (rule, res.checks)


def test_guard_a_rejected_prefix_folder_is_still_failed_by_naming(tmp_path):
    """`clean_run_*` keeps its OWN diagnosis — NAMING, unchanged.

    Both-arms guard: the new rule must not have swallowed the older, sharper
    message about the contents being stripped on the way in."""
    root = tmp_path / "benchmark-data"
    ic = _tree(root)
    _make_cell(ic / "clean_run_v1234_20260101")
    rc, out = _run("--tree", str(root))
    assert rc == 1
    assert "NAMING" in out and "gitignored" in out, out


def test_bug_a_rejected_prefix_folder_is_also_at_the_wrong_level(tmp_path):
    """...and it now ALSO gets the IC-level finding.

    Reported by both rules on purpose: NAMING says its contents would be
    stripped, IC_LEVEL_LAYOUT says it is not a cell. Different consequences,
    and collapsing them would lose one."""
    root = tmp_path / "benchmark-data"
    ic = _tree(root)
    _make_cell(ic / "clean_run_v1234_20260101")
    rc, out = _run("--tree", str(root))
    assert rc == 1
    assert "IC_LEVEL_LAYOUT" in out, out
    assert "clean_run_v1234_20260101/" in out, out


def test_bug_a_cell_result_is_tagged_as_a_cell(clean_tree):
    """The kind discriminator exists on the cell side too, so a --json consumer
    can separate the two result shapes rather than inferring it from null fields."""
    res = besc.check_folder(clean_tree / "ic" / "ic_alpha" / "v1.2.3_pdka")
    assert res.kind == "cell"


def test_guard_no_ic_level_finding_when_a_single_cell_is_named(clean_tree, tmp_path):
    """Naming one cell asks about that cell, not its siblings.

    A caller validating one staged folder must not be handed findings about
    unrelated legacy content beside it — that is the noise that makes a gate
    get ignored."""
    root = tmp_path / "benchmark-data"
    ic = _tree(root, strays=("phase1",))
    rc, out = _run(str(ic / "v1.2.3_pdka"))
    assert rc == 0, out
    assert "IC_LEVEL_LAYOUT" not in out, out


# --------------------------------------------------------------------------
# Grandfathering: the CI shape must stay usable, in BOTH directions.
# --------------------------------------------------------------------------

def _git(repo: Path, *args):
    return _pr.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)


@pytest.fixture()
def repo_with_legacy_strays(tmp_path):
    """A repo whose FIRST commit already carries IC-level strays."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    _tree(repo / "benchmark-data", strays=("phase1", "reports"))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "legacy")
    return repo


def test_guard_legacy_strays_are_grandfathered_by_changed_since(repo_with_legacy_strays):
    """Publishing a NEW conforming cell beside pre-existing strays must not fail.

    Scoping the diff to the IC directory would fail this push on evidence it did
    not create — exactly what `--changed-since` exists to prevent."""
    repo = repo_with_legacy_strays
    _make_cell(repo / "benchmark-data" / "ic" / "ic_alpha" / "v1.4.0_pdka")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "publish a new conforming cell")
    out = _pr.run(
        [sys.executable, str(_PROGRAMS / "benchmark_evidence_structure_check.py"),
         "--tree", str(repo / "benchmark-data"), "--changed-since", "HEAD~1"],
        capture_output=True, text=True, cwd=str(repo))
    combined = out.stdout + out.stderr
    assert out.returncode == 0, (
        f"a conforming publish was failed by pre-existing strays\n{combined}")
    assert "IC_LEVEL_LAYOUT" not in combined, combined


def test_bug_newly_added_ic_level_output_is_caught_by_changed_since(repo_with_legacy_strays):
    """The other direction — grandfathering must not become a blanket amnesty.

    A push that ADDS run output at the IC level is the regression the rule
    exists to stop, and `--changed-since` must still catch it."""
    repo = repo_with_legacy_strays
    new = repo / "benchmark-data" / "ic" / "ic_alpha" / "phase3"
    new.mkdir(parents=True)
    (new / "out.json").write_text("{}", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "dump run output at the IC level")
    out = _pr.run(
        [sys.executable, str(_PROGRAMS / "benchmark_evidence_structure_check.py"),
         "--tree", str(repo / "benchmark-data"), "--changed-since", "HEAD~1"],
        capture_output=True, text=True, cwd=str(repo))
    combined = out.stdout + out.stderr
    assert out.returncode == 1, (
        f"newly-added IC-level run output was not caught\n{combined}")
    assert "IC_LEVEL_LAYOUT" in combined and "phase3/" in combined, combined


def test_guard_untracked_local_scratch_is_not_a_published_finding(repo_with_legacy_strays):
    """Inside a repo, an entry with no tracked file is a developer's scratch
    directory, not a statement about what was PUBLISHED. NO_RAW_GEOMETRY is
    git-aware for this same reason; the two must not disagree."""
    repo = repo_with_legacy_strays
    scratch = repo / "benchmark-data" / "ic" / "ic_alpha" / "_scratch_local"
    scratch.mkdir()
    (scratch / "note.txt").write_text("local\n", encoding="utf-8")
    strays = [p.name for p in
              besc.ic_level_strays(repo / "benchmark-data" / "ic" / "ic_alpha")]
    assert "_scratch_local" not in strays, strays
    assert "phase1" in strays and "reports" in strays, strays
