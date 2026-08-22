#!/usr/bin/env python3
"""The per-layer metal-density PRODUCER must select what the CONSUMER accepts.

`phase3_one_shot_runner._METAL_DENSITY_KLAYOUT_RECIPE` is the KLayout script that
MEASURES per-layer metal density from the as-built GDS; `metal_layer_density_
check` is the gate that JUDGES the result against the foundry CMP window. The
producer picks which LEF layer names count as metal by regex, and the consumer
independently filters the same way (`_METAL_RE`) — two regexes for one question.

They had drifted. The producer's literal was the sky130 spelling only
(`^(met\\d+|li1)$`), so on any PDK that spells its metal layers differently the
producer selected NOTHING and shipped `"layers": {}` — a well-formed report with
no measurement in it, indistinguishable from "this PDK has no metal layers".

MEASURED on the real spm campaign (same GDS + same PDK layermap, only the recipe
swapped) before this fix landed:

    sky130A     BASE: li1,met1..met5           FIXED: identical  (no regression)
    gf180mcuD   BASE: {}                       FIXED: metal1..metal5
    ihp-sg13g2  BASE: {}                       FIXED: metal1..metal5,topmetal1..2

Both recovered measurements then FAIL the density gate (every layer far under the
30% floor) — the empty report had been hiding a real whole-die density failure,
not certifying its absence.

These tests pin the PARITY, not a copy of the pattern: a future edit to either
regex that re-opens the gap fails here.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import metal_layer_density_check as MLD  # noqa: E402
import phase3_one_shot_runner as R  # noqa: E402


def _producer_re() -> "re.Pattern[str]":
    """The regex the EMITTED KLayout script will actually compile — read back out
    of the rendered recipe, so a broken template substitution is caught here
    rather than silently measuring nothing at run time."""
    recipe = R._metal_density_recipe()
    m = re.search(r'metal_re = re\.compile\(r"(.*)", re\.IGNORECASE\)', recipe)
    assert m, "recipe no longer compiles a `metal_re` — parity can't be checked"
    return re.compile(m.group(1), re.IGNORECASE)


# ── the parity property itself ───────────────────────────────────────────────

def test_producer_selects_every_name_the_consumer_accepts():
    """The defect, stated as a property: any layer name the gate would JUDGE must
    be a name the measurement would COLLECT.

    The reverse direction used to be waved off as "safe — the consumer drops what
    it does not recognise". It was not safe, it was the mirror defect: a layer
    the producer measured and the consumer dropped reached the report as a number
    with no verdict attached. Both directions are now pinned, below."""
    prod = _producer_re()
    for name in ("met1", "met5", "metal1", "metal5", "Metal1", "Metal5",
                 "TopMetal1", "TopMetal2", "topmetal1", "m1", "capmetal1"):
        assert MLD._METAL_RE.match(name), f"fixture {name!r} is not a consumer layer"
        assert prod.match(name), (
            f"producer would NOT measure {name!r}, but the consumer judges it — "
            "this is exactly the drift that shipped an empty measurement")


def test_producer_regex_is_derived_from_the_consumer_not_restated():
    """Parity by construction. A hand-copied duplicate passes the test above on
    the day it is written and silently rots afterwards; the whole point of the
    fix is that there is ONE authority."""
    assert MLD._METAL_RE.pattern in R._METAL_DENSITY_LAYER_RE


# ── the three real PDK spellings, as measured ────────────────────────────────

def test_ihp_and_gf180_layer_names_are_now_selected():
    """DIRECTION 2 (the organic case): the real names from ihp-sg13g2's
    sg13g2.map and gf180mcuD's gf180mcu.map — each previously selected zero."""
    prod = _producer_re()
    for name in ("Metal1", "Metal2", "Metal3", "Metal4", "Metal5",
                 "TopMetal1", "TopMetal2"):
        assert prod.match(name), f"{name!r} still unmeasured"


def test_sky130_names_including_li1_still_selected():
    """DIRECTION 1: the PDK the old regex DID work for must not regress. The
    local-interconnect layer is measured today and is now also JUDGED — see
    `test_producer_needs_no_local_exception_for_the_interconnect_layer`."""
    prod = _producer_re()
    for name in ("met1", "met2", "met3", "met4", "met5", "li1"):
        assert prod.match(name), f"sky130 layer {name!r} regressed"


