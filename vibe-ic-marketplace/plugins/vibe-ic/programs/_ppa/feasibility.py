#!/usr/bin/env python3
"""The hard gate: a beautiful number on one axis does not promote a violation.

WHY THIS MODULE IS SEPARATE FROM THE SEARCH PENALTY (spec 8.2)
==============================================================
An optimiser needs a GRADED signal. If every infeasible candidate scored
"infinitely bad", the search would have no gradient to walk back along and
would wander. So a graded penalty is not a mistake -- it is how the navigation
works.

A published claim needs the opposite. "This candidate may be promoted" is a
statement about silicon, and it is either true or it is not; there is no
partial credit for a design-rule violation. A candidate whose worst-negative
slack improved by 40 ps and whose LVS is dirty is not 90% promotable. It is
refused.

The failure this module exists to prevent is the ONE code path that serves both
questions: a penalty large enough to lose a search, but finite, and therefore
capable of being outweighed by a big enough win on another axis. That is how a
violating candidate wins.

The separation here is STRUCTURAL, not a convention someone has to remember:

  * `promotion_verdict()` takes a `FeasibilityPolicy`. `search_penalty()` takes
    a `PenaltyWeights`. The two dataclasses share no field name, so there is no
    threshold both paths can read -- `separation_report()` MEASURES that with
    `dataclasses.fields`, it is not asserted in prose.
  * The dependency runs ONE WAY. `search_penalty()` consumes an already
    adjudicated `FeasibilityResult`; nothing in the gate's call closure
    references the penalty. `separation_report()` measures that too, over the
    module's own AST, so an author who wires the penalty into the gate makes
    this module say so out loud.

WHAT "COULD NOT CHECK" MEANS HERE, AND WHY IT IS NOT A PASS
===========================================================
"DRC reported zero violations" and "DRC never ran" both produce the number 0 if
you only look at a count. This module never reads a bare count. It reads
canonical metric records (`vibeic.ppa.metric.v1`), and a record only supports a
proof when its `status` is `MEASURED` and it carries provenance -- an artefact
path and the sha256 of the artefact that was parsed. A candidate whose DRC
evidence is a `NOT_MEASURED` record, or a `MEASURED` record with no artefact
behind it, is UNDETERMINED. It is never FEASIBLE.

For the same reason a waiver cannot rescue an axis that was never measured. A
waiver is a statement that a KNOWN violation is acceptable to a named owner.
Applying one to an axis nobody looked at converts an unknown into a pass, which
is precisely the move this whole contract exists to make impossible.

VERDICT PRECEDENCE, AND WHY IT DIFFERS BETWEEN A CANDIDATE AND A SET
====================================================================
Per CANDIDATE, a confirmed violation wins over an unmeasured axis: one measured
violation is already sufficient and sound grounds to refuse promotion, and
refusing is the safe direction. So VIOLATED beats UNDETERMINED and the candidate
is INFEASIBLE.

Per SET -- which is what the CLI's exit code reports -- it is the other way
round. rc=0 asserts "every candidate was adjudicated and all are feasible", and
one unadjudicated candidate makes that assertion false; rc=1 asserts a complete
finding about the design, and a run that could not see all of its evidence must
not make one. So at set level UNDETERMINED (rc=2) takes precedence over
INFEASIBLE (rc=1). Nothing is lost: both block, every per-candidate verdict is
in the JSON, and every finding is printed regardless of which code is returned.

AND THE FOURTH AXIS STATUS, WHICH IS NEITHER A PASS NOR A HOLE
==============================================================
Most axes always apply: every design that is routed has a DRC answer owed of
it. One does not. DESIGN-FOR-ECO readiness -- does this design carry the spare
cells that make a post-tape-out bug fixable by a metal-only ECO -- is a
requirement the DESIGN declares, and a design that declares none is not
thereby failing. So `AXIS_NOT_APPLICABLE` exists, it is produced only by an
axis that consults a declaration of its own applicability, and it contributes
nothing to the candidate verdict in either direction.

What it must never do is hide. The row is on EVERY verdict, it names which of
the four declaration states was read -- NOT_DECLARED, NOT_REQUIRED, UNREADABLE,
REQUIRED -- and it lists, by name, every obligation the run did not prove.
"nobody declared a requirement" and "the design declared it needs none" are
different facts about a design and they do not share a code.

chip-AGNOSTIC: nothing here names an IC, a vendor, an SKU or a process. Every
threshold in the default axis set is either zero violations, a non-negative
slack, or a limit the CONTRACT declares -- never a number invented here. The
ECO axis holds no spare count, no density and no cell kind for the same reason.
"""
from __future__ import annotations

import ast
import dataclasses
import inspect
import pathlib
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

__all__ = [
    "RC_PASS", "RC_FAIL", "RC_UNDETERMINED", "RC_BAD_INVOCATION",
    "METRIC_SCHEMA", "FEASIBILITY_SCHEMA",
    "STATUS_MEASURED", "COMPARABLE_STATUSES", "METRIC_STATUSES",
    "KIND_SLACK_NONNEG", "KIND_COUNT_ZERO", "KIND_VERDICT_IN", "KIND_LIMIT_MAX",
    "KIND_LIMIT_MIN",
    "AXIS_SATISFIED", "AXIS_VIOLATED", "AXIS_WAIVED", "AXIS_UNDETERMINED",
    "AXIS_NOT_APPLICABLE",
    "ECO_AXIS", "ECO_M_COUNT", "ECO_M_SURVIVING", "ECO_M_POSITIONS",
    "ECO_M_TIE_OFF", "ECO_M_PADS", "eco_metric_for_kind",
    "ECO_REQUIRED", "ECO_NOT_REQUIRED", "ECO_NOT_DECLARED", "ECO_UNREADABLE",
    "eco_requirement_state", "eco_proofs_and_limits", "eco_applicability",
    "ECO_NOT_DECLARED_ON_CHIP_PATH", "ECO_NOT_APPLICABLE_ON_IP_PATH",
    "ECO_PATH_UNDETERMINED",
    "FEASIBLE", "INFEASIBLE", "UNDETERMINED",
    "Proof", "Axis", "DEFAULT_AXES",
    "FeasibilityPolicy", "PenaltyWeights",
    "AxisResult", "FeasibilityResult",
    "policy_from_document", "promotion_verdict", "adjudicate_set",
    "views_for", "COV_MEASURED", "COV_NOT_MEASURED", "COV_NO_RECORD",
    "search_penalty", "separation_report", "shared_field_names",
    "set_exit_code",
]

# --- exit codes (docs/PPA_INTERFACES.md 1) ---------------------------------
RC_PASS = 0
RC_FAIL = 1
RC_UNDETERMINED = 2
RC_BAD_INVOCATION = 3

METRIC_SCHEMA = "vibeic.ppa.metric.v1"
FEASIBILITY_SCHEMA = "vibeic.ppa.feasibility.v1"

# --- metric statuses (docs/PPA_INTERFACES.md 2) ----------------------------
STATUS_MEASURED = "MEASURED"
#: Only these may enter a numeric comparison. The table in the interface freeze
#: has exactly one row with "yes" in it, and this is that row.
COMPARABLE_STATUSES = frozenset({STATUS_MEASURED})
METRIC_STATUSES = frozenset({
    "MEASURED", "NOT_MEASURED", "NOT_APPLICABLE",
    "INVALID", "ESTIMATED", "DERIVED",
})

# --- proof kinds ------------------------------------------------------------
#: value >= 0. Sign is invariant under any positive unit scaling, so this kind
#: deliberately does NOT require a unit match -- 0 ns and 0 ps are the same
#: boundary and demanding agreement would refuse a correct artefact.
KIND_SLACK_NONNEG = "slack_nonneg"
#: value == 0. A negative count is not "very clean", it is a broken parse.
KIND_COUNT_ZERO = "count_zero"
#: value is one of an accepted set of literals (e.g. an LVS verdict).
KIND_VERDICT_IN = "verdict_in"
#: value <= a limit the CONTRACT declares. There is no built-in number: a limit
#: this module invented would be a chip-specific constant in agnostic source.
KIND_LIMIT_MAX = "limit_max"
#: value >= a floor the CONTRACT declares. The mirror of KIND_LIMIT_MAX and it
#: exists for the same reason: a violation can be a number that is too SMALL.
#: A design-for-ECO spare population is the case that forced it -- "at least
#: this many spare cells survive" is a requirement, and a gate that could only
#: express ceilings could not state it at all. There is no built-in floor here
#: either; a floor this module invented would be a design decision in agnostic
#: source.
KIND_LIMIT_MIN = "limit_min"

# --- axis and candidate verdicts -------------------------------------------
AXIS_SATISFIED = "SATISFIED"
AXIS_VIOLATED = "VIOLATED"
AXIS_WAIVED = "WAIVED"
AXIS_UNDETERMINED = "UNDETERMINED"
#: The axis asks a question this design has not been asked to answer. It is not
#: SATISFIED -- nothing was proved -- and it is not UNDETERMINED -- nothing was
#: owed. It exists so an axis whose APPLICABILITY is itself declared can say
#: "no requirement was declared" without that reading as either a pass or a
#: hole. Only an axis that consults a declaration of applicability produces it.
AXIS_NOT_APPLICABLE = "NOT_APPLICABLE"

FEASIBLE = "FEASIBLE"
INFEASIBLE = "INFEASIBLE"
UNDETERMINED = "UNDETERMINED"

