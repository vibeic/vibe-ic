"""v0.3.26 — ORGANIC #527: SPEF-based post-route STA becomes the Step-23
canonical basis when a SPEF exists; estimate-based report_checks is fallback
only; a sign-flip / >1ns disagreement is surfaced as a named discrepancy
artifact; the repair decision (no_repair_needed.flag vs repair_log.json) gates on the
SPEF-based report.

Field round-4 evidence (reproduced for REAL in-container during this fix on
the same routed design): estimate-based slack 0.47 MET vs SPEF-based -12.27
VIOLATED — the old flow canonicalized the optimistic estimate.

NEGATIVE (#527's own no-leak clause): with NO SPEF the behavior is byte-for-
byte the pre-#527 one (estimate-based copy + MET flag).

chip-AGNOSTIC: synthetic project + fake docker; no chip literal as logic.
"""
import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402

EST_MET = """\
Startpoint: a (rising edge-triggered)
Endpoint: b (rising edge-triggered)
Path Type: max
           0.47   slack (MET)
"""

EST_MET_TNS0 = EST_MET + "\ntns 0.00\n"

SPEF_VIOLATED = """\
Startpoint: a (rising edge-triggered)
Endpoint: b (rising edge-triggered)
Path Type: max
         -12.27   slack (VIOLATED)

tns max -60088.21
wns max -12.27
worst slack max -12.27
"""


def _pdk():
    return R.PdkConfig(
        name="sky130A", liberty="/foss/pdks/x.lib", tech_lef="/t.tlef",
        cell_lef="/c.lef", cell_gds=None, site="s", drc_deck=None)


def _proj(tmp_path, est_text=EST_MET_TNS0, with_spef=True):
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / "chip_top.def").write_text("VERSION 5.8 ;\nDESIGN chip_top ;\n"
                                      "END DESIGN\n")
    (pnr / "sta.rpt").write_text(est_text)
    (pnr / "chip_top_pnr.v").write_text("module chip_top();\nendmodule\n")
    (pnr / "constraint.sdc").write_text("create_clock -period 10 [get_ports clk]\n")
    synth = tmp_path / "phase2" / "stage2" / "synth"
    synth.mkdir(parents=True)
    (synth / "chip_top_synth.v").write_text("module chip_top();\nendmodule\n")
    if with_spef:
        ext = tmp_path / "phase3" / "stage3" / "extracted"
        ext.mkdir(parents=True)
        (ext / "chip_top.spef").write_text(
            "*SPEF \"IEEE 1481-1998\"\n*DESIGN \"chip_top\"\n" + "x" * 200)
    return tmp_path


def _fake_docker(spef_sta_text):
    """Default-OK docker stub; the `sta -no_init` call writes the SPEF-based
    report at the path named in the tcl's `report_checks > <rpt>` line."""
    import re as _re

    def fake(container, cmd, timeout=0, **_):
        if "sta -no_init" in cmd:
            m = _re.search(r"-exit\s+(\S+\.tcl)", cmd)
            if m and Path(m.group(1)).is_file():
                tcl = Path(m.group(1)).read_text()
                rm = _re.search(r"report_checks > (\S+)", tcl)
                if rm:
                    Path(rm.group(1)).write_text(spef_sta_text)
            return (0, "", "")
        return (0, "", "")
    return fake


def test_worst_slack_parsing():
    assert R._worst_slack(EST_MET) == 0.47
    assert R._worst_slack(SPEF_VIOLATED) == -12.27
    assert R._worst_slack("no timing here") is None
    # worst-slack summary line alone parses too
    assert R._worst_slack("worst slack max -3.5\n") == -3.5


def test_spef_present_canonical_is_spef_based(tmp_path, monkeypatch):
    p = _proj(tmp_path)
    monkeypatch.setattr(R, "_docker_exec", _fake_docker(SPEF_VIOLATED))
    monkeypatch.setattr(R, "_to_container_path", lambda s, c: s)
    R.step_canonicalize_artefacts(p, "chip_top", _pdk(), "x")
    canon = p / "phase3/stage3/sta/post_route_timing.rpt"
    assert canon.is_file()
    body = canon.read_text()
    # SPEF-based content + explicit basis header; not the estimate copy.
    assert "SPEF-BASED" in body
    assert "VIOLATED" in body
    assert "slack (MET)" not in body.splitlines()[-1]
    # mirror staged for the acceptance grep (reports/phase3/sta*.rpt)
    assert (p / "reports/phase3/sta_spef_based.rpt").is_file()


