"""The borrowing-clone rule, driven in both directions.

The three-way drive against real git is a test in its own right: it is the
measurement that corrected the record this rule came from, and it must keep
being true of whatever git the container ships.
"""
from __future__ import annotations

import shutil
import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_RULE = "local_clone_does_not_borrow_objects"
PROG = (Path(__file__).resolve().parents[1]
        / "local_clone_does_not_borrow_objects_census.py")

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


def _tree(files: dict, inventory=None) -> Path:
    root = Path(tempfile.mkdtemp(prefix="lcb_"))
    (root / ".git").mkdir()
    progs = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
    progs.mkdir(parents=True)
    for name, body in files.items():
        (progs / name).write_text(body)
    (root / "inventory.json").write_text(
        json.dumps({"known": inventory or []}) + "\n")
    return root


def _run(root: Path, *extra, inventory: Path = None):
    return _pr.run(
        [sys.executable, str(PROG), "--root", str(root), "--inventory",
         str(inventory or (root / "inventory.json")), *extra],
        capture_output=True, text=True)


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
def test_a_shared_clone_is_refused():
    r = _run(_tree({"prepare_checkout.py": _DEFECT}), "--strict")
    assert r.returncode == 1, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "--shared" in r.stdout


def test_a_reference_clone_is_refused():
    r = _run(_tree({"prepare_checkout.py": _DEFECT_REFERENCE}), "--strict")
    assert r.returncode == 1, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "--reference" in r.stdout


def test_a_shell_script_clone_is_refused():
    r = _run(_tree({"prepare.sh": _SHELL_DEFECT}), "--strict")
    assert r.returncode == 1, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


# ----------------------------------------------------------- the GREEN cases
def test_a_plain_local_clone_is_not_refused():
    r = _run(_tree({"prepare_checkout.py": _PLAIN}))
    assert r.returncode == 0, (
        f"a plain clone was refused (rc={r.returncode}) — the rule would be "
        f"refusing the remedy the preflight names.\n{r.stdout}\n{r.stderr}")


def test_dissociate_absorbs_and_is_not_refused():
    r = _run(_tree({"prepare_checkout.py": _DISSOCIATE}))
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_an_unrelated_reference_flag_is_not_a_clone():
    r = _run(_tree({"ppa_area_threshold_check.py": _UNRELATED_REFERENCE}))
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_a_test_that_builds_the_shape_is_out_of_population():
    """Both first-sweep hits were tests proving the preflight refuses this."""
    root = _tree({})
    tests = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs" / "tests"
    tests.mkdir(parents=True)
    (tests / "test_preflight.py").write_text(_DEFECT)
    r = _run(root)
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


# ------------------------------------------------------------- the contract
def test_a_stale_inventory_row_is_a_failure():
    r = _run(_tree({"prepare_checkout.py": _PLAIN}, inventory=[
        {"key": "programs/gone.py::--shared::argv", "reason": "stale"}]), "--strict")
    assert r.returncode == 1, f"rc={r.returncode}\n{r.stdout}"


def test_a_missing_tree_is_undetermined_not_a_pass():
    r = _pr.run([sys.executable, str(PROG), "--root", "/nonexistent/jd"],
                       capture_output=True, text=True)
    assert r.returncode == 2, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_a_bad_invocation_is_rc_3():
    r = _pr.run([sys.executable, str(PROG), "--no-such-flag"],
                       capture_output=True, text=True)
    assert r.returncode == 3, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_the_shipped_tree_passes_its_own_rule():
    root = Path(__file__).resolve().parents[5]
    if not (root / ".git").exists():
        pytest.skip("not a checkout")
    r = _pr.run([sys.executable, str(PROG), "--root", str(root)],
                       capture_output=True, text=True)
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_the_census_never_blocks_by_default():
    """The ruling: this is a census and must not be wired as a blocking check.

    A census that exits non-zero gets wired as a gate by the next person who
    reads the exit code, so the default is 0 whatever is found — and the
    output says so and names the gate that does refuse.
    """
    root = Path(__file__).resolve().parents[5]
    if not (root / ".git").exists():
        pytest.skip("not a checkout")
    r = _pr.run([sys.executable, str(PROG), "--root", str(root)],
                       capture_output=True, text=True)
    assert r.returncode == 0, (
        f"the census refused by default (rc={r.returncode}); it must report\n"
        f"{r.stdout}\n{r.stderr}")
    assert "[CENSUS]" in r.stdout
    assert "the gate is programs/%s.py" % _RULE in r.stdout, (
        "the census must name the gate that does the refusing")


def test_a_count_over_an_empty_population_is_undetermined():
    """`[CENSUS] 0 site(s)` is honest only if something was read.

    Over a tree this program parsed NOTHING, a count of 0 is
    indistinguishable from a clean result. Measured before the guard: rc 0 --
    and still 0 under `--strict`, so "--strict is where a caller asks for the
    refusal" did not cover it either. Exiting 0 is a census's contract for a
    REAL population, not a licence to report over none.
    """
    root = Path(tempfile.mkdtemp(prefix="csz_"))
    try:
        (root / ".git").mkdir()
        (root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
         / "tests").mkdir(parents=True)
        r = _pr.run([sys.executable, str(PROG), "--root", str(root)],
                           capture_output=True, text=True)
        assert r.returncode == 2, f"rc={r.returncode}\n{r.stdout}"
        assert "NOT a pass" in r.stdout, r.stdout
        assert "[CENSUS] 0 site(s)" not in r.stdout, r.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)
