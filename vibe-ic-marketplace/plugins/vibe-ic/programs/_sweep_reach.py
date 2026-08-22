#!/usr/bin/env python3
"""A sweep must report how much of the guard it REACHED, not only its verdict.

WHY THIS MODULE EXISTS
======================
The plugin already answers this question for ONE gate over ONE project, twice
over:

  * ``_gate_denominator.Denominator`` makes a gate state what it examined
    (``unit`` / ``examined`` / ``considered`` / ``not_applicable_reason``), and
    REFUSES to be constructed with ``examined == 0`` and no reason.
  * ``_vacuous_exit`` routes that same conclusion onto the shipped exit-code
    convention (rc 2 = examined nothing) and onto the ``VACUOUS_PASS:``
    stdout sentinel, which are the only two signals
    ``flow_compliance_check`` actually consumes from a program.

Neither survives AGGREGATION. A sweep that invokes a guard over N targets and
is told "I examined nothing" N times can still print a summary and exit 0. The
per-item disclosure is produced, and then discarded at the layer that publishes
the number.

That is not hypothetical. A corpus sweep run as the acceptance evidence for a
guard reported ``exit 0, clean`` over 756 ordered pairs, and every one of the
756 had returned rc 2 / NOT_COMPARABLE because no pre-existing artefact carried
the digest the guard compares. The guard's decision point was never entered
once. The sweep's output, its exit code and its summary were identical to those
of a sweep that ran the guard 756 times and found nothing wrong.

MEASURED, ON THIS TREE, BY ``sweep_reach_survey.py``
====================================================
Every number below is what the shipped instrument prints on this tree today.
Re-derive it rather than trust it; that is why the instrument ships.

    python3 sweep_reach_survey.py                      -> 8 / 35   (this branch)
    python3 sweep_reach_survey.py --empty-corpus dirs  -> 25 / 29
    python3 sweep_reach_survey.py --empty-corpus none  -> 16 / 18

58 programs under ``programs/`` are sweep-shaped (a CLI taking a set of targets,
one rule applied to each, one aggregate verdict). 35 of them can be driven to a
genuine zero-reach run by a generic corpus of three valid, readable, trivial
Verilog modules — a corpus each sweep READS in full and whose contents its rule
never applies to. On pristine main the populated-corpus ratio is 7/35; this
module moves ``perc_corpus_sweep`` and makes it 8/35.

Empty the corpus and the ratio inverts — 25/29, or 16/18 with no targets at
all. NOTE that the DENOMINATOR moves too, and it has to: a sweep handed nothing
often cannot parse its own argv, so it leaves the drivable set. The two numbers
are answers to different questions and the report labels which corpus produced
it (``corpus: populated`` / ``corpus: empty:dirs``) so they cannot be quoted
against each other as if the denominator had held still.

So the existing disclosure covers "I was given nothing" and stops there. It is
the POPULATED-corpus zero-reach case, the one where the sweep really did read
every target and really did judge none of them, that is silent.

``clock_domain_reg_crossing_check`` is the measurement in one line. On the empty
corpus it exits 2. On the populated one it prints

    PASS — {'files_scanned': 3, 'multi_clock_modules_examined': 0, ...}

and exits 0. The reach counter is right there, computed and named, and the exit
code does not read it.

WHAT THIS MODULE IS
===================
The aggregation-layer counterpart of those two modules, built ON them rather
than beside them: ``as_denominator`` returns a real ``Denominator`` so a sweep's
aggregate lands in the ``denominator`` block consumers already parse, and
``exit_code`` / ``announce`` delegate to ``_vacuous_exit`` so a sweep cannot
invent a third dialect of the same conclusion.

WHAT THE RULE IS, AND — MORE IMPORTANTLY — WHAT IT IS NOT
=========================================================
The rule is TOTAL vacuity only::

    is_vacuous  <=>  reached == 0

One target out of 756 reaching the decision point is a PASS. It is a thin
sweep, and ``report()`` says exactly how thin (``reached``, ``targets``,
``coverage``, and a per-decision-point tally), but it is not a defect and this
module never fails it.

A rule demanding that a sweep prove TOTAL coverage would fire on every honest
partial sweep, and partial sweeps are legitimate — most of the sweeps measured
above are partial by construction, because most corpora contain designs the
rule genuinely does not apply to. Declared decision points that were never hit
are REPORTED with a count of 0 and never failed, for the same reason. The
target is narrower than coverage and is the whole of it: a sweep that cannot
tell you whether it reached the thing AT ALL.

A NOT-REACHED RECORD MUST CARRY A REASON
========================================
``not_reached`` requires a non-empty reason, and ``report()`` refuses to render
a zero-target sweep that has not declared why the corpus was empty. Same
doctrine as ``Denominator.__post_init__``, for the same reason: a sweep cannot
regress into silence by omission, only by writing a reason down, and a written
reason is reviewable where an absent one is not.

THIS MODULE DOES NOT DECIDE POLICY FOR ANYONE
=============================================
It computes ``exit_code`` from the caller's own ``passed`` flag and its own
``is_vacuous``, exactly as ``_vacuous_exit.exit_code`` does, and FAIL still
beats VACUOUS. Whether a given sweep should adopt it is a per-sweep question
with a per-sweep blast radius: ``clock_domain_reg_crossing_check`` above is a
registered structural gate in ``flow_compliance_check``, so flipping its rc for
single-clock designs would move every single-clock project between verdict
tiers. That is a flow-layer change and is deliberately NOT made here.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, TextIO, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _gate_denominator as _gd  # noqa: E402
import _vacuous_exit as _vx  # noqa: E402

__all__ = [
    "REACH_KEY",
    "SweepReach",
    "attach",
    "is_vacuous_report",
    "line_of",
    "reach_violations",
]

#: The summary key every disclosing sweep writes its reach report under. Named
#: once here so a consumer matches producers by construction rather than by
#: re-typing the string — the same discipline as
#: ``_gate_denominator.DENOMINATOR_KEY``.
REACH_KEY = "reach"


@dataclass
class SweepReach:
    """How much of a guard a corpus sweep actually exercised.

    ``unit`` names ONE target in the sweep's own terms ("ordered audit pair",
    "design directory with a routed DEF"). A bare integer with no unit is how a
    denominator gets attributed to the wrong field; the same trap applies here.

    ``decision_points`` optionally names the places inside the guard whose entry
    the sweep is claiming to exercise. Declaring them buys a per-point tally in
    the report; a declared point that was never hit is reported at 0 and is
    never, on its own, a failure.
    """

    unit: str
    decision_points: Tuple[str, ...] = ()
    _reached: List[str] = field(default_factory=list, repr=False)
    _not_reached: List[Tuple[str, str]] = field(default_factory=list, repr=False)
    _points: Dict[str, int] = field(default_factory=dict, repr=False)
    _empty_corpus_reason: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        if not str(self.unit).strip():
            raise ValueError(
                "SweepReach.unit is required: a reach count with no unit cannot "
                "be read back as a claim about anything")
        self.decision_points = tuple(str(p) for p in self.decision_points)
        for p in self.decision_points:
            if not p.strip():
                raise ValueError("a declared decision point cannot be empty")
            self._points.setdefault(p, 0)

    # ------------------------------------------------------------- recording
    def reached(self, target: Any, point: Optional[str] = None) -> None:
        """Record that ``target`` entered the guard's decision path.

        ``point`` must be one of the declared ``decision_points`` when any were
        declared. An undeclared name is rejected rather than silently counted
        under itself: a typo there would produce a point that is never hit and
        a hit that is never attributed, which is the failure this type exists
        to make visible, reintroduced one level down.
        """
        if point is not None:
            if self.decision_points and point not in self.decision_points:
                raise ValueError(
                    f"decision point {point!r} was not declared; declared: "
                    f"{list(self.decision_points)}")
            self._points[point] = self._points.get(point, 0) + 1
        elif self.decision_points:
            raise ValueError(
                "this sweep declared decision points "
                f"{list(self.decision_points)}, so reached() must name the one "
                "that was entered")
        self._reached.append(str(target))

    def not_reached(self, target: Any, reason: str) -> None:
        """Record that ``target`` was handled but the decision path was NOT entered.

        ``reason`` is required and must be non-empty — it is the field that
        turns "0 of 756" from a mystery into a triageable statement, and it is
        what the 756-pair sweep never published.
        """
        if not str(reason).strip():
            raise ValueError(
                f"not_reached({target!r}) needs a reason: an unexplained "
                "non-reach is indistinguishable from a target that was judged "
                "and found clean")
        self._not_reached.append((str(target), str(reason)))

    def absorb_child_rc(self, target: Any, rc: int,
                        vacuous_reason: str = "child gate returned rc 2 "
                                              "(examined nothing)") -> None:
        """Fold a per-target child invocation's ``_vacuous_exit`` rc into the sweep.

        This is the bridge the 756-pair sweep was missing: each child call had
        ALREADY disclosed rc 2, and the wrapper threw it away. rc 0 and rc 1
        both mean the child reached its subject (it passed it, or it failed it);
        only ``RC_VACUOUS`` means it did not.
        """
        if int(rc) == _vx.RC_VACUOUS:
            self.not_reached(target, vacuous_reason)
        else:
            self.reached(target, self.decision_points[0] if self.decision_points
                         else None)

    def declare_empty_corpus(self, reason: str) -> None:
        """State why the sweep was handed no targets at all.

        Required before ``report()`` will render a zero-target sweep. An empty
        corpus is a legitimate outcome (a filter matched nothing); an
        UNEXPLAINED empty corpus is the oldest form of this defect.
        """
        if not str(reason).strip():
            raise ValueError("declare_empty_corpus needs a non-empty reason")
        self._empty_corpus_reason = str(reason)

    # -------------------------------------------------------------- reading
    @property
    def targets(self) -> int:
        return len(self._reached) + len(self._not_reached)

    @property
    def n_reached(self) -> int:
        return len(self._reached)

    @property
    def is_vacuous(self) -> bool:
        """True iff the sweep judged NOTHING — including the empty-corpus case.

        Deliberately NOT "some target did not reach": a partial sweep is a
        legitimate sweep and this must not fire on one.
        """
        return self.n_reached == 0

    def reasons(self) -> Dict[str, int]:
        """Non-reach reason -> how many targets carried it, for triage."""
        out: Dict[str, int] = {}
        for _t, r in self._not_reached:
            out[r] = out.get(r, 0) + 1
        return dict(sorted(out.items()))

    def report(self) -> Dict[str, Any]:
        """The machine-readable reach block. Raises when the contract is unmet."""
        if self.targets == 0 and not self._empty_corpus_reason:
            raise ValueError(
                f"a sweep over 0 {self.unit} must say why the corpus was empty: "
                "call declare_empty_corpus(reason) — an unexplained empty "
                "corpus reads exactly like a clean one")
        d: Dict[str, Any] = {
            "unit": self.unit,
            "targets": self.targets,
            "reached": self.n_reached,
            "not_reached": len(self._not_reached),
            "coverage": f"{self.n_reached}/{self.targets}",
            "is_vacuous": self.is_vacuous,
            "not_reached_reasons": self.reasons(),
            "decision_points": dict(sorted(self._points.items())),
        }
        if self._empty_corpus_reason:
            d["empty_corpus_reason"] = self._empty_corpus_reason
        return d

    def as_denominator(self) -> _gd.Denominator:
        """The same conclusion as a ``_gate_denominator.Denominator``.

        So a sweep's aggregate is readable by every consumer that already parses
        the per-gate denominator block, instead of needing to learn a second
        shape for the same claim.
        """
        return _gd.Denominator(
            unit=self.unit,
            examined=self.n_reached,
            considered=self.targets,
            not_applicable_reason=(self._vacuous_reason() if self.is_vacuous else ""),
            details={"decision_points": dict(sorted(self._points.items()))},
        )

    def _reason_breakdown(self) -> str:
        reasons = self.reasons()
        return "; ".join(f"{r} x{n}" for r, n in
                         sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))[:3])

    def _vacuous_reason(self) -> str:
        if self.targets == 0:
            return self._empty_corpus_reason or "no targets"
        return (f"0 of {self.targets} {self.unit} reached the guard's decision "
                f"point ({self._reason_breakdown() or 'no reason recorded'})")

    def line(self) -> str:
        """One-line human disclosure, for sweeps whose verdict is stdout prose."""
        if self.is_vacuous:
            why = (self._reason_breakdown() if self.targets
                   else self._empty_corpus_reason) or "NO REASON GIVEN"
            return (f"reached the decision point on 0 of {self.targets} "
                    f"{self.unit} — {why}")
        base = f"reached the decision point on {self.n_reached} of {self.targets} {self.unit}"
        if self.decision_points:
            base += " [" + ", ".join(f"{p}={self._points.get(p, 0)}"
                                     for p in self.decision_points) + "]"
        return base

    # -------------------------------------------------------------- routing
    def exit_code(self, passed: bool) -> int:
        """Route onto the shipped rc convention via ``_vacuous_exit``.

        FAIL still beats VACUOUS: a sweep that reached nothing AND found a
        violation is reporting the violation.
        """
        return _vx.exit_code(bool(passed), self.is_vacuous)

    def announce(self, sweep: str, passed: bool = True,
                 stream: Optional[TextIO] = None) -> None:
        """Emit the rc-independent ``VACUOUS_PASS:`` line — only when vacuous AND passing.

        Gated on ``exit_code(passed)``, not on ``is_vacuous`` alone, so the
        printed sentinel and the returned rc are derived from the same pair.
        FAIL beats VACUOUS in ``_vacuous_exit.exit_code``; if the sentinel were
        gated only on vacuity, a sweep that reached nothing AND found a
        violation would print "examined nothing" beside rc 1, and a consumer
        reading the sentinel (``flow_compliance_check._stdout_signals_vacuous``,
        and ``_stdout_signals_structure_only`` which reads its sibling token on
        the FAILING path by design) could promote the run into the vacuous tier
        and silence the finding. That is the exact failure ``_vacuous_exit``'s
        "FAIL BEATS VACUOUS" section exists to prevent, so it is enforced on
        both channels rather than only on the rc.
        """
        if self.exit_code(passed) == _vx.RC_VACUOUS:
            _vx.announce_vacuous(sweep, self._vacuous_reason(), stream=stream)

    def verdict_line(self, sweep: str, passed: bool) -> str:
        """Human verdict, derived from the SAME pair ``exit_code`` routes."""
        return _vx.verdict_line(sweep, bool(passed), self.is_vacuous,
                                self._vacuous_reason())


# ----------------------------------------------------------------- consumer
def attach(summary: Dict[str, Any], reach: SweepReach) -> Dict[str, Any]:
    """Write ``reach``'s report into ``summary`` under the canonical key, in place."""
    summary[REACH_KEY] = reach.report()
    return summary


