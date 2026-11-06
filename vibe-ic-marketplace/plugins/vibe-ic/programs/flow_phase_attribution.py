#!/usr/bin/env python3
"""Describe Router decisions, RTL authorship, and native tool results.

The native engine report defines the executed window. The frontend report
adds the RTL authoring result used by Program First and its AI backup.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
import verdict as _V  # noqa: E402  R-0915-85 — the one vocabulary module

SCHEMA = 2
REPORT_NAME = "flow_phase_attribution.json"

_STEP_REPORT = ("reports", "orchestrator", "phase2_one_shot.json")

# The runner's status vocabulary, RE-PARTITIONED for the question this module
# asks. `design_one_shot_runner._aggregate_verdict` partitions the same
# statuses into FAIL / GREEN / SKIP / WAIVED because it is deciding a verdict;
# this module is deciding whether a gate was ATTEMPTED, which cuts the same set
# differently (BLOCKED is a FAIL for the verdict and a NOT-ATTEMPTED here — the
# step refused to run). The two partitions must stay TOTAL over the same
# vocabulary: anything outside lands in `unclassified_status` BY NAME, the same
# refusal-to-absorb that function makes, so a status invented tomorrow cannot
# arrive here as a silent pass or a silent skip.
# R-0915-85 — DERIVED FROM THE FIVE, and the partition is still TOTAL.
#
# `FAIL_RTL_REPAIR_INERT`, `STALE_BOARD_DETECTED` and `ADVISORY` were three
# spellings of "it ran"; `SKIP`, `SKIPPED-CONDITION`, `SKIPPED-BY-ENTRY`,
# `SKIPPED-BY-EXIT`, `BLOCKED` and `WAIVED` were six spellings of "it did not".
# The question this module asks -- WAS THE GATE ATTEMPTED -- cuts the five the
# same way it cut the eighteen:
#   * PASS / PASS_WITH_WAIVERS / FAIL -- the step produced a verdict about the
#     design. A waived step RAN; what is open is a row somebody owns, and that
#     row is in `waiver_rows`, not in the word.
#   * NOT_MEASURED / NOT_APPLICABLE -- nothing was measured, whether because
#     the run declared the site out of scope or because the step could not
#     look. WHICH of those is in `reason_class` / `declared_by`, published
#     beside the word, so nothing that used to be a separate word goes silent.
# Anything else still lands in `unclassified_status` BY NAME -- and `parse`
# now refuses it upstream too, so an un-migrated producer cannot arrive here
# as a silent pass or a silent skip.
_STATUS_RAN = frozenset({_V.Verdict.PASS.value,
                         _V.Verdict.PASS_WITH_WAIVERS.value,
                         _V.Verdict.FAIL.value})
_STATUS_NOT_ATTEMPTED = frozenset({_V.Verdict.NOT_MEASURED.value,
                                   _V.Verdict.NOT_APPLICABLE.value})
# R-0915-85 — A MARKER IS A DISCLOSURE, NOT A VERDICT. `RTL_REPAIR_RETRY` was
# a status word for "this row is a progress marker inside an iteration", which
# put a non-outcome in the field every consumer reads for an outcome. The
# runner records the marker as `PASS` carrying `Disclosure.PROGRESS_MARKER`
# now, so the question is asked of the disclosures. Left as the word this set
# matched NOTHING and every marker row fell through to `ran`, where it counted
# as a gate that produced a verdict about the design.
_MARKER_DISCLOSURE = _V.Disclosure.PROGRESS_MARKER.value


def _is_progress_marker(step: Dict[str, Any]) -> bool:
    """This row records that an iteration advanced, not that a gate decided."""
    return _MARKER_DISCLOSURE in [
        str(d) for d in (step.get("disclosures") or ())]
_STATUS_FAILING = (_V.Verdict.FAIL.value,)

# Repair / close-loop markers the runner appends, by the name it records them
# under. Each value says what the marker IS, so the report explains itself.
_REPAIR_MARKERS = {
    "rtl_repair_retry_iter":
        "the bounded RTL repair/retry marker design_one_shot_runner appends when the "
        "reference-TB step FAILs, before re-running rtl_gen",
    "rtl_repair_remediation":
        "the hint-driven Phase-1 regeneration the RTL repair/retry loop attempts once "
        "before it declares the loop inert",
}
_REPAIR_EXTRA_KEY = "gate_directed_repairs"

# The Path-A input the runner itself detects, in the order a reader should try.
_PROMPT_CANDIDATES = (("input", "phase1_prompt.md"),
                      ("input", "docs", "design_description.md"))


def _unknown(reason: str) -> Dict[str, Any]:
    return {"attributed": False, "verdict": "UNKNOWN", "reason": reason}


def _read_json(p: Path) -> Any:
    try:
        return json.loads(Path(p).read_text(errors="replace"))
    except (OSError, ValueError):
        return None


def step_report(project: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Read the native engine's selected window and the frontend's RTL result."""
    project = Path(project)
    engine = _read_json(project / "reports/flow_engine.json")
    owner = _read_json(project.joinpath(*_STEP_REPORT))
    if isinstance(engine, dict) and isinstance(engine.get("steps"), list):
        rows = list(engine["steps"])
        if isinstance(owner, dict):
            rows += [row for row in owner.get("steps", [])
                     if row.get("name") in {"rtl_gen", "rtl_validate"}]
        return {**engine, "steps": rows,
                "native_selected_steps": engine.get("selected", 0),
                "native_steps_recorded": len(engine["steps"])}, None
    if isinstance(owner, dict) and isinstance(owner.get("steps"), list):
        return owner, None
    return None, "The runner reported no native tool results."



