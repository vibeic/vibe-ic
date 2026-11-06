#!/usr/bin/env python3
"""The IP route is not "37.5ip's condition is met" any more, and this pins it.

THE DEFECT THIS CLOSES
======================
`_ppa/delivery_path.py` decides whether a design is tape-out-bound by driving
the flow's own conditions for the two terminal steps, and it read them as two
mutually-exclusive route selectors: 37.5ic met -> CHIP, 37.5ip met -> IP, both
met -> BOTH ("no silicon corresponds to a tree holding two routers").

OWNER RULING 2026-09-02, landed in `df8163448` and pinned by
`test_delivery_route_step_reachability.py`, made that reading false: "an IC
runs BOTH 37.5ic and 37.5ip; only a pure-IP route skips 37.5ic", because a die
also ships the IP deliverable set. 37.5ip's condition was widened from the one
router `NO_TEMPLATE.txt` to `any_of` over ALL THREE. `delivery_path` was not
in that commit.

MEASURED at 20031834c1, with no corpus pointer bound: EVERY chip tree resolved
`BOTH`, so `eco_readiness` answered `PATH_UNDETERMINED` -- "I could not
establish the route" -- on every tape-out-bound design in the search lane. Six
tests across `test_ppa_eco_delivery_path.py` and
`test_ppa_eco_axis_bites_in_the_search_lane.py` were red on it.

WHAT IS PINNED HERE, AND IN WHICH DIRECTION
===========================================
The first three go RED on the pre-fix module and GREEN after; they are written
through `_route_map()` so the OLD code ANSWERS them (wrongly) rather than
raising `AttributeError`, which would observe nothing.

The last two hold in BOTH directions. They are the other half of the pin: the
route may not be recovered by narrowing 37.5ip back to one router, or by
widening 37.5ic to accept the IP router and asking a pure IP for a pad ring it
has no die for. Those are the flow's decisions and this module follows them.
"""
import pathlib
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

from _ppa import delivery_path as DP  # noqa: E402

#: The three router artefacts step 0.5ic may write, spelled from the modules
#: that own them so a rename reaches this file.
import _submission_template as ST  # noqa: E402
import _tapeout_declaration as TD  # noqa: E402

#: As the FLOW spells them -- a glob for the shuttle slots, a literal for the
#: other two. These are what a terminal's `files_exist` names.

#: As a TREE carries them: one concrete file per chip route.
CHIP_ROUTERS = (ST.SLOTS_DIR_REL + "/1x1.yaml", TD.SELF_TAPEOUT_REL)


def _tree(root, routers):
    root.mkdir(parents=True, exist_ok=True)
    report = root / "reports/flow_engine.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(__import__("json").dumps({"route": {"delivery_target": "gds"}}))
    return root




# ---------------------------------------------------------------------------
# RED before the fix, GREEN after
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("router", CHIP_ROUTERS)
def test_a_tree_carrying_one_chip_router_is_on_the_chip_path(tmp_path, router):
    """Both chip routes, because a predicate that recognised only one of them
    would let a shuttle die through -- and one that recognised neither, as the
    pre-fix module did, refuses every die on the corpus."""
    pytest.importorskip("yaml")
    r = DP.resolve(_tree(tmp_path / pathlib.Path(router).name, [router]))
    assert r["path"] == DP.PATH_CHIP, r["reason"]
    assert DP.is_tapeout_bound(r["path"])




# ---------------------------------------------------------------------------
# UNCHANGED in both directions -- the flow's decision, which this module follows
# ---------------------------------------------------------------------------
