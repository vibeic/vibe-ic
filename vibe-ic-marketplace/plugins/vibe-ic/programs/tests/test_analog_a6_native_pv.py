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
