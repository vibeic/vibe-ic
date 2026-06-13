#!/usr/bin/env python3
"""
arch_dse_pareto.py -- Deterministic micro-architecture design-space exploration.

Codifies the four analytic PPA formulas from
skills/architecture-explore/SKILL.md (Workflow step 2) so the throughput /
area / power / latency math runs identically every time, and applies a
Pareto-dominance filter so the LLM no longer has to eyeball which candidates
are dominated.

The four formulas (verbatim from the skill):

    Throughput = f(parallelism, frequency)        -> parallelism * frequency
    Area      ~ Sum(units * unit_area) + memory * bit_area
    Power     ~ activity * C * Vdd^2 * f
    Latency   = depth * cycle_time   (cycle_time = 1 / frequency)

Input: a knob table where each candidate gives its knob values plus the
per-unit coefficients needed by the formulas. Coefficients are supplied by
the caller (chip-AGNOSTIC -- this program hard-codes NO process numbers, NO
chip names, NO benchmark paths). Anything the caller omits degrades to a
neutral default and the candidate is reported, never crashed on.

Pareto objective directions (fixed, standard for PPA DSE):
    throughput  -> MAXIMISE
    area        -> MINIMISE
    power       -> MINIMISE
    latency     -> MINIMISE

A candidate A dominates B iff A is no worse than B on every objective and
strictly better on at least one. The Pareto frontier is every candidate not
dominated by any other.

Input JSON shape (a list, or {"candidates": [...]}):

    [
      {
        "name": "p1_f500",          # optional label
        "parallelism": 1,            # lanes
        "frequency_mhz": 500,        # f
        "depth": 4,                  # pipeline depth (cycles) -> latency
        "units": [                   # area: Sum(count * unit_area)
            {"count": 1, "unit_area": 1000.0}
        ],
        "memory_bits": 0,            # area: memory term
        "bit_area": 0.0,             # area per memory bit
        "activity": 0.2,             # power: switching activity (0..1)
        "cap": 1.0,                  # power: lumped C (pF)
        "vdd": 0.9                   # power: supply (V)
      },
      ...
    ]

Each candidate may instead give an aggregate "area_units" number (Sum already
done by the caller) in place of the "units" list.

Usage:
    python3 arch_dse_pareto.py knobs.json
    python3 arch_dse_pareto.py knobs.json --json out.json
    cat knobs.json | python3 arch_dse_pareto.py -

Exit codes:
    0 = always when at least one candidate was evaluated (this is a
        calculator + filter, not a lint -- it never raises a false alarm)
    2 = the input could not be parsed into any candidate at all
        (reported as MISSING, never a stack trace)

No external dependencies -- pure Python / stdlib.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional


# Objective directions for the Pareto filter. +1 = larger is better,
# -1 = smaller is better. These are fixed by PPA semantics, not tunable.
OBJECTIVES = {
    "throughput": +1,
    "area": -1,
    "power": -1,
    "latency": -1,
}


@dataclass
class Candidate:
    name: str
    # echoed knobs (for the report; not all are used by every formula)
    knobs: Dict[str, Any] = field(default_factory=dict)
    # computed metrics
    throughput: float = 0.0
    area: float = 0.0
    power: float = 0.0
    latency: float = 0.0
    pareto: bool = False
    dominated_by: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


def _num(value: Any, default: float = 0.0) -> float:
    """Coerce to float, degrading gracefully on junk (never raises)."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _area_from_units(spec: Dict[str, Any], notes: List[str]) -> float:
    """Area ~ Sum(units * unit_area) + memory * bit_area.

    Accepts either an explicit "units" list of {count, unit_area} or a
    pre-summed "area_units" scalar. Missing pieces contribute 0.0.
    """
    units_term = 0.0
    if isinstance(spec.get("units"), list):
        for u in spec["units"]:
            if not isinstance(u, dict):
                notes.append("skipped a non-dict entry in 'units'")
                continue
            count = _num(u.get("count"), 0.0)
            unit_area = _num(u.get("unit_area"), 0.0)
            units_term += count * unit_area
    elif "area_units" in spec:
        units_term = _num(spec.get("area_units"), 0.0)
    else:
        notes.append("no 'units' or 'area_units' -> logic area term = 0")

    memory_bits = _num(spec.get("memory_bits"), 0.0)
    bit_area = _num(spec.get("bit_area"), 0.0)
    return units_term + memory_bits * bit_area


