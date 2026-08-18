"""ARINC 429 (Mark 33 DITS) protocol synth helper.

v0.1.83 — ic_class-gated overlay for `serial_peripheral_protocol` (or
`avionics_serial_protocol`) specs that exhibit the ARINC 429 structural
signature: (a) ARINC 429 + Label + SSM terminology; OR (b) Mark 33 +
DITS phrasing; OR (c) avionics + 32-bit word + BRZ + Label phrasing.
Applies ARINC-429-canonical content to L1-L18 + L21 + L23.

Doctrine: structural-keyword detection IS general within an ic_class
(mirrors the CAN / I2C / SPI / UART / USB / I2S synth approach). Any
ARINC-429-family device (single-channel, line-replaceable-unit-style,
Mark 33 DITS or any of its Part 1-x revisions including Part 1-17) or
ARINC 615 data loader layered on top exhibits the same wire-level
signature: 32-bit fixed word, Bit 1 first on the wire, Label / SDI /
Data / SSM / Parity field layout, BPRZ encoding on shielded 78 Ω
twisted-pair, single-transmitter ≤ 20-receiver broadcast topology,
odd parity over bits 1-31 with parity bit on bit 32.

Public entry: `apply_arinc429_synth(generated_docs_dir, is_arinc429,
arinc429_ic_name)`.

The default ic_name is `"ARINC 429 (Mark 33 DITS)"`.

Spec source: ARINC Specification 429 — Mark 33 Digital Information
Transfer System (DITS), Part 1-17 (Annapolis, Maryland: Aeronautical
Radio, Inc., 2004-05-17). Reference Wikipedia article and the standard
sections on Technical Description, Word Format, Labels, and Protection
from Interference.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

import l_doc_generator_stamp as _stamp


def _empty(v) -> bool:
    return v in (None, {}, []) or (isinstance(v, str) and not v.strip())


def _read(p: Path) -> dict:
    return json.loads(p.read_text())


def _write(p: Path, d: dict) -> None:
    # THE L-document write chokepoint: stamps the producing release onto
    # the document, then serialises it byte-identically to before.
    _stamp.dump(p, d)


def apply_arinc429_synth(generated_docs_dir: Path, is_arinc429: bool,
                         arinc429_ic_name: Optional[str]) -> None:
    """Apply ARINC 429 (Mark 33 DITS)-specific synth when the structural
    signature matched.

    Args:
        generated_docs_dir: Path to the phase1 generated_docs/ directory
            holding L1..L23 JSON layer documents.
        is_arinc429: True when the runner's structural detector confirmed
            ARINC 429 family.
        arinc429_ic_name: Canonical ic_name string to enforce across the
            14 main L docs (default `"ARINC 429 (Mark 33 DITS)"`).
    """
    if not is_arinc429:
        return
    gd = generated_docs_dir

    # Force ic_name across the 14 main L docs.
    if arinc429_ic_name is not None:
        for n in [
            "L1_DATASHEET.json", "L2_FRS.json", "L3_CMD_PROTOCOL.json",
            "L4_REGMAP.json", "L5_ADI_SPEC.json", "L6_CONTROL_LOGIC.json",
            "L7_TEST_DEBUG.json", "L8_RTL_CONSTANTS.json",
            "L8_TIMING_WAVEFORM.json", "L9_INTEGRATION_SPEC.json",
            "L10_TEST_CASES.json", "L11_OTP_CONTENT.json",
            "L12_BEHAVIORAL_SEQUENCES.json", "L13_LAB_CALIBRATION.json",
        ]:
            q = gd / n
            if q.is_file():
                d = _read(q)
                d["ic_name"] = arinc429_ic_name
                _write(q, d)

    # L1 DATASHEET
    p = gd / "L1_DATASHEET.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("document_title",
                     "ARINC 429 — Mark 33 Digital Information Transfer System (DITS)")
        d.setdefault("version",
                     "Mark 33 DITS (predominant avionics serial data bus)")
        d.setdefault("manufacturer",
                     "ARINC (Aeronautical Radio, Incorporated)")
        d.setdefault("revised_date",
                     "ARINC Specification 429 Part 1-17 — Annapolis, "
                     "Maryland: Aeronautical Radio, Inc. (2004-05-17)")
        d.setdefault("copyright",
                     "Aeronautical Radio, Inc. — ARINC technical standard")
        d.setdefault("document_layout", [
            "Technical description — medium and signaling, bit numbering, transmission order, bit significance.",
            "Word format — five fields per 32-bit word (Label / SDI / Data / SSM / Parity).",
            "Labels — equipment-type-specific octal identifier assignments (e.g. label 203 = barometric altitude).",
            "Protection from interference — RTCA DO-160 categories, shielded twisted-pair, BPRZ encoding.",
            "Development tools — protocol analyzers for signal capture/decode.",
            "Related ARINC specifications — 615, 629, 664 Part 7, 708, 828; and MIL-STD-1553 comparison.",
        ])
        d.setdefault("key_features", [
            "Avionics serial data bus — predominant on higher-end commercial and transport aircraft.",
            "Self-clocking, self-synchronizing two-wire protocol (Tx and Rx on separate ports).",
            "Balanced differential signaling on shielded twisted-pair (78 Ω characteristic impedance).",
            "Fixed 32-bit word format; most messages consist of a single data word.",
            "Two standard speeds: low (12.5 kbit/s, sometimes 12-14.5 kbit/s) and high (100 kbit/s).",
            "Single transmitter ↔ up to 20 receivers per bus (broadcast / simplex unidirectional).",
            "Five-field 32-bit word: Label (bits 1-8) + SDI (bits 9-10) + Data (bits 11-29) + SSM (bits 30-31) + Parity (bit 32).",
            "Three principal data encodings: BNR (Binary Number Representation, 2's complement), BCD (Binary Coded Decimal), Discrete bit fields.",
            "Odd parity over bits 1-31 (parity bit on bit 32).",
            "Bipolar return-to-zero (BRZ / BPRZ) encoding — eliminates clock-data transmission, reduces EMI.",
            "Implicit inter-word framing by ≥ 4 bit-times of NULL state (~ 40 µs gap at high speed).",
            "Alternative to MIL-STD-1553 multi-drop military serial bus.",
        ])
        d.setdefault("modes_of_operation", [
            {"name": "transmit (active)",      "description": "Transmitter constantly emits either 32-bit data words or the NULL state (0 V differential)."},
            {"name": "receive (passive monitor)", "description": "Up to 20 receivers tap the bus; each decodes BRZ → bits → Label/SDI/Data/SSM/Parity locally; receivers do not respond."},
            {"name": "NULL state (idle)",       "description": "Between words, both wires sit at 0 V differential (NULL); minimum gap ≥ 4 bit-times before next word."},
        ])
        d.setdefault("domain_of_application", [
            "Avionics local area network — flight management computer, inertial reference system, air data computer, radar altimeter, radios, GPS sensor interconnect.",
            "Higher-end commercial and transport aircraft (replaced widely on newer airframes by AFDX / ARINC 664 Part 7).",
            "Avionics protocol analyzers / development + troubleshooting tools.",
        ])
        d.setdefault("layered_structure", [
            {"layer": "Application Layer",         "scope": "Equipment-specific label assignments (e.g. label 203 = barometric altitude on any Air Data Computer). Out of scope for the wire-level protocol itself; defined in ARINC 429 Part 1-17 Sections 78-116."},
            {"layer": "Data Encoding Layer",       "scope": "BNR (2's complement scaled) / BCD (4-bit decimal digits) / Discrete (bit-field status). Mixed encodings permitted in the 19-bit data field."},
            {"layer": "Word / Frame Layer",        "scope": "32-bit fixed word with Label (bits 1-8) / SDI (9-10) / Data (11-29) / SSM (30-31) / Parity (32). Inter-word ≥ 4-bit-time NULL gap."},
            {"layer": "Physical Layer",            "scope": "Bipolar return-to-zero on shielded 78 Ω twisted-pair; ±10 V differential drive, ±5 V single-ended; receiver thresholds ±2.5 V; common-mode rejection ≥ 6.5 V."},
        ])
        d.setdefault("overview",
            "ARINC 429, the Mark 33 Digital Information Transfer System (DITS), is the ARINC technical standard for the predominant avionics data bus used on most higher-end commercial and transport aircraft. It defines the physical and electrical interfaces of a two-wire data bus and a data protocol to support an aircraft's avionics local area network. Each bus has one transmitter and up to 20 receivers; data is sent as 32-bit fixed-length words at either 12.5 kbit/s (low speed) or 100 kbit/s (high speed). The bus is self-clocking via bipolar return-to-zero (BRZ) encoding on a balanced differential pair, eliminating any separate clock line. ARINC 429 is an alternative to MIL-STD-1553.")
        d.setdefault("compatibility_note",
            "ARINC 429 is unidirectional and simplex — a single bus carries words in one direction only. Bidirectional avionics communication requires a pair of buses or a higher-layer protocol (e.g. ARINC 615 data loader, ARINC 629 multi-transmitter TDMA, ARINC 664 Part 7 deterministic Ethernet / AFDX). Some equipment suppliers renumber Label bits LSB-first (e.g. 8,7,6,5,4,3,2,1,9,10,..) reflecting octet-oriented shift-register hardware; the canonical standard numbers bits 1 (= LSB on the wire = Label MSB) through 32 (= MSB on the wire = Parity).")
        _write(p, d)

    # L2 FRS
    p = gd / "L2_FRS.json"
    if p.is_file():
        d = _read(p)
        po = d.setdefault("protocol_overview", {})
        if isinstance(po, dict):
            po.setdefault("type",
                "Avionics serial broadcast bus; single transmitter ↔ up to 20 receivers; 32-bit fixed word format with implicit ≥4-bit-time NULL inter-word framing.")
            po.setdefault("duplex",
                "simplex (unidirectional) on each bus; bidirectional pair requires two buses")
            po.setdefault("synchronous", False)
            po.setdefault("bus_arbitration",
                "Not applicable — one transmitter per bus; no arbitration mechanism (multi-master extension is ARINC 629).")
            po.setdefault("physical_layer",
                "Bipolar return-to-zero (BRZ / BPRZ) on shielded 78 Ω twisted-pair, balanced differential signaling. ±10 V differential drive (e.g. +5 V on DataA, -5 V on DataB); receiver thresholds ±2.5 V; common-mode rejection ≥ 6.5 V.")
            po.setdefault("bit_coding",
                "Bipolar return-to-zero (BRZ): three line states HI (positive differential) / LO (negative differential) / NULL (0 V differential). Each bit occupies one bit-time and returns to NULL halfway through, providing the self-clocking edge.")
            po.setdefault("bus_values",
                "Three line states: HI (≈ +10 V differential = logical 1), LO (≈ -10 V differential = logical 0), NULL (0 V differential = idle / inter-word gap).")
            po.setdefault("multimaster", False)
            po.setdefault("multicast", True)
            po.setdefault("addressing",
                "Content-addressed by 8-bit octal Label (bits 1-8) within an equipment-type context; SDI (bits 9-10) optionally identifies source subsystem or intended receiver. Each bus is logically broadcast to all (up to 20) attached receivers.")
        fr = [
            {"id": "FR-WORD-01",   "text": "Each ARINC 429 word is a 32-bit fixed-length sequence transmitted Bit 1 first (over the wire), Bit 32 last."},
            {"id": "FR-LABEL-02",  "text": "Bits 1-8 carry the 8-bit Label (expressed in octal, MSB 1 bit numbering). Label is transmitted most-significant-bit first within the Label field."},
            {"id": "FR-SDI-03",    "text": "Bits 9-10 are the Source/Destination Identifier (SDI) — may indicate the intended receiver or, more frequently, the transmitting subsystem."},
            {"id": "FR-DATA-04",   "text": "Bits 11-29 contain the 19-bit Data field. Encodings: Binary Number Representation (BNR, 2's complement scaled), Binary Coded Decimal (BCD, 4-bit decimal digits), Discrete (bit-field status). Encodings may be mixed within the same word."},
            {"id": "FR-SSM-05",    "text": "Bits 30-31 are the Sign/Status Matrix (SSM) — encoding depends on data representation (BCD / BNR / Discrete)."},
            {"id": "FR-PARITY-06", "text": "Bit 32 is the parity bit. Every ARINC 429 channel typically uses odd parity — the total number of 1 bits in bits 1..32 must be odd. The parity bit is set to 0 or 1 to enforce this."},
            {"id": "FR-BNR-07",    "text": "In BNR (2's-complement signed binary) representation, Bit 29 is the sign bit (0 = Plus, 1 = Minus); SSM (bits 30-31) carries Status Matrix (FW/NCD/FT/NO) only."},
            {"id": "FR-BCD-08",    "text": "In BCD representation, SSM may indicate Sign (+/-) or sign-equivalents (North/South, East/West, Right/Left, To/From, Above/Below). When indicating sign, the SSM is also considered Normal Operation."},
            {"id": "FR-DISCRETE-09","text": "In Discrete (bit-field) representation, the SSM has a different, signless encoding: 00 = Verified Data / Normal Operation; 01 = NCD; 10 = Functional Test; 11 = Failure Warning."},
            {"id": "FR-SPEED-10",  "text": "Two standard bit rates: low speed = 12.5 kbit/s (some equipment 12-14.5 kbit/s tolerance) and high speed = 100 kbit/s. Word time at high speed is 32 × 10 µs = 320 µs (with inter-word gap, total ≈ 360 µs)."},
            {"id": "FR-GAP-11",    "text": "Gap between two words ≥ 4 bit-times of NULL state (~ 40 µs at 100 kbit/s); implicit framing — no explicit start-of-word or end-of-word delimiter."},
            {"id": "FR-SELFCLK-12","text": "Self-clocking from bit-period: BRZ encoding returns to zero halfway through each bit-time. Receiver recovers bit clock from the BRZ transition pattern; no separate clock wire is transmitted."},
            {"id": "FR-RECEIVERS-13","text": "A single twisted-pair is limited to one transmitter and no more than 20 receivers."},
            {"id": "FR-BROADCAST-14","text": "Broadcast: transmitter constantly transmits either 32-bit data words or the NULL state (0 V differential). All up-to-20 attached receivers see every word; selection is by Label match locally."},
            {"id": "FR-EMI-15",    "text": "Cabling is shielded 78 Ω twisted-pair. BPRZ encoding minimizes EMI emissions from the cable. Avionics signaling defines a 10 Vp differential between Data A and Data B (e.g. +5 V on A and -5 V on B = valid drive)."},
            {"id": "FR-LABELS-16", "text": "Standard label assignments are defined per equipment type in ARINC 429 Part 1-17 Sections 78-116; e.g. any air data computer transmits barometric altitude on label 203. A given label may carry a different meaning when sent by a different equipment type."},
        ]
        if _empty(d.get("functional_requirements")):
            d["functional_requirements"] = fr
        d.setdefault("error_response_conditions", [
            "Parity mismatch — receiver computes odd parity over bits 1-31 and compares against bit 32; mismatch indicates word corruption.",
            "SSM = Failure Warning (FW) — transmitter signals a failure that causes the data to be suspect or missing.",
            "SSM = No Computed Data (NCD) — data is missing or inaccurate for some reason other than a failure (e.g. autopilot OFF → autopilot-command words show NCD).",
            "SSM = Functional Test (FT) — data is being provided by a test source, not by the real measurement subsystem.",
            "Receiver gap-check — fewer than 4 bit-times of NULL between two words signals a framing violation.",
            "Receiver threshold violation — line differential outside ±2.5 V valid HI/LO/NULL bands is rejected as an undefined state.",
        ])
        if _empty(d.get("compliance_requirements")):
            d["compliance_requirements"] = [
                "Transmit each 32-bit word with Bit 1 first; bits 1-8 carry Label (MSB-first within label), bits 11-29 Data, bits 30-31 SSM, bit 32 Parity.",
                "Use odd parity over bits 1-31 (parity bit on bit 32).",
                "Bipolar return-to-zero encoding on shielded 78 Ω twisted-pair, balanced differential, ±10 V differential drive.",
                "Inter-word gap ≥ 4 bit-times of NULL state.",
                "Use standard speed 12.5 kbit/s (low) or 100 kbit/s (high) — a single bus runs at one speed.",
                "Maximum 1 transmitter and ≤ 20 receivers per bus.",
                "Receiver thresholds ±2.5 V; common-mode rejection ≥ 6.5 V.",
                "Use the SSM encoding appropriate to the data representation (BCD / BNR / Discrete) per the standard matrix.",
            ]
        d.setdefault("performance_of_error_detection", [
            "Single-bit error within a 32-bit word: detected by odd parity (probability 1).",
            "Any odd number of bit errors: detected by parity.",
            "Even number of bit errors: NOT detected by parity alone — relies on subsystem-level redundancy / repetition (most ARINC 429 labels are transmitted at fixed periodic rates so a corrupted single transmission is naturally retried on the next cycle).",
            "Line-glitch shorter than half a bit-time: rejected by the BRZ mid-bit return-to-zero invariant.",
            "Cable shielding + balanced differential + bipolar return-to-zero collectively reduce EMI-induced errors below DO-160 environmental category limits.",
        ])
        _write(p, d)

    # L3 CMD_PROTOCOL
    p = gd / "L3_CMD_PROTOCOL.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("protocol_type",
            "Avionics broadcast serial word protocol; one transmitter ↔ ≤ 20 receivers; 32-bit fixed word; content-addressed by 8-bit Label (octal); no opcode/command set; no per-word handshake.")
        d.setdefault("opcodes", [])
        d.setdefault("channels", [
            {"name": "ARINC 429 bus (single twisted-pair)",
             "direction": "unidirectional (simplex) broadcast from one transmitter to up to 20 receivers",
             "description": "Two-wire shielded 78 Ω twisted-pair carrying balanced differential bipolar return-to-zero (BRZ) signaling. Three line states: HI / LO / NULL."},
        ])
        d.setdefault("frame_types", [
            {"name": "DATA WORD",  "purpose": "32-bit fixed word; the only structured ARINC 429 frame type. Carries Label / SDI / Data / SSM / Parity."},
            {"name": "NULL state", "purpose": "0 V differential idle between words. Not a frame — an implicit inter-word gap (≥ 4 bit-times) that delimits successive 32-bit words."},
        ])
        d.setdefault("data_frame_fields", [
            {"field": "Label",  "bits": "1-8",   "size": "8 bits",  "components": "Octal label code (MSB 1 bit numbering); transmitted MSB-first within the label field. Identifies the data type per equipment-type table."},
            {"field": "SDI",    "bits": "9-10",  "size": "2 bits",  "components": "Source/Destination Identifier — indicates intended receiver, or more commonly the transmitting subsystem."},
            {"field": "Data",   "bits": "11-29", "size": "19 bits", "components": "Data payload: BNR (2's complement scaled binary; Bit 29 = sign), BCD (4-bit decimal digits), or Discrete bit field. Encodings may be mixed within the same word."},
            {"field": "SSM",    "bits": "30-31", "size": "2 bits",  "components": "Sign/Status Matrix — encoding depends on data representation (see SSM tables)."},
            {"field": "Parity", "bits": "32",    "size": "1 bit",   "components": "Odd parity over bits 1..31 (parity bit is bit 32 — last bit transmitted)."},
        ])
        d.setdefault("ssm_encoding_table", {
            "header": ["Bit 31", "Bit 30", "BCD Data", "BNR Data", "Discrete Data"],
            "rows": [
                ["0", "0", "Plus, North, East, Right, To, Above",   "Failure Warning (FW)",   "Verified Data, Normal Operation"],
                ["0", "1", "No Computed Data (NCD)",                "No Computed Data (NCD)", "No Computed Data (NCD)"],
                ["1", "0", "Functional Test (FT)",                  "Functional Test (FT)",   "Functional Test (FT)"],
                ["1", "1", "Minus, South, West, Left, From, Below", "Normal Operation (NO)",  "Failure Warning (FW)"],
            ],
            "note": "For BNR-encoded data, Bit 29 (within the Data field) carries the sign separately: 0 = Plus, 1 = Minus.",
        })
        d.setdefault("bnr_sign_table", {
            "header": ["Bit 29", "Meaning"],
            "rows": [
                ["0", "Plus, North, East, Right, To, Above"],
                ["1", "Minus, South, West, Left, From, Below"],
            ],
        })
        d.setdefault("valid_ready_handshake_rules", [
            "There is no per-word VALID/READY handshake.",
            "There is no acknowledgment frame — the transmitter does not learn whether any receiver decoded the word successfully.",
            "Reliability is achieved by (a) periodic re-transmission of every label at its fixed update rate, (b) odd parity per word, and (c) BRZ self-clocking + shielded differential physical layer.",
        ])
        d.setdefault("framing_rules", [
            "Each word is exactly 32 bits; Bit 1 first on the wire, Bit 32 last.",
            "Within the Label field (bits 1-8), bits are transmitted MSB-first.",
            "Within the SDI / Data / SSM fields, bits are normally illustrated with bit 11 as the data-field LSB and bit 29 as the data-field MSB (BCD/BNR numeric MSB on the diagrammed left when the word is drawn from Bit 32 to Bit 1).",
            "Inter-word gap: ≥ 4 bit-times of NULL state. No explicit start/end delimiter.",
            "Bit transmission order over the wire = 1, 2, 3, ..., 31, 32 (first → last).",
        ])
        d.setdefault("burst_based", False)
        d.setdefault("byte_oriented_within_data_field", False)
        d.setdefault("byte_order_within_data_field",
            "N/A — the 19-bit data field is not byte-organized at the protocol layer. Implementation-level shift registers may access it in 8-bit chunks (LSB 0 within each octet); see L9 / L17 notes on equipment-supplier 'reversed label' octet ordering.")
        d.setdefault("interframe_space", {
            "null_gap":                "≥ 4 bit-times of NULL state between consecutive 32-bit words (~ 40 µs at 100 kbit/s).",
            "continuous_transmission": "Transmitter may emit back-to-back words separated only by the mandatory ≥ 4-bit-time NULL gap.",
            "idle":                    "When no words are queued, the transmitter holds the bus at NULL (0 V differential).",
        })
        _write(p, d)

    # L4 wire-level — no register map
    p = gd / "L4_REGMAP.json"
    if p.is_file():
        d = _read(p)
        d["register_map_present"] = False
        d["notes"] = (
            "ARINC 429 (Mark 33 DITS) is a wire-level avionics protocol "
            "specification, not a peripheral block guide. There is no "
            "architectural register map at the protocol layer. Concrete "
            "ARINC 429 transceiver / controller IP — e.g. Holt HI-3584, "
            "HI-3585, HI-8783/8784/8785, Texas Instruments DEI1016, "
            "Microchip / DDC BU-69091 — define their own register file "
            "(typically: control / status / interrupt-mask / TX FIFO / "
            "RX FIFO / label-filter / speed-select / loopback / parity-"
            "mode registers) at the device-integration level. Those are "
            "covered by individual device datasheets, not by the ARINC "
            "429 specification itself.")
        _write(p, d)

    # L5 ADI_SPEC — overwrite signaling
    # v0.1.88: force-overwrite analog_digital_interface_present (was setdefault,
    # but earlier serial_peripheral_protocol class synth — SPI _apply_universal —
    # runs UNCONDITIONALLY and stamps False on this key via setdefault, so a
    # later setdefault here no-ops. ARINC 429 IS analog (balanced differential
    # BPRZ on 78 Ω shielded twisted-pair at ±10 V); the value must be True for
    # every spec that exhibits the ARINC 429 structural signature.
    p = gd / "L5_ADI_SPEC.json"
    if p.is_file():
        d = _read(p)
        d["analog_digital_interface_present"] = True
        d["signaling_summary"] = (
            "ARINC 429 defines a balanced differential bipolar return-to-"
            "zero (BPRZ / BRZ) signaling scheme on a shielded 78 Ω "
            "twisted-pair. The bus carries three line states: HI (+10 V "
            "differential, e.g. +5 V on DataA / -5 V on DataB), LO (-10 V "
            "differential), and NULL (0 V differential, idle / inter-word "
            "gap). Each bit returns to NULL halfway through its bit-time, "
            "providing the self-clocking edge. Receiver thresholds are "
            "±2.5 V (anything above +2.5 V differential = HI, below -2.5 V "
            "= LO, between = NULL / undefined). Common-mode rejection of "
            "the differential receiver is ≥ 6.5 V. Voltage rise and fall "
            "times are bounded by the ARINC 429 specification to limit "
            "EMI emissions and overshoot. Two standard bit rates: low "
            "speed = 12.5 kbit/s (some equipment 12-14.5 kbit/s) and high "
            "speed = 100 kbit/s; a single bus runs at one fixed speed.")
        d.setdefault("drive_levels", {
            "HI_differential":         "+10 V (typical; e.g. +5 V on DataA, -5 V on DataB)",
            "LO_differential":         "-10 V (typical; e.g. -5 V on DataA, +5 V on DataB)",
            "NULL_differential":       "0 V (both lines at equal potential; idle / between bit halves / inter-word gap)",
            "single_ended_amplitude":  "±5 V on each wire relative to ground",
            "common_mode_rejection":   "≥ 6.5 V",
        })
        d.setdefault("receiver_thresholds", {
            "HI_threshold":  "differential > +2.5 V → HI",
            "LO_threshold":  "differential < -2.5 V → LO",
            "NULL_band":     "-2.5 V ≤ differential ≤ +2.5 V → NULL / between-bit-half",
        })
        d.setdefault("physical_medium", {
            "cable_type":               "shielded twisted-pair",
            "characteristic_impedance": "78 Ω",
            "drive_type":               "balanced differential, push-pull tri-state output (HI / LO / NULL)",
            "max_receivers_per_bus":    20,
            "max_transmitters_per_bus": 1,
        })
        d.setdefault("voltage_rise_fall_times",
            "Bounded by the ARINC 429 specification to limit EMI emissions "
            "and overshoot; specific rise/fall envelopes are spec-dependent "
            "(function of selected bit rate and bus length).")
        d.setdefault("bit_period_self_clocking",
            "BRZ: HI half / NULL half = logical 1; LO half / NULL half = "
            "logical 0. The mid-bit return-to-zero transition is the self-"
            "clocking edge; receiver recovers bit clock from the BRZ "
            "transition pattern without a separate clock wire.")
        _write(p, d)

    # L6 CONTROL_LOGIC
    p = gd / "L6_CONTROL_LOGIC.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("fsm_hints_transmitter", [
            {"name": "TX_IDLE",          "description": "No word queued; bus held at NULL state (0 V differential). Inter-word gap is NULL-held by default."},
            {"name": "TX_GAP",           "description": "Holding NULL for at least 4 bit-times before starting a new word (≥ 40 µs at 100 kbit/s)."},
            {"name": "TX_LABEL",         "description": "Transmit bits 1-8 (Label) MSB-first within the label field. Each bit drives HI or LO for the first half of the bit-time, then NULL for the second half (BRZ)."},
            {"name": "TX_SDI",           "description": "Transmit bits 9-10 (Source/Destination Identifier)."},
            {"name": "TX_DATA",          "description": "Transmit bits 11-29 (19-bit Data field) per chosen encoding (BNR / BCD / Discrete; mixed permitted)."},
            {"name": "TX_SSM",           "description": "Transmit bits 30-31 (Sign/Status Matrix) per BCD/BNR/Discrete SSM table."},
            {"name": "TX_PARITY",        "description": "Compute odd parity over bits 1..31; drive bit 32 accordingly (0 or 1) to make the total number of 1-bits in the 32-bit word odd."},
            {"name": "TX_RETURN_TO_IDLE","description": "After bit 32, return to NULL for ≥ 4 bit-times before optionally starting the next word."},
        ])
        d.setdefault("fsm_hints_receiver", [
            {"name": "RX_IDLE",          "description": "Bus at NULL state; waiting for first HI-or-LO bit-half transition that marks the start of bit 1 of a new word."},
            {"name": "RX_GAP_DETECT",    "description": "Counted ≥ 4 bit-times of NULL since the last bit 32 → ready to accept the next word's bit 1."},
            {"name": "RX_BIT_SAMPLE",    "description": "On each bit-time, sample line during the first half (HI = 1, LO = 0, NULL = framing error/ambiguous); confirm return-to-NULL in the second half. Recover bit clock from BRZ transitions."},
            {"name": "RX_DESHIFT_WORD",  "description": "Accumulate 32 bits into a word register: bits 1..8 → Label; 9..10 → SDI; 11..29 → Data; 30..31 → SSM; 32 → Parity."},
            {"name": "RX_PARITY_CHECK",  "description": "Verify odd parity over the 32-bit word; discard or flag on mismatch."},
            {"name": "RX_LABEL_FILTER",  "description": "Apply local Label filter (per equipment-type acceptance list); unmatched labels are dropped."},
            {"name": "RX_SSM_DECODE",    "description": "Decode SSM bits (30-31) per the data representation in use (BCD / BNR / Discrete); attach FW/NCD/FT/NO/sign attribute to the data sample."},
        ])
        d.setdefault("synchronization_rules", [
            "BRZ self-clocking: each bit-time begins with a HI or LO drive for the first half and returns to NULL for the second half.",
            "The receiver recovers bit clock from the HI→NULL or LO→NULL mid-bit transitions; no separate clock wire is transmitted.",
            "Hard inter-word resynchronization: after a ≥ 4-bit-time NULL gap, the next HI-or-LO drive is the start of bit 1 of a new 32-bit word.",
            "There is no preamble / start bit / stop bit other than the implicit ≥ 4-bit-time NULL framing.",
            "Bit-rate tolerance is bounded by the worst-case BRZ eye opening; in practice ±1 % oscillator tolerance per side is comfortably within margin at 100 kbit/s.",
        ])
        d.setdefault("arbitration_rule",
            "Not applicable — ARINC 429 is single-transmitter unidirectional broadcast. No arbitration mechanism exists at the protocol layer. Multi-source avionics networks use a pair of buses (one per direction) or a multi-transmitter extension such as ARINC 629 (TDMA) or ARINC 664 Part 7 (switched deterministic Ethernet / AFDX).")
        d.setdefault("anti_deadlock_rule",
            "Not applicable. Single-transmitter buses cannot deadlock. The transmitter constantly emits either 32-bit words or NULL; receivers are passive monitors with no upstream feedback.")
        d.setdefault("exit_from_reset_or_wakeup",
            "On power-up or reset, the transmitter holds the bus at NULL until its first word is queued, then waits ≥ 4 bit-times before driving bit 1. Receivers stay in RX_IDLE / RX_GAP_DETECT until the first HI-or-LO drive is detected; no handshake or wake-up exchange is defined at the wire-level protocol.")
        d.setdefault("default_signal_state_when_bus_free",
            "NULL state (0 V differential); single transmitter drives both wires to equal potential while idle.")
        d.setdefault("label_filtering_rule",
            "Each receiver implements a local label-acceptance filter (one bit per possible 8-bit octal label, or a CAM/lookup of accepted labels). Labels not in the filter are discarded after parity check. Filter semantics are equipment-specific; the ARINC 429 spec only standardizes the LABEL → meaning assignments per equipment type (Sections 78-116 of ARINC 429 Part 1-17).")
        _write(p, d)

    # L7 TEST_DEBUG
    p = gd / "L7_TEST_DEBUG.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("test_debug_architecture_present", False)
        d.setdefault("spec_provided_observability", [
            {"name": "Parity bit (bit 32)",      "purpose": "Per-word integrity check; odd parity over bits 1-31 detects all single-bit errors and all odd-multiplicity bit errors."},
            {"name": "SSM (bits 30-31)",         "purpose": "Per-word source-side health/status: Normal Operation (NO), No Computed Data (NCD), Functional Test (FT), Failure Warning (FW); semantics depend on data representation (BCD / BNR / Discrete)."},
            {"name": "Bit 29 (BNR sign bit)",    "purpose": "Explicit numeric sign for BNR-encoded data; sign-out-of-range or sign-vs-magnitude mismatch flags a subsystem error."},
            {"name": "Inter-word NULL gap",      "purpose": "≥ 4 bit-times of NULL between words; framing-error detector at the receiver."},
            {"name": "Label (bits 1-8)",         "purpose": "Octal label per equipment-type table; unknown / unused labels are dropped by the local filter and may be counted as 'unexpected label' observability points."},
            {"name": "Periodic update rate",     "purpose": "Each label is transmitted at a fixed periodic rate per the equipment-type spec; absence of a label for longer than its nominal period is a transmitter-down observability event."},
        ])
        d.setdefault("self_check_mechanisms", [
            "Odd parity over bits 1-31 — detects all single-bit errors and any odd number of bit errors per 32-bit word.",
            "BRZ self-clocking — receiver verifies HI-or-LO drive in first half + NULL in second half of every bit-time; failure is a line-glitch / framing fault.",
            "Inter-word gap monitor — receiver requires ≥ 4 bit-times of NULL between words; a too-short gap is a framing fault.",
            "Voltage threshold detection — line differential outside ±2.5 V bands or outside ±10 V drive envelope is rejected as undefined.",
            "SSM = Failure Warning (FW) or Functional Test (FT) at the transmitter signals the receiver to mark the data accordingly without re-deriving it.",
        ])
        d.setdefault("error_count_thresholds", [
            {"threshold": "implementation-specific",
             "consequence": "ARINC 429 does not standardize error counters or thresholds. Per-receiver implementations (Holt HI-3584, etc.) typically expose per-channel parity-error and framing-error counters in their device-level register file; threshold behavior is application-defined."},
        ])
        d.setdefault("recovery_from_error",
            "ARINC 429 has no explicit error-recovery handshake. Recovery is by natural periodic re-transmission: every label is sent at its fixed periodic update rate (per equipment-type spec), so a single corrupted word is automatically superseded by the next periodic transmission of the same label.")
        d.setdefault("notes",
            "ARINC 429 does not specify scan / JTAG / BIST at the protocol layer. Protocol-level integrity is provided by odd parity per word + BRZ self-clocking + ≥ 4-bit-time inter-word gap + SSM-based source-side health flags + the natural periodic re-transmission cadence of avionics labels. Development tools — protocol analyzers (e.g. Avionics Interface Technologies, AIM GmbH, Condor Engineering) — collect, decode, and store ARINC 429 traffic for debug; commercial transceivers (Holt, DDC) add device-level loopback / BIT modes.")
        _write(p, d)

    # L8 RTL constants
    p = gd / "L8_RTL_CONSTANTS.json"
    if p.is_file():
        d = _read(p)
        wp = d.setdefault("width_parameters", {})
        if isinstance(wp, dict):
            for k, v in {
                "WORD_WIDTH_bits": 32,
                "LABEL_WIDTH_bits": 8,
                "SDI_WIDTH_bits": 2,
                "DATA_WIDTH_bits": 19,
                "SSM_WIDTH_bits": 2,
                "PARITY_WIDTH_bits": 1,
                "BNR_SIGN_BIT_within_DATA_FIELD_bit_position": 29,
                "BNR_MAGNITUDE_WIDTH_bits": 18,
                "BCD_NIBBLE_WIDTH_bits": 4,
                "BCD_NIBBLES_PER_DATA_FIELD_max": 4,
                "INTER_WORD_NULL_GAP_min_bit_times": 4,
                "MAX_RECEIVERS_PER_BUS": 20,
                "MAX_TRANSMITTERS_PER_BUS": 1,
                "WORD_BIT_NUMBER_FIRST_TX": 1,
                "WORD_BIT_NUMBER_LAST_TX": 32,
                "LABEL_FIELD_BIT_FIRST": 1,
                "LABEL_FIELD_BIT_LAST": 8,
                "SDI_FIELD_BIT_FIRST": 9,
                "SDI_FIELD_BIT_LAST": 10,
                "DATA_FIELD_BIT_FIRST": 11,
                "DATA_FIELD_BIT_LAST": 29,
                "SSM_FIELD_BIT_FIRST": 30,
                "SSM_FIELD_BIT_LAST": 31,
                "PARITY_FIELD_BIT": 32,
            }.items():
                wp.setdefault(k, v)
        d.setdefault("parity_scheme", {
            "type": "odd parity",
            "covers": "bits 1..31",
            "parity_bit_position_on_wire": 32,
            "rule": "parity_bit = 0 or 1 chosen so that the number of 1-bits in bits 1..32 is odd",
        })
        d.setdefault("bit_rates", {
            "LOW_SPEED_kbit_per_s": 12.5,
            "LOW_SPEED_TOLERANCE_RANGE_kbit_per_s": [12, 14.5],
            "HIGH_SPEED_kbit_per_s": 100,
            "BIT_TIME_HIGH_SPEED_us": 10.0,
            "BIT_TIME_LOW_SPEED_us": 80.0,
            "WORD_TIME_HIGH_SPEED_us": 320.0,
            "MIN_WORD_TO_WORD_PERIOD_HIGH_SPEED_us": 360.0,
        })
        d.setdefault("electrical_constants", {
            "DRIVE_DIFFERENTIAL_HI_V": 10,
            "DRIVE_DIFFERENTIAL_LO_V": -10,
            "DRIVE_DIFFERENTIAL_NULL_V": 0,
            "DRIVE_SINGLE_ENDED_PER_WIRE_V": 5,
            "RX_THRESHOLD_HI_V": 2.5,
            "RX_THRESHOLD_LO_V": -2.5,
            "COMMON_MODE_REJECTION_MIN_V": 6.5,
            "CABLE_CHARACTERISTIC_IMPEDANCE_OHM": 78,
        })
        d.setdefault("key_constants_for_RTL_authoring", {
            "bit_coding": "Bipolar return-to-zero (BRZ): each bit-time = first-half drive (HI for '1', LO for '0') + second-half NULL (return to zero).",
            "bit_order_on_wire": "Bit 1 first → Bit 32 last for the 32-bit word.",
            "label_bit_order_within_label_field": "MSB-first (label_msb on bit 1, label_lsb on bit 8 when reading the label field MSB-1 numbering).",
            "data_field_endianness_in_diagrams": "When the word is illustrated with Bit 32 on the left, BCD/BNR numeric MSB is on the left (Bit 29) and LSB on the right (Bit 11).",
            "supplier_octet_renumbering_note": "Some equipment suppliers diagram the bit transmission order as '8,7,6,5,4,3,2,1,9,10,11,...,32' — this renumbers the Label field LSB-first to align with octet-oriented (LSB-0) shift-register hardware. The canonical ARINC 429 numbering is 1..32 with Label bit 1 first on the wire and Label bit 1 being the LSB of the label octal value.",
            "parity_scheme": "odd parity over bits 1..31; parity bit on bit 32",
            "inter_word_gap_min_bit_times": 4,
            "max_receivers_per_bus": 20,
            "max_transmitters_per_bus": 1,
            "bnr_sign_bit_position_in_data_field": 29,
            "encodings_supported_in_data_field": ["BNR", "BCD", "Discrete"],
            "encodings_may_be_mixed_within_word": True,
            "ssm_encoding_is_data_representation_dependent": True,
            "alternative_protocols": [
                "MIL-STD-1553",
                "ARINC 615 (data loader on top of 429)",
                "ARINC 629 (TDMA multi-transmitter)",
                "ARINC 664 Part 7 / AFDX (deterministic Ethernet)",
                "ARINC 708 (weather radar; simplified 1553-derived; control by 429 labels)",
            ],
        })
        d.setdefault("label_examples", {
            "label_203_octal":      "barometric altitude (Air Data Computer)",
            "label_260_octal":      "time of day (illustrated in the standard's Example ARINC 429 image as bits '17:3:3 2(Day)') — meaning is equipment-dependent",
            "label_assignments_source": "ARINC Specification 429 Part 1-17 — Annapolis, Maryland: Aeronautical Radio, Inc. (2004-05-17), pp. 78-116 (label tables per equipment type)",
        })
        _write(p, d)

    # L8_TIMING_WAVEFORM
    p = gd / "L8_TIMING_WAVEFORM.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("bit_time_structure", {
            "FIRST_HALF":   "Drive line to HI (for '1') or LO (for '0'); half a bit-time wide.",
            "SECOND_HALF":  "Return line to NULL (0 V differential); half a bit-time wide.",
            "BIT_TIME_HIGH_SPEED": "10 µs (100 kbit/s)",
            "BIT_TIME_LOW_SPEED":  "80 µs (12.5 kbit/s); equipment tolerance band typically 12-14.5 kbit/s",
            "SELF_CLOCKING_EDGE":  "Mid-bit transition (HI→NULL or LO→NULL); receiver recovers bit clock from this transition pattern without a separate clock wire.",
        })
        d.setdefault("word_waveform", {
            "WORD_WIDTH_bits": 32,
            "WORD_TIME_HIGH_SPEED_us": 320.0,
            "WORD_LAYOUT_BITS_1_to_32_first_to_last_transmitted": {
                "bits_1_to_8":   "Label (MSB-first within the label field).",
                "bits_9_to_10":  "SDI (Source/Destination Identifier).",
                "bits_11_to_29": "Data (19 bits; BNR / BCD / Discrete; mixed permitted; Bit 29 = BNR sign).",
                "bits_30_to_31": "SSM (Sign/Status Matrix).",
                "bit_32":        "Parity (odd parity over bits 1..31).",
            },
            "WORD_LAYOUT_BITS_32_to_1_diagram_convention_left_to_right": "Many ARINC publications draw the word with Bit 32 on the left and Bit 1 on the right. Under this convention BCD/BNR numeric MSB appears on the left (Bit 29) and the Label LSB on the right (Bit 8) — but the label is still transmitted MSB-first on the wire.",
        })
        d.setdefault("inter_word_gap_waveform", {
            "NULL_GAP_min_bit_times": 4,
            "NULL_GAP_min_us_high_speed": 40.0,
            "MIN_WORD_TO_WORD_PERIOD_HIGH_SPEED_us": 360.0,
            "DESCRIPTION": "Between bit 32 of one word and bit 1 of the next word, the line is held at NULL (0 V differential) for ≥ 4 bit-times. This gap is the only inter-word framing — there is no explicit start-of-word delimiter.",
        })
        d.setdefault("synchronization_waveform", {
            "HARD_FRAMING":          "Receiver counts NULL bit-times; once ≥ 4 NULL bit-times have elapsed, the next HI or LO drive marks the start of bit 1 of a new word.",
            "WITHIN_WORD_BIT_CLOCK": "Recovered from the mid-bit return-to-zero transitions of every bit; no preamble / sync pattern other than the implicit gap.",
            "OSCILLATOR_TOLERANCE":  "Bounded by worst-case BRZ eye opening; ±1 % per side is comfortably within margin at 100 kbit/s; tighter at 12.5 kbit/s.",
        })
        d.setdefault("brz_waveform_example", {
            "logical_1": "First half = HI (+10 V differential); second half = NULL (0 V differential).",
            "logical_0": "First half = LO (-10 V differential); second half = NULL (0 V differential).",
            "idle":      "Both halves = NULL (0 V differential).",
        })
        d.setdefault("example_word_from_spec", {
            "label_octal": 260,
            "data_field": "0 1 0 0 0 1 1 0 0 0 1 1 0 0 0 1 0 0 0  (bits 11..29, illustrated as '17 : 3 : 3 2 Day(0) Day(1) Month Milliseconds')",
            "sdi":  "0 0",
            "ssm":  "0 0",
            "bit_32_parity": 1,
            "note": "The standard's 'Example ARINC 429' figure encodes time-of-day with Label = 260 (octal), Day / Month / Milliseconds fields packed into the 19-bit data field, SSM and Parity per the matrix. The label appears in red, the data in blue-green, and the parity bit in navy blue in the published illustration.",
        })
        d.setdefault("max_receivers_loading",
            "Up to 20 receivers may load the bus; their parallel input impedance must respect the 78 Ω characteristic-impedance budget of the cable.")
        d.setdefault("ssm_encoding_waveform_consequence",
            "SSM = NCD or FW does NOT change the wire-level waveform — the 2-bit field is still BRZ-encoded normally. The flag's effect is purely at the receiver's data-validity logic.")
        _write(p, d)

    # L9 INTEGRATION
    p = gd / "L9_INTEGRATION_SPEC.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("module_role",
            "Wire-level avionics serial broadcast bus defined as physical + data-encoding + word-format layers (ISO/OSI physical + data-link scope). This specification scopes the 32-bit word format, BRZ encoding on shielded 78 Ω twisted-pair, and per-equipment-type label assignments. Application layer behavior (what to do with the data in label 203) is per equipment specification.")
        d.setdefault("layered_structure_summary", [
            "Application Layer — equipment-type-specific label assignments (e.g. Air Data Computer label 203 = barometric altitude). Defined per equipment in ARINC 429 Part 1-17 Sections 78-116.",
            "Data Encoding Layer — BNR (2's complement scaled), BCD (4-bit decimal digits), Discrete (bit-field status); mixed encodings permitted within the 19-bit data field.",
            "Word / Frame Layer — 32-bit word: Label (1-8) / SDI (9-10) / Data (11-29) / SSM (30-31) / Parity (32); inter-word gap ≥ 4 bit-times NULL.",
            "Physical Layer — bipolar return-to-zero on shielded 78 Ω twisted-pair, balanced differential, ±10 V drive, ±5 V single-ended, receiver thresholds ±2.5 V, common-mode rejection ≥ 6.5 V.",
        ])
        d.setdefault("integration_overview", {
            "topology":          "Point-to-multipoint unidirectional broadcast — one transmitter, up to 20 receivers; single twisted-pair per direction.",
            "drive_type":        "Single-driver push-pull tri-state (HI / LO / NULL) on a balanced differential pair; receivers are high-impedance differential loads (≤ 20 in parallel).",
            "no_arbitration":    "Only one transmitter per bus — there is no arbitration mechanism at the protocol layer. Bidirectional avionics communication requires a pair of buses or higher-layer protocols.",
            "uniform_bit_rate":  "Bit rate is uniform and fixed within a given bus: either 12.5 kbit/s (low speed, equipment tolerance 12-14.5 kbit/s) or 100 kbit/s (high speed).",
            "max_baud":          "100 kbit/s (high speed); word time at high speed = 320 µs; minimum word-to-word period at high speed = 360 µs (32 bits + 4 NULL bit-times).",
        })
        d.setdefault("interface_categories", [
            "TRANSMITTER — single source on the bus; constantly emits 32-bit words or NULL.",
            "RECEIVER — passive monitor; up to 20 per bus; applies local label filter + parity check + SSM decode.",
            "Bidirectional communication requires two ARINC 429 buses, one in each direction.",
        ])
        d.setdefault("interconnect_topologies_supported", [
            "Single point-to-multipoint bus — one transmitter, up to 20 receivers tapped onto one twisted-pair.",
            "Bidirectional pair — two unidirectional buses (one in each direction) between subsystems that exchange data both ways.",
            "Per-equipment dedicated buses — each transmitting subsystem typically owns one or more outbound buses; receivers subscribe to subsets.",
            "Higher-layer extensions (out of ARINC 429 scope): ARINC 615 (data loader, 429 PHY), ARINC 629 (multi-transmitter TDMA), ARINC 664 Part 7 / AFDX (deterministic switched Ethernet), ARINC 708 (weather radar, 1553-derived, controlled by 429 labels).",
        ])
        d.setdefault("default_signal_values_when_omitted",
            "Idle = NULL state (0 V differential). A transmitter that has no word to send holds both wires at equal potential. Receivers ignore the NULL state except as the implicit inter-word gap delimiter.")
        d.setdefault("soc_dependent_items", [
            "Physical-layer transceiver choice (e.g. Holt HI-3585, HI-8783, Texas Instruments DEI1016, Microchip / DDC BU-69091, FPGA-soft PHY).",
            "Cable selection (78 Ω shielded twisted-pair; length-vs-bit-rate compatible).",
            "Termination strategy (often source-terminated only; the spec leaves exact termination to the integrator within the 78 Ω budget).",
            "Crystal / oscillator selection (loose; ±1 % is comfortably within BRZ eye margin at 100 kbit/s).",
            "Per-channel label-acceptance filter / CAM programming.",
            "Per-channel TX/RX FIFO sizing (label rates per equipment-type spec).",
            "Interrupt routing for label-received / parity-error / FIFO-overflow events.",
            "Power-domain (transceiver-side ±5 V or single +3.3 V/+5 V with charge-pump for the ±10 V differential drive — chip-level detail).",
        ])
        d.setdefault("low_power_modes", {
            "transmitter_idle":   "Transmitter holds bus at NULL between words / when no labels are queued; no formal sleep mode is defined at the protocol layer.",
            "receiver_passive":   "Receivers are continuously listening; per-device controllers may implement clock-gated label-filter idle as a power-saving feature, but this is not specified by ARINC 429.",
        })
        _write(p, d)

    # L10 TEST_CASES
    # v0.1.88: force-overwrite both test_cases_present AND
    # derived_compliance_test_categories (was setdefault / _empty-guarded).
    # The SPI class-universal `_apply_universal` runs UNCONDITIONALLY before
    # the Tier-3 dispatch and hard-sets `test_cases_present` to the SPI
    # wording (`d["test_cases_present"] = ...` — not setdefault) plus a
    # SPI-flavored compliance category list (clock-polarity/phase, slave-
    # select, baud-rate-divisor — none of which apply to ARINC 429's
    # broadcast BRZ wire-level protocol). Force-overwrite makes the
    # ARINC 429 wording win, and force-overwrites the category list with
    # ARINC-429-canonical scenarios (32-bit word + Label + SDI + SSM + BRZ
    # + parity + NULL inter-word gap) instead of the leaked SPI defaults.
    p = gd / "L10_TEST_CASES.json"
    if p.is_file():
        d = _read(p)
        d["test_cases_present"] = (
            "partial - ARINC 429 defines mandatory wire-level behaviors "
            "(32-bit word format, BRZ encoding, odd parity, ≥ 4-bit-time "
            "NULL gap, SSM matrix per encoding) that map directly to "
            "compliance test scenarios but does not provide a formal "
            "testbench.")
        d["derived_compliance_test_categories"] = [
                "32-bit DATA WORD with each of the three data encodings (BNR, BCD, Discrete) and mixed encodings within the data field.",
                "Bit transmission order: Bit 1 first → Bit 32 last on the wire; Label field MSB-first within bits 1-8.",
                "BRZ waveform per bit: first-half HI (or LO) + second-half NULL; verify mid-bit return-to-zero edge.",
                "Bit-rate sweep: low speed (12.5 kbit/s + 12 / 14.5 tolerance corners) and high speed (100 kbit/s).",
                "Word time at high speed = 320 µs; minimum word-to-word period ≥ 360 µs (4-bit-time NULL gap).",
                "Inter-word NULL gap < 4 bit-times → framing-error detection at receiver.",
                "Odd-parity check on bits 1-31 vs bit 32: single-bit-flip detection (all 32 positions).",
                "Odd-multiplicity bit flips (3, 5, 7, ...) detected; even-multiplicity (2, 4, 6, ...) NOT detected by parity alone.",
                "Label-filter pass/drop: label in acceptance list → forwarded; label not in list → dropped.",
                "SSM encoding per BCD data: 00 Plus/N/E/R/To/Above, 01 NCD, 10 FT, 11 Minus/S/W/L/From/Below.",
                "SSM encoding per BNR data: 00 FW, 01 NCD, 10 FT, 11 NO (with Bit 29 = sign).",
                "SSM encoding per Discrete data: 00 Verified Data/NO, 01 NCD, 10 FT, 11 FW.",
                "BNR sign bit (Bit 29) = 0 → Plus; = 1 → Minus.",
                "Electrical: drive HI ≈ +10 V differential, LO ≈ -10 V, NULL ≈ 0 V; verify receiver thresholds ±2.5 V; verify common-mode rejection ≥ 6.5 V.",
                "Receiver loading: up to 20 receivers in parallel — verify rise/fall times remain within spec under maximum loading.",
                "Cable: shielded 78 Ω twisted-pair; impedance-mismatch and reflection sensitivity at boundary cases.",
                "Periodic re-transmission cadence: each label transmitted at its fixed update rate per equipment-type spec; verify no inter-label drift over a measurement window.",
                "Label table conformance: each transmitting subsystem emits its assigned labels (per ARINC 429 Part 1-17 Sections 78-116) at the spec'd update rates.",
                "Example reference word: Label 260 (octal) with the standard's example BCD time-of-day data; verify field-by-field decode.",
            ]
        _write(p, d)

    # L11 OTP
    p = gd / "L11_OTP_CONTENT.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("otp_present", False)
        d["notes"] = (
            "ARINC 429 (Mark 33 DITS) is a wire-level avionics protocol "
            "spec; no OTP / fuse / configuration ROM at the protocol "
            "layer. Concrete ARINC 429 transceiver / controller devices "
            "(Holt HI-3584 / HI-8783, Texas Instruments DEI1016, "
            "Microchip / DDC) may use device-level OTP or non-volatile "
            "config to lock label-filter content, channel speed, or "
            "parity-enable defaults, but this is a per-device feature, "
            "not protocol-defined. The label → meaning assignments per "
            "equipment type (e.g. label 203 = barometric altitude for "
            "any Air Data Computer) are defined in ARINC 429 Part 1-17 "
            "Sections 78-116 as a paper specification, not as on-chip "
            "OTP.")
        _write(p, d)

    # L12 BEHAVIORAL_SEQUENCES
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("typical_data_word_transmit_sequence", [
            "1. Wait for inter-word gap ≥ 4 bit-times of NULL state since the last bit 32 transmitted (≥ 40 µs at 100 kbit/s).",
            "2. Transmit bit 1 first: drive HI (logical 1) or LO (logical 0) for the first half of the bit-time, then NULL for the second half. This is the start of the new 32-bit word.",
            "3. Transmit bits 2..8 (Label) — MSB-first within the label field — each bit BRZ-encoded.",
            "4. Transmit bits 9..10 (SDI).",
            "5. Transmit bits 11..29 (Data) per chosen encoding (BNR / BCD / Discrete; mixed permitted).",
            "6. Transmit bits 30..31 (SSM) per the matrix appropriate to the data representation.",
            "7. Compute odd parity over bits 1..31; set bit 32 = 0 or 1 so the total 1-bit count is odd; transmit bit 32 (Parity) as the last bit of the word.",
            "8. Hold bus at NULL for ≥ 4 bit-times before optionally starting the next word.",
        ])
        d.setdefault("typical_receive_sequence", [
            "1. Receiver monitors the differential line; while at NULL (within ±2.5 V band) the receiver counts NULL bit-times.",
            "2. When ≥ 4 NULL bit-times have elapsed and the line then transitions to HI or LO, the receiver registers this as bit 1 of a new 32-bit word.",
            "3. Receiver samples each bit during the first half of its bit-time (HI = 1, LO = 0) and confirms NULL during the second half (BRZ invariant).",
            "4. Receiver shifts 32 bits into a word register; partitions into Label (1-8) / SDI (9-10) / Data (11-29) / SSM (30-31) / Parity (32).",
            "5. Receiver computes odd parity over bits 1..31 and compares against bit 32; mismatch → discard or flag.",
            "6. Receiver applies local Label filter (per equipment-type acceptance list); unmatched labels are dropped.",
            "7. Receiver decodes SSM bits per the data representation in use (BCD / BNR / Discrete) and tags the data with NO / NCD / FT / FW (or sign for BCD).",
            "8. For BNR-encoded data, receiver reads Bit 29 as the explicit sign (0 = Plus, 1 = Minus) and the remaining 18 bits as the magnitude.",
        ])
        d.setdefault("encoding_decode_sequence_bnr", [
            "1. Extract bits 11..29 as the 19-bit data field; Bit 29 = sign, bits 11..28 = 18-bit 2's complement magnitude.",
            "2. Apply equipment-type scaling factor (per the per-label data definition) to convert the integer to engineering units (knots, feet, degrees, etc.).",
            "3. Apply SSM: 11 = Normal Operation (NO); 10 = Functional Test (FT); 01 = NCD; 00 = Failure Warning (FW).",
            "4. If SSM ≠ NO, suppress or annotate the decoded value accordingly.",
        ])
        d.setdefault("encoding_decode_sequence_bcd", [
            "1. Extract bits 11..29 as the 19-bit data field; split into up to 4 BCD nibbles + 3 bits of MSD (per the per-label data definition).",
            "2. Decode each 4-bit BCD nibble to a decimal digit (0..9; values 10..15 are illegal).",
            "3. Apply SSM: 00 = sign Plus / N / E / R / To / Above (also Normal Operation); 11 = sign Minus / S / W / L / From / Below (also Normal Operation); 01 = NCD; 10 = FT.",
            "4. Combine BCD digits + SSM sign into a signed decimal value.",
        ])
        d.setdefault("encoding_decode_sequence_discrete", [
            "1. Extract bits 11..29 as the 19-bit data field; each bit (or named bit-group) is an independent boolean / multi-state status flag.",
            "2. Apply SSM: 00 = Verified Data / Normal Operation; 01 = NCD; 10 = FT; 11 = Failure Warning.",
            "3. If SSM ≠ NO, mark all discrete fields as unverified.",
        ])
        d.setdefault("error_signalling_sequence", [
            "1. Parity error detected → receiver discards the word and may increment a per-channel parity-error counter (device-specific).",
            "2. Framing error (inter-word NULL gap < 4 bit-times, or BRZ second-half not NULL) detected → receiver discards the offending word.",
            "3. SSM = Failure Warning (FW) at the transmitter → receiver leaves the previous value in place and marks it stale.",
            "4. SSM = No Computed Data (NCD) → receiver suppresses the data (e.g. autopilot OFF causes autopilot-command words to be transmitted with NCD).",
            "5. SSM = Functional Test (FT) → receiver tags the data as test-sourced; ground-test scenario.",
            "6. There is no protocol-level ACK or NACK; recovery is by natural periodic re-transmission of every label at its fixed update rate.",
        ])
        d.setdefault("periodic_label_transmission_sequence", [
            "1. Transmitter maintains a label table with each label's nominal update rate (per equipment-type spec).",
            "2. For each label, when its next-transmission-time arrives, the transmitter queues a 32-bit word with that Label / SDI / Data / SSM / Parity and emits it after the previous word's ≥ 4-bit-time NULL gap.",
            "3. Labels are interleaved on the bus; absence of a label for longer than ~ 2x its nominal period is treated by the application as a transmitter-down condition.",
        ])
        d.setdefault("alternative_protocol_handoff", [
            "1. ARINC 429 bus may carry data-loader frames at the wire level under ARINC 615 (higher-layer protocol on top of 429 PHY).",
            "2. Bidirectional pair of 429 buses supports request/response semantics at the application layer (each bus simplex; one in each direction).",
            "3. Multi-transmitter shared media → use ARINC 629 (TDMA) or ARINC 664 Part 7 / AFDX (deterministic switched Ethernet).",
        ])
        _write(p, d)

    # L13 LAB_CALIBRATION
    p = gd / "L13_LAB_CALIBRATION.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("lab_calibration_present", False)
        d["notes"] = (
            "ARINC 429 (Mark 33 DITS) is a wire-level protocol; no "
            "analog reference / trim / calibration loop is defined at "
            "the protocol layer. The bipolar return-to-zero (BRZ) "
            "waveform has only three line states (HI, LO, NULL) with "
            "thresholds in fixed ±2.5 V receiver bands, so receiver-"
            "side calibration is unnecessary. Oscillator tolerance is "
            "a system-integration concern but is loose enough (±1 % per "
            "side comfortably fits the BRZ eye at 100 kbit/s, even "
            "tighter at 12.5 kbit/s) that no per-bus calibration is "
            "required. Transmitter-side drive-level calibration (±10 V "
            "differential, ±5 V single-ended) and voltage rise/fall "
            "time bounding are device-level (transceiver IP) concerns "
            "covered by per-device datasheets, not by ARINC 429.")
        _write(p, d)

    # L14 PROTOCOL_VERSIONING
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("spec_version",
            "ARINC Specification 429 — Mark 33 Digital Information "
            "Transfer System (DITS); reference issue Part 1-17 "
            "(Annapolis, Maryland: Aeronautical Radio, Inc., 2004-05-17)")
        if _empty(f.get("previous_versions")):
            f["previous_versions"] = [
                "ARINC 429 Mark 33 DITS — original Part 1; incremental updates Part 1-1 through Part 1-17 over decades of avionics deployment.",
                "ARINC 419 — earlier digital data transfer standard, superseded by 429 on higher-end aircraft.",
                "MIL-STD-1553 — contemporary military multidrop serial bus (1973); 429 is the civil-avionics alternative.",
            ]
        if _empty(f.get("key_changes")):
            f["key_changes"] = [
                {"version": "ARINC 429 (Mark 33)", "summary": "Defined 32-bit word format (Label / SDI / Data / SSM / Parity), BRZ encoding on shielded 78 Ω twisted-pair, two standard bit rates (12.5 / 100 kbit/s), single-transmitter ≤ 20-receiver topology, BNR / BCD / Discrete data encodings, SSM matrix per encoding."},
                {"version": "ARINC 429 Part 1-17 (2004)", "summary": "Reference issue widely cited for label assignments (Sections 78-116) and the canonical wire-level definitions reproduced in commercial-controller datasheets (Holt, AIM, Condor)."},
                {"version": "ARINC 615 (data loader)", "summary": "Layered on top of ARINC 429 physical layer to define high-speed data loader protocol for software upload."},
                {"version": "ARINC 629", "summary": "TDMA-based multi-transmitter extension to ARINC 429; intended to replace 429 but largely superseded by ARINC 664 / AFDX."},
                {"version": "ARINC 664 Part 7 / AFDX (2009)", "summary": "Deterministic switched Ethernet replacement for ARINC 429 on newer airframes (Airbus A380, Boeing 787); virtual point-to-point links replace physical 429 buses."},
                {"version": "ARINC 708", "summary": "Weather-radar protocol; simplified version of MIL-STD-1553; control of 708 components is standardized through ARINC 429 labels."},
                {"version": "ARINC 828", "summary": "Electronic Flight Bag (EFB) interface spec; among other interfaces, defines ARINC 429 interfacing in EFB context."},
            ]
        if _empty(f.get("backward_compat_traps")):
            f["backward_compat_traps"] = [
                {"trap_name": "label_renumbering_LSB_first_supplier_diagram",
                 "spec_required":     "Bit 1 is the first bit transmitted on the wire and is the LSB of the Label octal value (label MSB-first means Label-MSB is on Bit 1 numerically within the label field MSB-1 numbering).",
                 "supplier_practice": "Some suppliers (AIM GmbH, Condor Engineering) renumber the bit transmission order as '8,7,6,5,4,3,2,1,9,10,11,...,32' (LSB-0 within the label octet) to align with octet-oriented shift-register hardware.",
                 "trap":              "Hardware programmed with a 'reversed label' octet (e.g. label 0o213 written to the Label byte as 0xD1) interoperates correctly on the wire only because the renumbering is purely a software/diagram convention; mixing tools that use opposite conventions causes label-table lookups to disagree."},
                {"trap_name": "BCD_SSM_vs_BNR_SSM_overlap",
                 "spec_required":     "SSM (bits 30-31) encoding is data-representation-dependent: BCD: 00=+/N/E/R/To/Above, 01=NCD, 10=FT, 11=-/S/W/L/From/Below; BNR: 00=FW, 01=NCD, 10=FT, 11=NO; Discrete: 00=NO, 01=NCD, 10=FT, 11=FW.",
                 "receiver_required": "Receiver must know the per-label encoding (BCD vs BNR vs Discrete) to decode SSM correctly.",
                 "trap":              "Mis-classifying a BCD label as BNR causes SSM=00 to be misread as Failure Warning instead of Plus/N/E/R/To/Above (or vice versa)."},
                {"trap_name": "bit_rate_tolerance_band",
                 "low_speed_spec":    "12.5 kbit/s standard.",
                 "equipment_practice":"Equipment commonly tolerates 12-14.5 kbit/s on the low-speed bus.",
                 "trap":              "Mixing a strict 12.5 kbit/s receiver with a transmitter at the 14.5 kbit/s edge may exit the BRZ eye at the receiver's sample point."},
                {"trap_name": "max_receivers_loading",
                 "spec_required":     "≤ 20 receivers per bus.",
                 "trap":              "Exceeding 20 receivers degrades the BRZ rise/fall times and parallel input impedance below the 78 Ω budget; receivers near the bus end see slewed transitions."},
            ]
        f.setdefault("version_naming_history_note",
            "ARINC 429 is the predominant avionics serial data bus on most higher-end commercial and transport aircraft, deployed since the late 1970s. Newer airframes (Airbus A380, Boeing 787) migrate to AFDX (ARINC 664 Part 7) deterministic Ethernet, retaining ARINC 429 only for legacy interfaces. ARINC 419 was the predecessor; MIL-STD-1553 is the contemporary military equivalent. 429 is unidirectional simplex; bidirectional avionics traffic requires a pair of 429 buses or an ARINC 629 / 664 / 615 extension.")
        d["fields"] = f
        _write(p, d)

    # L15 ENCODING_TABLES
    p = gd / "L15_ENCODING_TABLES.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("word_format_table", {
            "header_columns": ["Field", "Bits", "Width", "Form"],
            "rows": [
                ["Label",  "1-8",   "8 bits",  "Octal label code; MSB-first within label field; identifies data type per equipment-type table"],
                ["SDI",    "9-10",  "2 bits",  "Source/Destination Identifier"],
                ["Data",   "11-29", "19 bits", "BNR (Bit 29 = sign), BCD (4-bit nibbles), or Discrete (bit-field status); mixed permitted"],
                ["SSM",    "30-31", "2 bits",  "Sign/Status Matrix; encoding depends on data representation"],
                ["Parity", "32",    "1 bit",   "Odd parity over bits 1..31"],
            ],
            "note": "Each ARINC 429 word is a 32-bit fixed-length frame transmitted Bit 1 first, Bit 32 last over the wire. The standard's word-format figure draws bits from 32 (left) to 1 (right).",
        })
        f.setdefault("ssm_encoding_table_bcd", {
            "header_columns": ["Bit 31", "Bit 30", "BCD Data Meaning"],
            "rows": [
                ["0", "0", "Plus, North, East, Right, To, Above"],
                ["0", "1", "No Computed Data (NCD)"],
                ["1", "0", "Functional Test (FT)"],
                ["1", "1", "Minus, South, West, Left, From, Below"],
            ],
        })
        f.setdefault("ssm_encoding_table_bnr", {
            "header_columns": ["Bit 31", "Bit 30", "BNR Data Meaning"],
            "rows": [
                ["0", "0", "Failure Warning (FW)"],
                ["0", "1", "No Computed Data (NCD)"],
                ["1", "0", "Functional Test (FT)"],
                ["1", "1", "Normal Operation (NO)"],
            ],
            "note": "In BNR, Bit 29 within the data field carries the sign separately (0 = Plus, 1 = Minus).",
        })
        f.setdefault("ssm_encoding_table_discrete", {
            "header_columns": ["Bit 31", "Bit 30", "Discrete Data Meaning"],
            "rows": [
                ["0", "0", "Verified Data, Normal Operation"],
                ["0", "1", "No Computed Data (NCD)"],
                ["1", "0", "Functional Test (FT)"],
                ["1", "1", "Failure Warning (FW)"],
            ],
        })
        f.setdefault("bnr_sign_table", {
            "header_columns": ["Bit 29", "BNR Sign Meaning"],
            "rows": [
                ["0", "Plus, North, East, Right, To, Above"],
                ["1", "Minus, South, West, Left, From, Below"],
            ],
        })
        f.setdefault("bit_rate_table", {
            "header_columns": ["Speed", "Nominal Bit Rate", "Bit Time", "Word Time (32 bits)", "Inter-word Gap (≥ 4 bit-times)"],
            "rows": [
                ["Low speed",  "12.5 kbit/s (equipment tolerance 12-14.5 kbit/s)", "80 µs",  "2560 µs",  "≥ 320 µs"],
                ["High speed", "100 kbit/s",                                       "10 µs",  "320 µs",   "≥ 40 µs"],
            ],
        })
        f.setdefault("line_state_table", {
            "header_columns": ["Line State", "Differential Voltage", "Single-Ended (each wire)", "Logical Meaning"],
            "rows": [
                ["HI",   "+10 V (typical)", "+5 V / -5 V (DataA / DataB)", "logical 1 (first half of bit-time)"],
                ["LO",   "-10 V (typical)", "-5 V / +5 V (DataA / DataB)", "logical 0 (first half of bit-time)"],
                ["NULL", "0 V",             "0 V / 0 V",                    "second half of every bit-time; inter-word gap; idle"],
            ],
        })
        f.setdefault("receiver_threshold_table", {
            "header_columns": ["Differential at Receiver", "Decoded State"],
            "rows": [
                ["> +2.5 V", "HI (logical 1)"],
                ["< -2.5 V", "LO (logical 0)"],
                ["-2.5 V ≤ V_diff ≤ +2.5 V", "NULL"],
            ],
            "note": "Common-mode rejection ≥ 6.5 V.",
        })
        f.setdefault("parity_scheme",
            "Odd parity over bits 1..31; parity bit on bit 32. Detects all single-bit errors and any odd number of bit errors per 32-bit word.")
        f.setdefault("example_word_label_260_octal",
            "Label = 260 (octal); SDI = 00; Data field (bits 11-29) encodes time-of-day BCD: '17 : 3 : 3 2(Day) Day(0) Day(1) Month Milliseconds' per the standard's Example ARINC 429 figure; SSM = 00; Parity (bit 32) = 1.")
        if _empty(f.get("tables")):
            f["tables"] = [
                "32-bit ARINC 429 word format — Label(1-8) / SDI(9-10) / Data(11-29) / SSM(30-31) / Parity(32).",
                "SSM encoding per data representation (BCD / BNR / Discrete) — bits 30, 31.",
                "BNR sign at Bit 29.",
                "Two standard bit rates: 12.5 kbit/s (low) / 100 kbit/s (high).",
                "Line states HI / LO / NULL — drive ±10 V, receiver thresholds ±2.5 V, common-mode rejection ≥ 6.5 V.",
                "Label assignments per equipment type — ARINC 429 Part 1-17 Sections 78-116.",
            ]
        d["fields"] = f
        _write(p, d)

    # L16 COMPLIANCE_PROPERTIES
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("must_have_properties", [
            "Transmit each word as a 32-bit fixed-length sequence with Bit 1 first → Bit 32 last on the wire.",
            "Bits 1-8 = Label (octal); Label is transmitted MSB-first within the label field.",
            "Bits 9-10 = SDI (Source/Destination Identifier).",
            "Bits 11-29 = Data field (19 bits); encodings BNR / BCD / Discrete; mixed permitted.",
            "Bits 30-31 = SSM (Sign/Status Matrix); encoding depends on data representation.",
            "Bit 32 = Parity bit; odd parity over bits 1-31.",
            "Bipolar return-to-zero (BRZ / BPRZ) line encoding: HI = +10 V differential first half + NULL second half; LO = -10 V differential first half + NULL second half.",
            "Inter-word gap ≥ 4 bit-times of NULL state (≥ 40 µs at 100 kbit/s; ≥ 320 µs at 12.5 kbit/s).",
            "Bit rate: 12.5 kbit/s (low speed; equipment tolerance band 12-14.5 kbit/s) or 100 kbit/s (high speed); a single bus runs at one fixed speed.",
            "Single transmitter, ≤ 20 receivers per bus.",
            "Shielded 78 Ω twisted-pair cabling.",
            "Drive levels: ±10 V differential (e.g. +5 V on DataA / -5 V on DataB); ±5 V single-ended.",
            "Receiver thresholds: differential > +2.5 V = HI; < -2.5 V = LO; in between = NULL.",
            "Common-mode rejection ≥ 6.5 V.",
            "For BNR-encoded data, Bit 29 = sign (0 = Plus, 1 = Minus); SSM carries Status Matrix only.",
            "SSM encoding per BCD / BNR / Discrete matrix exactly as specified in the standard's SSM table.",
            "Label assignments per equipment type follow ARINC 429 Part 1-17 Sections 78-116.",
        ])
        f.setdefault("must_not_have_properties", [
            "More than one transmitter on a single bus (no protocol-layer arbitration is defined; use ARINC 629 / 664 for multi-transmitter).",
            "More than 20 receivers on a single bus (impedance budget violation).",
            "Inter-word gap shorter than 4 bit-times of NULL state.",
            "Bit transmitted with first-half NULL or second-half non-NULL (BRZ invariant violation).",
            "Drive level outside the ±10 V differential drive envelope.",
            "Receiver decoding a line state from a differential within the -2.5 V to +2.5 V band as HI or LO (must decode as NULL).",
            "Use of SSM encoding inconsistent with the per-label data representation (BCD label decoded with BNR SSM table, or vice versa).",
            "Use of bit-rate outside the two standard speeds (12.5 kbit/s low or 100 kbit/s high).",
            "Even number of bit errors per word — undetected by parity alone (must be caught by higher-layer redundancy or natural periodic re-transmission).",
        ])
        f.setdefault("compliance_failure_modes", [
            {"mode": "PARITY ERROR",                "trigger": "Receiver computes odd parity over bits 1-31 and finds it disagrees with bit 32."},
            {"mode": "FRAMING ERROR",               "trigger": "Inter-word NULL gap < 4 bit-times, or bit-time second half not at NULL, or first-half drive not HI/LO."},
            {"mode": "SSM FAILURE WARNING (FW)",    "trigger": "Transmitter signals failure via SSM = FW (BCD: not applicable; BNR: 00; Discrete: 11)."},
            {"mode": "SSM NO COMPUTED DATA (NCD)",  "trigger": "Transmitter signals data missing/unavailable via SSM = NCD (01 for BCD / BNR / Discrete)."},
            {"mode": "SSM FUNCTIONAL TEST (FT)",    "trigger": "Transmitter signals data is test-sourced via SSM = FT (10 for BCD / BNR / Discrete)."},
            {"mode": "LABEL UNKNOWN",               "trigger": "Receiver decodes a Label not in its local acceptance list; word is dropped (not an error, but a filter event)."},
            {"mode": "LINE GLITCH",                 "trigger": "Differential briefly outside ±2.5 V band but inside the bit's second-half NULL window; receiver may reject the bit-time."},
        ])
        f.setdefault("performance_of_error_detection", [
            "All single-bit errors per 32-bit word: detected (probability 1) by odd parity.",
            "All odd-multiplicity bit errors: detected by parity.",
            "Even-multiplicity bit errors: NOT detected by parity alone.",
            "Line-glitch shorter than half a bit-time: rejected by BRZ second-half NULL invariant.",
            "Sustained line-stuck failure: detected by missing labels at their nominal periodic update rate (application-layer timeout).",
            "EMI from neighboring cables: bounded by RTCA DO-160 environmental category compliance + cable shielding + balanced differential + BPRZ encoding.",
        ])
        f.setdefault("recovery_time_bound",
            "ARINC 429 does not specify a hard recovery time. In practice, recovery from a corrupted word is at most one nominal periodic update period of the affected label (per equipment-type spec) — i.e. the next periodic transmission supersedes the corrupted one.")
        d["fields"] = f
        _write(p, d)

    # L17 CHANNEL_SIGNAL_CATALOG
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        # Force-overwrite channels (earlier steps may have written CAN /
        # AXI / SPI leaning content; ARINC 429 shape is single simplex
        # broadcast channel).
        f["channels"] = [
            {
                "name": "ARINC 429 bus (single twisted-pair, simplex)",
                "direction": "unidirectional broadcast — one transmitter ↔ up to 20 receivers",
                "purpose": "Shielded 78 Ω twisted-pair carrying balanced differential bipolar return-to-zero (BRZ) signaling; carries 32-bit fixed-length words.",
                "physical_realization": "Two-wire shielded twisted-pair (DataA + DataB); ±10 V differential drive; receiver thresholds ±2.5 V; common-mode rejection ≥ 6.5 V; supports up to 20 high-impedance differential receivers.",
            },
        ]
        f["logical_signal_states"] = [
            {"name": "HI",   "value": "+10 V differential",  "rule": "First half of bit-time for a logical 1; receiver decodes as HI if differential > +2.5 V."},
            {"name": "LO",   "value": "-10 V differential",  "rule": "First half of bit-time for a logical 0; receiver decodes as LO if differential < -2.5 V."},
            {"name": "NULL", "value": "0 V differential",    "rule": "Second half of every bit-time; inter-word gap (≥ 4 bit-times); idle. Receiver decodes as NULL if -2.5 V ≤ differential ≤ +2.5 V."},
        ]
        f["frame_fields_as_signal_segments"] = [
            {"name": "LABEL",          "type": "address",          "form": "8 bits (bits 1-8); octal label; MSB-first within label field"},
            {"name": "SDI",            "type": "metadata",          "form": "2 bits (bits 9-10); Source/Destination Identifier"},
            {"name": "DATA",           "type": "payload",           "form": "19 bits (bits 11-29); BNR / BCD / Discrete; mixed permitted"},
            {"name": "BNR_SIGN",       "type": "sign",              "form": "1 bit (bit 29 within Data field; BNR-encoded labels only)"},
            {"name": "SSM",            "type": "status",            "form": "2 bits (bits 30-31); Sign/Status Matrix per data representation"},
            {"name": "PARITY",         "type": "integrity",         "form": "1 bit (bit 32); odd parity over bits 1..31"},
            {"name": "INTER_WORD_GAP", "type": "interframe space",  "form": "≥ 4 bit-times of NULL state (≥ 40 µs at 100 kbit/s)"},
        ]
        f["channel_counts"] = {
            "logical_channels": 1,
            "logical_line_states": 3,
            "word_fields": 5,
            "bit_halves_per_bit_time": 2,
            "data_encodings_supported": 3,
            "ssm_encodings_per_data_representation": 3,
            "standard_bit_rates": 2,
            "max_receivers_per_bus": 20,
            "max_transmitters_per_bus": 1,
        }
        f["dependency_graph"] = {
            "common_rule": "Single shared broadcast channel: all up-to-20 receivers see every bit. BRZ encoding makes each bit self-clocking; mid-bit return-to-zero is the clock-recovery edge.",
            "data_dependency": "Receiver samples each bit during the first half (HI/LO) and confirms NULL during the second half. Parity bit (bit 32) closes the integrity over bits 1..31. SSM (bits 30-31) decode requires knowing the per-label data representation.",
            "framing_dependency": "Implicit; inter-word gap = ≥ 4 bit-times NULL is the only word delimiter.",
        }
        f["handshake_pairs"] = [
            {"name": "NONE",                "from": "transmitter",  "to": "receivers", "rule": "ARINC 429 has no per-word handshake. The transmitter broadcasts continuously; receivers are passive monitors with no upstream feedback path."},
            {"name": "PERIODIC_RETRANSMIT", "from": "transmitter",  "to": "receivers", "rule": "Each label is sent at its fixed periodic update rate per equipment-type spec; this is the recovery mechanism for corrupted or missing words (no protocol-level NACK)."},
        ]
        f.setdefault("ordering_rules", {
            "within_a_word":         "Bit 1 first → Bit 32 last on the wire.",
            "within_label_field":    "MSB-first (Label bit 1 in MSB-1 numbering is the LSB of the label octal; Label bit 8 is the MSB).",
            "within_data_field":     "Per the per-label data definition; numerically, Bit 29 is the MSB of BNR/BCD numeric data when illustrated with Bit 32 on the left.",
            "global_ordering":       "Multiple labels from one transmitter are interleaved on the bus per their periodic update schedules; no priority arbitration.",
        })
        d["fields"] = f
        _write(p, d)

    # L18 INTERCONNECT_TOPOLOGY
    p = gd / "L18_INTERCONNECT_TOPOLOGY.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f["topology_type"] = (
            "Point-to-multipoint unidirectional broadcast — single "
            "transmitter ↔ up to 20 receivers on one shielded 78 Ω "
            "twisted-pair per direction.")
        f["supported_topologies"] = [
            {"name": "Single simplex bus",                  "description": "One transmitter drives one shielded 78 Ω twisted-pair; up to 20 receivers tap onto the pair. Most messages are a single 32-bit data word."},
            {"name": "Bidirectional pair (two buses)",      "description": "Two simplex 429 buses between subsystems that exchange data both ways — one bus per direction."},
            {"name": "Per-equipment dedicated outbound bus","description": "Each transmitting subsystem typically owns one or more outbound buses; receivers subscribe to subsets of labels."},
            {"name": "ARINC 615 data-loader overlay",       "description": "Higher-layer data-loader protocol layered on top of ARINC 429 PHY."},
            {"name": "Replaced on newer airframes",         "description": "On Airbus A380 and Boeing 787, deterministic switched Ethernet (ARINC 664 Part 7 / AFDX) replaces 429 for most data links; 429 remains for legacy interfaces."},
        ]
        f["master_slave_role_summary"] = [
            {"role": "TRANSMITTER",         "description": "Single source on the bus; constantly emits 32-bit words or NULL; maintains label-table + per-label update-rate schedule."},
            {"role": "RECEIVER",            "description": "Passive monitor; up to 20 per bus; runs local Label filter + parity check + SSM decode."},
            {"role": "no arbitration role", "description": "ARINC 429 has no contention or arbitration — only one transmitter per bus."},
        ]
        f["interconnect_role"] = (
            "There is no protocol-layer interconnect, router, or bridge "
            "in ARINC 429. The bus is a flat shared simplex medium; any "
            "of the up-to-20 receivers can decode any word, and label-"
            "acceptance filtering is purely local at each receiver. "
            "Avionics integration concatenates many individual 429 buses "
            "(often dozens to hundreds per aircraft) into a star/mesh "
            "wired interconnect at the airframe level.")
        f["ordering_guarantees"] = {
            "single_bus":      "All receivers see every word simultaneously (modulo cable propagation); data consistency is automatic.",
            "no_arbitration":  "Words from one transmitter are emitted in the order the transmitter's scheduler interleaves them — typically a fixed priority-by-update-rate scheme.",
            "label_periodicity":"Each label is transmitted at its nominal fixed update rate per equipment-type spec; receivers may rely on this cadence to detect transmitter-down conditions.",
        }
        f.setdefault("memory_vs_peripheral_regions",
            "Not applicable — ARINC 429 is wire-level. Per-controller register / FIFO / label-filter regions live in the device datasheet (Holt HI-3584, TI DEI1016, etc.), not in the ARINC 429 specification.")
        f.setdefault("slave_classification", {
            "addressable_target":   "Not applicable — ARINC 429 is content-addressed by Label (octal). All up-to-20 receivers see every frame; selection is local Label-filter match.",
            "data_producer":        "Exactly one transmitter per bus emits 32-bit words encoding labels assigned to that equipment type.",
            "data_consumer":        "Up to 20 receivers per bus, each with its own Label-acceptance list.",
        })
        f.setdefault("default_signal_values_evidence_tables", [
            "Technical description — medium and signaling (BRZ on shielded 78 Ω twisted-pair).",
            "Word format — bits 1-32 with Label / SDI / Data / SSM / Parity fields.",
            "Bit numbering, transmission order, and bit significance — Bit 1 first on the wire.",
            "Labels — equipment-type-specific octal assignments (ARINC 429 Part 1-17 Sections 78-116).",
            "Protection from interference — RTCA DO-160 environmental compliance + cable shielding + balanced differential + BPRZ encoding.",
        ])
        f.setdefault("wake_up_topology", {
            "wake_up_trigger": "Not applicable — ARINC 429 has no sleep/wake-up state machine. The transmitter is continuously active (emitting NULL when idle).",
            "wake_up_message": "Not applicable.",
            "post_wake_sync":  "Receivers continuously track BRZ transitions; they resynchronize automatically on every word's bit 1.",
        })
        d["fields"] = f
        _write(p, d)

    # L19 PDK
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("constraints_present", False)
        f["notes"] = (
            "ARINC 429 (Mark 33 DITS) is a wire-level avionics protocol "
            "spec; no PDK / SDC / floorplan constraints at the protocol "
            "layer. Per-transceiver integration constraints — pad ring "
            "sizing for ±10 V differential drive, charge-pump or "
            "external ±5 V supply choice, slew-rate-controlled output "
            "driver to bound rise/fall times per ARINC 429 EMI envelope, "
            "common-mode rejection ≥ 6.5 V at the receiver input — live "
            "in the per-device datasheet (Holt HI-3584 / HI-8783, Texas "
            "Instruments DEI1016, Microchip / DDC BU-69091), not in the "
            "ARINC 429 specification. Avionics-grade environmental "
            "qualification (RTCA DO-160 categories) is the system-level "
            "qualification, not a chip-level PDK constraint.")
        d["fields"] = f
        _write(p, d)

    # L20 DFT
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("dft_present", False)
        f["notes"] = (
            "ARINC 429 does not specify DFT / scan / BIST at the "
            "protocol layer. Protocol-level self-checking is provided "
            "by (a) odd parity per 32-bit word over bits 1-31, (b) BRZ "
            "self-clocking with mandatory mid-bit return-to-zero edge, "
            "(c) ≥ 4-bit-time NULL inter-word gap framing, (d) SSM "
            "(bits 30-31) per-word health flags (NO / NCD / FT / FW), "
            "and (e) the natural periodic re-transmission cadence of "
            "avionics labels per equipment-type spec. Commercial "
            "transceiver / controller IP (Holt HI-3584 with built-in "
            "loopback BIT mode, AIM GmbH, Condor Engineering) adds "
            "standard scan insertion + BIT (Built-In-Test) modes at the "
            "integrator level, but those are device-specific and not "
            "defined by ARINC 429 itself.")
        d["fields"] = f
        _write(p, d)

    # L21 POWER_INTENT
    p = gd / "L21_POWER_INTENT.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("power_intent_present", False)
        f["low_power_modes_summary"] = {
            "transmitter_idle":   "Transmitter holds bus at NULL state (0 V differential) between words / when no labels are queued. No formal sleep state is defined at the protocol layer; static-current drain through the ±5 V line drivers is bounded by device-level design only.",
            "receiver_passive":   "Receivers are continuously listening; per-device controllers may implement clock-gated label-filter idle as a power-saving optimization, but this is not specified by ARINC 429.",
            "no_wake_up_message": "ARINC 429 has no wake-up frame or sleep handshake — no equivalent to CAN's lowest-priority wake-up identifier.",
        }
        f["notes"] = (
            "Power-domain partitioning is deferred to SoC + transceiver "
            "IP. ARINC 429's only protocol-level power feature is the "
            "implicit NULL-state idle between words. Avionics power "
            "supplies and grounding follow RTCA / SAE conventions but "
            "are not specified by ARINC 429. Per-channel TX driver "
            "disable + RX clock gating + dynamic-voltage scaling on the "
            "digital decode logic are standard device-level features "
            "(Holt HI-3584 etc.), not protocol-level.")
        d["fields"] = f
        _write(p, d)

    # L22 VERIFICATION_PLAN
    p = gd / "L22_VERIFICATION_PLAN.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("verification_plan_present", "implicit")
        if _empty(f.get("verification_categories_derived_from_spec")):
            f["verification_categories_derived_from_spec"] = [
                "32-bit DATA WORD transmission with Bit 1 first → Bit 32 last.",
                "Label field (bits 1-8) MSB-first within label field; octal label round-trip via reference table.",
                "SDI field (bits 9-10) round-trip — value-preserving on the wire.",
                "Data field (bits 11-29) round-trip for each of three encodings (BNR / BCD / Discrete) and mixed encodings within one word.",
                "BNR sign bit (Bit 29) sweep: 0 = Plus, 1 = Minus; 2's complement magnitude in bits 11-28.",
                "BCD nibble decode: 4-bit nibbles in {0..9}; values 10..15 illegal.",
                "Discrete bit-field decode per per-label assignment.",
                "SSM (bits 30-31) decode per BCD / BNR / Discrete matrix:",
                "  BCD: 00 Plus/N/E/R/To/Above, 01 NCD, 10 FT, 11 Minus/S/W/L/From/Below",
                "  BNR: 00 FW, 01 NCD, 10 FT, 11 NO",
                "  Discrete: 00 Verified/NO, 01 NCD, 10 FT, 11 FW",
                "Odd parity (bit 32) over bits 1..31: single-bit-flip detection in all 32 positions; odd-multiplicity detection.",
                "Bit rate sweep: low speed = 12.5 kbit/s (also test 12 / 14.5 tolerance edges) and high speed = 100 kbit/s.",
                "Bit-time = 10 µs (high) / 80 µs (low); word-time = 320 µs (high) / 2560 µs (low).",
                "Inter-word NULL gap ≥ 4 bit-times; word-to-word period ≥ 360 µs at high speed.",
                "Framing fault: inter-word gap < 4 bit-times → receiver discards next word.",
                "BRZ waveform per bit: first-half drive (HI / LO) + second-half NULL; second-half non-NULL → framing fault.",
                "Drive level: HI ≈ +10 V differential, LO ≈ -10 V, NULL ≈ 0 V; ±5 V single-ended on each wire.",
                "Receiver thresholds: differential > +2.5 V = HI; < -2.5 V = LO; in-band = NULL.",
                "Common-mode rejection ≥ 6.5 V.",
                "Cable: shielded 78 Ω twisted-pair; verify rise/fall times with up to 20 parallel receivers.",
                "Label filter pass/drop: configured labels forwarded; unconfigured labels dropped.",
                "Periodic-label update-rate cadence: verify no drift over a measurement window.",
                "Multi-receiver consistency: all up-to-20 receivers decode the same 32-bit word identically.",
                "Example word: Label 260 (octal) BCD time-of-day per the standard's Example ARINC 429 figure.",
                "Negative tests: > 20 receivers loaded; > 1 transmitter on bus (electrical conflict); bit rate outside the two standard speeds.",
            ]
        f.setdefault("notes",
            "ARINC 429 (Mark 33 DITS) does not include a formal verification plan; categories above are derived from the technical description, word format, SSM matrix, electrical, and labels sections of ARINC Specification 429 Part 1-17. Industry-standard avionics test rigs (Avionics Interface Technologies, AIM GmbH ABC429, Condor Engineering ARINC analyzers, Ballard Technology programming manuals) implement these scenarios programmatically.")
        d["fields"] = f
        _write(p, d)

    # L23 SECURITY
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("security_requirements_present", False)
        f["notes"] = (
            "ARINC 429 (Mark 33 DITS) is a wire-level avionics protocol "
            "spec; no confidentiality / integrity / authentication "
            "features are defined. ARINC 429 is unidirectional "
            "broadcast — every receiver on the bus sees every 32-bit "
            "word. The built-in security primitive is the per-word odd-"
            "parity bit (bit 32 over bits 1..31), which guards against "
            "accidental corruption only, not against tampering. "
            "Physical isolation (shielded 78 Ω twisted-pair, balanced "
            "differential, RTCA DO-160 environmental qualification) "
            "plus avionics-grade airframe-level segregation provides "
            "anti-tamper defense in the deployment context. Modern "
            "avionics security (signed software upload via ARINC 615A, "
            "authenticated AFDX virtual links on ARINC 664 Part 7, "
            "secure boot of avionics LRUs) is layered on top of or "
            "replaces ARINC 429 — not part of ARINC 429 itself.")
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
def is_arinc429(blob: str) -> bool:
    """Content-only `arinc429` detector (importable, lifted from the runner)
    WITH a FOREIGN-PRIMARY DEFER.

    Empty-safe. Reads ONLY ``blob`` (spec text). Byte-for-byte the same
    boolean the runner used inline for the structural signature below.

    FOREIGN-PRIMARY DEFER (mirrors `is_mipi`'s defer doctrine and the AFDX
    sibling-MUTEX — general, content-only, no chip/SKU/benchmark literal as
    detection logic): the ARINC-429 structural signature is necessary but NOT
    sufficient. AFDX (ARINC 664 Part 7) specs cite ARINC 429 / Mark 33 / DITS
    as the LEGACY point-to-point bus that AFDX's deterministic switched
    Ethernet replaces, so an AFDX doc trips the `Mark 33`+`DITS` branch below
    and the generic ARINC-429 synth would inject 32-bit-word / Label / SSM
    avionics-bus content into an AFDX spec's L-docs.

    AFDX-primary is the VESA-style structural fingerprint that is ABSENT from
    a genuine ARINC 429 point-to-point spec: the Virtual Link (VL) abstraction
    plus AFDX's determinism mechanisms (Bandwidth Allocation Gap, dual-network
    Network A / Network B redundancy with redundancy management) plus the
    ARINC 664 / AFDX name anchor. A real ARINC 429 spec has none of these
    switched-fabric tokens, so deferring on them is safe.
    """
    if not blob:
        return False
    low = blob.lower()

    # --- FOREIGN-PRIMARY DEFER (blob's true subject is AFDX, not ARINC 429). -
    _afdx_name = (
        "afdx" in low
        or "avionics full-duplex switched ethernet" in low
        or "avionics full duplex switched ethernet" in low)
    _arinc664 = (
        "arinc 664" in low or "arinc664" in low
        or "664 part 7" in low or "664p7" in low or "664-p7" in low)
    _virtual_link = (
        "virtual link" in low or "vl id" in low or "vlid" in low
        or "virtual link identifier" in low)
    _bag = (
        "bandwidth allocation gap" in low
        or (bool(re.search(r"\bbag\b", low))
            and ("allocation gap" in low
                 or "inter-frame" in low or "interframe" in low
                 or "power of two" in low or "power-of-two" in low)))
    _dual_network = (
        ("network a" in low and "network b" in low)
        or "dual redundant" in low or "redundant network" in low)
    # AFDX-primary: the switched-fabric VL structure plus a determinism
    # mechanism (BAG or dual-network redundancy), anchored by the AFDX /
    # ARINC 664 name. None of these appear in a real ARINC 429 spec.
    afdx_primary = (
        (_afdx_name or _arinc664)
        and _virtual_link
        and (_bag or _dual_network))
    if afdx_primary:
        return False

    # --- STRUCTURAL ARINC 429 signature (unchanged from the runner's inline
    #     detector). ---
    return bool(
        ("ARINC 429" in blob and "Label" in blob
         and ("SSM" in blob or "Sign/Status" in blob))
        or ("Mark 33" in blob and "DITS" in blob)
        or ("avionics" in low
            and "32-bit word" in blob and "Label" in blob))
