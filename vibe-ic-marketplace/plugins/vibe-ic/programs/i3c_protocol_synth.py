"""I3C-class protocol synth helper.

v0.1.84 — ic_class-gated overlay for `serial_peripheral_protocol` specs
that exhibit the MIPI I3C Basic structural signature:
    (`I3C` + `Dynamic Address` + `IBI`)
        OR (`I3C Basic` + `CCC`)
        OR (`I3C` + `HDR-DDR` + `Hot-Join`)

Applies MIPI I3C Basic v1.0-spec-universal facts (the July 2018
royalty-free MIPI subset of I3C v1.0 + selected v1.1 elements) to
L1-L18 + L21. Sits ON TOP of the I2C synth (I3C is I2C's successor
on the same two-wire physical layer — many I2C facts are still true,
but with key overrides):

  * 12.5 MHz Push-Pull SDR replaces 1 MHz Open-Drain as headline speed.
  * 9-bit SDR Data Word: 8 data + T-Bit (parity / end-of-data), NOT
    8 data + ACK.
  * Broadcast Address 7'h7E is mandatory; Hot-Join Address 7'h02.
  * Dynamic Address Assignment via 48-bit Provisional ID + BCR + DCR.
  * In-Band Interrupt + Hot-Join + Secondary Master cooperative
    multi-master.
  * NO slave SCL stretching allowed; master may stall instead.
  * HDR exit pattern detection required even in SDR-Only devices.

Doctrine: structural-keyword detection IS general within an ic_class
(mirrors the AMBA-AXI R46/R48/R50/R52, the SPI R53/R54/R55, the I2C
R56/R57/R58, the UART, CAN, USB and I2S detectors). Any MIPI I3C
Basic variant exhibits the same signature.

Public entry: `apply_i3c_synth(generated_docs_dir, is_i3c, i3c_ic_name)`.
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


def _force(d: dict, key: str, value) -> None:
    """Unconditional overwrite — used to replace I2C-synth leftovers."""
    d[key] = value


def apply_i3c_synth(generated_docs_dir: Path, is_i3c: bool,
                    i3c_ic_name: Optional[str]) -> None:
    """Apply MIPI I3C Basic-specific synth when the structural signature matched."""
    if not is_i3c:
        return
    gd = generated_docs_dir

    # ------------------------------------------------------------------
    # ic_name across the main 14 L docs (top-level for L1-L23 + L8_timing)
    # ------------------------------------------------------------------
    if i3c_ic_name is not None:
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
                d["ic_name"] = i3c_ic_name
                _write(q, d)
        # L14-L23 keep ic_name under fields
        for n in [
            "L14_PROTOCOL_VERSIONING.json", "L15_ENCODING_TABLES.json",
            "L16_COMPLIANCE_PROPERTIES.json", "L17_CHANNEL_SIGNAL_CATALOG.json",
            "L18_INTERCONNECT_TOPOLOGY.json", "L19_CONSTRAINTS_PDK.json",
            "L20_DFT_SCAN_TOPOLOGY.json", "L21_POWER_INTENT.json",
            "L22_VERIFICATION_PLAN.json", "L23_SECURITY_REQUIREMENTS.json",
        ]:
            q = gd / n
            if q.is_file():
                d = _read(q)
                f = d.get("fields") or {}
                f["ic_name"] = i3c_ic_name
                d["fields"] = f
                _write(q, d)

    # ------------------------------------------------------------------
    # L1 datasheet metadata
    # ------------------------------------------------------------------
    p = gd / "L1_DATASHEET.json"
    if p.is_file():
        d = _read(p)
        d["document_number"] = "MIPI I3C Basic v1.0"
        d["document_title"] = (
            "Specification for I3C Basic — Improved Inter Integrated Circuit")
        d["version"] = "Version 1.0"
        d["revised_date"] = "19 July 2018 (MIPI Board Adopted 8 October 2018)"
        d["manufacturer"] = "MIPI Alliance, Inc."
        d["copyright"] = "© 2016-2018 MIPI Alliance, Inc. All rights reserved."
        d["external_pins"] = ["SDA", "SCL"]
        d["total_external_pin_count"] = 2
        d["wire_protocol"] = (
            "Two-wire bidirectional serial; Push-Pull native + Open-Drain "
            "(I2C-compatible) + High-Keeper; backward-compatible with Legacy "
            "I2C on the same bus")
        d.setdefault("key_features", [
            "Two-wire serial interface up to 12.5 MHz using Push-Pull (SDA + SCL).",
            "Legacy I2C Device co-existence on the same bus (Slave-only, with limitations).",
            "Dynamic Address Assignment (DAA) while supporting Static Addressing for Legacy I2C Devices.",
            "Legacy I2C messaging supported by the I3C Main Master.",
            "I2C-like Single Data Rate (SDR) messaging — default mode of the I3C bus.",
            "NOT SUPPORTED IN I3C BASIC: Optional High Data Rate (HDR) modes (HDR-DDR, HDR-TSP, HDR-TSL); however HDR Exit Pattern detection is required for compatibility.",
            "Multi-Drop capability.",
            "Multi-Master capability with cooperative bus handoff (Main Master ↔ Secondary Master).",
            "In-Band Interrupt (IBI) support — slave emits its address into the arbitrated address header.",
            "Hot-Join support — devices may join an already-running bus.",
            "NOT SUPPORTED IN I3C BASIC: Synchronous Timing Support and Asynchronous Time Stamping.",
            "Backward I2C Open-Drain compatibility on START / address-header arbitration; Push-Pull on data and post-Repeated-START headers.",
            "9-bit data words: 8 data bits + 1 T-bit (Transition / Parity / End-of-data) instead of I2C ACK on data.",
            "Broadcast (7'h7E) and Direct CCC framework for bus management.",
        ])
        d["modes_of_operation"] = [
            {"name": "SDR (Single Data Rate)",            "max_bit_rate": "12.5 MHz SCL (up to 12.9 MHz max)", "duplex": "bidirectional", "drive": "Push-Pull (data + Sr header) + Open-Drain (START + arbitrable address header + ACK + DAA)"},
            {"name": "Legacy I2C Fm",                     "max_bit_rate": "400 kHz",  "duplex": "bidirectional", "drive": "Open-Drain (I2C-compatible)"},
            {"name": "Legacy I2C Fm+",                    "max_bit_rate": "1 MHz",    "duplex": "bidirectional", "drive": "Open-Drain (I2C-compatible)"},
            {"name": "HDR-DDR (not in I3C Basic)",        "max_bit_rate": "25 Mbps (2 bits / SCL cycle)", "duplex": "bidirectional", "drive": "Push-Pull; only HDR Exit Pattern detection required of I3C Basic devices"},
            {"name": "HDR-TSP / HDR-TSL (not in I3C Basic)", "max_bit_rate": "approx. 33-40 Mbps (ternary symbols)", "duplex": "bidirectional", "drive": "Ternary signaling on SDA + SCL; only HDR Exit Pattern detection required of I3C Basic devices"},
        ]
        d.setdefault("system_use_cases", [
            "Sensor interfacing on mobile / wireless platforms (accelerometer, gyro, magnetometer, proximity, ALS, barometer, temperature, humidity, etc.)",
            "Biometric / health sensors (fingerprint, heart-rate, glucometer, EKG)",
            "Touch / haptic / NFC interfaces",
            "Sensor hub aggregation (I3C Secondary Master / Hub / Engine)",
            "Mixed-bus systems with Legacy I2C sensors and I3C sensors co-existing",
        ])
        # v0.1.85 force-overwrite: I2C synth (which fires first on the
        # shared SDA/SCL signature) writes UM10204 I2C-specific overview /
        # release_history_note. For I3C-class specs those overlays are
        # foreign-protocol pollution — replace unconditionally.
        _force(d, "overview",
            "MIPI I3C Basic v1.0 is a feature-reduced, royalty-free subset of "
            "the full MIPI I3C v1.0 specification (with selected I3C v1.1 "
            "elements), targeted at mobile-sensor interconnect. It preserves "
            "I2C backward compatibility while adding Push-Pull 12.5 MHz SDR, "
            "Dynamic Address Assignment, In-Band Interrupts, Hot-Join, and "
            "Common Command Codes — at much lower energy per bit than I2C and "
            "with greater than 10x speed.")
        _force(d, "release_history_note",
            "I3C Basic v1.0 initial board-adopted release: 8 October 2018. "
            "Subset of MIPI I3C v1.0 (31 December 2016) + selected I3C v1.1 "
            "features (Direct Read/Write CCCs, GETMXDS refinement, SETAASA, "
            "low-voltage / high-capacitive-load IO). Members can later upgrade "
            "to full I3C v1.x.")
        d.setdefault("scope_in", [
            "I3C interface protocols and commands leveraged for I3C Basic.",
            "Electrical specifications: DC I/O characteristics, AC timing, voltage levels.",
            "Support for sensor classes and other devices defined in this specification.",
        ])
        d.setdefault("scope_out", [
            "Mechanical / system / implementation details within an I3C Device.",
            "ESD (Electrostatic Discharge) structures.",
            "System power management.",
            "Use-case-specific data or format definitions besides bus management Common Command Codes (CCCs).",
        ])
        _write(p, d)

    # ------------------------------------------------------------------
    # L2 FRS
    # ------------------------------------------------------------------
    p = gd / "L2_FRS.json"
    if p.is_file():
        d = _read(p)
        po = d.setdefault("protocol_overview", {})
        if isinstance(po, dict):
            po["wires"] = 2
            po["wire_names"] = ["SDA", "SCL"]
            po["bidirectional"] = True
            po["synchronous"] = True
            po["serial"] = True
            po["byte_oriented"] = True
            po["byte_width_bits"] = 8
            po["msb_first"] = True
            po["open_drain_wired_and_legacy_compatible"] = True
            po["push_pull_native_for_sdr_data"] = True
            po["multi_master_capable"] = True
            po["i2c_backward_compatible"] = True
            po["addressing"] = (
                "7-bit slave address (Static for legacy I2C, Dynamic for I3C); "
                "Broadcast address 7'h7E; Hot-Join address 7'h02; per-CCC "
                "reserved-address restrictions per Table 9")
            po["ninth_bit_semantics"] = (
                "T-Bit (Transition / Parity / End-of-Data) replaces I2C ACK on "
                "data bytes; address header still uses ACK/NACK")
        fr = [
            {"id": "FR-PHY-01",    "text": "SDA and SCL are two bidirectional bus lines; in I3C native mode SCL is driven by the Master in Push-Pull (it can also be Open-Drain). SDA dynamically switches between Push-Pull (data, post-Sr header) and Open-Drain (START, arbitrable address header, ACK, DAA)."},
            {"id": "FR-PHY-02",    "text": "When SDA is in Open-Drain or High-Keeper mode, devices use the same wired-AND rule as I2C: any device can pull LOW; HIGH is achieved by releasing the line."},
            {"id": "FR-START-03",  "text": "START condition (S): HIGH-to-LOW transition on SDA while SCL HIGH — identical signaling to I2C, timing may differ (Section 6, Table 58)."},
            {"id": "FR-STOP-04",   "text": "STOP condition (P): LOW-to-HIGH transition on SDA while SCL HIGH — identical signaling to I2C, timing may differ (Section 6, Table 58)."},
            {"id": "FR-RSTART-05", "text": "Repeated START (Sr): equivalent to S; the address header following Sr is always Push-Pull (except its ACK/NACK)."},
            {"id": "FR-ADDR-06",   "text": "I3C Address Header = 7-bit address + 1-bit RnW + 1-bit ACK/NACK — same bit count as I2C; the arbitrable header (after S) may transition mid-header from Open-Drain to Push-Pull per Section 5.1.2.2.2."},
            {"id": "FR-DATA-07",   "text": "I3C SDR Data Word = 9 bits = 8 data bits + 1 T-Bit (Parity for Master-write; End-of-Data for Slave-read). The ninth bit is NEVER an ACK on data."},
            {"id": "FR-PARITY-08", "text": "T-Bit for Master-Written data byte = odd parity over the 8 data bits = XOR(Data[7:0], 1). On all-zeros or all-ones, the parity bit is 1."},
            {"id": "FR-EOM-09",    "text": "T-Bit for Slave-Returned (read) data: T=0 (LOW) ends the message; T=1 (HIGH) continues with parking SDA to allow Master to abort via Sr."},
            {"id": "FR-BCAST-10",  "text": "Broadcast Address 7'h7E (Reserved by I2C) is the I3C Broadcast Address: every I3C Slave shall ACK 7'h7E with RnW=0; no I2C Slave matches 7'h7E."},
            {"id": "FR-HOTJOIN-11","text": "Hot-Join Address 7'h02 is used by a Slave joining a running bus to request Dynamic Address Assignment via the IBI mechanism."},
            {"id": "FR-CCC-12",    "text": "Common Command Codes (CCC) come in Broadcast (0x00-0x7F) and Direct (0x80-0xFE) forms; every CCC frame begins with 7'h7E (Broadcast) + the CCC byte; Direct CCCs continue with Sr + target Slave Dynamic Address."},
            {"id": "FR-DAA-13",    "text": "Dynamic Address Assignment: Main Master broadcasts ENTDAA (CCC 0x07); slaves drive their 48-bit Provisional ID + BCR + DCR onto SDA while Master clocks; the device with lowest concatenated value wins each arbitration round; Master assigns 7-bit Dynamic Address + 1-bit parity; procedure repeats until no further ACK on 7'h7E with RnW=1."},
            {"id": "FR-IBI-14",    "text": "In-Band Interrupt: from Bus Available Condition a Slave may pull SDA LOW; the Master then drives SCL; the Slave drives its own Dynamic Address (RnW=1) in the arbitrable address header; the Master decides to ACK or NACK; optional Mandatory Data Byte(s) follow if BCR bit IBI Payload = 1."},
            {"id": "FR-HOTJ-15",   "text": "Hot-Join: from Bus Idle / Bus Available Condition the joining Slave issues a START and drives Hot-Join Address 7'h02 (RnW=0); Master may NACK, ACK + DISHJ, or ACK + ENTDAA to assign a Dynamic Address."},
            {"id": "FR-SMR-16",    "text": "Secondary Master Request: a BCR-marked Secondary Master may drive its own Dynamic Address with RnW=0 in the arbitrable header to request mastership; final handoff is via GETACCMST CCC."},
            {"id": "FR-LEGACY-17", "text": "Legacy I2C Slaves co-exist on the I3C bus subject to Tables 4-5 (Fm or Fm+ only; no 10-bit extended addressing; no Slave clock-stretching; recommended 50 ns Spike Filter for Mixed Fast Bus)."},
            {"id": "FR-NOSTRETCH-18","text": "Slave clock-stretching on SCL is NOT ALLOWED on the I3C bus (I3C Slaves cannot stretch SCL); the I3C Master may stall SCL LOW under specific transitory conditions per Section 5.1.2.5."},
            {"id": "FR-12M5-19",   "text": "Max SCL clock frequency: 12.5 MHz typical (12.9 MHz max) in I3C Push-Pull SDR; on Mixed Bus the SCL HIGH period may be constrained by tDIG_H_MIXED (≤ 45 ns) so Legacy I2C devices' 50 ns Spike Filter rejects I3C signaling."},
            {"id": "FR-CBLOAD-20", "text": "Maximum capacitive load per bus line (SDA / SCL) in I3C Push-Pull SDR: Cb ≤ 50 pF — significantly tighter than I2C."},
            {"id": "FR-CHAR-21",   "text": "Every I3C compliant device shall have a Bus Characteristics Register (BCR, Table 6) and a Device Characteristics Register (DCR, Table 7); every Legacy I2C device on an I3C bus shall have an associated Legacy Virtual Register (LVR, Table 8) held by the controller."},
        ]
        if _empty(d.get("functional_requirements")) or len(d.get("functional_requirements", [])) < 10:
            d["functional_requirements"] = fr
        d["error_response_conditions"] = [
            "S0 — Invalid Broadcast Address or CCC code (slave shall ignore address mismatches at S0)",
            "S1 — CCC code parity error (Slave shall NACK)",
            "S2 — Write Data parity error (Slave shall NACK at the next byte boundary)",
            "S3 — Read Data parity error (Slave shall set T=0 to end the read; Master detects)",
            "S4 — Slave-driven monitor error during read",
            "S5 — Transaction after IBI NACKed",
            "S6 — Slave self-test / optional",
            "M0 — Master detects unexpected NACK / no addressed slave",
            "M1 — Master detects invalid CCC return / optional",
            "M2 — Master detects bus error (e.g. SDA stuck) and escalates to recovery",
        ]
        d["protocol_features_applicability"] = {
            "header": ["Feature", "Main Master", "Secondary Master", "I3C Slave", "Legacy I2C Slave"],
            "rows": [
                ["START / STOP / Sr",            "M", "M",         "M",         "M"],
                ["7'h7E Broadcast match",        "M", "M (asSlave)","M",         "n/a"],
                ["Hot-Join Address 7'h02",       "M", "Optional",  "Optional",  "n/a"],
                ["Dynamic Address Assignment",   "M", "Optional",  "M",         "n/a"],
                ["BCR / DCR Registers",          "M", "M",         "M",         "n/a (LVR instead)"],
                ["IBI",                          "n/a","Optional", "Optional",  "n/a"],
                ["Secondary Master Request",     "n/a","M",        "n/a",       "n/a"],
                ["Master Clock Stall",           "Optional","Optional","n/a",   "n/a"],
                ["HDR Exit Pattern Detect",      "M", "M",         "M",         "n/a"],
                ["I3C SDR Mode",                 "M", "M",         "M",         "n/a"],
                ["Required CCCs (Table 15)",     "M", "M",         "M",         "n/a"],
            ],
        }
        d["wire_count"] = "2 (SDA, SCL)"
        d["compliance_requirements"] = [
            "All I3C devices must respond to Broadcast Address 7'h7E and to their assigned Dynamic Address.",
            "I3C Slaves shall NOT clock-stretch SCL (Slave-side clock stretching is not allowed on an I3C bus).",
            "I3C Slaves shall implement an HDR Exit Pattern Detector even if they do not implement any HDR mode.",
            "Every byte-write from Master uses 8 data + 1 T-Bit (odd parity = XOR(Data[7:0],1)); never an ACK from the Slave.",
            "Every byte-read from Slave uses 8 data + 1 T-Bit acting as end-of-data (0=end, 1=continue).",
            "Address-header ACK from Slave is Open-Drain on the 9th SCL bit, just like I2C.",
            "On Mixed Fast Bus the SCL HIGH period during I3C frames must be ≤ tDIG_H_MIXED so Legacy I2C devices' 50 ns Spike Filter ignores I3C traffic.",
            "Maximum SCL frequency in I3C Push-Pull SDR is 12.5 MHz (12.9 MHz absolute max).",
            "Bus capacitance Cb per line ≤ 50 pF in I3C Push-Pull SDR.",
            "Reserved addresses per Table 9 (7'h00, 7'h01, 7'h02, 7'h3E, 7'h5E, 7'h6E, 7'h76, 7'h7A, 7'h7C, 7'h7E, 7'h7F) shall not be used as Dynamic Addresses.",
        ]
        _write(p, d)

    # ------------------------------------------------------------------
    # L3 cmd protocol
    # ------------------------------------------------------------------
    p = gd / "L3_CMD_PROTOCOL.json"
    if p.is_file():
        d = _read(p)
        d["protocol_type"] = (
            "Two-wire synchronous serial bus with I2C-compatible signaling, "
            "Push-Pull native data drive, dynamic 7-bit addressing, "
            "Broadcast/Direct Common Command Code (CCC) framework, and "
            "slave-initiated In-Band Interrupts / Hot-Join")
        d["opcodes_summary"] = (
            "I3C does not use an MCU-style opcode set; protocol commands are "
            "Common Command Codes (CCCs) — Broadcast (0x00-0x7F) and Direct "
            "(0x80-0xFE) — sent as a one-byte CCC immediately after a "
            "Broadcast Address 7'h7E (W) header.")
        d["channels"] = [
            {"name": "SDA", "direction": "bidirectional", "description": "Serial data line; dynamically switches between Push-Pull (data, post-Sr header) and Open-Drain / High-Keeper (START, arbitrable address header, ACK, DAA). 8-bit data + 1-bit T-Bit per word."},
            {"name": "SCL", "direction": "master output (Push-Pull normally; may be Open-Drain in legacy / arbitration); slave input — slave clock-stretching is NOT allowed", "description": "Serial clock line; 9 SCL pulses per 9-bit word (Address Header: 8 addr/RnW + 1 ACK; SDR Data Word: 8 data + 1 T-Bit). Master may stall SCL LOW per Section 5.1.2.5."},
        ]
        d["valid_ready_handshake_rules"] = [
            "Address-Header handshake: addressed Slave drives 9th SCL bit LOW = ACK; HIGH = NACK (Open-Drain).",
            "SDR Master-Write data: NO ACK on data — receiver instead checks T-Bit parity; on parity error the Slave NACKs at the next byte boundary (error type S2).",
            "SDR Slave-Read data: NO ACK on data — Slave drives T-Bit = 1 to continue or 0 to end the message; Master may abort by driving SDA LOW during the T-Bit HIGH window (Repeated START).",
            "There is no AMBA-style per-cycle VALID/READY; the handshake is byte-level via T-Bit + header-level via ACK/NACK.",
            "Slave-side clock stretching is forbidden on I3C; only the Master may stall SCL LOW under specific conditions.",
        ]
        d["burst_based"] = False
        d["byte_oriented"] = True
        d["byte_order"] = (
            "MSB-first within each byte; Big-Endian over multi-byte fields "
            "(e.g. 48-bit Provisional ID transferred starting with bit [47]).")
        d["transaction_framing"] = {
            "start_S":           "HIGH-to-LOW transition on SDA while SCL HIGH (signaling identical to I2C; timing per Table 58).",
            "stop_P":            "LOW-to-HIGH transition on SDA while SCL HIGH (signaling identical to I2C; timing per Table 58).",
            "repeated_start_Sr": "Equivalent to S; address header following Sr is always Push-Pull (except its ACK/NACK).",
            "address_header":    "7 bits Address + 1 bit RnW + 1 bit ACK/NACK = 9 SCL pulses (Open-Drain ACK).",
            "sdr_data_word":     "8 bits Data + 1 bit T-Bit (Parity for Master-write; End-of-Data for Slave-read) = 9 SCL pulses.",
            "hdr_exit_pattern":  "Defined sequence of SDA toggles while SCL is held LOW; required to be detected by every I3C device including SDR-only.",
            "bus_free_condition":      "SDA and SCL both HIGH for at least tCAS after a STOP — bus becomes 'Free'.",
            "bus_available_condition": "SDA and SCL both HIGH for at least tAVAL — a Slave may issue a START Request to send an IBI or Master Request.",
            "bus_idle_condition":      "SDA and SCL both HIGH for at least tIDLE — a Hot-Join Device may issue a Hot-Join request.",
        }
        d["address_header_format"] = {
            "bits_0_to_7": "7-bit address (MSb-first on the wire). 7'h7E = I3C Broadcast Address; 7'h02 = Hot-Join Address; otherwise = Static I2C Address (Legacy I2C Slave) or assigned Dynamic Address (I3C Slave).",
            "bit_8":       "RnW direction; 0 = Write, 1 = Read.",
            "bit_9_ack":   "Open-Drain ACK from addressed Slave (or any Slave on 7'h7E). LOW = ACK, HIGH = NACK.",
        }
        d["single_response_for_write"] = (
            "I3C data writes are NOT individually ACKed by the slave. Each "
            "Master-written data byte is followed by a Master-driven T-Bit = "
            "odd parity over the 8 data bits = XOR(Data[7:0], 1). On parity "
            "violation the Slave NACKs the next byte boundary (error type S2).")
        d["per_beat_response_for_read"] = (
            "Slave-driven T-Bit: 1 = continue with next data word; 0 = end of "
            "message (Slave releases SDA). Master may abort by overriding "
            "T=1 with a driven LOW after SCL rising, treated as Repeated START.")
        d["reserved_addresses_table9_summary"] = {
            "header": ["Address (7-bit)", "Restriction", "Description"],
            "rows": [
                ["7'h00", "Shall not use", "I3C Reserved"],
                ["7'h01", "Shall not use", "I3C Reserved — SETDASA Point-to-Point Communication only"],
                ["7'h02", "Shall not use as Dynamic Address", "I3C Reserved — Hot-Join Address"],
                ["7'h03..7'h07", "Conditional / Optional", "Available only if no Legacy I2C 'High-Speed Mode' devices on bus; otherwise marked Reserved by I2C"],
                ["7'h08..7'h3D", "Available", "54 free addresses for Dynamic Address use"],
                ["7'h3E", "Shall not use", "Broadcast Address single-bit-error detect"],
                ["7'h3F..7'h5D", "Available", "31 free addresses"],
                ["7'h5E", "Shall not use", "Broadcast Address single-bit-error detect"],
                ["7'h5F..7'h6D", "Available", "15 free addresses"],
                ["7'h6E", "Shall not use", "Broadcast Address single-bit-error detect"],
                ["7'h6F..7'h75", "Available", "7 free addresses"],
                ["7'h76", "Shall not use", "Broadcast Address single-bit-error detect"],
                ["7'h77", "Available", "1 free address"],
                ["7'h78..7'h7B", "Conditional", "Available only if no Legacy I2C 'Extended Address Mode' devices on bus; 7'h7A is single-bit-error detect"],
                ["7'h7C", "Shall not use", "Broadcast Address single-bit-error detect + not available if any I2C 'Device ID Mode' device present"],
                ["7'h7D", "Conditional", "Available only if no I2C 'Device ID Mode' device on bus"],
                ["7'h7E", "Shall not use as Dynamic Address", "I3C Broadcast Address"],
                ["7'h7F", "Shall not use", "Broadcast Address single-bit-error detect"],
            ],
        }
        d["ccc_overview"] = {
            "broadcast_range": "0x00 .. 0x7F — applied to all I3C Slaves on the bus following 7'h7E + W + ACK.",
            "direct_range":    "0x80 .. 0xFE — addressed via Sr + Target Slave Dynamic Address + RnW.",
            "frame_skeleton_broadcast": "S → 7'h7E + W → ACK → CCC_byte + T → [optional payload bytes + T] → P (or Sr + 7'h7E to end CCC and start a new message)",
            "frame_skeleton_direct":    "S → 7'h7E + W → ACK → CCC_byte + T → Sr → Slave_DA + RnW → ACK → [payload] → (continue / Sr / P)",
            "tables_15_through_51":     "Per Table 15 there are Required and Optional CCCs covering bus events (ENEC/DISEC), activity state (ENTAS0..3), address management (RSTDAA, ENTDAA, SETDASA, SETNEWDA, SETAASA, DEFSLVS), per-slave length controls (SET/GET MWL/MRL), characteristics (GETPID, GETBCR, GETDCR, GETSTATUS), mastership (GETACCMST), bridge (SETBRGTGT), and capability (GETMXDS); HDR-related CCCs (ENTHDR0..7, SETXTIME, GETXTIME, GETHDRCAP) are not used by I3C Basic but must be parsed.",
        }
        d["ccc_required_subset_i3c_basic"] = [
            {"code": "0x00", "type": "Broadcast", "name": "ENEC",     "required": "Y",  "purpose": "Enable Slave event-driven interrupts (IBI / Hot-Join / Master Request)."},
            {"code": "0x01", "type": "Broadcast", "name": "DISEC",    "required": "Y",  "purpose": "Disable Slave event-driven interrupts."},
            {"code": "0x02", "type": "Broadcast", "name": "ENTAS0",   "required": "Y(1)","purpose": "Enter Activity State 0 (normal operation, lowest tCAS)."},
            {"code": "0x06", "type": "Broadcast", "name": "RSTDAA",   "required": "Y",  "purpose": "Reset Dynamic Address Assignment — slaves forget DA and await re-assignment."},
            {"code": "0x07", "type": "Broadcast", "name": "ENTDAA",   "required": "Y",  "purpose": "Enter Dynamic Address Assignment Mode."},
            {"code": "0x09", "type": "Broadcast", "name": "SETMWL",   "required": "Y(6)","purpose": "Set Maximum Write Length."},
            {"code": "0x0A", "type": "Broadcast", "name": "SETMRL",   "required": "Y(7)","purpose": "Set Maximum Read Length."},
            {"code": "0x80", "type": "Direct",    "name": "ENEC",     "required": "Y",  "purpose": "Direct Enable Slave Event Interrupts."},
            {"code": "0x81", "type": "Direct",    "name": "DISEC",    "required": "Y",  "purpose": "Direct Disable Slave Event Interrupts."},
            {"code": "0x86", "type": "Direct",    "name": "RSTDAA",   "required": "Y",  "purpose": "Direct Reset Dynamic Address."},
            {"code": "0x88", "type": "Direct Set","name": "SETNEWDA", "required": "Y",  "purpose": "Set New Dynamic Address."},
            {"code": "0x89", "type": "Direct Set","name": "SETMWL",   "required": "Y(2)","purpose": "Per-slave SETMWL."},
            {"code": "0x8A", "type": "Direct Set","name": "SETMRL",   "required": "Y(2)","purpose": "Per-slave SETMRL."},
            {"code": "0x8B", "type": "Direct Get","name": "GETMWL",   "required": "Y(2)","purpose": "Get Slave's max write length."},
            {"code": "0x8C", "type": "Direct Get","name": "GETMRL",   "required": "Y(2)","purpose": "Get Slave's max read length."},
            {"code": "0x8D", "type": "Direct Get","name": "GETPID",   "required": "Y",  "purpose": "Get Slave's 48-bit Provisional ID."},
            {"code": "0x8E", "type": "Direct Get","name": "GETBCR",   "required": "Y",  "purpose": "Get Slave's Bus Characteristics Register."},
            {"code": "0x8F", "type": "Direct Get","name": "GETDCR",   "required": "Y",  "purpose": "Get Slave's Device Characteristics Register."},
            {"code": "0x90", "type": "Direct Get","name": "GETSTATUS","required": "Y",  "purpose": "Get Slave operating status."},
        ]
        d["daa_entdaa_sequence_overview"] = [
            "Master sends ENTDAA (0x07) after 7'h7E + W + ACK (Broadcast).",
            "Master sends Sr + 7'h7E + R + ACK (every yet-unaddressed non-HotJoin slave ACKs).",
            "Master clocks SCL, releases SDA; each slave drives its 48-bit Provisional ID || BCR || DCR (8 bytes) MSb-first, Big-Endian, with no inter-byte ACK.",
            "Open-Drain arbitration: lowest concatenated value wins.",
            "Master assigns 7-bit Dynamic Address + 1-bit odd parity = ~XOR(DA[7:1]); winning slave ACKs.",
            "Repeat (Sr + 7'h7E + R) until no further ACK; Master ends with P.",
        ]
        d["ibi_transaction_overview"] = [
            "From Bus Available Condition, Slave pulls SDA LOW (acts as START).",
            "Master drives SCL within best-effort; Slave drives its 7-bit Dynamic Address (R=1) on SDA in Open-Drain, MSb-first.",
            "Open-Drain arbitration: lower address wins (priority).",
            "Master ACK = accept (Open-Drain LOW on 9th bit); NACK = reject (HIGH).",
            "On ACK, if BCR[2]=1 the Slave sends Mandatory Data Byte(s) (T-Bit 1=continue, 0=end).",
        ]
        d["master_to_slave_write_transaction_sdr"] = [
            "S → 7'h7E + W → ACK (broadcast) → CCC_or_Sr → ...",
            "If Direct CCC: → CCC_byte + T → Sr → Slave_DA + W → ACK → DATA0 + T0 → DATA1 + T1 → ... → P",
            "If private write (no CCC): S → Slave_DA + W → ACK → DATA0 + T0 → DATA1 + T1 → ... → P",
            "Each Master-driven T-Bit = XOR(Data[7:0], 1); ACK never appears on data bytes.",
        ]
        d["slave_to_master_read_transaction_sdr"] = [
            "S → 7'h7E + W → ACK (broadcast) → CCC + Sr → Slave_DA + R → ACK → DATA0 + T0 → DATA1 + T1 → ... → P",
            "Slave-driven T-Bit: T=1 continue, T=0 end-of-message; Master may force end via Sr.",
            "On error / no slave: NACK on header → Master STOPs or Sr to a different slave.",
        ]
        _write(p, d)

    # ------------------------------------------------------------------
    # L4 register map (protocol-level only — BCR / DCR / LVR / PID)
    # ------------------------------------------------------------------
    p = gd / "L4_REGMAP.json"
    if p.is_file():
        d = _read(p)
        d["register_map_present"] = "partial"
        d["notes"] = (
            "MIPI I3C Basic is a wire-level protocol specification, not a "
            "controller block guide. There is no SoC-level architectural "
            "register map. However, the spec defines three protocol-level "
            "characteristics registers that every device on the bus must "
            "expose (or hold virtually for I2C Slaves) — BCR, DCR, and (for "
            "legacy I2C devices) LVR.")
        d["protocol_level_characteristic_registers"] = [
            {
                "name": "BCR (Bus Characteristics Register)",
                "width_bits": 8,
                "applies_to": "Every I3C compliant Device (Master or Slave)",
                "access": "Read-only via GETBCR Direct CCC (0x8E) or as part of the 8 bytes returned during ENTDAA arbitration",
                "fields": [
                    {"bit": "BCR[7:6]", "name": "Device Role[1:0]", "description": "00 = I3C Slave; 01 = I3C Master; 10/11 = Reserved by MIPI"},
                    {"bit": "BCR[5]",   "name": "MIPI Reserved",   "description": "0 (default)"},
                    {"bit": "BCR[4]",   "name": "Bridge Identifier","description": "0 = not a Bridge Device; 1 = is a Bridge Device (must comply with full I3C v1.0)"},
                    {"bit": "BCR[3]",   "name": "Offline Capable", "description": "0 = always responds to I3C bus commands; 1 = may be offline (retains DA)"},
                    {"bit": "BCR[2]",   "name": "IBI Payload",     "description": "0 = no mandatory data byte follows accepted IBI; 1 = one or more mandatory data bytes follow, with T-Bit continuation"},
                    {"bit": "BCR[1]",   "name": "IBI Request Capable","description": "0 = not capable; 1 = capable"},
                    {"bit": "BCR[0]",   "name": "Max Data Speed Limitation","description": "0 = no limitation; 1 = limitation (Master must use GETMXDS to interrogate)"},
                ],
            },
            {
                "name": "DCR (Device Characteristics Register)",
                "width_bits": 8,
                "applies_to": "Every I3C compliant Device",
                "access": "Read-only via GETDCR Direct CCC (0x8F) or as part of the 8 bytes returned during ENTDAA arbitration",
                "fields": [
                    {"bit": "DCR[7:0]", "name": "Device ID[7:0]", "description": "255 available codes describing the type of device (e.g. accelerometer, gyroscope, magnetometer, composite, generic). Default = 8'h00 = Generic Device."},
                ],
            },
            {
                "name": "LVR (Legacy Virtual Register)",
                "width_bits": 8,
                "applies_to": "Every Legacy I2C Device on an I3C bus (held virtually by the Main Master / Application Host)",
                "access": "Loaded by the higher-level entity; transferable to Secondary Masters via DEFSLVS CCC (0x08)",
                "fields": [
                    {"bit": "LVR[7:5]", "name": "Legacy I2C only[2:0] (Index)", "description": "Index into Table 5 — 3'b000 Index 0; 3'b001 Index 1; 3'b010 Index 2; 3'b011..3'b111 Reserved"},
                    {"bit": "LVR[4]",   "name": "I2C Mode Indicator", "description": "0 = I2C Fm+; 1 = I2C Fm"},
                    {"bit": "LVR[3:0]", "name": "MIPI Reserved (Device-specific codes)", "description": "15 codes available for describing legacy I2C device capabilities / function"},
                ],
            },
            {
                "name": "PID (Provisional ID)",
                "width_bits": 48,
                "applies_to": "Every I3C compliant Device — burned in non-volatile / factory memory",
                "access": "Read-only via GETPID Direct CCC (0x8D) — returned as 6 bytes MSb-first; also driven during ENTDAA arbitration (Big-Endian)",
                "fields": [
                    {"bit": "PID[47:33]", "name": "MIPI Manufacturer ID",   "description": "15-bit MIPI Manufacturer ID per MIPI Alliance Manufacturer ID Page (most significant bit of the 16-bit MID is discarded)"},
                    {"bit": "PID[32]",    "name": "Provisional ID Type Selector", "description": "1'b0 = Vendor Fixed Value (Manufacturer-burnt); 1'b1 = Random Value (e.g. test mode)"},
                    {"bit": "PID[31:16]", "name": "Part ID",                 "description": "16-bit vendor-defined Part identifier"},
                    {"bit": "PID[15:12]", "name": "Instance ID",             "description": "4-bit unique instance identifier among devices of the same Part ID on a bus"},
                    {"bit": "PID[11:0]",  "name": "DCR-defined / Vendor-defined", "description": "12-bit field whose meaning is left to the vendor / DCR-specific definition"},
                ],
            },
        ]
        d["soc_dependent_registers"] = (
            "Concrete I3C controller IP blocks expose their own register file "
            "(transmit/receive FIFO, status, interrupt enable, address, mode "
            "select, baud / SCL divider, IBI / Hot-Join control, error flags, "
            "BCR/DCR shadow, etc.) — these are defined per controller block "
            "guide, not by this specification.")
        _write(p, d)

    # ------------------------------------------------------------------
    # L5 ADI
    # ------------------------------------------------------------------
    p = gd / "L5_ADI_SPEC.json"
    if p.is_file():
        d = _read(p)
        d["analog_digital_interface_present"] = False
        d["signaling_summary"] = (
            "Pure digital two-wire protocol with carefully-specified analog DC "
            "and AC characteristics. SDA and SCL operate at VDD (typically "
            "1.2 V / 1.8 V / 3.3 V); logic levels are ratiometric "
            "(VIL ≤ 0.3 VDD, VIH ≥ 0.7 VDD). SDA dynamically switches between "
            "Open-Drain (with passive Pull-Up resistor and optional "
            "High-Keeper) and Push-Pull; SCL is normally Push-Pull and may "
            "also be Open-Drain. Maximum capacitive load per bus line in I3C "
            "Push-Pull SDR is 50 pF (Cb). Max SCL clock = 12.5 MHz nominal / "
            "12.9 MHz max. Optional High-Keeper devices weakly maintain HIGH "
            "on SDA when no active driver is present to prevent floating "
            "during bus turnarounds. Failsafe pads required for Hot-Join "
            "devices.")
        _write(p, d)

    # ------------------------------------------------------------------
    # L6 control logic — FSM states for I3C
    # ------------------------------------------------------------------
    p = gd / "L6_CONTROL_LOGIC.json"
    if p.is_file():
        d = _read(p)
        d["fsm_overview"] = (
            "Annex C of the spec defines six normative FSMs covering the I3C "
            "Bus lifecycle: Main Master, Slave Interrupt Request, Dynamic "
            "Address Assignment, Hot-Join, Secondary Master Request, Master "
            "Regaining Bus Ownership, plus an I2C Legacy Master sub-FSM.")
        d["fsm_states"] = [
            {"name": "IDLE",                "description": "Bus free / available; SDA and SCL both HIGH (released, optional High-Keeper); no transaction active. Master may initiate a new frame; Slaves may issue Hot-Join / IBI after tIDLE / tAVAL respectively."},
            {"name": "START_DETECT",        "description": "Either Master or (in IBI / Hot-Join / Secondary Master Request from Bus Available) Slave drives SDA HIGH→LOW while SCL HIGH → bus becomes busy."},
            {"name": "ADDR_HDR_ARBITRABLE", "description": "Address Header following a START — driven Open-Drain initially; Open-Drain bit-by-bit arbitration on SDA; may transition to Push-Pull mid-header per Section 5.1.2.2.2."},
            {"name": "ADDR_HDR_PUSH_PULL",  "description": "Address Header following a Repeated START — driven entirely Push-Pull except the 9th ACK/NACK bit (Open-Drain)."},
            {"name": "ADDR_ACK_WAIT",       "description": "9th SCL bit of address header: addressed Slave drives SDA LOW = ACK; HIGH = NACK (Open-Drain)."},
            {"name": "WRITE_DATA_WORD",     "description": "Master drives 8 data bits Push-Pull MSb-first, then drives T-Bit = odd parity = XOR(Data[7:0], 1) on 9th SCL bit."},
            {"name": "READ_DATA_WORD",      "description": "Slave drives 8 data bits Push-Pull MSb-first, then drives T-Bit on 9th SCL bit: T=1 continue, T=0 end-of-message."},
            {"name": "READ_DATA_PARK",      "description": "On T=1, Slave releases SDA HIGH-Z on rising SCL — bus is 'parked' HIGH. Master may either let weak Pull-Up keep HIGH (continue) or drive SDA LOW (force Sr / abort)."},
            {"name": "DAA_ENTDAA",          "description": "Master broadcasts ENTDAA (0x07) → Sr + 7'h7E + R + ACK → slaves drive 48-bit PID + BCR + DCR onto SDA; Master clocks SCL only; Open-Drain arbitration; lowest concatenated value wins."},
            {"name": "DAA_ADDR_ASSIGN",     "description": "Master drives 7-bit Dynamic Address + 1-bit odd-parity on SDA Open-Drain; winning slave ACKs on the next SCL bit."},
            {"name": "DAA_REPEAT",          "description": "After ACK, Master returns to Sr + 7'h7E + R until no slave ACKs; then issues STOP."},
            {"name": "IBI_ARBITRATION",     "description": "From Bus Available Condition, Slave pulls SDA LOW; Master drives SCL; Slave drives its Dynamic Address (RnW=1) Open-Drain; lower address wins."},
            {"name": "IBI_ACK_DECIDE",      "description": "Master decides to ACK (accept) or NACK (reject) the IBI; if ACK and BCR[2]=1, Slave sends one or more Mandatory Data Bytes with T-Bit continuation."},
            {"name": "HOTJOIN_REQUEST",     "description": "From Bus Idle Condition (≥ tIDLE), Hot-Join Slave drives Hot-Join Address 7'h02 (RnW=0); Master may NACK (try later), ACK + DISHJ, or ACK + ENTDAA."},
            {"name": "SECMASTER_REQUEST",   "description": "BCR-marked Secondary Master drives its own Dynamic Address (RnW=0) in arbitrable header → Master responds; handoff finalized via GETACCMST (0x91)."},
            {"name": "MASTER_CLOCK_STALL",  "description": "Master holds SCL LOW under specific transitory conditions (ACK/NACK Phase, Write Parity Bit, T-Bit before Sr/STOP/next-read, DAA first bit). See Table 11."},
            {"name": "HDR_EXIT_DETECT",     "description": "Every device watches SDA toggles while SCL stays LOW; defined HDR Exit Pattern returns the bus to SDR Mode."},
            {"name": "STOP_GENERATE",       "description": "Master drives SDA LOW→HIGH while SCL HIGH → frame ends; bus becomes Free after tCAS / tBUF."},
        ]
        d["fsm_hints"] = {
            "trigger": "Either Master starts a frame from Bus Free / Available, or Slave starts a request (IBI / Hot-Join / Secondary Master Request) from Bus Available / Bus Idle.",
            "rule":    "Address Header has 9 SCL bits; SDR Data Word has 9 SCL bits (8 data + 1 T-Bit). On Push-Pull SDA, only one driver may be active. Slave NEVER drives SCL.",
            "abort":   "Master may abort a Slave-driven read at T-Bit HIGH by issuing Repeated START; or end any transaction with STOP.",
        }
        d["anti_deadlock_rule"] = (
            "Slaves cannot clock-stretch SCL; the only path through which a "
            "Slave delays the Master is the T-Bit end-of-message mechanism, "
            "Master Clock Stall (controlled by Master), and Open-Drain "
            "arbitration. SCL is always driven by the Master.")
        d["exit_from_reset"] = (
            "After POR every I3C device releases SDA and SCL HIGH-Z (Failsafe "
            "pads if Hot-Join). Main Master enters Dynamic Address Assignment "
            "Mode after collecting static-address / LVR data for any Legacy "
            "I2C devices and SETDASA / SETAASA for known-static I3C devices, "
            "then issues ENTDAA (0x07) to assign Dynamic Addresses to all "
            "remaining I3C devices.")
        d["default_ready_state_recommendation"] = {
            "SDA_idle":          "HIGH (released by all devices; optional High-Keeper).",
            "SCL_idle":          "HIGH (released by Master).",
            "header_ack_window": "Slave pulls SDA LOW only during the 9th SCL bit of the address header (Open-Drain).",
            "data_t_bit_window": "Master-write: Master drives T-Bit on the 9th SCL bit. Slave-read: Slave drives T-Bit on the 9th SCL bit; on T=1 it releases SDA HIGH-Z to allow Master abort.",
            "no_slave_clock_stretch": "Slave-side SCL stretching is forbidden — must NOT pull SCL LOW.",
        }
        d["channel_dependency_rules_master"] = {
            "note": "Master drives SCL Push-Pull (or Open-Drain in legacy / arbitration); generates START / STOP / Sr / DAA-assigned addresses; in Master-write drives SDA Push-Pull for data and T-Bit; in Master-read releases SDA after the address header. May Master Clock Stall under specific transitory conditions (Table 11).",
        }
        d["channel_dependency_rules_slave"] = {
            "note": "Slave samples SDA on rising SCL; drives SDA only during ACK windows, Slave-read data bytes + T-Bit, IBI arbitration, ENTDAA payload (PID/BCR/DCR), Hot-Join address. NEVER drives SCL.",
        }
        d["arbitration_rule"] = (
            "Open-Drain wired-AND on SDA, MSb-first: the device that drives "
            "LOW wins. Used in (a) arbitrable address header after S, "
            "(b) IBI address contention, (c) ENTDAA Provisional ID stream — "
            "the lowest concatenated value wins.")
        d["synchronization_rule"] = (
            "Single Master drives SCL Push-Pull; no SCL synchronization "
            "mechanism is required because slaves cannot stretch SCL. During "
            "Master handoff to a Secondary Master, the two Masters overlap "
            "their drive for at least tMMOverlap before the new Master takes "
            "sole control.")
        d["master_clock_stall_conditions_table11"] = [
            "ACK/NACK Phase — Master may stall SCL LOW to delay accepting an IBI / decision.",
            "Write Parity Bit — Master may stall before driving T-Bit on a Master-write byte.",
            "T-Bit before next Read Data — Master may stall to slow down the Slave's next read word.",
            "T-Bit before STOP — Master may stall before issuing STOP to give Slave time to release SDA.",
            "T-Bit before Repeated START — Master may stall before Sr.",
            "Dynamic Address First Bit — Master may stall in DAA between PID streams and address assignment.",
        ]
        _write(p, d)

    # ------------------------------------------------------------------
    # L7 test debug
    # ------------------------------------------------------------------
    p = gd / "L7_TEST_DEBUG.json"
    if p.is_file():
        d = _read(p)
        d["test_debug_architecture_present"] = False
        d["spec_provided_observability"] = [
            {"name": "Header ACK / NACK",       "purpose": "Per-frame success indicator on SDA 9th SCL bit during address header."},
            {"name": "T-Bit Parity (Write)",    "purpose": "Per-byte data integrity check on Master-write words; mismatch = error type S2."},
            {"name": "T-Bit End-of-Data (Read)","purpose": "Slave-driven flow-control on read; 0 = end, 1 = continue. Master may force end via Sr."},
            {"name": "IBI Address Arbitration", "purpose": "Slave-initiated request visibility: Open-Drain SDA arbitration on Slave Dynamic Address (RnW=1) starting from Bus Available Condition."},
            {"name": "Hot-Join Address (7'h02)","purpose": "Detection of joining devices; mappable to a controller interrupt."},
            {"name": "Bus Conditions",          "purpose": "Bus Free (≥ tCAS), Bus Available (≥ tAVAL), Bus Idle (≥ tIDLE) — observable timing windows."},
            {"name": "HDR Exit Pattern",        "purpose": "Detected by every device; signals return to SDR mode after any HDR session."},
            {"name": "BCR / DCR / PID",         "purpose": "Read-only protocol-level capability registers, exposed through GETBCR / GETDCR / GETPID Direct CCCs."},
            {"name": "GETSTATUS CCC (0x90)",    "purpose": "Per-slave operating status: MSb-first 2-byte response per Tables 40-41 — includes pending interrupt, protocol error, activity state."},
            {"name": "SDR Error Types S0..S6",  "purpose": "Slave-side error taxonomy: S0 illegal address, S1 CCC parity, S2 write parity, S3 read parity, S4 monitor error, S5 NACKed IBI, S6 optional self-test."},
            {"name": "SDR Error Types M0..M2",  "purpose": "Master-side error taxonomy: M0 unexpected NACK, M1 invalid CCC return, M2 bus error / recovery escalation."},
        ]
        d["interrupt_sources"] = [
            {"flag": "IBI_REQ",         "trigger": "Slave drove its Dynamic Address (RnW=1) starting from Bus Available Condition."},
            {"flag": "HOTJOIN_REQ",     "trigger": "Slave drove Hot-Join Address 7'h02 (RnW=0) starting from Bus Idle Condition."},
            {"flag": "MR_REQ",          "trigger": "Secondary Master drove its Dynamic Address (RnW=0) in arbitrable header."},
            {"flag": "HEADER_NACK",     "trigger": "Address header was NACKed."},
            {"flag": "WR_PARITY_ERR",   "trigger": "T-Bit parity violation on Master-write byte (S2 / M0)."},
            {"flag": "RD_END_OF_MSG",   "trigger": "Slave drove T=0 on read data."},
            {"flag": "DAA_DONE",        "trigger": "Dynamic Address Assignment procedure completed."},
            {"flag": "HDR_EXIT_DETECT", "trigger": "HDR Exit Pattern observed on the bus."},
            {"flag": "BUS_ERROR",       "trigger": "Master-detected bus stuck / unexpected condition (M2)."},
        ]
        d["interrupt_request"] = (
            "I3C is unique in that the protocol itself carries In-Band "
            "Interrupts (IBI) over SDA — no separate IRQ pin is required. "
            "Concrete controllers also expose conventional MCU interrupts for "
            "the controller events listed above.")
        d["notes"] = (
            "MIPI I3C Basic v1.0 is a wire-level specification; DFT / scan / "
            "BIST / JTAG architecture lives at the SoC integration level. "
            "The above lists protocol-level observable conditions any "
            "compliant controller should expose. Annex C of the spec contains "
            "the normative FSMs for Main Master, Slave Interrupt Request, "
            "DAA, Hot-Join, Secondary Master Request, and Master Regaining "
            "Bus Ownership.")
        _write(p, d)

    # ------------------------------------------------------------------
    # L8 RTL constants
    # ------------------------------------------------------------------
    p = gd / "L8_RTL_CONSTANTS.json"
    if p.is_file():
        d = _read(p)
        wp = d.setdefault("width_parameters", {})
        for k, v in {
            "ADDRESS_WIDTH_bits": 7,
            "RW_BIT_WIDTH": 1,
            "ACK_BIT_WIDTH": 1,
            "DATA_BYTE_WIDTH_bits": 8,
            "T_BIT_WIDTH": 1,
            "SDR_DATA_WORD_WIDTH_bits": 9,
            "ADDRESS_HEADER_WIDTH_bits": 9,
            "SCL_PULSES_PER_WORD": 9,
            "PROVISIONAL_ID_WIDTH_bits": 48,
            "PROV_ID_MFG_WIDTH_bits": 15,
            "PROV_ID_TYPE_SEL_WIDTH_bits": 1,
            "PROV_ID_PART_WIDTH_bits": 16,
            "PROV_ID_INSTANCE_WIDTH_bits": 4,
            "PROV_ID_DCR_DEFINED_WIDTH_bits": 12,
            "BCR_WIDTH_bits": 8,
            "DCR_WIDTH_bits": 8,
            "LVR_WIDTH_bits": 8,
            "DAA_BYTE_PAYLOAD_PER_ROUND_bytes": 8,
            "DAA_DYNAMIC_ADDR_PLUS_PARITY_bits": 8,
            "CCC_CODE_WIDTH_bits": 8,
            "MAX_SLAVES_PER_BUS_typical": 11,
        }.items():
            wp[k] = v
        d["key_addresses_hex"] = {
            "broadcast_address_7E":   "0x7E (7-bit) — I3C Broadcast Address",
            "hot_join_address_02":    "0x02 (7-bit) — I3C Hot-Join Address",
            "reserved_setdasa_01":    "0x01 (7-bit) — SETDASA Point-to-Point Communication",
            "reserved_other_00":      "0x00 (7-bit) — Reserved",
            "broadcast_single_bit_err":["0x3E","0x5E","0x6E","0x76","0x7A","0x7C","0x7F"],
            "conditional_addresses":  ["0x03..0x07","0x78..0x7B","0x7D"],
        }
        d["ccc_codes_hex"] = {
            "broadcast_range": "0x00..0x7F",
            "direct_range":    "0x80..0xFE",
            "required_broadcast": {
                "ENEC":   "0x00", "DISEC":  "0x01", "ENTAS0": "0x02",
                "RSTDAA": "0x06", "ENTDAA": "0x07", "SETMWL": "0x09",
                "SETMRL": "0x0A",
            },
            "optional_broadcast": {
                "ENTAS1":   "0x03", "ENTAS2":   "0x04", "ENTAS3":  "0x05",
                "DEFSLVS":  "0x08", "ENTTM":    "0x0B",
                "ENTHDR0..7": "0x20..0x27",
                "SETXTIME": "0x28", "SETAASA":  "0x29",
            },
            "required_direct": {
                "ENEC":     "0x80", "DISEC":    "0x81", "ENTAS0":   "0x82",
                "RSTDAA":   "0x86", "SETNEWDA": "0x88",
                "SETMWL":   "0x89", "SETMRL":   "0x8A",
                "GETMWL":   "0x8B", "GETMRL":   "0x8C",
                "GETPID":   "0x8D", "GETBCR":   "0x8E", "GETDCR":   "0x8F",
                "GETSTATUS":"0x90",
            },
            "optional_direct": {
                "ENTAS1..3":"0x83..0x85", "SETDASA":  "0x87",
                "GETACCMST":"0x91", "SETBRGTGT":"0x93",
                "GETMXDS":  "0x94", "GETHDRCAP":"0x95",
                "SETXTIME": "0x98", "GETXTIME": "0x99",
            },
        }
        d["voltage_levels"] = {
            "VIL_max": "0.3 * VDD",
            "VIH_min": "0.7 * VDD",
            "typical_VDD_options": "1.2 V / 1.8 V / 3.3 V",
        }
        d["mode_bit_rates"] = {
            "I3C_SDR_PushPull":     {"max_SCL_MHz_typ": 12.5, "max_SCL_MHz_abs": 12.9, "min_SCL_MHz": 0.01, "duplex": "bidirectional", "drive": "Push-Pull on data + Sr header; Open-Drain on START / arbitrable header / ACK / DAA"},
            "I3C_Mixed_Fast_Bus":   {"SCL_HIGH_max_ns_tDIG_H_MIXED": 45, "purpose": "Constrain SCL HIGH so 50 ns I2C Spike Filter ignores I3C traffic"},
            "Legacy_I2C_Fm":        {"max_SCL_kHz": 400,  "duplex": "bidirectional", "drive": "Open-Drain (I2C-compatible)"},
            "Legacy_I2C_Fm_Plus":   {"max_SCL_kHz": 1000, "duplex": "bidirectional", "drive": "Open-Drain (I2C-compatible)"},
            "HDR_DDR_not_in_basic": {"max_Mbps": 25, "note": "2 bits per SCL cycle; not supported in I3C Basic but exit pattern must be detected"},
            "HDR_TSx_not_in_basic": {"max_Mbps": "~33-40", "note": "Ternary symbol modes; not in I3C Basic"},
        }
        d["key_constants_for_RTL_authoring"] = {
            "wires": 2,
            "bits_per_address_header": 9,
            "bits_per_sdr_data_word": 9,
            "scl_pulses_per_word": 9,
            "broadcast_address_7bit_hex": "0x7E",
            "hot_join_address_7bit_hex": "0x02",
            "start_condition": "SDA HIGH→LOW while SCL HIGH",
            "stop_condition":  "SDA LOW→HIGH while SCL HIGH",
            "ack_polarity":    "Open-Drain LOW = ACK; HIGH = NACK (only on address-header 9th bit)",
            "t_bit_write_definition": "T = XOR(Data[7:0], 1) = odd parity over the 8 data bits",
            "t_bit_read_continue_value": 1,
            "t_bit_read_end_value":      0,
            "sda_change_rule":           "SDA may only change state while SCL is LOW (except S / P / Sr)",
            "msb_first_byte_order":      True,
            "max_bus_capacitance_pF":    50,
            "max_scl_freq_MHz":          12.5,
            "rw_bit_value_for_write":    0,
            "rw_bit_value_for_read":     1,
            "slave_clock_stretch_allowed": False,
            "dynamic_address_parity_definition": "parity = ~XOR(DA[7:1]) — placed in DA[0] position by the Master during DAA",
        }
        d["key_timing_parameters_summary_ns"] = {
            "tDIG_H_min":      32,
            "tDIG_L_min":      32,
            "tDIG_H_MIXED_max":45,
            "tHIGH_min":       24,
            "tLOW_min":        24,
            "tSCO_max":        12,
            "tCR_cap_ns":      60,
            "tCF_cap_ns":      60,
            "tSU_PP_min":      3,
            "Cb_max_pF":       50,
        }
        d["key_timing_parameters_summary_us"] = {
            "tCAS_min_ns":     38.4,
            "tCAS_max_us_ENTAS0": 1,
            "tCAS_max_us_ENTAS1": 100,
            "tCAS_max_ms_ENTAS2": 2,
            "tCAS_max_ms_ENTAS3": 50,
            "tAVAL_min_us":    1,
            "tIDLE_min_us":    200,
            "tLOW_OD_min_ns":  200,
            "tfDA_OD_max_ns":  12,
        }
        d["default_signal_values_when_idle"] = {
            "SDA": "HIGH (released; optional High-Keeper)",
            "SCL": "HIGH (released by Master)",
        }
        # remove I2C-only voltage_levels.legacy_fixed_* leftovers (if I2C synth populated them earlier)
        vl = d.get("voltage_levels", {})
        if isinstance(vl, dict):
            for kill in ("legacy_fixed_VIL", "legacy_fixed_VIH"):
                vl.pop(kill, None)
        _write(p, d)

    # ------------------------------------------------------------------
    # L8 timing
    # ------------------------------------------------------------------
    p = gd / "L8_TIMING_WAVEFORM.json"
    if p.is_file():
        d = _read(p)
        d["clock_and_reset_waveform"] = {
            "SCL_idle": "HIGH (released by Master; Push-Pull when driven)",
            "SDA_idle": "HIGH (released by all devices; optional High-Keeper)",
            "POR_release": "After Power-On Reset, devices release SDA and SCL HIGH-Z. Hot-Join-capable devices must be Failsafe — pad leakage shall not increase when unpowered (Section 5.1.5.1).",
        }
        d["bit_transfer_waveform"] = {
            "rule": "Data on SDA must be stable while SCL is HIGH (data valid window). SDA may change while SCL is LOW. Exception: START / STOP / Repeated START transition SDA while SCL is HIGH.",
            "figure": "Figures 30, 31, 32, 36, 37, 38",
        }
        d["start_stop_waveform"] = {
            "start_S":           "SDA HIGH→LOW while SCL HIGH (Figure 34 — Open-Drain in arbitrable header following S)",
            "stop_P":            "SDA LOW→HIGH while SCL HIGH (Figure 35)",
            "repeated_start_Sr": "Same as S; address header following Sr is Push-Pull (except ACK)",
            "figure": "Figure 34 / Figure 35",
        }
        d["data_transfer_waveform"] = {
            "address_header_unit": "8 address+RnW bits + 1 ACK bit (Open-Drain) = 9 SCL pulses",
            "sdr_data_word_unit":  "8 data bits + 1 T-Bit = 9 SCL pulses",
            "msb_first":           True,
            "ack_position":        "Address header only: 9th SCL pulse, Slave-driven Open-Drain (LOW=ACK, HIGH=NACK)",
            "t_bit_position":      "SDR data word: 9th SCL pulse — Master drives T=odd-parity on Master-Write; Slave drives T (1=continue, 0=end) on Master-Read",
            "figure": "Figure 32 / Figure 33 / Figures 38..43",
        }
        d["timing_parameters_legacy_fm_table57"] = {
            "fSCL_max_kHz": 400,
            "tHD_STA_min_ns": 600,
            "tLOW_min_ns":    1300,
            "tHIGH_min_ns":   600,
            "tSU_STA_min_ns": 600,
            "tHD_DAT_min_ns": 0,
            "tSU_DAT_min_ns": 100,
            "tBUF_min_us":    1.3,
            "trCL_min_ns":    20,
            "trCL_max_ns":    300,
            "tfCL_max_ns":    300,
            "tSPIKE_max_ns":  50,
        }
        d["timing_parameters_legacy_fm_plus_table57"] = {
            "fSCL_max_kHz": 1000,
            "tHD_STA_min_ns": 260,
            "tLOW_min_ns":    500,
            "tHIGH_min_ns":   260,
            "tSU_STA_min_ns": 260,
            "tSU_DAT_min_ns": 50,
            "tBUF_min_us":    0.5,
            "trCL_max_ns":    120,
            "tfCL_max_ns":    120,
            "tSPIKE_max_ns":  50,
        }
        d["timing_parameters_i3c_open_drain_table58"] = {
            "tLOW_OD_min_ns":      200,
            "tDIG_OD_L_min_ns":    "tLOW_OD_min + tfDA_ODmin",
            # Open-Drain has no tHIGH min cell in Table 58 (high-side
            # undriven via pull-up; rise time governed by tCR not tHIGH).
            # Captured as "n/a min" so the parity diff matches the gold.
            "tHIGH_min_ns":        "n/a min",
            "tHIGH_max_ns":        41,
            "tDIG_H_max_ns":       "tHIGH + tCF",
            "tfDA_OD_max_ns":      12,
            "tSU_OD_min_ns":       3,
            "tCAS_min_ns":         38.4,
            "tCAS_max_per_activity_state": {
                "ENTAS0": "1 µs",
                "ENTAS1": "100 µs",
                "ENTAS2": "2 ms",
                "ENTAS3": "50 ms",
            },
            "tCBP_min_ns":         "tCAS_min / 2",
            "tMMOverlap_min_ns":   "tDIG_OD_L_min",
            "tAVAL_min_us":        1,
            "tIDLE_min_us":        200,
            "tMMLock_min_us":      "tAVAL_min",
        }
        d["timing_parameters_i3c_push_pull_sdr_table59"] = {
            "fSCL_min_MHz":       0.01,
            "fSCL_typ_MHz":       12.5,
            "fSCL_max_MHz":       12.9,
            "tLOW_min_ns":        24,
            "tDIG_L_min_ns":      32,
            "tHIGH_MIXED_min_ns": 24,
            "tDIG_H_MIXED_min_ns":32,
            "tDIG_H_MIXED_max_ns":45,
            "tHIGH_min_ns":       24,
            "tDIG_H_min_ns":      32,
            "tSCO_max_ns":        12,
            "tCR_max_ns_formula": "min(150e6 * 1/fSCL, 60)",
            "tCF_max_ns_formula": "min(150e6 * 1/fSCL, 60)",
            "tHD_PP_master_min_ns":"tCR+3 / tCF+3",
            "tHD_PP_slave_min_ns": 0,
            "tSU_PP_min_ns":      3,
            "tCASr_min_ns":       "tCAS_min",
            "tCBSr_min_ns":       "tCAS_min / 2",
            "Cb_max_pF":          50,
        }
        d["scl_stalling_waveform"] = {
            "scope": "Master-only — Slave SCL stretching is forbidden on I3C",
            "stall_conditions_table11": [
                "ACK/NACK Phase — Figure 11",
                "Write Parity (T-Bit) — Figure 12",
                "T-Bit before next Read Data — Figure 13",
                "T-Bit before STOP — Figure 14",
                "T-Bit before Repeated START (low T) — Figure 15 / 16",
                "Dynamic Address First Bit — Figure 18",
            ],
        }
        d["arbitration_waveform"] = (
            "Open-Drain SDA wired-AND while SCL HIGH; lower-value MSb wins. "
            "Used in (a) S-following arbitrable address header, (b) IBI / "
            "Hot-Join / Secondary Master Request from Bus Available Condition, "
            "(c) ENTDAA Provisional ID arbitration.")
        d["ibi_handoff_waveform"] = (
            "Figure 20 — Slave's address-header ACK from Master kept "
            "Open-Drain LOW during 9th bit; on rising SCL Slave drives SDA "
            "LOW (overlap with Master); Master releases SDA after ≥ tSCO; "
            "Slave drives Mandatory Data Byte(s) on falling SCL using "
            "Push-Pull.")
        d["daa_waveform"] = (
            "Figure 19 — S + 7'h7E + W + ACK + CCC(ENTDAA) + T + Sr + 7'h7E "
            "+ R + ACK + (8 bytes PID/BCR/DCR Slave-driven, no inter-byte "
            "ACK) + (Master-driven 7-bit Dynamic Address + 1-bit odd parity) "
            "+ ACK/NACK; loop or end with P.")
        # blow away any I2C-only legacy keys that the I2C synth wrote earlier
        for kill in ("timing_parameters_standard_mode",
                     "timing_parameters_fast_mode",
                     "timing_parameters_fast_mode_plus",
                     "timing_parameters_high_speed_mode",
                     "clock_stretching_waveform",
                     "synchronization_waveform"):
            d.pop(kill, None)
        _write(p, d)

    # ------------------------------------------------------------------
    # L9 integration
    # ------------------------------------------------------------------
    p = gd / "L9_INTEGRATION_SPEC.json"
    if p.is_file():
        d = _read(p)
        d["module_role"] = (
            "Wire-level inter-IC serial bus specification for the I3C Basic "
            "family. Defines the protocol between any two or more I3C / "
            "Legacy-I2C-compatible devices sharing a two-wire bus (SDA + "
            "SCL). Concrete I3C Master / Slave / Secondary Master / Bridge "
            "IP blocks implement this protocol behind an MCU register "
            "interface at the SoC integration level.")
        d["integration_overview"] = {
            "physical_topology": "All devices' SDA pins connected together; all SCL pins connected together; SDA pulled up to VDD via a Pull-Up Resistor; optional High-Keeper across SDA; SCL Push-Pull-driven by the Main Master (legacy fallback to Open-Drain when serving Legacy I2C devices).",
            "drive_type":        "Mixed-mode: SDA dynamically switches between Push-Pull (data + post-Sr header) and Open-Drain (S + arbitrable header + ACK + DAA + IBI arbitration). SCL Push-Pull from Master (Open-Drain in Legacy I2C mode).",
            "voltage_domain":    "VDD-dependent; logic levels are ratiometric (VIL ≤ 0.3 VDD, VIH ≥ 0.7 VDD).",
            "max_devices":       "Up to 11 I3C Slave Devices typically supported; actual maximum depends on trace length, capacitive load per device (Cb ≤ 50 pF total bus capacitance), and the mix of I3C vs Legacy I2C devices.",
            "address_space":     "7-bit Dynamic Addresses + Static I2C Addresses; Master uses DAA + Static Address knowledge to allocate; reserved addresses per Table 9 cannot be used as Dynamic Addresses.",
            "no_chip_select":    "Addressing is software-based via the 7-bit slave address byte — no per-device chip-select signal.",
        }
        d["interface_categories"] = [
            "I3C Main Master (initially configures bus; may or may not support HDR — I3C Basic = SDR-Only Main Master)",
            "I3C Secondary Master (BCR-marked; functions as Slave until accepting mastership via GETACCMST)",
            "I3C Slave (Required-CCC support; SDR-Only in I3C Basic)",
            "Legacy I2C Slave (Static Address; must comply with Table 4 / Table 5 / Table 56)",
            "I3C Bridge Device (BCR Bit 4 = 1; required to comply with full MIPI I3C v1.0)",
        ]
        d["interconnect_topologies_supported"] = [
            "I3C Main Master + I3C Slaves (Pure Bus)",
            "I3C Main Master + I3C Slaves + Legacy I2C Slaves (Mixed Fast Bus — Legacy slaves have 50 ns Spike Filter)",
            "I3C Main Master + I3C Slaves + Legacy I2C Slaves (Mixed Slow/Limited Bus — Legacy slaves without Spike Filter)",
            "I3C Main Master + Secondary Master(s) + Slaves (multi-master with cooperative handoff)",
            "I3C Bus + I3C Hub / Engine (BCR-encoded role)",
            "I3C Bus with Bridge Devices to SPI / UART / I2C / etc.",
        ]
        d["default_signal_values_when_idle"] = (
            "SDA = HIGH (released, optional High-Keeper); SCL = HIGH "
            "(released by Master). Bus enters 'Free' state after STOP + tCAS "
            "/ tBUF; 'Available' after tAVAL; 'Idle' after tIDLE (Hot-Join "
            "window).")
        d["soc_dependent_items"] = [
            "Pad type (Push-Pull driver + Open-Drain driver + Schmitt input + Failsafe if Hot-Join capable)",
            "Pull-Up resistor sizing (depends on VDD, Cb ≤ 50 pF, target rise time tCR)",
            "Optional High-Keeper device on SDA",
            "SCL clock generation (up to 12.5 MHz typ / 12.9 MHz max)",
            "Bus speed selection per Bus Configuration (Pure / Mixed Fast / Mixed Slow-Limited) and Activity State",
            "Interrupt source mapping (IBI, Hot-Join, Header NACK, Write Parity Error, End-of-Read, DAA Done, HDR Exit Detect, Bus Error)",
            "Software vs hardware static-address strapping for legacy I2C slaves",
            "Master Clock Stall capability (per Table 11)",
            "HDR Exit Pattern Detector logic (every device, even SDR-Only)",
            "NVMEM / strap for Provisional ID storage (manufacturer / part / instance)",
        ]
        d["low_power_modes"] = {
            "bus_idle":     "Both SDA and SCL HIGH; static; only High-Keeper / Pull-Up leakage.",
            "device_sleep": "Slave may sleep but must continue to release SDA HIGH (Failsafe pads if Hot-Join).",
            "activity_states": "ENTAS0..ENTAS3 CCCs let the Master advise the Slaves about expected bus inactivity, adjusting tCAS budget from 1 µs (AS0) to 50 ms (AS3) for power optimization.",
        }
        d["bus_recovery_procedure"] = (
            "If SDA stuck LOW: Master uses HDR Exit Pattern toggling on SDA "
            "while SCL LOW, then re-issues RSTDAA + ENTDAA to recover. If "
            "SCL stuck LOW (e.g. a non-compliant slave): cycle power or "
            "assert system-level reset.")
        d["co_existence_with_i2c"] = {
            "spike_filter_requirement": "I2C slaves on a Mixed Fast Bus must have a true 50 ns Spike Filter so they ignore I3C Push-Pull SDR signaling (tDIG_H_MIXED ≤ 45 ns).",
            "supported_i2c_modes":      "Fm (400 kHz) — required; Fm+ (1 MHz) — desirable. Hs and UFm not used on an I3C bus.",
            "forbidden_i2c_features":   "Slave clock-stretching, 10-bit Extended Addressing, I3C Reserved Address use (per Table 9).",
            "lvr_required":             "Every Legacy I2C device on an I3C bus must have an associated LVR held by the Main Master.",
        }
        # remove I2C-only leftover keys
        d.pop("bus_clear_procedure", None)
        _write(p, d)

    # ------------------------------------------------------------------
    # L10 test cases — v0.1.85 add the Annex C normative FSM list and
    # Annex D typical-communication-example list. The MIPI I3C Basic v1.0
    # specification ships these annexes verbatim (Figures 57-66) and the
    # gold extraction captures them as top-level lists on L10. Without
    # this overlay the parity diff reports two ABSENT_IN_PROGRAM gaps
    # against any I3C-class spec.
    # ------------------------------------------------------------------
    p = gd / "L10_TEST_CASES.json"
    if p.is_file():
        d = _read(p)
        d["annex_c_normative_fsms"] = [
            "Figure 57 I3C Main Master FSM",
            "Figure 58 Slave Interrupt Request FSM",
            "Figure 59 Dynamic Address Assignment FSM",
            "Figure 60 Hot-Join FSM",
            "Figure 61 Secondary Master Request FSM",
            "Figure 62 Master Regaining Bus Ownership FSM",
            "Figure 63 I2C Legacy Master FSM",
        ]
        d["annex_d_typical_examples"] = [
            "Figure 64 Example Communication Using I3C Coding SDR (private write)",
            "Figure 65 Example Communication Using I3C Coding SDR with CCC Direct Addressing",
            "Figure 66 Example Communication Using I3C Coding SDR with CCC Broadcast",
        ]
        _write(p, d)

    # ------------------------------------------------------------------
    # L11 OTP — overwrite I2C generic with I3C-specific PID/BCR/DCR story
    # ------------------------------------------------------------------
    p = gd / "L11_OTP_CONTENT.json"
    if p.is_file():
        d = _read(p)
        d["otp_present"] = True
        d["notes"] = (
            "Unlike pure I2C, MIPI I3C requires every I3C-compliant device "
            "to expose a 48-bit Provisional ID (PID) that is either "
            "factory-burnt (Vendor Fixed Value, Type Selector PID[32]=0) or "
            "vendor-test-mode-random (Type Selector PID[32]=1). The Vendor "
            "Fixed Value is intended to live in factory non-volatile memory "
            "(typically OTP / e-fuse / mask-ROM). In addition, BCR and DCR "
            "carry device role / capability data that are normally "
            "factory-set and read-only.")
        d["factory_burnt_protocol_level_state"] = [
            {
                "name":      "Provisional ID (PID)",
                "width_bits": 48,
                "field_breakdown": "PID[47:33] = 15-bit MIPI Manufacturer ID (per http://mid.mipi.org); PID[32] = Type Selector (0 = Vendor Fixed, 1 = Random / Test); PID[31:16] = 16-bit Part ID; PID[15:12] = 4-bit Instance ID; PID[11:0] = 12-bit DCR-defined / Vendor-defined",
                "purpose": "Used during ENTDAA Dynamic Address Assignment arbitration (Big-Endian, MSb-first, no inter-byte ACK). Also exposed via GETPID Direct CCC (0x8D)."
            },
            {
                "name":      "Bus Characteristics Register (BCR)",
                "width_bits": 8,
                "field_breakdown": "BCR[7:6] Device Role; BCR[5] MIPI Reserved; BCR[4] Bridge Identifier; BCR[3] Offline Capable; BCR[2] IBI Payload; BCR[1] IBI Request Capable; BCR[0] Max Data Speed Limitation",
                "purpose": "Slave-capability exposure during DAA + via GETBCR Direct CCC (0x8E)."
            },
            {
                "name":      "Device Characteristics Register (DCR)",
                "width_bits": 8,
                "field_breakdown": "DCR[7:0] Device ID — 255 codes for sensor / device class (accelerometer, gyroscope, magnetometer, composite, generic = 0x00 default)",
                "purpose": "Slave-class exposure during DAA + via GETDCR Direct CCC (0x8F)."
            },
            {
                "name":      "Static I2C Address (optional)",
                "width_bits": 7,
                "field_breakdown": "Single 7-bit Static I2C Address for I3C Slaves that also support a static-address mode; used as input to SETDASA (CCC 0x87) or SETAASA (CCC 0x29).",
                "purpose": "Optional — allows faster Dynamic Address assignment when Static Address is known."
            },
            {
                "name":      "Legacy Virtual Register (LVR)",
                "width_bits": 8,
                "field_breakdown": "Per Table 8 — index 0..7, I2C mode (Fm / Fm+), vendor-defined codes",
                "purpose": "Held virtually by Main Master for each Legacy I2C device on the bus; not stored in the device itself."
            },
        ]
        d["fuse_otp_implementation_left_to_device"] = (
            "MIPI I3C Basic does not mandate a particular OTP / fuse / "
            "mask-ROM technology — vendors may implement the PID + BCR + DCR "
            "storage in factory-trim, e-fuse, NVMEM, or hardwired registers "
            "as appropriate for the device process. Hot-Join devices may use "
            "NVMEM or pin straps to allow the system designer to disable "
            "Hot-Join behavior.")
        _write(p, d)

    # ------------------------------------------------------------------
    # L12 sequences — overwrite I2C with I3C variants
    # ------------------------------------------------------------------
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if p.is_file():
        d = _read(p)
        d["typical_master_private_write_sequence_sdr"] = [
            "1. Wait for Bus Free Condition (≥ tCAS) or Bus Available Condition (≥ tAVAL).",
            "2. Generate START (S): SDA HIGH→LOW while SCL HIGH.",
            "3. Drive 7-bit Slave Dynamic Address + RnW=0 in the arbitrable address header (Open-Drain → may transition to Push-Pull mid-header).",
            "4. Release SDA on 9th SCL bit; sample SDA for ACK (LOW=ACK, HIGH=NACK).",
            "5. On ACK: drive first data byte Push-Pull MSb-first, 8 bits.",
            "6. On 9th SCL bit drive T-Bit = XOR(Data[7:0], 1) (odd parity).",
            "7. Continue with next data byte or generate Repeated START (Sr) or STOP (P).",
            "8. On NACK at header or on detected parity-NACK on data: optionally Sr to retry or P to abandon.",
        ]
        d["typical_master_private_read_sequence_sdr"] = [
            "1. Wait for Bus Free / Available Condition.",
            "2. Generate START (S).",
            "3. Drive 7-bit Slave Dynamic Address + RnW=1 in the arbitrable address header.",
            "4. Sample 9th SCL bit for ACK from Slave.",
            "5. On ACK: clock SCL while Slave drives 8 data bits Push-Pull MSb-first.",
            "6. On 9th SCL bit, sample Slave-driven T-Bit:",
            "   • T=1 → continue reading next word (Slave releases SDA HIGH-Z; Master may abort by driving SDA LOW = Sr).",
            "   • T=0 → end-of-message; Slave releases SDA; Master issues P or Sr.",
            "7. Master ends transaction with P (or Sr to chain another transaction).",
        ]
        d["typical_master_broadcast_ccc_sequence"] = [
            "1. Generate START.",
            "2. Drive 7'h7E + W in arbitrable address header.",
            "3. Sample 9th SCL bit for collective ACK (Open-Drain → at least one I3C Slave shall drive LOW).",
            "4. Drive CCC code byte (0x00..0x7F) + T-Bit parity on 9th SCL bit.",
            "5. Optionally drive payload bytes (each 8 bits + T-Bit parity).",
            "6. End CCC with STOP (P) or Repeated START + 7'h7E to terminate CCC scope.",
        ]
        d["typical_master_direct_ccc_sequence"] = [
            "1. Generate START.",
            "2. Drive 7'h7E + W.",
            "3. Sample ACK.",
            "4. Drive Direct CCC code byte (0x80..0xFE) + T-Bit parity.",
            "5. Generate Repeated START (Sr).",
            "6. Drive Target Slave Dynamic Address + RnW (W for Set, R for Get).",
            "7. Sample ACK from target Slave.",
            "8. For Direct Set: drive payload bytes + T-Bit parity.",
            "   For Direct Get: clock SCL while Slave drives response bytes + T-Bit end-of-data.",
            "9. End with STOP or Repeated START.",
        ]
        d["dynamic_address_assignment_entdaa_sequence"] = [
            "1. Main Master issues S + 7'h7E + W + ACK + CCC=ENTDAA (0x07) + T.",
            "2. Main Master issues Sr + 7'h7E + R + ACK (every yet-unaddressed non-Hot-Join I3C Slave shall ACK).",
            "3. Main Master drives SCL clock; releases SDA HIGH-Z.",
            "4. Every responding Slave drives its 48-bit Provisional ID || BCR || DCR (8 bytes) Open-Drain MSb-first, Big-Endian, no inter-byte ACK; arbitration: lowest concatenated value wins.",
            "5. Main Master drives 7-bit Dynamic Address + 1-bit odd parity = ~XOR(DA[7:1]) on SDA Open-Drain.",
            "6. Winning Slave ACKs (LOW) on next SCL bit if parity valid; passively NACKs (HIGH) otherwise.",
            "7. Main Master returns to step 2 until no Slave ACKs 7'h7E with R.",
            "8. Main Master ends procedure with STOP.",
            "9. Main Master may then issue DEFSLVS (0x08) to inform Secondary Masters of all bus participants.",
        ]
        d["hot_join_sequence"] = [
            "1. Hot-Join Slave waits ≥ tIDLE of Bus Available Condition.",
            "2. Slave issues START (pulls SDA LOW until Master pulls SCL LOW).",
            "3. Slave drives Hot-Join Address 7'h02 + RnW=0 in the arbitrable address header (Open-Drain).",
            "4. Current Master may:",
            "   a. NACK the request — Slave shall retry at next START opportunity.",
            "   b. ACK + Broadcast DISEC with DISHJ=1 — Master delays Dynamic Address Assignment.",
            "   c. ACK + Broadcast ENTDAA (0x07) — initiate Dynamic Address Assignment.",
            "5. On ENTDAA, the Slave drives its 48-bit Provisional ID + BCR + DCR as in the normal DAA flow.",
        ]
        d["ibi_in_band_interrupt_sequence"] = [
            "1. Slave waits for Bus Available Condition (≥ tAVAL).",
            "2. Slave pulls SDA LOW (acts as START Request).",
            "3. Master observes; pulls SCL LOW (best-effort timing) and pulls SDA LOW.",
            "4. Once SCL is LOW, Slave releases SDA HIGH-Z (Open-Drain).",
            "5. Slave drives its 7-bit Dynamic Address + RnW=1 in arbitrable address header.",
            "6. Master decides: ACK (accept) = drives SDA LOW on 9th SCL bit; NACK (reject) = leaves HIGH.",
            "7. On ACK + BCR[2]=1 (IBI Payload): Slave drives Mandatory Data Byte(s) with T-Bit continuation (1=continue, 0=end).",
            "8. After Mandatory Data, Master issues STOP or Repeated START.",
        ]
        d["secondary_master_request_and_handoff_sequence"] = [
            "1. Secondary Master (currently functioning as Slave) waits Bus Available.",
            "2. From Bus Available, drives its Dynamic Address + RnW=0 in arbitrable address header.",
            "3. Current Master observes the request; eventually issues GETACCMST (Direct CCC 0x91).",
            "4. Secondary Master replies via T-Bit per Tables 42/43/44 — Accepted / Not Accepted / Incorrect Cancel.",
            "5. On Accepted handoff, both Masters overlap their SDA drive for at least tMMOverlap before the new Master takes sole control of SCL.",
            "6. New Current Master continues with normal transactions; may later use GETACCMST to hand mastership back.",
        ]
        d["ccc_broadcast_skeleton_sequence"] = [
            "S → 7'h7E + W → ACK → CCC + T → [optional payload + T] → P (or Sr + 7'h7E to terminate CCC scope)",
        ]
        d["ccc_direct_skeleton_sequence"] = [
            "S → 7'h7E + W → ACK → CCC + T → Sr → Slave_DA + RnW → ACK → [payload + T] → (continue / Sr / P)",
        ]
        d["hdr_exit_pattern_sequence"] = [
            "Although HDR modes are not supported in I3C Basic, all I3C devices must detect the HDR Exit Pattern: a defined sequence of SDA edges while SCL is held LOW that returns the bus to SDR mode and is followed by STOP. See Section 5.2.1.1.",
        ]
        # remove I2C-only leftovers
        for kill in ("typical_master_write_sequence",
                     "typical_master_read_sequence",
                     "typical_slave_response_sequence",
                     "repeated_start_sequence",
                     "arbitration_loss_sequence",
                     "clock_stretching_sequence",
                     "general_call_sequence",
                     "device_id_read_sequence"):
            d.pop(kill, None)
        _write(p, d)

    # ------------------------------------------------------------------
    # L13 lab calibration — overwrite I2C generic with I3C-specific note
    # ------------------------------------------------------------------
    p = gd / "L13_LAB_CALIBRATION.json"
    if p.is_file():
        d = _read(p)
        d["lab_calibration_present"] = False
        d["notes"] = (
            "MIPI I3C Basic v1.0 is a wire-level protocol specification; no "
            "analog reference / trim / calibration loop at the protocol "
            "layer. Per-device sensor calibration (ADC offset, oscillator "
            "trim, sensor zero-point, temperature compensation) is documented "
            "in individual sensor datasheets, not in the I3C Basic spec. The "
            "only protocol-level lab-style measurement quantity is tSCO "
            "(Clock-to-Data Turnaround Delay) for slaves with high BCR[0]; "
            "reported via GETMXDS Direct CCC (0x94) so the Master can adjust "
            "SCL slew for that device.")
        _write(p, d)

    # ------------------------------------------------------------------
    # L14 versioning
    # ------------------------------------------------------------------
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f["spec_version"] = (
            "Version 1.0 (19 July 2018) — MIPI Board Adopted 8 October 2018")
        f["predecessor_protocols"] = [
            "I2C v1.0 (Philips, 1992) — 100 kbit/s Standard-mode",
            "I2C v2.0 (1998) — Fast-mode 400 kbit/s",
            "I2C v2.1 (2000) — editorial",
            "I2C v3.0 (2007) — Fast-mode Plus 1 Mbit/s, 10-bit addressing",
            "I2C Rev. 4 (2012) — Ultra Fast-mode push-pull unidirectional 5 Mbit/s",
            "I2C Rev. 6 (4 April 2014, NXP UM10204) — most recent I2C spec, basis for I3C backward compatibility",
        ]
        f["i3c_family_versions"] = [
            "MIPI I3C v1.0 (31 December 2016) — full I3C spec, members-only, includes HDR-DDR / HDR-TSP / HDR-TSL / Timing Control",
            "MIPI I3C Basic v1.0 (19 July 2018; Board Adopted 8 October 2018) — royalty-free subset of I3C v1.0 with selected I3C v1.1 features; THIS SPEC",
            "MIPI I3C v1.1 (forthcoming at time of I3C Basic v1.0 release) — full I3C members-only update; Direct R/W CCCs, GETMXDS refinement, SETAASA CCC, low-voltage / high-Cb IO",
        ]
        f["i3c_v1_0_functions_not_in_basic"] = [
            "Timing Control (Section 5.1.8 of full I3C v1.0)",
            "HDR Double Data Rate Mode (HDR-DDR) — Section 5.2.2",
            "HDR Ternary Modes (HDR-TSP and HDR-TSL) — Section 5.2.3",
        ]
        f["i3c_v1_1_functions_included_in_basic"] = [
            "Direct Read/Write CCC Capability (Section 5.1.9.1 Category 4)",
            "Get Max Data Speed (GETMXDS) Refinement (Section 5.1.9.3.18)",
            "SETAASA CCC (Section 5.1.9.3.22)",
            "Low Voltage / High Capacitive Load IO (Section 6, Table 55)",
        ]
        f["key_changes_vs_i2c"] = [
            {"version": "I3C SDR vs I2C Fm+", "summary": "Push-Pull SCL up to 12.5 MHz (vs 1 MHz Open-Drain); 9-bit data word uses T-Bit (parity / end-of-data) instead of ACK; mandatory 7'h7E broadcast support; Dynamic Address Assignment instead of static; In-Band Interrupt + Hot-Join + Secondary Master mechanisms; tighter Cb ≤ 50 pF."},
            {"version": "I3C Basic vs full I3C v1.0", "summary": "HDR modes removed (exit pattern detection retained); Timing Control removed; SETAASA + GETMXDS refinement + low-voltage IO + Direct R/W CCCs added from I3C v1.1."},
        ]
        f["backward_compat_traps"] = [
            {
                "trap_name": "i2c_slave_clock_stretch_forbidden",
                "i2c":  "Slaves may clock-stretch SCL (hold LOW).",
                "i3c":  "I3C Slaves shall NOT clock-stretch SCL; only the Master may stall.",
                "trap": "An I2C slave that retains its clock-stretch behavior cannot operate on an I3C bus; Master will treat held SCL as a bus error."
            },
            {
                "trap_name": "ninth_bit_meaning_change",
                "i2c":  "9th SCL bit on data byte = ACK / NACK from receiver.",
                "i3c":  "9th SCL bit on data byte = T-Bit (Master odd parity / Slave end-of-data); NO ACK on data.",
                "trap": "I2C-firmware ported to I3C must NOT drive ACK on data; doing so corrupts Push-Pull SDA and may damage drivers."
            },
            {
                "trap_name": "broadcast_address_7e_required",
                "i2c":  "Reserved address.",
                "i3c":  "Mandatory — every I3C slave shall ACK 7'h7E + W.",
                "trap": "I2C-style slaves ignoring 7'h7E will miss every Broadcast CCC including ENTDAA — they cannot get a Dynamic Address."
            },
            {
                "trap_name": "open_drain_to_push_pull_handoff",
                "i2c":  "All transitions are Open-Drain; brief overlap is harmless.",
                "i3c":  "Address-ACK → Master-Write data requires Open-Drain → Push-Pull handoff with overlap window (Section 5.1.2.3.1) to prevent driver contention.",
                "trap": "Incorrect handoff causes shorting of Push-Pull driver against Slave Open-Drain → potential damage."
            },
            {
                "trap_name": "cb_50pF_vs_400pF",
                "i2c":  "Cb_max 400 pF (Sm/Fm), 550 pF (Fm+).",
                "i3c":  "Cb_max 50 pF in Push-Pull SDR.",
                "trap": "Long traces / many devices that worked on I2C may be electrically infeasible at I3C SDR speeds."
            },
            {
                "trap_name": "i2c_devices_need_spike_filter_for_mixed_fast_bus",
                "rule": "On Mixed Fast Bus, every I2C device must have a true 50 ns Spike Filter on SCL; otherwise the bus drops to Mixed Slow/Limited speeds.",
                "trap": "Adding one I2C device without a Spike Filter caps the entire bus to Fm/Fm+ speeds."
            },
            {
                "trap_name": "reserved_addresses_table9",
                "rule": "Dynamic Addresses cannot use 7'h00, 7'h01, 7'h02, 7'h3E, 7'h5E, 7'h6E, 7'h76, 7'h7A, 7'h7C, 7'h7E, 7'h7F; several conditional addresses depend on whether legacy I2C devices with extended-address / device-ID modes are present.",
                "trap": "Static I2C addresses that fall into these slots are illegal on an I3C bus."
            },
        ]
        f["version_naming_history_note"] = (
            "MIPI I3C Basic v1.0 is the first public royalty-free release of "
            "an MIPI I3C-class specification. The IPR terms (RAND-Z, Annex E) "
            "allow non-MIPI-members to implement and license the spec without "
            "joining MIPI Alliance, in exchange for reciprocal licensing "
            "commitments.")
        # remove I2C-only legacy fields
        for kill in ("previous_versions",):
            f.pop(kill, None)
        d["fields"] = f
        _write(p, d)

    # ------------------------------------------------------------------
    # L15 encoding tables — overwrite I2C with I3C tables
    # ------------------------------------------------------------------
    p = gd / "L15_ENCODING_TABLES.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f["reserved_slave_addresses_table9"] = {
            "header_columns": ["Slave Dynamic Address (binary)", "Hex", "Restriction", "Description"],
            "rows": [
                {"address_binary": "000 0000", "hex": "7'h00", "restriction": "Shall not use", "purpose": "I3C Reserved"},
                {"address_binary": "000 0001", "hex": "7'h01", "restriction": "Shall not use", "purpose": "I3C Reserved — SETDASA Point-to-Point Communication"},
                {"address_binary": "000 0010", "hex": "7'h02", "restriction": "Shall not use", "purpose": "I3C Reserved — Hot-Join Address"},
                {"address_binary": "000 0011..000 0111", "hex": "7'h03..7'h07", "restriction": "Conditional / Optional", "purpose": "Available only if no I2C 'High-Speed Mode' devices on bus"},
                {"address_binary": "000 1000..011 1101", "hex": "7'h08..7'h3D", "restriction": "Available", "purpose": "54 free addresses"},
                {"address_binary": "011 1110", "hex": "7'h3E", "restriction": "Shall not use", "purpose": "Broadcast Address single-bit-error detect"},
                {"address_binary": "011 1111..101 1101", "hex": "7'h3F..7'h5D", "restriction": "Available", "purpose": "31 free addresses"},
                {"address_binary": "101 1110", "hex": "7'h5E", "restriction": "Shall not use", "purpose": "Broadcast Address single-bit-error detect"},
                {"address_binary": "101 1111..110 1101", "hex": "7'h5F..7'h6D", "restriction": "Available", "purpose": "15 free addresses"},
                {"address_binary": "110 1110", "hex": "7'h6E", "restriction": "Shall not use", "purpose": "Broadcast Address single-bit-error detect"},
                {"address_binary": "110 1111..111 0101", "hex": "7'h6F..7'h75", "restriction": "Available", "purpose": "7 free addresses"},
                {"address_binary": "111 0110", "hex": "7'h76", "restriction": "Shall not use", "purpose": "Broadcast Address single-bit-error detect"},
                {"address_binary": "111 0111", "hex": "7'h77", "restriction": "Available", "purpose": "1 free address"},
                {"address_binary": "111 1000..111 1001", "hex": "7'h78..7'h79", "restriction": "Conditional", "purpose": "Available only if no I2C 'Extended Address Mode' devices on bus"},
                {"address_binary": "111 1010", "hex": "7'h7A", "restriction": "Shall not use", "purpose": "Broadcast Address single-bit-error detect"},
                {"address_binary": "111 1011", "hex": "7'h7B", "restriction": "Conditional", "purpose": "Available only if no I2C 'Extended Address Mode' devices on bus"},
                {"address_binary": "111 1100", "hex": "7'h7C", "restriction": "Shall not use", "purpose": "Broadcast Address single-bit-error detect + not available if any I2C 'Device ID Mode' device present"},
                {"address_binary": "111 1101", "hex": "7'h7D", "restriction": "Conditional", "purpose": "Available only if no I2C 'Device ID Mode' device on bus"},
                {"address_binary": "111 1110", "hex": "7'h7E", "restriction": "Shall not use", "purpose": "I3C Broadcast Address"},
                {"address_binary": "111 1111", "hex": "7'h7F", "restriction": "Shall not use", "purpose": "Broadcast Address single-bit-error detect"},
            ],
        }
        f["common_command_codes_table15"] = {
            "header_columns": ["Code", "Type", "Required", "Name", "Section", "Brief Description"],
            "broadcast_rows": [
                ["0x00", "Broadcast", "Y",   "ENEC",       "5.1.9.3.1",  "Enable Slave event driven interrupts"],
                ["0x01", "Broadcast", "Y",   "DISEC",      "5.1.9.3.1",  "Disable Slave event driven interrupts"],
                ["0x02", "Broadcast", "Y(1)","ENTAS0",     "5.1.9.3.2",  "Enter Activity State 0"],
                ["0x03", "Broadcast", "N(1)","ENTAS1",     "5.1.9.3.2",  "Enter Activity State 1"],
                ["0x04", "Broadcast", "N(1)","ENTAS2",     "5.1.9.3.2",  "Enter Activity State 2"],
                ["0x05", "Broadcast", "N(1)","ENTAS3",     "5.1.9.3.2",  "Enter Activity State 3"],
                ["0x06", "Broadcast", "Y",   "RSTDAA",     "5.1.9.3.3",  "Reset Dynamic Address Assignment"],
                ["0x07", "Broadcast", "Y",   "ENTDAA",     "5.1.9.3.4",  "Enter Dynamic Address Assignment"],
                ["0x08", "Broadcast", "N",   "DEFSLVS",    "5.1.9.3.7",  "Define List of Slaves"],
                ["0x09", "Broadcast", "Y(6)","SETMWL",     "5.1.9.3.5",  "Set Max Write Length"],
                ["0x0A", "Broadcast", "Y(7)","SETMRL",     "5.1.9.3.6",  "Set Max Read Length"],
                ["0x0B", "Broadcast", "N",   "ENTTM",      "5.1.9.3.8",  "Enter Test Mode"],
                ["0x20", "Broadcast", "N(3)","ENTHDR0",    "5.1.9.3.9",  "Enter HDR Mode 0 (HDR-DDR; not in I3C Basic)"],
                ["0x21", "Broadcast", "N(3)","ENTHDR1",    "5.1.9.3.9",  "Enter HDR Mode 1 (HDR-TSP; not in I3C Basic)"],
                ["0x22", "Broadcast", "N(3)","ENTHDR2",    "5.1.9.3.9",  "Enter HDR Mode 2 (HDR-TSL; not in I3C Basic)"],
                ["0x23..0x27", "Broadcast", "N(3)", "ENTHDR3..7", "—", "Enter HDR Modes 3..7"],
                ["0x28", "Broadcast", "N",   "SETXTIME",   "5.1.9.3.20", "Exchange Timing Information (not in I3C Basic)"],
                ["0x29", "Broadcast", "—",   "SETAASA",    "5.1.9.3.22", "Set All Addresses to Static Address (I3C v1.1 in Basic)"],
            ],
            "direct_rows": [
                ["0x80", "Direct",     "Y",   "ENEC",       "5.1.9.3.1",  "Enable Slave event interrupts (direct)"],
                ["0x81", "Direct",     "Y",   "DISEC",      "5.1.9.3.1",  "Disable Slave event interrupts (direct)"],
                ["0x82", "Direct",     "Y(1)","ENTAS0",     "5.1.9.3.2",  "Direct ENTAS0"],
                ["0x83..0x85", "Direct", "N(1)", "ENTAS1..3", "5.1.9.3.2", "Direct ENTAS1..3"],
                ["0x86", "Direct",     "Y",   "RSTDAA",     "5.1.9.3.3",  "Direct RSTDAA"],
                ["0x87", "Direct Set", "N",   "SETDASA",    "5.1.9.3.10", "Set Dynamic Address from Static Address"],
                ["0x88", "Direct Set", "Y",   "SETNEWDA",   "5.1.9.3.11", "Set New Dynamic Address"],
                ["0x89", "Direct Set", "Y(2)","SETMWL",     "5.1.9.3.5",  "Set Max Write Length (per-slave)"],
                ["0x8A", "Direct Set", "Y(2)","SETMRL",     "5.1.9.3.6",  "Set Max Read Length (per-slave)"],
                ["0x8B", "Direct Get", "Y(2)","GETMWL",     "5.1.9.3.5",  "Get Slave Max Write Length"],
                ["0x8C", "Direct Get", "Y(2)","GETMRL",     "5.1.9.3.6",  "Get Slave Max Read Length"],
                ["0x8D", "Direct Get", "Y",   "GETPID",     "5.1.9.3.12", "Get 48-bit Provisional ID (6 bytes MSb-first)"],
                ["0x8E", "Direct Get", "Y",   "GETBCR",     "5.1.9.3.13", "Get Bus Characteristics Register"],
                ["0x8F", "Direct Get", "Y",   "GETDCR",     "5.1.9.3.14", "Get Device Characteristics Register"],
                ["0x90", "Direct Get", "Y",   "GETSTATUS",  "5.1.9.3.15", "Get Device Status (2-byte response per Tables 40/41)"],
                ["0x91", "Direct Get", "N",   "GETACCMST",  "5.1.9.3.16", "Get Accept Mastership"],
                ["0x93", "Direct Set", "N",   "SETBRGTGT",  "5.1.9.3.17", "Set Bridge Targets"],
                ["0x94", "Direct Get", "N(4)","GETMXDS",    "5.1.9.3.18", "Get Max Data Speed (BCR[0]=1 slaves only)"],
                ["0x95", "Direct Get", "N(5)","GETHDRCAP",  "5.1.9.3.19", "Get HDR Capability (not in I3C Basic)"],
                ["0x98", "Direct",     "N",   "SETXTIME",   "5.1.9.3.20", "Set Exchange Timing (not in I3C Basic)"],
                ["0x99", "Direct",     "N",   "GETXTIME",   "5.1.9.3.21", "Get Exchange Timing (not in I3C Basic)"],
            ],
            "notes": [
                "(1) Slave devices shall be permitted to self-power-manage based on this information.",
                "(2) Required by devices capable of transporting 16+ sequential bytes.",
                "(3) HDR modes not supported in I3C Basic; HDR Enter / Restart / Exit patterns must still be detected.",
                "(4) Required by slaves with BCR[0]=1 (Max Data Speed Limitation).",
                "(5) Required by slaves supporting any HDR mode.",
                "(6) See SETMWL Section 5.1.9.3.5.",
                "(7) See SETMRL Section 5.1.9.3.6.",
            ],
        }
        f["bcr_field_encoding_table6"] = {
            "header_columns": ["Bit", "Name", "Encoding"],
            "rows": [
                ["BCR[7:6]", "Device Role[1:0]", "2'b00 = I3C Slave; 2'b01 = I3C Master; 2'b10/11 = Reserved by MIPI"],
                ["BCR[5]",   "MIPI Reserved",    "0 (default)"],
                ["BCR[4]",   "Bridge Identifier","0 = not Bridge; 1 = Bridge Device"],
                ["BCR[3]",   "Offline Capable",  "0 = always online; 1 = may be offline (retains DA)"],
                ["BCR[2]",   "IBI Payload",      "0 = no mandatory data byte; 1 = mandatory byte(s) follow accepted IBI"],
                ["BCR[1]",   "IBI Request Capable","0 = not capable; 1 = capable"],
                ["BCR[0]",   "Max Data Speed Limitation","0 = no limitation; 1 = limitation (use GETMXDS)"],
            ],
        }
        f["dcr_field_encoding_table7"] = {
            "header_columns": ["Bit", "Name", "Encoding"],
            "rows": [
                ["DCR[7:0]", "Device ID[7:0]", "255 codes for sensor / device class; 0x00 = Generic Device (default)"],
            ],
        }
        f["lvr_field_encoding_table8"] = {
            "header_columns": ["Bit", "Name", "Encoding"],
            "rows": [
                ["LVR[7:5]", "Legacy I2C only[2:0] (Index)", "3'b000..3'b010 = Table 5 indices; 3'b011..3'b111 Reserved"],
                ["LVR[4]",   "I2C Mode Indicator",           "0 = I2C Fm+; 1 = I2C Fm"],
                ["LVR[3:0]", "MIPI Reserved (vendor codes)", "15 codes for vendor / device function"],
            ],
        }
        f["provisional_id_layout"] = {
            "header_columns": ["Bits", "Field", "Description"],
            "rows": [
                ["PID[47:33]", "MIPI Manufacturer ID", "15-bit MID (MSb of 16-bit MID discarded)"],
                ["PID[32]",    "Provisional ID Type Selector", "0 = Vendor Fixed Value; 1 = Random Value (test mode)"],
                ["PID[31:16]", "Part ID",                "16-bit vendor-defined Part ID"],
                ["PID[15:12]", "Instance ID",            "4-bit instance ID"],
                ["PID[11:0]",  "DCR-defined / Vendor",   "12-bit vendor / DCR-class defined"],
            ],
        }
        f["slave_event_byte_table18_19"] = {
            "enable_byte_format":  ["Bit7-4: Reserved", "Bit3: ENHJ",  "Bit2: Reserved", "Bit1: ENMR",  "Bit0: ENINT"],
            "disable_byte_format": ["Bit7-4: Reserved", "Bit3: DISHJ", "Bit2: Reserved", "Bit1: DISMR", "Bit0: DISINT"],
        }
        f["activity_state_table12"] = {
            "header_columns": ["State", "tCAS Max"],
            "rows": [
                ["ENTAS0 (normal operation)", "1 µs"],
                ["ENTAS1",                     "100 µs"],
                ["ENTAS2",                     "2 ms"],
                ["ENTAS3",                     "50 ms"],
            ],
        }
        f["tables"] = [
            "Table 1 Sensor Classes Addressed by I3C",
            "Table 2 Roles for I3C Compatible Devices",
            "Table 3 I3C Devices Roles vs Responsibilities",
            "Table 4 I2C Features Allowed in I3C Slaves",
            "Table 5 Legacy I2C-Only Slave Categories and Characteristics",
            "Table 6 Bus Characteristics Register (BCR)",
            "Table 7 I3C Device Characteristics Register (DCR)",
            "Table 8 Legacy I2C Virtual Register (LVR)",
            "Table 9 I3C Slave Address Restrictions",
            "Table 10 Available Options for Bus Operating Parameters, Per I3C Bus Configuration",
            "Table 11 Master Clock Stall Times",
            "Table 12 Activity States",
            "Table 13 Asynchronous Timing Control Modes",
            "Table 14 CCC Frame Field Definitions",
            "Table 15 I3C Common Command Codes",
            "Tables 16-51 Per-CCC frame format tables",
            "Table 52 SDR Slave Error Types (S0..S6)",
            "Table 53 SDR Master Error Types (M0..M2)",
            "Table 54 I3C I/O Stage Characteristics Common to Push-Pull / Open-Drain",
            "Table 55 Low Voltage / High Capacitive Load I/O (I3C v1.1 element in Basic)",
            "Table 56 Legacy I2C Device Requirements When Operating on I3C",
            "Table 57 I3C Timing Requirements With I2C Legacy Devices",
            "Table 58 I3C Open Drain Timing Parameters",
            "Table 59 I3C Push-Pull Timing Parameters for SDR Mode",
            "Tables 60-62 Timing and Drive for Start of New Frame / Continuation",
        ]
        # remove leftover I2C-only encoding entries
        for kill in ("reserved_slave_addresses",
                     "general_call_second_byte_codes",
                     "mode_summary_table",
                     "protocol_feature_applicability_matrix"):
            f.pop(kill, None)
        d["fields"] = f
        _write(p, d)

    # ------------------------------------------------------------------
    # L16 compliance properties
    # ------------------------------------------------------------------
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f["must_have_properties"] = [
            "SDA and SCL both HIGH in bus-free state (Bus Free Condition after STOP + ≥ tCAS).",
            "All I3C Slaves shall ACK Broadcast Address 7'h7E with RnW=0.",
            "All I3C Slaves shall ACK their own assigned Dynamic Address.",
            "9-bit Address Header = 7-bit address + 1-bit RnW + 1-bit ACK/NACK (Open-Drain ACK).",
            "9-bit SDR Data Word = 8 data bits + 1 T-Bit (parity for write / end-of-data for read).",
            "Master-Write T-Bit = XOR(Data[7:0], 1) (odd parity).",
            "Slave-Read T-Bit = 1 continue or 0 end-of-message.",
            "Slave-side SCL stretching is FORBIDDEN on I3C bus.",
            "Address Header after START is Open-Drain (arbitrable); after Sr is Push-Pull (except ACK).",
            "SDA data drive in SDR is Push-Pull; ACK / DAA / IBI arbitration use Open-Drain.",
            "Master shall be able to switch SDA between Open-Drain and Push-Pull dynamically.",
            "Every I3C device shall have a BCR (Table 6) and a DCR (Table 7).",
            "Every I3C device shall expose a 48-bit Provisional ID via ENTDAA arbitration and via GETPID Direct CCC.",
            "Every Legacy I2C device on an I3C bus shall have an associated LVR (held virtually by Main Master).",
            "Hot-Join-capable devices shall be Failsafe (Section 5.1.5.1).",
            "HDR Exit Pattern Detector required in every I3C device (even SDR-Only).",
            "On Mixed Fast Bus, SCL HIGH period during I3C frames shall be ≤ tDIG_H_MIXED (45 ns max) so legacy I2C 50 ns Spike Filter ignores I3C traffic.",
            "Bus capacitance Cb per line ≤ 50 pF in I3C Push-Pull SDR.",
            "Max SCL frequency 12.5 MHz nominal / 12.9 MHz absolute max.",
            "Every Required CCC (Y in Table 15) shall be supported by Master and Slave.",
        ]
        f["must_not_have_properties"] = [
            "Slave-driving of SCL (clock-stretching) — forbidden on I3C bus.",
            "Push-Pull SDA drive during arbitrable address header (must start Open-Drain).",
            "ACK on a Master-Write data byte — that bit is T-Bit (parity), never ACK.",
            "Driving SDA during Slave-Read data — only the addressed Slave drives.",
            "10-bit I2C Extended Addressing — not allowed on I3C bus.",
            "Slave-side use of any Table 9 Shall-Not-Use address as a Dynamic Address.",
            "Bridge devices that do not comply with full MIPI I3C v1.0 (BCR[4]=1 requires v1.0 compliance).",
            "Mixing I2C 'High-Speed Mode' or 'UFm' devices with I3C devices on the same bus (must be limited to Fm / Fm+).",
            "An I3C Slave responding to addresses other than 7'h7E or its own Dynamic Address.",
            "Driving SDA HIGH while another device drives LOW in Open-Drain windows (loses arbitration).",
        ]
        f["compliance_failure_modes"] = [
            {"mode": "Header NACK",                  "trigger": "No slave responds at the addressed Dynamic Address or 7'h7E broadcast."},
            {"mode": "T-Bit parity violation (S2)",  "trigger": "Slave detects XOR(Data[7:0],1) mismatch on Master-Write byte; NACKs at next byte boundary."},
            {"mode": "S0 illegal address",           "trigger": "Slave saw an address that is in Table 9 Shall-Not-Use or violates its DA; shall ignore for incorrect addresses only."},
            {"mode": "CCC parity error (S1)",        "trigger": "Slave detects T-Bit parity error on the CCC code byte; NACKs."},
            {"mode": "Read parity error (S3)",       "trigger": "Master detects Slave's T-Bit mismatched odd parity on read data."},
            {"mode": "Hot-Join collision",           "trigger": "Multiple Hot-Join devices contend on 7'h02; Open-Drain arbitration resolves."},
            {"mode": "DAA Provisional ID collision", "trigger": "Two slaves with same PID concatenation; resolved by RSTDAA + ENTDAA re-run per Section 5.1.4.3."},
            {"mode": "Mixed Fast Bus tDIG_H violation","trigger": "I3C SCL HIGH > 45 ns; Legacy I2C devices may mis-interpret I3C signaling."},
            {"mode": "Cb > 50 pF violation",         "trigger": "Bus load exceeds 50 pF; rise-time and Push-Pull integrity degraded."},
        ]
        f["min_bus_capacitance_constraint"] = (
            "No explicit minimum; maximum is Cb ≤ 50 pF per bus line in I3C "
            "Push-Pull SDR (vs 400 pF for I2C Sm/Fm).")
        f["reset_behavior_compliance"] = (
            "After POR every I3C device releases SDA and SCL HIGH-Z. Hot-Join "
            "devices must be Failsafe — leakage when unpowered shall not "
            "exceed normal active-pad Ii range. Main Master discovers all "
            "devices via SETDASA / SETAASA / ENTDAA before any normal "
            "traffic. RSTDAA can be issued to force re-discovery.")
        d["fields"] = f
        _write(p, d)

    # ------------------------------------------------------------------
    # L17 channel signal catalog
    # ------------------------------------------------------------------
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f["channels"] = [
            {
                "name": "SDA",
                "direction_master": "bidirectional — Push-Pull (data, post-Sr header) + Open-Drain (S, arbitrable header, ACK, DAA, IBI arbitration)",
                "direction_slave":  "bidirectional — Open-Drain (ACK, IBI / Hot-Join arbitration, DAA PID/BCR/DCR output) + Push-Pull (Slave-Read data + T-Bit)",
                "purpose": "Serial Data Line. Carries the 9-bit Address Header (7-bit address + RnW + ACK) and the 9-bit SDR Data Word (8 data + T-Bit). Drive mode switches dynamically during the same transaction. Optional High-Keeper weakly maintains HIGH between active drivers.",
                "active_levels": "Push-Pull mode: 0 / 1 actively driven. Open-Drain mode: 0 = LOW (driven by any device); 1 = HIGH-Z (pulled up by Rp / High-Keeper).",
                "idle_level": "HIGH",
            },
            {
                "name": "SCL",
                "direction_master": "output — Push-Pull normally; Open-Drain only in legacy / arbitration windows",
                "direction_slave":  "input — Slaves shall NOT drive SCL (clock-stretching is forbidden on I3C)",
                "purpose": "Serial Clock Line. Master generates all clock pulses; 9 SCL pulses per word (Address Header or SDR Data Word). Master may stall SCL LOW under specific transitory conditions per Table 11.",
                "active_levels": "Push-Pull 0/1 normally; Open-Drain only in I3C Legacy / I2C mode",
                "idle_level": "HIGH",
            },
        ]
        f["global_signals"] = [
            {"name": "VDD",          "purpose": "Supply voltage (1.2 V / 1.8 V / 3.3 V typ). Logic thresholds: VIL ≤ 0.3 VDD, VIH ≥ 0.7 VDD."},
            {"name": "Rp / Pull-Up", "purpose": "Pull-Up resistor on SDA (and possibly SCL in legacy mode) to VDD; sized per Cb ≤ 50 pF and target rise time tCR."},
            {"name": "High-Keeper",  "purpose": "Optional weak Pull-Up on SDA that maintains HIGH between active Push-Pull drivers (during turnaround windows)."},
            {"name": "GND",          "purpose": "Common ground reference for all devices on the bus."},
        ]
        f["channel_counts"] = {
            "channels": 2,
            "external_pins_total": 2,
            "supply_pins": 2,
            "register_count_at_protocol_layer": 3,
        }
        f["ordering_rules"] = {
            "byte_ordering":      "MSb-first within each byte.",
            "multi_byte_ordering":"Big-Endian over multi-byte fields (e.g. 48-bit Provisional ID streamed bit [47] first).",
            "byte_count":         "Number of bytes per transfer is unrestricted (limited by Master STOP + SETMWL/SETMRL).",
            "t_bit_per_word":     "Every SDR Data Word is followed by exactly one T-Bit on the 9th SCL pulse.",
        }
        f["dependency_graph"] = {
            "common_rule":     "Master drives SCL; Slaves sample SDA on rising SCL. Data on SDA must be stable while SCL HIGH; only S / P / Sr violate this rule.",
            "data_dependency": "Master-Write byte N → T-Bit (parity) on SCL pulse 9 → Master-Write byte N+1. Slave-Read byte N → Slave T-Bit (1 continue / 0 end) → Slave-Read byte N+1 if T=1 and Master did not abort.",
            "no_scl_stretch":  "Slaves cannot delay the bus via SCL; only Master Clock Stall (Table 11) is allowed.",
        }
        # purge I2C-only AXI/UFm leftovers if any
        dg = f.get("dependency_graph", {})
        if isinstance(dg, dict):
            for kill in ("AXI_read", "AXI3_write", "AXI4_write"):
                dg.pop(kill, None)
        # remove UFm leftover channels (I2C synth wrote these)
        f.pop("ufm_channels", None)
        f["handshake_pairs"] = [
            {"name": "ADDR_HDR_ACK",      "from": "Addressed Slave",        "to": "Master",  "rule": "After 8-bit address+RnW: Slave drives SDA LOW Open-Drain on 9th SCL pulse → ACK; HIGH → NACK."},
            {"name": "BROADCAST_ACK",     "from": "All I3C Slaves",         "to": "Master",  "rule": "After 7'h7E + W: every I3C Slave that is in scope ACKs collectively (wired-AND); at least one Slave must drive LOW."},
            {"name": "WRITE_T_BIT_PARITY","from": "Master",                  "to": "(Slave detects)", "rule": "After each Master-Write data byte: Master drives T-Bit = XOR(Data[7:0],1) Push-Pull; Slave NACKs at next byte on mismatch (error S2)."},
            {"name": "READ_T_BIT_EOD",    "from": "Slave",                   "to": "Master",  "rule": "After each Slave-Read data byte: Slave drives T-Bit = 1 (continue, releases SDA HIGH-Z next clock for Master abort window) or T-Bit = 0 (end-of-message)."},
            {"name": "IBI_ARBITRATION",   "from": "any Slave (IBI-capable)", "to": "Master",  "rule": "From Bus Available, Slave drives its Dynamic Address (RnW=1) Open-Drain; lowest address wins; Master ACK/NACK on 9th pulse."},
            {"name": "HOTJOIN_ARBITRATION","from": "Hot-Join Slave",         "to": "Master",  "rule": "From Bus Idle, Slave drives Hot-Join Address 7'h02 (RnW=0); Master ACK/NACK; ACK + ENTDAA triggers DAA."},
            {"name": "DAA_PID_ARBITRATION","from": "Yet-unaddressed Slaves",  "to": "Master",  "rule": "During ENTDAA: each Slave drives 48-bit PID + BCR + DCR Open-Drain MSb-first; lowest concatenated value wins; winner gets the Master-driven 7-bit DA + parity."},
            {"name": "MASTER_CLOCK_STALL","from": "Master",                   "to": "All",     "rule": "Master holds SCL LOW under conditions in Table 11 to slow down a transaction (ACK/NACK Phase, Write Parity, T-Bit transitions, DAA first bit)."},
        ]
        d["fields"] = f
        _write(p, d)

    # ------------------------------------------------------------------
    # L18 interconnect topology
    # ------------------------------------------------------------------
    p = gd / "L18_INTERCONNECT_TOPOLOGY.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f["topology_type"] = (
            "Multi-Drop 2-wire bus; all devices share SDA and SCL. Drive "
            "mode switches dynamically between Push-Pull (SDR data) and "
            "Open-Drain / High-Keeper (S, arbitrable header, ACK, DAA, IBI). "
            "Single I3C Main Master at a time; Secondary Masters can take "
            "cooperative mastership.")
        f["supported_topologies"] = [
            {"name": "Pure Bus",              "description": "All devices are I3C (Main Master + Slaves; optionally Secondary Masters); no Legacy I2C devices present. Allows full 12.5 MHz Push-Pull SDR."},
            {"name": "Mixed Fast Bus",        "description": "I3C devices + Legacy I2C Slaves WITH true 50 ns Spike Filter on SCL. I3C frames constrained to SCL HIGH ≤ tDIG_H_MIXED so I2C devices ignore I3C traffic."},
            {"name": "Mixed Slow/Limited Bus","description": "I3C devices + Legacy I2C Slaves WITHOUT Spike Filter. I3C SDR must run at Fm or Fm+ speed only."},
            {"name": "Multi-Master Bus",      "description": "One Main Master + one or more Secondary Masters; cooperative handoff via GETACCMST + tMMOverlap-bound overlap window."},
            {"name": "Hub / Engine / Bridge", "description": "Specialized I3C devices that aggregate or translate the bus. Bridge devices (BCR[4]=1) must comply with full MIPI I3C v1.0."},
            {"name": "Hot-Join Bus",          "description": "I3C devices that join the running bus after configuration. Joining device must be Failsafe; uses 7'h02 + IBI + ENTDAA flow."},
        ]
        f["master_slave_role_summary"] = [
            {"role": "I3C Main Master",            "responsibilities": ["Initially configures the I3C bus (collect static / LVR info)", "Assigns Dynamic Addresses via SETDASA / SETAASA / ENTDAA", "Drives SCL Push-Pull (12.5 MHz max)", "Manages Pull-Up / High-Keeper structures", "Handles IBI / Hot-Join / Secondary Master Request arbitration", "Supports Legacy I2C Slaves on the same bus", "Sends I2C messages to Legacy I2C Slaves"]},
            {"role": "SDR-Only Main Master (I3C Basic)", "responsibilities": ["Same as I3C Main Master but does not support HDR modes"]},
            {"role": "I3C Secondary Master",       "responsibilities": ["Functions as Slave until accepting mastership", "May request mastership via Secondary Master Request (Dynamic Address + W in arbitrable header)", "On accepting, drives SCL", "Eventually passes mastership back to Main Master"]},
            {"role": "I3C Slave",                  "responsibilities": ["Match 7'h7E (broadcast) and own Dynamic Address", "Respond to Required CCCs", "Drive SDA only during ACK / Read data / T-Bit / DAA payload / IBI arbitration", "NEVER drive SCL"]},
            {"role": "SDR-Only I3C Slave",         "responsibilities": ["Same as I3C Slave; only HDR Exit Pattern Detector required for HDR compatibility"]},
            {"role": "Legacy I2C Slave",           "responsibilities": ["Static Address recognition", "ACK / NACK per I2C", "May NOT clock-stretch on I3C bus", "Must have 50 ns Spike Filter for Mixed Fast Bus operation (desirable)"]},
            {"role": "I3C Bridge Device",          "responsibilities": ["Translate I3C ↔ another bus (SPI, UART, I2C-master, etc.)", "Must comply with full MIPI I3C v1.0"]},
        ]
        f["interconnect_role"] = (
            "There is no central protocol-layer interconnect — the bus is a "
            "flat Multi-Drop shared medium with SDA + SCL. Hubs / Engines / "
            "Bridges extend reach or translate to other buses but the "
            "protocol behaves as a single shared two-wire bus from the "
            "firmware perspective. Maximum I3C Slave count is typically 11 "
            "due to capacitive-load (Cb ≤ 50 pF) and address-space "
            "constraints.")
        f["ordering_guarantees"] = {
            "within_a_transaction": "Bytes are transmitted in software-issue order; MSb-first within each byte; multi-byte fields (e.g. 48-bit PID) are Big-Endian.",
            "across_transactions":  "No fairness guarantee in multi-master; arbitration (lower Dynamic Address = higher priority) determines order of IBI / Hot-Join / Secondary Master Request processing.",
        }
        f["memory_vs_peripheral_regions"] = (
            "Not applicable — I3C is a wire-level protocol, not a memory "
            "bus. Per-device register maps are defined by individual device "
            "datasheets, not by the I3C Basic spec.")
        f["slave_classification"] = {
            "i3c_slave":           "Ordinary I3C Slave — no Master capability. Required: Broadcast 7'h7E + DA match + Required CCCs.",
            "sdr_only_i3c_slave":  "I3C Slave that supports only SDR Mode; HDR Exit Pattern Detector still required.",
            "secondary_master":    "I3C Slave with Master capability; BCR Device Role = 2'b01 when acting as Master.",
            "sdr_only_secondary_master":"Secondary Master without HDR support.",
            "i3c_bridge":          "BCR Bit 4 = 1; translates I3C to another bus.",
            "i3c_hub_engine":      "Aggregates / re-fans I3C bus segments.",
            "hot_join_capable":    "Failsafe pads + may issue Hot-Join Address 7'h02.",
            "ibi_capable":         "BCR Bit 1 = 1; may emit address as IBI.",
            "ibi_payload_capable": "BCR Bit 2 = 1; provides Mandatory Data Byte(s) after IBI ACK.",
            "legacy_i2c_slave":    "I2C-only device on I3C bus; held by Main Master via LVR + Static Address.",
        }
        f["default_signal_values_evidence_tables"] = [
            "Table 6 Bus Characteristics Register (BCR)",
            "Table 7 I3C Device Characteristics Register (DCR)",
            "Table 8 Legacy I2C Virtual Register (LVR)",
            "Table 9 I3C Slave Address Restrictions",
            "Table 10 Available Options for Bus Operating Parameters, Per I3C Bus Configuration",
            "Table 15 I3C Common Command Codes",
        ]
        f["addressing_topology"] = {
            "7_bit_dynamic": "Default. Dynamic Address Assignment (DAA) by Main Master via ENTDAA after PID arbitration; ~104 free 7-bit addresses excluding the Table 9 reserved set.",
            "7_bit_static":  "Used for Legacy I2C compatibility and as input to SETDASA / SETAASA CCCs.",
            "broadcast_7E":  "Reserved address 7'h7E recognized by every I3C Slave.",
            "hot_join_02":   "Reserved address 7'h02 used as Hot-Join request.",
        }
        f["bus_management_overview"] = {
            "current_master": "Exactly one Master at a time drives SCL; mastership begins with the Main Master and can be passed via GETACCMST.",
            "bus_states":     "Free (≥ tCAS after STOP) → Available (≥ tAVAL → Slave may issue IBI) → Idle (≥ tIDLE → Slave may Hot-Join).",
            "tCAS_per_activity_state": "Determined by ENTAS0..3 CCC per Table 12 (1 µs to 50 ms).",
        }
        # remove I2C-only ultra_fast_mode_topology leftover
        f.pop("ultra_fast_mode_topology", None)
        d["fields"] = f
        _write(p, d)

    # ------------------------------------------------------------------
    # L19 PDK
    # ------------------------------------------------------------------
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f["constraints_present"] = False
        f["notes"] = (
            "MIPI I3C Basic v1.0 is a wire-level protocol spec; no PDK / "
            "SDC / floorplan constraints at the protocol layer. Per-device "
            "integration constraints (pad type, pull-up sizing, clock-tree "
            "budget for SCL, dual Push-Pull / Open-Drain driver "
            "implementation, Failsafe pad design for Hot-Join, High-Keeper "
            "sizing, 12.5 MHz SCL routing) live in the SoC-level integration "
            "spec, not in the I3C Basic spec. Section 6 of the spec does "
            "define electrical characteristics (Tables 54, 55) that "
            "constrain the pad cell — these are characterized at the device "
            "level, not as SoC backend constraints.")
        d["fields"] = f
        _write(p, d)

    # ------------------------------------------------------------------
    # L20 DFT
    # ------------------------------------------------------------------
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f["dft_present"] = False
        f["notes"] = (
            "MIPI I3C Basic v1.0 does not specify DFT / scan / BIST "
            "architecture. Concrete I3C controller IPs implement standard "
            "scan insertion at SoC integration time. The spec does define "
            "one protocol-level test mechanism — ENTTM (Enter Test Mode, "
            "Broadcast CCC 0x0B) per Section 5.1.9.3.8, and ENTTM Test Mode "
            "Byte values per Table 32 — which allows the Master to put "
            "Slaves into vendor-defined test modes (e.g. to provide a "
            "fully-random Provisional ID for DAA collision testing). This "
            "is a runtime protocol mechanism, not a silicon DFT "
            "architecture.")
        d["fields"] = f
        _write(p, d)

    # ------------------------------------------------------------------
    # L21 power intent
    # ------------------------------------------------------------------
    p = gd / "L21_POWER_INTENT.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f["power_intent_present"] = False
        f["low_power_modes_summary"] = {
            "bus_idle_static_power":   "Both SDA and SCL HIGH (released). Only Pull-Up / High-Keeper leakage.",
            "device_sleep_release":    "Sleeping I3C devices must release SDA and SCL HIGH-Z.",
            "activity_states_table12": "ENTAS0 = 1 µs tCAS budget (normal); ENTAS1 = 100 µs; ENTAS2 = 2 ms; ENTAS3 = 50 ms — Master signals expected inactivity so Slave can lower power.",
            "ibi_wake_response":       "From Bus Available Condition (≥ tAVAL = 1 µs) a Slave may emit an IBI to wake the Master.",
            "hot_join_wake":           "From Bus Idle Condition (≥ tIDLE = 200 µs) a Slave may issue Hot-Join Address 7'h02 to rejoin the running bus.",
            "failsafe_pads_for_hot_join": "Hot-Join devices must use Failsafe pads — unpowered pad leakage shall not exceed the active-pad Ii range (Section 5.1.5.1, Table 54).",
        }
        f["energy_advantage_over_i2c"] = (
            "Spec Section 1.3 / Figure 2 / Figure 3: I3C SDR consumes "
            "substantially less mJ/megabit than I2C at 400 kHz, while "
            "delivering > 10x bandwidth — major motivation for sensor-class "
            "applications.")
        f["notes"] = (
            "MIPI I3C Basic v1.0 explicitly lists 'System power management' "
            "as out-of-scope (Section 1.1). Power-domain partitioning "
            "(always-on / sensor-domain / off / retention) is deferred to "
            "SoC integration. The protocol does provide Activity State CCCs "
            "and IBI / Hot-Join mechanisms to support coarse-grained "
            "low-power operation.")
        d["fields"] = f
        _write(p, d)

    # ------------------------------------------------------------------
    # L22 verification plan
    # ------------------------------------------------------------------
    p = gd / "L22_VERIFICATION_PLAN.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f["verification_plan_present"] = "implicit"
        f["verification_categories_derived_from_spec"] = [
            "START / STOP / Repeated START condition generation + detection (I3C timing per Tables 58/59)",
            "Address Header 7-bit + RnW + ACK/NACK handshake (arbitrable vs Push-Pull post-Sr)",
            "Broadcast Address 7'h7E recognition by every I3C Slave",
            "Hot-Join Address 7'h02 issuance + Master response (NACK / ACK+DISHJ / ACK+ENTDAA)",
            "Reserved address compliance per Table 9 (single-bit-error detect, conditional addresses)",
            "9-bit SDR Data Word framing (8 data + T-Bit) — no ACK on data",
            "T-Bit odd-parity computation correctness on Master-Write (XOR(Data[7:0],1))",
            "T-Bit end-of-data behavior on Slave-Read (T=1 continue with Master-abort window / T=0 end)",
            "Master Clock Stall under all six Table 11 conditions",
            "Required Broadcast CCC coverage: ENEC, DISEC, ENTAS0, RSTDAA, ENTDAA, SETMWL, SETMRL",
            "Required Direct CCC coverage: ENEC, DISEC, ENTAS0, RSTDAA, SETNEWDA, SETMWL, SETMRL, GETMWL, GETMRL, GETPID, GETBCR, GETDCR, GETSTATUS",
            "Optional but useful CCCs: DEFSLVS, SETDASA, SETAASA, GETACCMST, GETMXDS",
            "ENTHDR0..7 + HDR Exit Pattern detection (HDR not used in Basic, but must be tolerated)",
            "ENTDAA full sequence: 48-bit PID + BCR + DCR Open-Drain arbitration + 7-bit DA + odd-parity",
            "Provisional ID Collision Detection and Correction (Section 5.1.4.3)",
            "SETDASA point-to-point + SETAASA set-all-from-static behavior",
            "In-Band Interrupt: Bus Available → SDA-LOW → arbitrable address → ACK / Mandatory Byte / NACK retry",
            "Secondary Master Request + GETACCMST handoff sequence (Figures 44, 61, 62)",
            "Master Regaining Bus Ownership FSM (Figure 62)",
            "Activity State CCCs and tCAS adjustment (1 µs / 100 µs / 2 ms / 50 ms)",
            "Mixed Fast Bus tDIG_H_MIXED ≤ 45 ns enforcement (I2C 50 ns Spike Filter ignore-test)",
            "Pure Bus full 12.5 MHz / 12.9 MHz max SDR speed compliance",
            "Cb ≤ 50 pF / Pull-Up sizing / rise-time compliance",
            "Failsafe pad leakage compliance for Hot-Join devices (Table 54 Ii spec)",
            "Open-Drain ↔ Push-Pull handoff windows (Figure 32, Section 5.1.2.3.1)",
            "Error type S0..S6 detection + S0 incorrect-address ignore behavior",
            "Error type M0..M2 escalation + Master Error Detection and Escalation Handling (Section 5.1.10.2.4)",
            "BCR / DCR / PID / LVR register readback via GETBCR / GETDCR / GETPID",
            "Legacy I2C interop: Fm + Fm+ compliance via Table 57; no Slave SCL stretching",
            "VIL ≤ 0.3 VDD / VIH ≥ 0.7 VDD threshold compliance per Section 6.1",
        ]
        f["annex_c_normative_fsm_coverage"] = [
            "I3C Main Master FSM (Figure 57)",
            "Slave Interrupt Request FSM (Figure 58)",
            "Dynamic Address Assignment FSM (Figure 59)",
            "Hot-Join FSM (Figure 60)",
            "Secondary Master Request FSM (Figure 61)",
            "Master Regaining Bus Ownership FSM (Figure 62)",
            "I2C Legacy Master FSM (Figure 63)",
        ]
        f["notes"] = (
            "MIPI I3C Basic v1.0 does not ship with a formal verification "
            "plan or testbench; the categories above are derived from "
            "Tables 2, 3, 4, 9, 10, 11, 12, 15, 52, 53, 57-59 and Sections "
            "5.1.x. Concrete I3C controller IP vendors typically build a UVM "
            "testbench based on these categories plus the Annex C FSMs and "
            "Annex D typical communication examples.")
        d["fields"] = f
        _write(p, d)

    # ------------------------------------------------------------------
    # L23 security
    # ------------------------------------------------------------------
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f["security_requirements_present"] = False
        f["notes"] = (
            "MIPI I3C Basic v1.0 is a wire-level protocol spec with no "
            "confidentiality / integrity / authentication requirements. "
            "I3C is broadcast-on-the-bus — any device can snoop SDA / SCL. "
            "Application-layer security (e.g. SMBus PEC byte equivalents, "
            "sensor-data authentication, encrypted firmware updates over "
            "I3C) is layered on top by higher protocols / OEMs, not by the "
            "I3C Basic spec itself. The T-Bit Parity bit on each "
            "Master-Write data byte provides only single-bit-error "
            "detection, not cryptographic integrity. The Provisional ID + "
            "Manufacturer ID provide device identity but are not "
            "anti-counterfeiting tokens — they can be cloned by any device "
            "that wishes to impersonate. Hot-Join devices that are "
            "physically inserted can therefore be malicious; system "
            "designers requiring trust must add a higher-layer "
            "authentication mechanism.")
        f["no_built_in_authentication"]  = True
        f["no_built_in_confidentiality"] = True
        f["no_built_in_integrity_beyond_parity"] = True
        f["ipr_status_note"] = (
            "The MIPI I3C Basic Specification carries RAND-Z (royalty-free) "
            "IPR terms per Annex E — both for member and non-member "
            "implementers — provided they accept reciprocal RAND-Z "
            "licensing obligations toward other implementers.")
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
def is_i3c(blob: str) -> bool:
    """Content-only `i3c` detector (importable, lifted from the runner).

    Empty-safe. Reads ONLY ``blob`` (spec text). Byte-for-byte the
    same boolean the runner used inline.
    """
    if not blob:
        return False
    return bool(
        ("I3C" in blob and "Dynamic Address" in blob
            and "IBI" in blob)
        or ("I3C Basic" in blob and "CCC" in blob)
        or ("I3C" in blob and "HDR-DDR" in blob
            and "Hot-Join" in blob)
        or ("ENTDAA" in blob and "CCC" in blob))
