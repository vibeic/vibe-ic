"""#766 — the post-route repair analysed a DIFFERENT DESIGN, with DIFFERENT
parasitics, than the one whose number fired it.

Measured on `subservient` x `gf180mcuD` (Vibe-IC benchmark matrix, r8):

    trigger (sta_mcorner_ocv.rpt, shipped post-route design + extracted SPEF
             + propagated clock + flat-OCV derate)   setup WNS -0.09 / TNS -0.13
    repair     (postroute_timing_repair.log, post_hold.def + estimate_parasitics)
                                       [INFO RSZ-0098] No setup violations found

and a deck pointed at `pnr/routed_repaired.def` + `extracted/spef_corners/
<top>.max.spef` with `read_spef -corner ss` closed the SAME design with ONE
buffer and one pin swap (-0.09 -> +0.14 ns, TNS -0.13 -> 0.00, +0.0% area).

Every test here RUNS the emitter / audit and reads its real output; none of
them assert on this file's own source text.
"""
import json
import sys
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import postroute_timing_repair_audit  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


TOP = "subservient"
CORNER_LIBS = {"SS": "/pdk/ss.lib", "TT": "/pdk/tt.lib", "FF": "/pdk/ff.lib"}


# ---------------------------------------------------------------------------
# helpers — a project tree in the shape the flow leaves after a shipped route
# ---------------------------------------------------------------------------













# ---------------------------------------------------------------------------
# (a) the repair must repair the design the trigger number was measured on
# ---------------------------------------------------------------------------





# ---------------------------------------------------------------------------
# (b) the repair must analyse the parasitics the violation exists under
# ---------------------------------------------------------------------------













# ---------------------------------------------------------------------------
# (c) the post-repair "after" must be measured on the repair's OWN parasitics
# ---------------------------------------------------------------------------







# ---------------------------------------------------------------------------
# the silent-no-op guard
# ---------------------------------------------------------------------------

_BLIND_LOG = """\
[INFO RSZ-0058] Using max wire length 1500um.
[INFO RSZ-0098] No setup violations found
[INFO RSZ-0098] No setup violations found
"""

_SEEING_LOG = """\
[INFO RSZ-0094] Found 2 endpoints with setup violations.
[INFO RSZ-0099] Repairing 2 out of 2 (100.00%) violating endpoints...
[INFO RSZ-0040] Inserted 1 buffers.
[INFO RSZ-0043] Swapped pins on 1 instances.
"""








def _repair_project(tmp_path, log_payload):
    proj = tmp_path / "auditproj"
    repair = proj / "phase3/stage3/postroute_timing_repair"
    repair.mkdir(parents=True, exist_ok=True)
    (repair / "postroute_timing_repair_decision.json").write_text(json.dumps(
        {"repair_needed": True, "action": "timing_repair_ran"}))
    (repair / "repair_log.json").write_text(json.dumps(log_payload))
    return proj


_BASE_LOG_JSON = {
    "verdict": "REPAIR_APPLIED",
    "changes": [{"type": "multi_corner_repair_timing"}],
    "re_verified": True,
    "affected_steps": [21, 23],
    "repair_before": {"setup_worst_slack_ns": -0.09},
    "repair_after": {"setup_worst_slack_ns": -0.09},
}










def test_a_real_regression_on_a_comparable_delta_still_errors(tmp_path):
    """The #766 comparability rule must not become a way to silence the
    regression guard: a delta the runner itself called comparable still fails."""
    payload = dict(_BASE_LOG_JSON)
    payload["repair_after"] = {"setup_worst_slack_ns": -8.31}
    payload["repair_setup_delta_ns"] = -8.22
    payload["repair_delta_comparable"] = True
    findings, _ = postroute_timing_repair_audit.audit(_repair_project(tmp_path, payload))
    assert "REPAIR_REGRESSED" in [f.category for f in findings
                               if f.severity == "ERROR"]


def test_a_record_without_the_comparability_field_behaves_exactly_as_before(
        tmp_path):
    """Backward compatibility: a repair_log.json from before #766 carries no
    `repair_delta_comparable`, and a negative delta there must still be ERROR."""
    payload = dict(_BASE_LOG_JSON)
    payload["repair_after"] = {"setup_worst_slack_ns": -8.31}
    payload["repair_setup_delta_ns"] = -8.22
    findings, _ = postroute_timing_repair_audit.audit(_repair_project(tmp_path, payload))
    assert "REPAIR_REGRESSED" in [f.category for f in findings
                               if f.severity == "ERROR"]
