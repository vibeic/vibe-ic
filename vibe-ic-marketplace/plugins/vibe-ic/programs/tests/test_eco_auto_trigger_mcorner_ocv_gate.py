#!/usr/bin/env python3
"""TAPEOUT-SIGNOFF (ibex-surfaced) — the ECO auto-trigger must gate on the
MULTI-CORNER OCV sign-off (ss/ff process corners), not just the single-corner
(tt) post-route STA.

The gap: a large design can MEET timing at the typical (tt) corner yet carry a
huge ss setup violation (slews explode at the slow process corner: ibex tt
+6.02 ns MET, ss −88 ns VIOLATED). The old auto-trigger read only the tt STA →
wrote `no_eco_needed.flag` → the v1.2.85/86 multi-corner-aware ECO
(`_build_eco_repair_tcl` with corner_libs) NEVER fired for exactly the designs
that need it. Worse, `eco_status_gen` (a derived generator that runs AFTER
canonicalize) independently re-wrote `no_eco_needed.flag` from the single-corner
STA — a SECOND site of the same gap.

These tests pin:
  * the SHARED decision (`eco_trigger_decision.decide`) — fires on a violated ss
    corner, does NOT fire when all corners MET, single-corner honest fallback;
  * the phase3 run/measure helpers (idempotent reuse, honest no-fabrication);
  * `eco_status_gen` (the second site) does NOT clobber the flag when a real
    multi-corner violation exists.

§4.05: never SKIP an ECO when a real multi-corner violation exists; never
fabricate closure; single-corner PDK ⇒ honest tt fallback (no regression).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import eco_trigger_decision as D  # noqa: E402
import phase3_one_shot_runner as R  # noqa: E402

ECO_STATUS_GEN = PROG / "eco_status_gen.py"


# --------------------------------------------------------------------------
# 1) Shared decision — the ONE gate both no_eco_needed.flag sites consult.
# --------------------------------------------------------------------------
def _stance(*, multi=True, report="phase3/stage3/sta/sta_mcorner_ocv.rpt",
            violated=(), setup=None, hold=None):
    return {
        "signoff_dimension": "multi_corner_ocv_process",
        "setup_process_corner": "SS",
        "hold_process_corner": "FF",
        "multi_process_corner": multi,
        "report": report,
        "setup_worst_slack_ns": setup,
        "hold_worst_slack_ns": hold,
        "violated_corners": list(violated),
    }


def test_fires_on_violated_ss_corner_even_when_tt_is_clean():
    # The KEY case: single-corner tt is CLEAN, but multi-corner OCV surfaced a
    # real ss setup violation → the ECO MUST fire (eco_needed True).
    d = D.decide(_stance(violated=["setup"], setup=-88.0, hold=0.5),
                 single_corner_clean=True)
    assert d["eco_needed"] is True
    assert d["basis"] == "multi_corner_ocv"
    assert d["mc_ocv_available"] is True
    assert d["violated_corners"] == ["setup"]
    assert d["setup_worst_slack_ns"] == -88.0


def test_does_not_fire_when_all_corners_met():
    # Multi-corner OCV ran and every corner MET → no ECO needed even though the
    # single-corner tt is (also) clean.
    d = D.decide(_stance(violated=[], setup=1.2, hold=0.3),
                 single_corner_clean=True)
    assert d["eco_needed"] is False
    assert d["basis"] == "multi_corner_ocv"
    assert d["mc_ocv_available"] is True
    assert d["violated_corners"] == []


def test_multi_corner_authoritative_over_single_corner_clean_flag():
    # Even if the caller thinks tt is clean, an authoritative multi-corner
    # violation wins (this is the whole point — tt cleanliness cannot mask ss).
    d = D.decide(_stance(violated=["hold"], hold=-3.0), single_corner_clean=True)
    assert d["eco_needed"] is True
    assert d["violated_corners"] == ["hold"]


def test_single_corner_fallback_when_stance_absent():
    # No stance file (single-corner PDK / OCV not run) → honest tt fallback:
    # eco_needed = NOT single_corner_clean. No fabricated multi-corner claim.
    clean = D.decide(None, single_corner_clean=True)
    assert clean["eco_needed"] is False
    assert clean["basis"] == "single_corner_tt"
    assert clean["mc_ocv_available"] is False

    dirty = D.decide(None, single_corner_clean=False)
    assert dirty["eco_needed"] is True
    assert dirty["basis"] == "single_corner_tt"
    assert dirty["mc_ocv_available"] is False


def test_single_corner_stance_is_not_authoritative():
    # multi_process_corner False (single-corner PDK stance) → NOT authoritative;
    # decision degrades to the tt fallback (no regression).
    st = _stance(multi=False, report=None)
    assert D.decide(st, single_corner_clean=True)["eco_needed"] is False
    assert D.decide(st, single_corner_clean=False)["eco_needed"] is True
    assert D.decide(st, single_corner_clean=True)["basis"] == "single_corner_tt"


def test_multi_process_true_but_no_report_is_not_authoritative():
    # multi_process_corner claimed True but the OCV run produced NO report →
    # NOT authoritative (§4.05: no fabricated multi-corner claim).
    st = _stance(multi=True, report=None, violated=["setup"])
    d = D.decide(st, single_corner_clean=True)
    assert d["mc_ocv_available"] is False
    assert d["eco_needed"] is False  # falls back to tt-clean


def test_decide_accepts_path(tmp_path):
    p = tmp_path / "mcorner_ocv_stance.json"
    p.write_text(json.dumps(_stance(violated=["setup"], setup=-12.3)))
    d = D.decide(p, single_corner_clean=True)
    assert d["eco_needed"] is True and d["setup_worst_slack_ns"] == -12.3
    # missing path → fallback, never a crash
    assert D.decide(tmp_path / "nope.json", True)["basis"] == "single_corner_tt"


def test_decide_survives_corrupt_json(tmp_path):
    p = tmp_path / "mcorner_ocv_stance.json"
    p.write_text("{not valid json")
    d = D.decide(p, single_corner_clean=False)
    assert d["eco_needed"] is True and d["basis"] == "single_corner_tt"


# --------------------------------------------------------------------------
# 2) phase3 helpers — parse, idempotent reuse, honest no-fabrication.
# --------------------------------------------------------------------------
_OCV_RPT = (
    "=== SETUP corner: process=SS liberty, SPEF=chip.max.spef ===\n"
    "OCV_DERATE_APPLIED early=0.95 late=1.05 flat-OCV\n"
    "worst slack max -35.78\n"
    "-35.78 slack (VIOLATED)\n"
    "=== HOLD corner: process=FF liberty, SPEF=chip.min.spef ===\n"
    "OCV_DERATE_APPLIED early=0.95 late=1.05 flat-OCV\n"
    "worst slack min 0.42\n"
    "0.42 slack (MET)\n"
)


def test_parse_mcorner_ocv_slacks():
    setup, hold = R._parse_mcorner_ocv_slacks(_OCV_RPT)
    assert setup == -35.78
    assert hold == 0.42


def test_run_eco_repair_reuses_existing_netlist(tmp_path):
    # IDEMPOTENT: an existing ECO netlist is reused, NOT re-run (no docker call).
    eco = tmp_path / "phase3/stage3/eco"
    eco.mkdir(parents=True)
    (eco / "chip_top_eco.v").write_text("module chip_top; endmodule\n")
    notes = []
    assert R._run_eco_repair(tmp_path, "chip_top", "no-such-container",
                             eco / "eco_timing_repair.tcl", notes) is True
    assert any("already present" in n for n in notes)


def test_run_eco_repair_returns_false_when_tcl_missing(tmp_path):
    # No ECO netlist AND no tcl → cannot fire → False (no fabricated success).
    eco = tmp_path / "phase3/stage3/eco"
    eco.mkdir(parents=True)
    notes = []
    assert R._run_eco_repair(tmp_path, "chip_top", "no-such-container",
                             eco / "eco_timing_repair.tcl", notes) is False
    assert any("cannot fire" in n for n in notes)


def test_measure_posteco_absent_netlist_is_not_measured(tmp_path):
    # No ECO netlist → measured=False, no fabricated MET.
    out = R._measure_posteco_mcorner_ocv(
        tmp_path, "chip_top", pdk=None, container="x", corner_libs={},
        mc_spef_dir=tmp_path / "nope", nom_spef_path=None,
        sta_out=tmp_path, notes=[])
    assert out["measured"] is False
    assert out["setup_worst_slack_ns"] is None


def test_measure_posteco_parses_existing_report_without_rerun(tmp_path):
    # An existing post-ECO OCV report is parsed directly (no docker re-run), and
    # a genuine ss floor is surfaced as VIOLATED (§4.05: recover, don't fabricate).
    eco = tmp_path / "phase3/stage3/eco"
    eco.mkdir(parents=True)
    (eco / "chip_top_eco.v").write_text("module chip_top; endmodule\n")
    sta = tmp_path / "phase3/stage3/sta"
    sta.mkdir(parents=True)
    (sta / "sta_mcorner_ocv_posteco.rpt").write_text(_OCV_RPT)
    notes = []
    out = R._measure_posteco_mcorner_ocv(
        tmp_path, "chip_top", pdk=None, container="no-such-container",
        corner_libs={}, mc_spef_dir=tmp_path / "nope", nom_spef_path=None,
        sta_out=sta, notes=notes)
    assert out["measured"] is True
    assert out["setup_worst_slack_ns"] == -35.78
    assert out["violated_corners"] == ["setup"]
    assert any("STILL VIOLATED" in n for n in notes)


# --------------------------------------------------------------------------
# 3) eco_status_gen — the SECOND site must not clobber the primary decision.
# --------------------------------------------------------------------------
def _run_eco_status_gen(project: Path):
    return subprocess.run([sys.executable, str(ECO_STATUS_GEN), str(project)],
                          capture_output=True, text=True)


def _write_single_corner_sta(project: Path, met=True):
    sta = project / "phase3/stage3/sta"
    sta.mkdir(parents=True, exist_ok=True)
    body = ("Endpoint reset_n\nslack (MET)\nslack (MET)\n" if met
            else "Endpoint clk\nslack VIOLATED\n-2.0 violation\n")
    (sta / "post_route_timing.rpt").write_text(body)


def _write_stance(project: Path, **kw):
    rp = project / "reports/phase3"
    rp.mkdir(parents=True, exist_ok=True)
    (rp / "mcorner_ocv_stance.json").write_text(json.dumps(_stance(**kw)))


def test_eco_status_gen_does_not_flag_when_mcorner_violated(tmp_path):
    # tt MET but ss VIOLATED (the ibex case): eco_status_gen must NOT write
    # no_eco_needed.flag — it must write eco_log.json (ECO_REQUIRED).
    _write_single_corner_sta(tmp_path, met=True)
    _write_stance(tmp_path, violated=["setup"], setup=-88.0)
    r = _run_eco_status_gen(tmp_path)
    assert r.returncode == 0, r.stderr
    assert not (tmp_path / "phase3/stage3/eco/no_eco_needed.flag").is_file()
    assert (tmp_path / "phase3/stage3/eco/eco_log.json").is_file()
    out = json.loads(r.stdout)
    assert out["eco_trigger_basis"] == "multi_corner_ocv"
    assert out["verdict"] == "ECO_REQUIRED"


def test_eco_status_gen_flags_when_all_corners_met(tmp_path):
    # tt MET and ss MET → no_eco_needed.flag is honest.
    _write_single_corner_sta(tmp_path, met=True)
    _write_stance(tmp_path, violated=[], setup=1.5, hold=0.3)
    r = _run_eco_status_gen(tmp_path)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "phase3/stage3/eco/no_eco_needed.flag").is_file()
    out = json.loads(r.stdout)
    assert out["verdict"] == "PASS"
    assert out["eco_trigger_basis"] == "multi_corner_ocv"


def test_eco_status_gen_preserves_rich_eco_log_from_primary(tmp_path):
    # phase3 canonicalize fired the ECO and wrote a rich eco_log.json; the
    # generator must PRESERVE it (merge, #564), never clobber with the minimal.
    _write_single_corner_sta(tmp_path, met=True)
    _write_stance(tmp_path, violated=["setup"], setup=-88.0)
    eco = tmp_path / "phase3/stage3/eco"
    eco.mkdir(parents=True, exist_ok=True)
    (eco / "eco_log.json").write_text(json.dumps({
        "program": "phase3_one_shot_runner.eco_auto_trigger",
        "verdict": "ECO_APPLIED",
        "changes": [{"type": "multi_corner_repair_timing"}],
        "re_verified": True,
        "affected_steps": [21, 23, 24, 29, 30],
    }))
    r = _run_eco_status_gen(tmp_path)
    assert r.returncode == 0, r.stderr
    log = json.loads((eco / "eco_log.json").read_text())
    assert log["changes"] == [{"type": "multi_corner_repair_timing"}]
    assert log["re_verified"] is True  # preserved, not erased


def test_eco_status_gen_backward_compat_no_stance(tmp_path):
    # No stance (single-corner PDK): tt MET → flag; tt VIOLATED → eco_log.
    _write_single_corner_sta(tmp_path, met=True)
    r = _run_eco_status_gen(tmp_path)
    assert (tmp_path / "phase3/stage3/eco/no_eco_needed.flag").is_file()
    out = json.loads(r.stdout)
    assert out["eco_trigger_basis"] == "single_corner_tt"
    assert out["mc_ocv_available"] is False
