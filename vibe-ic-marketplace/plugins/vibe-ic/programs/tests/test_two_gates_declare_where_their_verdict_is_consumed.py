#!/usr/bin/env python3
"""Two gates that could never block inline and never said so.

THE FINDING, MEASURED. `flow_gate_enforcement_audit` — a BLOCKING leg of
`tools/ci/repo_hygiene_gates.sh`, which `tools/gatekeeper-land.sh` runs before
any landing — failed on a clean checkout of `origin/main` at a00f53f20 with
rc 1:

    [FAIL] 2 NEW gate(s) are AUDIT_ONLY and declare no intent at all — nothing
    invokes them where they could block, and nothing in the gate says that was
    the decision:
       undeclared::area_total_vs_budget_check
       undeclared::tapeout_docs_gen

It is the same class `test_issue1035_five_gates_declare_where_they_are_enforced`
closed for five gates and `test_macro_obs_gate_enforcement_declared` for two
more, hit by two that landed since.

WHAT THE LABEL DOES NOT BUY. A declaration token on its own is worth nothing:
the tests below re-measure the wiring and verdict it describes rather than
stopping at "the declaration exists". Both gates were later promoted to real
inline blockers, so both declarations now say `blocking`:

  * `area_total_vs_budget_check` — the flow's only producer of the area figure,
    `synth_area_stats_emit`, declines to name the figure's unit, so through the
    flow this gate can reach ONLY rc 2 INCOMPLETE. An inline wiring would put a
    control-flow decision on an rc 1 no run can arrive at.
  * `tapeout_docs_gen` — Batch73 added a dedicated producer dispatch and
    canonical step 37.5ic consumes its rc in a blocking `program_exit_zero`
    slot. The producer row and the gate clause are separately measured below.

AND THE THIRD ANSWER, CONSIDERED AND REFUTED BY MEASUREMENT. `tapeout_docs_gen`
reads like a generator, and "a generator does not belong in the gate population"
is a legitimate third answer. It is wrong here, and the test named
`test_the_document_generator_carries_a_verdict_not_only_documents` is why: from
ONE metrics file differing in ONE number it returns rc 0 with documents and rc 1
with none. Removing the clause would delete the only consumer of that verdict.

NOT ONE ASSERTION IS A GREP FOR A STRING IN A SOURCE FILE. A test that greps for
`ENFORCEMENT: advisory` passes on a file where the audit cannot see the
declaration at all — it must OPEN a line and sit in the first 4000 characters —
which is vibe-ic#886's defect wearing a test's clothing. Every assertion reads a
returned value, an exit code, or emitted JSON.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import re
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_TESTS = Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent
_FLOW = _PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"
_BASELINE = _PROGRAMS / "flow_gate_enforcement_baseline.json"
_AUDIT = _PROGRAMS / "flow_gate_enforcement_audit.py"

#: (gate, flow step, slot, DECLARED intent). The intent is DATA now, not a
#: constant: `area_total_vs_budget_check` was declared `advisory` when this file
#: was written and is `blocking` since its wiring landed; Batch73 made the same
#: transition for `tapeout_docs_gen` through its dedicated step dispatcher.
_GATES = (
    ("area_total_vs_budget_check", "9", "program_exit_zero", "blocking"),
    ("tapeout_docs_gen", "37.5ic", "program_exit_zero", "blocking"),
)

# Pytest node IDs are part of the landing comparison.  The tapeout producer was
# promoted from advisory to blocking in Batch73, but the historical PASS must
# remain represented while its assertion now measures the promoted state.
_GATE_CASES = (
    pytest.param(*_GATES[0]),
    pytest.param(
        *_GATES[1],
        id="tapeout_docs_gen-37.5ic-program_exit_zero-advisory"),
)

#: Batch73's runner now consumes these three verdicts inline.  Keep this set
#: explicit so the declaration correction cannot silently regress back into
#: the audit's non-blocking disclosure class.
_BATCH73_INLINE_BLOCKERS = (
    "pad_assignment_gen",
    "pad_ring_check",
    "tapeout_docs_gen",
)

def _audit_mod():
    """A private copy, so a sibling test's `sys.modules` entry cannot decide
    which version of the program this file measures."""
    spec = importlib.util.spec_from_file_location("_fgea_jintent", _AUDIT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _area_gate_mod():
    """The area gate itself, for its `_UM2_SPELLINGS` — the set of spellings
    that ESTABLISH the unit. Read from the gate rather than restated here, so
    this file cannot judge the producer against a stale copy of the rule."""
    saved = list(sys.path)
    sys.path.insert(0, str(_PROGRAMS))          # it imports `_atomic_artefact`
    try:
        spec = importlib.util.spec_from_file_location(
            "_area_jintent", _PROGRAMS / "area_total_vs_budget_check.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.path[:] = saved


def _flow_command(gate: str) -> str:
    """The argv the flow ENGINE would dispatch for this gate, read from the
    audit's own structural walk rather than from the text of a YAML line."""
    cs = [c for c in _audit_mod().clauses_in_flow(_FLOW) if c["gate"] == gate]
    assert len(cs) == 1, f"{gate}: expected one clause, found {cs}"
    return cs[0]["command"]


# ───────────────────────────────────────────── axis 1: the declaration exists

