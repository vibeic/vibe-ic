"""A step must not declare an output whose ONLY producer is its own gate.

WHY THIS EXISTS
===============
``flow_compliance_check.check_step`` returns ``MISSING`` *before it runs the
gate* when every declared ``required_outputs`` entry is absent from the tree.
That early return is correct on its own: a step with none of its outputs
present has not run, and running its gate to find out is wasted work.

It becomes a trap for one specific shape of step — one whose declared artefact
has no producer anywhere in the plugin EXCEPT the first command of its own
gate. For that shape the early return is self-fulfilling:

    nothing declared is present  ->  MISSING, gate skipped
    gate skipped                 ->  the producer never runs
    producer never runs          ->  nothing declared is ever present

so the step is a permanent red that no run can clear, and the only thing that
can satisfy the declaration is the auditor writing the file and then finding
it. `flow/phase1_phase2_phase3.yaml` records at the FS1 step that exactly this
declaration was attempted and WITHDRAWN on 2026-07-28, and that the withdrawal
was forced by the suppression's blast radius: removing the early return for
this step SHAPE turned an unrelated step from a correct MISSING into a PASS on
a report the audit itself had just created.

vibe-ic#983 asked for that declaration again. This module is the measurement
that answers it, kept live so the answer does not have to be re-derived from
prose the next time it is proposed.

WHAT IS ASSERTED, AND WHY NONE OF IT PASSES BY ACCIDENT
=======================================================
Three legs over one DISCOVERED population — the "trap-shape" steps, those for
which every declared entry (if any) is a path the step's own gate writes:

  L1  the trap-shape steps that declare NOTHING are exactly as pinned. This is
      a JUDGEMENT, not a law derivable from the yaml: steps 2, 8 and 36 are the
      same shape and DO declare, accepting a permanent MISSING. FS1 is pinned
      on the other side because its declaration was measured and withdrawn.
      Declaring FS1 moves it out of the set and reddens this leg by name.
  L2  a trap-shape step that DOES declare is never certified by its own gate —
      check_step on a tree carrying none of its outputs must return MISSING,
      not a pass resting on a report the audit just wrote.
  L3  the mechanism behind L1, MEASURED: check_step is run BOTH ways on two
      byte-identical throwaway fixtures, and declaring the gate's own output
      paths must flip the verdict to MISSING *and* suppress the artefacts.

L1 on its own would be a pinned set asserting the tree is what it is. L2 and
L3 execute the real ``check_step`` against real gates, so if the early return
ever stops firing for this shape — a per-entry ``condition:`` in the grammar,
or the return learning about trap-shape steps — they go red and the
prohibition gets re-examined instead of outliving its reason. L3 failing is
good news, and it says so where it fails.

Steps are DISCOVERED from the yaml, never listed. A step that acquires this
shape later is covered the day it does.

DECLARING A GATE-WRITTEN OUTPUT IS NOT THE DEFECT
=================================================
It is common and usually safe: measured on this tree, 16 declared entries
across 13 steps name a path their own gate's ``--json`` argument writes, and 7
of those name a program no runner invokes. Every one of those steps ALSO
declares an entry a run produces, so the early return never fires and the gate
always gets to run. The trap needs the WHOLE shape — no run-produced entry
left to keep the step alive. That is why the population is defined on the
absence of a non-gate-written entry rather than on gate-written paths alone,
and why it comes out at four steps rather than thirteen.

The query is derived from the yaml alone, and it returns exactly the four
steps ``flow_compliance_check`` names from its own independent measurement of
the withdrawn exemption: "justified as reaching one step and reached four
(2, 8, 36, FS1) — every step of that SHAPE, not the one it was written for."
Two different routes, same set.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Dict, List, Tuple
from _published_corpus import needs_corpus   # vibe-ic: the corpus moved repositories

import pytest

_HERE = Path(__file__).resolve().parent
_PLUGIN = _HERE.parent.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_PLUGIN / "programs"))

from matrix import flowref as F  # noqa: E402

import flow_compliance_check as FCC  # noqa: E402
import _run_isolation as _iso  # noqa: E402

#: Minimal synthesizable source, so a gate that insists on reading real RTL
#: (FS1's does — "inapplicability is EARNED from RTL that was actually read")
#: has something to open. Deliberately generic: no design, vendor or process
#: token appears anywhere in this module.
_STUB_RTL = (
    "module dut(input wire clk, input wire rst, input wire d, output reg q);\n"
    "  always @(posedge clk) if (rst) q <= 1'b0; else q <= d;\n"
    "endmodule\n"
)


def _json_outputs(step_id) -> Tuple[str, ...]:
    """Paths this step's own gate writes via a ``--json <path>`` argument."""
    out: List[str] = []
    for clause in F.gate_clauses(step_id):
        cmd = clause.command
        if not cmd:
            continue
        toks = cmd.split()
        for i, tok in enumerate(toks):
            if tok == "--json" and i + 1 < len(toks):
                out.append(toks[i + 1])
    return tuple(dict.fromkeys(out))


