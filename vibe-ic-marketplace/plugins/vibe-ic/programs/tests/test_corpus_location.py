#!/usr/bin/env python3
"""`_corpus_location` — the one place seven gates agree where the corpus is.

WHY THIS FILE EXISTS
====================
v1.10.62 gave seven gates a shared corpus resolver and shipped it untested, which
`plugin_full_audit` caught on the next run:

    D1 program-test-coverage: FAIL — untested non-synth programs: ['_corpus_location']

The rule is right and the omission was mine. It matters more than the average helper
because SEVEN gates now agree about where the corpus is by agreeing with this module:
a defect here is not one wrong verdict, it is seven wrong verdicts that agree with each
other, which reads exactly like consensus.

WHAT IS ACTUALLY AT RISK
========================
Every function here decides between outcomes that look alike and mean opposite things:

    a named tree that exists          vs  a pointer that overrides it
    a pointer that is set and broken  vs  no pointer at all
    "git says there are none"         vs  "git could not be asked"

The last pair is the one that has already cost this repo a false certificate: over a
corpus that was PRESENT but not a checkout, an empty `git ls-files` was read as
"no tracked symlinks" and the gate printed
`[PASS] every tracked symlink is relative` over a tree carrying an absolute one.

So each case below asserts BOTH directions. A test that only proved "it refuses when
there is nothing" would pass against a resolver that refuses everything.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROGRAMS = Path(__file__).resolve().parents[1]
MOD = PROGRAMS / "_corpus_location.py"


def _load():
    spec = importlib.util.spec_from_file_location("_cl_under_test", MOD)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod          # dataclasses need it registered
    spec.loader.exec_module(mod)
    return mod


L = _load()


@pytest.fixture(autouse=True)
def _no_inherited_pointer(monkeypatch):
    """Every case states its own pointer. Inheriting the operator's would make the
    whole file's result depend on who ran it."""
    monkeypatch.delenv(L.CORPUS_ENV, raising=False)
    monkeypatch.delenv(L.BOUND_SHA_ENV, raising=False)


def _git(repo: Path, *args: str):
    return _pr.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)


# ---------------------------------------------------------------------------
# env_pointer: empty string is ABSENT, not a path. `export VAR=` is how a shell
# unsets-without-unsetting, and reading "" as a location would send every gate to
# the filesystem root.
# ---------------------------------------------------------------------------
def test_env_pointer_reads_the_variable(monkeypatch):
    monkeypatch.setenv(L.CORPUS_ENV, "/somewhere")
    assert L.env_pointer() == "/somewhere"


def test_an_empty_pointer_is_absent_not_the_root(monkeypatch):
    monkeypatch.setenv(L.CORPUS_ENV, "")
    assert L.env_pointer() is None, (
        "an empty pointer was read as a location; every gate would then scan "
        "whatever `Path('')` resolves to")


def test_no_pointer_is_none():
    assert L.env_pointer() is None


# ---------------------------------------------------------------------------
# resolve: the named tree WINS when it exists, and declining the pointer is
# announced — a reader with it set must be able to tell which tree was scanned.
# ---------------------------------------------------------------------------
def test_a_named_tree_that_exists_wins_over_the_pointer(tmp_path, monkeypatch, capsys):
    named = tmp_path / "benchmark-data"
    named.mkdir()
    monkeypatch.setenv(L.CORPUS_ENV, str(tmp_path / "elsewhere"))
    got, origin = L.resolve(named, gate="g", announce=True)
    assert (got, origin) == (named, L.NAMED)
    err = capsys.readouterr().err
    assert "NOT followed" in err, (
        f"the pointer was declined in silence; a reader who set it has no way to "
        f"know which tree produced the verdict\n{err}")


def test_the_pointer_takes_over_when_the_named_tree_is_absent(tmp_path, monkeypatch, capsys):
    named = tmp_path / "gone"
    clone = tmp_path / "clone"
    clone.mkdir()
    monkeypatch.setenv(L.CORPUS_ENV, str(clone))
    got, origin = L.resolve(named, gate="g", announce=True)
    assert (got, origin) == (clone, L.ENV)
    assert "overrides" in capsys.readouterr().err, "the override was not announced"


def test_subdir_is_dropped_because_the_clone_carries_it_at_the_top(tmp_path, monkeypatch):
    """CI names `<repo>/benchmark-data/ic`; the clone has `ic/` at its root."""
    clone = tmp_path / "clone"
    clone.mkdir()
    monkeypatch.setenv(L.CORPUS_ENV, str(clone))
    got, origin = L.resolve(tmp_path / "gone" / "ic", subdir="ic")
    assert (got, origin) == (clone / "ic", L.ENV)
    got, origin = L.resolve(tmp_path / "gone", subdir=None)
    assert (got, origin) == (clone, L.ENV)


def test_nothing_anywhere_returns_the_named_path_and_says_it_was_named(tmp_path):
    """The path is returned WHETHER OR NOT IT EXISTS — deciding what an absent one
    means belongs to `refuse`, and it differs by origin."""
    named = tmp_path / "gone"
    got, origin = L.resolve(named)
    assert (got, origin) == (named, L.NAMED)


def test_bound_snapshot_forces_external_pointer_over_named_tree(
        tmp_path, monkeypatch):
    named = tmp_path / "candidate" / "benchmark-data" / "ic"
    named.mkdir(parents=True)
    external = tmp_path / "attested" / "ic"
    external.mkdir(parents=True)
    monkeypatch.setenv(L.CORPUS_ENV, str(external.parent))
    monkeypatch.setenv(L.BOUND_SHA_ENV, "a" * 40)

    got, origin = L.resolve(named, subdir="ic")

    assert (got, origin) == (external, L.ENV), (
        "a candidate-local corpus shadowed the externally byte-attested "
        "landing population")


