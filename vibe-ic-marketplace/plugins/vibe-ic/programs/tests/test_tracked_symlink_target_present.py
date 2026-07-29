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
