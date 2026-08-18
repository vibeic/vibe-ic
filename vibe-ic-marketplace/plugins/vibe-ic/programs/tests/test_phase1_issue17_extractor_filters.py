"""tests/test_phase1_issue17_extractor_filters.py — v1.6.85

Closes #17 Bug A2 — phase1 top-port extractor over-collection.

Power rails (VDD/VSS/GND/V_IN/V_OUT/VCC2P5), narrative tokens
(HOST/ATE/GPIO), and the chip's own name (EXAMPLE_CHIP/A1101) must NOT
promote to L1.pin_table or L9.top_ports. Real pin-table rows must
still survive (positive control: id_bus / wake).

Reject-tests are chip-AGNOSTIC: they don't reference any specific
chip's hand-curated wiring; they just check the filter logic on
synthetic narrative.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
PROGRAMS = PLUGIN_ROOT / "programs"
for p in (str(PROGRAMS), str(PLUGIN_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from programs import phase1_one_shot_runner as p2a  # noqa: E402
import pytest

_GEN_DIR = Path("phase1") / "generated_docs"


def _read(project: Path, name: str) -> dict:
    return json.loads((project / _GEN_DIR / f"{name}.json").read_text())


def _seed(project: Path) -> Path:
    (project / _GEN_DIR).mkdir(parents=True, exist_ok=True)
    return project


def test_l1_drops_power_rails_from_pin_table(tmp_path):
    """VDD / GND / V_IN must NOT survive into L1.pin_table even when
    they appear in a row whose mode keyword (POWER/GROUND) matches
    the pin-table line regex."""
    project = _seed(tmp_path / "rails_proj")
    extracted = {
        "datasheet.txt": (
            "EXAMPLE_CHIP Pinout:\n"
            "PIN  NAME    I/O    DESCRIPTION\n"
            "1    VDD     POWER  Power supply\n"
            "2    GND     GROUND Ground\n"
            "3    V_IN    INPUT  Input voltage rail\n"
            "4    id_bus  INOUT  EXAMPLE_PROTOCOL command bus\n"
            "5    wake    INPUT  Wake interrupt\n"
        ),
    }
    p2a.gen_l1_datasheet(project, extracted)
    l1 = _read(project, "L1_DATASHEET")
    names = {p.get("name", "").upper() for p in (l1.get("pin_table") or [])}
    assert "VDD" not in names
    assert "GND" not in names
    assert "V_IN" not in names
    assert "VIN" not in names


def test_l1_drops_chip_name_and_version_codes(tmp_path):
    """The chip's own name (EXAMPLE_CHIP) and version codes (A1101, E4)
    must not promote to pins even when they appear in a pin-table
    row context."""
    project = _seed(tmp_path / "name_proj")
    extracted = {
        "datasheet.txt": (
            "EXAMPLE_CHIP ID IC. Component code A1101 / silicon rev E4.\n"
            "PIN  NAME    I/O    DESCRIPTION\n"
            "1    EXAMPLE_CHIP  INPUT  (caption mention, not a pin)\n"
            "2    A1101   INPUT  (caption mention)\n"
            "3    E4      INPUT  (rev mark)\n"
            "4    id_bus  INOUT  real port\n"
        ),
    }
    p2a.gen_l1_datasheet(project, extracted)
    l1 = _read(project, "L1_DATASHEET")
    names = {p.get("name", "").upper() for p in (l1.get("pin_table") or [])}
    assert "EXAMPLE_CHIP" not in names
    assert "A1101" not in names
    assert "E4" not in names


def test_l1_drops_narrative_tokens(tmp_path):
    """HOST / ATE / GPIO are environment / class words, not chip pins.
    They must not promote even if they happen to appear in a line
    that matches the pin-table line regex."""
    project = _seed(tmp_path / "narrative_proj")
    extracted = {
        "datasheet.txt": (
            "EXAMPLE_CHIP talks to the HOST via the ATE controller.\n"
            "Pin table:\n"
            "PIN  NAME    I/O    DESCRIPTION\n"
            "1    HOST    INPUT  (narrative mention)\n"
            "2    ATE     INPUT  (narrative mention)\n"
            "3    GPIO    INPUT  (generic class mention)\n"
            "4    POR     INPUT  (internal event)\n"
            "5    id_bus  INOUT  real port\n"
        ),
    }
    p2a.gen_l1_datasheet(project, extracted)
    l1 = _read(project, "L1_DATASHEET")
    names = {p.get("name", "").upper() for p in (l1.get("pin_table") or [])}
    assert "HOST" not in names
    assert "ATE" not in names
    assert "GPIO" not in names
    assert "POR" not in names


def test_l1_keeps_real_pin_table_entries(tmp_path):
    """Positive control: real chip-edge pins (id_bus / wake) survive
    the filter — we must not over-prune."""
    project = _seed(tmp_path / "real_proj")
    extracted = {
        "datasheet.txt": (
            "Pin table:\n"
            "PIN  NAME    I/O    DESCRIPTION\n"
            "1    ID_BUS  INOUT  real port\n"
            "2    WAKE    INPUT  real port\n"
            "3    OVP     OUTPUT real port\n"
        ),
    }
    p2a.gen_l1_datasheet(project, extracted)
    l1 = _read(project, "L1_DATASHEET")
    names = {p.get("name", "").upper() for p in (l1.get("pin_table") or [])}
    assert "ID_BUS" in names
    assert "WAKE" in names
    assert "OVP" in names


def test_is_real_port_token_unit():
    """Direct unit test of the chip-AGNOSTIC reject filter."""
    fn = p2a._is_real_port_token
    # Power rails — reject.
    for tok in ("VDD", "VSS", "GND", "V_IN", "V_OUT", "VCC2P5", "VCC1P2_VCC"):
        assert not fn(tok), f"{tok} should be rejected (power rail)"
    # Narrative tokens — reject.
    for tok in ("HOST", "ATE", "GPIO", "POR", "SICP", "IC"):
        assert not fn(tok), f"{tok} should be rejected (narrative)"
    # Version codes — reject.
    for tok in ("EXAMPLE_CHIP", "A1101", "E4", "EXAMPLE_TESTER"):
        assert not fn(tok), f"{tok} should be rejected (version code)"
    # Chip-name — reject when l1_chip_name supplied.
    assert not fn("MYCHIP", l1_chip_name="MYCHIP")
    # Real pin tokens — accept.
    for tok in ("ID_BUS", "WAKE", "OVP", "RX_DATA", "MOSI"):
        assert fn(tok), f"{tok} should be accepted (real pin)"


def test_has_pin_table_anchor_unit():
    """Direct unit test of the structural-anchor helper."""
    fn = p2a._has_pin_table_anchor
    # Lines carrying pin/port/signal/wire/bus/input/output keywords pass.
    assert fn("PIN  NAME  I/O  DESCRIPTION")
    assert fn("Signal id_bus is the EXAMPLE_PROTOCOL command bus")
    assert fn("input wire clk")
    # Bare narrative lines without anchor don't pass.
    assert not fn("EXAMPLE_CHIP talks to the host tester via the ATE controller")
    # Surrounding-line context grants the anchor.
    assert fn("ID_BUS", surrounding_lines=[
        "PIN  NAME  I/O  DESCRIPTION", "1    ID_BUS  INOUT"])
