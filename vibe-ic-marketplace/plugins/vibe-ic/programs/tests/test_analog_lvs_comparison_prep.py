#!/usr/bin/env python3
"""A sign-off LVS deck reads a netlist; the flow writes one for a simulator.

Every case below is a reduction of a measured refusal of this campaign's two
analog blocks by the PDK's OWN KLayout LVS runset — and every one of them was a
mismatch of CONVENTION, not a design defect: once prepared, the same deck
reports zero mismatched nets, devices and pins for both blocks.

chip/PDK-AGNOSTIC: no design or PDK name is required by any assertion here.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import analog_lvs_comparison_prep as P  # noqa: E402


NETLIST = """* a block
* _provenance: role_models={'cap': 'cmim', 'nmos': 'nfet', 'pmos': 'pfet', 'res': 'rpoly'}
.lib /somewhere/cornerMOS.lib mos_tt
.include /somewhere/extra.spice
.subckt blk vdd vss vin vout
xmn1 vout vin vss vss nfet w=8u l=1u
xmp1 vout vin vdd vdd pfet w=4u l=1u
xr1 vout vss vss rpoly w=0.5u l=115.384u
xc1 vout vss cmim w=10u l=10u
xsub1 vout vin some_other_block
.ends blk
"""


def test_ports_come_from_the_blocks_own_subckt_line():
    assert P.declared_ports(NETLIST, "blk") == ["vdd", "vss", "vin", "vout"]
    assert P.declared_ports(NETLIST, "not_this_block") == []


def test_role_models_are_read_from_the_designs_own_provenance():
    assert P.role_models(NETLIST) == {
        "cap": "cmim", "nmos": "nfet", "pmos": "pfet", "res": "rpoly"}
    letters = P.model_element_letters(P.role_models(NETLIST))
    assert letters == {"cmim": "C", "nfet": "M", "pfet": "M", "rpoly": "R"}


def test_device_calls_become_element_lines():
    """The measured failure: read as subcircuit calls, a block's devices become
    empty circuits and the top cell pairs against NOTHING (`CIRCUIT <blk> <->
    None` in the cross-reference)."""
    text, n = P.device_calls_to_elements(
        NETLIST, P.model_element_letters(P.role_models(NETLIST)))
    assert n == 4
    assert "Mmn1 vout vin vss vss nfet w=8u l=1u" in text
    assert "Rr1 vout vss vss rpoly w=0.5u l=115.384u" in text
    assert "Cc1 vout vss cmim w=10u l=10u" in text


def test_an_unmapped_model_is_left_alone_not_guessed():
    """`xsub1 … some_other_block` is a real subcircuit call, not a device. A
    rewrite under a guessed letter would invent a device that is not there."""
    text, _n = P.device_calls_to_elements(
        NETLIST, P.model_element_letters(P.role_models(NETLIST)))
    assert "xsub1 vout vin some_other_block" in text


def test_model_libraries_are_dropped():
    """LVS compares topology and never evaluates a model; the deck's SPICE
    reader aborted on the first model card it could not parse, killing the run
    before extraction."""
    text, n = P.strip_model_libraries(NETLIST)
    assert n == 2
    assert ".lib" not in text and ".include" not in text
    assert ".subckt blk" in text


def test_prepare_composes_all_three_and_snaps_the_grid():
    text, stats = P.prepare_source_netlist(NETLIST, "blk")
    assert stats == {"model_libraries_dropped": 2,
                     "device_calls_rewritten": 4,
                     "models_mapped": 4}
    # the drawn mask is on the grid and the declared parameter was not: the
    # deck reported the resistor pair as MatchWithWarning and three nets as
    # mismatched until the comparison side was quantized.
    assert "l=115.38u" in text
    assert "l=115.384u" not in text


def test_prepare_is_a_no_op_on_a_netlist_that_declares_no_roles():
    """No role provenance -> no mapping -> nothing rewritten. Refusing to guess
    is the same rule the DRC engine dispatch uses for an unknown deck."""
    plain = ".subckt blk a b\nxq1 a b widget\n.ends blk\n"
    text, stats = P.prepare_source_netlist(plain, "blk")
    assert stats["device_calls_rewritten"] == 0
    assert "xq1 a b widget" in text


def test_the_port_only_script_keeps_ports_and_only_in_the_top_cell():
    """Both halves are measured. Keeping every label made a 4-port block
    present 9 pins (a port mismatch in the deck's strict mode); stripping child
    labels too cost the device gencells their terminal identity, and the
    resistor pair then matched in the wrong orientation."""
    src = P.PORT_ONLY_LAYOUT_SCRIPT
    assert "if c.name not in tops" in src
    assert "continue" in src
    assert "s.text.string in want" in src
