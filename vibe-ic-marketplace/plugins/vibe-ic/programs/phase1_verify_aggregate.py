"""v0.1.50 — Phase 1 output verification aggregator (Pattern-C → program).

Doctrine: `skills/phase1-output-verify/SKILL.md` asks Claude to spot-check
13 L*.json layer documents emitted by `phase1_one_shot_runner`. The
spot-check is enumerable (file presence + schema conformance + cross-
layer consistency). All deterministic.

This aggregator runs the existing phase1_*_check programs and emits a
unified verdict per L doc, so the skill becomes a thin wrapper that
narrates residuals the program flagged.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List


# The 13 L docs phase1 emits, in order.
L_DOCS = (
    "L1_PRODUCT_VISION", "L2_FRS", "L3_USE_CASES", "L4_USER_FLOW",
    "L5_BLOCK_PLAN", "L6_INTERFACE_LIST", "L7_REGISTER_MAP",
    "L8_TIMING_WAVEFORM", "L9_CONSTRAINTS", "L10_TEST_PLAN",
    "L11_VERIFICATION_PLAN", "L12_BEHAVIORAL_SEQUENCES",
    "L13_DELIVERABLES",
)

# Backing programs (all existing as of v0.1.50)
BACKING_CHECKS = (
    "phase1_all_l_docs_present_check.py",
    "phase1_doc_presence_check.py",
    "phase1_doc_input_completeness_check.py",
    "phase1_doc_content_implementation_completeness_check.py",
    "phase1_consistency_check.py",
    "phase1_input_vs_generated_completeness_check.py",
    "phase1_gate_contract_check.py",
)

PROGRAMS_DIR = Path(__file__).resolve().parent


@dataclass
class CheckResult:
    name: str
    exit_code: int
    stdout_tail: str
    stderr_tail: str

    @property
    def passed(self) -> bool:
        return self.exit_code == 0

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self) | {"passed": self.passed}


@dataclass
class Phase1Report:
    project_dir: str
    l_doc_presence: Dict[str, bool]
    check_results: List[CheckResult]
    pass_count: int
    fail_count: int
    verdict: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "project_dir": self.project_dir,
            "l_doc_presence": self.l_doc_presence,
            "check_results": [c.as_dict() for c in self.check_results],
            "pass_count": self.pass_count,
            "fail_count": self.fail_count,
            "verdict": self.verdict,
            "emitted_by": "phase1_verify_aggregate v0.1.50",
        }


def scan_l_doc_presence(project_dir: Path) -> Dict[str, bool]:
    """Look for L*.json in <project>/generated_docs/ (canonical location)."""
    out: Dict[str, bool] = {}
    docs_dir = project_dir / "generated_docs"
    for doc in L_DOCS:
        # Match e.g. L1_PRODUCT_VISION.json (preferred) or L1.json
        candidates = (
            docs_dir / f"{doc}.json",
            docs_dir / f"{doc.split('_')[0]}.json",
        )
        out[doc] = any(p.exists() for p in candidates)
    return out


def _run_check(name: str, project_dir: Path) -> CheckResult:
    cmd = [sys.executable, str(PROGRAMS_DIR / name), str(project_dir)]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120, check=False)
        return CheckResult(
            name=name, exit_code=proc.returncode,
            stdout_tail=proc.stdout[-500:],
            stderr_tail=proc.stderr[-500:],
        )
    except subprocess.TimeoutExpired:
        return CheckResult(name=name, exit_code=124,
                            stdout_tail="", stderr_tail="timeout")
    except FileNotFoundError:
        return CheckResult(name=name, exit_code=127,
                            stdout_tail="", stderr_tail="program not found")


def aggregate(project_dir: Path,
              checks: List[CheckResult],
              presence: Dict[str, bool]) -> Phase1Report:
    pass_count = sum(1 for c in checks if c.passed)
    fail_count = len(checks) - pass_count
    missing = [d for d, p in presence.items() if not p]
    if missing or fail_count:
        verdict = "FAIL"
    else:
        verdict = "PASS"
    return Phase1Report(
        project_dir=str(project_dir),
        l_doc_presence=presence,
        check_results=checks,
        pass_count=pass_count,
        fail_count=fail_count,
        verdict=verdict,
    )


def verify(project_dir: Path) -> Phase1Report:
    presence = scan_l_doc_presence(project_dir)
    checks = [_run_check(name, project_dir) for name in BACKING_CHECKS]
    return aggregate(project_dir, checks, presence)


def report_to_markdown(rep: Phase1Report) -> str:
    out = ["# Phase 1 verification aggregate",
           "",
           f"_Emitted by `phase1_verify_aggregate.py` (v0.1.50). "
           f"Refuse to overclaim — every L doc must be present AND every "
           f"backing check must PASS._",
           "",
           f"- **Verdict**: {rep.verdict}",
           f"- **Backing checks**: {rep.pass_count}/{len(rep.check_results)} PASS",
           ""]
    out.append("## L doc presence")
    out.append("")
    out.append("| L doc | Present |")
    out.append("|---|---|")
    for doc, present in rep.l_doc_presence.items():
        out.append(f"| {doc} | {'✓' if present else '✗'} |")
    out.append("")
    out.append("## Backing check results")
    out.append("")
    out.append("| Check | Exit | Verdict |")
    out.append("|---|---|---|")
    for c in rep.check_results:
        out.append(f"| `{c.name}` | {c.exit_code} | "
                   f"{'PASS' if c.passed else 'FAIL'} |")
    out.append("")
    return "\n".join(out)


def _cli() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("project_dir", type=Path)
    p.add_argument("--out-md", type=Path)
    p.add_argument("--out-json", type=Path)
    p.add_argument("--strict", action="store_true")
    args = p.parse_args()
    if not args.project_dir.exists():
        print(f"project not found: {args.project_dir}", file=sys.stderr)
        return 2
    rep = verify(args.project_dir)
    md = report_to_markdown(rep)
    if args.out_md:
        args.out_md.write_text(md, encoding="utf-8")
    else:
        print(md)
    if args.out_json:
        args.out_json.write_text(
            json.dumps(rep.as_dict(), indent=2), encoding="utf-8")
    if args.strict and rep.verdict != "PASS":
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
