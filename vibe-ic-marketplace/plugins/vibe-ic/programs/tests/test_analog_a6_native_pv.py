"""A6 native per-block PV producer (v1.4.27) — consume staged sign-off decks.

The producer runs native DRC (svrfdrc) + LVS (klayout_pdk_lvs) on a block when
the v1.4.24 resolver resolves the staged decks, writes the block `drc.report` /
`comp.json`, and the A6 gate (analog_a6_block_pv_check) then verdicts on that
REAL evidence. These tests inject fake engine runners (no container) to prove:
  * invocation shape — the runners receive the RESOLVED deck path + block GDS;
  * producer→gate wiring — a clean run PASSes the A6 gate;
  * honest FAIL propagation — a violating DRC / mismatched LVS FAILs A6;
  * the native path is skipped when no decks are resolved / no GDS is present.

NDA hygiene: SYNTHETIC deck / block names only; the injected runners return
NUMBERS, never real foundry deck content.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import analog_a6_native_pv as PV               # noqa: E402
import analog_a6_block_pv_check as A6           # noqa: E402


def _mk_project(tmp_path: Path, block: str = "u_ldo",
                with_gds: bool = True, with_netlist: bool = True) -> Path:
    ad = tmp_path / "phase3" / "analog"
    bdir = ad / block
    bdir.mkdir(parents=True)
    (ad / "analog_block_list.json").write_text(
        json.dumps({"blocks": [{"name": block, "type": "ldo"}]}))
    if with_gds:
        (bdir / f"{block}.gds").write_bytes(b"\x00GDSII-fake\x00" * 4)
    if with_netlist:
        (bdir / f"{block}.sp").write_text(
            f".subckt {block} vdd vss vin vout\nr1 vin vout 1k\n.ends\n")
    return tmp_path


def _res(drc="/pdk/calibre/foundry_DRC.rule",
         lvs="/pdk/calibre/foundry_LVS.rule"):
    return {"available": True, "source": "project_custom_pdk",
            "family": "foundry", "target": "MyFoundry X180",
            "drc_deck": drc, "lvs_deck": lvs}


def _a6_verdict(project: Path, block: str) -> str:
    out = project / "a6.json"
    A6.main([str(project), "--block", block, "--json", str(out)])
    return json.loads(out.read_text())["verdict"]


# ── invocation shape ────────────────────────────────────────────────────────

def test_runner_receives_resolved_deck_and_gds():
    seen = {}

    def drc_runner(deck, gds, blk, ctn):
        seen["drc"] = (deck, gds, blk, ctn)
        return 0, {"method": "svrf_native", "rules_pass": 10, "rules_skip": 1}

    def lvs_runner(gds, nl, blk, ctn):
        seen["lvs"] = (gds, nl, blk, ctn)
        return "MATCH", {"method": "klayout_pdk_lvs"}

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p = _mk_project(Path(td))
        st = PV.run_block_pv(p, "u_ldo", _res(), "vibeic-eda",
                             drc_runner=drc_runner, lvs_runner=lvs_runner)
    assert st["ran"] is True
    # DRC runner saw the RESOLVED staged deck path + the block GDS
    assert seen["drc"][0] == "/pdk/calibre/foundry_DRC.rule"
    assert seen["drc"][1].endswith("u_ldo.gds")
    assert seen["drc"][2] == "u_ldo" and seen["drc"][3] == "vibeic-eda"
    # LVS runner saw the block GDS + the block source netlist
    assert seen["lvs"][0].endswith("u_ldo.gds")
    assert seen["lvs"][1].endswith("u_ldo.sp")


# ── producer → gate wiring (clean PASS) ─────────────────────────────────────

def test_clean_run_writes_evidence_and_passes_a6(tmp_path):
    p = _mk_project(tmp_path)
    st = PV.run_block_pv(
        p, "u_ldo", _res(), "c",
        drc_runner=lambda *a: (0, {"rules_pass": 42, "rules_skip": 3}),
        lvs_runner=lambda *a: ("MATCH", {"layout_devices": {"nmos": 4}}))
    assert st["ran"] and st["drc"]["verdict"] == "PASS"
    assert st["lvs"]["verdict"] == "match"
    bdir = p / "phase3" / "analog" / "u_ldo"
    assert (bdir / "drc.report").is_file()
    assert (bdir / "comp.json").is_file()
    # the A6 gate now verdicts on the REAL evidence
    assert _a6_verdict(p, "u_ldo") == "PASS"


# ── honest FAIL propagation ─────────────────────────────────────────────────

def test_violating_drc_fails_a6(tmp_path):
    p = _mk_project(tmp_path)
    st = PV.run_block_pv(
        p, "u_ldo", _res(), "c",
        drc_runner=lambda *a: (3, {"rules_pass": 40, "rules_skip": 0}),
        lvs_runner=lambda *a: ("MATCH", {}))
    assert st["drc"]["verdict"] == "FAIL" and st["drc"]["violations"] == 3
    # the written drc.report carries the honest count → A6 FAILs
    rpt = (p / "phase3" / "analog" / "u_ldo" / "drc.report").read_text()
    assert "violations: 3" in rpt
    assert _a6_verdict(p, "u_ldo") == "FAIL"


def test_lvs_mismatch_fails_a6(tmp_path):
    p = _mk_project(tmp_path)
    PV.run_block_pv(
        p, "u_ldo", _res(), "c",
        drc_runner=lambda *a: (0, {"rules_pass": 40}),
        lvs_runner=lambda *a: ("MISMATCH", {}))
    comp = json.loads(
        (p / "phase3" / "analog" / "u_ldo" / "comp.json").read_text())
    assert comp["result"] == "mismatch"
    assert _a6_verdict(p, "u_ldo") == "FAIL"


# ── native path correctly SKIPPED (existing waiver/stub path stands) ────────

def test_no_decks_resolved_does_not_run(tmp_path):
    p = _mk_project(tmp_path)
    res = {"available": True, "source": "container_installed",
           "drc_deck": None, "lvs_deck": None}
    st = PV.run_block_pv(p, "u_ldo", res, "c",
                         drc_runner=lambda *a: (0, {}),
                         lvs_runner=lambda *a: ("MATCH", {}))
    assert st["ran"] is False
    assert not (p / "phase3" / "analog" / "u_ldo" / "drc.report").exists()
    assert not (p / "phase3" / "analog" / "u_ldo" / "comp.json").exists()


def test_no_gds_skips_execution(tmp_path):
    p = _mk_project(tmp_path, with_gds=False)
    st = PV.run_block_pv(p, "u_ldo", _res(), "c",
                         drc_runner=lambda *a: (0, {}),
                         lvs_runner=lambda *a: ("MATCH", {}))
    assert st["ran"] is False
    assert "no block GDS" in st["reason"]


def test_engine_unavailable_leaves_no_evidence(tmp_path):
    """A resolved deck but an absent engine (runner returns None) must NOT
    fabricate evidence — the block dir stays evidence-free so A6 FAILs honestly
    (rather than a false clean)."""
    p = _mk_project(tmp_path)
    st = PV.run_block_pv(
        p, "u_ldo", _res(), "c",
        drc_runner=lambda *a: (None, {"reason": "svrfdrc not on PATH"}),
        lvs_runner=lambda *a: (None, {"reason": "klayout not on PATH"}))
    assert st["ran"] is False
    bdir = p / "phase3" / "analog" / "u_ldo"
    assert not (bdir / "drc.report").exists()
    assert not (bdir / "comp.json").exists()
    assert _a6_verdict(p, "u_ldo") == "FAIL"     # no evidence → honest FAIL


# ── report hygiene (NUMBERS ONLY) ───────────────────────────────────────────

def test_drc_report_is_numbers_only(tmp_path):
    p = _mk_project(tmp_path)
    PV.run_block_pv(
        p, "u_ldo", _res(), "c",
        drc_runner=lambda *a: (2, {"rules_pass": 9, "rules_skip": 1}),
        lvs_runner=lambda *a: ("MATCH", {}))
    rpt = (p / "phase3" / "analog" / "u_ldo" / "drc.report").read_text()
    # counts present; NO staged deck path / rule names leaked into the report
    assert "violations: 2" in rpt and "rules_pass: 9" in rpt
    assert "/pdk/" not in rpt
    assert "foundry_DRC.rule" not in rpt


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))


# ── THE RULES THE SIGN-OFF DECK DOES NOT GRADE ──────────────────────────
#
# MEASURED (ihp-sg13g2, image 0.3.46, u_hawaii_adc `delta_sigma` as A5 drew
# it before v1.17.88). The staged KLayout runset grades 560 rules and reports
# 0 violations — and of the PDK's MIM.a..MIM.i family its graded set contains
# only `MIM.c` and `MIM.d`, because the shipped deck comments out its own
# `%include` of the MiM rule file. While it said "0 of 560" that block
# carried eight `Via4 cannot contact MiM cap bottom plate (MIM.i)`, every one
# of them this flow's own paint on the capacitor's plate, and magic — which
# does grade MIM.i — was the only engine in the image that could see them.
#
# Both arms below run the REAL `run_block_pv` bookkeeping over a faked
# attribution, so what is under test is the ADJUDICATION RULE and not magic.

_LYRDB = ("<report><categories>"
          "<category><name>MIM.c</name></category>"
          "<category><name>MIM.d</name></category>"
          "<category><name>M2.b</name></category>"
          "</categories></report>")

_MIM_I = "Via4 cannot contact MiM cap bottom plate (MIM.i)"
_M2_D = "Metal2 minimum area < 0.144um^2 (M2.d)"
_M2_B = "Metal2 spacing < 0.21um (M2.b)"


def _attr(layout_rules):
    return {"result": "LAYOUT_OWNS" if layout_rules else "DEVICE_ONLY",
            "by_class_and_rule": {"LAYOUT": dict(layout_rules)}}


def test_second_engine_adjudicates_a_rule_the_signoff_deck_never_grades():
    got = PV.unadjudicated_rules(_attr({_MIM_I: 8}),
                                 PV.graded_rule_ids(_LYRDB))
    assert got == {"MIM.i": 8}


def test_second_engine_defers_where_the_signoff_deck_does_grade():
    """THE CONTROL that keeps the sign-off engine the authority. Both engines
    grade M2.b; the deck says 0 and that stands. Two engines counting the
    same rule differently is a separate question and not this one."""
    assert PV.unadjudicated_rules(_attr({_M2_B: 99}),
                                 PV.graded_rule_ids(_LYRDB)) == {}


def test_second_engine_never_verdicts_the_pdks_own_cell():
    """THE OTHER CONTROL, and the one that stops this failing every block on
    this PDK. `M2.d` is ungraded by the deck too, and `ldo` carries 60
    rectangles of it — every one inside the PDK's own gencells, which is why
    the attribution puts them in a class this reader does not look at."""
    attribution = {"result": "DEVICE_ONLY",
                   "by_class_and_rule": {"DEVICE_CELL": {_M2_D: 60},
                                         "LAYOUT": {}}}
    assert PV.unadjudicated_rules(attribution, PV.graded_rule_ids(_LYRDB)) == {}


def test_a_rule_id_that_cannot_be_read_is_named_not_defaulted():
    attribution = _attr({"a message with no rule id": 3})
    assert PV.unadjudicated_rules(attribution, PV.graded_rule_ids(_LYRDB)) == {}
    assert PV.unreadable_rule_messages(attribution) == [
        "a message with no rule id"]


def test_graded_set_of_an_absent_report_claims_nothing():
    """"Could not read it" is not "read it and it was empty": an unreadable
    report grades nothing, so nothing is deferred to it."""
    assert PV.graded_rule_ids("") == set()
    assert PV.unadjudicated_rules(_attr({_M2_B: 4}), PV.graded_rule_ids("")) \
        == {"M2.b": 4}


def test_rule_id_is_the_pdks_own_token_in_either_engines_message():
    assert PV.rule_id(_MIM_I) == "MIM.i"
    assert PV.rule_id("Metal1 overlap of Via1 < 0.045um (V1.c1)") == "V1.c1"
    assert PV.rule_id("no id here") is None
