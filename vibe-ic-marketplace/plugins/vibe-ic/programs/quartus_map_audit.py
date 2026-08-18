#!/usr/bin/env python3
"""
quartus_map_audit.py — Scan Quartus .map.rpt for silent-failure indicators.

Learned from <chip-class> FPGA BIST debug (2026-04-21):

  Quartus can compile a design "successfully" (0 errors) while still having
  rejected critical RTL init blocks or lost fanout on key registers. The
  map report flags these cases, but they are buried in hundreds of pages.

This program checks for patterns that almost always indicate broken hardware
even though the build tool returned success:

  1. "Stuck at GND" / "Stuck at VCC" — a register or net is optimized to a
     constant because its data_in cannot change. Usually caused by a failed
     ROM/LUT init, a missing driver, or an unreachable FSM state.

  2. "has no driver or initial value" (Warning 10030) — a signal has been
     declared but synthesis found no logic to drive it.

  3. "initial value for variable <name> should be constant" (Warning 10855) —
     an `initial` block assignment was dropped because Quartus couldn't fold
     it to a constant at elaboration time.

  4. "Lost fanout" — a register's output is never consumed after optimization;
     typically a symptom of upstream logic being optimized away to a constant.

Usage:
    python3 quartus_map_audit.py <path-to-*.map.rpt>
    python3 quartus_map_audit.py --json out.json <path-to-*.map.rpt>

    # Step-6 gate mode (project-relative; re-scans what is on disk):
    python3 quartus_map_audit.py --project . --json out.json

Exit codes:
    0 = clean (no hits)
    1 = at least one audit finding (always blocking)
    2 = usage / io error

PROJECT (GATE) MODE — why it exists
-----------------------------------
Step 6 declares `quartus_map_audit` in its `programs:` list, but nothing ever
executed it: `design_one_shot_runner.step_emit_phase2_manifests` HAND-WROTE
`reports/phase2/fpga/quartus_map_audit.json` as
``{"verdict": "PASS" if fpga_compile.status == "PASS" else "SKIP", ...}`` —
a verdict restated from another step's status, on a report file this scanner
never opened. A Quartus build carrying Stuck-at-GND / Warning(10030) /
lost-fanout therefore recorded `verdict: PASS`.

`--project` mode is the gate side of the fix. It does NOT trust the JSON: it
re-scans every `*.map.rpt` under `phase2/stage1/fpga/output_files/` itself and
FAILs on
  * any finding in the report(s) on disk — even if the JSON claims none;
  * a `.sof` present with no `.map.rpt` to scan (an unscannable build);
  * an audit JSON that is absent, unparseable, or does not claim `audited:true`
    while a build exists.

When NO `.sof` exists this mode exits 0 with an explicit `no-build` disclosure:
it never certifies that a build happened. Step 6's own
`files_exist: ["phase2/stage1/fpga/output_files/*.sof"]` leg and the #607/#663
board-absent capability-gap waiver own that verdict, and are left untouched.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class Finding:
    rule: str
    line: int
    text: str
    severity: str  # "error"


_PATTERNS = [
    ("stuck-at-gnd", re.compile(r"Stuck at GND", re.IGNORECASE)),
    ("stuck-at-vcc", re.compile(r"Stuck at VCC", re.IGNORECASE)),
    ("no-driver",    re.compile(r"Warning \(10030\)")),
    ("init-not-const", re.compile(r"Warning \(10855\)")),
    # Lost fanout lines appear inside tables; match them but exclude the
    # header line so we don't spam findings for every column.
    ("lost-fanout",  re.compile(r"Lost fanout", re.IGNORECASE)),
]


def scan(path: Path) -> List[Finding]:
    if not path.exists():
        print(f"quartus_map_audit: missing report file: {path}", file=sys.stderr)
        raise SystemExit(2)
    findings: List[Finding] = []
    with path.open(errors="replace") as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.rstrip()
            # skip table header/footer junk
            if line.startswith(";") and "Registers optimized away" in line:
                continue
            for rule, pat in _PATTERNS:
                if pat.search(line):
                    findings.append(
                        Finding(
                            rule=rule,
                            line=lineno,
                            text=line.strip()[:300],
                            severity="error",
                        )
                    )
                    break
    return findings


# --------------------------------------------------------------------------
# Project (gate) mode — shared with design_one_shot_runner's step-6 emitter so
# the producer and the gate cannot drift apart again.
# --------------------------------------------------------------------------

OUTPUT_FILES_REL = "phase2/stage1/fpga/output_files"
AUDIT_JSON_REL = "reports/phase2/fpga/quartus_map_audit.json"


def sof_files(project: Path) -> List[Path]:
    return sorted((project / OUTPUT_FILES_REL).glob("*.sof"))


def map_reports(project: Path) -> List[Path]:
    return sorted((project / OUTPUT_FILES_REL).glob("*.map.rpt"))


def scan_project(project: Path) -> Dict[str, Any]:
    """Scan every ``*.map.rpt`` this project's Quartus compile produced.

    Returns the AUDITED half of the step-6 artefact schema:

        audited        bool  — a .map.rpt was actually opened and scanned
        map_reports    [str] — project-relative paths that were scanned
        findings       [dict]— every silent-failure indicator found
        finding_count  int

    ``audited: false`` with an empty findings list means NOTHING WAS SCANNED —
    it is never evidence of a clean build.
    """
    reports = map_reports(project)
    findings: List[Finding] = []
    scanned: List[str] = []
    for rpt in reports:
        try:
            findings.extend(scan(rpt))
        except SystemExit:
            continue
        try:
            scanned.append(str(rpt.relative_to(project)))
        except ValueError:
            scanned.append(str(rpt))
    return {
        "audited": bool(scanned),
        "map_reports": scanned,
        "findings": [asdict(f) for f in findings],
        "finding_count": len(findings),
    }


def _gate(project: Path) -> tuple[int, Dict[str, Any]]:
    """Step-6 gate verdict. See the module docstring for the contract."""
    sofs = sof_files(project)
    scanned = scan_project(project)
    payload: Dict[str, Any] = {
        "mode": "project",
        "project": str(project),
        "sof_present": bool(sofs),
        "sof_files": [str(s.relative_to(project)) if s.is_relative_to(project)
                      else str(s) for s in sofs],
        **scanned,
    }
    if not sofs:
        # No Quartus build in this run. This gate audits a build; it does not
        # certify that one happened — step 6's own files_exist leg and the
        # #607/#663 board-absent cap-gap waiver own that verdict.
        payload["verdict"] = "NO_BUILD"
        payload["reason"] = (
            "no phase2/stage1/fpga/output_files/*.sof — no Quartus build to "
            "audit in this run (the .sof requirement itself is enforced by "
            "step 6's files_exist leg, not here)")
        return 0, payload
    if not scanned["audited"]:
        payload["verdict"] = "FAIL"
        payload["reason"] = (
            f"{len(sofs)} .sof present but no *.map.rpt under "
            f"{OUTPUT_FILES_REL} — the build was never scanned for "
            f"silent-failure indicators, so it cannot be certified clean")
        return 1, payload
    audit_json = project / AUDIT_JSON_REL
    claimed: Optional[Dict[str, Any]] = None
    if audit_json.is_file():
        try:
            loaded = json.loads(audit_json.read_text())
            claimed = loaded if isinstance(loaded, dict) else None
        except (OSError, ValueError):
            claimed = None
    if claimed is None:
        payload["verdict"] = "FAIL"
        payload["reason"] = (
            f"{AUDIT_JSON_REL} absent or unparseable while a Quartus build "
            f"exists — step 6's audit artefact must record a real scan")
        return 1, payload
    if claimed.get("audited") is not True:
        payload["verdict"] = "FAIL"
        payload["reason"] = (
            f"{AUDIT_JSON_REL} does not claim audited=true while a Quartus "
            f"build exists (verdict={claimed.get('verdict')!r}) — a verdict "
            f"restated from another step's status is not an audit")
        return 1, payload
    if scanned["finding_count"]:
        rules = sorted({f["rule"] for f in scanned["findings"]})
        payload["verdict"] = "FAIL"
        payload["reason"] = (
            f"{scanned['finding_count']} silent-failure indicator(s) in "
            f"{', '.join(scanned['map_reports'])}: {', '.join(rules)}")
        return 1, payload
    payload["verdict"] = "PASS"
    payload["reason"] = (
        f"scanned {', '.join(scanned['map_reports'])} — no silent-failure "
        f"indicators")
    return 0, payload


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    p.add_argument("report", nargs="?",
                   help="Path to Quartus *.map.rpt file")
    p.add_argument("--project",
                   help="Project root — gate mode: re-scan every *.map.rpt "
                        f"under {OUTPUT_FILES_REL} and cross-check "
                        f"{AUDIT_JSON_REL}")
    p.add_argument("--json", help="Write findings as JSON")
    args = p.parse_args(argv)

    if args.project:
        if args.report:
            print("quartus_map_audit: pass EITHER a report path OR --project, "
                  "not both", file=sys.stderr)
            return 2
        project = Path(args.project).resolve()
        if not project.is_dir():
            print(f"quartus_map_audit: not a directory: {project}",
                  file=sys.stderr)
            return 2
        rc, payload = _gate(project)
        if args.json:
            out = Path(args.json)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(payload, indent=2, ensure_ascii=False)
                           + "\n")
        line = f"[{payload['verdict']}] quartus_map_audit: {payload['reason']}"
        print(line, file=sys.stderr if rc else sys.stdout)
        return rc

    if not args.report:
        print("quartus_map_audit: a report path or --project is required",
              file=sys.stderr)
        return 2

    findings = scan(Path(args.report))

    if args.json:
        Path(args.json).write_text(
            json.dumps([asdict(f) for f in findings], indent=2)
        )

    if not findings:
        print("quartus_map_audit: OK — no silent-failure indicators found")
        return 0

    # group by rule for readable output
    by_rule: dict[str, list[Finding]] = {}
    for f in findings:
        by_rule.setdefault(f.rule, []).append(f)

    for rule, lst in by_rule.items():
        print(f"\n[{rule}] {len(lst)} hit(s):", file=sys.stderr)
        for f in lst[:10]:
            print(f"  {f.line}: {f.text}", file=sys.stderr)
        if len(lst) > 10:
            print(f"  ... ({len(lst) - 10} more)", file=sys.stderr)

    print(
        f"\nquartus_map_audit: {len(findings)} finding(s) — "
        f"build reports 0 errors but synthesis may have silently dropped logic. "
        f"See LL memory: feedback_fpga_debug_order.md + "
        f"feedback_quartus_init_for_loop.md",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
