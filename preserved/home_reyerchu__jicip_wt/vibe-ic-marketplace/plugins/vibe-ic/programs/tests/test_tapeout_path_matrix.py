#!/usr/bin/env python3
"""DESIGN CLASS x PATH STEP — the two tape-out paths, asked of the flow itself.

A design leaving this flow takes one of two terminal paths and they are not
variants of each other:

    CHIP / IC   0.5ic -> 15.5ic -> 26.5ic -> 37.5ic
                a die of its own: pad ring, seal ring, die identification,
                tape-out precheck. 37.5ic has TWO ARMS -- our general ladder
                always, and the shuttle operator's own container in addition
                wherever the PDK ships a precheck and its template was fetched.
    CELL / IP   37.5ip
                the hardmacro terminal: no die, no pad ring, no seal ring. It
                is delivered as a macro, not taped out.

WHY THIS IS A SUITE OF ITS OWN
==============================
Every defect measured in this area was a CONDITION mistake, not a logic
mistake -- a step conditioned on the wrong thing, so it silently skipped for a
whole class of design:

  * 15.5ic (pad ring) and 26.5ic (seal ring + die id) were conditioned on the
    SHUTTLE TEMPLATE, so a chip that tapes itself out shipped with neither;
  * `phase3/stage3/pnr/pad_assignment.json` had NO PRODUCER, so 15.5ic could
    only ever take `pad_ring_gen`'s SKIP branch -- on the shuttle path too;
  * `37.5self` existed as a THIRD route for a year, so a design routed to one
    authority was never shown the other.

A SKIPPED STEP AND A PASSED STEP LOOK THE SAME IN A SUMMARY. That is the whole
problem and it is what this file exists to make impossible.

THE THREE STATES, AND WHY THERE ARE THREE
=========================================
    RUNS               the step is declared and this class satisfies its
                       condition.
    SKIPPED-CONDITION  the step is declared and this class legitimately does
                       not satisfy it. Correct, and costs nothing.
    MISSING            the step is not there to run. Either the id is not
                       declared at all, or it is declared and nothing in it
                       can execute -- no gate, or a gate naming only programs
                       that do not resolve. THIS IS A DEFECT.

`MISSING` MUST NEVER READ AS `SKIPPED-CONDITION`. Both of the historical
failures above presented as a skip; one of them (steps declared ahead of their
programs) is exactly the second form. :func:`state_of` returns three words and
`test_missing_is_not_readable_as_skipped_condition` proves it can tell them
apart, on a MUTATED copy of the flow rather than by assertion.

NOTHING HERE READS THE YAML AND ASSERTS WHAT THE AUTHOR THINKS IT SAYS
======================================================================
Every state is resolved through `flow_compliance_check._check_condition`, the
predicate a real run is judged by, over a project tree materialised by step
0.5ic's OWN two producer programs. The expectation table in
`_tapeout_path_classes` is an argument about silicon -- a pad ring and a seal
ring are properties of being a DIE -- and is never derived from the flow, so it
can disagree with it. Where it does, one of the two is wrong and this file says
which cell.

chip-AGNOSTIC: the only process names are `gf180mcuD` and `sky130A`, both OPEN
PDKs, and they are here because the shuttle registry's LIVE / RETIRED split is
the fact under test.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pytest
import yaml

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import flow_compliance_check as FCC              # noqa: E402
import _tapeout_path_classes as PC               # noqa: E402
from _tapeout_path_classes import (              # noqa: E402
    CLASSES, MISSING, RUNS, SKIPPED_CONDITION,
)


# ─────────────────────────────────────────────────────────────────────────────
# The flow, read the way the flow's own consumer reads it
# ─────────────────────────────────────────────────────────────────────────────
def _load_flow(path: Optional[Path] = None) -> Dict:
    return yaml.safe_load((path or FCC.DEFAULT_FLOW_DEF).read_text())


def _steps(flow: Dict) -> Tuple[Dict, ...]:
    return tuple(flow.get("steps") or ())


def _step(flow: Dict, sid: str) -> Optional[Dict]:
    for s in _steps(flow):
        if str(s.get("id")) == sid:
            return s
    return None


def _is_path_specific(sid: str) -> bool:
    """A step id whose suffix names a delivery path rather than an order.

    `15.5ic` is step 15.5 ON THE CHIP PATH; the `ic`/`ip` suffix is part of the
    id and is not a version. Derived rather than listed so a SIXTH path step
    cannot be added to the flow and quietly stay uncovered by this file.
    """
    return sid.endswith("ic") or sid.endswith("ip")


def path_steps(flow: Optional[Dict] = None) -> Tuple[str, ...]:
    flow = flow if flow is not None else _load_flow()
    return tuple(str(s["id"]) for s in _steps(flow)
                 if _is_path_specific(str(s["id"])))


#: The five this file was written against, as a LITERAL, on purpose. It is the
#: control for the derivation above: if the two disagree, either a path step
#: was added without coverage or one was removed, and both are things a reader
#: must be told rather than have absorbed.
COVERED_PATH_STEPS: Tuple[str, ...] = (
    "0.5ic", "15.5ic", "26.5ic", "37.5ip", "37.5ic")


def _blocking_program_tokens(step: Dict) -> Tuple[str, ...]:
    """Every program a BLOCKING clause of this step's gate would execute.

    `advisory_program_exit_zero` is excluded: it runs, it reports, it cannot
    block, and a step whose only executable clause is advisory has no verdict
    of its own to reach.
    """
    toks: List[str] = []

    def walk(node) -> None:
        if isinstance(node, list):
            for n in node:
                walk(n)
            return
        if not isinstance(node, dict):
            return
        for key, val in node.items():
            if key in ("all_of", "any_of_gates"):
                walk(val)
            elif key in ("program_exit_zero", "optional_program_exit_zero"):
                cmd = val.get("command") if isinstance(val, dict) else val
                if isinstance(cmd, str) and cmd.strip():
                    toks.append(cmd.split()[0])

    walk(step.get("gate") or {})
    return tuple(toks)


def _gate_commands(step: Dict) -> Tuple[str, ...]:
    cmds: List[str] = []

    def walk(node) -> None:
        if isinstance(node, list):
            for n in node:
                walk(n)
            return
        if not isinstance(node, dict):
            return
        for key, val in node.items():
            if key in ("all_of", "any_of_gates"):
                walk(val)
            elif key in ("program_exit_zero", "optional_program_exit_zero"):
                cmd = val.get("command") if isinstance(val, dict) else val
                if isinstance(cmd, str) and cmd.strip():
                    cmds.append(cmd)

    walk(step.get("gate") or {})
    return tuple(cmds)


def _resolves(token: str) -> bool:
    return (PROGRAMS / f"{token}.py").is_file()


# ─────────────────────────────────────────────────────────────────────────────
# THE RESOLVER — three words, and it must never hand back the wrong one
# ─────────────────────────────────────────────────────────────────────────────
def state_of(project: Path, sid: str, flow: Optional[Dict] = None) -> str:
    """RUNS / SKIPPED-CONDITION / MISSING for one (design, step) cell.

    The condition is evaluated by `flow_compliance_check._check_condition` --
    the same call `check_step` makes on a real run -- so this cannot drift from
    what a run would do. The MISSING branches are checked FIRST and
    deliberately: a step that cannot execute must never be reported by the
    word that means "correctly not applicable".
    """
    flow = flow if flow is not None else _load_flow()
    step = _step(flow, sid)
    if step is None:
        return MISSING
    gate = step.get("gate") or {}
    if not gate:
        return MISSING
    tokens = _blocking_program_tokens(step)
    if tokens and not any(_resolves(t) for t in tokens):
        # Declared ahead of its programs: the id is in the flow, the step can
        # reach no verdict, and every summary would print it as a skip.
        return MISSING
    if not tokens and not gate.get("files_exist"):
        return MISSING
    cond = step.get("condition")
    if not cond:
        return RUNS
    return RUNS if FCC._check_condition(project, cond) else SKIPPED_CONDITION


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures — every class tree built ONCE, by the flow's own producers
# ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="session")
def flow() -> Dict:
    return _load_flow()


@pytest.fixture(scope="session")
def trees(tmp_path_factory) -> Dict[str, Dict]:
    root = tmp_path_factory.mktemp("tapeout_path_matrix")
    template = PC.make_template(root / "operator_template")
    built: Dict[str, Dict] = {}
    for dc in CLASSES:
        proj = root / dc.name
        rec = PC.build(proj, dc, template_root=template)
        rec["project"] = proj
        rec["cls"] = dc
        built[dc.name] = rec
    return built


CELLS = [(dc.name, sid) for dc in CLASSES for sid in COVERED_PATH_STEPS]


def _cell_id(val) -> str:
    return str(val)


# ═════════════════════════════════════════════════════════════════════════════
# 1. The population itself
# ═════════════════════════════════════════════════════════════════════════════
def test_the_path_specific_steps_are_exactly_the_ones_this_matrix_covers(flow):
    """A sixth path step must not be able to arrive uncovered.

    Derived from the flow, compared against this file's own literal. Silence
    is the failure mode being closed: a path step nobody enumerated is a path
    nobody tested, and it would show up in no summary as anything at all.
    """
    derived = set(path_steps(flow))
    covered = set(COVERED_PATH_STEPS)
    assert derived == covered, (
        "the flow's path-specific steps and this matrix's coverage disagree.\n"
        f"  in the flow, not covered here: {sorted(derived - covered)}\n"
        f"  covered here, not in the flow: {sorted(covered - derived)}\n"
        "Add the step to COVERED_PATH_STEPS and give every class in "
        "_tapeout_path_classes.CLASSES an explicit expectation for it. A "
        "path-specific step with no row is a path with no test.")


@pytest.mark.parametrize("sid", COVERED_PATH_STEPS)
def test_every_covered_path_step_is_declared_in_the_flow(sid, flow):
    """MISSING, in its first form: the id is simply not there."""
    assert _step(flow, sid) is not None, (
        f"step {sid} is named by this matrix and is not declared in "
        f"{FCC.DEFAULT_FLOW_DEF}. That is MISSING, not SKIPPED-CONDITION: no "
        f"design of any class can reach it.")


@pytest.mark.parametrize("dc", [c.name for c in CLASSES])
def test_every_class_states_a_state_for_every_covered_step(dc):
    """No cell may be left unstated. An unstated cell is an untested one."""
    cls = PC.CLASSES_BY_NAME[dc]
    missing = [s for s in COVERED_PATH_STEPS if s not in cls.expected]
    assert not missing, (
        f"class {dc} states no expectation for {missing}. Every "
        f"(class, step) cell must carry one of {PC.STATES}.")
    bad = {k: v for k, v in cls.expected.items() if v not in PC.STATES}
    assert not bad, f"class {dc} states unknown expectations {bad}"
    assert MISSING not in cls.expected.values(), (
        f"class {dc} EXPECTS a step to be MISSING. MISSING is never a correct "
        f"expectation -- it is the word for a step nobody wired. If a step is "
        f"legitimately not run for this class the expectation is "
        f"{SKIPPED_CONDITION}.")


# ═════════════════════════════════════════════════════════════════════════════
# 2. THE MATRIX — one test id per cell
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("dc_name,sid", CELLS,
                         ids=[f"{d}-{s}" for d, s in CELLS])
def test_cell(dc_name, sid, trees, flow):
    """The state of one (design class, path step) cell, measured.

    Failure here is one of exactly two things and the message says which:
      * the flow's condition is wrong for this class -- fix the FLOW; or
      * the expectation is wrong -- fix the TABLE, with the argument written
        into `DesignClass.why`.
    Never widen a condition until the step runs for designs it should not.
    """
    cls = PC.CLASSES_BY_NAME[dc_name]
    rec = trees[dc_name]
    want = cls.expected[sid]
    got = state_of(rec["project"], sid, flow)
    step = _step(flow, sid)
    cond = (step or {}).get("condition")
    assert got == want, (
        f"cell ({dc_name}, {sid}): expected {want}, measured {got}.\n"
        f"  class: {cls.why}\n"
        f"  routers written by step 0.5ic's own producers: "
        f"{list(rec['routers']) or '(none)'}\n"
        f"  step condition as declared: {cond}\n"
        f"  tree: {rec['project']}\n"
        f"Decide, in writing, which side is wrong. A pad ring and a seal ring "
        f"are properties of being a DIE, not of being on a shuttle; an IP is "
        f"delivered as a macro and has neither.")


# ═════════════════════════════════════════════════════════════════════════════
# 3. MISSING is not SKIPPED-CONDITION — proven by mutation, not asserted
# ═════════════════════════════════════════════════════════════════════════════
def test_missing_is_not_readable_as_skipped_condition(trees, tmp_path):
    """Break a path step three ways; each must read MISSING, never a skip.

    The three forms are the three that have actually happened here:
      (a) the id is gone from the flow;
      (b) the step is declared and has no gate at all;
      (c) the step is declared and its gate names a program that does not
          exist -- the exact shape of "declared ahead of their programs".
    All three used the SAME project tree that reports SKIPPED-CONDITION on the
    unmutated flow, so the difference measured is the mutation and nothing
    else.
    """
    proj = trees["ip_hardmacro_searched_and_declared"]["project"]
    base = _load_flow()
    assert state_of(proj, "15.5ic", base) == SKIPPED_CONDITION, (
        "the control is not a skip on the unmutated flow, so this test would "
        "be measuring the tree rather than the mutation")

    # (a) the id is gone
    gone = {"steps": [s for s in _steps(base) if str(s.get("id")) != "15.5ic"]}
    assert state_of(proj, "15.5ic", gone) == MISSING

    # (b) declared, no gate
    nogate = json.loads(json.dumps(base, default=str))
    for s in nogate["steps"]:
        if str(s.get("id")) == "15.5ic":
            s.pop("gate", None)
    assert state_of(proj, "15.5ic", nogate) == MISSING

    # (c) declared ahead of its program
    ahead = json.loads(json.dumps(base, default=str))
    for s in ahead["steps"]:
        if str(s.get("id")) == "15.5ic":
            s["gate"] = {"program_exit_zero":
                         "a_program_that_was_never_written . --json x.json"}
    assert state_of(proj, "15.5ic", ahead) == MISSING, (
        "a step whose gate names a program that does not exist reported "
        "SKIPPED-CONDITION. That is the reading every summary gave the three "
        "path steps while they were declared ahead of their programs.")


# ═════════════════════════════════════════════════════════════════════════════
# 4. A step that can only ever SKIP is not a step
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("sid", COVERED_PATH_STEPS)
def test_every_path_step_runs_for_at_least_one_class(sid, trees, flow):
    runners = [dc.name for dc in CLASSES
               if state_of(trees[dc.name]["project"], sid, flow) == RUNS]
    assert runners, (
        f"step {sid} is SKIPPED-CONDITION for every one of the "
        f"{len(CLASSES)} design classes in this matrix. A path-specific step "
        f"that can only ever skip is not a step -- either its condition names "
        f"an artefact no producer writes, or no class of design can satisfy "
        f"it. Classes tried: {[c.name for c in CLASSES]}")


@pytest.mark.parametrize("sid", [s for s in COVERED_PATH_STEPS if s != "0.5ic"])
def test_every_conditional_path_step_skips_for_at_least_one_class(
        sid, trees, flow):
    """The other half. A condition satisfied by every class is not a router.

    Without this, "make the cell green by widening the condition" passes the
    test above for every step at once, which is precisely the failure the
    brief forbids.
    """
    skippers = [dc.name for dc in CLASSES
                if state_of(trees[dc.name]["project"], sid,
                            flow) == SKIPPED_CONDITION]
    assert skippers, (
        f"step {sid} RUNS for every design class in this matrix. It is "
        f"declared path-specific, so some class must legitimately not reach "
        f"it; a condition satisfied by everything routes nothing.")


# ═════════════════════════════════════════════════════════════════════════════
# 5. Does a RUNNING step's gate reach a verdict, and can that verdict go RED?
# ═════════════════════════════════════════════════════════════════════════════
def _run_gate(project: Path, command: str) -> Tuple[int, str, str]:
    tok, *rest = command.split()
    prog = PROGRAMS / f"{tok}.py"
    proc = subprocess.run([sys.executable, str(prog), *rest],
                          cwd=str(project), capture_output=True, text=True,
                          timeout=600)
    return proc.returncode, proc.stdout, proc.stderr


RUN_CELLS = [(dc.name, sid) for dc in CLASSES for sid in COVERED_PATH_STEPS
             if dc.expected.get(sid) == RUNS]


@pytest.mark.parametrize("dc_name,sid", RUN_CELLS,
                         ids=[f"{d}-{s}" for d, s in RUN_CELLS])
def test_a_running_steps_gate_reaches_a_verdict(dc_name, sid, trees, flow):
    """Every blocking clause executes and CONCLUDES something.

    rc 0 / 1 / 2 are three verdicts -- a pass, a finding about silicon, and an
    honest refusal to check. Anything else is a gate that did not conclude:
    rc 3 is a bad invocation and a traceback is a gate that fell over. Both
    reach a reader as a step that "did not fail".
    """
    proj = trees[dc_name]["project"]
    step = _step(flow, sid)
    assert step is not None
    cmds = _gate_commands(step)
    assert cmds, (f"step {sid} declares no executable gate clause, so it has "
                  f"no verdict of its own to reach")
    for cmd in cmds:
        tok = cmd.split()[0]
        assert _resolves(tok), (
            f"step {sid}'s gate names {tok}, which is not a program in "
            f"{PROGRAMS}. The step is declared ahead of its program.")
        rc, out, err = _run_gate(proj, cmd)
        assert "Traceback (most recent call last)" not in err, (
            f"step {sid} gate `{cmd}` on class {dc_name} raised:\n"
            f"{err[-3000:]}")
        assert rc in (0, 1, 2), (
            f"step {sid} gate `{cmd}` on class {dc_name} exited {rc}. Only "
            f"0 (pass), 1 (a finding) and 2 (could not check) are verdicts; "
            f"3 is a bad invocation.\nstdout:\n{out[-2000:]}\n"
            f"stderr:\n{err[-2000:]}")


# ── RED WITNESSES ────────────────────────────────────────────────────────────
# One NAMED, minimal defect per path step, planted in a COPY of a class tree
# that RUNS the step. "The tree happened to be red" is not a proof that a gate
# can refuse; the witness says WHICH refusal was provoked, so a future
# weakening that removes exactly that predicate turns exactly this test.
#
# Four of the five witnesses are an ABSENT ARTEFACT, and that is not laziness:
# "an absent report is not a skip -- it means the producer never ran" is the
# refusal each of those gates was written to make, and reading an absence as a
# skip is the disease this whole file exists for.
def _witness_absent(rel: str):
    def plant(project: Path) -> str:
        tgt = project / rel
        if tgt.exists():
            tgt.unlink()
        return f"{rel} absent — the producer never ran, which is not a skip"
    return plant


def _witness_two_routers(project: Path) -> str:
    """A tree that selects two delivery paths at once.

    `tapeout_declaration_check` refuses this rather than resolving it by
    deleting one, and that refusal is the only thing keeping the three routes
    mutually exclusive.
    """
    sys.path.insert(0, str(PROGRAMS))
    import _tapeout_declaration as TD             # noqa: E402
    import _submission_template as ST             # noqa: E402
    for rel, marker in ((TD.SELF_TAPEOUT_REL, TD.SELF_TAPEOUT_MARKER),
                        (ST.NO_TEMPLATE_REL, ST.NO_TEMPLATE_MARKER)):
        tgt = project / rel
        tgt.parent.mkdir(parents=True, exist_ok=True)
        if not tgt.is_file():
            tgt.write_text(marker + "\n")
    return "two router files at once — the tree selects two delivery paths"


def _witness_hardmacro_view_missing(project: Path) -> str:
    """The IP terminal's own refusal: a kit delivered with a view short.

    The kit is built by `test_digital_hardmacro_check.make_kit`, which
    CONSTRUCTS its GDSII stream from record bytes. Reusing it rather than
    writing a second builder is deliberate: two builders that agree by
    construction prove nothing, and a hand-edited GDS is never acceptable here.
    """
    import test_digital_hardmacro_check as DHC    # noqa: E402
    DHC.make_kit(project)
    (project / "phase3" / "stage4" / "hardmacro" / "macro_a.lef").unlink()
    return "a hardmacro kit delivered with its LEF view missing (VIEW_MISSING)"


def _witness_seal_ring_failed(project: Path) -> str:
    """A die-finishing measurement that says the seal ring is not there.

    Unlike its sibling at 15.5ic, this gate answers an ABSENT report with rc 2
    (`DISCLOSED_SKIP` — "the producer has not run, nothing is claimed"), which
    is its documented contract and not a finding. So the witness is a report
    that CLAIMS a failure: the question this test asks is whether the gate
    reads the producer's measurement at all, and rc 2 would answer a different
    one.
    """
    rep = project / "reports" / "phase3" / "die_finishing.json"
    rep.parent.mkdir(parents=True, exist_ok=True)
    rep.write_text(json.dumps({
        "producer": "die_finishing_gen",
        "seal_ring": {"state": "FAIL",
                      "reason": "the generator ran and inserted no ring"},
        "die_id": {"state": "NOT_DETERMINED", "reason": "not reached"},
    }, indent=2) + "\n")
    return ("a die-finishing report measuring seal_ring=FAIL — a die with no "
            "scribe protection")


RED_WITNESS = {
    "0.5ic": _witness_two_routers,
    "15.5ic": _witness_absent("reports/phase3/padring.json"),
    "26.5ic": _witness_seal_ring_failed,
    "37.5ic": _witness_absent("reports/phase3/tapeout_precheck.json"),
    "37.5ip": _witness_hardmacro_view_missing,
}


@pytest.mark.parametrize("sid", COVERED_PATH_STEPS)
def test_a_running_steps_gate_can_go_red(sid, trees, flow, tmp_path):
    """Plant this step's named defect in a class that RUNS it; the gate must
    REFUSE.

    rc=2 does not count. `[CANNOT CHECK]` is an honest absence, not a finding,
    and a guard that can only ever say "I could not look" guards nothing. rc=0
    on a planted defect is worse: it is the shape every one of the measured
    failures in this area had.
    """
    step = _step(flow, sid)
    assert step is not None
    cmds = [c for c in _gate_commands(step) if _resolves(c.split()[0])]
    assert cmds, f"step {sid} declares no runnable gate clause"
    runners = [dc for dc in CLASSES if dc.expected.get(sid) == RUNS]
    assert runners, (
        f"no class in this matrix RUNS step {sid}, so its gate cannot be "
        f"exercised here at all")

    src = trees[runners[0].name]["project"]
    work = tmp_path / f"redwitness_{sid.replace('.', '_')}"
    shutil.copytree(src, work)
    defect = RED_WITNESS[sid](work)

    seen: List[str] = []
    reds: List[str] = []
    for cmd in cmds:
        rc, out, err = _run_gate(work, cmd)
        seen.append(f"{cmd.split()[0]}=rc{rc}")
        if rc == 1:
            reds.append(cmd.split()[0])
    assert reds, (
        f"step {sid}: planted {defect} in class {runners[0].name} and no "
        f"blocking clause of its gate refused. Measured: {seen}. A "
        f"path-specific step whose gate cannot go red is a step in name only.")


def test_the_ip_terminals_gate_is_positive_negative_and_vacuous(trees,
                                                                tmp_path):
    """37.5ip's gate, all three arms, because rc=2 is not rc=0 and not rc=1.

    The IP terminal is the one path step whose class tree carries no artefact
    for its gate to look at until step 37 has run, so it is the one place a
    "cannot check" could be mistaken for a clean terminal. Three arms, three
    exit codes, one command.
    """
    import test_digital_hardmacro_check as DHC    # noqa: E402
    cls = "ip_hardmacro_searched_and_declared"
    cmd = "digital_hardmacro_check . --json reports/phase3/digital_hardmacro.json"

    vac = tmp_path / "ip_vacuous"
    shutil.copytree(trees[cls]["project"], vac)
    rc_vac, out_vac, _ = _run_gate(vac, cmd)
    assert rc_vac == 2, (
        f"a project with no hardmacro package must REFUSE to check (rc 2), "
        f"not pass. Got rc={rc_vac}:\n{out_vac[-1500:]}")

    ok = tmp_path / "ip_pass"
    shutil.copytree(trees[cls]["project"], ok)
    DHC.make_kit(ok)
    rc_ok, out_ok, _ = _run_gate(ok, cmd)
    assert rc_ok == 0, (
        f"a complete, agreeing hardmacro kit must PASS. Got rc={rc_ok}:\n"
        f"{out_ok[-1500:]}")

    bad = tmp_path / "ip_fail"
    shutil.copytree(trees[cls]["project"], bad)
    DHC.make_kit(bad)
    (bad / "phase3" / "stage4" / "hardmacro" / "macro_a.lef").unlink()
    rc_bad, out_bad, _ = _run_gate(bad, cmd)
    assert rc_bad == 1, (
        f"a kit delivered with a view missing must be REFUSED. Got "
        f"rc={rc_bad}:\n{out_bad[-1500:]}")


# ═════════════════════════════════════════════════════════════════════════════
# 6. The routers, and the promise that a skip is never silent
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("dc_name", [c.name for c in CLASSES])
def test_step_0_5ic_writes_at_most_one_router_file(dc_name, trees):
    """Three routes, three files, MUTUALLY EXCLUSIVE by construction.

    A tree carrying two of them is a tree that selects two paths, and
    `tapeout_declaration_check` refuses it rather than resolving it by
    deleting one. This asserts the producers never build such a tree.
    """
    routers = trees[dc_name]["routers"]
    assert len(routers) <= 1, (
        f"class {dc_name} came out of step 0.5ic's own producers carrying "
        f"{list(routers)} — more than one router file, so it selects more "
        f"than one delivery path.")


ROUTED_CLASSES = [c.name for c in CLASSES
                  if not c.zero_five_ic_gate_must_refuse]


@pytest.mark.parametrize("dc_name", ROUTED_CLASSES)
def test_a_class_that_selects_a_route_can_pass_step_0_5ics_own_gate(
        dc_name, trees, flow):
    """A route no design can traverse is not a route.

    Step 0.5ic is the router: it writes the one file that decides which
    terminal a design reaches, and every path step blocks on it. So for each
    class that DOES select a route, 0.5ic's own gate must be passable — not
    "passable in principle", but exit 0 on the tree its own two producers
    built for that class, with every question they were given answered.

    The failure this closes is a route that exists in the flow and is gated
    shut: the yaml declares three mutually exclusive routers and three
    terminals, and if a gate refuses every tree that takes one of them, that
    third path is decoration. It is the same defect as a step conditioned on
    the wrong thing, moved one level up — and it presents the same way, as a
    step that "fails for now" on a design nobody has finished.
    """
    rec = trees[dc_name]
    assert rec["routers"], (
        f"class {dc_name} is declared as one that selects a route and step "
        f"0.5ic's producers wrote no router file for it")
    step = _step(flow, "0.5ic")
    assert step is not None
    refused = []
    for cmd in _gate_commands(step):
        if not _resolves(cmd.split()[0]):
            continue
        rc, out, err = _run_gate(rec["project"], cmd)
        if rc != 0:
            refused.append((cmd.split()[0], rc, (out or err)[:600]))
    assert not refused, (
        f"class {dc_name} selected route {list(rec['routers'])} and step "
        f"0.5ic's own gate refuses it, so NO design of this class can pass "
        f"the step every path step blocks on:\n"
        + "\n".join(f"  {t} rc={rc}: {msg}" for t, rc, msg in refused)
        + f"\n  tree: {rec['project']}\n"
        "Fix the gate or fix the producers — but a route that cannot be "
        "traversed must not stay in the flow as if it could.")


@pytest.mark.parametrize(
    "dc_name",
    [c.name for c in CLASSES if c.zero_five_ic_gate_must_refuse])
def test_a_class_with_no_route_is_refused_by_step_0_5ics_own_gate(
        dc_name, trees, flow):
    """The promise the flow makes, kept or not.

    Every path step's `condition_kind: design_dependent` comment says the same
    thing: the "someone forgot" case is not lost to a silent skip, because it
    is 0.5ic never having run, "which its own gate refuses as NEVER_LOOKED
    rather than leaving to be inferred from a downstream skip".

    That promise is what makes SKIPPED-CONDITION honest on these classes. If
    it is not kept, four terminals skip in silence and the design reaches
    tape-out having passed no submission check of any kind.
    """
    rec = trees[dc_name]
    assert not rec["routers"], (
        f"{dc_name} was built as a no-route class and carries "
        f"{list(rec['routers'])}")
    step = _step(flow, "0.5ic")
    assert step is not None
    refusals = []
    for cmd in _gate_commands(step):
        if not _resolves(cmd.split()[0]):
            continue
        rc, out, err = _run_gate(rec["project"], cmd)
        if rc != 0:
            refusals.append((cmd.split()[0], rc, (out or err)[:400]))
    assert refusals, (
        f"class {dc_name} selects NO delivery path — every one of "
        f"{[s for s in COVERED_PATH_STEPS if s != '0.5ic']} skips by "
        f"condition — and step 0.5ic's own gate passed it. The skips are then "
        f"indistinguishable from a correct not-applicable, and nothing in the "
        f"run says the design was never routed.")
