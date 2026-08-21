"""tests/test_v1_0_39_issue653_has_otp_empty_skeleton.py

ORGANIC-20260614 (#653, LOW) — `_l4_has_otp` reported has_otp=True for a
NO-OTP IC because the Phase-1 L4 generator emits an `otp_layout` SKELETON
dict (default depth/width geometry, all content lists empty) which is a
truthy dict.  The old `if v: return True` check counted mere dict
truthiness as OTP evidence.

The fix is chip-AGNOSTIC and two-fold:
  (1) an explicit absence veto (L11 `otp_present: false` OR L4/L11
      `no_otp_layout_in_input` / `no_otp_in_input`) is a HARD short-circuit
      to False; and
  (2) a dict-valued OTP key only counts as evidence when at least one
      CONTENT sub-field is non-empty — a geometry-only skeleton does not.

These tests pin both the false-positive fix AND the NEGATIVE no-leak
guarantee: a genuinely POPULATED otp_layout still yields has_otp=True, so
the relaxation removed false positives WITHOUT suppressing real OTP ICs.
This mirrors what the field agent observed on the round-3 v1.0.35
clean-room 6-IC re-run (a register-mapped hash-accelerator IC).
"""
from __future__ import annotations

import json
from pathlib import Path

from ic_class_profile import _l4_has_otp, detect_ic_class, required_layers


# ---------------------------------------------------------------------
# The exact skeleton the Phase-1 L4 generator emits for a NO-OTP IC.
# (truthy dict, geometry defaults present, every content list empty)
# ---------------------------------------------------------------------
_EMPTY_OTP_SKELETON = {
    "fields": [],
    "depth_bytes": 128,
    "width_bits": 8,
    "read_map": [],
    "write_map": [],
    "lockbits": [],
    "otp_ip_specs": None,
    "trim_registers": [],
    "mask_sources": [],
}


def _write_l_docs(project: Path, docs: dict[str, dict]) -> None:
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    for fname, data in docs.items():
        (gd / fname).write_text(json.dumps(data, indent=2))


# =====================================================================
# Helper-level (unit) tests on _l4_has_otp directly
# =====================================================================
def test_empty_otp_skeleton_is_not_evidence() -> None:
    """Geometry-only skeleton (truthy dict, no content) -> has_otp False."""
    l4 = {"registers": [{"addr": 0, "name": "CTRL"}],
          "otp_layout": dict(_EMPTY_OTP_SKELETON)}
    assert _l4_has_otp(l4, None, None) is False


def test_empty_skeleton_with_otp_present_false_veto() -> None:
    """Explicit L11 otp_present:false is a hard short-circuit to False,
    even if L4 still carries the truthy-but-empty skeleton."""
    l4 = {"otp_layout": dict(_EMPTY_OTP_SKELETON)}
    l11 = {"otp_present": False}
    assert _l4_has_otp(l4, l11, None) is False


def test_empty_skeleton_with_no_otp_layout_in_input_veto() -> None:
    """L4/L11 no_otp_layout_in_input:true is a hard short-circuit."""
    l4 = {"otp_layout": dict(_EMPTY_OTP_SKELETON),
          "no_otp_layout_in_input": True}
    assert _l4_has_otp(l4, None, None) is False
    l11 = {"no_otp_in_input": True}
    assert _l4_has_otp({"otp_layout": dict(_EMPTY_OTP_SKELETON)},
                       l11, None) is False


# ----- NEGATIVE no-leak: real OTP still detected -----
def test_populated_otp_layout_still_true() -> None:
    """No-leak: a genuinely POPULATED otp_layout still yields True."""
    l4 = {"otp_layout": {"trim_registers": ["TRIM_A", "TRIM_B"],
                         "lockbits": [0, 1, 2]}}
    assert _l4_has_otp(l4, None, None) is True


def test_populated_otp_layout_fields_only_still_true() -> None:
    """No-leak: a single non-empty content sub-field is enough."""
    l4 = {"otp_layout": {**_EMPTY_OTP_SKELETON,
                         "fields": [{"name": "CHIP_ID", "bits": 32}]}}
    assert _l4_has_otp(l4, None, None) is True


