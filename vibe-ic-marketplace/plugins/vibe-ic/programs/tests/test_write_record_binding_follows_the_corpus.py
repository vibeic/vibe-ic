"""The dimension-7 write-record binding must follow the corpus, or say it cannot.

THE DEFECT, MEASURED on origin/main 74ac9fa78 in the pinned container image
with ``VIBE_IC_BENCHMARK_DATA`` set at a readable corpus::

    RECORD roots: []
    observed:     0
    notes: ("no run root in this commit carries a tracked
             reports/write_ledger.json, so W2's producer oracle is the AST
             alone -- exactly as it was before this binding",)

The same probe against the corpus checkout, same commit, same host, finds both
pinned roots, loads both, and builds **318** observations. Nothing was wrong
with the records; ``matrix_d7_write_record.record_roots`` was asking the PLUGIN
checkout's ``HEAD``, and #1723 moved ``benchmark-data`` into its own repository.

WHY THAT IS A DEFECT AND NOT A DEGRADE. The published sentence — "no run root in
this commit carries a tracked record" — is true of the plugin commit and reads
as "nobody has published a record yet". The truth was "the records moved and
this function did not follow". A binding that goes inert while explaining its
silence in the vocabulary of a state it is not in is worse than one that fails:
it collects the credit for disclosure. It also loses findings. With the binding
restored, step 31's ``reports/phase3/lvs_verdict.json`` — written by
``phase3_one_shot_runner._lvs_verdict`` and read by ``magic_illegal_overlap_
check`` — surfaced immediately as a W2 completeness finding that had been
invisible.

WHAT THIS FILE ASSERTS THAT THE PIN DOES NOT.
``test_d7_the_write_record_population_is_named_root_by_root`` catches this only
while :data:`RECORD_BOUND_ROOTS` is non-empty: ``pin_complaints`` reports
"observed NOTHING at all" against a NAMED population. Move the pin to ``()`` —
the obvious thing to do when a binding stops finding anything — and the same
inertness becomes legal, quietly, in the one edit somebody makes when they are
trying to get the suite green. The first assertion below is pin-INDEPENDENT: if
a corpus is readable at all, the binding must resolve a repository and must
observe something.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import _published_corpus as _pc
from _published_corpus import needs_corpus
import matrix_d7_write_record as R


def _clear() -> None:
    R.record_roots.cache_clear()
    R._record_repo.cache_clear()
    R._index.cache_clear()
    R.tracked_at_head.cache_clear()


@pytest.fixture(autouse=True)
def _isolate():
    _clear()
    yield
    _clear()


@needs_corpus
def test_a_readable_corpus_is_resolved_and_observed():
    """PIN-INDEPENDENT. A readable corpus must not produce an inert binding."""
    repo, prefix, why = R._record_repo()
    assert repo is not None, (
        f"a corpus is readable at {_pc.corpus_root()} and the binding resolved "
        f"NO repository to ask. Reason published: {why!r}")
    assert why and why.strip(), "the binding published no reason at all"

    roots = R.record_roots()
    assert roots, (
        f"the binding resolved {repo} and found no run root carrying a tracked "
        f"{R.RECORD_REL} there. Either the corpus genuinely carries no record — "
        f"in which case say so from the corpus's own tree, not from the plugin "
        f"checkout's — or the population is being read from the wrong "
        f"repository again. Reason published: {why!r}")

    observed = R.observed_writes()
    assert observed, (
        f"{len(roots)} record root(s) resolved under {repo} and the observation "
        f"index is empty. A binding that loads records and promotes nothing is "
        f"indistinguishable from one that was never consulted — which is the "
        f"state this file exists to make loud.\n"
        f"  notes: {json.dumps(list(R.binding_notes()), indent=2)}")


@needs_corpus
def test_every_label_names_a_cell_the_way_the_campaign_spells_it():
    """Labels are `benchmark-data/...` in BOTH shapes, or the pin cannot hold.

    The pin, every published finding and every note name cells by that path. A
    clone of ``vibeic/benchmark-data`` tracks the same cells one level up under
    ``ic/``, so a binding that returned the clone's own spelling would rename
    every cell the day the corpus moved from an in-tree checkout to a clone.
    """
    for root in R.record_roots():
        assert root.label.startswith("benchmark-data/"), root.label
        assert (root.path / R.RECORD_REL).is_file(), (
            f"{root.label}: label resolved but {R.RECORD_REL} is not a file "
            f"under {root.path}")


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True,
                   capture_output=True, text=True)


def _synthetic_clone(tmp_path: Path) -> Path:
    """A minimal stand-in for a clone of ``vibeic/benchmark-data``.

    Cells live under ``ic/<design>/v<version>_<PDK>/`` — the shape
    ``_published_corpus._has_cells`` reads, quoted from ``PUBLISHING.md`` — and
    the clone's ROOT is the corpus, which is the layout this binding could not
    previously label.
    """
    clone = tmp_path / "benchmark-data-clone"
    cell = clone / "ic" / "synthetic" / "v0.0.1_testpdk"
    (cell / "reports").mkdir(parents=True)
    (cell / "reports" / "write_ledger.json").write_text(
        json.dumps({"schema": "unreadable-on-purpose"}), encoding="utf-8")
    _git(clone, "init", "-q")
    _git(clone, "config", "user.email", "t@t")
    _git(clone, "config", "user.name", "t")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-qm", "synthetic corpus")
    return clone


def test_a_clone_shaped_corpus_is_found_and_labelled(tmp_path, monkeypatch):
    """THE SHAPE THAT WAS BROKEN, built here rather than waited for.

    Needs no published corpus: a two-file git repository in the clone's layout
    is enough to decide whether the binding looks in the right repository and
    spells the label the way the pin does. The record itself is deliberately
    unreadable — this arm is about DISCOVERY, and ``_load`` refusing a bad
    schema by name is a different assertion in a different file.
    """
    clone = _synthetic_clone(tmp_path)
    monkeypatch.setenv(_pc.CORPUS_ENV, str(clone))
    monkeypatch.setattr(R._plugin_tree, "repo_root", lambda: None)
    _clear()

    repo, prefix, why = R._record_repo()
    assert repo is not None and repo.resolve() == clone.resolve(), (repo, why)
    assert prefix == "benchmark-data/", (prefix, why)
    labels = [r.label for r in R.record_roots()]
    assert labels == ["benchmark-data/ic/synthetic/v0.0.1_testpdk"], (labels, why)


def test_a_corpus_that_is_not_a_git_checkout_is_refused_by_name(tmp_path, monkeypatch):
    """THE OTHER DIRECTION: a loose directory has no HEAD to make a claim about.

    Following the pointer must not become "read whatever is on disk". #414/#416
    and #527 are the reason the population is a property of a COMMIT, and that
    property is what this change had to preserve while changing WHICH commit.
    """
    loose = tmp_path / "loose"
    (loose / "ic" / "synthetic" / "v0.0.1_testpdk" / "reports").mkdir(parents=True)
    (loose / "ic" / "synthetic" / "v0.0.1_testpdk" / "reports"
     / "write_ledger.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv(_pc.CORPUS_ENV, str(loose))
    monkeypatch.setattr(R._plugin_tree, "repo_root", lambda: None)
    _clear()

    repo, prefix, why = R._record_repo()
    assert repo is None, (repo, why)
    assert "not inside a git work tree" in why, why
    assert R.record_roots() == ()


def test_an_in_tree_checkout_still_answers_as_itself(tmp_path, monkeypatch):
    """The pre-#1723 shape is not broken by the new resolution.

    Every commit before the corpus moved carries the cells under
    ``benchmark-data/`` in the plugin repository itself, and must be answered
    from there with no prefix — otherwise this change would rewrite the history
    it was supposed to leave alone.
    """
    repo = tmp_path / "plugin"
    cell = repo / "benchmark-data" / "ic" / "synthetic" / "v0.0.1_testpdk"
    (cell / "reports").mkdir(parents=True)
    (cell / "reports" / "write_ledger.json").write_text("{}", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "in-tree corpus")

    monkeypatch.delenv(_pc.CORPUS_ENV, raising=False)
    monkeypatch.setattr(R._plugin_tree, "repo_root", lambda: repo)
    _clear()

    got, prefix, why = R._record_repo()
    assert got == repo and prefix == "", (got, prefix, why)
    assert "pre-#1723" in why, why
    assert [r.label for r in R.record_roots()] == [
        "benchmark-data/ic/synthetic/v0.0.1_testpdk"]
