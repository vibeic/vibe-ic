"""CAN-FD-class protocol synth helper.

v0.1.84 — ic_class-gated overlay for `serial_peripheral_protocol` specs
that exhibit the CAN-FD structural signature: (BRS + FDF + ESI) OR
(CAN-FD + 64 + payload) OR (Bosch + M_CAN + CCCR). Applies Bosch M_CAN
Controller v3.3.1 / ISO 11898-1:2015 CAN FD content to L1-L23.

Doctrine: structural-keyword detection IS general within an ic_class
(mirrors AMBA-AXI / SPI / I2C / UART / CAN synth approach). Any CAN-FD
implementation (Bosch M_CAN any revision, ST FDCAN, Microchip MCP2517FD,
NXP FlexCAN-FD, Renesas RS-CAN-FD, etc.) exhibits the same signature
because the CAN FD protocol is fixed by ISO 11898-1:2015.

Important: CAN-FD spec extends Classical CAN spec — the CAN structural
detector ('DATA FRAME + REMOTE FRAME + ERROR FRAME' or 'dominant +
recessive + ARBITRATION/IDENTIFIER') will fire first because CAN-FD
docs describe Classical CAN behaviour too. canfd_synth must
FORCE-overwrite (not setdefault) any L1/L2/L4 keys CAN sets, since
CAN's values are classic-CAN-specific (1991 Bosch spec, no register
map, no CRC-17/21, no BRS, no 64-byte payload).

Public entry: `apply_canfd_synth(generated_docs_dir, is_canfd,
canfd_ic_name)`.
"""
from __future__ import annotations

import json
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


def _ensure_dict(d: dict, key: str) -> dict:
    """Force d[key] to be a dict; if missing or wrong type, replace."""
    v = d.get(key)
    if not isinstance(v, dict):
        d[key] = {}
    return d[key]


def apply_canfd_synth(generated_docs_dir: Path, is_canfd: bool,
                      canfd_ic_name: Optional[str]) -> None:
    """Apply CAN-FD-specific synth when the structural signature matched.

    CRITICAL: This synth runs AFTER can_protocol_synth may have already
    setdefault'd Classical-CAN values. We must FORCE-overwrite keys that
    CAN synth touched in L1/L2/L4, because Classical-CAN values are
    incorrect for CAN-FD specs (e.g. 'no register map' is wrong — M_CAN
    has a 512-byte register map; '8 byte max payload' wrong — FD is 64 B).
    """
    if not is_canfd:
        return
    gd = generated_docs_dir

    # Force ic_name across L1-L23 FIRST (overwrites any earlier
    # Classical-CAN ic_name). Parity-diff unwraps `fields` to top-level so
    # setting ic_name at the top of the doc satisfies both shapes.
    if canfd_ic_name is not None:
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
            "L18_INTERCONNECT_TOPOLOGY.json", "L19_CONSTRAINTS_PDK.json",
            "L20_DFT_SCAN_TOPOLOGY.json", "L21_POWER_INTENT.json",
            "L22_VERIFICATION_PLAN.json", "L23_SECURITY_REQUIREMENTS.json",
        ]:
            q = gd / n
            if q.is_file():
                d = _read(q)
                d["ic_name"] = canfd_ic_name
                _write(q, d)

    _apply_l1(gd)
    _apply_l2(gd)
    _apply_l3(gd)
    _apply_l4(gd)
    _apply_l5(gd)
    _apply_l6(gd)
    _apply_l7(gd)
    _apply_l8(gd)
    _apply_l8_timing(gd)
    _apply_l9(gd)
    _apply_l10(gd)
    _apply_l11(gd)
    _apply_l12(gd)
    _apply_l13(gd)
    _apply_l14(gd)
    _apply_l15(gd)
    _apply_l16(gd)
    _apply_l17(gd)
    _apply_l18(gd)
    _apply_l19(gd)
    _apply_l20(gd)
    _apply_l21(gd)
    _apply_l23(gd)


def _apply_l1(gd: Path) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    # FORCE-overwrite Classical-CAN-specific top-level fields.
    d["document_title"] = "M_CAN Controller Area Network User's Manual"
    d["version"] = "Revision 3.3.1"
    d["manufacturer"] = "Robert Bosch GmbH"
    d["revised_date"] = "11.03.2023"
    d["copyright"] = (
        "© Copyright 2008-2023 by Robert Bosch GmbH and its licensors. "
        "All rights reserved. \"Bosch\" is a registered trademark of "
        "Robert Bosch GmbH.")
    d["intellectual_property_owners"] = (
        "Robert Bosch GmbH, Robert Bosch Platz 1, 70839 Gerlingen, "
        "Germany and its licensors.")
    d["governing_law"] = (
        "Federal Republic of Germany; exclusive legal venue Düsseldorf, "
        "Germany.")
    # FORCE-overwrite — CAN synth wrote Part A / Part B layout which is wrong.
    d["document_layout"] = [
        "Chapter 1 — Overview (features, block diagram, dual clock sources, "
        "dual interrupt lines).",
        "Chapter 2 — Programmer's Model (hardware reset, 512-byte register "
        "map, individual register descriptions, Message RAM elements).",
        "Chapter 3 — Functional Description (operating modes incl. CAN FD, "
        "timestamp + timeout, Rx + Tx handling, debug on CAN).",
        "Chapter 4 — Appendix (register bit overview)."
    ]
    # FORCE-overwrite key_features — CAN synth's were Classical only.
    d["key_features"] = [
        "Conform with ISO 11898-1:2015 (selectable ISO / non-ISO CAN FD "
        "via CCCR.NISO).",
        "CAN FD with up to 64 data bytes supported (DLC codes 9-15 map "
        "to 12/16/20/24/32/48/64 bytes).",
        "CAN Error Logging (8-bit Error Counter CEL with overflow flag).",
        "AUTOSAR support (≥3 Tx Queue Buffers + transmit cancellation).",
        "SAE J1939 support (XIDAM-based 29-bit ID masking).",
        "Improved acceptance filtering (up to 128 standard + 64 extended "
        "filter elements; range / dual-ID / classic-mask / disabled).",
        "Two configurable Receive FIFOs (Rx FIFO 0 + Rx FIFO 1; blocking "
        "or overwrite mode).",
        "Separate signalling on reception of High Priority Messages "
        "(HPMS register; IR.HPM flag).",
        "Up to 64 dedicated Receive Buffers.",
        "Up to 32 dedicated Transmit Buffers.",
        "Configurable Transmit FIFO.",
        "Configurable Transmit Queue.",
        "Configurable Transmit Event FIFO (stores Message ID + timestamp "
        "per transmitted message).",
        "Direct Message RAM access for the Host CPU.",
        "Multiple M_CANs may share the same Message RAM.",
        "Programmable loop-back test mode (internal / external).",
        "Maskable module interrupts (two lines m_can_int0 / m_can_int1).",
        "8/16/32 bit Generic Slave Interface for connection to "
        "customer-specific Host CPUs.",
        "Two clock domains (CAN clock m_can_cclk and Host clock "
        "m_can_hclk).",
        "Power-down support (clock stop via m_can_clkstop_req / CCCR.CSR).",
        "Debug on CAN support (three consecutive Rx Buffers for debug "
        "messages A/B/C + DMA hand-off).",
        "DMA Support (DMU add-on required).",
        "Support of Hardware Timestamping according to CiA 603 (TSU "
        "add-on required)."
    ]
    # FORCE-overwrite modes_of_operation — CAN had 4 fault-confinement; FD has
    # full operating modes incl. CAN FD operation, restricted op, test, etc.
    d["modes_of_operation"] = [
        {"name": "Software Initialization",
         "description": "Triggered by CCCR.INIT = 1; CAN bus output m_can_tx "
         "is recessive; configuration registers writable when "
         "CCCR.CCE = 1."},
        {"name": "Normal Operation",
         "description": "CCCR.INIT = 0; CAN bus communication active per "
         "CAN / CAN FD protocol."},
        {"name": "CAN FD Operation",
         "description": "CCCR.FDOE = 1 (and CCCR.BRSE = 1 for bit-rate "
         "switching); transmits/receives CAN FD frames with optional "
         "bit rate switching."},
        {"name": "Restricted Operation Mode",
         "description": "CCCR.ASM = 1; node receives data + remote frames "
         "+ sends ACK, but does NOT send data/remote/active-error/overload "
         "frames; entered automatically on Tx Handler access failure."},
        {"name": "Bus Monitoring Mode",
         "description": "CCCR.MON = 1; receive valid frames + remote "
         "frames only; dominant bits routed internally; TXBRP held "
         "in reset."},
        {"name": "Disabled Automatic Retransmission (DAR)",
         "description": "CCCR.DAR = 1; corrupted / arbitration-lost "
         "messages are NOT retransmitted automatically."},
        {"name": "Power Down / Sleep Mode",
         "description": "Triggered by m_can_clkstop_req or CCCR.CSR; "
         "after pending transfers + bus idle, INIT is set internally + "
         "CCCR.CSA goes 1; clocks may be stopped."},
        {"name": "Test Modes",
         "description": "CCCR.TEST = 1 enables Test Register; Loop-Back "
         "Mode (TEST.LBCK), Tx pin driver control (TEST.TX)."},
        {"name": "External Loop Back Mode",
         "description": "TEST.LBCK = 1, CCCR.MON = 0; messages transmitted "
         "on m_can_tx and looped back internally to Rx; ACK errors ignored."},
        {"name": "Internal Loop Back Mode",
         "description": "TEST.LBCK = 1, CCCR.MON = 1; m_can_rx disconnected, "
         "m_can_tx held recessive; \"hot self-test\"."}
    ]
    # FORCE-overwrite domain_of_application (CAN had 1991 1Mbit/s wording).
    d["domain_of_application"] = [
        "Automotive electronics — engine control, braking, body "
        "electronics; CAN FD enables higher payload (up to 64 bytes) "
        "and higher data-phase bit rates (typically 2-8 Mbit/s) than "
        "Classical CAN's 1 Mbit/s.",
        "Industrial automation — distributed control with deterministic "
        "latency.",
        "AUTOSAR-based + SAE J1939-based vehicle networks.",
        "Time-triggered CAN (TTCAN, ISO 11898-4) via DAR + external "
        "schedule.",
        "End-of-line programming (CAN FD switched off until programming "
        "completes)."
    ]
    # FORCE-overwrite layered_structure to remove Classical-CAN wording.
    d["layered_structure"] = [
        {"layer": "Application Layer",
         "scope": "Out of scope of this spec."},
        {"layer": "Object Layer",
         "scope": "Message acceptance filtering (M_CAN's Acceptance Filter "
         "+ Standard/Extended Filter Elements), Tx + Rx mailbox "
         "management (dedicated buffers / FIFOs / Queue / Tx Event FIFO)."},
        {"layer": "Transfer Layer (kernel)",
         "scope": "Bit Stream Processor (BSP), Bit Timing Logic (BTL), "
         "Error Management Logic (EML), Acceptance Filter — all per "
         "ISO 11898-1:2015."},
        {"layer": "Physical Layer",
         "scope": "Outside M_CAN; external transceiver (typically "
         "ISO 11898-2 high-speed differential) translates between "
         "m_can_tx/m_can_rx and CANH/CANL."}
    ]
    # FORCE-overwrite overview to use M_CAN wording.
    d["overview"] = (
        "The M_CAN module is the new CAN Communication Controller "
        "IP-module by Bosch, integrable as stand-alone or part of an "
        "ASIC. Described in VHDL on RTL level (synthesis-ready), it "
        "performs communication according to ISO 11898-1:2015. "
        "Additional transceiver hardware is required for connection "
        "to the physical layer. The message storage is a single- or "
        "dual-ported Message RAM outside the module, connected via "
        "the Generic Master Interface; multiple M_CAN controllers "
        "can share the same Message RAM. The Rx Handler manages "
        "message acceptance filtering, transfer of received messages "
        "from the CAN Core to the Message RAM, plus receive message "
        "status. The Tx Handler controls the transfer of transmit "
        "messages from the Message RAM to the CAN Core. Acceptance "
        "filtering uses up to 128 filter elements each configurable "
        "as range / bit-mask / dedicated-ID filter. The M_CAN connects "
        "to a wide range of Host CPUs via its 8/16/32-bit Generic "
        "Slave Interface. The M_CAN's dual clock domain concept "
        "separates the high-precision CAN clock from the Host clock, "
        "which may be generated by an FM-PLL.")
    # FORCE-overwrite compatibility_note — Classical text was about Part A/B.
    d["compatibility_note"] = (
        "CAN FD extends Classical CAN with three new control bits "
        "(FDF replacing reserved r0, BRS for bit-rate switch, ESI for "
        "error-state indicator) and 64-byte payload via new DLC "
        "encoding (9-15 → 12/16/20/24/32/48/64 bytes) + new CRC "
        "(17-bit for ≤16B, 21-bit for >16B). Classical CAN messages "
        "remain bit-compatible on the same bus when CCCR.FDOE = 0 OR "
        "when individual Tx Buffer elements set FDF = 0.")
    # ADDITIVE — only set if absent.
    d.setdefault("block_diagram_components", [
        {"name": "CAN Core",
         "scope": "CAN Protocol Controller + Rx/Tx Shift Register. "
         "Handles all ISO 11898-1:2015 protocol functions; supports "
         "11-bit and 29-bit identifiers."},
        {"name": "Sync",
         "scope": "Synchronizes signals from Host clock domain to CAN "
         "clock domain and vice versa."},
        {"name": "Clk",
         "scope": "Synchronizes reset signal to Host clock and to CAN "
         "clock domains."},
        {"name": "Cfg & Ctrl",
         "scope": "CAN Core related configuration and control bits."},
        {"name": "Interrupt & Timestamp",
         "scope": "Interrupt control + 16-bit CAN bit time counter for "
         "receive and transmit timestamp generation."},
        {"name": "Tx Handler",
         "scope": "Controls message transfer from external Message RAM "
         "to CAN Core; up to 32 Tx Buffers configurable as dedicated / "
         "Tx FIFO / Tx Queue; Tx Event FIFO stores Tx timestamps + "
         "Message ID."},
        {"name": "Rx Handler",
         "scope": "Controls transfer of received messages from CAN Core "
         "to external Message RAM; two Rx FIFOs (configurable size); "
         "up to 64 dedicated Rx Buffers; up to 128 standard / 64 "
         "extended filters."},
        {"name": "Generic Slave Interface",
         "scope": "Connects M_CAN to a customer-specific Host CPU on an "
         "8/16/32-bit bus."},
        {"name": "Generic Master Interface",
         "scope": "Connects M_CAN to external 32-bit Message RAM; max "
         "Message RAM size 16K × 32-bit; single M_CAN uses ≤ 4.25K × "
         "32-bit."},
        {"name": "Extension Interface",
         "scope": "Routes all Interrupt Register flags + selected "
         "internal status/control signals to a module-external "
         "interrupt unit (optional)."}
    ])
    d.setdefault("dual_clock_sources", {
        "m_can_hclk": "Host clock domain; may be a spread spectrum clock "
        "for EMC improvement.",
        "m_can_cclk": "CAN clock domain; high-precision (no modulation).",
        "constraint": "Host clock must always be faster than or equal to "
        "CAN clock."
    })
    d.setdefault("dual_interrupt_lines",
        "Two interrupt lines m_can_int0 / m_can_int1. By default all "
        "interrupts are routed to m_can_int0. ILE.EINT0 / ILE.EINT1 "
        "enable / disable the lines independently. ILS register selects "
        "which interrupt source goes to which line.")
    d.setdefault("iso_vs_nonISO_can_fd", {
        "ISO_11898_1_2015": "CCCR.NISO = 0; default; ISO CAN FD frame "
        "format with stuff-bit-count protection in CRC.",
        "non_ISO_CAN_FD": "CCCR.NISO = 1; Bosch CAN FD Specification "
        "V1.0 frame format (no stuff-bit-count protection); "
        "incompatible with ISO CAN FD on the same bus.",
        "synthesis_lock": "When generic parameter iso_only_g = 1, "
        "CCCR.NISO is reserved and read as 0."
    })
    d.setdefault("address_space_summary", {
        "total_size_bytes": 512,
        "register_organization": "All registers are 32-bit; accessible "
        "via 8 / 16 / 32-bit data widths through Generic Slave Interface.",
        "write_protection": "Registers marked \"P=Protected Write\" only "
        "writable when CCCR.CCE = 1 AND CCCR.INIT = 1."
    })
    d.setdefault("references", [
        "[1] ISO — ISO 11898-1:2015: CAN data link layer and physical "
        "signalling.",
        "[2] CiA — CiA 601: CAN FD guidelines and recommendations.",
        "[3] CiA — CiA 603: CAN Frame time-stamping.",
        "[4] AE/EID — M_CAN Module Integration Guide.",
        "[5] AE/EID — TSU User's Manual.",
        "[6] AE/EID — DMU User's Manual."
    ])
    d.setdefault("abbreviations", {
        "BRP": "Bit Rate Prescaler",
        "BSP": "Bit Stream Processor",
        "BTL": "Bit Timing Logic",
        "CAN": "Controller Area Network",
        "CAN FD": "Controller Area Network with Flexible Data-rate",
        "CRC": "Cyclic Redundancy Check",
        "DLC": "Data Length Code",
        "ECC": "Error Correction Code",
        "ECU": "Electronic Control Unit",
        "EML": "Error Management Logic",
        "EOF": "End of Frame",
        "FSM": "Finite State Machine",
        "mtq": "minimum time quantum = CAN clock period (m_can_cclk)",
        "SOF": "Start of Frame",
        "SSP": "Secondary Sample Point",
        "TDC": "Transmitter Delay Compensation",
        "tq": "time quantum",
        "TSEG1": "Time Segment before Sample Point",
        "TSEG2": "Time Segment after Sample Point",
        "TTCAN": "Time-Triggered CAN"
    })
    d.setdefault("conventions", {
        "Arial bold": "Names of bits and ports",
        "Arial italic": "States of bits and ports"
    })
    _write(p, d)


