#!/usr/bin/env python3
"""
tx_bit_width_min_resolution_check.py — advisory gate that flags when the
chip's TX bit-clock granularity is too coarse for the smallest L2 timing
parameter the chip must place edges at.

Why this gate exists
====================
A common Category-C residual (sub-microsecond pad / silicon detail not
visible to LL-* structural gates): the chip's RTL drives the bus pin
from a counter that ticks at the system clock period T_tx_ns. Every
TX edge (rising and falling) snaps to a multiple of T_tx_ns. The
host controller's analog front-end may decode a bit by integrating
the drive over a window narrower than 2 * T_tx_ns, causing a
deterministic FAIL even when the average pulse width is correct.

The rule of thumb: for every L2 timing parameter with a tolerance
window dT, the chip's TX clock period must be small enough that the
worst-case edge-snapping error (T_tx_ns / 2) consumes at most a
configurable fraction of dT (default safety_factor=4 → at most 25%).

Concrete failure mode (caught by v0.119.20 vendor benchmark, hypothesis
not yet oracle-confirmed): chip clocked at 5 MHz (T_tx_ns=200) drives
an AID-bus where the tightest BIT_LOW pulse is ~8 us with a ±0.5 us
host tolerance. Edge-snap error 100 ns = 0.1 us = 20% of the budget,
borderline but adequate. At 2.5 MHz (T_tx_ns=400) the error becomes
0.2 us = 40% — the gate would WARN. At 1 MHz (T_tx_ns=1000) it's
1.0 us = 200% — clear FAIL.

This is GENERAL — protocol-agnostic, chip-agnostic. Triggered only
when both L2 timing parameters AND the chip's TX clock period are
explicitly declared in the project. Silent-skip otherwise.

Rule
----
Let T_tx_ns be the chip's TX-side clock period. For every L2 timing
parameter that has both a min and max value (i.e. defines a tolerance
window), let `dT_us = (max - min)`. Then:

    T_tx_ns / 1000 <= dT_us / safety_factor    (default safety_factor=4)

A WARN is emitted when 4 < ratio <= 10 (advisory),
a FAIL when ratio > 10.

Where T_tx_ns comes from (in priority order)
--------------------------------------------
1. L9_INTEGRATION.json `tx_clk_ns` / `tx_clk_period_ns` /
   `bit_clk_period_ns` — chip-agnostic field names L9 should expose.
2. L9_INTEGRATION.json `clk_freq_mhz` — derived as 1000 / freq.
3. RTL constants file (rtl/*.sv / *.svh / *_pkg.sv) — parameter
   declaration of the form `parameter TX_CLK_NS = <int>;` or
   `localparam BIT_CLK_NS = <int>;` (case-insensitive).

Where dT_us comes from
----------------------
1. L2_FRS.json / L2_TIMING_WAVEFORM.json — any key matching
   `_us` / `_ms` / `_ns` suffix whose value is `[min, max]` or
   `{"min":..., "max":...}`.

Usage
-----
python3 tx_bit_width_min_resolution_check.py <project_dir>
python3 tx_bit_width_min_resolution_check.py <project_dir> \\
    --safety-factor 4 --warn-factor 10

Honors waivers.json key "tx_bit_width_resolution_intentional".

Exit codes:
    0 = PASS or silent-skip or WARN (advisory)
    1 = FAIL (T_tx_ns >> tolerance, real risk)
    2 = IO / parse error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional
import _path_layout as _pl


def find_doc(project_dir: Path, name: str) -> Optional[Path]:
    for base in (project_dir, project_dir / "phase1/generated_docs", _pl.generated_docs_dir(project_dir)):
        p = base / name
        if p.exists():
            return p
    return None


def extract_tx_clk_ns(project_dir: Path) -> tuple[Optional[float], str]:
    """Return (period_in_ns, source_description) or (None, why)."""
    # 1. L8 / L9 explicit fields. v0.119.27: L8_RTL_CONSTANTS.json has
    # been the de-facto home for clock_period_ns / clock_domain_hz in
    # several real projects, but the gate previously only searched L9.
    # That made it silently skip valid setups.
    for name in ("L9_INTEGRATION.json", "L9_INTEGRATION_SPEC.json",
                 "L8_RTL_CONSTANTS.json"):
        p = find_doc(project_dir, name)
        if not p:
            continue
        try:
            d = json.loads(p.read_text())
        except Exception:
            continue
        # v0.119.28: collect ALL period-equivalent declarations in this
        # doc and verify they agree to within 1%. Two clock-source keys
        # disagreeing by more than 1% (e.g. `clock_period_ns: 20` AND
        # `clock_domain_hz: 1e6` → period 1000ns) is almost certainly a
        # spec bug; print a WARN line so the user notices instead of
        # the gate silently picking the first hit. The first declaration
        # in the search order still wins as the returned period.
        candidates: list = []  # (period_ns, source_str)
        for k in ("tx_clk_ns", "tx_clk_period_ns",
                  "bit_clk_period_ns", "tx_period_ns",
                  "clock_period_ns", "clk_period_ns"):
            v = d.get(k)
            if isinstance(v, (int, float)) and v > 0:
                candidates.append((float(v), f"{name}.{k}={v}"))
        v = d.get("clk_freq_mhz")
        if isinstance(v, (int, float)) and v > 0:
            candidates.append((1000.0 / v,
                               f"{name}.clk_freq_mhz={v} → {1000.0/v:.1f}ns"))
        for k in ("clock_domain_hz", "clk_freq_hz", "core_clock_hz"):
            v = d.get(k)
            if isinstance(v, (int, float)) and v > 0:
                period_ns = 1e9 / v
                candidates.append((period_ns,
                                   f"{name}.{k}={v:g}Hz → {period_ns:.1f}ns"))
        if candidates:
            base_ns, base_src = candidates[0]
            for ns, src in candidates[1:]:
                # Relative tolerance 1% — picks up gross misconfig
                # (factor-of-2/5/10/1000 errors) without false-WARN on
                # round-trip floating-point representation noise.
                if abs(ns - base_ns) / base_ns > 0.01:
                    print(
                        f"WARN — clock-source disagreement in {name}: "
                        f"'{base_src}' vs '{src}' "
                        f"differ by {abs(ns - base_ns) / base_ns * 100:.1f}% "
                        f"(>1% threshold). Using {base_src}.",
                        file=sys.stderr,
                    )
            return base_ns, base_src

    # 2. RTL parameter declarations
    rtl = _pl.rtl_dir(project_dir)
    if rtl.exists():
        pat = re.compile(
            r"\b(?:parameter|localparam)\s+"
            # Optional SV type (int, integer, real, logic, bit, byte) —
            # also handle bare-vector form `[15:0]`. Both can appear.
            r"(?:(?:int|integer|real|logic|bit|byte|reg)\s+)?"
            r"(?:\[[^\]]+\]\s+)?"
            r"(TX_CLK_NS|BIT_CLK_NS|TX_PERIOD_NS|"
            r"TX_CLK_PERIOD_NS|CLK_PERIOD_NS|CLK_NS)\s*=\s*"
            r"(\d+)",
            re.IGNORECASE,
        )
        for f in sorted(list(rtl.glob("*.sv")) + list(rtl.glob("*.v"))
                        + list(rtl.glob("*.svh"))):
            try:
                src = f.read_text()
            except Exception:
                continue
            m = pat.search(src)
            if m:
                return float(m.group(2)), \
                    f"{f.name}:{m.group(1)}={m.group(2)}"

    return None, "no L9 tx_clk and no RTL parameter found"


_SUFFIX_TO_US = {
    "us": 1.0, "ms": 1000.0, "ns": 1.0 / 1000.0, "ps": 1.0 / 1_000_000.0,
}


def _parse_tolerance_us(value, key: str) -> Optional[float]:
    """Return the (max - min) in microseconds, or None if value isn't a
    range. Single-value entries have no tolerance and are skipped."""
    suffix_match = re.search(r"_(us|ms|ns|ps)$", key, re.IGNORECASE)
    if not suffix_match:
        return None
    factor = _SUFFIX_TO_US[suffix_match.group(1).lower()]
    lo = hi = None
    if isinstance(value, list) and len(value) == 2 and \
       all(isinstance(x, (int, float)) for x in value):
        lo, hi = value
    elif isinstance(value, dict):
        lo, hi = value.get("min"), value.get("max")
    if lo is None or hi is None:
        return None
    if not (isinstance(lo, (int, float)) and isinstance(hi, (int, float))):
        return None
    return abs(hi - lo) * factor


def collect_tolerances(project_dir: Path) -> list[tuple[str, float]]:
    """Walk L2 docs; return [(key, dT_us)] for every tolerance-bearing entry."""
    out: list[tuple[str, float]] = []
    for name in ("L2_FRS.json", "L2_TIMING_WAVEFORM.json"):
        p = find_doc(project_dir, name)
        if not p:
            continue
        try:
            d = json.loads(p.read_text())
        except Exception:
            continue
        _walk(d, out)
    return out


def _walk(node, out, prefix=""):
    if isinstance(node, dict):
        for k, v in node.items():
            full = f"{prefix}.{k}" if prefix else k
            tol = _parse_tolerance_us(v, k)
            if tol is not None and tol > 0:
                out.append((full, tol))
            elif isinstance(v, (dict, list)):
                _walk(v, out, full)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            _walk(item, out, f"{prefix}[{i}]")


def waived(project_dir: Path) -> bool:
    waivers = project_dir / "waivers.json"
    if not waivers.exists():
        return False
    try:
        d = json.loads(waivers.read_text())
        return bool(d.get("tx_bit_width_resolution_intentional"))
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--safety-factor", type=float, default=4.0,
                    help="Edge-snap error must be at most dT/N (default 4)")
    ap.add_argument("--warn-factor", type=float, default=10.0,
                    help="WARN if N < ratio <= warn-factor; FAIL if > (default 10)")
    args = ap.parse_args()

    project = args.project_dir.resolve()
    if not project.is_dir():
        print(f"FAIL — not a directory: {project}", file=sys.stderr)
        sys.exit(2)

    tx_ns, tx_src = extract_tx_clk_ns(project)
    tolerances = collect_tolerances(project)

    if tx_ns is None:
        print(f"PASS — chip TX clock period not declared (gate skipped). "
              f"Reason: {tx_src}")
        sys.exit(0)
    if not tolerances:
        print(f"PASS — no L2 timing tolerance windows declared "
              f"(gate skipped). TX clock = {tx_ns:.1f}ns from {tx_src}.")
        sys.exit(0)

    # Edge-snap worst case error in us
    edge_err_us = tx_ns / 2.0 / 1000.0

    warns = []
    fails = []
    for key, dT_us in tolerances:
        ratio = edge_err_us / (dT_us / args.safety_factor) \
            if dT_us > 0 else float("inf")
        if ratio > args.warn_factor:
            fails.append((key, dT_us, ratio))
        elif ratio > 1.0:
            warns.append((key, dT_us, ratio))

    if not warns and not fails:
        print(f"PASS — TX clock {tx_ns:.1f}ns ({tx_src}) is fine for all "
              f"{len(tolerances)} L2 tolerance window(s) at safety factor "
              f"{args.safety_factor:g}.")
        sys.exit(0)

    if waived(project):
        print(f"PASS_WITH_WAIVER — {len(warns)+len(fails)} tolerance(s) "
              "borderline/exceeded but waived.")
        sys.exit(0)

    if fails:
        print(f"FAIL — TX clock {tx_ns:.1f}ns ({tx_src}) is too coarse "
              f"for {len(fails)} L2 tolerance window(s):")
        for k, dT, r in fails[:10]:
            print(f"  • {k}: tolerance {dT:.3f}us, edge-snap error "
                  f"{edge_err_us:.3f}us, ratio={r:.1f}× allowed")
        if warns:
            print(f"  ... plus {len(warns)} WARN-level entries")
        print()
        print("Why this matters:")
        print("  At T_tx_ns granularity, chip can only place TX edges at")
        print("  multiples of T_tx_ns/2 us. For tolerance windows tighter")
        print("  than the safety factor allows, the host's analog decoder")
        print("  sees the deterministic edge-snap as a bit-time error and")
        print("  rejects the frame — the structural gates can't catch this")
        print("  because the AVERAGE pulse widths are still correct.")
        print()
        print("Fix options:")
        print("  1. Increase chip clock frequency (smaller T_tx_ns).")
        print("  2. Use a fractional TX divider clocked from a faster PLL.")
        print("  3. Document an oracle-validated exception in waivers.json:")
        print('     {"tx_bit_width_resolution_intentional": "<reason>"}')
        sys.exit(1)

    # WARN-only path: advisory, exit 0
    print(f"WARN — TX clock {tx_ns:.1f}ns ({tx_src}) is borderline for "
          f"{len(warns)} L2 tolerance window(s) (safety factor "
          f"{args.safety_factor:g}, warn at {args.warn_factor:g}x):")
    for k, dT, r in warns[:10]:
        print(f"  • {k}: tolerance {dT:.3f}us, edge-snap "
              f"{edge_err_us:.3f}us, ratio={r:.1f}× allowed")
    print()
    print("Advisory: not a hard FAIL. Verify against oracle if available, "
          "otherwise increase TX clock frequency to add margin.")
    sys.exit(0)


if __name__ == "__main__":
    main()
