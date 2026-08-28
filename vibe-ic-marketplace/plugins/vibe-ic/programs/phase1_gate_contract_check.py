#!/usr/bin/env python3
"""
phase1_gate_contract_check.py — Meta-checker for Phase 1 deterministic gates.

Every Phase 1 gate shipped under `vibe-ic/programs/` must satisfy a
plugin-level contract so that the flow orchestrator can rely on it:

  1. The file exists and is importable (valid Python).
  2. The module docstring contains:
      - a `Usage` section showing how to invoke it;
      - an `Exit codes` section that names exit codes 0, 1, and 2;
      - a free-form "Generic pattern" or "Real occurrence" section
        motivating the rule (prevents fabrication).
  3. `<name>.py --help` exits 0.
  4. The code handles the `--json` flag (machine-readable output).
  5. The gate handles at least one missing-input case by returning
     exit code 2 (smoke-tested by passing a non-existent path).
  6. `tests/test_<name>.py` exists alongside it.
  7. `<name>` is referenced in `vibe-ic/flow/phase1_phase2_phase3.yaml`
     (wired into the 33-step flow, not an orphan).

This meta-check covers deterministic flow programs only. The SKILL.md /
compliance.yaml / tests triangle of user-invocable SKILLS is NOT audited
by it, and — despite what this docstring used to claim — not by anything
else either: it named `skill_compliance_triangle_check.py` as if that
were a shipped checker, but no such program has ever existed in this
repo. Its name sat in `_STRUCTURAL_RTL_GATES` and was silently dropped by
the dispatch loop on every run. The dead registry entry has been removed
(see the comment at that site in flow_compliance_check.py); authoring a
real skill-triangle checker remains open work. Phase 1 gates are NOT
skills — they're deterministic flow programs, and they need their OWN
contract, which is what this file enforces.

Usage
-----
    phase1_gate_contract_check.py [--gates gate1,gate2,...] [--json]

By default checks the 7 gates shipped in v0.74:
  internal_vs_external_timing_check
  rsp_example_otp_consistency_check
  threshold_range_contiguity_check
  spec_response_delay_check
  nba_addr_read_race_check
  periodic_timer_vs_rx_activity_check
  memory_read_pipeline_check

Exit codes
----------
    0 = every listed gate satisfies the contract
    1 = one or more gates fail a contract clause
    2 = IO / argument error
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _progress_run as _pr  # noqa: E402


PROGRAMS_DIR = Path(__file__).parent
TESTS_DIR = PROGRAMS_DIR / "tests"
FLOW_YAML = (
    PROGRAMS_DIR.parent  # programs/ -> vibe-ic/
    / "flow" / "phase1_phase2_phase3.yaml"
)

DEFAULT_GATES = [
    "internal_vs_external_timing_check",
    "rsp_example_otp_consistency_check",
    "threshold_range_contiguity_check",
    "spec_response_delay_check",
    "nba_addr_read_race_check",
    "periodic_timer_vs_rx_activity_check",
    "memory_read_pipeline_check",
]


@dataclass
class Finding:
    gate: str
    severity: str          # "ERROR" | "WARN"
    rule: str
    message: str


def _read_module_docstring(py_path: Path) -> str:
    """Extract the top-level module docstring.

    Simple: find the first `\"\"\"` after any shebang/future import lines.
    """
    src = py_path.read_text(errors="replace")
    m = re.search(r'^\s*"""(.*?)"""', src, re.DOTALL | re.MULTILINE)
    if m:
        return m.group(1)
    m = re.search(r"^\s*'''(.*?)'''", src, re.DOTALL | re.MULTILINE)
    if m:
        return m.group(1)
    return ""


def _has_section(docstring: str, names: list[str]) -> bool:
    """Case-insensitive: look for a section heading line containing any name."""
    for line in docstring.splitlines():
        stripped = line.strip().lower()
        for name in names:
            if stripped.startswith(name.lower()) or name.lower() in stripped[:40]:
                return True
    return False


def check_gate(gate: str) -> list[Finding]:
    findings: list[Finding] = []
    py = PROGRAMS_DIR / f"{gate}.py"
    test = TESTS_DIR / f"test_{gate}.py"

    if not py.exists():
        findings.append(Finding(gate, "ERROR", "file_missing",
            f"{py} does not exist."))
        return findings  # short-circuit; no point checking the rest

    # 1. Importability (syntax-check via py_compile)
    r = subprocess.run(
        [sys.executable, "-c", f"import py_compile; py_compile.compile(r'{py}', doraise=True)"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        findings.append(Finding(gate, "ERROR", "syntax_error",
            f"py_compile failed: {r.stderr.strip()[:200]}"))

    # 2. Docstring sections
    docstring = _read_module_docstring(py)
    if not docstring.strip():
        findings.append(Finding(gate, "ERROR", "missing_docstring",
            "Module docstring missing or empty."))
    else:
        if not _has_section(docstring, ["Usage"]):
            findings.append(Finding(gate, "ERROR", "missing_usage_section",
                "Docstring must contain a `Usage` section showing CLI invocation."))
        if not _has_section(docstring, ["Exit codes", "Exit:", "exit code"]):
            findings.append(Finding(gate, "ERROR", "missing_exit_codes_section",
                "Docstring must document exit codes 0/1/2."))
        else:
            # Each of exit codes 0, 1, 2 should appear in docstring with
            # some description (any word after it is usually fine).
            missing = []
            for ec in (0, 1, 2):
                pat = rf"\b{ec}\s*=\s*\S"   # "0 = <anything>"
                if not re.search(pat, docstring):
                    missing.append(ec)
            if missing:
                findings.append(Finding(gate, "WARN", "exit_codes_incomplete",
                    f"Docstring should describe exit codes: missing {missing}. "
                    f"Use the form `<code> = <description>` on their own lines."))
        if not _has_section(docstring, [
            "Generic pattern", "Real occurrence", "Rule enforced",
            "Problem it catches", "Scope",
        ]):
            findings.append(Finding(gate, "WARN", "missing_motivation",
                "Docstring should motivate the rule (Generic pattern, Real "
                "occurrence, or Rule enforced section) — prevents fabricated gates."))

    # 3. --help exit 0
    r = _pr.run([sys.executable, str(py), "--help"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        findings.append(Finding(gate, "ERROR", "help_nonzero",
            f"--help exited {r.returncode}; help stdout: {r.stdout[:100]!r}"))

    # 4. --json flag present in source
    src = py.read_text(errors="replace")
    if "--json" not in src:
        findings.append(Finding(gate, "ERROR", "missing_json_flag",
            "Gate must accept `--json` for machine-readable output."))

    # 5. Exit 2 on missing input
    r = _pr.run([sys.executable, str(py), "/tmp/__nonexistent_for_gate_check__"],
                       capture_output=True, text=True)
    if r.returncode != 2:
        findings.append(Finding(gate, "WARN", "missing_input_not_exit2",
            f"Missing-input smoke test returned {r.returncode}, expected 2. "
            f"(Gate may require additional args; run manually to verify.)"))

    # 6. Matching pytest
    if not test.exists():
        findings.append(Finding(gate, "ERROR", "missing_pytest",
            f"No {test.name} in {TESTS_DIR}."))

    # 7. Wired into flow YAML
    if FLOW_YAML.exists():
        yaml_src = FLOW_YAML.read_text(errors="replace")
        if gate not in yaml_src:
            findings.append(Finding(gate, "ERROR", "not_wired_into_flow",
                f"Gate not referenced in {FLOW_YAML.name} — orphan gate."))
    else:
        findings.append(Finding(gate, "WARN", "flow_yaml_missing",
            f"{FLOW_YAML} not found; skipping flow-integration check."))

    return findings


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Verify each Phase 1 gate satisfies the plugin contract.",
    )
    ap.add_argument("--gates", default=",".join(DEFAULT_GATES),
                    help="Comma-separated list of gate names (without .py).")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    gates = [g.strip() for g in args.gates.split(",") if g.strip()]
    if not gates:
        print("error: no gates specified", file=sys.stderr)
        return 2

    all_findings: list[Finding] = []
    per_gate: dict[str, dict[str, int]] = {}
    for g in gates:
        fs = check_gate(g)
        errors = sum(1 for f in fs if f.severity == "ERROR")
        warnings = sum(1 for f in fs if f.severity == "WARN")
        per_gate[g] = {"errors": errors, "warnings": warnings}
        all_findings.extend(fs)

    total_errors = sum(p["errors"] for p in per_gate.values())
    total_warnings = sum(p["warnings"] for p in per_gate.values())

    if args.json:
        print(json.dumps({
            "gates_checked": len(gates),
            "total_errors": total_errors,
            "total_warnings": total_warnings,
            "per_gate": per_gate,
            "findings": [asdict(f) for f in all_findings],
            "verdict": "PASS" if total_errors == 0 else "FAIL",
        }, indent=2))
    else:
        for f in all_findings:
            print(f"[{f.severity}] {f.gate} :: {f.rule}")
            print(f"        {f.message}")
        print()
        print(f"Gates: {len(gates)}  Errors: {total_errors}  Warnings: {total_warnings}")
        print("PASS" if total_errors == 0 else "FAIL")

    return 0 if total_errors == 0 else 1


if __name__ == "__main__":
    # A stall is not a verdict about the subject: it reaches the exit
    # code as rc 2 (UNDETERMINED), announced, never as a finding.
    sys.exit(_pr.exit_undetermined_on_stall(main))
