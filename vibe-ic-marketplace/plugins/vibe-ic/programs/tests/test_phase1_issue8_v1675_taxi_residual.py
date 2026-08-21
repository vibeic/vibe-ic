"""tests/test_phase1_issue8_v1675_taxi_residual.py — v1.6.75

Closes the taxi-only residual surfaced by field agent on v1.6.74.
v1.6.74 closed sha256; taxi has 5 lines with `interface for/to <PROTOCOL>`
shape that v1.6.74's reject set doesn't cover. v1.6.75 adds 3 new
rejects: INTERFACE_FOR_PROTOCOL, INCLUDES_INTERFACE_FOR_PROTOCOL,
PROVIDING_PROTOCOL_INTERFACE.
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


def test_l2_rejects_providing_axi_lite_register_interface(tmp_path):
    """taxi line 60: providing an AXI-lite register interface."""
    project = _seed(tmp_path)
    extracted = {
        "README.md": (
            "# Taxi\nproviding an AXI-lite register interface to "
            "read the counters.\n"
        ),
    }
    gen_l2_frs(project, extracted)
    l2 = _read(project, "L2_FRS")
    assert l2.get("protocol_overview") is None


def test_l2_rejects_includes_interface_modules_for_uart(tmp_path):
    """taxi line 70: XFCP includes an interface modules for UART."""
    project = _seed(tmp_path)
    extracted = {
        "README.md": (
            "# Taxi\nXFCP includes an interface modules for UART, "
            "a parametrizable arbiter.\n"
        ),
    }
    gen_l2_frs(project, extracted)
    l2 = _read(project, "L2_FRS")
    assert l2.get("protocol_overview") is None


def test_l2_rejects_sv_interface_for_axi(tmp_path):
    """taxi lines 86 / 96 / 106: SV interface for AXI [lite|stream]."""
    project = _seed(tmp_path)
    extracted = {
        "README.md": (
            "# Taxi\n"
            "* SV interface for AXI\n"
            "* SV interface for AXI lite\n"
            "* SV interface for AXI stream\n"
        ),
    }
    gen_l2_frs(project, extracted)
    l2 = _read(project, "L2_FRS")
    assert l2.get("protocol_overview") is None


def test_l2_aid_class_rich_input_still_emits_dict(tmp_path):
    """Positive control: rich-input single-wire EXAMPLE_PROTOCOL command bus
    must STILL emit dict in v1.6.75."""
    project = _seed(tmp_path)
    extracted = {
        "datasheet.txt": (
            "EXAMPLE_CHIP ID IC over a single-wire EXAMPLE_PROTOCOL command bus.\n"
            "Half-duplex frames carry opcodes and responses.\n"
            "Wake pulse required before each command.\n"
        ),
    }
    gen_l2_frs(project, extracted)
    l2 = _read(project, "L2_FRS")
    po = l2.get("protocol_overview")
    assert po is not None
    assert po["half_duplex"] is True
    assert po["wire_count"] == 1


def test_l2_aggregate_v1675_taxi_no_leak(tmp_path_factory):
    """All 5 taxi v1.6.74 leak lines must emit null in v1.6.75."""
    cases = [
        ("l60",  "providing an AXI-lite register interface to read the counters.\n"),
        ("l70",  "XFCP includes an interface modules for UART, a parametrizable arbiter.\n"),
        ("l86",  "SV interface for AXI\n"),
        ("l96",  "SV interface for AXI lite\n"),
        ("l106", "SV interface for AXI stream\n"),
    ]
    leaked = []
    for label, src in cases:
        proj = _seed(tmp_path_factory.mktemp(label))
        gen_l2_frs(proj, {"spec.txt": src})
        l2 = _read(proj, "L2_FRS")
        if l2.get("protocol_overview") is not None:
            leaked.append(label)
    assert not leaked, f"v1.6.75 taxi leak: {leaked}"