def is_vacuous_report(summary: Dict[str, Any]) -> Optional[bool]:
    """Did this published sweep reach its guard? ``None`` when it does not say.

    ``None`` is a distinct answer from ``False`` on purpose: "the sweep says it
    judged something" and "the sweep does not say" must not collapse, or a
    consumer reintroduces the defect while reading the fix for it.
    """
    d = summary.get(REACH_KEY)
    if not isinstance(d, dict):
        return None
    reached = d.get("reached")
    if not isinstance(reached, int):
        return None
    return reached == 0


def line_of(summary: Dict[str, Any]) -> str:
    """``SweepReach.line()`` for a reach block already inside ``summary``.

    Formats straight from the dict, for the reason ``_gate_denominator.line_of``
    documents: rebuilding the object would re-run validation inside a printer,
    so a non-compliant report loaded from disk would raise rather than be
    DISPLAYED as the defect it is. Returns the disclosure a summary carrying no
    reach block owes, rather than an empty string — a printer must not be able
    to render silence.
    """
    d = summary.get(REACH_KEY)
    if not isinstance(d, dict):
        return ("reach NOT STATED — this sweep does not say whether it ever "
                "entered the guard it is reporting on")
    unit = str(d.get("unit", "")).strip() or "unit NOT STATED"
    try:
        reached = int(d.get("reached"))
        targets = int(d.get("targets"))
    except (TypeError, ValueError):
        return (f"reach NOT STATED (reached={d.get('reached')!r}, "
                f"targets={d.get('targets')!r}) for {unit}")
    if reached == 0:
        reasons = d.get("not_reached_reasons")
        why = ""
        if isinstance(reasons, dict) and reasons:
            why = "; ".join(f"{r} x{n}" for r, n in
                            sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))[:3])
        elif d.get("empty_corpus_reason"):
            why = str(d["empty_corpus_reason"])
        return (f"reached the decision point on 0 of {targets} {unit} — "
                f"{why or 'NO REASON GIVEN'}")
    return f"reached the decision point on {reached} of {targets} {unit}"