# --- verdict codes ----------------------------------------------------------
# Every verdict carries one of these. A human sentence is not a code: two
# authors write it two ways and no downstream selector can match on it.
C_METRIC_ABSENT = "FEAS_METRIC_ABSENT"
C_BAD_RECORD = "FEAS_BAD_RECORD"
C_BAD_STATUS = "FEAS_BAD_STATUS"
C_NOT_MEASURED = "FEAS_NOT_MEASURED"
C_NOT_MEASURED_CARRIES_VALUE = "FEAS_NOT_MEASURED_CARRIES_VALUE"
C_NO_PROVENANCE = "FEAS_NO_PROVENANCE"
C_INCOMPLETE_VIEW_SET = "FEAS_INCOMPLETE_VIEW_SET"
C_VIEWS_NOT_DECLARED = "FEAS_VIEWS_NOT_DECLARED"
C_LIMIT_NOT_DECLARED = "FEAS_LIMIT_NOT_DECLARED"
C_UNIT_MISMATCH = "FEAS_UNIT_MISMATCH"
C_NEGATIVE_COUNT = "FEAS_NEGATIVE_COUNT"
C_NON_NUMERIC = "FEAS_NON_NUMERIC_VALUE"
C_VIOLATION = "FEAS_VIOLATION"
C_WAIVER_NO_OWNER = "FEAS_WAIVER_NO_OWNER"
C_WAIVER_NO_JUSTIFICATION = "FEAS_WAIVER_NO_JUSTIFICATION"
C_WAIVER_NO_AXIS = "FEAS_WAIVER_NO_AXIS"
C_WAIVER_UNKNOWN_AXIS = "FEAS_WAIVER_UNKNOWN_AXIS"
C_WAIVER_ON_UNMEASURED = "FEAS_WAIVER_ON_UNMEASURED"
C_WAIVERS_DISABLED = "FEAS_WAIVERS_DISABLED"
C_OK = "FEAS_OK"
# --- design-for-ECO applicability ------------------------------------------
#: No `eco_readiness` block at all: nothing declared a requirement, so this run
#: makes no ECO-readiness finding. NOT the same as the next one.
C_ECO_NOT_DECLARED = "FEAS_ECO_NOT_DECLARED"
#: A declaration exists and says this design requires no spare population.
C_ECO_NOT_REQUIRED = "FEAS_ECO_NOT_REQUIRED"
#: A declaration exists and could not be read as one. Somebody tried to state a
#: requirement; refusing is the only safe reading of a requirement nobody can
#: parse, so this is UNDETERMINED and never NOT_APPLICABLE.
C_ECO_DECLARATION_UNREADABLE = "FEAS_ECO_DECLARATION_UNREADABLE"
#: `required: true` with no floor, no kind and no other stated obligation. It
#: asserts the design needs ECO readiness and then says nothing that could be
#: checked, which is a contradiction and not a pass.
C_ECO_REQUIREMENT_EMPTY = "FEAS_ECO_REQUIREMENT_EMPTY"
#: No declaration, and the flow routed this design onto the CHIP path. A
#: tape-out-bound design that declared no spare/ECO requirement is a
#: [CANNOT CHECK], never a silent pass -- the whole hole the delivery path
#: closes.
C_ECO_NOT_DECLARED_ON_CHIP_PATH = "FEAS_ECO_NOT_DECLARED_ON_CHIP_PATH"
#: No declaration, and the flow routed this design to the hardmacro/IP
#: terminal. An IP delivery is not tape-out-bound, so no spare population is
#: owed and this is a finding, not a hole.
C_ECO_NOT_APPLICABLE_ON_IP_PATH = "FEAS_ECO_NOT_APPLICABLE_ON_IP_PATH"
#: No declaration, and the route could not be established -- no router artefact,
#: both of them at once, or a flow that could not be read. A design that has
#: not been shown to be an IP delivery must not be treated as one.
C_ECO_PATH_UNDETERMINED = "FEAS_ECO_PATH_UNDETERMINED"
#: A declaration that opts out, on a design the flow routed onto the CHIP path.
#: Still NOT_APPLICABLE -- an opt-out is a decision somebody made and the axis
#: does not overrule it -- but it is the one shape a reader must be able to
#: find, so it does not share a code with an opt-out on the IP path.
C_ECO_OPTED_OUT_ON_CHIP_PATH = "FEAS_ECO_OPTED_OUT_ON_CHIP_PATH"


# ---------------------------------------------------------------------------
# the axis table -- DATA, so that adding an axis is not editing an algorithm
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Proof:
    """One way of establishing one axis from one canonical metric."""
    metric: str
    kind: str
    accept: Tuple[str, ...] = ()
    limit_key: str = ""


@dataclass(frozen=True)
class Axis:
    """A feasibility axis and the alternative ways of proving it.

    `groups` is an OR of ANDs: the axis is satisfied when every proof in at
    least one group is satisfied. That shape is here because real flows report
    the same fact two ways -- one rolled-up design-rule-violation count, or the
    individual max-transition / max-capacitance / max-fanout counts -- and a
    checker that insisted on one spelling would refuse a correct run.

    A measured failure in ANY group makes the axis VIOLATED even if another
    group is satisfied: two artefacts that disagree is not permission to
    believe the flattering one.
    """
    name: str
    groups: Tuple[Tuple[Proof, ...], ...]


# ---------------------------------------------------------------------------
# DESIGN-FOR-ECO READINESS -- an axis whose APPLICABILITY is itself declared
# ---------------------------------------------------------------------------
# WHY THIS AXIS IS NOT A COLUMN IN A TABLE OF NUMBERS.
#
# A spare/ECO cell population is what makes a bug found after tape-out fixable
# by a METAL-ONLY ECO. Remove it and the only remaining repair is a base-layer
# respin -- a new mask set. So for a tape-out-bound design a spare population is
# not a quantity to be traded against area on a Pareto front; it is a property
# the design is required to HAVE, and a candidate that does not have it is not
# a cheaper candidate, it is a different and unshippable one.
#
# MEASURED, and this is why the axis exists at all: in a published cross-layer
# search over one design, the winning place-and-route arm deleted all ten of the
# design's spare cells (`--spare-density 0`) and bought roughly a third of its
# own area margin doing it, while a sibling arm that kept all ten was still
# ahead of it on BOTH area and power. The search had already found the right
# answer. Nothing stopped it publishing the wrong ones beside it, because
# "spares deleted" was a column in the record and not a verdict over it.
#
# THE THREE RULES THIS IMPLEMENTS, AND WHY EACH ONE IS A REFUSAL
# ==============================================================
# 1. THE REQUIREMENT IS DECLARED, NEVER ASSUMED. This module contains no
#    spare-cell count, no density and no kind list. Every floor comes from the
#    design's own `eco_readiness` declaration. A design that declares none is
#    NOT thereby failing -- but the record must not silently collapse the two
#    ways of declaring none, so `NOT_DECLARED` (nobody stated a requirement)
#    and `NOT_REQUIRED` (somebody stated that there is none) are DIFFERENT
#    states with different codes, and both are visible on the axis row.
#
# 2. ABSENT IS NOT ZERO. A candidate whose spare population could not be read
#    is UNDETERMINED, exactly like every other unmeasured axis here. It is
#    never "0 spares, therefore fails" -- that convicts a run nobody looked at
#    -- and never "no data, therefore passes". The record shape does that work:
#    the producer emits NOT_MEASURED with a reason and NO value, and
#    `_record_defect` refuses it before any comparison happens.
#
# 3. THE COUNT IS NOT THE WHOLE PROPERTY. Ten spares of the wrong kind, ten
#    spares in one corner of the die, or ten spares with floating inputs are
#    not ECO readiness. So the declaration may ask for a kind mix, a spatial
#    spread, tie-off, spare pads and survival-to-the-shipped-netlist, and each
#    one becomes its own proof. What it may NOT do is make this axis claim more
#    than it measured: only proofs the declaration ASKS FOR are run, and every
#    obligation this gate did not prove is listed by name in the axis row's
#    `applicability.not_proved`. If all the artefacts can support is a count,
#    the record says it is a count.
ECO_AXIS = "eco_readiness"

#: How many spare/ECO cells the flow's own insertion plan recorded.
ECO_M_COUNT = "design_for_eco.spares.count"
#: How many of them are still named by the SHIPPED artefacts after every
#: optimisation pass that could have stripped them. A different fact from the
#: one above, and the one that actually bears on a post-tape-out repair.
ECO_M_SURVIVING = "design_for_eco.spares.surviving.count"
#: Distinct placement positions the spares occupy. A SPREAD PROXY, not
#: reachability: see `applicability.not_proved`.
ECO_M_POSITIONS = "design_for_eco.spares.distinct_positions.count"
#: Whether every spare input is tied off. A verdict, not a count.
ECO_M_TIE_OFF = "design_for_eco.spares.tie_off.verdict"
#: Reserved spare ECO pads, for a design whose repair has to reach a pin.
ECO_M_PADS = "design_for_eco.spare_pads.count"


def eco_metric_for_kind(kind: str) -> str:
    """The per-kind spare count metric. One metric NAME per kind, not one
    metric with the kind in `scope`, because each kind carries its OWN declared
    floor and a proof holds exactly one `limit_key`."""
    return f"design_for_eco.spares.kind.{kind}.count"


