#!/usr/bin/env python3
"""
utilization_band_check.py — Floorplan/placement utilization band classifier.

Extracts the `phase3-backend-verify` checklist-item-2 utilization rule out
of skill prose. The skill said: "confirm utilization between 50%-75%; <40%
wastes silicon, >85% causes routing congestion."

Why this is an ADVISORY (WARN) band, never a hard FAIL on the band
------------------------------------------------------------------
The 50/75 (and 40/85) numbers are an industry rule-of-thumb for a *free
die* (utilization the designer chooses). They are NOT a fab/spec hard
limit, and — measured against the real corpus — most legitimate
chipignite/Caravel-class designs sit at 13%-33% because the user-project
area is fixed by the harness, not by the design's own gate count. Making
"<40%" a hard FAIL would false-fire on the majority of legitimate
finished GDS in the corpus (aes 30%, chacha 33%, prince 24%, mdio 13%,
lpc 14%, …). The HARD project rule is: a guard must run CLEAN on the real
corpus — so the band is reported as advisory WARN, not FAIL.

The ONLY hard FAILs are universal, non-fabricated structural facts:
  * a derivable utilization < 0%  (impossible / corrupt report), or
  * a derivable utilization > 100% (cell-area overlap / illegal).
A literal 0% is NOT a hard FAIL (v0.2.69): OpenROAD's report_design_area
prints integer-rounded percentages, so any true value below 0.5% reads
"0%" — that is a precision floor, not corruption. It classifies as WARN
UTIL_ZERO_UNRESOLVED (no usable band datum).
These mirror the universal (0,100]% sanity that
`placement_legality_check.py` owns for DEF-derived density; this program
applies the same universal rule to the *utilization-report* artefacts the
phase3 runner emits (reports/density.rpt-style or OpenROAD JSON), which
placement_legality_check does not parse.

No fabrication
--------------
When NO utilization artefact is present, the check does NOT invent one:
it reports verdict NO_DATA (informational, rc=0 unless --strict) and never
emits a vacuous PASS that claims a band was checked. Garbage / non-numeric
values are reported honestly, never silently coerced to a pass.

Sources parsed (first present wins, never required)
---------------------------------------------------
  reports/density.rpt / reports/phase3/density.rpt — a
    "... utilization ...: <n>%" comment line (the runner's format), or
  a density/utilization JSON with a recognized key, or
  an `area.rpt` / placement report carrying a "utilization" numeric.

Usage
-----
    python3 utilization_band_check.py <project_dir> [--json out.json] [--strict]
    python3 utilization_band_check.py --util 62 [--json out.json]   # direct value

Exit codes
----------
    0 = utilization within [0,100]% (PASS; WARN if outside the 50-75 band
        or a quantized 0 reading), OR NO_DATA without --strict
    1 = derivable utilization < 0 or > 100 (FAIL), OR NO_DATA with --strict
    2 = bad arguments / project dir not found

Generality: chip-AGNOSTIC. The band numbers are advisory design
rule-of-thumb, applied identically to any design; the only FAIL is the
universal (0,100]% sanity.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# Advisory rule-of-thumb band (free-die design guidance, NOT a spec/fab limit).
_WARN_LOW = 50.0    # below this: under-filled (advisory only)
_WARN_HIGH = 75.0   # above this: congestion-prone (advisory only)

# Artefacts the phase3 runner may emit. Parsed only if present; never required.
_REPORT_CANDIDATES = (
    "reports/density.rpt",
    "reports/phase3/density.rpt",
    "phase3/pnr/area.rpt",
    "phase3/stage3/pnr/area.rpt",
    "reports/utilization.rpt",
)
_JSON_CANDIDATES = (
    "reports/phase3/density.json",
    "reports/density.json",
    "phase3/stage3/pnr/place_density.json",
    "phase3/stage3/pnr/placement.json",
)
_JSON_KEYS = (
    "core_utilization", "utilization_pct", "utilization",
    "placement_density_pct", "placement_density", "place_density",
    "density_pct", "density",
)

# A utilization/density comment line in the runner's report text.
_UTIL_TEXT = re.compile(
    r"(?:core[\s_]+)?(?:row\s+)?(?:utili[sz]ation|density)\b[^0-9%\n]*"
    r"([0-9]*\.?[0-9]+)\s*%",
    re.IGNORECASE)

# Key-value form emitted by the runner's own odb fill report (#445 rows-
# already-full path): `row_utilization_pct 99.75` — the percent unit is
# declared by the `_pct` key suffix, no `%` sign follows the number. The
# checker must parse its own emitter's format (emitter↔checker drift guard).
_UTIL_TEXT_PCT_KEY = re.compile(
    r"\b\w*(?:utili[sz]ation|density)\w*_pct\b\s*[:=]?\s*"
    r"([0-9]*\.?[0-9]+)",
    re.IGNORECASE)

# An HONEST unresolved disclosure (e.g. "core-area utilization
# (report_design_area, post-fill): unresolved" with the quantized-floor
# explanation) is DATA-QUALITY information, not absence of an artefact —
# it must classify as a NAMED verdict, never fold into NO_DATA.
_UTIL_UNRESOLVED = re.compile(
    r"utili[sz]ation\b[^:\n]*:\s*unresolved\b", re.IGNORECASE)


@dataclass
class Finding:
    severity: str   # ERROR, WARNING, INFO
    category: str
    message: str


def _coerce_pct(val) -> Optional[float]:
    """Coerce a value to a percentage. (0,1] is treated as a fraction."""
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    if f <= 0:
        return f  # caller classifies: negative → FAIL, 0 → WARN unresolved
    if f <= 1.0:
        return f * 100.0
    return f


def _read_from_text(project: Path) -> Tuple[Optional[float], Optional[str]]:
    for rel in _REPORT_CANDIDATES:
        p = project / rel
        if not p.is_file():
            continue
        try:
            text = p.read_text(errors="replace")
        except OSError:
            continue
        m = _UTIL_TEXT.search(text) or _UTIL_TEXT_PCT_KEY.search(text)
        if m:
            pct = _coerce_pct(m.group(1))
            if pct is not None:
                return pct, rel
        # No numeric value — but an explicit unresolved disclosure is
        # still a real artefact reading: return (None, rel) so classify
        # yields the named UNRESOLVED_DISCLOSED verdict, not NO_DATA.
        if _UTIL_UNRESOLVED.search(text):
            return None, rel
    return None, None


def _read_from_json(project: Path) -> Tuple[Optional[float], Optional[str]]:
    for rel in _JSON_CANDIDATES:
        p = project / rel
        if not p.is_file():
            continue
        try:
            doc = json.loads(p.read_text(errors="replace"))
        except Exception:
            continue
        if not isinstance(doc, dict):
            continue
        for k in _JSON_KEYS:
            if k in doc and doc[k] is not None:
                pct = _coerce_pct(doc[k])
                if pct is not None:
                    return pct, f"{rel}:{k}"
    return None, None


def read_utilization(project: Path) -> Tuple[Optional[float], Optional[str]]:
    """Return (utilization_pct, source_rel) from any present artefact, else
    (None, None). Never fabricates."""
    pct, src = _read_from_json(project)
    if pct is not None:
        return pct, src
    return _read_from_text(project)


def classify(util_pct: Optional[float], source: Optional[str]) -> Tuple[str, List[Finding]]:
    """Return (verdict, findings) for a utilization value.

    verdict in {PASS, WARN, FAIL, NO_DATA}. The 50-75 band is advisory:
    out-of-band yields WARN (verdict WARN, still rc=0). Only <=0 / >100 FAIL.
    """
    findings: List[Finding] = []
    if util_pct is None:
        if source is not None:
            # the artefact exists and EXPLICITLY discloses an unresolved
            # reading (e.g. report_design_area integer-rounded to 0%,
            # true value below report precision) — named verdict, never
            # folded into NO_DATA.
            findings.append(Finding(
                "INFO", "UNRESOLVED_DISCLOSED",
                f"{source} explicitly discloses an unresolved utilization "
                f"reading (quantized-floor class) — band check skipped on "
                f"disclosed data-quality grounds, NOT fabricated"))
            return "UNRESOLVED_DISCLOSED", findings
        findings.append(Finding(
            "INFO", "NO_DATA",
            "no utilization/density artefact present — band check skipped, "
            "NOT fabricated"))
        return "NO_DATA", findings

    if util_pct < 0:
        findings.append(Finding(
            "ERROR", "UTIL_NONPOSITIVE",
            f"utilization {util_pct:.3f}% from {source} is negative — "
            f"impossible / corrupt report"))
        return "FAIL", findings
    if util_pct == 0:
        # v0.2.69 — a literal 0 is NOT corruption evidence: OpenROAD's
        # `report_design_area` prints INTEGER-rounded utilization, so any
        # true value in [0, 0.5)% prints as "0%". A placed design cannot
        # have exactly-zero utilization, so a parsed 0 means "below the
        # report's precision floor", not "impossible". Corruption is
        # indicated by NEGATIVE or >100 values only. Advisory, rc=0.
        findings.append(Finding(
            "WARNING", "UTIL_ZERO_UNRESOLVED",
            f"utilization reads 0% from {source} — integer-rounded "
            f"report floor (true value < 0.5%, below report precision); "
            f"no usable band datum. Advisory only: extremely low fill is "
            f"already advisory territory, and a quantized 0 is not a "
            f"corrupt report (negative / >100 would be)."))
        return "WARN", findings
    if util_pct > 100.0 + 1e-6:
        findings.append(Finding(
            "ERROR", "UTIL_OVER_100",
            f"utilization {util_pct:.3f}% from {source} exceeds 100% — "
            f"cell-area overlap / illegal placement"))
        return "FAIL", findings

    if util_pct < _WARN_LOW:
        findings.append(Finding(
            "WARNING", "UTIL_UNDER_BAND",
            f"utilization {util_pct:.3f}% (source {source}) is below the "
            f"{_WARN_LOW:.0f}-{_WARN_HIGH:.0f}% advisory band — "
            f"low fill (often normal for fixed-die / harness-bounded "
            f"designs; advisory only, not a failure)"))
        return "WARN", findings
    if util_pct > _WARN_HIGH:
        findings.append(Finding(
            "WARNING", "UTIL_OVER_BAND",
            f"utilization {util_pct:.3f}% (source {source}) is above the "
            f"{_WARN_LOW:.0f}-{_WARN_HIGH:.0f}% advisory band — "
            f"routing-congestion risk; advisory only, not a failure"))
        return "WARN", findings

    findings.append(Finding(
        "INFO", "UTIL_IN_BAND",
        f"utilization {util_pct:.3f}% (source {source}) is within the "
        f"{_WARN_LOW:.0f}-{_WARN_HIGH:.0f}% advisory band"))
    return "PASS", findings


def build_report(verdict: str, util_pct: Optional[float], source: Optional[str],
                 findings: List[Finding], project: Optional[str]) -> dict:
    return {
        "program": "utilization_band_check",
        "version": "1.0.0",
        "project_dir": project,
        "verdict": verdict,
        "summary": {
            "utilization_pct": (round(util_pct, 4)
                                if util_pct is not None else None),
            "source": source,
            "advisory_band_low_pct": _WARN_LOW,
            "advisory_band_high_pct": _WARN_HIGH,
            "errors_count": len([f for f in findings if f.severity == "ERROR"]),
            "warnings_count": len([f for f in findings
                                   if f.severity == "WARNING"]),
            "pass": verdict in ("PASS", "WARN"),
        },
        "findings": [asdict(f) for f in findings],
    }


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Classify floorplan/placement utilization vs advisory band")
    parser.add_argument("project_dir", nargs="?", default=None,
                        help="project directory to scan for utilization reports")
    parser.add_argument("--util", type=float, default=None,
                        help="direct utilization value (percent or fraction)")
    parser.add_argument("--json", default=None, help="Output JSON report path")
    parser.add_argument("--strict", action="store_true",
                        help="treat NO_DATA as a failure (rc=1)")
    args = parser.parse_args(argv)

    project_str: Optional[str] = None
    if args.util is not None:
        util_pct = _coerce_pct(args.util)
        source = "--util arg"
    elif args.project_dir is not None:
        project = Path(args.project_dir)
        if not project.is_dir():
            print(f"[utilization_band_check] project dir not found: {project}",
                  file=sys.stderr)
            return 2
        project_str = str(project)
        util_pct, source = read_utilization(project)
    else:
        parser.error("provide a project_dir or --util")
        return 2  # pragma: no cover

    verdict, findings = classify(util_pct, source)
    report = build_report(verdict, util_pct, source, findings, project_str)
    report_json = json.dumps(report, indent=2, ensure_ascii=False)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(report_json)
    print(report_json)

    if verdict == "FAIL":
        return 1
    if verdict in ("NO_DATA", "UNRESOLVED_DISCLOSED") and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
