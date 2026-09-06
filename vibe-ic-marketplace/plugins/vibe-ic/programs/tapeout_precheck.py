#!/usr/bin/env python3
"""tapeout_precheck.py — step 37.5ic's ONE gate over TWO independent arms.

ENFORCEMENT: BLOCKING. This gate is in
``phase3_one_shot_runner._DECLARED_SIGNOFF_GATES`` as of 2026-09-04, so every
phase-3 run invokes it and its rc is part of the sign-off roll-up. It is ALSO
step 37.5ic's ``program_exit_zero`` clause under ``flow_compliance_check``, and
the two channels agree by construction because both read this one rc.

Until 2026-09-04 it was in NEITHER runner, and this paragraph said so while
noting that wiring it in "changes what a real run blocks on, which is the flow
owner's call and is recorded here rather than taken". The flow owner took it.
What it had been costing, measured on the published corpus: both ladders
existed, neither ran, and all seven published layouts carry GUARD_RING_MK = 0
and match no slot — with no run ever saying so.

BECAUSE IT NOW RUNS ON EVERY PHASE-3 PROJECT, it must first decide whether the
STEP applies at all: an IP/hardmacro delivery has no die, and a permanent red
on every such design would make this a detector that fires on everything. See
`delivery_route` — and note that an UNDECLARED route is NOT the IP path.
Declared because vibe-ic#886 counts an undeclared AUDIT_ONLY gate as an
enforcement decision nobody made. Kept in the first 4 kB: `declared_intent`
reads only `text[:4000]`.

WHY THIS EXISTS (2026-08-20 — the retirement of step `37.5self`)
================================================================
The flow used to carry THREE tape-out routes out of step 0.5ic, and the third
one was a mistake of shape rather than of content:

    slots/*.yaml     -> 37.5ic    the shuttle OPERATOR's own container
    SELF_TAPEOUT.txt -> 37.5self  OUR general ladder
    NO_TEMPLATE.txt  -> 37.5ip    the IP/hardmacro terminal

The first two are not alternatives. They are two independent authorities
examining the SAME GDS, and making them separate ROUTES meant a design routed
to one was never shown the other: a shuttle design got the operator's verdict
and never our ladder, and a self tape-out got our ladder and nothing external.
Each design was checked once by whichever party happened to be reachable.

So `37.5self` is retired as a step and folded in here as an ARM:

    OUR ladder   `general_precheck`         runs on EVERY design reaching 37.5ic
    THEIR ladder `tapeout_readiness_check`  runs IN ADDITION, when the PDK ships
                                            a shuttle precheck and its template
                                            was fetched

That is strictly MORE checking than the three-route shape, in both directions.
A PDK with no shuttle precheck is not a different route — it is this same step
with one fewer arm.

"THE PDK SHIPS A SHUTTLE PRECHECK" NEEDS BOTH HALVES
====================================================
The registry must name a LIVE shuttle for this PDK **and** that operator's
template must actually have been fetched. Registry says yes and nothing was
fetched is `NOT_DETERMINED` — never a silent skip. "We did not go and get it"
and "we got it and it passed" must not produce the same artefact, and a step
that quietly drops an arm produces exactly the artefact of a step that ran it
and was satisfied.

A PDK that could not be determined AT ALL is also `NOT_DETERMINED`, for the
same reason one layer up: not knowing which process this is means not knowing
whether a second authority exists, and reporting NOT_APPLICABLE from there
would be "we could not look" written down as "there was nothing to look at".

FOUR ARM STATES, AND ONLY ONE OF THEM IS A LEGITIMATE ABSENCE
=============================================================
    RAN             the arm executed and returned a verdict.
    NOT_APPLICABLE  the registry names no live shuttle for this PDK. THE ONLY
                    absence that is not a defect — the owner's "one fewer arm".
    NOT_DETERMINED  the arm should have run and could not: the template was
                    never fetched, or the PDK is unknown.
    ERROR           the arm was launched and did not produce a readable report.

DISAGREEMENT IS THE MOST VALUABLE OUTCOME, AND IT FAILS THE STEP
================================================================
Both ladders name their steps with the SAME ids on purpose — `general_precheck`
was written as the operator's ladder minus the operator's two steps — so eight
ladder steps are judged by both arms on the same layout. When two authorities
reach OPPOSITE CONCLUSIVE verdicts on the same step, one of the two checks is
wrong, and which one is a lesson for this plugin rather than a thing to be
resolved in the moment.

So a disagreement is recorded as a finding of its own, it names both verdicts
and both authorities, and it REFUSES. It is never resolved by preferring an
arm: preferring one is precisely how the wrong one survives. NOT_DETERMINED on
one side is an ABSENCE, not a disagreement, and is reported as such.

EVERY FINDING NAMES THE AUTHORITY THAT PRODUCED IT
==================================================
The entire value of the operator's arm is that its verdict is NOT one we wrote,
and a gate we wrote can be made to pass by editing it. Merging the two arms
into one report must not blur that, so every finding carries `authority` (the
party) and `authority_is_ours` (a boolean, so a consumer cannot infer it wrong
from a string it does not recognise). The merge's OWN findings — arm
applicability, disagreements — are labelled ours, because they are.

THE THREE VERDICTS, AND WHY THERE ARE ONLY THREE
================================================
Identical to both arms, on purpose, so all three reports read the same way:

    PASS            every arm that ran carries passing evidence, and the arm
                    that did not run is the legitimately absent one.
    FAIL            an arm refused, or the two arms disagree.
    NOT_DETERMINED  an arm could not reach a verdict, or should have run and
                    did not.

No `SKIPPED`, `N/A` or `BLOCKED`. All three read as "nothing to worry about
here" in an aggregate, and nothing-to-worry-about is exactly what a design
nobody finished checking is not entitled to.

EXIT CODES
==========
    0  PASS
    1  FAIL **and** NOT_DETERMINED — every non-pass
    2  usage / unreadable input

rc 3 is NOT used (`flow_compliance_check` reads it as PASS_WITH_WAIVERS and
promotes the step to WAIVED-DEFERRED). rc 2 is not used for NOT_DETERMINED
either: this repo credits a rc-2 `VACUOUS_PASS` as a pass repo-wide. Either
would route "we did not find out" back into a green light.

DENOMINATOR
===========
The verdict line always states how many arms were expected, how many ran, how
many findings each authority produced and how many disagreements were found. An
absent arm is counted and named, never rounded away.

chip-AGNOSTIC: no vendor, foundry, process node, SKU, chip codename or design
literal. The PDK is read from the design's own declaration through the tree's
existing accessor, and the shuttle registry names PUBLIC open-MPW programmes
and their OPEN PDKs — the same class of name `pdk_registry.json` already
carries.

USAGE
-----
    python3 tapeout_precheck.py <project>
        [--pdk NAME]            # default: read from the design's declaration
        [--gds PATH]            # default: discovered under the project
        [--declaration PATH]
        [--slot 1x1] [--cob] [--top NAME] [--id HEX]
        [--image IMG] [--pull]
        [--timeout SECONDS]
        [--json OUT]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import _submission_template as _st                            # noqa: E402
import _tapeout_declaration as _decl                          # noqa: E402
import general_precheck as _ours                             # noqa: E402
import plugin_manifest_discovery as _pmd                     # noqa: E402
import tapeout_readiness_check as _theirs                    # noqa: E402
from _atomic_artefact import write_text as atomic_write_text  # noqa: E402

ATTRIBUTION = "tapeout_precheck"

PASS = "PASS"
FAIL = "FAIL"
NOT_DETERMINED = "NOT_DETERMINED"

#: Arm states. See "FOUR ARM STATES" above.
RAN = "RAN"
NOT_APPLICABLE = "NOT_APPLICABLE"
ERROR = "ERROR"

#: The delivery route step 0.5ic established for this design.
ROUTE_CHIP = "CHIP"
ROUTE_IP = "IP"
ROUTE_UNDECLARED = "UNDECLARED"

#: The two authorities, named ONCE. `OURS` is this plugin; the operator's name
#: is composed from the registry entry at run time so a second shuttle names
#: itself rather than being mislabelled as the first.
OURS = "vibe-ic"

#: Where this gate's verdict belongs, and where each arm's own report goes.
#: Named here so the producer and every consumer cannot drift onto different
#: paths, and so the flow yaml's `required_outputs` and this file agree by
#: construction rather than by somebody remembering.
MERGED_ARTEFACT = "reports/phase3/tapeout_precheck.json"
OUR_ARM_ARTEFACT = "reports/phase3/general_precheck.json"
THEIR_ARM_ARTEFACT = "reports/phase3/shuttle_precheck.json"

#: The operator's template, fetched by step 0.5ic. Its PRESENCE is the second
#: half of "this PDK ships a shuttle precheck": the registry says one exists,
#: this says somebody went and got it.
TEMPLATE_SLOTS_GLOB = "input/submission_template/slots/*.yaml"


def _authority_of(shuttle: Any) -> str:
    """`<shuttle_id>/<tool>` — the party AND the tool, never one alone.

    Two shuttles can wrap tools of the same name and one shuttle can change the
    tool it runs, so a finding that names only one half is a finding whose
    provenance goes stale silently.
    """
    return f"{shuttle.shuttle_id}/{shuttle.tool}"


@dataclass
class Finding:
    """One line of the merged report, and it always names who said it."""
    authority: str
    authority_is_ours: bool
    kind: str                 # REFUSAL / UNDETERMINED / DISAGREEMENT / ARM
    step_id: Optional[str]    # the ladder step, when the finding is about one
    verdict: str
    message: str
    detail: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # RB2-08 (#2063) — NAME THE ARM. Every generic report reader in this
        # repo renders a finding as `f["rule"]: f["message"]` (see
        # `phase3_one_shot_runner._gate_detail`, `f.get('rule', '?')`), and this
        # gate's findings carry no `rule` key at all. MEASURED on the
        # subservient cell (lane rbsub2, 8HD-8, 2026-09-06), the step line read
        #
        #   FAIL tapeout_precheck ?: the arm reported NOT_DETERMINED with no
        #   evidence line; ?: ... (x6)
        #
        # — six undetermined arms and not one of them named. The information
        # was never missing; it was in `authority` / `kind` / `step_id`, in
        # fields no generic reader looks at. `rule` is DERIVED from those three
        # so it cannot drift from them, and it says which authority and which
        # ladder step the line is about.
        d["rule"] = self.rule
        return d

    @property
    def rule(self) -> str:
        """`<kind>/<ladder step or authority>` — the generic reader's key."""
        return f"{self.kind}/{self.step_id or self.authority or 'unattributed'}"


