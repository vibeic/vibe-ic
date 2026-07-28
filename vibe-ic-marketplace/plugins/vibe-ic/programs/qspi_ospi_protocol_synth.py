"""Quad/Octal SPI (QSPI/OSPI) — JEDEC Expanded SPI (xSPI, JESD251) protocol
synth helper.

v0.1.91 — protocol #56 of the Phase-1 doc-extraction sweep. ic_class-gated
overlay for a doc that exhibits the QSPI/OSPI (xSPI / JESD251) structural
signature: an EXPANSION of classic SPI that widens the data path to MULTIPLE
bidirectional data lines (IO0..IO3 Quad / IO0..IO7 Octal, "x8", or DQ0..DQ7),
adds a structured command-address-dummy-data phase protocol with programmable
DUMMY CYCLES and a protocol-mode notation (1-1-1 / 1-1-4 / 1-4-4 / 4-4-4 /
8-8-8 / 8D-8D-8D), a standard JEDEC serial-flash command set (Write Enable
0x06, Read Status 0x05, Fast Read 0x0B, Quad I/O Fast Read 0xEB, Quad Output
0x6B, Quad Page Program 0x32, Sector/Block Erase 0x20/0xD8, Read JEDEC ID
0x9F, Read SFDP 0x5A), SFDP (JESD216) self-description, SDR and DDR (DTR)
signaling with an optional Data Strobe (DQS), 3-byte / 4-byte addressing, and
continuous-read / XIP. Applies JESD251 (2020) + JESD216 SFDP + common
quad/octal SPI NOR-flash command conventions to L1-L23.

Doctrine — GENERAL not keyword: detection uses canonical STRUCTURAL QSPI/OSPI
signatures (multi-IO data lines, dummy cycles, the flash command set / SFDP,
the protocol-mode notation, SDR/DDR + DQS, the xSPI / JESD251 framework) read
from the L-doc CONTENT blob ONLY. It NEVER reads the input-document filename or
the benchmark folder name.

------------------------------------------------------------------------------
CHICKEN-AND-EGG MUTEX vs the plain-SPI detector (the hard part — like
SMBus/PMBus-extends-I2C)
------------------------------------------------------------------------------
QSPI/OSPI EXTENDS classic SPI and SHARES SCLK + CS# and is single-IO
SPI-Mode-0/Mode-3 compatible in its 1-1-1 commands. The runner has a UNIVERSAL
SPI synth (``spi_protocol_synth.apply_spi_synth``, R53/R54/R55) gated by the
inline predicate ``(MOSI AND MISO AND SCK) OR (CPOL AND CPHA)``. A QSPI/OSPI
spec names IO0=MOSI / IO1=MISO and SCLK and mentions Mode-0/Mode-3 CPOL/CPHA,
so the runner's ``is_spi`` ALSO fires on a QSPI/OSPI doc (empirically confirmed
at build time — the generated L1/L2 blob carries MOSI/MISO/SCK and CPOL/CPHA).

To avoid cross-firing in BOTH directions:

  (a) ``is_qspi_ospi`` REQUIRES QSPI/OSPI-only vocabulary that a plain-SPI spec
      (e.g. the Motorola/Freescale S12SPIV4 block: SCLK/MOSI/MISO/SS#,
      CPOL/CPHA, a bare full-duplex shift register) does NOT contain — at least
      one of {multi-IO data lines IO0..IO3 / IO0..IO7 / DQ0..DQ7, dummy cycles,
      the protocol-mode notation 1-1-4 / 1-4-4 / 4-4-4 / 8-8-8 / 8D-8D-8D, the
      flash command set (Fast Read 0x0B / Quad I/O 0xEB / Read SFDP 0x5A /
      Write Enable 0x06 / Read JEDEC ID 0x9F), SFDP, xSPI / JESD251, DDR/DTR
      with DQS} — AND DEFERS when the doc is plain-single-IO-SPI-primary (only
      MOSI/MISO single data lines + CPOL/CPHA + a shift register, with NONE of
      the multi-IO / dummy-cycle / flash-command / protocol-mode vocabulary).
      The S12SPIV4 generated blob has none of those tokens, so the predicate
      stays False on it (empirically confirmed at build time).

  (b) This module's synth is wired to run AFTER the SPI synth and
      FORCE-ASSIGNS (direct assignment, NOT setdefault) every L1/L2/L3/L4/...
      key the SPI synth would populate — the cross-protocol force-overwrite
      doctrine (SMBus-on-I2C, NVMe-on-PCIe, I3C-extends-I2C). Because
      ``is_spi`` DOES fire on a QSPI/OSPI doc, the SPI synth WILL have written
      plain-SPI content first; this module fully replaces it with the
      QSPI/OSPI-canonical values so plain-SPI output cannot leak through.

Public entry: ``apply_qspi_ospi_synth(generated_docs_dir, is_qspi_ospi,
qspi_ospi_ic_name)``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import l_doc_generator_stamp as _stamp


def _ensure_dict(d: dict, key: str) -> dict:
    """Return d[key] as a dict, replacing a pre-existing None/empty/non-dict."""
    v = d.get(key)
    if not isinstance(v, dict):
        v = {}
        d[key] = v
    return v


def _read(p: Path) -> dict:
    return json.loads(p.read_text())


def _write(p: Path, d: dict) -> None:
    # THE L-document write chokepoint: stamps the producing release onto
    # the document, then serialises it byte-identically to before.
    _stamp.dump(p, d)


_MAIN_DOCS = [
    "L1_DATASHEET.json", "L2_FRS.json", "L3_CMD_PROTOCOL.json",
    "L4_REGMAP.json", "L5_ADI_SPEC.json", "L6_CONTROL_LOGIC.json",
    "L7_TEST_DEBUG.json", "L8_RTL_CONSTANTS.json",
    "L8_TIMING_WAVEFORM.json", "L9_INTEGRATION_SPEC.json",
    "L10_TEST_CASES.json", "L11_OTP_CONTENT.json",
    "L12_BEHAVIORAL_SEQUENCES.json", "L13_LAB_CALIBRATION.json",
]

_FIELDS_DOCS = [
    "L14_PROTOCOL_VERSIONING.json", "L15_ENCODING_TABLES.json",
    "L16_COMPLIANCE_PROPERTIES.json", "L17_CHANNEL_SIGNAL_CATALOG.json",
    "L18_INTERCONNECT_TOPOLOGY.json", "L19_CONSTRAINTS_PDK.json",
    "L20_DFT_SCAN_TOPOLOGY.json", "L21_POWER_INTENT.json",
    "L22_VERIFICATION_PLAN.json", "L23_SECURITY_REQUIREMENTS.json",
]

# Canonical QSPI/OSPI structural facts (JESD251 xSPI 2020 / JESD216 SFDP /
# common JEDEC quad/octal SPI NOR-flash command conventions).
_PROTOCOL_MODES = [
    "1-1-1", "1-1-2", "1-2-2", "1-1-4", "1-4-4", "4-4-4",
    "1-1-8", "1-8-8", "8-8-8", "8D-8D-8D",
]
_FLASH_COMMANDS = [
    {"opcode": "0x06", "name": "Write Enable (WREN)"},
    {"opcode": "0x04", "name": "Write Disable (WRDI)"},
    {"opcode": "0x05", "name": "Read Status Register-1"},
    {"opcode": "0x03", "name": "Read Data"},
    {"opcode": "0x0B", "name": "Fast Read"},
    {"opcode": "0x3B", "name": "Dual Output Fast Read"},
    {"opcode": "0xBB", "name": "Dual I/O Fast Read"},
    {"opcode": "0x6B", "name": "Quad Output Fast Read"},
    {"opcode": "0xEB", "name": "Quad I/O Fast Read"},
    {"opcode": "0x02", "name": "Page Program"},
    {"opcode": "0x32", "name": "Quad Page Program"},
    {"opcode": "0x20", "name": "Sector Erase (4 KB)"},
    {"opcode": "0xD8", "name": "Block Erase (64 KB)"},
    {"opcode": "0xC7", "name": "Chip Erase"},
    {"opcode": "0x9F", "name": "Read JEDEC ID"},
    {"opcode": "0x5A", "name": "Read SFDP"},
    {"opcode": "0xB7", "name": "Enter 4-Byte Address Mode"},
    {"opcode": "0xE9", "name": "Exit 4-Byte Address Mode"},
]


# ----------------------------------------------------------------------
# Module-level CONTENT-ONLY detector (the runner wires this; evaluated on the
# generated L1+L2 blob, NEVER on a filename).
# ----------------------------------------------------------------------
def is_qspi_ospi(blob: str) -> bool:
    """Quad/Octal SPI (QSPI/OSPI) — JEDEC Expanded SPI (xSPI / JESD251): an
    EXPANSION of classic SPI for serial NOR-flash / NAND / PSRAM.

    MUTEX vs plain single-IO SPI: a plain-SPI spec (SCLK/MOSI/MISO/SS#,
    CPOL/CPHA, a bare full-duplex shift register) carries NONE of the
    QSPI/OSPI-specific vocabulary below, so requiring at least TWO independent
    QSPI/OSPI-only structural features (multi-IO data lines / dummy cycles /
    the protocol-mode notation / the flash command set / SFDP / xSPI-JESD251 /
    DDR-DTR+DQS) keeps the predicate False on a Motorola-S12SPIV4-style
    single-IO SPI document while firing on a genuine QSPI/OSPI/xSPI doc. All
    checks read ``blob`` only — no filename / folder / benchmark-name read.
    """
    if not blob:
        return False
    low = blob.lower()

    # --- MUTEX vs eSPI (v0.2.13) -----------------------------------------
    # eSPI (Enhanced SPI) is SPI-FAMILY and genuinely supports Single/Dual/Quad
    # I/O over ESPI_IO[3:0] plus a Flash Access channel, so it satisfies the
    # multi-IO + flash QSPI structural features. But eSPI is NOT a JEDEC xSPI
    # NOR-flash command interface: it multiplexes four logical channels
    # (Peripheral / Virtual Wire / OOB / Flash Access) with a command/response
    # turnaround protocol and GET/SET_CONFIGURATION negotiation. If the eSPI
    # four-channel signature is present, DEFER and let the eSPI synth own it.
    espi_signature = (
        "virtual wire" in low
        and "flash access" in low
        and ("oob" in low or "out-of-band" in low or "out of band" in low)
        and ("get_configuration" in low or "set_configuration" in low
             or "espi_alert" in low or "enhanced serial peripheral" in low))
    if espi_signature:
        return False

    # --- MUTEX vs ONFI / parallel-NAND-flash (the hard sibling) ----------
    # ONFI (Open NAND Flash Interface) is a PARALLEL, byte/word-wide NAND
    # protocol that ALSO uses DQ0..DQ7 data lines, a DQS read strobe, DDR
    # signaling, "x8", and the words "Write Enable" / "Page Program" — so it
    # shares much of the structural vocabulary below WITHOUT being a serial
    # SPI-derived bus. ONFI is identified by its parallel-NAND control pins and
    # the ONFI name (ALE/CLE/RE#/WE#/R/B#, the command/address/data cycle
    # model). QSPI/OSPI is a SERIAL SPI expansion (SCLK + CS#, no ALE/CLE/WE#).
    # If the doc is ONFI/parallel-NAND-primary and is NOT explicitly an
    # xSPI/QSPI/OSPI serial doc, DEFER — let the ONFI synth own it.
    onfi_nand = (
        "ONFI" in blob
        or "Open NAND Flash Interface" in blob
        or ("NAND" in blob and ("ALE" in blob or "CLE" in blob
                                or "R/B#" in blob or "Ready/Busy" in blob))
    )
    serial_spi_named = (
        "xSPI" in blob or "JESD251" in blob or "JESD 251" in blob
        or "Expanded Serial Peripheral Interface" in blob
        or "Expanded SPI" in blob
        or "QSPI" in blob or "OSPI" in blob
        or "Quad SPI" in blob or "Octal SPI" in blob or "Quad/Octal" in blob
        or "SFDP" in blob or "Serial Flash Discoverable Parameters" in blob
    )
    if onfi_nand and not serial_spi_named:
        return False

    # --- QSPI/OSPI-specific structural features (absent from a plain-SPI spec) ---

    # (1) Multiple bidirectional data lines IO0..IO3 (Quad) / IO0..IO7 (Octal).
    #     Plain SPI has only single MOSI + single MISO, never IO2/IO3/IO4..IO7.
    #     NOTE: DQ0..DQ7 is intentionally NOT used here as a multi_io signal,
    #     because parallel NAND (ONFI) also names DQ0..DQ7 — the IO0..IO7
    #     naming is the SPI-expansion-specific data-line vocabulary.
    multi_io = (
        ("IO2" in blob and "IO3" in blob)
        or "IO7" in blob
    )

    # (2) Programmable dummy cycles — the command-address-dummy-data latency
    #     phase that plain full-duplex SPI does not have.
    dummy_cycles = (
        "dummy cycle" in low or "dummy cycles" in low or "dummy clock" in low
    )

    # (3) Protocol-mode (lane) notation: 1-1-4 / 1-4-4 / 4-4-4 / 8-8-8 /
    #     8D-8D-8D — names the lanes used per phase; unique to multi-IO xSPI.
    mode_notation = (
        "8D-8D-8D" in blob or "8-8-8" in blob or "4-4-4" in blob
        or "1-4-4" in blob or "1-1-4" in blob or "1-8-8" in blob
        or "1-1-8" in blob or "1-2-2" in blob
    )

    # (4) Standard JEDEC serial-flash command set — by NAME (not bare hex
    #     opcodes, which collide with arbitrary register addresses in unrelated
    #     specs). The SPI-NOR named commands are the strong, specific signal.
    flash_cmds = sum(1 for t in (
        "Quad I/O", "Quad Output", "Fast Read", "Read SFDP",
        "Quad Page Program", "Read JEDEC ID", "Write Enable Latch",
        "Sector Erase", "Block Erase", "Chip Erase",
    ) if t in blob)
    flash_command_set = flash_cmds >= 2

    # (5) SFDP — Serial Flash Discoverable Parameters (JESD216).
    sfdp = ("SFDP" in blob or "Serial Flash Discoverable Parameters" in blob)

    # (6) JEDEC xSPI / JESD251 expanded-SPI framework.
    xspi = (
        "xSPI" in blob or "JESD251" in blob or "JESD 251" in blob
        or "Expanded Serial Peripheral Interface" in blob
        or "Expanded SPI" in blob
    )

    # (7) Quad / Octal multi-IO modes named explicitly (require an explicit
    #     Quad/Octal SPI phrasing, not a coincidental "Octal"+"x8" pair).
    quad_octal = (
        ("Quad" in blob and "Octal" in blob and "SPI" in blob)
        or "8D-8D-8D" in blob
        or ("quad mode" in low and "octal mode" in low)
        or "Quad I/O" in blob
        or "Quad SPI" in blob or "Octal SPI" in blob
    )

    # (8) DDR / DTR signaling with a Data Strobe (DQS). DQS+DDR alone also
    #     appears in DDR DRAM / ONFI, so this is only a SUPPORTING feature —
    #     the 8D-8D-8D octal-DDR notation is the SPI-specific form.
    ddr_dqs = (
        "8D-8D-8D" in blob
        or "Double Transfer Rate" in blob
        or ("DQS" in blob and ("DDR" in blob or "DTR" in blob))
    )

    features = [
        multi_io, dummy_cycles, mode_notation, flash_command_set,
        sfdp, xspi, quad_octal, ddr_dqs,
    ]
    n_features = sum(1 for f in features if f)

    # DEFER if the doc is plain-single-IO-SPI-primary: require at least TWO
    # independent QSPI/OSPI-specific structural features so a plain-SPI doc
    # (which has none) and an accidental single-token mention both stay False.
    if n_features < 2:
        return False

    # Anchor: it must actually be the QSPI/OSPI/xSPI family — a SERIAL,
    # SPI-expansion, multi-IO FLASH memory interface. Require either an
    # explicit serial-SPI-NOR name (xSPI / QSPI / OSPI / Quad-Octal SPI / SFDP)
    # OR the conjunction of multi-IO data lines (IO0..IO7) with the SPI-specific
    # phase/lane vocabulary (protocol-mode notation, dummy cycles, or the named
    # flash command set). A plain-SPI doc has none of these; an ONFI/NAND or
    # BLE doc lacks the serial-SPI-NOR identity and the IO0..IO7 + lane/dummy/
    # named-command conjunction.
    spi_nor_identity = (
        xspi or sfdp
        or "QSPI" in blob or "OSPI" in blob
        or "Quad SPI" in blob or "Octal SPI" in blob or "Quad/Octal" in blob
    )
    structural_serial_flash = (
        multi_io and (mode_notation or dummy_cycles or flash_command_set)
    )
    family = spi_nor_identity or structural_serial_flash
    return bool(family and n_features >= 2)


def apply_qspi_ospi_synth(generated_docs_dir: Path, is_qspi_ospi: bool,
                          qspi_ospi_ic_name: Optional[str]) -> None:
    """Apply JESD251 xSPI / Quad/Octal SPI synth when the signature matched.

    QSPI/OSPI EXPANDS classic SPI; because the runner's ``is_spi`` ALSO fires
    on a QSPI/OSPI doc (shared SCLK/CS#, IO0=MOSI/IO1=MISO, CPOL/CPHA), the SPI
    synth runs first and writes plain-SPI content. This routine FORCE-OVERWRITES
    (direct assignment, NOT setdefault) every key the SPI synth would populate
    with the QSPI/OSPI-canonical value, so plain-SPI output cannot leak through
    (cross-protocol force-overwrite doctrine).
    """
    if not is_qspi_ospi:
        return
    gd = Path(generated_docs_dir)

    # --- Force ic_name across ALL 24 docs FIRST (main + fields docs). ---
    if qspi_ospi_ic_name is not None:
        for n in _MAIN_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                d["ic_name"] = qspi_ospi_ic_name
                _write(q, d)
        for n in _FIELDS_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                f = _ensure_dict(d, "fields")
                f["ic_name"] = qspi_ospi_ic_name
                d["ic_name"] = qspi_ospi_ic_name
                _write(q, d)

    _l1(gd)
    _l2(gd)
    _l3(gd)
    _l4(gd)
    _l5(gd)
    _l6(gd)
    _l7(gd)
    _l8_rtl(gd)
    _l8_timing(gd)
    _l9(gd)
    _l10(gd)
    _l11(gd)
    _l12(gd)
    _l13(gd)
    _l14(gd)
    _l15(gd)
    _l16(gd)
    _l17(gd)
    _l18(gd)
    _l19(gd)
    _l20(gd)
    _l21(gd)
    _l22(gd)
    _l23(gd)


# ----------------------------------------------------------------------
# L1 — QSPI/OSPI (xSPI) datasheet header (FORCE-OVERWRITE).
# ----------------------------------------------------------------------
def _l1(gd: Path) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    d["document_title"] = (
        "Expanded Serial Peripheral Interface (xSPI) — Quad/Octal SPI "
        "(QSPI/OSPI) Controller and NOR-Flash Memory Interface Specification")
    d["version"] = "JESD251 (xSPI, 2020) / JESD251-1 (2021) / JESD216 (SFDP)"
    d["revised_date"] = "2020 (JESD251) / 2021 (JESD251-1)"
    d["manufacturer"] = "JEDEC Solid State Technology Association"
    d["copyright"] = "© JEDEC Solid State Technology Association"
    d["abstract"] = (
        "The Expanded Serial Peripheral Interface (xSPI), standardized by JEDEC "
        "as JESD251, is an EXPANSION of the classic Serial Peripheral Interface "
        "(SPI) for high-throughput access to serial NOR flash, serial NAND, and "
        "PSRAM. Where single-IO SPI uses a bare four-wire full-duplex shift "
        "register (SCLK, single MOSI output, single MISO input, CS#), Quad SPI "
        "(QSPI) and Octal SPI (OSPI) widen the data path to multiple "
        "bidirectional data lines — IO0..IO3 (Quad) and IO0..IO7 (Octal, 'x8'; "
        "DQ0..DQ7) — and add a structured command protocol: an instruction "
        "phase, an address phase (3 or 4 bytes), optional mode/alternate bits, "
        "programmable DUMMY CYCLES, and a data phase. Each phase can run over 1, "
        "2, 4, or 8 lanes, giving the protocol-mode notation 1-1-1 / 1-1-4 / "
        "1-4-4 / 4-4-4 / 8-8-8 / 8D-8D-8D, in Single Data Rate (SDR) or Double "
        "Data Rate (DDR/DTR) with an optional Data Strobe (DQS). A standard "
        "JEDEC flash command set (Write Enable 0x06, Read Status 0x05, Fast "
        "Read 0x0B, Quad I/O Fast Read 0xEB, Quad Output 0x6B, Quad Page "
        "Program 0x32, Sector Erase 0x20, Block Erase 0xD8, Read JEDEC ID 0x9F, "
        "Read SFDP 0x5A) and SFDP (JESD216) self-description make a generic "
        "controller interoperable with many devices. Continuous-read / "
        "eXecute-In-Place (XIP) supports code-shadow boot.")
    d["keywords"] = [
        "QSPI", "OSPI", "Quad SPI", "Octal SPI", "xSPI", "JESD251", "JESD216",
        "SFDP", "Quad/Octal", "multi-IO", "IO0", "IO1", "IO2", "IO3", "IO7",
        "DQ0", "DQ7", "dummy cycles", "Fast Read", "Quad I/O Fast Read",
        "0x0B", "0xEB", "0x6B", "0x32", "0x9F", "0x5A", "0x06",
        "1-4-4", "4-4-4", "8-8-8", "8D-8D-8D", "SDR", "DDR", "DTR", "DQS",
        "Continuous Read", "XIP", "3-byte address", "4-byte address",
        "Page Program", "Sector Erase", "Block Erase", "NOR flash", "PSRAM",
        "SCLK", "CS#",
    ]
    d["external_pins"] = [
        "SCLK — serial clock driven by the controller (master); up to 133 MHz "
        "typical SDR, 166-200+ MHz on fast devices",
        "CS# — active-low chip select; frames each command (CS# low for the "
        "whole transaction)",
        "IO0 — data line 0; in single mode this is MOSI (controller output), "
        "bidirectional/tri-stated in multi-IO modes",
        "IO1 — data line 1; in single mode this is MISO (controller input)",
        "IO2 — data line 2 (Quad/Octal); repurposed from the classic /WP "
        "(write-protect) pin",
        "IO3 — data line 3 (Quad/Octal); repurposed from the classic /HOLD "
        "or /RESET pin",
        "IO4..IO7 (DQ4..DQ7) — data lines 4-7 (Octal 'x8' only)",
        "DQS — optional Data Strobe (octal DDR); source-synchronous read "
        "strobe edge-aligned to read data",
        "RESET# — active-low hardware reset (xSPI)",
    ]
    d["data_line_count"] = {"single": 1, "dual": 2, "quad": 4, "octal": 8}
    d["protocol_modes"] = list(_PROTOCOL_MODES)
    d["address_byte_options"] = [3, 4]
    d["max_clock_MHz"] = {"typical_sdr": 133, "fast_sdr": 200,
                          "note": "DDR/octal raise effective throughput"}
    d["modes_of_operation"] = [
        {"name": "Single (1-1-1)", "data_lines": 1,
         "description": "SPI Mode-0/Mode-3 compatible: IO0=MOSI, IO1=MISO; "
         "instruction, address and data all on one lane."},
        {"name": "Dual (1-1-2 / 1-2-2)", "data_lines": 2,
         "description": "Data (and optionally address) on IO0-IO1."},
        {"name": "Quad (1-1-4 / 1-4-4 / 4-4-4 QPI)", "data_lines": 4,
         "description": "Data (and optionally address/instruction) on "
         "IO0-IO3; /WP->IO2, /HOLD->IO3 repurposed."},
        {"name": "Octal (1-1-8 / 1-8-8 / 8-8-8)", "data_lines": 8,
         "description": "All phases up to 8 lanes IO0-IO7 ('x8'), SDR."},
        {"name": "Octal DDR (8D-8D-8D)", "data_lines": 8,
         "description": "All phases on 8 lanes at double data rate with DQS "
         "source-synchronous capture (xSPI/JESD251)."},
    ]
    d["key_features"] = [
        "Expansion of classic SPI for NOR flash / NAND / PSRAM (JEDEC xSPI / "
        "JESD251); shares SCLK + CS# with single-IO SPI.",
        "Multi-IO data path: Single (IO0=MOSI/IO1=MISO), Dual (IO0-IO1), Quad "
        "(IO0-IO3), Octal (IO0-IO7 / DQ0-DQ7, 'x8').",
        "In Quad mode the /WP pin becomes IO2 and the /HOLD (or /RESET) pin "
        "becomes IO3.",
        "Structured command protocol: instruction -> address (3/4 byte) -> "
        "mode/alternate bits -> programmable DUMMY CYCLES -> data.",
        "Protocol-mode notation S-A-D: 1-1-1, 1-1-4, 1-4-4, 4-4-4 (QPI), "
        "1-1-8, 1-8-8, 8-8-8, 8D-8D-8D.",
        "SDR and DDR (DTR) signaling; data on one edge (SDR) or both edges "
        "(DDR), with an optional source-synchronous DQS in octal DDR.",
        "Command Extension byte in xSPI octal mode (repeated/inverted "
        "instruction -> 16-bit instruction field).",
        "Standard JEDEC flash command set: WREN 0x06, RDSR 0x05, Fast Read "
        "0x0B, Quad I/O 0xEB, Quad Output 0x6B, Quad PP 0x32, Sector Erase "
        "0x20, Block Erase 0xD8, Read JEDEC ID 0x9F, Read SFDP 0x5A.",
        "SFDP (JESD216) self-describing parameter tables (read with 0x5A) for "
        "controller auto-configuration of dummy cycles and read mode.",
        "Continuous Read Mode (mode/alternate bits) and eXecute-In-Place (XIP) "
        "for code-shadow boot.",
        "3-byte (24-bit, 16 MB) and 4-byte (32-bit, >16 MB) addressing; enter "
        "4-byte 0xB7 / exit 0xE9.",
        "Volatile / non-volatile xSPI configuration & status registers "
        "(dummy-cycle latency, mode, DQS enable, address-byte count).",
    ]
    d["topology_summary"] = (
        "Point-to-point: one xSPI/QSPI/OSPI controller (master) drives SCLK + "
        "CS# to one memory device per chip-select; the multiple bidirectional "
        "data lines IO0..IO7 are shared between the two ends, their direction "
        "set per command phase.")
    d["use_cases"] = [
        "Code-shadow / XIP boot from serial NOR flash for MCUs and SoCs",
        "High-bandwidth firmware and look-up-table storage via octal DDR",
        "PSRAM expansion memory over the same QSPI/OSPI controller",
        "FPGA configuration flash",
        "Automotive / industrial code storage with SFDP auto-configuration",
    ]
    d["revision_history"] = [
        {"version": "Quad SPI (vendor)", "date": "~2010",
         "description": "Multi-IO 1-1-4 / 1-4-4 / 4-4-4 reads added over "
                        "classic SPI NOR flash."},
        {"version": "SFDP (JESD216)", "date": "2011",
         "description": "Serial Flash Discoverable Parameters self-description "
                        "table (read with 0x5A)."},
        {"version": "Octal SPI (vendor)", "date": "~2017",
         "description": "x8 data lines IO0-IO7; octal SDR and DDR."},
        {"version": "xSPI (JESD251)", "date": "2020",
         "description": "JEDEC standardization of expanded SPI: octal DDR "
                        "(8D-8D-8D), DQS, command extension, register "
                        "interface, variable latency."},
        {"version": "JESD251-1", "date": "2021",
         "description": "xSPI profile / addendum."},
    ]
    d["overview"] = (
        "Quad/Octal SPI (QSPI/OSPI), standardized by JEDEC as the Expanded SPI "
        "(xSPI, JESD251), is an expansion of classic SPI for serial NOR flash, "
        "NAND, and PSRAM. It shares SCLK and CS# with single-IO SPI and is "
        "Mode-0/Mode-3 compatible in its 1-1-1 commands, but widens the data "
        "path to multiple bidirectional lines IO0..IO3 (Quad) and IO0..IO7 "
        "(Octal) and replaces SPI's bare full-duplex shift with a structured "
        "instruction-address-dummy-data phase protocol. Each phase runs over "
        "1/2/4/8 lanes (protocol modes 1-1-1 / 1-1-4 / 1-4-4 / 4-4-4 / 8-8-8 / "
        "8D-8D-8D), in SDR or DDR, with an optional DQS strobe in octal DDR. A "
        "standard JEDEC flash command set (Write Enable 0x06, Read Status 0x05, "
        "Fast Read 0x0B, Quad I/O Fast Read 0xEB, Quad Page Program 0x32, "
        "Sector/Block Erase 0x20/0xD8, Read JEDEC ID 0x9F, Read SFDP 0x5A) and "
        "the SFDP (JESD216) self-describing parameter tables let a generic "
        "controller auto-configure dummy cycles and the optimal multi-IO read "
        "and support continuous-read / XIP code-shadow boot. This is DISTINCT "
        "from plain single-IO SPI, which has only SCLK/MOSI/MISO/SS#, CPOL/CPHA "
        "and a shift register, with none of the multi-IO lines, dummy cycles, "
        "flash command set, SFDP, protocol-mode notation, or xSPI register "
        "framework.")
    _write(p, d)


# ----------------------------------------------------------------------
# L2 — QSPI/OSPI functional requirement set + protocol overview.
# ----------------------------------------------------------------------
def _l2(gd: Path) -> None:
    p = gd / "L2_FRS.json"
    if not p.is_file():
        return
    d = _read(p)
    po = _ensure_dict(d, "protocol_overview")
    po["type"] = (
        "Expanded multi-IO Serial Peripheral Interface (xSPI / QSPI / OSPI, "
        "JESD251) for NOR flash / NAND / PSRAM: a controller-driven SCLK + CS# "
        "interface with multiple bidirectional data lines (IO0..IO3 Quad / "
        "IO0..IO7 Octal) and a structured instruction-address-dummy-data phase "
        "protocol with programmable dummy cycles, SDR/DDR signaling, and a "
        "standard JEDEC flash command set.")
    po["duplex"] = (
        "half-duplex per phase (the bidirectional data lines IO0..IO7 are "
        "driven by one end at a time; instruction/address/data phases are "
        "directional). The single-IO 1-1-1 compatibility mode uses the classic "
        "full-duplex MOSI/MISO pair.")
    po["synchronous_serial"] = True
    po["source_synchronous"] = True  # octal DDR uses DQS source-synchronous
    po["embedded_clock"] = False
    po["clock_line"] = "SCLK (driven by the controller/master)"
    po["data_lines"] = "IO0..IO3 (Quad) / IO0..IO7 (Octal), bidirectional"
    po["data_strobe"] = "DQS (optional, octal DDR source-synchronous read)"
    po["chip_select"] = "CS# (active-low, frames each command)"
    po["extends"] = "classic single-IO SPI (shares SCLK + CS#)"
    po["spi_modes"] = ["Mode 0 (CPOL=0, CPHA=0)", "Mode 3 (CPOL=1, CPHA=1)"]
    po["protocol_modes"] = list(_PROTOCOL_MODES)
    po["address_byte_options"] = [3, 4]
    po["data_rate"] = {"sdr": True, "ddr_dtr": True}
    po["command_phases"] = ["instruction", "address (3/4 byte)",
                            "mode/alternate bits", "dummy cycles", "data"]
    po["max_clock_MHz"] = {"typical_sdr": 133, "fast_sdr": 200}
    po["sfdp"] = {
        "name": "Serial Flash Discoverable Parameters", "spec": "JESD216",
        "read_command": "0x5A", "signature": "SFDP (0x50444653)",
        "purpose": "self-describing capability tables for controller "
                   "auto-configuration of read mode and dummy cycles.",
    }
    po["xip_continuous_read"] = True
    d["protocol_overview"] = po
    d["functional_requirements"] = [
        {"id": "FR-PHY-01", "text": "QSPI/OSPI shares SCLK and CS# with "
         "classic SPI and is Mode-0/Mode-3 compatible in single-IO (1-1-1) "
         "commands; IO0 is MOSI and IO1 is MISO in single mode."},
        {"id": "FR-IO-02", "text": "The data path widens to multiple "
         "bidirectional data lines: Dual (IO0-IO1), Quad (IO0-IO3, with /WP->"
         "IO2 and /HOLD->IO3), and Octal (IO0-IO7 / DQ0-DQ7, 'x8')."},
        {"id": "FR-PHASE-03", "text": "Each transaction is a sequence of "
         "phases: instruction -> address (3 or 4 bytes) -> optional mode/"
         "alternate bits -> programmable dummy cycles -> data; each phase may "
         "use 1/2/4/8 lanes."},
        {"id": "FR-MODE-04", "text": "Protocol modes are written S-A-D (lanes "
         "per instruction/address/data): 1-1-1, 1-1-2, 1-2-2, 1-1-4, 1-4-4, "
         "4-4-4 (QPI), 1-1-8, 1-8-8, 8-8-8 (SDR), 8D-8D-8D (octal DDR)."},
        {"id": "FR-DUMMY-05", "text": "Dummy cycles absorb the device read "
         "latency between address/mode and data; their count is device- and "
         "frequency-dependent and configurable, and is discoverable via SFDP."},
        {"id": "FR-DDR-06", "text": "SDR launches/captures one bit per lane "
         "per SCLK cycle; DDR/DTR uses both SCLK edges. Octal DDR (8D-8D-8D) "
         "drives a source-synchronous Data Strobe (DQS) edge-aligned to read "
         "data for high-frequency capture."},
        {"id": "FR-CMD-07", "text": "A standard JEDEC flash command set is "
         "supported: Write Enable 0x06, Read Status 0x05, Fast Read 0x0B, Quad "
         "I/O Fast Read 0xEB, Quad Output 0x6B, Quad Page Program 0x32, Sector "
         "Erase 0x20, Block Erase 0xD8, Read JEDEC ID 0x9F, Read SFDP 0x5A."},
        {"id": "FR-SFDP-08", "text": "SFDP (JESD216) self-describing parameter "
         "tables, read with 0x5A, expose density, supported read modes, "
         "dummy-cycle and mode-bit counts, erase types, and address bytes so a "
         "generic controller can auto-configure."},
        {"id": "FR-ADDR-09", "text": "3-byte (24-bit, 16 MB) and 4-byte "
         "(32-bit, >16 MB) addressing are supported; 4-byte mode is entered "
         "with 0xB7 and exited with 0xE9, or via dedicated 4-byte opcodes."},
        {"id": "FR-XIP-10", "text": "Continuous Read Mode (mode/alternate "
         "bits) lets the next read skip the instruction phase, supporting "
         "eXecute-In-Place (XIP) code-shadow boot."},
        {"id": "FR-PROG-11", "text": "A program/erase requires Write Enable "
         "(0x06, sets WEL) first; the controller polls the Write In Progress "
         "(WIP) bit via Read Status (0x05) until the operation completes."},
        {"id": "FR-REG-12", "text": "xSPI defines volatile and non-volatile "
         "configuration registers (protocol mode, dummy-cycle latency, DQS "
         "enable, address-byte count, drive strength) in addition to the "
         "legacy status registers."},
    ]
    d["error_response_conditions"] = [
        "WEL not set — a Page Program / Erase is ignored.",
        "WIP busy — a new program/erase to a busy device is rejected; the "
        "controller must poll WIP.",
        "Wrong dummy-cycle configuration — high-frequency multi-IO reads "
        "return corrupted data (the most common bring-up error).",
        "Block/sector protection (BP) violation — a protected region rejects "
        "erase/program.",
        "Unsupported opcode in the current protocol mode — device ignores it.",
    ]
    d["compliance_requirements"] = [
        "Single-IO (1-1-1) SPI Mode-0/Mode-3 compatibility on SCLK/CS#/IO0/IO1.",
        "Correct phase sequencing: instruction -> address -> mode -> dummy -> "
        "data, with the configured dummy-cycle count per read mode.",
        "Support the claimed multi-IO modes (Dual/Quad/Octal) and SDR/DDR.",
        "Implement the mandatory flash command subset and WIP/WEL handshake.",
        "Where claimed: SFDP (JESD216) tables for self-description.",
        "Where claimed (xSPI): octal DDR 8D-8D-8D with DQS, command extension, "
        "and the configuration-register interface.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L3 — QSPI/OSPI command/phase protocol.
# ----------------------------------------------------------------------
def _l3(gd: Path) -> None:
    p = gd / "L3_CMD_PROTOCOL.json"
    if not p.is_file():
        return
    d = _read(p)
    d["protocol_type"] = (
        "Multi-IO command-oriented memory protocol. Each transaction is framed "
        "by CS# and consists of an instruction phase, an address phase (3/4 "
        "byte), optional mode/alternate bits, programmable dummy cycles, and a "
        "data phase. Each phase may run over 1/2/4/8 data lines (SDR or DDR), "
        "expressed as the protocol-mode notation S-A-D.")
    d["byte_oriented"] = True
    d["burst_based"] = True
    d["command_phases"] = [
        {"phase": "instruction", "width": "8-bit opcode (16-bit with command "
         "extension in xSPI octal mode)", "lanes": "1/4/8"},
        {"phase": "address", "width": "3 bytes (24-bit) or 4 bytes (32-bit)",
         "lanes": "1/2/4/8"},
        {"phase": "mode/alternate bits", "width": "device-specific (e.g. 8 "
         "bits)", "lanes": "matches address lanes",
         "purpose": "continuous-read / XIP hint"},
        {"phase": "dummy cycles", "width": "programmable count (SFDP-"
         "discoverable)", "lanes": "n/a (no data driven)",
         "purpose": "absorb device read latency before data"},
        {"phase": "data", "width": "1..N bytes", "lanes": "1/2/4/8"},
    ]
    d["protocol_mode_notation"] = {
        "format": "<instruction lanes>-<address lanes>-<data lanes>",
        "examples": list(_PROTOCOL_MODES),
        "ddr_suffix": "a 'D' suffix (e.g. 8D-8D-8D) denotes Double Data Rate "
                      "on that phase.",
    }
    d["channels"] = [
        {"name": "SCLK", "direction": "controller -> device",
         "description": "Serial clock; SDR captures one edge, DDR both edges."},
        {"name": "CS#", "direction": "controller -> device",
         "description": "Active-low chip select; frames each command."},
        {"name": "IO0..IO3 / IO0..IO7", "direction": "bidirectional",
         "description": "Multi-IO data lines; direction set per phase. IO0=MOSI "
         "and IO1=MISO in single mode; /WP->IO2, /HOLD->IO3 in Quad."},
        {"name": "DQS", "direction": "device -> controller (octal DDR)",
         "description": "Optional source-synchronous read data strobe."},
    ]
    d["flash_command_set"] = list(_FLASH_COMMANDS)
    d["read_mode_examples"] = [
        {"name": "Fast Read", "opcode": "0x0B", "mode": "1-1-1",
         "dummy_cycles": 8},
        {"name": "Dual Output Fast Read", "opcode": "0x3B", "mode": "1-1-2",
         "dummy_cycles": 8},
        {"name": "Dual I/O Fast Read", "opcode": "0xBB", "mode": "1-2-2"},
        {"name": "Quad Output Fast Read", "opcode": "0x6B", "mode": "1-1-4",
         "dummy_cycles": 8},
        {"name": "Quad I/O Fast Read", "opcode": "0xEB", "mode": "1-4-4",
         "mode_bits": 8, "dummy_cycles": 6,
         "continuous_read": "mode bits enable instruction-less next read"},
        {"name": "Octal I/O Read (xSPI)", "opcode": "device-specific",
         "mode": "8-8-8 / 8D-8D-8D", "dqs": True},
    ]
    d["addressing"] = {
        "byte_options": [3, 4],
        "3_byte_reach": "16 MB", "4_byte_reach": ">16 MB",
        "enter_4_byte": "0xB7", "exit_4_byte": "0xE9",
        "dedicated_4_byte_opcodes": ["0x0C Fast Read", "0xEC Quad I/O Fast "
                                     "Read", "0x12 Page Program", "0xDC Block "
                                     "Erase"],
        "bit_order": "MSB-first on each data line.",
    }
    d["sfdp"] = {
        "read_command": "0x5A", "mode": "1-1-1", "dummy_cycles": 8,
        "address_bits": 24, "signature": "SFDP (0x50444653)",
        "tables": ["Parameter Headers", "Basic Flash Parameter Table (BFPT)"],
        "spec": "JESD216",
    }
    d["frame_format"] = {
        "framing": "CS# low begins the command; CS# high ends it.",
        "bit_order": "MSB-first per data line.",
        "phase_sequence": "instruction -> address -> [mode bits] -> dummy "
        "cycles -> data.",
        "command_extension": "xSPI octal mode appends a Command Extension byte "
        "(repeated or inverted instruction) for a 16-bit instruction field.",
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L4 — register / command-code map (status, config, flash commands).
# ----------------------------------------------------------------------
def _l4(gd: Path) -> None:
    p = gd / "L4_REGMAP.json"
    if not p.is_file():
        return
    d = _read(p)
    d["register_map_present"] = True
    d["notes"] = (
        "QSPI/OSPI is command-oriented: opcodes (0x00..0xFF) select read / "
        "program / erase / status / configuration functions accessed through "
        "the instruction-address-dummy-data phase protocol. xSPI adds a "
        "volatile/non-volatile configuration-register interface; the legacy "
        "Status Register WIP/WEL bits are the primary program/erase handshake. "
        "Memory itself is a linear byte address space (3 or 4 byte address).")
    d["status_register_1"] = {
        "opcode_read": "0x05", "opcode_write": "0x01", "width_bits": 8,
        "bits": [
            {"name": "WIP", "bit": 0, "desc": "Write In Progress (busy); set "
             "during program/erase, polled for completion."},
            {"name": "WEL", "bit": 1, "desc": "Write Enable Latch; set by 0x06 "
             "before any program/erase."},
            {"name": "BP0..BP2", "bit": "2-4", "desc": "Block protection."},
            {"name": "SRWD/SRP", "bit": 7, "desc": "Status register write "
             "protect."},
        ],
    }
    d["status_register_2"] = {"opcode_read": "0x35", "width_bits": 8,
                              "note": "QE (Quad Enable) and other vendor bits."}
    d["configuration_registers_xspi"] = [
        {"name": "Protocol mode", "desc": "SPI / QPI / octal SDR / octal DDR "
         "selection (volatile + non-volatile)."},
        {"name": "Dummy-cycle latency", "desc": "Configurable read latency "
         "(dummy cycles) per frequency."},
        {"name": "DQS enable", "desc": "Enable source-synchronous read strobe "
         "in octal DDR."},
        {"name": "Address-byte count", "desc": "3-byte vs 4-byte addressing."},
        {"name": "Drive strength", "desc": "Output drive configuration."},
    ]
    d["command_groups"] = [
        {"group": "Write enable / status", "commands": [
            {"name": "Write Enable (WREN)", "code": "0x06"},
            {"name": "Write Disable (WRDI)", "code": "0x04"},
            {"name": "Read Status Register-1", "code": "0x05"},
            {"name": "Read Status Register-2", "code": "0x35"},
            {"name": "Write Status Register", "code": "0x01"}]},
        {"group": "Read", "commands": [
            {"name": "Read Data", "code": "0x03"},
            {"name": "Fast Read", "code": "0x0B"},
            {"name": "Dual Output Fast Read", "code": "0x3B"},
            {"name": "Quad Output Fast Read", "code": "0x6B"},
            {"name": "Quad I/O Fast Read", "code": "0xEB"},
            {"name": "Read SFDP", "code": "0x5A"}]},
        {"group": "Program / erase", "commands": [
            {"name": "Page Program", "code": "0x02"},
            {"name": "Quad Page Program", "code": "0x32"},
            {"name": "Sector Erase (4 KB)", "code": "0x20"},
            {"name": "Block Erase (64 KB)", "code": "0xD8"},
            {"name": "Chip Erase", "code": "0xC7"}]},
        {"group": "Identification / mode", "commands": [
            {"name": "Read JEDEC ID", "code": "0x9F"},
            {"name": "Enter 4-Byte Address Mode", "code": "0xB7"},
            {"name": "Exit 4-Byte Address Mode", "code": "0xE9"},
            {"name": "Enable Reset", "code": "0x66"},
            {"name": "Reset Device", "code": "0x99"}]},
    ]
    d["address_space"] = {
        "type": "linear byte-addressed flash memory",
        "address_bytes": [3, 4],
        "3_byte_reach": "16 MB", "4_byte_reach": ">16 MB",
        "page_size_bytes": 256, "sector_size_bytes": 4096,
        "block_size_bytes": 65536,
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L5 — electrical / signaling spec (single-ended push-pull multi-IO).
# ----------------------------------------------------------------------
def _l5(gd: Path) -> None:
    p = gd / "L5_ADI_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["analog_digital_interface_present"] = True
    d["signaling_summary"] = (
        "Single-ended CMOS/LVCMOS push-pull signaling. SCLK is driven by the "
        "controller; the data lines IO0..IO7 are bidirectional, tri-stated, "
        "and push-pull when driven (NOT open-drain — distinct from I2C/SMBus). "
        "Single-IO mode is SPI Mode-0 (CPOL=0,CPHA=0) / Mode-3 (CPOL=1,CPHA=1) "
        "compatible. In SDR a bit is captured on one SCLK edge; in DDR on both "
        "edges. Octal DDR uses a source-synchronous DQS strobe edge-aligned to "
        "read data for reliable high-frequency capture.")
    d["spi_modes"] = {"mode_0": "CPOL=0, CPHA=0", "mode_3": "CPOL=1, CPHA=1"}
    d["clocking"] = (
        "Synchronous to controller-driven SCLK. SDR = one edge; DDR/DTR = both "
        "edges. Octal DDR is source-synchronous via DQS (the device returns a "
        "strobe with the read data).")
    d["max_clock_MHz"] = {"typical_sdr": 133, "fast_sdr": 200}
    d["data_lines"] = {
        "single": ["IO0 (MOSI)", "IO1 (MISO)"],
        "quad": ["IO0", "IO1", "IO2 (/WP)", "IO3 (/HOLD or /RESET)"],
        "octal": ["IO0", "IO1", "IO2", "IO3", "IO4", "IO5", "IO6", "IO7"],
        "direction": "bidirectional, tri-stated; direction set per phase",
    }
    d["data_strobe"] = "DQS (optional, octal DDR; source-synchronous read)"
    d["bit_order"] = "MSB-first on each data line"
    d["extends"] = "classic SPI electrical layer (single-ended push-pull)"
    _write(p, d)


# ----------------------------------------------------------------------
# L6 — transaction FSM (command/address/dummy/data + program/erase).
# ----------------------------------------------------------------------
def _l6(gd: Path) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["fsm_states"] = [
        {"name": "IDLE", "description": "CS# high; bus idle, controller waiting "
         "to issue a command."},
        {"name": "SELECT", "description": "Controller drives CS# low to begin a "
         "command."},
        {"name": "INSTRUCTION", "description": "8-bit opcode shifted out "
         "(16-bit with command extension in xSPI octal mode), MSB-first, on "
         "1/4/8 lanes."},
        {"name": "ADDRESS", "description": "3 or 4 address bytes shifted out on "
         "the address lanes (for commands that take an address)."},
        {"name": "MODE_BITS", "description": "Optional mode/alternate bits for "
         "continuous-read / XIP."},
        {"name": "DUMMY", "description": "Programmable dummy cycles with no data "
         "driven, absorbing the device read latency."},
        {"name": "DATA", "description": "Data byte(s) read or written on the "
         "data lanes, MSB-first; DDR uses both SCLK edges, octal DDR aligns to "
         "DQS."},
        {"name": "DESELECT", "description": "CS# high ends the command; bus "
         "returns to IDLE."},
        {"name": "PROGRAM_ERASE", "description": "After WREN (sets WEL) the "
         "device performs Page Program / Erase; WIP=1 while busy."},
        {"name": "POLL_WIP", "description": "Controller issues Read Status "
         "(0x05) repeatedly until WIP clears, signaling completion."},
    ]
    d["fsm_hints"] = {
        "trigger": "CS# falling begins a command; the opcode selects the phase "
        "sequence (which of address/mode/dummy/data phases are present and on "
        "how many lanes).",
        "rule": "Dummy cycles MUST match the configured/SFDP-declared latency "
        "for the read mode and frequency, or the data phase is misaligned.",
        "program_erase": "WEL must be set (0x06) before program/erase; the "
        "controller polls WIP via 0x05 for completion.",
    }
    d["dummy_cycle_logic"] = (
        "The dummy-cycle count between the address/mode phase and the data "
        "phase is configurable (and SFDP-discoverable). It absorbs the "
        "device's internal read access latency; too few dummy cycles at high "
        "SCLK frequency corrupts the read.")
    d["exit_from_reset_or_poweron"] = (
        "After power-on/RESET#/software reset (0x66 then 0x99) the device "
        "powers up in single-IO (1-1-1) SPI mode with default (often 3-byte) "
        "addressing; the controller may read SFDP, then switch protocol mode "
        "(QPI / octal) and address-byte count via configuration commands.")
    d["configurations"] = [
        {"name": "Single (1-1-1)", "description": "SPI-compatible boot mode."},
        {"name": "Quad (1-4-4 / 4-4-4)", "description": "Quad Enable (QE) set; "
         "/WP->IO2, /HOLD->IO3."},
        {"name": "Octal SDR (8-8-8)", "description": "x8 data path, single "
         "data rate."},
        {"name": "Octal DDR (8D-8D-8D)", "description": "x8 double data rate "
         "with DQS source-synchronous capture (xSPI)."},
        {"name": "Continuous Read / XIP", "description": "Mode bits keep the "
         "device in read so the next access skips the instruction phase."},
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L7 — observability: status, JEDEC ID, SFDP, WIP polling.
# ----------------------------------------------------------------------
def _l7(gd: Path) -> None:
    p = gd / "L7_TEST_DEBUG.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_debug_architecture_present"] = True
    d["spec_provided_observability"] = [
        {"name": "Status Register (0x05/0x35)", "purpose": "WIP (busy), WEL "
         "(write-enabled), block-protection, and quad-enable bits."},
        {"name": "Read JEDEC ID (0x9F)", "purpose": "Manufacturer + device ID "
         "for identification."},
        {"name": "SFDP (0x5A)", "purpose": "Self-describing parameter tables "
         "(density, read modes, dummy cycles, erase types, address bytes)."},
        {"name": "WIP polling", "purpose": "Read Status repeatedly to observe "
         "program/erase completion."},
        {"name": "xSPI configuration registers", "purpose": "Read back the "
         "protocol mode, dummy-cycle latency, DQS enable, and address-byte "
         "count."},
    ]
    d["error_detection_mechanisms"] = [
        "WIP/WEL handshake detects incomplete or unauthorized program/erase.",
        "Block-protection bits flag protected-region violations.",
        "SFDP self-description prevents wrong-dummy-cycle / wrong-read-mode "
        "misconfiguration.",
        "Device-specific internal ECC on some xSPI NOR detects bit errors "
        "(the bus protocol itself has no transaction CRC).",
    ]
    d["notes"] = (
        "QSPI/OSPI observability is in-band over the same lines: Status "
        "Register, JEDEC ID, SFDP, WIP polling, and (xSPI) configuration "
        "registers. There is no protocol-defined scan/JTAG layer; chip-level "
        "DFT is the device implementer's concern.")
    _write(p, d)


# ----------------------------------------------------------------------
# L8 RTL constants — QSPI/OSPI widths, opcodes, dummy/latency.
# ----------------------------------------------------------------------
def _l8_rtl(gd: Path) -> None:
    p = gd / "L8_RTL_CONSTANTS.json"
    if not p.is_file():
        return
    d = _read(p)
    wp = _ensure_dict(d, "width_parameters")
    wp.update({
        "INSTRUCTION_BITS": 8,
        "INSTRUCTION_BITS_XSPI_OCTAL": 16,
        "ADDRESS_BYTES_3": 3,
        "ADDRESS_BYTES_4": 4,
        "ADDRESS_BITS_3BYTE": 24,
        "ADDRESS_BITS_4BYTE": 32,
        "DATA_LINES_SINGLE": 1,
        "DATA_LINES_DUAL": 2,
        "DATA_LINES_QUAD": 4,
        "DATA_LINES_OCTAL": 8,
        "DATA_BYTE_BITS": 8,
        "STATUS_REGISTER_BITS": 8,
        "PAGE_SIZE_BYTES": 256,
        "SECTOR_SIZE_BYTES": 4096,
        "BLOCK_SIZE_BYTES": 65536,
        "FAST_READ_DUMMY_CYCLES": 8,
        "QUAD_IO_READ_MODE_BITS": 8,
        "SFDP_DUMMY_CYCLES": 8,
        "SFDP_ADDRESS_BITS": 24,
        "MAX_CLOCK_MHZ_SDR": 133,
        "MAX_CLOCK_MHZ_FAST": 200,
    })
    d["opcodes"] = {c["name"]: c["opcode"] for c in _FLASH_COMMANDS}
    d["key_constants_for_RTL_authoring"] = {
        "extends_spi": True,
        "shares_sclk_cs": True,
        "spi_mode_0_and_3": True,
        "multi_io_data_lines": True,
        "max_data_lines": 8,
        "bidirectional_io": True,
        "msb_first": True,
        "command_phases": ["instruction", "address", "mode_bits",
                           "dummy_cycles", "data"],
        "protocol_modes": list(_PROTOCOL_MODES),
        "address_byte_options": [3, 4],
        "sdr_and_ddr": True,
        "dqs_octal_ddr": True,
        "dummy_cycles_programmable": True,
        "sfdp_present": True,
        "sfdp_read_opcode": "0x5A",
        "wip_wel_handshake": True,
        "continuous_read_xip": True,
    }
    d["reserved_constants"] = {
        "sfdp_signature_hex": "0x50444653",
        "enter_4byte_opcode": "0xB7",
        "exit_4byte_opcode": "0xE9",
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L8 timing — phase / SDR-DDR / DQS waveform.
# ----------------------------------------------------------------------
def _l8_timing(gd: Path) -> None:
    p = gd / "L8_TIMING_WAVEFORM.json"
    if not p.is_file():
        return
    d = _read(p)
    d["transaction_waveform"] = {
        "framing": "CS# low | instruction | [address 3/4B] | [mode bits] | "
                   "[dummy cycles] | data | CS# high",
        "fast_read_1_1_1": "CS#v | 0x0B (8b) | A23..A0 (24b) | 8 dummy | "
                           "D0,D1,... | CS#^",
        "quad_io_1_4_4": "CS#v | 0xEB (8b,1 lane) | A23..A0 (4 lanes) | mode "
                         "bits (4 lanes) | 6 dummy | data (4 lanes) | CS#^",
        "octal_ddr_8d": "CS#v | instr+ext (8 lanes, both edges) | addr (8 "
                        "lanes, both edges) | dummy | data (8 lanes, both "
                        "edges, DQS-aligned) | CS#^",
    }
    d["clock_edges"] = {
        "sdr": "one bit per lane per SCLK cycle (captured on one edge)",
        "ddr_dtr": "one bit per lane per SCLK edge (both rising and falling)",
    }
    d["dqs_timing"] = (
        "In octal DDR (8D-8D-8D) the device drives DQS edge-aligned to the read "
        "data on IO0..IO7 so the controller captures source-synchronously, "
        "tolerating SCLK-to-data flight time at high frequency.")
    d["dummy_cycle_timing"] = (
        "The programmable dummy-cycle count sits between the address/mode phase "
        "and the data phase; it must equal the device's configured/SFDP read "
        "latency for the chosen mode and frequency.")
    d["spi_mode_timing"] = {
        "mode_0": "CPOL=0, CPHA=0 (SCLK idles low, sample on rising edge)",
        "mode_3": "CPOL=1, CPHA=1 (SCLK idles high, sample on rising edge)",
    }
    d["bit_order"] = "MSB-first on each data line."
    d["general_timing_rule"] = (
        "QSPI/OSPI is synchronous to controller-driven SCLK. A transaction is "
        "framed by CS# and runs instruction -> address -> [mode] -> dummy -> "
        "data, each phase on 1/2/4/8 lanes (SDR or DDR). The dummy-cycle count "
        "and (octal DDR) DQS alignment are the timing-critical parameters.")
    _write(p, d)


# ----------------------------------------------------------------------
# L9 — integration spec (QSPI/OSPI controller <-> flash device).
# ----------------------------------------------------------------------
def _l9(gd: Path) -> None:
    p = gd / "L9_INTEGRATION_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["module_role"] = (
        "Expanded multi-IO SPI (xSPI / QSPI / OSPI) controller or memory "
        "device: a controller drives SCLK + CS# and the bidirectional data "
        "lines IO0..IO7 to a serial NOR-flash / NAND / PSRAM device, issuing "
        "the instruction-address-dummy-data phase protocol with programmable "
        "dummy cycles, SDR/DDR signaling, the JEDEC flash command set, SFDP "
        "auto-configuration, and continuous-read / XIP.")
    d["topology_description"] = (
        "Point-to-point per chip-select: one controller (master) to one memory "
        "device. SCLK and CS# are controller-driven; IO0..IO7 are shared "
        "bidirectional data lines whose direction is set per command phase; "
        "octal DDR adds a device-driven DQS strobe.")
    io = _ensure_dict(d, "integration_overview")
    io.update({
        "extends": "classic single-IO SPI (shares SCLK + CS#)",
        "wires": ["SCLK", "CS#", "IO0..IO3 (Quad) / IO0..IO7 (Octal)",
                  "DQS (octal DDR, optional)", "RESET# (xSPI)"],
        "data_lines_max": 8,
        "protocol_modes": list(_PROTOCOL_MODES),
        "address_byte_options": [3, 4],
        "sdr_and_ddr": True,
        "sfdp_present": True,
        "xip_continuous_read": True,
        "max_clock_MHz": {"typical_sdr": 133, "fast_sdr": 200},
        "host_side_register_spec": "flash command set (0x00..0xFF) over the "
        "phase protocol; Status Register WIP/WEL for program/erase handshake; "
        "xSPI configuration registers for mode/latency/DQS/address-bytes.",
    })
    d["interface_categories"] = [
        "SCLK / CS# — controller-driven clock and chip-select (shared with "
        "classic SPI).",
        "Multi-IO data lines — IO0..IO3 (Quad) / IO0..IO7 (Octal), "
        "bidirectional.",
        "DQS — optional source-synchronous read strobe (octal DDR).",
        "Command/phase protocol — instruction/address/mode/dummy/data.",
        "Flash command set + SFDP — read/program/erase/status/identify.",
        "xSPI register interface — protocol mode, dummy latency, DQS, "
        "address-byte count.",
    ]
    d["soc_dependent_items"] = [
        "Number of data lines wired (1/2/4/8) and pin repurposing (/WP->IO2, "
        "/HOLD->IO3 in Quad).",
        "Dummy-cycle configuration vs SCLK frequency (or SFDP auto-config).",
        "Address-byte count (3 vs 4) and the chosen read command/mode.",
        "Whether DDR/octal DDR with DQS is used.",
        "Memory-mapped XIP window vs indirect access in the controller.",
        "Chip-select count and per-device protocol mode.",
    ]
    d["default_signal_values_when_omitted"] = (
        "CS# idle high (deselected); SCLK idle per CPOL; IO lines tri-stated "
        "when not driven; device powers up in single-IO (1-1-1) SPI mode with "
        "default addressing until reconfigured.")
    _write(p, d)


# ----------------------------------------------------------------------
# L10 — derived compliance/test categories.
# ----------------------------------------------------------------------
def _l10(gd: Path) -> None:
    p = gd / "L10_TEST_CASES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_cases_present"] = (
        "partial - the specification defines protocol behaviors and "
        "compliance points (phase protocol, multi-IO modes, dummy cycles, "
        "flash command set, SFDP, SDR/DDR, addressing) but is not itself a "
        "testbench.")
    d["derived_compliance_test_categories"] = [
        "Single-IO (1-1-1) SPI Mode-0/Mode-3 compatibility on SCLK/CS#/"
        "IO0/IO1.",
        "Each multi-IO read mode: 1-1-2, 1-2-2, 1-1-4, 1-4-4, 4-4-4, 1-1-8, "
        "1-8-8, 8-8-8, 8D-8D-8D — correct lane usage.",
        "Dummy-cycle correctness across frequencies and read modes; "
        "wrong-count corruption detection.",
        "Flash command set: WREN/WRDI, Read Status, Fast Read (0x0B), Quad I/O "
        "(0xEB), Quad Output (0x6B), Quad PP (0x32), Sector/Block Erase, Read "
        "JEDEC ID (0x9F).",
        "SFDP read (0x5A): signature, parameter headers, Basic Flash Parameter "
        "Table decode.",
        "3-byte vs 4-byte addressing; Enter/Exit 4-byte (0xB7/0xE9) and "
        "dedicated 4-byte opcodes.",
        "SDR vs DDR (DTR) data capture; octal DDR DQS source-synchronous "
        "alignment.",
        "Program/erase: WEL gating, WIP polling, page/sector/block "
        "boundaries.",
        "Continuous Read Mode (mode bits) / XIP instruction-less reads.",
        "xSPI configuration registers: protocol mode, dummy latency, DQS "
        "enable, address-byte count; command extension byte.",
        "Reset: power-on default mode, RESET# / Enable-Reset (0x66) + "
        "Reset-Device (0x99).",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L11 — identity / discoverable fields (no OTP as a protocol concept).
# ----------------------------------------------------------------------
def _l11(gd: Path) -> None:
    p = gd / "L11_OTP_CONTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    d["otp_present"] = False
    d["otp_equivalent_factory_burned_fields"] = [
        {"field": "JEDEC ID", "width_bits": 24, "location": "command 0x9F",
         "note": "Manufacturer ID + memory type + capacity."},
        {"field": "SFDP parameter tables", "width_bits": "variable",
         "location": "command 0x5A", "note": "Density, supported read modes, "
         "dummy-cycle / mode-bit counts, erase types, address bytes (JESD216)."},
        {"field": "Unique ID / serial", "width_bits": "device-specific",
         "location": "vendor command",
         "note": "Many devices provide a factory-programmed unique ID."},
        {"field": "Security/OTP region", "width_bits": "device-specific",
         "location": "vendor OTP commands",
         "note": "Some NOR flash add a small one-time-programmable security "
                 "region; this is a device feature, not part of the bus "
                 "protocol."},
    ]
    d["notes"] = (
        "The QSPI/OSPI bus protocol does not define OTP. Device identity and "
        "capability are discoverable in-band via Read JEDEC ID (0x9F) and SFDP "
        "(0x5A). Individual NOR-flash devices may add a vendor OTP/security "
        "region, but that is a device feature outside the xSPI bus spec.")
    _write(p, d)


# ----------------------------------------------------------------------
# L12 — behavioral sequences (read / program / erase / SFDP / XIP).
# ----------------------------------------------------------------------
def _l12(gd: Path) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["quad_io_fast_read_sequence"] = [
        "1. Controller drives CS# low.",
        "2. Send instruction 0xEB (Quad I/O Fast Read) on IO0 (1 lane).",
        "3. Send the 3- or 4-byte address on IO0-IO3 (4 lanes).",
        "4. Send the mode/alternate bits on IO0-IO3 (enables continuous read "
        "if set).",
        "5. Wait the configured dummy cycles (e.g. 6).",
        "6. Device drives read data on IO0-IO3 (4 lanes), MSB-first.",
        "7. Controller drives CS# high to end the read.",
    ]
    d["octal_ddr_read_sequence"] = [
        "1. CS# low.",
        "2. Send instruction + command-extension byte on IO0-IO7, both SCLK "
        "edges (8D).",
        "3. Send the 4-byte address on IO0-IO7, both edges.",
        "4. Wait the configured dummy cycles.",
        "5. Device drives read data on IO0-IO7 at double data rate, with DQS "
        "edge-aligned for source-synchronous capture.",
        "6. CS# high.",
    ]
    d["page_program_sequence"] = [
        "1. Write Enable: CS# low, 0x06, CS# high (sets WEL).",
        "2. Program: CS# low, opcode (0x02 Page Program or 0x32 Quad Page "
        "Program), 3/4-byte address, up to 256 data bytes, CS# high.",
        "3. WIP=1 while the page programs.",
        "4. Poll Read Status (0x05) until WIP=0 -> program complete.",
    ]
    d["erase_sequence"] = [
        "1. Write Enable (0x06) -> WEL=1.",
        "2. Erase: CS# low, opcode (0x20 Sector / 0xD8 Block / 0xC7 Chip), "
        "address (for sector/block), CS# high.",
        "3. Poll Read Status (0x05) until WIP=0.",
    ]
    d["sfdp_read_sequence"] = [
        "1. CS# low, 0x5A (Read SFDP), 24-bit address, 8 dummy cycles "
        "(1-1-1).",
        "2. Read the SFDP signature, Parameter Headers, and the Basic Flash "
        "Parameter Table.",
        "3. Decode supported read modes, dummy-cycle counts, erase types, and "
        "address bytes; configure the controller accordingly.",
    ]
    d["mode_switch_sequence"] = [
        "1. Power-on / reset -> single-IO (1-1-1) SPI mode.",
        "2. (Optional) Read SFDP to learn capabilities.",
        "3. Set Quad Enable (QE) / enter QPI (0x35/0x38 vendor) or enter octal "
        "mode via configuration register.",
        "4. Configure dummy-cycle latency, address-byte count, and (octal DDR) "
        "DQS for the target frequency.",
    ]
    d["xip_continuous_read_sequence"] = [
        "1. Perform a Quad/Octal I/O read (e.g. 0xEB) and set the continuous-"
        "read mode bits.",
        "2. The device stays in read; the NEXT access skips the instruction "
        "phase (address + dummy + data only).",
        "3. A CPU fetches code directly via the memory-mapped XIP window.",
    ]
    d["reset_sequence"] = [
        "1. Assert RESET# (xSPI) or issue Enable-Reset (0x66) then "
        "Reset-Device (0x99).",
        "2. Device returns to single-IO (1-1-1) SPI mode with default "
        "addressing.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L13 — lab/characterization targets.
# ----------------------------------------------------------------------
def _l13(gd: Path) -> None:
    p = gd / "L13_LAB_CALIBRATION.json"
    if not p.is_file():
        return
    d = _read(p)
    d["lab_calibration_present"] = False
    d["lab_measurement_targets_from_spec"] = [
        {"name": "SCLK timing", "purpose": "Verify SCLK frequency range, "
         "setup/hold, and SDR/DDR data-valid windows."},
        {"name": "Dummy-cycle sweep", "purpose": "Find the minimum dummy "
         "cycles per read mode at each frequency without read corruption."},
        {"name": "DQS alignment (octal DDR)", "purpose": "Verify DQS-to-data "
         "edge alignment and the controller's source-synchronous capture."},
        {"name": "Multi-IO read integrity", "purpose": "Compare read data "
         "across 1-1-1 / 1-4-4 / 8-8-8 / 8D-8D-8D modes."},
        {"name": "Program/erase timing", "purpose": "Measure WIP busy time for "
         "page program, sector/block/chip erase."},
        {"name": "SFDP decode", "purpose": "Confirm SFDP tables match device "
         "behavior (read modes, dummy cycles, address bytes)."},
    ]
    d["notes"] = (
        "Characterization centers on the SCLK/data timing (SDR vs DDR, DQS "
        "alignment), the dummy-cycle latency margin at frequency, multi-IO "
        "read integrity, program/erase timing, and SFDP fidelity.")
    _write(p, d)


# ----------------------------------------------------------------------
# L14 — versioning + backward-compat traps.
# ----------------------------------------------------------------------
def _l14(gd: Path) -> None:
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["spec_version"] = (
        "JEDEC Expanded Serial Peripheral Interface (xSPI) JESD251 (2020) + "
        "JESD251-1 (2021); SFDP per JESD216; common quad/octal SPI NOR-flash "
        "command conventions.")
    f["previous_versions"] = [
        "Quad SPI (vendor, ~2010) — 1-1-4 / 1-4-4 / 4-4-4 multi-IO reads over "
        "classic SPI NOR.",
        "SFDP JESD216 (2011) — self-describing parameter tables.",
        "Octal SPI (vendor, ~2017) — x8 IO0-IO7, octal SDR/DDR.",
    ]
    f["key_changes"] = [
        {"version": "Quad/Octal SPI", "summary": "Multi-IO data lines and the "
         "instruction-address-dummy-data phase protocol added over classic "
         "single-IO SPI."},
        {"version": "SFDP (JESD216)", "summary": "Standardized self-describing "
         "capability tables (read with 0x5A)."},
        {"version": "xSPI (JESD251)", "summary": "JEDEC standardization: octal "
         "DDR 8D-8D-8D, DQS source-synchronous read, command extension byte, "
         "configuration-register interface, variable latency."},
    ]
    f["backward_compat_traps"] = [
        {"trap_name": "QSPI_is_not_plain_SPI",
         "rule": "QSPI/OSPI adds multi-IO lines, dummy cycles, and a phase "
                 "protocol; it is only single-IO SPI-compatible in 1-1-1.",
         "trap": "Treating a QSPI device as a bare full-duplex SPI shifter "
                 "ignores the address/dummy/data phases and reads garbage."},
        {"trap_name": "Dummy_cycles_are_frequency_dependent",
         "rule": "The dummy-cycle count must match the device's configured "
                 "latency for the read mode and SCLK frequency.",
         "trap": "Using too few dummy cycles at high frequency corrupts the "
                 "data phase (the most common bring-up bug)."},
        {"trap_name": "WP_HOLD_become_IO2_IO3_in_Quad",
         "rule": "In Quad mode the /WP pin is IO2 and /HOLD (or /RESET) is "
                 "IO3.",
         "trap": "Leaving /WP or /HOLD asserted as control pins breaks Quad "
                 "data transfer."},
        {"trap_name": "3_vs_4_byte_address",
         "rule": "Devices >16 MB need 4-byte addressing (0xB7) or 4-byte "
                 "opcodes.",
         "trap": "Sending a 3-byte address to a 4-byte-mode device targets the "
                 "wrong location."},
        {"trap_name": "DDR_needs_DQS_alignment",
         "rule": "Octal DDR (8D-8D-8D) requires DQS-based source-synchronous "
                 "capture at high frequency.",
         "trap": "Capturing DDR data off SCLK alone fails timing as frequency "
                 "rises."},
    ]
    f["version_naming_history_note"] = (
        "xSPI is JEDEC's standardization (JESD251) of the multi-IO 'Expanded "
        "SPI' that vendors shipped as Quad SPI and Octal SPI; SFDP is JESD216. "
        "Facts here are grounded in the public JEDEC xSPI and SFDP standards "
        "and common quad/octal SPI NOR-flash command conventions.")
    _write(p, d)


# ----------------------------------------------------------------------
# L15 — encoding/command/mode tables.
# ----------------------------------------------------------------------
def _l15(gd: Path) -> None:
    p = gd / "L15_ENCODING_TABLES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["flash_command_table"] = {
        "header_columns": ["Name", "Opcode", "Mode", "Notes"],
        "rows": [
            ["Write Enable (WREN)", "0x06", "1-0-0", "sets WEL"],
            ["Write Disable (WRDI)", "0x04", "1-0-0", "clears WEL"],
            ["Read Status Register-1", "0x05", "1-0-1", "WIP/WEL/BP"],
            ["Read Data", "0x03", "1-1-1", "low-frequency"],
            ["Fast Read", "0x0B", "1-1-1", "8 dummy cycles"],
            ["Dual Output Fast Read", "0x3B", "1-1-2", ""],
            ["Dual I/O Fast Read", "0xBB", "1-2-2", ""],
            ["Quad Output Fast Read", "0x6B", "1-1-4", ""],
            ["Quad I/O Fast Read", "0xEB", "1-4-4", "mode bits + dummy"],
            ["Page Program", "0x02", "1-1-1", "<=256 bytes"],
            ["Quad Page Program", "0x32", "1-1-4", ""],
            ["Sector Erase (4 KB)", "0x20", "1-1-0", ""],
            ["Block Erase (64 KB)", "0xD8", "1-1-0", ""],
            ["Chip Erase", "0xC7", "1-0-0", ""],
            ["Read JEDEC ID", "0x9F", "1-0-1", "mfr+device"],
            ["Read SFDP", "0x5A", "1-1-1", "JESD216, 8 dummy"],
            ["Enter 4-Byte Address", "0xB7", "1-0-0", ""],
            ["Exit 4-Byte Address", "0xE9", "1-0-0", ""],
        ],
    }
    f["protocol_mode_table"] = {
        "header_columns": ["Mode (S-A-D)", "Class", "Data lanes", "Rate"],
        "rows": [
            ["1-1-1", "Single", "1", "SDR"],
            ["1-1-2", "Dual", "2", "SDR"],
            ["1-2-2", "Dual I/O", "2", "SDR"],
            ["1-1-4", "Quad", "4", "SDR"],
            ["1-4-4", "Quad I/O", "4", "SDR"],
            ["4-4-4", "QPI", "4", "SDR"],
            ["1-1-8", "Octal", "8", "SDR"],
            ["1-8-8", "Octal I/O", "8", "SDR"],
            ["8-8-8", "Octal", "8", "SDR"],
            ["8D-8D-8D", "Octal DDR", "8", "DDR/DTR + DQS"],
        ],
    }
    f["data_line_table"] = {
        "header_columns": ["Line", "Single role", "Quad/Octal role"],
        "rows": [
            ["IO0", "MOSI", "data line 0"],
            ["IO1", "MISO", "data line 1"],
            ["IO2", "/WP", "data line 2 (Quad/Octal)"],
            ["IO3", "/HOLD or /RESET", "data line 3 (Quad/Octal)"],
            ["IO4-IO7", "-", "data lines 4-7 (Octal 'x8')"],
            ["DQS", "-", "data strobe (octal DDR)"],
        ],
    }
    f["phase_table"] = {
        "header_columns": ["Phase", "Width", "Lanes", "Purpose"],
        "rows": [
            ["instruction", "8b (16b xSPI octal)", "1/4/8", "opcode"],
            ["address", "24b / 32b", "1/2/4/8", "memory address"],
            ["mode bits", "device-specific", "addr lanes", "continuous/XIP"],
            ["dummy cycles", "programmable", "n/a", "read latency"],
            ["data", "1..N bytes", "1/2/4/8", "payload"],
        ],
    }
    f["tables"] = [
        "Flash command table",
        "Protocol-mode (S-A-D lane) table",
        "Data-line role table (single vs Quad/Octal)",
        "Command-phase table",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L16 — compliance properties / distinguishers.
# ----------------------------------------------------------------------
def _l16(gd: Path) -> None:
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["must_have_properties"] = [
        "Controller-driven SCLK + CS#, shared with classic SPI; single-IO "
        "(1-1-1) Mode-0/Mode-3 compatibility.",
        "Multiple bidirectional data lines: Quad (IO0-IO3) and/or Octal "
        "(IO0-IO7).",
        "Instruction -> address -> [mode] -> dummy-cycle -> data phase "
        "protocol.",
        "Programmable dummy cycles matched to read mode and frequency.",
        "A standard JEDEC flash command set (WREN/RDSR/Fast Read/Quad I/O/"
        "Page Program/Erase/JEDEC ID).",
        "Where claimed: SFDP (JESD216) self-description (read with 0x5A).",
        "Where claimed: SDR and DDR (DTR); octal DDR with DQS.",
        "3-byte and/or 4-byte addressing.",
        "WIP/WEL program-erase handshake.",
    ]
    f["must_not_have_properties"] = [
        "A bare full-duplex shift register with no command/address/dummy "
        "phases (that is plain single-IO SPI, not QSPI/OSPI).",
        "Open-drain wired-AND signaling (that is I2C/SMBus; QSPI/OSPI is "
        "push-pull single-ended).",
        "A wrong/zero dummy-cycle count for a high-frequency multi-IO read.",
        "Differential mainband signaling (QSPI/OSPI is single-ended).",
        "A device address byte on a shared bus (QSPI/OSPI is point-to-point "
        "per CS#, not address-multiplexed like I2C/SMBus).",
    ]
    f["compliance_failure_modes"] = [
        {"mode": "Dummy-cycle mismatch", "trigger": "Configured dummy cycles "
         "do not match the device latency at frequency -> corrupt read."},
        {"mode": "Mode/lane mismatch", "trigger": "Address/data sent on the "
         "wrong number of lanes for the opcode."},
        {"mode": "Missing WEL", "trigger": "Program/erase without a prior "
         "Write Enable -> operation ignored."},
        {"mode": "Address-byte mismatch", "trigger": "3-byte address sent to a "
         "4-byte-mode device (or vice-versa)."},
        {"mode": "DDR capture failure", "trigger": "Octal DDR captured without "
         "DQS at high frequency -> timing failure."},
    ]
    f["qspi_ospi_distinguishers"] = (
        "QSPI/OSPI (xSPI/JESD251) is identified by ALL of: shared SCLK + CS# "
        "with classic SPI; MULTIPLE bidirectional data lines (IO0..IO3 Quad / "
        "IO0..IO7 Octal / DQ0..DQ7); the instruction-address-dummy-data phase "
        "protocol with programmable dummy cycles; the protocol-mode notation "
        "(1-1-4 / 1-4-4 / 4-4-4 / 8-8-8 / 8D-8D-8D); a standard JEDEC flash "
        "command set (0x06 / 0x0B / 0xEB / 0x6B / 0x32 / 0x9F / 0x5A); SFDP "
        "self-description; SDR and DDR (DTR) with an optional DQS; and 3/4-byte "
        "addressing with continuous-read / XIP. This is DISTINCT from plain "
        "single-IO SPI (which has only SCLK/MOSI/MISO/SS#, CPOL/CPHA and a "
        "full-duplex shift register, with NONE of the multi-IO lines, dummy "
        "cycles, flash command set, SFDP, protocol-mode notation, or xSPI "
        "register framework).")
    _write(p, d)


# ----------------------------------------------------------------------
# L17 — channel / signal catalog + dependency graph (force-overwrite).
# ----------------------------------------------------------------------
def _l17(gd: Path) -> None:
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["channels"] = [
        {"name": "SCLK", "direction": "controller -> device",
         "purpose": "Serial clock (SDR one edge, DDR both edges).",
         "active_levels": "push-pull", "idle_level": "per CPOL"},
        {"name": "CS#", "direction": "controller -> device",
         "purpose": "Active-low chip select; frames each command.",
         "active_levels": "low = selected", "idle_level": "high"},
        {"name": "IO0..IO3 (Quad) / IO0..IO7 (Octal)",
         "direction": "bidirectional (tri-stated)",
         "purpose": "Multi-IO data (instruction/address/data per phase). "
         "IO0=MOSI, IO1=MISO single; /WP->IO2, /HOLD->IO3 in Quad.",
         "active_levels": "push-pull when driven", "idle_level": "tri-state"},
        {"name": "DQS", "direction": "device -> controller (octal DDR)",
         "purpose": "Source-synchronous read data strobe.",
         "active_levels": "edge-aligned to data", "idle_level": "tri-state"},
        {"name": "RESET#", "direction": "controller -> device",
         "purpose": "Hardware reset (xSPI).",
         "active_levels": "low = reset", "idle_level": "high"},
    ]
    f["global_signals"] = [
        {"name": "SCLK", "purpose": "Controller-driven serial clock."},
        {"name": "CS#", "purpose": "Per-device chip select."},
        {"name": "DQS", "purpose": "Octal-DDR read strobe."},
    ]
    f["packet_types_summary"] = [
        {"class": "protocol mode (S-A-D)", "members": list(_PROTOCOL_MODES),
         "count": len(_PROTOCOL_MODES)},
        {"class": "flash command", "members": [c["name"] for c in
                                                _FLASH_COMMANDS],
         "count": len(_FLASH_COMMANDS)},
    ]
    cc = _ensure_dict(f, "channel_counts")
    cc.update({
        "clock_lines": 1,
        "chip_select_lines": 1,
        "data_lines_quad": 4,
        "data_lines_octal": 8,
        "data_strobe_lines": 1,
        "reset_lines": 1,
        "instruction_bits": 8,
        "address_bits_3byte": 24,
        "address_bits_4byte": 32,
        "data_byte_bits": 8,
        "protocol_mode_count": len(_PROTOCOL_MODES),
        "flash_command_count": len(_FLASH_COMMANDS),
    })
    f["handshake_pairs"] = [
        {"name": "CS# / command frame", "from": "controller", "to": "device",
         "rule": "CS# low begins, CS# high ends each command."},
        {"name": "instruction / phase select", "from": "controller",
         "to": "device", "rule": "Opcode selects the address/mode/dummy/data "
         "phase sequence and lane counts."},
        {"name": "dummy cycles / read latency", "from": "controller",
         "to": "device", "rule": "Dummy cycles must equal the device read "
         "latency for the mode/frequency."},
        {"name": "DQS / read data", "from": "device", "to": "controller",
         "rule": "Octal DDR: DQS edge-aligned to read data on IO0..IO7."},
        {"name": "WEL/WIP / program-erase", "from": "controller",
         "to": "device", "rule": "WREN sets WEL; controller polls WIP via "
         "0x05 for completion."},
    ]
    f["dependency_graph"] = {
        "common_rule": "Every command is framed by CS#; phases run in order "
        "instruction -> address -> [mode] -> dummy -> data, each on 1/2/4/8 "
        "lanes, MSB-first. DQS (octal DDR) accompanies read data. The opcode "
        "determines which phases are present.",
        "data_dependency": "A correct read requires (1) the right protocol "
        "mode / lane count for the opcode, (2) the right address-byte count "
        "(3 vs 4), and (3) the right dummy-cycle count for the frequency. A "
        "program/erase requires WEL set (0x06) first and WIP polling for "
        "completion.",
    }
    f["ordering_rules"] = {
        "bit_order_on_wire": "MSB-first on each data line.",
        "phase_order": "instruction, address, mode bits, dummy cycles, data.",
        "transaction_atomicity": "One command per CS# assertion; "
        "point-to-point per chip-select.",
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L18 — interconnect topology.
# ----------------------------------------------------------------------
def _l18(gd: Path) -> None:
    p = gd / "L18_INTERCONNECT_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["topology_type"] = (
        "Point-to-point per chip-select: one xSPI/QSPI/OSPI controller "
        "(master) drives SCLK + CS# and the bidirectional data lines IO0..IO7 "
        "to one memory device per CS#. Unlike I2C/SMBus this is NOT a shared "
        "multi-drop addressed bus; each device has its own chip-select.")
    f["supported_topologies"] = [
        {"name": "Single controller, single device", "description": "One "
         "CS#, one memory device."},
        {"name": "Single controller, multiple devices", "description": "One "
         "controller with multiple CS# lines, one per device."},
        {"name": "Quad / Octal width", "description": "4 or 8 shared "
         "bidirectional data lines per device."},
    ]
    f["master_slave_role_summary"] = [
        {"role": "Controller (master)", "description": "Drives SCLK, CS#, the "
         "instruction/address/dummy phases, and the data lines when writing."},
        {"role": "Memory device (slave)", "description": "Responds to its "
         "CS#; drives the data lines (and DQS) during reads, latches data "
         "during writes."},
    ]
    f["interconnect_role"] = (
        "QSPI/OSPI is a controller-to-memory expansion of SPI. The controller "
        "selects a device with CS#, issues the phase protocol, and reads or "
        "writes the device's linear flash address space; it may expose a "
        "memory-mapped XIP window to the SoC.")
    f["ordering_guarantees"] = {
        "single_command": "One command per CS# assertion.",
        "point_to_point": "Each device addressed by a dedicated chip-select, "
        "not by an on-bus device address.",
    }
    f["memory_vs_peripheral_regions"] = (
        "QSPI/OSPI accesses a linear byte-addressed flash memory space (3- or "
        "4-byte address). The opcode space (0x00..0xFF) selects read/program/"
        "erase/status/config functions; xSPI adds a configuration-register "
        "interface.")
    _write(p, d)


# ----------------------------------------------------------------------
# L19 — channel/electrical constraints.
# ----------------------------------------------------------------------
def _l19(gd: Path) -> None:
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["constraints_present"] = True
    f["electrical_channel_constraints"] = {
        "signaling": "single-ended CMOS/LVCMOS push-pull; bidirectional "
                     "tri-stated data lines (NOT open-drain)",
        "clock_lines": 1, "chip_select_lines": 1,
        "data_lines": {"quad": 4, "octal": 8},
        "data_strobe": "DQS (octal DDR, source-synchronous read)",
        "spi_modes": ["Mode 0 (CPOL=0,CPHA=0)", "Mode 3 (CPOL=1,CPHA=1)"],
        "max_clock_MHz": {"typical_sdr": 133, "fast_sdr": 200},
        "data_rate": {"sdr": True, "ddr_dtr": True},
        "address_byte_options": [3, 4],
        "dummy_cycles": "programmable; matched to mode/frequency; SFDP-"
                        "discoverable",
        "bit_order": "MSB-first per data line",
    }
    f["notes"] = (
        "The interoperability-critical constraints are the dummy-cycle count "
        "vs frequency, the protocol mode / lane count per opcode, the address-"
        "byte count, and (octal DDR) DQS alignment. Board-level signal "
        "integrity on the multi-IO lines at high SCLK frequency is the "
        "implementer's concern.")
    _write(p, d)


# ----------------------------------------------------------------------
# L20 — DFT / in-band test facilities.
# ----------------------------------------------------------------------
def _l20(gd: Path) -> None:
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["dft_present"] = "partial"
    f["in_band_test_facilities"] = [
        {"name": "Status Register", "purpose": "WIP/WEL/BP observability."},
        {"name": "Read JEDEC ID (0x9F)", "purpose": "Device identification."},
        {"name": "SFDP (0x5A)", "purpose": "Capability self-description."},
        {"name": "Read-back verify", "purpose": "Read after program/erase to "
         "verify memory contents."},
        {"name": "xSPI configuration registers", "purpose": "Read back mode / "
         "dummy latency / DQS / address-byte settings."},
    ]
    f["internal_diagnostics_observability"] = [
        "WIP/WEL and block-protection status.",
        "Manufacturer/device ID and SFDP parameter tables.",
        "Configured protocol mode, dummy-cycle latency, and address-byte "
        "count.",
        "Device-specific ECC status on xSPI NOR (where present).",
    ]
    f["notes"] = (
        "QSPI/OSPI DFT is in-band over the same lines (Status, JEDEC ID, SFDP, "
        "read-back, config registers). There is no protocol-defined scan/JTAG "
        "layer; chip-level scan/BIST is the device implementer's concern.")
    _write(p, d)


# ----------------------------------------------------------------------
# L21 — power intent.
# ----------------------------------------------------------------------
def _l21(gd: Path) -> None:
    p = gd / "L21_POWER_INTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["power_intent_present"] = True
    f["managed_power_states"] = [
        {"state": "ACTIVE", "description": "Executing a read/program/erase "
         "command."},
        {"state": "STANDBY", "description": "CS# high, no command in "
         "progress; low quiescent current."},
        {"state": "DEEP_POWER_DOWN", "description": "Entered via 0xB9 (Deep "
         "Power-Down); minimal current, released by 0xAB."},
    ]
    f["output_enable_logic"] = (
        "The data lines IO0..IO7 are driven only during the appropriate phase "
        "(controller during instruction/address/write-data, device during "
        "read-data); otherwise tri-stated. DQS is driven by the device during "
        "octal-DDR reads.")
    f["bus_power"] = (
        "Single-ended push-pull I/O; no bus pull-ups required (unlike "
        "open-drain I2C/SMBus). Program/erase draws the most current; standby "
        "and deep-power-down minimize it.")
    f["notes"] = (
        "Power management is the device's standby / deep-power-down modes and "
        "the tri-stating of the multi-IO lines between phases; the protocol "
        "itself is not a power-control protocol (unlike PMBus).")
    _write(p, d)


# ----------------------------------------------------------------------
# L22 — verification plan categories.
# ----------------------------------------------------------------------
def _l22(gd: Path) -> None:
    p = gd / "L22_VERIFICATION_PLAN.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["verification_plan_present"] = "implicit"
    f["verification_categories_derived_from_spec"] = [
        "Single-IO (1-1-1) SPI Mode-0/Mode-3 compatibility.",
        "Every multi-IO mode: 1-1-2/1-2-2/1-1-4/1-4-4/4-4-4/1-1-8/1-8-8/"
        "8-8-8/8D-8D-8D lane correctness.",
        "Dummy-cycle sweep across read modes and frequencies.",
        "Flash command coverage: WREN/WRDI/RDSR/Fast Read/Quad I/O/Quad "
        "Output/Page Program/Quad PP/Sector-Block-Chip Erase/JEDEC ID.",
        "SFDP read and decode (signature, headers, BFPT).",
        "3-byte vs 4-byte addressing; Enter/Exit 4-byte and 4-byte opcodes.",
        "SDR vs DDR capture; octal-DDR DQS source-synchronous alignment.",
        "Program/erase: WEL gating, WIP polling, page/sector/block boundaries.",
        "Continuous-read / XIP instruction-less reads.",
        "xSPI configuration registers and command-extension byte.",
        "Reset behavior and power-on default mode.",
    ]
    f["notes"] = (
        "QSPI/OSPI ships no formal testbench, but the JEDEC xSPI / SFDP "
        "standards and the flash command conventions imply a verification "
        "plan spanning the phase protocol, the multi-IO modes, dummy cycles, "
        "the flash command set, SFDP, SDR/DDR, addressing, and program/erase.")
    _write(p, d)


# ----------------------------------------------------------------------
# L23 — security / robustness.
# ----------------------------------------------------------------------
def _l23(gd: Path) -> None:
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["security_requirements_present"] = False
    f["anti_corruption_features"] = [
        "WIP/WEL handshake prevents partial/unauthorized program-erase.",
        "Block-protection (BP) bits guard regions from accidental erase.",
        "Status-register write-protect (SRWD/SRP) locks configuration.",
        "SFDP self-description prevents wrong-dummy-cycle misconfiguration.",
        "Device-specific internal ECC on some xSPI NOR detects bit errors.",
    ]
    f["anti_tampering_features"] = [
        "Block protection and status-register write-protect (soft guards, not "
        "cryptographic).",
        "Some devices add a vendor security/OTP region and lockable blocks.",
    ]
    f["confidentiality_features"] = []
    f["authentication_features"] = []
    f["future_security_pointers"] = [
        "The QSPI/OSPI bus carries plaintext on a board-local point-to-point "
        "link; physical access is the trust boundary.",
        "Some xSPI/secure-flash devices add per-region locking and "
        "authenticated commands, but that is a device feature outside the base "
        "bus protocol.",
    ]
    f["notes"] = (
        "QSPI/OSPI built-in protections are anti-corruption and write-protect "
        "guards only (WIP/WEL, block protection, status-register protect, "
        "SFDP, optional ECC). There is no transaction CRC (unlike SMBus PEC) "
        "and no in-protocol encryption or device authentication in the base "
        "xSPI bus spec; the link is trusted at the board level.")
    _write(p, d)
