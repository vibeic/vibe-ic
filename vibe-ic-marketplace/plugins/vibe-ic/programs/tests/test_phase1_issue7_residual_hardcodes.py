"""tests/test_phase1_issue7_residual_hardcodes.py — v1.6.66

Closes GitHub issue #7 — three residual hardcodes / false-positives
not covered by issue #6:

  Bug X  L3.crc_parameters always emits EXAMPLE_PROTOCOL-class CRC-8
         (poly=0x31, init=0xFF, reflected=0x8C) regardless of input
  Bug Y  L5.analog_blocks emits `charge_pump_default` placeholder
         on pure-digital projects (false-positive on regex
         keyword "comparator" / "OTA" / "op-amp" matching digital
         RTL prose)
  Bug Z  L9.ports false-positives on protocol-class acronyms
         (DDR / SDR / PTP / etc.) harvested from README prose

Each test asserts the v1.6.66 fix mirrors the durable rule (memory:
`feedback_general_fixes_no_false_alert.md`):
  * fixes are general (chip-AGNOSTIC) — work for crypto / memory /
    storage / link / debug / networking / EXAMPLE_PROTOCOL classes
  * no false alerts — deny-lists / length floors / structural
    checks before regex fires
"""
from __future__ import annotations

import json
from pathlib import Path

from programs.phase1_one_shot_runner import (
    _PROTOCOL_ACRONYM_DENY,
    gen_l1_datasheet,
    gen_l3_cmd_protocol,
    gen_l5_adi_spec,
    gen_l9_integration_spec,
)

_GEN_DIR = Path("phase1") / "generated_docs"


def _seed(tmp_path: Path, l_docs: dict[str, dict] | None = None) -> Path:
    project = tmp_path
    (project / _GEN_DIR).mkdir(parents=True, exist_ok=True)
    for name, content in (l_docs or {}).items():
        (project / _GEN_DIR / f"{name}.json").write_text(json.dumps(content))
    return project


def _read(project: Path, name: str) -> dict:
    return json.loads((project / _GEN_DIR / f"{name}.json").read_text())


# ---------------------------------------------------------------------------
# Bug X — L3.crc_parameters emits None + flag when no extraction
# ---------------------------------------------------------------------------

def test_l3_no_crc_evidence_emits_null_with_flag(tmp_path: Path) -> None:
    """Block-cipher / hash-core / SerDes projects don't carry CRC-8.
    L3 must NOT emit the EXAMPLE_PROTOCOL-class default 0x31 / 0xFF / 0x8C."""
    project = _seed(tmp_path)
    extracted = {
        "aes_spec.txt": "Verilog AES core. Pure combinational rounds.\n",
    }
    gen_l3_cmd_protocol(project, extracted, l2={})
    l3 = _read(project, "L3_CMD_PROTOCOL")
    assert l3["crc_parameters"] is None
    assert l3["no_crc_parameters_in_input"] is True


def test_l3_real_crc_extraction_populates(tmp_path: Path) -> None:
    project = _seed(tmp_path)
    extracted = {
        "datasheet.txt": (
            "CRC-8 polynomial: 0x07 (CRC-8 ATM standard).\n"
            "init = 0x00\n"
        ),
    }
    gen_l3_cmd_protocol(project, extracted, l2={})
    l3 = _read(project, "L3_CMD_PROTOCOL")
    assert l3["crc_parameters"] is not None
    assert l3["no_crc_parameters_in_input"] is False
    cp = l3["crc_parameters"]
    assert cp["polynomial_hex"] == "0x07"
    # Critical: NOT the v1.6.65 EXAMPLE_PROTOCOL-class default 0x31.
    assert cp["polynomial_hex"] != "0x31"


def test_l3_no_crc_8_aid_default_leaks_into_non_aid_inputs(
        tmp_path: Path) -> None:
    """Aggregate guard: across 4 distinct non-EXAMPLE_PROTOCOL IC classes, none
    should produce the EXAMPLE_PROTOCOL 0x31 polynomial."""
    cases = [
        ("aes", "AES block cipher. NIST FIPS 197.\n"),
        ("sha256", "SHA-256 hash function. NIST FIPS 180.\n"),
        ("dram", "DRAM controller. ECC over 64-bit data path.\n"),
        ("serdes", "SerDes link. 8b/10b line code.\n"),
    ]
    for label, src in cases:
        proj = _seed(tmp_path / label)
        gen_l3_cmd_protocol(proj, {"spec.txt": src}, l2={})
        l3 = _read(proj, "L3_CMD_PROTOCOL")
        assert l3["crc_parameters"] is None, \
            f"{label}: EXAMPLE_PROTOCOL-class CRC-8 default leaked: {l3['crc_parameters']!r}"


# ---------------------------------------------------------------------------
# Bug Y — L5.analog_blocks no _default placeholder + tighter regex
# ---------------------------------------------------------------------------

def test_l5_no_analog_keywords_emits_empty_with_flag(
        tmp_path: Path) -> None:
    project = _seed(tmp_path)
    extracted = {
        "aes_spec.txt": "Pure digital AES. Combinational rounds.\n",
    }
    gen_l5_adi_spec(project, extracted)
    l5 = _read(project, "L5_ADI_SPEC")
    assert l5["analog_blocks"] == []
    assert l5["no_analog"] is True
    assert l5["analog_blocks_detected"] is False