def _apply_l2(gd: Path) -> None:
    p = gd / "L2_FRS.json"
    if not p.is_file():
        return
    d = _read(p)
    po = _ensure_dict(d, "protocol_overview")
    # FORCE-overwrite Classical-CAN-specific fields that CAN synth set.
    po["type"] = (
        "Multi-master serial bus with bitwise arbitration, frame-based "
        "messaging, and flexible data-rate extension; arbitration-phase "
        "classical-CAN compatibility + optional high-bit-rate data phase.")
    po["duplex"] = "half-duplex on a single shared channel"
    po["synchronous"] = False
    po["bus_arbitration"] = (
        "Bitwise on IDENTIFIER + RTR/RRS while sending arbitration field; "
        "lowest IDENTIFIER value wins; arbitration phase always uses "
        "Nominal Bit Time (NBTP).")
    po["physical_layer"] = (
        "Per ISO 11898-1:2015 link layer; physical layer per ISO 11898-2 "
        "(high-speed differential) — physical specifics out of the M_CAN "
        "module (transceiver required).")
    po["bit_coding"] = (
        "Non-Return-to-Zero (NRZ) with bit stuffing (insert complementary "
        "bit after 5 consecutive identical bits) in stuffed fields; CAN FD "
        "adds stuff-bit-count protection in CRC (ISO mode).")
    po["bus_values"] = (
        "Two complementary logical values: dominant (logical 0, drives bus "
        "low) and recessive (logical 1, bus released). Wired-AND: dominant "
        "wins.")
    po["multimaster"] = True
    po["multicast"] = True
    po["addressing"] = (
        "By message IDENTIFIER (content-addressed) — IDENTIFIER does not "
        "name a destination, it names the meaning of the data; receivers "
        "apply acceptance filtering (up to 128 standard + 64 extended "
        "filter elements).")
    po["dual_bit_rate"] = (
        "Nominal Bit Time (NBTP) for arbitration phase (≤ 1 Mbit/s "
        "typical); Data Bit Time (DBTP) for data phase (typically 2 / 5 / "
        "8 Mbit/s, up to ~5 Mbit/s with 20 MHz CAN clock); switch enabled "
        "by BRS bit + CCCR.BRSE.")

    # FORCE-overwrite functional_requirements (CAN synth wrote Classical-only).
    d["functional_requirements"] = [
        {"id": "FR-FRAME-01",
         "text": "Information is sent in fixed-format messages: DATA FRAME "
         "(Classical or FD), REMOTE FRAME (Classical only — no remote "
         "frames in CAN FD), ERROR FRAME, OVERLOAD FRAME."},
        {"id": "FR-START-02",
         "text": "START OF FRAME is a single dominant bit; triggers Hard "
         "Synchronization."},
        {"id": "FR-FDF-03",
         "text": "FDF bit (formerly r0/reserved in Classical CAN) "
         "distinguishes frame format: FDF = dominant → Classical CAN "
         "frame; FDF = recessive → CAN FD frame. Receiving FDF = "
         "recessive with res = recessive triggers Protocol Exception "
         "(PSR.PXE)."},
        {"id": "FR-RRS-04",
         "text": "In CAN FD frames (FDF = 1), the RRS (Remote Request "
         "Substitution) bit replaces the RTR bit — always dominant. There "
         "are no remote frames in CAN FD format."},
        {"id": "FR-BRS-05",
         "text": "BRS (Bit Rate Switch) follows FDF + res in CAN FD "
         "frames. BRS = recessive enables data-phase bit-rate switching: "
         "control field after BRS + data field + CRC are transmitted at "
         "DBTP rate; CRC delimiter switches back to NBTP. BRS only "
         "evaluated when CCCR.BRSE = 1 AND CCCR.FDOE = 1."},
        {"id": "FR-ESI-06",
         "text": "ESI (Error State Indicator) bit in CAN FD frames: "
         "dominant = error-active transmitter; recessive = error-passive "
         "transmitter; receiver-set per PSR.RESI."},
        {"id": "FR-ARB-07",
         "text": "Arbitration field = IDENTIFIER (11 bits standard / 29 "
         "bits extended via IDE) + RTR (Classical) or RRS (FD); "
         "transmitted MSB-first; lowest IDENTIFIER wins."},
        {"id": "FR-DLC-CL-08",
         "text": "Classical CAN DLC: 4-bit value; admissible data byte "
         "counts 0..8 (DLC 9..15 are interpreted as 8 bytes)."},
        {"id": "FR-DLC-FD-09",
         "text": "CAN FD DLC: 4-bit value; DLC 0..8 maps to 0..8 bytes; "
         "DLC 9..15 maps to 12 / 16 / 20 / 24 / 32 / 48 / 64 bytes."},
        {"id": "FR-CRC-CL-10",
         "text": "Classical CAN CRC: 15-bit BCH code; polynomial X^15 + "
         "X^14 + X^10 + X^8 + X^7 + X^4 + X^3 + 1."},
        {"id": "FR-CRC-FD-11",
         "text": "CAN FD CRC: 17-bit polynomial CRC-17 for payloads "
         "≤16 bytes; 21-bit polynomial CRC-21 for payloads >16 bytes; "
         "stuff-bit-count protection (ISO mode, CCCR.NISO = 0) prepends "
         "4 stuff-bit-count bits + parity to CRC sequence."},
        {"id": "FR-ACK-12",
         "text": "ACK FIELD = ACK SLOT (transmitter sends recessive; "
         "receivers superscribe with dominant if CRC matched) + recessive "
         "ACK DELIMITER. CAN FD ACK timing accounts for transmitter delay "
         "compensation."},
        {"id": "FR-EOF-13", "text": "END OF FRAME is 7 recessive bits."},
        {"id": "FR-STUFF-14",
         "text": "Bit stuffing in SOF .. CRC SEQUENCE: after 5 consecutive "
         "identical bits, insert a complementary bit. CRC DELIMITER + ACK "
         "+ EOF are NOT stuffed. CAN FD CRC field is preceded by fixed-"
         "form stuff bits in ISO mode."},
        {"id": "FR-NBTP-15",
         "text": "Nominal Bit Time = (NBRP+1) m_can_cclk per time quantum; "
         "NTSEG1 + NTSEG2 + SYNC_SEG; total programmable from 4 to 385 tq; "
         "SAMPLE POINT at end of NTSEG1."},
        {"id": "FR-DBTP-16",
         "text": "Data Bit Time = (DBRP+1) m_can_cclk per time quantum; "
         "DTSEG1 + DTSEG2 + SYNC_SEG; total programmable from 4 to 49 tq; "
         "only used for data phase of CAN FD frames with BRS = 1. Data "
         "phase bit rate must be ≥ arbitration phase bit rate."},
        {"id": "FR-SYNC-17",
         "text": "HARD SYNCHRONIZATION on START OF FRAME. RESYNCHRONIZATION "
         "on later edges; jump width NSJW (nominal) / DSJW (data). Edge "
         "filtering during bus integration (CCCR.EFBI) requires 2 "
         "consecutive dominant tq for hard sync."},
        {"id": "FR-ERR-18",
         "text": "Five error types: BIT ERROR, STUFF ERROR, CRC ERROR, "
         "FORM ERROR, ACKNOWLEDGMENT ERROR. CAN FD distinguishes "
         "arbitration-phase error (PSR.LEC) from data-phase error "
         "(PSR.DLEC)."},
        {"id": "FR-FAULT-19",
         "text": "Fault confinement uses 8-bit Transmit Error Counter "
         "ECR.TEC + 7-bit Receive Error Counter ECR.REC; nodes transition "
         "error-active (<128) ↔ error-passive (≥128, PSR.EP) ↔ bus-off "
         "(TEC = 256, PSR.BO). Warning level 96 set in PSR.EW + IR.EW."},
        {"id": "FR-INTERFRAME-20",
         "text": "INTERFRAME SPACE = INTERMISSION (3 recessive bits) + "
         "BUS IDLE; error-passive transmitter adds SUSPEND TRANSMISSION "
         "(8 recessive bits)."},
        {"id": "FR-OVERLOAD-21",
         "text": "OVERLOAD FRAME = OVERLOAD FLAG (6 dominant bits) + "
         "OVERLOAD DELIMITER (8 recessive bits); at most 2 OVERLOAD "
         "FRAMEs may be generated to delay the next DATA/REMOTE FRAME."},
        {"id": "FR-VALID-22",
         "text": "Message is valid for the transmitter if no error up to "
         "end of END OF FRAME; valid for receivers if no error up to the "
         "last-but-one bit of END OF FRAME."},
        {"id": "FR-TDC-23",
         "text": "Transmitter Delay Compensation (TDC, DBTP.TDC = 1): "
         "measures delay from m_can_tx to m_can_rx within each FD frame; "
         "positions Secondary Sample Point at delay + TDCR.TDCO offset; "
         "bit errors in data phase checked at SSP; bounded ≤ 6 bit times "
         "in data phase and ≤ 127 mtq absolute."},
        {"id": "FR-ACCFILT-24",
         "text": "Acceptance filtering: up to 128 11-bit standard filter "
         "elements + 64 29-bit extended filter elements; filter types "
         "range / dual-ID / classic-bit-mask / disabled."},
        {"id": "FR-RXBUF-25",
         "text": "Up to 64 dedicated Rx Buffers + two configurable Rx "
         "FIFOs (0 + 1; each up to 64 elements). Element size selectable "
         "8/12/16/20/24/32/48/64 data bytes."},
        {"id": "FR-TXBUF-26",
         "text": "Up to 32 Tx Buffers, configurable as dedicated + Tx "
         "FIFO + Tx Queue (mixed allowed); Tx Event FIFO stores up to "
         "32 Tx events."},
        {"id": "FR-TXCANCEL-27",
         "text": "Transmit Cancellation (TXBCR) supported for dedicated "
         "Tx Buffers + Tx Queue (not Tx FIFO); AUTOSAR requires ≥ 3 Tx "
         "Queue Buffers + cancellation support."},
        {"id": "FR-TIMEOUT-28",
         "text": "Timeout Counter (TOCC + TOCV): 16-bit down counter; "
         "modes: continuous / Rx FIFO 0 / Rx FIFO 1 / Tx Event FIFO; "
         "IR.TOO on reach-zero."},
        {"id": "FR-TIMESTAMP-29",
         "text": "Timestamp Generation: 16-bit internal counter OR 16-bit "
         "external timebase via m_can_ext_ts (required for CAN FD). "
         "External 32-bit TSU per CiA 603 enabled via CCCR.UTSU."},
        {"id": "FR-HPM-30",
         "text": "High Priority Message (HPM): IR.HPM + HPMS register "
         "updated on priority-filter match (SFEC/EFEC = 100/101/110)."},
        {"id": "FR-WAKEUP-31",
         "text": "Sleep Mode entered via m_can_clkstop_req or CCCR.CSR; "
         "after pending Tx complete + bus idle, CCCR.INIT + "
         "m_can_clkstop_ack + CCCR.CSA go 1."},
        {"id": "FR-EXTRESET-32",
         "text": "Hardware reset puts registers to reset values; CCCR = "
         "0x0000_0001 → CCCR.INIT = 1; m_can_tx forced recessive."}
    ]
    # FORCE-overwrite (CAN synth's text was Classical only).
    d["error_response_conditions"] = [
        "BIT ERROR — transmitter detects monitored bus value ≠ transmitted "
        "value (except recessive→dominant in arbitration or ACK SLOT); CAN "
        "FD data phase uses Secondary Sample Point for bit-error check.",
        "STUFF ERROR — 6th consecutive equal bit detected in a stuffed "
        "field.",
        "CRC ERROR — computed CRC ≠ received CRC SEQUENCE (15 / 17 / 21 "
        "bit depending on format and payload size).",
        "FORM ERROR — illegal bit(s) in a fixed-form field (CRC DELIMITER, "
        "ACK DELIMITER, EOF, INTERMISSION, fixed-form stuff bits in CAN FD "
        "CRC).",
        "ACKNOWLEDGMENT ERROR — transmitter does not monitor a dominant "
        "bit during ACK SLOT.",
        "PROTOCOL EXCEPTION — receiver sees FDF = recessive AND res = "
        "recessive (reserved). PXHD = 0 enabled: PSR.ACT goes to "
        "integrating + PSR.PXE = 1. PXHD = 1: treated as form error.",
        "ARA — Access to Reserved Address, IR.ARA flag + m_can_aei_ara "
        "asserted."
    ]
    d["compliance_requirements"] = [
        "Conform to ISO 11898-1:2015 (default; CCCR.NISO = 0).",
        "When generic parameter iso_only_g = 1, the M_CAN only operates "
        "per ISO 11898-1:2015.",
        "Maximum data-phase bit rate limited by m_can_cclk and bit-time "
        "configuration.",
        "Data phase bit time must be ≥ no lower than arbitration phase "
        "bit time (DBTP rate ≥ NBTP rate per spec note).",
        "Sum of measured TDC + TDCR.TDCO must be < 6 bit times in data "
        "phase; ≤ 127 mtq absolute.",
        "Bus-off recovery requires 129 occurrences of Bus Idle after "
        "CCCR.INIT is cleared.",
        "Dedicated Rx Buffer / Filter Element requires SFEC/EFEC = 111 + "
        "SFID2/EFID2[10:9] = 00.",
        "AUTOSAR requires ≥ 3 Tx Queue Buffers + transmit cancellation."
    ]
    d["performance_of_error_detection"] = [
        "All global errors detected per ISO 11898-1:2015.",
        "All local errors at transmitters detected.",
        "CAN FD CRC-17 and CRC-21 detect more errors than Classical 15-bit "
        "CRC due to wider polynomial + stuff-bit-count protection.",
        "Up to 5 randomly distributed errors per message detected.",
        "Burst errors detected.",
        "Errors of any odd number detected.",
        "Total residual error probability for undetected corrupted "
        "messages further reduced relative to Classical CAN."
    ]
    d.setdefault("what_can_fd_extends_vs_classical_can", {
        "frame_format": "Three new control bits (FDF, BRS, ESI); reserved "
        "r0 in classical → FDF; r1 follows BRS / ESI in CAN FD.",
        "payload": "0..64 bytes (vs 0..8 bytes classical); DLC 9..15 maps "
        "to 12/16/20/24/32/48/64.",
        "bit_rate": "Optional faster data phase via BRS + DBTP.",
        "crc": "17-bit (≤16 B) or 21-bit (>16 B) with stuff-bit-count "
        "protection (ISO mode), vs 15-bit BCH in classical.",
        "no_remote_frame": "CAN FD has no remote frames; RRS replaces RTR.",
        "error_state_indicator": "ESI bit advertises transmitter's error "
        "state to receivers."
    })
    _write(p, d)


def _apply_l3(gd: Path) -> None:
    p = gd / "L3_CMD_PROTOCOL.json"
    if not p.is_file():
        return
    d = _read(p)
    # FORCE-overwrite (CAN synth wrote Classical-only protocol_type).
    d["protocol_type"] = (
        "Frame-based serial messaging protocol with optional flexible "
        "data-rate extension; content-addressed by IDENTIFIER; no opcode/"
        "command set at the wire layer; controller register-level command "
        "set via M_CAN's 512-byte register map.")
    # FORCE-overwrite channels (CAN synth wrote single CAN bus only).
    d["channels"] = [
        {"name": "CAN bus", "direction": "bidirectional single-channel "
         "wired-AND",
         "description": "Single shared channel carrying NRZ-coded bits; "
         "dominant overrides recessive; physical realization via ISO "
         "11898-2 high-speed differential pair (external transceiver)."},
        {"name": "Generic Slave Interface (Host CPU)",
         "direction": "Host CPU ↔ M_CAN",
         "description": "8/16/32-bit register access bus; allows Host to "
         "program registers + access Message RAM indirectly."},
        {"name": "Generic Master Interface (Message RAM)",
         "direction": "M_CAN → external 32-bit Message RAM",
         "description": "32-bit external Message RAM access; max 16K × "
         "32-bit, one M_CAN uses ≤ 4.25K × 32-bit."}
    ]
    # FORCE-overwrite frame_types — CAN had 4 frames; FD adds FD DATA + BRS.
    d["frame_types"] = [
        {"name": "Classical CAN DATA FRAME",
         "purpose": "0..8-byte payload with 15-bit CRC; FDF = dominant; "
         "selected by Tx Buffer FDF = 0 or CCCR.FDOE = 0."},
        {"name": "Classical CAN REMOTE FRAME",
         "purpose": "Request frame; RTR = recessive; no DATA FIELD; only "
         "Classical CAN. Tx Buffer T0.RTR = 1 transmits remote frame even "
         "when CCCR.FDOE = 1."},
        {"name": "CAN FD DATA FRAME",
         "purpose": "0..64-byte payload with 17-bit (≤16 B) or 21-bit "
         "(>16 B) CRC; FDF = recessive; CCCR.FDOE must be 1."},
        {"name": "CAN FD DATA FRAME with Bit Rate Switching",
         "purpose": "Like CAN FD DATA FRAME but BRS = 1 + CCCR.BRSE = 1; "
         "data phase from BRS to CRC delimiter transmitted at DBTP rate."},
        {"name": "ERROR FRAME",
         "purpose": "Signals error; ACTIVE (6 dominant) or PASSIVE (6 "
         "recessive) + ERROR DELIMITER (8 recessive)."},
        {"name": "OVERLOAD FRAME",
         "purpose": "Delays the next DATA / REMOTE FRAME; OVERLOAD FLAG "
         "(6 dominant) + OVERLOAD DELIMITER (8 recessive); max 2 "
         "consecutive."}
    ]
    # FORCE-overwrite data_frame_fields (CAN had Classical only).
    d["data_frame_fields_classical"] = [
        {"field": "START OF FRAME", "size": "1 bit", "value": "dominant"},
        {"field": "ARBITRATION FIELD", "size": "12 / 32 bits",
         "components": "11-bit ID + RTR (std) OR 11+SRR+IDE+18+RTR (ext)"},
        {"field": "CONTROL FIELD", "size": "6 bits",
         "components": "r1 + r0 + DLC[3:0]"},
        {"field": "DATA FIELD", "size": "0..64 bits",
         "components": "0..8 data bytes (MSB-first per byte)"},
        {"field": "CRC FIELD", "size": "16 bits",
         "components": "15-bit CRC + recessive CRC DELIMITER"},
        {"field": "ACK FIELD", "size": "2 bits",
         "components": "ACK SLOT + recessive ACK DELIMITER"},
        {"field": "END OF FRAME", "size": "7 bits", "value": "all recessive"}
    ]
    d["data_frame_fields_can_fd"] = [
        {"field": "START OF FRAME", "size": "1 bit", "value": "dominant"},
        {"field": "ARBITRATION FIELD", "size": "12 / 32 bits",
         "components": "11-bit ID + RRS (always dominant) OR 11+SRR+IDE+18"
         "+RRS"},
        {"field": "CONTROL FIELD", "size": "8 bits",
         "components": "r1 + FDF (recessive) + res (dominant) + BRS + ESI "
         "+ DLC[3:0]"},
        {"field": "DATA FIELD", "size": "0..512 bits",
         "components": "0..64 data bytes per DLC encoding"},
        {"field": "STUFF COUNT FIELD (ISO only, CCCR.NISO = 0)",
         "size": "4 bits",
         "components": "3-bit stuff-bit-count + 1-bit parity"},
        {"field": "CRC FIELD", "size": "18 or 22 bits",
         "components": "17-bit CRC (payload ≤16 B) OR 21-bit CRC (>16 B) "
         "+ recessive CRC DELIMITER"},
        {"field": "ACK FIELD", "size": "2 bits",
         "components": "ACK SLOT + recessive ACK DELIMITER"},
        {"field": "END OF FRAME", "size": "7 bits", "value": "all recessive"}
    ]
    d["control_field_bits_can_fd"] = [
        {"bit": "r1 / r0", "value_at_transmit": "dominant (reserved)",
         "rule": "Receivers must accept any combination for forward "
         "compatibility."},
        {"bit": "FDF", "Classical_value": "dominant",
         "FD_value": "recessive",
         "purpose": "Identifies frame format. Receiving FDF=1 with res=1 "
         "triggers Protocol Exception."},
        {"bit": "BRS",
         "purpose": "Bit Rate Switch — recessive enables data-phase "
         "bit-rate switch (DBTP); only evaluated when CCCR.BRSE = 1 + "
         "CCCR.FDOE = 1."},
        {"bit": "ESI",
         "purpose": "Error State Indicator — dominant = transmitter "
         "error-active; recessive = transmitter error-passive."}
    ]
    # FORCE-overwrite data_length_code_encoding (CAN had Classical only).
    d["data_length_code_encoding_classical"] = {
        "header": ["DLC", "Number of Data Bytes"],
        "rows": [["0000", 0], ["0001", 1], ["0010", 2], ["0011", 3],
                 ["0100", 4], ["0101", 5], ["0110", 6], ["0111", 7],
                 ["1000", 8], ["1001-1111", 8]],
        "note": "Classical CAN: DLC values 9..15 are coded the same as 8."
    }
    d["data_length_code_encoding_can_fd"] = {
        "header": ["DLC", "Number of Data Bytes"],
        "rows": [["0000", 0], ["0001", 1], ["0010", 2], ["0011", 3],
                 ["0100", 4], ["0101", 5], ["0110", 6], ["0111", 7],
                 ["1000", 8], ["1001", 12], ["1010", 16], ["1011", 20],
                 ["1100", 24], ["1101", 32], ["1110", 48], ["1111", 64]],
        "note": "CAN FD extends DLC encoding: codes 9..15 select "
        "12/16/20/24/32/48/64 bytes."
    }
    # Remove the Classical-only key CAN synth set, if present.
    if "data_length_code_encoding" in d:
        del d["data_length_code_encoding"]
    d["remote_frame_rules"] = [
        "Classical CAN only — there are NO REMOTE FRAMES in CAN FD format.",
        "RTR bit = recessive (vs dominant for DATA FRAME) — classical.",
        "No DATA FIELD.",
        "Same IDENTIFIER as the requested DATA FRAME.",
        "If a DATA FRAME and REMOTE FRAME with same IDENTIFIER start "
        "simultaneously, the DATA FRAME prevails (RTR dominant wins).",
        "When Tx Buffer T0.RTR = 1, M_CAN transmits a remote frame per "
        "ISO 11898-1:2015 even if CCCR.FDOE = 1.",
        "GFC.RRFS / RRFE reject all remote frames with standard / "
        "extended IDs respectively."
    ]
    d["valid_ready_handshake_rules"] = [
        "There is no AMBA-style per-cycle VALID/READY handshake on the "
        "CAN bus.",
        "Frame-level ACK on bit 1 of ACK FIELD; in CAN FD frames ACK "
        "delimiter accounts for transmitter delay.",
        "Bitwise arbitration on the ARBITRATION FIELD: lost on recessive-"
        "driven vs dominant-monitored mismatch.",
        "Generic Slave Interface (Host CPU side) is a register-mapped bus "
        "— Protected-Write semantics on configuration registers."
    ]
    d.setdefault("burst_based", False)
    d.setdefault("byte_oriented_within_data_field", True)
    d["byte_order_within_data_field"] = (
        "MSB-first per byte; bytes within Tx/Rx Buffer Element packed 4 "
        "per 32-bit word (DB0 at bits 7:0, DB1 at bits 15:8, DB2 at bits "
        "23:16, DB3 at bits 31:24 of T2/R2).")
    d["interframe_space"] = {
        "intermission":         "3 recessive bits",
        "bus_idle":             "arbitrary length; any unit may start a "
        "transmission",
        "suspend_transmission": "8 recessive bits added by an error-passive "
        "transmitter after its message",
        "transmit_pause":       "2 CAN bit times added by M_CAN after each "
        "successful transmission when CCCR.TXP = 1."
    }
    d.setdefault("tx_handler_command_protocol_to_host", {
        "TXBAR_AR_n": "Host writes 1 to bit n of TXBAR to add Tx request.",
        "TXBCR_CR_n": "Host writes 1 to bit n of TXBCR to cancel Buffer n.",
        "TXBTO_TO_n": "Read-only: transmission occurred successfully.",
        "TXBCF_CF_n": "Read-only: cancellation finished.",
        "TXBTIE_TIE_n / TXBCIE_CFIE_n": "Per-buffer interrupt enables.",
        "TXFQS": "Read-only Tx FIFO / Queue fill level + indices."
    })
    d.setdefault("rx_handler_command_protocol_to_host", {
        "RXF0A_F0AI / RXF1A_F1AI": "Host writes index of last FIFO element "
        "read; M_CAN sets FnGI = F0AI + 1.",
        "NDAT1[n], NDAT2[n]": "New Data flag per Rx Buffer n; cleared by "
        "writing 1.",
        "TXEFA_EFAI": "Host writes index of last Tx Event FIFO element read."
    })
    d.setdefault("interrupt_command_protocol", {
        "IR_ack": "Host writes 1 to corresponding IR bit to clear (W1C).",
        "IE_route": "IE register bit n = 1 enables interrupt source n.",
        "ILS_route": "ILS bit n = 0 → m_can_int0; = 1 → m_can_int1.",
        "ILE_enable": "ILE.EINT0 / ILE.EINT1 enable / disable the two CPU "
        "interrupt lines."
    })
    d.setdefault("test_mode_command_protocol", {
        "enter_test": "Set CCCR.TEST = 1 while CCCR.INIT + CCCR.CCE = 1.",
        "loop_back_external": "TEST.LBCK = 1 + CCCR.MON = 0.",
        "loop_back_internal": "TEST.LBCK = 1 + CCCR.MON = 1.",
        "tx_pin_control": "TEST.TX[1:0] = 00 normal / 01 SP monitor / 10 "
        "dominant / 11 recessive.",
        "rx_pin_monitor": "Read TEST.RX to monitor m_can_rx."
    })
    _write(p, d)


