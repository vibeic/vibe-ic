#!/usr/bin/env python3
"""Step 32 may now be told what fixing timing is allowed to COST.

THE DEFECT, MEASURED ON origin/main @ 46db018669
================================================
Step 32 repaired timing with NO area ceiling whatsoever, and a design that
declared one was ignored WITHOUT A TRACE. Run against the base revision in a
second worktree, verbatim:

    _reference_flow_pnr_mapping({"PL_RESIZER_SETUP_MAX_UTIL_PCT": "55",
                                 "PL_RESIZER_HOLD_MAX_UTIL_PCT":  "45",
                                 "RESIZER_RECOVER_POWER_PCT":     "100"})
      -> keys present for the three knobs: []
      -> notes    = []
      -> rejected = []      withheld = []
    "-max_utilization" in _post_buffered_repair_tcl(...)  -> False
    "-recover_power"  in _post_buffered_repair_tcl(...)   -> False

Not adopted, not rejected, not withheld — DROPPED. That is the shape this
repository keeps re-learning: an unmeasured thing and a measured zero produce
the same artefact. The ingest already had a vocabulary, a rejection channel and
a withholding channel; these three knobs simply were not in it.

WHAT THE TOOL ACTUALLY OFFERS, measured rather than recalled
============================================================
In the pinned image (`docker run --skip`, OpenROAD 26Q3-1535-g543c33894f):

    repair_timing [-setup] [-hold] [-recover_power percent_of_paths_with_slack]
       ... [-max_utilization util] ...
    repair_design [-max_wire_length ...] [-max_utilization util] ...

There is ONE `-max_utilization` in OpenROAD. LibreLane's
`PL_RESIZER_SETUP_MAX_UTIL_PCT` / `PL_RESIZER_HOLD_MAX_UTIL_PCT` pair is its own
FLOW-level split — the same tool flag with a different value on the `-setup` and
`-hold` calls. The port therefore lands as two flow parameters reaching two
invocations, which is what the tool supports.

NO DEFAULT IS INVENTED, and that is the load-bearing half
=========================================================
Undeclared means the deck is emitted EXACTLY as before. A ceiling nobody
declared would be a ruler fitted to the answer, and the right ceiling depends on
the die the design declared — which the flow does not get to pick either.
`test_an_undeclared_ceiling_reproduces_todays_deck_byte_for_byte` is the guard.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

import phase3_one_shot_runner as P  # noqa: E402

KNOBS = ("PL_RESIZER_SETUP_MAX_UTIL_PCT", "PL_RESIZER_HOLD_MAX_UTIL_PCT",
         "RESIZER_RECOVER_POWER_PCT")
PARAMS = ("resizer_setup_max_util_pct", "resizer_hold_max_util_pct",
          "recover_power_pct")


# ══════════════════════════════════════════════════════════════════════
# The ingest: READ, and either ADOPTED or REJECTED — never dropped
# ══════════════════════════════════════════════════════════════════════
def test_the_three_knobs_are_in_the_one_vocabulary():
    """`_ORFS_PNR_KNOB_PARAMS` is the ingest's single vocabulary; a knob that is
    not in it cannot be read, reported or rejected."""
    for k in KNOBS:
        assert k in P._ORFS_PNR_KNOB_PARAMS, f"{k} is not in the vocabulary"


def test_they_are_optimization_class_not_routing_resource_supply():
    """They BOUND area consumption inside the floorplan phase 3 chose; they do
    not replace a self-calibrated quantity, so they must not be withheld."""
    for k in KNOBS:
        assert k not in P._ORFS_WITHHELD_PNR_KNOBS


def test_a_declared_ceiling_is_adopted_and_the_audit_trail_names_its_source():
    m = P._reference_flow_pnr_mapping(
        {"PL_RESIZER_SETUP_MAX_UTIL_PCT": "55",
         "PL_RESIZER_HOLD_MAX_UTIL_PCT": "45",
         "RESIZER_RECOVER_POWER_PCT": "100"},
        {k: "input/reference_flow/config.json" for k in KNOBS})
    assert m["resizer_setup_max_util_pct"] == 55.0
    assert m["resizer_hold_max_util_pct"] == 45.0
    assert m["recover_power_pct"] == 100
    assert not m["rejected"] and not m["withheld"]
    joined = "\n".join(m["notes"])
    # A silent behaviour change in the physical flow is worse than no change:
    # every adopted knob names its value, the flag it became, and its file.
    assert "repair_timing -setup -max_utilization 55" in joined
    assert "repair_timing -hold -max_utilization 45" in joined
    assert "repair_timing -recover_power 100" in joined
    assert joined.count("input/reference_flow/config.json") == 3


@pytest.mark.parametrize("knob,bad", [
    ("PL_RESIZER_SETUP_MAX_UTIL_PCT", "140"),
    ("PL_RESIZER_SETUP_MAX_UTIL_PCT", "0"),
    ("PL_RESIZER_HOLD_MAX_UTIL_PCT", "-5"),
    ("RESIZER_RECOVER_POWER_PCT", "0"),
    ("RESIZER_RECOVER_POWER_PCT", "101"),
])
def test_an_out_of_range_declaration_is_REJECTED_not_silently_dropped(knob, bad):
    """The difference between this and main: main dropped it. A value outside
    the range must appear in `rejected` with a reason, because a declaration the
    flow ignored is exactly what nobody could see before."""
    m = P._reference_flow_pnr_mapping({knob: bad})
    assert all(m[p] is None for p in PARAMS)
    assert [j["knob"] for j in m["rejected"]] == [knob]
    assert m["rejected"][0]["reason"]


def test_nothing_declared_is_three_Nones_and_no_noise():
    m = P._reference_flow_pnr_mapping({})
    assert all(m[p] is None for p in PARAMS)
    assert not m["rejected"]


# ══════════════════════════════════════════════════════════════════════
# The emission: the flag appears only when the design declared it
# ══════════════════════════════════════════════════════════════════════
def test_an_undeclared_ceiling_reproduces_todays_deck_byte_for_byte():
    """THE GUARD ON THE WHOLE CHANGE.

    Step 32's repair deck runs on real silicon. An undeclared run must emit what it
    always emitted — not a default somebody chose.
    """
    tcl = P._post_buffered_repair_tcl("repair", "_GR", "2")
    assert "-max_utilization" not in tcl
    assert "-recover_power" not in tcl
    assert "repair_timing -setup}" in tcl
    assert "repair_timing -hold}" in tcl


def test_a_declared_ceiling_reaches_both_invocations_separately():
    tcl = P._post_buffered_repair_tcl("repair", "_GR", "2",
                                      setup_max_util_pct=55.0,
                                      hold_max_util_pct=45.0)
    assert "repair_timing -setup -max_utilization 55}" in tcl
    assert "repair_timing -hold -max_utilization 45}" in tcl
    # LibreLane's two knobs are two VALUES on one tool flag; if they collapsed
    # into one, the hold pass would inherit the setup ceiling silently.
    assert "-max_utilization 55" in tcl and "-max_utilization 45" in tcl


def test_recover_power_is_emitted_after_both_repairs():
    """It spends SURPLUS slack, so it must only see the slack that survived the
    setup and hold passes."""
    tcl = P._post_buffered_repair_tcl("repair", "_GR", "2", recover_power_pct=100)
    i_setup = tcl.index("repair_timing -setup")
    i_hold = tcl.index("repair_timing -hold")
    i_rp = tcl.index("repair_timing -recover_power 100")
    assert i_setup < i_hold < i_rp


def test_every_emitted_repair_is_catch_wrapped():
    """A resizer that refuses is a note in the log, never a dead run — the
    convention every other repair call in this file already follows."""
    tcl = P._post_buffered_repair_tcl("repair", "_GR", "2", setup_max_util_pct=55.0,
                                      hold_max_util_pct=45.0,
                                      recover_power_pct=100)
    for cmd in ("repair_timing -setup -max_utilization 55",
                "repair_timing -hold -max_utilization 45",
                "repair_timing -recover_power 100"):
        assert f"[catch {{{cmd}}}" in tcl, cmd


@pytest.mark.parametrize("bad", [None, 0, -3, 101, "x", float("nan")])
def test_a_value_the_tool_would_refuse_never_reaches_the_deck(bad):
    """Defence in depth: the ingest rejects these, and the emitter refuses them
    again. A flag OpenROAD would error on must not be constructible."""
    assert P._resizer_bound_flag(bad) == ""
    assert P._recover_power_tcl(bad, "repair", "2") == ""


def test_the_setup_ceiling_also_bounds_repair_design():
    """`repair_design` is the setup repair's own buffer/upsize preparation and
    it accepts the same flag; bounding one without the other leaves the ceiling
    reachable around the side."""
    tcl = P._build_postroute_timing_repair_tcl(
        "top", "/t.lef", "/c.lef", "/l.lib", "/pnr", "/postroute_timing_repair", "met",
        setup_max_util_pct=55.0)
    assert "repair_design -max_utilization 55" in tcl


def test_the_repair_deck_is_unchanged_when_nothing_is_declared():
    bounded = P._build_postroute_timing_repair_tcl(
        "top", "/t.lef", "/c.lef", "/l.lib", "/pnr", "/postroute_timing_repair", "met",
        setup_max_util_pct=55.0, hold_max_util_pct=45.0, recover_power_pct=100)
    plain = P._build_postroute_timing_repair_tcl(
        "top", "/t.lef", "/c.lef", "/l.lib", "/pnr", "/postroute_timing_repair", "met")
    assert "-max_utilization" not in plain
    assert "-recover_power" not in plain
    assert bounded != plain


# ══════════════════════════════════════════════════════════════════════
# The reader never raises: a project with no declaration still gets a deck
# ══════════════════════════════════════════════════════════════════════
def test_the_reader_returns_three_nones_for_a_project_with_nothing_staged(
        tmp_path):
    b = P._postroute_timing_repair_resizer_bounds(tmp_path)
    assert set(b) == {"setup_max_util_pct", "hold_max_util_pct",
                      "recover_power_pct"}
    assert all(v is None for v in b.values())


def test_the_reader_survives_an_unreadable_project(tmp_path):
    """It feeds a deck that has to be written either way; an exception here
    would turn a missing declaration into a missing repair."""
    b = P._postroute_timing_repair_resizer_bounds(tmp_path / "does-not-exist")
    assert all(v is None for v in b.values())


def test_no_process_or_vendor_token_in_the_new_code():
    src = (_HERE.parent / "phase3_one_shot_runner.py").read_text()
    for fn in ("_resizer_bound_flag", "_recover_power_tcl",
               "_postroute_timing_repair_resizer_bounds"):
        i = src.index(f"def {fn}(")
        body = src[i:src.index("\ndef ", i + 10)].lower()
        for tok in ("tsmc", "samsung", "globalfound", "umc", "smic"):
            assert tok not in body, f"{fn} names {tok!r}"