ECO_REQUIRED = "REQUIRED"
ECO_NOT_REQUIRED = "NOT_REQUIRED"
ECO_NOT_DECLARED = "NOT_DECLARED"
ECO_UNREADABLE = "UNREADABLE"
#: The three states an ABSENT declaration resolves to once the DELIVERY PATH is
#: known. They exist because "nobody declared a requirement" is not one finding
#: -- it is three, and only one of them is benign:
#:
#:     on the CHIP path   a tape-out-bound design with no stated spare/ECO
#:                        requirement. [CANNOT CHECK]; never a silent pass.
#:     on the IP path     a hardmacro delivery owes no spare population. A
#:                        finding, and the right one.
#:     path unknown       no route was established, so the design has NOT been
#:                        shown to be an IP delivery. Refuse rather than guess.
ECO_NOT_DECLARED_ON_CHIP_PATH = "NOT_DECLARED_ON_CHIP_PATH"
ECO_NOT_APPLICABLE_ON_IP_PATH = "NOT_APPLICABLE_ON_IP_PATH"
ECO_PATH_UNDETERMINED = "PATH_UNDETERMINED"

#: The delivery-path values this module reasons about. They are RE-DECLARED
#: here, as strings, rather than imported from `_ppa/delivery_path.py`, and that
#: is deliberate: the gate reads records and must not acquire a dependency on a
#: module that walks a filesystem. `test_the_two_path_vocabularies_agree`
#: measures that the two spellings match, so the decoupling cannot silently
#: become a divergence.
PATH_CHIP = "CHIP"
PATH_IP = "IP"
PATH_NOT_SUPPLIED = "NOT_SUPPLIED"


