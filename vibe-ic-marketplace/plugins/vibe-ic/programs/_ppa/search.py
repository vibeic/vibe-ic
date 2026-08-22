#!/usr/bin/env python3
"""`_ppa/search.py` — candidate lifecycle, budget, and multi-fidelity.

Spec §11 (Search Layer), §11.1 (candidate lifecycle), §11.2 (multi-fidelity),
§11.6 (budget). Interface contract: `docs/PPA_INTERFACES.md`.

WHAT THIS MODULE OWNS, AND WHAT IT DELIBERATELY DOES NOT
========================================================
It owns the answer to three questions and no others:

    which points get proposed        (deterministically, from a space + a seed)
    which of them actually run       (budget, and what the budget bought)
    which results may be COMPARED    (scope, eligibility, and why each exclusion)

It does NOT decide which levers exist -- `crosslayer_search_space.py` answers
that and this module consumes its artefact. It does NOT compute the Pareto
frontier -- `_ppa/pareto.py` owns that. It does NOT decide whether a candidate
is feasible -- `_ppa/feasibility.py` owns that, and until that module lands this
one calls a stub whose only possible answer is UNDETERMINED (see below, it is
the single most important line in this file).

BUDGET IS AN INPUT, NOT AN ASSUMPTION
=====================================
Somebody downloads this plugin and runs it on one laptop; somebody else has a
hundred machines. A search layer that needs fifty trials before it can say
anything is useless to the first person and says so only after wasting their
evening. So `Budget()` with no arguments is `max_trials=1`, and one trial is a
complete, honest bundle: one candidate, its metrics, its cost, its eligibility,
and a report that states plainly that the budget bought one point.

A frontier of one point is a valid frontier. What is NOT valid is a frontier of
one point that does not say the budget was one.

PUBLISH EVERY TRIAL, NOT THE BEST ONE
=====================================
`Ledger.publish()` emits every candidate that was ever proposed, in every
terminal state, including the ones that never ran because the budget ended
(`BUDGET_EXHAUSTED`) and the ones that were refused before scheduling
(`REJECTED_SPACE`). Reporting only the winner is how a search makes a lucky
draw look like a method, and it is why trial COUNT alone cannot compare two
tuners: without CPU-hours and wall time beside it, "50 trials" describes an
unknown amount of machine.

TWO SEMANTIC TRAPS INHERITED FROM THE OPEN TUNERS
=================================================
1. ORFS's `step` is a Ray Tune TRAINING ITERATION. It counts how many times the
   tuner's objective was reported, and it has no relationship whatsoever to how
   far through the flow a trial got. A trial that died in floorplan and a trial
   that finished routing can carry the same `step`. This module therefore
   records `completed_stage`, an explicit member of `FIDELITY_LADDER`, and
   `set_completed_stage` REFUSES an integer outright -- because the plausible
   wrong implementation is `completed_stage = row["step"]`, it would typecheck,
   and it would silently make every fidelity comparison meaningless.

2. ORFS's `num_drc` counts DETAILED-ROUTE DRC only. It is not sign-off DRC, it
   says nothing about LVS, antenna, IR, EM or equivalence, and using it as the
   anti-cheating term lets a candidate that never ran sign-off look feasible.
   The eligibility term here is the feasibility VECTOR from the feasibility
   lane, and `FEASIBILITY_TERMS` names every component so a partial answer
   cannot be read as a whole one.

THE LINE THAT MATTERS MOST
==========================
`stub_feasibility` returns UNDETERMINED. It does not return ELIGIBLE.

A missing feasibility lane must never manufacture eligibility, because
"nothing said this candidate was infeasible" and "this candidate was checked
and is feasible" are opposite facts. Under the stub the frontier is EMPTY and
the report says why -- which is the correct output of a search whose feasibility
gate has not been wired yet, and is the same rule as: a check that cannot see
its input must say so, not report clean.

chip-AGNOSTIC: nothing here reasons about any IC, vendor, SKU, process or PDK.
"""
from __future__ import annotations

import importlib
import pathlib
import random
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from . import canonical_json as cj

SCHEMA = "vibeic.ppa.search_manifest.v1"

# ---------------------------------------------------------------------------
# §11.2 the fidelity ladder
# ---------------------------------------------------------------------------
# An ORDERED ladder, cheapest first. `completed_stage` is the highest rung a
# trial actually reached. The vocabulary is the one already spoken in this
# tree's programs (`synth`, `floorplan`, `cts`, `global_route`,
# `detailed_route`) plus the contract's own top rung, `post_route_extracted`,
# which is the scope the canonical metric record example carries.
FIDELITY_LADDER: Tuple[str, ...] = (
    "synth",
    "floorplan",
    "place",
    "cts",
    "global_route",
    "detailed_route",
    "post_route_extracted",
)

# The rung that costs a full place-and-route. `max_full_pnr_trials` is a
# SEPARATE budget line from `max_trials` precisely because a search that ran 50
# synthesis trials and 2 routed ones has not done the same work as one that
# routed 50, and a single "trials" number cannot tell those apart.
FULL_PNR_STAGE = "post_route_extracted"
FULL_PNR_STAGES: Tuple[str, ...] = ("detailed_route", "post_route_extracted")


def stage_rank(stage: Optional[str]) -> int:
    """Position on the ladder; -1 for "never ran / not a ladder member".

    -1 is deliberately not 0: `synth` is a real rung and "nothing completed"
    must not sort as if it were the cheapest success.
    """
    if stage is None:
        return -1
    try:
        return FIDELITY_LADDER.index(stage)
    except ValueError:
        return -1


def is_full_pnr(stage: Optional[str]) -> bool:
    return stage in FULL_PNR_STAGES


# ---------------------------------------------------------------------------
# §11.1 the candidate lifecycle
# ---------------------------------------------------------------------------
ST_PROPOSED = "PROPOSED"
ST_REJECTED_SPACE = "REJECTED_SPACE"
ST_DEDUPLICATED = "DEDUPLICATED"
ST_BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
ST_RUNNING = "RUNNING"
ST_COMPLETED = "COMPLETED"
ST_FAILED = "FAILED"
ST_TIMEOUT = "TIMEOUT"

