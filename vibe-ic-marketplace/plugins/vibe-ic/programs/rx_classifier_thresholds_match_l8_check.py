#!/usr/bin/env python3
"""rx_classifier_thresholds_match_l8_check.py — Wave 14 (v0.119.47) gate.

Purpose
-------
When L8 carries a `rx_classifier_ticks` table (vendor FPGA reference
table — H0/H1/BR/IBT/WKP min/max thresholds, all in tick units), the
project's RX-decode RTL MUST consume those threshold values. The
v0.119.46 fresh-agent benchmark surfaced the failure mode this gate
closes: L8 had a 6-entry classifier table, but `rx_phy.sv` collapsed
the entire bit-decode path onto a single magic constant
`T_BIT_DECODE_THRESHOLD=200` so real-silicon bits landing in the
H1_MAX..H0_MIN gap (1 tick wide) were mis-decoded → host saw garbage
→ <half-duplex-tester> padded byte[6]=0x02 instead of 0xF2.

Scope
-----
Chip-AGNOSTIC. The gate makes no assumption about specific chip
projects, vendors, opcodes or pin names. The synonym lists below are
all generic protocol-classifier vocabulary. The numeric tolerance is
±1 tick because clock-divisor recompute can shift values by 1.

Verdicts
--------
- PASS    — every L8 threshold value is matched (±1 tick) by some
            RTL numeric literal in threshold context.
- FAIL    — L8 has N thresholds, RTL covers fewer than N-1, OR a
            specific L8 threshold value has no RTL match.
- WARN    — RTL has *extra* threshold magic numbers not in L8 (likely
            tightening / loosening the spec without justification).
- SKIP    — L8 has no rx_classifier_ticks block (different gate
            family LL-29 covers extraction).
- PASS_WITH_WAIVER — waiver `rx_classifier_thresholds_simplified_intentional`
            (≥40 chars).

Usage
-----
    python3 rx_classifier_thresholds_match_l8_check.py <project_dir>
    python3 rx_classifier_thresholds_match_l8_check.py <project_dir> --json

Exit codes
----------
    0 = PASS / SKIP / waiver
    1 = FAIL
    2 = IO / parse error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import _path_layout as _pl

# ----------------------------------------------------------------------
# Synonyms — all generic protocol-classifier vocabulary
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

# Threshold sub-keys (lowercase, with several capitalization synonyms
# resolved via .lower() walk).
THRESHOLD_SUB_KEYS: Tuple[str, ...] = (
    "h0_min", "h0_max",
    "h1_min", "h1_max",
    "br_min", "br_max",
    "ibt_min", "ibt_max",
    "wkp_min", "wkp_max",
)

# Generic RX-decode filename heuristics
RX_DECODE_HINTS: Tuple[str, ...] = (
    "rx_phy", "rx_decode", "rx_classifier",
    "bit_assembler", "bit_classifier",
    "rx_bit", "rx_sample", "phy_rx",
)

# Threshold-context name regex (matches localparam/parameter NAMES whose
# semantic role is a tick threshold). Generic protocol vocabulary only.
THRESH_NAME_RE = re.compile(
    r"(THRESHOLD|MIN|MAX|TICK|LIMIT|H0|H1|BR|IBT|WKP|BIT|CLASSIFIER)",
    re.IGNORECASE,
)

# RTL numeric-literal patterns
LOCALPARAM_RE = re.compile(
    r"\b(?:localparam|parameter)\s+(?:int\s+|integer\s+)?(?:unsigned\s+)?"
    r"(?:\[[^\]]+\]\s+)?([A-Za-z_]\w*)\s*=\s*(?:\d+'[bdh])?([0-9_]+)\s*;",
    re.IGNORECASE,
)
DEFINE_RE = re.compile(
    r"^\s*`define\s+([A-Za-z_]\w*)\s+(?:\d+'[bdh])?([0-9_]+)\s*$",
    re.MULTILINE,
)
COMPARATOR_RE = re.compile(
    r"\b(\w+)\s*([<>!=]=?)\s*(?:\d+'[bdh])?([0-9_]+)\b"
)

WAIVER_KEY = "rx_classifier_thresholds_simplified_intentional"
WAIVER_MIN_CHARS = 40
TOLERANCE_TICKS = 1


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
    program: str = "rx_classifier_thresholds_match_l8_check"
    verdict: str = "PASS"  # PASS / FAIL / WARN / SKIP / PASS_WITH_WAIVER
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


# ----------------------------------------------------------------------
# L8 loader — synonym-tolerant
# ----------------------------------------------------------------------
def _load_classifier_table(project: Path) -> Optional[Dict[str, int]]:
    """Walk generated_docs/L8*.json (synonyms) and return a dict of
    threshold_name → tick_value. Returns None when no table exists.

    Recognises top-level keys, plus nested under any of NESTED_PARENT_KEYS.
    Threshold sub-keys are matched case-insensitive.
    """
    gd = _pl.generated_docs_dir(project)
    if not gd.is_dir():
        return None

    candidates: List[Path] = []
    for pat in ("L8*.json", "L8.json", "L8_RTL_CONSTANTS.json",
                "L8_RTL_CONSTANTS*.json"):
        candidates.extend(sorted(gd.glob(pat)))

    seen = set()
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
    """Recursively walk a JSON-decoded object looking for a
    classifier table. Returns flattened {sub_key_lower: int_value}."""
    if not isinstance(obj, dict):
        return None

    # Direct top-level table
    for key in TABLE_KEYS:
        if key in obj and isinstance(obj[key], dict):
            flat = _flatten_threshold_dict(obj[key])
            if flat:
                return flat

    # Nested under a recognised parent
    for parent in NESTED_PARENT_KEYS:
        if parent in obj and isinstance(obj[parent], dict):
            inner = _find_table_in_obj(obj[parent])
            if inner:
                return inner

    # As a last resort, see if the object itself has threshold sub-keys
    # at the top level (some L8 docs flatten directly).
    flat = _flatten_threshold_dict(obj)
    if flat:
        return flat

    return None


def _flatten_threshold_dict(d: dict) -> Dict[str, int]:
    """Pull recognised threshold sub-keys (case-insensitive) into a
    flat dict {lower_name: int}."""
    out: Dict[str, int] = {}
    for k, v in d.items():
        if not isinstance(k, str):
            continue
        lk = k.lower()
        if lk in THRESHOLD_SUB_KEYS:
            try:
                out[lk] = int(v)
            except (TypeError, ValueError):
                continue
    return out


# ----------------------------------------------------------------------
# RTL scanner
# ----------------------------------------------------------------------
def _discover_rx_decode_files(project: Path) -> List[Path]:
    """Return RTL files whose filename hints at RX-decode role, OR whose
    body contains comparators on a tick-counter signal."""
    rtl_dirs = [_pl.rtl_dir(project), project]
    seen: set = set()
    cands: List[Path] = []
    for d in rtl_dirs:
        if not d.is_dir():
            continue
        for ext in ("*.sv", "*.v", "*.svh", "*.vh"):
            for p in d.rglob(ext):
                if p in seen:
                    continue
                seen.add(p)
                cands.append(p)

    # Prefer filename match; then add bodies that look RX-decode.
    keep: List[Path] = []
    for p in cands:
        name_lower = p.name.lower()
        if any(h in name_lower for h in RX_DECODE_HINTS):
            keep.append(p)
            continue
        try:
            txt = p.read_text(errors="replace")
        except OSError:
            continue
        # Body heuristic: file references rx_ + a tick-style counter +
        # a comparator literal.
        has_rx = "rx_" in txt or "rx_byte" in txt or "id_bus" in txt
        has_tick = any(t in txt.lower() for t in ("tick", "low_cnt",
                                                  "bit_cnt", "low_count"))
        if has_rx and has_tick and re.search(r">\s*\d", txt):
            keep.append(p)
    return keep


def _strip_comments(src: str) -> str:
    """Drop // line comments and /* ... */ block comments."""
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.DOTALL)
    src = re.sub(r"//[^\n]*", "", src)
    return src


