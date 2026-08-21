#!/usr/bin/env python3
"""lvs_power_aware_extract_tcl.py — the LVS ROOT FIX (extraction side).

WHY THIS MODULE EXISTS
----------------------
Part 1 of the LVS root fix (`lvs_power_aware_netlist_emit.py`) makes the yosys
gate netlist power-aware so that — against a CLEAN-rail extracted layout — real
netgen reaches a GENUINE power-verified match (all four rails VPWR/VGND/VPB/VNB
verified). But the phase-3 DEF-direct Magic extraction
(`phase3_one_shot_runner._run_extraction_lvs`) does NOT produce a clean-rail
layout: with the plain `extract no all; extract do local; extract all` recipe on
a routed sky130 DEF, Magic COLLAPSES the four power nets onto ~2 mis-named nodes:

  * the GROUND rail (VGND, and the VNB p-substrate taps tied to it) is swallowed
    into the substrate node, which the sky130A magicrc names `VSUBS`
    (`set SUB VSUBS`, tech rule `substrate ... $SUB`), NOT `VGND`; and
  * the POWER rail (VPWR metal + the VPB n-well tied to it) loses its label and
    is auto-named after a leaf cell port, e.g. `_567_/VPB`, NOT `VPWR`.

netgen matches `global` nets BY NAME, so a layout whose rails are named `VSUBS`
and `_567_/VPB` can never match a power-aware schematic whose rails are the
globals `VGND`/`VPWR` — the power network stays unverified even though the DEF
carries VPWR/VGND as two distinct SPECIALNETS. The information is present; the
default extraction discards it.

THE FIX (two deterministic, PDK-derived levers — verified live on spm)
--------------------------------------------------------------------
  1. SUBSTRATE NAMING — emit `set SUB <ground-rail>` (VGND on sky130, VSS on
     gf180) into the extraction TCL *before* `extract`. The magicrc resolves the
     `$SUB` substrate-node name LAZILY at extract time, so this override renames
     the collapsed substrate/ground node from `VSUBS` to the true ground rail.

  2. POWER-NET LABEL SEEDING — parse the routed DEF's power SPECIALNET, take a
     handful of its stripe segments, and emit `box <..>um ...; label <power-rail>
     c <layer>` directives that paint the power-rail name (VPWR / VDD) onto the
     power geometry. An explicit top-level label out-ranks the auto-generated
     leaf-port name, so the extracted power net keeps its true name.

Both levers are chip-AGNOSTIC: the rail NAMES come from the PDK power model
(`lvs_power_aware_netlist_emit.power_model_for`), and the label GEOMETRY (layer +
coordinates, converted to microns via the DEF's own `UNITS DISTANCE MICRONS`
scale) comes from the routed DEF's SPECIALNETS — never a chip literal. Magic
accepts micron-suffixed box coordinates and the DEF layer name directly, so no
hardcoded per-PDK coordinate scale or layer-name map is needed.

§4.05 (load-bearing): this only RENAMES the power/ground nets that the layout
already has (VSUBS→VGND, leaf-port→VPWR); it never touches a SIGNAL net, so a
real signal-net mismatch is untouched and still FAILs. When the PDK is
unrecognised OR the DEF exposes no usable power SPECIALNET geometry, the emitter
returns the UNCHANGED base recipe (strict fall-through — no regression), and the
downstream `_try_power_aware_lvs` still returns None unless netgen reaches a
genuine match.

Usage:
    build_power_aware_extraction_tcl(base_tcl, pdk, def_text, top="") -> (tcl, stats)
    python3 lvs_power_aware_extract_tcl.py --def IN.def --pdk sky130A [--top NAME]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:  # package + script dual-import
    from . import lvs_power_aware_netlist_emit as _pa
except Exception:  # pragma: no cover - script/standalone import
    import lvs_power_aware_netlist_emit as _pa  # type: ignore


# Cap on how many power-net stripe segments we seed a label onto. One label is
# enough to name the whole connected net; a few give robustness margin if a
# single point somehow misses material. Kept small so the TCL stays compact even
# on a 20k-stripe full-chip PDN.
_MAX_LABEL_POINTS = 3


@dataclass
class ExtractTclStats:
    pdk: str = ""
    power_aware: bool = False
    ground_rail: str = ""
    power_rail: str = ""
    substrate_override: str = ""
    power_label_points: List[Dict[str, object]] = field(default_factory=list)
    skipped_reason: str = ""

    def as_dict(self) -> Dict[str, object]:
        return {
            "pdk": self.pdk,
            "power_aware": self.power_aware,
            "ground_rail": self.ground_rail,
            "power_rail": self.power_rail,
            "substrate_override": self.substrate_override,
            "power_label_points": self.power_label_points,
            "skipped_reason": self.skipped_reason,
        }


# A SPECIALNETS routing segment carrying two fully-numeric coordinates, e.g.
#   + ROUTED met5 1600 + SHAPE STRIPE ( 37320 158880 ) ( 158920 158880 )
#   NEW met5 1600 + SHAPE STRIPE ( 17320 138880 ) ( 178920 138880 )
# Segments with a `*` continuation coordinate are skipped (we only need one
# fully-specified stripe to seed a label).
_SEG_RE = re.compile(
    r"(?:ROUTED|NEW)\s+(?P<layer>\w+)\s+(?P<w>\d+)"
    r"(?:\s*\+\s*SHAPE\s+\w+)?\s*"
    r"\(\s*(?P<x1>\d+)\s+(?P<y1>\d+)\s*\)\s*"
    r"\(\s*(?P<x2>\d+)\s+(?P<y2>\d+)\s*\)")


def _dbu_per_um(def_text: str) -> int:
    m = re.search(r"UNITS\s+DISTANCE\s+MICRONS\s+(\d+)", def_text)
    return int(m.group(1)) if m else 1000


def _specialnets_section(def_text: str) -> str:
    m = re.search(r"^SPECIALNETS\b.*?^END SPECIALNETS", def_text, re.M | re.S)
    return m.group(0) if m else ""


@dataclass
class _SpecialNet:
    name: str
    use: Optional[str]                       # POWER / GROUND / None
    segments: List[Tuple[str, int, int, int, int, int]]  # layer,w,x1,y1,x2,y2


def _parse_specialnets(def_text: str) -> Dict[str, _SpecialNet]:
    """Parse the DEF SPECIALNETS into {name: _SpecialNet}. chip-AGNOSTIC."""
    sec = _specialnets_section(def_text)
    nets: Dict[str, _SpecialNet] = {}
    if not sec:
        return nets
    # Each net entry starts with a line `- <name>` and runs until the next
    # `- <name>` or END SPECIALNETS. The name may be plain or `\escaped`.
    for nm in re.finditer(
            r"^\s*-\s+(?P<name>\S+)\s(?P<body>.*?)"
            r"(?=^\s*-\s+\S+\s|^END SPECIALNETS)",
            sec, re.M | re.S):
        name = nm.group("name")
        body = nm.group("body")
        um = re.search(r"\+\s*USE\s+(POWER|GROUND)", body)
        segs: List[Tuple[str, int, int, int, int, int]] = []
        for seg in _SEG_RE.finditer(body):
            segs.append((seg.group("layer"), int(seg.group("w")),
                         int(seg.group("x1")), int(seg.group("y1")),
                         int(seg.group("x2")), int(seg.group("y2"))))
        nets[name] = _SpecialNet(name=name,
                                 use=(um.group(1) if um else None),
                                 segments=segs)
    return nets


def _find_rail_net(nets: Dict[str, _SpecialNet], rail_name: str,
                   use: str) -> Optional[_SpecialNet]:
    """Return the SPECIALNET that is the given rail: prefer an exact name match,
    else the (single) net carrying the matching `+ USE POWER|GROUND`."""
    if rail_name in nets:
        return nets[rail_name]
    # case-insensitive name match (DEF may use a different case)
    for n in nets.values():
        if n.name.lower() == rail_name.lower():
            return n
    use_matches = [n for n in nets.values() if n.use == use]
    if len(use_matches) == 1:
        return use_matches[0]
    return None


def _label_box_um(seg: Tuple[str, int, int, int, int, int],
                  dbu_per_um: int) -> Optional[Tuple[str, Tuple[float, float,
                                                               float, float]]]:
    """Return (layer, (x1um, y1um, x2um, y2um)) — a box strictly INSIDE the
    stripe `seg`, centred on its midpoint. The box spans len/4 along the wire
    and w/4 across it, so it is guaranteed to land on the metal regardless of
    grid snapping. Returns None for a degenerate/diagonal segment."""
    layer, w, x1, y1, x2, y2 = seg
    if w <= 0:
        return None
    horiz = (y1 == y2) and (x1 != x2)
    vert = (x1 == x2) and (y1 != y2)
    if not (horiz or vert):
        return None                          # diagonal / point — skip
    mx = (x1 + x2) / 2.0
    my = (y1 + y2) / 2.0
    length = abs(x2 - x1) if horiz else abs(y2 - y1)
    # Half-extent across the wire: a quarter of the width keeps the box well
    # inside the metal. Along the wire: a small box centred on the midpoint is
    # enough — cap it at the width so the box never grows to touch a crossing
    # strap even in a pathological PDN (same-layer nets never overlap anyway).
    perp = max(w / 4.0, 1.0)
    par = max(min(length / 4.0, float(w)), 1.0)
    if horiz:
        bx1, bx2 = mx - par, mx + par
        by1, by2 = my - perp, my + perp
    else:
        bx1, bx2 = mx - perp, mx + perp
        by1, by2 = my - par, my + par
    s = float(dbu_per_um)
    box = (round(bx1 / s, 4), round(by1 / s, 4),
           round(bx2 / s, 4), round(by2 / s, 4))
    return layer, box


def _power_label_points(power_net: _SpecialNet, dbu_per_um: int
                        ) -> List[Dict[str, object]]:
    """Pick up to `_MAX_LABEL_POINTS` label points on the power net's stripes."""
    pts: List[Dict[str, object]] = []
    for seg in power_net.segments:
        got = _label_box_um(seg, dbu_per_um)
        if got is None:
            continue
        layer, box = got
        pts.append({"layer": layer, "box_um": list(box)})
        if len(pts) >= _MAX_LABEL_POINTS:
            break
    return pts