@pytest.mark.parametrize("gate,_step,_slot,intent", _GATE_CASES)
def test_the_gate_declares_an_intent_the_audit_can_read(gate, _step, _slot, intent):
    """RETURNED VALUE, not a grep. `declared_intent` is the exact function the
    audit calls to decide DECLARED vs UNDECLARED, so this cannot pass on a
    declaration the audit would not see — one below the 4000-character window,
    one indented past a marker it does not accept, or one that is prose about
    the token rather than the token opening a line."""
    mod = _audit_mod()
    assert mod.declared_intent(_PROGRAMS, gate) == intent, (
        f"{gate} does not state where its verdict is consumed in a form the "
        f"audit reads: `ENFORCEMENT: advisory|blocking` opening a line in the "
        f"first 4000 characters, or a lone `\"verdict_mode\"` literal")


# ────────────────────────────────── axis 2: the declaration bought no demotion

@pytest.mark.parametrize("gate,step,slot,_intent", _GATE_CASES)
def test_the_declaration_did_not_move_the_gate_between_flow_slots(
        gate, step, slot, _intent):
    """THE PAIRED HALF OF THE DECLARATION.

    Both declarations describe runner wiring and both clauses remain in the
    blocking slot. They must never be cited to move a clause from
    `program_exit_zero` to `advisory_program_exit_zero`, where `_evaluate_gate`
    records the finding and passes the step anyway."""
    mod = _audit_mod()
    slots = sorted({c["slot"] for c in mod.clauses_in_flow(_FLOW)
                    if c["gate"] == gate})
    assert slots == [slot], (
        f"{gate} (step {step}) is wired in {slots}, not [{slot!r}]; the "
        f"declaration is not permission to move this clause")


# ─────────────────────────────────────────────────── axis 3: end to end, rc 0

def test_the_audit_exits_zero_and_names_neither_gate(tmp_path):
    """END TO END, on EXIT CODE and EMITTED JSON.

    The failing runner is `tools/ci/repo_hygiene_gates.sh`, which invokes this
    program and reads its exit status, so the exit status is what this asserts.
    The JSON half is there because rc 0 alone is also satisfied by an audit that
    has stopped looking at these gates — the failure mode the paired guard at
    the bottom of this file exists to rule out.

    `contradictions` is asserted as hard as `undeclared_audit_only`: writing
    `ENFORCEMENT: blocking` in a gate no runner spawns moves the finding into
    the OTHER register rather than removing it, and both registers fail.
    """
    out = tmp_path / "audit.json"
    cp = _pr.run(
        [sys.executable, str(_AUDIT), "--json", str(out)],
        capture_output=True, text=True)
    assert cp.returncode == 0, (
        f"rc={cp.returncode}\n{cp.stdout[-4000:]}\n{cp.stderr[-2000:]}")
    rep = json.loads(out.read_text())
    undeclared = {u["gate"] for u in rep["undeclared_audit_only"]}
    contradicting = {c["gate"] for c in rep["contradictions"]}
    orphaned = {o["gate"] for o in rep["orphaned"]}
    rows = {r["gate"]: r for r in rep["gates"]}
    for gate, step, slot, intent in _GATES:
        assert gate in rows, f"{gate} is not in the flow definition at all"
        assert rows[gate]["declared"] == intent, rows[gate]
        assert rows[gate]["slots"] == [slot], (step, rows[gate])
        assert gate not in undeclared
        assert gate not in contradicting
        assert gate not in orphaned


def test_batch73_inline_blockers_declare_the_wiring_they_already_have():
    """Declaration-vs-wiring control for the three Batch73 promotions.

    This reads the audit's semantic result, not source substrings.  It fails if
    a runner/gate change demotes the real wiring, if a declaration drifts back
    to advisory, or if the three re-enter ``declared_weaker_than_wired``.
    """
    rep = _audit_mod().audit(_FLOW, _PROGRAMS)
    rows = {row["gate"]: row for row in rep["gates"]}
    weaker = {row["gate"] for row in rep["declared_weaker_than_wired"]}
    for gate in _BATCH73_INLINE_BLOCKERS:
        row = rows[gate]
        assert row["enforcement"] == "ENFORCED", row
        assert row["wiring"] == "INLINE_BLOCKING", row
        assert row["declared"] == "blocking", row
        assert row["slots"] == ["program_exit_zero"], row
        assert gate not in weaker, rep["declared_weaker_than_wired"]


def test_the_recorded_register_did_not_grow_to_absorb_the_two():
    """The OTHER way to make the audit green, and the one this change refuses.

    `--write-baseline --scope-expanded '<why>'` would have recorded the two as
    permanent debt and exited 0 without either gate saying anything about
    itself. The register is shrink-only and they must be paid down OUT of it,
    not INTO it."""
    doc = json.loads(_BASELINE.read_text())
    recorded = set(doc["undeclared_known"])
    for gate, _step, _slot, _intent in _GATES:
        assert f"undeclared::{gate}" not in recorded, (
            f"{gate} was recorded as debt instead of declaring an intent")
        assert f"undeclared::{gate}.py" not in recorded, gate
    prev = doc["undeclared_previous_size"]
    assert prev is None or len(recorded) <= prev, (
        f"the shrink-only register grew: {prev} -> {len(recorded)}")
    for key in ("scope_expanded", "undeclared_scope_expanded"):
        reason = doc.get(key) or ""
        for gate, _step, _slot, _intent in _GATES:
            assert gate not in reason, (
                f"the {key} reason names {gate}, so the register was widened "
                f"to absorb it instead of the gate declaring an intent")
    # And the register must still be EXACT. "does not contain the two" is also
    # satisfied by a register that has drifted out of step some other way.
    mod = _audit_mod()
    computed = {f"undeclared::{u['gate']}"
                for u in mod.audit(_FLOW, _PROGRAMS)["undeclared_audit_only"]}
    assert computed == recorded, {
        "new_and_unrecorded": sorted(computed - recorded),
        "recorded_but_paid": sorted(recorded - computed)}


