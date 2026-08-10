#!/usr/bin/env python3
"""vibe-ic#905 — the layout gate must SEE what sits at the IC level.

WHAT #905 REPORTED, AND WHAT IS ACTUALLY THE MATTER
    #905 records one IC directory carrying a gitignored-prefix run folder plus
    stray `phase1/` `phase3/` `reports/` at the IC level, and treats it as a
    cleanup blocked on a deletion decision.

    Measured on the published corpus before this rule existed, the deletion
    question was not the blocker and the count was not one:

        benchmark_evidence_structure_check.py --tree benchmark-data
        -> 4/19 conformant, 15 nonconformant, rc=1

    Every one of those 15 is a `clean_run_*` cell the gate ALREADY names. What
    it never named — because `_discover_evidence_folders` never returns them —
    was 48 stray directories at the IC level across 8 of 9 IC directories. The
    gate that owns the layout contract could not see the layout violation. That
    is the defect; the cleanup is a maintainer's decision downstream of it.

WHY THESE TESTS DRIVE THE SCRIPT
    Every assertion below runs `benchmark_evidence_structure_check.py` as a
    subprocess and reads its real stdout and exit code. A test that walked the
    fixture itself and re-derived "phase3/ is not a cell" would pass against
    the UNFIXED program, because it would never have asked the program
    anything.

    Fixtures are synthetic and chip-AGNOSTIC (generic IC/PDK tokens under
    tmp_path), so nothing here depends on benchmark-data.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "benchmark_evidence_structure_check.py"

_GOOD_MANIFEST = ("top.gds 1180456B sha256:"
                  + "2915355c69e0162887e4c3e3e60855a0710a8bccb0e02f1b08191989ef392c8f")
_RESULT_PASS = "# RESULT\n\n## VERDICT\n\n**PASS_WITH_WAIVERS.** re-derived.\n"


def _run(args, **kw):
    return subprocess.run([sys.executable, str(PROG)] + args,
                          capture_output=True, text=True, **kw)


def _make_conformant(base: Path, name: str = "v9.9.9_openpdkx") -> Path:
    d = base / name
    (d / "phase1" / "generated_docs").mkdir(parents=True)
    (d / "phase1" / "generated_docs" / "L1.json").write_text("{}")
    (d / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (d / "phase2" / "stage1" / "rtl" / "top.v").write_text("module top; endmodule\n")
    (d / "reports" / "phase3").mkdir(parents=True)
    (d / "reports" / "phase3" / "drc.json").write_text("{}")
    (d / "phase3" / "stage4" / "gds").mkdir(parents=True)
    (d / "phase3" / "stage4" / "gds" / "GDS_MANIFEST.txt").write_text(_GOOD_MANIFEST + "\n")
    (d / "RESULT.md").write_text(_RESULT_PASS)
    return d


def _ic_with_strays(tmp_path: Path) -> Path:
    """A conforming cell + shared input/, with run output beside them — the
    exact shape #905 describes."""
    root = tmp_path / "benchmark-data"
    ic = root / "ic" / "widgetmul"
    ic.mkdir(parents=True)
    _make_conformant(ic)
    (ic / "input" / "docs").mkdir(parents=True)
    (ic / "input" / "docs" / "L1.md").write_text("# spec\n")
    for stray in ("phase1", "phase3", "reports"):
        (ic / stray / "inner").mkdir(parents=True)
        (ic / stray / "inner" / "out.json").write_text("{}")
    return root


# --------------------------------------------------------------------------
# THE FAILING ARM: this is what the unfixed program cannot do.
# --------------------------------------------------------------------------

def test_ic_level_run_output_is_reported_by_name(tmp_path):
    """The program must NAME each stray directory and exit nonzero.

    Against the program as it stood before #905 this fails on the first
    assertion: the tree walk returns only the cell, so `phase1/` `phase3/`
    `reports/` never appear in the output at all and rc is 0.
    """
    root = _ic_with_strays(tmp_path)
    r = _run(["--tree", str(root)])
    assert "IC_LEVEL_LAYOUT" in r.stdout, (
        "the gate that owns the ic/<IC>/ layout contract said nothing about "
        "run output sitting at the IC level:\n" + r.stdout + r.stderr)
    for stray in ("phase1", "phase3", "reports"):
        assert f"'{stray}/'" in r.stdout, (
            f"{stray}/ at the IC level was not named:\n" + r.stdout)
    assert r.returncode == 1, r.stdout


