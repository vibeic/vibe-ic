#!/usr/bin/env python3
"""
phase1_structured_field_substance_check.py — Tier-2 sibling of the
existing token-presence completeness gate.

Background — closes GitHub issue #4 partial scope
=================================================
The Tier-1 gate (`phase1_doc_input_completeness_check`)
audits whether tokens harvested from input docs appear ANYWHERE in
the union of generated_docs/L*.json — including the
``auto_discovered_identifiers`` catch-all that downstream consumers
do not read. The result: 7/10 thin-input projects PASSed Tier-1
at 96-100% while every structured field downstream consumers
actually query was at template default (``ic_name=UNKNOWN_IC``,
``protocol_overview={"half_duplex":false,"wire_count":2,...}``,
``opcodes=[{"hex":"0x00","name":"RESERVED",...}]`` etc.). The
phase2 classifier then substring-grepped that boilerplate and
mis-routed every IC into the AID generator (separate fix in #1/#2).

Tier-2 audits structured-field SUBSTANCE: for each L doc, check
whether the fields downstream consumers query carry real
extraction or template-default scaffolding.

Detection (chip-AGNOSTIC, declarative)
======================================
For each L doc, ``_TEMPLATE_DEFAULTS`` enumerates field paths whose
known default-value is a flag for "extractor returned no evidence".
A field is flagged as scaffolding when:

  * its value equals the literal default (e.g. ``UNKNOWN_IC``,
    ``__TODO__``, single-element opcode list with name ``RESERVED``)
  * AND no sibling ``no_<field>_in_input: true`` flag is set
    (the existing escape valve for L5 ``no_analog`` /
    L11 ``no_calibration``; generalised here)

Verdict tiers
=============
  PASS         — every audited field carries non-default content,
                 OR the corresponding ``no_<field>_in_input`` flag
                 is set.
  WARN         — 1+ fields at default WITHOUT a ``no_<field>_in_input``
                 flag, but ≤ 30% of audited fields total. Diagnostic
                 (informational) — input might be intrinsically thin.
  FAIL         — > 30% of audited fields at default WITHOUT the flag.
                 Indicates the L-doc generators degraded into
                 template scaffolding rather than extracting from
                 the real input.
  VACUOUS_PASS — generated_docs/ absent (Phase 1 (doc-extraction) not yet run).

Usage
=====
    python3 phase1_structured_field_substance_check.py <project_dir>
                                                         [--json <out>]

Exit codes
    0  PASS / WARN / VACUOUS_PASS
    1  FAIL
    2  argument or I/O error

chip-AGNOSTIC. ``_TEMPLATE_DEFAULTS`` is the only knob; no chip /
vendor / specific protocol is hardcoded. Add a new field by
appending one entry per L doc.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# Per-field substance audit. Each entry maps an L-doc name to a list
# of (field_path, default_value_or_predicate) tuples.
#
# `field_path` is a dotted path (e.g. "ic_name", "protocol_overview.half_duplex_default").
# `default_predicate` is one of:
#   * a primitive value      → equality check
#   * "__TODO__"             → exact substring match in JSON serialisation
#   * "scaffolding_opcodes"  → opcodes list of length 1 with name=RESERVED
#                              (the canonical thin-input scaffold)
#   * "scaffolding_pin_table" → pin_table single placeholder entry
#   * "empty_list"           → value is `[]`
#   * "default_protocol"     → protocol_overview matches the canonical
#                              boilerplate {"half_duplex":false,
#                              "wire_count":2, "byte_order":"LSB-first",
#                              "wake_required_pre_command":true}
#
# The list of mandatory fields per L-doc is consciously SHORT — we
# audit only the fields downstream consumers (ic_class detector,
# rtl_gen, signoff manifests) actually query. Surface area = controlled.
_TEMPLATE_DEFAULTS: Dict[str, List[Tuple[str, Any]]] = {
    "L1_DATASHEET": [
        ("ic_name", "UNKNOWN_IC"),
        ("pin_table", "scaffolding_pin_table"),
        ("electrical_specs", "empty_list"),
    ],
    "L2_FRS": [
        ("protocol_overview", "default_protocol"),
    ],
    "L3_CMD_PROTOCOL": [
        ("opcodes", "scaffolding_opcodes"),
    ],
    "L6_CONTROL_LOGIC": [
        ("fsm_states", "scaffolding_fsm_5"),
    ],
}


@dataclass
class FieldFinding:
    layer: str            # L1_DATASHEET / L2_FRS / etc
    field_path: str       # ic_name / protocol_overview / opcodes
    rule: str             # which template-default rule fired
    observed: Any = None  # the value that fired
    has_no_input_flag: bool = False  # whether the escape-valve flag is set


def _walk(obj: Any, dotted: str) -> Any:
    cur = obj
    for k in dotted.split("."):
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return None
    return cur


def _flag_set(obj: Any, field_path: str) -> bool:
    """Look for the canonical `no_<field>_in_input: true` escape
    valve, both at the top-level (e.g. `no_analog`) and nested
    inside the field's parent dict."""
    if not isinstance(obj, dict):
        return False
    base_field = field_path.split(".")[-1]
    flag_keys = (
        f"no_{base_field}_in_input",
        f"no_{base_field}",
        f"{base_field}_absent_in_input",
    )
    # Top-level
    for k in flag_keys:
        if obj.get(k) is True:
            return True
    # Nested: walk to the parent of the field and check there.
    parts = field_path.split(".")
    if len(parts) >= 2:
        parent = _walk(obj, ".".join(parts[:-1]))
        if isinstance(parent, dict):
            for k in flag_keys:
                if parent.get(k) is True:
                    return True
    return False