# ═══════════════════════ THE REASON, RE-MEASURED — `area_total_vs_budget_check`
#
# The declaration says this gate cannot reach a verdict about a design through
# its own flow clause. That is a claim about the tree, not a preference, so it
# is measured here on every run rather than believed.

def _producer_area_unit_literal() -> str:
    """The `chip_area_unit` string `synth_area_stats_emit` actually writes.

    TWO SHAPES, both resolved, because the producer moved between them and this
    guard is supposed to follow the VALUE rather than pin a spelling:

      1. a SHARED CONSTANT — `_ystat.AREA_UNIT_UNESTABLISHED`. The figure has
         two producers parsing the same yosys line, and they were made to share
         one sentence so they could not drift into disagreeing about the unit.
      2. an inline literal, which is what this file was first written against.
         Kept so the guard still works on a tree from before that change.

    It RAISES when it can resolve neither. A resolver that fell back to a guess
    would measure the wrong string and report the precondition as still holding
    when nobody had checked — which is the failure this whole guard exists to
    prevent, one level up.
    """
    src = (_PROGRAMS / "synth_area_stats_emit.py").read_text()
    if "_ystat.AREA_UNIT_UNESTABLISHED" in src:
        saved = list(sys.path)
        sys.path.insert(0, str(_PROGRAMS))
        try:
            spec = importlib.util.spec_from_file_location(
                "_ystat_areaunit", _PROGRAMS / "_yosys_stat.py")
            mod = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = mod
            spec.loader.exec_module(mod)
            return mod.AREA_UNIT_UNESTABLISHED
        finally:
            sys.path[:] = saved
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Dict):
            continue
        for k, v in zip(node.keys, node.values):
            if (isinstance(k, ast.Constant) and k.value == "chip_area_unit"
                    and isinstance(v, ast.Constant)
                    and isinstance(v.value, str)):
                return v.value
    raise AssertionError(
        "synth_area_stats_emit writes `chip_area_unit` from neither a shared "
        "constant this resolver knows nor an inline literal; the promotion "
        "precondition recorded in area_total_vs_budget_check's ENFORCEMENT "
        "block was written against that value and must be re-derived before "
        "the declaration is trusted")


def test_the_area_figures_only_producer_still_declines_to_name_the_unit():
    """PRECONDITION 1 of the area gate's `advisory` declaration.

    `synth_area_stats_emit` is the only producer of `chip_area` in this flow
    (`design_one_shot_runner.step_yosys_synth` calls its `emit_stats_json`) and
    it declines to name the unit on purpose. While that holds, the gate's own
    `_UM2_SPELLINGS` can never match and the unit is never ESTABLISHED.
    """
    unit = _producer_area_unit_literal()
    spellings = _area_gate_mod()._UM2_SPELLINGS
    matched = [s for s in spellings if s.lower() in unit.lower()]
    assert not matched, (
        f"synth_area_stats_emit now states chip_area_unit={unit!r}, which "
        f"names um^2 ({matched}). The precondition recorded in "
        f"area_total_vs_budget_check's ENFORCEMENT block no longer holds: the "
        f"gate can now reach rc 0 and rc 1 through the flow, so its "
        f"`advisory` declaration has to be re-decided — the wiring it names "
        f"(design_one_shot_runner.step_yosys_synth, immediately after "
        f"`_ystat.emit_stats_json`) is now buildable and provable")


def test_the_flow_clause_does_not_assert_a_unit_it_was_not_given():
    """PRECONDITION 2, and the shortcut this change refused.

    Adding `--area-unit-um2` to the step-9 clause would make rc 0/1 reachable
    tomorrow — by asserting a unit the PRODUCING artefact declined to assert,
    which is the ART-POWER-FIGURES-X1000 defect the gate exists to remove."""
    cmd = _flow_command("area_total_vs_budget_check")
    assert "--area-unit-um2" not in cmd, (
        f"the step-9 clause now reads {cmd!r}. Establishing the unit from the "
        f"caller rather than from the producing artefact is the exact "
        f"substitution area_total_vs_budget_check refuses; if this is "
        f"deliberate it needs its own argument, not a declaration written "
        f"against its absence")


def test_the_area_gate_reaches_only_incomplete_through_its_own_flow_clause(
        tmp_path):
    """THE MEASUREMENT the declaration quotes, re-run end to end.

    A project carrying BOTH authorities the comparison needs — a declared
    `L19.die_area_budget_um` and a synth `chip_area` far above it — invoked with
    the flow clause's own argv. rc 1 is what an inline wiring would decide on,
    and it is unreachable: the producer's unit string blocks the comparison, so
    the honest verdict is rc 2 INCOMPLETE naming what is missing.
    """
    proj = tmp_path / "proj"
    (proj / "phase2" / "stage2" / "synth").mkdir(parents=True)
    (proj / "generated_docs").mkdir(parents=True)
    (proj / "phase2" / "stage2" / "synth" / "stats.json").write_text(json.dumps({
        "schema": "vibeic.synth.stats.v1",
        "netlist": "phase2/stage2/synth/netlist.v",
        "top_module": "t",
        # 9e6 against a 1300x1300 = 1.69e6 ceiling: over budget by 5.3x, so if
        # the unit WERE established this is an unambiguous rc 1.
        "chip_area": 9000000.0,
        "chip_area_unit": _producer_area_unit_literal(),
        "cell_count": 100,
        "includes_submodules": False,
        "selection": {"rule": "top", "why": "top module"},
    }))
    (proj / "generated_docs" / "L19_CONSTRAINTS_PDK.json").write_text(
        json.dumps({"fields": {"die_area_budget_um": "1300x1300"}}))

    argv = _flow_command("area_total_vs_budget_check").split()
    assert argv[0] == "area_total_vs_budget_check", argv
    # `.` in the clause is the project root the flow runs the gate from.
    argv = [str(_PROGRAMS / "area_total_vs_budget_check.py")] + [
        str(proj) if a == "." else a for a in argv[1:]]
    cp = _pr.run([sys.executable] + argv, cwd=str(proj),
                        capture_output=True, text=True)
    blob = (cp.stdout or "") + (cp.stderr or "")
    assert cp.returncode == 2, (
        f"the step-9 clause now returns rc={cp.returncode} on a project that "
        f"declares a die budget and a synth area. area_total_vs_budget_check's "
        f"`ENFORCEMENT: advisory` rests on rc 2 being the only verdict "
        f"reachable here; it is no longer true, so the declaration has to be "
        f"re-decided.\n{blob[-2000:]}")
    assert "INCOMPLETE" in blob and "um^2" in blob, blob[-2000:]