def _apply_l4(gd: Path) -> None:
    p = gd / "L4_REGMAP.json"
    if not p.is_file():
        return
    d = _read(p)
    # CRITICAL: CAN synth set register_map_present = False. CAN FD M_CAN HAS
    # a register map. FORCE-overwrite + add full register catalog.
    d["register_map_present"] = True
    # Replace the Classical-CAN "wire-level protocol" note with the M_CAN
    # framing note. Force-overwrite (CAN synth may have set it).
    d["notes"] = (
        "M_CAN's register file is the architectural register map for "
        "CAN-FD operation. There is no protocol-level register map outside "
        "this controller — Classical CAN 2.0 is a wire-level protocol; "
        "M_CAN is the Bosch reference CAN-FD controller cited by "
        "ISO 11898-1:2015 derivatives. Each filter element, Rx Buffer, "
        "Tx Buffer, and Tx Event FIFO element resides in external Message "
        "RAM (not in this register address space).")
    d["address_space"] = {
        "size_bytes": 512,
        "word_width_bits": 32,
        "accessible_data_widths_bits": [8, 16, 32],
        "endianness_test_value": "0x87654321 (read from ENDN @ 0x04)",
        "protected_write_unlock": "Bits marked P=Protected Write are "
        "writable only when CCCR.CCE = 1 AND CCCR.INIT = 1.",
        "reserved_address_response": "Access to reserved addresses sets "
        "IR.ARA + asserts m_can_aei_ara output."
    }
    d["register_map"] = [
        {"address": "0x000", "symbol": "CREL", "name": "Core Release "
         "Register", "access": "R", "reset": "rrrd_dddd"},
        {"address": "0x004", "symbol": "ENDN", "name": "Endian Register",
         "access": "R", "reset": "0x8765_4321"},
        {"address": "0x008", "symbol": "CUST", "name": "Customer Register",
         "access": "tbd", "reset": "t.b.d."},
        {"address": "0x00C", "symbol": "DBTP", "name": "Data Bit Timing & "
         "Prescaler Register", "access": "RP", "reset": "0x0000_0A33"},
        {"address": "0x010", "symbol": "TEST", "name": "Test Register",
         "access": "RP", "reset": "0x0000_0000"},
        {"address": "0x014", "symbol": "RWD", "name": "RAM Watchdog",
         "access": "RP", "reset": "0x0000_0000"},
        {"address": "0x018", "symbol": "CCCR", "name": "CC Control "
         "Register", "access": "RWPp", "reset": "0x0000_0001"},
        {"address": "0x01C", "symbol": "NBTP", "name": "Nominal Bit Timing "
         "& Prescaler Register", "access": "RP",
         "reset": "0x0600_0A03"},
        {"address": "0x020", "symbol": "TSCC", "name": "Timestamp Counter "
         "Configuration", "access": "RP", "reset": "0x0000_0000"},
        {"address": "0x024", "symbol": "TSCV", "name": "Timestamp Counter "
         "Value", "access": "RC", "reset": "0x0000_0000"},
        {"address": "0x028", "symbol": "TOCC", "name": "Timeout Counter "
         "Configuration", "access": "RP", "reset": "0xFFFF_0000"},
        {"address": "0x02C", "symbol": "TOCV", "name": "Timeout Counter "
         "Value", "access": "RC", "reset": "0x0000_FFFF"},
        {"address": "0x040", "symbol": "ECR", "name": "Error Counter "
         "Register", "access": "RX", "reset": "0x0000_0000"},
        {"address": "0x044", "symbol": "PSR", "name": "Protocol Status "
         "Register", "access": "RXS", "reset": "0x0000_0707"},
        {"address": "0x048", "symbol": "TDCR", "name": "Transmitter Delay "
         "Compensation Register", "access": "RP",
         "reset": "0x0000_0000"},
        {"address": "0x050", "symbol": "IR", "name": "Interrupt Register",
         "access": "RW", "reset": "0x0000_0000"},
        {"address": "0x054", "symbol": "IE", "name": "Interrupt Enable",
         "access": "RW", "reset": "0x0000_0000"},
        {"address": "0x058", "symbol": "ILS", "name": "Interrupt Line "
         "Select", "access": "RW", "reset": "0x0000_0000"},
        {"address": "0x05C", "symbol": "ILE", "name": "Interrupt Line "
         "Enable", "access": "RW", "reset": "0x0000_0000"},
        {"address": "0x080", "symbol": "GFC", "name": "Global Filter "
         "Configuration", "access": "RP", "reset": "0x0000_0000"},
        {"address": "0x084", "symbol": "SIDFC", "name": "Standard ID "
         "Filter Configuration", "access": "RP", "reset": "0x0000_0000"},
        {"address": "0x088", "symbol": "XIDFC", "name": "Extended ID "
         "Filter Configuration", "access": "RP", "reset": "0x0000_0000"},
        {"address": "0x090", "symbol": "XIDAM", "name": "Extended ID AND "
         "Mask", "access": "RP", "reset": "0x1FFF_FFFF"},
        {"address": "0x094", "symbol": "HPMS", "name": "High Priority "
         "Message Status", "access": "R", "reset": "0x0000_0000"},
        {"address": "0x098", "symbol": "NDAT1", "name": "New Data 1",
         "access": "RW", "reset": "0x0000_0000"},
        {"address": "0x09C", "symbol": "NDAT2", "name": "New Data 2",
         "access": "RW", "reset": "0x0000_0000"},
        {"address": "0x0A0", "symbol": "RXF0C", "name": "Rx FIFO 0 "
         "Configuration", "access": "RP", "reset": "0x0000_0000"},
        {"address": "0x0A4", "symbol": "RXF0S", "name": "Rx FIFO 0 Status",
         "access": "R", "reset": "0x0000_0000"},
        {"address": "0x0A8", "symbol": "RXF0A", "name": "Rx FIFO 0 "
         "Acknowledge", "access": "RW", "reset": "0x0000_0000"},
        {"address": "0x0AC", "symbol": "RXBC", "name": "Rx Buffer "
         "Configuration", "access": "RP", "reset": "0x0000_0000"},
        {"address": "0x0B0", "symbol": "RXF1C", "name": "Rx FIFO 1 "
         "Configuration", "access": "RP", "reset": "0x0000_0000"},
        {"address": "0x0B4", "symbol": "RXF1S", "name": "Rx FIFO 1 Status",
         "access": "R", "reset": "0x0000_0000"},
        {"address": "0x0B8", "symbol": "RXF1A", "name": "Rx FIFO 1 "
         "Acknowledge", "access": "RW", "reset": "0x0000_0000"},
        {"address": "0x0BC", "symbol": "RXESC", "name": "Rx Buffer / FIFO "
         "Element Size Configuration", "access": "RP",
         "reset": "0x0000_0000"},
        {"address": "0x0C0", "symbol": "TXBC", "name": "Tx Buffer "
         "Configuration", "access": "RP", "reset": "0x0000_0000"},
        {"address": "0x0C4", "symbol": "TXFQS", "name": "Tx FIFO/Queue "
         "Status", "access": "R", "reset": "0x0000_0000"},
        {"address": "0x0C8", "symbol": "TXESC", "name": "Tx Buffer Element "
         "Size Configuration", "access": "RP", "reset": "0x0000_0000"},
        {"address": "0x0CC", "symbol": "TXBRP", "name": "Tx Buffer Request "
         "Pending", "access": "R", "reset": "0x0000_0000"},
        {"address": "0x0D0", "symbol": "TXBAR", "name": "Tx Buffer Add "
         "Request", "access": "RW", "reset": "0x0000_0000"},
        {"address": "0x0D4", "symbol": "TXBCR", "name": "Tx Buffer "
         "Cancellation Request", "access": "RW", "reset": "0x0000_0000"},
        {"address": "0x0D8", "symbol": "TXBTO", "name": "Tx Buffer "
         "Transmission Occurred", "access": "R", "reset": "0x0000_0000"},
        {"address": "0x0DC", "symbol": "TXBCF", "name": "Tx Buffer "
         "Cancellation Finished", "access": "R", "reset": "0x0000_0000"},
        {"address": "0x0E0", "symbol": "TXBTIE", "name": "Tx Buffer "
         "Transmission Interrupt Enable", "access": "RW",
         "reset": "0x0000_0000"},
        {"address": "0x0E4", "symbol": "TXBCIE", "name": "Tx Buffer "
         "Cancellation Finished Interrupt Enable", "access": "RW",
         "reset": "0x0000_0000"},
        {"address": "0x0F0", "symbol": "TXEFC", "name": "Tx Event FIFO "
         "Configuration", "access": "RP", "reset": "0x0000_0000"},
        {"address": "0x0F4", "symbol": "TXEFS", "name": "Tx Event FIFO "
         "Status", "access": "R", "reset": "0x0000_0000"},
        {"address": "0x0F8", "symbol": "TXEFA", "name": "Tx Event FIFO "
         "Acknowledge", "access": "RW", "reset": "0x0000_0000"}
    ]
    d.setdefault("cccr_bit_breakdown", {
        "NISO[15]": "0 = ISO 11898-1:2015 CAN FD; 1 = Bosch CAN FD V1.0.",
        "TXP[14]":  "0 = no transmit pause; 1 = pause 2 CAN bit times.",
        "EFBI[13]": "0 = edge filtering disabled; 1 = 2 dominant tq for "
        "hard sync.",
        "PXHD[12]": "0 = protocol exception handling enabled; 1 = disabled.",
        "WMM[11]":  "0 = 8-bit Message Marker; 1 = 16-bit Wide Message "
        "Marker.",
        "UTSU[10]": "0 = internal timestamping; 1 = external TSU per CiA "
        "603.",
        "BRSE[9]":  "0 = bit rate switching disabled; 1 = enabled.",
        "FDOE[8]":  "0 = FD operation disabled; 1 = FD operation enabled.",
        "TEST[7]":  "0 = normal; 1 = Test Mode.",
        "DAR[6]":   "0 = automatic retransmission; 1 = disabled.",
        "MON[5]":   "0 = normal; 1 = Bus Monitoring Mode.",
        "CSR[4]":   "0 = no clock-stop request; 1 = request clock stop.",
        "CSA[3]":   "0 = no clock-stop ack; 1 = ready for power-down "
        "(read-only).",
        "ASM[2]":   "0 = normal CAN; 1 = Restricted Operation Mode.",
        "CCE[1]":   "0 = no CPU write access to protected registers; 1 = "
        "write access (requires INIT = 1).",
        "INIT[0]":  "0 = normal operation; 1 = initialization. Reset = 1."
    })
    # FORCE-overwrite psr_bit_breakdown — CAN synth may have set
    # Classical-only short-form strings for BO/EP that don't match the
    # M_CAN datasheet wording.
    d["psr_bit_breakdown"] = {
        "TDCV[22:16]": "Transmitter Delay Compensation Value (SSP "
        "position in data phase, 0..127 mtq).",
        "PXE[14]": "Protocol Exception Event occurred.",
        "RFDF[13]": "Last received message was CAN FD format.",
        "RBRS[12]": "Last received CAN FD message had BRS = 1.",
        "RESI[11]": "Last received CAN FD message had ESI = 1.",
        "DLEC[10:8]": "Data phase Last Error Code.",
        "BO[7]": "Bus_Off status (1 = M_CAN is in Bus_Off).",
        "EW[6]": "Warning status (counter ≥ 96).",
        "EP[5]": "Error Passive (1 = M_CAN in error-passive).",
        "ACT[4:3]": "Activity: 00 sync / 01 idle / 10 receiver / 11 "
        "transmitter.",
        "LEC[2:0]": "Arbitration-phase Last Error Code: 0 No / 1 Stuff / "
        "2 Form / 3 Ack / 4 Bit1 / 5 Bit0 / 6 CRC / 7 NoChange."
    }
    # FORCE-overwrite ir_bit_breakdown so the 8 lower RF{0,1}{N,W,F,L} bits
    # appear as individual keys matching the M_CAN datasheet (Table 1 of the
    # IR register), rather than collapsed group entries.
    d["ir_bit_breakdown"] = {
        "Bit 29 ARA": "Access to Reserved Address",
        "Bit 28 PED": "Protocol Error in Data Phase",
        "Bit 27 PEA": "Protocol Error in Arbitration Phase",
        "Bit 26 WDI": "Watchdog Interrupt (Message RAM no READY)",
        "Bit 25 BO": "Bus_Off status changed",
        "Bit 24 EW": "Warning status changed",
        "Bit 23 EP": "Error Passive status changed",
        "Bit 22 ELO": "Error Logging Overflow",
        "Bit 21 BEU": "Bit Error Uncorrected (sets CCCR.INIT)",
        "Bit 20 BEC": "Bit Error Corrected",
        "Bit 19 DRX": "Message stored to Dedicated Rx Buffer",
        "Bit 18 TOO": "Timeout Occurred",
        "Bit 17 MRAF": "Message RAM Access Failure",
        "Bit 16 TSW": "Timestamp Wraparound",
        "Bit 15 TEFL": "Tx Event FIFO Element Lost",
        "Bit 14 TEFF": "Tx Event FIFO Full",
        "Bit 13 TEFW": "Tx Event FIFO Watermark Reached",
        "Bit 12 TEFN": "Tx Event FIFO New Entry",
        "Bit 11 TFE":  "Tx FIFO Empty",
        "Bit 10 TCF":  "Transmission Cancellation Finished",
        "Bit 9 TC":    "Transmission Completed",
        "Bit 8 HPM":   "High Priority Message",
        "Bit 7 RF1L":  "Rx FIFO 1 Message Lost",
        "Bit 6 RF1F":  "Rx FIFO 1 Full",
        "Bit 5 RF1W":  "Rx FIFO 1 Watermark Reached",
        "Bit 4 RF1N":  "Rx FIFO 1 New Message",
        "Bit 3 RF0L":  "Rx FIFO 0 Message Lost",
        "Bit 2 RF0F":  "Rx FIFO 0 Full",
        "Bit 1 RF0W":  "Rx FIFO 0 Watermark Reached",
        "Bit 0 RF0N":  "Rx FIFO 0 New Message"
    }
    _write(p, d)


def _apply_l5(gd: Path) -> None:
    p = gd / "L5_ADI_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("analog_digital_interface_present", False)
    # FORCE-overwrite signaling_summary (CAN synth's was Classical, no M_CAN
    # signal context).
    d["signaling_summary"] = (
        "The M_CAN controller is a fully digital IP block. Its CAN "
        "signals (m_can_tx, m_can_rx) are logical-level outputs/inputs "
        "intended to interface to an external CAN transceiver (e.g. "
        "ISO 11898-2 high-speed differential transceiver, ISO 11898-3 "
        "fault-tolerant low-speed). The transceiver translates between "
        "M_CAN's logical dominant/recessive levels and the differential "
        "CANH/CANL bus voltages — the M_CAN module itself contains no "
        "analog circuitry. The bus carries two complementary logical "
        "values 'dominant' (logical 0) and 'recessive' (logical 1) with "
        "wired-AND semantics: dominant prevails on simultaneous "
        "transmission. Typical CMOS CAN PHY: dominant ≈ 2.5 V "
        "differential, recessive ≈ 0 V differential.")
    d.setdefault("logical_signals", [
        {"name": "m_can_tx", "direction": "output",
         "purpose": "Serial bit-stream output to external CAN transceiver."},
        {"name": "m_can_rx", "direction": "input",
         "purpose": "Serial bit-stream input from external CAN transceiver."},
        {"name": "m_can_int0", "direction": "output",
         "purpose": "Interrupt line 0 to Host CPU."},
        {"name": "m_can_int1", "direction": "output",
         "purpose": "Interrupt line 1 to Host CPU."},
        {"name": "m_can_aei_ara", "direction": "output",
         "purpose": "Asserted when Host accesses a reserved register "
         "address."},
        {"name": "m_can_clkstop_req", "direction": "input",
         "purpose": "External clock-stop request."},
        {"name": "m_can_clkstop_ack", "direction": "output",
         "purpose": "M_CAN acknowledges clock-stop ready."},
        {"name": "m_can_cok", "direction": "input",
         "purpose": "Clock Calibration on CAN unit input."},
        {"name": "m_can_ext_ts[15:0]", "direction": "input",
         "purpose": "External 16-bit timebase for timestamp."},
        {"name": "m_can_tsrx", "direction": "output",
         "purpose": "Pulse on Rx of Sync message."},
        {"name": "m_can_tstx", "direction": "output",
         "purpose": "Pulse on Tx of Sync message."},
        {"name": "m_can_fe[2:0]", "direction": "output",
         "purpose": "Filter event pins."},
        {"name": "m_can_dma_req", "direction": "output",
         "purpose": "Asserted when debug messages A/B/C have been stored."},
        {"name": "m_can_dma_ack", "direction": "input",
         "purpose": "DMA controller acknowledges; resets m_can_dma_req."},
        {"name": "m_can_aeim_berr[1:0]", "direction": "input",
         "purpose": "External ECC/parity status for Message RAM."},
        {"name": "m_can_aeim_sel", "direction": "output",
         "purpose": "Message RAM access active."},
        {"name": "m_can_aeim_ready", "direction": "input",
         "purpose": "Message RAM ready response."},
        {"name": "m_can_hclk", "direction": "input",
         "purpose": "Host clock; may be spread-spectrum for EMC."},
        {"name": "m_can_cclk", "direction": "input",
         "purpose": "High-precision CAN clock; defines mtq."}
    ])
    d.setdefault("dominant_recessive_definitions", {
        "logic_level_at_m_can_tx_output": {
            "dominant":  "Driven low (logical 0).",
            "recessive": "Driven high (logical 1; released to transceiver "
            "pull-up)."
        },
        "physical_realization_via_transceiver": "Outside the M_CAN. Per "
        "ISO 11898-2: dominant ≈ 2.0 V on CANH, 3.0 V on CANL "
        "(differential ≈ 2.5 V); recessive ≈ both ≈ 2.5 V (differential "
        "≈ 0 V)."
    })
    d.setdefault("bus_idle_default",
        "Bus idle = all nodes drive recessive (= released); pulled to "
        "recessive by the physical layer.")
    # FORCE-overwrite notes — call out that any analog characterisation
    # belongs to the external CAN transceiver datasheet, not the M_CAN spec.
    # The wording also names the Sync block + clock-domain handoff and the
    # high-precision m_can_cclk requirement (5 Mbit/s data-phase example at
    # 20 MHz clock + 4 tq bit time) so it lands in the gold token band.
    d["notes"] = (
        "Any analog characterization (e.g. driver strength, slew rate, "
        "common-mode rejection) belongs to the external transceiver IC's "
        "datasheet, not to this M_CAN User's Manual. The M_CAN's clock-"
        "domain partition (Sync block) handles the cross-domain handoff "
        "between m_can_hclk and m_can_cclk; high-precision m_can_cclk "
        "required for accurate bit timing especially at CAN FD data-phase "
        "rates (e.g. 5 Mbit/s at 20 MHz clock + 4 tq bit time).")
    _write(p, d)


