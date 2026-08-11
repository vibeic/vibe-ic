#!/usr/bin/env python3
"""A served density window must disclose the SCOPE it was measured at.

MEASURED, on one published run, against that run's own PDK deck:

  * The consumer's measurement is not wrong. Reproducing the gate's producer
    recipe on the run's streamed GDS and running that PDK's OWN whole-die
    KLayout density deck on the SAME GDS agreed on all six regulated layers to
    six decimal places (delta 0.00e+00 on every layer). The arithmetic and the
    denominator are the PDK's own.

  * The WINDOW is where the scopes part. The bounds served for that PDK are read
    out of its magic sign-off script, in which they are a rule about a
    700um x 700um window stepped by 70um. That script REFUSES a die smaller than
    one window — it exits 1 with a "cannot run density checks" message rather
    than measure — and the published die is 176um x 176um, 1/16 of one window's
    area. So on that run the PDK's own tiled path yields NO verdict, while the
    only PDK path that DOES run there (the whole-die KLayout deck) states the
    max side alone and reports zero violations.

  * Consequence: five of six layers were being failed on a MINIMUM bound that
    the PDK evaluates only at a scope it declines to evaluate on that die, and
    nothing in the served payload said so.

One registry entry already recorded its scope, and used it to decide which of
its PDK's two rule sets to serve — "applying a windowed rule to a whole-die
number would judge the design against a rule it was never measured for". The
entries that recorded no scope were read as though their numbers were scope-free.

These tests pin the DISCLOSURE, not any verdict. No bound moves and no gate
changes its answer; a consumer is simply told, always, which scope it is holding.

House rule: each property states how many entries it examined and REFUSES on a
zero denominator, so an empty or unreadable registry cannot vacuously pass.

chip-AGNOSTIC / version-less: every entry is discovered from the registry and
none is named here; the properties are quantified over whatever the tree ships.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import pdk_metal_density_windows as PW  # noqa: E402


def _registry() -> dict:
    return json.loads((_PROGRAMS / "pdk_registry.json").read_text(encoding="utf-8"))


def _entries_stating_windows():
    """(name, block) for every registry PDK that actually states a bound.

    Discovered, never enumerated: a PDK added tomorrow is covered the day it
    lands, and one that states nothing is correctly out of scope here."""
    out = []
    for e in _registry().get("pdks", []) or []:
        block = e.get("metal_density_windows")
        if not isinstance(block, dict):
            continue
        wins, _ = PW.windows_for_pdk(str(e.get("name", "")))
        if wins:
            out.append((str(e.get("name", "")), block))
    return out


def _write_registry(tmp_path: Path, block) -> Path:
    p = tmp_path / "reg.json"
    p.write_text(json.dumps(
        {"pdks": [{"name": "p", "metal_density_windows": block}]}), encoding="utf-8")
    return p


# ── the property: a stated window carries a scope that was actually read ─────

def test_every_stated_window_set_discloses_a_scope_that_was_measured():
    entries = _entries_stating_windows()
    assert entries, ("zero PDKs state a density window — refusing rather than "
                     "passing on an empty denominator")
    missing = []
    for name, _block in entries:
        _wins, prov = PW.windows_for_pdk(name)
        scope = str(prov.get("scope", "")).strip()
        if not scope or scope == PW._SCOPE_UNRECORDED:
            missing.append(name)
    assert not missing, (
        f"examined {len(entries)} window-stating PDK(s); these serve bounds with "
        f"no scope read out of their own deck: {missing}")


def test_a_scope_that_declares_itself_tiled_states_the_window_it_tiles():
    """A tiled scope is only actionable if it says how big the window is.

    'TILED' alone would let a consumer keep judging a whole-die number against
    per-window bounds and believe it had been told something."""
    entries = _entries_stating_windows()
    assert entries, "zero window-stating PDKs — refusing on an empty denominator"
    dim = re.compile(r"\d+(?:\.\d+)?\s*um", re.IGNORECASE)
    checked = 0
    for name, _block in entries:
        _wins, prov = PW.windows_for_pdk(name)
        scope = str(prov.get("scope", ""))
        if "TILED" not in scope.upper():
            continue
        checked += 1
        assert dim.search(scope), (
            f"{name}: scope declares a tiled rule but states no window "
            f"dimension, so a consumer cannot tell what it must measure over")
    assert checked, (
        f"examined {len(entries)} window-stating PDK(s) and none declared a "
        f"tiled scope — this property would be vacuous; refusing")


# ── the property: silence is labelled, never silent ─────────────────────────

def test_a_pdk_recording_no_scope_is_labelled_unrecorded_not_left_silent(tmp_path):
    reg = _write_registry(tmp_path, {"layers": {"met1": [0.35, 0.60]}})
    wins, prov = PW.windows_for_pdk("p", reg)
    assert wins == {"met1": (0.35, 0.60)}
    assert "scope" in prov, (
        "a served window set with no recorded scope omitted the key entirely — "
        "indistinguishable from a PDK whose scope WAS read")
    assert prov["scope"] == PW._SCOPE_UNRECORDED


def test_a_recorded_scope_is_carried_through_verbatim(tmp_path):
    """The fallback must not overwrite a scope the entry actually recorded."""
    stated = "WHOLE-DIE. one ratio over the die, no window and no step."
    reg = _write_registry(
        tmp_path, {"_scope": stated, "layers": {"met1": [0.35, 0.60]}})
    _wins, prov = PW.windows_for_pdk("p", reg)
    assert prov["scope"] == stated


def test_a_blank_recorded_scope_is_treated_as_unrecorded(tmp_path):
    """An empty string is not a disclosure — it reads as one to a key check."""
    reg = _write_registry(
        tmp_path, {"_scope": "   ", "layers": {"met1": [0.35, 0.60]}})
    _wins, prov = PW.windows_for_pdk("p", reg)
    assert prov["scope"] == PW._SCOPE_UNRECORDED


# ── the pre-existing outcomes must not have moved ───────────────────────────

@pytest.mark.parametrize("block,status", [
    ({"layers": {}}, "states-none"),
    ({"layers": {"met1": [0.35, 0.60]}}, "stated"),
])
def test_scope_disclosure_does_not_disturb_the_status_it_travels_with(
        tmp_path, block, status):
    _wins, prov = PW.windows_for_pdk("p", _write_registry(tmp_path, block))
    assert prov["status"] == status


def test_a_pdk_that_states_no_rule_is_not_labelled_unlooked_at(tmp_path):
    """A measured ABSENCE must not be reported as an unread scope.

    A PDK that states no density rule has no bound to scope. Stamping it
    "scope NOT recorded" would report a PDK that WAS read as one that was not —
    the same class of misreading this disclosure exists to stop."""
    reg = _write_registry(tmp_path, {"_measured_from": "NOTHING", "layers": {}})
    wins, prov = PW.windows_for_pdk("p", reg)
    assert wins == {}
    assert prov["status"] == "states-none"
    assert prov.get("scope") != PW._SCOPE_UNRECORDED


def test_an_unknown_pdk_is_still_never_given_another_pdks_numbers(tmp_path):
    reg = _write_registry(tmp_path, {"layers": {"met1": [0.35, 0.60]}})
    wins, prov = PW.windows_for_pdk("not-in-this-registry", reg)
    assert wins == {}
    assert prov["status"] == "unknown-pdk"


def test_no_bound_moved_while_scope_was_being_disclosed():
    """Disclosure only. Every served bound is still exactly what the registry
    states, so this change cannot have turned any run green or red."""
    entries = _entries_stating_windows()
    assert entries, "zero window-stating PDKs — refusing on an empty denominator"
    n = 0
    for name, block in entries:
        wins, _prov = PW.windows_for_pdk(name)
        for layer, pair in (block.get("layers") or {}).items():
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                continue
            lo, hi = PW._coerce_bound(pair[0]), PW._coerce_bound(pair[1])
            if lo is None and hi is None:
                continue
            assert wins[str(layer).lower()] == (lo, hi), f"{name}/{layer} moved"
            n += 1
    assert n, "compared zero bounds — refusing on an empty denominator"
