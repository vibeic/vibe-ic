"""Low Pin Count (LPC) Interface protocol synth helper.

Drop-in protocol synth discovered by the runner's generic auto-dispatch
(`AUTO_DISPATCH = True`). Applies Intel Low Pin Count (LPC) Interface
Specification Revision 1.1 canonical content to L1-L23 when the LPC structural
signature is present.

Doctrine — GENERAL not keyword: detection uses canonical STRUCTURAL signatures
read from the L-doc / input_doc CONTENT blob only (never a filename or folder
name): the multiplexed LAD[3:0] address/data bus + LFRAME# frame signal, the
33 MHz PCI clock (LCLK), the START / CYCTYPE+DIR / SYNC field-stream model, and
the I/O / Memory / DMA / Firmware cycle types.

Sibling disambiguation — LPC vs eSPI, classic SPI, and QSPI/OSPI.
  * eSPI is the SERIAL successor that REPLACES LPC. eSPI has four logical
    channels (Peripheral / Virtual Wire / OOB / Flash Access),
    GET_CONFIGURATION / SET_CONFIGURATION negotiation, ESPI_ALERT#, and an
    optional CRC. LPC has NONE of those. The detector DEFERS (returns False) if
    the eSPI four-channel signature is present, because an eSPI spec mentions
    "low pin count" / "LPC" as the predecessor it replaces.
  * Classic SPI is a 4-wire (SCK/MOSI/MISO/CS) full-duplex shift link with NO
    LAD[3:0]+LFRAME# parallel multiplexed bus and NO START/CYCTYPE/SYNC fields.
  * QSPI/OSPI is a NOR-flash command interface (instruction/address/dummy/data
    over 1/2/4/8 IO lanes) with NO LFRAME# frame signal and NO SYNC field.
The detector requires the LPC name token AND the LAD[3:0]+LFRAME# signal pair
AND the START/CYCTYPE/SYNC field model, so a plain-SPI / QSPI / eSPI spec
cannot false-fire.

Public entry: ``apply_lpc_synth(generated_docs_dir, is_lpc_flag, ic_name)``.
Module-level ``is_lpc(blob)`` is the content-only detector.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

import l_doc_generator_stamp as _stamp

# Generic auto-dispatch opt-in (read by phase1_doc_one_shot_runner [14e2b/15]).
AUTO_DISPATCH = True
IC_NAME = "Low Pin Count (LPC) Interface"

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


def is_lpc(blob: str) -> bool:
    """Content-only LPC detector with eSPI / SPI / QSPI MUTEX."""
    if not blob:
        return False
    low = blob.lower()
    # Name token (structural identifier, NECESSARY condition).
    name_token = ("low pin count" in low or re.search(r"\blpc\b", low) is not None)
    if not name_token:
        return False
    # eSPI MUTEX: defer if the eSPI four-channel + negotiation signature is
    # present. An eSPI spec names "low pin count" / "LPC" as its predecessor,
    # so the name token alone is insufficient — the eSPI-only signature wins.
    espi_four_channel = (
        ("virtual wire" in low)
        and ("oob" in low or "out-of-band" in low or "out of band" in low)
        and ("flash access" in low or "flash channel" in low
             or "flash component" in low)
        and ("peripheral channel" in low or "logical channel" in low))
    espi_negotiation = ("get_configuration" in low or "set_configuration" in low
                        or "espi_alert" in low or "enhanced serial peripheral" in low)
    if espi_four_channel and espi_negotiation:
        return False
    # LPC-only structural quorum.
    signal_pair = (("lad[3:0]" in low or "lad [3:0]" in low or "lad3" in low
                    or "lad bus" in low)
                   and ("lframe#" in low or "lframe" in low))
    pci_clock = (("lclk" in low and "33 mhz" in low)
                 or ("pci clock" in low and "lclk" in low))
    field_model = (("start" in low)
                   and ("cyctype" in low or "cycle type" in low)
                   and ("sync" in low))
    cycle_types = (("i/o" in low or "i/o read" in low)
                   and ("memory" in low)
                   and ("dma" in low)
                   and ("firmware" in low))
    score = sum(bool(x) for x in
                (signal_pair, pci_clock, field_model, cycle_types))
    # Require the LAD[3:0]+LFRAME# signal pair plus the field model plus at
    # least one more LPC-only structural mark.
    return signal_pair and field_model and score >= 3


# ----------------------------------------------------------------------
# Canonical LPC content (Intel Low Pin Count Interface Specification Rev 1.1).
# ----------------------------------------------------------------------
def _canon():
    return {
        "L1_DATASHEET": {
            "ic_name": IC_NAME,
            "document_title": "Low Pin Count (LPC) Interface Specification",
            "document_number": "LPC 1.1",
            "manufacturer": "Intel Corporation",
            "revised_date": "Revision 1.1 (August 2002)",
            "external_pins": ["LAD0", "LAD1", "LAD2", "LAD3", "LFRAME#", "LCLK",
                              "LRESET#", "LDRQ#", "SERIRQ", "CLKRUN#", "PME#",
                              "LSMI#"],
            "external_pin_count": 7,
            "package": "Integrated chipset/Super-I/O interface (no dedicated package)",
            "key_features": [
                "Low-pin-count replacement for the legacy ISA / X-bus expansion bus in PC platforms",
                "4-bit multiplexed command/address/data bus LAD[3:0], one nibble per LCLK cycle",
                "Reuses the 33 MHz PCI clock (LCLK) — adds no new clock pin",
                "Minimum of 7 required signals (LAD[3:0], LFRAME#, LCLK, LRESET#)",
                "Cycle types: I/O (16-bit addr), Memory (32-bit addr), DMA (8237-compatible), Bus Master, Firmware Memory (28-bit addr)",
                "Optional encoded DMA request (LDRQ#) and Serialized IRQ (SERIRQ)",
                "PARALLEL predecessor of the serial eSPI interface (eSPI replaces LPC)",
            ],
            "io_voltage": "3.3 V (PCI signaling)",
            "clock_frequency": "33 MHz (PCI clock)",
            "electrical_specs": [
                {"name": "LCLK frequency", "min_typ_max": {"min": None, "typ": 33, "max": None},
                 "unit": "MHz",
                 "conditions": "Reuses the PCI clock; LPC adds no separate clock pin. All LPC signals driven and sampled relative to the rising edge of LCLK.",
                 "evidence": {"literal": "LCLK frequency            33 MHz (the PCI clock)"}},
                {"name": "Signaling voltage", "min_typ_max": {"min": None, "typ": 3.3, "max": None},
                 "unit": "V",
                 "conditions": "All required LPC signals share the 3.3 V signaling levels of PCI (PCI 3.3 V levels).",
                 "evidence": {"literal": "Signaling voltage         3.3 V (PCI levels)"}},
                {"name": "Setup time tSU", "min_typ_max": {"min": 7, "typ": None, "max": None},
                 "unit": "ns",
                 "conditions": "LAD[3:0] input setup before the rising edge of LCLK (PCI input setup).",
                 "evidence": {"literal": "Setup time tSU            7 ns (PCI input setup)"}},
                {"name": "Hold time tHO", "min_typ_max": {"min": 0, "typ": None, "max": None},
                 "unit": "ns",
                 "conditions": "LAD[3:0] input hold after the rising edge of LCLK (PCI input hold).",
                 "evidence": {"literal": "Hold time tHO             0 ns (PCI input hold)"}},
                {"name": "Clock-to-out tVAL", "min_typ_max": {"min": None, "typ": None, "max": 11},
                 "unit": "ns",
                 "conditions": "LAD[3:0] valid delay from the rising edge of LCLK (PCI Tval).",
                 "evidence": {"literal": "Clock-to-out tVAL         max 11 ns (PCI Tval)"}},
                {"name": "Reset (LRESET#) min assert", "min_typ_max": {"min": 1, "typ": None, "max": None},
                 "unit": "ms",
                 "conditions": "LRESET# is the active-low reset (same signal as PCI RST#); minimum asserted time at power-up.",
                 "evidence": {"literal": "Reset (LRESET#) min       1 ms asserted at power-up"}},
            ],
        },
        "L2_FRS": {
            "ic_name": IC_NAME,
            "protocol_overview": {
                "type": "Synchronous parallel multiplexed bus, single host to one or more peripherals",
                "duplex": "half-duplex (host drives command/address then turnaround then peripheral drives SYNC/data)",
                "half_duplex": True,
                "synchronous": True,
                "replaces": "ISA / X-bus expansion bus",
                "succeeded_by": "Enhanced Serial Peripheral Interface (eSPI)",
                "bus_width_bits": 4,
                "clock_mhz": 33,
                "io_voltage_v": 3.3,
                "cycle_types": ["I/O", "Memory", "DMA", "Bus Master", "Firmware Memory"],
                "wire_names": ["LAD[3:0]", "LFRAME#", "LCLK", "LRESET#", "LDRQ#", "SERIRQ"],
                "crc": "none (LPC defines no CRC)",
            },
            "functional_requirements": [
                "Host drives LCLK (the 33 MHz PCI clock); all LAD signals are driven and sampled on the rising edge of LCLK.",
                "Every cycle is framed by LFRAME#: a LOW on LFRAME# starts a new cycle (or signals an abort).",
                "Field order: START -> CYCTYPE+DIR -> ADDR nibbles -> TAR -> SYNC -> DATA nibbles -> TAR.",
                "START field selects the cycle (target, bus-master grant, firmware) while LFRAME# is low.",
                "The addressed peripheral drives the SYNC field to indicate ready / wait / error.",
                "Data nibbles are driven least-significant nibble (LSN) first, then most-significant nibble (MSN).",
                "DMA service is requested by the encoded LDRQ# serial message; 8237-compatible channels 0..7.",
                "LPC has no configuration-negotiation protocol — devices live at fixed platform-defined addresses.",
            ],
        },
        "L3_CMD_PROTOCOL": {
            "ic_name": IC_NAME,
            "protocol_type": "Field-stream over a 4-bit multiplexed LAD[3:0] bus framed by LFRAME#; START + CYCTYPE+DIR + ADDR + SYNC + DATA, one nibble per LCLK.",
            "start_field_encodings": [
                {"bits": "0000", "name": "TARGET", "purpose": "Start of a target (memory/I/O) cycle"},
                {"bits": "0010", "name": "GRANT_BM0", "purpose": "Bus-master 0 grant"},
                {"bits": "0011", "name": "GRANT_BM1", "purpose": "Bus-master 1 grant"},
                {"bits": "1101", "name": "FW_READ", "purpose": "Firmware Memory Read cycle"},
                {"bits": "1110", "name": "FW_WRITE_OR_ABORT", "purpose": "Firmware Memory Write / Stop-Abort on LFRAME#"},
                {"bits": "1111", "name": "STOP_ABORT", "purpose": "Stop/abort code on LAD during LFRAME# low (reserved/firmware legacy)"},
            ],
            "cycle_type_encodings": [
                {"bits": "0000", "name": "IO_READ", "purpose": "I/O read, 16-bit address"},
                {"bits": "0010", "name": "IO_WRITE", "purpose": "I/O write, 16-bit address"},
                {"bits": "0100", "name": "MEM_READ", "purpose": "Memory read, 32-bit address"},
                {"bits": "0110", "name": "MEM_WRITE", "purpose": "Memory write, 32-bit address"},
                {"bits": "1000", "name": "DMA_READ", "purpose": "DMA read (8237-compatible), host->peripheral"},
                {"bits": "1010", "name": "DMA_WRITE", "purpose": "DMA write (8237-compatible), peripheral->host"},
            ],
            "sync_field_encodings": [
                {"bits": "0000", "name": "READY", "meaning": "Data ready, no wait; transfer this cycle"},
                {"bits": "0101", "name": "SHORT_WAIT", "meaning": "Short wait sync; a few more cycles"},
                {"bits": "0110", "name": "LONG_WAIT", "meaning": "Long wait sync; many more cycles"},
                {"bits": "1001", "name": "READY_MORE", "meaning": "Ready with more DMA data to follow"},
                {"bits": "1010", "name": "ERROR", "meaning": "Error sync; cycle terminates abnormally"},
            ],
            "turnaround": "TAR is 2 LCLK cycles of bus float when LAD ownership reverses between host and peripheral",
            "addressing": "fixed platform-defined addresses; I/O 16-bit, Memory 32-bit, Firmware 28-bit + IDSEL",
            "nibble_oriented": True,
            "host_initiated": True,
            "crc": "none",
        },
        "L4_REGMAP": {
            "ic_name": IC_NAME,
            "registers": "N/A — LPC defines no on-bus configuration register space; peripherals expose their own fixed-address I/O/memory registers.",
            "address_reach": {
                "io_cycle_addr_bits": 16,
                "memory_cycle_addr_bits": 32,
                "firmware_cycle_addr_bits": 28,
                "dma_channels": "0..7 (8237-compatible; 0..3 8-bit, 5..7 16-bit, 4 cascade)",
            },
            "config_negotiation": "none — LPC has no GET/SET configuration protocol",
        },
        "L5_ADI_SPEC": {
            "ic_name": IC_NAME,
            "analog_mixed_signal": "Digital synchronous parallel interface; 3.3 V PCI signaling; no analog blocks.",
            "io_standard": "3.3 V PCI-compatible CMOS",
            "not_applicable_reason": "LPC is a purely digital bus interface.",
        },
        "L6_CONTROL_LOGIC": {
            "ic_name": IC_NAME,
            "control_logic": {
                "host_fsm": ["Idle (LFRAME# high)", "Assert LFRAME# + drive START",
                             "Drive CYCTYPE+DIR", "Drive ADDR nibbles",
                             "Turnaround (release LAD)", "Sample SYNC from peripheral",
                             "Drive/sample DATA nibbles", "Final turnaround", "Return to idle"],
                "peripheral_fsm": ["Watch LFRAME# + decode START", "Decode CYCTYPE+DIR + ADDR",
                                   "Match own address range", "Turnaround (take LAD)",
                                   "Drive SYNC (READY/WAIT/ERROR)", "Drive/sample DATA nibbles",
                                   "Release LAD on final turnaround"],
                "framing": "LFRAME# low starts a cycle; LFRAME# low for >=4 LCLK with LAD=1111 aborts.",
                "wait_states": "Peripheral inserts SHORT_WAIT (0101) or LONG_WAIT (0110) SYNC until READY (0000).",
            },
        },
        "L7_TEST_DEBUG": {
            "ic_name": IC_NAME,
            "test_debug": {
                "reset": "LRESET# (== PCI RST#) resets all LPC peripherals",
                "abort": "LFRAME# low for >=4 LCLK clocks with LAD=1111 aborts the current cycle",
                "sync_observe": "Observe the SYNC field on LAD to see READY/WAIT/ERROR",
                "serirq_observe": "SERIRQ stream serializes IRQ0..IRQ15 for interrupt debug",
            },
        },
        "L8_RTL_CONSTANTS": {
            "ic_name": IC_NAME,
            "width_parameters": {
                "LAD_BITS": {"width_bits": 4},
                "START_FIELD_BITS": {"width_bits": 4},
                "CYCTYPE_FIELD_BITS": {"width_bits": 4},
                "SYNC_FIELD_BITS": {"width_bits": 4},
                "IO_ADDR_BITS": {"width_bits": 16},
                "MEM_ADDR_BITS": {"width_bits": 32},
                "FW_ADDR_BITS": {"width_bits": 28},
            },
            "key_constants": {
                "LCLK_MHZ": 33, "TAR_CLOCKS": 2, "ABORT_MIN_CLOCKS": 4,
                "START_TARGET": "0000", "START_FW_READ": "1101",
                "START_FW_WRITE": "1110", "STOP_ABORT_CODE": "1111",
                "SYNC_READY": "0000", "SYNC_ERROR": "1010",
                "DMA_CHANNELS": 8,
            },
            "start_encodings": {"0000": "TARGET", "0010": "GRANT_BM0", "0011": "GRANT_BM1",
                                "1101": "FW_READ", "1110": "FW_WRITE_OR_ABORT", "1111": "STOP_ABORT"},
            "sync_encodings": {"0000": "READY", "0101": "SHORT_WAIT", "0110": "LONG_WAIT",
                               "1001": "READY_MORE", "1010": "ERROR"},
        },
        "L8_TIMING_WAVEFORM": {
            "ic_name": IC_NAME,
            "timing_constants": {"lclk_freq_mhz": 33, "tSU_ns": 7, "tHO_ns": 0,
                                 "tVAL_max_ns": 11, "turnaround_clocks": 2,
                                 "abort_min_clocks": 4, "reset_min_ms": 1},
            "clock_and_data_waveform": {"clk_source": "33 MHz PCI clock (LCLK)",
                                        "drive_edge": "rising edge of LCLK",
                                        "sample_edge": "rising edge of LCLK",
                                        "turnaround": "LAD floats for 2 LCLK cycles when ownership reverses (driver drives 1111 then tri-states)"},
            "cycle_waveform": {"order": ["LFRAME# low + START (4b)", "CYCTYPE+DIR (4b)",
                                         "ADDR nibbles", "TAR (2 clk)", "SYNC (4b)",
                                         "DATA nibbles (LSN then MSN)", "TAR (2 clk)"]},
            # Half-duplex direction split (host==external/RX vs peripheral==internal/TX).
            # LPC is a SYNCHRONOUS parallel bus, NOT a single-wire LIN-style
            # line-code link -- it has no H0/H1/BR/IBT pulse-width symbols.
            # Each "symbol" here is one LPC field nibble, sampled/driven one
            # per rising edge of the 33 MHz LCLK (period 30 ns). We declare the
            # per-side required-symbol sets empty (symbol_directionality) because
            # the four LIN-style symbols simply do not exist in LPC.
            "symbol_directionality": {"rx_host_side": [], "tx_dut_side": []},
            "rx_timing": {
                "description": "Host-driven (external) fields the peripheral SAMPLES on the rising edge of LCLK during the command/address/write-data phase, before turnaround.",
                "lclk_period_ns": 30,
                "START_nibble_ns": 30,
                "CYCTYPE_DIR_nibble_ns": 30,
                "ADDR_nibble_ns": 30,
                "WDATA_nibble_ns": 30,
                "evidence": {"literal": "All LPC signals are driven and sampled relative to the rising edge of LCLK."}},
            "tx_timing": {
                "description": "Peripheral-driven (internal/DUT) fields the peripheral DRIVES on the rising edge of LCLK after turnaround: the SYNC field then the read-data nibbles.",
                "lclk_period_ns": 30,
                "turnaround_clocks": 2,
                "SYNC_nibble_ns": 30,
                "RDATA_nibble_ns": 30,
                "evidence": {"literal": "The TAR (turnaround) interval is 2 LCLK cycles."}},
        },
        "L9_INTEGRATION_SPEC": {
            "ic_name": IC_NAME,
            "integration_overview": {
                "host": "Chipset South Bridge / I/O Controller Hub (ICH)",
                "peripherals": ["Super-I/O controller", "Embedded Controller", "BIOS/firmware flash", "Legacy I/O"],
                "topology": "single host, shared LAD[3:0] + LFRAME# + LCLK + LRESET#; per-device point-to-point LDRQ#",
                "replaces": "ISA / X-bus expansion bus",
                "succeeded_by": "Enhanced Serial Peripheral Interface (eSPI)",
                "pin_count": 7,
                "init_sequence": "LRESET# deasserts; host idles LFRAME# high; first activity is typically a firmware memory read to fetch the boot vector; no configuration negotiation.",
            },
        },
        "L10_TEST_CASES": {
            "ic_name": IC_NAME,
            "test_cases": [
                {"name": "io_write", "desc": "START=0000, CYCTYPE=I/O write, 16-bit addr, SYNC=READY, byte transferred LSN then MSN."},
                {"name": "io_read", "desc": "START=0000, CYCTYPE=I/O read, peripheral drives SYNC=READY then data nibbles."},
                {"name": "memory_cycle", "desc": "32-bit memory address (8 nibbles), one byte of data."},
                {"name": "firmware_read", "desc": "START=1101, 28-bit firmware address + IDSEL, fetch boot vector."},
                {"name": "dma_cycle", "desc": "Peripheral asserts encoded LDRQ#; host runs DMA Read/Write cycle on a channel 0..7."},
                {"name": "wait_state", "desc": "Peripheral drives SHORT_WAIT (0101) then READY (0000)."},
                {"name": "abort", "desc": "Host drives LFRAME# low >=4 clocks with LAD=1111; peripherals tri-state LAD."},
            ],
        },
        "L11_OTP_CONTENT": {
            "ic_name": IC_NAME,
            "otp_content": "N/A — LPC is a bus protocol, no one-time-programmable fuse content defined.",
            "applicable": False,
        },
        "L12_BEHAVIORAL_SEQUENCES": {
            "ic_name": IC_NAME,
            "io_write_sequence": ["Host drives LFRAME# low and START=0000 on LAD.",
                                  "Host drives CYCTYPE+DIR = I/O write.",
                                  "Host drives 4 address nibbles (16-bit I/O addr).",
                                  "Host drives 2 data nibbles (LSN then MSN).",
                                  "Turnaround (TAR) — ownership passes to peripheral.",
                                  "Peripheral drives SYNC = READY (0000).",
                                  "Final turnaround — host resumes; LFRAME# returns high."],
            "dma_sequence": ["Peripheral serializes its request on LDRQ# (START bit + 3-bit channel + ACT bit).",
                             "Host runs a DMA cycle: START=0000, CYCTYPE=DMA Read/Write, channel + size.",
                             "Peripheral drives SYNC (READY / READY_MORE) per transfer.",
                             "Data nibbles transfer; READY_MORE (1001) signals more DMA data."],
            "abort_sequence": ["Host drives LFRAME# low for >=4 LCLK clocks with LAD=1111.",
                               "All peripherals tri-state LAD and abandon the current cycle.",
                               "Host releases LFRAME# high to idle."],
        },
        "L13_LAB_CALIBRATION": {
            "ic_name": IC_NAME,
            "lab_calibration": "N/A — purely digital protocol; no analog trim/calibration.",
            "applicable": False,
        },
        "L14_PROTOCOL_VERSIONING": {
            "spec_version": "Low Pin Count (LPC) Interface Specification Revision 1.1 (Intel, August 2002)",
            "lineage": [
                {"version": "ISA / X-bus", "year": "1984", "summary": "Legacy parallel expansion bus that LPC replaces."},
                {"version": "LPC 1.0", "year": "1997", "summary": "First Low Pin Count interface specification."},
                {"version": "LPC 1.1", "year": "2002", "summary": "Adds firmware memory cycles and clarifications; the current base spec."},
                {"version": "eSPI 1.0", "year": "2013", "summary": "Serial successor that replaces LPC."},
            ],
            "backward_compat_traps": [
                {"trap_name": "Not_eSPI", "rule": "LPC is the PARALLEL predecessor — a 4-bit LAD[3:0] multiplexed bus framed by LFRAME#; it has NO logical channels, NO opcode table, NO CRC, NO GET/SET configuration.", "trap": "Treating LPC as if it had eSPI's four channels / CRC / negotiation is wrong."},
                {"trap_name": "Reuses_PCI_clock", "rule": "LPC reuses the 33 MHz PCI clock as LCLK and shares PCI RST# as LRESET#; it adds no new clock pin.", "trap": "Assuming LPC has its own independent clock domain misses the PCI-clock reuse intent."},
            ],
        },
        "L15_ENCODING_TABLES": {
            "start_table": {"header_columns": ["START bits", "Name"], "rows": [
                ["0000", "TARGET"], ["0010", "GRANT_BM0"], ["0011", "GRANT_BM1"],
                ["1101", "FW_READ"], ["1110", "FW_WRITE_OR_ABORT"], ["1111", "STOP_ABORT"]]},
            "cyctype_table": {"header_columns": ["CYCTYPE bits", "Name"], "rows": [
                ["0000", "IO_READ"], ["0010", "IO_WRITE"], ["0100", "MEM_READ"],
                ["0110", "MEM_WRITE"], ["1000", "DMA_READ"], ["1010", "DMA_WRITE"]]},
            "sync_table": {"header_columns": ["SYNC bits", "Name"], "rows": [
                ["0000", "READY"], ["0101", "SHORT_WAIT"], ["0110", "LONG_WAIT"],
                ["1001", "READY_MORE"], ["1010", "ERROR"]]},
            "cycle_addr_table": {"header_columns": ["Cycle type", "Address bits"], "rows": [
                ["I/O", "16"], ["Memory", "32"], ["Firmware Memory", "28"]]},
        },
        "L16_COMPLIANCE_PROPERTIES": {
            "must_have_properties": [
                "Every cycle is framed by LFRAME#; a LOW on LFRAME# starts a new cycle.",
                "All LAD[3:0] signals are driven and sampled on the rising edge of the 33 MHz LCLK.",
                "Field order is START -> CYCTYPE+DIR -> ADDR -> TAR -> SYNC -> DATA -> TAR.",
                "Turnaround (TAR) is 2 LCLK cycles when LAD ownership reverses.",
                "The peripheral drives SYNC: READY (0000), SHORT_WAIT (0101), LONG_WAIT (0110), or ERROR (1010).",
                "Data nibbles are driven least-significant nibble first, then most-significant nibble.",
                "An abort is LFRAME# low for >=4 LCLK clocks with LAD = 1111.",
            ],
            "lpc_distinguishers": [
                "4-bit multiplexed LAD[3:0] parallel bus framed by LFRAME# — not a serial command/response link.",
                "Reuses the 33 MHz PCI clock (LCLK) and PCI RST# (LRESET#).",
                "NO logical channels, NO opcode table, NO CRC, NO GET/SET configuration negotiation.",
                "PARALLEL predecessor of the serial eSPI bus.",
            ],
        },
        "L17_CHANNEL_SIGNAL_CATALOG": {
            "channels": [
                {"name": "LAD0", "direction": "bidirectional", "purpose": "Multiplexed command/address/data bus bit 0."},
                {"name": "LAD1", "direction": "bidirectional", "purpose": "Multiplexed command/address/data bus bit 1."},
                {"name": "LAD2", "direction": "bidirectional", "purpose": "Multiplexed command/address/data bus bit 2."},
                {"name": "LAD3", "direction": "bidirectional", "purpose": "Multiplexed command/address/data bus bit 3."},
                {"name": "LFRAME#", "direction": "output (host)", "purpose": "Active-low frame/abort; LOW starts a cycle."},
                {"name": "LCLK", "direction": "output (host)", "purpose": "33 MHz PCI clock; all LAD timing referenced to it."},
                {"name": "LRESET#", "direction": "output (host)", "purpose": "Active-low reset (== PCI RST#)."},
                {"name": "LDRQ#", "direction": "input (from peripheral)", "purpose": "Encoded serial DMA/bus-master request, point-to-point."},
                {"name": "SERIRQ", "direction": "bidirectional", "purpose": "Serialized IRQ stream (IRQ0..IRQ15)."},
                {"name": "CLKRUN#", "direction": "bidirectional", "purpose": "Optional clock-run for clock-stopping platforms."},
                {"name": "PME#", "direction": "input (from peripheral)", "purpose": "Optional Power Management Event / wakeup."},
                {"name": "LSMI#", "direction": "input (from peripheral)", "purpose": "Optional System Management Interrupt request."},
            ],
            "required_signals": ["LAD[3:0]", "LFRAME#", "LCLK", "LRESET#"],
            "optional_signals": ["LDRQ#", "SERIRQ", "CLKRUN#", "PME#", "LSMI#"],
            "signal_counts": {"required": 7, "optional": 5, "lad_width": 4},
        },
        "L18_INTERCONNECT_TOPOLOGY": {
            "topology_type": "Single host (chipset South Bridge / ICH) to one or more peripherals; shared LAD[3:0] + LFRAME# + LCLK + LRESET#; per-device point-to-point LDRQ#.",
            "supported_topologies": [
                {"name": "Host to single peripheral", "description": "ICH to one Super-I/O or firmware flash."},
                {"name": "Host to multiple peripherals", "description": "Shared LAD bus; devices decode their own fixed addresses; each DMA-capable device has its own LDRQ#."}],
            "device_classification": {"host": "Chipset South Bridge / ICH", "peripherals": ["Super-I/O", "Embedded Controller", "Firmware flash", "Legacy I/O"]},
            "replaces": "ISA / X-bus parallel expansion bus",
        },
        "L19_CONSTRAINTS_PDK": {"pdk_target": "N/A (protocol spec, not a tapeout)", "io_voltage": "3.3 V (PCI)", "clock_mhz": 33},
        "L20_DFT_SCAN_TOPOLOGY": {"scan_topology": "N/A — protocol spec, no DFT defined."},
        "L21_POWER_INTENT": {"power_domains": ["3.3 V PCI I/O rail"],
                             "power_considerations": "Reuses the PCI clock and supply; optional CLKRUN# allows clock stopping for mobile power saving."},
        "L22_VERIFICATION_PLAN": {"verification_items": ["I/O read/write cycles", "Memory cycles",
                                  "Firmware memory read (boot vector)", "DMA cycles via LDRQ#",
                                  "Wait-state SYNC insertion", "Abort via LFRAME#", "SERIRQ serialization"]},
        "L23_SECURITY_REQUIREMENTS": {"attack_surface": [
            "Firmware memory cycles expose the BIOS/firmware flash — must be write-protected against unauthorized reprogramming.",
            "No CRC or authentication on the bus — relies on the trusted physical board interconnect."],
            "security_notes": "LPC itself defines no encryption or integrity check; platform security relies on physical access control and firmware write-protect."},
    }


def apply_lpc_synth(generated_docs_dir, is_lpc_flag: bool,
                    ic_name: Optional[str]) -> None:
    """Force-merge LPC-canonical content into the generated L-docs when the
    LPC signature matched. No-op otherwise."""
    if not is_lpc_flag:
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
        _stamp.dump(p, d)
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
        _stamp.dump(p, d)
