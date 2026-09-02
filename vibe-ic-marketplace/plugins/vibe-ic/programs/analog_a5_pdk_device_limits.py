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
    owner: Optional[str] = None
    for line in flat.splitlines():
        # WHICH MODEL OWNS THESE NUMBERS, measured on a real PDK file rather
        # than on a fixture. A magic PDK writes each gencell as
        #
        #     proc <ns>::<model>_defaults {} {
        #         return {w 0.35 l 0.13 ... \
        #                 ... lmin 0.13 wmin 0.15 ... \
        #                 compatible {<model> <other model>} ...}
        #     }
        #
        # The proc header carries no continuation, so after the joins above
        # the model name and its lmin/wmin are on DIFFERENT lines, and the
        # only model name on the lmin line is the one inside `compatible`.
        # Keying on that took the FIRST compatible entry every time: on
        # ihp-sg13g2 it filed the high-voltage block's limits under the
        # low-voltage model and reported NO limits at all for the two
        # high-voltage models — 2 of 4 MOS models answered, and the LDO in
        # the measured design is built entirely from the two that did not.
        # The declaring proc is the owner, so it is tracked across the lines
        # its body spans.
        pm = re.search(r"\bproc\s+\w+::([A-Za-z]\w*)_defaults\b", line)
        if pm:
            owner = pm.group(1)
        elif re.search(r"\bproc\s+\w+::", line):
            owner = None
        lm = re.search(r"lmin\s+([0-9.]+)\s+wmin\s+([0-9.]+)", line)
        if not lm:
            continue
        name = owner
        if name is None:
            # a PDK that states the model on the same line as the rule
            nm = re.search(
                r"\b([A-Za-z][A-Za-z0-9]*_(?:lv|hv|mv)_[np]mos\w*)\b", line)
            name = nm.group(1) if nm else None
        if name is None or not re.fullmatch(
                r"[A-Za-z][A-Za-z0-9]*_(?:lv|hv|mv)_[np]mos\w*", name):
            continue
        cand = (float(lm.group(1)), float(lm.group(2)))
        cur = out.get(name)
        out[name] = cand if cur is None else (min(cur[0], cand[0]),
                                              min(cur[1], cand[1]))
    return out


# ── every gencell, not only the MOS ones ──────────────────────────────
# `fet_limits` above answers for the MOS models, which is what the tap
# clearance needed. A LAYOUT EMITTER needs more: it draws resistors and
# capacitors too, and before it calls a gencell it has to know which
# PARAMETERS that gencell accepts — passing `m` to a cell that has no `m`
# is an error, and passing `guard` to one that has no guard ring is another.
#
# The PDK states all of it in one place: each gencell's `_defaults` proc.
# Reading it here keeps ONE derivation of "what the PDK permits" in the
# tree; a caller that re-parsed the same file would be the very defect this
# program exists to remove.
_DEFAULTS_RE = re.compile(
    r"proc\s+([A-Za-z_]\w*)::([A-Za-z_]\w*)_defaults\s*\{\s*\}\s*\{"
    r"(.*?)\n\}", re.S)


def _brace_tokens(body: str) -> list:
    """Tokenise a Tcl list, keeping each `{...}` group as ONE token."""
    out, i, n = [], 0, len(body)
    while i < n:
        ch = body[i]
        if ch.isspace() or ch == "\\":
            i += 1
            continue
        if ch == "{":
            depth, j = 1, i + 1
            while j < n and depth:
                depth += {"{": 1, "}": -1}.get(body[j], 0)
                j += 1
            out.append(body[i:j])
            i = j
            continue
        j = i
        while j < n and not body[j].isspace() and body[j] != "\\":
            j += 1
        out.append(body[i:j])
        i = j
    return out


def gencell_defaults(text: str, source: str = "") -> Dict[str, dict]:
    """{model: {namespace, params, lmin, wmin, class, source}} for every
    gencell the PDK file defines — MOS, resistor, capacitor alike.

    `params` is the set of parameter NAMES the gencell declares, which is
    what a caller must respect when it builds the `magic::gencell` command.
    `lmin`/`wmin` are the same PDK-stated minima `fet_limits` reads, and
    `class` is the PDK's OWN device classification (mosfet / resistor /
    capacitor), so a caller never has to infer a device class from a name.
    """
    out: Dict[str, dict] = {}
    for m in _DEFAULTS_RE.finditer(text):
        ns, model, body = m.group(1), m.group(2), m.group(3)
        body = body[body.find("return") + 6:] if "return" in body else body
        toks = _brace_tokens(body)
        if toks and toks[0].startswith("{"):
            toks = _brace_tokens(toks[0][1:-1])
        pairs = {}
        for i in range(0, len(toks) - 1, 2):
            pairs[toks[i]] = toks[i + 1]
        rec = {"namespace": ns, "source": source,
               "params": sorted(pairs.keys()),
               "class": pairs.get("class")}
        for k in ("lmin", "wmin"):
            try:
                rec[k] = float(pairs[k])
            except (KeyError, ValueError):
                rec[k] = None
        out[model] = rec
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