def _prompt_text(project: Path) -> Tuple[Optional[str], Optional[str]]:
    project = Path(project)
    for parts in _PROMPT_CANDIDATES:
        p = project.joinpath(*parts)
        if p.is_file():
            try:
                return p.read_text(errors="replace"), "/".join(parts)
            except OSError:
                continue
    return None, None


# The canonical directories a design's INPUT RTL arrives in. `input/rtl/` is the
# declared one; `rtl/` is the one the rest of this plugin ALSO reads as input --
# phase1_doc_one_shot_runner's top-module extractor iterates
# `(project/"input"/"rtl", project/"rtl")`, and phase3_one_shot_runner's
# clock-port scanner lists `rtl/` among its search roots. Reading only the first
# of the two made this detector the odd one out, and a design staged at `rtl/`
# was reported as arriving with no RTL at all.
#
# The emit directory `phase2/stage1/rtl/` is deliberately NOT a member: RTL this
# run PRODUCED is not RTL the design ARRIVED with, and admitting it would make
# the signal true for every project after Phase 2 has run.
_INPUT_RTL_DIRS: Tuple[Tuple[str, ...], ...] = (("input", "rtl"), ("rtl",))
_RTL_SUFFIXES = (".v", ".sv", ".vh", ".svh")


def rtl_present_at_input(project: Path) -> bool:
    """Did the design ARRIVE with RTL? The router's `has_context` signal.

    This is the difference between "a spec asking for new RTL" and "a transform
    on RTL that already exists", and it is the one input the router cannot
    infer from prose. `classify_task_nature` states the consequence of getting
    it wrong: "never promote a context-bearing task to spec_generation -- that
    is the mistake that pushes a debug task through Phase 1." A blind detector
    makes exactly that mistake, silently, on every design whose RTL was staged
    anywhere but `input/rtl/`.

    A file is RTL by SUFFIX, not by living in a directory called `rtl`: a
    README or a manifest dropped beside the sources does not mean the design
    arrived with a module to transform.
    """
    project = Path(project)
    for parts in _INPUT_RTL_DIRS:
        d = project.joinpath(*parts)
        if not d.is_dir():
            continue
        for f in d.rglob("*"):
            if f.is_file() and f.suffix.lower() in _RTL_SUFFIXES:
                return True
    return False