@dataclass
class Arm:
    """One authority's participation in this step — including a non-run."""
    arm: str                  # "ours" / "operator"
    authority: str
    authority_is_ours: bool
    state: str                # RAN / NOT_APPLICABLE / NOT_DETERMINED / ERROR
    reason: str
    verdict: Optional[str] = None
    report: Optional[str] = None
    returncode: Optional[int] = None
    steps: List[Dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MergedReport:
    project: str
    verdict: str
    reason: str
    pdk: Optional[str]
    pdk_source: Optional[str]
    #: Which delivery route step 0.5ic established, and whether this STEP
    #: applies to it at all. Separate from `verdict` on purpose: "this design
    #: has no die" and "this die was checked and is clean" are different
    #: claims, and a consumer that could not tell them apart would read the
    #: whole IP population as tape-out-ready.
    route: str = ROUTE_UNDECLARED
    route_evidence: str = ""
    step_applies: bool = True
    arms_expected: int = 0
    arms_ran: int = 0
    arms: List[Arm] = field(default_factory=list)
    findings: List[Finding] = field(default_factory=list)
    disagreements: List[Dict[str, Any]] = field(default_factory=list)
    shared_ladder_steps: List[str] = field(default_factory=list)
    #: Values are strings EXCEPT `submission_prep`, which is the resolver's
    #: own dict — see below for why the report carries the resolution and not
    #: a sentence about it.
    retired_shuttles_for_this_pdk: List[Dict[str, Any]] = field(
        default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["arms"] = [a.as_dict() for a in self.arms]
        d["findings"] = [f.as_dict() for f in self.findings]
        d["emitted_by"] = _pmd.emitted_by(ATTRIBUTION)
        return d

    def summary_line(self) -> str:
        """One line that ALWAYS states the denominator."""
        per_authority = {}
        for f in self.findings:
            per_authority[f.authority] = per_authority.get(f.authority, 0) + 1
        by = ", ".join(f"{k}={v}" for k, v in sorted(per_authority.items()))
        return (
            f"{self.verdict}: tapeout_precheck (two arms) — "
            f"pdk={self.pdk or 'NOT_DETERMINED'}, "
            f"arms_expected={self.arms_expected}, arms_ran={self.arms_ran}, "
            f"disagreements={len(self.disagreements)}, "
            f"findings_by_authority=[{by or 'none'}] — {self.reason}")


#: Injectable seam so both arms are testable with NO EDA tool and NO container.
Runner = Callable[[List[str], Optional[float]], Tuple[int, str, str]]


try:  # sibling module; programs/ is on sys.path when run as a script
    import _watchdog as _wd
except ImportError:  # pragma: no cover - packaged/flattened layouts
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _watchdog as _wd  # type: ignore
def default_runner(cmd: List[str], timeout: Optional[float]
                   ) -> Tuple[int, str, str]:
    """PROGRESS-supervised delegation to a checker.

    `timeout` is the STALL GRACE, not a runtime bound. As
    `subprocess.run(timeout=)` its expiry returned rc 124 with "[timeout]",
    which the two-arm precheck reads as the delegated checker having FAILED —
    a verdict about the design derived from a number that describes this host.
    A checker on a large layout, or on a machine running four other jobs, is
    slow for reasons that say nothing about whether it would have passed. The
    watchdog kills only a delegate whose CPU, I/O and output have ALL sat flat
    for the grace, and says so under its own rc. `None` keeps its meaning of
    "no bound at all"; the supervisor is then given the module default grace,
    which still cannot end a job that is working."""
    grace = (float(timeout) if timeout is not None
             else _wd.DEFAULT_STALL_GRACE_S)
    try:
        res = _wd.run_host_supervised([str(c) for c in cmd],
                                      stall_grace_s=grace)
    except (OSError, subprocess.SubprocessError) as exc:
        return 125, "", f"[runner error] {exc!r}"
    if res.outcome == "launch_error":
        return 125, "", f"[runner error] {res.err}"
    return res.rc, res.out or "", res.err or ""


# --------------------------------------------------------------------------- #
# Which PDK is this, and does it ship a shuttle precheck?
# --------------------------------------------------------------------------- #
def resolve_pdk(project: Path,
                explicit: str = "") -> Tuple[Optional[str], Optional[str]]:
    """(pdk, where it was read from) — or (None, None) when nobody said.

    NOT re-derived here. `declared_pdk_is_the_pdk_used_check.declared_target`
    is the tree's accessor for "what does this design say it targets"; it walks
    the record Phase 1 already wrote, in a precedence order that module owns and
    tests. A second resolver here would be a second answer with nothing tying
    the two together — and that module's own docstring records what happened the
    last time this question had two implementations: one of them returned
    ``(None, None)`` for all 106 projects in the corpus.
    """
    if explicit.strip():
        return explicit.strip(), "--pdk"
    try:
        import declared_pdk_is_the_pdk_used_check as _pdkid
    except ImportError:                       # pragma: no cover - defensive
        return None, None

    # THE PDK A SIGN-OFF IS GRADED AGAINST IS THE ONE THE RUN BUILT, not the
    # one the design happened to name first.
    #
    # MEASURED on spm x gf180mcuD (2026-09-02), a run invoked `--pdk
    # gf180mcuD`: this function returned `('sky130', 'phase1/generated_docs/
    # L19_CONSTRAINTS_PDK.json:fields.pdk_target')` and the merged report
    # published `pdk=sky130`. L19 was RIGHT — the design declares
    # `pdk_target: "sky130"` with `pdk_target_alternates: ["sky130",
    # "gf180mcu"]`, faithfully extracted from a datasheet naming SKY130 primary
    # and GF180MCU secondary — and step 37.5ic's gate clause passes no `--pdk`,
    # so the scalar primary was the only thing anybody read. Everything
    # downstream in this module is PDK-scoped: `operator_arm_applicability`,
    # `shuttle_for_pdk`, `retired_shuttles_for_pdk`. All three were answered
    # for a process the run never used.
    #
    # `declared_alternates` exists for exactly this shape and says so: "a
    # design may legitimately declare more than one target ... and a run builds
    # ONE of them". So the declaration is read as the SET it is, and the member
    # the run corroborates is the answer. The corroboration channel is
    # `loaded_libraries` — the .lef/.lib basenames the tools themselves logged,
    # "because the question is what RAN". On the spm run: 0 names share
    # identity with `sky130` and many with `gf180mcu`.
    #
    # NO SECOND RESOLVER. Every accessor used here is that module's own, in its
    # own precedence, for the reason this docstring already gives; what is added
    # is that the design's own alternates are consulted before its primary is
    # asserted against a run that built something else. A design declaring one
    # target, or a run with no tool log to read, resolves exactly as before.
    declared, source = _pdkid.declared_target(project)
    alternates = _pdkid.declared_alternates(project)
    if not alternates:
        return declared, source
    try:
        loaded, scanned = _pdkid.loaded_libraries(project)
    except OSError:                           # pragma: no cover - defensive
        return declared, source
    if not scanned or not loaded:
        return declared, source
    corroborated = [c for c in alternates
                    if any(_pdkid.shares_identity(_pdkid.tokens(c), name)
                           for name in loaded)]
    # EXACTLY ONE, or nothing changes. Two corroborated members is a run that
    # loaded libraries from two processes, which is a contradiction this
    # function must not resolve by picking one — `declared_pdk_is_the_pdk_used_
    # check` owns that finding and reports it as one.
    if len(corroborated) == 1 and corroborated[0] != declared:
        return (corroborated[0],
                f"the run's own tool logs: {scanned} log(s) name "
                f"{corroborated[0]!r} libraries and none of the other "
                f"target(s) the design declares "
                f"(pdk_target_alternates={alternates!r}); "
                f"pdk_target={declared!r} from {source}")
    return declared, source


#: The three router artefacts step 0.5ic writes, exactly one per design. The
#: flow's own `condition` for 37.5ic is `any_of` over the two CHIP ones; this
#: mirrors it rather than restating it, because a step-level applicability
#: spelled in two places is two spellings that drift.


def delivery_route(project: Path) -> Tuple[str, str]:
    """(route, the evidence that decided it) — never a guess.

    WHY A GATE NEEDS THIS AT ALL. Wired into `_DECLARED_SIGNOFF_GATES`, this
    program runs on EVERY phase-3 project, including ones that will never have
    a die: an IP/hardmacro delivery has no pad ring, no seal ring and no
    tape-out precheck, and reporting it NOT_DETERMINED would put a permanent
    red on every such design for a question that was never asked of it. That is
    the shape of a detector that fires on everything.

    AND "NOBODY DECLARED A ROUTE" IS NOT THE IP PATH. It is its own answer.
    Treating an absent router as "this must be an IP" would let a CHIP design
    whose step 0.5ic failed skip the tape-out precheck silently — the failure
    would remove the check that would have reported it. So an undeclared route
    is NOT_DETERMINED and stays a non-pass.
    """
    if any(p.is_file() for p in project.glob(TEMPLATE_SLOTS_GLOB)):
        return ROUTE_CHIP, TEMPLATE_SLOTS_GLOB
    if (project / _decl.SELF_TAPEOUT_REL).is_file():
        return ROUTE_CHIP, _decl.SELF_TAPEOUT_REL
    if (project / _st.NO_TEMPLATE_REL).is_file():
        return ROUTE_IP, _st.NO_TEMPLATE_REL
    return ROUTE_UNDECLARED, ""


def resolve_slot(project: Path,
                 explicit: str = "") -> Tuple[Optional[str], Optional[str]]:
    """(slot, where it was read from) — or (None, None) when nobody said.

    WHY THIS EXISTS: `--slot` used to DEFAULT to ``"1x1"``, and that default was
    passed verbatim to the operator's own tool. So a design whose fetched
    template ships `0p5x0p5.yaml` was asked about a slot it never purchased, by
    the one arm whose entire value is that WE DID NOT WRITE IT — and the answer
    came back conclusive. A default is an answer to a question nobody asked, and
    it is worst exactly here: our arm can be made to agree by editing it, the
    operator's cannot, so a wrong input to theirs is the one that survives.

    THE SLOT IS THE OPERATOR'S CONSTANT, NOT OURS. It is handed over per slot in
    the fetched template, so the fetched template is the only place it can be
    read from. Resolution order:

        --slot                         the caller said so, explicitly
        exactly one slots/*.yaml       the template shipped one and only one
        the declaration names one      it must be one the template actually
                                       ships; a declaration naming a slot the
                                       operator does not offer is NOT a match

    Anything else — no template, several slots and no declaration, or a
    declaration naming a slot that is not on offer — returns ``None``, and the
    operator's arm is then NOT_DETERMINED with that reason in writing. It is
    NEVER "pick the first one": several slots means the question is open, and
    picking one closes it with an answer the design never gave.
    """
    if explicit.strip():
        return explicit.strip(), "--slot"
    names: Dict[str, str] = {}
    for p in sorted(project.glob(TEMPLATE_SLOTS_GLOB)):
        if not p.is_file():
            continue
        name = p.stem
        try:
            doc = json.loads(p.read_text(errors="replace"))
            if isinstance(doc, dict) and isinstance(doc.get("slot"), str):
                name = doc["slot"]
        except (OSError, ValueError):
            pass          # the stem is the ingest's own file name for the slot
        names[name] = str(p.relative_to(project))
    if not names:
        return None, None
    # ONE ON OFFER IS STILL NOT A DECLARATION. `submission_template_ingest`
    # states the rule for the whole step -- the slot is "the slot this design
    # DECLARES it targets. Never guessed and never defaulted." What the
    # operator happens to sell today is not what this design bought: an
    # operator that adds a second slot tomorrow would silently move a design
    # that never chose. So a sole slot is read only when the design points at
    # it, exactly like any other.
    declared = _declared_slot(project)
    if declared and declared in names:
        return declared, f"the declaration, matched against {names[declared]}"
    return None, None


def _declared_slot(project: Path) -> Optional[str]:
    """The slot the DESIGN declared, from the flow's own home for that fact.

    `input/step_0_5ic_answers.json` -> `operator_template.slot`, which is
    exactly where `phase1_one_shot_runner._run_step_0_5ic` reads it before
    passing `--slot` to the ingest. ONE home, read the same way by everybody.

    The first version of this function sniffed the TAPE-OUT DECLARATION for any
    of `slot` / `purchased_slot` / `operator_slot`. That was wrong twice over:
    the declaration has no such question among its 18, so the key could only
    ever be an unknown one; and matching a set of plausible NAMES is the
    token-match mistake this repo has paid for before — a name is not a
    declaration, and the declaration already exists somewhere else.
    """
    try:
        doc = json.loads(
            (project / _st.DESIGN_ANSWERS_REL).read_text(errors="replace"))
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict):
        return None
    operator = doc.get("operator_template")
    if not isinstance(operator, dict):
        return None
    got = operator.get("slot")
    if isinstance(got, str) and got.strip() and got.strip() != NOT_DETERMINED:
        return got.strip()
    return None


def template_was_fetched(project: Path) -> bool:
    """Did step 0.5ic actually bring back the operator's slot geometry?

    PRESENCE OF A SLOT FILE, not presence of the directory: an empty
    `input/submission_template/slots/` is what a fetch that failed leaves
    behind, and it must not read as a fetch that succeeded.
    """
    return any(p.is_file() for p in project.glob(TEMPLATE_SLOTS_GLOB))


def operator_arm_applicability(project: Path, pdk: Optional[str]
                               ) -> Tuple[str, str, Optional[Any]]:
    """(state, reason, shuttle) for the OPERATOR's arm.

    The four states are the ones in this module's docstring, and the whole
    point of having four is that only ONE of them is a legitimate absence.
    """
    if not pdk:
        return (NOT_DETERMINED,
                "the design declares no PDK target that this flow could read, "
                "so whether a shuttle precheck exists for it was never looked "
                "up. Not knowing which process this is, is not the same fact "
                "as knowing the process has no external check, and it must not "
                "be recorded as one",
                None)
    shuttle = _theirs.shuttle_for_pdk(pdk)
    if shuttle is None:
        return (NOT_APPLICABLE,
                f"the shuttle registry names no LIVE shuttle precheck for PDK "
                f"{pdk!r}, so there is no second authority to ask and this step "
                f"runs with one arm. Registry consulted: "
                f"{sorted(_theirs.SHUTTLES)}",
                None)
    if not template_was_fetched(project):
        return (NOT_DETERMINED,
                f"the registry names the LIVE shuttle {shuttle.shuttle_id!r} "
                f"for PDK {pdk!r}, and its project template was never fetched "
                f"(no {TEMPLATE_SLOTS_GLOB} under the project). The operator's "
                f"own container needs the slot geometry to run, so the "
                f"counterparty was not asked — and 'we did not go and get it' "
                f"must not produce the same artefact as 'we got it and it "
                f"passed'",
                shuttle)
    return (RAN,
            f"the registry names the LIVE shuttle {shuttle.shuttle_id!r} for "
            f"PDK {pdk!r} and its template was fetched, so the operator's own "
            f"container is asked about this layout in addition to our ladder",
            shuttle)


# --------------------------------------------------------------------------- #
# Running an arm — each one writes its OWN artefact, which we then QUOTE
# --------------------------------------------------------------------------- #
def _read_report(path: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    if not path.is_file():
        return None, f"the arm wrote no report at {path}"
    try:
        doc = json.loads(path.read_text(errors="replace"))
    except (OSError, ValueError) as exc:
        return None, f"the arm's report at {path} is unreadable: {exc}"
    if not isinstance(doc, dict):
        return None, f"the arm's report at {path} is not a JSON object"
    return doc, None


def _run_arm(cmd: List[str], out: Path, runner: Runner,
             timeout: Optional[float]) -> Tuple[Optional[Dict[str, Any]],
                                                int, Optional[str]]:
    out.parent.mkdir(parents=True, exist_ok=True)
    rc, _stdout, stderr = runner(cmd, timeout)
    doc, err = _read_report(out)
    if doc is None:
        tail = (stderr or "").strip()[-400:]
        return None, rc, f"{err}; the arm exited rc={rc}" + (
            f": {tail}" if tail else "")
    return doc, rc, None


def _steps_of(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    steps = doc.get("steps")
    return [s for s in steps if isinstance(s, dict)] if isinstance(
        steps, list) else []


def _unattributed_message(authority: str, verdict: str,
                          st: Dict[str, Any]) -> str:
    """The sentence for a non-passing ladder step whose arm wrote no evidence.

    RB2-08 (#2063). It used to read "the arm reported NOT_DETERMINED with no
    evidence line" — about a report that knows exactly which arm and which
    ladder step it just read. Six such lines, all identical, were the whole
    reason this gate FAILed on the subservient cell.
    """
    step = st.get("step_id") or "<the arm report names no step_id>"
    label = st.get("label")
    where = f"{step} ({label})" if label else f"{step}"
    return (f"arm {authority or 'unattributed'} reported "
            f"{verdict or 'no verdict'} for ladder step {where} "
            f"with no evidence line")


def _findings_from_arm(doc: Dict[str, Any], authority: str,
                       is_ours: bool) -> List[Finding]:
    """Every non-passing ladder step of one arm, as one labelled line each.

    The arm's OWN words are carried through verbatim in `message`. Nothing here
    re-judges a step: a merge that paraphrased a refusal would be a third
    opinion wearing the authority of the first two.
    """
    out: List[Finding] = []
    for st in _steps_of(doc):
        verdict = str(st.get("verdict") or "")
        if verdict == PASS:
            continue
        out.append(Finding(
            authority=authority, authority_is_ours=is_ours,
            kind="REFUSAL" if verdict == FAIL else "UNDETERMINED",
            step_id=str(st.get("step_id") or "") or None,
            verdict=verdict or NOT_DETERMINED,
            message=str(st.get("evidence") or "")
                    # RB2-08 (#2063) — the arm, and the step, by name. The old
                    # sentence said "the arm" about a report that knows exactly
                    # which arm it read.
                    or _unattributed_message(authority, verdict, st),
            detail={"label": st.get("label"),
                    "refuses_on": st.get("refuses_on"),
                    "source": st.get("source")}))
    return out


def find_disagreements(ours: Dict[str, Any], theirs: Dict[str, Any],
                       our_authority: str, their_authority: str
                       ) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Ladder steps BOTH arms judged conclusively and judged differently.

    CONCLUSIVE means PASS or FAIL. A NOT_DETERMINED on either side is an
    ABSENCE — one authority did not reach a verdict — and calling that a
    disagreement would flood the report with the very silence the arms exist to
    surface, and would hide the real disagreements among them.

    Returns (disagreements, shared_step_ids) so the report can state the
    DENOMINATOR: how many steps the two ladders actually have in common is the
    number that makes "0 disagreements" mean something.
    """
    ours_by = {str(s.get("step_id")): s for s in _steps_of(ours)}
    theirs_by = {str(s.get("step_id")): s for s in _steps_of(theirs)}
    shared = sorted(set(ours_by) & set(theirs_by))
    out: List[Dict[str, Any]] = []
    for sid in shared:
        ov = str(ours_by[sid].get("verdict") or "")
        tv = str(theirs_by[sid].get("verdict") or "")
        if ov not in (PASS, FAIL) or tv not in (PASS, FAIL) or ov == tv:
            continue
        out.append({
            "step_id": sid,
            "label": ours_by[sid].get("label") or theirs_by[sid].get("label"),
            "verdicts": [
                {"authority": our_authority, "authority_is_ours": True,
                 "verdict": ov,
                 "evidence": str(ours_by[sid].get("evidence") or "")},
                {"authority": their_authority, "authority_is_ours": False,
                 "verdict": tv,
                 "evidence": str(theirs_by[sid].get("evidence") or "")},
            ],
        })
    return out, shared


# --------------------------------------------------------------------------- #
# Evaluation
# --------------------------------------------------------------------------- #
def evaluate(project: Path,
             pdk: str = "",
             layout: Optional[Path] = None,
             declaration_path: Optional[Path] = None,
             slot: str = "",
             cob: bool = False,
             top: str = "",
             die_id: str = "",
             image: str = "",
             allow_pull: bool = False,
             runner: Optional[Runner] = None,
             programs_dir: Optional[Path] = None,
             timeout: Optional[float] = 7200.0) -> MergedReport:
    """Run both arms — or say, in writing, why one of them did not run."""
    run = runner or default_runner
    pdir = programs_dir or _HERE
    resolved_pdk, pdk_source = resolve_pdk(project, pdk)

    route, route_evidence = delivery_route(project)
    rep = MergedReport(project=str(project), verdict=NOT_DETERMINED, reason="",
                       pdk=resolved_pdk, pdk_source=pdk_source,
                       route=route, route_evidence=route_evidence)

    # STEP-LEVEL APPLICABILITY, DECIDED FIRST AND ON THE PROJECT'S OWN EVIDENCE.
    # This is the rc-0 NOT_APPLICABLE channel `_DECLARED_SIGNOFF_GATES` names —
    # not `_vacuous_exit.RC_VACUOUS`, which is rc 2 and which that table reads
    # as an ERROR outright.
    #
    # ONLY THE IP ROUTE GETS IT. An IP/hardmacro delivery has no die, so there
    # is no layout to submit and nothing for either ladder to judge; a red here
    # would be about a question never asked of it. An UNDECLARED route is
    # deliberately NOT included: 0.5ic failing is the one circumstance in which
    # a CHIP most needs this step, and reading its silence as "must be an IP"
    # would let the failure delete the check that would have reported it.
    if route == ROUTE_IP:
        rep.step_applies = False
        rep.verdict = PASS
        rep.reason = (
            f"step 37.5ic does not apply to this design: step 0.5ic routed it "
            f"to the IP/hardmacro terminal ({route_evidence}), which delivers "
            f"LEF/Liberty/GDS/Verilog and no die. There is no submission, so "
            f"there is no tape-out precheck to pass — `step_applies` is false "
            f"and this is NOT a statement that a layout was examined.")
        return rep
    # A RETIRED counterparty still has an in-tree submission-prep chain, and
    # "that chain is still here" is the entire reason the retired path is kept
    # rather than deleted. `resolve_submission_prep` IMPORTS it, so this arm
    # reports whether the claim is true on THIS checkout instead of repeating
    # a registry sentence that would keep reading true after the programs it
    # names were gone. This runs on every design whose PDK has a retired
    # shuttle, whether or not a live operator arm also applies.
    rep.retired_shuttles_for_this_pdk = [
        {"shuttle_id": sh.shuttle_id, "tool": sh.tool,
         "retired_reason": sh.retired_reason,
         "submission_prep": _theirs.resolve_submission_prep(sh, pdir)}
        for sh in (_theirs.retired_shuttles_for_pdk(resolved_pdk)
                   if resolved_pdk else ())]

    # ---------------- ARM 1 — OURS. No condition. Every design. -------------
    our_authority = f"{OURS}/{_ours.ATTRIBUTION}"
    our_out = project / OUR_ARM_ARTEFACT
    cmd = [sys.executable, str(pdir / "general_precheck.py"), str(project),
           "--json", str(our_out)]
    # THE PDK REACHES OUR OWN ARM. `general_precheck --pdk` exists so its
    # density rung can be judged against the PDK's OWN stated per-layer
    # windows; without it that delegate has no windows, every metal layer is
    # UNCHECKED and the rung cannot reach a verdict. That forwarding was
    # closed one level down (general_precheck -> metal_layer_density_check,
    # tests/test_gf180_general_precheck_forwards_the_pdk.py) and left open
    # here, at the only caller that has a resolved PDK to give. The value
    # forwarded is `resolved_pdk` — the same one this report publishes and the
    # operator arm is selected by — so the two arms cannot be judged against
    # different processes. HONEST ABSENCE: when the PDK could not be resolved
    # the flag is omitted exactly as before, the delegate reports that it had
    # no windows, and nothing is laundered into a clean density result.
    if resolved_pdk:
        cmd += ["--pdk", resolved_pdk]
    if layout is not None:
        cmd += ["--gds", str(layout)]
    if declaration_path is not None:
        cmd += ["--declaration", str(declaration_path)]
    our_doc, our_rc, our_err = _run_arm(cmd, our_out, run, timeout)
    our_arm = Arm(arm="ours", authority=our_authority, authority_is_ours=True,
                  state=RAN if our_doc is not None else ERROR,
                  reason=(our_err or "our general ladder ran on this layout; "
                          "it runs on every design that reaches this step, "
                          "with no condition"),
                  verdict=(str(our_doc.get("verdict")) if our_doc else None),
                  report=str(our_out), returncode=our_rc,
                  steps=_steps_of(our_doc) if our_doc else [])
    rep.arms.append(our_arm)
    if our_doc is not None:
        rep.findings.extend(
            _findings_from_arm(our_doc, our_authority, True))
    else:
        rep.findings.append(Finding(
            authority=our_authority, authority_is_ours=True, kind="ARM",
            step_id=None, verdict=NOT_DETERMINED, message=our_err or "",
            detail={"command": cmd}))

    # ---------------- ARM 2 — THEIRS, when there is a THEM ------------------
    state, why, shuttle = operator_arm_applicability(project, resolved_pdk)
    # WHICH SLOT — and NOT_DETERMINED rather than a guess. This runs only after
    # applicability, so it can never turn the legitimate absence
    # (NOT_APPLICABLE: no live shuttle for this PDK) into a defect. It fires in
    # exactly one place: the template WAS fetched, the operator IS there, and
    # the design still has not said which of the slots it bought.
    resolved_slot, slot_source = resolve_slot(project, slot)
    if state == RAN and not resolved_slot:
        state = NOT_DETERMINED
        why = (f"{why} — but which slot this design purchased was never "
               f"declared, and the operator's tool takes the slot as an "
               f"input it cannot check. A default here would be answered "
               f"CONCLUSIVELY by the one arm we cannot edit, so it is not "
               f"offered: state it with --slot, ship exactly one "
               f"{TEMPLATE_SLOTS_GLOB}, or name it in "
               f"{_decl.DECLARATION_REL}.")
    slot = resolved_slot or ""
    their_out = project / THEIR_ARM_ARTEFACT
    their_authority = (_authority_of(shuttle) if shuttle is not None
                       else f"{OURS}/{ATTRIBUTION}")
    their_doc: Optional[Dict[str, Any]] = None
    their_rc: Optional[int] = None
    if state == RAN:
        assert shuttle is not None
        cmd2 = [sys.executable, str(pdir / "tapeout_readiness_check.py"),
                str(project), "--shuttle", shuttle.shuttle_id,
                "--slot", slot, "--json", str(their_out)]
        if cob:
            cmd2.append("--cob")
        if top:
            cmd2 += ["--top", top]
        if die_id:
            cmd2 += ["--id", die_id]
        if image:
            cmd2 += ["--image", image]
        if allow_pull:
            cmd2.append("--pull")
        if layout is not None:
            cmd2 += ["--gds", str(layout)]
        their_doc, their_rc, their_err = _run_arm(cmd2, their_out, run, timeout)
        if their_doc is None:
            state, why = ERROR, their_err or "the operator's arm produced no report"
            # THE ARTEFACT EXISTS ON THIS PATH TOO. The arm was launched and
            # came back with nothing readable, which is a WORSE state than
            # never asking — and it must not be the state that leaves the
            # declared output absent, because an absent file is the one shape
            # a reader cannot tell from "this run predates the arm".
            _write_non_run_record(their_out, project, resolved_pdk, pdk_source,
                                  state, why, shuttle)
    else:
        # THE ARM DID NOT RUN, AND THE ARTEFACT STILL EXISTS. An absent file and
        # a file that says "nobody asked" are read identically by everything
        # downstream, which is the whole defect this step was rebuilt to close.
        # It is written under OUR authority, explicitly, because it is not the
        # operator's verdict — nobody obtained one.
        _write_non_run_record(their_out, project, resolved_pdk, pdk_source,
                              state, why, shuttle)

    rep.arms.append(Arm(
        arm="operator", authority=their_authority,
        authority_is_ours=(shuttle is None),
        state=state, reason=why,
        verdict=(str(their_doc.get("verdict")) if their_doc else None),
        report=str(their_out), returncode=their_rc,
        steps=_steps_of(their_doc) if their_doc else []))

    if their_doc is not None:
        rep.findings.extend(
            _findings_from_arm(their_doc, their_authority, False))
    elif state != NOT_APPLICABLE:
        rep.findings.append(Finding(
            authority=f"{OURS}/{ATTRIBUTION}", authority_is_ours=True,
            kind="ARM", step_id=None, verdict=NOT_DETERMINED, message=why,
            detail={"arm": "operator", "state": state}))
    else:
        # A LEGITIMATE ABSENCE IS STILL A LINE. It is not a defect and it does
        # not fail the step, and it is written down anyway: a report that
        # mentions one arm and is silent about the other cannot be told apart
        # from a report written before the second arm existed.
        rep.findings.append(Finding(
            authority=f"{OURS}/{ATTRIBUTION}", authority_is_ours=True,
            kind="ARM", step_id=None, verdict=NOT_APPLICABLE, message=why,
            detail={"arm": "operator", "state": state}))

    # ---------------- THE DISAGREEMENT PASS ---------------------------------
    if our_doc is not None and their_doc is not None:
        rep.disagreements, rep.shared_ladder_steps = find_disagreements(
            our_doc, their_doc, our_authority, their_authority)
        for d in rep.disagreements:
            a, b = d["verdicts"][0], d["verdicts"][1]
            rep.findings.append(Finding(
                authority=f"{OURS}/{ATTRIBUTION}", authority_is_ours=True,
                kind="DISAGREEMENT", step_id=d["step_id"], verdict=FAIL,
                message=(
                    f"two authorities judged ladder step {d['step_id']} on the "
                    f"same layout and reached opposite verdicts: "
                    f"{a['authority']} says {a['verdict']}, {b['authority']} "
                    f"says {b['verdict']}. One of the two checks is wrong, and "
                    f"which one is a finding about this plugin — it is NOT "
                    f"resolved here by preferring an arm"),
                detail=d))

    # ---------------- THE VERDICT -------------------------------------------
    rep.arms_expected = 1 + (0 if state == NOT_APPLICABLE else 1)
    rep.arms_ran = sum(1 for a in rep.arms if a.state == RAN)

    arm_verdicts = [a.verdict for a in rep.arms if a.state == RAN]
    any_fail = any(v == FAIL for v in arm_verdicts)
    any_undet = any(v == NOT_DETERMINED for v in arm_verdicts)
    arm_missing = [a for a in rep.arms
                   if a.state in (NOT_DETERMINED, ERROR)]

    if rep.disagreements:
        rep.verdict = FAIL
        rep.reason = (
            f"the two authorities disagree on "
            f"{len(rep.disagreements)} of the {len(rep.shared_ladder_steps)} "
            f"ladder step(s) they both judge: "
            + ", ".join(d["step_id"] for d in rep.disagreements)
            + ". A disagreement is not resolved by preferring an arm")
    elif any_fail:
        refusers = [a.authority for a in rep.arms if a.verdict == FAIL]
        rep.verdict = FAIL
        rep.reason = ("an arm refused this layout: " + ", ".join(refusers)
                      + " — each refusal is quoted from the authority that "
                        "produced it")
    elif arm_missing:
        rep.verdict = NOT_DETERMINED
        rep.reason = ("arm(s) reached no verdict: "
                      + ", ".join(f"{a.arm} ({a.state})" for a in arm_missing)
                      + ". An arm that did not run is not a pass")
    elif any_undet:
        undet = [a.authority for a in rep.arms if a.verdict == NOT_DETERMINED]
        rep.verdict = NOT_DETERMINED
        rep.reason = ("arm(s) ran and determined nothing: " + ", ".join(undet)
                      + ". A step that could not be evaluated is not a pass")
    else:
        rep.verdict = PASS
        rep.reason = (
            f"{rep.arms_ran} of {rep.arms_expected} expected arm(s) ran and "
            f"every one carries passing evidence for every ladder step"
            + (f"; the {len(rep.shared_ladder_steps)} step(s) both arms judge "
               f"agree" if their_doc is not None else
               "; the operator's arm is legitimately absent for this PDK"))
    return rep


def _write_non_run_record(out: Path, project: Path, pdk: Optional[str],
                          pdk_source: Optional[str], state: str, why: str,
                          shuttle: Any) -> None:
    """The operator arm's artefact on a path where the operator was NOT asked.

    Written under OUR attribution and saying so in three places — `authority`,
    `authority_is_ours`, and `verdict_is_the_operators: false` — because the one
    thing this file must never be mistaken for is a verdict the counterparty
    gave.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "project": str(project),
        # ERROR maps to NOT_DETERMINED, not to a fourth word. The three-verdict
        # rule is the whole reason this file reads the same as both arms'
        # reports; `arm_state` below carries the finer distinction for a reader
        # who wants it.
        "verdict": NOT_APPLICABLE if state == NOT_APPLICABLE
        else NOT_DETERMINED,
        "reason": why,
        "arm_state": state,
        "arm_ran": False,
        "authority": f"{OURS}/{ATTRIBUTION}",
        "authority_is_ours": True,
        "verdict_is_the_operators": False,
        "pdk": pdk,
        "pdk_source": pdk_source,
        "shuttle": (shuttle.shuttle_id if shuttle is not None else None),
        "steps": [],
        "emitted_by": _pmd.emitted_by(ATTRIBUTION),
    }
    atomic_write_text(out, json.dumps(payload, indent=2) + "\n",
                      encoding="utf-8")


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Step 37.5ic's gate: OUR general tape-out ladder on every "
                    "design, PLUS the shuttle operator's own container "
                    "whenever the PDK ships a precheck and its template was "
                    "fetched. PASS only when every arm that ran carries "
                    "passing evidence and the two agree; FAIL on any refusal "
                    "or any disagreement; NOT_DETERMINED whenever an arm "
                    "should have run and did not (rc 1, same as a refusal, "
                    "because a silence credited as a pass is the defect this "
                    "gate exists for).")
    p.add_argument("project", type=Path,
                   help="Project directory holding the finished layout.")
    p.add_argument("--pdk", default="",
                   help="Override the PDK; default is read from the design's "
                        "own declaration.")
    p.add_argument("--gds", type=Path, default=None, dest="layout",
                   help="Explicit layout file; default is discovered under "
                        "the project.")
    p.add_argument("--declaration", type=Path, default=None,
                   help="The tape-out declaration our arm compares against.")
    p.add_argument("--slot", default="",
                   help="Purchased slot size, passed to the operator's tool "
                        "verbatim. Default: read from the fetched template "
                        "(exactly one slots/*.yaml, or the declaration naming "
                        "one the template offers). There is NO fallback slot: "
                        "unresolved leaves the operator's arm NOT_DETERMINED "
                        "with that reason, because a guessed slot is answered "
                        "conclusively by the one arm we cannot edit.")
    p.add_argument("--cob", action="store_true",
                   help="Chip-on-board packaging: adds the operator's pad-mask "
                        "step to its ladder, exactly as its tool does.")
    p.add_argument("--top", default="",
                   help="Top-level cell name for the operator's arm.")
    p.add_argument("--id", default="", dest="die_id",
                   help="Die id passed through to the operator's tool.")
    p.add_argument("--image", default="",
                   help="Override the operator's precheck container image.")
    p.add_argument("--pull", action="store_true",
                   help="Attempt to pull that image when it is not local.")
    p.add_argument("--timeout", type=float, default=7200.0,
                   help="Seconds to allow each arm (default: %(default)s). A "
                        "real DRC ladder takes minutes to hours; a short "
                        "timeout reports zeros that look like success.")
    p.add_argument("--json", type=Path, dest="out_json", default=None,
                   help="Write the merged verdict JSON here (default: "
                        "<project>/" + MERGED_ARTEFACT + ").")
    args = p.parse_args(argv)

    if not args.project.is_dir():
        print(f"ERROR: project directory not found: {args.project}",
              file=sys.stderr)
        return 2

    rep = evaluate(project=args.project, pdk=args.pdk, layout=args.layout,
                   declaration_path=args.declaration, slot=args.slot,
                   cob=args.cob, top=args.top, die_id=args.die_id,
                   image=args.image, allow_pull=args.pull,
                   timeout=args.timeout)
    payload = rep.as_dict()
    out_json = args.out_json or (args.project / MERGED_ARTEFACT)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(out_json, json.dumps(payload, indent=2) + "\n",
                      encoding="utf-8")
    print(json.dumps(payload, indent=2))
    print(rep.summary_line())
    return 0 if rep.verdict == PASS else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
