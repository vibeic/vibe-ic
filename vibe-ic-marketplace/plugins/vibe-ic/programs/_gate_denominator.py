#!/usr/bin/env python3
"""No PASS without a denominator (#496).

WHY THIS MODULE EXISTS — a static gate's exit code answers "did I find a
defect?".  It does not answer "did I look at anything?".  When the two are
conflated, a gate whose extraction cannot reach its subject reports exactly what
a gate auditing a clean design reports: rc 0.  Permanent cleanliness is then
indistinguishable from permanent blindness, and the blind gate is the more
dangerous of the two because it reads as coverage.

#492 measured this over the 107 tracked ``rtl`` directories under
``benchmark-data`` and found six registered structural gates reporting an
explicit zero denominator on every one of them, and two more disclosing no
denominator at all.  #496 then re-measured the six and found that **one of the
published zeroes was itself a broken probe**: ``tristate_self_rx_mask_check``
was recorded as ``inout_ports: []`` on all 107, but it actually collects 24
inout ports across 4 of them and then examines none of those, for a reason it
never printed.  The zero was real; the field naming it was the wrong field.

That is the failure this module is built to make impossible.  A denominator is
not a number a gate may optionally mention — it is a claim the gate has to
state, in a fixed shape, alongside its verdict:

  * ``unit``      — what ONE unit is, in the gate's own terms ("dispatcher
                    files carrying a command buffer", "cross-file producer /
                    consumer pairs").  A bare integer with no unit is how
                    ``inout_ports`` came to be read as the denominator of a
                    rule that is actually denominated in driven buses.
  * ``examined``  — how many units the rule was actually APPLIED to.  Not how
                    many files were globbed, not how many candidates were
                    considered: how many reached the body of the rule.
  * ``considered``— candidates seen before the gate's own preconditions
                    filtered them out.  ``considered > 0`` with
                    ``examined == 0`` is the shape that hid #496's bug, so it
                    gets its own field rather than being inferable only by
                    reading the source.
  * ``not_applicable_reason`` — REQUIRED when ``examined == 0``.  Prose naming
                    what was searched for and not found.

The requirement is enforced in ``__post_init__``: constructing a zero
denominator with no reason raises.  A gate cannot regress into silence by
omission, only by writing a reason down — and a written reason is reviewable,
which an absent one is not.

WHAT THIS MODULE DELIBERATELY DOES NOT DO — it does not decide the exit code.
Whether ``examined == 0`` means PASS, or rc 2 (NOT CHECKED), is a per-gate and
per-caller question: #492's converted gates return rc 2 for a vacuous project
because the umbrella invokes them, whereas the gates in #496 are NOT invoked by
the umbrella at all and changing their exit contract would alter behaviour for
their direct callers without fixing anything.  This module makes the zero
VISIBLE.  Acting on it is the caller's decision, and the two-condition bar in
``flow_compliance_check._STRUCTURAL_GATE_ARGV_ADAPTERS`` is where that decision
is written down.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

# The summary key every disclosing gate writes its denominator under. Named
# once here so a consumer (or a test sweeping the gate set) matches the
# producers by construction rather than by re-typing the string.
DENOMINATOR_KEY = "denominator"


@dataclass
class Denominator:
    """What a gate examined, in units it names itself.

    Raises ``ValueError`` when ``examined == 0`` and no
    ``not_applicable_reason`` is supplied — the whole point of the type.
    """

    unit: str
    examined: int
    considered: int = 0
    not_applicable_reason: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.unit).strip():
            raise ValueError(
                "Denominator.unit is required: a bare count with no unit is "
                "how a zero gets attributed to the wrong field (#496)")
        if int(self.examined) < 0 or int(self.considered) < 0:
            raise ValueError("Denominator counts cannot be negative")
        if int(self.examined) == 0 and not str(self.not_applicable_reason).strip():
            raise ValueError(
                f"a gate that examined 0 {self.unit} must say why: "
                "not_applicable_reason is required when examined == 0 (#496). "
                "A silent zero is indistinguishable from a clean result.")

    @property
    def is_vacuous(self) -> bool:
        """True when the rule was never applied to anything."""
        return int(self.examined) == 0

    def as_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "unit": self.unit,
            "examined": int(self.examined),
            "considered": int(self.considered),
            "not_applicable_reason": self.not_applicable_reason,
        }
        if self.details:
            d["details"] = self.details
        return d

    def line(self) -> str:
        """One-line human disclosure, for gates whose verdict is stdout prose.

        A machine-readable report is not enough on its own: two of the gates in
        #496 print a verdict line and nothing else, and that line is what a
        human actually reads.
        """
        if self.is_vacuous:
            base = f"examined 0 {self.unit}"
            if self.considered:
                base += f" (of {self.considered} considered)"
            return f"{base} — {self.not_applicable_reason}"
        base = f"examined {self.examined} {self.unit}"
        if self.considered and self.considered != self.examined:
            base += f" (of {self.considered} considered)"
        return base


def attach(summary: Dict[str, Any], denom: Denominator) -> Dict[str, Any]:
    """Write ``denom`` into ``summary`` under the canonical key, in place."""
    summary[DENOMINATOR_KEY] = denom.as_dict()
    return summary


def line_of(summary: Dict[str, Any]) -> str:
    """``Denominator.line()`` for the denominator already inside ``summary``.

    A gate that has ATTACHED its denominator and now wants to put the same
    sentence on stdout would otherwise have to either keep the object alive
    beside the dict or rebuild one from the dict — and rebuilding re-runs
    ``__post_init__``, so a report loaded back from disk with a zero and an
    empty reason would RAISE inside a printer rather than being displayed as
    the defect it is. Formats straight from the dict for that reason; the
    sentence itself is ``Denominator.line``'s, not a second dialect of it.

    Returns the disclosure that a summary carrying NO denominator owes, rather
    than an empty string: a printer must not be able to render silence.
    """
    d = summary.get(DENOMINATOR_KEY)
    if not isinstance(d, dict):
        return "denominator NOT STATED — this verdict does not say what it examined"
    unit = str(d.get("unit", "")).strip() or "unit NOT STATED"
    try:
        examined = int(d.get("examined"))
    except (TypeError, ValueError):
        return f"denominator NOT STATED (examined={d.get('examined')!r}) for {unit}"
    try:
        considered = int(d.get("considered", 0))
    except (TypeError, ValueError):
        considered = 0
    reason = str(d.get("not_applicable_reason", "")).strip()
    if examined == 0:
        base = f"examined 0 {unit}"
        if considered:
            base += f" (of {considered} considered)"
        return f"{base} — {reason or 'NO REASON GIVEN'}"
    base = f"examined {examined} {unit}"
    if considered and considered != examined:
        base += f" (of {considered} considered)"
    return base


def disclosure_violations(summary: Dict[str, Any]) -> List[str]:
    """Return the ways ``summary`` breaks the disclosure contract.

    Empty list = compliant. Used by the cross-gate regression sweep so the
    contract is checked against every gate's REAL output rather than restated
    per gate.
    """
    problems: List[str] = []
    d = summary.get(DENOMINATOR_KEY)
    if d is None:
        return [f"summary has no {DENOMINATOR_KEY!r} block — "
                "the verdict does not say what was examined"]
    if not isinstance(d, dict):
        return [f"{DENOMINATOR_KEY!r} is {type(d).__name__}, expected an object"]
    for key in ("unit", "examined", "considered", "not_applicable_reason"):
        if key not in d:
            problems.append(f"{DENOMINATOR_KEY}.{key} missing")
    if not str(d.get("unit", "")).strip():
        problems.append(f"{DENOMINATOR_KEY}.unit is empty")
    examined = d.get("examined")
    if not isinstance(examined, int):
        problems.append(f"{DENOMINATOR_KEY}.examined is not an int: {examined!r}")
    elif examined == 0 and not str(d.get("not_applicable_reason", "")).strip():
        problems.append(
            f"{DENOMINATOR_KEY}.examined == 0 with no not_applicable_reason — "
            "a PASS over nothing, indistinguishable from a clean result")
    return problems
