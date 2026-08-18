"""Tests for flow_step_executor_coverage_check.classify (synthetic data only)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import flow_step_executor_coverage_check as ec  # noqa: E402


def _doc(*steps):
    return {"flow": {"steps": list(steps)}}


def _cls(rows, sid):
    return next(r["classification"] for r in rows if str(r["id"]) == str(sid))


def test_wired_when_runner_produces_output():
    doc = _doc({"id": 9, "name": "Synthesis", "stage": "stage2",
                "required_outputs": ["phase2/stage2/synth/netlist.v"],
                "mcp_tools": ["eda_synth"]})
    # runner text references the output path → WIRED
    rows = ec.classify(doc, "def step_synth(): write('phase2/stage2/synth/netlist.v')")
    assert _cls(rows, 9) == "WIRED"


def test_wired_by_mcp_tool_name():
    doc = _doc({"id": 21, "name": "Routing", "stage": "stage3",
                "required_outputs": ["pnr/routed.def"], "mcp_tools": ["eda_pnr"]})
    rows = ec.classify(doc, "result = call_eda_pnr(project)")  # tool name present
    assert _cls(rows, 21) == "WIRED"


def test_orphaned_digital_step_no_producer():
    doc = _doc({"id": 13, "name": "Equivalence check", "stage": "stage2",
                "required_outputs": ["reports/lec.rpt"],
                "programs": ["lec_equivalence_check"],
                "skills": ["equivalence-check"]})
    # nothing in the runner produces reports/lec.rpt → genuine orphan
    rows = ec.classify(doc, "def step_synth(): pass\ndef step_pnr(): pass")
    assert _cls(rows, 13) == "ORPHANED"


def test_manufacturing_is_silicon_external():
    doc = _doc({"id": 41, "name": "Wafer Sort", "stage": "stage5_manufacturing",
                "required_outputs": ["reports/mfg/wafer_sort.json"],
                "programs": ["wafer_sort_yield_check"]})
    rows = ec.classify(doc, "unrelated runner text")
    assert _cls(rows, 41) == "SILICON-EXTERNAL"


def test_mixed_signal_is_conditional_track():
    doc = _doc({"id": "M1", "name": "MS Top Integration",
                "stage": "stage_mixed_signal",
                "required_outputs": ["phase3/mixed_signal/top.gds"],
                "programs": ["mixed_signal_merge_check"]})
    rows = ec.classify(doc, "unrelated runner text")
    assert _cls(rows, "M1") == "CONDITIONAL-TRACK"


def test_skill_only_ai_step_requires_runner_waive():
    doc = _doc({"id": 1, "name": "Spec-to-RTL", "stage": "stage1",
                "required_outputs": ["phase2/stage1/rtl/top.sv"],
                "skills": ["spec-to-rtl"]})
    # legit AI-authoring handoff: the runner WAIVES to the skill (names it)
    rows = ec.classify(doc, "step_rtl_gen WAIVE fallback_skill=spec-to-rtl")
    assert _cls(rows, 1) == "SKILL-ONLY-AI"


def test_listed_skill_no_runner_waive_is_orphan():
    # A step that merely LISTS a skill no runner ever invokes is NOT a real
    # handoff — it is a silent orphan (step 12 post-DFT lists synth-doctor,
    # which appears in 0 runners).
    doc = _doc({"id": 12, "name": "Post-DFT optimization", "stage": "stage2",
                "required_outputs": ["phase2/stage2/synth/post_dft_netlist.v"],
                "skills": ["synth-doctor"]})
    rows = ec.classify(doc, "runner text that never mentions the skill")
    assert _cls(rows, 12) == "ORPHANED"


def test_generic_basename_does_not_false_wire():
    # 'coverage.json' is generic — a runner writing a DIFFERENT coverage.json
    # must NOT wire the DFT step (the real step-11 bug this gate was missing).
    doc = _doc({"id": 11, "name": "DFT insertion", "stage": "stage2",
                "required_outputs": ["reports/phase2/dft/coverage.json"],
                "mcp_tools": ["eda_dft"]})
    rows = ec.classify(doc, "write('reports/phase2/coverage/coverage.json')")
    assert _cls(rows, 11) == "ORPHANED"


def test_or_alternatives_and_glob_leaf_no_false_wire():
    # 'spice/*.sp' must not wire on the bare dir word 'spice' appearing anywhere
    # (the step-30 bug); ' OR ' alternatives are parsed as separate candidates.
    doc = _doc({"id": 30, "name": "Post-Layout SPICE", "stage": "stage3",
                "required_outputs": [
                    "phase3/stage3/spice/*.sp OR sim_spice/*.sp",
                    "phase3/stage3/spice/correlation.json"],
                "mcp_tools": ["eda_spice"]})
    # runner mentions the word 'spice' (extraction) but produces none of these
    rows = ec.classify(doc, "extracted spice netlist for lvs at extracted/top.sp")
    assert _cls(rows, 30) == "ORPHANED"


def test_disclosed_skip_is_not_orphan():
    # A step with no real producer but a conscious skip-sentinel under its
    # output dir is DISCLOSED-SKIP (honest), NOT a silent orphan.
    doc = _doc({"id": 29, "name": "Post-Layout GLS", "stage": "stage3",
                "required_outputs": [
                    "phase3/stage3/sim_postlayout/results.log OR "
                    "phase3/stage3/sim_postlayout/pass.flag"],
                "mcp_tools": ["eda_simulate"]})
    rows = ec.classify(
        doc, "skip_note = sim_pl_out / 'sim_postlayout/sdf_sim_skipped.json'")
    assert _cls(rows, 29) == "DISCLOSED-SKIP"


def test_real_flow_has_zero_silent_orphans():
    # The DFT->post-DFT->LEC chain (11/12/13) + post-layout SPICE (30) — the
    # only digital-main-track silent orphans the 6-audit convergence found — are
    # now WIRED (real executors) or DISCLOSED-SKIP (conscious skip-sentinel).
    # This locks ZERO silent orphans: any digital-main-track step whose executor
    # regresses to a silent MISSING fails here. The set must stay empty.
    import yaml
    flow = ec._DEFAULT_FLOW
    if not flow.is_file():
        return
    doc = yaml.safe_load(flow.read_text())
    rows = ec.classify(doc, ec._load_runner_text())
    orphans = {str(r["id"]) for r in rows if r["classification"] == "ORPHANED"}
    assert orphans == set(), f"silent orphan step(s) reappeared: {orphans}"
