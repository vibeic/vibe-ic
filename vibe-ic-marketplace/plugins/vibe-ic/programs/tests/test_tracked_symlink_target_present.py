#!/usr/bin/env python3
"""vibe-ic#555 — a committed pointer at a file that exists nowhere.

`gate_host_independence_check` reported the staleness gate as HOST_DEPENDENT:
225 records in a working checkout, 224 in a fresh worktree, same commit. The
record was a SYMLINK whose target is not tracked.

Counting properly changed the conclusion. I had framed it as a corpus-policy
question with three answers; the numbers settled it instead:

    tracked symlinks under benchmark-data     172
    …whose target is not tracked by git        43
    …unresolvable ON THE PUBLISHING BOX TOO    28

Twenty-eight are broken everywhere, seven of them `.json` a gate would read as a
published record. The corpus says a step produced an artefact and points at
nothing. That is a defect, not a choice — and `tracked_symlink_portability_check`
counted them on every run while deliberately not gating them, because its
subject is portability. This is the gate for the defect that one declines.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import tracked_symlink_target_present_check as T                # noqa: E402


def _repo(tmp_path):
    """A real git repo — the check reads git's index, so a fixture must too."""
    r = tmp_path / "repo"
    (r / "corpus" / "steps").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    subprocess.run(["git", "-C", str(r), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(r), "config", "user.name", "t"], check=True)
    return r


def _commit(r):
    subprocess.run(["git", "-C", str(r), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "x"], check=True)


def test_a_pointer_at_a_committed_file_is_fine(tmp_path):
    r = _repo(tmp_path)
    (r / "corpus" / "real.json").write_text("{}")
    os.symlink("../real.json", r / "corpus" / "steps" / "link.json")
    _commit(r)
    found = T.broken(r, ["corpus/steps/link.json"])
    assert found == [], "the target is tracked; there is nothing wrong here"


def test_a_pointer_at_nothing_is_broken_everywhere(tmp_path):
    """The defect: the corpus states an artefact exists and points at nothing."""
    r = _repo(tmp_path)
    os.symlink("../../nowhere.json", r / "corpus" / "steps" / "link.json")
    _commit(r)
    found = T.broken(r, ["corpus/steps/link.json"])
    assert len(found) == 1
    assert found[0]["kind"] == "BROKEN_EVERYWHERE"


def test_a_pointer_at_an_untracked_local_file_is_disclosed_not_failed(tmp_path):
    """THE HOST-DEPENDENCE ITSELF, and it must not fail the gate.

    The file DOES exist here; it is absent elsewhere because it was never
    committed. Failing on it would make the gate fail on a machine rather than
    on a commit, which is the shape #555 is about.
    """
    r = _repo(tmp_path)
    os.symlink("../local.json", r / "corpus" / "steps" / "link.json")
    _commit(r)                                    # link committed, target not
    (r / "corpus" / "local.json").write_text("{}")
    found = T.broken(r, ["corpus/steps/link.json"])
    assert len(found) == 1
    assert found[0]["kind"] == "UNTRACKED_TARGET_PRESENT_LOCALLY"


def test_a_missing_baseline_is_not_an_empty_one(tmp_path, capsys):
    """An unreadable register must refuse, not treat every debt as new-and-ok."""
    r = _repo(tmp_path)
    os.symlink("../../nowhere.json", r / "corpus" / "steps" / "link.json")
    _commit(r)
    bad = tmp_path / "unreadable.json"
    bad.write_text("{not json")
    rc = T.main(["--root", str(r), "--subdir", "corpus",
                 "--baseline", str(bad)])
    assert rc == T.RC_NOTHING
    assert "not an empty one" in capsys.readouterr().err


def test_an_empty_corpus_refuses_rather_than_passing(tmp_path, capsys):
    """No symlinks at all means the path is wrong or the corpus is absent."""
    r = _repo(tmp_path)
    (r / "corpus" / "f.txt").write_text("x")
    _commit(r)
    assert T.main(["--root", str(r), "--subdir", "corpus"]) == T.RC_NOTHING
    assert "not a pass" in capsys.readouterr().err


