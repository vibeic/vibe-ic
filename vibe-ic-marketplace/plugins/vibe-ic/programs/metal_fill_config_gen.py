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
from typing import Dict, List, Optional, Tuple
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


# The die-edge band the seal / scribe ring occupies is NOT fillable, and the
# PDK states its own width: its fill scripts declare a `space_to_scribe_line`
# and subtract `_frame - _frame.sized(-<that>)` before filling anything. Read
# the number the PDK already wrote rather than inventing one. No vendor,
# foundry or design literal — only the variable NAME, which is the PDK's.
_SCRIBE_RE = re.compile(
    r'space[_ ]to[_ ]scribe[_ ]line\W{1,4}([0-9]+(?:\.[0-9]+)?)', re.I)


def parse_scribe_keepout_um(fill_script_text: str) -> Optional[float]:
    """Return the PDK's own die-edge (scribe/seal) fill keep-out in microns, or
    None when the PDK's fill script declares none. Pure text parse.

    WHY THIS EXISTS. The engine's only keep-out used to be same-layer spacing
    to drawn metal, which says nothing about the ring band. MEASURED
    (2026-08-20): filling a SEALED die with no edge keep-out took sign-off DRC
    1177 -> 18686 — a guard-ring rule of the form
    `metal.not_outside(guard_ring_mk).width()` reports the WHOLE polygon of
    anything merely TOUCHING the marker band, so each dummy square that landed
    in it was counted. The identical fill on the UNSEALED die added ZERO
    violations. The PDK's own script never had the problem because it excludes
    this band."""
    if not fill_script_text:
        return None
    m = _SCRIBE_RE.search(fill_script_text)
    if not m:
        return None
    try:
        v = float(m.group(1))
    except ValueError:
        return None
    return v if v > 0 else None


def build_metal_fill_config(layermap_text: str, techlef_text: str, deck_text: str,
                            metal_prefix: Optional[str] = None,
                            margin: float = _DEFAULT_MARGIN,
                            window_um: Optional[float] = None,
                            max_passes: int = 8,
                            fill_script_text: str = "",
                            exclude_layers: Optional[list] = None
                            ) -> Optional[dict]:
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
    edge_excl = parse_scribe_keepout_um(fill_script_text)

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
    return {
        "boundary_layer": None,               # -> engine uses the full-die extent
        "window_um": window_um,               # None -> single whole-die window (== rule)
        "max_passes": max_passes,
        "mfg_grid_um": grid_um,               # fill snapped to the manufacturing grid
        "fill_datatype": None,
        # Die-edge keep-out: the seal/scribe band the PDK's own fill script
        # excludes. None -> no keep-out declared by this PDK (unchanged
        # behaviour); a number -> the engine insets the fillable area by it.
        "edge_exclusion_um": edge_excl,
        "exclude_layers": list(exclude_layers or []),
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
            "edge_exclusion_um": edge_excl,
            "edge_exclusion_source": (
                "the PDK fill script's own space_to_scribe_line"
                if edge_excl is not None else
                "not declared by this PDK's fill script — no die-edge keep-out"),
            "layers_derived": len(layers),
            "dummy_datatype_found": sum(1 for s in layers if "fill_datatype" in s),
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
    ap.add_argument("--fill-script", default=None,
                    help="the PDK's own metal-fill script; its "
                         "`space_to_scribe_line` becomes the die-edge "
                         "(seal/scribe band) fill keep-out")
    ap.add_argument("--out", default=None)
    ns = ap.parse_args(argv)

    cfg = build_metal_fill_config(
        _read(ns.layermap), _read(ns.techlef), _read(ns.deck),
        metal_prefix=ns.metal_prefix, margin=ns.margin,
        window_um=ns.window_um, max_passes=ns.max_passes,
        fill_script_text=_read(ns.fill_script))
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