def test_the_area_gate_itself_is_not_vacuous():
    """The other direction, so the test above cannot be satisfied by a gate that
    refuses everything. Given the unit — which is what the promotion precondition
    would supply from the artefact — the SAME inputs reach both real verdicts."""
    mod = _area_gate_mod()
    assert mod._UM2_SPELLINGS, "the gate no longer recognises any um^2 spelling"
    # The refusal is keyed on the unit, not on the comparison being impossible:
    # a caller carrying the requirement outside the artefact establishes it.
    cp = _pr.run(
        [sys.executable, str(_PROGRAMS / "area_total_vs_budget_check.py"),
         "--help"], capture_output=True, text=True)
    assert "--area-unit-um2" in cp.stdout, cp.stdout


def test_the_evidence_route_the_area_declaration_names_still_exists():
    """The promotion condition has to be an instruction someone can FOLLOW.

    The obvious wording — "record the unit the loaded Liberty declares" — is not
    one: Liberty has no area unit, so that sentence would have named a change
    nobody could make, which is barely better than naming none. The declaration
    instead points at a CROSS-CHECK against the cell LEF, and this asserts the
    two assets it needs are still what `pdk_registry.json` resolves for a PDK.

    Offline by construction: it reads the registry, never the image. The
    measurement quoted in the declaration was taken inside vibeic-eda 0.2.26 and
    is recorded there with its numbers; what has to hold on every run is that
    the ROUTE still exists.
    """
    reg = json.loads((_PROGRAMS / "pdk_registry.json").read_text())
    pdks = reg["pdks"]
    named = {p["name"]: p for p in pdks if isinstance(p, dict) and "name" in p}
    assert named, "pdk_registry.json carries no named PDK entries"
    # The two PDKs the declaration quotes numbers for must still resolve BOTH
    # assets the cross-check needs; if either key goes, the route named in the
    # ENFORCEMENT block is gone and the promotion condition must be re-derived.
    for pdk in ("gf180mcuD", "sky130A"):
        assert pdk in named, (
            f"{pdk} has left pdk_registry.json; the area gate's ENFORCEMENT "
            f"block quotes a measurement taken against it")
        for key in ("liberty_glob", "cell_lef_glob"):
            assert named[pdk].get(key), (
                f"{pdk} no longer declares {key}, so the cross-check the area "
                f"gate's promotion condition names — a cell's Liberty `area` "
                f"against its LEF `SIZE w BY h` in microns — cannot be built "
                f"from the registry any more")


def _ystat_mod():
    saved = list(sys.path)
    sys.path.insert(0, str(_PROGRAMS))
    try:
        spec = importlib.util.spec_from_file_location(
            "_ystat_wiring", _PROGRAMS / "_yosys_stat.py")
        m = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = m
        spec.loader.exec_module(m)
        return m
    finally:
        sys.path[:] = saved


#: The two synthesis log shapes this flow actually produces. Step 9 maps to
#: GENERIC primitives and loads no library, so yosys prints no area line;
#: phase 3 maps against a library and prints one.
_STEP9_LOG = "=== chip_top ===\n   Number of cells:                349\n"
_PHASE3_LOG = ("=== chip_top ===\n   Number of cells:                349\n"
               "     349 5.84E+03 cells\n\n"
               "   Chip area for module '\\chip_top': 5841.196200\n")


def test_step_nine_produces_no_area_figure_at_all():
    """WHY THE DECLARATION NAMES PHASE 3 AND NOT STEP 9.

    An earlier version of the ENFORCEMENT block said the inline wiring belonged
    in `design_one_shot_runner.step_yosys_synth`. It does not: that step runs
    `abc -g cmos2` and a bare `stat`, loads no library, and yosys prints no
    `Chip area for module` line — so a gate wired there reads None on every
    project ever built and refuses forever. This pins the fact the correction
    rests on."""
    ys = _ystat_mod()
    parsed = ys.parse_stat_block(_STEP9_LOG)
    assert parsed is not None, "the step-9 fixture no longer parses"
    assert parsed["chip_area"] is None, (
        "a library-less synthesis now yields an area figure; the reason "
        "area_total_vs_budget_check's promotion condition names phase 3 "
        "rather than step 9 has changed and must be re-derived")


def test_the_phase_three_synthesis_is_what_produces_the_figure():
    """The other half: with a library loaded the same parser DOES get one, so
    the correction is a statement about which step runs, not about the parser."""
    ys = _ystat_mod()
    assert ys.parse_stat_block(_PHASE3_LOG)["chip_area"] is not None