def derive_routing(project: Path) -> Dict[str, Any]:
    """Route this project the way any caller of the flow would route it.

    An adapter that has ALREADY routed passes its own verdict to `attribute`
    instead, because a second derivation is a second answer. A plain design has
    no such caller, so the routing is taken here — from the same function, on
    the same two inputs (the project's prompt and whether it arrived with RTL).
    """
    text, src = _prompt_text(project)
    if text is None:
        return {"verdict": None,
                "why": ("no Path-A input is present: none of "
                        + ", ".join("/".join(c) for c in _PROMPT_CANDIDATES)
                        + " exists, so there is no prompt to route")}
    try:
        import task_nature_route as tnr                   # noqa: PLC0415
    except Exception as exc:                              # noqa: BLE001
        return {"verdict": None,
                "why": f"task_nature_route is unimportable: "
                       f"{type(exc).__name__}: {exc}"}
    has_ctx = rtl_present_at_input(project)
    verdict = tnr.classify_task_nature(text, has_ctx, None)
    # `entry_nature` is the NATURE_ENTRY key on every branch; `nature` may be
    # the disclosing unpinned-transform label, which is not.
    entry_row = tnr.NATURE_ENTRY[verdict["entry_nature"]]
    entry = entry_row.get("entry_step")
    ev = entry_row.get("default_evidence")
    exit_step = (tnr.EVIDENCE_EXIT.get(ev) or {}).get("exit_step")
    return {"verdict": verdict, "entry": entry, "evidence": ev,
            "exit_step": exit_step, "rtl_present": has_ctx,
            "prompt_source": src, "why": None}


def phase1_routing(verdict: Optional[Dict[str, Any]], entry: Any, evidence: Any,
                   exit_step: Any, rtl_present: Optional[bool],
                   why: Optional[str] = None,
                   derived_here: bool = False) -> Dict[str, Any]:
    """WHO routed, and on what evidence — the router's own return value.

    `task_nature_route.classify_task_nature` returns {nature, entry_nature,
    route, plugin_entry, source, needs_ai_parse} and, on exactly one branch, a
    `warning`. Callers recorded the nature and threw the rest away; `source` is
    the difference between "a structural heuristic decided" and "prose said
    so", and `needs_ai_parse` is the router telling every caller that the
    structural verdict has not been confirmed by the AI first-layer parse.
    Measured on all 156 VerilogEval-Human prompts: `needs_ai_parse` is True for
    every one of them and nothing consumes it.

    `warning` is null when the classifier emitted none — an observation, not a
    default: the key is set on one branch only (prose hint without context).
    """
    if not isinstance(verdict, dict):
        return _unknown(f"phase-1 routing cannot be attributed: "
                        f"{why or 'no router verdict was supplied or derivable'}")
    return {
        "attributed": True,
        "actor": "task_nature_route.classify_task_nature",
        "mechanism": "PROGRAM",
        "verdict_source": ("DERIVED_HERE from the project's own input"
                           if derived_here else
                           "SUPPLIED by the caller that routed this run"),
        "nature": verdict.get("nature"),
        "entry_nature": verdict.get("entry_nature"),
        "route": verdict.get("route"),
        "plugin_entry": verdict.get("plugin_entry"),
        "source": verdict.get("source"),
        "needs_ai_parse": verdict.get("needs_ai_parse"),
        "needs_ai_parse_consumed_by":
            "NOTHING in a standalone runner invocation — a benchmark "
            "dispatcher may attach a blind Program First AI review; recorded "
            "here as disclosure, not as a decision",
        "warning": verdict.get("warning"),
        "rtl_present_at_input": rtl_present,
        "entry_step": entry,
        "evidence_class": evidence,
        "exit_step": exit_step,
    }


