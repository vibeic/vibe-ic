"""The PREPARE half must carry the MANIFEST ALONE, even from a staged edit.

WHY THIS FILE EXISTS.  `protected_landing_prepare.sh` restores each protected
path before it commits the manifest, so that `current` is a state the
repository actually had and the bytes arrive in the ACTIVATE half.  It restored
with `git checkout -- <path>`, which takes the INDEX copy -- so an operator who
had already `git add`ed the edit got a PREPARE that CARRIED THE FUTURE BYTES,
silently, and an ACTIVATE with nothing left to install.

MEASURED while authoring `protected-path-may-be-renamed-v1` on `cd0a98dd8`,
with the edit staged:

    landing(PREPARE): ... -- 1 protected path(s) move
     tools/ci/protected_landing_transition.json |   2 +-
     tools/ci/protected_landing_transition.py   | 301 +++++++++++++++++++--

The second line is the defect.  The split between the two halves IS the check --
it is what caught five paths that had drifted onto main with no transition
opened for them -- and a PREPARE holding the future bytes describes a tree
nobody ever ran.

THE SUBJECT IS THE SCRIPT, NOT THE REGISTER, so the fixture is a synthetic repo
with a stub author: this pins the restore semantics and nothing else, and it
runs in well under a second rather than checking out 150 MB to say one thing.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_SCRIPT = _HERE / "protected_landing_prepare.sh"
_MANIFEST = "tools/ci/protected_landing_transition.json"
_SUBJECT = "tools/ci/a_protected_file.py"

#: The refusing stub: an author that exits non-zero, which is what the real one
#: does when it cannot render.  The edits must survive it.
_REFUSING_AUTHOR = """#!/usr/bin/env python3
import sys
print("  REFUSE  probe", file=sys.stderr)
raise SystemExit(2)
"""

#: A stub standing in for the real author.  The script's contract with it is
#: exactly `--out <manifest>`; what it renders is not what this file is about,
#: and calling the real one would drag the whole derived path set in.
_STUB_AUTHOR = '''#!/usr/bin/env python3
import argparse, json, pathlib, sys
p = argparse.ArgumentParser()
for flag in ("--repo", "--commit", "--transition-id", "--current-id",
             "--next-id"):
    p.add_argument(flag)
p.add_argument("--next-file", action="append", default=[])
p.add_argument("--no-move", action="store_true")
p.add_argument("--out", type=pathlib.Path, required=True)
a = p.parse_args()
a.out.write_text(json.dumps({"stub": True, "next_file": a.next_file}) + "\\n")
'''


def _git(repo: Path, *args: str) -> str:
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example")
    proc = subprocess.run(["git", "-C", str(repo), *args], env=env,
                          stdin=subprocess.DEVNULL, capture_output=True,
                          text=True, check=False)
    assert proc.returncode == 0, f"git {args}: {proc.stderr}"
    return proc.stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "subject"
    (root / "tools" / "ci").mkdir(parents=True)
    _git(root.parent, "init", "-q", "-b", "main", str(root))
    (root / _SUBJECT).write_text("ORIGINAL\n")
    (root / _MANIFEST).write_text(
        json.dumps({"paths": [{"path": _SUBJECT, "roles": ["runtime"]}]}) + "\n")
    author = root / "tools" / "ci" / "protected_landing_manifest_author.py"
    author.write_text(_STUB_AUTHOR)
    (root / "tools" / "ci" / "protected_landing_prepare.sh").write_bytes(
        _SCRIPT.read_bytes())
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    return root


def _prepare(repo: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example")
    return subprocess.run(
        ["bash", "tools/ci/protected_landing_prepare.sh", "probe-v1"],
        cwd=str(repo), env=env, stdin=subprocess.DEVNULL,
        capture_output=True, text=True, check=False)


def test_a_staged_edit_does_not_ride_into_the_prepare_commit(repo: Path):
    """THE DEFECT.  Fails against the `git checkout -- <path>` form."""
    (repo / _SUBJECT).write_text("EDITED\n")
    _git(repo, "add", _SUBJECT)
    result = _prepare(repo)
    assert result.returncode == 0, result.stderr
    touched = _git(repo, "show", "--name-only", "--format=", "HEAD").split()
    assert touched == [_MANIFEST], (
        "the PREPARE half carried more than the manifest: " + repr(touched))


def test_an_unstaged_edit_behaves_exactly_as_it_always_did(repo: Path):
    """The NEGATIVE CONTROL: the path this change does not touch."""
    (repo / _SUBJECT).write_text("EDITED\n")
    result = _prepare(repo)
    assert result.returncode == 0, result.stderr
    touched = _git(repo, "show", "--name-only", "--format=", "HEAD").split()
    assert touched == [_MANIFEST]


def test_the_future_bytes_survive_for_the_activate_half(repo: Path):
    """The bytes are restored to the working tree after the PREPARE, because
    the ACTIVATE half is what installs them."""
    (repo / _SUBJECT).write_text("EDITED\n")
    _git(repo, "add", _SUBJECT)
    assert _prepare(repo).returncode == 0
    assert (repo / _SUBJECT).read_text() == "EDITED\n"
    manifest = json.loads((repo / _MANIFEST).read_text())
    assert manifest["next_file"] and _SUBJECT in manifest["next_file"][0]


def test_the_index_is_not_left_holding_the_future_bytes(repo: Path):
    """A restore that only fixed the working tree would leave the edit STAGED,
    so the very next `git commit` would carry it under whatever message the
    operator was writing."""
    (repo / _SUBJECT).write_text("EDITED\n")
    _git(repo, "add", _SUBJECT)
    assert _prepare(repo).returncode == 0
    staged = _git(repo, "diff", "--cached", "--name-only").split()
    assert staged == []


def test_a_refusing_author_does_not_eat_the_edits(repo: Path):
    """MEASURED: the author refused, the script exited, the EXIT trap removed
    the staging directory, and a 301-line edit to a protected file was gone
    with no message about it.  The staging directory is the ONLY copy of the
    operator's work between the restore and the ACTIVATE half."""
    (repo / "tools" / "ci" / "protected_landing_manifest_author.py").write_text(
        _REFUSING_AUTHOR)
    (repo / _SUBJECT).write_text("EDITED\n")
    result = _prepare(repo)
    assert result.returncode == 1
    assert (repo / _SUBJECT).read_text() == "EDITED\n", (
        "the ceremony ate the change it exists to record")


def test_a_refusing_author_leaves_no_half_written_manifest(repo: Path):
    """A manifest the author refused to finish must not be left on disk to be
    committed by the next thing that runs."""
    (repo / "tools" / "ci" / "protected_landing_manifest_author.py").write_text(
        _REFUSING_AUTHOR)
    before = (repo / _MANIFEST).read_text()
    (repo / _SUBJECT).write_text("EDITED\n")
    assert _prepare(repo).returncode == 1
    assert (repo / _MANIFEST).read_text() == before
