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

These tests assert on the DECISION VALUES the collector returns for a tree
built here — never on the text of the program.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys

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
# The citing document: a report that names both as its evidence. `log` and
# `report` are citation-shaped keys, so the collector finds them the same way
# the evidence gate does.
_DOC = "reports/gates/synth_gate.json"


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, timeout=60)


def _cell(tmp_path, *, gitignore: str | None, force_add: bool = False):
    """A repo with one published cell whose report cites a log and a json.

    Returns the cell directory. Both cited files EXIST ON DISK in every
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
        json.dumps({"status": "PASS", "log": _LOG, "report": _JSON}),
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


def test_ignored_log_is_disclosed_not_resolved(tmp_path):
    """THE DEFECT. The log is on disk and `*.log` means no clone gets it."""
    d = _decisions(_cell(tmp_path, gitignore="*.log\n"))
    assert d[(_DOC, _LOG)] == "OUT_OF_PUBLISHED_SCOPE", d
    # ... and the file beside it, which git DOES carry, still resolves. A fix
    # that disclosed everything would pass the first assert and be useless.
    assert d[(_DOC, _JSON)] == "RESOLVES", d


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
    so an invented one suppresses a real finding."""
    cell = _cell(tmp_path, gitignore="*.log\n")
    subprocess.run(["rm", "-rf", str(cell.parent / ".git")], check=True)
    d = _decisions(cell)
    assert d[(_DOC, _LOG)] == "RESOLVES", d


def test_a_cited_path_absent_from_disk_is_still_disclosed(tmp_path):
    """Unchanged behaviour, pinned: 'not on disk at all' was already handled
    and must not start reporting as something else."""
    cell = _cell(tmp_path, gitignore=None)
    (cell / _LOG).unlink()
    d = _decisions(cell)
    assert d[(_DOC, _LOG)] == "OUT_OF_PUBLISHED_SCOPE", d
