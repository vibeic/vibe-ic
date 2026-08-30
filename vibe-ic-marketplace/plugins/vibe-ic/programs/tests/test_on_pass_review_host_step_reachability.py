#!/usr/bin/env python3
"""A clause the engine can SEE is not a clause the engine RUNS.

MEASURED at v1.13.70. Three findings had already been paid for on this axis --
v1.13.32 (declared where the engine never looks), v1.13.42 (declared in a form
that can never answer), v1.13.63 (nothing executed the declared argv) -- and two
guards had been written for them. Both were green while:

  A. stage4's review, R4_DIE_IS_NOT_THE_DESIGN -- the one rule that reads the
     artefact that actually LEAVES -- was hosted on step 40, whose `condition:`
     names `phase3/stage5_manufacturing/silicon_received.json`. `find` over the
     tree returns 0 such files and `git log --all --diff-filter=A` for that path
     is EMPTY: no commit in the repository's history ever added one. A step whose
     condition is unmet is SKIPPED-CONDITION and its gate is not run, so that
     review had never executed inside the flow and could not.
  B. all six read `--compliance reports/flow_compliance.json`, a path whose only
     declared producer is the flow's `final_gate:` block -- which NOTHING
     EXECUTES. `flow_compliance_check`'s `--json` has no default and both
     drivers omit it, so the file was written on no run and every gate returned
     rc=2 NOT CHECKED, which is v1.13.42's outcome through a different door.

Neither guard could go red for either. This module is the two falsifiers that
prove they can now, and it is written so that no assertion here can pass because
a check is ABSENT: every rule is proved on a flow that VIOLATES it and again on
the repaired copy, with the shipped flow as the control that must stay green in
both arms.

M1 and M2 below are the exact mutations that were measured green on v1.13.70's
guards. Each leaves the declared command perfectly answerable and perfectly
executable and stops the engine from ever starting it.
"""
import copy
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

PLUGIN = Path(__file__).resolve().parent.parent.parent
CENSUS = PLUGIN / "programs" / "on_pass_review_declared_command_runs_check.py"
ANSWERABLE = PLUGIN / "programs" / "on_pass_review_answerable_check.py"
FLOW = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"

#: A path no step in the flow declares among its `required_outputs`, so nothing
#: the flow does can satisfy a condition naming it. The point of the mutations.
UNPRODUCED = "never/exists/at/all.json"

#: The stage whose clause the mutations move. Named, not indexed: an index is
#: invariant under a reorder and would silently start mutating another stage.
SUBJECT_STAGE = "stage1"


