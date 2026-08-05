#!/usr/bin/env python3
"""The classified blocker list — what each non-PASS step IS, beside the tally.

WHY THIS EXISTS, measured. A cell agent ran two experiments in opposite
directions in one round and reported:

    real post-route 3-corner STA — strictly BETTER evidence — scored 17
    PASSes LOWER; disabling a deliberate cross-step check scored 2 PASSes
    HIGHER while the design sat untouched. In neither direction was PASS
    measuring the design. The only number in that report that described the
    design was the classified blocker list.

The tally is a count of how many gates were satisfied. It moves when the
evidence improves, when a check is switched off, when a tool arrives on the
host — all without the design changing. The classified blocker list is the
part that is about the design, and until this module it existed only as prose
an agent might or might not write, in a shape no consumer could read.

THE THREE CLASSES, and why collapsing them into one number is the failure:

    PLUGIN_DEFECT       the plugin's own code did not do its job. Gets FIXED.
    DESIGN_FACT         a gate ran against this project's own artefacts and
                        returned a verdict about them. Gets reported as a
                        NAMED FAIL and never greened.
    MISSING_CAPABILITY  the flow could not do the work because a named tool,
                        board or PDK is not here. Gets NAMED precisely.

Three completely different correct responses. One number cannot carry them,
and a run that mistakes one for another mistakes measurement drift for
progress — which is the thing that was measured.

    UNCLASSIFIED        the fourth word, and the reason this module is usable
                        at all. Where the evidence the gate already holds does
                        not DETERMINE the class, the record says so. An honest
                        hole in the list can be worked; a wrong class cannot,
                        because nothing downstream knows to doubt it.

CLASSIFY FROM TYPED EVIDENCE, NEVER FROM MESSAGE PROSE. Every rule below keys
on a field or sentinel the producer already emits deliberately — a closed-enum
verdict word, a marker prefix it writes for the purpose, a waiver tier it
bound, a `blocks_on` edge from the flow definition. None of them reads a gate's
human message and guesses. That is not fastidiousness: the calibration corpus
contains four P0 sub-gate FAILs and TWO OF THEM are `read-error: Could not read
file`, i.e. the gate never measured anything. A rule that read "verdict == FAIL"
as "a fact about the design" would have been wrong on half of them, so those
four are UNCLASSIFIED here and the 36 sitting beside them are not.

ADDITIVE, BY CONSTRUCTION. Nothing in this module is read by the verdict.
`flow_compliance_check` computes `overall`, `counts` and every exit code before
it calls in here, and this module returns records and text. If a classification
ever moved a verdict, the classification would become worth gaming — which is
the disease, not the cure.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

import _flow_verdict_tiers as _T

__all__ = [
    "BLOCKER_CLASSES",
    "SCHEMA_VERSION",
    "CRASH_MARKER",
    "TIMEOUT_MARKER",
    "GATE_RAN_PREFIXES",
    "ENV_UNAVAILABLE_MARKER",
    "is_blocker",
    "classify",
    "build_blockers",
    "class_counts",
    "render_lines",
]

#: The closed vocabulary. A consumer switches on exactly these four words and
#: on nothing else; a fifth would be a change here that every consumer has to
#: handle, not a new sentence one can ignore.
BLOCKER_CLASSES: Tuple[str, ...] = (
    "PLUGIN_DEFECT", "DESIGN_FACT", "MISSING_CAPABILITY", "UNCLASSIFIED")

#: Bumped when a FIELD of the emitted record changes meaning or disappears.
#: Consumers key on it rather than probing for keys.
SCHEMA_VERSION = 1

# ── the producer's own sentinels, restated with a pinning test ──────────────
#
# These are `flow_compliance_check`'s markers. They are NOT imported from it:
# that module imports this one, and a cycle resolved with a lazy import is a
# second thing to keep correct. `test_blocker_list_beside_the_tally` asserts
# each constant here equals the producer's, so a rename there is a red test and
# not a rule that silently stops firing — the failure mode this whole file is
# written against.
CRASH_MARKER = "__CRASH_HINT__"
TIMEOUT_MARKER = "program TIMED OUT after"
ENV_UNAVAILABLE_MARKER = "ENV_UNAVAILABLE"
#: A gate PROGRAM ran as a subprocess and returned non-zero. Both slots, because
#: `optional_program_exit_zero` fails its step exactly as the required slot does
#: once its condition files are present — reading only one of them is how a
#: consumer ends up blind to half the corpus.
GATE_RAN_PREFIXES: Tuple[str, ...] = (
    "program failed:", "optional program failed:")

#: The producer's cascade grammars. `cascade_note` is the structured field and
#: is preferred; these patterns recover the same fact from the two shapes that
#: carry it only in a reason line.
_CASCADE_NOTE_RE = re.compile(r"blocked-by-upstream\(\s*(?:step\s*)?([^)\s,]+)")
_DEFERRED_NOTE_RE = re.compile(r"deferred-by-upstream\(\s*([^),\s]+)")
_PASS_VOIDED_RE = re.compile(r"PASS voided: dependency \[([^\]]+)\]")

#: Reason shapes that say only "the artefact is not here". They are the
#: producer's two absence lines, and absence is SILENT about cause.
_ABSENCE_PREFIXES = ("no required_outputs found",
                     "missing files (",
                     "condition not met")

#: The producer's DISCLOSURE tiers, normalised. A step wearing one of these
#: ran and told you its output was not design-bound. Named as a set here so a
#: tier added to the producer lands on `no-rule-matched` — visible — rather
#: than being quietly absorbed by a substring test.
_DISCLOSURE_TIERS = frozenset({"VACUOUS-PASS", "STRUCTURE-ONLY", "INCOMPLETE"})

#: Hint markers filtered out of the operator-facing `observed` text. They are
#: control signals for the producer's own tier promotion, not observations.
_HINT_PREFIXES = ("__VACUOUS_HINT__", "__SKIP_HINT__", "__WAIVER_HINT__",
                  "__STRUCTURE_ONLY_HINT__", "__SUBSTANTIVE_HINT__",
                  "__INCOMPLETE_HINT__", "__ADVISORY_HINT__")


def _field(step: Any, name: str, default: Any = "") -> Any:
    """One field off a step in either shape — `StepResult` in the producer,
    plain dict in the `--json` report and in every test. A predicate that knew
    only one shape would answer correctly in one place and silently return the
    default in the other; `_flow_verdict_tiers._field` exists for the same
    reason and this is deliberately the same device."""
    if isinstance(step, Mapping):
        val = step.get(name, default)
    else:
        val = getattr(step, name, default)
    return default if val is None else val


def _reasons(step: Any) -> List[str]:
    raw = _field(step, "reasons", []) or []
    return [str(r) for r in raw]


def _has_marker(step: Any, marker: str) -> bool:
    return any(marker in r for r in _reasons(step))


def _starts_with_any(reason: str, prefixes: Sequence[str]) -> bool:
    stripped = reason.lstrip()
    return any(stripped.startswith(p) for p in prefixes)


# ── membership: which steps are on the list at all ──────────────────────────
def is_blocker(step: Any) -> bool:
    """Is this step something a reader has to close before tape-out?

    DERIVED from `_flow_verdict_tiers`, never from a list of statuses kept
    here: a tier invented tomorrow lands on the blocking side by construction,
    which is the fail-SAFE direction and the same derivation the ordering guard
    uses. Two adjustments, and they are the producer's own semantics:

      * a FULL PASS is not a blocker;
      * `SKIPPED-CONDITION` is three different situations wearing one word
        (see `StepResult.self_skip_disclosed`), and only the third — the step
        that SHOULD have run and disclosed a capability gap instead — is an
        unmet requirement. Putting the other two on the list would add 97
        entries of "this digital chip has no analog blocks" to the calibration
        corpus, and a list nobody can read is a list nobody reads.

    Everything else non-PASS is on the list, INCLUDING waived deferrals (the
    producer's own verdict line calls them "must-close before production"),
    the disclosure tiers, and cascades. Cascades are marked `derived_from`
    rather than dropped: dropping them is how a report stops summing.
    """
    status = _T.normalize(_field(step, "status"))
    if _T.is_full_pass(status):
        return False
    if status == "SKIPPED-CONDITION":
        return bool(_field(step, "self_skip_disclosed", False))
    return bool(status)


# ── the derived/cascade attribution, orthogonal to the class ────────────────
def derived_from(step: Any) -> List[str]:
    """Which step(s) this blocker is a consequence of, as the producer said so.

    Kept SEPARATE from the class rather than made a fifth class. "This is a
    cascade of step 22" and "this is a plugin defect" answer different
    questions, and a reader triaging a list needs both: the class says what
    kind of work closes it, `derived_from` says whether it is even independent
    work. On the calibration run 22 of 41 blockers are derived, which is the
    difference between a 41-item backlog and a 19-item one.
    """
    out: List[str] = []

    def _add(val: str) -> None:
        val = val.strip()
        if val and val not in out:
            out.append(val)

    note = str(_field(step, "cascade_note", ""))
    for pat in (_CASCADE_NOTE_RE, _DEFERRED_NOTE_RE):
        for m in pat.finditer(note):
            _add(m.group(1))
    for reason in _reasons(step):
        for pat in (_CASCADE_NOTE_RE, _DEFERRED_NOTE_RE, _PASS_VOIDED_RE):
            for m in pat.finditer(reason):
                _add(m.group(1))
    return out


# ── the classification itself ───────────────────────────────────────────────
def classify(step: Any,
             *,
             non_pass_predecessors: Optional[Sequence[Any]] = None,
             oss_tool: str = "") -> Tuple[str, str, str]:
    """Return ``(classification, basis, note)`` for one blocker.

    `basis` NAMES THE RULE THAT FIRED. It is not decoration: a class with no
    named rule behind it is a guess wearing a label, and the guard
    `blocker_classification_check` refuses exactly that pairing. A reader who
    doubts an entry can go read the one rule that produced it.

    `non_pass_predecessors` is the step ids this step DECLARES it `blocks_on`
    that did not resolve to a full PASS. It comes from the flow definition, so
    it is a property of the flow and not of any chip. It is what separates "a
    gate measured this design and it is out of spec" from "a gate measured a
    design that is missing the input this step reads" — the second is not a
    fact about the design, and calling it one is precisely how a tally starts
    describing something other than the design.
    """
    status = _T.normalize(_field(step, "status"))
    reasons = _reasons(step)

    # 1. The gate program died. Whatever it was going to say about the design,
    #    it did not say it — the plugin's own process raised. `_process_crashed`
    #    has already separated this from a gate QUOTING a sub-tool's traceback,
    #    so the marker means the gate itself, not its subject.
    if _has_marker(step, CRASH_MARKER):
        return ("PLUGIN_DEFECT", "gate-crashed",
                "the gate program raised an unhandled exception and returned "
                "no verdict")

    # 2. A killed gate is INCONCLUSIVE and the producer says so in those words.
    #    Whether the hang is in the plugin or in the size of what it was asked
    #    to chew is not recorded anywhere, so it is not decided here.
    if _has_marker(step, TIMEOUT_MARKER):
        return ("UNCLASSIFIED", "gate-timed-out",
                "the gate was killed before reaching a verdict; nothing "
                "recorded says whether the plugin or the input is why")

    # 3-6. The capabilities the flow has already NAMED. Each of these is the
    #      producer having written down which tool/board/PDK is absent.
    #
    # `oss_tool` is passed ONLY for the steps the producer itself routed into
    # its open-source-constraints deferral — never for mere membership of
    # `_OPEN_SOURCE_CONTAINER_BLOCKED_STEPS`. That distinction was measured:
    # keying on table membership classified 10 of 41 blockers on the reference
    # run as MISSING_CAPABILITY, including four `PASS_VOIDED_BY_DEPENDENCY`
    # steps and a step that failed because its own gate program ran and
    # returned a verdict. "This step would ALSO need a commercial tool for
    # full sign-off" is true of those steps and is not why any of them is on
    # the list — a wrong class, produced exactly the way wrong classes get
    # produced, by a lookup that answers a nearby question.
    if oss_tool:
        return ("MISSING_CAPABILITY", "commercial-tool-required",
                f"the flow deferred this step for want of {oss_tool}, which "
                f"the open-source container does not provide")
    if _field(step, "self_skip_disclosed", False):
        return ("MISSING_CAPABILITY", "disclosed-capability-gap",
                "the runner disclosed a named capability gap in place of the "
                "sign-off artefact this step declares")
    if status == "SKIPPED-SETUP-REQUIRED":
        return ("MISSING_CAPABILITY", "setup-required",
                "the step could not start: its declared setup is not present "
                "on this host")
    if any(ENV_UNAVAILABLE_MARKER in r for r in reasons):
        return ("MISSING_CAPABILITY", "env-unavailable-waiver",
                "an ENV_UNAVAILABLE-tier waiver was bound to this step, which "
                "is the flow naming a capability it does not have here")

    # 7. A consequence of something else on this list. Ordered BEFORE the
    #    design-fact rule on purpose: a gate that ran, and failed, on a step
    #    whose declared input never arrived produced a number about an
    #    incomplete tree. `si_mcf_sta_check` reporting `NO_SPEF` while step 22
    #    (parasitic extraction) is MISSING is the calibration example — a
    #    substantive-looking FAIL that is not a fact about the design.
    preds = list(non_pass_predecessors or [])
    inherited = derived_from(step)
    if preds or inherited:
        named = ", ".join(str(p) for p in (preds or inherited))
        return ("UNCLASSIFIED", "derived-from-upstream",
                f"a step this one declares it depends on did not pass "
                f"({named}); nothing here measures this design until that is "
                f"closed")

    # 8. A gate PROGRAM ran to completion against artefacts this project
    #    produced, every step it depends on passed, and it returned non-zero.
    #    That is a statement about this project's tree — the class whose
    #    correct response is a named FAIL that is never greened.
    if any(_starts_with_any(r, GATE_RAN_PREFIXES) for r in reasons):
        return ("DESIGN_FACT", "gate-reached-verdict",
                "a gate program ran to a verdict against this project's own "
                "artefacts, with every declared dependency passed")

    # 9. The P0-style umbrella. It has no `program failed:` line of its own;
    #    what it has is typed per-gate records. Its class is therefore
    #    INHERITED from those records rather than asserted — the strongest
    #    class any of its failing sub-gates carries.
    #
    #    This started life as an unconditional DESIGN_FACT ("the umbrella
    #    dispatched gates that ran") and that was incoherent with its own
    #    sub-list: on the reference run every one of the umbrella's five FAIL
    #    records classifies UNCLASSIFIED (two of them are literally
    #    `read-error: Could not read file`), so the step said DESIGN_FACT
    #    above a list that said "we do not know" five times. A parent that
    #    claims more than its children is the same false-confidence in
    #    miniature.
    records = _field(step, "gate_records", None)
    if isinstance(records, list):
        sub_classes = {classify_sub_gate(r)[0] for r in records
                       if isinstance(r, Mapping)
                       and str(r.get("verdict")) == "FAIL"}
        for candidate in ("DESIGN_FACT", "PLUGIN_DEFECT",
                          "MISSING_CAPABILITY"):
            if candidate in sub_classes:
                return (candidate, "umbrella-subgate-verdict",
                        "inherited from the umbrella's own failing per-gate "
                        "records; see sub_blockers")
        if sub_classes:
            return ("UNCLASSIFIED", "umbrella-subgate-verdict",
                    "the umbrella's failing per-gate records carry a verdict "
                    "and no field that attributes it; see sub_blockers")

    # 10. Absence. The producer recorded that an artefact is not there, and
    #     that is ALL it recorded. A missing file is equally consistent with a
    #     plugin that never wrote it, a tool that is not installed, and a step
    #     nobody ran — so it is not decided here.
    if any(_starts_with_any(r, _ABSENCE_PREFIXES) for r in reasons):
        return ("UNCLASSIFIED", "declared-artefact-absent",
                "a declared artefact is not present; absence records no cause")

    # 11. The producer's own disclosure tiers. Each says, in a typed status
    #     word, that the step produced something OTHER than a design-bound
    #     measurement — no input applied, or content that came from a library
    #     default. That is a real and different thing from "we have no idea",
    #     so it gets its own basis; it is not a different CLASS, because
    #     which of the three closes it is exactly what the disclosure does not
    #     say.
    if status in _DISCLOSURE_TIERS:
        return ("UNCLASSIFIED", "disclosure-tier",
                f"the step disclosed {status}: it ran without measuring "
                f"design-bound content, which names no cause to act on")

    return ("UNCLASSIFIED", "no-rule-matched",
            "no classification rule matched the evidence this gate recorded")


def classify_sub_gate(record: Mapping[str, Any]) -> Tuple[str, str, str]:
    """Class for ONE typed per-gate record published by an umbrella step.

    Keys on the record's `verdict` — a closed enum the producer owns
    (`P0_GATE_VERDICTS`) — and on nothing else.

      * `NOT_INVOCABLE` is PLUGIN_DEFECT and it is not a judgement call:
        `_gate_invocation`'s own docstring calls it "a defect IN the caller,
        never benign". The umbrella built an argv its own registered gate
        rejects, so the plugin cannot run its own check. On the calibration run
        that is 36 of 246 registered gates.

      * `FAIL` stays UNCLASSIFIED. The record has verdict, name, message and
        evidence, and NO field that separates "measured the RTL and found a
        defect" from "could not open the file it audits". In the calibration
        run two of the four FAIL records are `read-error: Could not read file`.
        Reading FAIL as DESIGN_FACT would therefore have been wrong on half of
        them, and a wrong class is worse than a hole — the hole gets looked at.
    """
    verdict = str(record.get("verdict", ""))
    if verdict == "NOT_INVOCABLE":
        return ("PLUGIN_DEFECT", "sub-gate-not-invocable",
                "the umbrella's argv was rejected by the gate itself, so the "
                "plugin never ran its own registered check")
    if verdict == "FAIL":
        return ("UNCLASSIFIED", "sub-gate-verdict-not-attributed",
                "the record carries a FAIL verdict and no field that "
                "separates a measurement from a failure to read its input")
    return ("UNCLASSIFIED", "sub-gate-verdict-not-attributed", "")


def _sub_blockers(step: Any) -> Optional[List[Dict[str, Any]]]:
    """Per-gate blockers for a step that publishes typed records.

    Three-state, exactly as `StepResult.gate_records` is: ``None`` when the
    step publishes no records (the honest answer for ~56 flow steps), ``[]``
    when it published and every record is green, a list otherwise. Merging the
    first two would put "nothing to say" and "nothing wrong" in one bucket.
    """
    records = _field(step, "gate_records", None)
    if not isinstance(records, list):
        return None
    out: List[Dict[str, Any]] = []
    for rec in records:
        if not isinstance(rec, Mapping):
            continue
        verdict = str(rec.get("verdict", ""))
        if verdict not in ("FAIL", "NOT_INVOCABLE"):
            continue
        cls, basis, note = classify_sub_gate(rec)
        out.append({
            "gate": str(rec.get("name", "")),
            "verdict": verdict,
            "classification": cls,
            "basis": basis,
            "why": note,
            "observed": str(rec.get("message", ""))[:240],
        })
    return out


def _observed(step: Any, limit: int = 400) -> str:
    """What the gate actually reported, hints stripped.

    The hint prefixes are control signals the producer writes to promote its
    own tiers. They are not observations, and leaving them in is how a reader
    ends up quoting `__VACUOUS_HINT__` at a design review.
    """
    parts = [r for r in _reasons(step)
             if not any(h in r for h in _HINT_PREFIXES)]
    text = " | ".join(" ".join(p.split()) for p in parts)
    return text[:limit]


def _measures(step: Any, flow_step: Optional[Mapping[str, Any]],
              gate_summary_fn: Any = None) -> str:
    """What this step's gate is supposed to be measuring.

    Read off the FLOW DEFINITION, not off the failure text: the question "what
    was this step for" has an answer even when the step produced no output at
    all, and that is exactly the case where a reader most needs it.
    """
    if flow_step:
        if gate_summary_fn is not None:
            try:
                summary = gate_summary_fn(flow_step.get("gate"))
            except Exception:
                summary = ""
            if summary:
                return str(summary)[:300]
        outputs = flow_step.get("required_outputs")
        if outputs:
            return ("declared outputs: "
                    + ", ".join(str(o) for o in outputs))[:300]
        gate = flow_step.get("gate")
        if gate:
            # No summariser supplied and no declared outputs. Say the step HAS
            # a gate rather than that it has none — the second is a false
            # statement about the flow, and `_declared_gate_summary` exists
            # exactly because reading an empty program list as "no gate" made a
            # disclosure fire on 0 of the 3 steps it was written for.
            keys = sorted(gate) if isinstance(gate, Mapping) else []
            return f"gate declared ({', '.join(keys) or 'unnamed'})"[:300]
    return f"(the flow definition for step {_field(step, 'id')} declares no gate)"


def build_blockers(results: Sequence[Any],
                   flow_steps: Optional[Sequence[Mapping[str, Any]]] = None,
                   oss_blocked: Optional[Mapping[Any, str]] = None,
                   gate_summary_fn: Any = None) -> List[Dict[str, Any]]:
    """The list. One record per non-PASS step, in the order the steps ran.

    `flow_steps` is the flow definition's own step list — used for `measures`
    and for the `blocks_on` edges. Absent, the function still returns a
    complete and correctly-shaped list; it just cannot apply the
    derived-from-upstream rule from declared edges (the reason-line and
    `cascade_note` recovery still applies), which shows up as entries that stay
    on rule 8/9 instead of rule 7. Stated because a caller who omits it should
    know the classification gets LESS conservative, not more.
    """
    by_id: Dict[Any, Mapping[str, Any]] = {}
    for fs in (flow_steps or []):
        if isinstance(fs, Mapping) and "id" in fs:
            by_id[fs["id"]] = fs
    status_by_id: Dict[Any, str] = {
        _field(r, "id"): _T.normalize(_field(r, "status")) for r in results}
    oss_blocked = oss_blocked or {}

    out: List[Dict[str, Any]] = []
    for r in results:
        if not is_blocker(r):
            continue
        sid = _field(r, "id")
        flow_step = by_id.get(sid)
        preds: List[Any] = []
        if flow_step:
            for dep in (flow_step.get("blocks_on") or []):
                if dep in status_by_id and status_by_id[dep] != _T.FULL_PASS:
                    preds.append(dep)
        cls, basis, note = classify(
            r, non_pass_predecessors=preds,
            oss_tool=str(oss_blocked.get(sid, "")))
        out.append({
            "step_id": sid,
            "step_name": str(_field(r, "name")),
            "stage": str(_field(r, "stage")),
            "status": str(_field(r, "status")),
            "classification": cls,
            "basis": basis,
            "why": note,
            "measures": _measures(r, flow_step, gate_summary_fn),
            "observed": _observed(r),
            "derived_from": [str(p) for p in preds] or derived_from(r),
            "sub_blockers": _sub_blockers(r),
        })
    return out


def class_counts(blockers: Sequence[Mapping[str, Any]],
                 key: str = "classification") -> Dict[str, int]:
    """Every class word present as a key, including the zeroes.

    Zeroes are ON THE LINE deliberately: `PLUGIN_DEFECT=0` is a measurement,
    and a key that appears only when non-zero makes a consumer decide for
    itself what a missing key means — which is how a contract gets re-derived
    at each reader and drifts.
    """
    counts = {c: 0 for c in BLOCKER_CLASSES}
    for b in blockers:
        cls = str(b.get(key, ""))
        counts[cls] = counts.get(cls, 0) + 1
    return counts


def sub_blocker_class_counts(
        blockers: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    counts = {c: 0 for c in BLOCKER_CLASSES}
    for b in blockers:
        for sb in (b.get("sub_blockers") or []):
            cls = str(sb.get("classification", ""))
            counts[cls] = counts.get(cls, 0) + 1
    return counts


def render_lines(blockers: Sequence[Mapping[str, Any]],
                 max_sub: int = 6) -> List[str]:
    """The operator-facing block, printed BESIDE the tally.

    Deliberately not a replacement for the tally and not a second verdict — it
    carries no PASS/FAIL of its own. It answers the one question the tally
    cannot: for each thing that is not green, what IS it.
    """
    lines: List[str] = []
    if not blockers:
        lines.append("\nBlocker list (classified): none — every step is a "
                     "full PASS or a genuinely inapplicable skip.")
        return lines
    counts = class_counts(blockers)
    derived = sum(1 for b in blockers if b.get("derived_from"))
    lines.append(
        f"\nBlocker list (classified) — {len(blockers)} non-PASS step(s). "
        f"The tally above counts; this says what each one IS.")
    lines.append(
        "  " + "  ".join(f"{c}={counts.get(c, 0)}" for c in BLOCKER_CLASSES)
        + f"   ({derived} derived from another entry, "
          f"{len(blockers) - derived} independent)")
    sub_counts = sub_blocker_class_counts(blockers)
    if sum(sub_counts.values()):
        lines.append(
            "  per-gate, inside the umbrella step(s): "
            + "  ".join(f"{c}={sub_counts.get(c, 0)}"
                        for c in BLOCKER_CLASSES))
    for b in blockers:
        lines.append(
            f"  [{b['classification']:<18}] Step {b['step_id']}: "
            f"{b['step_name']}  ({b['status']})")
        lines.append(f"       measures : {b['measures']}")
        if b.get("observed"):
            lines.append(f"       observed : {b['observed']}")
        lines.append(f"       basis    : {b['basis']} — {b.get('why', '')}")
        if b.get("derived_from"):
            lines.append(
                f"       derived  : consequence of step(s) "
                f"{', '.join(b['derived_from'])}")
        subs = b.get("sub_blockers") or []
        for sb in subs[:max_sub]:
            lines.append(
                f"         ▸ [{sb['classification']:<18}] {sb['gate']} "
                f"({sb['verdict']}) — {sb['observed'][:110]}")
        if len(subs) > max_sub:
            lines.append(f"         ▸ … {len(subs) - max_sub} more per-gate "
                         f"entr(y/ies), full list in the JSON report")
    return lines
