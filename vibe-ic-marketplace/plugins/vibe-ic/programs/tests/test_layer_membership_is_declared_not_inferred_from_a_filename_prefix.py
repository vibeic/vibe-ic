"""The layer-membership rule, driven in both directions.

This gate is RED on the tree it ships with, deliberately, so the shipped-tree
test asserts rc 1 and names what must change for it to go green. A test that
asserted rc 0 here would be asserting the defect away.
"""
from __future__ import annotations

import shutil
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PROG = (Path(__file__).resolve().parents[1]
        / "layer_membership_is_declared_not_inferred_from_a_filename_prefix.py")

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
    return subprocess.run([sys.executable, str(PROG), "--root", str(root)],
                          capture_output=True, text=True, timeout=300)


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
    r = subprocess.run([sys.executable, str(PROG), "--root", "/nonexistent/jd"],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 2, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_a_bad_invocation_is_rc_3():
    r = subprocess.run([sys.executable, str(PROG), "--no-such-flag"],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 3, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_the_shipped_tree_is_RED_and_that_is_the_point():
    """This gate refuses on the tree it ships with, by design.

    There is no inventory: a recorded waiver would make the question disappear.
    When both `ppa` suites are pointed at the relation-derived population this
    goes green, and THAT is the signal the repair landed.
    """
    root = Path(__file__).resolve().parents[5]
    if not (root / ".git").exists():
        pytest.skip("not a checkout")
    r = subprocess.run([sys.executable, str(PROG), "--root", str(root)],
                       capture_output=True, text=True, timeout=1800)
    assert r.returncode == 1, (
        f"the ppa layer gap is GONE (rc={r.returncode}). If the two suites were "
        f"repaired, delete this assertion and assert rc 0 — do not weaken the "
        f"gate.\n{r.stdout}")
    assert "layer `ppa`" in r.stdout
    assert "power_total_vs_budget_check.py" in r.stdout
    # THE POPULATION, PINNED ALONGSIDE THE MEMBER. The member assertion above
    # cannot notice the layer GROWING: when the merge with main a4caccefe took
    # the gap from 5 outside to 6, this test still passed and said nothing.
    # RE-DERIVED on the composed tree: the layer took one more member into BOTH
    # the glob and the relation (20/26 -> 21/27) and the 6 outside are the same
    # 6 names, so the gap did not move — the population did.
    # RE-DERIVED AGAIN 2026-08-25 (21/27/6 -> 21/28/7). v1.11.81 added
    # `programs/_ppa/records_migrate.py`, which imports the layer package and so
    # joins the RELATION, and which no prefix glob reaches and so joins the
    # OUTSIDE set. The glob is unchanged at 21, which is the whole finding: the
    # layer grew and the population selected by a filename prefix did not.
    # The number was NOT edited to fit — the program was re-run on this tree and
    # its own line read back (`layer `ppa`: glob 21, relation 28, 7 outside`),
    # and the new outside member is named in the member list below.
    # A count pin without a member set is the defect
    # `population_pin_without_its_member_set` reports; a member set without a
    # count is the half that cannot see growth. Keep BOTH.
    # If this fails, RE-DERIVE the finding -- do not edit the number to fit.
    # ANCHORED, not a substring: "7 outside" is contained in "17 outside".
    assert re.search(r"glob 21, relation 28, 7 outside(?!\d)", r.stdout), (
        f"the ppa layer population moved; re-derive the finding\n{r.stdout}")
    # THE MEMBER THE COUNT ALONE WOULD NOT HAVE SHOWN. One arrival and one
    # departure leave 7 at 7; naming the arrival is what makes the count a
    # statement about a set rather than about its size.
    assert "records_migrate.py" in r.stdout, (
        f"the layer's newest outside member is not reported\n{r.stdout}")


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
        r = subprocess.run([sys.executable, str(PROG), "--root", str(root)],
                           capture_output=True, text=True, timeout=900)
        assert r.returncode == 2, f"rc={r.returncode}\n{r.stdout}"
        assert "0 test files were read" in r.stdout, r.stdout
        assert "[PASS]" not in r.stdout, r.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)
