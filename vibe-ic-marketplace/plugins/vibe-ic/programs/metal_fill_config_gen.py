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
  * min width / space  <- routing-layer WIDTH / max SPACING and SPACINGTABLE cell.
  * dummy datatype     <- the DRC deck's own layer table entry named like
    `<metal>_dummy` / `<metal>_fill` on the SAME drawn number. Foundry density =
    drawn UNION dummy datatype, while LVS `connect` uses drawn only, so fill on the
    dummy datatype raises density WITHOUT breaking LVS. If the deck declares no dummy
    datatype the fill falls back to the drawn datatype (disclosed).
  * density floor      <- the deck's metal-coverage rule threshold (`… * 100 < 30`),
    else a documented default; the fill target = floor + margin.

Public: build_metal_fill_config(layermap_text, techlef_text, deck_text, metal_prefix)
        -> dict | None (None when no ROUTING layers are declared).
        Raises ValueError naming routing layers whose required inputs cannot be derived.
"""
from __future__ import annotations

# --- sibling-import path (vibe-ic#2104) ------------------------------------
# `programs/` is a flat directory whose modules import each other by BARE
# name. Python puts a file's own directory on `sys.path` only when that file
# is run as `__main__`; under `importlib.util.spec_from_file_location` — how
# the gates, the wiring audit and much of the suite load a program — it does
# not, so every bare sibling import below raises ModuleNotFoundError. Measured
# on the base tree: 454 of the 1385 top-level programs died that way. Restore
# the condition the file is written for. Idempotent, and the same shape the
# sibling programs that already carry it use.
import os as _os                                                    # noqa: E402
import sys as _sys                                                  # noqa: E402

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
# ---------------------------------------------------------------------------


import argparse
import json
import math
import re
import sys
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple
from _atomic_artefact import writing as atomic_writing  # vibe-ic#1082 (helper from PR #1094)
#: The ONE derivation of "which of this deck's rules measure over the die".
#: Importing it is deliberate: a second copy here is a second place for the
#: two to disagree, and they would disagree silently.
import die_level_deck_rule_attribution as _dla  # noqa: E402

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


def parse_streamout_layermap(text: str, prefix: Optional[str] = None
                            ) -> "OrderedDict[str, Tuple[int, int]]":
    """metal base name (lower) -> (gds_number, drawn_datatype). Keeps the DRAWN line
    (datatype 0 / NET purpose), which is what the router streams and the deck measures."""
    pat = _metal_re(prefix) if prefix else None
    out: "OrderedDict[str, Tuple[int, int]]" = OrderedDict()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        toks = line.split()
        if len(toks) < 3:
            continue
        name = toks[0]
        if pat is not None and not pat.match(name):
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
    for raw in strip_line_comments(text).splitlines():
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


def _lef_statements(body: str) -> List[Tuple[List[str], bool]]:
    statements = []
    tokens: List[str] = []
    for token in re.findall(r'"(?:\\.|[^"\\])*"|;|[^\s;]+', body):
        if token == ";":
            if tokens:
                statements.append((tokens, True))
                tokens = []
        else:
            tokens.append(token)
    if tokens:
        statements.append((tokens, False))
    return statements


def _lef_routing_blocks(text: str) -> "OrderedDict[str, str]":
    return OrderedDict(
        (name, body) for name, body in _lef_layer_blocks(text).items()
        if any(ended and [t.upper() for t in tokens] == ["TYPE", "ROUTING"]
               for tokens, ended in _lef_statements(body)))


def derive_metal_prefix(techlef_text: str) -> Optional[str]:
    """Derive the legacy metadata stem from the LEF's routing-layer names.

    Strip a trailing number or ``top`` and return the stem most layers agree on.
    Returns None when names have no such stem; TYPE ROUTING still selects them.
    """
    stems: Dict[str, int] = {}
    for name in _lef_routing_blocks(techlef_text):
        m = re.match(r"^(.*?)(\d+|top)$", name, re.I)
        if not m or not m.group(1):
            continue
        stems[m.group(1)] = stems.get(m.group(1), 0) + 1
    if not stems:
        return None
    # Most-agreed stem wins; ties break on the longer stem, then alphabetically,
    # so the choice is deterministic and never depends on dict order.
    return sorted(stems.items(), key=lambda kv: (-kv[1], -len(kv[0]), kv[0]))[0][0]


def _lef_number(token: str, layer: str, field: str) -> float:
    if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", token):
        raise ValueError(f"routing layer {layer}: invalid {field} value {token!r}")
    value = float(token)
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"routing layer {layer}: invalid {field} value {token!r}")
    return value


def _spacingtable_cells(tokens: List[str], layer: str) -> List[float]:
    words = [t.upper() for t in tokens]
    if len(words) < 2:
        raise ValueError(f"routing layer {layer}: missing SPACINGTABLE kind")
    if words[1] == "PARALLELRUNLENGTH":
        rows = [i for i, word in enumerate(words) if word == "WIDTH"]
        if not rows or rows[0] <= 2:
            raise ValueError(f"routing layer {layer}: malformed SPACINGTABLE run lengths/rows")
        columns = rows[0] - 2
        for token in tokens[2:rows[0]]:
            _lef_number(token, layer, "SPACINGTABLE")
        cells = []
        for start, end in zip(rows, rows[1:] + [len(tokens)]):
            values = tokens[start + 1:end]
            if len(values) != columns + 1:
                raise ValueError(f"routing layer {layer}: malformed SPACINGTABLE WIDTH row")
            numbers = [_lef_number(t, layer, "SPACINGTABLE") for t in values]
            cells.extend(numbers[1:])
        return cells
    if words[1] == "INFLUENCE":
        if len(tokens) <= 2 or (len(tokens) - 2) % 6:
            raise ValueError(f"routing layer {layer}: malformed SPACINGTABLE INFLUENCE row")
        cells = []
        for start in range(2, len(tokens), 6):
            if words[start:start + 6:2] != ["WIDTH", "WITHIN", "SPACING"]:
                raise ValueError(f"routing layer {layer}: malformed SPACINGTABLE INFLUENCE row")
            numbers = [_lef_number(t, layer, "SPACINGTABLE")
                       for t in tokens[start + 1:start + 6:2]]
            cells.append(numbers[2])
        return cells
    raise ValueError(f"routing layer {layer}: unsupported SPACINGTABLE {tokens[1]}")


def parse_techlef_routing(text: str, prefix: Optional[str] = None
                         ) -> Dict[str, Tuple[float, float]]:
    """Routing name (lower) -> (min_width_um, max_space_um).

    The conservative spacing is the maximum numeric SPACING or SPACINGTABLE cell.
    Table axes do not supply spacing or standalone WIDTH. The legacy prefix argument
    is accepted, but TYPE ROUTING determines inclusion regardless of naming stem.
    """
    out: Dict[str, Tuple[float, float]] = {}
    missing = []
    for name, body in _lef_routing_blocks(text).items():
        widths, spaces = [], []
        for tokens, ended in _lef_statements(body):
            field = tokens[0].upper()
            if field != "SPACINGTABLE" and any(t.upper() == "SPACINGTABLE" for t in tokens[1:]):
                raise ValueError(f"routing layer {name}: missing semicolon before SPACINGTABLE")
            if field not in ("WIDTH", "SPACING", "SPACINGTABLE"):
                continue
            if not ended:
                raise ValueError(f"routing layer {name}: unterminated {field} statement")
            if field == "SPACINGTABLE":
                spaces.extend(_spacingtable_cells(tokens, name))
            else:
                if len(tokens) < 2 or (field == "WIDTH" and len(tokens) != 2):
                    raise ValueError(f"routing layer {name}: malformed {field} statement")
                value = _lef_number(tokens[1], name, field)
                if field == "WIDTH":
                    if value == 0:
                        raise ValueError(f"routing layer {name}: WIDTH must be positive")
                    widths.append(value)
                else:
                    spaces.append(value)
        absent = ([] if widths else ["WIDTH"]) + ([] if spaces else ["SPACING/SPACINGTABLE"])
        if absent:
            missing.append(f"routing layer {name}: missing {' and '.join(absent)}")
            continue
        out[name.lower()] = (min(widths), max(spaces))
    if missing:
        raise ValueError("; ".join(missing))
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
    min routing width, snapped to the manufacturing grid.

    THIS IS A STARTING WIDTH, NOT A CEILING (vibe-ic#2135). `aim` is capped at
    0.62 here because this builder reads the PDK's declared files ONLY and has
    never seen the layout: how much of the die the deck's dummy-to-circuit
    clearance leaves fillable, and therefore what packing the floor actually
    demands, is a property of the routed design. A fixed aim was read as a
    ceiling: on a layer whose drawn metal is 9.5% of the die and whose legal
    dummy room is 22.3% of it, 0.62 packing tops out at 22.9% against a 30%
    deck floor. The engine (`metal_fill.lattice_width_for_floor`) now measures
    that room and widens the top of its own ladder when the floor needs it, so
    the number here only decides where the search STARTS."""
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


