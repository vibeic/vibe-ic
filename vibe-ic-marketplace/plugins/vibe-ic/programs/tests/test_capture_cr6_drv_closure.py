"""Measured late repair and post-edit DRV ordering on a neutral design."""
from __future__ import annotations

import sys
import inspect
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import librelane_postroute_repair as P
import librelane_contract as L
from _ppa import closure
import pnr_timing_repair_completeness_check as C
import postroute_timing_repair_decision as D
import postroute_timing_repair_status_gen as S


def _sequence(body: str):
    checker = getattr(C, "drv_sequence", None)
    return checker(body) if checker else {"verdict": "NOT_MEASURED"}


def _trigger(**measurement):
    decide = getattr(P, "measured_repair_trigger", None)
    return decide(measurement) if decide else {"action": "NOT_MEASURED"}


def test_neutral_design_timing_edit_is_followed_by_drv_repair():
    deck = ("read_verilog neutral.v\nset_wire_rc -signal -layer M1\n"
            "repair_timing -setup\nrepair_design\n")
    assert _sequence(deck)["verdict"] == "PASS"
    # Reverse mutation: remove the final repair, leaving the changed netlist.
    assert _sequence(deck.replace("repair_design\n", ""))["verdict"] == "FAIL"


def test_antenna_edit_without_a_later_drv_census_is_disclosed():
    deck = ("repair_design\nrepair_timing -hold\n"
            "report_check_types -max_slew -violators\nrepair_antennas\n")
    result = _sequence(deck)
    assert result["verdict"] == "FAIL"
    assert result["last_unchecked_edit"] == "repair_antennas"
    assert _sequence(deck + "report_check_types -max_fanout -violators\n")[
        "verdict"] == "FAIL"
    assert _sequence(deck +
                     "report_check_types -max_slew -max_capacitance -violators\n"
                     "report_check_types -max_fanout -violators\n")["verdict"] == "PASS"


def test_drv_census_requires_executed_complete_three_axis_commands():
    edit = "repair_timing -setup\n"
    assert _sequence(edit + 'puts "report_check_types -max_slew -max_capacitance -max_fanout"\n')["verdict"] != "PASS"
    assert _sequence(edit + "report_check_types -max_fanout -violators\n")["verdict"] != "PASS"
    assert _sequence(edit + "# report_check_types -max_slew -max_capacitance -max_fanout\n")["verdict"] != "PASS"


def test_braced_data_does_not_clear_unchecked_drv_axes():
    edit = "repair_timing -setup\n"
    axes = "report_check_types -max_slew -max_capacitance -max_fanout"
    for data in (f"puts {{{axes}}}\n", f"set reminder {{{axes}}}\n"):
        result = _sequence(edit + data)
        assert result["verdict"] == "FAIL"
        assert result["missing_axes"] == ["max_capacitance", "max_fanout", "max_slew"]
    # The same words are a real query when catch executes them as a script.
    assert _sequence(edit + f"catch {{{axes}}}\n")["verdict"] == "PASS"
    assert _sequence(edit + f"if {{[catch {{{axes}}} err]}} {{ puts err }}\n")[
        "verdict"] == "PASS"
    assert _sequence(edit + f"if {{0}} {{{axes}}}\n")["verdict"] == "FAIL"


def test_clean_input_skips_late_repair_and_one_violation_runs():
    clean = {"setup_ws_min": 0.3, "hold_ws_min": 0.2, "drv_count": 0}
    assert _trigger(**clean)["action"] == "SKIP"
    assert _trigger(**dict(clean, drv_count=1))["action"] == "RUN"
    assert _trigger(**dict(clean, hold_ws_min=-0.01))["action"] == "RUN"
    assert _trigger(setup_ws_min=0.3, hold_ws_min=0.2)["action"] == "NOT_MEASURED"


def test_invalid_numeric_measurements_cannot_certify_clean_route():
    clean = {"setup_ws_min": 0.3, "hold_ws_min": 0.2, "drv_count": 0}
    for key, value in (("setup_ws_min", float("nan")),
                       ("hold_ws_min", float("inf")),
                       ("drv_count", -1), ("drv_count", 0.5)):
        result = _trigger(**dict(clean, **{key: value}))
        assert result["action"] == "NOT_MEASURED", (key, result)
        assert key in result["missing"]




