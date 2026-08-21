#!/usr/bin/env python3
"""step_preflight.py — the ORCHESTRATOR side of `required_inputs`.

WHY THIS FILE EXISTS
====================
`step_required_inputs_check.py` landed the CAPABILITY: given a project and a
flow step id, it answers "are the artefacts this step reads on disk right now?"
Its own docstring says how it is meant to be used —

    "call it with `--step <id>` immediately before dispatching that step"

— and `grep -rl step_required_inputs_check` over the whole plugin found the
module, its test, and a comment. **No runner called it.** The check was
available; the BEHAVIOUR ("a step that cannot read anything must not produce a
verdict about what it produced") did not exist. This module is that behaviour.

WHERE THE STEPS ARE ACTUALLY DISPATCHED FROM, AND WHY THERE IS NO WRAPPER
========================================================================
Measured, not assumed:

    phase3_one_shot_runner   step_synth :10278  step_pnr :18550
                             step_gds   :23193  step_drc :24577  step_lvs :25245
    call sites               :37878 :37948 :38072 :38075 :38081
    design_one_shot_runner   step_rtl_gen :2854  step_yosys_synth :8363
                             step_dft_lec_chain :10816
    call sites               :12672 :12951 :13070
    analog_one_shot_runner   step_for_block — ONE function, dispatched once per
                             (block, A-step) from `main()`'s double loop
    phase1_one_shot_runner   _run_docs_mode / step_ingest_render — TWO mode
                             branches of `main()`, both executing canonical D1

Every one is a separate `plan.append(step_X(...))` inside `main()`. There is no
common wrapper, and THREE independent reasons say do not add one:

  1. The signatures and return types differ — `StepResult`,
     `Optional[StepResult]`, `List[StepResult]` — and each site is wrapped in
     its own cache / skip / re-run decision (`_nl_pdk_ok`, `_pnr_cache_valid_for`,
     `_producer_cache_valid_for`). A generic driver would have to re-implement
     all of it.
  2. `phase3_one_shot_runner` reads `plan[-1].status` IMMEDIATELY after several
     of these appends, and its own comments record what happened the last time
     an extra row appeared between an append and its reader ("the last row is
     no longer the PnR row … re-runs PnR, produces a NEW DEF and then SHIPS THE
     PREVIOUS DIE'S GDS"). A wrapper that appended a pre-flight row would
     reintroduce exactly that defect.
  3. The two runners own DIFFERENT `StepResult` dataclasses.

So: ONE shared decision function, called AT each call site, appending NOTHING.
`gate()` returns exactly one object — the step's own result, or the refusal
built by a caller-supplied factory — so `plan[-1]` keeps meaning what it meant.

THE MAPPING PROBLEM, STATED HONESTLY
====================================
The flow declares 63 steps. The runners dispatch ~8 coarse ones. `step_pnr` is
ONE OpenROAD session that covers canonical steps 15..22; `step_drc` and
`step_lvs` are two halves of canonical step 31. A runner call site therefore
executes a SPAN of flow steps, and this module is built on spans, not on a
1:1 pretence.

Three consequences, each of which was MEASURED before it was coded:

* ENTRY INPUTS ONLY. An input owed by a step INSIDE the same span is an
  intra-span handoff the call is about to create. Step 17 reads step 15's
  `pdn.tcl`; both are inside `step_pnr`. Charging that to the dispatch would
  refuse every PnR that ever ran.

* PRODUCER-DISCLOSED SKIPS ARE NOT ABSENCES. Step 15 declares it reads step
  12's `post_dft_netlist.v`. On a design with no scan chain, step 12 writes
  `post_dft_not_run.json` carrying `skips_required_output:
  phase2/stage2/synth/post_dft_netlist.v` and a registered capability flag, and
  `flow_compliance_check` already promotes that step to SKIPPED-CONDITION. The
  SAME function decides it here — `_declared_sibling_self_skip_for_missing` —
  so there is ONE notion of "the producer declared it would not write this".
  MEASURED on 3 real runs: without this, every one of them is refused at PnR.

* AN INPUT WHOSE PRODUCER HAS NOT RUN YET IS NOT AN ABSENCE. MEASURED:
  canonical step 9 (synthesis) declares it reads step 7's
  `phase2/stage2/constraints/*.sdc`, and in EVERY real run on this host that
  file is written MINUTES TO HOURS AFTER the synth netlist — by
  `step_canonicalize_artefacts`, at the TAIL of phase 3:

      subservient v1.5.85   netlist.v 23:33:08   constraints/*.sdc 00:05:07 (+32 min)
      ibex        v1.5.78   netlist.v 12:25:07   constraints/*.sdc 14:26:55 (+26 h)
      spm         v1.5.74   netlist.v 12:29:09   constraints/*.sdc 12:32:23 (+3 min)

  The flow's `blocks_on` says 7 precedes 9; the runner emits 7's artefact after
  9, 15, 17, 21, 31. A refusal there could NEVER be satisfied — step 9 would
  wait for a file step 7 only writes after step 9 — which is not a check, it is
  a brick. So it is classified `NOT-YET-DUE` and RECORDED as an
  ORDER-CONTRADICTION finding. It is not silently dropped: it is named, with
  both orders, in the run's own pre-flight ledger.

  "Due" is not hand-waved either: a producer is DUE when it is in an EARLIER
  site of this runner's own ordered plan, or in the plan of a runner this one
  INHERITS from (phase 3 runs on the tree phase 2 produced).

THE MAPPING IS FALSIFIABLE, NOT ASSERTED
========================================
A hand-authored span is a claim. `gate()` therefore VERIFIES it after the fact:
when the dispatched step reports PASS, the span's own `required_outputs` are
re-probed and the ledger records `identity: confirmed` or `unconfirmed` with
the paths that are still missing. A mapping that is wrong shows up in the run's
own artefacts instead of living forever as an unexamined constant.

WHAT REFUSES, AND WHAT DELIBERATELY DOES NOT
============================================
    REFUSED              >=1 DUE entry input is absent. The step is NOT called.
    READY                every DUE entry input is present.
    PRODUCER-SKIPPED     the only absences are producer-disclosed skips.
    NOT-JUDGED           every span member has an UNMET CONDITION — it will
                         not run at all, so nothing can starve it.
    WAIVED-ONLY          every span member is WAIVED. The step still RUNS, and
                         its inputs are still probed and recorded (states
                         `present-under-waiver` / `absent-under-waiver`) —
                         never charged. See `_probe_waived` for why both halves
                         of that are deliberate.
    UNDECLARED           the span declares no required_inputs at all — the data
                         dependency is UNKNOWN, not empty. Runs, and SAYS SO.
    NOT-YET-DUE          every declared entry input is owed by a step this
                         runner has not dispatched yet. Runs, and SAYS SO.
    UNAVAILABLE          the pre-flight itself could not run (flow unreadable,
                         PyYAML absent, a span naming an id the flow does not
                         have, a SELF-INCONSISTENT declaration). Runs, and says
                         so on stderr AND in the ledger. Set
                         `VIBE_IC_PREFLIGHT_STRICT=1` to make this refuse too.

There is NO switch that turns a refusal into a pass. `VIBE_IC_PREFLIGHT_STRICT`
only ever tightens. A run that cannot read its inputs is meant to stop.

WHERE THE REFUSAL IS RECORDED
=============================
`reports/audit/step_preflight.json` — an APPEND-ONLY ledger of every pre-flight
decision this project has seen, in dispatch order, each naming the site, the
flow steps it claims to execute, the verdict, every input probed with its
declared producer, and the identity confirmation. A phase2-then-phase3 chain
accumulates into one file.

The refusal ALSO becomes the step's own row in the runner's plan, with status
`BLOCKED` (already this vocabulary's word for "the check could not be
attempted because an INPUT could not support it … Never green") and
`extras.finding = "REQUIRED_INPUT_ABSENT"`. So a reader can tell

    BLOCKED / REQUIRED_INPUT_ABSENT   refused for want of input — never ran
    FAIL                              ran and did not pass
    MISSING (compliance)              ran and produced nothing

apart, which is the whole point.
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

LEDGER_REL = "reports/audit/step_preflight.json"
STRICT_ENV = "VIBE_IC_PREFLIGHT_STRICT"

# Statuses that must NOT reach a dispatched step. `BLOCKED` is the existing
# phase-3 vocabulary word, documented there as "never green"; `_aggregate_verdict`
# in both runners must group it with FAIL (design's did not, and its catch-all
# `return "PASS"` would have turned a refusal into a green run — fixed in the
# same change that added this module).
REFUSAL_STATUS = "BLOCKED"
REFUSAL_FINDING = "REQUIRED_INPUT_ABSENT"


# --------------------------------------------------------------------------- #
# The runner plans. ORDERED — the order IS the "has this producer run yet?"
# answer, and it is read off the runners' own `main()` bodies (line numbers in
# the module docstring). Every id is machine-checked against the flow.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class RunnerPlan:
    name: str
    # Steps produced by an EARLIER phase, before this runner starts.
    inherited_steps: Tuple[str, ...]
    # Another runner whose whole plan closure this one inherits.
    inherits: Optional[str]
    # ORDERED dispatch sites: (site name, flow step ids this site executes).
    sites: Tuple[Tuple[str, Tuple[str, ...]], ...]


RUNNER_PLANS: Dict[str, RunnerPlan] = {
    "design_one_shot_runner": RunnerPlan(
        name="design_one_shot_runner",
        # Phase 1 (`phase1_one_shot_runner` / the D1 doc-extraction track) has
        # already run when phase 2 starts.
        inherited_steps=("D1",),
        inherits=None,
        sites=(
            # main():12672 — plan.append(step_rtl_gen(project, ic_class))
            ("rtl_gen", ("1",)),
            # main():12951 — plan.append(step_yosys_synth(...))
            ("yosys_synth", ("9",)),
            # main():13070 — plan.extend(step_dft_lec_chain(...))
            ("dft_lec_chain", ("11", "12", "13")),
        ),
    ),
    "phase3_one_shot_runner": RunnerPlan(
        name="phase3_one_shot_runner",
        inherited_steps=(),
        inherits="design_one_shot_runner",
        sites=(
            # main():37878 — plan.append(step_synth(...))
            ("synth", ("9",)),
            # main():37948 — plan.append(step_pnr(...)). ONE OpenROAD session:
            # floorplan+PDN, clock plan, placement, spare cells, CTS, hold fix,
            # route, extraction.
            ("pnr", ("15", "16", "17", "18", "19", "20", "21", "22")),
            # main():38072 — plan.append(step_gds(...)). Stream-out only; metal
            # fill (step 34) is written by step_canonicalize_artefacts AFTER
            # drc/lvs — MEASURED (spm v1.5.74: lvs.rpt 12:32:23, filled.def
            # 12:32:34), which is why 34 is NOT in this span.
            ("gds", ("37",)),
            # main():38075 — plan.append(step_drc(...))
            ("drc", ("31",)),
            # main():38081 — plan.append(step_lvs(...))
            # Same canonical step as `drc`: 31 is DRC + LVS + ERC + Density and
            # this runner splits it across two dispatches.
            ("lvs", ("31",)),
        ),
    ),
    # ── THE OTHER TWO RUNNERS ────────────────────────────────────────────
    # `flow_gate_enforcement_audit` and `flow_step_executor_coverage_check`
    # both name FOUR one-shot runners. Two of them dispatched every step of
    # the A1-A9 / D1 line with no pre-flight at all — measured, at
    # 855504f5: `grep -c step_preflight` = 13 in design_one_shot_runner, 16
    # in phase3_one_shot_runner, 0 in each of these two. So a whole track
    # could be starved of its inputs and still report a verdict about what
    # it produced, which is the exact defect this module exists to remove.
    "analog_one_shot_runner": RunnerPlan(
        name="analog_one_shot_runner",
        # Phase 1 has already run when the analog track starts: A1 reads D1's
        # L1_DATASHEET.json + L5_ADI_SPEC.json.
        inherited_steps=("D1",),
        # NOT `inherits="design_one_shot_runner"`. The A-track runs PARALLEL to
        # Phase 2, not after it — `vibe_ic_one_shot_runner` drives it off the
        # analog block list, and a pure-analog cell has no Phase-2 digital track
        # at all. Declaring phase 2 as inherited would make every phase-2 step
        # "due" here and turn an honest NOT-YET-DUE into a REFUSED.
        inherits=None,
        # ORDERED, and the order is the runner's own `_AI_STEP_NAMES` tuple.
        # ONE canonical flow step per site: unlike `step_pnr`, no A-site covers
        # a span, so `identity` below is a full check rather than a partial one.
        sites=(
            ("A1", ("A1",)), ("A2", ("A2",)), ("A3", ("A3",)),
            ("A4", ("A4",)), ("A5", ("A5",)), ("A6", ("A6",)),
            ("A7", ("A7",)), ("A8", ("A8",)), ("A9", ("A9",)),
        ),
    ),
    "phase1_one_shot_runner": RunnerPlan(
        name="phase1_one_shot_runner",
        # Nothing precedes Phase 1. D1's inputs are the user's own staged
        # corpus, so `external` is the only producer it can have.
        inherited_steps=(),
        inherits=None,
        # ONE site, gated at BOTH of this dispatcher's mode branches (docs and
        # prompt). Two branches, one flow step, one question: was anything
        # staged for the extractor to read?
        sites=(("doc_extract", ("D1",)),),
    ),
}


def due_steps(runner: str, site: str) -> Tuple[frozenset, Optional[str]]:
    """Flow steps whose producer has ALREADY had its chance, at this site.

    = this runner's inherited closure + the spans of every EARLIER site.
    Returns (set, error)."""
    plan = RUNNER_PLANS.get(runner)
    if plan is None:
        return frozenset(), f"unknown runner {runner!r}"
    acc: set = set()
    seen: set = set()
    cur: Optional[RunnerPlan] = plan
    while cur is not None:
        if cur.name in seen:
            return frozenset(), f"cyclic `inherits` chain at {cur.name!r}"
        seen.add(cur.name)
        acc.update(cur.inherited_steps)
        if cur is not plan:
            for _n, span in cur.sites:
                acc.update(span)
        cur = RUNNER_PLANS.get(cur.inherits) if cur.inherits else None
    for n, span in plan.sites:
        if n == site:
            return frozenset(acc), None
        acc.update(span)
    return frozenset(), f"{runner} declares no site {site!r}"


# --------------------------------------------------------------------------- #
# Decision
# --------------------------------------------------------------------------- #
@dataclass
class Decision:
    runner: str
    site: str
    flow_steps: List[str]
    verdict: str = "UNAVAILABLE"
    allow: bool = True
    detail: str = ""
    inputs: List[Dict[str, Any]] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    project: str = ""
    at: str = ""
    identity: str = "not-checked"
    identity_missing: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "runner": self.runner, "site": self.site,
            "flow_steps": self.flow_steps, "verdict": self.verdict,
            "allow": self.allow, "detail": self.detail,
            "inputs": self.inputs, "notes": self.notes,
            "project": self.project, "at": self.at,
            "identity": self.identity,
            "identity_missing": self.identity_missing,
        }


def _unavailable(runner: str, site: str, span: Sequence[str],
                 why: str) -> Decision:
    strict = os.environ.get(STRICT_ENV, "").strip() not in ("", "0", "false")
    return Decision(
        runner=runner, site=site, flow_steps=list(span),
        verdict="UNAVAILABLE", allow=not strict,
        detail=(f"pre-flight could not run: {why}. Nothing was checked, so "
                f"nothing passed — this step's inputs are UNVERIFIED"
                + ("; refused because " + STRICT_ENV + " is set." if strict
                   else ".")),
        at=time.strftime("%Y-%m-%dT%H:%M:%S%z"))


def _probe_waived(project: Path, dec: Decision,
                  by_id: Dict[str, Dict[str, Any]],
                  waived: Sequence[str], span: Sequence[str]) -> int:
    """Probe a WAIVED span member's declared inputs. RECORDS; never refuses.

    WHY A WAIVED STEP IS STILL PRE-FLIGHTED
    =======================================
    Until this existed, a waived span member was DROPPED before any input was
    looked at, and a site whose whole span was waived returned NOT-JUDGED with
    the words "there is nothing to be starved of". That sentence is false, and
    the falsehood matters:

      * A WAIVER IS A STATEMENT ABOUT AN OUTPUT. `waivers.json` entries excuse a
        step from producing its `required_outputs` — "no FPGA board on this
        host", "PDK substituted". Not one of them says anything about whether
        the step's INPUTS were on disk. So dropping the step on sight answers a
        question nobody asked.
      * THE STEP STILL RUNS. The runners do not read `waivers.json`;
        `flow_compliance_check` does, at ACCEPTANCE time. So the dispatch this
        module gates happens either way — the step executes, reads (or fails to
        read) its inputs, and writes (or does not write) an artefact.
      * THE TWO FACTS ARE DIFFERENT, AND ONE HIDES THE OTHER. "waived for a
        stated reason" and "could not read its inputs" are not the same
        finding, and collapsing them means a run can be starved for its whole
        analog track while the ledger says the track was merely waived.

    AND WHY IT STILL MAY NOT REFUSE
    ===============================
    The opposite error is worse in the other direction. `waivers.json` is
    HUMAN-AUTHORED and only ever EXCUSES; if a waived step could be REFUSED,
    then authoring a waiver would newly BLOCK a step that runs today, i.e. an
    excuse would tighten the flow. That inverts the artefact's whole direction
    and is a way to fail a cell that was fine. So: probe, record, name the
    absences in the ledger, and let the step run.

    Returns the number of declared inputs found ABSENT (recorded, not charged).
    """
    if not waived:
        return 0
    try:
        import step_required_inputs_check as _ric   # noqa: PLC0415
        import flow_compliance_check as _fcc        # noqa: PLC0415
    except Exception:                               # pragma: no cover
        return 0
    absent = 0
    for sid in waived:
        for e in (by_id.get(sid, {}).get("required_inputs") or []):
            if str(e.get("from")) in span:
                continue
            if str(e.get("from")) == "external" and e.get("check") == "none":
                continue
            for producer, spec in _ric.expand(e, by_id):
                hits: List[str] = []
                for alt in (p.strip() for p in str(spec).split(" OR ")):
                    hits = _fcc._glob_first(project, alt)
                    if hits:
                        break
                present = bool(hits)
                if not present:
                    absent += 1
                dec.inputs.append({
                    "consumer": sid, "from": producer, "path": spec,
                    "present": present,
                    "evidence": hits[0] if hits else None,
                    "state": ("present-under-waiver" if present
                              else "absent-under-waiver"),
                    "waived": True,
                    "not_charged": ("this step is waived; the absence is "
                                    "RECORDED and deliberately NOT charged to "
                                    "the dispatch — a waiver excuses an output "
                                    "and cannot excuse, or create, a missing "
                                    "input"),
                })
    return absent


def decide(project: Path, runner: str, site: str,
           flow_def: Optional[Path] = None) -> Decision:
    """The pre-flight, for ONE dispatch site. Reads only; writes nothing."""
    plan = RUNNER_PLANS.get(runner)
    span: Tuple[str, ...] = ()
    if plan is not None:
        for n, s in plan.sites:
            if n == site:
                span = s
                break
    if plan is None or not span:
        return _unavailable(runner, site, span,
                            f"no declared site {runner}/{site}")

    try:
        import step_required_inputs_check as _ric   # noqa: PLC0415
        import flow_compliance_check as _fcc        # noqa: PLC0415
    except Exception as exc:                        # pragma: no cover
        return _unavailable(runner, site, span,
                            f"cannot import the checker: "
                            f"{type(exc).__name__}: {exc}")

    fd = Path(flow_def) if flow_def else Path(_ric.DEFAULT_FLOW_DEF)
    steps, err = _ric.load_flow(fd)
    if err:
        return _unavailable(runner, site, span, err)
    by_id = {str(s.get("id")): s for s in steps}

    missing_ids = [i for i in span if i not in by_id]
    if missing_ids:
        return _unavailable(
            runner, site, span,
            f"this site claims flow step(s) {missing_ids} which the flow does "
            f"not declare — the runner-to-flow map is stale")

    # The declaration must MEAN something before a verdict is computed from it.
    defects = _ric.declaration_defects(steps)
    if defects:
        return _unavailable(
            runner, site, span,
            "SELF-INCONSISTENT required_inputs declaration ("
            + "; ".join(f"{d['where']}: {d['defect']}" for d in defects[:3])
            + f"{'; …' if len(defects) > 3 else ''})")

    due, derr = due_steps(runner, site)
    if derr:
        return _unavailable(runner, site, span, derr)

    dec = Decision(runner=runner, site=site, flow_steps=list(span),
                   project=str(project),
                   at=time.strftime("%Y-%m-%dT%H:%M:%S%z"))

    shared = [n for n, s in plan.sites if n != site and set(s) & set(span)]
    if shared:
        dec.notes.append(
            f"this canonical step is split across {len(shared) + 1} dispatches "
            f"in this runner ({', '.join([site] + shared)}); `identity` below "
            f"is therefore PARTIAL for this site — the span's other half is "
            f"produced by the sibling dispatch, not by this one.")

    try:
        waivers = _fcc._load_waivers(project)
    except SystemExit as exc:
        # `_load_waivers` EXITS THE PROCESS on a malformed waivers.json. That is
        # right in `flow_compliance_check`, which is the waiver-schema auditor.
        # It is wrong HERE: this module runs at the FIRST dispatch of a run, and
        # killing the run over a defect in a file it neither owns nor audits
        # would be a brand-new failure mode introduced by a pre-flight. The
        # schema check still fires, byte-unchanged, where it belongs. The
        # pre-flight instead reports what is actually true — it could not decide
        # which span members are live — in its own existing word for that.
        return _unavailable(runner, site, span,
                            f"waivers.json could not be loaded ({exc}) — which "
                            f"span members are live is UNKNOWN, so no absence "
                            f"could be charged to this dispatch")
    live: List[str] = []
    waived: List[str] = []
    for sid in span:
        st = by_id[sid]
        cond = st.get("condition")
        if cond and not _fcc._check_condition(project, cond):
            dec.notes.append(f"step {sid}: condition not met ({cond}) — this "
                             f"span member will not run")
            continue
        try:
            wkey: Any = int(sid)
        except ValueError:
            wkey = sid
        if wkey in waivers:
            dec.notes.append(
                f"step {sid}: waived ("
                f"{waivers[wkey].get('reason', '(no reason)')}) — probed "
                f"anyway, see `state: *-under-waiver` below")
            waived.append(sid)
            continue
        live.append(sid)

    n_waived_absent = _probe_waived(project, dec, by_id, waived, span)
    if n_waived_absent:
        dec.notes.append(
            f"{n_waived_absent} declared input(s) of the WAIVED span member(s) "
            f"is/are ABSENT — recorded as `absent-under-waiver` and NOT charged "
            f"to this dispatch.")

    if not live:
        dec.allow = True
        if waived:
            # NOT "there is nothing to be starved of". A waived step still ran
            # and still read something; see `_probe_waived`.
            dec.verdict = "WAIVED-ONLY"
            dec.detail = (
                f"every flow step this site executes is WAIVED ({', '.join(waived)})"
                + (f" — and {n_waived_absent} of their declared input(s) is/are "
                   f"ABSENT, recorded but NOT charged: a waiver excuses an "
                   f"output, it cannot answer whether the step could read."
                   if n_waived_absent else
                   " — every declared input of those steps is nevertheless "
                   "PRESENT, so the waiver is the only reason nothing is "
                   "judged here."))
        else:
            dec.verdict = "NOT-JUDGED"
            dec.detail = ("every flow step this site executes has an unmet "
                          "condition — it will not run at all, so there is "
                          "nothing to be starved of.")
        return dec

    declared_any = False
    refusals: List[Dict[str, Any]] = []
    not_yet_due: List[Dict[str, Any]] = []
    producer_skipped: List[Dict[str, Any]] = []
    satisfied = 0

    for sid in live:
        for e in (by_id[sid].get("required_inputs") or []):
            declared_any = True
            src = str(e.get("from"))
            if src in span:
                dec.notes.append(
                    f"step {sid} <- step {src}: intra-span handoff, not an "
                    f"entry input — this dispatch produces it")
                continue
            if src == "external" and e.get("check") == "none":
                dec.inputs.append({
                    "consumer": sid, "from": "external", "path": None,
                    "present": None, "state": "unprobeable",
                    "what": e.get("what")})
                continue
            for producer, spec in _ric.expand(e, by_id):
                hits: List[str] = []
                for alt in (p.strip() for p in str(spec).split(" OR ")):
                    hits = _fcc._glob_first(project, alt)
                    if hits:
                        break
                item: Dict[str, Any] = {
                    "consumer": sid, "from": producer, "path": spec,
                    "present": bool(hits),
                    "evidence": hits[0] if hits else None,
                }
                if hits:
                    item["state"] = "present"
                    satisfied += 1
                    dec.inputs.append(item)
                    continue
                skip = None
                if producer != "external":
                    try:
                        skip = _fcc._declared_sibling_self_skip_for_missing(
                            project, [spec])
                    except Exception:
                        skip = None
                if skip:
                    item["state"] = "producer-skipped"
                    item["producer_skip_marker"] = skip
                    producer_skipped.append(item)
                elif producer != "external" and producer not in due:
                    item["state"] = "not-yet-due"
                    item["order_contradiction"] = (
                        f"the flow declares step {sid} reads step "
                        f"{producer}'s {spec}, but {runner} dispatches step "
                        f"{producer} AFTER this site (or not at all). The "
                        f"data graph and the runner's order disagree; the "
                        f"absence is NOT chargeable to this dispatch and was "
                        f"NOT checked.")
                    not_yet_due.append(item)
                else:
                    item["state"] = "absent"
                    refusals.append(item)
                dec.inputs.append(item)

    if refusals:
        dec.verdict = "REFUSED"
        dec.allow = False
        parts = []
        for r in refusals:
            owed = ("an EXTERNAL input" if r["from"] == "external"
                    else f"step {r['from']}")
            parts.append(f"{r['path']} (owed by {owed}, read by step "
                         f"{r['consumer']})")
        dec.detail = (
            f"REFUSED TO RUN: {len(refusals)} declared input(s) ABSENT — "
            + "; ".join(parts)
            + ". The step was NOT dispatched: it had nothing to read, so any "
              "verdict it produced about its own outputs would be a verdict "
              "about an absence upstream.")
    elif producer_skipped and satisfied == 0:
        dec.verdict = "PRODUCER-SKIPPED"
        dec.detail = (
            f"{len(producer_skipped)} declared input(s) absent because their "
            f"producer DISCLOSED a capability-flagged skip that owns exactly "
            f"that output; nothing else is missing.")
    elif not declared_any:
        dec.verdict = "UNDECLARED"
        dec.detail = (
            f"flow step(s) {live} declare NO required_inputs — this step's "
            f"data dependency is UNKNOWN, not empty. Nothing was checked, so "
            f"nothing passed; the step runs because an unknown dependency is "
            f"not an absent one.")
    elif satisfied == 0 and not_yet_due:
        dec.verdict = "NOT-YET-DUE"
        dec.detail = (
            f"every declared entry input ({len(not_yet_due)}) is owed by a "
            f"step this runner dispatches later — nothing was checkable here. "
            f"See `order_contradiction` on each input.")
    else:
        dec.verdict = "READY"
        bits = [f"{satisfied} declared input(s) present"]
        if producer_skipped:
            bits.append(f"{len(producer_skipped)} producer-disclosed skip(s)")
        if not_yet_due:
            bits.append(f"{len(not_yet_due)} not-yet-due (order contradiction)")
        dec.detail = "; ".join(bits) + "."
    return dec


# --------------------------------------------------------------------------- #
# Recording
# --------------------------------------------------------------------------- #
def ledger_path(project: Path) -> Path:
    return Path(project) / LEDGER_REL


def record(project: Path, dec: Decision) -> None:
    """Append `dec` to the run's own pre-flight ledger. NEVER raises.

    Best-effort in the WRITE direction only: a ledger that cannot be written
    must not kill a run. It can never turn a REFUSED into a run — `gate()` has
    already decided by the time this is called."""
    try:
        p = ledger_path(project)
        p.parent.mkdir(parents=True, exist_ok=True)
        doc: Dict[str, Any] = {}
        if p.is_file():
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                doc = {}
        if not isinstance(doc, dict) or not isinstance(doc.get("decisions"),
                                                       list):
            doc = {"program": "step_preflight", "decisions": []}
        doc["program"] = "step_preflight"
        doc["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        doc["contract"] = (
            "One record per DISPATCH. `verdict: REFUSED` means the step was "
            "NOT called because a declared input was absent — distinct from a "
            "step that ran and produced nothing. `identity` is INFORMATIONAL "
            "and never gates: it re-probes, after the fact, whether the flow "
            "steps this site CLAIMS to execute actually have their declared "
            "outputs, so a wrong runner-to-flow mapping is falsified by the "
            "run instead of living on as an unexamined constant. See the "
            "module docstring of programs/step_preflight.py for the full "
            "verdict vocabulary.")
        doc["decisions"].append(dec.as_dict())
        counts: Dict[str, int] = {}
        for d in doc["decisions"]:
            v = str(d.get("verdict"))
            counts[v] = counts.get(v, 0) + 1
        doc["counts"] = counts
        doc["refused"] = [
            {"runner": d.get("runner"), "site": d.get("site"),
             "flow_steps": d.get("flow_steps"),
             "absent": [i for i in (d.get("inputs") or [])
                        if i.get("state") == "absent"]}
            for d in doc["decisions"] if d.get("verdict") == "REFUSED"]
        p.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    except Exception:                                    # pragma: no cover
        pass


def _confirm_identity(project: Path, dec: Decision,
                      flow_def: Optional[Path] = None) -> None:
    """Falsify the hand-authored span: did this site actually produce what the
    flow steps it CLAIMS to execute declare as their outputs?"""
    try:
        import step_required_inputs_check as _ric      # noqa: PLC0415
        import flow_compliance_check as _fcc          # noqa: PLC0415
        fd = Path(flow_def) if flow_def else Path(_ric.DEFAULT_FLOW_DEF)
        steps, err = _ric.load_flow(fd)
        if err:
            dec.identity = "not-checked"
            return
        by_id = {str(s.get("id")): s for s in steps}
        missing: List[str] = []
        probed = 0
        for sid in dec.flow_steps:
            for spec in (by_id.get(sid, {}).get("required_outputs") or []):
                probed += 1
                ok = False
                for alt in (p.strip() for p in str(spec).split(" OR ")):
                    if _fcc._glob_first(project, alt):
                        ok = True
                        break
                if not ok:
                    missing.append(f"{sid}:{spec}")
        if not probed:
            dec.identity = "no-declared-outputs"
        elif missing:
            dec.identity = "unconfirmed"
            dec.identity_missing = missing
        else:
            dec.identity = "confirmed"
    except Exception:                                    # pragma: no cover
        dec.identity = "not-checked"


# --------------------------------------------------------------------------- #
# The gate itself
# --------------------------------------------------------------------------- #
#: THERE IS DELIBERATELY NO SWITCH FOR THIS (vibe-ic#1097 S7).
#:
#: The first version of this carried `VIBE_IC_REPRO_BUNDLE=0` as an opt-out.
#: `test_there_is_no_switch_that_turns_a_refusal_into_a_pass` failed it, and
#: that test is right: it bans EVERY `os.environ.get` in this module except
#: `STRICT_ENV`, on the grounds that "a weakening switch would make the refusal
#: decorative". My knob did not weaken the refusal — it only suppressed a
#: diagnostic — but the ban is deliberately blanket, and blanket is the correct
#: shape: it means nobody has to adjudicate "is THIS knob a weakening one?" per
#: knob, which is the judgement call that eventually goes wrong. Moving the
#: switch into `step_repro_bundle` to satisfy the ban's letter would be routing
#: around a gate.
#:
#: So there is no switch. The bundle is produced only on a refusal — already an
#: abnormal outcome someone is about to investigate — it is wrapped in the
#: never-raises guard below, and it writes under `reports/repro/`. If it ever
#: does need suppressing, that is a reviewed change, not a hidden knob.
def _emit_repro_bundle(project: Path, dec: "Decision") -> Optional[str]:
    """Bundle the refused span's declared inputs. Returns a path, or None.

    NEVER RAISES AND NEVER CHANGES A VERDICT. This runs on the refusal path, so
    every failure mode here — no flow, unwritable reports dir, a step with no
    `required_inputs` — must leave the refusal exactly as it was. A diagnostic
    that can convert a clean refusal into a crash is worse than no diagnostic:
    the caller would lose the finding it came to report.

    An INCOMPLETE bundle is still returned. On this path the inputs are absent
    BY CONSTRUCTION — that is what was refused — so "some of it is missing" is
    the evidence, not a reason to withhold it. The manifest inside the archive
    names every unresolved input, so the bundle states its own completeness.
    """
    steps = [str(s) for s in (dec.flow_steps or []) if str(s)]
    if not steps:
        return None
    try:
        from step_repro_bundle import write_bundle, DEFAULT_REL  # type: ignore
        out = (Path(project) / DEFAULT_REL /
               f"refused-{dec.site}-{'-'.join(steps)}.tar.gz")
        rep = write_bundle(Path(project), steps, out)
        if rep.get("verdict") == "REFUSED":
            return None
        print(f"[preflight] {dec.site}: repro bundle -> {out} "
              f"({len(rep.get('files', []))} input(s) present, "
              f"{len(rep.get('missing', []))} absent)",
              file=sys.stderr, flush=True)
        return str(out)
    except Exception as exc:                            # noqa: BLE001
        # Named, never silent — and never fatal.
        print(f"[preflight] {dec.site}: repro bundle NOT produced: "
              f"{type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return None


def gate(project: Path, runner: str, site: str,
         refusal_factory: Callable[[str, Dict[str, Any]], Any],
         fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Pre-flight `site`, then dispatch `fn` — or REFUSE and never call it.

    Appends NOTHING and returns EXACTLY ONE object, so a caller's `plan[-1]`
    idiom is untouched. `refusal_factory(detail, extras)` builds the caller's
    own `StepResult`-shaped refusal row.
    """
    flow_def = kwargs.pop("_preflight_flow_def", None)
    # WHICH INSTANCE of the site this dispatch was. `analog_one_shot_runner`
    # dispatches every A-site once PER BLOCK, so without this the ledger would
    # carry N identical `A2` records with no way to tell which block each was
    # about. Free text, recorded verbatim in `notes`, read by nothing and
    # therefore incapable of changing a verdict.
    note = kwargs.pop("_preflight_note", None)
    # The CALLER's own, already-existing applicability authority. Passed as a
    # non-empty REASON, never a bare bool, and recorded verbatim.
    #
    # WHY THIS IS NOT A WEAKENING SWITCH. Some steps are N/A for a whole class
    # of design and the flow yaml does not model it: a pure-analog IC has no
    # digital RTL track, so canonical step 1 produces no `phase2/stage1/rtl/*`
    # BY DESIGN, and `step_yosys_synth` already answers that with SKIP
    # ("deferred to the analog A1..A8 track"), which `flow_compliance` reads as
    # WAIVED. A pre-flight that refused there would convert a legitimate SKIP
    # into BLOCKED — breaking a run that legitimately skips steps, which is
    # forbidden. The applicability decision is NOT made here and NOT re-derived
    # here: the call site passes the reason produced by the runner's OWN
    # predicate (`_analog_rtl_track_absent`), the step still runs, and its own
    # not-applicable path owns the outcome. Nothing is silenced — the ledger
    # records verdict NOT-APPLICABLE with the reason.
    not_applicable = kwargs.pop("_preflight_not_applicable", None)
    if not_applicable:
        _p = RUNNER_PLANS.get(runner)
        _span = dict(_p.sites).get(site, ()) if _p else ()
        dec = Decision(runner=runner, site=site,
                       flow_steps=list(_span),
                       project=str(project),
                       at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                       verdict="NOT-APPLICABLE", allow=True,
                       detail=(f"not pre-flighted: the caller's own "
                               f"applicability predicate says this step has no "
                               f"honest work to do — {not_applicable}. The "
                               f"step still runs and its own skip path owns "
                               f"the outcome; no input was probed."))
        if note:
            dec.notes.append(str(note))
        print(f"[preflight] {site}: NOT-APPLICABLE — {not_applicable}",
              file=sys.stderr, flush=True)
        result = fn(*args, **kwargs)
        record(Path(project), dec)
        return result

    dec = decide(Path(project), runner, site, flow_def=flow_def)
    if note:
        dec.notes.append(str(note))

    if not dec.allow:
        print(f"[preflight] {site}: {dec.detail}", file=sys.stderr, flush=True)
        record(Path(project), dec)
        extras = {
            "finding": REFUSAL_FINDING,
            "preflight_verdict": dec.verdict,
            "flow_steps": dec.flow_steps,
            "absent_inputs": [i for i in dec.inputs
                              if i.get("state") == "absent"],
            "preflight_ledger": LEDGER_REL,
        }
        # vibe-ic#1097 (S7) — THE ONE MOMENT A REPRO BUNDLE IS WORTH MOST.
        # This is the single place the flow says "this step cannot read what
        # it was promised", and it is exactly the state a field agent then
        # spends a round trip reconstructing by hand. ORFS emits its issue
        # tarball on the same event (`flow/util/makeIssue.sh`).
        #
        # Wired HERE and not at the ~11 dispatch sites for the reason this
        # module exists: `gate()` is the ONE shared decision point, and it
        # appends nothing, so `plan[-1]` keeps meaning what it meant.
        bundle = _emit_repro_bundle(Path(project), dec)
        if bundle:
            extras["repro_bundle"] = bundle
        return refusal_factory(dec.detail, extras)

    if dec.verdict != "READY":
        # Never silent: UNDECLARED / NOT-YET-DUE / UNAVAILABLE are all "this
        # was not checked", and a reader must see that on the console too.
        print(f"[preflight] {site}: {dec.verdict} — {dec.detail}",
              file=sys.stderr, flush=True)

    result = fn(*args, **kwargs)

    status = getattr(result, "status", None)
    if status is None and isinstance(result, (list, tuple)):
        status = "PASS" if any(getattr(r, "status", "") == "PASS"
                               for r in result) else None
    if status == "PASS":
        _confirm_identity(Path(project), dec, flow_def=flow_def)
    else:
        dec.identity = "not-applicable"
    record(Path(project), dec)
    return result


