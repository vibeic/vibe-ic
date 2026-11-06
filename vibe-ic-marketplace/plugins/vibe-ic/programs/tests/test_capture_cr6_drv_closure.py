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








# --------------------------------------------------------------------------
# Review round 2: the Step-32 timing basis, measured on the report shape the
# runner's own `_emit_spef_sta` writes (report_checks, report_tns, report_wns,
# report_worst_slack -max, basis stamps, report_check_types -violators).
# --------------------------------------------------------------------------

import json


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
