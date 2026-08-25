"""DIMENSION 9 of the flow-step coverage matrix — ``verdict_consumed``.

    "When this step FAILs, does that verdict reach the run's EXIT CODE —
     or is it reported and discarded?"

Dimensions 1-7 interrogate the GATE. Dimension 8 interrogates the CATCHER.
This one interrogates the CONSUMER: the walk from a step's own FAIL status to
``ok=False`` to ``overall="FAIL"`` to a non-zero exit. A gate can be wired
(d1), reachably falsifiable (d2), on-target (d4), complete (d7) and still be
ADVISORY IN PRACTICE, because nothing consumes its verdict where it matters.

====================================================================
WHY THIS IS A NINTH QUESTION AND NOT A RESTATEMENT OF THE SECOND
====================================================================
Dimension 2 proves a gate CAN reach a genuine FAIL verdict. It stops there, and
says so: it grades ``_check_program_exit_zero`` / ``_check_files_exist`` /
``_check_json_field_true`` at the CLAUSE level. Whether that clause's FAIL
becomes the STEP's FAIL, and whether that step's FAIL survives the verdict pass,
are two further edges nothing in d1-d8 traverses.

They are not hypothetical edges. ``flow_compliance_check`` carries three live
mechanisms that take a real FAIL and drop it before the exit code, all measured
on the tree this module was written against:

  1. ``INFORMATIONAL_GATES`` (4 entries) — ``_step_failure_is_informational_only``
     removes a step from ``failing`` when EVERY one of its FAIL reasons cites one
     of them. The module's own comment for the ``l25_...`` entry states the
     promotion trigger and names the risk in the same breath: *"'advisory'
     becomes the same 'FAIL and the flow continued anyway' mistake"*.
  2. ``advisory_program_exit_zero`` — measured live: **37 of 213** gate clauses.
     A FAIL there never becomes the step's FAIL at all.
  3. ``structural_only_verdict`` — under ``--phase 2 --strict-structural``,
     ``scoped`` collapses to P0 plus the analog track and every other step's
     verdict is, in the module's own words, *"REPORTED but NOT factored into
     Overall"*.

====================================================================
WHAT THIS MODULE DOES **NOT** CLAIM, STATED FIRST
====================================================================
**It does not speak about repo-hygiene gates, and the campaign's founding
example was one.** ``prose_polarity_consulted_check`` — the gate whose 35-commit
red run motivated this dimension — occurs **zero times** in
``flow/phase1_phase2_phase3.yaml``. It is invoked from
``tools/ci/repo_hygiene_gates.sh``. The matrix's unit is a FLOW STEP; a gate
that is not a flow step's gate has no cell here and never will. That hole is
real and it is somewhere else. It is recorded here rather than quietly
inherited, because a dimension that let a reader believe it covered the
motivating case would be measuring something adjacent and reporting it as if it
answered the question — the disease in ``README.md``'s "one rule".

It also does not claim a FAIL is *correct*, or that the gate measures the right
thing (d4), or that the artefact it read says what the design does. It claims
one edge: FAIL in, non-zero out.

====================================================================
THE THREE LEGS
====================================================================
Each cell is decided by the legs that APPLY to it. A cell is ENFORCED when every
applicable leg passes; the per-leg applicability is derived live, never pinned.

**L1 — BLOCKING REACH (live yaml).** The step declares at least one clause whose
FAIL can become the step's FAIL. An advisory-only gate cannot, no matter how
falsifiable its program is. Denominator: the 68 steps that declare a ``gate``.
Measured today: 0 advisory-only steps, 176 blocking of 213 clauses.

**L2 — NOT DISCARDED AS INFORMATIONAL (real consumer, in process).** A real
:class:`flow_compliance_check.StepResult` is built for the step at status FAIL,
with its reasons written in the grammar ``_evaluate_gate`` really emits
(``program failed: <cmd>``) and naming the step's OWN resolved gate programs.
The REAL ``_step_failure_is_informational_only`` is then asked whether it would
discard it. It must say no.

This leg is what L3's substitution cannot see, and that is why it exists. The
exclusion is keyed on the gate NAME appearing in the reason text, so a stand-in
gate erases the mechanism entirely: measure L3 alone and this dimension would
report a clean sweep while a step whose whole blocking gate set had been moved
into ``INFORMATIONAL_GATES`` sat green inside it.

**L3 — REACHES THE EXIT CODE (behavioural, real ``main()``).** The real
``programs/flow_compliance_check.py`` is run as a subprocess, ``--strict``,
against a synthesized project and a flow yaml built from the step's OWN live
dict, with the step's gate held at a known tier. Two arms, and the second is
what makes the first falsifiable:

    FAIL-tier  ``{"files_exist": ["_d9_gate/absent.flag"]}``  → rc != 0,
               and this step listed at status FAIL in the ``--json`` report.
    PASS-tier  ``{"files_exist": ["_d9_gate/gate_ok.flag"]}`` → rc == 0.

Without the PASS arm, a harness that returned rc=1 for an unrelated reason —
a crash, a bad invocation, an unsatisfied precondition — would certify every
step in the flow as consuming its verdict. The PASS arm is the control that
prices that.

**P0 IS MEASURED ON ITS OWN MECHANISM, NOT A STAND-IN.** P0 declares no
``gate:`` key at all; its verdict is emitted by
``_run_structural_rtl_gates``. Substituting a gate onto P0 does not take —
measured: ``check_step`` resolves it SKIPPED-CONDITION before any injected
clause is read, in both arms. So P0's L3 drives the real umbrella against RTL in
a synthesized project, and the real umbrella FAILs, and the run exits 1. That
makes P0 the one cell in this dimension whose ENFORCED verdict is measured
against the mechanism it is named after, and :func:`matrix_cell_substitution`
reports exactly that.

====================================================================
KNOWN GAPS — read these before quoting a green run
====================================================================
1. **L3 measures the DEFAULT invocation.** ``--phase 2 --strict-structural``
   deliberately scopes 60-odd steps out of the verdict, and that is an owner
   decision recorded at ``flow_compliance_check.py``'s
   ``structural_only_verdict`` block, not a defect for a cell to charge. This
   dimension does not grade that flag combination per-step; it pins the SHAPE of
   the exclusion instead, in
   :func:`test_d9_structural_only_scoping_is_still_the_documented_two_member_set`,
   so the set cannot widen without this module saying so.
2. **L3's stand-in gate is a ``files_exist`` clause**, so it exercises the
   step's ``files_exist`` consumption path, not its ``program_exit_zero`` path.
   The two converge at ``_evaluate_gate``'s return, which is upstream of
   everything this dimension measures — but they are not the same clause type,
   and that is disclosed rather than papered over.
3. **One edge is asserted and not driven: the runners.** A non-zero exit from
   ``flow_compliance_check`` is only a stop if a caller honours it.
   :func:`test_d9_every_one_shot_runner_reads_the_checkers_returncode` covers
   that by AST over the runners, which proves the return code is READ, not that
   the branch taken on it aborts. Closing that needs a live runner invocation
   per runner, which is a phase-scale job and is not done here.

====================================================================
MUTATION PROOFS — every leg was reddened, then reverted
====================================================================
Recorded by :mod:`matrix_mutation_ledger` where it can be replayed; the ones
proved by in-test fixtures live in the self-checks at the bottom of this file:

  L1  a scratch yaml demotes step 21's only blocking clause to
      ``advisory_program_exit_zero``    -> step21 red
  L2  ``INFORMATIONAL_GATES`` gains step 21's whole resolved gate set
      (monkeypatched on the real module) -> step21 red
  L3  the FAIL-tier stand-in is swapped for the PASS-tier one
      -> step21 red on the "rc != 0" assertion
  L3-control  the PASS-tier arm is swapped for the FAIL-tier one
      -> step21 red on the "rc == 0" assertion
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pytest
import yaml

from matrix import cells as C, flowref as F, waivers as W

sys.path.insert(0, str(F.PLUGIN_ROOT / "programs"))
import flow_compliance_check as FCC  # noqa: E402

DIM = 9

FCC_PY = F.PLUGIN_ROOT / "programs" / "flow_compliance_check.py"
PROGRAMS_DIR = F.PLUGIN_ROOT / "programs"

#: Where the stand-in gate's control files live inside the synthesized project.
_GATE_DIR = "_d9_gate"
_GATE_OK = f"{_GATE_DIR}/gate_ok.flag"
_GATE_ABSENT = f"{_GATE_DIR}/absent.flag"

PASS_GATE: Dict[str, object] = {"files_exist": [_GATE_OK]}
FAIL_GATE: Dict[str, object] = {"files_exist": [_GATE_ABSENT]}

#: P0 has no ``gate:`` key; its verdict comes from ``_run_structural_rtl_gates``.
#: Derived, not pinned — a second gate-less step must not silently inherit the
#: umbrella treatment, it must make :func:`test_d9_exactly_one_step_declares_no_gate`
#: fail and force a human look.
def _gateless_steps() -> Tuple[str, ...]:
    return tuple(F.normalize_id(s) for s in F.step_ids() if not F.gate_clauses(s))


_SUBPROCESS_TIMEOUT_S = 900

#: RTL good enough for the structural umbrella to have something to read.
_P0_RTL = ("phase2/stage1/rtl/top.v", "module top; endmodule\n")


# ══════════════════════════════════════════════════════════════════════
# Denominators — printed, never assumed
# ══════════════════════════════════════════════════════════════════════
def denominators() -> Dict[str, int]:
    """The live population each leg is measured over. Recomputed every call."""
    ids = F.step_ids()
    clauses = [c for s in ids for c in F.gate_clauses(s)]
    return {
        "steps": len(ids),
        "gated_steps": len([s for s in ids if F.gate_clauses(s)]),
        "gateless_steps": len(_gateless_steps()),
        "steps_with_resolved_gate_programs": len(
            [s for s in ids if F.gate_programs(s)]),
        "clauses": len(clauses),
        "blocking_clauses": len([c for c in clauses if c.is_blocking]),
        "advisory_clauses": len([c for c in clauses if c.is_advisory]),
        "informational_gates": len(FCC.INFORMATIONAL_GATES),
    }


def test_d9_denominators_are_disclosed(capsys):
    """PRINT the population, and refuse a denominator that has gone to zero.

    A leg measured over an empty set passes vacuously and reports a clean
    dimension. This is the same guard d5 carries over its derived-dependency
    count and for the same reason: the campaign was convened over a runtime
    ordering guard that saw 0 violations because it had been starved of input.
    """
    d = denominators()
    with capsys.disabled():
        print("\n  DIMENSION 9 (verdict_consumed) — live denominators")
        for k, v in d.items():
            print(f"    {k:38s} {v}")
    assert d["steps"] == len(C.cells_for(DIM)), (
        f"{len(C.cells_for(DIM))} cells for {d['steps']} steps — the ledger and "
        f"the flow yaml disagree about what a step is")
    for leg, key in (("L1", "gated_steps"),
                     ("L2", "steps_with_resolved_gate_programs"),
                     ("L3", "steps")):
        assert d[key] > 0, (
            f"leg {leg}'s denominator ({key}) is 0 — every {leg} cell would "
            f"pass without measuring anything")
    assert d["blocking_clauses"] > 0, (
        "no gate clause in the live yaml is blocking; L1 would be vacuous")


# ══════════════════════════════════════════════════════════════════════
# L1 — blocking reach
# ══════════════════════════════════════════════════════════════════════
def _l1(step_id) -> Tuple[bool, str]:
    """(passes, why). A step with no clause at all is not L1's subject."""
    clauses = F.gate_clauses(step_id)
    if not clauses:
        return True, "no gate clauses — L1 does not apply (see L3's P0 arm)"
    blocking = [c for c in clauses if c.is_blocking]
    if blocking:
        kinds = sorted({c.kind for c in blocking})
        return True, f"{len(blocking)}/{len(clauses)} clauses blocking: {kinds}"
    return False, (
        f"all {len(clauses)} gate clauses are advisory "
        f"({sorted({c.kind for c in clauses})}); a FAIL in any of them never "
        f"becomes this step's FAIL, so nothing this gate finds can stop a run")


