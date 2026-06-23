"""tests/test_phase2_classifier_canonical_routing.py — v1.6.55

Closes GitHub issue #1 (ORGANIC-20260509-phase2-shadow-classifier-
false-positive) and #2 (partial-fix dead-code follow-up). Replaces
the substring-grep shadow detect_ic_class() with a thin adapter onto
the schema-aware ``ic_class_profile.detect_ic_class``.

Test coverage:

  1. Synthetic L docs whose L2 carries `protocol_overview.half_duplex
     = false` and L3 carries an opcode list MUST NOT yield any
     aid_class label. (The exact regression that caused 10/10 fresh-
     agent benchmarks to FAIL identically before this fix.)

  2. Each of the four newly-registered classes
     (`digital_cmd_driven`, `mixed_signal_otp`, `pure_analog`,
     `bare_fpga`) must be reachable from a corresponding minimal
     fixture. v1.6.51 added them to the registry but the shadow
     classifier never produced them — issue #2.

  3. EXAMPLE_PROTOCOL-class is reached only when L2 actually carries an
     example_protocol-class protocol token (single_wire_half_duplex /
     id_bus / etc.) AND L3 has commands. KEY-presence alone of
     `half_duplex` / `opcode` / `crc` JSON keys is not sufficient.
"""
from __future__ import annotations

import json
from pathlib import Path

from programs.design_one_shot_runner import detect_ic_class
import pytest


