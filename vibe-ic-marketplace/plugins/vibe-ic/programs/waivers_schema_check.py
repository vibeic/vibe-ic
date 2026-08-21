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
        id        any step id THE FLOW DECLARES (#526 — derived, never
                  re-typed; see "THE CEILING IS DERIVED" below), OR
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
        evidence  non-empty list making the deferral auditable. #524 —
                  "non-empty" is a LENGTH test and cannot tell corroboration
                  from the run pointing at its own report, so each list is
                  also CLASSIFIED (`_evidence_independence`) and an entry
                  that no independent artefact corroborates is DISCLOSED as
                  a warning. Disclosed, not refused: an ENV_UNAVAILABLE
                  deferral claims a tool was absent, and nothing independent
                  can corroborate a non-execution.
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

  THE CEILING IS DERIVED FROM THE FLOW, NOT RE-TYPED (#526)
  ---------------------------------------------------------
  This program's accepted step ids used to be the hand-maintained range
  `1..40`, while `flow/phase1_phase2_phase3.yaml` — the file
  `flow_compliance_check` treats as the single source of truth for the step
  set — declares 44 integer ids plus alphabetic ones. The two drifted 4
  apart, and the drift was not merely "that waiver was ignored": this
  program's ERRORS become `SystemExit(1)` inside
  `flow_compliance_check._load_waivers`, so ONE waiver naming a real step the
  ceiling had not heard of produced NO COMPLIANCE REPORT AT ALL. Measured at
  v1.7.85, NINE of the 63 ids the flow declares were rejected that way:
  41, 42, 43, 44 and the alphabetic `D1`, `FS1`, `DT1`, `DT2`, `DT3` — which
  is why the remedy is a DERIVED ID SET and not a corrected number. A scalar
  ceiling of 44 would still have rejected the five alphabetic ones.

  So the vocabulary is read from the flow definition (`flow_step_ids`) and an
  id that names a step the flow ACTUALLY DECLARES is valid by construction.
  That is the same rule #519/v1.7.83 already applied to role-resolved ids
  ("a role resolved through the canonical map is valid by construction and is
  not re-range-checked"), extended to the hand-authored integer path it left
  behind. `--max-step` survives as an OVERRIDE — see its help text.

v1.6.14 Wave 90 — decimal "<int>.<int>" sub-step ids were retired in
favour of integer + alphabetic stage ids. The decimal acceptance
pattern is removed (pre-release; no migration path needed).
v1.6.15 Wave 91 — main track raised 1..39 → 1..40 (pre-PnR Yosys gate
promoted to Step 14, stage3-5 cascade +1) and `P0` accepted as the
new id for the structural-RTL preflight umbrella (replaces -1).
#526 — those two hand-edits are what the derivation replaces; a range this
program has to bump by hand every time the flow grows is the defect.

Placeholder strings rejected in reason:
    "TODO", "TBD", "n/a", "N/A", "not done", "skip", "skipped",
    "pending", "will do later"

Self-approval rejected: approver in {"agent","claude","ai","self",
"automated","bot"} (case-insensitive).

Usage:
    python3 waivers_schema_check.py <project_dir>
    python3 waivers_schema_check.py <project_dir> --json out.json
    python3 waivers_schema_check.py <project_dir> --max-step 60
    python3 waivers_schema_check.py <project_dir> --strict-ids

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
import _evidence_independence as _ei  # noqa: E402  (#524)


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


# ----------------------------------------------------------------------
# #526 — the step-id vocabulary, DERIVED from the flow definition
# ----------------------------------------------------------------------
#: The flow definition whose `steps:` list IS the step set. Named once; the
#: ids themselves are never restated in this file.
FLOW_DEF_FILENAME = "phase1_phase2_phase3.yaml"

#: Ceiling used ONLY when the flow definition cannot be read at all (PyYAML
#: absent, or this program vendored away from its plugin tree). It is a
#: FALLBACK, not the truth, and it is deliberately the historical value so
#: that an unreadable flow degrades to the previous behaviour instead of to
#: something new. Every path that uses it records `max_step_source` in the
#: summary, so "we guessed" is never indistinguishable from "we derived".
FALLBACK_MAX_STEP = 40

#: {(path, mtime_ns, size): frozenset(ids)} — re-derived whenever the flow
#: file changes on disk, so a test that grows a fixture flow sees the growth.
_FLOW_ID_CACHE: Dict[Any, frozenset] = {}


def find_flow_def() -> Path:
    """Locate `flow/phase1_phase2_phase3.yaml` for the installed plugin.

    Mirrors the unified-layout half of `flow_compliance_check._find_flow_def`.
    It is restated rather than imported because `flow_compliance_check`
    imports THIS module (`_load_waivers` -> `waivers_schema_check.validate`),
    so importing it back would be a cycle — and because this program must
    keep working standalone, which that heavyweight module does not (it
    `sys.exit(2)`s at import time when PyYAML is missing).
    """
    here = Path(__file__).resolve()
    for ancestor in (here.parent.parent,
                     here.parent.parent.parent,
                     here.parent.parent.parent.parent):
        cand = ancestor / "flow" / FLOW_DEF_FILENAME
        if cand.is_file():
            return cand
    return here.parent.parent / "flow" / FLOW_DEF_FILENAME


def flow_step_ids(flow_def: Path | None = None) -> frozenset:
    """Every step id the flow definition DECLARES, exactly as written.

    Integers (`1`..`44`) and alphabetic stage ids (`A5`, `M2`, `P0`, `D1`,
    `FS1`, `DT3`, ...) alike — the set is whatever `steps:` says, which is
    the point: a waiver naming a step the flow declares must never be
    rejected for naming it.

    Returns an EMPTY set when the flow cannot be read (no PyYAML, missing or
    unparseable file). Empty means "no derived vocabulary", which callers
    resolve to :data:`FALLBACK_MAX_STEP` — fail-SOFT, because a validator
    that raised here would take down every gate that merely wanted to ask
    whether a waiver was well-formed.
    """
    path = Path(flow_def) if flow_def is not None else find_flow_def()
    try:
        st = path.stat()
        key = (str(path), st.st_mtime_ns, st.st_size)
    except OSError:
        return frozenset()
    if key in _FLOW_ID_CACHE:
        return _FLOW_ID_CACHE[key]
    try:
        import yaml  # imported lazily: standalone use must not require it
        data = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:  # ImportError, YAMLError, OSError — all "not derivable"
        return frozenset()
    steps = (data or {}).get("steps") if isinstance(data, dict) else None
    if not isinstance(steps, list):
        return frozenset()
    ids = frozenset(
        s["id"] for s in steps
        if isinstance(s, dict) and isinstance(s.get("id"), (int, str))
        and not isinstance(s.get("id"), bool)
    )
    _FLOW_ID_CACHE[key] = ids
    return ids


def flow_max_step(flow_def: Path | None = None) -> int | None:
    """Highest INTEGER main-track step id the flow declares, or None when the
    flow is unreadable. This is the derived default for ``max_step``."""
    ints = [i for i in flow_step_ids(flow_def)
            if isinstance(i, int) and not isinstance(i, bool)]
    return max(ints) if ints else None


def _canonical_flow_id(raw: str, declared: frozenset) -> Any:
    """The flow's own spelling of ``raw``, or None when the flow declares no
    such step. Case-insensitive, because the existing `A<n>`/`M<n>`/`P0`
    forms have always been accepted case-insensitively and a hand-authored
    `"dt1"` should not mean something different from `"DT1"`."""
    norm = raw.strip().casefold()
    if not norm:
        return None
    for declared_id in declared:
        if isinstance(declared_id, str) and declared_id.casefold() == norm:
            return declared_id
    return None


def _consumer_coerced_id(raw: Any) -> Any:
    """What the COMPLIANCE READER makes of this id.

    A verbatim restatement of `flow_compliance_check._load_waivers._parse_id`
    (`int(v)` else `str(v)`), which is a nested function and therefore not
    importable — and which could not be imported anyway without a cycle.

    It is restated because the SEVERITY of an id finding depends on it. An id
    this schema rejects is harmless when the reader also binds it to nothing
    (it can waive no step), but NOT harmless when the reader's looser `int()`
    lands it on a real step after this validator declined to check the entry:
    `"39"` and `39.5` both reach step 39 that way. `test_issue526_*` pins the
    two readers in agreement by running the REAL `flow_compliance_check`, so
    this copy cannot drift unnoticed.
    """
    try:
        return int(raw)
    except (ValueError, TypeError):
        return str(raw)


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


def validate(project: Path, max_step: int | None = None,
             strict_review_required: bool = False,
             strict_ids: bool = False,
             flow_def: Path | None = None
             ) -> tuple[List[WaiverFinding], Dict[str, Any]]:
    """Validate ``project``/waivers.json.

    ``max_step`` — OVERRIDE. None (the default) means "derive the ceiling
    from the flow definition", which is the only setting that cannot drift
    away from the flow. Pass a number only to validate against a flow this
    program cannot read; see the CLI help for the full rationale. An explicit
    number EXTENDS the accepted range, it never subtracts a step the flow
    declares — #526: `flow_compliance_check._load_waivers` still carries its
    own `max_step: int = 40` and passes it explicitly, so a rule that let the
    caller's stale ceiling win would have left the defect exactly where it
    was found.

    ``strict_ids`` — upgrade the id findings from WARNING back to ERROR, for
    standalone gate use where a nonzero exit is the whole signal. Mirrors
    ``strict_review_required``. Off by default so that an unusable id costs
    the reader one warning line instead of the entire compliance report.

    ``flow_def`` — point the derivation at a specific flow definition
    (tests; alternate flows). Defaults to the installed plugin's.
    """
    findings: List[WaiverFinding] = []
    wpath = project / "waivers.json"

    declared_ids = flow_step_ids(flow_def)
    derived_max = flow_max_step(flow_def)
    if max_step is not None:
        effective_max, max_step_source = max_step, "caller-override"
    elif derived_max is not None:
        effective_max, max_step_source = derived_max, "derived-from-flow"
    else:
        effective_max, max_step_source = FALLBACK_MAX_STEP, "fallback-flow-unreadable"

    summary: Dict[str, Any] = {
        "waivers_file": str(wpath),
        "exists": wpath.exists(),
        "waiver_count": 0,
        # #526 — the ceiling and where it came from are REPORTED, so a run
        # that silently degraded to the fallback is distinguishable from one
        # that read the flow. "we guessed 40" must never look like "the flow
        # says 40".
        "flow_def": str(Path(flow_def) if flow_def is not None else find_flow_def()),
        "flow_step_ids_declared": len(declared_ids),
        "max_step": effective_max,
        "max_step_source": max_step_source,
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
        #   (a) integer in 1..effective_max (main-track steps), or
        #   (b) string "step_<n>_..." with n in 1..effective_max, or
        #   (c) string "A<n>" with n in 1..16 (analog A1-A16 from
        #       phase1_phase2_phase3.yaml stage_analog track; chip-AGNOSTIC).
        #   (d) string "M<n>" with n in 1..16 (mixed-signal M1-M16,
        #       M1-M4 currently used).
        #   (e) string "P0" — preflight structural-RTL umbrella
        #       (Wave 91 / v1.6.15; replaces synthetic step -1).
        #   (g) #526 — ANY id the flow definition DECLARES, integer or
        #       alphabetic. This is the rule that makes the others
        #       maintenance-free: `41`-`44` and `D1`/`FS1`/`DT1`-`DT3` are
        #       real steps that (a)-(e) had never been taught about, and
        #       because a rejection here becomes `SystemExit(1)` in
        #       `flow_compliance_check`, each one deleted the whole report.
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
                # #526 (g) — an alphabetic id the FLOW declares. `D1`, `FS1`,
                # `DT1`-`DT3` are steps of the canonical flow that none of the
                # patterns above had ever been taught, so a waiver naming one
                # was rejected as unparseable and took the report with it.
                # Canonicalised to the flow's own spelling so that dedup and
                # reporting agree with the flow.
                elif (flow_alpha := _canonical_flow_id(stripped,
                                                       declared_ids)) is not None:
                    sid = flow_alpha
        # #519 — an id RESOLVED from a canonical role name is valid by
        # construction and is not re-range-checked. The map is the source of
        # truth for which steps a role names, and it legitimately reaches past
        # a hand-typed ceiling: `htol` binds to Step 44, while this program's
        # default max_step used to be 40. Range-checking a resolved id
        # therefore rejected a correct waiver as out-of-range — and since
        # `flow_compliance_check` turns any schema error into SystemExit(1),
        # that killed the entire compliance run for every project deferring
        # HTOL.
        #
        # #526 — "valid by construction" is the right rule and it was applied
        # to only one of the two paths that need it. The map is a source of
        # truth for which steps a ROLE names; the FLOW DEFINITION is the
        # source of truth for which steps EXIST, and `flow_compliance_check`
        # already treats it that way. So `flow_ok` extends the same
        # construction to a hand-authored id: if the flow declares that step,
        # the step exists, and no ceiling this program was handed can make it
        # not exist. That matters concretely because `flow_compliance_check.
        # _load_waivers` carries its OWN `max_step: int = 40` and passes it
        # EXPLICITLY — a fix that only corrected this function's default would
        # have been overridden by the caller and changed nothing.
        #
        # The range check keeps its real job: catching a hand-authored
        # `id: 999`, which names nothing.
        flow_ok = sid is not None and sid in declared_ids
        digital_ok = isinstance(sid, int) and (1 <= sid <= effective_max)
        analog_ok = is_analog and isinstance(sid, str)
        mixed_signal_ok = is_mixed_signal and isinstance(sid, str)
        preflight_ok = is_preflight and isinstance(sid, str)
        role_ok = role_name is not None and sid is not None
        if not (digital_ok or analog_ok or mixed_signal_ok
                or preflight_ok or role_ok or flow_ok):
            # #526 — WHAT SEVERITY, and why it is not a matter of taste.
            #
            # This program's ERRORS become `SystemExit(1)` inside
            # `flow_compliance_check._load_waivers`, so the severity decides
            # whether the reader gets a report with a complaint in it or NO
            # REPORT AT ALL. The rule that follows is: an id finding is fatal
            # only where fatality is the ONLY protection left. Measured
            # against the real consumer, there are exactly three cases.
            coerced = _consumer_coerced_id(raw_sid)
            id_sev = "error" if strict_ids else "warning"

            if not attestation_dialect and "id" not in entry:
                # (1) NO `id` KEY AT ALL. `_load_waivers` does `w["id"]` on
                # every `waived_steps` entry, so this raises KeyError there
                # and the run dies either way — downgrading would only swap
                # this precise message for the caller's bare
                # "cannot parse waivers.json: 'id'". Precise beats vague when
                # the outcome is identical; this stays an ERROR.
                findings.append(WaiverFinding(
                    severity="error", entry_index=i, step_id=-1,
                    rule="id-missing",
                    message=(
                        "no `id` field. The compliance reader indexes every "
                        "`waived_steps` entry by `id` and cannot load this "
                        "file without one — add a canonical step id "
                        "(an integer the flow declares, 'A<n>', 'M<n>' or "
                        "'P0')."
                    ),
                ))
                continue

            if coerced in declared_ids:
                # (2) A NON-CANONICAL SPELLING THE READER STILL BINDS TO A
                # REAL STEP. `"39"` and `39.5` are not valid ids here, but
                # `_load_waivers`'s `int()` lands both on step 39 and waives
                # it. Skipping the entry — which is what the old `continue`
                # did — would hand the consumer an exemption this program
                # never checked for a reason or an approver. So the entry is
                # bound to the coerced step and validated in full, and the
                # spelling is DISCLOSED. Nothing is applied unvalidated, and
                # the report survives to say so.
                findings.append(WaiverFinding(
                    severity=id_sev, entry_index=i,
                    step_id=coerced if isinstance(coerced, int) else -1,
                    rule="id-noncanonical-spelling",
                    message=(
                        f"id={raw_sid!r} is not a canonical step id, but the "
                        f"compliance reader coerces it to step {coerced!r} "
                        f"and will apply this waiver there. Write the "
                        f"canonical id {coerced!r} so the two readers cannot "
                        f"disagree."
                    ),
                ))
                sid = coerced
            else:
                # (3) AN ID THAT NAMES NOTHING. `_load_waivers` files it under
                # a key no flow step has, so it grants NO exemption — the
                # waiver is inert. An ERROR here would not withhold anything;
                # it would only delete the report that says the waiver is
                # inert. WARNING, and `--strict-ids` restores the hard exit
                # for standalone gate use where the exit code is the signal.
                findings.append(WaiverFinding(
                    severity=id_sev, entry_index=i,
                    step_id=sid if isinstance(sid, int) else -1,
                    rule="id-range",
                    message=(
                        f"id must name a step the flow declares (integer in "
                        f"1..{effective_max}, or 'step_<n>_…', 'A<n>' with "
                        f"n<=16, 'M<n>' with n<=16, 'P0', or an alphabetic "
                        f"stage id the flow defines), got {raw_sid!r}. This "
                        f"waiver names no flow step, so it exempts nothing."
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
        # int 1..effective_max or analog A<n> 1..16). Each cascaded id must
        # NOT also have its own waiver entry (would duplicate-shadow the
        # cascade source). Reduces N+1 entries to 1 root.
        #
        # #526 — this list was range-checked against the SAME hand-typed
        # ceiling as `id`, so it carried the identical defect: a root waiver
        # cascading to a real step past the ceiling (`cascades_to: [44]`, or
        # any alphabetic flow id) was rejected, and the rejection deleted the
        # compliance report. It is held to the derived vocabulary now, and its
        # severity follows the same rule as `id` — a cascade child that names
        # no step propagates nothing, so saying so must not cost the report.
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
                        elif (child_alpha := _canonical_flow_id(
                                child, declared_ids)) is not None:
                            cs = child_alpha
                    if not (
                        (isinstance(cs, int) and 1 <= cs <= effective_max)
                        or (cs is not None and cs in declared_ids)
                        or isinstance(cs, str)
                    ):
                        findings.append(WaiverFinding(
                            severity=("error" if strict_ids else "warning"),
                            entry_index=i, step_id=sid,
                            rule="cascades-id-invalid",
                            message=(f"cascades_to[{j}]={child!r} names no step "
                                     f"the flow declares, so it propagates no "
                                     f"waiver"),
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
            else:
                # #524 — "non-empty" is a LENGTH test, and length cannot tell
                # corroboration from the run pointing at its own report. Over
                # the 8 tracked attestation entries, 5 cite ONLY the producing
                # run's orchestrator report and 1 fills the field with
                # free-text fragments that reference nothing; all 8 satisfy
                # "non-empty" identically, so the verdict a reader sees is the
                # same whether the evidence was independent or not.
                #
                # WARNING, and the severity is the whole point — same reasoning
                # as the block above, learnt the hard way in #519: this
                # program's ERRORS become `SystemExit(1)` inside
                # `flow_compliance_check._load_waivers`, which would stop the
                # run emitting ANY report, advisories included. A disclosure
                # that kills the report discloses nothing.
                #
                # And it stays a disclosure rather than a refusal for a
                # substantive reason, not a timid one: an ENV_UNAVAILABLE
                # deferral claims a tool was ABSENT, and no independent
                # artefact can corroborate a non-execution — the artefact whose
                # absence IS the waiver is the one being asked for. Measured on
                # the real producer, EVERY ENV_UNAVAILABLE waiver
                # `phase3_one_shot_runner._autogen_waivers_json` can emit is
                # uncorroborated, so refusing them would make an honest
                # tool-less-host deferral impossible to honour. Self-reference
                # is acceptable ALONGSIDE something else and is never
                # sufficient ALONE; what was wrong is that it was invisible.
                _assess = _ei.assess(evidence, project)
                if not _assess.corroborated:
                    findings.append(WaiverFinding(
                        severity="warning", entry_index=i, step_id=sid,
                        rule="attestation-evidence-uncorroborated",
                        message=_ei.disclosure(entry.get("step", sid),
                                               _assess),
                    ))
                elif _assess.dangling:
                    # Corroborated overall, but at least one item cites an
                    # artefact that is not there. Named separately because a
                    # dangling citation READS like corroboration — it is
                    # path-shaped — while a self-reference at least admits
                    # what it is.
                    findings.append(WaiverFinding(
                        severity="warning", entry_index=i, step_id=sid,
                        rule="attestation-evidence-dangling",
                        message=(
                            f"{_assess.dangling} evidence item(s) are "
                            f"path-shaped but name no artefact present in the "
                            f"project (or point outside it); they read as "
                            f"corroboration without being auditable. "
                            f"{_assess.describe()}"),
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
    p.add_argument("--max-step", type=int, default=None,
                   help=("OVERRIDE the highest valid main-track step id. "
                         "The default is DERIVED from the flow definition "
                         "(#526) — the flow is the single source of truth "
                         "for the step set, and a number kept in sync by "
                         "hand is how this program's ceiling and the flow "
                         "drifted 4 steps apart. Pass this only when "
                         "validating against a flow this program cannot "
                         "read; it EXTENDS the accepted range and never "
                         "subtracts a step the flow declares."))
    p.add_argument("--json", help="Write JSON report to this path")
    p.add_argument("--strict-review-required", action="store_true",
                   help=("v1.6.12: when set, missing review_required field "
                         "is upgraded from WARN to ERROR (exit 1)."))
    p.add_argument("--strict-ids", action="store_true",
                   help=("#526: when set, an id that names no flow step is "
                         "upgraded from WARN to ERROR (exit 1). Off by "
                         "default because these findings are consumed by "
                         "`flow_compliance_check`, which turns any error "
                         "into SystemExit(1) — an inert waiver must not "
                         "cost the reader the whole compliance report. Set "
                         "it when running this program standalone as a "
                         "gate, where the exit code is the signal."))
    args = p.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"waivers_schema_check: not a directory: {project}", file=sys.stderr)
        return 2

    findings, summary = validate(project, max_step=args.max_step,
                                 strict_review_required=args.strict_review_required,
                                 strict_ids=args.strict_ids)

    errors = [f for f in findings if f.severity == "error"]
    warnings = [f for f in findings if f.severity == "warning"]

    if not summary["exists"]:
        print(f"waivers_schema_check: no waivers.json (nothing waived) — OK")
    else:
        print(f"\n=== Waivers schema check ===")
        print(f"File: {summary['waivers_file']}")
        # #526 — print WHERE the ceiling came from. A run that silently fell
        # back because the flow was unreadable must not look like one that
        # read it.
        print(f"Step ids: {summary['flow_step_ids_declared']} declared by "
              f"{summary['flow_def']}")
        print(f"Max main-track step: {summary['max_step']} "
              f"({summary['max_step_source']})")
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