def _matches_default(value: Any, rule: Any) -> bool:
    """Return True iff `value` matches the rule (= scaffolding)."""
    if isinstance(rule, str):
        if rule == "empty_list":
            return value == []
        if rule == "__TODO__":
            return (
                isinstance(value, str) and "__TODO__" in value
            ) or (
                # Common shape: list of dicts whose values include __TODO__.
                isinstance(value, list)
                and all(isinstance(x, dict) and any(
                    isinstance(v, str) and "__TODO__" in v
                    for v in x.values()
                ) for x in value)
            )
        if rule == "scaffolding_opcodes":
            return (
                isinstance(value, list) and len(value) == 1
                and isinstance(value[0], dict)
                and value[0].get("name", "").upper() == "RESERVED"
            )
        if rule == "scaffolding_pin_table":
            if not isinstance(value, list):
                return False
            if len(value) == 0:
                return True
            # Single placeholder entry, all values "__TODO__"
            if len(value) == 1 and isinstance(value[0], dict):
                vals = list(value[0].values())
                if all(isinstance(v, str) and v == "__TODO__"
                       for v in vals):
                    return True
            return False
        if rule == "scaffolding_fsm_5":
            # 5 placeholder states with name RESERVED / IDLE / etc
            # only. Five is the suspicious-uniformity count cited in
            # the issue.
            if not isinstance(value, list):
                return False
            if len(value) != 5:
                return False
            placeholder_names = {"S0", "S1", "S2", "S3", "S4",
                                 "IDLE", "RESERVED", "STATE_0",
                                 "STATE_1", "STATE_2"}
            names = [s.get("name", "") if isinstance(s, dict) else str(s)
                     for s in value]
            return all(n in placeholder_names for n in names)
        if rule == "default_protocol":
            if not isinstance(value, dict):
                return False
            # The canonical thin-input scaffold:
            # Defensive: .get("byte_order", "") returns "" only when the
            # key is absent. If the key is present with value=None, the
            # default-arg branch is skipped and we get None.upper(). Use
            # `or ""` to coerce both None and absent to a safe empty
            # string before .upper() (sha256_v2_e2e e2e finding).
            return (
                value.get("half_duplex") is False
                and value.get("wire_count") in (1, 2)
                and (value.get("byte_order") or "").upper().startswith("LSB")
                and value.get("wake_required_pre_command") is True
            )
        # Fallback: treat as literal substring match in JSON.
        try:
            return rule in json.dumps(value, ensure_ascii=False)
        except Exception:
            return False
    # Primitive: equality.
    return value == rule