def _w(p: Path, name: str, payload: dict) -> None:
    """Write `payload` to `<project>/phase1/generated_docs/<name>`."""
    gd = p / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / name).write_text(json.dumps(payload, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Issue #1 / #2 regression: half_duplex=false + opcode list ≠ aid_class.
# ---------------------------------------------------------------------------

def test_half_duplex_false_does_not_yield_aid_class(tmp_path: Path) -> None:
    """The exact Phase-2a output that 10/10 fresh-agent benchmarks
    produced. Pre-fix shadow classifier scored ≥2 on KEY-presence and
    returned aid_class. Post-fix canonical classifier sees
    `protocol_overview.half_duplex == false` and `commands` populated
    → digital_cmd_driven."""
    p = tmp_path / "proj"
    _w(p, "L2_FRS.json", {
        "protocol_overview": {
            "half_duplex": False,
            "wire_count": 2,
            "byte_order": "LSB-first",
        },
        "frs_doc": {"interface": "axi4-lite"},
    })
    _w(p, "L3_CMD_PROTOCOL.json", {
        "opcodes": [
            {"hex": "0x10", "name": "READ_REG"},
            {"hex": "0x11", "name": "WRITE_REG"},
        ],
        "crc_parameters": {"polynomial_hex": "0x31"},
    })
    _w(p, "L1_DATASHEET.json", {"ic_name": "test_chip"})
    cls, evidence = detect_ic_class(p)
    assert "aid_class" not in cls, (
        f"Issue #1 regression: half_duplex=false routed to aid_class. "
        f"Got class={cls!r}, evidence={evidence!r}")
    assert cls == "digital_cmd_driven", cls


def test_opcode_keys_alone_do_not_yield_aid_class(tmp_path: Path) -> None:
    """Issue #1: shadow classifier matched on the literal substring
    `opcode` anywhere in the JSON. Confirm the fix only routes to
    aid_class when the protocol metadata actually says so."""
    p = tmp_path / "proj"
    _w(p, "L2_FRS.json", {
        "protocol_overview": {"half_duplex": False, "wire_count": 4},
    })
    _w(p, "L3_CMD_PROTOCOL.json", {
        # Has the "opcode" / "crc" keys but no real protocol semantics.
        "opcodes": [{"hex": "0x00", "name": "RESERVED"}],
        "crc_parameters": {"polynomial_hex": "0x07"},
    })
    cls, _ = detect_ic_class(p)
    assert "aid_class" not in cls


# ---------------------------------------------------------------------------
# Each registered class reachable from a fixture.
# ---------------------------------------------------------------------------

def test_digital_cmd_driven_class_reachable(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    _w(p, "L1_DATASHEET.json", {"ic_name": "block_cipher_core"})
    _w(p, "L2_FRS.json", {
        "protocol_overview": {"half_duplex": False},
        "interface_type": "axi4_lite",
    })
    _w(p, "L3_CMD_PROTOCOL.json", {
        "opcodes": [
            {"hex": "0x01", "name": "START"},
            {"hex": "0x02", "name": "STATUS"},
        ],
    })
    cls, _ = detect_ic_class(p)
    assert cls == "digital_cmd_driven"


def test_pure_analog_class_reachable(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    _w(p, "L1_DATASHEET.json", {"ic_name": "analog_pmic"})
    _w(p, "L5_ADI_SPEC.json", {
        "analog_blocks": [
            {"name": "ldo", "topology": "PMOS-pass"},
            {"name": "bandgap", "topology": "Brokaw"},
        ],
    })
    # No L3 commands → pure_analog.
    cls, _ = detect_ic_class(p)
    assert cls == "pure_analog"


def test_mixed_signal_otp_class_reachable(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    _w(p, "L1_DATASHEET.json", {"ic_name": "mixed_chip_otp"})
    _w(p, "L2_FRS.json", {"protocol_overview": {"half_duplex": False}})
    _w(p, "L3_CMD_PROTOCOL.json", {
        "opcodes": [{"hex": "0x10", "name": "READ_OTP"}],
    })
    _w(p, "L5_ADI_SPEC.json", {
        "analog_blocks": [{"name": "bandgap"}],
    })
    # ORGANIC-20260614 (#653): a geometry-only otp_layout (e.g. bare
    # `size_bits`) is no longer OTP evidence — the layout must carry at
    # least one populated CONTENT sub-field (fields/lockbits/...).  Give
    # this genuine mixed_signal_otp fixture real OTP content so it still
    # reaches the class for the right reason.
    _w(p, "L4_REGMAP.json", {
        "otp_layout": {
            "size_bits": 1024,
            "fields": [{"name": "CHIP_ID", "bits": 32}],
        },
    })
    cls, _ = detect_ic_class(p)
    assert cls == "mixed_signal_otp"


def test_bare_fpga_class_reachable(tmp_path: Path) -> None:
    """Path-A skeleton: no L1/L2/L3 generated docs but a `facts.yaml`
    on disk → bare_fpga.

    v1.6.523 reassigned the L1+L2-only-no-protocol case to
    `digital_arithmetic_primitive` (ASIC datapath primitives must not
    be mislabelled FPGA-only). The genuine, canonical way to reach
    `bare_fpga` is now the Path-A skeleton: no L-docs + facts.yaml
    present, which the classifier treats as a bare FPGA scaffold."""
    p = tmp_path / "proj"
    # generated_docs/ must exist (the phase2 adapter requires it) but
    # carry NO L1/L2/L3 docs — that's the Path-A skeleton shape.
    (p / "phase1" / "generated_docs").mkdir(parents=True, exist_ok=True)
    # A facts.yaml marks the bare FPGA scaffold path.
    (p / "facts.yaml").write_text("board: de10lite\n")
    cls, _ = detect_ic_class(p)
    assert cls == "bare_fpga"


# ---------------------------------------------------------------------------
# EXAMPLE_PROTOCOL class still reachable when the protocol IS half-duplex single-wire.
# ---------------------------------------------------------------------------

def test_aid_class_reached_when_protocol_actually_half_duplex(
        tmp_path: Path) -> None:
    p = tmp_path / "proj"
    _w(p, "L1_DATASHEET.json", {"ic_name": "real_aid_chip"})
    _w(p, "L2_FRS.json", {
        "protocol_overview": {
            "half_duplex": True,
            "wire_count": 1,
        },
        "protocol_type": "single_wire_half_duplex",
    })
    _w(p, "L3_CMD_PROTOCOL.json", {
        "opcodes": [
            {"hex": "0x70", "name": "GET_ID"},
        ],
        "physical_layer": {
            "interface": "single_wire_half_duplex",
            "br_framing": True,
        },
        "crc_parameters": {"polynomial_hex": "0x31"},
    })
    cls, _ = detect_ic_class(p)
    assert "aid_class" in cls, (
        f"EXAMPLE_PROTOCOL-class regression: real half-duplex chip mis-classified. "
        f"Got cls={cls!r}")


# ---------------------------------------------------------------------------
# Defensive: missing generated_docs/, malformed L docs.
# ---------------------------------------------------------------------------

def test_missing_generated_docs_yields_unknown(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    p.mkdir()
    cls, evidence = detect_ic_class(p)
    assert cls == "unknown"
    assert "generated_docs" in evidence


def test_malformed_l_docs_do_not_crash(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    gd = p / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L2_FRS.json").write_text("{not valid json,,,")
    cls, _ = detect_ic_class(p)
    # Canonical classifier handles malformed JSON internally; resulting
    # class should be conservative (anything that's not aid_class).
    assert "aid_class" not in cls


# ---------------------------------------------------------------------------
# Evidence string carries useful diagnostics.
# ---------------------------------------------------------------------------

def test_evidence_string_carries_class_facts(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    _w(p, "L3_CMD_PROTOCOL.json", {
        "opcodes": [{"hex": "0x01", "name": "FOO"}],
    })
    _w(p, "L2_FRS.json", {"protocol_overview": {"half_duplex": False}})
    _, evidence = detect_ic_class(p)
    # Evidence should reflect canonical-classifier flag fields.
    assert "has_command_protocol" in evidence