ALL_STATES: Tuple[str, ...] = (
    ST_PROPOSED, ST_REJECTED_SPACE, ST_DEDUPLICATED, ST_BUDGET_EXHAUSTED,
    ST_RUNNING, ST_COMPLETED, ST_FAILED, ST_TIMEOUT,
)

# A published manifest may contain no candidate in a non-terminal state: a
# search that reports a trial as still RUNNING is reporting an unfinished
# measurement as a result.
TERMINAL_STATES: Tuple[str, ...] = (
    ST_REJECTED_SPACE, ST_DEDUPLICATED, ST_BUDGET_EXHAUSTED,
    ST_COMPLETED, ST_FAILED, ST_TIMEOUT,
)

# States that consumed machine time. `REJECTED_SPACE`, `DEDUPLICATED` and
# `BUDGET_EXHAUSTED` did not run, so they cost nothing and must not be counted
# as trials -- counting them would let a search inflate its trial number
# without spending a second of CPU.
RAN_STATES: Tuple[str, ...] = (ST_COMPLETED, ST_FAILED, ST_TIMEOUT)


# ---------------------------------------------------------------------------
# feasibility -- the interface, and the stub that refuses to guess
# ---------------------------------------------------------------------------
FEAS_ELIGIBLE = "ELIGIBLE"
FEAS_INELIGIBLE = "INELIGIBLE"
FEAS_UNDETERMINED = "UNDETERMINED"

# `docs/PPA_INTERFACES.md` §4: "_ppa/feasibility.py  the hard gate:
# setup/hold/DRV/DRC/LVS/ANT/IR/EM/equivalence". These are the components, named
# individually so that a verdict built from a SUBSET is visibly a subset. This
# is the replacement for ORFS's `num_drc`: `drc` alone is one of the terms.
#
# `eco_readiness` joined them because a place-and-route search that deleted a
# design's whole spare-cell population scored BETTER on area and power and
# nothing in this vector said so. It is the one term whose APPLICABILITY the
# design declares, so on a design that declares no requirement it reads
# NOT_APPLICABLE -- which `audit_manifest` accepts, exactly as it accepts a
# NOT_APPLICABLE on any other term.
FEASIBILITY_TERMS: Tuple[str, ...] = (
    "setup", "hold", "drv", "drc", "lvs", "antenna", "ir", "em", "equivalence",
    "eco_readiness",
)


@dataclass(frozen=True)
class FeasibilityVerdict:
    """What the feasibility lane returns. Frozen: a verdict is not editable."""
    verdict: str
    reason: str
    terms: Dict[str, str] = field(default_factory=dict)

    def as_record(self) -> Dict[str, Any]:
        return {"verdict": self.verdict, "reason": self.reason,
                "terms": dict(self.terms)}


#: The module the stub stands in for. Named ONCE, because two places naming it
#: is how one of them goes stale -- which is exactly the defect below.
FEASIBILITY_MODULE_REL = "_ppa/feasibility.py"

#: The phrase a stub uses to name a condition it claims about the tree. It is a
#: constant so `audit_manifest` can look for the same words the stub writes,
#: rather than two lanes agreeing by eye.
UNLANDED_CLAIM_PHRASE = "has not landed"

#: Manifest audit code for a published reason that names a condition the tree
#: contradicts. See `unlanded_claims_contradicted_by_tree`.
AUDIT_STUB_REASON_FALSE = "STUB_REASON_CONTRADICTED_BY_TREE"

#: Every `<path>.py has not landed` claim, as it appears in a published string.
_UNLANDED_CLAIM_RE = re.compile(
    r"(?P<path>[A-Za-z0-9_][A-Za-z0-9_./-]*\.py)\s+" + UNLANDED_CLAIM_PHRASE)


def _programs_dir() -> pathlib.Path:
    """The `programs/` directory this module ships in. Not the launch cwd.

    Resolved from `__file__` so the answer describes the TREE, which is what a
    claim about a module having landed is about.
    """
    return pathlib.Path(__file__).resolve().parent.parent


def feasibility_module_has_landed() -> bool:
    """Is `_ppa/feasibility.py` present and importable ON THIS TREE, right now?

    MEASURED, not remembered. This is the whole of the F-12 fix: the stub used
    to state, as a hard-coded sentence published into every manifest, that this
    module "has not landed". It landed at v1.11.26 and the sentence went on
    being published for every candidate of every run. A hard-wired excuse that
    outlives its cause is a false record, and the way to make that impossible
    is to require the excuse to CHECK its own condition at the moment it speaks.

    Both halves are asked because they can disagree: a file can be present and
    unimportable (a syntax error in a half-landed edit), and a module can be
    importable from somewhere other than this tree. A claim about "landed"
    means both, so both are required.
    """
    if not (_programs_dir() / FEASIBILITY_MODULE_REL).is_file():
        return False
    try:
        importlib.import_module(".feasibility", __package__ or "_ppa")
    except Exception:                                   # pragma: no cover
        return False
    return True


def unlanded_claims_contradicted_by_tree(text: Any) -> List[str]:
    """Every `<path>.py has not landed` claim in `text` that this tree refutes.

    The generator side of F-12 is fixed by `stub_feasibility` below, which can
    no longer produce a false one. This is the AUDIT side, and it is the half
    that applies to a manifest somebody else published: a record asserting that
    a module of this plugin has not landed is checkable against the plugin, and
    a reader holding the plugin should not have to check it by hand.

    CONSERVATIVE ON PURPOSE. A path that does not resolve to a file here yields
    NOTHING -- not a finding, and not a pass either; it simply is not evidence.
    Only a claim the tree positively CONTRADICTS -- the named file is right
    there -- is returned. That way this can never redden an honest manifest
    published against a tree where the claim was true.
    """
    if not isinstance(text, str):
        return []
    out: List[str] = []
    for m in _UNLANDED_CLAIM_RE.finditer(text):
        rel = m.group("path")
        if (_programs_dir() / rel).is_file():
            out.append(rel)
    return list(dict.fromkeys(out))


