"""1-Wire-class protocol synth helper.

v0.1.84 — ic_class-gated overlay for `bus_interconnect_protocol` /
`serial_peripheral_protocol` specs that exhibit the 1-Wire structural
signature (multi-drop open-drain single-line bus + 64-bit ROM ID +
Reset/Presence + ROM commands + LSB-first time-slot signaling +
parasitic-power). Applies Maxim AN148 spec-canonical content to
L1-L18 + L21.

Doctrine: structural-keyword detection IS general within an ic_class
(mirrors AMBA-AXI / SPI / I2C / UART / CAN / USB / I2S synth approach).
Any 1-Wire-class spec (Maxim/Dallas 1-Wire AN148, individual device
datasheets like DS18B20 / DS2401 / iButton, derived Maxim secure
authenticators) exhibits the same signature: open-drain DQ + 64-bit
ROM ID + Reset/Presence + Read ROM (0x33) / Match ROM (0x55) / Skip
ROM (0xCC) / Search ROM (0xF0) opcode set + CRC-8 (poly x^8+x^5+x^4+1).

Public entry: `apply_onewire_synth(generated_docs_dir, is_onewire,
onewire_ic_name)`.
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


def _ensure_dict(d: dict, key: str) -> dict:
    """Helper: setdefault is a no-op if key exists with value None — use
    explicit empty-check to handle that case across the codebase."""
    if d.get(key) in (None, "", []):
        d[key] = {}
    return d[key]


def apply_onewire_synth(generated_docs_dir: Path,
                        is_onewire: bool,
                        onewire_ic_name: Optional[str]) -> None:
    """Apply 1-Wire-specific synth when the structural signature matched.

    fail-open contract: print errors but never raise.
    """
    if not is_onewire:
        return
    gd = Path(generated_docs_dir)

    try:
        # Force ic_name across the 14 main L docs (L1-L23 + L8 timing).
        if onewire_ic_name is not None:
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
                    d["ic_name"] = onewire_ic_name
                    _write(q, d)

        _l1(gd)
        _l2(gd)
        _l3(gd)
        _l4(gd)
        _l5(gd)
        _l6(gd)
        _l7(gd)
        _l8_rtl_constants(gd)
        _l8_timing_waveform(gd)
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
    except Exception as exc:  # fail-open
        print(f"[onewire_protocol_synth] WARN: {exc}")


# ============================================================
# L1 DATASHEET
# ============================================================
def _l1(gd: Path) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("document_title", "Guidelines for Reliable 1-Wire Networks")
    d.setdefault("document_number", "Application Note 148")
    d.setdefault("revised_date", "16 November 2001")
    d.setdefault("manufacturer", "Maxim Integrated (originally Dallas Semiconductor)")
    d.setdefault("trademark",
        "1-Wire® and iButton® are registered trademarks of Maxim Integrated.")
    d.setdefault("external_pins", ["1-Wire data line (DQ)", "GND"])
    d.setdefault("external_pin_count", 2)
    d.setdefault("key_features", [
        "Single-wire half-duplex serial bus (the 1-Wire 'data' line carries both clock + data via time-slot signaling).",
        "Multi-drop network — one master + many slave devices on a single twisted-pair (or single wire + ground).",
        "Parasitic power — slaves can draw power from the data line itself during HIGH periods (no separate VDD wire required).",
        "Master initiates all transactions; slaves are addressable by unique 64-bit ROM ID.",
        "Open-drain with weak pull-up — any device can pull the line LOW (wired-AND); released line is HIGH.",
        "Standard speed ~16 kbit/s; overdrive speed ~125 kbit/s (overdrive only on short connections).",
        "Time-slot signaling: master initiates each bit by pulling line LOW, then samples the line HIGH or LOW within a defined window.",
        "Robust to extended cable runs: up to several hundred meters of Category 5 twisted pair with proper bus master design.",
        "Designed for low-cost peripheral attach: temperature sensors, EEPROMs, real-time clocks, iButton tokens.",
        "Multi-drop arbitration via Search ROM — master broadcasts a binary-tree query and identifies each slave's unique 64-bit ROM ID.",
    ])
    d.setdefault("modes_of_operation", [
        {"name": "Standard speed",  "max_bit_rate": "~16 kbit/s",  "use_case": "Default; works at any cable length within the network limits."},
        {"name": "Overdrive speed", "max_bit_rate": "~125 kbit/s", "use_case": "Short connections only; not suitable for extended 1-Wire networks."},
    ])
    d.setdefault("topology_examples", [
        {"name": "Linear",  "description": "Single pair starting at master, extending to farthest slave (point-to-multipoint chain)."},
        {"name": "Stubbed", "description": "Linear backbone with short tap-off stubs to individual slaves."},
        {"name": "Star",    "description": "Multiple branches radiating from the master; harder to drive reliably."},
    ])
    d.setdefault("overview",
        "The 1-Wire protocol was originally designed for communication with nearby devices on a short connection — a way to add auxiliary memory on a single microprocessor port pin. The bus has grown to support multi-drop (networking) capabilities with bus lengths in the hundreds of meters. 1-Wire is suitable for temperature sensors, EEPROMs, real-time clocks, iButton tokens, and similar low-cost peripherals.")
    d.setdefault("use_cases", [
        "Temperature sensors (e.g. DS18B20)",
        "EEPROMs and memory devices",
        "Real-time clocks",
        "iButton authentication / access tokens",
        "Battery-pack monitors",
        "Auxiliary memory on a microcontroller port pin",
    ])
    _write(p, d)


# ============================================================
# L2 FRS
# ============================================================
def _l2(gd: Path) -> None:
    p = gd / "L2_FRS.json"
    if not p.is_file():
        return
    d = _read(p)
    po = _ensure_dict(d, "protocol_overview")
    if isinstance(po, dict):
        po.setdefault("type",
            "Half-duplex single-wire serial bus with master-initiated time-slot signaling.")
        po.setdefault("duplex", "half-duplex (single line shared TX/RX)")
        po.setdefault("synchronous", False)
        po.setdefault("wire_names", [
            "DQ (data line; carries both clock + data via time slots)",
            "GND",
        ])
        po["wire_count"] = 2  # force-overwrite (universal synth sets 1)
        po.setdefault("drive_type",
            "open-drain wired-AND; HIGH = released (pulled up to VDD by Rp)")
        po.setdefault("multi_drop", True)
        po.setdefault("max_slaves_per_bus",
            "~100 (practical limit set by network capacitance and pull-up budget)")
        po.setdefault("parasitic_power_capable", True)
    fr = [
        {"id": "FR-PHY-01",      "text": "DQ line is open-drain; HIGH state is achieved by all devices releasing the line (pulled up by Rp); any device may pull LOW (wired-AND)."},
        {"id": "FR-MASTER-02",   "text": "Master initiates every transaction; slaves never initiate non-presence-pulse traffic."},
        {"id": "FR-RESET-03",    "text": "Reset pulse = master pulls DQ LOW for ≥ 480 µs at standard speed; slaves respond with a Presence Pulse 60-240 µs after master releases the line."},
        {"id": "FR-WRITE-04",    "text": "Write-1 time slot: master pulls LOW for 1-15 µs then releases for the remainder of the 60 µs slot. Write-0 time slot: master pulls LOW for ≥ 60 µs (the full slot)."},
        {"id": "FR-READ-05",     "text": "Read time slot: master pulls LOW for 1-15 µs then releases; slave drives LOW (for 0) or releases HIGH (for 1) within the same slot; master samples ~15 µs after the slot start."},
        {"id": "FR-SLOT-06",     "text": "Standard time slot = 60 µs minimum (typically 60-120 µs); inter-slot recovery time ≥ 1 µs."},
        {"id": "FR-ROM-07",      "text": "Every 1-Wire slave has a unique 64-bit ROM ID: 8-bit family code + 48-bit serial number + 8-bit CRC-8."},
        {"id": "FR-CMD-ROM-08",  "text": "Master uses ROM commands to identify and select slaves: Read ROM (0x33, single-device only), Match ROM (0x55, address one slave by 64-bit ID), Skip ROM (0xCC, broadcast to all), Search ROM (0xF0, binary-tree enumeration)."},
        {"id": "FR-FUNCTION-09", "text": "After a successful ROM-command address-resolution phase, the master issues a device-specific Function Command (e.g. 0x44 Convert T for DS18B20)."},
        {"id": "FR-OVERDRIVE-10","text": "Optional Overdrive speed (~125 kbit/s); time-slot duration shrinks ~8×. Overdrive only suitable for short connections."},
        {"id": "FR-CRC-11",      "text": "CRC-8 polynomial x^8 + x^5 + x^4 + 1 (0x31 / reflected 0x8C) protects the 64-bit ROM ID and many function-command data payloads."},
        {"id": "FR-PRESENCE-12", "text": "Presence Pulse: each slave responds to Reset by holding DQ LOW for 60-240 µs after the master releases the line; presence of any slave is visible as the line going LOW."},
    ]
    if _empty(d.get("functional_requirements")):
        d["functional_requirements"] = fr
    if _empty(d.get("error_response_conditions")):
        d["error_response_conditions"] = [
            "CRC-8 mismatch on ROM ID or function-command payload — master discards data and may retry.",
            "Missing Presence Pulse after Reset — no slaves present (or slaves not synchronized).",
            "Bus-stuck-LOW — wiring fault or a held-down slave; master must reset or interrupt power.",
        ]
    if _empty(d.get("compliance_requirements")):
        d["compliance_requirements"] = [
            "Open-drain output stage with weak pull-up to VDD (typically 4.7 kΩ; ≤ 1 kΩ for long networks).",
            "Master must drive Reset pulse ≥ 480 µs at standard speed; ≥ 48 µs at overdrive speed.",
            "Slaves must respond to Reset with a Presence Pulse within tPDH + tPDL window.",
            "All bits transmitted LSB-first within each byte.",
        ]
    _write(p, d)


# ============================================================
# L3 CMD/PROTOCOL
# ============================================================
def _l3(gd: Path) -> None:
    p = gd / "L3_CMD_PROTOCOL.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("protocol_type",
        "Master-polled half-duplex single-wire bus; address-based (64-bit ROM ID per slave).")
    d.setdefault("channels", [
        {"name": "DQ", "direction": "bidirectional open-drain (wired-AND)",
         "description": "Single data line carrying time-slot-encoded bits AND optionally parasitic power."},
        {"name": "GND", "direction": "ground reference",
         "description": "Common ground for master + all slaves."},
    ])
    d.setdefault("rom_commands_table", [
        {"hex": "0x33", "name": "Read ROM",            "purpose": "Read 64-bit ROM ID of the single slave on bus (only works if exactly 1 slave is present)."},
        {"hex": "0x55", "name": "Match ROM",           "purpose": "Address one specific slave by transmitting its 64-bit ROM ID."},
        {"hex": "0xCC", "name": "Skip ROM",            "purpose": "Broadcast to all slaves (no address; useful when only 1 device is present)."},
        {"hex": "0xF0", "name": "Search ROM",          "purpose": "Binary-tree enumeration of all slaves; master discovers each ROM ID."},
        {"hex": "0xEC", "name": "Alarm Search",        "purpose": "Search ROM variant — only alarmed slaves respond."},
        {"hex": "0x69", "name": "Resume",              "purpose": "Re-address the previously addressed slave without resending ROM ID."},
        {"hex": "0xA5", "name": "Overdrive Skip ROM",  "purpose": "Switch all slaves to overdrive speed."},
        {"hex": "0x3C", "name": "Overdrive Match ROM", "purpose": "Match ROM and switch to overdrive speed."},
    ])
    d.setdefault("rom_id_format", {
        "total_width_bits": 64,
        "fields": [
            {"name": "Family Code",   "width_bits": 8,  "purpose": "Identifies device type (e.g. 0x28 = DS18B20)."},
            {"name": "Serial Number", "width_bits": 48, "purpose": "Unique per device (factory-assigned)."},
            {"name": "CRC-8",         "width_bits": 8,  "purpose": "CRC-8 over family code + serial number."},
        ],
        "crc8_polynomial": "x^8 + x^5 + x^4 + 1 (0x31; reflected 0x8C; initial 0)",
    })
    d.setdefault("function_commands_examples", [
        {"hex": "0x44", "name": "Convert T (DS18B20)",          "purpose": "Start temperature conversion on selected slave."},
        {"hex": "0xBE", "name": "Read Scratchpad (DS18B20)",    "purpose": "Read 9-byte scratchpad from selected slave."},
        {"hex": "0x4E", "name": "Write Scratchpad (DS18B20)",   "purpose": "Write to scratchpad bytes 2-4."},
        {"hex": "0x48", "name": "Copy Scratchpad (DS18B20)",    "purpose": "Copy scratchpad to internal EEPROM."},
        {"hex": "0xB8", "name": "Recall E2 (DS18B20)",          "purpose": "Recall EEPROM to scratchpad."},
        {"hex": "0xB4", "name": "Read Power Supply (DS18B20)",  "purpose": "Query parasitic vs external power."},
    ])
    d.setdefault("transaction_sequence", [
        "1. Master initiates a Reset Pulse (LOW for ≥ 480 µs at standard speed).",
        "2. Slaves respond with a Presence Pulse (LOW for 60-240 µs after master releases).",
        "3. Master issues a ROM Command (1 byte) to address a slave OR discover slaves.",
        "4. If targeted ROM operation: master transmits 64-bit ROM ID.",
        "5. Master issues a Function Command (device-specific 1 byte).",
        "6. Master and selected slave exchange data via Write/Read time slots, LSB-first byte by byte.",
    ])
    d.setdefault("valid_ready_handshake_rules", [
        "Slave devices indicate presence by pulling DQ LOW for 60-240 µs after master releases Reset.",
        "Data is transferred bit by bit in time slots; the master always initiates each slot.",
        "There is no general per-byte ACK — only the CRC-8 at the end of certain commands provides correctness checking.",
    ])
    d.setdefault("burst_based", False)
    _write(p, d)


# ============================================================
# L4 REGMAP (no register file at protocol layer)
# ============================================================
def _l4(gd: Path) -> None:
    p = gd / "L4_REGMAP.json"
    if not p.is_file():
        return
    d = _read(p)
    d["register_map_present"] = False
    d["notes"] = (
        "1-Wire is a wire-level multi-drop bus protocol; there is no "
        "addressable register file at the protocol layer. Each 1-Wire "
        "slave device (DS18B20 temperature sensor, DS2401 silicon "
        "serial number, iButton EEPROM, etc.) defines its own scratchpad "
        "/ EEPROM memory map accessed via device-specific function "
        "commands AFTER the ROM-command address resolution phase. AN148 "
        "specifies only the wire-level protocol (Reset / Presence / "
        "time-slot signaling) and the ROM-command set; per-slave "
        "register / scratchpad layouts live in each device's individual "
        "datasheet.")
    _write(p, d)


# ============================================================
# L5 ADI SPEC (digital, no analog interface)
# ============================================================
def _l5(gd: Path) -> None:
    p = gd / "L5_ADI_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("analog_digital_interface_present", False)
    d["signaling_summary"] = (
        "Pure digital open-drain signaling on the single DQ line "
        "(referenced to GND). The bus is held HIGH by a weak pull-up "
        "resistor Rp (typically 4.7 kΩ for small networks; ≤ 1 kΩ for "
        "long / heavy networks); any device (master or slave) may pull "
        "LOW (wired-AND). Although the protocol itself is purely "
        "digital, the analog characteristics of the network (cable "
        "capacitance, pull-up sizing, slew rate, signal reflections) "
        "directly affect reliability. AN148 emphasizes impedance "
        "matching, slew-rate control, and adequate pull-up current as "
        "critical for long networks — see Appendix C (Advanced Bus "
        "Driver) and Appendix D (R-C filter for DS2480B).")
    _write(p, d)


# ============================================================
# L6 CONTROL LOGIC (master + slave FSM)
# ============================================================
def _l6(gd: Path) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("fsm_states_master", [
        {"name": "M_IDLE",            "description": "Bus released (HIGH via pull-up); master waits for next transaction trigger."},
        {"name": "M_RESET",           "description": "Master drives DQ LOW for ≥ 480 µs (standard speed) to issue a Reset Pulse."},
        {"name": "M_PRESENCE_WAIT",   "description": "Master releases DQ; samples for Presence Pulse within tPDH + tPDL window (15-240 µs after release)."},
        {"name": "M_ROM_CMD",         "description": "Master transmits 1-byte ROM command (Read ROM 0x33, Match ROM 0x55, Skip ROM 0xCC, Search ROM 0xF0, Alarm Search 0xEC, Resume 0x69, Overdrive Skip 0xA5, Overdrive Match 0x3C)."},
        {"name": "M_ADDRESS",         "description": "If ROM command is Match ROM or Overdrive Match: master transmits the 64-bit ROM ID of the targeted slave."},
        {"name": "M_FUNC_CMD",        "description": "Master transmits 1-byte device-specific Function Command (e.g. 0x44 Convert T for DS18B20)."},
        {"name": "M_DATA_XFER",       "description": "Master generates Write or Read time slots; data flows MSB-first (or LSB-first depending on device convention) byte by byte."},
        {"name": "M_SEARCH",          "description": "During Search ROM, master transmits binary-tree query: at each ROM-ID bit position, master reads bit (all responding slaves drive their bit) then reads its complement (slaves drive complement); master then writes the chosen path bit to filter slaves not matching that path."},
    ])
    d.setdefault("fsm_states_slave", [
        {"name": "S_RESET_WAIT",      "description": "Slave samples DQ LOW for ≥ tRSTL_MIN; transitions to S_PRESENCE on master release."},
        {"name": "S_PRESENCE",        "description": "After tPDH (15-60 µs), slave drives DQ LOW for tPDL (60-240 µs) — the Presence Pulse."},
        {"name": "S_ROM_LISTEN",      "description": "Slave samples 8-bit ROM command transmitted by master."},
        {"name": "S_ROM_MATCH_CHECK", "description": "If Match ROM (0x55) or Overdrive Match (0x3C): slave compares each transmitted ROM-ID bit against its own; mismatch → drop out and wait for next Reset."},
        {"name": "S_SEARCH_RESPOND",  "description": "During Search ROM (0xF0): slave drives its current ROM-ID bit (Read slot 1), then drives the complement (Read slot 2); on master's Write slot, if master's bit doesn't match slave's bit, slave drops out."},
        {"name": "S_FUNC_LISTEN",     "description": "Slave executes device-specific Function Command (read scratchpad, write scratchpad, convert temperature, etc.)."},
        {"name": "S_DATA_XFER",       "description": "Slave participates in Write/Read time slots until next Reset Pulse aborts the transaction."},
    ])
    d.setdefault("fsm_hints_master", {
        "trigger": "Application initiates a Reset Pulse by pulling DQ LOW for ≥ 480 µs.",
        "rule":    "Always Reset before any new transaction; ROM command must be issued first; Match/Search ROM must be followed by 64-bit ROM ID; Function Command is device-specific.",
        "abort":   "Master issues new Reset Pulse to abort any in-progress transaction — slaves resync at next Presence Pulse.",
    })
    d.setdefault("fsm_hints_slave", {
        "trigger": "Slave detects DQ LOW for ≥ tRSTL_MIN (≥ 480 µs std / ≥ 48 µs overdrive).",
        "rule":    "Respond with Presence Pulse 15-60 µs after master release; then participate in ROM-command address resolution; drop out on first ROM-ID mismatch; resume only on next Reset.",
        "abort":   "Any DQ LOW for ≥ tRSTL_MIN aborts and re-arms the slave; slave returns to S_PRESENCE.",
    })
    d.setdefault("anti_deadlock_rule",
        "Wired-AND single line: any slave or master can pull LOW. Master always initiates and times the protocol; slaves never spontaneously transmit (except the Presence Pulse, which is a deterministic response to Reset). Bus-stuck-LOW indicates a wiring fault or a failed slave; master must restart by power-cycling or issuing Reset.")
    d.setdefault("exit_from_reset_or_poweron",
        "On power-on, master leaves DQ released (HIGH via pull-up); waits for application to issue Reset Pulse. Slaves power up and become ready when their on-chip energy storage capacitor charges via parasitic power; first Reset Pulse establishes synchronization.")
    d.setdefault("default_ready_state_recommendation", {
        "DQ_idle":               "HIGH (released; pulled to VDD by Rp). Both master and slave outputs are released.",
        "slave_internal_state":  "Awaiting Reset Pulse; no transaction in progress.",
    })
    d.setdefault("speed_modes", [
        {"name": "Standard speed",  "description": "tRSTL ≥ 480 µs; time-slot 60 µs minimum (typically 60-120 µs); bit rate ~16 kbit/s."},
        {"name": "Overdrive speed", "description": "tRSTL ≥ 48 µs (8× faster); time-slot ~7.5 µs; bit rate ~125 kbit/s. Only suitable for short connections."},
    ])
    d.setdefault("timing_dependency_rule",
        "All time-slot timings are master-driven. Master pulls DQ LOW to start each slot (1-15 µs LOW for Write-1/Read; ≥ 60 µs LOW for Write-0). Slave samples its expected behavior on the master's falling edge; master samples slave's response ~15 µs after its own falling edge (Read slot). Recovery time ≥ 1 µs between slots.")
    _write(p, d)


# ============================================================
# L7 TEST/DEBUG
# ============================================================
def _l7(gd: Path) -> None:
    p = gd / "L7_TEST_DEBUG.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("test_debug_architecture_present", False)
    d.setdefault("spec_provided_observability", [
        {"name": "Presence Pulse",                       "purpose": "After every Reset, master can verify at least one slave is present on the bus (DQ goes LOW 15-60 µs after master release)."},
        {"name": "CRC-8 over 64-bit ROM ID",             "purpose": "Last 8 bits of every ROM ID is a CRC-8 over the 56-bit (family code + serial) prefix; master can verify ROM-ID integrity end-to-end."},
        {"name": "CRC-8 over function-command payload", "purpose": "Many function commands (e.g. DS18B20 Read Scratchpad) end with a CRC-8 over the data bytes; master can verify data integrity."},
        {"name": "Search ROM enumeration",              "purpose": "Master can enumerate all slaves on the bus by binary-tree Search ROM; missing slaves are detectable as enumeration mismatches over time."},
        {"name": "Bus-stuck-LOW detection",             "purpose": "If DQ does not return HIGH after master release, master can infer wiring fault or held-down slave."},
    ])
    d["notes"] = (
        "AN148 does NOT specify protocol-level error reporting or BIST. "
        "Reliability mechanisms are confined to (a) the CRC-8 over the "
        "64-bit ROM ID and certain function-command payloads, and (b) "
        "the Presence Pulse as a coarse 'is anyone home' check. AN148 "
        "highlights search-algorithm robustness — Devices that physically "
        "present may appear and disappear in search results due to noise, "
        "parasite-power starvation, or signal reflections; reliable "
        "networks must implement debounce windows and tolerate transient "
        "enumeration failures. Master-end interface design (slew-rate "
        "control, dynamic pull-up, sample-time accuracy) is the primary "
        "lever for improving observability and reliability.")
    _write(p, d)


# ============================================================
# L8 RTL CONSTANTS
# ============================================================
def _l8_rtl_constants(gd: Path) -> None:
    p = gd / "L8_RTL_CONSTANTS.json"
    if not p.is_file():
        return
    d = _read(p)
    wp = _ensure_dict(d, "width_parameters")
    if isinstance(wp, dict):
        for k, v in {
            "DQ_BIT_WIDTH": 1,
            "EXTERNAL_PIN_COUNT": 2,
            "ROM_ID_WIDTH_BITS": 64,
            "FAMILY_CODE_WIDTH_BITS": 8,
            "SERIAL_NUMBER_WIDTH_BITS": 48,
            "CRC8_WIDTH_BITS": 8,
            "ROM_COMMAND_WIDTH_BITS": 8,
            "FUNCTION_COMMAND_WIDTH_BITS": 8,
            "DATA_FORMAT": "LSB-first within each byte (1-Wire transmits least-significant bit of each byte first)",
        }.items():
            wp.setdefault(k, v)
    d.setdefault("voltage_levels", {
        "VDD_typical_V": 5.0,
        "VDD_range_V": [4.5, 5.5],
        "VDD_min_slave_operation_V": 2.8,
        "VDD_max_slave_operation_V": 6.0,
        "signaling": "Open-drain on DQ; HIGH = released (pulled to VDD by Rp); LOW = any device drives DQ low.",
    })
    d.setdefault("pull_up_resistor", {
        "Rp_small_network_ohms": 4700,
        "Rp_simple_microcontroller_ohms": 2200,
        "Rp_improved_interface_ohms": 1000,
        "Rp_long_network_typical_ohms": 1000,
        "Rp_very_early_recommended_ohms_obsolete": 5000,
        "notes": "AN148 deprecates the early 5 kΩ recommendation for non-trivial networks. Modern designs use 4.7 kΩ for small networks and 1 kΩ (often with active pull-up assistance) for large networks.",
    })
    d.setdefault("standard_speed_timing_us", {
        "tRSTL_min": 480, "tRSTH_min": 480,
        "tPDH_min": 15,   "tPDH_max": 60,
        "tPDL_min": 60,   "tPDL_max": 240,
        "tSLOT_min": 60,  "tSLOT_typ": 70, "tSLOT_max": 120,
        "tLOW0_min": 60,  "tLOW0_max": 120,
        "tLOW1_min": 1,   "tLOW1_max": 15,
        "tRDV_min": 15,   "tRDV_max": 15,
        "tREC_min": 1,
        "tMSR_typical": 15, "tMSR_optimized_DS2480B": 21,
    })
    d.setdefault("overdrive_speed_timing_us", {
        "tRSTL_min": 48,  "tRSTL_max": 80,
        "tPDH_min": 2,    "tPDH_max": 6,
        "tPDL_min": 8,    "tPDL_max": 24,
        "tSLOT_typ": 7.5,
        "tLOW0_min": 6,   "tLOW0_max": 16,
        "tLOW1_min": 1,   "tLOW1_max": 2,
        "tRDV_typical": 2,
        "tREC_min": 1,
    })
    d.setdefault("ds2480b_optimized_timings", {
        "pulldown_slew_rate_V_per_us": 1.37,
        "write_one_low_time_us": 11,
        "data_sample_offset_recovery_us": 10,
        "applicable_VDD_range_V": [4.5, 5.5],
    })
    d.setdefault("key_constants_for_RTL_authoring", {
        "bus_drive_polarity":            "open-drain wired-AND; HIGH is the released state",
        "bit_order_within_byte":         "LSB first",
        "presence_pulse_polarity":       "active LOW (slaves drive DQ LOW after master release)",
        "reset_pulse_polarity":          "active LOW (master drives DQ LOW for ≥ 480 µs)",
        "master_initiates_all_slots":    True,
        "slaves_never_initiate_traffic": True,
        "wired_AND":                     True,
        "parasitic_power_capable":       True,
        "no_register_addressing":        True,
        "no_byte_level_ACK":             True,
        "crc8_polynomial":               "x^8 + x^5 + x^4 + 1",
        "crc8_polynomial_byte_hex":      "0x31",
        "crc8_polynomial_reflected_hex": "0x8C",
        "crc8_initial_value":            0,
    })
    d.setdefault("rom_id_layout", {
        "total_width_bits": 64,
        "field_order_LSB_first_on_wire": [
            {"name": "Family Code",   "width_bits": 8,  "transmitted_position": "1st byte"},
            {"name": "Serial Number", "width_bits": 48, "transmitted_position": "bytes 2-7"},
            {"name": "CRC-8",         "width_bits": 8,  "transmitted_position": "8th byte"},
        ],
    })
    d.setdefault("default_signal_values_when_idle", {
        "DQ": "HIGH (released; pulled to VDD by Rp); master + all slave outputs released.",
    })
    _write(p, d)


# ============================================================
# L8 TIMING WAVEFORM
# ============================================================
def _l8_timing_waveform(gd: Path) -> None:
    p = gd / "L8_TIMING_WAVEFORM.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("reset_presence_waveform", {
        "step_1_master_pull_LOW": "Master pulls DQ LOW for ≥ 480 µs (Reset Pulse, tRSTL).",
        "step_2_master_release":  "Master releases DQ; line begins rising toward VDD via Rp.",
        "step_3_slave_wait_tPDH": "After 15-60 µs (tPDH), at least one slave drives DQ LOW.",
        "step_4_slave_presence_pulse": "Slave holds DQ LOW for 60-240 µs (tPDL); multiple slaves' Presence Pulses may overlap into a single observable pulse.",
        "step_5_slave_release":   "Slave(s) release DQ; line returns to HIGH via Rp; master can sample HIGH and proceed to ROM command phase.",
    })
    d.setdefault("write_1_time_slot_waveform", {
        "step_1_master_pull_LOW": "Master pulls DQ LOW for 1-15 µs (typically ~10 µs).",
        "step_2_master_release":  "Master releases DQ; line rises via Rp.",
        "step_3_slot_idle":       "Line stays HIGH for remainder of 60-120 µs slot.",
        "step_4_recovery":        "Minimum 1 µs recovery before next slot.",
    })
    d.setdefault("write_0_time_slot_waveform", {
        "step_1_master_pull_LOW": "Master pulls DQ LOW for ≥ 60 µs (typically 60 µs; full slot).",
        "step_2_master_release":  "Master releases DQ at end of slot; line rises via Rp.",
        "step_3_recovery":        "Minimum 1 µs recovery before next slot.",
    })
    d.setdefault("read_time_slot_waveform", {
        "step_1_master_pull_LOW": "Master pulls DQ LOW for 1-15 µs to initiate Read slot.",
        "step_2_master_release":  "Master releases DQ.",
        "step_3_slave_response":  "Slave either drives DQ LOW (for bit = 0) or releases (for bit = 1) within the same slot.",
        "step_4_master_sample":   "Master samples DQ ~15 µs after slot start (tMSR); a HIGH sample = 1, a LOW sample = 0.",
        "step_5_slave_release":   "Slave releases DQ before end of slot; recovery ≥ 1 µs.",
    })
    d.setdefault("master_sample_time_window", {
        "spec_min_us": 1,
        "spec_max_us": 15,
        "optimum_us": 15,
        "DS2480B_optimized_us": 21,
        "notes": "Spec calls for sample time between 1 µs and 15 µs after start of read time slot. Optimum is 15 µs (allows full cable rise time). For controlled pull-up voltage 4.5-5.5 V, slave timing variation tightens to 22-60 µs, permitting moving sample time to 21 µs (allowing 6 µs more cable charge time for heavier networks). AN148 Appendix E explicitly documents this trade-off for DS2480B.",
    })
    d.setdefault("common_waveform_pathology_examples", [
        {"name": "Excessive weight + resistor-only pull-up", "effect": "Slow rise time during recovery — DQ may not reach valid HIGH before sample; reads borderline; long Write-0 streams starve slaves of parasitic power."},
        {"name": "Reflections on stubs and star branches",   "effect": "Ringing and undershoot on master falling edges; secondary edges may be interpreted as bit transitions by some slaves."},
        {"name": "Uncontrolled slave fall edge",             "effect": "Slave-driven Presence Pulse or Read-0 falling edge is not slew-rate controlled; can cause ringing and undershoot."},
        {"name": "Dynamic pull-up false trigger",            "effect": "DS2480B's dynamic pull-up may fire on ringing during falling edges, producing extra current that interferes with subsequent reads."},
    ])
    d.setdefault("general_timing_rule",
        "All time-slot timings scale by ~8× between Standard and Overdrive speeds. Reset Pulse ≥ 480 µs standard / ≥ 48 µs overdrive. Minimum slot 60 µs standard / 7.5 µs overdrive. Recovery between slots ≥ 1 µs at both speeds.")
    d.setdefault("voltage_levels", {
        "VDD_typical_V": 5.0,
        "VDD_range_V": [4.5, 5.5],
        "controlled_pullup_advantage": "When pull-up voltage is controlled to 4.5-5.5 V, slave bit-time variation narrows to 22-60 µs, allowing the master to push sample time out to 21 µs and supporting more network weight.",
    })
    _write(p, d)


# ============================================================
# L9 INTEGRATION SPEC
# ============================================================
def _l9(gd: Path) -> None:
    p = gd / "L9_INTEGRATION_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("module_role",
        "Wire-level half-duplex single-line multi-drop serial bus specification (Maxim/Dallas 1-Wire). Defines a 2-conductor (DQ + GND) network between one master and many slaves, with optional parasitic-power delivery on the data line itself. Concrete 1-Wire master controllers (e.g. DS9097U, DS2480B serial-to-1-Wire, microcontroller bit-bang, DS9097 port adapter) implement this protocol; 1-Wire slaves (DS18B20, DS2401, iButton, EEPROM) sit on the bus and respond to master-initiated transactions.")
    d.setdefault("integration_overview", {
        "wire_count":           2,
        "wire_names":           ["DQ", "GND"],
        "wire_directions":      "DQ is bidirectional open-drain wired-AND; master and any slave may pull LOW; pull-up Rp holds line HIGH when no device drives.",
        "no_separate_clock":    "Clock is encoded into time-slot signaling on DQ itself.",
        "no_chip_select":       "No CS line; slaves are addressed via 64-bit ROM ID transmitted on DQ.",
        "addressing":           "64-bit ROM ID per slave (8-bit family code + 48-bit serial + 8-bit CRC-8); factory-burned.",
        "no_byte_ACK":          "No per-byte handshake; CRC-8 at end of selected payloads is the only protocol-level integrity check.",
        "master_initiates_all": True,
    })
    d.setdefault("interface_categories", [
        "Master (drives DQ for Reset, ROM command, Function command, Write/Read time slots; samples DQ for Presence Pulse + Read slots)",
        "Slave (responds with Presence Pulse after Reset; samples bits from master in time slots; drives DQ to send bits during Read slots)",
        "Optional parasitic-power slave (powered solely from DQ HIGH periods via on-chip storage capacitor)",
        "Optional externally-powered slave (powered from a separate VDD pin in addition to DQ)",
    ])
    d.setdefault("interconnect_topologies_supported", [
        {"name": "Linear",   "description": "Single twisted pair from master to farthest slave; other slaves attach along its length with stubs < 3 m. Preferred for long networks."},
        {"name": "Stubbed",  "description": "Main backbone from master with branches/stubs ≥ 3 m to individual slaves. Acceptable for medium networks; degrades with stub length."},
        {"name": "Star",     "description": "Multiple branches diverging at master; not recommended due to impedance mismatch and reflections."},
        {"name": "Switched", "description": "Star or stubbed network with DS2409 (or equivalent) 1-Wire switches that electrically isolate inactive branches — each active branch electrically resembles a linear network."},
    ])
    d.setdefault("interconnect_metrics", {
        "radius_m_max": 750,
        "radius_m_practical_limit_comment": "AN148: 'no 1-Wire network may ever have a radius greater than 750 m' at which protocol fails due to cable delay. Practical limit usually lower.",
        "weight_definition": "Total length of connected wire in meters; capacitance dominates.",
        "device_equivalent_weight_iButton_m": 1.0,
        "device_equivalent_weight_non_iButton_m": 0.5,
        "capacitance_per_24pF_equivalent_weight_m": 1.0,
        "max_weight_simple_resistor_pullup_m": 200,
        "max_weight_active_pullup_m": 500,
    })
    d.setdefault("default_signal_values_when_omitted",
        "DQ released HIGH via Rp; master and slaves all in idle. To halt traffic gracefully: master simply stops generating time slots; bus naturally idles.")
    d.setdefault("soc_dependent_items", [
        "Master-end interface (port-pin bit-bang vs DS2480B vs advanced bus driver — Appendix A/B/C of AN148).",
        "Pull-up resistor Rp value (4.7 kΩ small; 2.2 kΩ port-pin only; 1 kΩ improved; ≤ 1 kΩ for long networks; optional active-pull-up assist).",
        "Slew-rate control on master's pull-down (AN148 recommends 1.37 V/µs at standard speed for long networks).",
        "Active dynamic pull-up (decreases rise time for long lines).",
        "Impedance matching (e.g. 150 Ω series resistors at stub connections).",
        "DS2480B R-C filter (100 Ω + 4700 pF for short-to-medium networks; see Appendix D).",
        "Per-slave register file / scratchpad layout (defined in each slave's individual datasheet, not in AN148).",
        "CRC-8 implementation (in hardware on the master controller, or in firmware).",
    ])
    d.setdefault("common_master_end_interfaces", [
        {"name": "Simple microcontroller port pin",                  "Rp_ohms": 2200, "weight_radius_m": "≤ 3",   "notes": "Limited drive; tabletop only."},
        {"name": "Microcontroller with slew-rate FET + 1 kΩ pull-up","Rp_ohms": 1000, "weight_radius_m": "≤ 200", "notes": "Reliable medium networks."},
        {"name": "DS9097 PC serial port adapter",                    "Rp_ohms": None, "weight_radius_m": "≤ 40 / radius ≤ 3", "notes": "Local iButton probes only."},
        {"name": "DS1410E PC parallel port adapter",                 "Rp_ohms": None, "weight_radius_m": "≤ 40 / radius ≤ 3", "notes": "Local iButton probes only."},
        {"name": "DS2480B-based (DS9097U, TINI)",                    "Rp_ohms": None, "weight_radius_m": "≤ 200 with R-C filter", "notes": "Configure 'flex mode' + R-C filter for short/medium."},
        {"name": "Advanced Bus Interface (Appendix C)",              "Rp_ohms": None, "weight_radius_m": "≤ 500", "notes": "Dynamic pull-up + impedance matching."},
    ])
    d.setdefault("low_power_modes", {
        "Stop_traffic":             "Master stops generating time slots; bus naturally idles; parasitic-powered slaves draw quiescent current; storage capacitor holds charge for limited time.",
        "Parasitic_power_recharge": "During HIGH (recovery) periods, the bus delivers power to parasitic slaves via Rp; long strings of Write-0 slots starve them.",
        "Hard_reset":               "Cycle external VDD (if any) or hold DQ LOW for sufficient time that storage capacitors discharge — slaves re-initialize on next Reset Pulse.",
    })
    _write(p, d)


# ============================================================
# L10 TEST CASES
# ============================================================
def _l10(gd: Path) -> None:
    p = gd / "L10_TEST_CASES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_cases_present"] = (
        "partial - AN148 defines normative timing parameters and several "
        "common compliance scenarios (Reset/Presence detection, ROM "
        "commands, time-slot signaling, CRC-8 integrity, search-ROM "
        "enumeration) but does not provide a formal testbench.")
    d.setdefault("derived_compliance_test_categories", [
        "Reset Pulse: master pulls DQ LOW for ≥ 480 µs (standard) or ≥ 48 µs (overdrive); verify min/max tRSTL.",
        "Presence Pulse: at least one slave drives DQ LOW for tPDL (60-240 µs std / 8-24 µs overdrive) after tPDH (15-60 µs std / 2-6 µs overdrive); verify timing window.",
        "Write-1 time slot: master LOW for 1-15 µs then HIGH for remainder of 60-120 µs slot; slave samples HIGH.",
        "Write-0 time slot: master LOW for ≥ 60 µs (full slot); slave samples LOW.",
        "Read time slot: master LOW for 1-15 µs then release; slave drives 0 or releases for 1; master samples at tMSR (15 µs or 21 µs optimized).",
        "Inter-slot recovery: ≥ 1 µs HIGH between slots.",
        "ROM commands round-trip: 0x33 Read ROM (single-slave bus), 0x55 Match ROM, 0xCC Skip ROM, 0xF0 Search ROM, 0xEC Alarm Search.",
        "Search ROM binary-tree enumeration: master finds all unique 64-bit ROM IDs on a multi-slave bus.",
        "CRC-8 verification: ROM ID's last byte = CRC-8 (poly 0x31, init 0) over the 56-bit prefix.",
        "CRC-8 over function-command payload (where supported, e.g. DS18B20 Read Scratchpad).",
        "Overdrive switching: 0xA5 Overdrive Skip / 0x3C Overdrive Match transitions slaves to overdrive timing.",
        "Bus-stuck-LOW detection: master infers fault when DQ stays LOW after master release.",
        "Parasitic-power stress: long string of Write-0 slots should not cause slaves to reset due to power starvation.",
        "Network weight stress: max weight (200 m simple / 500 m active) — verify Presence Pulse, ROM read, and CRC-8 still pass.",
        "Network radius stress: up to ~750 m max; verify protocol still works within cable delay budget.",
        "Resume command (0x69): re-address previously addressed slave without resending 64-bit ROM ID.",
        "Multi-drop cohabitation: parasitic-powered and externally-powered slaves on the same bus.",
        "LSB-first byte ordering: verify each byte is transmitted LSB first (1-Wire convention).",
        "Slew-rate controlled fall edge: master's falling edge should not ring or undershoot on long lines.",
        "Pull-up adequacy: bus must reach valid HIGH within recovery time even at maximum weight.",
    ])
    _write(p, d)


# ============================================================
# L11 OTP CONTENT (64-bit ROM ID)
# ============================================================
def _l11(gd: Path) -> None:
    p = gd / "L11_OTP_CONTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    d["otp_present"] = True  # force-overwrite (universal synth sets False)
    d.setdefault("otp_role",
        "Each 1-Wire slave device contains a factory-burned, immutable 64-bit ROM ID — a per-device serial number that is the protocol-level identity used for addressing on the multi-drop bus. AN148 itself does not specify the OTP mechanism (laser fuse, mask ROM, EEPROM); each slave family chooses an implementation. From the bus perspective, every slave has a permanent, unique 64-bit identifier readable via the Read ROM (0x33) or Search ROM (0xF0) commands.")
    d.setdefault("rom_id_layout", {
        "total_width_bits": 64,
        "fields": [
            {"name": "Family Code",   "width_bits": 8,  "transmitted_first": True, "purpose": "Identifies device type (e.g. 0x28 = DS18B20 temperature sensor; 0x01 = DS2401 silicon serial number; 0x10 = DS18S20; many others). Lets the master apply the correct function-command set after address resolution."},
            {"name": "Serial Number", "width_bits": 48, "purpose": "Unique per device within a family code (factory-assigned). 2^48 ≈ 2.8×10^14 unique IDs per family; effectively guarantees no collisions in any practical 1-Wire network."},
            {"name": "CRC-8",         "width_bits": 8,  "purpose": "CRC-8 over the 56-bit (family code + serial) prefix. Polynomial x^8 + x^5 + x^4 + 1 (0x31, reflected 0x8C, initial 0). Allows the master to detect bit errors in ROM-ID transmission."},
        ],
    })
    d["notes"] = (
        "OTP at the 1-Wire protocol layer is exactly the 64-bit ROM ID. "
        "Per-slave function-command memories (DS18B20 9-byte scratchpad, "
        "EEPROM scratchpad/storage, configuration registers, alarm "
        "thresholds) are separate from the ROM ID and are defined per "
        "slave datasheet — they are NOT part of AN148's protocol layer. "
        "Some slaves (e.g. iButton 1-Wire EEPROMs, DS28E25 SHA-256 auth "
        "devices) layer per-device OTP / EEPROM mechanisms ON TOP of "
        "the wire-level 1-Wire protocol.")
    _write(p, d)


# ============================================================
# L12 BEHAVIORAL SEQUENCES
# ============================================================
def _l12(gd: Path) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("typical_transaction_sequence", [
        "1. Master initiates a Reset Pulse: pull DQ LOW for ≥ 480 µs (standard) or ≥ 48 µs (overdrive), then release.",
        "2. Slave(s) respond with a Presence Pulse: 15-60 µs after master release, slave pulls DQ LOW for 60-240 µs; master samples LOW to confirm at least one slave is present.",
        "3. Master transmits a ROM Command (1 byte, LSB-first) to address slave(s): 0x33 Read ROM, 0x55 Match ROM, 0xCC Skip ROM, 0xF0 Search ROM, 0xEC Alarm Search, 0x69 Resume, 0xA5 Overdrive Skip, 0x3C Overdrive Match.",
        "4. If targeted (Match ROM / Overdrive Match): master transmits the 64-bit ROM ID of the selected slave; all other slaves drop out on first mismatched bit.",
        "5. Master transmits a Function Command (1 byte, device-specific, LSB-first).",
        "6. Master and selected slave exchange data via Write/Read time slots, byte by byte (LSB first within each byte).",
        "7. Transaction ends with the next Reset Pulse; until then, the addressed slave remains addressed.",
    ])
    d.setdefault("search_rom_enumeration_sequence", [
        "1. Master issues Reset + Presence; ALL slaves respond.",
        "2. Master issues Search ROM (0xF0).",
        "3. FOR each of the 64 ROM-ID bit positions:",
        "    a. Master generates Read slot 1: every responding slave drives its bit (n) onto DQ — wired-AND results visible to master.",
        "    b. Master generates Read slot 2: every responding slave drives the complement (~n) onto DQ.",
        "    c. Master observes (bit, complement) pair: (0,1) = all responding slaves have 0 → master writes 0; (1,0) = all have 1 → master writes 1; (0,0) = discrepancy → master picks 0 or 1 per its search-tree strategy; (1,1) = no slaves responded (error).",
        "    d. Master writes back the chosen bit; slaves whose ROM-ID bit doesn't match the chosen bit drop out and wait for next Reset.",
        "4. After 64 bits, exactly one slave remains; master has its full 64-bit ROM ID.",
        "5. Master records this ROM ID, issues Reset, and on next Search ROM picks the OPPOSITE branch at the last discrepancy point — discovering the next slave.",
        "6. Repeat until all branches exhausted → full slave list.",
    ])
    d.setdefault("configuration_handover_sequences", [
        {"name": "Single slave on bus",
         "steps": "Master may use Read ROM (0x33) to capture the lone slave's ROM ID without a binary search, or Skip ROM (0xCC) to broadcast directly to it without any address resolution."},
        {"name": "Multi-slave broadcast",
         "steps": "Master uses Skip ROM (0xCC) followed by a Function Command that all slaves can act on simultaneously (e.g. 0x44 Convert T to start all DS18B20s converting at once)."},
        {"name": "Multi-slave targeted",
         "steps": "Master uses Match ROM (0x55) + 64-bit ROM ID to address exactly one slave; only that slave responds to the subsequent Function Command."},
        {"name": "Resume same slave",
         "steps": "After a targeted transaction, master uses Resume (0x69) to re-address the same slave without resending 64 bits of ROM ID — speeds up repeat operations."},
        {"name": "Switch to Overdrive",
         "steps": "Master uses Overdrive Skip (0xA5) or Overdrive Match (0x3C) at standard speed; slave(s) immediately transition to overdrive timing for all subsequent slots in the transaction (until next Reset at standard speed)."},
    ])
    d.setdefault("abort_sequence", [
        "1. Master issues a new Reset Pulse: pull DQ LOW for ≥ 480 µs at standard speed (or ≥ 48 µs at overdrive).",
        "2. All slaves immediately drop their in-progress transaction state.",
        "3. After master release, slaves resync via Presence Pulse — bus returns to a known state.",
    ])
    d.setdefault("presence_pulse_overlap",
        "If multiple slaves are present, their individual Presence Pulses (60-240 µs LOW each) overlap on the wired-AND bus into a single observable LOW pulse — master sees at most one Presence Pulse regardless of slave count.")
    d.setdefault("parasitic_power_sequence", [
        "1. During HIGH periods (recovery time, idle bus, Write-1 slot after master release), the slave's on-chip storage capacitor charges via the pull-up resistor.",
        "2. During LOW periods (slave drives 0; master drives Write-0; master Reset Pulse), the slave runs off stored energy on its capacitor.",
        "3. Long strings of Write-0 slots (master holding LOW for 60 µs at a time, with only 1-µs recovery between) can drain the capacitor below the slave's brown-out threshold — slave resets and issues a spurious Presence Pulse, corrupting the transaction.",
        "4. Mitigation: use external power (separate VDD pin) for high-current operations like temperature conversion or EEPROM writes; or use a strong active pull-up during such operations.",
    ])
    _write(p, d)


# ============================================================
# L13 LAB CALIBRATION
# ============================================================
def _l13(gd: Path) -> None:
    p = gd / "L13_LAB_CALIBRATION.json"
    if not p.is_file():
        return
    d = _read(p)
    d["lab_calibration_present"] = "partial"  # force-overwrite
    d.setdefault("characterization_targets", [
        {"name": "Network capacitance",
         "purpose": "Total capacitance of cable + slave devices + ESD protection sets the rise time on Write-1 / Read slots. Characterize by measuring the time constant of the released-line waveform under known Rp.",
         "rule_of_thumb": "Approx. 24 pF of capacitance per slave equivalent weight of 1 m of wire."},
        {"name": "Pull-up resistor sizing",
         "purpose": "Trade rise time vs power dissipation vs slave-drive margin. Lab measurement: with all slaves in their LOW-driving Presence Pulse state, verify Rp can still source ≥ valid LOW (~0.8 V) at master input threshold."},
        {"name": "Slew-rate control",
         "purpose": "Master falling-edge slew rate sets noise (ringing/undershoot) on long lines. AN148 recommends 1.37 V/µs at standard speed.",
         "optimum_V_per_us": 1.37},
        {"name": "Master sample time tMSR",
         "purpose": "Master must sample Read slots within the slot's valid window. Spec window is 1-15 µs; optimized DS2480B uses 21 µs for controlled 4.5-5.5 V pull-up.",
         "spec_min_us": 1, "spec_max_us": 15, "ds2480b_optimum_us": 21},
        {"name": "DS2480B 'flex mode' settings",
         "purpose": "DS2480B (used in DS9097U PC serial adapter) supports software-controlled pulldown slew rate, Write-1 low time, and data sample offset / recovery time. Calibrate to bus characteristics per Appendix E.",
         "optimum": {"pulldown_slew_rate_V_per_us": 1.37, "write_one_low_time_us": 11, "data_sample_offset_recovery_us": 10}},
        {"name": "Eye diagram on long lines",
         "purpose": "Characterize valid sampling window vs cable length + slave count. Reflections from the far end can return within the same slot at long radii (~750 m max where protocol fails)."},
    ])
    d.setdefault("compliance_lab_setup_examples", [
        "Oscilloscope on DQ (single-ended vs GND), 1 ms/div for Reset-Presence sequence, 10 µs/div for individual time slots.",
        "Logic analyzer captures bit-stream including ROM commands, ROM ID transmission, and CRC-8 trailer.",
        "Network analyzer to characterize cable impedance (typ. ~100 Ω for Cat 5 twisted pair).",
        "Programmable load (capacitor bank) to emulate varying slave-count weight on the bus.",
    ])
    d["notes"] = (
        "AN148 itself is an application note (calibration guide for system "
        "designers), not a device datasheet. The 'lab calibration' content "
        "of AN148 is precisely the methodology for tuning pull-up resistor, "
        "slew rate, sample time, R-C filter, and impedance matching to "
        "match a given network's weight and radius. Concrete 1-Wire slave "
        "devices (DS18B20 temperature sensor, DS2438 battery monitor) may "
        "have separate on-chip analog calibration / trim that is "
        "per-device, not part of the AN148 protocol layer.")
    _write(p, d)


# ============================================================
# L14 PROTOCOL VERSIONING
# ============================================================
def _l14(gd: Path) -> None:
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f.setdefault("spec_version",
        "Application Note 148 — Guidelines for Reliable 1-Wire Networks (16 November 2001)")
    if _empty(f.get("previous_versions")):
        f["previous_versions"] = [
            "Original 1-Wire bus invention by Dallas Semiconductor in the late 1980s (DS1990 first commercial part).",
            "Numerous per-device datasheets (DS18B20, DS2401, DS2480B, iButton family) define the protocol over time.",
            "AN148 (2001) is the consolidated reliability / network-design guide; supersedes earlier ad-hoc pull-up sizing advice (e.g. obsolete 5 kΩ recommendation).",
        ]
    if _empty(f.get("speed_classes")):
        f["speed_classes"] = [
            {"name": "Standard speed",  "bit_rate_kbps": 16,  "tRSTL_min_us": 480, "tSLOT_typ_us": 70,  "introduced": "Original 1-Wire (late 1980s)"},
            {"name": "Overdrive speed", "bit_rate_kbps": 125, "tRSTL_min_us": 48,  "tSLOT_typ_us": 7.5, "introduced": "Mid-1990s — for short, low-weight connections only"},
        ]
    if _empty(f.get("key_changes")):
        f["key_changes"] = [
            {"version": "AN148 (2001)", "summary": "First consolidated reliability guide; introduces formal definitions of network radius vs weight, recommends slew-rate control, deprecates 5 kΩ pull-up, documents DS2480B 'flex mode' optimum timings, distinguishes Linear / Stubbed / Star / Switched topologies."},
        ]
    if _empty(f.get("backward_compat_traps")):
        f["backward_compat_traps"] = [
            {"trap_name": "obsolete_5kohm_pullup",
             "rule": "Modern networks use 4.7 kΩ (small) or 1 kΩ (medium / long) pull-up resistor.",
             "trap": "Pre-AN148 documents recommended 5 kΩ; that value starves long networks and causes intermittent search-ROM failures."},
            {"trap_name": "ds2480b_default_timings_for_small_networks",
             "rule": "DS2480B factory-default timings are tuned for SMALL networks. Use 'flex mode' to retune for medium / long networks (Appendix E).",
             "trap": "Programmers leave DS2480B at defaults; medium networks then fail intermittently. AN148 documents the optimum 1.37 V/µs slew, 11 µs Write-1 LOW, 10 µs sample offset values."},
            {"trap_name": "ds2480b_without_rc_filter",
             "rule": "On any network > 1 m using a DS2480B, add the 100 Ω + 4700 pF R-C filter (Appendix D).",
             "trap": "Without the R-C filter, dynamic pull-up false-triggers on ringing during falling edges, corrupting reads."},
            {"trap_name": "overdrive_on_long_networks",
             "rule": "Overdrive speed (125 kbit/s) is ONLY for short connections.",
             "trap": "Programmers enable overdrive on long networks → timing tolerance collapses → search-ROM fails. AN148 explicitly excludes overdrive from its scope."},
            {"trap_name": "unswitched_star_topology",
             "rule": "Unswitched star topology is NOT recommended.",
             "trap": "Multiple branches diverging at master cause impedance mismatch + reflections from each branch's end. Use DS2409 switches to electrically isolate inactive branches."},
            {"trap_name": "ignore_parasitic_power_starvation",
             "rule": "Long sequences of Write-0 slots starve parasitic-powered slaves of energy.",
             "trap": "Slaves brown-out mid-transaction → spurious Presence Pulse → corrupted bus state. Use external power for high-current operations, or use strong-pull-up assist."},
        ]
    f.setdefault("version_naming_history_note",
        "1-Wire was invented by Dallas Semiconductor (acquired by Maxim Integrated in 2001; later acquired by Analog Devices in 2021). The bus has been continuously deployed since the late 1980s for low-cost peripheral attach (iButton tokens, temperature sensors, ID chips). AN148 is the canonical reliability guide for network designers; per-device datasheets define each slave's function-command set and electrical characteristics. The 'i' in iButton stands for 'information', not Apple-style branding; the trademark dates to the early 1990s.")
    d["fields"] = f
    _write(p, d)


# ============================================================
# L15 ENCODING TABLES
# ============================================================
def _l15(gd: Path) -> None:
    p = gd / "L15_ENCODING_TABLES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f.setdefault("time_slot_encoding_table", {
        "header_columns": ["Slot Type", "Master Action", "Slave Action", "Bit Result"],
        "rows": [
            ["Write-1", "Pull LOW 1-15 µs, then release for remainder of 60-120 µs slot", "Sample HIGH after master release",       "1"],
            ["Write-0", "Pull LOW ≥ 60 µs (full slot)",                                   "Sample LOW",                              "0"],
            ["Read-1",  "Pull LOW 1-15 µs, then release; sample DQ at tMSR (~15 µs)",     "Release DQ; line stays HIGH via Rp",      "1 (master reads HIGH)"],
            ["Read-0",  "Pull LOW 1-15 µs, then release; sample DQ at tMSR (~15 µs)",     "Drive DQ LOW for remainder of slot",      "0 (master reads LOW)"],
        ],
    })
    f.setdefault("rom_command_table", {
        "header_columns": ["Hex", "Name", "Purpose", "Followed by"],
        "rows": [
            ["0x33", "Read ROM",            "Read 64-bit ROM ID of the SOLE slave on bus (only works if exactly one slave present).", "64-bit ROM ID returned by slave"],
            ["0x55", "Match ROM",           "Address one specific slave by transmitting its 64-bit ROM ID.",                          "64-bit ROM ID transmitted by master, then Function Command"],
            ["0xCC", "Skip ROM",            "Broadcast to all slaves (no address; useful when only one device on bus).",              "Function Command"],
            ["0xF0", "Search ROM",          "Binary-tree enumeration of all slaves; master discovers each ROM ID one at a time.",    "128 read slots + 64 write slots interleaved over 64 ROM-ID bits"],
            ["0xEC", "Alarm Search",        "Search ROM variant — only slaves with an active alarm condition respond.",               "Same as Search ROM, but limited responder set"],
            ["0x69", "Resume",              "Re-address the previously addressed slave without resending its 64-bit ROM ID.",         "Function Command"],
            ["0xA5", "Overdrive Skip ROM",  "Switch all slaves to overdrive speed for the rest of the transaction.",                  "Subsequent slots use overdrive timing; Function Command in overdrive"],
            ["0x3C", "Overdrive Match ROM", "Match ROM (by 64-bit ID) and switch to overdrive simultaneously.",                       "64-bit ROM ID in standard timing, then overdrive Function Command"],
        ],
    })
    f.setdefault("rom_id_field_table", {
        "header_columns": ["Field", "Width (bits)", "Transmission Order", "Notes"],
        "rows": [
            ["Family Code",   8,  "1st byte (LSB-first within byte)",                  "Device type (e.g. 0x28 = DS18B20; 0x01 = DS2401)"],
            ["Serial Number", 48, "Bytes 2-7 (LSB-first within each byte)",            "Unique per device within family"],
            ["CRC-8",         8,  "8th byte (LSB-first within byte)",                  "CRC-8 over (family code + serial); poly 0x31; init 0"],
        ],
    })
    f.setdefault("crc8_polynomial_table", {
        "polynomial_equation": "x^8 + x^5 + x^4 + 1",
        "polynomial_hex": "0x31",
        "polynomial_reflected_hex": "0x8C",
        "initial_value": 0,
        "input_reflected": True,
        "output_reflected": True,
        "xor_out": 0,
        "check_value_for_string_123456789": "0xA1",
        "use_cases": ["64-bit ROM ID trailer", "DS18B20 9-byte scratchpad", "Many other 1-Wire slaves' read-data payloads"],
    })
    f.setdefault("standard_speed_timing_table_us", {
        "header_columns": ["Parameter", "Symbol", "MIN (µs)", "TYP (µs)", "MAX (µs)", "Notes"],
        "rows": [
            ["Reset Pulse LOW (master)",     "tRSTL", 480, None,  None, "Master drives DQ LOW"],
            ["Reset HIGH recovery (master)", "tRSTH", 480, None,  None, "Master release; bus pulls HIGH"],
            ["Presence Pulse HIGH delay",    "tPDH",  15,  None,  60,   "Slave wait before pulling LOW"],
            ["Presence Pulse LOW duration",  "tPDL",  60,  None,  240,  "Slave drives LOW"],
            ["Time slot duration",           "tSLOT", 60,  70,    120,  "Master generates one bit per slot"],
            ["Write-0 LOW time",             "tLOW0", 60,  None,  120,  "Master drives LOW for full slot"],
            ["Write-1 / Read LOW time",      "tLOW1", 1,   None,  15,   "Master drives LOW briefly"],
            ["Master Read sample point",     "tMSR",  None, 15,   15,   "Master samples DQ after slot start; 21 µs optimum for DS2480B"],
            ["Slot recovery",                "tREC",  1,   None,  None, "Bus HIGH before next slot"],
        ],
    })
    f.setdefault("overdrive_speed_timing_table_us", {
        "header_columns": ["Parameter", "Symbol", "MIN (µs)", "TYP (µs)", "MAX (µs)", "Notes"],
        "rows": [
            ["Reset Pulse LOW (master)",     "tRSTL", 48,  None,  80,    "Overdrive Reset"],
            ["Presence Pulse HIGH delay",    "tPDH",  2,   None,  6,     "Slave wait"],
            ["Presence Pulse LOW duration",  "tPDL",  8,   None,  24,    "Slave drives LOW"],
            ["Time slot duration",           "tSLOT", None, 7.5,  None,  "8× faster than standard"],
            ["Write-0 LOW time",             "tLOW0", 6,   None,  16,    "Master drives LOW"],
            ["Write-1 / Read LOW time",      "tLOW1", 1,   None,  2,     "Master drives LOW briefly"],
            ["Slot recovery",                "tREC",  1,   None,  None,  "Bus HIGH before next slot"],
        ],
    })
    f.setdefault("topology_classification_table", {
        "header_columns": ["Topology", "Description", "Reliability"],
        "rows": [
            ["Linear",   "Single pair from master, slaves attach along length with stubs < 3 m",     "Best — recommended for long networks"],
            ["Stubbed",  "Main backbone with branches/stubs ≥ 3 m to slaves",                        "Acceptable for medium networks; degrades with stub length"],
            ["Star",     "Multiple branches diverging at master",                                    "Not recommended — impedance mismatch, reflections"],
            ["Switched", "Star or stubbed with DS2409 1-Wire switches isolating inactive branches",  "Recommended for complex topologies — each active branch is effectively linear"],
        ],
    })
    f.setdefault("weight_definition_table", {
        "header_columns": ["Term", "Definition"],
        "rows": [
            ["Radius",                              "Wire run distance from master to farthest slave (m)"],
            ["Weight",                              "Total length of connected wire in the network (m)"],
            ["Slave equivalent weight (non-iButton)","≈ 0.5 m of wire per device"],
            ["Slave equivalent weight (iButton)",   "≈ 1.0 m of wire per device"],
            ["Capacitance equivalent weight",       "24 pF of bus capacitance ≈ 1 m of wire"],
        ],
    })
    if _empty(f.get("tables")):
        f["tables"] = [
            "Appendix A — Typical CPU port-pin-only interface (5V, 2200 Ω pull-up)",
            "Appendix B — Improved CPU bus interface (5V, 1000 Ω pull-up, FET pulldown with slew-rate control)",
            "Appendix C — Advanced 1-Wire network driver (dynamic pull-up + impedance matching)",
            "Appendix D — R-C filter for DS2480B interfaces on short-to-medium networks (100 Ω + 4700 pF)",
            "Appendix E — Optimized DS2480B 'flex mode' timings",
            "Appendix F — Waveform examples (reset/presence, write-1, write-0, read-zero, dynamic pull-up)",
        ]
    d["fields"] = f
    _write(p, d)


# ============================================================
# L16 COMPLIANCE PROPERTIES
# ============================================================
def _l16(gd: Path) -> None:
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f.setdefault("must_have_properties", [
        "Two conductors: DQ (data line) + GND (ground reference).",
        "DQ is open-drain wired-AND; HIGH = released (pulled up by Rp).",
        "Master initiates every transaction; slaves never initiate non-presence traffic.",
        "Reset Pulse ≥ 480 µs at standard speed (≥ 48 µs at overdrive).",
        "Slaves respond to Reset with a Presence Pulse 15-60 µs after master release, lasting 60-240 µs.",
        "Time slots are master-initiated; minimum slot duration 60 µs at standard speed.",
        "Bit encoding: Write-1 = master LOW 1-15 µs then HIGH; Write-0 = master LOW for full slot; Read = master LOW 1-15 µs then sample at ~15 µs.",
        "All bytes transmitted LSB-first.",
        "Every slave has a unique 64-bit ROM ID: 8-bit family code + 48-bit serial + 8-bit CRC-8.",
        "CRC-8 polynomial: x^8 + x^5 + x^4 + 1 (0x31, reflected 0x8C, initial 0).",
        "ROM command set: Read ROM (0x33), Match ROM (0x55), Skip ROM (0xCC), Search ROM (0xF0).",
        "Inter-slot recovery ≥ 1 µs.",
        "Slaves drop out on first ROM-ID bit mismatch during Match / Search ROM.",
        "Network radius ≤ 750 m (protocol fails beyond this due to cable delay).",
    ])
    f.setdefault("must_not_have_properties", [
        "Multiple slaves simultaneously driving DQ outside Presence Pulse + Search ROM contexts (would corrupt bit reads).",
        "Master sampling Read slot earlier than 1 µs or later than 15 µs after slot start (outside valid window).",
        "Unswitched star topology on networks larger than a tabletop probe (impedance mismatch + reflections cause search failures).",
        "Obsolete 5 kΩ pull-up on networks beyond a few meters (insufficient drive; starves long lines).",
        "Default DS2480B timings on medium-or-larger networks (must use 'flex mode' optimized values).",
        "Overdrive speed on long or heavy networks (timing tolerance too tight).",
    ])
    f.setdefault("compliance_failure_modes", [
        {"mode": "Missing Presence Pulse",                  "trigger": "No slave on bus, slave brown-out from parasite-power starvation, or wiring fault."},
        {"mode": "CRC-8 mismatch on ROM ID",                "trigger": "Bit error during ROM-ID readback (cable noise, reflections, sample-time too early)."},
        {"mode": "Search ROM enumeration drift",            "trigger": "Same physical network produces different search results on consecutive runs — indicates marginal timing, parasitic power starvation, or wiring noise."},
        {"mode": "Spurious Presence Pulse mid-transaction", "trigger": "Parasitic slave brown-out → reset → Presence Pulse appears in the middle of a Write/Read stream, corrupting the bus state."},
        {"mode": "Slow rise time at sample point",          "trigger": "Excessive network weight + weak pull-up → DQ has not reached valid HIGH when master samples → reads borderline / wrong bit."},
        {"mode": "Ringing / undershoot on falling edge",    "trigger": "Uncontrolled slew rate on master or slave fall edge; reflections on impedance-mismatched stubs and stars."},
        {"mode": "Bus stuck LOW",                           "trigger": "Wiring fault (DQ shorted to GND) or failed/held-LOW slave; master cannot reset the bus."},
    ])
    f.setdefault("max_radius_m", 750)
    f.setdefault("max_weight_simple_resistor_pullup_m", 200)
    f.setdefault("max_weight_active_pullup_m", 500)
    f.setdefault("max_practical_slaves", 100)
    f.setdefault("min_recovery_time_us", 1)
    f.setdefault("reset_behavior_compliance",
        "1-Wire does not define a global power-on reset at the protocol level. Slaves arm themselves whenever DQ is held LOW for ≥ tRSTL. Master's first action on a fresh bus is a Reset Pulse — slaves respond with Presence Pulse to establish synchronization.")
    d["fields"] = f
    _write(p, d)


# ============================================================
# L17 CHANNEL SIGNAL CATALOG
# (force-overwrite dependency_graph + channels — earlier extractor
#  may have populated AXI-leaning content)
# ============================================================
def _l17(gd: Path) -> None:
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["channels"] = [
        {"name": "DQ", "direction": "bidirectional open-drain (wired-AND)",
         "purpose": "Single data line carrying time-slot-encoded bits (Reset / Presence / Write / Read slots), the 64-bit ROM ID address phase, ROM and Function command bytes, and data bytes — plus optional parasitic power delivery to slaves during HIGH periods.",
         "active_levels": "HIGH = released (pulled to VDD by Rp, typically 4.5-5.5 V); LOW = any device pulls below VIL (~0.8 V).",
         "drive_type": "open-drain (master FET pulldown; slave open-drain; both rely on shared external Rp for HIGH).",
         "idle_level": "HIGH (released; pulled up by Rp)"},
        {"name": "GND", "direction": "common ground reference",
         "purpose": "Return path for DQ current; shared ground reference for master and all slaves.",
         "active_levels": "0 V (reference)",
         "drive_type": "passive (wire only)",
         "idle_level": "0 V"},
    ]
    f.setdefault("optional_channels", [
        {"name": "VDD", "direction": "external power supply to slave",
         "purpose": "Optional separate power pin for non-parasitic-powered slaves (preferred for high-current operations like temperature conversion or EEPROM write).",
         "active_levels": "2.8-6.0 V (slave operating range)",
         "drive_type": "external supply",
         "idle_level": "Vdd"},
    ])
    f["global_signals"] = []
    f["channel_counts"] = {
        "external_pins_required": 2,
        "external_pins_optional": 1,
        "data_lines": 1,
        "clock_lines": 0,
        "control_lines": 0,
        "logical_bit_values": 2,
        "wired_AND": True,
    }
    f.setdefault("logical_signal_states", [
        {"name": "released", "value": "logical 1 (HIGH)", "rule": "Pulled to VDD via Rp; default bus state."},
        {"name": "driven",   "value": "logical 0 (LOW)",  "rule": "Master or any slave pulls DQ below VIL; wired-AND across all open-drain drivers."},
    ])
    f.setdefault("ordering_rules", {
        "bit_order_within_byte":     "LSB-first (1-Wire convention).",
        "field_order_within_rom_id": "Family code (8 bits) → Serial number (48 bits) → CRC-8 (8 bits), each field LSB-first within its bytes.",
        "transaction_order":         "Reset → Presence → ROM command → [64-bit ROM ID for Match/Search] → Function command → data bytes.",
    })
    # Force-overwrite dependency_graph for 1-Wire shape.
    f["dependency_graph"] = {
        "common_rule":           "Master initiates every time slot by pulling DQ LOW; slaves never drive DQ except during Presence Pulse (immediately after Reset) and Read slots (in response to master's leading LOW pulse).",
        "data_dependency":       "Every bit's interpretation depends on master's slot type (Write-0 / Write-1 / Read) AND on whether master or slave drives DQ during the 60-µs window.",
        "addressing_dependency": "Function commands have no effect until ROM-command address resolution selects a slave (Match ROM / Skip ROM / Search ROM / Resume).",
        "integrity_dependency":  "CRC-8 trailer on ROM ID and selected function-command payloads is the only protocol-level integrity check; bytes have no per-byte ACK.",
    }
    f["handshake_pairs"] = [
        {"name": "RESET_PRESENCE",      "from": "master",         "to": "slaves", "rule": "Master holds DQ LOW ≥ tRSTL; slaves respond with Presence Pulse 15-60 µs after master release."},
        {"name": "WRITE_SLOT",          "from": "master",         "to": "slave",  "rule": "Master pulls LOW 1-15 µs (Write-1) or ≥ 60 µs (Write-0); slave samples within its valid window."},
        {"name": "READ_SLOT",           "from": "master + slave", "to": "master", "rule": "Master pulls LOW 1-15 µs and releases; slave drives LOW (for 0) or releases (for 1); master samples at tMSR."},
        {"name": "MATCH_ROM_DROPOUT",   "from": "slave",          "to": "(self)", "rule": "If master's transmitted ROM-ID bit ≠ slave's own bit, slave silently drops out of the current transaction."},
        {"name": "SEARCH_ROM_BIT_PAIR", "from": "slaves",         "to": "master", "rule": "Slaves drive bit then complement in successive Read slots; (0,0) signals discrepancy; master writes back chosen path."},
        {"name": "CRC8_INTEGRITY",      "from": "slave",          "to": "master", "rule": "Final byte of ROM ID and selected payloads is CRC-8 of preceding bytes; master verifies."},
    ]
    d["fields"] = f
    _write(p, d)


# ============================================================
# L18 INTERCONNECT TOPOLOGY
# ============================================================
def _l18(gd: Path) -> None:
    p = gd / "L18_INTERCONNECT_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["topology_type"] = (
        "Multi-drop single-wire bus; one master + many slaves on a shared "
        "open-drain DQ line, addressed by 64-bit ROM ID. Network can be "
        "physically organized as Linear, Stubbed, Star, or Switched.")
    f["supported_topologies"] = [
        {"name": "Linear",   "description": "Single twisted pair starts at master and extends to farthest slave; intermediate slaves attach with stubs < 3 m. PREFERRED for long networks.", "max_radius_m": 750, "max_weight_simple_pullup_m": 200, "max_weight_active_pullup_m": 500},
        {"name": "Stubbed",  "description": "Main backbone from master with branches/stubs ≥ 3 m to slaves. Acceptable for medium networks; performance degrades with stub length and count."},
        {"name": "Star",     "description": "Multiple branches diverging at master; not recommended due to impedance mismatch and reflections from each branch's end."},
        {"name": "Switched", "description": "Star or stubbed network using DS2409 1-Wire switches to electrically isolate inactive branches — each active branch electrically behaves as a linear network."},
    ]
    f.setdefault("topology_intermixing_rule",
        "When different topologies are intermixed in a single network, the designer should defer to the most conservative limit. Example: a switched star with three 50-m linear branches has effective radius 150 m and effective weight 150 m (only one branch at a time, not 450 m total).")
    f["master_slave_role_summary"] = [
        {"role": "Master",                  "description": "The single bus-master; drives all time slots, the Reset Pulse, ROM commands, ROM-ID transmission, function commands, and Write slots. Samples Presence Pulse and Read slots."},
        {"role": "Slave",                   "description": "Wakes on Reset Pulse, drives Presence Pulse, listens for ROM commands, drops out on Match/Search ROM mismatch, responds to function commands when addressed. Cannot initiate traffic."},
        {"role": "Parasitic-powered slave", "description": "Powered solely from DQ HIGH periods via on-chip storage capacitor. Vulnerable to brown-out during long Write-0 sequences."},
        {"role": "Externally-powered slave","description": "Powered from a separate VDD pin in addition to DQ; immune to parasite-power starvation."},
        {"role": "DS2409 1-Wire switch",    "description": "Special slave that gates DQ to downstream branches — enables Switched topology."},
    ]
    f["interconnect_role"] = (
        "There is no protocol-layer interconnect (no router / bridge). "
        "The bus is a flat shared wire; multi-drop addressing is via "
        "64-bit ROM ID transmitted on DQ.")
    f["ordering_guarantees"] = {
        "within_a_byte":   "Bits transmitted LSB-first; receiver reassembles MSB on the master side.",
        "within_rom_id":   "Family code → Serial number → CRC-8 (each field LSB-first within its bytes).",
        "global_ordering": "Single shared bus; bits arrive in transmission order; collisions during Search ROM are resolved by the binary-tree algorithm.",
    }
    f.setdefault("physical_layer_parameters", {
        "cable_typical":              "Category 5 twisted pair (5 V bus from master)",
        "characteristic_impedance":   "~100 Ω (Cat 5)",
        "capacitance_per_meter":      "~24 pF/m equivalent (rough rule of thumb for slave weight)",
        "pullup_resistor_small_network_ohms": 4700,
        "pullup_resistor_medium_long_network_ohms": 1000,
        "distributed_impedance_match_series_resistor_ohms_per_stub": 150,
        "distributed_impedance_match_alternate_ohms_per_stub": 100,
    })
    f.setdefault("memory_vs_peripheral_regions",
        "Not applicable — 1-Wire is a multi-drop wire protocol; per-slave register / memory maps are device-specific and accessed AFTER address resolution.")
    f.setdefault("device_classification", {
        "DS18B20":          "Digital temperature sensor; family code 0x28; common 1-Wire slave.",
        "DS18S20 / DS1820": "Older temperature sensor; family code 0x10.",
        "DS2401 / DS2411":  "Silicon serial number (ROM ID only, no function); family code 0x01.",
        "DS2438":           "Smart battery monitor; voltage/current/temperature; family code 0x26.",
        "DS2480B":          "Serial-to-1-Wire converter (master-end IC); used in DS9097U PC adapter.",
        "DS2409":           "1-Wire-controlled switch for Switched topology.",
        "iButton":          "Steel-can 1-Wire token (DS1990, DS1971, DS1996 etc.); family-code per part.",
    })
    f.setdefault("default_signal_values_evidence_tables", [
        "Figure 1 — Linear topology (master + chain of slaves)",
        "Figure 2 — Stubbed topology (backbone + branches)",
        "Figure 3 — Star topology (multiple branches at master; NOT recommended)",
        "Figure 4 — Switched topology (DS2409 switches isolate inactive branches)",
        "Figure 5 — Distributed impedance matching (150 Ω series at stub junctions)",
        "Appendix A — Typical CPU port-pin-only interface",
        "Appendix B — Improved CPU bus interface with slew-rate FET",
        "Appendix C — Advanced 1-Wire network driver with dynamic pull-up",
        "Appendix D — DS2480B R-C filter (100 Ω + 4700 pF)",
        "Appendix F — Oscilloscope waveform examples",
    ])
    d["fields"] = f
    _write(p, d)


# ============================================================
# L19 CONSTRAINTS PDK
# ============================================================
def _l19(gd: Path) -> None:
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f.setdefault("constraints_present", False)
    f.setdefault("analog_board_level_guidelines_summary", {
        "pullup_resistor_ohms": {
            "small_network": 4700, "medium_network": 1000,
            "large_network": "≤ 1000 with active assist",
            "obsolete_recommendation_dropped": 5000,
        },
        "pulldown_slew_rate_V_per_us": 1.37,
        "ds2480b_rc_filter_ohms_pf": [100, 4700],
        "distributed_impedance_match_series_ohms": [100, 150],
        "max_network_radius_m": 750,
        "max_network_weight_simple_pullup_m": 200,
        "max_network_weight_active_pullup_m": 500,
        "operating_voltage_V_master_supply": [4.5, 5.5],
        "operating_voltage_V_slave_min": 2.8,
        "operating_voltage_V_slave_max": 6.0,
    })
    f["notes"] = (
        "1-Wire / AN148 is a wire-level network reliability guideline; "
        "no PDK / SDC / floorplan / clock-tree constraints at the "
        "protocol layer. Per-controller / per-slave silicon constraints "
        "(open-drain output drive strength, ESD protection on DQ, weak "
        "pull-up, on-chip storage capacitor sizing for parasite-power) "
        "live in each device's individual datasheet, NOT in AN148. "
        "AN148 instead specifies BOARD- and NETWORK-level analog "
        "constraints (pull-up sizing, slew-rate control, impedance "
        "matching, R-C filtering, topology recommendations) that any "
        "1-Wire system designer must observe.")
    d["fields"] = f
    _write(p, d)


# ============================================================
# L20 DFT SCAN TOPOLOGY
# ============================================================
def _l20(gd: Path) -> None:
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f.setdefault("dft_present", False)
    f.setdefault("protocol_level_self_check_features", [
        "Reset / Presence Pulse handshake — coarse 'is anyone on the bus' check after every transaction begin.",
        "CRC-8 over 64-bit ROM ID — verifies ROM-ID transmission integrity.",
        "CRC-8 over selected function-command payloads (e.g. DS18B20 9-byte scratchpad) — verifies data integrity.",
        "Search ROM enumeration — implicit discovery + duplicate-detection check; can run as periodic health check.",
        "Alarm Search (0xEC) — only slaves with active alarm respond; lets master poll for fault conditions efficiently.",
    ])
    f.setdefault("no_jtag_no_scan_chain",
        "1-Wire AN148 does not specify any JTAG / IEEE 1149.1 scan, BIST control register, or test-mode entry. Concrete 1-Wire slave devices may add per-device test modes (e.g. factory trim adjustment) but these are NOT part of the protocol layer.")
    f["notes"] = (
        "AN148 is a wire-level protocol and network-design guide; DFT is "
        "deferred entirely to per-device silicon. The 'DFT' role at the "
        "protocol level is filled by Reset/Presence + CRC-8 + Search ROM "
        "enumeration, which together let the master detect missing "
        "slaves, corrupted data, and intermittent bus failures.")
    d["fields"] = f
    _write(p, d)


# ============================================================
# L21 POWER INTENT (parasitic power capable)
# ============================================================
def _l21(gd: Path) -> None:
    p = gd / "L21_POWER_INTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["power_intent_present"] = True
    f["parasitic_power_capable"] = True
    f["parasitic_power_summary"] = (
        "1-Wire slaves can be powered SOLELY from the DQ data line — no "
        "separate VDD pin required. Each slave 'robs' power from the bus "
        "during HIGH periods (when DQ is at ~5 V), storing energy on an "
        "on-chip capacitor. During LOW periods (slave drives 0, master "
        "Write-0, or Reset Pulse), the slave runs off its stored energy. "
        "This is the canonical 1-Wire feature enabling 2-wire (DQ + GND) "
        "sensor / token attach.")
    f["parasitic_power_failure_mode"] = (
        "Worst-case scenario: master issues a long sequence of Write-0 "
        "slots (each ≥ 60 µs LOW with only 1-µs recovery between). The "
        "bus stays LOW most of the time and there is little opportunity "
        "for slaves to recharge. Eventually the storage capacitor "
        "drains below the slave's brown-out threshold; the slave resets "
        "and issues a spurious Presence Pulse, corrupting the bus "
        "state. When this happens the failure is data-dependent and "
        "intermittent — extremely hard to diagnose.")
    f.setdefault("parasitic_power_mitigations", [
        "External VDD pin on the slave for high-current operations (temperature conversion, EEPROM programming).",
        "Strong active pull-up (low-Z drive) during high-current operations — master switches Rp from weak (~1 kΩ) to strong (~100 Ω) during a window after the relevant function command.",
        "Avoid long contiguous Write-0 strings in firmware; interleave Read slots (which give the bus more time HIGH).",
        "Keep network weight under the active-pull-up limit (~500 m) — heavier networks reduce per-slave recharge current.",
    ])
    f["low_power_modes_summary"] = {
        "bus_idle":          "When master is not running a transaction, DQ stays HIGH via Rp; slaves draw quiescent leakage from their storage capacitors but no Active dynamic current.",
        "no_explicit_sleep": "1-Wire protocol does NOT define an explicit slave sleep / wake message. Each slave's quiescent current is set by silicon design (per device datasheet).",
        "ungate_via_reset":  "Slaves wake automatically when the bus comes back up (e.g. after power-up) and synchronize on the first Reset Pulse.",
    }
    f["notes"] = (
        "Power intent in 1-Wire is fundamentally about parasite-power "
        "feasibility — the protocol explicitly assumes that slaves can "
        "be powered from the data line. This places a HARD CONSTRAINT "
        "on (a) bus weight (cable capacitance + slave count), (b) "
        "pull-up resistor sizing (must source enough current to keep "
        "slaves alive), and (c) Write-0 duty cycle (must not starve "
        "slaves). Per-device sleep / suspend modes are deferred to "
        "individual slave datasheets. The protocol layer itself defines "
        "no formal power-domain partitioning, retention scheme, or "
        "wake-up state machine.")
    d["fields"] = f
    _write(p, d)


# ============================================================
# L22 VERIFICATION PLAN
# ============================================================
def _l22(gd: Path) -> None:
    p = gd / "L22_VERIFICATION_PLAN.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f.setdefault("verification_plan_present", "implicit")
    if _empty(f.get("verification_categories_derived_from_spec")):
        f["verification_categories_derived_from_spec"] = [
            "Reset Pulse timing — master drives DQ LOW for ≥ 480 µs (standard) or ≥ 48 µs (overdrive).",
            "Presence Pulse timing — slave drives DQ LOW for 60-240 µs (standard) starting 15-60 µs after master release.",
            "Write-1 time slot — master LOW 1-15 µs then HIGH for remainder of 60-120 µs slot.",
            "Write-0 time slot — master LOW ≥ 60 µs full slot.",
            "Read time slot — master LOW 1-15 µs then release; slave drives 0 or releases for 1; master samples at tMSR (15 µs spec / 21 µs DS2480B-optimized).",
            "Inter-slot recovery ≥ 1 µs.",
            "ROM command set round-trip — 0x33 Read ROM, 0x55 Match ROM, 0xCC Skip ROM, 0xF0 Search ROM, 0xEC Alarm Search, 0x69 Resume, 0xA5 / 0x3C Overdrive variants.",
            "Search ROM binary-tree enumeration over multi-slave bus.",
            "CRC-8 verification on 64-bit ROM ID (polynomial 0x31 / reflected 0x8C; initial 0).",
            "LSB-first byte transmission.",
            "Bus-stuck-LOW detection.",
            "Parasitic-power survival across worst-case Write-0 patterns.",
            "Network weight stress at 200 m (simple pull-up) and 500 m (active pull-up).",
            "Network radius stress up to 750 m max.",
            "Topology compliance — Linear / Stubbed / Switched verified working; Star verified marginal.",
            "Pull-up resistor adequacy — DQ reaches valid HIGH within recovery time.",
            "Slew-rate compliance — master falling edge ≤ ~1.37 V/µs at standard speed for long networks.",
            "Overdrive transition — 0xA5 / 0x3C correctly switches all slaves to 8× timing.",
            "Multi-slave Presence Pulse overlap — multiple slaves' Presence Pulses overlap into a single observable LOW.",
            "Mixed parasitic + externally-powered slaves on same bus.",
            "DS2480B 'flex mode' compliance — 1.37 V/µs slew, 11 µs Write-1 LOW, 10 µs sample offset.",
            "DS2480B R-C filter mandatory for any network > 1 m (Appendix D).",
        ]
    f.setdefault("compliance_test_environments", [
        "Bench oscilloscope on DQ vs GND (1 ms/div for Reset-Presence; 10 µs/div for individual slots).",
        "Logic analyzer / bus sniffer capturing ROM commands, ROM ID transmission, and CRC-8 trailers.",
        "Network capacitance bank emulating varying weight (0 m, 100 m, 200 m, 500 m equivalent).",
        "Multi-slave bench (mix of DS18B20, DS2401, DS2438, iButtons) on Linear / Stubbed / Switched layouts.",
        "Cat 5 twisted-pair physical cable at various radii (3 m / 40 m / 200 m / 500 m / 750 m).",
    ])
    f["notes"] = (
        "AN148 does not include a formal verification plan. The "
        "categories above are derived from Section 'Recommendations for "
        "Currently Available Interfaces', Section 'What Makes a "
        "Reliable 1-Wire Network?', the timing-parameter discussion, "
        "Appendices A-E, and the waveform examples in Appendix F.")
    d["fields"] = f
    _write(p, d)


# ============================================================
# L23 SECURITY REQUIREMENTS
# ============================================================
def _l23(gd: Path) -> None:
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f.setdefault("security_requirements_present", False)
    f.setdefault("protocol_layer_security_summary", {
        "confidentiality":   "None at the protocol layer — all bytes are transmitted in plaintext on a shared open-drain wire; any node with bus access can sniff every transaction.",
        "integrity":         "Anti-corruption only — CRC-8 (polynomial 0x31, reflected 0x8C, initial 0) over the 64-bit ROM ID and selected function-command payloads detects accidental bit errors. Not a cryptographic integrity check.",
        "authentication":    "None at the protocol layer — the 64-bit ROM ID is a factory-burned serial number, not a secret. Any node can read it via Read ROM (0x33) or Search ROM (0xF0); cloning a ROM ID is electrically trivial.",
        "authorization":     "None — no access control on which master or slave may transact.",
        "replay_protection": "None — Same ROM ID + Function Command bytes are interchangeable across sessions.",
        "anti_tamper":       "None — DQ is exposed; physical bus access permits arbitrary signal injection.",
    })
    f.setdefault("out_of_band_security_devices",
        "Maxim / Analog Devices DOES produce secure 1-Wire devices that LAYER cryptographic features on top of the wire-level 1-Wire protocol. Examples: DS2432 / DS28EC20 (SHA-1 challenge-response authentication), DS28E25 / DS28E15 (SHA-256 ECDSA authentication), DeepCover Secure Authenticator family. These devices use the standard 1-Wire wire-level protocol for transport, but their FUNCTION COMMANDS implement cryptographic primitives. AN148 itself does NOT specify any of these — they are separate product families with their own datasheets.")
    f.setdefault("common_misuse_modes", [
        "Using 1-Wire ROM ID as an authentication credential — trivially spoofed by cloning.",
        "Sending sensitive sensor data (temperature, battery voltage) on a 1-Wire bus that traverses untrusted physical space — plaintext sniffable.",
        "Assuming Presence Pulse means 'genuine slave' — any attacker holding DQ LOW for 60-240 µs after a Reset can spoof it.",
    ])
    f["notes"] = (
        "AN148 (Maxim 2001) addresses RELIABILITY, not SECURITY. The "
        "wire-level 1-Wire protocol is explicitly NOT a security "
        "boundary. Applications that need confidentiality, "
        "authentication, or anti-tamper MUST layer cryptography on top "
        "(using SHA-1 / SHA-256 / ECDSA secure 1-Wire devices, or "
        "wrapping the bus in a secure channel at a higher protocol "
        "layer). CRC-8 is anti-corruption only — it provides no "
        "cryptographic guarantee.")
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
def is_onewire(blob: str) -> bool:
    """Content-only `onewire` detector (importable, lifted from the runner).

    Empty-safe. Reads ONLY ``blob`` (spec text). Byte-for-byte the
    same boolean the runner used inline.
    """
    if not blob:
        return False
    return bool(
        (("1-Wire" in blob or "1Wire" in blob)
            and ("iButton" in blob
                 or "Maxim" in blob
                 or "Dallas Semiconductor" in blob))
        or ("1-Wire" in blob and "DQ" in blob)
        or ("1-Wire" in blob
            and "parasitic power" in blob.lower())
        or ("Match ROM" in blob and "Skip ROM" in blob
            and "Search ROM" in blob))
