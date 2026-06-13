#!/usr/bin/env python3
"""
cdc_crossing_check.py -- Deterministic CDC report checker.

For skill: cdc-check

Verifies that CDC (Clock Domain Crossing) reports exist and contain
meaningful crossing analysis content.

Checks:
  1. At least 1 CDC report exists
  2. Contains clock domain references (clk, clock, domain)
  3. Contains crossing analysis keywords (crossing(s), synchronizer,
     metastab, FIFO, async, CDC) -- OR -- is a legitimate single-clock
     design (canonical PASS report with <=1 clock / empty crossings list +
     single-clock evidence). A single-clock design has no crossings to
     analyse, so an empty crossings list is itself the correct substance.

Usage:
    python3 cdc_crossing_check.py <project_dir>
    python3 cdc_crossing_check.py <project_dir> --json out.json

Exit codes:
    0 = PASS (CDC report with crossing analysis found)
    1 = FAIL (no report or missing analysis)

No external tool dependencies -- pure Python.
"""
from __future__ import annotations

import argparse
import json
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
    severity: str
    message: str
    file: str = ""


@dataclass
class AuditResult:
    program: str
    passed: bool
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------
CDC_FILE_PATTERNS = [
    "*cdc*.rpt", "*cdc*.log", "*CDC*.rpt", "*CDC*.log",
    "*clock_domain*", "*clock_crossing*",
]

# v1.6.36 — canonical-JSON path emitted by phase2_one_shot_runner.
# When a project has run the runner, this JSON carries `verdict: PASS`
# and a `crossings` list — the substance the gate should accept WITHOUT
# requiring an external CDC tool's report. We treat the canonical JSON
# as a first-class CDC report (same as a *.rpt from a tool).
CANONICAL_JSON_PATHS = [
    "reports/phase2/cdc/crossing.json",
    "reports/phase2/cdc/async_input.json",
    "reports/phase2/cdc/reset_dep.json",
]

CLOCK_REF_RE = re.compile(r"\bclk\b|\bclock\b|\bdomain\b", re.I)
# ORGANIC-20260606 #458 — broaden to the plural / JSON-key form
# (`crossings`). A zero-crossing single-clock report legitimately phrases
# its substance as "no clock-domain crossings exist" (plural) and the
# canonical JSON carries a `"crossings"` key — the singular literal
# `\bcrossing\b` never matched either, which (combined with the
# crossings-list-must-be-non-empty canonical path) FAILed every legit
# single-clock design.
CROSSING_RE = re.compile(
    r"\bcrossings?\b|\bsynchronizer\b|\bmetastab|\bFIFO\b|\basync\b|\bCDC\b",
    re.I,
)

# ORGANIC-20260606 #458 — wording emitted by phase2_one_shot_runner for a
# single-clock design ("single clock domain [...] — no clock-domain
# crossings exist"). Used by the third accept-path to recognise a
# legitimate zero-crossing PASS whose `crossings` list is (correctly) empty.
SINGLE_CLOCK_EVIDENCE_RE = re.compile(
    r"single\s+clock\s+domain|no\s+(?:clock[- ]domain\s+)?crossings",
    re.I,
)