def _load_l_doc(gen_dir: Path, layer_prefix: str) -> Optional[Dict[str, Any]]:
    """Find the first matching L doc file (L1_*.json etc) and return
    its parsed content, or None."""
    for cand in sorted(gen_dir.glob(f"{layer_prefix}_*.json")):
        try:
            return json.loads(cand.read_text(errors="ignore"))
        except Exception:
            continue
    return None


def audit(project: Path) -> Tuple[str, List[FieldFinding], Dict[str, Any]]:
    summary: Dict[str, Any] = {
        "fields_audited": 0,
        "fields_at_default": 0,
        "fields_with_no_input_flag": 0,
        "default_pct": 0.0,
    }
    findings: List[FieldFinding] = []

    gen_dir = project / "phase1" / "generated_docs"
    if not gen_dir.is_dir():
        # Try legacy location.
        gen_dir = project / "generated_docs"
    if not gen_dir.is_dir():
        return "VACUOUS_PASS", [], summary

    for layer, fields in _TEMPLATE_DEFAULTS.items():
        # Strip the "_*" suffix when looking up by prefix.
        prefix = layer.split("_")[0] + "_" + layer.split("_", 1)[1]
        # Try the exact filename first, then the prefix glob.
        f_exact = gen_dir / f"{layer}.json"
        if f_exact.is_file():
            try:
                doc = json.loads(f_exact.read_text(errors="ignore"))
            except Exception:
                doc = None
        else:
            doc = _load_l_doc(gen_dir, layer.split("_")[0])
        if doc is None:
            continue
        for field_path, rule in fields:
            summary["fields_audited"] += 1
            value = _walk(doc, field_path)
            has_flag = _flag_set(doc, field_path)
            if has_flag:
                summary["fields_with_no_input_flag"] += 1
                continue
            if value is None:
                # Field absent without flag — count as at-default.
                summary["fields_at_default"] += 1
                findings.append(FieldFinding(
                    layer=layer, field_path=field_path,
                    rule="field_absent_no_flag",
                    observed=None, has_no_input_flag=False))
                continue
            if _matches_default(value, rule):
                summary["fields_at_default"] += 1
                findings.append(FieldFinding(
                    layer=layer, field_path=field_path,
                    rule=str(rule), observed=value,
                    has_no_input_flag=False))

    n_audited = summary["fields_audited"]
    if n_audited == 0:
        return "VACUOUS_PASS", [], summary
    summary["default_pct"] = round(
        summary["fields_at_default"] / n_audited * 100, 1)
    if summary["fields_at_default"] == 0:
        return "PASS", findings, summary
    if summary["default_pct"] > 30.0:
        return "FAIL", findings, summary
    return "WARN", findings, summary


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Tier-2 phase1 substance audit: detect template-"
                    "default scaffolding in mandatory L-doc fields.")
    ap.add_argument("project_dir")
    ap.add_argument("--json", help="write JSON report to this path")
    args = ap.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"error: project dir not found: {project}", file=sys.stderr)
        return 2

    verdict, findings, summary = audit(project)
    report = {
        "gate": "phase1_structured_field_substance_check",
        "verdict": verdict,
        "project": str(project),
        "audit_table": {
            layer: [{"field_path": fp, "rule": str(r)}
                    for fp, r in fields]
            for layer, fields in _TEMPLATE_DEFAULTS.items()
        },
        "summary": summary,
        "findings_count": len(findings),
        "findings": [asdict(f) for f in findings],
    }
    canonical_out = project / "reports" / "phase1" \
        / "structured_field_substance.json"
    canonical_out.parent.mkdir(parents=True, exist_ok=True)
    canonical_out.write_text(json.dumps(report, indent=2,
                                         ensure_ascii=False) + "\n")
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n")

    print(f"{verdict}: phase1_structured_field_substance_check — "
          f"audited={summary['fields_audited']}, "
          f"at_default={summary['fields_at_default']} "
          f"({summary['default_pct']}%), "
          f"with_no_input_flag={summary['fields_with_no_input_flag']}")
    if verdict in ("WARN", "FAIL"):
        for f in findings:
            print(f"  [{f.rule}] {f.layer}.{f.field_path}: "
                  f"observed={json.dumps(f.observed, ensure_ascii=False)[:80]}")
    return 1 if verdict == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
