#!/usr/bin/env python3
"""vibe-ic#2126 — the disclosure gate that was PRODUCED and never RUN.

THE DEFECT, MEASURED.  #2091 landed `sta_assumed_clock_disclosure_check`: a
sign-off measured against a clock period the design never stated must say so, in
the record.  The disclosure is stamped into the sign-off records by
`clock_target_provenance.stamp_signoff_records`, and the checker that reads it
back exists and works.  Nothing invoked it.  It was absent from
`phase3_one_shot_runner._DECLARED_SIGNOFF_GATES`, which is the only table any
one-shot runner walks, so no step ran it and no run could refuse on it.  A guard
nothing invokes is not a guard — #2103's shape, one gate later.

Measured on the pre-fix tree (f5a237d21546):

    grep -c sta_assumed_clock_disclosure_check flow/phase1_phase2_phase3.yaml  -> 0
    "sta_assumed_clock_disclosure_check.py" in
        {g[1] for g in phase3_one_shot_runner._DECLARED_SIGNOFF_GATES}         -> False

so the two declaration surfaces the repo has for "this gate runs on every
phase-3 sign-off" both said no.

WHAT THIS FILE ASSERTS, and in which direction.

  (1) DECLARATION, BY NAME.  The gate is in the runner's table and in the flow
      yaml, and the step name it plans reaches `DECLARED_SIGNOFF_STEP_NAMES` and
      the sign-off rollup exactly ONCE.  Every assertion here names the gate;
      none of them counts the population, because a count goes stale for the one
      reason that is never a defect (the population grew) and a substitution
      leaves it undisturbed.

  (2) ORDER, WHICH IS A CORRECTNESS CONSTRAINT HERE.  Two of the three
      `clock_target_provenance.SIGNOFF_RELS` are written by the `sta_signoff`
      and `sta_corner` rows of the same table.  The stamp must therefore run
      after those rows and before this gate reads them.  Placed anywhere else,
      the gate would fail every assumed-period run for the flow's own ordering
      rather than for anything about the design — so the ordering is pinned.

  (3) THE TWO-SIDED CONTROL, on a real project tree and through the real
      `step_declared_signoff_gates`.  A project whose period is ASSUMED reaches
      PASS on the step named `sta_clock_disclosure`; drop the disclosure the
      stamp writes and the SAME step goes FAIL, by name.  A check that cannot
      fail is not a check, and a check that fails on a healthy run is worse.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path


_HERE = Path(__file__).resolve()
_PROGRAMS = _HERE.parents[1]
_PLUGIN = _PROGRAMS.parent
_FLOW = _PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
_RUNNER_SRC = _PROGRAMS / "phase3_one_shot_runner.py"

if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

#: The subject, spelled once. Every assertion below refers to these names.
GATE_PROGRAM = "sta_assumed_clock_disclosure_check.py"
GATE_STEP = "sta_clock_disclosure"
GATE_OUT_REL = "reports/phase3/sta/assumed_clock_disclosure.json"


# ===========================================================================
# (1) DECLARED — in both of the flow's declaration surfaces, by name
# ===========================================================================
def test_the_runner_table_declares_the_gate_by_name():
    """FAILS ON THE PRE-FIX TREE. The whole of #2126: the table had no row."""
    import phase3_one_shot_runner as R
    rows = [g for g in R._DECLARED_SIGNOFF_GATES if g[1] == GATE_PROGRAM]
    assert len(rows) == 1, (
        f"{GATE_PROGRAM} is not a declared sign-off gate (rows: {rows}); "
        "no runner invokes it and nothing can refuse on its verdict")
    name, program, out_rel, extra_argv = rows[0]
    assert name == GATE_STEP, name
    assert out_rel == GATE_OUT_REL, out_rel
    # No argv tail: the gate takes a project and a --json target and resolves
    # everything else from the project's own artefacts. An unrecognised
    # argument would be an argparse rc 2, which this runner reads as
    # NOT CHECKED — a declared gate bought out of answering by its caller.
    assert tuple(extra_argv) == (), extra_argv


