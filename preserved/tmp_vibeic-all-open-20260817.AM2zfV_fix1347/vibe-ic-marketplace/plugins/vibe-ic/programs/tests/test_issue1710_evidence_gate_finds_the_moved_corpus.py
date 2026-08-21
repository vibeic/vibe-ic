#!/usr/bin/env python3
"""The evidence gate after the corpus moved to its own repository (#1710).

WHY THIS FILE EXISTS
====================
`benchmark_evidence_structure_check.py` is invoked as `--tree benchmark-data`, a
relative path. The published corpus now lives in `vibeic/benchmark-data`, so in
this repo that directory is gone and the gate returned:

    UNDETERMINED: --tree benchmark-data is not a directory, so this gate
    discovered nothing and scanned nothing.
    pre-push: BLOCKED

That verdict was CORRECT — a check that could not look has not passed — and it is
kept. What was wrong is where the gate looked, and that an absent corpus and a
broken pointer produced the same word.

`gatekeeper-land.sh` runs this gate; a red gate writes no stamp; without a stamp
`pre-push` refuses. So an absent corpus banned every push, and the only way to land
became bypassing the gate.

THE THREE OUTCOMES, WHICH MUST NOT COLLAPSE INTO TWO
====================================================
    pointer set + broken            -> UNDETERMINED (rc=2). Never excused, with or
                                       without --corpus-may-be-absent.
    nothing set + nothing local
      + the caller said so          -> NO_CORPUS (rc=0). Nothing scanned, and
                                       nothing CLAIMED to have been scanned.
    nothing set + nothing local
      + nobody said so              -> UNDETERMINED (rc=2). Unchanged.

The dangerous one is the middle row: an rc=0 for a scan that did not happen is the
false-certificate shape this repo keeps closing. It is safe only because it cannot
be reached while a pointer exists, it is opt-in at the call site, and it prints
NO_CORPUS rather than PASS.

EVERY CASE HERE IS PAIRED. A file that only proved "it stopped blocking" would pass
against a gate that had been deleted.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
from pathlib import Path
from unittest import mock

import pytest

import benchmark_evidence_structure_check as B

PROGRAMS = Path(__file__).resolve().parents[1]
ENV = "VIBE_IC_BENCHMARK_DATA"
HYGIENE = PROGRAMS.parents[3] / "tools" / "ci" / "repo_hygiene_gates.sh"


def _run(*args: str, env_tree: str | None = None, cwd: Path | None = None):
    env = dict(os.environ)
    env.pop(ENV, None)
    if env_tree is not None:
        env[ENV] = env_tree
    stdout = io.StringIO()
    stderr = io.StringIO()
    previous_cwd = Path.cwd()
    with mock.patch.dict(os.environ, env, clear=True), \
            contextlib.redirect_stdout(stdout), \
            contextlib.redirect_stderr(stderr):
        try:
            if cwd is not None:
                os.chdir(cwd)
            rc = B.main(list(args))
        finally:
            os.chdir(previous_cwd)
    return rc, stdout.getvalue() + stderr.getvalue()


@pytest.fixture()
def a_real_corpus(tmp_path: Path) -> Path:
    """A corpus shaped the way the discoverer actually keys on.

    Built from the naming rule the module documents (``v<semver>_<pdk>``) so the
    fixture exercises the real predicate rather than a stand-in for it.
    """
    root = tmp_path / "benchmark-data"
    cell = root / "ic" / "spm" / "v1.9.96_gf180mcuD"
    cell.mkdir(parents=True)
    (cell / "RESULT.md").write_text("# result\nverdict: PASS\n")
    return root


# ---------------------------------------------------------------------------
# 1. NOTHING ANYWHERE + the caller said so -> NO_CORPUS, rc 0, and it SAYS
#    nothing was scanned. This is the case that unblocks the removal.
# ---------------------------------------------------------------------------
def test_no_corpus_anywhere_with_the_flag_is_rc0_and_says_it_scanned_nothing(tmp_path):
    rc, out = _run("--tree", str(tmp_path / "gone"), "--corpus-may-be-absent")
    assert rc == 0, out
    assert "NO_CORPUS" in out, out
    assert "NOTHING WAS SCANNED" in out, "an rc=0 must not read as a scan that happened"
    assert "PASS" not in out.split("NO_CORPUS")[0][-40:], "must not be spelled as a pass"


# ---------------------------------------------------------------------------
# 2. …AND WITHOUT THE FLAG IT STILL BLOCKS. The half that makes case 1 mean
#    something: the relaxation is opt-in, not the new default.
# ---------------------------------------------------------------------------
def test_no_corpus_without_the_flag_is_still_undetermined(tmp_path):
    rc, out = _run("--tree", str(tmp_path / "gone"))
    assert rc == 2, f"the relaxation must be opt-in\n{out}"
    assert "UNDETERMINED" in out, out


# ---------------------------------------------------------------------------
# 3. A BROKEN POINTER IS NEVER EXCUSED — not even with the flag. "Somebody said
#    where the corpus is and was wrong" is a different event from "there is none".
# ---------------------------------------------------------------------------
def test_a_broken_pointer_is_undetermined_even_with_the_flag(tmp_path):
    rc, out = _run("--tree", "benchmark-data", "--corpus-may-be-absent",
                   env_tree=str(tmp_path / "nowhere"))
    assert rc == 2, f"a set-and-wrong pointer must never be waved through\n{out}"
    assert "UNDETERMINED" in out, out
    assert ENV in out, "the refusal must name the pointer it followed"
    assert "NO_CORPUS" not in out, "a broken pointer was laundered as an absent corpus"


# ---------------------------------------------------------------------------
# 4. THE POINTER IS FOLLOWED, AND ANNOUNCED. A gate that scans a different tree
#    than the one on its command line must say so — that silence is how
#    `--tree ../../../benchmark-data` reported 13/28 over a tree with 8 failing.
# ---------------------------------------------------------------------------
def test_the_pointer_overrides_the_relative_path_and_says_so(a_real_corpus):
    rc, out = _run("--tree", "benchmark-data", "--corpus-may-be-absent",
                   env_tree=str(a_real_corpus))
    assert f"{ENV} overrides --tree" in out, out
    assert str(a_real_corpus) in out, "the tree actually scanned must be named"
    assert "NO_CORPUS" not in out, "a present corpus was reported as absent"


# ---------------------------------------------------------------------------
# 5. A REAL CORPUS IS ACTUALLY EXAMINED — the flag must not switch the gate off
#    when there IS something to look at. Without this, cases 1-4 are compatible
#    with a gate that never scans anything.
# ---------------------------------------------------------------------------
def test_a_pointed_at_corpus_is_really_examined(a_real_corpus):
    rc, out = _run("--tree", "benchmark-data", "--corpus-may-be-absent",
                   env_tree=str(a_real_corpus))
    assert "NO_CORPUS" not in out and "UNDETERMINED" not in out, out
    # the cell name it was given must appear in what it reported on
    assert "v1.9.96_gf180mcuD" in out or "1 " in out, (
        f"the gate produced no evidence it looked at the corpus\n{out}")


# ---------------------------------------------------------------------------
# 6. AND IT CAN STILL FAIL. A gate that cannot fail is worthless, and this whole
#    change hands it an escape hatch — so the escape hatch must not reach the
#    case where there IS a corpus and the corpus is wrong.
# ---------------------------------------------------------------------------
def test_a_pointed_at_corpus_that_is_malformed_still_fails(tmp_path):
    root = tmp_path / "benchmark-data"
    # a directory the NAME rule rejects: the documented shape is v<semver>_<pdk>,
    # and the module explicitly lists `clean_run_` as a bad prefix.
    bad = root / "ic" / "spm" / "clean_run_whatever"
    bad.mkdir(parents=True)
    (bad / "RESULT.md").write_text("# result\n")
    rc, out = _run("--tree", "benchmark-data", "--corpus-may-be-absent",
                   env_tree=str(root))
    assert rc != 0, (
        f"a malformed published cell passed while the absent-corpus flag was set — "
        f"the flag reached a case it must never reach\n{out}")
    assert "NO_CORPUS" not in out, out


# ---------------------------------------------------------------------------
# 7. AN EMPTY-BUT-PRESENT TREE IS A DETERMINATION, NOT AN ABSENCE. The module's
#    own comment says so; the new branch must not have swallowed that case.
# ---------------------------------------------------------------------------
def test_an_empty_but_present_tree_is_not_no_corpus(tmp_path):
    root = tmp_path / "benchmark-data"
    root.mkdir()
    rc, out = _run("--tree", str(root), "--corpus-may-be-absent")
    assert "NO_CORPUS" not in out, (
        f"'I looked, there is nothing' was collapsed into 'there is nowhere to "
        f"look' — the same error in the other direction\n{out}")


# ---------------------------------------------------------------------------
# 8. THE SHIPPED CALL SITE CARRIES THE FLAG. Everything above tests the program;
#    this tests the only thing that ever invokes it in production. Without this,
#    the program could be perfect and the gate still blocked.
# ---------------------------------------------------------------------------
def test_the_landing_gate_actually_passes_the_flag():
    land = PROGRAMS.parents[3] / "tools" / "gatekeeper-land.sh"
    if not land.is_file():
        pytest.skip(f"{land} not present in this checkout")
    text = land.read_text()
    line = [ln for ln in text.splitlines()
            if "benchmark_evidence_structure_check.py" in ln and not ln.strip().startswith("#")]
    assert line, "the landing gate no longer invokes this program at all"
    assert all("--corpus-may-be-absent" in ln for ln in line), (
        f"the landing gate invokes the gate without the flag, so a repo with no "
        f"corpus is still blocked:\n" + "\n".join(line))


def _hygiene_list(tmp_path: Path, env_tree: str | None = None):
    summary = tmp_path / "hygiene-list.json"
    env = dict(os.environ)
    env.pop(ENV, None)
    if env_tree is not None:
        env[ENV] = env_tree
    proc = subprocess.run(
        ["bash", str(HYGIENE), "--list", "--summary-json", str(summary)],
        capture_output=True, text=True, env=env)
    assert summary.is_file(), proc.stdout + proc.stderr
    return proc, json.loads(summary.read_text())


def _init_corpus_repo(root: Path, *, routed_def: bool) -> Path:
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    cell = root / "ic" / "design" / "v1.10.55_test"
    cell.mkdir(parents=True)
    result = cell / "RESULT.md"
    result.write_text("# fixture published cell\n")
    subprocess.run(["git", "-C", str(root), "add", str(result)], check=True)
    if routed_def:
        path = cell / "phase3" / "stage3" / "pnr" / "routed.def"
        path.parent.mkdir(parents=True)
        path.write_text("VERSION 5.8 ;\nDESIGN fixture ;\nEND DESIGN\n")
        subprocess.run(["git", "-C", str(root), "add", str(path)], check=True)
    return root


def _precomputed(doc):
    return [gate for gate in doc["gates"]
            if gate.get("execution") == "PRECOMPUTED_CORPUS"]


def test_hygiene_no_config_is_named_and_dated_not_passed(tmp_path):
    proc, doc = _hygiene_list(tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    rows = _precomputed(doc)
    assert len(rows) == 1, rows
    assert rows[0]["state"] == "LISTED"
    assert rows[0]["reason_code"] == "NO_CORPUS"
    assert rows[0]["exempt_until"], rows[0]


def test_hygiene_broken_pointer_is_not_laundered_as_no_corpus(tmp_path):
    _, doc = _hygiene_list(tmp_path, str(tmp_path / "missing"))
    rows = _precomputed(doc)
    assert len(rows) == 1, rows
    assert rows[0]["reason_code"] == "PRODUCER_FAILED"
    assert rows[0]["exempt_until"] is None


def test_hygiene_present_but_empty_corpus_is_not_no_corpus(tmp_path):
    corpus = _init_corpus_repo(tmp_path / "corpus", routed_def=False)
    _, doc = _hygiene_list(tmp_path, str(corpus))
    rows = _precomputed(doc)
    assert len(rows) == 1, rows
    assert rows[0]["reason_code"] == "EMPTY_CORPUS"
    assert rows[0]["exempt_until"] is None


def test_hygiene_present_corpus_dispatches_real_cells(tmp_path):
    corpus = _init_corpus_repo(tmp_path / "corpus", routed_def=True)
    _, doc = _hygiene_list(tmp_path, str(corpus))
    assert _precomputed(doc) == []
    routed = [c for c in doc["corpora"]
              if c["name"] == "published cells carrying a routed DEF"]
    assert routed == [{"name": "published cells carrying a routed DEF",
                       "items": 1, "gates": 4, "expansion": "EXPANDED"}]


def test_hygiene_refuses_a_tracked_but_missing_routed_def(tmp_path):
    """The git index is not evidence that the checker can read the subject.

    A sparse checkout or dirty corpus may retain the routed-DEF path in
    ``git ls-files`` after its worktree bytes disappeared.  Treating that path
    as an item lets every per-cell checker decline and can make the configured
    corpus look measured.
    """
    corpus = _init_corpus_repo(tmp_path / "corpus", routed_def=True)
    routed_def = next(corpus.glob("ic/*/*/phase3/stage3/pnr/routed.def"))
    routed_def.unlink()
    _, doc = _hygiene_list(tmp_path, str(corpus))
    rows = _precomputed(doc)
    assert len(rows) == 1, rows
    assert rows[0]["reason_code"] == "PRODUCER_FAILED"
    assert rows[0]["exempt_until"] is None
    corpus_row = next(c for c in doc["corpora"]
                      if c["name"] == "published cells carrying a routed DEF")
    assert corpus_row["items"] == 0
    assert corpus_row["expansion"] == "PRODUCER_FAILED"
