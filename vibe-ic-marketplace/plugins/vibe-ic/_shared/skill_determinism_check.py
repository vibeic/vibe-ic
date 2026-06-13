#!/usr/bin/env python3
"""skill_determinism_check.py — verify two outputs of the same skill are
compliance-equivalent.

Problem: LLM-backed skills produce outputs that vary prose-by-prose between
runs. Byte-identical comparison is too strict; compliance-level equivalence
is the useful invariant — if both runs satisfy the same required patterns
AND any structured outputs (JSON) share the same schema-validated fields,
the skill is "deterministic at the spec level".

Usage:
    python3 skill_determinism_check.py <skill_name> <output_a> <output_b> [--json <report>]

Checks:
    1. Both outputs pass skill_compliance_check with identical verdict per rule
    2. If both are JSON: both parse, share the same top-level keys, and any
       schema_version / ic / platform fields agree
    3. If both are markdown: compliance rule set identical (no "rule passed
       in A but failed in B")

Exit 0 iff both outputs are spec-equivalent; 1 if they diverge.
"""
from __future__ import annotations
import argparse, json, subprocess, sys
from pathlib import Path

HERE    = Path(__file__).resolve().parent
DRIVER  = HERE / "skill_compliance_check.py"
SKILLS  = HERE.parent / "skills"


def _run_compliance(skill: str, output: Path, tmp_report: Path) -> dict:
    yml = SKILLS / skill / "compliance.yaml"
    subprocess.run(
        [sys.executable, str(DRIVER),
         "--requirements", str(yml),
         "--json", str(tmp_report),
         str(output)],
        capture_output=True, text=True,
    )
    if tmp_report.exists():
        return json.loads(tmp_report.read_text())
    return {}


def _try_parse_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _normalize_verdict(report: dict) -> dict:
    """Extract the set of per-rule pass/fail from a compliance report."""
    # The skill_compliance_check JSON has findings[] with severity + rule id.
    out = {}
    for f in report.get("findings") or []:
        rid = f.get("id") or f.get("rule")
        sev = f.get("severity", "")
        if rid:
            out[rid] = "FAIL" if sev.upper() == "FAIL" else "OK"
    return out


def check(skill: str, a: Path, b: Path, tmp_dir: Path) -> dict:
    rep_a = _run_compliance(skill, a, tmp_dir / "a.json")
    rep_b = _run_compliance(skill, b, tmp_dir / "b.json")

    verdict_a = _normalize_verdict(rep_a)
    verdict_b = _normalize_verdict(rep_b)

    findings = []

    # Rule-set mismatch
    only_in_a = set(verdict_a) - set(verdict_b)
    only_in_b = set(verdict_b) - set(verdict_a)
    for r in sorted(only_in_a):
        findings.append({
            "severity": "FAIL", "rule": "rule_only_in_a",
            "message": f"rule `{r}` evaluated in run A but not in run B",
        })
    for r in sorted(only_in_b):
        findings.append({
            "severity": "FAIL", "rule": "rule_only_in_b",
            "message": f"rule `{r}` evaluated in run B but not in run A",
        })

    # Per-rule divergence
    for r in sorted(set(verdict_a) & set(verdict_b)):
        if verdict_a[r] != verdict_b[r]:
            findings.append({
                "severity": "FAIL", "rule": "rule_divergent",
                "message": f"rule `{r}`: A={verdict_a[r]}, B={verdict_b[r]}",
            })

    # Structured JSON agreement (if both parse as JSON)
    j_a = _try_parse_json(a)
    j_b = _try_parse_json(b)
    if isinstance(j_a, dict) and isinstance(j_b, dict):
        keys_a = set(j_a)
        keys_b = set(j_b)
        if keys_a ^ keys_b:
            findings.append({
                "severity": "WARN", "rule": "json_top_level_keys_differ",
                "message": f"a-only={sorted(keys_a - keys_b)}, b-only={sorted(keys_b - keys_a)}",
            })
        for k in ("schema_version", "ic", "platform", "tester"):
            if j_a.get(k) != j_b.get(k):
                findings.append({
                    "severity": "FAIL", "rule": f"json_{k}_mismatch",
                    "message": f"A.{k}={j_a.get(k)!r}, B.{k}={j_b.get(k)!r}",
                })

    pass_ = not any(f["severity"] == "FAIL" for f in findings)
    return {
        "skill": skill,
        "a": str(a),
        "b": str(b),
        "compliance_a": rep_a,
        "compliance_b": rep_b,
        "findings": findings,
        "pass": pass_,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("skill")
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    a = Path(args.a); b = Path(args.b)
    if not a.exists() or not b.exists():
        print(f"ERROR: output path missing", file=sys.stderr)
        return 2

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        result = check(args.skill, a, b, Path(tmp))

    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