def _extract_rtl_thresholds(files: List[Path]) -> Dict[Path, List[Tuple[str, int]]]:
    """For each RTL file, list `(label, value)` pairs for every
    candidate threshold the file declares or compares against.

    Sources:
      - localparam / parameter NAME = N;  with NAME hitting THRESH_NAME_RE
      - `define NAME N
      - cnt-style comparator literals (cnt > N, cnt >= N, etc.) — the
        comparator-LHS name must hint at tick / low / bit / cnt /
        width / count / classifier.
    """
    out: Dict[Path, List[Tuple[str, int]]] = {}
    counter_hint = re.compile(
        r"(tick|cnt|count|width|low|bit|pulse|classif)", re.IGNORECASE)

    for fpath in files:
        try:
            raw = fpath.read_text(errors="replace")
        except OSError:
            continue
        src = _strip_comments(raw)
        pairs: List[Tuple[str, int]] = []

        for m in LOCALPARAM_RE.finditer(src):
            name, val = m.group(1), m.group(2)
            if THRESH_NAME_RE.search(name):
                try:
                    pairs.append((name, int(val.replace("_", ""))))
                except ValueError:
                    continue

        for m in DEFINE_RE.finditer(src):
            name, val = m.group(1), m.group(2)
            if THRESH_NAME_RE.search(name):
                try:
                    pairs.append((name, int(val.replace("_", ""))))
                except ValueError:
                    continue

        for m in COMPARATOR_RE.finditer(src):
            lhs, op, val = m.group(1), m.group(2), m.group(3)
            if not counter_hint.search(lhs):
                continue
            try:
                v = int(val.replace("_", ""))
            except ValueError:
                continue
            # Skip trivial 0 / 1 / 7 / 8 (loop indices, bit positions).
            if v <= 8:
                continue
            pairs.append((f"{lhs}{op}LIT", v))

        if pairs:
            out[fpath] = pairs
    return out


