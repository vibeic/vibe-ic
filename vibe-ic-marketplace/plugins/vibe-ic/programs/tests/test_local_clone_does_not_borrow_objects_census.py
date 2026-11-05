"""The borrowing-clone rule, driven in both directions.

The three-way drive against real git is a test in its own right: it is the
measurement that corrected the record this rule came from, and it must keep
being true of whatever git the container ships.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_RULE = "local_clone_does_not_borrow_objects"

_DEFECT = '''\
import subprocess


def prepare(src, dest):
    subprocess.run(["git", "clone", "--quiet", "--shared", str(src), str(dest)],
                   check=True)
'''

_DEFECT_REFERENCE = '''\
import subprocess


def prepare(src, dest, ref):
    subprocess.run(["git", "clone", "--reference", str(ref), str(src),
                    str(dest)], check=True)
'''

#: A plain local clone hardlinks immutable objects and leaves no alternates.
_PLAIN = '''\
import subprocess


def prepare(src, dest):
    subprocess.run(["git", "clone", "--quiet", str(src), str(dest)], check=True)
'''

#: --dissociate absorbs the borrowed objects, so no alternates survive.
_DISSOCIATE = '''\
import subprocess


def prepare(src, dest, ref):
    subprocess.run(["git", "clone", "--reference", str(ref), "--dissociate",
                    str(src), str(dest)], check=True)
'''

#: A program with a `--reference` golden of its own. Not a clone.
_UNRELATED_REFERENCE = '''\
import argparse


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reference", default=None, help="golden to compare with")
    return ap.parse_args()
'''

_SHELL_DEFECT = "#!/bin/bash\nset -eu\ngit clone --shared \"$SRC\" \"$DEST\"\n"






# ------------------------------------------------- what git actually does
def _git(*args, cwd=None):
    return _pr.run(["git", *args], cwd=cwd, capture_output=True,
                          text=True)


def test_only_shared_and_reference_actually_borrow():
    """The measurement that CORRECTED the record, kept as a control.

    The record's fix_action asks for `--no-hardlinks`. This shows why that is
    the wrong option: hardlinking is not borrowing, and the file the preflight
    refuses is written only by `--shared` / `--reference`.
    """
    base = Path(tempfile.mkdtemp(prefix="lcb_git_"))
    src = base / "src"
    src.mkdir()
    assert _git("init", "-q", ".", cwd=src).returncode == 0
    _git("config", "user.email", "t@t", cwd=src)
    _git("config", "user.name", "t", cwd=src)
    (src / "a.txt").write_text("x\n")
    _git("add", "a.txt", cwd=src)
    assert _git("commit", "-qm", "init", cwd=src).returncode == 0

    def alternates(mode, name, *opts):
        dest = base / name
        r = _git("clone", "-q", *opts, str(src), str(dest))
        assert r.returncode == 0, (mode, r.stderr)
        return (dest / ".git" / "objects" / "info" / "alternates").exists()

    assert alternates("plain", "plain") is False, (
        "a plain local clone borrowed — the preflight's premise would be wrong")
    assert alternates("no-hardlinks", "nohl", "--no-hardlinks") is False, (
        "--no-hardlinks changed nothing about borrowing, which is the point")
    assert alternates("shared", "shared", "--shared") is True, (
        "--shared did NOT borrow on this git; the rule's subject does not "
        "exist here and the predicate needs re-deriving, not re-asserting")


# ------------------------------------------------------------- the RED cases






# ----------------------------------------------------------- the GREEN cases








# ------------------------------------------------------------- the contract