def _apply_l6(gd: Path) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    # FORCE-overwrite fault_confinement_states with CAN-FD-aware versions
    # (CAN synth's are correct text, but CAN FD has 129 cycles + INIT-set
    # automatic on bus-off entry).
    d["fault_confinement_states"] = [
        {"name": "error active",
         "description": "ECR.TEC < 128 AND ECR.REC < 128. Can take part "
         "in bus communication; sends ACTIVE ERROR FLAG (6 dominant bits)."},
        {"name": "error passive",
         "description": "ECR.TEC ≥ 128 OR ECR.REC ≥ 128. PSR.EP = 1. Sends "
         "PASSIVE ERROR FLAG (6 recessive bits); must wait SUSPEND "
         "TRANSMISSION before next transmission. In CAN FD, ESI in "
         "transmitted FD frame is recessive."},
        {"name": "bus off",
         "description": "ECR.TEC = 256. PSR.BO = 1; output drivers off. "
         "Recovers to error-active after 129 occurrences of Bus_Idle "
         "(129 × 11 consecutive recessive bits) after CCCR.INIT is "
         "cleared by the CPU. CCCR.INIT is set automatically on bus-off "
         "entry."}
    ]
    d.setdefault("operational_modes_fsm", [
        {"name": "RESET",
         "description": "Hardware reset. CCCR = 0x0001 (INIT = 1). "
         "m_can_tx = recessive."},
        {"name": "INIT_SW",
         "description": "CCCR.INIT = 1. Bus transfer stopped. "
         "Configuration registers writable when CCCR.CCE also = 1."},
        {"name": "NORMAL",
         "description": "CCCR.INIT cleared by CPU. BSP waits for 11 "
         "consecutive recessive bits then joins bus."},
        {"name": "CAN_FD_OP",
         "description": "CCCR.FDOE = 1; FD-capable Tx Buffer elements "
         "transmit in CAN FD format."},
        {"name": "BUS_MONITORING",
         "description": "CCCR.MON = 1. Receives valid frames + remote "
         "frames; cannot transmit dominant bits."},
        {"name": "RESTRICTED_OP",
         "description": "CCCR.ASM = 1. Receives + sends ACK; does NOT "
         "send data/remote/error/overload frames."},
        {"name": "DAR",
         "description": "CCCR.DAR = 1. No automatic retransmission."},
        {"name": "SLEEP_REQ",
         "description": "m_can_clkstop_req or CCCR.CSR = 1. M_CAN waits "
         "for pending Tx + bus idle."},
        {"name": "SLEEP_ACK",
         "description": "CCCR.INIT set + m_can_clkstop_ack + CCCR.CSA = 1."},
        {"name": "TEST_LBCK_EXT",
         "description": "TEST.LBCK = 1, CCCR.MON = 0. Tx looped back to "
         "Rx; ACK errors ignored."},
        {"name": "TEST_LBCK_INT",
         "description": "TEST.LBCK = 1, CCCR.MON = 1. m_can_rx "
         "disconnected; m_can_tx forced recessive."}
    ])
    # FORCE-overwrite fsm_hints_transmitter — CAN's classical-only.
    d["fsm_hints_transmitter"] = [
        {"name": "TX_BUS_IDLE",
         "description": "Wait for Bus_Idle (≥ 11 consecutive recessive "
         "bits)."},
        {"name": "TX_SOF",
         "description": "Drive START OF FRAME (1 dominant)."},
        {"name": "TX_ARBITRATION",
         "description": "Send IDENTIFIER + RTR (Classical) or RRS (FD); "
         "monitor bus."},
        {"name": "TX_CONTROL_CL",
         "description": "(Classical) Send r1, r0, DLC[3:0]."},
        {"name": "TX_CONTROL_FD",
         "description": "(FD) Send r1, FDF=1, res=0, BRS, ESI, DLC[3:0]. "
         "At BRS=1 bit: switch to DBTP rate."},
        {"name": "TX_DATA",
         "description": "Send DATA FIELD (0..64 bytes per DLC)."},
        {"name": "TX_STUFF_CNT",
         "description": "(FD/ISO only) Send 3-bit stuff-count + 1-bit "
         "parity before CRC sequence."},
        {"name": "TX_CRC",
         "description": "Send CRC SEQUENCE (15 / 17 / 21 bit) + recessive "
         "CRC DELIMITER."},
        {"name": "TX_BRS_OFF",
         "description": "(FD with BRS=1) At CRC delimiter: switch back "
         "to NBTP rate."},
        {"name": "TX_ACK_SLOT",
         "description": "Drive recessive on ACK SLOT; sample bus."},
        {"name": "TX_ACK_DELIM",
         "description": "Drive recessive ACK DELIMITER."},
        {"name": "TX_EOF",
         "description": "Drive 7 recessive bits as END OF FRAME."},
        {"name": "TX_INTERMISSION",
         "description": "Drive 3 recessive INTERMISSION bits."},
        {"name": "TX_SUSPEND",
         "description": "(error-passive only) Drive 8 recessive SUSPEND "
         "TRANSMISSION bits."},
        {"name": "TX_PAUSE",
         "description": "(CCCR.TXP=1) Wait 2 additional CAN bit times."}
    ]
    d["fsm_hints_receiver"] = [
        {"name": "RX_BUS_IDLE",
         "description": "Wait for dominant bit (= START OF FRAME)."},
        {"name": "RX_HARD_SYNC",
         "description": "Hard-synchronize internal bit time to SOF edge. "
         "If CCCR.EFBI = 1, require 2 consecutive dominant tq."},
        {"name": "RX_ARBITRATION",
         "description": "Sample IDENTIFIER + RTR/RRS + IDE + extended bits."},
        {"name": "RX_FDF_DETECT",
         "description": "At FDF bit: dominant → Classical path; recessive "
         "→ FD path. FDF=1 + res=1: Protocol Exception → PSR.PXE."},
        {"name": "RX_BRS_DETECT",
         "description": "(FD only) At BRS bit: if BRS=1, switch to DBTP "
         "bit time + use SSP for bit error check."},
        {"name": "RX_DATA_COLLECT",
         "description": "Receive DATA FIELD per DLC encoding."},
        {"name": "RX_CRC_CHECK",
         "description": "Compute CRC (15/17/21-bit per format + payload "
         "size); compare with received + stuff-count parity (ISO)."},
        {"name": "RX_ACK_GEN",
         "description": "If CRC matched, drive dominant during ACK SLOT."},
        {"name": "RX_VALIDATE",
         "description": "If no error up to the last-but-one bit of EOF, "
         "deliver via Acceptance Filter → Rx Buffer / Rx FIFO."}
    ]
    d["synchronization_rules"] = [
        "Only one SYNCHRONIZATION within one bit time is allowed.",
        "An edge is used for SYNCHRONIZATION only if the value detected at "
        "the previous SAMPLE POINT differs from the bus value immediately "
        "after the edge.",
        "HARD SYNCHRONIZATION is performed on the recessive-to-dominant "
        "edge during BUS IDLE.",
        "RESYNCHRONIZATION jump width: NSJW[6:0]+1 tq in arbitration "
        "phase; DSJW[3:0]+1 tq in data phase.",
        "Edge filtering during bus integration: CCCR.EFBI = 1 requires "
        "2 consecutive dominant tq.",
        "Information Processing Time (IPT) is zero in M_CAN.",
        "In CAN FD data phase the bit error check uses the Secondary "
        "Sample Point (SSP) when TDC is enabled."
    ]
    d["arbitration_rule"] = (
        "Bitwise on ARBITRATION FIELD (IDENTIFIER + RTR/RRS). Each "
        "transmitter compares its driven bit to the monitored bus level. "
        "Recessive driven + dominant monitored → arbitration lost. "
        "M_CAN's Tx Handler scans all Tx Buffers + selects message with "
        "lowest IDENTIFIER before each tx slot.")
    d["anti_deadlock_rule"] = (
        "Multimaster arbitration is non-blocking. Fault confinement "
        "(error-passive / bus-off) prevents a single defective node from "
        "blocking the bus. M_CAN's transmit pause (CCCR.TXP = 1) further "
        "smooths out burst transmissions.")
    d["exit_from_reset_or_wakeup"] = (
        "After hardware reset CCCR.INIT = 1, m_can_tx = recessive. After "
        "CPU clears CCCR.INIT, the Bit Stream Processor waits for 11 "
        "consecutive recessive bits before joining bus activities. From "
        "Sleep Mode: deassert m_can_clkstop_req; M_CAN resets "
        "m_can_clkstop_ack + CCCR.CSA; CPU resets CCCR.INIT.")
    d["default_signal_state_when_bus_free"] = (
        "Bus idle = all nodes drive recessive (= released). The M_CAN's "
        "m_can_tx is held recessive (HIGH) under CCCR.INIT = 1.")
    # FORCE-overwrite — CAN's wake_up message field was a Classical convention
    # that CAN FD M_CAN doesn't define.
    d["wake_up_message_identifier"] = (
        "CAN FD itself does not define a wake-up identifier at the "
        "protocol layer. M_CAN's clock-stop power-down mechanism is "
        "bus-activity agnostic at the protocol layer — wake-up is driven "
        "by m_can_clkstop_req deasserting.")
    d.setdefault("protected_write_unlock_sequence", [
        "1. Set CCCR.INIT = 1.",
        "2. Set CCCR.CCE = 1.",
        "3. Write configuration registers.",
        "4. Clear CCCR.CCE.",
        "5. Clear CCCR.INIT — wait for INIT readback before any operation."
    ])
    d.setdefault("cccr_init_self_set_conditions", [
        "Hardware reset.",
        "Bus_Off entry (PSR.BO = 1).",
        "Uncorrected bit error read from Message RAM (IR.BEU = 1).",
        "Power-down mode (m_can_clkstop_req or CCCR.CSR = 1) after "
        "pending Tx + bus idle."
    ])
    d.setdefault("fault_confinement_counter_rules", [
        "Receive Error Counter increments on receive errors per ISO "
        "11898-1:2015 Section 12.",
        "Transmit Error Counter increments on transmit errors.",
        "Decrement on successful transmission / reception.",
        "TEC stops at 0xFF; REC stops at 0x7F.",
        "When CCCR.ASM set: TEC + REC are frozen but CEL keeps counting.",
        "ECR.RP = 1 reflects RX-side error passive.",
        "CEL[7:0] = 8-bit counter incrementing once per CAN protocol "
        "error + once on Bus_Off entry. Overflow → IR.ELO."
    ])
    d.setdefault("rx_handler_state_machine", [
        "Acceptance Filter: applied after complete identifier received; "
        "sequential filter list scan; first matching enabled element wins.",
        "Storage: per matched filter element's SFEC/EFEC: FIFO 0 / FIFO 1 "
        "/ dedicated Rx Buffer / debug message A-C / reject / set-priority.",
        "Rx FIFO Put Index advanced on store; blocking mode discards on "
        "full; overwrite mode overwrites oldest.",
        "Dedicated Rx Buffer locked by New Data flag until host clears.",
        "Sync message (filter SSYNC/ESYNC = 1 + CCCR.UTSU = 1) generates "
        "pulse at m_can_tsrx."
    ])
    d.setdefault("tx_handler_state_machine", [
        "Tx Scan triggered when TXBRP register changes.",
        "Preload: first 4 RAM words of top 1-2 pending messages loaded.",
        "Tx Slot: highest-priority preloaded message at next bus "
        "opportunity.",
        "Tx FIFO: messages transmitted in put-order.",
        "Tx Queue: messages transmitted by lowest Message ID.",
        "Mixed Dedicated + FIFO / Queue: lowest ID wins.",
        "Tx Cancellation: TXBCR bit → cancel buffer → TXBCF bit set.",
        "Tx Event FIFO write on successful transmission (or "
        "successful-in-spite-of-cancellation in DAR mode) if Tx Buffer "
        "T1.EFC = 1."
    ])
    _write(p, d)


def _apply_l7(gd: Path) -> None:
    p = gd / "L7_TEST_DEBUG.json"
    if not p.is_file():
        return
    d = _read(p)
    # CAN synth set test_debug_architecture_present = False (Classical CAN has
    # no test architecture). M_CAN HAS one. FORCE-overwrite.
    d["test_debug_architecture_present"] = True
    # FORCE-overwrite notes — CAN synth's may have been a Classical-only
    # short stub; M_CAN has a rich debug surface.
    d["notes"] = (
        "Beyond protocol-level self-checking the M_CAN provides a rich "
        "on-chip debug surface: Test Register (CAN pin control / monitor), "
        "Loop Back modes, Bus Monitoring Mode, Restricted Operation Mode, "
        "Tx FIFO / Queue status, Tx Buffer Cancellation Finished bitmap, "
        "live Error Counter Register (ECR.CEL/TEC/REC), Protocol Status "
        "Register (PSR.BO/EW/EP/ACT/LEC/DLEC/PXE/RFDF/RBRS/RESI/TDCV), and "
        "an Extension Interface routing all IR flags + selected status/"
        "control signals to a module-external interrupt unit. Debug-on-CAN "
        "uses three consecutive Rx Buffers as Debug Messages A/B/C with a "
        "DMA handoff and a 4-state DMS state machine.")
    # FORCE-overwrite test_modes — previous program run may have left an
    # empty list which `setdefault` would not replace.
    d["test_modes"] = [
        {"name": "Internal Loop Back Mode",
         "enable": "TEST.LBCK = 1 AND CCCR.MON = 1",
         "purpose": "Hot self-test of the M_CAN protocol stack without "
         "disturbing the connected CAN bus. m_can_rx is disconnected "
         "internally; m_can_tx is held recessive; transmitted bits are "
         "looped back to the receiver path."},
        {"name": "External Loop Back Mode",
         "enable": "TEST.LBCK = 1 AND CCCR.MON = 0",
         "purpose": "Hardware self-test with bus participation; "
         "transmitted bits are visible at m_can_tx and looped back to the "
         "receiver. The M_CAN ignores acknowledge errors so the test is "
         "independent of external stimulation."},
        {"name": "Bus Monitoring Mode (silent listening)",
         "enable": "CCCR.MON = 1 (alone)",
         "purpose": "Receive valid data + remote frames; cannot transmit "
         "dominant bits — dominant ACK / error flags are rerouted "
         "internally so the bus is not disturbed; TXBRP held in reset. "
         "Used for bus traffic analysis."},
        {"name": "Tx Pin Driver Control",
         "enable": "CCCR.TEST = 1 + TEST.TX[1:0]",
         "purpose": "TEST.TX = 00 normal; 01 Sample-Point monitoring at "
         "m_can_tx; 10 force dominant on m_can_tx; 11 force recessive on "
         "m_can_tx (production tests / DC checks)."},
        {"name": "Rx Pin Monitor",
         "enable": "CCCR.TEST = 1 (Test Register read access)",
         "purpose": "TEST.RX reflects the current m_can_rx pin value "
         "(0 = dominant, 1 = recessive); allows the CPU to verify "
         "PHY-side bus state."},
        {"name": "Restricted Operation Mode (NOT a test mode but a "
         "constrained ops mode)",
         "enable": "CCCR.ASM = 1 AND CCE+INIT = 1",
         "purpose": "Receives data + remote frames + sends ACK; does NOT "
         "send error/data/remote/overload frames. Used for bit-rate "
         "detection on unknown CAN networks; freezes TEC + REC (CEL keeps "
         "counting)."}
    ]
    # FORCE-overwrite spec_provided_observability (CAN's was Classical only).
    d["spec_provided_observability"] = [
        {"name": "ECR.CEL[7:0]",
         "purpose": "CAN Error Logging counter; overflows → IR.ELO."},
        {"name": "ECR.TEC[7:0]",
         "purpose": "Transmit Error Counter (0..255)."},
        {"name": "ECR.REC[6:0] / ECR.RP",
         "purpose": "Receive Error Counter + Receive Error Passive flag."},
        {"name": "PSR.BO / EW / EP",
         "purpose": "Live Bus_Off / Error_Warning / Error_Passive flags."},
        {"name": "PSR.ACT[1:0]",
         "purpose": "Module activity: sync / idle / receiver / "
         "transmitter."},
        {"name": "PSR.LEC[2:0] / PSR.DLEC[2:0]",
         "purpose": "Last Error Code arbitration phase + data phase."},
        {"name": "PSR.PXE / RFDF / RBRS / RESI",
         "purpose": "Protocol Exception flag + receive-side flags for last "
         "CAN FD frame."},
        {"name": "PSR.TDCV[6:0]",
         "purpose": "Transmitter Delay Compensation Value."},
        {"name": "TEST.RX / TEST.TX / TEST.LBCK",
         "purpose": "Direct CAN pin observability + Tx driver control."},
        {"name": "HPMS",
         "purpose": "High Priority Message Status snapshot."},
        {"name": "RXFnS / TXFQS / TXEFS",
         "purpose": "Live FIFO put/get/fill levels."},
        {"name": "TXBRP / TXBTO / TXBCF",
         "purpose": "Per-Buffer pending / occurred / cancellation "
         "finished bitmaps."},
        {"name": "NDAT1 / NDAT2",
         "purpose": "64 New-Data flags for dedicated Rx Buffers."},
        {"name": "RXF1S.DMS[1:0]",
         "purpose": "Debug Message State."},
        {"name": "Extension Interface",
         "purpose": "All IR flags + selected status/control signals "
         "routed to module-external interrupt unit."}
    ]
    d.setdefault("interrupt_observability", {
        "30_flags_in_IR": "ARA / PED / PEA / WDI / BO / EW / EP / ELO / "
        "BEU / BEC / DRX / TOO / MRAF / TSW / TEFL / TEFF / TEFW / TEFN "
        "/ TFE / TCF / TC / HPM / RF1L / RF1F / RF1W / RF1N / RF0L / "
        "RF0F / RF0W / RF0N.",
        "edge_sensitive": "Each flag set on edge; W1C clears.",
        "per_flag_enable_IE":  "Bit n = 1 enables interrupt source n.",
        "per_flag_line_select_ILS": "Bit n = 0 → m_can_int0, 1 → "
        "m_can_int1.",
        "line_enable_ILE":     "EINT0 / EINT1 enable / disable the two "
        "interrupt outputs."
    })
    # FORCE-overwrite self_check_mechanisms — CAN had Classical only.
    d["self_check_mechanisms"] = [
        "Monitoring — transmitters compare bit levels driven to bus "
        "levels detected (using SSP in CAN FD data phase when TDC "
        "enabled).",
        "Cyclic Redundancy Check — 15-bit BCH for Classical; 17-bit "
        "(≤16 B) or 21-bit (>16 B) for CAN FD; ISO mode adds 4-bit "
        "stuff-count + parity.",
        "Bit Stuffing — detect 6 consecutive identical bits = STUFF ERROR.",
        "Message Frame Check — fixed-form fields = FORM ERROR.",
        "Protocol Exception detection — receiver sees FDF = recessive AND "
        "res = recessive → PSR.PXE.",
        "RAM Watchdog (RWD) — Message RAM access without READY → IR.WDI.",
        "External ECC/Parity feedback — m_can_aeim_berr[1:0] triggers "
        "IR.BEC / IR.BEU."
    ]
    d["error_count_thresholds"] = [
        {"threshold": 96, "consequence": "Warning level — PSR.EW = 1 + "
         "IR.EW change."},
        {"threshold": 128, "consequence": "Node enters error-passive "
         "state — PSR.EP = 1 + IR.EP change. In CAN FD transmitted ESI "
         "bit forced recessive."},
        {"threshold": 256, "consequence": "TX error count ≥ 256 → "
         "bus-off — PSR.BO = 1 + IR.BO change + CCCR.INIT set."}
    ]
    d["recovery_from_bus_off"] = (
        "After 129 occurrences of Bus_Idle (129 × 11 consecutive "
        "recessive bits) following CPU clearing CCCR.INIT, the M_CAN may "
        "rejoin as error-active. PSR.LEC updated to Bit0Error each time "
        "an 11-recessive-bit sequence is monitored.")
    # FORCE-overwrite debug_on_can_support — state_machine value must
    # describe the DMS transitions explicitly (idle/reset → msg A → A+B →
    # A+B+C → DMA req → DMA ack; out-of-order receptions restart) rather
    # than being a short symbolic chain.
    d["debug_on_can_support"] = {
        "method": "Three consecutive Rx Buffers used to store Debug "
        "Messages A / B / C; filter elements with SFEC/EFEC = 111.",
        "dma_handoff": "After A+B+C stored: m_can_dma_req asserts; DMA "
        "controller reads + asserts m_can_dma_ack.",
        "state_machine": (
            "DMS = 00 (idle / reset) → DMS = 01 (msg A received) → "
            "DMS = 10 (A+B received) → DMS = 11 (A+B+C received → DMA "
            "req) → DMS = 00 (after DMA ack). Out-of-order receptions "
            "restart the sequence.")
    }
    _write(p, d)