# ══════════════════════════════════════════════════════════════════════
# L2 — not discarded as informational
# ══════════════════════════════════════════════════════════════════════
def _fail_result(step_id, gate_names: Tuple[str, ...]) -> "FCC.StepResult":
    """A real StepResult at FAIL, in the reason grammar ``_evaluate_gate`` emits.

    The grammar is not invented here: ``_step_failure_is_informational_only``'s
    own docstring states it (``program failed: <cmd>``) and the function
    ``startswith``-scans for exactly that prefix.
    """
    step = F.step_by_id(step_id) or {}
    return FCC.StepResult(
        id=step_id,
        name=str(step.get("name", "")),
        stage=str(step.get("stage", "")),
        status="FAIL",
        reasons=[f"program failed: python3 programs/{n}.py . --json r.json"
                 for n in gate_names],
    )


def _l2(step_id) -> Tuple[bool, str]:
    names = tuple(sorted(F.gate_programs(step_id)))
    if not names:
        return True, ("step resolves no gate program, so it emits no "
                      "`program failed:` reason and the informational "
                      "exclusion has nothing to key on")
    discarded = FCC._step_failure_is_informational_only(
        _fail_result(step_id, names))
    if not discarded:
        inf = sorted(set(names) & set(FCC.INFORMATIONAL_GATES))
        note = f"; {len(inf)} informational among {len(names)}: {inf}" if inf else ""
        return True, f"FAIL survives the informational filter{note}"
    return False, (
        f"every resolved gate program of this step is in INFORMATIONAL_GATES "
        f"({sorted(names)}), so the real "
        f"_step_failure_is_informational_only() removes the step from "
        f"`failing`: it can FAIL, be printed, and leave the exit code at 0")