def test_real_arm_skips_clean_input_but_runs_on_injected_violation(tmp_path,
                                                                    monkeypatch):
    config = tmp_path / "step.json"
    config.write_text("{}")
    monkeypatch.setattr(L, "derive_step_config", lambda src, out, updates: src)
    calls = []

    def registry(*_args, **_kwargs):
        calls.append("controller")
        return object()

    class Controller:
        def __init__(self, *_args):
            pass

        def run_controller(self, _cid):
            class Result:
                def to_record(self):
                    return {"iterations": []}
            return Result()

    monkeypatch.setattr(closure, "load_registry", registry)
    monkeypatch.setattr(closure, "ClosureController", Controller)
    candidate = {"setup_ws_min": 0.3, "hold_ws_min": 0.2, "drv_count": 0}
    # The mainline arm now also reads the census step's state_out metrics.
    # Supply that EDA output while _candidate is replaced by this fixture.
    (tmp_path / "state_out.json").write_text(json.dumps({"metrics": {}}))
    monkeypatch.setattr(P, "_candidate", lambda *_args: (tmp_path, dict(candidate)))

    def run(label):
        project = tmp_path / label
        state = project / "input.json"
        state.parent.mkdir()
        state.write_text("{}")
        return P.close_arm(project, "librelane", state, image="image", pdk="neutral",
                           configs={P.REPAIR_STEP: config}, corners=["tt"], mounts=[],
                           derate=(0.95, 1.05),
                           controllers=("postroute.repair_drv",))

    clean = run("clean")
    assert clean.get("repair_trigger", {}).get("action") == "SKIP"
    assert calls == []
    candidate["drv_count"] = 1
    violated = run("violated")
    assert violated.get("repair_trigger", {}).get("action") == "RUN"
    assert calls == ["controller"]


def test_missing_sta_is_not_a_measured_violation_or_a_clean_certificate():
    kw = ({"single_corner_evidence": "NOT_MEASURED"}
          if "single_corner_evidence" in inspect.signature(D.decide).parameters
          else {})
    result = D.decide(None, False, **kw)
    assert result["timing_repair_needed"] is False
    assert result["repair_needed"] is True
    assert S._parse_sta_for_violations("report header only").get(
        "timing_measurement") == "NOT_MEASURED"
    assert S._parse_sta_for_violations("tns -0.02\n")[
        "timing_measurement"] == "VIOLATED"


def test_explicit_single_corner_violation_outranks_zero_tns():
    report = "tns 0.00\nslack (VIOLATED) -0.05\n"
    parsed = S._parse_sta_for_violations(report)
    assert parsed["tns_zero"] is True
    assert parsed["timing_measurement"] == "VIOLATED"
    result = D.decide(None, parsed["tns_zero"], single_corner_evidence=parsed["timing_measurement"])
    assert result["timing_repair_needed"] is True
    assert result["repair_needed"] is True


def test_status_consumer_withholds_clean_flag_on_zero_tns_violated_path(
        tmp_path, monkeypatch):
    sta = tmp_path / "phase3/stage3/sta/sta_spef_based.rpt"
    sta.parent.mkdir(parents=True)
    sta.write_text("tns 0.00\nslack (VIOLATED) -0.05\n")
    monkeypatch.setattr(sys, "argv", ["status_gen", str(tmp_path)])
    assert S.main() == 0
    repair = tmp_path / "phase3/stage3/postroute_timing_repair"
    assert not (repair / "no_repair_needed.flag").exists()
    assert (repair / "repair_log.json").exists()


# --------------------------------------------------------------------------
# Review round 2: the Step-32 timing basis, measured on the report shape the
# runner's own `_emit_spef_sta` writes (report_checks, report_tns, report_wns,
# report_worst_slack -max, basis stamps, report_check_types -violators).
# --------------------------------------------------------------------------

import json

import postroute_timing_repair_audit as A

