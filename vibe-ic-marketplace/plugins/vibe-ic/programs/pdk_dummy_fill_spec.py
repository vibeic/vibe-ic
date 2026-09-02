#!/usr/bin/env python3
"""Derive a dummy-METAL fill spec from the PDK's OWN KLayout rule deck.

WHY THIS EXISTS. `phase3_one_shot_runner._GDS_DUMMY_FILL_PY` built its keep-out
from `pya.Region(tc.begin_shapes_rec(li))` — the shapes on **the one layer it
writes to**. That is expressible only for a PDK whose dummy metal shares a layer
with its circuit metal. MEASURED (2026-09-02/03, 8HD-4, `subservient` ×
`gf180mcuD`, image `sha256:190b37be3407…`): this PDK puts `metal2_dummy` on GDS
`36/4` and `metal2_drawn` on `36/0`, and requires 2 um between them
(`rule_decks/dummy_metal.rb`: `metal_dummy.separation(metal_drawn, 2.um)`).
Aiming the fill at `36/0` made every tile *circuit* metal inside 2 um of the
dummy the streamout already placed there, and the deck answered with 65 670
DM2.3/DM3.3 violations, their count tracking the tile count (35 215 tiles →
65 670; 11 027 → 30 518; 8 515 → 25 249).

WHAT THIS DOES. Reads the deck and returns, per metal level:
  * the GDS layer to WRITE dummy tiles on   (`<metal>_dummy`)
  * the set of layers to KEEP OUT of, each with its own spacing, taken from the
    rules that constrain dummy metal
  * the coverage target the density rule enforces, and the layers it sums

NOTHING IS HARDCODED. No `36/0`, no `2.0`, no `30`. Every number is parsed out of
the deck this run is judged by, so a PDK that spells its layers or spacings
differently is read correctly or refused.

FAIL-CLOSED, and that is the load-bearing property. Any of: deck absent, a layer
map that does not parse, a metal level whose dummy layer is not declared, a
dummy-spacing rule that cannot be read, or a density rule with no threshold →
`None` for that level, and the caller must not fill it. A fill placed on a
guess is worse than no fill: it is metal on a mask, and the deck that would have
caught it is the one we failed to read.

chip-AGNOSTIC: deck grammar only. No design, vendor or SKU literal.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

#: `extract_single_layer_from_design.call(:metal2_dummy, 36, 4)`
_RE_LAYER = re.compile(
    r"extract_single_layer_from_design\.call\(\s*:([A-Za-z0-9_]+)\s*,\s*"
    r"(\d+)\s*,\s*(\d+)\s*\)")

#: `2 => { metal_drawn: :metal2_drawn, metal_dummy: :metal2_dummy,
#:         metal_result: :metal2 },`
_RE_METAL_NAMES_ROW = re.compile(
    r"(\d+)\s*=>\s*\{\s*metal_drawn:\s*:([A-Za-z0-9_]+)\s*,\s*"
    r"metal_dummy:\s*:([A-Za-z0-9_]+)\s*,\s*"
    r"metal_result:\s*:([A-Za-z0-9_]+)\s*\}")

#: `ctx.register_layer(names[:metal_result]) { ctx[names[:metal_drawn]] + ctx[names[:metal_dummy]] }`
_RE_RESULT_IS_SUM = re.compile(
    r"register_layer\(\s*names\[:metal_result\]\s*\)\s*\{\s*"
    r"ctx\[names\[:metal_drawn\]\]\s*\+\s*ctx\[names\[:metal_dummy\]\]\s*\}")

#: `dm_2b_l1 = metal_dummy.space(0.98.um, euclidian)`
_RE_DUMMY_SPACE = re.compile(
    r"metal_dummy\.space\(\s*([0-9.]+)\.um")

#: `dm_3_l1 = metal_dummy.separation(metal_drawn, 2.um, euclidian)`
#: and the DM.8 family `metal_dummy.separation(fusetop, 6.um, euclidian)`
_RE_DUMMY_SEP = re.compile(
    r"metal_dummy\.separation\(\s*([A-Za-z0-9_]+)\s*,\s*([0-9.]+)\.um")

#: `if (metal2.area / chip_area) * 100 < 30`
_RE_DENSITY = re.compile(
    r"if\s*\(\s*([A-Za-z0-9_]+)\.area\s*/\s*chip_area\s*\)\s*\*\s*100\s*<\s*"
    r"([0-9.]+)")


def _read(root: Path, *rel: str) -> str:
    """Concatenated text of the named deck files; '' when any is unreadable."""
    out: List[str] = []
    for r in rel:
        p = root / r
        try:
            out.append(p.read_text(errors="ignore"))
        except OSError:
            return ""
    return "\n".join(out)


def _commented(text: str, match_start: int) -> bool:
    """Is the match on a commented-out line? The deck keeps disabled rules as
    comments (DM.4/DM.5/DM.6/DM.7 are commented out in this PDK) and reading one
    as live would keep tiles out of space the foundry allows."""
    line_start = text.rfind("\n", 0, match_start) + 1
    return text[line_start:match_start].lstrip().startswith("#")


def derive(deck_root: Path) -> Optional[Dict[str, Any]]:
    """The spec, or None when anything needed could not be read.

    Never returns a partial answer: a caller that gets a dict may rely on every
    key in it having come from the deck."""
    layers_txt = _read(deck_root, "generic_layers.rb")
    dummy_txt = _read(deck_root, "rule_decks/dummy_metal.rb")
    dens_txt = _read(deck_root, "rule_decks/density.rb")
    if not (layers_txt and dummy_txt and dens_txt):
        return None

    gds: Dict[str, str] = {}
    for m in _RE_LAYER.finditer(layers_txt):
        if _commented(layers_txt, m.start()):
            continue
        gds[m.group(1)] = f"{m.group(2)}/{m.group(3)}"
    if not gds:
        return None

    # metal level -> {drawn, dummy, result} symbol names
    names: Dict[int, Dict[str, str]] = {}
    for m in _RE_METAL_NAMES_ROW.finditer(layers_txt):
        if _commented(layers_txt, m.start()):
            continue
        names[int(m.group(1))] = {"drawn": m.group(2), "dummy": m.group(3),
                                  "result": m.group(4)}
    if not names:
        return None

    # Does the density rule's subject INCLUDE the dummy layer? If the deck sums
    # drawn+dummy then dummy fill moves the coverage number; if it does not,
    # filling the dummy layer cannot satisfy the density rule and this routine
    # must say so rather than emit a spec that cannot work.
    result_is_sum = _RE_RESULT_IS_SUM.search(layers_txt) is not None

    # dummy-to-dummy spacing (one rule, shared by every level in this deck)
    sp = [float(m.group(1)) for m in _RE_DUMMY_SPACE.finditer(dummy_txt)
          if not _commented(dummy_txt, m.start())]
    dummy_to_dummy = max(sp) if sp else None

    # dummy-to-<other layer> separations, by the SYMBOL the rule names
    seps: Dict[str, float] = {}
    for m in _RE_DUMMY_SEP.finditer(dummy_txt):
        if _commented(dummy_txt, m.start()):
            continue
        sym, val = m.group(1), float(m.group(2))
        seps[sym] = max(seps.get(sym, 0.0), val)
    if not seps:
        return None

    # coverage thresholds, by the result-layer symbol the rule measures
    dens: Dict[str, float] = {}
    for m in _RE_DENSITY.finditer(dens_txt):
        if _commented(dens_txt, m.start()):
            continue
        dens[m.group(1)] = float(m.group(2))

    out_levels: Dict[str, Any] = {}
    for lvl, nm in sorted(names.items()):
        dummy_sym, drawn_sym, res_sym = nm["dummy"], nm["drawn"], nm["result"]
        if dummy_sym not in gds or drawn_sym not in gds:
            continue                      # level not declared by this PDK
        target = dens.get(res_sym)
        if target is None or dummy_to_dummy is None:
            continue                      # nothing to aim at, or no spacing
        avoid: List[Dict[str, Any]] = []
        for sym, val in sorted(seps.items()):
            # `metal_drawn` / `metal_dummy` are the rule's own placeholders for
            # THIS level; anything else is a literal layer symbol (the fuse
            # family), kept only when the PDK declares its GDS numbers.
            if sym == "metal_drawn":
                avoid.append({"symbol": drawn_sym, "gds": gds[drawn_sym],
                              "space_um": val, "rule": "dummy-to-circuit"})
            elif sym == "metal_dummy":
                continue                  # covered by the space() rule below
            elif sym in gds:
                avoid.append({"symbol": sym, "gds": gds[sym],
                              "space_um": val, "rule": "dummy-to-keepout"})
        avoid.append({"symbol": dummy_sym, "gds": gds[dummy_sym],
                      "space_um": dummy_to_dummy, "rule": "dummy-to-dummy"})
        out_levels[str(lvl)] = {
            "write_gds": gds[dummy_sym],
            "write_symbol": dummy_sym,
            "drawn_gds": gds[drawn_sym],
            "coverage_target_pct": target,
            "coverage_counts": ([gds[drawn_sym], gds[dummy_sym]]
                                if result_is_sum else [gds[drawn_sym]]),
            "avoid": avoid,
        }
    if not out_levels:
        return None
    return {
        "program": "pdk_dummy_fill_spec",
        "deck_root": str(deck_root),
        "density_subject_includes_dummy": result_is_sum,
        "levels": out_levels,
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("deck_root", help="the PDK's libs.tech/klayout/tech/drc dir")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    spec = derive(Path(a.deck_root))
    if spec is None:
        print("REFUSED: the deck's dummy-metal layer map / spacing rules could "
              "not be read, so no fill spec is emitted (fail-closed).",
              file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(spec, indent=2))
    else:
        print(f"density subject includes dummy: "
              f"{spec['density_subject_includes_dummy']}")
        for lvl, d in spec["levels"].items():
            av = ", ".join(f"{x['gds']}@{x['space_um']}um" for x in d["avoid"])
            print(f"  level {lvl}: write {d['write_gds']} "
                  f"target>{d['coverage_target_pct']}% avoid[{av}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
