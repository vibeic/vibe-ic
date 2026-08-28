"""vibe-ic#967 — an `ic/<IC>/` that published NOTHING is not a conformant unit.

THE MEASURED DEFECT
===================
#952 gave `benchmark_evidence_structure_check` an IC-LEVEL rule, and relaxed the
"nothing to check" refusal in `main()` from `if not targets:` to
`if not targets and not ic_dirs:` so the new units could be reached. That opened
the hole one level up from the one it closed: a tree of `ic/<IC>/` directories
containing NOTHING AT ALL now prints

    benchmark_evidence_structure_check: 3/3 conformant, 0 nonconformant   rc 0

where the same program before #952 refused it with rc 2, "ERROR: no evidence
folders to check". The RULE is not wrong — an empty directory genuinely has no
stray entries — the ROLL-UP is: it credits a number that reads like coverage to
a tree that published nothing. "3/3 conformant" over an empty tree is a PASS
earned by having nothing to fail on, which is the exact misreading the IC-level
rule was written to prevent.

WHICH ANSWER, AND WHY IT IS THE HOUSE'S AND NOT A THIRD ONE
===========================================================
Two rules in this repo already fix it, at the two levels each applies to:

  * `gate_discloses_denominator_check` — "a PASS must say how much it looked
    at ... A gate may say PASS over zero items as long as a reader can SEE that
    it was zero: a count, or an explicit 'no corpus' / 'nothing to check' /
    SKIP." It explicitly does NOT require a FAIL on an empty tree. So the
    PER-UNIT zero is disclosed as `[SKIP]` with its count and kept out of both
    the numerator and the denominator.
  * `gate_zero_denominator_refuses_check` — "the gate states it read NOTHING and
    still exits 0 ... Either make it refuse (rc 2 is the disclosed-skip
    convention)". So when the WHOLE RUN examined nothing, it refuses with rc 2 —
    the pre-#952 behaviour, restored at the level where it went missing.

TWO-ARM CONTROL
===============
Every `test_bug_*` here FAILS against origin/main's program and PASSES against
the fixed one. Every `test_guard_*` passes in BOTH arms — they are the paired
guard, so the fix cannot be bought by making the gate refuse more often. A gate
that only ever says no is a ban, not a check.

Deliberately NOT pinned here: the live `benchmark-data/` numbers. A count-based
baseline over the real corpus is host-dependent (that is one of the four defects
named in `gate_discloses_denominator_check`'s own docstring: 46 cells in a
checkout vs 23 in a worktree), and it moves every time a cell is published. The
before/after measurement on the real corpus is in the commit message instead.

chip-AGNOSTIC: every name is synthetic (`ic_alpha`, `ic_empty`, `pdka`). No
design, PDK, foundry or process identifier appears.
"""

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

import benchmark_evidence_structure_check as besc  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

# --------------------------------------------------------------------------
# Fixtures. The allowed-entry vocabulary is READ OFF THE PROGRAM, never typed:
# the cell name is asserted against the program's own `_NAME_RE`, so a contract
# change breaks the fixture loudly instead of leaving it testing a rule the
# program no longer has.
# --------------------------------------------------------------------------

_CELL = "v1.2.3_pdka"


def _make_cell(cell: Path) -> None:
    """A cell complete enough that every PER-CELL rule passes, so anything these
    tests observe is attributable to the IC-level roll-up and nothing else."""
    assert besc._NAME_RE.match(cell.name), (
        f"fixture cell name {cell.name!r} is not what the program calls a cell")
    (cell / "phase1" / "generated_docs").mkdir(parents=True, exist_ok=True)
    (cell / "phase1" / "generated_docs" / "L1.json").write_text("{}", encoding="utf-8")
    (cell / "phase2" / "stage2").mkdir(parents=True, exist_ok=True)
    (cell / "phase2" / "stage2" / "stats.json").write_text("{}", encoding="utf-8")
    (cell / "reports" / "phase3").mkdir(parents=True, exist_ok=True)
    (cell / "reports" / "phase3" / "drc.rpt").write_text("clean\n", encoding="utf-8")
    gds = cell / "phase3" / "stage4" / "gds"
    gds.mkdir(parents=True, exist_ok=True)
    (gds / "GDS_MANIFEST.txt").write_text(
        "top.gds 1234B sha256:" + ("a" * 64) + "\n", encoding="utf-8")
    (cell / "RESULT.md").write_text("## VERDICT\nPASS\n", encoding="utf-8")


