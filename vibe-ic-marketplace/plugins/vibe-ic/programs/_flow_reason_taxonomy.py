#!/usr/bin/env python3
"""Shared reason taxonomy for flow outcomes that did not decide the question.

The verdict word and the reason are deliberately separate.  ``SKIP`` says what
the flow does with an outcome; ``reason_class`` says why the check did not
produce a substantive PASS/FAIL verdict.  Only the three classes in
``SKIP_ELIGIBLE`` may remain in a skip/not-applicable tier.  The other three
leave the executed-PASS population and require follow-up.

This module is chip-, process-, tool-vendor-, and gate-agnostic.  Producers
should publish an explicit ``reason_class`` whenever possible.  The inference
helper exists for legacy programs and is deliberately fail-closed: an
unclassified non-verdict is an execution error, never a benign skip.

This is a shared helper, not an independently dispatched gate.  Its consuming
compliance rule blocks false PASS/N/A certification by moving unsafe reasons
to BLOCKED or INCOMPLETE, but it never fabricates a design FAIL from a process-
provenance gap.  Existing flow policy decides whether that disclosed tier
stops a caller.
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Optional


DESIGN_DECLARED_NA = "DESIGN_DECLARED_NA"
CAPABILITY_ABSENT = "CAPABILITY_ABSENT"
EXTERNAL = "EXTERNAL"
BLOCKED_BY_UPSTREAM = "BLOCKED_BY_UPSTREAM"
EXECUTION_ERROR = "EXECUTION_ERROR"
ZERO_DENOMINATOR = "ZERO_DENOMINATOR"

REASON_CLASSES = (
    DESIGN_DECLARED_NA,
    CAPABILITY_ABSENT,
    EXTERNAL,
    BLOCKED_BY_UPSTREAM,
    EXECUTION_ERROR,
    ZERO_DENOMINATOR,
)
REASON_CLASS_SET = frozenset(REASON_CLASSES)

# Only these classes satisfy the interrogation doctrine's N/A/skip bar.
SKIP_ELIGIBLE = frozenset({
    DESIGN_DECLARED_NA,
    CAPABILITY_ABSENT,
    EXTERNAL,
})
INCOMPLETE = frozenset({
    BLOCKED_BY_UPSTREAM,
    EXECUTION_ERROR,
    ZERO_DENOMINATOR,
})


def normalise(value: Any) -> Optional[str]:
    """Return a canonical reason class, or ``None`` for an invalid value."""
    if not isinstance(value, str):
        return None
    token = value.strip().upper().replace("-", "_").replace(" ", "_")
    return token if token in REASON_CLASS_SET else None


def report_reason_class(report: Any) -> Optional[str]:
    """Read an explicit class from a gate report without inventing one."""
    if not isinstance(report, Mapping):
        return None
    for key in ("reason_class", "not_measured_class", "skip_reason_class"):
        cls = normalise(report.get(key))
        if cls:
            return cls
    summary = report.get("summary")
    if isinstance(summary, Mapping):
        for key in ("reason_class", "not_measured_class", "skip_reason_class"):
            cls = normalise(summary.get(key))
            if cls:
                return cls
    return None


_ZERO_RE = re.compile(
    r"(?:\bzero[ -]denominator\b|\bexamined\s*[=:]?\s*0\b|"
    r"\bchecked\s*[=:]?\s*0\b|\b0\s*/\s*\d+\s+(?:examined|checked)\b|"
    r"\ball\s+0\b|\bno (?:reports?|entries|documents?)\b|"
    r"\bno\b[^\n]{0,50}\bdocuments?\b|"
    r"\bnone\s+(?:could|were)\s+(?:be\s+)?(?:aged|examined|checked)\b|"
    r"\bdocs?\s+loaded\s*[=:]?\s*none\b)", re.I)
_BLOCKED_RE = re.compile(
    r"(?:\bblocked\b|\bupstream\b|\bhas not run\b|\bnot yet run\b|"
    r"\bno deliverable\b|\bno result\.md\b|\bno orchestrator report\b|"
    r"\bno\b[^\n]{0,80}\b(?:doc(?:ument)?|report|file)\b[^\n]{0,40}\bfound\b|"
    r"\bno\b[^\n]{0,80}\b(?:results?\.json|generated docs|input docs|"
    r"canonical artefacts?|canonical artifacts?)\b|"
    r"\bno (?:spef|analog dir|l\d+)\b|\bpre output project\b|"
    r"\bphase 1\b[^\n]{0,40}\bnot attempted\b|"
    r"\brequired output\b.*\b(?:absent|missing)\b|"
    r"\bmissing\b.*\b(?:producer|output|artefact|artifact)\b)", re.I)
_CAPABILITY_RE = re.compile(
    r"(?:\bcapability\b.*\b(?:absent|missing|unavailable)\b|"
    r"\b(?:executable|simulator|toolchain|instrument)\b.*\b(?:absent|missing|unavailable)\b|"
    r"\bno (?:supported )?(?:simulator|tool|instrument)\b)", re.I)
_EXTERNAL_RE = re.compile(
    r"(?:\bexternal\b|\bhardware bench\b|\bboard[- ]level\b|"
    r"\bfpga board\b|\bfoundry handoff\b)", re.I)
_DECLARED_NA_RE = re.compile(
    r"(?:\bdeclared no\b|\bno\b[^\n]{0,80}\bdeclared\b|"
    r"\bdo not declare\b|\bapplicable\s*(?:is|=|:)\s*false\b|"
    r"\bno waivers\.json\b|"
    r"\bwaivers\.json has no entries\b|\bno command protocol\b|"
    r"\bnon protocol design\b|"
    r"\bno analog (?:content|blocks?)\b|\bno inout\b|\bno otp\b|"
    r"\bno fpga target\b|\basic target\b)", re.I)


def infer_nonverdict_reason(*, verdict: str = "", message: str = "",
                            evidence: Optional[Mapping[str, Any]] = None,
                            explicit: Any = None) -> str:
    """Classify a legacy non-verdict, defaulting loudly to execution error.

    Branch-owned evidence outranks prose.  The prose recognisers are narrow and
    ordered: a zero denominator or failed producer must not be laundered into a
    design N/A merely because its sentence also contains the word ``no``.
    """
    cls = normalise(explicit)
    if cls:
        return cls
    ev = dict(evidence or {})
    cls = normalise(ev.get("reason_class"))
    if cls:
        return cls
    skip_kind = str(ev.get("skip_kind") or "").lower()
    if skip_kind == "class-not-applicable":
        return DESIGN_DECLARED_NA
    if skip_kind in {"external", "analog-track-deferred"}:
        return EXTERNAL
    if skip_kind in {"capability-absent", "verified-capability-absent"}:
        return CAPABILITY_ABSENT
    if skip_kind in {"blocked-by-upstream", "missing-upstream-output"}:
        return BLOCKED_BY_UPSTREAM
    if skip_kind in {"zero-denominator", "empty-denominator"}:
        return ZERO_DENOMINATOR
    if skip_kind in {"no-backing-program", "invocation-error"}:
        return EXECUTION_ERROR

    # Many gate-owned reason tokens use snake/kebab case.  Normalise only for
    # classification; the original message remains the published evidence.
    text = re.sub(r"[_-]+", " ", str(message or ""))
    if str(verdict).upper() in {"NOT_INVOCABLE", "NOT_FOUND", "CRASHED",
                                "STALLED", "INVOCATION_ERROR"}:
        return EXECUTION_ERROR
    if _ZERO_RE.search(text):
        return ZERO_DENOMINATOR
    if _BLOCKED_RE.search(text):
        return BLOCKED_BY_UPSTREAM
    if _CAPABILITY_RE.search(text):
        return CAPABILITY_ABSENT
    if _EXTERNAL_RE.search(text):
        return EXTERNAL
    if _DECLARED_NA_RE.search(text):
        return DESIGN_DECLARED_NA
    return EXECUTION_ERROR


def record_verdict(reason_class: str) -> str:
    """The P0 record verdict permitted for this reason class."""
    cls = normalise(reason_class)
    if cls in SKIP_ELIGIBLE:
        return "SKIP"
    if cls == BLOCKED_BY_UPSTREAM:
        return "BLOCKED"
    return "INCOMPLETE"


def p0_tier_for_reason_classes(reason_classes: list[str]) -> str:
    """Return PASS only when every non-verdict class is skip-eligible."""
    return ("INCOMPLETE" if any(normalise(c) not in SKIP_ELIGIBLE
                                for c in reason_classes) else "PASS")
