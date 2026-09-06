#!/usr/bin/env python3
"""analog_a5_layout_emit.py — A5's missing PRODUCER: it draws the layout.

WHY THIS PROGRAM EXISTS
-----------------------
A5 is the one step in the analog track that had no deterministic producer.
The plugin shipped a CHECKER (`analog_a5_layout_check`, "is geometry
present?"), a RECORD (`_analog_layout_matching`), and a stub in
`analog_one_shot_runner` that wrote 400 bytes of `x` as `layout.mag`. The
DRAWING was a hand-off to the `analog-layout` skill, and the skill had no
program behind it — so every run that needed a real analog layout authored
its own generator.

MEASURED (u_hawaii_adc / ihp-sg13g2, round 20). The generator one run
authored was hand-written in a scratch directory and copied forward for
eight rounds. It encoded "what is drawable" as the two widths it happened to
have probed, and refused a legal `w=1.0u l=0.5u` keeper — a device the PDK is
perfectly happy with (wmin 0.15 um) — with

    AssertionError: ('mp_mkp1', 'no leg tap level')

The refusal was not about the width at all: its bulk-tap scan walked UP from
the guard ring's B label, which on that device sits BELOW the ring leg, and a
25-lambda stride anchored on that label missed the only legal band by ONE
lambda. A predicted refusal, in a hand-authored script, blocked a measured
circuit fix.

THE CONTRACT
------------
INPUTS, all files, none of them a design:

  1. the A3 block netlist `phase3/analog/<block>/<block>.sp`, parsed for the
     subckt name, its port order, and per device (name, model, terminals,
     w, l, m). Nothing else is read from it. Section 4.05: the netlist is
     design INPUT; no oracle, golden or harness artefact is ever opened.
  2. the PDK's own gencell definitions and DRC deck, through
     `analog_a5_pdk_device_limits` — (lmin, wmin) per model, Metal1 minimum
     space, and a bulk-tap clearance floor built from those plus this
     emitter's OWN pad half-heights (pad size is the GENERATOR's choice, so
     the limits program takes it as an argument).
  3. a tool handle (container name / magic rcfile) — a path, not a behaviour.

OUTPUTS, exactly two, both under `phase3/analog/<block>/`:

  1. `layout.mag` and the streamed `<block>.gds`, carrying REAL placed
     geometry. `analog_a5_layout_check` already rejects an empty or
     stub-marked layout and keeps passing unchanged.
  2. `layout_provenance.json`: producer + version, block, device count, the
     resolved PDK limits WITH the file each came from, and a `deviations`
     list. A deviation is a structured record, not prose:
     {device, model, w, l, quantity, required, achieved, shortfall,
      adjudicator}.

THE INVARIANTS
--------------
I1  DRAWS WHAT THE LIMITS PERMIT. A geometry inside (lmin, wmin) is drawn. A
    width this emitter has not drawn before is NOT an error: there is no
    width list anywhere in this file. An emitter that refuses everything also
    refuses the bug.

I2  REFUSES SUB-MINIMUM BY NAME, NEVER BY ASSERTION. `w`/`l` below the PDK
    minimum exits non-zero naming the model, the value, the rule and the FILE
    the rule came from, BEFORE any probe. An AssertionError tuple is a
    contract violation.

I3  SEARCHES THE WHOLE STRUCTURE, NOT ONE DIRECTION. The bulk tap is chosen
    by scanning the ring leg's FULL extent on the PDK's own grid and taking
    the position of MAXIMUM clearance — never the first hit of a descending
    ladder of magic numbers, and never a walk in one direction from a label
    that may sit at either end. The same rule governs the escape lanes.

I4  RECORDS SHORTFALLS LOUDLY, AND NEVER GRADES. A clearance floor is a
    PREDICTION; the sign-off deck is the adjudicator. When the best available
    position is under the floor this emitter DRAWS it and writes a deviation
    naming device, quantity, required, achieved and shortfall — then A6
    decides. This program never prints a DRC verdict of its own and never
    silently downgrades a floor to make itself pass.

I5  DEGRADES LOUDLY, NEVER SILENTLY. An unreadable PDK, or an unreachable
    tool, is ENV_UNAVAILABLE with the file/tool named and a non-zero exit —
    never a built-in default and never a fabricated `layout.mag`. A structure
    that cannot host a tap at all is REFUSED by name, with the extent it
    measured, and nothing is written.

WHAT IS CHIP-AGNOSTIC HERE, AND HOW
-----------------------------------
No design, block, net or device name appears in this file, and no PDK family
name either. Everything PDK-specific is MEASURED:

  * the gencell namespace, the parameter names each gencell accepts, the
    device CLASS (mosfet / resistor / capacitor) and (lmin, wmin) come from
    the PDK's own `_defaults` procs, through `analog_a5_pdk_device_limits`;
  * lambda-per-micron comes from asking Magic itself, not from a constant;
  * a terminal's metal level is the lowest `metalN` plane whose rectangle
    covers the label point in the gencell's OWN output — so a capacitor
    terminal that lands on metal5 is routed as metal5 without this file ever
    naming a capacitor or a metal5;
  * the guard-ring layer is whatever layer the bulk label sits on.

The only numbers this file chooses are the ones the PDK does NOT state: the
wire width and via pad size of its own routing. They are CLI arguments, and
they are recorded in the provenance.

    analog_a5_layout_emit.py <project_dir> [--block B] [--container C]
                             [--magicrc PATH] [--pdk-root P] [--family F]

exit 0 → LAYOUT: OK          (layout.mag + <block>.gds + provenance written)
exit 1 → FORBIDDEN           (the PDK refuses this geometry, named) — OR the
                             layout this emitter drew SHORTS two routed nets,
                             with the witness path in the provenance
exit 2 → ENV_UNAVAILABLE     (PDK unreadable or tool unreachable, named)
exit 3 → REFUSED             (drawn structure cannot host the connection)
chip-AGNOSTIC.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shlex
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _atomic_artefact as _aa  # noqa: E402 — vibe-ic#1082
import _path_layout as _pl  # noqa: E402
import analog_a5_pdk_device_limits as _lim  # noqa: E402
from _analog_a_check_common import load_block_list  # noqa: E402
import magic_gencell_layout_lib as _gl  # noqa: E402
from analog_hardmacro_gds_emit import Stage  # noqa: E402

PRODUCER = "analog_a5_layout_emit"
SCHEMA = 1

RC_OK = 0
RC_FORBIDDEN = 1
RC_ENV_UNAVAILABLE = 2
RC_REFUSED = 3

# The adjudicator of every clearance this emitter predicts. Named in each
# deviation so a reader never mistakes a prediction for a verdict.
ADJUDICATOR = "A6 per-block sign-off DRC deck (analog_a6_block_pv_check)"


class Refusal(RuntimeError):
    """I5 — a structure this emitter cannot draw. Named, with what was
    measured, and never an assertion tuple."""


# The two numbers the PDK does not state, because they are this generator's
# own choice of routing style. CLI-overridable; recorded in the provenance.
DEFAULT_WIRE_W_UM = 0.30
DEFAULT_VIA_PAD_HALF_UM = 0.15


# ──────────────────────────────────────────────────────────────────────
# 1. the A3 netlist — design INPUT, and the only design this program reads
# ──────────────────────────────────────────────────────────────────────
_SUBCKT_RE = re.compile(r"(?is)^\.subckt\s+(\S+)([^\n]*)\n(.*?)^\.ends",
                        re.M)
_NUM_RE = re.compile(r"^([-+]?[0-9.]+(?:[eE][-+]?\d+)?)\s*([a-zA-Z]*)$")

# SPICE magnitude suffixes. A bare number in a device parameter is read as
# microns, which is what every analog netlist in this flow writes; the
# assumption is recorded in the provenance rather than left implicit.
_SUFFIX_UM = {"": 1.0, "u": 1.0, "um": 1.0, "n": 1e-3, "nm": 1e-3,
              "m": 1e3, "p": 1e-6, "meg": 1e6, "k": 1e9}


def _param_value(raw: str) -> Optional[float]:
    m = _NUM_RE.match(raw.strip())
    if not m:
        return None
    scale = _SUFFIX_UM.get(m.group(2).lower())
    if scale is None:
        return None
    return float(m.group(1)) * scale


def parse_netlist(sp: Path) -> Tuple[str, List[str], List[dict]]:
    """(subckt name, port order, devices). A device line is
    `x<name> <net>... <model> [k=v]...`: the parameters are the trailing
    `k=v` tokens, the model is the token before them, the rest are nets."""
    text = sp.read_text(errors="replace")
    m = _SUBCKT_RE.search(text)
    if not m:
        raise ValueError(f"{sp} declares no .subckt/.ends pair")
    block, portstr, body = m.group(1), m.group(2), m.group(3)
    ports = portstr.split()
    devs: List[dict] = []
    for line in body.splitlines():
        line = line.split("$")[0].strip()
        if not line or line[0] in "*.+":
            continue
        toks = line.split()
        if not toks[0].lower().startswith("x") or len(toks) < 3:
            continue
        pars: Dict[str, float] = {}
        i = len(toks)
        while i > 1 and "=" in toks[i - 1]:
            k, _, v = toks[i - 1].partition("=")
            val = _param_value(v)
            if val is not None:
                pars[k.lower()] = val
            i -= 1
        if i < 3:
            continue
        devs.append({"name": toks[0][1:], "model": toks[i - 1],
                     "nets": toks[1:i - 1], "pars": pars})
    return block, ports, devs


# ──────────────────────────────────────────────────────────────────────
# 2. the PDK — every number in this section comes out of a PDK file
# ──────────────────────────────────────────────────────────────────────
class PdkFacts:
    """What the PDK says, and which file said it."""

    def __init__(self) -> None:
        self.gencells: Dict[str, dict] = {}     # model -> defaults record
        self.mos_limits: Dict[str, Tuple[float, float]] = {}
        self.m1_space_um: Optional[float] = None
        self.deck: Dict[str, Dict] = {}
        self.sources: Dict[str, str] = {}
        # WHAT A DRAWN TYPE IS, out of the technology file that declares it.
        # See `analog_a5_pdk_device_limits.layer_identity` for the defect
        # this closes; `read_pdk` refuses rather than leave it None.
        self.layers: Optional["_lim.LayerIdentity"] = None

    def limits_for(self, model: str) -> Tuple[Optional[float], Optional[float],
                                              Optional[str]]:
        """(lmin_um, wmin_um, file that stated them) or (None, None, None)."""
        rec = self.gencells.get(model)
        lmin = rec.get("lmin") if rec else None
        wmin = rec.get("wmin") if rec else None
        src = rec.get("source") if rec else None
        if model in self.mos_limits:
            # `fet_limits` takes the MINIMUM across every gencell block a
            # model appears in, which is what the PDK actually permits. It is
            # the authority wherever it speaks.
            flmin, fwmin = self.mos_limits[model]
            lmin = flmin if lmin is None else min(lmin, flmin)
            wmin = fwmin if wmin is None else min(wmin, fwmin)
            src = self.sources.get("gencell_tcl", src)
        return lmin, wmin, src


def read_pdk(stage: Stage, pdk_root: str, family: str,
             gencell_tcl: Optional[str], drc_tech: Optional[str],
             magic_tech: Optional[str] = None
             ) -> Tuple[Optional[PdkFacts], str]:
    """Read every PDK fact this emitter needs, or say which file was
    unreadable. Never a default: a limit that cannot be read is ABSENT."""
    gp = gencell_tcl or _lim.GENCELL_TCL.format(root=pdk_root, family=family)
    dp = drc_tech or _lim.DRC_TECH.format(root=pdk_root, family=family)
    tp = magic_tech or _lim.MAGIC_TECH.format(root=pdk_root, family=family)
    tech_dir = str(Path(gp).parent)

    facts = PdkFacts()
    facts.sources["gencell_tcl"] = gp
    facts.sources["drc_tech"] = dp
    facts.sources["magic_tech"] = tp

    rc, out, err = stage.sh(f"cat {shlex.quote(gp)}", timeout=120)
    if rc != 0 or not out.strip():
        return None, (f"ENV_UNAVAILABLE: the PDK gencell definitions are "
                      f"unreadable at {gp} ({(err or out).strip()[:160]}). "
                      f"Device limits are DERIVED from the PDK; a limit this "
                      f"program cannot read is ABSENT, never a default.")
    facts.mos_limits = _lim.fet_limits(out)
    facts.gencells.update(_lim.gencell_defaults(out, gp))

    rc, out, err = stage.sh(f"cat {shlex.quote(dp)}", timeout=120)
    if rc != 0 or not out.strip():
        return None, (f"ENV_UNAVAILABLE: the PDK DRC deck is unreadable at "
                      f"{dp} ({(err or out).strip()[:160]}). The Metal1 "
                      f"spacing rule is DERIVED from it, never assumed.")
    facts.m1_space_um = _lim.m1_space_um(out)
    facts.deck = _lim.deck_rules(out)
    if facts.m1_space_um is None:
        return None, (f"ENV_UNAVAILABLE: {dp} states no Metal1 minimum-space "
                      f"rule this program can read. The bulk-tap clearance "
                      f"floor is built on it and is not guessed.")

    # THE LAYER TABLE. Which conductor a gencell delivered a terminal on is
    # a question about what the drawn type IS, and the technology file is
    # the only thing that knows. It is required for the same reason the two
    # files above are: without it this emitter reads a TYPE NAME, and a PDK
    # that spells a capacitor's top plate `mimcapcontact` gets both of that
    # device's terminals painted onto its bottom plate.
    rc, out, err = stage.sh(f"cat {shlex.quote(tp)}", timeout=120)
    if rc != 0 or not out.strip():
        return None, (f"ENV_UNAVAILABLE: the PDK technology file is "
                      f"unreadable at {tp} ({(err or out).strip()[:160]}). "
                      f"Which conductor plane each drawn type occupies is "
                      f"DERIVED from it; reading the type's NAME instead is "
                      f"what shorts a capacitor whose plates are not spelled "
                      f"metalN.")
    facts.layers = _lim.layer_identity(out, tp)
    if not facts.layers.plane_of:
        return None, (f"ENV_UNAVAILABLE: {tp} declares no `types` section "
                      f"this program can read, so no drawn type has a plane. "
                      f"A conductor level is DERIVED, never assumed.")

    # Every OTHER gencell file the same technology directory ships — the
    # resistors and capacitors live there, and their `_defaults` procs state
    # their own minima and parameter names. Failing to list the directory is
    # not fatal: the MOS file above already answered, and a model with no
    # gencell entry is refused BY NAME later rather than silently drawn.
    rc, out, _ = stage.sh(f"ls {shlex.quote(tech_dir)}/*.tcl", timeout=120)
    if rc == 0:
        for path in sorted(set(out.split())):
            if path == gp:
                continue
            rc2, txt, _ = stage.sh(f"cat {shlex.quote(path)}", timeout=120)
            if rc2 == 0 and txt.strip():
                for model, rec in _lim.gencell_defaults(txt, path).items():
                    facts.gencells.setdefault(model, rec)
    return facts, ""


def forbidden_geometries(devs: Sequence[dict], facts: PdkFacts) -> List[str]:
    """I2 — every sub-minimum geometry, named, with the rule and the FILE.

    Runs BEFORE any probe. A width this emitter has never drawn is not in
    here; only a width the PDK itself forbids is."""
    bad: List[str] = []
    for dev in devs:
        lmin, wmin, src = facts.limits_for(dev["model"])
        w, l = dev["pars"].get("w"), dev["pars"].get("l")
        if w is not None and wmin is not None and w < wmin - 1e-9:
            bad.append(f"{dev['name']}: w={w}u is below the PDK minimum "
                       f"wmin={wmin}u for {dev['model']} ({src})")
        if l is not None and lmin is not None and l < lmin - 1e-9:
            bad.append(f"{dev['name']}: l={l}u is below the PDK minimum "
                       f"lmin={lmin}u for {dev['model']} ({src})")
    return bad


# ──────────────────────────────────────────────────────────────────────
# 3. Magic — the tool handle, and the cell geometry it reports back
# ──────────────────────────────────────────────────────────────────────
_METAL_RE = re.compile(r"^m(?:etal)?(\d+)$")
_VIA_RE = re.compile(r"^(?:via|v)(\d+)$")
_SECTION_RE = re.compile(r"^<< (\S+) >>\n(.*?)(?=^<<)", re.S | re.M)
_FIXED_BBOX_RE = re.compile(
    r"string FIXED_BBOX (-?\d+) (-?\d+) (-?\d+) (-?\d+)")
_MAG_NAME_RE = re.compile(r"(?m)^([A-Za-z0-9_.+-]+\.mag)$")


def parse_cell(text: str, layers: Optional["_lim.LayerIdentity"] = None
               ) -> dict:
    """Geometry of one gencell child, in LAMBDA.

    The two coordinate spaces inside a `.mag` — `rect`/`use` following the
    file's own `magscale` header while `rlabel` is always internal units —
    are `magic_gencell_layout_lib`'s LAW #22, measured in the same campaign
    this emitter comes from. They are read THROUGH that library rather than
    re-derived here: a second copy of one measured fact is a second thing to
    keep true."""
    scale = _gl.mag_scale(text)

    sections: Dict[str, List[Tuple[int, int, int, int]]] = {}
    for sm in _SECTION_RE.finditer(text):
        name = sm.group(1)
        if name in ("checkpaint", "labels", "properties"):
            continue          # bookkeeping, not geometry
        # OUTWARD, never toward zero. A `magscale 1 2` gencell puts edges on
        # the HALF lambda, and `int()` pulls both of them toward zero: the
        # low edge rises, the high edge falls, and every rectangle this
        # emitter reads is up to a lambda SMALLER than the one the deck will
        # grade. That is the wrong direction for a number used as an
        # obstacle. MEASURED, after the island placer was already clearing
        # everything it could see: 30 M2.b violations left on one block, all
        # of them at a gap of 0.205 um against a 0.21 um rule — one half
        # lambda, and the placer had computed 0.21 and was satisfied. The
        # same law as `Geo.L`: a minimum is never rounded down, and neither
        # is the size of the thing you have to stay away from.
        sections[name] = [(int(math.floor(r[0])), int(math.floor(r[1])),
                           int(math.ceil(r[2])), int(math.ceil(r[3])))
                          for r in _gl.parse_rects_lambda(sm.group(2), scale)]

    def metal_level_at(x: int, y: int) -> int:
        """The HIGHEST metal the gencell itself already delivers at this
        label, read out of the gencell's own output.

        A terminal either sits on a conductor plane, or on a CONTACT type —
        and in Magic a contact IS its two residues plus the cut, so a
        contact carries the terminal up to the HIGHER of the two planes it
        joins.

        WHICH IS WHICH IS THE **PDK'S** ANSWER, not this file's. `layers` is
        the technology file's own `types`/`contact` table
        (`_lim.layer_identity`), and asking it is the whole repair: reading
        the section NAME instead gave every type this PDK does not spell
        `metalN`/`viaN` no level at all, so a MiM capacitor's top plate —
        delivered on `mimcapcontact`, a contact from the cap plate to metal6
        — read as the metal5 plane its BOTTOM plate occupies. Both terminals
        then landed on one conductor and the capacitor was shorted: 13 of
        them across u_hawaii_adc's two blocks, and the sign-off LVS answered
        `mismatch` with nothing in the flow able to say why. The same table
        answers `via4 metal4 metal5` -> 5, which is what the name-reading
        code already returned, so a PDK that does spell its conductors that
        way is unchanged.

        WITHOUT a table the NAMES are read, exactly as before. That path is
        unreachable from the producer — `read_pdk` refuses ENV_UNAVAILABLE
        when the technology file cannot be read — and exists so that the
        parser stays a pure function of one `.mag`.

        MEASURED, and the reason this takes the HIGHEST rather than the
        lowest: the PDK's own MOS gencell brings drain, source and gate up to
        metal2 through a stack of via1 cuts. Reading the terminal as metal1
        and painting a fresh via1 pad on top of those cuts produced 1096
        `exact_overlap v1/m1` errors — "this layer can't abut or partially
        overlap between subcells" — for connections the gencell had already
        made. Connecting at the top of what is already there makes no via at
        all where none is needed."""
        levels = []
        for name, rects in sections.items():
            if not any(r[0] <= x <= r[2] and r[1] <= y <= r[3]
                       for r in rects):
                continue
            if layers is not None and layers.knows(name):
                lvl = layers.level(name)
                if lvl is not None:
                    levels.append(lvl)
                continue
            mm = _METAL_RE.match(name)
            if mm:
                levels.append(int(mm.group(1)))
            vm = _VIA_RE.match(name)
            if vm:
                levels.append(int(vm.group(1)) + 1)
        return max(levels) if levels else 1

    labels = []
    for lab in _gl.parse_rlabels(text):
        lab = dict(lab)
        lab["level"] = metal_level_at(lab["x"], lab["y"])
        labels.append(lab)

    xs, ys = [], []
    for rects in sections.values():
        for r in rects:
            xs += [r[0], r[2]]
            ys += [r[1], r[3]]
    bbox = (min(xs), min(ys), max(xs), max(ys)) if xs else (0, 0, 0, 0)
    fb = _FIXED_BBOX_RE.search(text)
    if fb:
        f = [int(_gl.to_lambda(int(v), scale)) for v in fb.groups()]
        bbox = (min(bbox[0], f[0]), min(bbox[1], f[1]),
                max(bbox[2], f[2]), max(bbox[3], f[3]))
    return {"labels": labels, "bbox": bbox, "sections": sections,
            "layers": layers}


def config_key(dev: dict) -> tuple:
    p = dev["pars"]
    return (dev["model"], p.get("w"), p.get("l"), int(p.get("m", 1) or 1))


def gencell_call(dev: dict, inst: str, facts: PdkFacts) -> str:
    """`magic::gencell <ns>::<model> <inst> ...`, passing ONLY the parameters
    this gencell declares. The namespace and the parameter list are the PDK's
    own, read from its `_defaults` proc."""
    rec = facts.gencells[dev["model"]]
    accepted = set(rec["params"])
    args = []
    for key in ("w", "l"):
        if key in accepted and dev["pars"].get(key) is not None:
            args += [key, _fmt(dev["pars"][key])]
    if "m" in accepted:
        args += ["m", str(int(dev["pars"].get("m", 1) or 1))]
    if "guard" in accepted:
        args += ["guard", "1"]
    return (f"magic::gencell {rec['namespace']}::{dev['model']} {inst} "
            + " ".join(args))


def _fmt(v: float) -> str:
    return f"{v:g}"


class MagicError(RuntimeError):
    pass


def magic_run(stage: Stage, magicrc: str, script: str, tag: str,
              marker: str, timeout: int = 3600) -> str:
    ok, err = stage.put_text(script, f"{tag}.tcl")
    if not ok:
        raise MagicError(f"cannot stage {tag}.tcl: {err}")
    rc, out, serr = stage.sh(
        f"cd {shlex.quote(stage.path or '.')} && "
        f"magic -dnull -noconsole -rcfile {shlex.quote(magicrc)} {tag}.tcl",
        timeout=timeout)
    blob = (out or "") + (serr or "")
    if marker not in blob:
        raise MagicError(f"magic did not reach {marker} (rc={rc}):\n"
                         f"{blob[-1800:]}")
    return blob


_LAMBDA_RE = re.compile(r"^A5SCALE (\d+) (\d+) (\d+)", re.M)


_USE_CELL_RE = re.compile(r"^use (\S+)\s+(\S+)\s*$", re.M)


def read_scale(blob: str) -> int:
    """Lambda per micron, from Magic's own answer.

    `box values` reports internal units and `tech lambda` reports the
    internal-to-lambda ratio, so the product of the two is the only place
    this program learns its working unit. There is no fallback: a scale this
    program cannot measure is ABSENT."""
    m = _LAMBDA_RE.search(blob)
    if not m:
        raise MagicError("magic did not report its own coordinate scale; "
                         "this emitter does not assume one")
    internal_per_1000um, la, lb = (int(m.group(1)), int(m.group(2)),
                                   int(m.group(3)))
    return (internal_per_1000um * la) // (lb * 1000)


def probe(stage: Stage, magicrc: str, devs: Sequence[dict], facts: PdkFacts
          ) -> Tuple[int, Dict[tuple, dict]]:
    """Pass 1. Generate every unique device configuration once, save the
    children, and read back their real geometry. Also asks Magic for its own
    lambda-per-micron, so no scale constant lives in this file.

    Returns (lambda_per_um, {config: cell record}). Each record carries the
    placement DELTA — the offset between the box position a gencell is
    invoked at and where the child actually lands — MEASURED from the probe
    block's own transforms rather than assumed."""
    layers = facts.layers
    order: List[tuple] = []
    seen = set()
    for dev in devs:
        k = config_key(dev)
        if k not in seen:
            seen.add(k)
            order.append(k)
    by_key = {config_key(d): d for d in devs}

    # The probe pitch is stated in microns so it does not need the scale the
    # same run is about to measure.
    pitch_um = 400
    lines = ["drc off",
             "cellname create a5probe", "load a5probe",
             "box 0um 0um 1000um 1000um",
             'puts "A5SCALE [lindex [box values] 2] [lindex [tech lambda] 0]'
             ' [lindex [tech lambda] 1]"']
    for i, key in enumerate(order):
        x = i * pitch_um
        lines.append(f"box {x}um 0um {x}um 0um")
        lines.append(gencell_call(by_key[key], f"p{i}", facts))
    lines += ["set cl [cellname list children a5probe]",
              "foreach c $cl { load $c ; save $c.mag }",
              "load a5probe", "save a5probe.mag",
              'puts "A5_PROBE_OK"', "quit -noprompt"]
    blob = magic_run(stage, magicrc, "\n".join(lines), "a5probe",
                     "A5_PROBE_OK")
    lam = read_scale(blob)

    host = Path(stage.host_tmp)
    ok, err = stage.get("a5probe.mag", host / "a5probe.mag")
    if not ok:
        raise MagicError(f"the probe block did not come back: {err}")
    ptext = (host / "a5probe.mag").read_text(errors="replace")
    # The probe block carries its OWN `magscale`, and whether Magic writes
    # one at all depends on the cells inside it — a block of MOS children
    # gets `magscale 1 2` and a block of capacitor children gets none. That
    # is the library's LAW #22 again, and reading the transforms raw made
    # every placement delta twice its true value, which put each device on
    # top of its neighbour.
    by_inst = _gl.parse_use_transforms(ptext)
    inst_cell = {inst: cell for cell, inst in _USE_CELL_RE.findall(ptext)}

    cells: Dict[tuple, dict] = {}
    for i, key in enumerate(order):
        if f"p{i}" not in by_inst or f"p{i}" not in inst_cell:
            raise MagicError(
                f"the PDK gencell for {key[0]} (w={key[1]} l={key[2]} "
                f"m={key[3]}) produced no cell in the probe block")
        tx, ty = by_inst[f"p{i}"]
        name = Path(inst_cell[f"p{i}"]).name
        dst = host / f"{name}.mag"
        ok, err = stage.get(f"{name}.mag", dst)
        if not ok:
            raise MagicError(f"gencell child {name}.mag did not come "
                             f"back: {err}")
        rec = parse_cell(dst.read_text(errors="replace"), layers)
        rec["cell"] = name
        rec["delta"] = (int(tx) - i * pitch_um * lam, int(ty))
        cells[key] = rec
    return lam, cells


