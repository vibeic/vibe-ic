"""Enhanced Serial Peripheral Interface (eSPI) protocol synth helper.

Drop-in protocol synth discovered by the runner's generic auto-dispatch
(`AUTO_DISPATCH = True`). Applies Intel eSPI Base Specification canonical
content to L1-L23 when the eSPI structural signature is present.

Doctrine — GENERAL not keyword: detection uses canonical STRUCTURAL signatures
read from the L-doc / input_doc CONTENT blob only (never a filename or folder
name): the four eSPI logical channels (Peripheral / Virtual Wire / OOB /
Flash Access), the command/response-with-turnaround transaction model, the
GET_CONFIGURATION / SET_CONFIGURATION register negotiation, ESPI_ALERT#, and
the fact that eSPI REPLACES the LPC bus.

Sibling disambiguation — eSPI vs classic SPI, QSPI/OSPI, and LPC.
  * Classic SPI is a 4-wire (SCK/MOSI/MISO/CS) full-duplex shift link with NO
    logical channels, NO turnaround command/response, NO CRC negotiation, NO
    Virtual Wire / OOB / Flash channels. eSPI is NOT classic SPI.
  * QSPI/OSPI is a NOR-flash command interface (1/2/4/8 IO lanes, flash read
    opcodes 0x03/0xEB, dummy cycles) with NO four-channel model and NO sideband
    tunneling. eSPI multiplexes 4 logical channels and tunnels sideband signals.
  * LPC is the PARALLEL predecessor eSPI replaces (LAD[3:0] + LFRAME# at 33 MHz);
    eSPI is the serial successor. The detector requires the eSPI-only four
    logical channels + GET/SET_CONFIGURATION, which LPC lacks.
The detector DEFERS (returns False) unless the eSPI-only structural quorum is
met, so a plain-SPI / QSPI / LPC spec cannot false-fire.

Public entry: ``apply_espi_synth(generated_docs_dir, is_espi_flag, ic_name)``.
Module-level ``is_espi(blob)`` is the content-only detector.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

# Generic auto-dispatch opt-in (read by phase1_doc_one_shot_runner [14e2b/15]).
AUTO_DISPATCH = True
IC_NAME = "Enhanced Serial Peripheral Interface (eSPI)"

# Docs whose canonical content sits at the TOP level of the L-doc JSON.
_FLAT_DOCS = (
    "L1_DATASHEET", "L2_FRS", "L3_CMD_PROTOCOL", "L4_REGMAP", "L5_ADI_SPEC",
    "L6_CONTROL_LOGIC", "L7_TEST_DEBUG", "L8_RTL_CONSTANTS",
    "L8_TIMING_WAVEFORM", "L9_INTEGRATION_SPEC", "L10_TEST_CASES",
    "L11_OTP_CONTENT", "L12_BEHAVIORAL_SEQUENCES", "L13_LAB_CALIBRATION",
)
# Docs whose canonical content sits under a "fields" wrapper.
_FIELDS_DOCS = (
    "L14_PROTOCOL_VERSIONING", "L15_ENCODING_TABLES",
    "L16_COMPLIANCE_PROPERTIES", "L17_CHANNEL_SIGNAL_CATALOG",
    "L18_INTERCONNECT_TOPOLOGY", "L19_CONSTRAINTS_PDK",
    "L20_DFT_SCAN_TOPOLOGY", "L21_POWER_INTENT", "L22_VERIFICATION_PLAN",
    "L23_SECURITY_REQUIREMENTS",
)


def is_espi(blob: str) -> bool:
    """Content-only eSPI detector with SPI / QSPI / LPC MUTEX."""
    if not blob:
        return False
    low = blob.lower()
    # Name token (structural identifier, not a bare folder name).
    name_token = ("enhanced serial peripheral interface" in low
                  or "espi" in low or "e-spi" in low)
    if not name_token:
        return False
    # eSPI-only structural quorum.
    four_channels = (
        ("peripheral" in low and "virtual wire" in low
         and ("oob" in low or "out-of-band" in low or "out of band" in low)
         and "flash" in low))
    config_negotiation = ("get_configuration" in low
                          or "set_configuration" in low
                          or "get configuration" in low)
    alert = "espi_alert" in low or "alert#" in low
    replaces_lpc = ("replace" in low and "lpc" in low) or "low pin count" in low
    cmd_resp = ("turnaround" in low or "tar" in low) and (
        "response" in low or "get_status" in low or "put_pc" in low)
    score = sum(bool(x) for x in
                (four_channels, config_negotiation, alert, replaces_lpc, cmd_resp))
    # Require the four-channel signature plus at least two more eSPI-only marks.
    return four_channels and score >= 3


# ----------------------------------------------------------------------
# Canonical eSPI content (Intel eSPI Base Specification Rev 1.5).
# ----------------------------------------------------------------------
def _canon():
    return {
        "L1_DATASHEET": {
            "ic_name": IC_NAME,
            "document_title": "Enhanced Serial Peripheral Interface (eSPI) Base Specification",
            "document_number": "327432-004",
            "manufacturer": "Intel Corporation",
            "revised_date": "Revision 1.5",
            "external_pins": ["ESPI_CLK", "ESPI_IO0", "ESPI_IO1", "ESPI_IO2",
                              "ESPI_IO3", "ESPI_CS#", "ESPI_RESET#", "ESPI_ALERT#"],
            "external_pin_count": 8,
            "package": "Integrated chipset/PCH interface (no dedicated package)",
            "key_features": [
                "Replaces the Low Pin Count (LPC) bus in PC platforms with reduced pin count",
                "Source-synchronous serial bus, single master (PCH/chipset) to one or more slaves (EC, BMC, Super-I/O, flash)",
                "Single (1-bit), Dual (2-bit), and Quad (4-bit) I/O modes over ESPI_IO[3:0]",
                "Clock 20 MHz (boot) up to 66 MHz (negotiated)",
                "Low I/O voltage (1.0 V / 1.8 V rail)",
                "Four independent logical channels: Peripheral, Virtual Wire, OOB (Out-Of-Band), Flash Access",
                "In-band Virtual Wire messages consolidate legacy sideband signals",
                "Optional CRC-8 (polynomial 0x07) integrity checking, negotiated",
            ],
            "io_voltage": "1.0 V / 1.8 V",
            "clock_frequency": "20 MHz to 66 MHz",
        },
        "L2_FRS": {
            "ic_name": IC_NAME,
            "protocol_overview": {
                "type": "Source-synchronous serial bus, single master to one or more slaves",
                "duplex": "half-duplex (command phase then turnaround then response phase)",
                "synchronous": True,
                "replaces": "Low Pin Count (LPC) bus",
                "io_modes": ["Single (1-bit)", "Dual (2-bit)", "Quad (4-bit)"],
                "clock_mhz_range": [20, 66],
                "io_voltage_v": [1.0, 1.8],
                "channels": ["Peripheral", "Virtual Wire", "OOB (Out-Of-Band)", "Flash Access"],
                "wire_names": ["ESPI_CLK", "ESPI_IO[3:0]", "ESPI_CS#", "ESPI_RESET#", "ESPI_ALERT#"],
                "crc": "optional CRC-8 (poly 0x07), negotiated",
            },
            "functional_requirements": [
                "Master drives ESPI_CLK common to all slaves; data on rising edge, sample on falling edge (command phase).",
                "Every transaction: CS# assert -> 8-bit CMD opcode -> command fields -> optional data -> CRC -> turnaround (TAR) -> RESPONSE (8-bit code + data + status + CRC) -> CS# deassert.",
                "Four logical channels multiplexed over one physical bus, each with independent flow control and ordering.",
                "Virtual Wire channel tunnels sideband signals (interrupts, SUS_STAT#, SLP_S3#, etc.) in-band.",
                "OOB channel tunnels SMBus/MCTP messages.",
                "Flash Access channel lets the slave read/write the flash component.",
                "Configuration negotiated via GET_CONFIGURATION/SET_CONFIGURATION at offsets 0x08/0x10/0x20/0x30/0x40.",
                "On reset: Single I/O mode, 20 MHz, CRC disabled.",
            ],
        },
        "L3_CMD_PROTOCOL": {
            "ic_name": IC_NAME,
            "protocol_type": "Command/response over shared serial bus; 8-bit opcode + fields + CRC; turnaround; 8-bit response code.",
            "opcodes": [
                {"hex": "0x00", "name": "PUT_PC", "purpose": "Put a posted/completion Peripheral Channel transaction"},
                {"hex": "0x01", "name": "GET_PC", "purpose": "Get a posted/completion Peripheral Channel transaction"},
                {"hex": "0x04", "name": "PUT_NP", "purpose": "Put a non-posted Peripheral Channel transaction"},
                {"hex": "0x02", "name": "GET_NP", "purpose": "Get a non-posted Peripheral Channel transaction"},
                {"hex": "0x06", "name": "PUT_IORD_SHORT", "purpose": "Short (1/2/4 byte) I/O read"},
                {"hex": "0x07", "name": "PUT_IOWR_SHORT", "purpose": "Short I/O write"},
                {"hex": "0x08", "name": "PUT_MEMRD32_SHORT", "purpose": "Short 32-bit memory read"},
                {"hex": "0x09", "name": "PUT_MEMWR32_SHORT", "purpose": "Short 32-bit memory write"},
                {"hex": "0x10", "name": "PUT_VWIRE", "purpose": "Put Virtual Wire packet (Channel 1)"},
                {"hex": "0x11", "name": "GET_VWIRE", "purpose": "Get Virtual Wire packet"},
                {"hex": "0x12", "name": "PUT_OOB", "purpose": "Put OOB (tunneled SMBus) message (Channel 2)"},
                {"hex": "0x13", "name": "GET_OOB", "purpose": "Get OOB message"},
                {"hex": "0x14", "name": "PUT_FLASH_C", "purpose": "Put Flash Access completion (Channel 3)"},
                {"hex": "0x15", "name": "GET_FLASH_NP", "purpose": "Get Flash Access non-posted request"},
                {"hex": "0x20", "name": "GET_STATUS", "purpose": "Get the 16-bit slave STATUS register"},
                {"hex": "0x21", "name": "SET_CONFIGURATION", "purpose": "Write a slave configuration register"},
                {"hex": "0x22", "name": "GET_CONFIGURATION", "purpose": "Read a slave configuration register"},
                {"hex": "0xFF", "name": "RESET", "purpose": "In-band reset"},
            ],
            "response_codes": [
                {"hex": "0x08", "name": "ACCEPT", "meaning": "Command accepted"},
                {"hex": "0x01", "name": "DEFER", "meaning": "Non-posted command deferred; completion to follow"},
                {"hex": "0x02", "name": "NON_FATAL_ERROR", "meaning": "Recoverable error"},
                {"hex": "0x03", "name": "FATAL_ERROR", "meaning": "Unrecoverable error; link must re-init"},
                {"hex": "0x04", "name": "WAIT_STATE", "meaning": "Slave inserts a wait state byte (0x0F nibble)"},
                {"hex": "0x0C", "name": "NO_RESPONSE", "meaning": "Slave has no response (0xFF on bus)"},
            ],
            "crc": {"name": "CRC-8", "poly_hex": "0x07", "init_hex": "0x00",
                    "coverage": "all command/response bytes except the CRC byte; optional, negotiated"},
            "turnaround": "2 clock cycles bus float between command and response phases",
            "addressing": "per-slave point-to-point ESPI_CS# select",
            "byte_oriented": True,
            "master_initiated": True,
        },
        "L4_REGMAP": {
            "ic_name": IC_NAME,
            "registers": [
                {"offset": "0x04", "name": "Device Identification", "desc": "eSPI version in bits 7:0"},
                {"offset": "0x08", "name": "General Capabilities and Configuration", "desc": "CRC enable (bit0), I/O mode supported (bits2:1), I/O mode select (bit3), operating frequency (bits7:4), CRC supported (bit31)"},
                {"offset": "0x10", "name": "Channel 0 Capabilities (Peripheral)", "desc": "bit0 Channel Enable, bit1 Channel Ready"},
                {"offset": "0x20", "name": "Channel 1 Capabilities (Virtual Wire)", "desc": "bit0 Channel Enable, bit1 Channel Ready"},
                {"offset": "0x30", "name": "Channel 2 Capabilities (OOB)", "desc": "bit0 Channel Enable, bit1 Channel Ready"},
                {"offset": "0x40", "name": "Channel 3 Capabilities (Flash Access)", "desc": "bit0 Channel Enable, bit1 Channel Ready"},
            ],
            "status_register": {"width_bits": 16, "bits": {
                "0": "PC_FREE", "1": "NP_FREE", "2": "VWIRE_FREE", "3": "OOB_FREE",
                "4": "PC_AVAIL", "5": "NP_AVAIL", "6": "VWIRE_AVAIL", "7": "OOB_AVAIL",
                "8": "FLASH_C_AVAIL", "9": "FLASH_NP_AVAIL", "15:10": "Reserved"}},
        },
        "L5_ADI_SPEC": {
            "ic_name": IC_NAME,
            "analog_mixed_signal": "Digital source-synchronous interface; I/O rail 1.0 V / 1.8 V; no analog blocks.",
            "io_standard": "1.0 V / 1.8 V CMOS",
            "not_applicable_reason": "eSPI is a purely digital protocol interface.",
        },
        "L6_CONTROL_LOGIC": {
            "ic_name": IC_NAME,
            "control_logic": {
                "master_fsm": ["Idle (CS# high)", "Assert CS#", "Drive CMD opcode",
                               "Drive command fields/data", "Drive CRC",
                               "Turnaround (release bus)", "Sample response code",
                               "Sample response data/status/CRC", "Deassert CS#"],
                "slave_fsm": ["Wait CS# assert", "Receive CMD + fields + CRC", "Check CRC",
                              "Turnaround (take bus)", "Insert WAIT_STATE bytes if not ready",
                              "Drive response code", "Drive response data/status/CRC",
                              "Release on CS# deassert"],
                "flow_control": "Per-channel FREE/AVAIL bits in STATUS gate PUT/GET; DEFER for non-posted; completion returned later.",
                "alert": "Slave drives ESPI_ALERT# (or ESPI_IO[1] in single-slave dedicated-alert mode); master responds with GET_STATUS.",
            },
        },
        "L7_TEST_DEBUG": {
            "ic_name": IC_NAME,
            "test_debug": {
                "in_band_reset": "CMD 0xFF resets the link",
                "status_poll": "GET_STATUS (0x20) reads channel FREE/AVAIL bits",
                "config_readback": "GET_CONFIGURATION (0x22) reads negotiated frequency/mode/CRC",
                "crc_check": "optional CRC-8 detects bit errors"},
        },
        "L8_RTL_CONSTANTS": {
            "ic_name": IC_NAME,
            "width_parameters": {
                "CMD_OPCODE_BITS": {"width_bits": 8}, "RESPONSE_CODE_BITS": {"width_bits": 8},
                "STATUS_BITS": {"width_bits": 16}, "CRC_BITS": {"width_bits": 8},
                "IO_LANES": {"legal_values": [1, 2, 4]}},
            "key_constants": {
                "CRC8_POLY": "0x07", "CRC8_INIT": "0x00", "TURNAROUND_CLOCKS": 2,
                "BOOT_FREQ_MHZ": 20, "MAX_FREQ_MHZ": 66, "WAIT_STATE_NIBBLE": "0x0F",
                "NO_RESPONSE_BYTE": "0xFF", "RESET_OPCODE": "0xFF", "GET_STATUS_OPCODE": "0x20"},
            "freq_encodings": {"000": "20MHz", "001": "25MHz", "010": "33MHz", "011": "50MHz", "100": "66MHz"},
            "io_mode_encodings": {"00": "Single", "01": "Single+Dual", "10": "Single+Quad", "11": "Single+Dual+Quad"},
        },
        "L8_TIMING_WAVEFORM": {
            "ic_name": IC_NAME,
            "timing_constants": {"clk_freq_mhz": {"boot": 20, "max": 66}, "tSU_ns": 2, "tHO_ns": 1,
                                 "cs_to_clk_setup_clocks": 2, "turnaround_clocks": 2, "reset_pulse_min_us": 100},
            "clock_and_data_waveform": {"clk_idle": "low", "drive_edge": "rising (command phase)",
                                        "sample_edge": "falling (command phase)",
                                        "turnaround": "bus floats for 2 ESPI_CLK cycles when ownership reverses"},
            "transaction_waveform": {"order": ["CS# assert", "CMD opcode (8 bits)", "command fields",
                                               "optional data", "CRC byte", "TAR (2 clk float)",
                                               "response code (8 bits)", "response data/status",
                                               "CRC byte", "CS# deassert"]},
        },
        "L9_INTEGRATION_SPEC": {
            "ic_name": IC_NAME,
            "integration_overview": {
                "master": "Chipset / PCH",
                "slaves": ["Embedded Controller (EC)", "Baseboard Management Controller (BMC)", "Super-I/O", "Flash device"],
                "topology": "single master, per-slave ESPI_CS#, shared ESPI_CLK and ESPI_IO[3:0]",
                "replaces": "Low Pin Count (LPC) bus", "pin_count": 8,
                "init_sequence": "On ESPI_RESET# deassert: Single I/O, 20 MHz, CRC off; master negotiates via GET/SET_CONFIGURATION; enable each channel (set Channel Enable, poll Channel Ready)."},
        },
        "L10_TEST_CASES": {
            "ic_name": IC_NAME,
            "test_cases": [
                {"name": "reset_defaults", "desc": "After ESPI_RESET#, link is Single I/O, 20 MHz, CRC disabled."},
                {"name": "get_status", "desc": "GET_STATUS returns 16-bit STATUS with correct FREE/AVAIL bits."},
                {"name": "config_negotiate", "desc": "SET_CONFIGURATION sets 66 MHz + Quad; GET_CONFIGURATION reads it back."},
                {"name": "vwire_tunnel", "desc": "PUT_VWIRE delivers a system-event index/data pair; slave reflects it."},
                {"name": "crc_error", "desc": "Corrupted CRC -> NON_FATAL_ERROR response."},
                {"name": "wait_state", "desc": "Slave not ready inserts 0x0F WAIT_STATE bytes before response code."}],
        },
        "L11_OTP_CONTENT": {
            "ic_name": IC_NAME,
            "otp_content": "N/A — eSPI is a bus protocol, no one-time-programmable fuse content defined.",
            "applicable": False,
        },
        "L12_BEHAVIORAL_SEQUENCES": {
            "ic_name": IC_NAME,
            "command_sequence": ["Master asserts ESPI_CS#.", "Master drives 8-bit CMD opcode on ESPI_IO.",
                                 "Master drives command-specific fields and optional payload.",
                                 "Master drives CRC byte (if enabled).",
                                 "Bus turnaround (TAR) 2 clocks — ownership passes to slave.",
                                 "Slave optionally inserts WAIT_STATE (0x0F) bytes.",
                                 "Slave drives 8-bit response code.",
                                 "Slave drives response data + 16-bit STATUS + CRC.",
                                 "Master deasserts ESPI_CS#."],
            "alert_sequence": ["Slave drives ESPI_ALERT# (service required).", "Master issues GET_STATUS.",
                               "Master reads which channel's AVAIL bit is set.", "Master issues the matching GET_* command."],
            "vwire_sequence": ["Master/slave forms VW packet: count byte + (index, data) pairs.",
                               "Each index addresses up to 4 virtual wires; data carries 4 valid bits + 4 wire-value bits.",
                               "Receiver updates the tunneled sideband signals."],
        },
        "L13_LAB_CALIBRATION": {
            "ic_name": IC_NAME,
            "lab_calibration": "N/A — purely digital protocol; no analog trim/calibration.",
            "applicable": False,
        },
        "L14_PROTOCOL_VERSIONING": {
            "spec_version": "eSPI Base Specification Revision 1.5 (Intel Doc 327432-004)",
            "lineage": [
                {"version": "LPC 1.1", "year": "2002", "summary": "Low Pin Count bus — the predecessor eSPI replaces."},
                {"version": "eSPI 0.6", "year": "2012", "summary": "Early eSPI revision."},
                {"version": "eSPI 1.0", "year": "2013", "summary": "First production eSPI base spec."},
                {"version": "eSPI 1.5", "year": "2023", "summary": "Adds Quad I/O at 66 MHz, refined Virtual Wire indices."}],
            "backward_compat_traps": [
                {"trap_name": "Not_plain_SPI", "rule": "eSPI multiplexes 4 logical channels with a command/response + turnaround protocol; it is NOT a NOR-flash SPI (single MOSI/MISO read/write).", "trap": "Decoding eSPI as classic SPI (no channels, no VW/OOB/Flash, no CRC negotiation) is wrong."},
                {"trap_name": "Replaces_LPC", "rule": "eSPI is the LPC successor — it tunnels LPC-style I/O, memory and DMA cycles plus sideband signals in-band.", "trap": "Treating eSPI as unrelated to LPC misses the Virtual Wire sideband tunneling intent."}],
        },
        "L15_ENCODING_TABLES": {
            "opcode_table": {"header_columns": ["CMD hex", "Name"], "rows": [
                ["0x00", "PUT_PC"], ["0x01", "GET_PC"], ["0x04", "PUT_NP"], ["0x02", "GET_NP"],
                ["0x10", "PUT_VWIRE"], ["0x11", "GET_VWIRE"], ["0x12", "PUT_OOB"], ["0x13", "GET_OOB"],
                ["0x14", "PUT_FLASH_C"], ["0x15", "GET_FLASH_NP"], ["0x20", "GET_STATUS"],
                ["0x21", "SET_CONFIGURATION"], ["0x22", "GET_CONFIGURATION"], ["0xFF", "RESET"]]},
            "response_table": {"header_columns": ["RSP hex", "Name"], "rows": [
                ["0x08", "ACCEPT"], ["0x01", "DEFER"], ["0x02", "NON_FATAL_ERROR"],
                ["0x03", "FATAL_ERROR"], ["0x04", "WAIT_STATE"], ["0x0C", "NO_RESPONSE"]]},
            "vwire_index_table": {"header_columns": ["Index", "Signals"], "rows": [
                ["0x02", "SLP_S3#, SLP_S4#, SLP_S5#"], ["0x03", "SUS_STAT#, PLTRST#, OOB_RST_WARN"],
                ["0x04", "OOB_RST_ACK, WAKE#, PME#"],
                ["0x05", "SLAVE_BOOT_LOAD_DONE, ERROR_FATAL, ERROR_NONFATAL, SLAVE_BOOT_LOAD_STATUS"],
                ["0x06", "SCI#, SMI#, RCIN#, HOST_RST_ACK"], ["0x07", "HOST_RST_WARN"]]},
            "freq_table": {"header_columns": ["Code", "Frequency"], "rows": [
                ["000", "20 MHz"], ["001", "25 MHz"], ["010", "33 MHz"], ["011", "50 MHz"], ["100", "66 MHz"]]},
            "io_mode_table": {"header_columns": ["Code", "Modes supported"], "rows": [
                ["00", "Single"], ["01", "Single+Dual"], ["10", "Single+Quad"], ["11", "Single+Dual+Quad"]]},
        },
        "L16_COMPLIANCE_PROPERTIES": {
            "must_have_properties": [
                "On ESPI_RESET# deassertion the link operates Single I/O, 20 MHz, CRC disabled.",
                "Every transaction is CMD(8b) + fields + optional data + CRC + turnaround + response(8b) + data + STATUS(16b) + CRC.",
                "Turnaround (TAR) is 2 ESPI_CLK cycles of bus float when ownership reverses.",
                "CRC-8 uses polynomial 0x07, init 0x00, over all bytes except the CRC byte; CRC is optional and negotiated.",
                "Each of the 4 channels is independently enabled (Channel Enable) and must report Channel Ready before use.",
                "Slave not ready inserts WAIT_STATE bytes (0x0F nibble) before its response code.",
                "Slave signals service via ESPI_ALERT#; master replies with GET_STATUS."],
            "espi_distinguishers": [
                "Four multiplexed logical channels (Peripheral/VW/OOB/Flash) — not present in classic SPI or QSPI.",
                "In-band Virtual Wire sideband tunneling.",
                "GET/SET_CONFIGURATION register negotiation.",
                "Replaces the LPC bus."],
        },
        "L17_CHANNEL_SIGNAL_CATALOG": {
            "channels": [
                {"name": "ESPI_CLK", "direction": "output (master)", "purpose": "Common source-synchronous clock 20-66 MHz; idles low."},
                {"name": "ESPI_IO0", "direction": "bidirectional", "purpose": "Command/response data lane 0 (Single/Dual/Quad)."},
                {"name": "ESPI_IO1", "direction": "bidirectional", "purpose": "Data lane 1 (Dual/Quad); ALERT in single-slave dedicated mode."},
                {"name": "ESPI_IO2", "direction": "bidirectional", "purpose": "Data lane 2 (Quad)."},
                {"name": "ESPI_IO3", "direction": "bidirectional", "purpose": "Data lane 3 (Quad)."},
                {"name": "ESPI_CS#", "direction": "output (master)", "purpose": "Active-low per-slave chip select."},
                {"name": "ESPI_RESET#", "direction": "output (master)", "purpose": "Active-low reset to all slaves; min 100 us."},
                {"name": "ESPI_ALERT#", "direction": "input (from slave)", "purpose": "Slave service-required alert."}],
            "logical_channels": [
                {"id": 0, "name": "Peripheral", "purpose": "Memory/IO/message cycles (LPC-like)."},
                {"id": 1, "name": "Virtual Wire", "purpose": "In-band tunneling of sideband signals."},
                {"id": 2, "name": "OOB", "purpose": "Tunneled SMBus/MCTP messages."},
                {"id": 3, "name": "Flash Access", "purpose": "Slave reads/writes the attached flash."}],
            "channel_counts": {"physical_signals": 8, "logical_channels": 4, "io_lanes": 4},
        },
        "L18_INTERCONNECT_TOPOLOGY": {
            "topology_type": "Single master (PCH/chipset) to one or more slaves; shared ESPI_CLK + ESPI_IO[3:0]; per-slave ESPI_CS#.",
            "supported_topologies": [
                {"name": "Single master, single slave", "description": "PCH to one EC/BMC; ESPI_IO[1] may serve as ALERT (dedicated-alert mode)."},
                {"name": "Single master, multiple slaves", "description": "Shared bus; one ESPI_CS# per slave; ESPI_ALERT# shared (shared-alert mode)."}],
            "device_classification": {"master": "Chipset / PCH", "slaves": ["EC", "BMC", "Super-I/O", "Flash"]},
            "replaces": "Low Pin Count (LPC) parallel sideband wiring",
        },
        "L19_CONSTRAINTS_PDK": {"pdk_target": "N/A (protocol spec, not a tapeout)", "io_voltage": "1.0 V / 1.8 V", "clock_mhz": [20, 66]},
        "L20_DFT_SCAN_TOPOLOGY": {"scan_topology": "N/A — protocol spec, no DFT defined."},
        "L21_POWER_INTENT": {"power_domains": ["1.0 V / 1.8 V I/O rail"],
                             "power_considerations": "Low-voltage source-synchronous signaling reduces sideband pin count and power vs LPC."},
        "L22_VERIFICATION_PLAN": {"verification_items": ["Reset defaults", "Config negotiation",
                                  "Per-channel flow control", "Virtual Wire tunneling", "CRC error handling",
                                  "WAIT_STATE insertion", "ALERT/GET_STATUS handshake"]},
        "L23_SECURITY_REQUIREMENTS": {"attack_surface": [
            "Flash Access channel exposes flash read/write — must be access-controlled.",
            "OOB tunneling of SMBus/MCTP must validate message source."],
            "security_notes": "eSPI itself defines no encryption; platform must gate Flash and OOB channels."},
    }


def apply_espi_synth(generated_docs_dir, is_espi_flag: bool,
                     ic_name: Optional[str]) -> None:
    """Force-merge eSPI-canonical content into the generated L-docs when the
    eSPI signature matched. No-op otherwise."""
    if not is_espi_flag:
        return
    gd = Path(generated_docs_dir)
    canon = _canon()
    name = ic_name or IC_NAME
    for doc in _FLAT_DOCS:
        p = gd / f"{doc}.json"
        if not p.is_file():
            continue
        d = json.loads(p.read_text())
        d.update(canon.get(doc, {}))
        d["ic_name"] = name
        p.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n")
    for doc in _FIELDS_DOCS:
        p = gd / f"{doc}.json"
        if not p.is_file():
            continue
        d = json.loads(p.read_text())
        f = d.get("fields")
        if not isinstance(f, dict):
            f = {}
        f.update(canon.get(doc, {}))
        d["fields"] = f
        d["ic_name"] = name
        p.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n")
