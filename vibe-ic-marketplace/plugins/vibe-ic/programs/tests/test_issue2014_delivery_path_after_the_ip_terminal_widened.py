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
CHIP_ROUTER_PATTERNS = (ST.SLOTS_DIR_REL + "/*.yaml", TD.SELF_TAPEOUT_REL)
IP_ROUTER = ST.NO_TEMPLATE_REL

#: As a TREE carries them: one concrete file per chip route.
CHIP_ROUTERS = (ST.SLOTS_DIR_REL + "/1x1.yaml", TD.SELF_TAPEOUT_REL)


def _tree(root, routers):
    (root / ST.INGEST_DIR_REL).mkdir(parents=True, exist_ok=True)
    for rel in routers:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x\n", encoding="utf-8")
    return root


def _route_map():
    """`{CHIP: condition, IP: condition}` — from the fix if it is there, and
    from the PRE-FIX reading if it is not.

    Written this way on purpose. A control that raises `AttributeError` on the
    tree it is meant to falsify has observed nothing; this one makes the old
    module state its answer, and its answer is the defect.
    """
    fn = getattr(DP, "_route_conditions", None)
    if fn is not None:
        conds, why = fn()
        assert why is None, why
        return conds
    conds, why = DP._terminal_conditions()
    assert why is None, why
    return {DP.PATH_CHIP: conds[DP.STEP_CHIP], DP.PATH_IP: conds[DP.STEP_IP]}


# ---------------------------------------------------------------------------
# RED before the fix, GREEN after
# ---------------------------------------------------------------------------
def test_the_ip_condition_names_no_router_that_also_reaches_the_chip_terminal():
    """THE CAUSE, stated as a set. Every router 37.5ic accepts is a CHIP
    router; a condition that calls one of them evidence of a hardmacro
    delivery is reading a step that runs on every route."""
    pytest.importorskip("yaml")
    routes = _route_map()
    chip = set(str(f) for f in routes[DP.PATH_CHIP].get("files_exist") or [])
    ip = set(str(f) for f in routes[DP.PATH_IP].get("files_exist") or [])
    assert ip, "no router selects the IP route, so no tree can be shown to be one"
    assert not (ip & chip), (
        "these router(s) are read as evidence of BOTH a die and a hardmacro "
        f"delivery: {sorted(ip & chip)}")


@pytest.mark.parametrize("router", CHIP_ROUTERS)
def test_a_tree_carrying_one_chip_router_is_on_the_chip_path(tmp_path, router):
    """Both chip routes, because a predicate that recognised only one of them
    would let a shuttle die through -- and one that recognised neither, as the
    pre-fix module did, refuses every die on the corpus."""
    pytest.importorskip("yaml")
    r = DP.resolve(_tree(tmp_path / pathlib.Path(router).name, [router]))
    assert r["path"] == DP.PATH_CHIP, r["reason"]
    assert DP.is_tapeout_bound(r["path"])


def test_terminals_that_stop_distinguishing_are_UNREADABLE_and_say_so(
        tmp_path, monkeypatch):
    """DEGRADE LOUDLY. If the flow ever gives the two terminals the same
    router set, no route can be established from them -- and the answer must
    be the one that makes no finding, never a silent CHIP or a silent IP.

    The pre-fix module answers BOTH here, which is a statement ABOUT the tree
    ("it carries two routers") when the truth is about the FLOW.
    """
    pytest.importorskip("yaml")
    same = {"any_of": True, "files_exist": [TD.SELF_TAPEOUT_REL]}
    monkeypatch.setattr(
        DP, "_terminal_conditions",
        lambda: ({DP.STEP_CHIP: dict(same), DP.STEP_IP: dict(same)}, None))
    r = DP.resolve(_tree(tmp_path / "p", [TD.SELF_TAPEOUT_REL]))
    assert r["path"] == DP.PATH_UNREADABLE, r
    assert DP.STEP_IP in (r["reason"] or "")


# ---------------------------------------------------------------------------
# UNCHANGED in both directions -- the flow's decision, which this module follows
# ---------------------------------------------------------------------------
def _condition(step_id):
    import yaml
    doc = yaml.safe_load(
        (_PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml")
        .read_text(encoding="utf-8"))
    for step in doc["steps"]:
        if str(step.get("id")) == step_id:
            return step.get("condition") or {}
    raise AssertionError(f"step {step_id} is not in the flow")


def test_the_owner_ruling_stands_every_route_still_reaches_the_ip_terminal():
    """The route is NOT recovered by narrowing 37.5ip back to one router: a
    die that reached neither terminal's kit is the defect that ruling fixed."""
    pytest.importorskip("yaml")
    files = [str(f) for f in _condition(DP.STEP_IP).get("files_exist") or []]
    for rel in (*CHIP_ROUTER_PATTERNS, IP_ROUTER):
        assert rel in files, (rel, files)


def test_the_chip_terminal_still_excludes_the_ip_router():
    """Nor by widening 37.5ic: a pure IP has no die, so a pad ring, a seal
    ring and a tape-out precheck are questions it can never answer."""
    pytest.importorskip("yaml")
    files = [str(f) for f in _condition(DP.STEP_CHIP).get("files_exist") or []]
    assert IP_ROUTER not in files, files
