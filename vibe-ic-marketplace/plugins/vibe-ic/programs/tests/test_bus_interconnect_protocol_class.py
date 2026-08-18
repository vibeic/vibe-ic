"""Tests for v0.1.62 R12 capture: bus_interconnect_protocol ic_class +
structural detector.

Captured from AMBA AXI IHI0022H parity run: the runner previously
mis-classified the spec as digital_arithmetic_primitive (because no L3
command protocol + no analog), triggering OTP/chip-template L1/L2
over-fill. The bus_interconnect_protocol class + structural detector
correctly routes such specs.

Doctrine: detector uses SHAPE (≥3 of 6 structural features in L1+L2 text)
not BRAND NAMES — no `re.search('AMBA')` etc. Pytest pins that no
benchmark-keyword regex is used.
"""
import importlib
import json
import re
import sys
from pathlib import Path
from _hostpaths import require_repo  # noqa: E402

PROGRAMS = Path(__file__).resolve().parents[1]


def _load():
    if "ic_class_profile" in sys.modules:
        del sys.modules["ic_class_profile"]
    sys.path.insert(0, str(PROGRAMS))
    return importlib.import_module("ic_class_profile")


# ── Registry entry ────────────────────────────────────────────────────

def test_registry_has_bus_interconnect_protocol_entry():
    reg = json.loads((PROGRAMS / "ic_class_registry.json").read_text())
    names = [c["name"] for c in reg["classes"]]
    assert "bus_interconnect_protocol" in names


def test_registry_entry_flags_are_correct():
    reg = json.loads((PROGRAMS / "ic_class_registry.json").read_text())
    entry = next(c for c in reg["classes"]
                 if c["name"] == "bus_interconnect_protocol")
    assert entry["command_protocol_applicable"] is False, (
        "bus protocols are not SW-opcode-driven; payload is data")
    assert entry["analog_applicable"] is False
    assert entry["half_duplex_bus"] is False
    assert entry["rtl_gen"] is None  # spec docs don't have an RTL generator
    assert entry["fallback_skill"] == "spec-to-rtl"


def test_class_verification_flags_match_registry():
    mod = _load()
    flags = mod.class_verification_flags("bus_interconnect_protocol")
    assert flags["registry_matched"] is True
    assert flags["command_protocol_applicable"] is False
    assert flags["analog_applicable"] is False


# ── Detector: structural features ─────────────────────────────────────

def test_detector_general_not_brand_keyword():
    """Per memory: 'enhancements must be general, not keyword'. The
    detector's regex catalog must NOT contain brand names (AMBA, AXI,
    AHB, APB, Wishbone, TileLink, ACE, CHI). Anyone reading the source
    must see SHAPE patterns only.

    WHOLE WORDS, not substrings. The bare-substring form of this check
    fired on the word "chip" (`CHI` inside `chip`) the first time ordinary
    prose was added to this block — and it would equally have fired on
    "interface", "replace" or "trace" for `ACE`. A brand name appears in a
    regex catalog as a token, so a token is what is searched for; matching
    inside longer words made the check reject the one vocabulary a chip
    classifier cannot avoid."""
    mod = _load()
    src = (PROGRAMS / "ic_class_profile.py").read_text()
    forbidden = ["AMBA", "AXI", "AHB", "APB", "ACE",
                 "Wishbone", "TileLink", "CHI", "AvalonMM"]
    detector_block_start = src.find("_BUS_PROTO_FEATURES")
    detector_block_end = src.find("def _looks_like_bus_interconnect_protocol")
    block = src[detector_block_start:detector_block_end]
    for brand in forbidden:
        assert not re.search(rf"\b{re.escape(brand)}\b", block, re.I), (
            f"bench-keyword {brand!r} found in detector regex block; "
            f"per memory enhancements must be general, not keyword.")


def test_detector_real_amba_axi_l_docs_trigger():
    """The real benchmark_phase1/arm_aix L1/L2 must trigger the detector."""
    mod = _load()
    arm = require_repo("benchmark-data/evaluation/phase1_parity/arm_aix/phase1/generated_docs")
    if not arm.is_dir():
        import pytest
        pytest.skip("AMBA AXI benchmark not present on this host")
    l1 = json.loads((arm / "L1_DATASHEET.json").read_text())
    l2 = json.loads((arm / "L2_FRS.json").read_text())
    assert mod._looks_like_bus_interconnect_protocol(l1, l2) is True


