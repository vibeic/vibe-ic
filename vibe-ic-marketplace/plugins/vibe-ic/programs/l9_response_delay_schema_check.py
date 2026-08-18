#!/usr/bin/env python3
"""l9_response_delay_schema_check.py — R5 L9 spec mandate

For any module in L9 Integration Spec whose role is "command dispatcher"
or "response generator" on a half-duplex bus, require the
`response_delay` block with correct schema:

    modules:
      <dispatcher>:
        response_delay:
          required: true
          spec_constant: <name-from-L2>
          reference_event: end_of_trailing_delimiter
          min_cycles: <integer>

Validates:
  1. MISSING_RESPONSE_DELAY — dispatcher module lacks `response_delay` block
  2. WRONG_REFERENCE_EVENT — reference_event is cmd_valid/validation_pass
     (early-fire cases) instead of end_of_trailing_delimiter
  3. MISSING_SPEC_CONSTANT — no spec_constant field linking to L2
  4. MISSING_MIN_CYCLES — no min_cycles field

Usage:
    python3 l9_response_delay_schema_check.py <L9_INTEGRATION_SPEC.json>
    python3 l9_response_delay_schema_check.py <L9_INTEGRATION_SPEC.json> --json

Exit codes:
    0 = all dispatcher modules have valid response_delay
    1 = one or more violations
    2 = IO / parse error
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List

DISPATCHER_ROLE_HINTS = (
    "dispatcher", "response_generator", "command_handler",
    "cmd_dispatcher", "resp_gen", "protocol_controller",
    "bus_controller", "frame_handler",
)

HALF_DUPLEX_HINTS = (
    "half_duplex", "half-duplex", "single_wire", "single-wire",
    "one_wire", "1-wire", "shared_bus", "bidirectional_bus",
)

EARLY_FIRE_EVENTS = (
    "cmd_valid", "validation_pass", "validate_pass",
    "cmd_received", "frame_valid", "cmd_complete",
)

ALLOWED_REFERENCE_EVENTS = (
    "end_of_trailing_delimiter", "delimiter_release",
    "trailing_break_end", "bus_idle_detected",
    "end_of_frame_delimiter", "trailing_delimiter_end",
)


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    module: str = ""


@dataclass
class AuditResult:
    program: str = "l9_response_delay_schema_check"
    passed: bool = True
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def is_dispatcher_module(mod_name: str, mod_data: dict) -> bool:
    name_lower = mod_name.lower()
    for hint in DISPATCHER_ROLE_HINTS:
        if hint in name_lower:
            return True
    role = str(mod_data.get("role", "")).lower()
    for hint in DISPATCHER_ROLE_HINTS:
        if hint in role:
            return True
    desc = str(mod_data.get("description", "")).lower()
    for hint in DISPATCHER_ROLE_HINTS:
        if hint in desc:
            return True
    return False


def is_half_duplex_context(data: dict) -> bool:
    text = json.dumps(data).lower()
    for hint in HALF_DUPLEX_HINTS:
        if hint in text:
            return True
    return False


def validate_response_delay(mod_name: str, rd: dict, findings: List[Finding]) -> bool:
    ok = True

    if not rd.get("required", False) and rd.get("required") is not True:
        findings.append(Finding(
            rule="RESPONSE_DELAY_NOT_REQUIRED",
            severity="WARNING",
            message=f"response_delay.required is not true — consider setting to true for half-duplex protocol",
            module=mod_name,
        ))

    ref_event = rd.get("reference_event", "")
    if not ref_event:
        ok = False
        findings.append(Finding(
            rule="MISSING_REFERENCE_EVENT",
            severity="ERROR",
            message=f"response_delay missing reference_event field",
            module=mod_name,
        ))
    elif ref_event.lower() in [e.lower() for e in EARLY_FIRE_EVENTS]:
        ok = False
        findings.append(Finding(
            rule="WRONG_REFERENCE_EVENT",
            severity="ERROR",
            message=(
                f"response_delay.reference_event='{ref_event}' is an early-fire event. "
                f"Must use end_of_trailing_delimiter (or equivalent). "
                f"Starting delay from {ref_event} fires BEFORE the delimiter is fully released."
            ),
            module=mod_name,
        ))
    elif ref_event.lower() not in [e.lower() for e in ALLOWED_REFERENCE_EVENTS]:
        findings.append(Finding(
            rule="UNRECOGNIZED_REFERENCE_EVENT",
            severity="WARNING",
            message=(
                f"response_delay.reference_event='{ref_event}' not in recognized list. "
                f"Accepted: {', '.join(ALLOWED_REFERENCE_EVENTS)}"
            ),
            module=mod_name,
        ))

    if "spec_constant" not in rd:
        ok = False
        findings.append(Finding(
            rule="MISSING_SPEC_CONSTANT",
            severity="ERROR",
            message="response_delay missing spec_constant field linking to L2 timing",
            module=mod_name,
        ))

    if "min_cycles" not in rd:
        ok = False
        findings.append(Finding(
            rule="MISSING_MIN_CYCLES",
            severity="ERROR",
            message="response_delay missing min_cycles field (integer in fabric clocks)",
            module=mod_name,
        ))
    elif not isinstance(rd.get("min_cycles"), int) or rd["min_cycles"] < 1:
        ok = False
        findings.append(Finding(
            rule="INVALID_MIN_CYCLES",
            severity="ERROR",
            message=f"response_delay.min_cycles must be positive integer, got: {rd.get('min_cycles')}",
            module=mod_name,
        ))

    return ok


def run_audit(l9_path: Path) -> AuditResult:
    result = AuditResult()

    try:
        data = json.loads(l9_path.read_text())
    except Exception as e:
        result.passed = False
        result.findings.append(Finding(
            rule="PARSE_ERROR",
            severity="ERROR",
            message=f"Cannot parse L9 JSON: {e}",
        ))
        return result

    if not is_half_duplex_context(data):
        result.findings.append(Finding(
            rule="NOT_HALF_DUPLEX",
            severity="INFO",
            message="No half-duplex indicators found in L9; response_delay check not applicable",
        ))
        result.summary = {"modules_checked": 0, "dispatchers": 0, "violations": 0}
        return result

    modules = data.get("modules", {})
    if isinstance(modules, list):
        modules = {m.get("name", f"module_{i}"): m for i, m in enumerate(modules)}

    dispatchers_found = 0
    violations = 0

    for mod_name, mod_data in modules.items():
        if not isinstance(mod_data, dict):
            continue
        if not is_dispatcher_module(mod_name, mod_data):
            continue

        dispatchers_found += 1
        rd = mod_data.get("response_delay")

        if rd is None:
            violations += 1
            result.passed = False
            result.findings.append(Finding(
                rule="MISSING_RESPONSE_DELAY",
                severity="ERROR",
                message=(
                    f"Dispatcher module '{mod_name}' on half-duplex bus "
                    f"missing response_delay block. Must specify: "
                    f"required, spec_constant, reference_event (=end_of_trailing_delimiter), min_cycles."
                ),
                module=mod_name,
            ))
        elif isinstance(rd, dict):
            if not validate_response_delay(mod_name, rd, result.findings):
                violations += 1
                result.passed = False

    if dispatchers_found == 0:
        result.findings.append(Finding(
            rule="NO_DISPATCHERS",
            severity="INFO",
            message="No dispatcher/response-generator modules identified in L9",
        ))

    result.summary = {
        "modules_total": len(modules),
        "dispatchers": dispatchers_found,
        "violations": violations,
    }
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("l9_path", type=Path, help="Path to L9_INTEGRATION_SPEC.json")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if not args.l9_path.is_file():
        print(f"ERROR: {args.l9_path} not found", file=sys.stderr)
        return 2

    result = run_audit(args.l9_path)

    if args.json:
        print(json.dumps(asdict(result), indent=2))
    else:
        status = "PASS" if result.passed else "FAIL"
        print(f"[{status}] l9_response_delay_schema_check")
        s = result.summary
        print(f"  Modules: {s.get('modules_total', 0)}, Dispatchers: {s.get('dispatchers', 0)}, Violations: {s.get('violations', 0)}")
        for f in result.findings:
            if f.severity in ("ERROR", "WARNING"):
                mod = f" [{f.module}]" if f.module else ""
                print(f"  [{f.severity}] {f.rule}{mod}: {f.message}")

    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
