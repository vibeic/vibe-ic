"""Regression tests for the OCP (Open Core Protocol) detector (protocol #70).

Pins the content-only structural ``is_ocp`` detector: it must FIRE on a genuine
OCP spec (the M/S-prefixed MCmd/SCmdAccept/SResp/MRespAccept signal model) and
NOT fire on the SoC-bus siblings (AXI / AHB / Wishbone / Avalon / TileLink) nor
on a bare "ocp" name token. Doctrine: general-not-keyword, structural-not-name.
"""
from __future__ import annotations

from ocp_protocol_synth import is_ocp


_OCP_SPEC = (
    "The Open Core Protocol (OCP) defines a point-to-point synchronous "
    "master/slave socket. Dataflow signals: MCmd (master command "
    "IDLE/WR/RD/RDEX/WRNP/BCST), MAddr, MData, MByteEn, SCmdAccept (slave "
    "accepts the request), SResp (NULL/DVA/FAIL/ERR), SData, MRespAccept. "
    "Sideband and test signal groups are also defined."
)


def test_fires_on_genuine_ocp_spec():
    assert is_ocp(_OCP_SPEC) is True


def test_does_not_fire_on_bare_name_token():
    assert is_ocp("This SoC uses the OCP bus and ocp wrappers everywhere.") is False


def test_does_not_fire_on_empty():
    assert is_ocp("") is False
    assert is_ocp(None) is False  # type: ignore[arg-type]


def test_mutex_axi_primary():
    blob = (
        "AMBA AXI: five channels AWVALID/AWREADY, WVALID/WREADY, BVALID/BREADY, "
        "ARVALID/ARREADY, RVALID/RREADY. Burst INCR/WRAP/FIXED."
    )
    assert is_ocp(blob) is False


def test_mutex_ahb_primary():
    blob = (
        "AMBA AHB: HADDR, HTRANS, HWRITE, HSIZE, HBURST, HREADY, HRESP. "
        "Pipelined address and data phases."
    )
    assert is_ocp(blob) is False


def test_mutex_wishbone_primary():
    blob = (
        "Wishbone B4: CYC_O, STB_O, ACK_I, ADR_O, DAT_O, DAT_I, WE_O, SEL_O. "
        "OpenCores SoC interconnect."
    )
    assert is_ocp(blob) is False


def test_mutex_avalon_primary():
    blob = (
        "Avalon-MM: address, read, write, readdata, writedata, byteenable, "
        "waitrequest, readdatavalid, burstcount. Platform Designer / Qsys."
    )
    assert is_ocp(blob) is False


def test_mutex_tilelink_primary():
    blob = (
        "TileLink TL-UL / TL-C: Get, Put, Acquire, Release, Grant, Probe. "
        "SiFive on-chip interconnect."
    )
    assert is_ocp(blob) is False


def test_ocp_spec_mentioning_axi_for_comparison_still_fires():
    # An OCP doc that mentions AXI only for comparison must NOT be deferred,
    # because the OCP command core (MCmd/SCmdAccept/SResp/MRespAccept) is present.
    blob = (
        "OCP master drives MCmd; the slave asserts SCmdAccept; the slave drives "
        "SResp; the master asserts MRespAccept. MData/SData/MAddr carry the "
        "transfer. Unlike AXI's ARVALID/RVALID channels, OCP uses M/S-prefixed "
        "signals. dataflow sideband test groups."
    )
    assert is_ocp(blob) is True


def test_does_not_fire_on_unrelated_arithmetic_block():
    blob = (
        "An 8-bit ripple-carry adder with carry-in, carry-out, and sum output. "
        "Two operands a and b are added bit by bit."
    )
    assert is_ocp(blob) is False
