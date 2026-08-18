#!/usr/bin/env python3
"""
sta_achievable_fmax_report.py — honest achievable-Fmax measurement (Step 23 STA).

Scope (be honest about it)
--------------------------
When a design's post-route STA FAILS the spec-target clock period, the residual
is often a genuine spec-vs-technology timing-closure workload (a full CPU / crypto
round at a slow OSS PDK) — NOT a fabricated floor and NOT a masking bug. For that
class the honest engineering answer is to REPORT the design's achievable Fmax
alongside the (still-FAIL) spec-target verdict, exactly as the sha256 canonical IC
was reported at its depth-autoscaled 25.9 ns. Before this program that report was
produced by hand (sha256) or omitted entirely (ibex was left as a bare 10 ns FAIL
with no achievable-Fmax datapoint), so the honest Category-H conclusion was not
automatic.

This program makes it deterministic and general.

⚠️ HONESTY BOUNDARY (this is a MEASUREMENT, not a relaxation — §4.05)
--------------------------------------------------------------------
This program NEVER modifies an SDC, NEVER relaxes a clock, and NEVER claims the
spec target passed. `spec_met` is True ONLY when the ACTUAL spec-target worst
setup slack is >= 0. The achievable Fmax is emitted as a SEPARATE honest datapoint
that ALWAYS travels with the spec-target verdict (which stays FAIL when slack < 0).
Relaxing the sign-off SDC to make STA "pass" against the original spec is the
`phase3_one_shot_runner` anti-relax footgun this program is careful NOT to be.

The exact computation (why no sweep is needed)
----------------------------------------------
For a reg->reg setup path the launch/capture clock-network delays and the data
arrival are all PERIOD-INDEPENDENT (a propagated clock's capture edge is
`period + network_delay`), so the worst setup slack is EXACTLY LINEAR in the clock
period:

    slack(P) = slack(P_spec) + (P - P_spec)

Setting slack(P)=0 gives the minimum period at which setup MEETs:

    achievable_period = P_spec - worst_setup_slack_at_spec

(verified empirically on ibex_top at sky130: worst slack -2.64 ns @ 10 ns ->
achievable 12.64 ns; a re-STA at 13 ns measured +0.36 ns, i.e. 13 - 12.64,
perfectly linear). The value is the achievable period for the CURRENT worst path;
if a second path is within the reported `margin_note` ns it may govern instead, so
`emit_verification_sweep_tcl` optionally produces an OpenROAD period sweep to
confirm the single-point number the same way the ibex close-loop did.

Chip-AGNOSTIC / benchmark-AGNOSTIC: operates on a spec period + a measured worst
setup slack (or the STA report / SDC they live in). No chip/PDK/benchmark literal.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional


# ── report / SDC parsing ────────────────────────────────────────────────────

# `report_worst_slack -max` -> "worst slack max -2.64"
_WORST_SLACK_RE = re.compile(
    r"worst\s+slack\s+max\s+(-?\d+(?:\.\d+)?)", re.IGNORECASE
)
# `report_checks` path tail -> "        -21.89   slack (VIOLATED)" / "3.34   slack (MET)"
_PATH_SLACK_RE = re.compile(
    r"^\s*(-?\d+(?:\.\d+)?)\s+slack\s+\((?:VIOLATED|MET)\)", re.IGNORECASE | re.MULTILINE
)
# `create_clock -name clk -period 10.0 [get_ports clk_i]` (also `-period 10`)
_CREATE_CLOCK_PERIOD_RE = re.compile(
    r"create_clock\b[^\n]*?-period\s+(\d+(?:\.\d+)?)", re.IGNORECASE
)
# SDC written by a `set clk_period 10.0` idiom then `create_clock ... $clk_period`
_SET_PERIOD_RE = re.compile(
    r"set\s+clk_period\s+(\d+(?:\.\d+)?)", re.IGNORECASE
)


def parse_worst_setup_slack(sta_text: str) -> Optional[float]:
    """Extract the worst (most-negative) setup slack from an STA report.

    Prefers the explicit ``report_worst_slack -max`` line; falls back to the
    most-negative ``report_checks`` path-tail slack. Returns None if neither is
    present (an empty/absent report -> honest None, never a fabricated 0).
    """
    slacks = [float(m) for m in _WORST_SLACK_RE.findall(sta_text)]
    slacks += [float(m) for m in _PATH_SLACK_RE.findall(sta_text)]
    if not slacks:
        return None
    return min(slacks)


def parse_spec_period_ns(sdc_text: str) -> Optional[float]:
    """Extract the spec clock period (ns) from SDC text.

    Reads a literal ``create_clock -period`` first; if the period is carried via
    a ``set clk_period`` variable (the wrapper-core convention) use that.
    """
    m = _CREATE_CLOCK_PERIOD_RE.search(sdc_text)
    if m:
        return float(m.group(1))
    m = _SET_PERIOD_RE.search(sdc_text)
    if m:
        return float(m.group(1))
    return None


# ── the deterministic core ──────────────────────────────────────────────────

def achievable_from_slack(
    spec_period_ns: float, worst_setup_slack_ns: float
) -> dict:
    """Compute the honest achievable-Fmax report from a spec period + the STA
    worst setup slack measured AT that period.

    Returns a dict with the spec-target verdict (unrelaxed) AND the achievable
    Fmax datapoint. `spec_met` reflects the REAL spec-target slack only.
    """
    if spec_period_ns is None or spec_period_ns <= 0:
        raise ValueError("spec_period_ns must be a positive number")
    achievable_period = spec_period_ns - worst_setup_slack_ns
    spec_met = worst_setup_slack_ns >= 0.0
    spec_fmax = 1000.0 / spec_period_ns
    achievable_fmax = (
        1000.0 / achievable_period if achievable_period > 0 else None
    )
    return {
        "spec_period_ns": round(spec_period_ns, 4),
        "spec_fmax_mhz": round(spec_fmax, 3),
        "worst_setup_slack_ns": round(worst_setup_slack_ns, 4),
        "spec_met": spec_met,
        # honest achievable datapoint — measured, NOT a relaxation of the spec
        "achievable_period_ns": round(achievable_period, 4),
        "achievable_fmax_mhz": (
            round(achievable_fmax, 3) if achievable_fmax is not None else None
        ),
        # when the spec already MET, "achievable == spec + margin"; the margin is
        # exactly the positive slack, so the design has headroom, not a shortfall
        "spec_margin_ns": round(worst_setup_slack_ns, 4) if spec_met else None,
        "relaxation_applied": False,  # INVARIANT: this program never relaxes SDC
    }


def format_human(rep: dict) -> str:
    """One-block human summary that always states the spec verdict first."""
    spec_verdict = "MET" if rep["spec_met"] else "FAIL"
    lines = [
        f"SPEC TARGET : {rep['spec_period_ns']:.2f} ns "
        f"({rep['spec_fmax_mhz']:.1f} MHz) -> worst setup slack "
        f"{rep['worst_setup_slack_ns']:+.2f} ns : {spec_verdict}",
    ]
    if rep["spec_met"]:
        lines.append(
            f"HEADROOM    : +{rep['spec_margin_ns']:.2f} ns "
            f"(design meets spec with margin)"
        )
    else:
        af = rep["achievable_fmax_mhz"]
        af_s = f"{af:.1f} MHz" if af is not None else "n/a"
        lines.append(
            f"ACHIEVABLE  : {rep['achievable_period_ns']:.2f} ns "
            f"({af_s}) : setup MET at this period"
        )
        lines.append(
            "NOTE        : measured Fmax datapoint, NOT a waiver — the "
            "spec-target verdict stays FAIL and the sign-off SDC is unchanged."
        )
    return "\n".join(lines)


def emit_verification_sweep_tcl(
    lef_tech: str,
    lef_cells: str,
    liberty: str,
    routed_def: str,
    clk_port: str,
    periods_ns: list[float],
    *,
    signal_layer: str = "met3",
    clock_layer: str = "met5",
) -> str:
    """Emit an OpenROAD TCL that re-measures worst setup slack at each candidate
    period on the real routed DEF, so the single-point `achievable_from_slack`
    number can be independently confirmed (the ibex close-loop did exactly this).
    Pure string builder — unit-testable without OpenROAD.
    """
    per = " ".join(f"{p:g}" for p in periods_ns)
    return (
        f"read_lef {lef_tech}\n"
        f"read_lef {lef_cells}\n"
        f"read_liberty {liberty}\n"
        f"read_def {routed_def}\n"
        f"set_wire_rc -signal -layer {signal_layer}\n"
        f"set_wire_rc -clock  -layer {clock_layer}\n"
        f"estimate_parasitics -placement\n"
        f"foreach P {{{per}}} {{\n"
        f"  create_clock -name clk -period $P [get_ports {clk_port}]\n"
        f"  set_propagated_clock [all_clocks]\n"
        f"  set ws [worst_slack -max]\n"
        f'  puts "ACHIEVABLE_SWEEP period=$P worst_setup_slack=[format %.3f $ws]"\n'
        f"}}\n"
        f"exit\n"
    )


# ── CLI ─────────────────────────────────────────────────────────────────────

def _run(args) -> int:
    if args.period is not None and args.worst_slack is not None:
        spec_period = args.period
        worst_slack = args.worst_slack
    else:
        if not args.sta_report:
            print("ERROR: provide --sta-report (and optionally --sdc), or "
                  "both --period and --worst-slack", file=sys.stderr)
            return 2
        sta_text = Path(args.sta_report).read_text(errors="replace")
        worst_slack = parse_worst_setup_slack(sta_text)
        if worst_slack is None:
            print(f"ERROR: no worst setup slack found in {args.sta_report} "
                  "(empty/absent STA report -> honest no-verdict, not a fake 0)",
                  file=sys.stderr)
            return 2
        spec_period = args.period
        if spec_period is None:
            sdc_path = args.sdc
            if not sdc_path:
                print("ERROR: --sdc (or --period) needed to resolve the spec "
                      "clock period", file=sys.stderr)
                return 2
            spec_period = parse_spec_period_ns(
                Path(sdc_path).read_text(errors="replace")
            )
            if spec_period is None:
                print(f"ERROR: no create_clock -period found in {sdc_path}",
                      file=sys.stderr)
                return 2

    rep = achievable_from_slack(spec_period, worst_slack)
    print(format_human(rep))
    if args.json:
        Path(args.json).write_text(json.dumps(rep, indent=2))
    # Exit code mirrors the SPEC-TARGET verdict (honest): 0 = spec met,
    # 1 = spec FAIL (an achievable Fmax is reported but the spec did not pass).
    return 0 if rep["spec_met"] else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Report a design's honest achievable Fmax from its post-route "
                    "STA worst setup slack (measurement, never a clock relaxation)."
    )
    ap.add_argument("--sta-report", help="path to an STA report "
                    "(report_worst_slack / report_checks output)")
    ap.add_argument("--sdc", help="path to the sign-off SDC (for the spec period)")
    ap.add_argument("--period", type=float,
                    help="spec clock period ns (overrides --sdc)")
    ap.add_argument("--worst-slack", type=float,
                    help="worst setup slack ns at the spec period "
                         "(overrides --sta-report parsing)")
    ap.add_argument("--json", help="write the structured report to this path")
    args = ap.parse_args(argv)
    return _run(args)


if __name__ == "__main__":
    raise SystemExit(main())