def stub_feasibility(candidate: "Candidate") -> FeasibilityVerdict:
    """The stand-in when no feasibility function is supplied. UNDETERMINED.

    It answers UNDETERMINED for every candidate, including a candidate that
    completed a full place-and-route with beautiful numbers, and that is the
    entire point: this function has not looked at setup, hold, DRV, DRC, LVS,
    antenna, IR, EM or equivalence, so it has no basis to call anything
    eligible. Returning ELIGIBLE here would be a program asserting silicon it
    never examined.

    Every term is explicitly NOT_CHECKED rather than absent, so a reader can
    see there are nine of them and that none was answered.

    THE REASON IS COMPUTED, NEVER REMEMBERED (F-12)
    ==============================================
    A stub that names a condition -- "X has not landed" -- must CHECK that
    condition at the moment it speaks, or it must not name one. The previous
    text was a literal, and it was published verbatim into sixty manifests
    three commits after the module it named had landed. So the two possible
    worlds are distinguished HERE, on every call:

        module absent    the stub is standing in for something that is
                         genuinely not there, and says so
        module present   the stub is standing in for a lane this RUN did not
                         consult, which is a fact about the invocation and not
                         about the tree, and it says THAT instead

    Both sentences are true when they are written. Neither can rot, because
    neither is stored.
    """
    if feasibility_module_has_landed():
        reason = (
            "no feasibility function was supplied to this search: "
            f"{FEASIBILITY_MODULE_REL} IS present on this tree but this run "
            "did not consult it, so no setup/hold/DRV/DRC/LVS/antenna/IR/EM/"
            "equivalence evidence was read for this candidate. Re-run with "
            "the feasibility lane wired to adjudicate it.")
    else:
        reason = (
            f"feasibility lane not wired: {FEASIBILITY_MODULE_REL} "
            f"{UNLANDED_CLAIM_PHRASE} on the tree that produced this record, "
            "so no setup/hold/DRV/DRC/LVS/antenna/IR/EM/equivalence evidence "
            "was read for this candidate")
    return FeasibilityVerdict(
        verdict=FEAS_UNDETERMINED,
        reason=reason,
        terms={t: "NOT_CHECKED" for t in FEASIBILITY_TERMS},
    )


FeasibilityFn = Callable[["Candidate"], FeasibilityVerdict]


# ---------------------------------------------------------------------------
# §11.6 budget
# ---------------------------------------------------------------------------
FAILED_COUNTS = "COUNTS_AGAINST_BUDGET"
FAILED_RETRY_ONCE = "RETRY_ONCE_THEN_COUNTS"
FAILED_FREE = "FREE"
FAILED_TRIAL_POLICIES: Tuple[str, ...] = (
    FAILED_COUNTS, FAILED_RETRY_ONCE, FAILED_FREE)

CACHE_REUSE = "REUSE"
CACHE_IGNORE = "IGNORE"
CACHE_REFUSE = "REFUSE"
CACHE_POLICIES: Tuple[str, ...] = (CACHE_REUSE, CACHE_IGNORE, CACHE_REFUSE)


@dataclass
class Budget:
    """Every dimension a trial count cannot express, declared as an input.

    `max_trials` defaults to 1. That default is a decision, not laziness: the
    smallest useful budget must be the one you get for free, so that a first
    run on one machine produces a real bundle instead of an estimate of how
    long a real bundle would take.

    `failed_trial_policy` is declared rather than assumed because both answers
    are defensible and they give different numbers: a crashed trial DID consume
    wall time, so charging it is honest accounting; retrying once is also
    honest if the retry is disclosed. What is dishonest is not saying which.

    `cache_policy` matters for the same reason. A cache hit costs no CPU, so a
    run with many hits reports low CPU-hours; unless the manifest says how many
    trials were hits, those CPU-hours describe a different amount of work than
    the reader thinks.
    """
    max_trials: int = 1
    max_full_pnr_trials: int = 1
    max_cpu_hours: Optional[float] = None
    max_wall_seconds: Optional[float] = None
    concurrency: int = 1
    memory_limit_mb: Optional[int] = None
    per_trial_timeout_s: Optional[float] = None
    failed_trial_policy: str = FAILED_COUNTS
    seed: int = 0
    cache_policy: str = CACHE_IGNORE

    def problems(self) -> List[str]:
        """Every way this budget is not a budget. Empty list = usable."""
        out: List[str] = []
        if self.max_trials < 1:
            out.append(f"max_trials must be >= 1, got {self.max_trials}: a "
                       "search that may run zero trials cannot produce a "
                       "bundle, and would report an empty one as a result")
        if self.max_full_pnr_trials < 0:
            out.append("max_full_pnr_trials must be >= 0, got "
                       f"{self.max_full_pnr_trials}")
        if self.max_full_pnr_trials > self.max_trials:
            out.append(
                f"max_full_pnr_trials ({self.max_full_pnr_trials}) exceeds "
                f"max_trials ({self.max_trials}): the full-PnR line is a "
                "SUBSET of the trial line, not an additional allowance")
        if self.concurrency < 1:
            out.append(f"concurrency must be >= 1, got {self.concurrency}")
        for name in ("max_cpu_hours", "max_wall_seconds",
                     "per_trial_timeout_s"):
            v = getattr(self, name)
            if v is not None and v <= 0:
                out.append(f"{name} must be > 0 when declared, got {v}")
        if self.memory_limit_mb is not None and self.memory_limit_mb <= 0:
            out.append("memory_limit_mb must be > 0 when declared, got "
                       f"{self.memory_limit_mb}")
        if self.failed_trial_policy not in FAILED_TRIAL_POLICIES:
            out.append(
                f"failed_trial_policy {self.failed_trial_policy!r} is not one "
                f"of {list(FAILED_TRIAL_POLICIES)}; it may not be left "
                "implicit because the two defensible answers give different "
                "trial counts")
        if self.cache_policy not in CACHE_POLICIES:
            out.append(f"cache_policy {self.cache_policy!r} is not one of "
                       f"{list(CACHE_POLICIES)}")
        return out

    def as_record(self) -> Dict[str, Any]:
        """The budget as it appears in the manifest.

        Every field is present, including the ones that are None. A budget that
        omits `max_cpu_hours` because it was not set is indistinguishable from
        one that omits it because the writer forgot; `null` says "declared, and
        unbounded", which is a different and readable fact.
        """
        return {
            "max_trials": self.max_trials,
            "max_full_pnr_trials": self.max_full_pnr_trials,
            "max_cpu_hours": self.max_cpu_hours,
            "max_wall_seconds": self.max_wall_seconds,
            "concurrency": self.concurrency,
            "memory_limit_mb": self.memory_limit_mb,
            "per_trial_timeout_s": self.per_trial_timeout_s,
            "failed_trial_policy": self.failed_trial_policy,
            "seed": self.seed,
            "cache_policy": self.cache_policy,
        }