def _populated_ic(root: Path, name: str = "ic_alpha", strays=()) -> Path:
    ic = root / "ic" / name
    (ic / "input" / "docs").mkdir(parents=True, exist_ok=True)
    (ic / "input" / "docs" / "spec.md").write_text("spec\n", encoding="utf-8")
    _make_cell(ic / _CELL)
    for s in strays:
        d = ic / s
        d.mkdir(parents=True, exist_ok=True)
        (d / "out.json").write_text("{}", encoding="utf-8")
    return ic


def _empty_ic(root: Path, name: str) -> Path:
    ic = root / "ic" / name
    ic.mkdir(parents=True, exist_ok=True)
    return ic


@pytest.fixture()
def all_empty_tree(tmp_path):
    """The #967 shape verbatim: three IC directories, nothing inside any of them."""
    root = tmp_path / "benchmark-data"
    for n in ("ic_empty_a", "ic_empty_b", "ic_empty_c"):
        _empty_ic(root, n)
    return root


@pytest.fixture()
def mixed_tree(tmp_path):
    """One IC that really published, two that published nothing."""
    root = tmp_path / "benchmark-data"
    _populated_ic(root)
    _empty_ic(root, "ic_empty_a")
    _empty_ic(root, "ic_empty_b")
    return root


def _run(*args, cwd=None):
    out = _pr.run(
        [sys.executable, str(_PROGRAMS / "benchmark_evidence_structure_check.py"),
         *args],
        capture_output=True, text=True, cwd=str(cwd) if cwd else None)
    return out.returncode, out.stdout + out.stderr


def _git(repo: Path, *args):
    return _pr.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)


# --------------------------------------------------------------------------
# THE BUG ARM — these fail against origin/main.
# --------------------------------------------------------------------------

def test_bug_a_tree_of_empty_ic_dirs_is_refused_not_credited(all_empty_tree):
    """rc 2, and the roll-up must not read as 3-of-3 coverage.

    Against origin/main: rc 0 and `3/3 conformant, 0 nonconformant`."""
    rc, out = _run("--tree", str(all_empty_tree))
    assert rc == 2, (
        f"a tree that published nothing was not refused (rc={rc})\n{out}")
    roll = [ln for ln in out.splitlines()
            if ln.startswith("benchmark_evidence_structure_check:")]
    assert roll, out
    assert "3/3 conformant" not in roll[0], (
        f"an empty tree was credited with 3-of-3 coverage\n{roll[0]}")


def test_bug_the_refusal_says_what_it_found_instead_of_nothing(all_empty_tree):
    """The refusal DISCLOSES its zero rather than dying mute — the property
    `gate_discloses_denominator_check` enforces, applied to a refusal."""
    rc, out = _run("--tree", str(all_empty_tree))
    assert rc == 2, out
    assert "SKIP" in out, f"the zero-denominator units were not disclosed\n{out}"
    for ic in ("ic_empty_a", "ic_empty_b", "ic_empty_c"):
        assert ic in out, f"{ic} was not named in the disclosure\n{out}"


def test_bug_the_roll_up_denominator_is_what_was_examined(mixed_tree):
    """One real IC + one real cell = 2 examined units; the two empty IC dirs are
    in neither the numerator nor the denominator.

    Against origin/main this reads `4/4 conformant` — two of those four looked
    at nothing."""
    rc, out = _run("--tree", str(mixed_tree))
    assert rc == 0, out
    assert "2/2 conformant" in out, (
        f"the printed count is not the count examined\n{out}")
    assert "4/4" not in out, out
    assert "2 skipped" in out, f"the skipped units were not disclosed\n{out}"