# ══════════════════════════════════════════════════════════════════════
# L3 — reaches the exit code
# ══════════════════════════════════════════════════════════════════════
def _write_flow(step_id, path: Path, gate: Optional[Dict[str, object]]) -> None:
    """A flow yaml holding ONLY this step, verbatim from the live one.

    ``blocks_on`` is dropped (an unsatisfied upstream resolves the step to
    DEFERRED-BY-UPSTREAM, which measures the cascade, not the consumption).
    ``required_outputs`` and ``condition`` are dropped so the step's status is
    decided by its GATE alone — a MISSING verdict also exits non-zero, and
    letting it in would certify consumption on d8's evidence rather than this
    dimension's.
    """
    doc = F.load_flow()
    top = {k: v for k, v in doc.items() if k != "steps"}
    step = dict(F.step_by_id(step_id))
    step.pop("blocks_on", None)
    if gate is not None:
        step["gate"] = gate
        step.pop("required_outputs", None)
        step.pop("condition", None)
    top["steps"] = [step]
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(top, fh, allow_unicode=True, sort_keys=False)


def _run_checker(step_id, gate: Optional[Dict[str, object]], root: Path,
                 with_rtl: bool = False) -> Tuple[int, Optional[str], Optional[str]]:
    """Run the REAL checker. Returns ``(returncode, step status, overall)``.

    ``with_rtl`` IS LOAD-BEARING AND DEFAULTS OFF. `flow_compliance_check`
    injects the P0 structural umbrella into every run whose project carries
    RTL — it is not a step of the one-step yaml, it appears anyway — and on a
    synthesized tree that umbrella FAILs (`rig_topology_not_found`,
    `generated_docs/ absent`), and P0 is unconditionally inside `scoped`. So a
    project with RTL exits 1 whatever the step under test did, and the PASS-tier
    control arm can never return 0. MEASURED while building this module: with
    RTL present, step D1 resolved PASS and the run still exited 1, on P0's
    verdict. That is the harness certifying the whole dimension on P0's failure
    — the exact vacuity the control arm exists to price. Only the own-mechanism
    arm, whose subject IS the umbrella, turns it on.
    """
    project = root / "proj"
    (project / _GATE_DIR).mkdir(parents=True, exist_ok=True)
    (project / _GATE_OK).write_text("d9 gate control\n", encoding="utf-8")
    if with_rtl:
        rtl = project / _P0_RTL[0]
        rtl.parent.mkdir(parents=True, exist_ok=True)
        rtl.write_text(_P0_RTL[1], encoding="utf-8")

    flow = root / "flow.yaml"
    _write_flow(step_id, flow, gate)
    report = root / "report.json"
    proc = subprocess.run(
        [sys.executable, str(FCC_PY), str(project),
         "--flow-def", str(flow), "--json", str(report), "--strict"],
        capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT_S,
    )
    status = overall = None
    if report.is_file():
        doc = json.loads(report.read_text(encoding="utf-8"))
        overall = doc.get("overall")
        for entry in doc.get("steps") or []:
            if str(entry.get("id")) == F.normalize_id(step_id):
                status = entry.get("status")
    return proc.returncode, status, overall