def _trap_shape_steps() -> Tuple[str, ...]:
    """DISCOVERED, never listed: steps for which EVERY declared entry (if any)
    is a path the step's own gate writes.

    That is the shape the early return catches: with no entry a run produces,
    nothing can ever be present when check_step looks, so the gate is skipped
    forever. A step that also declares a run-produced entry is NOT of this
    shape -- its gate still runs -- which is why declaring a gate-written path
    is common and safe elsewhere in the flow.

    CORROBORATION, not coincidence: this query is derived from the yaml alone,
    and it returns exactly the four steps ``flow_compliance_check`` names from
    its own independent measurement of the withdrawn exemption -- "justified as
    reaching one step and reached four (2, 8, 36, FS1) -- every step of that
    SHAPE". Two different routes to the same set.
    """
    found = []
    for sid in F.step_ids():
        gate_json = _json_outputs(sid)
        if not gate_json:
            continue
        declared = list(F.required_outputs(sid) or [])
        if not [e for e in declared if e not in gate_json]:
            found.append(str(sid))
    return tuple(sorted(found))


def _build_fixture(root: Path, step_id) -> List[str]:
    """Materialise the step's declared preconditions and nothing else.

    Built from the step's OWN ``condition.files_exist`` plus its
    ``required_inputs`` paths, so the fixture is derived from the flow rather
    than hand-tuned to one step.
    """
    made: List[str] = []
    wanted: List[str] = []

    cond = F.step_condition(step_id) or {}
    wanted += [str(p) for p in (cond.get("files_exist") or [])]
    node = F.step_by_id(step_id) or {}
    for dep in (node.get("required_inputs") or []):
        path = dep.get("path") if isinstance(dep, dict) else None
        if path:
            wanted += [alt.strip() for alt in str(path).split(" OR ")]

    for spec in wanted:
        # A glob names a family of files; its parent is the directory that must
        # exist and be non-empty.
        if "*" in spec:
            d = root / Path(spec).parent
            d.mkdir(parents=True, exist_ok=True)
            f = d / "dut.v"
            if not f.exists():
                f.write_text(_STUB_RTL)
                made.append(str(f.relative_to(root)))
            continue
        target = root / spec
        if target.suffix:
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.write_text(_STUB_RTL)
                made.append(str(target.relative_to(root)))
        else:
            target.mkdir(parents=True, exist_ok=True)
            f = target / "dut.v"
            if not f.exists():
                f.write_text(_STUB_RTL)
                made.append(str(f.relative_to(root)))
    return made


def _reports_present(root: Path) -> List[str]:
    r = root / "reports"
    if not r.is_dir():
        return []
    return sorted(str(p.relative_to(root)) for p in r.rglob("*") if p.is_file())


_POPULATION = _trap_shape_steps()

#: The trap-shape steps that declare NOTHING today. Pinned, because whether a
#: step of this shape should declare is a JUDGEMENT and not something the yaml
#: can decide for itself: steps 2, 8 and 36 are the same shape and DO declare,
#: accepting a permanent MISSING until a non-audit producer appears. FS1 is
#: pinned on the other side of that judgement because its declaration was
#: attempted, measured and withdrawn (vibe-ic#983 ruling 1 asked for it again).
#: A step entering or leaving this set is a named, loud event -- which is
#: exactly what happens if anyone declares FS1's two gate paths.
_DECLARE_NOTHING_AS_PINNED: Tuple[str, ...] = ("FS1",)

