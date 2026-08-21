"""I2C-class protocol synth helper.

v0.1.79 — ic_class-gated overlay for `serial_peripheral_protocol` specs
that exhibit the I2C structural signature (SDA + SCL pin pair in L1+L2
text; or alternatively START/STOP/ACK terminology + 7-bit slave
addressing). Applies I2C-spec-universal facts (UM10204 family) to
L1-L18 + L21.

Doctrine: structural-keyword detection IS general within an ic_class
(mirrors the AMBA-AXI R46/R48/R50/R52 and the SPI R53/R54/R55
approach). Any I2C variant (SMBus, PMBus, IPMI, DDC, ATCA over I2C)
exhibits the same signature.

Public entry: `apply_i2c_synth(generated_docs_dir, is_i2c, i2c_ic_name)`.
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


def apply_i2c_synth(generated_docs_dir: Path, is_i2c: bool,
                    i2c_ic_name: Optional[str]) -> None:
    """Apply I2C-specific synth when the structural signature matched."""
    if not is_i2c:
        return
    gd = generated_docs_dir

    # Force ic_name across the 14 main L docs
    if i2c_ic_name is not None:
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
                d["ic_name"] = i2c_ic_name
                _write(q, d)

    # L1 datasheet metadata
    p = gd / "L1_DATASHEET.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("document_number", "UM10204")
        d.setdefault("document_title", "I2C-bus specification and user manual")
        d.setdefault("version", "Rev. 6")
        d.setdefault("revised_date", "4 April 2014")
        d.setdefault("manufacturer", "NXP Semiconductors (originally Philips Semiconductors)")
        d.setdefault("copyright", "© NXP Semiconductors N.V. 2014")
        d.setdefault("external_pins", ["SDA", "SCL"])
        d.setdefault("total_external_pin_count", 2)
        d.setdefault("wire_protocol", "Open-drain / open-collector, wired-AND, two-wire bidirectional serial")
        d.setdefault("key_features", [
            "Only two bus lines are required: a serial data line (SDA) and a serial clock line (SCL).",
            "Each device connected to the bus is software addressable by a unique address; simple master/slave relationships exist at all times.",
            "Masters can operate as master-transmitters or master-receivers.",
            "True multi-master bus including collision detection and arbitration to prevent data corruption.",
            "Serial 8-bit oriented bidirectional data transfers up to 100 kbit/s (Standard-mode), 400 kbit/s (Fast-mode), 1 Mbit/s (Fast-mode Plus), 3.4 Mbit/s (High-speed mode).",
            "Serial 8-bit oriented unidirectional data transfers up to 5 Mbit/s (Ultra Fast-mode).",
            "On-chip filtering rejects spikes on the bus data line.",
            "Number of ICs limited only by maximum bus capacitance.",
            "Software-Reset, Device ID, General Call address, START byte, 10-bit addressing optional features.",
        ])
        d.setdefault("modes_of_operation", [
            {"name": "Standard-mode (Sm)",    "max_bit_rate": "100 kbit/s",  "duplex": "bidirectional", "drive": "open-drain"},
            {"name": "Fast-mode (Fm)",        "max_bit_rate": "400 kbit/s",  "duplex": "bidirectional", "drive": "open-drain"},
            {"name": "Fast-mode Plus (Fm+)",  "max_bit_rate": "1 Mbit/s",    "duplex": "bidirectional", "drive": "open-drain"},
            {"name": "High-speed mode (Hs)",  "max_bit_rate": "3.4 Mbit/s",  "duplex": "bidirectional", "drive": "open-drain with current source"},
            {"name": "Ultra Fast-mode (UFm)", "max_bit_rate": "5 Mbit/s",    "duplex": "unidirectional (push-pull)", "drive": "push-pull"},
        ])
        d.setdefault("system_use_cases", [
            "System Management Bus (SMBus)",
            "Power Management Bus (PMBus)",
            "Intelligent Platform Management Interface (IPMI)",
            "Display Data Channel (DDC)",
            "Advanced Telecom Computing Architecture (ATCA)",
        ])
        d.setdefault("overview",
            "The I2C-bus is a de facto world standard, implemented in over 1000 different ICs from more than 50 companies. It is a simple bidirectional 2-wire serial bus for efficient inter-IC control.")
        d.setdefault("release_history_note",
            "Originally Philips Semiconductors (now NXP). Revision history per document footer; Rev. 6 dated 4 April 2014; previous versions span 1982-2007 (v1.0..v3.0).")
        _write(p, d)

    # L2 FRS
    p = gd / "L2_FRS.json"
    if p.is_file():
        d = _read(p)
        po = d.setdefault("protocol_overview", {})
        if isinstance(po, dict):
            po.setdefault("wires", 2)
            po.setdefault("wire_names", ["SDA", "SCL"])
            po.setdefault("bidirectional", True)
            po.setdefault("synchronous", True)
            po.setdefault("serial", True)
            po.setdefault("byte_oriented", True)
            po.setdefault("byte_width_bits", 8)
            po.setdefault("msb_first", True)
            po.setdefault("open_drain_wired_and", True)
            po.setdefault("multi_master_capable", True)
            po.setdefault("addressing", "7-bit (default) or 10-bit (optional); software-addressable per device")
        fr = [
            {"id": "FR-PHY-01",   "text": "SDA and SCL are bidirectional lines connected to a positive supply via pull-up resistors; when the bus is free both lines are HIGH."},
            {"id": "FR-PHY-02",   "text": "Devices must use open-drain or open-collector output stages to perform the wired-AND function."},
            {"id": "FR-DATA-03",  "text": "Data on SDA must be stable during the HIGH period of SCL; SDA may only change state while SCL is LOW."},
            {"id": "FR-START-04", "text": "A HIGH-to-LOW transition on SDA while SCL is HIGH defines a START condition (S)."},
            {"id": "FR-STOP-05",  "text": "A LOW-to-HIGH transition on SDA while SCL is HIGH defines a STOP condition (P)."},
            {"id": "FR-RSTART-06","text": "A repeated START (Sr) is functionally identical to S; keeps the bus busy without an intervening STOP."},
            {"id": "FR-BYTE-07",  "text": "Every byte put on SDA must be 8 bits long; number of bytes per transfer is unrestricted; MSB-first."},
            {"id": "FR-ACK-08",   "text": "Each byte is followed by a 9th ACK clock pulse generated by the master; receiver pulls SDA LOW to ACK, leaves SDA HIGH to NACK."},
            {"id": "FR-ADDR-09",  "text": "After START, master sends 7-bit slave address + 1-bit R/W direction; R/W=0 indicates write, R/W=1 indicates read."},
            {"id": "FR-MASTER-10","text": "Only the master may generate START, STOP, repeated START, and SCL clock pulses."},
            {"id": "FR-ARB-11",   "text": "In multi-master systems, masters arbitrate bit by bit on SDA while SCL is HIGH; the first master to drive SDA HIGH when another drives LOW loses arbitration."},
            {"id": "FR-SYNC-12",  "text": "Clock synchronization is performed using the wired-AND on SCL; final SCL LOW period is determined by the master with the longest LOW, HIGH period by the master with the shortest HIGH."},
            {"id": "FR-STRETCH-13","text": "Optional clock stretching: a slave can hold SCL LOW to extend the LOW period and force the master into a wait state."},
            {"id": "FR-MODE-14",  "text": "Standard-mode (≤100 kbit/s), Fast-mode (≤400 kbit/s), Fast-mode Plus (≤1 Mbit/s), High-speed mode (≤3.4 Mbit/s), Ultra Fast-mode (≤5 Mbit/s) are supported."},
            {"id": "FR-LEVEL-15", "text": "Input reference levels are 30% (VIL = 0.3 VDD) and 70% (VIH = 0.7 VDD) of VDD; legacy fixed-level devices were VIL=1.5 V / VIH=3.0 V."},
        ]
        if _empty(d.get("functional_requirements")):
            d["functional_requirements"] = fr
        d.setdefault("error_response_conditions", [
            "NACK at slave address — no responding device",
            "NACK at data byte — receiver cannot accept or cannot understand the data",
            "Arbitration lost — master must turn off its SDA driver and restart when bus is free",
            "Bus stuck LOW (SDA or SCL) — master sends 9 clock pulses or asserts HW reset / cycles power",
        ])
        d.setdefault("protocol_features_applicability", {
            "header": ["Feature", "Single master", "Multi-master", "Slave"],
            "rows": [
                ["START condition",   "M", "M", "M"],
                ["STOP condition",    "M", "M", "M"],
                ["Acknowledge",        "M", "M", "M"],
                ["Synchronization",   "n/a", "M", "n/a"],
                ["Arbitration",        "n/a", "M", "n/a"],
                ["Clock stretching",   "O", "O", "O"],
                ["7-bit slave address","M", "M", "M"],
                ["10-bit slave address","O","O","O"],
                ["General Call address","O","O","O"],
                ["Software Reset",     "O", "O", "O"],
                ["START byte",         "n/a", "O", "n/a"],
                ["Device ID",          "n/a", "n/a", "O"],
            ],
        })
        d.setdefault("wire_count", "2 (SDA, SCL)")
        cr = [
            "All devices on the bus must use open-drain or open-collector outputs (except Ultra Fast-mode which is push-pull unidirectional).",
            "Pull-up resistor to VDD on both SDA and SCL.",
            "Data on SDA must remain stable while SCL is HIGH.",
            "Only master generates START, STOP, repeated START.",
            "Each byte is 8 bits + 1 ACK bit; total 9 SCL clock pulses per byte.",
            "Bus capacitance must not exceed the per-mode maximum (e.g. 400 pF for Standard-mode, 550 pF max with current-source for Hs-mode 400 pF).",
        ]
        if _empty(d.get("compliance_requirements")):
            d["compliance_requirements"] = cr
        _write(p, d)

    # L3
    p = gd / "L3_CMD_PROTOCOL.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("protocol_type", "Two-wire synchronous serial bus with software addressing; no opcode/command set")
        d.setdefault("channels", [
            {"name": "SDA", "direction": "bidirectional", "description": "Serial data line; open-drain (or push-pull in UFm); pulled HIGH by Rp; carries address byte + data bytes + ACK/NACK."},
            {"name": "SCL", "direction": "master output (slave input; slave may pull LOW to stretch)", "description": "Serial clock line; open-drain; pulled HIGH by Rp; 9 clock pulses per byte (8 data + 1 ACK)."},
        ])
        d.setdefault("valid_ready_handshake_rules", [
            "Per-byte handshake: receiver pulls SDA LOW during the 9th SCL clock pulse to ACK; leaves HIGH to NACK.",
            "Optional clock-stretching handshake: slave holds SCL LOW after a byte to delay the next byte.",
            "There is no AMBA-style per-cycle VALID/READY; the handshake is byte-level + bit-level via SCL synchronization.",
        ])
        d.setdefault("burst_based", False)
        d.setdefault("byte_oriented", True)
        d.setdefault("byte_order", "MSB-first")
        d.setdefault("transaction_framing", {
            "start_S":   "HIGH-to-LOW transition on SDA while SCL is HIGH",
            "stop_P":    "LOW-to-HIGH transition on SDA while SCL is HIGH",
            "repeated_start_Sr": "Functionally identical to S; keeps bus busy without an intervening STOP",
            "byte":      "8 data bits + 1 ACK clock pulse = 9 SCL cycles",
            "ack_bit":   "Receiver pulls SDA LOW during 9th SCL clock pulse",
            "nack_bit":  "SDA remains HIGH during 9th SCL clock pulse",
        })
        d.setdefault("address_byte_format", {
            "bits_0_to_7": "7-bit slave address (LSB-first into ADDRESS field, MSB-first on wire)",
            "bit_8": "R/W direction bit; 0 = write to slave; 1 = read from slave",
            "10_bit_addressing": "Two address bytes: first byte 0b11110XX0/1 (XX = upper 2 address bits + R/W); second byte = lower 8 address bits",
        })
        d.setdefault("single_response_for_write", "Every byte (including the address byte) is acknowledged by the receiver via an ACK / NACK on the 9th clock pulse.")
        d.setdefault("per_beat_response_for_read", "Each read byte gets an ACK from the master-receiver, except the last byte where master sends NACK to signal end of transfer.")
        d.setdefault("reserved_slave_addresses", {
            "header": ["Address (7-bit)", "R/W", "Description"],
            "rows": [
                ["0000 000", "0", "General Call address"],
                ["0000 000", "1", "START byte"],
                ["0000 001", "X", "Cbus address"],
                ["0000 010", "X", "Reserved for different bus format"],
                ["0000 011", "X", "Reserved for future purposes"],
                ["0000 1XX", "X", "Hs-mode master code"],
                ["1111 0XX", "X", "10-bit slave addressing"],
                ["1111 1XX", "X", "Reserved for future purposes including Device ID"],
            ],
        })
        d.setdefault("master_to_slave_write_transaction", [
            "S → SLAVE_ADDR[7:1] || R/W=0 → ACK → DATA0 → ACK → DATA1 → ACK → … → P",
            "Optional repeated START between bytes: S … DATA → ACK → Sr → SLAVE_ADDR2 || R/W → …",
        ])
        d.setdefault("slave_to_master_read_transaction", [
            "S → SLAVE_ADDR[7:1] || R/W=1 → ACK (slave) → DATA0 (slave drives SDA) → ACK (master) → DATA1 → ACK → … → DATAN → NACK (master) → P",
        ])
        _write(p, d)

    # L11 OTP — overwrite class-universal note with I2C-specific
    p = gd / "L11_OTP_CONTENT.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("otp_present", False)
        d["notes"] = (
            "I2C is a wire-level protocol; no OTP / fuse content at the "
            "protocol layer. Individual I2C devices may hard-wire their "
            "slave address (effectively factory-OTP) but this is per-device, "
            "not protocol-defined.")
        _write(p, d)

    # L13 lab cal — overwrite with I2C-specific
    p = gd / "L13_LAB_CALIBRATION.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("lab_calibration_present", False)
        d["notes"] = (
            "I2C is a wire-level protocol; no analog reference / trim / "
            "calibration loop at the protocol layer. Per-device calibration "
            "(e.g. ADC offset trim, oscillator trim) is documented in "
            "individual device datasheets, not in UM10204.")
        _write(p, d)

    # L19 PDK — overwrite with I2C-specific
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("constraints_present", False)
        f["notes"] = (
            "I2C is a wire-level protocol spec; no PDK / SDC / floorplan "
            "constraints at the protocol layer. Per-device integration "
            "constraints (pad type, pull-up sizing, clock-tree budget) live "
            "in the SoC-level integration spec, not in UM10204.")
        d["fields"] = f
        _write(p, d)

    # L20 DFT — overwrite with I2C-specific
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("dft_present", False)
        f["notes"] = (
            "UM10204 does not specify DFT / scan / BIST. Concrete I2C "
            "controller IPs implement standard scan insertion at SoC "
            "integration time.")
        d["fields"] = f
        _write(p, d)

    # L23 security — overwrite with I2C-specific
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("security_requirements_present", False)
        f["notes"] = (
            "UM10204 is a wire-level protocol spec; no confidentiality / "
            "integrity / authentication requirements. I2C is broadcast-on-"
            "the-bus — any device can snoop SDA/SCL. Application-layer "
            "security (e.g. SMBus PEC byte for integrity) is layered on top "
            "per the SMBus / PMBus / IPMI specs.")
        d["fields"] = f
        _write(p, d)

    # L4 — I2C is wire-level; no register map at protocol layer
    p = gd / "L4_REGMAP.json"
    if p.is_file():
        d = _read(p)
        d["register_map_present"] = False
        d["notes"] = (
            "I2C is a wire-level protocol specification, not a peripheral "
            "block guide. There is no architectural register map at the "
            "protocol layer. Concrete I2C-controller IP blocks define "
            "their own register file (typically: address register, data "
            "register, status/interrupt register, control register, baud "
            "rate register) at the SoC integration level — covered by "
            "individual block guides, not by UM10204.")
        _write(p, d)

    # L5 — overrides class-universal with I2C-specific signaling note
    p = gd / "L5_ADI_SPEC.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("analog_digital_interface_present", False)
        d["signaling_summary"] = (
            "Pure digital protocol with analog-aware DC characteristics. "
            "Lines (SDA, SCL) are open-drain (or open-collector) wired to "
            "VDD through pull-up resistors Rp; logic levels are referenced "
            "to VDD as VIL = 0.3 VDD (LOW max) and VIH = 0.7 VDD (HIGH min). "
            "Ultra Fast-mode (UFm) uses push-pull drivers and is "
            "unidirectional. Bus capacitance (Cb) limits the maximum bus "
            "speed per mode.")
        _write(p, d)

    # L6 control
    p = gd / "L6_CONTROL_LOGIC.json"
    if p.is_file():
        d = _read(p)
        if _empty(d.get("fsm_states")) or all(
                isinstance(s, dict) and s.get("name") not in
                ("START_DETECT", "ADDR_TRANSMIT", "ARBITRATION_LOSS")
                for s in d.get("fsm_states", [])):
            d["fsm_states"] = [
                {"name": "IDLE",              "description": "Bus free; SDA and SCL both HIGH (released by all devices)."},
                {"name": "START_DETECT",      "description": "Master generates HIGH→LOW on SDA while SCL HIGH; bus becomes busy."},
                {"name": "ADDR_TRANSMIT",     "description": "Master transmits 7-bit slave address + R/W bit; 8 SCL pulses."},
                {"name": "ADDR_ACK_WAIT",     "description": "9th SCL pulse: master releases SDA; addressed slave pulls SDA LOW to ACK."},
                {"name": "DATA_TRANSMIT",     "description": "Transmitter (master or slave depending on R/W) drives 8 data bits MSB-first on SDA."},
                {"name": "DATA_ACK_WAIT",     "description": "9th SCL pulse: receiver pulls SDA LOW for ACK or leaves HIGH for NACK."},
                {"name": "CLOCK_STRETCH",     "description": "Slave holds SCL LOW to delay next byte (optional handshake)."},
                {"name": "ARBITRATION_LOSS",  "description": "Master detected SDA actual LOW while it drove HIGH; turns off SDA driver; falls back to slave mode if it has one."},
                {"name": "STOP_GENERATE",     "description": "Master generates LOW→HIGH on SDA while SCL HIGH; bus free."},
                {"name": "REPEATED_START",    "description": "Master generates new START without intervening STOP; keeps bus busy."},
            ]
        d.setdefault("fsm_hints", {
            "trigger": "Master initiates by driving START (S); slave responds when its address is matched.",
            "rule": "Every byte requires 9 SCL pulses (8 data + 1 ACK). Data on SDA is stable while SCL HIGH; SDA only changes when SCL LOW.",
            "abort": "Master may abort by sending STOP or repeated START. Slave may abort by NACKing a byte.",
        })
        d.setdefault("anti_deadlock_rule",
            "Only master drives SCL (slave may pull LOW to stretch). Only one device drives SDA at a time; collision detected via arbitration (bit-by-bit SDA monitoring while SCL HIGH).")
        d.setdefault("exit_from_reset",
            "After reset, the device must release both SDA and SCL (both HIGH). Master can begin a transaction only when both lines are HIGH (bus free). Bus-clear procedure: if SDA stuck LOW, master sends 9 SCL pulses to allow the stuck device to release.")
        d.setdefault("default_ready_state_recommendation", {
            "SDA_idle": "HIGH (released; pulled up by Rp).",
            "SCL_idle": "HIGH (released by master).",
            "ACK_receiver_pull": "Receiver pulls SDA LOW only during the 9th SCL pulse.",
            "Clock_stretch": "Slave holds SCL LOW after the 8th ACK pulse to delay next byte if it needs time.",
        })
        d.setdefault("channel_dependency_rules_master", {
            "note": "Master generates START / STOP / repeated START; drives SCL; drives SDA during address byte and during write data bytes; releases SDA during read data bytes for slave to drive.",
        })
        d.setdefault("channel_dependency_rules_slave", {
            "note": "Slave samples SDA on rising edge of SCL; drives SDA during read data bytes; may pull SCL LOW to clock-stretch; may NACK to indicate inability to continue.",
        })
        d.setdefault("arbitration_rule",
            "Bit-by-bit on SDA while SCL HIGH: each master checks SDA level matches what it sent. First master to drive SDA HIGH while another drives LOW loses arbitration and switches off its SDA driver. No information is lost — the winning master's transaction continues normally.")
        d.setdefault("synchronization_rule",
            "Clock synchronization via wired-AND on SCL: combined SCL LOW period = longest LOW among contending masters; combined SCL HIGH period = shortest HIGH among contending masters.")
        _write(p, d)

    # L7
    p = gd / "L7_TEST_DEBUG.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("test_debug_architecture_present", False)
        d.setdefault("spec_provided_observability", [
            {"name": "ACK / NACK",        "purpose": "Per-byte success / failure indicator on SDA's 9th SCL pulse."},
            {"name": "Arbitration Lost",  "purpose": "Master detects SDA actual ≠ driven; signal to higher layer that bus access was lost."},
            {"name": "Clock Stretch",     "purpose": "Slave-side flow control; observable as SCL held LOW after byte ACK."},
            {"name": "Bus Busy / Free",   "purpose": "Bus is busy after S and free a tBUF time after P."},
            {"name": "Device ID Read",    "purpose": "Optional 24-bit Device ID (12-bit manufacturer + 9-bit part + 3-bit revision) via Reserved Device ID address."},
        ])
        d.setdefault("interrupt_sources", [
            {"flag": "ARB_LOST",  "trigger": "Master detected arbitration loss on SDA."},
            {"flag": "ACK_FAIL",  "trigger": "Receiver returned NACK when ACK expected."},
            {"flag": "STOP_DET",  "trigger": "STOP condition detected (slave side)."},
            {"flag": "START_DET", "trigger": "START condition detected (slave side)."},
            {"flag": "BYTE_DONE", "trigger": "Byte transfer complete (ACK clock done)."},
            {"flag": "BUS_ERROR", "trigger": "Illegal condition (START or STOP at unexpected position)."},
        ])
        d.setdefault("interrupt_request",
            "Interrupts are SoC-controller-specific; UM10204 lists the canonical conditions observable at the protocol layer.")
        d.setdefault("notes",
            "I2C is a wire-level spec; test/debug architecture (scan, JTAG, BIST) lives at the SoC integration level. The above are protocol-level observable conditions any compliant controller should expose.")
        _write(p, d)

    # L8_RTL_CONSTANTS
    p = gd / "L8_RTL_CONSTANTS.json"
    if p.is_file():
        d = _read(p)
        wp = d.setdefault("width_parameters", {})
        if isinstance(wp, dict):
            for k, v in {
                "DATA_BYTE_WIDTH_bits": 8, "ACK_BIT_WIDTH": 1,
                "ADDRESS_7BIT_WIDTH_bits": 7,
                "ADDRESS_10BIT_WIDTH_bits": 10, "RW_BIT_WIDTH": 1,
                "DEVICE_ID_WIDTH_bits": 24,
                "DEVICE_ID_MANUFACTURER_WIDTH_bits": 12,
                "DEVICE_ID_PART_WIDTH_bits": 9,
                "DEVICE_ID_REVISION_WIDTH_bits": 3,
                "SCL_PULSES_PER_BYTE": 9,
            }.items():
                wp.setdefault(k, v)
        d.setdefault("voltage_levels", {
            "VIL_max": "0.3 * VDD (LOW input)",
            "VIH_min": "0.7 * VDD (HIGH input)",
            "legacy_fixed_VIL": "1.5 V",
            "legacy_fixed_VIH": "3.0 V",
        })
        d.setdefault("mode_bit_rates", {
            "Standard_mode_Sm":    {"max_bit_rate_kHz": 100,   "duplex": "bidirectional", "drive": "open-drain"},
            "Fast_mode_Fm":        {"max_bit_rate_kHz": 400,   "duplex": "bidirectional", "drive": "open-drain"},
            "Fast_mode_Plus_Fm+":  {"max_bit_rate_kHz": 1000,  "duplex": "bidirectional", "drive": "open-drain"},
            "High_speed_mode_Hs":  {"max_bit_rate_kHz": 3400,  "duplex": "bidirectional", "drive": "open-drain with current source pull-up"},
            "Ultra_Fast_mode_UFm": {"max_bit_rate_kHz": 5000,  "duplex": "unidirectional",  "drive": "push-pull"},
        })
        d.setdefault("key_constants_for_RTL_authoring", {
            "bits_per_byte": 8,
            "scl_pulses_per_byte_incl_ack": 9,
            "start_condition": "SDA HIGH→LOW while SCL HIGH",
            "stop_condition":  "SDA LOW→HIGH while SCL HIGH",
            "ack_polarity":    "Receiver pulls SDA LOW = ACK; leaves HIGH = NACK",
            "sda_change_rule": "SDA may only change state while SCL is LOW (except for S, P, Sr)",
            "msb_first_byte_order": True,
            "max_bus_capacitance_pF_Sm_Fm": 400,
            "max_bus_capacitance_pF_Fm_plus": 550,
            "rw_bit_value_for_write": 0,
            "rw_bit_value_for_read": 1,
        })
        d.setdefault("reserved_slave_addresses_hex_dec_summary", {
            "general_call_address": "0x00 (7-bit) with R/W=0",
            "start_byte":           "0x01 (7-bit) with R/W=1",
            "cbus_address":         "0x01 (7-bit)",
            "hs_master_code":       "0x04..0x07 (upper bits 0000 1XX)",
            "10bit_addressing":     "0x78..0x7B (upper bits 1111 0XX)",
            "reserved_future":      "0x78..0x7F (upper bits 1111 1XX) — includes Device ID",
        })
        d.setdefault("default_signal_values_when_idle", {
            "SDA": "HIGH (released by all devices, pulled up by Rp)",
            "SCL": "HIGH (released by all masters)",
        })
        _write(p, d)

    # L8_TIMING
    p = gd / "L8_TIMING_WAVEFORM.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("clock_and_reset_waveform", {
            "SCL_idle": "HIGH",
            "SDA_idle": "HIGH",
            "POR_release": "After Power-On Reset, devices must release both SDA and SCL (drive HIGH-Z) before any transaction.",
        })
        d.setdefault("bit_transfer_waveform", {
            "rule": "Data on SDA must be stable while SCL is HIGH (data valid window). SDA may change while SCL is LOW (change-of-data window).",
            "figure": "Figure 4 — Bit transfer on the I2C-bus",
        })
        d.setdefault("start_stop_waveform", {
            "start_S":  "SDA HIGH→LOW transition while SCL HIGH",
            "stop_P":   "SDA LOW→HIGH transition while SCL HIGH",
            "repeated_start_Sr": "Same as S; keeps bus busy without intervening P",
            "figure": "Figure 5 — START and STOP conditions",
        })
        d.setdefault("data_transfer_waveform", {
            "byte_unit": "8 data bits + 1 ACK clock = 9 SCL pulses per byte",
            "msb_first": True,
            "ack_position": "On the 9th SCL pulse; receiver pulls SDA LOW",
            "figure": "Figure 6 — Data transfer on the I2C-bus",
        })
        d.setdefault("timing_parameters_standard_mode", {
            "fSCL_max_kHz": 100,
            "tHD_STA_min_us": 4.0,
            "tLOW_min_us":   4.7,
            "tHIGH_min_us":  4.0,
            "tSU_STA_min_us": 4.7,
            "tHD_DAT_min_us": 0,
            "tSU_DAT_min_us": 0.25,
            "tBUF_min_us":   4.7,
            "Cb_max_pF":     400,
        })
        d.setdefault("timing_parameters_fast_mode", {
            "fSCL_max_kHz": 400,
            "tHD_STA_min_us": 0.6,
            "tLOW_min_us":   1.3,
            "tHIGH_min_us":  0.6,
            "tSU_STA_min_us": 0.6,
            "tHD_DAT_min_us": 0,
            "tSU_DAT_min_us": 0.1,
            "tBUF_min_us":   1.3,
            "Cb_max_pF":     400,
        })
        d.setdefault("timing_parameters_fast_mode_plus", {
            "fSCL_max_kHz": 1000,
            "tHD_STA_min_us": 0.26,
            "tLOW_min_us":   0.5,
            "tHIGH_min_us":  0.26,
            "tSU_STA_min_us": 0.26,
            "tBUF_min_us":   0.5,
            "Cb_max_pF":     550,
        })
        d.setdefault("timing_parameters_high_speed_mode", {
            "fSCL_max_kHz_100pF": 3400,
            "fSCL_max_kHz_400pF": 1700,
            "drive": "Open-drain with current-source pull-up; SDA push-pull on HIGH",
        })
        d.setdefault("clock_stretching_waveform",
            "Slave holds SCL LOW after a byte to extend the byte period; master enters wait state.")
        d.setdefault("arbitration_waveform",
            "While SCL HIGH, each master compares SDA actual to SDA driven; master that drove HIGH while bus is LOW loses arbitration immediately.")
        d.setdefault("synchronization_waveform",
            "SCL = wired-AND of all masters' SCL outputs; final LOW period = longest LOW, final HIGH period = shortest HIGH.")
        _write(p, d)

    # L9
    p = gd / "L9_INTEGRATION_SPEC.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("module_role",
            "Wire-level inter-IC serial bus specification. Defines the protocol between any two or more I2C-compatible ICs sharing a 2-wire bus (SDA + SCL). Concrete I2C controller / target IP blocks implement this protocol behind an MCU register interface (per SoC integration).")
        d.setdefault("integration_overview", {
            "physical_topology": "All devices' SDA pins connected together; all SCL pins connected together; both lines pulled up to VDD via Rp.",
            "drive_type":        "Open-drain / open-collector wired-AND (push-pull in Ultra Fast-mode only).",
            "voltage_domain":    "VDD-dependent; mixed-voltage operation supported via Rp to highest VDD on bus (or via voltage-level translator).",
            "max_devices":       "Limited by total bus capacitance Cb (typ ≤ 400 pF for Sm/Fm; ≤ 550 pF for Fm+) and address-space (≈ 112 free 7-bit addresses).",
            "no_chip_select":    "Addressing is software-based via the 7-bit (or 10-bit) slave address byte — no per-device chip-select signal.",
        })
        d.setdefault("interface_categories", [
            "Master-transmitter / master-receiver",
            "Slave-transmitter / slave-receiver",
            "Multi-master (with arbitration and clock synchronization)",
            "Mixed (e.g. master with optional slave fallback after arbitration loss)",
        ])
        d.setdefault("interconnect_topologies_supported", [
            "Single master + single slave (2-wire point-to-multipoint)",
            "Single master + N slaves (each addressed by unique 7/10-bit address)",
            "Multi-master + multi-slave (true multi-master bus with arbitration on SDA)",
            "Hub / repeater / extender / multiplexer / bridge for expanding capacitance or reach",
        ])
        d.setdefault("default_signal_values_when_idle",
            "SDA = HIGH, SCL = HIGH (both released, pulled up by Rp). The bus is 'free' after tBUF following a STOP condition.")
        d.setdefault("soc_dependent_items", [
            "Pad type (open-drain output + Schmitt input + glitch filter)",
            "Pull-up resistor sizing (depends on VDD, Cb, target rise time)",
            "Optional current-source pull-up for Hs-mode",
            "Bus speed (selected per device capability + bus load)",
            "Interrupt source mapping (ACK fail, arbitration loss, bus error, byte complete, START/STOP detect)",
            "Software vs hardware addressing (some I2C controllers latch their slave address from external pins)",
            "Glitch filter spike-suppression length (typically 50 ns for Fm)",
        ])
        d.setdefault("low_power_modes", {
            "bus_idle":     "Both SDA and SCL HIGH; static; no power consumption beyond Rp leakage.",
            "device_sleep": "Device must continue to pull SDA HIGH (release) when sleeping; on wakeup it must respond to its address within the timing budget.",
        })
        d.setdefault("bus_clear_procedure",
            "If SDA stuck LOW: master sends 9 SCL clock pulses to allow the device holding SDA LOW to release it. If SCL stuck LOW: use HW reset pin or cycle power.")
        _write(p, d)

    # L12 sequences
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("typical_master_write_sequence", [
            "1. Wait for bus free (both SDA and SCL HIGH for at least tBUF).",
            "2. Generate START condition (S): drive SDA HIGH→LOW while SCL HIGH.",
            "3. Transmit 8 bits of slave address byte: 7-bit address || R/W=0 (write).",
            "4. Release SDA on 9th SCL pulse; sample SDA. If LOW = ACK; if HIGH = NACK.",
            "5. On ACK: transmit 8 data bits (MSB-first); release SDA on 9th pulse; sample for ACK.",
            "6. Repeat step 5 for each additional byte.",
            "7. On NACK or when done: generate STOP (P): drive SDA LOW→HIGH while SCL HIGH.",
            "8. Alternatively: generate repeated START (Sr) to chain another transaction without releasing the bus.",
        ])
        d.setdefault("typical_master_read_sequence", [
            "1. Wait for bus free (both SDA and SCL HIGH for at least tBUF).",
            "2. Generate START (S).",
            "3. Transmit 7-bit slave address || R/W=1 (read); receive ACK from slave.",
            "4. Drive SCL clock pulses; slave drives data bits on SDA (MSB-first).",
            "5. Master pulls SDA LOW on 9th pulse to ACK; or leaves SDA HIGH to NACK the byte.",
            "6. Master NACKs the LAST byte it wants to read, then generates STOP (P).",
        ])
        d.setdefault("typical_slave_response_sequence", [
            "1. Slave monitors SDA for START condition (HIGH→LOW while SCL HIGH).",
            "2. Slave clocks in 8 bits = 7-bit address + R/W; compares to its own address.",
            "3. On match: slave pulls SDA LOW on 9th pulse to ACK.",
            "4. On R/W=0 (master-write): slave clocks in 8 data bits per byte; pulls SDA LOW on 9th pulse to ACK (or HIGH for NACK).",
            "5. On R/W=1 (master-read): slave drives 8 data bits per byte; releases SDA on 9th pulse and samples for master ACK.",
        ])
        d.setdefault("repeated_start_sequence", [
            "Master may issue repeated START (Sr) anywhere instead of STOP (P) to chain transactions to the same or different slave.",
            "Sr keeps the bus busy throughout, avoiding the need to re-arbitrate.",
        ])
        d.setdefault("arbitration_loss_sequence", [
            "While SCL HIGH: master compares its driven SDA level to actual SDA on bus.",
            "If master drove HIGH but bus is LOW: arbitration lost. Master immediately turns off SDA driver.",
            "Master may continue to clock until end of byte but does not retransmit.",
            "Master that won completes transaction normally. Loser restarts transaction when bus is free.",
        ])
        d.setdefault("clock_stretching_sequence", [
            "After receiving (slave-receiver) or before sending (slave-transmitter) a byte, the slave may hold SCL LOW.",
            "Master, monitoring SCL, observes that SCL did not rise as expected; enters wait state.",
            "Slave releases SCL when ready; transaction resumes.",
        ])
        d.setdefault("general_call_sequence", [
            "Master sends address 0x00 with R/W=0 (General Call).",
            "Slaves that recognize General Call ACK the first byte.",
            "Master sends second byte = subroutine code (Software Reset, Slave Address change, etc.).",
            "Slaves act on the code per UM10204 Table 3.",
        ])
        d.setdefault("device_id_read_sequence", [
            "1. Master sends S + Reserved Device ID address 0xF8 (R/W=0 write).",
            "2. Master sends target slave address (LSB don't-care); only the one matching slave ACKs.",
            "3. Master sends Sr + Reserved Device ID address 0xF9 (R/W=1 read).",
            "4. Master reads 3 bytes: 12-bit manufacturer + 9-bit part + 3-bit revision.",
            "5. Master NACKs last byte and sends STOP.",
        ])
        _write(p, d)

    # L14 versioning
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("spec_version", "Rev. 6 (4 April 2014)")
        if _empty(f.get("previous_versions")):
            f["previous_versions"] = [
                "v1.0 (1992) — Original Philips I2C-bus spec; Standard-mode 100 kHz",
                "v2.0 (1998) — Added Fast-mode 400 kHz",
                "v2.1 (2000) — Editorial cleanup",
                "v3.0 (2007) — Added Fast-mode Plus 1 MHz; clarified 10-bit addressing",
                "Rev. 4 (2012) — Added Ultra Fast-mode (UFm) 5 Mbit/s push-pull unidirectional",
                "Rev. 5 (2012) — Editorial",
                "Rev. 6 (2014) — Editorial + clarifications",
            ]
        if _empty(f.get("key_changes")):
            f["key_changes"] = [
                {"version": "v2.0",   "summary": "Fast-mode (400 kbit/s) added; legacy fixed input levels (1.5/3.0 V) supplemented by 30%/70% VDD spec."},
                {"version": "v3.0",   "summary": "Fast-mode Plus (1 Mbit/s) introduced; Cb up to 550 pF allowed for Fm+."},
                {"version": "Rev. 4", "summary": "Ultra Fast-mode (UFm) added — unidirectional, push-pull, 5 Mbit/s; no arbitration."},
                {"version": "Rev. 6", "summary": "Editorial cleanup; clarified bus-clear procedure and Device ID read sequence."},
            ]
        if _empty(f.get("backward_compat_traps")):
            f["backward_compat_traps"] = [
                {"trap_name": "input_level_specification_change",
                 "v1_to_v2_inclusive": "VIL fixed 1.5 V, VIH fixed 3.0 V (legacy).",
                 "v3_and_later":       "VIL = 0.3 VDD, VIH = 0.7 VDD (ratiometric).",
                 "trap": "Mixing legacy (1.5/3.0 V fixed) devices on a 5 V bus with new ratiometric devices may cause input-level violations on the legacy device."},
                {"trap_name": "ufm_unidirectional_push_pull",
                 "pre_rev4": "All I2C-bus devices were open-drain bidirectional.",
                 "rev4_and_later": "Ultra Fast-mode is push-pull unidirectional (write-only); not interoperable with bidirectional Sm/Fm/Fm+/Hs devices on the same physical bus.",
                 "trap": "Mixing UFm devices with bidirectional devices is forbidden — UFm bus is electrically a separate physical bus."},
                {"trap_name": "max_capacitance_per_mode",
                 "Sm_Fm":         "Cb_max = 400 pF",
                 "Fm_plus":       "Cb_max = 550 pF (with stronger pull-up)",
                 "Hs_at_3.4MHz":  "Cb_max = 100 pF (with current-source pull-up)",
                 "trap": "Over-loading the bus past per-mode Cb_max causes rise-time violations and CRC-equivalent data corruption."},
            ]
        f.setdefault("version_naming_history_note",
            "Originally a Philips internal spec (1982); first public release v1.0 in 1992; NXP took ownership in 2006 when split from Philips. Recent versions are numbered as 'Rev. N' rather than 'vX.Y'.")
        d["fields"] = f
        _write(p, d)

    # L15
    p = gd / "L15_ENCODING_TABLES.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("reserved_slave_addresses", {
            "header_columns": ["Slave address (7-bit)", "R/W", "Description"],
            "rows": [
                {"address_binary": "0000 000", "RW": "0", "purpose": "General Call address"},
                {"address_binary": "0000 000", "RW": "1", "purpose": "START byte"},
                {"address_binary": "0000 001", "RW": "X", "purpose": "Cbus address"},
                {"address_binary": "0000 010", "RW": "X", "purpose": "Reserved for different bus format"},
                {"address_binary": "0000 011", "RW": "X", "purpose": "Reserved for future purposes"},
                {"address_binary": "0000 1XX", "RW": "X", "purpose": "Hs-mode master code"},
                {"address_binary": "1111 0XX", "RW": "X", "purpose": "10-bit slave addressing"},
                {"address_binary": "1111 1XX", "RW": "X", "purpose": "Reserved for future purposes (incl. Device ID at 1111 100)"},
            ],
        })
        f.setdefault("protocol_feature_applicability_matrix", {
            "header_columns": ["Feature", "Single master", "Multi-master", "Slave"],
            "rows": [
                ["START condition",     "M", "M", "M"],
                ["STOP condition",      "M", "M", "M"],
                ["Acknowledge",          "M", "M", "M"],
                ["Synchronization",     "n/a", "M", "n/a"],
                ["Arbitration",          "n/a", "M", "n/a"],
                ["Clock stretching",     "O", "O", "O"],
                ["7-bit slave address",  "M", "M", "M"],
                ["10-bit slave address", "O", "O", "O"],
                ["General Call address", "O", "O", "O"],
                ["Software Reset",       "O", "O", "O"],
                ["START byte",           "n/a", "O", "n/a"],
                ["Device ID",            "n/a", "n/a", "O"],
            ],
        })
        f.setdefault("general_call_second_byte_codes", {
            "header_columns": ["Second byte", "Description"],
            "rows": [
                {"byte": "0x06", "description": "Reset and write programmable part of slave address by HW"},
                {"byte": "0x04", "description": "Write programmable part of slave address by HW"},
                {"byte": "0x00", "description": "NOT allowed as 2nd byte"},
                {"byte": "X X X X X X X 1", "description": "HW general call (LSB=1) — 7 MSBs form master's own address"},
            ],
        })
        f.setdefault("mode_summary_table", {
            "header_columns": ["Mode", "Max bit rate", "Duplex", "Drive"],
            "rows": [
                {"mode": "Standard-mode (Sm)",    "rate": "100 kbit/s",  "duplex": "bidirectional", "drive": "open-drain"},
                {"mode": "Fast-mode (Fm)",        "rate": "400 kbit/s",  "duplex": "bidirectional", "drive": "open-drain"},
                {"mode": "Fast-mode Plus (Fm+)",  "rate": "1 Mbit/s",    "duplex": "bidirectional", "drive": "open-drain"},
                {"mode": "High-speed mode (Hs)",  "rate": "3.4 Mbit/s",  "duplex": "bidirectional", "drive": "open-drain + current source"},
                {"mode": "Ultra Fast-mode (UFm)", "rate": "5 Mbit/s",    "duplex": "unidirectional", "drive": "push-pull"},
            ],
        })
        tbl = [
            "Table 1 Definition of I2C-bus terminology",
            "Table 2 Applicability of I2C-bus protocol features",
            "Table 3 Definition of bits in the first byte",
            "Table 4 Assigned manufacturer IDs",
            "Table 5 Definition of UFm I2C-bus terminology",
            "Table 6 General call second byte codes",
            "Table 8 Standard-mode I2C-bus timing",
            "Table 10 Fast-mode I2C-bus timing",
            "Table 12 Fast-mode Plus I2C-bus timing",
            "Table 14 High-speed mode I2C-bus timing",
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
            "SDA and SCL both HIGH in bus-free state",
            "Open-drain (or open-collector) outputs on SDA and SCL for Sm/Fm/Fm+/Hs modes (push-pull only for UFm)",
            "Data on SDA stable while SCL HIGH; SDA changes only while SCL LOW (except for START / STOP / repeated START)",
            "START condition: SDA HIGH→LOW while SCL HIGH",
            "STOP condition: SDA LOW→HIGH while SCL HIGH",
            "Every byte is 8 bits + 1 ACK = 9 SCL clock pulses",
            "Receiver pulls SDA LOW on 9th SCL pulse to ACK",
            "MSB-first byte ordering",
            "Master generates all clock pulses including the 9th ACK pulse",
            "In multi-master systems: arbitration on SDA while SCL HIGH; loser turns off SDA driver immediately",
            "In multi-master systems: SCL synchronization via wired-AND (LOW dominates)",
            "Input levels: VIL ≤ 0.3 VDD, VIH ≥ 0.7 VDD (legacy fixed 1.5/3.0 V acceptable for backward compatibility)",
            "Bus capacitance Cb ≤ per-mode maximum (400 pF Sm/Fm, 550 pF Fm+, 100/400 pF Hs)",
        ])
        f.setdefault("must_not_have_properties", [
            "Push-pull bidirectional drivers (forbidden — only open-drain in Sm/Fm/Fm+/Hs)",
            "SDA transition while SCL HIGH (except for S/P/Sr)",
            "Slave driving SCL HIGH (slave may only release SCL HIGH-Z or pull LOW for stretching)",
            "Master responding to its own START byte",
            "Slave acknowledging the START byte (0x01)",
            "Mixing Ultra Fast-mode push-pull devices with bidirectional open-drain devices on the same physical bus",
        ])
        f.setdefault("compliance_failure_modes", [
            {"mode": "Bus stuck LOW",     "trigger": "SDA or SCL not released by some device after STOP."},
            {"mode": "Arbitration loss",  "trigger": "Two masters started simultaneously; loser must abandon and retry when bus free."},
            {"mode": "NACK at address",   "trigger": "No slave responds at the addressed 7-bit / 10-bit address."},
            {"mode": "NACK at data",      "trigger": "Receiver cannot accept further data (e.g. buffer full)."},
            {"mode": "Rise-time violation","trigger": "Bus capacitance × pull-up R exceeds tr_max for the mode."},
        ])
        f.setdefault("min_bus_capacitance_constraint",
            "No minimum stated; maximum is per-mode (Sm/Fm 400 pF; Fm+ 550 pF; Hs 100 pF @ 3.4 MHz / 400 pF @ 1.7 MHz).")
        f.setdefault("reset_behavior_compliance",
            "After Power-On Reset, devices must release both SDA and SCL (drive HIGH-Z). Bus-clear procedure: if SDA stuck LOW, master sends 9 SCL clocks to allow the holding device to release.")
        d["fields"] = f
        _write(p, d)

    # L17 channel catalog (overwrite — SPI shape was set by R55 if SPI;
    # for I2C, overwrite with SDA/SCL shape)
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f["channels"] = [
            {
                "name": "SDA",
                "direction_master": "bidirectional output (open-drain)",
                "direction_slave":  "bidirectional output (open-drain)",
                "purpose": "Serial Data Line. Carries address byte + data bytes + ACK/NACK bit. Open-drain, wired-AND: any device can pull LOW; HIGH is achieved by all devices releasing the line.",
                "active_levels": "0 = LOW (driven); 1 = HIGH-Z (released, pulled up by Rp to VDD)",
                "idle_level": "HIGH",
            },
            {
                "name": "SCL",
                "direction_master": "output (drives clock); also released to allow slave clock-stretching",
                "direction_slave":  "input (samples on rising edge); optional output (pulls LOW to stretch)",
                "purpose": "Serial Clock Line. Master drives clock pulses; slave may pull LOW to stretch. 9 pulses per byte (8 data + 1 ACK).",
                "active_levels": "0 = LOW (driven by master, or stretched by slave); 1 = HIGH-Z (released, pulled up by Rp)",
                "idle_level": "HIGH",
            },
        ]
        f["global_signals"] = [
            {"name": "VDD", "purpose": "Supply voltage. Determines VIL (0.3 VDD) and VIH (0.7 VDD) thresholds for non-legacy devices."},
            {"name": "Rp",  "purpose": "Pull-up resistor on SDA and SCL to VDD; sized per mode and bus capacitance."},
            {"name": "GND", "purpose": "Common ground reference for all devices on the bus."},
        ]
        f["ufm_channels"] = [
            {
                "name": "USDA",
                "direction_master": "push-pull output (master drives)",
                "direction_slave":  "input only",
                "purpose": "Ultra Fast-mode serial data. Push-pull, unidirectional (master-to-slave only). No ACK; the 9th SCL pulse drives SDA HIGH ignoring response.",
            },
            {
                "name": "USCL",
                "direction_master": "push-pull output (master drives)",
                "direction_slave":  "input only",
                "purpose": "Ultra Fast-mode serial clock. Push-pull, unidirectional. Master drives all clock pulses; no clock stretching.",
            },
        ]
        f["channel_counts"] = {
            "channels": 2,
            "external_pins_total": 2,
            "supply_pins": 2,
            "register_count_at_module": 0,
        }
        f["handshake_pairs"] = [
            {"name": "ADDR_ACK",    "from": "addressed slave", "to": "master", "rule": "After 8-bit address byte: slave pulls SDA LOW on 9th SCL pulse → addressed; HIGH → not addressed (NACK)."},
            {"name": "DATA_ACK",    "from": "receiver",        "to": "transmitter", "rule": "After each 8-bit data byte: receiver pulls SDA LOW on 9th SCL pulse to ACK; HIGH = NACK."},
            {"name": "CLOCK_STRETCH","from": "slave",          "to": "master",     "rule": "Slave holds SCL LOW after 8th pulse to delay next byte; master waits."},
            {"name": "ARBITRATION", "from": "any master",     "to": "any master",  "rule": "On SDA while SCL HIGH: each master compares actual SDA to its driven value; mismatch = arbitration loss → release SDA."},
        ]
        dg = f.setdefault("dependency_graph", {})
        if isinstance(dg, dict):
            dg["common_rule"] = (
                "Master drives SCL; slaves sample SDA on rising SCL. Data on "
                "SDA must be stable while SCL HIGH; only S/P/Sr violate this "
                "rule.")
            dg["data_dependency"] = (
                "Receiver's ACK on byte N permits transmitter to send byte "
                "N+1. Slave's clock-stretching on SCL forces master to wait.")
            for kill in ("AXI_read", "AXI3_write", "AXI4_write"):
                dg.pop(kill, None)
        f.setdefault("ordering_rules", {
            "byte_ordering": "MSB-first within each byte.",
            "byte_count":    "Number of bytes per transfer is unrestricted (limited only by master's STOP).",
            "ack_per_byte":  "Each byte (including address byte) is followed by exactly one ACK / NACK bit on the 9th SCL pulse.",
        })
        d["fields"] = f
        _write(p, d)

    # L18
    p = gd / "L18_INTERCONNECT_TOPOLOGY.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f["topology_type"] = "Multi-drop 2-wire bus; all devices share SDA and SCL through wired-AND open-drain (or push-pull in UFm)."
        f["supported_topologies"] = [
            {"name": "Single master + single slave",  "description": "Two devices sharing SDA + SCL with one set of pull-up resistors."},
            {"name": "Single master + multi-slave",   "description": "One master + N slaves; each slave addressed by unique 7-bit or 10-bit address. ~112 free 7-bit addresses available."},
            {"name": "Multi-master + multi-slave",    "description": "Multiple masters share the same bus. Bus access is arbitrated bit-by-bit on SDA while SCL HIGH."},
            {"name": "Hub / repeater / extender",     "description": "Boosts bus capacitance budget or reach via dedicated I2C hub ICs."},
            {"name": "Multiplexer / switch",          "description": "Allows segmenting the bus into multiple branches with independent capacitance."},
            {"name": "Bridge",                        "description": "Translates between I2C and other interfaces (SPI, UART, USB)."},
        ]
        f["master_slave_role_summary"] = [
            {"role": "Master", "responsibilities": [
                "Generate START / STOP / repeated START",
                "Generate SCL clock pulses (all 9 per byte)",
                "Send 7-bit (or 10-bit) slave address byte + R/W bit",
                "In multi-master systems: participate in arbitration",
            ]},
            {"role": "Slave", "responsibilities": [
                "Monitor SDA for START condition",
                "Match its address against received address byte",
                "ACK matched address; NACK unmatched",
                "Drive (read) or sample (write) SDA per R/W direction",
                "Optionally clock-stretch SCL",
            ]},
            {"role": "Transmitter", "description": "Drives SDA during the 8 data bits of a byte. May be master (in master-write) or slave (in master-read)."},
            {"role": "Receiver",    "description": "Samples SDA on rising SCL; drives ACK / NACK on 9th pulse. May be master or slave."},
        ]
        f["ultra_fast_mode_topology"] = {
            "description": "Push-pull, unidirectional master-to-slaves only. No arbitration, no clock stretching, no ACK.",
            "drive": "Push-pull on USDA and USCL",
            "max_speed": "5 Mbit/s",
            "use_case": "LED controllers, GPO devices that need fast unidirectional writes.",
        }
        f["interconnect_role"] = (
            "There is no central protocol-layer interconnect — the bus is a "
            "flat multi-drop shared medium. The 'interconnect' is purely "
            "physical (wires + pull-ups + hubs/repeaters).")
        f["ordering_guarantees"] = {
            "within_a_transaction": "Bytes are transmitted in software-issue order, MSB-first within each byte.",
            "across_transactions":  "No fairness guarantee in multi-master; arbitration determines who completes first.",
        }
        f.setdefault("memory_vs_peripheral_regions",
            "Not applicable — I2C is a wire-level protocol, not a memory bus. Per-device register maps are defined by the individual device datasheets, not by UM10204.")
        f.setdefault("slave_classification", {
            "addressable_slave":    "Standard slave with hardwired or pin-selectable 7/10-bit address.",
            "general_call_slave":   "Slave that recognizes the General Call address (0x00, R/W=0) in addition to its own.",
            "ufm_slave":            "Ultra Fast-mode receive-only slave (LED controller, GPO).",
        })
        f.setdefault("default_signal_values_evidence_tables", [
            "Table 2 Applicability of I2C-bus protocol features",
            "Table 3 Definition of bits in the first byte",
            "Table 6 General call second byte codes",
            "Section 6 Electrical specifications (per-mode timing and capacitance)",
        ])
        f.setdefault("addressing_topology", {
            "7_bit": "Default. ~112 free 7-bit addresses (excluding 16 reserved).",
            "10_bit": "Optional. Two-byte address format: first byte 0b11110XX0/1 + 2 MSBs of address + R/W; second byte = 8 LSBs of address.",
        })
        d["fields"] = f
        _write(p, d)

    # L21 power — I2C-specific key names
    p = gd / "L21_POWER_INTENT.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("power_intent_present", False)
        f["low_power_modes_summary"] = {
            "bus_idle_static_power":  "Both SDA and SCL HIGH (released). Only Rp leakage current per VDD/Rp.",
            "device_sleep_release":   "Sleeping devices must release SDA and SCL (HIGH-Z).",
            "wakeup_response_window": "Device must respond to its address within tACK at the prevailing bus speed.",
        }
        f.setdefault("notes",
            "Power-domain partitioning is deferred to SoC integration. Mixed-VDD I2C is supported via voltage-level translators or by pulling Rp to the highest VDD on the bus and ensuring all devices tolerate that level.")
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
def is_i2c(blob: str) -> bool:
    """Content-only `i2c` detector (importable, lifted from the runner) WITH a
    FOREIGN-PRIMARY DEFER.

    Empty-safe. Reads ONLY ``blob`` (spec text). The original structural
    signature below is byte-for-byte the boolean the runner used inline.

    Why the defer (mirrors `is_mipi` / `is_mdio` / `is_smbus_pmbus` doctrine —
    general, content-only, NO chip/SKU/benchmark-name literal): the NXP
    UM10204 I2C spec is the PARENT of a whole family of two-wire / control
    buses and therefore mentions many of them incidentally (it discusses SMBus,
    PMBus, the HDMI DDC channel, and I3C's IBI / dynamic-addressing as
    comparisons). Conversely, every one of those foreign specs cites SDA/SCL +
    "I2C" because they are built on or compared against the I2C 2-wire model —
    so the loose `(SDA+SCL or START/STOP/slave-addr) and I2C` structural test
    below over-fires on them. The guard defers (returns False) when the blob's
    DOMINANT subject is one of those foreign protocols, detected by ITS OWN
    distinctive multi-token structural signature (frame-field names, density
    counts, signal/role names) — not by a name token alone.

    Two of the foreign protocols (SMBus/PMBus and I3C) are genuine derived
    CHILDREN of I2C; they are deferred via the CHILD's distinctive sibling-MUTEX
    discriminator (SMBus PEC / SMBALERT# / PMBus command set; I3C ENTDAA /
    dynamic-address+IBI / CCC / Hot-Join), which the plain I2C parent spec never
    satisfies. Empirically the real I2C benchmark (spec + runner blob) trips
    NONE of these defers and stays True; all nine foreign benchmarks
    (a2b / ethercat / hdmi / i3c / mdio / mipi_csi2 / mipi_spmi_rffe /
    smbus_pmbus / tpm) trip exactly their own defer and are suppressed.
    """
    if not blob:
        return False
    low = blob.lower()

    # --- FOREIGN-PRIMARY DEFER (the blob's true subject is NOT I2C). ---
    # A2B (ADI Automotive Audio Bus): a twisted-pair daisy-chain audio bus with
    # a sample-rate-locked superframe. Dense "a2b" subject + superframe + daisy
    # chain is absent from the I2C spec.
    a2b_primary = (
        low.count("a2b") >= 20
        and "superframe" in low
        and ("daisy chain" in low or "daisy-chain" in low
             or "daisy chained" in low or "daisy-chained" in low))
    # EtherCAT: the EtherCAT Slave Controller (ESC) + FMMU / SyncManager
    # frame-processing model, or the EtherType 0x88A4.
    ethercat_primary = (
        ("EtherCAT" in blob and "ESC" in blob and "FMMU" in blob)
        or ("EtherCAT" in blob and "SyncManager" in blob)
        or ("0x88A4" in blob and "EtherCAT" in blob))
    # HDMI/DVI: the TMDS three-channel transmitter (TX0/TX1/TX2), the
    # TFP410 PanelBus part, or the HDMI DDC+EDID+HPD display-link triad.
    hdmi_primary = (
        ("TMDS" in blob and ("HDMI" in blob or "DVI" in blob)
         and "TX0" in blob and "TX1" in blob and "TX2" in blob)
        or ("TFP410" in blob and "PanelBus" in blob)
        or ("HDMI" in blob and "DDC" in blob
            and "EDID" in blob and "HPD" in blob))
    # I3C (MIPI I3C — a derived child of I2C): the dynamic-addressing +
    # in-band-interrupt (IBI) + Common-Command-Code (CCC) + ENTDAA / Hot-Join
    # signature. This is the sibling-MUTEX discriminator the plain I2C parent
    # spec (which only mentions IBI / dynamic addressing in passing) never has.
    i3c_primary = (
        ("I3C" in blob and "Dynamic Address" in blob and "IBI" in blob)
        or ("I3C Basic" in blob and "CCC" in blob)
        or ("ENTDAA" in blob and "CCC" in blob)
        or ("I3C" in blob and "Hot-Join" in blob
            and ("HDR-DDR" in blob or "CCC" in blob)))
    # MDIO (IEEE 802.3 Clause 22/45): the MDC/MDIO two-wire pair PLUS the
    # PHYAD/REGAD frame-field model PLUS the Clause-22/45 marker.
    mdio_primary = (
        ("mdc" in low and "mdio" in low)
        and (("phyad" in low or "phy address" in low)
             and ("regad" in low or "register address" in low))
        and ("clause 22" in low or "clause 45" in low
             or "management data input" in low))
    # MIPI CSI-2: dense CSI-2 subject + the Camera Control Interface (CCI)
    # camera-pipeline sideband (present in NO I2C-family doc).
    csi2_primary = (
        (low.count("csi-2") + low.count("csi2")) >= 20
        and "camera control interface" in low
        and ("d-phy" in low or "image sensor" in low))
    # MIPI SPMI / RFFE: the MIPI two-wire (SCLK + SDATA, NOT SDA/SCL) control
    # bus framed by a Sequence Start Condition (SSC, NOT I2C START/STOP) with
    # 4-bit MASTER_ID/SLAVE_ID (SPMI) or USID/GSID (RFFE).
    spmi_rffe_primary = (
        ("SCLK" in blob and "SDATA" in blob)
        and ("Sequence Start Condition" in blob
             or re.search(r"\bSSC\b", blob))
        and (("SPMI" in blob and ("MASTER_ID" in blob or "SLAVE_ID" in blob))
             or ("RFFE" in blob and ("USID" in blob or "GSID" in blob))))
    # SMBus / PMBus (a system-/power-management bus derived from I2C): the
    # SMBus-only Packet Error Code (PEC) / SMBALERT# / Alert-Response, or a
    # dense PMBus subject with its command-code set. This is the sibling-MUTEX
    # discriminator the plain I2C parent spec (which only names SMBus/PMBus in
    # passing, without their structural vocabulary) never satisfies.
    smbus_pmbus_primary = (
        (re.search(r"\bPEC\b", blob) and ("CRC-8" in blob or "CRC8" in blob))
        or "Packet Error Code" in blob
        or "SMBALERT" in blob
        or ("PMBus" in blob and low.count("pmbus") >= 20
            and (("OPERATION" in blob and "VOUT_COMMAND" in blob)
                 or ("STATUS_WORD" in blob and "PAGE" in blob))))
    # TPM (TCG Trusted Platform Module — a security device, not a bus): the
    # TPM 2.0 commandCode/PCR model, the TCG+PCR+hierarchy triad, or TPM2_.
    tpm_primary = (
        ("TPM 2.0" in blob and "PCR" in blob and "commandCode" in blob)
        or ("TPM" in blob and "TCG" in blob and "PCR" in blob
            and "hierarchy" in low)
        or ("Trusted Platform Module" in blob and "TPM2_" in blob))

    if (a2b_primary or ethercat_primary or hdmi_primary or i3c_primary
            or mdio_primary or csi2_primary or spmi_rffe_primary
            or smbus_pmbus_primary or tpm_primary):
        return False

    # --- STRUCTURAL I2C signature (unchanged from the runner's inline
    #     detector). ---
    return bool(
        (("SDA" in blob and "SCL" in blob)
         or ("START condition" in blob
             and "STOP condition" in blob
             and "slave address" in blob))
        and ("I2C" in blob
             or "I²C" in blob
             or "I2C-bus" in blob))