_SPEF_STA_MET_WITH_DRV = """\
Startpoint: _0412_ (rising edge-triggered flip-flop clocked by clk)
Endpoint: _0558_ (rising edge-triggered flip-flop clocked by clk)
Path Group: clk
Path Type: max

  Delay    Time   Description
---------------------------------------------------------
   0.00    0.00   clock clk (rise edge)
   0.41    9.24 ^ _0558_/D (neutral_dff)
           9.24   data arrival time
           9.62   data required time
---------------------------------------------------------
           9.62   data required time
          -9.24   data arrival time
---------------------------------------------------------
           0.38   slack (MET)


tns max 0.00
wns max 0.00
worst slack max 0.38
STA_BASIS: POST_ROUTE_SPEF
STA_SIGNOFF_CORNER: tt
STA_BASIS_SPEF: neutral.spef
STA_BASIS_CORNER: nom
STA_SIGNOFF_CORNER_COUNT: 1
OCV_DERATE_APPLIED early=0.95 late=1.05 flat-OCV
Group                                  Slack
--------------------------------------------
asynchronous                            1.09

max slew

Pin                                    Limit    Slew   Slack
------------------------------------------------------------
_0558_/Y                                0.75    1.23   -0.48 (VIOLATED)

SIGNOFF_CHECK_TYPES_REPORTED recovery removal max_slew min_pulse_width max_capacitance max_fanout
SIGNOFF_DRV_CENSUS_BEGIN the tool's own violator count for every check type requested above, zero included -- an absent table is silence, a count is a measurement
SIGNOFF_DRV_CENSUS max_slew violators=1
SIGNOFF_DRV_CENSUS max_fanout violators=0
SIGNOFF_DRV_CENSUS max_capacitance violators=0
"""

_VIOLATED_PATH = (_SPEF_STA_MET_WITH_DRV
                  .replace("0.38   slack (MET)", "-0.12   slack (VIOLATED)")
                  .replace("tns max 0.00", "tns max -0.12")
                  .replace("wns max 0.00", "wns max -0.12")
                  .replace("worst slack max 0.38", "worst slack max -0.12"))

_MIN_PULSE_TABLE = """\
min pulse width

                                       Required  Actual
Pin                                    Width     Width    Slack
------------------------------------------------------------
_0412_/CLK (high)                       1.30      0.90    -0.40 (VIOLATED)
"""


def _spef_sta(project: Path, text: str) -> Path:
    sta = project / "phase3/stage3/sta/sta_spef_based.rpt"
    sta.parent.mkdir(parents=True, exist_ok=True)
    sta.write_text(text)
    return project / "phase3/stage3/postroute_timing_repair"


def test_met_paths_beside_a_drv_violator_row_are_measured_clean_timing(tmp_path):
    parsed = S._parse_sta_for_violations(_SPEF_STA_MET_WITH_DRV)
    assert parsed["timing_measurement"] == "CLEAN"
    npv = parsed["non_path_violations"]
    assert npv["by_check"] == {"max_slew": 1}
    assert any("_0558_/Y" in row for row in npv["rows"])

    repair = _spef_sta(tmp_path, _SPEF_STA_MET_WITH_DRV)
    assert S.main([str(tmp_path)]) == 0
    assert not (repair / "measurement_not_available.json").exists()
    summary = json.loads((repair / "no_repair_summary.json").read_text())
    assert summary["timing_basis_status"] == "CLEAN"
    assert summary["verdict"] == "PASS"
    # The DRV row is disclosed beside the timing verdict, not folded into it.
    assert summary["non_path_violations"]["by_check"] == {"max_slew": 1}
    assert "max_slew" in (repair / "no_repair_needed.flag").read_text()


def test_the_same_report_with_a_violated_path_is_a_timing_violation(tmp_path):
    parsed = S._parse_sta_for_violations(_VIOLATED_PATH)
    assert parsed["timing_measurement"] == "VIOLATED"
    repair = _spef_sta(tmp_path, _VIOLATED_PATH)
    assert S.main([str(tmp_path)]) == 0
    log = json.loads((repair / "repair_log.json").read_text())
    assert log["verdict"] == "REPAIR_REQUIRED"
    assert log["timing_repair_needed"] is True
    assert not (repair / "no_repair_needed.flag").exists()


def test_every_timing_number_spelling_is_a_measurement():
    for text in ("tns max -1.20\n", "wns min -0.01\n", "worst slack max -0.5\n",
                 "worst slack -0.5\n", "tns -0.02\n", "  -0.05   slack (VIOLATED)\n",
                 "Group                                  Slack\n"
                 "--------------------------------------------\n"
                 "asynchronous                           -0.20 (VIOLATED)\n"):
        assert S._parse_sta_for_violations(text)["timing_measurement"] == \
            "VIOLATED", text
    for text in ("tns max 0.00\n", "worst slack max 0.38\n", "wns 0.05\n",
                 "           0.38   slack (MET)\n",
                 "Group                                  Slack\n"
                 "--------------------------------------------\n"
                 "asynchronous                            1.09\n"):
        assert S._parse_sta_for_violations(text)["timing_measurement"] == \
            "CLEAN", text