def _uses_own_mechanism(step_id) -> bool:
    """True when this step's L3 runs the step's OWN verdict producer.

    Today that is exactly the gate-less steps: a substituted ``gate:`` never
    reaches ``check_step`` for them, so they are driven through the real
    structural umbrella instead.
    """
    return F.normalize_id(step_id) in _gateless_steps()


# ══════════════════════════════════════════════════════════════════════
# Parametrization + the campaign hooks
# ══════════════════════════════════════════════════════════════════════
def _marks(step_id):
    m = W.xfail_mark(step_id, DIM)
    return [m] if m is not None else []


def _cell_params():
    return [pytest.param(c, marks=_marks(c.step_id),
                         id=f"step{F.normalize_id(c.step_id)}")
            for c in C.cells_for(DIM)]


def matrix_na_precondition(step_id) -> Optional[str]:
    """No cell of this dimension is NA.

    Every flow step either declares a gate (L1/L2/L3 all apply) or is the
    structural umbrella (L3 applies against its own producer). There is no step
    for which "does its verdict reach the exit code" is a malformed question, so
    an NA here would be a skip wearing a hat.
    """
    return None


def matrix_cell_state(step_id) -> str:
    """``"ENFORCED"`` / ``"WAIVED"`` / ``"NA"`` for one cell of this dimension."""
    if matrix_na_precondition(step_id) is not None:
        return "NA"
    if W.waiver_for(step_id, DIM) is not None:
        return "WAIVED"
    return "ENFORCED"


def matrix_cell_substitution(step_id) -> Optional[str]:
    """Was this cell's ENFORCED verdict measured against the step's OWN producer?

    ``None`` for the gate-less steps, whose L3 drives the real
    ``_run_structural_rtl_gates`` umbrella. A disclosure for every other step,
    whose L3 verdict comes from a ``files_exist`` stand-in held at a known tier.

    The split is RE-DERIVED from :func:`_gateless_steps` against the live yaml,
    not read off a pinned tuple, so a flow edit re-points it instead of leaving
    the census publishing a stale OWN count.
    """
    if matrix_cell_state(step_id) != "ENFORCED":
        return None
    if _uses_own_mechanism(step_id):
        return None
    return (
        "L3 holds this step's gate at a known tier with a two-arm "
        "`files_exist` stand-in, so what it measures is the consumption path "
        "from a step FAIL to the process exit code, NOT this step's own gate "
        "reaching that FAIL (dimension 2's question). L2 covers the part the "
        "stand-in erases — the informational-gate exclusion keys on the real "
        "gate NAME — and is measured against this step's own resolved programs."
    )


