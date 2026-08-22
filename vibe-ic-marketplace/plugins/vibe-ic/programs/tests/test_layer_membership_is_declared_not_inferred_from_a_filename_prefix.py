"""The layer-membership rule, driven in both directions.

This gate is RED on the tree it ships with, deliberately, so the shipped-tree
test asserts rc 1 and names what must change for it to go green. A test that
asserted rc 0 here would be asserting the defect away.
"""
from __future__ import annotations

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
    # A count pin without a member set is the defect
    # `population_pin_without_its_member_set` reports; a member set without a
    # count is the half that cannot see growth. Keep BOTH.
    # If this fails, RE-DERIVE the finding -- do not edit the number to fit.
    # ANCHORED, not a substring: "6 outside" is contained in "16 outside".
    assert re.search(r"glob 20, relation 26, 6 outside(?!\d)", r.stdout), (
        f"the ppa layer population moved; re-derive the finding\n{r.stdout}")