def _pos_int(v: Any) -> Optional[int]:
    """`v` as a non-negative int, or None if it is not one. `True` is not 1."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    if isinstance(v, float) and v != int(v):
        return None
    n = int(v)
    return n if n >= 0 else None


def eco_requirement_state(decl: Any) -> Tuple[str, str, Dict[str, Any]]:
    """(state, code, detail) for a design's ECO-readiness declaration.

    The FOUR answers are deliberately four and not two:

        NOT_DECLARED   no `eco_readiness` block. Nobody was asked. The axis
                       makes no finding and says so.
        NOT_REQUIRED   a block that says this design requires no spares --
                       `required: false`, or a floor of 0 with nothing else
                       asked for. A statement, not a silence.
        REQUIRED       a block with at least one checkable obligation.
        UNREADABLE     a block that is not an object, or one that says
                       `required: true` and then states nothing checkable.
                       Somebody tried to state a requirement and this module
                       cannot tell what it is; refusing is the only safe read.
    """
    if decl is None:
        return ECO_NOT_DECLARED, C_ECO_NOT_DECLARED, {
            "reason": ("the contract carries no `eco_readiness` block, so no "
                       "spare/ECO population was required of this design and "
                       "this run makes no ECO-readiness finding about it")}
    if not isinstance(decl, Mapping):
        return ECO_UNREADABLE, C_ECO_DECLARATION_UNREADABLE, {
            "reason": (f"`eco_readiness` is {type(decl).__name__}, not an "
                       "object; a requirement nobody can parse is refused, "
                       "not waived")}

    required = decl.get("required")
    floor = _pos_int(decl.get("min_spare_cells"))
    kinds_raw = decl.get("min_spare_cells_by_kind")
    kinds: Dict[str, int] = {}
    if isinstance(kinds_raw, Mapping):
        for k, v in kinds_raw.items():
            n = _pos_int(v)
            if isinstance(k, str) and k.strip() and n:
                kinds[k.strip()] = n
    positions = _pos_int(decl.get("min_distinct_positions"))
    pads = _pos_int(decl.get("min_spare_pads"))
    tie_off = bool(decl.get("require_tie_off"))
    preservation = bool(decl.get("require_preservation"))

    obligations: Dict[str, Any] = {}
    if floor:
        obligations["min_spare_cells"] = floor
    if kinds:
        obligations["min_spare_cells_by_kind"] = dict(sorted(kinds.items()))
    if positions:
        obligations["min_distinct_positions"] = positions
    if pads:
        obligations["min_spare_pads"] = pads
    if tie_off:
        obligations["require_tie_off"] = True
    if preservation:
        obligations["require_preservation"] = True

    if required is False:
        return ECO_NOT_REQUIRED, C_ECO_NOT_REQUIRED, {
            "reason": ("the declaration states `required: false`: this design "
                       "asks for no spare/ECO population"),
            "obligations_ignored": obligations}
    if obligations:
        return ECO_REQUIRED, C_OK, {"obligations": obligations}
    if required is True:
        return ECO_UNREADABLE, C_ECO_REQUIREMENT_EMPTY, {
            "reason": ("the declaration says `required: true` and then states "
                       "no floor, no kind, no spread, no pad count and no "
                       "tie-off or preservation obligation. There is nothing "
                       "here to check, and a requirement with nothing to check "
                       "is not a satisfied one")}
    return ECO_NOT_REQUIRED, C_ECO_NOT_REQUIRED, {
        "reason": ("the declaration states no obligation and does not say "
                   "`required: true`, so it declares that this design needs "
                   "no spare/ECO population")}


def eco_applicability(decl: Any, delivery: Any
                      ) -> Tuple[str, str, Dict[str, Any]]:
    """(state, code, detail) for one design: its DECLARATION and its ROUTE.

    THE DECLARATION WINS WHERE IT SPEAKS. A design that states a requirement is
    held to it whatever path it is on, and a design that states it needs none
    has made a decision this axis does not overrule. The route only decides
    what an ABSENT declaration means -- which is exactly the case that used to
    mean nothing at all.

    An opt-out ON THE CHIP PATH is still NOT_APPLICABLE, and it gets its own
    code. It is the one shape somebody would reach for to get around this axis,
    so a reader has to be able to find it; but converting it into a refusal
    would be overruling a decision, which is not this module's to make.
    """
    state, code, detail = eco_requirement_state(decl)
    path_row = delivery if isinstance(delivery, Mapping) else {}
    path = str(path_row.get("path") or PATH_NOT_SUPPLIED)
    detail = dict(detail)
    detail["delivery_path"] = path
    if path_row.get("reason"):
        detail["delivery_path_reason"] = path_row["reason"]
    if path_row.get("evidence"):
        detail["delivery_path_evidence"] = path_row["evidence"]

    if state == ECO_REQUIRED or state == ECO_UNREADABLE:
        return state, code, detail
    if state == ECO_NOT_REQUIRED:
        if path == PATH_CHIP:
            return state, C_ECO_OPTED_OUT_ON_CHIP_PATH, detail
        return state, code, detail

    # --- the declaration is ABSENT: the route decides what that means -------
    if path == PATH_CHIP:
        detail["reason"] = (
            "the flow routed this design onto the CHIP path, so it is "
            "tape-out-bound, and no design-for-ECO requirement was declared "
            "for it. A tape-out-bound design with no stated spare/ECO "
            "requirement is a [CANNOT CHECK]: this run cannot say whether the "
            "layout could be repaired by a metal-only ECO, and saying nothing "
            "must not read as saying it is fine")
        return ECO_NOT_DECLARED_ON_CHIP_PATH, C_ECO_NOT_DECLARED_ON_CHIP_PATH, detail
    if path == PATH_IP:
        detail["reason"] = (
            "the flow routed this design to the hardmacro/IP terminal, so it "
            "is not tape-out-bound and owes no spare/ECO population of its "
            "own. The die that integrates it owes one")
        return ECO_NOT_APPLICABLE_ON_IP_PATH, C_ECO_NOT_APPLICABLE_ON_IP_PATH, detail
    if path == PATH_NOT_SUPPLIED:
        # Nobody asked. Distinct from every route answer, and it keeps the
        # pre-route behaviour for a caller that adjudicates records with no
        # project behind them.
        return ECO_NOT_DECLARED, C_ECO_NOT_DECLARED, detail
    detail["reason"] = (
        f"no design-for-ECO requirement was declared and the delivery path is "
        f"{path}: the route this design took could not be established, so it "
        "has NOT been shown to be a hardmacro delivery. Treating an "
        "unestablished route as an IP delivery is the guess this axis refuses "
        "to make")
    return ECO_PATH_UNDETERMINED, C_ECO_PATH_UNDETERMINED, detail


#: Every obligation this axis knows how to prove, and the sentence that says
#: what it is. `not_proved` is built by SUBTRACTION from this table, so an
#: obligation added here and forgotten in the declaration is disclosed by
#: construction rather than by somebody remembering to mention it.
ECO_OBLIGATIONS: Tuple[Tuple[str, str], ...] = (
    ("min_spare_cells",
     "how many spare/ECO cells the insertion plan recorded"),
    ("min_spare_cells_by_kind",
     "how many spares of each named kind -- a mux2 cannot do a flop's repair"),
    ("min_distinct_positions",
     "how many distinct placement positions the spares occupy"),
    ("require_tie_off",
     "whether every spare input is tied off rather than left floating"),
    ("min_spare_pads",
     "how many spare ECO pads are reserved"),
    ("require_preservation",
     "how many spares are still named by the SHIPPED artefacts after every "
     "optimisation pass that could have stripped them"),
)

#: What this axis CANNOT establish from any artefact the flow produces, stated
#: unconditionally on every applicable row. These are not obligations somebody
#: forgot to declare; they are properties of ECO readiness that no count, no
#: position list and no tie-off report can answer.
ECO_NEVER_PROVED: Tuple[Mapping[str, str], ...] = (
    {"property": "eco_reachability",
     "reason": ("whether a metal-only ECO could actually route from a given "
                "failing net to a given spare depends on the routing "
                "resources left around BOTH, and no artefact here is a "
                "routability answer. Distinct placement positions are a "
                "spread PROXY and are reported as one")},
    {"property": "kind_sufficiency",
     "reason": ("whether the declared kind mix can implement the repairs this "
                "design will actually need is a judgement about future bugs. "
                "This axis checks the mix against the declaration and makes "
                "no claim that the declaration is the right mix")},
    {"property": "post_eco_timing",
     "reason": ("whether a repair built from these spares would still meet "
                "timing is a question for an STA run on the ECO netlist, "
                "which does not exist yet")},
)


def eco_proofs_and_limits(decl: Any
                          ) -> Tuple[Tuple[Proof, ...],
                                     Dict[str, Dict[str, Any]],
                                     List[str]]:
    """(proofs, limits, obligations-NOT-asked-for) for one declaration.

    ONLY what the declaration asks for becomes a proof. That is rule 1 in the
    header working in the direction people forget: a gate that also checked the
    obligations nobody declared would be inventing requirements, which is the
    same defect as inventing a threshold.
    """
    state, _code, detail = eco_requirement_state(decl)
    if state != ECO_REQUIRED:
        return (), {}, [name for name, _ in ECO_OBLIGATIONS]
    obligations: Mapping[str, Any] = detail.get("obligations") or {}
    proofs: List[Proof] = []
    limits: Dict[str, Dict[str, Any]] = {}

    floor = obligations.get("min_spare_cells")
    if floor:
        limits[ECO_M_COUNT] = {"min": floor, "unit": "count"}
        proofs.append(Proof(ECO_M_COUNT, KIND_LIMIT_MIN,
                            limit_key=ECO_M_COUNT))
    for kind, n in (obligations.get("min_spare_cells_by_kind") or {}).items():
        metric = eco_metric_for_kind(kind)
        limits[metric] = {"min": n, "unit": "count"}
        proofs.append(Proof(metric, KIND_LIMIT_MIN, limit_key=metric))
    positions = obligations.get("min_distinct_positions")
    if positions:
        limits[ECO_M_POSITIONS] = {"min": positions, "unit": "count"}
        proofs.append(Proof(ECO_M_POSITIONS, KIND_LIMIT_MIN,
                            limit_key=ECO_M_POSITIONS))
    if obligations.get("require_tie_off"):
        proofs.append(Proof(ECO_M_TIE_OFF, KIND_VERDICT_IN,
                            accept=("TIED_OFF",)))
    pads = obligations.get("min_spare_pads")
    if pads:
        limits[ECO_M_PADS] = {"min": pads, "unit": "count"}
        proofs.append(Proof(ECO_M_PADS, KIND_LIMIT_MIN, limit_key=ECO_M_PADS))
    if obligations.get("require_preservation"):
        # Survival is held to the SAME floor as insertion when one is declared.
        # A design that requires ten spares and ships nine has nine, whatever
        # the plan said it inserted.
        surviving_floor = floor if floor else 1
        limits[ECO_M_SURVIVING] = {"min": surviving_floor, "unit": "count"}
        proofs.append(Proof(ECO_M_SURVIVING, KIND_LIMIT_MIN,
                            limit_key=ECO_M_SURVIVING))

    not_asked = [name for name, _ in ECO_OBLIGATIONS if name not in obligations]
    return tuple(proofs), limits, not_asked


#: WHY `worst_slack_ns` IS A GROUP AND NOT A RELAXATION.
#:
#: MEASURED: across all six STA artefacts of a real sign-off run, both
#: `timing.setup.wns_ns` and `timing.hold.wns_ns` are NOT_MEASURED on every
#: view, with the reason "the artefact carries no wns line for this view" --
#: because the two MULTI-CORNER sign-off emitters, the ones that decide setup at
#: the slow corner and hold at the fast one, call `report_worst_slack` and
#: `report_tns` and never call `report_wns` at all. So the hold axis was
#: STRUCTURALLY unprovable: no run of this flow could produce the evidence it
#: proved from, on any design, ever.
#:
#: The tool DOES print the fact, under its other name. OpenSTA's wns is
#: `min(0, worst_slack)` -- stated in `_ppa/timing.py`'s own header and measured
#: in `tests/test_ppa_timing.py`, where one view reports `worst slack max 0.19`
#: beside `wns max 0.00`. Under that identity
#:
#:     wns >= 0   <=>   min(0, worst_slack) >= 0   <=>   worst_slack >= 0
#:
#: so `slack_nonneg` over `worst_slack_ns` is the SAME PREDICATE, not a looser
#: one. It admits no candidate that the wns proof would refuse: a negative worst
#: slack is a negative wns and both VIOLATE. `test_ppa_feasibility_slack_proofs`
#: asserts that equivalence over a swept range rather than trusting this comment.
#:
#: What it is NOT allowed to do is rescue a view nobody analysed. OpenSTA's
#: `worst_slack` starts at infinity and takes the min over the analysed paths,
#: so an empty path set leaves it at INF -- and `_ppa/timing.py` emits that as
#: NOT_MEASURED with the no-paths reason, which this axis then refuses like any
#: other NOT_MEASURED record. The sentinel is handled where it is read.
#:
#: `report_wns` is ALSO now emitted by the two sign-off stanzas (see
#: `phase3_one_shot_runner._report_wns_tcl`) so that future runs state the fact
#: directly. This group is what makes the axis provable on the runs that already
#: exist, and on any tool that reports a worst slack and not a wns.

DEFAULT_AXES: Tuple[Axis, ...] = (
    Axis("setup", ((Proof("timing.setup.wns_ns", KIND_SLACK_NONNEG),),
                   (Proof("timing.setup.worst_slack_ns", KIND_SLACK_NONNEG),),
                   (Proof("timing.setup.violations", KIND_COUNT_ZERO),))),
    Axis("hold", ((Proof("timing.hold.wns_ns", KIND_SLACK_NONNEG),),
                  (Proof("timing.hold.worst_slack_ns", KIND_SLACK_NONNEG),),
                  (Proof("timing.hold.violations", KIND_COUNT_ZERO),))),
    Axis("drv", ((Proof("timing.drv.violations", KIND_COUNT_ZERO),),
                 (Proof("timing.drv.max_tran_violations", KIND_COUNT_ZERO),
                  Proof("timing.drv.max_cap_violations", KIND_COUNT_ZERO),
                  Proof("timing.drv.max_fanout_violations", KIND_COUNT_ZERO)))),
    Axis("drc", ((Proof("physical.drc.violations", KIND_COUNT_ZERO),),)),
    Axis("lvs", ((Proof("physical.lvs.verdict", KIND_VERDICT_IN,
                        accept=("CLEAN", "MATCH")),),
                 (Proof("physical.lvs.violations", KIND_COUNT_ZERO),))),
    Axis("antenna", ((Proof("physical.antenna.violations", KIND_COUNT_ZERO),),)),
    Axis("ir", ((Proof("power.ir.violations", KIND_COUNT_ZERO),),
                (Proof("power.ir.worst_drop_v", KIND_LIMIT_MAX,
                       limit_key="power.ir.worst_drop_v"),))),
    Axis("em", ((Proof("reliability.em.violations", KIND_COUNT_ZERO),),
                (Proof("reliability.em.worst_ratio", KIND_LIMIT_MAX,
                       limit_key="reliability.em.worst_ratio"),))),
    Axis("equivalence", ((Proof("equivalence.verdict", KIND_VERDICT_IN,
                                accept=("PROVEN", "EQUIVALENT")),),)),
    #: The proofs here are a PLACEHOLDER and are never the ones evaluated:
    #: `_evaluate_axis` rebuilds this axis from the design's own declaration
    #: before it runs, so the obligations checked are exactly the obligations
    #: declared. The entry exists in the table so that the axis is a ROW on
    #: every verdict -- including on a design that declared nothing, which is
    #: the case where an absent row would read as "no problem here".
    Axis(ECO_AXIS, ((Proof(ECO_M_COUNT, KIND_LIMIT_MIN,
                           limit_key=ECO_M_COUNT),),)),
)


# ---------------------------------------------------------------------------
# the two configurations. THEIR FIELD NAMES ARE DISJOINT AND THAT IS CHECKED.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class FeasibilityPolicy:
    """Everything the HARD gate is allowed to read. No weights, no penalties.

    `required_views` is not optional and has no default that means "any". A
    setup check is feasible across the views the contract required, and a
    module that let an undeclared view set mean "whatever was measured is
    enough" would credit a one-corner run as signoff.
    """
    axes: Tuple[Axis, ...] = DEFAULT_AXES
    required_views: Tuple[Mapping[str, Any], ...] = ()
    #: Per-axis override of `required_views`, keyed by axis name.
    #:
    #: WHY ONE GLOBAL LIST WAS NOT ENOUGH. The axes are not measured in one
    #: scope namespace. Setup and hold sign off across process corners; DRC, LVS,
    #: antenna, IR, EM, equivalence and design-for-ECO readiness are single
    #: measurements over one database and have no process corner at all. With one global list, a contract that
    #: declared the timing corners it signs off at ALSO demanded those corners of
    #: DRC -- so either DRC was permanently uncovered, or its producer had to
    #: emit the same measurement once per corner under a fabricated scope, N
    #: records carrying ONE source hash, into an index whose whole job is to
    #: notice when two numbers claim to be the same fact. That is a modelling
    #: defect being paid for by a producer.
    #:
    #: WHAT THIS DOES NOT CHANGE. An unmeasured required view still sinks the
    #: axis. A corner nobody ran is a corner nobody ran, and this field cannot
    #: express "any view will do" -- an axis named with an EMPTY list is
    #: UNDETERMINED, exactly as an undeclared global list is. What it changes is
    #: only WHICH views each axis is asked for. An axis this map does not name
    #: falls back to `required_views`, so a contract written before this field
    #: existed adjudicates identically.
    required_views_by_axis: Mapping[str, Tuple[Mapping[str, Any], ...]] = \
        field(default_factory=dict)
    limits: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    allow_waivers: bool = True
    #: The design's own DESIGN-FOR-ECO declaration, verbatim, or None when the
    #: contract carried none.
    #:
    #: WHY IT IS A FIELD OF ITS OWN AND NOT A ROW IN `limits`. `limits` answers
    #: "what number does this threshold take"; this answers "is there a
    #: requirement at all". Collapsing them makes an ABSENT limit and a
    #: DECLARED-ZERO limit the same input, and those are the two states the ECO
    #: axis exists to keep apart -- one is "nobody asked", the other is
    #: "somebody said no spares are needed". The floors this declaration
    #: implies are derived into `limits` at evaluation time by
    #: `eco_proofs_and_limits`, so nothing here is a number this module chose.
    eco_requirement: Optional[Mapping[str, Any]] = None
    #: The DELIVERY PATH this design is on, as `_ppa/delivery_path.resolve()`
    #: returned it -- `{"path", "reason", "evidence"}` -- or None when nobody
    #: established one.
    #:
    #: WHY A ROUTE AND NOT A DECLARATION. `eco_requirement` above is opt-in,
    #: and a run that simply omits it would get NOT_APPLICABLE: the pre-fix
    #: behaviour, silently. The predicate that closes that must be one a design
    #: cannot accidentally omit, so it is the ROUTE THE FLOW TOOK -- a design
    #: routed 0.5ic -> 15.5ic -> 26.5ic -> 37.5ic is tape-out-bound, and one
    #: that terminates at 37.5ip is a hardmacro delivery and is not. It is NOT
    #: inferred from a GDS (an IP delivery streams one too) or from the PDK
    #: (every design here targets a real one).
    #:
    #: This field holds a VALUE, not a path to probe: the gate reads records
    #: and never a filesystem, and a promotion gate that walked a tree could be
    #: pointed at a different one than the records came from.
    delivery_path: Optional[Mapping[str, Any]] = None


@dataclass(frozen=True)
class PenaltyWeights:
    """Everything the SEARCH penalty is allowed to read. No axis table.

    Deliberately shares NO field name with `FeasibilityPolicy`; that disjointness
    is what `separation_report` measures, and it is the machine-checkable form
    of "those are two different code paths and must not share a threshold".
    """
    weights: Mapping[str, float] = field(default_factory=dict)
    undetermined_weight: float = 1.0
    default_weight: float = 1.0


@dataclass(frozen=True)
class AxisResult:
    """One axis's verdict, and the VIEW COVERAGE the verdict rests on.

    `coverage` is not decoration. An UNDETERMINED axis has two very different
    causes -- a view nobody ran, and a view somebody ran whose artefact could
    not support the metric -- and before this field the verdict said only
    `FEAS_INCOMPLETE_VIEW_SET` for the first and `FEAS_NOT_MEASURED` for the
    second, with no statement of WHICH view either was about. A reader who
    wants to re-decide the policy question ("is one unmeasured corner supposed
    to sink the axis?") needs the per-view answer, so the record states it.
    """
    name: str
    status: str
    codes: Tuple[str, ...]
    detail: Tuple[Mapping[str, Any], ...] = ()
    waiver_ids: Tuple[str, ...] = ()
    coverage: Tuple[Mapping[str, Any], ...] = ()
    #: For an axis whose APPLICABILITY is itself declared: which of the four
    #: declaration states was read, what obligations it produced, and -- the
    #: part a reader is entitled to and would otherwise have to infer -- what
    #: this axis did NOT prove. Absent on the axes that always apply.
    applicability: Optional[Mapping[str, Any]] = None

    def as_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"axis": self.name, "status": self.status,
                             "codes": list(self.codes),
                             "evidence": [dict(x) for x in self.detail],
                             "coverage": [dict(x) for x in self.coverage]}
        if self.waiver_ids:
            d["waiver_ids"] = list(self.waiver_ids)
        if self.applicability is not None:
            d["applicability"] = dict(self.applicability)
        return d


@dataclass(frozen=True)
class FeasibilityResult:
    candidate_id: str
    verdict: str
    axes: Tuple[AxisResult, ...]
    codes: Tuple[str, ...]
    waivers: Tuple[Mapping[str, Any], ...] = ()

    @property
    def eligible_for_promotion(self) -> bool:
        """The ONE predicate any promoter may use. Not a number, not a margin."""
        return self.verdict == FEASIBLE

    def as_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "verdict": self.verdict,
            "codes": list(self.codes),
            "axes": [a.as_dict() for a in self.axes],
            "waivers": [dict(w) for w in self.waivers],
        }


# ---------------------------------------------------------------------------
# metric record reading -- defensive, because the record is another lane's
# ---------------------------------------------------------------------------
def _is_number(v: Any) -> bool:
    # bool is an int in Python and a boolean slack is a parse defect, not a 1.
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _record_defect(rec: Any) -> Optional[str]:
    """None if `rec` may support a proof; otherwise the code saying why not."""
    if not isinstance(rec, Mapping):
        return C_BAD_RECORD
    if rec.get("schema") != METRIC_SCHEMA:
        return C_BAD_RECORD
    status = rec.get("status")
    if status not in METRIC_STATUSES:
        return C_BAD_STATUS
    if status not in COMPARABLE_STATUSES:
        # A NOT_MEASURED record that still carries a value is worse than a
        # missing one: it looks like evidence to anything that reads `value`
        # without reading `status`, which is the exact confusion that lets
        # "DRC never ran" print the same 0 as "DRC found nothing".
        if status == "NOT_MEASURED" and rec.get("value") is not None:
            return C_NOT_MEASURED_CARRIES_VALUE
        return C_NOT_MEASURED
    if rec.get("value") is None:
        return C_BAD_RECORD
    if not isinstance(rec.get("scope"), Mapping):
        return C_BAD_RECORD
    src = rec.get("source")
    if not isinstance(src, Mapping):
        return C_NO_PROVENANCE
    if not str(src.get("path") or "").strip():
        return C_NO_PROVENANCE
    digest = str(src.get("sha256") or "")
    if not digest.startswith("sha256:") or len(digest) != len("sha256:") + 64:
        return C_NO_PROVENANCE
    return None


#: Artefact-shaped provenance values. A record that could not support a metric
#: often names, in its own `provenance`, the artefact whose ABSENCE is the
#: reason -- and that is a DIFFERENT file from the one the parser read. The
#: `sources` list carries what was READ; without this, a `MISSING` line cites a
#: file that exists and is healthy, and the reader learns nothing about what to
#: produce. MEASURED on this repository's own corpus: 42 NOT_MEASURED metrics
#: name `reports/phase3/em_signoff.json` in provenance while citing
#: `reports/phase3/em.json` as the source, and em.json is present and states
#: `verdict: MEASURED`. Naming a healthy file as the citation for a missing
#: measurement is a misdirection, not a naming.
#:
#: The test is on the SHAPE of the value, not on the key's name: a rule keyed to
#: `screen_artefact` would fit today's corpus and miss the next producer's word
#: for the same thing. Whitespace disqualifies -- provenance also carries prose
#: (`stage_basis` reads "... the worst J/Jmax ratio ..."), and a sentence that
#: happens to contain a slash is not a path.
_ARTEFACT_SUFFIXES = (".json", ".rpt", ".log", ".csv", ".def", ".spef",
                      ".v", ".lib", ".sdc", ".gds")


def _looks_like_artefact(value: Any) -> bool:
    """Is this provenance value a file this run could have produced?"""
    return (isinstance(value, str) and bool(value)
            and not re.search(r"\s", value)
            and value.lower().endswith(_ARTEFACT_SUFFIXES))


def _awaited_artefacts(records: Sequence[Any], read: Sequence[str]) -> List[str]:
    """Artefacts named in provenance that are NOT the ones already read.

    Only the difference is returned. An artefact that was read and found
    wanting is reported by `sources` and its own reason; repeating it here
    would say "waiting for" about a file that is present.
    """
    already = {str(x) for x in read if x}
    out = set()
    for rec in records:
        if not isinstance(rec, Mapping):
            continue
        for value in (rec.get("provenance") or {}).values():
            if _looks_like_artefact(value) and str(value) not in already:
                out.add(str(value))
    return sorted(out)

def _covers(scope: Mapping[str, Any], view: Mapping[str, Any]) -> bool:
    """True when `scope` satisfies every key/value the required `view` names.

    A view is a SUBSET, so a contract can require "the slow process corner"
    without also having to restate the clock name and the check type.
    """
    return all(k in scope and scope[k] == v for k, v in view.items())


def _evaluate_one(rec: Mapping[str, Any], proof: Proof,
                  policy: FeasibilityPolicy) -> Tuple[str, Tuple[str, ...],
                                                      Dict[str, Any]]:
    """Adjudicate one VALID MEASURED record against one proof."""
    value = rec.get("value")
    ev: Dict[str, Any] = {"metric": proof.metric, "kind": proof.kind,
                          "value": value, "unit": rec.get("unit"),
                          "scope": dict(rec.get("scope") or {}),
                          "source": dict(rec.get("source") or {})}
    if proof.kind == KIND_VERDICT_IN:
        ok = isinstance(value, str) and value.upper() in {
            a.upper() for a in proof.accept}
        ev["accept"] = list(proof.accept)
        return (AXIS_SATISFIED if ok else AXIS_VIOLATED,
                (C_OK,) if ok else (C_VIOLATION,), ev)

    if not _is_number(value):
        return AXIS_UNDETERMINED, (C_NON_NUMERIC,), ev

    if proof.kind == KIND_SLACK_NONNEG:
        ok = value >= 0
        return (AXIS_SATISFIED if ok else AXIS_VIOLATED,
                (C_OK,) if ok else (C_VIOLATION,), ev)

    if proof.kind == KIND_COUNT_ZERO:
        if value < 0:
            return AXIS_UNDETERMINED, (C_NEGATIVE_COUNT,), ev
        ok = value == 0
        return (AXIS_SATISFIED if ok else AXIS_VIOLATED,
                (C_OK,) if ok else (C_VIOLATION,), ev)

    if proof.kind == KIND_LIMIT_MAX:
        lim = policy.limits.get(proof.limit_key)
        if not isinstance(lim, Mapping) or not _is_number(lim.get("max")):
            # There is no default. A limit this module supplied would be a
            # design-specific number living in chip-agnostic source.
            return AXIS_UNDETERMINED, (C_LIMIT_NOT_DECLARED,), ev
        ev["limit"] = dict(lim)
        if str(lim.get("unit", "")) != str(rec.get("unit", "")):
            # Comparing a magnitude to a limit requires the same unit; sign
            # comparisons do not, which is why only this kind checks it.
            return AXIS_UNDETERMINED, (C_UNIT_MISMATCH,), ev
        ok = value <= lim["max"]
        return (AXIS_SATISFIED if ok else AXIS_VIOLATED,
                (C_OK,) if ok else (C_VIOLATION,), ev)

    if proof.kind == KIND_LIMIT_MIN:
        lim = policy.limits.get(proof.limit_key)
        if not isinstance(lim, Mapping) or not _is_number(lim.get("min")):
            # Same refusal as the ceiling kind, for the same reason: a floor
            # this module supplied would be a design decision in agnostic
            # source, and "at least however many happen to be there" is not a
            # requirement.
            return AXIS_UNDETERMINED, (C_LIMIT_NOT_DECLARED,), ev
        ev["limit"] = dict(lim)
        if str(lim.get("unit", "")) != str(rec.get("unit", "")):
            return AXIS_UNDETERMINED, (C_UNIT_MISMATCH,), ev
        if value < 0:
            # A negative population is not "very few"; it is a broken parse,
            # and convicting a design on one would be convicting the parser.
            return AXIS_UNDETERMINED, (C_NEGATIVE_COUNT,), ev
        ok = value >= lim["min"]
        return (AXIS_SATISFIED if ok else AXIS_VIOLATED,
                (C_OK,) if ok else (C_VIOLATION,), ev)

    return AXIS_UNDETERMINED, (C_BAD_RECORD,), ev


#: Per-view coverage states, published on every AxisResult.
COV_MEASURED = "MEASURED"
#: A record covers the view and states the metric -- the proof could be evaluated.
COV_NOT_MEASURED = "NOT_MEASURED"
#: A record covers the view and says it could NOT support the metric. The run
#: looked; the artefact did not carry the fact. Distinct from COV_NO_RECORD
#: because the fix is different: one needs a better artefact, the other a run.
COV_NO_RECORD = "NO_RECORD"
#: Nothing in the candidate names this metric under a scope covering this view.


def views_for(axis_name: str, policy: FeasibilityPolicy
              ) -> Tuple[Mapping[str, Any], ...]:
    """The views THIS axis must be covered across.

    `required_views_by_axis` when it names the axis, the global
    `required_views` otherwise. An axis named with an empty list is NOT thereby
    exempt: an empty view set is undeclared, and undeclared is UNDETERMINED --
    there is no spelling here that means "whatever was measured is enough".
    """
    per = policy.required_views_by_axis or {}
    if isinstance(per, Mapping) and axis_name in per:
        v = per[axis_name]
        if isinstance(v, Sequence) and not isinstance(v, (str, bytes)):
            return tuple(dict(x) for x in v if isinstance(x, Mapping))
        return ()
    return tuple(policy.required_views)


def _evaluate_proof(records: Sequence[Any], proof: Proof,
                    policy: FeasibilityPolicy,
                    views: Sequence[Mapping[str, Any]]
                    ) -> Tuple[str, Tuple[str, ...], List[Dict[str, Any]],
                               List[Dict[str, Any]]]:
    """Adjudicate one proof, and REPORT the per-view coverage it rested on.

    The coverage rows are built for every declared view whatever the verdict, so
    a SATISFIED axis states its coverage too -- a reader checking whether the
    view set was the right one should not have to make the axis fail first.
    """
    named = [r for r in records
             if isinstance(r, Mapping) and r.get("metric") == proof.metric]
    if not named:
        cov = [{"metric": proof.metric, "view": dict(v),
                "state": COV_NO_RECORD,
                "reason": "no record in this candidate names this metric"}
               for v in views]
        return (AXIS_UNDETERMINED, (C_METRIC_ABSENT,),
                [{"metric": proof.metric, "kind": proof.kind, "absent": True}],
                cov)

    codes: List[str] = []
    evidence: List[Dict[str, Any]] = []
    usable: List[Mapping[str, Any]] = []
    #: Rejected records are kept WITH their scope, not just their code. Before
    #: this, a NOT_MEASURED row contributed a bare code and the verdict could
    #: not say which view it was about -- so "the ff corner was never analysed"
    #: and "the ff corner was analysed and the report carried no wns line" were
    #: one sentence.
    rejected: List[Tuple[Mapping[str, Any], str]] = []
    for rec in named:
        defect = _record_defect(rec)
        if defect is not None:
            codes.append(defect)
            evidence.append({"metric": proof.metric, "kind": proof.kind,
                             "rejected": defect,
                             "status": (rec.get("status")
                                        if isinstance(rec, Mapping) else None)})
            rejected.append((rec, defect))
            continue
        usable.append(rec)

    if not views:
        # Not declared is not the same as satisfied. Without a declared view
        # set nothing here can tell a single-corner run from full coverage.
        codes.append(C_VIEWS_NOT_DECLARED)
        return (AXIS_UNDETERMINED, tuple(dict.fromkeys(codes)), evidence,
                [{"metric": proof.metric, "view": None,
                  "state": COV_NO_RECORD,
                  "reason": "no required view is declared for this axis, so "
                            "there is nothing this proof could be complete "
                            "across"}])

    verdict = AXIS_SATISFIED
    uncovered: List[Mapping[str, Any]] = []
    coverage: List[Dict[str, Any]] = []
    for view in views:
        hits = [r for r in usable if _covers(r.get("scope") or {}, view)]
        if not hits:
            uncovered.append(view)
            # Was the view covered by a record that could NOT support the
            # metric? That is a different finding from a view nobody ran, and
            # the reason the artefact gave is carried through verbatim.
            near = [(r, d) for r, d in rejected
                    if isinstance(r, Mapping)
                    and _covers(r.get("scope") or {}, view)]
            if near:
                coverage.append({
                    "metric": proof.metric, "view": dict(view),
                    "state": COV_NOT_MEASURED,
                    "codes": sorted({d for _, d in near}),
                    "reason": "; ".join(
                        sorted({str(r.get("reason") or "the record states no "
                                    "reason") for r, _ in near})),
                    "sources": sorted({str((r.get("source") or {}).get("path")
                                           or "") for r, _ in near if
                                       isinstance(r.get("source"), Mapping)}),
                    # WHAT IS AWAITED, which is not what was READ. See
                    # `_awaited_artefacts`.
                    "awaiting": _awaited_artefacts(
                        [r for r, _ in near],
                        [str((r.get("source") or {}).get("path") or "")
                         for r, _ in near
                         if isinstance(r.get("source"), Mapping)]),
                })
            else:
                coverage.append({
                    "metric": proof.metric, "view": dict(view),
                    "state": COV_NO_RECORD,
                    "reason": "no record covering this view names this metric"})
            continue
        states: List[str] = []
        for rec in hits:
            st, cs, ev = _evaluate_one(rec, proof, policy)
            ev["required_view"] = dict(view)
            evidence.append(ev)
            codes.extend(cs)
            states.append(st)
            if st == AXIS_VIOLATED:
                verdict = AXIS_VIOLATED
            elif st == AXIS_UNDETERMINED and verdict != AXIS_VIOLATED:
                verdict = AXIS_UNDETERMINED
        coverage.append({"metric": proof.metric, "view": dict(view),
                         "state": COV_MEASURED, "records": len(hits),
                         "outcomes": sorted(set(states))})

    if uncovered:
        codes.append(C_INCOMPLETE_VIEW_SET)
        evidence.append({"metric": proof.metric,
                         "uncovered_views": [dict(v) for v in uncovered]})
        # A measured violation stands even if coverage is partial -- it is a
        # fact about the design and more views cannot unmake it.
        if verdict != AXIS_VIOLATED:
            verdict = AXIS_UNDETERMINED

    codes = [c for c in dict.fromkeys(codes) if c != C_OK] or [C_OK]
    return verdict, tuple(codes), evidence, coverage


def _evaluate_axis(records: Sequence[Any], axis: Axis,
                   policy: FeasibilityPolicy) -> AxisResult:
    """Adjudicate one axis. The DISPATCHER, so the ECO axis cannot be reached
    by its placeholder proofs from any caller, including a test."""
    if axis.name == ECO_AXIS:
        return _evaluate_eco_axis(records, policy)
    return _evaluate_axis_table(records, axis, policy)


def _eco_not_proved(state: str, not_asked: Sequence[str]
                    ) -> List[Dict[str, Any]]:
    """Every ECO obligation this run did NOT establish, and why not.

    Built by SUBTRACTION from `ECO_OBLIGATIONS` plus the unconditional
    `ECO_NEVER_PROVED` rows, so a reader of a SATISFIED axis can see the shape
    of the claim rather than having to assume it covers everything. An axis
    that proved a count and printed nothing else would be read as having
    proved ECO readiness.
    """
    if state == ECO_NOT_DECLARED:
        why = ("no ECO-readiness requirement was declared for this design and "
               "no delivery path was supplied, so nothing was owed and "
               "nothing was checked")
    elif state == ECO_NOT_DECLARED_ON_CHIP_PATH:
        why = ("this design is on the chip path and declared no ECO-readiness "
               "requirement, so there was nothing to check it against")
    elif state == ECO_NOT_APPLICABLE_ON_IP_PATH:
        why = ("this design terminates at the hardmacro/IP delivery, so it "
               "owes no spare/ECO population of its own")
    elif state == ECO_PATH_UNDETERMINED:
        why = ("no requirement was declared and the route this design took "
               "could not be established")
    elif state == ECO_NOT_REQUIRED:
        why = "the declaration states this design requires no spare population"
    elif state == ECO_UNREADABLE:
        why = ("the declaration could not be read as a requirement, so no "
               "obligation could be derived from it")
    else:
        why = "the declaration does not ask for it"
    rows: List[Dict[str, Any]] = [
        {"obligation": name, "would_have_stated": desc, "reason": why}
        for name, desc in ECO_OBLIGATIONS if name in set(not_asked)]
    rows.extend(dict(x) for x in ECO_NEVER_PROVED)
    return rows


def _evaluate_eco_axis(records: Sequence[Any],
                       policy: FeasibilityPolicy) -> AxisResult:
    """The design-for-ECO axis, whose proof set is the DESIGN'S declaration.

    Three outcomes before any record is read, and they are three because
    collapsing any pair of them is a lie somebody would act on:

        NOT_DECLARED / NOT_REQUIRED  -> NOT_APPLICABLE. No requirement, so no
            finding. The row is still PRESENT and still says which of the two
            it was, because an absent row reads as a satisfied one.
        UNREADABLE                   -> UNDETERMINED. A requirement was stated
            and cannot be parsed; refusing is the only safe reading.
        REQUIRED                     -> the declared obligations are proved
            from the candidate's own canonical records, through exactly the
            same machinery every other axis uses, so an unmeasured spare
            population is UNDETERMINED and never "0 spares, fails".
    """
    decl = policy.eco_requirement
    state, code, detail = eco_applicability(decl, policy.delivery_path)
    proofs, limits, not_asked = eco_proofs_and_limits(decl)
    app: Dict[str, Any] = {
        "state": state,
        "declaration_present": decl is not None,
        "not_proved": _eco_not_proved(state, not_asked),
    }
    app.update(detail)
    if state in (ECO_NOT_DECLARED, ECO_NOT_REQUIRED,
                 ECO_NOT_APPLICABLE_ON_IP_PATH):
        return AxisResult(ECO_AXIS, AXIS_NOT_APPLICABLE, (code,),
                          applicability=app)
    if state in (ECO_UNREADABLE, ECO_NOT_DECLARED_ON_CHIP_PATH,
                 ECO_PATH_UNDETERMINED):
        return AxisResult(ECO_AXIS, AXIS_UNDETERMINED, (code,),
                          applicability=app)
    if not proofs:
        # Unreachable from `eco_requirement_state` today: REQUIRED needs at
        # least one obligation and every obligation maps to a proof. It is
        # guarded anyway because the failure mode is the worst one available
        # -- a group with no proofs is SATISFIED vacuously, so an obligation
        # added to ECO_OBLIGATIONS without a proof would silently turn this
        # axis into a pass for every design that declares it.
        app["reason"] = ("the declaration states an obligation this gate has "
                         "no proof for, so nothing could be checked")
        return AxisResult(ECO_AXIS, AXIS_UNDETERMINED,
                          (C_ECO_REQUIREMENT_EMPTY,), applicability=app)
    # The floors travel in `limits` so `_evaluate_one` reads them the one way
    # it reads every threshold. Nothing below this line is ECO-specific.
    sub_policy = dataclasses.replace(
        policy, limits={**dict(policy.limits), **limits})
    result = _evaluate_axis_table(
        records, Axis(ECO_AXIS, (tuple(proofs),)), sub_policy)
    app["proofs"] = [{"metric": p.metric, "kind": p.kind,
                      "limit": dict(limits.get(p.limit_key, {})) or None,
                      "accept": list(p.accept) or None}
                     for p in proofs]
    return dataclasses.replace(result, applicability=app)


def _evaluate_axis_table(records: Sequence[Any], axis: Axis,
                         policy: FeasibilityPolicy) -> AxisResult:
    views = views_for(axis.name, policy)
    group_status: List[str] = []
    codes: List[str] = []
    evidence: List[Dict[str, Any]] = []
    coverage: List[Dict[str, Any]] = []
    for group in axis.groups:
        st = AXIS_SATISFIED
        for proof in group:
            pst, pcodes, pev, pcov = _evaluate_proof(records, proof, policy,
                                                     views)
            codes.extend(pcodes)
            evidence.extend(pev)
            coverage.extend(pcov)
            if pst == AXIS_VIOLATED:
                st = AXIS_VIOLATED
            elif pst == AXIS_UNDETERMINED and st != AXIS_VIOLATED:
                st = AXIS_UNDETERMINED
        group_status.append(st)

    if AXIS_VIOLATED in group_status:
        status = AXIS_VIOLATED
    elif AXIS_SATISFIED in group_status:
        status = AXIS_SATISFIED
    else:
        status = AXIS_UNDETERMINED

    keep = [c for c in dict.fromkeys(codes) if c != C_OK]
    return AxisResult(axis.name, status, tuple(keep) or (C_OK,),
                      tuple(evidence), (), tuple(coverage))


# ---------------------------------------------------------------------------
# waivers
# ---------------------------------------------------------------------------
def _waiver_defect(w: Any, axis_names: Iterable[str]) -> Optional[str]:
    if not isinstance(w, Mapping):
        return C_WAIVER_NO_AXIS
    if not str(w.get("axis") or "").strip():
        return C_WAIVER_NO_AXIS
    if w["axis"] not in set(axis_names):
        return C_WAIVER_UNKNOWN_AXIS
    # An UNOWNED waiver is the named failure. A waiver is one person's signed
    # acceptance of a known risk; with nobody named there is no acceptance,
    # only a violation with a note attached, and the violation stands.
    if not str(w.get("owner") or "").strip():
        return C_WAIVER_NO_OWNER
    if not str(w.get("justification") or "").strip():
        return C_WAIVER_NO_JUSTIFICATION
    return None


def _apply_waivers(axes: Sequence[AxisResult], waivers: Sequence[Any],
                   policy: FeasibilityPolicy
                   ) -> Tuple[Tuple[AxisResult, ...], List[Dict[str, Any]]]:
    names = [a.name for a in axes]
    adjudicated: List[Dict[str, Any]] = []
    by_axis: Dict[str, List[str]] = {}
    for w in waivers:
        wid = str((w or {}).get("waiver_id") or "") if isinstance(w, Mapping) else ""
        if not policy.allow_waivers:
            adjudicated.append({"waiver_id": wid, "applied": False,
                                "code": C_WAIVERS_DISABLED})
            continue
        defect = _waiver_defect(w, names)
        if defect is not None:
            adjudicated.append({"waiver_id": wid, "applied": False,
                                "code": defect,
                                "axis": (w.get("axis")
                                         if isinstance(w, Mapping) else None)})
            continue
        by_axis.setdefault(w["axis"], []).append(wid)
        adjudicated.append({"waiver_id": wid, "applied": None,
                            "axis": w["axis"], "owner": w["owner"]})

    out: List[AxisResult] = []
    for a in axes:
        ids = by_axis.get(a.name, [])
        if not ids:
            out.append(a)
            continue
        if a.status == AXIS_VIOLATED:
            # `a.coverage` is carried through: a WAIVED axis is a violation
            # somebody signed for, and the reader is entitled to see the same
            # per-view evidence they signed against.
            out.append(AxisResult(a.name, AXIS_WAIVED, a.codes, a.detail,
                                  tuple(ids), a.coverage))
            for rec in adjudicated:
                if rec.get("waiver_id") in ids and rec.get("applied") is None:
                    rec["applied"] = True
            continue
        # Not violated: either nothing to waive, or -- the dangerous one --
        # the axis was never measured. A waiver may not turn an unknown into
        # a pass; that is the whole failure mode this contract removes.
        code = (C_WAIVER_ON_UNMEASURED if a.status == AXIS_UNDETERMINED
                else "FEAS_WAIVER_NOT_NEEDED")
        for rec in adjudicated:
            if rec.get("waiver_id") in ids and rec.get("applied") is None:
                rec["applied"] = False
                rec["code"] = code
        out.append(a)
    for rec in adjudicated:
        if rec.get("applied") is None:
            rec["applied"] = False
            rec.setdefault("code", "FEAS_WAIVER_NOT_NEEDED")
    return tuple(out), adjudicated


# ---------------------------------------------------------------------------
# THE HARD GATE
# ---------------------------------------------------------------------------
def promotion_verdict(candidate: Mapping[str, Any],
                      policy: FeasibilityPolicy) -> FeasibilityResult:
    """Adjudicate ONE candidate. The only function a promoter may consult.

    It reads canonical metric records and nothing else. It never reads a
    summary field on the candidate, never reads a penalty, and has no numeric
    margin of its own -- so there is no quantity a caller could make large
    enough to buy a pass.
    """
    cid = str(candidate.get("candidate_id") or "")
    records = candidate.get("metrics")
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        return FeasibilityResult(cid, UNDETERMINED, (), (C_BAD_RECORD,))

    axes = tuple(_evaluate_axis(records, ax, policy) for ax in policy.axes)
    waivers_in = candidate.get("waivers") or []
    if not isinstance(waivers_in, Sequence) or isinstance(waivers_in, (str, bytes)):
        waivers_in = []
    axes, waiver_rows = _apply_waivers(axes, waivers_in, policy)

    statuses = {a.status for a in axes}
    if AXIS_VIOLATED in statuses:
        verdict = INFEASIBLE
    elif AXIS_UNDETERMINED in statuses:
        verdict = UNDETERMINED
    else:
        verdict = FEASIBLE

    codes: List[str] = []
    for a in axes:
        if a.status in (AXIS_VIOLATED, AXIS_UNDETERMINED, AXIS_WAIVED):
            codes.extend(f"{a.name}:{c}" for c in a.codes)
    for row in waiver_rows:
        if not row.get("applied") and row.get("code"):
            codes.append(f"waiver:{row['code']}")
    return FeasibilityResult(cid, verdict, axes,
                             tuple(dict.fromkeys(codes)) or (C_OK,),
                             tuple(waiver_rows))


def adjudicate_set(candidates: Sequence[Mapping[str, Any]],
                   policy: FeasibilityPolicy) -> List[FeasibilityResult]:
    return [promotion_verdict(c, policy) for c in candidates]


def set_exit_code(results: Sequence[FeasibilityResult]) -> int:
    """rc for a whole set. See the module docstring for why 2 beats 1 here."""
    if not results:
        return RC_UNDETERMINED
    verdicts = {r.verdict for r in results}
    if UNDETERMINED in verdicts:
        return RC_UNDETERMINED
    if INFEASIBLE in verdicts:
        return RC_FAIL
    return RC_PASS


def policy_from_document(doc: Mapping[str, Any]) -> FeasibilityPolicy:
    """Build a policy from the contract document. Unknown keys are ignored.

    Only `required_views`, `limits` and `allow_waivers` are configurable. The
    axis table is not caller-supplied: a promotion gate whose axis list came
    from the same document as the candidate could be handed a set of axes that
    happens to omit the failing one.
    """
    views = doc.get("required_views") or ()
    if not isinstance(views, Sequence) or isinstance(views, (str, bytes)):
        views = ()
    views = tuple(dict(v) for v in views if isinstance(v, Mapping))
    #: Per-axis views. A key naming no axis in the table is DROPPED and not
    #: silently honoured: `required_views_by_axis: {"drc ": [...]}` must not
    #: quietly become a policy nobody can find the effect of.
    per_axis: Dict[str, Tuple[Mapping[str, Any], ...]] = {}
    raw_per = doc.get("required_views_by_axis")
    if isinstance(raw_per, Mapping):
        known = {a.name for a in DEFAULT_AXES}
        for name, vs in raw_per.items():
            if not isinstance(name, str) or name not in known:
                continue
            if isinstance(vs, Sequence) and not isinstance(vs, (str, bytes)):
                per_axis[name] = tuple(dict(v) for v in vs
                                       if isinstance(v, Mapping))
            else:
                per_axis[name] = ()
    limits = doc.get("limits") or {}
    if not isinstance(limits, Mapping):
        limits = {}
    allow = doc.get("allow_waivers")
    #: The declaration is carried through VERBATIM and is not normalised here.
    #: `eco_requirement_state` is the one reader, and a second normalisation
    #: on the way in is how a malformed declaration becomes a well-formed one
    #: that says something nobody wrote. A key that is absent stays absent, so
    #: "no declaration" survives as None all the way to the axis.
    eco = doc.get("eco_readiness") if "eco_readiness" in doc else None
    #: A contract MAY carry the route already resolved, so a caller that has no
    #: project tree to hand can still adjudicate one. It is read verbatim for
    #: the same reason the declaration is: a second normalisation here is how a
    #: malformed route becomes a well-formed one that says something nobody
    #: wrote.
    delivery = doc.get("delivery_path")
    if not isinstance(delivery, Mapping):
        delivery = None
    return FeasibilityPolicy(
        axes=DEFAULT_AXES,
        required_views=views,
        required_views_by_axis=per_axis,
        limits={str(k): dict(v) for k, v in limits.items()
                if isinstance(v, Mapping)},
        allow_waivers=True if allow is None else bool(allow),
        eco_requirement=eco,
        delivery_path=delivery,
    )


# ---------------------------------------------------------------------------
# THE SEARCH PENALTY -- graded, one-way downstream, never consulted above
# ---------------------------------------------------------------------------
def search_penalty(result: FeasibilityResult,
                   weights: PenaltyWeights) -> Dict[str, Any]:
    """A graded, finite badness for an OPTIMISER to walk down. Not a verdict.

    It consumes an ALREADY adjudicated `FeasibilityResult`, so the dependency
    runs one way: the search can see the gate, the gate cannot see the search.
    That is what makes it impossible for a big enough win elsewhere to outweigh
    a violation in the published claim -- the published claim never reads this
    number at all.

    The returned document says so in its own payload (`promotable` is always
    None here, `basis` is SEARCH_ONLY) so that a caller who serialises it into
    a report cannot pass it off as an eligibility decision.
    """
    terms: Dict[str, float] = {}
    for a in result.axes:
        if a.status == AXIS_VIOLATED:
            terms[a.name] = float(weights.weights.get(a.name,
                                                      weights.default_weight))
        elif a.status == AXIS_UNDETERMINED:
            terms[a.name] = float(weights.undetermined_weight)
    return {
        "basis": "SEARCH_ONLY",
        "penalty": float(sum(terms.values())),
        "terms": terms,
        "promotable": None,
        "note": ("graded navigation signal; promotion is decided only by "
                 "promotion_verdict()"),
    }


# ---------------------------------------------------------------------------
# the separation, MEASURED
# ---------------------------------------------------------------------------
_GATE_ENTRY = "promotion_verdict"
_SEARCH_ENTRY = "search_penalty"
#: Names the hard gate's call closure may not mention ANYWHERE in its AST --
#: not call, not reference, not alias.
_SEARCH_ONLY_NAMES = frozenset({"search_penalty", "PenaltyWeights"})


def _module_source() -> str:
    return pathlib.Path(inspect.getsourcefile(promotion_verdict)).read_text(
        encoding="utf-8")


def _module_functions(source: Optional[str] = None) -> Dict[str, ast.AST]:
    tree = ast.parse(_module_source() if source is None else source)
    return {n.name: n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def shared_field_names(a: Any, b: Any) -> List[str]:
    """Field names two dataclasses have in common. Empty is the whole rule.

    Extracted so the detector can be exercised against a pair that DOES share a
    field: a separation check that has never been shown to fire is a check
    nobody can trust to fire.
    """
    fa = {f.name for f in dataclasses.fields(a)}
    fb = {f.name for f in dataclasses.fields(b)}
    return sorted(fa & fb)


def _closure(entry: str, funcs: Mapping[str, ast.AST]) -> List[str]:
    seen: List[str] = []
    stack = [entry]
    while stack:
        name = stack.pop()
        if name in seen or name not in funcs:
            continue
        seen.append(name)
        for node in ast.walk(funcs[name]):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                stack.append(node.func.id)
    return sorted(seen)


def separation_report(source: Optional[str] = None) -> Dict[str, Any]:
    """MEASURE, do not assert, that the two paths cannot share a threshold.

    Returns the two call closures, every name the gate closure mentions that
    belongs to the search path, and the field names of the two configuration
    dataclasses. `separated` is True only when the gate mentions nothing from
    the search path and the two configurations have no field in common.

    This is a measurement over this file's own AST, so it stays true as the
    file changes -- which is the point. A rule that lives in a docstring is a
    rule a future author breaks without being told.

    `source` overrides the text analysed. It exists so a test can feed this the
    same module with the leak PUT BACK IN and watch `separated` go false; a
    detector that has only ever been run against a clean file has not been shown
    to detect anything.
    """
    funcs = _module_functions(source)
    gate = _closure(_GATE_ENTRY, funcs)
    search = _closure(_SEARCH_ENTRY, funcs)

    leaked: List[str] = []
    for fname in gate:
        for node in ast.walk(funcs[fname]):
            if isinstance(node, ast.Name) and node.id in _SEARCH_ONLY_NAMES:
                leaked.append(f"{fname}->{node.id}")
            elif isinstance(node, ast.Attribute) and node.attr in _SEARCH_ONLY_NAMES:
                leaked.append(f"{fname}->{node.attr}")

    gate_fields = sorted(f.name for f in dataclasses.fields(FeasibilityPolicy))
    search_fields = sorted(f.name for f in dataclasses.fields(PenaltyWeights))
    shared_fields = shared_field_names(FeasibilityPolicy, PenaltyWeights)

    return {
        "gate_entry": _GATE_ENTRY,
        "search_entry": _SEARCH_ENTRY,
        "gate_closure": gate,
        "search_closure": search,
        "search_names_reachable_from_gate": sorted(set(leaked)),
        "gate_config_fields": gate_fields,
        "search_config_fields": search_fields,
        "shared_config_fields": shared_fields,
        "separated": not leaked and not shared_fields,
    }