# ══════════════════════════════════════════════════════════════════════
# THE CELLS
# ══════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("cell", _cell_params())
def test_d9_verdict_consumed(cell, tmp_path):
    """One cell per flow step: a FAIL here must reach the exit code."""
    sid = cell.step_id
    l1_ok, l1_why = _l1(sid)
    assert l1_ok, f"{cell.label} L1: {l1_why}"

    l2_ok, l2_why = _l2(sid)
    assert l2_ok, f"{cell.label} L2: {l2_why}"

    if _uses_own_mechanism(sid):
        rc, status, overall = _run_checker(sid, None, tmp_path / "own",
                                           with_rtl=True)
        assert rc != 0 and status == "FAIL", (
            f"{cell.label} L3(own): the structural umbrella FAILed nothing, or "
            f"its FAIL did not reach the exit code — rc={rc} status={status!r} "
            f"overall={overall!r}. This step's verdict is produced by "
            f"_run_structural_rtl_gates, and this arm drives it for real.")
        return

    rc_fail, st_fail, ov_fail = _run_checker(sid, FAIL_GATE, tmp_path / "fail")
    assert st_fail == "FAIL", (
        f"{cell.label} L3: the FAIL-tier stand-in did not resolve this step to "
        f"FAIL (got {st_fail!r}); the arm measured nothing about consumption. "
        f"rc={rc_fail} overall={ov_fail!r}")
    assert rc_fail != 0, (
        f"{cell.label} L3: the step resolved FAIL and overall={ov_fail!r}, yet "
        f"the checker exited 0. This step's verdict is REPORTED and DISCARDED "
        f"— it can go red without stopping anything.")

    rc_pass, st_pass, ov_pass = _run_checker(sid, PASS_GATE, tmp_path / "pass")
    assert st_pass == "PASS" and rc_pass == 0, (
        f"{cell.label} L3-control: with the PASS-tier stand-in the run must "
        f"exit 0, else the FAIL arm's rc!=0 is not evidence about this step — "
        f"rc={rc_pass} status={st_pass!r} overall={ov_pass!r}")


# ══════════════════════════════════════════════════════════════════════
# SELF-CHECKS — the legs must be able to go red
# ══════════════════════════════════════════════════════════════════════
def _probe_step():
    """A live step with >= 1 blocking program clause. Derived, never pinned."""
    for c in C.cells_for(DIM):
        if F.gate_programs(c.step_id) and any(
                cl.is_blocking and cl.program for cl in F.gate_clauses(c.step_id)):
            return c.step_id
    raise RuntimeError("no step declares a blocking program clause")


#: The clause keys ``flowref`` grades as blocking. Demoting every one of them
#: is how L1's mutation arm builds an advisory-only gate. The gate grammar nests
#: clauses inside ``all_of`` / ``any_of`` containers, so this recurses: an
#: earlier version rewrote only the TOP-LEVEL keys, and since every real gate in
#: the flow is ``{"all_of": [...]}`` it changed nothing at all while reporting a
#: successful mutation. A mutation arm that does not mutate is worse than none —
#: it certifies the leg it was supposed to test.
_BLOCKING_CLAUSE_KEYS = (
    "program_exit_zero", "optional_program_exit_zero",
    "files_exist", "json_field_true",
)


def _demote_to_advisory(node):
    """Rewrite every blocking clause key in a gate tree to the advisory one."""
    if isinstance(node, list):
        return [_demote_to_advisory(n) for n in node]
    if not isinstance(node, dict):
        return node
    out = {}
    for key, value in node.items():
        if key in _BLOCKING_CLAUSE_KEYS:
            out["advisory_program_exit_zero"] = value
        else:
            out[key] = _demote_to_advisory(value)
    return out


def test_d9_l1_reddens_when_a_steps_only_blocking_clause_goes_advisory(tmp_path):
    """MUTATION ARM for L1, against a scratch yaml — never the real one."""
    sid = _probe_step()
    doc = F.load_flow()
    steps = []
    for raw in doc["steps"]:
        if F.normalize_id(raw.get("id")) != F.normalize_id(sid):
            steps.append(raw)
            continue
        mutated = dict(raw)
        mutated["gate"] = _demote_to_advisory(mutated.get("gate") or {})
        steps.append(mutated)
    scratch = tmp_path / "mutated.yaml"
    with scratch.open("w", encoding="utf-8") as fh:
        yaml.safe_dump({**{k: v for k, v in doc.items() if k != "steps"},
                        "steps": steps}, fh, allow_unicode=True, sort_keys=False)

    original = F.FLOW_YAML
    F.set_flow_yaml(scratch)
    C.rebuild()
    try:
        ok, why = _l1(sid)
    finally:
        F.set_flow_yaml(original)
        C.rebuild()
    assert not ok, (
        f"step {sid}'s gate was rewritten so every clause is advisory and L1 "
        f"still passed ({why}); the leg cannot detect an advisory-only gate and "
        f"is worthless")


def test_d9_l2_reddens_when_a_steps_whole_gate_set_becomes_informational(
        monkeypatch):
    """MUTATION ARM for L2, against the REAL consumer function.

    ``INFORMATIONAL_GATES`` is monkeypatched on the imported module, so what
    runs is ``_step_failure_is_informational_only`` itself — not a copy of its
    logic that could agree with a broken original.
    """
    sid = _probe_step()
    names = tuple(sorted(F.gate_programs(sid)))
    assert names, f"probe step {sid} resolves no gate programs"

    ok_before, _ = _l2(sid)
    assert ok_before, (
        f"step {sid} is ALREADY discarded as informational-only on the live "
        f"tree; the mutation arm needs a step that starts green")

    monkeypatch.setattr(FCC, "INFORMATIONAL_GATES",
                        frozenset(set(FCC.INFORMATIONAL_GATES) | set(names)))
    ok_after, why = _l2(sid)
    assert not ok_after, (
        f"every gate program of step {sid} ({list(names)}) was moved into "
        f"INFORMATIONAL_GATES and L2 still passed ({why}); the leg cannot see "
        f"the exclusion it exists to measure")