def _earlier_waive(rep: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The FIRST rtl_gen WAIVE to a skill, if the run ever waived.

    Scans EVERY rtl_gen, not just the last, so a run that waived and then
    emitted on a later attempt can show both facts instead of one winning.
    """
    for st in rep.get("steps") or []:
        if (st.get("name") == "rtl_gen"
                and st.get("status") == _V.Verdict.PASS_WITH_WAIVERS.value):
            ex = st.get("extras") or {}
            if ex.get("fallback_skill"):
                return {"fallback_skill": ex["fallback_skill"],
                        "detail": str(st.get("detail") or "")[:300]}
    return None


def phase2_solving(rep: Optional[Dict[str, Any]], why: Optional[str],
                   artefact_collected: Optional[bool] = None,
                   project: Optional[Path] = None) -> Dict[str, Any]:
    """WHO wrote the RTL, BY NAME.

    "a program did it" is not an attribution — 32 distinct emitters fired
    across one 156-design sweep and the run could not say which. The emitter
    name is already in the step record (`extras.deterministic_generator`, set
    by every deterministic producer in the runner), and the emitters the chain
    REFUSED are in `extras.rejected_emitters` / `rejected_rules`. Both are read
    here; neither is re-derived by calling the chain a second time.

    The last `rtl_gen` step describes the current dispatch. A handoff names
    the backup skill. Reporting does not infer authorship from old records.

    `artefact_collected` is a claim about a SCORER's collector, not about the
    design. It is optional and its absence is recorded as an absence.
    """
    if rep is None:
        return _unknown(f"phase-2 solving cannot be attributed: {why}")
    steps = rep.get("steps") or []
    attempts = [s for s in steps if s.get("name") == "rtl_gen"]
    if not attempts:
        return _unknown("phase-2 solving cannot be attributed: the run "
                        "recorded no `rtl_gen` step at all")

    rejected: List[Dict[str, Any]] = []
    for i, s in enumerate(attempts):
        ex = s.get("extras") or {}
        if ex.get("rejected_emitters"):
            rejected.append({"attempt": i + 1,
                             "emitters": ex.get("rejected_emitters"),
                             "rules": ex.get("rejected_rules"),
                             "detail": str(s.get("detail") or "")[:300]})

    last = attempts[-1]
    ex = last.get("extras") or {}
    status = str(last.get("status"))
    detail = str(last.get("detail") or "")
    out: Dict[str, Any] = {
        "attributed": True,
        "attempts": len(attempts),
        "attempt_statuses": [str(s.get("status")) for s in attempts],
        "status": status,
        "rejected": rejected,
    }
    if artefact_collected is None:
        out["artefact_collected"] = {
            "known": False,
            "reason": "no collector verdict was supplied; whether a scorer "
                      "would collect this artefact is not a property of the "
                      "design and is never guessed from the tree",
        }
    else:
        out["artefact_collected"] = bool(artefact_collected)

    gen = ex.get("deterministic_generator")
    if status == "PASS" and gen:
        out.update({
            "solved_by": "EMITTER",
            "mechanism": "PROGRAM",
            "actor": ("deterministic_emit_chain"
                      if "deterministic_emit_chain[" in detail else "runner"),
            "emitter": gen,
            "evidence": f"rtl_gen PASS with extras.deterministic_generator="
                        f"{gen!r}",
        })
    elif status == "PASS":
        out.update({
            "solved_by": "PROGRAM_UNNAMED",
            "mechanism": "PROGRAM",
            "actor": "UNKNOWN",
            "emitter": "UNKNOWN",
            "evidence": f"rtl_gen PASS but its step record names no "
                        f"`deterministic_generator`; extras keys present: "
                        f"{sorted(ex)}; detail: {detail[:200]}",
        })
    elif status == _V.Verdict.PASS_WITH_WAIVERS.value:
        # R-0915-85 — `WAIVED` is `PASS_WITH_WAIVERS`. Dead as the old word,
        # this branch never fired and every waived-to-a-skill run fell through
        # to `_unknown`: the attribution said the vocabulary was unclassified
        # about the one hand-off it exists to name.
        skill = ex.get("fallback_skill")
        out.update({
            "solved_by": "AI_BACKUP" if skill else "WAIVED_NO_SKILL",
            "mechanism": "AI_HANDOFF" if skill else "NONE",
            "actor": skill or "UNKNOWN",
            "emitter": None,
            "emitter_absent_reason":
                "no deterministic emitter fired; the runner passed rtl_gen "
                "WITH WAIVERS to "
                f"the AI skill {skill!r} — a handover, not an emit"
                if skill else
                f"rtl_gen PASS_WITH_WAIVERS with no fallback_skill: "
                f"{detail[:200]}",
            "ai_authored_in_this_invocation": False,
            "evidence": f"rtl_gen PASS_WITH_WAIVERS, "
                        f"extras.fallback_skill={skill!r}",
        })
    # R-0915-85 — `BLOCKED` is `NOT_MEASURED(input_absent)`, which the
    # NOT-ATTEMPTED arm below already owns. It is dropped here rather than
    # translated: a step that could not look is not a step that looked and
    # found nothing, and this branch is the second.
    elif status == _V.Verdict.FAIL.value:
        out.update({
            "solved_by": "NONE",
            "mechanism": "PROGRAM",
            "actor": "runner",
            "emitter": None,
            "emitter_absent_reason": f"rtl_gen reported {status}: "
                                     f"{detail[:200]}",
            "finding": ex.get("finding"),
            "evidence": f"rtl_gen {status}",
        })
    elif status in _STATUS_NOT_ATTEMPTED:
        out.update({
            "solved_by": "NONE",
            "mechanism": "NONE",
            "actor": None,
            "emitter": None,
            "emitter_absent_reason": f"rtl_gen {status}: {detail[:200]}",
            "evidence": f"rtl_gen {status}",
        })
    else:
        return _unknown(f"phase-2 solving cannot be attributed: the last "
                        f"rtl_gen carries status {status!r}, which is outside "
                        f"the runner's classified status vocabulary; detail: "
                        f"{detail[:200]}")

    waive = _earlier_waive(rep)
    if (waive and out.get("solved_by") != "AI_BACKUP"
            and not out.get("reused")):
        # A run that waived and then emitted on a later attempt shows both.
        # Say so instead of letting one of the two facts win silently.
        out["earlier_waive_to"] = waive.get("fallback_skill")
    return out


def phase3_verifying(rep: Optional[Dict[str, Any]],
                     why: Optional[str]) -> Dict[str, Any]:
    """Report the tool statuses from the runner's selected window."""
    if rep is None:
        return _unknown(why or "No native tool results.")
    ran, not_attempted, markers, unclassified, repeats = {}, {}, {}, {}, {}
    for row in rep.get("steps", []):
        name, status = str(row.get("name")), str(row.get("status"))
        repeats[name] = repeats.get(name, 0) + 1
        if _is_progress_marker(row):
            markers[name] = status
        elif status in _STATUS_RAN:
            ran[name] = status
        elif status in _STATUS_NOT_ATTEMPTED:
            not_attempted[name] = status
        else:
            unclassified[name] = status
    return {"attributed": True, "source": "native runner reports",
            "run_verdict": rep.get("verdict"), "ran": ran,
            "failed": sorted(name for name, status in ran.items() if status == "FAIL"),
            "not_attempted": not_attempted, "markers": markers,
            "unclassified_status": unclassified,
            "selected_steps": rep.get("native_selected_steps", 0),
            "steps_recorded": rep.get("native_steps_recorded", len(rep.get("steps", []))),
            "steps_recorded_more_than_once": {name: count for name, count in repeats.items() if count > 1}}



def phase4_debugging(rep: Optional[Dict[str, Any]],
                     why: Optional[str]) -> Dict[str, Any]:
    """WHETHER RTL was repaired/retried, its trigger, and whether it mattered.

    Recorded NOWHERE before. The evidence was always in the step list — the repair
    markers, and the `gate_directed_repairs` extras — and no consumer read it,
    so a design that was BLOCKED, close-looped and then emitted looked exactly
    like a design that emitted first time. None of these events is a
    physical/metal ECO.

    Mechanism is read off the step the runner recorded IMMEDIATELY AFTER the
    marker (that is the repair action the loop actually took), never assumed
    from the marker's name.
    """
    if rep is None:
        return _unknown(f"phase-4 debugging cannot be attributed: {why}")
    steps = rep.get("steps") or []
    events: List[Dict[str, Any]] = []
    for i, s in enumerate(steps):
        name = str(s.get("name"))
        ex = s.get("extras") or {}
        if name in _REPAIR_MARKERS:
            prev = steps[i - 1] if i else None
            prev_status = str(prev.get("status")) if prev else "UNKNOWN"
            if prev_status in _STATUS_NOT_ATTEMPTED:
                event_kind = "RTL_RETRY"
            elif prev_status in _STATUS_FAILING:
                event_kind = "RTL_REPAIR"
            else:
                event_kind = "RTL_REPAIR_OR_RETRY"
            nxt = steps[i + 1] if i + 1 < len(steps) else None
            nxt_ex = (nxt.get("extras") or {}) if nxt else {}
            if nxt is None:
                mech, mech_ev = "UNKNOWN", ("the marker is the last recorded "
                                            "step, so no repair action was "
                                            "recorded after it")
            elif nxt.get("name") == "rtl_gen" and nxt_ex.get("fallback_skill"):
                mech = "AI_HANDOFF"
                mech_ev = (f"the step recorded immediately after the marker is "
                           f"rtl_gen WAIVED to skill "
                           f"{nxt_ex.get('fallback_skill')!r}")
            elif nxt.get("name") == "rtl_gen":
                mech = "PROGRAM"
                mech_ev = (f"the step recorded immediately after the marker is "
                           f"rtl_gen, a runner program step (status "
                           f"{nxt.get('status')}"
                           + (f", deterministic_generator="
                              f"{nxt_ex['deterministic_generator']!r}"
                              if nxt_ex.get("deterministic_generator") else "")
                           + ")")
            else:
                mech, mech_ev = "UNKNOWN", (
                    f"the step recorded immediately after the marker is "
                    f"{nxt.get('name')!r} ({nxt.get('status')}), which is not "
                    f"a repair action this reader can name")
            events.append({
                "index": i,
                "step": name,
                "status": str(s.get("status")),
                "what_it_is": _REPAIR_MARKERS[name],
                "event_kind": event_kind,
                "physical_eco": False,
                "terminology": ("RTL repair/retry; legacy internal eco_loop "
                                "marker only, not a physical/metal ECO"),
                "triggered_by": ({"step": str(steps[i - 1].get("name")),
                                  "status": str(steps[i - 1].get("status"))}
                                 if i else
                                 {"step": "UNKNOWN",
                                  "reason": "the marker is the first recorded "
                                            "step, so nothing precedes it"}),
                "repair_action": ({"step": str(nxt.get("name")),
                                   "status": str(nxt.get("status"))}
                                  if nxt else None),
                "mechanism": mech,
                "mechanism_evidence": mech_ev,
                "detail": str(s.get("detail") or "")[:300],
            })
        if ex.get(_REPAIR_EXTRA_KEY):
            events.append({
                "index": i,
                "step": name,
                "status": str(s.get("status")),
                "what_it_is": f"the step recorded extras.{_REPAIR_EXTRA_KEY}, "
                              f"the record gate_directed_rtl_repair writes "
                              f"when it applies a deterministic repair",
                "event_kind": "RTL_REPAIR",
                "physical_eco": False,
                "terminology": "deterministic RTL repair, not physical ECO",
                "triggered_by": {"step": name,
                                 "status": str(s.get("status")),
                                 "note": "the repair is recorded on the "
                                         "failing step itself"},
                "repair_action": {"step": name, "status": str(s.get("status"))},
                "mechanism": "PROGRAM",
                "mechanism_evidence": f"extras.{_REPAIR_EXTRA_KEY} is written "
                                      f"by gate_directed_rtl_repair, a program",
                "repairs": ex.get(_REPAIR_EXTRA_KEY),
            })

    rtl_steps = [(i, s) for i, s in enumerate(steps)
                 if s.get("name") == "rtl_gen"]
    last_rtl = str(rtl_steps[-1][1].get("status")) if rtl_steps else None
    if not events:
        if last_rtl is None:
            reason = ("no repair or close-loop step is recorded, and neither "
                      "is any rtl_gen step — nothing to repair was recorded")
        elif last_rtl == "PASS" and len(rtl_steps) == 1:
            reason = ("passed first time: rtl_gen PASSed on its only attempt "
                      "and no close-loop marker or gate-directed repair is "
                      "recorded")
        else:
            reason = (f"no repair path fired for this failure: rtl_gen reached "
                      f"{last_rtl} in {len(rtl_steps)} attempt(s) and the run "
                      f"records no {sorted(_REPAIR_MARKERS)} marker and no "
                      f"extras.{_REPAIR_EXTRA_KEY}")
        return {"attributed": True, "fired": False, "verdict": "NONE",
                "reason": reason}

    first = min(e["index"] for e in events)
    before = None
    for i, s in rtl_steps:
        if i < first:
            before = str(s.get("status"))
    if before is None or last_rtl is None:
        changed = {"changed": "UNKNOWN",
                   "reason": "no rtl_gen status was recorded on both sides of "
                             "the first repair marker, so whether the repair "
                             "changed the verdict cannot be observed"}
    else:
        changed = {"changed": before != last_rtl,
                   "basis": "rtl_gen status recorded before the first repair "
                            "marker vs the last rtl_gen status recorded",
                   "before": before, "after": last_rtl}
    event_kinds = {e.get("event_kind") for e in events}
    if event_kinds == {"RTL_RETRY"}:
        phase_verdict = "RETRIED"
    elif event_kinds <= {"RTL_REPAIR"}:
        phase_verdict = "REPAIRED"
    else:
        phase_verdict = "REPAIRED_AND_RETRIED"
    return {"attributed": True, "fired": True, "verdict": phase_verdict,
            "physical_eco": False,
            "events": events, "verdict_change": changed}


def attribute(project: Path,
              routing: Optional[Dict[str, Any]] = None,
              entry: Any = None,
              evidence: Any = None,
              exit_step: Any = None,
              rtl_present: Optional[bool] = None,
              artefact_collected: Optional[bool] = None) -> Dict[str, Any]:
    """All four phases for ONE design, every field observed.

    `routing` is the router verdict the CALLER already took, when there is one:
    an adapter that routed the design before invoking the runner passes its own
    return value so this module never produces a second answer to a question
    already answered. When it is absent — the plain case, a user running the
    runner directly — the routing is derived here from the project's own input.
    """
    rep, why = step_report(project)
    derived = False
    if routing is None:
        d = derive_routing(project)
        routing = d.get("verdict")
        derived = routing is not None
        if entry is None:
            entry = d.get("entry")
        if evidence is None:
            evidence = d.get("evidence")
        if exit_step is None:
            exit_step = d.get("exit_step")
        if rtl_present is None:
            rtl_present = d.get("rtl_present")
        route_why = d.get("why")
    else:
        route_why = None
    if rtl_present is None:
        rtl_present = rtl_present_at_input(project)
    return {
        "schema": SCHEMA,
        "project": str(project),
        "phase1_routing": phase1_routing(routing, entry, evidence, exit_step,
                                         rtl_present, route_why, derived),
        "phase2_solving": phase2_solving(rep, why, artefact_collected, project),
        "phase3_verifying": phase3_verifying(rep, why),
        "phase4_debugging": phase4_debugging(rep, why),
    }


def summarize(attributions: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """The roll-up over N designs, from the SAME per-design records.

    Never re-derived: a second derivation is a second answer. Accepts either
    the attribution dicts themselves or any mapping that carries the four
    phase keys, so a caller that nests them under its own record can pass its
    records straight in.
    """
    def bump(d: Dict[str, int], k: Any) -> None:
        d[str(k)] = d.get(str(k), 0) + 1

    p1_source: Dict[str, int] = {}
    p1_nature: Dict[str, int] = {}
    p2_solved_by: Dict[str, int] = {}
    p2_emitter: Dict[str, int] = {}
    p3_failed: Dict[str, int] = {}
    p4: Dict[str, int] = {}
    unattributed: Dict[str, int] = {}
    p2_rejections = 0
    n = 0
    for r in attributions:
        n += 1
        ph = r.get("phases") if isinstance(r.get("phases"), dict) else r
        p1 = ph.get("phase1_routing") or {}
        p2 = ph.get("phase2_solving") or {}
        p3 = ph.get("phase3_verifying") or {}
        p4r = ph.get("phase4_debugging") or {}
        for key, node in (("phase1_routing", p1), ("phase2_solving", p2),
                          ("phase3_verifying", p3), ("phase4_debugging", p4r)):
            if not node.get("attributed"):
                bump(unattributed, key)
        bump(p1_source, p1.get("source"))
        bump(p1_nature, p1.get("nature"))
        if p2.get("attributed"):
            bump(p2_solved_by, p2.get("solved_by"))
            if p2.get("emitter"):
                bump(p2_emitter, p2.get("emitter"))
            p2_rejections += len(p2.get("rejected") or [])
        if p3.get("attributed"):
            for g in p3.get("failed") or []:
                bump(p3_failed, g)
        if p4r.get("attributed"):
            bump(p4, p4r.get("verdict") if p4r.get("fired") else "NONE")
    return {
        "designs": n,
        "phase1_nature": p1_nature,
        "phase1_source": p1_source,
        "phase2_solved_by": p2_solved_by,
        "phase2_emitters": dict(sorted(p2_emitter.items(),
                                       key=lambda kv: (-kv[1], kv[0]))),
        "phase2_distinct_emitters": len(p2_emitter),
        "phase2_designs_with_rejections": p2_rejections,
        "phase3_failed_gates": dict(sorted(p3_failed.items(),
                                           key=lambda kv: (-kv[1], kv[0]))),
        "phase4": p4,
        "unattributed_phases": unattributed,
    }


def write_report(project: Path, attribution: Dict[str, Any]) -> Path:
    """Put the attribution where a plain run's reader will find it."""
    out = Path(project).joinpath(*_STEP_REPORT[:-1]) / REPORT_NAME
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(attribution, indent=2, ensure_ascii=False) + "\n")
    return out


def render(att: Dict[str, Any]) -> str:
    p1 = att.get("phase1_routing") or {}
    p2 = att.get("phase2_solving") or {}
    p3 = att.get("phase3_verifying") or {}
    p4 = att.get("phase4_debugging") or {}
    lines = [
        f"  phase 1 routing   : {p1.get('nature')} "
        f"(source={p1.get('source')}, entry={p1.get('entry_step')}, "
        f"exit={p1.get('exit_step')})"
        if p1.get("attributed") else
        f"  phase 1 routing   : UNKNOWN — {p1.get('reason')}",
        f"  phase 2 solving   : {p2.get('solved_by')} "
        f"{p2.get('emitter')} (mechanism {p2.get('mechanism')}, "
        f"{p2.get('attempts')} rtl_gen attempt(s))"
        if p2.get("attributed") else
        f"  phase 2 solving   : UNKNOWN — {p2.get('reason')}",
        f"  phase 3 verifying : {len(p3.get('ran') or {})} gate(s) ran, "
        f"failing {p3.get('failed')}"
        if p3.get("attributed") else
        f"  phase 3 verifying : UNKNOWN — {p3.get('reason')}",
    ]
    if not p4.get("attributed"):
        lines.append(f"  phase 4 debugging : UNKNOWN — {p4.get('reason')}")
    elif p4.get("fired"):
        lines.append(
            f"  phase 4 debugging : {p4.get('verdict')} — "
            + ", ".join(f"{e['step']}({e['mechanism']})"
                        for e in p4.get("events") or [])
            + f"; verdict change {p4.get('verdict_change')}")
    else:
        lines.append(f"  phase 4 debugging : NONE — {p4.get('reason')}")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    ap = argparse.ArgumentParser(
        # The help text is LOGIC, not provenance: the naming test reads live
        # strings. Say what this reads, and let the module docstring carry the
        # names of the runs it was measured on.
        description="Attribute the four phases — routing, solving, verifying, "
                    "debugging — of one design project, from the router's "
                    "verdict and the runner's own step record.")
    ap.add_argument("project", type=Path)
    ap.add_argument("--json", action="store_true",
                    help="print the attribution as JSON on stdout")
    ap.add_argument("--no-write", action="store_true",
                    help="do not write reports/orchestrator/" + REPORT_NAME)
    a = ap.parse_args(argv)
    att = attribute(a.project)
    if not a.no_write:
        att["report"] = str(write_report(a.project, att))
    if a.json:
        print(json.dumps(att, indent=2, ensure_ascii=False))
    else:
        print(f"four-phase attribution — {a.project}")
        print(render(att))
        if not a.no_write:
            print(f"  report            : {att.get('report')}")
    # A design whose phases could not all be attributed is an instrumentation
    # finding, and the exit code must say so — but it is NEVER a design
    # failure, so it is 3, distinct from an argument error.
    missing = [k for k in ("phase1_routing", "phase2_solving",
                           "phase3_verifying", "phase4_debugging")
               if not (att.get(k) or {}).get("attributed")]
    if missing:
        print(f"  UNATTRIBUTED      : {missing} — an instrumentation finding, "
              f"not a rounding error")
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