def test_the_flow_yaml_declares_the_same_invocation():
    """The runner and typed producer write the raw report; its blocking
    consumer writes a distinct verdict, never the producer's required output.
    """
    import shlex
    import yaml
    flow = yaml.safe_load(_FLOW.read_text(errors="replace"))
    row = next(step for step in flow["steps"] if str(step["id"]) == "23")
    program = GATE_PROGRAM.removesuffix(".py")
    producer_command = f"{program} . --json {GATE_OUT_REL}"
    verdict_path = "reports/phase3/sta/assumed_clock_disclosure_verdict.json"
    consumer_command = f"{program} . --json {verdict_path}"
    producer_entries = [entry for entry in row["program_outputs"]
                        if entry.get("program") == program]
    assert len(producer_entries) == 1, producer_entries
    assert producer_entries[0]["path"] == GATE_OUT_REL
    assert producer_entries[0]["producer_command"] == producer_command
    all_producer_entries = [entry for step in flow["steps"]
                            for entry in step.get("program_outputs", [])]
    assert sum(entry.get("producer_command") == producer_command
               for entry in all_producer_entries) == 1
    assert row["required_outputs"].count(GATE_OUT_REL) == 1
    assert verdict_path != GATE_OUT_REL
    assert verdict_path not in row["required_outputs"]
    assert all(verdict_path not in step.get("required_outputs", [])
               for step in flow["steps"])
    assert all(entry.get("path") != verdict_path for entry in all_producer_entries)
    commands = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("program_exit_zero", "advisory_program_exit_zero",
                           "optional_program_exit_zero"):
                    commands.append((key, value if isinstance(value, str)
                                     else value.get("command")))
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for step in flow["steps"]:
        walk(step.get("gate", {}))
    assert commands.count(("program_exit_zero", consumer_command)) == 1, commands
    assert sum(command == consumer_command for _, command in commands) == 1
    assert all(command != producer_command for _, command in commands)
    for _, command in commands:
        assert isinstance(command, str) and command, command
        tokens = shlex.split(command)
        assert f"--json={GATE_OUT_REL}" not in tokens, command
        assert all(tokens[i + 1] != GATE_OUT_REL for i, token in enumerate(tokens[:-1])
                   if token == "--json"), command


def test_the_step_name_reaches_the_declared_step_names_exactly_once():
    import phase3_one_shot_runner as R
    assert R.DECLARED_SIGNOFF_STEP_NAMES.count(GATE_STEP) == 1, (
        R.DECLARED_SIGNOFF_STEP_NAMES)


def test_the_rollup_lists_the_new_gate_exactly_once():
    """The sign-off census states its own denominator (#538 / #544). A gate the
    flow declares and the census omits is a denominator that lies."""
    import phase3_one_shot_runner as R
    plan = [R.StepResult(n, "PASS", 0.0, "", [])
            for n in R.DECLARED_SIGNOFF_STEP_NAMES]
    rollup = R.declared_signoff_rollup(plan)
    assert rollup["passed"].count(GATE_STEP) == 1, rollup
    assert rollup["declared"] == len(set(R.DECLARED_SIGNOFF_STEP_NAMES)), rollup




# ===========================================================================
# (2) ORDER — the stamp writes what this gate reads
# ===========================================================================
def test_the_disclosure_row_is_the_last_row_of_the_table():
    """Two of the three records this gate audits are written by rows ABOVE it.
    If it stops being last, the stamp placed before it no longer happens after
    the writers, and every assumed-period run fails on the flow's ordering."""
    import phase3_one_shot_runner as R
    assert R._DECLARED_SIGNOFF_GATES[-1][1] == GATE_PROGRAM, [
        g[1] for g in R._DECLARED_SIGNOFF_GATES]
    assert R._ASSUMED_CLOCK_DISCLOSURE_STEP == GATE_STEP


