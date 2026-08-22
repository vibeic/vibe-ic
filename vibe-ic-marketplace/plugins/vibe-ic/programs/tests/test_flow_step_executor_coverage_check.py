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


# ---------------------------------------------------------------------------
# The gate above is a TEXT SEARCH over the concatenated runner sources, and it
# is blind in one direction that matters to the two steps it most recently
# stopped calling orphans.  MEASURED, not argued: with `step_pad_ring_gen` and
# `step_tapeout_docs_gen` still DEFINED in phase3_one_shot_runner but their two
# `plan.append(...)` call sites deleted, `test_real_flow_has_zero_silent_orphans`
# above reports `1 passed` — the producer names survive inside the dead function
# bodies, so `classify` still sees them and still says WIRED.
#
# That is exactly the shape 15.5ic and 37.5ic were in before they were wired:
# a declaration nothing executes.  The gate cannot tell definition from
# invocation without becoming a call-graph analysis, which is a different gate
# with a corpus-wide blast radius and is not this change's call.  What IS this
# change's call is that its own fix must have an absence that reappears, so the
# invocation is pinned here, by AST, for these two steps only.
def _phase3_runner_ast():
    src = (Path(__file__).resolve().parent.parent
           / "phase3_one_shot_runner.py").read_text(encoding="utf-8")
    import ast
    return ast.parse(src)


def _used_from(tree, caller: str):
    """Names USED anywhere inside the body of the top-level function `caller` —
    called, or passed by reference.

    A CALL IS NOT THE ONLY WAY A RUNNER DISPATCHES A STEP, and requiring one
    would break on this repo's dominant idiom. MEASURED across the seven runner
    modules: `step_gds` is never called by name anywhere in
    `phase3_one_shot_runner`; it is handed to a gate wrapper as a VALUE —

        phase3_one_shot_runner.py:41648
            step_gds, project, effective_top, pdk, args.container))

    and `design_one_shot_runner` dispatches `step_dft_lec_chain` the same way
    through `_spf.gate(...)`. A call-graph that follows only `ast.Call` marked
    282 of 789 top-level runner defs "unreachable" for exactly this reason, and
    two steps (13, 26.5ic) came out as false orphans; pairwise confirmation
    found both genuinely invoked. So this reads NAME USE, not call shape.

    It is still far stronger than the gate's own text search, which cannot
    distinguish a dead function body — or a comment — from a live reference."""
    import ast
    fn = next((n for n in tree.body
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name == caller), None)
    assert fn is not None, f"{caller}() is not a top-level function any more"
    return {n.id for n in ast.walk(fn)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}


def test_the_two_newly_wired_producers_are_invoked_and_not_merely_defined():
    # 15.5ic (pad ring) and 37.5ic (tape-out docs) were ORPHANED because their
    # declared producers were invoked from nothing but each step's own `gate:`
    # clause — the acceptance auditor writing the required_output it then reads.
    # Defining a step function does not undo that; CALLING it does.
    import ast
    tree = _phase3_runner_ast()
    defined = {n.name for n in tree.body
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    used = _used_from(tree, "main")
    for step in ("step_pad_ring_gen", "step_tapeout_docs_gen"):
        assert step in defined, f"{step}() is gone from phase3_one_shot_runner"
        assert step in used, (
            f"{step}() is defined but never used from main() — the step is "
            f"declared, the coverage gate reads its producer names out of the "
            f"dead body and says WIRED, and nothing runs it. This is the "
            f"orphan shape the wiring was supposed to end.")
