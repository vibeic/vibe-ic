#!/usr/bin/env python3
"""Step 37.5ic must actually RUN, and it must never guess which slot was bought.

TWO DEFECTS, ONE STEP, AND THE SECOND IS WHY THE FIRST COULD NOT SIMPLY BE
WIRED IN
=========================================================================
`tapeout_precheck` merges two independent authorities over one GDS: our
`general_precheck` ladder, and — where the PDK ships one — the shuttle
operator's own tool. Both existed. Neither ran: the gate was in no runner's
declared sign-off table, so a phase-3 run reached its verdict without either
authority having looked at the layout at all.

Wiring it in was blocked on a defect in its own input. `--slot` DEFAULTED to
``"1x1"`` and that default was handed verbatim to the operator's tool. The
operator's arm is valuable precisely because WE DID NOT WRITE IT and cannot
edit it to agree — so feeding it a slot the design never purchased gets a
CONCLUSIVE answer about the wrong question, from the one arm nobody can
correct. A guessed input is worse there than anywhere else in the flow.

So the slot is resolved from the OPERATOR's fetched template — the only place
the constant legitimately lives — and is NOT_DETERMINED when the template does
not settle it. Never "the first one": several slots on offer means the design
has not chosen, and choosing for it closes an open question with an answer the
design never gave.

WHAT WOULD DEFEAT EACH TEST (write it down, or a green test proves nothing):
  * the wiring test  — deleting the tuple entry, or renaming the program;
  * the no-guess tests — restoring any fallback slot, including "pick the only
    plausible one" or "pick the first";
  * the still-refuses test — a resolver that returns a slot for a declaration
    naming one the operator does not offer;
  * the not-applicable test — a slot check that fires BEFORE applicability and
    turns "this PDK has no shuttle" (the one legitimate absence) into a defect.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import tapeout_precheck as tp                                  # noqa: E402
import _tapeout_declaration as _decl                           # noqa: E402


# --------------------------------------------------------------------------- #
# 1. The step is wired into the runner's declared sign-off table
# --------------------------------------------------------------------------- #
def _declared_gates():
    """The runner's tuple, read WITHOUT importing the runner.

    `phase3_one_shot_runner` is ~48 k lines and importing it drags the whole
    backend in. The tuple is a literal, so parse it out of the source: this
    test is about what the table DECLARES, and reading the declaration is the
    honest way to ask that.
    """
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text()
    start = src.index("_DECLARED_SIGNOFF_GATES = (")
    end = src.index("\n)\n", start)
    return src[start:end]


def test_step_37_5ic_is_a_declared_signoff_gate():
    """It must be IN the table — the whole defect was that it was not."""
    body = _declared_gates()
    assert '"tapeout_precheck"' in body, (
        "step 37.5ic's gate is not in `_DECLARED_SIGNOFF_GATES`, so no phase-3 "
        "run invokes it and every run reaches a verdict without either "
        "tape-out authority having read the GDS.")
    assert '"tapeout_precheck.py"' in body, (
        "the table names the step but not the program that answers it.")
    assert '"reports/phase3/tapeout_precheck.json"' in body, (
        "the table must name the artefact the gate writes, or the runner "
        "cannot read back the reason for a refusal.")


def test_the_declared_entry_passes_no_slot_or_pdk_argv():
    """Both must self-resolve; this table cannot carry per-run values.

    `step_declared_signoff_gates(project)` takes only the project, so anything
    this entry needed per-run would have to be frozen into a default — which is
    the defect the rest of this file exists to prevent.
    """
    body = _declared_gates()
    entry = body[body.index('"tapeout_precheck"'):]
    entry = entry[:entry.index("),") + 2]
    assert "--slot" not in entry and "--pdk" not in entry, (
        "a frozen --slot or --pdk in the declared table is a guess with a "
        f"fixed value for every design in the corpus: {entry!r}")


# --------------------------------------------------------------------------- #
# 2. The slot is read from the operator's template, or not at all
# --------------------------------------------------------------------------- #
def _slot(project: Path, name: str, content=None) -> None:
    d = project / "input/submission_template/slots"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.yaml").write_text(
        json.dumps(content if content is not None else {"slot": name}))


def _declare(project: Path, **operator_template) -> None:
    """The DESIGN's slot, in the flow's own home for it.

    `input/step_0_5ic_answers.json` -> `operator_template.slot` is where
    `phase1_one_shot_runner._run_step_0_5ic` reads it before passing `--slot`
    to the ingest, so it is where every reader must look. The tape-out
    DECLARATION is not that home — `slot` is not one of its 18 questions, and
    writing it there makes the declaration carry an unknown key.
    """
    import _submission_template as _st
    p = project / _st.DESIGN_ANSWERS_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"operator_template": operator_template}))


def test_no_template_resolves_no_slot(tmp_path):
    """The constant lives in the operator's template. No template, no slot."""
    assert tp.resolve_slot(tmp_path) == (None, None)