def test_the_stamp_is_performed_inside_the_dispatch_loop():
    """AST, not prose. `stamp_signoff_records` used to be called after the whole
    loop, which was correct while nothing read it back. It must now be called
    from INSIDE the loop, so it lands between the rows that write the sign-off
    records and the row that audits them."""
    tree = ast.parse(_RUNNER_SRC.read_text(errors="replace"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef)
              and n.name == "step_declared_signoff_gates")
    # RE-DERIVED (T109c). ac2104931 added a second loop over the same table:
    # a parallel FIRST WAVE that submits independent readers to a pool before
    # the dispatch loop. The claim is about the DISPATCH loop -- the one that
    # walks `_DECLARED_SIGNOFF_GATES` row by row -- so it is found by what it
    # iterates, and the first wave is held to never include the audited row.
    loops = [n for n in ast.walk(fn) if isinstance(n, ast.For)
             and ast.unparse(n.iter) == "_DECLARED_SIGNOFF_GATES"]
    dispatch = [n for n in loops if isinstance(n.target, ast.Tuple)]
    assert len(dispatch) == 1, "the row-by-row dispatch loop is no longer one loop"
    import phase3_one_shot_runner as R
    for n in ast.walk(fn):
        if (isinstance(n, ast.Assign) and isinstance(n.value, ast.Set)
                and any(isinstance(t, ast.Name) and t.id == "parallel_names"
                        for t in n.targets)):
            wave = {e.value for e in n.value.elts if isinstance(e, ast.Constant)}
            assert R._ASSUMED_CLOCK_DISCLOSURE_STEP not in wave, (
                "the disclosure row would run in the parallel first wave, "
                "before the stamp")
    stamped_in_loop = [
        n for n in ast.walk(dispatch[0])
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "stamp_signoff_records"]
    assert len(stamped_in_loop) == 1, (
        "stamp_signoff_records is not called from inside the gate dispatch "
        "loop; the disclosure gate would read records the stamp has not "
        "written yet")
    stamped_anywhere = [
        n for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "stamp_signoff_records"]
    assert len(stamped_anywhere) == 1, (
        "the stamp is performed more than once; the second call would rewrite "
        "records this step has already had audited")


# ===========================================================================
# (3) THE TWO-SIDED CONTROL — through the real dispatcher, on a real tree
# ===========================================================================
_STA_RPT = """\
Startpoint: reg_a (rising edge-triggered flip-flop clocked by clk)
Endpoint: reg_b (rising edge-triggered flip-flop clocked by clk)
  worst slack max            0.4210
  worst slack min            0.1120
"""


def _assumed_project(tmp: Path) -> Path:
    """A post-route project whose clock period NOBODY STATED.

    Nothing here declares a period: no staged SDC, no phase-2 SDC, no L8
    record, no doc prose, no config json. That is the #2091 condition, reached
    by ABSENCE rather than by writing `assumed: true` into a fixture — a
    fixture that asserts the provenance module's own conclusion would prove
    only that the fixture agrees with itself.
    """
    sta = tmp / "phase3" / "stage3" / "sta"
    sta.mkdir(parents=True)
    (sta / "post_route_timing.rpt").write_text(_STA_RPT)
    (tmp / "reports" / "phase3").mkdir(parents=True)
    st = tmp / "input" / "submission_template"
    st.mkdir(parents=True, exist_ok=True)
    (st / "NO_TEMPLATE.txt").write_text(
        "# submission_template_ingest: no template record\n"
        "STATUS: ABSENT — this fixture delivers an IP, not a die.\n")
    return tmp


def _row(results, name):
    hit = [r for r in results if r.name == name]
    assert len(hit) == 1, [(r.name, r.status) for r in results]
    return hit[0]


def test_the_fixture_really_is_the_assumed_case(tmp_path):
    """The precondition, measured rather than assumed. If this project's period
    were design-owned the gate would pass unconditionally and the control below
    would be vacuous — the #2091 shape of a green that certifies nothing."""
    import clock_target_provenance as ctp
    proj = _assumed_project(tmp_path)
    rep = ctp.emit_report(proj, applied_period_ns=20.0)
    assert rep["assumed"] is True, rep