def test_d9_l3_control_arm_discriminates(tmp_path):
    """MUTATION ARM for L3, in both directions, on one live step.

    The FAIL-tier stand-in must exit non-zero and the PASS-tier one must exit
    zero. If either arm did not move, the cell sweep above is measuring the
    harness rather than the flow.
    """
    sid = _probe_step()
    rc_fail, st_fail, _ = _run_checker(sid, FAIL_GATE, tmp_path / "f")
    rc_pass, st_pass, _ = _run_checker(sid, PASS_GATE, tmp_path / "p")
    assert (st_fail, st_pass) == ("FAIL", "PASS"), (
        f"the two stand-in tiers did not resolve step {sid} to two different "
        f"statuses: FAIL-tier -> {st_fail!r}, PASS-tier -> {st_pass!r}")
    assert rc_fail != 0 and rc_pass == 0, (
        f"the checker's exit code did not follow the step's status for step "
        f"{sid}: FAIL-tier rc={rc_fail}, PASS-tier rc={rc_pass}. Every L3 cell "
        f"is decided by this difference, so a harness that returns the same rc "
        f"for both certifies the whole dimension on nothing")


def test_d9_the_informational_exclusion_is_reachable_at_all():
    """A leg that can never fire is not a guard.

    Proved against the real function with a synthetic gate name, so it stays
    true on the day no live step is anywhere near the mechanism — which is the
    state of the tree this was written on.
    """
    fake = "d9_synthetic_informational_gate"
    result = _fail_result(_probe_step(), (fake,))
    assert not FCC._step_failure_is_informational_only(result), (
        "a gate name that is NOT in INFORMATIONAL_GATES was discarded anyway")
    original = FCC.INFORMATIONAL_GATES
    try:
        FCC.INFORMATIONAL_GATES = frozenset(set(original) | {fake})
        assert FCC._step_failure_is_informational_only(result), (
            "a step whose ONLY FAIL reason cites an INFORMATIONAL_GATES member "
            "was NOT discarded; either the mechanism is dead or the reason "
            "grammar this module writes no longer matches the one the consumer "
            "parses, and L2 has been passing vacuously")
    finally:
        FCC.INFORMATIONAL_GATES = original


def test_d9_exactly_one_step_declares_no_gate():
    """The umbrella carve-out must not silently adopt a second step.

    :func:`_uses_own_mechanism` routes gate-less steps down a different L3 arm.
    A new gate-less step appearing in the yaml would inherit that arm without
    anybody deciding it should, so it reddens here instead.
    """
    gateless = _gateless_steps()
    assert gateless == ("P0",), (
        f"steps declaring no `gate:` are {list(gateless)}, expected exactly "
        f"['P0']. A gate-less step is routed through the structural-umbrella "
        f"arm of L3; whether that is right for a NEW one is a decision, not a "
        f"default")


def test_d9_structural_only_scoping_is_still_the_documented_two_member_set():
    """KNOWN GAP 1's pin: the ``--strict-structural`` scope may not widen quietly.

    L3 measures the DEFAULT invocation. The flag combination that scopes most
    steps out of the verdict is an owner decision; what this module refuses is
    that decision growing without a reader noticing. The scope is read out of
    the module's own source, because it is expressed as a comprehension over
    ``results`` rather than as a named constant.
    """
    src = FCC_PY.read_text(encoding="utf-8")
    marker = 'scoped = [r for r in results'
    assert src.count(marker) == 1, (
        f"the `scoped` comprehension appears {src.count(marker)} times in "
        f"flow_compliance_check.py; this pin resolved exactly one and can no "
        f"longer tell which one scopes the structural-only verdict")
    start = src.index(marker)
    block = src[start:src.index("]", start) + 1]
    assert 'r.id == "P0"' in block and "in_analog_track" in block, (
        f"the structural-only verdict scope is no longer 'P0 plus the analog "
        f"track'. It now reads:\n{block}\nWidening it moves more steps out of "
        f"the verdict under `--phase 2 --strict-structural`; narrowing it moves "
        f"them in. Either is a flow-policy change and must be stated.")


