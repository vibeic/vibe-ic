#!/usr/bin/env python3
"""
fpga_pad_fanout_check.py — Category-C structural gate that catches FPGA
output pins whose Combinational Fan-Out is too high.

Why this gate exists
====================
For half-duplex protocol pins (id_bus_oe, lin_bus_oe, owire_oe, ...),
the source signal feeding the FPGA pad must have a low combinational
fan-out (ideally 1). High fan-out adds capacitance to the pad-driving
LUT, slowing its edges. The host's analog bit-receiver detects the
difference even when a 100 ns/sample scope cannot.

Empirical evidence (<benchmark> v3 vs v0118-vendor oracle):
  v0118 (HW PASS): GPIO_id_bus Combinational Fan-Out = 1
                   Output Enable Source = "GPIO_id_bus~2 (inverted)"
                   (Quartus inferred a pin-local optimized LUT)
  v3    (HW FAIL): GPIO_id_bus Combinational Fan-Out = 5
                   Output Enable Source = "tx_phy:u_tx|WideNor0 (inverted)"
                   (Quartus routed the OE through deep tx_phy combinational
                    logic feeding 5 internal taps)

The fix is to reduce internal taps on the bus-OE signal, or to use the
LL-17 split data/oe wrapper pattern that lets Quartus place a pin-
local LUT.

Rule
----
This gate parses the Quartus Fitter `*.fit.rpt` for the fan-out value
on each output pin matching a half-duplex bus-pin name. If any such
pin has Combinational Fan-Out > 1, FAIL with a fix template.

If no fit.rpt exists yet, gate skips with PASS (compile hasn't run).

Usage
-----
python3 fpga_pad_fanout_check.py <project_dir>

Honors waivers.json["fpga_pad_fanout_alternative"].
Returns 0 on PASS, 1 on FAIL.
"""

import json
import re
import sys
from pathlib import Path
import _path_layout as _pl


PIN_NAME_HINTS = (
    "id_bus", "GPIO_id_bus",
    "lin_bus", "kline_bus", "owire", "1wire",
    "single_wire", "halfduplex_bus",
)


def _project_pin_hints(project_dir: Path) -> tuple:
    """v0.119.27: extend the hardcoded HALF_DUPLEX hint list with the
    aliases ONLY of pads whose canonical name matches one of the built-in
    hints (`id_bus`, `lin_bus`, `owire`, …). That keeps the gate's
    semantic ("this checks the half-duplex BUS pin only") intact —
    arbitrary pads like `KEY[0]` (reset button, naturally fan-out>1)
    are not pulled into scope just because L2 declares an alias for them.

    Two declaration paths supported (both project-driven):
      • `pad_definitions[].fpga_alias` for pads whose `name` matches a
        built-in hint
      • top-level `fpga_pin_aliases` dict whose canonical key matches a
        built-in hint
    """
    extra: list = []
    builtin_lower = tuple(h.lower() for h in PIN_NAME_HINTS)

    def _is_bus_pad_name(name: str) -> bool:
        nl = name.lower()
        return any(b in nl for b in builtin_lower)

    for name in ("L2_FRS.json", "L2_TIMING_WAVEFORM.json"):
        for base in (project_dir, project_dir / "phase1/generated_docs", _pl.generated_docs_dir(project_dir)):
            p = base / name
            if not p.exists():
                continue
            try:
                d = json.loads(p.read_text())
            except Exception:
                continue
            pad_defs = d.get("pad_definitions") or []
            if isinstance(pad_defs, list):
                for pad in pad_defs:
                    if not isinstance(pad, dict):
                        continue
                    pad_name = pad.get("name")
                    if not isinstance(pad_name, str) or \
                       not _is_bus_pad_name(pad_name):
                        continue
                    aliases = pad.get("fpga_alias") or pad.get("fpga_aliases")
                    if isinstance(aliases, str):
                        aliases = [aliases]
                    if isinstance(aliases, list):
                        extra.extend(str(a) for a in aliases
                                     if isinstance(a, str))
            top_aliases = d.get("fpga_pin_aliases")
            if isinstance(top_aliases, dict):
                for canon, alist in top_aliases.items():
                    if not isinstance(canon, str) or \
                       not _is_bus_pad_name(canon):
                        continue
                    if isinstance(alist, str):
                        extra.append(alist)
                    elif isinstance(alist, list):
                        extra.extend(str(a) for a in alist
                                     if isinstance(a, str))
    seen = set()
    out = []
    for h in PIN_NAME_HINTS + tuple(extra):
        if h.lower() not in seen:
            seen.add(h.lower())
            out.append(h)
    return tuple(out)


def find_fit_rpts(project_dir: Path):
    """Look for a Quartus fit report under common output paths."""
    candidates = []
    for pat in ("**/output_files/*.fit.rpt", "**/quartus_work/*.fit.rpt",
                "**/*.fit.rpt"):
        candidates.extend(project_dir.glob(pat))
    return sorted(set(candidates))