def test_detector_adder_negative():
    """A pure digital adder's L1/L2 must NOT trigger."""
    mod = _load()
    l1 = {"description": "8-bit adder with carry-in. Combinational logic.",
          "pin_table": [{"name": "a"}, {"name": "b"}, {"name": "sum"}, {"name": "cin"}]}
    l2 = {"description": "Pure combinational adder. No state, no protocol."}
    assert mod._looks_like_bus_interconnect_protocol(l1, l2) is False


def test_detector_otp_with_isolated_slave_mention_negative():
    """An OTP IC that uses the word 'slave' but doesn't have channels +
    burst + interconnect must NOT trigger (slave alone is not enough)."""
    mod = _load()
    l1 = {"description": "OTP IC."}
    l2 = {"description": "Half-duplex protocol. Host issues opcodes; "
                          "slave IC responds with status byte."}
    assert mod._looks_like_bus_interconnect_protocol(l1, l2) is False


def test_detector_amplifier_negative():
    """An analog amplifier description must NOT trigger."""
    mod = _load()
    l1 = {"description": "Class-D audio amplifier with 20W output, "
                          "differential input, single-ended output."}
    l2 = {"description": "Closed-loop feedback, PWM modulator at 384kHz."}
    assert mod._looks_like_bus_interconnect_protocol(l1, l2) is False


def test_detector_synthetic_minimal_protocol_positive():
    """A minimal protocol spec mentioning the structural features (≥4 of 6
    + ≥2 named channels) must trigger. v0.1.79 tightened the detector so
    single-data-line serial peripherals (I2C/SPI/UART) that happen to
    mention 'master/slave' + 'arbitration' do NOT mis-classify; only
    multi-channel bus protocols with EXPLICIT NAMED CHANNELS qualify."""
    mod = _load()
    l1 = {"description": "Bus protocol IP"}
    l2 = {"description": "Five channels — read channel, write channel, "
                          "address channel, response channel — carry "
                          "valid/ready handshakes. Master and slave roles. "
                          "Burst transfers supported. Interconnect "
                          "arbitration."}
    assert mod._looks_like_bus_interconnect_protocol(l1, l2) is True


# ── End-to-end class assignment ───────────────────────────────────────

def test_detect_ic_class_routes_amba_axi_to_bus_protocol(tmp_path):
    """The full detect_ic_class on the AMBA AXI L docs must return
    'bus_interconnect_protocol', not 'digital_arithmetic_primitive'."""
    mod = _load()
    arm = require_repo("benchmark-data/evaluation/phase1_parity/arm_aix")
    if not (arm / "phase1" / "generated_docs" / "L1_DATASHEET.json").is_file():
        import pytest
        pytest.skip("AMBA AXI benchmark not present on this host")
    # Stage a project that points at the AMBA AXI generated_docs
    proj = tmp_path / "p"
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    for f in (arm / "phase1" / "generated_docs").glob("L*.json"):
        (proj / "phase1" / "generated_docs" / f.name).write_text(f.read_text())
    profile = mod.detect_ic_class(proj)
    assert profile["ic_class"] == "bus_interconnect_protocol", (
        f"AMBA AXI mis-routed to {profile['ic_class']!r}; expected "
        f"bus_interconnect_protocol")


def test_pure_digital_arithmetic_still_routes_correctly(tmp_path):
    """ANTI-REGRESSION: the new branch must not eat a real adder/multiplier.
    Stage a minimal arithmetic-primitive L1+L2 → digital_arithmetic_primitive."""
    mod = _load()
    proj = tmp_path / "p"
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L1_DATASHEET.json").write_text(json.dumps({
        "ic_name": "adder_8bit",
        "pin_table": [{"name": "a"}, {"name": "b"}, {"name": "sum"}],
        "description": "8-bit adder. Pure combinational. No protocol.",
    }))
    (gd / "L2_FRS.json").write_text(json.dumps({
        "protocol_overview": "Combinational data transform. sum = a + b. No state.",
    }))
    profile = mod.detect_ic_class(proj)
    assert profile["ic_class"] == "digital_arithmetic_primitive", (
        f"Adder mis-routed to {profile['ic_class']!r}; expected "
        f"digital_arithmetic_primitive (must stay in fallback branch).")