# ──────────────────────────────────────────────────────────────────────
# 4. terminals — which drawn label answers to which netlist net
# ──────────────────────────────────────────────────────────────────────
def _base(name: str) -> str:
    """A gencell numbers the labels of a multi-finger device (`D0`, `D1`,
    ...); the finger index is not a terminal."""
    return re.sub(r"\d+$", "", name)


# The four SPICE MOS terminal letters, in SPICE's own terminal order. This is
# the SPICE/Magic device convention, not a chip, PDK or design fact: a
# subcircuit call `x<name> d g s b <model>` names them in this order and the
# gencell labels them with these letters.
_MOS_LETTERS = ("D", "G", "S", "B")

#: A terminal the gencell numbered — `R1`, `R2`, `C1`, `C2`. It is the
#: gencell saying "this one is in the sequence"; a label WITHOUT a number,
#: where every other label has one, is the terminal outside it. See
#: `terminal_map`.
_ORDINAL_TERMINAL_RE = re.compile(r"\d$")


def ring_layer_of(cell: dict) -> Optional[str]:
    """The layer the device's guard ring is drawn on, or None.

    A guard ring is the layer whose rectangles enclose the device: it spans
    (almost) the whole cell in BOTH axes and is drawn as several bars rather
    than one. Read from the gencell's own output, so this file never names a
    ring layer of any PDK."""
    bx1, by1, bx2, by2 = cell["bbox"]
    span_x, span_y = bx2 - bx1, by2 - by1
    if span_x <= 0 or span_y <= 0:
        return None
    best = None
    for layer, rects in cell["sections"].items():
        if len(rects) < 3:
            continue
        xs = [v for r in rects for v in (r[0], r[2])]
        ys = [v for r in rects for v in (r[1], r[3])]
        cover_x = (max(xs) - min(xs)) / span_x
        cover_y = (max(ys) - min(ys)) / span_y
        if cover_x >= 0.9 and cover_y >= 0.9:
            area = sum((r[2] - r[0]) * (r[3] - r[1]) for r in rects)
            # the ring is the ENCLOSING frame, so it covers the cell extent
            # while filling only a fraction of the cell area
            if area < 0.5 * span_x * span_y and (best is None
                                                 or area < best[1]):
                best = (layer, area)
    return best[0] if best else None