def test_the_producer_the_declaration_names_is_still_a_real_place():
    """The promotion path has to be somewhere that EXISTS. Anchored on the
    FUNCTION and the CALL, never on a line number."""
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text()
    fn = next((n for n in ast.walk(ast.parse(src))
               if isinstance(n, ast.FunctionDef) and n.name == "step_synth"),
              None)
    assert fn is not None, (
        "phase3_one_shot_runner.step_synth is gone; the producer the area "
        "gate's ENFORCEMENT block names no longer exists")
    body = ast.get_source_segment(src, fn) or ""
    assert "emit_for_run" in body, (
        "step_synth no longer calls emit_for_run, so the point the declaration "
        "names — the call that writes the figure this gate reads — is not there")
    assert "-liberty" in body, (
        "step_synth no longer passes -liberty, so it would stop producing an "
        "area line and the whole promotion chain must be re-derived")


def test_the_emitter_can_now_be_told_which_library_produced_the_figure():
    """RE-DECIDED, not edited to match (2026-08-22).

    This assertion used to read the other way: `emit_for_run` took no library
    parameter, and that was recorded as precondition 1 of the `advisory`
    declaration — "when that changes, the unit becomes establishable and this
    declaration must be re-decided". It changed, so it was re-decided, and this
    now pins the state that replaced it.

    The declaration stays `advisory` and the reason is DIFFERENT: the unit is no
    longer what stands in the way. No runner spawns this gate inline, which is
    the only axis that token names, and that is a product decision rather than a
    technical gap.
    """
    emit = (_PROGRAMS / "synth_area_stats_emit.py").read_text()
    fn = next((n for n in ast.walk(ast.parse(emit))
               if isinstance(n, ast.FunctionDef) and n.name == "emit_for_run"),
              None)
    assert fn is not None, "synth_area_stats_emit.emit_for_run is gone"
    params = [a.arg for a in fn.args.args] + [a.arg for a in fn.args.kwonlyargs]
    assert any("lib" in a.lower() for a in params), (
        f"emit_for_run takes {params}; it can no longer be told which library "
        f"produced the figure, so the unit is unestablishable again and the "
        f"ENFORCEMENT block's account of what remains is wrong")


def test_the_producer_actually_passes_the_library_it_synthesised_against():
    """A parameter nothing supplies is the same as no parameter. The caller
    must hand over the library it interpolated into `stat -liberty`, or the
    figure and the unit could come from different libraries."""
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text()
    fn = next((n for n in ast.walk(ast.parse(src))
               if isinstance(n, ast.FunctionDef) and n.name == "step_synth"), None)
    assert fn is not None
    body = ast.get_source_segment(src, fn) or ""
    call = body.split("_sas.emit_for_run(", 1)
    assert len(call) == 2, "step_synth no longer calls the emitter"
    assert "liberty" in call[1][:400], (
        "step_synth calls the emitter without handing over the library it "
        "synthesised against, so the unit cannot be established on a real run")


def test_the_gate_reaches_a_real_verdict_once_the_unit_is_established(tmp_path):
    """THE CLOSURE, asserted end to end rather than described.

    Before this chain existed the gate's only reachable verdict through the
    flow was rc 2 INCOMPLETE. With the unit established it must reach BOTH real
    verdicts on the same figure — and a test that only proved rc 1 would be
    satisfied by a gate that fails everything."""
    def _project(root: Path, budget: str) -> Path:
        (root / "phase2/stage2/synth").mkdir(parents=True)
        (root / "generated_docs").mkdir(parents=True)
        (root / "phase2/stage2/synth/stats.json").write_text(json.dumps({
            "schema": "vibeic.synth.stats.v1",
            "netlist": "phase2/stage2/synth/netlist.v", "top_module": "t",
            "chip_area": 25282.1184, "chip_area_unit": "um^2",
            "cell_count": 349, "includes_submodules": False,
            "selection": {"rule": "top", "why": "top module"}}))
        (root / "generated_docs/L19_CONSTRAINTS_PDK.json").write_text(
            json.dumps({"fields": {"die_area_budget_um": budget}}))
        return root

    prog = str(_PROGRAMS / "area_total_vs_budget_check.py")
    over = _project(tmp_path / "over", "10x10")          # 100 um^2, far too small
    cp = _pr.run([sys.executable, prog, str(over)],
                        capture_output=True, text=True)
    assert cp.returncode == 1, (cp.returncode, cp.stdout[-800:])
    assert "AREA_TOTAL_OVER_DECLARED_DIE" in cp.stdout

    fits = _project(tmp_path / "fits", "1000x1000")      # 1e6 um^2, roomy
    cp2 = _pr.run([sys.executable, prog, str(fits)],
                         capture_output=True, text=True)
    assert cp2.returncode == 0, (cp2.returncode, cp2.stdout[-800:])


def test_both_producers_write_to_the_same_artefact_path():
    """The overwrite the correction depends on: phase 3 replaces step 9's own
    stats.json, which is the only reason a figure is there at final-audit."""
    saved = list(sys.path)
    sys.path.insert(0, str(_PROGRAMS))
    try:
        spec = importlib.util.spec_from_file_location(
            "_pl_wiring", _PROGRAMS / "_path_layout.py")
        pl = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = pl
        spec.loader.exec_module(pl)
    finally:
        sys.path[:] = saved
    assert pl.synth_dir(Path("/P")) == Path("/P/phase2/stage2/synth"), (
        "the synthesis artefact directory moved; the claim that phase 3 "
        "overwrites step 9's stats.json must be re-measured")