def test_producer_needs_no_local_exception_for_the_interconnect_layer():
    """The mirror of the drift this file was written for, closed.

    The producer used to append its OWN `|(?:^li1$)` clause because the consumer
    did not recognise the local-interconnect layer. That clause was a SECOND
    authority living next to the derived one, and the whole point of deriving is
    that there is only one. It is gone, and the only reason it can be gone is
    that the consumer now accepts the name — so assert the consumer does, rather
    than merely asserting the clause is absent (which a re-added, differently
    spelled exception would still satisfy)."""
    assert MLD._METAL_RE.match("li1"), (
        "the consumer must judge the local-interconnect layer — if it does not, "
        "removing the producer's exception silently stops it being measured")
    assert R._METAL_DENSITY_LAYER_RE == MLD._METAL_RE.pattern, (
        "the producer selector must be the consumer's pattern and nothing else; "
        "a local addition is a second authority and drifts")


def test_non_metal_layermap_rows_are_still_rejected():
    """DIRECTION 1: widening the producer must not start counting vias, wells,
    contacts or the layermap's own NAME/DIEAREA bookkeeping rows as metal — every
    one of these is a real first-column token in the three PDKs' .map files.

    `licon1` is the pointed one: it shares its first two characters with the
    local-interconnect layer the selector now accepts, and it is a CUT, which has
    no area-density rule. It is the near-miss that a lazily written `li.*` would
    swallow."""
    prod = _producer_re()
    for name in ("Via1", "Via5", "TopVia1", "TopVia2", "via", "via2", "mcon",
                 "licon1", "licon", "li", "nwell", "pwell", "GatPoly", "Cont",
                 "NAME", "DIEAREA"):
        assert not prod.match(name), f"{name!r} must not be measured as metal"
        assert not MLD._METAL_RE.match(name), f"{name!r} must not be judged"


# ── the template must not silently fail to render ────────────────────────────

def test_renamed_placeholder_raises_instead_of_measuring_nothing():
    """The realistic drift: someone renames the placeholder in the template and
    misses the call site. `replace()` then matches nothing, the emitted script
    compiles a regex over the literal token, and every PDK measures zero layers —
    the original bug, restored in its most deniable form.

    Note this test would PASS against a guard written the natural way
    (`if placeholder in recipe: raise`) only because that guard can never fire at
    all — `str.replace` removes every occurrence by construction. The guard has
    to look for what SHOULD be there."""
    saved = R._METAL_DENSITY_KLAYOUT_RECIPE
    try:
        R._METAL_DENSITY_KLAYOUT_RECIPE = (
            'metal_re = re.compile(r"__RENAMED_TOKEN__", re.IGNORECASE)\n')
        try:
            R._metal_density_recipe()
        except RuntimeError:
            pass
        else:
            raise AssertionError(
                "the regex was never injected, yet the recipe rendered silently")
    finally:
        R._METAL_DENSITY_KLAYOUT_RECIPE = saved


def test_rendered_recipe_is_valid_python_and_leaves_no_placeholder():
    recipe = R._metal_density_recipe()
    assert "__METAL_LAYER_NAME_RE__" not in recipe
    compile(recipe, "metal_density_klayout.py", "exec")


# ── end-to-end on the real layermap shape ────────────────────────────────────

_IHP_MAP_ROWS = """\
# EDI Stream layer mapping table for SG13
Metal1           NET,SPNET,PIN,LEFPIN,VIA     8                  0
Metal1           FILL                         8                  22
NAME             Metal1/PIN                   8                  25
Via1             PIN                          19                 0
Metal2           NET,SPNET,PIN,LEFPIN,VIA     10                 0
TopMetal1        NET,SPNET,PIN,LEFPIN,VIA     126                0
TopVia1          VIA                          125                0
"""

_SKY_MAP_ROWS = """\
li1     NET,SPNET,VIA            67  20
met1    LEFPIN,NET,SPNET,PIN,VIA 68  20
met1    LEFOBS                   68  4
mcon    VIA,LEFPIN,PIN           67  44
nwell   LEFPIN                   64  16
"""


def _select(map_text: str) -> dict:
    """Re-implement the recipe's own selection loop over a layermap, using the
    rendered regex — the parse logic is 6 lines and re-stating it here keeps the
    test independent of KLayout being installed."""
    prod = _producer_re()
    out: dict = {}
    for line in map_text.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        name, purpose = parts[0], parts[1]
        try:
            gl, gd = int(parts[2]), int(parts[3])
        except ValueError:
            continue
        if prod.match(name) and "NET" in purpose.upper():
            out.setdefault(name.lower(), (gl, gd))
    return out


def test_real_ihp_layermap_rows_select_the_routing_purpose_only():
    sel = _select(_IHP_MAP_ROWS)
    assert sel == {"metal1": (8, 0), "metal2": (10, 0), "topmetal1": (126, 0)}, sel
    # the FILL datatype and the NAME/via bookkeeping rows are not metal routing
    assert (8, 22) not in sel.values()


def test_real_sky130_layermap_rows_unchanged():
    assert _select(_SKY_MAP_ROWS) == {"li1": (67, 20), "met1": (68, 20)}