def test_bound_sha_without_pointer_is_unscannable_and_refuses(
        tmp_path, monkeypatch, capsys):
    named = tmp_path / "candidate" / "benchmark-data" / "ic"
    named.mkdir(parents=True)
    monkeypatch.setenv(L.BOUND_SHA_ENV, "a" * 40)

    got, origin = L.resolve(named, subdir="ic", gate="g", announce=True)

    assert origin == L.REFUSED
    assert not got.is_dir(), (
        "a partial bound environment resolved to a scannable path")
    rc = L.refuse("g", named, got, origin, may_be_absent=True,
                  scanned="published cell(s)")
    msg = capsys.readouterr().err
    assert rc == 2
    assert "nothing was scanned" in msg
    assert str(named) not in str(got), (
        "the refusal sentinel is candidate-controlled")


# ---------------------------------------------------------------------------
# not_a_checkout_reason: THE ONE THAT ALREADY COST A FALSE CERTIFICATE.
# Both directions, plus the arm that `git init` alone would have defeated.
# ---------------------------------------------------------------------------
def test_a_real_checkout_is_accepted(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "a.txt").write_text("x\n")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "x")
    assert L.not_a_checkout_reason(repo, "the index") is None


def test_a_loose_directory_is_refused_with_a_reason(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "a.txt").write_text("x\n")
    why = L.not_a_checkout_reason(plain, "the index")
    assert why, (
        "a directory that is not a checkout was accepted; a gate reading git's "
        "index would then enumerate zero of everything and call it clean")
    assert "the index" in why, f"the reason does not say what could not be read: {why!r}"


def test_an_empty_checkout_is_still_a_checkout_here(tmp_path):
    """AND THE TRACKS-NOTHING REFUSAL IS NOT THIS FUNCTION'S JOB.

    I first asserted the opposite — that `git init` with nothing committed should be
    refused here — and the module was right and the test was wrong. This function
    answers exactly one question, "is this a git checkout", and an initialised
    repository IS one. Making it also mean "and it has content" would give one
    sentence two jobs and leave a caller unable to tell which failed.

    The tracks-nothing arm is REAL and is enforced one layer up: the gates read
    `published_paths()`, which returns None for BOTH "git could not answer" and "the
    index is empty", and each gate refuses on None rather than falling back to a disk
    walk. Without that, `git init` alone would defeat the not-a-checkout refusal.
    It is verified where it lives — see
    test_issue1710_corpus_reading_gates_find_the_moved_corpus.py — not here.
    """
    repo = tmp_path / "empty"
    repo.mkdir()
    _git(repo, "init", "-q")
    assert L.not_a_checkout_reason(repo, "the index") is None, (
        "this function grew a second job; a caller can no longer tell 'not a "
        "checkout' from 'a checkout with nothing in it'")


# ---------------------------------------------------------------------------
# refuse: the four outcomes must stay four. Collapsing any two is the defect.
# ---------------------------------------------------------------------------
def _refuse(capsys, named, resolved, origin, may_be_absent):
    """`refuse` PRINTS the reason and RETURNS the rc, so the message is read off
    stderr. Asserting on a returned string would have tested a shape this function
    does not have."""
    rc = L.refuse("g", Path(named), Path(resolved), origin,
                  may_be_absent=may_be_absent, scanned="published cell(s)")
    return rc, capsys.readouterr().err


def test_a_broken_pointer_is_undetermined_even_with_the_opt_in(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv(L.CORPUS_ENV, str(tmp_path / "nope"))
    rc, msg = _refuse(capsys, tmp_path / "named", tmp_path / "nope", L.ENV,
                      may_be_absent=True)
    assert rc == 2, f"a set-and-wrong pointer was excused: rc={rc} {msg!r}"
    assert "NO_CORPUS" not in (msg or ""), "a broken pointer was laundered as absent"


def test_nothing_anywhere_with_the_opt_in_is_no_corpus_and_claims_nothing(tmp_path, capsys):
    rc, msg = _refuse(capsys, tmp_path / "named", tmp_path / "named", L.NAMED,
                      may_be_absent=True)
    assert rc == 0, f"rc={rc} {msg!r}"
    assert "NO_CORPUS" in (msg or ""), msg
    assert "PASS" not in (msg or ""), "an unscanned tree was reported as a pass"


def test_nothing_anywhere_without_the_opt_in_still_refuses(tmp_path, capsys):
    rc, _ = _refuse(capsys, tmp_path / "named", tmp_path / "named", L.NAMED,
                    may_be_absent=False)
    assert rc == 2, "the relaxation is opt-in; it fired without anybody opting in"


# ---------------------------------------------------------------------------
# population_key: the corpus a verdict was measured over must be identifiable, or
# a record from one corpus can be compared against a run over another.
# ---------------------------------------------------------------------------
def test_the_population_key_distinguishes_two_corpora(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(); b.mkdir()
    assert L.population_key(a, L.ENV) != L.population_key(b, L.ENV), (
        "two different corpora share a population key, so a record measured over "
        "one would be accepted as describing the other")


def test_the_population_key_is_stable_for_one_corpus(tmp_path):
    a = tmp_path / "a"
    a.mkdir()
    assert L.population_key(a, L.ENV) == L.population_key(a, L.ENV)