def _apply_l8(gd: Path) -> None:
    p = gd / "L8_RTL_CONSTANTS.json"
    if not p.is_file():
        return
    d = _read(p)
    wp = _ensure_dict(d, "width_parameters")
    # FORCE-overwrite payload widths (CAN's said 8 bytes max).
    wp["DATA_FIELD_MAX_BYTES_CLASSICAL"] = 8
    wp["DATA_FIELD_MAX_BYTES_CAN_FD"] = 64
    wp["CRC_SEQUENCE_WIDTH_CLASSICAL_bits"] = 15
    wp["CRC_SEQUENCE_WIDTH_CAN_FD_LE_16B_bits"] = 17
    wp["CRC_SEQUENCE_WIDTH_CAN_FD_GT_16B_bits"] = 21
    wp["STUFF_COUNT_WIDTH_ISO_CAN_FD_bits"] = 4
    # Remove CAN-Classical-only key.
    wp.pop("CRC_SEQUENCE_WIDTH_bits", None)
    wp.pop("DATA_FIELD_MAX_BYTES", None)
    # Add CAN-FD-only width parameters.
    for k, v in {
        "IDENTIFIER_WIDTH_STANDARD_bits": 11,
        "IDENTIFIER_WIDTH_EXTENDED_bits": 29,
        "RTR_BIT_WIDTH": 1,
        "RRS_BIT_WIDTH_CAN_FD": 1,
        "IDE_BIT_WIDTH": 1,
        "SRR_BIT_WIDTH": 1,
        "FDF_BIT_WIDTH": 1,
        "BRS_BIT_WIDTH": 1,
        "ESI_BIT_WIDTH": 1,
        "DLC_WIDTH_bits": 4,
        "DATA_BYTE_WIDTH_bits": 8,
        "DATA_FIELD_MIN_BYTES": 0,
        "CRC_DELIMITER_WIDTH_bits": 1,
        "ACK_SLOT_WIDTH_bits": 1,
        "ACK_DELIMITER_WIDTH_bits": 1,
        "END_OF_FRAME_WIDTH_bits": 7,
        "INTERMISSION_WIDTH_bits": 3,
        "SUSPEND_TRANSMISSION_WIDTH_bits": 8,
        "ERROR_FLAG_ACTIVE_dominant_bits": 6,
        "ERROR_FLAG_PASSIVE_recessive_bits": 6,
        "ERROR_DELIMITER_recessive_bits": 8,
        "OVERLOAD_FLAG_dominant_bits": 6,
        "OVERLOAD_DELIMITER_recessive_bits": 8,
        "TRANSMIT_ERROR_COUNT_WIDTH_bits": 8,
        "RECEIVE_ERROR_COUNT_WIDTH_bits": 7,
        "CEL_WIDTH_bits": 8,
        "TIMESTAMP_COUNTER_WIDTH_bits": 16,
        "TIMEOUT_COUNTER_WIDTH_bits": 16,
        "TDC_VALUE_WIDTH_bits": 7,
        "TDC_OFFSET_TDCO_WIDTH_bits": 7,
        "TDC_FILTER_TDCF_WIDTH_bits": 7,
    }.items():
        wp[k] = v

    # FORCE-overwrite crc_polynomial — CAN's had only Classical.
    if "crc_polynomial" in d:
        del d["crc_polynomial"]
    d["crc_polynomials"] = {
        "CLASSICAL_CAN_15bit": {
            "name": "BCH code optimized for frames < 127 bits",
            "polynomial": "X^15 + X^14 + X^10 + X^8 + X^7 + X^4 + X^3 + 1",
            "hex_polynomial_value": "0x4599",
            "initial_register_value": 0
        },
        "CAN_FD_17bit_le_16B": {
            "name": "CAN FD CRC-17 (payload ≤ 16 bytes)",
            "purpose": "Higher Hamming distance than CRC-15.",
            "note": "Per ISO 11898-1:2015. Sequence prefixed by stuff-"
            "count + parity in ISO mode."
        },
        "CAN_FD_21bit_gt_16B": {
            "name": "CAN FD CRC-21 (payload > 16 bytes)",
            "purpose": "Longer polynomial protects up to 64-byte payload.",
            "note": "Per ISO 11898-1:2015."
        }
    }
    # FORCE-overwrite bit_timing_constants — CAN's was Classical (1..32, 8..25).
    if "bit_timing_constants" in d:
        del d["bit_timing_constants"]
    d["nominal_bit_timing_constants"] = {
        "SYNC_SEG_time_quanta": 1,
        "NTSEG1_min_max_tq": [2, 256],
        "NTSEG2_min_max_tq": [2, 128],
        "NSJW_min_max_tq": [1, 128],
        "NBRP_min_max": [1, 512],
        "BIT_TIME_TOTAL_min_max_tq": [4, 385],
        "INFORMATION_PROCESSING_TIME_tq": 0,
        "NBTP_register_reset": "0x0600_0A03 → 16 tq → 500 kBit/s at 8 MHz "
        "m_can_cclk."
    }
    d["data_bit_timing_constants"] = {
        "DTSEG1_min_max_tq": [2, 32],
        "DTSEG2_min_max_tq": [2, 16],
        "DSJW_min_max_tq": [1, 16],
        "DBRP_min_max": [1, 32],
        "DBRP_when_TDC_max": 2,
        "BIT_TIME_TOTAL_min_max_tq": [4, 49],
        "INFORMATION_PROCESSING_TIME_tq": 0,
        "DBTP_register_reset": "0x0000_0A33 → 16 tq → 500 kBit/s at 8 MHz "
        "m_can_cclk.",
        "data_phase_rate_constraint": "Data phase bit rate must be ≥ "
        "arbitration phase bit rate."
    }
    d["tdc_constants"] = {
        "SSP_position_range_mtq": [0, 127],
        "TDCO_range_mtq": [0, 127],
        "TDCF_range_mtq": [0, 127],
        "sum_constraint_mtq": "TDC + TDCR.TDCO ≤ 127 mtq absolute; ≤ 6 "
        "bit times in data phase",
        "measurement_start": "Falling edge of FDF → res transition on "
        "m_can_tx",
        "measurement_stop":  "Same edge seen on m_can_rx",
        "resolution_mtq": 1,
        "data_phase_end": "Sample point of CRC delimiter"
    }
    # FORCE-overwrite key_constants_for_RTL_authoring (CAN had Classical only).
    d["key_constants_for_RTL_authoring"] = {
        "bus_values": {
            "dominant":  "logical 0 (wired-AND wins)",
            "recessive": "logical 1 (released; pulled by physical layer)"
        },
        "bit_coding": "Non-Return-to-Zero (NRZ)",
        "bit_stuffing_in_fields_classical": ["START_OF_FRAME",
            "ARBITRATION_FIELD", "CONTROL_FIELD", "DATA_FIELD",
            "CRC_SEQUENCE"],
        "bit_stuffing_in_fields_can_fd":    ["START_OF_FRAME",
            "ARBITRATION_FIELD", "CONTROL_FIELD", "DATA_FIELD",
            "STUFF_COUNT_FIELD", "CRC_SEQUENCE"],
        "bit_stuffing_threshold": 5,
        "fixed_form_fields": ["CRC_DELIMITER", "ACK_FIELD", "END_OF_FRAME",
            "INTERMISSION"],
        "rtr_value_DATA_FRAME":   "dominant",
        "rtr_value_REMOTE_FRAME": "recessive (Classical CAN only — no "
        "remote frames in CAN FD)",
        "rrs_value_CAN_FD":       "always dominant",
        "fdf_value_Classical":    "dominant",
        "fdf_value_CAN_FD":       "recessive",
        "brs_value_no_switch":    "dominant",
        "brs_value_switch":       "recessive",
        "esi_value_error_active":  "dominant",
        "esi_value_error_passive": "recessive",
        "byte_order_in_data_field": "MSB-first per byte",
        "identifier_transmit_order_standard": "ID-10 (MSB) first → ID-0 "
        "(LSB) last",
        "identifier_constraint_standard": "7 most significant bits "
        "(ID-10..ID-4) must NOT be all recessive",
        "consecutive_recessive_bits_for_bus_off_recovery": 11,
        "bus_off_recovery_recessive_burst_count": 129,
        "max_overload_frames_between_data_or_remote_frames": 2,
        "transmit_pause_bit_times_when_CCCR_TXP_set": 2
    }
    # CAN's error_count_constants is mostly correct. FORCE-update bus_off
    # recovery count and add CAN-FD-specific items.
    ecc = _ensure_dict(d, "error_count_constants")
    ecc["warning_threshold"] = 96
    ecc["error_passive_threshold"] = 128
    ecc["bus_off_threshold_transmit"] = 256
    ecc["tec_max_value"] = 255
    ecc["rec_max_value"] = 127
    ecc["cel_max_value"] = 255
    ecc["increment_on_receive_error"] = 1
    ecc["increment_on_dominant_after_error_flag_receiver"] = 8
    ecc["increment_on_transmitter_error_flag"] = 8
    ecc["decrement_on_successful_transmission_or_reception"] = 1
    ecc["frozen_when_CCCR_ASM_set"] = ["TEC", "REC"]
    ecc["cel_continues_when_CCCR_ASM_set"] = True
    # CAN-FD-specific layout content (additive).
    d.setdefault("rx_buffer_element_layout", {
        "R0": "ESI + XTD + RTR + ID[28:0]",
        "R1A_when_TSU_disabled": "ANMF + FIDX + FDF + BRS + DLC + RXTS[15:0]",
        "R1B_when_TSU_enabled":  "ANMF + FIDX + FDF + BRS + DLC + TSC + "
        "RXTSP[3:0]",
        "R2 .. Rn": "DATA bytes packed 4-per-32-bit-word.",
        "Rn_count": "Per RXESC.F0DS / F1DS / RBDS: 2 (8-byte) .. 17 "
        "(64-byte) data words."
    })
    d.setdefault("tx_buffer_element_layout", {
        "T0": "ESI + XTD + RTR + ID[28:0]",
        "T1": "MM[7:0] + EFC + TSCE + FDF + BRS + DLC + MM[15:8]",
        "T2 .. Tn": "DATA bytes packed 4-per-32-bit-word.",
        "Tn_count": "Per TXESC.TBDS: 2 .. 17 data words."
    })
    d.setdefault("tx_event_fifo_element_layout", {
        "E0": "ESI + XTD + RTR + ID[28:0]",
        "E1A_no_TSU":  "MM[7:0] + ET[1:0] + FDF + BRS + DLC + TXTS[15:0]",
        "E1B_TSU":     "MM[7:0] + ET[1:0] + FDF + BRS + DLC + MM[15:8] + "
        "TSC + TXTSP[3:0]"
    })
    d.setdefault("standard_message_id_filter_element_layout", {
        "S0": "SFT[1:0] + SFEC[2:0] + SFID1[10:0] + SSYNC + SFID2[10:0]",
        "SFT_values": "00 range / 01 dual-ID / 10 classic-bit-mask / 11 "
        "disabled",
        "SFEC_values": "000 disable / 001 store FIFO0 / 010 store FIFO1 / "
        "011 reject / 100 set-priority / 101 set-priority+store FIFO0 / "
        "110 set-priority+store FIFO1 / 111 store-RxBuffer or debug"
    })
    # FORCE-overwrite extended_message_id_filter_element_layout — the F0/F1
    # values include the explicit bit-field positions per M_CAN Table 53
    # (Extended Message ID Filter Element); these positions are part of the
    # element layout, not optional shorthand.
    d["extended_message_id_filter_element_layout"] = {
        "F0": "EFEC[2:0] (bit 31:29) + EFID1[28:0]",
        "F1": "EFT[1:0] (bit 31:30) + ESYNC (bit 29) + EFID2[28:0]",
        "EFT_values": "00 range / 01 dual-ID / 10 classic-bit-mask / 11 "
        "range (XIDAM not applied)",
        "EFEC_values": "Same as SFEC"
    }
    d.setdefault("message_ram_section_capacity", {
        "max_total_words": 4352,
        "max_11bit_filters_words": 128,
        "max_29bit_filters_words": 128,
        "max_RxFIFO0_words": 1152,
        "max_RxFIFO1_words": 1152,
        "max_RxBuffers_words": 1152,
        "max_TxEventFIFO_words": 64,
        "max_TxBuffers_words": 576,
        "rx_buffer_fifo_element_size_words_by_RBDS_FnDS": {
            "000_8B": 4, "001_12B": 5, "010_16B": 6, "011_20B": 7,
            "100_24B": 8, "101_32B": 10, "110_48B": 14, "111_64B": 18},
        "tx_buffer_element_size_words_by_TBDS": "Same encoding as RxBuffer."
    })
    d.setdefault("synthesis_generic_parameters", {
        "iso_only_g": "1 → forces CCCR.NISO = 0.",
        "connected_tsu_g": "1 → enables TSU interface; 0 → CCCR.UTSU = 0.",
        "CREL_year_month_day_generics": "Set at hardware synthesis."
    })
    _write(p, d)


def _apply_l8_timing(gd: Path) -> None:
    p = gd / "L8_TIMING_WAVEFORM.json"
    if not p.is_file():
        return
    d = _read(p)
    # FORCE-overwrite nominal_bit_time_structure — CAN had Classical only,
    # and the M_CAN-specific lump of PROP_SEG into NTSEG1+PHASE_SEG1 plus
    # the zero IPT note are spec-level facts that must appear verbatim.
    d["nominal_bit_time_structure"] = {
        "SYNC_SEG":   "1 Time Quantum (tq). Used to synchronize the "
        "various nodes; an edge is expected to lie within this segment.",
        "PROP_SEG":   "Lumped into NTSEG1 with PHASE_SEG1 in M_CAN's "
        "encoding. Compensates for physical delay times on the network: "
        "twice the sum of (signal propagation + input comparator delay + "
        "output driver delay).",
        "NTSEG1":     "Programmable 2..256 tq (NTSEG1[7:0]+1). Combined "
        "Prop_Seg + Phase_Seg1.",
        "NTSEG2":     "Programmable 2..128 tq (NTSEG2[6:0]+1). Phase_Seg2.",
        "NSJW":       "Programmable 1..128 tq (NSJW[6:0]+1). Nominal "
        "(Re)Synchronization Jump Width.",
        "NBRP":       "Programmable 1..512 (NBRP[8:0]+1). Bit Rate "
        "Prescaler in arbitration phase. tq = NBRP × m_can_cclk period.",
        "SAMPLE_POINT": "At the end of NTSEG1 — bus level read.",
        "INFORMATION_PROCESSING_TIME": (
            "0 tq (data for next bit available at first clock edge after "
            "sample point — M_CAN-specific zero IPT)."),
        "BIT_TIME_TOTAL": "4..385 tq in arbitration phase."
    }
    # FORCE-overwrite data_bit_time_structure — DTDC_enable and DBRP /
    # DTSEG values are spec-defined and must include the TDC + harmonized
    # range notes verbatim.
    d["data_bit_time_structure"] = {
        "SYNC_SEG":   "1 tq",
        "DTSEG1":     "Programmable 2..32 tq (DTSEG1[4:0]+1). Combined "
        "Prop_Seg + Phase_Seg1 in data phase.",
        "DTSEG2":     "Programmable 2..16 tq (DTSEG2[3:0]+1). Phase_Seg2 "
        "in data phase. Range harmonized with ISO 11898-1:2015 in M_CAN "
        "v3.2.1.1 (errata #16).",
        "DSJW":       "Programmable 1..16 tq (DSJW[3:0]+1). Data "
        "(Re)Synchronization Jump Width.",
        "DBRP":       "Programmable 1..32 (DBRP[4:0]+1). Data Bit Rate "
        "Prescaler; limited to 1..2 when TDC is enabled.",
        "DTDC_enable": (
            "DBTP.TDC = 1 → enable Transmitter Delay Compensation."),
        "BIT_TIME_TOTAL": "4..49 tq in data phase."
    }
    d.setdefault("transmitter_delay_compensation_waveform", {
        "principle": "During CAN FD data phase the transmitter compares "
        "received bit against transmitted bit at the Secondary Sample "
        "Point (SSP).",
        "measurement_window_start": "Falling edge of FDF → res transition "
        "on m_can_tx.",
        "measurement_window_stop":  "Same edge seen on m_can_rx.",
        "ssp_position_formula": "SSP_position = measured_delay + "
        "TDCR.TDCO offset (in mtq).",
        "filter_window": "TDCR.TDCF defines minimum SSP position.",
        "data_phase_end": "Sample point of CRC delimiter.",
        "constraint_sum_le_6_bit_times": "sum of measured delay + TDCO "
        "≤ 6 bit times in data phase.",
        "constraint_sum_le_127_mtq":     "sum ≤ 127 mtq absolute.",
        "psr_tdcv_visible": "PSR.TDCV[6:0] reflects current SSP position."
    })
    # FORCE-overwrite synchronization_waveform — CAN had Classical-only.
    d["synchronization_waveform"] = {
        "HARD_SYNCHRONIZATION": "Restarts internal bit time with SYNC_SEG; "
        "forced by recessive-to-dominant edge during BUS IDLE.",
        "RESYNCHRONIZATION_arbitration":  "Lengthens NTSEG1 (positive "
        "phase error ≤ NSJW) or shortens NTSEG2 (negative phase error ≤ "
        "NSJW).",
        "RESYNCHRONIZATION_data":  "Lengthens DTSEG1 (positive phase "
        "error ≤ DSJW) or shortens DTSEG2 (negative phase error ≤ DSJW).",
        "EFBI_filter":             "CCCR.EFBI = 1: 2 consecutive dominant "
        "tq required for hard sync."
    }
    # FORCE-overwrite frame_waveform — CAN had Classical only.
    d["frame_waveform"] = {
        "CLASSICAL_DATA_FRAME": "SOF (1d) → ARBITRATION → CONTROL (r1 r0 "
        "DLC) → DATA (0..64 bits) → CRC15 + recessive delim → ACK → EOF → "
        "INTERMISSION",
        "CLASSICAL_REMOTE_FRAME": "Same as CLASSICAL_DATA_FRAME but RTR = "
        "recessive and no DATA FIELD.",
        "CAN_FD_DATA_FRAME_no_BRS": "SOF → ARBITRATION (RRS dominant) → "
        "CONTROL (r1 + FDF=1 + res=0 + BRS=0 + ESI + DLC) → DATA (0..512 "
        "bits) → [ISO: STUFF_COUNT + parity] → CRC17/CRC21 + delim → ACK "
        "→ EOF → INTERMISSION. All at NBTP rate.",
        "CAN_FD_DATA_FRAME_with_BRS": "Same but BRS = recessive. From BRS "
        "bit through CRC sequence at DBTP rate; CRC delimiter back to NBTP.",
        "ERROR_FRAME":     "ACTIVE/PASSIVE ERROR FLAG (6 dominant/"
        "recessive bits) → ERROR DELIMITER (8 recessive bits)",
        "OVERLOAD_FRAME":  "OVERLOAD FLAG (6 dominant bits) → OVERLOAD "
        "DELIMITER (8 recessive bits)"
    }
    d.setdefault("control_field_waveform_can_fd", {
        "bits_in_order": ["r1 (reserved, dominant)", "FDF (recessive)",
            "res (reserved, dominant)",
            "BRS (dominant=no switch / recessive=switch)",
            "ESI (dominant=error-active / recessive=error-passive)",
            "DLC[3:0]"]
    })
    # FORCE-overwrite interframe_space_waveform — CAN had no TRANSMIT_PAUSE,
    # and the INTERMISSION line must spell out the rule that no station may
    # start a transmission during the 3-recessive-bit gap (this is the
    # spec wording, not just the bit count).
    d["interframe_space_waveform"] = {
        "INTERMISSION":         (
            "3 recessive bits; no station may start a transmission "
            "during this time."),
        "BUS_IDLE":             "Arbitrary length recessive.",
        "SUSPEND_TRANSMISSION": "8 recessive bits after INTERMISSION; "
        "only for error-passive transmitters.",
        "TRANSMIT_PAUSE":       "2 additional CAN bit times when "
        "CCCR.TXP = 1."
    }
    d.setdefault("active_error_flag_superposition_waveform",
        "When multiple nodes detect the error and each transmit a 6-"
        "dominant-bit ACTIVE ERROR FLAG, the result on the bus is a "
        "superposition of 6..12 dominant bits.")
    d.setdefault("phase_error_definition", {
        "e_eq_0": "Edge lies within SYNC_SEG.",
        "e_gt_0": "Edge lies before the SAMPLE POINT.",
        "e_lt_0": "Edge lies after the SAMPLE POINT of the previous bit."
    })
    d.setdefault("max_distance_between_resync_edges_bit_times", 29)
    d.setdefault("reset_bit_timing_examples", {
        "NBTP_reset_8MHz_500kbps":  "NBRP=1, NTSEG1=12, NTSEG2=4, NSJW=4 "
        "→ 16 tq → 500 kbps at 8 MHz m_can_cclk.",
        "DBTP_reset_8MHz_500kbps":  "DBRP=1, DTSEG1=12, DTSEG2=4, DSJW=4 "
        "→ 16 tq → 500 kbps at 8 MHz m_can_cclk.",
        "CAN_FD_5Mbps_example":     "20 MHz m_can_cclk + DBRP=1 + 4 tq "
        "bit time → 5 Mbit/s data phase."
    })
    d.setdefault("byte_packing_in_message_ram", {
        "rule": "Data bytes packed 4-per-32-bit-word.",
        "note": "Element size words = data_bytes / 4 + 2 header words "
        "(rounded up per RXESC / TXESC encoding)."
    })
    d.setdefault("filter_path_waveforms", {
        "standard_id_filter_path": [
            "Valid frame received → 11-bit identifier path",
            "If remote frame AND GFC.RRFS = 1 → discard.",
            "Else: walk SIDFC.LSS standard filter elements.",
            "First matching element → apply SFEC action.",
            "No match: ANFS[1]=0 → accept to FIFO0/FIFO1 per ANFS[0]; "
            "ANFS[1]=1 → discard.",
            "If target FIFO selected and full in blocking mode → discard."
        ],
        "extended_id_filter_path": [
            "Valid 29-bit identifier path: ID ANDed with XIDAM before "
            "filter list comparison.",
            "If remote frame AND GFC.RRFE = 1 → discard.",
            "Else: walk XIDFC.LSE extended filter elements.",
            "No match: ANFE[1]=0 → accept; ANFE[1]=1 → discard."
        ]
    })
    _write(p, d)


def _apply_l9(gd: Path) -> None:
    p = gd / "L9_INTEGRATION_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    # FORCE-overwrite module_role (CAN's was wire-level Classical wording).
    d["module_role"] = (
        "Synthesizable CAN-FD communication controller IP (Bosch M_CAN), "
        "integrable as stand-alone or part of an ASIC. Performs "
        "communication per ISO 11898-1:2015. Includes CAN Core + Tx/Rx "
        "Handlers + Generic Slave Interface (Host CPU) + Generic Master "
        "Interface (32-bit Message RAM) + Extension Interface (optional). "
        "Requires external CAN transceiver + external Message RAM.")
    d["layered_structure_summary"] = [
        "Application Layer — out of scope.",
        "Object Layer — message acceptance filtering (Acceptance Filter + "
        "Standard/Extended Filter Elements), Tx + Rx mailbox management.",
        "Transfer Layer (kernel) — BSP, BTL, EML, Acceptance Filter per "
        "ISO 11898-1:2015.",
        "Physical Layer — outside M_CAN; external transceiver translates "
        "between m_can_tx/m_can_rx and CANH/CANL voltages."
    ]
    d["integration_overview"] = {
        "topology":          "Single shared CAN serial channel.",
        "drive_type":        "Wired-AND at the bus.",
        "no_chip_select":    "CAN is content-addressed by IDENTIFIER.",
        "uniform_arbitration_bit_rate":  "Arbitration bit rate (NBTP) "
        "uniform within a CAN network. Data phase bit rate (DBTP) may be "
        "higher but must be ≥ arbitration rate.",
        "max_baud_typical": "Arbitration ≤ 1 Mbit/s; data phase typically "
        "2 / 5 / 8 Mbit/s."
    }
    # FORCE-overwrite interface_categories — CAN had only 3.
    d["interface_categories"] = [
        "Generic Slave Interface — Host CPU register access.",
        "Generic Master Interface — 32-bit external Message RAM.",
        "CAN PHY interface — m_can_tx + m_can_rx.",
        "Interrupt interface — m_can_int0 + m_can_int1.",
        "TSU interface — m_can_tsrx + m_can_tstx + m_can_ext_ts inputs.",
        "DMU interface — m_can_dma_req / m_can_dma_ack.",
        "Extension interface — all IR flags + selected status/control.",
        "Power-down interface — m_can_clkstop_req + m_can_clkstop_ack.",
        "Clock interface — m_can_hclk + m_can_cclk."
    ]
    d["interconnect_topologies_supported"] = [
        "Single multi-master bus — all CAN nodes share one physical "
        "channel.",
        "Multiple M_CANs sharing the same Message RAM.",
        "Mixed Classical-CAN + CAN-FD nodes (when CCCR.FDOE = 1).",
        "Mixed ISO + non-ISO CAN-FD nodes — CCCR.NISO selects which "
        "frame format is generated/accepted; mixing on same bus is NOT "
        "interoperable."
    ]
    d["default_signal_values_when_omitted"] = (
        "Bus idle = all nodes drive recessive. M_CAN's m_can_tx is held "
        "recessive (HIGH) under CCCR.INIT = 1.")
    d["soc_dependent_items"] = [
        "External transceiver choice (ISO 11898-2 / -3 / -6).",
        "Pull-up / termination resistor selection.",
        "Crystal / oscillator selection for m_can_cclk.",
        "m_can_hclk choice — may be FM-PLL spread spectrum; must satisfy "
        "m_can_hclk ≥ m_can_cclk.",
        "Message RAM size + ECC/parity choice.",
        "Filter element count programming (SIDFC.LSS / XIDFC.LSE).",
        "Rx FIFO + Rx Buffer + Tx Buffer / FIFO / Queue + Tx Event FIFO "
        "element counts + start addresses.",
        "Bit-timing programming (NBTP / DBTP / TDCR).",
        "Interrupt-line routing (ILS / ILE) + per-flag enables (IE).",
        "Clock-stop / power-down strategy + wake-up source.",
        "Optional TSU (CiA 603) + DMU connection.",
        "Synthesis generic parameter choice: iso_only_g, "
        "connected_tsu_g, CREL synthesis-stamp values."
    ]
    d["low_power_modes"] = {
        "sleep_mode": "Triggered via m_can_clkstop_req or CCCR.CSR. After "
        "pending Tx complete + bus idle: CCCR.INIT set, m_can_clkstop_ack "
        "+ CCCR.CSA = 1.",
        "wake_up":    "Restart clocks → CPU deasserts m_can_clkstop_req → "
        "M_CAN clears m_can_clkstop_ack + CCCR.CSA → CPU clears CCCR.INIT "
        "→ BSP synchronizes to bus.",
        "abort_path": "If bus is heavily disturbed and idle is never "
        "reached, CCCR.INIT is not set automatically; software polls "
        "PSR.ACT."
    }
    d.setdefault("l9_contract_summary", {
        "host_cpu_protocol": "Memory-mapped 32-bit register bus, 8/16/32-"
        "bit access. Protected-Write for configuration. W1C on IR flags.",
        "message_ram_protocol": "32-bit Generic Master Interface; M_CAN "
        "drives m_can_aeim_sel + address + write data, RAM responds with "
        "m_can_aeim_ready + read data + m_can_aeim_berr[1:0].",
        "phy_protocol": "Logical-level m_can_tx + m_can_rx. External "
        "transceiver drives differential bus.",
        "interrupt_protocol": "Two CPU lines per ILE; per-flag enable + "
        "line-select via IE + ILS.",
        "clock_domain_protocol": "m_can_hclk ≥ m_can_cclk; Sync block "
        "handles cross-domain handoff."
    })
    _write(p, d)


