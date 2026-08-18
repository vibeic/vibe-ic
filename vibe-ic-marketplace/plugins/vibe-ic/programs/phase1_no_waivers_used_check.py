#!/usr/bin/env python3
"""
phase1_no_waivers_used_check.py — gate (Wave 23, v0.119.55).

Wave 23 — extraction coverage is non-waivable. 100% is the HARD
acceptance threshold for Phase 1 (doc-extraction). If a literal cannot be extracted
by the auto-discovery patterns, the agent MUST add a project-level
`extraction_patterns.json` to teach the extractor how to find it.
There is NO "we'll skip this doc" option.

This gate guards Phase 1 (doc-extraction) from being silenced by waivers. It scans
`<project>/waivers.json` and FAILs if any waiver name matches one
of the forbidden Phase 1 (doc-extraction) patterns (prefix / keyword based).

Forbidden waiver name patterns
==============================
  * `extraction_coverage_*`
  * `phase1_coverage_*`
  * `extraction_evidence_*`
  * `phase1_*_acceptable`
  * `phase1_*_intentional`
  * `extraction_*_alternative`

The 28th fresh-agent attempt (v0.119.54 benchmark) bypassed Phase 1 (doc-extraction)
coverage gates with three waivers covering exactly these shapes:
  * `extraction_coverage_acceptable_below_95`
  * `phase1_coverage_below_threshold_intentional`
  * `extraction_evidence_schema_alternative`

Wave 23 forbids any of them.

Behavior
========
- If `<project>/waivers.json` is absent or unparseable → PASS
  (no Phase 1 (doc-extraction) waiver in use).
- If `<project>/waivers.json` lists 0 forbidden waivers → PASS.
- If 1+ forbidden waiver names appear → FAIL listing each one.

Non-Phase 1 waivers (e.g. `nba_shift_register_intentional`,
`open_drain_active_drive_intentional`, `vendor_fpga_table_alternative`)
remain valid and DO NOT trigger this gate. The intent is to forbid
silencing the Phase 1 (doc-extraction) coverage / evidence gates only.

Usage
-----
    python3 phase1_no_waivers_used_check.py <project_dir>

Returns 0 PASS, 1 FAIL, 2 input error.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


# Forbidden patterns. Each tuple is (label, regex_string). Compiled
# with re.fullmatch so the pattern must match the entire waiver name.
_FORBIDDEN_PATTERNS: tuple[tuple[str, str], ...] = (
    ("extraction_coverage_*",     r"extraction_coverage_.+"),
    ("phase1_coverage_*",        r"phase1_coverage_.+"),
    ("extraction_evidence_*",     r"extraction_evidence_.+"),
    ("phase1_*_acceptable",      r"phase1_.+_acceptable"),
    ("phase1_*_intentional",     r"phase1_.+_intentional"),
    ("extraction_*_alternative",  r"extraction_.+_alternative"),
    # Wave 29 (v0.119.61) — runtime functional verification (Wave 28
    # plugin reference TB) is non-waivable.  33 hardware FAIL attempts
    # proved every escape mechanism gets used.
    ("protocol_reference_tb_*",   r"protocol_reference_tb_.+"),
    # Wave 30 (v0.119.62) — Phase 2+3 self-audit, flow-compliance and
    # pre-burn audit are non-waivable.  35th-attempt root cause was
    # mcp-eda pre-burn guard parsing 0 failed gates and allowing the
    # burn; agents must not be able to re-introduce the same hole via
    # waivers like phase23_audit_alternative or
    # pre_burn_check_acceptable.
    ("phase23_audit_*",           r"phase23_audit_.+"),
    ("flow_compliance_*",         r"flow_compliance_.+"),
    ("pre_burn_*",                r"pre_burn_.+"),
    ("coverage_*_acceptable",     r"coverage_.+_acceptable"),
    # Wave 31 (v0.119.63) — typed-field / blob-size / unique-content /
    # denominator gates are non-waivable. SEMANTIC_AUDIT_v0119.57
    # showed the 100% literal-grep score was gameable while ~87% of
    # design data lived in raw blob fields; Wave 31 forbids waivers
    # in any of the four enforcement axes.
    ("l_doc_structured_*",        r"l_doc_structured_.+"),
    ("l_doc_aggregated_*",        r"l_doc_aggregated_.+"),
    ("l_doc_unique_*",            r"l_doc_unique_.+"),
    ("extraction_coverage_denominator_*",
     r"extraction_coverage_denominator_.+"),
    # Wave-on-fix v1.6.10 — per-input-doc completeness audit closes
    # the silent-skip vector where phase1's extractors miss an
    # entire vendor doc because of fname-filter or format-extractor
    # gaps.  Non-waivable (a missed vendor doc means missed RTL spec).
    ("phase1_input_vs_generated_*",
     r"phase1_input_vs_generated_.+"),
)


def _is_forbidden(name: str) -> str | None:
    """Return the matching forbidden-pattern label, or None."""
    for label, rx in _FORBIDDEN_PATTERNS:
        if re.fullmatch(rx, name):
            return label
    return None


# Wave 36 (v0.119.68) — class-not-applicable whitelist.  An L doc
# that is genuinely not applicable to the IC class can be silenced
# via a typed waiver of shape:
#
#   "phase1_l5_class_not_applicable_for_uart_chip": {
#       "rationale": "≥40 char explanation tying L5 to the
#                     pure-UART class…",
#       "ic_class": "digital_cmd_driven"
#   }
#
# These do NOT trigger M4's forbidden-pattern check because they are
# evidence-backed escape paths, not blanket silencers.  We only
# admit them when the body carries (a) an `ic_class` field and (b)
# a rationale string ≥ 40 chars.
_CLASS_NOT_APPLICABLE_KEY_RE = re.compile(
    r"(?:phase1|extraction)_l(\d{1,2})_class_not_applicable_[A-Za-z0-9_]+"
)
_CLASS_NOT_APPLICABLE_MIN_RATIONALE = 40


def _is_class_not_applicable_waiver(key: str, body: object) -> bool:
    """Wave 36 — accept evidence-backed class-not-applicable waivers.

    Returns True iff key matches the canonical shape AND the body
    carries an `ic_class` field plus a ≥40-char rationale.  Anything
    else falls through to the existing forbidden-pattern check.
    """
    if not _CLASS_NOT_APPLICABLE_KEY_RE.fullmatch(key):
        return False
    if not isinstance(body, dict):
        return False
    ic_class = body.get("ic_class")
    if not isinstance(ic_class, str) or not ic_class.strip():
        return False
    rationale = body.get("rationale") or body.get("reason") or ""
    if not isinstance(rationale, str):
        return False
    return len(rationale.strip()) >= _CLASS_NOT_APPLICABLE_MIN_RATIONALE


def _check(project: Path) -> tuple[int, list[str]]:
    if not project.is_dir():
        return 2, [f"FAIL — project dir not found: {project}"]

    waivers_path = project / "waivers.json"
    if not waivers_path.is_file():
        return 0, [
            "phase1_no_waivers_used_check: PASS — "
            "no waivers.json present"
        ]
    try:
        data = json.loads(waivers_path.read_text())
    except Exception as e:
        return 0, [
            f"phase1_no_waivers_used_check: PASS — "
            f"waivers.json unparseable ({e}); cannot detect forbidden "
            f"keys (treated as no Phase 1 (doc-extraction) waiver in use)"
        ]
    if not isinstance(data, dict):
        return 0, [
            "phase1_no_waivers_used_check: PASS — "
            "waivers.json top-level is not an object; cannot detect "
            "forbidden keys"
        ]

    hits: list[tuple[str, str]] = []  # [(name, matched_label), ...]
    for key, body in data.items():
        if not isinstance(key, str):
            continue
        # Wave 36 — class-not-applicable typed waivers are admitted
        # iff they carry ic_class + rationale ≥ 40 chars.
        if _is_class_not_applicable_waiver(key, body):
            continue
        label = _is_forbidden(key)
        if label is not None:
            hits.append((key, label))

    if not hits:
        return 0, [
            "phase1_no_waivers_used_check: PASS — "
            "no forbidden Phase 1 (doc-extraction) waiver names in waivers.json"
        ]

    out = [
        f"FAIL — Wave 23 (v0.119.55): Phase 1 (doc-extraction) waivers are forbidden. "
        f"Detected {len(hits)} forbidden waiver name(s) in waivers.json:"
    ]
    for name, label in hits:
        out.append(
            f"  - `{name}` matches forbidden pattern `{label}`. "
            f"Wave 23 — Phase 1 (doc-extraction) waivers are forbidden. "
            f"Detected waiver: {name}. Remove from waivers.json and "
            f"resolve the underlying extraction gap by adding "
            f"patterns to extraction_patterns.json."
        )
    out.append(
        "To resolve: remove every forbidden waiver from waivers.json "
        "and fix the underlying Phase 1 (doc-extraction) coverage / evidence gap by "
        "adding patterns to `<project>/extraction_patterns.json` "
        "until extraction_coverage_check / "
        "phase1_coverage_report_present_check / "
        "extraction_evidence_schema_check all PASS at 100%."
    )
    return 1, out


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("Usage: phase1_no_waivers_used_check.py <project_dir>")
        return 2
    pos = [a for a in argv if not a.startswith("--")]
    if not pos:
        print("Usage: phase1_no_waivers_used_check.py <project_dir>")
        return 2
    project = Path(pos[0]).resolve()
    code, lines = _check(project)
    for ln in lines:
        print(ln)
    return code


if __name__ == "__main__":
    sys.exit(main())
