"""Modbus-class protocol synth helper.

v0.1.84 — ic_class-gated overlay for `industrial_field_protocol` specs that
exhibit the Modbus structural signature (Modbus + Function Code + PDU; or
Read Holding Registers + Read Coils; or Modbus + RTU/ASCII/TCP). Applies
Modbus Application Protocol V1.1b3 (Modbus.org, April 26, 2012) canonical
content to L1-L23.

Doctrine: structural-keyword detection IS general within an ic_class
(mirrors AMBA-AXI / SPI / I2C / UART / CAN / USB / I2S synth approach).
Any Modbus Application Protocol document (V1.1, V1.1a, V1.1b, V1.1b3,
plus the companion Modbus Messaging Implementation Guide V1.0a and
Modbus over Serial Line V1.02 documents) exhibits the same signature —
Function Code + PDU + ADU framing across RTU/ASCII/TCP, the four data
tables (Discrete Inputs / Coils / Input Registers / Holding Registers),
and the 9-entry exception code table.

Public entry: `apply_modbus_synth(generated_docs_dir, is_modbus, modbus_ic_name)`.
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


def apply_modbus_synth(generated_docs_dir: Path, is_modbus: bool,
                       modbus_ic_name: Optional[str]) -> None:
    """Apply Modbus-specific synth when the structural signature matched."""
    if not is_modbus:
        return
    gd = generated_docs_dir

    # Force ic_name across the 14 main L docs that carry top-level ic_name
    # (L14..L23 wrap content under "fields" per the protocol-spec template
    # convention and intentionally do NOT carry a top-level ic_name).
    if modbus_ic_name is not None:
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
                d["ic_name"] = modbus_ic_name
                _write(q, d)

    # ---------------- L1 datasheet metadata ----------------
    p = gd / "L1_DATASHEET.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("document_title", "MODBUS APPLICATION PROTOCOL SPECIFICATION V1.1b3")
        d.setdefault("version", "V1.1b3")
        d.setdefault("revised_date", "April 26, 2012")
        d.setdefault("manufacturer",
            "Modbus Organization, Inc. (Modbus.org) — successor to Modicon / Schneider Automation")
        d.setdefault("copyright",
            "© 2012 Modbus Organization, Inc. — MODBUS is a registered trademark of Schneider Automation Inc.")
        d.setdefault("abstract",
            "MODBUS is an application-layer (OSI level 7) request/reply messaging protocol that provides "
            "client/server communication between devices connected on different types of buses or networks. "
            "It has been the industry's serial de-facto standard since 1979. The protocol defines a simple "
            "Protocol Data Unit (PDU) independent of the underlying communication layers; the mapping on "
            "specific buses or networks introduces additional fields on the Application Data Unit (ADU) — "
            "server address + CRC for RTU, ':' + 2-ASCII-hex address + LRC + CR-LF for ASCII, or a 7-byte "
            "MBAP Header for MODBUS TCP. Function codes (1 byte; range 1..255, code 0 invalid; 128..255 "
            "reserved for exception responses) name actions across four categories: Bit Access (Coils + "
            "Discrete Inputs), 16-bit Access (Holding + Input Registers), File Record access, and "
            "Diagnostics / Encapsulated Interface Transport.")
        d.setdefault("keywords", [
            "MODBUS", "Modbus.org", "application protocol", "OSI layer 7",
            "PDU", "ADU", "MBAP", "function code", "exception code",
            "Modbus RTU", "Modbus ASCII", "Modbus TCP", "Modbus PLUS", "MB+", "HDLC",
            "Coils", "Discrete Inputs", "Holding Registers", "Input Registers",
            "Read Coils 0x01", "Read Discrete Inputs 0x02", "Read Holding Registers 0x03",
            "Read Input Registers 0x04", "Write Single Coil 0x05", "Write Single Register 0x06",
            "Write Multiple Coils 0x0F", "Write Multiple Registers 0x10",
            "Mask Write Register 0x16", "Read/Write Multiple Registers 0x17", "Read FIFO Queue 0x18",
            "Read File Record 0x14", "Write File Record 0x15",
            "Read Exception Status 0x07", "Diagnostics 0x08", "Get Comm Event Counter 0x0B",
            "Get Comm Event Log 0x0C", "Report Server ID 0x11",
            "Encapsulated Interface Transport 0x2B", "MEI 13", "MEI 14",
            "CANopen General Reference", "Read Device Identification",
            "client/server", "master/slave", "request/reply",
            "EIA/TIA-232", "EIA/TIA-422", "EIA/TIA-485", "RS-232", "RS-485",
            "big-endian", "CRC-16", "LRC", "port 502",
        ])
        d.setdefault("external_pins", [
            "MODBUS is an application-layer protocol, not a chip; it has no physical pinout. ",
            "The underlying transport supplies the physical wires: ",
            "Modbus RTU/ASCII on EIA/TIA-485 — A (D+) and B (D-) differential pair, optional ground, half-duplex; ",
            "Modbus RTU/ASCII on EIA/TIA-232 — TXD, RXD, GND, and optional RTS/CTS/DSR/DTR/DCD/RI handshake; ",
            "Modbus TCP — Ethernet (MAC + PHY), MODBUS server reserved at TCP port 502.",
        ])
        d.setdefault("external_pin_count", 0)
        d.setdefault("package",
            "Not applicable — MODBUS is a protocol specification, distributed as a PDF "
            "document (50 pages) by Modbus.org. The 'package' is the OSI-layer-7 "
            "application-protocol payload that rides on top of a vendor- and "
            "transport-chosen physical layer.")
        d.setdefault("supported_transports", [
            {"name": "Modbus RTU (serial)",
             "physical_layer": "EIA/TIA-232 or EIA/TIA-485 (typical baud 9600 / 19200 / 38400 / 115200; vendor-extensible)",
             "duplex": "half-duplex on RS-485 / full-duplex on RS-232",
             "adu_size_bytes": 256,
             "adu_format": "Address (1 B) + PDU (≤ 253 B) + CRC-16-Modbus (2 B)",
             "framing": "End-of-frame = ≥ 3.5 character times of silent line"},
            {"name": "Modbus ASCII (serial)",
             "physical_layer": "EIA/TIA-232 or EIA/TIA-485",
             "duplex": "half-duplex on RS-485 / full-duplex on RS-232",
             "adu_size_bytes": "≤ 513 characters on the wire (each PDU byte → 2 ASCII hex chars)",
             "adu_format": "':' + Address (2 ASCII hex) + PDU as ASCII hex (2N chars) + LRC (2 ASCII hex) + CR LF",
             "framing": "Start-of-frame ':'; end-of-frame CR LF"},
            {"name": "Modbus TCP",
             "physical_layer": "TCP/IP on Ethernet (IEEE 802.3), reserved server port 502",
             "duplex": "full-duplex",
             "adu_size_bytes": 260,
             "adu_format": "MBAP Header (Transaction ID 2 B + Protocol ID 2 B = 0x0000 + Length 2 B + Unit ID 1 B) + PDU (≤ 253 B)",
             "framing": "TCP segment boundaries + MBAP.Length field"},
            {"name": "MODBUS PLUS (MB+)",
             "physical_layer": "HDLC-based token-passing network (Modicon-proprietary legacy)",
             "duplex": "token-controlled",
             "adu_size_bytes": "vendor-specific",
             "adu_format": "HDLC frame carrying MODBUS PDU",
             "framing": "Token-passing"},
        ])
        d.setdefault("modes_of_operation", [
            {"name": "Modbus RTU on serial",   "description": "Binary 8-bit transmission. Address + PDU + CRC-16. End-of-frame = 3.5 character-time silence."},
            {"name": "Modbus ASCII on serial", "description": "ASCII-hex transmission. ':' + 2-ASCII-hex address + 2N ASCII-hex PDU + 2-ASCII-hex LRC + CR LF."},
            {"name": "Modbus TCP (Open MODBUS)", "description": "Binary PDU prefixed with a 7-byte MBAP header. Runs on TCP port 502. No CRC."},
            {"name": "Modbus PLUS (legacy)",   "description": "High-speed token-passing peer-to-peer network on HDLC carrier; Modicon-proprietary."},
        ])
        d.setdefault("key_features", [
            "Application-layer request/reply protocol — OSI level 7 — independent of the underlying communication layer.",
            "Single-master / multi-slave (legacy serial RTU/ASCII) or client/server (modern TCP).",
            "Compact 1-byte function code identifies the action. Valid range 1..255; 128..255 reserved for exception responses; 0 invalid.",
            "Function-code categories: Bit-Access (read/write Coils + read Discrete Inputs), 16-bit-Access (read/write Holding Registers + read Input Registers), File Record access, Diagnostics + Encapsulated Interface Transport.",
            "Four primary data tables: Discrete Inputs (1 bit RO), Coils (1 bit R/W), Input Registers (16 bit RO), Holding Registers (16 bit R/W). Each table addresses up to 65536 items.",
            "Address space: PDU addresses each item 0..65535; the user-facing data model numbers items 1..n; PDU address = user_number - 1.",
            "Big-Endian byte order on the wire: 0x1234 transmits 0x12 first then 0x34.",
            "Exception response: server returns the original function code OR'd with 0x80 followed by a 1-byte exception code (1=Illegal Function, 2=Illegal Data Address, 3=Illegal Data Value, 4=Server Failure, 5=Acknowledge, 6=Busy, 8=Memory Parity Error, 0x0A=Gateway Path Unavailable, 0x0B=Gateway Target Failed).",
            "PDU maximum size = 253 bytes. ADU max: RTU 256 B / ASCII 513 chars / TCP 260 B.",
            "Read Coils / Read Discrete Inputs (FC 1, 2) — up to 2000 (0x7D0) bits per request; coils packed 8 per byte LSB-first.",
            "Read Holding / Read Input Registers (FC 3, 4) — up to 125 (0x7D) registers per request; each register 2 bytes high-byte-first.",
            "Write Single Coil (FC 5) — output value 0xFF00 = ON, 0x0000 = OFF; all other values illegal.",
            "Write Multiple Coils (FC 15 / 0x0F) — up to 1968 (0x7B0) coils per request.",
            "Write Multiple Registers (FC 16 / 0x10) — up to 123 (0x7B) registers per request.",
            "Read/Write Multiple Registers (FC 23 / 0x17) — read up to 125 + write up to 121 registers in one transaction.",
            "Mask Write Register (FC 22 / 0x16) — atomic Result = (Current AND AND_Mask) OR (OR_Mask AND (NOT AND_Mask)).",
            "Read FIFO Queue (FC 24 / 0x18) — drains up to 31 (0x1F) 16-bit registers from a FIFO at a specified pointer address.",
            "File Record access (FC 20 / 0x14 Read, FC 21 / 0x15 Write) — accesses a Reference Type 6 file model.",
            "Serial-only Diagnostics: FC 7, 8 (sub 0..18 + 20), 11, 12, 17.",
            "Encapsulated Interface Transport (FC 43 / 0x2B): MEI 13 = CANopen General Reference, MEI 14 = Read Device Identification.",
            "Three Function-Code Categories: Public (1..64, 73..99, 111..127), User-Defined (65..72, 100..110), and Reserved (Annex A).",
        ])
        d.setdefault("data_model_summary", [
            "Discrete Inputs   : 1-bit RO, provided by an I/O system.",
            "Coils             : 1-bit R/W, alterable by application program.",
            "Input Registers   : 16-bit RO, provided by an I/O system.",
            "Holding Registers : 16-bit R/W, alterable by application program.",
        ])
        d.setdefault("overview",
            "MODBUS is the industry's serial de-facto standard since 1979. Originally invented by Modicon for "
            "its PLC family, it is now overseen by Modbus.org and exists as three open variants: Modbus RTU "
            "(binary, with CRC-16, on RS-232 or RS-485), Modbus ASCII (ASCII-hex, with LRC, line-readable), "
            "and Modbus TCP (binary PDU with a 7-byte MBAP header, on TCP/IP port 502). The application "
            "protocol is simple: a single-byte function code names an action and is followed by a "
            "function-code-dependent data field. Four memory-mapped tables — Discrete Inputs (1-bit RO), "
            "Coils (1-bit R/W), Input Registers (16-bit RO), and Holding Registers (16-bit R/W) — hold the "
            "device data. The protocol defines a clean exception mechanism: the server replies with the "
            "original function code OR'd with 0x80 followed by a 1-byte exception code naming the error.")
        d.setdefault("block_diagram_components", [
            "MODBUS application layer (function-code processor) — common across all transports",
            "Modbus RTU framer (ADU = Address + PDU + CRC-16; T3.5 silent-line end-of-frame detection)",
            "Modbus ASCII framer (ADU = ':' + 2-ASCII-hex address + 2N-char PDU + LRC + CR LF)",
            "Modbus TCP framer (MBAP Header: Transaction ID + Protocol ID = 0 + Length + Unit ID, on TCP socket port 502)",
            "Four data tables: Discrete Inputs (1-bit RO), Coils (1-bit R/W), Input Registers (16-bit RO), Holding Registers (16-bit R/W)",
            "Exception-response generator (FC | 0x80 + exception code)",
            "Diagnostics sub-function table (FC 8 sub-codes 0..18, 20)",
            "Encapsulated Interface Transport (FC 43, MEI types 13 CANopen / 14 Read Device Identification)",
            "Optional File Record store (FC 20 / 21)",
            "Optional FIFO queue (FC 24)",
        ])
        d.setdefault("process_technology",
            "Not applicable — MODBUS is a published protocol specification (PDF), not a silicon part. "
            "Implementations exist as RTL IP cores, microcontroller firmware, PLC engines, embedded "
            "gateways, and software stacks (libmodbus, pymodbus, FreeModbus, etc.).")
        d.setdefault("use_cases", [
            "Industrial PLC ↔ I/O device communication (read sensor inputs, write actuator outputs)",
            "SCADA / HMI ↔ field-device polling over RS-485 multi-drop bus",
            "Modbus TCP gateway bridging an Ethernet-side SCADA system to legacy serial Modbus RTU sub-networks",
            "Building automation, HVAC, energy metering, and electric-utility substation telemetry",
            "Renewable energy: inverter / battery-management-system data acquisition",
            "Process control: chemical / oil-gas / water-treatment plant device polling",
            "Variable-frequency drive (VFD) configuration and run-time monitoring",
        ])
        d.setdefault("transaction_summary",
            "A client builds the request ADU = optional-address + Function Code + Data + "
            "optional-CRC/LRC, sends it to the server. The server validates the function code "
            "(else exception 0x01), validates the data address (else 0x02), validates the data "
            "value (else 0x03), executes the function (else 0x04), and replies — either a normal "
            "response (echoes the function code with response data) or an exception response "
            "(function code | 0x80 + exception code).")
        _write(p, d)

    # ---------------- L2 FRS ----------------
    p = gd / "L2_FRS.json"
    if p.is_file():
        d = _read(p)
        po = d.setdefault("protocol_overview", {})
        if isinstance(po, dict):
            po.setdefault("type",
                "Application-layer (OSI level 7) request/reply messaging protocol with a transport-agnostic "
                "Protocol Data Unit (PDU = Function Code + Data) and three published Application Data Unit "
                "(ADU) framings: Modbus RTU, Modbus ASCII, and Modbus TCP.")
            po.setdefault("role_model",
                "Single client (master) initiates a transaction; one or more servers (slaves) reply. "
                "Address 0 in RTU/ASCII ADU is broadcast — broadcast frames are not acknowledged.")
            po.setdefault("synchronous", False)
            po.setdefault("duplex_per_transport", {
                "Modbus RTU on RS-485": "half-duplex multi-drop",
                "Modbus RTU on RS-232": "full-duplex point-to-point",
                "Modbus ASCII on RS-485": "half-duplex multi-drop",
                "Modbus ASCII on RS-232": "full-duplex point-to-point",
                "Modbus TCP": "full-duplex on TCP socket",
            })
            po.setdefault("pdu_format", "Function Code (1 byte) + Data (0..252 bytes)")
            po.setdefault("adu_format_per_transport", {
                "Modbus RTU":   "Address (1 B) + PDU (≤ 253 B) + CRC-16-Modbus (2 B, low byte first) — total ≤ 256 B",
                "Modbus ASCII": "':' + 2-hex address + 2-hex FC + 2N-hex data + 2-hex LRC + CR LF",
                "Modbus TCP":   "MBAP Header (7 B) + PDU (≤ 253 B) — total ≤ 260 B",
            })
            po.setdefault("max_pdu_bytes", 253)
            po.setdefault("max_adu_bytes_rtu", 256)
            po.setdefault("max_adu_bytes_tcp", 260)
            po.setdefault("byte_order_on_wire", "big-endian")
            po.setdefault("broadcast_address", 0)
            po.setdefault("tcp_reserved_port", 502)
            po.setdefault("function_code_categories", [
                "Bit Access — FC 01, 02, 05, 15",
                "16-bit Access — FC 03, 04, 06, 16, 22, 23 + 24 (FIFO)",
                "File Record Access — FC 20, 21",
                "Diagnostics — FC 07, 08, 11, 12, 17",
                "Encapsulated Interface Transport — FC 43 (MEI 13 CANopen / MEI 14 Read Device Identification)",
            ])
            po.setdefault("data_model_tables", [
                {"name": "Discrete Inputs",   "object_type": "Single bit",   "access": "Read-Only"},
                {"name": "Coils",              "object_type": "Single bit",   "access": "Read-Write"},
                {"name": "Input Registers",   "object_type": "16-bit word",  "access": "Read-Only"},
                {"name": "Holding Registers", "object_type": "16-bit word",  "access": "Read-Write"},
            ])
            po.setdefault("address_space_per_table_items", 65536)
            po.setdefault("address_mapping_rule",
                "PDU address X corresponds to user-facing data-model number X+1; "
                "data numbered X is at PDU address X-1.")
        fr = [
            {"id": "FR-PDU-01",    "text": "Every MODBUS PDU shall start with a 1-byte Function Code in range 1..255 (0 invalid). Total PDU length ≤ 253 bytes."},
            {"id": "FR-ADU-02",    "text": "Modbus RTU ADU = Address (1 B) + PDU + CRC-16 (2 B, low byte first); total ≤ 256 B. ASCII ADU = ':' + 2N-hex chars + LRC + CR LF."},
            {"id": "FR-MBAP-03",   "text": "Modbus TCP ADU = MBAP Header (Transaction ID 2 B + Protocol ID 2 B = 0 + Length 2 B + Unit ID 1 B) + PDU; total ≤ 260 B."},
            {"id": "FR-FC-04",     "text": "Function code 0 invalid; FCs 128..255 reserved for exception responses; FCs 65..72 and 100..110 are User-Defined; remainder 1..127 reserved for Public function codes."},
            {"id": "FR-DATA-MODEL-05","text": "Four data tables: Discrete Inputs (1-bit RO), Coils (1-bit R/W), Input Registers (16-bit RO), Holding Registers (16-bit R/W). Each addresses up to 65536 items."},
            {"id": "FR-FC01-06",   "text": "FC 0x01 Read Coils: Starting Address (2 B) + Quantity (1..2000); response = FC + Byte Count + ceil(N/8) bytes; LSB of first byte = first coil."},
            {"id": "FR-FC02-07",   "text": "FC 0x02 Read Discrete Inputs: same shape as FC 1; quantity 1..2000."},
            {"id": "FR-FC03-08",   "text": "FC 0x03 Read Holding Registers: Starting Address (2 B) + Quantity (1..125); response = FC + Byte Count + 2N bytes (high byte first)."},
            {"id": "FR-FC04-09",   "text": "FC 0x04 Read Input Registers: identical shape to FC 3."},
            {"id": "FR-FC05-10",   "text": "FC 0x05 Write Single Coil: Output Address + Output Value; valid 0xFF00 (ON) / 0x0000 (OFF); response echoes request."},
            {"id": "FR-FC06-11",   "text": "FC 0x06 Write Single Register: Register Address + Register Value; response echoes request."},
            {"id": "FR-FC0F-12",   "text": "FC 0x0F Write Multiple Coils: quantity 1..1968; response = FC + Starting Address + Quantity."},
            {"id": "FR-FC10-13",   "text": "FC 0x10 Write Multiple Registers: quantity 1..123; response = FC + Starting Address + Quantity."},
            {"id": "FR-FC16-14",   "text": "FC 0x16 Mask Write Register: Result = (Current AND AND_Mask) OR (OR_Mask AND (NOT AND_Mask))."},
            {"id": "FR-FC17-15",   "text": "FC 0x17 Read/Write Multiple Registers: read 1..125 + write 1..121 in single transaction."},
            {"id": "FR-FC18-16",   "text": "FC 0x18 Read FIFO Queue: returns Byte Count + FIFO Count (≤ 31) + FIFO values (≤ 62 bytes)."},
            {"id": "FR-FILE-17",   "text": "FC 0x14 / 0x15 access Reference Type 6 file records; multi-sub-request PDU; per-PDU ≤ 252 data bytes."},
            {"id": "FR-FC07-18",   "text": "FC 0x07 Read Exception Status (serial only): returns 8 device-specific exception-status bits in one byte."},
            {"id": "FR-FC08-19",   "text": "FC 0x08 Diagnostics (serial only): sub-functions 0..18 + 20 (00 Return Query Data, 04 Force Listen Only, 0A Clear Counters, 0B..12 counter reads)."},
            {"id": "FR-FC0B-20",   "text": "FC 0x0B Get Comm Event Counter (serial only): Status (2 B) + Event Count (2 B)."},
            {"id": "FR-FC0C-21",   "text": "FC 0x0C Get Comm Event Log (serial only): Byte Count + Status + Event Count + Message Count + ≤ 64 event bytes."},
            {"id": "FR-FC11-22",   "text": "FC 0x11 Report Server ID (serial only): Server ID + Run Indicator (0x00 OFF / 0xFF ON) + device-specific data."},
            {"id": "FR-FC2B-23",   "text": "FC 0x2B Encapsulated Interface: MEI Type 0x0D (CANopen) / 0x0E (Read Device Identification)."},
            {"id": "FR-EXCEPT-24", "text": "Exception PDU = (FC OR 0x80) + Exception Code. Codes: 0x01..0x06, 0x08, 0x0A, 0x0B (no 0x07, 0x09)."},
            {"id": "FR-ENDIAN-25", "text": "Multi-byte numerical quantities transmitted big-endian: 0x1234 → 0x12, 0x34."},
            {"id": "FR-ADDRMAP-26","text": "Item numbered X in user model is at PDU address X-1; PDU addresses 0..65535."},
            {"id": "FR-BCAST-27",  "text": "On serial transports, Address 0 = broadcast. Servers do not reply. Read codes are not broadcastable."},
            {"id": "FR-TIMEOUT-28","text": "Client manages a request timeout to avoid waiting indefinitely when server does not reply."},
        ]
        if _empty(d.get("functional_requirements")):
            d["functional_requirements"] = fr
        d.setdefault("error_response_conditions", [
            "Function code not implemented → 0x01 ILLEGAL FUNCTION.",
            "Address + Quantity outside server's data table → 0x02 ILLEGAL DATA ADDRESS.",
            "Quantity outside per-function limit or FC 5 Output Value ∉ {0xFF00, 0x0000} → 0x03 ILLEGAL DATA VALUE.",
            "Unrecoverable internal error during execution → 0x04 SERVER DEVICE FAILURE.",
            "Long-running programming command accepted but not yet complete → 0x05 ACKNOWLEDGE.",
            "Server busy with another long-duration command → 0x06 SERVER DEVICE BUSY.",
            "FC 0x14 / 0x15 reference-type-6 file area consistency check failed → 0x08 MEMORY PARITY ERROR.",
            "Gateway misconfigured / overloaded → 0x0A GATEWAY PATH UNAVAILABLE.",
            "Gateway forwarded request; target unresponsive → 0x0B GATEWAY TARGET DEVICE FAILED TO RESPOND.",
            "Serial-line communication error (parity/framing/CRC/LRC) → silent discard; no response.",
        ])
        if _empty(d.get("compliance_requirements")):
            d["compliance_requirements"] = [
                "MODBUS PDU shall not exceed 253 bytes regardless of transport.",
                "Modbus RTU ADU shall not exceed 256 bytes.",
                "Modbus TCP ADU shall not exceed 260 bytes; MBAP.Protocol_ID shall be 0x0000.",
                "Function code field 1 byte; value 0 invalid.",
                "Exception response sets MSB of function code (FC | 0x80).",
                "Big-endian byte order for multi-byte numerical quantities.",
                "FC 1 / 2 quantity 1..2000; FC 3 / 4 quantity 1..125.",
                "FC 0x0F quantity 1..1968; FC 0x10 quantity 1..123; FC 0x17 read 1..125 + write 1..121.",
                "FC 0x05 output value exactly 0xFF00 (ON) or 0x0000 (OFF).",
                "FC 0x18 returns at most 31 FIFO registers.",
            ]
        _write(p, d)

    # ---------------- L3 protocol channels + opcodes ----------------
    p = gd / "L3_CMD_PROTOCOL.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("protocol_type",
            "Request/reply application-layer protocol. The client (master) initiates every "
            "transaction by sending a Function Code + Data PDU, and the server (slave) replies "
            "with either a normal response or an exception response (FC | 0x80) + Exception Code. "
            "The same PDU rides three published ADU framings: Modbus RTU, Modbus ASCII, and Modbus TCP.")
        if _empty(d.get("opcodes")):
            d["opcodes"] = [
                {"name": "Read Coils",                    "code_hex": "0x01", "code_dec": 1,  "category": "Bit-Access read",  "section": "6.1",  "scope": "all transports", "broadcastable": False, "max_items_per_request": 2000, "max_items_hex": "0x07D0"},
                {"name": "Read Discrete Inputs",          "code_hex": "0x02", "code_dec": 2,  "category": "Bit-Access read",  "section": "6.2",  "scope": "all transports", "broadcastable": False, "max_items_per_request": 2000, "max_items_hex": "0x07D0"},
                {"name": "Read Holding Registers",        "code_hex": "0x03", "code_dec": 3,  "category": "16-bit read",      "section": "6.3",  "scope": "all transports", "broadcastable": False, "max_items_per_request": 125,  "max_items_hex": "0x007D"},
                {"name": "Read Input Registers",          "code_hex": "0x04", "code_dec": 4,  "category": "16-bit read",      "section": "6.4",  "scope": "all transports", "broadcastable": False, "max_items_per_request": 125,  "max_items_hex": "0x007D"},
                {"name": "Write Single Coil",             "code_hex": "0x05", "code_dec": 5,  "category": "Bit-Access write", "section": "6.5",  "scope": "all transports", "broadcastable": True},
                {"name": "Write Single Register",         "code_hex": "0x06", "code_dec": 6,  "category": "16-bit write",     "section": "6.6",  "scope": "all transports", "broadcastable": True},
                {"name": "Read Exception Status",         "code_hex": "0x07", "code_dec": 7,  "category": "Diagnostics",      "section": "6.7",  "scope": "Serial line only", "broadcastable": False},
                {"name": "Diagnostics",                   "code_hex": "0x08", "code_dec": 8,  "category": "Diagnostics",      "section": "6.8",  "scope": "Serial line only", "broadcastable": False, "sub_function_codes": "00..18, 20"},
                {"name": "Get Comm Event Counter",        "code_hex": "0x0B", "code_dec": 11, "category": "Diagnostics",      "section": "6.9",  "scope": "Serial line only", "broadcastable": False},
                {"name": "Get Comm Event Log",            "code_hex": "0x0C", "code_dec": 12, "category": "Diagnostics",      "section": "6.10", "scope": "Serial line only", "broadcastable": False},
                {"name": "Write Multiple Coils",          "code_hex": "0x0F", "code_dec": 15, "category": "Bit-Access write", "section": "6.11", "scope": "all transports", "broadcastable": True, "max_items_per_request": 1968, "max_items_hex": "0x07B0"},
                {"name": "Write Multiple Registers",      "code_hex": "0x10", "code_dec": 16, "category": "16-bit write",     "section": "6.12", "scope": "all transports", "broadcastable": True, "max_items_per_request": 123,  "max_items_hex": "0x007B"},
                {"name": "Report Server ID",              "code_hex": "0x11", "code_dec": 17, "category": "Diagnostics",      "section": "6.13", "scope": "Serial line only", "broadcastable": False},
                {"name": "Read File Record",              "code_hex": "0x14", "code_dec": 20, "category": "File Record",      "section": "6.14", "scope": "all transports", "broadcastable": False},
                {"name": "Write File Record",             "code_hex": "0x15", "code_dec": 21, "category": "File Record",      "section": "6.15", "scope": "all transports", "broadcastable": False},
                {"name": "Mask Write Register",           "code_hex": "0x16", "code_dec": 22, "category": "16-bit write",     "section": "6.16", "scope": "all transports", "broadcastable": True, "operation": "Result = (Current AND AND_Mask) OR (OR_Mask AND (NOT AND_Mask))"},
                {"name": "Read/Write Multiple Registers", "code_hex": "0x17", "code_dec": 23, "category": "16-bit read+write","section": "6.17", "scope": "all transports", "broadcastable": False, "max_read_per_request": 125, "max_write_per_request": 121},
                {"name": "Read FIFO Queue",               "code_hex": "0x18", "code_dec": 24, "category": "16-bit read",      "section": "6.18", "scope": "all transports", "broadcastable": False},
                {"name": "Encapsulated Interface Transport", "code_hex": "0x2B", "code_dec": 43, "category": "Encapsulated MEI", "section": "6.19", "scope": "all transports", "broadcastable": False,
                 "MEI_types": [
                    {"mei_hex": "0x0D", "mei_dec": 13, "name": "CANopen General Reference Request and Response PDU", "section": "6.20"},
                    {"mei_hex": "0x0E", "mei_dec": 14, "name": "Read Device Identification",                          "section": "6.21"},
                 ]},
            ]
        d.setdefault("function_code_ranges", {
            "Public_low_range":         "1..64 + 73..99 + 111..127",
            "User_Defined_range_1":     "65..72",
            "User_Defined_range_2":     "100..110",
            "Reserved_range":           "Annex A — FC 9, 10, 13, 14, 41, 42, 90, 91, 125..127; FC 8 sub 19, 21..65535; FC 43 sub-MEI 0..12, 15..255",
            "Exception_response_range": "128..255",
            "Invalid_code":             "0 (not valid)",
        })
        d.setdefault("exception_codes", [
            {"code_hex": "0x01", "name": "ILLEGAL FUNCTION",                            "meaning": "FC not implemented or server not in a state to process it."},
            {"code_hex": "0x02", "name": "ILLEGAL DATA ADDRESS",                        "meaning": "Reference + length invalid for server's data space."},
            {"code_hex": "0x03", "name": "ILLEGAL DATA VALUE",                          "meaning": "Value field outside per-function limit; structural error."},
            {"code_hex": "0x04", "name": "SERVER DEVICE FAILURE",                       "meaning": "Unrecoverable internal error during execution."},
            {"code_hex": "0x05", "name": "ACKNOWLEDGE",                                 "meaning": "Long-running command accepted; client should poll for completion."},
            {"code_hex": "0x06", "name": "SERVER DEVICE BUSY",                          "meaning": "Server busy with another long command."},
            {"code_hex": "0x08", "name": "MEMORY PARITY ERROR",                         "meaning": "FC 20/21 extended file area consistency check failed."},
            {"code_hex": "0x0A", "name": "GATEWAY PATH UNAVAILABLE",                    "meaning": "Gateway could not allocate input→output path."},
            {"code_hex": "0x0B", "name": "GATEWAY TARGET DEVICE FAILED TO RESPOND",     "meaning": "Gateway forwarded request; target sub-device did not reply."},
        ])
        d.setdefault("diagnostics_subfunctions_FC08", [
            {"sub_hex": "0x0000", "sub_dec": 0,  "name": "Return Query Data"},
            {"sub_hex": "0x0001", "sub_dec": 1,  "name": "Restart Communications Option"},
            {"sub_hex": "0x0002", "sub_dec": 2,  "name": "Return Diagnostic Register"},
            {"sub_hex": "0x0003", "sub_dec": 3,  "name": "Change ASCII Input Delimiter"},
            {"sub_hex": "0x0004", "sub_dec": 4,  "name": "Force Listen Only Mode"},
            {"sub_hex": "0x000A", "sub_dec": 10, "name": "Clear Counters and Diagnostic Register"},
            {"sub_hex": "0x000B", "sub_dec": 11, "name": "Return Bus Message Count"},
            {"sub_hex": "0x000C", "sub_dec": 12, "name": "Return Bus Communication Error Count"},
            {"sub_hex": "0x000D", "sub_dec": 13, "name": "Return Bus Exception Error Count"},
            {"sub_hex": "0x000E", "sub_dec": 14, "name": "Return Server Message Count"},
            {"sub_hex": "0x000F", "sub_dec": 15, "name": "Return Server No Response Count"},
            {"sub_hex": "0x0010", "sub_dec": 16, "name": "Return Server NAK Count"},
            {"sub_hex": "0x0011", "sub_dec": 17, "name": "Return Server Busy Count"},
            {"sub_hex": "0x0012", "sub_dec": 18, "name": "Return Bus Character Overrun Count"},
            {"sub_hex": "0x0014", "sub_dec": 20, "name": "Clear Overrun Counter and Flag"},
        ])
        d.setdefault("channels", [
            {"name": "Modbus RTU on EIA/TIA-485", "wires": ["A (D+) differential", "B (D-) differential", "GND"], "framing": "T3.5 silent-line end-of-frame", "error_check": "CRC-16-Modbus"},
            {"name": "Modbus RTU on EIA/TIA-232", "wires": ["TXD", "RXD", "GND"], "framing": "T3.5 silent-line end-of-frame", "error_check": "CRC-16-Modbus"},
            {"name": "Modbus ASCII on serial",    "wires": ["TXD/RXD or RS-485 A/B", "GND"], "framing": "':' = SOF, CR LF = EOF", "error_check": "LRC (Longitudinal Redundancy Check)"},
            {"name": "Modbus TCP",                "wires": ["Ethernet MAC + PHY"], "framing": "TCP segment + MBAP.Length", "error_check": "TCP checksum + Ethernet CRC-32"},
        ])
        d.setdefault("host_bus_interface",
            "Implementation-defined. Typical IP-core RTL exposes (a) an APB/AHB/AXI slave port for "
            "register configuration + four mapped data tables, and (b) a UART or Ethernet-MAC port for "
            "the ADU on the wire. No standardized MODBUS CPU-bus is mandated.")
        d.setdefault("valid_ready_handshake_rules", [
            "MODBUS is strictly request/reply — there is no per-byte ACK; ACK is implicit in the normal response PDU.",
            "Server shall not reply to a broadcast address-0 frame (serial transports).",
            "If the server detects a transmission error (parity/framing/CRC/LRC), it shall send no reply.",
            "On Modbus TCP, client may pipeline multiple outstanding transactions via Transaction_ID; server echoes the same ID.",
            "Client should manage a request timeout to avoid indefinite waits.",
            "Programming-style long commands may return exception 0x05 ACKNOWLEDGE so client doesn't time out.",
        ])
        d.setdefault("burst_based", False)
        d.setdefault("byte_oriented", True)
        d.setdefault("frame_format_rtu", {
            "address":      "1 byte. 0 = broadcast; 1..247 = individual server; 248..255 = reserved.",
            "function_code":"1 byte; 1..255 (excluding 0).",
            "data":         "0..252 bytes; layout depends on function code.",
            "error_check":  "CRC-16-Modbus, 2 bytes, low byte first on the wire.",
            "framing":      "End-of-frame indicated by ≥ 3.5 character-time silence on the line.",
        })
        d.setdefault("frame_format_ascii", {
            "start_of_frame": "':' (0x3A) — 1 character.",
            "address":        "2 ASCII-hex characters (encodes 1 byte).",
            "function_code":  "2 ASCII-hex characters (encodes 1 byte).",
            "data":           "2N ASCII-hex characters (encodes N bytes of PDU data).",
            "error_check":    "LRC over Address + Function + Data, 2 ASCII-hex characters (1 byte).",
            "end_of_frame":   "CR (0x0D) + LF (0x0A) — 2 characters.",
        })
        d.setdefault("frame_format_tcp", {
            "transaction_id":"2 bytes. Set by client; echoed by server.",
            "protocol_id":   "2 bytes. Always 0x0000 for MODBUS.",
            "length":        "2 bytes. = 1 (Unit ID) + len(PDU).",
            "unit_id":       "1 byte. Server address on a sub-network behind a gateway; 0xFF/0x00 when TCP endpoint is itself the server.",
            "pdu":           "Function Code (1 B) + Data (0..252 B).",
        })
        _write(p, d)

    # ---------------- L4 register map (logical data tables) ----------------
    p = gd / "L4_REGMAP.json"
    if p.is_file():
        d = _read(p)
        d["register_map_present"] = True
        # Force-override: serial-peripheral universal synth (SPI) writes a
        # generic "Defined at SoC level" default before the Modbus structural
        # detector fires. Modbus is a protocol, not a memory-mapped device,
        # so direct-assign the protocol-accurate value.
        d["base_address"] = (
            "Not applicable in the same sense as a memory-mapped peripheral. MODBUS organizes "
            "server-side state as four logical tables (Discrete Inputs, Coils, Input Registers, "
            "Holding Registers), each independently addressed 0..65535 in the PDU. The user-visible "
            "numbering of each item is PDU_address + 1.")
        d.setdefault("register_count",
            "Up to 65536 per table × 4 tables = 262144 logical items; actual deployment is "
            "application-defined and almost always a small subset.")
        d.setdefault("data_tables", [
            {"name": "Discrete Inputs",   "object_type": "Single bit",   "access": "Read-Only",
             "pdu_address_range": "0x0000..0xFFFF", "user_index_range": "1..65536",
             "function_codes": ["0x02 Read Discrete Inputs"]},
            {"name": "Coils",              "object_type": "Single bit",   "access": "Read-Write",
             "pdu_address_range": "0x0000..0xFFFF", "user_index_range": "1..65536",
             "function_codes": ["0x01 Read Coils", "0x05 Write Single Coil", "0x0F Write Multiple Coils"]},
            {"name": "Input Registers",   "object_type": "16-bit word",  "access": "Read-Only",
             "pdu_address_range": "0x0000..0xFFFF", "user_index_range": "1..65536",
             "function_codes": ["0x04 Read Input Registers"]},
            {"name": "Holding Registers", "object_type": "16-bit word",  "access": "Read-Write",
             "pdu_address_range": "0x0000..0xFFFF", "user_index_range": "1..65536",
             "function_codes": ["0x03 Read Holding Registers", "0x06 Write Single Register",
                                "0x10 Write Multiple Registers", "0x16 Mask Write Register",
                                "0x17 Read/Write Multiple Registers", "0x18 Read FIFO Queue"]},
        ])
        regs = [
            {"name": "MBAP_TRANSACTION_ID", "long_name": "MBAP Transaction Identifier", "offset": "TCP ADU bytes 0..1", "width_bits": 16, "access": "client-set, server-echo", "scope": "Modbus TCP only", "description": "Identification of a MODBUS Request/Response transaction. Allows pipelined transactions."},
            {"name": "MBAP_PROTOCOL_ID",     "long_name": "MBAP Protocol Identifier",    "offset": "TCP ADU bytes 2..3", "width_bits": 16, "access": "Constant",                "scope": "Modbus TCP only", "reset_value": "0x0000", "description": "0 = MODBUS protocol."},
            {"name": "MBAP_LENGTH",          "long_name": "MBAP Length",                  "offset": "TCP ADU bytes 4..5", "width_bits": 16, "access": "Read",                    "scope": "Modbus TCP only", "description": "= 1 (Unit ID) + len(PDU)."},
            {"name": "MBAP_UNIT_ID",         "long_name": "MBAP Unit Identifier",         "offset": "TCP ADU byte 6",     "width_bits": 8,  "access": "Read",                    "scope": "Modbus TCP only", "description": "Server address on sub-network behind a gateway; 0xFF/0x00 when TCP endpoint is the server."},
            {"name": "RTU_ADDRESS",          "long_name": "Server Address (RTU/ASCII)",   "offset": "Serial ADU byte 0",  "width_bits": 8,  "access": "Read",                    "scope": "Modbus RTU/ASCII only", "description": "0 = broadcast; 1..247 individual; 248..255 reserved."},
            {"name": "FUNCTION_CODE",        "long_name": "MODBUS Function Code",         "offset": "PDU byte 0",         "width_bits": 8,  "access": "Read",                    "scope": "all transports", "description": "1..255 (0 invalid); 128..255 = exception."},
            {"name": "EXCEPTION_CODE",       "long_name": "Exception Code",                "offset": "Exception PDU byte 1", "width_bits": 8, "access": "Read",             "scope": "all transports", "description": "1=Illegal Function, 2=Illegal Data Address, 3=Illegal Data Value, 4=Server Failure, 5=Acknowledge, 6=Busy, 8=Memory Parity Error, 0x0A=Gateway Path Unavailable, 0x0B=Gateway Target Failed."},
            {"name": "RTU_CRC",              "long_name": "Modbus RTU CRC-16",            "offset": "Serial ADU last 2 bytes", "width_bits": 16, "access": "Read",             "scope": "Modbus RTU only", "description": "CRC-16-Modbus, polynomial 0xA001 reflected, init 0xFFFF, low byte first on wire."},
            {"name": "ASCII_LRC",            "long_name": "Modbus ASCII LRC",             "offset": "Serial ADU before CR LF", "width_bits": 8, "access": "Read",              "scope": "Modbus ASCII only", "description": "Longitudinal Redundancy Check, 2 ASCII-hex characters."},
            {"name": "RUN_INDICATOR_STATUS", "long_name": "Server Run Indicator Status (FC 0x11)", "offset": "FC 0x11 response", "width_bits": 8, "access": "Read", "scope": "Serial line only", "description": "0x00 = OFF; 0xFF = ON."},
            {"name": "MEI_TYPE",             "long_name": "Encapsulated Interface MEI Type", "offset": "FC 0x2B byte after FC", "width_bits": 8, "access": "Read", "scope": "all transports", "description": "0x0D = CANopen General Reference; 0x0E = Read Device Identification."},
        ]
        if _empty(d.get("registers")):
            d["registers"] = regs
        d.setdefault("device_id_objects_mei14", [
            {"object_id": 0,    "name": "VendorName",                            "mandatory": True,  "category": "Basic"},
            {"object_id": 1,    "name": "ProductCode",                            "mandatory": True,  "category": "Basic"},
            {"object_id": 2,    "name": "MajorMinorRevision",                     "mandatory": True,  "category": "Basic"},
            {"object_id": 3,    "name": "VendorUrl",                              "mandatory": False, "category": "Regular"},
            {"object_id": 4,    "name": "ProductName",                            "mandatory": False, "category": "Regular"},
            {"object_id": 5,    "name": "ModelName",                              "mandatory": False, "category": "Regular"},
            {"object_id": 6,    "name": "UserApplicationName",                    "mandatory": False, "category": "Regular"},
            {"object_id": "0x07..0x7F", "name": "Reserved",                       "mandatory": False, "category": "Reserved"},
            {"object_id": "0x80..0xFF", "name": "Vendor-defined Extended objects","mandatory": False, "category": "Extended"},
        ])
        d.setdefault("diagnostic_counters", [
            "Bus Message Count",
            "Bus Communication Error Count",
            "Bus Exception Error Count",
            "Server Message Count",
            "Server No Response Count",
            "Server NAK Count",
            "Server Busy Count",
            "Bus Character Overrun Count",
            "Diagnostic Register",
            "Comm Event Counter",
            "Comm Event Log buffer (≤ 64 events)",
        ])
        d["notes"] = (
            "MODBUS is a protocol, not a chip; the 'register map' describes the canonical "
            "fields that appear on the wire (in the ADU/PDU framing) and the four logical "
            "data-table address spaces the server exposes to the client.")
        _write(p, d)

    # ---------------- L5 ADI signaling (n/a at protocol layer) ----------------
    p = gd / "L5_ADI_SPEC.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("analog_digital_interface_present", False)
        d["signaling_summary"] = (
            "Not applicable at the application-protocol level. MODBUS is OSI layer 7; all "
            "wire-level signaling (voltage levels, line drivers, differential pairs, optical "
            "interfaces, Ethernet PHY) is delegated to the chosen transport layer — EIA/TIA-232, "
            "EIA/TIA-422, EIA/TIA-485, fiber, radio, MODBUS PLUS, or TCP/IP-over-Ethernet. The "
            "MODBUS spec only constrains the byte sequence on the wire and the framing markers "
            "(3.5-char silence for RTU, ':' + CR LF for ASCII, MBAP Length for TCP).")
        _write(p, d)

    # ---------------- L6 control logic / FSM ----------------
    p = gd / "L6_CONTROL_LOGIC.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("fsm_states_server_transaction", [
            {"name": "WAIT_FOR_MB_INDICATION", "description": "Idle. Server waits for an incoming MODBUS request ADU."},
            {"name": "VALIDATE_FUNCTION_CODE", "description": "Check FC is supported. If not → ExceptionCode 0x01."},
            {"name": "VALIDATE_DATA_ADDRESS",  "description": "Check Address + Quantity in range. If not → ExceptionCode 0x02."},
            {"name": "VALIDATE_DATA_VALUE",    "description": "Check quantity/byte-count/value within per-FC limits. If not → ExceptionCode 0x03."},
            {"name": "EXECUTE_MB_FUNCTION",    "description": "Perform the action. On unrecoverable failure → ExceptionCode 0x04/0x05/0x06/0x08."},
            {"name": "SEND_MODBUS_RESPONSE",   "description": "Compose normal response PDU and transmit."},
            {"name": "SEND_MODBUS_EXCEPTION_RESPONSE", "description": "Compose exception PDU (FC | 0x80, Exception Code) and transmit."},
        ])
        d.setdefault("fsm_states_client_transaction", [
            {"name": "BUILD_REQUEST",     "description": "Client constructs PDU per FC-specific layout."},
            {"name": "TRANSMIT_REQUEST",  "description": "Client sends ADU on the chosen transport."},
            {"name": "WAIT_FOR_RESPONSE", "description": "Client starts request-timeout timer."},
            {"name": "RECEIVE_RESPONSE",  "description": "Wait for end-of-frame; validate CRC/LRC implicitly."},
            {"name": "CLASSIFY_RESPONSE", "description": "Normal (MSB=0) or exception (MSB=1)."},
            {"name": "TIMEOUT",           "description": "No response within timeout → report to application."},
        ])
        d.setdefault("fsm_hints", {
            "validation_order":   "Function code → Data address → Data value → Execute (Figure 9).",
            "broadcast_handling": "Address 0 = broadcast; server processes but does NOT respond.",
            "abort_conditions":   "Communication error → silent discard; no exception response.",
            "no_response_class":  "Exception 0x05 ACKNOWLEDGE prevents client timeout for long programming commands.",
        })
        d.setdefault("anti_deadlock_rule",
            "Strict request/reply: only the client initiates; the server replies (or stays silent "
            "on broadcast / communication error). On Modbus TCP, MBAP.Transaction_ID lets the "
            "client correlate concurrent responses.")
        d.setdefault("exit_from_reset_or_power_up",
            "After server power-up, all communication counters and the diagnostic register start "
            "cleared; data tables hold their power-on defaults. Server is ready to accept the "
            "first MODBUS request without further client-side initialization.")
        d.setdefault("default_state_recommendation", {
            "serial_line_idle":        "Both directions idle (UART idle HIGH / TXD = mark).",
            "rtu_end_of_frame_marker": "≥ 3.5 character-time silent line.",
            "ascii_start_of_frame":    "':' (0x3A).",
            "tcp_socket_initial":      "Client opens TCP connection to server's port 502.",
        })
        d.setdefault("exception_response_logic", {
            "trigger":      "Any failed validation gate (function / address / value / execute).",
            "pdu_layout":   "(FC | 0x80, 1 B) + (Exception Code, 1 B). Total exception PDU = 2 bytes.",
            "client_action":"Inspect response.byte[0] MSB. If 1, treat as exception.",
        })
        d.setdefault("diagnostics_listen_only_mode", {
            "trigger":  "FC 0x08 sub-function 0x0004 Force Listen Only Mode.",
            "behavior": "Server stops responding to all requests until sub-function 0x0001 Restart Communications Option.",
            "rationale":"Allows offline troubleshooting without affecting other devices on a multi-drop bus.",
        })
        d.setdefault("interrupt_priority_order", [
            "Not applicable at the protocol layer.",
        ])
        _write(p, d)

    # ---------------- L7 test/debug ----------------
    p = gd / "L7_TEST_DEBUG.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("test_debug_architecture_present", True)
        d.setdefault("test_debug_features", [
            "Read Exception Status (FC 0x07, serial only) — 8 device-specific exception-status bits in 1 byte.",
            "Diagnostics (FC 0x08, serial only) — 14 sub-functions covering loopback, restart, diagnostic-register read, Force Listen Only Mode, Clear Counters, and counter readouts.",
            "Get Comm Event Counter (FC 0x0B, serial only) — Status + Event Count.",
            "Get Comm Event Log (FC 0x0C, serial only) — Status + Event Count + Message Count + ≤ 64 event bytes.",
            "Report Server ID (FC 0x11, serial only) — Server ID + Run Indicator Status (0xFF / 0x00) + device-specific data.",
            "Exception responses (FC | 0x80 + Exception Code) — built-in mechanism for the server to tell the client exactly which validation gate failed.",
        ])
        d.setdefault("spec_provided_observability", [
            {"name": "Function Code MSB of response", "purpose": "If set, response is an exception."},
            {"name": "Exception Code 0x01 ILLEGAL FUNCTION",                  "purpose": "FC not implemented."},
            {"name": "Exception Code 0x02 ILLEGAL DATA ADDRESS",              "purpose": "Address + quantity outside server's data space."},
            {"name": "Exception Code 0x03 ILLEGAL DATA VALUE",                "purpose": "Structural value outside per-function limit."},
            {"name": "Exception Code 0x04 SERVER DEVICE FAILURE",             "purpose": "Internal unrecoverable error."},
            {"name": "Exception Code 0x05 ACKNOWLEDGE",                       "purpose": "Long-running command accepted."},
            {"name": "Exception Code 0x06 SERVER DEVICE BUSY",                "purpose": "Server busy with another long command."},
            {"name": "Exception Code 0x08 MEMORY PARITY ERROR",               "purpose": "FC 20/21 reference-type-6 area consistency check failed."},
            {"name": "Exception Code 0x0A GATEWAY PATH UNAVAILABLE",          "purpose": "Gateway misconfigured / overloaded."},
            {"name": "Exception Code 0x0B GATEWAY TARGET FAILED TO RESPOND",  "purpose": "Target sub-device didn't reply."},
            {"name": "Bus Message Count (FC 0x08 sub 11)",                    "purpose": "All messages on bus."},
            {"name": "Bus Communication Error Count (FC 0x08 sub 12)",        "purpose": "CRC/LRC/parity/framing errors."},
            {"name": "Bus Exception Error Count (FC 0x08 sub 13)",            "purpose": "Exception responses sent."},
            {"name": "Comm Event Counter (FC 0x0B)",                          "purpose": "Successful-message event counter."},
            {"name": "Run Indicator Status (FC 0x11)",                        "purpose": "0xFF = server running; 0x00 = stopped."},
        ])
        d.setdefault("interrupt_sources", [
            {"flag": "New ADU received on serial RX", "trigger": "End-of-frame detected (T3.5 silence on RTU, CR LF on ASCII)."},
            {"flag": "TCP segment received on port 502", "trigger": "Length-prefixed MBAP frame fully received."},
            {"flag": "T3.5 silence timer expired",       "trigger": "RTU end-of-frame trigger."},
        ])
        d.setdefault("interrupt_request",
            "Not specified by MODBUS itself. Implementation-defined: serial uses UART RX interrupt "
            "+ one-shot timer for T3.5; TCP relies on socket-recv callbacks.")
        d.setdefault("notes",
            "MODBUS provides rich built-in diagnostic visibility through FCs 7, 8, 11, 12, 17 — "
            "collectively the Diagnostic / Communications Event Log / Server ID subsystem. "
            "These run only over serial-line transports; TCP diagnostics are vendor-specific.")
        _write(p, d)

    # ---------------- L8 RTL constants ----------------
    p = gd / "L8_RTL_CONSTANTS.json"
    if p.is_file():
        d = _read(p)
        wp = d.setdefault("width_parameters", {})
        if isinstance(wp, dict):
            for k, v in {
                "FUNCTION_CODE_WIDTH_bits":          8,
                "EXCEPTION_CODE_WIDTH_bits":         8,
                "ADDRESS_WIDTH_bits":                16,
                "RTU_ADU_ADDRESS_WIDTH_bits":        8,
                "QUANTITY_WIDTH_bits":               16,
                "BYTE_COUNT_WIDTH_bits":             8,
                "COIL_VALUE_WIDTH_bits":             1,
                "DISCRETE_INPUT_VALUE_WIDTH_bits":   1,
                "REGISTER_VALUE_WIDTH_bits":         16,
                "PDU_MAX_SIZE_bytes":                253,
                "PDU_DATA_MAX_SIZE_bytes":           252,
                "RTU_ADU_MAX_SIZE_bytes":            256,
                "ASCII_ADU_MAX_SIZE_chars":          513,
                "TCP_ADU_MAX_SIZE_bytes":            260,
                "MBAP_HEADER_SIZE_bytes":            7,
                "MBAP_TRANSACTION_ID_WIDTH_bits":    16,
                "MBAP_PROTOCOL_ID_WIDTH_bits":       16,
                "MBAP_LENGTH_WIDTH_bits":            16,
                "MBAP_UNIT_ID_WIDTH_bits":           8,
                "RTU_CRC_WIDTH_bits":                16,
                "ASCII_LRC_WIDTH_bits":              8,
                "DATA_TABLE_INDEX_RANGE":            65536,
                "DATA_TABLES_PRIMARY":               4,
                "MEI_TYPE_WIDTH_bits":               8,
            }.items():
                wp.setdefault(k, v)
        d.setdefault("voltage_levels", {
            "VDD_nominal": "Not specified — MODBUS is a protocol; voltage levels fixed by the chosen physical layer.",
        })
        d.setdefault("clock_constants", {
            "T_3p5_chars_RTU":  "End-of-frame Modbus RTU = ≥ 3.5 character times of silent line. At 9600 baud, ≈ 4.0 ms. Above 19200 baud, fixed minimum 1.75 ms.",
            "T_1p5_chars_RTU":  "Inter-character timeout = 1.5 character times.",
            "tcp_baseline_speed": "MODBUS TCP runs over standard TCP/IP; no additional protocol-level clocking constants.",
            "tcp_server_port":   502,
        })
        d.setdefault("key_constants_for_RTL_authoring", {
            "function_code_byte_size":               1,
            "function_code_invalid":                 0,
            "function_code_exception_mask":          "0x80",
            "exception_function_code_offset":        128,
            "pdu_max_bytes":                         253,
            "pdu_data_max_bytes":                    252,
            "rtu_adu_max_bytes":                     256,
            "tcp_adu_max_bytes":                     260,
            "mbap_header_size_bytes":                7,
            "mbap_protocol_id_value":                0,
            "tcp_default_port":                      502,
            "broadcast_address":                     0,
            "rtu_address_individual_range":          [1, 247],
            "rtu_address_reserved_range":            [248, 255],
            "quantity_max_FC01":                     2000,
            "quantity_max_FC02":                     2000,
            "quantity_max_FC03":                     125,
            "quantity_max_FC04":                     125,
            "quantity_max_FC0F":                     1968,
            "quantity_max_FC10":                     123,
            "quantity_max_FC17_read":                125,
            "quantity_max_FC17_write":               121,
            "quantity_max_FC18_fifo":                31,
            "fifo_byte_count_max":                   64,
            "write_single_coil_on_value":            "0xFF00",
            "write_single_coil_off_value":           "0x0000",
            "byte_order_on_wire":                    "big-endian (MSB first)",
            "rtu_crc_polynomial_reflected":          "0xA001",
            "rtu_crc_polynomial_normal":             "0x8005",
            "rtu_crc_initial_value":                 "0xFFFF",
            "rtu_crc_low_byte_first_on_wire":        True,
            "ascii_lrc_initial_value":               0,
            "ascii_start_of_frame_char":             "0x3A (':')",
            "ascii_end_of_frame_chars":              "0x0D 0x0A (CR LF)",
            "rtu_end_of_frame_silence_chars":        3.5,
            "rtu_intra_frame_max_silence_chars":     1.5,
            "data_tables_count":                     4,
            "data_table_items_per_table_max":        65536,
            "address_zero_based_in_pdu":             True,
            "address_one_based_in_user_model":       True,
            "mei_type_canopen":                      "0x0D",
            "mei_type_read_device_identification":   "0x0E",
        })
        d.setdefault("function_code_table", {
            "0x01": "Read Coils",                       "0x02": "Read Discrete Inputs",
            "0x03": "Read Holding Registers",           "0x04": "Read Input Registers",
            "0x05": "Write Single Coil",                "0x06": "Write Single Register",
            "0x07": "Read Exception Status (serial)",   "0x08": "Diagnostics (serial)",
            "0x0B": "Get Comm Event Counter (serial)",  "0x0C": "Get Comm Event Log (serial)",
            "0x0F": "Write Multiple Coils",             "0x10": "Write Multiple Registers",
            "0x11": "Report Server ID (serial)",        "0x14": "Read File Record",
            "0x15": "Write File Record",                "0x16": "Mask Write Register",
            "0x17": "Read/Write Multiple Registers",    "0x18": "Read FIFO Queue",
            "0x2B": "Encapsulated Interface Transport",
        })
        d.setdefault("exception_code_table", {
            "0x01": "ILLEGAL FUNCTION",
            "0x02": "ILLEGAL DATA ADDRESS",
            "0x03": "ILLEGAL DATA VALUE",
            "0x04": "SERVER DEVICE FAILURE",
            "0x05": "ACKNOWLEDGE",
            "0x06": "SERVER DEVICE BUSY",
            "0x08": "MEMORY PARITY ERROR",
            "0x0A": "GATEWAY PATH UNAVAILABLE",
            "0x0B": "GATEWAY TARGET DEVICE FAILED TO RESPOND",
        })
        d.setdefault("default_signal_values_after_reset", {
            "Bus_Message_Count":              0,
            "Bus_Communication_Error_Count":  0,
            "Bus_Exception_Error_Count":      0,
            "Server_Message_Count":           0,
            "Server_No_Response_Count":       0,
            "Server_NAK_Count":               0,
            "Server_Busy_Count":              0,
            "Bus_Character_Overrun_Count":    0,
            "Diagnostic_Register":            "implementation-defined",
            "Comm_Event_Counter":             0,
            "Comm_Event_Log":                 "empty",
        })
        _write(p, d)

    # ---------------- L8 timing waveform ----------------
    p = gd / "L8_TIMING_WAVEFORM.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("rtu_frame_waveform", {
            "frame_layout":  "Address (1 B) | Function Code (1 B) | Data (0..252 B) | CRC-Lo (1 B) | CRC-Hi (1 B) — total ≤ 256 B.",
            "start_of_frame": "First bit of the first byte after ≥ T3.5 silent line.",
            "byte_transmission": "1 start + 8 data LSB-first + parity (even default) + 1 stop bit (or 2 stop bits if no parity).",
            "inter_character_gap_intra_frame": "Up to T1.5 character times allowed between bytes of the same frame.",
            "end_of_frame_silence": "≥ T3.5 character times of silent line.",
            "T_3p5_at_9600":   "≈ 4.0 ms (11 bit-times × 3.5 chars / 9600 baud)",
            "T_3p5_at_19200":  "≈ 2.0 ms",
            "T_3p5_above_19200": "Fixed 1.75 ms minimum",
            "wire_polarity":   "Idle line = mark (HIGH); start bit = space (LOW).",
        })
        d.setdefault("ascii_frame_waveform", {
            "start_of_frame":  "':' (0x3A) — single ASCII character. Receiver finds frame start by scanning for ':' on the line.",
            "address":         "2 ASCII-hex characters (1 binary byte).",
            "function_code":   "2 ASCII-hex characters.",
            "data":            "2N ASCII-hex characters.",
            "lrc":             "2 ASCII-hex characters.",
            "end_of_frame":    "CR (0x0D) + LF (0x0A).",
            "ascii_chars_only":"0-9, A-F between SOF and EOF.",
        })
        d.setdefault("tcp_frame_waveform", {
            "mbap_header":  "Transaction ID (2 B) | Protocol ID (2 B = 0x0000) | Length (2 B) | Unit ID (1 B) — 7 B.",
            "pdu_payload":  "Function Code (1 B) + Data (0..252 B).",
            "length_field": "MBAP.Length = 1 + len(PDU).",
            "tcp_port":     502,
            "no_extra_crc": "MODBUS TCP has no per-PDU CRC; integrity via Ethernet CRC-32 + TCP checksum.",
            "concurrent_transactions": "Client may have multiple outstanding requests via Transaction ID.",
        })
        d.setdefault("request_response_timing", {
            "client_request_timeout":  "Implementation-defined; typical 100..500 ms for RTU at 9600 baud, 1..5 s for TCP.",
            "server_processing_delay": "Implementation-defined; long-running commands return 0x05 ACKNOWLEDGE.",
            "broadcast_no_response":   "Broadcast frames elicit no response; client waits T_broadcast_interval.",
            "comm_error_no_response":  "Parity/framing/CRC/LRC error → no response; client times out.",
        })
        d.setdefault("crc_lrc_computation_timing", {
            "rtu_crc_throughput":   "1 byte / 8 cycles bit-serial, or 1 byte / 1 cycle table-based.",
            "ascii_lrc_throughput": "Two's-complement of the byte-wise sum of Address + Function + Data; trivially computed as a running 8-bit accumulator.",
        })
        d.setdefault("absolute_max_ratings", {
            "n_a_at_protocol_layer": "MODBUS is OSI level 7; absolute maxima belong to the chosen physical layer.",
        })
        _write(p, d)

    # ---------------- L9 integration spec ----------------
    p = gd / "L9_INTEGRATION_SPEC.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("module_role",
            "MODBUS application-layer server (and/or client) module — implements the function-code "
            "processor + ADU framer/parser for one or more of the three published transports "
            "(RTU, ASCII, TCP). Exposes the four data tables plus diagnostic counters and an "
            "optional Encapsulated Interface (FC 0x2B) handler.")
        _ptm.apply(d, "modbus_server_top")
        d.setdefault("integration_overview", {
            "host_side":         "Two memory-mapped regions: (a) configuration/control/status registers, (b) the four MODBUS data tables.",
            "wire_side_rtu":     "UART TX/RX plus optional RTS for RS-485 transceiver direction control.",
            "wire_side_ascii":   "UART TX/RX; LRC/CR LF detection internal.",
            "wire_side_tcp":     "TCP socket on port 502 — typically delegated to an external TCP/IP stack.",
            "clock_source":      "Implementation-defined.",
            "reset_source":      "Implementation-defined; synchronous reset that clears counters and re-initializes framer.",
            "interrupt_routing": "End-of-frame on UART RX, TCP segment received, response-transmit-complete, framing-error detected.",
        })
        d.setdefault("interface_categories", [
            "Host CPU bus (APB / AHB / AXI / Avalon / Wishbone) for register/data-table access",
            "Serial UART pair (TX, RX, optional RTS for RS-485 direction)",
            "TCP socket (delegated to a TCP/IP stack)",
            "Diagnostic counter readout interface",
            "Optional File Record store (FC 20 / 21)",
            "Optional FIFO queue (FC 24)",
        ])
        d.setdefault("interconnect_topologies_supported", [
            "Modbus RTU multi-drop bus on EIA/TIA-485 — 1 client + up to 247 servers + broadcast.",
            "Modbus RTU point-to-point on EIA/TIA-232.",
            "Modbus ASCII multi-drop / point-to-point.",
            "Modbus TCP — switched Ethernet client/server on port 502; pipelined transactions per connection.",
            "Modbus gateway — bridges TCP front-end to one or more serial sub-networks.",
            "Modbus PLUS (legacy HDLC token-passing).",
        ])
        d.setdefault("default_signal_values_when_omitted",
            "Diagnostic counters and Comm Event Counter/Log reset to zero on power-up. Run Indicator "
            "Status defaults to 0xFF (running) once the server's main loop is dispatched.")
        d.setdefault("soc_dependent_items", [
            "Transport selection (RTU / ASCII / TCP / multi-transport)",
            "Server-address (RTU) / MBAP_Unit_ID (TCP) configuration",
            "Baud rate, parity, stop-bit configuration for serial transports",
            "Sizing of the four data tables and their backing-RAM allocation",
            "File-record subsystem presence and flash/EEPROM mapping",
            "FIFO queue presence and depth",
            "Diagnostic counter persistence across reset",
            "Sub-function set supported under FC 0x08",
            "Encapsulated Interface support (FC 0x2B): CANopen and/or Read Device Identification",
            "Gateway routing table (if implementing a gateway)",
            "Listen-Only Mode escape mechanism",
        ])
        d.setdefault("low_power_modes", {
            "n_a_at_protocol_layer": "MODBUS does not define low-power states.",
        })
        d.setdefault("compatibility_notes", [
            "All three transports carry the same PDU; an application is portable across RTU/ASCII/TCP modulo transport-only function codes (FC 7, 8, 11, 12, 17 are serial-only).",
            "MBAP.Protocol_ID is always 0x0000 for MODBUS; non-zero reserved for future use.",
            "FC 43 / MEI 13 (CANopen) requires CiA documentation for the encapsulated payload; FC 43 / MEI 14 fully defined in spec 6.21.",
            "Reserved function codes (Annex A) shall not be implemented by interoperable devices.",
            "Some vendors encode 32-bit float/integer across two consecutive holding registers; word order is vendor-specific.",
        ])
        _write(p, d)

    # ---------------- L10 test cases (overwrite SPI-universal generic) ----------------
    # Doctrine: serial-peripheral universal synth (SPI) writes a generic
    # test_cases_present + SPI-flavored derived_compliance_test_categories
    # before the Modbus structural detector fires. Modbus is a protocol with
    # its own per-function-code state diagrams and validation gates, so
    # direct-assign the protocol-accurate values.
    p = gd / "L10_TEST_CASES.json"
    if p.is_file():
        d = _read(p)
        d["test_cases_present"] = (
            "partial - the spec provides per-function-code state diagrams (Figures 11..14 etc.), "
            "normal/error response tables, and example request/response byte traces, but no formal "
            "compliance testbench. The cases below are derived from the validation gates in Figure 9 "
            "(Define MODBUS Transaction state diagram) plus the per-function-code state diagrams "
            "in Section 6.")
        d["derived_compliance_test_categories"] = [
            "PDU minimum case — Function Code only (e.g. FC 0x07 Read Exception Status with no data).",
            "PDU maximum size — request whose Data portion fills 252 bytes (FC 0x10 Write Multiple Registers with quantity 123 ≈ 246 data bytes).",
            "RTU ADU maximum size — 256 bytes total including 1-byte address + 253-byte PDU + 2-byte CRC.",
            "TCP ADU maximum size — 260 bytes total including 7-byte MBAP + 253-byte PDU.",
            "Big-endian byte order — write a 16-bit register to 0x1234 and verify the first byte on the wire is 0x12.",
            "PDU vs user address offset — FC 0x03 reading user-register-1 must use Starting Address = 0x0000 in the PDU.",
            "FC 0x01 Read Coils — request quantity at boundary (1 and 2000); verify byte_count = ceil(quantity/8); verify LSB of first byte = first coil.",
            "FC 0x02 Read Discrete Inputs — same shape as FC 1; ensure separate data-table backing.",
            "FC 0x03 Read Holding Registers — quantity at boundary (1 and 125); verify byte_count = 2*quantity, big-endian per register.",
            "FC 0x04 Read Input Registers — same shape as FC 3.",
            "FC 0x05 Write Single Coil — Output Value 0xFF00 (ON) and 0x0000 (OFF) accepted; any other value → exception 0x03 ILLEGAL DATA VALUE.",
            "FC 0x06 Write Single Register — register value 0x0000..0xFFFF; response echoes request.",
            "FC 0x0F Write Multiple Coils — quantity boundary (1 and 1968); byte_count = ceil(quantity/8); response echoes Starting Address + Quantity.",
            "FC 0x10 Write Multiple Registers — quantity boundary (1 and 123); byte_count = 2*quantity; response echoes Starting Address + Quantity.",
            "FC 0x16 Mask Write Register — verify Result = (Current AND AND_Mask) OR (OR_Mask AND (NOT AND_Mask)). Example from spec: Current 0x0012, AND 0x00F2, OR 0x0025 → Result 0x0017.",
            "FC 0x17 Read/Write Multiple Registers — atomic combined transaction; read up to 125 + write up to 121 in single PDU.",
            "FC 0x18 Read FIFO Queue — fifo_count ≤ 31; byte_count ≤ 64.",
            "FC 0x14 Read File Record — multi-sub-request PDU; each sub-request specifies File Number / Record Number / Record Length.",
            "FC 0x15 Write File Record — multi-sub-request PDU; response echoes the request.",
            "FC 0x07 Read Exception Status — single-byte response; LSB = lowest-numbered output.",
            "FC 0x08 Diagnostics sub 0 Return Query Data — echoes the data field.",
            "FC 0x08 Diagnostics sub 0x0004 Force Listen Only Mode — server enters silent state; can only be exited via sub 0x0001 Restart Communications Option.",
            "FC 0x0B Get Comm Event Counter — Event Count increments only on successful (non-exception) responses.",
            "FC 0x0C Get Comm Event Log — events buffer length ≤ 64; Byte Count = events count + 6.",
            "FC 0x11 Report Server ID — Run Indicator Status 0xFF = ON, 0x00 = OFF.",
            "FC 0x2B Encapsulated Interface — MEI Type 14 Read Device Identification with Read Device ID code 01 (Basic), 02 (Regular), 03 (Extended), 04 (One specific identification object).",
            "Exception 0x01 ILLEGAL FUNCTION — send an undefined function code (e.g. FC 0x0A); expect (FC | 0x80) + 0x01.",
            "Exception 0x02 ILLEGAL DATA ADDRESS — FC 0x03 with Starting Address = 0x0030 + Quantity = 0x0005 on a server that has only 99 registers (0..98); expect (0x83, 0x02).",
            "Exception 0x03 ILLEGAL DATA VALUE — FC 0x01 with Quantity = 0x07D1 (= 2001) or FC 0x05 with Output Value 0x1234; expect (0x81 / 0x85, 0x03).",
            "Exception 0x04 SERVER DEVICE FAILURE — simulate an internal failure during execution.",
            "Exception 0x05 ACKNOWLEDGE — long-running programming command; client must not time out.",
            "Exception 0x06 SERVER DEVICE BUSY — second long-running command issued; expect 0x06 then retry.",
            "Exception 0x08 MEMORY PARITY ERROR — corrupt the reference-type-6 file area; FC 0x14 / 0x15 should return 0x94 / 0x95 + 0x08.",
            "Exception 0x0A / 0x0B — gateway scenarios: misconfigured sub-network and unresponsive target device.",
            "RTU broadcast — Address 0 + FC 0x06 or 0x10; verify server processes the request but emits no response.",
            "RTU CRC error — flip one bit of the request; verify the server emits no response and the Bus Communication Error Count increments.",
            "ASCII LRC error — flip one ASCII-hex character; verify silent discard + counter increment.",
            "ASCII inter-character timing — long pauses inside a frame are tolerated; only ':' starts a new frame, only CR LF ends one.",
            "TCP Transaction ID — issue two concurrent requests with different Transaction IDs; verify responses carry the matching IDs.",
            "TCP malformed Length — MBAP.Length != 1 + len(PDU); verify connection-level error handling.",
            "TCP Protocol ID != 0 — verify rejection.",
        ]
        _write(p, d)

    # ---------------- L11 OTP ----------------
    p = gd / "L11_OTP_CONTENT.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("otp_present", False)
        d["notes"] = (
            "MODBUS is a protocol specification, not a silicon part — it has no OTP/fuse/"
            "configuration ROM at the protocol level. Implementing devices may persist (a) the "
            "server's RTU address or MBAP Unit ID, (b) the four data tables' power-on defaults, "
            "(c) Read-Device-Identification objects (Vendor Name, Product Code, Revision, etc.) "
            "in vendor-defined OTP/EEPROM/flash. All implementation-specific.")
        _write(p, d)

    # ---------------- L12 behavioral sequences ----------------
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("initialization_sequence_server_rtu", [
            "1. Power up / reset; load server address (1..247) and serial parameters.",
            "2. Clear diagnostic counters; reset Comm Event Counter and Log.",
            "3. Initialize four data tables to application-defined defaults.",
            "4. Enter WAIT_FOR_MB_INDICATION; wait for T3.5 silence + start char.",
        ])
        d.setdefault("initialization_sequence_server_tcp", [
            "1. Power up; open TCP server socket on port 502.",
            "2. Initialize data tables and clear comm-event counter/log.",
            "3. Accept incoming TCP connections; for each connection enter MBAP frame-receive loop.",
        ])
        d.setdefault("typical_request_sequence_client", [
            "1. Application calls e.g. modbus_read_holding_registers(server, address, quantity).",
            "2. Client builds PDU = FC + Starting Address + Quantity.",
            "3. Prepend Address (RTU/ASCII) or MBAP (TCP); append CRC/LRC.",
            "4. Transmit ADU.",
            "5. Start request timeout timer.",
            "6. Wait for response.",
            "7. Validate CRC/LRC.",
            "8. If response.byte[0] == request.FC → decode normal response.",
            "9. If response.byte[0] == request.FC | 0x80 → decode exception code.",
            "10. If timer fires → raise timeout to application.",
        ])
        d.setdefault("typical_response_sequence_server", [
            "1. End-of-frame detected on RX.",
            "2. Validate transport framing (CRC/LRC); on error: silent discard, increment Bus Communication Error Count.",
            "3. On serial: validate Address. Address 0 = broadcast: process but no response.",
            "4. Validate Function Code. Unsupported → (FC | 0x80, 0x01).",
            "5. Validate Data Address. Out-of-range → (FC | 0x80, 0x02).",
            "6. Validate Data Value. Out-of-range → (FC | 0x80, 0x03).",
            "7. Execute the action. Failure → (FC | 0x80, 0x04).",
            "8. Build normal response PDU.",
            "9. Prepend Address/MBAP; append CRC/LRC; transmit.",
            "10. Increment Comm Event Counter; push event into Comm Event Log.",
        ])
        d.setdefault("broadcast_sequence_rtu", [
            "1. Client builds ADU with Address = 0.",
            "2. FC must be a write that can be safely applied unconditionally (0x05, 0x06, 0x0F, 0x10, 0x16).",
            "3. Client transmits.",
            "4. Server(s) receive, validate, apply — no response.",
            "5. Client waits T_broadcast_interval before next frame.",
        ])
        d.setdefault("exception_response_sequence", [
            "1. Server detects validation failure.",
            "2. Build Exception PDU: byte0 = FC | 0x80; byte1 = Exception Code.",
            "3. Transmit (2-byte PDU).",
            "4. Increment Bus Exception Error Count.",
            "5. Client sees MSB=1, decodes exception code.",
        ])
        d.setdefault("diagnostics_listen_only_sequence", [
            "1. Client sends FC 0x08 sub 0x0004 (Force Listen Only Mode).",
            "2. Server enters Listen Only Mode.",
            "3. Server does not respond; only Bus Message Count increments.",
            "4. Client sends FC 0x08 sub 0x0001 to exit Listen Only Mode.",
        ])
        d.setdefault("read_device_identification_sequence_FC2B_MEI14", [
            "1. Client sends PDU = 0x2B + 0x0E + Read Device ID code (01..04) + Object ID.",
            "2. Server replies with Read Device ID code + Conformity Level + More Follows + Next Object ID + Number Of Objects + (Object ID + Length + Value) × N.",
            "3. If More Follows = 0xFF, client issues another request with Next Object ID.",
            "4. Mandatory Basic objects: 0x00 VendorName, 0x01 ProductCode, 0x02 MajorMinorRevision.",
        ])
        d.setdefault("encapsulated_interface_canopen_sequence_FC2B_MEI13", [
            "1. Client sends PDU = 0x2B + 0x0D + CANopen General Reference payload.",
            "2. Server replies with PDU = 0x2B + 0x0D + CANopen response payload.",
            "3. CANopen sub-protocol is referenced via CiA documentation.",
        ])
        d.setdefault("tcp_transaction_pipelining_sequence", [
            "1. Client opens TCP connection to server's port 502.",
            "2. Client sends Request_1 (Transaction_ID = 1), Request_2 (Transaction_ID = 2) without waiting.",
            "3. Server processes in any order; replies with matching Transaction_IDs.",
            "4. Client matches each response to its request via Transaction_ID.",
        ])
        _write(p, d)

    # ---------------- L13 lab calibration ----------------
    p = gd / "L13_LAB_CALIBRATION.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("lab_calibration_present", False)
        d["notes"] = (
            "MODBUS is an application-layer messaging protocol — it has no analog reference, "
            "no oscillator trim, and no PVT-dependent calibration loop. Any implementation-side "
            "calibration (e.g. UART baud-rate trim for RTU/ASCII, Ethernet PHY auto-negotiation "
            "for TCP) belongs to the underlying transport hardware.")
        _write(p, d)

    # ---------------- L14 protocol versioning ----------------
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("spec_version", "Modbus Application Protocol V1.1b3 (April 26, 2012)")
        if _empty(f.get("lineage")):
            f["lineage"] = [
                {"version": "Modbus (original)",  "year": "1979",
                 "summary": "Originally invented by Modicon for its PLC family. Defined the serial RTU and ASCII framings, the four data tables, and the core function-code set."},
                {"version": "Modbus PLUS (MB+)",  "year": "1980s",
                 "summary": "Modicon-proprietary high-speed HDLC token-passing peer-to-peer network. Deprecated in favor of Modbus TCP."},
                {"version": "Open Modbus / Modbus TCP", "year": "1999 / 2000",
                 "summary": "Schneider Electric publishes the Open Modbus Specification. Reserved TCP port 502."},
                {"version": "Modbus.org formation","year": "2002",
                 "summary": "Schneider transfers stewardship of MODBUS to Modbus.org."},
                {"version": "Modbus Application Protocol V1.1",   "year": "2002",
                 "summary": "First Modbus.org release. Added Encapsulated Interface Transport (FC 0x2B) with MEI 13 (CANopen) and 14 (Read Device Identification)."},
                {"version": "Modbus Application Protocol V1.1a",  "year": "2004",
                 "summary": "Minor errata + clarifications."},
                {"version": "Modbus Application Protocol V1.1b",  "year": "2006",
                 "summary": "Errata release; clarified Read Device Identification."},
                {"version": "Modbus Application Protocol V1.1b3", "year": "April 26, 2012",
                 "summary": "Current stable release; editorial cleanups; no new function codes."},
            ]
        f.setdefault("related_specifications", [
            {"name": "Modbus Messaging Implementation Guide V1.0a",   "description": "Modbus TCP framing (MBAP header) and TCP-specific behavior."},
            {"name": "Modbus over Serial Line Specification V1.02",   "description": "RTU and ASCII serial framing rules (T3.5, CRC-16-Modbus, LRC, ':', CR LF)."},
            {"name": "CiA CANopen General Reference",                  "description": "Encapsulated under FC 0x2B MEI Type 13; payload format defined by CAN-in-Automation."},
        ])
        if _empty(f.get("backward_compat_traps")):
            f["backward_compat_traps"] = [
                {"trap_name": "address_offset_off_by_one",
                 "user_model":   "Coil 1, Register 1 — numbered from 1.",
                 "pdu_value":    "Starting Address = 0x0000.",
                 "trap": "Putting user-facing register number directly into PDU reads one register too far. PDU_address = user_number - 1."},
                {"trap_name": "fc05_output_value_enum",
                 "valid_on":   "0xFF00",
                 "valid_off":  "0x0000",
                 "trap": "FC 0x05 rejects any other value with exception 0x03."},
                {"trap_name": "rtu_crc_byte_order",
                 "computation_order": "CRC-16-Modbus is a 16-bit value.",
                 "on_wire_order":     "Low byte first, then high byte.",
                 "trap": "Many debuggers check the wrong CRC byte order. CRC is little-endian on the wire while data is big-endian."},
                {"trap_name": "function_code_msb_overload",
                 "normal_response":    "FC byte echoes request FC.",
                 "exception_response": "FC byte = FC | 0x80.",
                 "trap": "Ignoring MSB of response FC causes mis-parsing an exception as a normal response."},
                {"trap_name": "tcp_protocol_id_nonzero",
                 "modbus": "Protocol ID = 0x0000.",
                 "trap":   "Non-zero Protocol ID is reserved for future use; non-MODBUS payloads silently invalid."},
                {"trap_name": "serial_only_function_codes",
                 "serial_only": "FC 0x07, 0x08, 0x0B, 0x0C, 0x11.",
                 "trap":         "These FCs are not supported on Modbus TCP per spec."},
                {"trap_name": "max_quantity_per_function_code",
                 "fc01_fc02":  "≤ 2000 / 0x07D0",
                 "fc03_fc04":  "≤ 125 / 0x007D",
                 "fc0f":        "≤ 1968 / 0x07B0",
                 "fc10":        "≤ 123 / 0x007B",
                 "fc17":        "read ≤ 125 + write ≤ 121",
                 "fc18":        "fifo ≤ 31 / 0x001F",
                 "trap":         "Different FCs have different maxima."},
                {"trap_name": "reserved_function_codes",
                 "reserved":   "Annex A — FC 9, 10, 13, 14, 41, 42, 90, 91, 125..127.",
                 "trap":        "Implementing them breaks future MODBUS compliance; use User-Defined ranges 65..72 or 100..110 instead."},
            ]
        f.setdefault("version_naming_history_note",
            "Modbus.org maintains the application protocol document on https://modbus.org. "
            "Version 1.1b3 is the current April-26-2012 release used by virtually all modern MODBUS "
            "implementations.")
        d["fields"] = f
        _write(p, d)

    # ---------------- L15 encoding tables ----------------
    p = gd / "L15_ENCODING_TABLES.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("public_function_code_table", {
            "header_columns": ["Category", "Sub-category", "Function Name", "FC code (dec)", "Sub-code", "FC code (hex)", "Section"],
            "rows": [
                ["Data Access", "Bit access — Physical Discrete Inputs", "Read Discrete Inputs", "02", "",      "0x02", "6.2"],
                ["Data Access", "Bit access — Internal Bits or Physical Coils", "Read Coils",     "01", "",      "0x01", "6.1"],
                ["Data Access", "Bit access — Internal Bits or Physical Coils", "Write Single Coil","05", "",     "0x05", "6.5"],
                ["Data Access", "Bit access — Internal Bits or Physical Coils", "Write Multiple Coils","15", "", "0x0F", "6.11"],
                ["Data Access", "16-bit access — Physical Input Registers",     "Read Input Register","04", "",  "0x04", "6.4"],
                ["Data Access", "16-bit access — Internal Registers / Physical Output Registers", "Read Holding Registers","03", "", "0x03", "6.3"],
                ["Data Access", "16-bit access — Internal Registers / Physical Output Registers", "Write Single Register","06","", "0x06", "6.6"],
                ["Data Access", "16-bit access — Internal Registers / Physical Output Registers", "Write Multiple Registers","16","","0x10","6.12"],
                ["Data Access", "16-bit access — Internal Registers / Physical Output Registers", "Read/Write Multiple Registers","23","", "0x17", "6.17"],
                ["Data Access", "16-bit access — Internal Registers / Physical Output Registers", "Mask Write Register","22","",   "0x16", "6.16"],
                ["Data Access", "16-bit access — Internal Registers / Physical Output Registers", "Read FIFO queue","24","",       "0x18", "6.18"],
                ["File record access", "", "Read File record",  "20", "",          "0x14", "6.14"],
                ["File record access", "", "Write File record", "21", "",          "0x15", "6.15"],
                ["Diagnostics", "", "Read Exception status",    "07", "",          "0x07", "6.7"],
                ["Diagnostics", "", "Diagnostic",                "08", "00..18, 20", "0x08", "6.8"],
                ["Diagnostics", "", "Get Comm event counter",   "11", "",          "0x0B", "6.9"],
                ["Diagnostics", "", "Get Comm event Log",       "12", "",          "0x0C", "6.10"],
                ["Diagnostics", "", "Report Server ID",          "17", "",          "0x11", "6.13"],
                ["Diagnostics", "", "Read device Identification","43", "14",        "0x2B", "6.21"],
                ["Other",        "", "Encapsulated Interface Transport","43", "13,14","0x2B", "6.19"],
                ["Other",        "", "CANopen General Reference",       "43", "13",  "0x2B", "6.20"],
            ],
        })
        f.setdefault("function_code_category_ranges", {
            "header_columns": ["Range", "Class"],
            "rows": [
                ["1..64",     "PUBLIC function codes"],
                ["65..72",    "User Defined function codes"],
                ["73..99",    "PUBLIC function codes"],
                ["100..110",  "User Defined function codes"],
                ["111..127",  "PUBLIC function codes"],
                ["128..255",  "Exception responses (FC | 0x80)"],
            ],
        })
        f.setdefault("data_model_table", {
            "header_columns": ["Primary table", "Object type", "Type of", "Comments"],
            "rows": [
                ["Discretes Input",  "Single bit",   "Read-Only",  "Provided by an I/O system."],
                ["Coils",            "Single bit",   "Read-Write", "Alterable by an application program."],
                ["Input Registers",  "16-bit word",  "Read-Only",  "Provided by an I/O system."],
                ["Holding Registers","16-bit word",  "Read-Write", "Alterable by an application program."],
            ],
        })
        f.setdefault("exception_code_table", {
            "header_columns": ["Code (hex)", "Name", "Meaning"],
            "rows": [
                ["0x01", "ILLEGAL FUNCTION",                  "Function code not implemented."],
                ["0x02", "ILLEGAL DATA ADDRESS",              "Starting Address + Quantity outside server's data space."],
                ["0x03", "ILLEGAL DATA VALUE",                "Value field outside per-function limit."],
                ["0x04", "SERVER DEVICE FAILURE",             "Unrecoverable internal error."],
                ["0x05", "ACKNOWLEDGE",                       "Long-running command accepted."],
                ["0x06", "SERVER DEVICE BUSY",                "Server busy with another long command."],
                ["0x08", "MEMORY PARITY ERROR",               "FC 20/21 file area consistency check failed."],
                ["0x0A", "GATEWAY PATH UNAVAILABLE",          "Gateway could not allocate input→output path."],
                ["0x0B", "GATEWAY TARGET DEVICE FAILED TO RESPOND", "Gateway forwarded; target unresponsive."],
            ],
        })
        f.setdefault("diagnostics_subfunction_table_FC08", {
            "header_columns": ["Sub-function (hex)", "Sub-function (dec)", "Name"],
            "rows": [
                ["0x0000", "0",  "Return Query Data"],
                ["0x0001", "1",  "Restart Communications Option"],
                ["0x0002", "2",  "Return Diagnostic Register"],
                ["0x0003", "3",  "Change ASCII Input Delimiter"],
                ["0x0004", "4",  "Force Listen Only Mode"],
                ["0x000A", "10", "Clear Counters and Diagnostic Register"],
                ["0x000B", "11", "Return Bus Message Count"],
                ["0x000C", "12", "Return Bus Communication Error Count"],
                ["0x000D", "13", "Return Bus Exception Error Count"],
                ["0x000E", "14", "Return Server Message Count"],
                ["0x000F", "15", "Return Server No Response Count"],
                ["0x0010", "16", "Return Server NAK Count"],
                ["0x0011", "17", "Return Server Busy Count"],
                ["0x0012", "18", "Return Bus Character Overrun Count"],
                ["0x0014", "20", "Clear Overrun Counter and Flag"],
            ],
        })
        f.setdefault("mbap_header_layout_table", {
            "header_columns": ["MBAP Field", "Length (bytes)", "Description"],
            "rows": [
                ["Transaction Identifier", "2", "Set by client; echoed by server. Pipelined transactions."],
                ["Protocol Identifier",    "2", "0x0000 = MODBUS."],
                ["Length",                 "2", "= 1 (Unit ID) + len(PDU)."],
                ["Unit Identifier",        "1", "Server address on a sub-network behind a gateway."],
            ],
        })
        f.setdefault("device_identification_object_table_FC2B_MEI14", {
            "header_columns": ["Object ID", "Object Name", "Category", "Mandatory"],
            "rows": [
                ["0x00", "VendorName",                            "Basic",    "Yes"],
                ["0x01", "ProductCode",                            "Basic",    "Yes"],
                ["0x02", "MajorMinorRevision",                     "Basic",    "Yes"],
                ["0x03", "VendorUrl",                              "Regular",  "No"],
                ["0x04", "ProductName",                            "Regular",  "No"],
                ["0x05", "ModelName",                              "Regular",  "No"],
                ["0x06", "UserApplicationName",                    "Regular",  "No"],
                ["0x07..0x7F", "Reserved",                         "Reserved", "—"],
                ["0x80..0xFF", "Vendor-defined Extended objects",  "Extended", "No"],
            ],
        })
        f.setdefault("read_device_id_code_table_FC2B_MEI14", {
            "header_columns": ["Code", "Meaning"],
            "rows": [
                ["0x01", "Request to get the Basic Device Identification (stream access)"],
                ["0x02", "Request to get the Regular Device Identification (stream access)"],
                ["0x03", "Request to get the Extended Device Identification (stream access)"],
                ["0x04", "Request to get one specific identification object (individual access)"],
            ],
        })
        tbl = [
            "Public Function Code Definition (Section 5.1)",
            "MODBUS Function Code Categories (Figure 10)",
            "MODBUS Data Model — primary tables (Section 4.3)",
            "MODBUS Exception Codes (Section 7)",
            "Diagnostics sub-function codes (Section 6.8.1)",
            "MBAP Header layout (Modbus Messaging Implementation Guide)",
            "Read Device Identification — Object IDs (Section 6.21)",
            "Read Device ID codes 01..04 (Section 6.21)",
            "Annex A — Reserved Function Codes, Sub-codes and MEI Types",
        ]
        if _empty(f.get("tables")):
            f["tables"] = tbl
        d["fields"] = f
        _write(p, d)

    # ---------------- L16 compliance ----------------
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("must_have_properties", [
            "Every MODBUS PDU shall start with a 1-byte Function Code in range 1..255 (0 invalid).",
            "Exception responses shall have FC = (original FC) OR 0x80, followed by 1-byte Exception Code.",
            "PDU length shall not exceed 253 bytes.",
            "Modbus RTU ADU shall not exceed 256 bytes.",
            "Modbus ASCII ADU shall use ':' as SOF, 2-ASCII-hex char encoding, LRC, CR LF as EOF.",
            "Modbus TCP ADU shall not exceed 260 bytes; MBAP.Protocol_ID = 0x0000; MBAP.Length = 1 + len(PDU).",
            "All multi-byte numerical quantities shall be big-endian on the wire.",
            "PDU addresses are zero-based; user-facing item X is at PDU address X-1.",
            "Server validation order: FC → Data Address → Data Value → Execute.",
            "Server shall not respond to a broadcast request (Address 0 on serial transports).",
            "Server shall silently discard frames that fail CRC / LRC checks; no exception response.",
            "FC 0x05 Write Single Coil shall accept only 0xFF00 (ON) or 0x0000 (OFF); other values → 0x03.",
            "FC 0x01 / 0x02 quantity per request 1..2000.",
            "FC 0x03 / 0x04 quantity per request 1..125.",
            "FC 0x0F quantity 1..1968; FC 0x10 quantity 1..123; FC 0x17 read 1..125 + write 1..121.",
            "FC 0x18 returned FIFO count ≤ 31.",
            "FC 0x16 Mask Write Register: Result = (Current AND AND_Mask) OR (OR_Mask AND (NOT AND_Mask)).",
            "FC 0x2B Encapsulated Interface includes 1-byte MEI Type: 0x0D = CANopen, 0x0E = Read Device Identification.",
            "FC 0x2B / MEI 14 supports at least Basic conformity (objects 0x00, 0x01, 0x02 mandatory).",
            "Diagnostic counters readable via FC 0x08 sub-codes 11..18.",
        ])
        f.setdefault("must_not_have_properties", [
            "Function code 0 shall never be transmitted as a valid request.",
            "Reserved function codes in Annex A shall not be implemented by interoperable devices.",
            "MBAP.Protocol_ID != 0 shall not be sent by a MODBUS-conforming device.",
            "FC 7, 8, 11, 12, 17 shall not be used on Modbus TCP — they are serial-line-only.",
            "Server shall not respond to its own broadcast frames.",
            "Server shall not echo a corrupted request as if it were valid.",
            "FC 0x05 Output Value other than 0xFF00 / 0x0000 shall not produce a normal response.",
            "MBAP fields shall not be re-ordered.",
        ])
        f.setdefault("compliance_failure_modes", [
            {"mode": "Function code not recognized",         "trigger": "Server receives FC it does not implement → 0x01 ILLEGAL FUNCTION."},
            {"mode": "Address + Quantity out of range",      "trigger": "Server receives read/write whose items partly fall outside data tables → 0x02 ILLEGAL DATA ADDRESS."},
            {"mode": "Quantity / Byte Count out of range",   "trigger": "Quantity exceeds per-FC max; FC 0x05 Output Value ∉ {0xFF00, 0x0000} → 0x03 ILLEGAL DATA VALUE."},
            {"mode": "Server internal error during execute", "trigger": "Memory/hardware fault → 0x04 SERVER DEVICE FAILURE."},
            {"mode": "Long-running command",                 "trigger": "Programming command queued → 0x05 ACKNOWLEDGE; complete later via Poll Program Complete."},
            {"mode": "Server busy",                          "trigger": "Long command already running → 0x06 SERVER DEVICE BUSY."},
            {"mode": "File-record consistency error",        "trigger": "FC 0x14/0x15 reference-type-6 area memory-parity failed → 0x08 MEMORY PARITY ERROR."},
            {"mode": "Gateway path unavailable",             "trigger": "Gateway misconfigured/overloaded → 0x0A."},
            {"mode": "Gateway target unresponsive",          "trigger": "Gateway forwarded; target didn't reply → 0x0B."},
            {"mode": "Serial framing error",                 "trigger": "Parity/framing/CRC/LRC mismatch → silent discard; client timeout."},
            {"mode": "TCP framing error",                    "trigger": "MBAP.Protocol_ID != 0 or Length mismatch → connection-level error."},
        ])
        tc = f.setdefault("transport_constraints", {
            "modbus_rtu": {
                "adu_max_bytes": 256,
                "framing":       "T3.5 silent-line end-of-frame",
                "byte_format":   "1 start + 8 data LSB-first + parity (even default) + 1 stop bit",
                "error_check":   "CRC-16-Modbus, polynomial 0xA001 (reflected), init 0xFFFF, low byte first on wire",
                "broadcast_address": 0,
            },
            "modbus_ascii": {
                "adu_max_chars_on_wire": 513,
                "framing":               "':' start, CR LF end",
                "byte_format":            "Each PDU byte encoded as 2 ASCII-hex chars",
                "error_check":            "LRC, 2 ASCII-hex characters",
                "broadcast_address":      0,
            },
            "modbus_tcp": {
                "adu_max_bytes":     260,
                "mbap_header_size":  7,
                "protocol_id":       0,
                "reserved_port":     502,
                "no_modbus_crc":     True,
                "broadcast_concept": "Not applicable",
            },
        })
        # Nested setdefaults — fill in any inner subkey added in a later
        # round even when the outer transport_constraints dict was already
        # populated by an earlier extractor pass.
        if isinstance(tc, dict):
            mt = tc.setdefault("modbus_tcp", {})
            if isinstance(mt, dict):
                mt.setdefault("concurrent_transactions_per_socket",
                    "Limited only by Transaction-ID field width (65536 values)")
        f.setdefault("reset_behavior_compliance",
            "On power-up/reset, server's diagnostic counters and Comm Event Counter/Log shall be "
            "cleared to 0; four data tables hold implementation-defined power-on defaults; server "
            "enters WAIT_FOR_MB_INDICATION state.")
        d["fields"] = f
        _write(p, d)

    # ---------------- L17 channel catalog (overwrite — MODBUS shape) ----------------
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f["protocol_layer"] = "OSI level 7 (application). Wire signaling delegated to the chosen transport."
        f["channels_pdu"] = [
            {"name": "FUNCTION_CODE",  "direction": "bidirectional", "width_bits": 8, "purpose": "Identifies the action. Range 1..255 (0 invalid; 128..255 exception)."},
            {"name": "EXCEPTION_CODE", "direction": "server→client", "width_bits": 8, "purpose": "Identifies which validation/execution gate failed (0x01..0x0B)."},
            {"name": "DATA",           "direction": "bidirectional", "width_bits": "0..252 bytes", "purpose": "Function-code-dependent data."},
        ]
        f["channels_modbus_rtu_adu"] = [
            {"name": "ADDRESS",  "direction": "bidirectional", "width_bits": 8,  "purpose": "Server address; 0 = broadcast, 1..247 individual, 248..255 reserved."},
            {"name": "PDU",      "direction": "bidirectional", "width_bits": "8..253×8", "purpose": "Function Code + Data."},
            {"name": "CRC",       "direction": "bidirectional", "width_bits": 16, "purpose": "CRC-16-Modbus. Low byte first on the wire."},
        ]
        f["channels_modbus_ascii_adu"] = [
            {"name": "SOF (':')",  "direction": "bidirectional", "width_chars": 1, "purpose": "Start-of-frame (0x3A)."},
            {"name": "ADDRESS",    "direction": "bidirectional", "width_chars": 2, "purpose": "Server address as 2 ASCII-hex characters."},
            {"name": "FUNCTION",   "direction": "bidirectional", "width_chars": 2, "purpose": "Function code as 2 ASCII-hex characters."},
            {"name": "DATA",        "direction": "bidirectional", "width_chars": "0..504", "purpose": "PDU data as 2N ASCII-hex characters."},
            {"name": "LRC",         "direction": "bidirectional", "width_chars": 2, "purpose": "Longitudinal Redundancy Check."},
            {"name": "EOF (CR LF)", "direction": "bidirectional", "width_chars": 2, "purpose": "End-of-frame (0x0D 0x0A)."},
        ]
        f["channels_modbus_tcp_mbap"] = [
            {"name": "TRANSACTION_ID", "direction": "client-set, server-echo", "width_bits": 16, "purpose": "Request/response correlation across pipelined transactions."},
            {"name": "PROTOCOL_ID",    "direction": "bidirectional",            "width_bits": 16, "purpose": "Always 0x0000 = MODBUS."},
            {"name": "LENGTH",         "direction": "bidirectional",            "width_bits": 16, "purpose": "= 1 (Unit ID) + len(PDU)."},
            {"name": "UNIT_ID",        "direction": "client→server",             "width_bits": 8,  "purpose": "Server address behind a gateway."},
            {"name": "PDU",             "direction": "bidirectional",            "width_bits": "8..253×8", "purpose": "Function Code + Data."},
        ]
        f["channels_physical_options"] = [
            {"name": "EIA/TIA-485 differential pair A/B",          "use": "Modbus RTU/ASCII multi-drop"},
            {"name": "EIA/TIA-232 TXD/RXD + optional handshake",   "use": "Modbus RTU/ASCII point-to-point"},
            {"name": "EIA/TIA-422 differential pair",              "use": "Modbus RTU/ASCII full-duplex"},
            {"name": "Ethernet 10/100/1000BASE-T (RJ-45) or fiber","use": "Modbus TCP"},
            {"name": "MODBUS PLUS HDLC carrier (legacy)",          "use": "Modbus PLUS"},
        ]
        f["global_signals"] = [
            {"name": "BUS_IDLE_STATE",   "purpose": "Serial line idle = UART mark (HIGH)."},
            {"name": "TCP_PORT_502",     "purpose": "IANA-reserved server port for MODBUS TCP."},
            {"name": "BIG_ENDIAN_ORDER", "purpose": "All multi-byte numerical quantities are MSB-first on the wire."},
        ]
        f["channel_counts"] = {
            "pdu_function_code_bytes":   1,
            "pdu_exception_code_bytes":  1,
            "pdu_max_data_bytes":        252,
            "rtu_adu_min_bytes":         5,
            "rtu_adu_max_bytes":         256,
            "ascii_adu_min_chars":       11,
            "ascii_adu_max_chars":       513,
            "tcp_adu_min_bytes":         8,
            "tcp_adu_max_bytes":         260,
            "mbap_header_bytes":         7,
            "data_tables_primary":       4,
            "data_table_items_max":      65536,
            "function_code_full_range":  255,
            "exception_code_values":     9,
        }
        # Force-overwrite dependency_graph (earlier steps may have written
        # non-MODBUS content; MODBUS shape is request/reply application-layer).
        f["dependency_graph"] = {
            "common_rule":      "MODBUS is strictly request/reply: client transmits a complete request ADU; server validates, executes, and responds (or stays silent on broadcast / framing error). There is no application-layer ACK separate from the response PDU.",
            "data_dependency":  "Response Data depends on request Data (Starting Address, Quantity, etc.) and on server's data-table contents. MBAP.Transaction_ID of the response equals that of the request.",
        }
        f.setdefault("ordering_rules", {
            "byte_ordering":         "Big-endian (MSB first) for all multi-byte numerical quantities in the PDU.",
            "rtu_crc_order":          "CRC-16 result transmitted low byte first, then high byte — exception to big-endian rule.",
            "ascii_nibble_order":     "Within each 2-ASCII-hex byte encoding, high nibble first.",
            "frame_ordering_serial":  "Order on wire: Address, FC, Data, CRC (RTU) or LRC (ASCII).",
            "frame_ordering_tcp":     "Order on wire: Transaction ID, Protocol ID, Length, Unit ID, FC, Data.",
        })
        d["fields"] = f
        _write(p, d)

    # ---------------- L18 interconnect topology ----------------
    p = gd / "L18_INTERCONNECT_TOPOLOGY.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f["topology_type"] = (
            "Single-client / multi-server request/reply application protocol; the underlying transport "
            "(RTU/ASCII on EIA/TIA-485 multi-drop, RTU/ASCII on EIA/TIA-232 point-to-point, or Modbus TCP "
            "on switched Ethernet) determines the physical interconnect.")
        f["supported_topologies"] = [
            {"name": "RS-485 multi-drop (Modbus RTU / ASCII)",   "description": "1 master + up to 247 individual servers (addresses 1..247) on a half-duplex differential pair. Broadcast (address 0) reaches all."},
            {"name": "RS-232 point-to-point (Modbus RTU / ASCII)","description": "1 client + 1 server on a 2-wire async serial link."},
            {"name": "Switched Ethernet (Modbus TCP)",            "description": "Each MODBUS endpoint behind a TCP socket on its MAC + IP. Server reserves TCP port 502."},
            {"name": "Modbus gateway (TCP ↔ RTU bridge)",         "description": "Terminates TCP, originates RTU on downstream serial sub-networks. MBAP.Unit_ID routes to specific serial addresses."},
            {"name": "Modbus PLUS (HDLC, legacy)",                "description": "Modicon-proprietary token-passing peer-to-peer."},
        ]
        f["master_slave_role_summary"] = [
            {"role": "Client (a.k.a. master in RTU/ASCII terminology)", "description": "Sole initiator. Builds request PDU, sends it, awaits response."},
            {"role": "Server (a.k.a. slave)",                            "description": "Responds to addressed requests; never initiates."},
            {"role": "Gateway",                                          "description": "Bridges TCP front-end to downstream serial sub-network."},
        ]
        f["interconnect_role"] = (
            "MODBUS itself defines no routing or switching — every transaction is unicast addressed "
            "by RTU address (serial) or MBAP Unit ID + IP/port (TCP). Routing across transports is "
            "handled by Modbus gateways.")
        f["ordering_guarantees"] = {
            "within_a_message":  "Bytes appear on wire in transport-specific order: Address → PDU → CRC (RTU); ':' → ADDR → FC → DATA → LRC → CR LF (ASCII); MBAP → PDU (TCP).",
            "across_messages":   "Serial: one transaction in flight at a time. TCP: multiple transactions per socket, disambiguated by Transaction ID; responses may arrive in any order.",
        }
        f.setdefault("memory_vs_peripheral_regions",
            "MODBUS exposes 4 logical data tables each addressed 0..65535 in the PDU. Physical mapping is vendor-specific.")
        f.setdefault("slave_classification", {
            "polling_target":   "Client periodically reads Holding/Input Registers.",
            "event_target":     "MODBUS does not natively support unsolicited server-to-client notifications.",
            "gateway_target":   "Server addressed indirectly via gateway by setting MBAP.Unit_ID.",
        })
        f.setdefault("broadcast_topology_rtu_ascii", {
            "address_value":         0,
            "valid_function_codes":  "Writes that can be applied unconditionally — typical: FC 0x05, 0x06, 0x0F, 0x10, 0x16.",
            "invalid_for_broadcast": "All Read codes (no useful response possible).",
            "server_action":         "Process the request; do NOT transmit any response.",
            "client_post_broadcast": "Wait T_broadcast_interval before next frame.",
        })
        f.setdefault("default_signal_values_evidence_tables", [
            "Section 4.5 Define MODBUS Transaction — state diagram (Figure 9).",
            "Section 4.1 Protocol description — ADU/PDU layout (Figure 3).",
            "Section 4.3 MODBUS Data model (Figures 6/7/8).",
            "Section 6.x per-function-code state diagrams (Figures 11..16).",
            "Annex A — Reserved Function Codes/Subcodes/MEI Types.",
            "Modbus Messaging Implementation Guide V1.0a — MBAP header layout.",
        ])
        f.setdefault("gateway_routing_topology", {
            "tcp_front_end":   "Listens on TCP port 502; demultiplexes by source IP / TCP-connection.",
            "unit_id_routing": "MBAP.Unit_ID selects downstream device.",
            "serial_back_end": "Originates RTU (or ASCII) frames.",
            "failure_modes":   "Exception 0x0A GATEWAY PATH UNAVAILABLE; 0x0B GATEWAY TARGET DEVICE FAILED TO RESPOND.",
        })
        d["fields"] = f
        _write(p, d)

    # ---------------- L19 PDK (n/a) ----------------
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("constraints_present", False)
        f["notes"] = (
            "MODBUS is a published protocol specification — there is no PDK, floor-plan, SDC, UPF, "
            "or DFT artifact associated with it. Implementing IP cores ship their own physical-design "
            "collateral targeted at the underlying transport hardware (UART for RTU/ASCII, Ethernet "
            "MAC + PHY for TCP).")
        d["fields"] = f
        _write(p, d)

    # ---------------- L20 DFT (partial — protocol-level diagnostics) ----------------
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f["dft_present"] = "partial"
        f.setdefault("internal_diagnostics", [
            "FC 0x07 Read Exception Status (serial only) — 8 device-specific exception-status bits.",
            "FC 0x08 Diagnostics (serial only) — 14 sub-functions including Force Listen Only Mode and counter readouts.",
            "FC 0x0B Get Comm Event Counter (serial only).",
            "FC 0x0C Get Comm Event Log (serial only) — ≤ 64 event bytes.",
            "FC 0x11 Report Server ID (serial only) — Server ID + Run Indicator Status.",
            "Built-in exception-response mechanism — tells client exactly which validation gate failed.",
        ])
        f.setdefault("exception_response_observability", [
            "FC-MSB on response byte 0 — distinguishes normal vs exception response.",
            "Exception code (1 byte): 0x01..0x0B per spec.",
            "Diagnostic counters via FC 0x08 sub-codes 11..18.",
        ])
        f["notes"] = (
            "MODBUS provides protocol-level observability (exception responses + diagnostic counters + "
            "comm event log) rather than silicon-level DFT (scan chain, MBIST, ATPG). Modern SoC-"
            "integrated MODBUS IP from FPGA vendors adds standard scan insertion at the IP-license "
            "level.")
        d["fields"] = f
        _write(p, d)

    # ---------------- L21 power intent (n/a) ----------------
    p = gd / "L21_POWER_INTENT.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("power_intent_present", False)
        f["low_power_modes_summary"] = {
            "n_a_at_protocol_layer":   "MODBUS is OSI level 7 — no built-in low-power state, sleep/wake handshake, or power-management exchange.",
            "implementation_strategies":"Devices may gate UART/Ethernet PHY clock between transactions; host CPU may sleep until socket-receive interrupt.",
            "no_explicit_sleep_command":"No MODBUS function code places the server into a low-power state. Some vendors use User-Defined-range FCs (65..72/100..110) for proprietary sleep/wake.",
        }
        f["notes"] = (
            "Any low-power behavior is a property of the implementing silicon and firmware, not of "
            "the MODBUS protocol itself.")
        d["fields"] = f
        _write(p, d)

    # ---------------- L22 verification plan ----------------
    p = gd / "L22_VERIFICATION_PLAN.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("verification_plan_present", "implicit")
        f.setdefault("verification_categories_derived_from_spec", [
            "PDU minimum cases — FC 0x07, FC 0x0B (no data).",
            "PDU maximum cases — FC 0x10 quantity 123 = 246 byte payload.",
            "ADU framing — RTU ≤ 256 B, ASCII ≤ 513 chars, TCP ≤ 260 B.",
            "PDU-vs-user-address offset — user register 1 → PDU 0x0000.",
            "Big-endian on wire — 0x1234 → first byte 0x12.",
            "Per-FC quantity boundaries — 1, 2000, 125, 1968, 123, 121, 31.",
            "FC 0x05 Output Value enum — only 0xFF00 / 0x0000.",
            "FC 0x16 Mask Write Register: Current 0x0012, AND 0x00F2, OR 0x0025 → Result 0x0017.",
            "FC 0x17 atomic read+write — write first, then read.",
            "FC 0x18 Read FIFO Queue — fifo_count ≤ 31.",
            "FC 0x14 / 0x15 multi-sub-request file record access.",
            "Exception 0x01 ILLEGAL FUNCTION — undefined FC.",
            "Exception 0x02 ILLEGAL DATA ADDRESS — spec example: 100-register controller, address 96 + quantity 5 fails.",
            "Exception 0x03 ILLEGAL DATA VALUE — Quantity > limit; FC 0x05 invalid Output Value.",
            "Exception 0x04 SERVER DEVICE FAILURE — internal error.",
            "Exception 0x05 ACKNOWLEDGE / 0x06 SERVER DEVICE BUSY — long-running programming commands.",
            "Exception 0x08 MEMORY PARITY ERROR — file-record area consistency.",
            "Exception 0x0A / 0x0B — gateway scenarios.",
            "Broadcast (RTU/ASCII Address 0) — server processes, no response.",
            "Serial RTU CRC error — silent discard; Bus Communication Error Count++.",
            "Serial ASCII LRC error — same silent discard.",
            "RTU T3.5 silence — end-of-frame detection.",
            "ASCII intra-frame timing — long pauses tolerated.",
            "TCP MBAP.Protocol_ID = 0x0000 enforcement.",
            "TCP MBAP.Transaction_ID echo.",
            "TCP pipelined transactions.",
            "TCP MBAP.Length consistency.",
            "Diagnostics — Force Listen Only Mode entry/exit.",
            "Diagnostic counters — all 8 standard counters.",
            "Read Device Identification (FC 0x2B / MEI 14) — Basic / Regular / Extended / Specific access modes.",
            "CANopen General Reference (FC 0x2B / MEI 13).",
            "Reserved-FC rejection — FC 9, 10, 13, 14, 41, 42, 90, 91, 125..127 → 0x01.",
        ])
        f["notes"] = (
            "The MODBUS V1.1b3 spec embeds per-function-code state diagrams (Figures 11..16) that "
            "implicitly define the verification surface for each FC. There is no Modbus.org-published "
            "testbench in this document — Modbus.org references a separate 'available conformance "
            "test' for Public function codes.")
        d["fields"] = f
        _write(p, d)

    # ---------------- L23 security ----------------
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("security_requirements_present", False)
        f["notes"] = (
            "MODBUS Application Protocol V1.1b3 (2012) predates the standardization of MODBUS "
            "security extensions and contains no confidentiality, integrity, authentication, or "
            "access-control mechanisms. PDUs travel in cleartext; no signing; no client "
            "authentication; no replay protection. Practical deployments mitigate via network "
            "segmentation, VPN, IPsec, or application-layer firewalls. The dedicated 'MODBUS/TCP "
            "Security' specification (post-2018) introduces TLS encapsulation on a separate TCP "
            "port (typically 802) but is outside V1.1b3 scope.")
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
def is_modbus(blob: str) -> bool:
    """Content-only `modbus` detector with a FOREIGN-PRIMARY DEFER.

    Empty-safe. Reads ONLY ``blob`` (spec text). The original structural
    signature (below) is necessary but NOT sufficient: the loose
    ``"Modbus" and ("RTU" | "ASCII" | "TCP")`` branch is tripped by any
    spec that merely *mentions* Modbus as an incidental comparison or
    example application. Three foreign fieldbus / transceiver benchmarks
    do exactly that and would otherwise have the generic Modbus synth
    inject Modbus PDU / Function-Code content into their L-docs:
      - DALI (IEC 62386 lighting) cites Modbus/TCP as a comparison bus.
      - PROFIBUS-DP carries a Modbus-as-fieldbus comparison plus its own
        Function-Code-ish service text.
      - the TI RS-485 design guide uses Modbus-RTU as its canonical
        application example (26 "Modbus" / 21 "RTU" tokens).

    Guard (mirrors `is_mipi`'s foreign-primary defer doctrine — general,
    content-only, NO chip / SKU / benchmark-name literal as detection
    logic): if the blob's DOMINANT subject is one of those foreign
    protocols (detected by THAT protocol's distinctive multi-token
    structural signature, not by the incidental Modbus mention), defer
    (False) so the generic Modbus synth never fires on it.

    Empirically corpus-clean: the real `modbus` benchmark trips NONE of
    these defers (it carries no IEC-62386 / DPVx / SD1-SD4 / SLLA272 /
    TIA-EIA-485 signature), while dali trips dali_primary, profibus trips
    profibus_primary, and rs485 trips rs485_primary — all suppressed.
    """
    if not blob:
        return False
    low = blob.lower()

    # --- FOREIGN-PRIMARY DEFER (the blob's true subject is NOT Modbus). ---
    # DALI-primary: the IEC 62386 lighting structural signature (mirrors
    # dali_protocol_synth.is_dali). Control gear / control device + forward
    # / backward frame are DALI-only and absent from every Modbus spec.
    dali_primary = (
        ("DALI" in blob and "IEC 62386" in blob and "lighting" in low)
        or ("DALI" in blob and "control gear" in low
            and "control device" in low)
        or ("DALI" in blob and "forward frame" in low
            and "backward frame" in low))
    # PROFIBUS-primary: the PROFIBUS-DP structural signature (mirrors
    # profibus_protocol_synth.is_profibus). Require the name token AND at
    # least TWO independent PROFIBUS-only structural features (SD1-SD4
    # telegram delimiters, DPV0/1/2 service levels, GSD device database,
    # DSAP/SSAP service access points) so a passing "PROFIBUS vs Modbus"
    # comparison sentence never trips it.
    _pb_name = "profibus" in low or "process field bus" in low
    _pb_sd = sum(t in blob for t in ("SD1", "SD2", "SD3", "SD4")) >= 3
    _pb_dpv = sum(t in blob for t in ("DPV0", "DPV1", "DPV2")) >= 2
    _pb_gsd = "gsd" in low and ("device database" in low
                                or "general station description" in low
                                or "device description" in low)
    _pb_sap = "dsap" in low and "ssap" in low
    profibus_primary = _pb_name and (
        sum([_pb_sd, _pb_dpv, _pb_gsd, _pb_sap]) >= 2)
    # RS-485-primary: the TI RS-485 transceiver design-guide signature
    # (mirrors rs485_protocol_synth.is_rs485). The electrical-PHY tokens
    # (TIA/EIA-485, unit-load, fail-safe biasing, 120 Ω termination) are a
    # transceiver-layer signature absent from a Modbus application spec.
    rs485_primary = (
        "RS-485 Design Guide" in blob
        or "SLLA272" in blob
        or ("RS-485 transceiver" in blob
            and ("TIA/EIA-485" in blob or "32 unit load" in low
                 or "fail-safe biasing" in low or "120 Ω" in blob
                 or "120 ohm" in low)))
    if dali_primary or profibus_primary or rs485_primary:
        return False

    # --- STRUCTURAL Modbus signature (unchanged from the runner's inline
    #     detector). ---
    return bool(
        ("Modbus" in blob and "Function Code" in blob
            and "PDU" in blob)
        or ("Read Holding Registers" in blob
            and "Read Coils" in blob)
        or ("Modbus" in blob
            and ("RTU" in blob or "ASCII" in blob
                 or "TCP" in blob)))