#: How each runner that really invokes the checker CONSUMES its verdict, as
#: MEASURED 2026-08-21. Pinned in both directions: a runner that stops consuming
#: reddens, and a runner that starts invoking the checker reddens until someone
#: says which channel it uses.
#:
#:   RETURNCODE  the exit code is bound and read. `design_one_shot_runner`
#:               does `rc, out, err = _run(...)` and maps rc onto a StepResult.
#:   REPORT      the exit code is DISCARDED and the verdict is taken from the
#:               json the checker writes.
#:
#: `phase3_one_shot_runner` WAS REPORT AND IS NOT ANY MORE, re-measured on this
#: tree. Its call now binds the result (`_fc = _sp_fc.run(...)`) and reads
#: `_fc.returncode`, and the enclosing handler is no longer a bare
#: `except Exception: pass` — it names the consequence. `_consumption_channel`
#: therefore scores it RETURNCODE, so the pin moves REPORT -> RETURNCODE. The
#: direction matters: this dimension's subject is a runner going the OTHER way,
#: and the message below still fails on that.
#:
#: WHAT RETURNCODE DOES NOT SAY HERE, stated so the pin is not read as more than
#: it is. The channel classifies whether the exit status is BOUND AND READ, not
#: whether anything BRANCHES on it in a way that stops the run. At this call
#: site the non-zero branch prints an `[INFO]` line and the headline verdict is
#: still derived from the refreshed `phase23_completion_audit.json`. What the
#: repair removed was the SILENCE — a refresh that never ran, or one that
#: returned non-zero, used to be indistinguishable from a clean one, and
#: `_derive_headline_verdict` still has no STALE branch. That remaining hole is
#: reported, not fixed here: changing a runner's verdict plumbing is a
#: flow-level change and belongs in a change that carries its own acceptance
#: evidence.
RUNNER_CONSUMPTION_AS_MEASURED = {
    "design_one_shot_runner.py": "RETURNCODE",
    "phase3_one_shot_runner.py": "RETURNCODE",
}

#: The exact string constant a runner builds the checker's argv from. Matched by
#: EQUALITY, not containment: five runners mention `flow_compliance_check` only
#: in prose, and an earlier version of this test read the raw file text and
#: counted those docstrings as call sites — it passed on three runners that never
#: invoke the checker at all. That is the PR #460 trap, reproduced inside the
#: module written to warn about it, and it is why this walks the AST.
_CHECKER_ARGV_CONSTANT = "flow_compliance_check.py"


def _runner_invocations() -> Dict[str, ast.FunctionDef]:
    """``{runner filename: the function that builds the checker's argv}``.

    Docstrings are excluded by construction: only a string constant EQUAL to
    `_CHECKER_ARGV_CONSTANT` counts, and a docstring is never that.
    """
    out: Dict[str, ast.FunctionDef] = {}
    for path in sorted(PROGRAMS_DIR.glob("*_one_shot_runner.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - defensive
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for sub in ast.walk(node):
                if (isinstance(sub, ast.Constant)
                        and sub.value == _CHECKER_ARGV_CONSTANT):
                    out[path.name] = node
                    break
            if path.name in out:
                break
    return out


#: Call names that launch a subprocess. `_run` is this tree's own thin wrapper.
_SUBPROCESS_CALLS = ("run", "call", "Popen", "check_output", "check_call", "_run")


def _consumption_channel(fn: ast.FunctionDef) -> str:
    """RETURNCODE when the exit code is bound and read; REPORT when discarded.

    SCOPED TO THE CALL, not to the function. An earlier version asked whether
    `.returncode` appeared anywhere in the enclosing function and graded
    `phase3_one_shot_runner` RETURNCODE on a `.returncode` belonging to a
    DIFFERENT subprocess in the same 200-line function. Measuring an adjacent
    call and reporting it as this one is the disease in `README.md`'s "one
    rule", and it got into this module twice before the scan was tight enough.
    """
    parent: Dict[int, ast.AST] = {}
    for node in ast.walk(fn):
        for child in ast.iter_child_nodes(node):
            parent[id(child)] = node

    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = (func.attr if isinstance(func, ast.Attribute)
                else func.id if isinstance(func, ast.Name) else None)
        if name not in _SUBPROCESS_CALLS:
            continue
        argv_names_the_checker = any(
            isinstance(sub, ast.Constant) and sub.value == _CHECKER_ARGV_CONSTANT
            for arg in node.args for sub in ast.walk(arg))
        if not argv_names_the_checker:
            continue
        # The call launches the checker. Is its RESULT kept?
        if isinstance(parent.get(id(node)), ast.Expr):
            # A bare expression statement: the CompletedProcess is dropped on
            # the floor. With `check=False` that discards the exit code too.
            return "REPORT"
        return "RETURNCODE"

    # The checker's path is built here but launched through a helper. Fall back
    # to whether this function binds an exit code at all.
    for sub in ast.walk(fn):
        if isinstance(sub, ast.Attribute) and sub.attr == "returncode":
            return "RETURNCODE"
        if isinstance(sub, ast.Assign):
            for tgt in sub.targets:
                names = ([e.id for e in tgt.elts if isinstance(e, ast.Name)]
                         if isinstance(tgt, ast.Tuple) else
                         [tgt.id] if isinstance(tgt, ast.Name) else [])
                if any(n in ("rc", "returncode", "exit_code") for n in names):
                    return "RETURNCODE"
    return "REPORT"


def test_d9_every_runner_that_invokes_the_checker_consumes_its_verdict():
    """KNOWN GAP 3's partial cover — and it is PARTIAL, stated precisely.

    What this proves: every runner that really builds the checker's argv
    consumes the result through the channel recorded for it, and no runner
    invokes it through a channel nobody has classified.

    What it does NOT prove: that the branch taken on a non-zero verdict aborts
    anything. That needs a live runner invocation per runner — a phase-scale
    job — and is open.
    """
    found = _runner_invocations()
    assert found, (
        f"no *_one_shot_runner.py builds an argv from {_CHECKER_ARGV_CONSTANT!r}; "
        f"either the runners stopped invoking the checker or this scan broke, "
        f"and in both cases the test below would pass vacuously")

    measured = {name: _consumption_channel(fn) for name, fn in found.items()}
    assert measured == RUNNER_CONSUMPTION_AS_MEASURED, (
        f"the runners' verdict-consumption changed.\n"
        f"  measured: {measured}\n"
        f"  pinned  : {RUNNER_CONSUMPTION_AS_MEASURED}\n"
        f"Newly invoking: "
        f"{sorted(set(measured) - set(RUNNER_CONSUMPTION_AS_MEASURED))}; "
        f"stopped invoking: "
        f"{sorted(set(RUNNER_CONSUMPTION_AS_MEASURED) - set(measured))}; "
        f"changed channel: "
        f"{ {k: (RUNNER_CONSUMPTION_AS_MEASURED.get(k), v) for k, v in measured.items() if RUNNER_CONSUMPTION_AS_MEASURED.get(k) not in (None, v)} }.\n"
        f"A runner moving RETURNCODE -> REPORT is this dimension's subject at "
        f"the flow's outer edge and must be a decision, not a diff nobody read.")


#: Two call sites that differ ONLY in whether the result is kept. Held here as
#: source text and parsed, so the classifier is asked the question directly.
_DISCARDING_SITE = '''
def finalize(project):
    try:
        subprocess.run(
            [sys.executable, str(PROGRAMS_DIR / "flow_compliance_check.py"),
             str(project), "--strict"],
            check=False, capture_output=True, text=True)
    except Exception:
        pass
'''
_BINDING_SITE = '''
def finalize(project):
    try:
        _fc = subprocess.run(
            [sys.executable, str(PROGRAMS_DIR / "flow_compliance_check.py"),
             str(project), "--strict"],
            check=False, capture_output=True, text=True)
        if _fc.returncode != 0:
            print("refresh rc=%d" % _fc.returncode)
    except Exception:
        pass
'''


def test_d9_the_channel_classifier_can_still_answer_REPORT():
    """NON-DEGENERACY, and it is load-bearing from the day the last real REPORT
    left the tree.

    Both entries in `RUNNER_CONSUMPTION_AS_MEASURED` now read RETURNCODE, so
    every assertion in `test_d9_every_runner_that_invokes_the_checker_consumes_
    its_verdict` is equally satisfied by a `_consumption_channel` that has lost
    the ability to say REPORT at all — the pin would go green over a classifier
    that answers RETURNCODE to everything, which is the shape of a check that
    cannot fail. This asks the classifier both questions on call sites that
    differ in exactly one thing: whether the CompletedProcess is bound.
    """
    def _fn(src):
        tree = ast.parse(src)
        return next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef))

    assert _consumption_channel(_fn(_DISCARDING_SITE)) == "REPORT", (
        "a bare-expression spawn of the checker no longer reads as REPORT; the "
        "classifier can only answer RETURNCODE and the pin above proves "
        "nothing")
    assert _consumption_channel(_fn(_BINDING_SITE)) == "RETURNCODE", (
        "binding the result and reading .returncode no longer reads as "
        "RETURNCODE, so the two answers are not distinguished by the thing "
        "they are supposed to be distinguished by")


