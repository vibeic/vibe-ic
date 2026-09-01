#!/usr/bin/env python3
"""The LVS arm fired on the PRESENCE of a resolved deck and then ignored it.

MEASURED. A6's LVS runner triggered whenever the resolver produced an
`lvs_deck`, and then ran a generic geometric extraction whose device
recognition is driven by a built-in EXAMPLE layer map. On the open PDK this
campaign runs, that extraction recognized nothing, the extracted netlist had no
circuit at all, and the arm died inside the container on
`'NoneType' object has no attribute 'each_device'` — reaching the caller as a
bare `rc=1`. A6 then said "no parseable LVS result — the tool has not run",
which was true, and gave no hint that a sign-off engine for that exact deck was
on PATH.

These tests pin the dispatch, and both directions of the verdict reader.
chip/PDK-AGNOSTIC.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import analog_a6_native_pv as PV  # noqa: E402
import pdk_analog_completeness_check as PAC  # noqa: E402


def test_lvs_deck_kind_keys_on_the_decks_own_extension():
    assert PV.lvs_deck_kind("/p/klayout/x.lvs") == "klayout"
    assert PV.lvs_deck_kind("/p/klayout/x.lylvs") == "klayout"
    assert PV.lvs_deck_kind("/p/netgen/x.tcl") == "netgen"
    assert PV.lvs_deck_kind("/p/calibre/x.rule") == "svrf"
    assert PV.lvs_deck_kind("/p/whatever/x.txt") == "unknown"
    assert PV.lvs_deck_kind("") == "unknown"


def test_a_klayout_lvs_runset_is_a_recognised_lvs_deck():
    """The axis listed the DRC runset an open PDK ships and not the LVS one, so
    a design that staged its PDK's own `klayout/*.lvs` had it resolved to a
    netgen setup no engine here reads — or to nothing."""
    globs = PAC._AXES["lvs_deck"]
    assert any(g.endswith("klayout/*.lvs") for g in globs), globs


def test_the_axis_also_matches_the_pdks_own_subdirectory():
    """…and the fix above was INERT on the corpus as landed: the runset was
    staged at `klayout/lvs/<pdk>.lvs`, the layout of the PDK it was copied
    from, and `klayout/*.lvs` does not match one directory down. Enumerated,
    never `**`: a recursive glob also matches the 53 `rule_decks/*.lvs`
    INCLUDE files and the resolver takes the first hit."""
    globs = PAC._AXES["lvs_deck"]
    assert any(g.endswith("klayout/lvs/*.lvs") for g in globs), globs
    assert not any("**" in g and g.endswith(".lvs") for g in globs), globs
    deep = min(i for i, g in enumerate(globs)
               if g.endswith("klayout/lvs/*.lvs"))
    flat = min(i for i, g in enumerate(globs)
               if g.endswith("klayout/*.lvs"))
    assert deep < flat, globs


def test_a_drc_deck_staged_at_its_own_depth_is_preferred():
    """A KLayout runset resolves siblings RELATIVE TO ITSELF, so a deck staged
    flat cannot find its tech-JSON and raises; staged at the depth it was
    copied from, the same deck grades 590 rules. When both are present the
    resolver must reach the one that can resolve its own includes, so the
    deeper glob comes FIRST."""
    globs = list(PAC._AXES["drc_deck"])
    deep = min(i for i, g in enumerate(globs)
               if g.endswith("klayout/tech/drc/*.drc"))
    flat = min(i for i, g in enumerate(globs)
               if g.endswith("klayout/*.drc"))
    assert deep < flat, globs


def test_the_runset_verdict_reads_both_directions_and_refuses_silence():
    assert PV.lvs_runset_verdict(
        "INFO : Congratulations! Netlists match.") == "MATCH"
    assert PV.lvs_runset_verdict(
        "ERROR : Netlists don't match") == "MISMATCH"
    # An aborted deck said NEITHER. Reading that as a verdict in either
    # direction is the false-clean this whole arm exists to avoid.
    assert PV.lvs_runset_verdict("Starting LVS ... RuntimeError") is None
    assert PV.lvs_runset_verdict("") is None


def _project(tmp_path: Path, deck_name: str) -> Path:
    p = tmp_path / "proj"
    b = p / "phase3" / "analog" / "ldo"
    b.mkdir(parents=True)
    (b / "ldo.gds").write_bytes(b"\x00" * 64)
    (b / "ldo.sp").write_text(".subckt ldo vdd vss\n.ends ldo\n")
    (p / "phase3" / "analog" / "analog_block_list.json").write_text(
        json.dumps({"blocks": ["ldo"]}))
    deck = p / "deck" / deck_name
    deck.parent.mkdir(parents=True)
    deck.write_text("# deck\n")
    return p


def test_the_deck_extension_chooses_the_engine_with_no_runner_injected(
        tmp_path: Path, monkeypatch):
    """The discriminating case: NOTHING is injected, so the choice is the
    dispatch itself. Before the fix a `.lvs` deck reached the geometric
    extractor, which is the engine that cannot read it."""
    called = []
    monkeypatch.setattr(PV, "_klayout_lvs_runset_runner",
                        lambda *a, **k: (called.append("runset"), ("MATCH", {}))[1])
    monkeypatch.setattr(PV, "_default_lvs_runner",
                        lambda *a, **k: (called.append("generic"), ("MATCH", {}))[1])

    p = _project(tmp_path, "sg.lvs")
    PV.run_block_pv(p, "ldo", {"drc_deck": None,
                               "lvs_deck": str(p / "deck" / "sg.lvs")})
    assert called == ["runset"], called

    q = _project(tmp_path / "two", "setup.tcl")
    called.clear()
    PV.run_block_pv(q, "ldo", {"drc_deck": None,
                               "lvs_deck": str(q / "deck" / "setup.tcl")})
    assert called == ["generic"], called


def test_a_klayout_lvs_deck_reaches_the_runset_engine(tmp_path: Path):
    p = _project(tmp_path, "sg.lvs")
    seen = {}

    def runner(gds, nl, blk, ctn):
        seen["called"] = True
        return "MATCH", {"method": "klayout_lvs_runset"}

    res = PV.run_block_pv(p, "ldo",
                          {"drc_deck": None,
                           "lvs_deck": str(p / "deck" / "sg.lvs")},
                          lvs_runner=runner)
    assert seen.get("called")
    assert res["lvs"]["verdict"] == "match"
    comp = json.loads((p / "phase3" / "analog" / "ldo" / "comp.json").read_text())
    assert comp["result"] == "match"


def test_a_mismatch_is_carried_through_as_a_mismatch(tmp_path: Path):
    """NO WAIVER. The arm must be able to say no — this is the direction that
    makes the PASS direction worth anything."""
    p = _project(tmp_path, "sg.lvs")
    res = PV.run_block_pv(p, "ldo",
                          {"drc_deck": None,
                           "lvs_deck": str(p / "deck" / "sg.lvs")},
                          lvs_runner=lambda *a: ("MISMATCH", {}))
    assert res["lvs"]["verdict"] == "mismatch"
    comp = json.loads((p / "phase3" / "analog" / "ldo" / "comp.json").read_text())
    assert comp["result"] == "mismatch"


def test_an_engine_that_could_not_run_writes_no_verdict(tmp_path: Path):
    p = _project(tmp_path, "sg.lvs")
    res = PV.run_block_pv(p, "ldo",
                          {"drc_deck": None,
                           "lvs_deck": str(p / "deck" / "sg.lvs")},
                          lvs_runner=lambda *a: (None, {"reason": "no klayout"}))
    assert res["lvs"] is None
    assert not (p / "phase3" / "analog" / "ldo" / "comp.json").exists()
