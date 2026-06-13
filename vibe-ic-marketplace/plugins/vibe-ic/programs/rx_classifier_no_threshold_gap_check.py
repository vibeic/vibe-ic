#!/usr/bin/env python3
"""rx_classifier_no_threshold_gap_check.py — Wave 26 (v0.119.58) gate.

Purpose
-------
Enforce that L8.rx_classifier_ticks has CONTIGUOUS thresholds.
Specifically the upper bound of one symbol class must meet (or
overlap) the lower bound of the next class with NO uncovered
gap.  When a gap exists, host bit jitter falling inside the gap
gets mis-classified deterministically (the bit is neither BIT1
nor BIT0 nor BR), the chip RX FSM enters a wrong path, CRC
fails, host pads byte[6]=0x02.

Background
----------
Surfaced by the v0.119.57 31st-attempt fresh-agent benchmark
(`docs/design/MIN_DELTA_DIAG_v0119.57.md`).  Input doc
`20230103-3.txt` carries TWO vendor classifier tables
(historical NEW vs ORG variants).  The fresh agent picked the
NEW table H0_MIN=196 paired with H1_MAX=192 from the same
table — a 3-tick gap at [193, 194, 195].  All 5/5 connect_test
runs returned byte[6]=0x02 because real-silicon BIT0 transitions
landing on those edge ticks were classified as no-symbol →
frame discarded.

Scope
-----
Chip-AGNOSTIC.  Synonym sets cover the canonical
`rx_classifier_ticks` shape used across half-duplex single-wire
protocols (AID class, LIN-ish, K-line-ish).  No vendor / chip /
PDK / tester-specific identifier is hard-coded.

Verdicts
--------
- PASS               — every adjacent threshold pair is contiguous.
- FAIL               — at least one pair has gap > 0.
- SKIP               — no L8 / no rx_classifier_ticks block.
- PASS_WITH_WAIVER   — waiver `rx_classifier_threshold_gap_intentional`
                       (≥40 chars).

Usage
-----
    python3 rx_classifier_no_threshold_gap_check.py <project_dir>
    python3 rx_classifier_no_threshold_gap_check.py <project_dir> --json

Exit codes
----------
    0 = PASS / SKIP / waiver / WARN
    1 = FAIL
    2 = IO / parse error
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import _path_layout as _pl

# ----------------------------------------------------------------------
# Synonyms — generic protocol-classifier vocabulary
# ----------------------------------------------------------------------
TABLE_KEYS: Tuple[str, ...] = (
    "rx_classifier_ticks",
    "bit_classifier_ticks",
    "classifier_thresholds",
    "rx_thresholds",
)

NESTED_PARENT_KEYS: Tuple[str, ...] = (
    "vendor_fpga_reference_table",
    "fpga_reference_table",
    "vendor_table",
    "rx_classifier",
)

# Adjacent pairs (upper_name, lower_name) that must be contiguous —
# upper_max + 1 >= lower_min.  Each pair is silent-skipped when either
# side is absent.
ADJACENT_PAIRS: Tuple[Tuple[str, str, str, str], ...] = (
    # (upper_class, upper_max_key, lower_class, lower_min_key)
    ("BIT1", "h1_max", "BIT0", "h0_min"),
    ("BIT0", "h0_max", "BR",   "br_min"),
    ("BR",   "br_max", "WKP",  "wkp_min"),
)

WAIVER_KEY = "rx_classifier_threshold_gap_intentional"
WAIVER_MIN_CHARS = 40


# ----------------------------------------------------------------------
# Data containers
# ----------------------------------------------------------------------
@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str = ""


@dataclass
class AuditResult:
    program: str = "rx_classifier_no_threshold_gap_check"
    verdict: str = "PASS"
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


# ----------------------------------------------------------------------
# L8 loader (synonym-tolerant; mirrors rx_classifier_thresholds_match_l8)
# ----------------------------------------------------------------------
def _load_classifier_table(project: Path) -> Optional[Dict[str, int]]:
    gd = _pl.generated_docs_dir(project)
    if not gd.is_dir():
        return None
    candidates: List[Path] = []
    for pat in ("L8*.json", "L8.json", "L8_RTL_CONSTANTS.json",
                "L8_RTL_CONSTANTS*.json"):
        candidates.extend(sorted(gd.glob(pat)))
    seen: set = set()
    for p in candidates:
        if p in seen:
            continue
        seen.add(p)
        try:
            data = json.loads(p.read_text(errors="replace"))
        except (OSError, json.JSONDecodeError):
            continue
        table = _find_table_in_obj(data)
        if table:
            return table
    return None


def _find_table_in_obj(obj) -> Optional[Dict[str, int]]:
    if not isinstance(obj, dict):
        return None
    for key in TABLE_KEYS:
        if key in obj and isinstance(obj[key], dict):
            flat = _flatten_threshold_dict(obj[key])
            if flat:
                return flat
    for parent in NESTED_PARENT_KEYS:
        if parent in obj and isinstance(obj[parent], dict):
            inner = _find_table_in_obj(obj[parent])
            if inner:
                return inner
    flat = _flatten_threshold_dict(obj)
    if flat:
        return flat
    return None


_RECOGNISED_SUBKEYS = {
    "h0_min", "h0_max", "h1_min", "h1_max",
    "br_min", "br_max", "ibt_min", "ibt_max",
    "wkp_min", "wkp_max",
}


def _flatten_threshold_dict(d: dict) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for k, v in d.items():
        if not isinstance(k, str):
            continue
        lk = k.lower()
        if lk in _RECOGNISED_SUBKEYS:
            try:
                out[lk] = int(v)
            except (TypeError, ValueError):
                continue
    return out


# ----------------------------------------------------------------------
# Waiver
# ----------------------------------------------------------------------
def _is_waived(project: Path) -> bool:
    p = project / "waivers.json"
    if not p.is_file():
        return False
    try:
        d = json.loads(p.read_text(errors="replace"))
    except (OSError, json.JSONDecodeError):
        return False
    v = d.get(WAIVER_KEY, "")
    return isinstance(v, str) and len(v.strip()) >= WAIVER_MIN_CHARS


# ----------------------------------------------------------------------
# Gap analysis
# ----------------------------------------------------------------------
def _find_gaps(table: Dict[str, int]) -> List[dict]:
    """Return list of gap dicts: {upper_class, upper_max_key, upper_max,
    lower_class, lower_min_key, lower_min, gap_size, gap_range}."""
    gaps: List[dict] = []
    for u_cls, u_key, l_cls, l_key in ADJACENT_PAIRS:
        if u_key not in table or l_key not in table:
            continue
        u_max = table[u_key]
        l_min = table[l_key]
        # Contiguous: u_max + 1 >= l_min (overlap is OK).
        gap_size = l_min - u_max - 1
        if gap_size > 0:
            gap_range = list(range(u_max + 1, l_min))
            gaps.append({
                "upper_class": u_cls,
                "upper_max_key": u_key,
                "upper_max": u_max,
                "lower_class": l_cls,
                "lower_min_key": l_key,
                "lower_min": l_min,
                "gap_size": gap_size,
                "gap_range": gap_range,
            })
    return gaps


# ----------------------------------------------------------------------
# Audit driver
# ----------------------------------------------------------------------
def run_audit(project: Path) -> AuditResult:
    result = AuditResult()
    table = _load_classifier_table(project)
    if not table:
        result.verdict = "SKIP"
        result.findings.append(Finding(
            rule="NO_L8_CLASSIFIER",
            severity="INFO",
            message=("L8 has no rx_classifier_ticks block; gate skipped"),
        ))
        result.summary = {"thresholds": {}, "gaps": []}
        return result

    gaps = _find_gaps(table)

    if _is_waived(project):
        result.verdict = "PASS_WITH_WAIVER"
        result.findings.append(Finding(
            rule="WAIVED",
            severity="INFO",
            message=(f"Waiver '{WAIVER_KEY}' set; "
                     f"{len(gaps)} gap(s) deferred"),
        ))
        result.summary = {"thresholds": table, "gaps": gaps}
        return result

    if gaps:
        result.verdict = "FAIL"
        for g in gaps:
            tail = (
                f"L8.rx_classifier_ticks has a {g['gap_size']}-tick "
                f"uncovered gap between {g['upper_class']} (max="
                f"{g['upper_max']}) and {g['lower_class']} (min="
                f"{g['lower_min']}). "
                f"Real silicon bit jitter falling at ticks "
                f"{g['gap_range']} will be mis-classified.\n"
                "Hint: when input docs have multiple vendor tables "
                "(e.g. 20230103-3.txt has both NEW and ORG versions), "
                "select the version with NO gap (e.g. ORG H0_MIN=193 "
                "instead of NEW H0_MIN=196). Plugin gate "
                "`rtl-constants-gen` must disambiguate."
            )
            # Verbatim diagnostic substring tested by the verify step.
            shorthand = (
                f"{g['gap_size']}-tick gap "
                f"[{g['gap_range'][0]}.."
                f"{g['gap_range'][-1]}]"
            )
            result.findings.append(Finding(
                rule="RX_CLASSIFIER_THRESHOLD_GAP",
                severity="ERROR",
                message=f"FAIL — RX_CLASSIFIER_THRESHOLD_GAP "
                        f"({shorthand}). {tail}",
            ))
        result.summary = {"thresholds": table, "gaps": gaps}
        return result

    result.findings.append(Finding(
        rule="THRESHOLDS_CONTIGUOUS",
        severity="INFO",
        message=("All adjacent threshold pairs in "
                 "L8.rx_classifier_ticks are contiguous (no gap)."),
    ))
    result.summary = {"thresholds": table, "gaps": []}
    return result


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if not args.project_dir.is_dir():
        print(f"ERROR: {args.project_dir} is not a directory",
              file=sys.stderr)
        return 2

    result = run_audit(args.project_dir)

    if args.json:
        print(json.dumps(asdict(result), indent=2, default=str))
    else:
        print(f"[{result.verdict}] rx_classifier_no_threshold_gap_check")
        print(f"  thresholds: "
              f"{result.summary.get('thresholds', {}) or '(none)'}")
        print(f"  gaps found: {len(result.summary.get('gaps', []))}")
        for f in result.findings:
            print(f"  [{f.severity}] {f.rule}: {f.message}")

    return 1 if result.verdict == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