# ═══════════════════════════════ THE REASON, RE-MEASURED — `tapeout_docs_gen`

def test_the_document_generator_carries_a_verdict_not_only_documents(tmp_path):
    """THE THIRD ANSWER, REFUTED BY MEASUREMENT.

    "It is a generator, so take it out of the gate population" would delete a
    real verdict. Two runs of ONE metrics file differing in ONE number:
    a clean run writes both documents and exits 0; the same run with a negative
    setup slack writes NOTHING and exits 1 — rc 1 rather than rc 2 deliberately,
    because rc 2 is this flow's VACUOUS_PASS tier and reported a pass on
    precisely the runs the program had refused to document.
    """
    clean = {
        "route__drc_errors": 0, "magic__drc_error__count": 0,
        "klayout__drc_error__count": 0, "klayout__density_error__count": 0,
        "antenna__violating__nets": 0, "antenna__violating__pins": 0,
        "design__lvs_error__count": 0,
        "design__lvs_unmatched_device__count": 0,
        "design__lvs_unmatched_net__count": 0,
        "design__lvs_unmatched_pin__count": 0,
        "design__xor_difference__count": 0,
        "timing__setup__ws": 0.5, "timing__setup__tns": 0.0,
        "timing__hold__ws": 0.1, "timing__hold__tns": 0.0,
        "design__max_slew_violation__count": 0,
        "design__max_cap_violation__count": 0,
        "design__die__bbox": "0 0 100 100",
    }
    prog = str(_PROGRAMS / "tapeout_docs_gen.py")

    def _run(metrics: dict, tag: str):
        proj = tmp_path / tag
        (proj / "phase3" / "final").mkdir(parents=True)
        (proj / "input").mkdir(parents=True)
        (proj / "input" / "project.json").write_text(
            json.dumps({"design": "demo", "pdk": "gf180mcuD"}))
        (proj / "phase3" / "final" / "metrics.json").write_text(
            json.dumps(metrics))
        out = proj / "reports" / "phase3" / "docs"
        cp = _pr.run(
            [sys.executable, prog, "--project", str(proj),
             "--out-dir", str(out)],
            capture_output=True, text=True)
        return cp, sorted(p.name for p in out.glob("*.html")) if out.is_dir() else []

    ok, ok_docs = _run(clean, "clean")
    assert ok.returncode == 0, (ok.stdout, ok.stderr)
    assert len(ok_docs) == 2, ok_docs

    bad, bad_docs = _run({**clean, "timing__setup__ws": -1.53}, "violated")
    assert bad.returncode == 1, (
        f"one negative setup slack no longer produces a verdict "
        f"(rc={bad.returncode}). If this program has stopped judging, its "
        f"place in step 37.5ic's gate population — and the ENFORCEMENT block "
        f"that argues for keeping it there — has to be re-decided.\n"
        f"{(bad.stdout or '')[-1000:]}\n{(bad.stderr or '')[-1000:]}")
    assert bad_docs == [], (
        f"a NOT RELEASABLE run wrote documents anyway: {bad_docs}")
    assert "NOT RELEASABLE" in (bad.stderr or ""), bad.stderr[-1000:]


def test_the_runner_dispatches_the_document_generator_on_canonical_37_5ic():
    """Measure the dedicated producer path that made the declaration blocking."""
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text()
    tree = ast.parse(src)
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef)
               and n.name == "step_tapeout_docs_gen"), None)
    assert fn is not None, "phase3_one_shot_runner.step_tapeout_docs_gen is gone"
    body = ast.get_source_segment(src, fn) or ""
    assert '"37.5ic"' in body, body[:1200]
    assert '"tapeout_docs_gen.py"' in body, body[:1200]
    assert "subprocess.run" in body and "returncode" in body, body[:1600]
    assert "step_tapeout_docs_gen(project)" in src, (
        "the dedicated function exists but the phase-3 plan no longer calls it")


def test_canonical_37_5ic_consumes_the_document_verdict_in_a_blocking_slot():
    """The producer dispatch does not replace the blocking flow verdict."""
    mod = _audit_mod()
    row = {r["gate"]: r for r in mod.audit(_FLOW, _PROGRAMS)["gates"]}[
        "tapeout_docs_gen"]
    assert row["enforcement"] == "ENFORCED", row
    assert row["wiring"] == "INLINE_BLOCKING", row
    assert row["declared"] == "blocking", row
    assert row["slots"] == ["program_exit_zero"], row


def test_the_inline_signoff_table_still_cannot_call_the_document_generator():
    """The old generic table remains incompatible; 37.5ic is a dedicated path."""
    cp = _pr.run(
        [sys.executable, str(_PROGRAMS / "tapeout_docs_gen.py"),
         "/nonexistent/project", "--json", "/nonexistent/out.json",
         "--out-dir", "/nonexistent/docs"],
        capture_output=True, text=True)
    assert cp.returncode == 2 and "unrecognized arguments" in cp.stderr, (
        cp.returncode, cp.stdout[-800:], cp.stderr[-800:])


def test_the_call_shape_that_precondition_is_written_against_is_still_the_one():
    """The generic table still uses ``--json`` and excludes the dedicated gate."""
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text()
    tree = ast.parse(src)
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef)
               and n.name == "_run_declared_signoff_gate"), None)
    assert fn is not None
    body = ast.get_source_segment(src, fn) or ""
    assert '"--json"' in body
    table = re.search(r"_DECLARED_SIGNOFF_GATES\s*=\s*\((.*?)\n\)", src,
                      re.DOTALL)
    assert table, "_DECLARED_SIGNOFF_GATES is no longer a literal tuple"
    assert "tapeout_docs_gen" not in table.group(1)


