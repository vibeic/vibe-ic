"""vibe-ic#220 — the self-disabling-condition guard.

Pins the distinction that makes the sweep non-trivial: a condition that scopes
a step to a DESIGN SHAPE is legitimate, while a condition whose false branch
coincides with the FAILURE MODE is the defect. A guard that could not tell them
apart would strip every legitimately-scoped step and be worse than the bug, so
both directions are pinned here — holes are caught AND correct scoping is left
alone.
"""
import sys
from pathlib import Path

import pytest  # noqa: F401

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import flow_condition_reachability_check as R  # noqa: E402

_FLOW = (Path(__file__).resolve().parent.parent.parent
         / "flow" / "phase1_phase2_phase3.yaml")


def _write(tmp_path, doc):
    import yaml
    tmp_path.mkdir(parents=True, exist_ok=True)
    p = tmp_path / "flow.yaml"
    p.write_text(yaml.safe_dump(doc))
    return p


def _verdicts(path):
    return {(r["step"], r["program"]): r["verdict"] for r in R.classify(path)}


# --------------------------------------------------------------- the corpus
def test_canonical_flow_has_no_unbaselined_holes():
    """The shipped flow must carry no self-disabling condition that is not
    explicitly listed as known-open in the baseline."""
    import json
    holes = [r for r in R.classify(_FLOW) if r["verdict"] == "self-disabling"]
    baseline = json.loads(
        (_FLOW.parent / "flow_condition_reachability_baseline.json").read_text()
    )["holes"]

    def key(step, program, paths):
        return (str(step), program or None, tuple(sorted(map(str, paths))))

    known = {key(b["step"], b.get("program"), b["paths"]) for b in baseline}
    unlisted = [h for h in holes
                if key(h["step"], h["program"], h["paths"]) not in known]
    assert unlisted == [], f"new self-disabling condition(s): {unlisted}"


def test_baseline_has_no_stale_entries():
    """A fix must delete its baseline entry, or the file rots into a permanent
    excuse that outlives the defect it described."""
    import json
    holes = R.classify(_FLOW)
    hole_keys = {(h["step"], h["program"], tuple(sorted(h["paths"])))
                 for h in holes if h["verdict"] == "self-disabling"}
    baseline = json.loads(
        (_FLOW.parent / "flow_condition_reachability_baseline.json").read_text()
    )["holes"]
    for b in baseline:
        k = (str(b["step"]), b.get("program") or None,
             tuple(sorted(map(str, b["paths"]))))
        assert k in hole_keys, (
            f"baseline entry {k} is no longer a hole — delete it")


# ------------------------------------------------------- the defect is caught
def test_step_gated_on_its_own_required_output_is_flagged(tmp_path):
    """R1 self-gate — Step 44's shape: the trigger IS the required output."""
    doc = {"steps": [{
        "id": 99, "name": "Reliability qual",
        "condition": {"files_exist": ["mfg/htol_results.json"]},
        "required_outputs": ["mfg/htol_results.json", "mfg/other.json"],
        "gate": {"program_exit_zero": "htol_attestation_check ."},
    }]}
    assert _verdicts(_write(tmp_path, doc))[("99", None)] == "self-disabling"


def test_predicate_gated_on_the_artefact_it_audits_is_flagged(tmp_path):
    """Instance 1's shape: an optional checker gated on its own subject."""
    doc = {"steps": [{
        "id": 23, "name": "Post-route STA",
        "required_outputs": ["sta/post_route_timing.rpt"],
        "gate": {"all_of": [{"optional_program_exit_zero": {
            "command": "post_route_signoff_corner_check . --json x.json",
            "condition_files_exist": ["sta/sta_spef_multicorner.rpt"]}}]},
    }]}
    assert _verdicts(_write(tmp_path, doc))[("23", "post_route_signoff_corner_check")] \
        == "self-disabling"


def test_all_of_condition_flagged_when_any_single_path_is_the_subject(tmp_path):
    """DT2's shape. A step-level condition without `any_of` is ALL-of, so ONE
    self-disabling path disarms the whole step — a surviving sibling trigger
    does NOT rescue it. This is the case a naive any-path-survives rule misses.
    """
    doc = {"steps": [{
        "id": "DT2", "name": "Path-delay ATPG",
        "condition": {"files_exist": ["input/pdk/cells.lib",
                                      "dft/cut_netlist.v"]},
        "gate": {"program_exit_zero": "path_delay_coverage_check ."},
    }]}
    # `input/**` survives (T1) but `dft/cut_netlist.v` does not, and ALL-of
    # semantics mean the step still vanishes when the cut netlist is missing.
    assert _verdicts(_write(tmp_path, doc))[("DT2", None)] == "self-disabling"


# --------------------------------------------- legitimate scoping is left alone
def test_declaration_trigger_is_legitimate_scoping(tmp_path):
    """T1 — 'skip the analog gate on a purely digital design' must NOT flag."""
    doc = {"steps": [{
        "id": "A3", "name": "Analog netlist generation",
        "condition": {"files_exist": ["phase1/analog/analog_block_list.json"]},
        "required_outputs": ["phase2/analog/x.sp"],
        "gate": {"program_exit_zero": "analog_check ."},
    }]}
    assert _verdicts(_write(tmp_path, doc))[("A3", None)] == "legitimate-scoping"


