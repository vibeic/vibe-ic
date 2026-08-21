"""An `advisory_program_exit_zero` sibling of a blocking key never executes.

`_evaluate_gate` handles the gate keys in order and RETURNS inside the
`program_exit_zero` branch. So this shape:

    gate:
      program_exit_zero: "tapeout_signoff_check …"
      advisory_program_exit_zero: "report_belongs_to_project_check …"

declares an advisory gate that cannot run. Nothing reports it: the step passes
or fails on the blocking gate alone, and `checker_execution_wiring_audit` —
which reads the FLOW, not the run — counts the checker as wired.

MEASURED, which is how it was found. Wiring `report_belongs_to_project_check`
that way and driving a real project through `flow_compliance_check`:

    ✗ [FAIL] Step 36: Tapeout checklist …
    reports/audit/report_belongs_to_project.json   <- never written

and with the same two gates under `all_of`:

    ✗ [FAIL] Step 36: Tapeout checklist …
       └─ ADVISORY (non-blocking, #306): FINDING: report_belongs_to_project_check …
    reports/audit/report_belongs_to_project.json   <- 8 findings, verdict FAIL

Same declaration, same step verdict, and the difference is whether the checker
ran at all. `all_of` evaluates each sub-gate and deliberately keeps running the
advisory ones after a failure (#306/#297) — which is the run where an advisory
has the most to say.

The invariant is over the WHOLE flow rather than the one step that had it: this
is a gate-authoring shape, and the next author writing it gets no signal from
anywhere else. Zero instances on main when this was written, so it costs no
recorded debt.
"""
from __future__ import annotations

import pathlib

import pytest
import yaml

_PLUGIN = pathlib.Path(__file__).resolve().parents[2]
_FLOW = _PLUGIN / "flow" / "phase1_phase2_phase3.yaml"

#: Keys whose branch in `_evaluate_gate` returns before the advisory branch is
#: reached, so an advisory key beside one of them is dead.
_SHADOWERS = {"program_exit_zero", "optional_program_exit_zero"}

_FLOW_DOC = yaml.safe_load(_FLOW.read_text(encoding="utf-8"))
_STEPS = _FLOW_DOC.get("steps") or []


def _mappings(gate, path):
    """Every gate mapping in the tree, with a readable path."""
    if not isinstance(gate, dict):
        return
    yield path, gate
    for key in ("all_of", "any_of"):
        subs = gate.get(key)
        if isinstance(subs, list):
            for i, sub in enumerate(subs):
                yield from _mappings(sub, f"{path}.{key}[{i}]")


def test_the_flow_has_steps():
    """Guard the guard. A parse that yields nothing would make every assertion
    below pass vacuously, which is the failure shape this file is about."""
    assert len(_STEPS) > 40, len(_STEPS)


@pytest.mark.parametrize("step", _STEPS, ids=lambda s: str(s.get("id")))
def test_no_advisory_gate_is_shadowed_by_a_blocking_sibling(step):
    dead = [
        (path, sorted(set(g)))
        for path, g in _mappings(step.get("gate") or {}, f"step {step.get('id')}")
        if "advisory_program_exit_zero" in g and (_SHADOWERS & set(g))
    ]
    assert dead == [], (
        f"{dead} — `_evaluate_gate` returns inside the blocking branch, so this "
        f"advisory gate never runs. Put the two under `all_of` as separate "
        f"sub-gates.")


def test_step_36_wires_the_report_attribution_check_reachably():
    """The instance that motivated this, asserted by SHAPE rather than by text.

    Pinned because it is the only thing making `report_belongs_to_project_check`
    see a production artefact: before it, that checker's own unit test was the
    only thing running it.
    """
    s36 = next((s for s in _STEPS if s.get("id") == 36), None)
    assert s36 is not None, "step 36 moved or was renumbered"
    found = [
        g for _p, g in _mappings(s36.get("gate") or {}, "36")
        if "report_belongs_to_project_check" in str(
            g.get("advisory_program_exit_zero", ""))
    ]
    assert found, "step 36 no longer wires report_belongs_to_project_check"
    assert not (_SHADOWERS & set(found[0])), (
        f"it is back beside a blocking key ({sorted(set(found[0]))}) and will "
        f"not run")
