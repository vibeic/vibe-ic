#!/usr/bin/env python3
"""vibe-ic#1538 — the IC-level record must not be a veto on the next person.

THE MEASURED DEFECT
===================
`test_matrix_d3_outputs_produced` ends every unevidenced verdict with one
instruction:

    Commit (or register in the manifest) a run tree that carries it and this
    cell answers live again.

`tools/gatekeeper-land.sh` runs, unconditionally and with no override:

    benchmark_evidence_structure_check.py --tree benchmark-data \
        --changed-since "$BASE"

Take the first half of that advice and the landing is refused. 8 of the 9 ICs
that carry run output were laid out before the `v<ver>_<PDK>` convention, so
their IC-level entries are ALREADY non-conformant, and `IC_LEVEL_LAYOUT`
reported the whole legacy set against whoever touched a file underneath one of
them next.

CONTROL, because "my change broke it" and "my change revealed it" look
identical: on origin/main, a commit that adds NOTHING — one comment line
appended to an already-tracked file under a pre-existing stray — produced the
byte-identical 15-entry finding as a commit that adds four files. Same names,
same order, same rc 1.

`_changed_ic_dirs` already scoped the diff to the stray entries themselves, and
that is what makes the gap precise rather than general: it exempts a push that
publishes BESIDE a stray, never one that touches a file UNDER one — and the
directory d3's remedy sends you to IS one.

WHAT THIS TEST PINS
===================
Under `--changed-since`, `IC_LEVEL_LAYOUT` fails on the entries THIS CHANGE
CREATED and RECORDS the rest. The register is read from git at the baseline rev,
so it cannot grow silently, shrinks in the same commit that migrates an entry,
and is never standing permission.

TWO-ARM CONTROL: every `test_bug_*` FAILS against origin/main's program (the
grandfathering does not exist there, so the legacy set is charged to the change)
and PASSES against the fixed one. Every `test_guard_*` must hold in BOTH arms —
they are what stops the fix from being bought by weakening the rule:

  * newly-ADDED IC-level output is still refused, including inside an IC that
    carries a large pre-existing set (no blanket amnesty per IC);
  * the full `--tree` audit shape, with no `--changed-since`, still fails every
    legacy entry — coverage is diff-scoped, never reduced;
  * an unreadable baseline grandfathers NOTHING.

chip-AGNOSTIC: every name here is synthetic (`ic_alpha`, `pdka`). No design,
PDK, foundry or process identifier appears.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

import benchmark_evidence_structure_check as besc  # noqa: E402

_TIMEOUT = 60  # every subprocess in this file is bounded well under the cap
_CHECK = _PROGRAMS / "benchmark_evidence_structure_check.py"


# --------------------------------------------------------------------------
# Fixture: a real git repo whose FIRST commit already carries IC-level strays,
# because "pre-existing" is a statement about history and cannot be modelled on
# a bare filesystem.
# --------------------------------------------------------------------------

def _git(repo: Path, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, timeout=_TIMEOUT)


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
    """`ic_alpha` carries input/, one conforming cell, and three legacy strays —
    one of them holding a nested file, which is where d3's remedy lands."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    ic = repo / "benchmark-data" / "ic" / "ic_alpha"
    (ic / "input" / "docs").mkdir(parents=True)
    (ic / "input" / "docs" / "spec.md").write_text("spec\n", encoding="utf-8")
    _make_cell(ic / "v1.2.3_pdka")
    for stray in ("phase1", "reports"):
        (ic / stray).mkdir(parents=True)
        (ic / stray / "out.json").write_text("{}", encoding="utf-8")
    pnr = ic / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / "run.tcl").write_text("# legacy run script\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "legacy layout, predating the cell convention")
    return repo


def _run(repo: Path, *args):
    out = subprocess.run([sys.executable, str(_CHECK), *args],
                         capture_output=True, text=True, timeout=_TIMEOUT,
                         cwd=str(repo))
    return out.returncode, out.stdout + out.stderr


def _scoped(repo: Path, *extra):
    return _run(repo, "--tree", str(repo / "benchmark-data"),
                "--changed-since", "HEAD~1", *extra)


def _commit(repo: Path, msg: str):
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", msg)


# --------------------------------------------------------------------------
# THE BUG ARM — these fail against origin/main.
# --------------------------------------------------------------------------

def test_bug_a_zero_added_file_change_under_a_legacy_entry_is_not_refused(legacy_repo):
    """The issue's own control: a commit that ADDS NOTHING.

    One comment line appended to an already-tracked file under a pre-existing
    IC-level entry. Against origin/main this exits 1 and names all three legacy
    entries — a veto earned by evidence the change did not create."""
    repo = legacy_repo
    tcl = repo / "benchmark-data" / "ic" / "ic_alpha" / "phase3" / "stage3" / "pnr" / "run.tcl"
    tcl.write_text(tcl.read_text(encoding="utf-8") + "# one comment\n", encoding="utf-8")
    _commit(repo, "append one comment to an already-tracked file")
    added = _git(repo, "diff", "--diff-filter=A", "--name-only", "HEAD~1", "HEAD")
    assert added.stdout.strip() == "", (
        f"the control must add NO file; it added: {added.stdout!r}")
    rc, out = _scoped(repo)
    assert rc == 0, f"a change that adds nothing was refused\n{out}"


def test_bug_committing_a_run_tree_under_a_legacy_entry_is_accepted(legacy_repo):
    """d3's printed remedy, taken literally, must be an action the gate accepts.

    A repository that prints "commit a run tree that carries it" and then
    refuses the commit has two halves that do not agree, which is what #1538
    is."""
    repo = legacy_repo
    pnr = repo / "benchmark-data" / "ic" / "ic_alpha" / "phase3" / "stage3" / "pnr"
    for name in ("floorplan", "placed", "post_cts", "post_hold"):
        (pnr / f"{name}.def").write_text("VERSION 5.8 ;\nEND DESIGN\n", encoding="utf-8")
    _commit(repo, "commit a run tree under the pre-existing entry")
    rc, out = _scoped(repo)
    assert rc == 0, f"the remedy the repository prints was refused\n{out}"


def test_bug_the_pre_existing_set_is_disclosed_not_swallowed(legacy_repo):
    """Grandfathered is not the same as forgotten.

    The escape must PRINT the entries it did not charge, on a run that PASSES —
    a silent escape is indistinguishable from a rule that was simply met, and
    a register nobody sees is exactly how one becomes standing permission."""
    repo = legacy_repo
    tcl = repo / "benchmark-data" / "ic" / "ic_alpha" / "phase3" / "stage3" / "pnr" / "run.tcl"
    tcl.write_text(tcl.read_text(encoding="utf-8") + "# one comment\n", encoding="utf-8")
    _commit(repo, "append one comment")
    rc, out = _scoped(repo)
    assert rc == 0, out
    assert "IC_LEVEL_LAYOUT" in out, f"the record was not printed at all\n{out}"
    for name in ("phase1/", "phase3/", "reports/"):
        assert name in out, f"{name!r} was not disclosed as pre-existing\n{out}"
    assert "0 added by this change" in out, out


def test_bug_the_json_summary_carries_the_pre_existing_register(legacy_repo, tmp_path):
    """A machine consumer can read the register too.

    It exists to be WATCHED FOR GROWTH, and a disclosure only a human can read
    can only be watched by a human."""
    repo = legacy_repo
    tcl = repo / "benchmark-data" / "ic" / "ic_alpha" / "phase3" / "stage3" / "pnr" / "run.tcl"
    tcl.write_text(tcl.read_text(encoding="utf-8") + "# one comment\n", encoding="utf-8")
    _commit(repo, "append one comment")
    out_json = tmp_path / "summary.json"
    rc, _ = _scoped(repo, "--json", str(out_json))
    assert rc == 0
    data = json.loads(out_json.read_text(encoding="utf-8"))
    roots = [f for f in data["folders"] if f.get("kind") == "ic-root"]
    assert len(roots) == 1, data["folders"]
    assert sorted(roots[0]["pre_existing"]) == ["phase1/", "phase3/", "reports/"], roots[0]
    assert roots[0]["failures"] == [], roots[0]


def test_bug_the_finding_names_only_what_the_change_added(legacy_repo):
    """When a change DOES add an entry, the FAILURE line is about that entry.

    Handing back the whole legacy set beside it is what made the message
    unreadable as a statement about the change — the reader could not tell
    which of the 15 names they had just created."""
    repo = legacy_repo
    new = repo / "benchmark-data" / "ic" / "ic_alpha" / "steps"
    new.mkdir(parents=True)
    (new / "out.json").write_text("{}", encoding="utf-8")
    _commit(repo, "dump new run output at the IC level")
    ic = repo / "benchmark-data" / "ic" / "ic_alpha"
    names, _ = besc.ic_level_entry_names_at("HEAD~1", ic)
    res = besc.check_ic_level_layout(ic, pre_existing_names=names)
    assert res.conforms is False, res
    assert len(res.failures) == 1, res.failures
    assert "steps/" in res.failures[0], res.failures
    for legacy in ("phase1/", "phase3/", "reports/"):
        assert legacy not in res.failures[0], res.failures
        assert legacy in res.pre_existing, res.pre_existing


def test_bug_an_unreadable_baseline_grandfathers_nothing(legacy_repo):
    """A register derived from a listing that FAILED is a licence, not a record.

    `ic_level_entry_names_at` returns None, and the caller must take the STRICT
    branch — the same direction #1254 took `--changed-since` itself when the
    change set could not be determined."""
    repo = legacy_repo
    ic = repo / "benchmark-data" / "ic" / "ic_alpha"
    names, why = besc.ic_level_entry_names_at("no-such-rev-deadbeef", ic)
    assert names is None, (names, why)
    res = besc.check_ic_level_layout(ic, pre_existing_names=set(),
                                     baseline_mode="unreadable")
    assert res.conforms is False, res
    assert res.pre_existing == [], res.pre_existing


# --------------------------------------------------------------------------
# THE PAIRED GUARDS — behaviour that must NOT change. A fix bought by
# weakening the rule breaks these, and every one of them holds in BOTH arms.
# --------------------------------------------------------------------------

def test_guard_a_newly_added_ic_level_entry_is_still_refused(legacy_repo):
    """The other direction, inside an IC that carries a LARGE legacy set.

    Per-IC amnesty would be the easy wrong fix: the IC already fails, so let it
    keep failing quietly. The scope is the ENTRY, not the IC."""
    repo = legacy_repo
    new = repo / "benchmark-data" / "ic" / "ic_alpha" / "steps"
    new.mkdir(parents=True)
    (new / "out.json").write_text("{}", encoding="utf-8")
    _commit(repo, "dump new run output at the IC level")
    rc, out = _scoped(repo)
    assert rc == 1, f"newly-added IC-level run output was not caught\n{out}"
    assert "IC_LEVEL_LAYOUT" in out and "steps/" in out, out


def test_guard_a_new_loose_file_at_the_ic_level_is_still_refused(legacy_repo):
    """Not only directories. A loose file that belongs inside a cell is the
    other half of the #905 shape and must stay refused."""
    repo = legacy_repo
    (repo / "benchmark-data" / "ic" / "ic_alpha" / "provenance.jsonl").write_text(
        "{}\n", encoding="utf-8")
    _commit(repo, "drop a loose file at the IC level")
    rc, out = _scoped(repo)
    assert rc == 1, out
    assert "provenance.jsonl" in out, out


def test_guard_a_brand_new_ic_published_with_strays_is_fully_refused(legacy_repo):
    """An IC directory that did not exist at the baseline has NO register.

    This is the case the escape would be worst in if it were scoped per IC
    rather than per entry: a whole messy IC arriving in one commit would carry
    its own amnesty. git returns an empty listing for a path absent at the
    baseline, so every entry in it is ADDED and every one is refused."""
    repo = legacy_repo
    ic = repo / "benchmark-data" / "ic" / "ic_beta"
    for stray in ("phase1", "phase3", "reports"):
        (ic / stray).mkdir(parents=True)
        (ic / stray / "out.json").write_text("{}", encoding="utf-8")
    _make_cell(ic / "v1.2.3_pdka")
    _commit(repo, "publish a brand-new IC with a legacy-shaped layout")
    rc, out = _scoped(repo)
    assert rc == 1, f"a brand-new messy IC was let through\n{out}"
    for name in ("phase1/", "phase3/", "reports/"):
        assert name in out, f"{name!r} was not refused on the new IC\n{out}"

def test_guard_the_full_audit_shape_still_fails_every_legacy_entry(legacy_repo):
    """No `--changed-since` = the AUDIT shape, and it is untouched.

    This is what keeps the change diff-SCOPING rather than coverage-REDUCING:
    the divergence is still measurable in full, on demand, at any time."""
    repo = legacy_repo
    rc, out = _run(repo, "--tree", str(repo / "benchmark-data"))
    assert rc == 1, f"the audit shape stopped reporting the legacy layout\n{out}"
    assert "IC_LEVEL_LAYOUT" in out, out
    for name in ("phase1/", "phase3/", "reports/"):
        assert name in out, f"{name!r} vanished from the audit\n{out}"
    assert "ADDED by this change" not in out, (
        "the audit shape must not talk about a change it was not given\n" + out)


def test_guard_a_conforming_ic_still_passes_with_no_register(tmp_path):
    """An IC with only input/ and a cell must PASS and disclose NO register.

    A check that printed a pre-existing set for a clean layout would be
    indistinguishable from one that prints it for everything."""
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
    _make_cell(ic / "v1.4.0_pdka")
    _commit(repo, "publish a second conforming cell")
    rc, out = _scoped(repo)
    assert rc == 0, out
    assert "pre-existing" not in out, out
    # And in the audit shape, where the IC-level unit IS reported (the scoped
    # shape drops an IC with no changed stray entirely, which is `_changed_ic_
    # dirs` working, not the register), the line is the unqualified one.
    rc, out = _run(repo, "--tree", str(repo / "benchmark-data"))
    assert rc == 0, out
    assert "all allowed" in out, out
    assert "pre-existing" not in out, out


def test_guard_the_default_call_is_unchanged(legacy_repo):
    """`check_ic_level_layout(ic)` with no register argument behaves exactly as
    before: every stray is a finding.

    Deliberately asserts on NOTHING the fix introduced except the default, so a
    future refactor that flips the default to lenient is caught here."""
    ic = legacy_repo / "benchmark-data" / "ic" / "ic_alpha"
    res = besc.check_ic_level_layout(ic)
    assert res.conforms is False, res
    assert len(res.failures) == 1 and "IC_LEVEL_LAYOUT" in res.failures[0], res.failures
    for name in ("phase1/", "phase3/", "reports/"):
        assert name in res.failures[0], res.failures
