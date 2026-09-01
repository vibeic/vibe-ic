#!/usr/bin/env python3
"""
threshold_range_contiguity_check.py — Discrete classification ranges must be contiguous.

Generic pattern (applies to any IC, not <chip-class>-specific):
  When RTL classifies an input into discrete symbols via range thresholds
  (pulse width bins, voltage levels, frequency bins, ADC codes), the ranges
  MUST be contiguous — every possible input value must fall into exactly
  one class, never into a gap between ranges.

  A 1-tick gap between `H1_MAX` and `H0_MIN` seems harmless on paper but
  causes silent-drop behaviour on hardware: a pulse whose sampled width
  lands on the boundary due to jitter or clock drift is classified as
  "reject" and the containing packet is silently discarded.

Real occurrence (v068 <benchmark> fresh-agent):
  L8_RTL_CONSTANTS declared:
    H1_MIN=1 ... H1_MAX=192   (0.02us .. 3.84us)
    H0_MIN=196 ... H0_MAX=612 (3.92us .. 12.24us)
    BR_MIN=637 ... BR_MAX=1314 (12.74us .. 26.28us)
  Gaps: H1_MAX→H0_MIN = 192→196 (4 ticks), H0_MAX→BR_MIN = 612→637 (25 ticks).
  On hardware, real pulses occasionally landed in either gap and were
  silently rejected → rx_decoder byte-frame shift → CRC fail.

  The fix is trivial once caught: make ranges contiguous
  (H1_MAX=199, H0_MIN=200, H0_MAX=639, BR_MIN=640). But it must be
  caught at Phase 1 generation time — this gate does that.

Generic applicability
---------------------
- Any `{X}_MIN/{X}_MAX` paired thresholds forming an exhaustive
  classification over a continuous measurement.
- Also applies to voltage bins, ADC codes, timer ranges, or any discrete
  bucketing that must cover its domain.

Scope
-----
The gate looks at a structured L8 / timing-constants JSON and finds
entries of shape `{"name": "<X>_MIN", "value_dec": N}` paired with
`{"name": "<X>_MAX", ...}`. For each ordered pair of classes (by name
prefix order in an `--order` arg, or inferred alphabetically), verify
that the NEXT class's MIN equals PREVIOUS class's MAX + 1.

Usage
-----
    threshold_range_contiguity_check.py <L8_RTL_CONSTANTS.json>
        [--order H1,H0,BR,IBT]      # ordered list of class prefixes
        [--json]

Exit codes
----------
    0 = all ranges contiguous
    1 = one or more gaps (or overlaps) found
    2 = IO / parse error

Not a replacement for `clock_scale_consistency_check.py` (which checks
the absolute values are in the right clock domain) — this gate
specifically checks range continuity.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

DEFAULT_CLASS_ORDER = ["H1", "H0", "BR"]
# IBT / WKP are typically SEPARATE measurement domains (IBT = HIGH-idle
# time between bytes; WKP = abnormally wide LOW pulse), not part of the
# same continuous LOW-pulse classification chain as H1/H0/BR. Users who
# DO want them in a chain can pass `--order H1,H0,BR,IBT` explicitly.


@dataclass
class Finding:
    severity: str
    rule: str
    field: str
    message: str


def _walk(obj: Any, path: str = ""):
    if isinstance(obj, dict):
        yield path, obj
        for k, v in obj.items():
            yield from _walk(v, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            yield from _walk(item, f"{path}[{i}]" if path else f"[{i}]")


_VERILOG_LITERAL = re.compile(
    r"^\s*(?:\d+)?'(?:[bhdoBHDO])\s*([0-9a-fA-F_]+)\s*$"
)


def _parse_int(v: Any) -> int | None:
    """Parse int | float | '123' | Verilog '8'd123' / '0xFF'."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(v)
    if isinstance(v, str):
        s = v.strip()
        m = _VERILOG_LITERAL.match(s)
        if m:
            digits = m.group(1).replace("_", "")
            base_ch = s[s.index("'") + 1].lower()
            base = {"b": 2, "h": 16, "d": 10, "o": 8}.get(base_ch, 10)
            try:
                return int(digits, base)
            except ValueError:
                return None
        try:
            if s.lower().startswith("0x"):
                return int(s, 16)
            return int(s)
        except ValueError:
            return None
    return None


def _collect_thresholds(doc: Any) -> dict[str, dict[str, int]]:
    """Collect {class_name: {MIN: int, MAX: int}} from doc.

    Recognised name forms (bound-suffix may be _MIN/_MAX, optionally with
    _TICKS / _CYC / _COUNTS / _COUNT tails; class may include _LOW or
    _HIGH infix like H1_LOW_MIN — we strip that infix):
      H1_MIN, H1_MIN_TICKS, H1_LOW_MIN, H1_LOW_MIN_COUNTS, etc.

    Recognised value forms:
      {"value_dec": 1}
      {"value": "8'd1"}        (Verilog literal)
      {"value": "0x0C"}        (hex string)
      {"value": 1}
    """
    thresholds: dict[str, dict[str, int]] = {}

    def _record(name: str, val: int):
        # Strip suffixes: _TICKS, _CYC, _COUNTS, _COUNT
        name_up = name.upper()
        name_up = re.sub(r"_(?:TICKS|CYC|COUNTS|COUNT)$", "", name_up)
        # Match CLASS[_LOW|_HIGH]?_MIN|MAX
        m = re.match(r"^([A-Z0-9]+?)(?:_LOW|_HIGH)?_(MIN|MAX)$", name_up)
        if not m:
            return
        cls, bound = m.group(1), m.group(2)
        thresholds.setdefault(cls, {})[bound] = val

    for p, v in _walk(doc):
        if isinstance(v, dict):
            name = str(v.get("name", "")).strip()
            if name:
                for val_key in ("value_dec", "value", "val", "value_hex"):
                    if val_key in v:
                        n = _parse_int(v[val_key])
                        if n is not None:
                            _record(name, n)
                            break
            for k2, v2 in v.items():
                n = _parse_int(v2)
                if n is not None:
                    _record(str(k2), n)

    return thresholds