def reach_violations(summary: Dict[str, Any]) -> List[str]:
    """The ways ``summary`` breaks the reach-disclosure contract. Empty = compliant.

    Used by the cross-sweep regression sweep so the contract is checked against
    every adopter's REAL output rather than restated once per adopter.
    """
    problems: List[str] = []
    d = summary.get(REACH_KEY)
    if d is None:
        return [f"summary has no {REACH_KEY!r} block — the sweep does not say "
                "whether it ever reached the guard"]
    if not isinstance(d, dict):
        return [f"{REACH_KEY!r} is {type(d).__name__}, expected an object"]
    for key in ("unit", "targets", "reached", "not_reached", "is_vacuous",
                "not_reached_reasons", "decision_points"):
        if key not in d:
            problems.append(f"{REACH_KEY}.{key} missing")
    if not str(d.get("unit", "")).strip():
        problems.append(f"{REACH_KEY}.unit is empty")
    for key in ("targets", "reached", "not_reached"):
        v = d.get(key)
        if key in d and not isinstance(v, int):
            problems.append(f"{REACH_KEY}.{key} is not an int: {v!r}")
    tg, rc_, nr = d.get("targets"), d.get("reached"), d.get("not_reached")
    if all(isinstance(v, int) for v in (tg, rc_, nr)):
        if rc_ + nr != tg:
            problems.append(
                f"{REACH_KEY}: reached({rc_}) + not_reached({nr}) != targets({tg}) "
                "— the sweep's own arithmetic does not close, so neither number "
                "can be read")
        if isinstance(d.get("is_vacuous"), bool) and d["is_vacuous"] != (rc_ == 0):
            problems.append(
                f"{REACH_KEY}.is_vacuous={d['is_vacuous']} contradicts "
                f"reached={rc_}")
        if rc_ == 0 and tg > 0 and not d.get("not_reached_reasons"):
            problems.append(
                f"{REACH_KEY}: 0 of {tg} targets reached the decision point and "
                "no reason is recorded — an unexplained zero reads exactly like "
                "a clean sweep")
        if tg == 0 and not str(d.get("empty_corpus_reason", "")).strip():
            problems.append(
                f"{REACH_KEY}: the corpus was empty and no empty_corpus_reason "
                "is recorded")
    return problems
