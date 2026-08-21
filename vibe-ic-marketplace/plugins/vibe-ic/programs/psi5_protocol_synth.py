"""Peripheral Sensor Interface 5 (PSI5) protocol synth helper.

PSI5 is an automotive sensor<->ECU interface built on a TWO-WIRE CURRENT
LOOP: the SAME two wires both supply power to the sensor (the ECU powers
the loop) and carry the sensor data. The sensor transmits by CURRENT
MODULATION — it draws modulated supply-current pulses (nominally +-26 mA
superimposed on the quiescent supply current) that are MANCHESTER-CODED so
the bit clock is embedded in the data. In SYNCHRONOUS mode the ECU emits a
SYNC PULSE (a voltage pulse on the supply) that triggers the sensor(s) to
transmit in defined TIME SLOTS (time-division multiplexing on a parallel
bus); in ASYNCHRONOUS mode the sensor transmits autonomously. Topologies
are point-to-point, parallel bus, and daisy-chain (universal timing). A
PSI5 telegram is a start condition + Manchester data bits + optional
region/status bits + a 2-bit/3-bit CRC or parity field. Bit rates are
125 / 189 kbps. PSI5-P is a point-to-point variant. Applies the
PSI5 Technical Specification (Peripheral Sensor Interface 5) spec-canonical
content to L1-L23.

Doctrine — GENERAL not keyword: detection uses canonical STRUCTURAL
wire-level signatures (two-wire current loop + current modulation +
Manchester coding + sync-pulse-triggered time slots) PLUS the canonical
protocol NAME / spec-id token read from L1/L2 CONTENT. It NEVER reads the
input-document filename or the benchmark folder name (the runner-side
detector predicate is evaluated on the L-doc CONTENT blob only).

Sibling disambiguation — PSI5 is an AUTOMOTIVE SENSOR interface, like SENT
(SAE J2716), LIN, and DALI. The closest sibling is SENT: both are
automotive sensor<->ECU links. The MUTEX:

  * SENT-primary: a SINGLE-SIGNAL-WIRE, falling-edge-to-falling-edge,
    NIBBLE pulse-width interface (12 + value ticks, 56-tick
    calibration pulse, SAE J2716, unit-time "ticks"). SENT carries data as
    VOLTAGE pulse-width on ONE dedicated signal wire — it is NOT a
    current-loop and NOT current-modulated and NOT Manchester-coded.
    PSI5 REQUIRES the two-wire current loop + current modulation +
    Manchester. So a SENT spec (nibble/tick/SAE J2716, no current loop)
    must DEFER.
  * LIN-primary: a UART-based single-master bus with a break field, sync
    field, and protected identifier (PID), master schedule table. LIN is
    voltage/UART, not a current loop. DEFER.
  * DALI-primary: a Manchester-coded LIGHTING control bus (digital
    addressable lighting interface). DALI does use Manchester, but it is a
    lighting bus, NOT a two-wire current-loop sensor interface with
    current modulation and sync-pulse time slots. DEFER unless the PSI5
    current-loop + current-modulation + PSI5-name signature is present.

SIGNATURE (the runner wires this; evaluated on the L1/L2 content blob,
never on a filename):

    is_psi5 = (
        ("PSI5" or "Peripheral Sensor Interface 5" in blob)
        AND (two-wire current loop)
        AND (current modulation)
        AND (Manchester)
        AND NOT (SENT-primary / LIN-primary / DALI-primary)
    )

Public entry: `apply_psi5_synth(generated_docs_dir, is_psi5, psi5_ic_name)`.
Module-level `is_psi5(blob)` is the content-only detector.
"""
from __future__ import annotations

import json
import re
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

# Canonical PSI5 structural facts (PSI5 Technical Specification).
_BIT_RATES_KBPS = [125, 189]
_NOMINAL_MOD_CURRENT_MA = 26  # +-26 mA current pulse on the loop
_CRC_PARITY_OPTIONS = ["parity bit", "2-bit CRC", "3-bit CRC"]
_TOPOLOGIES = ["point-to-point", "parallel bus", "daisy-chain (universal timing)"]


def _word(blob_low: str, token: str) -> bool:
    """Word-boundary token search on a lowercased blob."""
    return re.search(r"(?<![a-z0-9])" + re.escape(token) + r"(?![a-z0-9])",
                     blob_low) is not None


def is_psi5(blob: str) -> bool:
    """Content-only PSI5 detector with a SENT / LIN / DALI MUTEX.

    Fire on the PSI5 structural signature: a TWO-WIRE CURRENT LOOP (power +
    data on the same two wires) where the sensor transmits by CURRENT
    MODULATION of MANCHESTER-coded current pulses, with a SYNC PULSE that
    triggers transmission in TIME SLOTS (synchronous mode), named "PSI5" /
    "Peripheral Sensor Interface 5". Defer if the doc is SENT-primary
    (single-wire nibble/tick/SAE-J2716 voltage pulse-width), LIN-primary
    (UART break/sync/PID), or DALI-primary (Manchester lighting bus). Reads
    ONLY the spec text `blob` — never a filename or benchmark name — and
    NEVER keys on a bare folder/file token.
    """
    if not blob:
        return False
    low = blob.lower()

    # --- PSI5-only NAME tokens (word-boundary, structural spec identifiers). ---
    name_token = (
        _word(low, "psi5")
        or "psi-5" in low
        or "peripheral sensor interface 5" in low
    )

    # --- PSI5-only STRUCTURAL tokens. ---
    # Two-wire CURRENT LOOP — power + data on the same two wires.
    two_wire_current_loop = (
        ("current loop" in low
         and ("two-wire" in low or "two wire" in low or "2-wire" in low
              or "two wires" in low))
        or ("two-wire" in low and "current" in low
            and ("power" in low or "supply" in low) and "data" in low)
    )
    # Current modulation / current-mode signaling (the sensor modulates its
    # supply current to send data).
    current_modulation = (
        "current modulation" in low
        or "current-modulation" in low
        or "modulated supply current" in low
        or ("modulat" in low and "current" in low
            and ("ma" in low or "milliamp" in low or "26 ma" in low))
    )
    # Manchester coding of the current pulses.
    manchester = "manchester" in low
    # Synchronous mode: ECU sync pulse triggers transmission in time slots.
    sync_pulse_time_slots = (
        ("sync pulse" in low or "synchronization pulse" in low
         or "sync-pulse" in low)
        and ("time slot" in low or "time-slot" in low or "time slots" in low
             or "time-division" in low or "time division" in low)
    )
    # Loop-powered sensor (power and data share the two wires).
    loop_powered = (
        ("loop-powered" in low or "loop powered" in low)
        or ("powers the sensor" in low and "current loop" in low)
        or ("same two wires" in low
            and ("power" in low or "supply" in low) and "data" in low)
    )
    # Telegram + CRC/parity.
    telegram_crc = (
        ("telegram" in low or "start condition" in low)
        and (("crc" in low and ("2-bit" in low or "3-bit" in low
                                or "2 bit" in low or "3 bit" in low))
             or "parity" in low)
    )

    # PSI5 structural core: the defining current-loop + current-modulation +
    # Manchester signature. SENT/LIN/PWM do NOT have a current loop; LIN/SENT
    # are not Manchester current-modulated; DALI is Manchester but a lighting
    # bus, not a two-wire current-loop sensor link.
    psi5_structure = (
        two_wire_current_loop and current_modulation and manchester
    )

    # --- Sibling MUTEX (defer paths). ---
    # SENT-primary: single-signal-wire nibble pulse-width interface
    # (SAE J2716 / nibble / 56-tick calibration), VOLTAGE not current loop.
    sent_structure = (
        ("sae j2716" in low
         or "single edge nibble transmission" in low
         or "single-edge nibble transmission" in low)
        or ("nibble" in low
            and ("tick" in low or "ticks" in low)
            and ("12 + value" in low or "12+value" in low
                 or "56 tick" in low or "56-tick" in low
                 or "calibration pulse" in low))
    )
    sent_primary = sent_structure and not psi5_structure
    if sent_primary:
        return False

    # LIN-primary: UART-based bus with break/sync/PID + master schedule,
    # voltage/UART signalling — no current loop / current modulation.
    lin_primary = (
        (("lin" in low and "protected identifier" in low)
         or ("break field" in low and "sync field" in low
             and ("pid" in low or "protected identifier" in low)))
        and not psi5_structure
    )
    if lin_primary:
        return False

    # DALI-primary: Manchester-coded LIGHTING control bus — Manchester is
    # present but it is NOT a two-wire current-loop sensor interface with
    # current modulation + sync-pulse time slots.
    dali_primary = (
        manchester
        and ("digital addressable lighting" in low or "dali" in low
             or ("lighting" in low and "luminaire" in low))
        and not psi5_structure
    )
    if dali_primary:
        return False

    # --- Fire decision. ---
    # Require the PSI5 name token AND the current-loop + current-modulation +
    # Manchester structural core, plus at least one of the corroborating PSI5
    # features (sync-pulse time slots / loop-powered / telegram+CRC). This is
    # the canonical PSI5 wire-level signature; SENT/LIN/DALI do not have it.
    return bool(
        name_token and psi5_structure
        and (sync_pulse_time_slots or loop_powered or telegram_crc)
    )


