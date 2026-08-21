"""NFC / ISO 14443 contactless-protocol synth helper.

v0.1.84+ — ic_class-gated overlay for `bus_interconnect_protocol` /
`serial_peripheral_protocol` specs that exhibit the NFC / ISO 14443
structural signature:
  (NFC + ISO 14443 + UID) OR
  (MIFARE + 13.56 MHz + SAK) OR
  (PCD + PICC + ATQA).

Applies the NXP AN10833 'MIFARE type identification procedure'
(Rev. 3.8, 10 January 2023) canonical content — plus the ISO/IEC
14443-2/-3/-4 layer model it sits on — to L1..L23.

Doctrine: structural-keyword detection IS general within a protocol
class (mirrors AMBA-AXI / SPI / I2C / UART / CAN / USB / I2S / SD-MMC
synth approach). Any contactless smartcard / proximity tag whose
spec discusses ISO 14443 anti-collision + UID + SAK (and especially
any NXP MIFARE family member — Classic / Plus / DESFire / Ultralight /
NTAG) exhibits the same air-interface signature: 13.56 MHz carrier +
847.5 kHz subcarrier + 100% ASK Modified-Miller (Type A) or 10% ASK
NRZ-L (Type B) + REQA/WUPA → ATQA → SELECT cascade → UID + SAK
(+ optional RATS → ATS for Layer 4 PICCs).

Public entry: `apply_nfc_synth(generated_docs_dir, is_nfc, nfc_ic_name)`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import l_doc_generator_stamp as _stamp
import _pack_top_module as _ptm  # L9.top_module: one decision, one provenance stamp


# ---------------------------------------------------------------------------
# I/O helpers (mirror sdmmc/spi/i2c synth conventions)
# ---------------------------------------------------------------------------

def _empty(v) -> bool:
    return v in (None, {}, []) or (isinstance(v, str) and not v.strip())


def _read(p: Path) -> dict:
    return json.loads(p.read_text())


def _write(p: Path, d: dict) -> None:
    # THE L-document write chokepoint: stamps the producing release onto
    # the document, then serialises it byte-identically to before.
    _stamp.dump(p, d)


def _ensure_dict(d: dict, key: str) -> dict:
    """setdefault-None bug fix: if the value is None / empty, replace with {}."""
    if d.get(key) in (None, "", []):
        d[key] = {}
    if not isinstance(d.get(key), dict):
        d[key] = {}
    return d[key]


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------

def apply_nfc_synth(generated_docs_dir: Path, is_nfc: bool,
                    nfc_ic_name: Optional[str]) -> None:
    """Apply NFC / ISO 14443 / AN10833 overlay when the structural signature matched."""
    if not is_nfc:
        return
    gd = Path(generated_docs_dir)

    # ---- Force ic_name across all 24 L docs (parity target).
    if nfc_ic_name is not None:
        for n in [
            "L1_DATASHEET.json", "L2_FRS.json", "L3_CMD_PROTOCOL.json",
            "L4_REGMAP.json", "L5_ADI_SPEC.json", "L6_CONTROL_LOGIC.json",
            "L7_TEST_DEBUG.json", "L8_RTL_CONSTANTS.json",
            "L8_TIMING_WAVEFORM.json", "L9_INTEGRATION_SPEC.json",
            "L10_TEST_CASES.json", "L11_OTP_CONTENT.json",
            "L12_BEHAVIORAL_SEQUENCES.json", "L13_LAB_CALIBRATION.json",
            "L14_PROTOCOL_VERSIONING.json", "L15_ENCODING_TABLES.json",
            "L16_COMPLIANCE_PROPERTIES.json",
            "L17_CHANNEL_SIGNAL_CATALOG.json",
            "L18_INTERCONNECT_TOPOLOGY.json",
            "L19_CONSTRAINTS_PDK.json", "L20_DFT_SCAN_TOPOLOGY.json",
            "L21_POWER_INTENT.json", "L22_VERIFICATION_PLAN.json",
            "L23_SECURITY_REQUIREMENTS.json",
        ]:
            q = gd / n
            if q.is_file():
                d = _read(q)
                d["ic_name"] = nfc_ic_name
                _write(q, d)

    _l1(gd)
    _l2(gd)
    _l3(gd)
    _l4(gd)
    _l5(gd)
    _l6(gd)
    _l7(gd)
    _l8_const(gd)
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


# ---------------------------------------------------------------------------
# L1 datasheet metadata
# ---------------------------------------------------------------------------

def _l1(gd: Path) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("document_title", "MIFARE type identification procedure")
    d.setdefault("document_number", "AN10833")
    d.setdefault("version", "Rev. 3.8")
    d.setdefault("revised_date", "10 January 2023")
    d.setdefault("manufacturer", "NXP Semiconductors (NXP B.V.)")
    d.setdefault("publisher", "NXP B.V., Eindhoven, The Netherlands")
    d.setdefault("copyright", "Copyright 2004-2023 NXP B.V. All rights reserved.")
    d.setdefault("external_pins_picc", ["LA (Antenna Coil terminal A)", "LB (Antenna Coil terminal B)"])
    d.setdefault("external_pin_count_picc", 2)
    d.setdefault("external_pins_pcd_reader_typical_chip", [
        "TX1 (Antenna driver A)",
        "TX2 (Antenna driver B)",
        "RX (Receiver input)",
        "VMID (Internal regulator decoupling)",
        "AVDD / DVDD / PVDD (Analog / Digital / Pad supplies)",
        "AVSS / DVSS / PVSS (Grounds)",
        "Host bus: SPI / I2C / UART / parallel (varies)",
        "IRQ (Interrupt to host)",
        "NRSTPD (Reset / Power-down)",
        "OSCIN / OSCOUT (27.12 MHz crystal — 2× carrier)",
    ])
    d.setdefault("key_features", [
        "Air-interface: 13.56 MHz RF carrier; PCD (reader) ↔ PICC (card) at proximity range (≤ 10 cm typical, 0-100 mm operating volume).",
        "Two coding/modulation families: Type A (Modified Miller PCD→PICC at 100% ASK, Manchester PICC→PCD via load modulation on 847.5 kHz subcarrier) and Type B (NRZ PCD→PICC at 10% ASK, BPSK PICC→PCD on 847.5 kHz subcarrier).",
        "Bit rates: 106 / 212 / 424 / 848 kbps (fc/128, fc/64, fc/32, fc/16); PICC initially answers at 106 kbps then negotiates higher via PPS.",
        "ISO 14443-3 Type A anti-collision: REQA (0x26) / WUPA (0x52) → ATQA (2 bytes, indicates UID size + bit-frame anti-collision support) → SELECT CL1/CL2/CL3 (3-byte command + 5-byte UID-CLn + CRC_A) → UID 4 / 7 / 10 bytes + 1-byte SAK per Cascade Level.",
        "ISO 14443-3 Type B anti-collision: REQB / WUPB (0x05 + AFI + PARAM) → ATQB (12 bytes: PUPI + Application + Protocol Info) → ATTRIB / Slot-Marker for selection.",
        "UID byte 0 ('Manufacturer Byte', UID0): 0x04 = NXP, 0x05 = Infineon, 0x07 = STMicroelectronics, others assigned by ISO/IEC 7816-6.",
        "SAK (Select Acknowledge) classification: bit 6 = 1 indicates ISO/IEC 14443-4 compliance (T=CL supported); bit 3 = 1 indicates UID not complete (Cascade Tag follows).",
        "Common SAK values: 0x00 = MIFARE Ultralight / Ultralight C / Ultralight EV1 / NTAG; 0x08 = MIFARE Classic 1K (or MIFARE Plus SL1 2K/SE); 0x18 = MIFARE Classic 4K (or MIFARE Plus SL1 4K); 0x20 = ISO/IEC 14443-4 compliant (MIFARE DESFire / MIFARE Plus SL3 / JCOP); 0x10/0x11 = MIFARE Plus SL2.",
        "ISO 14443-4 (T=CL Block Transmission Protocol): RATS (0xE0) → ATS → I-Block / R-Block / S-Block with optional NAD, CID, FSDI/FSD; FSDI/FSCI encode frame size 16..256 B.",
        "Frame integrity: 16-bit CRC_A (poly 0x8408, init 0x6363, reflected, no final XOR) on Type A; CRC_B (CRC-16/X-25, poly 0x1021 reflected, init 0xFFFF, XOR 0xFFFF) on Type B.",
        "Bit-level framing on Type A: Standard frame = SOF + LSB-first byte stream with one odd-parity bit after every byte + EOF; short frame = 7 bits no parity no CRC (REQA/WUPA/HLTA).",
        "GetVersion command (across MIFARE Ultralight EV1, MIFARE Plus EV1/EV2, MIFARE DESFire EV2/EV3 and DESFire Light) returns a 7-byte version block whose byte 2 (HW/Product Type) deterministically identifies the family — recommended preferred ID path over ATQA/SAK.",
        "MIFARE Classic family — proprietary NXP CRYPTO1 stream cipher + Authentication via Key A / Key B per sector; 1K = 16 sectors × 4 blocks × 16 B; 4K = 32 × 4 + 8 × 16; native (non-T=CL) protocol above Layer 3.",
        "MIFARE Ultralight family — no cryptographic authentication on UL; 3DES on Ultralight C; password (32-bit) on Ultralight EV1 / NTAG21x; 16-byte pages.",
        "MIFARE DESFire family — 3DES / 3K-3DES / AES-128 authentication; ISO/IEC 7816-style file system; T=CL above; supports up to 28 applications × 32 files (DESFire EV1+).",
        "MIFARE Plus family — bridges MIFARE Classic and DESFire; AES-128 in SL3; backwards-compatible Crypto1 in SL1.",
        "Three Cascade Levels (CL1 / CL2 / CL3) accommodate 4-, 7-, and 10-byte UIDs; Cascade Tag (CT = 0x88) marks UID is not yet complete.",
    ])
    d.setdefault("picc_family_classification", [
        {"family": "MIFARE Classic 1K",  "atqa": "0x00 0x04", "sak_after_final_cl": "0x08", "uid_length_bytes": "4 or 7", "iso14443_4_compliant": False, "protocol_above_l3": "MIFARE proprietary (Crypto1)"},
        {"family": "MIFARE Classic 4K",  "atqa": "0x00 0x02", "sak_after_final_cl": "0x18", "uid_length_bytes": "4 or 7", "iso14443_4_compliant": False, "protocol_above_l3": "MIFARE proprietary (Crypto1)"},
        {"family": "MIFARE Ultralight",  "atqa": "0x00 0x44", "sak_after_final_cl": "0x00", "uid_length_bytes": "7",     "iso14443_4_compliant": False, "protocol_above_l3": "Native UL command set"},
        {"family": "MIFARE Ultralight C","atqa": "0x00 0x44", "sak_after_final_cl": "0x00", "uid_length_bytes": "7",     "iso14443_4_compliant": False, "protocol_above_l3": "Native UL + 3DES auth"},
        {"family": "MIFARE Ultralight EV1","atqa": "0x00 0x44", "sak_after_final_cl": "0x00", "uid_length_bytes": "7",   "iso14443_4_compliant": False, "protocol_above_l3": "Native UL + GetVersion + 32-bit password"},
        {"family": "MIFARE DESFire (EV1/EV2/EV3)", "atqa": "0x03 0x44", "sak_after_final_cl": "0x20", "uid_length_bytes": "7", "iso14443_4_compliant": True, "protocol_above_l3": "T=CL + DESFire AES/3K-3DES file system"},
        {"family": "MIFARE DESFire Light","atqa": "0x03 0x44", "sak_after_final_cl": "0x20", "uid_length_bytes": "7",    "iso14443_4_compliant": True, "protocol_above_l3": "T=CL + DESFire Light AES file system"},
        {"family": "MIFARE Plus SL1 2K", "atqa": "0x00 0x04", "sak_after_final_cl": "0x08", "uid_length_bytes": "4 or 7", "iso14443_4_compliant": False, "protocol_above_l3": "Classic-compatible (Crypto1)"},
        {"family": "MIFARE Plus SL1 4K", "atqa": "0x00 0x02", "sak_after_final_cl": "0x18", "uid_length_bytes": "4 or 7", "iso14443_4_compliant": False, "protocol_above_l3": "Classic-compatible (Crypto1)"},
        {"family": "MIFARE Plus SL2 2K", "atqa": "0x00 0x04", "sak_after_final_cl": "0x10", "uid_length_bytes": "4 or 7", "iso14443_4_compliant": True,  "protocol_above_l3": "T=CL + AES sector auth (Crypto1 disabled)"},
        {"family": "MIFARE Plus SL2 4K", "atqa": "0x00 0x02", "sak_after_final_cl": "0x11", "uid_length_bytes": "4 or 7", "iso14443_4_compliant": True,  "protocol_above_l3": "T=CL + AES sector auth"},
        {"family": "MIFARE Plus SL3",    "atqa": "0x00 0x04 / 0x00 0x42", "sak_after_final_cl": "0x20", "uid_length_bytes": "4 or 7", "iso14443_4_compliant": True, "protocol_above_l3": "T=CL + AES + Virtual Card"},
        {"family": "NTAG (NTAG21x / NTAG I2C)", "atqa": "0x00 0x44", "sak_after_final_cl": "0x00", "uid_length_bytes": "7", "iso14443_4_compliant": False, "protocol_above_l3": "NFC Forum Type 2 Tag + GetVersion"},
        {"family": "JCOP / generic Type-4 tag",  "atqa": "0x00 0x04 (varies)", "sak_after_final_cl": "0x20", "uid_length_bytes": "4 / 7 / 10", "iso14443_4_compliant": True, "protocol_above_l3": "T=CL + ISO 7816-4 APDU"},
    ])
    d.setdefault("revision_history", [
        {"version": "3.8", "date": "20230110", "description": "Correction of Figure 1 to the latest version."},
        {"version": "3.7", "date": "20210810", "description": "Addition of newest generation (MIFARE DESFire EV3 / MIFARE DESFire Light); general restructuring with focus on the GetVersion command."},
        {"version": "3.6", "date": "20160711", "description": "Update for MIFARE Plus EV1."},
        {"version": "3.5", "date": "20140327", "description": "Update for multi-MIFARE implementation and implementation in UICC."},
        {"version": "3.4", "date": "20121029", "description": "Update for MIFARE implementation in a device."},
        {"version": "3.3", "date": "20110928", "description": "Update for TNP3xxx."},
        {"version": "3.2", "date": "20110829", "description": "Update for the new MIFARE Classic with 7-byte UID option."},
        {"version": "3.1", "date": "20090707", "description": "Correction of Table 12."},
        {"version": "3",   "date": "20090518", "description": "Third release; supersedes AN MIFARE Interface Platform, Type Identification Procedure, Rev. 1.3, Nov. 2004."},
    ])
    d.setdefault("topology_summary",
        "Single PCD (reader) generates the 13.56 MHz RF field; one or more PICCs "
        "(cards/tags) within the operating volume are powered by the carrier. "
        "Anti-collision (Layer 3) selects a single PICC by UID; ISO 14443-4 (Layer "
        "4, T=CL) then carries application-level commands between PCD and the "
        "selected PICC.")
    d.setdefault("abstract",
        "This document describes how to differentiate between the members of the "
        "MIFARE card IC family. ISO/IEC 14443-3 describes the initialization and "
        "anti-collision procedure, and ISO/IEC 14443-4 describes the protocol "
        "activation procedure. This document shows how to use these procedures to "
        "deliver the chip type information for all MIFARE ICs and implementations "
        "/ emulations. AN10833 covers the protocol stack — 13.56 MHz RF carrier, "
        "ISO 14443-2 modulation, ISO 14443-3 anti-collision (REQA/WUPA → ATQA → "
        "bit-frame anti-collision → SELECT cascade CL1/CL2/CL3 + BCC → UID 4/7/10 "
        "bytes + SAK), and ISO 14443-4 T=CL protocol activation (RATS → ATS → "
        "I/R/S-blocks).")
    d.setdefault("overview",
        "AN10833 documents the deterministic identification procedure for the NXP "
        "MIFARE family by walking the ISO/IEC 14443 contactless stack — Layer 2 "
        "modulation/coding at 13.56 MHz, Layer 3 anti-collision (REQA → ATQA → "
        "SELECT cascade → UID + SAK), and Layer 4 T=CL protocol activation (RATS "
        "→ ATS). After Layer 3, the SAK byte and ATQA together classify the PICC "
        "into one of the MIFARE families (Classic / Plus / DESFire / Ultralight / "
        "NTAG). For newer generations the GetVersion command is the recommended "
        "exact-identity path.")
    d.setdefault("keywords", [
        "NFC", "ISO/IEC 14443", "ISO 14443-2", "ISO 14443-3", "ISO 14443-4",
        "Type A", "Type B", "13.56 MHz", "MIFARE", "MIFARE Classic",
        "MIFARE Plus", "MIFARE DESFire", "MIFARE Ultralight", "NTAG",
        "PCD", "PICC", "REQA", "WUPA", "ATQA", "SELECT", "UID", "SAK",
        "BCC", "RATS", "ATS", "T=CL", "CRC_A", "CRC_B", "GetVersion",
    ])
    d.setdefault("use_cases", [
        "Public-transport ticketing (MIFARE Classic 1K, MIFARE Plus, MIFARE DESFire)",
        "Building access control (MIFARE Classic / Plus / DESFire)",
        "Payment / contactless cards (MIFARE DESFire EV2/EV3 + EMVCo)",
        "Loyalty cards (MIFARE Ultralight C, NTAG21x)",
        "Smart posters / NFC Forum Type 2 tags (NTAG21x, NTAG I2C)",
        "Product authentication / brand protection (NTAG I2C, MIFARE DESFire)",
        "ID badges / e-passports (Type B + ISO 14443-4 above)",
        "Vending machines, hotel room keys, ski-lift gates",
    ])
    _write(p, d)


# ---------------------------------------------------------------------------
# L2 FRS
# ---------------------------------------------------------------------------

def _l2(gd: Path) -> None:
    p = gd / "L2_FRS.json"
    if not p.is_file():
        return
    d = _read(p)
    po = _ensure_dict(d, "protocol_overview")
    po.setdefault("type",
        "Contactless inductively-coupled half-duplex command-response protocol "
        "over a 13.56 MHz RF carrier. PCD (reader) is the master and always "
        "initiates a transaction; PICC (card) is the slave and only transmits "
        "when addressed. Three protocol layers: Layer 2 (ISO 14443-2), Layer 3 "
        "(ISO 14443-3), Layer 4 (ISO 14443-4 T=CL).")
    po.setdefault("duplex", "half-duplex (PCD modulates carrier amplitude; PICC modulates load on the carrier — never simultaneous)")
    po.setdefault("synchronous", True)
    po.setdefault("wire_names_air_interface", ["13.56 MHz RF carrier (single-ended air-coupled)"])
    po.setdefault("wire_count_air_interface", 0)
    po.setdefault("physical_carrier_MHz", 13.56)
    po.setdefault("subcarrier_kHz", 847.5)
    po.setdefault("supports_type_a", True)
    po.setdefault("supports_type_b", True)
    po.setdefault("supports_iso14443_4_t_cl", True)
    po.setdefault("supports_anticollision_for_multiple_piccs_in_field", True)
    po.setdefault("pcd_role",
        "Generates 13.56 MHz RF field; powers the PICC by inductive coupling; "
        "initiates every transaction; encodes PCD→PICC bits as Modified Miller "
        "(Type A, 100% ASK) or NRZ (Type B, 10% ASK).")
    po.setdefault("picc_role",
        "Field-powered; responds only when polled; encodes PICC→PCD bits as "
        "Manchester (Type A) or BPSK (Type B) load modulation on the 847.5 kHz "
        "subcarrier.")
    fr = [
        {"id": "FR-L2-CARRIER-01",   "text": "The air interface shall use a single 13.56 MHz RF carrier per ISO/IEC 14443-2. Operating range shall be 0-100 mm from the PCD antenna with proximity (≤ 10 cm) as the typical functional envelope."},
        {"id": "FR-L2-MOD-A-02",     "text": "Type A PCD→PICC shall use 100% ASK Modified Miller coding at one of 106 / 212 / 424 / 848 kbps."},
        {"id": "FR-L2-LOAD-A-03",    "text": "Type A PICC→PCD shall use Manchester coding via load modulation of an 847.5 kHz subcarrier (fc/16) on the 13.56 MHz carrier."},
        {"id": "FR-L2-MOD-B-04",     "text": "Type B PCD→PICC shall use 10% ASK NRZ-L coding at 106 / 212 / 424 / 848 kbps. PICC→PCD shall use BPSK of the 847.5 kHz subcarrier."},
        {"id": "FR-L3-REQA-05",      "text": "A PCD shall initiate Layer-3 polling using REQA (0x26, 7-bit short frame) or WUPA (0x52, 7-bit short frame)."},
        {"id": "FR-L3-ATQA-06",      "text": "Every Type A PICC shall reply to REQA / WUPA with a 16-bit ATQA encoding bit-frame anti-collision support bitmap and UID size."},
        {"id": "FR-L3-AC-07",        "text": "PCDs shall perform bit-frame anti-collision per ISO/IEC 14443-3 §6.4.3 using SELECT cascade levels CL1 (0x93), CL2 (0x95), CL3 (0x97)."},
        {"id": "FR-L3-BCC-08",       "text": "Each Cascade-Level block shall be protected by a BCC (Block Check Character) = UID-CLn[0] XOR UID-CLn[1] XOR UID-CLn[2] XOR UID-CLn[3]."},
        {"id": "FR-L3-UID-09",       "text": "UID lengths shall be 4 bytes (single CL), 7 bytes (CL1 + CL2 with CT 0x88), or 10 bytes (CL1 + CL2 + CL3)."},
        {"id": "FR-L3-CT-10",        "text": "Cascade Tag CT = 0x88 (Type A) shall mark a UID block that is not yet complete."},
        {"id": "FR-L3-SAK-11",       "text": "After the PCD transmits a complete SELECT for the final cascade level, the PICC shall return a 1-byte SAK + CRC_A. SAK bit 3 = 1 means UID not complete; SAK bit 6 = 1 means T=CL supported."},
        {"id": "FR-L3-MANUF-12",     "text": "UID byte 0 shall be the IC Manufacturer Byte per ISO/IEC 7816-6 (0x04 = NXP, 0x05 = Infineon, 0x07 = STMicro, 0x08 = Random ID)."},
        {"id": "FR-L3-HLTA-13",      "text": "A PICC shall transition to HALT state on receipt of HLTA (0x50 0x00 + CRC_A); subsequent REQA shall not wake it (WUPA required)."},
        {"id": "FR-L4-RATS-14",      "text": "When SAK indicates ISO/IEC 14443-4 support, the PCD may activate Layer 4 by transmitting RATS (0xE0 + PARAM = FSDI<<4 | CID) and the PICC shall reply with ATS."},
        {"id": "FR-L4-ATS-15",       "text": "ATS shall be a length-prefixed structure: TL + T0 + optional TA(1) / TB(1) / TC(1) + historical bytes."},
        {"id": "FR-L4-T_CL-16",      "text": "Layer 4 shall use three block types: I-Block, R-Block (ACK/NAK), S-Block (DESELECT or WTX)."},
        {"id": "FR-CRC-A-17",        "text": "Frames longer than the short-frame size shall be protected by CRC_A with poly 0x8408 (reflected), init 0x6363."},
        {"id": "FR-CRC-B-18",        "text": "Type B frames shall use CRC_B = CRC-16/X-25 with init 0xFFFF, final XOR 0xFFFF."},
        {"id": "FR-RID-19",          "text": "A PICC may use a Random ID (RID) for privacy: UID0 = 0x08 fixed, UID1..UID3 randomised at each Power-on Reset."},
        {"id": "FR-GET-VER-20",      "text": "For exact identification beyond ATQA/SAK, the PCD should issue GetVersion (0x60) on PICCs that advertise the command."},
    ]
    if _empty(d.get("functional_requirements")):
        d["functional_requirements"] = fr
    if _empty(d.get("error_response_conditions")):
        d["error_response_conditions"] = [
            "Bit collision during anti-collision — PCD detects the collision bit-position and re-transmits SELECT with NVB extended.",
            "CRC_A / CRC_B mismatch — PICC silently ignores the malformed frame; PCD detects via response timeout and may retry.",
            "Parity error on Type A — PICC drops a frame on parity error and does not respond.",
            "Frame size violation — PCD shall not exceed PICC's FSCI-advertised size; PICC shall not exceed PCD's FSDI.",
            "PICC moves to HALT after HLTA; subsequent REQA shall not wake it (WUPA required).",
            "Loss of carrier / removal from field — PICC loses VCC; all session state is lost.",
            "WTX requested by PICC via S-Block when an internal operation requires longer than the negotiated FWT.",
            "Block-number desynchronisation — T=CL uses 1-bit alternating block number; mismatch triggers retransmission via R(NAK).",
        ]
    if _empty(d.get("compliance_requirements")):
        d["compliance_requirements"] = [
            "PCD shall maintain Hmin operating field strength of 1.5 A/m and Hmax of 7.5 A/m at the operating volume per ISO 14443-2.",
            "PCD shall use 100% ASK + Modified Miller for Type A and 10% ASK + NRZ-L for Type B PCD→PICC paths.",
            "PICC shall power up, decode REQA, and respond with ATQA within fdt_listen ≤ 86.43 μs.",
            "PCD shall wait at least fdt_poll ≥ 1172 / fc ≈ 86.43 μs before transmitting again.",
            "PICC initial response shall always be at 106 kbps; higher rates require explicit PPS negotiation after RATS.",
            "PCD shall implement the bit-frame anti-collision loop until exactly one PICC is selected.",
            "PCD shall validate SAK bit 6 before issuing RATS — issuing RATS to a non-14443-4 PICC is a violation.",
            "Application-layer commands above Layer 4 shall be wrapped as APDUs in I-Block payload.",
        ]
    if _empty(d.get("configurations")):
        d["configurations"] = [
            {"name": "Type A 106 kbps + ISO 14443-3 only", "description": "MIFARE Classic / Ultralight / NTAG21x default. SAK bit 6 = 0."},
            {"name": "Type A 106 kbps + ISO 14443-4 T=CL", "description": "MIFARE DESFire / DESFire Light / MIFARE Plus SL2/SL3 / JCOP. SAK bit 6 = 1."},
            {"name": "Type A higher rates (212/424/848 kbps)", "description": "Negotiated by PPS after ATS for ISO 14443-4 PICCs."},
            {"name": "Type B + ISO 14443-4 T=CL", "description": "ATQB returns 12 bytes; ATTRIB selects; Layer 4 same as Type A."},
            {"name": "Random ID (RID) privacy mode", "description": "PICC randomises UID1..UID3; UID0 = 0x08."},
        ]
    _write(p, d)


# ---------------------------------------------------------------------------
# L3 CMD protocol
# ---------------------------------------------------------------------------

def _l3(gd: Path) -> None:
    p = gd / "L3_CMD_PROTOCOL.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("protocol_type",
        "Three-layer half-duplex contactless command/response protocol. Layer 2 "
        "(ISO 14443-2): 13.56 MHz carrier + modulation. Layer 3 (ISO 14443-3): "
        "anti-collision and selection. Layer 4 (ISO 14443-4): T=CL Block "
        "Transmission Protocol.")
    d.setdefault("frame_types_type_a", [
        {"name": "Short frame", "bits": 7, "purpose": "Initial polling / wake / halt — no parity, no CRC.", "used_for": "REQA (0x26), WUPA (0x52)."},
        {"name": "Standard frame", "bits": "N×9 + 2 × (8+1) CRC_A", "purpose": "Anti-collision/selection and T=CL traffic.", "used_for": "SELECT, ATQA carry, SAK carry, RATS, ATS, T=CL blocks."},
        {"name": "Anti-collision (bit-oriented) frame", "bits": "16..45", "purpose": "Bit-position collision resolution.", "used_for": "ANTICOLLISION CL1/CL2/CL3."},
    ])
    d.setdefault("layer3_short_frame_commands_type_a", [
        {"name": "REQA", "code_hex": "0x26", "bits": 7, "wakes_halt": False, "response": "ATQA (2 bytes)", "description": "Request Command, Type A — wake any PICC in IDLE."},
        {"name": "WUPA", "code_hex": "0x52", "bits": 7, "wakes_halt": True,  "response": "ATQA (2 bytes)", "description": "Wake-Up Command, Type A — wake any PICC in IDLE or HALT."},
        {"name": "HLTA", "code_hex_seq": "0x50 0x00 + CRC_A (2 bytes)", "bits": 32, "wakes_halt": False, "response": "no response (silence acknowledges HALT)", "description": "HALT Command, Type A — instruct selected PICC to enter HALT state."},
    ])
    d.setdefault("layer3_atqa_format", {
        "size_bytes": 2,
        "transmit_order": "LSB byte 1 first then byte 2; bits LSB-first within each byte.",
        "byte_1_bits": [
            {"bits": "b1-b5", "field": "Bit frame anti-collision bitmap", "description": "Which of the 5 anti-collision frame variants the PICC supports."},
            {"bits": "b6",    "field": "RFU",                              "description": "Reserved; encoded as 0."},
            {"bits": "b7-b8", "field": "UID size",                         "description": "00 = single (4 B), 01 = double (7 B), 10 = triple (10 B), 11 = RFU."},
        ],
        "byte_2_bits": [
            {"bits": "b1-b4", "field": "Proprietary", "description": "Vendor-defined classification."},
            {"bits": "b5-b8", "field": "RFU",          "description": "Reserved."},
        ],
        "common_values": [
            {"atqa": "0x00 0x04", "interpretation": "MIFARE Classic 1K or MIFARE Plus SL1 2K"},
            {"atqa": "0x00 0x02", "interpretation": "MIFARE Classic 4K or MIFARE Plus SL1 4K"},
            {"atqa": "0x00 0x44", "interpretation": "MIFARE Ultralight family / NTAG"},
            {"atqa": "0x03 0x44", "interpretation": "MIFARE DESFire (EV1/EV2/EV3) or MIFARE DESFire Light"},
            {"atqa": "0x00 0x42", "interpretation": "MIFARE Plus SL3"},
        ],
    })
    d.setdefault("layer3_select_cascade_commands_type_a", [
        {"sel": "0x93", "cascade_level": 1, "purpose": "Anti-collision and SELECT for the 4 first bytes of UID."},
        {"sel": "0x95", "cascade_level": 2, "purpose": "Anti-collision and SELECT for UID bytes 4..7 (for 7- or 10-byte UID)."},
        {"sel": "0x97", "cascade_level": 3, "purpose": "Anti-collision and SELECT for UID bytes 7..9 (for 10-byte UID)."},
    ])
    d.setdefault("layer3_select_format", {
        "select_frame_size_bytes": 9,
        "fields": [
            {"name": "SEL",           "size_bytes": 1, "value": "0x93 / 0x95 / 0x97", "description": "Cascade level byte."},
            {"name": "NVB",           "size_bytes": 1, "value": "0x70 = full SELECT", "description": "Number of Valid Bits."},
            {"name": "UID-CLn[0..3]", "size_bytes": 4, "value": "UID bytes for this CL", "description": "UID-CL1[0]=0x88 for 7-byte UID."},
            {"name": "BCC",           "size_bytes": 1, "value": "XOR of the 4 UID-CLn bytes", "description": "Block Check Character."},
            {"name": "CRC_A",         "size_bytes": 2, "value": "CRC over SEL..BCC", "description": "Polynomial 0x8408 reflected, init 0x6363."},
        ],
        # ISO/IEC 14443-3 §6.4.4: the final SELECT response carries the SAK byte
        # (1 B) plus the CRC_A (2 B). The 3-byte total is the frame footprint
        # captured by L8_TIMING_WAVEFORM.sak_frame_waveform.size_bytes=3.
        "sak_response_size_bytes": "1 SAK byte + 2 CRC_A bytes",
    })
    d.setdefault("layer3_sak_format", {
        "size_bytes": 1,
        "bits_msb_first": [
            {"bit": "b8", "field": "RFU",                          "description": "Reserved."},
            {"bit": "b7", "field": "RFU",                          "description": "Reserved."},
            {"bit": "b6", "field": "ISO 14443-4 compliant",        "description": "1 = PICC supports T=CL."},
            {"bit": "b5", "field": "RFU",                          "description": "Reserved."},
            {"bit": "b4", "field": "Proprietary",                  "description": "NXP variant encoding."},
            {"bit": "b3", "field": "UID not complete (CT follows)","description": "1 = next Cascade Level required."},
            {"bit": "b2", "field": "RFU",                          "description": "Reserved."},
            {"bit": "b1", "field": "Proprietary",                  "description": "NXP variant encoding."},
        ],
        "well_known_values": [
            {"sak_hex": "0x00", "meaning": "MIFARE Ultralight / NTAG — no ISO 14443-4."},
            {"sak_hex": "0x04", "meaning": "UID not complete (Cascade Tag follows)."},
            {"sak_hex": "0x08", "meaning": "MIFARE Classic 1K (and MIFARE Plus SL1 2K / SE)."},
            {"sak_hex": "0x10", "meaning": "MIFARE Plus SL2 2K."},
            {"sak_hex": "0x11", "meaning": "MIFARE Plus SL2 4K."},
            {"sak_hex": "0x18", "meaning": "MIFARE Classic 4K (and MIFARE Plus SL1 4K)."},
            {"sak_hex": "0x20", "meaning": "ISO 14443-4 compliant — DESFire / Plus SL3 / JCOP."},
            {"sak_hex": "0x28", "meaning": "ISO 14443-4 + UID not complete."},
        ],
    })
    d.setdefault("layer3_anticollision_loop_summary", [
        "1. PCD transmits REQA (0x26, 7-bit short frame).",
        "2. PICC(s) reply with ATQA (2 bytes).",
        "3. PCD enters Cascade Level 1 (SEL = 0x93) — bit-frame anti-collision.",
        "4. PCD sends SEL + NVB → PICCs reply UID-CL1[0..3] + BCC.",
        "5. If bit collision at bit k: PCD records bits 0..k-1, sets bit k, updates NVB, retransmits.",
        "6. Loop until NVB = 0x70 — only one PICC remains.",
        "7. PCD sends full SELECT → PICC responds with SAK.",
        "8. If SAK bit 3 = 1: advance to next Cascade Level.",
        "9. After the final Cascade Level: PCD has complete UID + final SAK.",
        "10. If SAK bit 6 = 1: PCD may issue RATS to activate Layer 4.",
    ])
    d.setdefault("layer4_rats_format", {
        "command_byte": "0xE0",
        "size_bytes_command": 4,
        "fields_command": [
            {"name": "Start byte", "value": "0xE0",                              "description": "RATS opcode."},
            {"name": "PARAM",       "value": "FSDI (b8:b5) | CID (b4:b1)",       "description": "FSDI 0..8 encodes PCD max frame size; CID 0..14."},
            {"name": "CRC_A",       "value": "2 bytes",                          "description": "Frame integrity."},
        ],
    })
    d.setdefault("layer4_ats_format", {
        "ats_byte_layout": [
            {"name": "TL",             "size_bytes": 1, "description": "Total ATS length."},
            {"name": "T0",             "size_bytes": 1, "description": "Interface bytes presence + FSCI."},
            {"name": "TA(1) (optional)","size_bytes": 1, "description": "Bit-rate support."},
            {"name": "TB(1) (optional)","size_bytes": 1, "description": "FWI + SFGI."},
            {"name": "TC(1) (optional)","size_bytes": 1, "description": "NAD + CID support."},
            {"name": "Historical bytes","size_bytes": "0..15", "description": "Vendor-specific."},
            {"name": "CRC_A",          "size_bytes": 2, "description": "Frame integrity."},
        ],
        "fsci_to_fsc_table_bytes": {"0": 16, "1": 24, "2": 32, "3": 40, "4": 48, "5": 64, "6": 96, "7": 128, "8": 256},
        "fwi_meaning": "FWT = (256 × 16 / fc) × 2^FWI; FWI ∈ {0..14}; fc = 13.56 MHz.",
    })
    d.setdefault("layer4_t_cl_blocks", [
        {"name": "I-Block",  "pcb_pattern": "0b000C-NRBN", "purpose": "Information block — carries APDU."},
        {"name": "R-Block",  "pcb_pattern": "0b101N-X0RN", "purpose": "ACK (R(ACK)) / NAK (R(NAK))."},
        {"name": "S-Block",  "pcb_pattern": "0b11SS-X0X0", "purpose": "S(DESELECT) / S(WTX)."},
    ])
    d.setdefault("layer4_pcb_byte_decoded", {
        "I_Block_pattern":       "0000 0010 + CID/NAD/chaining",
        "R_Block_ACK_pattern":   "1010 0010",
        "R_Block_NAK_pattern":   "1011 0010",
        "S_Block_DESELECT":      "1100 0010",
        "S_Block_WTX":           "1111 0010",
    })
    d.setdefault("layer4_block_format", {
        "fields_order":          ["PCB", "(CID) optional", "(NAD) optional", "INF (payload)", "CRC_A (2 B)"],
        "block_number_field":    "PCB bit 1 is the 1-bit alternating block number.",
    })
    d.setdefault("type_b_command_summary", [
        {"name": "REQB / WUPB", "fields": "APf (0x05) + AFI + PARAM + CRC_B", "description": "Polling for Type B."},
        {"name": "ATQB",         "fields": "0x50 + PUPI + Application + Protocol Info + CRC_B", "description": "Answer to REQB."},
        {"name": "ATTRIB",       "fields": "0x1D + PUPI + Param1..Param4 + INF + CRC_B", "description": "PCD selects PICC by PUPI."},
        {"name": "HLTB",         "fields": "0x50 + PUPI + CRC_B", "description": "Move PICC to HALT-B."},
    ])
    # v0.1.85+ — CRC-A / CRC-B definitions follow ISO/IEC 13239 reflected-CRC
    # convention: byte-reflection (LSB-first) on input AND output, with no
    # final XOR for Type A (CRC initial = 0x6363) and XOR-out = 0xFFFF for
    # Type B (CRC initial = 0xFFFF). Express the reflection fields as
    # prose strings ("yes (LSB-first ...)") rather than booleans because the
    # CRC standard distinguishes byte-reflection from bit-reflection and the
    # parity-target carries the qualifier text verbatim.
    d.setdefault("crc_a_definition", {
        "polynomial":           "x^16 + x^12 + x^5 + 1 (CRC-CCITT)",
        "polynomial_hex_reflected": "0x8408",
        "initial_value":        "0x6363",
        "final_xor":            "none (no XOR-out)",
        "input_byte_reflection": "yes (LSB-first)",
        "output_reflection":    "yes (LSB-first on wire)",
        "covers": "all frame bytes after SOF up to but excluding the CRC itself; CRC then appended LSB-first.",
    })
    d.setdefault("crc_b_definition", {
        "polynomial":           "x^16 + x^12 + x^5 + 1 (CRC-CCITT)",
        "polynomial_hex_reflected": "0x8408",
        "initial_value":        "0xFFFF",
        "final_xor":            "0xFFFF",
        "input_byte_reflection": "yes",
        "output_reflection":    "yes",
        "covers": "all frame bytes after SOF up to but excluding the CRC.",
    })
    d.setdefault("byte_oriented", True)
    d.setdefault("bit_oriented_anticollision", True)
    d.setdefault("burst_based", False)
    d.setdefault("msb_or_lsb_first", "LSB-first on Type A wire; LSB-first on Type B wire; parity bit (Type A only) follows every byte.")
    d.setdefault("valid_ready_handshake_rules", [
        "There is no VALID/READY handshake on the air interface; framing uses SOF + parity (Type A) or SOF + EGT (Type B) + CRC.",
        "PCD-side flow control via Frame Waiting Time (FWT); if PICC needs longer, it transmits S(WTX).",
        "Block-number alternation on T=CL detects lost block; R(NAK) requests retransmission.",
    ])
    d.setdefault("frame_format", {
        "type_a_short_frame":     "SOF + 7 data bits LSB-first + EOF.",
        "type_a_standard_frame":  "SOF + repeat[ byte LSB-first + odd parity bit ] + CRC_A + EOF.",
        "type_a_anti_collision":  "SOF + bytes-up-to-collision + collision bit + remaining bits from PICC + EOF.",
        "type_b_frame":           "SOF + char[ start(0) + 8 data + stop(1) + 2 EGT ETU HIGH ] + CRC_B + EOF.",
    })
    if _empty(d.get("channels")):
        d["channels"] = [
            {"name": "RF (air carrier)", "direction": "PCD → field; PICC modulates load → PCD", "description": "Single 13.56 MHz channel."},
            {"name": "RF subcarrier",    "direction": "PICC → PCD (load modulation)",           "description": "847.5 kHz subcarrier (fc/16)."},
        ]
    d.setdefault("command_set_layer_summary", {
        "layer_2_iso14443_2":  "Modulation + carrier; no commands at this layer.",
        "layer_3_iso14443_3_type_a": "REQA / WUPA / ATQA / ANTICOLLISION / SELECT / SAK / HLTA.",
        "layer_3_iso14443_3_type_b": "REQB / WUPB / ATQB / ATTRIB / HLTB.",
        "layer_4_iso14443_4":   "RATS / ATS / PPS / I-Block / R-Block / S(DESELECT) / S(WTX).",
        "layer_application_mifare_classic": "AUTH (0x60/0x61), READ (0x30), WRITE (0xA0), DECREMENT, INCREMENT, TRANSFER.",
        "layer_application_mifare_ultralight_ntag": "GetVersion (0x60), READ (0x30), FAST_READ (0x3A), WRITE (0xA2), PWD_AUTH (0x1B).",
        "layer_application_mifare_desfire": "AuthenticateAES (0xAA), SelectApplication (0x5A), ReadData (0xBD), WriteData (0x3D), GetVersion (0x60), GetUID (0x51).",
    })
    _write(p, d)


# ---------------------------------------------------------------------------
# L4 registers
# ---------------------------------------------------------------------------

def _l4(gd: Path) -> None:
    p = gd / "L4_REGMAP.json"
    if not p.is_file():
        return
    d = _read(p)
    d["register_map_present"] = True
    d["notes"] = (
        "ISO/IEC 14443 itself does not standardise a host-bus register map; what "
        "it standardises are on-card identification structures (ATQA, UID + SAK "
        "per Cascade Level, ATS) and a small set of MIFARE family classification "
        "'pseudo-registers' that AN10833 documents as the deterministic identity "
        "surface of every PICC. PCD reader chips (CLRC663, PN512, MFRC522) "
        "implement their own host-side register file behind SPI/I2C/UART — "
        "those are vendor-specific and out of scope here.")
    d.setdefault("register_count", 9)
    regs = [
        {"name": "ATQA", "long_name": "Answer to Request, Type A", "width_bits": 16,
         "access": "Read (PICC reply to REQA / WUPA)",
         "description": "16-bit identification field returned by the PICC."},
        {"name": "UID", "long_name": "Unique Identifier (Type A)", "width_bits": "32 / 56 / 80",
         "access": "Read (across Cascade Levels 1..3)",
         "description": "Unique PICC serial number; UID byte 0 = Manufacturer Byte."},
        {"name": "BCC_per_CL", "long_name": "Block Check Character per Cascade Level", "width_bits": 8,
         "access": "Computed by both PCD and PICC",
         "description": "8-bit XOR of the 4 UID bytes within the current Cascade Level."},
        {"name": "SAK", "long_name": "Select Acknowledge (Type A)", "width_bits": 8,
         "access": "Read (PICC reply to final SELECT)",
         "description": "8-bit classification byte; bit 3 = UID not complete; bit 6 = ISO 14443-4 compliant."},
        {"name": "ATS", "long_name": "Answer To Select", "width_bits": "8 × TL",
         "access": "Read (PICC reply to RATS 0xE0)",
         "description": "Length-prefixed Layer 4 capability descriptor."},
        {"name": "GetVersion_Response", "long_name": "GetVersion command response", "width_bits": "7 × 8",
         "access": "Read (host APDU 0x60)",
         "description": "7-byte version frame; byte 2 = HW Product Type."},
        {"name": "ATQB", "long_name": "Answer To REQB, Type B", "width_bits": "12 × 8",
         "access": "Read (PICC reply to REQB / WUPB)",
         "description": "Type B equivalent of ATQA + UID + SAK."},
        {"name": "PCB", "long_name": "Protocol Control Byte (T=CL block header)", "width_bits": 8,
         "access": "Read/Write (per T=CL block)",
         "description": "First byte of every T=CL Layer-4 block."},
        {"name": "CID", "long_name": "Card IDentifier (logical channel)", "width_bits": 8,
         "access": "Read/Write (assigned by PCD at RATS PARAM)",
         "description": "0-14 = logical-channel CID; 15 = RFU."},
    ]
    if _empty(d.get("registers")):
        d["registers"] = regs
    _write(p, d)


# ---------------------------------------------------------------------------
# L5 ADI
# ---------------------------------------------------------------------------

def _l5(gd: Path) -> None:
    p = gd / "L5_ADI_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    # Force-overwrite (not setdefault): the R52 universal-protocol residual
    # cleanup pass that runs BEFORE the per-protocol synth defaults
    # `analog_digital_interface_present` to False (correct for pure-digital
    # AMBA-style bus interconnects). ISO/IEC 14443 IS an analog/mixed-signal
    # RF air interface (13.56 MHz carrier + 847.5 kHz subcarrier + ASK load
    # modulation), so the NFC overlay must overwrite the False that R52
    # planted; mirror the same force-overwrite pattern LIN uses to fix the
    # CAN/UART False default.
    d["analog_digital_interface_present"] = True
    d["signaling_summary"] = (
        "ISO/IEC 14443 is fundamentally an analog/mixed-signal protocol because "
        "Layer 2 is an RF air interface. The PCD generates a 13.56 MHz unmodulated "
        "carrier at field strength H within Hmin (1.5 A/m) and Hmax (7.5 A/m); "
        "Type A PCD→PICC bits are 100% ASK Modified-Miller pulses (pause durations "
        "2.0..3.0 μs); Type B uses 10% ASK NRZ-L. The PICC harvests power from the "
        "carrier, demodulates the envelope, and replies by switching a load "
        "resistor in/out of the resonant antenna at the 847.5 kHz subcarrier rate "
        "(Manchester for Type A, BPSK for Type B). All digital framing — bits, "
        "parity, CRC — is layered on top of this analog substrate.")
    d.setdefault("voltage_classes", [
        {"class": "PICC field-powered",      "field_strength_A_per_m": "1.5 ≤ H ≤ 7.5",  "applicable_modes": "All ISO 14443 PICCs — voltage is induced, not external."},
        {"class": "PCD analog supply",        "VDD_range_V": "typically 3.3 V or 5.0 V", "applicable_modes": "Powers PCD oscillator/modulator/receiver."},
        {"class": "PICC chip internal VCC",   "V_int_V": "1.6 .. 1.8 typ.", "applicable_modes": "Rectified + regulated; only valid while field is present."},
    ])
    # PICC-internal threshold levels — the rectified VCC at which the analog
    # front-end is guaranteed to operate. ISO/IEC 14443-2 §6 + the AN10833
    # PICC-power-budget guidance establishes 1.6 V (min) / 1.8 V (typ) /
    # shunt-regulator-clamped (max).
    d.setdefault("input_threshold_levels_picc_internal", {
        "Vcc_picc_min_V": 1.6,
        "Vcc_picc_typ_V": 1.8,
        "Vcc_picc_max_V": "Internally clamped (shunt regulator)",
    })
    d.setdefault("rf_carrier_parameters", {
        "fc_MHz": 13.56,
        # ISO/IEC 14443-2 expresses fc tolerance as an absolute ±7 kHz window
        # (≈ ±517 ppm of 13.56 MHz); keep both representations so downstream
        # parity-with-spec and parity-with-Claude tooling can match either.
        "fc_tolerance_ppm": "±7 kHz (≈ ±517 ppm) per ISO 14443-2",
        "subcarrier_fc_div_16_kHz": 847.5,
        "etu_us_at_106kbps": 9.44,
        "etu_us_at_212kbps": 4.72,
        "etu_us_at_424kbps": 2.36,
        "etu_us_at_848kbps": 1.18,
    })
    d.setdefault("type_a_pcd_to_picc_modulation", {
        "ask_depth_percent": "100% (full pause)",
        "pulse_pause_duration_us": "2.0 (min) .. 3.0 (max) at 106 kbps",
        "rise_time_to_5_percent_us": "≤ 0.5",
        "fall_time_to_5_percent_us": "≤ 0.5",
        "modulation_coding": "Modified Miller — bit 1 = pause in second half of ETU.",
        "etu_duration_at_106kbps_us": 9.44,
    })
    d.setdefault("type_a_picc_to_pcd_load_modulation", {
        "subcarrier_kHz": 847.5,
        "modulation_index_min_mV_peak": "22 / sqrt(H)",
        "coding": "Manchester — bit 1 = subcarrier ON in first half ETU + OFF in second half.",
        "etu_duration_at_106kbps_us": 9.44,
    })
    d.setdefault("type_b_pcd_to_picc_modulation", {
        "ask_depth_percent": "8% to 14% (nominal 10%)",
        # ISO/IEC 14443-2 §9.2 defines the rise time at the 10 % envelope point
        # for 106 kbps; higher rates use the same shape with the ETU scaled.
        "rise_time_to_10_percent_us": "≤ 2.0 (at 106 kbps)",
        "fall_time_to_10_percent_us": "≤ 2.0",
        # The coding is NRZ-L with bit-1 = high amplitude carrier and bit-0 =
        # lower amplitude (≈8-14 % depth); each ETU carries one bit.
        "modulation_coding": "NRZ-L — high amplitude carrier = bit 1, lower amplitude = bit 0; each ETU carries one bit.",
    })
    d.setdefault("type_b_picc_to_pcd_load_modulation", {
        "subcarrier_kHz": 847.5,
        "coding": "BPSK — phase 0° = bit 1, phase 180° = bit 0.",
    })
    d.setdefault("minimum_field_strength_for_picc_operation", {
        "Hmin_A_per_m_class1": 1.5,
        "Hmax_A_per_m_class1": 7.5,
        "operating_volume_mm": "Class 1: 100 × 60 mm reference area.",
    })
    d.setdefault("notes",
        "The PICC analog front-end is a passive rectifier + shunt regulator + "
        "envelope detector + load-switch modulator with no analog trim register "
        "exposed to the air interface — vendor-specific trim is wafer-test "
        "programmed and not visible to the PCD over RF.")
    d.setdefault("evidence_in_an10833", [
        "Section 1.3: 'The ISO/IEC 14443-2 defines the carrier frequency of 13.56 MHz, the modulation, and the bit coding'",
    ])
    _write(p, d)


# ---------------------------------------------------------------------------
# L6 control logic
# ---------------------------------------------------------------------------

def _l6(gd: Path) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("fsm_states_picc", [
        {"name": "POWER_OFF",  "code": "—", "description": "Card outside operating field; no internal state."},
        {"name": "IDLE",       "code": "0", "description": "Card powered but not yet polled."},
        {"name": "READY",      "code": "1", "description": "Card answered REQA/WUPA with ATQA."},
        {"name": "READY*",     "code": "2", "description": "Same as READY but reached from HALT."},
        {"name": "ACTIVE",     "code": "3", "description": "Card selected after final SELECT."},
        {"name": "ACTIVE*",    "code": "4", "description": "Same as ACTIVE but via HALT→WUPA."},
        {"name": "T_CL_ACTIVE","code": "5", "description": "ISO 14443-4 Layer 4 activated."},
        {"name": "HALT",       "code": "6", "description": "Card executed HLTA; only WUPA wakes it."},
    ])
    d.setdefault("fsm_transitions_major", [
        {"trigger": "Power-on (carrier present)", "from": "POWER_OFF", "to": "IDLE", "description": "Internal POR releases; OTP loads."},
        {"trigger": "REQA (0x26) received",        "from": "IDLE", "to": "READY", "description": "PICC transmits ATQA."},
        {"trigger": "WUPA (0x52) received",        "from": "IDLE / HALT", "to": "READY / READY*", "description": "PICC transmits ATQA."},
        {"trigger": "Anti-Collision / SELECT CL_n","from": "READY", "to": "READY", "description": "PICC keeps replying until NVB = 0x70."},
        {"trigger": "Final SELECT with matching UID","from": "READY", "to": "ACTIVE", "description": "PICC transmits SAK."},
        {"trigger": "RATS (0xE0) in ACTIVE (SAK b6=1)","from": "ACTIVE", "to": "T_CL_ACTIVE", "description": "PICC transmits ATS."},
        {"trigger": "S(DESELECT)",                  "from": "T_CL_ACTIVE", "to": "HALT", "description": "PICC enters HALT."},
        {"trigger": "HLTA (0x50 0x00)",             "from": "ACTIVE", "to": "HALT", "description": "PICC enters HALT."},
        {"trigger": "Carrier removed",              "from": "any", "to": "POWER_OFF", "description": "All state lost."},
        {"trigger": "PCB block-number mismatch",    "from": "T_CL_ACTIVE", "to": "T_CL_ACTIVE", "description": "PICC replies R(NAK)."},
    ])
    d.setdefault("fsm_states_pcd", [
        {"name": "PCD_FIELD_OFF",       "description": "Carrier off; antenna driver idle."},
        {"name": "PCD_FIELD_ON",        "description": "Carrier on; 5 ms guard for PICC POR."},
        {"name": "PCD_POLL_LOOP",       "description": "Cyclically transmit REQA + REQB."},
        {"name": "PCD_ANTICOLLISION",   "description": "Run Cascade Level loop."},
        {"name": "PCD_SELECTED",        "description": "Single PICC selected."},
        {"name": "PCD_T_CL_ACTIVE",     "description": "PCD owns the T=CL channel."},
        {"name": "PCD_HALT_AND_RESCAN", "description": "HLTA issued; rescan for more PICCs."},
    ])
    d.setdefault("fsm_hints", {
        "trigger": "PCD always initiates; PICC never autonomously transmits.",
        "rule":    "After HALT, the PCD must use WUPA (not REQA) to re-engage the same PICC.",
        "abort":   "PCD may always remove the field to forcibly reset all PICCs.",
    })
    d.setdefault("anti_deadlock_rule",
        "Layer 4 (T=CL) uses 1-bit alternating block numbers per direction. After "
        "any timeout > FWT or any R(NAK), the PCD retransmits with the same block "
        "number; the PICC must respond. If the PICC requests more time it "
        "transmits S(WTX) with a multiplier ≤ 59.")
    d.setdefault("exit_from_reset_or_poweron",
        "On internal POR, PICC loads its OTP'd UID / ATQA / SAK templates, sets "
        "state = IDLE, sets T=CL counters to 0, and starts listening.")
    d.setdefault("default_ready_state_recommendation", {
        "carrier_idle":         "PCD carrier present but no modulation.",
        "picc_subcarrier_idle": "OFF (load resistor not switching).",
        "antenna_loading":      "PCD antenna sees only the linear PICC rectifier load.",
    })
    d.setdefault("configurations", [
        {"name": "Type A only", "description": "PCD only polls REQA."},
        {"name": "Type A + Type B", "description": "PCD alternates REQA and REQB polls."},
        {"name": "Layer-3-only PICC", "description": "SAK bit 6 = 0; PCD never issues RATS."},
        {"name": "Layer-4 (T=CL) PICC", "description": "SAK bit 6 = 1; PCD issues RATS → ATS."},
        {"name": "Random ID (RID) mode", "description": "PICC reports UID0 = 0x08, UID1..UID3 randomised per POR."},
    ])
    d.setdefault("timing_dependency_rule",
        "All PCD-PICC timing is referenced to the 13.56 MHz carrier (fc). ETU at "
        "106 kbps is 128/fc ≈ 9.44 μs. The PICC must answer REQA within "
        "fdt_listen ≤ 1172/fc ≈ 86.43 μs from the end of the PCD command; the "
        "PCD must wait fdt_poll ≥ 1172/fc before resuming polling. T=CL uses "
        "FWT = (256 × 16 / fc) × 2^FWI.")
    _write(p, d)


# ---------------------------------------------------------------------------
# L7 test/debug
# ---------------------------------------------------------------------------

def _l7(gd: Path) -> None:
    p = gd / "L7_TEST_DEBUG.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("test_debug_architecture_present", False)
    d.setdefault("spec_provided_observability", [
        {"name": "UID",        "purpose": "Factory-OTP unique identifier."},
        {"name": "ATQA",       "purpose": "16-bit value advertising UID size + bit-frame AC support."},
        {"name": "SAK",        "purpose": "8-bit classification byte."},
        {"name": "BCC",        "purpose": "Block check character per Cascade Level."},
        {"name": "ATS",        "purpose": "ISO 14443-4 Layer 4 capability descriptor."},
        {"name": "GetVersion response", "purpose": "7-byte vendor-deterministic family ID."},
        {"name": "PCD error counters", "purpose": "Vendor-specific CRC / parity / framing counters."},
    ])
    d.setdefault("notes",
        "AN10833 does not specify a debug architecture; it specifies the "
        "deterministic identification surface (ATQA / SAK / UID / ATS / "
        "GetVersion) that itself serves as the standard observability for a "
        "freshly-discovered PICC.")
    d.setdefault("scope_observability", [
        "RF logic analyzer + 13.56 MHz envelope probe is the standard debug path.",
        "Subcarrier waveform on a scope confirms Manchester (Type A) vs BPSK (Type B).",
        "PCD's analog RX channel is the only visibility on PICC behavior.",
        "PCD reader chips often expose a 'collision-bit position' register.",
    ])
    d.setdefault("ate_or_dft",
        "No standard DFT / scan / JTAG path is exposed on the air interface or "
        "on the PICC IC. Wafer / package test uses internal scan + parametric "
        "pads visible only at probe.")
    _write(p, d)


# ---------------------------------------------------------------------------
# L8 RTL constants
# ---------------------------------------------------------------------------

def _l8_const(gd: Path) -> None:
    p = gd / "L8_RTL_CONSTANTS.json"
    if not p.is_file():
        return
    d = _read(p)
    wp = _ensure_dict(d, "width_parameters")
    for k, v in {
        "RF_CARRIER_HZ": 13560000,
        "SUBCARRIER_HZ": 847500,
        "ETU_DIVIDER_106KBPS": 128,
        "ETU_DIVIDER_212KBPS": 64,
        "ETU_DIVIDER_424KBPS": 32,
        "ETU_DIVIDER_848KBPS": 16,
        "ATQA_BITS": 16,
        "SAK_BITS": 8,
        "BCC_BITS": 8,
        "UID_BYTES_SINGLE": 4,
        "UID_BYTES_DOUBLE": 7,
        "UID_BYTES_TRIPLE": 10,
        "CASCADE_TAG_HEX": "0x88",
        "REQA_HEX": "0x26",
        "WUPA_HEX": "0x52",
        "HLTA_HEX_SEQ": "0x50 0x00",
        "SEL_CL1_HEX": "0x93",
        "SEL_CL2_HEX": "0x95",
        "SEL_CL3_HEX": "0x97",
        "NVB_FULL_HEX": "0x70",
        "RATS_HEX": "0xE0",
        "REQB_HEX_SEQ": "0x05 + AFI + PARAM",
        "ATQB_BYTES": 12,
        "PUPI_BYTES": 4,
        "PCB_BITS": 8,
        "CID_BITS": 4,
        "NAD_BITS": 8,
        "CRC_A_BITS": 16,
        "CRC_B_BITS": 16,
        "PARITY_BITS_PER_BYTE_TYPE_A": 1,
        "FSDI_BITS": 4,
        "FSCI_BITS": 4,
        "FWI_BITS": 4,
        "SFGI_BITS": 4,
        "BIT_RATES_KBPS": [106, 212, 424, 848],
    }.items():
        wp.setdefault(k, v)
    d.setdefault("crc_polynomials", {
        "CRC_A": {
            "polynomial":        "x^16 + x^12 + x^5 + 1 (CCITT)",
            "hex_reflected":     "0x8408",
            "init":              "0x6363",
            "final_xor":         "none",
            "input_reflection":  True,
            "output_reflection": True,
            "applies_to":        "ISO 14443-3 Type A standard frames + T=CL blocks.",
        },
        "CRC_B": {
            "polynomial":        "x^16 + x^12 + x^5 + 1 (CCITT)",
            "hex_reflected":     "0x8408",
            "init":              "0xFFFF",
            "final_xor":         "0xFFFF",
            "input_reflection":  True,
            "output_reflection": True,
            "applies_to":        "ISO 14443-3 Type B frames + T=CL blocks on Type B.",
        },
    })
    d.setdefault("manufacturer_byte_codes_iso_7816_6", {
        "0x04": "NXP Semiconductors",
        "0x05": "Infineon Technologies",
        "0x07": "STMicroelectronics",
        "0x02": "Atmel",
        "0x08": "Random ID (UID1..UID3 randomised at POR — privacy-preserving)",
        "0x16": "EM Microelectronic-Marin SA",
        "0x28": "AT&T / Bell",
        "0x33": "AMIC Technology",
    })
    d.setdefault("cascade_level_table", {
        "SEL_CL1": 147,
        "SEL_CL2": 149,
        "SEL_CL3": 151,
        "CT_BYTE": 136,
        "purpose": "SEL bytes (0x93/0x95/0x97) and Cascade Tag (0x88) — embedded in UID-CLn[0] of all non-final CLs.",
    })
    d.setdefault("voltage_levels", {
        "PICC_VCC_internal_min_V": 1.6,
        "PICC_VCC_internal_typ_V": 1.8,
        "Hmin_A_per_m": 1.5,
        "Hmax_A_per_m": 7.5,
    })
    cc = _ensure_dict(d, "clock_constants")
    for k, v in {
        "FC_MHz":                            13.56,
        "FC_TOLERANCE_PPM":                  517,
        "SUBCARRIER_DIVIDER":                16,
        "ETU_AT_106KBPS_US":                 9.44,
        "ETU_AT_212KBPS_US":                 4.72,
        "ETU_AT_424KBPS_US":                 2.36,
        "ETU_AT_848KBPS_US":                 1.18,
        "FDT_LISTEN_MAX_US_AT_106KBPS":      86.43,
        "FDT_POLL_MIN_US_AT_106KBPS":        86.43,
        "POWER_ON_TIME_MIN_MS":              5,
        "FWT_DEFAULT_FWI_4_MS":              4.83,
    }.items():
        cc.setdefault(k, v)
    kc = _ensure_dict(d, "key_constants_for_RTL_authoring")
    for k, v in {
        "REQA_PATTERN_7BIT":           "0010110",
        "WUPA_PATTERN_7BIT":           "0101001",
        "HLTA_PATTERN_BYTES":          "0x50 0x00",
        "SOF_TYPE_A_SYMBOL":           "Modified Miller 'Z' (pause in first half of ETU)",
        "EOF_TYPE_A_SYMBOL":           "Modified Miller logic 0 followed by no further modulation",
        "PARITY_RULE_TYPE_A":          "odd parity bit after every byte (LSB-first byte transmission)",
        "BIT_ORDER_ON_WIRE":           "LSB-first within each byte; bytes in protocol order",
        "ATQA_UID_SIZE_BITS_LOCATION": "Byte 1 bits 7..8 (LSB-first interpretation)",
        "SAK_T_CL_COMPLIANT_BIT":      "Bit 6 = 1",
        "SAK_UID_NOT_COMPLETE_BIT":    "Bit 3 = 1",
        "CASCADE_TAG_VALUE":           "0x88",
        "NVB_FORMAT":                  "High nibble = full bytes transmitted; low nibble = additional bits",
        "NVB_INITIAL_AC":              "0x20",
        "NVB_FULL_SELECT":             "0x70",
        "PCB_I_BLOCK_PATTERN":         "0b000c0010",
        "PCB_R_BLOCK_ACK_PATTERN":     "0b1010c01n",
        "PCB_R_BLOCK_NAK_PATTERN":     "0b1011c01n",
        "PCB_S_DESELECT_PATTERN":      "0b1100c010",
        "PCB_S_WTX_PATTERN":           "0b1111c010",
    }.items():
        kc.setdefault(k, v)
    d.setdefault("default_signal_values_when_idle", {
        "PCD_CARRIER":          "Continuous unmodulated 13.56 MHz when in field-on, no command.",
        "PICC_LOAD_MODULATION": "OFF (load resistor not switching).",
        "PICC_RESPONSE_WINDOW": "Closed except within fdt_listen of the end of a PCD command frame.",
    })
    d.setdefault("frame_size_fsci_table", {
        "0": 16, "1": 24, "2": 32, "3": 40, "4": 48, "5": 64, "6": 96, "7": 128, "8": 256,
        "9..15": "RFU",
    })
    d.setdefault("max_throughput_table", [
        {"mode": "Type A 106 kbps", "data_rate_kbps": 106, "ETU_us": 9.44,  "subcarrier_kHz": 847.5},
        {"mode": "Type A 212 kbps", "data_rate_kbps": 212, "ETU_us": 4.72,  "subcarrier_kHz": 847.5},
        {"mode": "Type A 424 kbps", "data_rate_kbps": 424, "ETU_us": 2.36,  "subcarrier_kHz": 847.5},
        {"mode": "Type A 848 kbps", "data_rate_kbps": 848, "ETU_us": 1.18,  "subcarrier_kHz": 847.5},
        {"mode": "Type B 106 kbps", "data_rate_kbps": 106, "ETU_us": 9.44,  "subcarrier_kHz": 847.5},
        {"mode": "Type B 212 kbps", "data_rate_kbps": 212, "ETU_us": 4.72,  "subcarrier_kHz": 847.5},
        {"mode": "Type B 424 kbps", "data_rate_kbps": 424, "ETU_us": 2.36,  "subcarrier_kHz": 847.5},
        {"mode": "Type B 848 kbps", "data_rate_kbps": 848, "ETU_us": 1.18,  "subcarrier_kHz": 847.5},
    ])
    _write(p, d)


# ---------------------------------------------------------------------------
# L8 TIMING
# ---------------------------------------------------------------------------

def _l8_timing(gd: Path) -> None:
    p = gd / "L8_TIMING_WAVEFORM.json"
    if not p.is_file():
        return
    d = _read(p)
    cw = _ensure_dict(d, "carrier_waveform")
    for k, v in {
        "fc_MHz":                       13.56,
        "fc_tolerance_ppm":             "±517 ppm (±7 kHz absolute)",
        "subcarrier_fc_div_16_kHz":     847.5,
        "etu_at_106kbps_us":            9.44,
        "etu_at_212kbps_us":            4.72,
        "etu_at_424kbps_us":            2.36,
        "etu_at_848kbps_us":            1.18,
        "minimum_field_strength_A_per_m":1.5,
        "maximum_field_strength_A_per_m":7.5,
    }.items():
        cw.setdefault(k, v)
    cf = _ensure_dict(d, "type_a_pcd_to_picc_waveform")
    cf.setdefault("modulation", "100% ASK Modified Miller (envelope dropped to 0)")
    cf.setdefault("pause_duration_us", "2.0 (min) .. 3.0 (max) at 106 kbps")
    cf.setdefault("rise_time_us", "≤ 0.5")
    cf.setdefault("fall_time_us", "≤ 0.5")
    cf.setdefault("miller_encoding", {
        "logic_1":     "Pause in the second half of the ETU (Z symbol)",
        "logic_0_after_logic_0": "Pause at the start of the ETU (X symbol)",
        "logic_0_after_logic_1": "No pause (Y symbol)",
        # Type A SOF is a Z symbol — the Modified-Miller spec uses the
        # leading logic-1 (Z) to establish receiver phase / bit-clock recovery.
        "SOF":         "Z (logic 1 prefix establishes phase)",
        "EOF":         "Logic 0 followed by no further modulation",
    })
    cf.setdefault("bit_order_on_wire", "LSB-first within each byte")
    cf.setdefault("parity_bit", "1 odd-parity bit appended after every 8 data bits")
    pa = _ensure_dict(d, "type_a_picc_to_pcd_waveform")
    pa.setdefault("modulation", "Load modulation at 847.5 kHz subcarrier")
    pa.setdefault("coding", "Manchester — bit 1 = subcarrier ON in first half of ETU.")
    pa.setdefault("SOF", "Subcarrier modulation starts with 'logic 1' pattern.")
    pa.setdefault("EOF", "Subcarrier OFF for ≥ 2 ETU.")
    bp = _ensure_dict(d, "type_b_pcd_to_picc_waveform")
    bp.setdefault("modulation", "10% ASK NRZ-L")
    bp.setdefault("rise_time_us", "≤ 2.0")
    bp.setdefault("fall_time_us", "≤ 2.0")
    bp.setdefault("etu_us_at_106kbps", 9.44)
    bp.setdefault("SOF", "10-11 ETU of low amplitude")
    bp.setdefault("EOF", "10-11 ETU of low amplitude")
    bb = _ensure_dict(d, "type_b_picc_to_pcd_waveform")
    bb.setdefault("modulation", "BPSK of 847.5 kHz subcarrier")
    bb.setdefault("SOF", "Subcarrier phase reference established")
    bb.setdefault("EOF", "Subcarrier turn-off")
    d.setdefault("timing_table_layer_3", {
        "fdt_listen_max_us_at_106kbps": 86.43,
        # Verbose definitions mirror the AN10833 §A wording so the parity gate
        # picks up the same descriptive phrasing.
        "fdt_listen_definition": (
            "Maximum delay from end of PCD frame (last EOF bit) to start of "
            "PICC response (first SOF bit). For short-frame (REQA/WUPA) PICC "
            "responses this is 1172/fc = 86.43 μs at 106 kbps."
        ),
        "fdt_poll_min_us_at_106kbps": 86.43,
        "fdt_poll_definition": (
            "Minimum PCD-side delay from end of PICC response (last EOF) "
            "before the PCD starts the next request, ensuring the PICC has "
            "time to switch its load modulator off."
        ),
        # ISO/IEC 14443-3 §6.2 specifies TR0/TR1/TRf as PICC-side subcarrier
        # turn-on / sync-pattern / ramp parameters; only the lower bound
        # (zero) is normatively defined — the upper bound is implementation-
        # specific. Reflect the qualifier text so the parity gate matches.
        "tr0_min_us": "0 (subcarrier turn-on time, lower bound only)",
        "tr1_min_us": "0 (synchronisation pattern duration, lower bound only)",
        "trf_min_us": "0 (subcarrier ramp time)",
    })
    d.setdefault("timing_table_layer_4", {
        "fwt_formula": "FWT = (256 × 16 / fc) × 2^FWI; FWI ∈ {0..14}",
        "fwt_fwi_0_ms": 0.302,
        "fwt_fwi_4_ms": 4.83,
        "fwt_fwi_8_ms": 77.3,
        "fwt_fwi_14_ms": 4949.0,
        "fwt_max_ms_fwi_14": 4949.0,
        "sfgt_formula": "SFGT = (256 × 16 / fc) × 2^SFGI; SFGI ∈ {0..14}",
        # WTXM (Waiting-Time eXtension Multiplier) is carried in the S(WTX)
        # Layer-4 S-Block (PCB = 0xF2) and extends FWT by the WTXM factor.
        # ISO/IEC 14443-4 §7.5.2 restricts the value to 1..59 (0/60..63 RFU).
        "wtxm_range": "1..59 (S(WTX) multiplier in S-Block)",
        "fwt_definition": "Frame Waiting Time — max PCD wait for PICC response.",
        "sfgt_definition": "Startup Frame Guard Time — min PCD wait after ATS.",
    })
    d.setdefault("atqa_frame_waveform", {
        "size_bits": 16,
        "transmit_after_REQA": "End of REQA EOF + fdt_listen ≤ 86.43 μs → ATQA SOF",
        "frame_structure": "Standard frame = SOF + bytes LSB-first + odd parity + EOF (no CRC)",
    })
    d.setdefault("select_frame_waveform", {
        "size_bytes": 9,
        "frame_structure": "Standard frame = SOF + repeat[ byte LSB-first + parity ] × 9 + EOF",
        "pcd_to_picc_byte_order": ["SEL", "NVB", "UID-CLn[0]", "UID-CLn[1]", "UID-CLn[2]", "UID-CLn[3]", "BCC", "CRC_A[7:0]", "CRC_A[15:8]"],
    })
    d.setdefault("sak_frame_waveform", {
        "size_bytes": 3,
        "frame_structure": "Standard frame = SOF + (SAK + parity) + CRC_A + EOF",
    })
    d.setdefault("rats_ats_waveform", {
        "rats_size_bytes": 4,
        "rats_byte_order": ["0xE0", "PARAM (FSDI/CID)", "CRC_A[7:0]", "CRC_A[15:8]"],
        "ats_size_bytes": "TL + 2 (variable; TL is first byte; CRC_A appended)",
        "ats_byte_order": ["TL", "T0", "TA(1)?", "TB(1)?", "TC(1)?", "Historical bytes", "CRC_A[7:0]", "CRC_A[15:8]"],
    })
    d.setdefault("t_cl_block_waveform", {
        "block_byte_order": ["PCB", "CID? (if PCB.b4=1)", "NAD? (if PCB.b3=1, I-Block only)", "INF[]", "CRC_A[7:0]", "CRC_A[15:8]"],
        # Spell out the overhead components (PCB + CRC_A) so downstream
        # parity-with-Claude tooling matches the explicit subtraction form.
        "max_inf_bytes_at_fsci_8": "≤ 256 - PCB - CRC_A overhead = 251 bytes",
        "max_inf_bytes_at_fsci_5": "≤ 64 - overhead = 59 bytes",
    })
    d.setdefault("timing_tables_referenced", [
        "ISO 14443-2 §8 — PCD Type A modulation timing",
        "ISO 14443-2 §9 — PCD Type B modulation timing",
        "ISO 14443-3 §6.1 — Polling sequence and FDT",
        "ISO 14443-3 §6.4.3 — Anti-collision frame timing",
        "ISO 14443-4 §7.2 — FWT and SFGT timing",
        "ISO 10373-6 — Test methods for proximity cards",
    ])
    d.setdefault("general_timing_rule",
        "All ISO 14443 timing is referenced to the 13.56 MHz carrier (fc). ETU = "
        "128/fc ≈ 9.44 μs at 106 kbps; higher rates halve ETU. PICC must answer "
        "REQA within fdt_listen ≤ 86.43 μs; PCD must wait fdt_poll. Layer 4 FWT "
        "= (256 × 16 / fc) × 2^FWI bounds PICC processing time per block.")
    d.setdefault("voltage_thresholds", {
        "PCD_modulation_envelope_min_pause_pct_Type_A": 100,
        "PCD_modulation_envelope_pct_Type_B":           "88-92% (10% modulation index)",
        "PICC_subcarrier_min_amplitude_at_reference_antenna_mV": "22 / sqrt(H)",
    })
    _write(p, d)


# ---------------------------------------------------------------------------
# L9 integration
# ---------------------------------------------------------------------------

def _l9(gd: Path) -> None:
    p = gd / "L9_INTEGRATION_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("module_role",
        "Air-interface contactless identification protocol stack between a PCD "
        "(reader) and one or more PICCs within a single 13.56 MHz RF field. "
        "Defines air carrier (Layer 2), anti-collision and selection (Layer 3), "
        "and block transmission protocol (Layer 4).")
    _ptm.apply(d, "NFC_ISO14443_Stack")
    io = _ensure_dict(d, "integration_overview")
    io.setdefault("air_interface_pin_count_picc", 2)
    io.setdefault("air_interface_pin_count_pcd", "2 antenna driver + matching network components")
    io.setdefault("host_bus_to_pcd_chip", "SPI (most common) / I2C / UART / parallel")
    io.setdefault("antenna_resonance_target_MHz", "13.56 (Q ≈ 30..40 for PCD, Q ≈ 20..30 for PICC)")
    io.setdefault("no_chip_select_air_interface", "Air interface has no chip-select; addressing is by UID (Layer 3) or CID (Layer 4).")
    io.setdefault("controller_role", "PCD is master and field generator; PICC is field-powered slave.")
    io.setdefault("no_handshake_per_bit", "Bit-level framing via SOF + parity + CRC; flow control above is via FWT and S(WTX).")
    d.setdefault("interface_categories", [
        "RF Air Interface (single 13.56 MHz inductively-coupled channel)",
        "PICC antenna terminals (LA, LB) — passive coil + tuning capacitor",
        "PCD antenna driver pair (TX1, TX2) + matching network + receive path",
        "PCD host bus (SPI / I2C / UART / parallel) to embedded MCU",
        "PCD interrupt line (IRQ) and reset / power-down (NRSTPD)",
        "PCD crystal oscillator (typical 27.12 MHz)",
    ])
    d.setdefault("interconnect_topologies_supported", [
        "Single PCD + single PICC — most common case",
        "Single PCD + multiple PICCs — anti-collision required",
        "Single PCD + Type A + Type B mix — PCD alternates polls",
        "Co-located PCDs — only one PCD field active at a time",
        "NFC peer-to-peer — strictly out of ISO 14443 scope",
    ])
    d.setdefault("default_signal_values_when_omitted",
        "PCD's antenna driver is push-pull through the matching network when "
        "transmitting; receive path operates concurrently for load-modulation "
        "detection. PICC antenna terminals are passive.")
    d.setdefault("soc_dependent_items", [
        "PCD reader chip (CLRC663 / PN5180 / PN512 / MFRC522 / TRF7970A)",
        "Antenna geometry + Q-tuning matching network",
        "EMC filter on antenna driver",
        "ESD protection on antenna terminals",
        "Crystal source (typical 27.12 MHz)",
        "Host MCU / AP running NFC stack",
        "Optional secure element (SE) for payment / authentication",
    ])
    d.setdefault("pull_up_resistors", [
        {"signal": "PCD SPI / I2C bus", "value_kohm": "4.7-10", "location": "host PCB", "purpose": "Idle bus HIGH."},
        {"signal": "PCD IRQ",           "value_kohm": "10",     "location": "host PCB", "purpose": "Level-triggered."},
        {"signal": "PCD NRSTPD",        "value_kohm": "10",     "location": "host PCB", "purpose": "Default released."},
    ])
    lpm = _ensure_dict(d, "low_power_modes")
    lpm.setdefault("PCD_carrier_off",   "Maximum power saving.")
    lpm.setdefault("PCD_doze_mode",     "Chip-specific reduced polling cadence.")
    lpm.setdefault("PICC_field_off",    "Total loss of VCC; no PICC state retained.")
    lpm.setdefault("T_CL_S_DESELECT",   "Layer 4: PCD drops PICC from T_CL_ACTIVE to HALT.")
    d.setdefault("compatibility_notes", [
        "Type A and Type B PICCs share the same 13.56 MHz carrier but use different modulation/coding.",
        "MIFARE Classic family (and MIFARE Plus SL1) sits above Layer 3 with a proprietary Crypto1 command set; SAK bit 6 = 0.",
        "MIFARE DESFire family (and Plus SL2/SL3) advertises SAK bit 6 = 1 and runs above T=CL with APDU semantics.",
        "MIFARE Ultralight / NTAG21x are NFC Forum Type 2 tags — Layer 3 + simple READ/WRITE.",
        "Modern reader chips support Type A + Type B + ISO 15693 + ISO 18092 + EMVCo + NFC Forum simultaneously.",
        "All MIFARE ICs are compliant to ISO/IEC 14443 part 2 (Layer 2) and part 3 (Layer 3); Part 4 (T=CL) is optional.",
    ])
    _write(p, d)


# ---------------------------------------------------------------------------
# L10 test cases
# ---------------------------------------------------------------------------

def _l10(gd: Path) -> None:
    p = gd / "L10_TEST_CASES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_cases_present"] = (
        "partial - AN10833 plus ISO/IEC 14443-1/2/3/4 define functional commands, "
        "register layouts, anti-collision flow, and timing tables that map "
        "directly to compliance test scenarios. ISO 10373-6 is the normative "
        "compliance test framework and is out of scope of this application note.")
    tc = d.get("test_cases")
    if isinstance(tc, list):
        d["test_cases"] = [x for x in tc if not (isinstance(x, dict) and "opcode_hex" in x)]
    if _empty(d.get("derived_compliance_test_categories")):
        d["derived_compliance_test_categories"] = [
            "PICC Layer-3 reset on field exit / re-entry.",
            "REQA → ATQA reply; verify 16-bit ATQA contents.",
            "WUPA → ATQA from both IDLE and HALT.",
            "REQA from HALT shall NOT trigger ATQA.",
            "Cascade Level 1 anti-collision: SEL = 0x93 + BCC.",
            "Cascade Level 2: SEL = 0x95 with Cascade Tag 0x88 in UID-CL1[0].",
            "Cascade Level 3: SEL = 0x97 for 10-byte UID PICCs.",
            "Full SELECT (NVB = 0x70) → SAK with CRC_A.",
            "BCC verification per CL: XOR of 4 UID bytes.",
            "Cascade Tag (0x88) presence in UID-CL1[0] for 7-/10-byte UID PICCs.",
            "Random ID mode: UID0 = 0x08, UID1..UID3 differ across POR events.",
            "HLTA → HALT transition; PICC silent on REQA, responsive on WUPA.",
            "Multi-PICC anti-collision: 2..N PICCs in field.",
            "Bit-frame collision injection.",
            "SAK b6 = 0 PICC + RATS: PCD shall NOT issue RATS.",
            "SAK b6 = 1 PICC + RATS → ATS with TL/T0/optional bytes.",
            "ATS FSCI vs PCD FSDI: respect frame size.",
            "ATS FWI: PCD shall wait FWT before timeout.",
            "T=CL I-Block round-trip with alternating block number.",
            "T=CL R(NAK) → PCD retransmission.",
            "T=CL S(WTX) → PCD extension of FWT.",
            "T=CL S(DESELECT) → PICC enters HALT.",
            "GetVersion on MIFARE Ultralight EV1 → byte 2 = 0xX3.",
            "GetVersion on MIFARE Plus EV1 → byte 2 = 0xX2.",
            "GetVersion on MIFARE DESFire EV3 → byte 2 = 0xX1.",
            "GetVersion on MIFARE DESFire Light → byte 2 = 0xX8.",
            "GetVersion on NTAG21x → byte 2 = 0xX4.",
            "GetVersion on legacy MIFARE Classic 1K → fallback to ATQA/SAK.",
            "Type B REQB → ATQB (12 bytes); PUPI extracted.",
            "Type B ATTRIB → PICC selection.",
            "CRC_A / CRC_B injection: PICC shall silently ignore.",
            "Parity bit injection (Type A): PICC shall silently ignore.",
            "Bit rate negotiation: PPS after RATS.",
            "Field-on guard time ≥ 5 ms before first REQA.",
            "Operation at H = Hmin = 1.5 A/m and Hmax = 7.5 A/m.",
        ]
    _write(p, d)


# ---------------------------------------------------------------------------
# L11 OTP
# ---------------------------------------------------------------------------

def _l11(gd: Path) -> None:
    p = gd / "L11_OTP_CONTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    d["otp_present"] = True
    d["notes"] = (
        "The UID is the primary irreversible identification field. UID0 = 0x04 "
        "binds the chip to NXP; the manufacturer byte cannot be altered "
        "post-fabrication. For RID variants, UID1..UID3 are randomised per POR "
        "and the persistent identity must be obtained via GetUID under a T=CL "
        "authenticated session. AN10833 recommends GetVersion (where supported) "
        "over ATQA/SAK for exact identification because SAK values may be re-used.")
    d.setdefault("non_otp_card_state",
        "Layer-3-volatile state — current PICC state, T=CL block-number counter, "
        "CID assignment, FSCI/FWI negotiated session, application-layer "
        "authentication session keys — all lost when carrier is removed.")
    d.setdefault("otp_summary",
        "PICC UID + ATQA + SAK + ATS are factory-programmed into the IC's OTP "
        "region during wafer/package test and are immutable thereafter (with the "
        "exception of Random ID (RID) variants). Together these fields form a "
        "deterministic identification fingerprint per AN10833.")
    d.setdefault("otp_registers", [
        {"name": "UID", "width_bits": "32 / 56 / 80 (4 / 7 / 10 bytes)",
         "factory_programmed": True, "host_programmable": False,
         "fields": [
            {"name": "Manufacturer Byte (UID0)", "bytes": "0", "size_bits": 8,  "description": "ISO 7816-6 (0x04 = NXP)."},
            {"name": "Serial (UID1..UID3)",       "bytes": "1..3", "size_bits": 24, "description": "Per-chip serial."},
            {"name": "Serial extension (7B UID)", "bytes": "4..6", "size_bits": 24, "description": "For double-size UID."},
            {"name": "Serial extension (10B UID)","bytes": "7..9", "size_bits": 24, "description": "For triple-size UID."},
         ],
         "exception_random_id": "When UID0 = 0x08, UID1..UID3 are randomised per POR."},
        {"name": "ATQA", "width_bits": 16, "factory_programmed": True, "host_programmable": False},
        {"name": "SAK",  "width_bits": 8,  "factory_programmed": True, "host_programmable": False},
        {"name": "ATS (Layer 4)", "width_bits": "8 × TL (variable)",
         "factory_programmed": "mostly", "host_programmable": "no (over RF)"},
    ])
    _write(p, d)


# ---------------------------------------------------------------------------
# L12 behavioral sequences
# ---------------------------------------------------------------------------

def _l12(gd: Path) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("initialization_sequence", [
        "1. PCD turns on antenna driver; ≥ 5 ms guard time allows PICC POR + OTP load.",
        "2. PCD transmits REQA (0x26, 7-bit short frame).",
        "3. PICC in IDLE replies ATQA (2 bytes LSB-first).",
        "4. PCD enters Cascade Level 1 with SEL = 0x93, NVB = 0x20.",
        "5. PICC(s) reply UID-CL1[0..3] + BCC; PCD resolves bit collisions.",
        "6. PCD transmits full SELECT (NVB = 0x70 + UID-CL1 + BCC + CRC_A).",
        "7. If SAK b3 = 1, repeat at CL2 (SEL = 0x95) and possibly CL3 (SEL = 0x97).",
        "8. PCD now has the complete UID + final SAK.",
        "9. (If SAK b6 = 1) PCD transmits RATS → PICC replies ATS.",
        "10. (Optional) PCD transmits PPS to negotiate higher bit rate.",
        "11. PCD waits SFGT before first I-Block.",
        "12. PCD is in T_CL_ACTIVE and can carry application APDUs.",
    ])
    d.setdefault("anti_collision_loop_sequence", [
        "1. NVB = 0x20 (0 full bytes, 0 additional bits).",
        "2. PCD sends SEL + NVB.",
        "3. PICCs reply with bits beyond NVB.",
        "4. If no collision: PICCs converge; PCD reads UID + BCC.",
        "5. If collision at bit k: PCD chooses bit-k value and updates NVB.",
        "6. Repeat until NVB = 0x70.",
        "7. PCD sends final SELECT → PICC replies SAK.",
    ])
    d.setdefault("type_b_initialization_sequence", [
        "1. PCD turns on antenna; ≥ 5 ms PICC POR guard.",
        "2. PCD transmits REQB (0x05 + AFI + PARAM + CRC_B).",
        "3. PICC(s) randomly pick slot k ∈ [0, N-1].",
        "4. PCD transmits Slot-MARKER for k = 1..N-1.",
        "5. PICC in matching slot replies ATQB (12 bytes).",
        "6. PCD transmits ATTRIB to select a specific PICC.",
        "7. PCD now in T=CL active.",
    ])
    d.setdefault("rats_ats_sequence", [
        "1. PCD verifies SAK b6 = 1.",
        "2. PCD transmits RATS (0xE0 + PARAM + CRC_A).",
        "3. PICC replies ATS.",
        "4. PCD extracts FSC, FWT, SFGT, DS/DR.",
        "5. PCD waits ≥ SFGT before first I-Block.",
    ])
    d.setdefault("i_block_round_trip_sequence", [
        "1. PCD assembles APDU into I-Block payload.",
        "2. PCD computes CRC_A; sets PCB.b1 = N_PCD.",
        "3. PCD transmits I-Block.",
        "4. PICC validates and replies I-Block (block number = N_PICC).",
        "5. PCD validates; toggles N_PCD for next exchange.",
        "6. If PICC needs more time, S(WTX) → PCD extends FWT.",
        "7. If PICC error, no reply within FWT → PCD retransmits R(NAK).",
    ])
    d.setdefault("halt_sequence", [
        "1. PCD transmits HLTA (0x50 0x00 + CRC_A).",
        "2. PICC silently transitions ACTIVE → HALT.",
        "3. PCD verifies by REQA — no reply.",
        "4. PCD uses WUPA for re-engagement or continues anti-collision.",
    ])
    d.setdefault("deselect_sequence_layer_4", [
        "1. PCD transmits S(DESELECT) (PCB = 0xC2 + CRC_A).",
        "2. PICC replies S(DESELECT) ack and transitions to HALT.",
        "3. PCD may turn off field or re-enumerate.",
    ])
    d.setdefault("wtx_sequence_layer_4", [
        "1. PICC needs more than FWT.",
        "2. PICC transmits S(WTX) with WTXM 1..59.",
        "3. PCD acknowledges with same WTXM.",
        "4. PCD extends FWT to WTXM × FWT for this exchange.",
        "5. PICC must respond within extended FWT.",
    ])
    d.setdefault("get_version_command_sequence_layer_4_application", [
        "1. PCD transmits I-Block carrying APDU 0x60 GetVersion.",
        "2. PICC computes 7-byte GetVersion response.",
        "3. PICC replies I-Block with VendorID + HW_ProductType + HW_ProductSubType + HW_Major + HW_Minor + HW_StorageSize + HW_Protocol.",
        "4. PCD parses byte 2 HW_ProductType.",
        "5. (Optional) PCD chains for software version block.",
    ])
    d.setdefault("multi_picc_enumeration_sequence", [
        "1. PCD polls with REQA.",
        "2. Anti-collision selects first PICC; PCD records UID_1 + SAK_1.",
        "3. PCD transmits HLTA to PICC_1.",
        "4. PCD polls with WUPA.",
        "5. PICCs in field (excluding PICC_1) reply ATQA.",
        "6. Anti-collision selects next PICC; loop repeats.",
        "7. Loop terminates when no PICC replies to WUPA.",
    ])
    d.setdefault("field_loss_recovery_sequence", [
        "1. PCD detects loss of envelope.",
        "2. PCD aborts pending T=CL exchange.",
        "3. On field-restoration, PCD restarts at REQA.",
    ])
    _write(p, d)


# ---------------------------------------------------------------------------
# L13 lab calibration
# ---------------------------------------------------------------------------

def _l13(gd: Path) -> None:
    p = gd / "L13_LAB_CALIBRATION.json"
    if not p.is_file():
        return
    d = _read(p)
    d["lab_calibration_present"] = True
    d["notes"] = (
        "Conformance per ISO 10373-6 requires the calibrated PCD to be tested "
        "against a complete suite of reference PICCs at multiple positions in "
        "the operating volume; AN10833 identification is checked against each "
        "expected ATQA/SAK/GetVersion response. Most PCD reader chips expose "
        "vendor-specific calibration registers (TxControl, RxThreshold, "
        "ModWidth, RFCfg) written from the host MCU.")
    d.setdefault("calibration_summary",
        "Calibration in ISO 14443 is split between PCD-side analog calibration "
        "(antenna tuning, transmit/receive level, EMC) and PCD-side timing "
        "calibration (carrier frequency, FDT). The PICC itself is intentionally "
        "not calibrated by the PCD; it self-trims internally at wafer probe. "
        "ISO 10373-6 defines the normative compliance test method.")
    d.setdefault("pcd_antenna_tuning", {
        "purpose": "Tune the PCD antenna's LC tank to 13.56 MHz under PCB stack-up.",
        "procedure": [
            "1. Probe with network analyzer; measure S11 around 13.56 MHz.",
            "2. Adjust matching network capacitors; achieve VSWR ≤ 1.5:1.",
            "3. Q-factor target: PCD Q ≈ 30..40.",
            "4. Verify Hmin = 1.5 A/m at maximum operating distance.",
        ],
    })
    d.setdefault("pcd_field_strength_calibration", {
        "purpose": "Set PCD transmit power so field at operating volume is in [1.5, 7.5] A/m.",
        "instrument": "ISO 10373-6 Calibration Coil Antenna (single-turn 30 × 30 mm)",
        "procedure": [
            "1. Place calibration coil at reference position.",
            "2. Measure induced voltage; compute H.",
            "3. Adjust PCD TX amplifier output.",
            "4. Verify modulation envelope shape.",
        ],
    })
    d.setdefault("pcd_to_picc_timing_calibration", {
        "purpose": "Ensure PCD modulation pause + rise/fall comply with ISO 14443-2.",
        "instrument": "RF logic analyser with envelope detector + scope ≥ 100 MHz",
        "type_a_targets": {
            # Carry the (min)/(max) qualifier text so the parity gate keeps
            # alignment with the AN10833 lab-procedure wording.
            "pause_duration_us": "2.0 (min) .. 3.0 (max)",
            "rise_time_us": "≤ 0.5",
            "fall_time_us": "≤ 0.5",
            "modulation_depth": "100%",
        },
        "type_b_targets": {
            "rise_time_us": "≤ 2.0",
            "fall_time_us": "≤ 2.0",
            "modulation_depth": "8-14% (nominal 10%)",
        },
    })
    d.setdefault("picc_to_pcd_load_modulation_calibration", {
        "purpose": "Verify PICC subcarrier amplitude is detectable at the PCD's RX path.",
        "procedure": [
            "1. Place a reference PICC at min/mid/max-coupling positions.",
            "2. Capture envelope at the PCD's RX path with subcarrier.",
            "3. Measure subcarrier amplitude.",
            "4. Run anti-collision; verify UID extraction.",
        ],
    })
    d.setdefault("carrier_frequency_calibration", {
        "purpose": "PCD carrier shall be 13.56 MHz ± 517 ppm.",
        "instrument": "Frequency counter referenced to GPS/OCXO",
        "procedure": [
            "1. Transmit unmodulated carrier; count frequency.",
            "2. If outside ± 7 kHz, swap crystal or adjust load caps.",
        ],
    })
    d.setdefault("fdt_listen_timing_check", {
        "purpose": "Verify PICCs respond within fdt_listen ≤ 86.43 μs at 106 kbps.",
        "procedure": [
            "1. Capture (PCD command EOF) → (PICC response SOF) interval.",
            "2. Sweep across operating volume.",
            "3. All conforming PICCs shall meet fdt_listen.",
        ],
    })
    d.setdefault("no_picc_side_trim",
        "The PICC does not expose any calibration register on the air interface "
        "— its antenna-resonance trim caps + analog front-end trim are programmed "
        "at wafer probe and permanent.")
    _write(p, d)


# ---------------------------------------------------------------------------
# L14 versioning
# ---------------------------------------------------------------------------

def _l14(gd: Path) -> None:
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if not p.is_file():
        return
    d = _read(p)
    f = d.get("fields") or {}
    f.setdefault("spec_version",
        "NXP Application Note AN10833 'MIFARE type identification procedure' "
        "Rev. 3.8 (10 January 2023). References ISO/IEC 14443-1/-2/-3/-4 "
        "(most-recently 2018 / 2020).")
    if _empty(f.get("spec_lineage_an10833")):
        f["spec_lineage_an10833"] = [
            {"version": "3.8", "date": "20230110", "summary": "Correction of Figure 1."},
            {"version": "3.7", "date": "20210810", "summary": "Addition of DESFire EV3 / DESFire Light; restructure around GetVersion."},
            {"version": "3.6", "date": "20160711", "summary": "Update for MIFARE Plus EV1."},
            {"version": "3.5", "date": "20140327", "summary": "Update for multi-MIFARE / UICC."},
            {"version": "3.4", "date": "20121029", "summary": "Update for implementation in a device."},
            {"version": "3.3", "date": "20110928", "summary": "Update for TNP3xxx."},
            {"version": "3.2", "date": "20110829", "summary": "Update for 7-byte UID Classic."},
            {"version": "3.1", "date": "20090707", "summary": "Correction of Table 12."},
            {"version": "3",   "date": "20090518", "summary": "Third release."},
        ]
    if _empty(f.get("spec_lineage_iso_14443")):
        f["spec_lineage_iso_14443"] = [
            {"version": "ISO/IEC 14443-1 (Physical characteristics)", "summary": "Defines proximity card physical dimensions, durability."},
            {"version": "ISO/IEC 14443-2 (RF interface)",              "summary": "Defines 13.56 MHz carrier + Type A/B modulation."},
            {"version": "ISO/IEC 14443-3 (Initialization + anticollision)", "summary": "Defines REQA/WUPA, anti-collision, SELECT, SAK, HLTA."},
            {"version": "ISO/IEC 14443-4 (Transmission protocol)",     "summary": "Defines T=CL — RATS/ATS/PPS, I/R/S-Block, FSCI/FWI."},
        ]
    if _empty(f.get("backward_compat_traps")):
        f["backward_compat_traps"] = [
            {"trap_name": "atqa_alone_ambiguity",       "rule": "ATQA alone is not sufficient. 0x00 0x44 is shared.",                       "trap": "Mis-identify cross-family variants."},
            {"trap_name": "sak_alone_ambiguity",         "rule": "SAK = 0x08 is shared between Classic 1K and Plus SL1.",                  "trap": "Wrong command set selection."},
            {"trap_name": "future_sak_reuse",            "rule": "SAK RFU bits may be re-used by future chips.",                            "trap": "Hard-coded SAK classifier silently breaks."},
            {"trap_name": "get_version_not_on_legacy",   "rule": "Legacy Classic / Ultralight (non-EV1) lack GetVersion.",                  "trap": "Must fall back to ATQA/SAK."},
            {"trap_name": "uid_4_byte_legacy",           "rule": "Pre-2010 Classic 1K used 4-byte UID; post may use 7-byte UID.",          "trap": "Buffer overflow on 7-byte UID."},
            {"trap_name": "rats_on_layer3_only_picc",   "rule": "Host shall not send RATS to SAK b6 = 0 PICC.",                            "trap": "PICC behavior undefined."},
            {"trap_name": "type_b_distinct_command_set","rule": "Type B uses REQB/WUPB/ATTRIB/HLTB.",                                       "trap": "Type-A-only PCD misses Type B PICCs."},
            {"trap_name": "random_id_uid_unstable",      "rule": "UID0 = 0x08 → UID randomised per POR.",                                   "trap": "App using UID as session ID fails."},
        ]
    if _empty(f.get("key_changes")):
        f["key_changes"] = [
            {"version": "AN10833 Rev. 3.2 (2011)", "summary": "7-byte UID variant of MIFARE Classic 1K/4K; CL2 required."},
            {"version": "AN10833 Rev. 3.6 (2016)", "summary": "MIFARE Plus EV1; SAK 0x10/0x11 for Plus SL2."},
            {"version": "AN10833 Rev. 3.7 (2021)", "summary": "Restructured around GetVersion; byte 2 product type table."},
        ]
    f.setdefault("version_naming_history_note",
        "Identification doctrine has evolved across AN10833 revisions: through "
        "Rev. 3.6 the canonical decision flow was 'ATQA + SAK → family'. Rev. "
        "3.7 (2021) introduced GetVersion as the recommended primary "
        "identification command for newer chips because (a) SAK bit values may "
        "be re-used in future products, (b) ATQA and SAK are coarse, (c) "
        "GetVersion deterministically reveals product type + storage size + "
        "protocol version.")
    d["fields"] = f
    _write(p, d)


# ---------------------------------------------------------------------------
# L15 encoding tables
# ---------------------------------------------------------------------------

def _l15(gd: Path) -> None:
    p = gd / "L15_ENCODING_TABLES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = d.get("fields") or {}
    f.setdefault("short_frame_table_type_a", {
        "header_columns": ["Command", "Hex", "Bits", "Wakes HALT?", "Reply"],
        "rows": [
            ["REQA", "0x26", "7",  "no",  "ATQA (16 bits)"],
            ["WUPA", "0x52", "7",  "yes", "ATQA (16 bits)"],
        ],
    })
    f.setdefault("select_cascade_level_table_type_a", {
        "header_columns": ["Cascade Level", "SEL hex", "Purpose"],
        "rows": [
            ["CL1", "0x93", "Anti-collision / SELECT for UID-CL1"],
            ["CL2", "0x95", "Anti-collision / SELECT for UID-CL2"],
            ["CL3", "0x97", "Anti-collision / SELECT for UID-CL3"],
        ],
    })
    f.setdefault("atqa_format_table", {
        "header_columns": ["Bit position (byte1.byte2)", "Field", "Description"],
        "rows": [
            ["1.b1-b5",  "AC bitmap",   "Bit-frame anti-collision support bitmap"],
            ["1.b6",     "RFU",         "Reserved"],
            ["1.b7-b8",  "UID size",    "00 = single, 01 = double, 10 = triple, 11 = RFU"],
            ["2.b1-b4",  "Proprietary", "Vendor classification"],
            ["2.b5-b8",  "RFU",         "Reserved"],
        ],
    })
    f.setdefault("atqa_common_values_table", {
        "header_columns": ["ATQA (byte 1 byte 2 hex)", "UID size", "Family hint"],
        "rows": [
            ["0x00 0x04", "4 byte", "MIFARE Classic 1K / MIFARE Plus SL1 2K/SE"],
            ["0x00 0x02", "4 byte", "MIFARE Classic 4K / MIFARE Plus SL1 4K"],
            ["0x00 0x44", "7 byte", "MIFARE Ultralight family / NTAG21x"],
            ["0x03 0x44", "7 byte", "MIFARE DESFire (EV1/EV2/EV3) / DESFire Light"],
            ["0x00 0x42", "7 byte", "MIFARE Plus SL3"],
        ],
    })
    f.setdefault("sak_bit_meaning_table", {
        "header_columns": ["Bit", "Field", "Meaning when 1"],
        "rows": [
            ["b1", "Proprietary",          "NXP variant encoding"],
            ["b2", "RFU",                  "Reserved"],
            ["b3", "UID not complete",     "Cascade Tag follows"],
            ["b4", "Proprietary",          "NXP variant / capacity"],
            ["b5", "RFU",                  "Reserved"],
            ["b6", "ISO 14443-4 compliant","PICC supports T=CL"],
            ["b7", "RFU",                  "Reserved"],
            ["b8", "RFU",                  "Reserved"],
        ],
    })
    f.setdefault("sak_common_values_table", {
        "header_columns": ["SAK hex", "Meaning"],
        "rows": [
            ["0x00", "MIFARE Ultralight / NTAG — no T=CL"],
            ["0x04", "UID not complete"],
            ["0x08", "MIFARE Classic 1K / MIFARE Plus SL1 2K/SE"],
            ["0x10", "MIFARE Plus SL2 2K"],
            ["0x11", "MIFARE Plus SL2 4K"],
            ["0x18", "MIFARE Classic 4K / MIFARE Plus SL1 4K"],
            ["0x20", "ISO 14443-4 compliant"],
            ["0x28", "ISO 14443-4 + UID not complete"],
        ],
    })
    f.setdefault("manufacturer_byte_table_iso_7816_6", {
        "header_columns": ["UID0 hex", "Manufacturer"],
        "rows": [
            ["0x02", "Atmel"],
            ["0x04", "NXP Semiconductors"],
            ["0x05", "Infineon Technologies"],
            ["0x07", "STMicroelectronics"],
            ["0x08", "Random ID (privacy mode)"],
            ["0x16", "EM Microelectronic-Marin SA"],
            ["0x28", "AT&T / Bell"],
            ["0x33", "AMIC Technology"],
        ],
    })
    f.setdefault("cascade_tag_table", {
        "header_columns": ["Byte", "Value", "Description"],
        "rows": [
            ["UID-CL1[0]", "0x88", "Cascade Tag for 7- or 10-byte UID"],
            ["UID-CL2[0]", "0x88", "Cascade Tag for 10-byte UID"],
            ["UID-CL3[0]", "actual UID byte", "Final cascade level"],
        ],
    })
    f.setdefault("crc_polynomial_table", {
        "header_columns": ["CRC", "Polynomial", "Init", "Final XOR", "Reflected", "Coverage"],
        "rows": [
            ["CRC_A", "x^16+x^12+x^5+1 (0x8408 reflected)", "0x6363", "—",      "yes", "ISO 14443-3 Type A standard frames + T=CL"],
            ["CRC_B", "x^16+x^12+x^5+1 (0x8408 reflected)", "0xFFFF", "0xFFFF", "yes", "ISO 14443-3 Type B frames + T=CL"],
        ],
    })
    f.setdefault("bit_rate_table", {
        "header_columns": ["Rate kbps", "Divider (1/fc)", "ETU (µs)", "Subcarrier (kHz)"],
        "rows": [
            ["106", "128",  "9.44", "847.5"],
            ["212", "64",   "4.72", "847.5"],
            ["424", "32",   "2.36", "847.5"],
            ["848", "16",   "1.18", "847.5"],
        ],
    })
    f.setdefault("fsci_to_fsc_table", {
        "header_columns": ["FSCI", "Max Frame Size FSC (bytes)"],
        "rows": [
            ["0", "16"], ["1", "24"], ["2", "32"], ["3", "40"], ["4", "48"],
            ["5", "64"], ["6", "96"], ["7", "128"], ["8", "256"], ["9-15", "RFU"],
        ],
    })
    f.setdefault("fwi_to_fwt_table_ms", {
        "header_columns": ["FWI", "FWT (ms)"],
        "rows": [
            ["0",  "0.302"], ["1",  "0.604"], ["2",  "1.21"], ["3",  "2.42"],
            ["4",  "4.83"], ["5",  "9.66"], ["6",  "19.3"], ["7",  "38.6"],
            ["8",  "77.3"], ["9",  "154.6"], ["10", "309.2"], ["11", "618.4"],
            ["12", "1236.8"], ["13", "2473.5"], ["14", "4949.0"], ["15", "RFU"],
        ],
    })
    f.setdefault("get_version_byte_2_product_type_table", {
        "header_columns": ["Byte 2 (HW Product Type) hex", "Product family"],
        "rows": [
            ["0xX1", "MIFARE DESFire"],
            ["0xX2", "MIFARE Plus"],
            ["0xX3", "MIFARE Ultralight"],
            ["0xX4", "NTAG"],
            ["0xX5", "(reserved by NXP)"],
            ["0xX6", "(reserved by NXP)"],
            ["0xX7", "NTAG I2C"],
            ["0xX8", "MIFARE DESFire Light"],
        ],
    })
    f.setdefault("pcb_t_cl_block_classifier_table", {
        "header_columns": ["PCB pattern", "Block kind", "Notes"],
        "rows": [
            ["0b000c0010", "I-Block",      "c = CID present, low bit = block number"],
            ["0b1010c01n", "R(ACK)",       "Positive ack"],
            ["0b1011c01n", "R(NAK)",       "Negative ack — request retransmission"],
            ["0b1100c010", "S(DESELECT)",  "PCD requests PICC to release T=CL session"],
            ["0b1111c010", "S(WTX)",       "PICC requests additional wait time"],
        ],
    })
    f.setdefault("type_b_command_table", {
        "header_columns": ["Command", "Header hex", "Reply"],
        "rows": [
            ["REQB / WUPB", "0x05 + AFI + PARAM", "ATQB (12 bytes)"],
            ["ATTRIB",      "0x1D + PUPI + ...",  "PCD-PICC parameter selection"],
            ["HLTB",        "0x50 + PUPI",        "HLTB ack"],
        ],
    })
    if _empty(f.get("tables")):
        f["tables"] = [
            "Table 1 — Abbreviations (REQA, WUPA, ATQA, SAK, UID, CT, RID, NUID)",
            "Table 2 — GetVersion response byte 2 (HW/Product Type) meaning",
            "Table 3..6 — ATQA + SAK for MIFARE Classic / Plus / Ultralight / DESFire family",
            "Table 7 — Cascade Level coverage per UID size",
            "Table 8 — Forbidden combinations (e.g. SAK bit 5 RFU)",
            "Table 9 — Common SAK values cross-reference",
            "Table 10 — Manufacturer Byte (ISO 7816-6 IC Manufacturer ID code list)",
            "Figure 1 — MIFARE type identification decision tree",
            "Figure 2 — ATQA bit layout",
            "Figure 3 — Anti-collision loop as part of card activation",
        ]
    d["fields"] = f
    _write(p, d)


# ---------------------------------------------------------------------------
# L16 compliance
# ---------------------------------------------------------------------------

def _l16(gd: Path) -> None:
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = d.get("fields") or {}
    f.setdefault("must_have_properties", [
        "PCD shall transmit at 13.56 MHz ± 517 ppm with field strength 1.5 ≤ H ≤ 7.5 A/m.",
        "PCD shall use 100% ASK Modified Miller for Type A at 106 kbps.",
        "PCD shall use 10% ASK NRZ-L for Type B.",
        "PICC shall load-modulate the 847.5 kHz subcarrier with Manchester (Type A) or BPSK (Type B).",
        "Every Type A standard frame shall protect each byte with one odd-parity bit and the whole frame with CRC_A.",
        "PICC shall answer REQA / WUPA with ATQA within fdt_listen ≤ 86.43 μs.",
        "PCD anti-collision loop shall be bit-frame at CL1/CL2/CL3 with SEL = 0x93/0x95/0x97.",
        "Cascade Tag 0x88 shall appear in UID-CLn[0] of every non-final Cascade Level.",
        "BCC at each CL shall be UID-CLn[0] XOR UID-CLn[1] XOR UID-CLn[2] XOR UID-CLn[3].",
        "Final SELECT (NVB = 0x70) shall be followed by SAK + CRC_A.",
        "SAK b3 = 1 shall indicate UID-CLn[0] was the Cascade Tag.",
        "SAK b6 = 1 shall indicate ISO 14443-4 compliance.",
        "PICC shall transition to HALT on receipt of HLTA.",
        "Layer 4 RATS (0xE0) shall be followed by ATS reply.",
        "Layer 4 FWT shall obey FWT = (256 × 16 / fc) × 2^FWI.",
        "T=CL block format shall use PCB + CID (optional) + NAD (optional) + INF + CRC_A.",
        "T=CL block number shall alternate 0/1 per direction.",
        "GetVersion shall be supported on Ultralight EV1 / Plus EV1/EV2 / DESFire EV2/EV3 / DESFire Light.",
    ])
    f.setdefault("must_not_have_properties", [
        "PCD shall not transmit RATS to a PICC whose SAK b6 = 0.",
        "PICC shall not respond to REQA while in HALT.",
        "PICC shall not respond with malformed CRC_A / CRC_B.",
        "PICC shall not respond if Type A byte parity is incorrect.",
        "Two PICCs shall not transmit simultaneously on the same subcarrier slot post-anti-collision.",
        "PCD shall not exceed PICC's FSCI-advertised frame size.",
        "PCD shall not declare communication failure before FWT has elapsed.",
        "PICC shall not transition out of T_CL_ACTIVE except via S(DESELECT) or carrier removal.",
        "Application above Layer 3 shall not be invoked on a PICC that has not completed SELECT.",
    ])
    f.setdefault("compliance_failure_modes", [
        {"mode": "Parity error (Type A)",            "trigger": "PICC silently ignores frame; PCD detects via timeout."},
        {"mode": "CRC_A / CRC_B mismatch",            "trigger": "PICC silently ignores; PCD retries."},
        {"mode": "BCC mismatch at anti-collision",   "trigger": "PCD detects via XOR check."},
        {"mode": "Bit collision during AC",           "trigger": "PCD detects collision bit position; bisects."},
        {"mode": "PICC HALT after HLTA",              "trigger": "PICC silent on REQA; PCD uses WUPA next."},
        {"mode": "T=CL block number desync",          "trigger": "PCD/PICC replies R(NAK); retransmits."},
        {"mode": "FWT timeout",                       "trigger": "PCD waits beyond FWT; declares Layer 4 error."},
        {"mode": "Carrier removal",                   "trigger": "Total state loss in PICC."},
        {"mode": "RATS to non-T=CL PICC",             "trigger": "PCD violation — PICC behavior undefined."},
        {"mode": "GetVersion not supported",          "trigger": "Legacy PICC returns NAK; PCD falls back."},
    ])
    f.setdefault("reset_behavior_compliance",
        "On loss of carrier (envelope below POR threshold for > 1 ms), PICC "
        "enters POWER_OFF; all state lost. On re-entering field, PICC POR "
        "completes within ≤ 5 ms and PICC enters IDLE.")
    f.setdefault("min_clock_constraint",
        "PCD shall maintain unmodulated 13.56 MHz carrier whenever any PICC is "
        "expected to remain in field; minimum continuous carrier presence "
        "between commands is implementation-defined but typically ≥ 1 ms.")
    f.setdefault("iso_10373_6_compliance_summary",
        "Normative compliance tests against ISO 14443 are documented in "
        "ISO/IEC 10373-6 (PCD field strength + modulation envelope + subcarrier "
        "sensitivity + bit-error rate + anti-collision throughput + FWT "
        "measurement). AN10833 itself is non-normative — it documents the "
        "deterministic identification surface within the ISO 14443 envelope.")
    d["fields"] = f
    _write(p, d)


# ---------------------------------------------------------------------------
# L17 channel signal catalog
# ---------------------------------------------------------------------------

def _l17(gd: Path) -> None:
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if not p.is_file():
        return
    d = _read(p)
    f = d.get("fields") or {}
    f["channels"] = [
        {"name": "RF Carrier (13.56 MHz)",     "direction": "PCD → field; PICC receives via inductive coupling", "purpose": "Continuous unmodulated 13.56 MHz carrier that powers the PICC and serves as the synchronous clock reference.", "active_levels": "Field strength 1.5..7.5 A/m at operating volume", "idle_level": "Continuous unmodulated carrier"},
        {"name": "PCD→PICC modulation",        "direction": "PCD → PICC", "purpose": "Carries 7-bit short frames, standard frames, and anti-collision bit-frames as envelope changes.", "active_levels": "100% ASK Modified Miller (Type A) or 10% ASK NRZ-L (Type B)", "idle_level": "Unmodulated carrier"},
        {"name": "PICC→PCD load modulation",   "direction": "PICC → PCD", "purpose": "Carries ATQA, UID-CLn+BCC, SAK, ATS, T=CL replies as 847.5 kHz subcarrier sidebands.", "active_levels": "Subcarrier amplitude ≥ 22 / sqrt(H) mV", "idle_level": "No subcarrier"},
        {"name": "PCD Host Bus (SPI/I2C/UART)","direction": "host MCU ↔ PCD chip", "purpose": "Application path between host MCU and PCD chip.", "active_levels": "Per host-bus convention", "idle_level": "Per host bus convention"},
        {"name": "PCD IRQ",                    "direction": "PCD chip → host MCU", "purpose": "Asynchronous interrupt indicating frame received / TX complete / error.", "active_levels": "Active LOW (typ)", "idle_level": "Inactive HIGH"},
        {"name": "PCD NRSTPD",                 "direction": "host MCU → PCD chip", "purpose": "Reset / power-down control.", "active_levels": "Active LOW = reset", "idle_level": "HIGH"},
    ]
    f["power_pins"] = [
        {"name": "PCD AVDD",                "purpose": "Analog supply for PCD oscillator / modulator / RX (typ 3.3 V)."},
        {"name": "PCD DVDD",                "purpose": "Digital supply for PCD logic (typ 3.3 V or 1.8 V)."},
        {"name": "PCD PVDD",                "purpose": "Pad / antenna driver supply."},
        {"name": "PCD AVSS / DVSS / PVSS",  "purpose": "Grounds."},
        {"name": "PICC LA / LB",            "purpose": "PICC antenna coil terminals; no external VCC pin."},
    ]
    f["global_signals"] = [
        {"name": "13.56 MHz RF carrier", "purpose": "Shared synchronous time base for PCD-PICC system."},
    ]
    f["channel_counts"] = {
        "air_interface_carriers": 1,
        "air_interface_subcarriers": 1,
        "picc_air_pins": 2,
        "pcd_antenna_driver_pins": 2,
        "pcd_rx_pins": 1,
        "pcd_host_bus_pins_spi": 4,
        "pcd_host_bus_pins_i2c": 2,
        "pcd_irq_pins": 1,
        "pcd_reset_pins": 1,
    }
    f["type_a_vs_type_b_pin_aliases"] = [
        {"role": "PCD→PICC modulation", "type_a_form": "100% ASK Modified Miller", "type_b_form": "10% ASK NRZ-L"},
        {"role": "PICC→PCD response",   "type_a_form": "847.5 kHz subcarrier Manchester", "type_b_form": "847.5 kHz subcarrier BPSK"},
        {"role": "Polling command",     "type_a_form": "REQA (0x26, 7-bit short)", "type_b_form": "REQB (0x05+AFI+PARAM)"},
        {"role": "Polling reply",       "type_a_form": "ATQA (2 bytes)",          "type_b_form": "ATQB (12 bytes)"},
        {"role": "Selection command",   "type_a_form": "SELECT cascade",          "type_b_form": "ATTRIB"},
        {"role": "Halt command",        "type_a_form": "HLTA",                     "type_b_form": "HLTB"},
    ]
    f["ordering_rules"] = {
        "byte_ordering_on_wire_type_a": "Bytes in protocol order; bits LSB-first; one odd-parity bit per byte.",
        "byte_ordering_on_wire_type_b": "Bytes in protocol order; bits LSB-first; start bit + 8 data + stop bit + 2-ETU EGT.",
        "atqa_byte_order":              "Byte 1 LSB-first then byte 2 LSB-first.",
        "uid_byte_order":               "UID-CL1[0] first (CT = 0x88 if not final).",
        "crc_a_byte_order":             "CRC_A[7:0] first, then CRC_A[15:8].",
        "crc_b_byte_order":             "CRC_B[7:0] first, then CRC_B[15:8].",
    }
    f["dependency_graph"] = {
        "common_rule":   "PCD transmits the carrier continuously; PICC powers itself from the carrier and replies only within fdt_listen of a recognised PCD command. There is no PICC-initiated traffic.",
        "data_dependency": "PCD command framing depends on the current PICC state. Anti-collision depends on bitwise PICC replies. Layer 4 traffic depends on a successful RATS/ATS handshake.",
    }
    f["handshake_pairs"] = [
        {"name": "REQA_ATQA",     "from": "PCD",         "to": "PICC", "rule": "PCD REQA (7-bit) → PICC ATQA (16-bit) within fdt_listen."},
        {"name": "AC_SELECT",     "from": "PCD",         "to": "PICC", "rule": "PCD SEL+NVB → PICC UID-CLn+BCC. Full SELECT → SAK + CRC_A."},
        {"name": "RATS_ATS",      "from": "PCD",         "to": "PICC", "rule": "PCD RATS → PICC ATS within FWT."},
        {"name": "T_CL_I_BLOCK",  "from": "PCD & PICC",  "to": "both", "rule": "Alternating-block-number round-trips carrying APDU."},
        {"name": "HLTA",          "from": "PCD",         "to": "PICC", "rule": "PCD HLTA → PICC silent ACK → HALT."},
        {"name": "S_DESELECT",    "from": "PCD",         "to": "PICC", "rule": "PCD S(DESELECT) → PICC S(DESELECT) ACK → HALT."},
    ]
    d["fields"] = f
    _write(p, d)


# ---------------------------------------------------------------------------
# L18 interconnect topology
# ---------------------------------------------------------------------------

def _l18(gd: Path) -> None:
    p = gd / "L18_INTERCONNECT_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = d.get("fields") or {}
    f["topology_type"] = (
        "Single PCD (master, field-generator) + 1..N PICCs (slaves, "
        "field-powered) sharing a single 13.56 MHz inductively-coupled RF "
        "channel. PICCs are anti-collision-resolved by UID (Type A) or PUPI "
        "(Type B). After Layer 3 SELECT, exactly one PICC is in ACTIVE state; "
        "remaining PICCs can be HALTed.")
    f["supported_topologies"] = [
        {"name": "Single PCD + single PICC",         "description": "Most common case."},
        {"name": "Single PCD + multiple PICCs",      "description": "Anti-collision enumerates all PICCs."},
        {"name": "Single PCD + Type A + Type B mix", "description": "PCD alternates REQA and REQB."},
        {"name": "Co-located PCDs",                  "description": "Only one PCD field active at a time."},
        {"name": "NFC peer-to-peer (NFCIP-1)",       "description": "Out of ISO 14443 scope."},
    ]
    f["master_slave_role_summary"] = [
        {"role": "PCD (master)", "description": "Generates field; transmits all commands; controls bit rate."},
        {"role": "PICC (slave)", "description": "Field-powered; replies only when polled; load-modulates subcarrier."},
    ]
    f["interconnect_role"] = (
        "No protocol-layer interconnect (no router / bridge). The 13.56 MHz "
        "field is the flat 1-PCD : N-PICC channel; Layer 3 addresses by UID; "
        "Layer 4 addresses by CID.")
    f["ordering_guarantees"] = {
        "within_a_block": "Bits LSB-first per byte.",
        "across_blocks":  "Strictly sequential per direction at Layer 4; alternating block number detects lost block.",
    }
    f["memory_vs_peripheral_regions"] = (
        "No shared memory region on the air interface. PICC memory is layered "
        "above Layer 3/4 and addressed via family-specific command sets.")
    f.setdefault("default_signal_values_evidence_tables", [
        "Figure 1 — MIFARE type identification decision tree (AN10833)",
        "Figure 3 — Anticollision Loop as part of the Card Activation Sequence",
        "ISO 14443-3 §6.4 — Polling for proximity cards Type A",
        "ISO 14443-3 §7.4 — Polling for proximity cards Type B",
        "ISO 14443-4 §4-§7 — RATS, ATS, T=CL",
    ])
    f.setdefault("device_classification", {
        "pcd_reader_chip":       "NXP CLRC663 / PN5180 / PN512 / MFRC522 / TRF7970A / ST CR95HF.",
        "picc_chip_classic":     "MIFARE Classic 1K / 4K — Crypto1 above Layer 3; no T=CL.",
        "picc_chip_plus":        "MIFARE Plus 2K / 4K — SL1 / SL2 / SL3.",
        "picc_chip_desfire":     "MIFARE DESFire EV1/EV2/EV3 / DESFire Light.",
        "picc_chip_ultralight":  "MIFARE Ultralight / Ultralight C / Ultralight EV1.",
        "picc_chip_ntag":        "NTAG21x / NTAG I2C.",
        "picc_chip_jcop":        "JCOP smartcard — Java Card OS + ISO 7816-4 APDU.",
    })
    d["fields"] = f
    _write(p, d)


# ---------------------------------------------------------------------------
# L19 PDK constraints
# ---------------------------------------------------------------------------

def _l19(gd: Path) -> None:
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if not p.is_file():
        return
    d = _read(p)
    f = d.get("fields") or {}
    f.setdefault("constraints_present", False)
    f.setdefault("host_pcb_constraints_summary", [
        "PCD antenna: planar coil tuned to 13.56 MHz, Q ≈ 30..40, area ≈ 70 × 50 mm (Class 1).",
        "PCD matching network: LCL or T-network for VSWR ≤ 1.5:1 at 13.56 MHz.",
        "PCD EMC filter: low-pass at ~ 25 MHz; FCC Part 15 / ETSI EN 300 330.",
        "PCD power supply: separate AVDD/DVDD/PVDD rails with decoupling.",
        "PCD ESD protection: TVS diodes on antenna terminals.",
        "PCD crystal: 27.12 MHz ± 30 ppm.",
        "PCD layout: matched-length, short, shielded TX/RX traces.",
    ])
    f["notes"] = (
        "ISO/IEC 14443-2 defines the air-interface electrical envelope but does "
        "not specify host PCB layout or PDK timing constraints. PCD reader chip "
        "vendors publish reference designs. The PICC silicon side ships with "
        "vendor-specific design rules for the antenna-PICC interface.")
    f.setdefault("picc_internal_constraints",
        "PICC-internal silicon constraints (C_tune, rectifier V_drop, "
        "shunt-regulator clamp, modulation FET RDS_on) are vendor-specific and "
        "out of scope of AN10833. PICC analog-pad signoff is at LA / LB only.")
    d["fields"] = f
    _write(p, d)


# ---------------------------------------------------------------------------
# L20 DFT
# ---------------------------------------------------------------------------

def _l20(gd: Path) -> None:
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = d.get("fields") or {}
    f["dft_present"] = "partial"
    f.setdefault("exposed_dft_features", [
        {"name": "ATQA + SAK identification surface", "purpose": "Every PICC always exposes a deterministic fingerprint."},
        {"name": "ATS historical bytes",                "purpose": "Vendor-readable firmware revision + family code."},
        {"name": "GetVersion (Layer 4 application)",   "purpose": "7-byte HW/SW version block on newer PICCs."},
        {"name": "Card Detect via RF envelope",        "purpose": "PCD chip detects PICC presence via load-modulation."},
        {"name": "PCD collision-bit-position register","purpose": "Vendor-specific anti-collision debug."},
        {"name": "PCD CRC / parity / framing counters","purpose": "Vendor-specific protocol-error counters."},
    ])
    f["notes"] = (
        "ISO 14443 has no formal DFT / scan architecture exposed at the air "
        "interface. The protocol's identification surface (ATQA / SAK / UID / "
        "ATS / GetVersion) is itself the standard observability for a "
        "freshly-discovered PICC.")
    f.setdefault("no_jtag_on_air_interface",
        "There is no JTAG / scan / boundary-scan port on the PICC air "
        "interface. Internal scan + parametric tests happen only at wafer "
        "probe / package test.")
    d["fields"] = f
    _write(p, d)


# ---------------------------------------------------------------------------
# L21 power intent
# ---------------------------------------------------------------------------

def _l21(gd: Path) -> None:
    p = gd / "L21_POWER_INTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    f = d.get("fields") or {}
    f.setdefault("power_intent_present", True)
    pds = _ensure_dict(f, "power_domains_summary")
    pds.setdefault("PCD_AVDD",     "Analog supply for PCD oscillator / TX modulator / RX (typ 3.3 V).")
    pds.setdefault("PCD_DVDD",     "Digital supply for PCD logic (typ 3.3 V or 1.8 V).")
    pds.setdefault("PCD_PVDD",     "Pad / antenna driver supply (3.3 V to 5 V).")
    pds.setdefault("PCD_HOST_BUS_VDD", "Host bus I/O supply (3.3 V or 1.8 V).")
    pds.setdefault("PICC_VCC_INTERNAL","PICC field-rectified VCC (typ 1.8 V); generated on-chip — no external power pin.")
    f.setdefault("power_up_sequence", [
        "1. Host MCU applies AVDD / DVDD / PVDD to PCD chip.",
        "2. Host MCU releases NRSTPD.",
        "3. PCD chip boots in disabled / field-off state.",
        "4. Host MCU configures PCD chip.",
        "5. Host MCU commands PCD to turn on antenna driver.",
        "6. PCD waits ≥ 5 ms for any PICC POR before first REQA.",
        "7. PICC: rectifier output rises; internal POR releases at VCC ≥ 1.6 V.",
    ])
    f.setdefault("power_down_sequence", [
        "1. Host MCU commands PCD to turn off antenna driver.",
        "2. PICC: rectifier output falls; all PICC state lost.",
        "3. Host MCU may assert NRSTPD to fully power-down PCD chip.",
    ])
    lps = _ensure_dict(f, "low_power_modes_summary")
    lps.setdefault("PCD_field_off",         "PCD antenna driver disabled; max power saving.")
    lps.setdefault("PCD_doze",              "Vendor-specific reduced polling cadence.")
    lps.setdefault("PCD_host_bus_suspend",  "Host MCU asserts NRSTPD.")
    lps.setdefault("PICC_HALT",             "PICC ignores REQA; only WUPA wakes it.")
    lps.setdefault("PICC_T_CL_inactive",    "PICC in T_CL_ACTIVE between commands.")
    f.setdefault("power_consumption_typical", {
        "PCD_field_off_mA":       "≤ 10",
        "PCD_field_on_mA_at_3V3": "30..100",
        "PICC_field_powered_µA":  "5..20 (idle / HALT) ; up to 1 mA during EEPROM write",
        "PICC_DESFire_mA":        "Up to 2..3 during AES authentication",
    })
    f.setdefault("field_strength_for_power_budget", {
        "minimum_field_strength_A_per_m_for_picc_POR": 1.5,
        "maximum_field_strength_A_per_m_per_iso_14443_2": 7.5,
        "operating_envelope_per_class": "Class 1 antenna: 0..100 mm; Class 2/3/4 progressively reduced.",
    })
    f.setdefault("notes",
        "Power intent is asymmetric: PCD requires DC power and active control; "
        "PICC requires only an RF field. There is no PICC-side power switch or "
        "sleep register exposed on the air interface — the PCD modulates PICC "
        "power by controlling the field.")
    d["fields"] = f
    _write(p, d)


# ---------------------------------------------------------------------------
# L22 verification plan
# ---------------------------------------------------------------------------

def _l22(gd: Path) -> None:
    p = gd / "L22_VERIFICATION_PLAN.json"
    if not p.is_file():
        return
    d = _read(p)
    f = d.get("fields") or {}
    f.setdefault("verification_plan_present", "implicit")
    if _empty(f.get("verification_categories_derived_from_spec")):
        f["verification_categories_derived_from_spec"] = [
            "PICC POR sequence — field on → ≤ 5 ms → IDLE state, OTP loaded.",
            "REQA + ATQA across all family variants.",
            "WUPA wakes from both IDLE and HALT; REQA wakes only from IDLE.",
            "Cascade Level 1 anti-collision (SEL = 0x93) for 4-byte UID.",
            "Cascade Level 2 (SEL = 0x95) for 7-byte UID.",
            "Cascade Level 3 (SEL = 0x97) for 10-byte UID.",
            "Cascade Tag (0x88) in UID-CLn[0] of non-final CLs.",
            "BCC verification at every CL.",
            "SAK bit 6 = 1 → PCD activates Layer 4.",
            "SAK bit 3 = 1 → PCD continues to next CL.",
            "HLTA → HALT transition; PICC silent on REQA, responsive on WUPA.",
            "Multi-PICC anti-collision — 2 PICCs, distinct UIDs.",
            "Multi-PICC anti-collision — UID prefix shared, bisection.",
            "Multi-PICC anti-collision — 5 PICCs, full HALT loop.",
            "Type A + Type B mixed-field.",
            "RATS → ATS exchange + parameter parsing.",
            "PPS → PPS-RSP bit-rate negotiation.",
            "T=CL I-Block round-trip with alternating block number.",
            "T=CL R(NAK) retransmission.",
            "T=CL S(WTX) time extension.",
            "T=CL S(DESELECT) → HALT.",
            "CRC_A / CRC_B injection.",
            "Parity injection (Type A).",
            "Bit-frame anti-collision split at wrong bit position.",
            "GetVersion on Ultralight EV1 (byte 2 = 0xX3).",
            "GetVersion on Plus EV1 (byte 2 = 0xX2).",
            "GetVersion on Plus EV2 (subtype byte 3).",
            "GetVersion on DESFire EV1 (byte 2 = 0xX1).",
            "GetVersion on DESFire EV2 (chained response).",
            "GetVersion on DESFire EV3 (subtype).",
            "GetVersion on DESFire Light (byte 2 = 0xX8).",
            "GetVersion on NTAG21x (byte 2 = 0xX4).",
            "GetVersion on NTAG I2C (byte 2 = 0xX7).",
            "GetVersion on legacy MIFARE Classic — fallback path.",
            "Random ID mode — UID1..UID3 differ across POR.",
            "fdt_listen ≤ 86.43 μs across temp corners.",
            "FWT respected across FWI 0..14.",
            "Operation at H = Hmin = 1.5 A/m and Hmax = 7.5 A/m.",
            "ISO 10373-6 reference positions (6 positions).",
            "Carrier frequency tolerance ± 7 kHz.",
            "Long-frame test — maximum FSC = 256 bytes.",
        ]
    f["notes"] = (
        "AN10833 does not include a formal verification plan. Categories above "
        "are derived from ISO/IEC 14443 Parts 2/3/4 plus AN10833 §2 + Figure 1 + "
        "Figure 3. The normative compliance test framework is ISO/IEC 10373-6. "
        "EMVCo Contactless and NFC Forum Certification are sibling normative "
        "frameworks that subset ISO 14443 for specific application domains.")
    d["fields"] = f
    _write(p, d)


# ---------------------------------------------------------------------------
# L23 security
# ---------------------------------------------------------------------------

def _l23(gd: Path) -> None:
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if not p.is_file():
        return
    d = _read(p)
    f = d.get("fields") or {}
    f["security_requirements_present"] = True
    f["notes"] = (
        "Security requirements at the AN10833 level are bounded by what the "
        "identification surface can guarantee: (a) UID is factory-OTP-unique "
        "(except RID), (b) ATQA + SAK are public and deterministic, (c) "
        "GetVersion is public and deterministic. None of these are "
        "cryptographically authenticated. Practical security therefore lives in "
        "the application layer above Layer 4 (DESFire AES, Plus SL3 AES, "
        "Originality Signature). EMVCo, ICAO, and FIPS-201 all require Layer-4 "
        "mutual authentication before any application data exchange.")
    f.setdefault("security_summary",
        "ISO/IEC 14443 itself provides only data-integrity protection (CRC_A + "
        "CRC_B + parity for Type A frames) and structural anti-collision — not "
        "confidentiality, not authentication, and not replay protection. All "
        "cryptographic protection is layered above Layer 3 (MIFARE Classic "
        "Crypto1) or above Layer 4 (MIFARE DESFire 3DES / 3K-3DES / AES-128; "
        "MIFARE Plus AES-128 in SL2 / SL3).")
    if _empty(f.get("security_features")):
        f["security_features"] = [
            {"name": "CRC_A (Type A frame)",         "type": "integrity",        "scope": "Type A standard frames + T=CL",      "description": "Polynomial 0x8408 reflected, init 0x6363. NOT cryptographic."},
            {"name": "CRC_B (Type B frame)",         "type": "integrity",        "scope": "Type B frames + T=CL on Type B",     "description": "Polynomial 0x8408 reflected, init 0xFFFF, final XOR 0xFFFF. NOT cryptographic."},
            {"name": "Odd parity per byte (Type A)", "type": "integrity",        "scope": "Each byte on Type A wire",            "description": "Per-byte error detection."},
            {"name": "UID — Random ID (RID) variant","type": "privacy",          "scope": "Per-PICC POR",                         "description": "UID1..UID3 randomised at POR. Defeats persistent tracking."},
            {"name": "MIFARE Classic Crypto1",        "type": "stream cipher (legacy)", "scope": "MIFARE Classic 1K/4K, Plus SL1", "description": "Proprietary 48-bit stream cipher; broken since 2008."},
            {"name": "MIFARE Plus AES-128 (SL2/SL3)","type": "AES-128 mutual auth",     "scope": "MIFARE Plus",                  "description": "Standard AES-128 in CBC mode."},
            {"name": "MIFARE DESFire AES / 3K-3DES / 3DES", "type": "mutual auth + secure messaging", "scope": "DESFire family", "description": "ISO 7816-style file system; recommended for new designs."},
            {"name": "MIFARE Ultralight C 3DES",      "type": "3DES auth",        "scope": "Ultralight C",                       "description": "Per-tag 3DES authentication."},
            {"name": "NTAG21x password (PWD_AUTH)",  "type": "32-bit password",  "scope": "NTAG21x",                              "description": "4-byte password + 2-byte PACK ack. Not cryptographic."},
            {"name": "Card Lock — Classic / Ultralight", "type": "permanent read-only", "scope": "Sector trailers / pages",     "description": "Per-sector or per-page lock bits."},
            {"name": "Originality Signature (ECC NIST-P256)", "type": "anti-cloning", "scope": "NTAG21x DNA / DESFire EV3",      "description": "Factory-signed ECDSA over UID."},
        ]
    f["no_base_layer_confidentiality"] = (
        "The base ISO 14443 protocol does NOT encrypt user data on the air "
        "interface. An attacker with an RF sniffer can capture both PCD "
        "commands and PICC responses cleartext at Layer 3. Confidentiality "
        "must come from Layer 4 application crypto (DESFire / Plus) or from a "
        "secure element (SmartMX / JCOP).")
    f["comparison_to_iso_15693_and_nfc_p2p"] = (
        "ISO 15693 (Vicinity Cards) shares the same lack of base-layer "
        "confidentiality. NFC peer-to-peer (NFCIP-1 / ISO 18092) inherits the "
        "same wire-level transparency — application crypto must be added above "
        "DEP.")
    d["fields"] = f
    _write(p, d)


# ---------------------------------------------------------------------------
# Module-level importable detector (lifted from the inline detector in
# phase1_doc_one_shot_runner.py — ORGANIC-20260531). Byte-for-byte the same
# boolean the runner used inline (`_spi_blob` -> `blob`), so behaviour is
# identical; exposing it module-level lets the universal no-misfire guard
# (tests/test_protocol_detector_no_misfire.py) auto-cover this protocol.
# Reads ONLY the spec text `blob` — never a filename or benchmark name.
# ---------------------------------------------------------------------------
def is_nfc(blob: str) -> bool:
    """Content-only `nfc` detector (importable, lifted from the runner).

    Empty-safe. Reads ONLY ``blob`` (spec text). Byte-for-byte the
    same boolean the runner used inline.
    """
    if not blob:
        return False
    return bool(
        ("NFC" in blob and "ISO 14443" in blob
         and "UID" in blob)
        or ("MIFARE" in blob and "13.56" in blob
            and "SAK" in blob)
        or ("PCD" in blob and "PICC" in blob
            and "ATQA" in blob))