_DECLARING = tuple(s for s in _POPULATION if F.required_outputs(s))
_DECLARING_NOTHING = tuple(s for s in _POPULATION if not F.required_outputs(s))


def test_the_population_is_non_empty_and_disclosed(record_property):
    """A zero denominator REFUSES rather than passing.

    Every leg below is parametrized over a subset of :data:`_POPULATION`. If
    the discovery query silently returned nothing — a renamed accessor, a
    grammar change, a yaml that failed to load — pytest would report a green
    run over zero cells, which is the "green produced by having looked at
    nothing" this repo's house rule (``gate_zero_denominator_refuses_check``)
    exists to forbid.
    """
    record_property("steps_in_flow", len(F.step_ids()))
    record_property("denominator_trap_shape", len(_POPULATION))
    record_property("population_trap_shape", list(_POPULATION))
    record_property("declaring", list(_DECLARING))
    record_property("declaring_nothing", list(_DECLARING_NOTHING))
    assert _POPULATION, (
        f"discovery returned NO trap-shape steps out of {len(F.step_ids())} "
        f"flow steps. That is not a pass: either the flow changed shape (in "
        f"which case this prohibition needs re-deriving, not deleting) or the "
        f"discovery query is broken. Refusing rather than reporting a green "
        f"run over an empty population."
    )


def test_the_set_that_declares_nothing_is_exactly_as_pinned(record_property):
    """L1 — the JUDGEMENT, pinned so that changing it is loud.

    Not derivable from the yaml: steps 2/8/36 are the same shape and DO
    declare. What separates FS1 is a decision taken on a measurement, so the
    split is pinned here the way ``EXTERNALLY_ATTESTED_STEPS`` is pinned in the
    dimension-3 module — a set whose membership must not drift silently.

    Declaring FS1's two gate paths (what vibe-ic#983 ruling 1 asked for) moves
    it out of this set and reddens this test with the reason attached.
    """
    record_property("declaring_nothing", list(_DECLARING_NOTHING))
    record_property("pinned", list(_DECLARE_NOTHING_AS_PINNED))
    assert _DECLARING_NOTHING == _DECLARE_NOTHING_AS_PINNED, (
        f"the trap-shape steps that declare nothing changed: measured "
        f"{_DECLARING_NOTHING}, pinned {_DECLARE_NOTHING_AS_PINNED}.\n\n"
        f"If a step LEFT the set it now declares paths only its own gate "
        f"writes, with no run-produced entry to keep the gate alive, so "
        f"check_step returns MISSING before the gate runs and the step is a "
        f"permanent red no run can clear — see the sibling measurement "
        f"test_declaring_them_would_suppress_the_producer, and the FS1 comment "
        f"in flow/phase1_phase2_phase3.yaml recording the 2026-07-28 "
        f"withdrawal. What closes it is wiring the producer into a runner so "
        f"the artefact exists BEFORE the audit looks; then declare, and move "
        f"the pin in the same commit."
    )


@pytest.mark.parametrize("step_id", _DECLARING)
def test_a_declaring_trap_shape_step_is_never_certified_by_its_own_gate(
        step_id, tmp_path, record_property):
    """L2 — the auditor does not accept an artefact it wrote itself.

    For a trap-shape step that DOES declare, the early return is the only
    thing standing between "the gate wrote its report during the audit" and
    "the step passed". Measured live, per step, on a throwaway fixture.
    """
    step = dict(F.step_by_id(step_id))
    root = tmp_path / f"step_{step_id}"
    root.mkdir(parents=True, exist_ok=True)
    # An EMPTY seed is not a failed measurement here, it is the strictest one:
    # the property under test is "a tree carrying none of this step's outputs
    # must not pass", and a step whose preconditions are themselves unseedable
    # (step 36 declares no required_inputs paths) gives exactly that tree. L3
    # is the leg that genuinely needs a producing fixture, and it asserts one.
    seeded = _build_fixture(root, step_id)
    record_property("seeded", seeded)
    res = FCC.check_step(root, step, {})
    record_property("step", step_id)
    record_property("status", res.status)
    record_property("declared", list(F.required_outputs(step_id) or []))

    assert res.status == "MISSING", (
        f"step {step_id} declares only paths its own gate writes "
        f"{list(_json_outputs(step_id))} and check_step returned "
        f"{res.status} on a tree seeded with nothing but {seeded}. A passing "
        f"verdict here can only rest on artefacts the audit itself created "
        f"during this very run. reasons={[str(r)[:200] for r in res.reasons][:3]}"
    )