def test_an_assumed_run_passes_the_step_once_the_stamp_has_run(tmp_path):
    """DIRECTION 1. Wiring a gate that reddens a healthy run is not a fix.
    The stamp runs inside the dispatch loop, so by the time the disclosure gate
    reads the sign-off records they carry the flag and the sentence."""
    import phase3_one_shot_runner as R
    proj = _assumed_project(tmp_path)
    results = R.step_declared_signoff_gates(proj)
    row = _row(results, GATE_STEP)
    assert row.status == "PASS", (row.status, row.detail)
    # And the record it read really is an assumed-period record: the gate is
    # not passing because there was nothing to audit.
    rec = json.loads((proj / "reports" / "phase3" / "sta"
                      / "post_route_summary.json").read_text())
    assert rec["clock_period_assumed"] is True, rec
    disclosure = json.loads((proj / GATE_OUT_REL).read_text())
    assert disclosure["assumed"] is True, disclosure
    assert disclosure["verdict"] == "PASS", disclosure


def test_dropping_the_disclosure_fails_the_step_by_name(tmp_path, monkeypatch):
    """DIRECTION 2 — THE MUTATION #2126 asks for. Drop the disclosure the stamp
    writes (the flag and the sentence together, which is what "the record does
    not say so" means) and the step named `sta_clock_disclosure` must go FAIL.

    Mutated at the STAMP, not in the checker and not by editing the record after
    the fact: the defect being modelled is a sign-off record that was never told
    the period was assumed, which is exactly a run where the stamp did not
    happen. Every other declared sign-off step must be undisturbed — a mutation
    that reddens the whole population proves nothing about this gate.
    """
    import clock_target_provenance as ctp
    import phase3_one_shot_runner as R
    proj = _assumed_project(tmp_path)
    baseline = {r.name: r.status for r in R.step_declared_signoff_gates(proj)}
    assert baseline[GATE_STEP] == "PASS", baseline

    monkeypatch.setattr(ctp, "stamp_signoff_records", lambda project: [])
    mutant_proj = _assumed_project(tmp_path / "mutant")
    mutated = {r.name: r.status
               for r in R.step_declared_signoff_gates(mutant_proj)}
    assert mutated[GATE_STEP] == "FAIL", mutated
    others = {k: v for k, v in mutated.items() if k != GATE_STEP}
    assert others == {k: v for k, v in baseline.items() if k != GATE_STEP}, (
        "the mutation moved a step other than the one under test", baseline,
        mutated)


def test_a_design_owned_period_passes_with_nothing_to_disclose(tmp_path):
    """The third direction, and the one that keeps this gate out of the way of
    every design that DID state its clock: the gate has an opinion only about
    an assumed period."""
    import clock_target_provenance as ctp
    import phase3_one_shot_runner as R
    proj = _assumed_project(tmp_path)
    sdc_dir = proj / "phase2" / "stage2" / "constraints"
    sdc_dir.mkdir(parents=True)
    (sdc_dir / "design.sdc").write_text("create_clock -name clk -period 8.0\n")
    rep = ctp.emit_report(proj, applied_period_ns=8.0)
    assert rep["assumed"] is False, rep
    row = _row(R.step_declared_signoff_gates(proj), GATE_STEP)
    assert row.status == "PASS", (row.status, row.detail)
    rec = json.loads((proj / "reports" / "phase3" / "sta"
                      / "post_route_summary.json").read_text())
    assert "clock_period_assumed" not in rec, (
        "a design-owned period was stamped as an assumption", rec)


def test_an_absent_provenance_report_is_not_checked_never_a_pass(tmp_path):
    """#1140. The gate's own vacuity guard, asserted through the runner's
    routing: rc 2 reaches the plan as BLOCKED, not as a green."""
    import phase3_one_shot_runner as R
    proj = _assumed_project(tmp_path)
    row = R._run_declared_signoff_gate(
        proj, GATE_STEP, GATE_PROGRAM, GATE_OUT_REL, ())
    assert row.status == "NOT_MEASURED", (row.status, row.detail)
    assert R._SIGNOFF_NOT_CHECKED in row.detail, row.detail