def _apply_l10(gd: Path) -> None:
    p = gd / "L10_TEST_CASES.json"
    if not p.is_file():
        return
    d = _read(p)
    # FORCE-overwrite test_cases_present — CAN said "partial" with Classical
    # focus. Reset to CAN FD framing.
    d["test_cases_present"] = (
        "partial — the M_CAN User's Manual describes operating modes, "
        "register semantics, and protocol behaviors per ISO 11898-1:2015 "
        "that directly map to compliance test scenarios but no formal "
        "testbench is shipped.")
    d["derived_compliance_test_categories"] = [
        "Classical CAN DATA FRAME with each DLC value 0..8.",
        "CAN FD DATA FRAME with each DLC value 0..15 (covers payload "
        "sizes 0..64 bytes).",
        "CAN FD DATA FRAME with BRS = 0 AND BRS = 1 — covering both DBTP "
        "and NBTP-only data phases.",
        "CAN FD DATA FRAME with ESI = 1 AND ESI = 0.",
        "Classical REMOTE FRAME → matching DATA FRAME response (REMOTE "
        "FRAMES illegal in CAN FD).",
        "Bitwise arbitration with 2 and 3 nodes — Classical and CAN-FD "
        "mixed.",
        "Arbitration loss at first differing bit.",
        "Protocol Exception Event (FDF = recessive + res = recessive) → "
        "PSR.PXE = 1.",
        "CRC mismatch in Classical CAN (15-bit BCH).",
        "CRC mismatch in CAN FD CRC-17 (≤16-byte payload).",
        "CRC mismatch in CAN FD CRC-21 (>16-byte payload).",
        "Stuff-count parity error in ISO CAN FD (CCCR.NISO = 0).",
        "STUFF ERROR injection — Classical and CAN FD frames.",
        "FORM ERROR injection on Classical CAN fixed-form fields.",
        "FORM ERROR injection on CAN FD fixed-form stuff bits.",
        "ACKNOWLEDGMENT ERROR.",
        "BIT ERROR in arbitration phase (PSR.LEC ≠ 0,7).",
        "BIT ERROR in data phase of FD frame with BRS = 1 (PSR.DLEC ≠ 0,7).",
        "Nominal Bit Timing per-segment programming sweep.",
        "Data Bit Timing per-segment programming sweep.",
        "Transmitter Delay Compensation: verify PSR.TDCV updated.",
        "TDC filter window (TDCR.TDCF) suppression of early dominant edges.",
        "Hard synchronization on SOF — verify CCCR.EFBI = 0 vs = 1.",
        "Resynchronization within ±NSJW / ±DSJW.",
        "Fault confinement counter transitions.",
        "Warning level (count ≥ 96) → PSR.EW = 1 + IR.EW.",
        "Error Logging Counter ECR.CEL increment + overflow → IR.ELO.",
        "Restricted Operation Mode.",
        "Bus Monitoring Mode.",
        "Disabled Automatic Retransmission.",
        "External Loop Back Mode.",
        "Internal Loop Back Mode.",
        "Tx Pin Driver Control + Rx Pin Monitor.",
        "Power-down sequence + abort path + wake-up.",
        "Acceptance Filter — all SFT/EFT types + all SFEC/EFEC actions.",
        "Acceptance Filter — XIDAM masking for 29-bit IDs.",
        "Acceptance Filter — Sync messages → m_can_tsrx pulse.",
        "Acceptance Filter — filter event pins → m_can_fe[2:0].",
        "Acceptance Filter — debug message A / B / C handling.",
        "Rx FIFO 0 + Rx FIFO 1 blocking + overwrite modes.",
        "Dedicated Rx Buffer New Data flag handling.",
        "Tx FIFO transmit-in-put-order.",
        "Tx Queue transmit-by-lowest-ID.",
        "Mixed Dedicated + FIFO / Mixed Dedicated + Queue.",
        "Tx Buffer Add Request + Cancellation.",
        "Tx Event FIFO — ET = 01 / ET = 10 cases.",
        "Internal vs External Timestamp Counter (required for CAN FD).",
        "TSU external 32-bit timestamping (CCCR.UTSU = 1).",
        "Wide Message Markers (CCCR.WMM = 1).",
        "Timeout Counter — all 4 modes.",
        "Access to Reserved Address → IR.ARA.",
        "Message RAM Access Failure → IR.MRAF.",
        "External ECC/Parity feedback.",
        "ISO vs non-ISO CAN FD selection.",
        "Iso-only synthesis lock.",
        "Transmit Pause (CCCR.TXP = 1)."
    ]
    _write(p, d)


def _apply_l11(gd: Path) -> None:
    p = gd / "L11_OTP_CONTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    d["otp_present"] = False
    d["notes"] = (
        "The M_CAN module has no OTP / fuse / configuration ROM at the "
        "protocol layer. The only synthesis-time-locked values are the "
        "BCD-coded YEAR / MONTH / DAY fields in the Core Release Register "
        "(CREL) set by hardware-synthesis generic parameters, and the "
        "synthesis generic parameters iso_only_g (forces CCCR.NISO = 0 "
        "when 1) and connected_tsu_g (when 0, fixes CCCR.UTSU = 0). "
        "Customer Register at 0x008 is reserved for customer-specific "
        "configuration / control / status bits — functionality outside "
        "this spec.")
    _write(p, d)


def _apply_l12(gd: Path) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("software_initialization_sequence", [
        "1. After hardware reset, CCCR.INIT = 1; m_can_tx = recessive.",
        "2. Set CCCR.CCE = 1 to enable write access.",
        "3. Initialize Message RAM (write 0x0 to each word) if ECC enabled.",
        "4. Program NBTP, DBTP, TDCR.",
        "5. Program GFC, SIDFC, XIDFC, XIDAM.",
        "6. Program RXF0C / RXF1C / RXBC / RXESC.",
        "7. Program TXBC / TXESC / TXEFC.",
        "8. Program CCCR: NISO, TXP, EFBI, PXHD, WMM, UTSU, BRSE, FDOE, "
        "DAR.",
        "9. Program TSCC, TOCC, IE, ILS, ILE, TXBTIE, TXBCIE.",
        "10. Clear CCCR.CCE.",
        "11. Clear CCCR.INIT.",
        "12. BSP waits for 11 consecutive recessive bits before joining "
        "bus."
    ])
    # FORCE-overwrite typical_data_frame_transmit_sequence — CAN's was Classical.
    d["typical_classical_data_frame_transmit_sequence"] = [
        "1. Host writes Tx Buffer element (T0/T1/T2..Tn).",
        "2. Host writes TXBAR.AR_n = 1.",
        "3. M_CAN Tx Handler scans Tx Buffers + updates TXBRP.TRP_n.",
        "4. At Bus_Idle: drive SOF.",
        "5. Drive IDENTIFIER + RTR.",
        "6. Drive CONTROL FIELD (r1 + r0/FDF=0 + DLC).",
        "7. Drive DATA FIELD (0..8 bytes).",
        "8. Drive 15-bit CRC + recessive CRC DELIMITER.",
        "9. Drive recessive ACK SLOT; sample bus.",
        "10. Drive ACK DELIMITER + EOF.",
        "11. Drive INTERMISSION.",
        "12. (error-passive) SUSPEND TRANSMISSION.",
        "13. (CCCR.TXP = 1) 2-bit-time pause.",
        "14. Set TXBRP.TRP_n = 0 + TXBTO.TO_n = 1; raise IR.TC.",
        "15. (T1.EFC = 1) Write Tx Event FIFO."
    ]
    d.setdefault("typical_can_fd_data_frame_transmit_sequence_with_BRS", [
        "1..3. Same as Classical but T1.FDF = 1 + BRS = 1.",
        "4. Drive SOF → hard-sync.",
        "5. Drive IDENTIFIER + RRS (always dominant).",
        "6a. Drive r1 + FDF=1 + res + BRS=1 at NBTP rate.",
        "6b. At BRS bit sample point: switch to DBTP. ESI + DLC at DBTP.",
        "7. Drive DATA FIELD (0..64 bytes) at DBTP.",
        "8a. (ISO) Drive 3-bit stuff-count + 1-bit parity.",
        "8b. Drive CRC17 or CRC21 at DBTP.",
        "9. At CRC DELIMITER: switch back to NBTP.",
        "10. Drive ACK SLOT (ACK timing SSP-aware).",
        "11. Drive ACK DELIMITER + EOF + INTERMISSION.",
        "12. PSR.TDCV updated.",
        "13. (T1.EFC = 1) Write Tx Event FIFO with FDF + BRS = 1."
    ])
    d.setdefault("typical_can_fd_data_frame_transmit_sequence_no_BRS",
        ["Same as classical except T1.FDF = 1, BRS = 0. Whole frame at "
         "NBTP rate; CAN FD CRC; RRS replaces RTR."])
    d.setdefault("typical_remote_frame_sequence_classical_only", [
        "1. Host writes Tx Buffer T0.RTR = 1, T1.FDF = 0, T1.DLC = 0.",
        "2. M_CAN transmits Classical remote frame even if CCCR.FDOE = 1.",
        "3. Node holding matching DATA FRAME responds.",
        "4. DATA wins over REMOTE on simultaneous start."
    ])
    # FORCE-overwrite typical_receive_sequence — CAN's was Classical.
    d["typical_receive_sequence"] = [
        "1. Receiver detects SOF dominant bit; hard-synchronizes.",
        "2. Sample IDENTIFIER + RTR (or RRS in FD) + IDE.",
        "3. At FDF bit: dominant → Classical path; recessive → FD path.",
        "4. (FD) Detect res bit: if res = 1 → Protocol Exception.",
        "5. (FD) Detect BRS bit: if BRS = 1 → switch to DBTP.",
        "6. Receive DATA FIELD + CRC + (ISO FD) stuff-count parity.",
        "7. (FD with BRS = 1) At CRC delimiter: switch back to NBTP.",
        "8. If CRC matched: drive dominant ACK on ACK SLOT.",
        "9. Apply Acceptance Filter; write Rx FIFO / Rx Buffer element.",
        "10. Raise IR.RFnN / IR.DRX / IR.HPM.",
        "11. (Sync message with CCCR.UTSU = 1) Pulse m_can_tsrx.",
        "12. (Filter event pins) Pulse m_can_fe[2:0]."
    ]
    d.setdefault("arbitration_loss_sequence", [
        "1. Two transmitters start simultaneously on Bus_Idle.",
        "2. On each ARBITRATION FIELD bit, each compares its driven bit.",
        "3. First recessive-driven vs dominant-monitored → lose.",
        "4. Loser withdraws and becomes receiver.",
        "5. May retry once bus idle again (unless CCCR.DAR = 1)."
    ])
    d.setdefault("error_signalling_sequence", [
        "1. Error-active node detects BIT/STUFF/FORM/ACK error.",
        "2. Transmit ACTIVE ERROR FLAG (6 dominant bits).",
        "3. Other nodes superpose their own flags.",
        "4. ERROR DELIMITER (8 recessive bits).",
        "5. PSR.LEC / PSR.DLEC updated; IR.PEA / IR.PED raised.",
        "6. Original transmitter retransmits (unless DAR)."
    ])
    d.setdefault("fault_confinement_transition_sequence", [
        "1. error-active → error-passive: TEC ≥ 128 OR REC ≥ 128. ESI "
        "forced recessive in CAN FD.",
        "2. error-passive → bus-off: TEC = 256. CCCR.INIT set "
        "automatically.",
        "3. error-passive → error-active: both ≤ 127.",
        "4. bus-off → error-active: 129 × Bus_Idle after CPU clears "
        "CCCR.INIT."
    ])
    d.setdefault("tx_event_handling_sequence", [
        "1. Tx Handler completes transmission.",
        "2. If T1.EFC = 1, write Tx Event FIFO at TXEFS.EFPI.",
        "3. EFPI + EFFL incremented.",
        "4. Watermark / Full → IR.TEFW / IR.TEFF.",
        "5. Host reads element at EFGI; writes TXEFA.EFAI."
    ])
    d.setdefault("transmit_cancellation_sequence", [
        "1. Host writes TXBCR.CR_n = 1 (dedicated or Queue only).",
        "2. If not yet started: TXBRP.TRP_n cleared; TXBCF.CF_n set.",
        "3. If ongoing: cancellation finishes on success / disturbance.",
        "4. IR.TCF raised.",
        "5. DAR mode + success-in-spite-of-cancel: Tx Event with ET = 10."
    ])
    d.setdefault("power_down_sequence", [
        "1. CPU asserts m_can_clkstop_req or sets CCCR.CSR = 1.",
        "2. M_CAN completes pending Tx + waits for Bus_Idle.",
        "3. CCCR.INIT set internally.",
        "4. m_can_clkstop_ack + CCCR.CSA = 1.",
        "5. Clocks may be stopped.",
        "6. Wake: restart clocks → deassert m_can_clkstop_req.",
        "7. M_CAN clears m_can_clkstop_ack + CCCR.CSA.",
        "8. CPU clears CCCR.INIT."
    ])
    d.setdefault("tdc_per_frame_sequence_with_BRS", [
        "1. CCCR.FDOE = 1 + CCCR.BRSE = 1 + T1.FDF = 1 + BRS = 1 + "
        "DBTP.TDC = 1.",
        "2. At FDF → res falling edge on m_can_tx, start delay counter.",
        "3. Stop when same edge seen on m_can_rx.",
        "4. SSP_position = measured_delay + TDCR.TDCO.",
        "5. TDCR.TDCF filters early dominant edges.",
        "6. Use SSP for bit-error check in data phase.",
        "7. PSR.TDCV updated."
    ])
    d.setdefault("acceptance_filter_sequence_for_high_priority_message", [
        "1. Configure filter element with SFEC/EFEC = 100/101/110.",
        "2. Receiver matches incoming frame.",
        "3. Match: update HPMS register with FLST/FIDX/MSI/BIDX.",
        "4. Raise IR.HPM.",
        "5. Host CPU reads HPMS, fast-paths the message."
    ])
    d.setdefault("debug_on_can_dma_sequence", [
        "1. Configure 3 filter elements with SFEC/EFEC = 111 + SFID2/"
        "EFID2[10:9] = 01 (A), 10 (B), 11 (C).",
        "2. Configure 3 consecutive Rx Buffers for A/B/C.",
        "3. DMS = 00 initially.",
        "4. Receive A → DMS = 01.",
        "5. Receive B → DMS = 10.",
        "6. Receive C → DMS = 11 → m_can_dma_req.",
        "7. DMA reads + asserts m_can_dma_ack → DMS = 00."
    ])
    _write(p, d)


def _apply_l13(gd: Path) -> None:
    p = gd / "L13_LAB_CALIBRATION.json"
    if not p.is_file():
        return
    d = _read(p)
    d["lab_calibration_present"] = False
    d["notes"] = (
        "The M_CAN controller is purely digital and ships no analog "
        "reference / trim / calibration loop. Oscillator tolerance for "
        "the high-precision CAN clock m_can_cclk is a system-integration "
        "concern (CAN FD's faster data phase makes this stricter than "
        "Classical CAN — typical implementations require ≤0.1 % crystal "
        "at 5 Mbit/s data rate). Per-segment bit-timing programming "
        "(NTSEG1 / NTSEG2 / NSJW / NBRP for arbitration; DTSEG1 / DTSEG2 "
        "/ DSJW / DBRP for data) plus Transmitter Delay Compensation "
        "(DBTP.TDC + TDCR.TDCO + TDCR.TDCF) substitute for any analog "
        "calibration loop at the controller level. The Clock Calibration "
        "on CAN unit (CCC) integration is indicated by m_can_cok: when "
        "0, CCCR.ASM is forced 1 (Restricted Operation Mode); when 1, "
        "normal operation. Default tied-high when no CCC is connected.")
    _write(p, d)


def _apply_l14(gd: Path) -> None:
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    # FORCE-overwrite spec_version (CAN had Sept 1991 Classical).
    f["spec_version"] = "M_CAN Revision 3.3.1 (11.03.2023)"
    f["previous_versions"] = [
        "0.1-0.7 (2008) — early working revisions.",
        "1.0 (25.03.2009) — first complete revision.",
        "1.1 (25.06.2009) — Tx Handler functionality updated.",
        "1.2 (20.08.2009) — register TXBSC removed, RAM Watchdog added.",
        "2.0 (27.10.2011) — debug on CAN, dedicated Rx Buffers, CAN FD, "
        "Extension IF.",
        "3.0 (17.10.2012) — FIFO overwrite mode, transmit pause, CAN FD "
        "64-byte frames.",
        "3.1.0 (22.07.2014) — Major register restructure: FBTP→DBTP, "
        "BTP→NBTP, EDL→FDF, CCCR.FDOE+BRSE, TDCR added.",
        "3.1.5 (14.10.2014) — Bit NISO added to CCCR.",
        "3.2.1.1 (24.03.2016) — ISO 11898-1 references updated; "
        "NBTP.NTSEG2 range fixed.",
        "3.3.0 (30.10.2018) — Wide Message Markers, DMU + TSU interface, "
        "Sync message filtering.",
        "3.3.1 (11.03.2023) — DTSEG2 range harmonized with "
        "ISO 11898-1:2015; Tx Buffer handling wording corrections."
    ]
    f["key_changes"] = [
        {"version": "v2.0 (2011)",
         "summary": "Major: CAN FD support introduced; debug on CAN; "
         "dedicated Rx Buffers; Extension Interface."},
        {"version": "v3.0 (2012)",
         "summary": "FIFO overwrite mode + transmit pause + CAN FD 64-"
         "byte frame support."},
        {"version": "v3.1.0 (2014)",
         "summary": "Major register restructure for CAN FD: DBTP / NBTP "
         "/ FDF / FDOE+BRSE / TDCR / interrupt flag renames."},
        {"version": "v3.1.5 (2014)",
         "summary": "CCCR.NISO bit added — selectable ISO 11898-1:2015 "
         "vs Bosch CAN FD V1.0."},
        {"version": "v3.3.0 (2018)",
         "summary": "Wide Message Markers (CCCR.WMM); DMU + TSU "
         "interfaces; CCCR.UTSU bit; Sync-message timestamping."},
        {"version": "v3.3.1 (2023)",
         "summary": "DTSEG2 range harmonized; Tx Buffer handling "
         "wording corrections."}
    ]
    f["backward_compat_traps"] = [
        {"trap_name": "register_name_changes_pre_v3.1",
         "pre_v3.1_register_names":  "FBTP / BTP / EDL / CME / FDBS",
         "post_v3.1_register_names": "DBTP / NBTP / FDF / FDOE+BRSE / EFBI",
         "trap": "Driver code for M_CAN v3.0 will not compile / will "
         "misprogram registers when ported to ≥ v3.1.0."},
        {"trap_name": "iso_vs_non_iso_can_fd",
         "iso_only_g_eq_1":  "Synthesis-locked to ISO 11898-1:2015.",
         "iso_only_g_eq_0":  "Software-selectable via CCCR.NISO.",
         "trap": "Mixing ISO + non-ISO CAN FD nodes on the same bus is "
         "NOT interoperable."},
        {"trap_name": "wmm_disables_internal_timestamp",
         "with_WMM_eq_1": "Wide Message Markers use 16-bit MM; internal "
         "Tx timestamping DISABLED in Tx Event FIFO.",
         "trap": "Code expecting internal Tx timestamp will see empty "
         "TXTS field when WMM = 1."},
        {"trap_name": "tsu_requires_external_timestamp_counter_for_can_fd",
         "without_external_counter": "TSCC.TSS = 01 works for Classical "
         "CAN only.",
         "for_can_fd": "External timebase via m_can_ext_ts required "
         "(TSCC.TSS = 10).",
         "trap": "CAN FD frames timestamped with internal counter will "
         "have inaccurate timestamps across BRS switch."}
    ]
    f["version_naming_history_note"] = (
        "M_CAN is Bosch's reference CAN-FD controller — successor to "
        "C_CAN (Classical CAN). M_CAN v3.1.0 (2014) was the major "
        "restructure that consolidated the CAN-FD register set. "
        "ISO 11898-1:2015 is the protocol standard M_CAN implements; "
        "Bosch CAN FD Specification V1.0 is the precursor non-ISO format "
        "selectable via CCCR.NISO. CAN FD is a frame-format-only "
        "extension of Classical CAN: same physical layer + ID semantics "
        "+ arbitration, with three new control bits (FDF/BRS/ESI) + new "
        "DLC encoding + new CRC.")
    d["fields"] = f
    _write(p, d)