def _inject_directives(base_tcl: str, directives: List[str]) -> Optional[str]:
    """Insert `directives` into `base_tcl` right before the first `extract`
    command line. Returns the new TCL, or None if there is no extract line."""
    lines = base_tcl.splitlines(keepends=True)
    for i, ln in enumerate(lines):
        if re.match(r"\s*extract\b", ln):
            block = "".join(d if d.endswith("\n") else d + "\n"
                            for d in directives)
            return "".join(lines[:i]) + block + "".join(lines[i:])
    return None


def build_power_aware_extraction_tcl(
        base_tcl: str, pdk: str, def_text: str, top: str = "",
        cell_lef: Optional[Path] = None
) -> Tuple[str, Dict[str, object]]:
    """Return (tcl, stats). Power-aware ONLY when the PDK is recognised AND the
    routed DEF exposes both a ground rail and usable power-net stripe geometry;
    otherwise the UNCHANGED `base_tcl` is returned (strict fall-through — no
    regression). chip-AGNOSTIC: rail names from the PDK model, geometry from the
    DEF."""
    stats = ExtractTclStats(pdk=_pa._normalize_pdk(pdk))
    # cell_lef is consulted ONLY when the NAME resolves to no table entry, so
    # the named-PDK lanes are unchanged and only the project-staged
    # (commercial) lane — which previously skipped — gains a model derived
    # from the PDK's own std-cell LEF.
    model = _pa.power_model_for(pdk, cell_lef=cell_lef)
    if model is None:
        stats.skipped_reason = (
            f"unrecognised PDK '{pdk}' — no power model"
            + ("" if cell_lef else
               " and no cell LEF supplied to derive one from"))
        return base_tcl, stats.as_dict()
    if not stats.pdk:
        stats.pdk = model.key
    # Rail names: pg_pins = (power, ground, well-of-power, well-of-ground).
    power_rail = model.pg_pins[0]
    ground_rail = model.pg_pins[1]
    stats.power_rail = power_rail
    stats.ground_rail = ground_rail

    nets = _parse_specialnets(def_text)
    if not nets:
        stats.skipped_reason = "no SPECIALNETS in DEF — cannot seed power labels"
        return base_tcl, stats.as_dict()
    ground_net = _find_rail_net(nets, ground_rail, "GROUND")
    power_net = _find_rail_net(nets, power_rail, "POWER")
    if ground_net is None or power_net is None:
        stats.skipped_reason = (
            "DEF SPECIALNETS do not expose both a power and a ground rail "
            f"(power={power_rail!r} ground={ground_rail!r})")
        return base_tcl, stats.as_dict()

    dbu = _dbu_per_um(def_text)
    label_pts = _power_label_points(power_net, dbu)
    if not label_pts:
        stats.skipped_reason = (
            f"power rail {power_net.name!r} has no usable stripe geometry to "
            "seed a label onto")
        return base_tcl, stats.as_dict()

    # Build the injected directive block.
    directives: List[str] = [
        "# --- power-aware extraction (lvs_power_aware_extract_tcl) ---",
        "# 1) name the collapsed substrate/ground node the true ground rail",
        f"set SUB {ground_rail}",
        "# 2) seed the power-rail name onto its DEF stripe geometry so the",
        "#    extracted power net keeps its true name (not a leaf-port name)",
        "snap internal",
    ]
    for pt in label_pts:
        bx = pt["box_um"]
        directives.append(
            f"box {bx[0]}um {bx[1]}um {bx[2]}um {bx[3]}um")
        directives.append(f"label {power_rail} c {pt['layer']}")
    directives.append(
        f'puts "PA_EXTRACT_APPLIED SUB={ground_rail} '
        f'power_rail={power_rail} labels={len(label_pts)}"')

    new_tcl = _inject_directives(base_tcl, directives)
    if new_tcl is None:
        stats.skipped_reason = "base TCL has no `extract` line to inject before"
        return base_tcl, stats.as_dict()

    stats.power_aware = True
    stats.substrate_override = ground_rail
    stats.power_label_points = label_pts
    return new_tcl, stats.as_dict()