# ── the rest of what the deck states, for a caller that DRAWS ─────────
# `m1_space_um` above answers the one question the tap clearance needed. A
# layout EMITTER needs more of the same deck, and needs it PER LAYER:
#
#   MEASURED (ihp-sg13g2, this emitter's first output). Using the Metal1
#   spacing rule as the floor for every metal produced 594 Metal3 spacing
#   errors and 399 Metal2 spacing errors, because M2.b/M3.b are 0.21 um and
#   M1.b is 0.18. Choosing a via pad without reading the surround rules
#   produced another 2746 "metal overlap of via < 0.045um" errors, and
#   ignoring the minimum-area rule produced 117 more.
#
# Every one of those numbers is stated in the deck, in four rule forms that
# a magic DRC deck writes the same way whatever the PDK:
#
#   width    <layers> N           "... (<TAG>)"
#   spacing  <l> <l>  N touching_ok "... (<TAG>)"
#   area     <layers> A W         "... (<TAG>)"
#   surround <cut>/<metal> <layers> N <kind> "... (<TAG>)"
#
# The layer INDEX is read from the deck's own layer tokens (`allm2`, `v1/m1`),
# so no metal is named here.
_RULE_WIDTH = re.compile(r"^\s*width\s+(\S+)\s+(\d+)\s", re.M)
_RULE_SPACING = re.compile(r"^\s*spacing\s+(\S+)\s+(\S+)\s+(\d+)\s", re.M)
_RULE_AREA = re.compile(r"^\s*area\s+(\S+)\s+(\d+)\s+(\d+)\s", re.M)
_RULE_SURROUND = re.compile(
    r"^\s*surround\s+v(\d+)/m(\d+)\s+(\S+)\s+(\d+)\s", re.M)
_METAL_TOK = re.compile(r"(?:^|[,*])(?:all|obs|seal)?m(\d+)\b")
_VIA_TOK = re.compile(r"^v(\d+)$")


def _metal_index(token: str) -> Optional[int]:
    """The metal level a deck layer token names, or None if it names more
    than one — a rule that spans several metals binds none of them here."""
    hits = {int(m.group(1)) for m in _METAL_TOK.finditer(token)}
    return hits.pop() if len(hits) == 1 else None


def deck_rules(text: str) -> Dict[str, Dict]:
    """What the DRC deck states, per layer, in MICRONS.

        {"metal_space_um": {n: um}, "metal_width_um": {n: um},
         "metal_area_um2": {n: um2},
         "via_width_um":   {n: um},  "via_space_um": {n: um},
         "via_surround_um": {(via, metal): um}}

    Deck lengths are in the deck's own integer units, which the Metal1 rules
    calibrate as nanometres; areas are those units squared. Nothing here is
    defaulted: a rule the deck does not state is simply absent, and a caller
    that needs it must say so rather than invent it."""
    out: Dict[str, Dict] = {"metal_space_um": {}, "metal_width_um": {},
                            "metal_area_um2": {}, "via_width_um": {},
                            "via_space_um": {}, "via_surround_um": {}}
    for tok, val in _RULE_WIDTH.findall(text):
        vm = re.match(r"^v(\d+)/m\d+$", tok)
        if vm:
            out["via_width_um"][int(vm.group(1))] = int(val) / 1000.0
            continue
        idx = _metal_index(tok)
        if idx is not None:
            cur = out["metal_width_um"].get(idx)
            out["metal_width_um"][idx] = (int(val) / 1000.0 if cur is None
                                          else max(cur, int(val) / 1000.0))
    for t1, t2, val in _RULE_SPACING.findall(text):
        v1, v2 = _VIA_TOK.match(t1), _VIA_TOK.match(t2)
        if v1 and v2 and v1.group(1) == v2.group(1):
            k = int(v1.group(1))
            out["via_space_um"][k] = max(out["via_space_um"].get(k, 0.0),
                                         int(val) / 1000.0)
            continue
        i1, i2 = _metal_index(t1), _metal_index(t2)
        if i1 is not None and i1 == i2:
            out["metal_space_um"][i1] = max(
                out["metal_space_um"].get(i1, 0.0), int(val) / 1000.0)
    for tok, area, _w in _RULE_AREA.findall(text):
        idx = _metal_index(tok)
        if idx is not None:
            out["metal_area_um2"][idx] = max(
                out["metal_area_um2"].get(idx, 0.0), int(area) / 1e6)
    for via, met, _tgt, val in _RULE_SURROUND.findall(text):
        key = (int(via), int(met))
        out["via_surround_um"][key] = max(out["via_surround_um"].get(key, 0.0),
                                          int(val) / 1000.0)
    return out


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
