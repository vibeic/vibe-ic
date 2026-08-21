"""v0.2.83 — flow v2.3 professional restructure (43 steps).

Pre-release flow correction (no backward-compat debt):
  * Step 14 (synthesis handoff gate) belongs to Stage 2 — it is the
    synthesis stage's closing QA, not a physical step; marked
    open-source-flow specific;
  * NEW Step 28 "PERC / Reliability sign-off" — the deterministic
    PERC-equivalent's conclusive categories (ESD ring/topology,
    latch-up well-tap, cross-domain) become an ENFORCED numbered gate
    instead of a memo; old 28-41 renumbered to 29-42;
  * NEW Step 43 "Reliability qualification (HTOL)" — long-duration
    qual distinct from the Step-42 burn-in screen, dormant until
    htol_results.json exists;
  * the env-unavailable step-name map is re-aligned to the YAML
    (it carried off-by-one legacy ids: drc→29 while PV was 30, …).

chip-AGNOSTIC: structural yaml/program assertions only.
"""
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import flow_compliance_check as F     # noqa: E402
import htol_attestation_check as HTOL  # noqa: E402
import perc_signoff_check as PERC      # noqa: E402

PLUGIN = Path(__file__).resolve().parent.parent.parent
_FLOW = yaml.safe_load(
    (PLUGIN / "flow" / "phase1_phase2_phase3.yaml").read_text())
_STEPS = {s["id"]: s for s in _FLOW["steps"] if isinstance(s, dict)}
_INT_IDS = sorted(i for i in _STEPS if isinstance(i, int))


# ── structure ───────────────────────────────────────────────────────────────

def test_flow_is_contiguous_1_to_44():
    assert _INT_IDS == list(range(1, 45)), _INT_IDS


def test_step14_is_stage2_synthesis_handoff():
    s = _STEPS[14]
    assert s["stage"] == "stage2"
    assert "handoff" in s["name"].lower()
    assert "open-source" in s["name"].lower()


def test_step28_is_perc_reliability_signoff():
    s = _STEPS[28]
    assert s["stage"] == "stage3"
    assert "PERC" in s["name"]
    assert "perc_signoff_check" in json.dumps(s.get("gate", {}))
    assert set(s["blocks_on"]) >= {24, 25, 26, 27}


def test_renumbered_steps_kept_identity():
    # spot-pins across the shifted span (incl. the Step-35 DFM insertion)
    assert "Gate-Level Simulation" in _STEPS[29]["name"]
    assert "SPICE" in _STEPS[30]["name"]
    assert "Physical" in _STEPS[31]["name"] or "DRC" in _STEPS[31]["name"]
    # v1.8.87 renamed step 32: it was labelled an ECO step, but what it runs is
    # a multi-corner repair_design + repair_timing + reroute pass, and its skill
    # moved from eco-plan to sta-review to match. The identity this line pins is
    # "step 32 is the post-route timing repair", not the old word.
    assert "timing repair" in _STEPS[32]["name"].lower()
    assert "Power" in _STEPS[33]["name"]
    assert "fill" in _STEPS[34]["name"].lower()
    assert "DFM" in _STEPS[35]["name"]
    assert "checklist" in _STEPS[36]["name"].lower()
    assert "GDS" in _STEPS[37]["name"]
    assert "Handoff" in _STEPS[38]["name"] or "handoff" in _STEPS[38]["name"]
    assert "FPGA" in _STEPS[39]["name"]
    assert "Final Test" in _STEPS[43]["name"]


def test_step35_dfm_screen():
    s = _STEPS[35]
    assert s["stage"] == "stage4"
    assert "dfm_screen_check" in json.dumps(s.get("gate", {}))
    assert s["blocks_on"] == [34]


def test_step44_htol_conditional():
    s = _STEPS[44]
    assert "HTOL" in s["name"]
    assert s["blocks_on"] == [43]
    # Step 44 stays CONDITIONAL — reliability qual is genuinely N/A for a
    # design that was never fabricated. What changed in vibe-ic#220 is WHICH
    # artefact scopes it. This used to assert the condition named
    # `htol_results.json`, which is also step 44's own required_output, so the
    # assertion pinned the self-disabling shape: missing HTOL results are the
    # defect the attestation exists to catch, and naming them in the condition
    # meant the step vanished exactly when it had something to report. The
    # scope now comes from the silicon-intake declaration that steps 40-43
    # already use, so an absent htol_results.json reaches the required_outputs
    # check and reports MISSING.
    cond = json.dumps(s.get("condition", {}))
    assert "silicon_received.json" in cond
    assert "htol_results.json" not in cond, (
        "step 44 must not be gated on its own required_output")
    assert "htol_results.json" in json.dumps(s.get("required_outputs", []))


def test_file_order_is_numeric():
    seq = [s["id"] for s in _FLOW["steps"]
           if isinstance(s, dict) and isinstance(s["id"], int)]
    assert seq == sorted(seq), "yaml physical order must follow numbering"


