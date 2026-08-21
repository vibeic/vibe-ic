#!/usr/bin/env python3
"""metal_fill_config_gen.py — derive a per-layer density metal-fill config from a PDK's
OWN declared files (streamout layermap + tech LEF + sign-off DRC deck).

WHAT GAP THIS CLOSES
--------------------
`metal_fill_emit` / `_density_metal_fill` only run when a PDK bridge declares a
`metal_fill_density` config with per-layer numbers. Every OPEN PDK (gf180mcuD, sky130A,
ihp-sg13g2, …) ships NO such bridge config, so the flow skipped metal fill entirely and
a sparse die FAILed the foundry min-metal-density sign-off DRC (e.g. gf180 M1.4..M5.4 /
MT.3: "Metal_n coverage over the entire die shall be >30%"). This builder synthesizes
the config from data the PDK ALREADY declares, so metal fill runs for any PDK — with
ZERO vendor/chip literal in the logic (chip-AGNOSTIC): every number is READ from the
PDK's own layermap / tech LEF / DRC deck.

DERIVATION (all from PDK-declared text)
---------------------------------------
  * GDS layer numbers  <- the streamout LEF->GDS layermap (`Metal1 <purpose> 34 0`),
    the SAME map the streamout uses, so the fill lands on the exact numbers the deck
    measures.
  * min width / space  <- the tech LEF routing-layer WIDTH / (max) SPACING.
  * dummy datatype     <- the DRC deck's own layer table entry named like
    `<metal>_dummy` / `<metal>_fill` on the SAME drawn number. Foundry density =
    drawn UNION dummy datatype, while LVS `connect` uses drawn only, so fill on the
    dummy datatype raises density WITHOUT breaking LVS. If the deck declares no dummy
    datatype the fill falls back to the drawn datatype (disclosed).
  * density floor      <- the deck's metal-coverage rule threshold (`… * 100 < 30`),
    else a documented default; the fill target = floor + margin.

Public: build_metal_fill_config(layermap_text, techlef_text, deck_text, metal_prefix)
        -> dict | None  (None when no routing metal is derivable).
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple
from _atomic_artefact import writing as atomic_writing  # vibe-ic#1082 (helper from PR #1094)

_DEFAULT_FLOOR_PCT = 30.0
_DEFAULT_MARGIN = 0.05          # fill target = floor + margin, so >floor with headroom
_DEFAULT_MAX_DENSITY = 0.95     # only a soft over-fill flag; gf180 has no max-metal rule


def _metal_re(prefix: str) -> "re.Pattern":
    # a routing metal layer is <prefix><n> or <prefix>Top (e.g. Metal1, MetalTop, met3)
    return re.compile(rf"^{re.escape(prefix)}(\d+|top)$", re.I)


def _metal_order(name: str) -> int:
    """Sort key: numbered metals by number, a `…top` layer last."""
    m = re.search(r"(\d+)$", name)
    if m:
        return int(m.group(1))
    return 9999  # MetalTop / top_metal sits above every numbered layer


def parse_streamout_layermap(text: str, prefix: str) -> "OrderedDict[str, Tuple[int, int]]":
    """metal base name (lower) -> (gds_number, drawn_datatype). Keeps the DRAWN line
    (datatype 0 / NET purpose), which is what the router streams and the deck measures."""
    pat = _metal_re(prefix)
    out: "OrderedDict[str, Tuple[int, int]]" = OrderedDict()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        toks = line.split()
        if len(toks) < 3:
            continue
        name = toks[0]
        if not pat.match(name):
            continue
        try:
            num, dt = int(toks[-2]), int(toks[-1])
        except ValueError:
            continue
        # drawn layer only (datatype 0); ignore LABEL/PIN (usually a non-zero datatype).
        if dt != 0:
            continue
        key = name.lower()
        if key not in out:
            out[key] = (num, dt)
    return out


def _lef_layer_blocks(text: str) -> "OrderedDict[str, str]":
    """Split a (tech) LEF into `LAYER <name> … END <name>` sections, line-by-line so a
    layer that is not closed with its own name never swallows the rest of the file (a
    single spanning `LAYER…END \\1` regex does exactly that)."""
    blocks: "OrderedDict[str, str]" = OrderedDict()
    cur: Optional[str] = None
    body: List[str] = []
    for raw in text.splitlines():
        s = raw.strip()
        m = re.match(r"LAYER\s+(\S+)", s)
        if m:
            # keep the FIRST definition of a name: a routing LAYER is defined once up
            # top, but its NAME recurs as a one-line geometry ref (`LAYER Metal1 ;`)
            # inside every via/macro — those must not overwrite the real block.
            if cur is not None:
                blocks.setdefault(cur, "\n".join(body))
            cur, body = m.group(1), []
            continue
        e = re.match(r"END\s+(\S+)", s)
        if e and cur is not None and e.group(1) == cur:
            blocks.setdefault(cur, "\n".join(body))
            cur, body = None, []
            continue
        if cur is not None:
            body.append(s)
    if cur is not None:
        blocks.setdefault(cur, "\n".join(body))
    return blocks


def derive_metal_prefix(techlef_text: str) -> Optional[str]:
    """The PDK's OWN routing-metal naming stem, read from its tech LEF.

    WHY THIS EXISTS (measured defect, chip-AGNOSTIC).
    `_metal_re` matches `^<prefix>(\\d+|top)$`, so the prefix must equal the PDK's
    stem EXACTLY (case-insensitively). There is no literal that works everywhere:

        prefix "metal"  matches Metal1  (gf180mcuD)      -- and NOTHING else
                        does NOT match met1   (sky130A)
                        does NOT match MET1   (this campaign's process)

    The caller's fallback default was the literal ``"metal"``, so on ANY PDK whose
    routing layers are named ``met<n>`` / ``MET<n>`` the layermap and tech-LEF
    parses both returned {}, ``layers`` came out EMPTY, and the caller treated an
    empty config as "this PDK declares no fill config" and skipped metal fill
    silently. The die then FAILs the foundry min-metal-density rule with no
    diagnostic pointing at a name mismatch. That is a one-word default deciding a
    sign-off outcome for two of the three PDKs the module's own docstring claims
    to serve.

    Deriving the stem removes the guess: take every ``TYPE ROUTING`` layer the
    tech LEF declares, strip a trailing number or ``top``, and return the stem
    that the most routing layers agree on. Nothing is assumed about spelling or
    case, and a PDK that names its layers anything self-consistent works.
    Returns None when the tech LEF declares no usable routing-layer name, so the
    caller can DISCLOSE that rather than fill on a guess.
    """
    stems: Dict[str, int] = {}
    for name, body in _lef_layer_blocks(techlef_text).items():
        if not re.search(r"TYPE\s+ROUTING", body, re.I):
            continue
        m = re.match(r"^(.*?)(\d+|top)$", name, re.I)
        if not m or not m.group(1):
            continue
        stems[m.group(1)] = stems.get(m.group(1), 0) + 1
    if not stems:
        return None
    # Most-agreed stem wins; ties break on the longer stem, then alphabetically,
    # so the choice is deterministic and never depends on dict order.
    return sorted(stems.items(), key=lambda kv: (-kv[1], -len(kv[0]), kv[0]))[0][0]


def parse_techlef_routing(text: str, prefix: str) -> Dict[str, Tuple[float, float]]:
    """metal base name (lower) -> (min_width_um, max_space_um). max SPACING (incl. the
    wide-metal RANGE rule) is used as keep-out so fill next to a wide PDN strap is safe."""
    pat = _metal_re(prefix)
    out: Dict[str, Tuple[float, float]] = {}
    for name, body in _lef_layer_blocks(text).items():
        if not pat.match(name):
            continue
        if not re.search(r"TYPE\s+ROUTING", body, re.I):
            continue
        # `\bWIDTH` does not match inside `MINWIDTH` (no word boundary), so this is the
        # standalone routing WIDTH; SPACING picks up both Mn.2a and the wide-metal Mn.2b.
        widths = [float(x) for x in re.findall(r"\bWIDTH\s+([\d.]+)", body, re.I)]
        spaces = [float(x) for x in re.findall(r"\bSPACING\s+([\d.]+)", body, re.I)]
        if not widths or not spaces:
            continue
        out[name.lower()] = (min(widths), max(spaces))
    return out


def parse_layer_table(text: str) -> List[Tuple[str, int, int]]:
    """(name_lower, gds_number, datatype) for every layer the DRC deck names, from the
    two common declaration styles: Ruby `:name, N, D` and `name = input(N, D)`."""
    entries: List[Tuple[str, int, int]] = []
    for m in re.finditer(r":([A-Za-z]\w*)\s*,\s*(\d+)\s*,\s*(\d+)", text):
        entries.append((m.group(1).lower(), int(m.group(2)), int(m.group(3))))
    for m in re.finditer(
            r"([A-Za-z]\w*)\s*=\s*(?:input|polygons)\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)", text):
        entries.append((m.group(1).lower(), int(m.group(2)), int(m.group(3))))
    return entries


def dummy_datatype_for(base: str, drawn_num: int,
                       table: List[Tuple[str, int, int]]) -> Optional[int]:
    """The datatype the deck reserves for DUMMY/FILL metal on this layer number. A
    foundry density layer is drawn UNION this datatype, and LVS ignores it — so fill on
    it raises density without breaking LVS."""
    base = base.lower()
    for name, num, dt in table:
        if num != drawn_num or dt == 0:
            continue
        if base in name and ("dummy" in name or "fill" in name):
            return dt
    return None


def parse_dummy_metal_spacings(deck_text: str) -> Tuple[Optional[float], Optional[float]]:
    """(dummy-to-dummy space, dummy-to-circuit-metal space) in um, from the deck's own
    dummy-metal rules — gf180: `metal_dummy.space(0.98.um…)` (DM.2b) and
    `metal_dummy.separation(metal_drawn, 2.um…)` (DM.3). Either None if not found."""
    dd = [float(x) for x in re.findall(
        r"metal\w*dummy\w*\.space\s*\(\s*([\d.]+)\s*\.\s*um", deck_text, re.I)]
    dc = [float(x) for x in re.findall(
        r"metal\w*dummy\w*\.separation\s*\(\s*[A-Za-z]\w*drawn\w*\s*,\s*([\d.]+)\s*\.\s*um",
        deck_text, re.I)]
    return (max(dd) if dd else None, max(dc) if dc else None)


def parse_manufacturing_grid_um(techlef_text: str) -> Optional[float]:
    """PDK MANUFACTURINGGRID (um) — fill geometry is snapped to it so it never trips the
    off-grid rule."""
    m = re.search(r"MANUFACTURINGGRID\s+([\d.]+)", techlef_text, re.I)
    return float(m.group(1)) if m else None


def _fill_width_for_target(space: float, target: float,
                           min_w: float, grid_um: Optional[float]) -> float:
    """Square side that makes the OPEN-area coverage of a `width`-square / `width+space`-
    pitch grid clear the target with headroom: coverage = w^2/(w+space)^2, so for an
    aim slightly above target, w = space*sqrt(aim)/(1-sqrt(aim)). Bounded below by the
    min routing width, snapped to the manufacturing grid."""
    # top square of the fill LADDER: aim for a HIGH open-area ceiling (>> target) so the
    # big squares carry density in open regions; the engine's ladder then packs the
    # channels with progressively smaller squares down to the target floor.
    aim = min(max(target + 0.25, 0.40), 0.62)
    r = math.sqrt(aim)
    w = space * r / (1.0 - r) if r < 1.0 else space
    w = max(w, 2.0 * min_w, min_w + 0.20)
    if grid_um:
        w = round(w / grid_um) * grid_um
    return round(w, 4)


def parse_density_floor_pct(text: str) -> Optional[float]:
    """The metal min-coverage threshold the deck enforces, e.g. gf180
    `(metal1.area / chip_area) * 100 < 30` -> 30.0. None if not found."""
    vals = [float(x) for x in re.findall(
        r"metal\w*\.area\s*/\s*\w+\s*\)\s*\*\s*100\s*<\s*([\d.]+)", text, re.I)]
    if not vals:
        # fallback: a documented "Metal_n coverage … shall be >NN%" comment/string
        vals = [float(x) for x in re.findall(
            r"metal\w*\s+coverage[^\n]*?>?\s*(\d{1,2})\s*%", text, re.I)]
    return max(vals) if vals else None


def strip_line_comments(text: str) -> str:
    """`text` with every UNQUOTED `#`-to-end-of-line comment removed.

    A deck carries rules that are deliberately switched OFF by commenting them
    out — gf180mcuD's dummy-metal deck ships `DM.5_DM.7` (dummy metal to poly2)
    that way, and the PDK's own fill script has a knob for the same thing. A
    parser that reads the comment reads a rule the PDK is not enforcing, and in
    this case it would subtract every poly2 shape on the die from the fillable
    area — a large, silent, wrong answer. So the comments come off first.

    Quote-aware, because a live rule's `output(...)` label legitimately
    contains `#` (`"DM#{idx}.3"`), and cutting there would truncate the line.
    """
    out = []
    for line in text.splitlines():
        q = None
        for i, ch in enumerate(line):
            if q:
                if ch == q and (i == 0 or line[i - 1] != "\\"):
                    q = None
            elif ch in "\"'":
                q = ch
            elif ch == "#":
                line = line[:i]
                break
        out.append(line)
    return "\n".join(out)


#: A deck states what dummy metal must keep clear of as an ordinary separation
#: rule, e.g. ``metal.separation(guard_ring_mk, 10.um)`` or
#: ``metal_dummy.separation(otp_mk, 6.um, euclidian)``. Both halves of the
#: keep-out are therefore IN THE DECK — the layer, and the distance.
_SEPARATION_RE = re.compile(
    r"([A-Za-z_]\w*)\s*\.\s*separation\s*\(\s*([A-Za-z_]\w*)\s*,\s*"
    r"([0-9]+(?:\.[0-9]+)?)\s*\.\s*um")


def parse_metal_keepout_layers(deck_text: str, metal_prefix: str,
                               routing_layers: Optional[Dict[str, Tuple[int, int]]] = None
                               ) -> List[List[Any]]:
    """``[[gds_layer, datatype, margin_um], ...]`` — the regions THIS DECK says
    metal (and therefore dummy metal, which is metal) must stay away from.

    WHY THIS EXISTS. The fill engine already supports two keep-out forms and
    only the weaker one was ever populated: a band of fixed width inset from
    the layout's own bounding box, whose width was read out of the PDK's fill
    script (``space_to_scribe_line``). That works when — and only when — three
    things coincide: the marked structure is flush with the layout edge, the
    fill script's margin happens to equal the marker's own width plus the
    deck's clearance for it, and the structure is actually PRESENT. On
    gf180mcuD all three happen to hold for the seal ring (marker 0..16 um,
    clearance 10 um, fill-script margin 26 um), which is what made the
    coincidence look like a contract.

    None of the three is a contract. This reads the rule instead: every layer
    a separation rule names against metal, with the distance that rule states.
    It is self-gating in the way a band is not — a marker layer the layout does
    not carry is EMPTY, so it keeps out nothing, and a layout with no seal ring
    loses no fill area to a band protecting a ring that is not there.

    Layers that are themselves routing metal are excluded: dummy-to-circuit
    metal spacing is not a keep-out REGION, it is the per-layer
    ``space_to_metal`` this same config already carries, and re-expressing it
    here would subtract every wire on the die from the fillable area.

    Chip- and PDK-AGNOSTIC: no layer number, no distance and no layer name is
    written here. An empty list means the deck states no such rule, which is a
    different thing from a clearance of zero and is disclosed as such by the
    caller.
    """
    deck_text = strip_line_comments(deck_text)
    table = parse_layer_table(deck_text)
    by_name: Dict[str, Tuple[int, int]] = {}
    for name, num, dt in table:
        by_name.setdefault(name, (num, dt))
    pref = (metal_prefix or "").lower()
    routing_ids = {v for v in (routing_layers or {}).values()}
    routing_nums = {num for num, _dt in routing_ids}

    best: "OrderedDict[Tuple[int, int], float]" = OrderedDict()
    names: Dict[Tuple[int, int], str] = {}
    for m in _SEPARATION_RE.finditer(deck_text):
        left, right, dist = m.group(1).lower(), m.group(2).lower(), float(m.group(3))
        # LEFT must be metal: either the PDK's own routing-metal stem, or the
        # generic `metal`/`metal_dummy` variable a deck uses when it writes one
        # rule for every level. A rule about poly or comp is not ours to apply
        # to a metal fill.
        if not (pref and pref in left) and "metal" not in left:
            continue
        ids = by_name.get(right)
        if ids is None:
            continue                       # the deck names no GDS layer for it
        # RIGHT must not be routing metal — see the docstring.
        if ids in routing_ids or ids[0] in routing_nums:
            continue
        if pref and pref in right:
            continue
        if dist <= 0:
            continue
        prev = best.get(ids)
        if prev is None or dist > prev:
            best[ids] = dist
            names[ids] = right
    return [[num, dt, margin] for (num, dt), margin in best.items()]


def build_metal_fill_config(layermap_text: str, techlef_text: str, deck_text: str,
                            metal_prefix: Optional[str] = None,
                            margin: float = _DEFAULT_MARGIN,
                            window_um: Optional[float] = None,
                            max_passes: int = 8) -> Optional[dict]:
    # `metal_prefix=None` (the new default) means DERIVE IT FROM THE PDK. The old
    # default was the literal "metal", which matches gf180mcuD's `Metal1` and
    # neither sky130A's `met1` nor a `MET1`-style process — on those the parses
    # returned {} and metal fill was skipped with no diagnostic. See
    # `derive_metal_prefix`. An explicit prefix is still honoured verbatim so a
    # bridge can override the derivation.
    prefix_derived = False
    if not metal_prefix:
        metal_prefix = derive_metal_prefix(techlef_text)
        prefix_derived = True
        if not metal_prefix:
            return None
    gds = parse_streamout_layermap(layermap_text, metal_prefix)
    ws = parse_techlef_routing(techlef_text, metal_prefix)
    table = parse_layer_table(deck_text)
    floor_pct = parse_density_floor_pct(deck_text)
    floor = (floor_pct if floor_pct is not None else _DEFAULT_FLOOR_PCT) / 100.0
    target = round(min(floor + margin, 0.95), 4)
    grid_um = parse_manufacturing_grid_um(techlef_text)
    space_dd, space_dc = parse_dummy_metal_spacings(deck_text)

    layers = []
    for base in sorted(gds.keys(), key=_metal_order):
        if base not in ws:
            continue                          # no routing WIDTH/SPACING -> skip
        num, drawn_dt = gds[base]
        min_w, max_s = ws[base]
        fill_dt = dummy_datatype_for(base, num, table)
        # When fill lands on a dedicated DUMMY datatype the deck's dummy-metal rules
        # apply (dummy-to-dummy `space_dd`, dummy-to-circuit `space_dc`); otherwise the
        # drawn-metal spacing (max SPACING, incl. the wide-metal rule) governs.
        if fill_dt is not None:
            space = space_dd if space_dd is not None else round(max_s, 4)
            space_to_metal = space_dc if space_dc is not None else space
        else:
            space = round(max_s, 4)
            space_to_metal = space
        fill_width = _fill_width_for_target(space, target, min_w, grid_um)
        spec = {
            "name": base,
            "layer": [num, drawn_dt],
            "target": target,
            "max": _DEFAULT_MAX_DENSITY,
            "space": round(space, 4),
            "space_to_metal": round(space_to_metal, 4),
            "width": fill_width,
        }
        if fill_dt is not None:
            spec["fill_datatype"] = fill_dt
        else:
            spec["fill_on_drawn"] = True      # disclosed: no dummy datatype in the deck
        layers.append(spec)

    if not layers:
        return None
    # The deck's OWN keep-out rules (see `parse_metal_keepout_layers`). Emitted
    # ALWAYS, `[]` included, so "this deck states none" and "this config was
    # built before the concept existed" are distinguishable to a consumer.
    keepout_layers = parse_metal_keepout_layers(deck_text, metal_prefix, gds)
    return {
        "boundary_layer": None,               # -> engine uses the full-die extent
        "window_um": window_um,               # None -> single whole-die window (== rule)
        "keepout_layers": keepout_layers,
        "max_passes": max_passes,
        "mfg_grid_um": grid_um,               # fill snapped to the manufacturing grid
        "fill_datatype": None,
        "layers": layers,
        "_derivation": {
            "source": "metal_fill_config_gen (chip-AGNOSTIC; PDK-declared files)",
            "metal_prefix": metal_prefix,
            # Which of the two produced the prefix, so a reader can tell a
            # PDK-derived stem from a bridge-supplied override.
            "metal_prefix_derived_from_techlef": prefix_derived,
            "density_floor_pct": floor_pct,
            "target_density": target,
            "mfg_grid_um": grid_um,
            "dummy_space_um": space_dd,
            "dummy_to_circuit_space_um": space_dc,
            "layers_derived": len(layers),
            "dummy_datatype_found": sum(1 for s in layers if "fill_datatype" in s),
            "keepout_layers_derived": len(keepout_layers),
            # The deck's own NAME for each keep-out, so a reader can check the
            # derivation against the rule instead of against a layer number.
            "keepout_layer_names": [
                next((n for n, num, dt in table
                      if (num, dt) == (k[0], k[1])), None)
                for k in keepout_layers],
        },
    }


def _read(path: Optional[str]) -> str:
    if not path:
        return ""
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--layermap", required=True, help="LEF->GDS streamout layermap")
    ap.add_argument("--techlef", required=True, help="tech LEF (routing WIDTH/SPACING)")
    ap.add_argument("--deck", required=True,
                    help="DRC deck text (concatenate the deck + its rule modules)")
    # Default None = derive the stem from the tech LEF. The old default was the
    # literal "metal", which silently matched no layer on any met<n>/MET<n> process.
    ap.add_argument("--metal-prefix", default=None,
                    help="routing-metal name stem; omit to derive it from the "
                         "tech LEF's own TYPE ROUTING layer names")
    ap.add_argument("--window-um", type=float, default=None)
    ap.add_argument("--max-passes", type=int, default=8)
    ap.add_argument("--margin", type=float, default=_DEFAULT_MARGIN)
    ap.add_argument("--out", default=None)
    ns = ap.parse_args(argv)

    cfg = build_metal_fill_config(
        _read(ns.layermap), _read(ns.techlef), _read(ns.deck),
        metal_prefix=ns.metal_prefix, margin=ns.margin,
        window_um=ns.window_um, max_passes=ns.max_passes)
    if cfg is None:
        sys.stderr.write("metal_fill_config_gen: no routing metal derivable "
                         "from the supplied PDK files\n")
        return 2
    text = json.dumps(cfg, indent=2)
    if ns.out:
        with atomic_writing(ns.out) as f:
            f.write(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
