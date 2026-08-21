"""UART-class protocol synth helper.

v0.1.80 — ic_class-gated overlay for `serial_peripheral_protocol` specs
that exhibit the UART structural signature (SIN+SOUT pin pair OR
PC16550D / 16450 lineage terminology + start/data/stop framing).
Applies PC16550D-spec-canonical content to L1-L18 + L21.

Doctrine: structural-keyword detection IS general within an ic_class
(mirrors AMBA-AXI / SPI / I2C synth approach). Any 16450/16550-family
UART (PC16550D, NS16550A, Synopsys DesignWare UART, ARM PL011 software
register-compatible, Xilinx UARTLite) exhibits the same signature.

Public entry: `apply_uart_synth(generated_docs_dir, is_uart, uart_ic_name)`.
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


def apply_uart_synth(generated_docs_dir: Path, is_uart: bool,
                     uart_ic_name: Optional[str]) -> None:
    """Apply UART-specific synth when the structural signature matched."""
    if not is_uart:
        return
    gd = generated_docs_dir

    # Force ic_name across the 14 main L docs.
    if uart_ic_name is not None:
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
                d["ic_name"] = uart_ic_name
                _write(q, d)

    # L1 datasheet metadata
    p = gd / "L1_DATASHEET.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("document_title", "PC16550D Universal Asynchronous Receiver/Transmitter with FIFOs")
        d.setdefault("document_number", "TL/C/8652")
        d.setdefault("manufacturer", "National Semiconductor Corporation")
        d.setdefault("revised_date", "June 1995")
        d.setdefault("copyright", "© 1995 National Semiconductor Corporation")
        d.setdefault("external_pins", [
            "SIN", "SOUT", "CTS", "RTS", "DSR", "DTR", "DCD", "RI",
            "OUT1", "OUT2", "TXRDY", "RXRDY", "BAUDOUT", "RCLK",
            "XIN", "XOUT", "INTR", "MR", "ADS", "DDIS", "RD", "WR",
            "CS0", "CS1", "CS2", "A0", "A1", "A2",
            "D0", "D1", "D2", "D3", "D4", "D5", "D6", "D7",
            "VDD", "VSS",
        ])
        d.setdefault("external_pin_count", 40)
        d.setdefault("package", "40-pin DIP / PLCC")
        d.setdefault("key_features", [
            "Capable of running all existing 16450 software.",
            "Pin-for-pin compatible with the existing 16450 except for TXRDY (24) and RXRDY (29).",
            "After reset, all registers are identical to the 16450 register set.",
            "In FIFO mode, transmitter and receiver are each buffered with 16-byte FIFOs to reduce CPU interrupts.",
            "Adds or deletes standard asynchronous communication bits (start, stop, and parity) to/from the serial data.",
            "Holding and shift registers in 16450 mode eliminate the need for precise synchronization between CPU and serial data.",
            "Independently controlled transmit, receive, line status, and data set interrupts.",
            "Programmable baud generator divides any input clock by 1 to (2^16 - 1) and generates the 16× clock.",
            "Independent receiver clock input (RCLK).",
            "MODEM control functions: CTS, RTS, DSR, DTR, RI, DCD.",
            "Fully programmable serial-interface characteristics: 5-, 6-, 7-, or 8-bit characters; even, odd, or no-parity bit generation and detection; 1-, 1½-, or 2-stop-bit generation; baud generation DC to 1.5 Mbaud.",
            "False start-bit detection.",
            "Complete status reporting capabilities.",
            "TRI-STATE TTL drive for data and control buses.",
            "Line-break generation and detection.",
            "Internal diagnostic capabilities: loopback for fault isolation; break, parity, overrun, framing error simulation.",
            "Full prioritized interrupt system controls.",
            "Fabricated using National Semiconductor M2CMOS process.",
        ])
        d.setdefault("modes_of_operation", [
            {"name": "Character mode (16450 Mode)", "description": "Backward-compatible 16450 mode; FIFOs disabled. Each character causes an interrupt."},
            {"name": "FIFO mode",                   "description": "Enabled by writing FCR0=1. 16-byte RX + 16-byte TX FIFOs; trigger-level-based interrupts."},
            {"name": "Loopback diagnostic mode",    "description": "Enabled by MCR bit 4. SOUT is internally connected to SIN; CTS/DSR/DCD/RI driven by MCR bits."},
            {"name": "FIFO Polled Mode",            "description": "Software polls status flags instead of using interrupts; no INTR generation while polled."},
        ])
        d.setdefault("overview",
            "The PC16550D is an improved version of the original 16450 Universal Asynchronous Receiver/Transmitter (UART). Functionally identical to the 16450 on powerup (Character mode), the PC16550D can be put into an alternate mode (FIFO mode) to relieve the CPU of excessive software overhead. In FIFO mode, internal FIFOs are activated allowing 16 bytes (plus 3 bits of error data per byte in the RCVR FIFO) to be stored in both receive and transmit modes.")
        d.setdefault("block_diagram_components", [
            "Receiver Buffer Register (RBR)", "Transmitter Holding Register (THR)",
            "Receiver Shift Register", "Transmitter Shift Register",
            "Receiver FIFO (16 bytes + 3 bits error per byte)",
            "Transmitter FIFO (16 bytes)",
            "Baud Generator Divisor Latches (DLL, DLM)",
            "Programmable Baud Generator + 16× clock divider",
            "Line Control Register (LCR)", "Line Status Register (LSR)",
            "Interrupt Enable Register (IER)",
            "Interrupt Identification Register (IIR)",
            "FIFO Control Register (FCR)", "MODEM Control Register (MCR)",
            "MODEM Status Register (MSR)", "Scratchpad Register (SCR)",
            "Interrupt logic + INTR output",
            "TRI-STATE bus driver for D7-D0", "Loopback control",
        ])
        d.setdefault("process_technology", "National Semiconductor M2CMOS")
        _write(p, d)

    # L2 FRS
    p = gd / "L2_FRS.json"
    if p.is_file():
        d = _read(p)
        po = d.setdefault("protocol_overview", {})
        if isinstance(po, dict):
            po.setdefault("type", "Asynchronous serial (start/data/parity/stop framing)")
            po.setdefault("duplex", "full duplex (independent TX SOUT and RX SIN lines)")
            po.setdefault("synchronous", False)
            po.setdefault("wire_names_serial", ["SIN (Serial In)", "SOUT (Serial Out)"])
            po.setdefault("wire_names_modem_handshake", ["CTS", "RTS", "DSR", "DTR", "DCD", "RI"])
            po.setdefault("host_interface_bus_width_bits", 8)
            po.setdefault("fifo_depth_bytes", 16)
            po.setdefault("data_character_widths_bits", [5, 6, 7, 8])
            po.setdefault("stop_bits_options", ["1", "1.5 (for 5-bit characters)", "2"])
            po.setdefault("parity_options", ["None", "Odd", "Even", "Stick parity (Mark or Space)"])
        fr = [
            {"id": "FR-FRAME-01",  "text": "Each character is framed by 1 start bit (LOW), 5-8 data bits LSB-first, optional parity bit, and 1, 1.5, or 2 stop bits (HIGH)."},
            {"id": "FR-BAUD-02",   "text": "Baud rate generator divides input clock (XIN/XOUT or external) by a 16-bit divisor (DLM:DLL) to produce the BAUDOUT 16× sampling clock."},
            {"id": "FR-OVER-03",   "text": "Receiver samples each bit at the 8th clock of a 16× clock (mid-bit sampling); transmitter shifts at the rising edge of the 16× clock divided by 16."},
            {"id": "FR-FIFO-04",   "text": "FIFO mode (FCR0=1): RX FIFO 16 bytes + 3 error bits per byte; TX FIFO 16 bytes. Character mode (FCR0=0 or after reset): one holding + one shift register on each side."},
            {"id": "FR-TRIG-05",   "text": "RX FIFO trigger levels: 1, 4, 8, or 14 bytes (selected by FCR bits 6-7)."},
            {"id": "FR-INT-06",    "text": "Interrupts (OR'd into INTR pin): Receiver Line Status, Received Data Available, Character Timeout (FIFO mode only), Transmitter Holding Register Empty, MODEM Status; priorities and IDs in IIR."},
            {"id": "FR-MODEM-07",  "text": "Outputs RTS, DTR, OUT1, OUT2 driven from MCR bits; inputs CTS, DSR, DCD, RI sampled and reported in MSR with delta-flag bits."},
            {"id": "FR-LOOP-08",   "text": "Loopback diagnostic (MCR bit 4 = 1): SOUT→SIN internally; CTS/DSR/DCD/RI driven by MCR bits 0-3; allows fault isolation."},
            {"id": "FR-BREAK-09",  "text": "Line break generation: setting LCR bit 6 forces SOUT continuously LOW; break detection: receiver flags BI when SIN is LOW for longer than a complete character."},
            {"id": "FR-ERROR-10",  "text": "Error detection: parity (PE), framing (FE), overrun (OE), break interrupt (BI); reported in LSR bits 1-4."},
            {"id": "FR-RESET-11",  "text": "Master Reset (MR pin HIGH) clears all registers except RBR, THR, and Divisor Latches; sets outputs to inactive state per Table I."},
            {"id": "FR-DLAB-12",   "text": "Divisor Latch Access Bit (LCR bit 7 = 1) re-maps register addresses A0=0 → DLL, A0=1 → DLM, enabling baud-rate programming."},
            {"id": "FR-RXRDY-13",  "text": "RXRDY pin signals RX FIFO has data (or character mode RBR has data); Mode 0 = single-character indication; Mode 1 = FIFO-level indication."},
            {"id": "FR-TXRDY-14",  "text": "TXRDY pin signals TX FIFO can accept data (or character mode THR empty); Mode 0 = THR empty; Mode 1 = FIFO empty."},
            {"id": "FR-DMA-15",    "text": "DDIS output goes LOW when CPU is reading from UART; can disable / direction-control an external bus transceiver."},
        ]
        if _empty(d.get("functional_requirements")):
            d["functional_requirements"] = fr
        d.setdefault("error_response_conditions", [
            "Parity Error (PE, LSR bit 2): received parity does not match LCR-configured parity.",
            "Framing Error (FE, LSR bit 3): stop bit not detected at expected position.",
            "Overrun Error (OE, LSR bit 1): new character received before previous character read from RBR (character mode) or FIFO full (FIFO mode).",
            "Break Interrupt (BI, LSR bit 4): SIN held LOW for longer than start + data + parity + stop bit time.",
            "FIFO data error (LSR bit 7, FIFO mode only): at least one PE/FE/BI in the FIFO.",
        ])
        d.setdefault("external_serial_wire_count",
            "2 (SIN, SOUT); + 6 modem control (CTS/RTS/DSR/DTR/DCD/RI); + 1-2 status output (TXRDY/RXRDY) + 1 INTR; + CPU bus 8 + addr 3 + ctrl 3-5")
        if _empty(d.get("compliance_requirements")):
            d["compliance_requirements"] = [
                "Baud rate generator divisor 1 ≤ divisor ≤ 2^16 - 1 = 65535.",
                "Character format must be programmed (LCR) before transmission begins; both ends must agree on bits/parity/stop.",
                "Master Reset must be asserted for at least 1 µs after power-up.",
                "External clock XIN frequency must be ≤ 24.0 MHz.",
            ]
        _write(p, d)

    # L3
    p = gd / "L3_CMD_PROTOCOL.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("protocol_type", "Register-mapped UART chip on a parallel host bus (CPU side); async serial framing on the wire side. No opcode/command set.")
        d.setdefault("host_bus_interface", {
            "data_bus_width_bits": 8,
            "address_pins": ["A0", "A1", "A2"],
            "chip_select_pins": ["CS0 (active high)", "CS1 (active high)", "CS2 (active low)"],
            "control_strobes": ["RD / RD (read; either active edge works)", "WR / WR (write; either active edge works)"],
            "address_strobe": "ADS (latches A0-A2 + CS0-CS2 on positive edge if used; tie LOW if not needed)",
            "buffer_disable_output": "DDIS (LOW during CPU reads from UART)",
            "interrupt_output": "INTR (active HIGH)",
        })
        d.setdefault("register_addressing", {
            "header": ["DLAB", "A2", "A1", "A0", "Register (R/W)"],
            "rows": [
                ["0", "0", "0", "0", "RBR (R) / THR (W) — Receiver Buffer / Transmitter Holding"],
                ["0", "0", "0", "1", "IER — Interrupt Enable Register"],
                ["X", "0", "1", "0", "IIR (R) / FCR (W) — Interrupt Identification / FIFO Control"],
                ["X", "0", "1", "1", "LCR — Line Control Register"],
                ["X", "1", "0", "0", "MCR — MODEM Control Register"],
                ["X", "1", "0", "1", "LSR — Line Status Register"],
                ["X", "1", "1", "0", "MSR — MODEM Status Register"],
                ["X", "1", "1", "1", "SCR — Scratchpad Register"],
                ["1", "0", "0", "0", "DLL — Divisor Latch (least significant byte)"],
                ["1", "0", "0", "1", "DLM — Divisor Latch (most significant byte)"],
            ],
        })
        d.setdefault("channels_serial_side", [
            {"name": "SIN",  "direction": "input",  "description": "Serial data input from peripheral/modem. Idle HIGH."},
            {"name": "SOUT", "direction": "output", "description": "Serial data output to peripheral/modem. Idle HIGH."},
            {"name": "CTS",  "direction": "input",  "description": "Clear to Send (active LOW); modem status only — does not gate transmitter."},
            {"name": "RTS",  "direction": "output", "description": "Request to Send (active LOW); MCR bit 1."},
            {"name": "DSR",  "direction": "input",  "description": "Data Set Ready (active LOW); modem status."},
            {"name": "DTR",  "direction": "output", "description": "Data Terminal Ready (active LOW); MCR bit 0."},
            {"name": "DCD",  "direction": "input",  "description": "Data Carrier Detect (active LOW); modem status."},
            {"name": "RI",   "direction": "input",  "description": "Ring Indicator (active LOW); modem status."},
            {"name": "OUT1", "direction": "output", "description": "User-designated output (active LOW); MCR bit 2."},
            {"name": "OUT2", "direction": "output", "description": "User-designated output (active LOW); MCR bit 3."},
        ])
        d.setdefault("valid_ready_handshake_rules", [
            "There is no per-byte ACK or VALID/READY handshake on the serial wire — UART is asynchronous with frame-level start/stop framing.",
            "Host-bus side uses RD/WR strobes with stable A0-A2 + CS0-CS2.",
            "Hardware flow control (when used): RTS asserted = UART ready to receive; CTS asserted = modem ready to receive. CTS does NOT gate transmitter directly — software interprets MSR.CTS.",
        ])
        d.setdefault("burst_based", False)
        d.setdefault("byte_oriented", True)
        d.setdefault("frame_format", {
            "start_bit":      "1 bit, always LOW (mark→space transition).",
            "data_bits":      "5, 6, 7, or 8 bits, LSB first.",
            "parity_bit":     "Optional; even / odd / stick (mark or space).",
            "stop_bits":      "1, 1.5 (5-bit char only), or 2 bits, always HIGH.",
            "idle_state":     "HIGH (mark).",
        })
        _write(p, d)

    # L4 registers
    p = gd / "L4_REGMAP.json"
    if p.is_file():
        d = _read(p)
        d["register_map_present"] = True
        d.setdefault("base_address",
            "Defined at SoC level; PC16550D occupies 8 contiguous addresses (A0..A2 = 0..7) relative to its CS0/CS1/CS2 chip-select region.")
        d.setdefault("register_count", 12)
        regs = [
            {"name": "RBR", "long_name": "Receiver Buffer Register", "offset": "A2:A1:A0 = 000", "dlab": "0", "width_bits": 8, "access": "Read",
             "description": "Holds the most recently received character (or in FIFO mode, the next character at the head of the RX FIFO). Reading clears RDR / advances the FIFO."},
            {"name": "THR", "long_name": "Transmitter Holding Register", "offset": "A2:A1:A0 = 000", "dlab": "0", "width_bits": 8, "access": "Write",
             "description": "Holds the next character to transmit (or pushes into the TX FIFO in FIFO mode). Writing clears THRE."},
            {"name": "IER", "long_name": "Interrupt Enable Register", "offset": "A2:A1:A0 = 001", "dlab": "0", "width_bits": 8, "access": "Read / Write", "reset_value": "0x00",
             "fields": [
                {"bit": 0, "name": "ERBI",  "description": "Enable Received Data Available Interrupt."},
                {"bit": 1, "name": "ETBEI", "description": "Enable Transmitter Holding Register Empty Interrupt."},
                {"bit": 2, "name": "ELSI",  "description": "Enable Receiver Line Status Interrupt."},
                {"bit": 3, "name": "EDSSI", "description": "Enable MODEM Status Interrupt."},
                {"bits": "7:4", "name": "Reserved", "description": "Always 0."}]},
            {"name": "IIR", "long_name": "Interrupt Identification Register", "offset": "A2:A1:A0 = 010", "width_bits": 8, "access": "Read", "reset_value": "0x01",
             "fields": [
                {"bit": 0, "name": "INT_PENDING", "description": "0 = interrupt pending; 1 = no interrupt."},
                {"bits": "3:1", "name": "INT_ID", "description": "Encodes the highest-priority pending interrupt."},
                {"bits": "5:4", "name": "Reserved", "description": "Always 0."},
                {"bits": "7:6", "name": "FIFO_EN", "description": "00 = char mode; 11 = FIFO mode."}]},
            {"name": "FCR", "long_name": "FIFO Control Register", "offset": "A2:A1:A0 = 010", "width_bits": 8, "access": "Write", "reset_value": "0x00",
             "fields": [
                {"bit": 0, "name": "FIFO_EN",  "description": "1 = enable FIFOs; 0 = char mode."},
                {"bit": 1, "name": "RX_FIFO_RESET", "description": "Write 1 to clear RX FIFO; self-clears."},
                {"bit": 2, "name": "TX_FIFO_RESET", "description": "Write 1 to clear TX FIFO; self-clears."},
                {"bit": 3, "name": "DMA_MODE_SELECT", "description": "0 = Mode 0; 1 = Mode 1 for TXRDY/RXRDY signalling."},
                {"bits": "5:4", "name": "Reserved", "description": "Always 0."},
                {"bits": "7:6", "name": "RX_TRIGGER", "description": "RX FIFO interrupt trigger level: 00=1, 01=4, 10=8, 11=14 bytes."}]},
            {"name": "LCR", "long_name": "Line Control Register", "offset": "A2:A1:A0 = 011", "width_bits": 8, "access": "Read / Write", "reset_value": "0x00",
             "fields": [
                {"bits": "1:0", "name": "WLS", "description": "Word Length Select: 00=5, 01=6, 10=7, 11=8 data bits."},
                {"bit": 2, "name": "STB",  "description": "Stop Bits: 0 = 1 stop bit; 1 = 1.5 (5-bit char) or 2 stop bits."},
                {"bit": 3, "name": "PEN",  "description": "Parity Enable."},
                {"bit": 4, "name": "EPS",  "description": "Even Parity Select (when PEN=1)."},
                {"bit": 5, "name": "STICK","description": "Stick Parity (when PEN=1): force parity bit to mark or space."},
                {"bit": 6, "name": "BREAK","description": "Set Break: forces SOUT LOW continuously."},
                {"bit": 7, "name": "DLAB", "description": "Divisor Latch Access Bit: 1 = remap A0=0/1 to DLL/DLM."}]},
            {"name": "MCR", "long_name": "MODEM Control Register", "offset": "A2:A1:A0 = 100", "width_bits": 8, "access": "Read / Write", "reset_value": "0x00",
             "fields": [
                {"bit": 0, "name": "DTR",  "description": "Sets DTR pin LOW when 1."},
                {"bit": 1, "name": "RTS",  "description": "Sets RTS pin LOW when 1."},
                {"bit": 2, "name": "OUT1", "description": "Sets OUT1 pin LOW when 1."},
                {"bit": 3, "name": "OUT2", "description": "Sets OUT2 pin LOW when 1."},
                {"bit": 4, "name": "LOOP", "description": "Loopback Diagnostic enable."},
                {"bits": "7:5", "name": "Reserved", "description": "Always 0."}]},
            {"name": "LSR", "long_name": "Line Status Register", "offset": "A2:A1:A0 = 101", "width_bits": 8, "access": "Read", "reset_value": "0x60",
             "fields": [
                {"bit": 0, "name": "DR",   "description": "Data Ready: 1 = character available in RBR / RX FIFO."},
                {"bit": 1, "name": "OE",   "description": "Overrun Error."},
                {"bit": 2, "name": "PE",   "description": "Parity Error."},
                {"bit": 3, "name": "FE",   "description": "Framing Error."},
                {"bit": 4, "name": "BI",   "description": "Break Interrupt."},
                {"bit": 5, "name": "THRE", "description": "Transmitter Holding Register Empty."},
                {"bit": 6, "name": "TEMT", "description": "Transmitter Empty (THR + shift register both empty)."},
                {"bit": 7, "name": "RFE",  "description": "FIFO Data Error (FIFO mode only)."}]},
            {"name": "MSR", "long_name": "MODEM Status Register", "offset": "A2:A1:A0 = 110", "width_bits": 8, "access": "Read",
             "fields": [
                {"bit": 0, "name": "DCTS", "description": "Delta CTS since last read."},
                {"bit": 1, "name": "DDSR", "description": "Delta DSR since last read."},
                {"bit": 2, "name": "TERI", "description": "Trailing Edge of RI since last read."},
                {"bit": 3, "name": "DDCD", "description": "Delta DCD since last read."},
                {"bit": 4, "name": "CTS",  "description": "Complement of CTS pin."},
                {"bit": 5, "name": "DSR",  "description": "Complement of DSR pin."},
                {"bit": 6, "name": "RI",   "description": "Complement of RI pin."},
                {"bit": 7, "name": "DCD",  "description": "Complement of DCD pin."}]},
            {"name": "SCR", "long_name": "Scratchpad Register", "offset": "A2:A1:A0 = 111", "width_bits": 8, "access": "Read / Write",
             "description": "Has no internal function; the CPU may use it as a scratch holding register."},
            {"name": "DLL", "long_name": "Divisor Latch (Least Significant Byte)", "offset": "A2:A1:A0 = 000 with DLAB=1", "width_bits": 8, "access": "Read / Write",
             "description": "Lower 8 bits of 16-bit baud rate divisor."},
            {"name": "DLM", "long_name": "Divisor Latch (Most Significant Byte)", "offset": "A2:A1:A0 = 001 with DLAB=1", "width_bits": 8, "access": "Read / Write",
             "description": "Upper 8 bits of 16-bit baud rate divisor."},
        ]
        if _empty(d.get("registers")):
            d["registers"] = regs
        d["notes"] = "Eight CPU-visible register addresses; DLAB bit in LCR remaps the first two to access DLL / DLM. After Master Reset all registers (except RBR, THR, DLL, DLM) are cleared per Table I."
        _write(p, d)

    # L5 — overwrite with UART-specific
    p = gd / "L5_ADI_SPEC.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("analog_digital_interface_present", False)
        d["signaling_summary"] = (
            "Digital TTL-compatible signaling on all pins. Power supply VDD = +5 V ± 10 %. "
            "Input thresholds VIL ≤ 0.8 V, VIH ≥ 2.0 V; output VOL ≤ 0.4 V at 1.6 mA sink, "
            "VOH ≥ 2.4 V at 1.0 mA source. Master Reset pin (MR) has a Schmitt trigger with "
            "0.5 V typical hysteresis. TRI-STATE TTL drive on D7-D0 data bus.")
        _write(p, d)

    # L6 control logic
    p = gd / "L6_CONTROL_LOGIC.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("fsm_states_transmitter", [
            {"name": "TX_IDLE",       "description": "SOUT HIGH; THR + TX FIFO empty; THRE=1, TEMT=1."},
            {"name": "TX_START_BIT",  "description": "Drive SOUT LOW for 1 bit-time (start bit)."},
            {"name": "TX_DATA_BITS",  "description": "Shift out 5-8 data bits LSB-first on SOUT, one bit per BAUDOUT/16 cycle."},
            {"name": "TX_PARITY_BIT", "description": "Drive parity bit (even / odd / mark / space) if PEN=1."},
            {"name": "TX_STOP_BITS",  "description": "Drive SOUT HIGH for 1, 1.5, or 2 stop bit-times."},
            {"name": "TX_BREAK",      "description": "While LCR.BREAK=1: hold SOUT LOW continuously."},
        ])
        d.setdefault("fsm_states_receiver", [
            {"name": "RX_IDLE",       "description": "Wait for SIN HIGH→LOW (start-bit edge)."},
            {"name": "RX_START_BIT",  "description": "Re-sample SIN mid-bit (8 clocks into the bit cell) to confirm valid start; false start-bit detection."},
            {"name": "RX_DATA_BITS",  "description": "Sample SIN mid-bit (every 16th BAUDOUT) and shift into receive shift register LSB-first."},
            {"name": "RX_PARITY_BIT", "description": "Sample parity bit (if PEN=1) and compare to expected parity."},
            {"name": "RX_STOP_BITS",  "description": "Sample stop bit(s); if 0 then FE=1."},
            {"name": "RX_TRANSFER",   "description": "Move received character + error bits into RBR (char mode) or RX FIFO (FIFO mode); set DR=1."},
            {"name": "RX_BREAK_DET",  "description": "SIN held LOW for ≥ entire character time → BI=1."},
        ])
        d.setdefault("fsm_hints", {
            "tx_trigger":      "CPU write to THR (char mode) or push into TX FIFO (FIFO mode) starts a transfer cycle.",
            "rx_trigger":      "SIN HIGH→LOW transition starts a receive cycle.",
            "oversampling":    "Receiver samples each bit at the 8th of 16 BAUDOUT clocks; mid-bit sampling for noise immunity.",
            "abort_conditions":"Master Reset (MR HIGH); a configuration change to LCR/MCR/baud divisor while a frame is in progress will corrupt the frame.",
        })
        d.setdefault("anti_deadlock_rule",
            "TX SOUT and RX SIN are independent serial wires; full-duplex operation has no cross-coupling. The chip-select bus interface uses simple RD/WR strobes.")
        d.setdefault("exit_from_reset",
            "After Master Reset (MR=1 for ≥ 1 µs): all registers (except RBR/THR/DLL/DLM) cleared; SOUT, INTR, OUT1, OUT2, RTS, DTR set per Table I. Software must program DLL/DLM (baud) and LCR (framing) before transmission begins.")
        d.setdefault("default_ready_state_recommendation", {
            "SOUT_idle": "HIGH (mark).",
            "SIN_idle":  "HIGH (mark).",
            "Modem_outputs_idle": "All HIGH (inactive) after MR; software writes MCR to assert.",
        })
        d.setdefault("loopback_diagnostic_mode", {
            "trigger": "MCR bit 4 (LOOP) = 1.",
            "behavior": [
                "Transmitter SOUT is set to HIGH-Z and internally connected to receiver SIN.",
                "Modem inputs CTS, DSR, DCD, RI are disconnected from pins; driven instead by MCR bits 0-3 (DTR→DSR, RTS→CTS, OUT1→RI, OUT2→DCD).",
                "Allows software self-test without external loopback.",
            ],
        })
        d.setdefault("false_start_bit_detection",
            "On SIN HIGH→LOW edge, receiver waits 8 BAUDOUT clocks (half a bit time) and re-samples; if SIN is still LOW, accept as start bit. Otherwise discard as noise.")
        d.setdefault("interrupt_priority_order", [
            "1 (highest): Receiver Line Status — OE/PE/FE/BI",
            "2: Received Data Available (or FIFO trigger level reached)",
            "3: Character Timeout (FIFO mode only)",
            "4: Transmitter Holding Register Empty",
            "5 (lowest): MODEM Status — CTS/DSR/RI/DCD change",
        ])
        _write(p, d)

    # L7
    p = gd / "L7_TEST_DEBUG.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("test_debug_architecture_present", True)
        d.setdefault("test_debug_features", [
            "Internal loopback (MCR.LOOP=1) for fault isolation; SOUT internally drives SIN; modem outputs drive modem inputs.",
            "Break, parity, overrun, framing error simulation through loopback + register manipulation.",
            "FIFO reset bits (FCR.RX_FIFO_RESET, FCR.TX_FIFO_RESET) for in-chip BIST equivalent.",
            "Complete LSR status reporting allows software self-test of all framing / error paths.",
            "Master Reset (MR pin) sets a known reset state per Table I.",
        ])
        d.setdefault("spec_provided_observability", [
            {"name": "LSR.DR",   "purpose": "Data Ready — character available in RBR / RX FIFO."},
            {"name": "LSR.OE",   "purpose": "Overrun Error indicator."},
            {"name": "LSR.PE",   "purpose": "Parity Error indicator."},
            {"name": "LSR.FE",   "purpose": "Framing Error indicator."},
            {"name": "LSR.BI",   "purpose": "Break Interrupt indicator."},
            {"name": "LSR.THRE", "purpose": "TX Holding Register Empty."},
            {"name": "LSR.TEMT", "purpose": "TX shift register also empty."},
            {"name": "LSR.RFE",  "purpose": "RX FIFO contains at least one error (FIFO mode)."},
            {"name": "IIR",      "purpose": "Identifies highest-priority pending interrupt + FIFO-enabled status."},
            {"name": "MSR delta bits", "purpose": "DCTS / DDSR / TERI / DDCD record modem-input transitions since last read."},
        ])
        d.setdefault("interrupt_sources", [
            {"flag": "ERBI",   "register": "IER bit 0", "trigger": "RX data available or FIFO trigger level reached."},
            {"flag": "ETBEI",  "register": "IER bit 1", "trigger": "Transmitter Holding Register empty."},
            {"flag": "ELSI",   "register": "IER bit 2", "trigger": "Receiver line status — OE/PE/FE/BI."},
            {"flag": "EDSSI",  "register": "IER bit 3", "trigger": "MODEM Status change — CTS/DSR/RI/DCD."},
            {"flag": "FIFO_TO","register": "FIFO mode auto", "trigger": "Character timeout — RX FIFO non-empty + no new char within 4 character times."},
        ])
        d.setdefault("interrupt_request",
            "INTR pin (active HIGH) is the OR of all enabled interrupt sources; IIR identifies the highest-priority pending source.")
        d.setdefault("notes",
            "The 16450/16550 family was the de-facto standard PC serial-port UART; the loopback diagnostic + status registers make it self-testable through software alone — historically important for BIOS power-on self-test (POST).")
        _write(p, d)

    # L8 RTL constants
    p = gd / "L8_RTL_CONSTANTS.json"
    if p.is_file():
        d = _read(p)
        wp = d.setdefault("width_parameters", {})
        if isinstance(wp, dict):
            for k, v in {
                "DATA_BUS_WIDTH_bits": 8, "ADDRESS_BUS_WIDTH_bits": 3,
                "CHIP_SELECT_PINS": 3, "REGISTER_COUNT_VISIBLE": 8,
                "REGISTER_COUNT_TOTAL_WITH_DLAB": 10,
                "BAUD_DIVISOR_WIDTH_bits": 16,
                "FIFO_DEPTH_BYTES_RX": 16, "FIFO_DEPTH_BYTES_TX": 16,
                "RX_FIFO_ERROR_BITS_PER_BYTE": 3,
                "CHARACTER_WIDTH_RANGE_bits": [5, 6, 7, 8],
                "OVERSAMPLING_RATIO": 16,
            }.items():
                wp.setdefault(k, v)
        d.setdefault("voltage_levels", {
            "VDD_nominal": "+5 V ± 10 %",
            "VIL_max": "0.8 V", "VIH_min": "2.0 V",
            "VOL_max": "0.4 V at 1.6 mA sink",
            "VOH_min": "2.4 V at 1.0 mA source",
            "MR_Schmitt_hysteresis_typ": "0.5 V",
        })
        d.setdefault("clock_constants", {
            "XIN_max_frequency_MHz": 24.0,
            "BAUDOUT_relation": "BAUDOUT = XIN / divisor where divisor = (DLM << 8) | DLL; 1 ≤ divisor ≤ 65535",
            "Baud_rate_relation": "Baud rate = BAUDOUT / 16 = XIN / (16 × divisor)",
            "Max_baud_rate": "1.5 Mbaud (typical) at high XIN; DC at high divisor",
            "Min_baud_rate": "Determined by max divisor = 65535",
        })
        d.setdefault("key_constants_for_RTL_authoring", {
            "oversampling_x": 16, "rx_mid_bit_sample_clock": 8,
            "frame_minimum_bits": 7, "frame_maximum_bits": 12,
            "start_bit_value": 0, "stop_bit_value": 1, "idle_line_value": 1,
            "lsb_first_data_order": True,
            "fifo_trigger_levels_bytes": [1, 4, 8, 14],
            "interrupt_priority_count": 5,
            "modem_outputs": ["DTR", "RTS", "OUT1", "OUT2"],
            "modem_inputs": ["CTS", "DSR", "DCD", "RI"],
        })
        d.setdefault("register_address_map", {
            "RBR_THR_offset": 0, "IER_offset": 1, "IIR_FCR_offset": 2,
            "LCR_offset": 3, "MCR_offset": 4, "LSR_offset": 5,
            "MSR_offset": 6, "SCR_offset": 7,
            "DLL_offset_with_DLAB": 0, "DLM_offset_with_DLAB": 1,
        })
        d.setdefault("default_signal_values_after_reset", {
            "SOUT": "HIGH (mark / idle)",
            "INTR": "LOW",
            "OUT1": "HIGH (inactive)",
            "OUT2": "HIGH (inactive)",
            "RTS":  "HIGH (inactive)",
            "DTR":  "HIGH (inactive)",
            "TXRDY":"HIGH (inactive — no XMIT data)",
            "RXRDY":"HIGH (inactive — no RCVR data)",
        })
        _write(p, d)

    # L8_TIMING
    p = gd / "L8_TIMING_WAVEFORM.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("clock_and_reset_waveform", {
            "XIN":         "External clock input; ≤ 24.0 MHz; drives baud rate generator.",
            "XOUT":        "Output of internal feedback inverter for crystal oscillator; unused when external clock is applied.",
            "BAUDOUT":     "16× baud-rate clock generated by the baud rate generator.",
            "RCLK":        "Receiver clock input; typically tied to BAUDOUT.",
            "MR_reset":    "Master Reset (active HIGH); ≥ 1 µs pulse width. Schmitt input with 0.5 V hysteresis.",
        })
        d.setdefault("serial_frame_waveform", {
            "idle":         "SIN/SOUT remain HIGH (mark).",
            "start_bit":    "1 bit-time LOW (drives mark→space transition); detected on SIN HIGH→LOW edge.",
            "data_bits":    "5-8 bits, transmitted LSB first; each bit lasts 1 bit-time (16 BAUDOUT clocks).",
            "parity_bit":   "Optional 1 bit; even, odd, mark, or space per LCR.EPS/STICK.",
            "stop_bits":    "1, 1.5, or 2 bit-times HIGH (mark) per LCR.STB.",
            "false_start_rejection": "Receiver re-samples SIN 8 BAUDOUT clocks after the start-bit edge; if still LOW, accepts start bit; otherwise rejects.",
        })
        d.setdefault("receiver_mid_bit_sampling", {
            "rule": "Receiver samples each bit at the 8th of 16 BAUDOUT clocks (mid-bit), maximizing noise immunity.",
            "figure": "Receiver Timing waveform (Section 4.0)",
        })
        d.setdefault("write_cycle_timing", {
            "control_strobes": "WR / WR with chip selected (CS0 + CS1 HIGH, CS2 LOW) and Register Select (A0-A2) stable.",
            "tADS_setup": "Register-Select setup before WR rising edge.",
            "tADH_hold":  "Register-Select hold after WR rising edge.",
            "figure": "Write Cycle waveform (Section 4.0)",
        })
        d.setdefault("read_cycle_timing", {
            "control_strobes": "RD / RD with chip selected and Register Select stable.",
            "DDIS_low_during_read": "DDIS goes LOW while CPU is reading from UART; can disable / direct an external bus transceiver.",
            "figure": "Read Cycle waveform (Section 4.0)",
        })
        d.setdefault("interrupt_timing", {
            "tSI_initial":  "Delay from initial CPU write to first interrupt.",
            "tSTI_stop":    "Delay from stop-bit edge to THRE interrupt.",
            "tIR_reset":    "Delay from RD (IIR) to INTR reset.",
            "tHR_reset":    "Delay from WR (THR) to interrupt reset.",
        })
        d.setdefault("modem_control_timing", {
            "tMDO": "Delay from WR (MCR) to modem output change.",
            "tRIM": "Delay from RD (MSR) to interrupt reset.",
            "tSIM": "Delay from MODEM input change to interrupt set.",
        })
        d.setdefault("fifo_mode_timing_notes", [
            "Trigger-level interrupts and DR indication are delayed 3 RCLKs in FIFO mode.",
            "Status indicators (PE/FE/BI) delayed 3 RCLKs after the first byte; immediate for subsequent bytes once RDR goes inactive.",
            "Character timeout interrupt is delayed 8 RCLKs after the last RX char.",
        ])
        d.setdefault("absolute_max_ratings", {
            "VDD_max": "+7.0 V (with respect to VSS)",
            "Storage_temperature": "-65 °C to +150 °C",
            "Operating_temperature": "0 °C to +70 °C",
            "Power_dissipation_max": "1 W",
            "Average_ICC_max": "15 mA",
        })
        _write(p, d)

    # L9
    p = gd / "L9_INTEGRATION_SPEC.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("module_role",
            "Stand-alone 40-pin UART peripheral connecting an 8-bit CPU bus (D7-D0 + A0-A2 + CS0-CS2 + RD/WR + INTR) to a serial async + modem-control interface (SIN/SOUT + CTS/RTS/DSR/DTR/DCD/RI).")
        _ptm.apply(d, "PC16550D")
        d.setdefault("integration_overview", {
            "host_bus_side": "8-bit data bus + 3 address pins + 3 chip-select pins + RD/WR strobes + optional ADS latch + INTR + DDIS bus-direction signal.",
            "serial_side":   "SIN + SOUT for data; CTS/RTS/DSR/DTR/DCD/RI for modem handshaking; OUT1/OUT2 as user GPOs; TXRDY/RXRDY for DMA handshake.",
            "clock_source":  "External crystal between XIN and XOUT, or external clock on XIN (≤ 24.0 MHz). Independent RCLK input for the receiver section if desired.",
            "reset_source":  "Master Reset MR pin (active HIGH, Schmitt input, ≥ 1 µs).",
            "interrupt_routing": "Single INTR output (active HIGH) ORs all enabled sources.",
        })
        d.setdefault("interface_categories", [
            "8-bit parallel CPU bus (RBR/THR + status + control registers)",
            "Serial async TX/RX (SIN/SOUT)",
            "Modem control (CTS/RTS/DSR/DTR/DCD/RI)",
            "DMA handshake (TXRDY/RXRDY in Mode 0 / Mode 1)",
            "User-defined GPO (OUT1/OUT2)",
            "Loopback diagnostic",
        ])
        d.setdefault("interconnect_topologies_supported", [
            "Point-to-point UART (SIN/SOUT to a peer UART or modem)",
            "Modem connection (RS-232 line driver + modem on CTS/RTS/DSR/DTR/DCD/RI)",
            "RS-485 multi-drop via external transceiver + RTS-controlled enable",
        ])
        d.setdefault("default_signal_values_when_omitted",
            "See L4 register reset values + Table I. After Master Reset all outputs are at inactive state.")
        d.setdefault("soc_dependent_items", [
            "Crystal selection (oscillator capacitor sizing) or external clock source",
            "Choice of XIN frequency (drives max baud rate)",
            "Chip-select decoding (CS0/CS1/CS2 polarity)",
            "Optional ADS use for non-stable A/CS during R/W",
            "External level translator for RS-232 / RS-485 / TTL drive",
            "Interrupt controller wiring",
            "DMA-controller wiring (TXRDY / RXRDY)",
            "GPO routing (OUT1, OUT2)",
        ])
        d.setdefault("low_power_modes", {
            "Standby": "Not formally defined; ICC max 15 mA at 5.5 V; reducing XIN frequency reduces dynamic current.",
        })
        d.setdefault("compatibility_notes", [
            "Pin-for-pin compatible with 16450 except pins 24 (TXRDY) and 29 (RXRDY) which replace 16450's CSOUT and NC.",
            "Software-compatible with 16450 after reset (FCR0=0 forces 16450 mode).",
            "Setting FCR0=1 enters FIFO mode (16-byte RX/TX FIFOs).",
        ])
        _write(p, d)

    # L11 OTP
    p = gd / "L11_OTP_CONTENT.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("otp_present", False)
        d["notes"] = (
            "PC16550D has no on-chip OTP / fuse / configuration ROM. All "
            "configuration is via the run-time register file (LCR, MCR, "
            "FCR, IER, DLL, DLM). The Scratchpad register (SCR) is volatile "
            "RAM and not OTP.")
        _write(p, d)

    # L12 behavioral sequences
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("initialization_sequence", [
            "1. Pulse MR HIGH for ≥ 1 µs to reset the chip.",
            "2. Write LCR with DLAB=1 + desired word length / parity / stop bits.",
            "3. Write DLL and DLM with the 16-bit divisor (BAUDOUT = XIN / divisor; baud rate = BAUDOUT / 16).",
            "4. Clear DLAB by writing LCR with the same framing bits and DLAB=0.",
            "5. Write FCR to enable / clear FIFOs and set trigger level (FCR0=1, RX trigger 00/01/10/11 = 1/4/8/14 bytes).",
            "6. Write MCR for modem outputs (DTR / RTS / OUT1 / OUT2) and LOOP mode if needed.",
            "7. Write IER to enable the desired interrupts (ERBI, ETBEI, ELSI, EDSSI).",
        ])
        d.setdefault("typical_transmit_sequence", [
            "1. Software polls LSR.THRE (or waits for THRE interrupt with IER.ETBEI=1).",
            "2. Software writes character to THR (or up to 16 characters into TX FIFO).",
            "3. UART loads character from THR / FIFO head into TX shift register; THRE asserts when slot is free.",
            "4. Start bit (LOW) is transmitted on SOUT; followed by data bits LSB-first, optional parity, then stop bit(s) HIGH.",
            "5. TEMT asserts when shift register is also empty.",
        ])
        d.setdefault("typical_receive_sequence", [
            "1. Receiver detects SIN HIGH→LOW edge → start of frame.",
            "2. Re-sample SIN 8 BAUDOUT clocks later; if still LOW, confirm start bit (false start rejected otherwise).",
            "3. Sample each data bit mid-bit (every 16 BAUDOUT clocks); shift into receive shift register LSB-first.",
            "4. Sample parity bit (if PEN=1); compare with expected parity → PE=1 on mismatch.",
            "5. Sample stop bit; if LOW → FE=1.",
            "6. Transfer character + PE/FE/BI bits into RBR (char mode) or RX FIFO (FIFO mode); set LSR.DR=1.",
            "7. Generate RX interrupt (or set RXRDY pin) based on FCR / IER configuration.",
            "8. CPU reads RBR (or top of FIFO) to consume character; DR clears.",
        ])
        d.setdefault("loopback_diagnostic_sequence", [
            "1. Set MCR.LOOP=1.",
            "2. Set MCR.DTR, RTS, OUT1, OUT2 to desired test values (these drive MSR.DSR, CTS, RI, DCD in loop mode).",
            "3. Write character to THR.",
            "4. Wait for LSR.DR=1, read RBR; compare to written character.",
            "5. Read MSR; verify CTS/DSR/RI/DCD match MCR drive.",
            "6. Optional: set LCR.BREAK=1 then 0; verify LSR.BI gets set on RX side.",
        ])
        d.setdefault("fifo_mode_transmit_sequence", [
            "1. Set FCR0=1 to enable FIFO; set RX trigger level.",
            "2. Push up to 16 characters into TX FIFO via consecutive writes to THR.",
            "3. UART transmits each character with the configured framing; THRE asserts when FIFO has room.",
            "4. THRE interrupt fires when FIFO is empty (transmit complete).",
        ])
        d.setdefault("fifo_mode_receive_sequence", [
            "1. Set FCR0=1 + RX trigger level (1/4/8/14 bytes).",
            "2. Characters accumulate in RX FIFO.",
            "3. Interrupt fires when FIFO level ≥ trigger level OR after 4-character-time of silence with FIFO non-empty (character timeout).",
            "4. CPU reads RBR repeatedly until LSR.DR clears or FIFO empty.",
        ])
        d.setdefault("modem_status_change_sequence", [
            "1. CTS/DSR/DCD/RI input transitions trigger MSR delta bits (DCTS, DDSR, DDCD, TERI).",
            "2. If IER.EDSSI=1, INTR is asserted.",
            "3. Software reads MSR to clear delta bits and INTR for this source.",
        ])
        _write(p, d)

    # L13
    p = gd / "L13_LAB_CALIBRATION.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("lab_calibration_present", False)
        d["notes"] = (
            "PC16550D has no analog reference / trim / calibration loop. "
            "Baud-rate accuracy depends on the external XIN clock or "
            "crystal; no on-chip trim. The receiver uses 16× oversampling "
            "for noise immunity, eliminating any need for chip-side "
            "calibration.")
        _write(p, d)

    # L14 versioning
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("spec_version", "PC16550D")
        if _empty(f.get("lineage")):
            f["lineage"] = [
                {"version": "INS8250",  "year": "1977", "summary": "Original IBM PC serial-port UART; no FIFOs."},
                {"version": "16450",    "year": "1980s","summary": "Faster INS8250; no FIFOs; widely used in IBM PC/AT."},
                {"version": "PC16550",  "year": "1987", "summary": "First version with 16-byte FIFOs; had RX FIFO bug."},
                {"version": "PC16550A", "year": "1989", "summary": "FIFO bug fixed; widely deployed in 286/386 era."},
                {"version": "PC16550AF","year": "1991", "summary": "Improved process; same architecture."},
                {"version": "PC16550C", "year": "1993", "summary": "Lower-power CMOS version."},
                {"version": "PC16550D", "year": "1995", "summary": "Current National Semiconductor part; M2CMOS process; 24 MHz max XIN."},
            ]
        if _empty(f.get("backward_compat_traps")):
            f["backward_compat_traps"] = [
                {"trap_name": "fifo_default_disabled",
                 "16450_mode":       "After Master Reset, FCR0=0 (character mode); behaves like 16450.",
                 "fifo_mode":        "Software must explicitly write FCR0=1 to enable FIFOs.",
                 "trap": "Drivers ported from 16450 silently leave FIFOs disabled; 16550 advantage (reduced CPU interrupts) is not realized."},
                {"trap_name": "txrdy_rxrdy_pin_assignment",
                 "16450_pins":       "Pin 24 = CSOUT, Pin 29 = NC.",
                 "16550_pins":       "Pin 24 = TXRDY, Pin 29 = RXRDY (for DMA handshake).",
                 "trap": "Board designs that relied on CSOUT functionality on pin 24 will fail when populated with 16550 part."},
                {"trap_name": "original_16550_fifo_bug",
                 "PC16550_1987":     "Original 16550 had an RX FIFO error that lost characters under certain conditions; not safe to enable FIFOs.",
                 "PC16550A_and_later":"FIFOs are functional; software typically checks IIR bits 7-6 to detect a 'usable FIFO' part.",
                 "trap": "Defensive drivers check FIFO-detection signature (write FCR, read back IIR) before enabling FIFO mode."},
                {"trap_name": "dlab_register_remap",
                 "DLAB_0":           "Address 0/1 = RBR/THR / IER.",
                 "DLAB_1":           "Address 0/1 = DLL / DLM (Divisor Latches).",
                 "trap": "Forgetting to clear DLAB after setting baud rate causes subsequent THR writes to corrupt the divisor latch."},
            ]
        f.setdefault("version_naming_history_note",
            "The 16450/16550 lineage descends from National Semiconductor's INS8250 (1977). Most modern SoC UART IPs (Synopsys DesignWare UART, ARM PL011, Xilinx UARTLite) are software-register-compatible with the 16550A; the PC16550D documented here is the original hardware reference.")
        d["fields"] = f
        _write(p, d)

    # L15 encoding tables
    p = gd / "L15_ENCODING_TABLES.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("register_address_map_table", {
            "header_columns": ["DLAB", "A2", "A1", "A0", "Register"],
            "rows": [
                {"DLAB": "0", "A2": "0", "A1": "0", "A0": "0", "register": "Receiver Buffer (read), Transmitter Holding Register (write)"},
                {"DLAB": "0", "A2": "0", "A1": "0", "A0": "1", "register": "Interrupt Enable"},
                {"DLAB": "X", "A2": "0", "A1": "1", "A0": "0", "register": "Interrupt Identification (read), FIFO Control (write)"},
                {"DLAB": "X", "A2": "0", "A1": "1", "A0": "1", "register": "Line Control"},
                {"DLAB": "X", "A2": "1", "A1": "0", "A0": "0", "register": "MODEM Control"},
                {"DLAB": "X", "A2": "1", "A1": "0", "A0": "1", "register": "Line Status"},
                {"DLAB": "X", "A2": "1", "A1": "1", "A0": "0", "register": "MODEM Status"},
                {"DLAB": "X", "A2": "1", "A1": "1", "A0": "1", "register": "Scratch"},
                {"DLAB": "1", "A2": "0", "A1": "0", "A0": "0", "register": "Divisor Latch (least significant byte) DLL"},
                {"DLAB": "1", "A2": "0", "A1": "0", "A0": "1", "register": "Divisor Latch (most significant byte) DLM"},
            ],
        })
        f.setdefault("lcr_word_length_table", {
            "header_columns": ["WLS1 (LCR.1)", "WLS0 (LCR.0)", "Word Length"],
            "rows": [["0", "0", "5 bits"], ["0", "1", "6 bits"], ["1", "0", "7 bits"], ["1", "1", "8 bits"]],
        })
        f.setdefault("lcr_parity_table", {
            "header_columns": ["PEN (LCR.3)", "EPS (LCR.4)", "STICK (LCR.5)", "Parity Mode"],
            "rows": [
                ["0", "X", "X", "None"],
                ["1", "0", "0", "Odd"],
                ["1", "1", "0", "Even"],
                ["1", "0", "1", "Mark (stick = 1)"],
                ["1", "1", "1", "Space (stick = 0)"],
            ],
        })
        f.setdefault("fcr_rx_trigger_table", {
            "header_columns": ["RX_TRIGGER (FCR.7:6)", "RX FIFO Trigger Level"],
            "rows": [["00", "1 byte"], ["01", "4 bytes"], ["10", "8 bytes"], ["11", "14 bytes"]],
        })
        f.setdefault("iir_priority_table", {
            "header_columns": ["IIR Bits 3:0", "Priority", "Source", "Reset by"],
            "rows": [
                ["0110", "1 (highest)", "Receiver Line Status (OE/PE/FE/BI)", "Read LSR"],
                ["0100", "2", "Received Data Available", "Read RBR"],
                ["1100", "2", "Character Timeout (FIFO mode)",  "Read RBR"],
                ["0010", "3", "Transmitter Holding Register Empty", "Read IIR (if source) or Write THR"],
                ["0000", "4 (lowest)", "MODEM Status", "Read MSR"],
                ["0001", "—", "No interrupt pending", "—"],
            ],
        })
        f.setdefault("reset_state_table", {
            "header_columns": ["Signal / Register", "Reset State"],
            "rows": [
                ["IER", "0x00"], ["IIR", "0x01 (no interrupt pending)"], ["LCR", "0x00"], ["MCR", "0x00"],
                ["LSR", "0x60 (THRE + TEMT)"], ["FCR", "0x00"],
                ["SOUT", "HIGH (marking)"], ["INTR", "LOW"], ["OUT1, OUT2, RTS, DTR", "HIGH (inactive)"],
            ],
        })
        tbl = [
            "Table I — Reset Configuration",
            "Register Address Table (Section 6.0)",
            "DLL/DLM Baud Generator Divisor (Section 8.3)",
            "Line Control Register Word Length encoding (Section 8.1)",
            "Line Control Register Parity encoding (Section 8.1)",
            "FIFO Control Register RX trigger encoding (Section 8.5)",
            "Interrupt Identification Register encoding (Section 8.6)",
        ]
        if _empty(f.get("tables")):
            f["tables"] = tbl
        d["fields"] = f
        _write(p, d)

    # L16
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("must_have_properties", [
            "Master Reset clears IER/IIR/LCR/MCR/FCR; sets LSR to 0x60; sets outputs to inactive (Table I).",
            "After reset, FIFO is disabled (16450 mode) until FCR.0 is set.",
            "Baud rate divisor must be in range 1..65535 (DLM:DLL).",
            "Character frame = 1 start bit + 5-8 data bits LSB-first + optional parity + 1, 1.5, or 2 stop bits HIGH.",
            "Receiver oversampling = 16×; mid-bit sampling at the 8th BAUDOUT clock.",
            "False start-bit detection: re-sample 8 clocks after edge; reject if SIN returned HIGH.",
            "DLAB=1 remaps registers 0/1 to DLL/DLM; DLAB=0 restores RBR/THR + IER mapping.",
            "INTR is the OR of all enabled interrupts; IIR.0=0 indicates interrupt pending.",
            "LSR.OE/PE/FE/BI are cleared by reading LSR.",
            "MSR delta bits (DCTS/DDSR/TERI/DDCD) are cleared by reading MSR.",
            "Loopback mode (MCR.4=1): SOUT internally connected to SIN; modem outputs drive modem inputs; transmitter SOUT pin is HIGH-Z.",
        ])
        f.setdefault("must_not_have_properties", [
            "Configuration changes (LCR, MCR, divisor) during in-progress transmission corrupt the frame.",
            "Writing THR without first checking LSR.THRE=1 causes data loss.",
            "Writing FCR.0 toggling does NOT reset FIFOs unless paired with FCR.1 / FCR.2 reset bits.",
            "Reading LSR clears the OE/PE/FE/BI bits; treating them as latched across reads is forbidden.",
            "CTS does NOT gate the transmitter; software must interpret MSR.CTS for hardware flow control.",
        ])
        f.setdefault("compliance_failure_modes", [
            {"mode": "Lost RX character", "trigger": "Overrun — RBR not read before next character ready (LSR.OE=1)."},
            {"mode": "Frame error",       "trigger": "Stop bit LOW (LSR.FE=1)."},
            {"mode": "Parity error",      "trigger": "Computed parity ≠ received parity (LSR.PE=1)."},
            {"mode": "Break interrupt",   "trigger": "SIN LOW for ≥ 1 character time (LSR.BI=1)."},
            {"mode": "FIFO data error",   "trigger": "Any PE/FE/BI byte still resident in RX FIFO (LSR.RFE=1)."},
        ])
        f.setdefault("min_baud_rate_constraint",
            "Implementation-defined per crystal selection; max divisor 65535 → minimum baud = XIN / (16 × 65535).")
        f.setdefault("reset_behavior_compliance",
            "After MR pulse (≥ 1 µs HIGH), all registers in Table I are at the listed reset state; SOUT, INTR, modem outputs as per Table I.")
        d["fields"] = f
        _write(p, d)

    # L17 channel catalog (overwrite — set UART shape)
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f["channels_serial_side"] = [
            {"name": "SIN",  "direction": "input",  "purpose": "Serial data input from peripheral or modem; idle HIGH; receiver samples mid-bit.", "active_levels": "0 = start/data 0; 1 = data 1/stop/idle"},
            {"name": "SOUT", "direction": "output", "purpose": "Serial data output to peripheral or modem; idle HIGH (mark).", "active_levels": "0 = start/data 0; 1 = data 1/stop/idle"},
        ]
        f["channels_modem_handshake"] = [
            {"name": "CTS", "direction": "input",  "purpose": "Clear To Send (active LOW); modem status; software interprets, not gating TX hardware."},
            {"name": "RTS", "direction": "output", "purpose": "Request To Send (active LOW); driven by MCR.1."},
            {"name": "DSR", "direction": "input",  "purpose": "Data Set Ready (active LOW); modem status."},
            {"name": "DTR", "direction": "output", "purpose": "Data Terminal Ready (active LOW); driven by MCR.0."},
            {"name": "DCD", "direction": "input",  "purpose": "Data Carrier Detect (active LOW); modem status."},
            {"name": "RI",  "direction": "input",  "purpose": "Ring Indicator (active LOW); modem status."},
            {"name": "OUT1","direction": "output", "purpose": "User-defined output (active LOW); driven by MCR.2."},
            {"name": "OUT2","direction": "output", "purpose": "User-defined output (active LOW); driven by MCR.3."},
        ]
        f["channels_dma_handshake"] = [
            {"name": "TXRDY", "direction": "output", "purpose": "TX FIFO/THR ready; Mode 0 = THR empty; Mode 1 = FIFO empty (selected by FCR.3)."},
            {"name": "RXRDY", "direction": "output", "purpose": "RX FIFO/RBR has data; Mode 0 = data available; Mode 1 = FIFO at trigger level."},
        ]
        f["channels_cpu_bus"] = [
            {"name": "D7-D0", "direction": "bidirectional TRI-STATE", "purpose": "8-bit data bus to CPU."},
            {"name": "A0",    "direction": "input", "purpose": "Register-select address LSB."},
            {"name": "A1",    "direction": "input", "purpose": "Register-select address mid."},
            {"name": "A2",    "direction": "input", "purpose": "Register-select address MSB."},
            {"name": "CS0",   "direction": "input", "purpose": "Chip-select (active HIGH)."},
            {"name": "CS1",   "direction": "input", "purpose": "Chip-select (active HIGH)."},
            {"name": "CS2",   "direction": "input", "purpose": "Chip-select (active LOW)."},
            {"name": "RD",    "direction": "input", "purpose": "Read strobe (either RD HIGH or RD LOW with CS active enables read)."},
            {"name": "WR",    "direction": "input", "purpose": "Write strobe."},
            {"name": "ADS",   "direction": "input", "purpose": "Address strobe; positive edge latches A0-A2 + CS0-CS2; tie LOW if unused."},
            {"name": "INTR",  "direction": "output", "purpose": "Interrupt request (active HIGH)."},
            {"name": "DDIS",  "direction": "output", "purpose": "Driver Disable; LOW while CPU reads UART (for external bus transceiver)."},
        ]
        f["channels_clock_reset"] = [
            {"name": "XIN",     "direction": "input",  "purpose": "Baud-rate-generator clock input (≤ 24 MHz)."},
            {"name": "XOUT",    "direction": "output", "purpose": "Crystal feedback inverter output; unused if external clock applied."},
            {"name": "BAUDOUT", "direction": "output", "purpose": "16× baud-rate clock; tie to RCLK or external use."},
            {"name": "RCLK",    "direction": "input",  "purpose": "Receiver 16× clock input."},
            {"name": "MR",      "direction": "input",  "purpose": "Master Reset (active HIGH; Schmitt input)."},
        ]
        f["global_signals"] = [
            {"name": "VDD", "purpose": "+5 V ± 10 % supply."},
            {"name": "VSS", "purpose": "Ground (0 V)."},
        ]
        f["channel_counts"] = {
            "serial_data_pins": 2, "modem_control_pins": 6,
            "user_output_pins": 2, "dma_handshake_pins": 2,
            "cpu_data_bus_bits": 8, "cpu_address_pins": 3,
            "chip_select_pins": 3, "cpu_control_pins": 5,
            "clock_reset_pins": 5, "supply_pins": 2,
            "total_external_pins": 40,
        }
        # Force-overwrite dependency_graph (earlier steps may have written
        # AXI-leaning content; UART shape is fundamentally different).
        f["dependency_graph"] = {
            "common_rule": "TX and RX paths are independent (full duplex). Master Reset gates all output activity. Baud generator drives both TX and RX at 16× the bit rate.",
            "data_dependency": "Transmitter shifts on each /16 BAUDOUT edge. Receiver samples mid-bit on the 8th of every 16 BAUDOUT edges.",
        }
        f.setdefault("ordering_rules", {
            "byte_ordering": "LSB-first on the serial wire.",
            "register_ordering": "DLAB must be set/cleared correctly to select between (RBR/THR/IER) and (DLL/DLM) views.",
        })
        d["fields"] = f
        _write(p, d)

    # L18 interconnect
    p = gd / "L18_INTERCONNECT_TOPOLOGY.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f["topology_type"] = "Point-to-point asynchronous serial (TX → peer RX, RX ← peer TX) with optional 6-wire modem handshake."
        f["supported_topologies"] = [
            {"name": "Two-wire point-to-point",  "description": "SOUT ↔ SIN cross-connected between two UARTs; common ground reference; no clock wire."},
            {"name": "Modem (DTE-DCE) link",     "description": "Full RS-232 link via external line driver: 2 data + 6 modem handshake (CTS/RTS/DSR/DTR/DCD/RI)."},
            {"name": "RS-485 multi-drop",        "description": "External RS-485 transceiver with direction enabled by RTS or OUT1/OUT2; multi-node half-duplex."},
            {"name": "TTL-level loopback",       "description": "MCR.LOOP=1; internal SOUT→SIN; modem outputs drive modem inputs; for chip-level diagnostic."},
        ]
        f["master_slave_role_summary"] = [
            {"role": "DTE (Data Terminal Equipment)", "description": "A UART acting as the data source/sink (e.g. PC); drives DTR + RTS; receives DSR / CTS / DCD / RI from DCE."},
            {"role": "DCE (Data Circuit Equipment)",  "description": "A modem or peer; drives DSR / CTS / DCD / RI; receives DTR + RTS from DTE."},
            {"role": "Peer-to-peer (null modem)",      "description": "Two UARTs back-to-back with crossed TX/RX + crossed RTS/CTS + crossed DTR/DSR/DCD."},
        ]
        f["interconnect_role"] = (
            "There is no protocol-layer interconnect (no router). The UART "
            "is one endpoint of a 2-wire async serial link; routing/"
            "switching happens at the application layer (e.g. modem dial-"
            "up) or via external multiplexers.")
        f["ordering_guarantees"] = {
            "within_a_byte":  "Bits transmitted LSB-first; receiver reassembles in same order.",
            "across_bytes":   "Strictly in software-issue order (no reordering); TX FIFO is FIFO; RX FIFO is FIFO.",
        }
        f.setdefault("memory_vs_peripheral_regions",
            "Not applicable — UART is one peripheral; its 8 register slots live in the SoC's I/O space.")
        f.setdefault("slave_classification", {
            "polling_target":     "Software polls LSR.DR / THRE for non-interrupt-driven operation.",
            "interrupt_target":   "INTR signal drives external interrupt controller; software services via IIR-identified source.",
            "dma_target":         "TXRDY/RXRDY drive an external DMA controller for high-throughput data movement.",
        })
        f.setdefault("default_signal_values_evidence_tables", [
            "Table I — Reset Configuration of the UART",
            "Section 6.0 Pin Descriptions",
            "Section 7.0 Connection Diagrams",
        ])
        f.setdefault("modem_control_topology", {
            "DTE_outputs": ["DTR", "RTS"],
            "DTE_inputs":  ["DSR", "CTS", "DCD", "RI"],
            "active_polarity": "All modem control signals are active LOW at the modem interface.",
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
            "PC16550D is a stand-alone 40-pin packaged part; no PDK / "
            "floorplan / SDC constraints in the datasheet. M2CMOS process "
            "is mentioned but no design rules. Modern SoC integrations "
            "(Synopsys DesignWare UART, Cadence UART IP, ARM PL011) "
            "provide their own SDC + UPF + DFT files at the IP-license "
            "level.")
        d["fields"] = f
        _write(p, d)

    # L20 DFT
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f["dft_present"] = "partial"
        f.setdefault("internal_diagnostics", [
            "Loopback (MCR.LOOP=1) — SOUT internally drives SIN; modem outputs drive modem inputs.",
            "Error simulation through loopback — break, parity, overrun, framing error scenarios reproducible without external hardware.",
            "FIFO reset (FCR.RX_FIFO_RESET / FCR.TX_FIFO_RESET) — self-clearing in-chip RAM reset.",
        ])
        f["notes"] = (
            "PC16550D pre-dates scan-insertion as a standard DFT approach. "
            "Internal diagnostic features (loopback + error injection "
            "through register manipulation) are the documented DFT story. "
            "SoC-integrated 16550-compatible UART IP from modern vendors "
            "adds standard scan insertion at the integrator level.")
        d["fields"] = f
        _write(p, d)

    # L21 power
    p = gd / "L21_POWER_INTENT.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("power_intent_present", False)
        f["low_power_modes_summary"] = {
            "active_run": "ICC max 15 mA at VDD = 5.5 V; XIN running.",
            "clock_gating": "Reducing XIN frequency reduces dynamic current proportionally.",
            "no_explicit_sleep_mode": "PC16550D has no formal sleep/standby register; standby is achieved by stopping XIN externally.",
        }
        f["notes"] = "M2CMOS process; absolute max power dissipation 1 W. No power-domain partitioning at the chip level."
        d["fields"] = f
        _write(p, d)

    # L23 security
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("security_requirements_present", False)
        f["notes"] = (
            "PC16550D datasheet (1995) predates modern security "
            "requirements. No confidentiality / integrity / authentication "
            "features at the chip level. Serial data on SIN/SOUT is in "
            "plaintext. Application-layer security (TLS, SSH, etc.) is "
            "layered on top of the byte stream.")
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
def is_uart(blob: str) -> bool:
    """Content-only `uart` detector (importable, lifted from the runner) WITH a
    FOREIGN-PRIMARY DEFER.

    Empty-safe. Reads ONLY ``blob`` (spec text). The original structural UART
    signature below (SIN+SOUT pin pair, 16450/16550 lineage, or
    UART + start/stop framing) is necessary but NOT sufficient: many serial /
    fieldbus protocols either (a) physically transport their bytes in async
    UART start/stop frames (LIN, IO-Link COMx octets, PROFIBUS / Modbus over an
    async wire, RS-485 transceivers carrying a UART payload) or (b) merely cite
    UART framing as an incidental comparison (ARINC 429, NFC, BLE, SWD). Those
    foreign specs trip the loose ``UART`` + ``start bit`` + ``stop bit`` branch
    (and a few huge superset docs even carry the literal PC16550D text), so the
    generic UART synth would inject PC16550D register/framing content into a
    foreign protocol's L-docs.

    Guard (mirrors `is_mipi`'s foreign-primary defer doctrine and the
    sibling-MUTEX pattern of `is_modbus` / `is_profibus` / `is_rs485` — general,
    content-only, NO chip / SKU / benchmark-directory literal as detection
    logic): if the blob's DOMINANT subject is one of those foreign protocols
    (detected by THAT protocol's own distinctive multi-token structural
    signature — the SAME signature its own ``is_<proto>`` detector keys on, not
    by the incidental UART mention), defer (False).

    Empirically corpus-clean (test_protocol_detector_no_misfire.py): the real
    `uart` (PC16550D) benchmark trips NONE of these foreign-primary signatures
    (it carries no LIN/IO-Link/PROFIBUS/Modbus/RS-485-PHY/ARINC/NFC/BLE/SWD
    structure) and stays True; the nine foreign superset/incidental specs each
    trip their own protocol's signature and are suppressed.
    """
    if not blob:
        return False
    low = blob.lower()

    # --- FOREIGN-PRIMARY DEFER (the blob's true subject is NOT a 16550 UART,
    #     even though it transports / cites async start/stop framing). ---

    # LIN-primary: the Local Interconnect Network signature (its name anchor +
    # the BREAK/SYNC frame header or the single-master + schedule-table MAC).
    # LIN is a UART-framed automotive sub-bus, so it carries UART tokens, but a
    # 16550 UART spec has no LIN name / BREAK+SYNC / schedule table.
    lin_primary = (
        ("LIN bus" in blob or "Local Interconnect Network" in blob
         or "LIN Consortium" in blob or "LIN 2." in blob)
        and (("BREAK" in blob.upper() and "SYNC" in blob.upper())
             or ("master" in low and "schedule" in low)))

    # IO-Link-primary: the SDCI / IEC 61131-9 structural signature (the name
    # anchor + the C/Q combined communication-and-switching line). IO-Link
    # exchanges UART 8-E-1 octets but a plain UART has no C/Q dual-mode line.
    io_link_primary = (
        ("sdci" in low or "iec 61131-9" in low or "iec61131-9" in low
         or "io-link" in low or "io link" in low)
        and ("c/q" in low
             or "combined communication and switching" in low
             or "combined communication + switching" in low))

    # PROFIBUS-primary: the PROFIBUS-DP structural signature (name + DP/PA
    # profile + at least one PROFIBUS-only frame/service feature: SD1-SD4
    # telegram delimiters, DPV0-2 service levels, or DSAP/SSAP).
    _pb_name = "profibus" in low or "process field bus" in low
    _pb_profile = ("profibus-dp" in low or "decentralized periphery" in low
                   or "decentralised periphery" in low
                   or "profibus-pa" in low or "process automation" in low)
    _pb_feature = (
        sum(t in blob for t in ("SD1", "SD2", "SD3", "SD4")) >= 3
        or sum(t in blob for t in ("DPV0", "DPV1", "DPV2")) >= 2
        or ("dsap" in low and "ssap" in low))
    profibus_primary = _pb_name and _pb_profile and _pb_feature

    # Modbus-primary: the application-layer Modbus PDU framing model, OR the
    # canonical register/coil access function names. A 16550 UART spec carries
    # neither (it is the wire below such a protocol, not the protocol).
    modbus_primary = (
        ("Modbus" in blob and "Function Code" in blob and "PDU" in blob)
        or ("Read Holding Registers" in blob and "Read Coils" in blob))

    # RS-485-primary: the transceiver / PHY design-guide signature (TI SLLA272
    # design guide, OR an RS-485 transceiver with its termination / unit-load /
    # TIA-485 electrical vocabulary). This is the line-driver layer, not a UART.
    rs485_primary = (
        "SLLA272" in blob
        or "RS-485 Design Guide" in blob
        or ("RS-485 transceiver" in blob
            and ("120 Ω" in blob or "120 ohm" in low
                 or "32 unit load" in low or "TIA/EIA-485" in blob
                 or "TIA-485" in blob)))

    # ARINC 429-primary: the avionics DITS word signature (Mark 33 + DITS, OR
    # ARINC 429 + Label + SSM/Sign-Status). A UART spec carries no avionics
    # 32-bit-word / Label / SSM framing.
    arinc429_primary = (
        ("ARINC 429" in blob and "Label" in blob
         and ("SSM" in blob or "Sign/Status" in blob))
        or ("Mark 33" in blob and "DITS" in blob))

    # NFC-primary: the ISO 14443 / MIFARE contactless signature. None of its
    # PCD/PICC/ATQA/UID/SAK tokens appear in a UART spec.
    nfc_primary = (
        ("NFC" in blob and "ISO 14443" in blob and "UID" in blob)
        or ("MIFARE" in blob and "13.56" in blob and "SAK" in blob)
        or ("PCD" in blob and "PICC" in blob and "ATQA" in blob))

    # BLE-primary: the Bluetooth Low Energy structural signature (Core stack
    # GAP/GATT, advertising+connection, or the 2.4 GHz 40-channel PHY). A UART
    # spec has none of the Bluetooth Core vocabulary.
    ble_primary = (
        ("Bluetooth Low Energy" in blob and "advertising" in low
         and "connection" in low)
        or ("BLE" in blob and "GAP" in blob and "GATT" in blob)
        or ("Bluetooth" in blob and "LE" in blob
            and "2.4 GHz" in blob and "40 channels" in blob))

    # SWD-primary: the ARM Serial-Wire Debug / ADIv5 transport signature
    # (SWDIO+SWCLK+DAP, SWD+ADIv5+DP+AP, or SWJ-DP+ARM+Debug Port). A UART spec
    # has no serial-wire debug-port structure.
    swd_primary = (
        ("SWDIO" in blob and "SWCLK" in blob and "DAP" in blob)
        or ("SWD" in blob and "ADIv5" in blob and "DP" in blob and "AP" in blob)
        or ("SWJ-DP" in blob and "ARM" in blob and "Debug Port" in blob))

    if (lin_primary or io_link_primary or profibus_primary or modbus_primary
            or rs485_primary or arinc429_primary or nfc_primary or ble_primary
            or swd_primary):
        return False

    # --- STRUCTURAL UART (16450/16550) signature (unchanged from the runner's
    #     inline detector). ---
    return bool(
        ("SIN" in blob and "SOUT" in blob)
        or ("16450" in blob and "16550" in blob)
        or ("UART" in blob
            and "start bit" in blob.lower()
            and "stop bit" in blob.lower()))
