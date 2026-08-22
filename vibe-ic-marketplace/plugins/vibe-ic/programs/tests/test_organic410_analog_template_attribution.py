#!/usr/bin/env python3
"""ORGANIC #410 (analog half) — a context must not claim to describe a PDK
whose template it does not carry.

`known_family_context` falls back to sky130's template for an unknown
selector while `family` records the name that was ASKED FOR. The context then
claims to describe a PDK whose devices, corner sections and model lib it does
not have — #389's misattribution in the analog track.

MEASURED, AND NARROWER THAN IT LOOKS. No consumer today SIMULATES with the
substituted values: `analog_real_corner_sweep` uses its own `PDK_LIB` on the
`source == "known_family"` fast path, gets None for an unknown selector, and
stops at "pdk lib not reachable"; `analog_mc_yield_run` only calls
`parse_sections`. This is a LATENT trap for the next consumer that reads
`ctx.device_map` at face value, not a wrong simulation happening now — and
these tests say so rather than implying a live defect.

CONTROL FLOW IS DELIBERATELY UNCHANGED, pinned below: marking the fallback
with a different `source` would push unknown selectors into the caller's
`else` branch where sky130's `model_lib` WOULD be used — strictly worse than
today's honest stop.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import analog_pdk_deck_context as A  # noqa: E402


def test_a_known_family_attributes_to_itself():
    for sel in ("sky130", "gf180"):
        c = A.known_family_context(sel)
        assert c.family == sel and c.template_family == sel
        assert "NO authored template" not in c.disclosure


def test_an_unknown_selector_says_which_template_it_carries():
    c = A.known_family_context("ihp-sg13g2")
    assert c.family == "ihp-sg13g2", "the request is still recorded"
    assert c.template_family == "sky130", "and so is what it actually carries"
    assert "NO authored template family for 'ihp-sg13g2'" in c.disclosure
    assert "does NOT describe" in c.disclosure


def test_the_attribution_reaches_the_serialised_form():
    """A truth only present in a Python attribute does not reach the artefact
    a reviewer reads."""
    j = A.known_family_context("totally_made_up").as_json()
    assert j["family"] == "totally_made_up"
    assert j["template_family"] == "sky130"


def test_the_known_family_values_are_unchanged():
    """The paired half. The sky130/gf180 fast path is a documented
    bit-identical regression surface; a fix that moved those values would
    trade a latent misattribution for a live behaviour change."""
    sky = A.known_family_context("sky130")
    assert sky.device_map == dict(A._KNOWN_FAMILIES["sky130"]["device_map"])
    assert sky.model_lib == A._KNOWN_FAMILIES["sky130"]["model_lib"]
    gf = A.known_family_context("gf180")
    assert gf.model_lib == A._KNOWN_FAMILIES["gf180"]["model_lib"]
    assert gf.corner_sections == list(
        A._KNOWN_FAMILIES["gf180"]["corner_sections"])


def test_the_source_still_reads_known_family_for_an_unknown_selector():
    """Control flow must NOT change. `analog_real_corner_sweep` branches on
    `source == "known_family"` BEFORE it looks at status; sending an unknown
    selector down the other branch would make it use sky130's model_lib
    instead of stopping at "pdk lib not reachable"."""
    assert A.known_family_context("ihp-sg13g2").source == "known_family"


def test_the_consumers_measured_claim_still_holds():
    """The premise of the narrow scope. If a consumer starts reading
    `ctx.device_map` off the fast path, this fails and the scope must be
    re-measured."""
    sweep = (_PROGRAMS / "analog_real_corner_sweep.py").read_text()
    i = sweep.index('ctx.source == "known_family"')
    branch = sweep[i:i + 700]
    assert "PDK_LIB.get(pdk)" in branch, \
        "the fast path no longer takes its own lib — re-measure #410's scope"
    assert "devices = None" in branch
