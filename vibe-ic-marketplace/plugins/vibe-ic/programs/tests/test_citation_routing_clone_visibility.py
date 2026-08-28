"""CITATION_ROUTING said RESOLVES for files `git add` never carried.

MEASURED on the two published cells this landing repairs, at origin/main:

    45 rows claimed RESOLVES
    45 of them cite a path no clone receives

Every one is a `*.log` that WAS sitting in the staged directory when
`collect_citation_records` ran, and that the repo-root `*.log` ignore rule then
dropped at `git add`. So the record was not stale — it was false at the moment
it was written, because the publisher asked THIS MACHINE'S DISK a question only
git can answer.

The same program already knew better one function over: `_prune_provenance`
asks `git check-ignore` for exactly this reason and names
`phase2/stage2/synth/synth.log` in its docstring. One publish, two definitions
of "the reader receives this"; the citation record held the wrong one.

AND THE OTHER HALF: "NOT CARRIED" IS NOT YET A REASON
-----------------------------------------------------
Saying a citation does not resolve is half a decision; the record must also say
WHY, and the two reasons are not interchangeable to the program that reads it.
`evidence_citation_resolves_check` honours `OUT_OF_PUBLISHED_SCOPE` — that word
RETIRES its finding — and deliberately does not honour `DANGLING*`.

What used to decide it was the string prefix `phase{1,2,3}/stage`. MEASURED on
the same two cells, that prefix is TRUE of `phase3/stage3/pnr/` (0 files
shipped) and FALSE of `phase2/stage2/synth/` (10) and `phase2/stage2/dft/tdf/`
(5). Logs sitting in the carried directories were therefore recorded as "the
publisher's layout excludes them" while the layout demonstrably carries their
neighbours — retiring four findings that back PUBLISHED verdicts and repairing
nothing. The cell is now asked whether it carries anything at that location.

These tests assert on the DECISION VALUES the collector returns for a tree
built here — never on the text of the program — and they pin BOTH directions:
a dropped log is a hole, and a location the layout really does exclude keeps
the word that says so.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _PROGRAMS / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    try:
        spec.loader.exec_module(m)
    except SystemExit:
        pass
    return m


B = _load("benchmark_evidence_publish")

# A cited log and a cited JSON, both under a subtree the publisher DOES stage.
_LOG = "phase2/stage2/synth/synth.log"
_JSON = "phase2/stage2/synth/stats.json"
# A citation into a location the cell carries NOTHING at — the shape
# OUT_OF_PUBLISHED_SCOPE was named for. Never written to disk in any variant.
_GONE = "phase3/stage3/sta/sta_mcorner.rpt"
# The citing document: a report that names them as its evidence. `log` and
# `report` are citation-shaped keys, so the collector finds them the same way
# the evidence gate does.
_DOC = "reports/gates/synth_gate.json"

# The decisions `evidence_citation_resolves_check` HONOURS — the words that
# make its finding go away. Named so a test can assert a decision is not one of
# them rather than restate a single spelling.
_SUPPRESSING = {"OUT_OF_PUBLISHED_SCOPE", "UNFOLLOWABLE_ABSOLUTE"}


def _git(cwd, *args):
    return _pr.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True)


def _cell(tmp_path, *, gitignore: str | None, force_add: bool = False,
          status: str = "PASS"):
    """A repo with one published cell whose report cites a log, a json and a
    path the cell does not carry at all.

    Returns the cell directory. The log and the json EXIST ON DISK in every
    variant — the only thing that changes between variants is whether git
    carries them, which is the whole question.
    """
    root = tmp_path / "repo"
    (root / "cell" / "phase2" / "stage2" / "synth").mkdir(parents=True)
    (root / "cell" / "reports" / "gates").mkdir(parents=True)
    if gitignore is not None:
        (root / ".gitignore").write_text(gitignore, encoding="utf-8")
    cell = root / "cell"
    (cell / _LOG).write_text("transcript\n", encoding="utf-8")
    (cell / _JSON).write_text(json.dumps({"cells": 12}), encoding="utf-8")
    (cell / _DOC).write_text(
        json.dumps({"status": status, "log": _LOG, "report": _JSON,
                    "timing": _GONE}),
        encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    if force_add:
        _git(root, "add", "-f", "cell/" + _LOG)
    _git(root, "commit", "-qm", "cell")
    return cell


def _decisions(cell):
    return {(r["doc"], r["cited"]): r["decision"]
            for r in B.collect_citation_records(cell)}


def test_ignored_log_is_a_hole_and_a_missing_subtree_is_not(tmp_path):
    """THE DEFECT, and the reason recorded for it — both directions at once.

    The log is on disk and `*.log` means no clone gets it, so it must not say
    RESOLVES. It must also not say OUT_OF_PUBLISHED_SCOPE: the json beside it
    ships, so the layout plainly carries `phase2/stage2/synth/`, and that word
    would retire the evidence gate's finding for a proof nobody can open.
    `phase3/stage3/sta/` ships nothing, and keeps the word."""
    d = _decisions(_cell(tmp_path, gitignore="*.log\n"))
    assert d[(_DOC, _LOG)] == "DANGLING_UNDER_PASS", d
    assert d[(_DOC, _LOG)] not in _SUPPRESSING, d
    assert d[(_DOC, _GONE)] == "OUT_OF_PUBLISHED_SCOPE", d
    # ... and the file beside it, which git DOES carry, still resolves. A fix
    # that disclosed everything would pass the asserts above and be useless.
    assert d[(_DOC, _JSON)] == "RESOLVES", d


def test_ignored_log_gone_from_disk_is_still_a_hole(tmp_path):
    """THE SHAPE THAT PRODUCED THE PUBLISHED ROWS.

    A record re-derived over an ALREADY PUBLISHED cell reads a clean checkout,
    where the dropped log is precisely the file that is not there. Disk
    presence cannot tell that case apart from a subtree the publisher never
    staged, and the prefix rule answered out-of-scope for both."""
    cell = _cell(tmp_path, gitignore="*.log\n")
    (cell / _LOG).unlink()
    d = _decisions(cell)
    assert d[(_DOC, _LOG)] == "DANGLING_UNDER_PASS", d
    assert d[(_DOC, _GONE)] == "OUT_OF_PUBLISHED_SCOPE", d


def test_a_hole_outside_a_pass_is_dangling_not_dangling_under_pass(tmp_path):
    """The PLAN/CLAIM split survives the correction: a citing document that
    asserts nothing gets the weaker word. Without this, a program that answered
    DANGLING_UNDER_PASS for every dropped log would pass the tests above."""
    d = _decisions(_cell(tmp_path, gitignore="*.log\n", status="SKIP"))
    assert d[(_DOC, _LOG)] == "DANGLING", d


def test_control_same_tree_without_the_ignore_rule(tmp_path):
    """CONTROL. Identical tree, no ignore rule: the log resolves.

    Without this, the first test is also passed by a program that decided
    'a .log never resolves', which would be a second wrong answer."""
    d = _decisions(_cell(tmp_path, gitignore=None))
    assert d[(_DOC, _LOG)] == "RESOLVES", d
    assert d[(_DOC, _JSON)] == "RESOLVES", d


def test_force_added_log_resolves_despite_the_ignore_rule(tmp_path):
    """A TRACKED path is carried even while a pattern matches it — which is
    how this repo ships the evidence logs it force-adds. Disclosing one would
    tell a reader they cannot reach a file they demonstrably have."""
    d = _decisions(_cell(tmp_path, gitignore="*.log\n", force_add=True))
    assert d[(_DOC, _LOG)] == "RESOLVES", d


def test_no_git_repository_falls_back_to_disk_presence(tmp_path):
    """FAIL-OPEN. With no repository to ask, a disk-present citation resolves —
    the behaviour that shipped before this. Failing the other way would invent
    a disclosure, and `evidence_citation_resolves_check` HONOURS disclosures,
    so an invented one suppresses a real finding.

    The layout question degrades the same way: with no repository there is no
    carried-directory set, so the prefix rule alone decides, exactly as it did
    before. An unreachable git can neither manufacture a hole nor silence one.
    """
    cell = _cell(tmp_path, gitignore="*.log\n")
    subprocess.run(["rm", "-rf", str(cell.parent / ".git")], check=True)
    d = _decisions(cell)
    assert d[(_DOC, _LOG)] == "RESOLVES", d
    assert d[(_DOC, _GONE)] == "OUT_OF_PUBLISHED_SCOPE", d
