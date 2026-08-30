#!/usr/bin/env python3
"""The supply voltage must come from the library, not from a constant.

eda_ir_drop declared `voltage: z.number().default(1.8)` while `pdk` defaults to
"gf180", whose Liberty this same file selects as
gf180mcu_fd_sc_mcu7t5v0__tt_025C_3v30.lib. The default run therefore fed
`set_pdnsim_net_voltage -net VDD -voltage 1.8` into a 3.3 V library, and nothing
compared the two.

That matters because PSM does not measure the supply — it echoes the caller's
value back:

    Supply voltage   : 1.80e+00 V

and computes `Percentage drop` against it. So the caller's assumption is
reported as if it were a measurement, and a wrong value silently rescales the
answer.

MEASURED nom_voltage of the three shipped PDKs:

    gf180      3.3    <- pdk default; the 1.8 default was wrong here
    nangate45  1.1    <- also wrong
    sky130     1.8    <- the only one the constant happened to match

The constant was wrong for TWO of the three PDKs. The fix makes `voltage`
optional and resolves it from the Liberty about to be loaded; an explicitly
supplied value is still honoured (an off-nominal corner is legitimate) but is
cross-checked and warned about on disagreement. An unreadable nom_voltage is an
unknown, not a disagreement, and falls back to 1.8 flagged as ASSUMED.

FALSIFIED, live (192.168.1.121, sky130A, pdn_pnr.def):
  no voltage supplied -> voltage_v 1.8, lib_nom 1.8, source liberty_nom_voltage,
                         no mismatch
  voltage 3.3 supplied -> voltage_v 3.3, lib_nom 1.8, mismatch:true + a warning
                          naming both values and the Liberty
  voltage 1.8 supplied -> agrees, no warning
  and per-PDK resolution: gf180 3.3, nangate45 1.1, sky130 1.8
"""
import re
from pathlib import Path

MCP_ROOT = Path(__file__).resolve().parents[1]
SRC = (MCP_ROOT / "src" / "index.js").read_text()


def _tool(name: str) -> str:
    i = SRC.find(f'"{name}"')
    assert i > 0, f"tool {name} not found"
    j = SRC.find("server.tool(", i)
    return SRC[i:j if j > 0 else len(SRC)]


def test_voltage_is_not_a_hardcoded_default_any_more():
    t = _tool("eda_ir_drop")
    assert "voltage: z.number().default(1.8)" not in t, (
        "voltage still defaults to a constant 1.8 while pdk defaults to gf180, "
        "whose Liberty is characterised at 3.3 V"
    )
    assert "voltage: z.number().optional()" in t


def test_the_supply_is_resolved_from_the_liberty():
    assert "function libNomVoltage(cfg)" in SRC, "nothing reads nom_voltage"
    assert "nom_voltage" in SRC
    t = _tool("eda_ir_drop")
    assert "const nomVoltage = libNomVoltage(cfg);" in t
    assert "const effVoltage = voltageSupplied ? voltage" in t
    # and the resolved value, not the raw param, is what PSM is told
    assert "-voltage ${effVoltage}" in t
    assert "-voltage ${voltage}" not in t


def test_a_supplied_voltage_is_honoured_but_cross_checked():
    t = _tool("eda_ir_drop")
    assert "const voltageMismatch =" in t
    assert "voltageSupplied && nomVoltage !== null" in t, (
        "an unreadable nom_voltage must not be reported as a disagreement"
    )
    assert "voltage_mismatch" in t and "lib_nom_voltage_v" in t
    assert "voltage_source" in t
    # the warning must name both numbers so the reader can judge
    assert "is characterised at nom_voltage" in t


def test_an_assumed_voltage_says_so():
    t = _tool("eda_ir_drop")
    assert "const voltageAssumed = !voltageSupplied && nomVoltage === null;" in t
    assert "ASSUMED" in t
    assert '"assumed_default"' in t


def test_the_tolerance_is_relative_and_cannot_divide_by_zero():
    t = _tool("eda_ir_drop")
    m = re.search(r"Math\.abs\(voltage - nomVoltage\) > ([^;]+)\);", t)
    assert m, "the mismatch tolerance is not an explicit expression"
    tol = m.group(1)
    assert "0.01" in tol, f"tolerance is not 1% of nominal: {tol}"
    assert "Math.max" in tol, f"a nom_voltage of 0 would make the tolerance 0: {tol}"
