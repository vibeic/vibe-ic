"""Regression tests — the declaration producer must know the spec's contract.

DEFECT (measured on v1.9.71, on a `processor_cpu` IC whose own spec declares an
8-field `plugin_output/declaration.json` contract):

  * `step_arith_declaration_emit` was wired to `arith_declaration_emit.py`
    ALONE.  That emitter resolves an ARITHMETIC-PRIMITIVE field set —
    `bit_order`, `size_param`, `multiplier_algorithm`, `integer_encoding`.
  * The design's spec declared a completely different field set.  The wired
    emitter fail-closed naming its four arithmetic fields — none of which that
    spec mentions — and wrote nothing.
  * `spec_required_artifact_check` then FAILed the run for the missing file,
    Step P0 FAILed, and the flow HALTED IN PHASE 2.  Phase 3 never ran, so the
    run certified nothing about the target process at all.
  * `spec_declaration_emit.py` — the CONTRACT-DRIVEN emitter that reads the
    field list out of the project's OWN Phase-1 documents — was wired in
    `--contract` mode only (the authoring hint).  Its emit mode had no caller.

Net: the general emitter existed, was tested, and could not write; the
arithmetic-only emitter was the sole producer and could not know the contract.

Each test states the pre-fix behaviour it would have shown.  A test that cannot
fail against the old code is not evidence, so the negative control is explicit.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, PROGRAMS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# A spec that declares a machine-readable declaration contract.  The field
# names are INVENTED for this test on purpose: they belong to no design in this
# repo, so a fix that hard-codes any real design's field list fails here.
_SPEC_WITH_CONTRACT = """\
# L7 — Verification Plan

## 7.0 Plugin Declaration Requirements

The implementer MUST emit `plugin_output/declaration.json` carrying:

| Field | Required | Example |
|---|---|---|
| `widget_port_name` | YES | `"w_in"` |
| `sprocket_count` | YES | `7` |
"""

# A spec that declares NO declaration contract at all — the arithmetic-primitive
# case, where the previous behaviour must survive byte for byte.
_SPEC_WITHOUT_CONTRACT = """\
# L7 — Verification Plan

## 7.1 Functional Verification

Drive the block with the reference vectors and compare against the golden.
"""


def _project(tmp_path: Path, spec_text: str) -> Path:
    docs = tmp_path / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "L7_verification_plan.md").write_text(spec_text, encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# 1. NEGATIVE CONTROL — the reason must name THIS spec's fields.
# ---------------------------------------------------------------------------
def test_fail_closed_reason_names_the_specs_own_fields(tmp_path):
    """NEGATIVE CONTROL: pre-fix the step ran only the arithmetic emitter, so
    the detail named `bit_order` / `size_param` / `multiplier_algorithm` /
    `integer_encoding` and never `widget_port_name`.  An author reading it was
    told to supply fields their spec does not have, which is why the halt was
    unactionable.  This assertion fails against the pre-fix code."""
    d = _load("design_one_shot_runner")
    project = _project(tmp_path, _SPEC_WITH_CONTRACT)

    res = d.step_arith_declaration_emit(project)
    detail = res.detail or ""

    assert "widget_port_name" in detail, (
        "the fail-closed reason must name the field THIS spec declares; "
        f"got: {detail!r}")
    for arithmetic_only in ("bit_order", "size_param",
                            "multiplier_algorithm", "integer_encoding"):
        assert arithmetic_only not in detail, (
            f"{arithmetic_only!r} belongs to the arithmetic-primitive contract "
            f"and this spec never declares it; got: {detail!r}")


# ---------------------------------------------------------------------------
# 2. PRESERVATION — no contract declared, previous behaviour survives.
# ---------------------------------------------------------------------------
def test_no_declared_contract_still_routes_to_the_arithmetic_emitter(tmp_path):
    """A spec that declares no contract is the arithmetic-primitive case. The
    contract-driven emitter exits NO_CONTRACT there, and the step must fall
    through to the emitter it always used — otherwise this fix would silently
    retire a working producer."""
    d = _load("design_one_shot_runner")
    project = _project(tmp_path, _SPEC_WITHOUT_CONTRACT)

    res = d.step_arith_declaration_emit(project)
    detail = res.detail or ""

    assert "spec_declaration_emit" not in detail, (
        "with no spec-declared contract the contract-driven emitter must not "
        f"be the one reporting; got: {detail!r}")
    assert "widget_port_name" not in detail


# ---------------------------------------------------------------------------
# 3. NON-BLOCKING BY CONSTRUCTION — this step may never FAIL a run.
# ---------------------------------------------------------------------------
def test_step_never_returns_fail(tmp_path):
    """Whether an absent declaration MATTERS is `spec_required_artifact_check`'s
    decision, not this producer's.  If this step could FAIL, wiring a second
    emitter into it could newly fail an IC that passes today."""
    d = _load("design_one_shot_runner")
    for spec in (_SPEC_WITH_CONTRACT, _SPEC_WITHOUT_CONTRACT):
        project = _project(tmp_path / f"p{hash(spec) & 0xffff}", spec)
        res = d.step_arith_declaration_emit(project)
        assert res.status in ("PASS", "SKIP"), (
            f"the declaration producer must never block; got {res.status}")


# ---------------------------------------------------------------------------
# 4. The contract-driven emitter must actually be reachable from the step.
# ---------------------------------------------------------------------------
def test_step_invokes_the_contract_driven_emitter(tmp_path):
    """The defect was one of WIRING, not of capability: `spec_declaration_emit`
    was complete and tested but had no caller in emit mode.  A future edit that
    drops the call would restore the defect with every test above still green
    only if they were weaker than this one — so name the wiring explicitly."""
    import inspect

    d = _load("design_one_shot_runner")
    # The STEP's own body — not the whole module.  `spec_declaration_emit.py`
    # already appeared elsewhere in this file pre-fix, as the text of the
    # RTL-authoring hint, so a module-wide substring test would pass against
    # the defect and prove nothing.
    body = inspect.getsource(d.step_arith_declaration_emit)
    assert "spec_declaration_emit.py" in body, (
        "the declaration step must INVOKE the contract-driven emitter, not "
        "merely name it in a hint elsewhere in the module")
    # and the previous producer must still be wired for the no-contract case
    assert "arith_declaration_emit.py" in body