def test_capability_gaps_follow_renumber():
    # v1.3.94 — Steps 29 (SDF sim) + 30 (SPICE corr) were CLOSED this campaign
    # with real OSS tools (iverilog $sdf_annotate; ngspice NLDM correlation), so
    # they gate normally now and are no longer cap-gaps. 28 (PERC) is enforced.
    # v1.3.99 — 5 (formal) closed via formal_property_run: the table is EMPTY.
    assert 29 not in F._PLATFORM_CAPABILITY_GAPS
    assert 30 not in F._PLATFORM_CAPABILITY_GAPS
    assert 28 not in F._PLATFORM_CAPABILITY_GAPS  # PERC is enforced, not a gap
    assert F._PLATFORM_CAPABILITY_GAPS == {}


def test_env_map_matches_yaml():
    m = F._ENV_UNAVAILABLE_STEP_NAME_TO_ID
    assert m["physical_verification"] == 31
    assert m["ir_drop"] == 24 and m["em"] == 25
    assert m["antenna"] == 26 and m["si"] == 27
    assert m["perc"] == 28 and m["htol"] == 44
    assert m["metal_fill"] == 34 and m["dfm"] == 35
    assert m["fpga_final_signoff"] == 39
    # every mapped id must exist in the yaml
    for name, sid in m.items():
        assert sid in _STEPS, (name, sid)


# ── perc_signoff_check gate ─────────────────────────────────────────────────

def _perc(tmp_path, categories):
    d = tmp_path / "reports" / "phase3"
    d.mkdir(parents=True)
    (d / "perc_equivalent.json").write_text(json.dumps(
        {"verdict": "x", "categories": categories}))
    return tmp_path


def test_perc_conclusive_fail_blocks(tmp_path):
    _perc(tmp_path, [
        {"category": "ESD discharge topology", "status": "AUTOMATED",
         "result": "FAIL", "note": "dangling clamp on vccd/vssd"},
        {"category": "IR drop", "status": "AUTOMATED", "result": "PASS"}])
    rep = PERC.audit(tmp_path)
    assert rep["rc"] == 1 and rep["verdict"] == "FAIL"
    assert "ESD discharge topology" in rep["automated_failed"]


def test_perc_incomplete_and_manual_are_named_open_items(tmp_path):
    _perc(tmp_path, [
        {"category": "EM (electromigration)", "status": "AUTOMATED",
         "result": "INCOMPLETE"},
        {"category": "ESD clamp sizing", "status": "MANUAL_REVIEW"},
        {"category": "Antenna", "status": "AUTOMATED", "result": "PASS"}])
    rep = PERC.audit(tmp_path)
    assert rep["rc"] == 0
    assert rep["verdict"] == "PASS_WITH_OPEN_ITEMS"
    assert len(rep["open_items"]) == 2


def test_perc_all_pass(tmp_path):
    _perc(tmp_path, [
        {"category": "Antenna", "status": "AUTOMATED", "result": "PASS"}])
    rep = PERC.audit(tmp_path)
    assert rep["rc"] == 0 and rep["verdict"] == "PASS"


def test_perc_absent_is_vacuous(tmp_path):
    assert PERC.audit(tmp_path)["rc"] == 2


# ── htol_attestation_check gate ─────────────────────────────────────────────

def _htol(tmp_path, payload):
    d = tmp_path / "phase3" / "stage5_manufacturing"
    d.mkdir(parents=True)
    (d / "htol_results.json").write_text(json.dumps(payload))
    return tmp_path


def test_htol_zero_failures_passes_with_fit(tmp_path):
    _htol(tmp_path, {"units_tested": 77, "stress_hours": 1000,
                     "failures": 0, "acceleration_factor": 50})
    rep = HTOL.audit(tmp_path)
    assert rep["rc"] == 0 and rep["verdict"] == "PASS"
    assert rep["device_hours"] == 77000
    assert rep["fit_point_estimate"] is not None


def test_htol_failures_fail(tmp_path):
    _htol(tmp_path, {"units_tested": 77, "stress_hours": 1000,
                     "failures": 2})
    rep = HTOL.audit(tmp_path)
    assert rep["rc"] == 1


def test_htol_inconsistent_device_hours_fail(tmp_path):
    _htol(tmp_path, {"units_tested": 77, "stress_hours": 1000,
                     "failures": 0, "device_hours": 999999})
    rep = HTOL.audit(tmp_path)
    assert rep["rc"] == 1
    assert "DEVICE_HOURS_INCONSISTENT" in rep["reason"]


def test_htol_missing_fields_fail(tmp_path):
    _htol(tmp_path, {"note": "ran fine"})
    assert HTOL.audit(tmp_path)["rc"] == 1


def test_htol_absent_is_vacuous(tmp_path):
    assert HTOL.audit(tmp_path)["rc"] == 2
