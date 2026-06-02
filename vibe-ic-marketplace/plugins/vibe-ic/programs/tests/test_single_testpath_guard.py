"""v0.2.24 — single-testpath guard (Bucket A capture from the v0.2.19 merge).

Pins the "let two test folders be one" invariant: pytest.ini must declare
exactly ONE test tree. PASS on the current single-tree state; FAIL if a second
testpath is re-added (the green-local/red-CI footgun) or the tree is missing.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import single_testpath_guard as G  # noqa: E402

_PLUGIN = Path(__file__).resolve().parent.parent.parent


def test_current_repo_is_single_tree():
    """corpus-sweep: after the merge, the shipped pytest.ini is single-tree."""
    res = G.evaluate(_PLUGIN)
    assert res["findings"] == [], res
    assert res["testpaths"] == ["programs/tests"]


def _mk(tmp_path, testpaths_line, make_dirs=()):
    (tmp_path / "pytest.ini").write_text(
        "[pytest]\ntestpaths = " + testpaths_line + "\n")
    for d in make_dirs:
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    return tmp_path


def test_two_testpaths_fails(tmp_path):
    _mk(tmp_path, "programs/tests tests", ("programs/tests", "tests"))
    assert G.main([str(tmp_path)]) == 1


def test_single_testpath_passes(tmp_path):
    _mk(tmp_path, "programs/tests", ("programs/tests",))
    assert G.main([str(tmp_path)]) == 0


def test_zero_testpaths_fails(tmp_path):
    _mk(tmp_path, "", ())
    assert G.main([str(tmp_path)]) == 1


def test_missing_declared_tree_fails(tmp_path):
    _mk(tmp_path, "programs/tests", ())  # declared but not created
    assert G.main([str(tmp_path)]) == 1


def test_no_pytest_ini_is_skip(tmp_path):
    assert G.main([str(tmp_path)]) == 2