# ---------------------------------------------------------------------------
# the candidate
# ---------------------------------------------------------------------------
@dataclass
class Candidate:
    """One point in the space, and everything that happened to it.

    `identity` is the sha256 of (space identity, knobs) through the ONE
    serializer, so the same point proposed by two runs against the same space
    is the same identity -- which is what makes a cache hit checkable rather
    than asserted.
    """
    knobs: Dict[str, Any]
    space_digest: str = ""
    state: str = ST_PROPOSED
    completed_stage: Optional[str] = None
    feasibility: FeasibilityVerdict = field(
        default_factory=lambda: FeasibilityVerdict(
            FEAS_UNDETERMINED, "not evaluated", {}))
    metrics: List[Dict[str, Any]] = field(default_factory=list)
    cpu_seconds: Optional[float] = None
    wall_seconds: Optional[float] = None
    peak_rss_mb: Optional[float] = None
    cache_hit: bool = False
    note: str = ""

    @property
    def identity(self) -> str:
        return cj.digest_of({"space": self.space_digest,
                             "knobs": self.knobs})

    def set_completed_stage(self, stage: Any) -> None:
        """Record how far the trial actually got. REFUSES a tuner iteration.

        The wrong implementation this guard exists to stop is one line long:

            candidate.set_completed_stage(orfs_row["step"])

        ORFS's `step` is a Ray Tune training iteration. It is an integer, it
        looks like progress, and it is not progress -- a trial that died in
        floorplan can carry the same `step` as one that finished routing. A
        `completed_stage` populated from it would make every fidelity
        comparison in the manifest meaningless while looking perfectly typed,
        so an int is rejected here by TYPE, before it can be stringified into
        something that resembles a stage name.
        """
        if isinstance(stage, bool) or isinstance(stage, int):
            raise TypeError(
                "completed_stage must be a member of FIDELITY_LADDER, not an "
                f"integer ({stage!r}). A tuner's iteration counter (ORFS/Ray "
                "Tune `step`) is NOT flow-stage progress: the same value can "
                "mean 'died in floorplan' and 'finished routing'. Map the "
                "tool's real stage instead, or leave it None.")
        if stage is not None and stage not in FIDELITY_LADDER:
            raise ValueError(
                f"completed_stage {stage!r} is not on the ladder "
                f"{list(FIDELITY_LADDER)}")
        self.completed_stage = stage

    def measured_metrics(self) -> List[Dict[str, Any]]:
        """Only `MEASURED` records may enter a numeric comparison (contract §2)."""
        return [m for m in self.metrics if m.get("status") == "MEASURED"]

    def as_record(self) -> Dict[str, Any]:
        return {
            "identity": self.identity,
            "knobs": dict(self.knobs),
            "state": self.state,
            "completed_stage": self.completed_stage,
            "feasibility": self.feasibility.as_record(),
            "metrics": list(self.metrics),
            "cost": {"cpu_seconds": self.cpu_seconds,
                     "wall_seconds": self.wall_seconds,
                     "peak_rss_mb": self.peak_rss_mb},
            "cache_hit": self.cache_hit,
            "note": self.note,
        }


# ---------------------------------------------------------------------------
# the space -> concrete values, WITHOUT inventing any
# ---------------------------------------------------------------------------
NOT_ENUMERABLE = "NOT_ENUMERABLE"


def _tokens_from_domain(domain: str) -> Optional[List[str]]:
    """Pipe-separated categorical values, or None when the prose is not a list.

    `crosslayer_search_space.json` states each lever's `domain` as HUMAN PROSE
    -- measured, on this tree: `"binary | gray | one-hot | johnson"` next to
    `"additional pipeline stages on the output path, 0..N"` next to
    `"AREA 0..3 | DELAY 0..4"`. The first is mechanically a value list. The
    other two are not: `N` is unbound, and `AREA 0..3` names a FAMILY of four
    values, not one.

    So a token containing a range marker disqualifies the whole domain. The
    alternative -- treating `"AREA 0..3"` as a single literal knob value --
    would search two points while reporting that it searched a nine-preset
    space, and nothing downstream could see the difference.

    Returning None is not a failure. It means "this lever needs explicit
    values", and the caller records the lever as NOT_ENUMERABLE rather than
    dropping it, because a lever that silently vanished from a search is
    indistinguishable from a lever that was never searchable.
    """
    if not isinstance(domain, str) or "|" not in domain:
        return None
    toks = [t.strip() for t in domain.split("|")]
    if any(not t for t in toks):
        return None
    if any(".." in t or "…" in t for t in toks):
        return None
    return toks


