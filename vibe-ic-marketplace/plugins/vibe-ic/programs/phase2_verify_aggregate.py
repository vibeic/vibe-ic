"""v0.1.50 — Phase 2 output verification aggregator (Pattern-C → program).

Doctrine: `skills/phase2-rtl-verify/SKILL.md` asks Claude to spot-check
RTL + SOF + reference TB PASS after phase2 runner. Spot-check is
enumerable (RTL hygiene gates, spec-conformance, lint, SOF artifact
presence). All deterministic.

Uses the existing rtl_precheck_gate + spec_conformance_check programs;
returns a unified verdict so the skill becomes a thin wrapper.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List
import plugin_manifest_discovery as _pmd  # noqa: E402  (#800 ONE version reader)


REQUIRED_ARTIFACTS = (
    "phase2/stage1/rtl",        # RTL directory
    "phase2/stage1/sof",        # synth-output netlist + SDC
    "phase2/stage1/tb",         # reference testbench
)


BACKING_CHECKS = (
    ("rtl_precheck_gate", "rtl_precheck_gate.py", ["--rtl-dir"]),
    ("spec_conformance", "spec_conformance_check.py", []),
    ("rtl_hygiene_lint", "rtl_hygiene_lint.py", []),
)

PROGRAMS_DIR = Path(__file__).resolve().parent


@dataclass
class ArtifactPresence:
    name: str
    path: str
    present: bool


@dataclass
class CheckResult:
    name: str
    exit_code: int
    stdout_tail: str

    @property
    def passed(self) -> bool:
        return self.exit_code == 0

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self) | {"passed": self.passed}


@dataclass
class Phase2Report:
    project_dir: str
    artifacts: List[ArtifactPresence]
    checks: List[CheckResult]
    verdict: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "project_dir": self.project_dir,
            "artifacts": [asdict(a) for a in self.artifacts],
            "checks": [c.as_dict() for c in self.checks],
            "verdict": self.verdict,
            "emitted_by": _pmd.emitted_by("phase2_verify_aggregate"),
        }


def scan_artifacts(project_dir: Path) -> List[ArtifactPresence]:
    out: List[ArtifactPresence] = []
    for rel in REQUIRED_ARTIFACTS:
        p = project_dir / rel
        out.append(ArtifactPresence(
            name=rel.split("/")[-1],
            path=str(p),
            present=p.exists(),
        ))
    return out


def _run_check(label: str, name: str, extra_args: List[str],
               project_dir: Path) -> CheckResult:
    rtl_dir = project_dir / "phase2" / "stage1" / "rtl"
    cmd = [sys.executable, str(PROGRAMS_DIR / name)]
    if "--rtl-dir" in extra_args:
        cmd += ["--rtl-dir", str(rtl_dir)]
    else:
        # programs that take positional <project_dir>
        cmd += [str(project_dir)]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=180, check=False)
        return CheckResult(
            name=label, exit_code=proc.returncode,
            stdout_tail=proc.stdout[-500:])
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return CheckResult(name=label, exit_code=127,
                            stdout_tail=f"error: {e}")


def aggregate(project_dir: Path,
              artifacts: List[ArtifactPresence],
              checks: List[CheckResult]) -> Phase2Report:
    missing_artifacts = [a for a in artifacts if not a.present]
    failed_checks = [c for c in checks if not c.passed]
    verdict = "FAIL" if (missing_artifacts or failed_checks) else "PASS"
    return Phase2Report(
        project_dir=str(project_dir),
        artifacts=artifacts, checks=checks, verdict=verdict)


def verify(project_dir: Path) -> Phase2Report:
    artifacts = scan_artifacts(project_dir)
    checks = [
        _run_check(label, name, args, project_dir)
        for label, name, args in BACKING_CHECKS
    ]
    return aggregate(project_dir, artifacts, checks)


def report_to_markdown(rep: Phase2Report) -> str:
    out = ["# Phase 2 verification aggregate",
           "",
           f"_Emitted by `phase2_verify_aggregate.py` "
           f"(v{_pmd.running_plugin_version()}). "
           f"Refuse to claim PASS without all artifacts AND all checks._",
           "",
           f"- **Verdict**: {rep.verdict}",
           "",
           "## Required artifacts",
           ""]
    for a in rep.artifacts:
        out.append(f"- `{a.path}`: {'✓' if a.present else '✗ MISSING'}")
    out.append("")
    out.append("## Backing checks")
    out.append("")
    out.append("| Check | Exit | Verdict |")
    out.append("|---|---|---|")
    for c in rep.checks:
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
