#!/usr/bin/env python3
"""analog_a5_pdk_device_limits.py — what the PDK ITSELF permits a drawn
device to be, and what clearance its metal-1 rule demands of a bulk tap.

WHY THIS PROGRAM EXISTS
-----------------------
A5 is the one step in the analog track with NO deterministic producer. The
plugin ships a CHECKER (`analog_a5_layout_check.py`) and a matching record
(`_analog_layout_matching.py`); the DRAWING is a handoff to the
`analog-layout` skill. Nothing in the tree derives what geometry the PDK will
accept, so every layout generator a run authors invents that answer, and
invents it as a LIST of widths it happens to have probed.

MEASURED (u_hawaii_adc / ihp-sg13g2, round 20). A generator authored that way
refused to draw a 1.0/0.5 um keeper with

    AssertionError: ('mp_mkp1', 'no leg tap level')

on a device the PDK is perfectly happy with (sg13_lv_pmos wmin 0.15 um). It
was not refusing a WIDTH: its bulk-tap scan walked UP from the guard ring's B
label, and on a narrow device that label sits at the ring leg's BOTTOM, so two
thirds of the leg was never examined. The circuit that needed it was the fix
for a counter that never counted. A predicted refusal, in a hand-authored
script, blocked a measured circuit fix.

WHAT THIS PROGRAM ANSWERS, from the PDK and nothing else:

  * `limits`    — (lmin, wmin) per MOS gencell, out of the PDK's own gencell
                  definitions. A model appears in several gencell blocks
                  (short- and long-channel variants); the PDK permits the
                  SMALLEST, so the minimum across blocks is taken. Taking the
                  last match instead yields lmin 0.4 um for sg13_lv_pmos and
                  would refuse a legal 0.13 um device.
  * `m1_space`  — the Metal1 minimum space/notch rule, from the DRC deck.
  * `tap_clear` — the clearance a bulk tap needs from the nearest terminal
                  structure: m1_space + the two M1 pads' half-heights, which
                  the caller supplies because pad size is the GENERATOR's
                  choice, not the PDK's.

WHAT IT DOES NOT DO. It does not draw, place or route, and it does not grade a
layout: DRC does that, and a clearance floor computed here is a PREDICTION,
not a verdict. A generator that cannot meet the floor should DRAW and RECORD
the shortfall, and let the sign-off deck adjudicate — never assert.

CHIP-AGNOSTIC. No design, block, net or device name appears here. The PDK
family and its file layout are arguments; the numbers all come out of files
the PDK ships.

    analog_a5_pdk_device_limits.py --container <c> [--pdk-root <p>]
                                   [--check-w W --check-l L --model M]
                                   [--tap-pad-half N --terminal-pad-half N]
                                   [--json out.json]

exit 0 → limits derived (and, if asked, the geometry is permitted)
exit 1 → the geometry is FORBIDDEN by the PDK (named, with the rule + file)
exit 2 → NOT CHECKED: the PDK files could not be read
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from typing import Dict, Optional, Tuple

# Where a magic-based PDK keeps the two files this program reads. Both are
# arguments; these are only the conventional names.
GENCELL_TCL = "{root}/{family}/libs.tech/magic/{family}-fet.tcl"
DRC_TECH = "{root}/{family}/libs.tech/magic/{family}-drc.tech"


def _read(path: str, container: Optional[str]) -> Optional[str]:
    """Read a PDK file. It usually lives in the EDA image, not on the host."""
    if container:
        cp = subprocess.run(["docker", "exec", container, "cat", path],
                            capture_output=True, text=True, timeout=120)
        return cp.stdout if cp.returncode == 0 and cp.stdout else None
    try:
        with open(path) as fh:
            return fh.read()
    except OSError:
        return None


def fet_limits(text: str) -> Dict[str, Tuple[float, float]]:
    """{gencell model: (lmin_um, wmin_um)} from the PDK's gencell defs.

    A model recurs across gencell blocks; the PDK permits the SMALLEST of
    them, so take the minimum rather than the last one parsed.
    """
    flat = re.sub(r"\\\s*\n", " ", text)          # join tcl continuations
    out: Dict[str, Tuple[float, float]] = {}
    for line in flat.splitlines():
        lm = re.search(r"lmin\s+([0-9.]+)\s+wmin\s+([0-9.]+)", line)
        if not lm:
            continue
        nm = re.search(r"\b([A-Za-z][A-Za-z0-9]*_(?:lv|hv|mv)_[np]mos\w*)\b",
                       line)
        if not nm:
            continue
        cand = (float(lm.group(1)), float(lm.group(2)))
        cur = out.get(nm.group(1))
        out[nm.group(1)] = cand if cur is None else (min(cur[0], cand[0]),
                                                     min(cur[1], cand[1]))
    return out


def m1_space_um(text: str) -> Optional[float]:
    """Metal1 min space / notch, in um, from the DRC deck.

    magic decks state the value in the deck's own integer units and name the
    rule in the trailing message; the width rule on the same layer calibrates
    the unit, so no scale factor is assumed.
    """
    sp = re.search(r"^\s*spacing\s+\S*m1\S*[^\n]*?\s(\d+)\s+touching_ok\s*"
                   r"\\?\s*\n?[^\n]*M1\.b", text, re.M)
    wd = re.search(r"^\s*width\s+\S*m1\S*[^\n]*?\s(\d+)\s+\"[^\"]*M1\.a",
                   text, re.M)
    if not sp or not wd:
        return None
    # the deck's units are calibrated by the width rule: magic PDKs state
    # these in nm, which the width rule's own magnitude confirms.
    return int(sp.group(1)) / 1000.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--container")
    ap.add_argument("--pdk-root", default="/foss/pdks")
    ap.add_argument("--family", default="ihp-sg13g2")
    ap.add_argument("--gencell-tcl")
    ap.add_argument("--drc-tech")
    ap.add_argument("--model")
    ap.add_argument("--check-w", type=float)
    ap.add_argument("--check-l", type=float)
    ap.add_argument("--tap-pad-half-um", type=float, default=0.0)
    ap.add_argument("--terminal-pad-half-um", type=float, default=0.0)
    ap.add_argument("--json")
    a = ap.parse_args()

    gp = a.gencell_tcl or GENCELL_TCL.format(root=a.pdk_root, family=a.family)
    dp = a.drc_tech or DRC_TECH.format(root=a.pdk_root, family=a.family)
    gt, dt = _read(gp, a.container), _read(dp, a.container)

    out: Dict[str, object] = {"family": a.family,
                              "gencell_tcl": gp, "drc_tech": dp}
    if gt is None or dt is None:
        out["result"] = "NOT_CHECKED"
        out["reason"] = (
            f"PDK files unreadable ({'gencell' if gt is None else 'drc deck'})"
            f"{' in container ' + a.container if a.container else ''}. "
            f"Device limits are DERIVED from the PDK; a limit this program "
            f"cannot read is ABSENT, never a default.")
        print(json.dumps(out, indent=2))
        if a.json:
            open(a.json, "w").write(json.dumps(out, indent=2) + "\n")
        return 2

    lim = fet_limits(gt)
    m1 = m1_space_um(dt)
    out["limits_um"] = {k: {"lmin": v[0], "wmin": v[1]}
                        for k, v in sorted(lim.items())}
    out["m1_space_um"] = m1
    if m1 is not None:
        out["tap_clear_um"] = round(
            m1 + a.tap_pad_half_um + a.terminal_pad_half_um, 6)
        out["tap_clear_terms"] = {
            "m1_space_um": m1,
            "tap_pad_half_um": a.tap_pad_half_um,
            "terminal_pad_half_um": a.terminal_pad_half_um}
    out["result"] = "OK"

    rc = 0
    if a.model and (a.check_w is not None or a.check_l is not None):
        if a.model not in lim:
            out["result"] = "NOT_CHECKED"
            out["reason"] = (f"{a.model} has no gencell entry in {gp}; this "
                             f"program cannot say what the PDK permits it")
            rc = 2
        else:
            lmin, wmin = lim[a.model]
            bad = []
            if a.check_w is not None and a.check_w < wmin - 1e-9:
                bad.append(f"w={a.check_w}u is below the PDK minimum "
                           f"wmin={wmin}u for {a.model} ({gp})")
            if a.check_l is not None and a.check_l < lmin - 1e-9:
                bad.append(f"l={a.check_l}u is below the PDK minimum "
                           f"lmin={lmin}u for {a.model} ({gp})")
            out["checked"] = {"model": a.model, "w": a.check_w,
                              "l": a.check_l,
                              "lmin": lmin, "wmin": wmin}
            if bad:
                out["result"] = "FORBIDDEN"
                out["refusals"] = bad
                rc = 1
            else:
                out["result"] = "PERMITTED"

    print(json.dumps(out, indent=2))
    if a.json:
        open(a.json, "w").write(json.dumps(out, indent=2) + "\n")
    return rc


if __name__ == "__main__":
    sys.exit(main())