def test_bug_check_ic_level_layout_renders_no_verdict_over_zero_entries(tmp_path):
    """The unit-level API says `skipped`, not `conforms=True`.

    Against origin/main this raises AttributeError: `FolderResult` has no
    `skipped` and no `examined`, because the zero case was indistinguishable
    from a clean one."""
    ic = _empty_ic(tmp_path / "benchmark-data", "ic_empty_a")
    res = besc.check_ic_level_layout(ic)
    assert res.skipped is True, res
    assert res.examined == 0, res
    assert res.conforms is not True, (
        "a unit that examined nothing was reported as conformant")


def test_bug_a_conforming_ic_root_states_the_count_it_judged(mixed_tree):
    """A PASS says how much it looked at, on its own line.

    Against origin/main the IC-level PASS prints `(IC=... IC-level layout)` with
    no denominator at all — indistinguishable from a PASS over zero entries,
    which is how the defect stayed invisible."""
    rc, out = _run("--tree", str(mixed_tree))
    assert rc == 0, out
    pass_lines = [ln for ln in out.splitlines()
                  if ln.startswith("[PASS]") and "ic_alpha" in ln
                  and "IC-level layout" in ln]
    assert pass_lines, out
    assert any("2 published entries" in ln for ln in pass_lines), (
        f"the IC-level PASS did not disclose its denominator\n{pass_lines}")


def test_bug_the_json_separates_examined_from_skipped(mixed_tree, tmp_path):
    """A machine consumer sees the same split — a disclosure only a human can
    read is not one CI can gate on."""
    out_json = tmp_path / "summary.json"
    rc, out = _run("--tree", str(mixed_tree), "--json", str(out_json))
    assert rc == 0, out
    data = json.loads(out_json.read_text(encoding="utf-8"))
    assert data["checked"] == 2, data
    assert data["conformant"] == 2, data
    assert data["skipped_examined_nothing"] == 2, data
    empties = [f for f in data["folders"] if f.get("skipped")]
    assert len(empties) == 2, data["folders"]
    assert all(f["conforms"] is not True for f in empties), empties