def test_d9_the_invocation_scan_ignores_prose(tmp_path):
    """The scan must not count a docstring mention as a call site.

    This is the exact defect the first version of this test shipped with, so it
    is pinned rather than trusted: five runners name `flow_compliance_check` in
    prose only, and a text scan graded three of them as consumers.
    """
    prose_only = [p.name for p in sorted(PROGRAMS_DIR.glob("*_one_shot_runner.py"))
                  if "flow_compliance_check" in p.read_text(encoding="utf-8")
                  and p.name not in _runner_invocations()]
    assert prose_only, (
        "no runner mentions flow_compliance_check in prose without invoking it; "
        "this guard has nothing to discriminate and cannot detect a regression "
        "to text scanning")
    for name in prose_only:
        assert name not in RUNNER_CONSUMPTION_AS_MEASURED, (
            f"{name} names the checker only in prose, yet is recorded as a "
            f"consumer of its verdict")


def test_d9_every_cell_lands_in_exactly_one_state():
    """The three-state rule, for this dimension's cells."""
    states = {F.normalize_id(c.step_id): matrix_cell_state(c.step_id)
              for c in C.cells_for(DIM)}
    assert len(states) == len(C.cells_for(DIM)), "duplicate cell keys"
    bad = {k: v for k, v in states.items()
           if v not in ("ENFORCED", "WAIVED", "NA")}
    assert not bad, f"cells in no valid state: {bad}"


def test_d9_waivers_are_evidence_backed():
    """Any gap this dimension cannot close is registered WITH A REASON."""
    for c in C.cells_for(DIM):
        waiver = W.waiver_for(c.step_id, DIM)
        if waiver is None:
            continue
        problems = W.validate(waiver)
        assert not problems, f"{c.label}: waiver rejected — {problems}"
