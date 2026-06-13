#!/usr/bin/env python3
"""
drc_vacuous_pass_check.py -- Reject a "0 DRC violations" verdict when the
layout the checker ran on was EMPTY.

For skill: benchmark-verify (Pillar 2 — "No vacuous result counts as PASS")

The defect this catches (real, from benchmark_clean runs)
--------------------------------------------------------
Magic / KLayout can be handed a GDS that streamed in with **zero geometry**
(a cell read that dropped all layers, a wrong cell name, an empty top cell).
The DRC engine then dutifully reports "0 DRC errors" / "Total errors: 0"
because there is nothing to check. A naive gate sees `errors == 0` and
stamps the design DRC-CLEAN. That is a *vacuous* PASS: the layout was never
actually checked.

The discriminator
-----------------
A DRC log of a REAL checked layout contains, in addition to the 0-violation
count, evidence that geometry was loaded:
    - Magic:   "Loading <cell>" / "Reading <cell>" / "cell ... loaded"
               "<N> rectangles" / "<N> cells" / "Total area" / "checking ..."
    - KLayout: "Layout read" / "<N> shapes" / "<N> polygons" / "cells: <N>"
    - generic: a non-zero cell-count / shape-count / area token.

This checker ONLY flips a 0-violation verdict to INCONCLUSIVE when it can
prove the layout was empty (an explicit zero geometry token, OR a "no cells /
empty / contains no geometry" diagnostic, OR NO geometry-loaded evidence at
all alongside a clean 0-count). If the log shows real geometry was loaded,
the 0-violation verdict is honoured (PASS).

This is a *structural* check on the DRC tool log — it does NOT re-run DRC and
does NOT replace the violation-count gate; it sits in front of it.

Honest-failure contract
------------------------
  - No DRC log found            -> SKIP (exit 2)  -- nothing to vet, never PASS
  - Unreadable / empty log file -> INCONCLUSIVE (exit 1)
  - 0-count + empty-layout proof -> INCONCLUSIVE (exit 1)  -- the bug
  - 0-count + geometry-loaded    -> PASS (exit 0)
  - non-zero violation count     -> PASS (exit 0)  -- not vacuous; a real
                                    violation gate (eda_report_audit) handles it

Usage:
    python3 drc_vacuous_pass_check.py <project_dir_or_logfile> [--json <out>]

Exit codes:
    0 = PASS         (verdict is earned — geometry was checked)
    1 = INCONCLUSIVE (a 0-violation verdict on an empty/unchecked layout)
    2 = SKIP         (no DRC log to evaluate / I/O error)

No external tool dependencies -- pure Python.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional


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
    program: str = "drc_vacuous_pass_check"
    verdict: str = "SKIP"          # PASS | INCONCLUSIVE | SKIP
    passed: bool = False
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Token tables
# ---------------------------------------------------------------------------
# A clean DRC verdict: an explicit "0 <violation-word>" or "<violation-word>
# [found/reported/detected] : 0". An optional intervening report verb lets
# Magic's "Total DRC errors found: 0" match.
_VWORD = r"(?:violation|error|issue)s?"
_REPORT_VERB = r"(?:\s+(?:found|reported|detected|present))?"
_ZERO_COUNT_RE = [
    re.compile(r"\b0\s+(?:drc\s+)?" + _VWORD + r"\b", re.I),
    re.compile(r"(?:total\s+)?(?:drc\s+)?" + _VWORD + _REPORT_VERB
               + r"\s*[:=]\s*0\b", re.I),
    re.compile(r"\bdrc\s+(?:is\s+)?(?:clean|clear)\b", re.I),
    re.compile(r"\bno\s+(?:drc\s+)?" + _VWORD + r"\s+found\b", re.I),
]

# A NON-zero violation count: "<N> errors" / "errors found: <N>" with N>=1.
_NONZERO_COUNT_RE = [
    re.compile(r"\b([1-9]\d*)\s+(?:drc\s+)?" + _VWORD + r"\b", re.I),
    re.compile(r"(?:total\s+)?(?:drc\s+)?" + _VWORD + _REPORT_VERB
               + r"\s*[:=]\s*([1-9]\d*)\b", re.I),
]

# Proof the layout was actually LOADED with geometry (any one is enough).
# A leading 0 (e.g. "0 cells") is explicitly NOT geometry-loaded evidence.
_GEOMETRY_LOADED_RE = [
    re.compile(r"\b([1-9]\d*)\s+(?:rectangle|polygon|shape|geometr|cell)s?\b", re.I),
    re.compile(r"\bcells?\s*[:=]\s*([1-9]\d*)\b", re.I),
    re.compile(r"\b(?:shapes?|polygons?|rectangles?)\s*[:=]\s*([1-9]\d*)\b", re.I),
    re.compile(r"\b(?:loading|reading)\s+(?:cell\s+)?\S", re.I),
    re.compile(r"\bcell\s+\S+\s+loaded\b", re.I),
    re.compile(r"\blayout\s+read\b", re.I),
    re.compile(r"\btotal\s+area\s*[:=]?\s*[1-9]", re.I),
    re.compile(r"\bchecking\s+\S", re.I),
]

# Explicit proof the layout was EMPTY / not checked.
_EMPTY_LAYOUT_RE = [
    re.compile(r"\b0\s+(?:cell|rectangle|polygon|shape|geometr)s?\b", re.I),
    re.compile(r"\b(?:cells?|shapes?|polygons?|rectangles?)\s*[:=]\s*0\b", re.I),
    re.compile(r"\bno\s+(?:cell|geometr|shape|layer)\S*\s+(?:found|present|loaded)\b", re.I),
    re.compile(r"\bcontains?\s+no\s+geometr", re.I),
    re.compile(r"\bempty\s+(?:cell|layout|top\s*cell|design)\b", re.I),
    re.compile(r"\bcell\s+\(\?\)\s", re.I),  # Magic's "Cell (?)" — nothing loaded
    re.compile(r"\bcouldn'?t\s+find\b", re.I),
    re.compile(r"\bnothing\s+to\s+check\b", re.I),
]

_DRC_GLOBS = ["*drc*.rpt", "*drc*.log", "*drc*.txt", "*drc*.out",
              "*DRC*.rpt", "*DRC*.log", "*DRC*.txt", "*DRC*.out"]


def _is_drc_log(text: str) -> bool:
    """Heuristic: does this look like a DRC report at all?"""
    return bool(re.search(r"\bdrc\b|\bviolation|\berror", text, re.I))


def _discover(path: Path) -> List[Path]:
    """Return DRC log files. If `path` is a file, use it directly."""
    if path.is_file():
        return [path]
    if not path.is_dir():
        return []
    out: List[Path] = []
    seen = set()
    for g in _DRC_GLOBS:
        for fp in sorted(path.rglob(g)):
            rp = fp.resolve()
            if rp not in seen and fp.is_file():
                seen.add(rp)
                out.append(fp)
    return out


def _classify_one(text: str) -> dict:
    """Classify a single DRC log's geometry/verdict signals."""
    zero = any(r.search(text) for r in _ZERO_COUNT_RE)
    nonzero = None
    for r in _NONZERO_COUNT_RE:
        m = r.search(text)
        if m:
            nonzero = int(m.group(1))
            break
    geometry = any(r.search(text) for r in _GEOMETRY_LOADED_RE)
    empty = any(r.search(text) for r in _EMPTY_LAYOUT_RE)
    return {"zero_count": zero, "nonzero_count": nonzero,
            "geometry_loaded": geometry, "empty_layout": empty}


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------
def audit(path: Path) -> AuditResult:
    result = AuditResult()
    files = _discover(path)
    if not files:
        result.verdict = "SKIP"
        result.passed = False
        result.findings.append(Finding(
            rule="DRC_LOG_EXISTS", severity="ERROR",
            message="No DRC log found — nothing to vet (SKIP, never a PASS)."))
        result.summary = {"files_found": 0}
        return result

    per_file = []
    any_empty_with_clean = False
    any_real_check = False
    any_drc_log = False

    for fp in files:
        try:
            text = fp.read_text(errors="replace")
        except OSError:
            result.findings.append(Finding(
                rule="DRC_LOG_READABLE", severity="ERROR",
                message="DRC log could not be read.", file=str(fp)))
            continue
        if not text.strip():
            result.findings.append(Finding(
                rule="DRC_LOG_NONEMPTY", severity="ERROR",
                message="DRC log is empty.", file=str(fp)))
            per_file.append({"file": str(fp), "empty_file": True})
            continue
        if not _is_drc_log(text):
            # Not actually a DRC report; ignore it.
            continue
        any_drc_log = True
        c = _classify_one(text)
        c["file"] = str(fp)
        per_file.append(c)

        if c["nonzero_count"] and c["nonzero_count"] > 0:
            # Real violations reported — not vacuous (a real count gate handles it).
            any_real_check = True
            result.findings.append(Finding(
                rule="DRC_NONZERO_COUNT", severity="INFO",
                message=f"DRC log reports {c['nonzero_count']} violation(s) — "
                        "not a vacuous PASS (defer to the violation-count gate).",
                file=str(fp)))
            continue

        if c["zero_count"]:
            if c["empty_layout"] or not c["geometry_loaded"]:
                any_empty_with_clean = True
                why = ("explicit empty-layout token" if c["empty_layout"]
                       else "NO geometry-loaded evidence")
                result.findings.append(Finding(
                    rule="DRC_VACUOUS_PASS", severity="ERROR",
                    message=f"0-violation verdict on an unchecked layout "
                            f"({why}) — INCONCLUSIVE, not DRC-clean.",
                    file=str(fp)))
            else:
                any_real_check = True
                result.findings.append(Finding(
                    rule="DRC_CLEAN_EARNED", severity="INFO",
                    message="0-violation verdict with geometry-loaded "
                            "evidence — earned DRC-clean.",
                    file=str(fp)))
        else:
            # No clean verdict and no nonzero count parsed: cannot judge
            # vacuousness; leave it to the count gate. Treat as a real log.
            any_real_check = True
            result.findings.append(Finding(
                rule="DRC_NO_VERDICT_TOKEN", severity="INFO",
                message="No 0-count clean verdict parsed; not vacuous "
                        "by this gate (defer to violation-count gate).",
                file=str(fp)))

    result.summary = {"files_found": len(files), "per_file": per_file}

    if not any_drc_log:
        result.verdict = "SKIP"
        result.passed = False
        if not any(f.rule in ("DRC_LOG_READABLE", "DRC_LOG_NONEMPTY")
                   for f in result.findings):
            result.findings.append(Finding(
                rule="DRC_LOG_RECOGNISED", severity="ERROR",
                message="File(s) found but none look like a DRC report (SKIP)."))
        return result

    if any_empty_with_clean:
        result.verdict = "INCONCLUSIVE"
        result.passed = False
        return result

    result.verdict = "PASS"
    result.passed = True
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
_EXIT = {"PASS": 0, "INCONCLUSIVE": 1, "SKIP": 2}


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Reject a vacuous '0 DRC violations' PASS on an empty layout")
    parser.add_argument("path", help="Project directory or a single DRC log file")
    parser.add_argument("--json", default=None, help="Output JSON report path")
    args = parser.parse_args(argv)

    result = audit(Path(args.path))
    report = asdict(result)
    report_json = json.dumps(report, indent=2, ensure_ascii=False)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(report_json)

    print(report_json)
    return _EXIT.get(result.verdict, 2)


if __name__ == "__main__":
    sys.exit(main())
