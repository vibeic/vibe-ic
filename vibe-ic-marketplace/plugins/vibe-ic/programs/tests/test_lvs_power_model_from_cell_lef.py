"""The documented LVS root fix was unavailable to every project-staged PDK.

MEASURED DEFECT (pre-fix). `lvs_power_aware_netlist_emit._PDK_POWER_MODELS` is
a hardcoded table of three OPEN-SOURCE PDKs. A project-staged PDK — which is
how every commercial PDK reaches this flow — resolves to the synthetic name
`custom:pdk`, so `_normalize_pdk` returns "", `power_model_for` returns None,
and the emitter SKIPS. The gate netlist then stays power-blind while the
extracted layout is not, and netgen reports every std cell as
`is a placeholder, treated as a black box` with the supply pins
`(no matching pin)` — a whole-design LVS mismatch.

`lvs_netgen_setup_emit` fails the same way and says so in its own artifact:
`LVS_SETUP_SKIPPED: unknown PDK '<name>'; no power-net globalisation applied.`

So the named-PDK lanes were complete and the lane that actually needs the fix
was unserved. A LEF already declares everything the model needs, so derive it
from the PDK's own file instead of a name table.

Synthetic library, cell and rail names throughout.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]


def _mod(name: str, fname: str):
    key = f"{name}_lvspwr"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, PROGRAMS / fname)
    m = importlib.util.module_from_spec(spec)
    sys.modules[key] = m
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m


def _pa():
    return _mod("pa", "lvs_power_aware_netlist_emit.py")


# A commercial-shaped std-cell LEF: no common cell-name prefix, supply pins
# declared only by `USE POWER` / `USE GROUND`, no well/body pins.
_CELL_LEF = """VERSION 5.7 ;
MACRO INVX1
  CLASS CORE ;
  PIN A
    DIRECTION INPUT ;
  END A
  PIN Y
    DIRECTION OUTPUT ;
  END Y
  PIN PWRA
    DIRECTION INOUT ;
    USE POWER ;
  END PWRA
  PIN GNDA
    DIRECTION INOUT ;
    USE GROUND ;
  END GNDA
END INVX1
MACRO ND2B4
  CLASS CORE ;
  PIN A1
    DIRECTION INPUT ;
  END A1
  PIN PWRA
    USE POWER ;
  END PWRA
  PIN GNDA
    USE GROUND ;
  END GNDA
END ND2B4
END LIBRARY
"""

_NETLIST = """module top (input a, output y);
  wire n1;
  INVX1 u1 (.A(a), .Y(n1));
  ND2B4 u2 (.A1(n1), .Y(y));