def audit_cdc(project_dir: Path) -> AuditResult:
    result = AuditResult(program="cdc_crossing_check", passed=False)

    if not project_dir.is_dir():
        result.findings.append(Finding(
            rule="PROJECT_DIR_EXISTS", severity="ERROR",
            message=f"Project directory does not exist: {project_dir}"))
        result.summary = {"files_found": 0, "has_clock_ref": False,
                          "has_crossing": False}
        return result

    # Discover CDC files
    found: List[Path] = []
    for pat in CDC_FILE_PATTERNS:
        found.extend(project_dir.rglob(pat))

    # v1.6.36 — also accept canonical JSON emissions from
    # phase2_one_shot_runner. If a JSON at one of the canonical paths
    # carries `verdict: PASS` and has crossings/synchroniser content,
    # that is the runner's machine-readable equivalent of a *.cdc.rpt
    # from a third-party CDC tool. Same substance check applies (clock
    # domain references + crossing keywords) — we just need to count
    # them as findable input.
    canonical_pass = 0
    for rel in CANONICAL_JSON_PATHS:
        cand = project_dir / rel
        if cand.is_file():
            try:
                doc = json.loads(cand.read_text())
            except Exception:
                continue
            if doc.get("verdict") == "PASS":
                found.append(cand)
                canonical_pass += 1

    # Deduplicate
    seen = set()
    unique: List[Path] = []
    for p in found:
        if p not in seen:
            seen.add(p)
            unique.append(p)

    if not unique:
        result.findings.append(Finding(
            rule="CDC_REPORT_EXISTS", severity="ERROR",
            message="No CDC report found (searched *cdc*.rpt/log, *clock_domain*, *clock_crossing*)"))
        result.summary = {"files_found": 0, "has_clock_ref": False,
                          "has_crossing": False}
        return result

    result.findings.append(Finding(
        rule="CDC_REPORT_EXISTS", severity="INFO",
        message=f"Found {len(unique)} CDC report file(s)",
        file=str(unique[0])))

    # Analyze content
    has_clock_ref = False
    has_crossing = False
    best_file = str(unique[0])

    # ORGANIC-20260606 #458 — the canonical JSON files are evaluated by the
    # dedicated structured paths below (canonical_substance_pass /
    # single_clock_pass), NOT by the freeform keyword regex. Running the
    # broadened `\bcrossings?\b` over canonical JSON text would let the bare
    # structural key `"crossings": []` (the ABSENCE of crossings) masquerade
    # as analysis content — which would defeat the corpus-sweep guard for a
    # multi-clock report. The keyword scan is therefore restricted to
    # human-readable tool-report files, where the prose word "crossing(s)"
    # genuinely signals analysis content.
    canonical_resolved = {
        (project_dir / rel).resolve() for rel in CANONICAL_JSON_PATHS
    }

    for fp in unique:
        if fp.resolve() in canonical_resolved:
            continue
        try:
            text = fp.read_text(errors="replace")
        except OSError:
            result.findings.append(Finding(
                rule="CDC_FILE_READABLE", severity="WARNING",
                message=f"Cannot read file: {fp.name}",
                file=str(fp)))
            continue

        if CLOCK_REF_RE.search(text):
            has_clock_ref = True
        if CROSSING_RE.search(text):
            has_crossing = True

    # v1.6.36 — if any canonical JSON declares verdict=PASS with a
    # populated crossings/async-input/reset-strategy field, accept that
    # as the substance check. The runner-emitted JSON IS the
    # machine-readable equivalent of a 3rd-party CDC report.
    canonical_substance_pass = False
    for rel in CANONICAL_JSON_PATHS:
        cand = project_dir / rel
        if not cand.is_file():
            continue
        try:
            doc = json.loads(cand.read_text())
        except Exception:
            continue
        if doc.get("verdict") != "PASS":
            continue
        # crossing.json: must list at least one crossing
        # async_input.json: must list at least one async_input
        # reset_dep.json: must declare reset_strategy
        if (
            (isinstance(doc.get("crossings"), list)
             and len(doc["crossings"]) > 0)
            or (isinstance(doc.get("async_inputs"), list)
                and len(doc["async_inputs"]) > 0)
            or doc.get("reset_strategy")
        ):
            canonical_substance_pass = True
            break

    # ORGANIC-20260606 #458 — THIRD accept-path: a single-clock design has
    # ZERO clock-domain crossings, so a legitimate canonical PASS report
    # carries an EMPTY `crossings` list. The pre-#458 paths both failed it:
    # the keyword path found no singular `crossing` token, and the
    # canonical-substance path required len(crossings) > 0. Accept a
    # canonical crossing.json with verdict=PASS when it is provably a
    # single-clock report — either it explicitly enumerates at most one
    # clock (`clocks_found` <= 1), or it carries an empty `crossings` list
    # together with single-clock evidence wording. The corpus-sweep guard
    # is preserved: a MULTI-clock report (clocks_found > 1) that lists real
    # crossings can NOT enter this path (it is gated on the single-clock
    # condition), so a multi-clock report lacking analysis content still
    # FAILs.
    single_clock_pass = False
    for rel in CANONICAL_JSON_PATHS:
        cand = project_dir / rel
        if not cand.is_file():
            continue
        try:
            doc = json.loads(cand.read_text())
        except Exception:
            continue
        if doc.get("verdict") != "PASS":
            continue
        clocks_found = doc.get("clocks_found")
        crossings = doc.get("crossings")
        evidence = str(doc.get("evidence") or "")
        # (a) explicit single-clock enumeration: <= 1 clock means no
        #     crossing is even possible.
        explicit_single = (
            isinstance(clocks_found, list) and len(clocks_found) <= 1
        )
        # (b) empty crossings list backed by single-clock evidence wording.
        empty_with_evidence = (
            isinstance(crossings, list) and len(crossings) == 0
            and bool(SINGLE_CLOCK_EVIDENCE_RE.search(evidence))
        )
        if explicit_single or empty_with_evidence:
            single_clock_pass = True
            break

    # A single-clock canonical PASS legitimately has NO crossing-analysis
    # keywords (there is nothing to analyse) — so the CDC_CROSSING_ANALYSIS
    # ERROR must NOT be raised in that case, otherwise the findings would
    # contradict the (correct) PASS verdict.
    crossing_substance_ok = (
        has_crossing or canonical_substance_pass or single_clock_pass
    )
    # The canonical JSONs are excluded from the freeform keyword scan
    # (above), so a canonical-only project would not set has_clock_ref. A
    # canonical PASS report inherently references clocks (clocks_found /
    # evidence), so a recognised canonical substance/single-clock PASS also
    # satisfies the clock-reference check — keep the finding consistent with
    # the verdict.
    clock_ref_ok = (
        has_clock_ref or canonical_substance_pass or single_clock_pass
    )

    if not clock_ref_ok:
        result.findings.append(Finding(
            rule="CDC_CLOCK_REFERENCES", severity="ERROR",
            message="No clock domain references (clk/clock/domain) found in CDC report",
            file=best_file))

    if not crossing_substance_ok:
        result.findings.append(Finding(
            rule="CDC_CROSSING_ANALYSIS", severity="ERROR",
            message="No crossing analysis keywords (crossing(s)/synchronizer/metastab/FIFO/async/CDC) found",
            file=best_file))

    result.passed = (
        (has_clock_ref and has_crossing)
        or canonical_substance_pass
        or single_clock_pass
    )
    result.summary = {
        "files_found": len(unique),
        "has_clock_ref": has_clock_ref,
        "has_crossing": has_crossing,
        "canonical_json_pass": canonical_pass,
        "canonical_substance_pass": canonical_substance_pass,
        "single_clock_pass": single_clock_pass,
    }
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: list = None) -> int:
    parser = argparse.ArgumentParser(
        description="CDC report crossing analysis checker")
    parser.add_argument("project_dir", help="Project directory to scan")
    parser.add_argument("--json", default=None, help="Output JSON report path")
    args = parser.parse_args(argv)

    result = audit_cdc(Path(args.project_dir))

    report = asdict(result)
    report_json = json.dumps(report, indent=2, ensure_ascii=False)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(report_json)

    print(report_json)
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