def test_non_dict_otp_value_still_true() -> None:
    """No-leak: a populated list-valued lockbits / otp_bytes blob keeps
    plain truthiness (the dict-content rule only gates dict values)."""
    assert _l4_has_otp({"lockbits": [0, 1, 2]}, None, None) is True
    assert _l4_has_otp({"otp_bytes": "DEADBEEF"}, None, None) is True


def test_nested_regmap_skeleton_not_evidence() -> None:
    """The nested L4_REGMAP / L11_OTP_CONTENT path also rejects an
    empty skeleton but still honors populated content."""
    nested_empty = {"L4_REGMAP": {"otp_layout": dict(_EMPTY_OTP_SKELETON)}}
    assert _l4_has_otp(nested_empty, None, None) is False
    nested_full = {"L4_REGMAP": {"otp_layout":
                                 {"lockbits": [1], "fields": [{"x": 1}]}}}
    assert _l4_has_otp(nested_full, None, None) is True


def test_populated_otp_layout_beats_a_stale_otp_present_false() -> None:
    """CONTENT beats a bare absence DECLARATION.

    This replaces `test_populated_otp_layout_with_otp_present_false_veto_wins`,
    which asserted the opposite.  Three reasons, in order of weight:

      1. It contradicted THIS FILE'S OWN stated no-leak guarantee, quoted from
         the module docstring above: *"a genuinely POPULATED otp_layout still
         yields has_otp=True, so the relaxation removed false positives
         WITHOUT suppressing real OTP ICs."*  A populated layout returning
         False is precisely a suppressed real OTP IC.
      2. The veto is not what fixes #653.  The module docstring lists the fix
         as two-fold, and part (2) — "a dict-valued OTP key only counts as
         evidence when at least one CONTENT sub-field is non-empty" — already
         disposes of the geometry-only skeleton on its own.  Part (1)'s
         unconditional short-circuit adds nothing for the skeleton case and
         only creates this override.
      3. Measured on a real design: an L-doc carrying a fully populated OTP
         image and a populated field layout was reported has_otp=False because
         a pass that does not own that document had `setdefault`-ed an
         `otp_present: False` beside the image.  The declaration is a PROXY for
         "this design has no OTP"; the property is "is there OTP content".

    The property #653 actually defends — a NO-OTP IC is not flagged — is
    unchanged and is still pinned by `test_empty_otp_skeleton_is_not_evidence`,
    `test_empty_skeleton_with_otp_present_false_veto`,
    `test_empty_skeleton_with_no_otp_layout_in_input_veto`,
    `test_nested_regmap_skeleton_not_evidence` and the three e2e tests below,
    all of which still pass.
    """
    l4 = {"otp_layout": {"lockbits": [1], "fields": [{"x": 1}]}}
    l11 = {"otp_present": False}
    assert _l4_has_otp(l4, l11, None) is True

    # …and the declaration still wins when there is no content to prefer,
    # which is the whole of what the veto was introduced to do.
    l4_skeleton = {"otp_layout": dict(_EMPTY_OTP_SKELETON)}
    assert _l4_has_otp(l4_skeleton, {"otp_present": False}, None) is False


def test_populated_nested_layout_beats_a_stale_declaration() -> None:
    """Same rule on the nested L4_REGMAP / L11_OTP_CONTENT path, which
    carries its own copy of the veto."""
    nested_full = {"L11_OTP_CONTENT": {
        "otp_present": False,
        "otp_layout": {"fields": [{"field": "ID[0]"}]}}}
    assert _l4_has_otp(None, nested_full, None) is True

    nested_empty = {"L11_OTP_CONTENT": {
        "otp_present": False,
        "otp_layout": dict(_EMPTY_OTP_SKELETON)}}
    assert _l4_has_otp(None, nested_empty, None) is False