def test_one_slot_on_offer_is_still_not_a_declaration(tmp_path):
    """What the operator SELLS is not what this design BOUGHT.

    `submission_template_ingest` states the rule for the whole step: the slot
    is "the slot this design DECLARES it targets. Never guessed and never
    defaulted." A sole slot read as the design's choice would silently move any
    design that never chose, the moment the operator adds a second one.
    """
    _slot(tmp_path, "0p5x0p5")
    assert tp.resolve_slot(tmp_path) == (None, None)


def test_a_declaration_naming_the_only_slot_resolves_it(tmp_path):
    """The positive control, so "never guessed" cannot become "never works"."""
    _slot(tmp_path, "0p5x0p5")
    _declare(tmp_path, slot="0p5x0p5")
    got, source = tp.resolve_slot(tmp_path)
    assert got == "0p5x0p5"
    assert source and "0p5x0p5" in source, (
        "the resolution must name WHERE it read the slot from; a bare value "
        "cannot be audited against the template that supposedly carries it.")


def test_several_slots_and_no_declaration_is_not_determined(tmp_path):
    """THE CORE OF IT: several on offer means the design has not chosen.

    A resolver that picks the first — or the smallest, or the one that fits —
    answers a question the design never answered, and the operator's tool then
    reports CONCLUSIVELY about a slot nobody bought.
    """
    _slot(tmp_path, "0p5x0p5")
    _slot(tmp_path, "1x1")
    assert tp.resolve_slot(tmp_path) == (None, None)


def test_a_declaration_selects_among_the_slots_actually_offered(tmp_path):
    _slot(tmp_path, "0p5x0p5")
    _slot(tmp_path, "1x1")
    _declare(tmp_path, slot="0p5x0p5")
    got, source = tp.resolve_slot(tmp_path)
    assert got == "0p5x0p5"
    assert "declaration" in (source or "")


def test_a_declaration_naming_a_slot_nobody_sells_selects_nothing(tmp_path):
    """The declaration proposes; the template disposes.

    Otherwise a typo in our own file would put a fabricated slot name in front
    of the operator's tool.
    """
    _slot(tmp_path, "0p5x0p5")
    _slot(tmp_path, "1x1")
    _declare(tmp_path, slot="9x9")
    assert tp.resolve_slot(tmp_path) == (None, None)


def test_an_explicit_slot_always_wins(tmp_path):
    """The caller stating it is a declaration too — the most direct one."""
    _slot(tmp_path, "0p5x0p5")
    got, source = tp.resolve_slot(tmp_path, "1x0p5")
    assert (got, source) == ("1x0p5", "--slot")


def test_a_declaration_of_NOT_DETERMINED_is_not_an_answer(tmp_path):
    """`NOT_DETERMINED` is the word for "nobody said", not a slot name."""
    _slot(tmp_path, "0p5x0p5")
    _slot(tmp_path, "1x1")
    _declare(tmp_path, slot=_decl.NOT_DETERMINED)
    assert tp.resolve_slot(tmp_path) == (None, None)


# --------------------------------------------------------------------------- #
# 3. The no-guess rule must not manufacture a defect where none exists
# --------------------------------------------------------------------------- #
def test_the_source_carries_no_fallback_slot_literal():
    """A grep-level pin on the defect itself.

    The value `"1x1"` as a DEFAULT is the whole bug. It may still appear as
    test data or in prose; what may not come back is a default= or an `or`
    fallback handing it to the operator's tool.
    """
    src = (_PROGRAMS / "tapeout_precheck.py").read_text()
    assert 'default="1x1"' not in src, (
        "`--slot` defaults to a slot again. That default is passed verbatim to "
        "the operator's own tool, which answers conclusively about it.")
    assert 'slot: str = "1x1"' not in src, (
        "`evaluate(slot=...)` defaults to a slot again — same defect, reached "
        "by every in-process caller instead of the CLI.")


