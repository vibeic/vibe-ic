"""The count-pin rule, driven in both directions.

The positive control the capture recorded is kept here as a test: a departure
and an arrival applied to one population leave the COUNT identical and the
MEMBER SET different. That is the whole claim, and it is arithmetic.
"""
from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


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