def evaluate(spec: Dict[str, Any], index: int) -> Candidate:
    """Apply the four formulas to one candidate spec, degrading gracefully."""
    notes: List[str] = []
    name = str(spec.get("name") or spec.get("id") or f"cand_{index}")

    parallelism = _num(spec.get("parallelism"), 1.0)
    freq_mhz = _num(spec.get("frequency_mhz", spec.get("freq_mhz")), 0.0)
    depth = _num(spec.get("depth"), 0.0)
    activity = _num(spec.get("activity"), 0.0)
    cap = _num(spec.get("cap", spec.get("capacitance")), 0.0)
    vdd = _num(spec.get("vdd"), 0.0)

    # Throughput = parallelism * frequency  (results/second, in M-ops/s)
    throughput = parallelism * freq_mhz

    # Area ~ Sum(units * unit_area) + memory * bit_area
    area = _area_from_units(spec, notes)

    # Power ~ activity * C * Vdd^2 * f
    power = activity * cap * (vdd ** 2) * freq_mhz

    # Latency = depth * cycle_time ; cycle_time = 1 / frequency
    if freq_mhz > 0:
        cycle_time_ns = 1000.0 / freq_mhz  # ns per cycle (MHz -> ns)
        latency = depth * cycle_time_ns
    else:
        latency = 0.0
        notes.append("frequency_mhz missing/0 -> latency=0, throughput=0")

    return Candidate(
        name=name,
        knobs={
            "parallelism": parallelism,
            "frequency_mhz": freq_mhz,
            "depth": depth,
            "activity": activity,
            "cap": cap,
            "vdd": vdd,
        },
        throughput=round(throughput, 6),
        area=round(area, 6),
        power=round(power, 6),
        latency=round(latency, 6),
        notes=notes,
    )


def _dominates(a: Candidate, b: Candidate) -> bool:
    """True iff a dominates b: no worse on every objective, better on >=1."""
    no_worse = True
    strictly_better = False
    for metric, direction in OBJECTIVES.items():
        av = getattr(a, metric)
        bv = getattr(b, metric)
        # Normalise so "bigger is better" for the comparison.
        an = direction * av
        bn = direction * bv
        if an < bn:
            no_worse = False
            break
        if an > bn:
            strictly_better = True
    return no_worse and strictly_better


def pareto_filter(cands: List[Candidate]) -> List[Candidate]:
    """Mark each candidate's pareto flag + who dominates it. Returns frontier."""
    for c in cands:
        c.pareto = True
        c.dominated_by = []
    for b in cands:
        for a in cands:
            if a is b:
                continue
            if _dominates(a, b):
                b.pareto = False
                b.dominated_by.append(a.name)
    return [c for c in cands if c.pareto]


def _load_candidates(raw: Any) -> List[Dict[str, Any]]:
    """Pull the candidate list out of either a bare list or a wrapper dict."""
    if isinstance(raw, list):
        return [c for c in raw if isinstance(c, dict)]
    if isinstance(raw, dict):
        for key in ("candidates", "knobs", "knob_table", "points"):
            if isinstance(raw.get(key), list):
                return [c for c in raw[key] if isinstance(c, dict)]
        # A single candidate dict is also acceptable.
        if any(k in raw for k in
               ("parallelism", "frequency_mhz", "freq_mhz", "units",
                "area_units", "name")):
            return [raw]
    return []


def run(raw: Any) -> Dict[str, Any]:
    """Core entry: raw parsed JSON -> result dict. Pure, deterministic."""
    specs = _load_candidates(raw)
    if not specs:
        return {
            "status": "MISSING",
            "reason": "no candidates found in input",
            "candidates": [],
            "pareto_frontier": [],
        }

    cands = [evaluate(s, i) for i, s in enumerate(specs)]
    frontier = pareto_filter(cands)

    return {
        "status": "OK",
        "objectives": dict(OBJECTIVES),
        "num_candidates": len(cands),
        "num_pareto": len(frontier),
        "candidates": [asdict(c) for c in cands],
        "pareto_frontier": [c.name for c in frontier],
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Deterministic micro-arch DSE: 4 PPA formulas + Pareto "
                    "dominance filter.")
    parser.add_argument(
        "input", nargs="?", default="-",
        help="Knob-table JSON file ('-' or omitted = read stdin)")
    parser.add_argument("--json", default=None, help="Output JSON report path")
    args = parser.parse_args(argv)

    # Load input, degrading gracefully on any read/parse failure.
    try:
        if args.input in ("-", None):
            text = sys.stdin.read()
        else:
            text = Path(args.input).read_text()
        raw = json.loads(text)
    except (OSError, json.JSONDecodeError) as exc:
        report = {
            "status": "MISSING",
            "reason": f"could not read/parse input: {exc}",
            "candidates": [],
            "pareto_frontier": [],
        }
        out = json.dumps(report, indent=2, ensure_ascii=False)
        if args.json:
            Path(args.json).parent.mkdir(parents=True, exist_ok=True)
            Path(args.json).write_text(out)
        print(out)
        return 2

    report = run(raw)
    out = json.dumps(report, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out)
    print(out)
    return 0 if report["status"] == "OK" else 2


if __name__ == "__main__":
    sys.exit(main())