def test_falsy_content_keys_do_not_defeat_the_declaration() -> None:
    """No-leak boundary: a content key that is PRESENT BUT EMPTY is not
    content, so an honest negative declaration must still win."""
    assert _l4_has_otp(
        None, {"otp_present": False, "otp_bytes": [],
               "otp_layout": {"fields": []}}, None) is False
    assert _l4_has_otp(
        None, {"no_otp_in_input": True, "otp_image": "",
               "otp_table": None}, None) is False


# =====================================================================
# End-to-end via detect_ic_class — the field-agent's observed scenario
# =====================================================================
def test_e2e_no_otp_ic_skeleton_has_otp_false(tmp_path: Path) -> None:
    """Field-agent round-3 scenario: a register-mapped accelerator IC
    whose L4 carries the empty otp_layout skeleton and whose L11 declares
    otp_present:false must NOT be flagged has_otp."""
    project = tmp_path / "ic_no_otp"
    project.mkdir(parents=True, exist_ok=True)
    _write_l_docs(project, {
        "L1_DATASHEET.json": {"ic_name": "HASH-ACCEL"},
        "L2_FRS.json": {"protocol_type": "register_mapped"},
        "L4_REGMAP.json": {
            "registers": [{"addr": 0, "name": "CTRL"}],
            "otp_layout": dict(_EMPTY_OTP_SKELETON),
            "no_otp_layout_in_input": True,
        },
        "L11_OTP_CONTENT.json": {"otp_present": False},
    })
    profile = detect_ic_class(project)
    # The core fix: the empty skeleton + otp_present:false must clear the
    # OTP-evidence flag (was True before #653).
    assert profile["has_otp"] is False


def test_e2e_cmd_driven_no_otp_skeleton_drops_l11(tmp_path: Path) -> None:
    """A digital_cmd_driven IC (which uses the conditional L5/L11/L12/L13
    skip mechanism) whose L4 carries only the empty otp_layout skeleton
    must let L11 drop to skip — before #653 the phantom has_otp flag
    forced L11 mandatory.  Mirrors test_digital_cmd_driven_uart but with
    the skeleton present in L4."""
    project = tmp_path / "ic_uart_skeleton"
    project.mkdir(parents=True, exist_ok=True)
    _write_l_docs(project, {
        "L1_DATASHEET.json": {"ic_name": "UART-EEPROM"},
        "L2_FRS.json": {"protocol_type": "UART"},
        "L3_CMD_PROTOCOL.json": {
            "commands": [
                {"name": "READ", "opcode": "0x01"},
                {"name": "WRITE", "opcode": "0x02"},
                {"name": "ERASE", "opcode": "0x03"},
                {"name": "STATUS", "opcode": "0x04"},
            ],
        },
        "L4_REGMAP.json": {
            "registers": [{"addr": 0, "name": "CTRL"}],
            # The truthy-but-empty skeleton the L4 generator emits.
            "otp_layout": dict(_EMPTY_OTP_SKELETON),
        },
    })
    profile = detect_ic_class(project)
    assert profile["has_otp"] is False
    assert profile["ic_class"] == "digital_cmd_driven"
    layers = required_layers(profile)
    # No analog, no cal, no OTP -> L11 must drop to skip.
    assert "L11" in layers["skip"]


def test_e2e_real_otp_ic_still_has_otp_true(tmp_path: Path) -> None:
    """No-leak end-to-end: a real OTP IC with a populated otp_layout
    still classifies has_otp=True and keeps L11 mandatory."""
    project = tmp_path / "ic_real_otp"
    project.mkdir(parents=True, exist_ok=True)
    _write_l_docs(project, {
        "L1_DATASHEET.json": {"ic_name": "SENSOR-OTP"},
        "L2_FRS.json": {"protocol_type": "I2C"},
        "L4_REGMAP.json": {
            "registers": [{"addr": 0, "name": "CTRL"}],
            "otp_layout": {
                "trim_registers": ["TRIM_A", "TRIM_B"],
                "lockbits": [0, 1, 2],
            },
        },
    })
    profile = detect_ic_class(project)
    assert profile["has_otp"] is True
    layers = required_layers(profile)
    assert "L11" in layers["mandatory"]
