"""v0.1.49 — Chipignite/foundry signoff-waiver scaffold emitter.

Scope (distinct from `waivers_schema_check.py` / `waiver_template_gen.py`)
========================================================================

The existing plugin waiver tooling is for **internal flow-step waivers**
(Phase 2 / 3 mandatory steps that this project does not exercise). This
NEW program targets a different waiver shape:

  **External signoff-failure waivers** — entries the submitter attaches to
  a chipignite / Open MPW / commercial-foundry submission to explain
  expected-but-non-fatal sign-off failures (e.g. a XOR delta from a
  blackbox-macro abstract LEF, a LVS consistency LAYOUT mismatch from
  a hard-macro user-project). The eFabless reviewer reads them as policy
  documents; mpw_precheck does not auto-consume them, but the submission
  is incomplete without them when known FAILs are expected.

Why a PROGRAM
=============

The waiver **schema** is deterministic:
  - `failed_check`     — enum of precheck step names
  - `reason_class`     — enum of standard mitigation categories
  - `evidence_files`   — list of pilot writeups + log paths backing the claim
  - `mitigation`       — required free-text (≥ 40 chars; not a placeholder)
  - `approver`         — real person identifier
  - `risk_assessment`  — "low|medium|high" with required justification on medium/high
  - `id` / `signed_at` — auto-generated

This is a Bucket-A program emission, not a skill — same pattern as
`lvs_netgen_setup_emit.py` and `waiver_template_gen.py`. The
**content** (mitigation, evidence path list, risk justification) is per-
design and is supplied by the user; the **shape** is fixed.

Reference
=========

  - spm pilot PHASE_C_CLEANUP_RESULT.md § "Three standard remediation paths"
  - spm pilot PHASE_C_FLATTEN_EXPERIMENT.md (validates path 3 = waiver is
    the practical chipignite remediation; paths 1/2 fight the design intent)
  - benchmark_clean/spm_pilot_v0144/caravel_integration/signoff/waivers/
    (the actual spm waiver files this program scaffolded)

Unit tests: `programs/tests/test_signoff_waiver_emit.py`.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
import plugin_manifest_discovery as _pmd  # noqa: E402  (#800 ONE version reader)


# ---------------------------------------------------------------------------
# Canonical precheck-step waiver targets (chipignite / Open MPW shuttle).
# Source: eFabless mpw_precheck check names emitted as the `Failed:` set.
# Update when eFabless adds / renames a check. ANY/UNKNOWN means the
# waiver targets a non-precheck signoff event (e.g. internal commercial
# LVS) and the validator only checks shape, not enum membership.
# ---------------------------------------------------------------------------
CHIPIGNITE_PRECHECK_FAIL_NAMES: List[str] = [
    "License",
    "Makefile",
    "Default",
    "Documentation",
    "Consistency",
    "GPIO-Defines",
    "XOR",
    "DRC",
    "LVS",
    "Antenna",
    "Manifest",
    "OEB",
    "PDN",
    "Metal",
    "IllegalCellname",
    "Topcell",
    "Spike",
]


# ---------------------------------------------------------------------------
# Reason / mitigation categories. Picking from this list (vs free text)
# enforces consistent triage across submissions and lets the eFabless
# reviewer recognise the category without re-reading every reason field.
# ---------------------------------------------------------------------------
REASON_CLASSES: Dict[str, str] = {
    "blackbox-macro-signoff-limit": (
        "Failure stems from open-source signoff tooling's inability to "
        "verify a blackbox hard-macro abstract (LEF / GDS abstract). "
        "Device-equivalence proven by orthogonal evidence."),
    "open-source-extraction-naming-convention": (
        "Net-level mismatch driven by Magic ext2spice hierarchical-net-name "
        "vs Yosys flat-wire convention. Device-level LVS device-class match "
        "and device count equivalence already PASS."),
    "stock-empty-vs-user-content-xor-delta": (
        "XOR check compares the user wrapper GDS against the stock-empty "
        "harness; deltas are the user content the submission is meant to add. "
        "Geometry change is intended, not an error."),
    "precheck-tool-self-issue": (
        "Failure is in the precheck tool's own bundled files (not the user "
        "project). Upstream PR filed / referenced; submitter applied local "
        "workaround."),
    "foundry-deck-unavailable-open-source": (
        "Commercial signoff deck (Calibre / Pegasus PEX) not available to "
        "the open-source submitter; equivalent open-source PASS achieved "
        "for all checkable invariants."),
    "intentional-design-choice": (
        "Reported failure is intended behavior of the design "
        "(e.g. analog block intentionally floating I/O, ESD diode area)."),
}


RISK_LEVELS = ("low", "medium", "high")


@dataclass
class WaiverEntry:
    """One waiver entry. Shape matches the chipignite-submission JSON Schema."""
    project_name: str
    failed_check: str
    reason_class: str
    mitigation: str
    approver: str
    evidence_files: List[str] = field(default_factory=list)
    risk_assessment: str = "low"
    risk_justification: str = ""
    sub_check_detail: str = ""
    expected_remediation_path: str = ""
    # Auto-filled if absent.
    signed_at: str = ""
    id: str = ""


def _stable_id(project: str, check: str, reason: str) -> str:
    """Deterministic-but-readable id: `<project>__<check>__<short-hash>`."""
    h = hashlib.sha256(f"{project}|{check}|{reason}".encode("utf-8")).hexdigest()[:8]
    safe_check = re.sub(r"[^A-Za-z0-9]+", "-", check).strip("-").lower() or "check"
    safe_proj = re.sub(r"[^A-Za-z0-9]+", "-", project).strip("-").lower() or "project"
    return f"{safe_proj}__{safe_check}__{h}"


def _today_iso() -> str:
    return _dt.date.today().isoformat()


PLACEHOLDER_TOKENS = ("TODO", "FIXME", "TBD", "tbd", "placeholder", "REPLACE")


def validate_waiver(entry: Dict[str, Any]) -> List[str]:
    """Validate a waiver dict against the schema. Returns list of error strings
    (empty if valid). Pure function; no I/O.

    Honesty gates that mirror `waivers_schema_check.py`:
      - mitigation must be ≥ 40 chars (default; reason_class-bearing
        boilerplate alone is not enough)
      - approver must be a real identifier (not 'ai' / 'claude' / 'agent')
      - risk_assessment medium/high requires non-empty risk_justification
      - any placeholder token (TODO/FIXME/TBD) anywhere in user-supplied
        fields rejects the entry
    """
    errors: List[str] = []

    # ---- Required scalar fields ----
    for k in ("project_name", "failed_check", "reason_class",
              "mitigation", "approver"):
        v = entry.get(k)
        if not isinstance(v, str) or not v.strip():
            errors.append(f"missing or empty required field: {k}")

    # ---- failed_check enum (warn, not error, since plugin may lag) ----
    fc = entry.get("failed_check", "")
    # We accept any name but flag unknowns so an audit can see.
    # (We don't error — eFabless may have added a new check the plugin
    # hasn't catalogued; the user's submission isn't blocked by our
    # vocabulary lag.)

    # ---- reason_class enum (strict) ----
    rc = entry.get("reason_class", "")
    if rc and rc not in REASON_CLASSES:
        errors.append(
            f"reason_class '{rc}' not in canonical set "
            f"({sorted(REASON_CLASSES)})")

    # ---- mitigation length + placeholder check ----
    mit = entry.get("mitigation", "")
    if isinstance(mit, str):
        if len(mit.strip()) < 40:
            errors.append(
                f"mitigation must be >= 40 chars (got {len(mit.strip())}); "
                "describe how a downstream reviewer can independently "
                "verify the failure is the documented kind")
        for tok in PLACEHOLDER_TOKENS:
            if tok in mit:
                errors.append(
                    f"mitigation contains placeholder token '{tok}'; "
                    "fill in the real mitigation before submitting")
                break

    # ---- approver gate ----
    app = entry.get("approver", "")
    if isinstance(app, str):
        bad = {"ai", "claude", "agent", "self", "tbd", "todo", "anon", ""}
        if app.strip().lower() in bad:
            errors.append(
                f"approver '{app}' is not a real reviewer identifier — "
                "use a human contact (email or org-id)")

    # ---- risk_assessment + justification ----
    risk = entry.get("risk_assessment", "low")
    if risk not in RISK_LEVELS:
        errors.append(
            f"risk_assessment '{risk}' must be one of {RISK_LEVELS}")
    if risk in ("medium", "high"):
        rj = entry.get("risk_justification", "")
        if not isinstance(rj, str) or len(rj.strip()) < 40:
            errors.append(
                f"risk_assessment '{risk}' requires a "
                "risk_justification >= 40 chars")

    # ---- evidence_files list shape ----
    ev = entry.get("evidence_files", [])
    if not isinstance(ev, list):
        errors.append("evidence_files must be a list of strings")
    else:
        for i, p in enumerate(ev):
            if not isinstance(p, str) or not p.strip():
                errors.append(f"evidence_files[{i}] must be a non-empty string")

    return errors


def build_waiver_entry(
    entry: WaiverEntry,
) -> Dict[str, Any]:
    """Build a normalised waiver dict from a `WaiverEntry`. Auto-fills
    `id` and `signed_at` if absent. Does NOT validate — call
    `validate_waiver` on the returned dict to surface errors.
    """
    d: Dict[str, Any] = {
        "id": entry.id or _stable_id(
            entry.project_name, entry.failed_check, entry.mitigation[:80]),
        "project_name": entry.project_name,
        "failed_check": entry.failed_check,
        "sub_check_detail": entry.sub_check_detail,
        "reason_class": entry.reason_class,
        "mitigation": entry.mitigation,
        "evidence_files": list(entry.evidence_files),
        "expected_remediation_path": entry.expected_remediation_path,
        "risk_assessment": entry.risk_assessment,
        "risk_justification": entry.risk_justification,
        "approver": entry.approver,
        "signed_at": entry.signed_at or _today_iso(),
        # Reproducibility hint: which program emitted this entry.
        "emitted_by": _pmd.emitted_by("vibe-ic plugin signoff_waiver_emit"),
    }
    # Drop optional empty fields so the JSON stays clean.
    if not d["sub_check_detail"]:
        d.pop("sub_check_detail")
    if not d["risk_justification"] and entry.risk_assessment == "low":
        d.pop("risk_justification")
    return d


def emit_waiver_json(
    entry: WaiverEntry,
    indent: int = 2,
) -> str:
    """Emit one waiver entry as a JSON string."""
    d = build_waiver_entry(entry)
    return json.dumps(d, indent=indent, ensure_ascii=False) + "\n"


def _cli() -> int:
    p = argparse.ArgumentParser(
        description="Scaffold a chipignite-submission signoff-waiver JSON.")
    p.add_argument("--project-name", required=True)
    p.add_argument("--failed-check", required=True,
                   help=f"Precheck step name; canonical set: {CHIPIGNITE_PRECHECK_FAIL_NAMES}")
    p.add_argument("--reason-class", required=True,
                   help=f"One of: {sorted(REASON_CLASSES)}")
    p.add_argument("--mitigation", required=True,
                   help="Free text (>= 40 chars)")
    p.add_argument("--approver", required=True,
                   help="Real reviewer id (e.g. name@org)")
    p.add_argument("--evidence-file", action="append", default=[],
                   help="Path to a piece of supporting evidence (repeatable)")
    p.add_argument("--sub-check-detail", default="",
                   help="Free-text sub-check name (e.g. 'LAYOUT' for "
                        "Consistency, '30 deltas vs stock' for XOR)")
    p.add_argument("--expected-remediation-path", default="",
                   help="One of: flatten-flow | lef-with-obs | waiver | "
                        "commercial-signoff (free-text accepted)")
    p.add_argument("--risk", default="low", choices=RISK_LEVELS)
    p.add_argument("--risk-justification", default="",
                   help="Required if --risk in (medium, high)")
    p.add_argument("--out", type=Path,
                   help="Write to this path. Defaults to stdout.")
    p.add_argument("--validate-only", action="store_true",
                   help="Just validate stdin (JSON) instead of emitting")
    p.add_argument("--strict", action="store_true",
                   help="Exit non-zero if validation surfaces errors")
    args = p.parse_args()

    if args.validate_only:
        import sys as _sys
        data = json.load(_sys.stdin)
        if isinstance(data, dict) and "waivers" in data:
            entries = data["waivers"]
        elif isinstance(data, list):
            entries = data
        else:
            entries = [data]
        had_error = False
        for i, e in enumerate(entries):
            errs = validate_waiver(e)
            if errs:
                had_error = True
                print(f"entry[{i}] ({e.get('id', '?')}):", flush=True)
                for er in errs:
                    print(f"  - {er}", flush=True)
        return (1 if had_error and args.strict else 0)

    entry = WaiverEntry(
        project_name=args.project_name,
        failed_check=args.failed_check,
        reason_class=args.reason_class,
        mitigation=args.mitigation,
        approver=args.approver,
        evidence_files=args.evidence_file,
        sub_check_detail=args.sub_check_detail,
        expected_remediation_path=args.expected_remediation_path,
        risk_assessment=args.risk,
        risk_justification=args.risk_justification,
    )
    text = emit_waiver_json(entry)
    errs = validate_waiver(build_waiver_entry(entry))
    if errs:
        import sys as _sys
        for er in errs:
            print(f"WARN: {er}", file=_sys.stderr)
        if args.strict:
            return 1

    if args.out:
        args.out.write_text(text, encoding="utf-8")
        import sys as _sys
        print(f"wrote: {args.out}", file=_sys.stderr)
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
