"""ORGANIC #611 [HIGH] — the L1->L9 port promoter's version-code rejector
dropped banked/enumerated top ports (PREFIX+digit) that the banked-pin
expander deliberately enumerated.

`_CHIP_VERSION_CODE_RE = ^[A-Z]+\\d+[A-Z0-9]*$` matched IN1..IN6 / OUT1..OUT6 /
CK4..CK6 and `_is_real_port_token` dropped them as part-numbers — even though
`_v455_expand_pin_token` had just enumerated them into L1.pin_table with
`_extraction='backticked_interface_v455'` (∈ _PORT_TABLE_STRATEGIES). A VREF
reference INPUT was also dropped by _POWER_RAIL_TOKENS. L9.top_ports under-counted.

POSITIVE: a banked/port-table-provenance pin (IN1/OUT6/CK4) is now promoted;
a VREF with a functional input direction is no longer dropped as a supply.

NEGATIVE no-leak (the relaxation must stay provenance-gated, not blanket):
a real version-code WITHOUT port-table provenance is STILL rejected; a genuine
supply WITHOUT a functional direction is STILL dropped; the 2-arg callsites
(pin defaulting to None) behave exactly as before.

chip-AGNOSTIC: keys on extraction provenance + functional direction, never on
chip/port names.
"""
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import phase1_doc_one_shot_runner as P  # noqa: E402

_BANKED = {"_extraction": "backticked_interface_v455", "mode": "input"}


# --- POSITIVE: provenance / functional-direction exemptions fire -----------
def test_banked_member_with_port_table_provenance_promoted():
    for name in ("IN1", "IN6", "OUT1", "OUT6", "CK4", "CK6"):
        assert P._CHIP_VERSION_CODE_RE.match(name), f"{name} must look like a version code"
        assert P._is_real_port_token(name, pin=_BANKED) is True, (
            f"banked/port-table pin {name} must be promoted, not dropped (#611)")


def test_vref_input_not_dropped_as_power_rail():
    assert "VREF" in P._POWER_RAIL_TOKENS
    assert P._is_real_port_token("VREF", pin={"mode": "input"}) is True, (
        "a VREF reference INPUT is a functional port, not a supply rail (#611)")


# --- NEGATIVE no-leak: the guards still fire without the corroborating signal
def test_version_code_without_port_table_provenance_still_rejected():
    # prose-walker provenance is NOT a structured port table → still screened
    assert P._is_real_port_token("A1101", pin={"_extraction": "some_prose_walker"}) is False
    assert P._is_real_port_token("E4", pin={"mode": "input"}) is False, (
        "functional direction must NOT exempt the version-code shape — only "
        "port-table provenance does")


def test_supply_without_functional_direction_still_dropped():
    assert P._is_real_port_token("VDD") is False
    assert P._is_real_port_token("VSS", pin={"mode": "power"}) is False, (
        "a non-functional 'power' mode must not rescue a supply rail")
    # provenance alone (no functional dir) must NOT rescue a supply rail
    assert P._is_real_port_token("VDD", pin=_BANKED | {"mode": "power"}) is False


def test_two_arg_callsites_unchanged():
    # the other _is_real_port_token callsites pass (tok, ic_name) with pin=None
    assert P._is_real_port_token("IN1") is False
    assert P._is_real_port_token("IN1", "somechip") is False
    # a normal functional port name is still accepted
    assert P._is_real_port_token("dout") is True
