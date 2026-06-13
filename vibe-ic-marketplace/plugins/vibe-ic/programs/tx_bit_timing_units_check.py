#!/usr/bin/env python3
"""
tx_bit_timing_units_check.py — verify TX bit-cell constants in
rtl/**/tx_phy*.{v,sv} match L8/L11 microsecond targets at the
clock the TX_PHY is actually bound to.

Why this gate exists
====================
Surfaced by the v0.119.29 ROOT_CAUSE_ANALYSIS Area 1 (<benchmark> fresh
agent vs vendor). Fresh agent declared TX bit-cell constants in
clock-cycle units (LOW0/HIGH0/LOW1/HIGH1/IBT) at one clock domain
while the spec µs targets are defined against another. Result: total
bit period is right by accident but per-bit LOW/HIGH ratio is wrong
and the host receiver's pulse-width classifier mis-classifies bit-0
vs bit-1 boundaries.

Concrete fingerprint (chip-agnostic): if rtl declares
    localparam TX_BIT0_LOW = 36;       // expected 6.8 µs
and the actual clock bound to TX_PHY is 5 MHz (period 0.2 µs), then
36 * 0.2 = 7.2 µs — outside the ±5% tolerance band of 6.8 µs (band
6.46..7.14). FAIL.

The fix is one of:
  - regenerate rtl_constants_gen with the correct clock frequency
  - rebind TX_PHY in L9 clock_binding to the doc-specified clock
  - declare an explicit waiver if asymmetric IBT semantics differ
    intentionally on this chip

Rule
----
For each TX bit-cell parameter declared in rtl/**/tx_phy*.{v,sv}:
  LOW0 / HIGH0 / LOW1 / HIGH1 / IBT_AFTER_0 / IBT_AFTER_1 / IBT
assert  cyc / clk_hz * 1e6  ∈  [ spec_us * 0.95 , spec_us * 1.05 ].

spec_us is looked up from L8_RTL_CONSTANTS.json or
L11_CALIBRATION.json by name fragment (case-insensitive). clk_hz is
looked up from L8_RTL_CONSTANTS.json `tx_clock_hz` or
`clock_domain_hz` or 1e9 / `clock_period_ns`. If L9
`clock_binding.tx_phy` is present, that name is resolved against L8
clocks first.

Skips silently when:
  - no rtl/**/tx_phy*.{v,sv} present
  - L8 / L11 absent
  - no spec_us entry for any of the constants
  - no resolvable TX clock

Honors waivers.json key `tx_bit_timing_units_alternative`
(≥20-char rationale) for chips that intentionally tune outside ±5%.

Usage
-----
python3 tx_bit_timing_units_check.py <project_dir>

Returns 0 on PASS / silent-skip / waived, 1 on FAIL.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
import _path_layout as _pl


# Constant-name fragments to scan for in rtl/tx_phy*. The matched
# rtl param maps to the *_us spec name fragment by the table below.
# Order is significant: longer / more-specific first so e.g. IBT_AFTER_0
# wins over IBT.
TX_TIMING_KEYS = (
    # rtl-name-fragment, spec-us-fragment-list (any match)
    ("IBT_AFTER_0", ("ibt_after_0", "ibt_after0")),
    ("IBT_AFTER_1", ("ibt_after_1", "ibt_after1")),
    ("BIT0_LOW",    ("bit0_low", "low0", "tx_bit0_low")),
    ("BIT0_HIGH",   ("bit0_high", "high0", "tx_bit0_high")),
    ("BIT1_LOW",    ("bit1_low", "low1", "tx_bit1_low")),
    ("BIT1_HIGH",   ("bit1_high", "high1", "tx_bit1_high")),
    # Generic IBT only matched when no after_0 / after_1 distinction.
    ("IBT",         ("ibt", "tx_ibt", "inter_byte")),
)


def _strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    src = re.sub(r"//[^\n]*", "", src)
    return src


def _find_tx_phy_files(project: Path) -> list[Path]:
    out: list[Path] = []
    for root in (_pl.rtl_dir(project), project / "src", project / "hdl"):
        if not root.is_dir():
            continue
        for ext in ("*.v", "*.sv"):
            for p in root.rglob(ext):
                if "tx_phy" in p.name.lower():
                    out.append(p)
    return sorted(set(out))


def _parse_localparams(src: str) -> dict[str, int]:
    """Extract every `localparam [type?] NAME = INT;` assignment.
    Returns {NAME_UPPER: int_value}. Hex / decimal / sized literals
    accepted."""
    src = _strip_comments(src)
    out: dict[str, int] = {}
    pat = re.compile(
        r"localparam\s+"
        r"(?:(?:int|integer|byte|shortint|longint|logic\s*\[\d+:\d+\]|"
        r"reg\s*\[\d+:\d+\]|bit\s*\[\d+:\d+\])\s+)?"
        r"(\w+)\s*=\s*([^;]+);",
        re.IGNORECASE,
    )
    for m in pat.finditer(src):
        name = m.group(1).upper()
        raw = m.group(2).strip()
        val = _parse_int(raw)
        if val is not None:
            out[name] = val
    return out


def _parse_int(raw: str) -> int | None:
    raw = raw.strip()
    # sized literal e.g. 5'b1_1001 / 6'h2A / 8'd17
    m = re.match(r"\d+'\s*([bdho])\s*([0-9a-f_]+)", raw, re.IGNORECASE)
    if m:
        base = {"b": 2, "d": 10, "o": 8, "h": 16}[m.group(1).lower()]
        digits = m.group(2).replace("_", "")
        try:
            return int(digits, base)
        except ValueError:
            return None
    # hex 0xNN
    m = re.match(r"0[xX]([0-9a-fA-F_]+)$", raw)
    if m:
        try:
            return int(m.group(1).replace("_", ""), 16)
        except ValueError:
            return None
    # plain decimal (allow underscores)
    m = re.match(r"-?[\d_]+$", raw)
    if m:
        try:
            return int(raw.replace("_", ""))
        except ValueError:
            return None
    return None


def _load_json(p: Path) -> dict:
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _find_l_jsons(project: Path) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for base in (project, _pl.generated_docs_dir(project)):
        if not base.exists():
            continue
        for p in base.glob("L*.json"):
            out.setdefault(p.name, p)
    return out


def _walk_find_us(node, fragments: tuple[str, ...]) -> float | None:
    """Walk a JSON tree looking for a spec µs value matching any of
    `fragments`. Two schemas accepted:
      (a) record form: dict with `name` matching a fragment AND a
          numeric `physical_value_us`/`value_us`/`us`/`spec_us` field.
      (b) flat form: dict key whose lowercased form ENDS in `_us` AND
          contains a fragment, with a numeric / [min,max] / {min,max}
          value (returns the midpoint of a range so ±5% is symmetric).
    """
    fr = tuple(f.lower() for f in fragments)
    if isinstance(node, dict):
        nm = str(node.get("name", "")).lower()
        if nm and any(f in nm for f in fr):
            for fld in ("physical_value_us", "value_us", "spec_us",
                        "us", "value"):
                v = node.get(fld)
                if isinstance(v, (int, float)):
                    return float(v)
        for k, v in node.items():
            if isinstance(k, str) and k.lower().endswith("_us") and \
               any(f in k.lower() for f in fr):
                if isinstance(v, (int, float)):
                    return float(v)
                if isinstance(v, list) and len(v) == 2 and \
                   all(isinstance(x, (int, float)) for x in v):
                    return (float(v[0]) + float(v[1])) / 2.0
                if isinstance(v, dict) and isinstance(v.get("min"),
                                                     (int, float)) and \
                   isinstance(v.get("max"), (int, float)):
                    return (float(v["min"]) + float(v["max"])) / 2.0
        for v in node.values():
            r = _walk_find_us(v, fragments)
            if r is not None:
                return r
    elif isinstance(node, list):
        for item in node:
            r = _walk_find_us(item, fragments)
            if r is not None:
                return r
    return None


def _resolve_tx_clock_hz(l8: dict, l9: dict) -> float | None:
    """Pick the clock frequency bound to TX_PHY.

    Priority:
      1. L9 `clock_binding.tx_phy` resolved against L8 clock table.
      2. L8 `tx_clock_hz`.
      3. L8 `clock_domain_hz`.
      4. L8 `clock_period_ns` → 1e9 / period.
      5. L8 `clock_hz` (last-resort generic single clock).
    """
    binding = None
    if isinstance(l9, dict):
        cb = l9.get("clock_binding") or l9.get("clock_bindings")
        if isinstance(cb, dict):
            for key in ("tx_phy", "TX_PHY", "tx", "tx_phy_clock"):
                if key in cb and isinstance(cb[key], str):
                    binding = cb[key]
                    break
    if binding and isinstance(l8, dict):
        clocks = l8.get("clocks") or l8.get("clock_table") or {}
        if isinstance(clocks, dict):
            entry = clocks.get(binding)
            if isinstance(entry, dict):
                hz = entry.get("hz") or entry.get("frequency_hz")
                if isinstance(hz, (int, float)):
                    return float(hz)
                period_ns = entry.get("period_ns")
                if isinstance(period_ns, (int, float)) and period_ns > 0:
                    return 1e9 / float(period_ns)
        # try walking l8 generally for a key named like the binding
        v = _walk_find_hz_named(l8, binding)
        if v is not None:
            return v

    if isinstance(l8, dict):
        for k in ("tx_clock_hz", "clock_domain_hz", "clock_hz"):
            v = l8.get(k)
            if isinstance(v, (int, float)) and v > 0:
                return float(v)
        v = l8.get("clock_period_ns")
        if isinstance(v, (int, float)) and v > 0:
            return 1e9 / float(v)
    return None


def _walk_find_hz_named(node, name: str) -> float | None:
    target = name.lower()
    if isinstance(node, dict):
        if str(node.get("name", "")).lower() == target:
            for fld in ("hz", "frequency_hz", "freq_hz"):
                v = node.get(fld)
                if isinstance(v, (int, float)):
                    return float(v)
            v = node.get("period_ns")
            if isinstance(v, (int, float)) and v > 0:
                return 1e9 / float(v)
        for k, v in node.items():
            if isinstance(k, str) and k.lower() == target:
                if isinstance(v, (int, float)) and v > 0:
                    # bare number — assume Hz
                    return float(v)
            r = _walk_find_hz_named(v, name)
            if r is not None:
                return r
    elif isinstance(node, list):
        for item in node:
            r = _walk_find_hz_named(item, name)
            if r is not None:
                return r
    return None


def _waived(project: Path) -> bool:
    waivers = project / "waivers.json"
    if not waivers.exists():
        return False
    try:
        d = json.loads(waivers.read_text())
        v = d.get("tx_bit_timing_units_alternative", "")
        return isinstance(v, str) and len(v.strip()) >= 20
    except Exception:
        return False


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: tx_bit_timing_units_check.py <project_dir>")
        return 2
    project = Path(sys.argv[1]).resolve()
    if not project.is_dir():
        print(f"FAIL — not a directory: {project}")
        return 1

    files = _find_tx_phy_files(project)
    if not files:
        print("PASS — no rtl/**/tx_phy*.{v,sv} present (gate not "
              "applicable)")
        return 0

    l_jsons = _find_l_jsons(project)
    l8 = _load_json(l_jsons.get("L8_RTL_CONSTANTS.json", Path()))
    l11 = _load_json(l_jsons.get("L11_CALIBRATION.json", Path()))
    l9 = _load_json(l_jsons.get("L9_INTEGRATION_SPEC.json", Path()))
    # Some projects drop L11 in different file layouts; fall back to L2.
    l2 = _load_json(l_jsons.get("L2_FRS.json", Path()))

    if not (l8 or l11):
        print("PASS — L8/L11 absent; cannot compare to spec µs (gate "
              "skipped)")
        return 0

    clk_hz = _resolve_tx_clock_hz(l8, l9)
    if clk_hz is None or clk_hz <= 0:
        print("PASS — no resolvable TX clock in L8/L9 (gate skipped)")
        return 0

    # Collect every localparam from every tx_phy file.
    all_params: dict[str, int] = {}
    for f in files:
        try:
            src = f.read_text()
        except Exception:
            continue
        all_params.update(_parse_localparams(src))

    if not all_params:
        print("PASS — no TX-timing localparams found in rtl/tx_phy "
              "(gate not applicable)")
        return 0

    # For each TX_TIMING_KEY, find the matching localparam and the
    # spec µs. If a generic IBT is present alongside IBT_AFTER_0 /
    # IBT_AFTER_1, ignore the generic one (covered by the asymmetric
    # variants).
    has_after_0 = any("IBT_AFTER_0" in n for n in all_params)
    has_after_1 = any("IBT_AFTER_1" in n for n in all_params)

    checks: list[tuple[str, int, float, float]] = []  # (param, cyc, actual_us, spec_us)
    skipped: list[str] = []
    for fragment, spec_frags in TX_TIMING_KEYS:
        if fragment == "IBT" and (has_after_0 or has_after_1):
            continue
        # Find matching rtl param (case-insensitive, fragment substring).
        match_name = None
        match_cyc = None
        for name, cyc in all_params.items():
            up = name.upper()
            if fragment in up:
                match_name = name
                match_cyc = cyc
                break
        if match_name is None:
            continue
        spec_us = (_walk_find_us(l8, spec_frags) or
                   _walk_find_us(l11, spec_frags) or
                   _walk_find_us(l2, spec_frags))
        if spec_us is None:
            skipped.append(f"{match_name} (no spec_us in L8/L11/L2)")
            continue
        actual_us = match_cyc / clk_hz * 1e6
        checks.append((match_name, match_cyc, actual_us, spec_us))

    if not checks:
        print("PASS — no TX-timing param/spec pair could be matched "
              "(gate skipped)")
        for s in skipped:
            print(f"  • skipped: {s}")
        return 0

    fails: list[tuple[str, int, float, float, float, float]] = []
    for name, cyc, actual_us, spec_us in checks:
        lo = spec_us * 0.95
        hi = spec_us * 1.05
        if not (lo <= actual_us <= hi):
            fails.append((name, cyc, actual_us, spec_us, lo, hi))

    if not fails:
        print(f"PASS — all {len(checks)} TX bit-timing constant(s) "
              f"within ±5%% of spec µs at TX clock = {clk_hz/1e6:.3f} MHz")
        for name, cyc, actual_us, spec_us in checks:
            print(f"  • {name} = {cyc} cyc → {actual_us:.3f} µs "
                  f"(spec {spec_us:.3f} µs)")
        return 0

    if _waived(project):
        print(f"PASS_WITH_WAIVER — {len(fails)} TX bit-timing "
              "constant(s) outside ±5%% but waiver is set")
        for name, cyc, actual_us, spec_us, lo, hi in fails:
            print(f"  • {name} = {cyc} cyc → {actual_us:.3f} µs "
                  f"(spec {spec_us:.3f} µs, band {lo:.3f}..{hi:.3f})")
        return 0

    print(f"FAIL — {len(fails)} TX bit-timing constant(s) outside ±5%% "
          f"of spec µs at TX clock = {clk_hz/1e6:.3f} MHz:")
    for name, cyc, actual_us, spec_us, lo, hi in fails:
        print(f"  • {name} = {cyc} cyc → {actual_us:.3f} µs "
              f"(spec {spec_us:.3f} µs, band {lo:.3f}..{hi:.3f})")
    print()
    print("Why this matters:")
    print("  Total bit period can be right by accident even when the")
    print("  per-bit LOW/HIGH ratio is wrong; the host's pulse-width")
    print("  classifier mis-categorises bit-0 vs bit-1 boundaries and")
    print("  the resulting CRC fails silently. This is the per-bit")
    print("  fingerprint of TX_PHY bound to the wrong clock domain.")
    print()
    print("Fix: regenerate L8 with the correct TX clock, OR rebind")
    print("  TX_PHY in L9.clock_binding to the doc-specified clock,")
    print("  OR declare an exception in waivers.json (≥20 chars):")
    print('    {"tx_bit_timing_units_alternative": "<reason>"}')
    return 1


if __name__ == "__main__":
    sys.exit(main())
