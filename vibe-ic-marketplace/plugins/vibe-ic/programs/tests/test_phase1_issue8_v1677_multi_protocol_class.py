"""tests/test_phase1_issue8_v1677_multi_protocol_class.py — v1.6.77

Closes the multi-protocol-transport-library architectural class
question on issue #8. v1.6.71-76 chased line-level rejects on
taxi/Corundum/XFCP. v1.6.77 adds an upstream IC-class classifier
_is_multi_protocol_transport_library() that detects this class
and forces protocol_overview=null + ic_class_hint, instead of
trying to reject every prose-shape variation.

Trigger requires BOTH a library-marker phrase AND >=4 distinct
protocol acronyms in the source — either alone is too loose.
"""
from __future__ import annotations
import json
from pathlib import Path
from programs.phase1_one_shot_runner import gen_l2_frs

_GEN_DIR = Path("phase1") / "generated_docs"


def _seed(tmp_path):
    project = tmp_path
    (project / _GEN_DIR).mkdir(parents=True, exist_ok=True)
    return project


def _read(project, name):
    return json.loads((project / _GEN_DIR / f"{name}.json").read_text())


def test_l2_taxi_class_transport_library_emits_null_with_class_hint(tmp_path):
    """Taxi-class verbatim README: 'transport library' marker +
    AXI/APB/UART/I2C/Ethernet/PCIe = 6 distinct acronyms.
    Must emit protocol_overview=null + ic_class_hint."""
    project = _seed(tmp_path)
    extracted = {
        "README.md": (
            "# Taxi\n\n"
            "The Taxi transport library is to provide a set of "
            "performant, easy-to-use building blocks for the "
            "construction of complex FPGA-based hardware platforms.\n"
            "Provides interfacing, both internally via AXI, AXI "
            "stream, and APB, and externally via Ethernet, PCI "
            "express, UART, and I2C.\n"
        ),
    }
    gen_l2_frs(project, extracted)
    l2 = _read(project, "L2_FRS")
    assert l2.get("protocol_overview") is None
    assert l2.get("no_protocol_overview_in_input") is True
    assert l2.get("ic_class_hint") == "multi_protocol_transport_library"


def test_l2_corundum_class_platform_for_in_network_compute(tmp_path):
    """Corundum-class: 'platform for in-network compute' marker +
    Ethernet/PCIe/PCI express/AXI/UART >= 4 distinct acronyms."""
    project = _seed(tmp_path)
    extracted = {
        "README.md": (
            "# Corundum\n\n"
            "Corundum is an open-source FPGA-based NIC and "
            "platform for in-network compute. Features include "
            "10G/25G/100G Ethernet, PCI express gen 3+, AXI "
            "stream interconnect, AXI-lite control bus, UART "
            "console.\n"
        ),
    }
    gen_l2_frs(project, extracted)
    l2 = _read(project, "L2_FRS")
    assert l2.get("protocol_overview") is None
    assert l2.get("ic_class_hint") == "multi_protocol_transport_library"


def test_l2_aid_class_rich_input_does_NOT_trigger(tmp_path):
    """Positive control: rich-input EXAMPLE_PROTOCOL-class IC must NOT match
    the multi-protocol classifier even though it has a few
    AXI/SPI references in calibration sections. Marker phrases
    don't fire on a normal datasheet."""
    project = _seed(tmp_path)
    extracted = {
        "datasheet.txt": (
            "EXAMPLE_CHIP ID IC over a single-wire EXAMPLE_PROTOCOL command bus.\n"
            "Half-duplex frames carry opcodes and responses.\n"
            "Wake pulse required before each command.\n"
            "Optional SPI debug interface for calibration.\n"
        ),
    }
    gen_l2_frs(project, extracted)
    l2 = _read(project, "L2_FRS")
    po = l2.get("protocol_overview")
    # Should still emit dict for the EXAMPLE_PROTOCOL-class IC.
    assert po is not None
    assert po["half_duplex"] is True
    assert l2.get("ic_class_hint") != "multi_protocol_transport_library"


def test_l2_single_protocol_library_does_NOT_trigger(tmp_path):
    """Reject case: a UART-only library has no marker phrase and
    only 1 distinct protocol → does NOT match the classifier.
    Asserts ic_class_hint is NOT set."""
    project = _seed(tmp_path)
    extracted = {
        "README.md": (
            "# UartLib\n\n"
            "An open-source library for UART communication. "
            "Provides UART transmit and receive blocks.\n"
        ),
    }
    gen_l2_frs(project, extracted)
    l2 = _read(project, "L2_FRS")
    # Outcome of protocol_overview itself depends on other gates;
    # the only assertion is that ic_class_hint is NOT set.
    assert l2.get("ic_class_hint") != "multi_protocol_transport_library"


def test_l2_marker_phrase_alone_without_4_protocols_does_NOT_trigger(tmp_path):
    """Reject case: a real transport library with only 2 protocols
    (AXI + APB) has the marker phrase but doesn't qualify as
    multi-protocol."""
    project = _seed(tmp_path)
    extracted = {
        "README.md": (
            "# AXIBridge\n\n"
            "A transport library providing an AXI-to-APB bridge "
            "for SoC integration.\n"
        ),
    }
    gen_l2_frs(project, extracted)
    l2 = _read(project, "L2_FRS")
    assert l2.get("ic_class_hint") != "multi_protocol_transport_library"


def test_l2_4_protocols_alone_without_marker_does_NOT_trigger(tmp_path):
    """Reject case: a normal IC datasheet that happens to mention
    4 protocols in pin descriptions but has no library-marker
    phrase. Must NOT classify as multi-protocol library."""
    project = _seed(tmp_path)
    extracted = {
        "datasheet.txt": (
            "ASIC1234 datasheet.\n"
            "Pin 1: SPI MOSI input.\n"
            "Pin 2: I2C SDA bidirectional.\n"
            "Pin 3: UART TX output.\n"
            "Pin 4: AXI clk reference.\n"
        ),
    }
    gen_l2_frs(project, extracted)
    l2 = _read(project, "L2_FRS")
    assert l2.get("ic_class_hint") != "multi_protocol_transport_library"


def test_l2_count_distinct_protocols_word_bounded(tmp_path):
    """Helper sanity: AXI / AXI-lite / AXI stream all collapse to
    the single AXI acronym for the distinct count."""
    from programs.phase1_one_shot_runner import _count_distinct_protocols
    text = "Supports AXI, AXI-lite, and AXI stream wrappers."
    assert _count_distinct_protocols(text) == 1
    text = "Supports AXI, APB, UART, I2C, and Ethernet."
    assert _count_distinct_protocols(text) == 5
