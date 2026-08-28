"""The moving-reference rule, driven in both directions."""
from __future__ import annotations

import shutil
import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROG = (Path(__file__).resolve().parents[1]
        / "reference_control_resolved_through_a_mutable_ref.py")

#: The ORIGINAL shape the capture measured: a control loading its reference
#: version of a program through a remote-tracking branch name.
_DEFECT = '''\
import subprocess


def reference_version(repo, rel):
    r = subprocess.run(["git", "-C", str(repo), "show", f"origin/main:{rel}"],
                       capture_output=True, text=True)
    return r.stdout
'''

#: The same control with the reference point held still.
_REPAIRED = '''\
import subprocess

#: PINNED to an object, not a branch: the control must keep asserting against
#: the state that was legitimately vulnerable.
_BASE_REV = "397b3f25f0a1b2c3d4e5f60718293a4b5c6d7e8f"


def reference_version(repo, rel):
    r = subprocess.run(["git", "-C", str(repo), "show", f"{_BASE_REV}:{rel}"],
                       capture_output=True, text=True)
    return r.stdout
'''

#: 30 of the 31 revision reads measured on the capture commit are this: a
#: working-tree pointer against a fixture the caller just built.
_FIXTURE_POINTER = '''\
import subprocess


def head_of_fixture(repo):
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout
'''

#: A NAME resolution, not an object read — out of scope by construction.
_NAME_RESOLUTION = '''\
import subprocess


def upstream_name(repo):
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--abbrev-ref",
         "--symbolic-full-name", "@{upstream}"],
        capture_output=True, text=True).stdout
'''

#: The mirror the second lane measured: a guard whose SUBJECT SET comes from a
#: diff against a moving name, so it collects a different population per clone.
_COVERAGE_DIFF = '''\
import subprocess


def subjects(repo):
    r = subprocess.run(["git", "-C", str(repo), "diff", "--name-only",
                        "origin/main"], capture_output=True, text=True)
    return r.stdout.splitlines()
'''


def _tree(body: str, inventory=None) -> Path:
    root = Path(tempfile.mkdtemp(prefix="mrr_"))
    (root / ".git").mkdir()
    progs = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
    progs.mkdir(parents=True)
    (progs / "sample_control.py").write_text(body)
    (root / "inventory.json").write_text(
        json.dumps({"known": inventory or []}) + "\n")
    return root


def _run(root: Path, inventory: Path = None):
    return _pr.run(
        [sys.executable, str(PROG), "--root", str(root), "--inventory",
         str(inventory or (root / "inventory.json"))],
        capture_output=True, text=True)


def test_a_reference_read_through_a_branch_name_is_refused():
    """NEGATIVE CONTROL — the original defect, reintroduced."""
    root = _tree(_DEFECT)
    r = _run(root)
    assert r.returncode == 1, (
        f"the defect was NOT refused (rc={r.returncode})\n{r.stdout}\n{r.stderr}")
    assert "git show origin/main" in r.stdout


def test_a_subject_set_derived_from_a_branch_diff_is_refused():
    """The mirror: coverage that differs between two clones of one tree."""
    root = _tree(_COVERAGE_DIFF)
    r = _run(root)
    assert r.returncode == 1, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "git diff origin/main" in r.stdout


def test_a_pinned_object_is_not_refused():
    root = _tree(_REPAIRED)
    r = _run(root)
    assert r.returncode == 0, (
        f"the remedy was refused (rc={r.returncode})\n{r.stdout}\n{r.stderr}")


def test_a_working_tree_pointer_against_a_fixture_is_not_refused():
    """The discriminator is the BRANCH SHAPE, not the presence of a revision."""
    root = _tree(_FIXTURE_POINTER)
    r = _run(root)
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_a_name_resolution_is_out_of_scope():
    root = _tree(_NAME_RESOLUTION)
    r = _run(root)
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_a_branch_name_in_prose_is_not_a_finding():
    """The naive regex form of this search was 87% docstrings."""
    root = _tree('"""Measured on origin/main against main and master."""\n'
                 "# see git show origin/main:programs/x.py\n"
                 "VALUE = 1\n")
    r = _run(root)
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_a_stale_inventory_row_is_a_failure():
    root = _tree(_REPAIRED, inventory=[
        {"key": "programs/gone.py::show::origin/main:x", "reason": "stale"}])
    r = _run(root)
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


def test_an_empty_population_is_undetermined_not_a_pass():
    """A GREEN FROM AN EMPTY DENOMINATOR IS NOT A PASS.

    Measured before the guard existed: on a well-formed but EMPTY tree this
    program printed its populations as 0 and then a `[PASS]` sentence that is a
    universal claim over the empty set -- vacuously true, and indistinguishable
    to a caller from the same sentence over the real repository.

    `gate_zero_denominator_refuses_check` refuses this shape, and CANNOT SEE
    THIS FILE: its population is `*_check.py`. So the refusal is asserted here.
    """
    root = Path(tempfile.mkdtemp(prefix="zeropop_"))
    try:
        (root / ".git").mkdir()
        (root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
         / "tests").mkdir(parents=True)
        r = _pr.run([sys.executable, str(PROG), "--root", str(root)],
                           capture_output=True, text=True)
        assert r.returncode == 2, (
            f"an empty population returned rc={r.returncode}; it must be "
            f"UNDETERMINED, not a pass\n{r.stdout}")
        assert "NOT a pass" in r.stdout, r.stdout
        assert "[PASS]" not in r.stdout, r.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)