def terminal_map(dev: dict, cell: dict
                 ) -> Tuple[Dict[str, List[dict]], Optional[str], List[str]]:
    """({net: [labels]}, ring layer, unmapped netlist terminals).

    Two conventions, and both are read rather than assumed:

      * a device the PDK CLASSIFIES as a mosfet has its four terminals named
        by the SPICE MOS letters, matched by letter;
      * every other device's gencell emits its ports in the netlist's own
        terminal order, with the guard-ring terminal last — which is what the
        PDK's resistor and capacitor gencells were measured to do.

    WHICH LABEL IS THE TRAILING ONE, and the defect that rule had. It was
    found by asking `ring_layer_of` which layer the guard ring is on and
    taking the label sitting there. On this PDK's own gencell children that
    answer is NONE — the ring is inside a WELL rectangle wider than itself,
    so the ring fails the "encloses the cell" test it is judged by — and with
    no trailing label the netlist's terminals were zipped against the labels
    in the order the `.mag` happens to list them. The PDK's resistor lists
    them B, R1, R2 while SPICE calls it R1, R2, B, so every resistor's
    SUBSTRATE TAP was wired to a signal net and its two body terminals were
    each one position out.

    MEASURED on u_hawaii_adc (ihp-sg13g2, image 0.3.46). `xr1 vout vfb vss`
    mapped B->vout, R1->vfb, R2->vss, and `xr_bias vin nbias vss` mapped
    B->vin: the substrate is ONE node, so vin, vout, vfb and vss extracted
    as a single net carrying 20 device terminals — exactly |vin|+|vout|+|vss|
    of the source netlist — with a block-spanning substrate polygon on it.
    `ldo` extracted 6 nets and 10 devices for a netlist of 9 and 11, and the
    per-block LVS answered `mismatch`.

    So the trailing terminal is identified from the LABELS THEMSELVES, which
    is where the gencell already says it: a device whose terminals are named
    with an ORDINAL (`R1`, `R2`, `C1`, `C2`) and which has exactly ONE label
    without one has named that odd label as the terminal outside the
    sequence, and SPICE puts it last. A gencell whose labels are all ordinal
    (the capacitor's `C1`/`C2`) has no such label and is unchanged; a device
    whose ring `ring_layer_of` DOES find is unchanged; a mosfet never reaches
    here. After it: `ldo` extracts 9 nets and 11 devices and the LVS says
    `match`; `delta_sigma` goes 119 nets -> 122 for a netlist of 122, with
    294 devices on both sides and no merged net left.
    """
    ring = ring_layer_of(cell)
    labels = cell["labels"]
    nets = dev["nets"]
    out: Dict[str, List[dict]] = {}
    unmapped: List[str] = []

    if dev.get("class") == "mosfet" and len(nets) >= 4:
        for letter, net in zip(_MOS_LETTERS, nets):
            hits = [l for l in labels if _base(l["name"]) == letter]
            if hits:
                out.setdefault(net, []).extend(hits)
            else:
                unmapped.append(f"{letter}->{net}")
        return out, ring, unmapped

    ring_labels = [l for l in labels if ring and l["layer"] == ring]
    if not ring_labels:
        odd = [l for l in labels if not _ORDINAL_TERMINAL_RE.search(l["name"])]
        if len(odd) == 1 and len(labels) == len(nets) > 1:
            ring_labels = odd
    rest = [l for l in labels if l not in ring_labels]
    order = list(nets)
    if ring_labels and len(order) == len(rest) + 1:
        out.setdefault(order[-1], []).extend(ring_labels)
        order = order[:-1]
    for net, lab in zip(order, rest):
        out.setdefault(net, []).append(lab)
    for net in order[len(rest):]:
        unmapped.append(f"?->{net}")
    return out, ring, unmapped


# ──────────────────────────────────────────────────────────────────────
# 5. the bulk tap — I3, the search that must cover the whole structure
# ──────────────────────────────────────────────────────────────────────
def choose_tap(ring_rects: Sequence[Tuple[int, int, int, int]],
               others: Sequence[Tuple[int, int, int, int]],
               forbidden_rows: Sequence[Tuple[int, int]],
               pad_half: int) -> Optional[Tuple[int, int, int, bool]]:
    """(x, y, centre-to-centre clearance, row_constraint_met) — where on the
    guard ring to put the bulk tap.

    THE ROUND-20 DEFECT, and why this looks the way it does. The generator
    that failed searched in ONE direction — up from the bulk label — and on a
    narrow device that label sits at the BOTTOM of the ring leg, so two
    thirds of the leg was never examined. It then stepped in a 25-lambda
    stride anchored on that same label, and missed the one legal band by ONE
    lambda. Both are quantisation, not rules.

    So every bar of the ring is a candidate structure, the scan walks its
    full extent on the PDK's own grid (one lambda), and the position taken is
    the one of MAXIMUM clearance — never the first that clears a threshold,
    because a first-hit search cannot report how much room the structure
    actually had.

    `forbidden_rows` are the height bands the device's other terminals will
    escape through. A tap that lands inside one is legal against the tap
    clearance floor and still unroutable, so the scan prefers a position
    outside them; when the ring offers none it takes the best position
    anyway and says so, rather than refusing a device the PDK permits.

    The clearance returned is CENTRE-TO-CENTRE, which is what the limits
    program's floor (`m1_space + tap_pad_half + terminal_pad_half`) measures.
    """
    def scan(respect_rows: bool) -> Optional[Tuple[int, int, int]]:
        best: Optional[Tuple[int, int, int]] = None
        for (rx1, ry1, rx2, ry2) in ring_rects:
            vertical = (ry2 - ry1) >= (rx2 - rx1)
            cx, cy = (rx1 + rx2) // 2, (ry1 + ry2) // 2
            lo, hi = (ry1, ry2) if vertical else (rx1, rx2)
            # the pad must sit ON the bar, so its centre stays a pad-half in
            lo, hi = lo + pad_half, hi - pad_half
            if lo > hi:
                continue
            for pos in range(lo, hi + 1):
                x, y = (cx, pos) if vertical else (pos, cy)
                if respect_rows and any(r0 <= y <= r1
                                        for r0, r1 in forbidden_rows):
                    continue
                pad = (x - pad_half, y - pad_half, x + pad_half, y + pad_half)
                clear = min((box_separation(pad, o) + 2 * pad_half
                             for o in others), default=10 ** 9)
                if best is None or clear > best[2]:
                    best = (x, y, clear)
        return best

    hit = scan(True)
    if hit is not None:
        return hit[0], hit[1], hit[2], True
    hit = scan(False)
    if hit is None:
        return None
    return hit[0], hit[1], hit[2], False


def box_separation(a: Tuple[int, int, int, int],
                   b: Tuple[int, int, int, int]) -> int:
    """Separation between two rectangles, 0 when they touch or overlap.

    `max(dx, dy)` is deliberately CONSERVATIVE: it never exceeds the true
    corner-to-corner distance, so a clearance this program reports as short
    is never long in the deck. Reporting more shortfalls than the deck will
    is the safe direction for a producer that does not grade."""
    dx = max(b[0] - a[2], a[0] - b[2], 0)
    dy = max(b[1] - a[3], a[1] - b[3], 0)
    return max(dx, dy)


# ──────────────────────────────────────────────────────────────────────
# 5b. the routing geometry — every number the deck states, in lambda
# ──────────────────────────────────────────────────────────────────────
class Geo:
    """What the routing may be, per layer, resolved to lambda.

    The PDK does not state a routing WIRE WIDTH or a VIA PAD SIZE: those are
    the generator's style, which is why the limits program takes the pad
    half-height as an argument. Everything else — the minimum width a metal
    may be, the spacing it needs, the metal a via must be enclosed by, the
    area a metal island must have — the deck states, and every one of those is
    read here rather than chosen.

    A rule the deck does not state is ABSENT, not defaulted: the Metal1
    spacing the limits program already derives is the only fallback, and it
    is used only where the deck is silent."""

    def __init__(self, rules: dict, m1_space_um: float, lam: int,
                 wire_w_um: float, pad_half_um: float) -> None:
        self.lam = lam
        self.rules = rules
        self._fallback_space = m1_space_um

        def L(um: float) -> int:
            """A deck MINIMUM in lambda, always rounded UP.

            MEASURED: `round()` here turns the deck's 0.045 um via surround
            into 4 lambda on a 100-lambda/um grid — Python rounds 4.5 to the
            even 4 — and 4 lambda is 0.04 um, which is under the rule. That
            single half-lambda produced 1436 `metal overlap of via` errors on
            an 11-device block. A minimum is never rounded down."""
            return max(1, int(math.ceil(um * lam - 1e-9)))

        self.space = {n: L(v) for n, v in rules["metal_space_um"].items()}
        self.default_space = L(m1_space_um)
        self.wire = {}
        for n in (1, 2, 3, 4, 5, 6, 7):
            need = rules["metal_width_um"].get(n, 0.0)
            self.wire[n] = max(L(wire_w_um), L(need) if need else 1)
        self.via_pad = {}
        self.patch = {}
        self.short_half: Dict[int, int] = {}
        self.long_half: Dict[int, int] = {}
        self.enc_half: Dict[int, int] = {}
        self.via_pad_min: Dict[int, int] = {}
        self.area_lam2: Dict[int, int] = {}
        for k in range(1, 8):
            side = max(2 * pad_half_um, rules["via_width_um"].get(k, 0.0))
            half = max(1, int(round(side * lam / 2)))
            self.via_pad[k] = half
            enc = max(rules["via_surround_um"].get((k, k), 0.0),
                      rules["via_surround_um"].get((k, k + 1), 0.0))
            enc_dir = max(rules.get("via_surround_dir_um", {}).get((k, k), 0.0),
                          rules.get("via_surround_dir_um", {}).get((k, k + 1),
                                                                   0.0))
            area = max(rules["metal_area_um2"].get(k, 0.0),
                       rules["metal_area_um2"].get(k + 1, 0.0))
            # A via island must clear the cut by the surround the deck
            # demands AND be large enough for the minimum-area rule, because
            # an island connected to nothing else is its own area region.
            #
            # THE TWO SURROUNDS ARE NOT ONE. This PDK states an ALL-AROUND
            # surround of 0.005 um and a DIRECTIONAL one of 0.045 um, and
            # `deck_rules` now hands them over separately. Applying the
            # directional distance on every side is not caution: it is a
            # different rule, nine times the stated all-around one, and it
            # is what made every island a 0.4 um square. MEASURED on
            # ihp-sg13g2: the square is wider than the 0.16 um terminal
            # metal a device gencell offers, so it overhangs into the
            # 0.185 um gap the gencell leaves above that terminal, and the
            # sign-off deck answers M1.b / M2.b / V1.b — 2242 of them across
            # two blocks, every one of them this island's own edge.
            #
            # So the island is ANISOTROPIC by construction: the all-around
            # surround on the SHORT axis, the directional one on the LONG
            # axis, and the minimum area met by lengthening the long axis
            # rather than by growing both. Which axis is long is decided per
            # site, by where the neighbouring geometry leaves room.
            # At least ONE lambda of metal past the cut on every side even
            # where the deck states no all-around surround at all: a metal
            # island exactly the size of the cut it covers is a drawing this
            # generator will not make, and saying so here is cheaper than a
            # rule nobody wrote down. It is the generator's choice, like the
            # wire width, and it is recorded with the rest of them.
            short = half + max(L(enc) if enc else 0, 1)
            long_by_enc = half + (L(enc_dir) if enc_dir else 0)
            # one lambda of margin on the area island: the rule is an
            # inequality on a quantised grid, and a patch drawn at exactly
            # the minimum has nowhere to lose a half-lambda
            long_by_area = (int(math.ceil(area * lam * lam
                                          / (4.0 * short))) + 1
                            if area else 0)
            self.short_half[k] = short
            self.long_half[k] = max(long_by_enc, long_by_area, short)
            self.enc_half[k] = max(long_by_enc, short)
            # The painted via is the GENERATOR's size; the deck's own via
            # width is the FLOOR. Where the preferred pad leaves no legal
            # island, the floor is what the deck actually asks for, and
            # falling back to it is reading the deck rather than overruling
            # it. Recorded per site in the provenance when it is used.
            floor = max(1, int(math.ceil(
                rules["via_width_um"].get(k, 0.0) * lam / 2 - 1e-9))) \
                if rules["via_width_um"].get(k) else half
            self.via_pad_min[k] = min(half, floor)
            self.area_lam2[k] = int(round(
                rules["metal_area_um2"].get(k, 0.0) * lam * lam))
            # `patch` stays the widest half this generator can paint at a
            # via, because `pitch()` sizes its corridors from it.
            self.patch[k] = self.long_half[k]

    def metal_space(self, layer: str) -> int:
        m = _METAL_RE.match(layer) or _VIA_RE.match(layer)
        if m:
            n = int(m.group(1))
            if _VIA_RE.match(layer) and not _METAL_RE.match(layer):
                return self.rules_via_space(n)
            return self.space.get(n, self.default_space)
        return self.default_space

    def rules_via_space(self, k: int) -> int:
        um = self.rules["via_space_um"].get(k)
        return (max(1, int(round(um * self.lam))) if um
                else self.default_space)

    def pitch(self) -> int:
        """Centre-to-centre spacing for parallel routing: the widest thing
        this generator paints plus the widest spacing any routed layer asks
        for. One number, deliberately, so the corridor arithmetic stays
        readable — and it is the MAXIMUM, so it is never short."""
        widest = max(list(self.wire.values())
                     + [2 * v for v in self.patch.values()])
        return widest + max(list(self.space.values())
                            + [self.default_space])


