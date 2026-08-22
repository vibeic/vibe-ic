"""The tautological-guard rule, driven in both directions.

Every green case here is a shape that made the predicate wrong at some point in
its development, kept so it stays wrong-proof.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PROG = (Path(__file__).resolve().parents[1]
        / "population_guard_asserts_equality_not_a_floor.py")

#: A literal asserted against its own length. Cannot fail.
_DEFECT_EQ = '''\
_PORTS = ("a", "b", "c", "d")
assert len(_PORTS) == 4
'''

#: A floor already satisfied by the literal itself. Also cannot fail.
_DEFECT_FLOOR = '''\
NEG_FIXTURES = ["a", "b", "c", "d", "e", "f"]


def test_at_least_five_negatives():
    assert len(NEG_FIXTURES) >= 5
'''

#: The remedy: assert the literal against a POPULATION that can differ.
_REPAIRED = '''\
_PORTS = ("a", "b", "c", "d")


def test_the_parser_recovers_every_declared_port(parsed):
    assert set(parsed) == set(_PORTS), (
        sorted(set(parsed) - set(_PORTS)), sorted(set(_PORTS) - set(parsed)))
'''

#: A SET of non-constants is a DISTINCTNESS assertion and fails the moment two
#: collide. Never a tautology.
_DISTINCTNESS = '''\
import gate as G


def test_the_exit_codes_are_distinct():
    assert len({G.RC_OK, G.RC_FAIL, G.RC_REFUSE}) == 3
'''

#: The collection is MUTATED, so its size is not the literal's.
_MUTATED = '''\
def test_findings():
    fails = []
    for row in range(10):
        if row % 2:
            fails.append(row)
    assert len(fails) == 0 or True
'''

#: SCOPE. One function binds `steps` to a literal; the assertion's own scope
#: binds it from a call. Module-wide tracking called this a tautology.
_SCOPE = '''\
def _shipped():
    return [1, 2, 3], {"a": 1}


def test_parity():
    steps, manifest_steps = _shipped()
    assert len(steps) > 0, "no flow steps"


def test_fixture():
    steps = [{"id": "D1"}]
    return steps
'''


def _tree(body: str, inventory=None, name="test_sample.py") -> Path:
    root = Path(tempfile.mkdtemp(prefix="pgf_"))
    (root / ".git").mkdir()
    tests = (root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
             / "tests")
    tests.mkdir(parents=True)
    (tests / name).write_text(body)
    (root / "inventory.json").write_text(
        json.dumps({"known": inventory or []}) + "\n")
    return root


def _run(root: Path, inventory: Path = None):
    return subprocess.run(
        [sys.executable, str(PROG), "--root", str(root), "--inventory",
         str(inventory or (root / "inventory.json"))],
        capture_output=True, text=True, timeout=300)


def test_a_literal_asserted_against_its_own_length_is_refused():
    """NEGATIVE CONTROL."""
    r = _run(_tree(_DEFECT_EQ))
    assert r.returncode == 1, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "_PORTS" in r.stdout


def test_a_floor_the_literal_already_satisfies_is_refused():
    r = _run(_tree(_DEFECT_FLOOR))
    assert r.returncode == 1, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "NEG_FIXTURES" in r.stdout


def test_a_set_comparison_against_a_population_is_not_refused():
    r = _run(_tree(_REPAIRED))
    assert r.returncode == 0, (
        f"the remedy was refused (rc={r.returncode})\n{r.stdout}\n{r.stderr}")


def test_a_distinctness_set_is_not_a_tautology():
    """It fails the moment two constants collide, which is why it is written."""
    r = _run(_tree(_DISTINCTNESS))
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_a_mutated_collection_is_not_its_literal():
    r = _run(_tree(_MUTATED))
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_scope_is_load_bearing():
    """Module-wide binding called this a tautology; it is not.

    `steps` in `test_parity` comes from a tuple-unpack of a call. A DIFFERENT
    function binds a name spelled the same way to a literal.
    """
    r = _run(_tree(_SCOPE))
    assert r.returncode == 0, (
        f"a name bound in another scope was attributed to this assertion "
        f"(rc={r.returncode})\n{r.stdout}\n{r.stderr}")


def test_the_population_is_stated_even_when_clean():
    r = _run(_tree(_REPAIRED))
    assert "len() over an unmutated literal:" in r.stdout


def test_a_stale_inventory_row_is_a_failure():
    r = _run(_tree(_REPAIRED, inventory=[
        {"key": "programs/tests/test_gone.py::len(X) == 3", "reason": "stale"}]))
    assert r.returncode == 1, f"rc={r.returncode}\n{r.stdout}"


def test_a_missing_tree_is_undetermined_not_a_pass():
    r = subprocess.run([sys.executable, str(PROG), "--root", "/nonexistent/jd"],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 2, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_a_bad_invocation_is_rc_3():
    r = subprocess.run([sys.executable, str(PROG), "--no-such-flag"],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 3, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_the_shipped_tree_passes_its_own_rule():
    root = Path(__file__).resolve().parents[5]
    if not (root / ".git").exists():
        pytest.skip("not a checkout")
    r = subprocess.run([sys.executable, str(PROG), "--root", str(root)],
                       capture_output=True, text=True, timeout=1800)
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