def values_from_space(space: Dict[str, Any],
                      explicit: Optional[Dict[str, Sequence[Any]]] = None,
                      ) -> Tuple[Dict[str, List[Any]], List[Dict[str, str]]]:
    """(searchable values per lever, one note per lever that could not be read).

    Only levers the space ADMITTED are considered. An explicit value list
    always wins over the prose domain, because a caller who states the values
    has supplied the fact the artefact only described.
    """
    explicit = dict(explicit or {})
    values: Dict[str, List[Any]] = {}
    notes: List[Dict[str, str]] = []
    for lever in space.get("levers", []):
        if not isinstance(lever, dict):
            continue
        name = lever.get("lever")
        if not name or not lever.get("admitted"):
            continue
        if name in explicit:
            vs = list(explicit[name])
            if not vs:
                notes.append({"lever": name, "status": NOT_ENUMERABLE,
                              "reason": "explicit value list was empty"})
                continue
            values[name] = vs
            continue
        toks = _tokens_from_domain(str(lever.get("domain", "")))
        if toks is None:
            notes.append({
                "lever": name, "status": NOT_ENUMERABLE,
                "reason": ("the space states this lever's domain as prose "
                           f"({lever.get('domain')!r}); it is admitted but "
                           "carries no mechanically enumerable value list, so "
                           "this search did NOT vary it. Supply explicit "
                           "values to search it.")})
            continue
        values[name] = toks
    for name in sorted(explicit):
        if name not in values and not any(n["lever"] == name for n in notes):
            notes.append({
                "lever": name, "status": "NOT_ADMITTED",
                "reason": ("explicit values were supplied for a lever the "
                           "space did not admit; the space decides what may "
                           "be searched and this one was not varied")})
    return values, notes


# ---------------------------------------------------------------------------
# proposing candidates -- deterministic from (space, values, seed)
# ---------------------------------------------------------------------------
def propose(values: Dict[str, List[Any]], budget: Budget, space_digest: str,
            ) -> List[Candidate]:
    """The candidate sequence for this budget. Same inputs -> same sequence.

    The BASELINE is always first and is always the lever set's first value on
    every axis. A search whose first trial is random has no reference point,
    and its "improvement" is measured against whichever draw it happened to
    make.

    Beyond the baseline the order is a seeded shuffle of the remaining grid.
    Seeded, so a re-run reproduces it; shuffled rather than lexicographic, so a
    budget that truncates the list does not systematically get one corner of
    the space. `random.Random(seed)` is used rather than the module-level
    `random`, so a caller elsewhere in the process cannot move this sequence.

    The list is NOT truncated to the budget here. Every proposed point is
    returned and the scheduler marks the ones it could not afford as
    BUDGET_EXHAUSTED, because a point that was dropped before publication and a
    point that was never proposed look identical in the artefact.
    """
    if not values:
        return [Candidate(knobs={}, space_digest=space_digest,
                          note="no searchable lever: the single candidate is "
                               "the baseline configuration")]
    axes = sorted(values)
    grid: List[Dict[str, Any]] = [{}]
    for axis in axes:
        grid = [dict(pt, **{axis: v}) for pt in grid for v in values[axis]]
    baseline = {a: values[a][0] for a in axes}
    rest = [p for p in grid if p != baseline]
    random.Random(budget.seed).shuffle(rest)
    return [Candidate(knobs=p, space_digest=space_digest, note=note)
            for p, note in [(baseline, "baseline")] + [(r, "") for r in rest]]


# ---------------------------------------------------------------------------
# the ledger -- budget accounting and what the budget bought
# ---------------------------------------------------------------------------
class Ledger:
    """Every candidate that was ever proposed, and what happened to it.

    The class exists so that "how many trials ran" is COMPUTED from the states
    rather than incremented by whoever remembered to. A counter and a list can
    disagree; a derived count cannot.
    """

    def __init__(self, budget: Budget, space_digest: str = "") -> None:
        self.budget = budget
        self.space_digest = space_digest
        self.candidates: List[Candidate] = []

    # -- accounting ---------------------------------------------------------
    def ran(self) -> List[Candidate]:
        return [c for c in self.candidates if c.state in RAN_STATES]

    def trials_charged(self) -> int:
        """Trials counted against `max_trials`, per the declared failed policy.

        A cache hit is not charged: it consumed no machine. It is still
        PUBLISHED as a trial with `cache_hit: true`, so the reader can see the
        gap between "trials in the ledger" and "trials that cost something".
        """
        n = 0
        for c in self.ran():
            if c.cache_hit:
                continue
            if c.state == ST_FAILED and \
                    self.budget.failed_trial_policy == FAILED_FREE:
                continue
            n += 1
        return n

    def full_pnr_trials(self) -> int:
        return sum(1 for c in self.ran() if is_full_pnr(c.completed_stage))

    def cache_hits(self) -> int:
        return sum(1 for c in self.ran() if c.cache_hit)

    def cpu_hours(self) -> Optional[float]:
        """Total CPU-hours, or None when no trial reported CPU time.

        None, never 0.0. A search that did not instrument CPU time and a search
        that used no CPU are opposite facts, and `0.0` reads as the second.
        Contract §2: no numeric sentinels.
        """
        vals = [c.cpu_seconds for c in self.ran() if c.cpu_seconds is not None]
        if not vals:
            return None
        return sum(vals) / 3600.0

    def wall_seconds(self) -> Optional[float]:
        """Wall time, aggregated honestly for the declared concurrency.

        At concurrency 1 the trials were serial, so wall time is their sum. At
        concurrency > 1 this ledger does not hold start/end timestamps, so it
        cannot reconstruct the true elapsed span -- and it says None rather
        than dividing by the concurrency, which would be a MODEL of the wall
        time presented as a measurement of it.
        """
        vals = [c.wall_seconds for c in self.ran() if c.wall_seconds is not None]
        if not vals:
            return None
        if self.budget.concurrency != 1:
            return None
        return sum(vals)

    def budget_spent(self) -> Dict[str, Any]:
        return {
            "trials_proposed": len(self.candidates),
            "trials_ran": len(self.ran()),
            "trials_charged": self.trials_charged(),
            "full_pnr_trials": self.full_pnr_trials(),
            "cache_hits": self.cache_hits(),
            "cpu_hours": self.cpu_hours(),
            "wall_seconds": self.wall_seconds(),
            "states": {s: sum(1 for c in self.candidates if c.state == s)
                       for s in ALL_STATES},
        }

    # -- scheduling ---------------------------------------------------------
    def admit(self, proposed: Iterable[Candidate]) -> None:
        """Take the proposed sequence and assign every point a state.

        Duplicates by identity become DEDUPLICATED; points past the budget
        become BUDGET_EXHAUSTED. Both are kept in the ledger. Nothing is
        dropped, ever -- the manifest audit checks exactly that.
        """
        seen: Dict[str, int] = {}
        charged = 0
        for cand in proposed:
            ident = cand.identity
            if ident in seen:
                cand.state = ST_DEDUPLICATED
                cand.note = (cand.note or "") + \
                    (" " if cand.note else "") + \
                    f"identical to candidate #{seen[ident]}"
                self.candidates.append(cand)
                continue
            seen[ident] = len(self.candidates)
            if charged >= self.budget.max_trials:
                cand.state = ST_BUDGET_EXHAUSTED
                cand.note = (cand.note or "") + \
                    (" " if cand.note else "") + \
                    (f"not started: max_trials={self.budget.max_trials} was "
                     "already spent")
                self.candidates.append(cand)
                continue
            charged += 1
            self.candidates.append(cand)

    def evaluate_feasibility(self, fn: Optional[FeasibilityFn] = None) -> None:
        """Attach a feasibility verdict to every trial that RAN.

        Trials that never ran keep UNDETERMINED with their own reason: there is
        no artefact to check, which is not the same as a check that came back
        clean.
        """
        fn = fn or stub_feasibility
        for c in self.candidates:
            if c.state in RAN_STATES:
                c.feasibility = fn(c)
            else:
                c.feasibility = FeasibilityVerdict(
                    FEAS_UNDETERMINED,
                    f"candidate is {c.state}: it produced no artefact, so no "
                    "feasibility evidence exists to read",
                    {t: "NOT_CHECKED" for t in FEASIBILITY_TERMS})