# Standalone default base recipe — kept identical to
# phase3_one_shot_runner._MAGIC_EXT2SPICE_TCL so the CLI can be exercised on its
# own. The runner passes its own copy in; this is only the fallback for --def.
_DEFAULT_BASE_TCL = """\
crashbackups stop
drc off
lef read $env(TLEF)
lef read $env(CLEF)
eval $env(MACRO_LEF_READS)
def read $env(DEF)
load $env(TOP)
select top cell
port makeall
puts "PORTS_PROMOTED [port first]..[port last]"
extract no all
extract do local
extract all
ext2spice lvs
ext2spice -o $env(SPICE_OUT)
feedback save $env(FEEDBACK_OUT)
puts "MAGIC_EXT2SPICE_FEEDBACK $env(FEEDBACK_OUT) [feedback count]"
puts "MAGIC_EXT2SPICE_DONE $env(SPICE_OUT)"
quit -noprompt
"""


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Emit a POWER-AWARE Magic DEF-extraction TCL (keeps VPWR/"
                    "VGND separated + labelled, instead of collapsing them onto "
                    "the substrate) — the extraction side of the LVS root fix.")
    ap.add_argument("--def", dest="def_file", required=True, type=Path,
                    help="routed DEF (its SPECIALNETS seed the power labels)")
    ap.add_argument("--pdk", required=True,
                    help="PDK: sky130A | gf180mcuC | gf180mcuD")
    ap.add_argument("--top", default="", help="top module name (informational)")
    ap.add_argument("--base-tcl", type=Path, default=None,
                    help="base extraction TCL (default: built-in recipe)")
    ap.add_argument("--out", type=Path, default=None,
                    help="write the emitted TCL here (default: stdout)")
    ap.add_argument("--json", dest="json_out", type=Path, default=None,
                    help="write the stats JSON here")
    ns = ap.parse_args(argv)

    if not ns.def_file.is_file():
        print(f"ERROR: DEF not found: {ns.def_file}", file=sys.stderr)
        return 2
    base = (ns.base_tcl.read_text() if ns.base_tcl and ns.base_tcl.is_file()
            else _DEFAULT_BASE_TCL)
    def_text = ns.def_file.read_text(errors="replace")
    tcl, stats = build_power_aware_extraction_tcl(
        base, ns.pdk, def_text, top=ns.top)
    if ns.out:
        ns.out.write_text(tcl)
    else:
        print(tcl)
    if ns.json_out:
        ns.json_out.parent.mkdir(parents=True, exist_ok=True)
        ns.json_out.write_text(json.dumps(stats, indent=2) + "\n")
    print(json.dumps(stats, indent=2), file=sys.stderr)
    return 0 if stats.get("power_aware") else 1


if __name__ == "__main__":
    raise SystemExit(main())