def parse_pin_table(rpt_text: str, hints: tuple = PIN_NAME_HINTS):
    """
    The Fitter table for output pins is column-aligned with header
    fields including 'Name', 'Pin #', 'Combinational Fan-Out',
    'Output Enable Source'. Parse rows whose Name contains one of
    the half-duplex pin hints. Returns list of dicts.
    """
    out = []
    # Find rows that start with "; <name> ;" and contain V## pin numbers.
    # The columns are separated by ';' so we split on ';' and trim.
    for line in rpt_text.splitlines():
        if not line.startswith(";"):
            continue
        parts = [p.strip() for p in line.split(";")]
        # Header detection: Name is parts[1] in the IO table.
        if len(parts) < 5:
            continue
        name = parts[1] if len(parts) > 1 else ""
        if not any(h.lower() in name.lower() for h in hints):
            continue
        # Combinational Fan-Out column varies in position. Heuristic:
        # find the integer that follows the pin coordinate triple.
        try:
            # Attempt: parts[7] is fan-out in the typical Fitter IO table.
            fanout = int(parts[7])
        except (IndexError, ValueError):
            continue
        # Find OE source which contains the word "(inverted)" or
        # the signal path with ":".
        oe_source = ""
        for p in parts:
            if "inverted" in p.lower() or ":" in p:
                oe_source = p
        out.append({"name": name, "fanout": fanout, "oe_source": oe_source})
    return out


def waived(project_dir: Path) -> bool:
    waivers = project_dir / "waivers.json"
    if not waivers.exists():
        return False
    try:
        d = json.loads(waivers.read_text())
        return bool(d.get("fpga_pad_fanout_alternative"))
    except Exception:
        return False


def main():
    if len(sys.argv) < 2:
        print("Usage: fpga_pad_fanout_check.py <project_dir>")
        sys.exit(2)
    project_dir = Path(sys.argv[1]).resolve()
    rpts = find_fit_rpts(project_dir)
    if not rpts:
        print("PASS — no Quartus fit.rpt yet (gate skipped; compile hasn't run)")
        sys.exit(0)

    hints = _project_pin_hints(project_dir)
    failures = []
    pins_seen = []
    for rpt in rpts:
        try:
            text = rpt.read_text(errors="ignore")
        except Exception:
            continue
        for pin in parse_pin_table(text, hints):
            pins_seen.append((str(rpt.relative_to(project_dir)), pin))
            if pin["fanout"] > 1:
                failures.append((str(rpt.relative_to(project_dir)), pin))

    if not pins_seen:
        print("PASS — fit.rpt present but no half-duplex bus pin found")
        sys.exit(0)

    if not failures:
        print(f"PASS — {len(pins_seen)} half-duplex bus pin(s); all have "
              "Combinational Fan-Out ≤ 1")
        for rpt, pin in pins_seen:
            print(f"  • {pin['name']} fan-out={pin['fanout']}")
        sys.exit(0)

    if waived(project_dir):
        print(f"PASS_WITH_WAIVER — {len(failures)} high-fan-out pin(s)")
        sys.exit(0)

    print(f"FAIL — {len(failures)} half-duplex bus pin(s) with Combinational "
          "Fan-Out > 1:")
    for rpt, pin in failures:
        print(f"  • {pin['name']}: fan-out={pin['fanout']}")
        if pin["oe_source"]:
            print(f"    OE source = {pin['oe_source']}")
        print(f"    fit.rpt = {rpt}")
    print()
    print("Why this matters:")
    print("  High fan-out on the pad-driving LUT slows the rising/falling")
    print("  edges of the bus by adding internal capacitance. The host's")
    print("  analog bit-receiver detects this even at sub-microsecond")
    print("  scale; a 100 ns/sample scope sees identical 24 us LOW pulses")
    print("  for both PASS and FAIL versions, but the host distinguishes.")
    print()
    print("Fix: reduce internal taps on the bus-OE signal. Common causes:")
    print("  - tx_active also derived from id_bus_oe → 2 taps")
    print("  - debug observability ports also tap id_bus_oe → +N taps")
    print("  - rx_phy self-RX mask reads id_bus_oe → +1 tap")
    print()
    print("Specific patterns:")
    print("  - Use the LL-17 split data/oe wrapper. The independent")
    print("    `(oe && !tx) ? 1'b0 : 1'bz` lets Quartus place a small")
    print("    pin-local LUT instead of routing the deep state-decode.")
    print("  - Derive tx_active from a DIFFERENT signal (state itself,")
    print("    not id_bus_oe).")
    print("  - Move debug observability through a registered shadow,")
    print("    not a direct tap of id_bus_oe.")
    print()
    print('Or document an alternative in waivers.json:')
    print('    {"fpga_pad_fanout_alternative": "<reason>"}')
    sys.exit(1)


if __name__ == "__main__":
    main()