# ──────────────────────────────────────────────────────────────────────
# 6. the plan — placement, straps, escape lanes, rails
# ──────────────────────────────────────────────────────────────────────
# All coordinates below are in LAMBDA, the unit Magic's own `box`/`paint`
# commands take, and the scale that turns microns into it was measured from
# Magic in the probe pass.
class Plan:
    """Everything the layout pass will paint, and every shortfall it found.

    The routing style is deliberately simple and deliberately EXPLICIT about
    what makes it correct, because a producer that cannot say why its wires
    do not touch is a producer nobody can audit:

      * every device sits in ONE row, so each occupies its own x interval;
      * the terminals of one net at one height are strapped together on
        metal2 at a height just above or just below that row of contacts —
        two nets sharing a contact row take OPPOSITE sides, which is what
        keeps an interleaved multi-finger device's drain strap clear of its
        source stubs;
      * each strap escapes sideways on metal3 into the corridor between two
        devices and drops to its net's metal2 rail below the row. Lanes in a
        corridor are handed out in order of the height they come from, so an
        escape never crosses the lane of an escape that started lower;
      * the rails are one metal2 track per net, below every device.

    Everything the plan cannot make clear it MEASURES and records as a
    deviation. It never adjusts a floor to make itself pass."""

    def __init__(self) -> None:
        self.shapes: List[dict] = []      # {net, layer, box}
        self.sites: Optional["Sites"] = None
        self.tcl: List[str] = []
        self.deviations: List[dict] = []
        self.ports: List[Tuple[str, int, int]] = []
        self.port_nets: List[str] = []
        self.row_base = 0
        # the gencells' OWN geometry, placed. The emitter does not draw it
        # and cannot change it, but its routing runs beside it, and a
        # clearance record that cannot see the thing the routing is closest
        # to is not a record.
        self.device_shapes: List[dict] = []

    def paint(self, net: str, layer: str, x1: int, y1: int, x2: int, y2: int
              ) -> None:
        x1, x2 = min(x1, x2), max(x1, x2)
        y1, y2 = min(y1, y2), max(y1, y2)
        row = {"net": net, "layer": layer, "box": (x1, y1, x2, y2)}
        self.shapes.append(row)
        if self.sites is not None:
            self.sites.add(row)
        self.tcl.append(f"box {x1} {y1} {x2} {y2}")
        self.tcl.append(f"paint {layer}")

    def deviate(self, dev: dict, quantity: str, required, achieved,
                detail: str = "") -> None:
        """I4 — a shortfall is a STRUCTURED record, never prose and never a
        verdict. The floor is this emitter's prediction; the adjudicator
        named here is the one that actually grades the geometry."""
        rec = {
            "device": dev.get("name"), "model": dev.get("model"),
            "w": dev.get("pars", {}).get("w"),
            "l": dev.get("pars", {}).get("l"),
            "quantity": quantity, "required": required, "achieved": achieved,
            "shortfall": (round(required - achieved, 6)
                          if isinstance(required, (int, float))
                          and isinstance(achieved, (int, float)) else None),
            "adjudicator": ADJUDICATOR,
        }
        if detail:
            rec["detail"] = detail
        self.deviations.append(rec)


_CONTACT_SECTION = re.compile(r"cont|c$")


def carried_planes(section: str,
                   layers: Optional["_lim.LayerIdentity"] = None
                   ) -> List[str]:
    """Which CONDUCTOR planes a gencell section's tiles actually occupy.

    In Magic a contact type IS its two conductors plus the cut, so the metal
    a contact carries is NOT in the metal section — the tiles there stop at
    the contact's edge, and the GDS the sign-off deck grades has metal
    everywhere the contact is. A reader that takes `<< metal2 >>` at face
    value is blind to every metal2 rectangle a via1 tile generates.
    `magic_gencell_layout_lib.implicit_metal_sections` measured the same law
    for metal1 (a `psubdiffcont` neighbour a metal1-only reader could not
    see, and 30 notch violations from not seeing it); this is that law
    applied to every level, from the section NAME, so no PDK layer is
    named here.

    MEASURED on delta_sigma, with the island placer already clearing every
    metal2 rectangle it could see: 80 M2.b violations left, all of them
    against device metal2 that exists only in the GDS a via1 tile writes.
    """
    if layers is not None and layers.knows(section):
        # THE PDK'S OWN ANSWER. A contact carries the planes of BOTH its
        # residues; a plain type carries its own. The heuristics below
        # reproduce this for a PDK that spells its conductors `metalN` /
        # `viaN` and get it WRONG for one that does not: on ihp-sg13g2 the
        # `mimcapcontact` a MiM capacitor's top plate is drawn on ends in
        # `cont`, so the guess below registered a metal6 plate as metal1
        # geometry — 960x960 lambda of conductor in the wrong place, and
        # the island placer could not see the plate it had to clear.
        return [section] + [p for p in layers.conductor_planes(section)
                            if p != section]
    out = [section]
    vm = _VIA_RE.match(section)
    if vm and not _METAL_RE.match(section):
        k = int(vm.group(1))
        out += [f"metal{k}", f"metal{k + 1}"]
    elif not _METAL_RE.match(section) and _CONTACT_SECTION.search(section):
        out.append("metal1")
    return out


def device_planes(cell: dict) -> Dict[str, List[Tuple[int, ...]]]:
    """The gencell's geometry as the DECK will see it: one entry per
    conductor plane, with every contact's implied metal folded in."""
    planes: Dict[str, List[Tuple[int, ...]]] = {}
    for section, rects in cell["sections"].items():
        for layer in carried_planes(section, cell.get("layers")):
            if not (_METAL_RE.match(layer) or _VIA_RE.match(layer)):
                continue
            planes.setdefault(layer, []).extend(rects)
    return planes


def _linked(a: str, b: str) -> bool:
    """Two layers a current can cross between: the same metal, the same via,
    or a via and either metal it joins. Derived from the layer NAMES, so a
    PDK with more or fewer levels needs no entry anywhere."""
    if a == b:
        return True
    va, vb = _VIA_RE.match(a), _VIA_RE.match(b)
    ma, mb = _METAL_RE.match(a), _METAL_RE.match(b)
    if va and mb and not _VIA_RE.match(b):
        k = int(va.group(1))
        return int(mb.group(1)) in (k, k + 1)
    if vb and ma and not _VIA_RE.match(a):
        k = int(vb.group(1))
        return int(ma.group(1)) in (k, k + 1)
    return False


