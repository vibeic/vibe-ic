#!/usr/bin/env python3
"""pdk_local hard-macro <-> target-PDK LAYER compatibility guard.

Found by the PDK-portability convergence cell (2026-07-22): a design that
carries its own hard macro under ``input/pdk_local/<vendor>/`` carries ONE
abstract, cut for ONE PDK's layer stack. LEF layer names are PDK-PRIVATE, so
pointing that design at a different PDK makes every pin shape land on a layer
the target technology never declares.

OpenROAD's LEF reader does NOT fail on that. It prints

    [WARNING ODB-0176] error: undefined layer (<name>) referenced

once per shape, DROPS the shape, and still reports
``LEF file: ..., created N library cells``. The macro loads with the correct
OUTLINE and ZERO pin geometry: placement, CTS, PDN and GDS all succeed while
every macro pin is physically unroutable. The run looks closed and is void —
the same "tool reports success while silently not doing the thing" class as
the silent wrong-PDK fallback guard next to it.

Guard: refuse, naming the macro and the exact undeclared layers. It never
renames or remaps a layer — remapping would silently re-cut another PDK's
abstract onto this stack at a pitch it was never drawn for.

chip-AGNOSTIC: the declared-layer set comes from whatever tech LEF the target
PDK resolved to; the guard holds no chip, vendor or PDK literal. Both a
positive (compatible macro must still pass) and a negative (incompatible
macro must be caught) proof are present, per the §4.05 no-leak requirement.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import phase3_one_shot_runner as p3  # noqa: E402


TECH_LEF = """\
VERSION 5.7 ;
LAYER LayerA1
    TYPE ROUTING ;
END LayerA1
LAYER ViaA1
    TYPE CUT ;
END ViaA1
LAYER LayerA2
    TYPE ROUTING ;
END LayerA2
"""


def _macro_lef(layer: str) -> str:
    return f"""\
VERSION 5.7 ;
MACRO some_hard_macro
  CLASS BLOCK ;
  SIZE 100.000 BY 200.000 ;
  PIN d0
    DIRECTION INPUT ;
    PORT
      LAYER {layer} ;
      RECT 0.000 1.000 0.070 1.070 ;
    END
  END d0
  OBS
    LAYER {layer} ;
    RECT 0.000 0.000 100.000 200.000 ;
  END
END some_hard_macro
"""


@pytest.fixture()
def tech(tmp_path: Path) -> Path:
    p = tmp_path / "target.tlef"
    p.write_text(TECH_LEF)
    return p


def test_layer_parsers_separate_declaration_from_reference(tech: Path):
    """`LAYER x` (no semicolon) declares; `LAYER x ;` references."""
    declared = p3._lef_declared_layers(tech.read_text())
    assert declared == {"LayerA1", "ViaA1", "LayerA2"}
    referenced = p3._lef_referenced_layers(_macro_lef("LayerA1"))
    assert referenced == {"LayerA1"}


def test_negative_incompatible_macro_is_refused(tmp_path: Path, tech: Path):
    """A macro cut for another stack must be REFUSED, naming the layer."""
    mlef = tmp_path / "foreign_macro.lef"
    mlef.write_text(_macro_lef("someOtherStackM3"))
    msg = p3.macro_lef_layer_compat_guard(
        "target_pdk", str(tech), None, [str(mlef)])
    assert msg is not None
    assert "REFUSED" in msg
    assert "someOtherStackM3" in msg          # names the offending layer
    assert str(mlef) in msg                   # names the offending macro
    assert "target_pdk" in msg
    # It must explain the silent-void mechanism, not just fail.
    assert "ODB-0176" in msg


def test_positive_compatible_macro_still_passes(tmp_path: Path, tech: Path):
    """The overwhelmingly common case — macro matches the target stack."""
    mlef = tmp_path / "native_macro.lef"
    mlef.write_text(_macro_lef("LayerA1"))
    assert p3.macro_lef_layer_compat_guard(
        "target_pdk", str(tech), None, [str(mlef)]) is None


def test_positive_no_macros_is_a_noop(tech: Path):
    """A design with no pdk_local macros is untouched."""
    assert p3.macro_lef_layer_compat_guard(
        "target_pdk", str(tech), None, []) is None
    assert p3.macro_lef_layer_compat_guard(
        "target_pdk", str(tech), None, None) is None


def test_cell_lef_may_also_declare_layers(tmp_path: Path, tech: Path):
    """Libraries that declare a layer in the CELL LEF must not be refused."""
    cell = tmp_path / "cells.lef"
    cell.write_text("VERSION 5.7 ;\nLAYER LayerA9\n    TYPE ROUTING ;\n"
                    "END LayerA9\n")
    mlef = tmp_path / "m.lef"
    mlef.write_text(_macro_lef("LayerA9"))
    # Without the cell LEF the layer is unknown -> refused ...
    assert p3.macro_lef_layer_compat_guard(
        "target_pdk", str(tech), None, [str(mlef)]) is not None
    # ... with it, the layer is declared -> compatible.
    assert p3.macro_lef_layer_compat_guard(
        "target_pdk", str(tech), str(cell), [str(mlef)]) is None


def test_unreadable_tech_lef_never_fabricates_a_refusal(tmp_path: Path):
    """Fail-safe toward NOT-refusing: no declared-layer evidence, no verdict.

    A refusal asserted from an unreadable tech LEF would block every run on
    any host where the PDK lives somewhere this process cannot read.
    """
    mlef = tmp_path / "m.lef"
    mlef.write_text(_macro_lef("anything"))
    assert p3.macro_lef_layer_compat_guard(
        "target_pdk", str(tmp_path / "missing.tlef"), None,
        [str(mlef)]) is None


def test_macro_with_no_geometry_is_not_refused(tmp_path: Path, tech: Path):
    """A pure-outline abstract (no PORT/OBS layers) references nothing."""
    mlef = tmp_path / "outline_only.lef"
    mlef.write_text("VERSION 5.7 ;\nMACRO m\n  CLASS BLOCK ;\n"
                    "  SIZE 10.000 BY 10.000 ;\nEND m\n")
    assert p3.macro_lef_layer_compat_guard(
        "target_pdk", str(tech), None, [str(mlef)]) is None


# ---------------------------------------------------------------------------
# PIN-PORT vs OBS-only distinction (2026-07-22, SN2025 x HP18E80).
#
# The eMemory OTP macro EO0128X8KA180BA11 puts EVERY pin on a declared metal
# (MET3) and references the LEF-reserved `OVERLAP` layer ONLY inside its OBS
# obstruction section (a whole-cell RECT). The target tech LEF does not declare
# OVERLAP, so the original guard refused the macro and halted phase3 before
# PnR/DRC/LVS/STA — a FALSE POSITIVE, because dropping an OBS obstruction on an
# undeclared layer leaves every pin intact and a CLASS BLOCK macro already
# blocks its own footprint. The guard must refuse ONLY when a PIN PORT lands on
# an undeclared layer; an OBS-only undeclared layer warns and proceeds.
# ---------------------------------------------------------------------------
def _macro_lef_split(pin_layer: str, obs_layer: str) -> str:
    """A macro whose PIN PORT and OBS obstruction use DIFFERENT layers."""
    return f"""\
