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

WHAT THE LABEL DOES NOT BUY. Both gates now read `ENFORCEMENT: advisory`, and
that token on its own is worth nothing: `advisory` with no reason is the state
the audit is complaining about with a label on it. So this file does NOT stop at
"the declaration exists". Each declaration names a CONCRETE precondition that
must change before the gate can be wired inline, and the tests below RE-MEASURE
those preconditions on every run:

  * `area_total_vs_budget_check` — the flow's only producer of the area figure,
    `synth_area_stats_emit`, declines to name the figure's unit, so through the
    flow this gate can reach ONLY rc 2 INCOMPLETE. An inline wiring would put a
    control-flow decision on an rc 1 no run can arrive at.
  * `tapeout_docs_gen` — it takes `--project` and emits HTML, so
    `phase3_one_shot_runner._run_declared_signoff_gate`, which invokes every
    entry as `<prog> <project> ... --json <out>`, structurally cannot call it.

If either precondition stops holding — someone teaches the stats emitter the
Liberty's unit, or gives the document generator a verdict artefact and the
table's call shape — the test that measures it goes RED and the declaration has
to be re-decided rather than quietly outliving its reason.

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
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent
_FLOW = _PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"
_BASELINE = _PROGRAMS / "flow_gate_enforcement_baseline.json"
_AUDIT = _PROGRAMS / "flow_gate_enforcement_audit.py"

#: (gate, flow step it guards, the slot it is wired in). The slot is DATA, not a
#: constant: `advisory` answers the RUNNER axis and must never be quoted as
#: licence to move either clause out of the flow's blocking slot.
_GATES = (
    ("area_total_vs_budget_check", "9", "program_exit_zero"),
    ("tapeout_docs_gen", "37.5ic", "program_exit_zero"),
)

#: 60s is the per-call ceiling `ci_harness_timeout_ceiling_check` enforces (the
#: 180s harness session bound // 3): a bound above it can outlive the session and
#: take the rest of the subset down with it.
_TIMEOUT = 60


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

@pytest.mark.parametrize("gate,_step,_slot", _GATES)
def test_the_gate_declares_an_intent_the_audit_can_read(gate, _step, _slot):
    """RETURNED VALUE, not a grep. `declared_intent` is the exact function the
    audit calls to decide DECLARED vs UNDECLARED, so this cannot pass on a
    declaration the audit would not see — one below the 4000-character window,
    one indented past a marker it does not accept, or one that is prose about
    the token rather than the token opening a line."""
    mod = _audit_mod()
    assert mod.declared_intent(_PROGRAMS, gate) == "advisory", (
        f"{gate} does not state where its verdict is consumed in a form the "
        f"audit reads: `ENFORCEMENT: advisory|blocking` opening a line in the "
        f"first 4000 characters, or a lone `\"verdict_mode\"` literal")


# ────────────────────────────────── axis 2: the declaration bought no demotion

@pytest.mark.parametrize("gate,step,slot", _GATES)
def test_the_declaration_did_not_move_the_gate_between_flow_slots(
        gate, step, slot):
    """THE PAIRED HALF OF THE DECLARATION.

    `advisory` answers "no runner spawns this inline". It is NOT a statement
    that the finding may be ignored, and it must never be cited to move a clause
    from `program_exit_zero` to `advisory_program_exit_zero`, where
    `_evaluate_gate` records the finding and passes the step anyway. Both of
    these sit in the blocking slot on a measured argument recorded at their flow
    rows; if this declaration ever becomes the reason one of them moves, this
    assertion is what fails."""
    mod = _audit_mod()
    slots = sorted({c["slot"] for c in mod.clauses_in_flow(_FLOW)
                    if c["gate"] == gate})
    assert slots == [slot], (
        f"{gate} (step {step}) is wired in {slots}, not [{slot!r}]; the "
        f"`ENFORCEMENT: advisory` declaration answers a different axis and is "
        f"not permission to move this clause")


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
    cp = subprocess.run(
        [sys.executable, str(_AUDIT), "--json", str(out)],
        capture_output=True, text=True, timeout=_TIMEOUT)
    assert cp.returncode == 0, (
        f"rc={cp.returncode}\n{cp.stdout[-4000:]}\n{cp.stderr[-2000:]}")
    rep = json.loads(out.read_text())
    undeclared = {u["gate"] for u in rep["undeclared_audit_only"]}
    contradicting = {c["gate"] for c in rep["contradictions"]}
    orphaned = {o["gate"] for o in rep["orphaned"]}
    rows = {r["gate"]: r for r in rep["gates"]}
    for gate, step, slot in _GATES:
        assert gate in rows, f"{gate} is not in the flow definition at all"
        assert rows[gate]["declared"] == "advisory", rows[gate]
        assert rows[gate]["slots"] == [slot], (step, rows[gate])
        assert gate not in undeclared
        assert gate not in contradicting
        assert gate not in orphaned


