"""CAN-class protocol synth helper.

v0.1.81 — ic_class-gated overlay for `serial_peripheral_protocol` specs
that exhibit the CAN structural signature (DATA FRAME / REMOTE FRAME /
ERROR FRAME / OVERLOAD FRAME terminology, OR dominant/recessive bus
values, OR ARBITRATION FIELD + RTR + IDENTIFIER terminology). Applies
Bosch CAN 2.0-canonical content to L1-L18 + L21.

Doctrine: structural-keyword detection IS general within an ic_class
(mirrors AMBA-AXI / SPI / I2C / UART synth approach). Any CAN-family
variant (CAN 2.0 Part A, Part B, CAN FD, time-triggered TTCAN, ISO
11898-1 derivatives) exhibits the same signature.

Public entry: `apply_can_synth(generated_docs_dir, is_can, can_ic_name)`.
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


def apply_can_synth(generated_docs_dir: Path, is_can: bool,
                    can_ic_name: Optional[str]) -> None:
    """Apply CAN-specific synth when the structural signature matched."""
    if not is_can:
        return
    gd = generated_docs_dir

    # Force ic_name across the 14 main L docs.
    if can_ic_name is not None:
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
                d["ic_name"] = can_ic_name
                _write(q, d)

    # L1
    p = gd / "L1_DATASHEET.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("document_title", "CAN Specification Version 2.0")
        d.setdefault("version", "2.0")
        d.setdefault("manufacturer", "Robert Bosch GmbH")
        d.setdefault("revised_date", "September 1991")
        d.setdefault("copyright", "© 1991 Robert Bosch GmbH, Postfach 50, D-7000 Stuttgart 1")
        d.setdefault("document_layout", [
            "Part A — CAN message format as defined in CAN Specification 1.2 (11-bit identifier, standard format).",
            "Part B — both standard (11-bit) and extended (29-bit) message formats.",
        ])
        d.setdefault("key_features", [
            "Prioritization of messages by IDENTIFIER (lower IDENTIFIER value = higher priority).",
            "Guarantee of latency times.",
            "Configuration flexibility — nodes can be added without changing other nodes.",
            "Multicast reception with time synchronization.",
            "System wide data consistency — a message is simultaneously accepted by all nodes or by no node.",
            "Multimaster — when bus is free any unit may start transmitting; arbitration by IDENTIFIER.",
            "Error detection and signalling.",
            "Automatic retransmission of corrupted messages once bus is idle again.",
            "Distinction between temporary errors and permanent failures of nodes; autonomous switching off of defect nodes (fault confinement).",
            "Non-Return-to-Zero (NRZ) bit coding with bit stuffing (insert complementary bit after 5 identical consecutive bits).",
            "Bitwise arbitration on IDENTIFIER — no information lost.",
            "Sleep mode / Wake-up — power saving plus dedicated wake-up identifier.",
        ])
        d.setdefault("modes_of_operation", [
            {"name": "error active",   "description": "Normal operation; sends ACTIVE ERROR FLAG on error."},
            {"name": "error passive",  "description": "Sends PASSIVE ERROR FLAG only; must wait before initiating further transmission (SUSPEND TRANSMISSION)."},
            {"name": "bus off",        "description": "Not allowed to influence the bus; output drivers switched off."},
            {"name": "sleep / wake-up","description": "Reduced power consumption with disconnected bus drivers; wake on bus activity or internal condition."},
        ])
        d.setdefault("domain_of_application", [
            "Automotive electronics — engine control units, sensors, anti-skid systems (bit rates up to 1 Mbit/s).",
            "Vehicle body electronics — lamp clusters, electric windows (replacing wiring harness).",
            "Industrial control / distributed real-time control / multiplex wiring.",
        ])
        d.setdefault("layered_structure", [
            {"layer": "Application Layer",       "scope": "Not in this specification."},
            {"layer": "Object Layer",            "scope": "Message filtering; status and message handling."},
            {"layer": "Transfer Layer (kernel)", "scope": "Fault confinement, error detection / signalling, message validation, acknowledgment, arbitration, message framing, bit timing + synchronization."},
            {"layer": "Physical Layer",          "scope": "Signal level + bit representation + transmission medium; NOT defined in this spec — implementation may choose single-wire, differential, optical, etc."},
        ])
        d.setdefault("overview",
            "The Controller Area Network (CAN) is a serial communications protocol which efficiently supports distributed realtime control with a very high level of security. Its domain of application ranges from high speed networks to low cost multiplex wiring. The intention of this specification is to achieve compatibility between any two CAN implementations.")
        d.setdefault("compatibility_note",
            "CAN implementations designed according to Part A of this or previous CAN Specifications, and CAN implementations designed according to Part B, can communicate with each other as long as it is not made use of the extended format.")
        _write(p, d)

    # L2
    p = gd / "L2_FRS.json"
    if p.is_file():
        d = _read(p)
        po = d.setdefault("protocol_overview", {})
        if isinstance(po, dict):
            po.setdefault("type", "Multi-master serial bus with bitwise arbitration and frame-based messaging.")
            po.setdefault("duplex", "half-duplex on a single shared channel")
            po.setdefault("synchronous", False)
            po.setdefault("bus_arbitration", "Bitwise on IDENTIFIER while sending arbitration field; lowest IDENTIFIER value wins.")
            po.setdefault("physical_layer", "Not specified — implementation chooses single-wire+ground, differential pair, optical fibre, etc.")
            po.setdefault("bit_coding", "Non-Return-to-Zero (NRZ) with bit stuffing (insert complementary bit after 5 consecutive identical bits in stuffed fields).")
            po.setdefault("bus_values", "Two complementary logical values: dominant (typically logical 0) and recessive (typically logical 1). Wired-AND: dominant wins.")
            po.setdefault("multimaster", True)
            po.setdefault("multicast", True)
            po.setdefault("addressing", "By message IDENTIFIER (content-addressed) — IDENTIFIER does not name a destination, it names the meaning of the data; receivers apply MESSAGE FILTERING.")
        fr = [
            {"id": "FR-FRAME-01",  "text": "Information is sent in fixed-format messages of different but limited length: DATA FRAME, REMOTE FRAME, ERROR FRAME, OVERLOAD FRAME."},
            {"id": "FR-START-02",  "text": "START OF FRAME is a single dominant bit; marks the beginning of DATA and REMOTE FRAMEs."},
            {"id": "FR-ARB-03",    "text": "Arbitration field = IDENTIFIER (11 bits in standard format; 29 bits in extended) + RTR bit; transmitted MSB-first (ID-10 → ID-0)."},
            {"id": "FR-RTR-04",    "text": "RTR bit dominant = DATA FRAME; recessive = REMOTE FRAME."},
            {"id": "FR-DLC-05",    "text": "DATA LENGTH CODE is 4 bits in CONTROL FIELD; admissible data byte counts are 0..8."},
            {"id": "FR-CRC-06",    "text": "15-bit CRC SEQUENCE using polynomial X^15 + X^14 + X^10 + X^8 + X^7 + X^4 + X^3 + 1, followed by single recessive CRC DELIMITER bit."},
            {"id": "FR-ACK-07",    "text": "ACK FIELD = ACK SLOT (transmitter sends recessive; receivers superscribe with dominant if CRC matched) + recessive ACK DELIMITER."},
            {"id": "FR-EOF-08",    "text": "END OF FRAME is 7 recessive bits."},
            {"id": "FR-STUFF-09",  "text": "Bit stuffing in START_OF_FRAME .. CRC_SEQUENCE: after 5 consecutive identical bits, insert a complementary bit. CRC DELIMITER + ACK + EOF are NOT stuffed."},
            {"id": "FR-BITTIME-10","text": "Nominal Bit Time = 1 / Nominal Bit Rate; divided into SYNC_SEG (1 TQ) + PROP_SEG (1..8 TQ) + PHASE_SEG1 (1..8 TQ) + PHASE_SEG2 (max of PHASE_SEG1 and INFORMATION_PROCESSING_TIME). Total programmable from 8 to 25 TQ."},
            {"id": "FR-SAMP-11",   "text": "SAMPLE POINT is at the end of PHASE_SEG1; INFORMATION PROCESSING TIME ≤ 2 TQ."},
            {"id": "FR-SYNC-12",   "text": "HARD SYNCHRONIZATION on START OF FRAME (recessive → dominant during BUS IDLE). RESYNCHRONIZATION on later edges within the frame, bounded by RESYNCHRONIZATION JUMP WIDTH (1 to min(4, PHASE_SEG1))."},
            {"id": "FR-ERR-13",    "text": "Five error types: BIT ERROR, STUFF ERROR, CRC ERROR, FORM ERROR, ACKNOWLEDGMENT ERROR."},
            {"id": "FR-FAULT-14",  "text": "Fault confinement uses TRANSMIT ERROR COUNT and RECEIVE ERROR COUNT; nodes transition between error-active (<128), error-passive (≥128), and bus-off (TX count ≥256)."},
            {"id": "FR-INTERFRAME-15", "text": "INTERFRAME SPACE = INTERMISSION (3 recessive bits) + BUS IDLE (arbitrary length). Error-passive transmitter adds SUSPEND TRANSMISSION (8 recessive bits)."},
            {"id": "FR-OVERLOAD-16",   "text": "OVERLOAD FRAME = OVERLOAD FLAG (6 dominant bits) + OVERLOAD DELIMITER (8 recessive bits); at most 2 OVERLOAD FRAMEs may be generated to delay the next DATA/REMOTE FRAME."},
            {"id": "FR-VALID-17",      "text": "Message is valid for the transmitter if no error up to end of END OF FRAME; valid for receivers if no error up to the last-but-one bit of END OF FRAME."},
        ]
        if _empty(d.get("functional_requirements")):
            d["functional_requirements"] = fr
        d.setdefault("error_response_conditions", [
            "BIT ERROR — transmitter detects monitored bus value ≠ transmitted value (except recessive→dominant in arbitration or ACK SLOT).",
            "STUFF ERROR — 6th consecutive equal bit detected in a stuffed field.",
            "CRC ERROR — computed CRC ≠ received CRC SEQUENCE.",
            "FORM ERROR — illegal bit(s) in a fixed-form field (CRC DELIMITER, ACK DELIMITER, EOF, INTERMISSION).",
            "ACKNOWLEDGMENT ERROR — transmitter does not monitor a dominant bit during ACK SLOT.",
        ])
        if _empty(d.get("compliance_requirements")):
            d["compliance_requirements"] = [
                "Implementation must conform to either Part A (standard 11-bit) or Part B (standard + extended 29-bit).",
                "7 most significant bits of 11-bit IDENTIFIER (ID-10 .. ID-4) must not be all recessive.",
                "All nodes share the same NOMINAL BIT RATE within a given network.",
                "Bus values: dominant must override recessive on simultaneous transmission (wired-AND).",
                "Programmable prescaler integral values at least from 1 to 32.",
            ]
        d.setdefault("performance_of_error_detection", [
            "All global errors are detected.",
            "All local errors at transmitters are detected.",
            "Up to 5 randomly distributed errors in a message are detected.",
            "Burst errors of length less than 15 in a message are detected.",
            "Errors of any odd number in a message are detected.",
            "Total residual error probability for undetected corrupted messages: less than message_error_rate × 4.7 × 10^-11.",
        ])
        _write(p, d)

    # L3
    p = gd / "L3_CMD_PROTOCOL.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("protocol_type", "Frame-based serial messaging protocol; content-addressed by IDENTIFIER; no opcode/command set.")
        d.setdefault("channels", [
            {"name": "CAN bus", "direction": "bidirectional single-channel wired-AND",
             "description": "Single shared channel (single-wire-plus-ground OR differential pair OR optical) carrying NRZ-coded bits; dominant overrides recessive."},
        ])
        d.setdefault("frame_types", [
            {"name": "DATA FRAME",     "purpose": "Carries data from a transmitter to receivers; bit fields S-O-F + ARBITRATION + CONTROL + DATA + CRC + ACK + EOF."},
            {"name": "REMOTE FRAME",   "purpose": "Requests transmission of the DATA FRAME with same IDENTIFIER; RTR=recessive; no DATA FIELD."},
            {"name": "ERROR FRAME",    "purpose": "Signals an error condition; ERROR FLAG + ERROR DELIMITER."},
            {"name": "OVERLOAD FRAME", "purpose": "Delays the next DATA/REMOTE FRAME; OVERLOAD FLAG + OVERLOAD DELIMITER."},
        ])
        d.setdefault("data_frame_fields", [
            {"field": "START OF FRAME",  "size": "1 bit",   "value": "dominant"},
            {"field": "ARBITRATION FIELD","size": "12 bits","components": "IDENTIFIER (11) + RTR (1)"},
            {"field": "CONTROL FIELD",   "size": "6 bits",  "components": "r1 + r0 (reserved, dominant) + DLC[3:0]"},
            {"field": "DATA FIELD",      "size": "0..64 bits", "components": "0..8 data bytes, each 8 bits MSB-first"},
            {"field": "CRC FIELD",       "size": "16 bits", "components": "CRC SEQUENCE (15 bits) + CRC DELIMITER (1 recessive)"},
            {"field": "ACK FIELD",       "size": "2 bits",  "components": "ACK SLOT (1 transmitter-recessive / receivers-dominant) + ACK DELIMITER (1 recessive)"},
            {"field": "END OF FRAME",    "size": "7 bits",  "value": "all recessive"},
        ])
        d.setdefault("data_length_code_encoding", {
            "header": ["Bytes", "DLC3", "DLC2", "DLC1", "DLC0"],
            "rows": [
                ["0", "d", "d", "d", "d"],
                ["1", "d", "d", "d", "r"],
                ["2", "d", "d", "r", "d"],
                ["3", "d", "d", "r", "r"],
                ["4", "d", "r", "d", "d"],
                ["5", "d", "r", "d", "r"],
                ["6", "d", "r", "r", "d"],
                ["7", "d", "r", "r", "r"],
                ["8", "r", "d", "d", "d"],
            ],
            "note": "Admissible numbers of data bytes: {0, 1, ..., 7, 8}. Other values may not be used.",
        })
        d.setdefault("remote_frame_rules", [
            "RTR bit = recessive (vs dominant for DATA FRAME).",
            "No DATA FIELD.",
            "Same IDENTIFIER as the requested DATA FRAME.",
            "If a DATA FRAME and REMOTE FRAME with same IDENTIFIER start simultaneously, the DATA FRAME prevails.",
        ])
        d.setdefault("valid_ready_handshake_rules", [
            "There is no AMBA-style per-cycle VALID/READY handshake.",
            "Frame-level ACK on bit 1 of ACK FIELD: receivers superscribe transmitter's recessive with dominant if CRC matched.",
            "Bitwise arbitration on the ARBITRATION FIELD: each transmitter compares its driven bit to the monitored bus value; if it drove recessive but bus is dominant, it loses arbitration and withdraws.",
        ])
        d.setdefault("burst_based", False)
        d.setdefault("byte_oriented_within_data_field", True)
        d.setdefault("byte_order_within_data_field", "MSB-first")
        d.setdefault("interframe_space", {
            "intermission":         "3 recessive bits",
            "bus_idle":             "arbitrary length; any unit may start a transmission",
            "suspend_transmission": "8 recessive bits added by an error-passive transmitter after its message",
        })
        _write(p, d)

    # L4 wire-level — no register map
    p = gd / "L4_REGMAP.json"
    if p.is_file():
        d = _read(p)
        d["register_map_present"] = False
        d["notes"] = (
            "CAN 2.0 is a wire-level protocol specification, not a "
            "peripheral block guide. There is no architectural register "
            "map at the protocol layer. Concrete CAN controller IP blocks "
            "(e.g. Bosch C_CAN, M_CAN; Intel/Altera; Microchip MCP2515) "
            "define their own register file (typically: control / status "
            "/ IER / bit-timing / acceptance-filter / mailbox / error-"
            "count registers) at the SoC integration level — covered by "
            "individual block guides, not by Bosch CAN 2.0.")
        _write(p, d)

    # L5 — overwrite signaling
    p = gd / "L5_ADI_SPEC.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("analog_digital_interface_present", False)
        d["signaling_summary"] = (
            "CAN 2.0 is a logical/protocol specification — physical "
            "signal levels are intentionally not defined to allow "
            "implementation flexibility (single-wire+ground, differential "
            "pair, optical fibre, etc.). The bus carries two complementary "
            "logical values 'dominant' and 'recessive' with wired-AND "
            "semantics: dominant prevails on simultaneous transmission. In "
            "typical CMOS CAN PHY implementations (e.g. ISO 11898-2), "
            "dominant ≈ 2.5 V differential and recessive ≈ 0 V differential.")
        _write(p, d)

    # L6 control logic
    p = gd / "L6_CONTROL_LOGIC.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("fault_confinement_states", [
            {"name": "error active",  "description": "Can take part in bus communication; sends ACTIVE ERROR FLAG (6 dominant bits) on error."},
            {"name": "error passive", "description": "Sends PASSIVE ERROR FLAG (6 recessive bits) only; must wait SUSPEND TRANSMISSION (8 recessive bits) before initiating further transmission."},
            {"name": "bus off",       "description": "Output drivers switched off; no influence on the bus. Recovers to error-active (counters = 0) after 128 occurrences of 11 consecutive recessive bits monitored on the bus."},
        ])
        d.setdefault("fsm_hints_transmitter", [
            {"name": "TX_BUS_IDLE",        "description": "Bus idle (≥ 11 consecutive recessive bits). Pending message waits."},
            {"name": "TX_SOF",             "description": "Transmit START OF FRAME (1 dominant bit); all nodes hard-synchronize."},
            {"name": "TX_ARBITRATION",     "description": "Send IDENTIFIER + RTR bit by bit; monitor bus. Drove recessive but read dominant → LOSE arbitration → switch to receiver."},
            {"name": "TX_CONTROL",         "description": "Send CONTROL FIELD (r1, r0, DLC)."},
            {"name": "TX_DATA",            "description": "Send DATA FIELD (0..8 bytes, MSB first within each byte)."},
            {"name": "TX_CRC",             "description": "Send 15-bit CRC SEQUENCE + recessive CRC DELIMITER."},
            {"name": "TX_ACK_SLOT",        "description": "Drive recessive on ACK SLOT; sample bus; expect a dominant from at least one receiver."},
            {"name": "TX_ACK_DELIM",       "description": "Drive recessive ACK DELIMITER."},
            {"name": "TX_EOF",             "description": "Drive 7 recessive bits as END OF FRAME."},
            {"name": "TX_INTERMISSION",    "description": "Drive 3 recessive INTERMISSION bits."},
            {"name": "TX_SUSPEND",         "description": "(error-passive only) Drive 8 recessive SUSPEND TRANSMISSION bits before next transmission."},
        ])
        d.setdefault("fsm_hints_receiver", [
            {"name": "RX_BUS_IDLE",      "description": "Wait for dominant bit (= START OF FRAME)."},
            {"name": "RX_HARD_SYNC",     "description": "Hard-synchronize internal bit time to the SOF edge."},
            {"name": "RX_ARBITRATION",   "description": "Sample IDENTIFIER + RTR; apply MESSAGE FILTERING locally."},
            {"name": "RX_DATA_COLLECT",  "description": "Receive CONTROL + DATA + CRC; resynchronize on each recessive→dominant transition (subject to RJW)."},
            {"name": "RX_ACK_GEN",       "description": "If CRC matched, drive dominant during ACK SLOT."},
            {"name": "RX_VALIDATE",      "description": "If no error up to the last-but-one bit of EOF, message is valid; deliver to object layer."},
        ])
        d.setdefault("synchronization_rules", [
            "Only one SYNCHRONIZATION within one bit time is allowed.",
            "An edge is used for SYNCHRONIZATION only if the value detected at the previous SAMPLE POINT differs from the bus value immediately after the edge.",
            "HARD SYNCHRONIZATION is performed on the recessive-to-dominant edge during BUS IDLE (= START OF FRAME).",
            "All other recessive-to-dominant edges (and optionally dominant-to-recessive edges at low bit rates) use RESYNCHRONIZATION.",
            "A node transmitting a dominant bit will not RESYNCHRONIZE on a recessive-to-dominant edge with positive PHASE ERROR (when only recessive-to-dominant edges are used).",
        ])
        d.setdefault("arbitration_rule",
            "Bitwise on ARBITRATION FIELD (IDENTIFIER + RTR). Each transmitter compares its driven bit to the monitored bus level. Recessive driven + dominant monitored → arbitration lost; transmitter withdraws (does not send any further bits this frame) and may retry when bus is idle.")
        d.setdefault("anti_deadlock_rule",
            "Multimaster arbitration is non-blocking — winner continues with its frame; losers become receivers. No information is lost. Fault confinement (error-passive / bus-off) prevents a single defective node from blocking the bus.")
        d.setdefault("exit_from_reset_or_wakeup",
            "On wake-up the transfer layer waits for the system's oscillator to stabilize, then waits to synchronize itself to bus activity by checking for 11 consecutive recessive bits before switching bus drivers to 'on-bus'.")
        d.setdefault("default_signal_state_when_bus_free",
            "Bus idle = all nodes drive recessive (= released; pulled to recessive by the physical layer).")
        d.setdefault("wake_up_message_identifier",
            "Special wake-up message uses the dedicated lowest-priority IDENTIFIER 'rrr rrrd rrrr' (r=recessive, d=dominant).")
        _write(p, d)

    # L7 test/debug
    p = gd / "L7_TEST_DEBUG.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("test_debug_architecture_present", False)
        d.setdefault("spec_provided_observability", [
            {"name": "TRANSMIT ERROR COUNT", "purpose": "Tracks transmitter-side error events; thresholds 96 (heavily-disturbed warning), 128 (error-passive), 256 (bus-off)."},
            {"name": "RECEIVE ERROR COUNT",  "purpose": "Tracks receiver-side error events; threshold 128 → error-passive."},
            {"name": "ACK SLOT response",    "purpose": "Per-frame acknowledgment: transmitter samples ACK SLOT for dominant; absence is ACKNOWLEDGMENT ERROR."},
            {"name": "ERROR FLAG",           "purpose": "Active = 6 dominant bits (visible globally); Passive = 6 recessive bits."},
            {"name": "OVERLOAD FLAG",        "purpose": "Receiver-requested delay before next DATA/REMOTE FRAME; 6 dominant bits."},
            {"name": "11-consecutive-recessive monitor", "purpose": "Used for re-entry from bus-off and start-up synchronization."},
        ])
        d.setdefault("self_check_mechanisms", [
            "Monitoring — transmitters compare bit levels driven to bus levels detected.",
            "Cyclic Redundancy Check — 15-bit CRC SEQUENCE.",
            "Bit Stuffing — detect 6 consecutive identical bits in stuffed fields = STUFF ERROR.",
            "Message Frame Check — fixed-form fields (CRC DELIMITER, ACK DELIMITER, EOF, INTERMISSION) checked for illegal bits = FORM ERROR.",
        ])
        d.setdefault("error_count_thresholds", [
            {"threshold": 96,  "consequence": "Diagnostic warning — heavily disturbed bus (note in spec)."},
            {"threshold": 128, "consequence": "Node enters error-passive state."},
            {"threshold": 256, "consequence": "Transmit-error-count ≥ 256 → node enters bus-off state."},
        ])
        d.setdefault("recovery_from_bus_off",
            "After 128 occurrences of 11 consecutive recessive bits on the bus, a bus-off node is permitted to become error-active again (error counts both reset to 0).")
        d.setdefault("notes",
            "CAN 2.0 does not specify scan / JTAG / BIST. The protocol's strong built-in error detection (CRC + bit-monitoring + bit-stuffing + frame check + ACK) plus fault confinement counts provide a self-checking system at the protocol layer.")
        _write(p, d)

    # L8 RTL constants
    p = gd / "L8_RTL_CONSTANTS.json"
    if p.is_file():
        d = _read(p)
        wp = d.setdefault("width_parameters", {})
        if isinstance(wp, dict):
            for k, v in {
                "IDENTIFIER_WIDTH_PART_A_bits": 11,
                "IDENTIFIER_WIDTH_PART_B_extended_bits": 29,
                "RTR_BIT_WIDTH": 1,
                "CONTROL_FIELD_WIDTH_bits": 6,
                "DLC_WIDTH_bits": 4,
                "DATA_BYTE_WIDTH_bits": 8,
                "DATA_FIELD_MIN_BYTES": 0,
                "DATA_FIELD_MAX_BYTES": 8,
                "CRC_SEQUENCE_WIDTH_bits": 15,
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
                "CRC_REGISTER_WIDTH_bits": 15,
                "TRANSMIT_ERROR_COUNT_WIDTH_bits": 9,
                "RECEIVE_ERROR_COUNT_WIDTH_bits": 9,
            }.items():
                wp.setdefault(k, v)
        d.setdefault("crc_polynomial", {
            "name": "BCH code optimized for frames < 127 bits",
            "polynomial": "X^15 + X^14 + X^10 + X^8 + X^7 + X^4 + X^3 + 1",
            "hex_polynomial_value": "0x4599",
            "initial_register_value": 0,
        })
        d.setdefault("bit_timing_constants", {
            "SYNC_SEG_time_quanta": 1,
            "PROP_SEG_min_max_time_quanta": [1, 8],
            "PHASE_SEG1_min_max_time_quanta": [1, 8],
            "PHASE_SEG2_rule": "max(PHASE_SEG1, INFORMATION_PROCESSING_TIME)",
            "INFORMATION_PROCESSING_TIME_max_time_quanta": 2,
            "BIT_TIME_TOTAL_min_max_time_quanta": [8, 25],
            "RJW_min_max_time_quanta": [1, "min(4, PHASE_SEG1)"],
            "PRESCALER_range": [1, 32],
            "MAX_OSCILLATOR_TOLERANCE_baseline_percent": 0.5,
            "MAX_OSCILLATOR_TOLERANCE_with_Section_9_modifications_percent": 1.5,
        })
        d.setdefault("key_constants_for_RTL_authoring", {
            "bus_values": {
                "dominant": "logical 0 (wired-AND wins)",
                "recessive": "logical 1 (released; pulled by physical layer)",
            },
            "bit_coding": "Non-Return-to-Zero (NRZ)",
            "bit_stuffing_in_fields": ["START_OF_FRAME", "ARBITRATION_FIELD", "CONTROL_FIELD", "DATA_FIELD", "CRC_SEQUENCE"],
            "bit_stuffing_threshold": 5,
            "fixed_form_fields": ["CRC_DELIMITER", "ACK_FIELD", "END_OF_FRAME", "INTERMISSION"],
            "rtr_value_DATA_FRAME": "dominant",
            "rtr_value_REMOTE_FRAME": "recessive",
            "byte_order_in_data_field": "MSB-first",
            "identifier_transmit_order_part_A": "ID-10 (MSB) first → ID-0 (LSB) last",
            "identifier_constraint_part_A": "7 most significant bits (ID-10 .. ID-4) must NOT be all recessive",
            "recovery_time_max_bit_times": 29,
            "consecutive_recessive_bits_for_bus_off_recovery": 11,
            "bus_off_recovery_recessive_burst_count": 128,
            "max_overload_frames_between_data_or_remote_frames": 2,
        })
        d.setdefault("error_count_constants", {
            "warning_threshold": 96,
            "error_passive_threshold": 128,
            "bus_off_threshold_transmit": 256,
            "increment_on_receive_error": 1,
            "increment_on_dominant_after_error_flag_receiver": 8,
            "increment_on_transmitter_error_flag": 8,
            "decrement_on_successful_transmission_or_reception": 1,
        })
        _write(p, d)

    # L8_TIMING
    p = gd / "L8_TIMING_WAVEFORM.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("nominal_bit_time_structure", {
            "SYNC_SEG":   "1 Time Quantum (TQ). Used to synchronize the various nodes; an edge is expected to lie within this segment.",
            "PROP_SEG":   "Programmable 1..8 TQ. Compensates for physical delay times within the network: twice the sum of (signal propagation time on bus line + input comparator delay + output driver delay).",
            "PHASE_SEG1": "Programmable 1..8 TQ. Lengthened by RESYNCHRONIZATION when phase error is positive.",
            "PHASE_SEG2": "max(PHASE_SEG1, INFORMATION_PROCESSING_TIME). Shortened by RESYNCHRONIZATION when phase error is negative.",
            "SAMPLE_POINT": "At the end of PHASE_SEG1 — bus level read and interpreted as bit value.",
            "INFORMATION_PROCESSING_TIME": "≤ 2 TQ; starts at SAMPLE_POINT for calculating the subsequent bit level.",
            "BIT_TIME_TOTAL": "8..25 TQ (programmable)",
            "TIME_QUANTUM": "TQ = m × MINIMUM_TIME_QUANTUM, where m is the prescaler value (1..32).",
        })
        d.setdefault("synchronization_waveform", {
            "HARD_SYNCHRONIZATION": "Restarts internal bit time with SYNC_SEG; forced by recessive-to-dominant edge during BUS IDLE (= START OF FRAME).",
            "RESYNCHRONIZATION":    "Lengthens PHASE_SEG1 (positive PHASE ERROR ≤ RJW) or shortens PHASE_SEG2 (negative PHASE ERROR ≤ RJW).",
        })
        d.setdefault("frame_waveform", {
            "DATA_FRAME":      "SOF (1d) → ARBITRATION (12 bits: 11-bit ID + RTR) → CONTROL (6 bits: r1 r0 DLC[3:0]) → DATA (0..64 bits) → CRC (15-bit + recessive delim) → ACK (recessive slot + recessive delim) → EOF (7 recessive bits) → INTERMISSION (3 recessive bits) → BUS IDLE",
            "REMOTE_FRAME":    "Same as DATA FRAME but RTR=recessive and no DATA FIELD.",
            "ERROR_FRAME":     "ACTIVE ERROR FLAG (6 dominant bits) [or PASSIVE = 6 recessive bits in error-passive node] → ERROR DELIMITER (8 recessive bits)",
            "OVERLOAD_FRAME":  "OVERLOAD FLAG (6 dominant bits) → OVERLOAD DELIMITER (8 recessive bits)",
        })
        d.setdefault("interframe_space_waveform", {
            "INTERMISSION":         "3 recessive bits; no station may start a transmission during this time.",
            "BUS_IDLE":             "Arbitrary length recessive; any unit may access.",
            "SUSPEND_TRANSMISSION": "8 recessive bits after INTERMISSION; only for error-passive transmitters before initiating next transmission.",
        })
        d.setdefault("active_error_flag_superposition_waveform",
            "When multiple nodes detect the error and each transmit a 6-dominant-bit ACTIVE ERROR FLAG, the result on the bus is a superposition of 6..12 dominant bits depending on detection timing.")
        d.setdefault("phase_error_definition", {
            "e_eq_0": "Edge lies within SYNC_SEG.",
            "e_gt_0": "Edge lies before the SAMPLE POINT.",
            "e_lt_0": "Edge lies after the SAMPLE POINT of the previous bit.",
        })
        d.setdefault("max_distance_between_resync_edges_bit_times", 29)
        _write(p, d)

    # L9 integration
    p = gd / "L9_INTEGRATION_SPEC.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("module_role",
            "Wire-level multi-master serial communications protocol defined as object + transfer + physical layers (ISO/OSI data-link + physical scope). This specification scopes the transfer layer + consequences on the surrounding layers; object layer + application layer + physical layer details left to integrator.")
        d.setdefault("layered_structure_summary", [
            "Application Layer — out of scope.",
            "Object Layer — message filtering, message + status handling.",
            "Transfer Layer (kernel) — fault confinement, error detection + signalling, message validation, acknowledgment, arbitration, message framing, bit timing + synchronization.",
            "Physical Layer — signal level + bit representation + transmission medium (NOT defined here; integrator picks single-wire+ground, differential pair, optical fibre, etc.).",
        ])
        d.setdefault("integration_overview", {
            "topology":          "Single shared serial channel; any number of units may be connected (limited by delay and electrical loads).",
            "drive_type":        "Wired-AND: dominant overrides recessive on simultaneous transmission.",
            "no_chip_select":    "Addressing is by message IDENTIFIER (content-addressed) — no per-device chip-select.",
            "uniform_bit_rate":  "Bit rate is uniform and fixed within a given network.",
            "max_baud_typical_automotive": "1 Mbit/s",
        })
        d.setdefault("interface_categories", [
            "TRANSMITTER — unit originating a message; stays transmitter until bus idle or arbitration lost.",
            "RECEIVER — any unit that is not transmitter and the bus is not idle.",
            "error-active / error-passive / bus-off — fault confinement states.",
        ])
        d.setdefault("interconnect_topologies_supported", [
            "Single multi-master bus — all CAN nodes share one physical channel; arbitration by IDENTIFIER.",
            "Star / branched topology with bus repeaters (integrator's choice at physical layer).",
            "Mixed Part-A (11-bit) + Part-B (29-bit) nodes — interoperable as long as extended-format messages are not used.",
        ])
        d.setdefault("default_signal_values_when_omitted",
            "Bus idle = all nodes drive recessive (= released). The bus is recognized to be free; any unit having something to transmit can access the bus.")
        d.setdefault("soc_dependent_items", [
            "Physical-layer transceiver choice (e.g. ISO 11898-2 differential, ISO 11898-3 fault-tolerant low-speed, optical).",
            "Pull-up / termination resistor selection at the physical layer.",
            "Crystal / oscillator selection (must meet 0.5 % or 1.5 % tolerance depending on Section 9 modifications).",
            "Prescaler value (1..32) and per-segment programming (PROP_SEG, PHASE_SEG1, SJW).",
            "Acceptance-filter / mailbox programming (per controller's register file).",
            "Interrupt routing for error / wakeup / message-received events.",
            "Sleep-mode wake-up source selection.",
        ])
        d.setdefault("low_power_modes", {
            "sleep_mode":   "CAN device set into sleep mode without internal activity and with disconnected bus drivers.",
            "wake_up":      "Finished by any bus activity or by internal conditions of the system.",
            "wake_up_message_id": "Special wake-up message with dedicated lowest-possible IDENTIFIER ('rrr rrrd rrrr').",
        })
        _write(p, d)

    # L11 OTP
    p = gd / "L11_OTP_CONTENT.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("otp_present", False)
        d["notes"] = (
            "CAN 2.0 is a wire-level protocol spec; no OTP / fuse / "
            "configuration ROM at the protocol layer. Concrete CAN "
            "controllers may use OTP to lock acceptance filters or bit-"
            "timing presets, but this is a per-device feature, not "
            "protocol-defined.")
        _write(p, d)

    # L12 behavioral
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("typical_data_frame_transmit_sequence", [
            "1. Wait for bus idle (≥ 11 consecutive recessive bits).",
            "2. Drive START OF FRAME (1 dominant bit); all nodes hard-synchronize.",
            "3. Drive 11-bit IDENTIFIER + RTR bit (ARBITRATION FIELD); on each bit monitor bus level. If drove recessive but bus is dominant → LOSE arbitration, withdraw, become receiver of the winner's frame.",
            "4. Drive CONTROL FIELD (r1 + r0 + DLC[3:0]).",
            "5. Drive DATA FIELD (0..8 bytes, MSB first per byte).",
            "6. Drive 15-bit CRC SEQUENCE + recessive CRC DELIMITER.",
            "7. Drive recessive ACK SLOT; sample bus; expect dominant ACK from at least one receiver. Otherwise raise ACKNOWLEDGMENT ERROR.",
            "8. Drive recessive ACK DELIMITER + 7 recessive END OF FRAME bits.",
            "9. Drive 3 recessive INTERMISSION bits.",
            "10. (if error-passive) Drive 8 recessive SUSPEND TRANSMISSION bits before next transmission.",
        ])
        d.setdefault("typical_remote_frame_sequence", [
            "1. Send DATA FRAME structure with RTR = recessive and no DATA FIELD.",
            "2. Node holding the matching DATA FRAME responds with DATA FRAME (same IDENTIFIER).",
            "3. If a DATA FRAME and matching REMOTE FRAME start simultaneously, DATA FRAME wins (RTR dominant beats RTR recessive).",
        ])
        d.setdefault("typical_receive_sequence", [
            "1. Receiver detects SOF dominant bit; hard-synchronizes.",
            "2. Samples IDENTIFIER + RTR + CONTROL + DATA + CRC.",
            "3. Applies MESSAGE FILTERING on IDENTIFIER (per object layer).",
            "4. Computes 15-bit CRC; compares with received CRC SEQUENCE.",
            "5. If CRC matched and message reaches last-but-one bit of EOF: drive dominant ACK on ACK SLOT and validate message.",
            "6. If CRC mismatch: at the bit following ACK DELIMITER, start transmitting an ERROR FLAG.",
        ])
        d.setdefault("arbitration_loss_sequence", [
            "1. Two transmitters start simultaneously on bus idle.",
            "2. On each ARBITRATION FIELD bit, each compares its driven bit to bus.",
            "3. The first time a transmitter drives recessive but reads dominant: it loses arbitration.",
            "4. Loser withdraws (stops driving) and becomes a receiver of the winner's frame.",
            "5. Loser may retry retransmission once the bus is idle again.",
        ])
        d.setdefault("error_signalling_sequence", [
            "1. Error-active node detects BIT/STUFF/FORM/ACK error during a frame.",
            "2. At the next bit, transmit ACTIVE ERROR FLAG (6 dominant bits).",
            "3. Other nodes detect this and transmit their own ACTIVE ERROR FLAG; superposition results in 6..12 dominant bits.",
            "4. After ERROR FLAG, transmit ERROR DELIMITER (8 recessive bits).",
            "5. Original transmitter automatically retransmits the message once bus is idle.",
            "6. CRC errors specifically: ERROR FLAG starts at the bit following ACK DELIMITER (not immediately).",
        ])
        d.setdefault("fault_confinement_transition_sequence", [
            "1. error-active → error-passive: when TX_ERR_COUNT ≥ 128 or RX_ERR_COUNT ≥ 128.",
            "2. error-passive → bus-off: when TX_ERR_COUNT ≥ 256.",
            "3. error-passive → error-active: when both TX_ERR_COUNT and RX_ERR_COUNT ≤ 127.",
            "4. bus-off → error-active: after observing 128 consecutive sequences of 11 recessive bits; both error counts reset to 0.",
        ])
        d.setdefault("wake_up_sequence", [
            "1. Node enters sleep mode: internal activity stopped; bus drivers disconnected.",
            "2. Bus activity (any dominant edge) or internal condition triggers wake-up.",
            "3. Transfer layer waits for oscillator to stabilize.",
            "4. Waits for 11 consecutive recessive bits → confirmed bus synchronization.",
            "5. Bus drivers go on-bus.",
            "6. To wake other nodes: transmit special wake-up message with identifier 'rrr rrrd rrrr' (the lowest possible priority — guaranteed to lose arbitration to anything else).",
        ])
        _write(p, d)

    # L13
    p = gd / "L13_LAB_CALIBRATION.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("lab_calibration_present", False)
        d["notes"] = (
            "CAN 2.0 is a wire-level protocol; no analog reference / "
            "trim / calibration loop. Oscillator tolerance is a system-"
            "integration concern (0.5 % baseline; 1.5 % with the Section "
            "9 upwards-compatible modifications). Per-segment bit-timing "
            "programming (PROP_SEG / PHASE_SEG1 / SJW) substitutes for "
            "any calibration loop at the protocol level.")
        _write(p, d)

    # L14 versioning
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("spec_version", "CAN 2.0 (September 1991)")
        if _empty(f.get("previous_versions")):
            f["previous_versions"] = [
                "CAN 1.0 — first Bosch CAN spec (1986).",
                "CAN 1.2 — Bosch CAN spec used through late 1980s; standard 11-bit identifier format only.",
                "CAN 2.0 Part A — message format equivalent to CAN 1.2.",
                "CAN 2.0 Part B — adds 29-bit extended identifier format; standard + extended messages coexist on same network.",
            ]
        if _empty(f.get("key_changes")):
            f["key_changes"] = [
                {"version": "CAN 2.0 Part A", "summary": "Renamed/clarified CAN 1.2 11-bit identifier format; introduced four frame types (DATA / REMOTE / ERROR / OVERLOAD); fault confinement formalized."},
                {"version": "CAN 2.0 Part B", "summary": "Adds 29-bit extended identifier format; backward-compatible with Part A nodes provided extended-format messages are not used in mixed networks."},
                {"version": "Section 9 (oscillator tolerance)", "summary": "Upwards-compatible modifications increase max oscillator tolerance from 0.5 % to 1.5 % by allowing SOF at the 3rd INTERMISSION bit etc."},
            ]
        if _empty(f.get("backward_compat_traps")):
            f["backward_compat_traps"] = [
                {"trap_name": "extended_id_in_mixed_network",
                 "Part_A_only_node":  "Sees the 29-bit extended identifier as a malformed standard frame.",
                 "Part_B_node":       "Generates extended-format frames.",
                 "trap": "Mixing Part-A and Part-B nodes is interoperable ONLY if no extended-format messages are used; introducing extended-format breaks Part-A nodes."},
                {"trap_name": "reserved_control_bits_r0_r1",
                 "spec_required":     "Transmitter sends r1 and r0 as dominant.",
                 "receiver_required": "Accept dominant AND recessive in all combinations (for forward compatibility with future protocol expansions).",
                 "trap": "Receivers that reject recessive r0/r1 break when interoperating with future Part C or CAN FD nodes."},
                {"trap_name": "section_9_oscillator_tolerance",
                 "without_modification":  "Max oscillator tolerance 0.5 %.",
                 "with_section_9_mods":   "Max oscillator tolerance 1.5 %; node treats dominant at 3rd INTERMISSION bit as new SOF.",
                 "trap": "Nodes without Section 9 modifications may interpret the 3rd-bit dominant as an OVERLOAD condition, generating a different bus behavior."},
            ]
        f.setdefault("version_naming_history_note",
            "Bosch CAN 1.0 was internal (1986); CAN 1.2 was the widely deployed early-1990s automotive spec; CAN 2.0 (1991) introduced the Part A / Part B split. Later, ISO 11898 standardized CAN (1993) — ISO 11898-1 ≈ Bosch CAN 2.0 Part B, ISO 11898-2 specifies the high-speed physical layer, ISO 11898-3 the fault-tolerant low-speed PHY.")
        d["fields"] = f
        _write(p, d)

    # L15 encoding tables
    p = gd / "L15_ENCODING_TABLES.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("data_length_code_table", {
            "header_columns": ["Number of Data Bytes", "DLC3", "DLC2", "DLC1", "DLC0"],
            "rows": [
                {"bytes": 0, "DLC3": "d", "DLC2": "d", "DLC1": "d", "DLC0": "d"},
                {"bytes": 1, "DLC3": "d", "DLC2": "d", "DLC1": "d", "DLC0": "r"},
                {"bytes": 2, "DLC3": "d", "DLC2": "d", "DLC1": "r", "DLC0": "d"},
                {"bytes": 3, "DLC3": "d", "DLC2": "d", "DLC1": "r", "DLC0": "r"},
                {"bytes": 4, "DLC3": "d", "DLC2": "r", "DLC1": "d", "DLC0": "d"},
                {"bytes": 5, "DLC3": "d", "DLC2": "r", "DLC1": "d", "DLC0": "r"},
                {"bytes": 6, "DLC3": "d", "DLC2": "r", "DLC1": "r", "DLC0": "d"},
                {"bytes": 7, "DLC3": "d", "DLC2": "r", "DLC1": "r", "DLC0": "r"},
                {"bytes": 8, "DLC3": "r", "DLC2": "d", "DLC1": "d", "DLC0": "d"},
            ],
            "note": "Admissible numbers of data bytes: {0, 1, ..., 7, 8}. Other values may not be used.",
        })
        f.setdefault("frame_field_widths_table", {
            "header_columns": ["Field", "Width (bits)", "Form"],
            "rows": [
                ["START_OF_FRAME",     "1",       "1 dominant bit"],
                ["IDENTIFIER (Part A)", "11",     "MSB-first; constraint: 7 MSBs not all recessive"],
                ["RTR",                "1",       "dominant for DATA FRAME; recessive for REMOTE FRAME"],
                ["r1 r0 (reserved)",   "2",       "transmitter sends dominant; receiver accepts both"],
                ["DLC",                "4",       "data byte count (0..8)"],
                ["DATA",               "0..64",   "0..8 data bytes; MSB-first per byte"],
                ["CRC_SEQUENCE",       "15",      "BCH polynomial CRC"],
                ["CRC_DELIMITER",      "1",       "1 recessive bit"],
                ["ACK_SLOT",           "1",       "transmitter recessive; receivers superscribe with dominant"],
                ["ACK_DELIMITER",      "1",       "1 recessive bit"],
                ["END_OF_FRAME",       "7",       "all recessive bits"],
                ["INTERMISSION",       "3",       "all recessive bits"],
                ["SUSPEND_TRANSMISSION","8",      "all recessive bits (error-passive transmitter only)"],
            ],
        })
        f.setdefault("error_frame_table", {
            "header_columns": ["Sub-field", "Width", "Form"],
            "rows": [
                ["ACTIVE_ERROR_FLAG",  "6 bits", "all dominant"],
                ["PASSIVE_ERROR_FLAG", "6 bits", "all recessive"],
                ["ERROR_DELIMITER",    "8 bits", "all recessive"],
            ],
        })
        f.setdefault("overload_frame_table", {
            "header_columns": ["Sub-field", "Width", "Form"],
            "rows": [
                ["OVERLOAD_FLAG",      "6 bits", "all dominant"],
                ["OVERLOAD_DELIMITER", "8 bits", "all recessive"],
            ],
        })
        f.setdefault("crc_polynomial",
            "X^15 + X^14 + X^10 + X^8 + X^7 + X^4 + X^3 + 1 (hex 0x4599 in 15-bit form)")
        f.setdefault("wake_up_message_identifier_encoding",
            "'rrr rrrd rrrr' (11-bit; only the 5th MSB is dominant; lowest possible priority)")
        if _empty(f.get("tables")):
            f["tables"] = [
                "Coding of the number of data bytes by the DATA LENGTH CODE (Part A page 12)",
                "Frame field widths and form (Part A pages 11-13)",
                "Bus values: dominant / recessive (Part A page 8)",
                "Fault confinement state thresholds (Part A pages 24-26)",
            ]
        d["fields"] = f
        _write(p, d)

    # L16 compliance
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("must_have_properties", [
            "Conform to either Part A (standard 11-bit) or Part B (standard + extended 29-bit).",
            "Bit coding by NRZ + bit stuffing in stuffed fields (SOF, ARBITRATION, CONTROL, DATA, CRC_SEQUENCE).",
            "Bit stuffing inserts complementary bit after 5 identical consecutive bits.",
            "Fixed-form fields (CRC_DELIMITER, ACK_FIELD, EOF, INTERMISSION) NOT stuffed.",
            "Bus values: dominant overrides recessive (wired-AND).",
            "START_OF_FRAME = 1 dominant bit; all stations hard-synchronize on its leading edge.",
            "IDENTIFIER (11 bits, Part A) transmitted MSB-first (ID-10 → ID-0); 7 MSBs must not be all recessive.",
            "RTR: dominant for DATA FRAME; recessive for REMOTE FRAME.",
            "DLC encoded per Table; only values for 0..8 bytes are admissible.",
            "CRC SEQUENCE: 15-bit BCH polynomial X^15 + X^14 + X^10 + X^8 + X^7 + X^4 + X^3 + 1.",
            "CRC DELIMITER + ACK DELIMITER + each EOF bit must be recessive.",
            "ACK SLOT: transmitter sends recessive; receivers with matched CRC respond dominant.",
            "Active error flag = 6 dominant bits; passive = 6 recessive bits; both followed by 8 recessive ERROR DELIMITER bits.",
            "Intermission = 3 recessive bits; no station may start transmission during it.",
            "Error-passive transmitter adds SUSPEND TRANSMISSION (8 recessive bits) before next transmission.",
            "Fault confinement state transitions per TRANSMIT/RECEIVE ERROR COUNT thresholds 128 and 256.",
            "Bus-off node may rejoin only after 128 occurrences of 11 consecutive recessive bits.",
        ])
        f.setdefault("must_not_have_properties", [
            "More than 2 OVERLOAD FRAMEs generated between two DATA/REMOTE FRAMEs.",
            "Transmitting on the bus while in 'bus off' state (output drivers must be off).",
            "Using identifier with 7 MSBs all recessive (Part A constraint).",
            "Using DLC values outside the table for 0..8 bytes.",
        ])
        f.setdefault("compliance_failure_modes", [
            {"mode": "BIT ERROR",            "trigger": "Monitored bus value ≠ transmitted bit (except in arbitration recessive→dominant and ACK SLOT recessive→dominant)."},
            {"mode": "STUFF ERROR",          "trigger": "6 consecutive identical bits in a stuffed field."},
            {"mode": "CRC ERROR",            "trigger": "Calculated CRC ≠ received CRC SEQUENCE."},
            {"mode": "FORM ERROR",           "trigger": "Illegal bit in a fixed-form field."},
            {"mode": "ACKNOWLEDGMENT ERROR", "trigger": "Transmitter does not monitor a dominant bit during the ACK SLOT."},
        ])
        f.setdefault("performance_of_error_detection", [
            "All global errors detected.",
            "All local errors at transmitters detected.",
            "Up to 5 randomly distributed errors per message detected.",
            "Burst errors of length < 15 detected.",
            "Errors of any odd number detected.",
            "Residual error probability for undetected corrupted messages < message_error_rate × 4.7 × 10^-11.",
        ])
        f.setdefault("recovery_time_bound",
            "At most 29 bit times from detecting an error until the start of the next message (if no further error).")
        d["fields"] = f
        _write(p, d)

    # L17
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f["channels"] = [
            {
                "name": "CAN bus (single channel)",
                "direction": "bidirectional wired-AND",
                "purpose": "Single shared serial channel carrying NRZ-coded bit stream; dominant overrides recessive on simultaneous transmission.",
                "physical_realization": "Spec leaves physical layer unspecified: single-wire+ground, differential pair, optical, etc. Common: ISO 11898-2 high-speed differential, ISO 11898-3 fault-tolerant low-speed, ISO 11898-4 time-triggered.",
            },
        ]
        f["logical_signal_states"] = [
            {"name": "dominant",  "value": "logical 0", "rule": "Wins simultaneous transmission (wired-AND)."},
            {"name": "recessive", "value": "logical 1", "rule": "Released; pulled to recessive by the physical layer when no node drives dominant."},
        ]
        f["frame_fields_as_signal_segments"] = [
            {"name": "START_OF_FRAME",       "type": "delimiter",      "form": "1 dominant bit"},
            {"name": "ARBITRATION_FIELD",    "type": "address+request","form": "11-bit IDENTIFIER + 1-bit RTR (Part A)"},
            {"name": "CONTROL_FIELD",        "type": "metadata",        "form": "r1 + r0 + 4-bit DLC"},
            {"name": "DATA_FIELD",           "type": "payload",         "form": "0..8 bytes, MSB-first"},
            {"name": "CRC_FIELD",            "type": "integrity",       "form": "15-bit CRC + 1 recessive delimiter"},
            {"name": "ACK_FIELD",            "type": "handshake",       "form": "1 ACK slot + 1 recessive delimiter"},
            {"name": "END_OF_FRAME",         "type": "delimiter",       "form": "7 recessive bits"},
            {"name": "INTERMISSION",         "type": "interframe space","form": "3 recessive bits"},
            {"name": "BUS_IDLE",             "type": "interframe space","form": "arbitrary recessive"},
            {"name": "SUSPEND_TRANSMISSION", "type": "interframe space","form": "8 recessive bits (error-passive TX only)"},
            {"name": "ACTIVE_ERROR_FLAG",    "type": "error signal",    "form": "6 dominant bits"},
            {"name": "PASSIVE_ERROR_FLAG",   "type": "error signal",    "form": "6 recessive bits"},
            {"name": "ERROR_DELIMITER",      "type": "error delimiter", "form": "8 recessive bits"},
            {"name": "OVERLOAD_FLAG",        "type": "delay signal",    "form": "6 dominant bits"},
            {"name": "OVERLOAD_DELIMITER",   "type": "delay delimiter", "form": "8 recessive bits"},
        ]
        f["channel_counts"] = {
            "logical_channels": 1,
            "logical_bit_values": 2,
            "frame_types": 4,
            "bit_fields_in_data_frame": 7,
            "bit_timing_segments_per_bit": 4,
            "fault_confinement_states": 3,
        }
        # Force-overwrite dependency_graph (earlier steps may have written
        # AXI-leaning content; CAN shape is single shared channel).
        f["dependency_graph"] = {
            "common_rule": "Single shared channel: all nodes monitor every bit; dominant wins on collision. Synchronization is event-driven on recessive-to-dominant edges.",
            "data_dependency": "Each bit is sampled at SAMPLE POINT (end of PHASE_SEG1). Resynchronization adjusts PHASE_SEG1 or PHASE_SEG2 (bounded by RJW) per phase error sign.",
            "ack_dependency":  "ACK SLOT response = OR of (CRC-matched ∧ ready) across all receivers.",
        }
        f["handshake_pairs"] = [
            {"name": "ARBITRATION",     "from": "competing transmitters", "to": "transmitters", "rule": "Bitwise on IDENTIFIER + RTR; loser withdraws on recessive-driven vs dominant-monitored mismatch."},
            {"name": "ACK_SLOT_ACK",    "from": "all CRC-matched receivers", "to": "transmitter", "rule": "Receivers superscribe transmitter's recessive ACK SLOT with dominant."},
            {"name": "OVERLOAD_REQUEST","from": "any receiver",            "to": "all nodes",   "rule": "Receiver drives OVERLOAD FLAG to delay next DATA/REMOTE FRAME (max 2 consecutive)."},
        ]
        f.setdefault("ordering_rules", {
            "within_a_byte":  "MSB-first within each data byte.",
            "identifier_bits":"MSB-first (ID-10 → ID-0).",
            "global_ordering":"Higher-priority IDENTIFIER (more dominant bits early) wins arbitration; messages with same IDENTIFIER serialized by re-arbitration.",
        })
        d["fields"] = f
        _write(p, d)

    # L18
    p = gd / "L18_INTERCONNECT_TOPOLOGY.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f["topology_type"] = "Multi-master single-channel shared serial bus; multidrop wired-AND with bitwise IDENTIFIER arbitration."
        f["supported_topologies"] = [
            {"name": "Linear bus (typical automotive)", "description": "All CAN nodes tap onto a single twisted-pair or single-wire+ground line; terminated at both ends in high-speed ISO 11898-2."},
            {"name": "Star / branched (low-speed)",     "description": "ISO 11898-3 fault-tolerant low-speed CAN allows branched topology (typical body electronics)."},
            {"name": "Optical fibre",                   "description": "Spec permits optical realization at physical layer (intentionally not detailed)."},
            {"name": "Sleep / wake-up network",         "description": "Sleeping nodes are woken by special wake-up message with dedicated lowest-priority identifier."},
        ]
        f["master_slave_role_summary"] = [
            {"role": "TRANSMITTER", "description": "A unit originating a message; stays transmitter until bus idle or arbitration is lost."},
            {"role": "RECEIVER",    "description": "A unit that is not transmitter and the bus is not idle."},
            {"role": "error-active node",  "description": "Normal operation; sends ACTIVE ERROR FLAGs."},
            {"role": "error-passive node", "description": "Degraded operation; sends only PASSIVE ERROR FLAGs; adds SUSPEND TRANSMISSION after own messages."},
            {"role": "bus-off node",       "description": "Not allowed to influence the bus; output drivers off."},
        ]
        f["interconnect_role"] = (
            "There is no protocol-layer interconnect (no router / bridge). "
            "The bus is a flat shared medium; any node can transmit when "
            "the bus is idle, and bitwise arbitration on IDENTIFIER resolves "
            "contention without information loss.")
        f["ordering_guarantees"] = {
            "single_bus":  "All nodes simultaneously see the same bus value (modulo signal propagation); data consistency = a message is accepted by all receivers or by none.",
            "arbitration": "Higher-priority messages (lower IDENTIFIER value) are transmitted first; no fairness guarantee for equal-priority messages — re-arbitration each time.",
        }
        f.setdefault("memory_vs_peripheral_regions",
            "Not applicable — CAN is wire-level. Per-controller mailbox / FIFO / acceptance-filter register maps live in the SoC integration spec.")
        f.setdefault("slave_classification", {
            "addressable_target":   "Not applicable — CAN is content-addressed, not destination-addressed. All nodes see every frame; MESSAGE FILTERING happens locally on the IDENTIFIER.",
            "data_producer":        "Any node may transmit DATA FRAMEs with one or more IDENTIFIERs.",
            "data_consumer":        "Any node may apply MESSAGE FILTERING to accept matching IDENTIFIERs.",
        })
        f.setdefault("default_signal_values_evidence_tables", [
            "Section 2 Basic Concepts — bus values",
            "Section 3 Message Transfer — frame types and fields",
            "Section 7 Fault Confinement — error count rules + state transitions",
        ])
        f.setdefault("wake_up_topology", {
            "wake_up_trigger": "Any bus activity (dominant edge) or internal condition.",
            "wake_up_message": "Dedicated identifier 'rrr rrrd rrrr' — lowest possible priority; intended to lose arbitration to anything else.",
            "post_wake_sync":  "Transfer layer waits for oscillator stabilization + 11 consecutive recessive bits before re-enabling bus drivers.",
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
            "CAN 2.0 is a wire-level protocol spec; no PDK / SDC / "
            "floorplan constraints at the protocol layer. Per-controller "
            "integration constraints (clock-tree budget, transceiver pad "
            "ring, common-mode rejection at the PHY) live in the SoC "
            "integration spec, not in Bosch CAN 2.0.")
        d["fields"] = f
        _write(p, d)

    # L20 DFT
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("dft_present", False)
        f["notes"] = (
            "CAN 2.0 does not specify DFT / scan / BIST. Protocol-level "
            "self-checking (CRC + bit monitoring + bit stuffing + frame "
            "check + ACK) plus fault confinement counts provide system-"
            "level diagnostics. SoC-integrated CAN controller IP from "
            "modern vendors (Bosch C_CAN / M_CAN, Microchip MCP2515, "
            "Xilinx XLN_CAN) adds standard scan insertion at the "
            "integrator level.")
        d["fields"] = f
        _write(p, d)

    # L21 power
    p = gd / "L21_POWER_INTENT.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("power_intent_present", False)
        f["low_power_modes_summary"] = {
            "sleep_mode":   "CAN device set into sleep mode without internal activity and with disconnected bus drivers.",
            "wake_up":      "Finished by any bus activity or by internal conditions; transfer layer waits for oscillator stabilization + 11 consecutive recessive bits before going on-bus.",
            "wake_up_message_id": "'rrr rrrd rrrr' (lowest-possible identifier; loses arbitration to everything else).",
        }
        f["notes"] = (
            "Power-domain partitioning is deferred to SoC + transceiver "
            "IP. The protocol-defined sleep/wake state machine is the "
            "only power feature in CAN 2.0.")
        d["fields"] = f
        _write(p, d)

    # L23 security
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("security_requirements_present", False)
        f["notes"] = (
            "Bosch CAN 2.0 (1991) is a wire-level protocol spec; no "
            "confidentiality / integrity / authentication features. CAN "
            "is broadcast — every node sees every frame. Built-in "
            "security primitive is the 15-bit CRC (anti-corruption only, "
            "not anti-tampering). Modern automotive security (CAN-FD "
            "MAC, SecOC, AUTOSAR SecOC profile) is layered on top — not "
            "part of Bosch CAN 2.0.")
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
def is_can(blob: str) -> bool:
    """Content-only `can` detector with a FOREIGN-PRIMARY DEFER.

    Empty-safe. Reads ONLY ``blob`` (spec text). The original Bosch CAN 2.0
    structural signature (DATA/REMOTE/ERROR FRAME, OR dominant/recessive +
    arbitration/identifier, OR CAN + Bosch) is necessary but NOT sufficient:
    several adjacent automotive / serial-bus protocols carry the same CAN
    data-link vocabulary or cite Bosch / CAN as a comparison, and would
    otherwise trip the (deliberately loose) structural branches below and have
    the generic CAN synth inject Bosch CAN 2.0 frame-format facts into their
    L-docs.

    Guard (mirrors `is_mipi`'s foreign-primary defer doctrine — general,
    content-only, NO benchmark-name / chip / SKU literal as detection logic):
    if the blob's DOMINANT subject is one of these foreign protocols, defer
    (return False), so the generic CAN synth never fires on a foreign spec
    that only shares CAN data-link vocabulary or names CAN/Bosch incidentally:

      - CAN-FD (a genuine derived-CHILD of CAN — it extends the CAN data-link
        layer, so it shares the structural base). Defer via CAN-FD's distinctive
        discriminators (a sibling-MUTEX): the flexible-data-rate control bits
        (BRS + FDF + ESI) or the Bosch M_CAN register model (M_CAN + CCCR).
      - CANopen (the CiA-301 application layer ON TOP of CAN): Object Dictionary
        / COB-ID with the PDO + SDO communication-object kernel.
      - FlexRay (TDMA automotive bus that cites CAN): static segment + dynamic
        segment + the macrotick/microtick or communication-cycle timing.
      - HDLC (ISO 13239 link layer that names bit-stuffing / Bosch comparisons):
        the HDLC I/S/U frame triple, or HDLC + 0x7E flag + bit stuffing.
      - I3C (MIPI sensor bus that supersedes I2C and cites CAN/Bosch): I3C +
        Dynamic Address + IBI, or the ENTDAA / CCC common-command-code model.
      - LIN (the low-cost automotive companion bus to CAN): the LIN name token
        with the BREAK+SYNC header or the master+schedule-table structure.

    These distinctive signatures are absent from the real Bosch CAN 2.0
    benchmark, so deferring on them keeps own-fire intact while suppressing the
    six foreign cross-fires. See test_protocol_detector_no_misfire.py.
    """
    if not blob:
        return False
    low = blob.lower()
    up = blob.upper()

    # --- FOREIGN-PRIMARY DEFER (the blob's true subject is NOT raw CAN). ---
    # CAN-FD child-MUTEX: flexible-data-rate control bits / Bosch M_CAN model.
    canfd_primary = (
        ("BRS" in blob and "FDF" in blob and "ESI" in blob)
        or ("M_CAN" in blob and "CCCR" in blob))
    # CANopen application-layer kernel (Object Dictionary / COB-ID + PDO + SDO).
    canopen_primary = (
        ("object dictionary" in low or "cob-id" in low or "cob id" in low)
        and "pdo" in low and "sdo" in low)
    # FlexRay TDMA segment + macrotick/microtick / communication-cycle timing.
    flexray_primary = (
        "static segment" in low and "dynamic segment" in low
        and ("macrotick" in low or "microtick" in low
             or "communication cycle" in low))
    # HDLC framing signature (I/S/U frame triple, or 0x7E flag + bit stuffing).
    hdlc_primary = (
        ("HDLC" in blob and "I-frame" in blob
         and "S-frame" in blob and "U-frame" in blob)
        or ("HDLC" in blob and "0x7E" in blob
            and "bit stuffing" in low))
    # I3C dynamic-addressing / common-command-code signature.
    i3c_primary = (
        ("I3C" in blob and "Dynamic Address" in blob and "IBI" in blob)
        or ("ENTDAA" in blob and "CCC" in blob)
        or ("I3C" in blob and "CCC" in blob))
    # LIN name token + BREAK/SYNC header or master/schedule-table structure.
    lin_primary = (
        ("LIN bus" in blob or "Local Interconnect Network" in blob
         or "LIN Consortium" in blob or "LIN 2." in blob)
        and (("BREAK" in up and "SYNC" in up)
             or ("master" in low and "schedule" in low)))
    if (canfd_primary or canopen_primary or flexray_primary
            or hdlc_primary or i3c_primary or lin_primary):
        return False

    # --- STRUCTURAL Bosch CAN 2.0 signature (unchanged from the runner's
    #     inline detector). ---
    return bool(
        ("DATA FRAME" in blob and "REMOTE FRAME" in blob
            and "ERROR FRAME" in blob)
        or ("dominant" in blob and "recessive" in blob
            and ("ARBITRATION" in blob.upper()
                 or "IDENTIFIER" in blob.upper()))
        or ("CAN" in blob and "Bosch" in blob))
