"""LIN-class protocol synth helper.

v0.1.84 — ic_class-gated overlay for `serial_peripheral_protocol` specs
that exhibit the LIN structural signature:
  (LIN + BREAK + SYNC + PID) OR
  (LIN bus + master + schedule) OR
  (Local Interconnect Network)

Applies LIN 2.2A canonical content to L1-L18 + L21.

Doctrine: structural-keyword detection IS general within an ic_class
(mirrors AMBA-AXI / SPI / I2C / UART / CAN synth approach). Any LIN-family
variant (LIN 1.x, LIN 2.0/2.1/2.2/2.2A, ISO 17987-1..-7) exhibits the same
signature — single master with multiple slaves, UART byte framing on a
single wire, BREAK + SYNC (0x55) + Protected Identifier (6+2 parity)
header, 1-8 data byte response + 8-bit inverted-sum-with-carry checksum,
schedule-table-driven slots, response_error status reporting, Go-To-Sleep
master-request (PID 0x3C, data1=0, data2..8=0xFF) + dominant-pulse wake-up.

Public entry: `apply_lin_synth(generated_docs_dir, is_lin, lin_ic_name)`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import l_doc_generator_stamp as _stamp
import _pack_top_module as _ptm  # L9.top_module: one decision, one provenance stamp


def _empty(v) -> bool:
    return v in (None, {}, []) or (isinstance(v, str) and not v.strip())


def _read(p: Path) -> dict:
    return json.loads(p.read_text())


def _write(p: Path, d: dict) -> None:
    # THE L-document write chokepoint: stamps the producing release onto
    # the document, then serialises it byte-identically to before.
    _stamp.dump(p, d)


def apply_lin_synth(generated_docs_dir: Path, is_lin: bool,
                    lin_ic_name: Optional[str]) -> None:
    """Apply LIN-specific synth when the structural signature matched."""
    if not is_lin:
        return
    gd = generated_docs_dir

    # Force ic_name across the 14 main L docs.
    if lin_ic_name is not None:
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
                d["ic_name"] = lin_ic_name
                _write(q, d)

    # ------------------------------------------------------------------ L1
    p = gd / "L1_DATASHEET.json"
    if p.is_file():
        d = _read(p)
        # Force-overwrite: UART (PC16550D) / CAN synths run before LIN and
        # populate these scalar fields with their own product identity. LIN
        # class is authoritative for an LIN-class spec.
        d["document_title"] = "LIN Specification Package"
        d["revision"] = "2.2A"
        d["revised_date"] = "December 31, 2010"
        d["manufacturer"] = "LIN Consortium"
        d["copyright"] = "© LIN Consortium, 2010"
        d.setdefault("website", "www.lin-subbus.org")
        d.setdefault("trademark_note",
                     "LIN is a registered Trademark ®. All rights reserved.")
        d.setdefault("document_layout", [
            "Specification Package — overall scope, glossary, history (sections 1.1-1.2).",
            "Protocol Specification — data-link-layer behaviour: signal mgmt, frame transfer, schedule tables, task behaviour, network/status mgmt (section 2).",
            "Transport Layer Specification — packet-/segment-level transport of up to 4095 bytes for diagnostics and node configuration (section 3).",
            "Node Configuration and Identification Specification — slave node model, NAD assignment, identification (section 4).",
            "Diagnostic Specification — Diagnostic Class I/II/III services on top of the transport layer (section 5).",
            "Physical Layer Specification — line driver / receiver / bit timing / EMC (section 6).",
            "Application Program Interface Specification — API between network and application (section 7).",
            "Configuration Language Specification — LIN Description File (LDF) format (section 8).",
            "Node Capability Language Specification — slave node capability file format (section 9).",
        ])
        d.setdefault("key_features", [
            "Single master with multiple slaves concept; master controls all bus timing.",
            "Low cost silicon implementation based on common UART/SCI interface hardware, an equivalent in software or as pure state machine.",
            "Self synchronization without a quartz or ceramic resonator in the slave nodes (slaves resync on every SYNC byte 0x55).",
            "Deterministic signal transmission with signal propagation time computable in advance (schedule-table driven).",
            "Low cost single-wire implementation (LIN bus line + VBAT + GND).",
            "Speed up to 20 kbit/s.",
            "Signal based application interaction (signals are scalars 1-16 bits or byte arrays 1-8 bytes).",
            "Predictable behaviour (no asynchronous bus contention; collisions only allowed on event-triggered frames).",
            "Reconfigurability — frame IDs / NAD reassignable by master via node configuration services.",
            "Transport layer and diagnostic support — up to 4095 bytes via segmented PDUs on IDs 0x3C / 0x3D.",
            "Physical layer based on the ISO 9141 standard with enhancements regarding EMI behaviour.",
            "Cost efficient bus communication where the bandwidth and versatility of CAN are not required.",
        ])
        d.setdefault("main_properties_of_LIN_bus_summary", [
            "single master with multiple slaves concept",
            "low cost silicon implementation based on common UART/SCI interface hardware, an equivalent in software or as pure state machine",
            "self synchronization without a quartz or ceramics resonator in the slave nodes",
            "deterministic signal transmission with signal propagation time computable in advance",
            "low cost single-wire implementation",
            "speed up to 20 kbit/s",
            "signal based application interaction",
            "predictable behavior",
            "reconfigurability",
            "transport layer and diagnostic support",
        ])
        d.setdefault("modes_of_operation", [
            {"name": "Initializing",   "description": "Instantaneously entered after first connection to power source, reset, or wakeup. Slave does LIN-related init. Init process must finish within 100 ms."},
            {"name": "Operational",    "description": "Normal LIN protocol behaviour (transmitting and receiving frames) applies only in this state."},
            {"name": "Bus sleep mode", "description": "Bus level is recessive; only the wake-up signal may be transmitted on the cluster. Entered after a Go-To-Sleep command or 4-10 s of bus inactivity."},
        ])
        d.setdefault("node_roles", [
            {"role": "master node", "description": "Contains a master task as well as a slave task. Master task transmits headers based on the schedule table; slave task may publish/subscribe like any slave."},
            {"role": "slave node",  "description": "Contains a slave task only. Provides the response (data + checksum) to headers it subscribes to or publishes."},
        ])
        d.setdefault("domain_of_application", [
            "Low cost automotive networks — door, seat, lighting, climate, sensor / actuator clusters.",
            "Complements existing CAN networks in a hierarchical vehicle network where the bandwidth and versatility of CAN are not required.",
            "Replacement of legacy low-end multiplex wiring with a standardised serial bus.",
        ])
        d.setdefault("layered_structure", [
            {"layer": "Application",    "scope": "The user logic of the node; not standardised by LIN protocol spec."},
            {"layer": "API",            "scope": "Signal interaction layer + Transport Layer (TL); see Application Program Interface Specification."},
            {"layer": "Protocol",       "scope": "Frame handler — break/sync/PID/data/checksum framing, schedule, error/status mgmt."},
            {"layer": "Physical (PHY)", "scope": "LIN bus line — single wire, dominant/recessive, based on ISO 9141; covered by Physical Layer Specification."},
        ])
        d["overview"] = (
            "LIN (Local Interconnect Network) is a concept for low cost automotive networks, which complements the existing portfolio of automotive multiplex networks. LIN promotes the interoperability of network nodes from the viewpoint of hardware and software and a predictable EMC behaviour. The LIN is a serial communications protocol which efficiently supports the control of mechatronics nodes in distributed automotive applications. The specification is intended to achieve compatibility between any two LIN implementations with respect to the scope of the standard, i.e. from the application interface (API) all the way down to the physical layer.")
        d.setdefault("history_summary", [
            {"version": "LIN 1.0",  "year": "1999-07-01", "remark": "Initial Version of the LIN Specification. Heavily influenced by the VLITE bus used by some automotive companies."},
            {"version": "LIN 1.1",  "year": "2000-03-06", "remark": "Minor update."},
            {"version": "LIN 1.2",  "year": "2000-11-17", "remark": "Updated standard."},
            {"version": "LIN 1.3",  "year": "2002-12-13", "remark": "Mainly physical-layer changes for improved compatibility between nodes."},
            {"version": "LIN 2.0",  "year": "2003-09-16", "remark": "Major Revision Step. Reworked spec; standardised configuration/diagnostics and Node Capability files."},
            {"version": "LIN 2.1",  "year": "2006-11-24", "remark": "Clarifications, configuration modified, transport layer enhanced and diagnostics added."},
            {"version": "LIN 2.2",  "year": "2010-12-31", "remark": "Updated document according to LIN 2.1 Errata sheet 1.4. Softened bit sampling specification."},
            {"version": "LIN 2.2A", "year": "2010-12-31", "remark": "Corrected wakeup signal definition in chapter 2.6.2 (this document)."},
        ])
        d.setdefault("external_pins_overview", [
            "LIN bus line — single-wire bidirectional bus shared by master + slaves; dominant = 0, recessive = 1.",
            "VBAT — battery supply to nodes (typ. 12 V automotive).",
            "GND — common ground reference.",
        ])
        d.setdefault("external_pin_count_protocol_view", 3)
        d["package"] = (
            "Not specified — LIN is a protocol standard; physical packages are vendor / transceiver specific (e.g. LIN transceiver IC + microcontroller with UART/SCI).")
        _write(p, d)

    # ------------------------------------------------------------------ L2
    p = gd / "L2_FRS.json"
    if p.is_file():
        d = _read(p)
        po = d.setdefault("protocol_overview", {})
        if isinstance(po, dict):
            # Force-overwrite: UART (PC16550D) / CAN synths fill protocol_overview
            # with their own semantics (UART = full-duplex / async; CAN =
            # multi-master / bitwise arbitration). For an LIN-class spec we are
            # authoritative — overwrite the contested subkeys.
            po["type"] = "Single-master / multiple-slave serial bus on a single wire (LIN bus line), UART/SCI byte-framed."
            po["duplex"] = "half-duplex on the shared single-wire bus"
            po.setdefault("synchronous", False)
            po["bus_arbitration"] = (
                "No arbitration — master controls all timing. Collisions are possible only on event-triggered frames and are resolved by switching to a collision-resolving schedule table.")
            po["bit_coding"] = (
                "UART byte fields (start bit dominant + 8 data bits LSB-first + stop bit recessive). Break field does not comply with UART byte framing; it is ≥13 dominant nominal bit times + ≥1 recessive bit time break delimiter.")
            po.setdefault("bus_values",
                "Two complementary logical values: dominant (typically logical 0) and recessive (typically logical 1). Wired-AND: dominant wins.")
            po["multimaster"] = False
            po.setdefault("multicast", True)
            po.setdefault("addressing",
                "Frame addressing is by 6-bit frame IDENTIFIER (0..63); content-addressed (the IDENTIFIER names the meaning of the data, not the destination). Diagnostic addressing uses NAD (Node Address) inside the data field of master-request / slave-response frames.")
            po.setdefault("max_speed_kbit_s", 20)
            po.setdefault("max_nodes_in_cluster_typical",
                "single master + up to ~16 slaves (LDF-constrained, not protocol-hardcoded)")
            po.setdefault("physical_layer_reference",
                "ISO 9141 with EMI enhancements")
        fr = [
            {"id": "FR-FRAME-01",   "text": "A frame consists of a header (provided by the master task) and a response (provided by a slave task). The header = Break field + Sync byte field + Protected Identifier field. The response = 1..8 Data bytes + Checksum byte."},
            {"id": "FR-BREAK-02",   "text": "Break field is at least 13 nominal dominant bit times followed by a Break Delimiter of at least 1 recessive nominal bit time. It is the only field that does not comply with the standard UART byte-field structure."},
            {"id": "FR-BRK-DET-03", "text": "A slave shall use a break detection threshold of 11 dominant local slave bit times; slaves with bit-rate tolerance better than F_TOL_RES_SLAVE may use 9.5 dominant nominal bit times."},
            {"id": "FR-SYNC-04",    "text": "Sync byte field is a byte field with data value 0x55. Its alternating edges allow slaves without a precision time base to measure the master's nominal bit time and resynchronise the slave UART."},
            {"id": "FR-PID-05",     "text": "The Protected Identifier (PID) byte field carries the 6-bit frame identifier (ID0..ID5, bits 0..5) plus 2 parity bits (P0 = bit 6, P1 = bit 7). P0 = ID0 ⊕ ID1 ⊕ ID2 ⊕ ID4. P1 = ¬(ID1 ⊕ ID3 ⊕ ID4 ⊕ ID5)."},
            {"id": "FR-ID-RANGE-06","text": "6-bit ID range 0..63. IDs 0..59 (0x00..0x3B) are signal-carrying frames; ID 60 (0x3C) = Master Request diagnostic; ID 61 (0x3D) = Slave Response diagnostic; ID 62 (0x3E) and 63 (0x3F) are reserved for future LIN extended format."},
            {"id": "FR-DATA-07",    "text": "A frame carries between 1 and 8 bytes of data. Each data byte is transmitted as a UART byte field (start + 8 LSB-first data + stop). For multi-byte entities, the entity LSB is in the byte sent first (little-endian)."},
            {"id": "FR-CHK-CLA-08", "text": "Classic checksum = inverted 8-bit sum-with-carry over all data bytes only. Used for diagnostic frames (IDs 0x3C and 0x3D) and for communication with LIN 1.x slaves."},
            {"id": "FR-CHK-ENH-09", "text": "Enhanced checksum = inverted 8-bit sum-with-carry over Protected Identifier + all data bytes. Used for communication with LIN 2.x slaves on non-diagnostic frames. Choice of classic vs enhanced is per frame ID, managed by the master."},
            {"id": "FR-FRAMETYPES-10","text": "Frame types: Unconditional (IDs 0..59 signal carrying), Event-Triggered (response only when a publisher has new data; collisions possible), Sporadic (master-published, transmitted only when a signal in the associated frame is updated), Diagnostic (IDs 0x3C master request / 0x3D slave response — always 8 data bytes; classic checksum), Reserved (IDs 0x3E / 0x3F — shall not be used in LIN 2.x clusters)."},
            {"id": "FR-SCHED-11",   "text": "The master task transmits headers based on a schedule table. The schedule table specifies the frames and the inter-slot intervals (each slot = an integer multiple of the time base T_base, typically 5 or 10 ms). Active schedule is processed cyclically until another schedule is requested; schedule switches only at frame slot boundaries."},
            {"id": "FR-TIMING-12",  "text": "T_Header_Nominal = 34 × T_Bit. T_Response_Nominal = 10 × (N_Data + 1) × T_Bit. T_Frame_Nominal = T_Header_Nominal + T_Response_Nominal. Maximum lengths are 1.4 × nominal (40% inter-byte slack)."},
            {"id": "FR-WAKE-13",    "text": "Wake-up signal: any node in a sleeping cluster may force the bus dominant for 250 µs to 5 ms (followed by return to recessive). Slaves detect a wake-up by observing a dominant pulse longer than 150 µs; slaves shall be ready to listen within 100 ms after the ending edge of the dominant pulse."},
            {"id": "FR-SLEEP-14",   "text": "Master sets the cluster into bus sleep mode by transmitting a Go-To-Sleep command — a master-request frame (ID=0x3C) with data1=0 and data2..data8=0xFF. Slaves shall automatically enter bus sleep mode after 4..10 s of bus inactivity even if the master never sent the command."},
            {"id": "FR-RESPERR-15", "text": "Each slave shall publish a one-bit scalar signal response_error in one of its transmitted unconditional frames. response_error is set whenever a non-event-triggered frame transmitted or received by the slave contains an error in the response. It is cleared once the unconditional frame carrying response_error is successfully transmitted."},
            {"id": "FR-NODECFG-16", "text": "Slave nodes are configured / identified via master-request / slave-response diagnostic frames (IDs 0x3C/0x3D) using the LIN node configuration services: Assign NAD, Conditional Change NAD, Data Dump, Save Configuration, Assign frame ID range, Read by identifier."},
            {"id": "FR-TRANSPORT-17","text": "Transport layer is used for node configuration, identification, and diagnostics. PDUs are 8-byte fixed-length and may be Single Frame (SF) or Multi-Frame (FF + CF) carrying up to 4095 bytes total."},
        ]
        if _empty(d.get("functional_requirements")):
            d["functional_requirements"] = fr
        d.setdefault("error_response_conditions", [
            "Framing error on a byte field — start/stop bit not as expected.",
            "Bit error in transmitted byte — slave's UART readback ≠ transmitted bit; transmission shall be aborted no later than the end of the byte field containing the mismatch (master also performs this readback check).",
            "Checksum error — received checksum does not match the locally computed sum.",
            "Unknown PID — received PID has no matching frame in the local node's frame table.",
            "Parity error in PID — computed P0/P1 ≠ received P0/P1.",
            "No response — master transmitted a header but no slave responded within T_Frame_Maximum.",
            "Last frame response too short — the last frame contained at least one field (correct byte or framing error) but ended prematurely.",
            "Collision on an event-triggered frame — handled by switching the active schedule to the associated collision-resolving schedule table.",
        ])
        if _empty(d.get("compliance_requirements")):
            d["compliance_requirements"] = [
                "Implementations must be compatible at the protocol level — header + response framing, PID parity equations, checksum models, and schedule-table-driven slot timing must match the spec exactly.",
                "LIN 2.2A is a superset of LIN 1.3 at the protocol level — LIN 1.3 slaves may coexist in a LIN 2.x cluster, but they will not support enhanced checksum, reconfiguration & diagnostics, automatic baud-rate detection, or response_error signal monitoring.",
                "LIN 2.2A physical layer is backwards compatible with LIN 1.3 physical layer; the reverse is not guaranteed (LIN 2.2A sets harder requirements).",
                "Bus values: dominant must override recessive on simultaneous transmission (wired-AND).",
                "All bits not used/defined in a frame shall be recessive (ones).",
                "Frame identifier 0x3C and 0x3D shall always use classic checksum.",
                "Frame identifiers 0x3E and 0x3F shall not be used in a LIN 2.x cluster (reserved for future LIN extended format).",
            ]
        _write(p, d)

    # ------------------------------------------------------------------ L3
    p = gd / "L3_CMD_PROTOCOL.json"
    if p.is_file():
        d = _read(p)
        # Force-overwrite: UART (PC16550D) synth seeds protocol_type with its
        # register-mapped UART semantics; LIN class is authoritative.
        d["protocol_type"] = (
            "Single-master schedule-table-driven serial bus on a single wire (LIN bus line). Each frame = header from master + response from one publishing slave. Byte-oriented (UART framing on each non-break byte).")
        d.setdefault("frame_structure", {
            "header_fields": ["Break field", "Sync byte field (0x55)",
                              "Protected Identifier (PID) byte field"],
            "response_fields": ["1..8 Data byte fields", "Checksum byte field"],
            "byte_field_format": {
                "start_bit": "1 bit dominant (logical 0).",
                "data_bits": "8 bits LSB-first.",
                "stop_bit":  "1 bit recessive (logical 1).",
            },
            "break_field": {
                "min_dominant_bits":                          13,
                "break_delimiter_min_recessive_bits":         1,
                "slave_detection_threshold_bits":             11,
                "slave_detection_threshold_bits_better_tolerance": 9.5,
                "note": "Break is the only field that does not comply with the UART byte-field structure. A break/sync sequence shall always be detectable by slave tasks; an in-progress frame shall be aborted and processing of the new frame shall commence on a break/sync detection.",
            },
            "sync_byte_value_hex": "0x55",
            "sync_byte_purpose":
                "Slaves without a precise time base measure the alternating edges of 0x55 to compute the master's nominal bit time and resynchronise their UART.",
        })
        d.setdefault("protected_identifier", {
            "id_bits": "ID0..ID5 = bits 0..5 of PID byte (LSB first).",
            "parity_bits": "P0 = bit 6, P1 = bit 7.",
            "P0_equation": "P0 = ID0 ⊕ ID1 ⊕ ID2 ⊕ ID4",
            "P1_equation": "P1 = ¬(ID1 ⊕ ID3 ⊕ ID4 ⊕ ID5)",
            "id_range": "0..63 (6 bits)",
            "id_categories": [
                {"range": "0x00..0x3B (0..59)",   "name": "Signal-carrying frames",          "checksum": "classic for LIN 1.x slaves, enhanced for LIN 2.x slaves"},
                {"range": "0x3C (60)",            "name": "Master Request diagnostic frame", "checksum": "classic (always)"},
                {"range": "0x3D (61)",            "name": "Slave Response diagnostic frame", "checksum": "classic (always)"},
                {"range": "0x3E (62), 0x3F (63)", "name": "Reserved (LIN extended format)",  "checksum": "shall not be used in a LIN 2.x cluster"},
            ],
        })
        d.setdefault("frame_types", [
            {"name": "Unconditional frame",   "description": "IDs 0..59. Always transmitted when its slot is processed. Single publisher, one-or-many subscribers."},
            {"name": "Event-triggered frame", "description": "Designed to increase responsiveness without high polling overhead. Multiple slaves may publish associated unconditional frames; the first data byte of each associated unconditional frame must equal its PID. Collisions are allowed and resolved by switching to a collision-resolving schedule table."},
            {"name": "Sporadic frame",        "description": "Group of unconditional frames sharing one slot. Master publishes only if a signal in one of the associated frames has been updated; otherwise the slot is silent."},
            {"name": "Diagnostic frame",      "description": "IDs 0x3C (master request) and 0x3D (slave response). Always 8 data bytes. Carry transport-layer PDUs for node configuration / identification / diagnostics. Always classic checksum."},
            {"name": "Reserved frame",        "description": "IDs 0x3E and 0x3F. Shall not be used in LIN 2.x clusters."},
        ])
        d.setdefault("checksum_models", [
            {"name": "classic",  "covers": "data bytes only",
             "applies_to": "Diagnostic frames (0x3C, 0x3D) and frames going to LIN 1.x slaves."},
            {"name": "enhanced", "covers": "Protected Identifier + data bytes",
             "applies_to": "Frames going to LIN 2.x slaves (non-diagnostic)."},
        ])
        d.setdefault("checksum_algorithm",
            "Eight-bit sum with carry, then bit-inverted: sum all bytes; whenever sum ≥ 256 subtract 255 (equivalent to add-with-carry); finally invert the 8-bit result. Receiver adds the received checksum to its intermediate sum; result shall be 0xFF.")
        d.setdefault("checksum_example_from_spec", {
            "data_bytes_hex": ["0x4A", "0x55", "0x93", "0xE5"],
            "intermediate_sum_hex": "0x19",
            "inverted_checksum_hex": "0xE6",
            "verification": "0x19 + 0xE6 = 0xFF",
        })
        d.setdefault("schedule_table", {
            "owner":             "master node (master task)",
            "T_base_typical_ms": [5, 10],
            "frame_slot_definition":
                "T_Frame_Slot = T_base × n (n integer, normally different per slot). Slot must satisfy T_Frame_Slot > jitter + T_Frame_Maximum.",
            "switch_behaviour":
                "Active schedule processed cyclically. Switch request to new schedule is honoured only at the start of the next frame slot — never mid-frame.",
            "go_to_sleep_command_data_bytes":
                ["0x00", "0xFF", "0xFF", "0xFF", "0xFF", "0xFF", "0xFF", "0xFF"],
        })
        d.setdefault("wake_sleep", {
            "wake_up_dominant_pulse_min_us":   250,
            "wake_up_dominant_pulse_max_ms":   5,
            "slave_wake_detection_threshold_us_min": 150,
            "slave_ready_window_after_wake_ms_max":  100,
            "wake_retry_silence_between_signals_ms_min": 150,
            "wake_retry_silence_between_signals_ms_max": 250,
            "wake_retry_silence_after_3_attempts_s_min": 1.5,
            "bus_inactivity_to_sleep_s_min": 4,
            "bus_inactivity_to_sleep_s_max": 10,
        })
        d.setdefault("valid_ready_handshake_rules", [
            "There is no per-byte VALID/READY handshake on the LIN wire.",
            "Master fully owns timing: it issues each header at the time-base tick scheduled in the active schedule table.",
            "A slave's response is implicitly authorised by receipt of a header whose PID it publishes; subscribers simply receive and validate the checksum.",
        ])
        d["byte_oriented"] = True
        d["burst_based"] = False
        d.setdefault("host_interface_assumption",
            "On a node, the LIN protocol is implemented on top of a UART/SCI peripheral or equivalent state machine. There is no LIN-defined CPU host-bus register interface — that is vendor-specific (e.g. LIN transceiver IC + microcontroller UART).")
        _write(p, d)

    # ------------------------------------------------------------------ L4
    p = gd / "L4_REGMAP.json"
    if p.is_file():
        d = _read(p)
        d["register_map_present"] = False
        d.setdefault("rationale",
            "LIN is a wire-level protocol specification, not a chip. The spec does not define a host-CPU register map. Implementations build on top of an existing UART/SCI peripheral (or a pure state machine) on a microcontroller; the register map at that level is vendor-specific (e.g. NXP / Renesas / Microchip / TI LIN-capable UARTs).")
        d.setdefault("implementation_register_groups_required_at_node_level", [
            "UART/SCI: baud-rate divisor, parity = none, data bits = 8, stop bits = 1, LSB-first.",
            "Break generator / detector: ≥13 bit-time dominant TX break; ≥11 bit-time dominant RX detect threshold.",
            "Schedule table memory (master only): a list of (slot_index, frame_id, slot_duration, type) entries.",
            "Frame table (master + slave): per-frame entry { ID, direction (publish/subscribe), length, checksum model, callback }.",
            "NAD register (slave only): initial NAD (from LDF) + current NAD assignable via Assign NAD service.",
            "Supplier ID, Function ID, Variant (slave only): published in Read by Identifier service.",
            "Status / response_error register (slave): 1-bit signal published in one of the slave's unconditional frames; set on any non-event-triggered frame response error.",
        ])
        d.setdefault("data_field_constants", {
            "go_to_sleep_data_byte_count":      8,
            "go_to_sleep_data1_value_hex":      "0x00",
            "go_to_sleep_data2_to_data8_value_hex": "0xFF",
        })
        d.setdefault("diagnostic_pdu_layout", {
            "pdu_byte_count": 8,
            "byte0": "NAD (Node Address for Diagnostics)",
            "byte1": "PCI (Protocol Control Information): bits 7:4 = PDU type code (SF=0x0, FF=0x1, CF=0x2), bits 3:0 = length (SF) or sequence number (CF) or upper nibble of length (FF).",
            "byte2_if_SF_or_FF": "SF: LEN (1..6); FF: lower 8 bits of total LEN (LEN 7..4095).",
            "byte3_if_SF": "SID (Service Identifier)",
            "byte4_to_byte7_if_SF": "D1..D5 service data (last bytes padded 0xFF if unused)",
            "byte3_to_byte7_if_FF": "D1..D5 service data (first chunk)",
            "byte2_to_byte7_if_CF": "D1..D6 service data (next 6 bytes)",
        })
        d["notes"] = ("Where this Phase-1 LRM expects 'registers', the LIN "
                      "protocol provides 'fields and tables'. The "
                      "register-level mapping is left to the implementer.")
        _write(p, d)

    # ------------------------------------------------------------------ L5
    p = gd / "L5_ADI_SPEC.json"
    if p.is_file():
        d = _read(p)
        # Force-overwrite: UART/CAN synths default analog_digital_interface_present
        # to False (CAN/UART are digital-only above the PHY); LIN has explicit
        # dominant/recessive voltage thresholds in the Physical Layer Spec.
        d["analog_digital_interface_present"] = True
        d["notes"] = (
            "Bit-level analog details (thresholds VBUSdom_min/max, VBUSrec_min, slew rates, leakage, EMC) are defined in the LIN Physical Layer Specification (section 6 of the LIN Specification Package) and not duplicated in the protocol body of this document. Implementers should refer to the Physical Layer Specification for the absolute analog signoff numbers.")
        d["signaling_summary"] = (
            "LIN bus is a single-wire automotive serial bus. Two complementary "
            "logical bus values: dominant (typically interpreted as logic 0; "
            "low voltage / current sink to GND through the transceiver) and "
            "recessive (typically interpreted as logic 1; pulled toward VBAT "
            "through a termination resistor). The bus is open-drain / "
            "wired-AND so multiple drivers concurrently asserting recessive "
            "produce recessive while any single driver asserting dominant "
            "pulls the bus dominant. The line driver / receiver "
            "characteristics are defined in the LIN Physical Layer "
            "Specification (section 6) and are based on the ISO 9141 "
            "standard with enhancements regarding EMI behaviour.")
        d.setdefault("physical_layer_reference", "ISO 9141 (with EMI enhancements)")
        d.setdefault("termination",
            "Master node typically contains a 1 kΩ termination resistor to VBAT; slave nodes typically contain a 30 kΩ termination resistor to VBAT (vendor / transceiver dependent; defined in section 6 of the LIN spec).")
        d.setdefault("supply_voltage_range",
            "Automotive 12 V battery rail (VBAT). The Physical Layer Specification (section 6) defines absolute limits, dominant/recessive voltage thresholds, slew rate, leakage, EMC behaviour.")
        d.setdefault("max_bit_rate_kbit_s", 20)
        d.setdefault("min_bit_rate_kbit_s", 1)
        d.setdefault("logic_levels_summary", {
            "dominant":  "Bus pulled toward GND by an active transceiver. Logical 0.",
            "recessive": "Bus relaxed toward VBAT via pull-up termination. Logical 1.",
        })
        _write(p, d)

    # ------------------------------------------------------------------ L6
    p = gd / "L6_CONTROL_LOGIC.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("fsm_states_master_task", [
            {"name": "Idle",  "description": "No frame scheduled. Wait for the next schedule-table tick whose slot is due for transportation."},
            {"name": "Break", "description": "Send Break field (≥13 dominant nominal bit times + ≥1 recessive bit Break Delimiter)."},
            {"name": "Sync",  "description": "Send Sync byte field (0x55) as a UART byte field."},
            {"name": "PID",   "description": "Send Protected Identifier byte field (ID0..ID5 + P0 + P1). After PID is sent, transition back to Idle to await next slot (master may simultaneously act as slave-task publisher/subscriber on its own slave task)."},
        ])
        d.setdefault("fsm_states_slave_task_processor", [
            {"name": "Idle",                "description": "Receive break and sync. Wait for break/sync field sequence."},
            {"name": "Active.PID",          "description": "Receive PID byte. If unknown PID or framing error → Quit (back to Idle). Else dispatch by PID role."},
            {"name": "Active.RxData",       "description": "Receive each data byte. On framing error → Error. After all data bytes received → RxChecksum."},
            {"name": "Active.RxChecksum",   "description": "Receive checksum byte. If checksum valid → Success. If invalid or framing error → Error."},
            {"name": "Active.TxData",       "description": "Transmit each data byte; perform UART readback. If readback ≠ sent → Error. After all bytes sent → TxChecksum."},
            {"name": "Active.TxChecksum",   "description": "Transmit checksum byte with readback. If readback correct → Success. Else → Error."},
            {"name": "Success",             "description": "Successful_transfer flag set. Return to Idle."},
            {"name": "Error",                "description": "Error_in_response flag set; response_error signal set on next status-carrying unconditional frame. Return to Idle."},
            {"name": "Quit (unknown PID / no role)", "description": "Slave is not publisher nor subscriber of this PID — no further action this slot."},
        ])
        # Force-overwrite: UART (PC16550D) synth populates fsm_hints with its
        # own TX/RX trigger semantics. Replace with LIN frame-handler semantics.
        d["fsm_hints"] = {
            "trigger":          "A break/sync field sequence detected at any time aborts any in-progress slave activity and forces the slave into Active.PID processing for the new frame.",
            "abort_conditions": "Detection of a new break/sync sequence; framing error on any received byte; bit error (TX readback mismatch); checksum mismatch; ID parity mismatch; T_Frame_Maximum exceeded.",
            "oversampling":     "Slaves without a precise time base use the alternating edges of the Sync byte (0x55) to measure the master's nominal bit time, then sample subsequent bytes at the centre of each measured bit.",
        }
        d.setdefault("network_management_state_machine_slave_node", [
            {"state": "Initializing",   "entry":    "First connection to power source, reset, or wakeup.",
                                         "duration": "Init process must finish within 100 ms.",
                                         "exit":     "Transition to Operational."},
            {"state": "Operational",    "behaviour":"LIN protocol (TX/RX of frames) applies only in this state.",
                                         "exit":     "Go-to-sleep request received OR bus inactive for 4 to 10 s → Bus sleep mode."},
            {"state": "Bus sleep mode", "behaviour":"Bus level is recessive; only the wake-up signal may be transmitted on the cluster.",
                                         "exit":     "Wake-up signal received OR internal reason to wake up the cluster → Initializing."},
        ])
        d.setdefault("wake_up_protocol", {
            "wake_signal_generation":   "Any node forces the bus dominant for 250 µs to 5 ms, then releases to recessive.",
            "slave_wake_detection":     "Dominant pulse > 150 µs followed by rising edge.",
            "slave_ready_window_ms_max": 100,
            "retry_protocol":           "If wake-up not acknowledged (no break from master in 150-250 ms), node may retransmit wake signal. After 3 failed attempts a node shall wait at least 1.5 s before issuing a 4th wake signal.",
            "block_pattern":            "One block of up to 3 wake signals separated by 150-250 ms; ≥ 1.5 s pause between blocks (recommended).",
        })
        d.setdefault("go_to_sleep_protocol", {
            "command_pid":      "0x3C (Master Request diagnostic frame, classic checksum)",
            "data1":            "0x00",
            "data2_to_data8":   "0xFF",
            "slave_action":     "Slaves shall interpret only the first data field; data2..data8 = 0xFF are ignored. The request need not enforce the slave application into low-power mode (application-specific).",
            "automatic_sleep":  "Slave automatically enters bus sleep mode after 4..10 s of bus inactivity even without an explicit Go-To-Sleep command.",
        })
        # Force-overwrite: UART synth seeds default_ready_state_recommendation
        # with SOUT/SIN/Modem semantics; LIN has bus/master/slave semantics.
        d["default_ready_state_recommendation"] = {
            "bus_idle":           "Recessive (logical 1).",
            "master_after_reset": "Begin schedule processing only after the slave initialisation window has elapsed.",
            "slave_after_reset":  "Initializing state; LIN protocol behaviour does not apply until Operational entered (≤ 100 ms).",
        }
        d["anti_deadlock_rule"] = (
            "Bus arbitration does not exist on LIN; deadlock prevention is by single-master control of timing + collision-resolving schedule tables for event-triggered frames. Any break/sync at any time forces all slaves to abort and restart frame processing — there is no held-bus state that could deadlock a node.")
        _write(p, d)

    # ------------------------------------------------------------------ L7
    p = gd / "L7_TEST_DEBUG.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("test_debug_architecture_present", True)
        d.setdefault("test_debug_features", [
            "response_error signal — 1-bit scalar published by every slave in one of its transmitted unconditional frames. Set on any non-event-triggered frame response error; cleared once the carrying unconditional frame is successfully transmitted. Allows the master to detect intermittent slave problems.",
            "Error_in_response status bit (within own node) — set whenever a frame received or transmitted by the node contains an error in the response.",
            "Successful_transfer status bit (within own node) — set whenever a frame has been successfully transferred (received or transmitted).",
            "Bus analyzer / emulator hooked into the cluster via the LIN Description File (LDF) — standardised LDF allows tooling to decode frames, log signals, emulate missing slaves.",
            "Diagnostic Class I / II / III services on the transport layer (IDs 0x3C / 0x3D) — read DTC, clear DTC, ECU identification, etc.",
            "Read by Identifier service (sid = 0xB2) — returns Supplier ID + Function ID + Variant + ECU-specific identifiers.",
        ])
        d.setdefault("spec_provided_observability", [
            {"name": "response_error",           "purpose": "Cluster-wide: master detects slaves that have intermittent response problems."},
            {"name": "Error_in_response (own)",  "purpose": "Node-internal: any response-field error in this slot."},
            {"name": "Successful_transfer (own)","purpose": "Node-internal: this slot completed cleanly."},
            {"name": "Last frame PID (own)",     "purpose": "Node tracks the PID of the last frame it processed."},
        ])
        d.setdefault("response_error_truth_table", [
            {"response_error_value": "false",                        "interpretation": "the slave node is operating correctly"},
            {"response_error_value": "true",                         "interpretation": "the slave node has intermittent problems"},
            {"response_error_value": "the slave node did not answer","interpretation": "the slave node, bus or master node has serious problems"},
        ])
        d.setdefault("interrupt_sources_node_level", [
            {"trigger": "Break/sync field sequence detected",           "purpose": "Synchronise UART to master's bit time; reset slave frame processor."},
            {"trigger": "Full byte received in UART",                   "purpose": "Pull byte; if part of a frame body process; if standalone outside Active state ignore."},
            {"trigger": "PID matches local subscribe role",             "purpose": "Begin RX data + checksum collection."},
            {"trigger": "PID matches local publish role",               "purpose": "Begin TX data + checksum emission."},
            {"trigger": "Frame slot complete / T_Frame_Maximum elapsed","purpose": "Update Successful_transfer or Error_in_response; possibly clear response_error."},
            {"trigger": "Bus inactivity 4..10 s",                       "purpose": "Auto-enter Bus sleep mode."},
            {"trigger": "Wake-up dominant pulse > 150 µs detected",     "purpose": "Exit Bus sleep mode → Initializing → Operational."},
        ])
        d.setdefault("interrupt_request_summary",
            "LIN does not define a hardware INTR line at the protocol level — interrupts are entirely vendor-microcontroller-side (UART RX, UART TX, timer for slot boundaries, transceiver wake pin).")
        # Force-overwrite: UART synth seeds notes with PC16550D historical
        # narrative; LIN notes are protocol-level.
        d["notes"] = (
            "LIN is intentionally designed so that a single-bit response_error signal suffices to perform a conformance test of the frame transceiver (the protocol engine) independent of the application and the signal interaction layer (section 2.7.3).")
        _write(p, d)

    # ------------------------------------------------------------------ L8 RTL constants
    p = gd / "L8_RTL_CONSTANTS.json"
    if p.is_file():
        d = _read(p)
        wp = d.setdefault("width_parameters", {})
        if isinstance(wp, dict):
            for k, v in {
                "FRAME_ID_WIDTH_bits": 6,
                "PARITY_WIDTH_bits": 2,
                "PID_BYTE_WIDTH_bits": 8,
                "SYNC_BYTE_WIDTH_bits": 8,
                "DATA_BYTE_WIDTH_bits": 8,
                "CHECKSUM_BYTE_WIDTH_bits": 8,
                "DATA_BYTES_PER_FRAME_min": 1,
                "DATA_BYTES_PER_FRAME_max": 8,
                "BREAK_MIN_DOMINANT_bits": 13,
                "BREAK_DELIMITER_MIN_RECESSIVE_bits": 1,
                "BREAK_DETECT_THRESHOLD_bits": 11,
                "BREAK_DETECT_THRESHOLD_BETTER_TOLERANCE_bits": 9.5,
                "UART_START_BITS": 1,
                "UART_STOP_BITS": 1,
                "UART_DATA_BITS": 8,
                "UART_PARITY_BITS": 0,
                "TRANSPORT_PDU_BYTES": 8,
                "TRANSPORT_MAX_PAYLOAD_BYTES": 4095,
                "SCALAR_SIGNAL_WIDTH_BITS_min": 1,
                "SCALAR_SIGNAL_WIDTH_BITS_max": 16,
                "BYTE_ARRAY_SIGNAL_SIZE_BYTES_min": 1,
                "BYTE_ARRAY_SIGNAL_SIZE_BYTES_max": 8,
                "NAD_BYTE_WIDTH_bits": 8,
            }.items():
                wp.setdefault(k, v)
        # Force-overwrite: UART (PC16550D) / CAN synths populate clock_constants
        # and key_constants_for_RTL_authoring with their own product values.
        # LIN class is authoritative for an LIN-class spec.
        d["clock_constants"] = {
            "max_bit_rate_kbit_s":          20,
            "T_Bit_min_us_at_20kbit_s":     50,
            "T_Header_Nominal_TBit":        34,
            "T_Response_Nominal_TBit_formula":   "10 × (N_Data + 1)",
            "T_Frame_Nominal_TBit_formula":      "T_Header_Nominal + T_Response_Nominal",
            "T_Header_Maximum_factor_over_nominal":   1.4,
            "T_Response_Maximum_factor_over_nominal": 1.4,
            "T_Frame_Maximum_formula":      "T_Header_Maximum + T_Response_Maximum",
            "T_base_typical_ms":            [5, 10],
            "T_Frame_Slot_constraint":      "T_Frame_Slot > jitter + T_Frame_Maximum; T_Frame_Slot = T_base × n",
        }
        d["key_constants_for_RTL_authoring"] = {
            "bus_dominant_value":           0,
            "bus_recessive_value":          1,
            "idle_bus_value":               1,
            "uart_lsb_first_data_order":    True,
            "sync_byte_value_hex":          "0x55",
            "go_to_sleep_id_hex":           "0x3C",
            "master_request_id_hex":        "0x3C",
            "slave_response_id_hex":        "0x3D",
            "reserved_ids_hex":             ["0x3E", "0x3F"],
            "go_to_sleep_data_bytes_hex":   ["0x00", "0xFF", "0xFF", "0xFF",
                                             "0xFF", "0xFF", "0xFF", "0xFF"],
            "diagnostic_frame_data_byte_count": 8,
            "diagnostic_frame_checksum_model":  "classic",
            "P0_equation": "P0 = ID0 ⊕ ID1 ⊕ ID2 ⊕ ID4",
            "P1_equation": "P1 = NOT (ID1 ⊕ ID3 ⊕ ID4 ⊕ ID5)",
            "checksum_algorithm":
                "inverted 8-bit sum-with-carry; classic over data bytes only; enhanced over PID + data bytes",
            "checksum_classic_applies_to_ids_hex":    ["0x3C", "0x3D"],
            "wake_up_dominant_pulse_min_us":          250,
            "wake_up_dominant_pulse_max_ms":          5,
            "slave_wake_detection_threshold_us":      150,
            "slave_init_max_ms":                      100,
            "bus_inactivity_min_to_sleep_s":          4,
            "bus_inactivity_max_to_sleep_s":          10,
            "wake_retry_silence_min_ms":              150,
            "wake_retry_silence_max_ms":              250,
            "wake_retry_silence_after_3_attempts_min_s": 1.5,
            "all_undefined_bits_value":               1,
        }
        # Force-overwrite: UART/CAN synths seed default_signal_values_after_reset
        # with their own bus / pin idle semantics.
        d["default_signal_values_after_reset"] = {
            "lin_bus_line":           "recessive (HIGH / logical 1)",
            "master_outputs_after_reset":
                "recessive; no frame issued until first scheduled slot",
            "slave_outputs_after_reset":
                "recessive; slave in Initializing state for ≤ 100 ms before entering Operational",
            "response_error_signal_after_reset":
                "implementation-defined initial value (typically 0 = no error)",
        }
        d.setdefault("frame_field_lengths_summary_TBit", {
            "break_field_min":              13,
            "break_delimiter_min":          1,
            "sync_byte":                    10,
            "pid_byte":                     10,
            "each_data_byte":               10,
            "checksum_byte":                10,
            "header_nominal_total":         34,
            "response_nominal_total_formula_TBit": "10 × (N_Data + 1)",
        })
        _write(p, d)

    # ------------------------------------------------------------------ L8 timing
    p = gd / "L8_TIMING_WAVEFORM.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("frame_waveform_layout", [
            "Break field (≥13 dominant nominal bit times) + Break Delimiter (≥1 recessive nominal bit time)",
            "Sync byte field — UART byte field carrying data value 0x55 (start + LSB 1 0 1 0 1 0 1 0 + stop = alternating edges for slave bit-time measurement)",
            "Protected Identifier field — UART byte field {ID0..ID5, P0, P1}",
            "Inter-byte space (≥ 0) — between PID and Data 1, and between consecutive Data bytes",
            "Data 1 .. Data N — N = 1..8, each transmitted as a UART byte field, LSB first",
            "Checksum field — UART byte field carrying classic or enhanced checksum",
        ])
        d.setdefault("uart_byte_field_layout", {
            "start_bit":  "1 nominal bit, dominant (logical 0)",
            "data_bits":  "8 bits LSB-first",
            "stop_bit":   "1 nominal bit, recessive (logical 1)",
            "total_TBit": 10,
        })
        d.setdefault("break_field_timing", {
            "T_break_min_TBit":                       13,
            "T_break_delimiter_min_TBit":             1,
            "T_break_detect_threshold_TBit":          11,
            "T_break_detect_threshold_better_tolerance_TBit": 9.5,
            "note":
                "An UART can only handle complete bits, so the break delimiter may be shorter than one bit time on the physical layer. Recommended to use a delimiter longer than one nominal bit time.",
        })
        d.setdefault("frame_length_relations", {
            "T_Header_Nominal_TBit":    34,
            "T_Response_Nominal_TBit":  "10 × (N_Data + 1)",
            "T_Frame_Nominal_TBit":     "T_Header_Nominal_TBit + T_Response_Nominal_TBit",
            "T_Header_Maximum_TBit":    "1.4 × T_Header_Nominal_TBit",
            "T_Response_Maximum_TBit":  "1.4 × T_Response_Nominal_TBit",
            "T_Frame_Maximum_TBit":     "T_Header_Maximum_TBit + T_Response_Maximum_TBit",
            "rationale":
                "Up to 40 % additional inter-byte space is allowed (split between header and response). Tools and tests check T_Frame_Maximum; nodes themselves do not need to check this — receivers must accept frames up to the next frame slot (next break field), even if they exceed T_Frame_Maximum.",
        })
        d.setdefault("schedule_table_timing", {
            "T_base_typical_ms":     [5, 10],
            "frame_slot_definition":
                "T_Frame_Slot = T_base × n (n integer ≥ 1, normally different per slot).",
            "frame_slot_constraint":
                "T_Frame_Slot > jitter + T_Frame_Maximum.",
            "jitter_definition":
                "Differences between the max and min delay from time-base tick to the header sending start point (falling edge of break field).",
            "schedule_switch_point":
                "Schedule switch request is honoured only at the start of the next frame slot — never mid-frame.",
        })
        d.setdefault("wake_up_waveform", {
            "wake_dominant_pulse_us_min":      250,
            "wake_dominant_pulse_ms_max":      5,
            "slave_detection_threshold_us":    150,
            "slave_ready_to_receive_ms_max":   100,
            "block_of_wake_signals":
                "Up to 3 wake signals separated by 150-250 ms (silence). Recommendation: not more than one such block per wake condition.",
            "post_3_attempts_silence_s_min":   1.5,
            "post_block_silence_recommended_s_min": 1.5,
        })
        d.setdefault("go_to_sleep_waveform", {
            "trigger": "Master transmits master-request frame (PID = 0x3C, classic checksum)",
            "data_bytes": ["0x00", "0xFF", "0xFF", "0xFF",
                           "0xFF", "0xFF", "0xFF", "0xFF"],
            "slave_post_command_behaviour":
                "Enter Bus sleep mode. Application may still run.",
            "implicit_sleep_timeout_s_min": 4,
            "implicit_sleep_timeout_s_max": 10,
        })
        d.setdefault("slave_synchronisation", {
            "method":
                "Slave measures successive falling/rising edges of the Sync byte (0x55). The 0x55 pattern (alternating bits between start dominant and stop recessive) provides 9 evenly-spaced edges; slave averages the period to compute T_Bit.",
            "tolerance_classes": [
                "F_TOL_RES_SLAVE — slaves without precision time base (typical RC oscillator) — use 11-bit break detect threshold.",
                "Slaves with crystal or ceramic resonator — may use 9.5-bit break detect threshold.",
            ],
        })
        d.setdefault("bit_sampling_note",
            "LIN 2.2 softened the bit sampling specification relative to 2.1 (per revision history). Exact sample-point tolerance is defined in section 6 (Physical Layer Specification).")
        d.setdefault("frame_response_timing_for_signals", {
            "master_node_signal_received_at":
                "Next time base tick after the maximum frame length (T_Frame_Maximum).",
            "slave_node_signal_received_at":
                "When the checksum for the received frame is validated.",
            "master_node_signal_transmitted_at":
                "Before the frame transmission is initiated.",
            "slave_node_signal_transmitted_at":
                "When the PID for the frame is received.",
        })
        _write(p, d)

    # ------------------------------------------------------------------ L9
    p = gd / "L9_INTEGRATION_SPEC.json"
    if p.is_file():
        d = _read(p)
        # Force-overwrite: UART (PC16550D) synth populates module_role and
        # integration_overview with its 40-pin parallel-host-bus semantics
        # (host_bus_side, serial_side, interrupt_routing). LIN class is
        # authoritative — wire_side / node_side replace UART subkeys.
        d["module_role"] = (
            "Single-master / multiple-slave UART-byte-framed serial bus on a single wire, intended for low-cost mechatronic clusters in vehicles where the bandwidth and versatility of CAN are not required. Implemented on each node as a master task (master node only) + slave task on top of a UART/SCI peripheral or pure state machine.")
        _ptm.apply(d, "lin_node")
        d["integration_overview"] = {
            "wire_side":   "Single LIN bus wire shared by master + slaves; VBAT for line termination via 1 kΩ (master) / 30 kΩ (slave) pull-ups; common GND.",
            "node_side":   "UART/SCI peripheral (or pure state machine) on a microcontroller, plus a LIN transceiver IC bridging TTL UART pins (TXD/RXD) to the LIN bus line.",
            "clock_source":"Master needs a stable time base (xtal or precise resonator) to honour schedule-table slot timing. Slave node may use an internal RC oscillator since it self-synchronises on every Sync byte.",
            "reset_source":"Microcontroller reset (POR / external pin); LIN-level reset behaviour = Initializing state.",
        }
        d.setdefault("interface_categories", [
            "Physical wire — LIN bus line + VBAT + GND",
            "Frame transceiver — UART byte fields + break generator/detector",
            "Schedule table (master only) — slot timer + frame-id pointer",
            "Signal interaction layer — signal pack/unpack into frame data bytes",
            "Transport layer (TL) — single / multi frame PDU assembly for node config / identification / diagnostics",
            "Diagnostic module — Diagnostic Class I/II/III services on top of TL",
        ])
        d.setdefault("interconnect_topologies_supported", [
            "Single LIN cluster — 1 master + N slaves on one bus wire. Typical N up to ~16 slaves (LDF-constrained).",
            "A master node may belong to more than one LIN bus; multi-bus interactions are handled at higher layers (application), not by this protocol.",
        ])
        # Force-overwrite: UART synth seeds default_signal_values_when_omitted
        # with mark/space + register-default semantics.
        d["default_signal_values_when_omitted"] = (
            "All bits not used or defined in a frame shall be recessive (ones). After reset, the LIN bus line is recessive.")
        d.setdefault("soc_dependent_items", [
            "UART/SCI peripheral configuration (baud rate divisor, 8-N-1 framing, LSB-first).",
            "Break generation / detection (≥13 / ≥11 dominant bit times).",
            "Schedule table memory (master) and time base (5 ms or 10 ms typical).",
            "Frame table per node — which IDs to publish / subscribe, length, checksum model.",
            "Initial NAD + Supplier ID + Function ID + Variant (per slave node).",
            "Transceiver wake pin handling.",
            "Interrupt routing for UART RX byte / TX byte / break detect / slot timer / transceiver wake.",
        ])
        # Force-overwrite: UART synth seeds low_power_modes with its Standby
        # vendor narrative (PC16550D specific).
        d["low_power_modes"] = {
            "Bus_sleep_mode":   "Bus level recessive; only wake-up signal allowed on the cluster. Application may continue to run; transceiver can enter low-current state.",
            "Wakeup_latency_ms":100,
            "Wake_trigger":     "Dominant pulse > 150 µs on the bus or internal reason in any node.",
        }
        d.setdefault("compatibility_notes", [
            "LIN 2.2A is a superset of LIN 1.3. A LIN 2.2A master can handle clusters consisting of both LIN 1.3 slaves and LIN 2.2 slaves; for LIN 1.3 slaves the master will avoid requesting LIN 2.1+ features (enhanced checksum, reconfiguration & diagnostics, automatic baud-rate detection, response_error monitoring).",
            "LIN 2.2 slave nodes cannot operate with a LIN 1.3 master node (e.g. LIN 1.3 master does not support enhanced checksum).",
            "LIN 2.2 physical layer is backwards compatible with LIN 1.3 physical layer, but not the other way around.",
            "LIN 2.2A corrected the wake-up signal definition (chapter 2.6.2) relative to LIN 2.2.",
        ])
        d.setdefault("ldf_role",
            "The LIN Description File (LDF) is the cluster-wide configuration file generated by the cluster design tool from each node's Node Capability File. It is parsed by the LIN cluster generator to auto-generate LIN-related functions on master + slave nodes, and is also consumed by bus analyzer / emulator tools.")
        _write(p, d)

    # ------------------------------------------------------------------ L10
    p = gd / "L10_TEST_CASES.json"
    if p.is_file():
        d = _read(p)
        # Force-overwrite: UART (PC16550D) synth seeds test_cases_present with
        # its waveform-figure narrative; LIN has a per-frame conformance signal.
        d["test_cases_present"] = (
            "partial - the LIN spec defines protocol behaviour and a per-frame conformance signal (response_error) but does not enumerate stand-alone bench test vectors. Conformance tests are derived from the must-have / must-not-have properties (L16) and the behavioural sequences (L12).")
        _write(p, d)

    # ------------------------------------------------------------------ L11 OTP
    p = gd / "L11_OTP_CONTENT.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("otp_present", False)
        d["notes"] = (
            "LIN is a wire-level protocol specification, not a chip. There "
            "is no LIN-defined OTP / fuse / configuration ROM. Per-node "
            "identity data (initial NAD, Supplier ID, Function ID, Variant) "
            "is typically stored in microcontroller program flash or EEPROM "
            "and exposed via the Read by Identifier service (transport "
            "layer, ID 0x3C / 0x3D). The Save Configuration service may "
            "persist a node's reassigned NAD into non-volatile storage so "
            "that the assignment survives a power cycle — but the storage "
            "medium is vendor-specific.")
        _write(p, d)

    # ------------------------------------------------------------------ L12
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("initialization_sequence", [
            "1. Power-on / reset — slave node enters Initializing state instantaneously.",
            "2. Slave performs LIN-related initialisation: configure UART (8-N-1, LSB-first), set break detect threshold (11 or 9.5 bit times), populate frame table with publishing and subscribing PIDs from LDF, set initial NAD + Supplier ID + Function ID + Variant.",
            "3. Initialisation must complete within 100 ms.",
            "4. Transition to Operational. LIN protocol behaviour (TX/RX of frames) now applies.",
        ])
        d.setdefault("master_schedule_sequence", [
            "1. On every time-base tick (5 ms or 10 ms typical) check the active schedule table for a frame slot whose due time has elapsed.",
            "2. Issue Break (≥13 dominant nominal bit times) + Break Delimiter (≥1 recessive).",
            "3. Issue Sync byte (0x55) as a UART byte field.",
            "4. Issue Protected Identifier byte (ID0..ID5 + P0 + P1).",
            "5. If master is also the publisher of this PID → transmit Data 1 .. Data N + Checksum.",
            "6. Otherwise wait for slave response within T_Frame_Maximum; receive data + checksum; validate.",
            "7. Mark Successful_transfer or Error_in_response in own node.",
            "8. Advance to next schedule slot at the next slot's due time (or honour a pending schedule switch request).",
        ])
        d.setdefault("slave_publish_sequence", [
            "1. On break/sync detection, slave UART resynchronises to master's bit time using the 0x55 edges.",
            "2. Receive PID byte; verify P0/P1 parity.",
            "3. If PID matches a frame this slave publishes → begin Active.TxData.",
            "4. Transmit Data 1 .. Data N, performing UART readback on each byte; abort no later than end of any byte where readback ≠ sent.",
            "5. Compute classic or enhanced checksum per frame ID convention.",
            "6. Transmit Checksum with readback.",
            "7. On successful readback: set Successful_transfer; clear response_error if this is the unconditional frame carrying response_error.",
            "8. On any mismatch: set Error_in_response and response_error for next slot.",
        ])
        d.setdefault("slave_subscribe_sequence", [
            "1. On break/sync detection, slave UART resynchronises to master's bit time using the 0x55 edges.",
            "2. Receive PID byte; verify P0/P1 parity.",
            "3. If PID matches a frame this slave subscribes to → begin Active.RxData.",
            "4. Receive Data 1 .. Data N; on framing error → Error.",
            "5. Receive Checksum; validate (classic or enhanced per frame ID convention).",
            "6. If valid → Success; update subscribed signals; signal is available to the application directly after the frame is finished (at interrupt level).",
            "7. If invalid → Error_in_response = 1; response_error scheduled for next unconditional slot.",
        ])
        d.setdefault("wake_up_sequence", [
            "1. A node desiring to wake the cluster forces the bus dominant for 250 µs to 5 ms, then releases to recessive.",
            "2. Every slave detects the dominant pulse longer than 150 µs and begins its Initializing state.",
            "3. Slave shall be ready to listen for headers within 100 ms after the trailing edge of the dominant pulse.",
            "4. Master detects the wake-up signal (dominant pulse > 150 µs) and starts to transmit headers within an application-specific time to query the cause via signals.",
            "5. If the master does not transmit a break within 150-250 ms from the wake-up signal, the originating node may retransmit a wake-up signal (up to 3 attempts per block).",
            "6. After 3 failed attempts in a block, wait at least 1.5 s before issuing the 4th wake-up signal.",
        ])
        d.setdefault("go_to_sleep_sequence", [
            "1. Master transmits the Go-To-Sleep command — a master-request frame (PID = 0x3C) with data1 = 0x00 and data2..data8 = 0xFF.",
            "2. Slaves receive, decode the first data byte, and transition Operational → Bus sleep mode. Slave application may still run.",
            "3. Alternatively, slave automatically enters Bus sleep mode after 4..10 s of bus inactivity (defined as no recessive-to-dominant transition).",
        ])
        d.setdefault("collision_resolving_sequence_event_triggered_frame", [
            "1. Master issues a header for an event-triggered frame (e.g. ID = 0x10).",
            "2. Two or more associated unconditional-frame publishers (e.g. ID 0x11 from Slave 1, ID 0x12 from Slave 2) respond simultaneously → collision on the bus.",
            "3. Master detects the collision (checksum / framing error) and automatically switches the active schedule to the collision-resolving schedule table at the next slot boundary.",
            "4. Master polls each associated unconditional frame in turn (header for 0x12, then header for 0x11) so each publisher gets a dedicated slot.",
            "5. After processing the collision-resolving schedule once, the master switches back to the previous schedule, continuing with the slot subsequent to where the collision occurred (or first slot if the collision was in the last slot).",
            "6. A withdrawing slave's response is lost unless it retransmits in a subsequent slot.",
        ])
        d.setdefault("node_configuration_sequence_assign_NAD", [
            "1. Master sends master-request frame (PID 0x3C) carrying SF SID = 0xB0 Assign NAD with parameters {initial NAD, supplier ID, function ID, new NAD}.",
            "2. The addressed slave changes its NAD to the new value and responds with PCI=0x01, RSID=0xF0 in a slave-response frame (PID 0x3D).",
        ])
        d.setdefault("transport_layer_single_frame_sequence", [
            "1. Master transmits master-request frame (PID 0x3C) with PCI = SF-LEN-nibble; data field = NAD + PCI + SID + D1..D5.",
            "2. Slave executes service; responds with slave-response frame (PID 0x3D) carrying SF-LEN-nibble PCI + RSID + result D1..D5.",
        ])
        d.setdefault("transport_layer_multi_frame_sequence", [
            "1. Master sends First Frame (FF) — PCI hi-nibble = 0x1, lo-nibble = upper-nibble of LEN (12-bit total LEN up to 4095). Carries NAD + PCI + LEN + SID + first 5 data bytes.",
            "2. Master sends Consecutive Frames (CF) — PCI hi-nibble = 0x2, lo-nibble = sequence number (1..15 cycling). Each CF carries NAD + PCI + 6 data bytes.",
            "3. Receiver reassembles and acts on the complete service request once all bytes received.",
        ])
        _write(p, d)

    # ------------------------------------------------------------------ L13
    p = gd / "L13_LAB_CALIBRATION.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("lab_calibration_present", False)
        d["notes"] = (
            "LIN is a wire-level protocol spec. There is no LIN-defined "
            "analog reference / trim / calibration loop at the protocol "
            "level. Bit-rate accuracy: the master must hold a precise time "
            "base (xtal or precision resonator); slave nodes resynchronise "
            "on every Sync byte (0x55) and may therefore tolerate a less "
            "stable clock (typical internal RC). The Physical Layer "
            "Specification (section 6) defines F_NOM and the bit-rate "
            "tolerance classes F_TOL_RES_SLAVE and F_TOL_RES_SLAVE_BETTER "
            "(which sets the 11 vs 9.5 bit-time break-detect threshold). "
            "Beyond those, no on-chip calibration is required by the "
            "protocol.")
        _write(p, d)

    # ------------------------------------------------------------------ L14
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        # Force-overwrite: UART (PC16550D) synth populates spec_version with
        # its product code.
        f["spec_version"] = "LIN 2.2A"
        f.setdefault("spec_revised_date", "December 31, 2010")
        f.setdefault("publisher", "LIN Consortium")
        f.setdefault("website", "www.lin-subbus.org")
        if _empty(f.get("lineage")):
            f["lineage"] = [
                {"version": "LIN 1.0",  "year": "1999-07-01", "summary": "Initial version of the LIN Specification; heavily influenced by the VLITE bus used by some automotive companies."},
                {"version": "LIN 1.1",  "year": "2000-03-06", "summary": "Minor update."},
                {"version": "LIN 1.2",  "year": "2000-11-17", "summary": "Updated standard."},
                {"version": "LIN 1.3",  "year": "2002-12-13", "summary": "Mainly physical-layer changes, targeting improved compatibility between nodes."},
                {"version": "LIN 2.0",  "year": "2003-09-16", "summary": "Major Revision Step. Spec completely reworked. Standardised configuration/diagnostics and Node Capability files. Introduced enhanced checksum + reconfiguration + diagnostics + automatic baud-rate detection + response_error status monitoring."},
                {"version": "LIN 2.1",  "year": "2006-11-24", "summary": "Clarifications, configuration modified, transport layer enhanced, diagnostics added."},
                {"version": "LIN 2.2",  "year": "2010-12-31", "summary": "Updated document according to LIN 2.1 Errata sheet 1.4. Softened bit sampling specification."},
                {"version": "LIN 2.2A", "year": "2010-12-31", "summary": "Corrected wake-up signal definition in chapter 2.6.2 (current revision)."},
            ]
        if _empty(f.get("backward_compat_traps")):
            f["backward_compat_traps"] = [
                {"trap_name": "lin_1_3_vs_2_x_checksum",
                 "lin_1_x_behaviour": "All frames use classic checksum (over data bytes only).",
                 "lin_2_x_behaviour": "Non-diagnostic frames use enhanced checksum (over PID + data bytes); diagnostic frames (IDs 0x3C / 0x3D) still use classic.",
                 "trap": "A LIN 2.x slave node cannot operate with a LIN 1.3 master because the LIN 1.3 master cannot produce enhanced checksum. A LIN 2.x master driving a mixed cluster must know which slaves are LIN 1.3 (use classic) vs LIN 2.x (use enhanced) on a per-frame-ID basis."},
                {"trap_name": "lin_2_2_softened_bit_sampling",
                 "lin_2_1_behaviour": "Stricter bit-sampling requirement.",
                 "lin_2_2_behaviour": "Softened bit sampling specification (per revision history).",
                 "trap": "A LIN 2.1 compliance test may reject a LIN 2.2-tuned implementation as too lenient; do not retrofit a softened-sample slave into a strict-2.1 cluster without a tolerance audit."},
                {"trap_name": "lin_2_2A_wake_up_corrected",
                 "lin_2_2_behaviour": "Original wake-up signal definition (section 2.6.2).",
                 "lin_2_2A_behaviour": "Corrected wake-up signal definition in chapter 2.6.2.",
                 "trap": "A 2.2 implementation may have a slightly different wake-up signal interpretation than a 2.2A implementation; verify against the 2.2A text before claiming 2.2A compliance."},
                {"trap_name": "reserved_frame_ids_3E_3F",
                 "lin_1_x_behaviour": "IDs 0x3E and 0x3F were not used.",
                 "lin_2_x_behaviour": "IDs 0x3E and 0x3F are reserved for future LIN extended format and shall not be used in a LIN 2.x cluster.",
                 "trap": "Some legacy nodes may have used 0x3E / 0x3F as private signal carriers; this is non-compliant in LIN 2.x and will collide with any future extended-format LIN implementation."},
                {"trap_name": "physical_layer_1_3_vs_2_2",
                 "lin_1_3_behaviour": "Looser physical-layer requirements.",
                 "lin_2_2_behaviour": "LIN 2.2 physical layer is backwards compatible with LIN 1.3 — but not the other way around. LIN 2.2 sets harder requirements.",
                 "trap": "A node implemented to LIN 2.2 physical layer can join a LIN 1.3 cluster, but a LIN 1.3 node may fail EMC/voltage thresholds when placed in a LIN 2.2 cluster."},
            ]
        # Force-overwrite: UART synth seeds version_naming_history_note with
        # PC16550D historical narrative.
        f["version_naming_history_note"] = (
            "The LIN Consortium released seven revisions (1.0 → 1.1 → 1.2 → 1.3 → 2.0 → 2.1 → 2.2 → 2.2A) between 1999 and 2010. LIN 2.0 was the major revision step that standardised diagnostics, configuration, and the Node Capability File workflow. LIN 2.2A is the final revision before the LIN protocol was harmonised into ISO 17987 (2016+).")
        d["fields"] = f
        _write(p, d)

    # ------------------------------------------------------------------ L15
    p = gd / "L15_ENCODING_TABLES.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("protected_identifier_encoding", {
            "description": "PID byte = ID0..ID5 in bits 0..5 + P0 in bit 6 + P1 in bit 7 (per Figure 2.7).",
            "P0_equation": "P0 = ID0 ⊕ ID1 ⊕ ID2 ⊕ ID4",
            "P1_equation": "P1 = ¬(ID1 ⊕ ID3 ⊕ ID4 ⊕ ID5)",
        })
        # Auto-generate full PID table from the parity equations — this is
        # both general (algorithm not magic numbers) and matches Table 2.4.
        if _empty(f.get("valid_frame_identifier_table")):
            rows = []
            for ident in range(64):
                bits = [(ident >> i) & 1 for i in range(6)]  # ID0..ID5
                p0 = bits[0] ^ bits[1] ^ bits[2] ^ bits[4]
                p1 = 1 - (bits[1] ^ bits[3] ^ bits[4] ^ bits[5])
                pid = ident | (p0 << 6) | (p1 << 7)
                rows.append([ident, f"0x{ident:02X}", p0, p1, f"0x{pid:02X}"])
            f["valid_frame_identifier_table"] = {
                "description": "Table 2.4 — all 64 valid frame identifiers with their parity bits and resulting PID-Field byte value.",
                "header_columns": ["ID[0..5] Dec", "ID[0..5] Hex",
                                   "P0", "P1", "PID-Field Hex"],
                "rows": rows,
                "annotations": [
                    "ID 60 (0x3C) — Master Request diagnostic frame.",
                    "ID 61 (0x3D) — Slave Response diagnostic frame.",
                    "ID 62 (0x3E) and 63 (0x3F) — reserved for future LIN extended format; shall not be used in a LIN 2.x cluster.",
                ],
            }
        f.setdefault("checksum_calculation_example_table", {
            "description": "Section 2.8.3 example. Inverted 8-bit sum-with-carry over 4 bytes {0x4A, 0x55, 0x93, 0xE5}.",
            "header_columns": ["Action", "hex", "Carry", "D7..D0"],
            "rows": [
                ["Start with byte 0x4A",          "0x4A",  None, "01001010"],
                ["+ 0x55",                         "0x9F",  0,    "10011111"],
                ["(Add Carry result)",             "0x9F",  None, "10011111"],
                ["+ 0x93 = 0x132",                 "0x132", 1,    "100110010"],
                ["Add Carry → 0x33",               "0x33",  None, "00110011"],
                ["+ 0xE5 = 0x118",                 "0x118", 1,    "100011000"],
                ["Add Carry → 0x19",               "0x19",  None, "00011001"],
                ["Invert → 0xE6 (final checksum)", "0xE6",  None, "11100110"],
                ["Verify: 0x19 + 0xE6 = 0xFF",     "0xFF",  None, "11111111"],
            ],
        })
        f.setdefault("numerical_properties_table", {
            "description": "Table 2.3 — Defined numerical properties of the LIN protocol.",
            "header_columns": ["Property", "Min", "Max", "Unit", "Reference"],
            "rows": [
                ["Scalar signal size",                        1,    16,   "bit",  "section 2.2.1"],
                ["Byte array size",                           1,    8,    "byte", "section 2.2.1"],
                ["Break field length (dominant + delimiter)", 14,   None, "T_bit","section 2.3.1.1"],
                ["Break detect threshold",                    11,   11,   "T_bit","section 2.3.1.1"],
                ["Wake up signal duration",                   0.25, 5,    "ms",   "section 2.6.2"],
                ["Slave initialize time",                     None, 100,  "ms",   "section 2.6.2"],
                ["Silence period between wake up signals",    150,  250,  "ms",   "section 2.6.2"],
                ["Silence period after three wake up signals",1.5,  None, "s",    "section 2.6.2"],
            ],
        })
        f.setdefault("go_to_sleep_command_table", {
            "description": "Table 2.1 — Go to sleep command. Master-request frame (ID 0x3C, classic checksum).",
            "header_columns": ["data1", "data2", "data3", "data4",
                               "data5", "data6", "data7", "data8"],
            "rows": [["0x00", "0xFF", "0xFF", "0xFF",
                      "0xFF", "0xFF", "0xFF", "0xFF"]],
        })
        f.setdefault("response_error_interpretation_table", {
            "description": "Table 2.2 — Master-node interpretation of slave-node response_error reports.",
            "header_columns": ["response_error", "Interpretation"],
            "rows": [
                ["false",                          "the slave node is operating correctly"],
                ["true",                           "the slave node has intermittent problems"],
                ["the slave node did not answer",  "the slave node, bus or master node has serious problems"],
            ],
        })
        if _empty(f.get("tables")):
            f["tables"] = [
                "Table 2.1 — Go to sleep command",
                "Table 2.2 — Interpretation of the response_error",
                "Table 2.3 — Defined numerical properties",
                "Table 2.4 — Valid frame identifiers",
                "Table 2.5 — Example of checksum calculation",
            ]
        d["fields"] = f
        _write(p, d)

    # ------------------------------------------------------------------ L16
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("must_have_properties", [
            "Each frame consists of a Header (Break + Sync + PID) followed by a Response (1..8 Data bytes + Checksum).",
            "Break field is at least 13 nominal dominant bit times followed by ≥1 recessive bit Break Delimiter.",
            "Slave break detect threshold is 11 nominal bit times (9.5 for slaves with bit-rate tolerance better than F_TOL_RES_SLAVE).",
            "Sync byte field is the byte value 0x55 transmitted as a UART byte field.",
            "PID byte = {ID0..ID5, P0, P1} where P0 = ID0 ⊕ ID1 ⊕ ID2 ⊕ ID4 and P1 = ¬(ID1 ⊕ ID3 ⊕ ID4 ⊕ ID5).",
            "Every non-break byte field is start (dominant) + 8 data bits LSB-first + stop (recessive).",
            "Frames carry between 1 and 8 data bytes.",
            "Multi-byte data entities are little-endian (LSB-first byte sent first).",
            "Checksum is the inverted 8-bit sum-with-carry. Classic checksum covers data bytes only; enhanced checksum covers Protected Identifier + data bytes.",
            "Diagnostic frames (IDs 0x3C and 0x3D) shall always use classic checksum and always carry 8 data bytes.",
            "Frame IDs 0x3E and 0x3F shall not be used in a LIN 2.x cluster.",
            "All bits not used/defined in a frame shall be recessive (ones).",
            "Master task transmits headers based on a schedule table; schedule switch is honoured only at slot boundaries.",
            "Wake-up signal: dominant pulse 250 µs to 5 ms; slaves detect dominant pulses longer than 150 µs and are ready to receive within 100 ms.",
            "Go-To-Sleep command is a master-request frame (PID 0x3C) with data1 = 0x00 and data2..data8 = 0xFF.",
            "Slave shall automatically enter Bus sleep mode after 4 to 10 s of bus inactivity.",
            "Slave init process must complete within 100 ms.",
            "Every slave publishes a 1-bit scalar response_error in one of its transmitted unconditional frames.",
            "response_error is set on any frame (except event-triggered) that is transmitted or received with an error in the response, and cleared once the carrying unconditional frame is successfully transmitted.",
            "Receiving node shall accept a frame up to the next frame slot (next break field), even if it exceeds T_Frame_Maximum.",
            "Bit error on TX: mismatch between readback and sent data shall be detected no later than the end of the byte field containing the mismatch; transmission shall be aborted.",
        ])
        f.setdefault("must_not_have_properties", [
            "A slave may not publish more than one publishing role on the same frame ID.",
            "An unconditional frame associated with an event-triggered frame may not be in the same schedule table as the event-triggered frame.",
            "A schedule switch may not interrupt an ongoing frame transmission (switch deferred to the next slot boundary).",
            "Reserved frame IDs 0x3E and 0x3F may not be transmitted in a LIN 2.x cluster.",
            "Mixing classic and enhanced checksum frames within an event-triggered frame's associated unconditional frames is not allowed.",
            "A slave may not initiate a frame on its own — all frames are header-driven by the master task.",
            "An unconditional frame associated with a sporadic frame may not be allocated in the same schedule table as the sporadic frame.",
            "The master may not check T_Frame_Maximum at the receiving node level (only tools/tests check it).",
        ])
        f.setdefault("compliance_failure_modes", [
            {"mode": "Framing error",                  "trigger": "Start/stop bit not as expected in a byte field."},
            {"mode": "Bit error (TX)",                 "trigger": "Transmitter's UART readback ≠ sent bit; detected no later than end of byte field."},
            {"mode": "Checksum error",                 "trigger": "Received checksum ≠ locally computed checksum (classic or enhanced per frame ID convention)."},
            {"mode": "PID parity error",               "trigger": "Computed P0/P1 ≠ received P0/P1."},
            {"mode": "Unknown PID",                    "trigger": "Received PID has no matching frame in local node frame table."},
            {"mode": "No response",                    "trigger": "Master transmitted a header but no slave responded within T_Frame_Maximum."},
            {"mode": "Last frame response too short",  "trigger": "Last frame contained ≥ 1 field but ended prematurely (distinguishes error vs no response)."},
            {"mode": "Event-triggered collision",      "trigger": "Multiple slaves responded to the same event-triggered frame; master switches to collision-resolving schedule."},
            {"mode": "Wake-up not acknowledged",       "trigger": "Originating node did not see a break within 150-250 ms of its wake signal; retransmit (max 3 per block, then ≥1.5 s wait)."},
        ])
        f.setdefault("minimum_implementation_requirements", [
            "UART or equivalent state machine with break gen / detect.",
            "Frame table with publish / subscribe roles per PID.",
            "Schedule-table-driven header generation (master only).",
            "Classic checksum (LIN 1.x) + enhanced checksum (LIN 2.x) per-frame-ID configurable.",
            "response_error signal published in one of the slave's unconditional frames.",
            "Bus sleep mode entry on Go-To-Sleep command OR ≥4 s bus inactivity; wake-up signal generation + detection.",
        ])
        # Force-overwrite: UART (PC16550D) synth populates reset_behavior_compliance
        # with its MR-pulse register-reset semantics.
        f["reset_behavior_compliance"] = (
            "After power-on / reset / wake-up the slave is in Initializing state. LIN protocol behaviour applies only in Operational state. Init must complete within 100 ms; bus is recessive throughout init.")
        d["fields"] = f
        _write(p, d)

    # ------------------------------------------------------------------ L17
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f["channels_physical_wire"] = [
            {"name": "LIN bus line", "direction": "bidirectional (open-drain / wired-AND)", "purpose": "Shared single-wire data bus between master and slaves. Idle = recessive (pulled toward VBAT via 1 kΩ master / 30 kΩ slave termination). Active dominant pulls toward GND via the transmitting transceiver."},
            {"name": "VBAT",         "direction": "supply",                                  "purpose": "Battery rail providing pull-up for bus termination (12 V typical)."},
            {"name": "GND",          "direction": "supply",                                  "purpose": "Common ground reference."},
        ]
        f["channels_node_uart_side"] = [
            {"name": "TXD", "direction": "node→transceiver", "purpose": "Logic-level UART transmit. Driven by the node's UART/SCI peripheral; transceiver translates to dominant on the bus when TXD low."},
            {"name": "RXD", "direction": "transceiver→node", "purpose": "Logic-level UART receive. Transceiver reports bus state to the node's UART/SCI peripheral; node samples for byte fields."},
        ]
        f["channels_transceiver_control"] = [
            {"name": "EN / SLP / WAKE", "direction": "vendor-specific", "purpose": "Transceiver mode control (normal / low-power / wake) — implementation defined; the LIN protocol does not standardise these pins."},
        ]
        f["node_role_classification"] = [
            {"role": "master node", "count_per_cluster": 1,                                      "tasks": "master task + slave task"},
            {"role": "slave node",  "count_per_cluster": "1..N (typically ≤ 16 by LDF convention)","tasks": "slave task only"},
        ]
        f["frame_field_signal_catalog"] = [
            {"name": "Break field",                "direction": "master→bus",    "purpose": "Frame-start delimiter; ≥13 dominant nominal bit times + ≥1 recessive Break Delimiter."},
            {"name": "Sync byte field",            "direction": "master→bus",    "purpose": "0x55 UART byte field; provides alternating edges for slave bit-time measurement."},
            {"name": "Protected Identifier (PID)", "direction": "master→bus",    "purpose": "8-bit field: ID0..ID5 + P0 + P1; identifies the frame and triggers publish / subscribe roles."},
            {"name": "Data 1 .. Data N",           "direction": "publisher→bus", "purpose": "1..8 payload bytes; transmitted LSB-first (little-endian for multi-byte entities)."},
            {"name": "Checksum",                   "direction": "publisher→bus", "purpose": "Inverted 8-bit sum-with-carry; classic over data bytes, enhanced over PID + data."},
        ]
        f["signal_types_supported_by_protocol"] = [
            {"type": "boolean scalar",          "width_bits": "1",       "notes": "1-bit scalar signal."},
            {"type": "unsigned integer scalar", "width_bits": "2..16",   "notes": "Packed within frame data bytes; can cross byte boundaries."},
            {"type": "byte array",              "size_bytes": "1..8",    "notes": "Byte-aligned within the frame data field; LSB byte first."},
        ]
        f["channel_counts"] = {
            "physical_bus_wires":      1,
            "supply_wires":            2,
            "node_uart_logic_pins":    2,
            "max_slaves_typical":      16,
            "max_master_per_cluster":  1,
        }
        # Force-overwrite dependency_graph (earlier steps may have written
        # AXI-leaning content; LIN shape is fundamentally different).
        f["dependency_graph"] = {
            "common_rule": "All bus activity is initiated by the master task. Each frame slot is a header + at most one response. Slaves never initiate; they may only respond to a header whose PID they publish (or send a wake signal from Bus sleep mode).",
            "data_dependency": "Slave response data is bound to the PID transmitted in the slot's header. response_error in a status-carrying unconditional frame depends on the success/failure of all prior non-event-triggered frames since the last response_error transmission.",
        }
        # Force-overwrite: UART (PC16550D) synth seeds ordering_rules with
        # register-DLAB semantics; LIN ordering is wire-level.
        f["ordering_rules"] = {
            "byte_ordering":  "LSB-first on the wire (each UART byte field) and LSB-byte-first within the frame data field (little-endian).",
            "field_ordering": "Break → Sync → PID → Data 1 .. Data N → Checksum, with optional inter-byte spaces.",
        }
        f["global_signals"] = [
            {"name": "response_error",                       "purpose": "1-bit scalar published by every slave in one of its transmitted unconditional frames. Cluster-wide health indicator."},
            {"name": "NAD",                                  "purpose": "8-bit Node Address for Diagnostics, used in master-request / slave-response frames to address a specific slave."},
            {"name": "Supplier ID + Function ID + Variant", "purpose": "16-bit + 16-bit + 8-bit slave identification, returned by Read by Identifier."},
        ]
        d["fields"] = f
        _write(p, d)

    # ------------------------------------------------------------------ L18
    p = gd / "L18_INTERCONNECT_TOPOLOGY.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f["topology_type"] = "Single-master, multi-slave shared-medium bus on one wire. All nodes (1 master + N slaves) tap the same LIN bus line; communication is half-duplex."
        f["supported_topologies"] = [
            {"name": "Single LIN cluster",            "description": "1 master + 1..N slaves on a shared single-wire bus (LIN bus line + VBAT + GND). Master controls all timing via schedule table."},
            {"name": "Multi-cluster node",            "description": "A node (normally the master) may be connected to more than one LIN bus; multi-bus coordination is handled by higher layers (application), not by the LIN protocol."},
            {"name": "Hierarchical with CAN backbone","description": "Vehicle architecture commonly uses CAN as the high-bandwidth backbone with LIN as low-cost sub-buses behind specific CAN ECUs. LIN protocol does not standardise the CAN ↔ LIN gateway behaviour."},
        ]
        f["master_slave_role_summary"] = [
            {"role": "master node", "description": "Contains a master task (header / schedule generator) plus a slave task (just like any other slave). Owner of timing. Owns the schedule tables and switches between them. Owns cluster status management. Issues Go-To-Sleep command. Single per cluster."},
            {"role": "slave node",  "description": "Contains a slave task only. Publishes data on PIDs it owns; subscribes on PIDs whose response data it consumes. Self-synchronises on every Sync byte. Reports response_error in one of its transmitted unconditional frames. May issue wake-up signal from Bus sleep mode."},
        ]
        f["interconnect_role"] = (
            "The LIN protocol provides no in-cluster switching / routing — "
            "every byte transmitted is heard by every node on the shared "
            "wire. Frame-ID-based content addressing (similar to CAN) lets "
            "each receiver decide whether the payload is interesting via "
            "its frame table.")
        f["ordering_guarantees"] = {
            "within_a_byte":   "Bits transmitted LSB-first on the wire.",
            "across_bytes":    "Strict in-frame order per Figure 2.3 — Break → Sync → PID → Data 1 → Data 2 → … → Data N → Checksum.",
            "across_frames":   "Strict schedule-table order; in the absence of a schedule switch, the master transmits each slot's header in the order it appears in the active schedule.",
            "schedule_switch": "A schedule switch request is honoured at the start of the next frame slot only; never mid-frame.",
        }
        f.setdefault("memory_vs_peripheral_regions",
            "Not applicable — LIN is a bus protocol, not a memory map. Per-node frame tables, schedule tables, and NAD storage live in the implementer's memory map.")
        # Force-overwrite: UART (PC16550D) synth seeds slave_classification
        # with polling/interrupt/dma target taxonomy; LIN uses publisher/
        # subscriber semantics.
        f["slave_classification"] = {
            "publisher":          "Slave that owns one or more frame IDs and produces data + checksum when its PID is heard.",
            "subscriber":         "Slave that listens to one or more frame IDs and consumes the response.",
            "diagnostic_target":  "Slave addressed by the current NAD in a master-request frame (ID 0x3C) and required to respond on the slave-response frame (ID 0x3D).",
            "self_role":          "Same physical slave can be publisher of some PIDs and subscriber of others.",
        }
        f.setdefault("default_signal_values_evidence_tables", [
            "Table 2.3 — Defined numerical properties",
            "Table 2.4 — Valid frame identifiers",
            "Section 1.1.2 main properties of LIN bus",
        ])
        f.setdefault("cluster_design_artefacts", [
            "LIN Description File (LDF) — cluster-wide config generated by the cluster design tool, consumed by code generators and bus analyzers.",
            "Node Capability File — per-slave capability description, input to the cluster design tool.",
            "Schedule tables — N × (slot, PID, duration, type) lists, owned by the master.",
        ])
        f.setdefault("modem_control_topology", None)
        f.setdefault("wakeup_topology",
            "Any node may initiate a wake-up by forcing the bus dominant for 250 µs to 5 ms; all other nodes detect the pulse and begin their Initializing state.")
        d["fields"] = f
        _write(p, d)

    # ------------------------------------------------------------------ L19
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("constraints_present", False)
        f["notes"] = (
            "LIN 2.2A is a wire-level protocol specification, not a chip "
            "specification. No PDK / floorplan / SDC / UPF / DFT constraints "
            "exist at the protocol level. The Physical Layer Specification "
            "(section 6) defines line-driver / receiver characteristics — "
            "bit-rate tolerances (F_NOM, F_TOL_RES_SLAVE, "
            "F_TOL_RES_SLAVE_BETTER), bus voltage thresholds, slew rate, "
            "EMI behaviour — but these are wire-level requirements, not "
            "silicon constraints. Real LIN-capable silicon (vendor LIN "
            "transceivers, microcontroller UARTs with LIN extensions) "
            "provides its own SDC / Liberty / UPF at the IP-license level "
            "outside the LIN spec.")
        d["fields"] = f
        _write(p, d)

    # ------------------------------------------------------------------ L20
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f["dft_present"] = False
        f.setdefault("internal_diagnostics", [
            "response_error signal — 1-bit scalar that allows the master node to detect intermittent slave problems via standard frames; no hardware-test pins required.",
            "Error_in_response + Successful_transfer status bits (within the slave) — software-observable through the API.",
            "Read by Identifier service (SID 0xB2) — returns Supplier ID / Function ID / Variant + ECU-specific identifiers for cluster-level identification.",
            "Diagnostic Class I / II / III services on the transport layer — DTC read / clear, ECU info, programming.",
        ])
        f["notes"] = (
            "LIN is a wire-level protocol specification, not a chip. No "
            "JTAG / scan / boundary-scan / MBIST is defined at the "
            "protocol level. DFT belongs to whichever silicon implements "
            "the LIN node (vendor LIN transceiver IC + microcontroller "
            "UART).")
        d["fields"] = f
        _write(p, d)

    # ------------------------------------------------------------------ L21
    p = gd / "L21_POWER_INTENT.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        # Force-overwrite: UART (PC16550D) synth defaults power_intent_present
        # to False (UART has no formal power-domain spec). LIN has Bus_sleep_mode.
        f["power_intent_present"] = True
        f["low_power_modes_summary"] = {
            "Operational":    "Bus active. Master schedules headers; slaves respond. Normal current consumption (vendor-specific).",
            "Bus_sleep_mode": "Bus level recessive; only wake-up signal allowed on the cluster. Transceivers can enter low-current standby. Application may still run independently of the bus.",
            "wake_latency_ms": 100,
        }
        f["wake_up_protocol_summary"] = {
            "wake_dominant_pulse_min_us":   250,
            "wake_dominant_pulse_max_ms":   5,
            "slave_detection_threshold_us": 150,
            "slave_ready_to_listen_ms_max": 100,
            "retry_silence_between_signals_ms": [150, 250],
            "post_3_retries_silence_s_min":  1.5,
            "post_block_silence_recommended_s_min": 1.5,
            "max_recommended_wake_signals_per_block": 3,
        }
        f["go_to_sleep_summary"] = {
            "command_pid_hex": "0x3C",
            "checksum_model":  "classic",
            "data_byte_pattern_hex": ["0x00", "0xFF", "0xFF", "0xFF",
                                       "0xFF", "0xFF", "0xFF", "0xFF"],
            "implicit_sleep_after_bus_inactivity_s_min": 4,
            "implicit_sleep_after_bus_inactivity_s_max": 10,
            "bus_inactivity_definition":
                "no transitions between recessive and dominant bit values (after the LIN-transceiver spike filter)",
        }
        f["notes"] = (
            "LIN defines power intent at the cluster level (Operational ↔ "
            "Bus sleep mode) but not at the silicon-power-domain level. "
            "UPF / power-intent files belong to whichever IP implements "
            "the LIN node.")
        d["fields"] = f
        _write(p, d)

    # ------------------------------------------------------------------ L23
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("security_requirements_present", False)
        f["notes"] = (
            "LIN 2.2A (December 31, 2010) predates the inclusion of "
            "automotive cybersecurity in the standard's scope. The spec "
            "does not define confidentiality, integrity, authentication, "
            "freshness, or key-management primitives at the protocol "
            "level — data is transmitted in plaintext on the LIN bus "
            "line. Any security must be layered above LIN at the "
            "application level (e.g. host-side message authentication "
            "codes appended in the frame data field, fixed challenge-"
            "response across diagnostic services). Modern automotive "
            "cybersecurity (SecOC, AUTOSAR security, ISO/SAE 21434) was "
            "standardised after LIN 2.2A. The reserved-frame doctrine "
            "(IDs 0x3E / 0x3F shall not be used in LIN 2.x clusters) is "
            "the closest the spec comes to a forward-compatibility "
            "guard.")
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
def is_lin(blob: str) -> bool:
    """Content-only `lin` detector (importable, lifted from the runner).

    Empty-safe. Reads ONLY ``blob`` (spec text). Byte-for-byte the
    same boolean the runner used inline.
    """
    if not blob:
        return False
    return bool(
        ("LIN bus" in blob
         or "Local Interconnect Network" in blob
         or "LIN Consortium" in blob
         or "LIN 2." in blob)
        and (("BREAK" in blob.upper()
              and "SYNC" in blob.upper())
             or ("master" in blob.lower()
                 and "schedule" in blob.lower())))