VERSION 5.7 ;
MACRO split_macro
  CLASS BLOCK ;
  SIZE 100.000 BY 200.000 ;
  PIN d0
    DIRECTION INPUT ;
    PORT
      LAYER {pin_layer} ;
      RECT 0.000 1.000 0.070 1.070 ;
    END
  END d0
  OBS
    LAYER {obs_layer} ;
    RECT 0.000 0.000 100.000 200.000 ;
  END
END split_macro
"""


def test_lef_pin_referenced_layers_excludes_obs():
    """The PORT-only parser must see the pin layer and NOT the OBS layer."""
    pin_only = p3._lef_pin_referenced_layers(
        _macro_lef_split("LayerA1", "OVERLAP"))
    assert pin_only == {"LayerA1"}          # OBS layer OVERLAP excluded
    # The all-references parser still sees both (unchanged behaviour).
    both = p3._lef_referenced_layers(_macro_lef_split("LayerA1", "OVERLAP"))
    assert both == {"LayerA1", "OVERLAP"}


def test_obs_only_undeclared_layer_is_not_refused(tmp_path: Path, tech: Path):
    """NEGATIVE CONTROL for the false positive: pins on a declared layer,
    an undeclared layer ONLY in OBS → must NOT be refused (returns None).

    This FAILS against the pre-fix guard (which refused on any undeclared
    referenced layer) and PASSES against the fixed guard."""
    mlef = tmp_path / "obs_only.lef"
    mlef.write_text(_macro_lef_split("LayerA1", "OVERLAP"))
    assert p3.macro_lef_layer_compat_guard(
        "target_pdk", str(tech), None, [str(mlef)]) is None


def test_pin_undeclared_is_refused_even_when_obs_is_declared(
        tmp_path: Path, tech: Path):
    """The genuine void case must still be caught: a PIN PORT on an
    undeclared layer is REFUSED even if the OBS layer is fine."""
    mlef = tmp_path / "pin_bad.lef"
    mlef.write_text(_macro_lef_split("foreignStackM7", "LayerA1"))
    msg = p3.macro_lef_layer_compat_guard(
        "target_pdk", str(tech), None, [str(mlef)])
    assert msg is not None
    assert "REFUSED" in msg
    assert "foreignStackM7" in msg           # names the fatal pin layer
    # The offender line names ONLY the fatal pin layer, not the declared OBS
    # layer (which may still appear in the informational declared-layers list).
    offender_line = next(
        ln for ln in msg.splitlines() if "undeclared layer(s)" in ln)
    assert "foreignStackM7" in offender_line
    assert "LayerA1" not in offender_line


def test_real_world_otp_overlap_obs_only_passes(tmp_path: Path):
    """Replica of EO0128X8KA180BA11: all pins on a declared metal (MET3),
    OVERLAP referenced only in OBS. Must pass (None)."""
    tech = tmp_path / "hp18e80.tlef"
    tech.write_text("VERSION 5.7 ;\n"
                    "LAYER MET3\n    TYPE ROUTING ;\nEND MET3\n"
                    "LAYER MET1\n    TYPE ROUTING ;\nEND MET1\n"
                    "LAYER MET2\n    TYPE ROUTING ;\nEND MET2\n")
    otp = tmp_path / "EO0128X8KA180BA11_M3.lef"
    otp.write_text("""\
VERSION 5.7 ;
MACRO EO0128X8KA180BA11
  CLASS BLOCK ;
  SIZE 406 BY 143 ;
  PIN PDOB[1]
    DIRECTION OUTPUT ;
    PORT
      LAYER MET3 ;
      RECT 140.435 0 140.875 0.6 ;
    END
  END PDOB[1]
  PIN PA[0]
    DIRECTION INPUT ;
    PORT
      LAYER MET3 ;
      RECT 10.0 0 10.44 0.6 ;
    END
  END PA[0]
  OBS
    LAYER OVERLAP ;
      RECT 0 0 406 143 ;
    LAYER MET1 ;
      RECT 0 0 406 143 ;
    LAYER MET3 ;
      RECT 0 0 1.2 48.735 ;
  END
END EO0128X8KA180BA11
""")
    assert p3.macro_lef_layer_compat_guard(
        "custom:pdk", str(tech), None, [str(otp)]) is None
