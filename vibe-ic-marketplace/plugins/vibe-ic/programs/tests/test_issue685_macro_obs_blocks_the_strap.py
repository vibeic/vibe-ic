"""#685 — the PDN planner strapped a layer the macro declares blocked.

`_macro_pdn_grid_plan` built its candidate list from the macro LEF's `PIN`
entries and never read `OBS`. Measured before the fix:

    inspect.getsource(_macro_pdn_grid_plan)   "OBS" in it -> False
    inspect.getsource(_macro_pg_ports_from_lef)              -> False

So the flow would place a macro PDN strap on a metal layer the macro's own LEF
declares unroutable across its ENTIRE footprint, and no gate could see it.

THE DECIDING MEASUREMENT — same design, same core stripe list, only the macro
LEF's OBS varied:

    L4 not blocked            strap = L4
    L4 blocked full-footprint strap = L5, refused_for_blockage = ['L4']

WHAT IT DELIBERATELY DOES NOT REFUSE:

  a PARTIAL obstruction — ordinary, and a strap routes around it. Refusing
      those would reject nearly every real macro, and a rule that rejects
      everything is one that gets turned off.
  an UNDECIDABLE macro (no SIZE) — not evidence of a block. Inventing one would
      fail designs this cannot speak about, which is the absence-reads-as-a-
      finding shape, pointed the other way.
  `LAYER OVERLAP` — a LEF keyword declaring the macro's own extent, not a metal
      layer. Treating it as one would block every layer of every macro.
"""
from __future__ import annotations

import importlib.util
import pathlib
import re
import sys

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
for _p in (str(_PROGRAMS), str(_PROGRAMS / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_spec = importlib.util.spec_from_file_location(
    "phase3_one_shot_runner", _PROGRAMS / "phase3_one_shot_runner.py")
R = importlib.util.module_from_spec(_spec)
sys.modules["phase3_one_shot_runner"] = R
try:
    _spec.loader.exec_module(R)
except SystemExit:
    pass

_t = importlib.util.spec_from_file_location(
    "_pdnfix", _PROGRAMS / "tests/test_macro_pdn_grid.py")
T = importlib.util.module_from_spec(_t)
sys.modules["_pdnfix"] = T
try:
    _t.loader.exec_module(T)
except SystemExit:
    pass


def _with_obs(lef: str, layers, size=None):
    """The same macro, plus an OBS declaring `layers` blocked full-footprint."""
    name = re.search(r"MACRO\s+(\S+)", lef).group(1)
    m = re.search(r"SIZE\s+([\d.]+)\s+BY\s+([\d.]+)\s*;", lef)
    w, h = (size or (m.group(1), m.group(2)))
    body = f"  OBS\n    LAYER OVERLAP ;\n      RECT 0 0 {w} {h} ;\n"
    for L in layers:
        body += f"    LAYER {L} ;\n      RECT 0 0 {w} {h} ;\n"
    body += "  END\n"
    return lef.replace(f"END {name}", body + f"END {name}", 1)


def _plan(lef):
    return R._macro_pdn_grid_plan([lef], T.TECH_LEF, T.STRIPES, "L1")


# ── the OBS parser, on its own ────────────────────────────────────────────
def test_it_reads_blocked_layers_and_their_area():
    o = R._macro_obs_layers_from_lef(_with_obs(T.MACRO_LEF, ["L4"]))
    e = next(iter(o.values()))
    assert "L4" in e["blocked"] and e["blocked"]["L4"] > 0
    assert e["size"] is not None


def test_LAYER_OVERLAP_is_not_a_metal_layer():
    """LOAD-BEARING. OVERLAP declares the macro's placement extent. Counting it
    as a blockage would block every layer of every macro that has an OBS."""
    o = R._macro_obs_layers_from_lef(_with_obs(T.MACRO_LEF, ["L4"]))
    e = next(iter(o.values()))
    assert not any(k.upper() == "OVERLAP" for k in e["blocked"])
    assert e["overlap_area"] > 0, "and it is still recorded, just separately"


def test_a_partial_block_is_not_a_full_block():
    e = {"size": (100.0, 50.0), "blocked": {"L4": 2000.0}}   # 40 %
    assert R._layer_is_fully_blocked(e, "L4") is False


def test_an_undecidable_macro_is_None_not_False():
    """A macro whose extent is unknown is one this cannot speak about. False
    would be a claim; None is the absence of one."""
    assert R._layer_is_fully_blocked({"blocked": {"L4": 5.0}}, "L4") is None
    assert R._layer_is_fully_blocked({"size": (0, 0), "blocked": {}}, "L4") is None


# ── the planner, both directions ──────────────────────────────────────────
def test_the_baseline_plan_is_unchanged_without_an_OBS():
    """THE ACCEPT CASE: a macro with no blockage must plan exactly as before."""
    p = _plan(T.MACRO_LEF)
    assert p is not None and p["strap_layer"] == "L4"
    assert p["blocked_layers"] == [] and p["refused_for_blockage"] == []


def test_a_fully_blocked_layer_is_refused_and_NAMED():
    """The defect, and the fix, in one comparison. Naming it matters: a reader
    must be able to tell a layer that was never a candidate from one this rule
    removed."""
    p = _plan(_with_obs(T.MACRO_LEF, ["L4"]))
    assert p is not None, "refusing L4 must not refuse the whole plan"
    assert p["strap_layer"] != "L4"
    assert p["refused_for_blockage"] == ["L4"]
    assert "L4" in p["blocked_layers"]


def test_a_partially_blocked_layer_is_still_usable():
    """Half the footprint blocked is ordinary; a strap routes around it."""
    name = re.search(r"MACRO\s+(\S+)", T.MACRO_LEF).group(1)
    m = re.search(r"SIZE\s+([\d.]+)\s+BY\s+([\d.]+)\s*;", T.MACRO_LEF)
    half = f"{float(m.group(1)) / 2:.3f}"
    partial = _with_obs(T.MACRO_LEF, ["L4"], size=(half, m.group(2)))
    p = _plan(partial)
    assert p is not None and p["strap_layer"] == "L4"
    assert p["refused_for_blockage"] == []


def test_every_candidate_blocked_yields_no_plan_not_a_bad_one():
    """When nothing legal is left the answer is 'no macro grid', not a strap on
    a blocked layer. A planner that returns something rather than nothing is how
    this defect shipped."""
    p = _plan(_with_obs(T.MACRO_LEF, ["L4", "L5", "L6", "L7"]))
    assert p is None


def test_the_planner_reads_OBS_at_all():
    """The measurement the issue opened with, kept as a test: this returned
    False for both functions.

    #701 moved the planner BODY into `_macro_pdn_grid_outcome` and left
    `_macro_pdn_grid_plan` as a one-line accessor onto it, so the source of the
    entry point no longer holds the call. Follow the logic rather than the
    name: the property is "the code that plans reads OBS", and it is checked
    over the whole planning path — plus, below, behaviourally, which is the
    check a rename cannot fool."""
    import inspect
    src = (inspect.getsource(R._macro_pdn_grid_outcome)
           + inspect.getsource(R._macro_pdn_grid_plan))
    assert "_macro_obs_layers_from_lef" in src
    # and the same claim without any reference to source text at all
    assert _plan(_with_obs(T.MACRO_LEF, ["L4"]))["strap_layer"] != "L4"
    assert _plan(T.MACRO_LEF)["strap_layer"] == "L4"
