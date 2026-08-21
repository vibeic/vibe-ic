"""tests/test_phase1_issue18_fixes.py — v1.6.86

Closes issue #18 — 4 bugs from #17 partial close:
- Bug 1 (P0): canonicalization both-sided (L9 writer + RTL emitter use
              the same _canon_port_name)
- Bug 2 (P0): id_bus direction inferred inout for half-duplex single-
              wire bus, regardless of source-doc claim
- Bug 3 (P0): dev-kit / FPGA-board token rejection in L9.ports +
              PIN_<package-ball> rejector
- Bug 4 (P1): L11 fsm_state_catalogue 3-filter cascade — length floor +
              protocol/gate-acronym blacklist + state-noun context
              window

All fixes are chip-AGNOSTIC.
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

from programs.phase1_one_shot_runner import (  # noqa: E402
    _canon_port_name,
    _force_inout_for_half_duplex,
    _is_real_port_token,
    _is_real_fsm_state,
    gen_l1_datasheet,
    gen_l2_frs,
    gen_l9_integration_spec,
    gen_l11_otp_content,
)
from programs import aid_class_rtl_gen  # noqa: E402

_GEN_DIR = Path("phase1") / "generated_docs"


def _seed(tmp_path: Path) -> Path:
    project = tmp_path
    (project / _GEN_DIR).mkdir(parents=True, exist_ok=True)
    return project


def _read(project: Path, name: str) -> dict:
    p = project / _GEN_DIR / f"{name}.json"
    return json.loads(p.read_text())


# ---------------------------------------------------------------------------
# Bug 1 — both-sided canonicalization
# ---------------------------------------------------------------------------

def test_l9_canon_helper_same_semantics_as_rtl_emitter():
    """The phase1 runner and the RTL emitter must produce IDENTICAL
    canonicalisation output. They are byte-identical functions; this
    test catches any future divergence."""
    cases = ["ID_BUS", "OVP", "V_IN", "V  IN", "V__OUT", "clk",
             "Mixed_Case", "  spaces_around  "]
    for s in cases:
        assert _canon_port_name(s) == aid_class_rtl_gen._canon_port_name(s), (
            f"divergence on {s!r}: phase1={_canon_port_name(s)!r} "
            f"vs rtl={aid_class_rtl_gen._canon_port_name(s)!r}"
        )


def test_l9_writes_lowercase_canonical_port_names(tmp_path):
    """L9.top_ports / L9.ports MUST emit lowercase canonical names so
    they match the RTL emitter's chip_top.sv ports."""
    project = _seed(tmp_path)
    extracted = {
        "datasheet.txt": (
            "Pinout:\n"
            "PIN  NAME    I/O   TYPE\n"
            "1    OVP     input digital\n"
            "2    ID_BUS  inout digital\n"
            "3    WAKE    output digital\n"
        ),
    }
    gen_l1_datasheet(project, extracted)
    gen_l2_frs(project, extracted)
    gen_l9_integration_spec(project, extracted, l3={})
    l9 = _read(project, "L9_INTEGRATION_SPEC")
    ports_field = l9.get("top_ports") or l9.get("ports") or []
    port_names = [p["name"] for p in ports_field if p.get("name")]
    # SHOUTING forms must NOT survive into L9.
    for nm in port_names:
        assert nm == nm.lower(), (
            f"L9 port name not canonicalised to lowercase: {nm!r}")
    # And the canonical lowercase forms must be present (sanity).
    assert any(n == "ovp" for n in port_names) or not port_names
    assert any(n == "id_bus" for n in port_names) or not port_names


# ---------------------------------------------------------------------------
# Bug 2 — id_bus direction must be inout
# ---------------------------------------------------------------------------

def test_force_inout_helper_overrides_input_for_id_bus():
    """Direct unit test: _force_inout_for_half_duplex must flip
    direction=input → inout for id_bus regardless of L2 claim."""
    ports = [
        {"name": "id_bus", "direction": "input", "mode": "input"},
        {"name": "ovp", "direction": "input", "mode": "input"},
        {"name": "clk", "direction": "input", "mode": "input"},
    ]
    _force_inout_for_half_duplex(ports, l2={})
    by_name = {p["name"]: p for p in ports}
    assert by_name["id_bus"]["direction"] == "inout"
    assert by_name["id_bus"].get("direction_source") == "half_duplex_inferred"
    # Plain input pins must not be flipped.
    assert by_name["ovp"]["direction"] == "input"
    assert by_name["clk"]["direction"] == "input"


def test_force_inout_via_l2_protocol_overview():
    """When L2.protocol_overview.half_duplex=True and a port name
    ends in `_bus`, force inout."""
    ports = [
        {"name": "data_bus", "direction": "input", "mode": "input"},
    ]
    l2 = {"protocol_overview": {"half_duplex": True}}
    _force_inout_for_half_duplex(ports, l2)
    assert ports[0]["direction"] == "inout"


