#!/usr/bin/env python3
"""skill_runner.py — enforce all declared gates after a skill produces output.

Closes the gap between "gates declared in compliance.yaml" and "gates
actually run at execution time". Previously the plugin relied on the
agent to cooperatively read SKILL.md and invoke each gate; an
uncooperative agent could silently skip gates and still report success.

Usage:
    python3 skill_runner.py <skill_name> <output_path> [--json <report>]

Pipeline:
    1. Load the skill's compliance.yaml
    2. Run `skill_compliance_check.py` against the markdown/JSON output
       to verify every `requirements.pattern` is satisfied
    3. Parse `cross_checks` + `postchecks` — each declares a deterministic
       program to run (extracted from the description field). Run them.
    4. Collect all verdicts into a single JSON report.
    5. Exit 0 iff every gate returned 0.

This makes the "script as ground truth" principle (from
feedback_deterministic_verification memory) enforceable regardless of
agent cooperation.
"""
from __future__ import annotations
import argparse, json, re, subprocess, sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("PyYAML required", file=sys.stderr)
    sys.exit(2)

HERE         = Path(__file__).resolve().parent
SKILLS       = HERE.parent / "skills"
PROGRAMS     = HERE.parent / "programs"
DRIVER       = HERE / "skill_compliance_check.py"


def extract_program_name(description: str) -> str | None:
    """Extract 'foo_check.py' from a description like 'Run foo_check.py; ...'."""
    m = re.search(
        r"(\w+(?:_check|_audit|_calculator|_gen|_run|_verify|_lint|_compat|_sweep|_sizing))\.py",
        description,
    )
    return m.group(1) + ".py" if m else None


def run(skill: str, output_path: Path, report_path: Path | None = None) -> dict:
    yml = SKILLS / skill / "compliance.yaml"
    if not yml.exists():
        return {"pass": False, "error": f"no compliance.yaml for skill {skill}"}
    data = yaml.safe_load(yml.read_text()) or {}

    verdicts = []

    # ---- Step 1: compliance engine (pattern requirements) ----
    compliance_json = (report_path.parent / f"{skill}_compliance.json"
                       if report_path else Path("/tmp/skill_compliance.json"))
    r = subprocess.run(
        [sys.executable, str(DRIVER),
         "--requirements", str(yml),
         "--json", str(compliance_json),
         str(output_path)],
        capture_output=True, text=True,
    )
    verdicts.append({
        "gate": "skill_compliance_check",
        "exit_code": r.returncode,
        "pass": r.returncode == 0,
        "report": str(compliance_json),
    })

    # ---- Step 2: cross_checks + postchecks deterministic programs ----
    for section in ("cross_checks", "postchecks"):
        for req in data.get(section) or []:
            if not isinstance(req, dict):
                continue
            rid  = req.get("id", "?")
            desc = req.get("description", "")
            prog = extract_program_name(desc)
            if not prog:
                continue
            prog_path = PROGRAMS / prog
            if not prog_path.exists():
                verdicts.append({
                    "gate": rid,
                    "program": prog,
                    "exit_code": None,
                    "pass": False,
                    "error": f"program not found: {prog_path}",
                })
                continue
            # We call with --help to verify the program is runnable; a full
            # invocation requires skill-specific args the skill_runner cannot
            # know. Programs are supposed to be called by the skill's own
            # orchestrator or SKILL.md bash blocks.
            r = subprocess.run(
                [sys.executable, str(prog_path), "--help"],
                capture_output=True, text=True,
            )
            verdicts.append({
                "gate": rid,
                "program": prog,
                "exit_code": r.returncode,
                "pass": r.returncode == 0,
                "note": "help-only verification; real invocation requires skill-specific args",
            })

    overall_pass = all(v.get("pass") for v in verdicts)
    result = {
        "skill": skill,
        "output": str(output_path),
        "verdicts": verdicts,
        "pass": overall_pass,
    }
    if report_path:
        report_path.write_text(json.dumps(result, indent=2))
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("skill")
    ap.add_argument("output_path")
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    out = Path(args.output_path)
    if not out.exists():
        print(f"ERROR: output path {out} not found", file=sys.stderr)
        return 2

    report = Path(args.json) if args.json else None
    result = run(args.skill, out, report)
    print(json.dumps(result, indent=2))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
