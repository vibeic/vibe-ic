"""The layer-membership rule, driven in both directions.

This gate is RED on the tree it ships with, deliberately, so the shipped-tree
test asserts rc 1 and names what must change for it to go green. A test that
asserted rc 0 here would be asserting the defect away.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROG = (Path(__file__).resolve().parents[1]
        / "layer_membership_is_declared_not_inferred_from_a_filename_prefix.py")

# ── THE PIN IS A MEMBER SET, NOT A COUNT ─────────────────────────────────────
# Every earlier spelling of this pin was three counts (`glob 21, relation 28,
# 7 outside`) with ONE member named beside them. A count cannot report an
# arrival that a departure cancels -- 8 members leave 8 members -- and a count
# is the one thing that can be re-derived without reading the tree, so a
# re-derivation and an edit-to-fit are indistinguishable in the diff. These are
# the members. A move is then reported as a NAME that entered or left.
#
# Read from the program's own `--json` (`glob_members` / `relation_members` /
# `outside`), which is the program's `_imports` / `_is_executable` over the live
# tree -- not a filename pattern this file wrote for the occasion.
#: The finding itself: layer members no `ppa_*.py` glob reaches.
#: `phase3_one_shot_runner.py` entered at v1.17.91 `8d7a76cca`, which added
#: `from _ppa import delivery_path` to an executable module. Nothing left.



_LAYER_MEMBER = '''\
import _demo


def main():
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

_NOT_EXECUTABLE = '''\
import _demo


def helper():
    return 1
'''


def _tree(*, glob_named: int, outside: int, outside_executable: bool = True,
          test_body: str = None) -> Path:
    root = Path(tempfile.mkdtemp(prefix="lmd_"))
    (root / ".git").mkdir()
    progs = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
    (progs / "_demo").mkdir(parents=True)
    (progs / "_demo" / "__init__.py").write_text("")
    tests = progs / "tests"
    tests.mkdir()
    for i in range(glob_named):
        (progs / f"demo_{i}.py").write_text(_LAYER_MEMBER)
    body = _LAYER_MEMBER if outside_executable else _NOT_EXECUTABLE
    for i in range(outside):
        (progs / f"other_{i}.py").write_text(body)
    (tests / "test_demo_layer.py").write_text(
        test_body if test_body is not None
        else 'from pathlib import Path\n'
             'P = Path(__file__).parent.parent\n'
             'MEMBERS = sorted(p.name for p in P.glob("demo_*.py"))\n')
    return root


def _run(root: Path):
    return _pr.run([sys.executable, str(PROG), "--root", str(root)],
                          capture_output=True, text=True)


def test_a_layer_member_outside_the_glob_is_refused():
    """NEGATIVE CONTROL."""
    r = _run(_tree(glob_named=3, outside=2))
    assert r.returncode == 1, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "other_0.py" in r.stdout and "demo" in r.stdout


def test_a_glob_that_reaches_the_whole_relation_is_not_refused():
    r = _run(_tree(glob_named=3, outside=0))
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_a_non_executable_importer_is_not_a_member():
    """An exit-code contract cannot be enforced on a module with no entry point.

    Counting them would have inflated the real finding by 40 per cent.
    """
    r = _run(_tree(glob_named=3, outside=2, outside_executable=False))
    assert r.returncode == 0, (
        f"a module with no __main__ was counted as a layer executable "
        f"(rc={r.returncode})\n{r.stdout}")


def test_a_prefix_with_no_layer_package_is_out_of_population():
    root = _tree(glob_named=2, outside=1)
    import shutil
    shutil.rmtree(root / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
                  / "programs" / "_demo")
    r = _run(root)
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_a_test_star_glob_is_test_discovery_not_a_layer():
    root = _tree(glob_named=2, outside=1,
                 test_body='from pathlib import Path\n'
                           'P = Path(__file__).parent\n'
                           'T = sorted(p.name for p in P.glob("test_*.py"))\n')
    r = _run(root)
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_a_missing_tree_is_undetermined_not_a_pass():
    r = _pr.run([sys.executable, str(PROG), "--root", "/nonexistent/jd"],
                       capture_output=True, text=True)
    assert r.returncode == 2, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_a_bad_invocation_is_rc_3():
    r = _pr.run([sys.executable, str(PROG), "--no-such-flag"],
                       capture_output=True, text=True)
    assert r.returncode == 3, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"




def test_no_test_files_read_is_undetermined_not_a_pass():
    """The denominator that decides is TESTS READ, not globs in scope.

    A tree whose only prefix glob is test discovery HAS been examined and found
    nothing in scope -- the tests above pin that as a real rc 0. A tree with no
    test files at all was not examined, and the `[PASS]` sentence is then a
    universal claim over the empty set.

    A first attempt keyed this on `prefix_globs` and turned three of the tests
    above red, correctly, by conflating the two.
    """
    root = Path(tempfile.mkdtemp(prefix="lmzero_"))
    try:
        (root / ".git").mkdir()
        (root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
         / "tests").mkdir(parents=True)
        r = _pr.run([sys.executable, str(PROG), "--root", str(root)],
                           capture_output=True, text=True)
        assert r.returncode == 2, f"rc={r.returncode}\n{r.stdout}"
        assert "0 test files were read" in r.stdout, r.stdout
        assert "[PASS]" not in r.stdout, r.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)
