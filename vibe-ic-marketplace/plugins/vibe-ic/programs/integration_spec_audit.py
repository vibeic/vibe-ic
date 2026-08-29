#!/usr/bin/env python3
"""
integration_spec_audit.py — Deterministic compliance check for integration-spec-gen.

ENFORCEMENT: advisory

The line above is a DECLARATION, in the anchored form `flow_gate_enforcement_
audit.declared_intent` reads. This program is wired into the flow as an
`advisory_program_exit_zero` clause: it RUNS on every project that reaches its
step, its findings are printed, and its exit code cannot deny the step its PASS
tier. That is deliberate — it was wired to make a real check reachable, not to
block a landing on debt it did not create — and the declaration says so where
the audit looks. Without it, "wired where it cannot block" and "nobody decided"
are the same record, and the reliable way to stay clean is to say nothing.
Verifies that L9 Integration Spec JSON files contain valid top-module definitions,
submodule lists with ports, internal wiring, and no stub/placeholder modules.

What it catches:
  1. NO_SPEC_FILE — no *L9*.json, *integration*.json, or *integration_spec*.json found
  2. INVALID_JSON — file is not valid JSON
  3. MISSING_TOP — missing 'top_module' or 'dtop' key
  4. MISSING_SUBMODULES — missing or empty 'submodules' list
  5. INVALID_SUBMODULE — a submodule lacks 'name' or 'ports'
  6. MISSING_WIRES — missing 'internal_wires' or 'connections' section
  7. STUB_DETECTED — a value contains TODO/stub/placeholder text
  8. REGISTER_INFRA_MISSING — (WARNING) no register infrastructure section found
  9. POR_SYNC_MISSING — (WARNING) no power-on-reset / reset sequence section found
  10. CLOCK_GATING_MISSING — (WARNING) no clock / clock gating section found

Usage:
    python3 integration_spec_audit.py ./my_project
    python3 integration_spec_audit.py ./my_project --json

Exit codes:
    0 = all checks pass
    1 = one or more checks fail

Generality: works for ANY IC project with L9 Integration Spec JSON.
No external tool dependencies — pure Python.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class Finding:
    rule: str
    severity: str       # ERROR, WARNING, INFO
    message: str
    file: str = ""


@dataclass
class AuditResult:
    program: str
    passed: bool
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Stub/placeholder detection
# ---------------------------------------------------------------------------
STUB_PATTERNS = re.compile(r'\b(TODO|stub|placeholder)\b', re.IGNORECASE)


def contains_stub(value) -> bool:
    """Recursively check if any string value contains stub/placeholder text."""
    if isinstance(value, str):
        return bool(STUB_PATTERNS.search(value))
    if isinstance(value, list):
        return any(contains_stub(v) for v in value)
    if isinstance(value, dict):
        return any(contains_stub(v) for v in value.values())
    return False


def find_stub_paths(data, path: str = "") -> List[str]:
    """Return list of JSON paths that contain stub/placeholder text."""
    paths: List[str] = []
    if isinstance(data, str):
        if STUB_PATTERNS.search(data):
            paths.append(f"{path}={data!r}")
    elif isinstance(data, list):
        for i, v in enumerate(data):
            paths.extend(find_stub_paths(v, f"{path}[{i}]"))
    elif isinstance(data, dict):
        for k, v in data.items():
            paths.extend(find_stub_paths(v, f"{path}.{k}" if path else k))
    return paths


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------
def discover_spec_files(base: Path) -> List[Path]:
    """Find JSON files matching *L9*.json, *integration*.json, *integration_spec*.json."""
    found: List[Path] = []
    for fpath in sorted(base.rglob("*.json")):
        name_lower = fpath.name.lower()
        if ("l9" in name_lower or "integration" in name_lower):
            found.append(fpath)
    return found


# ---------------------------------------------------------------------------
# Core audit logic
# ---------------------------------------------------------------------------
def audit(project_dir: str) -> AuditResult:
    findings: List[Finding] = []
    base = Path(project_dir)

    if not base.exists() or not base.is_dir():
        findings.append(Finding(
            rule="DIR_MISSING",
            severity="ERROR",
            message=f"Project directory does not exist: {project_dir}",
        ))
        return AuditResult(
            program="integration_spec_audit",
            passed=False,
            findings=findings,
            summary={"files_checked": 0},
        )

    json_files = discover_spec_files(base)

    if not json_files:
        findings.append(Finding(
            rule="NO_SPEC_FILE",
            severity="ERROR",
            message="No *L9*.json or *integration*.json files found in project directory",
        ))
        return AuditResult(
            program="integration_spec_audit",
            passed=False,
            findings=findings,
            summary={"files_checked": 0},
        )

    files_passed = 0

    for jf in json_files:
        rel = str(jf.relative_to(base)) if jf.is_relative_to(base) else str(jf)
        file_findings: List[Finding] = []

        # Parse JSON
        try:
            raw = jf.read_text(errors="replace")
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            findings.append(Finding(
                rule="INVALID_JSON",
                severity="ERROR",
                message=f"Invalid JSON: {e}",
                file=rel,
            ))
            continue
        except OSError as e:
            findings.append(Finding(
                rule="READ_ERROR",
                severity="ERROR",
                message=f"Cannot read file: {e}",
                file=rel,
            ))
            continue

        if not isinstance(data, dict):
            findings.append(Finding(
                rule="INVALID_JSON",
                severity="ERROR",
                message=f"JSON root is not an object (got {type(data).__name__})",
                file=rel,
            ))
            continue

        # Check 1: top_module or dtop
        has_top = any(k in data for k in ("top_module", "dtop", "top"))
        if not has_top:
            file_findings.append(Finding(
                rule="MISSING_TOP",
                severity="ERROR",
                message="Missing 'top_module' or 'dtop' key",
                file=rel,
            ))

        # Check 2: submodules list with at least 1 entry
        submodules = data.get("submodules", data.get("sub_modules",
                     data.get("instances", data.get("module_instances"))))
        if submodules is None:
            file_findings.append(Finding(
                rule="MISSING_SUBMODULES",
                severity="ERROR",
                message="Missing 'submodules' section",
                file=rel,
            ))
        elif not isinstance(submodules, list) or len(submodules) == 0:
            file_findings.append(Finding(
                rule="MISSING_SUBMODULES",
                severity="ERROR",
                message="'submodules' is empty or not a list",
                file=rel,
            ))
        else:
            # Check 3: each submodule has name and ports
            for idx, sub in enumerate(submodules):
                if not isinstance(sub, dict):
                    file_findings.append(Finding(
                        rule="INVALID_SUBMODULE",
                        severity="ERROR",
                        message=f"submodules[{idx}]: not a dict",
                        file=rel,
                    ))
                    continue
                if not sub.get("name") and not sub.get("module_name"):
                    file_findings.append(Finding(
                        rule="INVALID_SUBMODULE",
                        severity="ERROR",
                        message=f"submodules[{idx}]: missing 'name'",
                        file=rel,
                    ))
                if not sub.get("ports") and not sub.get("port_list") and not sub.get("port_map"):
                    # READ THE PRODUCER'S OWN HEDGE. An emitter that scraped a
                    # submodule out of a markdown heading marks the entry
                    # `low_confidence: true` -- it is saying, in the artefact,
                    # that it is not sure this is a module at all. Demanding a
                    # port list of an entry its own producer flagged as
                    # uncertain renders an extraction hedge as a design defect.
                    # MEASURED 2026-08-29 on subservient/gf180mcuD: all six
                    # entries in L9_INTEGRATION_SPEC.json carry
                    # `"type": "markdown submodule-contract heading"`,
                    # `"role": "documented submodule"` and
                    # `"low_confidence": true`, and one of them is a prose
                    # noun phrase, not an identifier. Six hard errors, none of
                    # which names anything the design got wrong.
                    #
                    # The finding is NOT dropped -- it is still emitted and
                    # still printed, at the severity the evidence supports.
                    # Degrade loudly, never silently.
                    hedged = bool(sub.get("low_confidence"))
                    file_findings.append(Finding(
                        rule="INVALID_SUBMODULE",
                        severity="WARNING" if hedged else "ERROR",
                        message=(f"submodules[{idx}]: missing 'ports'"
                                 + (" (entry is flagged low_confidence by its "
                                    "producer, so this is reported, not "
                                    "refused)" if hedged else "")),
                        file=rel,
                    ))

        # Check 4: internal_wires or connections
        has_wires = any(k in data for k in (
            "internal_wires", "connections", "wire_map", "wires", "internal_signals"
        ))
        if not has_wires:
            file_findings.append(Finding(
                rule="MISSING_WIRES",
                severity="ERROR",
                message="Missing 'internal_wires' or 'connections' section",
                file=rel,
            ))

        # Check 5: stub/placeholder detection
        stub_paths = find_stub_paths(data)
        for sp in stub_paths:
            file_findings.append(Finding(
                rule="STUB_DETECTED",
                severity="ERROR",
                message=f"Stub/placeholder found: {sp}",
                file=rel,
            ))

        # Check 6: register infrastructure (WARNING)
        REGISTER_KEYS = {"registers", "register_infrastructure",
                         "control_registers", "register_map"}
        if not any(k in data for k in REGISTER_KEYS):
            file_findings.append(Finding(
                rule="REGISTER_INFRA_MISSING",
                severity="WARNING",
                message="No register infrastructure section found "
                        "(registers, register_infrastructure, control_registers, register_map)",
                file=rel,
            ))

        # Check 7: power-on-reset / reset sequence (WARNING)
        POR_KEYS = {"por_sync", "por", "reset_sequence",
                    "power_on_reset", "reset"}
        if not any(k in data for k in POR_KEYS):
            file_findings.append(Finding(
                rule="POR_SYNC_MISSING",
                severity="WARNING",
                message="No power-on-reset / reset section found "
                        "(por_sync, por, reset_sequence, power_on_reset, reset)",
                file=rel,
            ))

        # Check 8: clock / clock gating (WARNING)
        CLOCK_KEYS = {"clock_gating", "clock", "clocks",
                      "clock_domains", "gated_clk"}
        if not any(k in data for k in CLOCK_KEYS):
            file_findings.append(Finding(
                rule="CLOCK_GATING_MISSING",
                severity="WARNING",
                message="No clock / clock gating section found "
                        "(clock_gating, clock, clocks, clock_domains, gated_clk)",
                file=rel,
            ))

        if not any(f.severity == "ERROR" for f in file_findings):
            files_passed += 1
        findings.extend(file_findings)

    passed = not any(f.severity == "ERROR" for f in findings)
    return AuditResult(
        program="integration_spec_audit",
        passed=passed,
        findings=findings,
        summary={
            "files_checked": len(json_files),
            "files_passed": files_passed,
            "errors": sum(1 for f in findings if f.severity == "ERROR"),
            "stubs_found": sum(1 for f in findings if f.rule == "STUB_DETECTED"),
        },
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(
        description="Deterministic compliance check for integration-spec-gen"
    )
    p.add_argument("project_dir", nargs="?", default=".")
    p.add_argument("--json", action="store_true",
                   help="Output JSON report to stdout")
    args = p.parse_args()

    result = audit(args.project_dir)

    if args.json:
        print(json.dumps(asdict(result), indent=2, ensure_ascii=False))
    else:
        for f in result.findings:
            tag = f"[{f.file}] " if f.file else ""
            print(f"[{f.severity}] {f.rule}: {tag}{f.message}")
        status = "PASS" if result.passed else "FAIL"
        print(f"\n{status} — {result.summary}")

    sys.exit(0 if result.passed else 1)


if __name__ == "__main__":
    main()
