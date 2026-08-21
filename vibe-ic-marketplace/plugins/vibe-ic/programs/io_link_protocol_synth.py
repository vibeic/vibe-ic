"""IO-Link (IEC 61131-9 / SDCI) protocol synth helper.

ic_class-gated overlay for the IO-Link structural signature: a point-to-point,
single-drop, serial digital communication interface for one sensor or actuator
per IO-Link Master port, standardized as IEC 61131-9 under the name SDCI
(Single-drop Digital Communication Interface). IO-Link is NOT a fieldbus and
NOT a bus: each Device connects point-to-point to one Master port over a single
three-wire cable — L+ (24 V supply), L- (ground), and C/Q (the combined
communication and switching signal line). The C/Q line carries either a binary
switching signal in Standard IO (SIO) mode or UART-based half-duplex
communication frames in SDCI (communication) mode. Communication reuses UART
8-E-1 character framing (1 start, 8 data, 1 even parity, 1 stop) at one of three
rates: COM1 = 4.8 kbaud, COM2 = 38.4 kbaud, COM3 = 230.4 kbaud. The Master
issues a wake-up request that switches the Device from SIO mode to SDCI mode.
Master and Device then exchange M-sequences (a Master message + a Device
response, TYPE_0/1/2, with the CKT/CKS checksums). Data is cyclic Process Data
(PD, up to 32 bytes), acyclic On-request Data via the ISDU (Indexed Service Data
Unit, Index/Subindex), and Events (diagnostics); each Device is described by an
IODD (IO Device Description, XML), declares a minimum cycle time, and is driven
through STARTUP / PREOPERATE / OPERATE states by the MasterCommand. Applies the
IEC 61131-9 (SDCI) spec-canonical content to L1-L23.

Doctrine — GENERAL not keyword: detection uses canonical STRUCTURAL signatures
(SDCI / single-drop digital communication interface + the C/Q combined
communication and switching line + the wake-up request SIO<->SDCI mode switch +
COM1/COM2/COM3 + M-sequence + CKT/CKS + ISDU Index/Subindex + Process Data +
IODD) read from the L-doc / input_doc CONTENT blob only. It NEVER reads the
input-document filename or the benchmark folder name, and — critically — it
NEVER keys on the bare English words "io" or "link" (e.g. "the IO is linked to
the bus"); it keys on IO-Link-structural tokens (SDCI / IEC 61131-9 + C/Q line +
wake-up + SIO/SDCI mode + M-sequence + ISDU + IODD).

Sibling disambiguation — IO-Link vs plain UART and SENT (the single-wire serial
family). IO-Link reuses UART 8-E-1 character framing but is NOT a plain UART
link: a plain UART link has only asynchronous start/stop framing on TX/RX wires
with no C/Q dual-mode line, no wake-up request, no SIO<->SDCI mode switch, no
M-sequences, no CKT/CKS, and no ISDU. SENT (SAE J2716) encodes data as nibble
pulse widths in ticks on a single wire with a 56-tick calibration pulse — no
UART octets, no COM1/COM2/COM3, no C/Q, no wake-up, no M-sequence, no ISDU. The
detector REQUIRES the IO-Link-only structural vocabulary and DEFERS when the doc
is plain-UART-primary (just async serial framing, no C/Q / wake-up / M-sequence
/ ISDU) or SENT-primary (nibble / tick / SAE J2716), so it cannot false-fire on
a UART or SENT spec.

Public entry: ``apply_io_link_synth(generated_docs_dir, is_io_link, io_link_ic_name)``.
Module-level ``is_io_link(blob)`` is the content-only detector.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import l_doc_generator_stamp as _stamp


def _empty(v) -> bool:
    return v in (None, {}, []) or (isinstance(v, str) and not v.strip())


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

# Canonical IO-Link facts (IEC 61131-9 — SDCI).
_SUPPLY_V = 24                     # L+ nominal supply voltage
_COM1_KBAUD = 4.8
_COM2_KBAUD = 38.4
_COM3_KBAUD = 230.4
_UART_DATA_BITS = 8
_UART_PARITY = "even"
_UART_START_BITS = 1
_UART_STOP_BITS = 1
_UART_BITS_PER_CHAR = 11           # 1 start + 8 data + 1 parity + 1 stop
_PD_MAX_BYTES = 32                 # Process Data max bytes per direction
_MAX_CABLE_M = 20
_DEVICE_STATES = ["STARTUP", "PREOPERATE", "OPERATE"]
_M_SEQUENCE_TYPES = ["TYPE_0", "TYPE_1", "TYPE_2"]
_THREE_WIRES = ["L+ (24 V supply)", "L- (ground / 0 V return)",
                "C/Q (combined communication and switching signal line)"]


def is_io_link(blob: str) -> bool:
    """Content-only IO-Link (IEC 61131-9 / SDCI) detector with a UART/SENT MUTEX.

    Fire on the IO-Link structural signature: a point-to-point single-drop
    serial digital communication interface (SDCI / IEC 61131-9) on a three-wire
    L+/L-/C-Q cable where the C/Q combined communication and switching line is
    switched from SIO (Standard IO) mode to SDCI (communication) mode by a
    wake-up request, UART 8-E-1 octets are exchanged at COM1/COM2/COM3 in
    M-sequences (Master message + Device response, CKT/CKS checksums), with
    cyclic Process Data, acyclic On-request Data via the ISDU (Index/Subindex),
    Events, and an IODD. Defer if the doc is plain-UART-primary (async start/stop
    framing only, no C/Q / wake-up / M-sequence / ISDU) or SENT-primary
    (nibble / tick / SAE J2716), so a UART or SENT spec cannot false-fire. Reads
    ONLY the spec text `blob` — never a filename or benchmark name — and NEVER
    keys on the bare English words "io" or "link".
    """
    if not blob:
        return False
    low = blob.lower()

    # --- IO-Link-only NAME tokens (structural, NOT the bare words "io"/"link"). ---
    # word-boundary structural spec identifiers, absent from plain UART / SENT.
    name_token = (
        "sdci" in low
        or "single-drop digital communication interface" in low
        or "single drop digital communication interface" in low
        or "iec 61131-9" in low
        or "iec61131-9" in low
        or "io-link" in low
        or "io link" in low
    )

    # --- IO-Link-only STRUCTURAL tokens. ---
    # The C/Q combined communication + switching signal line (the defining wire).
    cq_line = (
        "c/q" in low
        or "combined communication and switching" in low
        or "combined communication + switching" in low
    )
    # Wake-up request that switches SIO -> SDCI.
    wakeup = (
        "wake-up request" in low or "wakeup request" in low
        or "wake up request" in low
        or ("wake-up" in low and ("sio" in low or "sdci" in low))
        or "wurq" in low
    )
    # SIO (Standard IO) mode <-> SDCI (communication) mode.
    sio_sdci_mode = (
        ("sio" in low and "sdci" in low)
        or ("standard io" in low and ("sdci" in low or "communication mode" in low))
    )
    # M-sequence (message sequence) with CKT/CKS checksums.
    m_sequence = (
        "m-sequence" in low or "m sequence" in low or "msequence" in low
        or "message sequence" in low
    )
    ckt_cks = (
        ("ckt" in low and "cks" in low)
        or ("checksum" in low and m_sequence)
    )
    # ISDU (Indexed Service Data Unit) via Index/Subindex.
    isdu = (
        "isdu" in low
        or "indexed service data unit" in low
        or ("index" in low and "subindex" in low and name_token)
    )
    # Cyclic Process Data + acyclic On-request Data.
    process_data = (
        "process data" in low
        or ("cyclic" in low and "acyclic" in low and name_token)
    )
    on_request_data = "on-request data" in low or "on request data" in low
    # IODD (IO Device Description, XML).
    iodd = (
        "iodd" in low
        or "io device description" in low
    )
    # COM1/COM2/COM3 baud rates.
    com_rates = (
        ("com1" in low and "com2" in low and "com3" in low)
        or ("4.8 kbaud" in low and "38.4 kbaud" in low)
        or "230.4 kbaud" in low
    )
    # UART 8-E-1 framing.
    uart_framing = (
        ("8-e-1" in low or "8 e 1" in low)
        or ("even parity" in low and ("start bit" in low or "stop bit" in low))
    )
    # Master/Device (master/slave) role pair.
    master_device = (
        ("io-link master" in low and "io-link device" in low)
        or ("master" in low and "device" in low and name_token)
    )
    # Three-wire L+/L-/C-Q.
    three_wire = (
        ("l+" in low and "l-" in low and cq_line)
        or ("three-wire" in low and cq_line)
        or ("three wire" in low and cq_line)
    )

    # --- Sibling MUTEX (defer paths). ---
    # SENT-primary: nibble pulse-width / tick / SAE J2716 with NO IO-Link
    # structure (no C/Q, no wake-up, no M-sequence, no ISDU).
    sent_primary = (
        ("sae j2716" in low or "single edge nibble transmission" in low
         or ("nibble" in low and "tick" in low))
        and not (name_token or cq_line or m_sequence or isdu or sio_sdci_mode)
    )
    if sent_primary:
        return False

    # Plain-UART-primary: async start/stop UART framing only, with NO IO-Link
    # structure (no C/Q line, no wake-up, no SIO/SDCI mode, no M-sequence, no
    # ISDU). A bare "uart" / "16550" doc must not fire.
    uart_primary = (
        ("uart" in low or "16550" in low or "asynchronous receiver" in low)
        and not (name_token or cq_line or wakeup or sio_sdci_mode
                 or m_sequence or isdu)
    )
    if uart_primary:
        return False

    # --- Structural core. ---
    # The IO-Link wire-level signature: the C/Q dual-mode line + the wake-up
    # SIO->SDCI switch + M-sequences. This is canonical IO-Link; UART/SENT do
    # not have it.
    io_link_structure = (
        cq_line
        and (wakeup or sio_sdci_mode)
        and (m_sequence or isdu or process_data)
    )

    # --- Fire decision. ---
    # Require BOTH an IO-Link name token AND the structural signature, OR a very
    # strong structure (name token may be implicit) anchored by the C/Q line +
    # wake-up SIO/SDCI mode switch + M-sequence + (ISDU or Process Data).
    return bool(
        (name_token and io_link_structure)
        or (name_token and cq_line and (wakeup or sio_sdci_mode)
            and (m_sequence or isdu) and (com_rates or uart_framing))
        or (io_link_structure and m_sequence and isdu
            and (com_rates or three_wire))
    )


def apply_io_link_synth(generated_docs_dir: Path, is_io_link_flag: bool,
                        io_link_ic_name: Optional[str]) -> None:
    """Apply IEC 61131-9 (SDCI) IO-Link synth when the IO-Link signature matched."""
    if not is_io_link_flag:
        return
    gd = Path(generated_docs_dir)

    # --- Force ic_name across ALL 24 docs FIRST (main + fields docs). ---
    if io_link_ic_name is not None:
        for n in _MAIN_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                d["ic_name"] = io_link_ic_name
                _write(q, d)
        for n in _FIELDS_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                f = _ensure_dict(d, "fields")
                f["ic_name"] = io_link_ic_name
                d["ic_name"] = io_link_ic_name
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
# L1 — IO-Link datasheet header + headline facts.
# ----------------------------------------------------------------------
def _l1(gd: Path) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    d["document_title"] = (
        "IO-Link Interface (SDCI — Single-drop Digital Communication Interface)")
    d["version"] = "IEC 61131-9 (SDCI — Single-drop Digital Communication Interface)"
    d["revised_date"] = "IEC 61131-9"
    d["manufacturer"] = "IEC / IO-Link Community"
    d["copyright"] = "© IEC / IO-Link Community"
    d["abstract"] = (
        "IO-Link is a point-to-point, serial, digital communication interface "
        "for connecting individual sensors and actuators to an IO-Link Master, "
        "standardized as IEC 61131-9 under the name SDCI (Single-drop Digital "
        "Communication Interface). IO-Link is NOT a fieldbus and NOT a bus: each "
        "IO-Link Device connects point-to-point to one Master port over a single "
        "three-wire cable (max 20 m) — L+ (24 V supply), L- (ground), and C/Q "
        "(the combined communication and switching signal line). The C/Q line "
        "carries a binary switching signal in Standard IO (SIO) mode or "
        "UART-based half-duplex communication frames in SDCI (communication) "
        "mode. Communication reuses UART 8-E-1 character framing (1 start, 8 "
        "data, 1 even parity, 1 stop) at one of three rates: COM1 = 4.8 kbaud, "
        "COM2 = 38.4 kbaud, COM3 = 230.4 kbaud. The Master issues a wake-up "
        "request that switches the Device from SIO mode to SDCI mode; Master and "
        "Device then exchange M-sequences (a Master message + a Device response, "
        "TYPE_0/1/2) protected by the CKT/CKS checksums. Data is cyclic Process "
        "Data (up to 32 bytes), acyclic On-request Data via the ISDU (Indexed "
        "Service Data Unit, Index/Subindex), and Events (diagnostics); each "
        "Device is described by an IODD (IO Device Description, XML), declares a "
        "minimum cycle time, and is driven through STARTUP / PREOPERATE / "
        "OPERATE states by the MasterCommand.")
    d["keywords"] = [
        "IO-Link", "SDCI", "Single-drop Digital Communication Interface",
        "IEC 61131-9", "C/Q", "C/Q line", "combined communication and switching",
        "L+", "L-", "three-wire", "wake-up request", "SIO", "Standard IO",
        "SDCI mode", "M-sequence", "message sequence", "CKT", "CKS", "checksum",
        "COM1", "COM2", "COM3", "4.8 kbaud", "38.4 kbaud", "230.4 kbaud",
        "8-E-1", "even parity", "Process Data", "On-request Data", "ISDU",
        "Indexed Service Data Unit", "Index", "Subindex", "Event", "IODD",
        "IO Device Description", "MasterCommand", "MinCycleTime", "STARTUP",
        "PREOPERATE", "OPERATE", "IO-Link Master", "IO-Link Device",
        "point-to-point", "sensor", "actuator",
    ]
    d["external_pins"] = [
        "L+: 24 V DC device supply (pin 1 on a standard M12 A-coded connector)",
        "L-: ground / 0 V supply return (pin 3)",
        "C/Q: combined communication and switching signal line — the single "
        "IO-Link signal wire; SIO switching signal or SDCI UART communication "
        "(pin 4)",
        "Q (optional): additional digital output / input (pin 2)",
    ]
    d["supply_voltage_v"] = _SUPPLY_V
    d["com_rates_kbaud"] = {"COM1": _COM1_KBAUD, "COM2": _COM2_KBAUD,
                            "COM3": _COM3_KBAUD}
    d["uart_framing"] = "8-E-1 (1 start, 8 data, 1 even parity, 1 stop)"
    d["process_data_max_bytes"] = _PD_MAX_BYTES
    d["max_cable_length_m"] = _MAX_CABLE_M
    d["modes_of_operation"] = [
        {"name": "SIO (Standard IO)",
         "role": "binary switching signal on the C/Q line",
         "note": "The Device powers up in SIO mode; the C/Q line behaves as a "
                 "conventional digital sensor switching output/input, so an "
                 "IO-Link Device is backward compatible with a plain digital "
                 "input card."},
        {"name": "SDCI (communication)",
         "role": "UART-based serial communication on the C/Q line",
         "note": "After the Master's wake-up request the Device switches into "
                 "SDCI mode and exchanges M-sequences (Process Data, On-request "
                 "Data, Events) with the Master."},
    ]
    d["key_features"] = [
        "Point-to-point single-drop digital communication interface (SDCI, IEC "
        "61131-9): one Device per IO-Link Master port; NOT a fieldbus, NOT a "
        "bus, no multi-drop, no on-wire Device addressing.",
        "Three-wire cable (max 20 m, unshielded): L+ (24 V), L- (ground), and "
        "C/Q (combined communication and switching signal line).",
        "Dual-mode C/Q line: binary switching in SIO (Standard IO) mode, "
        "UART-based serial communication in SDCI (communication) mode.",
        "Wake-up request from the Master switches the Device from SIO mode to "
        "SDCI mode; a Fallback returns it to SIO.",
        "UART 8-E-1 character framing (1 start, 8 data, 1 even parity, 1 stop) "
        "at COM1 = 4.8 kbaud, COM2 = 38.4 kbaud, or COM3 = 230.4 kbaud.",
        "Half-duplex M-sequences: a Master message + a Device response "
        "(TYPE_0/1/2) with the CKT (Master) and CKS (Device) checksums.",
        "Cyclic Process Data (up to 32 bytes per direction) exchanged every "
        "cycle in OPERATE.",
        "Acyclic On-request Data via the ISDU (Indexed Service Data Unit) using "
        "an Index and Subindex.",
        "Events for diagnostics (EventCode + EventQualifier).",
        "Each Device described by an IODD (IO Device Description, XML); declares "
        "a MinCycleTime; driven through STARTUP / PREOPERATE / OPERATE by the "
        "MasterCommand.",
    ]
    d["topology_summary"] = (
        "Point-to-point: one IO-Link Device (sensor or actuator) connects to "
        "one port of an IO-Link Master over a single three-wire cable. The "
        "Master provides multiple independent ports; each port drives exactly "
        "one Device. There is no bus and no multi-drop.")
    d["use_cases"] = [
        "Smart sensors (photoelectric, inductive, pressure, temperature, level)",
        "Smart actuators (valves, grippers, signal beacons)",
        "Parameterizable / IO-Link-enabled field devices",
        "RFID read/write heads and measurement devices",
        "Any sensor/actuator needing parameterization, diagnostics, and a "
        "digital value over a cheap three-wire cable",
    ]
    d["revision_history"] = [
        {"version": "IO-Link Interface Spec v1.0", "date": "2009",
         "description": "First IO-Link specification: SDCI single-drop "
                        "point-to-point link on the C/Q line, SIO/SDCI modes, "
                        "wake-up, UART 8-E-1 at COM1/COM2/COM3, M-sequences, "
                        "Process Data, ISDU, IODD."},
        {"version": "IO-Link Interface Spec v1.1", "date": "2011",
         "description": "Added/clarified larger Process Data, Data Storage "
                        "(parameter backup/restore at the Master), additional "
                        "M-sequence types, and COM3 (230.4 kbaud)."},
        {"version": "IEC 61131-9 (SDCI)", "date": "2013",
         "description": "International standardization of the IO-Link interface "
                        "as IEC 61131-9 (SDCI — Single-drop Digital "
                        "Communication Interface)."},
    ]
    d["overview"] = (
        "IO-Link (IEC 61131-9, SDCI) connects a single sensor or actuator (the "
        "IO-Link Device) to one port of an IO-Link Master over a three-wire "
        "cable: L+ (24 V supply), L- (ground), and C/Q (the combined "
        "communication and switching signal line). The link is strictly "
        "point-to-point — one Device per Master port — and is therefore not a "
        "fieldbus and not a bus. The C/Q line is dual-purpose: in Standard IO "
        "(SIO) mode it carries a binary switching signal like an ordinary "
        "digital sensor, and in SDCI (communication) mode it carries UART-based "
        "serial communication. The Master is always the initiator: it issues a "
        "wake-up request that switches the Device from SIO mode into SDCI mode, "
        "detects the Device's COM rate (COM1 = 4.8 kbaud, COM2 = 38.4 kbaud, or "
        "COM3 = 230.4 kbaud), reads the Direct Parameter page, and drives the "
        "Device through STARTUP, PREOPERATE, and OPERATE using the "
        "MasterCommand. In SDCI mode communication is organized into "
        "M-sequences — a Master message followed by a Device response, each "
        "terminated by a checksum (CKT for the Master, CKS for the Device). "
        "Three kinds of data flow over the link: cyclic Process Data (up to 32 "
        "bytes per direction), acyclic On-request Data accessed through the "
        "ISDU (Indexed Service Data Unit) by Index and Subindex, and Events for "
        "diagnostics. Each Device is described by an IODD (IO Device "
        "Description, an XML file) and declares a minimum cycle time the Master "
        "respects.")
    _write(p, d)


# ----------------------------------------------------------------------
# L2 — FRS / protocol overview.
# ----------------------------------------------------------------------
def _l2(gd: Path) -> None:
    p = gd / "L2_FRS.json"
    if not p.is_file():
        return
    d = _read(p)
    po = _ensure_dict(d, "protocol_overview")
    po["type"] = (
        "Point-to-point, single-drop, serial digital communication interface "
        "for one sensor/actuator per IO-Link Master port (three-wire: L+, L-, "
        "C/Q). UART-based half-duplex communication on the C/Q line in SDCI "
        "mode; binary switching on the C/Q line in SIO mode. Standardized as "
        "IEC 61131-9 (SDCI).")
    po["duplex"] = (
        "Half-duplex on the single C/Q line: the Master transmits its message, "
        "then the Device transmits its response; the line direction reverses "
        "within each M-sequence.")
    po["synchronous_serial"] = False
    po["source_synchronous"] = False
    po["embedded_clock"] = False
    po["forwarded_clock"] = False
    po["encoding"] = (
        "UART character framing on the C/Q line: each character is 1 start bit, "
        "8 data bits (LSB first), 1 even parity bit, and 1 stop bit (8-E-1, 11 "
        "bit times) at the negotiated COM rate.")
    po["modulation"] = (
        "Push-pull single-wire (C/Q) levels (0 V near L- / 24 V near L+); UART "
        "asynchronous serial framing in SDCI mode, binary switching in SIO "
        "mode.")
    po["supply_voltage_v"] = _SUPPLY_V
    po["com_rates_kbaud"] = {"COM1": _COM1_KBAUD, "COM2": _COM2_KBAUD,
                             "COM3": _COM3_KBAUD}
    po["uart_data_bits"] = _UART_DATA_BITS
    po["uart_parity"] = _UART_PARITY
    po["uart_bits_per_char"] = _UART_BITS_PER_CHAR
    po["process_data_max_bytes"] = _PD_MAX_BYTES
    po["m_sequence_types"] = list(_M_SEQUENCE_TYPES)
    po["device_states"] = list(_DEVICE_STATES)
    po["max_cable_length_m"] = _MAX_CABLE_M
    po["point_to_point"] = True
    po["is_fieldbus"] = False
    po["topology"] = (
        "IO-Link Master port -> single three-wire cable (L+, L-, C/Q) -> one "
        "IO-Link Device; one Device per port, no bus, no multi-drop, no on-wire "
        "addressing.")
    d["functional_requirements"] = [
        {"id": "FR-WIRE-01", "text": "IO-Link is a point-to-point single-drop "
         "interface (SDCI, IEC 61131-9) on a three-wire cable: L+ (24 V "
         "supply), L- (ground), and C/Q (combined communication and switching "
         "signal line); one Device per Master port."},
        {"id": "FR-CQ-02", "text": "The C/Q line is dual-mode: in SIO (Standard "
         "IO) mode it carries a binary switching signal; in SDCI "
         "(communication) mode it carries UART-based serial communication."},
        {"id": "FR-WAKE-03", "text": "The Master starts communication with a "
         "wake-up request on the C/Q line, switching the Device from SIO mode "
         "into SDCI mode; the Master then detects the Device's COM rate."},
        {"id": "FR-UART-04", "text": "Communication uses UART 8-E-1 character "
         "framing (1 start bit, 8 data bits LSB first, 1 even parity bit, 1 "
         "stop bit) at COM1 = 4.8 kbaud, COM2 = 38.4 kbaud, or COM3 = 230.4 "
         "kbaud; a Device supports exactly one COM rate."},
        {"id": "FR-MSEQ-05", "text": "Communication is organized into "
         "M-sequences: a Master message (Master Control octet + optional data + "
         "CKT checksum) followed by a Device response (optional data + status + "
         "CKS checksum); types TYPE_0, TYPE_1, TYPE_2."},
        {"id": "FR-PD-06", "text": "Cyclic Process Data (up to 32 bytes per "
         "direction) is exchanged every cycle in the OPERATE state; the Master "
         "respects the Device's MinCycleTime."},
        {"id": "FR-ORD-07", "text": "Acyclic On-request Data (parameters, "
         "identification, diagnostics) is accessed through the ISDU (Indexed "
         "Service Data Unit) using an Index and Subindex, interleaved with the "
         "cyclic Process Data."},
        {"id": "FR-EVT-08", "text": "The Device reports diagnostics through "
         "Events (EventCode + EventQualifier), signalled in its response so the "
         "Master can read the Event detail."},
        {"id": "FR-IODD-09", "text": "Each Device is described by an IODD (IO "
         "Device Description), an XML file used by the engineering tool to "
         "identify and parameterize the Device."},
        {"id": "FR-STATE-10", "text": "The Device moves through STARTUP, "
         "PREOPERATE, and OPERATE states driven by the MasterCommand "
         "(PreoperateMaster, OperateMaster, Fallback)."},
        {"id": "FR-CKSUM-11", "text": "Each Master message ends with a CKT "
         "checksum and each Device response with a CKS checksum; a checksum or "
         "parity error causes the receiver to discard the message and the "
         "Master to retry, falling back to SIO on repeated failure."},
    ]
    d["error_response_conditions"] = [
        "Parity error — the even parity bit of a UART character is wrong; the "
        "character is rejected.",
        "Checksum error — the recomputed CKT/CKS differs from the transmitted "
        "checksum; the message is discarded and the Master retries.",
        "Response timeout — the Device does not answer within the Master's "
        "response timeout; the Master retries.",
        "Communication lost — repeated failure causes the Master to declare the "
        "Device lost and fall back to SIO mode.",
    ]
    d["compliance_requirements"] = [
        "Point-to-point single-drop interface (SDCI, IEC 61131-9): one Device "
        "per Master port on a three-wire L+/L-/C-Q cable.",
        "C/Q line dual-mode (SIO switching / SDCI communication) with a "
        "wake-up request switching SIO to SDCI.",
        "UART 8-E-1 framing at COM1/COM2/COM3.",
        "M-sequences (Master message + Device response) with CKT/CKS checksums.",
        "Cyclic Process Data (up to 32 bytes) + acyclic On-request Data via the "
        "ISDU (Index/Subindex) + Events.",
        "STARTUP / PREOPERATE / OPERATE state machine driven by the "
        "MasterCommand.",
        "IODD (IO Device Description) per Device; declared MinCycleTime.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L3 — command / protocol model.
# ----------------------------------------------------------------------
def _l3(gd: Path) -> None:
    p = gd / "L3_CMD_PROTOCOL.json"
    if not p.is_file():
        return
    d = _read(p)
    d["protocol_type"] = (
        "Master-initiated, half-duplex, M-sequence-based UART protocol on the "
        "C/Q line. Each M-sequence is a Master message (Master Control octet "
        "selecting read/write and a communication channel + optional Process "
        "Data and/or On-request Data octets + a CKT checksum) followed by a "
        "Device response (optional data octets + a status octet + a CKS "
        "checksum). Acyclic parameters are addressed by the ISDU using an Index "
        "and Subindex.")
    d["frame_structure"] = [
        {"element": "Master Control (MC) octet",
         "purpose": "Selects read/write, the communication channel (Process / "
                    "Page / Diagnosis / ISDU), and the address."},
        {"element": "Master data octets (optional)",
         "purpose": "Process Data Out and/or On-request Data from the Master."},
        {"element": "CKT checksum octet",
         "purpose": "6-bit checksum + 2-bit type/event field over the Master "
                    "message."},
        {"element": "Device data octets (optional)",
         "purpose": "Process Data In and/or On-request Data from the Device."},
        {"element": "Device status octet",
         "purpose": "Device status / Event flag."},
        {"element": "CKS checksum octet",
         "purpose": "6-bit checksum + 2-bit type/event field over the Device "
                    "response."},
    ]
    d["uart_character"] = {
        "start_bits": _UART_START_BITS,
        "data_bits": _UART_DATA_BITS,
        "parity": _UART_PARITY,
        "stop_bits": _UART_STOP_BITS,
        "bits_per_char": _UART_BITS_PER_CHAR,
        "bit_order": "LSB first",
        "format": "8-E-1",
    }
    d["m_sequence_types"] = [
        {"name": "TYPE_0",
         "use": "A single On-request Data octet per message; used in STARTUP."},
        {"name": "TYPE_1",
         "use": "An On-request Data octet plus a small fixed Process Data "
                "length."},
        {"name": "TYPE_2",
         "use": "Interleaved or larger Process Data with On-request Data; used "
                "in OPERATE for Devices with longer Process Data."},
    ]
    d["isdu"] = {
        "name": "Indexed Service Data Unit",
        "addressing": "Index (16-bit) + optional Subindex (8-bit)",
        "operations": ["ISDU read", "ISDU write"],
        "segmentation": "An ISDU larger than one M-sequence payload is "
                        "segmented across several M-sequences and reassembled.",
        "standard_indices": [
            {"index": "0x0010", "name": "VendorName"},
            {"index": "0x0012", "name": "ProductName"},
            {"index": "0x0018", "name": "ApplicationSpecificTag"},
        ],
    }
    d["communication_channels"] = [
        "Process (cyclic Process Data)",
        "Page (Direct Parameter page)",
        "Diagnosis (Events)",
        "ISDU (On-request Data)",
    ]
    d["checksum"] = {
        "ckt": "Master-message checksum octet (6-bit checksum + 2-bit "
               "type/event field).",
        "cks": "Device-response checksum octet (6-bit checksum + 2-bit "
               "type/event field).",
        "purpose": "Data-integrity protection over the half-duplex link.",
    }
    d["mastercommand"] = [
        "Fallback (return to SIO)", "MasterIdent", "DeviceIdent",
        "PreoperateMaster (enter PREOPERATE)", "OperateMaster (enter OPERATE)",
    ]
    d["addressing"] = {
        "on_wire": "None — point-to-point, one Device per Master port.",
        "parameters": "ISDU Index (16-bit) + Subindex (8-bit).",
    }
    d["byte_oriented"] = True
    d["frame_oriented"] = True
    d["half_duplex"] = True
    d["master_initiated"] = True
    _write(p, d)


# ----------------------------------------------------------------------
# L4 — register / configuration parameter model.
# ----------------------------------------------------------------------
def _l4(gd: Path) -> None:
    p = gd / "L4_REGMAP.json"
    if not p.is_file():
        return
    d = _read(p)
    d["register_map_present"] = True
    d["notes"] = (
        "IO-Link (IEC 61131-9, SDCI) is a communication interface rather than a "
        "memory-mapped register IC. A Device exposes the Direct Parameter page "
        "(read directly during STARTUP) and an ISDU-addressed parameter space "
        "(Index/Subindex). The groups below are the canonical IO-Link "
        "configuration/parameter surfaces.")
    d["register_access"] = {
        "transport": "Direct Parameter page (Page 1, read directly) + ISDU "
                     "Index/Subindex parameter access",
        "purpose": "Configure the link (STARTUP) and parameterize the Device "
                   "(PREOPERATE).",
    }
    d["register_groups"] = [
        {"group": "Direct Parameter page (Page 1)", "fields": [
            "MasterCommand", "MasterCycleTime", "MinCycleTime",
            "M-sequence capability / type", "RevisionID (IO-Link revision)",
            "VendorID", "DeviceID", "FunctionID",
            "Process Data In length", "Process Data Out length"]},
        {"group": "Identification (ISDU)", "fields": [
            "VendorName (Index 0x0010)", "ProductName (Index 0x0012)",
            "ApplicationSpecificTag (Index 0x0018)",
            "SerialNumber", "HardwareRevision", "FirmwareRevision"]},
        {"group": "Process Data / status", "fields": [
            "Process Data In (Device -> Master, up to 32 bytes)",
            "Process Data Out (Master -> Device, up to 32 bytes)",
            "Device status octet", "Event buffer (EventCode + EventQualifier)"]},
        {"group": "Communication parameters", "fields": [
            "COM rate (COM1/COM2/COM3)", "MinCycleTime", "MasterCycleTime",
            "M-sequence type (TYPE_0/1/2)"]},
    ]
    d["protocol_fields"] = {
        "supply_voltage_v": _SUPPLY_V,
        "process_data_max_bytes": _PD_MAX_BYTES,
        "com_rates_kbaud": {"COM1": _COM1_KBAUD, "COM2": _COM2_KBAUD,
                            "COM3": _COM3_KBAUD},
        "isdu_index_bits": 16,
        "isdu_subindex_bits": 8,
        "device_states": list(_DEVICE_STATES),
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L5 — analog / physical signaling spec.
# ----------------------------------------------------------------------
def _l5(gd: Path) -> None:
    p = gd / "L5_ADI_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["analog_digital_interface_present"] = True
    d["signaling_summary"] = (
        "The C/Q line is a single push-pull wire driven between the low level "
        "(near L-, 0 V) and the high level (near L+, 24 V). In SIO mode the "
        "level directly represents the switching state. In SDCI mode the line "
        "carries UART characters: the idle level is the UART idle (logic 1), "
        "each character starts with a falling edge (the start bit), and bits "
        "are clocked at the negotiated COM rate (COM1/COM2/COM3). There is no "
        "separate clock wire — both ends use locally generated UART bit "
        "timing.")
    d["modulation"] = (
        "Single-wire (C/Q) push-pull 0 V / 24 V; UART asynchronous serial "
        "framing in SDCI mode, binary switching in SIO mode.")
    d["clocking"] = (
        "Asynchronous: each end generates its own UART bit clock at the agreed "
        "COM rate (COM1 = 4.8 kbaud, COM2 = 38.4 kbaud, COM3 = 230.4 kbaud); "
        "the start-bit falling edge synchronizes each character. No forwarded "
        "or embedded clock.")
    d["transmitter_specs_canonical"] = {
        "levels": "0 V (low, near L-) / 24 V (high, near L+), push-pull",
        "supply_voltage_v": _SUPPLY_V,
        "com_rates_kbaud": {"COM1": _COM1_KBAUD, "COM2": _COM2_KBAUD,
                            "COM3": _COM3_KBAUD},
        "uart_framing": "8-E-1 (1 start, 8 data, 1 even parity, 1 stop)",
        "bit_time_us": {"COM1": 208.33, "COM2": 26.04, "COM3": 4.34},
        "max_cable_length_m": _MAX_CABLE_M,
    }
    d["receiver_specs_canonical"] = {
        "edge_of_interest": "start-bit falling edge per UART character",
        "sampling": "Sample each data bit near its center at the agreed COM "
                    "rate; check the even parity bit.",
        "decode": "Reassemble octets into M-sequences; verify the CKT/CKS "
                  "checksum.",
    }
    d["edge_encoding"] = {
        "name": "UART asynchronous framing on the C/Q line",
        "edge": "start-bit falling edge",
        "rule": "1 start + 8 data (LSB first) + 1 even parity + 1 stop per "
                "character.",
    }
    d["supply_voltage_v"] = _SUPPLY_V
    d["com_rates_kbaud"] = {"COM1": _COM1_KBAUD, "COM2": _COM2_KBAUD,
                            "COM3": _COM3_KBAUD}
    d["encoding_role_in_analog"] = (
        "IO-Link carries digital octets as UART characters on the single C/Q "
        "wire (0 V / 24 V push-pull); the analog/physical concern is the "
        "switching levels, the C/Q dual-mode behavior (SIO switching vs SDCI "
        "communication), and the bit timing at COM1/COM2/COM3, not a multi-"
        "level analog signal. Frame integrity comes from the even parity bit "
        "and the CKT/CKS checksums.")
    _write(p, d)


# ----------------------------------------------------------------------
# L6 — control logic / Master + Device FSMs.
# ----------------------------------------------------------------------
def _l6(gd: Path) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["fsm_states_master"] = [
        {"name": "WAKE_UP", "description": "Issue the wake-up request on the "
         "C/Q line and detect the Device's COM rate."},
        {"name": "STARTUP", "description": "Read the Direct Parameter page "
         "(VendorID, DeviceID, MinCycleTime, Process Data lengths, M-sequence "
         "type) and check the Device identity."},
        {"name": "PREOPERATE", "description": "Parameterize the Device via the "
         "ISDU before cyclic data exchange."},
        {"name": "OPERATE", "description": "Exchange cyclic Process Data each "
         "cycle; interleave On-request Data and Events."},
        {"name": "FALLBACK", "description": "Issue Fallback (or on lost "
         "communication) and return the C/Q line to SIO mode."},
    ]
    d["fsm_states_device"] = [
        {"name": "SIO", "description": "Standard IO: the C/Q line is a binary "
         "switching signal; wait for a wake-up request."},
        {"name": "STARTUP", "description": "After wake-up, present the Direct "
         "Parameter page to the Master."},
        {"name": "PREOPERATE", "description": "Accept ISDU parameter "
         "reads/writes from the Master."},
        {"name": "OPERATE", "description": "Exchange cyclic Process Data; serve "
         "On-request Data; raise Events."},
    ]
    d["fsm_hints"] = {
        "trigger": "The Master is always the initiator: it issues the wake-up "
        "request and every M-sequence; the Device only answers.",
        "rule": "The Device powers up in SIO mode and enters SDCI mode only "
        "after the Master's wake-up request; the MasterCommand drives "
        "STARTUP -> PREOPERATE -> OPERATE.",
        "decode": "Each M-sequence = Master message (MC + data + CKT) + Device "
        "response (data + status + CKS).",
    }
    d["exit_from_reset_or_poweron"] = (
        "On power-up the Device is in SIO mode (the C/Q line is a binary "
        "switching signal). It remains in SIO until an IO-Link Master issues a "
        "wake-up request, which switches it into SDCI communication mode.")
    d["default_ready_state_recommendation"] = {
        "idle": "In SIO mode the C/Q line carries the binary switching value; "
                "in SDCI mode the line idles at the UART idle level between "
                "characters.",
        "resync": "On a checksum/parity error the Master retries; on repeated "
                  "failure it falls back to SIO and may re-wake the Device.",
    }
    d["configurations"] = [
        {"name": "SIO operation", "description": "C/Q line as a plain digital "
         "switching signal (no communication)."},
        {"name": "SDCI operation", "description": "UART communication on the "
         "C/Q line: cyclic Process Data + acyclic On-request Data + Events."},
        {"name": "Data Storage", "description": "Optional Master-side parameter "
         "backup/restore so a replaced Device is auto-parameterized."},
    ]
    d["timing_dependency_rule"] = (
        "Cyclic Process Data exchange in OPERATE must respect the Device's "
        "MinCycleTime; the Master uses a MasterCycleTime greater than or equal "
        "to the Device's minimum. Communication cannot start until the wake-up "
        "request has switched the Device from SIO into SDCI mode.")
    _write(p, d)


# ----------------------------------------------------------------------
# L7 — test / debug / observability.
# ----------------------------------------------------------------------
def _l7(gd: Path) -> None:
    p = gd / "L7_TEST_DEBUG.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_debug_architecture_present"] = True
    d["spec_provided_observability"] = [
        {"name": "CKT/CKS checksum", "purpose": "Per-M-sequence integrity "
         "check; a mismatch flags a corrupted message."},
        {"name": "Even parity bit", "purpose": "Per-UART-character integrity "
         "check."},
        {"name": "Device status octet", "purpose": "Observable Device status "
         "and Event flag in each response."},
        {"name": "Events", "purpose": "EventCode + EventQualifier carry "
         "diagnostics (error / warning / notification)."},
        {"name": "Direct Parameter page", "purpose": "Identification and "
         "communication parameters readable during STARTUP."},
    ]
    d["error_detection_mechanisms"] = [
        "Even parity bit per UART character detects single-bit errors.",
        "CKT/CKS checksum per M-sequence detects message corruption.",
        "Response timeout detects a non-responding Device.",
        "Repeated failure causes fallback to SIO and a communication-lost "
        "Event.",
    ]
    d["test_modes"] = [
        {"name": "Wake-up / COM-rate test", "purpose": "Verify the wake-up "
         "request switches SIO->SDCI and the Master detects COM1/COM2/COM3."},
        {"name": "M-sequence capture / decode", "purpose": "Capture the C/Q "
         "UART traffic and decode M-sequences for bring-up."},
        {"name": "ISDU read/write test", "purpose": "Exercise ISDU "
         "Index/Subindex parameter access and segmentation."},
        {"name": "Checksum error injection", "purpose": "Inject CKT/CKS errors "
         "to confirm detection and retry."},
        {"name": "Event test", "purpose": "Trigger Device Events and confirm "
         "the Master reads them."},
    ]
    d["interrupt_or_event_sources"] = [
        {"event": "Process Data ready", "trigger": "A cyclic Process Data "
         "exchange completed (CKS pass)."},
        {"event": "Checksum error", "trigger": "CKT/CKS mismatch."},
        {"event": "Device Event", "trigger": "The Device raised an Event "
         "(EventCode/EventQualifier)."},
        {"event": "Communication lost", "trigger": "Repeated timeout/checksum "
         "failure; fallback to SIO."},
    ]
    d["notes"] = (
        "IO-Link's protocol-level observability is the per-character even "
        "parity, the per-M-sequence CKT/CKS checksum, the Device status octet, "
        "the Event mechanism, and the Direct Parameter page. Chip-level "
        "JTAG/scan/BIST remain Device/SoC-integrator concerns.")
    _write(p, d)


# ----------------------------------------------------------------------
# L8 RTL constants.
# ----------------------------------------------------------------------
def _l8_rtl(gd: Path) -> None:
    p = gd / "L8_RTL_CONSTANTS.json"
    if not p.is_file():
        return
    d = _read(p)
    wp = _ensure_dict(d, "width_parameters")
    wp.update({
        "IO_LINK_STANDARD": "IEC 61131-9 (SDCI)",
        "MODULATION": "single-wire (C/Q) UART 8-E-1 (SDCI) / binary switching (SIO)",
        "SUPPLY_VOLTAGE_V": _SUPPLY_V,
        "COM1_KBAUD": _COM1_KBAUD,
        "COM2_KBAUD": _COM2_KBAUD,
        "COM3_KBAUD": _COM3_KBAUD,
        "UART_START_BITS": _UART_START_BITS,
        "UART_DATA_BITS": _UART_DATA_BITS,
        "UART_PARITY": _UART_PARITY,
        "UART_STOP_BITS": _UART_STOP_BITS,
        "UART_BITS_PER_CHAR": _UART_BITS_PER_CHAR,
        "PROCESS_DATA_MAX_BYTES": _PD_MAX_BYTES,
        "ISDU_INDEX_BITS": 16,
        "ISDU_SUBINDEX_BITS": 8,
        "MAX_CABLE_LENGTH_M": _MAX_CABLE_M,
        "POINT_TO_POINT": True,
        "HALF_DUPLEX": True,
        "MASTER_INITIATED": True,
        "EMBEDDED_CLOCK": False,
        "FORWARDED_CLOCK": False,
    })
    d["frame_format_constants"] = {
        "uart_character": "8-E-1 (1 start, 8 data, 1 even parity, 1 stop)",
        "m_sequence": "Master message (MC + data + CKT) + Device response "
                      "(data + status + CKS)",
        "m_sequence_types": list(_M_SEQUENCE_TYPES),
        "process_data_max_bytes": _PD_MAX_BYTES,
    }
    d["checksum_constants"] = {
        "ckt": {"role": "Master-message checksum",
                "form": "6-bit checksum + 2-bit type/event field"},
        "cks": {"role": "Device-response checksum",
                "form": "6-bit checksum + 2-bit type/event field"},
    }
    kc = _ensure_dict(d, "key_constants_for_RTL_authoring")
    kc.update({
        "is_single_wire_signal": True,
        "signal_wire": "C/Q",
        "is_point_to_point": True,
        "is_half_duplex": True,
        "master_initiated": True,
        "uart_framing": "8-E-1",
        "com_rates_kbaud": {"COM1": _COM1_KBAUD, "COM2": _COM2_KBAUD,
                            "COM3": _COM3_KBAUD},
        "supply_voltage_v": _SUPPLY_V,
        "process_data_max_bytes": _PD_MAX_BYTES,
        "isdu_index_bits": 16,
        "isdu_subindex_bits": 8,
        "device_states": list(_DEVICE_STATES),
        "m_sequence_types": list(_M_SEQUENCE_TYPES),
        "modes": ["SIO", "SDCI"],
        "wakeup_required": True,
        "embedded_clock": False,
        "forwarded_clock": False,
    })
    d["default_signal_values_when_idle"] = {
        "sio": "In SIO mode the C/Q line carries the binary switching value.",
        "sdci": "In SDCI mode the C/Q line idles at the UART idle level "
                "(logic 1) between characters.",
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L8 timing waveform.
# ----------------------------------------------------------------------
def _l8_timing(gd: Path) -> None:
    p = gd / "L8_TIMING_WAVEFORM.json"
    if not p.is_file():
        return
    d = _read(p)
    d["bit_waveform"] = {
        "modulation": "single-wire (C/Q) UART character; start-bit falling "
                      "edge begins each character",
        "uart_framing": "8-E-1 (1 start, 8 data LSB first, 1 even parity, 1 "
                        "stop) = 11 bit times",
        "com_rates_kbaud": {"COM1": _COM1_KBAUD, "COM2": _COM2_KBAUD,
                            "COM3": _COM3_KBAUD},
        "bit_time_us": {"COM1": 208.33, "COM2": 26.04, "COM3": 4.34},
        "clock_recovery": "asynchronous: local UART bit clock per end; "
                          "start-bit edge synchronizes each character.",
    }
    d["wakeup_waveform"] = {
        "rule": "The Master applies a wake-up request pulse on the C/Q line; "
                "the Device (in SIO mode) detects it and switches to SDCI mode.",
        "effect": "SIO (Standard IO) mode -> SDCI (communication) mode.",
    }
    d["m_sequence_waveform"] = {
        "order": ["Master message (MC + data + CKT)",
                  "Device response (data + status + CKS)"],
        "duplex": "half-duplex: the C/Q line direction reverses between the "
                  "Master message and the Device response.",
        "types": list(_M_SEQUENCE_TYPES),
    }
    d["cycle_waveform"] = {
        "rule": "In OPERATE the Master polls the Device every cycle, exchanging "
                "Process Data; the cycle time >= the Device's MinCycleTime.",
        "min_cycle_time": "declared per Device (typ. ~0.4 ms to several ms).",
    }
    d["general_timing_rule"] = (
        "UART characters are clocked at the negotiated COM rate (COM1 = 4.8 "
        "kbaud, COM2 = 38.4 kbaud, COM3 = 230.4 kbaud); each character is 11 "
        "bit times (8-E-1); M-sequences are half-duplex Master message + Device "
        "response; the cyclic Process Data exchange respects the Device's "
        "MinCycleTime.")
    d["data_rate_waveform"] = {
        "com_rates_kbaud": {"COM1": _COM1_KBAUD, "COM2": _COM2_KBAUD,
                            "COM3": _COM3_KBAUD},
        "uart_framing": "8-E-1",
        "modulation": "single-wire (C/Q) UART (SDCI) / binary switching (SIO)",
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L9 — integration spec.
# ----------------------------------------------------------------------
def _l9(gd: Path) -> None:
    p = gd / "L9_INTEGRATION_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["module_role"] = (
        "Point-to-point single-drop sensor/actuator communication controller: "
        "an IO-Link (IEC 61131-9, SDCI) Master port or Device that drives the "
        "C/Q combined communication and switching line, switches between SIO "
        "(binary switching) and SDCI (UART communication) modes via a wake-up "
        "request, exchanges UART 8-E-1 octets at COM1/COM2/COM3 in M-sequences "
        "(CKT/CKS checksums), carries cyclic Process Data and acyclic "
        "On-request Data (ISDU Index/Subindex) and Events, and runs the "
        "STARTUP/PREOPERATE/OPERATE state machine via the MasterCommand.")
    d["topology_description"] = (
        "Point-to-point: one IO-Link Device connects to one port of an IO-Link "
        "Master over a single three-wire cable (L+, L-, C/Q), max 20 m. The "
        "Master provides multiple independent ports; each port drives exactly "
        "one Device. No bus, no multi-drop, no on-wire Device addressing.")
    io = _ensure_dict(d, "integration_overview")
    io.update({
        "io_link_standard": "IEC 61131-9 (SDCI)",
        "supply_voltage_v": _SUPPLY_V,
        "com_rates_kbaud": {"COM1": _COM1_KBAUD, "COM2": _COM2_KBAUD,
                            "COM3": _COM3_KBAUD},
        "uart_framing": "8-E-1 (1 start, 8 data, 1 even parity, 1 stop)",
        "process_data_max_bytes": _PD_MAX_BYTES,
        "m_sequence_types": list(_M_SEQUENCE_TYPES),
        "device_states": list(_DEVICE_STATES),
        "max_cable_length_m": _MAX_CABLE_M,
        "modulation": "single-wire (C/Q) UART (SDCI) / binary switching (SIO)",
        "clocking": "asynchronous UART (local bit clock per end)",
        "point_to_point": True,
        "half_duplex": True,
        "master_initiated": True,
        "interfaces": {"signal": "C/Q combined communication and switching "
                       "line (0 V / 24 V)",
                       "supply": "L+ (24 V)",
                       "ground": "L- (ground / 0 V return)"},
    })
    d["interface_categories"] = [
        "Signal interface — single C/Q combined communication and switching "
        "line.",
        "Power interface — L+ (24 V supply) and L- (ground) (three-wire "
        "interface).",
        "Communication interface — UART 8-E-1 M-sequences (Process Data, "
        "On-request Data, Events).",
        "Engineering interface — IODD (IO Device Description) for "
        "identification and parameterization.",
    ]
    d["interconnect_topologies_supported"] = [
        "Point-to-point Device -> Master port (one Device per port).",
        "SIO operation (binary switching on the C/Q line).",
        "SDCI operation (UART communication on the C/Q line).",
        "Multi-port Master (independent point-to-point ports).",
    ]
    d["default_signal_values_when_omitted"] = (
        "The Device powers up in SIO mode, so the C/Q line carries the binary "
        "switching value until an IO-Link Master issues a wake-up request and "
        "switches it into SDCI communication mode.")
    d["soc_dependent_items"] = [
        "COM rate (COM1 = 4.8 kbaud, COM2 = 38.4 kbaud, COM3 = 230.4 kbaud).",
        "Process Data In / Out lengths (up to 32 bytes each).",
        "M-sequence type (TYPE_0 / TYPE_1 / TYPE_2).",
        "MinCycleTime declared by the Device.",
        "ISDU parameter map (Index/Subindex) and IODD.",
        "Optional Data Storage (Master-side parameter backup/restore).",
    ]
    d["device_classes_examples"] = [
        "IO-Link Device (smart sensor / actuator) — communication slave",
        "IO-Link Master port controller — communication master",
        "IO-Link transceiver (C/Q line driver, SIO/SDCI)",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L10 — derived test cases.
# ----------------------------------------------------------------------
def _l10(gd: Path) -> None:
    p = gd / "L10_TEST_CASES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_cases_present"] = (
        "partial - the specification defines protocol behaviors rather than an "
        "embedded testbench; the categories below are derived from the spec.")
    d["derived_compliance_test_categories"] = [
        "Wake-up: the wake-up request switches the Device from SIO to SDCI "
        "mode.",
        "COM-rate detection: the Master detects COM1 / COM2 / COM3.",
        "UART framing: 8-E-1 (1 start, 8 data, 1 even parity, 1 stop) at each "
        "COM rate.",
        "M-sequence: Master message + Device response with CKT/CKS checksums "
        "(TYPE_0/1/2).",
        "Process Data: cyclic exchange of up to 32 bytes per direction in "
        "OPERATE.",
        "On-request Data / ISDU: read/write by Index/Subindex with "
        "segmentation.",
        "Events: EventCode/EventQualifier reporting and Master read-back.",
        "Device states: STARTUP -> PREOPERATE -> OPERATE driven by the "
        "MasterCommand.",
        "MinCycleTime: the Master respects the Device's declared minimum cycle "
        "time.",
        "Error handling: parity error, CKT/CKS mismatch, response timeout, "
        "fallback to SIO.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L11 — OTP / factory-burned equivalents.
# ----------------------------------------------------------------------
def _l11(gd: Path) -> None:
    p = gd / "L11_OTP_CONTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    d["otp_present"] = False
    d["otp_equivalent_factory_burned_fields"] = [
        {"field": "VendorID / DeviceID",
         "location": "Direct Parameter page",
         "note": "Device identity read by the Master during STARTUP; typically "
                 "factory-fixed, not a protocol OTP concept."},
        {"field": "RevisionID (IO-Link revision)",
         "location": "Direct Parameter page",
         "note": "The IO-Link protocol revision the Device implements."},
        {"field": "COM rate / M-sequence capability",
         "location": "Direct Parameter page / IODD",
         "note": "Fixed for a given Device; one of COM1/COM2/COM3."},
        {"field": "SerialNumber / identification",
         "location": "ISDU (Index 0x0010 VendorName, 0x0012 ProductName, etc.)",
         "note": "Device identification; programmed at manufacture."},
    ]
    d["notes"] = (
        "IO-Link (IEC 61131-9, SDCI) does not define OTP/fuse content as a "
        "protocol concept. The VendorID, DeviceID, RevisionID, COM rate, and "
        "identification strings are Device configuration (often factory-"
        "programmed) exposed via the Direct Parameter page and the ISDU. An "
        "implementation may back these with non-volatile storage, but the "
        "standard only requires the identity be readable and the communication "
        "parameters be consistent. Optional Data Storage backs up Device "
        "parameters at the Master so a replaced Device is auto-parameterized.")
    _write(p, d)


# ----------------------------------------------------------------------
# L12 — behavioral sequences.
# ----------------------------------------------------------------------
def _l12(gd: Path) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["wakeup_sequence"] = [
        "1. The Device powers up in SIO mode (the C/Q line is a binary "
        "switching signal).",
        "2. The Master applies a wake-up request pulse on the C/Q line.",
        "3. The Device detects the wake-up and switches to SDCI "
        "(communication) mode.",
        "4. The Master detects the Device's COM rate (COM1/COM2/COM3) from the "
        "first valid response.",
    ]
    d["startup_sequence"] = [
        "1. The Master reads the Direct Parameter page (VendorID, DeviceID, "
        "RevisionID, MinCycleTime, Process Data lengths, M-sequence type).",
        "2. The Master checks the Device identity against the expected "
        "VendorID/DeviceID.",
        "3. The Master issues PreoperateMaster to enter PREOPERATE.",
    ]
    d["preoperate_sequence"] = [
        "1. The Master writes Device parameters via ISDU (Index/Subindex).",
        "2. The Master reads back identification / parameters via ISDU.",
        "3. The Master issues OperateMaster to enter OPERATE.",
    ]
    d["operate_cyclic_sequence"] = [
        "1. Each cycle the Master sends a Master message (MC + Process Data Out "
        "+ CKT).",
        "2. The Device responds with Process Data In + status + CKS.",
        "3. The Master verifies the CKS checksum and consumes the Process "
        "Data.",
        "4. On-request Data (ISDU) and Events are interleaved as needed.",
        "5. The cycle period respects the Device's MinCycleTime.",
    ]
    d["isdu_sequence"] = [
        "1. The Master sends an ISDU read/write request addressing a parameter "
        "by Index (16-bit) and Subindex (8-bit).",
        "2. If the ISDU is larger than one M-sequence payload it is segmented "
        "across several M-sequences.",
        "3. The Device returns the parameter value (read) or an acknowledgement "
        "(write) and the Master reassembles it.",
    ]
    d["event_sequence"] = [
        "1. The Device sets the Event flag in its status octet.",
        "2. The Master reads the Event detail (EventCode + EventQualifier) via "
        "the diagnosis channel.",
        "3. The Master clears/acknowledges the Event.",
    ]
    d["fallback_sequence"] = [
        "1. On a Fallback MasterCommand or repeated communication failure the "
        "Device returns to SIO mode.",
        "2. The C/Q line resumes its binary switching behavior.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L13 — lab calibration / measurement targets.
# ----------------------------------------------------------------------
def _l13(gd: Path) -> None:
    p = gd / "L13_LAB_CALIBRATION.json"
    if not p.is_file():
        return
    d = _read(p)
    d["lab_calibration_present"] = False
    d["lab_measurement_targets_from_spec"] = [
        {"name": "C/Q signal levels", "purpose": "Verify the push-pull 0 V / "
         "24 V switching and UART levels on the C/Q line."},
        {"name": "Wake-up request", "purpose": "Confirm the wake-up pulse "
         "switches the Device from SIO to SDCI mode."},
        {"name": "COM rate / bit timing", "purpose": "Confirm COM1 = 4.8 "
         "kbaud, COM2 = 38.4 kbaud, COM3 = 230.4 kbaud and the 8-E-1 bit "
         "timing."},
        {"name": "M-sequence / checksum", "purpose": "Confirm the Master "
         "message + Device response framing and the CKT/CKS checksums."},
        {"name": "Process Data cycle time", "purpose": "Confirm cyclic "
         "exchange respects the Device's MinCycleTime."},
        {"name": "ISDU access", "purpose": "Confirm Index/Subindex parameter "
         "read/write and segmentation."},
        {"name": "Event reporting", "purpose": "Confirm EventCode/"
         "EventQualifier reporting."},
    ]
    d["notes"] = (
        "IO-Link characterization centers on the C/Q line switching/UART "
        "levels, the wake-up request and SIO<->SDCI transition, the COM-rate "
        "bit timing (COM1/COM2/COM3) and 8-E-1 framing, the M-sequence "
        "CKT/CKS checksums, the Process Data cycle time vs MinCycleTime, the "
        "ISDU parameter access, and Event reporting. Conformance is "
        "established by IO-Link / IEC 61131-9 (SDCI) compliance testing.")
    _write(p, d)


# ----------------------------------------------------------------------
# L14 — protocol versioning.
# ----------------------------------------------------------------------
def _l14(gd: Path) -> None:
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["spec_version"] = "IEC 61131-9 (SDCI — Single-drop Digital Communication Interface) / IO-Link"
    f["previous_versions"] = [
        "IO-Link Interface Spec v1.0 (2009) — first SDCI single-drop link.",
        "IO-Link Interface Spec v1.1 (2011) — larger Process Data, Data "
        "Storage, COM3 (230.4 kbaud).",
        "IEC 61131-9 (2013) — international standardization as SDCI.",
    ]
    f["key_changes"] = [
        {"version": "IO-Link v1.1", "summary": "Added larger Process Data, the "
         "Data Storage mechanism (Master-side parameter backup/restore for "
         "Device replacement), additional M-sequence types, and COM3 (230.4 "
         "kbaud)."},
        {"version": "IEC 61131-9", "summary": "Standardized the IO-Link "
         "interface internationally as SDCI (Single-drop Digital Communication "
         "Interface), aligning the C/Q line, SIO/SDCI modes, wake-up, UART "
         "8-E-1 framing, M-sequences, ISDU, Events, and IODD."},
    ]
    f["future_versions_industry_outline"] = [
        {"version": "IO-Link (later editions)", "summary": "Continued "
         "refinement of Process Data, Data Storage, and security profiles "
         "(IO-Link Safety, IO-Link Wireless) while preserving the SDCI C/Q "
         "single-drop point-to-point link, UART framing, M-sequences, ISDU, "
         "and IODD."},
    ]
    f["backward_compat_traps"] = [
        {"trap_name": "Not_a_fieldbus",
         "rule": "IO-Link is point-to-point single-drop (one Device per Master "
                 "port), NOT a fieldbus and NOT a multi-drop bus.",
         "trap": "Treating IO-Link as a bus with multiple addressed Devices on "
                 "one wire is wrong."},
        {"trap_name": "C_Q_is_dual_mode",
         "rule": "The C/Q line is binary switching in SIO mode and UART "
                 "communication in SDCI mode.",
         "trap": "Assuming the C/Q line is always a UART line ignores the SIO "
                 "switching behavior before wake-up."},
        {"trap_name": "Master_always_initiates",
         "rule": "The Master issues the wake-up request and every M-sequence; "
                 "the Device only answers.",
         "trap": "Expecting the Device to initiate communication is wrong."},
        {"trap_name": "Not_plain_UART_not_SENT",
         "rule": "IO-Link reuses UART 8-E-1 but adds the C/Q dual-mode line, "
                 "wake-up, SIO/SDCI modes, M-sequences, CKT/CKS, and ISDU; it "
                 "is not a plain UART link and not SENT (nibble/tick/J2716).",
         "trap": "Applying plain async UART decoding or SENT nibble/tick "
                 "decoding to an IO-Link link is wrong."},
    ]
    f["version_naming_history_note"] = (
        "IO-Link is standardized internationally by the IEC as IEC 61131-9 "
        "under the name SDCI (Single-drop Digital Communication Interface). The "
        "interface preserves the C/Q combined communication and switching "
        "line, the SIO/SDCI dual mode with a wake-up request, UART 8-E-1 "
        "framing at COM1/COM2/COM3, M-sequences with CKT/CKS checksums, cyclic "
        "Process Data, acyclic On-request Data via the ISDU (Index/Subindex), "
        "Events, and the IODD across revisions; v1.1 added larger Process Data, "
        "Data Storage, and COM3.")
    _write(p, d)


# ----------------------------------------------------------------------
# L15 — encoding / parameter tables.
# ----------------------------------------------------------------------
def _l15(gd: Path) -> None:
    p = gd / "L15_ENCODING_TABLES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["com_rate_table"] = {
        "header_columns": ["COM rate", "Baud", "Bit time"],
        "rows": [
            ["COM1", "4.8 kbaud", "208.33 us"],
            ["COM2", "38.4 kbaud", "26.04 us"],
            ["COM3", "230.4 kbaud", "4.34 us"],
        ],
        "rule": "A Device supports exactly one COM rate; the Master adapts.",
    }
    f["uart_character_table"] = {
        "header_columns": ["Field", "Value"],
        "rows": [
            ["Start bit", "1 (logic 0, falling edge)"],
            ["Data bits", "8 (LSB first)"],
            ["Parity", "1 even parity bit"],
            ["Stop bit", "1 (logic 1)"],
            ["Bits per character", "11 (8-E-1)"],
        ],
    }
    f["wire_table"] = {
        "header_columns": ["Wire", "M12 pin", "Function"],
        "rows": [
            ["L+", "1", "24 V supply"],
            ["L-", "3", "ground / 0 V return"],
            ["C/Q", "4", "combined communication and switching signal line"],
            ["Q (optional)", "2", "additional digital output / input"],
        ],
    }
    f["m_sequence_table"] = {
        "header_columns": ["Type", "Use"],
        "rows": [
            ["TYPE_0", "single On-request Data octet (STARTUP)"],
            ["TYPE_1", "On-request Data + small Process Data"],
            ["TYPE_2", "larger / interleaved Process Data (OPERATE)"],
        ],
    }
    f["isdu_index_table"] = {
        "header_columns": ["Index", "Name"],
        "rows": [
            ["0x0010", "VendorName"],
            ["0x0012", "ProductName"],
            ["0x0018", "ApplicationSpecificTag"],
        ],
    }
    f["encoding_note"] = (
        "IO-Link encodes each octet as a UART 8-E-1 character (1 start, 8 data "
        "LSB first, 1 even parity, 1 stop) on the C/Q line at COM1 = 4.8 "
        "kbaud, COM2 = 38.4 kbaud, or COM3 = 230.4 kbaud. Octets are framed "
        "into M-sequences (Master message + Device response) ending with the "
        "CKT/CKS checksums. Acyclic parameters are addressed by ISDU "
        "Index/Subindex; cyclic Process Data is up to 32 bytes per direction.")
    f["tables"] = [
        "COM-rate table (COM1/COM2/COM3 baud and bit time)",
        "UART-character table (8-E-1)",
        "Wire table (L+, L-, C/Q, optional Q)",
        "M-sequence-type table (TYPE_0/1/2)",
        "ISDU standard-Index table",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L16 — compliance properties.
# ----------------------------------------------------------------------
def _l16(gd: Path) -> None:
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["must_have_properties"] = [
        "Point-to-point single-drop interface (SDCI, IEC 61131-9): one Device "
        "per IO-Link Master port; three-wire L+/L-/C-Q cable.",
        "C/Q combined communication and switching line, dual-mode: SIO "
        "(binary switching) and SDCI (UART communication).",
        "Wake-up request from the Master switches the Device from SIO to SDCI "
        "mode.",
        "UART 8-E-1 framing at COM1 = 4.8 kbaud, COM2 = 38.4 kbaud, or COM3 = "
        "230.4 kbaud.",
        "M-sequences (Master message + Device response, TYPE_0/1/2) with the "
        "CKT/CKS checksums.",
        "Cyclic Process Data (up to 32 bytes) + acyclic On-request Data via the "
        "ISDU (Index/Subindex) + Events.",
        "STARTUP / PREOPERATE / OPERATE state machine via the MasterCommand; "
        "IODD per Device; declared MinCycleTime.",
    ]
    f["must_not_have_properties"] = [
        "A multi-drop bus with multiple addressed Devices on one wire (IO-Link "
        "is point-to-point single-drop, not a fieldbus).",
        "Plain asynchronous UART start/stop framing only, with no C/Q "
        "dual-mode line, no wake-up, no SIO/SDCI modes, no M-sequences, and no "
        "ISDU (that is plain UART, not IO-Link).",
        "Nibble pulse-width / tick encoding with a 56-tick calibration pulse "
        "and SAE J2716 (that is SENT, not IO-Link).",
        "Device-initiated communication (the Master always initiates in "
        "IO-Link).",
    ]
    f["compliance_failure_modes"] = [
        {"mode": "Checksum mismatch", "trigger": "The recomputed CKT/CKS "
         "differs from the transmitted checksum octet."},
        {"mode": "Parity error", "trigger": "A UART character's even parity "
         "bit is wrong."},
        {"mode": "Response timeout", "trigger": "The Device does not answer "
         "within the Master's response timeout."},
        {"mode": "MinCycleTime violation", "trigger": "The Master polls faster "
         "than the Device's declared minimum cycle time."},
    ]
    f["min_link_constraint"] = (
        "An IO-Link link requires three wires (L+, L-, C/Q) between one Master "
        "port and one Device; the Master must issue a wake-up request to switch "
        "the Device from SIO into SDCI mode before any M-sequence can be "
        "exchanged.")
    f["reset_behavior_compliance"] = (
        "On power-up the Device is in SIO mode (the C/Q line is a binary "
        "switching signal); it enters SDCI mode only after the Master's "
        "wake-up request and returns to SIO on a Fallback MasterCommand or "
        "communication loss.")
    f["io_link_distinguishers"] = (
        "IO-Link is identified by ALL of: a point-to-point single-drop "
        "interface (SDCI, IEC 61131-9) with one Device per IO-Link Master "
        "port on a three-wire L+/L-/C-Q cable; the C/Q combined communication "
        "and switching line that is binary switching in SIO mode and UART "
        "communication in SDCI mode; a wake-up request that switches SIO to "
        "SDCI; UART 8-E-1 framing at COM1/COM2/COM3; M-sequences (Master "
        "message + Device response, TYPE_0/1/2) with the CKT/CKS checksums; "
        "cyclic Process Data (up to 32 bytes) and acyclic On-request Data via "
        "the ISDU (Index/Subindex); Events; and an IODD per Device. This is "
        "distinct from a plain UART link (async start/stop framing only, no "
        "C/Q dual-mode line, no wake-up, no M-sequence, no ISDU) and from SENT "
        "(SAE J2716 nibble pulse-width / tick encoding on a single wire with a "
        "56-tick calibration pulse).")
    _write(p, d)


# ----------------------------------------------------------------------
# L17 — channel / signal catalog.
# ----------------------------------------------------------------------
def _l17(gd: Path) -> None:
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["channels"] = [
        {"name": "C/Q",
         "direction": "bidirectional (half-duplex: Master <-> Device)",
         "purpose": "Combined communication and switching signal line; binary "
                    "switching (SIO) or UART communication (SDCI).",
         "active_levels": "0 V (near L-) / 24 V (near L+)", "idle_level": "high"},
        {"name": "L+",
         "direction": "to Device",
         "purpose": "24 V supply.",
         "active_levels": "24 V", "idle_level": "24 V"},
        {"name": "L-",
         "direction": "common",
         "purpose": "Ground / 0 V supply return.",
         "active_levels": "0 V", "idle_level": "0 V"},
        {"name": "Q (optional)",
         "direction": "Device -> Master (or input)",
         "purpose": "Additional digital output / input (pin 2).",
         "active_levels": "0 V / 24 V", "idle_level": "device-defined"},
    ]
    f["logical_signaling_levels"] = [
        {"name": "Wake-up request", "meaning": "Master pulse on the C/Q line "
         "that switches the Device from SIO to SDCI mode."},
        {"name": "UART character", "meaning": "8-E-1 octet on the C/Q line in "
         "SDCI mode."},
        {"name": "SIO switching level", "meaning": "Binary switching value on "
         "the C/Q line in SIO mode."},
    ]
    f["packet_types_summary"] = [
        {"class": "M-sequence element",
         "members": ["Master message (MC + data + CKT)",
                     "Device response (data + status + CKS)"],
         "count": 2},
        {"class": "Data type",
         "members": ["Process Data (cyclic)", "On-request Data (ISDU)",
                     "Event (diagnostics)"],
         "count": 3},
    ]
    cc = _ensure_dict(f, "channel_counts")
    cc.update({
        "signal_wires": 1,
        "total_wires": 3,
        "uart_bits_per_char": _UART_BITS_PER_CHAR,
        "process_data_max_bytes": _PD_MAX_BYTES,
        "com_rate_count": 3,
        "supply_voltage_v": _SUPPLY_V,
        "m_sequence_type_count": len(_M_SEQUENCE_TYPES),
        "device_state_count": len(_DEVICE_STATES),
    })
    f["global_signals"] = [
        {"name": "C/Q line", "purpose": "The single signal wire; SIO switching "
         "or SDCI UART communication."},
        {"name": "M-sequence", "purpose": "Master message + Device response "
         "with CKT/CKS checksums."},
        {"name": "MasterCommand", "purpose": "Drives the Device state machine "
         "(STARTUP/PREOPERATE/OPERATE/Fallback)."},
    ]
    f["dependency_graph"] = {
        "common_rule": "No M-sequence can be exchanged until the Master's "
        "wake-up request has switched the Device from SIO into SDCI mode and "
        "the COM rate has been detected.",
        "data_dependency": "Cyclic Process Data flows in OPERATE; acyclic "
        "On-request Data (ISDU) and Events are interleaved; each message is "
        "validated by the CKT/CKS checksum.",
    }
    f["handshake_pairs"] = [
        {"name": "Wake-up / mode switch", "from": "Master", "to": "Device",
         "rule": "The wake-up request switches the Device from SIO to SDCI "
                 "mode."},
        {"name": "Master message / Device response", "from": "Master",
         "to": "Device",
         "rule": "Each M-sequence is a Master message answered by a Device "
                 "response (half-duplex)."},
    ]
    f["ordering_rules"] = {
        "m_sequence_order": "Master message (MC + data + CKT) then Device "
        "response (data + status + CKS).",
        "state_order": "SIO -> (wake-up) -> STARTUP -> PREOPERATE -> OPERATE.",
        "isdu": "Large ISDU transfers are segmented across several M-sequences "
        "and reassembled in order.",
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
        "Point-to-point single-drop link: one IO-Link Device connects to one "
        "port of an IO-Link Master over a single three-wire cable (L+, L-, "
        "C/Q). There is no bus, no multi-drop, and no on-wire Device "
        "addressing; the Master provides multiple independent ports, each "
        "driving exactly one Device. IO-Link is not a fieldbus.")
    f["supported_topologies"] = [
        {"name": "Point-to-point", "description": "One Device -> one Master "
         "port over one three-wire cable (max 20 m)."},
        {"name": "Multi-port Master", "description": "A Master with several "
         "independent IO-Link ports, each a separate point-to-point link."},
        {"name": "SIO / SDCI", "description": "The same C/Q line operates as a "
         "binary switching signal (SIO) or a communication link (SDCI)."},
    ]
    f["master_slave_role_summary"] = [
        {"role": "IO-Link Master", "description": "The communication master; "
         "provides ports, issues the wake-up request, drives M-sequences, runs "
         "the Device state machine, and presents Process Data / On-request "
         "Data / Events upward. The only initiator."},
        {"role": "IO-Link Device", "description": "The communication slave "
         "(sensor or actuator); answers Master messages, provides Process "
         "Data, serves ISDU requests, raises Events, and is described by an "
         "IODD."},
    ]
    f["interconnect_role"] = (
        "IO-Link is a single-drop point-to-point sensor/actuator link on the "
        "C/Q line. Communication is half-duplex and Master-initiated; cyclic "
        "Process Data and acyclic On-request Data (ISDU) and Events flow over "
        "the same wire in SDCI mode, while SIO mode reuses the wire as a plain "
        "switching signal.")
    f["routing_methods"] = ["point-to-point (no routing)"]
    f["ordering_guarantees"] = {
        "m_sequence": "M-sequences are exchanged in order; each is a Master "
        "message answered by a Device response.",
        "process_data": "Cyclic Process Data is updated every cycle in "
        "OPERATE.",
        "isdu": "Segmented ISDU transfers are reassembled in order.",
    }
    f["memory_vs_peripheral_regions"] = (
        "IO-Link is not memory-mapped on the wire; the Direct Parameter page "
        "(read directly) and the ISDU parameter space (Index/Subindex) are the "
        "addressable surfaces. There is no on-wire Device address — one Device "
        "per Master port.")
    dc = _ensure_dict(f, "device_classification")
    dc["master"] = "IO-Link Master port that initiates and drives the link."
    dc["device"] = "IO-Link Device (sensor/actuator) that answers the Master."
    dc["transceiver"] = "C/Q line driver supporting SIO and SDCI."
    f["default_signal_values_evidence_tables"] = [
        "IO-Link three-wire interface figure (L+, L-, C/Q)",
        "C/Q dual-mode figure (SIO switching / SDCI communication)",
        "M-sequence figure (Master message / Device response, CKT/CKS)",
        "Device state machine figure (SIO/STARTUP/PREOPERATE/OPERATE)",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L19 — constraints / PDK.
# ----------------------------------------------------------------------
def _l19(gd: Path) -> None:
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["constraints_present"] = True
    f["electrical_channel_constraints"] = {
        "signaling": "single-wire (C/Q) push-pull 0 V / 24 V; UART (SDCI) / "
                     "binary switching (SIO)",
        "supply_voltage_v": _SUPPLY_V,
        "com_rates_kbaud": {"COM1": _COM1_KBAUD, "COM2": _COM2_KBAUD,
                            "COM3": _COM3_KBAUD},
        "uart_framing": "8-E-1 (1 start, 8 data, 1 even parity, 1 stop)",
        "max_cable_length_m": _MAX_CABLE_M,
        "process_data_max_bytes": _PD_MAX_BYTES,
        "clocking": "asynchronous UART (local bit clock per end)",
        "half_duplex": True,
        "point_to_point": True,
    }
    f["notes"] = (
        "IO-Link (IEC 61131-9, SDCI) is a single-drop sensor/actuator interface "
        "standard: it fixes the three-wire L+/L-/C-Q interface, the C/Q "
        "dual-mode (SIO switching / SDCI communication) with a wake-up request, "
        "UART 8-E-1 framing at COM1/COM2/COM3, the M-sequence format with "
        "CKT/CKS checksums, cyclic Process Data (up to 32 bytes) and acyclic "
        "On-request Data via the ISDU, Events, and the IODD. It does NOT impose "
        "PDK-specific SDC / floorplan constraints; the interoperability-"
        "critical constraints are the C/Q signaling, the COM-rate bit timing, "
        "the M-sequence framing, the checksums, and the MinCycleTime. The "
        "24 V push-pull driver and cable behavior are physical-layer / board "
        "concerns.")
    _write(p, d)


# ----------------------------------------------------------------------
# L20 — DFT / scan topology.
# ----------------------------------------------------------------------
def _l20(gd: Path) -> None:
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["dft_present"] = "partial"
    f["in_band_test_facilities"] = [
        {"name": "CKT/CKS checksum", "purpose": "Per-M-sequence integrity "
         "check observable at both ends."},
        {"name": "Even parity bit", "purpose": "Per-character integrity "
         "check."},
        {"name": "Device status octet", "purpose": "Status and Event flag "
         "observable each response."},
        {"name": "Direct Parameter page / ISDU", "purpose": "Identification "
         "and parameter readback for diagnostics."},
    ]
    f["internal_diagnostics_observability"] = [
        "Process Data values (in / out).",
        "Checksum-pass / error and retry counters.",
        "Device state (SIO / STARTUP / PREOPERATE / OPERATE).",
        "Event buffer (EventCode / EventQualifier).",
    ]
    f["out_of_band_test_facilities"] = [
        "IO-Link / IEC 61131-9 (SDCI) conformance / compliance testing.",
        "IODD-driven engineering-tool identification and parameterization.",
    ]
    f["notes"] = (
        "IO-Link's protocol-level DFT surface is the per-character even "
        "parity, the per-M-sequence CKT/CKS checksum, the Device status octet "
        "and Events, and the Direct Parameter page / ISDU readback. Chip-level "
        "JTAG / scan / BIST remain Device-vendor / SoC-integrator concerns; "
        "conformance is established by IO-Link (IEC 61131-9, SDCI) compliance "
        "testing.")
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
    f["power_management_states"] = [
        {"state": "SIO", "name": "Standard IO", "description": "Device powered, "
         "C/Q line as a binary switching signal, no communication."},
        {"state": "SDCI", "name": "Communication", "description": "Device "
         "powered, UART communication active on the C/Q line."},
    ]
    f["wakeup_mechanism"] = (
        "The Master applies a wake-up request on the C/Q line, switching the "
        "Device from SIO mode into SDCI communication mode. On Fallback or "
        "communication loss the Device returns to SIO.")
    f["power_rails"] = [
        {"rail": "L+ (24 V supply)", "purpose": "Device supply over the supply "
         "wire."},
        {"rail": "C/Q driver", "purpose": "Push-pull driver of the C/Q signal "
         "line."},
        {"rail": "L- (ground)", "purpose": "Ground / 0 V return."},
    ]
    f["io_link_power_considerations"] = (
        "IO-Link defines a three-wire supply: L+ (24 V), L- (ground), and the "
        "C/Q signal line. The Device draws operating current from L+/L-; the "
        "C/Q communication shares the supply ground. Detailed rails and "
        "low-power behavior are Device-implementation concerns.")
    f["notes"] = (
        "IO-Link's protocol-level power intent is a 24 V supply over the "
        "three-wire interface (L+, L-, C/Q), with the C/Q line operating in "
        "SIO (switching) or SDCI (communication) mode. Fine-grained "
        "power-domain control is a Device / SoC concern.")
    _write(p, d)


# ----------------------------------------------------------------------
# L22 — verification plan.
# ----------------------------------------------------------------------
def _l22(gd: Path) -> None:
    p = gd / "L22_VERIFICATION_PLAN.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["verification_plan_present"] = "implicit"
    f["verification_categories_derived_from_spec"] = [
        "Wake-up / mode switch — the wake-up request switches SIO to SDCI.",
        "COM-rate detection — COM1 / COM2 / COM3.",
        "UART framing — 8-E-1 at each COM rate.",
        "M-sequence — Master message + Device response with CKT/CKS (TYPE_0/1/2).",
        "Process Data — cyclic exchange up to 32 bytes per direction.",
        "On-request Data / ISDU — Index/Subindex read/write and segmentation.",
        "Events — EventCode/EventQualifier reporting.",
        "Device states — STARTUP / PREOPERATE / OPERATE via MasterCommand.",
        "MinCycleTime — the Master respects the Device's minimum cycle time.",
        "Error handling — parity, CKT/CKS, timeout, fallback to SIO.",
    ]
    f["notes"] = (
        "IO-Link does not ship an embedded testbench, but the standard implies "
        "a verification plan spanning the wake-up and SIO<->SDCI mode switch, "
        "the COM-rate detection and 8-E-1 framing, the M-sequence CKT/CKS "
        "checksums, the cyclic Process Data and MinCycleTime, the ISDU "
        "parameter access, Events, and the Device state machine. IO-Link "
        "(IEC 61131-9, SDCI) compliance testing supplies the formal suite.")
    _write(p, d)


# ----------------------------------------------------------------------
# L23 — security requirements.
# ----------------------------------------------------------------------
def _l23(gd: Path) -> None:
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["security_requirements_present"] = False
    f["anti_corruption_features"] = [
        "Even parity bit per UART character detects single-bit errors.",
        "CKT/CKS checksum per M-sequence detects message corruption.",
        "Response timeouts and retries handle lost messages.",
        "Fallback to SIO on repeated communication failure.",
    ]
    f["anti_tampering_features"] = []
    f["confidentiality_features"] = []
    f["authentication_features"] = []
    f["future_security_pointers"] = [
        "IO-Link's base SDCI protocol provides no cryptographic "
        "confidentiality or authentication on the data path; the parity and "
        "CKT/CKS checksums are anti-corruption only.",
        "IO-Link Safety (functional-safety profile) and security layering are "
        "addressed by separate IO-Link profiles above the base SDCI link.",
    ]
    f["notes"] = (
        "IO-Link (IEC 61131-9, SDCI) is a point-to-point single-drop "
        "sensor/actuator link: its built-in protection is anti-corruption (the "
        "per-character even parity plus the per-M-sequence CKT/CKS checksums "
        "and retry/fallback). The link carries plaintext UART octets. "
        "Cryptographic confidentiality / authentication are NOT part of the "
        "base SDCI data path; functional safety (IO-Link Safety) and security "
        "are provided by separate IO-Link profiles if required.")
    _write(p, d)