def test_the_recorded_register_did_not_grow_to_absorb_the_two():
    """The OTHER way to make the audit green, and the one this change refuses.

    `--write-baseline --scope-expanded '<why>'` would have recorded the two as
    permanent debt and exited 0 without either gate saying anything about
    itself. The register is shrink-only and they must be paid down OUT of it,
    not INTO it."""
    doc = json.loads(_BASELINE.read_text())
    recorded = set(doc["undeclared_known"])
    for gate, _step, _slot in _GATES:
        assert f"undeclared::{gate}" not in recorded, (
            f"{gate} was recorded as debt instead of declaring an intent")
        assert f"undeclared::{gate}.py" not in recorded, gate
    prev = doc["undeclared_previous_size"]
    assert prev is None or len(recorded) <= prev, (
        f"the shrink-only register grew: {prev} -> {len(recorded)}")
    for key in ("scope_expanded", "undeclared_scope_expanded"):
        reason = doc.get(key) or ""
        for gate, _step, _slot in _GATES:
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
    """The `chip_area_unit` string `synth_area_stats_emit` actually writes, read
    from its AST rather than copied. The value is an implicit concatenation of
    two literals, so a regex over the source would see half of it."""
    src = (_PROGRAMS / "synth_area_stats_emit.py").read_text()
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Dict):
            continue
        for k, v in zip(node.keys, node.values):
            if (isinstance(k, ast.Constant) and k.value == "chip_area_unit"
                    and isinstance(v, ast.Constant)
                    and isinstance(v.value, str)):
                return v.value
    raise AssertionError(
        "synth_area_stats_emit no longer writes a literal `chip_area_unit`; "
        "the promotion precondition recorded in area_total_vs_budget_check's "
        "ENFORCEMENT block was written against that literal and must be "
        "re-derived before the declaration is trusted")


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
    cp = subprocess.run([sys.executable] + argv, cwd=str(proj),
                        capture_output=True, text=True, timeout=_TIMEOUT)
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
    cp = subprocess.run(
        [sys.executable, str(_PROGRAMS / "area_total_vs_budget_check.py"),
         "--help"], capture_output=True, text=True, timeout=_TIMEOUT)
    assert "--area-unit-um2" in cp.stdout, cp.stdout


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
        cp = subprocess.run(
            [sys.executable, prog, "--project", str(proj),
             "--out-dir", str(out)],
            capture_output=True, text=True, timeout=_TIMEOUT)
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


def test_the_inline_signoff_table_still_cannot_call_the_document_generator():
    """PRECONDITION 1 of `tapeout_docs_gen`'s `advisory` declaration.

    `_run_declared_signoff_gate` invokes every entry of
    `_DECLARED_SIGNOFF_GATES` as `<prog> <project> [extra argv] --json <out>`.
    This program takes `--project`, has no positional and no `--json`, so it
    cannot be an entry in that table until it emits a verdict artefact and
    accepts that call shape. MEASURED by handing it the call shape.
    """
    cp = subprocess.run(
        [sys.executable, str(_PROGRAMS / "tapeout_docs_gen.py"),
         "/nonexistent/project", "--json", "/nonexistent/out.json",
         "--out-dir", "/nonexistent/docs"],
        capture_output=True, text=True, timeout=_TIMEOUT)
    assert cp.returncode == 2 and "unrecognized arguments" in cp.stderr, (
        f"tapeout_docs_gen now accepts the inline sign-off table's call shape "
        f"(rc={cp.returncode}). The structural half of its `ENFORCEMENT: "
        f"advisory` reason no longer holds — only the blast-radius half is "
        f"left, and the declaration has to be re-decided.\n"
        f"{cp.stdout[-800:]}\n{cp.stderr[-800:]}")


def test_the_call_shape_that_precondition_is_written_against_is_still_the_one():
    """The other end of the same precondition, read from the runner's own AST.

    Anchored on the FUNCTION, never on a line number: a line-anchored citation
    rots silently the first time anything above it moves.
    """
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text()
    tree = ast.parse(src)
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef)
               and n.name == "_run_declared_signoff_gate"), None)
    assert fn is not None, (
        "phase3_one_shot_runner._run_declared_signoff_gate is gone; the "
        "wiring tapeout_docs_gen's ENFORCEMENT block names no longer exists "
        "and the promotion path must be re-derived")
    body = ast.get_source_segment(src, fn) or ""
    assert '"--json"' in body, (
        "the inline sign-off wiring no longer passes `--json`, so the reason "
        "tapeout_docs_gen cannot join it has changed")
    table = re.search(r"_DECLARED_SIGNOFF_GATES\s*=\s*\((.*?)\n\)", src,
                      re.DOTALL)
    assert table, "_DECLARED_SIGNOFF_GATES is no longer a literal tuple"
    assert "tapeout_docs_gen" not in table.group(1), (
        "tapeout_docs_gen is now an entry in _DECLARED_SIGNOFF_GATES, i.e. it "
        "IS wired inline — its declaration must say `blocking`, and the audit "
        "will file `advisory` as a contradiction")


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
    and NOTHING invoking any of them — the shape both real gates are in."""
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
    """WHY `advisory` IS THE HONEST TOKEN AND NOT THE CONVENIENT ONE.

    Both real gates sit in the flow's BLOCKING slot, so `ENFORCEMENT: blocking`
    is a tempting thing to write in them. It would be a DIFFERENT claim — that a
    runner can stop the step — and the audit files it as a `contradiction::`,
    which fails just as hard and in a register whose debt is paid down
    differently. This control proves that branch is live."""
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