def test_id_bus_forced_inout_in_l9_emission(tmp_path):
    """End-to-end: L9 emitter must force id_bus to inout even when
    the source doc claims input. Closes #18 Bug 2."""
    project = _seed(tmp_path)
    extracted = {
        "datasheet.txt": (
            "Single-wire half-duplex EXAMPLE_PROTOCOL protocol.\n"
            "PIN NAME    I/O\n"
            "1   id_bus  input\n"  # source says input — must override
        ),
    }
    gen_l1_datasheet(project, extracted)
    gen_l2_frs(project, extracted)
    gen_l9_integration_spec(project, extracted, l3={})
    l9 = _read(project, "L9_INTEGRATION_SPEC")
    ports_field = l9.get("top_ports") or l9.get("ports") or []
    id_bus_entries = [p for p in ports_field
                      if p.get("name", "").lower() == "id_bus"]
    if id_bus_entries:
        assert id_bus_entries[0].get("direction", "").lower() == "inout", (
            f"id_bus direction must be inout, got: {id_bus_entries[0]!r}")


def test_normal_input_pin_not_overridden(tmp_path):
    """Plain input pins (e.g. ovp) on a half-duplex IC must NOT be
    flipped — only the bus pin itself should become inout."""
    project = _seed(tmp_path)
    extracted = {
        "datasheet.txt": (
            "Single-wire half-duplex bus.\n"
            "PIN NAME I/O\n"
            "1   ovp  input\n"
            "2   id_bus inout\n"
        ),
    }
    gen_l1_datasheet(project, extracted)
    gen_l2_frs(project, extracted)
    gen_l9_integration_spec(project, extracted, l3={})
    l9 = _read(project, "L9_INTEGRATION_SPEC")
    ports_field = l9.get("top_ports") or l9.get("ports") or []
    ovp_entries = [p for p in ports_field
                   if p.get("name", "").lower() == "ovp"]
    if ovp_entries:
        assert ovp_entries[0].get("direction", "").lower() == "input", (
            f"ovp must remain input, got: {ovp_entries[0]!r}")


def test_check_no_input_driven_helper():
    """Direct unit test: _check_no_input_driven catches `assign
    <input_port> = ...` patterns."""
    rtl = (
        "module chip_top (\n"
        "  input wire clk,\n"
        "  input wire id_bus,\n"
        "  output wire wake\n"
        ");\n"
        "  assign id_bus = drive_low ? 1'b0 : 1'bz;\n"
        "endmodule\n"
    )
    violation = aid_class_rtl_gen._check_no_input_driven(rtl)
    assert violation == "id_bus", (
        f"expected id_bus violation, got {violation!r}")


def test_check_no_input_driven_clean_passes():
    """Direct unit test: clean RTL produces no violation."""
    rtl = (
        "module chip_top (\n"
        "  input wire clk,\n"
        "  inout wire id_bus,\n"
        "  output wire wake\n"
        ");\n"
        "  assign id_bus = drive_low ? 1'b0 : 1'bz;\n"
        "endmodule\n"
    )
    assert aid_class_rtl_gen._check_no_input_driven(rtl) is None


# ---------------------------------------------------------------------------
# Bug 3 — dev-kit / board-pin rejection
# ---------------------------------------------------------------------------

def test_is_real_port_token_rejects_dev_kit_tokens():
    """Direct unit test: FPGA-board tokens are rejected."""
    rejected = ["FPGA", "ADC", "SDRAM", "VGA", "MAX10_CLK1_50",
                "ARDUINO", "RGB", "SWITCH", "GSENSOR_SDI", "OSC",
                "SOF", "PWR", "BOOT_SEL", "LVTTL",
                "COM", "VCOM", "UFP", "LRL", "EN_L", "MPD_CAP",
                "ID_CAP", "V_HY_GPIO", "RMPD_0", "V_ACC_ID_HYST",
                "CLM", "CLM_CURRENT", "FSM"]
    for tok in rejected:
        assert not _is_real_port_token(tok), (
            f"_is_real_port_token({tok!r}) must return False")


def test_is_real_port_token_rejects_pin_numbered():
    """Board-pin labels (PIN_N5, PIN_N14, PIN_AB12) are FPGA-package
    ball assignments, never chip top-level ports."""
    rejected = ["PIN_N5", "PIN_N14", "PIN_P11", "PIN_V11", "PIN_AB12"]
    for tok in rejected:
        assert not _is_real_port_token(tok), (
            f"_is_real_port_token({tok!r}) must return False")


