#!/usr/bin/env python3
"""
waivers_schema_check.py — Validate <project>/waivers.json for the
phase 2+3 canonical flow (40 main-track steps + A1-A9 + M1-M4 + P0
preflight in v1.6.15 / Wave 91).

A waiver is the ONLY legitimate way to skip a mandatory step. To prevent
rubber-stamp waivers ("waived: TODO") from passing through, this program
enforces schema + content rules:

  Top-level entry list: {"waived_steps": [ ... ]} or {"waivers": [ ... ]}.
  Both keys are read, via the shared reader `_waiver_entries` — see #519 and
  that module's docstring. Reading only `waived_steps` meant 6 of 11 tracked
  waiver files and 8 of 19 entries were never examined, and this program
  reported that blindness as "Waiver count: 0", exit 0.

  TWO DIALECTS, TWO APPROVAL MODELS, TWO SEVERITIES (#519)
  --------------------------------------------------------
  The keys are not two spellings of one record. Each entry is validated
  against the dialect it is written in:

  (1) `waived_steps` — A NAMED HUMAN APPROVES.
        id        integer in 1..40 (main-track step id), OR
                  "A<n>" with n in 1..16 (analog stage), OR
                  "M<n>" with n in 1..16 (mixed-signal stage), OR
                  "P0" (preflight structural-RTL umbrella, Wave 91), OR
                  "step_<n>_..." (legacy compatible form)
        reason    non-empty string, ≥ 20 chars, not a placeholder
                  (`rationale` is an accepted synonym)
        approver  non-empty string; not "agent", "claude", "ai", "self"
      `flow_compliance_check` applies these entries with no further gate, so
      THIS PROGRAM IS THE ONLY GATE and substance failures are ERRORS.

  (2) `waivers` — AN EVIDENCE-GATED ATTESTATION STANDS IN FOR A SIGNATURE.
      Emitted by `phase3_one_shot_runner` when a step is deferred; no human
      is present at generation, so the dialect requires disclosure instead:
        step      role name resolving through `_waiver_entries.STEP_NAME_TO_ID`
                  (e.g. "lvs" -> 31)
        rationale substantive prose (>= 40 chars at the point of use)
        ticket    tracks the deferred work
        review_required   must be true — deferred, not closed
        evidence  non-empty list making the deferral auditable
        approver  OPTIONAL. `flow_compliance_check` supplies the tier approver
                  (`field-agent-attest (ENV_UNAVAILABLE tier)`) when absent, so
                  its absence here is the design, not an omission.
      `flow_compliance_check` re-checks all of the above BEFORE honouring such
      an entry, refuses it with a named advisory when incomplete, and lets the
      step fail on its own merits. Because that gate is stricter and fail-SAFE
      — and because this program's errors become `SystemExit(1)` in that same
      caller — content findings on this dialect are WARNINGS. Escalating them
      would replace a self-explaining refusal with a dead report.

  What stays an ERROR in BOTH dialects: an unparseable file, a non-list under
  either key, a duplicated step, and a self-approving/placeholder `approver`
  (that field IS applied when present, so nothing else guards it).

  Optional:
    approved_at   ISO-8601 timestamp — the HUMAN approver's dated signature.
                  #519 DECIDED it is a signature, never a generation stamp:
                  nothing writes it automatically and nothing should, because
                  a machine-written approval date is a self-approval, which
                  this schema bars in the `approver` field. Its absence is a
                  WARNING (`approved-at-missing`) so that the un-ageable
                  waiver is visible rather than silently un-aged.
    review_required  bool (default true)
    ticket        str (e.g. Linear/Jira issue id)

v1.6.14 Wave 90 — decimal "<int>.<int>" sub-step ids were retired in
favour of integer + alphabetic stage ids. The decimal acceptance
pattern is removed (pre-release; no migration path needed).
v1.6.15 Wave 91 — main track raised 1..39 → 1..40 (pre-PnR Yosys gate
promoted to Step 14, stage3-5 cascade +1) and `P0` accepted as the
new id for the structural-RTL preflight umbrella (replaces -1).

Placeholder strings rejected in reason:
    "TODO", "TBD", "n/a", "N/A", "not done", "skip", "skipped",
    "pending", "will do later"

Self-approval rejected: approver in {"agent","claude","ai","self",
"automated","bot"} (case-insensitive).

Usage:
    python3 waivers_schema_check.py <project_dir>
    python3 waivers_schema_check.py <project_dir> --json out.json
    python3 waivers_schema_check.py <project_dir> --max-step 40

Exit codes:
    0 = valid (or no waivers file)
    1 = schema / content violation
    2 = io error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _waiver_entries as _we  # noqa: E402  (after sys.path bootstrap)


PLACEHOLDER_REASONS = {
    "todo", "tbd", "n/a", "na", "not done", "skip", "skipped",
    "pending", "will do later", "fixme", "?"
}

SELF_APPROVERS = {
    "agent", "claude", "ai", "self", "automated", "bot",
    "claude-code", "auto"
}

# Unfilled name-slot fillers a scaffold leaves behind. Kept separate from
# PLACEHOLDER_REASONS (which _is_placeholder_approver also consults) because
# these read as approver slots specifically, not as prose rationales.
PLACEHOLDER_APPROVERS = {
    "name", "your name", "human", "human name", "approver",
    "approver name", "reviewer", "owner", "someone",
    "xxx", "xxxx", "???", "unknown", "unfilled", "placeholder",
}

MIN_REASON_LEN = 20


@dataclass
class WaiverFinding:
    severity: str  # "error" | "warning"
    entry_index: int
    step_id: int | str  # int for digital 1..N, str "A<n>" for analog
    rule: str
    message: str


def _is_placeholder(s: str) -> bool:
    norm = s.strip().lower()
    if norm in PLACEHOLDER_REASONS:
        return True
    # Also reject reasons that are JUST whitespace or punctuation
    if not re.search(r"[a-z0-9]", norm):
        return True
    return False


def _is_self_approver(s: str) -> bool:
    return s.strip().lower() in SELF_APPROVERS


def _is_placeholder_approver(s: str) -> bool:
    """True when `approver` is still an UNFILLED scaffold value.

    ``waiver_template_gen.py`` emits ``waivers.json.template`` with placeholder
    fields and documents that the schema is "GUARANTEED to reject" them, so an
    unfilled template cannot be renamed to ``waivers.json`` and ship as a green
    sign-off. That guarantee was not actually implemented here: the only approver
    rule was the SELF_APPROVERS set, which a sentinel like ``__TODO_HUMAN_NAME__``
    does not match. A template whose `reason` had been filled in (>= MIN_REASON_LEN,
    not a PLACEHOLDER_REASON) therefore validated clean while nobody had approved
    anything. This closes that hole.

    General by construction — matches the SHAPE of an unfilled slot, not our own
    template's literal string:
      * a ``__SENTINEL__`` dunder-wrapped token (the scaffold convention), and
      * bare placeholder words, incl. the PLACEHOLDER_REASONS vocabulary reused
        for approvers plus name-slot fillers ("name", "your name", "xxx", ...).
    """
    norm = s.strip().lower()
    if re.fullmatch(r"__.*__", norm):          # __TODO_HUMAN_NAME__, __APPROVER__, ...
        return True
    norm = norm.strip("<>[]{}").strip()        # <TODO>, [name], {approver}
    if norm in PLACEHOLDER_REASONS:            # todo / tbd / fixme / ? / ...
        return True
    return norm in PLACEHOLDER_APPROVERS


def validate(project: Path, max_step: int = 40,
             strict_review_required: bool = False
             ) -> tuple[List[WaiverFinding], Dict[str, Any]]:
    findings: List[WaiverFinding] = []
    wpath = project / "waivers.json"

    summary: Dict[str, Any] = {
        "waivers_file": str(wpath),
        "exists": wpath.exists(),
        "waiver_count": 0,
    }

    if not wpath.exists():
        # No waivers = valid (nothing to review)
        return findings, summary

    try:
        data = json.loads(wpath.read_text())
    except json.JSONDecodeError as exc:
        findings.append(WaiverFinding(
            severity="error", entry_index=-1, step_id=-1,
            rule="json-parse",
            message=f"waivers.json is not valid JSON: {exc}",
        ))
        return findings, summary

    if not isinstance(data, dict):
        findings.append(WaiverFinding(
            severity="error", entry_index=-1, step_id=-1,
            rule="top-level-structure",
            message='waivers.json must be a JSON object',
        ))
        return findings, summary

    # A key that is PRESENT but holds a non-list is malformed regardless of
    # what the other key holds — report before considering emptiness, so
    # {"waived_steps": "oops"} still fails instead of falling through the
    # no-entries early return below.
    bad_keys = _we.malformed_keys(data)
    for _bad_key in bad_keys:
        findings.append(WaiverFinding(
            severity="error", entry_index=-1, step_id=-1,
            rule="waived-steps-type",
            message=f'"{_bad_key}" must be a list',
        ))
    if bad_keys:
        return findings, summary

    # A flow-step waiver list is optional. Many projects use ONLY per-gate
    # waiver keys (e.g. {"frame_end_idle_reset_alternative": "...",
    #        "otp_field_map_unresolved": [...]}) and never have any flow-step
    # waivers — those files are perfectly valid and shouldn't be rejected
    # for lacking an empty waived_steps array. v0.119.21 fix.
    #
    # #519 — that reasoning is sound and is PRESERVED, but it must be reachable
    # only when NEITHER key holds entries. It used to key off `"waived_steps"
    # not in data` alone, so a file whose entries sat under `waivers` — the key
    # `phase3_one_shot_runner` writes — inherited the genuinely-empty file's
    # pass. 8 of the corpus's 19 waiver entries were never examined at all.
    # The emptiness test now asks the shared reader about BOTH keys.
    by_key = _we.entries_by_key(data)
    entries = _we.entries(data)
    summary["waiver_count"] = len(entries)
    summary["waiver_count_by_key"] = {k: len(v) for k, v in by_key.items()}
    if not _we.has_entries(data):
        return findings, summary

    # #519 — each entry is validated against THE DIALECT IT IS WRITTEN IN.
    #
    # The two keys are not two spellings of one record shape; they are two
    # schemas with two different approval models, and the codebase already
    # knew it:
    #
    #   `waived_steps`  {"id": 31, "reason": ..., "approver": "<a human>"}
    #                   A NAMED HUMAN approves. `waivers_schema_check` rejects
    #                   a machine in that field (SELF_APPROVERS).
    #
    #   `waivers`       {"step": "lvs", "rationale": ..., "ticket": ...,
    #                    "review_required": true, "evidence": [...]}
    #                   No human is present when the runner emits this, so the
    #                   dialect substitutes an EVIDENCE-GATED ATTESTATION for a
    #                   signature: `flow_compliance_check` honours such an entry
    #                   "IFF every required attestation field is present"
    #                   (ticket + review_required + non-empty evidence +
    #                   >= 40-char rationale) and, when it does, SUPPLIES the
    #                   tier approver itself — `w.get("approver", "field-agent-
    #                   attest (ENV_UNAVAILABLE tier)")`. The absence of
    #                   `approver` there is the design, not an omission.
    #
    # Validating the second dialect with the first's `approver` rule was tried
    # and is wrong twice over: it reports `approver-missing` on every waiver the
    # runner has ever emitted, and because `flow_compliance_check` turns any
    # schema error into `SystemExit(1)`, it does not merely report — it takes
    # the whole compliance check down for every project that legitimately
    # defers a step for a missing tool. Disclosure would stop buying deferral.
    #
    # So the attestation dialect is held to the attestation contract, mirrored
    # from the one already enforced at the point of use: a ticket-less,
    # evidence-less or hand-wave-rationale entry is REPORTED here and REFUSED
    # there. Because it is the same contract in both places, a file that this
    # program passes clean is a file whose waivers will actually be applied —
    # which the previous silence could never promise.
    sourced = [(key, e) for key, lst in by_key.items() for e in lst]

    seen_ids: set = set()
    for i, (source_key, entry) in enumerate(sourced):
        attestation_dialect = (source_key == "waivers")
        raw_sid = entry.get("id") if isinstance(entry, dict) else None

        if not isinstance(entry, dict):
            findings.append(WaiverFinding(
                severity="error", entry_index=i, step_id=-1,
                rule="entry-type",
                message="each waiver must be an object with id/reason/approver",
            ))
            continue

        # id — accept:
        #   (a) integer in 1..max_step (main-track steps), or
        #   (b) string "step_<n>_..." with n in 1..max_step, or
        #   (c) string "A<n>" with n in 1..16 (analog A1-A16 from
        #       phase1_phase2_phase3.yaml stage_analog track; chip-AGNOSTIC).
        #   (d) string "M<n>" with n in 1..16 (mixed-signal M1-M16,
        #       M1-M4 currently used).
        #   (e) string "P0" — preflight structural-RTL umbrella
        #       (Wave 91 / v1.6.15; replaces synthetic step -1).
        # v1.6.14 Wave 90 — decimal "<int>.<int>" sub-step ids retired.
        # Wave 88 introduced patch ids that Wave 90 integerised; the
        # decimal pattern is no longer accepted.
        # #519 — (f) a `waivers`-shaped entry identifies its step by ROLE NAME
        # (`{"step": "lvs"}`) rather than by canonical id. That spelling is
        # first-class: `flow_compliance_check` has bound it to canonical ids
        # for as long as the shape has existed, via the role-name map now
        # shared in `_waiver_entries`. Resolving it here matters for honesty,
        # not just tidiness — an unresolved role name falls through to
        # `id-range`, whose `continue` would skip the approver check, so the
        # validator would complain that a waiver named its step in the wrong
        # dialect while saying nothing about the fact that NOBODY APPROVED IT.
        # The rubber-stamp finding is the one this program exists to make.
        role_name = None
        if raw_sid is None and isinstance(entry, dict):
            _role = entry.get("step")
            _resolved = _we.resolve_step_name(_role)
            if _resolved is not None:
                raw_sid = _resolved
                role_name = _role.strip().lower()
            elif isinstance(_role, str) and _role.strip():
                findings.append(WaiverFinding(
                    severity="warning", entry_index=i, step_id=-1,
                    rule="step-name-unknown",
                    message=(
                        f"step={_role!r} is not a recognised flow step role "
                        f"name, so this waiver cannot be bound to a flow step. "
                        f"Use a canonical `id`, or one of: "
                        + ", ".join(sorted(_we.STEP_NAME_TO_ID))
                    ),
                ))
                continue

        sid = None
        is_analog = False
        is_mixed_signal = False
        is_preflight = False
        if isinstance(raw_sid, int):
            sid = raw_sid
        elif isinstance(raw_sid, str):
            stripped = raw_sid.strip()
            m = re.match(r"^step[_\-\s]*(\d+)(?:[_\-\s]|$)", stripped, re.IGNORECASE)
            if m:
                sid = int(m.group(1))
            else:
                am = re.match(r"^A(\d+)$", stripped, re.IGNORECASE)
                mm = re.match(r"^M(\d+)$", stripped, re.IGNORECASE)
                pm = re.match(r"^P0$", stripped, re.IGNORECASE)
                if am and 1 <= int(am.group(1)) <= 16:
                    sid = stripped.upper()
                    is_analog = True
                elif mm and 1 <= int(mm.group(1)) <= 16:
                    sid = stripped.upper()
                    is_mixed_signal = True
                elif pm:
                    sid = "P0"
                    is_preflight = True
        # #519 — an id RESOLVED from a canonical role name is valid by
        # construction and is not re-range-checked. The map is the source of
        # truth for which steps a role names, and it legitimately reaches past
        # `max_step`: `htol` binds to Step 44, while this program's default
        # max_step is still 40. Range-checking a resolved id therefore rejected
        # a correct waiver as out-of-range — and since `flow_compliance_check`
        # turns any schema error into SystemExit(1), that killed the entire
        # compliance run for every project deferring HTOL. The range check
        # exists to catch a hand-authored `id: 999`, which this is not.
        digital_ok = isinstance(sid, int) and (1 <= sid <= max_step)
        analog_ok = is_analog and isinstance(sid, str)
        mixed_signal_ok = is_mixed_signal and isinstance(sid, str)
        preflight_ok = is_preflight and isinstance(sid, str)
        role_ok = role_name is not None and sid is not None
        if not (digital_ok or analog_ok or mixed_signal_ok
                or preflight_ok or role_ok):
            findings.append(WaiverFinding(
                severity="error", entry_index=i,
                step_id=sid if isinstance(sid, int) else -1,
                rule="id-range",
                message=(
                    f"id must be integer in 1..{max_step} "
                    "(or 'step_<n>_…', 'A<n>' with n<=16, "
                    "'M<n>' with n<=16, or 'P0'), "
                    f"got {raw_sid!r}"
                ),
            ))
            continue

        # #519 — deduplicate on the identifier AS WRITTEN, not on the resolved
        # id. Role names are many-to-one onto flow steps (Step 31 is "Physical
        # Verification (DRC + LVS + ERC + Density)", so `drc` and `lvs` both
        # resolve to 31). Keying on the resolved id would report a project that
        # waives DRC and LVS separately — the shape the runner actually emits —
        # as having waived one step twice. Entries that supply a canonical `id`
        # keep the exact previous semantics: they dedupe on the resolved `sid`,
        # so `39` and `step_39_foo` still collide.
        dup_key = f"step:{role_name}" if role_name is not None else sid
        if dup_key in seen_ids:
            findings.append(WaiverFinding(
                severity="error", entry_index=i, step_id=sid,
                rule="id-duplicate",
                message=(f"step {role_name!r} is waived more than once"
                         if role_name is not None
                         else f"step id {sid} is waived more than once"),
            ))
        seen_ids.add(dup_key)

        # v0.112 (BACKLOG-v10 P0.2): cascades_to validation. Optional
        # field — if present, must be a list of valid step ids (digital
        # int 1..max_step or analog A<n> 1..16). Each cascaded id must
        # NOT also have its own waiver entry (would duplicate-shadow the
        # cascade source). Reduces N+1 entries to 1 root.
        cascades = entry.get("cascades_to")
        if cascades is not None:
            if not isinstance(cascades, list):
                findings.append(WaiverFinding(
                    severity="error", entry_index=i, step_id=sid,
                    rule="cascades-type",
                    message="cascades_to must be a list of step ids if present",
                ))
            else:
                for j, child in enumerate(cascades):
                    cs = None
                    if isinstance(child, int):
                        cs = child
                    elif isinstance(child, str):
                        cm = re.match(r"^A(\d+)$", child.strip(), re.IGNORECASE)
                        cmm = re.match(r"^M(\d+)$", child.strip(), re.IGNORECASE)
                        if cm and 1 <= int(cm.group(1)) <= 16:
                            cs = child.strip().upper()
                        elif cmm and 1 <= int(cmm.group(1)) <= 16:
                            cs = child.strip().upper()
                    if not (
                        (isinstance(cs, int) and 1 <= cs <= max_step)
                        or isinstance(cs, str)
                    ):
                        findings.append(WaiverFinding(
                            severity="error", entry_index=i, step_id=sid,
                            rule="cascades-id-invalid",
                            message=f"cascades_to[{j}]={child!r} is not a valid step id",
                        ))
                    elif cs == sid:
                        findings.append(WaiverFinding(
                            severity="error", entry_index=i, step_id=sid,
                            rule="cascades-self",
                            message=f"cascades_to cannot include the root id {sid}",
                        ))

        # reason — ORGANIC-20260606 #437(e): `rationale` is an accepted
        # synonym. Waiver authors (incl. the runner's own templates) use
        # the two interchangeably; rejecting a rationale-keyed entry as
        # "reason-missing" voided VALID waivers (displayed "INVALID (no
        # reason given)", counted WAIVED:0). Same substance bars apply.
        #
        # #519 — WHY THE SEVERITY DEPENDS ON THE DIALECT. Not leniency; it
        # follows from which gate is the LAST one standing:
        #
        #   `waived_steps` entries are applied by `flow_compliance_check`
        #   directly, with no attestation gate of their own — it loads them and
        #   grants the exemption. This program is therefore the ONLY thing
        #   between a rubber-stamped entry and a waived step, so a substance
        #   failure here must be an ERROR and must block.
        #
        #   `waivers` entries pass through a STRICTER gate at the point of use:
        #   `flow_compliance_check` demands a >= 40-char rationale (double this
        #   program's bar), refuses the waiver outright when it is not met, and
        #   says which field was missing. The step then fails on its own merits.
        #   Escalating to an ERROR here would not add a check — it would replace
        #   a stricter, fail-SAFE, self-explaining refusal with `SystemExit(1)`
        #   that discards the report the reader needed.
        #
        # The severity tracks who else is watching, so no defect loses a gate.
        substance_sev = "warning" if attestation_dialect else "error"
        reason = entry.get("reason", "")
        if (not isinstance(reason, str) or not reason.strip()) \
                and isinstance(entry.get("rationale"), str):
            reason = entry["rationale"]
        if not isinstance(reason, str) or not reason.strip():
            findings.append(WaiverFinding(
                severity=substance_sev, entry_index=i, step_id=sid,
                rule="reason-missing",
                message="reason must be a non-empty string",
            ))
        elif len(reason.strip()) < MIN_REASON_LEN:
            findings.append(WaiverFinding(
                severity=substance_sev, entry_index=i, step_id=sid,
                rule="reason-too-short",
                message=f"reason is {len(reason.strip())} chars; need >= {MIN_REASON_LEN}",
            ))
        elif _is_placeholder(reason):
            findings.append(WaiverFinding(
                severity=substance_sev, entry_index=i, step_id=sid,
                rule="reason-placeholder",
                message=f"reason is a placeholder/empty value: {reason!r}",
            ))

        # attestation dialect — the `waivers` shape's substitute for a human
        # signature. Mirrors the contract `flow_compliance_check` applies before
        # HONOURING such a waiver, so "validates" and "will be applied" agree.
        #
        # WARNING, not error, and the severity is load-bearing. These same
        # conditions are ALREADY ENFORCED where it matters: `flow_compliance_
        # check` refuses to honour an incomplete attestation, emits a named
        # advisory saying exactly which field is missing, and leaves the step
        # to fail on its own merits (#216 — "makes the report LOUDER, never
        # greener"). That is fail-SAFE and strictly more informative than what
        # an error here would produce, because this program's errors are turned
        # into `SystemExit(1)` by that same caller: an incomplete waiver would
        # stop killing one step's exemption and start killing the entire
        # compliance report, advisory and all. So the enforcement stays at the
        # point of use and this gate REPORTS. The rubber-stamp bar that must
        # bite — a placeholder or too-short rationale — remains an ERROR below
        # for both dialects, which is the check this program exists for.
        if attestation_dialect:
            if not str(entry.get("ticket") or "").strip():
                findings.append(WaiverFinding(
                    severity="warning", entry_index=i, step_id=sid,
                    rule="attestation-ticket-missing",
                    message=("a `waivers` entry defers work under an "
                             "evidence-gated attestation instead of a human "
                             "signature, so it must carry a `ticket` tracking "
                             "the deferred work"),
                ))
            if entry.get("review_required") is not True:
                findings.append(WaiverFinding(
                    severity="warning", entry_index=i, step_id=sid,
                    rule="attestation-review-not-required",
                    message=("`review_required` must be exactly true — the "
                             "attestation defers the step, it does not close "
                             "it, and a human still owes the review"),
                ))
            evidence = entry.get("evidence")
            if not (isinstance(evidence, list) and evidence):
                findings.append(WaiverFinding(
                    severity="warning", entry_index=i, step_id=sid,
                    rule="attestation-evidence-missing",
                    message=("a non-empty `evidence` list is what makes this "
                             "an attestation rather than an assertion; "
                             "without it the deferral cannot be audited"),
                ))

        # approver — REQUIRED in the `waived_steps` dialect, where a named
        # human is the whole approval. OPTIONAL in the attestation dialect,
        # which has no human at generation time and whose approval is the
        # evidence gate checked just above; `flow_compliance_check` supplies
        # the tier approver itself for those. Still validated WHEN PRESENT:
        # an entry that does name an approver may not name a machine.
        approver = entry.get("approver", "")
        if not isinstance(approver, str) or not approver.strip():
            if not attestation_dialect:
                findings.append(WaiverFinding(
                    severity="error", entry_index=i, step_id=sid,
                    rule="approver-missing",
                    message="approver must be a non-empty string",
                ))
        elif _is_self_approver(approver):
            findings.append(WaiverFinding(
                severity="error", entry_index=i, step_id=sid,
                rule="approver-self",
                message=f"self-approval rejected: {approver!r}",
            ))
        elif _is_placeholder_approver(approver):
            findings.append(WaiverFinding(
                severity="error", entry_index=i, step_id=sid,
                rule="approver-placeholder",
                message=(f"approver is an unfilled scaffold placeholder: {approver!r} "
                         f"— a waivers.json.template must have a real human approver "
                         f"filled in before it can ship as waivers.json"),
            ))

        # review_required — v1.6.12: silent default true is too lenient.
        # If field is missing, emit WARN (or ERROR under
        # --strict-review-required). Either way, behavior still
        # defaults to True so existing callers aren't broken.
        # (attestation dialect already ERRORs above on a missing/false
        # review_required and on a missing ticket — do not double-report)
        if "review_required" not in entry and not attestation_dialect:
            findings.append(WaiverFinding(
                severity=("error" if strict_review_required else "warning"),
                entry_index=i, step_id=sid,
                rule="review-required-missing",
                message=(
                    "review_required field is missing; defaulted to true. "
                    "Make explicit (set true|false) to remove this "
                    + ("error." if strict_review_required else "warning.")
                ),
            ))
        # approved_at — #519. DECIDED: `approved_at` is a HUMAN APPROVAL
        # SIGNATURE (the WHEN of the act whose WHO is `approver`), NOT a
        # generation timestamp. Nothing in the codebase writes it and 0 of the
        # corpus's 19 entries carry one, so the question was open; it is closed
        # here, in the direction the rest of this schema already points.
        #
        # WHY NOT stamp it at generation, which would make `waiver_staleness_
        # check` start ageing waivers: because this validator REJECTS a machine
        # as the `approver` (SELF_APPROVERS), so letting a machine write the
        # matching timestamp would readmit through the time field exactly the
        # self-approval the approver field bars — and `waivers_materialize`'s
        # own documented invariant is "NEVER self-approving". A generated
        # timestamp would manufacture an approval nobody gave and start an
        # aging clock on it, which is strictly worse than the current silence:
        # it would convert an unreviewed waiver into one that merely looks
        # young. Writers therefore continue NOT to emit it.
        #
        # The consequence is made VISIBLE rather than silent. `waiver_staleness_
        # check` documents that it stays quiet on entries lacking `approved_at`
        # because "waivers_schema_check already flags it" — a deferral to a
        # gate that did not exist. This warning is that gate. It is a WARNING,
        # not an error: a waiver whose human approval is otherwise well-formed
        # should not be void for want of a date, and the entries with no
        # approver AT ALL already fail above.
        # Scoped to the dialect where a human actually signs. An
        # attestation entry has no human at generation time by design, so
        # demanding a signature DATE from it would be noise on every waiver
        # the runner emits; its open work is tracked by `ticket` +
        # `review_required`, both errors above if absent.
        if not attestation_dialect and \
                not str(entry.get("approved_at") or "").strip():
            findings.append(WaiverFinding(
                severity="warning", entry_index=i, step_id=sid,
                rule="approved-at-missing",
                message=(
                    "no `approved_at` — this waiver cannot be aged, so "
                    "`waiver_staleness_check` will never flag it however long "
                    "it stays open. `approved_at` is the human approver's "
                    "dated signature (ISO-8601); it is never stamped "
                    "automatically, because a machine-written approval date "
                    "would be a self-approval. A human closing this waiver "
                    "should set it alongside `approver`."
                ),
            ))

        review_required = entry.get("review_required", True)
        if review_required and not entry.get("ticket") and not attestation_dialect:
            findings.append(WaiverFinding(
                severity="warning", entry_index=i, step_id=sid,
                rule="ticket-missing",
                message="review_required=true but no ticket field (Linear/Jira id recommended)",
            ))

    return findings, summary


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    p.add_argument("project_dir", help="Project directory containing (optional) waivers.json")
    p.add_argument("--max-step", type=int, default=40,
                   help="Highest valid main-track step id "
                        "(default 40 for phase1_phase2_phase3 v1.6.15 flow)")
    p.add_argument("--json", help="Write JSON report to this path")
    p.add_argument("--strict-review-required", action="store_true",
                   help=("v1.6.12: when set, missing review_required field "
                         "is upgraded from WARN to ERROR (exit 1)."))
    args = p.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"waivers_schema_check: not a directory: {project}", file=sys.stderr)
        return 2

    findings, summary = validate(project, max_step=args.max_step,
                                 strict_review_required=args.strict_review_required)

    errors = [f for f in findings if f.severity == "error"]
    warnings = [f for f in findings if f.severity == "warning"]

    if not summary["exists"]:
        print(f"waivers_schema_check: no waivers.json (nothing waived) — OK")
    else:
        print(f"\n=== Waivers schema check ===")
        print(f"File: {summary['waivers_file']}")
        print(f"Waiver count: {summary['waiver_count']}")
        print(f"Errors: {len(errors)}    Warnings: {len(warnings)}\n")
        for f in findings:
            icon = "✗" if f.severity == "error" else "⚠"
            print(f"  {icon} [{f.severity}] step {f.step_id} / entry {f.entry_index}: {f.rule}")
            print(f"     {f.message}")

    if args.json:
        Path(args.json).write_text(json.dumps({
            "summary": summary,
            "errors": [asdict(f) for f in errors],
            "warnings": [asdict(f) for f in warnings],
        }, indent=2))

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
