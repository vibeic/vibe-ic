#!/usr/bin/env python3
"""The consumer's own TARGETS keys must be normalizable — a closure invariant.

WHY THIS TEST EXISTS, stated plainly because it is a record of a real miss:
v1.8.61 widened `_SPEC_NAME_ALIASES` from LDO-only vocabulary by INVENTING a
data-converter word list (enob/osr/order/fclk/...). It never asked the obvious
question — *what quantities does this module's own TARGETS table ask for?* — and
so it missed `reff`, which is literally `TARGETS["pull"]["key"]`.

The consequence was not cosmetic. `_normalize_spec_name("Reff")` returned None,
so `l5_block_specs` dropped the entry, while
`l5_analog_block_spec_actionable_check` simultaneously DEMANDED a
numerically-bounded spec for that block. **The gate was unsatisfiable for any
`pull` block, no matter how well Phase 1 extracted its spec.**

A hand-maintained word list will drift from the table it serves again. This
test removes the need to remember: it asserts the CLOSURE — every quantity the
consumer asks for must be a quantity the normalizer can name.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, str(PROG / f"{name}.py"))
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


ars = _load("analog_real_corner_sweep")


def _target_keys():
    return {t: v.get("key") for t, v in getattr(ars, "TARGETS", {}).items()
            if isinstance(v, dict) and v.get("key")}


def test_every_target_key_is_a_canonical_spec_name():
    """CLOSURE: every key TARGETS asks for is one _SPEC_NAME_ALIASES defines."""
    canon = set(getattr(ars, "_SPEC_NAME_ALIASES", {}))
    missing = {t: k for t, k in _target_keys().items() if k not in canon}
    assert not missing, (
        f"TARGETS asks for quantities the normalizer cannot name: {missing}. "
        f"Any block of that type has an UNSATISFIABLE actionable-spec gate.")


@pytest.mark.parametrize("btype,key", sorted(_target_keys().items()))
def test_each_target_key_round_trips_through_the_normalizer(btype, key):
    """The key itself must normalize to itself — the minimum a producer needs
    to be able to emit a value this consumer will read."""
    assert ars._normalize_spec_name(key) == key, (
        f"{btype}: TARGETS key {key!r} does not normalize to itself")


def test_block_type_aliases_only_point_at_decked_types():
    """An alias must resolve to a type the module really decks, or it smuggles
    a deckless type past the gate — a false PASS, worse than the false FAIL."""
    aliases = getattr(ars, "BLOCK_TYPE_ALIASES", {})
    decked = set(getattr(ars, "TARGETS", {})) | set(getattr(ars, "T", {}))
    bad = {k: v for k, v in aliases.items() if str(v).lower() not in decked}
    assert not bad, f"aliases pointing at undecked types: {bad}"


def test_aliases_do_not_shadow_a_real_type():
    """NEGATIVE CONTROL: an alias must never rename a type that already has
    its own deck, which would silently reroute it to a different testbench."""
    aliases = getattr(ars, "BLOCK_TYPE_ALIASES", {})
    decked = set(getattr(ars, "TARGETS", {})) | set(getattr(ars, "T", {}))
    shadowed = {k for k in aliases if str(k).lower() in decked}
    assert not shadowed, f"aliases shadowing a decked type: {shadowed}"


def test_per_type_aliases_resolve_to_canonical_names():
    """Every per-type spelling must land on a canonical key, not a typo."""
    canon = set(getattr(ars, "_SPEC_NAME_ALIASES", {}))
    bad = {}
    for btype, table in getattr(ars, "_TYPE_SPEC_ALIASES", {}).items():
        for tok, target in table.items():
            if target not in canon:
                bad[f"{btype}.{tok}"] = target
    assert not bad, f"per-type aliases pointing at non-canonical keys: {bad}"


def test_ambiguous_words_stay_out_of_the_per_type_tables():
    """The admission rule, enforced. Bare `threshold` in a real datasheet names
    an over-voltage REGISTER field far more often than a POR trip point;
    admitting it manufactures a spec the design never stated."""
    banned = {"threshold", "thresholdvoltage", "value", "level", "setting"}
    found = {f"{b}.{tok}" for b, t in getattr(ars, "_TYPE_SPEC_ALIASES", {}).items()
             for tok in t if tok in banned}
    assert not found, f"ambiguous tokens admitted: {found}"


def test_normalize_spec_label_is_exported_for_producers():
    """The public seam exists, so Phase 1 can emit the consumer's vocabulary
    instead of maintaining a second copy that drifts from it."""
    assert callable(getattr(ars, "normalize_spec_label", None))
    assert ars.normalize_spec_label("Reff", "pull") == "reff"
    assert ars.normalize_spec_label("total nonsense xyzzy") is None
