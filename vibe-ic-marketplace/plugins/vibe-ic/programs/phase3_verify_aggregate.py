"""v0.1.50 — Phase 3 backend verification aggregator (Pattern-C → program).

Doctrine: `skills/phase3-backend-verify/SKILL.md` asks Claude to spot-
check synth netlist + DEF + GDS + STA + DRC reports. Spot-check is
enumerable (file presence + DRC count + STA margin + LVS verdict). All
deterministic.

Uses existing phase3 backing programs + eda_report_audit.
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


REQUIRED_FILES = (
    ("synth_netlist", "phase3/synth.v"),
    ("final_gds",     "phase3/final.gds"),
    ("final_def",     "phase3/final.def"),
    ("sta_rpt",       "phase3/sta.rpt"),
    ("drc_rpt",       "phase3/drc.rpt"),
    ("lvs_rpt",       "phase3/lvs.rpt"),
)


BACKING_CHECKS = (
    "phase23_completion_audit.py",
    "drc_zero_violations_check.py",
    "lvs_pass_check.py",
    "sta_report_check.py",
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


@dataclass
class Phase3Report:
    project_dir: str
    artifacts: List[ArtifactPresence]
    checks: List[CheckResult]
    drc_violations: int  # parsed from drc.rpt if present
    sta_wns_ns: float
    sta_tns_ns: float
    verdict: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "project_dir": self.project_dir,
            "artifacts": [asdict(a) for a in self.artifacts],
            "checks": [asdict(c) | {"passed": c.passed}
                        for c in self.checks],
            "drc_violations": self.drc_violations,
            "sta_wns_ns": self.sta_wns_ns,
            "sta_tns_ns": self.sta_tns_ns,
            "verdict": self.verdict,
            "emitted_by": _pmd.emitted_by("phase3_verify_aggregate"),
        }


def scan_artifacts(project_dir: Path) -> List[ArtifactPresence]:
    out: List[ArtifactPresence] = []
    for name, rel in REQUIRED_FILES:
        p = project_dir / rel
        out.append(ArtifactPresence(name=name, path=str(p),
                                       present=p.exists()))
    return out


def parse_drc_count(rpt_path: Path) -> int:
    if not rpt_path.exists():
        return -1
    text = rpt_path.read_text(encoding="utf-8", errors="replace")
    import re
    # Accept either order: "<N> violations" or "Total violations: <N>"
    m = re.search(r"total\s+violations?\s*[:=]?\s*(\d+)", text, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s+(?:total\s+)?violations?", text, re.I)
    if m:
        return int(m.group(1))
    # Magic-style summary "Number of DRC errors found: N"
    m = re.search(r"DRC errors? found:\s*(\d+)", text, re.I)
    return int(m.group(1)) if m else -1


def parse_sta_margins(rpt_path: Path) -> tuple:
    if not rpt_path.exists():
        return 0.0, 0.0
    text = rpt_path.read_text(encoding="utf-8", errors="replace")
    import re
    wns = 0.0
    tns = 0.0
    m = re.search(r"wns\s+(-?\d+\.?\d*)", text, re.I)
    if m:
        wns = float(m.group(1))
    m = re.search(r"tns\s+(-?\d+\.?\d*)", text, re.I)
    if m:
        tns = float(m.group(1))
    return wns, tns


def _run_check(name: str, project_dir: Path) -> CheckResult:
    cmd = [sys.executable, str(PROGRAMS_DIR / name), str(project_dir)]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=180, check=False)
        return CheckResult(name=name, exit_code=proc.returncode,
                             stdout_tail=proc.stdout[-500:])
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return CheckResult(name=name, exit_code=127,
                             stdout_tail=f"error: {e}")


def aggregate(project_dir: Path,
              artifacts: List[ArtifactPresence],
              checks: List[CheckResult],
              drc_violations: int,
              wns: float, tns: float) -> Phase3Report:
    missing = [a for a in artifacts if not a.present]
    failed = [c for c in checks if not c.passed]
    timing_fail = wns < 0 or tns < 0
    drc_fail = drc_violations > 0
    # NOT MEASURED IS NOT NOT-FAILING (vibe-ic#727). This line used to read
    #
    #     drc_fail = drc_violations > 0  # treat -1 (unknown) as not-failing here
    #
    # and the comment was the defect, stated in the source. `parse_drc_count`
    # returns -1 when it cannot determine a count, and it carries NO XML dialect
    # at all — so a KLayout report database, which is the format every sign-off
    # certificate in this corpus uses, is unparseable to it BY CONSTRUCTION,
    # yields -1, and yielded "not failing".
    #
    # It was masked rather than safe: this program reads `phase3/drc.rpt` while
    # the corpus writes `phase3/reports/drc.rpt`, so the missing-artefact check
    # fired first. Put a real RDB at the declared path and it graded it clean.
    #
    # An unmeasurable DRC count is now its OWN verdict, distinct from PASS and
    # from FAIL, because "the tool ran and found nothing" and "nobody could read
    # the answer" are different facts and a reader must not have to guess which
    # one a PASS means.
    drc_unmeasured = drc_violations < 0
    if missing or failed or timing_fail or drc_fail:
        verdict = "FAIL"
    elif drc_unmeasured:
        verdict = "UNMEASURED"
    else:
        verdict = "PASS"
    return Phase3Report(
        project_dir=str(project_dir),
        artifacts=artifacts, checks=checks,
        drc_violations=drc_violations,
        sta_wns_ns=wns, sta_tns_ns=tns,
        verdict=verdict,
    )


def verify(project_dir: Path) -> Phase3Report:
    artifacts = scan_artifacts(project_dir)
    drc_n = parse_drc_count(project_dir / "phase3/drc.rpt")
    wns, tns = parse_sta_margins(project_dir / "phase3/sta.rpt")
    checks = [_run_check(name, project_dir) for name in BACKING_CHECKS]
    return aggregate(project_dir, artifacts, checks, drc_n, wns, tns)


def report_to_markdown(rep: Phase3Report) -> str:
    out = ["# Phase 3 backend verification aggregate",
           "",
           f"_Emitted by `phase3_verify_aggregate.py` "
           f"(v{_pmd.running_plugin_version()}). "
           f"Refuse to claim tape-out-ready without DRC=0 AND WNS>=0 "
           f"AND all backing checks PASS._",
           "",
           f"- **Verdict**: {rep.verdict}",
           f"- **DRC violations**: {rep.drc_violations}",
           f"- **WNS / TNS (ns)**: {rep.sta_wns_ns} / {rep.sta_tns_ns}",
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
    if rep.verdict == "UNMEASURED":
        # rc 2 EVEN WITHOUT --strict (vibe-ic#727). Without this, an
        # unmeasurable DRC count exits 0 — the same code as a clean run — and
        # the caller cannot tell "the tool found nothing" from "nobody could
        # read the answer". `--strict` already makes it rc 1; the point here is
        # that the NON-strict path must not report it as clean either.
        print("phase3_verify_aggregate: UNMEASURED — the DRC count could not be "
              "determined, which is not a clean result.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