def _run(program: Path, flow: Path):
    r = subprocess.run([sys.executable, str(program), "--flow", str(flow)],
                       capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def _doc():
    return yaml.safe_load(FLOW.read_text(encoding="utf-8"))


def _write(tmp_path: Path, doc, name="flow.yaml") -> Path:
    p = tmp_path / name
    p.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return p


def _host_step(doc, stage):
    """The step carrying `--stage <stage>`'s review clause, and its all_of."""
    for step in doc["steps"]:
        gate = step.get("gate") or {}
        for sub in gate.get("all_of") or []:
            for key, val in sub.items():
                cmd = val.get("command") if isinstance(val, dict) else val
                if (isinstance(cmd, str)
                        and cmd.startswith("stage_on_pass_review")
                        and f"--stage {stage} " in cmd + " "):
                    return step, gate["all_of"], sub, key, cmd
    raise AssertionError(f"no clause dispatches --stage {stage}")


# ─────────────────────────────────────────────────────────────────────────────
# the control: the shipped flow must be green on BOTH guards
# ─────────────────────────────────────────────────────────────────────────────
def test_the_shipped_flow_is_green_on_both_guards():
    """If this is red the mutations below prove nothing about the mutation."""
    rc_c, out_c = _run(CENSUS, FLOW)
    assert rc_c == 0, out_c
    rc_a, out_a = _run(ANSWERABLE, FLOW)
    assert rc_a == 0, out_a


def test_no_on_pass_host_step_carries_a_condition_the_flow_cannot_meet():
    """The state FINDING A left behind, asserted directly on the shipped flow.

    Read from the document rather than through the census, so a census that
    stopped looking cannot make this green.
    """
    doc = _doc()
    produced = set()
    for step in doc["steps"]:
        for out in step.get("required_outputs") or []:
            produced.update(p.strip() for p in str(out).split(" OR "))
    for stage in doc.get("stages") or []:
        if not isinstance(stage.get("on_pass_review"), dict):
            continue
        if stage["on_pass_review"].get("enabled", True) is False:
            continue
        step, _all_of, _sub, _key, _cmd = _host_step(doc, stage["id"])
        cond = step.get("condition")
        if not cond:
            continue
        named = list(cond.get("files_exist") or [])
        unmet = [p for p in named if p not in produced]
        assert not unmet, (
            f"{stage['id']}'s review is hosted on step {step['id']!r}, whose "
            f"condition names {unmet} — paths no step declares among its "
            f"required_outputs. SKIPPED-CONDITION means the gate does not run.")


# ─────────────────────────────────────────────────────────────────────────────
# M1 — an unsatisfiable `condition:` on the HOST STEP
# ─────────────────────────────────────────────────────────────────────────────
def _m1(tmp_path):
    doc = _doc()
    step, _a, _s, _k, _c = _host_step(doc, SUBJECT_STAGE)
    assert not step.get("condition"), (
        "M1 must ADD a condition to a step that has none, or it is not the "
        "mutation that was measured")
    step["condition"] = {"files_exist": [UNPRODUCED]}
    return _write(tmp_path, doc, "m1.yaml")


def test_m1_an_unreachable_host_step_turns_the_census_red(tmp_path):
    rc, out = _run(CENSUS, _m1(tmp_path))
    assert rc == 1, out
    assert "P8 THE HOST STEP IS NOT REACHABLE" in out, out
    assert SUBJECT_STAGE in out and UNPRODUCED in out, out


def test_m1_is_invisible_to_the_answerable_check_and_that_is_the_division(
        tmp_path):
    """NOT a gap. Answerability and reachability are two questions.

    `on_pass_review_answerable_check` asks whether the INVOCATION can produce a
    verdict; M1 does not touch the invocation. Making it red here too would put
    one premise in two programs, which is the shape this repo has already paid
    for, and the two could then disagree. The census owns reachability because
    it already resolves the host step in order to execute the argv.
    """
    rc, out = _run(ANSWERABLE, _m1(tmp_path))
    assert rc == 0, out


# ─────────────────────────────────────────────────────────────────────────────
# M2 — the same silence one level down, on the CLAUSE
# ─────────────────────────────────────────────────────────────────────────────
def _m2(tmp_path):
    doc = _doc()
    _step, all_of, sub, key, cmd = _host_step(doc, SUBJECT_STAGE)
    idx = all_of.index(sub)
    all_of[idx] = {key: {
        "command": cmd,
        "condition_files_exist": [UNPRODUCED],
        "absent_condition_reason":
            "this project has no such input, so the review has nothing to read "
            "and is correctly silent about it"}}
    return _write(tmp_path, doc, "m2.yaml")


def test_m2_a_clause_conditioned_out_turns_the_census_red(tmp_path):
    rc, out = _run(CENSUS, _m2(tmp_path))
    assert rc == 1, out
    assert "P9 THE CLAUSE IS CONDITIONED OUT" in out, out
    assert UNPRODUCED in out, out


@pytest.mark.parametrize("mutate", [_m1, _m2], ids=["M1", "M2"])
def test_the_mutated_clause_still_executes_and_still_refuses(mutate, tmp_path):
    """P6/P7 stay GREEN under both mutations, and that is the whole point.

    This is why P8/P9 had to be added rather than P6 tightened. P6 executes the
    argv ITSELF, with `cwd=<a materialised fixture>`; it proves the COMMAND
    works and can never prove the ENGINE reaches it. Read from the report
    rather than from stdout, which prints the arm table only on PASS.
    """
    import json
    out_json = tmp_path / "census.json"
    flow = mutate(tmp_path)
    subprocess.run([sys.executable, str(CENSUS), "--flow", str(flow),
                    "--json", str(out_json)], capture_output=True, text=True)
    rows = {r["stage"]: r for r in json.loads(
        out_json.read_text(encoding="utf-8"))["stages"]}
    row = rows[SUBJECT_STAGE]
    assert row["checks"].get("P6") != "FAIL", row
    assert row["checks"].get("P7") != "FAIL", row
    assert row["arms"]["P6"]["rc"] == 1 and row["arms"]["P7"]["rc"] == 0, row
    # ...and exactly one of the two reachability checks is what caught it.
    assert "FAIL" in (row["checks"].get("P8", "") + row["checks"].get("P9", "")), row


# ─────────────────────────────────────────────────────────────────────────────
# FINDING B — the verdict source must have an EXECUTED producer, ordered
# ─────────────────────────────────────────────────────────────────────────────
def test_a_compliance_path_no_earlier_clause_writes_is_refused(tmp_path):
    """M3: repoint one review at a path nothing in its `all_of` produces.

    This is v1.13.70's shipped state for all six, restated as a mutation.
    """
    doc = _doc()
    _step, all_of, sub, key, cmd = _host_step(doc, SUBJECT_STAGE)
    idx = all_of.index(sub)
    parts = cmd.split()
    parts[parts.index("--compliance") + 1] = "reports/flow_compliance.json"
    all_of[idx] = {key: " ".join(parts)}
    rc, out = _run(ANSWERABLE, _write(tmp_path, doc, "m3.yaml"))
    assert rc == 1, out
    assert "P2 NAMES A REPORT WITH NO EXECUTED PRODUCER" in out, out
    assert SUBJECT_STAGE in out, out


def test_a_producer_that_runs_AFTER_the_review_does_not_count(tmp_path):
    """Ordering is half the question: `all_of` is walked in sequence.

    Moving the producer behind the review leaves both clauses present and the
    file written — just not before it is read.
    """
    doc = _doc()
    _step, all_of, sub, _key, cmd = _host_step(doc, SUBJECT_STAGE)
    named = cmd.split()[cmd.split().index("--compliance") + 1]
    producer = None
    for other in list(all_of):
        for val in other.values():
            c = val.get("command") if isinstance(val, dict) else val
            if isinstance(c, str) and f"--json {named}" in c:
                producer = other
    assert producer is not None, "the shipped flow must have a producer to move"
    all_of.remove(producer)
    all_of.insert(all_of.index(sub) + 1, producer)
    rc, out = _run(ANSWERABLE, _write(tmp_path, doc, "m4.yaml"))
    assert rc == 1, out
    assert "P2 NAMES A REPORT WITH NO EXECUTED PRODUCER" in out, out


def test_final_gate_alone_is_not_an_executed_producer(tmp_path):
    """The exact substitution the old P2 accepted, asserted as refused.

    `final_gate:` declares `--json reports/flow_compliance.json` and nothing in
    the tree executes `final_gate`. A check that took that declaration for a
    producer was validating a declaration against a declaration.
    """
    doc = _doc()
    _step, all_of, sub, key, cmd = _host_step(doc, SUBJECT_STAGE)
    fg = doc.get("final_gate") or {}
    assert "--json" in str(fg.get("args") or ""), (
        "this test's premise is that final_gate DOES declare a --json path")
    named = str(fg["args"]).split()[str(fg["args"]).split().index("--json") + 1]
    parts = cmd.split()
    parts[parts.index("--compliance") + 1] = named
    all_of[all_of.index(sub)] = {key: " ".join(parts)}
    rc, out = _run(ANSWERABLE, _write(tmp_path, doc, "m5.yaml"))
    assert rc == 1, out
    assert "P2 NAMES A REPORT WITH NO EXECUTED PRODUCER" in out, out