def test_discrepancy_artifact_on_sign_flip(tmp_path, monkeypatch):
    p = _proj(tmp_path)
    monkeypatch.setattr(R, "_docker_exec", _fake_docker(SPEF_VIOLATED))
    monkeypatch.setattr(R, "_to_container_path", lambda s, c: s)
    R.step_canonicalize_artefacts(p, "chip_top", _pdk(), "x")
    disc = p / "reports/phase3/sta/spef_vs_estimate_discrepancy.json"
    assert disc.is_file()
    d = json.loads(disc.read_text())
    assert d["finding"] == "STA_BASIS_DISCREPANCY"
    assert d["sign_flip"] is True
    assert d["canonical_basis"] == "spef"
    assert d["estimate_worst_slack_ns"] == 0.47
    assert d["spef_worst_slack_ns"] == -12.27


def test_no_repair_flag_gates_on_spef_not_estimate(tmp_path, monkeypatch):
    # estimate says TNS=0 (would have written no_repair_needed.flag pre-#527);
    # SPEF says VIOLATED → the flag must NOT be written.
    p = _proj(tmp_path, est_text=EST_MET_TNS0)
    monkeypatch.setattr(R, "_docker_exec", _fake_docker(SPEF_VIOLATED))
    monkeypatch.setattr(R, "_to_container_path", lambda s, c: s)
    R.step_canonicalize_artefacts(p, "chip_top", _pdk(), "x")
    assert not (p / "phase3/stage3/postroute_timing_repair/no_repair_needed.flag").is_file()


def test_negative_no_spef_behavior_unchanged(tmp_path, monkeypatch):
    # NEGATIVE (#527): no SPEF → estimate-based copy is canonical, the MET
    # flag is written from it, and no discrepancy artifact appears.
    p = _proj(tmp_path, est_text=EST_MET_TNS0, with_spef=False)
    # docker stub: every call OK, never writes any report (extraction
    # prerequisites absent → _emit_spef returns False / writes nothing).
    monkeypatch.setattr(R, "_docker_exec", lambda c, cmd, timeout=0, **_: (1, "", ""))
    monkeypatch.setattr(R, "_to_container_path", lambda s, c: s)
    R.step_canonicalize_artefacts(p, "chip_top", _pdk(), "x")
    canon = p / "phase3/stage3/sta/post_route_timing.rpt"
    assert canon.is_file()
    assert "SPEF-BASED" not in canon.read_text()
    assert "slack (MET)" in canon.read_text()
    assert (p / "phase3/stage3/postroute_timing_repair/no_repair_needed.flag").is_file()
    assert not (p / "reports/phase3/sta/spef_vs_estimate_discrepancy.json"
                ).is_file()


def test_spef_met_design_still_gets_flag(tmp_path, monkeypatch):
    # a design MET on BOTH bases keeps its no-repair flag (the SPEF basis is
    # canonical but a clean design stays clean — no false repair trigger).
    spef_met = EST_MET + "\ntns max 0.00\nworst slack max 0.47\n"
    p = _proj(tmp_path, est_text=EST_MET_TNS0)
    monkeypatch.setattr(R, "_docker_exec", _fake_docker(spef_met))
    monkeypatch.setattr(R, "_to_container_path", lambda s, c: s)
    R.step_canonicalize_artefacts(p, "chip_top", _pdk(), "x")
    assert (p / "phase3/stage3/postroute_timing_repair/no_repair_needed.flag").is_file()
    flag = (p / "phase3/stage3/postroute_timing_repair/no_repair_needed.flag").read_text()
    assert "sta_spef_based.rpt" in flag  # Source line points at the SPEF rpt


def test_postroute_timing_repair_status_gen_prefers_spef_report(tmp_path):
    import postroute_timing_repair_status_gen as G
    p = tmp_path
    pnr = p / "phase3/stage3/pnr"
    pnr.mkdir(parents=True)
    (pnr / "sta.rpt").write_text(EST_MET_TNS0)            # estimate: MET
    sta = p / "phase3/stage3/sta"
    sta.mkdir(parents=True)
    (sta / "sta_spef_based.rpt").write_text(SPEF_VIOLATED)  # spef: VIOLATED
    rc = G.main([str(p)])
    assert rc == 0
    repair = p / "phase3/stage3/postroute_timing_repair"
    assert (repair / "repair_log.json").is_file(), \
        "SPEF-VIOLATED must drive repair_log.json even when the estimate is MET"
    assert not (repair / "no_repair_needed.flag").is_file()
    d = json.loads((repair / "repair_log.json").read_text())
    assert "sta_spef_based" in d.get("sta_source", "")
