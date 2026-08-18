"""Single Edge Nibble Transmission (SENT) protocol synth helper.

ic_class-gated overlay for the SENT structural signature: a unidirectional,
point-to-point, single-signal-wire (three-wire: signal + supply + ground)
automotive sensor interface standardized as SAE J2716. SENT conveys data on a
single wire by the TIME between successive falling edges, measured in unit time
intervals called ticks (nominal 3 us, range 3-90 us). Each nibble (4 bits) is a
pulse of (12 + value) ticks, value 0-15. A message frame is a
synchronization/calibration pulse (56 ticks) -> status & serial-communication
nibble -> 1-6 data nibbles (typically two 12-bit sensor channels) -> a 4-bit
CRC (CRC-4) nibble -> an optional pause pulse. A slow serial communication
channel (Short Serial Message / Enhanced Serial Message) is carried in bit 2/3
of the status nibble across many frames. The synchronous SENT-SPC (Short PWM
Code) variant adds an ECU master trigger pulse, making the link
request/response and addressable. Applies the SAE J2716 spec-canonical content
to L1-L23.

Doctrine — GENERAL not keyword: detection uses canonical STRUCTURAL signatures
(single-wire nibble pulses + tick unit time + 56-tick synchronization/
calibration pulse + 4-bit CRC nibble + SAE J2716, OR the falling-edge-to-
falling-edge nibble-timing rule "12 + value ticks") read from the L-doc /
input_doc CONTENT blob only. It NEVER reads the input-document filename or the
benchmark folder name, and — critically — it NEVER keys on the bare English
word "sent" (e.g. "the data was sent to the host"); it keys on SENT-structural
tokens (SAE J2716 / single edge nibble transmission + nibble + tick + 56-tick
calibration pulse + falling-edge nibble timing).

Sibling disambiguation — SENT vs LIN, DALI, UART, and generic PWM (the
single-wire automotive family). SENT, LIN, DALI all use few wires, but only
SENT carries data as pulse-width nibble timing (12 + value ticks), framed by a
56-tick synchronization/calibration pulse and a 4-bit CRC nibble, on a
unidirectional single signal wire. LIN is a UART-based bidirectional bus with a
break field, sync field, protected identifier (PID), and a master schedule;
DALI is a Manchester-coded bidirectional lighting bus; UART is start/stop bit
framing; a generic PWM sensor encodes a value as a duty cycle of a fixed-period
square wave (no nibbles, no tick count, no calibration pulse, no CRC nibble).
The detector REQUIRES the SENT-only structural vocabulary and DEFERS when the
doc is LIN-primary (UART framing + break/sync/PID + master schedule), DALI-
primary (Manchester + lighting, no nibble/tick/SAE-J2716), or generic-PWM-only,
so it cannot false-fire on a LIN, DALI, UART, or PWM spec.

Public entry: ``apply_sent_synth(generated_docs_dir, is_sent, sent_ic_name)``.
Module-level ``is_sent(blob)`` is the content-only detector.
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

# Canonical SENT facts (SAE J2716 — Single Edge Nibble Transmission).
_TICK_NOMINAL_US = 3
_TICK_MIN_US = 3
_TICK_MAX_US = 90
_SYNC_CAL_TICKS = 56
_NIBBLE_BITS = 4
_NIBBLE_OFFSET_TICKS = 12          # nibble pulse period = 12 + value ticks
_NIBBLE_VALUE_MAX = 15
_NIBBLE_PERIOD_MIN_TICKS = 12      # value 0
_NIBBLE_PERIOD_MAX_TICKS = 27      # value 15
_MIN_NIBBLE_LOW_TICKS = 5
_CRC_BITS = 4                      # CRC-4 nibble
_DATA_NIBBLE_MIN = 1
_DATA_NIBBLE_MAX = 6
_FRAME_NIBBLE_ORDER = [
    "Synchronization/Calibration pulse (56 ticks)",
    "Status & Serial Communication nibble",
    "Data nibbles (1-6, typically two 12-bit channels)",
    "CRC nibble (4-bit, CRC-4)",
    "Optional pause pulse",
]


def is_sent(blob: str) -> bool:
    """Content-only SENT (SAE J2716) detector with a LIN/DALI/UART/PWM MUTEX.

    Fire on the SENT structural signature: a single-signal-wire, falling-edge-
    to-falling-edge, nibble pulse-width interface where each nibble = 12 + value
    ticks, framed by a 56-tick synchronization/calibration pulse and a 4-bit CRC
    nibble (SAE J2716). Defer if the doc is LIN-primary (UART framing + break/
    sync/PID + master schedule), DALI-primary (Manchester lighting), or generic-
    PWM-only, so a LIN / DALI / UART / PWM spec cannot false-fire. Reads ONLY the
    spec text `blob` — never a filename or benchmark name — and NEVER keys on the
    bare English word "sent".
    """
    if not blob:
        return False
    low = blob.lower()

    # --- SENT-only NAME tokens (structural, NOT the bare word "sent"). ---
    # word-boundary structural spec identifiers, absent from LIN/DALI/UART/PWM.
    name_token = (
        "sae j2716" in low
        or "single edge nibble transmission" in low
        or "single-edge nibble transmission" in low
        or "single edge nibble" in low
    )

    # --- SENT-only STRUCTURAL tokens. ---
    nibble = "nibble" in low
    tick = (
        "tick" in low
        and ("unit time" in low or "3 us" in low or "3 microsecond" in low
              or "3 µs" in low or "tick time" in low or "ticks" in low)
    )
    # The defining nibble-timing rule: pulse period = 12 + value ticks.
    nibble_timing_rule = (
        "12 + value" in low
        or "12 + nibble" in low
        or "12+value" in low
        or ("12 + " in low and "ticks" in low and nibble)
        or ("falling edge to falling edge" in low and nibble)
        or ("falling-edge-to-falling-edge" in low and nibble)
        or ("falling edge" in low and nibble and tick)
    )
    # 56-tick synchronization / calibration pulse.
    sync_cal_pulse = (
        ("56 tick" in low or "56-tick" in low)
        and ("calibration" in low or "synchronization" in low or "sync" in low)
    ) or ("calibration pulse" in low and "56" in low)
    # 4-bit CRC nibble.
    crc_nibble = (
        ("crc nibble" in low)
        or ("crc-4" in low)
        or ("crc" in low and nibble and ("4-bit" in low or "4 bit" in low))
    )
    # Single signal wire / three-wire sensor interface.
    single_wire = (
        "single signal wire" in low or "single signal line" in low
        or "single-signal-wire" in low or "single wire" in low
        or ("three-wire" in low or "three wire" in low or "3-wire" in low)
    )

    # Structural core: a nibble + tick interface with the SENT nibble-timing
    # rule AND at least one of {56-tick sync/cal pulse, CRC nibble}. This is the
    # canonical SENT wire-level signature; PWM/UART/DALI/LIN do not have it.
    sent_structure = (
        nibble and tick and nibble_timing_rule
        and (sync_cal_pulse or crc_nibble)
    )

    # --- Sibling MUTEX (defer paths). ---
    # LIN-primary: UART-based bus with break/sync/PID + master schedule and NO
    # SENT nibble/tick/SAE-J2716 structure.
    lin_primary = (
        ("lin" in low and "protected identifier" in low)
        or ("break field" in low and "sync field" in low
            and ("pid" in low or "protected identifier" in low))
    ) and not (name_token or (nibble and tick and nibble_timing_rule))
    if lin_primary:
        return False

    # DALI-primary: Manchester-coded lighting bus with NO SENT structure.
    dali_primary = (
        "manchester" in low
        and ("lighting" in low or "dali" in low
             or "digital addressable" in low)
        and not (name_token or sent_structure)
    )
    if dali_primary:
        return False

    # Generic-PWM-only: duty-cycle of a fixed-period square wave, NO nibbles /
    # tick count / SAE-J2716 / calibration pulse.
    pwm_only = (
        ("duty cycle" in low or "duty-cycle" in low)
        and "pwm" in low
        and not (name_token or nibble or sync_cal_pulse or crc_nibble
                 or nibble_timing_rule)
    )
    if pwm_only:
        return False

    # IO-Link-primary: an IO-Link (SDCI) spec describes SENT verbatim in its
    # comparison section (full nibble/tick/56-tick/CRC-4 structure), so the SENT
    # structure alone is present. The doc is anchored by IO-Link-EXCLUSIVE tokens
    # (SDCI + IODD + ISDU/M-sequence/C-Q) that a real SENT spec never carries.
    io_link_primary = (
        ("sdci" in low or "io-link" in low or "io link" in low)
        and ("iodd" in low or "isdu" in low)
        and ("m-sequence" in low or "m sequence" in low or "c/q" in low)
    )
    if io_link_primary:
        return False

    # PSI5-primary: a PSI5 (2-wire current-loop automotive sensor) spec describes
    # SENT in its comparison section (sae j2716 / nibble / tick), so SENT tokens
    # appear. PSI5-EXCLUSIVE tokens (current loop + Manchester current modulation +
    # PSI5 name) are absent from a real SENT (single-wire voltage pulse-width) doc.
    psi5_primary = (
        ("psi5" in low or "peripheral sensor interface 5" in low
         or "psi-5" in low)
        and "current loop" in low
        and "manchester" in low
    )
    if psi5_primary:
        return False

    # --- Fire decision. ---
    # Require BOTH a SENT name token AND the structural signature, OR a very
    # strong structure (name token may be implicit) anchored by the nibble-
    # timing rule + 56-tick calibration pulse + CRC nibble.
    return bool(
        (name_token and sent_structure)
        or (name_token and nibble and tick
            and (sync_cal_pulse or crc_nibble) and single_wire)
        or (sent_structure and sync_cal_pulse and crc_nibble
            and nibble_timing_rule)
    )


def apply_sent_synth(generated_docs_dir: Path, is_sent_flag: bool,
                     sent_ic_name: Optional[str]) -> None:
    """Apply SAE J2716 SENT synth when the SENT signature matched."""
    if not is_sent_flag:
        return
    gd = Path(generated_docs_dir)

    # --- Force ic_name across ALL 24 docs FIRST (main + fields docs). ---
    if sent_ic_name is not None:
        for n in _MAIN_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                d["ic_name"] = sent_ic_name
                _write(q, d)
        for n in _FIELDS_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                f = _ensure_dict(d, "fields")
                f["ic_name"] = sent_ic_name
                d["ic_name"] = sent_ic_name
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
# L1 — SENT datasheet header + headline facts.
# ----------------------------------------------------------------------
def _l1(gd: Path) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    d["document_title"] = "Single Edge Nibble Transmission (SENT) Interface"
    d["version"] = "SAE J2716 (SENT — Single Edge Nibble Transmission)"
    d["revised_date"] = "SAE J2716"
    d["manufacturer"] = "SAE International"
    d["copyright"] = "© SAE International"
    d["abstract"] = (
        "Single Edge Nibble Transmission (SENT) is a unidirectional, "
        "point-to-point, single-signal-wire digital interface defined by SAE "
        "J2716 for transmitting high-resolution sensor data from a smart "
        "sensor to an electronic control unit (ECU). SENT is a three-wire "
        "interface: a single signal line, a supply voltage line, and a ground "
        "line. Data is conveyed on the single signal wire by the time between "
        "successive falling edges, measured in unit time intervals called "
        "ticks (nominal 3 us, range 3-90 us). Each nibble (four bits) is a "
        "pulse of (12 + value) ticks, value 0-15. A message frame consists of "
        "a synchronization/calibration pulse (56 ticks), a status & serial "
        "communication nibble, one to six data nibbles (typically two 12-bit "
        "sensor channels), a 4-bit CRC (CRC-4) nibble, and an optional pause "
        "pulse. A slow serial communication channel (Short Serial Message / "
        "Enhanced Serial Message) is carried in two bits of the status nibble "
        "across many frames. The synchronous SENT-SPC (Short PWM Code) variant "
        "adds an ECU master trigger pulse, making the link request/response "
        "and addressable.")
    d["keywords"] = [
        "SENT", "Single Edge Nibble Transmission", "SAE J2716", "nibble",
        "tick", "unit time", "falling edge", "synchronization pulse",
        "calibration pulse", "56 ticks", "status nibble", "data nibble",
        "CRC nibble", "CRC-4", "slow serial channel", "Short Serial Message",
        "Enhanced Serial Message", "SENT-SPC", "Short PWM Code",
        "master trigger pulse", "single signal wire", "three-wire",
        "automotive sensor", "ECU", "pulse width", "unidirectional",
        "point-to-point", "pause pulse",
    ]
    d["external_pins"] = [
        "SENT signal: single push-pull data wire (0 V / 5 V); carries nibble "
        "pulses (falling-edge to falling-edge timing in ticks)",
        "VCC / supply: 5 V supply to the sensor",
        "GND: common ground reference",
        "No separate clock wire — the receiver recovers the tick time from the "
        "56-tick synchronization/calibration pulse each frame",
    ]
    d["tick_nominal_us"] = _TICK_NOMINAL_US
    d["tick_range_us"] = [_TICK_MIN_US, _TICK_MAX_US]
    d["sync_calibration_ticks"] = _SYNC_CAL_TICKS
    d["nibble_bits"] = _NIBBLE_BITS
    d["nibble_pulse_period_ticks"] = "12 + value (12..27 ticks, value 0..15)"
    d["crc_bits"] = _CRC_BITS
    d["modes_of_operation"] = [
        {"name": "SENT (asynchronous)",
         "role": "free-running unidirectional sensor transmission",
         "note": "The sensor transmits message frames back-to-back over the "
                 "single signal wire; the ECU only receives. No request, no "
                 "addressing, no bus arbitration."},
        {"name": "SENT-SPC (Short PWM Code, synchronous)",
         "role": "ECU-triggered request/response",
         "note": "The ECU drives a master trigger pulse; the sensor responds "
                 "with a SENT frame. The trigger pulse width can select which "
                 "data channel is returned, making SPC addressable."},
        {"name": "Slow serial channel",
         "role": "low-rate serial messaging",
         "note": "Bit 2/3 of the status nibble accumulate a Short Serial "
                 "Message (16-bit) or Enhanced Serial Message across many "
                 "frames for IDs, configuration, and diagnostics."},
    ]
    d["key_features"] = [
        "Unidirectional, point-to-point, single-signal-wire automotive sensor "
        "interface (three-wire: signal + supply + ground); SAE J2716.",
        "Data encoded as the time between successive falling edges, measured "
        "in ticks (unit time, nominal 3 us, range 3-90 us).",
        "Each nibble (4 bits) is a pulse of (12 + value) ticks, value 0-15 "
        "(12..27 ticks); the fixed 12-tick offset sets a minimum pulse "
        "period.",
        "Message frame: synchronization/calibration pulse (56 ticks) -> status "
        "& serial communication nibble -> 1-6 data nibbles -> 4-bit CRC "
        "(CRC-4) nibble -> optional pause pulse.",
        "Receiver recovers the per-frame tick time from the 56-tick "
        "synchronization/calibration pulse, compensating for transmitter clock "
        "drift (up to +/- 20%).",
        "Typically two independent 12-bit sensor channels in six data nibbles.",
        "Slow serial communication channel (Short Serial Message 16-bit / "
        "Enhanced Serial Message) carried in bit 2/3 of the status nibble "
        "across many frames.",
        "4-bit CRC (CRC-4) nibble detects frame corruption; out-of-range "
        "nibble periods flag framing errors.",
        "Synchronous SENT-SPC (Short PWM Code) variant: ECU master trigger "
        "pulse makes the link request/response and addressable.",
        "No clock wire, no addressing, no bus arbitration in basic mode.",
    ]
    d["topology_summary"] = (
        "Point-to-point: one smart sensor (transmitter) drives one ECU "
        "(receiver) over a single signal wire. There is no bus and no "
        "multi-drop; each sensor has its own SENT wire to the ECU.")
    d["use_cases"] = [
        "Pressure sensors (manifold, fuel rail, brake)",
        "Position sensors (throttle, pedal, gear)",
        "Mass air flow and temperature sensors",
        "Torque and angle sensors",
        "Any smart automotive sensor reporting a high-resolution value to an "
        "ECU over a cheap single wire",
    ]
    d["revision_history"] = [
        {"version": "SAE J2716 (initial)", "date": "2007",
         "description": "First SENT standard: single-wire nibble pulse-width "
                        "sensor interface, tick/nibble encoding, "
                        "synchronization/calibration pulse, status + data "
                        "nibbles, CRC-4 nibble."},
        {"version": "SAE J2716 (revised)", "date": "2010+",
         "description": "Added/clarified the slow serial communication channel "
                        "(Short Serial Message / Enhanced Serial Message), "
                        "pause pulse, and the SENT-SPC (Short PWM Code) "
                        "synchronous variant; tightened CRC and timing "
                        "definitions."},
    ]
    d["overview"] = (
        "Single Edge Nibble Transmission (SENT, SAE J2716) sends high-"
        "resolution sensor data from a smart sensor to an ECU over a single "
        "signal wire. The interface is unidirectional and point-to-point. "
        "Information is carried by the time between successive falling edges, "
        "measured in unit time intervals called ticks (nominal 3 us, range "
        "3-90 us). A nibble (4 bits) is sent as one pulse whose falling-edge "
        "to falling-edge period equals 12 + value ticks (value 0-15, i.e. "
        "12..27 ticks). A message frame begins with a 56-tick synchronization/"
        "calibration pulse the receiver measures to recover the per-frame tick "
        "time; it is followed by a status & serial communication nibble, one "
        "to six data nibbles (typically two 12-bit channels), and a 4-bit CRC "
        "(CRC-4) nibble, with an optional pause pulse to fix the frame length. "
        "A slow serial channel carried in bit 2/3 of the status nibble "
        "assembles a Short Serial Message (16-bit) or Enhanced Serial Message "
        "over many frames. The synchronous SENT-SPC (Short PWM Code) variant "
        "adds an ECU master trigger pulse so the otherwise free-running stream "
        "becomes a request/response, addressable exchange while preserving the "
        "tick/nibble encoding and the message frame format.")
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
        "Unidirectional, point-to-point, single-signal-wire automotive sensor "
        "interface (three-wire: signal + supply + ground). Data is encoded as "
        "the falling-edge-to-falling-edge time of nibble pulses, measured in "
        "ticks (unit time). Standardized as SAE J2716 (SENT).")
    po["duplex"] = (
        "Half-duplex / unidirectional: the sensor transmits, the ECU receives. "
        "In the basic SENT mode there is no return path; the synchronous "
        "SENT-SPC variant adds an ECU master trigger pulse on the same wire.")
    po["synchronous_serial"] = False
    po["source_synchronous"] = False
    po["embedded_clock"] = True
    po["forwarded_clock"] = False
    po["encoding"] = (
        "Pulse-width nibble encoding: each nibble (4 bits) is a pulse of "
        "(12 + value) ticks (value 0-15), measured falling-edge to "
        "falling-edge. The receiver recovers the tick time from the 56-tick "
        "synchronization/calibration pulse at the start of each frame.")
    po["modulation"] = (
        "Push-pull single-wire pulse stream (0 V / 5 V); information in the "
        "falling-edge-to-falling-edge period, not in voltage level.")
    po["tick_nominal_us"] = _TICK_NOMINAL_US
    po["tick_range_us"] = [_TICK_MIN_US, _TICK_MAX_US]
    po["sync_calibration_ticks"] = _SYNC_CAL_TICKS
    po["nibble_bits"] = _NIBBLE_BITS
    po["nibble_offset_ticks"] = _NIBBLE_OFFSET_TICKS
    po["nibble_value_max"] = _NIBBLE_VALUE_MAX
    po["data_nibble_range"] = [_DATA_NIBBLE_MIN, _DATA_NIBBLE_MAX]
    po["crc_bits"] = _CRC_BITS
    po["frame_order"] = list(_FRAME_NIBBLE_ORDER)
    po["unidirectional"] = True
    po["point_to_point"] = True
    po["topology"] = (
        "smart sensor (transmitter) -> single signal wire -> ECU (receiver); "
        "one wire per sensor, no bus, no addressing in basic mode.")
    d["functional_requirements"] = [
        {"id": "FR-WIRE-01", "text": "SENT is a unidirectional point-to-point "
         "interface on a single signal wire (three-wire including supply and "
         "ground); the sensor transmits and the ECU receives."},
        {"id": "FR-TICK-02", "text": "The unit time is the tick, nominal 3 "
         "microseconds, permitted range 3 to 90 microseconds; all nibble "
         "pulse periods are an integer number of ticks."},
        {"id": "FR-NIB-03", "text": "A nibble is four bits, transmitted as one "
         "pulse whose falling-edge-to-falling-edge period equals 12 + value "
         "ticks (value 0-15, i.e. 12 to 27 ticks)."},
        {"id": "FR-SYNC-04", "text": "Every message frame begins with a "
         "synchronization/calibration pulse of nominal 56 ticks; the receiver "
         "measures it and divides by 56 to recover the per-frame tick time, "
         "compensating for transmitter clock drift."},
        {"id": "FR-STAT-05", "text": "The pulse after the calibration pulse is "
         "the status and serial communication nibble; two of its bits carry "
         "status and two bits (bit 2 and bit 3) carry the slow serial "
         "communication channel."},
        {"id": "FR-DATA-06", "text": "One to six data nibbles follow the "
         "status nibble; a typical SENT sensor sends two independent 12-bit "
         "data channels in six data nibbles."},
        {"id": "FR-CRC-07", "text": "The frame ends with a 4-bit CRC (CRC-4) "
         "nibble computed over the data nibbles (and optionally the status "
         "nibble); the receiver recomputes and compares it to detect frame "
         "corruption."},
        {"id": "FR-PAUSE-08", "text": "An optional pause pulse may follow a "
         "frame so the total frame length (including pause) is a constant "
         "number of ticks, giving a fixed frame period."},
        {"id": "FR-SLOW-09", "text": "The slow serial communication channel "
         "assembles a Short Serial Message (16-bit: 4-bit ID + 8-bit data + "
         "4-bit CRC over 16 frames) or an Enhanced Serial Message "
         "(configuration/identification over ~18 frames) from bit 2/3 of the "
         "status nibble."},
        {"id": "FR-SPC-10", "text": "The synchronous SENT-SPC (Short PWM Code) "
         "variant adds an ECU master trigger pulse; the sensor responds with a "
         "SENT frame, and the trigger pulse width can select a data channel "
         "(addressable)."},
        {"id": "FR-ERR-11", "text": "Errors are detected by the CRC-4 nibble, "
         "by out-of-range nibble periods (outside 12 to 27 ticks) or a "
         "calibration pulse not near 56 ticks, and by ECU plausibility "
         "checks; loss of the calibration pulse causes resynchronization."},
    ]
    d["error_response_conditions"] = [
        "CRC-4 nibble mismatch — the frame is flagged as corrupted and "
        "discarded by the ECU.",
        "Out-of-range nibble period — a measured falling-edge-to-falling-edge "
        "period outside 12 to 27 ticks indicates a framing error.",
        "Calibration-pulse error — a synchronization/calibration pulse not "
        "near 56 ticks indicates loss of frame sync; the receiver "
        "resynchronizes at the next calibration pulse.",
        "Implausible value change between successive frames — the ECU may "
        "reject the value.",
    ]
    d["compliance_requirements"] = [
        "Single-signal-wire unidirectional point-to-point interface "
        "(three-wire) per SAE J2716.",
        "Tick unit time (nominal 3 us, range 3-90 us); nibble pulse period = "
        "12 + value ticks (value 0-15).",
        "56-tick synchronization/calibration pulse at the start of each frame; "
        "receiver recalibration per frame.",
        "Frame order: calibration pulse -> status nibble -> 1-6 data nibbles "
        "-> 4-bit CRC nibble -> optional pause pulse.",
        "4-bit CRC (CRC-4) nibble over the data nibbles.",
        "Slow serial channel (Short Serial Message / Enhanced Serial Message) "
        "in bit 2/3 of the status nibble.",
        "Optional synchronous SENT-SPC (Short PWM Code) master-trigger "
        "variant.",
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
        "Frame-based, pulse-width nibble protocol on a single wire. The sensor "
        "transmits message frames (synchronization/calibration pulse -> status "
        "nibble -> 1-6 data nibbles -> 4-bit CRC nibble -> optional pause "
        "pulse); each nibble is a pulse of (12 + value) ticks measured "
        "falling-edge to falling-edge. There are no addressed commands in "
        "basic SENT; the synchronous SENT-SPC variant uses an ECU master "
        "trigger pulse whose width selects a data channel.")
    d["frame_structure"] = [
        {"element": "Synchronization/Calibration pulse",
         "ticks": _SYNC_CAL_TICKS,
         "purpose": "Receiver measures it to recover the per-frame tick time "
                    "(divide by 56)."},
        {"element": "Status & Serial Communication nibble",
         "ticks": "12 + value",
         "purpose": "2 status bits + 2 slow-serial-channel bits (bit 2/3)."},
        {"element": "Data nibbles (1-6)",
         "ticks": "12 + value each",
         "purpose": "Sensor data; typically two 12-bit channels (6 nibbles)."},
        {"element": "CRC nibble",
         "ticks": "12 + value",
         "purpose": "4-bit CRC-4 over the data nibbles."},
        {"element": "Pause pulse (optional)",
         "ticks": "variable",
         "purpose": "Pads the frame to a constant total length."},
    ]
    d["nibble_encoding"] = {
        "bits_per_nibble": _NIBBLE_BITS,
        "pulse_period_ticks": "12 + value",
        "value_range": [0, _NIBBLE_VALUE_MAX],
        "period_range_ticks": [_NIBBLE_PERIOD_MIN_TICKS,
                               _NIBBLE_PERIOD_MAX_TICKS],
        "min_low_ticks": _MIN_NIBBLE_LOW_TICKS,
        "note": "Each nibble pulse is measured falling-edge to falling-edge; "
                "value = (period_ticks - 12).",
    }
    d["slow_serial_channel"] = [
        {"name": "Short Serial Message",
         "frames": 16,
         "payload": "4-bit message ID + 8-bit data + 4-bit CRC (16-bit total)",
         "carrier": "bit 2 (serial data) and bit 3 (start) of the status "
                    "nibble."},
        {"name": "Enhanced Serial Message",
         "frames": "~18",
         "payload": "configuration / identification (extended ID + 12/16-bit "
                    "data + CRC)",
         "carrier": "bit 2/3 of the status nibble across many frames."},
    ]
    d["spc_variant"] = {
        "name": "SENT-SPC (Short PWM Code)",
        "trigger": "ECU drives a master trigger pulse on the signal line.",
        "response": "Sensor returns a standard SENT frame.",
        "addressing": "The master trigger pulse width can select which data "
                      "channel the sensor returns (addressable).",
        "synchronous": True,
    }
    d["crc"] = {
        "crc_bits": _CRC_BITS,
        "name": "CRC-4",
        "coverage": "data nibbles (and optionally the status nibble)",
        "method": "4-bit polynomial with a defined seed; lookup-table-based "
                  "calculation.",
    }
    d["addressing"] = {
        "basic_sent": "None — unidirectional point-to-point, one sensor per "
                      "wire.",
        "spc": "Channel selection by master-trigger-pulse width.",
    }
    d["byte_oriented"] = False
    d["nibble_oriented"] = True
    d["frame_oriented"] = True
    d["unidirectional"] = True
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
        "SENT (SAE J2716) is a sensor transmission interface rather than a "
        "memory-mapped register IC. A SENT sensor has configuration "
        "parameters (tick time, number of data nibbles, channel format, "
        "pause-pulse enable, CRC variant, slow-channel content) that are "
        "fixed for a given sensor or programmed at manufacture; the ECU side "
        "exposes decoded values and status. The groups below are the "
        "canonical SENT configuration/status surfaces.")
    d["register_access"] = {
        "transport": "Sensor configuration (often factory-programmed) + ECU "
                     "decoded-value/status registers",
        "purpose": "Configure the frame format and decode the nibble stream.",
    }
    d["register_groups"] = [
        {"group": "Sensor timing configuration", "fields": [
            "Tick time (nominal 3 us; 3-90 us)",
            "Synchronization/calibration pulse length (56 ticks)",
            "Pause-pulse enable and target frame length"]},
        {"group": "Frame format configuration", "fields": [
            "Number of data nibbles (1-6)",
            "Channel format (e.g. two 12-bit channels)",
            "Status-nibble slow-channel content (Short / Enhanced)",
            "CRC variant (data-only vs status+data)"]},
        {"group": "ECU decode / status", "fields": [
            "Decoded data channel 1 / channel 2 values",
            "Status nibble bits",
            "CRC-pass / frame-error flags",
            "Slow serial message buffer (ID / data / CRC)"]},
    ]
    d["protocol_fields"] = {
        "tick_nominal_us": _TICK_NOMINAL_US,
        "sync_calibration_ticks": _SYNC_CAL_TICKS,
        "nibble_bits": _NIBBLE_BITS,
        "crc_bits": _CRC_BITS,
        "data_nibble_range": [_DATA_NIBBLE_MIN, _DATA_NIBBLE_MAX],
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
        "The SENT signal is a single push-pull wire driven between 0 V (low) "
        "and 5 V (high). Each pulse starts with a falling edge, holds a "
        "minimum low time (nominal 5 ticks), then returns high; the "
        "falling-edge-to-falling-edge period (in ticks) carries the nibble "
        "value. There is no separate clock wire — the receiver recovers the "
        "tick time from the 56-tick synchronization/calibration pulse each "
        "frame.")
    d["modulation"] = (
        "Single-wire push-pull pulse stream (0 V / 5 V); pulse-width "
        "(falling-edge-to-falling-edge tick count) encoding.")
    d["clocking"] = (
        "Embedded / self-clocked: the receiver derives the per-frame tick time "
        "from the 56-tick synchronization/calibration pulse, compensating for "
        "transmitter clock drift (up to +/- 20%).")
    d["transmitter_specs_canonical"] = {
        "levels": "0 V (low) / 5 V (high), push-pull",
        "tick_nominal_us": _TICK_NOMINAL_US,
        "tick_range_us": [_TICK_MIN_US, _TICK_MAX_US],
        "tick_tolerance": "+/- 20% (basic); receiver recalibrates per frame",
        "min_nibble_low_ticks": _MIN_NIBBLE_LOW_TICKS,
        "nibble_pulse_period_ticks": "12 + value (12..27)",
        "sync_calibration_ticks": _SYNC_CAL_TICKS,
    }
    d["receiver_specs_canonical"] = {
        "edge_of_interest": "falling edge (single edge nibble transmission)",
        "calibration": "Measure the 56-tick synchronization/calibration pulse "
                       "and divide by 56 to obtain the per-frame tick time.",
        "decode": "For each pulse, measure falling-edge-to-falling-edge "
                  "period, divide by tick time, round, subtract 12 -> nibble "
                  "value (0-15).",
    }
    d["edge_encoding"] = {
        "name": "single edge nibble transmission",
        "edge": "falling edge",
        "rule": "data conveyed by the time between successive falling edges, "
                "in ticks.",
    }
    d["tick_nominal_us"] = _TICK_NOMINAL_US
    d["sync_calibration_ticks"] = _SYNC_CAL_TICKS
    d["encoding_role_in_analog"] = (
        "SENT carries digital nibble values purely in the timing of falling "
        "edges on a single push-pull wire; the analog/physical concern is the "
        "edge timing accuracy and the tick-time recovery from the 56-tick "
        "calibration pulse, not voltage-level discrimination. Frame integrity "
        "comes from the 4-bit CRC nibble and out-of-range period checks.")
    _write(p, d)


# ----------------------------------------------------------------------
# L6 — control logic / receiver + transmitter FSMs.
# ----------------------------------------------------------------------
def _l6(gd: Path) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["fsm_states_receiver"] = [
        {"name": "WAIT_CALIBRATION", "description": "Wait for a "
         "synchronization/calibration pulse (~56 ticks, longer than any "
         "nibble pulse)."},
        {"name": "MEASURE_CALIBRATION", "description": "Measure the "
         "calibration pulse and divide by 56 to obtain the per-frame tick "
         "time."},
        {"name": "DECODE_STATUS", "description": "Decode the status & serial "
         "communication nibble (status bits + slow-channel bit 2/3)."},
        {"name": "DECODE_DATA", "description": "Decode the 1-6 data nibbles by "
         "measuring each falling-edge-to-falling-edge period."},
        {"name": "DECODE_CRC", "description": "Decode the CRC nibble and "
         "recompute CRC-4 over the data nibbles to validate the frame."},
        {"name": "FRAME_DONE", "description": "Output the decoded values and "
         "flags; optionally consume a pause pulse; return to "
         "WAIT_CALIBRATION."},
    ]
    d["fsm_states_transmitter"] = [
        {"name": "SEND_CALIBRATION", "description": "Emit the 56-tick "
         "synchronization/calibration pulse."},
        {"name": "SEND_STATUS", "description": "Emit the status & serial "
         "communication nibble (12 + value ticks)."},
        {"name": "SEND_DATA", "description": "Emit the 1-6 data nibbles."},
        {"name": "SEND_CRC", "description": "Emit the CRC-4 nibble."},
        {"name": "SEND_PAUSE", "description": "Optionally emit a pause pulse to "
         "fix the frame length, then start the next frame."},
    ]
    d["fsm_hints"] = {
        "trigger": "Basic SENT: the transmitter free-runs, emitting frames "
        "back-to-back. SENT-SPC: an ECU master trigger pulse starts a frame.",
        "rule": "Every frame starts with the 56-tick calibration pulse; the "
        "receiver recalibrates the tick time each frame before decoding "
        "nibbles.",
        "decode": "nibble_value = round(period_ticks / tick_time) - 12.",
    }
    d["exit_from_reset_or_poweron"] = (
        "On power-up the sensor begins transmitting frames (basic SENT) or "
        "waits for an ECU master trigger pulse (SENT-SPC). The receiver waits "
        "for the first synchronization/calibration pulse to synchronize.")
    d["default_ready_state_recommendation"] = {
        "idle": "The signal line idles high between pulses; a frame is "
                "delimited by its 56-tick calibration pulse.",
        "resync": "On a calibration-pulse or CRC error, resynchronize at the "
                  "next 56-tick calibration pulse.",
    }
    d["configurations"] = [
        {"name": "Asynchronous SENT", "description": "Free-running "
         "unidirectional transmission; frames back-to-back."},
        {"name": "SENT with pause pulse", "description": "Fixed frame length "
         "via an optional pause pulse."},
        {"name": "SENT-SPC", "description": "Synchronous, ECU-triggered, "
         "addressable (channel selection by trigger pulse width)."},
    ]
    d["timing_dependency_rule"] = (
        "All nibble decoding depends on the per-frame tick time recovered from "
        "the 56-tick synchronization/calibration pulse; without a valid "
        "calibration pulse the nibble periods cannot be converted to values.")
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
        {"name": "CRC-4 nibble", "purpose": "Per-frame integrity check over "
         "the data nibbles; mismatch flags a corrupted frame."},
        {"name": "Calibration-pulse measurement", "purpose": "A pulse not "
         "near 56 ticks indicates loss of frame synchronization."},
        {"name": "Nibble-period range check", "purpose": "A measured period "
         "outside 12-27 ticks indicates a framing error."},
        {"name": "Status nibble", "purpose": "Carries 2 status bits "
         "observable each frame."},
        {"name": "Slow serial message", "purpose": "Short/Enhanced serial "
         "message carries IDs and diagnostic codes over many frames."},
    ]
    d["error_detection_mechanisms"] = [
        "4-bit CRC (CRC-4) nibble over the data nibbles detects frame "
        "corruption.",
        "Out-of-range nibble period (outside 12-27 ticks) detects framing "
        "errors.",
        "Calibration pulse not near 56 ticks detects loss of synchronization.",
        "ECU plausibility checks across successive frames detect implausible "
        "value changes.",
    ]
    d["test_modes"] = [
        {"name": "Frame capture / decode", "purpose": "Capture the single-wire "
         "pulse train and decode nibbles for bring-up."},
        {"name": "Tick-time / calibration test", "purpose": "Verify the "
         "receiver recovers the tick time from the 56-tick calibration "
         "pulse across the tolerance range."},
        {"name": "CRC error injection", "purpose": "Inject CRC errors to "
         "confirm detection."},
        {"name": "SPC trigger test", "purpose": "Exercise the SENT-SPC master "
         "trigger pulse and channel selection."},
    ]
    d["interrupt_or_event_sources"] = [
        {"event": "Frame received", "trigger": "A complete valid frame "
         "decoded (CRC pass)."},
        {"event": "CRC error", "trigger": "CRC-4 mismatch."},
        {"event": "Sync loss", "trigger": "Calibration pulse out of range."},
        {"event": "Slow message complete", "trigger": "A Short/Enhanced serial "
         "message fully assembled."},
    ]
    d["notes"] = (
        "SENT's protocol-level observability is the per-frame CRC-4 nibble, "
        "the calibration-pulse and nibble-period range checks, the status "
        "nibble, and the slow serial message. Chip-level JTAG/scan/BIST "
        "remain sensor/SoC-integrator concerns.")
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
        "SENT_STANDARD": "SAE J2716",
        "MODULATION": "single-wire push-pull pulse-width (falling edge)",
        "TICK_NOMINAL_US": _TICK_NOMINAL_US,
        "TICK_MIN_US": _TICK_MIN_US,
        "TICK_MAX_US": _TICK_MAX_US,
        "SYNC_CALIBRATION_TICKS": _SYNC_CAL_TICKS,
        "NIBBLE_BITS": _NIBBLE_BITS,
        "NIBBLE_OFFSET_TICKS": _NIBBLE_OFFSET_TICKS,
        "NIBBLE_VALUE_MAX": _NIBBLE_VALUE_MAX,
        "NIBBLE_PERIOD_MIN_TICKS": _NIBBLE_PERIOD_MIN_TICKS,
        "NIBBLE_PERIOD_MAX_TICKS": _NIBBLE_PERIOD_MAX_TICKS,
        "MIN_NIBBLE_LOW_TICKS": _MIN_NIBBLE_LOW_TICKS,
        "CRC_BITS": _CRC_BITS,
        "DATA_NIBBLE_MIN": _DATA_NIBBLE_MIN,
        "DATA_NIBBLE_MAX": _DATA_NIBBLE_MAX,
        "UNIDIRECTIONAL": True,
        "POINT_TO_POINT": True,
        "EMBEDDED_CLOCK": True,
        "FORWARDED_CLOCK": False,
    })
    d["frame_format_constants"] = {
        "frame_order": list(_FRAME_NIBBLE_ORDER),
        "sync_calibration_ticks": _SYNC_CAL_TICKS,
        "nibble_pulse_period_ticks": "12 + value",
        "crc_bits": _CRC_BITS,
    }
    d["crc_constants"] = {
        "crc4_nibble": {"width_bits": _CRC_BITS,
                        "coverage": "data nibbles (optionally status nibble)"},
    }
    kc = _ensure_dict(d, "key_constants_for_RTL_authoring")
    kc.update({
        "is_single_wire": True,
        "is_unidirectional": True,
        "is_point_to_point": True,
        "edge_of_interest": "falling",
        "embedded_clock": True,
        "forwarded_clock": False,
        "tick_nominal_us": _TICK_NOMINAL_US,
        "tick_range_us": [_TICK_MIN_US, _TICK_MAX_US],
        "sync_calibration_ticks": _SYNC_CAL_TICKS,
        "nibble_bits": _NIBBLE_BITS,
        "nibble_offset_ticks": _NIBBLE_OFFSET_TICKS,
        "nibble_value_max": _NIBBLE_VALUE_MAX,
        "nibble_period_ticks": [_NIBBLE_PERIOD_MIN_TICKS,
                                _NIBBLE_PERIOD_MAX_TICKS],
        "crc_bits": _CRC_BITS,
        "data_nibble_range": [_DATA_NIBBLE_MIN, _DATA_NIBBLE_MAX],
        "frame_order": list(_FRAME_NIBBLE_ORDER),
        "spc_variant": True,
        "slow_serial_channel": True,
    })
    d["default_signal_values_when_idle"] = {
        "line_idle": "The signal line idles high between nibble pulses.",
        "frame_delim": "A frame is delimited by its 56-tick calibration "
                       "pulse.",
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
        "modulation": "single-wire push-pull pulse; falling-edge-to-"
                      "falling-edge period in ticks carries the nibble value",
        "tick_nominal_us": _TICK_NOMINAL_US,
        "tick_range_us": [_TICK_MIN_US, _TICK_MAX_US],
        "min_nibble_low_ticks": _MIN_NIBBLE_LOW_TICKS,
        "clock_recovery": "tick time from the 56-tick calibration pulse; no "
                          "forwarded clock.",
    }
    d["nibble_waveform"] = {
        "rule": "nibble pulse period = 12 + value ticks (value 0-15)",
        "period_range_ticks": [_NIBBLE_PERIOD_MIN_TICKS,
                               _NIBBLE_PERIOD_MAX_TICKS],
        "edge": "each pulse begins with a falling edge; measure to the next "
                "falling edge.",
    }
    d["frame_waveform"] = {
        "order": list(_FRAME_NIBBLE_ORDER),
        "sync_calibration_ticks": _SYNC_CAL_TICKS,
        "crc": "4-bit CRC (CRC-4) nibble after the data nibbles.",
        "pause": "optional pause pulse pads the frame to a constant length.",
    }
    d["spc_waveform"] = {
        "trigger": "ECU master trigger pulse starts a frame (synchronous).",
        "response": "sensor returns a standard SENT frame.",
        "addressing": "trigger pulse width selects the data channel.",
    }
    d["general_timing_rule"] = (
        "Each frame begins with the 56-tick synchronization/calibration pulse "
        "the receiver uses to recover the tick time; nibble values are decoded "
        "as round(period_ticks / tick_time) - 12.")
    d["data_rate_waveform"] = {
        "tick_nominal_us": _TICK_NOMINAL_US,
        "nibble_pulse_period_ticks": "12 + value",
        "modulation": "single-wire pulse-width (falling edge)",
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
        "Single-wire automotive sensor interface controller: a SENT (SAE "
        "J2716) transmitter (smart sensor) or receiver (ECU) that encodes/"
        "decodes nibble pulses (12 + value ticks, falling-edge timed), frames "
        "them with a 56-tick synchronization/calibration pulse, a status "
        "nibble, 1-6 data nibbles, and a 4-bit CRC nibble, carries a slow "
        "serial channel in the status nibble, and optionally implements the "
        "synchronous SENT-SPC master-trigger variant.")
    d["topology_description"] = (
        "Point-to-point: one smart sensor drives one ECU over a single signal "
        "wire (plus supply and ground). One SENT wire per sensor; no bus, no "
        "multi-drop, no addressing in basic mode.")
    io = _ensure_dict(d, "integration_overview")
    io.update({
        "sent_standard": "SAE J2716",
        "tick_nominal_us": _TICK_NOMINAL_US,
        "tick_range_us": [_TICK_MIN_US, _TICK_MAX_US],
        "sync_calibration_ticks": _SYNC_CAL_TICKS,
        "nibble_bits": _NIBBLE_BITS,
        "nibble_pulse_period_ticks": "12 + value",
        "crc_bits": _CRC_BITS,
        "data_nibble_range": [_DATA_NIBBLE_MIN, _DATA_NIBBLE_MAX],
        "modulation": "single-wire push-pull pulse-width (falling edge)",
        "clocking": "embedded (tick time from the 56-tick calibration pulse)",
        "unidirectional": True,
        "point_to_point": True,
        "spc_variant": True,
        "interfaces": {"signal": "single SENT signal wire (0 V / 5 V)",
                       "supply": "5 V supply",
                       "ground": "common ground"},
    })
    d["interface_categories"] = [
        "Signal interface — single push-pull SENT wire (nibble pulses).",
        "Power interface — supply and ground (three-wire interface).",
        "Frame interface — calibration pulse + status + data + CRC nibbles.",
        "SPC interface — optional ECU master trigger pulse (synchronous).",
    ]
    d["interconnect_topologies_supported"] = [
        "Point-to-point sensor -> ECU (one wire per sensor).",
        "Asynchronous free-running SENT (frames back-to-back).",
        "SENT with optional pause pulse (fixed frame length).",
        "Synchronous SENT-SPC (ECU master trigger, addressable channels).",
    ]
    d["default_signal_values_when_omitted"] = (
        "The signal line idles high between pulses; in basic SENT the sensor "
        "transmits continuously, so an idle wire indicates no sensor or a "
        "fault.")
    d["soc_dependent_items"] = [
        "Tick time (nominal 3 us; 3-90 us).",
        "Number of data nibbles (1-6) and channel format.",
        "Pause-pulse enable and target frame length.",
        "CRC variant (data-only vs status+data).",
        "Slow-channel content (Short vs Enhanced serial message).",
        "Asynchronous SENT vs synchronous SENT-SPC.",
    ]
    d["device_classes_examples"] = [
        "SENT smart sensor (pressure / position / mass-air-flow) — "
        "transmitter",
        "ECU SENT receiver / decoder",
        "SENT-SPC master (ECU trigger) controller",
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
        "Tick-time recovery: measure the 56-tick synchronization/calibration "
        "pulse across the 3-90 us range and +/- 20% drift.",
        "Nibble decoding: pulse period 12 + value ticks for value 0..15 "
        "(12..27 ticks).",
        "Frame order: calibration pulse -> status nibble -> 1-6 data nibbles "
        "-> CRC nibble -> optional pause pulse.",
        "Two-channel format: two independent 12-bit channels in six data "
        "nibbles.",
        "CRC-4 nibble: correct computation and error detection over the data "
        "nibbles.",
        "Status nibble: status bits and slow-channel bit 2/3 extraction.",
        "Slow serial channel: Short Serial Message (16 frames) and Enhanced "
        "Serial Message assembly.",
        "Pause pulse: fixed total frame length.",
        "SENT-SPC: master trigger pulse, synchronous response, channel "
        "selection by trigger width.",
        "Error handling: out-of-range nibble period, calibration-pulse loss, "
        "CRC mismatch, plausibility.",
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
        {"field": "Sensor identifier",
         "location": "sensor configuration / slow serial message",
         "note": "A device ID conveyed in the Short/Enhanced serial message; "
                 "typically factory-programmed, not a protocol-fixed OTP "
                 "concept."},
        {"field": "Frame format (data nibble count, channel format)",
         "location": "sensor configuration",
         "note": "Fixed for a given sensor; programmed at manufacture."},
        {"field": "Tick time / timing configuration",
         "location": "sensor configuration",
         "note": "The nominal tick time and pause-pulse setting."},
        {"field": "CRC / slow-channel configuration",
         "location": "sensor configuration",
         "note": "CRC variant and slow-channel message content."},
    ]
    d["notes"] = (
        "SENT does not define OTP/fuse content as a protocol concept. The "
        "sensor ID, frame format, tick time, and slow-channel content are "
        "sensor configuration (often factory-programmed and partly "
        "discoverable via the slow serial message); an implementation may back "
        "these with non-volatile storage, but the standard only requires the "
        "frame format be consistent and the ID be conveyable over the slow "
        "channel.")
    _write(p, d)


# ----------------------------------------------------------------------
# L12 — behavioral sequences.
# ----------------------------------------------------------------------
def _l12(gd: Path) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["frame_transmit_sequence"] = [
        "1. Emit the synchronization/calibration pulse (nominal 56 ticks).",
        "2. Emit the status & serial communication nibble (12 + value ticks).",
        "3. Emit the 1-6 data nibbles (each 12 + value ticks).",
        "4. Emit the CRC-4 nibble (12 + value ticks).",
        "5. Optionally emit a pause pulse to fix the frame length; then begin "
        "the next frame.",
    ]
    d["frame_receive_sequence"] = [
        "1. Detect the synchronization/calibration pulse (~56 ticks, longer "
        "than any nibble pulse).",
        "2. Measure it and divide by 56 to recover the per-frame tick time.",
        "3. For each following pulse, measure its falling-edge-to-falling-edge "
        "period, divide by the tick time, round, and subtract 12 -> nibble "
        "value (0-15).",
        "4. Decode the status nibble, then the data nibbles, then the CRC "
        "nibble.",
        "5. Recompute the CRC-4 over the data nibbles and compare; flag a "
        "frame error on mismatch.",
        "6. Accumulate bit 2 / bit 3 of the status nibble into the slow serial "
        "channel message.",
    ]
    d["slow_serial_sequence"] = [
        "1. Each frame contributes bit 2 (serial data) and bit 3 (start) of "
        "the status nibble.",
        "2. Sixteen frames assemble a Short Serial Message (4-bit ID + 8-bit "
        "data + 4-bit CRC); ~18 frames assemble an Enhanced Serial Message.",
        "3. The receiver validates the message CRC and outputs the ID / data.",
    ]
    d["spc_sequence"] = [
        "1. The ECU drives a master trigger pulse on the signal line (the "
        "pulse width may select a data channel).",
        "2. The sensor responds with a standard SENT frame (calibration "
        "pulse -> status -> data -> CRC).",
        "3. The ECU decodes the frame; the exchange is synchronous and "
        "addressable.",
    ]
    d["resync_sequence"] = [
        "1. On a calibration-pulse or CRC error, discard the frame.",
        "2. Resynchronize at the next 56-tick synchronization/calibration "
        "pulse.",
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
        {"name": "Tick time", "purpose": "Verify the nominal 3 us tick (range "
         "3-90 us) and the +/- 20% drift tolerance."},
        {"name": "Synchronization/calibration pulse", "purpose": "Confirm the "
         "56-tick pulse and the receiver's per-frame tick-time recovery."},
        {"name": "Nibble pulse period", "purpose": "Confirm 12 + value ticks "
         "(12..27) for value 0..15 and the minimum 5-tick low time."},
        {"name": "Falling-edge timing", "purpose": "Confirm falling-edge-to-"
         "falling-edge period accuracy (single edge nibble transmission)."},
        {"name": "CRC-4 nibble", "purpose": "Confirm correct CRC-4 computation "
         "and error detection."},
        {"name": "Slow serial channel", "purpose": "Confirm Short/Enhanced "
         "serial message assembly and CRC."},
        {"name": "SENT-SPC trigger", "purpose": "Confirm master-trigger-pulse "
         "timing and channel selection."},
    ]
    d["notes"] = (
        "SENT characterization centers on the tick-time accuracy and recovery "
        "from the 56-tick calibration pulse, the nibble pulse-period encoding "
        "(12 + value ticks), falling-edge timing, the CRC-4 nibble, the slow "
        "serial channel, and (if used) the SENT-SPC master trigger. "
        "Conformance is established by SAE J2716 compliance testing.")
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
    f["spec_version"] = "SAE J2716 — Single Edge Nibble Transmission (SENT)"
    f["previous_versions"] = [
        "SAE J2716 (2007) — initial SENT: single-wire nibble pulse-width "
        "sensor interface.",
        "SAE J2716 (2010) — slow serial channel (Short/Enhanced), pause "
        "pulse, SENT-SPC variant.",
    ]
    f["key_changes"] = [
        {"version": "SAE J2716 (2010+)", "summary": "Standardized the slow "
         "serial communication channel (Short Serial Message and Enhanced "
         "Serial Message), the optional pause pulse for fixed frame length, "
         "and the synchronous SENT-SPC (Short PWM Code) master-trigger "
         "variant; clarified CRC-4 and timing tolerances."},
    ]
    f["future_versions_industry_outline"] = [
        {"version": "SAE J2716 (later revisions)", "summary": "Continued "
         "refinement of the slow channel, CRC, and SPC addressing while "
         "preserving the tick/nibble pulse-width encoding and the message "
         "frame format."},
    ]
    f["backward_compat_traps"] = [
        {"trap_name": "Nibble_is_12_plus_value",
         "rule": "A nibble pulse period is 12 + value ticks (value 0-15), not "
                 "the raw value.",
         "trap": "Treating the period as the value (forgetting the 12-tick "
                 "offset) decodes every nibble wrong."},
        {"trap_name": "Per_frame_tick_recovery",
         "rule": "The tick time is recovered from the 56-tick calibration "
                 "pulse every frame.",
         "trap": "Assuming a fixed nominal 3 us tick ignores transmitter drift "
                 "(up to +/- 20%) and misdecodes nibbles."},
        {"trap_name": "Unidirectional_basic",
         "rule": "Basic SENT is unidirectional sensor->ECU; only SENT-SPC adds "
                 "an ECU trigger.",
         "trap": "Expecting an ECU request in basic SENT is wrong."},
        {"trap_name": "Not_LIN_not_DALI_not_PWM",
         "rule": "SENT is pulse-width nibble timing on one wire with a 56-tick "
                 "calibration pulse and CRC-4 nibble; LIN is UART/PID, DALI is "
                 "Manchester, PWM is duty cycle.",
         "trap": "Applying LIN PID/break, DALI Manchester, or PWM duty-cycle "
                 "decoding to a SENT stream is wrong."},
    ]
    f["version_naming_history_note"] = (
        "Single Edge Nibble Transmission is standardized by SAE International "
        "as SAE J2716 (SENT). The interface preserves a single-wire pulse-"
        "width nibble encoding (12 + value ticks), a 56-tick synchronization/"
        "calibration pulse, a status nibble, 1-6 data nibbles, and a 4-bit CRC "
        "nibble across revisions; later revisions added the slow serial "
        "communication channel, the pause pulse, and the SENT-SPC (Short PWM "
        "Code) synchronous variant.")
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
    f["nibble_encoding_table"] = {
        "header_columns": ["Nibble value", "Pulse period (ticks)"],
        "rows": [
            ["0", "12"], ["1", "13"], ["7", "19"], ["8", "20"],
            ["15", "27"],
        ],
        "rule": "pulse period (ticks) = 12 + value; value 0-15.",
    }
    f["frame_format_table"] = {
        "header_columns": ["Order", "Element", "Period (ticks)"],
        "rows": [
            ["1", "Synchronization/Calibration pulse", "56"],
            ["2", "Status & Serial Communication nibble", "12 + value"],
            ["3", "Data nibbles (1-6)", "12 + value each"],
            ["4", "CRC nibble (CRC-4)", "12 + value"],
            ["5", "Pause pulse (optional)", "variable"],
        ],
    }
    f["timing_table"] = {
        "header_columns": ["Parameter", "Value"],
        "rows": [
            ["Tick (unit time) nominal", "3 us"],
            ["Tick range", "3-90 us"],
            ["Synchronization/calibration pulse", "56 ticks"],
            ["Nibble pulse period", "12-27 ticks (12 + value)"],
            ["Minimum nibble low time", "5 ticks"],
            ["Transmitter tick tolerance", "+/- 20% (basic)"],
        ],
    }
    f["slow_channel_table"] = {
        "header_columns": ["Message", "Frames", "Payload"],
        "rows": [
            ["Short Serial Message", "16",
             "4-bit ID + 8-bit data + 4-bit CRC (16-bit)"],
            ["Enhanced Serial Message", "~18",
             "configuration / identification (extended ID + data + CRC)"],
        ],
    }
    f["crc_table"] = {
        "header_columns": ["CRC", "Width (bits)", "Coverage"],
        "rows": [
            ["CRC-4 nibble", "4", "data nibbles (optionally status nibble)"],
        ],
    }
    f["encoding_note"] = (
        "SENT encodes each 4-bit nibble as a single-wire pulse of (12 + value) "
        "ticks, measured falling-edge to falling-edge. A frame is a 56-tick "
        "synchronization/calibration pulse, a status nibble, 1-6 data nibbles, "
        "and a 4-bit CRC nibble, with an optional pause pulse. The slow serial "
        "channel (Short/Enhanced Serial Message) rides in bit 2/3 of the "
        "status nibble.")
    f["tables"] = [
        "Nibble-encoding table (value -> 12 + value ticks)",
        "Frame-format table (calibration/status/data/CRC/pause)",
        "Timing table (tick, 56-tick calibration pulse, tolerances)",
        "Slow-channel table (Short / Enhanced serial message)",
        "CRC table (4-bit CRC-4 nibble)",
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
        "Unidirectional, point-to-point, single-signal-wire interface "
        "(three-wire) per SAE J2716.",
        "Tick unit time (nominal 3 us, range 3-90 us); nibble pulse period = "
        "12 + value ticks (value 0-15).",
        "56-tick synchronization/calibration pulse at the start of each frame "
        "with per-frame tick-time recovery.",
        "Frame order: calibration pulse -> status nibble -> 1-6 data nibbles "
        "-> 4-bit CRC nibble -> optional pause pulse.",
        "4-bit CRC (CRC-4) nibble over the data nibbles.",
        "Slow serial communication channel (Short/Enhanced Serial Message) in "
        "bit 2/3 of the status nibble.",
        "Falling-edge-to-falling-edge timing (single edge nibble "
        "transmission).",
    ]
    f["must_not_have_properties"] = [
        "A UART-based bus with a break field, sync field, and protected "
        "identifier (PID) and a master schedule (that is LIN, not SENT).",
        "Manchester-coded bidirectional lighting bus signaling (that is DALI, "
        "not SENT).",
        "Start/stop-bit byte framing on a shared bus (that is UART, not "
        "SENT).",
        "A fixed-period duty-cycle (PWM) value with no nibbles, tick count, "
        "calibration pulse, or CRC nibble (that is generic PWM, not SENT).",
    ]
    f["compliance_failure_modes"] = [
        {"mode": "CRC-4 mismatch", "trigger": "The recomputed CRC over the "
         "data nibbles differs from the transmitted CRC nibble."},
        {"mode": "Out-of-range nibble period", "trigger": "A nibble pulse "
         "outside 12-27 ticks."},
        {"mode": "Calibration-pulse loss", "trigger": "No ~56-tick pulse "
         "detected; the receiver resynchronizes."},
        {"mode": "Tick-drift misdecode", "trigger": "Using a stale tick time "
         "instead of recalibrating from the 56-tick pulse each frame."},
    ]
    f["min_link_constraint"] = (
        "A SENT link requires one signal wire driven by the sensor and read by "
        "the ECU; the receiver must detect the 56-tick synchronization/"
        "calibration pulse and recover the tick time before any nibble can be "
        "decoded.")
    f["reset_behavior_compliance"] = (
        "On power-up the sensor begins transmitting frames (or waits for the "
        "ECU master trigger in SENT-SPC); the receiver synchronizes on the "
        "first 56-tick calibration pulse and resynchronizes after any "
        "calibration-pulse or CRC error.")
    f["sent_distinguishers"] = (
        "SENT is identified by ALL of: a single-signal-wire, unidirectional, "
        "point-to-point sensor interface (three-wire); pulse-width nibble "
        "encoding where each 4-bit nibble is a pulse of 12 + value ticks "
        "measured falling-edge to falling-edge; a 56-tick synchronization/"
        "calibration pulse the receiver uses to recover the per-frame tick "
        "time; a message frame of calibration pulse + status nibble + 1-6 data "
        "nibbles + a 4-bit CRC (CRC-4) nibble + optional pause pulse; a slow "
        "serial channel (Short/Enhanced Serial Message) in bit 2/3 of the "
        "status nibble; and an optional synchronous SENT-SPC (Short PWM Code) "
        "master-trigger variant. This is distinct from LIN (a UART-based bus "
        "with break/sync/PID and a master schedule), DALI (a Manchester-coded "
        "lighting bus), UART (start/stop-bit byte framing), and generic PWM (a "
        "fixed-period duty cycle).")
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
        {"name": "SENT signal",
         "direction": "sensor -> ECU (unidirectional; bidirectional in SPC)",
         "purpose": "Single push-pull wire carrying nibble pulses "
                    "(falling-edge-to-falling-edge tick timing).",
         "active_levels": "0 V (low) / 5 V (high)", "idle_level": "high"},
        {"name": "Supply",
         "direction": "to sensor",
         "purpose": "5 V supply.",
         "active_levels": "5 V", "idle_level": "5 V"},
        {"name": "Ground",
         "direction": "common",
         "purpose": "Ground reference.",
         "active_levels": "0 V", "idle_level": "0 V"},
    ]
    f["logical_signaling_levels"] = [
        {"name": "Calibration pulse", "meaning": "56-tick pulse delimiting a "
         "frame and recovering the tick time."},
        {"name": "Nibble pulse", "meaning": "12 + value ticks; carries 4 bits "
         "of data/status/CRC."},
        {"name": "Pause pulse", "meaning": "Optional padding to a fixed frame "
         "length."},
    ]
    f["packet_types_summary"] = [
        {"class": "Frame element", "members": list(_FRAME_NIBBLE_ORDER),
         "count": len(_FRAME_NIBBLE_ORDER)},
        {"class": "Slow serial message",
         "members": ["Short Serial Message", "Enhanced Serial Message"],
         "count": 2},
    ]
    cc = _ensure_dict(f, "channel_counts")
    cc.update({
        "signal_wires": 1,
        "total_wires": 3,
        "nibble_bits": _NIBBLE_BITS,
        "crc_bits": _CRC_BITS,
        "data_nibble_max": _DATA_NIBBLE_MAX,
        "sync_calibration_ticks": _SYNC_CAL_TICKS,
        "tick_nominal_us": _TICK_NOMINAL_US,
        "slow_message_type_count": 2,
    })
    f["global_signals"] = [
        {"name": "Tick (unit time)", "purpose": "The time base; recovered from "
         "the 56-tick calibration pulse each frame."},
        {"name": "Frame", "purpose": "calibration pulse + status + data + CRC "
         "(+ optional pause)."},
        {"name": "Slow channel", "purpose": "Serial message assembled from "
         "status-nibble bit 2/3 across frames."},
    ]
    f["dependency_graph"] = {
        "common_rule": "A nibble cannot be decoded until the receiver has "
        "measured the 56-tick synchronization/calibration pulse and recovered "
        "the per-frame tick time. Each frame is independent: the calibration "
        "pulse re-establishes the tick time.",
        "data_dependency": "A data nibble value = round(period_ticks / "
        "tick_time) - 12; the CRC nibble validates the data nibbles; the slow "
        "channel accumulates bit 2/3 of the status nibble.",
    }
    f["handshake_pairs"] = [
        {"name": "Calibration / decode", "from": "transmitter", "to": "ECU",
         "rule": "The 56-tick calibration pulse sets the tick time for all "
                 "nibbles in the frame."},
        {"name": "SPC trigger / response", "from": "ECU", "to": "sensor",
         "rule": "An ECU master trigger pulse elicits a SENT frame "
                 "(synchronous, addressable)."},
    ]
    f["ordering_rules"] = {
        "frame_order": "calibration pulse -> status nibble -> data nibbles -> "
        "CRC nibble -> optional pause pulse.",
        "edge_order": "each pulse begins with a falling edge; nibble value is "
        "the falling-edge-to-falling-edge period minus 12 ticks.",
        "slow_channel": "bit 2/3 of the status nibble accumulate across frames "
        "into a Short/Enhanced serial message.",
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
        "Point-to-point single-wire link: one smart sensor (transmitter) "
        "drives one ECU (receiver) over a single signal wire. There is no bus, "
        "no multi-drop, and no addressing in basic SENT; each sensor has its "
        "own SENT wire to the ECU.")
    f["supported_topologies"] = [
        {"name": "Point-to-point", "description": "One sensor -> one ECU over "
         "one signal wire (plus supply and ground)."},
        {"name": "Asynchronous SENT", "description": "Free-running "
         "transmission; frames back-to-back."},
        {"name": "SENT-SPC", "description": "Synchronous ECU-triggered "
         "exchange; the trigger pulse width selects a channel "
         "(addressable)."},
    ]
    f["master_slave_role_summary"] = [
        {"role": "Sensor (transmitter)", "description": "Encodes sensor data "
         "as nibble pulses and transmits SENT frames; the only talker in "
         "basic SENT."},
        {"role": "ECU (receiver)", "description": "Decodes the nibble stream, "
         "validates the CRC, and consumes the data; in SENT-SPC it also drives "
         "the master trigger pulse."},
    ]
    f["interconnect_role"] = (
        "SENT is a single-wire sensor-to-ECU link. Data flows one way (sensor "
        "to ECU) as pulse-width nibble timing; the optional SENT-SPC variant "
        "lets the ECU trigger and address the sensor on the same wire.")
    f["routing_methods"] = ["point-to-point (no routing)"]
    f["ordering_guarantees"] = {
        "frame": "Frames are transmitted in order; each is self-delimited by "
        "its 56-tick calibration pulse.",
        "nibble": "Nibbles are ordered status -> data -> CRC within a frame.",
        "slow_channel": "Slow-channel bits accumulate in frame order.",
    }
    f["memory_vs_peripheral_regions"] = (
        "SENT is not memory-mapped; it is a timed pulse stream on a single "
        "wire. There is no address space — one sensor per wire (basic SENT); "
        "SENT-SPC selects a data channel by trigger-pulse width.")
    dc = _ensure_dict(f, "device_classification")
    dc["transmitter"] = "Smart sensor that emits SENT frames."
    dc["receiver"] = "ECU that decodes the nibble stream."
    dc["spc_master"] = "ECU that drives the SENT-SPC master trigger pulse."
    f["default_signal_values_evidence_tables"] = [
        "SENT single-wire interface figure (signal + supply + ground)",
        "Message frame figure (calibration / status / data / CRC / pause)",
        "Nibble pulse-width figure (12 + value ticks, falling edge)",
        "SENT-SPC trigger/response figure",
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
        "signaling": "single-wire push-pull (0 V / 5 V); pulse-width "
                     "(falling-edge) encoding",
        "tick_nominal_us": _TICK_NOMINAL_US,
        "tick_range_us": [_TICK_MIN_US, _TICK_MAX_US],
        "sync_calibration_ticks": _SYNC_CAL_TICKS,
        "nibble_pulse_period_ticks": "12 + value (12..27)",
        "min_nibble_low_ticks": _MIN_NIBBLE_LOW_TICKS,
        "crc_bits": _CRC_BITS,
        "clocking": "embedded (tick time recovered from the 56-tick "
                    "calibration pulse)",
        "unidirectional": True,
        "spc_variant": True,
    }
    f["notes"] = (
        "SENT (SAE J2716) is a single-wire sensor-interface standard: it fixes "
        "the pulse-width nibble encoding (12 + value ticks), the 56-tick "
        "synchronization/calibration pulse and per-frame tick-time recovery, "
        "the message frame format (status + 1-6 data nibbles + 4-bit CRC "
        "nibble + optional pause), the slow serial channel, and the SENT-SPC "
        "variant. It does NOT impose PDK-specific SDC / floorplan constraints; "
        "the interoperability-critical constraints are the tick/nibble timing, "
        "the calibration pulse, and the CRC-4. Edge timing accuracy and "
        "push-pull driver behavior are physical-layer / board concerns.")
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
        {"name": "CRC-4 nibble", "purpose": "Per-frame integrity check "
         "observable by the ECU."},
        {"name": "Status nibble", "purpose": "Status bits and slow-channel "
         "bit 2/3 observable each frame."},
        {"name": "Slow serial message", "purpose": "Sensor ID / diagnostic "
         "codes over many frames."},
        {"name": "Nibble-period / calibration range checks", "purpose": "Frame "
         "and sync error observability."},
    ]
    f["internal_diagnostics_observability"] = [
        "Decoded data channel values.",
        "CRC pass / frame-error flags.",
        "Calibration-pulse / tick-time recovery status.",
        "Slow serial message buffer (ID / data / CRC).",
    ]
    f["out_of_band_test_facilities"] = [
        "SAE J2716 SENT compliance / conformance testing.",
        "Vendor sensor bring-up and characterization tooling "
        "(implementation-defined).",
    ]
    f["notes"] = (
        "SENT's protocol-level DFT surface is the per-frame CRC-4 nibble, the "
        "status nibble, the slow serial message, and the calibration/nibble "
        "range checks. Chip-level JTAG / scan / BIST remain sensor-vendor / "
        "SoC-integrator concerns; conformance is established by SAE J2716 "
        "compliance testing.")
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
        {"state": "Active", "name": "Active", "description": "Sensor "
         "transmitting frames (or responding to SPC triggers)."},
        {"state": "Idle", "name": "Idle", "description": "Signal line high "
         "between pulses; in SENT-SPC the sensor idles until triggered."},
    ]
    f["wakeup_mechanism"] = (
        "In basic SENT the sensor free-runs while powered. In SENT-SPC the "
        "sensor responds to the ECU master trigger pulse, so it can idle "
        "between triggers and wake on the trigger edge.")
    f["power_rails"] = [
        {"rail": "VCC / supply (5 V)", "purpose": "Sensor supply via the "
         "supply wire."},
        {"rail": "Signal driver", "purpose": "Push-pull driver of the SENT "
         "signal wire."},
        {"rail": "GND", "purpose": "Ground."},
    ]
    f["sent_power_considerations"] = (
        "SENT defines a simple three-wire supply (signal + 5 V supply + "
        "ground). Basic SENT transmits continuously; SENT-SPC allows the "
        "sensor to idle between ECU triggers to save power. Detailed rails and "
        "low-power behavior are sensor-implementation concerns.")
    f["notes"] = (
        "SENT's protocol-level power intent is minimal: a 5 V supply over the "
        "three-wire interface, continuous transmission in basic SENT, and "
        "trigger-gated activity in SENT-SPC. Fine-grained power-domain control "
        "is a sensor / SoC concern.")
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
        "Tick-time recovery — measure the 56-tick calibration pulse across "
        "3-90 us and +/- 20% drift.",
        "Nibble encoding — pulse period 12 + value ticks for value 0..15.",
        "Frame format — calibration pulse / status / 1-6 data nibbles / CRC / "
        "pause.",
        "Two-channel format — two 12-bit channels in six data nibbles.",
        "CRC-4 nibble — computation and error detection.",
        "Status nibble — status bits and slow-channel bit 2/3.",
        "Slow serial channel — Short Serial Message and Enhanced Serial "
        "Message assembly.",
        "Pause pulse — fixed total frame length.",
        "SENT-SPC — master trigger, synchronous response, channel selection.",
        "Error handling — out-of-range nibble period, calibration-pulse loss, "
        "CRC mismatch, plausibility.",
    ]
    f["notes"] = (
        "SENT does not ship an embedded testbench, but the standard implies a "
        "verification plan spanning the tick/nibble pulse-width encoding, the "
        "56-tick calibration pulse and tick-time recovery, the message frame "
        "format, the 4-bit CRC nibble, the slow serial channel, and the "
        "SENT-SPC variant. SAE J2716 compliance testing supplies the formal "
        "suite.")
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
        "4-bit CRC (CRC-4) nibble per frame detects data corruption.",
        "Out-of-range nibble-period checks detect framing errors.",
        "Calibration-pulse range checks detect loss of synchronization.",
        "ECU plausibility checks across successive frames.",
    ]
    f["anti_tampering_features"] = []
    f["confidentiality_features"] = []
    f["authentication_features"] = []
    f["future_security_pointers"] = [
        "SENT's base protocol provides no cryptographic confidentiality or "
        "authentication on the data path; the CRC-4 is anti-corruption only.",
        "Any sensor authentication / message security would be layered above "
        "SENT by the ECU / vehicle network architecture.",
    ]
    f["notes"] = (
        "SENT is a simple unidirectional single-wire sensor interface: its "
        "built-in protection is anti-corruption (the 4-bit CRC nibble plus "
        "nibble-period and calibration-pulse range checks). The link carries "
        "plaintext nibble pulses. Cryptographic confidentiality / "
        "authentication are NOT part of the base SENT data path; they would be "
        "provided by higher-layer ECU / network security if required.")
    _write(p, d)