def test_a_recorded_entry_that_heals_must_fail(tmp_path, capsys):
    """The register MAY ONLY SHRINK. An entry that starts resolving and stays
    recorded is standing permission for a defect that no longer exists."""
    r = _repo(tmp_path)
    os.symlink("../real.json", r / "corpus" / "steps" / "link.json")
    _commit(r)
    (r / "corpus" / "real.json").write_text("{}")
    _commit(r)                                     # target now tracked too
    bl = tmp_path / "bl.json"
    bl.write_text(json.dumps({"known": ["corpus/steps/link.json"]}))
    rc = T.main(["--root", str(r), "--subdir", "corpus", "--baseline", str(bl)])
    assert rc == T.RC_FINDING
    assert "MAY ONLY SHRINK" in capsys.readouterr().err


def test_a_deliberately_ignored_target_is_not_debt(tmp_path):
    """The classification that nearly cost something real.

    `.gitignore:138` excludes `benchmark-data/ic/*/clean_run_*/` with its reason
    written beside it: a raw run directory can carry a commercial-PDK identifier
    IN ITS NAME, and tracking it is one `git add -A` from re-leaking what the
    2026-07-19/20 history rewrite removed.

    Measured on the real corpus: 31 of 44 flagged pointers resolve into that
    ignored tree. My first reading called them broken and my recommendation to
    the owner was to DELETE the pointers — which would have deleted the index
    into a deliberately-untracked corpus. A decision is not a defect.
    """
    r = _repo(tmp_path)
    (r / ".gitignore").write_text("corpus/raw_run/\n")
    (r / "corpus" / "raw_run").mkdir()
    os.symlink("../raw_run/out.json", r / "corpus" / "steps" / "link.json")
    _commit(r)
    found = T.broken(r, ["corpus/steps/link.json"])
    assert len(found) == 1
    assert found[0]["kind"] == "TARGET_DELIBERATELY_UNTRACKED", \
        "an ignored target is a decision the repo recorded, not debt"


def test_ignore_is_asked_of_git_not_reimplemented(tmp_path):
    """Negations, nested ignore files and precedence are git's rules.

    A second implementation of them would disagree with the first, which is the
    defect class this repo has spent the day removing. Exercised through a
    negation, the case a naive matcher gets wrong.
    """
    r = _repo(tmp_path)
    (r / ".gitignore").write_text("corpus/raw/\n!corpus/raw/keep.json\n")
    (r / "corpus" / "raw").mkdir()
    (r / "corpus" / "raw" / "keep.json").write_text("{}")
    os.symlink("../raw/keep.json", r / "corpus" / "steps" / "kept.json")
    _commit(r)

    # MY FIRST EXPECTATION HERE WAS WRONG, AND THAT IS THE POINT. I asserted
    # the negation put `keep.json` back in, so there would be no finding.
    # git disagrees: once a DIRECTORY is excluded, a negation for a path inside
    # it has no effect — `git check-ignore -v` names `corpus/raw/` as the
    # matching rule, and `git add -A` does not track the file. The program was
    # right and my model of the rules was not, which is exactly why the answer
    # is asked of git instead of reimplemented.
    found = T.broken(r, ["corpus/steps/kept.json"])
    assert len(found) == 1
    assert found[0]["kind"] == "TARGET_DELIBERATELY_UNTRACKED"
    assert T._is_ignored(r, "corpus/raw/keep.json") is True


# --- the exit code is what CI reads, and no test asserted it

def test_a_new_broken_pointer_produces_a_failing_exit_code(tmp_path, capsys):
    """Every test above asserts what `broken()` RETURNS. None asserted what
    `main()` EXITS with, and the hygiene suite reads only the exit code.

    Measured: replacing `return RC_FINDING` with `RC_OK` left all eight green.
    Eight tests over a gate that had stopped gating — the third instance of this
    shape in two days, each time in tests written to prevent it.
    """
    r = _repo(tmp_path)
    os.symlink("../../nowhere.json", r / "corpus" / "steps" / "link.json")
    _commit(r)
    bl = tmp_path / "empty.json"
    bl.write_text(json.dumps({"known": []}))
    assert T.main(["--root", str(r), "--subdir", "corpus",
                   "--baseline", str(bl)]) == T.RC_FINDING


def test_a_recorded_pointer_produces_a_passing_exit_code(tmp_path):
    """The other direction, or the test above is met by always failing."""
    r = _repo(tmp_path)
    os.symlink("../../nowhere.json", r / "corpus" / "steps" / "link.json")
    _commit(r)
    bl = tmp_path / "bl.json"
    bl.write_text(json.dumps({"known": ["corpus/steps/link.json"]}))
    assert T.main(["--root", str(r), "--subdir", "corpus",
                   "--baseline", str(bl)]) == T.RC_OK