def test_drv_and_min_pulse_rows_alone_are_not_a_timing_measurement():
    drv_only = _SPEF_STA_MET_WITH_DRV[
        _SPEF_STA_MET_WITH_DRV.index("max slew"):]
    parsed = S._parse_sta_for_violations(drv_only)
    assert parsed["timing_measurement"] == "NOT_MEASURED"
    assert parsed["non_path_violations"]["by_check"] == {"max_slew": 1}
    pulse = S._parse_sta_for_violations(_MIN_PULSE_TABLE)
    assert pulse["timing_measurement"] == "NOT_MEASURED"
    assert pulse["non_path_violations"]["by_check"] == {"min_pulse_width": 1}
    measured = S._parse_sta_for_violations(
        "tns max 0.00\nworst slack max 0.20\n" + _MIN_PULSE_TABLE)
    assert measured["timing_measurement"] == "CLEAN"
    # A tagged row with no table to own it is not silently cleared.
    assert S._parse_sta_for_violations(
        "tns max 0.00\n_u1/Y  0.75  1.23  -0.48 (VIOLATED)\n")[
            "timing_measurement"] == "VIOLATED"




def test_unmeasured_timing_beside_a_failed_domain_claims_no_timing_result(tmp_path):
    result = D.decide(None, False, signoff_reports={"ir_drop": {"verdict": "FAIL"}},
                      single_corner_evidence="NOT_MEASURED")
    assert "no timing violation" not in result["reason"]
    assert "timing NOT_MEASURED" in result["reason"]
    assert "ir_drop" in result["reason"]
    # Reverse: a measured clean timing basis keeps the established wording.
    clean = D.decide(None, True, signoff_reports={"ir_drop": {"verdict": "FAIL"}},
                     single_corner_evidence="CLEAN")
    assert clean["reason"].startswith("no timing violation, but")

    repair = _spef_sta(tmp_path, "Post-route STA report header only\n")
    ir = tmp_path / "reports/phase3/ir_drop.json"
    ir.parent.mkdir(parents=True)
    ir.write_text(json.dumps({"verdict": "FAIL"}))
    assert S.main([str(tmp_path)]) == 0
    log = json.loads((repair / "repair_log.json").read_text())
    assert log["timing_basis_status"] == "NOT_MEASURED"
    assert "no timing violation" not in log["trigger_reason"]
    assert "Re-run post-route STA" in log["remediation"]
    assert "non-timing sign-off domain FAILED" in log["remediation"]
    findings, _ = A.audit(tmp_path)
    blocked = [f for f in findings
               if f.category == "REPAIR_BLOCKED_ON_NONTIMING_SIGNOFF"]
    assert len(blocked) == 1 and "ALSO NOT_MEASURED" in blocked[0].message


def test_unmeasured_repair_trigger_is_not_stamped_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "fork_capability", lambda image, docker="docker": {"capable": True})
    configs = {step: tmp_path / f"{step}.json"
               for step in (P.REPAIR_STEP, *P.MEASURE_STEPS)}
    monkeypatch.setattr(P, "_prepare", lambda project, **kw: (configs, ["tt"], []))
    monkeypatch.setattr(P, "declared_timing_floor", lambda project, sdc: {})
    trigger = {}
    measured = {"drv": {"fanout": {"tt": 0}}, "drv_count": 0, "antenna_nets": 0,
                "antenna_pins": 0, "sta_state_sha256": "0" * 64}
    monkeypatch.setattr(P, "close_arm", lambda *a, **k: {
        "repair_trigger": trigger, "closure": [], "adopted": None,
        "corners": ["tt"],
        "input_baseline": measured if trigger.get("action") == "SKIP" else {},
        "final": measured if trigger.get("action") == "SKIP" else {}})

    def chain():
        return P.run_in_chain(tmp_path, mode="librelane", image="img", pdk="pdk",
                              pdk_root=tmp_path, sdc=tmp_path / "x.sdc",
                              derate=(0.95, 1.05), route_state=tmp_path / "s.json",
                              route_drc=0)

    trigger.update(_trigger(setup_ws_min=0.3, hold_ws_min=0.2))
    report = chain()
    assert report["verdict"] == "NOT_MEASURED"
    assert report["code"] == "LL_PRR_TRIGGER_NOT_MEASURED"
    assert "drv_count" in report["reason"]
    monkeypatch.setattr(L, "state_from_direct", lambda *a, **k: tmp_path / "s.json")
    direct = P.run(tmp_path, image="img", pdk="pdk", pdk_root=tmp_path, views={},
                   sdc=tmp_path / "x.sdc", derate=(0.95, 1.05))
    assert direct["verdict"] == "NOT_MEASURED" and "drv_count" in direct["reason"]
    # Reverse: a measured clean input is a PASS that ran nothing.
    trigger.clear()
    trigger.update(_trigger(setup_ws_min=0.3, hold_ws_min=0.2, drv_count=0))
    assert chain()["verdict"] == "PASS"