def test_every_stray_is_a_separate_finding_in_the_json(tmp_path):
    """Findings are countable, not folded into one line — the count is what a
    blast-radius diff reads."""
    root = _ic_with_strays(tmp_path)
    out = tmp_path / "out.json"
    r = _run(["--tree", str(root), "--json", str(out)])
    assert r.returncode == 1
    data = json.loads(out.read_text())
    flagged = [f for f in data["folders"]
               if any(x.startswith("IC_LEVEL_LAYOUT") for x in f["failures"])]
    assert len(flagged) == 3, [f["path"] for f in flagged]
    assert {Path(f["path"]).name for f in flagged} == {"phase1", "phase3", "reports"}
    assert all(f["ic"] == "widgetmul" for f in flagged)


def test_the_report_does_not_prescribe_deletion(tmp_path):
    """#905 stalled on a deletion-doctrine decision. The gate must not make it.

    Retiring published evidence is a maintainer's call; a gate that told them
    to delete would be taking it, and 'we never ran this' and 'we ran it, it
    failed, and we kept the record' are not the same state.
    """
    root = _ic_with_strays(tmp_path)
    out = _run(["--tree", str(root)]).stdout.lower()
    for verb in ("delete", "remove it", "rm -rf", "purge"):
        assert verb not in out, f"the gate prescribed {verb!r}:\n{out}"


# --------------------------------------------------------------------------
# THE PAIRED GUARD: behaviour that must NOT change, so the rule above cannot
# be satisfied by making the gate louder about everything.
# --------------------------------------------------------------------------

def test_a_conforming_ic_still_reports_nothing(tmp_path):
    """input/ + v<ver>_<PDK>/ and nothing else — still a clean rc=0."""
    root = tmp_path / "benchmark-data"
    ic = root / "ic" / "widgetmul"
    ic.mkdir(parents=True)
    _make_conformant(ic)
    (ic / "input" / "docs").mkdir(parents=True)
    (ic / "input" / "docs" / "L1.md").write_text("# spec\n")
    r = _run(["--tree", str(root)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "IC_LEVEL_LAYOUT" not in r.stdout


def test_input_is_never_flagged(tmp_path):
    """The shared input/ is admitted by the contract and must stay admitted."""
    root = _ic_with_strays(tmp_path)
    out = _run(["--tree", str(root)]).stdout
    assert "'input/'" not in out, out


def test_a_misnamed_cell_is_reported_once_not_twice(tmp_path):
    """A `clean_run_*` folder is not `input/` and not `v<ver>_<PDK>/`, so a
    careless rule would report it a second time as an IC-level stray and bury
    the NAMING message that says what to do about it."""
    root = tmp_path / "benchmark-data"
    ic = root / "ic" / "widgetmul"
    ic.mkdir(parents=True)
    _make_conformant(ic, name="clean_run_v9.9.8_openpdky")
    r = _run(["--tree", str(root)])
    assert r.returncode == 1
    assert "NAMING" in r.stdout
    assert "IC_LEVEL_LAYOUT" not in r.stdout, r.stdout


def test_changed_since_grandfathers_a_preexisting_stray(tmp_path):
    """Landing this rule must not retroactively fail a PR that never touched
    the IC level. The CI shape is diff-scoped; a stray already committed at
    BASE is grandfathered exactly as a legacy cell is."""
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
           "HOME": str(repo)}

    def _git(*a):
        return subprocess.run(["git", "-C", str(repo)] + list(a),
                              capture_output=True, text=True, env=dict(env),
                              check=False)

    _git("init", "-q")
    _git("config", "user.email", "t@t")
    _git("config", "user.name", "t")
    ic = repo / "benchmark-data" / "ic" / "widgetmul"
    ic.mkdir(parents=True)
    _make_conformant(ic)
    (ic / "reports" / "inner").mkdir(parents=True)          # pre-existing stray
    (ic / "reports" / "inner" / "out.json").write_text("{}")
    _git("add", "-A")
    _git("commit", "-q", "-m", "base with a legacy IC-level stray")
    base = _git("rev-parse", "HEAD").stdout.strip()
    (repo / "README.md").write_text("hi\n")                 # unrelated commit
    _git("add", "-A")
    _git("commit", "-q", "-m", "unrelated")

    r = _run(["--tree", str(repo / "benchmark-data"), "--changed-since", base])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "IC_LEVEL_LAYOUT" not in r.stdout


def test_changed_since_flags_a_newly_added_stray(tmp_path):
    """The other direction of the same scoping: grandfathering must not become
    'never fires'. A stray this push ADDS is reported."""
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
           "HOME": str(repo)}

    def _git(*a):
        return subprocess.run(["git", "-C", str(repo)] + list(a),
                              capture_output=True, text=True, env=dict(env),
                              check=False)

    _git("init", "-q")
    _git("config", "user.email", "t@t")
    _git("config", "user.name", "t")
    ic = repo / "benchmark-data" / "ic" / "widgetmul"
    ic.mkdir(parents=True)
    _make_conformant(ic)
    _git("add", "-A")
    _git("commit", "-q", "-m", "base, conforming")
    base = _git("rev-parse", "HEAD").stdout.strip()
    (ic / "phase3" / "inner").mkdir(parents=True)           # NEW stray
    (ic / "phase3" / "inner" / "out.json").write_text("{}")
    _git("add", "-A")
    _git("commit", "-q", "-m", "leave run output at the IC level")

    r = _run(["--tree", str(repo / "benchmark-data"), "--changed-since", base])
    assert r.returncode == 1, r.stdout + r.stderr
    assert "IC_LEVEL_LAYOUT" in r.stdout and "'phase3/'" in r.stdout