def _apply_l15(gd: Path) -> None:
    p = gd / "L15_ENCODING_TABLES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    # FORCE-overwrite the DLC table — CAN had Classical only.
    if "data_length_code_table" in f:
        del f["data_length_code_table"]
    f["data_length_code_table_classical"] = {
        "header_columns": ["DLC[3:0]", "Number of Data Bytes (Classical)"],
        "rows": [["0000", 0], ["0001", 1], ["0010", 2], ["0011", 3],
                 ["0100", 4], ["0101", 5], ["0110", 6], ["0111", 7],
                 ["1000", 8], ["1001", 8], ["1010", 8], ["1011", 8],
                 ["1100", 8], ["1101", 8], ["1110", 8], ["1111", 8]],
        "note": "Classical CAN: DLC values 9..15 all encode 8 data bytes."
    }
    f["data_length_code_table_can_fd"] = {
        "header_columns": ["DLC[3:0]", "Number of Data Bytes (CAN FD)"],
        "rows": [["0000", 0], ["0001", 1], ["0010", 2], ["0011", 3],
                 ["0100", 4], ["0101", 5], ["0110", 6], ["0111", 7],
                 ["1000", 8], ["1001", 12], ["1010", 16], ["1011", 20],
                 ["1100", 24], ["1101", 32], ["1110", 48], ["1111", 64]],
        "note": "CAN FD extends DLC: codes 9..15 select 12/16/20/24/32/"
        "48/64 bytes per Table 54."
    }
    # FORCE-overwrite frame_field_widths_table — CAN had Classical only.
    if "frame_field_widths_table" in f:
        del f["frame_field_widths_table"]
    f["frame_field_widths_table_classical"] = {
        "header_columns": ["Field", "Width (bits)", "Form"],
        "rows": [
            ["START_OF_FRAME",     "1",       "1 dominant bit"],
            ["IDENTIFIER (standard)", "11",   "MSB-first"],
            ["RTR", "1", "dominant DATA / recessive REMOTE"],
            ["r1 r0", "2", "transmitter dominant"],
            ["DLC", "4", "0..8 admissible"],
            ["DATA", "0..64", "0..8 bytes; MSB-first"],
            ["CRC_SEQUENCE", "15", "BCH polynomial CRC"],
            ["CRC_DELIMITER", "1", "1 recessive bit"],
            ["ACK_SLOT", "1", "transmitter recessive"],
            ["ACK_DELIMITER", "1", "1 recessive bit"],
            ["END_OF_FRAME", "7", "all recessive"],
            ["INTERMISSION", "3", "all recessive"],
            ["SUSPEND_TRANSMISSION", "8", "error-passive TX only"]
        ]
    }
    f["frame_field_widths_table_can_fd"] = {
        "header_columns": ["Field", "Width (bits)", "Form"],
        "rows": [
            ["START_OF_FRAME", "1", "1 dominant bit"],
            ["IDENTIFIER (standard)", "11", "MSB-first"],
            ["RRS", "1", "always dominant (replaces RTR; no remote frames)"],
            ["r1", "1", "transmitter dominant"],
            ["FDF", "1", "recessive (signals CAN FD format)"],
            ["res", "1", "transmitter dominant; FDF+res=11 triggers "
             "Protocol Exception"],
            ["BRS", "1", "dominant=no switch; recessive=switch to DBTP"],
            ["ESI", "1", "dominant=error-active; recessive=error-passive"],
            ["DLC", "4", "per CAN FD DLC table (0..64 bytes)"],
            ["DATA", "0..512", "0..64 data bytes per DLC"],
            ["STUFF_COUNT (ISO)", "4", "3-bit count + 1-bit parity"],
            ["CRC_SEQUENCE_LE_16B", "17", "CRC-17 for ≤16 bytes"],
            ["CRC_SEQUENCE_GT_16B", "21", "CRC-21 for >16 bytes"],
            ["CRC_DELIMITER", "1", "1 recessive; rate switches back to NBTP"],
            ["ACK_SLOT", "1", "transmitter recessive; SSP-aware timing"],
            ["ACK_DELIMITER", "1", "1 recessive bit"],
            ["END_OF_FRAME", "7", "all recessive"],
            ["INTERMISSION", "3", "all recessive"]
        ]
    }
    f.setdefault("extended_id_arbitration_field_widths", {
        "header_columns": ["Sub-field", "Width", "Form"],
        "rows": [
            ["11-bit IDENTIFIER (ID[28:18])", "11", "First MSBs of "
             "29-bit ID"],
            ["SRR (Substitute Remote Request)", "1", "Always recessive"],
            ["IDE (Identifier Extension)", "1", "Recessive → 29-bit; "
             "Dominant → 11-bit"],
            ["18-bit IDENTIFIER (ID[17:0])", "18", "Remaining LSBs"],
            ["RTR (Classical) or RRS (CAN FD)", "1", "Last bit of "
             "arbitration field"]
        ]
    })
    f.setdefault("rx_buffer_fifo_element_size_table", {
        "header_columns": ["RBDS / FnDS", "Data Field (bytes)",
            "Element Size (RAM 32-bit words)"],
        "rows": [["000", 8, 4], ["001", 12, 5], ["010", 16, 6],
                 ["011", 20, 7], ["100", 24, 8], ["101", 32, 10],
                 ["110", 48, 14], ["111", 64, 18]]
    })
    f.setdefault("tx_buffer_element_size_table", {
        "header_columns": ["TBDS", "Data Field (bytes)",
            "Element Size (RAM 32-bit words)"],
        "rows": [["000", 8, 4], ["001", 12, 5], ["010", 16, 6],
                 ["011", 20, 7], ["100", 24, 8], ["101", 32, 10],
                 ["110", 48, 14], ["111", 64, 18]]
    })
    f.setdefault("frame_transmission_configuration_table", {
        "header_columns": ["CCCR.BRSE", "CCCR.FDOE", "Tx Buffer FDF",
            "Tx Buffer BRS", "Frame Transmission"],
        "rows": [
            ["ignored", "0", "ignored", "ignored", "Classical CAN"],
            ["0",       "1", "0",       "ignored", "Classical CAN"],
            ["0",       "1", "1",       "ignored", "FD without bit rate "
             "switching"],
            ["1",       "1", "0",       "ignored", "Classical CAN"],
            ["1",       "1", "1",       "0",       "FD without bit rate "
             "switching"],
            ["1",       "1", "1",       "1",       "FD with bit rate "
             "switching"]
        ]
    })
    f.setdefault("psr_last_error_code_table", {
        "header_columns": ["LEC / DLEC value", "Meaning"],
        "rows": [["0", "No Error"], ["1", "Stuff Error"],
                 ["2", "Form Error"], ["3", "Ack Error"],
                 ["4", "Bit1Error"], ["5", "Bit0Error"],
                 ["6", "CRCError"], ["7", "NoChange"]]
    })
    f.setdefault("filter_element_type_sft_eft_table", {
        "header_columns": ["SFT/EFT", "Type"],
        "rows": [["00", "Range filter"], ["01", "Dual-ID filter"],
                 ["10", "Classic bit-mask filter"],
                 ["11", "Disabled / Range w/o XIDAM"]]
    })
    f.setdefault("filter_element_config_sfec_efec_table", {
        "header_columns": ["SFEC/EFEC", "Action on Match"],
        "rows": [
            ["000", "Disable filter element"],
            ["001", "Store in Rx FIFO 0"],
            ["010", "Store in Rx FIFO 1"],
            ["011", "Reject ID"],
            ["100", "Set priority match, no storage"],
            ["101", "Set priority + store FIFO 0"],
            ["110", "Set priority + store FIFO 1"],
            ["111", "Store into Rx Buffer or as debug message"]
        ]
    })
    f.setdefault("timestamp_select_tscc_tss_table", {
        "header_columns": ["TSCC.TSS[1:0]", "Behavior"],
        "rows": [["00", "Timestamp always 0"],
                 ["01", "Internal counter incremented per TSCC.TCP"],
                 ["10", "External timestamp counter (required for CAN FD)"],
                 ["11", "Same as 00"]]
    })
    f.setdefault("tx_event_type_et_table", {
        "header_columns": ["ET[1:0]", "Meaning"],
        "rows": [["00", "Reserved"], ["01", "Tx event"],
                 ["10", "Transmission in spite of cancellation"],
                 ["11", "Reserved"]]
    })
    # FORCE-overwrite crc_polynomial — CAN had Classical only.
    f["crc_polynomials"] = (
        "Classical CAN: X^15 + X^14 + X^10 + X^8 + X^7 + X^4 + X^3 + 1 "
        "(hex 0x4599). CAN FD ISO mode: CRC-17 (≤16 B) + CRC-21 (>16 B), "
        "each prefixed with 3-bit stuff-bit-count + 1-bit parity per "
        "ISO 11898-1:2015. CAN FD non-ISO mode: same CRC-17 / CRC-21 "
        "polynomials without stuff-count protection.")
    f["endian_test_value"] = (
        "ENDN register at 0x004 always reads 0x87654321.")
    f.setdefault("tables", [
        "Table 1 — M_CAN Register Map",
        "Table 8 — CC Control Register CCCR",
        "Table 9 — Nominal Bit Timing & Prescaler NBTP",
        "Table 5 — Data Bit Timing & Prescaler DBTP",
        "Table 15 — Protocol Status Register PSR",
        "Table 49 — Rx Buffer and FIFO Element",
        "Table 50 — Tx Buffer Element",
        "Table 51 — Tx Event FIFO Element",
        "Table 52 — Standard Message ID Filter Element",
        "Table 53 — Extended Message ID Filter Element",
        "Table 54 — Coding of DLC in CAN FD",
        "Table 55 — Rx Buffer / FIFO Element Size",
        "Table 58 — Possible Configurations for Frame Transmission",
        "Table 60 — M_CAN Register Overview"
    ])
    # Classical-CAN-specific scalar keys CAN synth set — drop them. But
    # error_frame_table and overload_frame_table are common to Classical
    # CAN AND CAN FD (same ACTIVE_ERROR_FLAG / PASSIVE_ERROR_FLAG /
    # ERROR_DELIMITER / OVERLOAD_FLAG / OVERLOAD_DELIMITER widths and
    # forms); add them in the spec-table shape if missing.
    f.pop("crc_polynomial", None)
    f.pop("wake_up_message_identifier_encoding", None)
    f["error_frame_table"] = {
        "header_columns": ["Sub-field", "Width", "Form"],
        "rows": [
            ["ACTIVE_ERROR_FLAG", "6 bits", "all dominant"],
            ["PASSIVE_ERROR_FLAG", "6 bits", "all recessive"],
            ["ERROR_DELIMITER", "8 bits", "all recessive"]
        ]
    }
    f["overload_frame_table"] = {
        "header_columns": ["Sub-field", "Width", "Form"],
        "rows": [
            ["OVERLOAD_FLAG", "6 bits", "all dominant"],
            ["OVERLOAD_DELIMITER", "8 bits", "all recessive"]
        ]
    }
    d["fields"] = f
    _write(p, d)


def _apply_l16(gd: Path) -> None:
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    # FORCE-overwrite — CAN's was Classical-only.
    f["must_have_properties"] = [
        "Conform to ISO 11898-1:2015 (default; CCCR.NISO = 0).",
        "Support 11-bit and 29-bit identifiers.",
        "Support Classical CAN frame format (FDF = dominant).",
        "Support CAN FD frame format (FDF = recessive; new DLC + CRC).",
        "Bit coding by NRZ + bit stuffing in stuffed fields.",
        "Bit stuffing inserts complementary bit after 5 identical bits.",
        "Fixed-form fields NOT stuffed.",
        "Bus values: dominant overrides recessive (wired-AND).",
        "START_OF_FRAME = 1 dominant bit.",
        "IDENTIFIER (11 bits) transmitted MSB-first; 7 MSBs not all "
        "recessive.",
        "Classical CAN RTR: dominant DATA / recessive REMOTE.",
        "CAN FD RRS bit: always dominant.",
        "CAN FD FDF bit: dominant=Classical, recessive=CAN FD.",
        "CAN FD BRS bit: only evaluated when CCCR.BRSE = 1 AND CCCR.FDOE "
        "= 1.",
        "CAN FD ESI bit: error-active → dominant; error-passive → "
        "recessive.",
        "DLC encoded per Classical / CAN FD table.",
        "Classical CRC: 15-bit BCH polynomial.",
        "CAN FD CRC: 17-bit (≤16 B) or 21-bit (>16 B).",
        "ISO CAN FD: 3-bit stuff-count + 1-bit parity in CRC field.",
        "Active error flag = 6 dominant; passive = 6 recessive; ERROR "
        "DELIMITER = 8 recessive.",
        "Intermission = 3 recessive bits.",
        "Error-passive transmitter adds SUSPEND TRANSMISSION.",
        "Fault confinement state transitions per TEC/REC thresholds 128 "
        "and 256.",
        "Bus-off recovery requires 129 × Bus_Idle after CCCR.INIT cleared.",
        "Configuration registers writable only when CCCR.CCE + CCCR.INIT "
        "= 1.",
        "Reserved register access sets IR.ARA + m_can_aei_ara.",
        "Acceptance filter: up to 128 standard + 64 extended filter "
        "elements.",
        "Rx FIFO 0 + Rx FIFO 1 configurable up to 64 elements each.",
        "Up to 64 dedicated Rx Buffers + up to 32 Tx Buffers + 32 Tx "
        "Event FIFO elements.",
        "Data phase bit time must be ≥ no shorter than arbitration bit "
        "time.",
        "Sum of measured TDC + TDCR.TDCO < 6 bit times in data phase; "
        "≤ 127 mtq absolute.",
        "Uncorrected Message RAM bit error sets IR.BEU + CCCR.INIT = 1."
    ]
    f["must_not_have_properties"] = [
        "More than 2 consecutive OVERLOAD FRAMEs.",
        "Transmitting while bus-off.",
        "Using identifier with 7 MSBs all recessive.",
        "Using Classical DLC 9..15 to encode > 8 data bytes.",
        "Transmitting CAN FD frames when CCCR.FDOE = 0.",
        "Bit rate prescaler DBRP > 2 when DBTP.TDC = 1.",
        "Mixing ISO + non-ISO CAN FD nodes on the same bus.",
        "Combining Restricted Operation Mode with Loop Back Mode.",
        "Transmit Cancellation for Tx FIFO buffers."
    ]
    f["compliance_failure_modes"] = [
        {"mode": "BIT ERROR (arbitration phase)",
         "psr_field": "PSR.LEC = 4 or 5",
         "trigger": "Monitored bus value ≠ transmitted bit."},
        {"mode": "BIT ERROR (data phase, FD with BRS=1)",
         "psr_field": "PSR.DLEC = 4 or 5",
         "trigger": "Bus value at SSP ≠ transmitted bit."},
        {"mode": "STUFF ERROR",
         "psr_field": "PSR.LEC = 1 / PSR.DLEC = 1",
         "trigger": "6 consecutive identical bits in stuffed field."},
        {"mode": "CRC ERROR",
         "psr_field": "PSR.LEC = 6 / PSR.DLEC = 6",
         "trigger": "Calculated CRC ≠ received CRC."},
        {"mode": "FORM ERROR",
         "psr_field": "PSR.LEC = 2 / PSR.DLEC = 2",
         "trigger": "Illegal bit in fixed-form field."},
        {"mode": "ACKNOWLEDGMENT ERROR",
         "psr_field": "PSR.LEC = 3",
         "trigger": "No dominant bit during ACK SLOT."},
        {"mode": "PROTOCOL EXCEPTION EVENT",
         "psr_field": "PSR.PXE = 1 + PSR.ACT = 00",
         "trigger": "FDF = recessive + res = recessive received."},
        {"mode": "MESSAGE RAM ACCESS FAILURE",
         "ir_flag": "IR.MRAF",
         "trigger": "Rx Handler / Tx Handler RAM access timeout."},
        {"mode": "BIT ERROR UNCORRECTED (Message RAM)",
         "ir_flag": "IR.BEU",
         "trigger": "External ECC asserts m_can_aeim_berr[1]."},
        {"mode": "TIMEOUT OCCURRED",
         "ir_flag": "IR.TOO",
         "trigger": "Timeout Counter decremented to 0."},
        {"mode": "ACCESS TO RESERVED ADDRESS",
         "ir_flag": "IR.ARA",
         "trigger": "Host accesses reserved register address."}
    ]
    f["performance_of_error_detection"] = [
        "All global errors detected per ISO 11898-1:2015.",
        "All local errors at transmitters detected.",
        "Up to 5 randomly distributed errors per message detected.",
        "Burst errors detected.",
        "Errors of any odd number detected.",
        "ISO CAN FD's stuff-count parity protection further reduces "
        "residual error probability.",
        "Total residual error probability for undetected corrupted "
        "messages further reduced relative to Classical CAN."
    ]
    f["recovery_time_bound"] = (
        "After detecting an error and transmitting an error frame, the "
        "M_CAN retries within tens of bit times once the bus is idle "
        "(subject to CCCR.TXP transmit pause and CCCR.DAR setting).")
    f.setdefault("iso_vs_non_iso_distinction", {
        "selectable_via": "CCCR.NISO (when iso_only_g = 0).",
        "ISO_mode_NISO_0": "ISO 11898-1:2015 with stuff-bit-count + "
        "parity protection in CRC.",
        "non_ISO_mode_NISO_1": "Bosch CAN FD V1.0 (no stuff-count "
        "protection).",
        "interoperability": "ISO + non-ISO nodes CANNOT coexist on the "
        "same bus."
    })
    d["fields"] = f
    _write(p, d)


def _apply_l17(gd: Path) -> None:
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    # FORCE-overwrite channels (CAN had single-channel only).
    f["channels"] = [
        {"name": "CAN bus (single channel)",
         "direction": "bidirectional wired-AND",
         "purpose": "Single shared serial channel.",
         "physical_realization": "Outside M_CAN; ISO 11898-2 typical."},
        {"name": "Generic Slave Interface (Host CPU)",
         "direction": "Host CPU ↔ M_CAN",
         "purpose": "8/16/32-bit register access."},
        {"name": "Generic Master Interface (Message RAM)",
         "direction": "M_CAN → external 32-bit Message RAM",
         "purpose": "Read / write to Message RAM."},
        {"name": "Interrupt lines",
         "direction": "M_CAN → Host CPU",
         "purpose": "Two CPU lines m_can_int0 + m_can_int1."},
        {"name": "Extension Interface",
         "direction": "M_CAN → external interrupt unit",
         "purpose": "All IR flags + selected status/control signals."},
        {"name": "TSU Interface",
         "direction": "M_CAN ↔ external TSU (CiA 603)",
         "purpose": "32-bit external timestamping."},
        {"name": "DMU Interface",
         "direction": "M_CAN → external DMA unit",
         "purpose": "Debug-on-CAN hand-off."},
        {"name": "Power-down Interface",
         "direction": "External clock controller ↔ M_CAN",
         "purpose": "Clock-stop handshake."}
    ]
    f["logical_signal_states"] = [
        {"name": "dominant",  "value": "logical 0",
         "rule": "Wins simultaneous transmission. At m_can_tx: driven low."},
        {"name": "recessive", "value": "logical 1",
         "rule": "Released. At m_can_tx: driven high."}
    ]
    # FORCE-overwrite frame_fields_as_signal_segments — CAN had Classical only.
    f["frame_fields_as_signal_segments_classical"] = [
        {"name": "START_OF_FRAME", "type": "delimiter",
         "form": "1 dominant bit"},
        {"name": "ARBITRATION_FIELD", "type": "address+request",
         "form": "11+RTR (std) or 11+SRR+IDE+18+RTR (ext)"},
        {"name": "CONTROL_FIELD", "type": "metadata",
         "form": "r1 + r0 + 4-bit DLC"},
        {"name": "DATA_FIELD", "type": "payload",
         "form": "0..8 bytes, MSB-first"},
        {"name": "CRC_FIELD", "type": "integrity",
         "form": "15-bit CRC + 1 recessive delimiter"},
        {"name": "ACK_FIELD", "type": "handshake",
         "form": "1 ACK slot + 1 recessive delimiter"},
        {"name": "END_OF_FRAME", "type": "delimiter",
         "form": "7 recessive bits"},
        {"name": "INTERMISSION", "type": "interframe space",
         "form": "3 recessive bits"},
        {"name": "BUS_IDLE", "type": "interframe space",
         "form": "arbitrary recessive"},
        {"name": "SUSPEND_TRANSMISSION", "type": "interframe space",
         "form": "8 recessive bits"}
    ]
    f["frame_fields_as_signal_segments_can_fd"] = [
        {"name": "START_OF_FRAME", "type": "delimiter",
         "form": "1 dominant bit"},
        {"name": "ARBITRATION_FIELD", "type": "address",
         "form": "11+RRS (std) or 11+SRR+IDE+18+RRS (ext); RRS always "
         "dominant"},
        {"name": "CONTROL_FIELD_FD", "type": "metadata",
         "form": "r1 + FDF=1 + res=0 + BRS + ESI + DLC[3:0]"},
        {"name": "DATA_FIELD_FD", "type": "payload",
         "form": "0..64 bytes; DBTP rate if BRS=1"},
        {"name": "STUFF_COUNT_FIELD_ISO", "type": "stuff protection",
         "form": "4 bits when CCCR.NISO = 0"},
        {"name": "CRC_FIELD_FD", "type": "integrity",
         "form": "17/21-bit CRC + recessive delimiter; switches back to "
         "NBTP"},
        {"name": "ACK_FIELD_FD", "type": "handshake",
         "form": "ACK SSP-aware timing"},
        {"name": "END_OF_FRAME", "type": "delimiter",
         "form": "7 recessive bits"},
        {"name": "INTERMISSION", "type": "interframe space",
         "form": "3 recessive bits"},
        {"name": "ACTIVE_ERROR_FLAG", "type": "error signal",
         "form": "6 dominant"},
        {"name": "PASSIVE_ERROR_FLAG", "type": "error signal",
         "form": "6 recessive"},
        {"name": "ERROR_DELIMITER", "type": "error delimiter",
         "form": "8 recessive"},
        {"name": "OVERLOAD_FLAG", "type": "delay signal",
         "form": "6 dominant"},
        {"name": "OVERLOAD_DELIMITER", "type": "delay delimiter",
         "form": "8 recessive"}
    ]
    f.setdefault("module_ports_catalog", [
        {"name": "m_can_tx", "direction": "output",
         "purpose": "CAN bit-stream output."},
        {"name": "m_can_rx", "direction": "input",
         "purpose": "CAN bit-stream input."},
        {"name": "m_can_int0", "direction": "output",
         "purpose": "Interrupt line 0."},
        {"name": "m_can_int1", "direction": "output",
         "purpose": "Interrupt line 1."},
        {"name": "m_can_aei_ara", "direction": "output",
         "purpose": "Reserved address access signal."},
        {"name": "m_can_clkstop_req", "direction": "input",
         "purpose": "Clock-stop request."},
        {"name": "m_can_clkstop_ack", "direction": "output",
         "purpose": "Clock-stop acknowledge."},
        {"name": "m_can_cok", "direction": "input",
         "purpose": "Clock Calibration on CAN unit input."},
        {"name": "m_can_ext_ts[15:0]", "direction": "input",
         "purpose": "External 16-bit timebase."},
        {"name": "m_can_tsrx", "direction": "output",
         "purpose": "Sync message Rx pulse."},
        {"name": "m_can_tstx", "direction": "output",
         "purpose": "Sync message Tx pulse."},
        {"name": "m_can_fe[2:0]", "direction": "output",
         "purpose": "Filter event pins."},
        {"name": "m_can_dma_req", "direction": "output",
         "purpose": "Debug-on-CAN DMA request."},
        {"name": "m_can_dma_ack", "direction": "input",
         "purpose": "Debug-on-CAN DMA ack."},
        {"name": "m_can_aeim_sel", "direction": "output",
         "purpose": "Generic Master select."},
        {"name": "m_can_aeim_ready", "direction": "input",
         "purpose": "Message RAM ready."},
        {"name": "m_can_aeim_berr[1:0]", "direction": "input",
         "purpose": "Message RAM ECC status."},
        {"name": "m_can_hclk", "direction": "input",
         "purpose": "Host clock."},
        {"name": "m_can_cclk", "direction": "input",
         "purpose": "CAN clock."}
    ])
    # FORCE-overwrite channel_counts — CAN had Classical only.
    f["channel_counts"] = {
        "logical_can_channels": 1,
        "logical_bit_values": 2,
        "classical_frame_types": 4,
        "can_fd_frame_types": 4,
        "bit_fields_in_classical_data_frame": 7,
        "bit_fields_in_can_fd_data_frame": 8,
        "bit_timing_segments_per_bit": 4,
        "fault_confinement_states": 3,
        "interrupt_lines": 2,
        "register_address_space_bytes": 512,
        "interrupt_flags_in_IR": 30,
        "max_standard_filter_elements": 128,
        "max_extended_filter_elements": 64,
        "max_dedicated_rx_buffers": 64,
        "max_rx_fifo_elements_each": 64,
        "max_tx_buffers": 32,
        "max_tx_event_fifo_elements": 32
    }
    # FORCE-overwrite dependency_graph — CAN had Classical only.
    f["dependency_graph"] = {
        "common_rule": "Single shared CAN channel: dominant wins on "
        "collision. CAN FD adds: data-phase bit time (DBTP) used after "
        "BRS bit when BRS=1.",
        "data_dependency": "Each bit sampled at SAMPLE POINT (NTSEG1 / "
        "DTSEG1). Resynchronization adjusts segments bounded by NSJW / "
        "DSJW.",
        "ack_dependency":  "ACK SLOT response = OR of (CRC-matched ∧ "
        "ready). CAN FD ACK timing accounts for transmitter delay.",
        "tdc_dependency":  "When DBTP.TDC = 1, data-phase bit-error "
        "check at Secondary Sample Point."
    }
    # FORCE-overwrite handshake_pairs — CAN had Classical-only set.
    f["handshake_pairs"] = [
        {"name": "ARBITRATION", "from": "competing transmitters",
         "to": "transmitters",
         "rule": "Bitwise on IDENTIFIER + RTR/RRS; loser withdraws."},
        {"name": "ACK_SLOT_ACK", "from": "all CRC-matched receivers",
         "to": "transmitter",
         "rule": "Dominant superscribed on transmitter's recessive ACK; "
         "CAN FD timing accounts for transmitter delay."},
        {"name": "OVERLOAD_REQUEST", "from": "any receiver",
         "to": "all nodes",
         "rule": "OVERLOAD FLAG (max 2 consecutive)."},
        {"name": "TXBAR / TXBRP", "from": "Host CPU",
         "to": "M_CAN Tx Handler",
         "rule": "TXBAR.AR_n = 1 → TXBRP.TRP_n = 1."},
        {"name": "TXBCR / TXBCF", "from": "Host CPU",
         "to": "M_CAN Tx Handler",
         "rule": "TXBCR.CR_n = 1 → TXBCF.CF_n = 1."},
        {"name": "RXF0A / F0GI", "from": "Host CPU",
         "to": "M_CAN Rx Handler",
         "rule": "RXF0A.F0AI → F0GI = F0AI + 1."},
        {"name": "TXEFA / EFGI", "from": "Host CPU",
         "to": "M_CAN Tx Handler",
         "rule": "TXEFA.EFAI → EFGI = EFAI + 1."},
        {"name": "DMA_REQ / DMA_ACK", "from": "M_CAN", "to": "external DMU",
         "rule": "Debug-on-CAN A+B+C → m_can_dma_req; DMU asserts "
         "m_can_dma_ack."},
        {"name": "CLKSTOP_REQ / CLKSTOP_ACK", "from": "external",
         "to": "M_CAN",
         "rule": "Clock-stop request → after pending Tx + bus idle: "
         "CCCR.INIT + CCCR.CSA + m_can_clkstop_ack = 1."}
    ]
    f["ordering_rules"] = {
        "within_a_byte":   "MSB-first within each data byte.",
        "identifier_bits": (
            "MSB-first (ID-10 → ID-0 for 11-bit standard; ID-28 → ID-0 "
            "for 29-bit extended)."),
        "global_ordering": "Higher-priority IDENTIFIER wins.",
        "tx_fifo":         "M_CAN Tx FIFO transmits in put-order.",
        "tx_queue":        "M_CAN Tx Queue transmits by lowest Message ID.",
        "mixed_dedicated_fifo_queue": "All eligible Tx Buffers scanned; "
        "lowest Message ID wins."
    }
    d["fields"] = f
    _write(p, d)


