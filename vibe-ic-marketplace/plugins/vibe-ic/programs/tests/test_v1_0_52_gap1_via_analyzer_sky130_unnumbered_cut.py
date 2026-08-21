#!/usr/bin/env python3
"""Regression tests for GAP#1 (caravel round-7) — the via-analyzer must not
collapse signal routing to met1 on SKY130's unnumbered cut-layer naming.

Root cause (round-7 clean-room, unmasked by the #687 fix that made the
analyzer actually READ the techlef): `_pdk_via_analyzer.routing_layer_upper_
bound` derived the cut-transition index from DIGITS in the cut-layer NAME
(`^VIA(\\d+)$`). SKY130 names its cut layers `mcon` (li1↔met1), `via`
(met1↔met2, UNNUMBERED), `via2`/`via3`/`via4`. The bare `via` has no digit,
so the met1↔met2 transition was dropped from coverage; the gap-walk
`n=1; while n in {2,3,4}` returned 1, the runner emitted
`set_routing_layers -signal met1-met1`, and global route died with GRT-0229
(single-layer signal route cannot complete). Field-verified: flipping that
one line to met1-met5 makes PnR complete EXIT=0.

Fix: derive the transition index STRUCTURALLY from the two ROUTING layers
each via spans (met(k)↔met(k+1) → index k), naming-AGNOSTIC; recognise bare
`via`/`mcon` as cut layers; return None (no restriction) when every present
transition is single-cut-covered; floor any real restriction at met2 so
signal routing never collapses to one layer.

§4.05 negative (no false alert): a real multi-cut-only upper transition must
STILL produce a restriction (don't blanket-disable the DRT-0234 workaround) —
test_real_gap_still_restricts.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "_pdk_via_analyzer.py"
sys.path.insert(0, str(PROG.parent))
import _pdk_via_analyzer as via  # noqa: E402


# SKY130-shaped tech LEF: mcon (li1↔met1), the UNNUMBERED `via` (met1↔met2),
# then via2/via3/via4 — every transition single-cut. The exact pattern that
# collapsed routing to met1 pre-fix.
_SKY130_SHAPED = """
VIA L1M1_PR DEFAULT
  LAYER mcon ;
    RECT 0 0 1 1 ;
  LAYER li1 ;
  LAYER met1 ;
END L1M1_PR
VIA M1M2_PR DEFAULT
  LAYER via ;
    RECT 0 0 1 1 ;
  LAYER met1 ;
  LAYER met2 ;
END M1M2_PR
VIA M2M3_PR DEFAULT
  LAYER via2 ;
    RECT 0 0 1 1 ;
  LAYER met2 ;
  LAYER met3 ;
END M2M3_PR
VIA M3M4_PR DEFAULT
  LAYER via3 ;
    RECT 0 0 1 1 ;
  LAYER met3 ;
  LAYER met4 ;
END M3M4_PR
VIA M4M5_PR DEFAULT
  LAYER via4 ;
    RECT 0 0 1 1 ;
  LAYER met4 ;
  LAYER met5 ;
END M4M5_PR
"""


def test_unnumbered_via_counted_in_coverage():
    """The bare `via` (met1↔met2) and `mcon` (li1↔met1) must be recognised
    as cut layers and mapped to the right transition index."""
    cover = via.via_transition_coverage(_SKY130_SHAPED)
    # transition 0 = li1↔met1 (mcon), 1 = met1↔met2 (`via`), 2..4 = via2..4.
    assert cover.get(1) is True, "met1↔met2 (unnumbered `via`) must be covered"
    assert cover.get(2) is True
    assert cover.get(3) is True
    assert cover.get(4) is True


def test_sky130_shaped_emits_no_restriction():
    """The headline GAP#1 fix: a fully single-cut-covered SKY130-shaped PDK
    must return None (route ALL layers), NOT 1 (which collapsed routing to
    met1-met1 → GRT-0229)."""
    assert via.routing_layer_upper_bound(_SKY130_SHAPED) is None


def test_classify_recognizes_unnumbered_cuts():
    assert via._classify_layer_kind("via") == "cut"
    assert via._classify_layer_kind("mcon") == "cut"
    assert via._classify_layer_kind("via2") == "cut"
    assert via._classify_layer_kind("met1") == "routing"
    assert via._classify_layer_kind("li1") == "unknown"  # sub-metal, not cut


def test_routing_index_maps_metals():
    assert via._routing_index("met1") == 1
    assert via._routing_index("metal3") == 3
    assert via._routing_index("M5") == 5
    assert via._routing_index("li1") == 0
    assert via._routing_index("nwell") is None


# ── §4.05 NEGATIVE — a real multi-cut-only upper gap STILL restricts ────
_SKY130_SHAPED_WITH_GAP = _SKY130_SHAPED.replace(
    "  LAYER via4 ;\n    RECT 0 0 1 1 ;",
    "  LAYER via4 ;\n    RECT 0 0 1 1 ;\n    RECT 2 2 3 3 ;")  # via4 multi-cut


def test_real_gap_still_restricts():
    """If met4↔met5 is genuinely multi-cut-only, the DRT-0234 restriction
    must STILL fire — route met1..met4, skip the uncovered transition."""
    bound = via.routing_layer_upper_bound(_SKY130_SHAPED_WITH_GAP)
    assert bound == 4


def test_restriction_floored_at_met2():
    """Even if the met1↔met2 transition itself is multi-cut-only, the bound
    must never be 1 (a single-layer signal route cannot complete)."""
    bad_m1m2 = _SKY130_SHAPED.replace(
        "  LAYER via ;\n    RECT 0 0 1 1 ;",
        "  LAYER via ;\n    RECT 0 0 1 1 ;\n    RECT 2 2 3 3 ;")
    bound = via.routing_layer_upper_bound(bad_m1m2)
    assert bound is None or bound >= 2


# ── real sky130A nom.tlef (only if the container PDK is reachable) ──────
def _sky130_nom_tlef() -> str | None:
    import subprocess
    p = ("/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/techlef/"
         "sky130_fd_sc_hd__nom.tlef")
    if Path(p).is_file():
        return Path(p).read_text(errors="ignore")
    try:
        r = subprocess.run(
            ["docker", "run", "--rm", "--entrypoint", "bash",
             "hpretl/iic-osic-tools:latest", "-lc", f"cat {p}"],
            capture_output=True, text=True, timeout=60)
        if r.returncode == 0 and "VIA" in r.stdout:
            return r.stdout
    except Exception:
        pass
    return None


def test_real_sky130a_nom_tlef_no_restriction():
    txt = _sky130_nom_tlef()
    if txt is None:
        pytest.skip("sky130A nom.tlef not reachable (no container/PDK)")
    # The real PDK has single-cut vias at every transition → no restriction.
    assert via.routing_layer_upper_bound(txt) is None
    cover = via.via_transition_coverage(txt)
    assert cover.get(1) is True  # the formerly-dropped met1↔met2 `via`