def apply_psi5_synth(generated_docs_dir: Path, is_psi5_flag: bool,
                     psi5_ic_name: Optional[str]) -> None:
    """Apply PSI5 Technical Specification synth when the PSI5 signature matched."""
    if not is_psi5_flag:
        return
    gd = Path(generated_docs_dir)

    # --- Force ic_name across ALL 24 docs FIRST (main + fields docs). ---
    if psi5_ic_name is not None:
        for n in _MAIN_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                d["ic_name"] = psi5_ic_name
                _write(q, d)
        for n in _FIELDS_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                f = _ensure_dict(d, "fields")
                f["ic_name"] = psi5_ic_name
                d["ic_name"] = psi5_ic_name  # belt-and-braces top-level
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
# L1 — PSI5 datasheet header + headline facts.
# ----------------------------------------------------------------------
def _l1(gd: Path) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    d["document_title"] = "Peripheral Sensor Interface 5 (PSI5)"
    d["version"] = "PSI5 Technical Specification (Peripheral Sensor Interface 5)"
    d["revised_date"] = "PSI5 Technical Specification"
    d["manufacturer"] = "PSI5 Organization"
    d["copyright"] = "© PSI5 Organization"
    d["abstract"] = (
        "Peripheral Sensor Interface 5 (PSI5) is a two-wire, current-loop "
        "digital interface for connecting automotive sensors (such as airbag "
        "acceleration sensors and pressure sensors) to an electronic control "
        "unit (ECU). The SAME two wires both supply power to the sensor and "
        "carry the sensor data: the ECU powers the sensor over the two-wire "
        "current loop, and the sensor transmits its data back by current "
        "modulation — it draws a modulated supply current (a current pulse, "
        "nominally +-26 mA superimposed on the quiescent supply current) and "
        "the data bits are Manchester-coded onto this current. PSI5 has two "
        "operating modes: synchronous, in which the ECU sends a sync pulse (a "
        "voltage pulse on the supply) that triggers the sensor(s) to transmit "
        "in defined time slots (time-division multiplexing on a parallel "
        "bus), and asynchronous, in which the sensor transmits autonomously. "
        "Topologies are point-to-point, parallel bus, and daisy-chain "
        "(universal timing). A PSI5 telegram consists of a start condition, "
        "Manchester-coded data bits, optional region/status bits, and a "
        "2-bit or 3-bit CRC or a parity bit. Bit rates are 125 kbps and "
        "189 kbps. PSI5-P is a point-to-point variant.")
    d["keywords"] = [
        "PSI5", "Peripheral Sensor Interface 5", "two-wire current loop",
        "current loop", "current modulation", "Manchester coding", "telegram",
        "sync pulse", "time slot", "time-division", "synchronous mode",
        "asynchronous mode", "point-to-point", "parallel bus", "daisy chain",
        "universal timing", "loop-powered", "start condition", "CRC",
        "parity", "2-bit CRC", "3-bit CRC", "125 kbps", "189 kbps", "PSI5-P",
        "automotive sensor", "airbag", "acceleration sensor",
        "pressure sensor", "ECU",
    ]
    d["external_pins"] = [
        "PSI5 line A / line B: the two-wire current loop; the same two wires "
        "supply power to the sensor (from the ECU) and carry the sensor data "
        "by current modulation",
        "No separate data wire — data is carried as modulated current on the "
        "two supply wires",
        "No separate clock wire — Manchester coding embeds the bit clock in "
        "the current pulses; the ECU recovers timing from the mid-bit "
        "transitions",
        "Sync pulse is a voltage pulse the ECU applies on the two-wire supply "
        "(synchronous mode); no extra pin",
    ]
    d["physical_layer"] = "two-wire current loop (power + data on the same two wires)"
    d["signaling"] = (
        "current modulation (current-mode); nominal +-26 mA current pulses "
        "superimposed on the supply current")
    d["coding"] = "Manchester coding (self-clocking; embedded bit clock)"
    d["nominal_modulation_current_mA"] = _NOMINAL_MOD_CURRENT_MA
    d["bit_rates_kbps"] = list(_BIT_RATES_KBPS)
    d["error_check_options"] = list(_CRC_PARITY_OPTIONS)
    d["modes_of_operation"] = [
        {"name": "Synchronous mode",
         "description": "The ECU sends a sync pulse (a voltage pulse on the "
         "two-wire supply) that triggers the sensor(s) to transmit in defined "
         "time slots. On a parallel bus, multiple sensors each transmit in "
         "their own time slot (time-division multiplexing) following the same "
         "sync pulse."},
        {"name": "Asynchronous mode",
         "description": "The sensor transmits its telegrams autonomously on "
         "its own internal timing, without an ECU sync pulse; typically used "
         "for a single point-to-point sensor."},
    ]
    d["key_features"] = [
        "Two-wire current loop: the same two wires power the sensor and carry "
        "the data — no separate data or clock wire.",
        "Loop-powered sensor: the ECU supplies the sensor over the loop; the "
        "sensor draws its operating current from the same two wires.",
        "Current modulation: the sensor sends data by modulating its supply "
        "current (nominal +-26 mA pulses); the ECU senses the loop current.",
        "Manchester coding embeds the bit clock in the current pulses so no "
        "clock wire is needed.",
        "Synchronous mode: an ECU sync pulse (voltage pulse on the supply) "
        "triggers transmission in defined time slots.",
        "Time-division multiplexing: on a parallel bus, several sensors "
        "transmit in distinct time slots after one sync pulse.",
        "Asynchronous mode: the sensor transmits autonomously without a sync "
        "pulse.",
        "Topologies: point-to-point, parallel bus, and daisy-chain (universal "
        "timing).",
        "Telegram = start condition + Manchester data bits + optional "
        "region/status bits + 2-bit/3-bit CRC or parity.",
        "Bit rates 125 kbps and 189 kbps.",
        "PSI5-P point-to-point variant.",
        "Targets automotive safety/powertrain sensors (airbag/acceleration/"
        "pressure) with low wiring count.",
    ]
    d["topology_summary"] = (
        "PSI5 connects automotive sensors to an ECU over a two-wire current "
        "loop. It supports point-to-point (one sensor, including the PSI5-P "
        "variant), parallel bus (several sensors sharing one loop, each in its "
        "own time slot in synchronous mode), and daisy-chain (universal "
        "timing) topologies.")
    d["use_cases"] = [
        "Airbag / restraint crash sensors (satellite acceleration sensors)",
        "Side-impact and other pressure sensors",
        "Acceleration sensors",
        "Other automotive safety, chassis, and powertrain sensors",
    ]
    d["overview"] = (
        "Peripheral Sensor Interface 5 (PSI5) defines how a remote automotive "
        "sensor communicates with an ECU over just two wires. The two wires "
        "form a current loop: the ECU is the supply (it powers the sensor over "
        "the loop) and the sensor is the data transmitter. Rather than "
        "switching a voltage on a dedicated data line, the sensor transmits by "
        "modulating the current it draws from the supply — a current-mode "
        "physical layer with nominal +-26 mA current pulses. The data is "
        "Manchester-coded onto the current pulses so the bit clock is embedded "
        "and no separate clock wire is required. In synchronous mode the ECU "
        "emits a sync pulse that triggers the sensor(s) to transmit in defined "
        "time slots (time-division on a parallel bus); in asynchronous mode "
        "the sensor transmits autonomously. PSI5 telegrams carry a start "
        "condition, Manchester data bits, optional region/status bits, and a "
        "2-bit/3-bit CRC or parity, at 125 or 189 kbps. PSI5-P is a "
        "point-to-point variant.")
    d["revision_history"] = [
        {"version": "PSI5", "date": "Peripheral Sensor Interface 5",
         "description": "Two-wire current-loop automotive sensor interface: "
         "loop-powered sensor, current modulation, Manchester coding, "
         "synchronous (sync-pulse time slots) and asynchronous modes, "
         "point-to-point / parallel-bus / daisy-chain topologies, telegram "
         "with 2-bit/3-bit CRC or parity, 125/189 kbps, PSI5-P variant."},
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L2 — FRS / protocol_overview.
# ----------------------------------------------------------------------
def _l2(gd: Path) -> None:
    p = gd / "L2_FRS.json"
    if not p.is_file():
        return
    d = _read(p)
    po = _ensure_dict(d, "protocol_overview")
    po["type"] = (
        "Two-wire current-loop automotive sensor<->ECU interface. The same "
        "two wires supply power to the sensor (ECU-powered loop) and carry "
        "the sensor data by current modulation of Manchester-coded current "
        "pulses. Point-to-point or bus-capable; bit rates 125/189 kbps.")
    po["duplex"] = (
        "Asymmetric: ECU -> sensor is power (and, in synchronous mode, a sync "
        "pulse); sensor -> ECU is data by current modulation on the same two "
        "wires.")
    po["physical_layer"] = "two-wire current loop (power + data shared)"
    po["signaling"] = (
        "current modulation (current-mode); nominal +-26 mA current pulses "
        "on the supply current")
    po["encoding"] = (
        "Manchester coding of the current pulses — each bit has a mid-bit "
        "transition so the bit clock is embedded; the ECU recovers timing "
        "from the Manchester transitions, so no clock wire is needed.")
    po["loop_powered"] = True
    po["bit_rates_kbps"] = list(_BIT_RATES_KBPS)
    po["operating_modes"] = [
        "Synchronous (ECU sync pulse triggers transmission in time slots; "
        "time-division on a parallel bus)",
        "Asynchronous (sensor transmits autonomously without a sync pulse)",
    ]
    po["sync_pulse"] = (
        "A voltage pulse the ECU applies on the two-wire supply; in "
        "synchronous mode it triggers the sensor(s) to transmit in their "
        "assigned time slots.")
    po["time_slots"] = (
        "In synchronous mode each sensor on a parallel bus transmits in its "
        "own time slot relative to the sync pulse (time-division "
        "multiplexing).")
    po["topologies"] = list(_TOPOLOGIES)
    po["telegram_fields"] = [
        "Start condition (start bits marking the beginning of the telegram)",
        "Manchester-coded data bits (the measurement word; length "
        "configurable)",
        "Optional region / status bits",
        "Error check: a 2-bit CRC, a 3-bit CRC, or a parity bit (depending on "
        "data word length)",
    ]
    po["error_check"] = (
        "Each telegram is protected by a 2-bit CRC, a 3-bit CRC, or a parity "
        "bit, depending on the configured data word length; the ECU discards "
        "telegrams that fail the check.")
    po["variants"] = ["PSI5-P (point-to-point variant)"]
    d["functional_requirements"] = [
        {"id": "FR-LOOP-01", "text": "PSI5 uses a two-wire current loop: the "
         "same two wires supply power to the sensor (from the ECU) and carry "
         "the sensor data. There is no separate data wire and no separate "
         "clock wire."},
        {"id": "FR-PWR-02", "text": "The sensor is loop-powered — it draws "
         "its operating current from the same two wires it uses to transmit "
         "data; the ECU powers the loop."},
        {"id": "FR-MOD-03", "text": "The sensor transmits data by current "
         "modulation: it modulates the supply current it draws, producing "
         "current pulses (nominal +-26 mA) that the ECU senses on the loop."},
        {"id": "FR-MAN-04", "text": "The current pulses are Manchester-coded "
         "so that each bit has a mid-bit transition; the bit clock is "
         "embedded and the ECU recovers timing without a clock wire."},
        {"id": "FR-SYNC-05", "text": "In synchronous mode the ECU sends a "
         "sync pulse (a voltage pulse on the supply) that triggers the "
         "sensor(s) to transmit in defined time slots."},
        {"id": "FR-TDM-06", "text": "On a parallel bus, multiple sensors "
         "share one two-wire current loop and each transmits in its own time "
         "slot relative to the sync pulse (time-division multiplexing)."},
        {"id": "FR-ASYNC-07", "text": "In asynchronous mode the sensor "
         "transmits its telegrams autonomously on its own timing, without an "
         "ECU sync pulse."},
        {"id": "FR-TOPO-08", "text": "PSI5 supports point-to-point, parallel "
         "bus, and daisy-chain (universal timing) topologies on the two-wire "
         "current loop."},
        {"id": "FR-TELE-09", "text": "A PSI5 telegram consists of a start "
         "condition, Manchester-coded data bits, optional region/status bits, "
         "and an error-check field (2-bit CRC, 3-bit CRC, or parity)."},
        {"id": "FR-CRC-10", "text": "The telegram error-check field is a "
         "2-bit CRC, a 3-bit CRC, or a parity bit depending on the configured "
         "data word length; telegrams failing the check are discarded."},
        {"id": "FR-RATE-11", "text": "PSI5 supports bit rates of 125 kbps and "
         "189 kbps."},
        {"id": "FR-VAR-12", "text": "PSI5-P is a point-to-point variant for a "
         "single sensor on a dedicated two-wire current loop using the same "
         "current-loop, current-modulation, Manchester-coded physical layer."},
    ]
    d["error_response_conditions"] = [
        "Telegram CRC (2-bit/3-bit) or parity check fails — the ECU discards "
        "the corrupted telegram.",
        "Missing telegram in an expected time slot (synchronous mode).",
        "Loss of the sync pulse — sensors cannot be triggered in synchronous "
        "mode.",
        "Out-of-range loop current — supply / sensor fault detection by the "
        "ECU.",
    ]
    d["compliance_requirements"] = [
        "Two-wire current loop powering the sensor and carrying the data on "
        "the same two wires.",
        "Current-modulation transmission (nominal +-26 mA current pulses).",
        "Manchester coding of the data bits (embedded bit clock).",
        "Synchronous mode with an ECU sync pulse triggering time-slot "
        "transmission, and asynchronous mode.",
        "Telegram framing: start condition + data bits + optional "
        "region/status + 2-bit/3-bit CRC or parity.",
        "Support for point-to-point, parallel-bus, and daisy-chain "
        "(universal timing) topologies.",
        "Bit rates 125 kbps and 189 kbps.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L3 — command/protocol: telegram framing + current-loop channel model.
# ----------------------------------------------------------------------
def _l3(gd: Path) -> None:
    p = gd / "L3_CMD_PROTOCOL.json"
    if not p.is_file():
        return
    d = _read(p)
    d["protocol_type"] = (
        "Two-wire current-loop sensor telegram protocol. The sensor transmits "
        "Manchester-coded telegrams to the ECU by current modulation on the "
        "two-wire current loop; the ECU powers the loop and (in synchronous "
        "mode) emits a sync pulse to trigger time-slot transmission.")
    d["channels"] = [
        {"name": "Two-wire current loop (line A / line B)",
         "direction": "ECU -> sensor power; sensor -> ECU data (current "
                      "modulation)",
         "description": "The same two wires supply power to the sensor and "
         "carry the sensor data. The sensor modulates its supply current "
         "(nominal +-26 mA) to send Manchester-coded telegrams; the ECU "
         "senses the loop current to receive them."},
        {"name": "Sync pulse (on the two-wire supply)",
         "direction": "ECU -> sensor",
         "description": "In synchronous mode the ECU applies a voltage pulse "
         "on the supply to trigger the sensor(s) to transmit in defined time "
         "slots."},
    ]
    d["telegram_format"] = {
        "start_condition": "Start bits marking the beginning of the telegram "
                           "so the ECU can detect the start of a "
                           "Manchester-coded data word.",
        "data_bits": "Manchester-coded sensor data bits (the measurement "
                     "word); the data word length is configurable.",
        "region_status_bits": "Optional bits carrying region/range or status "
                              "information.",
        "error_check": "A 2-bit CRC, a 3-bit CRC, or a parity bit, depending "
                       "on the configured data word length.",
        "transmission": "The telegram is sent as Manchester-coded current "
                        "pulses on the two-wire current loop, from start "
                        "condition to CRC/parity.",
    }
    d["error_check_field"] = {
        "options": list(_CRC_PARITY_OPTIONS),
        "selection_rule": "Short data words use a parity bit or a 2-bit CRC; "
                          "longer data words use a 3-bit CRC.",
    }
    d["operating_modes"] = {
        "synchronous": "ECU sync pulse triggers the sensor(s) to transmit in "
                       "defined time slots (time-division on a parallel bus).",
        "asynchronous": "Sensor transmits telegrams autonomously without a "
                        "sync pulse.",
    }
    d["addressing"] = {
        "note": "PSI5 has no explicit per-frame address; on a parallel bus in "
                "synchronous mode, sensors are distinguished by their assigned "
                "TIME SLOT relative to the ECU sync pulse, not by an address "
                "field.",
        "slot_based": True,
    }
    d["frame_format"] = {
        "line_coding": "Manchester (mid-bit transition per bit; embedded bit "
                       "clock).",
        "physical": "current modulation on a two-wire current loop (nominal "
                    "+-26 mA pulses).",
        "framing": "Telegram = start condition + Manchester data bits + "
                   "optional region/status bits + 2-bit/3-bit CRC or parity.",
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L4 — register map (PSI5 is a sensor link; ECU-side config registers).
# ----------------------------------------------------------------------
def _l4(gd: Path) -> None:
    p = gd / "L4_REGMAP.json"
    if not p.is_file():
        return
    d = _read(p)
    d["register_map_present"] = False
    d["notes"] = (
        "PSI5 is a two-wire current-loop sensor protocol; it does not define a "
        "software register map as a protocol concept. The ECU-side PSI5 "
        "controller exposes implementation-defined configuration for the loop "
        "(operating mode synchronous/asynchronous, sync-pulse period, time-slot "
        "assignment, bit rate 125/189 kbps, telegram length, CRC/parity "
        "selection); the sensor's own configuration is sensor-specific.")
    d["ecu_controller_config_groups"] = [
        {"group": "Loop / mode configuration", "fields": [
            "Operating mode (synchronous / asynchronous)",
            "Sync-pulse period (synchronous mode)",
            "Bit rate (125 kbps / 189 kbps)",
            "Topology (point-to-point / parallel bus / daisy-chain)"]},
        {"group": "Time-slot configuration", "fields": [
            "Number of time slots / sensors on the loop",
            "Per-slot offset relative to the sync pulse"]},
        {"group": "Telegram configuration", "fields": [
            "Data word length",
            "Error-check selection (parity / 2-bit CRC / 3-bit CRC)",
            "Region/status-bit presence"]},
        {"group": "Status / diagnostics", "fields": [
            "Loop current status / out-of-range detection",
            "Per-slot telegram-received / CRC-error counters"]},
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L5 — analog/electrical interface: current loop + current modulation.
# ----------------------------------------------------------------------
def _l5(gd: Path) -> None:
    p = gd / "L5_ADI_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["analog_digital_interface_present"] = True
    d["signaling_summary"] = (
        "PSI5 is a current-mode interface on a two-wire current loop. The ECU "
        "applies a supply voltage across the two wires and powers the sensor; "
        "the sensor transmits by current modulation — it draws a modulated "
        "supply current, producing current pulses of nominally +-26 mA "
        "superimposed on its quiescent supply current. The ECU senses the "
        "loop current (e.g. with a sense resistor in the supply path) to "
        "receive the Manchester-coded data. In synchronous mode the ECU "
        "applies a voltage sync pulse on the supply to trigger transmission.")
    d["physical_layer"] = "two-wire current loop"
    d["modulation"] = (
        "current modulation (current-mode); nominal +-26 mA current pulses on "
        "the supply current")
    d["nominal_modulation_current_mA"] = _NOMINAL_MOD_CURRENT_MA
    d["line_coding"] = "Manchester (embedded bit clock)"
    d["clocking"] = (
        "No separate clock wire. Manchester coding embeds the bit clock in the "
        "current pulses; the ECU recovers bit timing from the mid-bit "
        "transitions.")
    d["bit_rates_kbps"] = list(_BIT_RATES_KBPS)
    d["power_delivery"] = (
        "The sensor is loop-powered: the ECU supplies energy over the same "
        "two-wire current loop that carries the data. The sensor's quiescent "
        "supply current is the carrier on which the +-26 mA data modulation "
        "is superimposed.")
    d["sync_pulse"] = {
        "type": "voltage pulse on the two-wire supply",
        "role": "triggers sensor transmission in defined time slots "
                "(synchronous mode)",
    }
    d["receiver_specs_canonical"] = {
        "sensing": "ECU senses the modulated loop current to recover the "
                   "Manchester-coded telegram.",
        "decoding": "Manchester decode -> telegram (start condition, data "
                    "bits, optional region/status, CRC/parity).",
        "bit_rates_kbps": list(_BIT_RATES_KBPS),
    }
    d["transmitter_specs_canonical"] = {
        "device": "sensor (loop-powered)",
        "method": "current modulation of the supply current",
        "nominal_current_pulse_mA": _NOMINAL_MOD_CURRENT_MA,
        "coding": "Manchester",
        "bit_rates_kbps": list(_BIT_RATES_KBPS),
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L6 — control logic: sensor TX FSM + ECU RX/sync FSM.
# ----------------------------------------------------------------------
def _l6(gd: Path) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["fsm_states_sensor_tx"] = [
        {"name": "POWER_UP", "description": "Sensor powers up from the "
         "two-wire current loop supplied by the ECU; quiescent supply current "
         "established."},
        {"name": "IDLE", "description": "Sensor idle. In synchronous mode it "
         "waits for the ECU sync pulse; in asynchronous mode it runs its own "
         "transmit timer."},
        {"name": "WAIT_SLOT", "description": "Synchronous mode: after the sync "
         "pulse, wait until the sensor's assigned time slot."},
        {"name": "TX_START", "description": "Drive the telegram start "
         "condition (start bits) by current modulation."},
        {"name": "TX_DATA", "description": "Transmit the Manchester-coded data "
         "bits (and optional region/status bits) as +-26 mA current pulses."},
        {"name": "TX_CRC", "description": "Transmit the error-check field "
         "(2-bit/3-bit CRC or parity) and end the telegram."},
    ]
    d["fsm_states_ecu_rx"] = [
        {"name": "RX_IDLE", "description": "ECU powers the loop and monitors "
         "the loop current."},
        {"name": "SYNC_EMIT", "description": "Synchronous mode: ECU emits the "
         "sync pulse (voltage pulse on the supply) to trigger the sensors."},
        {"name": "RX_SLOT", "description": "ECU samples each time slot for a "
         "sensor telegram (synchronous mode)."},
        {"name": "RX_DECODE", "description": "Manchester-decode the modulated "
         "current pulses into a telegram."},
        {"name": "RX_CHECK", "description": "Verify the telegram CRC/parity; "
         "accept on pass, discard on fail."},
    ]
    d["fsm_hints"] = {
        "trigger": "Synchronous mode: the ECU sync pulse triggers sensors to "
        "transmit in time slots. Asynchronous mode: the sensor's own timer "
        "triggers transmission.",
        "rule": "Each telegram is Manchester-coded and protected by a "
        "2-bit/3-bit CRC or parity; the ECU discards telegrams that fail the "
        "check.",
    }
    d["exit_from_reset_or_poweron"] = (
        "On power-up the sensor draws its quiescent current from the two-wire "
        "loop. In synchronous mode it then waits for the ECU sync pulse and "
        "transmits in its assigned time slot; in asynchronous mode it begins "
        "transmitting autonomously.")
    d["configurations"] = [
        {"name": "Synchronous parallel bus", "description": "Multiple sensors "
         "on one loop; each transmits in its time slot after the sync pulse "
         "(time-division)."},
        {"name": "Asynchronous point-to-point", "description": "A single "
         "sensor transmits autonomously over a dedicated loop."},
        {"name": "Daisy-chain (universal timing)", "description": "Sensors in "
         "a daisy chain with the PSI5 universal timing model."},
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L7 — test/debug observability.
# ----------------------------------------------------------------------
def _l7(gd: Path) -> None:
    p = gd / "L7_TEST_DEBUG.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_debug_architecture_present"] = True
    d["spec_provided_observability"] = [
        {"name": "Loop current monitoring", "purpose": "The ECU senses the "
         "modulated loop current; out-of-range current indicates a fault."},
        {"name": "Telegram CRC / parity", "purpose": "Per-telegram 2-bit/"
         "3-bit CRC or parity lets the ECU detect corrupted telegrams."},
        {"name": "Time-slot occupancy", "purpose": "In synchronous mode the "
         "ECU observes which time slots returned a telegram and flags "
         "missing ones."},
        {"name": "Sync-pulse presence", "purpose": "Loss of the ECU sync "
         "pulse stops synchronous transmission — a detectable condition."},
    ]
    d["error_detection_mechanisms"] = [
        "Telegram 2-bit/3-bit CRC or parity detects bit errors.",
        "Missing telegram in an expected time slot (synchronous mode).",
        "Out-of-range loop current (supply / sensor fault).",
        "Loss of sync pulse in synchronous mode.",
    ]
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
        "PHYSICAL_LAYER": "two-wire current loop",
        "SIGNALING": "current modulation",
        "LINE_CODING": "Manchester",
        "NOMINAL_MODULATION_CURRENT_MA": _NOMINAL_MOD_CURRENT_MA,
        "BIT_RATES_KBPS": list(_BIT_RATES_KBPS),
        "CRC_OPTIONS_BITS": [2, 3],
        "PARITY_SUPPORTED": True,
        "LOOP_POWERED": True,
        "SYNC_MODE_SUPPORTED": True,
        "ASYNC_MODE_SUPPORTED": True,
        "TIME_DIVISION_MULTIPLEX": True,
    })
    kc = _ensure_dict(d, "key_constants_for_RTL_authoring")
    kc.update({
        "is_current_loop": True,
        "is_current_modulated": True,
        "is_manchester": True,
        "embedded_clock": True,
        "two_wire": True,
        "loop_powered": True,
        "sync_pulse_triggered_time_slots": True,
        "bit_rates_kbps": list(_BIT_RATES_KBPS),
        "crc_options_bits": [2, 3],
        "parity_supported": True,
        "topologies": list(_TOPOLOGIES),
    })
    d["telegram_format_constants"] = {
        "start_condition": True,
        "manchester_data_bits": True,
        "region_status_bits_optional": True,
        "error_check_options": list(_CRC_PARITY_OPTIONS),
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
    d["current_loop_waveform"] = {
        "physical": "current modulation on a two-wire current loop",
        "nominal_pulse_mA": _NOMINAL_MOD_CURRENT_MA,
        "coding": "Manchester (mid-bit transition per bit; embedded clock)",
        "note": "The sensor superimposes +-26 mA current pulses on its "
                "quiescent supply current; the ECU senses the loop current.",
    }
    d["telegram_waveform"] = {
        "order": "start condition -> Manchester data bits -> optional "
                 "region/status bits -> 2-bit/3-bit CRC or parity",
        "bit_rates_kbps": list(_BIT_RATES_KBPS),
    }
    d["sync_pulse_waveform"] = {
        "type": "voltage pulse on the two-wire supply (ECU)",
        "role": "triggers sensor transmission in time slots (synchronous "
                "mode)",
    }
    d["time_slot_waveform"] = {
        "synchronous": "After the sync pulse, each sensor transmits its "
                       "telegram in its assigned time slot (time-division on "
                       "a parallel bus).",
    }
    d["general_timing_rule"] = (
        "PSI5 is self-clocked via Manchester coding (the bit clock is embedded "
        "in the current pulses). In synchronous mode the ECU sync pulse sets "
        "the timing reference and sensors transmit in fixed time slots "
        "relative to it; in asynchronous mode each sensor uses its own "
        "internal timing. Bit period is set by the 125 or 189 kbps bit rate.")
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
        "Automotive sensor<->ECU interface over a two-wire current loop: the "
        "ECU powers the loop and the sensor transmits Manchester-coded "
        "telegrams by current modulation. Supports synchronous (sync-pulse "
        "time slots) and asynchronous modes and point-to-point / parallel-bus "
        "/ daisy-chain topologies, at 125/189 kbps.")
    d["topology_description"] = (
        "Two-wire current loop between the ECU and one or more sensors. "
        "Point-to-point (one sensor; PSI5-P variant), parallel bus (several "
        "sensors sharing the loop, each in its own time slot in synchronous "
        "mode), and daisy-chain (universal timing) topologies are supported.")
    io = _ensure_dict(d, "integration_overview")
    io.update({
        "physical_layer": "two-wire current loop (power + data shared)",
        "signaling": "current modulation (nominal +-26 mA)",
        "line_coding": "Manchester",
        "loop_powered": True,
        "bit_rates_kbps": list(_BIT_RATES_KBPS),
        "operating_modes": ["synchronous", "asynchronous"],
        "sync_pulse": "voltage pulse on the supply triggers time-slot "
                      "transmission (synchronous mode)",
        "topologies": list(_TOPOLOGIES),
        "telegram": "start condition + Manchester data bits + optional "
                    "region/status bits + 2-bit/3-bit CRC or parity",
        "variants": ["PSI5-P (point-to-point)"],
    })
    d["interface_categories"] = [
        "Sensor side — loop-powered transmitter; current-modulates the "
        "Manchester-coded telegram onto the two-wire loop.",
        "ECU side — powers the loop, emits the sync pulse (synchronous mode), "
        "and senses/decodes the loop current.",
        "Two-wire current loop — shared power + data medium.",
    ]
    d["interconnect_topologies_supported"] = list(_TOPOLOGIES)
    d["soc_dependent_items"] = [
        "Operating mode (synchronous vs asynchronous) and sync-pulse period.",
        "Bit rate (125 / 189 kbps).",
        "Topology (point-to-point / parallel bus / daisy-chain) and time-slot "
        "assignment.",
        "Telegram data-word length and error-check selection (parity / 2-bit "
        "/ 3-bit CRC).",
        "Loop supply voltage, current-sense implementation, and sensor power "
        "budget.",
    ]
    d["device_classes_examples"] = [
        "Airbag satellite acceleration sensor",
        "Side-impact pressure sensor",
        "Powertrain / chassis sensor",
        "ECU-side PSI5 receiver / loop controller",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L10 — test cases / compliance categories.
# ----------------------------------------------------------------------
def _l10(gd: Path) -> None:
    p = gd / "L10_TEST_CASES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_cases_present"] = (
        "partial - the specification defines behaviors (current-loop "
        "signaling, telegram framing, sync/async modes, CRC/parity) that map "
        "to compliance test categories; it does not include a full testbench.")
    d["derived_compliance_test_categories"] = [
        "Two-wire current loop powers the sensor (loop-powered) and carries "
        "data on the same wires.",
        "Current modulation: sensor transmits by +-26 mA current pulses; ECU "
        "senses loop current.",
        "Manchester coding: embedded bit clock; ECU recovers timing from "
        "mid-bit transitions.",
        "Synchronous mode: ECU sync pulse triggers transmission in time "
        "slots.",
        "Time-division: multiple sensors on a parallel bus transmit in "
        "distinct time slots.",
        "Asynchronous mode: sensor transmits autonomously.",
        "Telegram framing: start condition + data bits + optional "
        "region/status + CRC/parity.",
        "Error check: 2-bit CRC, 3-bit CRC, or parity per data word length; "
        "corrupted telegrams discarded.",
        "Bit rates: 125 kbps and 189 kbps.",
        "Topologies: point-to-point, parallel bus, daisy-chain (universal "
        "timing).",
        "PSI5-P point-to-point variant.",
        "Fault handling: out-of-range loop current, missing telegram, lost "
        "sync pulse.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L11 — OTP / factory-burned (N/A for PSI5).
# ----------------------------------------------------------------------
def _l11(gd: Path) -> None:
    p = gd / "L11_OTP_CONTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    d["otp_present"] = False
    d["notes"] = (
        "PSI5 does not define OTP/fuse content as a protocol concept. "
        "Interface configuration (operating mode, bit rate, time-slot "
        "assignment, telegram length, CRC/parity selection) is "
        "implementation/sensor-specific; an implementation may back some "
        "settings with fuses, but the PSI5 specification does not require it.")
    _write(p, d)


# ----------------------------------------------------------------------
# L12 — behavioral sequences.
# ----------------------------------------------------------------------
def _l12(gd: Path) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["synchronous_transmission_sequence"] = [
        "1. ECU powers the two-wire current loop; the sensor(s) draw "
        "quiescent supply current.",
        "2. ECU emits a sync pulse (voltage pulse on the supply).",
        "3. The sync pulse triggers the sensor(s); each waits for its "
        "assigned time slot.",
        "4. In its time slot, a sensor current-modulates its Manchester-coded "
        "telegram (+-26 mA pulses) onto the loop.",
        "5. The ECU senses the loop current and Manchester-decodes the "
        "telegram.",
        "6. The ECU verifies the telegram CRC/parity and accepts or discards "
        "it.",
        "7. Remaining sensors transmit in their own time slots (time-division "
        "multiplexing) before the next sync pulse.",
    ]
    d["asynchronous_transmission_sequence"] = [
        "1. ECU powers the two-wire current loop.",
        "2. The sensor transmits telegrams autonomously on its own internal "
        "timing, without a sync pulse.",
        "3. The ECU senses the loop current, Manchester-decodes each telegram, "
        "and checks CRC/parity.",
    ]
    d["telegram_sequence"] = [
        "1. Drive the start condition (start bits).",
        "2. Send the Manchester-coded data bits (and optional region/status "
        "bits).",
        "3. Send the error-check field (2-bit/3-bit CRC or parity).",
        "4. End the telegram.",
    ]
    d["error_sequence"] = [
        "1. ECU computes the telegram CRC/parity.",
        "2. On mismatch the telegram is discarded.",
        "3. Persistent errors / missing telegrams / lost sync pulse are "
        "flagged as loop or sensor faults.",
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
        {"name": "Modulation current amplitude", "purpose": "Verify the "
         "sensor's current-modulation pulses are at the nominal +-26 mA on "
         "the loop."},
        {"name": "Manchester bit timing", "purpose": "Confirm the "
         "Manchester-coded bit period matches the configured 125/189 kbps and "
         "that mid-bit transitions are clean."},
        {"name": "Sync-pulse / time-slot timing", "purpose": "Validate the "
         "ECU sync pulse and the sensors' time-slot offsets (synchronous "
         "mode)."},
        {"name": "Telegram CRC / parity", "purpose": "Inject errors and "
         "confirm the 2-bit/3-bit CRC or parity detects them."},
        {"name": "Loop current / power budget", "purpose": "Confirm the "
         "sensor is correctly loop-powered and the quiescent + modulation "
         "current is within range."},
    ]
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
    f["spec_version"] = (
        "PSI5 Technical Specification (Peripheral Sensor Interface 5)")
    f["previous_versions"] = [
        "PSI5 evolved from earlier peripheral sensor interface generations; "
        "PSI5 is the two-wire current-loop sensor<->ECU interface with "
        "current modulation, Manchester coding, synchronous/asynchronous "
        "modes, and parallel-bus time slots.",
    ]
    f["key_changes"] = [
        {"version": "PSI5", "summary": "Two-wire current-loop automotive "
         "sensor interface: loop-powered sensor, current-modulation "
         "transmission of Manchester-coded telegrams, synchronous (sync-pulse "
         "time slots) and asynchronous modes, point-to-point / parallel-bus / "
         "daisy-chain (universal timing) topologies, telegram with 2-bit/3-bit "
         "CRC or parity, 125/189 kbps, and the PSI5-P point-to-point "
         "variant."},
    ]
    f["backward_compat_traps"] = [
        {"trap_name": "Current_loop_not_single_wire_voltage",
         "rule": "PSI5 carries data as current modulation on a two-wire "
                 "current loop, NOT as a voltage on a dedicated single signal "
                 "wire.",
         "trap": "Treating PSI5 like a voltage single-wire interface (e.g. "
                 "SENT's single signal wire) is wrong — PSI5 modulates the "
                 "supply current on the shared two-wire loop."},
        {"trap_name": "Manchester_not_pulse_width_nibble",
         "rule": "PSI5 data is Manchester-coded (embedded bit clock), not "
                 "pulse-width nibble timing.",
         "trap": "Assuming SENT-style (12 + value ticks) nibble pulse-width "
                 "timing is wrong for PSI5."},
        {"trap_name": "Sync_pulse_for_time_slots",
         "rule": "In synchronous mode the ECU sync pulse triggers time-slot "
                 "transmission; in asynchronous mode there is no sync pulse.",
         "trap": "Expecting a sync pulse in asynchronous mode, or expecting "
                 "autonomous transmission in synchronous mode, breaks "
                 "timing."},
        {"trap_name": "CRC_or_parity_depends_on_word_length",
         "rule": "The telegram error check is a 2-bit CRC, a 3-bit CRC, or a "
                 "parity bit depending on the data word length.",
         "trap": "Hard-coding a single error-check width fails for telegram "
                 "formats that use a different CRC/parity option."},
    ]
    f["version_naming_history_note"] = (
        "PSI5 (Peripheral Sensor Interface 5) is an automotive sensor "
        "interface specification. Facts here are grounded in the PSI5 "
        "Technical Specification: a two-wire current loop (power + data on the "
        "same wires), current-modulation transmission of Manchester-coded "
        "telegrams, synchronous (sync-pulse-triggered time slots) and "
        "asynchronous modes, point-to-point / parallel-bus / daisy-chain "
        "(universal timing) topologies, a telegram with start condition + data "
        "bits + optional region/status + 2-bit/3-bit CRC or parity, bit rates "
        "of 125 and 189 kbps, and the PSI5-P point-to-point variant.")
    _write(p, d)


# ----------------------------------------------------------------------
# L15 — encoding tables.
# ----------------------------------------------------------------------
def _l15(gd: Path) -> None:
    p = gd / "L15_ENCODING_TABLES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["bit_rate_table"] = {
        "header_columns": ["Bit rate (kbps)", "Coding", "Physical layer"],
        "rows": [
            ["125", "Manchester", "two-wire current loop"],
            ["189", "Manchester", "two-wire current loop"],
        ],
    }
    f["telegram_format_table"] = {
        "header_columns": ["Field", "Description"],
        "rows": [
            ["Start condition", "Start bits marking the telegram start"],
            ["Data bits", "Manchester-coded measurement word (configurable "
             "length)"],
            ["Region / status bits", "Optional region/range or status"],
            ["Error check", "2-bit CRC, 3-bit CRC, or parity bit"],
        ],
    }
    f["error_check_table"] = {
        "header_columns": ["Option", "When used"],
        "rows": [
            ["Parity bit", "Short data words"],
            ["2-bit CRC", "Short data words"],
            ["3-bit CRC", "Longer data words"],
        ],
    }
    f["mode_table"] = {
        "header_columns": ["Mode", "Trigger", "Use"],
        "rows": [
            ["Synchronous", "ECU sync pulse", "Time-slot (time-division) "
             "transmission on a parallel bus"],
            ["Asynchronous", "Sensor internal timer", "Autonomous "
             "point-to-point transmission"],
        ],
    }
    f["encoding_note"] = (
        "PSI5 data is Manchester-coded onto current pulses (nominal +-26 mA) "
        "on a two-wire current loop. There is no separate clock wire — the "
        "Manchester mid-bit transitions embed the bit clock. The telegram is "
        "protected by a 2-bit/3-bit CRC or parity. Bit rates are 125 and "
        "189 kbps.")
    f["tables"] = [
        "Bit-rate table (125 / 189 kbps)",
        "Telegram-format table (start / data / region-status / CRC-parity)",
        "Error-check table (parity / 2-bit / 3-bit CRC)",
        "Mode table (synchronous / asynchronous)",
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
        "Two-wire current loop: the same two wires power the sensor and carry "
        "the data.",
        "Loop-powered sensor (the ECU powers the loop).",
        "Current-modulation transmission (nominal +-26 mA current pulses).",
        "Manchester coding of the data bits (embedded bit clock).",
        "Synchronous mode with an ECU sync pulse triggering time-slot "
        "transmission.",
        "Asynchronous mode (autonomous sensor transmission).",
        "Time-division multiplexing of multiple sensors on a parallel bus.",
        "Telegram framing: start condition + Manchester data bits + optional "
        "region/status + 2-bit/3-bit CRC or parity.",
        "Bit rates 125 kbps and 189 kbps.",
        "Point-to-point, parallel-bus, and daisy-chain (universal timing) "
        "topologies.",
    ]
    f["must_not_have_properties"] = [
        "A dedicated single voltage signal wire carrying pulse-width nibbles "
        "(that is SENT, SAE J2716 — not PSI5).",
        "A separate clock wire (PSI5 is self-clocked via Manchester).",
        "UART-style break/sync/PID framing (that is LIN — not PSI5).",
        "A voltage-mode lighting bus (that is DALI — not PSI5).",
    ]
    f["compliance_failure_modes"] = [
        {"mode": "Telegram CRC/parity error", "trigger": "Bit error in the "
         "Manchester-coded telegram; the ECU discards it."},
        {"mode": "Missing time-slot telegram", "trigger": "A sensor does not "
         "transmit in its assigned slot (synchronous mode)."},
        {"mode": "Lost sync pulse", "trigger": "The ECU sync pulse is absent; "
         "synchronous transmission cannot be triggered."},
        {"mode": "Loop current out of range", "trigger": "Supply / sensor "
         "fault detected by the ECU."},
    ]
    f["psi5_distinguishers"] = (
        "PSI5 is identified by ALL of: a two-wire current loop where the same "
        "two wires power the sensor and carry the data; current-modulation "
        "transmission (nominal +-26 mA current pulses) of Manchester-coded "
        "telegrams; synchronous mode with an ECU sync pulse triggering "
        "time-slot (time-division) transmission plus an asynchronous mode; "
        "point-to-point / parallel-bus / daisy-chain (universal timing) "
        "topologies; a telegram with start condition + data + optional "
        "region/status + 2-bit/3-bit CRC or parity; and 125/189 kbps bit "
        "rates. This is distinct from SENT (single voltage signal wire, "
        "pulse-width nibble/tick, SAE J2716 — no current loop), LIN (UART "
        "break/sync/PID), and DALI (Manchester lighting bus, not a two-wire "
        "current-loop sensor link).")
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
        {"name": "Two-wire current loop (line A / line B)",
         "direction": "ECU -> sensor power; sensor -> ECU data",
         "purpose": "Supply power to the sensor AND carry the sensor data by "
                    "current modulation on the same two wires.",
         "active_levels": "Manchester-coded current pulses, nominal +-26 mA "
                          "on the supply current",
         "idle_level": "quiescent supply current (no data modulation)"},
        {"name": "Sync pulse (on the supply)",
         "direction": "ECU -> sensor",
         "purpose": "Trigger sensor transmission in time slots (synchronous "
                    "mode).",
         "active_levels": "voltage pulse on the two-wire supply",
         "idle_level": "nominal supply voltage"},
    ]
    f["logical_signaling_levels"] = [
        {"name": "Data pulse", "meaning": "Sensor draws a +-26 mA modulated "
         "current pulse (Manchester-coded bit) on the loop."},
        {"name": "Idle", "meaning": "Sensor draws only its quiescent supply "
         "current; no data on the loop."},
        {"name": "Sync pulse", "meaning": "ECU voltage pulse on the supply "
         "triggering time-slot transmission."},
    ]
    cc = _ensure_dict(f, "channel_counts")
    cc.update({
        "wires": 2,
        "current_loop": 1,
        "separate_clock_wires": 0,
        "separate_data_wires": 0,
        "bit_rates_kbps": list(_BIT_RATES_KBPS),
    })
    f["global_signals"] = [
        {"name": "Two-wire current loop", "purpose": "Shared power + data "
         "medium for the whole link."},
        {"name": "Sync pulse", "purpose": "ECU-driven time-slot trigger "
         "(synchronous mode)."},
    ]
    f["dependency_graph"] = {
        "common_rule": "Power and data share the two-wire current loop. The "
        "sensor is powered by the loop and transmits by current modulation; "
        "the ECU senses the loop current. In synchronous mode transmission "
        "depends on the ECU sync pulse and the sensor's time slot.",
        "data_dependency": "A telegram requires: (1) the sensor is "
        "loop-powered, (2) in synchronous mode, the sync pulse + the sensor's "
        "time slot, (3) a valid CRC/parity for the ECU to accept it.",
    }
    f["handshake_pairs"] = [
        {"name": "Sync-trigger", "from": "ECU", "to": "sensor",
         "rule": "The ECU sync pulse triggers the sensor(s) to transmit in "
                 "their time slots (synchronous mode)."},
        {"name": "Telegram-CRC", "from": "sensor", "to": "ECU",
         "rule": "The sensor appends a 2-bit/3-bit CRC or parity; the ECU "
                 "verifies it and discards corrupted telegrams."},
    ]
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
        "Two-wire current loop between an ECU and one or more sensors. "
        "Point-to-point (one sensor; PSI5-P variant), parallel bus (several "
        "sensors sharing the loop, each in its own time slot in synchronous "
        "mode), and daisy-chain (universal timing) topologies.")
    f["supported_topologies"] = [
        {"name": "Point-to-point", "description": "One sensor on a dedicated "
         "two-wire current loop (PSI5-P variant)."},
        {"name": "Parallel bus", "description": "Several sensors share one "
         "two-wire current loop; in synchronous mode each transmits in its "
         "own time slot (time-division multiplexing)."},
        {"name": "Daisy-chain (universal timing)", "description": "Sensors "
         "connected in a daisy chain with the PSI5 universal timing model."},
    ]
    f["master_slave_role_summary"] = [
        {"role": "ECU", "description": "Powers the two-wire current loop, "
         "emits the sync pulse (synchronous mode), and senses/decodes the "
         "loop current."},
        {"role": "Sensor", "description": "Loop-powered transmitter; "
         "current-modulates its Manchester-coded telegram onto the loop in "
         "its time slot (synchronous) or autonomously (asynchronous)."},
    ]
    f["interconnect_role"] = (
        "PSI5 is a sensor<->ECU link, not a routed bus. Multiple sensors on a "
        "parallel bus are separated by time slots (time-division), not by "
        "addresses; the ECU is the loop master that powers the loop and "
        "(synchronously) triggers transmission.")
    f["memory_vs_peripheral_regions"] = (
        "PSI5 has no address space; on a parallel bus, sensors are "
        "distinguished by their time slot relative to the ECU sync pulse.")
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
        "physical_layer": "two-wire current loop (power + data shared)",
        "signaling": "current modulation",
        "nominal_modulation_current_mA": _NOMINAL_MOD_CURRENT_MA,
        "line_coding": "Manchester",
        "bit_rates_kbps": list(_BIT_RATES_KBPS),
        "loop_powered": True,
        "operating_modes": ["synchronous", "asynchronous"],
        "topologies": list(_TOPOLOGIES),
        "error_check": list(_CRC_PARITY_OPTIONS),
    }
    f["notes"] = (
        "PSI5 fixes the electrical channel model (two-wire current loop, "
        "current modulation at nominal +-26 mA, Manchester coding, 125/189 "
        "kbps) and the telegram/error-check format. Sensor power budget, loop "
        "supply voltage, and current-sense implementation are "
        "system-integrator concerns.")
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
        {"name": "Loop current sensing", "purpose": "The ECU observes the "
         "modulated loop current; out-of-range current flags faults."},
        {"name": "Telegram CRC / parity", "purpose": "Per-telegram error "
         "check provides run-time observability of link integrity."},
        {"name": "Time-slot occupancy", "purpose": "The ECU detects missing "
         "telegrams per time slot (synchronous mode)."},
    ]
    f["internal_diagnostics_observability"] = [
        "Loop current status / out-of-range.",
        "Per-slot telegram-received and CRC-error counts.",
        "Sync-pulse presence (synchronous mode).",
    ]
    f["notes"] = (
        "PSI5's protocol-level test surface is the loop-current sensing, the "
        "telegram CRC/parity, and time-slot occupancy. Chip-level JTAG / scan "
        "/ BIST remain integrator concerns.")
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
    f["power_delivery_model"] = (
        "The sensor is loop-powered: the ECU supplies energy over the same "
        "two-wire current loop that carries the data. The sensor's quiescent "
        "supply current is the carrier for the +-26 mA data modulation.")
    f["power_rails"] = [
        {"rail": "Loop supply (two-wire)", "purpose": "ECU-supplied power to "
         "the sensor over the current loop; also the data medium."},
    ]
    f["psi5_power_considerations"] = (
        "Because power and data share the two-wire current loop, the sensor "
        "must operate within the loop's current/power budget while leaving "
        "headroom for the +-26 mA data modulation. The ECU supplies and "
        "senses the loop.")
    f["notes"] = (
        "PSI5's power model is loop-powered: there is no separate power bus. "
        "The ECU powers the two-wire loop; the sensor draws its operating "
        "current from it and modulates that current to send data.")
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
        "Two-wire current loop — loop-powered sensor; power + data on the same "
        "wires.",
        "Current modulation — +-26 mA current pulses; ECU current sensing.",
        "Manchester coding — embedded bit clock; ECU timing recovery.",
        "Synchronous mode — sync pulse triggers time-slot transmission.",
        "Time-division — multiple sensors in distinct time slots on a "
        "parallel bus.",
        "Asynchronous mode — autonomous sensor transmission.",
        "Telegram framing — start condition + data + optional region/status + "
        "CRC/parity.",
        "Error check — 2-bit/3-bit CRC or parity; corrupted telegrams "
        "discarded.",
        "Bit rates — 125 and 189 kbps.",
        "Topologies — point-to-point, parallel bus, daisy-chain (universal "
        "timing).",
        "Fault handling — out-of-range current, missing telegram, lost sync "
        "pulse.",
    ]
    f["notes"] = (
        "PSI5 does not ship a formal testbench, but the specification implies "
        "a verification plan covering the current-loop physical layer, "
        "current modulation, Manchester coding, synchronous/asynchronous "
        "modes, telegram framing + CRC/parity, the topologies, and the bit "
        "rates.")
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
        "Per-telegram 2-bit/3-bit CRC or parity detects bit errors; corrupted "
        "telegrams are discarded by the ECU.",
        "Out-of-range loop-current detection flags supply/sensor faults.",
        "Missing-telegram / lost-sync-pulse detection (synchronous mode).",
    ]
    f["anti_tampering_features"] = []
    f["confidentiality_features"] = []
    f["authentication_features"] = []
    f["notes"] = (
        "PSI5 is a two-wire current-loop sensor transport; its built-in "
        "protections are anti-corruption only (telegram CRC/parity, "
        "loop-current monitoring). It does not define cryptographic "
        "confidentiality, integrity, or authentication; those would be "
        "added at the system level if required. The in-vehicle, "
        "point-to-point/short-bus nature of the loop limits the physical "
        "attack surface.")
    _write(p, d)