def test_runner_step_row_names_why_the_closure_did_not_run(tmp_path, monkeypatch):
    import test_t102_librelane_postroute_repair as T102
    unmeasured = _trigger(setup_ws_min=0.3, hold_ws_min=0.2)

    def report_nm(project):
        return {"verdict": "PASS", "adopted": None, "baseline": {}, "final": {},
                "closure": [], "repair_trigger": unmeasured}
    runner, _project, pnr, result, _ = T102._runner_step(
        tmp_path / "nm", monkeypatch, report_nm)
    assert result.status == "NOT_MEASURED", result.detail
    assert "drv_count" in result.detail
    rec = json.loads((pnr / runner._DRV_PROMOTION_NOT_RUN).read_text())
    assert rec["not_run_stage"] == "repair_trigger_not_measured"
    assert "drv_count" in rec["reason"]

    def report_code(project):
        return {"verdict": "NOT_MEASURED", "code": "LL_PRR_TRIGGER_NOT_MEASURED",
                "reason": "x", "adopted": None, "repair_trigger": unmeasured}
    runner, _project, pnr, result, _ = T102._runner_step(
        tmp_path / "code", monkeypatch, report_code)
    rec = json.loads((pnr / runner._DRV_PROMOTION_NOT_RUN).read_text())
    assert rec["not_run_stage"] == "repair_trigger_not_measured"

    skipped = _trigger(setup_ws_min=0.3, hold_ws_min=0.2, drv_count=0)

    def report_skip(project):
        return {"verdict": "PASS", "adopted": None, "baseline": {}, "final": {},
                "closure": [], "repair_trigger": skipped}
    runner, _project, pnr, result, _ = T102._runner_step(
        tmp_path / "skip", monkeypatch, report_skip)
    assert result.status == "PASS"
    assert "SKIP" in result.detail
    rec = json.loads((pnr / runner._DRV_PROMOTION_NOT_RUN).read_text())
    assert "SKIP" in rec["reason"] and "drv_count" in rec["reason"]
    assert not rec["reason"].rstrip().endswith(":")


def test_step32_gate_names_an_unmeasured_timing_basis(tmp_path):
    repair = _spef_sta(tmp_path, "Post-route STA report header only\n")
    assert S.main([str(tmp_path)]) == 2
    record = repair / "measurement_not_available.json"
    assert record.is_file()
    findings, stats = A.audit(tmp_path)
    named = [f for f in findings if f.category == "TIMING_BASIS_NOT_MEASURED"]
    assert len(named) == 1 and named[0].severity == "ERROR"
    text = named[0].message + " " + named[0].details
    assert "phase3/stage3/sta/sta_spef_based.rpt" in text
    assert "Re-run post-route STA" in text
    assert A.build_report(findings, stats, str(tmp_path))["summary"]["pass"] is False
    # Reverse: without the record the gate can only report the generic absence.
    record.unlink()
    findings, _ = A.audit(tmp_path)
    cats = [f.category for f in findings]
    assert "NO_REPAIR_ARTIFACT" in cats
    assert "TIMING_BASIS_NOT_MEASURED" not in cats


def test_decision_module_path_helper_reads_every_timing_spelling(tmp_path):
    rpt = tmp_path / "sta.rpt"
    for text, expected in (("tns max -1.20\n", True),
                           ("worst slack max -0.5\n", True),
                           (_VIOLATED_PATH, True),
                           (_SPEF_STA_MET_WITH_DRV, False),
                           ("Post-route STA report header only\n", False)):
        rpt.write_text(text)
        assert D.post_route_timing_violation_measured(rpt) is expected, text
    assert D.post_route_timing_violation_measured(tmp_path / "absent.rpt") is False