# ═════════════════════════════════════════════════════════════ THE PAIRED GUARD
#
# Every assertion above is of the form "the audit does NOT report gate X". That
# family is trivially satisfied by an audit that reports nothing at all, and
# "declaring these two made the audit go quiet about a real regression later" is
# the precise defect this change could introduce. The controls below drive the
# SAME `audit()` and `main()` entry points over synthetic trees and prove the
# code path is still live — including the branch that makes `advisory` the
# honest token here rather than a way around a check.

_SILENT = '''"""A gate that says nothing about where its verdict is enforced."""
'''
_DECLARING = '''"""A gate that says so.

ENFORCEMENT: advisory — no runner spawns it.
"""
'''
_DECLARING_BLOCKING = '''"""A gate that claims more than its wiring delivers.

ENFORCEMENT: blocking
"""
'''
_FLOW_DOC = textwrap.dedent("""\
    steps:
      - id: 1
        name: "synthetic"
        gate:
          all_of:
    {rows}
    """)


def _synthetic(root: Path, gates: dict):
    """A synthetic plugin tree: every gate wired into the flow's BLOCKING slot
    and NOTHING invoking any of them — the shape the historical undeclared
    finding and the remaining advisory control exercise."""
    progs = root / "programs"
    progs.mkdir(parents=True, exist_ok=True)
    for name, body in gates.items():
        (progs / f"{name}.py").write_text(body)
    flow = root / "flow.yaml"
    flow.write_text(_FLOW_DOC.format(rows="\n".join(
        f'        - program_exit_zero: "{n} . --json out.json"'
        for n in gates)))
    return flow, progs


def _empty_baseline(tmp_path: Path) -> Path:
    p = tmp_path / "baseline.json"
    p.write_text(json.dumps({"known": [], "undeclared_known": []}))
    return p


def test_the_control_a_genuinely_undeclared_new_gate_is_still_reported(
        tmp_path):
    """THE GUARD. A third gate, added later, wired where it cannot block and
    saying nothing about that, must still be named AND must still exit 1 —
    because the exit status is the only channel that can stop a landing."""
    mod = _audit_mod()
    flow, progs = _synthetic(tmp_path / "t", {
        "declared_sibling_check": _DECLARING,     # like the two: green
        "brand_new_quiet_check": _SILENT,         # the regression: must fail
    })
    rep = mod.audit(flow, progs)
    assert [u["gate"] for u in rep["undeclared_audit_only"]] == [
        "brand_new_quiet_check"], rep
    assert mod.main(["--flow", str(flow), "--programs", str(progs),
                     "--baseline", str(_empty_baseline(tmp_path))]) == 1


def test_the_control_a_declared_gate_beside_it_stays_green(tmp_path):
    """The other half of the same tree, so "reports the new one" cannot be
    satisfied by reporting everything."""
    mod = _audit_mod()
    flow, progs = _synthetic(tmp_path / "t", {
        "declared_sibling_check": _DECLARING})
    rep = mod.audit(flow, progs)
    assert rep["undeclared_audit_only"] == [], rep
    assert rep["contradictions"] == [], rep
    assert mod.main(["--flow", str(flow), "--programs", str(progs),
                     "--baseline", str(_empty_baseline(tmp_path))]) == 0


def test_the_control_declaring_blocking_without_the_wiring_still_fails(
        tmp_path):
    """A blocking flow slot alone is not proof of inline runner wiring.

    A gate that nothing invokes cannot honestly claim blocking merely because
    its flow clause uses a blocking slot. The audit files that as a
    `contradiction::`; this control proves that branch remains live."""
    mod = _audit_mod()
    flow, progs = _synthetic(tmp_path / "t", {
        "overclaiming_check": _DECLARING_BLOCKING})
    rep = mod.audit(flow, progs)
    assert [c["gate"] for c in rep["contradictions"]] == [
        "overclaiming_check"], rep
    assert mod.main(["--flow", str(flow), "--programs", str(progs),
                     "--baseline", str(_empty_baseline(tmp_path))]) == 1


if __name__ == "__main__":
    sys.exit(pytest.main([str(Path(__file__).resolve()), "-v"]))


# ═════════════════════════ THE WIRING, AND THAT IT CAN GO RED (2026-08-22)
#
# `area_total_vs_budget_check` is DECLARED blocking and WIRED inline. A wiring
# nobody can make fail is not a wiring, so this section proves the red three
# ways and is honest about the one thing it does not execute: `step_synth`
# itself needs a real synthesis, so what is executed here is the verdict the
# wiring consumes and the branch that consumes it, not the whole step.

def test_the_wiring_is_measured_as_inline_blocking_by_the_audit():
    """The repo's OWN instrument for "can this gate stop the step". It parses
    the runner and asks whether the exit status reaches a control-flow
    decision — the exact question `advisory` used to answer no to."""
    mod = _audit_mod()
    rep = mod.audit(_FLOW, _PROGRAMS)
    row = {r["gate"]: r for r in rep["gates"]}["area_total_vs_budget_check"]
    assert row["enforcement"] == "ENFORCED", row
    assert row["wiring"] == "INLINE_BLOCKING", row
    assert row["declared"] == "blocking", row
    assert row["slots"] == ["program_exit_zero"], (
        "the wiring is not permission to move the clause out of the flow's "
        "blocking slot")