# ----------------------------------------------------------------------
# Cross-check
# ----------------------------------------------------------------------
def _cross_check(l8: Dict[str, int],
                 rtl: Dict[Path, List[Tuple[str, int]]],
                 ) -> Tuple[List[str], List[Tuple[str, int]],
                            List[Tuple[str, int]]]:
    """Return (missing_names, extras, all_rtl_values).

    missing_names — L8 threshold names with no RTL value within ±1.
    extras — RTL (name, value) pairs whose value matches no L8 entry.
    all_rtl_values — flattened (label,val) over all RTL files.
    """
    rtl_values: List[Tuple[str, int]] = []
    for plist in rtl.values():
        rtl_values.extend(plist)

    all_rtl_ints = [v for _, v in rtl_values]

    missing: List[str] = []
    for name, target in l8.items():
        hit = any(abs(v - target) <= TOLERANCE_TICKS for v in all_rtl_ints)
        if not hit:
            missing.append(name)

    l8_values = list(l8.values())
    extras: List[Tuple[str, int]] = []
    for label, v in rtl_values:
        if not any(abs(v - lv) <= TOLERANCE_TICKS for lv in l8_values):
            extras.append((label, v))

    # De-duplicate extras (same value listed twice in same file is still
    # one extra magic number).
    dedup_extras: List[Tuple[str, int]] = []
    seen_vals: set = set()
    for label, v in extras:
        if v in seen_vals:
            continue
        seen_vals.add(v)
        dedup_extras.append((label, v))

    return missing, dedup_extras, rtl_values


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
# Audit driver
# ----------------------------------------------------------------------
def run_audit(project: Path) -> AuditResult:
    result = AuditResult()
    l8 = _load_classifier_table(project)
    if not l8:
        result.verdict = "SKIP"
        result.findings.append(Finding(
            rule="NO_L8_CLASSIFIER",
            severity="INFO",
            message=("L8 has no rx_classifier_ticks block; gate skipped "
                     "(extraction is covered by LL-29 family)"),
        ))
        result.summary = {"l8_thresholds": 0, "rtl_files": 0,
                          "missing": [], "extras": []}
        return result

    rx_files = _discover_rx_decode_files(project)
    if not rx_files:
        result.verdict = "SKIP"
        result.findings.append(Finding(
            rule="NO_RX_DECODE_RTL",
            severity="INFO",
            message=("No RX-decode RTL identified by filename or body "
                     "heuristics; gate skipped"),
        ))
        result.summary = {"l8_thresholds": len(l8), "rtl_files": 0,
                          "missing": [], "extras": []}
        return result

    rtl_thresholds = _extract_rtl_thresholds(rx_files)
    missing, extras, rtl_pairs = _cross_check(l8, rtl_thresholds)

    rtl_values_set = {v for _, v in rtl_pairs}
    n_l8 = len(l8)
    n_rtl_distinct = len(rtl_values_set)
    coverage_insufficient = n_rtl_distinct < n_l8 - 1

    if _is_waived(project):
        result.verdict = "PASS_WITH_WAIVER"
        result.findings.append(Finding(
            rule="WAIVED",
            severity="INFO",
            message=(f"Waiver '{WAIVER_KEY}' set "
                     f"(L8 has {n_l8} thresholds, RTL distinct values "
                     f"{n_rtl_distinct})"),
        ))
        result.summary = {
            "l8_thresholds": n_l8,
            "rtl_files": len(rx_files),
            "rtl_distinct_values": n_rtl_distinct,
            "missing": missing,
            "extras": [{"name": n, "value": v} for n, v in extras],
        }
        return result

    if coverage_insufficient:
        result.verdict = "FAIL"
        rtl_summary = ", ".join(f"{n}={v}" for n, v in rtl_pairs[:8]) \
            or "(none extracted)"
        l8_summary = ", ".join(f"{n}={v}" for n, v in l8.items())
        result.findings.append(Finding(
            rule="RTL_THRESHOLD_COVERAGE_INSUFFICIENT",
            severity="ERROR",
            message=(
                f"L8.rx_classifier_ticks defines {n_l8} thresholds: "
                f"{l8_summary}. RX-decode RTL defines only "
                f"{n_rtl_distinct} distinct threshold value(s): "
                f"{rtl_summary}. Missing: {sorted(missing)}. "
                "Hint: a single threshold cannot distinguish 4+ symbol "
                "classes (BIT0/BIT1/BR/IBT/WKP). Each L8 threshold "
                "must be referenced in the RX classifier RTL via "
                "parameter (preferred: import from L8 or generate "
                "from rtl_constants_pkg)."
            ),
        ))
    elif missing:
        result.verdict = "FAIL"
        result.findings.append(Finding(
            rule="L8_THRESHOLD_VALUE_NOT_IN_RTL",
            severity="ERROR",
            message=(
                f"L8.rx_classifier_ticks values not represented in RTL "
                f"(±{TOLERANCE_TICKS} tick tolerance): {sorted(missing)}. "
                f"L8: { {k: l8[k] for k in missing} }. RTL distinct "
                f"values: {sorted(rtl_values_set)}."
            ),
        ))

    if extras and result.verdict not in ("FAIL",):
        result.verdict = "WARN"
    if extras:
        result.findings.append(Finding(
            rule="RTL_HAS_EXTRA_THRESHOLDS",
            severity="WARNING",
            message=(
                f"RTL declares {len(extras)} threshold value(s) NOT in "
                f"L8 (±{TOLERANCE_TICKS}): "
                f"{[(n, v) for n, v in extras[:8]]}. These are unjustified "
                "magic numbers — either lift them into L8 with vendor "
                "evidence, or remove."
            ),
        ))

    if result.verdict == "PASS":
        result.findings.append(Finding(
            rule="THRESHOLDS_MATCH",
            severity="INFO",
            message=(f"All {n_l8} L8 thresholds matched in RX-decode "
                     f"RTL (±{TOLERANCE_TICKS} tick)."),
        ))

    result.summary = {
        "l8_thresholds": n_l8,
        "rtl_files": len(rx_files),
        "rtl_distinct_values": n_rtl_distinct,
        "missing": missing,
        "extras": [{"name": n, "value": v} for n, v in extras],
    }
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
        print(f"[{result.verdict}] rx_classifier_thresholds_match_l8_check")
        print(f"  L8 thresholds: {result.summary.get('l8_thresholds', 0)}")
        print(f"  RTL files scanned: {result.summary.get('rtl_files', 0)}")
        print(f"  RTL distinct values: "
              f"{result.summary.get('rtl_distinct_values', 0)}")
        for f in result.findings:
            print(f"  [{f.severity}] {f.rule}: {f.message}")

    if result.verdict == "FAIL":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