@pytest.mark.parametrize("step_id", _DECLARING_NOTHING)
@needs_corpus
def test_declaring_them_would_suppress_the_producer(step_id, tmp_path, record_property):
    """L3 — the mechanism behind L1, MEASURED, not quoted.

    Runs ``check_step`` twice on two byte-identical throwaway fixtures and
    asserts the trap is real: as shipped the gate runs and writes its reports;
    with the gate's own output paths declared the step is MISSING and the tree
    holds nothing.

    NEVER run against a published tree: ``check_step`` executes real gates,
    which WRITE into the project directory. Doing this in-place would mutate
    committed run evidence.

    That sentence used to be the whole guarantee. It is now CHECKED (#996):
    the tripwire at the end of this test asserts
    ``git status --porcelain benchmark-data/`` is empty after the real gates
    have run, so a future fixture that accidentally resolves to a published
    path fails here instead of being noticed in somebody's `git status` three
    commits later. A promise in a docstring is not a guard.
    """
    gate_json = _json_outputs(step_id)
    step = dict(F.step_by_id(step_id))

    arm_a_root = tmp_path / "as_shipped"
    arm_b_root = tmp_path / "declared"
    seeded_a = _build_fixture(arm_a_root, step_id)
    seeded_b = _build_fixture(arm_b_root, step_id)
    assert seeded_a == seeded_b and seeded_a, (
        f"step {step_id}: could not build a fixture from the step's own "
        f"condition/required_inputs (seeded {seeded_a!r}). Refusing to report "
        f"a result measured on an empty tree."
    )

    shipped = dict(step)
    shipped.pop("required_outputs", None)
    res_a = FCC.check_step(arm_a_root, shipped, {})
    produced_a = _reports_present(arm_a_root)

    declared = dict(step)
    declared["required_outputs"] = list(gate_json)
    res_b = FCC.check_step(arm_b_root, declared, {})
    produced_b = _reports_present(arm_b_root)

    record_property("step", step_id)
    record_property("arm_a_status", res_a.status)
    record_property("arm_a_reports", produced_a)
    record_property("arm_b_status", res_b.status)
    record_property("arm_b_reports", produced_b)

    assert produced_a, (
        f"step {step_id} ARM A (as shipped): the gate produced NO file under "
        f"reports/ on a fixture seeded with {seeded_a}, so this fixture cannot "
        f"demonstrate anything about the declaration. status={res_a.status}, "
        f"reasons={[str(r)[:200] for r in res_a.reasons][:3]}"
    )

    assert res_b.status == "MISSING" and not produced_b, (
        f"step {step_id}: declaring the paths its own gate writes NO LONGER "
        f"suppresses the producer — ARM A {res_a.status} produced "
        f"{produced_a}; ARM B (declaring {list(gate_json)}) returned "
        f"{res_b.status} and produced {produced_b}.\n\n"
        f"THIS IS GOOD NEWS AND THIS TEST IS THE WRONG SHAPE NOW. The early "
        f"'every declared entry absent -> MISSING' return is what made the "
        f"declaration a trap; if it no longer fires for this step, the "
        f"prohibition pinned above has lost its reason and vibe-ic#983's "
        f"ruling 1 should be re-evaluated on this measurement rather than on "
        f"the 2026-07-28 one. Do not silence this by deleting the assert: "
        f"change the flow and the pin together."
    )

    # THE TRIPWIRE (#996). Both arms above executed REAL gates through
    # `check_step`, and real gates write. They were pointed at `tmp_path`
    # fixtures, which is why this passes — but "which is why this passes" was
    # previously a claim in the docstring rather than a measurement.
    record_property("corpus_after",
                    _iso.assert_corpus_pristine(
                        what=f"L3 for step {step_id}").describe())
