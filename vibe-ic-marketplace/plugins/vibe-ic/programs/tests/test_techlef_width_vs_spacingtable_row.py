#!/usr/bin/env python3
"""A LEF SPACINGTABLE row was read as the layer's own WIDTH, dropping the layer.

MEASURED DEFECT
===============
`_techlef_routing_layers` matched `^WIDTH\\s+([\\d.]+)`. In LEF, a
`SPACINGTABLE PARALLELRUNLENGTH` row ALSO begins with the token `WIDTH`:

    LAYER metalN
      TYPE ROUTING ;
      SPACINGTABLE
        PARALLELRUNLENGTH  0.0000  0.3000  0.9000 ...
          WIDTH 0.0000     0.0700  0.0700  0.0700 ...   <-- a table row
          WIDTH 0.0900     0.0700  0.0900  0.0900 ...   <-- a table row
          ...
      WIDTH 0.07 ;                                      <-- the layer's width
      PITCH 0.19 ;

When the table is declared BEFORE the layer's own `WIDTH` — which is exactly
how one shipped open PDK writes it — the first match is the table's leading
`0.0000` row. `width is None` then locks 0.0 in, the real `WIDTH 0.07` is
skipped, and `_flush()`'s `width > 0` guard DISCARDS THE WHOLE LAYER, silently.

Measured on the shipped PDKs, before the fix:

    <10-layer PDK>   routing layers = 1   -> only the one layer with no
                                             spacing table survived
    auto strap plan  = None

`_auto_pdn_straps_from_techlef` then saw a single routing layer, correctly
concluded there was nothing above the follow-pin layer to strap to, and
returned None. Phase 3 BLOCKED the PnR step with `PDN_NO_STRAPS: ... no
routing layer above <rail> to strap with`, so that PDK could not reach a GDS
at all and DRC/LVS never ran.

After the fix that PDK parses all 10 layers and a valid orthogonal strap plan
is derived; the two PDKs that already worked parse the SAME layers and derive
the SAME straps.

WHY THE `;` IS NOT ANCHORED TO END OF LINE
===========================================
Two other shipped PDKs write the declaration with a trailing comment:

    WIDTH 0.14 ;                     # Met1 1
    WIDTH 0.230 ;                    # Mn.1  (n=1)

An end-anchored `;\\s*$` dropped every one of their layers (measured 6 -> 0 and
5 -> 0). Requiring the `;` immediately after the SINGLE value is enough: a
spacing-table row always has another number next, so it can never match.

chip-, PDK- and vendor-AGNOSTIC: the fixtures below are synthetic LEF text.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import phase3_one_shot_runner as R  # noqa: E402


# The shape that broke it: SPACINGTABLE BEFORE the layer's own WIDTH.
_TABLE_FIRST = """
LAYER lowest
  TYPE ROUTING ;
  WIDTH 0.07 ;
  PITCH 0.14 ;
  DIRECTION HORIZONTAL ;
END lowest
LAYER upper
  TYPE ROUTING ;
  SPACINGTABLE
    PARALLELRUNLENGTH    0.0000     0.3000     0.9000
      WIDTH 0.0000       0.0700     0.0700     0.0700
      WIDTH 0.0900       0.0700     0.0900     0.0900
      WIDTH 1.5000       0.0700     0.0900     1.5000  ;
  WIDTH 0.14 ;
  PITCH 0.28 ;
  DIRECTION VERTICAL ;
END upper
"""

# The shape that already worked: declaration first, AND a trailing comment.
_DECL_FIRST_WITH_COMMENT = """
LAYER lowest
  TYPE ROUTING ;
  DIRECTION HORIZONTAL ;
  PITCH 0.34 ;
  WIDTH 0.14 ;                     # rule ref 1
  SPACINGTABLE
     PARALLELRUNLENGTH 0 3
     WIDTH 0 0.14
     WIDTH 3 0.28 ;
END lowest
LAYER upper
  TYPE ROUTING ;
  DIRECTION VERTICAL ;
  PITCH 0.46 ;
  WIDTH 0.140 ;                    # rule ref 2
END upper
"""


def _names(text):
    return [layer[0] for layer in R._techlef_routing_layers(text)]


def _widths(text):
    return {layer[0]: layer[3] for layer in R._techlef_routing_layers(text)}


# --------------------------------------------------------------- the fix ----
def test_spacingtable_before_declaration_does_not_drop_the_layer():
    """`upper` declares its table first. Pre-fix it parsed width 0.0 and was
    discarded entirely, leaving a single-layer stack."""
    assert _names(_TABLE_FIRST) == ["lowest", "upper"]
    assert _widths(_TABLE_FIRST)["upper"] == 0.14


def test_a_strap_plan_is_derivable_once_the_upper_layer_survives():
    """The consequence that blocked the flow: with one layer there is nothing
    above the rails to strap to, so no PDN can be built."""
    assert R._auto_pdn_straps_from_techlef(_TABLE_FIRST, "lowest") is not None


def test_dropping_the_upper_layer_yields_no_strap_plan():
    """Negative control for the line above — proves the strap plan really does
    depend on the layer this fix rescues, so the assertion is not vacuous."""
    only_lowest = _TABLE_FIRST.split("LAYER upper")[0]
    assert _names(only_lowest) == ["lowest"]
    assert R._auto_pdn_straps_from_techlef(only_lowest, "lowest") is None


# ------------------------------------------------------ negative controls ----
def test_trailing_comment_after_the_semicolon_still_parses():
    """Two shipped PDKs write `WIDTH 0.14 ;  # rule`. An end-anchored `;` broke
    them (measured 6 -> 0 and 5 -> 0 layers). This must stay green."""
    assert _names(_DECL_FIRST_WITH_COMMENT) == ["lowest", "upper"]
    w = _widths(_DECL_FIRST_WITH_COMMENT)
    assert w["lowest"] == 0.14 and w["upper"] == 0.14


def test_a_spacingtable_row_is_never_taken_as_a_width():
    """`WIDTH 0 0.14` and `WIDTH 3 0.28 ;` are table rows: the first carries
    another number where the `;` would be, and the second's `;` is behind a
    second value. Neither may be read as the layer's width — 0.0 in particular
    would silently discard the layer."""
    w = _widths(_DECL_FIRST_WITH_COMMENT)
    assert 0.0 not in w.values()
    assert w["lowest"] != 0.0


def test_a_layer_with_no_usable_width_is_still_dropped():
    """The `width > 0` guard must survive: a routing layer that declares no
    parseable width of its own is still not reported, so this fix cannot
    manufacture a layer out of a malformed block."""
    txt = "LAYER bad\n  TYPE ROUTING ;\n  PITCH 0.2 ;\n  DIRECTION HORIZONTAL ;\nEND bad\n"
    assert _names(txt) == []


def test_declaration_order_does_not_change_the_answer():
    """Same layer, table before vs after — the parsed width must agree."""
    assert _widths(_TABLE_FIRST)["upper"] == 0.14
    assert _widths(_DECL_FIRST_WITH_COMMENT)["upper"] == 0.14