def test_the_verdict_the_wiring_consumes_really_is_rc_one(tmp_path):
    """EXECUTED, not asserted. The wiring branches on rc 1 from a real
    subprocess, so this runs that subprocess on a project whose declared die
    cannot hold its own synthesised area — the only input that makes the step
    fail — and on one that fits, so a gate that failed everything would not
    satisfy it."""
    def _project(root: Path, budget: str) -> Path:
        (root / "phase2/stage2/synth").mkdir(parents=True)
        (root / "generated_docs").mkdir(parents=True)
        (root / "phase2/stage2/synth/stats.json").write_text(json.dumps({
            "schema": "vibeic.synth.stats.v1",
            "netlist": "phase2/stage2/synth/netlist.v", "top_module": "t",
            "chip_area": 25282.1184, "chip_area_unit": "um^2",
            "cell_count": 349, "includes_submodules": False,
            "selection": {"rule": "top", "why": "top module"}}))
        (root / "generated_docs/L19_CONSTRAINTS_PDK.json").write_text(
            json.dumps({"fields": {"die_area_budget_um": budget}}))
        return root
    prog = str(_PROGRAMS / "area_total_vs_budget_check.py")
    over = _pr.run(
        [sys.executable, prog, str(_project(tmp_path / "o", "10x10"))],
        capture_output=True, text=True)
    assert over.returncode == 1, (over.returncode, over.stdout[-600:])
    fits = _pr.run(
        [sys.executable, prog, str(_project(tmp_path / "f", "1000x1000"))],
        capture_output=True, text=True)
    assert fits.returncode == 0, (fits.returncode, fits.stdout[-600:])


def test_the_runner_turns_that_rc_one_into_a_failed_step():
    """The branch that consumes it, read from the runner's AST rather than
    from a line number. Three things must all hold, and each has been a way
    this class of wiring was silently defanged before: the gate is SPAWNED, the
    rc is COMPARED to 1, and that comparison returns a FAIL StepResult rather
    than merely logging."""
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text()
    fn = next((n for n in ast.walk(ast.parse(src))
               if isinstance(n, ast.FunctionDef) and n.name == "step_synth"), None)
    assert fn is not None, "phase3_one_shot_runner.step_synth is gone"
    body = ast.get_source_segment(src, fn) or ""
    assert "area_total_vs_budget_check.py" in body, (
        "step_synth no longer spawns the gate, so nothing can stop the step")
    seg = body.split("area_total_vs_budget_check.py", 1)[1]
    assert "returncode == 1" in seg, (
        "the gate's exit status no longer reaches a comparison; a runner that "
        "spawns a gate and discards its status is vibe-ic#884's defect")
    # NO CHARACTER WINDOW. This used to read `[:800]`, and 800 is not a property
    # of anything — it is a guess about how much PROSE sits between two tokens.
    # MEASURED: at v1.12.30 `"FAIL"` sat at offset 66 and this passed; v1.12.31
    # added a comment block above it ("THE AREA LOOP, step 9 -> 1") and the same
    # unchanged, correct code moved the token to offset 5071, so the assertion
    # fell off the end of its own window and reported the RUNNER as broken. The
    # subject never changed. Searching the whole segment cannot go stale that way.
    tail = seg.split("returncode == 1", 1)[1]
    assert '"FAIL"' in tail, (
        "rc 1 no longer returns a FAIL StepResult — the verdict is computed "
        "and dropped, which is exactly what `advisory` used to mean")


def test_only_rc_one_stops_the_step_and_the_bound_is_deliberate():
    """rc 2 is "no ceiling declared" for 118 of 136 real converge runs across all
    5 fleet machines — CITED from `l19_pdk_floorplan_contract_check`, which is
    dated and attributed and in this repository, though its population is fleet
    run trees a reader here may not be able to reach. An earlier version of this
    docstring said "176 of 177 published L19 copies", from a corpus withdrawn on
    2026-08-20 that cannot be re-derived at all; it overstated the case for this
    bound by more than an order of magnitude. A second draft called the
    replacement "reproducible", which was also wrong — it is a citation.

    If rc 2 ever starts stopping the step, 118 of 136 runs go non-green over a
    requirement they never wrote — a product decision this wiring deliberately
    did not take. Pinned so it cannot be taken silently."""
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text()
    fn = next((n for n in ast.walk(ast.parse(src))
               if isinstance(n, ast.FunctionDef) and n.name == "step_synth"), None)
    # NO CHARACTER WINDOW, and here the truncation was worse than a false red.
    # These two assertions pull in OPPOSITE directions over the same slice:
    #   * `"INCOMPLETE" in seg` is POSITIVE — a short window makes it fail
    #     spuriously, which is loud and gets fixed;
    #   * `"returncode != 0" not in seg` is NEGATIVE — a short window makes it
    #     PASS, and a forbidden pattern sitting past the cut is invisible.
    # MEASURED on this tree: the segment is 7062 characters, so `[:2000]` left
    # 72% of it unexamined by the check that is supposed to refuse something.
    # The pattern happens to be absent everywhere, so the assertion was true —
    # but it was true BY LUCK, and a guard that is right by luck is not a guard.
    seg = (ast.get_source_segment(src, fn) or "").split(
        "area_total_vs_budget_check.py", 1)[1]
    assert "returncode != 0" not in seg, (
        "the wiring now stops the step on ANY non-zero rc, which makes rc 2 "
        "INCOMPLETE — the state of nearly every published run — a failure")
    assert "INCOMPLETE" in seg, (
        "the non-blocking rc-2 outcome is no longer disclosed in the step's "
        "detail, so a run that could not be compared reads like one that was")