def cell_components(cell: dict) -> Dict[Tuple[str, int], int]:
    """Two ids per rectangle: (conductor, same-layer polygon).

    Union-find over the cell's metal and via rectangles: two that touch or
    overlap on electrically linked layers are the same conductor. Magic
    writes a conductor as a TILE DECOMPOSITION, so a terminal's metal is
    many abutting rectangles and a scan that treats each rectangle as its
    own obstacle would call a terminal's own metal foreign to itself."""
    items: List[Tuple[str, int, Tuple[int, ...]]] = []
    for layer, rects in sorted(device_planes(cell).items()):
        for j, r in enumerate(rects):
            items.append((layer, j, tuple(r)))
    parent = list(range(len(items)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(items)):
        la, _ja, ra = items[i]
        for j in range(i + 1, len(items)):
            lb, _jb, rb = items[j]
            if not _linked(la, lb):
                continue
            if ra[0] > rb[2] or rb[0] > ra[2] or ra[1] > rb[3] or rb[1] > ra[3]:
                continue
            a, b = find(i), find(j)
            if a != b:
                parent[a] = b
    # A SECOND partition, on ONE layer at a time. The first says what is
    # electrically the same conductor; this one says what MERGES INTO ONE
    # POLYGON on the layer the deck is grading. They are not the same
    # question and the deck only ever asks the second: two rectangles of one
    # conductor that meet only through a via are still two polygons on the
    # metal between them, and the spacing rule applies between them exactly
    # as it does between strangers. Exempting a whole conductor from spacing
    # because the island touched it SOMEWHERE is how an island lands two
    # lambda from its own terminal's other metal and the deck answers M2.b.
    lparent = list(range(len(items)))

    def lfind(i: int) -> int:
        while lparent[i] != i:
            lparent[i] = lparent[lparent[i]]
            i = lparent[i]
        return i

    for i in range(len(items)):
        la, _ja, ra = items[i]
        for j in range(i + 1, len(items)):
            lb, _jb, rb = items[j]
            if la != lb:
                continue
            if ra[0] > rb[2] or rb[0] > ra[2] or ra[1] > rb[3] or rb[1] > ra[3]:
                continue
            a, b = lfind(i), lfind(j)
            if a != b:
                lparent[a] = b

    return {(la, ja): (find(i), lfind(i))
            for i, (la, ja, _r) in enumerate(items)}


def friendly_conductor(rows: Sequence[dict], layer: str, x: int, y: int,
                       reach: int = 0):
    """Which conductor a terminal at (x, y) belongs to.

    The label's own layer first, by containment; then, because a gencell may
    put a label on a contact layer whose metal begins a lambda away, the
    NEAREST conductor on that layer within `reach`. None when neither
    answers — and None means "no conductor claimed here", which the caller
    treats as "clear everything", never as "clear nothing"."""
    best = None
    for r in rows:
        if r["layer"] != layer:
            continue
        b = r["box"]
        if b[0] <= x <= b[2] and b[1] <= y <= b[3]:
            return r.get("comp")
        if reach:
            dx = max(b[0] - x, x - b[2], 0)
            dy = max(b[1] - y, y - b[3], 0)
            d = max(dx, dy)
            if d <= reach and (best is None or d < best[0]):
                best = (d, r.get("comp"))
    return best[1] if best else None


# ── where a via island may stand ────────────────────────────────────────
#
# THE DEFECT THIS CLOSES, MEASURED (ihp-sg13g2, u_hawaii_adc, image 0.3.46,
# the PDK's own KLayout sign-off deck, 560 rules graded):
#
#   delta_sigma  2780 violations   M2.b 1504  M3.b 654  V1.b 326  M1.b 296
#   ldo           264 violations   M2.b  210  V1.b  42  M1.b  12
#
# and, with the flow's own top-level paint stripped and the gencells left
# exactly where this emitter placed them, the SAME deck on the SAME
# placement reports ZERO. Not one violation on either block is the PDK's
# gencell or this emitter's placement of it; every one is this emitter's
# own paint, and every one is a MINIMUM-SPACING rule on a layer it routes
# on. Of the 2242 that involve a device, every single one has a via island
# as one of its two edges.
#
# The cause is that the island was drawn as a fixed square centred on the
# terminal label, with nothing consulted about what the label sits next to.
# A gencell hands over a terminal on a metal strip 0.16 um tall and leaves
# 0.185 um of legal space above it; a 0.4 um square centred on that strip
# overhangs 0.12 um into the gap at both ends. The emitter already HELD the
# geometry it needed — `Plan.device_shapes` is built before a single wire is
# drawn — and used it only to write the shortfall down afterwards.
#
# So the island is placed, not assumed: this index answers "may a box of
# this size stand here?" for the device geometry, and the search below takes
# the nearest position to the terminal where the answer is yes.
class Sites:
    """The device geometry an island must clear, indexed by layer and cell.

    A device is not ONE obstacle. It is one obstacle per CONDUCTOR, and the
    conductor the terminal sits on is the one the island must OVERLAP
    rather than clear — otherwise the only legal position for a terminal's
    island is off its own terminal. Conductors are found by union-find over
    the gencell's own rectangles on electrically linked layers, so nothing
    here names a device, a net or a PDK.
    """

    CELL = 400            # lambda per bucket side

    def __init__(self, rows: Sequence[dict], geo: Geo) -> None:
        self.geo = geo
        self.grid: Dict[tuple, List[dict]] = {}
        for r in rows:
            self.add(r)

    def add(self, r: dict) -> None:
        """Index one more rectangle. The emitter's OWN paint goes in here as
        it is drawn: an island placed clear of every device and into the
        island of the terminal next door has not been placed either, and
        that is what a wider island makes possible where a narrower one
        could not reach."""
        b = r["box"]
        for gx in range(b[0] // self.CELL, b[2] // self.CELL + 1):
            for gy in range(b[1] // self.CELL, b[3] // self.CELL + 1):
                self.grid.setdefault((r["layer"], gx, gy), []).append(r)

    def near(self, layer: str, box: Sequence[int], m: int) -> List[dict]:
        out: List[dict] = []
        seen: set = set()
        for gx in range((box[0] - m) // self.CELL, (box[2] + m) // self.CELL + 1):
            for gy in range((box[1] - m) // self.CELL,
                            (box[3] + m) // self.CELL + 1):
                for r in self.grid.get((layer, gx, gy), ()):
                    if id(r) not in seen:
                        seen.add(id(r))
                        out.append(r)
        return out

    def clear(self, box: Sequence[int], layers: Sequence[str],
              friendly, net: Optional[str] = None) -> bool:
        """True when a box on `layers` keeps the deck's space from every
        conductor but `friendly`, and touches none of them.

        The test is per-axis (`dx < s and dy < s`), which is the CONSERVATIVE
        reading of a Euclidean spacing rule: every pair the deck would call a
        violation is rejected here, and a few diagonal pairs it would allow
        are rejected too. Refusing a legal position costs a lambda of travel;
        accepting an illegal one costs a violation."""
        for layer in layers:
            s = self.geo.metal_space(layer)
            rows = self.near(layer, box, s)
            merged = set()
            for r in rows:
                if "lcomp" not in r:
                    continue
                b = r["box"]
                if b[0] <= box[2] and box[0] <= b[2] \
                        and b[1] <= box[3] and box[1] <= b[3]:
                    merged.add(r["lcomp"])
            for r in rows:
                if "lcomp" not in r:
                    # this emitter's own paint. One conductor is one net
                    # here, so a same-net rectangle is skipped and every
                    # other one is an obstacle like any device's.
                    if net is not None and r["net"] == net:
                        continue
                    b = r["box"]
                    dx = max(b[0] - box[2], box[0] - b[2], 0)
                    dy = max(b[1] - box[3], box[1] - b[3], 0)
                    if dx < s and dy < s:
                        return False
                    continue
                if r["lcomp"] in merged:
                    # one polygon with this island: no spacing rule applies
                    # between the parts of a single polygon — but a polygon
                    # this island has no business joining is a SHORT.
                    if friendly is None or r.get("comp") != friendly:
                        return False
                    continue
                b = r["box"]
                dx = max(b[0] - box[2], box[0] - b[2], 0)
                dy = max(b[1] - box[3], box[1] - b[3], 0)
                if dx < s and dy < s:
                    return False
        return True

    def touches(self, box: Sequence[int], layer: str, friendly) -> bool:
        """True when the box actually OVERLAPS the conductor it is there to
        connect to. A stack that clears everything by moving off its own
        terminal has not been placed; it has been lost."""
        if friendly is None:
            return True
        for r in self.near(layer, box, 0):
            if "lcomp" not in r or r.get("comp") != friendly:
                continue
            if (r["box"][0] < box[2] and box[0] < r["box"][2]
                    and r["box"][1] < box[3] and box[1] < r["box"][3]):
                return True
        return False


#: How far from its terminal an island may be moved before this emitter
#: stops looking. A stack that needs more than this is reported as a
#: deviation and DRAWN where it was asked for — the deck adjudicates.
ISLAND_SEARCH_LAMBDA = 120

#: The plane this generator runs its lanes and rails on. A terminal handed
#: over ABOVE it has to come down, and where it comes down is the question
#: `build_plan` answers.
ROUTE_LEVEL = 3


def _island_candidates(span: int):
    """Displacements, nearest first: along one axis, then the other, then
    the Manhattan rings. The one-axis passes come first because a terminal
    on a gencell's metal strip has room along that strip and none across
    it, and finding that with two scans instead of a ring saves the search
    from being quadratic in the span for the common case."""
    yield (0, 0)
    for d in range(1, span + 1):
        yield (0, -d)
        yield (0, d)
    for d in range(1, span + 1):
        yield (-d, 0)
        yield (d, 0)
    for r in range(2, span // 4 + 1):
        for dx in range(-r, r + 1):
            rest = r - abs(dx)
            if rest == 0 or dx == 0:
                continue
            yield (dx, rest)
            yield (dx, -rest)


def _via_stack(plan: Plan, net: str, x: int, y: int, level: int, geo: Geo,
               top: int = 3, sites: Optional["Sites"] = None,
               friendly=None, dev: Optional[dict] = None) -> Tuple[int, int]:
    """Carry a terminal from the metal the gencell delivered it on to the
    routing layer, and give every cut the metal the deck demands around it.

    Magic paints a via type as the two metals it joins plus the cut, so the
    stack between any two levels is just the vias between them — in either
    direction, which is how a terminal that lands ABOVE the routing layer
    comes down to it without this file naming the device that put it there.
    The enclosing metal is painted explicitly because the cut alone does not
    satisfy `surround`, and it is sized to the deck's surround AND
    minimum-area rules, both read from the deck.

    The island is ANISOTROPIC (`Geo.short_half` / `Geo.long_half`) and it is
    PLACED: when a `Sites` index is supplied, both orientations are tried at
    the nearest displacement that clears every foreign conductor and still
    overlaps the terminal's own. When no such position exists the island is
    drawn where it was asked for and a deviation is written — this emitter
    records shortfalls, it does not refuse to draw.

    Returns the centre the stack was actually placed at, so the wire that
    leaves it starts where it is rather than where it was asked for."""
    lo, hi = min(level, top), max(level, top)
    if lo == hi:
        return x, y
    metals = list(range(lo, hi + 1))
    vias = list(range(lo, hi))
    layers = [f"metal{k}" for k in metals] + [f"via{k}" for k in vias]
    term_layer = f"metal{level}"

    pad = max(geo.via_pad[k] for k in vias)
    pad_min = max(geo.via_pad_min[k] for k in vias)
    enc_short = max(geo.short_half[k] - geo.via_pad[k] for k in vias)
    enc_long = max(geo.enc_half[k] - geo.via_pad[k] for k in vias)

    # WHICH METAL OF THE STACK MUST CARRY THE MINIMUM AREA ON ITS OWN. The
    # rule is about a REGION, not about a rectangle, so an island that
    # merges into something bigger is not the region the rule grades:
    #   * the terminal metal merges with the conductor it lands on — that is
    #     what `touches` below is made to guarantee;
    #   * the top metal merges with the wire that leaves the stack, which is
    #     painted a few lines after this call and is never small;
    #   * a metal in BETWEEN merges with neither, so it is an island in the
    #     rule's own sense and must meet the area by itself.
    # Claiming the merge for the first two is not a waiver: if the merge does
    # not happen the deck says so, on the same layer, in the same run.
    inter = [k for k in metals if k not in (level, top)]
    area_full = max([geo.area_lam2.get(k, 0) for k in metals] or [0])
    area_min = max([geo.area_lam2.get(k, 0) for k in inter] or [0])

    def halves(p: int, area: int) -> Tuple[int, int]:
        hs = p + enc_short
        by_area = (int(math.ceil(area / (4.0 * hs))) + 1) if area else 0
        return hs, max(p + enc_long, by_area, hs)

    shapes: List[Tuple[int, int, int]] = []
    seen_shapes = set()
    ladder = [(pad, area_full)]
    if friendly is not None and area_min < area_full:
        ladder.append((pad, area_min))
    if pad_min < pad:
        ladder.append((pad_min, area_full))
        if friendly is not None and area_min < area_full:
            ladder.append((pad_min, area_min))
    for p, area in ladder:
        hs, hl = halves(p, area)
        for ax, ay in ((hl, hs), (hs, hl)):
            if (ax, ay, p) not in seen_shapes:
                seen_shapes.add((ax, ay, p))
                shapes.append((ax, ay, p))

    hx, hy, ph = shapes[0]
    cx, cy = x, y
    if sites is not None:
        placed = None
        for (ax, ay, p) in shapes:
            for (dx, dy) in _island_candidates(ISLAND_SEARCH_LAMBDA):
                box = (x + dx - ax, y + dy - ay, x + dx + ax, y + dy + ay)
                if not sites.clear(box, layers, friendly, net):
                    continue
                if not sites.touches(box, term_layer, friendly):
                    continue
                placed = (x + dx, y + dy, ax, ay, p)
                break
            if placed is not None:
                break
        if placed is None:
            plan.deviate(dev or {}, "via_island_clearance_lambda",
                         geo.metal_space(term_layer), 0,
                         f"no position within {ISLAND_SEARCH_LAMBDA} lambda "
                         f"of ({x}, {y}) hosts any of the "
                         f"{len(shapes)} island shapes this deck permits "
                         f"(smallest {2 * shapes[-1][0]}x{2 * shapes[-1][1]} "
                         f"lambda) clear of the neighbouring device geometry "
                         f"while still overlapping this terminal's own "
                         f"metal; DRAWN at the terminal and recorded, never "
                         f"moved off it")
        else:
            cx, cy, hx, hy, ph = placed

    for k in vias:
        plan.paint(net, f"metal{k}", cx - hx, cy - hy, cx + hx, cy + hy)
        plan.paint(net, f"metal{k + 1}", cx - hx, cy - hy, cx + hx, cy + hy)
        plan.paint(net, f"via{k}", cx - ph, cy - ph, cx + ph, cy + ph)
    return cx, cy


def build_plan(devs: Sequence[dict], ports: Sequence[str],
               cells: Dict[tuple, dict], facts: PdkFacts, geo: Geo,
               tap_clear: int) -> Plan:
    plan = Plan()
    pitch = geo.pitch()
    pad_half = geo.via_pad[1]
    m1_space = geo.default_space
    hw2 = max(geo.wire[2] // 2, 1)
    hw3 = max(geo.wire[3] // 2, 1)
    min_gap = 4 * pitch

    # ── nets and their rails ──────────────────────────────────────────
    nets: List[str] = []
    for net in list(ports) + [n for d in devs for n in d["nets"]]:
        if net not in nets:
            nets.append(net)
    rail_y = {net: pitch + i * pitch for i, net in enumerate(nets)}
    row_base = pitch * (len(nets) + 24)

    # ── per device: which terminals escape at which height, on which side ──
    per_dev: List[dict] = []
    for dev in devs:
        cell = cells[config_key(dev)]
        tmap, ring, unmapped = terminal_map(dev, cell)
        for term in unmapped:
            plan.deviate(dev, "terminal_mapped", 1, 0,
                         f"the gencell emitted no label for {term}; that "
                         f"netlist terminal is not connected in this layout")
        # a label sitting ON the ring layer is the bulk contact, identified
        # per LABEL and not per net: a device whose source and bulk share a
        # net (a diode-tied bias leg does) would otherwise lose its source
        # terminal along with its bulk one.
        ring_labels = [(n, l) for n, labs in tmap.items() for l in labs
                       if ring and l["layer"] == ring]
        plain = [(n, l) for n, labs in tmap.items() for l in labs
                 if not (ring and l["layer"] == ring)]

        groups: List[dict] = []
        by_ny: Dict[tuple, List[dict]] = {}
        for net, lab in plain:
            by_ny.setdefault((net, lab["y"]), []).append(lab)
        for (net, y), glabs in by_ny.items():
            groups.append({"net": net, "y": y, "labels": glabs,
                           "level": min(l["level"] for l in glabs)})

        # A group of ONE contact escapes at its own height. A group of SEVERAL
        # contacts on one row — the fingers of a multi-finger device — must
        # first be tied together, and the strap cannot sit on that row: the
        # other net's fingers are interleaved with it. So it is reserved a
        # height OUTSIDE the device, alternately below and above, one strap
        # per row of its own. Every stub then runs away from the shared
        # contact row in one direction only, which is what keeps a drain
        # strap clear of the source stubs it passes.
        bx1, by1, bx2, by2 = cell["bbox"]
        n_below = n_above = 0
        for g in sorted(groups, key=lambda g: (-len(g["labels"]), g["y"])):
            if len(g["labels"]) == 1:
                g["escape_y"] = g["y"]
                g["strapped"] = False
                continue
            g["strapped"] = True
            if n_below <= n_above:
                n_below += 1
                g["escape_y"] = by1 - n_below * pitch
            else:
                n_above += 1
                g["escape_y"] = by2 + n_above * pitch

        if ring_labels:
            others = [(l["x"] - pad_half, l["y"] - pad_half,
                       l["x"] + pad_half, l["y"] + pad_half)
                      for _, l in plain]
            rows = sorted({g["escape_y"] for g in groups})
            forbidden = [(y - pitch + 1, y + pitch - 1) for y in rows]
            best = choose_tap(cell["sections"].get(ring, []), others,
                              forbidden, pad_half)
            if best is None:
                # I5 — a structure that cannot host the connection at all is
                # REFUSED by name, with what was measured, not asserted.
                raise Refusal(
                    f"{dev['name']} ({dev['model']} "
                    f"w={dev['pars'].get('w')}u l={dev['pars'].get('l')}u): "
                    f"its guard ring on layer {ring} offers no position that "
                    f"can host a {2 * pad_half}-lambda bulk tap. The device "
                    f"is legal; the RING is too small to tap.")
            tx, ty, clear, rows_ok = best
            if clear < tap_clear:
                plan.deviate(dev, "bulk_tap_clearance_lambda", tap_clear,
                             clear,
                             f"the best position on the guard ring clears "
                             f"the nearest terminal by {clear} lambda "
                             f"centre-to-centre; the floor is Metal1 space "
                             f"{m1_space} + tap pad {pad_half} + terminal "
                             f"pad {pad_half}. DRAWN and recorded, never "
                             f"refused")
            if not rows_ok:
                plan.deviate(dev, "bulk_tap_row_separation_lambda", pitch, 0,
                             "every position on the guard ring lies in the "
                             "escape band of another terminal row; the tap "
                             "is drawn at the clearest of them")
            groups.append({"net": ring_labels[0][0], "y": ty,
                           "escape_y": ty, "strapped": False,
                           "labels": [{"x": tx, "y": ty, "level": 1,
                                       "name": "tap"}],
                           "level": 1})

        # two groups escaping at one height take opposite sides, so their
        # metal3 runs are on opposite sides of the device and never meet
        for y in sorted({g["escape_y"] for g in groups}):
            row = sorted([g for g in groups if g["escape_y"] == y],
                         key=lambda g: min(l["x"] for l in g["labels"]))
            for idx, g in enumerate(row):
                g["side"] = "left" if idx % 2 == 0 else "right"
                if idx >= 2:
                    plan.deviate(
                        dev, "escape_sides_available", 2, idx + 1,
                        f"{idx + 1} nets escape at height {y}; only two "
                        f"sides exist, so this group shares a side")

        # SAME SIDE, DIFFERENT HEIGHT IS NOT AUTOMATICALLY CLEAR. Opposite
        # sides were the only separation this plan had, and it was applied
        # only to groups at the SAME height. A group of one contact escapes
        # at its own label's height, and a gencell's label rows are on the
        # gencell's grid, not on this generator's: two nets whose contacts
        # sit 47 lambda apart both went left, and their escape wires ran
        # parallel 17 lambda apart against a 21 lambda rule.
        #
        # MEASURED on delta_sigma with the island placer already in: 246
        # M3.b and 125 M2.b left, every one of them two escapes of one
        # device on one side. So the heights on a side are SPREAD to the
        # pitch the deck's own width and spacing require, upward, in the
        # order they already had — an escape never crosses one that started
        # below it, which is the property the lane allocation below rests on.
        # THE WIRE IS NOT THE TALLEST THING AT AN ESCAPE HEIGHT. Spacing the
        # heights by wire-width-plus-space left exactly 20 lambda against a
        # 21 lambda rule wherever the neighbour was a via ISLAND rather than
        # a wire — the island is 48 lambda across its long axis, the wire is
        # 30, and the placer may point either axis along the escape. So the
        # pitch is built from the WIDEST thing this generator paints at a
        # height, which is the island's long side. Measured: the last 18
        # M3.b on delta_sigma, every one of them an island against the
        # escape one slot above it.
        esc_pitch = max(max(geo.wire[k], 2 * geo.long_half[k])
                        + geo.metal_space(f"metal{k}") for k in (2, 3))
        for side in ("left", "right"):
            prev = None
            for g in sorted([g for g in groups if g["side"] == side],
                            key=lambda g: g["escape_y"]):
                if prev is not None and g["escape_y"] - prev < esc_pitch:
                    g["escape_y"] = prev + esc_pitch
                prev = g["escape_y"]
        per_dev.append({"dev": dev, "cell": cell, "groups": groups,
                        "bbox": cell["bbox"]})

    # ── corridors wide enough for the lanes they must carry ───────────
    n_left = [sum(1 for g in d["groups"] if g["side"] == "left")
              for d in per_dev]
    n_right = [sum(1 for g in d["groups"] if g["side"] == "right")
               for d in per_dev]
    gap_w = []
    for i in range(len(per_dev) + 1):
        need = (n_right[i - 1] if i > 0 else 0) + \
               (n_left[i] if i < len(per_dev) else 0)
        gap_w.append(max(min_gap, (need + 2) * pitch))

    x = 0
    for i, d in enumerate(per_dev):
        x += gap_w[i]
        d["box_x"] = x
        d["gap_hi"] = x
        x += d["bbox"][2] - d["bbox"][0]
        d["right_lo"] = x

    # ── the layout pass, in the order Magic will execute it ───────────
    for i, d in enumerate(per_dev):
        plan.tcl.append(f"box {d['box_x']} {row_base} "
                        f"{d['box_x']} {row_base}")
        plan.tcl.append(gencell_call(d["dev"], f"d{i}", facts))
        d["origin"] = (d["box_x"] + d["cell"]["delta"][0],
                       row_base + d["cell"]["delta"][1])

    comp_cache: Dict[int, Dict[Tuple[str, int], int]] = {}
    for d in per_dev:
        ox, oy = d["origin"]
        cell = d["cell"]
        if id(cell) not in comp_cache:
            comp_cache[id(cell)] = cell_components(cell)
        comps = comp_cache[id(cell)]
        name = d["dev"]["name"]
        rows: List[dict] = []
        for layer, rects in sorted(device_planes(cell).items()):
            for j, r in enumerate(rects):
                c, lc = comps.get((layer, j), (-1, -1))
                rows.append(
                    {"net": f"<device {name}>", "layer": layer,
                     "comp": (name, c), "lcomp": (name, layer, lc),
                     "box": (ox + r[0], oy + r[1], ox + r[2], oy + r[3])})
        d["rows"] = rows
        plan.device_shapes.extend(rows)
        for g in d["groups"]:
            g["abs_labels"] = [(ox + l["x"], oy + l["y"], l["level"])
                               for l in g["labels"]]
            g["abs_escape_y"] = oy + g["escape_y"]

    # The index is built ONCE, after every device is placed and before a
    # single wire is drawn: the routing runs closest to the devices, and a
    # placer that cannot see them places into them.
    sites = Sites(plan.device_shapes, geo)
    plan.sites = sites

    # Lanes are handed out in order of the height they come from: the lane
    # nearest the device serves the LOWEST escape. An escape therefore never
    # crosses the lane of an escape that started below it, and the lane of an
    # escape that started above it stops short of this one's height.
    for d in per_dev:
        for side, base, step in (("right", d["right_lo"], 1),
                                 ("left", d["gap_hi"], -1)):
            gs = sorted([g for g in d["groups"] if g["side"] == side],
                        key=lambda g: g["abs_escape_y"])
            for k, g in enumerate(gs):
                g["lane_x"] = base + step * (k + 1) * pitch

    for d in per_dev:
        for g in d["groups"]:
            net, ey, lane = g["net"], g["abs_escape_y"], g["lane_x"]
            if g["strapped"]:
                # THE STUB STARTS WHERE THE STACK ENDED UP. An island that
                # was moved a lambda off its label and then wired from the
                # label is not connected to itself.
                xs = []
                for (lx, ly, level) in g["abs_labels"]:
                    fr = friendly_conductor(d["rows"], f"metal{level}", lx, ly,
                                            reach=geo.default_space)
                    cx, cy = _via_stack(plan, net, lx, ly, level, geo, top=2,
                                        sites=sites, friendly=fr,
                                        dev=d["dev"])
                    xs.append(cx)
                    plan.paint(net, "metal2", cx - hw2, min(cy, ey),
                               cx + hw2, max(cy, ey))
                plan.paint(net, "metal2", min(xs) - hw2, ey - hw2,
                           max(xs) + hw2, ey + hw2)
                joint = max(xs) if g["side"] == "right" else min(xs)
                _via_stack(plan, net, joint, ey, 2, geo, top=3, sites=sites)
            elif g["level"] > ROUTE_LEVEL:
                # THE TERMINAL IS DELIVERED ABOVE THE ROUTING LAYER, and
                # every plane between the two is the DEVICE'S OWN.
                #
                # MEASURED on u_hawaii_adc (ihp-sg13g2, image 0.3.46). A MiM
                # capacitor hands its top plate over on metal6 and its
                # bottom plate on metal5, and the bottom plate is one
                # rectangle covering the WHOLE device. A stack dropped at
                # the top-plate terminal to come down to metal3 therefore
                # paints this net's metal5 island directly onto the other
                # terminal's plate: the two plates become one conductor, the
                # capacitor is shorted, and the sign-off LVS answers
                # `mismatch`. The island placer cannot rescue it — the plate
                # is 1120 lambda across and no position within
                # `ISLAND_SEARCH_LAMBDA` of the terminal is off it. The same
                # descent puts a via4 on the plate, which this PDK's deck
                # forbids outright (`spacing mimcap via4/m5`, 8 of them on
                # `delta_sigma` under Magic).
                #
                # So a terminal delivered above the routing layer LEAVES on
                # its own plane first and comes down at its lane, which is
                # outside the device by construction. Nothing here names a
                # device, a layer or a PDK: the level is the one the PDK's
                # layer table reported for the type the label sits on, and a
                # terminal at or below the routing layer is untouched.
                lx, ly, level = g["abs_labels"][0]
                esc, ex, ey0 = level, lx, ly
                sect = g["labels"][0].get("layer", "")
                if facts.layers is not None \
                        and facts.layers.device_electrode_contact(sect) \
                        and (level + 1) in geo.wire:
                    # AND WHEN THE PLANE IT ARRIVES ON IS THE DEVICE'S OWN
                    # ELECTRODE, IT GOES UP ONE MORE BEFORE IT LEAVES.
                    #
                    # A contact IS its residues, so this terminal's metal
                    # has exactly the electrode's footprint; a wire on that
                    # plane taken out of the contact crosses the
                    # electrode's edge, and that is the geometry a PDK
                    # writes an electrode-spacing rule about. MEASURED on a
                    # two-cell fixture (the PDK's own gencell child plus one
                    # painted stub, magic `drc style drc(full)`): the child
                    # alone 0, the contact covered but not left 0, a stub
                    # from the contact's own edge 1, from the plate centre
                    # 1, over the whole plate 4 — and the contact-sized pad
                    # plus one via up plus a stub on the plane ABOVE, 0. The
                    # rule is `analog_a5_pdk_device_limits.LayerIdentity.
                    # device_electrode_contact` and it names no device.
                    esc = level + 1
                    fr = friendly_conductor(d["rows"], f"metal{level}",
                                            lx, ly, reach=geo.default_space)
                    ex, ey0 = _via_stack(plan, net, lx, ly, level, geo,
                                         top=esc, sites=sites, friendly=fr,
                                         dev=d["dev"])
                hwt = max(geo.wire[esc] // 2, 1)
                plan.paint(net, f"metal{esc}",
                           min(ex, lane) - hwt, ey0 - hwt,
                           max(ex, lane) + hwt, ey0 + hwt)
                cx, cy = _via_stack(plan, net, lane, ey0, esc, geo,
                                    top=ROUTE_LEVEL, sites=sites,
                                    dev=d["dev"])
                joint = cx
                if cy != ey:
                    plan.paint(net, "metal3", cx - hw3, min(cy, ey) - hw3,
                               cx + hw3, max(cy, ey) + hw3)
            else:
                lx, ly, level = g["abs_labels"][0]
                fr = friendly_conductor(d["rows"], f"metal{level}", lx, ly,
                                        reach=geo.default_space)
                cx, cy = _via_stack(plan, net, lx, ly, level, geo,
                                    top=ROUTE_LEVEL,
                                    sites=sites, friendly=fr, dev=d["dev"])
                joint = cx
                if cy != ey:
                    # a metal3 jog back to the escape height. Metal3 is the
                    # one routed layer no gencell in this PDK paints, so the
                    # jog is free of the geometry the island had to leave —
                    # and keeping the escape at its own height is what stops
                    # one moved island from re-ordering every lane.
                    plan.paint(net, "metal3", cx - hw3, min(cy, ey) - hw3,
                               cx + hw3, max(cy, ey) + hw3)
            # across to the lane on metal3, then straight down to the rail
            plan.paint(net, "metal3", min(joint, lane) - hw3, ey - hw3,
                       max(joint, lane) + hw3, ey + hw3)
            plan.paint(net, "metal3", lane - hw3, rail_y[net], lane + hw3, ey)
            _via_stack(plan, net, lane, rail_y[net], 2, geo, top=3,
                       sites=sites)

    # ── one metal2 rail per net, and a label on each declared port ──────
    for net in nets:
        xs = [g["lane_x"] for d in per_dev for g in d["groups"]
              if g["net"] == net]
        if not xs:
            continue
        ty = rail_y[net]
        plan.paint(net, "metal2", min(xs) - pitch, ty - hw2,
                   max(xs) + pitch, ty + hw2)
        plan.ports.append((net, min(xs), ty))

    plan.row_base = row_base
    plan.port_nets = [n for n in nets if n in ports]
    return plan


# ──────────────────────────────────────────────────────────────────────
# 7. what the plan actually achieved — measured on the plan, not asserted
# ──────────────────────────────────────────────────────────────────────
def _banded(manifest: Sequence[dict], margin: int) -> List[List[dict]]:
    """The manifest cut into overlapping vertical bands.

    The library's two geometry audits are exact and quadratic, which is the
    right shape for a wiring manifest and the wrong one for a manifest that
    also carries every rectangle of 256 placed devices. Banding preserves the
    audits' answer — two rectangles closer than `margin` share at least one
    band — and pays for it in memory instead of time. A shape wider than a
    band simply appears in each band it crosses, which is what a rail does."""
    if not manifest:
        return []
    lo = min(r["box"][0] for r in manifest)
    hi = max(r["box"][2] for r in manifest)
    width = max(margin * 8, 1)
    n = max(1, (hi - lo) // width + 1)
    bands: List[List[dict]] = [[] for _ in range(n)]
    for r in manifest:
        a = max(0, (int(r["box"][0]) - margin - lo) // width)
        b = min(n - 1, (int(r["box"][2]) + margin - lo) // width)
        for k in range(a, b + 1):
            bands[k].append(r)
    return [b for b in bands if len(b) > 1]


def clearance_deviations(plan: Plan, geo: Geo,
                         devs: Sequence[dict]) -> None:
    """Every clearance this emitter's own routing came up short on, recorded.

    This is I4 applied to the routing itself, and the two questions it asks
    are `magic_gencell_layout_lib`'s, not this file's:

      * `cross_net_overlaps` — is it SHORTED? Two different nets overlapping
        on electrically linked layers. Run over the routing manifest.
      * `cross_net_spacing_violations` — is it MANUFACTURABLE? Same-layer
        cross-net pairs closer than the deck's minimum space, touching and
        overlapping pairs excluded because those are the other audit's
        finding. Run over the routing manifest AND over the routing beside
        the gencells' own geometry, which is the neighbour the routing is
        actually closest to.

    MEASURED, and the reason the second manifest exists: comparing the
    routing only with itself reported ZERO deviations for a block whose
    sign-off deck found 1339 violations. Nearly all of them were between this
    emitter's metal and the device's. A record that cannot see the thing the
    routing runs closest to is not a record.

    The floors are the spacing rules the deck states PER LAYER, and the deck
    is named as the adjudicator in every record. This program never converts
    any of it into a verdict."""
    owner = {d["name"]: d for d in devs}
    anon = {"name": None, "model": None, "pars": {}}
    layers = {s["layer"] for s in plan.shapes}
    min_space = {ly: geo.metal_space(ly) for ly in layers}
    margin = max(list(min_space.values()) + [geo.default_space])

    seen = set()
    for band in _banded(plan.shapes, margin):
        for hit in _gl.cross_net_overlaps(band):
            key = ("short",) + tuple(map(str, hit))
            if key in seen:
                continue
            seen.add(key)
            na, la, ba, nb, _lb, bb = hit
            plan.deviate(owner.get(na, anon), f"{la}_cross_net_overlap",
                         0, 1,
                         f"nets {na} and {nb} overlap on electrically linked "
                         f"layers at {list(ba)} / {list(bb)}")
        for hit in _gl.cross_net_spacing_violations(band, min_space):
            na, nb, layer, gap, ba, bb = hit
            key = ("space",) + tuple(map(str, hit))
            if key in seen:
                continue
            seen.add(key)
            plan.deviate(owner.get(na, anon), f"{layer}_space_lambda",
                         min_space[layer], round(gap, 3),
                         f"nets {na} and {nb} are {gap:.3g} lambda apart on "
                         f"{layer} at {list(ba)} / {list(bb)}")

    # THE ROUTING BESIDE THE DEVICE. The device's own rectangles are entered
    # under a pseudo-net that no netlist net can spell, so the same cross-net
    # scan asks the question, and pairs of device rectangles are dropped
    # afterwards: what a PDK gencell draws is the PDK's business, and a bare
    # gencell was measured DRC-clean on its own.
    mixed = list(plan.shapes) + plan.device_shapes
    for band in _banded(mixed, margin):
        for hit in _gl.cross_net_spacing_violations(band, min_space):
            na, nb, layer, gap, ba, bb = hit
            dev_a, dev_b = na.startswith("<device "), nb.startswith("<device ")
            if dev_a == dev_b:
                continue          # routing/routing above, device/device not ours
            key = ("dev",) + tuple(map(str, hit))
            if key in seen:
                continue
            seen.add(key)
            who = (na if dev_a else nb)[len("<device "):-1]
            plan.deviate(owner.get(who, anon),
                         f"{layer}_space_to_device_lambda",
                         min_space[layer], round(gap, 3),
                         f"net {(nb if dev_a else na)} runs {gap:.3g} lambda "
                         f"from {who}'s own {layer} at {list(ba)} / "
                         f"{list(bb)}")

    # THE SHORT AUDIT, TRANSITIVE AND OVER THE DEVICES. See `net_shorts`.
    for short in net_shorts(plan):
        na, nb = short["nets"]
        chain = " -> ".join(
            f"{s['net']}:{s['layer']}{s['box']}" for s in short["path"]) \
            or "(no path recovered)"
        plan.deviate(anon, "routed_nets_per_conductor", 1, 2,
                     f"nets {na} and {nb} are ONE conductor in this layout: "
                     f"{chain}")


# ── the short audit, run TRANSITIVELY and over the devices too ──────────
#
# THE DEFECT THIS CLOSES, MEASURED. `clearance_deviations` above asks
# `cross_net_overlaps` "is it shorted?" — PAIRWISE, and over `plan.shapes`
# ONLY. Both halves of that are holes:
#
#   * a short does not need two of THIS emitter's rectangles to touch. It
#     needs a PATH. On u_hawaii_adc's `ldo` the path is three shapes long —
#     our metal5 island on `vg`, the MiM capacitor's own metal5 plate, our
#     metal5 island on `vout` — and no PAIR in it is two routing rectangles
#     of different nets, so the pairwise scan over the routing manifest saw
#     nothing and the producer reported a clean sheet.
#   * the deck's own LVS then reported `mismatch` on that block and on its
#     sibling, five schematic nets extracting as ONE, and nothing in the
#     flow could say why.
#
# The cause, once the path is printed, is one line of `parse_cell`:
# `metal_level_at` recognises a conductor only if its section is called
# `metalN` or `viaN`, and this PDK delivers a MiM capacitor's TOP plate on a
# section called `mimcapcontact`. Both of that device's terminal labels
# therefore read as the metal5 plane the BOTTOM plate occupies, and the
# emitter drops a via stack for each of them onto the same plate. The
# capacitor is shorted, and every net downstream of it collapses.
#
# This scan does not fix that. It makes the producer SAY it, in the record
# it owns, with the path — which is what I4 already requires of every other
# thing this emitter cannot make clear.
def net_shorts(plan: Plan, limit: int = 8) -> List[dict]:
    """Every pair of routed nets that share one conductor, with a WITNESS.

    Union-find over the routing manifest AND the placed gencells' own
    geometry, joined wherever two rectangles on electrically linked layers
    touch or overlap. A component carrying two routed nets is a short, and
    the shortest chain of rectangles between them is reported with it: a
    reader who is told "vg and vout are one net" and not WHERE has been told
    the symptom, which is what the sign-off LVS already said.
    """
    rows = [dict(r, _own=True) for r in plan.shapes] \
        + [dict(r, _own=False) for r in plan.device_shapes]
    if not rows:
        return []
    cell = max(64, geo_bucket(rows))
    grid: Dict[tuple, List[int]] = {}
    for i, r in enumerate(rows):
        b = r["box"]
        for gx in range(b[0] // cell, b[2] // cell + 1):
            for gy in range(b[1] // cell, b[3] // cell + 1):
                grid.setdefault((gx, gy), []).append(i)

    parent = list(range(len(rows)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    adj: Dict[int, List[int]] = {}
    for i, r in enumerate(rows):
        b = r["box"]
        seen: set = set()
        for gx in range(b[0] // cell, b[2] // cell + 1):
            for gy in range(b[1] // cell, b[3] // cell + 1):
                for j in grid.get((gx, gy), ()):
                    if j <= i or j in seen:
                        continue
                    seen.add(j)
                    o = rows[j]
                    if not _linked(r["layer"], o["layer"]):
                        continue
                    ob = o["box"]
                    if b[0] > ob[2] or ob[0] > b[2] \
                            or b[1] > ob[3] or ob[1] > b[3]:
                        continue
                    adj.setdefault(i, []).append(j)
                    adj.setdefault(j, []).append(i)
                    a, c = find(i), find(j)
                    if a != c:
                        parent[a] = c

    by_comp: Dict[int, Dict[str, List[int]]] = {}
    for i, r in enumerate(rows):
        if not r["_own"]:
            continue
        by_comp.setdefault(find(i), {}).setdefault(r["net"], []).append(i)

    out: List[dict] = []
    for comp, nets in sorted(by_comp.items()):
        if len(nets) < 2:
            continue
        order = sorted(nets)
        for k in range(1, len(order)):
            a, b_net = order[0], order[k]
            out.append({"nets": (a, b_net),
                        "path": _short_path(rows, adj, nets[a], set(nets[b_net]),
                                            limit)})
    return out


def geo_bucket(rows: Sequence[dict]) -> int:
    """A bucket side that keeps the neighbour lists short without making the
    grid itself the cost: the median rectangle's larger side, floored."""
    sides = sorted(max(r["box"][2] - r["box"][0], r["box"][3] - r["box"][1])
                   for r in rows)
    return max(1, sides[len(sides) // 2])


def _short_path(rows: Sequence[dict], adj: Dict[int, List[int]],
                src: Sequence[int], dst: set, limit: int) -> List[dict]:
    """The shortest chain of rectangles joining two nets, breadth-first."""
    prev: Dict[int, int] = {}
    seen = set(src)
    queue = list(src)
    hit = None
    while queue:
        u = queue.pop(0)
        if u in dst:
            hit = u
            break
        for v in adj.get(u, ()):
            if v in seen:
                continue
            seen.add(v)
            prev[v] = u
            queue.append(v)
    if hit is None:
        return []
    chain = [hit]
    while chain[-1] in prev:
        chain.append(prev[chain[-1]])
    chain.reverse()
    return [{"net": rows[i]["net"], "layer": rows[i]["layer"],
             "box": list(rows[i]["box"])} for i in chain[:limit]]


def layout_tcl(block: str, plan: Plan, out_dir: str) -> str:
    """The Magic script that draws the block, streams it, and says so.

    `LAYOUT_OK` is printed LAST: a run that dies mid-way prints no marker and
    this program reports the failure rather than a partial layout."""
    L = ["drc off", f"cellname create {block}", f"load {block}"]
    L += plan.tcl
    for net, x, y in plan.ports:
        L.append(f"box {x} {y} {x} {y}")
        L.append(f"label {net} FreeSans 40 0 0 0 c metal2")
        if net in plan.port_nets:
            L.append("port make")
    # Each gencell child is SAVED BY NAME rather than left to `writeall`: a
    # cell Magic generated has no filename of its own, so `writeall force`
    # silently writes none of them and `layout.mag` comes out naming children
    # that do not exist. That is what made the first version's layout
    # unreadable — and a layout Magic cannot load reports DRC 0.
    L += [f"load {block}",
          f"set a5kids [cellname list children {block}]",
          "foreach c $a5kids { load $c ; save $c.mag }",
          f"load {block}",
          f"gds write {shlex.quote(out_dir)}/{block}.gds",
          f"save {shlex.quote(out_dir)}/layout.mag",
          'puts "A5_LAYOUT_OK"', "quit -noprompt"]
    return "\n".join(L)


# ──────────────────────────────────────────────────────────────────────
# 8. the producer
# ──────────────────────────────────────────────────────────────────────
def emit_block(project: Path, block: str, stage: Stage, magicrc: str,
               facts: PdkFacts, args) -> Tuple[int, dict]:
    bdir = _pl.analog_dir(project) / block
    sp = bdir / f"{block}.sp"
    report: dict = {"producer": PRODUCER, "schema": SCHEMA, "block": block,
                    "netlist": str(sp)}
    if not sp.is_file():
        report["result"] = "NO_NETLIST"
        report["reason"] = (f"A3 has not produced {sp}; A5 draws the A3 "
                            f"netlist and nothing else")
        return RC_REFUSED, report

    # A REFUSAL DOES NOT ERASE AN EARLIER LAYOUT, and it must not be silent
    # about that. MEASURED on this program's own negative control: drawing a
    # legal device, then editing its width below the PDK minimum and
    # re-running, leaves the first run's `layout.mag` on disk — and the A5
    # gate reads geometry, not provenance, so it PASSes that layout for a
    # netlist the PDK forbids. Deleting someone else's artefact is not this
    # producer's call; saying so, in the record it owns, is.
    stale = bdir / "layout.mag" if (bdir / "layout.mag").is_file() else None
    if stale:
        report["layout_present_before_this_run"] = str(stale)

    def refuse(result: str, reason: str, rc: int) -> Tuple[int, dict]:
        report["result"] = result
        report["reason"] = reason
        if stale:
            report["stale_layout_warning"] = (
                f"{stale} is from an EARLIER run and this netlist was "
                f"refused; it was not produced from the netlist now on disk, "
                f"and nothing here deleted it")
        return rc, report

    try:
        blockname, ports, devs = parse_netlist(sp)
    except ValueError as exc:
        # a netlist this program cannot read is NAMED, like everything else it
        # cannot do — never a traceback out of a producer the runner calls
        return refuse("UNREADABLE_NETLIST", str(exc), RC_REFUSED)
    report["subckt"] = blockname
    report["ports"] = ports
    report["devices"] = len(devs)

    unknown = sorted({d["model"] for d in devs
                      if d["model"] not in facts.gencells})
    if unknown:
        return refuse(
            "NO_GENCELL",
            f"the PDK defines no gencell for {', '.join(unknown)} in "
            f"{facts.sources.get('gencell_tcl')} or its technology "
            f"directory; this emitter draws with the PDK's own gencells and "
            f"does not invent a device", RC_REFUSED)
    for d in devs:
        d["class"] = facts.gencells[d["model"]].get("class")

    # I2 — before any probe.
    bad = forbidden_geometries(devs, facts)
    if bad:
        report["refusals"] = bad
        return refuse("FORBIDDEN",
                      "the PDK forbids " + str(len(bad)) + " geometry(ies) in "
                      "this netlist; see `refusals`", RC_FORBIDDEN)

    limits_used = {}
    for model in sorted({d["model"] for d in devs}):
        lmin, wmin, src = facts.limits_for(model)
        limits_used[model] = {"lmin_um": lmin, "wmin_um": wmin,
                              "class": facts.gencells[model].get("class"),
                              "source": src}
    report["pdk_limits"] = limits_used
    report["pdk_sources"] = dict(facts.sources)
    report["m1_space_um"] = facts.m1_space_um

    lam, cells = probe(stage, magicrc, devs, facts)
    report["lambda_per_um"] = lam

    geo = Geo(facts.deck, facts.m1_space_um, lam,
              args.wire_width_um, args.via_pad_half_um)
    pad_half_um = geo.via_pad[1] / lam
    tap_clear_um = facts.m1_space_um + 2 * pad_half_um
    tap_clear = max(1, round(tap_clear_um * lam))
    report["deck_rules"] = {
        k: {str(a): b for a, b in sorted(v.items(), key=str)}
        for k, v in facts.deck.items()}
    report["generator_geometry_um"] = {
        "wire_width": args.wire_width_um,
        "via_pad_half": args.via_pad_half_um,
        "note": ("the PDK does not state a routing wire width or a via pad "
                 "size — they are this generator's own choice, which is why "
                 "the limits program takes the pad half-height as an "
                 "argument. Both are recorded here and both are CLI flags."),
    }
    report["tap_clearance_um"] = {
        "value": round(tap_clear_um, 6),
        "terms": {"m1_space_um": facts.m1_space_um,
                  "tap_pad_half_um": pad_half_um,
                  "terminal_pad_half_um": pad_half_um},
        "status": ("PREDICTION — the sign-off deck adjudicates, this "
                   "emitter does not"),
    }

    plan = build_plan(devs, ports, cells, facts, geo, tap_clear)
    clearance_deviations(plan, geo, devs)

    bdir.mkdir(parents=True, exist_ok=True)
    magic_run(stage, magicrc,
              layout_tcl(blockname, plan, stage.path or "."),
              f"a5layout_{blockname}", "A5_LAYOUT_OK")
    ok_mag, err_mag = stage.get("layout.mag", bdir / "layout.mag")
    ok_gds, err_gds = stage.get(f"{blockname}.gds", bdir / f"{block}.gds")
    # A Magic layout is a CELL HIERARCHY: `layout.mag` names the gencell
    # children it instantiates, and without them beside it the file cannot be
    # read back at all. MEASURED: the first version of this producer shipped
    # `layout.mag` alone, and Magic answered
    #
    #     File .../sg13_hv_nmos_NXWZTH.mag couldn't be read
    #     Failure to read in entire subtree of cell.
    #
    # then reported `drc list count total` = 0 — a clean DRC verdict on a
    # layout it had not loaded. The children are not a third output; they are
    # the layout, and they travel with it.
    rc_ls, listing, _ = stage.sh(
        f"cd {shlex.quote(stage.path or '.')} && ls -1 *.mag", timeout=120)
    children: List[str] = []
    if rc_ls == 0:
        # An interactive-login shell in an EDA image prints a banner on
        # stdout, so the listing is filtered to plain file names in the stage
        # rather than trusted whole. An unfiltered token here is an absolute
        # path from that banner, and joining it to the block directory
        # escapes the project entirely.
        for name in sorted(_MAG_NAME_RE.findall(listing)):
            if name in ("layout.mag", "a5probe.mag"):
                continue
            got, _ = stage.get(name, bdir / name)
            if got:
                children.append(name)
    report["layout_cells"] = children
    if not ok_mag:
        report["result"] = "NO_ARTEFACT"
        report["reason"] = f"magic reported success but layout.mag did not " \
                           f"come back: {err_mag}"
        return RC_REFUSED, report
    if not ok_gds:
        report["gds_note"] = f"{blockname}.gds did not come back: {err_gds}"

    report["result"] = "OK"
    report["shapes_painted"] = len(plan.shapes)
    report["deviations"] = plan.deviations
    report["deviation_summary"] = _summarise(plan.deviations)
    report["layout_mag"] = str(bdir / "layout.mag")
    report["layout_gds"] = str(bdir / f"{block}.gds") if ok_gds else None

    # A DRAWN SHORT IS BLOCKING. The layout is still written and still
    # reported — a reader repairing this needs the geometry — but the exit
    # code says the emitter did not draw this netlist. See `blocking_shorts`.
    shorts = blocking_shorts(plan.deviations)
    if shorts:
        report["result"] = "SHORTED"
        report["shorts"] = shorts
        report["reason"] = (
            f"{len(shorts)} pair(s) of routed nets are ONE conductor in the "
            f"layout this emitter drew; each is recorded above with the "
            f"chain of rectangles that joins them. The layout and its GDS "
            f"are written so the geometry can be read, and the exit code is "
            f"non-zero because the netlist was not drawn.")
        return RC_FORBIDDEN, report
    return RC_OK, report


#: The deviation quantity `clearance_deviations` writes for a drawn short.
#: One name, used by the producer's exit code and by the A5 gate, so the two
#: cannot drift apart.
SHORT_QUANTITY = "routed_nets_per_conductor"


def blocking_shorts(deviations: Sequence[dict]) -> List[dict]:
    """The deviations that say this layout JOINS TWO ROUTED NETS.

    WHY THIS ONE IS NOT A DEVIATION LIKE THE OTHERS. Everything else this
    emitter records is a CLEARANCE it predicts and the sign-off deck
    adjudicates: drawn, recorded, and left to the deck, because the deck is
    the authority on whether 0.205 um is far enough. A short is not that
    kind of statement. It is not a distance the deck might yet permit; it is
    two nets of the netlist being one conductor in the layout, measured by
    union-find over this emitter's OWN manifest plus the placed gencells'
    own geometry, with the chain of rectangles that joins them printed
    beside it. No deck adjudicates it away, and the sign-off LVS that
    eventually says `mismatch` is telling the reader the symptom of a defect
    this emitter could already name.

    MEASURED on u_hawaii_adc (ihp-sg13g2, image 0.3.46): 13 of these — 1 on
    `ldo`, 12 on `delta_sigma` — while A5 exited 0 on both blocks and the
    per-block LVS answered `mismatch` with nothing in the flow able to say
    why. A design that carries none is untouched: this is the whole
    difference the rule makes to a clean block's exit code."""
    return [d for d in deviations if d.get("quantity") == SHORT_QUANTITY]


def _summarise(devs: Sequence[dict]) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for d in devs:
        q = out.setdefault(d["quantity"], {"count": 0, "worst_shortfall": 0})
        q["count"] += 1
        sf = d.get("shortfall")
        if isinstance(sf, (int, float)) and sf > q["worst_shortfall"]:
            q["worst_shortfall"] = sf
    return out


def _plugin_version() -> str:
    for up in Path(__file__).resolve().parents:
        meta = up / ".claude-plugin" / "plugin.json"
        if meta.is_file():
            try:
                return json.loads(meta.read_text()).get("version", "unknown")
            except (OSError, ValueError):
                break
    return "unknown"


def _finish(out: dict, args, rc: int) -> int:
    """Print the report and, when asked, write it — on EVERY path.

    A run that ends in ENV_UNAVAILABLE is exactly the run whose report a
    reader most needs, so it is written like any other."""
    print(json.dumps(out, indent=2))
    if getattr(args, "json", None):
        _aa.write_text(Path(args.json), json.dumps(out, indent=2) + "\n")
    return rc


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--block", action="append", default=[])
    ap.add_argument("--container", default="")
    ap.add_argument("--magicrc")
    ap.add_argument("--pdk-root", default="/foss/pdks")
    ap.add_argument("--family", default="ihp-sg13g2")
    ap.add_argument("--gencell-tcl")
    ap.add_argument("--drc-tech")
    ap.add_argument("--magic-tech")
    ap.add_argument("--wire-width-um", type=float,
                    default=DEFAULT_WIRE_W_UM)
    ap.add_argument("--via-pad-half-um", type=float,
                    default=DEFAULT_VIA_PAD_HALF_UM)
    ap.add_argument("--json")
    args = ap.parse_args(argv)

    project = args.project_dir.resolve()
    blocks = list(args.block) or list(load_block_list(project) or [])
    out: dict = {"producer": PRODUCER, "schema": SCHEMA,
                 "version": _plugin_version(),
                 "project": str(project), "blocks": {}}
    if not blocks:
        out["result"] = "NO_BLOCKS"
        out["reason"] = ("no analog block is declared and none was named; "
                         "there is nothing for A5 to draw")
        return _finish(out, args, RC_OK)

    magicrc = args.magicrc or (
        f"{args.pdk_root}/{args.family}/libs.tech/magic/{args.family}.magicrc")
    host_tmp = Path(tempfile.mkdtemp(prefix="a5_layout_emit."))
    stage = Stage(args.container, host_tmp)
    opened, why = stage.open()
    if not opened:
        out["result"] = "ENV_UNAVAILABLE"
        out["tool"] = "docker/container"
        out["reason"] = (f"ENV_UNAVAILABLE: magic is reached through the EDA "
                         f"container and the container is not: {why}. A5 "
                         f"emits NO layout.mag rather than a fabricated one.")
        return _finish(out, args, RC_ENV_UNAVAILABLE)

    try:
        rc_tool, _, _ = stage.sh("command -v magic", timeout=120)
        if rc_tool != 0:
            out["result"] = "ENV_UNAVAILABLE"
            out["tool"] = "magic"
            out["reason"] = (
                f"ENV_UNAVAILABLE: `magic` is not on PATH in "
                f"{args.container or 'this host'}. A5 draws with Magic's own "
                f"PDK gencells; without it there is no layout, and a "
                f"fabricated layout.mag is worse than none.")
            return _finish(out, args, RC_ENV_UNAVAILABLE)

        facts, why = read_pdk(stage, args.pdk_root, args.family,
                              args.gencell_tcl, args.drc_tech,
                              args.magic_tech)
        if facts is None:
            out["result"] = "ENV_UNAVAILABLE"
            out["tool"] = "pdk"
            out["reason"] = why
            return _finish(out, args, RC_ENV_UNAVAILABLE)

        worst = RC_OK
        for block in blocks:
            try:
                rc, rep = emit_block(project, block, stage, magicrc, facts,
                                     args)
            except Refusal as exc:
                rc, rep = RC_REFUSED, {"block": block, "result": "REFUSED",
                                       "reason": str(exc)}
            except MagicError as exc:
                rc, rep = RC_REFUSED, {"block": block, "result": "TOOL_ERROR",
                                       "reason": str(exc)}
            rep["version"] = out["version"]
            out["blocks"][block] = rep
            worst = max(worst, rc)
            # the provenance is written on EVERY outcome, not only the good
            # one: a block directory that still holds a layout must also hold
            # this producer's latest word about it, or the newest thing on
            # disk is an artefact nobody has vouched for.
            bdir = _pl.analog_dir(project) / block
            if bdir.is_dir():
                (bdir / "layout_provenance.json").write_text(
                    json.dumps(rep, indent=2) + "\n")
            print(f"LAYOUT: {'OK' if rc == RC_OK else rep.get('result')} "
                  f"[{block}] "
                  f"{len(rep.get('deviations', []))} deviation(s)")
    finally:
        stage.close()
        shutil.rmtree(host_tmp, ignore_errors=True)

    out["result"] = "OK" if worst == RC_OK else "NOT_OK"
    return _finish(out, args, worst)


if __name__ == "__main__":
    sys.exit(main())