# ---------------------------------------------------------------------------
# the frontier INPUT -- which results may legitimately be compared
# ---------------------------------------------------------------------------
EXCL_NOT_ELIGIBLE = "NOT_ELIGIBLE"
EXCL_UNDETERMINED = "FEASIBILITY_UNDETERMINED"
EXCL_SCOPE_MISMATCH = "SCOPE_MISMATCH"
EXCL_DID_NOT_RUN = "DID_NOT_RUN"
EXCL_NO_MEASURED_METRIC = "NO_MEASURED_METRIC"


def frontier_input(ledger: Ledger, frontier_stage: Optional[str] = None,
                   ) -> Dict[str, Any]:
    """The comparable set, plus a NAMED reason for every candidate left out.

    `_ppa/pareto.py` computes the frontier; this decides what it is allowed to
    see, and that is the harder half. Three rules, each of which is a way a
    published frontier has been wrong:

    ELIGIBILITY. Only `ELIGIBLE` enters. `UNDETERMINED` is excluded with its own
    distinct code, never folded in with `INELIGIBLE` -- "we checked and it
    fails" and "we never checked" are different findings and the reader must be
    able to tell which one emptied the frontier.

    SCOPE. Contract §2: two numbers are comparable only if their scope matches.
    A synthesis-stage area and a post-route area are different metrics, so a
    frontier mixing rungs is not a frontier, it is a category error with a
    plot. The stage is therefore FIXED for the whole frontier -- by default the
    highest rung any eligible candidate actually reached -- and candidates at
    other rungs are excluded as SCOPE_MISMATCH rather than silently rescaled.

    EVIDENCE. A candidate with no `MEASURED` metric contributes no coordinate.
    It is excluded rather than plotted at the origin.

    An empty `included` list is a legitimate and complete answer. It means the
    budget bought no comparable point, and the caller reports that instead of
    reporting a winner.
    """
    ran = ledger.ran()
    eligible = [c for c in ran if c.feasibility.verdict == FEAS_ELIGIBLE]
    if frontier_stage is None:
        ranks = [stage_rank(c.completed_stage) for c in eligible]
        best = max(ranks) if ranks else -1
        frontier_stage = FIDELITY_LADDER[best] if best >= 0 else None

    included: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []
    for c in ledger.candidates:
        if c.state not in RAN_STATES:
            excluded.append({"identity": c.identity, "code": EXCL_DID_NOT_RUN,
                             "detail": f"state={c.state}"})
            continue
        v = c.feasibility.verdict
        if v == FEAS_UNDETERMINED:
            excluded.append({"identity": c.identity,
                             "code": EXCL_UNDETERMINED,
                             "detail": c.feasibility.reason})
            continue
        if v != FEAS_ELIGIBLE:
            excluded.append({"identity": c.identity, "code": EXCL_NOT_ELIGIBLE,
                             "detail": c.feasibility.reason})
            continue
        if frontier_stage is None or c.completed_stage != frontier_stage:
            excluded.append({
                "identity": c.identity, "code": EXCL_SCOPE_MISMATCH,
                "detail": (f"completed_stage={c.completed_stage!r} but the "
                           f"frontier scope is {frontier_stage!r}; metrics at "
                           "different stages are different metrics")})
            continue
        if not c.measured_metrics():
            excluded.append({"identity": c.identity,
                             "code": EXCL_NO_MEASURED_METRIC,
                             "detail": "no metric record has status MEASURED"})
            continue
        included.append({"identity": c.identity, "knobs": dict(c.knobs),
                         "completed_stage": c.completed_stage,
                         "metrics": c.measured_metrics()})
    return {
        "frontier_stage": frontier_stage,
        "included": included,
        "excluded": excluded,
        "included_count": len(included),
        "excluded_count": len(excluded),
    }