endmodule
"""


def _lef(tmp_path: Path) -> Path:
    p = tmp_path / "libx_macro.lef"
    p.write_text(_CELL_LEF)
    return p


# --------------------------------------------------------------------------
# 1. The model is derivable from the LEF alone.
# --------------------------------------------------------------------------
def test_model_is_derived_from_the_lefs_own_declarations(tmp_path: Path) -> None:
    m = _pa().model_from_cell_lef(_lef(tmp_path))
    assert m is not None
    # Rails come from `USE POWER`/`USE GROUND`, in declaration order.
    assert m.pg_pins == ("PWRA", "GNDA")
    # Cell identity comes from the MACRO names — no prefix convention assumed.
    assert "INVX1" in m.cell_prefix_re and "ND2B4" in m.cell_prefix_re


def test_a_lef_with_no_supply_pins_yields_no_model(tmp_path: Path) -> None:
    """Never guess. A LEF that declares no supply pin must produce None so the
    caller reports a SKIP rather than inventing rail names."""
    p = tmp_path / "nopg.lef"
    p.write_text("VERSION 5.7 ;\nMACRO INVX1\n  PIN A\n  END A\nEND INVX1\n")
    assert _pa().model_from_cell_lef(p) is None


def test_longer_cell_names_are_not_shadowed_by_shorter_ones(
        tmp_path: Path) -> None:
    """`INV` must not shadow `INVX1` in the alternation."""
    p = tmp_path / "l.lef"
    p.write_text(
        "MACRO INV\n  PIN VDDX\n    USE POWER ;\n  END VDDX\n"
        "  PIN VSSX\n    USE GROUND ;\n  END VSSX\nEND INV\n"
        "MACRO INVX1\n  PIN VDDX\n    USE POWER ;\n  END VDDX\nEND INVX1\n")
    m = _pa().model_from_cell_lef(p)
    assert m is not None
    assert m.cell_prefix_re.index("INVX1") < m.cell_prefix_re.index("|INV)") \
        or m.cell_prefix_re.index("INVX1") < m.cell_prefix_re.index("INV|")


# --------------------------------------------------------------------------
# 2. power_model_for — the named lanes are untouched, the custom lane works.
# --------------------------------------------------------------------------
def test_named_pdk_lanes_are_byte_for_byte_unchanged(tmp_path: Path) -> None:
    """A table PDK must resolve to its table entry even when a cell LEF is
    supplied — the LEF is a FALLBACK, never an override."""
    pa = _pa()
    for key in ("sky130A", "gf180mcuC", "gf180mcuD", "ihp-sg13g2"):
        without = pa.power_model_for(key)
        with_lef = pa.power_model_for(key, cell_lef=_lef(tmp_path))
        assert without is not None
        assert with_lef == without, key


def test_unknown_pdk_without_a_lef_still_returns_none() -> None:
    """The pre-fix behaviour is preserved exactly when no LEF is supplied —
    this change adds a capability, it does not silently change a verdict."""
    assert _pa().power_model_for("custom:pdk") is None


def test_unknown_pdk_with_a_lef_gets_a_model(tmp_path: Path) -> None:
    m = _pa().power_model_for("custom:pdk", cell_lef=_lef(tmp_path))
    assert m is not None and m.pg_pins == ("PWRA", "GNDA")


# --------------------------------------------------------------------------
# 3. The end-to-end effect: the netlist actually becomes power-aware.
# --------------------------------------------------------------------------
def test_staged_pdk_netlist_is_no_longer_skipped(tmp_path: Path) -> None:
    pa = _pa()
    txt, stats = pa.emit_power_aware_netlist(
        _NETLIST, "custom:pdk", top="top", cell_lef=_lef(tmp_path))
    assert not stats.get("skipped_reason"), stats
    assert stats.get("instances_patched") == 2, stats
    # Both instances now carry the PDK's own rails.
    assert txt.count(".PWRA(PWRA)") == 2
    assert txt.count(".GNDA(GNDA)") == 2


def test_staged_pdk_without_a_lef_reports_why_it_skipped() -> None:
    """A skip must say what was missing. 'no power model' alone sent people
    looking for a PDK name problem when the real answer was a missing input."""
    _, stats = _pa().emit_power_aware_netlist(_NETLIST, "custom:pdk", top="top")
    assert "no cell LEF supplied" in str(stats.get("skipped_reason"))


# --------------------------------------------------------------------------
# 4. The netgen setup emitter globalises the PDK's own rails.
# --------------------------------------------------------------------------
def test_netgen_setup_globalises_rails_harvested_from_the_lef(
        tmp_path: Path) -> None:
    setup = _mod("setup", "lvs_netgen_setup_emit.py")
    tcl = setup.build_supplementary_setup_tcl(
        "custom:pdk", cell_lef=_lef(tmp_path))
    assert "LVS_SETUP_SKIPPED" not in tcl
    assert "global PWRA" in tcl and "global GNDA" in tcl


def test_netgen_setup_still_skips_loudly_with_no_lef() -> None:
    setup = _mod("setup", "lvs_netgen_setup_emit.py")
    tcl = setup.build_supplementary_setup_tcl("custom:pdk")
    assert "LVS_SETUP_SKIPPED" in tcl


def test_netgen_setup_named_pdk_is_unchanged(tmp_path: Path) -> None:
    setup = _mod("setup", "lvs_netgen_setup_emit.py")
    assert (setup.build_supplementary_setup_tcl("sky130A")
            == setup.build_supplementary_setup_tcl(
                "sky130A", cell_lef=_lef(tmp_path)))
