#!/usr/bin/env python3
"""
clock_scale_consistency_check.py — Catch un-rescaled threshold values.

Problem (2026-04-22 audit): rtl-constants-gen copies numeric values from
an L8 timing doc verbatim into SystemVerilog localparams, but the L8 doc
often cites threshold values in counter-ticks under a DIFFERENT clock
than the counter's actual clock domain.

Real case (<chip-class>):
  20230103-3.txt says "H1_MIN=1 H1_MAX=192 H0_MIN=196 H0_MAX=612
                       BR_MIN=637 BR_MAX=1314"
  These are ticks under a 50 MHz reference clock (context: implicit).
  The RTL's rx_phy.v counts on sys_clk_2p5m (50 MHz / 20).
  Copying verbatim makes H1 accept 1..192 ticks-at-2.5MHz = 400ns..77us,
  while the actual H1 pulse is 1.6us (4 ticks). 20x scale error;
  rx_phy accepts garbage.

Rule enforced
-------------
For every numeric threshold in the RTL constants JSON (L8_RTL_CONSTANTS
or similar), the generator MUST record:
  {
    "name": "H1_MIN",
    "value": 4,
    "unit": "ticks",
    "domain_clock": "sys_clk_2p5m",      ← required
    "source_clock":  "ref_50MHz",         ← required (doc source)
    "source_value":  80,                  ← the raw spec number
    "scale_factor":  20,                  ← source_clock / domain_clock
    "physical_value_us": 1.6,             ← sanity cross-check
  }

This program verifies:
  1. Every threshold has BOTH domain_clock AND source_clock fields.
  2. If domain_clock != source_clock, scale_factor MUST be present and
     must equal source_freq/domain_freq (within 5% tolerance).
  3. physical_value_us (if present) must equal value * domain_period_us
     (or source_value * source_period_us) within 5%.

Usage
-----
    clock_scale_consistency_check.py <rtl_constants.json> \\
        [--clocks clocks.json] [--tolerance 0.05]

`clocks.json` is optional: a simple map {clock_name: freq_hz}.

Exit codes
----------
    0 = all thresholds consistent
    1 = one or more fields missing or scaled incorrectly
    2 = io error

Prevents
--------
The "numbers look plausible, hardware accepts nothing" failure class.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Dict, Any


REQUIRED_FIELDS = ["domain_clock", "source_clock"]


@dataclass
class Finding:
    severity: str
    name: str
    rule: str
    message: str


def _get_nested(obj: Any, path: str) -> Any:
    cur = obj
    for p in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(p)
        else:
            return None
    return cur


def _iter_thresholds(data: Any):
    """Yield (path_description, threshold_obj) for every threshold-like entry.

    Heuristic: a dict with a 'value' field AND either 'name' or a key-like
    parent name is a threshold.
    """
    def walk(node, path):
        if isinstance(node, dict):
            if "value" in node and ("name" in node or "unit" in node):
                yield path, node
            for k, v in node.items():
                yield from walk(v, f"{path}.{k}" if path else k)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                yield from walk(v, f"{path}[{i}]")
    yield from walk(data, "")


def inspect(data: Dict[str, Any], clocks: Dict[str, float] | None,
             tol: float = 0.05) -> List[Finding]:
    findings: List[Finding] = []
    thresholds = list(_iter_thresholds(data))

    if not thresholds:
        findings.append(Finding(
            "warning", "", "no-thresholds-found",
            "no threshold-like entries found (expected dicts with 'value' + 'name'/'unit')"
        ))
        return findings

    for path, t in thresholds:
        name = t.get("name", path)

        # Rule 1: required fields
        for f in REQUIRED_FIELDS:
            if f not in t:
                findings.append(Finding(
                    "error", name, f"missing-{f.replace('_','-')}",
                    f"{path}: threshold lacks '{f}' field. "
                    f"Agents copying from a doc must declare which clock "
                    f"the value is measured in AND which clock the RTL "
                    f"counter runs on."
                ))
                continue

        if "domain_clock" not in t or "source_clock" not in t:
            continue

        dom = t["domain_clock"]
        src = t["source_clock"]

        # Rule 2: scale_factor when they differ
        if dom != src:
            if "scale_factor" not in t:
                findings.append(Finding(
                    "error", name, "missing-scale-factor",
                    f"{path}: domain_clock={dom} != source_clock={src} "
                    f"but no 'scale_factor' field. Agent must compute "
                    f"scale = source_freq / domain_freq and record it."
                ))
            elif clocks:
                sf_claimed = float(t["scale_factor"])
                src_f = clocks.get(src)
                dom_f = clocks.get(dom)
                if src_f and dom_f and dom_f > 0:
                    sf_true = src_f / dom_f
                    if abs(sf_claimed - sf_true) / sf_true > tol:
                        findings.append(Finding(
                            "error", name, "scale-factor-mismatch",
                            f"{path}: claimed scale={sf_claimed} but "
                            f"{src}/{dom} = {sf_true:.3f}"
                        ))

        # Rule 3: physical_value sanity
        if "physical_value_us" in t and clocks:
            phys = float(t["physical_value_us"])
            val = float(t["value"])
            dom_f = clocks.get(dom)
            if dom_f and dom_f > 0:
                period_us = 1e6 / dom_f
                expected = val * period_us
                if expected > 0 and abs(expected - phys) / expected > tol:
                    findings.append(Finding(
                        "error", name, "physical-value-mismatch",
                        f"{path}: value={val} ticks @ {dom} "
                        f"({period_us:.3f} us/tick) ⇒ {expected:.3f} us, "
                        f"but physical_value_us={phys}. 20x-scale class bug?"
                    ))

    return findings


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    p.add_argument("input_json", help="RTL constants JSON (e.g. L8_RTL_CONSTANTS.json)")
    p.add_argument("--clocks", help="Optional JSON: {clock_name: freq_hz}")
    p.add_argument("--tolerance", type=float, default=0.05,
                   help="Max relative error (default 0.05)")
    p.add_argument("--json", help="Write findings JSON")
    args = p.parse_args(argv)

    try:
        data = json.loads(Path(args.input_json).read_text())
    except Exception as exc:
        print(f"clock_scale_consistency_check: cannot read "
              f"{args.input_json}: {exc}", file=sys.stderr)
        return 2

    clocks = None
    if args.clocks:
        try:
            clocks = json.loads(Path(args.clocks).read_text())
        except Exception as exc:
            print(f"clock_scale_consistency_check: cannot read "
                  f"{args.clocks}: {exc}", file=sys.stderr)
            return 2

    findings = inspect(data, clocks, tol=args.tolerance)
    errors = [f for f in findings if f.severity == "error"]
    warnings = [f for f in findings if f.severity == "warning"]

    print(f"\n=== clock_scale_consistency_check ===")
    print(f"  errors: {len(errors)}  warnings: {len(warnings)}")
    for f in findings[:20]:
        icon = "✗" if f.severity == "error" else "⚠"
        print(f"  {icon} {f.name}: {f.rule}")
        print(f"       {f.message}")

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(
            {"errors": [asdict(f) for f in errors],
             "warnings": [asdict(f) for f in warnings]},
            indent=2))

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