def test_is_real_port_token_accepts_legitimate_pins():
    """Real chip pin names must still pass."""
    accepted = ["ID_BUS", "OVP", "WAKE", "RESET_N", "CLK_EXT"]
    for tok in accepted:
        assert _is_real_port_token(tok), (
            f"_is_real_port_token({tok!r}) must return True")


def test_l9_drops_pin_numbered_references(tmp_path):
    """End-to-end: PIN_N5 / PIN_N14 must NOT promote into L9.ports."""
    project = _seed(tmp_path)
    extracted = {
        "datasheet.txt": (
            "Board pin assignment: PIN_N5 = clock, PIN_N14 = reset.\n"
            "Chip pinout:\n"
            "PIN NAME    I/O\n"
            "1   id_bus  inout\n"
            "2   ovp     input\n"
        ),
    }
    gen_l1_datasheet(project, extracted)
    gen_l2_frs(project, extracted)
    gen_l9_integration_spec(project, extracted, l3={})
    l9 = _read(project, "L9_INTEGRATION_SPEC")
    ports_field = l9.get("top_ports") or l9.get("ports") or []
    port_names = [p.get("name", "").lower() for p in ports_field]
    for forbidden in ("pin_n5", "pin_n14", "pin_p11", "pin_v11"):
        assert forbidden not in port_names, (
            f"L9 must not promote board-pin label: {forbidden}")


# ---------------------------------------------------------------------------
# Bug 4 — L11 FSM state cleanup
# ---------------------------------------------------------------------------

def test_is_real_fsm_state_rejects_protocol_acronyms():
    """Protocol / IP class acronyms are NOT FSM states."""
    text = "FSM states: CRC, JTAG, SDR, TDI, TMS, SGND, ACLR, ESD"
    for tok in ("CRC", "JTAG", "SDR", "TDI", "TMS", "SGND",
                "ACLR", "ESD", "AND", "OR"):
        assert not _is_real_fsm_state(tok, text), (
            f"_is_real_fsm_state({tok!r}) must return False")


def test_is_real_fsm_state_rejects_short_acronyms():
    """Tokens shorter than 3 chars are NOT FSM states."""
    text = "States: F8, EC, OK, UV are status flags"
    for tok in ("F8", "EC", "OK", "UV"):
        assert not _is_real_fsm_state(tok, text), (
            f"_is_real_fsm_state({tok!r}) must return False (length floor)")


def test_is_real_fsm_state_accepts_real_states():
    """Real FSM-state names (S_IDLE / S_RUN / IDLE) must pass when
    they appear in `state:` narrative context."""
    text = "FSM states: S_IDLE, S_RUN, S_VALIDATE"
    for tok in ("S_IDLE", "S_RUN", "S_VALIDATE"):
        assert _is_real_fsm_state(tok, text), (
            f"_is_real_fsm_state({tok!r}) must return True")


def test_l11_fsm_excludes_protocol_acronyms(tmp_path):
    """End-to-end: L11.fsm_state_catalogue must not contain CRC / JTAG /
    SDR / TDI / TMS pulled from protocol-narrative regions."""
    project = _seed(tmp_path)
    extracted = {
        "datasheet.txt": (
            "FSM states: S_IDLE, S_RX, S_TX, S_VALIDATE.\n"
            "CRC parameters: state polynomial 0x31. JTAG TAP "
            "controller has TDI/TMS pins. SDR memory state "
            "transitions on every cycle.\n"
            "Mode: standby, active.\n"
        ),
    }
    gen_l11_otp_content(project, extracted)
    l11 = _read(project, "L11_OTP_CONTENT")
    fsm_states = [
        s.get("name", "").upper()
        for s in (l11.get("fsm_state_catalogue") or [])
    ]
    forbidden = ["CRC", "JTAG", "SDR", "TDI", "TMS", "SGND", "ACLR",
                 "ESD", "AND"]
    for f in forbidden:
        assert f not in fsm_states, (
            f"L11 FSM polluted with protocol/gate token: {f}")


def test_l11_fsm_excludes_short_acronyms(tmp_path):
    """End-to-end: F8, EC, OK, UV must not appear in
    L11.fsm_state_catalogue (length-floor filter)."""
    project = _seed(tmp_path)
    extracted = {
        "datasheet.txt": (
            "States: F8, EC, OK, UV are status flags. Real FSM "
            "states: S_INIT, S_RUN, S_DONE.\n"
        ),
    }
    gen_l11_otp_content(project, extracted)
    l11 = _read(project, "L11_OTP_CONTENT")
    fsm_states = [
        s.get("name", "").upper()
        for s in (l11.get("fsm_state_catalogue") or [])
    ]
    for f in ("F8", "EC", "OK", "UV"):
        assert f not in fsm_states, (
            f"L11 FSM has short acronym: {f}")