def test_single_folder_mode_is_unchanged(tmp_path):
    """Passing one cell path still grades that cell and nothing else — the
    publish self-check calls the program this way."""
    d = _make_conformant(tmp_path)
    r = _run([str(d)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "IC_LEVEL_LAYOUT" not in r.stdout


def test_an_untracked_local_leftover_is_not_reported(tmp_path):
    """PUBLISHED MEANS TRACKED — a gate must not give two answers at one commit.

    A working checkout also holds whatever the last local run left behind. If
    the scan read the disk, this fixture would report a finding that a fresh
    clone of the same commit does not, and the gate's verdict would depend on
    who ran it. Committed evidence is still reported; the leftover is not.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
           "HOME": str(repo)}

    def _git(*a):
        return subprocess.run(["git", "-C", str(repo)] + list(a),
                              capture_output=True, text=True, env=dict(env),
                              check=False)

    _git("init", "-q")
    _git("config", "user.email", "t@t")
    _git("config", "user.name", "t")
    ic = repo / "benchmark-data" / "ic" / "widgetmul"
    ic.mkdir(parents=True)
    _make_conformant(ic)
    (ic / "reports" / "inner").mkdir(parents=True)       # COMMITTED stray
    (ic / "reports" / "inner" / "out.json").write_text("{}")
    _git("add", "-A")
    _git("commit", "-q", "-m", "published, with one IC-level stray")

    # what a local run leaves behind, never committed
    (ic / "phase3" / "inner").mkdir(parents=True)
    (ic / "phase3" / "inner" / "scratch.json").write_text("{}")

    r = _run(["--tree", str(repo / "benchmark-data")])
    assert "'reports/'" in r.stdout, r.stdout      # tracked -> reported
    assert "'phase3/'" not in r.stdout, (          # untracked -> not published
        "an untracked local leftover was reported, so this gate answers "
        "differently on a working checkout than on a fresh worktree at the "
        "same commit:\n" + r.stdout)
    assert r.returncode == 1
