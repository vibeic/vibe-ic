"""USB-class protocol synth helper.

v0.1.82 — ic_class-gated overlay for `serial_peripheral_protocol` specs
that exhibit the USB structural signature (D+/D- differential data
lines + VBUS power + USB 2.0 / 1.1 / 1.0 / NRZI + tiered-star + hub
terminology). Applies USB 2.0 spec-canonical content to L1-L18 + L21.

Doctrine: structural-keyword detection IS general within an ic_class
(mirrors AMBA-AXI / SPI / I2C / UART / CAN synth approach). Any USB
2.0 family variant (USB 2.0 spec, OHCI / UHCI / EHCI host controllers,
USB-IF class specs) exhibits the same structural signature.

Public entry: `apply_usb_synth(generated_docs_dir, is_usb, usb_ic_name)`.
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


def apply_usb_synth(generated_docs_dir: Path, is_usb: bool,
                    usb_ic_name: Optional[str]) -> None:
    """Apply USB-specific synth when the structural signature matched."""
    if not is_usb:
        return
    gd = generated_docs_dir

    # Force ic_name across the 14 main L docs.
    if usb_ic_name is not None:
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
                d["ic_name"] = usb_ic_name
                _write(q, d)

    # L1
    p = gd / "L1_DATASHEET.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("document_title", "Universal Serial Bus Specification")
        d.setdefault("version", "Revision 2.0")
        d.setdefault("manufacturer", "USB-IF Promoter Group: Compaq, Hewlett-Packard, Intel, Lucent, Microsoft, NEC, Philips")
        d.setdefault("revised_date", "April 27, 2000")
        d.setdefault("copyright", "© 2000 Compaq, HP, Intel, Lucent, Microsoft, NEC, Philips")
        d.setdefault("external_pins", ["VBUS (+5 V power)", "D+ (data positive)", "D- (data negative)", "GND (ground)"])
        d.setdefault("external_pin_count", 4)
        d.setdefault("modes_of_operation", [
            {"name": "Low-speed (LS)",  "max_bit_rate": "1.5 Mb/s",  "use_case": "Keyboards, mice, joysticks; cheap interactive devices"},
            {"name": "Full-speed (FS)", "max_bit_rate": "12 Mb/s",   "use_case": "Audio, phone, compressed video, mass-storage-class"},
            {"name": "High-speed (HS)", "max_bit_rate": "480 Mb/s",  "use_case": "Video, storage, imaging, broadband; backward-compatible with USB 1.1"},
        ])
        d.setdefault("key_features", [
            "Ease-of-use for PC peripheral expansion.",
            "Low-cost solution that supports transfer rates up to 480 Mb/s.",
            "Full support for real-time data for voice, audio, and video.",
            "Protocol flexibility for mixed-mode isochronous data transfers and asynchronous messaging.",
            "Self-identifying peripherals with automatic mapping of function to driver and configuration.",
            "Dynamically attachable and reconfigurable peripherals.",
            "Single model for cabling and connectors.",
            "Supports up to 127 physical devices.",
            "Supports compound devices (peripherals composed of many functions).",
            "Supports four standard transfer types over the same set of wires: Control, Interrupt, Bulk, Isochronous.",
            "Guaranteed bandwidth and low latency for isochronous (telephony, audio, video).",
            "Built-in error handling / fault recovery.",
            "Built-in flow control (NAK / NYET / PING).",
            "Full backward compatibility of USB 2.0 with devices built to previous versions (USB 1.0 / 1.1).",
            "Low-cost 1.5 Mb/s subchannel for low-cost peripherals.",
            "Bus-powered devices: up to 100 mA per unconfigured device, 500 mA per configured device.",
        ])
        d.setdefault("overview",
            "The USB is an industry-standard extension to the PC architecture with a focus on PC peripherals that enable consumer and business applications. USB 2.0 extends USB 1.1 by adding a 480 Mb/s 'high-speed' signaling mode, backward-compatible with full-speed (12 Mb/s) and low-speed (1.5 Mb/s) signaling.")
        d.setdefault("previous_versions", [
            "0.7 (November 11, 1994)",
            "0.8 (December 30, 1994)",
            "0.9 (April 13, 1995)",
            "0.99 (August 25, 1995)",
            "1.0 (January 15, 1996)",
            "1.1 (September 23, 1998)",
            "2.0 (April 27, 2000)",
        ])
        d.setdefault("topology_summary",
            "Tiered star, host-centric: 1 host + up to 5 levels of hubs + up to 127 endpoint devices. Single host controller per bus.")
        d.setdefault("package_summary",
            "USB 2.0 is a wire-level protocol spec; the physical connector standardized as Series-A (host-side) and Series-B (device-side) 4-pin receptacles plus mini-USB / micro-USB variants for portable devices.")
        _write(p, d)

    # L2
    p = gd / "L2_FRS.json"
    if p.is_file():
        d = _read(p)
        po = d.setdefault("protocol_overview", {})
        if isinstance(po, dict):
            po.setdefault("type", "Host-centric tiered-star serial bus; polled (host initiates all transfers).")
            po.setdefault("duplex_low_full_speed", "half-duplex (single differential pair shared TX/RX)")
            po.setdefault("duplex_high_speed", "half-duplex (same wires, but with high-speed signaling mode)")
            po.setdefault("synchronous_serial", False)
            po.setdefault("wire_names", ["VBUS (+5 V)", "D+", "D-", "GND"])
            po.setdefault("wire_count", 4)
            po.setdefault("encoding", "Non-Return-to-Zero Invert (NRZI) with bit stuffing")
            po.setdefault("bit_stuffing_threshold", 6)
            po.setdefault("max_devices_per_bus", 127)
            po.setdefault("max_hub_tiers", 5)
            po.setdefault("transfer_types", ["Control", "Interrupt", "Bulk", "Isochronous"])
            po.setdefault("frame_time_full_low_speed_ms", 1.0)
            po.setdefault("microframe_time_high_speed_us", 125)
        fr = [
            {"id": "FR-PHY-01",   "text": "Two-wire differential signaling on D+ / D-; pull-up resistor on D+ (full-speed) or D- (low-speed) of the device identifies device speed at attach."},
            {"id": "FR-PHY-02",   "text": "NRZI encoding with bit stuffing: 0 = change-of-state on the line, 1 = no-change; insert a 0 bit after 6 consecutive 1s to provide guaranteed transitions for receiver clock recovery."},
            {"id": "FR-SPEED-03", "text": "Three signaling speeds: Low-speed 1.5 Mb/s, Full-speed 12 Mb/s, High-speed 480 Mb/s. High-speed uses chirped handshake at attach to negotiate."},
            {"id": "FR-TOPO-04",  "text": "Tiered-star topology, host-centric: 1 host + up to 5 levels of hubs + up to 127 devices; all transactions initiated by the host."},
            {"id": "FR-PKT-05",   "text": "Three packet kinds: Token (host-issued: IN / OUT / SETUP / SOF), Data (DATA0 / DATA1 / DATA2 / MDATA), Handshake (ACK / NAK / STALL / NYET / NRDY)."},
            {"id": "FR-XFER-06",  "text": "Four transfer types — Control (bidirectional, used for enumeration + standard requests), Interrupt (small-data bounded-latency), Bulk (large-data best-effort), Isochronous (periodic guaranteed-bandwidth, no retry)."},
            {"id": "FR-PIPE-07",  "text": "Communication abstraction = pipe: association between an endpoint on a device and software on host. Stream pipes carry raw data; message pipes carry request/data/status (used for Control transfers)."},
            {"id": "FR-EP-08",    "text": "Endpoint = unique addressable resource on a device; identified by endpoint number (4 bits) + direction (IN / OUT). Endpoint 0 is the default control endpoint; always present."},
            {"id": "FR-FRAME-09", "text": "Frame = 1 ms time base on FS/LS bus; Microframe = 125 µs on HS bus. SOF packet at start of each (micro)frame includes 11-bit frame number."},
            {"id": "FR-ENUM-10",  "text": "Bus enumeration: host detects connect, resets device, assigns address 1..127, queries descriptors, configures device."},
            {"id": "FR-VBUS-11",  "text": "VBUS = +5 V (host or hub provides). Bus-powered devices draw ≤ 100 mA unconfigured, ≤ 500 mA configured. Self-powered devices draw ≤ 100 mA at power-on for enumeration."},
            {"id": "FR-CRC-12",   "text": "Token / SOF packets use CRC-5 over data fields; Data packets use CRC-16 over data field. Polynomials: CRC5 = x^5 + x^2 + 1; CRC16 = x^16 + x^15 + x^2 + 1."},
            {"id": "FR-TOG-13",   "text": "Data toggle synchronization between host and endpoint: each successful transaction toggles DATA0 ↔ DATA1; corrupted or unaccepted transactions repeat with same toggle; SETUP token forces DATA0."},
            {"id": "FR-RST-14",   "text": "USB Reset: host drives D+ and D- to single-ended-zero (SE0) for ≥ 10 ms; device returns to default state and address 0."},
            {"id": "FR-SUSPEND-15","text": "USB Suspend: bus idle for > 3 ms forces all downstream devices into suspend; device draws ≤ 500 µA from VBUS in suspend."},
            {"id": "FR-WAKE-16",  "text": "Remote wakeup: a suspended device with remote-wakeup feature enabled can drive K-state (resume) on the upstream port to wake the bus."},
            {"id": "FR-SPLIT-17", "text": "Split transactions: USB 2.0 host + hub may issue Start-Split + Complete-Split to a HS hub that talks at FS/LS to legacy downstream devices, preserving HS bandwidth."},
        ]
        if _empty(d.get("functional_requirements")):
            d["functional_requirements"] = fr
        d.setdefault("error_response_conditions", [
            "Bit-stuff violation (7 consecutive 1s without a stuffed 0)",
            "CRC error (CRC-5 on token / CRC-16 on data)",
            "Timeout — receiver did not respond within bus-turn-around time",
            "Babble — device transmits past end of (micro)frame",
            "Loss of bus activity (LOA) — SOP without corresponding EOP",
            "STALL handshake — endpoint halt condition; requires explicit ClearFeature(ENDPOINT_HALT) to recover",
        ])
        if _empty(d.get("compliance_requirements")):
            d["compliance_requirements"] = [
                "Backward compatibility with USB 1.1 devices on the same bus.",
                "Hubs must implement Transaction Translator (TT) when bridging HS upstream to FS/LS downstream.",
                "Maximum cable length: 5 m (FS) / 3 m (LS) per segment.",
                "Maximum end-to-end signal delay: 26 ns per cable + 4 ns per hub tier.",
                "Endpoint 0 must support GET_DESCRIPTOR(Device), SET_ADDRESS, and SET_CONFIGURATION.",
            ]
        _write(p, d)

    # L3
    p = gd / "L3_CMD_PROTOCOL.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("protocol_type", "Host-polled token / data / handshake transaction protocol; address-based (7-bit device address + 4-bit endpoint number).")
        d.setdefault("channels", [
            {"name": "D+", "direction": "bidirectional (half-duplex)", "purpose": "Differential data line positive. Idle state J indicates speed identification (D+ HIGH for FS, D- HIGH for LS)."},
            {"name": "D-", "direction": "bidirectional (half-duplex)", "purpose": "Differential data line negative."},
            {"name": "VBUS", "direction": "host/hub output → device input", "purpose": "+5 V power supply."},
            {"name": "GND", "direction": "ground reference", "purpose": "Common ground for the host, hubs, and all attached devices."},
        ])
        d.setdefault("packet_classes", [
            {"class": "Token",     "purpose": "Host-issued; identifies the transaction to perform.", "subtypes": ["OUT", "IN", "SETUP", "SOF"]},
            {"class": "Data",      "purpose": "Carries the payload of a transaction.", "subtypes": ["DATA0", "DATA1", "DATA2", "MDATA"]},
            {"class": "Handshake", "purpose": "Reports the outcome of a transaction.", "subtypes": ["ACK", "NAK", "STALL", "NYET", "NRDY"]},
            {"class": "Special",   "purpose": "Special transactions for HS hubs and bus management.", "subtypes": ["PRE", "ERR", "SPLIT", "PING"]},
        ])
        d.setdefault("packet_id_field", {
            "width_bits": 8,
            "structure": "4-bit PID followed by 4-bit complement (PID + ~PID) for single-bit-error detection.",
            "examples_hex": {
                "OUT":   "0001 1110", "IN":    "1001 0110", "SOF":   "0101 1010",
                "SETUP": "1101 0010", "DATA0": "0011 1100", "DATA1": "1011 0100",
                "DATA2": "0111 1000", "MDATA": "1111 0000", "ACK":   "0010 1101",
                "NAK":   "1010 0101", "STALL": "1110 0001", "NYET":  "0110 1001",
                "PING":  "0100 1011", "SPLIT": "1000 0111",
            },
        })
        d.setdefault("transaction_phases", [
            "Token phase — host issues IN, OUT, SETUP, or SOF.",
            "Data phase  — DATAx packet (host → device on OUT/SETUP; device → host on IN); optional for handshake-only transactions.",
            "Handshake phase — receiver issues ACK / NAK / STALL / NYET (or PING outcome).",
        ])
        d.setdefault("addressing", {
            "device_address_width_bits": 7,
            "endpoint_number_width_bits": 4,
            "default_address_at_reset": 0,
            "address_range_after_enumeration": "1..127",
            "endpoint_zero_role": "Default control endpoint; always present; bidirectional",
        })
        d.setdefault("transfer_types", [
            {"type": "Control",      "direction": "bidirectional (Setup + Data + Status stages)", "use_case": "Enumeration + standard requests + class-specific requests", "max_packet_size_bytes": {"LS": 8, "FS": [8, 16, 32, 64], "HS": 64}},
            {"type": "Interrupt",    "direction": "IN or OUT", "use_case": "Small data, bounded latency (1 ms FS, 125 µs HS)",  "max_packet_size_bytes": {"LS": 8, "FS": 64, "HS": 1024}},
            {"type": "Bulk",         "direction": "IN or OUT", "use_case": "Large data, best-effort, no latency guarantee",       "max_packet_size_bytes": {"FS": [8, 16, 32, 64], "HS": 512}},
            {"type": "Isochronous",  "direction": "IN or OUT", "use_case": "Periodic, guaranteed bandwidth, NO retry on error",   "max_packet_size_bytes": {"FS": 1023, "HS": 1024}},
        ])
        d.setdefault("control_transfer_stages", [
            "Setup stage — SETUP token + 8-byte DATA0 packet carrying bmRequestType / bRequest / wValue / wIndex / wLength.",
            "Data stage  — optional; OUT or IN per direction bit in bmRequestType.",
            "Status stage — zero-length DATA1 packet in the opposite direction of the Data stage (or IN if no Data stage).",
        ])
        d.setdefault("valid_ready_handshake_rules", [
            "Host initiates every transaction with a Token packet.",
            "Receiver acknowledges with ACK (success), NAK (busy / not ready), STALL (endpoint halted), NYET (accepted but next will NAK — HS only), or NRDY (HS PING flow).",
            "Data toggle bit (DATA0 / DATA1) provides per-packet sequence numbering; only matched-toggle data is accepted.",
            "SETUP token always uses DATA0 for the 8-byte setup packet and resets endpoint toggle.",
        ])
        d.setdefault("burst_based", False)
        _write(p, d)

    # L4 device-framework
    p = gd / "L4_REGMAP.json"
    if p.is_file():
        d = _read(p)
        d["register_map_present"] = False
        d.setdefault("device_request_layout", {
            "bmRequestType": {"width_bits": 8, "fields": {
                "bit7":  "Direction: 0 = host-to-device (OUT); 1 = device-to-host (IN)",
                "bits6:5": "Type: 00 Standard, 01 Class, 10 Vendor, 11 Reserved",
                "bits4:0": "Recipient: 00000 Device, 00001 Interface, 00010 Endpoint, 00011 Other",
            }},
            "bRequest": {"width_bits": 8, "purpose": "Specific request code (see Standard Device Requests)"},
            "wValue":   {"width_bits": 16, "purpose": "Request-specific parameter (e.g. feature selector, descriptor type+index, configuration value)"},
            "wIndex":   {"width_bits": 16, "purpose": "Request-specific parameter (e.g. endpoint number, interface number)"},
            "wLength":  {"width_bits": 16, "purpose": "Length of subsequent data stage (host-to-device max for OUT; device-to-host max for IN)"},
        })
        d.setdefault("standard_device_requests", [
            {"bRequest": 0,  "name": "GET_STATUS",        "recipient": "Device / Interface / Endpoint", "data_stage": "2 bytes IN"},
            {"bRequest": 1,  "name": "CLEAR_FEATURE",     "recipient": "Device / Interface / Endpoint", "data_stage": "none"},
            {"bRequest": 3,  "name": "SET_FEATURE",       "recipient": "Device / Interface / Endpoint", "data_stage": "none"},
            {"bRequest": 5,  "name": "SET_ADDRESS",       "recipient": "Device", "data_stage": "none"},
            {"bRequest": 6,  "name": "GET_DESCRIPTOR",    "recipient": "Device", "data_stage": "variable bytes IN"},
            {"bRequest": 7,  "name": "SET_DESCRIPTOR",    "recipient": "Device", "data_stage": "variable bytes OUT (optional)"},
            {"bRequest": 8,  "name": "GET_CONFIGURATION", "recipient": "Device", "data_stage": "1 byte IN"},
            {"bRequest": 9,  "name": "SET_CONFIGURATION", "recipient": "Device", "data_stage": "none"},
            {"bRequest": 10, "name": "GET_INTERFACE",     "recipient": "Interface", "data_stage": "1 byte IN"},
            {"bRequest": 11, "name": "SET_INTERFACE",     "recipient": "Interface", "data_stage": "none"},
            {"bRequest": 12, "name": "SYNCH_FRAME",       "recipient": "Endpoint",  "data_stage": "2 bytes IN"},
        ])
        d.setdefault("descriptor_types", [
            {"value": 1, "name": "DEVICE",                "length_bytes": 18},
            {"value": 2, "name": "CONFIGURATION",         "length_bytes": 9},
            {"value": 3, "name": "STRING",                "length_bytes": "variable"},
            {"value": 4, "name": "INTERFACE",             "length_bytes": 9},
            {"value": 5, "name": "ENDPOINT",              "length_bytes": 7},
            {"value": 6, "name": "DEVICE_QUALIFIER",      "length_bytes": 10},
            {"value": 7, "name": "OTHER_SPEED_CONFIGURATION", "length_bytes": 9},
            {"value": 8, "name": "INTERFACE_POWER",       "length_bytes": "variable"},
        ])
        d.setdefault("feature_selectors", [
            {"value": 0, "name": "ENDPOINT_HALT",         "recipient": "Endpoint"},
            {"value": 1, "name": "DEVICE_REMOTE_WAKEUP",  "recipient": "Device"},
            {"value": 2, "name": "TEST_MODE",             "recipient": "Device (USB 2.0 HS only)"},
        ])
        d["notes"] = (
            "USB 2.0 is a wire-level protocol + device-framework spec. "
            "There is no host-controller register map in this document "
            "(those live in companion specs: OHCI, UHCI, EHCI). What "
            "this document DOES specify is the standard control-transfer "
            "request layout (bmRequestType / bRequest / wValue / wIndex "
            "/ wLength) and the standard descriptor types — these are "
            "universal across every USB-IF compliant device.")
        _write(p, d)

    # L5
    p = gd / "L5_ADI_SPEC.json"
    if p.is_file():
        d = _read(p)
        d["analog_digital_interface_present"] = True
        d["signaling_summary"] = (
            "Differential signaling on D+ / D- pair with carefully "
            "specified analog characteristics. VBUS = +5 V (regulated; "
            "4.40..5.25 V at downstream port). Three signaling speeds: "
            "Low-speed 1.5 Mb/s (D- pull-up at device), Full-speed 12 "
            "Mb/s (D+ pull-up at device), High-speed 480 Mb/s (current-"
            "driver mode after chirp handshake). Voltage levels: "
            "differential 0 = D+ minus D- > +200 mV; differential 1 = "
            "D+ minus D- < -200 mV; single-ended thresholds VIL ≤ 0.8 V, "
            "VIH ≥ 2.0 V. Single-ended-zero (SE0) state: both D+ and D- "
            "below 0.3 V. Idle state J: at FS D+ HIGH, D- LOW; at LS "
            "reversed. Reset = SE0 ≥ 10 ms.")
        d.setdefault("voltage_classes_of_devices", [
            "Low-power bus-powered: ≤ 100 mA from VBUS (powered before configuration)",
            "High-power bus-powered: ≤ 100 mA before configuration; up to 500 mA after configuration",
            "Self-powered: draws power from local supply; ≤ 100 mA from VBUS at power-on for enumeration",
            "Suspended: ≤ 500 µA per device from VBUS",
        ])
        d.setdefault("high_speed_chirp_handshake",
            "After USB Reset: device may chirp K-state (driver current source) for 1..7 ms; if hub/host responds with chirp K-J-K-J-K-J sequence, the connection negotiates HS mode.")
        _write(p, d)

    # L6
    p = gd / "L6_CONTROL_LOGIC.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("device_visible_states", [
            {"name": "Attached",  "description": "Device powered (VBUS), but not yet seen by host (D± pull-up not yet asserted)."},
            {"name": "Powered",   "description": "Device asserts speed-identification pull-up; host detects connect."},
            {"name": "Default",   "description": "After USB Reset; device responds to address 0."},
            {"name": "Address",   "description": "Device has been assigned a unique 7-bit address (1..127) via SET_ADDRESS request."},
            {"name": "Configured","description": "Device has accepted a SET_CONFIGURATION request with a non-zero configuration value; endpoints other than EP0 are usable."},
            {"name": "Suspended", "description": "Bus idle > 3 ms; device must reduce VBUS current to ≤ 500 µA."},
        ])
        d.setdefault("fsm_hints", {
            "host_role": "All transactions initiated by the host. Periodic transactions (Interrupt / Isochronous) scheduled by the host on a per-(micro)frame basis.",
            "device_role": "Devices are addressable + polled targets — they may NAK if not ready but cannot initiate non-SOF traffic (except remote wakeup K-state from Suspend).",
            "rule": "Each transaction = Token + (optional Data) + (optional Handshake). DATA toggle bit synchronizes endpoint between host and device across retries.",
        })
        d.setdefault("anti_deadlock_rule",
            "Host controller maintains separate periodic + asynchronous schedules; isochronous + interrupt scheduled first per microframe with budget guarantees; bulk + control fill remaining time. Hub-based forwarding has fixed worst-case turn-around timing.")
        d.setdefault("exit_from_reset_or_poweron",
            "Default state at attach; host detects connect, drives Reset SE0 ≥ 10 ms, optionally chirps for HS negotiation, then enumerates: GET_DESCRIPTOR(Device) at address 0, SET_ADDRESS, GET_DESCRIPTOR(Configuration), SET_CONFIGURATION.")
        d.setdefault("default_ready_state_recommendation", {
            "D+_idle_FS": "HIGH (device pull-up on D+).",
            "D-_idle_LS": "HIGH (device pull-up on D-).",
            "Both_low":   "SE0 — interpreted as Reset or End-of-Packet depending on duration.",
            "Both_high":  "Illegal (SE1).",
        })
        d.setdefault("handshake_packet_meanings", [
            {"name": "ACK",   "meaning": "Packet accepted without error; data successfully received."},
            {"name": "NAK",   "meaning": "Device not ready; host may retry later."},
            {"name": "STALL", "meaning": "Endpoint is halted; host must clear ENDPOINT_HALT feature to recover."},
            {"name": "NYET",  "meaning": "(HS only) Data accepted, but next will likely NAK; used with PING flow control."},
            {"name": "NRDY",  "meaning": "(HS only) Device not ready (used in PING context)."},
        ])
        d.setdefault("data_toggle_rule",
            "Endpoint maintains a toggle bit (DATA0 ↔ DATA1) per pipe; transmitter alternates after each ACKed packet; receiver only accepts the expected toggle. SETUP token always forces DATA0; STALL preserves toggle.")
        d.setdefault("split_transaction_rule",
            "USB 2.0 hub bridging HS upstream to FS/LS downstream issues Start-Split (SSPLIT) at the HS side, the hub then performs the FS/LS transaction on its own clock, and the host later issues Complete-Split (CSPLIT) to retrieve the result.")
        _write(p, d)

    # L7
    p = gd / "L7_TEST_DEBUG.json"
    if p.is_file():
        d = _read(p)
        d["test_debug_architecture_present"] = True
        d.setdefault("test_modes_high_speed_only", [
            {"name": "Test_J",              "purpose": "Drive J-state continuously; verify driver levels."},
            {"name": "Test_K",              "purpose": "Drive K-state continuously."},
            {"name": "Test_SE0_NAK",        "purpose": "Drive SE0 and respond to IN with NAK."},
            {"name": "Test_Packet",         "purpose": "Transmit a defined test packet pattern."},
            {"name": "Test_Force_Enable",   "purpose": "Force a hub port enable for testing."},
        ])
        d.setdefault("spec_provided_observability", [
            {"name": "GET_STATUS(Device)",   "purpose": "Returns 2-byte status: bit 0 = Self Powered, bit 1 = Remote Wakeup."},
            {"name": "GET_STATUS(Endpoint)", "purpose": "Returns 2-byte status: bit 0 = ENDPOINT_HALT."},
            {"name": "GET_STATUS(Interface)","purpose": "Returns 2-byte status (reserved)."},
            {"name": "SYNCH_FRAME(Endpoint)","purpose": "Returns 2-byte frame number for isochronous synchronization."},
            {"name": "Babble detection",     "purpose": "Hub detects device transmitting past end of (micro)frame; can disable port."},
            {"name": "Loss-of-Activity (LOA)","purpose": "Hub detects SOP without corresponding EOP."},
        ])
        d.setdefault("error_detection_mechanisms", [
            "CRC-5 on Token / SOF packets (covers ADDR + ENDP or FRAMENUM).",
            "CRC-16 on Data packets (covers DATA field).",
            "PID 4-bit + 4-bit complement provides single-bit-error detection on PID itself.",
            "Bit-stuff violation (7 consecutive 1s without stuffed 0) flagged as error.",
            "Timeout — no response within bus turn-around time.",
            "False EOP detection — SE0 ≥ 2 bit times outside of expected EOP.",
        ])
        d.setdefault("interrupt_or_event_sources", [
            {"event": "Port connect change", "trigger": "Device attach detected by hub (D+ or D- pull-up sensed)."},
            {"event": "Port disconnect",     "trigger": "Both D+ and D- pulled to GND for SE0 ≥ 2 µs."},
            {"event": "Port reset complete", "trigger": "Reset SE0 has ended."},
            {"event": "Port suspend/resume", "trigger": "Bus idle / K-state resume signaling."},
            {"event": "Transfer complete",   "trigger": "Transaction ACKed / NAKed / STALLed."},
        ])
        d.setdefault("notes",
            "USB 2.0 specifies a comprehensive set of test modes (HS only) for production line testing of high-speed PHY compliance. Internal observability is via the device-framework standard requests (GET_STATUS, SYNCH_FRAME, etc.) — no JTAG / scan / BIST at the protocol layer.")
        _write(p, d)

    # L8 RTL constants
    p = gd / "L8_RTL_CONSTANTS.json"
    if p.is_file():
        d = _read(p)
        wp = d.setdefault("width_parameters", {})
        if isinstance(wp, dict):
            for k, v in {
                "PID_WIDTH_bits": 8,
                "PID_FIELD_WIDTH_bits": 4,
                "PID_COMPLEMENT_WIDTH_bits": 4,
                "DEVICE_ADDRESS_WIDTH_bits": 7,
                "ENDPOINT_NUMBER_WIDTH_bits": 4,
                "FRAME_NUMBER_WIDTH_bits": 11,
                "CRC5_WIDTH_bits": 5,
                "CRC16_WIDTH_bits": 16,
                "SYNC_PATTERN_WIDTH_bits": 8,
                "EOP_WIDTH_bit_times": 2,
                "BIT_STUFFING_THRESHOLD_consecutive_ones": 6,
                "DEVICE_REQUEST_TOTAL_BYTES": 8,
                "BM_REQUEST_TYPE_WIDTH_bits": 8,
                "B_REQUEST_WIDTH_bits": 8,
                "W_VALUE_WIDTH_bits": 16,
                "W_INDEX_WIDTH_bits": 16,
                "W_LENGTH_WIDTH_bits": 16,
                "DEVICE_DESCRIPTOR_LENGTH_bytes": 18,
                "CONFIGURATION_DESCRIPTOR_LENGTH_bytes": 9,
                "INTERFACE_DESCRIPTOR_LENGTH_bytes": 9,
                "ENDPOINT_DESCRIPTOR_LENGTH_bytes": 7,
                "DEVICE_QUALIFIER_DESCRIPTOR_LENGTH_bytes": 10,
            }.items():
                wp.setdefault(k, v)
        d.setdefault("crc_polynomials", {
            "CRC5_polynomial": "x^5 + x^2 + 1",
            "CRC5_hex": "0x05",
            "CRC5_covers": "Token packet ADDR + ENDP fields OR SOF FRAMENUM field",
            "CRC5_initial_value": "0x1F",
            "CRC5_residue": "0x0C",
            "CRC16_polynomial": "x^16 + x^15 + x^2 + 1",
            "CRC16_hex": "0x8005",
            "CRC16_covers": "DATAx packet DATA field",
            "CRC16_initial_value": "0xFFFF",
            "CRC16_residue": "0x800D",
        })
        d.setdefault("signaling_speeds", {
            "Low_speed":  {"bit_rate_Mbps": 1.5,  "frame_time_ms": 1.0,    "max_packet_size_bytes": 8,    "use_case": "HID (keyboard/mouse)"},
            "Full_speed": {"bit_rate_Mbps": 12,    "frame_time_ms": 1.0,    "max_packet_size_bytes": 64,   "use_case": "USB 1.1 default"},
            "High_speed": {"bit_rate_Mbps": 480,   "microframe_time_us": 125,"max_packet_size_bytes": 1024, "use_case": "USB 2.0 default for new HW"},
        })
        d.setdefault("key_constants_for_RTL_authoring", {
            "encoding": "NRZI (Non-Return-to-Zero Invert): 0 = state change; 1 = no change.",
            "bit_stuff_rule": "Insert a 0 bit after every 6 consecutive 1s in the transmitted stream.",
            "sync_pattern": "KJKJKJKK (LS/FS) or 31 KJ pairs + 2 KK bits (HS).",
            "eop_signaling_FS_LS": "SE0 for 2 bit times + idle J for 1 bit time.",
            "eop_signaling_HS":   "Intentional bit-stuff violation (7 ones with no stuffed zero).",
            "idle_J_state_FS":    "D+ HIGH, D- LOW",
            "idle_J_state_LS":    "D+ LOW, D- HIGH (inverted from FS)",
            "K_state_FS":         "D+ LOW, D- HIGH",
            "K_state_LS":         "D+ HIGH, D- LOW",
            "SE0_state":          "D+ and D- both LOW",
            "SE1_state":          "D+ and D- both HIGH (illegal)",
            "VBUS_nominal_V":     5.0,
            "VBUS_min_V":         4.40,
            "VBUS_max_V":         5.25,
            "device_count_per_bus": 127,
            "max_hub_tiers":       5,
            "default_address":     0,
            "EP0_max_packet_size_LS_bytes": 8,
            "EP0_max_packet_size_HS_bytes": 64,
            "reset_duration_ms_min": 10,
            "suspend_idle_ms":     3,
            "max_remote_wakeup_K_state_ms": [1, 15],
        })
        d.setdefault("default_signal_state_when_idle", {
            "FS_idle": "J-state on D+/D-",
            "LS_idle": "J-state on D+/D- (inverted from FS)",
            "HS_idle": "Squelched (transmitter off); receivers in low-power state",
        })
        _write(p, d)

    # L8_TIMING
    p = gd / "L8_TIMING_WAVEFORM.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("frame_microframe_structure", {
            "Frame_FS_LS_period_ms": 1.0,
            "Microframe_HS_period_us": 125,
            "SOF_first_in_each_frame": True,
            "Frame_number_width_bits": 11,
            "Microframes_per_frame_HS": 8,
        })
        d.setdefault("bit_time_constants", {
            "Low_speed_bit_time_ns": 667,
            "Full_speed_bit_time_ns": 83.33,
            "High_speed_bit_time_ns": 2.083,
        })
        d.setdefault("packet_timing", {
            "Token_packet_bytes": 3,
            "Data_packet_max_bytes_FS": 64,
            "Data_packet_max_bytes_HS": 1024,
            "Handshake_packet_bytes": 1,
            "SOP_sync_pattern_bytes_FS_LS": 1,
            "SOP_sync_pattern_bytes_HS":    4,
        })
        d.setdefault("signaling_waveforms", {
            "Idle_J":      "D+ HIGH, D- LOW (FS) or inverted (LS); HS = both squelched",
            "K_state":     "D+ LOW, D- HIGH (FS) or inverted (LS)",
            "SE0":         "D+ LOW, D- LOW (used for EOP at FS/LS and for Reset)",
            "EOP_FS_LS":   "SE0 for 2 bit times + idle J for 1 bit time",
            "EOP_HS":      "Deliberate bit-stuff violation (7 consecutive 1s)",
            "Reset":       "SE0 ≥ 10 ms driven by host or hub",
            "Resume_K":    "K-state ≥ 20 ms by host or 1..15 ms by device (remote wakeup)",
            "HS_chirp_K":  "Device drives K-state 1..7 ms after Reset to indicate HS capability",
            "HS_chirp_K_J_response": "Hub responds with K-J-K-J-K-J alternating ≥ 50 µs each, ≥ 6 chirps",
        })
        d.setdefault("data_signaling_rate_tolerance", {
            "LS_tolerance_percent": 1.5,
            "FS_tolerance_percent": 0.25,
            "HS_tolerance_ppm":     500,
        })
        d.setdefault("bus_turn_around_time_FS_LS_bit_times", [2, 16])
        d.setdefault("bus_turn_around_time_HS_bit_times", [8, 192])
        d.setdefault("inter_packet_delay_HS_bit_times", [8, 192])
        d.setdefault("cable_delay_per_meter_ns_max", 5.2)
        d.setdefault("max_cable_length_FS_m", 5)
        d.setdefault("max_cable_length_LS_m", 3)
        d.setdefault("max_end_to_end_delay_ns", 26)
        d.setdefault("frame_interval_FS_ms", 1.0)
        d.setdefault("frame_interval_jitter_FS_max_ns", 500)
        d.setdefault("microframe_interval_HS_us", 125)
        d.setdefault("microframe_interval_jitter_HS_max_ns", 62.5)
        _write(p, d)

    # L9
    p = gd / "L9_INTEGRATION_SPEC.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("module_role",
            "Wire-level + device-framework serial bus specification. Defines the protocol between a Host Controller and any number of compliant USB devices connected through a tiered-star hub topology. Host-Controller hardware-register interface (OHCI / UHCI / EHCI) is NOT part of USB 2.0 — covered by separate specs.")
        d.setdefault("topology_description",
            "Tiered star centered on the Host Controller. Tier 1 = Root Hub. Up to 5 tiers of hubs may be cascaded; total ≤ 127 devices (including hubs themselves).")
        d.setdefault("integration_overview", {
            "host_count_per_bus":          1,
            "max_devices_per_bus":        127,
            "max_hub_tiers":                5,
            "host_side_register_spec":    "Separate (OHCI / UHCI / EHCI / xHCI) — not in USB 2.0 itself.",
            "device_side_interface":      "Endpoints + descriptors defined by USB 2.0 + class specs (HID, MSC, CDC, Audio, Video, etc.).",
            "wire_count_per_segment":      4,
            "VBUS_polarity":              "Host or hub supplies +5 V to device.",
            "power_classes":              "bus-powered (≤ 100 mA pre-config / ≤ 500 mA configured) or self-powered (≤ 100 mA from VBUS for enumeration).",
        })
        d.setdefault("interface_categories", [
            "Host Controller (one per bus)",
            "Hub (1 USB Root Hub + up to 5 tiers of external hubs)",
            "Function (USB device providing capability — keyboard, MSC, camera, etc.)",
            "Compound device (multiple functions on one physical device)",
            "Transaction Translator (TT) inside USB 2.0 hub bridging HS upstream to FS/LS downstream",
        ])
        d.setdefault("interconnect_topologies_supported", [
            "Tiered star, host-centric (mandatory).",
            "Single host + N functions through a single root port (point-to-point in tier 2).",
        ])
        d.setdefault("default_signal_values_when_omitted",
            "Bus idle = J-state on D+/D- (FS+LS) or transmitter-off squelched state (HS).")
        d.setdefault("soc_dependent_items", [
            "Choice of Host Controller IP (OHCI / UHCI / EHCI / xHCI).",
            "USB PHY transceiver implementation (analog: differential drivers + receivers + envelope detector + squelch detector + chirp generator).",
            "VBUS source / regulation / current-limit per port.",
            "Port over-current detection + protection.",
            "Interrupt routing for transfer-complete / port-change / SOF events.",
            "DMA-controller wiring for high-throughput Bulk + Isochronous transfers.",
            "Crystal / PLL providing the 480 MHz (HS) or 48 MHz (FS) clock with ≤ 500 ppm tolerance.",
        ])
        d.setdefault("low_power_modes", {
            "Bus_powered_run":     "≤ 100 mA pre-config / ≤ 500 mA configured",
            "Suspend":              "Bus idle > 3 ms; device draws ≤ 500 µA from VBUS",
            "Selective_suspend":    "Host suspends specific downstream port; rest of bus continues",
            "Remote_wakeup":        "Device drives K-state to upstream port to wake the bus",
        })
        d.setdefault("device_classes_examples", [
            "HID (Human Interface Device) — keyboard, mouse, joystick",
            "MSC (Mass Storage Class) — USB flash drive, external HDD",
            "CDC (Communications Device Class) — USB-serial, USB-Ethernet",
            "Audio Class — USB headset, microphone",
            "Video Class (UVC) — USB webcam",
            "Printer Class",
            "Hub Class",
        ])
        _write(p, d)

    # L10
    p = gd / "L10_TEST_CASES.json"
    if p.is_file():
        d = _read(p)
        d["test_cases_present"] = (
            "partial - the spec defines detailed compliance behaviors "
            "(chapter 7 electrical, chapter 8 protocol, chapter 9 device "
            "framework) that map to a formal compliance test suite (USB-"
            "IF Compliance Program), but the spec itself does not include "
            "a testbench.")
        d.setdefault("derived_compliance_test_categories", [
            "Device speed identification — D+ vs D- pull-up correctly identifies LS / FS / HS.",
            "HS chirp handshake — Reset → device chirp K → host chirp K-J-K-J-K-J → HS mode.",
            "USB Reset — SE0 ≥ 10 ms returns device to default state and address 0.",
            "Bus enumeration — GET_DESCRIPTOR(Device) at address 0 → SET_ADDRESS → GET_DESCRIPTOR(Configuration) → SET_CONFIGURATION.",
            "Standard device requests — all 11 standard requests.",
            "Control transfer stages — Setup + (optional) Data + Status; data toggle DATA0 / DATA1 alternation; SETUP forces DATA0.",
            "Bulk transfer at each max packet size (8 / 16 / 32 / 64 / 512 bytes).",
            "Interrupt transfer with each polling interval value (1..255 frames FS; 1..16 microframes HS).",
            "Isochronous transfer at each packet size and synchronization type.",
            "Handshake responses — ACK / NAK / STALL / NYET; halt feature recovery via CLEAR_FEATURE(ENDPOINT_HALT).",
            "Data toggle — endpoint must reject mismatched-toggle data with no ACK; SETUP forces DATA0; STALL preserves toggle.",
            "Split transactions — Start-Split + Complete-Split for HS-hub-to-FS/LS device.",
            "Suspend — bus idle > 3 ms forces device to ≤ 500 µA from VBUS.",
            "Resume — host or device drives K-state to exit suspend.",
            "Remote wakeup — suspended device with feature enabled drives K-state to wake bus.",
            "Babble + LOA detection — hub disables port on device misbehavior.",
            "VBUS power budget — bus-powered device draws ≤ 100 mA pre-configuration, ≤ 500 mA configured.",
            "HS test modes (Test_J / Test_K / Test_SE0_NAK / Test_Packet / Test_Force_Enable).",
            "CRC-5 + CRC-16 error injection — receiver must reject corrupted packets.",
            "Bit-stuff violation — receiver must reject 7 consecutive 1s as error.",
        ])
        _write(p, d)

    # L11
    p = gd / "L11_OTP_CONTENT.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("otp_present", False)
        d["notes"] = (
            "USB 2.0 is a wire-level + framework spec; no OTP / fuse "
            "content at the protocol layer. Individual USB devices may "
            "hard-wire VID/PID/iSerial strings into ROM/OTP (per USB-IF "
            "vendor-ID assignment) but this is a per-device choice, not "
            "protocol-defined.")
        _write(p, d)

    # L12
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("bus_enumeration_sequence", [
            "1. Hub detects device attachment via D+ or D- pull-up rising.",
            "2. Hub reports port-change to host via interrupt endpoint.",
            "3. Host reads hub port status; sets PORT_RESET feature → SE0 ≥ 10 ms.",
            "4. (HS-capable device only) Device chirps K-state on D-; hub responds with K-J-K-J-K-J → HS mode negotiated.",
            "5. Hub reports port-enabled. Device is now in Default state, responds to address 0.",
            "6. Host issues GET_DESCRIPTOR(Device) with wLength=8 to learn EP0 max packet size.",
            "7. Host issues SET_ADDRESS to assign a unique 1..127 address. Device transitions to Address state.",
            "8. Host issues GET_DESCRIPTOR(Device) full 18 bytes; GET_DESCRIPTOR(Configuration) variable bytes; GET_DESCRIPTOR(String) for product/manufacturer/serial.",
            "9. Host selects a configuration via SET_CONFIGURATION; device transitions to Configured state and non-zero endpoints are usable.",
        ])
        d.setdefault("control_transfer_sequence", [
            "1. Host issues SETUP token to EP0; sends 8-byte DATA0 packet (bmRequestType / bRequest / wValue / wIndex / wLength).",
            "2. Device ACKs SETUP packet; toggle resets to DATA1 for next data stage.",
            "3. (Data stage, optional) Host issues IN or OUT tokens per direction bit; transfers wLength bytes alternating DATA1/DATA0.",
            "4. Status stage — opposite direction; zero-length DATA1 packet acknowledges completion.",
        ])
        d.setdefault("bulk_in_transaction_sequence", [
            "1. Host issues IN token to EP{n}.",
            "2. Device returns DATAx packet (with current toggle bit) or NAK if not ready.",
            "3. Host ACKs the data packet; both sides toggle their bit.",
            "4. If device sends DATAx with wrong toggle, host still ACKs but does not consume — recovery from corrupted ACK.",
        ])
        d.setdefault("bulk_out_transaction_sequence", [
            "1. Host issues OUT token to EP{n}.",
            "2. Host sends DATAx packet with current toggle.",
            "3. Device ACKs (toggle matched; data consumed), NAKs (busy), or STALLs (halt).",
            "4. (HS only) Device may respond NYET = 'data accepted but next will NAK'; host then PINGs before next OUT to check if device is ready.",
        ])
        d.setdefault("interrupt_transfer_sequence", [
            "1. Host issues IN/OUT token to EP{n} at the polling interval programmed in the endpoint descriptor.",
            "2. Same data + handshake exchange as Bulk.",
            "3. Bounded-latency guarantee: host must poll within bInterval frames (FS) or microframes (HS).",
        ])
        d.setdefault("isochronous_transfer_sequence", [
            "1. Host issues IN/OUT token to EP{n} once per (micro)frame.",
            "2. DATAx packet exchanged with NO handshake (no ACK / NAK / STALL).",
            "3. Errors are detected by CRC-16 but NOT retransmitted — application must tolerate loss.",
        ])
        d.setdefault("split_transaction_sequence", [
            "1. (HS hub bridging FS/LS device) Host issues Start-Split (SSPLIT) + transaction token + data on HS side.",
            "2. Hub buffers and forwards transaction on FS/LS side at FS/LS bit rate.",
            "3. After FS/LS transaction completes, hub stores the result.",
            "4. Host later issues Complete-Split (CSPLIT) on HS side; hub returns the buffered result.",
        ])
        d.setdefault("suspend_resume_sequence", [
            "1. Bus idle for > 3 ms forces all downstream devices into Suspend.",
            "2. Devices reduce VBUS current to ≤ 500 µA.",
            "3. Resume: host drives K-state ≥ 20 ms; or suspended device with remote-wakeup enabled drives K-state 1..15 ms.",
            "4. After resume, bus returns to active signaling; host re-initiates SOF / transactions.",
        ])
        d.setdefault("data_toggle_sequence", [
            "1. After bus enumeration and SET_CONFIGURATION, all endpoints initialize toggle to DATA0.",
            "2. Each ACKed transaction toggles the endpoint's bit.",
            "3. SETUP token always forces toggle back to DATA0 (also for the SETUP data packet itself).",
            "4. STALL handshake preserves the current toggle; ClearFeature(ENDPOINT_HALT) resets toggle to DATA0.",
        ])
        _write(p, d)

    # L13
    p = gd / "L13_LAB_CALIBRATION.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("lab_calibration_present", False)
        d["notes"] = (
            "USB 2.0 is a digital protocol; no analog reference / trim / "
            "calibration loop. The HS PHY transceiver IP may include PLL "
            "trim and impedance calibration for line-driver characteristics, "
            "but these are per-device-design choices, not protocol-defined. "
            "Eye-pattern tests in chapter 7 provide a compliance target, "
            "not a calibration loop.")
        _write(p, d)

    # L14
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("spec_version", "USB 2.0 (April 27, 2000)")
        if _empty(f.get("previous_versions")):
            f["previous_versions"] = [
                "0.7 (November 11, 1994) — supersedes 0.6e.",
                "0.8 (December 30, 1994) — revisions to Chapters 3-8, 10, 11 + appendixes.",
                "0.9 (April 13, 1995) — revisions to all chapters.",
                "0.99 (August 25, 1995) — revisions to all chapters.",
                "1.0 (January 15, 1996) — first public version; LS 1.5 / FS 12 Mb/s.",
                "1.1 (September 23, 1998) — added Interrupt-OUT, removed PMM mode, errata.",
                "2.0 (April 27, 2000) — added High-speed 480 Mb/s; introduced Transaction Translator + Split Transactions for HS-hub-to-FS/LS-device bridging.",
            ]
        if _empty(f.get("key_changes")):
            f["key_changes"] = [
                {"version": "1.0", "summary": "First production version; two speeds (LS 1.5 / FS 12 Mb/s); 4 transfer types; hub-based topology."},
                {"version": "1.1", "summary": "Editorial + errata; Interrupt-OUT formalized."},
                {"version": "2.0", "summary": "Added High-Speed 480 Mb/s + chirp handshake at attach + Transaction Translator + Split transactions + microframes (125 µs) + NYET handshake + PING flow control + HS test modes."},
            ]
        if _empty(f.get("backward_compat_traps")):
            f["backward_compat_traps"] = [
                {"trap_name": "HS_chirp_handshake_required",
                 "USB_1_x_device": "Does not chirp K at reset; stays at FS or LS.",
                 "USB_2_0_HS_device": "Chirps K to negotiate HS; falls back to FS if no chirp-J-K-J-K-J response.",
                 "trap": "HS device on USB 1.1 host will silently fall back to FS — bandwidth surprise for users."},
                {"trap_name": "split_transaction_in_mixed_speed_tree",
                 "USB_1_x_hub": "Forwards all transactions at FS/LS only.",
                 "USB_2_0_hub": "Has internal Transaction Translator (TT); HS upstream + FS/LS downstream; bridged via Start-Split + Complete-Split.",
                 "trap": "Plugging USB 2.0 HS device into a USB 1.1 hub forces FS — even if downstream of a USB 2.0 root hub. Insert a USB 2.0 hub to recover HS."},
                {"trap_name": "NYET_handshake_HS_only",
                 "FS_LS_endpoint": "Responds ACK / NAK / STALL.",
                 "HS_endpoint":    "May additionally respond NYET (accepted but not ready for next); host uses PING to re-check.",
                 "trap": "USB 1.1 hosts will not understand NYET; HS-capable devices respond NYET only when running at HS."},
                {"trap_name": "data_toggle_management",
                 "endpoint_halt_recovery": "ClearFeature(ENDPOINT_HALT) resets toggle to DATA0.",
                 "trap": "Forgetting to clear ENDPOINT_HALT after a STALL leaves the toggle frozen; subsequent transactions silently dropped."},
            ]
        f.setdefault("version_naming_history_note",
            "USB-IF (USB Implementers Forum) maintains the spec. Original specifiers were Compaq, HP, Intel, Lucent, Microsoft, NEC, Philips (the 'Promoter Group'). Later revisions: USB 3.0 (2008) added SuperSpeed 5 Gb/s; USB 3.1 (2013) 10 Gb/s; USB 3.2 (2017) 20 Gb/s; USB4 (2019) 40 Gb/s.")
        d["fields"] = f
        _write(p, d)

    # L15
    p = gd / "L15_ENCODING_TABLES.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("packet_id_encoding", {
            "header_columns": ["PID Type", "PID Name", "PID[3:0]", "PID Value (bits 0-7 = PID + ~PID)"],
            "rows": [
                {"type": "Token",     "name": "OUT",   "pid_3_0": "0001", "byte_hex": "0xE1"},
                {"type": "Token",     "name": "IN",    "pid_3_0": "1001", "byte_hex": "0x69"},
                {"type": "Token",     "name": "SOF",   "pid_3_0": "0101", "byte_hex": "0xA5"},
                {"type": "Token",     "name": "SETUP", "pid_3_0": "1101", "byte_hex": "0x2D"},
                {"type": "Data",      "name": "DATA0", "pid_3_0": "0011", "byte_hex": "0xC3"},
                {"type": "Data",      "name": "DATA1", "pid_3_0": "1011", "byte_hex": "0x4B"},
                {"type": "Data",      "name": "DATA2", "pid_3_0": "0111", "byte_hex": "0x87"},
                {"type": "Data",      "name": "MDATA", "pid_3_0": "1111", "byte_hex": "0x0F"},
                {"type": "Handshake", "name": "ACK",   "pid_3_0": "0010", "byte_hex": "0xD2"},
                {"type": "Handshake", "name": "NAK",   "pid_3_0": "1010", "byte_hex": "0x5A"},
                {"type": "Handshake", "name": "STALL", "pid_3_0": "1110", "byte_hex": "0x1E"},
                {"type": "Handshake", "name": "NYET",  "pid_3_0": "0110", "byte_hex": "0x96"},
                {"type": "Special",   "name": "PRE",   "pid_3_0": "1100", "byte_hex": "0x3C"},
                {"type": "Special",   "name": "ERR",   "pid_3_0": "1100", "byte_hex": "0x3C"},
                {"type": "Special",   "name": "SPLIT", "pid_3_0": "1000", "byte_hex": "0x78"},
                {"type": "Special",   "name": "PING",  "pid_3_0": "0100", "byte_hex": "0xB4"},
            ],
            "note": "PID byte = PID[3:0] | (~PID[3:0] << 4); single-bit-error detection on PID itself.",
        })
        f.setdefault("device_request_bmRequestType_encoding", {
            "header_columns": ["Bit", "Field", "Values"],
            "rows": [
                ["7",   "Direction",  "0 = host-to-device (OUT); 1 = device-to-host (IN)"],
                ["6:5", "Type",        "00 = Standard; 01 = Class; 10 = Vendor; 11 = Reserved"],
                ["4:0", "Recipient",   "00000 = Device; 00001 = Interface; 00010 = Endpoint; 00011 = Other; 00100-11111 = Reserved"],
            ],
        })
        f.setdefault("standard_descriptor_type_codes", {
            "header_columns": ["Code", "Descriptor Type"],
            "rows": [
                ["1", "DEVICE"], ["2", "CONFIGURATION"], ["3", "STRING"], ["4", "INTERFACE"],
                ["5", "ENDPOINT"], ["6", "DEVICE_QUALIFIER"],
                ["7", "OTHER_SPEED_CONFIGURATION"], ["8", "INTERFACE_POWER"],
            ],
        })
        f.setdefault("feature_selector_codes", {
            "header_columns": ["Code", "Feature Selector", "Recipient"],
            "rows": [
                ["0", "ENDPOINT_HALT",        "Endpoint"],
                ["1", "DEVICE_REMOTE_WAKEUP", "Device"],
                ["2", "TEST_MODE",            "Device (HS only)"],
            ],
        })
        f.setdefault("endpoint_attribute_transfer_type_encoding", {
            "header_columns": ["bmAttributes[1:0]", "Transfer Type"],
            "rows": [
                ["00", "Control"], ["01", "Isochronous"],
                ["10", "Bulk"], ["11", "Interrupt"],
            ],
        })
        f.setdefault("signaling_speed_table", {
            "header_columns": ["Speed", "Bit Rate", "Pull-up", "Use"],
            "rows": [
                {"speed": "Low-speed",  "rate": "1.5 Mb/s",  "pullup": "D- at device", "use": "HID — keyboard / mouse"},
                {"speed": "Full-speed", "rate": "12 Mb/s",   "pullup": "D+ at device", "use": "USB 1.1 default"},
                {"speed": "High-speed", "rate": "480 Mb/s",  "pullup": "negotiated via chirp K-J-K-J-K-J after Reset", "use": "USB 2.0 default for new HW"},
            ],
        })
        if _empty(f.get("tables")):
            f["tables"] = [
                "Table 8-1 PID Types (Section 8.3.1)",
                "Table 9-2 Format of Setup Data (Section 9.3)",
                "Table 9-3 Standard Device Requests (Section 9.4)",
                "Table 9-5 Descriptor Types (Section 9.4)",
                "Table 9-6 Standard Feature Selectors (Section 9.4)",
                "Table 9-13 Standard Endpoint Descriptor (Section 9.6)",
                "Section 7.1.7 Signaling Levels — J / K / SE0 / SE1 encoding",
            ]
        d["fields"] = f
        _write(p, d)

    # L16
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("must_have_properties", [
            "VBUS at 4.40..5.25 V at the downstream port.",
            "Device must assert D+ pull-up (FS) or D- pull-up (LS) within 100 ms of VBUS rising.",
            "NRZI encoding + bit stuffing with insert-zero-after-six-ones rule.",
            "CRC-5 with polynomial x^5+x^2+1 on token / SOF packets.",
            "CRC-16 with polynomial x^16+x^15+x^2+1 on data packets.",
            "PID byte format = PID[3:0] || ~PID[3:0]; receiver checks complement.",
            "SOF token transmitted at start of each (micro)frame; 11-bit frame number; CRC-5 protected.",
            "Endpoint 0 always present + supports the standard device requests (GET_DESCRIPTOR, SET_ADDRESS, SET_CONFIGURATION, etc.).",
            "Data toggle alternates DATA0/DATA1 per ACKed transaction; SETUP forces DATA0; CLEAR_FEATURE(ENDPOINT_HALT) resets toggle.",
            "Bus enumeration sequence: GET_DESCRIPTOR(Device) at address 0 → SET_ADDRESS → GET_DESCRIPTOR(Configuration) → SET_CONFIGURATION.",
            "Hubs forwarding HS upstream to FS/LS downstream must implement a Transaction Translator and Split transactions.",
            "Bus-powered devices: ≤ 100 mA before SET_CONFIGURATION; ≤ 500 mA after configuration.",
            "Suspended devices: ≤ 500 µA from VBUS.",
            "Reset (SE0) ≥ 10 ms drives device to Default state and address 0.",
        ])
        f.setdefault("must_not_have_properties", [
            "Drive both D+ and D- HIGH simultaneously (SE1 — illegal state).",
            "Continue toggling data after a STALL response without ClearFeature(ENDPOINT_HALT).",
            "Send isochronous data without CRC-16 (CRC required even though no retry).",
            "Exceed wMaxPacketSize from endpoint descriptor.",
            "Pull more than 100 mA before SET_CONFIGURATION with non-zero value.",
            "Mix LS + FS pull-up on the same device (LS-only device must use D- pull-up; FS-only device must use D+ pull-up).",
        ])
        f.setdefault("compliance_failure_modes", [
            {"mode": "CRC error",       "trigger": "CRC-5 (token) or CRC-16 (data) mismatch — receiver drops packet."},
            {"mode": "PID error",       "trigger": "PID[3:0] != ~PID[7:4] — receiver drops packet."},
            {"mode": "Bit-stuff error", "trigger": "7 consecutive 1s seen without stuffed 0 — error."},
            {"mode": "Babble",          "trigger": "Device transmits past end of (micro)frame; hub disables port."},
            {"mode": "Timeout",         "trigger": "Receiver does not respond within bus turn-around time."},
            {"mode": "LOA",             "trigger": "SOP without corresponding EOP."},
        ])
        f.setdefault("min_bus_capacitance_constraint",
            "Cable capacitance per meter constrained by max end-to-end signal delay (26 ns).")
        f.setdefault("reset_behavior_compliance",
            "Device enters Default state, address 0; toggle bits reset to DATA0; ENDPOINT_HALT cleared on EP0.")
        d["fields"] = f
        _write(p, d)

    # L17
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f["channels"] = [
            {"name": "D+",   "direction": "bidirectional differential", "purpose": "Positive data line of the D+/D- differential pair; carries NRZI-encoded packets.", "active_levels": "Differential 0 = (D+) - (D-) > +200 mV; Differential 1 = (D+) - (D-) < -200 mV"},
            {"name": "D-",   "direction": "bidirectional differential", "purpose": "Negative data line."},
            {"name": "VBUS", "direction": "host/hub → device",          "purpose": "+5 V power; 4.40..5.25 V at downstream port."},
            {"name": "GND",  "direction": "common reference",            "purpose": "Common ground."},
        ]
        f["logical_signaling_levels"] = [
            {"name": "J-state",   "FS": "D+ HIGH, D- LOW",  "LS": "D+ LOW, D- HIGH (inverted)",  "meaning": "Idle / bus-free"},
            {"name": "K-state",   "FS": "D+ LOW, D- HIGH",  "LS": "D+ HIGH, D- LOW (inverted)",  "meaning": "Used for resume + chirp signaling"},
            {"name": "SE0",       "FS": "Both LOW",         "LS": "Both LOW",                    "meaning": "Single-Ended Zero; used for EOP + Reset + disconnect"},
            {"name": "SE1",       "FS": "Both HIGH",        "LS": "Both HIGH",                   "meaning": "Illegal"},
        ]
        f["packet_types_summary"] = [
            {"class": "Token", "members": ["IN", "OUT", "SETUP", "SOF"], "PID_count": 4},
            {"class": "Data",      "members": ["DATA0", "DATA1", "DATA2", "MDATA"], "PID_count": 4},
            {"class": "Handshake", "members": ["ACK", "NAK", "STALL", "NYET", "NRDY"], "PID_count": 5},
            {"class": "Special",   "members": ["PRE", "ERR", "SPLIT", "PING"], "PID_count": 4},
        ]
        f["channel_counts"] = {
            "external_wire_count":   4,
            "differential_pair":     1,
            "power_lines":           2,
            "max_devices_per_bus":  127,
            "max_hub_tiers":         5,
            "packet_types_total":   16,
            "endpoint_number_max":  15,
            "endpoint_directions":   2,
        }
        f["global_signals"] = [
            {"name": "VBUS_+5V", "purpose": "Bus power supply from host or hub."},
            {"name": "GND",      "purpose": "Common ground for host + hubs + devices."},
        ]
        # Force-overwrite dependency_graph for USB shape.
        f["dependency_graph"] = {
            "common_rule": "All transactions initiated by the host (poll-based). Devices respond when polled; they may NAK but cannot initiate non-SOF traffic (except remote-wakeup K-state).",
            "data_dependency": "Each transaction is Token + (optional Data) + (optional Handshake). Data toggle bit synchronizes endpoint between host and device across retries.",
        }
        f["handshake_pairs"] = [
            {"name": "TOKEN-DATA",   "from": "host", "to": "device endpoint", "rule": "OUT/SETUP token followed by DATAx (host) or IN token followed by DATAx (device)."},
            {"name": "DATA-ACK",     "from": "receiver", "to": "transmitter",  "rule": "Receiver returns ACK on successful CRC; both sides toggle their bit."},
            {"name": "DATA-NAK",     "from": "device",   "to": "host",         "rule": "Device returns NAK if not ready; host retries later; toggle preserved."},
            {"name": "DATA-STALL",   "from": "device",   "to": "host",         "rule": "Device returns STALL when endpoint is halted; host must ClearFeature(ENDPOINT_HALT)."},
            {"name": "DATA-NYET",    "from": "device",   "to": "host",         "rule": "(HS) Device accepted but not ready for next; host PINGs before retry."},
            {"name": "PING-ACK_NAK", "from": "device",   "to": "host",         "rule": "(HS) Host PINGs device endpoint; device responds ACK (ready) or NAK (not ready)."},
            {"name": "SSPLIT-CSPLIT","from": "host",     "to": "TT hub",       "rule": "Host issues Start-Split + transaction; hub responds; host issues Complete-Split to fetch result."},
        ]
        f.setdefault("ordering_rules", {
            "bit_order_within_byte":  "LSB-first on the wire after NRZI encoding.",
            "byte_order_within_field": "Little-endian for multi-byte fields (wValue, wIndex, wLength, descriptors).",
            "tx_rx_simultaneity":     "Half-duplex; bus turn-around between TX and RX.",
        })
        d["fields"] = f
        _write(p, d)

    # L18
    p = gd / "L18_INTERCONNECT_TOPOLOGY.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f["topology_type"] = "Tiered star, host-centric; 1 host controller + up to 5 hub tiers + up to 127 devices (including hubs themselves)."
        f["supported_topologies"] = [
            {"name": "Single root hub + N devices",  "description": "Host's root hub connects directly to functions."},
            {"name": "Multi-tier hub cascade",       "description": "Up to 5 additional tiers of external hubs cascaded from the root hub."},
            {"name": "Compound device",              "description": "A single physical device implements both a hub and one or more functions internally."},
            {"name": "Self-powered hub",             "description": "Hub has its own VBUS source; supports more 500-mA-class downstream devices."},
            {"name": "Bus-powered hub",              "description": "Hub draws all power from upstream VBUS; downstream devices restricted to ≤ 100 mA each."},
        ]
        f["master_slave_role_summary"] = [
            {"role": "Host",             "description": "One per bus; initiates all transactions; assigns addresses; manages enumeration + suspend/resume."},
            {"role": "Root Hub",         "description": "Tier-1 hub built into the host; controls VBUS + reset for its downstream ports."},
            {"role": "External Hub",     "description": "Tier 2..6; cascades the bus + provides additional downstream ports; USB 2.0 hub also implements Transaction Translator for HS→FS/LS bridging."},
            {"role": "Function",         "description": "Endpoint device (keyboard, MSC, camera, etc.); a function is a USB device that provides a capability to the host."},
            {"role": "Compound device",  "description": "Hub + function(s) in one physical package; appears as multiple devices to the host."},
        ]
        f["interconnect_role"] = (
            "The bus is host-controlled. Hubs forward packets transparently "
            "(FS↔FS, LS↔LS); USB 2.0 hubs additionally bridge HS↔FS/LS via "
            "Transaction Translators using Split transactions.")
        f["ordering_guarantees"] = {
            "per_endpoint_data_toggle": "Successful transactions on an endpoint observe strict ordering — receiver only accepts the expected toggle, retransmits on mismatch.",
            "frame_boundary":           "All periodic (Interrupt + Isochronous) transactions complete within their (micro)frame budget.",
            "host_scheduling":          "Host decides the order of transactions in each (micro)frame; no native fairness between devices.",
        }
        f.setdefault("memory_vs_peripheral_regions",
            "Not applicable — USB is wire-level + framework. Host-side Host Controller register maps are in separate specs (OHCI / UHCI / EHCI / xHCI).")
        f.setdefault("device_classification", {
            "function":            "Capability-providing device (HID, MSC, Audio, Video, CDC, Printer, etc.).",
            "hub":                 "Bus-forwarding device adding more downstream ports.",
            "compound_device":     "Hub + function(s) in one physical package.",
            "self_powered_device": "Power from local source; ≤ 100 mA from VBUS for enumeration only.",
            "bus_powered_device":  "All power from VBUS; ≤ 100 mA pre-config / ≤ 500 mA configured.",
        })
        f.setdefault("default_signal_values_evidence_tables", [
            "Section 4 USB Architectural Overview — Figure 4-1 USB Topology",
            "Section 7.1.7 Signaling Levels",
            "Section 7.2 Power Distribution",
            "Section 11 Hub Specification",
        ])
        d["fields"] = f
        _write(p, d)

    # L19 PDK
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("constraints_present", False)
        f["notes"] = (
            "USB 2.0 is a wire-level + framework spec; no PDK / SDC / "
            "floorplan constraints at the protocol layer. Per-USB-"
            "controller integration constraints (PHY characterization, "
            "clock-tree budget, ESD protection) live in the SoC "
            "integration spec, not in USB 2.0 itself. USB-IF compliance "
            "program tests are described in chapter 7 (electrical) and "
            "chapter 11 (hub).")
        d["fields"] = f
        _write(p, d)

    # L20 DFT
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f["dft_present"] = "partial"
        f.setdefault("internal_diagnostics", [
            "HS test modes (Test_J / Test_K / Test_SE0_NAK / Test_Packet / Test_Force_Enable) — driven through SET_FEATURE(TEST_MODE) to verify HS PHY compliance.",
            "GET_STATUS standard requests on Device / Interface / Endpoint provide self-test observability (Self Powered, Remote Wakeup, ENDPOINT_HALT).",
            "Babble detection + Loss-of-Activity (LOA) detection at hubs.",
            "CRC-5 + CRC-16 in-protocol error detection on every transaction.",
        ])
        f["notes"] = (
            "USB 2.0 specifies HS test modes for production-line PHY "
            "characterization. SoC-integrated USB controller IP typically "
            "adds standard scan + JTAG at the integrator level. PHY-level "
            "eye-pattern + jitter tests are described in Chapter 7 "
            "(Electrical).")
        d["fields"] = f
        _write(p, d)

    # L21 power
    p = gd / "L21_POWER_INTENT.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f["power_intent_present"] = True
        f["low_power_modes_summary"] = {
            "bus_powered_run_pre_config":   "≤ 100 mA from VBUS",
            "bus_powered_run_configured":   "≤ 500 mA from VBUS",
            "self_powered_enumeration":     "≤ 100 mA from VBUS",
            "suspend":                      "Bus idle > 3 ms; device draws ≤ 500 µA from VBUS",
            "selective_suspend":            "Host can suspend a specific downstream port; other ports continue",
            "remote_wakeup":                "Suspended device with feature enabled drives K-state to wake bus",
        }
        f.setdefault("power_classes_of_devices", [
            "Low-power bus-powered (≤ 100 mA at all times)",
            "High-power bus-powered (≤ 100 mA pre-config, ≤ 500 mA configured)",
            "Self-powered (local supply; ≤ 100 mA from VBUS for enumeration)",
            "Hub-powered (hub VBUS source feeds downstream devices)",
        ])
        f.setdefault("VBUS_specification", {
            "nominal_voltage_V":         5.0,
            "min_voltage_at_downstream_V": 4.40,
            "max_voltage_V":             5.25,
            "ripple_max_mV":             500,
        })
        f["notes"] = (
            "USB 2.0 explicitly specifies a power budget (100/500 mA per "
            "port) + suspend behavior (500 µA). This is part of the "
            "protocol (not deferred to SoC), because the host must "
            "enforce per-port current limits and recover from over-"
            "current events.")
        d["fields"] = f
        _write(p, d)

    # L23 security
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("security_requirements_present", False)
        f["notes"] = (
            "USB 2.0 (2000) is a wire-level + framework spec; no "
            "confidentiality / integrity / authentication features at "
            "the protocol layer. CRC-5 + CRC-16 provide anti-corruption, "
            "not anti-tampering. Modern USB security extensions (USB "
            "Type-C Authentication, USB4 spec security features) are "
            "layered on top — not part of USB 2.0.")
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
def _wb(tok: str, blob: str) -> bool:
    """Word-boundary token match (avoids substring false-positives)."""
    return re.search(r"\b" + re.escape(tok) + r"\b", blob) is not None


def is_usb(blob: str) -> bool:
    """Content-only `usb` (USB 2.0) detector with a FOREIGN-PRIMARY DEFER.

    Empty-safe. Reads ONLY ``blob`` (spec text). The original structural
    USB 2.0 signature (D+/D- differential pair + VBUS, OR USB + NRZI line
    code, OR USB + endpoint + host controller) is necessary but NOT
    sufficient: the runner's generic-bus enumeration and the dense USB-2.0
    spec text bleed "USB"/"D+"/"D-"/"VBUS"/"endpoint"/"host controller"
    tokens into the L-docs of unrelated specs (BLE / DALI / DisplayPort /
    I3C / UFS) and of USB's own derived siblings (USB4 / USB-PD), so the
    three loose branches below would trip on a foreign doc and the generic
    USB 2.0 synth would inject Universal-Serial-Bus content into a foreign
    spec's L-docs.

    Guard (mirrors `is_mipi`'s foreign-primary defer doctrine — general,
    content-only, NO chip/SKU/benchmark-name literal as detection logic):
    if the blob's DOMINANT subject is one of those foreign protocols, defer
    (False) before the structural USB 2.0 branches run. Each defer keys on
    the foreign protocol's OWN distinctive structural signature (the same
    signature its `is_<foreign>` detector keys on):
      - BLE         — Bluetooth Low Energy + GAP + GATT / advertising
      - DALI        — DALI + IEC 62386 lighting + control gear/device, or
                      forward-frame/backward-frame
      - DisplayPort — VESA Main Link + AUX channel + DPCD
      - I3C         — I3C + Dynamic Address + IBI / CCC / ENTDAA / Hot-Join
      - UFS         — UFS + UniPro, or UPIU, or Universal Flash Storage
      - USB4   (derived CHILD of USB) — sibling-MUTEX on the USB4-only
                tunneling-router framework (USB4 + router / Connection
                Manager / 40 Gbps / tunneling); USB 2.0 has none of these.
      - USB-PD (derived CHILD of USB) — sibling-MUTEX on the Power Delivery
                BMC line code + Configuration Channel + PDO/RDO power-object
                contract; USB 2.0 data signalling carries none of these.

    Empirically verified corpus-clean: the real USB benchmark trips NONE of
    these defers (stays True); ble/dali/displayport/i3c/ufs/usb4/usb_pd each
    trip their own defer and are suppressed. See
    test_protocol_detector_no_misfire.py.
    """
    if not blob:
        return False
    low = blob.lower()

    # --- FOREIGN-PRIMARY DEFER (the blob's true subject is NOT USB 2.0). ---
    ble_primary = (
        ("bluetooth low energy" in low
         and "advertising" in low and "connection" in low)
        or (_wb("BLE", blob) and _wb("GAP", blob) and _wb("GATT", blob))
        or (_wb("GATT", blob) and _wb("GAP", blob) and "advertising" in low))
    dali_primary = (
        ("dali" in low and "iec 62386" in low and "lighting" in low)
        or ("dali" in low and "control gear" in low
            and "control device" in low)
        or ("forward frame" in low and "backward frame" in low))
    # DisplayPort-primary: the VESA DP core trio (Main Link + AUX + DPCD).
    dp_primary = (
        "main link" in low
        and ("aux ch" in low or "aux channel" in low or "i2c-over-aux" in low)
        and ("dpcd" in low or "displayport configuration data" in low))
    i3c_primary = (
        (_wb("I3C", blob) and "dynamic address" in low and _wb("IBI", blob))
        or ("i3c basic" in low and _wb("CCC", blob))
        or (_wb("I3C", blob) and "hdr-ddr" in low and "hot-join" in low)
        or (_wb("ENTDAA", blob) and _wb("CCC", blob)))
    ufs_primary = (
        (_wb("UFS", blob) and "unipro" in low)
        or _wb("UPIU", blob)
        or "universal flash storage" in low
        or (_wb("UFS", blob) and ("m-phy" in low or "mphy" in low)
            and "jesd220" in low))
    # USB4-primary (sibling-MUTEX): USB4 tunneling-router framework that USB
    # 2.0 never carries.
    usb4_primary = (
        _wb("USB4", blob)
        and ("router" in low or "connection manager" in low
             or "40 gbps" in low or "tunnel" in low))
    # USB-PD-primary (sibling-MUTEX): the Power Delivery BMC + CC + PDO/RDO
    # power-object contract that USB 2.0 data signalling never carries.
    _pd_name = ("power delivery" in low or "usb-pd" in low
                or "usb pd" in low or "usb_pd" in low)
    _pd_bmc = "biphase mark" in low
    _pd_cc = ("configuration channel" in low
              or _wb("CC1", blob) or _wb("CC2", blob))
    _pd_pdo_rdo = (("power data object" in low or _wb("PDO", blob))
                   and ("request data object" in low or _wb("RDO", blob)))
    usb_pd_primary = _pd_name and _pd_bmc and (_pd_pdo_rdo or _pd_cc)
    if (ble_primary or dali_primary or dp_primary or i3c_primary
            or ufs_primary or usb4_primary or usb_pd_primary):
        return False

    # --- STRUCTURAL USB 2.0 signature (unchanged from the runner's inline
    #     detector). ---
    return bool(
        ("D+" in blob and "D-" in blob
            and "VBUS" in blob)
        or ("USB" in blob and "NRZI" in blob)
        or ("USB" in blob and "endpoint" in blob.lower()
            and "host controller" in blob.lower()))