def test_l5_digital_comparator_does_not_trigger_charge_pump(
        tmp_path: Path) -> None:
    """v1.6.66 — closes issue #7 Bug Y false-positive. Digital RTL
    prose mentioning `comparator` / `OTA` / `op-amp` (e.g. ChaCha
    quarter-round bit comparator, networking IP discussing data-rate
    comparators) must NOT trigger the `charge_pump` analog-keyword
    match. Regex narrowed to `charge[\\s\\-]?pump` only."""
    cases = [
        "ChaCha quarter-round. Bit-comparator selects rotated word.\n",
        "Networking IP. Comparator stage classifies header type.\n",
        "Digital OTA wrapper for stream-cipher state.\n",
        "Algorithm uses an op-amp metaphor for clarity.\n",
    ]
    for src in cases:
        proj = _seed(tmp_path / src[:30].replace("/", "_"))
        gen_l5_adi_spec(proj, {"spec.txt": src})
        l5 = _read(proj, "L5_ADI_SPEC")
        names = [b.get("name") for b in l5["analog_blocks"]]
        assert "charge_pump" not in names, \
            f"false-positive on prose {src!r}"
        assert "charge_pump_default" not in names


def test_l5_no_default_suffix_in_analog_block_names(
        tmp_path: Path) -> None:
    """Aggregate guard: NO L5.analog_blocks entry should ever carry
    a `_default` suffix — that suffix self-declared as scaffolding."""
    project = _seed(tmp_path)
    extracted = {
        "datasheet.txt": (
            "Built-in LDO regulator output stage.\n"
            "RC oscillator at fOSC.\n"
            "Bandgap reference VBG.\n"
            "Internal charge pump for OTP programming.\n"
        ),
    }
    gen_l5_adi_spec(project, extracted)
    l5 = _read(project, "L5_ADI_SPEC")
    for b in l5["analog_blocks"]:
        assert not b["name"].endswith("_default"), \
            f"v1.6.66 must not emit `*_default` placeholder: {b!r}"
    # And real keywords still fire — regression guard for the
    # narrowed regex not breaking real detection.
    types = {b["type"] for b in l5["analog_blocks"]}
    assert types >= {"ldo", "oscillator", "bandgap", "charge_pump"}


# ---------------------------------------------------------------------------
# Bug Z — L9.ports protocol-acronym filter
# ---------------------------------------------------------------------------

def test_protocol_acronym_deny_list_covers_known_classes() -> None:
    expected = {"DDR", "SDR", "PTP", "PCIE", "AXI", "AHB", "APB",
                "ETH", "MII", "RMII", "USB", "MAC", "FIFO", "DMA"}
    missing = expected - _PROTOCOL_ACRONYM_DENY
    assert not missing, f"deny-list missing: {missing}"


def test_l1_pin_table_rejects_protocol_acronyms_from_prose(
        tmp_path: Path) -> None:
    """v1.6.66 — closes issue #7 Bug Z. README prose like
    `Inputs: DDR, SDR, PTP` previously slipped past the
    `_PIN_TABLE_LINE_RE` filter and emitted three pseudo-pins on
    the Taxi networking project. Now: protocol-class acronyms are
    rejected at L1 token-extraction time."""
    project = _seed(tmp_path)
    extracted = {
        "README.md": (
            "# Taxi Transport Library\n\n"
            "Inputs: DDR SDR PTP USB ETH PCIe\n"
            "Outputs: PHY MII RMII MAC\n"
        ),
    }
    gen_l1_datasheet(project, extracted)
    l1 = _read(project, "L1_DATASHEET")
    pin_names = {p["name"] for p in l1.get("pin_table", [])}
    # None of the protocol-class acronyms should appear as pin names.
    forbidden = {"DDR", "SDR", "PTP", "USB", "ETH", "PCIE",
                 "PHY", "MII", "RMII", "MAC"}
    leaked = forbidden & pin_names
    assert not leaked, f"protocol acronyms emitted as pins: {leaked}"


def test_l9_no_acronym_pins_when_l1_has_none(tmp_path: Path) -> None:
    """Cross-layer regression: if L1.pin_table correctly excludes
    acronym false-positives, L9.ports must too (since v1.6.65 L9
    promotes from L1)."""
    project = _seed(tmp_path, l_docs={
        "L1_DATASHEET": {
            "schema_version": 2,
            "ic_name": "Taxi Transport Library",
            # Empty pin_table — acronym false-positives correctly
            # filtered out at L1.
            "pin_table": [],
        },
    })
    gen_l9_integration_spec(project, {}, l3={})
    l9 = _read(project, "L9_INTEGRATION_SPEC")
    pin_names = {p.get("name") for p in l9["top_module_pins"]}
    forbidden = {"DDR", "SDR", "PTP", "USB", "ETH"}
    assert not (forbidden & pin_names)
    assert l9["no_integration_in_input"] is True


def test_real_pin_names_with_acronym_substring_not_rejected(
        tmp_path: Path) -> None:
    """Don't over-reject: real pin names with embedded acronym
    substrings (e.g. `DDR_CLK`, `USB_DM`, `ETH_TXD0`) MUST be kept
    — the deny-list checks the WHOLE token, not substrings."""
    project = _seed(tmp_path)
    extracted = {
        "datasheet.txt": (
            "Pin table:\n"
            "Pin   Type    Description\n"
            "DDR_CLK   output  DDR memory clock\n"
            "USB_DM    inout   USB D-\n"
            "ETH_TXD0  output  Ethernet TX data 0\n"
            "MAC_ADDR  input   MAC ID strap\n"
        ),
    }
    gen_l1_datasheet(project, extracted)
    l1 = _read(project, "L1_DATASHEET")
    pin_names = {p["name"] for p in l1.get("pin_table", [])}
    # Real pins with acronym substrings survive.
    assert "DDR_CLK" in pin_names
    assert "USB_DM" in pin_names
    assert "ETH_TXD0" in pin_names
    # Bare acronym tokens still rejected.
    assert "DDR" not in pin_names
    assert "USB" not in pin_names
    assert "ETH" not in pin_names