def test_bug_an_ic_holding_only_untracked_scratch_published_nothing(tmp_path):
    """Inside a repo, "published" means tracked. An IC whose only entry is a
    developer's local scratch directory published NOTHING, so it is a skip, not
    a pass — the same git-awareness `ic_level_strays` already applies when it
    declines to call that scratch a stray.

    Against origin/main it is a conformant unit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    ic = _empty_ic(repo / "benchmark-data", "ic_empty_a")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "empty")
    scratch = ic / "_scratch_local"
    scratch.mkdir()
    (scratch / "note.txt").write_text("local\n", encoding="utf-8")
    res = besc.check_ic_level_layout(ic)
    assert res.skipped is True, res
    assert res.examined == 0, res


# --------------------------------------------------------------------------
# THE PAIRED GUARD — behaviour that must NOT change. Every one of these passes
# in BOTH arms. Without them the fix could be bought by refusing more, and a
# gate that only ever says no is a ban, not a check.
# --------------------------------------------------------------------------

def test_guard_a_conforming_tree_still_passes(tmp_path):
    """input/ + one cell and nothing else: rc 0, no finding. The whole point of
    the change is that this stays a PASS while the empty tree stops being one."""
    root = tmp_path / "benchmark-data"
    _populated_ic(root)
    rc, out = _run("--tree", str(root))
    assert rc == 0, f"the conforming reference layout was failed\n{out}"
    assert "IC_LEVEL_LAYOUT:" not in out.replace("~ IC_LEVEL_LAYOUT", ""), out


def test_guard_an_ic_with_input_and_no_cell_is_still_a_real_unit(tmp_path):
    """`input/` IS published content: the layout rule opened it and allowed it.

    This is #564's own line — "an empty artefact is not a missing one" — and it
    is the boundary of the change: publishing shared input before the first cell
    lands must not be demoted to "examined nothing"."""
    root = tmp_path / "benchmark-data"
    ic = root / "ic" / "ic_alpha"
    (ic / "input" / "docs").mkdir(parents=True)
    (ic / "input" / "docs" / "spec.md").write_text("spec\n", encoding="utf-8")
    rc, out = _run("--tree", str(root))
    assert rc == 0, out
    assert "1/1 conformant" in out, out


def test_guard_stray_run_output_is_still_a_named_nonconformance(tmp_path):
    """#952's rule, untouched: every stray is counted and named, and the IC is
    FAILed. This is the behaviour the paired guard exists to protect — the fix
    must not have been bought by turning IC-level findings into skips."""
    root = tmp_path / "benchmark-data"
    _populated_ic(root, strays=("phase1", "phase3", "reports"))
    rc, out = _run("--tree", str(root))
    assert rc == 1, out
    assert "IC_LEVEL_LAYOUT" in out, out
    assert "3 entries at the IC level" in out, out
    for name in ("phase1/", "phase3/", "reports/"):
        assert name in out, f"{name!r} was not named as a stray\n{out}"


def test_guard_the_stray_set_itself_is_unchanged(tmp_path):
    """`ic_level_strays` still returns exactly the disallowed entries, and still
    excludes untracked scratch. The population/stray split reordered the
    git-tracked filter; this pins that the stray answer did not move."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    ic = _populated_ic(repo / "benchmark-data", strays=("phase1", "reports"))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "legacy")
    scratch = ic / "_scratch_local"
    scratch.mkdir()
    (scratch / "note.txt").write_text("local\n", encoding="utf-8")
    names = sorted(p.name for p in besc.ic_level_strays(ic))
    assert names == ["phase1", "reports"], names


def test_guard_changed_since_still_grandfathers_a_conforming_publish(tmp_path):
    """The CI shape `gatekeeper-land.sh` runs on every push. Untouched."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    _populated_ic(repo / "benchmark-data", strays=("phase1",))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "legacy")
    _make_cell(repo / "benchmark-data" / "ic" / "ic_alpha" / "v1.4.0_pdka")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "publish a conforming cell")
    rc, out = _run("--tree", str(repo / "benchmark-data"),
                   "--changed-since", "HEAD~1", cwd=repo)
    assert rc == 0, f"a conforming publish was failed by pre-existing strays\n{out}"


def test_guard_changed_since_still_catches_new_ic_level_output(tmp_path):
    """...and grandfathering is still not a blanket amnesty."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    _populated_ic(repo / "benchmark-data")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    new = repo / "benchmark-data" / "ic" / "ic_alpha" / "phase3"
    new.mkdir(parents=True)
    (new / "out.json").write_text("{}", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "dump run output at the IC level")
    rc, out = _run("--tree", str(repo / "benchmark-data"),
                   "--changed-since", "HEAD~1", cwd=repo)
    assert rc == 1, f"newly-added IC-level run output was not caught\n{out}"
    assert "IC_LEVEL_LAYOUT" in out and "phase3/" in out, out


def test_guard_no_argument_at_all_still_refuses(tmp_path):
    """The original rc-2 refusal for "you gave me nothing" is unchanged, message
    included — this fix restores a refusal, it must not have replaced one."""
    rc, out = _run(cwd=tmp_path)
    assert rc == 2, out
    assert "no evidence folders to check" in out, out


def test_guard_a_single_named_cell_is_still_validated_on_its_own(tmp_path):
    """Naming one cell asks about that cell. No IC-level unit, no skip, rc 0 —
    this is the shape `benchmark_evidence_publish._self_check` runs."""
    root = tmp_path / "benchmark-data"
    _populated_ic(root, strays=("phase1",))
    rc, out = _run(str(root / "ic" / "ic_alpha" / _CELL))
    assert rc == 0, out
    assert "IC_LEVEL_LAYOUT" not in out, out
    assert "1/1 conformant" in out, out
