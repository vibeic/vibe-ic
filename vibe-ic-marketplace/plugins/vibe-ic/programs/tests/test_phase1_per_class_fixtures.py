"""tests/test_phase1_per_class_fixtures.py — v1.6.57

Closes GitHub issue #4 sub-fix #5 (regression fixtures). Each
fixture exercises a distinct IC class through the full Phase 2a
extraction pipeline and asserts the structured fields that
downstream consumers query are populated correctly — NOT at
template default — for the matching class.

Four fixtures, one per IC class the registry recognises (pre-EXAMPLE_PROTOCOL-
class):

  block-cipher        — README-only project, FIPS 197 / AES family
  memory-controller   — README-only project, DDR4 / LPDDR4 family
  serial-protocol     — README + spec, real opcode list
  pure-analog         — README-only, LDO / bandgap / no command protocol

For each fixture the test asserts:
  * `gen_l1_datasheet` resolves L1.ic_name to the right family-name
    (NOT "UNKNOWN_IC")
  * `gen_l2_frs` sets `no_protocol_overview_in_input` only when the
    input is genuinely silent on protocol
  * `gen_l3_cmd_protocol` populates `opcodes` when present, sets
    `no_opcodes_in_input: true` when absent
  * the Tier-2 substance gate PASSes for fixtures with substantive
    fields and either PASSes (escape valve) or WARNs for the
    pure-analog fixture where most fields legitimately have no
    input evidence.
"""
from __future__ import annotations

import json
from pathlib import Path

from programs.phase1_one_shot_runner import (
    extract_text_pipeline, gen_l1_datasheet, gen_l2_frs,
    gen_l3_cmd_protocol,
)


def _read_l_doc(project: Path, name: str) -> dict:
    p = project / "phase1" / "generated_docs" / f"{name}.json"
    return json.loads(p.read_text())


def _stage_input(project: Path, files: dict) -> None:
    docs = project / "input" / "docs"
    for rel, content in files.items():
        f = docs / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content)


# ---------------------------------------------------------------------------
# Fixture 1: block-cipher — README-only, FIPS 197.
# ---------------------------------------------------------------------------

def test_fixture_block_cipher_aes(tmp_path: Path) -> None:
    p = tmp_path / "aes_proj"
    _stage_input(p, {
        "README.md": (
            "# AES core\n\n"
            "Open-source Verilog implementation of AES (NIST FIPS 197).\n"
            "Supports 128 / 192 / 256 bit keys.\n"
        ),
    })
    extracted = extract_text_pipeline(p)
    assert extracted, "extraction failed; expected at least 1 file"

    l1 = gen_l1_datasheet(p, extracted)
    l1_data = _read_l_doc(p, "L1_DATASHEET")
    # ic_name resolved (was UNKNOWN_IC pre-fix).
    assert l1_data["ic_name"] != "UNKNOWN_IC"
    assert "AES" in l1_data["ic_name"] or l1_data["ic_name"] in (
        "AES", "AES core")
    # No pin table or electrical specs in README → flag set.
    assert l1_data["no_pin_table_in_input"] is True
    assert l1_data["no_electrical_specs_in_input"] is True

    gen_l2_frs(p, extracted)
    l2_data = _read_l_doc(p, "L2_FRS")
    # Block-cipher README has no half-duplex / single-wire markers.
    # NOTE: the README also has no AXI / I2C / SPI keyword, so this
    # IS a genuine "no protocol overview in input" case.
    assert l2_data["no_protocol_overview_in_input"] is True

    gen_l3_cmd_protocol(p, extracted, l2_data)
    l3_data = _read_l_doc(p, "L3_CMD_PROTOCOL")
    assert l3_data["no_opcodes_in_input"] is True


# ---------------------------------------------------------------------------
# Fixture 2: memory-controller — DDR4 keywords + AXI interface.
# ---------------------------------------------------------------------------

def test_fixture_memory_controller_ddr4(tmp_path: Path) -> None:
    p = tmp_path / "ddr4_proj"
    _stage_input(p, {
        "README.md": (
            "# DDR4 controller\n\n"
            "Open-source DDR4 memory controller IP. AXI4 interface.\n"
            "Supports x8 / x16 device widths.\n"
        ),
    })
    extracted = extract_text_pipeline(p)
    gen_l1_datasheet(p, extracted)
    gen_l2_frs(p, extracted)

    l1 = _read_l_doc(p, "L1_DATASHEET")
    l2 = _read_l_doc(p, "L2_FRS")

    # ic_name should pick up "DDR4 controller" / "DDR4" via H1 or
    # adjacency-to-controller rule.
    assert l1["ic_name"] != "UNKNOWN_IC"
    assert "DDR4" in l1["ic_name"]
    # AXI4 mention triggers protocol_evidence_found → flag NOT set.
    assert l2["no_protocol_overview_in_input"] is False