# ---------------------------------------------------------------------------
# the manifest
# ---------------------------------------------------------------------------
def build_manifest(ledger: Ledger, space_digest: str,
                   lever_notes: Optional[List[Dict[str, str]]] = None,
                   frontier_stage: Optional[str] = None,
                   toolchain: Optional[Dict[str, Any]] = None,
                   ) -> Dict[str, Any]:
    """The published search bundle. Complete at budget 1, complete at budget N."""
    spent = ledger.budget_spent()
    fi = frontier_input(ledger, frontier_stage)
    return {
        "schema": SCHEMA,
        "space_digest": space_digest,
        "budget": ledger.budget.as_record(),
        "budget_spent": spent,
        "fidelity_ladder": list(FIDELITY_LADDER),
        "full_pnr_stage": FULL_PNR_STAGE,
        "feasibility_terms": list(FEASIBILITY_TERMS),
        "lever_notes": list(lever_notes or []),
        "candidates": [c.as_record() for c in ledger.candidates],
        "frontier_input": fi,
        "toolchain": dict(toolchain or {}),
        "what_the_budget_bought": what_the_budget_bought(ledger, fi),
    }


def what_the_budget_bought(ledger: Ledger,
                           fi: Dict[str, Any]) -> Dict[str, Any]:
    """One paragraph a human can read without decoding the ledger.

    It exists because the number a reader takes away from a search report is
    whichever one is easiest to read, and if that is the trial count they will
    compare two tuners on it. So the sentence puts CPU-hours and wall time in
    the same breath as the count, and says None where nothing was measured.
    """
    spent = ledger.budget_spent()
    cpu = spent["cpu_hours"]
    wall = spent["wall_seconds"]
    cpu_s = "CPU time not instrumented" if cpu is None \
        else f"{cpu:.4f} CPU-hours"
    if wall is not None:
        wall_s = f"{wall:.1f}s wall"
    elif ledger.budget.concurrency != 1:
        # Two different Nones, and saying so matters: one is "nothing to add
        # up", the other is "the sum is not the elapsed span". Printing the
        # same phrase for both would hide a run that DID measure its trials
        # behind a wording that blames the concurrency.
        wall_s = ("wall time not reconstructible at concurrency "
                  f"{ledger.budget.concurrency}")
    else:
        wall_s = "wall time not instrumented"
    return {
        "sentence": (
            f"budget {ledger.budget.max_trials} trial(s) / "
            f"{ledger.budget.max_full_pnr_trials} full-PnR: proposed "
            f"{spent['trials_proposed']}, ran {spent['trials_ran']} "
            f"({spent['cache_hits']} from cache, charged "
            f"{spent['trials_charged']}), of which "
            f"{spent['full_pnr_trials']} reached full place-and-route; "
            f"{cpu_s}, {wall_s}; "
            f"{fi['included_count']} candidate(s) are comparable at scope "
            f"{fi['frontier_stage']!r}."),
        "comparable_points": fi["included_count"],
        "frontier_stage": fi["frontier_stage"],
        "cpu_hours": cpu,
        "wall_seconds": wall,
    }


