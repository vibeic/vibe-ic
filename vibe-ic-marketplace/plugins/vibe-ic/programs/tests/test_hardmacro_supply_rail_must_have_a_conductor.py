"""A rail is not a rail without a conductor, and a declaration derived from its
own subject cannot validate that subject.

Synthetic throughout — generic rail names, a generic macro, no design or process
is named.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import hardmacro_supply_intent as H  # noqa: E402

BUILT = """SPECIALNETS 3 ;
    - VPWR ( * VPWR ) + USE POWER
      + ROUTED met1 480 + SHAPE FOLLOWPIN ( 0 2720 ) ( 199920 * )
      NEW met4 1600 + SHAPE STRIPE ( 1000 0 ) ( 1000 200000 )
      ;
    - VGND ( * VGND ) + USE GROUND
      + ROUTED met1 480 + SHAPE FOLLOWPIN ( 0 5440 ) ( 199920 * )
      ;
    - VPROG ( * VPROG ) + USE POWER ;
END SPECIALNETS
"""


def _project(tmp: Path, def_text: str) -> Path:
    d = tmp / "phase3" / "stage3" / "pnr"
    d.mkdir(parents=True, exist_ok=True)
    (d / "routed.def").write_text(def_text, encoding="utf-8")
    return tmp


def test_a_rail_with_conductor_is_measured(tmp_path):
    assert "VPWR" in H.measured_rails(_project(tmp_path, BUILT))


def test_a_rail_that_is_only_a_name_is_not_measured(tmp_path):
    """`- VPROG ( * VPROG ) + USE POWER ;` — connect-all-by-name, no metal.

    The shape this file exists for: it was counted as a rail the PDN built, so a
    macro pin bound to it read as covered while carrying no current.
    """
    p = _project(tmp_path, BUILT)
    assert H.measured_rails(p) == ["VGND", "VPWR"]
    assert "VPROG" not in H.measured_rails(p)


def test_the_unbuilt_rail_is_reported_not_silently_dropped(tmp_path):
    """Dropping it without saying so trades one silence for another."""
    assert H.rails_named_but_not_built(_project(tmp_path, BUILT)) == ["VPROG"]


def test_a_rail_built_only_with_fixed_geometry_still_counts(tmp_path):
    """Some flows emit FIXED rather than ROUTED; both are conductor."""
    txt = ("SPECIALNETS 1 ;\n"
           "    - VPWR ( * VPWR ) + USE POWER\n"
           "      + FIXED met1 480 ( 0 2720 ) ( 199920 * )\n      ;\n"
           "END SPECIALNETS\n")
    assert H.measured_rails(_project(tmp_path, txt)) == ["VPWR"]


def test_no_def_measures_nothing(tmp_path):
    assert H.measured_rails(tmp_path) == []
    assert H.rails_named_but_not_built(tmp_path) == []


# ---------------------------------------------------------------- independence

def _l21(entries):
    return {"fields": {"power_domains": entries}}


def test_a_hand_written_declaration_still_counts(tmp_path):
    """No provenance means hand-written. Refusing those would lock the door the
    escape hatch exists to open (#348)."""
    assert H.declared_rails(_l21([{"rail": "VPWR"}])) == ["VPWR"]


def test_a_rail_synthesised_from_the_macro_pins_is_not_a_declaration():
    """The anti-cheat anchor its own docstring names, now enforced.

    A rail derived from the pins it would be used to check matches every one of
    them by construction, so the "pins with no matching rail" count could never
    be non-zero.
    """
    l21 = _l21([{"rail": "VPROG",
                 "derived_by": "l21_macro_supply_rail_synth",
                 "derived_from": {"macro_lef_pin_use": "POWER",
                                  "declared_by_macros": ["GENERIC_HARDMACRO"]}}])
    assert H.declared_rails(l21) == []


def test_provenance_naming_the_macros_is_enough_on_its_own():
    """Keyed on what the synthesiser records, not on a list of its names."""
    l21 = _l21([{"rail": "VPROG",
                 "derived_from": {"declared_by_macros": ["GENERIC_HARDMACRO"]}}])
    assert H.declared_rails(l21) == []


def test_an_unrelated_derivation_is_not_treated_as_self_derived():
    """A rail derived from the PDK or the floorplan is still independent of the
    macro pins, and must not be discarded."""
    l21 = _l21([{"rail": "VPWR", "derived_by": "pdk_default_supply_map",
                 "derived_from": {"pdk": "generic"}}])
    assert H.declared_rails(l21) == ["VPWR"]


def test_a_macro_pin_bound_to_a_nameonly_rail_is_no_longer_covered(tmp_path):
    """End to end: the verdict this whole file is about.

    The mapping points at a rail that exists only as a name, and the design's
    only declaration of it was synthesised from the pin itself.
    """
    l21 = {"fields": {
        "power_domains": [{"rail": "VPROG",
                           "derived_by": "l21_macro_supply_rail_synth",
                           "derived_from": {"macro_lef_pin_use": "POWER"}}],
        "hard_macro_supplies": [{"master": "GENERIC_HARDMACRO", "pin": "VPROG",
                                 "rail": "VPROG"}]}}
    measured = H.measured_rails(_project(tmp_path, BUILT))
    got = H.classify_pin("GENERIC_HARDMACRO", "VPROG", l21, extra_rails=measured)
    assert got["status"] == "rail_undeclared", got