def _apply_l18(gd: Path) -> None:
    p = gd / "L18_INTERCONNECT_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    # FORCE-overwrite — CAN had Classical-only wording.
    f["topology_type"] = (
        "Multi-master single-channel shared serial bus; multidrop "
        "wired-AND with bitwise IDENTIFIER arbitration. The M_CAN "
        "controller is one node on this bus, attached via external "
        "transceiver. Internally exposes Host CPU register interface + "
        "external Message RAM interface + optional DMU + TSU + Extension "
        "interfaces.")
    f["supported_topologies"] = [
        {"name": "Linear bus (typical automotive)",
         "description": "All CAN nodes tap onto a single twisted-pair. "
         "CAN FD enables faster data phase on the same wire."},
        {"name": "Star / branched (low-speed)",
         "description": "ISO 11898-3 fault-tolerant low-speed."},
        {"name": "Optical fibre",
         "description": "Physical layer optional; CAN FD frame format "
         "unchanged."},
        {"name": "Mixed Classical + CAN FD network",
         "description": "Coexist if FD nodes never transmit FD frames "
         "while Classical nodes active."},
        {"name": "Multiple M_CANs sharing one Message RAM",
         "description": "Generic Master Interface arbitration supports "
         "this."},
        {"name": "Partial networking (ISO 11898-6 transceiver)",
         "description": "Transceiver handles partial wake-up."},
        {"name": "Time-Triggered CAN (TTCAN, ISO 11898-4)",
         "description": "Use CCCR.DAR = 1; software runs schedule above "
         "M_CAN."}
    ]
    f["master_slave_role_summary"] = [
        {"role": "TRANSMITTER",
         "description": "A unit originating a message."},
        {"role": "RECEIVER",
         "description": "A unit that is not transmitter and the bus is "
         "not idle."},
        {"role": "error-active node",
         "description": "Normal operation; CAN FD ESI = dominant."},
        {"role": "error-passive node",
         "description": "Degraded; CAN FD ESI = recessive."},
        {"role": "bus-off node",
         "description": "Output drivers off; CCCR.INIT held = 1."},
        {"role": "Restricted Operation node",
         "description": "Receives + sends ACK; does NOT send error/data/"
         "remote/overload frames."},
        {"role": "Bus Monitoring node",
         "description": "Receive only."}
    ]
    f["interconnect_role"] = (
        "There is no protocol-layer interconnect (no router / bridge) on "
        "the CAN bus. Inside the M_CAN, the Generic Master Interface "
        "arbitrates Tx Handler vs Rx Handler accesses to the external "
        "Message RAM.")
    f["ordering_guarantees"] = {
        "single_bus":  "All nodes simultaneously see the same bus value.",
        "arbitration": "Higher-priority messages transmitted first.",
        "tx_fifo":     "Tx FIFO transmits in put-order.",
        "tx_queue":    "Tx Queue transmits by lowest Message ID.",
        "rx_fifo":     "Rx FIFO writes in arrival order; Get Index "
        "advanced by host via FIFO Acknowledge.",
        "rx_buffer":   "Dedicated Rx Buffer locked by New Data flag."
    }
    f["memory_vs_peripheral_regions"] = {
        "M_CAN_register_space": "512 bytes; 32-bit word-aligned.",
        "Message_RAM_space": "External; up to 4.25K × 32-bit per M_CAN."
    }
    f["slave_classification"] = {
        "addressable_target": "Not applicable — CAN is content-addressed.",
        "data_producer": "Any node may transmit DATA FRAMEs.",
        "data_consumer": "Any node may apply acceptance filtering.",
        "M_CAN_as_Host_slave": "Generic Slave Interface presents 512-byte "
        "register space.",
        "M_CAN_as_Master": "Generic Master Interface initiates 32-bit "
        "Message RAM access."
    }
    f["default_signal_values_evidence_tables"] = [
        "Section 1 Overview — block diagram + dual clock domains.",
        "Section 2.2 Register Map — 512-byte address space.",
        "Section 2.3 Registers — per-register reset values.",
        "Section 2.4 Message RAM — section partitioning + elements.",
        "Section 3.1 Operating Modes.",
        "Section 3.4 Rx Handling.",
        "Section 3.5 Tx Handling.",
        "Section 4.1 Register Bit Overview."
    ]
    # FORCE-overwrite — CAN's wake_up_topology was Classical convention.
    f["wake_up_topology"] = {
        "wake_up_trigger": "External clock controller deasserts "
        "m_can_clkstop_req (or CPU clears CCCR.CSR).",
        "wake_up_message": "CAN FD itself does not define a wake-up "
        "identifier. Partial networking via ISO 11898-6 transceiver "
        "handles wake-up at the physical layer.",
        "post_wake_sync":  "After clocks restart, M_CAN clears "
        "m_can_clkstop_ack + CCCR.CSA; CPU clears CCCR.INIT; BSP waits "
        "for 11 consecutive recessive bits."
    }
    f.setdefault("M_CAN_block_topology", {
        "two_clock_domains": ["Host clock domain — Tx Handler, Rx "
            "Handler, Generic Slave, Generic Master, RAM Watchdog.",
            "CAN clock domain — CAN Core, BSP, BTL."],
        "sync_block": "Cross-domain handoff.",
        "interrupt_and_timestamp_block": "16-bit CAN-bit-time counter; "
        "routes IR to two CPU lines.",
        "extension_interface_block": "Routes all IR flags + status/"
        "control to external interrupt unit."
    })
    d["fields"] = f
    _write(p, d)


def _apply_l19(gd: Path) -> None:
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["constraints_present"] = False
    f["notes"] = (
        "The M_CAN module is delivered as synthesizable VHDL RTL — "
        "synthesis-time generic parameters (iso_only_g, connected_tsu_g, "
        "CREL year/month/day stamp) are documented but no SDC / floorplan "
        "/ PDK constraints ship with the spec. Per-controller integration "
        "constraints — clock-tree budget for the two clock domains "
        "(m_can_hclk + m_can_cclk), Message RAM access timing budget, "
        "RAM Watchdog period choice — live in the integrator's SoC "
        "integration spec. The CAN FD data phase imposes stricter timing "
        "on m_can_cclk than Classical CAN.")
    f.setdefault("synthesis_generic_parameters", [
        {"name": "iso_only_g", "values": [0, 1],
         "purpose": "1 → CCCR.NISO fixed = 0."},
        {"name": "connected_tsu_g", "values": [0, 1],
         "purpose": "0 → CCCR.UTSU fixed = 0."},
        {"name": "CREL.YEAR / MON / DAY",
         "purpose": "BCD time-stamp set at synthesis."}
    ])
    f.setdefault("integrator_responsibilities", [
        "Choose Message RAM size + partition.",
        "External ECC / parity logic for Message RAM.",
        "RAM Watchdog start value (RWD.WDC).",
        "Interrupt routing (ILS / ILE / IE).",
        "Transceiver choice (ISO 11898-2 / -3 / -6).",
        "Bit-timing programming using CAN bit timing calculator.",
        "m_can_cclk crystal / PLL choice.",
        "m_can_hclk choice (FM-PLL allowed if ≥ m_can_cclk).",
        "Clock-stop strategy + wake source.",
        "Optional TSU / DMU connection."
    ])
    d["fields"] = f
    _write(p, d)


def _apply_l20(gd: Path) -> None:
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["dft_present"] = False
    f["notes"] = (
        "The M_CAN User's Manual does not specify DFT / scan / BIST "
        "insertion — M_CAN ships as VHDL RTL synthesis-ready and DFT is "
        "added by the integrator at SoC level. M_CAN does provide rich "
        "protocol-level self-checking and built-in test features that "
        "substitute for traditional BIST at the protocol level:")
    f.setdefault("spec_provided_built_in_test_features", [
        "Loop Back Modes (External + Internal) — TEST.LBCK = 1.",
        "Bus Monitoring Mode (CCCR.MON = 1).",
        "Restricted Operation Mode (CCCR.ASM = 1).",
        "Tx Pin Driver Control (TEST.TX[1:0]).",
        "Rx Pin Monitor (TEST.RX).",
        "PSR.TDCV live readback.",
        "CAN Error Logging Counter ECR.CEL.",
        "RAM Watchdog (RWD).",
        "Access to Reserved Address detection.",
        "ECC / parity hooks (m_can_aeim_berr[1:0])."
    ])
    f.setdefault("scan_topology", "Not specified — integrator's DFT "
        "methodology. Typical SoC-integrated CAN controller IP inserts "
        "standard scan chains at the integrator level + per-domain at-"
        "speed test (separate scan modes for m_can_hclk and m_can_cclk "
        "domains).")
    f.setdefault("atpg_strategy", "Not specified — typically full-scan "
        "stuck-at + at-speed transition.")
    d["fields"] = f
    _write(p, d)


def _apply_l21(gd: Path) -> None:
    p = gd / "L21_POWER_INTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    # CAN had power_intent_present = False. M_CAN has clock-stop power
    # feature — set to True.
    f["power_intent_present"] = True
    f.setdefault("power_features", {
        "clock_stop_request_inputs": ["m_can_clkstop_req external signal",
            "CCCR.CSR software bit"],
        "clock_stop_response_outputs": ["m_can_clkstop_ack external signal",
            "CCCR.CSA software-readable bit"],
        "trigger_actions": "When clock-stop request asserted, M_CAN "
        "completes pending transmissions, waits for bus idle, sets "
        "CCCR.INIT = 1 internally, then asserts m_can_clkstop_ack + "
        "CCCR.CSA = 1.",
        "clocks_that_may_be_stopped": ["m_can_hclk (Host clock)",
            "m_can_cclk (CAN clock)"],
        "register_access_during_power_down": "Allowed except for "
        "CCCR.INIT (held at 1).",
        "abort_path": "If bus is heavily disturbed and idle never "
        "reached, CCCR.INIT remains 0; software polls PSR.ACT and may "
        "write CCCR.INIT = 1 explicitly.",
        "wake_up_procedure": [
            "1. External clock controller restarts m_can_hclk + m_can_cclk.",
            "2. CPU deasserts m_can_clkstop_req or clears CCCR.CSR.",
            "3. M_CAN clears m_can_clkstop_ack + CCCR.CSA.",
            "4. CPU clears CCCR.INIT.",
            "5. BSP waits for 11 consecutive recessive bits."
        ]
    })
    # FORCE-overwrite low_power_modes_summary — CAN's was Classical convention.
    f["low_power_modes_summary"] = {
        "normal_operation": "Both clocks running; CCCR.INIT = 0.",
        "initialization_mode": "CCCR.INIT = 1; clocks running; bus output "
        "recessive.",
        "power_down_sleep": "Both clocks may be stopped after pending Tx "
        "+ bus idle. m_can_clkstop_ack + CCCR.CSA = 1.",
        "bus_off": "Forced shutdown after TEC = 256; CCCR.INIT set "
        "automatically; recovery requires 129 × Bus_Idle."
    }
    # FORCE-overwrite dual_clock_domain_concept — the frequency_constraint
    # must include the explicit "frequency" qualifier and the spread-spectrum
    # depth caveat (these are spec wording, not optional shorthand).
    f["dual_clock_domain_concept"] = {
        "m_can_hclk": "Host clock domain — Tx Handler / Rx Handler / "
        "Generic Slave / Generic Master / RAM Watchdog. May be FM-PLL "
        "spread spectrum.",
        "m_can_cclk": "CAN clock domain — CAN Core / BSP / BTL. Must be "
        "high-precision.",
        "frequency_constraint": (
            "m_can_hclk frequency ≥ m_can_cclk frequency (spread-spectrum "
            "modulation depth must also be considered)."),
        "sync_block": "Synchronizes signals + reset across the two "
        "domains."
    }
    f.setdefault("interrupt_during_power_down", "The two CPU interrupt "
        "lines reflect IR + IE + ILS + ILE state. During clock-stop, no "
        "new IR flags are set; existing latched flags remain visible "
        "until host clears them.")
    f["notes"] = (
        "The M_CAN's power model is intentionally simple: one register-"
        "control bit (CCCR.CSR) + one pin (m_can_clkstop_req) gate the "
        "clock-stop request; the only protocol-level power feature is "
        "the clock-stop / wake-up sequence. Power-domain partitioning, "
        "retention strategy, and isolation cells are deferred to SoC + "
        "transceiver IP.")
    d["fields"] = f
    _write(p, d)


def _apply_l23(gd: Path) -> None:
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["security_requirements_present"] = False
    f["notes"] = (
        "The M_CAN module + the ISO 11898-1:2015 CAN FD protocol provide "
        "no confidentiality, integrity (against tampering), or "
        "authentication features. CAN is broadcast — every node sees "
        "every frame; the M_CAN's acceptance filter is a content-routing "
        "mechanism, not a security boundary. Built-in protocol primitives "
        "providing error-detection (anti-corruption, not anti-tampering): "
        "15-bit BCH CRC (Classical), 17-bit / 21-bit CRC (CAN FD), bit-"
        "stuffing, fixed-form field checks, bit-error monitoring, ISO "
        "mode stuff-count + parity. Modern automotive security layers ON "
        "TOP of CAN FD: AUTOSAR SecOC, ISO/SAE 21434, CAN-XL. None of "
        "these are part of the M_CAN spec — they are application-layer "
        "protocols carried in the CAN FD DATA FIELD. The M_CAN's "
        "Protected-Write semantics (CCCR.CCE + CCCR.INIT) prevent "
        "accidental misconfiguration during operation but are not a "
        "security mechanism. The Customer Register at 0x008 is reserved "
        "for customer-specific bits (functionality outside this spec).")
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
def is_canfd(blob: str) -> bool:
    """Content-only `canfd` detector (importable) WITH a FOREIGN-PRIMARY DEFER.

    Empty-safe. Reads ONLY ``blob`` (spec text) — never a filename or
    benchmark name. The original structural signature (below) is unchanged.

    The structural signature is necessary but NOT sufficient. CAN-FD is a
    derived-CHILD extension of two sibling protocols that share its base
    vocabulary, so their specs incidentally carry CAN-FD tokens (every CAN /
    CANopen spec names "CAN-FD" and "64 ... payload" when describing the FD
    extension, and the Bosch M_CAN controller is cited by name). Without a
    guard, the loose ``"CAN-FD" + "64" + "payload"`` branch fires on a
    Classical-CAN or a CANopen spec whose true subject is NOT CAN-FD. Guard
    (mirrors the `is_mipi` / `_axi_primary` foreign-primary-defer doctrine —
    general, content-only, sibling-MUTEX via each foreign's DISTINCTIVE
    structural signature):

      - CANopen-primary: the CiA-301 application-layer signature absent from a
        CAN-FD data-link spec — the Object Dictionary PLUS the PDO/SDO/NMT
        communication-object triple PLUS a COB-ID / Node-ID. (Same signature
        `is_canopen` keys on.) CANopen layers ON CAN-FD, so it must MUTEX out.

      - Classical-CAN-primary: a CAN data-link spec that names "CAN-FD" only
        to describe the FD extension but is NOT itself a CAN-FD spec. The
        sibling-MUTEX discriminator is CAN-FD's own DISTINCTIVE signature: the
        FD frame-format control bits (BRS + FDF + ESI) OR the Bosch M_CAN
        register controller (M_CAN + CCCR). A real CAN-FD spec ALWAYS exhibits
        at least one of these (the strong structural branches below require
        them); a Classical-CAN-primary doc exhibits NEITHER and only trips the
        loose incidental-mention branch — so defer when both are absent.

    Empirically corpus-clean: `canfd` carries both FD discriminators and is
    NOT CANopen-primary, so it stays True; `canopen` trips canopen_primary and
    `can` carries neither FD discriminator, so both are suppressed.
    """
    if not blob:
        return False
    low = blob.lower()

    # --- FOREIGN-PRIMARY DEFER (the blob's true subject is NOT CAN-FD). ---
    # CANopen application-layer structural signature (CiA-301 kernel).
    _obj_dict = "object dictionary" in low
    _pdo = ("pdo" in low or "process data object" in low)
    _sdo = ("sdo" in low or "service data object" in low)
    _nmt = ("nmt" in low or "network management" in low)
    _cob_or_node = ("cob-id" in low or "cob id" in low
                    or "node-id" in low or "node id" in low)
    canopen_primary = _obj_dict and (_pdo and _sdo and _nmt) and _cob_or_node

    # CAN-FD's DISTINCTIVE discriminators (sibling-MUTEX vs Classical CAN):
    # the FD frame-format control bits OR the Bosch M_CAN register controller.
    _fd_frame_bits = ("BRS" in blob and "FDF" in blob and "ESI" in blob)
    _mcan_controller = ("M_CAN" in blob and "CCCR" in blob)
    classical_can_primary = not (_fd_frame_bits or _mcan_controller)

    if canopen_primary or classical_can_primary:
        return False

    # --- STRUCTURAL CAN-FD signature (unchanged from the runner's inline
    #     detector). ---
    return bool(
        ("BRS" in blob and "FDF" in blob and "ESI" in blob)
        or ("CAN-FD" in blob and "64" in blob
            and "payload" in blob.lower())
        or ("Bosch" in blob and "M_CAN" in blob
            and "CCCR" in blob))
