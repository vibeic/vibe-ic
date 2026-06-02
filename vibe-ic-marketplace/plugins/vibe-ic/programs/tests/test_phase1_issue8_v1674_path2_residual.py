"""tests/test_phase1_issue8_v1674_path2_residual.py — v1.6.74

Closes the path-#2 keyword-scan leak surfaced by field agent on
v1.6.73. The path-#1 _has_bus_protocol_evidence gate had reject
regexes (HEADING/MULTI/WRAPPER), but a separate path-#2 keyword
scan did not, so 2/11 thin-input projects (sha256, taxi) still
emitted partial protocol_overview dicts on real-benchmark
verification.

v1.6.74 unifies the rejects: the per-line rejected-context check
now also fires on
  - `interface for/to/with the core` (sha256 wrapper-availability)
  - `interface (provides|wraps|exposes|...)` (sha256 verb form)
  - `(wraps|wrapper|contributed|added|optional|...) (by|via|for|
     to|in|interface|module|the|an?)` (contrib-style attribution)
  - `<acronym> wrappers?` trailing-noun (`includes the AXI4
     wrapper.`)
  - `there is now ... interface` (wrapper-availability prose)
and `_MULTI_ALTERNATIVE_PROTOCOL_RE` now catches `and`-separated
3+ acronym lists including `XFCP`, `Corundum`, `Zircon`, `PCI
express` synonyms.

Durable rule: every regex change ships with a reject-test pair
(`feedback_general_fixes_no_false_alert.md`).
"""
from __future__ import annotations

import json
from pathlib import Path

from programs.phase1_one_shot_runner import gen_l2_frs

_GEN_DIR = Path("phase1") / "generated_docs"


def _seed(tmp_path: Path) -> Path:
    project = tmp_path
    (project / _GEN_DIR).mkdir(parents=True, exist_ok=True)
    return project


def _read(project: Path, name: str) -> dict:
    return json.loads(
        (project / _GEN_DIR / f"{name}.json").read_text(encoding="utf-8")
    )


def test_l2_rejects_axi4_interface_for_the_core_contributed_by(tmp_path):
    """sha256-class line: 'There is now an AXI4 interface for the core
    contributed by ...'. Path #2 must reject."""
    project = _seed(tmp_path)
    extracted = {
        "README.md": (
            "# SHA-256\n\n"
            "Pure FIPS 180-4 hash core.\n\n"
            "There is now an AXI4 interface for the core contributed by "
            "Sanjay. The interface wraps the streaming I/O.\n"
        ),
    }
    gen_l2_frs(project, extracted)
    l2 = _read(project, "L2_FRS")
    assert l2.get("protocol_overview") is None


def test_l2_rejects_includes_axi_wrapper(tmp_path):
    project = _seed(tmp_path)
    extracted = {
        "README.md": (
            "# Some core\nincludes the AXI4 wrapper.\n"
            "Default interface is the streaming I/O port.\n"
        ),
    }
    gen_l2_frs(project, extracted)
    l2 = _read(project, "L2_FRS")
    assert l2.get("protocol_overview") is None


def test_l2_rejects_interface_provides_axi_lite_slave(tmp_path):
    project = _seed(tmp_path)
    extracted = {
        "README.md": (
            "# AES core\nThe interface provides an AXI4-Lite slave "
            "interface with added complete interrupt signal.\n"
        ),
    }
    gen_l2_frs(project, extracted)
    l2 = _read(project, "L2_FRS")
    assert l2.get("protocol_overview") is None


def test_l2_rejects_three_or_more_with_and_separators(tmp_path):
    """Taxi-class line: 'internally via AXI, AXI stream, and APB,
    and externally via Ethernet, PCI express, UART, and I2C'."""
    project = _seed(tmp_path)
    extracted = {
        "README.md": (
            "# Taxi networking\nProvides interfacing, both internally "
            "via AXI, AXI stream, and APB, and externally via "
            "Ethernet, PCI express, UART, and I2C.\n"
        ),
    }
    gen_l2_frs(project, extracted)
    l2 = _read(project, "L2_FRS")
    assert l2.get("protocol_overview") is None


def test_l2_rejects_corundum_zircon_xfcp_axi_pcie_components(tmp_path):
    """Taxi line 5: 'home of Corundum, Zircon, and XFCP, plus AXI,
    AXI stream, Ethernet, and PCIe components'."""
    project = _seed(tmp_path)
    extracted = {
        "README.md": (
            "# Taxi\nThe home of Corundum, Zircon, and XFCP, plus "
            "AXI, AXI stream, Ethernet, and PCIe components in "
            "System Verilog.\n"
        ),
    }
    gen_l2_frs(project, extracted)
    l2 = _read(project, "L2_FRS")
    assert l2.get("protocol_overview") is None


def test_l2_rejects_bridges_for_interfacing_with_axi_apb_i2c(tmp_path):
    """Taxi line 70: 'bridges for interfacing with various devices
    including AXI, AXI-lite, APB, and I2C'."""
    project = _seed(tmp_path)
    extracted = {
        "README.md": (
            "# Taxi\nbridges for interfacing with various devices "
            "including AXI, AXI-lite, APB, and I2C.\n"
        ),
    }
    gen_l2_frs(project, extracted)
    l2 = _read(project, "L2_FRS")
    assert l2.get("protocol_overview") is None


def test_l2_aid_class_rich_input_still_emits_dict(tmp_path):
    """Positive control: rich-input single-wire EXAMPLE_PROTOCOL command bus
    must STILL emit dict in v1.6.74."""
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


def test_l2_aggregate_v1674_path2_no_leak(tmp_path_factory):
    """All v1.6.73 path-#2 leak cases must emit null in v1.6.74."""
    cases = [
        ("sha256",
         "There is now an AXI4 interface for the core contributed by "
         "Sanjay.\n"),
        ("sha256b",
         "The interface provides an AXI4-Lite slave interface.\n"),
        ("sha256c",
         "includes the AXI4 wrapper.\n"),
        ("taxi-l5",
         "The home of Corundum, Zircon, and XFCP, plus AXI, AXI "
         "stream, Ethernet, and PCIe components.\n"),
        ("taxi-l13",
         "internally via AXI, AXI stream, and APB, and externally "
         "via Ethernet, PCI express, UART, and I2C.\n"),
        ("taxi-l70",
         "bridges for interfacing with various devices including "
         "AXI, AXI-lite, APB, and I2C.\n"),
    ]
    leaked = []
    for label, src in cases:
        proj = _seed(tmp_path_factory.mktemp(label))
        gen_l2_frs(proj, {"spec.txt": src})
        l2 = _read(proj, "L2_FRS")
        if l2.get("protocol_overview") is not None:
            leaked.append(label)
    assert not leaked, f"v1.6.74 path-#2 dict leak: {leaked}"
