#!/usr/bin/env python3
"""
json_schema_check.py — Deterministic JSON schema key checker.

Verifies a JSON file has required top-level (or nested) keys with non-empty values.
Designed for L1-L8 document validation in the Vibe-IC pipeline.

What it catches:
  1. FILE_MISSING — JSON file does not exist
  2. INVALID_JSON — file is not valid JSON
  3. MISSING_KEY — a required key is absent
  4. EMPTY_VALUE — a required key exists but its value is null, "", or []

Usage:
    python3 json_schema_check.py --json-file L1_DATASHEET.json --required-keys "part_number,pins,electrical_specs"
    python3 json_schema_check.py --json-file L5.json --required-keys "signals,clock.frequency"
    python3 json_schema_check.py --json-file L1.json --skill-profile datasheet-gen
    python3 json_schema_check.py --json-file L1.json --skill-profile datasheet-gen --required-keys "extra_key"

Exit codes:
    0 = all keys present and non-empty
    1 = missing or empty keys
    2 = parse error / invalid arguments

Supports dot notation for nested keys (e.g. "clock.frequency" checks data["clock"]["frequency"]).
No external tool dependencies — pure Python.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, List, Tuple


# ---------------------------------------------------------------------------
# Predefined key sets per skill type (used with --skill-profile)
# ---------------------------------------------------------------------------
# Two profile families:
#
#   1. Path B (existing-Design-Documents → Phase 1 (doc-extraction) doc-gen skills):
#      legacy v0.51 skill-name keys. Each doc-gen skill emits one L*.json
#      using its own native key vocabulary. These remain for backward
#      compatibility with Path B's per-skill --skill-profile invocations.
#
#   2. Path A (Prompt → tools/phase1_engine/ fact-graph render): the renderer
#      uses fact-path keys (ic_name, register_map, dtop_top_level, ...)
#      that do NOT match the v0.51 skill keys. Added v0.61 to fix Bug #2:
#      v0.60 had no fact-graph-aware profile, so every Path A
#      `--skill-profile <skill>` invocation FAIL-ed on missing keys that
#      the fact-graph renderer never produces.
#
# When in doubt: keep required keys MINIMAL per layer so the gate doesn't
# false-FAIL on class variants (e.g. memory ICs with no command set, analog
# ICs with no register map). Class-specific structural checks belong in
# phase1_consistency_check.py / spec_floor / qbank, not here.
SKILL_PROFILES = {
    # --- Path B: v0.51 doc-gen skill profiles (kept for backwards compat) ---
    "datasheet-gen": ["part_number", "description", "pin_count", "package"],
    "frs-gen": ["requirements", "functional_description", "operating_modes"],
    "regmap-gen": ["registers", "base_address"],
    "adi-spec-gen": ["analog_digital_boundary", "synchronizer_stages", "voltage_levels"],
    "cmd-protocol-gen": ["commands", "protocol_name", "packet_format"],
    "control-logic-gen": ["states", "transitions", "control_signals"],
    "test-debug-gen": ["test_modes", "entry_conditions", "test_sequence"],
    "timing-waveform-gen": ["waveforms", "timing_parameters", "clock_specification"],

    # --- Path A: fact-graph render profiles (v0.61) ---
    # Universal-minimum keys — class-specific structure validated elsewhere.
    # Wave 32 (v0.119.64) — L11 ownership decree:
    #   - L4 owns: registers + control_bits + otp_layout
    #     (otp_layout: read_map / write_map / lockbits / otp_ip_specs /
    #      trim_registers / mask_sources)
    #   - L11 owns: behavioral_sequences + calibration_tables
    #     (jointly populated by calibration-gen + behavioral-sequences-gen)
    #   - L12 retained as legacy slot for behavioral_sequences (alias)
    "L1":  ["ic_name"],
    "L2":  [],   # FRS structure varies by IC; covered by spec_floor
    "L3":  [],   # protocol_present sentinel OR commands; covered by no_protocol_consistency_check
    "L4":  [],   # registers + otp_layout (Wave 32); class structure covered elsewhere
    "L5":  [],   # ADI signals vary; covered by class qbank
    "L6":  [],   # control logic submodules count covered by spec_floor
    "L7":  [],   # test/debug structure varies; covered by qbank
    "L8":  [],   # timing waveforms vary by protocol; covered by qbank
    "L8R": ["clock_frequency_hz"],
    "L9":  ["dtop_top_level", "submodules"],
    "L10": ["test_cases"],
    # Wave 32 — L11 carries behavioral_sequences and/or calibration_tables.
    # Empty profile because either field satisfies; class-specific
    # structure enforced by l_doc_structured_field_count_check.
    "L11": [],
    "L12": [],   # legacy alias; behavioral_sequences accepted under L11 or L12
    "L13": ["criterion", "tester"],
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class Finding:
    severity: str       # ERROR, WARNING, INFO
    category: str       # FILE_MISSING, INVALID_JSON, MISSING_KEY, EMPTY_VALUE
    message: str
    key: str = ""
    details: str = ""


# ---------------------------------------------------------------------------
# Helper: resolve dot-notation key
# ---------------------------------------------------------------------------
def resolve_key(data: dict, key: str) -> Tuple[bool, Any]:
    """Resolve a dot-notation key path in a nested dict.

    Returns (found: bool, value: Any).
    """
    parts = key.split('.')
    current = data
    for part in parts:
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current


def is_empty(value: Any) -> bool:
    """Check if a value is considered 'empty' (null, "", [], {})."""
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    if isinstance(value, (list, dict)) and len(value) == 0:
        return True
    return False


# ---------------------------------------------------------------------------
# Core audit logic
# ---------------------------------------------------------------------------
def audit_json_keys(
    json_file: Path,
    required_keys: List[str],
) -> Tuple[List[Finding], dict]:
    """Check that a JSON file has all required keys with non-empty values.

    Returns (findings, parsed_data_or_empty).
    """
    findings: List[Finding] = []

    if not json_file.exists():
        findings.append(Finding(
            severity="ERROR",
            category="FILE_MISSING",
            message=f"JSON file does not exist: {json_file}",
        ))
        return findings, {}

    try:
        text = json_file.read_text(errors='replace')
        data = json.loads(text)
    except json.JSONDecodeError as e:
        findings.append(Finding(
            severity="ERROR",
            category="INVALID_JSON",
            message=f"File is not valid JSON: {e}",
            details=str(json_file),
        ))
        return findings, {}

    if not isinstance(data, dict):
        findings.append(Finding(
            severity="ERROR",
            category="INVALID_JSON",
            message="JSON root is not an object (dict)",
            details=f"Got type: {type(data).__name__}",
        ))
        return findings, {}

    for key in required_keys:
        key = key.strip()
        if not key:
            continue
        found, value = resolve_key(data, key)
        if not found:
            findings.append(Finding(
                severity="ERROR",
                category="MISSING_KEY",
                message=f"Required key not found: '{key}'",
                key=key,
            ))
        elif is_empty(value):
            findings.append(Finding(
                severity="ERROR",
                category="EMPTY_VALUE",
                message=f"Required key has empty value: '{key}'",
                key=key,
                details=f"Value: {value!r}",
            ))

    return findings, data


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_report(findings: List[Finding], json_file: str,
                 required_keys: List[str]) -> dict:
    return {
        "program": "json_schema_check",
        "version": "1.1.0",
        "json_file": json_file,
        "summary": {
            "required_keys": required_keys,
            "findings_count": len(findings),
            "pass": len(findings) == 0,
        },
        "findings": [asdict(f) for f in findings],
    }


def main(argv: list = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify JSON file has required keys with non-empty values"
    )
    parser.add_argument('--json-file', required=True,
                        help="Path to the JSON file to validate")
    parser.add_argument('--required-keys', default=None,
                        help="Comma-separated list of required keys (supports dot notation)")
    parser.add_argument('--skill-profile', default=None,
                        help="Skill profile name to load predefined required keys "
                             f"(choices: {', '.join(SKILL_PROFILES)})")
    parser.add_argument('--json', default=None,
                        help="Output JSON report path")
    args = parser.parse_args(argv)

    # Build required_keys from --required-keys and/or --skill-profile
    required_keys: list[str] = []
    if args.required_keys:
        required_keys.extend(k for k in args.required_keys.split(',') if k.strip())

    profile_explicitly_empty = False
    if args.skill_profile:
        profile_name = args.skill_profile.strip()
        if profile_name in SKILL_PROFILES:
            profile_keys = SKILL_PROFILES[profile_name]
            # An explicitly-empty profile (e.g. fact-graph L2) means
            # "no universal required keys for this layer" — class-specific
            # structure is enforced elsewhere. PASS rather than error.
            if not profile_keys and not args.required_keys:
                profile_explicitly_empty = True
            # Merge profile keys (deduplicate while preserving order)
            for k in profile_keys:
                if k not in required_keys:
                    required_keys.append(k)
        else:
            print(
                f"WARNING: Unknown skill profile '{profile_name}'. "
                f"Available profiles: {', '.join(SKILL_PROFILES)}",
                file=sys.stderr,
            )

    if not required_keys and not profile_explicitly_empty:
        print("ERROR: No required keys specified. "
              "Use --required-keys and/or --skill-profile.", file=sys.stderr)
        return 2

    json_file = Path(args.json_file)
    findings, _ = audit_json_keys(json_file, required_keys)

    report = build_report(findings, str(json_file), required_keys)
    report_json = json.dumps(report, indent=2, ensure_ascii=False)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(report_json)

    print(report_json)
    return 0 if report["summary"]["pass"] else 1


if __name__ == '__main__':
    sys.exit(main())
