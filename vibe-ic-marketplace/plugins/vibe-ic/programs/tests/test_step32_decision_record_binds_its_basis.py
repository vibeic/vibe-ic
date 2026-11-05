"""Step 32: the canonical decision record is bound to the report it decided
from, so the no-repair certificate survives the status generator that
verifies it; and the derived generators' outcomes are no longer discarded.

MEASURED (IC-path gf180mcuD run, 2026-09-28, evidence copy replayed): the
canonical `postroute_timing_repair_decision.json` said `repair_needed=false`
(multi-corner OCV, setup +2.68 ns, hold +0.44 ns, action
`no_repair_needed_flag`) and canonicalize wrote `no_repair_needed.flag`. The
Step-32 status generator dispatched after it accepts a decision receipt only
when `source_report` resolves inside the project to a file whose sha256 is
`source_report_sha256` -- the receipt shape the Step-32 LibreLane producer
publishes. The canonical record carried neither field, so the generator
answered "NOT_MEASURED: Step-32 decision invalid: measured source or sha256
absent", unlinked the flag and exited 2. The runner discarded that exit and
its message; Step 32 failed with the flag "absent" while the runner's output
list still named it.

Real code paths: `step_canonicalize_artefacts` (docker faked: only the EDA
tool's report write), the shipped status generator, the shipped
`postroute_timing_repair_audit`, and `_run_derived_artefact_generators`.
chip-agnostic: synthetic project, no design names in any assertion.
"""
import hashlib
import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402

REPAIR = "phase3/stage3/postroute_timing_repair"
DECISION = f"{REPAIR}/postroute_timing_repair_decision.json"
FLAG = f"{REPAIR}/no_repair_needed.flag"
LOG = f"{REPAIR}/repair_log.json"
CANONICAL = f"{REPAIR}/postroute_timing_repair_decision.canonical.json"
STATUS_GEN = "postroute_timing_repair_status_gen.py"

PATH_MET = """\
Startpoint: a (rising edge-triggered)
Endpoint: b (rising edge-triggered)
Path Type: max
           0.47   slack (MET)
"""
EST_MET = PATH_MET + "\ntns 0.00\n"
SPEF_MET = PATH_MET + "\ntns max 0.00\nworst slack max 0.47\n"
SPEF_VIOLATED = """\
Startpoint: a (rising edge-triggered)
Endpoint: b (rising edge-triggered)
Path Type: max
         -12.27   slack (VIOLATED)

tns max -60088.21
wns max -12.27
worst slack max -12.27
"""










def test_missing_native_power_state_retires_previous_measurement(tmp_path):
    from _ppa import power

    report = tmp_path / "reports/phase3/power.rpt"
    report.parent.mkdir(parents=True)
    report.write_text("previous tool measurement\n")
    report.with_suffix(".current.json").write_text("{}")
    report.with_suffix(".json").write_text(json.dumps({
        "verdict": "PASS", "power_measurement": "MEASURED",
        "total_power_w": 0.01}))
    notes = []
    assert power.adopt_current_power_report(tmp_path, "chip_top", report, notes) is False
    assert not report.exists()
    assert not report.with_suffix(".current.json").exists()
    retired = json.loads(report.with_suffix(".json").read_text())
    assert retired["power_measurement"] == "NOT_MEASURED"
    assert retired.get("total_power_w") is None
    assert any("LL_STAPOSTPNR_STATE_ABSENT" in note for note in notes)
















# ---------------------------------------------------------------------------
# Review wave 57 (STEP32FLAG adversarial) + R-0929-STEP32-RECORD
# ---------------------------------------------------------------------------

LL_REPORT = "reports/phase3/librelane_postroute_repair.json"




def _ll_report(p: Path, *, adopted, before_drv, after_drv, setup=0.5, hold=0.2):
    """The Step-32 LibreLane producer's own report, as `run` writes it: the
    census baseline, the adopted candidate, and the adopted route's
    STAPostPNR measurement bound by its state's sha256."""
    state = p / "phase3/librelane/32-cand01/03-openroad-stapostpnr/state_out.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({"metrics": {"x": 1}}))
    digest = hashlib.sha256(state.read_bytes()).hexdigest()
    report = p / LL_REPORT
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({
        "step": "32", "mode": "librelane", "verdict": "PASS", "adopted": adopted,
        "baseline": {"drv_count": before_drv, "setup_ws_min": setup,
                     "hold_ws_min": hold},
        "final": {"drv_count": after_drv, "setup_ws_min": setup, "hold_ws_min": hold,
                  "sta_state": str(state), "sta_state_sha256": digest}}))
    return report, state






def test_decide_sees_the_step32_drv(tmp_path):
    """decide() reads the DRV Step 32 measured on the route it kept: a
    residual is a failed domain, an absent count is not a zero."""
    p = tmp_path
    _ll_report(p, adopted=None, before_drv=3, after_drv=3)
    d = R._repair_dec.decide(None, True, project=p)
    assert d["repair_needed"] is True and d["timing_repair_needed"] is False
    assert d["nontiming_failures"][0]["signal"] == "drv_count=3"
    _ll_report(p, adopted=None, before_drv=3, after_drv=None)
    d = R._repair_dec.decide(None, True, project=p)
    assert d["repair_needed"] is True
    assert d["nontiming_not_determined"][0]["domain"] == "drv"
    _ll_report(p, adopted=None, before_drv=0, after_drv=0)
    assert R._repair_dec.decide(None, True, project=p)["repair_needed"] is False








# ---------------------------------------------------------------------------
# Review wave 58 (STEP32FLAG final): behind a bound producer receipt the
# canonical decision's demands must still reach the Step-32 audit.
# ---------------------------------------------------------------------------
