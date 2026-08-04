"""`--die-um auto` must size from the SITE definition, never from a macro.

`_parse_site_area_um2` feeds `_resolve_auto_die_um`: `avg_cell = site_area *
_AUTO_DIE_AVG_SITES_PER_CELL`, and the die side is `sqrt(cells * avg_cell /
util)`. A wrong site area therefore propagates straight into the die AREA.

Two defects, both MEASURED on sky130A (plugin 1.9.76, container
ghcr.io/vibeic/vibeic-eda:0.2.58):

  1. WRONG TOKEN. A cell LEF carries two kinds of `SITE` token and only one is
     a definition:
         definition   `SITE unithd`      (bare; then SYMMETRY/CLASS/SIZE/END)
         reference    `SITE unithd ;`    (one inside EVERY macro)
     The old pattern `SITE .*? SIZE w BY h ;` (DOTALL) matched the first
     `SITE` token anywhere — a macro's REFERENCE — and then captured THAT
     MACRO's footprint. On `sky130_fd_sc_hd.lef` it returned 4.14 x 2.72 =
     11.26 um2 instead of the real `SITE unithd` 0.46 x 2.72 = 1.2512 um2.
     9x high on area, i.e. a 9x die: measured end-to-end, `--die-um auto` for
     subservient went 433x433 -> 1299x1299.

  2. WRONG FILE. The cell LEF holds NO site definition at all (measured: 0
     bare-`SITE` lines in `lef/sky130_fd_sc_hd.lef`, 2 in
     `techlef/sky130_fd_sc_hd__nom.tlef`) — so it must fall through to the
     TECH lef rather than accept whatever the cell LEF yields.

NEGATIVE CONTROL: `test_macro_site_reference_is_not_mistaken_for_the_site`
asserts 1.2512 and FAILS (returns 11.2608) against the pre-fix body.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import phase3_one_shot_runner as R  # noqa: E402

# Shaped exactly like sky130_fd_sc_hd.lef: macros FIRST, each carrying a SITE
# REFERENCE and its own SIZE; the site DEFINITION (if any) comes later.
_CELL_LEF_MACROS_FIRST = """\
VERSION 5.7 ;
MACRO sky130_fd_sc_hd__a211oi_1
  CLASS CORE ;
  SITE unithd ;
  SIZE 4.14 BY 2.72 ;
END sky130_fd_sc_hd__a211oi_1
MACRO sky130_fd_sc_hd__inv_1
  CLASS CORE ;
  SITE unithd ;
  SIZE 1.38 BY 2.72 ;
END sky130_fd_sc_hd__inv_1
END LIBRARY
"""

_TECH_LEF = """\
VERSION 5.7 ;
LAYER met1
  TYPE ROUTING ;
END met1
SITE unithd
  SYMMETRY Y ;
  CLASS CORE ;
  SIZE 0.46 BY 2.72 ;
END unithd
SITE unithddbl
  SYMMETRY Y ;
  CLASS CORE ;
  SIZE 0.46 BY 5.44 ;
END unithddbl
"""


def test_macro_site_reference_is_not_mistaken_for_the_site():
    """NEGATIVE CONTROL — pre-fix this returns 11.2608 (a macro) and FAILS.

    The cell LEF declares no site, only references, so the correct answer is
    "no site here" — NOT the first macro's footprint.
    """
    got = R._parse_site_area_um2(_CELL_LEF_MACROS_FIRST)
    assert got != 4.14 * 2.72, (
        "parsed a MACRO's SIZE as the site area — a macro's `SITE x ;` is a "
        "reference, not a definition")
    assert got is None, got


def test_site_definition_in_tech_lef_is_parsed():
    got = R._parse_site_area_um2(_TECH_LEF)
    assert got is not None
    assert abs(got - 0.46 * 2.72) < 1e-9, got


def test_class_core_site_is_preferred_over_a_non_core_site():
    """When a LEF declares several sites, the placement row site (CLASS CORE)
    is the one the die model means — not a pad/corner site that happens to be
    declared first."""
    lef = """\
SITE ioSite
  CLASS PAD ;
  SIZE 60.0 BY 180.0 ;
END ioSite
SITE unithd
  CLASS CORE ;
  SIZE 0.46 BY 2.72 ;
END unithd
"""
    got = R._parse_site_area_um2(lef)
    assert abs(got - 0.46 * 2.72) < 1e-9, got


def test_no_site_anywhere_returns_none_so_the_caller_can_degrade():
    assert R._parse_site_area_um2("VERSION 5.7 ;\nEND LIBRARY\n") is None
    assert R._parse_site_area_um2("") is None
    assert R._parse_site_area_um2(None) is None
