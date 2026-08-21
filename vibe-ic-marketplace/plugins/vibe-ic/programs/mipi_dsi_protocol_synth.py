"""MIPI DSI v1.01.00 protocol synth helper.

v0.1.84 — ic_class-gated overlay for `bus_interconnect_protocol` /
`serial_peripheral_protocol` specs that exhibit the MIPI DSI Display
Serial Interface structural signature (DSI + DCS + Command Mode +
Video Mode OR MIPI + DSI + Tearing Effect OR DSI + Display Serial
Interface). Applies MIPI Alliance DSI v1.01.00 (21-Feb-2008) spec-
canonical content to L1-L23.

IMPORTANT: MIPI (CSI-2) synth may fire BEFORE this one because DSI
and CSI-2 share the D-PHY physical layer and both detectors may
match. This helper FORCE-OVERWRITES the L1 / L3 keys that the CSI-2
synth populates with CSI-2-specific values (e.g. document_title,
key_features that mention RAW/YUV/RGB image-sensor pixel formats,
data_types_enum) so the final L docs reflect DSI's display-protocol
character, not CSI-2's camera-protocol character. For keys that
contain D-PHY content shared by both (e.g. HS Entry sequence, lane
voltage levels), CSI-2 values are left in place.

Doctrine: structural-keyword detection IS general within an ic_class
(mirrors AMBA-AXI / SPI / I2C / UART / CAN / USB / I2S / CSI-2 synth
approach). Any DSI v1.x variant exhibits the same structural
signature (Command Mode + Video Mode + DCS + EoTp + TE).

Public entry: `apply_mipi_dsi_synth(generated_docs_dir, is_mipi_dsi,
                                    mipi_dsi_ic_name)`.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

import l_doc_generator_stamp as _stamp


# ----- helpers --------------------------------------------------------------

def _wb(tok: str, blob: str) -> bool:
    """Word-boundary token match (avoids substring false-positives)."""
    return re.search(r"\b" + re.escape(tok) + r"\b", blob) is not None


def _empty(v) -> bool:
    return v in (None, {}, []) or (isinstance(v, str) and not v.strip())


def _read(p: Path) -> dict:
    return json.loads(p.read_text())


def _write(p: Path, d: dict) -> None:
    # THE L-document write chokepoint: stamps the producing release onto
    # the document, then serialises it byte-identically to before.
    _stamp.dump(p, d)


def _ensure_dict(d: dict, key: str) -> dict:
    """setdefault-None-safe: if the key holds None / '' / [] replace with {}."""
    if d.get(key) in (None, "", []):
        d[key] = {}
    return d[key]


def _force(d: dict, key: str, value) -> None:
    """Force-overwrite a key. Used when CSI-2 synth has already
    populated the key with CSI-2-specific value that DSI must
    replace with DSI-specific content."""
    d[key] = value


# ----- per-layer overlays ---------------------------------------------------

def _l1(gd: Path, ic_name: str) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    # DSI-specific values force-overwrite any CSI-2 values left by mipi synth.
    _force(d, "document_title",
           "MIPI Alliance Specification for Display Serial Interface (DSI)")
    _force(d, "document_number",
           "MIPI Alliance Specification for DSI, Version 1.01.00")
    _force(d, "version", "DSI v1.01.00")
    _force(d, "revised_date", "21 February 2008")
    _force(d, "original_release_date",
           "21 February 2008 (DSI v1.01.00, MIPI Board Approved 18-Jun-2008)")
    _force(d, "manufacturer", "MIPI Alliance, Inc.")
    _force(d, "copyright",
           "© 2005-2008 MIPI Alliance, Inc. All rights reserved. MIPI Alliance Member Confidential.")
    _force(d, "abstract",
           "The MIPI Display Serial Interface (DSI) specification defines protocols between a host processor and peripheral devices (display modules) that adhere to MIPI Alliance specifications for mobile device interfaces. DSI is a high-speed packet-based serial interface built on top of the MIPI D-PHY physical layer, carrying both real-time pixel data (Video Mode) and command-driven display traffic (Command Mode). DSI builds on existing MIPI Alliance specifications by adopting pixel formats from DPI-2 and the Display Command Set (DCS), serializing them into 4-byte Short Packets and variable-length Long Packets protected by an 8-bit Hamming-modified ECC over the header and an optional 16-bit CRC-16 over the payload.")
    _force(d, "keywords", [
        "MIPI", "DSI", "Display Serial Interface", "D-PHY", "DCS",
        "DPI-2", "DBI-2", "Command Mode", "Video Mode", "Burst Mode",
        "Non-Burst Mode", "Sync Pulses", "Sync Events",
        "Tearing Effect", "TE", "BTA", "Bus Turn-Around",
        "ECC", "CRC-16", "EoTp", "Virtual Channel", "Data Type",
        "Long Packet", "Short Packet",
        "Acknowledge and Error Report", "ULPS", "LPDT",
    ])
    _force(d, "external_pins", [
        "Clock+ / Clock- (Clock Lane differential pair — host → peripheral only, never reverse)",
        "Data0+ / Data0- (Data Lane 0 differential pair — bidirectional in LP Mode in Command Mode systems)",
        "Data1+ / Data1- (Data Lane 1, optional — unidirectional host → peripheral)",
        "Data2+ / Data2- (Data Lane 2, optional — unidirectional)",
        "Data3+ / Data3- (Data Lane 3, optional — unidirectional)",
    ])
    _force(d, "external_pin_count",
           "4..10 (1 Clock Lane pair + 1..4 Data Lane pairs)")
    _force(d, "key_features", [
        "Half-duplex bidirectional packet-based serial display interface — host processor (e.g. application processor) ↔ peripheral (e.g. active-matrix display module).",
        "Built on MIPI D-PHY physical layer: 1 Clock Lane + 1..4 Data Lanes, differential HS (High-Speed, 80 Mbps..1.5 Gbps per lane) and LP (Low-Power, ≤ 10 Mbps single-ended 1.2 V CMOS) signaling on the same wires.",
        "Two operating modes: Command Mode (host sends DCS commands + parameters to a peripheral with its own display controller and frame buffer; bidirectional required for read-back) and Video Mode (host streams pixel data in real time to a peripheral without local frame buffer).",
        "Three Video Mode packet sequences: Non-Burst with Sync Pulses (matches DPI-style timing including sync widths), Non-Burst with Sync Events (only Sync Start events transmitted), Burst Mode (RGB packets time-compressed to free LP intervals for power saving or other transmissions).",
        "Packet formats: Short Packet = 4 bytes (Data ID + Data0 + Data1 + ECC); Long Packet = 6..65541 bytes (Data ID + Word Count LS + Word Count MS + ECC + Payload + 16-bit Checksum).",
        "Data Identifier byte DI[7:0] = VC[7:6] Virtual Channel (4 channels) + DT[5:0] Data Type (enumerates DCS / pixel-stream / sync-event / generic short/long types).",
        "Header ECC: Hamming-modified (24,8) — single-bit correction + double-bit detection over the 24 data bits (DI + WC) of every Packet Header.",
        "Long Packet Checksum: CRC-16 polynomial x^16 + x^12 + x^5 + 1 (gsCRC16GenerationCode = 0x8408 right-shift form), initial value 0xFFFF, LSB-first; covers payload only; optional for peripheral, mandatory for host.",
        "Bus Turn-Around (BTA): explicit token-passing escape sequence on Data Lane 0 to switch link direction host ↔ peripheral; only Data Lane 0 is used for reverse-direction transmissions.",
        "Reverse direction uses LP Mode only (Low-Power Data Transmission, LPDT). HS reverse transmission is not permitted.",
        "Acknowledge and Error Report Short Packet (DT = 0x02 in peripheral-to-processor direction): 16-bit error mask reporting SoT / SoT Sync / EoT Sync / Escape Entry / LP TX Sync / HS RX Timeout / False Control / ECC single / ECC multi / Checksum / DSI DT Not Recognized / DSI VC ID Invalid / Invalid TX Length / DSI Protocol Violation.",
        "Display Command Set (DCS) transport: DCS Short Write 0/1 param (0x05/0x15), DCS Read 0 param (0x06), DCS Long Write / write_LUT (0x39), DCS Short Read Response (0x21/0x22), DCS Long Read Response (0x1C).",
        "Generic Short WRITE 0/1/2 param (0x03/0x13/0x23), Generic READ 0/1/2 param (0x04/0x14/0x24), Generic Long Write (0x29), Generic Short Read Response (0x11/0x12), Generic Long Read Response (0x1A).",
        "Sync Event Short Packets (Data Type bit pattern xx0001): V Sync Start (0x01), V Sync End (0x11), H Sync Start (0x21), H Sync End (0x31).",
        "Display control Short Packets: Color Mode Off (0x02), Color Mode On (0x12), Shutdown Peripheral (0x22), Turn On Peripheral (0x32), Set Maximum Return Packet Size (0x37).",
        "Long-Packet pixel streams: Packed Pixel Stream 16-bit RGB565 (0x0E), 18-bit RGB666 Packed (0x1E), 18-bit RGB666 Loosely Packed in three bytes (0x2E), 24-bit RGB888 (0x3E).",
        "Long-Packet non-pixel: Null Packet (0x09), Blanking Packet (0x19), Generic Long Write (0x29), DCS Long Write (0x39).",
        "End of Transmission packet (EoTp, DT = 0x08): fixed Short Packet with payload 0x0F0F, VC=0, ECC=0x01 — appended to every HS transmission per DSI v1.01 to decouple end-of-HS detection from PHY characteristics.",
        "Tearing Effect (TE): peripheral-initiated LP trigger message byte 0x5D (LSB-first 10111010) sent via Escape Mode after BTA, used by Command Mode display modules to tell the host when it is safe to write the next frame.",
        "Required timers for contention recovery: HS RX Timeout (HRX_TO, in bidirectional peripheral), HS TX Timeout (HTX_TO, in host), LP TX-Peripheral Timeout (LTX-P_TO), LP RX-Host Timeout (LRX-H_TO). Additional optional timers: TA_TO (Turnaround Acknowledge) and PR_TO (Peripheral Reset).",
        "Power-up: host drives sustained LP-11 TX-Stop for T_INIT; peripheral powers up in RX-Stop and starts accepting bus transactions immediately after T_INIT elapses. Host's T_INIT_MASTER must be longer than t_POR + T_INIT_SLAVE + T_INTERNAL_DELAY of the peripheral.",
        "Multi-Lane operation: Lane Distributor sends bytes round-robin (byte k → lane k mod N); Lane Merger reassembles on the receive side. All Lanes start SoT in parallel; some may complete EoT one byte earlier than others when payload byte count is not a multiple of N.",
        "Up to 4 Virtual Channels via DI[7:6] allow multiplexing multiple peripherals onto a shared DSI Link (when the host supports it).",
    ])
    _force(d, "topology_summary",
           "Point-to-point asymmetric (mostly source → sink, with Data Lane 0 bidirectional for ACK/error/read responses/TE). Host processor drives Clock Lane unconditionally; peripheral never drives Clock Lane. In Command Mode systems Data Lane 0 is mandatory bidirectional. In Video Mode systems Data Lane 0 may be bidirectional or unidirectional. Additional Data Lanes are always unidirectional host → peripheral.")
    _force(d, "package_summary",
           "Application-processor SoC ↔ active-matrix display module (panel + on-panel driver IC). Physical interconnect is short PCB trace or FFC cable inside a mobile device chassis (phone / tablet / handheld) — typically a few centimeters at sub-Gbps rates.")
    _force(d, "revision_history", [
        {"version": "DSI v1.01.00",
         "date": "21-Feb-2008 (MIPI Board approved 18-Jun-2008)",
         "description": "Current revision. Added EoTp (DT=0x08) as a dedicated end-of-transmission Short Packet. Aligned with D-PHY v0.90.00 (MIPI Alliance, 8-Oct-2007), DBI-2 v2.00, DPI-2 v2.00, and DCS v1.02.00."},
        {"version": "DSI v1.0", "date": "earlier",
         "description": "Initial DSI release; did not support EoTp Short Packet. v1.01-compliant devices must provide a means to enable/disable EoTp for interoperability with v1.0 peripherals."},
    ])
    _force(d, "use_cases", [
        "Mobile-phone main display (active-matrix LCD or OLED on-panel-driver) connected to application processor.",
        "Tablet / handheld display panel link.",
        "Wearable / IoT small-format active-matrix display.",
        "Video Mode operation for displays without on-panel frame buffer (host streams pixel data at frame rate).",
        "Command Mode operation for displays with on-panel display controller + frame buffer (host writes pixels into the panel's frame memory).",
    ])
    _force(d, "overview",
           "DSI specifies a high-speed bidirectional serial interface between a host processor (typically a mobile application processor or baseband processor) and a peripheral, typically an active-matrix display module. It builds on existing MIPI Alliance specifications by adopting the Display Command Set (DCS) for register-style command transport (analogous to the parallel DBI-2 standard) and the DPI-2 pixel-format definitions for real-time pixel streaming. All information traverses DSI as a byte stream that is serialized over D-PHY HS / LP signaling; on the peripheral side the serial stream is deserialized back into parallel data and control signals for the on-panel display controller. From a system viewpoint, DSI hides the serialization/deserialization from software and offers higher performance, lower power, lower EMI, and fewer pins than the legacy parallel DBI / DPI interfaces it replaces.")
    _write(p, d)


def _l2(gd: Path, ic_name: str) -> None:
    p = gd / "L2_FRS.json"
    if not p.is_file():
        return
    d = _read(p)
    # CSI-2 synth's protocol_overview is camera-oriented; DSI overwrites.
    _force(d, "protocol_overview", {
        "type": "Packet-based half-duplex bidirectional serial display interface on top of source-synchronous DDR D-PHY physical layer; combines DPI-2 pixel streaming (Video Mode) and DBI-2-style command/parameter transport (Command Mode) into one serialized link.",
        "duplex": "Half-duplex per Data Lane 0 (the only bidirectional lane); additional Data Lanes 1..3 are strictly unidirectional host → peripheral.",
        "synchronous": True,
        "wire_names": ["Clock+ / Clock- (Clock Lane differential pair)",
                       "Data0+ / Data0- (Data Lane 0 — bidirectional in LP)",
                       "Data1.. (optional Data Lanes 1..3, unidirectional)"],
        "wire_count": "2 + 2 × N_data_lanes (N=1..4); 4..10 wires total",
        "dual_mode_signaling": "HS (high-speed differential 100-200 mV terminated) + LP (low-power 1.2 V single-ended) on the same Dp/Dn pair; mode arbitrated by the lane-state controller.",
        "DDR_clock": "Source-synchronous DDR Clock Lane — both edges latch one bit per Data Lane; data-rate-per-lane = 2 × Clock-Lane Hz. Clock Lane is host → peripheral only (never reversed).",
        "controller_role": "Host processor: drives Clock Lane; transmits all forward-direction HS / LP packets; initiates BTA; programs T_INIT_MASTER ≥ t_POR + T_INIT_SLAVE + T_INTERNAL_DELAY at power-up.",
        "target_role": "Peripheral (display module): receives forward HS / LP packets; after BTA, transmits LP reverse-direction packets (Acknowledge, Acknowledge and Error Report, Read Response, Tearing Effect trigger message); returns bus to host with its own BTA.",
    })
    _force(d, "functional_requirements", [
        {"id": "FR-DSI-MODE-01",      "text": "DSI peripherals shall support either Command Mode (DCS commands + frame buffer at peripheral) or Video Mode (real-time pixel streaming from host), or both."},
        {"id": "FR-DSI-LANE-02",      "text": "Host shall implement at minimum 1 Data Lane plus 1 Clock Lane; additional Data Lanes 1..3 are optional."},
        {"id": "FR-DSI-CLOCK-03",     "text": "Clock Lane shall be driven by the host processor only, never by the peripheral. Continuous Clock Mode shall be supported by all DSI transmitters and receivers."},
        {"id": "FR-DSI-LP-BIDIR-04",  "text": "In a Command Mode system, Data Lane 0 shall be bidirectional; additional Data Lanes shall be unidirectional. In a Video Mode system, Data Lane 0 may be bidirectional or unidirectional."},
        {"id": "FR-DSI-LP-ONLY-05",   "text": "Forward-direction Low Power transmissions shall use Data Lane 0 only. Reverse-direction transmissions shall use Low Power Mode only and shall use Data Lane 0 only."},
        {"id": "FR-DSI-PACKET-06",    "text": "DSI shall transport data using Short Packet (4 bytes) and Long Packet (6..65541 bytes) per §8.4."},
        {"id": "FR-DSI-DI-07",        "text": "Data Identifier byte DI[7:0] = VC[7:6] (Virtual Channel, 4 channels) + DT[5:0] (Data Type)."},
        {"id": "FR-DSI-ECC-08",       "text": "Every Packet Header shall carry an 8-bit ECC providing single-bit error correction + 2-bit error detection over DI + WC using a Hamming-modified code. P6 and P7 are unused and shall be 0 by transmitter; receiver shall ignore P6/P7 and force them to 0 before processing."},
        {"id": "FR-DSI-CRC-09",       "text": "Long Packet Payload Checksum shall be 16-bit CRC poly x^16+x^12+x^5+1, init 0xFFFF, LSB-first, covering payload only. Zero-length payload Checksum = 0xFFFF. Non-checksum peripheral Checksum = 0x0000."},
        {"id": "FR-DSI-ENDIAN-10",    "text": "All packet data traverses LSB-first within each byte; multi-byte fields LS byte first unless otherwise specified."},
        {"id": "FR-DSI-EOTP-11",      "text": "Devices compliant with DSI v1.01 shall support EoTp Short Packet (DT = 0x08, VC = 0, payload = 0x0F0F, ECC = 0x01). EoTp shall be sent at end of every HS transmission when enabled, NOT for LP transmissions. Devices shall provide a means to enable / disable EoTp."},
        {"id": "FR-DSI-BTA-12",       "text": "Bus Turn-Around shall use D-PHY LP Escape Mode mechanism. Host asserts TurnRequest; peripheral responds; peripheral hands bus back via own TurnRequest."},
        {"id": "FR-DSI-ACK-13",       "text": "Peripheral shall respond with one or more appropriate packets after every host transmission that asserts BTA, then return bus ownership."},
        {"id": "FR-DSI-VC-14",        "text": "Up to four Virtual Channels (VC[1:0]) shall be supported."},
        {"id": "FR-DSI-ERR-REPORT-15","text": "Peripheral shall implement ECC checking; Checksum checking is optional. Errors reported via Acknowledge and Error Report Short Packet (DT = 0x02) after BTA."},
        {"id": "FR-DSI-TIMER-16",     "text": "Bidirectional peripheral shall implement HRX_TO and LTX-P_TO. Host shall implement HTX_TO and LRX-H_TO. LRX-H_TO must be set longer than LTX-P_TO."},
        {"id": "FR-DSI-INIT-17",      "text": "Host shall drive sustained LP-11 TX-Stop for T_INIT at power-up. Host's T_INIT_MASTER ≥ t_POR + T_INIT_SLAVE + T_INTERNAL_DELAY of peripheral."},
        {"id": "FR-DSI-MULTILANE-18", "text": "When N_data_lanes > 1, Lane Distributor sends bytes round-robin (byte k → lane (k mod N)); all Lanes start SoT in parallel; single common Clock Lane shared by all Data Lanes."},
        {"id": "FR-DSI-TE-19",        "text": "Tearing Effect from a Command Mode display module shall be transmitted as LP Escape trigger byte 0x5D (LSB-first 10111010); host first gives bus possession to peripheral via BTA without command."},
        {"id": "FR-DSI-VIDEOSEQ-20",  "text": "Video Mode peripherals shall support at least one of three packet sequences: Non-Burst with Sync Pulses, Non-Burst with Sync Events, Burst Mode."},
        {"id": "FR-DSI-DCS-21",       "text": "Command Mode peripherals shall support DCS (0x05 / 0x15 / 0x06 / 0x39 + 0x21 / 0x22 / 0x1C) on top of DSI Short/Long Packets."},
        {"id": "FR-DSI-PIXFMT-22",    "text": "Video Mode host SHALL implement all four pixel formats (RGB565 / RGB666 Packed / RGB666 Loosely Packed / RGB888). Peripheral SHALL implement at least one."},
        {"id": "FR-DSI-MRPS-23",      "text": "Maximum Return Packet Size defaults to 1 at power-on / reset. Host programs via Set Maximum Return Packet Size Short Packet (DT=0x37)."},
        {"id": "FR-DSI-DTRESERVED-24","text": "Data Type codes with DT[3:0] = 0b0000 or 0b1111 SHALL NOT be used. Other unspecified codes are Reserved."},
    ])
    _force(d, "configurations", [
        {"name": "Command Mode + 1 Lane (bidir)",
         "description": "Smallest bidirectional config: 1 Clock Lane + 1 bidirectional Data Lane 0."},
        {"name": "Command Mode + 2..4 Lanes",
         "description": "Data Lane 0 bidirectional + 1..3 additional unidirectional Data Lanes."},
        {"name": "Video Mode + 1..4 Lanes, unidirectional",
         "description": "Cost-optimized Video Mode display without on-panel buffer."},
        {"name": "Video Mode + 1..4 Lanes, bidirectional",
         "description": "Video Mode with bidirectional Data Lane 0 for Acknowledge and Error Report."},
        {"name": "Continuous Clock Mode",
         "description": "Clock Lane stays in HS forever; lowest latency."},
        {"name": "Non-Continuous Clock Mode",
         "description": "Clock Lane returns to LP-11 between HS bursts; saves clock-tree power."},
        {"name": "EoTp enabled",
         "description": "Every HS transmission ends with EoTp Short Packet (DT=0x08, payload 0x0F0F)."},
        {"name": "EoTp disabled",
         "description": "Backward-compatible with v1.0 peripherals."},
    ])
    _force(d, "error_response_conditions", [
        "ECC single-bit error — corrected; Error Report bit 8 set.",
        "ECC multi-bit error — packet dropped; bit 9 set; rest of transmission lost.",
        "Checksum mismatch on Long Packet payload — bit 10 set.",
        "Unrecognized Data Type — bit 11 set.",
        "Invalid VC ID — bit 12 set.",
        "Invalid Transmission Length — bit 13 set.",
        "DSI Protocol Violation — bit 15 set (expected EoTp / BTA not received).",
        "SoT Error — bit 0 set; SoT Sync Error — bit 1; EoT Sync Error — bit 2.",
        "Escape Mode Entry Command Error — bit 3; LP Transmit Sync Error — bit 4.",
        "HS Receive Timeout Error — bit 5 set (HRX_TO expired).",
        "False Control Error — bit 6 set.",
        "LP Contention — Annex A recovery flow.",
    ])
    _force(d, "compliance_requirements", [
        "Sync pattern, HS Entry / Exit, lane-state encoding inherit from MIPI D-PHY v0.90.00.",
        "Packet Header ECC = Hamming-modified single-bit-correct / 2-bit-detect over 24-bit DI + WC.",
        "Long-Packet Payload Checksum = 16-bit CRC, polynomial x^16+x^12+x^5+1, init 0xFFFF, LSB-first.",
        "All DSI transmitters and receivers shall support Continuous Clock behavior on the Clock Lane.",
        "Host LP clock frequency shall be in the range 67%..150% of peripheral LP clock frequency.",
        "Set Maximum Return Packet Size (0x37) default value at power-on or reset shall be 1.",
        "Reserved bit positions in the Error Report (bits 7 and 14) shall be sent as 0.",
    ])
    _write(p, d)


def _l3(gd: Path, ic_name: str) -> None:
    p = gd / "L3_CMD_PROTOCOL.json"
    if not p.is_file():
        return
    d = _read(p)
    # CSI-2 synth populated this with camera Long/Short + RAW/YUV/RGB DTs.
    # DSI replaces wholesale with display-protocol values.
    _force(d, "protocol_type",
           "Packet-based half-duplex display-traffic protocol on top of source-synchronous DDR D-PHY. Two transaction styles coexist: (a) command/parameter transactions (Command Mode) using DCS and Generic Read/Write Short/Long Packets, and (b) real-time pixel-stream transactions (Video Mode) using Sync Event Short Packets + Packed/Loosely-Packed RGB Long Packets + Blanking/Null Long Packets.")
    _force(d, "channels", [
        {"name": "Clock+ / Clock-",
         "direction": "host → peripheral (HS); idle LP-11 between bursts",
         "purpose": "Differential DDR Clock Lane; sourced exclusively by host."},
        {"name": "Data0+ / Data0-",
         "direction": "host → peripheral (HS); bidirectional in LP for Command Mode; carries all reverse-direction LP traffic",
         "purpose": "Differential Data Lane 0; carries Short / Long Packets and is the only lane used for reverse direction (BTA + ACK + read response + TE)."},
        {"name": "Data1..3 (optional)",
         "direction": "host → peripheral only",
         "purpose": "Additional unidirectional Data Lanes for higher forward bandwidth; bytes interleaved round-robin."},
    ])
    _force(d, "packet_classes", [
        {"class": "Short Packet (Processor-sourced)",
         "purpose": "Command Mode commands, Video Mode Sync Events, Generic / DCS Short Read/Write, Set Maximum Return Packet Size.",
         "header_layout": "DI (1 byte) + Data0 (1 byte) + Data1 (1 byte) + ECC (1 byte) = 4 bytes.",
         "members": [
             "0x01 Sync Event V Sync Start",
             "0x11 Sync Event V Sync End",
             "0x21 Sync Event H Sync Start",
             "0x31 Sync Event H Sync End",
             "0x08 End of Transmission packet (EoTp)",
             "0x02 Color Mode Off",
             "0x12 Color Mode On",
             "0x22 Shutdown Peripheral",
             "0x32 Turn On Peripheral",
             "0x03 / 0x13 / 0x23 Generic Short WRITE, 0/1/2 parameters",
             "0x04 / 0x14 / 0x24 Generic READ Request, 0/1/2 parameters",
             "0x05 / 0x15 DCS Short Write, 0/1 parameter",
             "0x06 DCS Read Request, no parameters",
             "0x37 Set Maximum Return Packet Size",
         ]},
        {"class": "Long Packet (Processor-sourced)",
         "purpose": "Pixel streams, generic blocks of host-to-peripheral data, blanking padding, DCS Long Write.",
         "header_layout": "DI + WC LS + WC MS + ECC = 32-bit Packet Header.",
         "payload_layout": "WC bytes of data; LSB-first within each byte.",
         "footer_layout": "16-bit Packet Footer = CRC-16 polynomial x^16+x^12+x^5+1, init 0xFFFF, LSB-first; covers payload only. For zero-length payload, Footer = 0xFFFF.",
         "members": [
             "0x09 Null Packet, no data",
             "0x19 Blanking Packet, no data",
             "0x29 Generic Long Write",
             "0x39 DCS Long Write / write_LUT",
             "0x0E Packed Pixel Stream 16-bit RGB565",
             "0x1E Packed Pixel Stream 18-bit RGB666 Packed",
             "0x2E Packed Pixel Stream 18-bit RGB666 Loosely Packed (three bytes per pixel)",
             "0x3E Packed Pixel Stream 24-bit RGB888",
         ]},
        {"class": "Short Packet (Peripheral-sourced)",
         "purpose": "Acknowledge / error report / short read responses, EoTp.",
         "header_layout": "DI + Byte 1 + Byte 2 + ECC = 4 bytes.",
         "members": [
             "0x02 Acknowledge and Error Report",
             "0x08 EoTp",
             "0x11 Generic Short READ Response, 1 byte",
             "0x12 Generic Short READ Response, 2 bytes",
             "0x21 DCS Short READ Response, 1 byte",
             "0x22 DCS Short READ Response, 2 bytes",
         ]},
        {"class": "Long Packet (Peripheral-sourced)",
         "purpose": "Long read responses.",
         "header_layout": "DI + WC LS + WC MS + ECC + payload + 16-bit Checksum.",
         "members": [
             "0x1A Generic Long READ Response",
             "0x1C DCS Long READ Response",
         ]},
    ])
    _force(d, "data_identifier_byte", {
        "width_bits": 8,
        "structure": "DI = { VC[7:6] : DT[5:0] }",
        "VC_field_bits": [7, 6],
        "DT_field_bits": [5, 0],
        "VC_count": 4,
    })
    _force(d, "data_types_enum", {
        "processor_sourced_short_packets": [
            {"DT_hex": "0x01", "DT_binary": "00 0001", "name": "Sync Event V Sync Start"},
            {"DT_hex": "0x11", "DT_binary": "01 0001", "name": "Sync Event V Sync End"},
            {"DT_hex": "0x21", "DT_binary": "10 0001", "name": "Sync Event H Sync Start"},
            {"DT_hex": "0x31", "DT_binary": "11 0001", "name": "Sync Event H Sync End"},
            {"DT_hex": "0x08", "DT_binary": "00 1000", "name": "End of Transmission packet (EoTp)"},
            {"DT_hex": "0x02", "DT_binary": "00 0010", "name": "Color Mode (CM) Off Command"},
            {"DT_hex": "0x12", "DT_binary": "01 0010", "name": "Color Mode (CM) On Command"},
            {"DT_hex": "0x22", "DT_binary": "10 0010", "name": "Shutdown Peripheral Command"},
            {"DT_hex": "0x32", "DT_binary": "11 0010", "name": "Turn On Peripheral Command"},
            {"DT_hex": "0x03", "DT_binary": "00 0011", "name": "Generic Short WRITE, no parameters"},
            {"DT_hex": "0x13", "DT_binary": "01 0011", "name": "Generic Short WRITE, 1 parameter"},
            {"DT_hex": "0x23", "DT_binary": "10 0011", "name": "Generic Short WRITE, 2 parameters"},
            {"DT_hex": "0x04", "DT_binary": "00 0100", "name": "Generic READ, no parameters"},
            {"DT_hex": "0x14", "DT_binary": "01 0100", "name": "Generic READ, 1 parameter"},
            {"DT_hex": "0x24", "DT_binary": "10 0100", "name": "Generic READ, 2 parameters"},
            {"DT_hex": "0x05", "DT_binary": "00 0101", "name": "DCS Short WRITE, no parameters"},
            {"DT_hex": "0x15", "DT_binary": "01 0101", "name": "DCS Short WRITE, 1 parameter"},
            {"DT_hex": "0x06", "DT_binary": "00 0110", "name": "DCS READ, no parameters"},
            {"DT_hex": "0x37", "DT_binary": "11 0111", "name": "Set Maximum Return Packet Size"},
        ],
        "processor_sourced_long_packets": [
            {"DT_hex": "0x09", "DT_binary": "00 1001", "name": "Null Packet, no data"},
            {"DT_hex": "0x19", "DT_binary": "01 1001", "name": "Blanking Packet, no data"},
            {"DT_hex": "0x29", "DT_binary": "10 1001", "name": "Generic Long Write"},
            {"DT_hex": "0x39", "DT_binary": "11 1001", "name": "DCS Long Write / write_LUT Command Packet"},
            {"DT_hex": "0x0E", "DT_binary": "00 1110", "name": "Packed Pixel Stream, 16-bit RGB 5-6-5"},
            {"DT_hex": "0x1E", "DT_binary": "01 1110", "name": "Packed Pixel Stream, 18-bit RGB 6-6-6 Packed"},
            {"DT_hex": "0x2E", "DT_binary": "10 1110", "name": "Loosely Packed Pixel Stream, 18-bit RGB 6-6-6 (three bytes per pixel)"},
            {"DT_hex": "0x3E", "DT_binary": "11 1110", "name": "Packed Pixel Stream, 24-bit RGB 8-8-8"},
        ],
        "peripheral_sourced_short_packets": [
            {"DT_hex": "0x02", "DT_binary": "00 0010", "name": "Acknowledge and Error Report"},
            {"DT_hex": "0x08", "DT_binary": "00 1000", "name": "End of Transmission packet (EoTp)"},
            {"DT_hex": "0x11", "DT_binary": "01 0001", "name": "Generic Short READ Response, 1 byte returned"},
            {"DT_hex": "0x12", "DT_binary": "01 0010", "name": "Generic Short READ Response, 2 bytes returned"},
            {"DT_hex": "0x21", "DT_binary": "10 0001", "name": "DCS Short READ Response, 1 byte returned"},
            {"DT_hex": "0x22", "DT_binary": "10 0010", "name": "DCS Short READ Response, 2 bytes returned"},
        ],
        "peripheral_sourced_long_packets": [
            {"DT_hex": "0x1A", "DT_binary": "01 1010", "name": "Generic Long READ Response (with optional Checksum)"},
            {"DT_hex": "0x1C", "DT_binary": "01 1100", "name": "DCS Long READ Response (with optional Checksum)"},
        ],
        "reserved_and_do_not_use": "DT codes with DT[3:0] = 0b0000 or 0b1111 shall NOT be used. Other unspecified codes are Reserved.",
    })
    _force(d, "header_ecc_field", {
        "width_bits": 8,
        "structure": "Hamming-modified (24,8): 6 parity bits over 24 data bits (DI + WC LS + WC MS) packed into ECC[5:0]; P6 and P7 are unused.",
        "correction_capability": "Single-bit header error — corrected automatically.",
        "detection_capability": "Double-bit header error — detected; packet shall be dropped.",
    })
    _force(d, "payload_crc_field", {
        "width_bits": 16,
        "polynomial_equation": "x^16 + x^12 + x^5 + 1",
        "polynomial_hex_msb_first": "0x1021",
        "polynomial_hex_lsb_first_shift_form": "0x8408",
        "initial_value_hex": "0xFFFF",
        "shift_direction": "LSB-first (per DSI v1.01.00 Annex B reference implementation)",
        "covers": "Long Packet payload bytes only (NOT the header).",
        "zero_payload_value_hex": "0xFFFF",
        "no_checksum_peripheral_value_hex": "0x0000",
    })
    _force(d, "transaction_phases", [
        "Host LP-11 idle.",
        "HS Entry: LP-11 → LP-01 → LP-00 → HS-0 → Sync 8'b00011101 → HS payload (per D-PHY).",
        "Packet Stream: one or more concatenated Short / Long Packets (DI → WC → ECC → payload → Checksum for Long).",
        "Optional EoTp: Short Packet DT=0x08, VC=0, Data=0x0F0F, ECC=0x01 appended at end of every HS transmission when enabled.",
        "HS Exit: HS-Trail → LP-11.",
        "Optional BTA: LP Escape Mode handover from host to peripheral; peripheral transmits LP response packets; peripheral hands bus back.",
        "Optional TE: peripheral, holding the bus after a BTA-without-command, sends LP Escape trigger 0x5D then returns bus to host.",
    ])
    _force(d, "addressing", {
        "device_address": "None at the protocol layer; DSI is normatively point-to-point (host ↔ one peripheral).",
        "virtual_channel_width_bits": 2,
        "virtual_channel_count": 4,
        "default_VC_at_reset": 0,
        "VC_role": "Time-multiplex multiple logical streams or peripherals onto the same physical DSI Link.",
    })
    _force(d, "valid_ready_handshake_rules", [
        "No per-packet ACK / NAK / retry on HS payload; integrity is end-to-end via ECC and CRC-16.",
        "Following a non-Read command with BTA asserted, peripheral responds with Acknowledge Trigger Message (single byte 0x21 in escape mode) if no errors stored, or Acknowledge and Error Report Short Packet (DT=0x02) if any errors set.",
        "Following a Read Request with BTA, peripheral responds with the requested DCS / Generic Short/Long Read Response packet; single-bit ECC error → Read Response + Acknowledge and Error Report in same LP transmission.",
        "Multi-bit ECC error on a request: peripheral sends ONLY Acknowledge and Error Report (no read data).",
        "Errors accumulate in the peripheral's Error Register across multiple transmissions until next BTA; single Acknowledge and Error Report returned regardless of how many transmissions preceded.",
        "EoTp (when enabled) supplements rather than replaces D-PHY EoT sequence.",
        "Set Maximum Return Packet Size constrains read responses; default is 1 byte at power-on / reset.",
    ])
    d["burst_based"] = True
    d["byte_oriented"] = True
    _force(d, "endian_policy",
           "Bytes traverse the interface LSB-first; multi-byte fields (WC, Checksum, read-response 2-byte data) transmit least-significant byte first.")
    _write(p, d)


def _l4(gd: Path, ic_name: str) -> None:
    p = gd / "L4_REGMAP.json"
    if not p.is_file():
        return
    d = _read(p)
    d["register_map_present"] = False
    # CSI-2 sets notes to camera-protocol text; DSI must overwrite.
    _force(d, "notes",
           "MIPI DSI v1.01.00 defines a packet-based wire-level transport layer (Short / Long Packets, DI + WC + ECC + Checksum) but does NOT define a conventional addressable register file. Display-controller registers (CABC / gamma / Gate / Source / partial-display / scanline / Tearing Effect / etc.) are accessed through the standardized Display Command Set (DCS) per the MIPI Alliance Standard for DCS (referenced in DSI spec §3.3), which is layered ON TOP OF DSI Short/Long Packets — DCS commands travel inside DSI 0x05/0x15/0x06/0x39 packets as opaque payload from the DSI Protocol Layer's perspective. The peripheral also implements (per §8.9.5 / §8.10.7) an internal Error Register that accumulates the 16-bit Error Report bit-flags; this register is observed by the host indirectly via the Acknowledge and Error Report Short Packet (DT=0x02) and is cleared on report. Implementation-specific registers (skew trim, PLL configuration, lane-count select, EoTp enable, Continuous-Clock select, etc.) are vendor-defined and not part of the DSI normative spec; some are exposed via the peripheral's vendor-specific DCS extension command codes 0x00..0xFF (per MIPI DCS spec).")
    _write(p, d)


def _l5(gd: Path, ic_name: str) -> None:
    p = gd / "L5_ADI_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["analog_digital_interface_present"] = True
    # CSI-2's signaling_summary mentions camera; DSI version is similar but
    # references D-PHY v0.90.00 + bidir Data Lane 0 + LP-CD requirement.
    if "DSI" not in (d.get("signaling_summary") or ""):
        _force(d, "signaling_summary",
               "DSI inherits the dual-mode analog/mixed-signal D-PHY physical layer described in MIPI Alliance Specification for D-PHY v0.90.00 (8-Oct-2007). The DSI spec itself (§1.1, §5) explicitly declares electrical specifications and physical specifications out of scope — those are covered by D-PHY. DSI specifies WHEN HS vs LP is used (forward HS payload, reverse LP only, BTA via Escape Mode) and the protocol-level timing relationships (T_INIT, HRX_TO, LTX-P_TO, etc.) but not the electrical waveforms.")
    # ABSENT in CSI-2: voltage levels, analog component list, DSI-specific data
    # rate range extras. DSI fills them in.
    d.setdefault("voltage_levels_inherited_from_d_phy", {
        "HS_differential_swing_mV": [100, 200],
        "HS_common_mode_V_typ": 0.2,
        "HS_termination_ohm": 100,
        "LP_swing_V": 1.2,
        "LP_termination": "unterminated (high-impedance)",
    })
    d.setdefault("analog_components_per_lane_inherited", [
        "HS differential driver (current-mode, 100-200 mV differential, sub-LVDS) — host side only on Clock Lane; bidirectional on Data Lane 0 (LP) but unidirectional on Data Lane 0 (HS).",
        "HS differential receiver with 100 Ω internal differential termination + comparator.",
        "LP push-pull CMOS driver (1.2 V rail-to-rail).",
        "LP receiver — two single-ended CMOS Schmitt inputs (one per Dp, one per Dn).",
        "LP contention detector (LP-CD) — required on Data Lane 0 for bidirectional operation.",
        "Lane-state controller — arbitrates HS vs LP per lane and per direction.",
        "PLL providing Clock-Lane DDR frequency on host side; receiver clock recovery on peripheral side.",
    ])
    # DSI data_rate_ranges supplements CSI-2's HS_min/HS_max/LP_max with two
    # DSI-specific extras (DSI_clock_byte_clock_ratio, HS_max_Mbps_per_lane_d_phy_v0_90).
    _drr = d.get("data_rate_ranges")
    if isinstance(_drr, dict):
        _drr.setdefault("HS_min_Mbps_per_lane", 80)
        _drr.setdefault("HS_max_Mbps_per_lane_d_phy_v0_90", 1000)
        _drr.setdefault("LP_max_Mbps_per_lane", 10)
        _drr.setdefault("DSI_clock_byte_clock_ratio",
                        "Bit Clock = full HS data rate per Data Lane; Byte Clock = Bit Clock / 8 at the Protocol↔Application interface.")
    else:
        d["data_rate_ranges"] = {
            "HS_min_Mbps_per_lane": 80,
            "HS_max_Mbps_per_lane_d_phy_v0_90": 1000,
            "LP_max_Mbps_per_lane": 10,
            "DSI_clock_byte_clock_ratio": "Bit Clock = full HS data rate per Data Lane; Byte Clock = Bit Clock / 8 at the Protocol↔Application interface.",
        }
    d.setdefault("dsi_specific_lane_module_requirements", {
        "host_command_mode_minimum": {
            "data_lane_module": "CIL-MFAA (HS-TX, LP-TX, LP-RX, LP-CD)",
            "clock_lane_module": "CIL-MCNN (HS-TX, LP-TX)",
        },
        "peripheral_command_mode_minimum": {
            "data_lane_module": "CIL-SFAA (HS-RX, LP-RX, LP-TX, LP-CD)",
            "clock_lane_module": "CIL-SCNN (HS-RX, LP-RX)",
        },
        "host_video_mode_minimum": {
            "data_lane_module": "CIL-MFAN (HS-TX, LP-TX)",
            "clock_lane_module": "CIL-MCNN (HS-TX, LP-TX)",
        },
        "peripheral_video_mode_minimum": {
            "data_lane_module": "CIL-SFAN (HS-RX, LP-RX)",
            "clock_lane_module": "CIL-SCNN (HS-RX, LP-RX)",
        },
    })
    d.setdefault("lp_clock_frequency_constraint",
                 "Host LP clock frequency shall be 67%..150% of peripheral LP clock frequency (3:2 maximum mismatch). Peripheral implementer shall specify nominal LP clock frequency and guaranteed accuracy.")
    d.setdefault("init_timer_accuracy",
                 "Detecting T_INIT requires only minimal timing capability on the peripheral; an R-C timer with ±30% accuracy is acceptable in most cases.")
    # CSI-2 sets notes to camera-protocol text; DSI must overwrite.
    _force(d, "notes",
           "Although DSI itself is a purely protocol/transport-layer specification, the underlying D-PHY is firmly mixed-signal. HS-driver current control, 100 Ω termination matching, and skew control on the differential pairs are mandatory for multi-gigabit-rate operation. The DSI-specific addition over CSI-2 is the bidirectional Data Lane 0 in Command Mode and the LP-CD contention detector required to recover the Link without hard reset (Annex A).")
    _write(p, d)


def _l6(gd: Path, ic_name: str) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    # CSI-2's FSM states are unidirectional source/sink; DSI adds BTA + bidir.
    _force(d, "fsm_states_host_protocol", [
        {"name": "HOST_LP11_IDLE",            "description": "All Lanes driving LP-11 Stop state; host has bus possession; no pending transaction."},
        {"name": "HOST_HS_ENTRY",             "description": "Host issues D-PHY HS Request sequence."},
        {"name": "HOST_TX_PACKET_STREAM",     "description": "Host streams one or more Short/Long Packets back-to-back on HS payload."},
        {"name": "HOST_TX_EOTP",              "description": "If EoTp enabled, host appends Short Packet DI=0x08, payload=0x0F0F, ECC=0x01."},
        {"name": "HOST_HS_EXIT",              "description": "HS-Trail → LP-11."},
        {"name": "HOST_BTA_REQUEST",          "description": "Host asserts TurnRequest after transmission expecting response; PHY drives BTA escape."},
        {"name": "HOST_LP_RX_WAIT",           "description": "Host has handed bus to peripheral; LRX-H_TO running."},
        {"name": "HOST_LP_RX_DECODE",         "description": "Host receives Acknowledge / Error Report / Read Response / TE in LP on Data Lane 0."},
        {"name": "HOST_BTA_RETURN",           "description": "Peripheral has issued its BTA; host re-acquires bus."},
        {"name": "HOST_INIT_DRIVE_LP11",      "description": "Power-on: host drives sustained LP-11 for T_INIT_MASTER."},
        {"name": "HOST_CONTENTION_RECOVERY",  "description": "Host detected LP Contention; LP TX → STOP; ErrContention; optional Reset Entry."},
    ])
    _force(d, "fsm_states_peripheral_protocol", [
        {"name": "PERIPH_RX_STOP",            "description": "Peripheral in LP-RX, all Lanes idle LP-11; waiting for SoT."},
        {"name": "PERIPH_RX_HS_PAYLOAD",      "description": "Peripheral receiving HS payload; parsing DI + WC + ECC + payload + Checksum."},
        {"name": "PERIPH_RX_EOTP_DETECT",     "description": "Peripheral detects EoTp Short Packet regardless of HS or LP transmission mode."},
        {"name": "PERIPH_ERROR_ACCUMULATE",   "description": "Peripheral updates internal 16-bit Error Register without clearing."},
        {"name": "PERIPH_BTA_ACQUIRED",       "description": "BTA received; peripheral now has bus possession; LTX-P_TO running."},
        {"name": "PERIPH_LP_TX_RESPONSE",     "description": "Peripheral transmits Acknowledge (0x21) or Acknowledge and Error Report (DT=0x02) or Read Response in LP."},
        {"name": "PERIPH_BTA_RETURN",         "description": "Peripheral hands bus back to host via own TurnRequest → BTA."},
        {"name": "PERIPH_TE_TX",              "description": "Command Mode peripheral sends LP Escape trigger byte 0x5D for Tearing Effect, then BTA."},
        {"name": "PERIPH_INIT_RX_STOP",       "description": "Peripheral powers up in RX-Stop, ignores all Link states for T_INIT_SLAVE."},
        {"name": "PERIPH_HS_RX_TIMEOUT",      "description": "HRX_TO expired during HS RX; peripheral transitions to LP-RX."},
        {"name": "PERIPH_RESET_RECEIVED",     "description": "Peripheral received Reset Entry command via LP Escape Mode; executes reset; PR_TO running."},
    ])
    # CSI-2 sets fsm_hints / anti_deadlock_rule / exit_from_reset_or_poweron /
    # default_ready_state_recommendation to camera-FSM text; DSI overwrites.
    _force(d, "fsm_hints", {
        "trigger":      "HS Entry begins when host drives LP-11 → LP-01 → LP-00 → HS payload. BTA begins when host asserts TurnRequest at the end of the last packet of a transmission. TE begins when host gives bus possession to peripheral without an accompanying DSI command.",
        "rule":         "Packet boundaries are determined by header DT + WC fields. EoTp (when enabled) provides a robust packet-stream terminator independent of D-PHY EoT. BTA uses LP Escape Mode only and is restricted to Data Lane 0.",
        "abort":        "Multi-bit ECC errors lose packet boundary for the rest of the transmission (per §8.9.5 / §9.5). HS RX Timeout expiry forces peripheral back to LP-RX. LP Contention triggers Annex A recovery flows (Cases 1/2/3).",
    })
    _force(d, "anti_deadlock_rule",
           "Required timers HRX_TO (HS RX Timeout, peripheral), HTX_TO (HS TX Timeout, host), LTX-P_TO (LP TX Peripheral Timeout), LRX-H_TO (LP RX Host Timeout) ensure the bus returns to LP-11 Stop state within bounded time after any transient fault. LRX-H_TO MUST be longer than LTX-P_TO so the peripheral has returned to LP-RX before host timer expires. Optional TA_TO (Turnaround Acknowledge Timeout) and PR_TO (Peripheral Reset Timeout) provide additional safety nets.")
    _force(d, "exit_from_reset_or_poweron",
           "Power-up sequence per §5.7: host's T_INIT_MASTER ≥ t_POR + T_INIT_SLAVE + T_INTERNAL_DELAY. Host drives LP-11 on all Lanes throughout T_INIT_MASTER. Peripheral powers up in RX-Stop, ignores all Link states until T_INIT_SLAVE elapses (R-C timer with ±30% accuracy is acceptable), then enters PERIPH_RX_STOP. Default Maximum Return Packet Size = 1 at this point.")
    _force(d, "default_ready_state_recommendation", {
        "Clock_Lane_idle": "LP-11 (Stop state) between HS bursts when Non-Continuous Clock Mode is selected; HS-0 in Continuous Clock Mode.",
        "Data_Lane_idle":  "LP-11 (Stop state) when host has bus possession and no traffic; LP-RX when peripheral has bus possession.",
    })
    d.setdefault("lane_states_table_inherited_from_d_phy", [
        {"state": "LP-00", "Dp": 0, "Dn": 0, "meaning": "Bridge state before HS / Escape entry"},
        {"state": "LP-01", "Dp": 0, "Dn": 1, "meaning": "HS Request"},
        {"state": "LP-10", "Dp": 1, "Dn": 0, "meaning": "Escape Request / LP Mark-One"},
        {"state": "LP-11", "Dp": 1, "Dn": 1, "meaning": "Stop state (idle)"},
        {"state": "HS-0",  "Dp": "diff-LOW",  "Dn": "diff-HIGH", "meaning": "HS differential 0"},
        {"state": "HS-1",  "Dp": "diff-HIGH", "Dn": "diff-LOW",  "meaning": "HS differential 1"},
    ])
    _force(d, "configurations", [
        {"name": "Continuous Clock Mode",     "description": "Clock Lane stays in HS continuously."},
        {"name": "Non-Continuous Clock Mode", "description": "Clock Lane returns to LP-11 between HS bursts."},
        {"name": "EoTp enabled",               "description": "EoTp Short Packet appended at end of every HS transmission."},
        {"name": "EoTp disabled",              "description": "Backward-compatible with v1.0 peripherals."},
    ])
    d.setdefault("timing_dependency_rule",
                 "Host drives Clock Lane DDR; peripheral DDR receiver uses both edges. Sync pattern byte-aligns the receiver. Inter-pair skew across N Data Lanes must remain bounded.")
    _write(p, d)


def _l7(gd: Path, ic_name: str) -> None:
    p = gd / "L7_TEST_DEBUG.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("test_debug_architecture_present", True)
    # CSI-2 observability is one-way streaming; DSI adds Ack-Error-Report + EoTp + TE.
    _force(d, "spec_provided_observability", [
        {"name": "Header ECC syndrome",       "purpose": "Hamming-modified (24,8) single-bit-correct + 2-bit-detect over DI + WC."},
        {"name": "Long Packet Checksum",       "purpose": "CRC-16 poly x^16+x^12+x^5+1, init 0xFFFF, LSB-first; payload coverage."},
        {"name": "Acknowledge and Error Report","purpose": "16-bit Error Report mask returned via Short Packet DT=0x02 after BTA."},
        {"name": "Acknowledge Trigger Message", "purpose": "Single-byte LP trigger 0x21 sent by peripheral when no errors stored."},
        {"name": "EoTp Short Packet (DT=0x08)", "purpose": "Robust end-of-HS-transmission marker; payload 0x0F0F + ECC 0x01."},
        {"name": "Sync Event Short Packets",    "purpose": "VSS/VSE/HSS/HSE (DT=0x01/0x11/0x21/0x31) convey display-timing events."},
        {"name": "Set Maximum Return Packet Size (0x37)", "purpose": "Host bounds peripheral read-response length."},
        {"name": "BTA (Bus Turn-Around)",       "purpose": "LP Escape Mode-based explicit ownership handover."},
        {"name": "Tearing Effect (TE) trigger 0x5D", "purpose": "LP Escape trigger from Command Mode peripheral; safe-to-write signal."},
    ])
    _force(d, "error_detection_mechanisms", [
        "Hamming-modified header ECC: single-bit correct / 2-bit detect.",
        "Payload CRC-16 on Long Packets; 0xFFFF for zero-length payload; 0x0000 from non-checksum peripheral.",
        "Acknowledge and Error Report Short Packet (DT=0x02 reverse) — 16-bit error mask.",
        "HRX_TO / HTX_TO / LTX-P_TO / LRX-H_TO contention-recovery timers.",
        "Optional TA_TO and PR_TO timers.",
        "LP-Contention detector (LP-CD on bidirectional Data Lane 0) per §7.2.1 + Annex A.",
    ])
    _force(d, "interrupt_or_event_sources", [
        {"event": "ECC single-bit corrected",     "trigger": "1-bit header error corrected; Error Report bit 8 set."},
        {"event": "ECC multi-bit detected",        "trigger": "2-bit header error; packet dropped; bit 9 set."},
        {"event": "Checksum error",                "trigger": "Long-Packet payload mismatch; bit 10 set."},
        {"event": "DSI Data Type Not Recognized", "trigger": "DT not defined / implemented; bit 11 set."},
        {"event": "DSI VC ID Invalid",             "trigger": "VC field not recognized; bit 12 set."},
        {"event": "Invalid Transmission Length",   "trigger": "WC mismatch; bit 13 set."},
        {"event": "DSI Protocol Violation",        "trigger": "Expected EoTp / BTA not received; bit 15 set."},
        {"event": "SoT Error",                     "trigger": "Bit 0 set."},
        {"event": "SoT Sync Error",                "trigger": "Bit 1 set."},
        {"event": "EoT Sync Error",                "trigger": "Bit 2 set."},
        {"event": "Escape Mode Entry Command Error","trigger": "Bit 3 set."},
        {"event": "Low-Power Transmit Sync Error", "trigger": "Bit 4 set."},
        {"event": "HS Receive Timeout Error",      "trigger": "HRX_TO expired; bit 5 set."},
        {"event": "False Control Error",           "trigger": "Bit 6 set."},
        {"event": "Tearing Effect (TE)",           "trigger": "Peripheral sends LP trigger 0x5D after BTA."},
        {"event": "LP Contention detected",        "trigger": "LP-CD asserts; Annex A recovery."},
    ])
    # CSI-2 sets error_clearing_rule / error_isolation_caveat / notes to
    # camera-protocol text; DSI overwrites.
    _force(d, "error_clearing_rule",
           "Errors shall be accumulated by the peripheral during single or multiple transmissions and only cleared after they have been reported back to the host. Errors are transmitted as part of an Acknowledge and Error Report Short Packet after the next BTA from the host.")
    _force(d, "error_isolation_caveat",
           "Since errors accumulate across multiple transmissions before the next BTA, the host may be unable to associate a particular error to the specific transmission causing it. If per-transmission error attribution is required, software shall send individual packets in separate transmissions, each followed by BTA.")
    _force(d, "notes",
           "DSI v1.01.00 inherits ECC + Checksum integrity machinery from CSI-2 / D-PHY but adds a peripheral-to-host reverse channel for explicit error reporting, plus the EoTp Short Packet as a protocol-layer end-marker independent of D-PHY EoT. The Tearing Effect trigger 0x5D is a DSI-only addition over CSI-2 — it replaces the dedicated TE pin of parallel DBI-2 interfaces with an in-band LP escape signaling sequence.")
    _write(p, d)


def _l8_rtl(gd: Path, ic_name: str) -> None:
    p = gd / "L8_RTL_CONSTANTS.json"
    if not p.is_file():
        return
    d = _read(p)
    # CSI-2 width_parameters has CSI-specific VC widths (v1_1 / v1_2_plus).
    # DSI v1.01 has fixed VC width = 2 bits. Force-overwrite.
    _force(d, "width_parameters", {
        "CLOCK_LANE_PAIRS": 1,
        "DATA_LANE_PAIRS_MIN": 1,
        "DATA_LANE_PAIRS_MAX": 4,
        "SHORT_PACKET_TOTAL_BYTES": 4,
        "LONG_PACKET_MIN_BYTES": 6,
        "LONG_PACKET_MAX_BYTES": 65541,
        "HEADER_TOTAL_BYTES": 4,
        "HEADER_DI_BYTES": 1,
        "HEADER_WC_BYTES": 2,
        "HEADER_ECC_BYTES": 1,
        "LONG_PACKET_FOOTER_BYTES": 2,
        "DI_FIELD_WIDTH_bits": 8,
        "VC_FIELD_WIDTH_bits": 2,
        "DT_FIELD_WIDTH_bits": 6,
        "WC_FIELD_WIDTH_bits": 16,
        "ECC_FIELD_WIDTH_bits": 8,
        "CRC_FIELD_WIDTH_bits": 16,
        "PACKET_HEADER_DATA_BITS_ECC_PROTECTED": 24,
        "ECC_PARITY_BITS_USED": 6,
        "ECC_PARITY_BITS_RESERVED": 2,
        "ERROR_REPORT_WIDTH_bits": 16,
        "MAX_VC_COUNT": 4,
        "MAX_PAYLOAD_BYTES_PER_LONG_PACKET": 65535,
    })
    # CSI-2 puts a CRC_polynomial_hex key (=0x1021, MSB-first).
    # DSI uses LSB-first form 0x8408 per Annex B — overwrite the key constants.
    _force(d, "key_constants_for_RTL_authoring", {
        "ECC_polynomial_class": "Hamming-modified (24,8) — single-bit correct + 2-bit detect.",
        "ECC_data_bits_protected": 24,
        "ECC_parity_bits_used": 6,
        "ECC_parity_bits_p6_p7": "Reserved, transmit as 0, receiver forces to 0 before processing.",
        "ECC_parity_table_first_8_rows": {
            "0": "0x07",
            "1": "0x0B",
            "2": "0x0D",
            "3": "0x0E",
            "4": "0x13",
            "5": "0x15",
            "6": "0x16",
            "7": "0x19",
        },
        "ECC_parity_table_note": "Full 24-row table is in DSI Spec §9.3 Table 22 (ECC Parity Generation Rules). The 64-entry syndrome decoder is in §9.3 Table 21 (ECC Syndrome Association Matrix).",
        "CRC_polynomial":              "x^16 + x^12 + x^5 + 1",
        "CRC_polynomial_hex_msb_first": "0x1021",
        "CRC_polynomial_hex_lsb_first_shift_form": "0x8408",
        "CRC_initial_value_hex": "0xFFFF",
        "CRC_shift_direction":  "LSB-first (per Annex B reference implementation)",
        "CRC_covers":           "Long Packet payload bytes only (NOT header).",
        "CRC_zero_payload_value_hex": "0xFFFF",
        "CRC_no_checksum_peripheral_value_hex": "0x0000",
        "is_packet_based": True,
        "is_streaming": True,
        "burst_based": True,
        "byte_oriented": True,
        "no_handshake_no_retry_on_payload": True,
        "is_source_synchronous": True,
        "data_lane_LSB_first_within_byte": True,
        "header_byte_order": "DI (byte 0), WC[7:0] (byte 1), WC[15:8] (byte 2), ECC (byte 3); LSB-first on the wire within byte; little-endian byte ordering over the wire.",
        "checksum_byte_order": "CRC[7:0] (CRC LS Byte) first, then CRC[15:8] (CRC MS Byte); LSB-first on the wire within byte.",
        "DDR_clock_lane": True,
        "data_rate_to_clock_rate_ratio": 2,
        "multilane_byte_interleave_rule": "byte k → lane (k mod N_data_lanes); byte 0 → Lane 0, byte 1 → Lane 1, ...",
    })
    _force(d, "eotp_short_packet_constants", {
        "DT_hex": "0x08",
        "VC": 0,
        "DI_byte_hex": "0x08",
        "payload_hex": "0x0F0F",
        "ECC_hex": "0x01",
        "applicability": "All HS transmissions when EoTp enabled; SHOULD NOT be sent for LP transmissions.",
    })
    _force(d, "te_trigger_byte", {
        "value_hex": "0x5D",
        "value_binary_first_to_last_bit": "01011101",
        "value_binary_on_the_wire_lsb_first": "10111010",
        "purpose": "Tearing Effect — Command Mode peripheral signals safe-to-write to host via LP Escape Mode trigger after BTA.",
    })
    _force(d, "acknowledge_trigger_message_byte", {
        "value_hex": "0x21",
        "value_binary_first_to_last_bit": "00100001",
        "purpose": "Acknowledge — peripheral confirms reception of a non-Read host transmission with no errors stored.",
    })
    _force(d, "error_report_bits", [
        {"bit":  0, "name": "SoT Error"},
        {"bit":  1, "name": "SoT Sync Error"},
        {"bit":  2, "name": "EoT Sync Error"},
        {"bit":  3, "name": "Escape Mode Entry Command Error"},
        {"bit":  4, "name": "Low-Power Transmit Sync Error"},
        {"bit":  5, "name": "HS Receive Timeout Error"},
        {"bit":  6, "name": "False Control Error"},
        {"bit":  7, "name": "Reserved (transmit as 0)"},
        {"bit":  8, "name": "ECC Error, single-bit (detected and corrected)"},
        {"bit":  9, "name": "ECC Error, multi-bit (detected, not corrected)"},
        {"bit": 10, "name": "Checksum Error (Long packet only)"},
        {"bit": 11, "name": "DSI Data Type Not Recognized"},
        {"bit": 12, "name": "DSI VC ID Invalid"},
        {"bit": 13, "name": "Invalid Transmission Length"},
        {"bit": 14, "name": "Reserved (transmit as 0)"},
        {"bit": 15, "name": "DSI Protocol Violation"},
    ])
    _force(d, "named_timers", [
        {"name": "T_INIT_MASTER",   "description": "Host minimum LP-11 TX-Stop drive at power-on; must be ≥ t_POR + T_INIT_SLAVE + T_INTERNAL_DELAY."},
        {"name": "T_INIT_SLAVE",    "description": "Peripheral minimum LP-11 RX-Stop monitor at power-on; R-C timer ±30% acceptable."},
        {"name": "HRX_TO",          "description": "HS RX Timeout — required in bidirectional peripheral."},
        {"name": "HTX_TO",          "description": "HS TX Timeout — required in host."},
        {"name": "LTX-P_TO",        "description": "LP TX-Peripheral Timeout — required in bidirectional peripheral."},
        {"name": "LRX-H_TO",        "description": "LP RX-Host Timeout — required in host; must be longer than LTX-P_TO."},
        {"name": "TA_TO",           "description": "Turnaround Acknowledge Timeout — optional."},
        {"name": "PR_TO",           "description": "Peripheral Reset Timeout — optional."},
    ])
    d.setdefault("default_signal_values_when_idle", {
        "Clock_Lane": "LP-11 in Non-Continuous Clock Mode; HS-0 in Continuous Clock Mode.",
        "Data_Lane":  "LP-11 — Stop state with host owning the bus.",
    })
    d.setdefault("default_max_return_packet_size_at_reset", 1)
    d.setdefault("host_lp_clock_vs_peripheral_lp_clock_ratio_pct_range", [67, 150])
    _write(p, d)


def _l8_timing(gd: Path, ic_name: str) -> None:
    p = gd / "L8_TIMING_WAVEFORM.json"
    if not p.is_file():
        return
    d = _read(p)
    # CSI-2's clock_waveform is unidirectional; DSI adds Clock-Lane host-only rule.
    if "Clock Lane is host → peripheral" not in (
            str(d.get("clock_waveform") or "")):
        _force(d, "clock_waveform", {
            "Clock_Lane_DDR":         "Host drives differential Clock Lane (Clock+ / Clock-). DDR — both edges latch one bit per Data Lane → data-rate-per-lane = 2 × Clock-Lane-Hz. Clock Lane is host → peripheral ONLY; peripheral never drives Clock Lane.",
            "HS_clock_swing_inherits": "D-PHY HS — 100-200 mV differential (sub-LVDS, 100 Ω terminated).",
            "Continuous_Clock_Mode":   "All DSI transmitters and receivers SHALL support Continuous Clock behavior.",
            "Non_Continuous_Clock_Mode":"Clock Lane returns to LP-11 between HS bursts; optional support.",
        })
    _force(d, "hs_entry_waveform_inherited_from_d_phy", {
        "step_1_stop":     "LP-11 on both Dp and Dn (Stop state).",
        "step_2_request":  "LP-01 for T-LPX.",
        "step_3_bridge":   "LP-00 for T-LPX.",
        "step_4_prepare":  "HS-0 for T-HS-PREPARE.",
        "step_5_zero":     "Continue HS-0 for T-HS-ZERO.",
        "step_6_sync":     "Transmit 8'b00011101 Sync (LSB-first on wire = 10111000).",
        "step_7_payload":  "Stream DSI packet bytes; byte k → lane (k mod N).",
        "step_8_eotp":     "(Optional) Append EoTp Short Packet DI=0x08, payload=0x0F0F, ECC=0x01.",
        "step_9_trail":    "Hold last bit for T-HS-TRAIL.",
        "step_10_exit":    "LP-11 (Stop state) returns.",
    })
    _force(d, "bta_waveform", {
        "step_1_host_lp11":    "Host finished last packet; both Lanes LP-11.",
        "step_2_host_request": "Host PHY drives BTA escape sequence on Data Lane 0.",
        "step_3_peripheral_takes_bus": "Peripheral takes bus; sends ACK / Error Report / Read Response in LP.",
        "step_4_peripheral_returns_bus": "Peripheral PHY drives BTA escape sequence back.",
        "step_5_host_resumes": "Host returns to LP-11 Stop state.",
    })
    _force(d, "te_signaling_waveform", {
        "step_1_setup":       "Host gives bus possession to peripheral via BTA WITHOUT accompanying DSI command.",
        "step_2_te_event":    "Display module detects TE event.",
        "step_3_te_send":     "Display module sends LP Escape Mode sequence + trigger message byte 0x5D (LSB-first 10111010).",
        "step_4_bta_return":  "Display module returns bus possession to host via BTA.",
    })
    _force(d, "powerup_waveform", {
        "step_1_external_vdd":  "External VDD ramps.",
        "step_2_io_voltage":     "I/O voltage stable.",
        "step_3_core_voltage":   "Core voltage stable.",
        "step_4_por_release":    "POR de-asserts after t_POR.",
        "step_5_rx_sm_active":   "Peripheral Rx SM active; T_INIT_SLAVE timer begins.",
        "step_6_host_lp11_drive": "Host drives LP-11 throughout T_INIT_MASTER ≥ t_POR + T_INIT_SLAVE + T_INTERNAL_DELAY.",
        "step_7_clock_active":   "Host Clock Lane LP-11 → HS-0 → DDR waveform begins.",
        "step_8_data_active":    "Host Data Lanes LP-11 → HS at first burst.",
    })
    _force(d, "video_mode_timing_legend", {
        "VSS": "DSI Sync Event Packet: V Sync Start (DT=0x01)",
        "VSE": "DSI Sync Event Packet: V Sync End (DT=0x11)",
        "BLLP":"DSI Packet: non-restricted DSI packets or Low Power Mode incl. optional BTA",
        "HSS": "DSI Sync Event Packet: H Sync Start (DT=0x21)",
        "HSA": "DSI Blanking Packet: Horizontal Sync Active",
        "HSE": "DSI Sync Event Packet: H Sync End (DT=0x31)",
        "HFP": "DSI Blanking Packet: Horizontal Front Porch or LP",
        "HBP": "DSI Blanking Packet: Horizontal Back Porch or LP",
        "RGB": "DSI Packet: pixel-stream and Null Packets",
        "LPM": "Low Power Mode incl. optional BTA",
    })
    _force(d, "video_mode_sequences", {
        "non_burst_with_sync_pulses": "VSA(VSS+BLLP+VSE) ... VBP(HSS+BLLP) ... VACT(HSS+HSA+HSE+HBP+RGB+HFP) ... VFP(HSS+BLLP).",
        "non_burst_with_sync_events": "VSA(VSS+BLLP) ... VBP(HSS+BLLP) ... VACT(HSS+HBP+RGB+HFP) ... VFP(HSS+BLLP).",
        "burst_mode":                 "VSA(VSS+BLLP) ... VACT(HSS+HBP+RGB+BLLP+HFP) ... — time-compressed RGB.",
    })
    _force(d, "video_mode_named_timing_parameters_from_table_20", [
        {"parameter": "brPHY",  "description": "Bit rate total on all Lanes",   "units": "Mbps",   "comment": "Depends on PHY implementation"},
        {"parameter": "tL",     "description": "Line time",                      "units": "us",     "comment": "Define range to meet frame rate"},
        {"parameter": "tHSA",   "description": "Horizontal sync active",         "units": "us",     "comment": ""},
        {"parameter": "tHBP",   "description": "Horizontal back porch",          "units": "us",     "comment": ""},
        {"parameter": "tHACT",  "description": "Time for image data",            "units": "us",     "comment": "Defining min = 0 allows max PHY speed"},
        {"parameter": "HACT",   "description": "Active pixels per line",         "units": "pixels", "comment": ""},
        {"parameter": "tHFP",   "description": "Horizontal front porch",         "units": "us",     "comment": "No upper limit as long as line time is met"},
        {"parameter": "VSA",    "description": "Vertical sync active",           "units": "lines",  "comment": "Lines in vertical sync area"},
        {"parameter": "VBP",    "description": "Vertical back porch",            "units": "lines",  "comment": ""},
        {"parameter": "VACT",   "description": "Active lines per frame",         "units": "lines",  "comment": ""},
        {"parameter": "VFP",    "description": "Vertical front porch",           "units": "lines",  "comment": ""},
    ])
    # ABSENT in CSI-2 — DSI fills in escape-entry + data-signaling waveform
    # inherits.
    d.setdefault("escape_entry_waveform_inherited_from_d_phy", {
        "step_1_stop":             "LP-11.",
        "step_2_request":          "LP-10 (Dp HIGH, Dn LOW) for T-LPX.",
        "step_3_bridge":           "LP-00 for T-LPX.",
        "step_4_escape_pattern":   "Transmit Escape Entry command + payload (LPDT data, Trigger code, or Reset code) at LP rate.",
        "step_5_exit":             "LP-11 to return to Stop.",
    })
    d.setdefault("data_signaling_waveforms_inherited", {
        "HS_0": "differential 0 (Dn HIGH, Dp LOW)",
        "HS_1": "differential 1 (Dp HIGH, Dn LOW)",
        "LP_11": "Stop state — Dp and Dn at 1.2 V CMOS HIGH",
        "LP_01": "HS Request — Dp LOW, Dn HIGH",
        "LP_10": "Escape Request / Mark-One — Dp HIGH, Dn LOW",
        "LP_00": "Bridge / Escape — both LOW",
    })
    # If CSI-2 set payload_byte_serialization without checksum_byte_order, fill it.
    _pbs = d.get("payload_byte_serialization")
    if isinstance(_pbs, dict):
        _pbs.setdefault("format",
                        "Each byte transmitted LSB-first on the wire (bit 0 first, bit 7 last).")
        _pbs.setdefault("header_byte_order",
                        "DI (byte 0), WC LS Byte (byte 1), WC MS Byte (byte 2), ECC (byte 3).")
        _pbs.setdefault("checksum_byte_order",
                        "CRC LS Byte first, then CRC MS Byte.")
        _pbs.setdefault("multilane_interleave",
                        "With N Lanes: byte k → lane (k mod N); SoT replicated on every active Lane; some Lanes may EoT one byte earlier than others when WC not multiple of N.")
    else:
        d["payload_byte_serialization"] = {
            "format":              "Each byte transmitted LSB-first on the wire (bit 0 first, bit 7 last).",
            "header_byte_order":   "DI (byte 0), WC LS Byte (byte 1), WC MS Byte (byte 2), ECC (byte 3).",
            "checksum_byte_order": "CRC LS Byte first, then CRC MS Byte.",
            "multilane_interleave":"With N Lanes: byte k → lane (k mod N); SoT replicated on every active Lane; some Lanes may EoT one byte earlier than others when WC not multiple of N.",
        }
    # CSI-2 set general_timing_rule to camera text; DSI overwrites.
    _force(d, "general_timing_rule",
           "All HS payload bit timings derive from UI = 1 / data-rate-per-lane = 1 / (2 × Clock-Lane Hz). DDR clock: both edges of Clock+/Clock- latch one Data-Lane bit. Detailed numeric T-LPX / T-HS-PREPARE / T-HS-ZERO / T-HS-TRAIL bounds inherit from D-PHY v0.90.00 specification, referenced as [4] in DSI §3.5.")
    _write(p, d)


def _l9(gd: Path, ic_name: str) -> None:
    p = gd / "L9_INTEGRATION_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    # CSI-2 module_role is camera; DSI replaces with display protocol stack.
    _force(d, "module_role",
           "Packet-based serial display interface stack inside a SoC, layered as Application → Low Level Protocol → Lane Management → PHY (per DSI §4.1). Provides the wire-level transport for both Video Mode pixel streaming (DPI-2-like) and Command Mode command/parameter delivery (DBI-2-like + DCS).")
    _force(d, "integration_overview", {
        "wire_count":          "2 + 2 × N_data_lanes (N=1..4); 4..10 pins.",
        "wire_directions":     "Clock Lane host → peripheral only; Data Lane 0 bidirectional in LP for Command Mode; additional Data Lanes 1..3 host → peripheral only.",
        "no_chip_select":      "No CS line; point-to-point pair with VC[1:0] for up to 4 logical channels.",
        "no_addressing_at_dsi_layer":"DSI Protocol Layer does not address a register file; DCS commands carry vendor/standardized command codes inside DSI 0x05/0x15/0x06/0x39 packets.",
        "controller_choices":  "Host is always Clock Lane driver and dominant HS payload source. Peripheral drives LP only on Data Lane 0.",
        "handshake":           "BTA (Bus Turn-Around) provides explicit ownership handover for reverse-direction Acknowledge / Error Report / Read Response / TE.",
    })
    _force(d, "layer_stack", [
        {"layer": "PHY Layer",                       "responsibilities": ["Start-of-Packet / End-of-Packet (D-PHY SoT / EoT)", "Serializer / Deserializer", "Clock Management (DDR)", "Electrical Layer (sub-LVDS)"]},
        {"layer": "Lane Management Layer",           "responsibilities": ["Lane Distribution (Distributor on TX)", "Lane Merging (Merger on RX)", "1..4 Lane scaling"]},
        {"layer": "Low Level Protocol Layer",        "responsibilities": ["Packet-Based Protocol", "ECC Generation/Testing", "Checksum Generation/Testing"]},
        {"layer": "Application Layer",               "responsibilities": ["Pixel-to-Byte Packing Formats (RGB565/RGB666 Packed/RGB666 Loosely Packed/RGB888)", "Command Generation/Interpretation (DCS)"]},
    ])
    _force(d, "interface_categories", [
        "Host D-PHY transmitter on Clock Lane + Data Lanes 0..N-1.",
        "Peripheral D-PHY receiver on Clock Lane + Data Lanes.",
        "Host Lane Distribution / Merging block.",
        "DSI Protocol Layer — header builder + ECC; payload builder + CRC; EoTp generator/detector; BTA controller; Error Register accumulator.",
        "Application interface — Pixel-to-Byte Packing block; Command Generation/Interpretation block; Tearing Effect controller.",
    ])
    _force(d, "interconnect_topologies_supported", [
        "Point-to-point — host ↔ one peripheral per physical DSI Link (normative scope).",
        "Multi-peripheral via Virtual Channel (informative).",
    ])
    # CSI-2 set default_signal_values_when_omitted to camera text; DSI overwrites.
    _force(d, "default_signal_values_when_omitted",
           "All Lanes idle LP-11 (Stop state) between transmissions; peripheral in LP-RX until host begins HS Entry; peripheral's Maximum Return Packet Size defaults to 1 byte at power-on / reset.")
    _force(d, "soc_dependent_items", [
        "Number of Data Lanes (1..4).",
        "Clock-Lane mode: Continuous vs Non-Continuous.",
        "Operating mode: Command Mode and/or Video Mode.",
        "Video Mode packet sequence: Non-Burst Sync Pulses / Non-Burst Sync Events / Burst.",
        "Pixel format: 16-bpp RGB565 / 18-bpp RGB666 Packed / 18-bpp RGB666 Loosely Packed / 24-bpp RGB888.",
        "EoTp enable / disable.",
        "Bidirectional support on Data Lane 0 (mandatory in Command Mode, optional in Video Mode).",
        "PLL providing Clock Lane DDR frequency on host; CDR on peripheral.",
        "ESD protection on differential pairs.",
        "Vendor sideband (backlight, panel-reset GPIOs) outside DSI scope.",
    ])
    # CSI-2 may have populated pcb_integration_constraints_inherited_from_d_phy
    # with abridged values; DSI force-overwrites with the canonical DSI text.
    _force(d, "pcb_integration_constraints_inherited_from_d_phy", {
        "differential_pair_impedance_ohm": 100,
        "intra_pair_skew_ps_max":          5,
        "inter_pair_skew_ps_max":          100,
        "max_trace_length_cm":             "≤ 30 cm at sub-Gbps rates; shorter at higher rates (per D-PHY).",
        "AC_coupling":                     "NOT used — D-PHY is DC-coupled differential.",
        "ESD_protection_class":            "HBM 2 kV minimum (Class 2).",
    })
    _force(d, "low_power_modes", {
        "Stop_state":           "LP-11 between bursts — minimal current.",
        "ULPS":                 "Ultra-Low Power State — LP-00 indefinitely.",
        "Non_Continuous_Clock": "Clock Lane returns to LP-11 between bursts.",
        "BLLP_LP_substitution": "Video Mode HBP/HFP intervals can substitute LP for Blanking Packets.",
    })
    _force(d, "typical_use_cases", [
        "Mobile-phone primary display (LCD or OLED).",
        "Tablet display panel link.",
        "Video Mode handheld display without on-panel frame buffer.",
        "Command Mode display with on-panel frame buffer.",
        "Multi-peripheral panel via VC (informative).",
    ])
    _write(p, d)


def _l10(gd: Path, ic_name: str) -> None:
    p = gd / "L10_TEST_CASES.json"
    if not p.is_file():
        return
    d = _read(p)
    # CSI-2 set test_cases_present; DSI overwrites.
    _force(d, "test_cases_present",
           "partial — DSI v1.01.00 defines detailed compliance behaviors (packet formats, ECC + Checksum algorithms, BTA, EoTp, Tearing Effect, video timing) and the Acknowledge-and-Error-Report mechanism, but is not a self-contained testbench; the formal conformance suite is operated by MIPI Alliance.")
    if not d.get("derived_compliance_test_categories"):
        d["derived_compliance_test_categories"] = []
    extra = [
        "EoTp Short Packet (DT=0x08, payload=0x0F0F, ECC=0x01, VC=0) — verify HS detection regardless of HS/LP transmission; verify NOT sent in LP.",
        "EoTp enable/disable interoperability with DSI v1.0 peripherals.",
        "Short Packet decode: DI + Data0 + Data1 + ECC = 4 bytes; verify all processor-sourced and peripheral-sourced Data Types.",
        "Long Packet decode: 6..65541 bytes; DI + WC + ECC + payload + 2-byte Checksum.",
        "Header ECC: Hamming-modified (24,8); verify single-bit correction + 2-bit detection; verify P6 and P7 = 0.",
        "Annex B Long Packet Checksum test vectors: gpcTestData0 → 0x0F87; gpcTestData1 → 0x1E0E; gpcTestData2 → 0xE569; gpcTestData3 → 0x00F0.",
        "Zero-payload Long Packet Footer = 0xFFFF; non-checksum-peripheral Footer = 0x0000.",
        "Video Mode Non-Burst with Sync Pulses (§8.11.2).",
        "Video Mode Non-Burst with Sync Events (§8.11.3).",
        "Video Mode Burst (§8.11.4) — verify LP transition in BLLP.",
        "Video Mode pixel formats — host implements all four (0x0E/0x1E/0x2E/0x3E); peripheral implements at least one.",
        "Command Mode DCS: 0x05 / 0x15 / 0x06 / 0x39 / 0x21 / 0x22 / 0x1C.",
        "Generic Short/Long: 0x03/0x13/0x23/0x04/0x14/0x24/0x29 + 0x11/0x12/0x1A.",
        "Sync Event packets: 0x01 / 0x11 / 0x21 / 0x31.",
        "Display control: 0x02 / 0x12 / 0x22 / 0x32 / 0x37.",
        "Null Packet (0x09) and Blanking Packet (0x19).",
        "BTA flow: host TurnRequest → BTA → peripheral takes bus → response → peripheral BTA → host.",
        "Acknowledge Trigger Message: peripheral sends single byte 0x21 after non-Read no-error.",
        "Acknowledge and Error Report (DT=0x02 reverse): all 16 bits map to correct conditions.",
        "Error accumulation + clearing: errors accumulate until BTA; cleared on report.",
        "Multi-bit ECC on any command: peripheral sends ONLY Acknowledge and Error Report (no read data).",
        "Single-bit ECC on Read: peripheral sends Read Response + Acknowledge and Error Report in same LP transmission.",
        "Tearing Effect: BTA-without-command → peripheral LP Escape trigger byte 0x5D → BTA back.",
        "Set Maximum Return Packet Size default = 1 at power-on.",
        "Contention recovery (Annex A): Cases 1 / 2 / 3.",
        "Required timers: HRX_TO, HTX_TO, LTX-P_TO, LRX-H_TO; verify LRX-H_TO > LTX-P_TO.",
        "Reserved DT codes (DT[3:0] = 0b0000 or 0b1111) shall NOT be used.",
        "Endian: LSB-first within byte; multi-byte fields LS byte first.",
        "Display Resolution interoperability per Table 23.",
        "Power-up T_INIT sequencing per §5.7.",
    ]
    # Append only items not already present.
    existing = set(d["derived_compliance_test_categories"])
    for item in extra:
        if item not in existing:
            d["derived_compliance_test_categories"].append(item)
    _write(p, d)


def _l11(gd: Path, ic_name: str) -> None:
    p = gd / "L11_OTP_CONTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("otp_present", False)
    d.setdefault("notes",
                 "MIPI DSI v1.01.00 does NOT define OTP / fuse content at the protocol or PHY layer. Vendor-specific calibration constants (skew trim, HS swing trim, PLL trim, EoTp default) may live in implementation-specific OTP but are out of normative DSI scope.")
    _write(p, d)


def _l12(gd: Path, ic_name: str) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    # CSI-2 frame_transmit_sequence is camera-FS/FE; DSI replaces.
    _force(d, "powerup_sequence", [
        "1. Power applied — t_POR elapses while host POR is asserted.",
        "2. Host drives sustained LP-11 TX-Stop for T_INIT_MASTER ≥ t_POR + T_INIT_SLAVE + T_INTERNAL_DELAY.",
        "3. Peripheral powers up in RX-Stop and ignores Link until T_INIT_SLAVE elapses.",
        "4. Peripheral T_INIT_SLAVE expires; Rx state machine active; T_INTERNAL_DELAY may follow.",
        "5. Maximum Return Packet Size initialized to default 1.",
        "6. Host issues Set Maximum Return Packet Size (0x37).",
        "7. Host issues Turn On Peripheral (0x32).",
        "8. Host begins normal Video Mode or Command Mode operation.",
    ])
    _force(d, "command_mode_write_sequence", [
        "1. Host LP-11 idle.",
        "2. Host issues HS Entry.",
        "3. Host transmits DCS Short Write Short Packet (DT=0x05 or 0x15) + DCS Command Byte + parameter + ECC.",
        "4. (Optional) Host appends EoTp Short Packet.",
        "5. Host issues HS Exit.",
        "6. (Optional) Host asserts TurnRequest → BTA; peripheral responds with ACK (0x21) or Error Report.",
        "7. Host returns to LP-11.",
    ])
    _force(d, "command_mode_read_sequence", [
        "1. Host issues DCS Read Short Packet (DT=0x06) in HS mode.",
        "2. Host asserts TurnRequest → BTA escape.",
        "3. Peripheral takes bus; transmits in LP.",
        "4. No error: Read Response (DT=0x21 or 0x22 or 0x1C).",
        "5. Single-bit ECC error: Read Response + Acknowledge and Error Report in same LP transmission.",
        "6. Multi-bit ECC error: ONLY Acknowledge and Error Report (no read data).",
        "7. Peripheral BTA → host re-acquires.",
        "8. Host LP-11.",
    ])
    _force(d, "video_mode_frame_sequence_non_burst_sync_pulses", [
        "1. Host LP-11 idle, HS Entry.",
        "2. VSA lines: VSS (0x01) + BLLP + VSE (0x11).",
        "3. VBP lines: HSS (0x21) + BLLP.",
        "4. VACT lines: HSS + HSA (Blanking 0x19) + HSE (0x31) + HBP + RGB (0x0E/0x1E/0x2E/0x3E) + HFP.",
        "5. VFP lines: HSS + BLLP.",
        "6. HS Exit → LP-11 → next frame.",
    ])
    _force(d, "video_mode_frame_sequence_burst", [
        "1. Host LP-11 idle, HS Entry.",
        "2. VACT lines: HSS + HBP + RGB (time-compressed) + BLLP + HFP.",
        "3. Burst Mode frees time for LP transition or other transmissions.",
        "4. HS Exit → LP-11.",
    ])
    _force(d, "tearing_effect_sequence", [
        "1. Host previously issued set_tear_on or set_tear_scanline DCS command.",
        "2. Host gives bus to peripheral via BTA WITHOUT command.",
        "3. Peripheral waits for TE event.",
        "4. TE event → peripheral sends LP Escape + trigger byte 0x5D (LSB-first 10111010).",
        "5. Peripheral returns bus via BTA.",
        "6. Host may write next frame.",
    ])
    _force(d, "bta_sequence", [
        "1. Host asserts TurnRequest just before EoT of last packet.",
        "2. Host PHY drives BTA on Data Lane 0.",
        "3. Peripheral PHY recognizes; peripheral asserts internal TurnRequest.",
        "4. Peripheral transmits LP response packets.",
        "5. Peripheral asserts own TurnRequest after last response.",
        "6. Peripheral PHY drives BTA back.",
        "7. Host re-acquires; both ends LP-11.",
    ])
    d.setdefault("ecc_recovery_sequence", [
        "1. Receiver computes Hamming-modified parity over DI + WC LS + WC MS.",
        "2. XOR with received ECC[5:0] → 6-bit syndrome.",
        "3. Syndrome = 0: clean.",
        "4. Single-bit syndrome match: correct bit; set Error Report bit 8.",
        "5. Multi-bit syndrome: set bit 9; drop packet + rest of transmission.",
    ])
    d.setdefault("checksum_recovery_sequence", [
        "1. CRC register init 0xFFFF.",
        "2. For each payload byte LSB-first: shift through poly 0x8408.",
        "3. Compare with 2-byte Footer (CRC LS first then CRC MS).",
        "4. Mismatch: Error Report bit 10.",
    ])
    d.setdefault("contention_recovery_sequence", [
        "Case 1 — Both sides initially detect: both → LP TX STOP → wait → optional Reset.",
        "Case 2 — Only host detects: host → LP TX STOP → ErrContention → Engine Wait Timeout.",
        "Case 3 — Only peripheral detects: peripheral → LP-RX → wait LP-11 from host.",
    ])
    d.setdefault("powerdown_or_shutdown_sequence", [
        "1. Host completes any in-flight transmission.",
        "2. Host issues Shutdown Peripheral (0x22).",
        "3. Peripheral turns off display; interface stays powered.",
        "4. Host issues Turn On Peripheral (0x32) to wake.",
    ])
    _write(p, d)


def _l13(gd: Path, ic_name: str) -> None:
    p = gd / "L13_LAB_CALIBRATION.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("lab_calibration_present", True)
    d.setdefault("calibration_categories", [
        {"name": "Eye diagram (HS pair)", "purpose": "Inherited from D-PHY."},
        {"name": "HS swing trim",          "purpose": "Inherited from D-PHY."},
        {"name": "Lane delay-line trim",   "purpose": "Inherited from D-PHY."},
        {"name": "Clock-Lane PLL lock",    "purpose": "Host PLL hits DDR target."},
        {"name": "Host vs Peripheral LP clock ratio","purpose": "67%..150% band per §5.6.1."},
        {"name": "T_INIT_MASTER vs t_POR + T_INIT_SLAVE + T_INTERNAL_DELAY","purpose": "Verify host's T_INIT_MASTER programmed long enough."},
        {"name": "EoTp enable/disable mechanism", "purpose": "Verify means exists for backward compatibility."},
        {"name": "ECC self-check",         "purpose": "Inject 1-bit / 2-bit header errors; verify Error Report bits 8/9."},
        {"name": "Checksum self-check",    "purpose": "Annex B vectors (gpcTestData0..3 → 0x0F87 / 0x1E0E / 0xE569 / 0x00F0)."},
        {"name": "BTA timing",              "purpose": "Verify BTA completes; TA_TO if implemented."},
        {"name": "HRX_TO / HTX_TO / LTX-P_TO / LRX-H_TO","purpose": "Configure + verify LRX-H_TO > LTX-P_TO."},
        {"name": "TE wait window",          "purpose": "Verify ≈ one video frame period after BTA-without-command."},
        {"name": "Set Maximum Return Packet Size","purpose": "Default 1 at reset; 0x37 takes effect."},
    ])
    d.setdefault("compliance_test_inputs_from_annex_b", [
        {"name": "gpcTestData0", "bytes_hex": ["0x00"], "expected_crc16_hex": "0x0F87"},
        {"name": "gpcTestData1", "bytes_hex": ["0x01"], "expected_crc16_hex": "0x1E0E"},
        {"name": "gpcTestData2",
         "bytes_hex": ["0xFF","0x00","0x00","0x00","0x1E","0xF0","0x1E","0xC7","0x4F","0x82","0x78","0xC5","0x82","0xE0","0x8C","0x70","0xD2","0x3C","0x78","0xE9","0xFF","0x00","0x00","0x01"],
         "expected_crc16_hex": "0xE569"},
        {"name": "gpcTestData3",
         "bytes_hex": ["0xFF","0x00","0x00","0x02","0xB9","0xDC","0xF3","0x72","0xBB","0xD4","0xB8","0x5A","0xC8","0x75","0xC2","0x7C","0x81","0xF8","0x05","0xDF","0xFF","0x00","0x00","0x01"],
         "expected_crc16_hex": "0x00F0"},
    ])
    # CSI-2 set notes to camera-PHY text; DSI overwrites.
    _force(d, "notes",
           "MIPI DSI v1.01.00 inherits all PHY-level lab characterization from D-PHY v0.90.00 (eye, swing, skew, PLL). Above the PHY, DSI-specific calibration centers on (a) verifying T_INIT power-up timing, (b) EoTp enable/disable interoperability, (c) BTA + contention-recovery timers, (d) TE wait period, and (e) Set Maximum Return Packet Size default. Annex B of the spec provides four reference CRC-16 test vectors with expected outputs that are the canonical regression inputs for any DSI receiver's checksum verifier.")
    _write(p, d)


def _l14(gd: Path, ic_name: str) -> None:
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    _force(f, "spec_version",
           "MIPI DSI v1.01.00 (21-Feb-2008, MIPI Board Approved 18-Jun-2008)")
    f.setdefault("previous_versions", [
        "DSI v1.0 — earlier release; did NOT support EoTp Short Packet.",
    ])
    f.setdefault("key_changes_in_v1_01", [
        {"version": "DSI v1.01.00",
         "summary": "Added EoTp Short Packet (DT=0x08, payload 0x0F0F, ECC 0x01) as protocol-layer end-of-HS marker."},
        {"version": "DSI v1.01.00",
         "summary": "Aligned with D-PHY v0.90.00 (8-Oct-2007), DBI-2 v2.00, DPI-2 v2.00, DCS v1.02.00."},
    ])
    f.setdefault("referenced_external_specifications", [
        {"id": "[1]", "spec": "MIPI Alliance Specification for Display Command Set (DCS), version 1.02.00."},
        {"id": "[2]", "spec": "MIPI Alliance Standard for Display Bus Interface (DBI-2), version 2.00, 29 Nov 2005."},
        {"id": "[3]", "spec": "MIPI Alliance Standard for Display Pixel Interface (DPI-2), version 2.00, 15 Sep 2005."},
        {"id": "[4]", "spec": "MIPI Alliance Specification for D-PHY, version 0.90.00, 8 Oct 2007."},
    ])
    # CSI-2 synth puts CSI/DPHY/CPHY backward_compat_traps; DSI replaces with
    # DSI-specific traps (EoTp v1.0 / LP-no-EoTp / zero-payload Checksum / TE 0x5D / etc.).
    _force(f, "backward_compat_traps", [
        {"trap_name": "eotp_v1_0_no_support",
         "rule": "DSI v1.0 devices do NOT support EoTp; v1.01 devices SHALL provide enable/disable.",
         "trap": "Always-on EoTp + v1.0 peripheral → DSI DT Not Recognized + lost packet boundary."},
        {"trap_name": "eotp_lp_mode_send",
         "rule": "EoTp SHOULD NOT be sent in LP mode.",
         "trap": "LP EoTp → DSI Protocol Violation or DT Not Recognized."},
        {"trap_name": "checksum_value_for_zero_payload",
         "rule": "Zero-byte payload Footer SHALL be 0xFFFF.",
         "trap": "Emitting 0x0000 → Checksum Error on any v1.01 receiver."},
        {"trap_name": "checksum_value_for_non_checksum_peripheral",
         "rule": "Non-checksum peripheral SHALL transmit 0x0000 in Footer.",
         "trap": "Receiver must disable Checksum check for such peripheral."},
        {"trap_name": "vc_field_only_2_bits",
         "rule": "DSI v1.01.00 VC field is 2 bits (DI[7:6]); supports up to 4 VCs.",
         "trap": "Confusion with CSI-2 v1.2+ widened VC; DSI v1.01.00 has NO VC extension."},
        {"trap_name": "ecc_p6_p7_unused",
         "rule": "P6/P7 of ECC byte SHALL be 0 by transmitter; receiver ignores and forces to 0.",
         "trap": "Receivers including P6/P7 in syndrome mis-decode every header."},
        {"trap_name": "te_trigger_byte_reserved",
         "rule": "Trigger byte 0x5D is reserved for Tearing Effect only.",
         "trap": "Vendor overload breaks interoperability."},
        {"trap_name": "lp_clock_ratio_3_to_2",
         "rule": "Host LP clock 67%..150% of peripheral.",
         "trap": "Outside band → BTA handshake fails."},
        {"trap_name": "lrx_h_to_ordering",
         "rule": "LRX-H_TO MUST be longer than LTX-P_TO.",
         "trap": "Reversed → host times out before peripheral hands back bus."},
        {"trap_name": "dt_lsb_zero_or_one_reserved",
         "rule": "DT[3:0] = 0b0000 or 0b1111 SHALL NOT be used.",
         "trap": "Vendor custom DT must avoid these patterns."},
    ])
    # CSI-2 set version_naming_history_note via fields; DSI overwrites.
    _force(f, "version_naming_history_note",
           "MIPI Alliance maintains the DSI Display Serial Interface specification, the DCS Display Command Set, the DBI-2 / DPI-2 parallel display interfaces it supersedes, and the D-PHY physical layer specification. DSI v1.01.00 (Feb 2008) is the first revision to include EoTp. Subsequent DSI releases (v1.02 onward, v1.3, v2.x) — not covered by this document — added more pixel formats, higher data rates aligned with later D-PHY revisions, and additional command types.")
    _write(p, d)


def _l15(gd: Path, ic_name: str) -> None:
    p = gd / "L15_ENCODING_TABLES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f.setdefault("data_identifier_byte_encoding", {
        "header_columns": ["Bit", "Field", "Description"],
        "rows": [
            ["7:6", "VC (Virtual Channel)", "0..3 — multiple peripherals or logical streams"],
            ["5:0", "DT (Data Type)",       "Enumerates packet category and pixel/command format"],
        ],
    })
    f.setdefault("processor_sourced_data_type_table_16", {
        "header_columns": ["Data Type (hex)", "Data Type (binary)", "Description", "Packet Size"],
        "rows": [
            ["0x01", "00 0001", "Sync Event, V Sync Start",     "Short"],
            ["0x11", "01 0001", "Sync Event, V Sync End",       "Short"],
            ["0x21", "10 0001", "Sync Event, H Sync Start",     "Short"],
            ["0x31", "11 0001", "Sync Event, H Sync End",       "Short"],
            ["0x08", "00 1000", "EoTp",                          "Short"],
            ["0x02", "00 0010", "Color Mode Off",                "Short"],
            ["0x12", "01 0010", "Color Mode On",                 "Short"],
            ["0x22", "10 0010", "Shutdown Peripheral",            "Short"],
            ["0x32", "11 0010", "Turn On Peripheral",             "Short"],
            ["0x03", "00 0011", "Generic Short WRITE 0 param",    "Short"],
            ["0x13", "01 0011", "Generic Short WRITE 1 param",    "Short"],
            ["0x23", "10 0011", "Generic Short WRITE 2 param",    "Short"],
            ["0x04", "00 0100", "Generic READ 0 param",           "Short"],
            ["0x14", "01 0100", "Generic READ 1 param",           "Short"],
            ["0x24", "10 0100", "Generic READ 2 param",           "Short"],
            ["0x05", "00 0101", "DCS Short WRITE 0 param",        "Short"],
            ["0x15", "01 0101", "DCS Short WRITE 1 param",        "Short"],
            ["0x06", "00 0110", "DCS READ 0 param",               "Short"],
            ["0x37", "11 0111", "Set Maximum Return Packet Size", "Short"],
            ["0x09", "00 1001", "Null Packet",                    "Long"],
            ["0x19", "01 1001", "Blanking Packet",                "Long"],
            ["0x29", "10 1001", "Generic Long Write",             "Long"],
            ["0x39", "11 1001", "DCS Long Write / write_LUT",     "Long"],
            ["0x0E", "00 1110", "Packed Pixel Stream 16-bit RGB565", "Long"],
            ["0x1E", "01 1110", "Packed Pixel Stream 18-bit RGB666 Packed", "Long"],
            ["0x2E", "10 1110", "Loosely Packed Pixel Stream 18-bit RGB666", "Long"],
            ["0x3E", "11 1110", "Packed Pixel Stream 24-bit RGB888", "Long"],
        ],
    })
    f.setdefault("peripheral_sourced_data_type_table_19", {
        "header_columns": ["Data Type (hex)", "Data Type (binary)", "Description", "Packet Size"],
        "rows": [
            ["0x02", "00 0010", "Acknowledge and Error Report",   "Short"],
            ["0x08", "00 1000", "EoTp",                            "Short"],
            ["0x11", "01 0001", "Generic Short READ Response 1 byte", "Short"],
            ["0x12", "01 0010", "Generic Short READ Response 2 bytes","Short"],
            ["0x1A", "01 1010", "Generic Long READ Response",      "Long"],
            ["0x1C", "01 1100", "DCS Long READ Response",          "Long"],
            ["0x21", "10 0001", "DCS Short READ Response 1 byte",  "Short"],
            ["0x22", "10 0010", "DCS Short READ Response 2 bytes", "Short"],
        ],
    })
    f.setdefault("crc_16_polynomial_table", {
        "header_columns": ["Field", "Value"],
        "rows": [
            ["Polynomial", "x^16 + x^12 + x^5 + 1"],
            ["Polynomial hex (MSB-first)", "0x1021"],
            ["Polynomial hex (LSB-first shift form)", "0x8408"],
            ["Initial value", "0xFFFF"],
            ["Shift direction", "LSB-first"],
            ["Coverage", "Long Packet payload bytes only"],
            ["Output order", "CRC LS Byte first, then CRC MS Byte"],
            ["Zero-payload Footer", "0xFFFF"],
            ["Non-checksum-peripheral Footer", "0x0000"],
        ],
    })
    f.setdefault("error_report_bit_definitions_table_18", {
        "header_columns": ["Bit", "Description"],
        "rows": [
            ["0",  "SoT Error"],
            ["1",  "SoT Sync Error"],
            ["2",  "EoT Sync Error"],
            ["3",  "Escape Mode Entry Command Error"],
            ["4",  "Low-Power Transmit Sync Error"],
            ["5",  "HS Receive Timeout Error"],
            ["6",  "False Control Error"],
            ["7",  "Reserved"],
            ["8",  "ECC Error, single-bit (detected and corrected)"],
            ["9",  "ECC Error, multi-bit (detected, not corrected)"],
            ["10", "Checksum Error (Long packet only)"],
            ["11", "DSI Data Type Not Recognized"],
            ["12", "DSI VC ID Invalid"],
            ["13", "Invalid Transmission Length"],
            ["14", "Reserved"],
            ["15", "DSI Protocol Violation"],
        ],
    })
    f.setdefault("eotp_short_packet_encoding", {
        "header_columns": ["Field", "Value"],
        "rows": [
            ["DI byte", "0x08"],
            ["Byte 1+Byte 2 payload", "0x0F0F"],
            ["ECC byte", "0x01"],
        ],
    })
    f.setdefault("trigger_messages_table", {
        "header_columns": ["Byte (hex)", "Bit Pattern first-to-last", "On-the-wire LSB-first", "Use"],
        "rows": [
            ["0x21", "00100001", "10000100", "Acknowledge"],
            ["0x5D", "01011101", "10111010", "Tearing Effect"],
        ],
    })
    f.setdefault("display_resolutions_table_23", {
        "header_columns": ["Resolution", "Horizontal Extent", "Vertical Extent"],
        "rows": [
            ["QQVGA", "160", "120"],
            ["QCIF", "176", "144"],
            ["QCIF+", "176", "208"],
            ["QCIF+", "176", "220"],
            ["QVGA", "320", "240"],
            ["CIF", "352", "288"],
            ["CIF+", "352", "416"],
            ["CIF+", "352", "440"],
            ["(1/2)VGA", "320", "480"],
            ["(2/3)VGA", "640", "320"],
            ["VGA", "640", "480"],
            ["WVGA", "800", "480"],
            ["SVGA", "800", "600"],
            ["XVGA", "1024", "768"],
        ],
    })
    f.setdefault("video_pixel_formats_table", {
        "header_columns": ["Bits per Pixel", "Format", "DT (hex)", "Bytes per Pixel"],
        "rows": [
            ["16", "RGB 5-6-5 packed",         "0x0E", "2"],
            ["18", "RGB 6-6-6 packed",         "0x1E", "9 bytes per 4 pixels"],
            ["18", "RGB 6-6-6 loosely packed", "0x2E", "3"],
            ["24", "RGB 8-8-8",                "0x3E", "3"],
        ],
    })
    f.setdefault("tables", [
        "Table 16 — Data Types for Processor-sourced Packets",
        "Table 17 — EoT Support for Host and Peripheral",
        "Table 18 — Error Report Bit Definitions",
        "Table 19 — Data Types for Peripheral-sourced Packets",
        "Table 20 — Required Peripheral Timing Parameters (Video Mode)",
        "Table 21 — ECC Syndrome Association Matrix",
        "Table 22 — ECC Parity Generation Rules",
        "Table 23 — Display Resolutions",
    ])
    # ABSENT in CSI-2 — full Table 21 + 22 row data.
    f.setdefault("ecc_syndrome_association_matrix_table_21", {
        "header_columns": [
            "d5d4d3 \\ d2d1d0",
            "0b000", "0b001", "0b010", "0b011",
            "0b100", "0b101", "0b110", "0b111",
        ],
        "rows": [
            ["0b000", "0x07", "0x0B", "0x0D", "0x0E", "0x13", "0x15", "0x16", "0x19"],
            ["0b001", "0x1A", "0x1C", "0x23", "0x25", "0x26", "0x29", "0x2A", "0x2C"],
            ["0b010", "0x31", "0x32", "0x34", "0x38", "0x1F", "0x2F", "0x37", "0x3B"],
            ["0b011", "0x43", "0x45", "0x46", "0x49", "0x4A", "0x4C", "0x51", "0x52"],
            ["0b100", "0x54", "0x58", "0x61", "0x62", "0x64", "0x68", "0x70", "0x83"],
            ["0b101", "0x85", "0x86", "0x89", "0x8A", "0x3D", "0x3E", "0x4F", "0x57"],
            ["0b110", "0x8C", "0x91", "0x92", "0x94", "0x98", "0xA1", "0xA2", "0xA4"],
            ["0b111", "0xA8", "0xB0", "0xC1", "0xC2", "0xC4", "0xC8", "0xD0", "0xE0"],
        ],
        "note": "Each cell holds the syndrome for the data bit at position (d5d4d3 << 3 | d2d1d0). Syndrome is MSB-left aligned: 0x07 = 0b00000111 = P7 P6 P5 P4 P3 P2 P1 P0. For example bit position D37 = 0b100_101 → syndrome 0x68.",
    })
    f.setdefault("ecc_parity_generation_rules_table_22_first_8_rows", {
        "header_columns": [
            "Data Bit", "P7", "P6", "P5", "P4", "P3", "P2", "P1", "P0", "Hex",
        ],
        "rows": [
            ["0", "0", "0", "0", "0", "0", "1", "1", "1", "0x07"],
            ["1", "0", "0", "0", "0", "1", "0", "1", "1", "0x0B"],
            ["2", "0", "0", "0", "0", "1", "1", "0", "1", "0x0D"],
            ["3", "0", "0", "0", "0", "1", "1", "1", "0", "0x0E"],
            ["4", "0", "0", "0", "1", "0", "0", "1", "1", "0x13"],
            ["5", "0", "0", "0", "1", "0", "1", "0", "1", "0x15"],
            ["6", "0", "0", "0", "1", "0", "1", "1", "0", "0x16"],
            ["7", "0", "0", "0", "1", "1", "0", "0", "1", "0x19"],
        ],
        "note": "Full 24-row table is provided in DSI Spec §9.3 Table 22; first 8 rows shown here. ECC[i] = XOR of data bits Dj where row j has a 1 in column Pi. P6 and P7 are unused in the 8-bit ECC byte and shall be 0 by transmitter.",
    })
    _write(p, d)


def _l16(gd: Path, ic_name: str) -> None:
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    # CSI-2 must_have is camera-oriented; DSI replaces with display SHALLs.
    _force(f, "must_have_properties", [
        "Exactly 1 Clock Lane + 1..4 Data Lane pairs.",
        "Clock Lane SHALL be driven only by host; peripheral SHALL NOT drive Clock Lane.",
        "All DSI transmitters and receivers SHALL support Continuous Clock behavior.",
        "In Command Mode systems Data Lane 0 SHALL be bidirectional; additional Lanes SHALL be unidirectional.",
        "Forward LP transmissions SHALL use Data Lane 0 only.",
        "Reverse-direction transmissions SHALL use LP mode only on Data Lane 0 only.",
        "Short Packets SHALL be 4 bytes; Long Packets SHALL be 6..65541 bytes.",
        "Packet Header SHALL be 32 bits (DI + WC LS + WC MS + ECC).",
        "Header ECC SHALL be Hamming-modified (24,8) — single-bit correct + 2-bit detect.",
        "P6 and P7 of ECC byte SHALL be 0 by transmitter; receiver SHALL ignore and force to 0.",
        "Long Packet Footer SHALL be CRC-16 poly x^16+x^12+x^5+1, init 0xFFFF, LSB-first, payload only.",
        "Zero-byte payload Footer SHALL be 0xFFFF.",
        "Non-checksum peripheral SHALL transmit 0x0000 in Footer.",
        "Bytes SHALL be LSB-first within byte; multi-byte fields LS byte first.",
        "Devices SHALL support EoTp Short Packet (DT=0x08, payload 0x0F0F, ECC 0x01).",
        "Devices SHALL provide implementation-specific means to enable/disable EoTp.",
        "EoTp SHOULD NOT be sent in LP mode.",
        "Trigger Message byte 0x5D is RESERVED for TE only.",
        "Set Maximum Return Packet Size default SHALL be 1 at power-on / reset.",
        "Set Maximum Return Packet Size SHALL be ignored by unidirectional DSI peripherals.",
        "Host SHALL implement ECC and Checksum capabilities; separately enable/disable.",
        "Peripheral SHALL implement ECC; Checksum implementation is optional.",
        "Bidirectional peripheral SHALL implement HRX_TO and LTX-P_TO.",
        "Host SHALL implement HTX_TO and LRX-H_TO.",
        "LRX-H_TO MUST be set longer than LTX-P_TO.",
        "Host LP clock SHALL be 67%..150% of peripheral LP clock.",
        "Host T_INIT_MASTER SHALL be ≥ t_POR + T_INIT_SLAVE + T_INTERNAL_DELAY.",
        "Peripheral SHALL power up in RX-Stop and SHALL ignore all Link states until T_INIT_SLAVE elapses.",
        "After every BTA peripheral SHALL respond with appropriate packets and return bus.",
        "Errors SHALL accumulate until reported via Acknowledge and Error Report, then clear.",
        "Bit 7 and Bit 14 of Error Report SHALL be transmitted as 0.",
        "Video Mode peripheral SHALL implement at least one of the four pixel formats; host SHALL implement all four.",
        "Host SHALL implement one or more Display Resolutions in Table 23.",
        "DT codes with DT[3:0] = 0b0000 or 0b1111 SHALL NOT be used.",
        "Multi-Lane implementations SHALL use a single common Clock Lane shared by all Data Lanes.",
    ])
    _force(f, "must_not_have_properties", [
        "Peripheral SHALL NOT drive Clock Lane.",
        "Reverse direction HS is NOT permitted.",
        "Reserved bits SHALL NOT carry data.",
        "DSI v1.0 devices SHALL NOT advertise EoTp.",
        "EoTp SHALL NOT be sent in LP.",
        "0x5D SHALL NOT be used for non-TE.",
        "Reserved DT codes SHALL NOT be used.",
        "DT[3:0] = 0b0000 or 0b1111 SHALL NOT be transmitted.",
        "P6 and P7 of ECC byte SHALL NOT be set to 1.",
    ])
    _force(f, "compliance_failure_modes", [
        {"mode": "ECC double-bit detect",       "trigger": "2-bit header error → packet dropped + bit 9."},
        {"mode": "Checksum mismatch",            "trigger": "Long-Packet payload corruption → bit 10."},
        {"mode": "DSI Data Type Not Recognized", "trigger": "Unknown DT → bit 11 + boundary lost."},
        {"mode": "DSI VC ID Invalid",            "trigger": "VC not recognized → bit 12."},
        {"mode": "Invalid Transmission Length",  "trigger": "WC mismatch → bit 13."},
        {"mode": "DSI Protocol Violation",       "trigger": "Expected EoTp / BTA missing → bit 15."},
        {"mode": "HS Receive Timeout",           "trigger": "HRX_TO expired → bit 5."},
        {"mode": "LP Contention",                "trigger": "LP-CD asserts; Annex A recovery."},
    ])
    f.setdefault("reset_behavior_compliance",
                 "Power-on or LP-Escape Reset → LP-11 Stop; peripheral powers up in RX-Stop with Maximum Return Packet Size = 1.")
    f.setdefault("min_clock_constraint",
                 "Determined by D-PHY v0.90.00.")
    _write(p, d)


def _l17(gd: Path, ic_name: str) -> None:
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    # CSI-2 channels list has CLK_P/N + DAT*; DSI uses Clock+/- and Data0+/-.
    _force(f, "channels", [
        {"name": "Clock+", "direction_host": "output (HS) only",
         "direction_peripheral": "input only",
         "purpose": "Differential Clock Lane positive; DDR.",
         "active_levels": "HS 100-200 mV diff; LP 1.2 V",
         "idle_level": "LP-11 in Non-Continuous; HS-0 in Continuous"},
        {"name": "Clock-", "direction_host": "output (HS) only",
         "direction_peripheral": "input only",
         "purpose": "Differential Clock Lane negative."},
        {"name": "Data0+", "direction_host": "output (HS) + I/O (LP)",
         "direction_peripheral": "input (HS) + I/O (LP)",
         "purpose": "Differential Data Lane 0 positive; bidirectional in LP."},
        {"name": "Data0-", "direction_host": "output (HS) + I/O (LP)",
         "direction_peripheral": "input (HS) + I/O (LP)",
         "purpose": "Differential Data Lane 0 negative."},
        {"name": "Data1+ / Data1- (optional)", "direction_host": "output only",
         "direction_peripheral": "input only",
         "purpose": "Data Lane 1 — unidirectional."},
        {"name": "Data2+ / Data2- (optional)", "direction_host": "output only",
         "direction_peripheral": "input only",
         "purpose": "Data Lane 2 — unidirectional."},
        {"name": "Data3+ / Data3- (optional)", "direction_host": "output only",
         "direction_peripheral": "input only",
         "purpose": "Data Lane 3 — unidirectional."},
    ])
    f.setdefault("logical_signaling_levels_inherited_from_d_phy", [
        {"name": "LP-00", "Dp": "0", "Dn": "0", "meaning": "Bridge"},
        {"name": "LP-01", "Dp": "0", "Dn": "1", "meaning": "HS Request"},
        {"name": "LP-10", "Dp": "1", "Dn": "0", "meaning": "Escape Request / Mark-One"},
        {"name": "LP-11", "Dp": "1", "Dn": "1", "meaning": "Stop state"},
        {"name": "HS-0",  "Dp": "diff-LOW",  "Dn": "diff-HIGH", "meaning": "HS differential 0"},
        {"name": "HS-1",  "Dp": "diff-HIGH", "Dn": "diff-LOW",  "meaning": "HS differential 1"},
    ])
    # CSI-2 packet_types_summary is RAW/YUV/RGB/sync; DSI replaces.
    _force(f, "packet_types_summary", [
        {"class": "Processor-sourced Short Packet", "count_approx": 19,
         "members": ["Sync Events (0x01/0x11/0x21/0x31)", "EoTp (0x08)",
                     "CM Off/On (0x02/0x12)", "Shutdown/Turn On (0x22/0x32)",
                     "Generic Short Write 0/1/2 (0x03/0x13/0x23)",
                     "Generic READ 0/1/2 (0x04/0x14/0x24)",
                     "DCS Short Write 0/1 (0x05/0x15)", "DCS READ (0x06)",
                     "Set Max Return Pkt Size (0x37)"]},
        {"class": "Processor-sourced Long Packet", "count_approx": 8,
         "members": ["Null (0x09)", "Blanking (0x19)", "Generic Long Write (0x29)",
                     "DCS Long Write (0x39)", "Packed Pixel 16-bit RGB565 (0x0E)",
                     "Packed Pixel 18-bit RGB666 Packed (0x1E)",
                     "Loosely Packed Pixel 18-bit (0x2E)",
                     "Packed Pixel 24-bit RGB888 (0x3E)"]},
        {"class": "Peripheral-sourced Short Packet", "count_approx": 6,
         "members": ["Acknowledge and Error Report (0x02)", "EoTp (0x08)",
                     "Generic Short Read Response 1/2 byte (0x11/0x12)",
                     "DCS Short Read Response 1/2 byte (0x21/0x22)"]},
        {"class": "Peripheral-sourced Long Packet", "count_approx": 2,
         "members": ["Generic Long Read Response (0x1A)",
                     "DCS Long Read Response (0x1C)"]},
    ])
    # CSI-2 sets channel_counts to camera values; DSI force-overwrites with
    # display values (4..10 wires / 2..5 pairs / 35 packet types / 4 VCs).
    _force(f, "channel_counts", {
        "external_wire_count": "4..10 (1 Clock Lane pair + 1..4 Data Lane pairs).",
        "differential_pairs":  "2..5 (1 Clock + 1..4 Data).",
        "max_devices_per_link": 1,
        "max_VC": 4,
        "packet_types_total_approx": 35,
    })
    f.setdefault("global_signals", [])
    # CSI-2 sets ordering_rules without checksum / transmission_order; DSI
    # force-overwrites with the full DSI set.
    _force(f, "ordering_rules", {
        "bit_order_within_byte":  "LSB-first on the wire (bit 0 first, bit 7 last).",
        "byte_order_within_header": "DI (byte 0) → WC LS Byte (byte 1) → WC MS Byte (byte 2) → ECC (byte 3); little-endian over the wire.",
        "byte_order_within_checksum": "CRC LS Byte first, then CRC MS Byte; CRC computed LSB-first over payload (per Annex B).",
        "multilane_byte_order":     "byte k → lane (k mod N); SoT replicated on every active Lane.",
        "tx_rx_simultaneity":       "Host → peripheral during HS payload (forward); peripheral → host during LP after BTA (reverse); never both ends HS-driving at the same time.",
        "transmission_order":       "Long packet: SoT → LPS → DI → WC LS → WC MS → ECC → Data0 → Data1 → ... → DataWC-1 → CRC LS Byte → CRC MS Byte → EoT → LPS.",
    })
    _force(f, "dependency_graph", {
        "common_rule": "Host drives Clock Lane unconditionally. During HS, host drives all Data Lanes; during LP after BTA, peripheral drives Data Lane 0 only. EoTp Short Packet, when enabled, is the last packet of every HS transmission and is detected at the protocol layer independent of D-PHY EoT.",
        "data_dependency": "Each Data-Lane bit sampled on a Clock-Lane edge (both edges, DDR). Header ECC validates DI+WC; payload Checksum validates payload. Errors accumulate in peripheral Error Register and are reported on next BTA via Acknowledge and Error Report Short Packet.",
    })
    _force(f, "handshake_pairs", [
        {"name": "HS_ENTRY", "from": "host", "to": "peripheral",
         "rule": "LP-11 → LP-01 → LP-00 → HS-0 → Sync → packet stream."},
        {"name": "HS_EXIT",  "from": "host", "to": "peripheral",
         "rule": "Last packet (optionally EoTp) → HS-Trail → LP-11."},
        {"name": "BTA",      "from": "either", "to": "other",
         "rule": "TurnRequest → BTA Escape sequence on Data Lane 0."},
        {"name": "ACK_TRIGGER", "from": "peripheral", "to": "host",
         "rule": "LP Escape trigger byte 0x21 after BTA when no errors."},
        {"name": "ACK_AND_ERR_REPORT", "from": "peripheral", "to": "host",
         "rule": "Short Packet DT=0x02 carrying 16-bit Error Report."},
        {"name": "READ_RESPONSE", "from": "peripheral", "to": "host",
         "rule": "Generic/DCS Short/Long Read Response bounded by Set Max Return Pkt Size."},
        {"name": "TE_TRIGGER", "from": "peripheral", "to": "host",
         "rule": "LP Escape trigger byte 0x5D after BTA-without-command."},
    ])
    _write(p, d)


def _l18(gd: Path, ic_name: str) -> None:
    p = gd / "L18_INTERCONNECT_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    _force(f, "topology_type",
           "Point-to-point asymmetric (mostly source → sink with reverse direction Data Lane 0 in LP only). Host processor ↔ one peripheral. Normatively the DSI v1.01.00 specification only addresses host-to-single-peripheral connections; multi-peripheral via VC is informative.")
    _force(f, "supported_topologies", [
        {"name": "Host ↔ one peripheral, Command Mode",
         "description": "Bidirectional Data Lane 0 + optional unidirectional Data Lanes 1..3; supports DCS read/write + Acknowledge + TE."},
        {"name": "Host ↔ one peripheral, Video Mode unidirectional",
         "description": "Cost-optimized; all Data Lanes host → peripheral only."},
        {"name": "Host ↔ one peripheral, Video Mode bidirectional",
         "description": "Data Lane 0 bidirectional for Acknowledge and Error Report."},
        {"name": "Multi-peripheral via VC (informative)",
         "description": "Multiple peripherals share Link via DI[7:6] VC[1:0]; outside DSI v1.01 normative scope."},
    ])
    _force(f, "master_slave_role_summary", [
        {"role": "Host Processor",
         "description": "Drives Clock Lane DDR unconditionally; sources all forward HS/LP; initiates BTA; programs T_INIT_MASTER; implements HTX_TO + LRX-H_TO."},
        {"role": "Peripheral (Display Module)",
         "description": "Powers up in RX-Stop; receives forward HS/LP; after BTA transmits Acknowledge/Error Report/Read Response/TE in LP on Data Lane 0; returns bus via own BTA; bidirectional peripheral implements HRX_TO + LTX-P_TO."},
    ])
    f.setdefault("interconnect_role",
                 "Flat point-to-point pair. VC-based multi-peripheral is informative.")
    # CSI-2 may set ordering_guarantees / device_classification with camera
    # values; DSI force-overwrites with display-protocol shape.
    _force(f, "ordering_guarantees", {
        "within_a_packet":     "Bytes transmitted byte-0 first; within each byte, LSB-first on the wire.",
        "within_a_transmission":"Packets may be concatenated within a single HS transmission; when EoTp enabled the last packet is EoTp; HS Exit follows.",
        "within_a_frame":      "Video Mode: VSS → VBP lines → VACT lines (HSS + HSA + HSE + HBP + RGB + HFP per line) → VFP lines → VSE (or just next VSS in Sync-Events / Burst modes).",
        "across_VCs":          "VCs interleave at packet boundary; no ordering between VCs.",
    })
    f.setdefault("memory_vs_peripheral_regions",
                 "DSI has no addressable memory; DCS commands access peripheral registers.")
    _force(f, "device_classification", {
        "host_processor":           "Application processor or baseband processor with embedded DSI master controller.",
        "peripheral_command_mode":  "Active-matrix display module with on-panel display controller, frame buffer, DCS interpreter, and bidirectional DSI slave interface.",
        "peripheral_video_mode":    "Active-matrix display module without on-panel frame buffer; relies on continuous host pixel stream.",
        "multi_peripheral_setup":   "Multiple driver ICs serving different areas of a common display panel, each tagged by a different VC[1:0]; informative.",
    })
    f.setdefault("max_link_length_inherited_from_d_phy", {
        "PCB_trace_cm_at_low_data_rate":  30,
        "PCB_trace_cm_at_high_data_rate": 10,
        "FFC_cable_cm_typical":           20,
    })
    f.setdefault("default_signal_values_evidence_tables", [
        "Section 4 — DSI Introduction + DSI Layer Definitions",
        "Section 5 — DSI Physical Layer + Bidirectionality and LP Signaling Policy",
        "Section 6 — Multi-Lane Distribution and Merging",
        "Section 7 — Low-Level Protocol Errors and Contention",
        "Section 8 — DSI Protocol",
        "Section 9 — Error-Correcting Code (ECC) and Checksum",
        "Section 10 — Compliance, Interoperability, and Optional Capabilities",
    ])
    _write(p, d)


def _l19(gd: Path, ic_name: str) -> None:
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f.setdefault("constraints_present", True)
    f.setdefault("notes_on_dsi_scope",
                 "DSI v1.01.00 §1.1 explicitly declares electrical / physical specifications out of scope; PCB constraints come from D-PHY v0.90.00.")
    # CSI-2 may set pcb_constraints_inherited_from_d_phy / dsi_specific_*; DSI
    # force-overwrites with full DSI strings.
    _force(f, "pcb_constraints_inherited_from_d_phy", {
        "differential_pair_impedance_ohm": 100,
        "intra_pair_skew_ps_max":          5,
        "inter_pair_skew_ps_max":          100,
        "max_trace_length_cm_at_low_rate": 30,
        "max_trace_length_cm_at_high_rate": 10,
        "AC_coupling":                     "NOT used — D-PHY is DC-coupled differential",
        "common_mode_choke":               "Not recommended; degrades HS eye",
        "ESD_protection_class":            "HBM 2 kV minimum (Class 2); diodes placed close to connector",
    })
    f.setdefault("pad_constraints_inherited_from_d_phy", {
        "HS_termination_internal_ohm": 100,
        "HS_swing_diff_mV_target":     [100, 200],
        "LP_swing_V_target":           1.2,
        "ESD_clamp_present":           True,
        "shared_HS_LP_pad":            "Same Dp/Dn carries both modes.",
    })
    _force(f, "dsi_specific_implementation_constraints", {
        "host_lp_clock_vs_peripheral_lp_clock_ratio_pct_range": [67, 150],
        "peripheral_T_INIT_accuracy":              "R-C timer with ±30% accuracy is acceptable (§5.7).",
        "host_T_INIT_MASTER_lower_bound":          "≥ t_POR + T_INIT_SLAVE + T_INTERNAL_DELAY of the peripheral (§5.7).",
        "default_max_return_packet_size_at_reset": 1,
        "EoTp_enable_disable_means":               "Implementation-specific; must exist on every v1.01-compliant device for backward compatibility (§8.8.2, §10.9).",
    })
    _force(f, "sdc_floorplan_hints", {
        "Clock_Lane_PLL_placement":     "Close to host pads; minimize jitter.",
        "Per_lane_delay_line_placement":"Close to peripheral pads; programmable for deskew.",
        "Sync_hunter_placement":        "Peripheral side; pipelined to meet Clock-Lane DDR rate.",
        "BTA_LP_TX_LP_RX_arbiter_placement": "On bidirectional Data Lane 0 only — must coexist on the same pad pair.",
    })
    # CSI-2 set notes to camera-PHY scope text; DSI overwrites with DSI scope.
    _force(f, "notes",
           "DSI v1.01.00 is a protocol-layer specification; all electrical / timing constraints flow down from D-PHY. The only DSI-specific physical requirement of consequence is host-vs-peripheral LP clock frequency ratio (67%..150%) and the T_INIT power-up timing chain. EoTp enable/disable is also an implementation requirement that must be exposed (no normative mechanism specified).")
    _write(p, d)


def _l20(gd: Path, ic_name: str) -> None:
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f.setdefault("dft_present", "partial")
    _force(f, "internal_diagnostics", [
        "Acknowledge and Error Report Short Packet (DT=0x02) — 16-bit error mask.",
        "Header ECC (Hamming-modified 24,8) — single-bit-correct + 2-bit-detect.",
        "Long Packet Checksum (CRC-16) over payload bytes only.",
        "EoTp Short Packet (DT=0x08) — protocol-layer end-of-HS marker.",
        "Contention recovery timers (HRX_TO / HTX_TO / LTX-P_TO / LRX-H_TO).",
        "Optional TA_TO and PR_TO.",
        "Annex B reference CRC-16 test vectors as regression inputs.",
    ])
    f.setdefault("scan_topology", {
        "standard_scan_chain_present": False,
        "JTAG_present_at_protocol_layer": False,
        "vendor_BIST_extensions": "Vendor IP commonly adds BIST + loopback; NOT in DSI v1.01.00 spec.",
    })
    # CSI-2 set notes to camera-DFT text; DSI overwrites.
    _force(f, "notes",
           "DSI v1.01.00 does NOT define standard scan or JTAG mechanisms. Debug relies on (a) the in-band 16-bit Error Report returned via Acknowledge and Error Report Short Packet after BTA, (b) Header ECC and Payload Checksum integrity checks, and (c) the EoTp Short Packet as a protocol-layer end-of-transmission marker. Production-line characterization adds eye-diagram measurements and the MIPI Alliance Conformance Test Suite procedures on top. Vendor IP commonly layers BIST, loopback, and eye-monitor on top of the standard.")
    _write(p, d)


def _l21(gd: Path, ic_name: str) -> None:
    p = gd / "L21_POWER_INTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f.setdefault("power_intent_present", True)
    _force(f, "low_power_modes_summary", {
        "HS_active":         "HS payload streaming on Data Lanes + DDR Clock Lane; highest current; used for pixel-stream and large command bursts.",
        "LP_active":         "Low-Power signaling (≤ 10 Mbps); used for forward escape (LPDT, Trigger, Reset) on Data Lane 0 and all reverse-direction Acknowledge / Error Report / Read Response / TE.",
        "Stop_state_LP11":   "Both Dp and Dn driven HIGH (1.2 V CMOS); near-static; minimal current; baseline idle state between bursts.",
        "ULPS":              "Ultra-Low Power State; lane held LP-00 indefinitely; receiver in deep sleep; entered via LP Escape command; lowest current state.",
        "Non_Continuous_Clock_Mode": "Clock Lane returns to LP-11 between bursts to save clock-tree power; optional support — host explicitly chooses this mode.",
        "Continuous_Clock_Mode": "Clock Lane stays in HS forever; lower latency at the cost of higher power.",
        "Video_Mode_BLLP_LP_substitution": "In Video Mode, if sufficient time exists during HBP / HFP / blanking, the bus may transition to LP instead of sending Blanking Packets — substantial power saving.",
    })
    f.setdefault("current_estimates_inherited_from_d_phy", {
        "HS_per_lane_mA_typ":    8,
        "LP_per_lane_mA_typ":    1,
        "Stop_LP11_per_lane_uA": 100,
        "ULPS_per_lane_uA":      10,
    })
    _force(f, "ulps_specification_inherited_from_d_phy", {
        "entry_command_byte":   "0x1E (LP escape ULPS command, per D-PHY)",
        "exit_signaling":       "Source drives LP-10 (Mark-One) for ≥ T-WAKEUP (≈ 1 ms minimum); both ends return to LP-11.",
        "minimum_duration":     "Unbounded — peripheral may stay in ULPS indefinitely for deep sleep.",
    })
    f.setdefault("shutdown_and_turn_on_commands", {
        "shutdown_peripheral_DT": "0x22 — turns off display; interface stays powered for wake-up.",
        "turn_on_peripheral_DT":  "0x32 — turns on display.",
    })
    f.setdefault("color_mode_commands", {
        "color_mode_off_DT": "0x02 — back to normal color.",
        "color_mode_on_DT":  "0x12 — low-color mode for power saving.",
    })
    f.setdefault("command_mode_low_power_substitute",
                 "Video Mode display module may include simplified Command Mode operation with reduced-size frame buffer for low-power refresh; local frame buffer SHALL be loaded prior to shutdown.")
    f.setdefault("power_classes_of_implementations", [
        "Mobile-phone Command Mode — aggressive Non-Continuous Clock + ULPS + Color Mode On.",
        "Mobile-phone Video Mode — Continuous Clock or BLLP-to-LP substitution.",
        "Tablet / handheld with on-panel frame buffer — Command Mode + ULPS between writes.",
    ])
    # CSI-2 may set notes to camera-power text; DSI overwrites.
    _force(f, "notes",
           "DSI v1.01.00 inherits all PHY-level power modes (HS, LP, Stop, ULPS, Non-Continuous Clock) from D-PHY. DSI adds protocol-level power-control commands — Shutdown Peripheral (0x22), Turn On Peripheral (0x32), Color Mode Off / On (0x02 / 0x12) — and the Video Mode BLLP-to-LP substitution mechanism that allows the bus to enter LP during horizontal blanking intervals when timing permits. Power management for the panel itself is exposed via DCS commands carried inside DSI 0x05 / 0x15 / 0x39 packets.")
    _write(p, d)


def _l22(gd: Path, ic_name: str) -> None:
    p = gd / "L22_VERIFICATION_PLAN.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f.setdefault("verification_plan_present", "implicit")
    if not f.get("verification_categories_derived_from_spec"):
        f["verification_categories_derived_from_spec"] = []
    extra = [
        "Power-up T_INIT compliance.",
        "HS Entry / Exit (inherited from D-PHY).",
        "Short Packet round-trip — every Processor-sourced + Peripheral-sourced DT.",
        "Long Packet round-trip — Null / Blanking / Generic Long / DCS Long / Packed Pixel formats.",
        "Header ECC single-bit correction — Error Report bit 8.",
        "Header ECC multi-bit detect — bit 9 + packet drop.",
        "Long Packet Checksum verification — Annex B vectors gpcTestData0..3.",
        "Zero-payload Footer = 0xFFFF; non-checksum Footer = 0x0000.",
        "EoTp detection (HS only).",
        "EoTp enable/disable interoperability.",
        "Multi-Lane interleave N=1..4.",
        "Video Mode Non-Burst Sync Pulses.",
        "Video Mode Non-Burst Sync Events.",
        "Video Mode Burst.",
        "All four pixel formats (RGB565 / RGB666 Packed / RGB666 Loosely Packed / RGB888).",
        "Set Maximum Return Packet Size default 1.",
        "BTA host ↔ peripheral.",
        "Acknowledge Trigger Message 0x21.",
        "Acknowledge and Error Report Short Packet (16 bits).",
        "Single-bit ECC on Read → Response + Error Report same LP transmission.",
        "Multi-bit ECC on any command → ONLY Error Report.",
        "Tearing Effect 0x5D after BTA-without-command.",
        "Required + optional timers (HRX_TO / HTX_TO / LTX-P_TO / LRX-H_TO / TA_TO / PR_TO).",
        "Contention recovery (Annex A Cases 1/2/3).",
        "Continuous vs Non-Continuous Clock Mode.",
        "Host LP clock 67%..150% of peripheral.",
        "Reserved DT codes trigger DT Not Recognized.",
        "Endian compliance.",
        "Display Resolution interoperability per Table 23.",
    ]
    existing = set(f["verification_categories_derived_from_spec"])
    for item in extra:
        if item not in existing:
            f["verification_categories_derived_from_spec"].append(item)
    f.setdefault("notes",
                 "Formal verification via MIPI Alliance Conformance Test Suite; this list captures design-time categories from DSI v1.01.00 spec.")
    _write(p, d)


def _l23(gd: Path, ic_name: str) -> None:
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f.setdefault("security_requirements_present", False)
    _force(f, "anti_corruption_mechanisms", [
        "Header ECC: Hamming-modified (24,8) single-bit-correct + 2-bit-detect.",
        "Long Packet Checksum: CRC-16 poly x^16+x^12+x^5+1, init 0xFFFF, LSB-first.",
        "Sync-pattern lock (D-PHY): 8'b00011101.",
        "EoTp Short Packet: protocol-layer end-of-HS marker.",
        "Acknowledge and Error Report Short Packet: 16-bit error mask after BTA.",
        "Contention recovery timers HRX_TO / HTX_TO / LTX-P_TO / LRX-H_TO.",
        "LP Contention detector + Annex A recovery flows.",
    ])
    f.setdefault("notes",
                 "MIPI DSI v1.01.00 provides NO confidentiality, integrity-against-tampering, or authentication. Content protection (HDCP/DRM) must be layered above DSI; for secure use cases vendors implement extensions on top.")
    _write(p, d)


# ----- public entry ---------------------------------------------------------

def apply_mipi_dsi_synth(generated_docs_dir, is_mipi_dsi: bool,
                         mipi_dsi_ic_name: Optional[str]) -> None:
    """Apply MIPI DSI v1.01.00-specific synth when the structural
    signature matched.

    IMPORTANT: this may run AFTER `apply_mipi_synth` (CSI-2) if both
    detectors triggered (D-PHY is shared). The L1/L3 overlays here
    force-overwrite the CSI-2-specific values so the final L docs
    are DSI display-protocol shape, not CSI-2 camera-protocol shape.
    """
    if not is_mipi_dsi:
        return
    gd = Path(generated_docs_dir)

    # Force ic_name across all 24 L docs.
    if mipi_dsi_ic_name is not None:
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
                d["ic_name"] = mipi_dsi_ic_name
                _write(q, d)

    # Per-layer overlays.
    name = mipi_dsi_ic_name or "MIPI DSI v1.01.00"
    _l1(gd, name)
    _l2(gd, name)
    _l3(gd, name)
    _l4(gd, name)
    _l5(gd, name)
    _l6(gd, name)
    _l7(gd, name)
    _l8_rtl(gd, name)
    _l8_timing(gd, name)
    _l9(gd, name)
    _l10(gd, name)
    _l11(gd, name)
    _l12(gd, name)
    _l13(gd, name)
    _l14(gd, name)
    _l15(gd, name)
    _l16(gd, name)
    _l17(gd, name)
    _l18(gd, name)
    _l19(gd, name)
    _l20(gd, name)
    _l21(gd, name)
    _l22(gd, name)
    _l23(gd, name)


# ---------------------------------------------------------------------------
# Module-level importable detector (lifted from the inline detector in
# phase1_doc_one_shot_runner.py — ORGANIC-20260531). Byte-for-byte the same
# boolean the runner used inline (`_spi_blob` -> `blob`), so behaviour is
# identical; exposing it module-level lets the universal no-misfire guard
# (tests/test_protocol_detector_no_misfire.py) auto-cover this protocol.
# Reads ONLY the spec text `blob` — never a filename or benchmark name.
# ---------------------------------------------------------------------------
def is_mipi_dsi(blob: str) -> bool:
    """Content-only `mipi_dsi` detector with a FOREIGN-PRIMARY DEFER.

    Empty-safe. Reads ONLY ``blob`` (spec text).

    The structural DSI signature below ("DSI"+"DCS"+Command Mode+Video Mode,
    or MIPI+DSI+Tearing Effect, or DSI+"Display Serial Interface") is
    necessary but NOT sufficient: DSI shares the MIPI D-PHY physical layer
    and the Long/Short-Packet + ECC + CRC-16 framing with its CSI-2 camera
    sibling, and DSI is routinely cited as a comparison interface inside
    sibling-MIPI / UFS multi-doc blobs. Three foreign benchmarks therefore
    trip the loose branches even though DSI is not their subject:
      - generic-MIPI D-PHY / CSI-2 app note (incidental "DSI" + a single
        "Display Serial Interface" mention),
      - mipi_csi2 (its DCS / Command-Mode / Video-Mode cross-references trip
        branch 1), and
      - UFS (incidental "DSI" + "Display Serial Interface" co-occurrence).

    Guard (mirrors `is_mipi`'s foreign-primary defer doctrine — general,
    content-only, no chip/SKU/benchmark literal as detection logic): if the
    blob's DOMINANT subject is a foreign protocol, defer (False), so the DSI
    synth never fires on a foreign spec that only mentions DSI incidentally:
      - UFS  (UniPro+M-PHY, UPIU, JESD220+UFS, or dense "ufs"),
      - CSI-2 (the camera serial interface is the running subject: its
        mention density exceeds DSI's AND the CSI-2-only camera-pipeline
        structure — image-sensor role and/or the Camera Control Interface
        sideband — is present). A real DSI display spec is DSI-dominant
        (DSI mentioned far more than CSI-2) and lacks the image-sensor /
        CCI camera structure, so it never trips this defer.

    Empirically corpus-clean: mipi_dsi stays True; mipi/mipi_csi2 trip
    csi2_primary, ufs trips ufs_primary, so all three are suppressed.
    """
    if not blob:
        return False
    low = blob.lower()

    # --- FOREIGN-PRIMARY DEFER (the blob's true subject is NOT MIPI DSI). ---
    # UFS-primary: Universal Flash Storage / UniPro / M-PHY / UPIU / JESD220
    # is the running subject (mirrors is_ufs + the is_mipi ufs_primary defer).
    ufs_primary = (
        low.count("ufs") >= 20
        or _wb("UPIU", blob)
        or ("unipro" in low and ("m-phy" in low or "mphy" in low))
        or ("jesd220" in low and ("universal flash storage" in low
                                  or _wb("UFS", blob))))
    # CSI-2-primary: the Camera Serial Interface is the running subject. DSI
    # and CSI-2 share the D-PHY + packet framing, so the discriminator is
    # SUBJECT DOMINANCE — CSI-2 is mentioned more than DSI — combined with the
    # CSI-2-only camera-pipeline structure (image-sensor source role and/or the
    # Camera Control Interface sensor-control sideband, present in NO DSI
    # display spec). A genuine DSI spec is DSI-dominant and carries neither.
    csi2_density = (low.count("csi-2") + low.count("csi2")
                    + low.count("camera serial interface"))
    dsi_density = low.count("dsi")
    csi2_camera_struct = (
        "camera control interface" in low
        or "image sensor" in low
        or ("camera" in low and "sensor" in low))
    csi2_primary = (
        csi2_density >= 20
        and csi2_density > dsi_density
        and csi2_camera_struct)
    if ufs_primary or csi2_primary:
        return False

    # --- STRUCTURAL MIPI DSI signature (unchanged from the runner's inline
    #     detector). ---
    return bool(
        ("DSI" in blob and "DCS" in blob
            and "Command Mode" in blob and "Video Mode" in blob)
        or ("MIPI" in blob and "DSI" in blob
            and "Tearing Effect" in blob)
        or ("DSI" in blob and "Display Serial Interface" in blob))