def test_not_run_disclosure_makes_a_condition_reachable(tmp_path):
    """T2 — the #219 shape: a not-run record can itself trigger the step, so
    an unrunnable step reports BLOCKED instead of disappearing."""
    doc = {"steps": [{
        "id": "DT1", "name": "Transition ATPG",
        "condition": {"any_of": True,
                      "files_exist": ["dft/cut_netlist.v",
                                      "dft/transition_atpg_not_run.json"]},
        "gate": {"program_exit_zero": "transition_coverage_check ."},
    }]}
    assert _verdicts(_write(tmp_path, doc))[("DT1", None)] == "legitimate-scoping"


def test_hard_files_exist_in_same_step_exonerates(tmp_path):
    """T4 — Step 18's shape. A hard `files_exist` on the same path already
    FAILs the step, so the conditioned checker hides nothing and must not be
    reported as a hole."""
    doc = {"steps": [{
        "id": 18, "name": "Spare-cell insertion",
        "required_outputs": ["pnr/spare_cells.json", "reports/spare.json"],
        "gate": {"all_of": [
            {"files_exist": ["pnr/spare_cells.json"]},
            {"optional_program_exit_zero": {
                "command": "spare_cell_coverage_check . --json x.json",
                "condition_files_exist": ["pnr/spare_cells.json"]}}]},
    }]}
    assert _verdicts(_write(tmp_path, doc))[("18", "spare_cell_coverage_check")] \
        == "legitimate-scoping"


def test_source_directory_trigger_is_scoping_not_a_hole(tmp_path):
    """T5 — lints gated on `phase2/stage1/rtl` judge the CONTENT's quality; the
    directory only vanishes when the step that fills it produced nothing, and
    that step goes MISSING on its own required_outputs."""
    doc = {"steps": [
        {"id": 3, "name": "RTL gen",
         "required_outputs": ["phase2/stage1/rtl/top.v"], "gate": {}},
        {"id": 2, "name": "Lint",
         "required_outputs": ["reports/lint.json"],
         "gate": {"all_of": [{"optional_program_exit_zero": {
             "command": "nba_addr_read_race_check . --json x.json",
             "condition_files_exist": ["phase2/stage1/rtl"]}}]}},
    ]}
    assert _verdicts(_write(tmp_path, doc))[("2", "nba_addr_read_race_check")] \
        == "legitimate-scoping"


def test_cross_step_hard_gate_exonerates(tmp_path):
    """T7 — Step 34's spare-cell PRESERVATION check is gated on a file Step 18
    already hard-requires, so the absence is loud somewhere."""
    doc = {"steps": [
        {"id": 18, "name": "Spare-cell insertion",
         "required_outputs": ["pnr/spare_cells.json"],
         "gate": {"all_of": [{"files_exist": ["pnr/spare_cells.json"]}]}},
        {"id": 34, "name": "Metal fill",
         "required_outputs": ["pnr/filled.def"],
         "gate": {"all_of": [{"optional_program_exit_zero": {
             "command": "spare_cell_preservation_check . --json x.json",
             "condition_files_exist": ["pnr/spare_cells.json"]}}]}},
    ]}
    assert _verdicts(_write(tmp_path, doc))[("34", "spare_cell_preservation_check")] \
        == "legitimate-scoping"


def test_step_vs_predicate_own_output_are_judged_differently(tmp_path):
    """The ordering rule, pinned. `check_step` evaluates the step-level
    `condition` (flow_compliance_check.py:5598) and returns SKIPPED-CONDITION
    at :5617 BEFORE the required_outputs check at :5651 — so a STEP gated on
    its own sole required_output never reaches the MISSING path and IS a hole
    (Step 44 / HTOL). A PREDICATE condition lives inside the gate, which runs
    after :5651, so there required_outputs really does fire first and the same
    shape is safe. Getting this backwards silently clears the textbook case.
    """
    step_level = {"steps": [{
        "id": 44, "name": "Reliability qual",
        "condition": {"files_exist": ["mfg/htol_results.json"]},
        "required_outputs": ["mfg/htol_results.json"],
        "gate": {"program_exit_zero": "htol_attestation_check ."},
    }]}
    assert _verdicts(_write(tmp_path / "a", step_level))[("44", None)] \
        == "self-disabling"

    predicate = {"steps": [{
        "id": 45, "name": "Some step",
        "required_outputs": ["reports/thing.json"],
        "gate": {"all_of": [{"optional_program_exit_zero": {
            "command": "thing_check . --json x.json",
            "condition_files_exist": ["reports/thing.json"]}}]},
    }]}
    assert _verdicts(_write(tmp_path / "b", predicate))[("45", "thing_check")] \
        == "legitimate-scoping"


# ------------------------------------------------------------------- plumbing
def test_plugin_directory_argument_resolves(tmp_path):
    """A guard invoked with the plugin dir (as plugin_full_audit does) must
    RUN. Answering that call with 'cannot find the flow' is the same
    self-disabling shape one level up."""
    plugin = tmp_path / "plug"
    (plugin / "flow").mkdir(parents=True)
    (plugin / "flow" / "phase1_phase2_phase3.yaml").write_text(
        "steps: [{id: 1, name: x, gate: {}}]\n")
    assert R._resolve_flow_yaml(str(plugin)).is_file()


def test_exit_code_is_1_on_a_new_hole(tmp_path):
    doc = {"steps": [{
        "id": 99, "name": "Bogus",
        "condition": {"files_exist": ["reports/thing.json"]},
        "required_outputs": ["reports/thing.json", "reports/other.json"],
        "gate": {"program_exit_zero": "thing_check ."},
    }]}
    p = _write(tmp_path, doc)
    assert R.main([str(p), "--baseline", ""]) == 1
