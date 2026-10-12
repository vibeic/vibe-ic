"""v0.1.50 — Phase 2 output verification aggregator (Pattern-C → program).

Deterministic evidence for the Phase2 expert review: RTL, mapped netlist and
reference TB for IC/IP; RTL, reference TB and bitstream for an explicit FPGA
review. Artifact presence and static check results do not claim simulation,
hardware execution or whole-flow acceptance.

Uses the existing rtl_precheck_gate + spec_conformance_check programs;
returns a unified verdict so the skill becomes a thin wrapper.
"""
from __future__ import annotations

# --- sibling-import path (vibe-ic#2104) ------------------------------------
# `programs/` is a flat directory whose modules import each other by BARE
# name. Python puts a file's own directory on `sys.path` only when that file
# is run as `__main__`; under `importlib.util.spec_from_file_location` — how
# the gates, the wiring audit and much of the suite load a program — it does
# not, so every bare sibling import below raises ModuleNotFoundError. Measured
# on the base tree: 454 of the 1385 top-level programs died that way. Restore
# the condition the file is written for. Idempotent, and the same shape the
# sibling programs that already carry it use.
import os as _os                                                    # noqa: E402
import sys as _sys                                                  # noqa: E402

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
# ---------------------------------------------------------------------------


import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List
import plugin_manifest_discovery as _pmd  # noqa: E402  (#800 ONE version reader)
import _path_layout as _pl
import _submission_template as _st
import _tapeout_declaration as _td
from spec_conformance_check import collect_rtl_files


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
    argv: List[str] = field(default_factory=list)
    stderr_tail: str = ""
    reason_class: str = ""

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
    verification_target: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "project_dir": self.project_dir,
            "artifacts": [asdict(a) for a in self.artifacts],
            "checks": [c.as_dict() for c in self.checks],
            "verdict": self.verdict,
            "verification_target": self.verification_target,
            "emitted_by": _pmd.emitted_by("phase2_verify_aggregate"),
        }


def _verification_target(project_dir: Path, target: str | None = None) -> str:
    if target is not None:
        return target
    # The raw owner answer takes precedence over a generated declaration.
    for rel in (_st.DESIGN_ANSWERS_REL, _td.DECLARATION_REL):
        if not (project_dir / rel).is_file():
            continue
        try:
            _, delivery = _td.read_owner_delivery(project_dir, rel)
        except ValueError:
            return "UNSPECIFIED"
        return "ic" if delivery == _td.DELIVERABLE_DIE else "ip"
    return "UNSPECIFIED"


def _nonempty(paths) -> bool:
    return any(path.is_file() and path.stat().st_size > 0 for path in paths)


def scan_artifacts(project_dir: Path, target: str | None = None) -> List[ArtifactPresence]:
    target = _verification_target(project_dir, target)
    rtl = _pl.rtl_dir(project_dir)
    tb_dirs = _pl.resolve_tb_dirs(project_dir)
    tb = next((directory for directory in tb_dirs if _nonempty(
        p for pattern in ("*.v", "*.sv") for p in directory.glob(pattern))),
        _pl.sim_full_stack_dir(project_dir))
    out = [ArtifactPresence("rtl", str(rtl), _nonempty(collect_rtl_files([], str(rtl)))),
           ArtifactPresence("tb", str(tb), _nonempty(p for pattern in
                            ("*.v", "*.sv") for p in tb.glob(pattern)))]
    if target in ("ic", "ip"):
        netlist = _pl.synth_dir(project_dir)
        out.append(ArtifactPresence("netlist", str(netlist), _nonempty(
            p for pattern in ("*.v", "*.sv") for p in netlist.glob(pattern))))
    elif target == "fpga":
        fpga = _pl.fpga_early_dir(project_dir) / "output_files"
        out.append(ArtifactPresence("sof", str(fpga), _nonempty(fpga.glob("*.sof"))))
    else:
        out.append(ArtifactPresence("verification_target", "owner delivery or --target", False))
    return out


def _run_check(label: str, name: str, extra_args: List[str],
               project_dir: Path) -> CheckResult:
    rtl_dir = project_dir / "phase2" / "stage1" / "rtl"
    cmd = [sys.executable, str(PROGRAMS_DIR / name)]
    if name == "rtl_precheck_gate.py":
        cmd += ["--rtl-dir", str(rtl_dir)]
    elif name == "spec_conformance_check.py":
        spec = _pl.generated_docs_dir(project_dir) / "L9_INTEGRATION_SPEC.json"
        cmd += ["--rtl-dir", str(rtl_dir), "--spec", str(spec)]
    elif name == "rtl_hygiene_lint.py":
        cmd += [str(path) for path in collect_rtl_files([], str(rtl_dir))]
    else:
        raise ValueError(f"no child CLI adapter for {name}")
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=180, check=False)
        return CheckResult(
            name=label, exit_code=proc.returncode,
            stdout_tail=proc.stdout[-500:], argv=cmd, stderr_tail=proc.stderr[-1000:],
            reason_class=("" if proc.returncode == 0 else
                          "CHECK_FAILED" if proc.returncode == 1 else "INVOCATION_ERROR"))
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return CheckResult(name=label, exit_code=127,
                            stdout_tail=f"error: {e}", argv=cmd, stderr_tail=str(e),
                            reason_class="EXECUTION_ERROR")


def aggregate(project_dir: Path,
              artifacts: List[ArtifactPresence],
              checks: List[CheckResult]) -> Phase2Report:
    missing_artifacts = [a for a in artifacts if not a.present]
    failed_checks = [c for c in checks if not c.passed]
    verdict = "FAIL" if (missing_artifacts or failed_checks) else "PASS"
    return Phase2Report(
        project_dir=str(project_dir),
        artifacts=artifacts, checks=checks, verdict=verdict)


def verify(project_dir: Path, target: str | None = None) -> Phase2Report:
    target = _verification_target(project_dir, target)
    artifacts = scan_artifacts(project_dir, target)
    checks = [
        _run_check(label, name, args, project_dir)
        for label, name, args in BACKING_CHECKS
    ]
    report = aggregate(project_dir, artifacts, checks)
    report.verification_target = target
    return report


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
    p.add_argument("--target", choices=("ic", "ip", "fpga"),
                   help="Phase2 artifact review target; default: owner delivery answer")
    args = p.parse_args()
    rep = verify(args.project_dir, args.target)
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