def parse_metal_keepout_layers(deck_text: str, metal_prefix: Optional[str],
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
        if (left not in (routing_layers or {}) and by_name.get(left) not in routing_ids
                and not (pref and pref in left) and "metal" not in left):
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


def density_rule_layer_identifiers(deck_text: str) -> Dict[str, List[str]]:
    """{die-level density rule id: the layer identifier(s) whose area it
    measures}, read from the deck and from nothing else.

    THE RULE SET comes from `die_level_deck_rule_attribution` — the deck's own
    whole-die area identifier, and the `# Rule` blocks that read it — so there
    is exactly ONE derivation of "which rules measure over the die" in this
    repository and this file does not acquire a second.

    THE LAYER comes from the block, in the two shapes both open decks in this
    image use:
      * inline, `<layer>.area / <die area>` in the block itself;
      * named, `<x>_area = <layer>.area` at deck scope with the block
        referencing `<x>_area`.
    Identifiers are merged across every block that carries the same rule id: a
    deck that emits one rule from a loop spells the layer once, outside it.

    Nothing here is a layer name, a rule name or a PDK. MEASURED on the two
    open decks in the pinned image:
        gf180mcuD  M1.4..M5.4 -> metal1..metal5, MT.3/MT30.7 -> top_metal,
                   PL.8 -> poly2_result
        ihp-sg13g2 AFil.g/g1 -> activ, GFil.g -> poly, Mn.j/k -> metal1,
                   TM1.c/d -> topmetal1, TM2.c/d -> topmetal2, LBE.i -> lbe_drw
    """
    die_names, _why = _dla.die_area_identifiers(deck_text)
    if not die_names:
        return {}
    family = _dla.die_level_density_rules(deck_text, die_names)
    if not family:
        return {}
    ident = r"[A-Za-z_][A-Za-z0-9_]*"
    # NO SENTENCE REACHES ANY REGEX BELOW. A deck's rule block carries English —
    # the `# Rule` header, the `##` notes, and the human-readable violation
    # message the rule prints — and an identifier read out of THAT is a value
    # taken from a sentence that may DENY it (#706/#711). `deck_code_only`
    # blanks every quoted string and every comment first, keeping offsets, so
    # what is matched here is deck CODE and the polarity question has no
    # referent. The direction of the loss is the safe one: an identifier that
    # exists only in a comment is no longer read, and the caller's answer to
    # "no identifier" is a named refusal, never a supplied value.
    code_text = _dla.deck_code_only(deck_text)
    area_of: Dict[str, str] = {}
    for line in code_text.splitlines():
        m = re.match(r"\s*(" + ident + r")\s*=\s*(" + ident + r")\s*\.\s*area\b",
                     line)
        if m and m.group(1) not in die_names:
            area_of[m.group(1)] = m.group(2)
    out: Dict[str, List[str]] = {r: [] for r in family}
    for rid, _where, body in _dla._rule_blocks(deck_text):
        if rid not in out:
            continue
        code = _dla.deck_code_only(body)
        found = set(re.findall(r"(" + ident + r")\s*\.\s*area\b", code))
        found -= set(die_names)
        for word in set(re.findall(ident, code)):
            if word in area_of:
                found.add(area_of[word])
        out[rid] = sorted(set(out[rid]) | found)
    return out


def density_rule_coverage(deck_text: str, layers: List[dict]
                          ) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
    """(covered, uncovered) — {rule: identifiers} split by whether THIS config
    emits a fill entry the rule can point at.

    WHY THIS EXISTS. The config carried whatever the streamout layermap and the
    tech LEF between them produced, and nothing ever asked whether that set
    covers the layers the DECK has a density rule for. On the run that
    motivated this the config carried five metals; the deck also states a
    coverage rule for the stack's TOP metal and one for poly, and neither has
    an entry here. The metal top may be an alias the deck resolves at run time
    to a level this config does fill — this cannot see a Ruby alias and does
    not pretend to. Which is the point: the gap is REPORTED BY NAME, with the
    rule and the identifier the rule names, instead of being invisible.

    The pairing is by NAME, and the two names come from the same PDK: the
    deck's rule says `metal2.area`, and this builder keys its layers off the
    PDK's own streamout layermap entry for `Metal2`. A rule whose identifier
    matches none of them is UNCOVERED — never assumed covered.
    """
    names = {str(sp.get("name")) for sp in layers if sp.get("name")}
    covered: Dict[str, List[str]] = {}
    uncovered: Dict[str, List[str]] = {}
    for rid, idents in sorted(density_rule_layer_identifiers(deck_text).items()):
        (covered if (set(idents) & names) else uncovered)[rid] = idents
    return covered, uncovered


def density_coverage_refusal(uncovered: Dict[str, List[str]]) -> Optional[str]:
    """The named refusal, or None. A density-ruled layer with no fill entry is
    a layer this generator will never raise, so the rule can only be closed by
    the drawn metal or by another program — and a reader has to be told which
    rule and which layer, not handed a total."""
    if not uncovered:
        return None
    parts = []
    for rid, idents in sorted(uncovered.items()):
        what = ", ".join(idents) or "an identifier this could not read"
        parts.append(f"{rid} (measures {what})")
    return ("the deck states a die-level density rule for a layer this config "
            "emits NO fill entry for: " + "; ".join(parts) +
            ". This fill cannot raise those layers; the rule can only be "
            "closed by the drawn metal, by a different fill program, or the "
            "identifier is an alias the deck resolves at run time to a layer "
            "this config does carry — which this cannot see and does not "
            "assume.")


def build_metal_fill_config(layermap_text: str, techlef_text: str, deck_text: str,
                            metal_prefix: Optional[str] = None,
                            margin: float = _DEFAULT_MARGIN,
                            window_um: Optional[float] = None,
                            max_passes: int = 8) -> Optional[dict]:
    ws = parse_techlef_routing(techlef_text)
    if not ws:
        return None
    prefix_derived = False
    if not metal_prefix:
        metal_prefix = derive_metal_prefix(techlef_text)
        prefix_derived = True
    gds = OrderedDict((name, ids) for name, ids in parse_streamout_layermap(layermap_text).items()
                      if name in ws)
    unmapped = [name for name in _lef_routing_blocks(techlef_text) if name.lower() not in gds]
    if unmapped:
        raise ValueError(f"routing layer {', '.join(unmapped)}: no drawn GDS mapping")
    table = parse_layer_table(deck_text)
    floor_pct = parse_density_floor_pct(deck_text)
    floor = (floor_pct if floor_pct is not None else _DEFAULT_FLOOR_PCT) / 100.0
    target = round(min(floor + margin, 0.95), 4)
    grid_um = parse_manufacturing_grid_um(techlef_text)
    space_dd, space_dc = parse_dummy_metal_spacings(deck_text)

    layers = []
    for base in sorted(gds.keys(), key=_metal_order):
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

    _dens_covered, _dens_uncovered = density_rule_coverage(deck_text, layers)
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
            # WHICH OF THE DECK'S OWN DENSITY RULES THIS CONFIG CAN SERVE.
            # Emitted ALWAYS, `{}` included, so "this deck states none" and
            # "this config was built before the concept existed" are
            # distinguishable to a consumer — the same rule the keep-out list
            # above already follows.
            "density_rules_covered": _dens_covered,
            "density_rules_without_fill_entry": _dens_uncovered,
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
    ap.add_argument("--metal-prefix", default=None,
                    help="legacy metadata name stem; omit to derive it from the "
                         "tech LEF's own TYPE ROUTING layer names")
    ap.add_argument("--window-um", type=float, default=None)
    ap.add_argument("--max-passes", type=int, default=8)
    ap.add_argument("--margin", type=float, default=_DEFAULT_MARGIN)
    ap.add_argument("--out", default=None)
    ns = ap.parse_args(argv)

    try:
        cfg = build_metal_fill_config(
            _read(ns.layermap), _read(ns.techlef), _read(ns.deck),
            metal_prefix=ns.metal_prefix, margin=ns.margin,
            window_um=ns.window_um, max_passes=ns.max_passes)
    except ValueError as exc:
        sys.stderr.write(f"metal_fill_config_gen: {exc}\n")
        return 2
    if cfg is None:
        sys.stderr.write("metal_fill_config_gen: no routing metal derivable "
                         "from the supplied PDK files\n")
        return 2
    text = json.dumps(cfg, indent=2)
    if ns.out:
        with atomic_writing(ns.out) as f:
            f.write(text)
    print(text)
    # REFUSE BY NAME, on stderr so it survives a caller that consumes stdout as
    # the config. rc 3 is its own code: the config IS usable and was written —
    # what is being refused is the CLAIM that it covers the deck's density
    # rules. rc 2 already means "no routing metal derivable", a different
    # thing, and folding the two would make a caller unable to tell a config
    # that could not be built from one that does not cover everything.
    _why = density_coverage_refusal(
        (cfg.get("_derivation") or {}).get("density_rules_without_fill_entry")
        or {})
    if _why:
        sys.stderr.write(f"metal_fill_config_gen: REFUSED — {_why}\n")
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
