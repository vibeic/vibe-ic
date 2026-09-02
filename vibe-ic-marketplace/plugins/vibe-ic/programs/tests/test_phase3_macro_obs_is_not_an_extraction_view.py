#!/usr/bin/env python3
"""An obstruction is not a conductor, and at chip level it is not even a view.

MEASURED on a die whose per-block LVS already PASSES (A6: DRC 0, LVS match for
both analog blocks). Handing magic the macro abstracts VERBATIM produced 3,719
`Illegal overlap between obsmN and metalN (types do not connect)` feedback
entries, which the extraction step reports as ">= 1,000 extraction errors;
extracted netlist untrustworthy" — stopping LVS and the whole sign-off tail.

Isolated by three arms on the SAME die and the SAME DEF:

    abstracts read verbatim ................. 3,719 errors
    abstracts with the OBS section removed ......... 0
    no macro abstracts read at all ................. 7

The OBS marks the macro's internal metal so a ROUTER will not route over it.
Magic reads it as the `obsm*` types and then sees die-level metal — the PDN,
and every wire that legitimately runs above the macro — on top of an
obstruction, which it calls an illegal overlap. Nothing is wrong with the die.

chip/PDK-AGNOSTIC.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import phase3_one_shot_runner as R  # noqa: E402


_LEF = """VERSION 5.7 ;
MACRO blk
  CLASS BLOCK ;
  SIZE 10.000 BY 10.000 ;
  PIN p
    DIRECTION INOUT ;
    USE POWER ;
    PORT
      LAYER Metal2 ;
        RECT 4.000 4.000 5.000 4.300 ;
    END
  END p
  OBS
      LAYER Metal2 ;
        RECT 0.000 0.000 10.000 10.000 ;
      LAYER Metal3 ;
        RECT 0.000 0.000 10.000 10.000 ;
  END
END blk
END LIBRARY
"""


def test_the_obs_block_is_removed_and_nothing_else_is():
    out, n = R._RE_LEF_OBS_BLOCK.subn("\n", _LEF)
    assert n == 1
    assert "OBS" not in out
    # the pin, its PG declaration and the macro's own END survive
    assert "PIN p" in out and "USE POWER ;" in out
    assert "RECT 4.000 4.000 5.000 4.300 ;" in out
    assert "END blk" in out and "END LIBRARY" in out
    assert "SIZE 10.000 BY 10.000 ;" in out


def test_a_lef_with_no_obs_is_left_alone():
    plain = _LEF.split("  OBS")[0] + "END blk\nEND LIBRARY\n"
    out, n = R._RE_LEF_OBS_BLOCK.subn("\n", plain)
    assert n == 0 and out == plain


def test_each_macro_in_a_multi_macro_lef_loses_only_its_own_obs():
    """Non-greedy: a greedy match would delete everything between the FIRST
    OBS and the LAST END, taking the second macro's pins with it."""
    two = _LEF.replace("END LIBRARY\n", "") + _LEF.replace(
        "blk", "blk2").replace("VERSION 5.7 ;\n", "")
    out, n = R._RE_LEF_OBS_BLOCK.subn("\n", two)
    assert n == 2
    assert "MACRO blk\n" in out and "MACRO blk2\n" in out
    assert out.count("PIN p") == 2
    assert "OBS" not in out


# ---------------------------------------------------------------------------
# DECLARING A PG PIN AND NOT CONNECTING IT IS WORSE THAN NOT DECLARING IT.
#
# MEASURED: once the A8 abstract carries `USE POWER` / `USE GROUND` on a
# macro's supplies, those terminals become PG terminals the flow can see — and
# the PDN's `add_global_connection` patterns were built from the STANDARD-CELL
# LEF alone, so nothing connected them. The run then FAILed, correctly, with
# `PG_TERMINALS_ON_NO_NET: 8 of 155772 power/ground instance terminals are
# attached to no net after routing` — eight being exactly the seven macros'
# supplies. The first ships a floating supply; the second at least fails
# honestly. This closes it.
# ---------------------------------------------------------------------------

_MACRO_LEF = """MACRO m
  PIN vdd
    DIRECTION INOUT ;
    USE POWER ;
    PORT
      LAYER Metal3 ;
        RECT 0 0 1 1 ;
    END
  END vdd
  PIN vss
    DIRECTION INOUT ;
    USE GROUND ;
    PORT
    END
  END vss
  PIN sig
    PORT
    END
  END sig
END m
"""


def test_pg_pin_names_are_read_from_the_abstracts(tmp_path: Path):
    f = tmp_path / "m.lef"
    f.write_text(_MACRO_LEF)
    assert R.macro_pg_pin_names([f]) == (["vdd"], ["vss"])
    # a signal pin is not a PG pin
    assert "sig" not in R.macro_pg_pin_names([f])[0]


def test_the_global_connect_uses_the_macros_own_names(tmp_path: Path):
    f = tmp_path / "m.lef"
    f.write_text(_MACRO_LEF)
    tcl = R._macro_pg_global_connect_tcl([f], "VDD", "VSS")
    assert 'add_global_connection -net VDD -pin_pattern "^vdd$" -power' in tcl
    assert 'add_global_connection -net VSS -pin_pattern "^vss$" -ground' in tcl


def test_a_macro_whose_names_match_the_stdcells_adds_nothing(tmp_path: Path):
    """No duplicate line when the macro already uses the design's own net
    names — the stdcell pattern already covers it."""
    f = tmp_path / "m.lef"
    f.write_text(_MACRO_LEF.replace("vdd", "VDD").replace("vss", "VSS"))
    assert R._macro_pg_global_connect_tcl([f], "VDD", "VSS") == ""


def test_no_macros_is_a_no_op():
    assert R._macro_pg_global_connect_tcl(None, "VDD", "VSS") == ""
    assert R.macro_pg_pin_names([]) == ([], [])