def check(doc: Any, class_order: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    thresholds = _collect_thresholds(doc)

    if not thresholds:
        # The caller distinguishes explicit N/A from an undeclared empty
        # domain; this function has no threshold relation to adjudicate.
        return findings

    chain = set(class_order)
    for cls, bounds in thresholds.items():
        if cls not in chain:
            # Out-of-chain classes (IBT, WKP, etc.) may legitimately have
            # only MIN (single-sided threshold); don't complain.
            continue
        if "MIN" not in bounds or "MAX" not in bounds:
            findings.append(Finding(
                "ERROR", "incomplete_threshold_pair", cls,
                f"Class '{cls}' is in the contiguity chain but only has "
                f"{list(bounds.keys())}; needs both {cls}_MIN and {cls}_MAX.",
            ))
            continue
        if bounds["MIN"] > bounds["MAX"]:
            findings.append(Finding(
                "ERROR", "inverted_threshold_pair", cls,
                f"{cls}_MIN ({bounds['MIN']}) > {cls}_MAX ({bounds['MAX']}).",
            ))

    found_classes = [c for c in class_order if c in thresholds]
    # Classes not in class_order are treated as independent domains —
    # they're NOT added to the contiguity chain. User must explicitly
    # include them via `--order` if they form a single domain.

    for i in range(len(found_classes) - 1):
        a = found_classes[i]
        b = found_classes[i + 1]
        if "MAX" not in thresholds[a] or "MIN" not in thresholds[b]:
            continue
        a_max = thresholds[a]["MAX"]
        b_min = thresholds[b]["MIN"]
        gap = b_min - a_max - 1
        if gap > 0:
            findings.append(Finding(
                "ERROR", "range_gap", f"{a}_MAX → {b}_MIN",
                f"{a}_MAX={a_max}, next class {b}_MIN={b_min}. Gap of "
                f"{gap} tick(s) — pulses/values landing in [{a_max+1}, "
                f"{b_min-1}] will be silently rejected. "
                f"Fix: set {a}_MAX={b_min-1} (contiguous) or adjust "
                f"{b}_MIN={a_max+1}.",
            ))
        elif gap < 0:
            findings.append(Finding(
                "ERROR", "range_overlap", f"{a}_MAX ↔ {b}_MIN",
                f"{a}_MAX={a_max} overlaps {b}_MIN={b_min} (overlap "
                f"{abs(gap)+1} tick(s)). Ambiguous classification.",
            ))

    return findings


def declares_no_threshold_classifier(doc: Any) -> bool:
    """Only an explicit design declaration can make an empty domain N/A."""
    if not isinstance(doc, dict):
        return False
    return any(doc.get(key) is True for key in (
        "no_rx_classifier_ticks_in_input",
        "no_thresholds_in_input",
        "no_threshold_classifier_in_input",
        "no_classification_logic_in_input",
    ))


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Verify discrete classification ranges are contiguous.",
    )
    ap.add_argument("constants", help="L8_RTL_CONSTANTS.json (or any doc with MIN/MAX threshold pairs).")
    ap.add_argument("--order", default=",".join(DEFAULT_CLASS_ORDER),
                    help="Ordered class prefixes (comma-separated). Default: H1,H0,BR,IBT.")
    ap.add_argument("--json", nargs='?', const='-', default=None, metavar='PATH',
                    help="Emit JSON. With PATH writes to file; bare flag prints to stdout.")
    args = ap.parse_args()

    try:
        with open(args.constants, "r") as f:
            doc = json.load(f)
    except FileNotFoundError:
        print(f"error: file not found: {args.constants}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as e:
        print(f"error: invalid JSON: {e}", file=sys.stderr)
        return 2

    class_order = [c.strip().upper() for c in args.order.split(",") if c.strip()]
    thresholds = _collect_thresholds(doc)
    declared_na = not thresholds and declares_no_threshold_classifier(doc)
    applicable: bool | None = False if declared_na else (
        True if thresholds else None)
    findings = check(doc, class_order)
    if not thresholds and not declared_na:
        findings.append(Finding(
            "WARN", "no_thresholds_found", "(root)",
            "No MIN/MAX threshold pairs and no explicit no-classifier "
            "declaration were found. Declare the condition N/A or provide "
            "the classification thresholds.",
        ))
    errors = [f for f in findings if f.severity == "ERROR"]
    verdict = ("SKIPPED-CONDITION" if declared_na else
               "PASS" if not errors else "FAIL")

    if args.json:
        _txt = json.dumps({
            "source_file": args.constants,
            "applicable": applicable,
            "reason_class": "DESIGN_DECLARED_NA" if declared_na else None,
            "reason": (None if not declared_na else
                       "The design document declares no MIN/MAX threshold "
                       "classification pairs."),
            "total_findings": len(findings),
            "errors": len(errors),
            "findings": [asdict(f) for f in findings],
            "verdict": verdict,
        }, indent=2)
        if args.json == '-':
            print(_txt)
        else:
            from pathlib import Path as _P
            _P(args.json).parent.mkdir(parents=True, exist_ok=True)
            _P(args.json).write_text(_txt + "\n")
    else:
        for f in findings:
            print(f"[{f.severity}] {f.rule} @ {f.field}: {f.message}")
        print(f"\n{len(errors)} error(s), {len(findings)-len(errors)} warning(s)")
        print(verdict)

    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
