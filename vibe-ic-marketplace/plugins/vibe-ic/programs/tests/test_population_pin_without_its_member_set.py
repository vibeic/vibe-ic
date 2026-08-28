"""The count-pin rule, driven in both directions.

The positive control the capture recorded is kept here as a test: a departure
and an arrival applied to one population leave the COUNT identical and the
MEMBER SET different. That is the whole claim, and it is arithmetic.
"""
from __future__ import annotations

import re
import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROG = (Path(__file__).resolve().parents[1]
        / "population_pin_without_its_member_set.py")

#: A count pinned against a live re-derivation of the checkout, with nothing
#: pinning the identities.
_DEFECT = '''\
import yaml
from pathlib import Path

FLOW = Path(__file__).resolve().parents[1] / "flow.yaml"


def step_ids():
    return [s["id"] for s in yaml.safe_load(FLOW.read_text())["steps"]]


def test_the_grid_is_the_size_it_was():
    assert len(step_ids()) == 69
'''

#: The remedy: the identities pinned beside the count, compared both ways.
_REPAIRED = '''\
import yaml
from pathlib import Path

FLOW = Path(__file__).resolve().parents[1] / "flow.yaml"

_EXPECTED = {"s1", "s2", "s3"}


def step_ids():
    return [s["id"] for s in yaml.safe_load(FLOW.read_text())["steps"]]


def test_the_grid_is_the_size_it_was():
    assert len(step_ids()) == 69


def test_the_grid_is_the_set_it_was():
    got = set(step_ids())
    assert got == _EXPECTED, (sorted(got - _EXPECTED), sorted(_EXPECTED - got))
'''

#: A count over a fixture the test itself just wrote is the test stating its
#: own input. Reading those as population pins was measured at 73 modules.
_OWN_FIXTURE = '''\
import json


def test_the_emitter_writes_three_rows(tmp_path):
    out = tmp_path / "rows.json"
    out.write_text(json.dumps([1, 2, 3]))
    assert len(json.loads(out.read_text())) == 3
'''

#: `== 1` is a presence test, not a population.
_PRESENCE = '''\
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_exactly_one():
    assert len(list(ROOT.glob("*.cfg"))) == 1
'''


def _tree(body: str, inventory=None, name="test_sample.py") -> Path:
    root = Path(tempfile.mkdtemp(prefix="ppm_"))
    (root / ".git").mkdir()
    tests = (root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
             / "tests")
    tests.mkdir(parents=True)
    (tests / name).write_text(body)
    (root / "inventory.json").write_text(
        json.dumps({"known": inventory or []}) + "\n")
    return root


def _run(root: Path, inventory: Path = None):
    return _pr.run(
        [sys.executable, str(PROG), "--root", str(root), "--inventory",
         str(inventory or (root / "inventory.json"))],
        capture_output=True, text=True)


def test_a_count_only_pin_is_refused():
    """NEGATIVE CONTROL."""
    r = _run(_tree(_DEFECT))
    assert r.returncode == 1, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "test_sample.py" in r.stdout
    # ANCHORED TO THE COUNT POSITION. The finding renders as
    #   test_sample.py  N pin(s): 69 via <derived_by> (line L)
    # so a bare `"69" in r.stdout` is also satisfied by a LINE NUMBER of 69,
    # or by 169/690. It must be the pinned COUNT that is 69.
    assert re.search(r"\b69 via ", r.stdout), (
        f"69 is not reported as the pinned count\n{r.stdout}")


def test_a_member_pin_beside_the_count_is_not_refused():
    r = _run(_tree(_REPAIRED))
    assert r.returncode == 0, (
        f"the remedy was refused (rc={r.returncode})\n{r.stdout}\n{r.stderr}")


def test_a_count_over_the_tests_own_fixture_is_not_a_population_pin():
    r = _run(_tree(_OWN_FIXTURE))
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_a_count_of_one_is_a_presence_test_not_a_population():
    r = _run(_tree(_PRESENCE))
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_the_positive_control_a_count_cannot_see_a_swap():
    """One departure and one arrival: the count is identical, the set is not.

    This is the measurement the rule rests on, re-derived rather than quoted.
    """
    live = [f"s{i}" for i in range(69)]
    assert len(live) == 69

    moved = [x for x in live if x != "s7"] + ["s99"]
    assert len(moved) == len(live), "the control is not a compensating change"
    assert set(moved) != set(live)
    assert set(moved) ^ set(live) == {"s7", "s99"}, (
        "the symmetric difference must be exactly the departure and the "
        "arrival, or the control is measuring something else")


def test_a_stale_inventory_row_is_a_failure():
    r = _run(_tree(_REPAIRED, inventory=[
        {"key": "programs/tests/test_gone.py", "reason": "stale"}]))
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