# --------------------------------------------------------------------------- #
# Self-check CLI: `python3 step_preflight.py <project> [--runner R] [--site S]`
# --------------------------------------------------------------------------- #
def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="Pre-flight a runner dispatch site (read-only).")
    ap.add_argument("project", nargs="?", default=".", type=Path)
    ap.add_argument("--runner", default=None)
    ap.add_argument("--site", default=None)
    ap.add_argument("--flow-def", type=Path, default=None)
    ap.add_argument("--json", type=Path, default=None)
    a = ap.parse_args(argv)

    pairs = [(r, s) for r, p in RUNNER_PLANS.items() for s, _ in p.sites
             if (a.runner in (None, r) and a.site in (None, s))]
    if not pairs:
        print("step_preflight: no such runner/site", file=sys.stderr)
        return 2
    out = []
    rc = 0
    for r, s in pairs:
        d = decide(a.project.resolve(), r, s, flow_def=a.flow_def)
        out.append(d.as_dict())
        print(f"[{d.verdict:16}] {r}/{s} {d.flow_steps} — {d.detail}")
        if d.verdict == "REFUSED":
            rc = 1
        elif d.verdict == "UNAVAILABLE" and rc == 0:
            rc = 2
    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(json.dumps({"decisions": out}, indent=2) + "\n",
                          encoding="utf-8")
    return rc


if __name__ == "__main__":
    sys.exit(main())