# ---------------------------------------------------------------------------
# Fixture 3: serial-protocol — README with real opcode mention.
# ---------------------------------------------------------------------------

def test_fixture_serial_protocol_with_opcodes(tmp_path: Path) -> None:
    p = tmp_path / "serial_proj"
    _stage_input(p, {
        "README.md": (
            "# Serial Authentication Bus\n\n"
            "Half-duplex serial protocol over single-wire bus.\n"
        ),
        "spec/cmd_table.txt": (
            "Command table\n"
            "1 1 X 70\n"
            "1 2 X 72\n"
            "1 3 X 74\n"
        ),
    })
    extracted = extract_text_pipeline(p)
    l1_r = gen_l1_datasheet(p, extracted)
    l2_r = gen_l2_frs(p, extracted)
    l2_data = _read_l_doc(p, "L2_FRS")
    gen_l3_cmd_protocol(p, extracted, l2_data)
    l3 = _read_l_doc(p, "L3_CMD_PROTOCOL")
    # Half-duplex single-wire keywords found in README.
    assert l2_data["no_protocol_overview_in_input"] is False
    assert l2_data["protocol_overview"]["half_duplex"] is True
    # Opcodes table parsed → no_opcodes flag NOT set.
    assert l3["no_opcodes_in_input"] is False
    assert len(l3["opcodes"]) >= 1


# ---------------------------------------------------------------------------
# Fixture 4: pure-analog — LDO / bandgap, no command protocol.
# ---------------------------------------------------------------------------

def test_fixture_pure_analog_ldo(tmp_path: Path) -> None:
    p = tmp_path / "ldo_proj"
    _stage_input(p, {
        "README.md": (
            "# LDO regulator\n\n"
            "Low-dropout linear regulator core. No digital command\n"
            "interface; analog control via reference voltage input.\n"
        ),
    })
    extracted = extract_text_pipeline(p)
    gen_l1_datasheet(p, extracted)
    gen_l2_frs(p, extracted)
    l2_data = _read_l_doc(p, "L2_FRS")
    gen_l3_cmd_protocol(p, extracted, l2_data)
    l1 = _read_l_doc(p, "L1_DATASHEET")
    l2 = _read_l_doc(p, "L2_FRS")
    l3 = _read_l_doc(p, "L3_CMD_PROTOCOL")
    # ic_name resolves via H1.
    assert l1["ic_name"] != "UNKNOWN_IC"
    # No protocol keyword (LDO / regulator are not in the panel) → flag set.
    assert l2["no_protocol_overview_in_input"] is True
    # No opcodes → flag set.
    assert l3["no_opcodes_in_input"] is True


# ---------------------------------------------------------------------------
# Tier-2 substance gate now respects the flags — escape valve works.
# ---------------------------------------------------------------------------

def test_substance_gate_escape_valve_for_thin_input_class(tmp_path: Path):
    """Pure-analog fixture: no_<field>_in_input flags should make
    the Tier-2 substance gate PASS (not FAIL) on what would
    otherwise look like template-default scaffolding."""
    p = tmp_path / "ldo_proj"
    _stage_input(p, {
        "README.md": (
            "# LDO regulator\n\n"
            "Low-dropout linear regulator core.\n"
        ),
    })
    extracted = extract_text_pipeline(p)
    gen_l1_datasheet(p, extracted)
    gen_l2_frs(p, extracted)
    l2_data = _read_l_doc(p, "L2_FRS")
    gen_l3_cmd_protocol(p, extracted, l2_data)
    # Run the Tier-2 gate.
    from programs.phase1_structured_field_substance_check import audit
    verdict, findings, summary = audit(p)
    # Escape valves cover most of the would-be scaffolding; verdict
    # should NOT be FAIL (>30% at default).
    assert verdict in ("PASS", "WARN"), (
        f"Pure-analog fixture mis-flagged as FAIL by substance gate. "
        f"verdict={verdict} findings={findings}")
