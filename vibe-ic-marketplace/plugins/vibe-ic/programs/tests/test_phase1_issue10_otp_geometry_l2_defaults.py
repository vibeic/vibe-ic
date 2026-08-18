"""tests/test_phase1_issue10_otp_geometry_l2_defaults.py — v1.6.70

Closes GitHub issue #10:

  Bug A — L4.otp_layout / L11 emitted hardcoded `depth_bytes=128,
          width_bits=8` EXAMPLE_PROTOCOL-class OTP geometry on every project,
          including the ten thin-input projects with no OTP at all.
          fields=[] correctly said "no fields documented", but the
          sibling geometry was a positive false claim.

  Bug B — L2.protocol_overview retained EXAMPLE_PROTOCOL-class
          `byte_order: "LSB-first"` and
          `wake_required_pre_command: true` even on projects whose
          source had no structured byte-order claim or wake-required
          prose. The picker fired any time ANY protocol keyword
          (i2c/spi/uart/axi/...) appeared, blanket-defaulting all
          per-field values.

Fixes apply the same general-fix + no-false-alert rule the closed
issues #6/#7/#8/#9 used: extract from source or null+flag.
"""
from __future__ import annotations

import json
from pathlib import Path

from programs.phase1_one_shot_runner import (
    gen_l2_frs,
    gen_l4_regmap,
    gen_l11_otp_content,
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
# Bug A — L4.otp_layout geometry no longer emitted on OTP-less projects
# ---------------------------------------------------------------------------

def test_l4_otp_less_project_emits_null_geometry(tmp_path: Path) -> None:
    """A pure-digital block cipher / hash core / DRAM controller has
    no OTP. v1.6.69 emitted `{depth_bytes:128, width_bits:8, fields:[]}`
    — a positive false claim. v1.6.70 emits `otp_layout: null` +
    `no_otp_layout_in_input: true`."""
    project = _seed(tmp_path)
    extracted = {
        "aes_spec.txt": "Verilog AES core. Pure combinational rounds.\n",
    }
    gen_l4_regmap(project, extracted)
    l4 = _read(project, "L4_REGMAP")
    assert l4["otp_layout"] is None
    assert l4["no_otp_layout_in_input"] is True


def test_l4_otp_evidence_keeps_geometry(tmp_path: Path) -> None:
    """When the source mentions OTP / fuse / one-time programmable,
    the geometry block is preserved (extraction-positive case)."""
    project = _seed(tmp_path)
    extracted = {
        "datasheet.txt": (
            "EXAMPLE_CHIP OTP layout: 128-byte EEPROM with one-time-"
            "programmable lock bits.\n"
            "OTP_PROGRAM command burns the fuse map.\n"
        ),
    }
    gen_l4_regmap(project, extracted)
    l4 = _read(project, "L4_REGMAP")
    assert l4["otp_layout"] is not None
    assert l4["no_otp_layout_in_input"] is False
    assert l4["otp_layout"]["depth_bytes"] == 128
    assert l4["otp_layout"]["width_bits"] == 8


def test_l4_aggregate_no_otp_geometry_leak_across_3_classes(
        tmp_path_factory) -> None:
    """3 OTP-less IC classes — none should carry depth_bytes=128."""
    cases = [
        ("aes",  "Verilog AES core. NIST FIPS 197.\n"),
        ("sha",  "SHA-256 hash. Combinational.\n"),
        ("dram", "DRAM controller. ECC over 64-bit data.\n"),
    ]
    leaked = []
    for label, src in cases:
        proj = _seed(tmp_path_factory.mktemp(label))
        gen_l4_regmap(proj, {"spec.txt": src})
        l4 = _read(proj, "L4_REGMAP")
        layout = l4.get("otp_layout")
        if isinstance(layout, dict) and layout.get("depth_bytes") == 128:
            leaked.append(label)
    assert not leaked, f"otp_layout geometry leak: {leaked}"


def test_l11_otp_less_project_emits_null_geometry(tmp_path: Path) -> None:
    """L11 mirrors L4. When L4 has no OTP layout, L11 must emit
    `otp_layout: null`, `depth: null`, `width_bits: null` and the
    flag — not the v1.6.69 hardcoded 128 / 8."""
    project = _seed(tmp_path, l_docs={
        # Simulated L4 from an OTP-less project.
        "L4_REGMAP": {
            "schema_version": 2,
            "otp_layout": None,
            "no_otp_layout_in_input": True,
        },
    })
    gen_l11_otp_content(project, {})
    l11 = _read(project, "L11_OTP_CONTENT")
    assert l11["otp_layout"] is None
    assert l11["depth"] is None
    assert l11["width_bits"] is None
    assert l11["no_otp_layout_in_input"] is True


def test_l11_with_otp_bytes_keeps_geometry(tmp_path: Path) -> None:
    """When OTP bytes ARE present (rich-input project case via
    input/otp/*.hex), L11 keeps depth and width_bits populated."""
    project = _seed(tmp_path, l_docs={
        "L4_REGMAP": {
            "schema_version": 2,
            "otp_layout": {
                "fields": [{"field": "ID[0]", "address_hint": "0x00"}],
                "depth_bytes": 128, "width_bits": 8,
            },
            "no_otp_layout_in_input": False,
        },
    })
    # No actual OTP bytes file, but L4 has fields → has_otp_evidence.
    gen_l11_otp_content(project, {})
    l11 = _read(project, "L11_OTP_CONTENT")
    # Geometry preserved because L4 reports OTP layout fields.
    assert l11["otp_layout"] is not None
    assert l11["width_bits"] == 8


# ---------------------------------------------------------------------------
# Bug B — L2.protocol_overview byte_order/wake_required_pre_command
# ---------------------------------------------------------------------------

def test_l2_byte_order_null_when_no_structured_evidence(
        tmp_path: Path) -> None:
    """A project README mentioning AXI / SPI as the IP's bus
    interface — protocol_overview should populate `half_duplex` /
    `wire_count` from the keyword match BUT `byte_order` and
    `wake_required_pre_command` should be null without a structured
    byte-order or wake-required claim. v1.6.69 returned LSB-first /
    True; v1.6.70 returns null."""
    project = _seed(tmp_path)
    extracted = {
        "README.md": (
            "MyDRAMCtrl. AXI4 slave interface for memory controller.\n"
            "Supports read/write transactions per AXI spec.\n"
        ),
    }
    gen_l2_frs(project, extracted)
    l2 = _read(project, "L2_FRS")
    po = l2.get("protocol_overview")
    assert po is not None
    assert po.get("byte_order") is None
    assert po.get("wake_required_pre_command") is None


def test_l2_byte_order_populates_when_structured_claim_present(
        tmp_path: Path) -> None:
    """`byte order: LSB-first` (structured) → populates."""
    project = _seed(tmp_path)
    extracted = {
        "datasheet.txt": (
            "EXAMPLE_CHIP single-wire EXAMPLE_PROTOCOL protocol.\n"
            "Byte order: LSB-first within each frame.\n"
            "Wake pulse required before each command.\n"
        ),
    }
    gen_l2_frs(project, extracted)
    l2 = _read(project, "L2_FRS")
    po = l2.get("protocol_overview")
    assert po is not None
    assert po["byte_order"] == "LSB-first"
    assert po["wake_required_pre_command"] is True


def test_l2_byte_order_null_on_passing_lsb_first_mention(
        tmp_path: Path) -> None:
    """A cipher's internal "process bytes LSB-first within each word"
    is NOT a claim about the IC's bus byte order. v1.6.70 structured
    regex requires `byte order:` / `bit order:` etc. to fire, so a
    plain `LSB-first` mention in unrelated text doesn't trigger."""
    project = _seed(tmp_path)
    extracted = {
        "README.md": (
            "ChaCha stream cipher. The cipher processes bytes "
            "LSB-first within each 32-bit word during the "
            "quarter-round.\n"
            "AXI4 slave interface.\n"
        ),
    }
    gen_l2_frs(project, extracted)
    l2 = _read(project, "L2_FRS")
    po = l2.get("protocol_overview")
    # AXI fires protocol_evidence_found, but byte_order should be
    # null because the LSB-first mention is the cipher's INTERNAL
    # convention, not a structured byte-order column.
    assert po is not None
    assert po.get("byte_order") is None


def test_l2_aggregate_no_aid_default_leak_across_3_protocol_classes(
        tmp_path_factory) -> None:
    """3 IC classes that mention bus protocol keywords (AXI / SPI /
    UART) but have no EXAMPLE_PROTOCOL-class characteristics — none should pick
    up `byte_order: LSB-first` or `wake_required_pre_command: true`."""
    cases = [
        ("dram",  "DRAM controller. AXI4 slave for read/write.\n"),
        ("uart",  "UART transceiver. 8-N-1 frame.\n"),
        ("spi",   "SPI master. 4-wire MOSI/MISO/SCLK/SS.\n"),
    ]
    for label, src in cases:
        proj = _seed(tmp_path_factory.mktemp(label))
        gen_l2_frs(proj, {"spec.txt": src})
        l2 = _read(proj, "L2_FRS")
        po = l2.get("protocol_overview")
        if po is None:
            continue
        assert po.get("byte_order") is None, \
            f"{label}: byte_order leak {po.get('byte_order')!r}"
        assert po.get("wake_required_pre_command") is None, \
            f"{label}: wake_required leak"


# ---------------------------------------------------------------------------
# v1.6.71 -- broaden L2.byte_order ACCEPT to natural-language IC-bus
# claims while keeping cipher-internal mentions REJECTED.
# ---------------------------------------------------------------------------

def test_l2_byte_order_populates_on_natural_language_lsb_first_at_bus_level(
        tmp_path: Path) -> None:
    """v1.6.70 narrow regex rejected `data is transmitted LSB-first
    on the ID bus` -- a legitimate natural-language IC-bus byte-order
    claim. v1.6.71 broadens ACCEPT to capture these forms."""
    project = _seed(tmp_path)
    extracted = {
        "datasheet.txt": (
            "EXAMPLE_CHIP single-wire EXAMPLE_PROTOCOL protocol.\n"
            "Wake pulse required before each command.\n"
            "Data is transmitted LSB-first on the ID bus.\n"
        ),
    }
    gen_l2_frs(project, extracted)
    l2 = _read(project, "L2_FRS")
    po = l2.get("protocol_overview")
    assert po is not None
    assert po["byte_order"] == "LSB-first"


def test_l2_byte_order_rejects_cipher_internal_lsb_first_mention(
        tmp_path: Path) -> None:
    """Cipher-internal `processes bytes LSB-first within each word`
    is NOT an IC bus byte-order claim. The two-stage ACCEPT/REJECT
    matcher must keep this rejected."""
    project = _seed(tmp_path)
    extracted = {
        "spec.txt": (
            "ChaCha stream cipher.\n"
            "The cipher processes bytes LSB-first within each "
            "32-bit word during the quarter-round.\n"
            "AXI4 slave interface.\n"
        ),
    }
    gen_l2_frs(project, extracted)
    l2 = _read(project, "L2_FRS")
    po = l2.get("protocol_overview")
    assert po is not None
    assert po.get("byte_order") is None


def test_l2_byte_order_populates_on_transmitted_msb_first(
        tmp_path: Path) -> None:
    """`data is transmitted as MSB-first on the bus` matches the
    `(?:transmitted|sent|...) (?:as )?(LSB|MSB)-first` ACCEPT regex."""
    project = _seed(tmp_path)
    extracted = {
        "datasheet.txt": (
            "Single-wire half-duplex command bus.\n"
            "Wake pulse required before each command.\n"
            "Data is transmitted as MSB-first on the bus.\n"
        ),
    }
    gen_l2_frs(project, extracted)
    l2 = _read(project, "L2_FRS")
    po = l2.get("protocol_overview")
    assert po is not None
    assert po["byte_order"] == "MSB-first"


# ---------------------------------------------------------------------------
# v1.6.71 -- L2.protocol_overview emission gate tightened
# (issue #8 Bug A residual: 7/10 thin-input projects leaked a
# partially-filled dict via bare protocol-keyword match).
# ---------------------------------------------------------------------------

def test_l2_protocol_overview_null_on_passing_mention_of_dram_class(
        tmp_path: Path) -> None:
    """`integrating LiteDRAM` mentions DDR-class but the line lacks a
    structural anchor describing the IC's OWN command bus. v1.6.71
    tightened gate must emit null."""
    project = _seed(tmp_path)
    extracted = {
        "README.md": (
            "LiteDRAM is a small footprint and configurable DRAM "
            "core integrating ECC over 64-bit data.\n"
        ),
    }
    gen_l2_frs(project, extracted)
    l2 = _read(project, "L2_FRS")
    po = l2.get("protocol_overview")
    assert po is None
    assert l2["no_protocol_overview_in_input"] is True


def test_l2_protocol_overview_emits_dict_when_real_bus_described(
        tmp_path: Path) -> None:
    """A line like `EXAMPLE_CHIP single-wire EXAMPLE_PROTOCOL command bus. Half-duplex
    frames carry opcodes.` has BOTH a protocol keyword (single-wire)
    AND a structural anchor (bus, command, frame) -- emit the dict."""
    project = _seed(tmp_path)
    extracted = {
        "datasheet.txt": (
            "EXAMPLE_CHIP single-wire EXAMPLE_PROTOCOL command bus.\n"
            "Half-duplex frames carry opcodes.\n"
        ),
    }
    gen_l2_frs(project, extracted)
    l2 = _read(project, "L2_FRS")
    po = l2.get("protocol_overview")
    assert po is not None
    assert po["half_duplex"] is True
    assert po["wire_count"] == 1


def test_l2_protocol_overview_null_on_block_cipher(
        tmp_path: Path) -> None:
    """`AES-256 block cipher. Pure combinational rounds. NIST FIPS
    197.` has no bus-protocol description -- emit null."""
    project = _seed(tmp_path)
    extracted = {
        "spec.txt": (
            "AES-256 block cipher.\n"
            "Pure combinational rounds.\n"
            "NIST FIPS 197.\n"
        ),
    }
    gen_l2_frs(project, extracted)
    l2 = _read(project, "L2_FRS")
    assert l2["protocol_overview"] is None
    assert l2["no_protocol_overview_in_input"] is True


def test_l2_aggregate_no_dict_leak_on_3_thin_input_classes(
        tmp_path_factory) -> None:
    """3 IC classes that mention bus acronyms in passing without
    describing their OWN command interface. None should emit a
    protocol_overview dict.

    Counterpoint: an AES core with `AXI4 slave interface for
    register access` DOES describe its own bus (AXI + interface on
    the same line) and is allowed to emit a dict -- that's the
    legitimate rich-input case the gate must NOT suppress.
    """
    cases_null = [
        ("dram",   "Integrating LiteDRAM for DDR3 memory backing.\n"),
        ("serdes", "High-speed link layer for storage applications.\n"),
        ("sata",   "LiteSATA, a SATA controller for peripherals.\n"),
    ]
    for label, src in cases_null:
        proj = _seed(tmp_path_factory.mktemp(label))
        gen_l2_frs(proj, {"spec.txt": src})
        l2 = _read(proj, "L2_FRS")
        assert l2["protocol_overview"] is None, \
            f"{label}: dict leaked: {l2['protocol_overview']!r}"

    # Positive control -- the IC really does speak AXI on its own
    # interface, so the dict SHOULD emit. Guards against
    # over-tightening.
    proj_pos = _seed(tmp_path_factory.mktemp("axi_real"))
    gen_l2_frs(proj_pos, {
        "spec.txt": "AES core. AXI4 slave interface for register access.\n"
    })
    l2_pos = _read(proj_pos, "L2_FRS")
    assert l2_pos["protocol_overview"] is not None