# ---------------------------------------------------------------------------
# the audit -- every way a published manifest could be dishonest
# ---------------------------------------------------------------------------
def audit_manifest(man: Dict[str, Any]) -> List[Dict[str, str]]:
    """Findings about a manifest. Empty list = the manifest is self-consistent.

    Each clause is a shape a search report has actually been wrong in, and each
    is checkable from the document alone -- an audit that needed the original
    run could not be applied to a manifest somebody else published, which is
    the only interesting case.
    """
    out: List[Dict[str, str]] = []

    def bad(code: str, detail: str) -> None:
        out.append({"code": code, "detail": detail})

    if man.get("schema") != SCHEMA:
        bad("WRONG_SCHEMA",
            f"first key must be {SCHEMA!r}, got {man.get('schema')!r}")

    budget = man.get("budget")
    if not isinstance(budget, dict):
        bad("NO_BUDGET", "a search without a declared budget publishes a "
                         "trial count that describes an unknown amount of "
                         "machine")
        budget = {}
    for key in Budget().as_record():
        if key not in budget:
            bad("BUDGET_FIELD_MISSING",
                f"budget does not declare {key!r}; it may not be left implicit")

    cands = man.get("candidates")
    if not isinstance(cands, list):
        bad("NO_CANDIDATES", "candidates[] absent: a manifest that publishes "
                             "no trial ledger cannot be checked against its "
                             "own counts")
        cands = []

    spent = man.get("budget_spent")
    if not isinstance(spent, dict):
        bad("NO_BUDGET_SPENT", "budget_spent absent")
        spent = {}
    else:
        if spent.get("trials_proposed") != len(cands):
            bad("LEDGER_TRUNCATED",
                f"budget_spent.trials_proposed={spent.get('trials_proposed')} "
                f"but candidates[] holds {len(cands)}. Publish every trial, "
                "not the best one.")

    ran = [c for c in cands if isinstance(c, dict)
           and c.get("state") in RAN_STATES]
    if isinstance(spent, dict) and spent.get("trials_ran") is not None \
            and spent.get("trials_ran") != len(ran):
        bad("RAN_COUNT_DISAGREES",
            f"budget_spent.trials_ran={spent.get('trials_ran')} but "
            f"{len(ran)} candidates carry a state that ran")

    n_full = sum(1 for c in ran if is_full_pnr(c.get("completed_stage")))
    if isinstance(budget, dict) and \
            isinstance(budget.get("max_full_pnr_trials"), int) and \
            n_full > budget["max_full_pnr_trials"]:
        bad("FULL_PNR_OVER_BUDGET",
            f"{n_full} trials reached full place-and-route but the declared "
            f"max_full_pnr_trials is {budget['max_full_pnr_trials']}; the "
            "published budget does not describe the run that happened")

    for i, c in enumerate(cands):
        if not isinstance(c, dict):
            bad("CANDIDATE_NOT_AN_OBJECT", f"candidates[{i}] is not an object")
            continue
        st = c.get("state")
        if st not in ALL_STATES:
            bad("UNKNOWN_STATE", f"candidates[{i}].state={st!r}")
        elif st not in TERMINAL_STATES:
            bad("NON_TERMINAL_STATE",
                f"candidates[{i}] is published as {st!r}: an unfinished trial "
                "is not a result")
        stage = c.get("completed_stage")
        if isinstance(stage, bool) or isinstance(stage, int):
            bad("STEP_LEAKED_AS_STAGE",
                f"candidates[{i}].completed_stage={stage!r} is an integer. A "
                "tuner iteration counter (ORFS/Ray Tune `step`) is not "
                "flow-stage progress and must never be recorded as one.")
        elif stage is not None and stage not in FIDELITY_LADDER:
            bad("STAGE_OFF_LADDER",
                f"candidates[{i}].completed_stage={stage!r} is not on the "
                f"declared ladder")
        if st in RAN_STATES and stage is None:
            bad("RAN_WITHOUT_A_STAGE",
                f"candidates[{i}] ran but records no completed_stage, so "
                "nothing can say what scope its metrics belong to")
        feas = c.get("feasibility")
        if not isinstance(feas, dict) or "verdict" not in feas:
            bad("NO_FEASIBILITY_VERDICT",
                f"candidates[{i}] carries no feasibility verdict")
        elif feas.get("verdict") not in (FEAS_ELIGIBLE, FEAS_INELIGIBLE,
                                         FEAS_UNDETERMINED):
            bad("UNKNOWN_FEASIBILITY",
                f"candidates[{i}].feasibility.verdict="
                f"{feas.get('verdict')!r}")
        elif feas.get("verdict") == FEAS_ELIGIBLE:
            terms = feas.get("terms") or {}
            missing = [t for t in FEASIBILITY_TERMS
                       if terms.get(t) not in ("PASS", "NOT_APPLICABLE")]
            if missing:
                bad("ELIGIBLE_ON_A_PARTIAL_VECTOR",
                    f"candidates[{i}] is ELIGIBLE but these feasibility terms "
                    f"do not PASS or state NOT_APPLICABLE: {missing}. "
                    "Detailed-route DRC alone (ORFS `num_drc`) is one of "
                    f"{len(FEASIBILITY_TERMS)} terms and is not an "
                    "eligibility verdict.")

    fi = man.get("frontier_input")
    if not isinstance(fi, dict):
        bad("NO_FRONTIER_INPUT", "frontier_input absent: nothing states which "
                                 "results were comparable")
    else:
        stage = fi.get("frontier_stage")
        inc = fi.get("included") or []
        by_ident = {c.get("identity"): c for c in cands if isinstance(c, dict)}
        for j, p in enumerate(inc):
            if not isinstance(p, dict):
                bad("FRONTIER_POINT_NOT_AN_OBJECT", f"included[{j}]")
                continue
            src = by_ident.get(p.get("identity"))
            if src is None:
                bad("FRONTIER_POINT_NOT_IN_LEDGER",
                    f"included[{j}] identity {p.get('identity')!r} appears on "
                    "the frontier but in no published candidate")
                continue
            v = (src.get("feasibility") or {}).get("verdict")
            if v != FEAS_ELIGIBLE:
                bad("FRONTIER_POINT_NOT_ELIGIBLE",
                    f"included[{j}] is on the frontier with feasibility {v!r}")
            if p.get("completed_stage") != stage:
                bad("FRONTIER_SCOPE_MIXED",
                    f"included[{j}].completed_stage="
                    f"{p.get('completed_stage')!r} but frontier_stage="
                    f"{stage!r}; metrics at different stages are different "
                    "metrics and a frontier over them is UNDETERMINED")
            for m in p.get("metrics") or []:
                if isinstance(m, dict) and m.get("status") != "MEASURED":
                    bad("FRONTIER_USES_UNMEASURED_METRIC",
                        f"included[{j}] carries a {m.get('status')!r} metric "
                        f"{m.get('metric')!r}; only MEASURED may enter a "
                        "numeric comparison")

    if isinstance(budget, dict) and budget.get("cache_policy") == CACHE_REUSE \
            and isinstance(spent, dict) and spent.get("cache_hits") is None:
        bad("CACHE_HITS_NOT_DECLARED",
            "cache_policy is REUSE but budget_spent does not say how many "
            "trials were cache hits; without it the published CPU-hours "
            "describe a different amount of work than a reader will assume")

    # F-12. A manifest may carry a REASON that names a condition about this
    # plugin -- "X has not landed". That is a checkable sentence, and a reader
    # holding the plugin should not have to check it by hand. Sixty published
    # manifests carried this exact sentence about a module that had landed
    # three commits earlier.
    #
    # It is a finding (rc=1), not UNDETERMINED, and the distinction is the
    # point: the audit LOOKED, the named file is right there, and the record
    # says it is not. That is a statement about the record, which is what this
    # audit adjudicates.
    for where, text in _published_reasons(man):
        for rel in unlanded_claims_contradicted_by_tree(text):
            bad(AUDIT_STUB_REASON_FALSE,
                f"{where} publishes as fact that {rel} {UNLANDED_CLAIM_PHRASE}"
                f", and {rel} is present on the tree auditing this manifest "
                f"({_programs_dir() / rel}). A stub reason that names a "
                "condition must check that condition at the moment it speaks; "
                "this one outlived its cause and was published as a fact.")

    return out


def _published_reasons(man: Dict[str, Any]) -> List[Tuple[str, Any]]:
    """(where, text) for every free-text reason a manifest publishes.

    Enumerated EXPLICITLY rather than by walking every string in the document,
    because a blanket walk would also read the design's own notes and turn a
    quotation into a finding. These are the fields this module writes.
    """
    rows: List[Tuple[str, Any]] = []
    tc = man.get("toolchain")
    if isinstance(tc, dict):
        for key, val in sorted(tc.items()):
            rows.append((f"toolchain.{key}", val))
    for i, c in enumerate(man.get("candidates") or []):
        if not isinstance(c, dict):
            continue
        feas = c.get("feasibility")
        if isinstance(feas, dict):
            rows.append((f"candidates[{i}].feasibility.reason",
                         feas.get("reason")))
    fi = man.get("frontier_input")
    if isinstance(fi, dict):
        for j, x in enumerate(fi.get("excluded") or []):
            if isinstance(x, dict):
                rows.append((f"frontier_input.excluded[{j}].detail",
                             x.get("detail")))
    return rows