def test_the_slot_check_runs_after_applicability_not_before():
    """`NOT_APPLICABLE` is the ONE legitimate absence and must survive.

    A PDK with no live shuttle has no operator to ask and therefore no slot to
    buy. If the slot check fired first it would turn that design — every
    non-GF180 design in the corpus — into NOT_DETERMINED, i.e. report "we could
    not look" where the truthful answer is "there was nothing to look at".
    """
    src = (_PROGRAMS / "tapeout_precheck.py").read_text()
    applic = src.index("state, why, shuttle = operator_arm_applicability(")
    slotres = src.index("resolved_slot, slot_source = resolve_slot(")
    assert applic < slotres, (
        "the slot is resolved BEFORE applicability, so a PDK with no shuttle "
        "would be reported NOT_DETERMINED instead of NOT_APPLICABLE.")
    guard = src[slotres:slotres + 400]
    assert "state == RAN" in guard, (
        "the unresolved-slot downgrade must be conditional on the operator's "
        "arm actually being due to run.")


@pytest.mark.parametrize("declared", ["", None, "   "])
def test_an_empty_declaration_value_is_not_a_slot(tmp_path, declared):
    _slot(tmp_path, "0p5x0p5")
    _slot(tmp_path, "1x1")
    _declare(tmp_path, slot=declared)
    assert tp.resolve_slot(tmp_path) == (None, None)


# --------------------------------------------------------------------------- #
# 4. The step must decide whether it APPLIES before it decides anything else
# --------------------------------------------------------------------------- #
import _submission_template as _st                              # noqa: E402


def _route_file(project: Path, rel: str) -> None:
    p = project / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# a router artefact step 0.5ic writes\n")


def test_the_ip_terminal_is_not_applicable_and_passes(tmp_path):
    """An IP delivery has no die, so there is no submission to precheck.

    Wired into every phase-3 run, a gate that reported NOT_DETERMINED here
    would put a permanent red on the whole IP population for a question never
    asked of it — a detector that fires on everything.
    """
    _route_file(tmp_path, _st.NO_TEMPLATE_REL)
    rep = tp.evaluate(project=tmp_path)
    assert rep.route == tp.ROUTE_IP
    assert rep.step_applies is False
    assert rep.verdict == tp.PASS
    assert "does not apply" in rep.reason


def test_an_undeclared_route_is_not_the_ip_path(tmp_path):
    """THE ASYMMETRY THAT MATTERS. Silence is not the IP terminal.

    Step 0.5ic failing is the one circumstance in which a CHIP most needs this
    step. Reading "no router artefact" as "must be an IP" would let that
    failure delete the check that would have reported it.
    """
    rep = tp.evaluate(project=tmp_path)
    assert rep.route == tp.ROUTE_UNDECLARED
    assert rep.step_applies is True
    assert rep.verdict != tp.PASS


def test_a_chip_route_applies_and_is_not_passed_for_free(tmp_path):
    _route_file(tmp_path, tp._decl.SELF_TAPEOUT_REL)
    rep = tp.evaluate(project=tmp_path)
    assert rep.route == tp.ROUTE_CHIP
    assert rep.step_applies is True
    assert rep.verdict != tp.PASS, (
        "a chip with no layout examined must not reach PASS")


def test_a_slot_file_is_a_chip_route_too(tmp_path):
    _slot(tmp_path, "0p5x0p5")
    rep = tp.evaluate(project=tmp_path)
    assert rep.route == tp.ROUTE_CHIP
    assert rep.step_applies is True


def test_the_report_carries_the_evidence_that_decided_the_route(tmp_path):
    """A route with no named evidence cannot be audited."""
    _route_file(tmp_path, _st.NO_TEMPLATE_REL)
    rep = tp.evaluate(project=tmp_path)
    assert _st.NO_TEMPLATE_REL in rep.route_evidence


def test_step_applies_is_reported_separately_from_the_verdict(tmp_path):
    """`PASS` and `step_applies: false` must both reach the artefact.

    A consumer that saw only the verdict would read the entire IP population as
    tape-out ready.
    """
    _route_file(tmp_path, _st.NO_TEMPLATE_REL)
    doc = tp.evaluate(project=tmp_path).as_dict()
    assert doc["verdict"] == tp.PASS
    assert doc["step_applies"] is False
    assert doc["route"] == tp.ROUTE_IP
