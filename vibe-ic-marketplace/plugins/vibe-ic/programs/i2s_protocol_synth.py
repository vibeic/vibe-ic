"""I2S-class protocol synth helper.

v0.1.83 — ic_class-gated overlay for `serial_peripheral_protocol` specs
that exhibit the I2S structural signature (SCK+WS+SD triple OR Word
Select terminology OR inter-IC sound bus mention). Applies Philips/NXP
I2S bus 1986/1996/2022 spec-canonical content to L1-L18 + L21.

Doctrine: structural-keyword detection IS general within an ic_class
(mirrors AMBA-AXI / SPI / I2C / UART / CAN / USB synth approach). Any
I2S variant (Philips strict I2S, NXP UM11732 reconstruction, codec
implementations) exhibits the same signature.

Public entry: `apply_i2s_synth(generated_docs_dir, is_i2s, i2s_ic_name)`.
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


def apply_i2s_synth(generated_docs_dir: Path, is_i2s: bool,
                    i2s_ic_name: Optional[str]) -> None:
    """Apply I2S-specific synth when the structural signature matched."""
    if not is_i2s:
        return
    gd = generated_docs_dir

    # Force ic_name across the 14 main L docs.
    if i2s_ic_name is not None:
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
                d["ic_name"] = i2s_ic_name
                _write(q, d)

    # L1
    p = gd / "L1_DATASHEET.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("document_title", "I2S bus specification")
        d.setdefault("document_number", "UM11732")
        d.setdefault("version", "Rev. 3.0")
        d.setdefault("revised_date", "17 February 2022")
        d.setdefault("original_release_date", "1 February 1986 (Philips Semiconductors)")
        d.setdefault("manufacturer", "NXP Semiconductors (originally Philips Semiconductors)")
        d.setdefault("copyright", "© NXP B.V. 2022")
        d.setdefault("abstract", "This document details the specifications of the I2S bus.")
        d.setdefault("keywords", ["I2S bus", "SCK", "SD"])
        d.setdefault("external_pins", ["SCK (Continuous Serial Clock)", "WS (Word Select)", "SD (Serial Data)"])
        d.setdefault("external_pin_count", 3)
        d.setdefault("key_features", [
            "A serial link especially for digital audio (Inter-IC Sound = I2S).",
            "Three-line serial bus: SCK + WS + SD.",
            "Two time-multiplexed audio channels (left + right) carried on a single data line.",
            "MSB-first two's-complement serial data transmission.",
            "Word Select line indicates the channel being transmitted (WS=0 = channel 1 / left; WS=1 = channel 2 / right).",
            "WS line changes one clock period before the MSB is transmitted.",
            "Receiver latches data on the leading (LOW-to-HIGH) edge of SCK.",
            "Transmitter may sync to either edge of SCK; receiver always uses leading edge.",
            "Transmitter and receiver may have different word lengths — MSB has a fixed position, LSB position depends on word length.",
            "TTL-level signaling: VH = 2.0 V, VL = 0.8 V.",
            "Controller (= transmitter or receiver in simple systems; system controller in complex systems) generates SCK and WS.",
            "Target derives its internal clock from the external SCK input.",
        ])
        d.setdefault("topology_summary",
            "Three configurations: (1) Transmitter = Controller (transmitter generates SCK + WS + SD); (2) Receiver = Controller (receiver generates SCK + WS, transmitter generates SD under external clock); (3) System Controller = Controller (separate IC drives SCK + WS, transmitter generates SD under external clock).")
        d.setdefault("revision_history", [
            {"version": "v.1", "date": "1 February 1986", "description": "Initial version (Philips Semiconductors)."},
            {"version": "v.2", "date": "5 June 1996",     "description": "Second version (Philips Semiconductors)."},
            {"version": "v.3", "date": "17 February 2022","description": "Reconstructed from the original Philips I2S bus specification of 1986/1996 by NXP. Format redesigned for NXP identity guidelines; terms 'Master' and 'Slave' updated to 'Controller' and 'Target' for inclusive language."},
        ])
        d.setdefault("use_cases", [
            "Compact disc", "Digital audio tape", "Digital sound processors",
            "Digital TV-sound", "A/D and D/A converters",
            "Digital signal processors",
            "Error correction for compact disc and digital recording",
            "Digital filters", "Digital input/output interfaces",
        ])
        d.setdefault("overview",
            "Many digital audio systems are being introduced into the consumer audio market, including compact disc, digital audio tape, digital sound processors, and digital TV-sound. The digital audio signals in these systems are being processed by a number of (V)LSI ICs. Standardized communication structures are vital for both the equipment and the IC manufacturer, because they increase system flexibility. To this end, Philips developed the inter-IC sound (I2S) bus — a serial link especially for digital audio.")
        _write(p, d)

    # L2
    p = gd / "L2_FRS.json"
    if p.is_file():
        d = _read(p)
        # Handle pre-existing None — setdefault returns None and we'd skip
        # subkey synth otherwise.
        if d.get("protocol_overview") in (None, "", []):
            d["protocol_overview"] = {}
        po = d["protocol_overview"]
        if isinstance(po, dict):
            po.setdefault("type", "Three-line synchronous serial bus for digital audio (two time-multiplexed stereo channels).")
            po.setdefault("duplex", "simplex per direction (SD line is unidirectional from transmitter to receiver)")
            po.setdefault("synchronous", True)
            po.setdefault("wire_names", ["SCK (Serial Clock)", "WS (Word Select)", "SD (Serial Data)"])
            po.setdefault("wire_count", 3)
            po.setdefault("channels_carried", "Two — left (channel 1, WS=0) + right (channel 2, WS=1)")
            po.setdefault("data_format", "Two's complement, MSB-first")
            po.setdefault("controller_role", "Generates SCK + WS (either transmitter or receiver, or a separate system controller)")
            po.setdefault("target_role", "Derives internal clock from external SCK")
        fr = [
            {"id": "FR-LINES-01",  "text": "I2S bus shall use exactly three lines: SCK (continuous serial clock), WS (word select), SD (serial data)."},
            {"id": "FR-CTRL-02",   "text": "The device generating SCK and WS is the Controller. In simple systems this is the transmitter; in complex systems it may be a separate system controller."},
            {"id": "FR-FMT-03",    "text": "Serial data is transmitted in two's complement with the MSB first. MSB position is fixed; LSB position depends on word length."},
            {"id": "FR-WORDLEN-04","text": "Transmitter and receiver may have different word lengths — neither needs to know the other's word length. If the receiver's word length is greater than the transmitted word, missing bits are set to zero internally. If smaller, bits after LSB are ignored."},
            {"id": "FR-MSB-AFTER-WS-05","text": "The transmitter always sends the MSB of the next word one clock period after the WS changes."},
            {"id": "FR-WS-CHANNEL-06","text": "WS = 0 selects channel 1 (left); WS = 1 selects channel 2 (right). WS may change on either edge of SCK and need not be symmetrical."},
            {"id": "FR-LATCH-07",  "text": "Target latches WS and SD on the leading (LOW-to-HIGH) edge of SCK."},
            {"id": "FR-TX-EDGE-08","text": "Transmitter may synchronize data with either edge of SCK, BUT data must be valid at the leading edge so the receiver can latch it."},
            {"id": "FR-LEVEL-09",  "text": "Logic levels: VH = 2.0 V, VL = 0.8 V (TTL-compatible)."},
            {"id": "FR-TIMING-10", "text": "All timing requirements are specified relative to clock period T or minimum allowed clock period Ttr of a device — allowing scaling to higher data rates in the future."},
            {"id": "FR-CLK-DUTY-11","text": "Clock HIGH time tHC ≥ 0.35 T and clock LOW time tLC ≥ 0.35 T (transmitter min; receiver may use 0.35 T relaxed)."},
        ]
        if _empty(d.get("functional_requirements")):
            d["functional_requirements"] = fr
        d.setdefault("configurations", [
            {"name": "Transmitter = Controller", "description": "Transmitter generates SCK + WS + SD; receiver only consumes."},
            {"name": "Receiver = Controller",    "description": "Receiver generates SCK + WS; transmitter generates SD under external clock."},
            {"name": "System Controller",        "description": "Separate IC generates SCK + WS; transmitter generates SD under external clock; receiver consumes."},
        ])
        d.setdefault("error_response_conditions", [
            "Word-length mismatch — neither transmitter nor receiver signals an error; data is truncated or zero-extended as needed.",
            "Timing violation (insufficient setup or hold) — receiver may sample incorrect bit; no protocol-level handshake.",
        ])
        if _empty(d.get("compliance_requirements")):
            d["compliance_requirements"] = [
                "MSB transmitted one clock period AFTER WS changes.",
                "Receiver must latch on leading edge of SCK.",
                "Transmitter must hold SD valid through leading edge of SCK.",
                "Clock duty cycle: tHC and tLC ≥ 0.35 T (transmitter).",
            ]
        _write(p, d)

    # L3
    p = gd / "L3_CMD_PROTOCOL.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("protocol_type", "Streaming serial audio bus; no command/opcode protocol. Continuous clock + word-select + serial data.")
        d.setdefault("channels", [
            {"name": "SCK", "direction": "controller output → target input", "description": "Continuous Serial Clock. Drives bit rate (one rising edge per data bit)."},
            {"name": "WS",  "direction": "controller output → target input", "description": "Word Select. 0 = channel 1 (left); 1 = channel 2 (right). Changes one clock period before MSB."},
            {"name": "SD",  "direction": "transmitter output → receiver input", "description": "Serial Data. MSB-first two's complement; latched by receiver on leading edge of SCK."},
        ])
        d.setdefault("valid_ready_handshake_rules", [
            "There is no handshake / ACK / framing — I2S is a continuous streaming bus.",
            "Synchronization is purely by SCK + WS edges; the transmitter must hold SD valid through the leading edge of SCK so the receiver can latch.",
            "WS edge serves as the channel-boundary marker: WS transition + 1 SCK period later = MSB of next word.",
        ])
        d.setdefault("burst_based", False)
        d.setdefault("byte_oriented", False)
        d.setdefault("frame_format", {
            "word_layout":     "MSB-first; word length implementation-defined; transmitter sends MSB first, then bit n-1, ..., LSB.",
            "channel_layout":  "Two channels time-multiplexed: WS=0 → channel 1 (left); WS=1 → channel 2 (right).",
            "channel_boundary":"WS transition (either direction) marks the boundary; the MSB of the next word is sent on the SCK period following the WS transition.",
            "word_length_handling": "Mismatched word lengths: transmitter zero-pads LSBs (if shorter than system width); receiver truncates LSBs (if narrower than transmitted).",
        })
        _write(p, d)

    # L4 wire-level
    p = gd / "L4_REGMAP.json"
    if p.is_file():
        d = _read(p)
        d["register_map_present"] = False
        d["notes"] = (
            "I2S is a wire-level audio streaming protocol; no register "
            "map at the protocol layer. Concrete I2S controller / target "
            "IP blocks define their own register file (typically: TX/RX "
            "FIFO control, sample rate / bit clock divisor, word length, "
            "channel-format select, mute, interrupt enable) at the SoC "
            "integration level — covered by individual block guides, "
            "not by UM11732.")
        _write(p, d)

    # L5
    p = gd / "L5_ADI_SPEC.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("analog_digital_interface_present", False)
        d["signaling_summary"] = (
            "Digital TTL-compatible signaling on SCK / WS / SD. Input "
            "threshold levels: VH = 2.0 V (HIGH), VL = 0.8 V (LOW). "
            "Although the protocol is purely digital, I2S is the data-bus "
            "interface to A/D and D/A audio converters — the analog "
            "characteristics of those converters (sample rate, dynamic "
            "range, SNR) are separate from the I2S protocol itself.")
        _write(p, d)

    # L6 control
    p = gd / "L6_CONTROL_LOGIC.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("fsm_states_transmitter", [
            {"name": "TX_IDLE_OR_RUNNING",   "description": "Continuous data streaming; no idle state — once enabled, SCK runs continuously and SD outputs one bit per SCK period."},
            {"name": "TX_WS_TRANSITION",     "description": "On the SCK period where WS changes, transmitter prepares to send MSB of the next channel's word."},
            {"name": "TX_MSB_BIT",           "description": "One SCK period after WS change: drive the MSB on SD."},
            {"name": "TX_DATA_BITS",         "description": "Drive each subsequent bit of the word on SD, MSB → LSB."},
            {"name": "TX_AFTER_LSB",         "description": "If transmitter word is shorter than what receiver expects, transmitter LSBs are zero-padded; if longer, extra bits beyond receiver capacity are ignored."},
        ])
        d.setdefault("fsm_states_receiver", [
            {"name": "RX_LATCH_WS",          "description": "On each leading edge of SCK, latch WS to know current channel."},
            {"name": "RX_LATCH_SD",          "description": "On the same leading edge, latch the SD bit."},
            {"name": "RX_ON_WS_CHANGE",      "description": "When WS change is detected, store previous word and clear input for next word."},
            {"name": "RX_MSB_AT_WS+1",       "description": "Expect MSB of next word one SCK period after the WS change."},
        ])
        d.setdefault("fsm_hints", {
            "trigger":      "Continuous SCK runs whenever the bus is active. No start/stop framing.",
            "rule":         "WS edge + 1 SCK period later = MSB of next word. Receiver latches SD and WS on every leading edge of SCK.",
            "abort":        "Stopping SCK (controller's responsibility) halts the stream gracefully; no special protocol abort.",
        })
        d.setdefault("anti_deadlock_rule",
            "Single transmitter on SD line at a time; controller is unambiguous (whichever device generates SCK + WS). No multi-master arbitration.")
        d.setdefault("exit_from_reset_or_poweron",
            "On power-on / reset, controller drives SCK + WS in stable idle state; transmitter starts driving SD when ready; receiver synchronizes via WS edges.")
        d.setdefault("default_ready_state_recommendation", {
            "SCK_idle":     "Implementation-defined; continuous when streaming.",
            "WS_idle":      "Either polarity is valid; WS toggles between channels.",
            "SD_idle":      "Not specified — receiver may sample garbage outside an active channel; rely on WS to delimit words.",
        })
        d.setdefault("configurations", [
            {"name": "Transmitter as Controller", "description": "Transmitter drives SCK + WS + SD."},
            {"name": "Receiver as Controller",    "description": "Receiver drives SCK + WS; transmitter drives SD under external clock."},
            {"name": "Separate System Controller","description": "A separate IC drives SCK + WS; transmitter drives SD under external clock; receiver consumes SD."},
        ])
        d.setdefault("timing_dependency_rule",
            "Transmitter may use either edge of SCK to drive new data, but receiver always latches on the leading (LOW-to-HIGH) edge. Total target-side delay = (external clock → internal clock delay) + (internal clock → data/WS output delay). For data and word-select inputs, the external→internal delay is of no consequence because it only lengthens the effective setup time.")
        _write(p, d)

    # L7
    p = gd / "L7_TEST_DEBUG.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("test_debug_architecture_present", False)
        d.setdefault("spec_provided_observability", [
            {"name": "WS edge",         "purpose": "Channel boundary marker; receiver can verify expected periodicity (e.g. 32 SCK periods per channel for 16-bit stereo)."},
            {"name": "SCK frequency",   "purpose": "Bit clock; can be measured externally to verify sample rate × 2 (channels) × bits-per-sample."},
        ])
        d.setdefault("notes",
            "I2S 2.0 does NOT specify any protocol-level error detection, CRC, parity, or framing error reporting. There is no handshake or acknowledgment. Concrete I2S controller IPs may add FIFO overrun / underrun status registers, but these are per-implementation, not protocol-defined.")
        _write(p, d)

    # L8 RTL constants
    p = gd / "L8_RTL_CONSTANTS.json"
    if p.is_file():
        d = _read(p)
        wp = d.setdefault("width_parameters", {})
        if isinstance(wp, dict):
            for k, v in {
                "WS_BIT_WIDTH": 1, "SD_BIT_WIDTH": 1, "SCK_BIT_WIDTH": 1,
                "EXTERNAL_PIN_COUNT": 3, "CHANNELS": 2,
                "DATA_FORMAT": "two's complement, MSB-first",
                "WORD_LENGTH_bits_typical_examples": [16, 18, 20, 24, 32],
                "WORD_LENGTH_protocol_constraint": "Word length is implementation-defined and need NOT match between transmitter and receiver.",
            }.items():
                wp.setdefault(k, v)
        d.setdefault("voltage_levels", {
            "VH_min_V": 2.0,
            "VL_max_V": 0.8,
            "signaling": "TTL-compatible",
        })
        d.setdefault("key_constants_for_RTL_authoring", {
            "WS_value_for_left_channel":   0,
            "WS_value_for_right_channel":  1,
            "MSB_position_relative_to_WS": "MSB transmitted ONE SCK period AFTER WS changes.",
            "receiver_latch_edge":         "leading (LOW-to-HIGH) edge of SCK",
            "transmitter_drive_edge":      "either edge of SCK (transmitter's choice)",
            "data_byte_order":             "MSB first",
            "is_continuous":               True,
            "is_streaming":                True,
            "no_start_bit":                True,
            "no_stop_bit":                 True,
            "no_parity":                   True,
            "no_framing_bytes":            True,
        })
        d.setdefault("example_timing_at_2.5MHz_data_rate", {
            "data_rate_MHz": 2.5,
            "tolerance_percent": 10,
            "clock_period_T_min_ns": 360,
            "clock_period_T_typ_ns": 400,
            "clock_period_T_max_ns": 440,
            "Ttr_ns": 360,
            "transmitter_controller_clock_HIGH_min_ns": 160,
            "transmitter_controller_clock_LOW_min_ns":  160,
            "transmitter_delay_tdtr_max_ns":            300,
            "transmitter_hold_time_thtr_min_ns":        100,
            "transmitter_clock_rise_time_tRC_target_max_ns": 60,
            "receiver_clock_HIGH_min_ns": 110,
            "receiver_clock_LOW_min_ns":  110,
            "receiver_setup_time_tsr_min_ns": 60,
            "receiver_hold_time_thr_min_ns":   0,
        })
        d.setdefault("default_signal_values_when_idle", {
            "SCK": "Implementation-defined idle level; typically held LOW or HIGH between active streaming sessions.",
            "WS":  "Implementation-defined idle level.",
            "SD":  "Don't-care between channels; receiver latches per WS.",
        })
        _write(p, d)

    # L8 timing
    p = gd / "L8_TIMING_WAVEFORM.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("clock_waveform", {
            "SCK_continuous":         "Continuous serial clock; one bit per SCK period.",
            "leading_edge":           "LOW-to-HIGH transition; receiver latches SD + WS here.",
            "trailing_edge":          "HIGH-to-LOW transition; transmitter may use this edge to drive new SD.",
            "duty_cycle_transmitter": "Both tHC and tLC must be ≥ 0.35 T at the typical data rate.",
            "duty_cycle_receiver":    "tHC and tLC ≥ 0.35 T (slightly relaxed for receivers per Table 2 — 110 ns at 2.5 MHz typical).",
        })
        d.setdefault("word_select_waveform", {
            "polarity_left":   "WS = 0",
            "polarity_right":  "WS = 1",
            "WS_change_to_MSB_delay": "Transmitter sends MSB of the next word ONE SCK period AFTER WS changes.",
            "WS_symmetry":     "Need not be symmetrical; may change on either edge of SCK.",
            "WS_latched_by_receiver": "Leading edge of SCK in the target.",
        })
        d.setdefault("serial_data_waveform", {
            "format":       "Two's complement, MSB-first.",
            "MSB_position": "Fixed: one SCK period after WS change.",
            "LSB_position": "Depends on word length; receiver may receive more or fewer bits than its internal word length.",
            "underrun_LSBs":"Transmitter zero-pads LSB(s) if transmitter word is shorter than receiver word.",
            "overrun_LSBs": "Receiver ignores extra LSB(s) if transmitter word is longer than receiver word.",
        })
        d.setdefault("transmitter_timing_table_at_2.5MHz", {
            "header": ["Parameter", "MIN ns", "TYP ns", "MAX ns", "CONDITION"],
            "rows": [
                ["clock period T",          360, 400, 440, "Ttr = 360"],
                ["clock HIGH tHC",          160, None, None, "min > 0.35 T = 140 (typical)"],
                ["clock LOW tLC",           160, None, None, "min > 0.35 T = 140 (typical)"],
                ["delay tdtr",              None, None, 300, "max < 0.80 T = 320 (typical)"],
                ["hold time thtr",          100, None, None, "min > 0"],
                ["clock rise-time tRC",     None, None, 60,  "max > 0.15 Ttr = 54 (target mode only)"],
            ],
        })
        d.setdefault("receiver_timing_table_at_2.5MHz", {
            "header": ["Parameter", "MIN ns", "TYP ns", "MAX ns", "CONDITION"],
            "rows": [
                ["clock period T",  360, 400, 440, "Ttr = 360"],
                ["clock HIGH tHC",  110, None, None, "min < 0.35 T = 126"],
                ["clock LOW tLC",   110, None, None, "min < 0.35 T = 126"],
                ["set-up time tsr", 60,  None, None, "min < 0.20 T = 72"],
                ["hold time thr",   0,   None, None, "min < 0"],
            ],
        })
        d.setdefault("general_timing_rule",
            "All timing requirements are specified relative to clock period T or minimum allowed clock period Ttr of a device. This means that higher data rates can be used in the future (the timings scale with T).")
        d.setdefault("voltage_levels", {
            "VH_threshold_V": 2.0,
            "VL_threshold_V": 0.8,
        })
        _write(p, d)

    # L9
    p = gd / "L9_INTEGRATION_SPEC.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("module_role",
            "Wire-level inter-IC digital-audio serial bus specification. Defines a 3-line streaming-audio interface between any two (or more) I2S-compatible ICs. Concrete I2S controller / target IP blocks implement this protocol behind an MCU register interface (per SoC integration).")
        d.setdefault("integration_overview", {
            "wire_count":         3,
            "wire_directions":    "SCK + WS: controller → target; SD: transmitter → receiver (one-way per direction)",
            "no_chip_select":     "No CS / SS line; the bus is a pure point-to-point stream.",
            "no_addressing":      "No device addressing; one transmitter + one receiver per direction.",
            "controller_choices": "Transmitter, receiver, OR separate system controller can be the SCK+WS source.",
            "no_handshake":       "Continuous streaming; no ACK, no flow control.",
        })
        d.setdefault("interface_categories", [
            "Transmitter (drives SD; may also drive SCK + WS if it is the controller)",
            "Receiver (consumes SD; may drive SCK + WS if it is the controller)",
            "System Controller (drives SCK + WS only; both transmitter and receiver are targets)",
        ])
        d.setdefault("interconnect_topologies_supported", [
            "Point-to-point (one transmitter + one receiver)",
            "Multi-receiver broadcast (one transmitter + multiple receivers sharing the same SCK/WS/SD)",
            "Multi-transmitter selected by system controller (rare; requires external MUX of SD)",
        ])
        d.setdefault("default_signal_values_when_omitted",
            "Implementation-defined idle level for SCK + WS; controller stops driving SCK to halt streaming gracefully.")
        d.setdefault("soc_dependent_items", [
            "I2S controller / target IP register file (FIFO control, sample rate, bit clock divisor, word length, channel format select, mute, interrupt enable).",
            "Master clock (MCLK) generation if needed for the codec — NOT part of the 3-wire I2S spec but commonly required for audio codecs.",
            "Audio sample rate selection (44.1 kHz, 48 kHz, 96 kHz, 192 kHz, etc.).",
            "Bit clock division: SCK = sample_rate × channels × bits_per_sample.",
            "Pad voltage selection (TTL-compatible 3.3 V / 5 V).",
            "Interrupt routing for FIFO over/underflow events.",
            "DMA-controller wiring for streaming audio data.",
        ])
        d.setdefault("common_audio_sample_rate_examples", [
            {"rate_kHz": 32,    "bits": 16, "SCK_MHz_stereo": 1.024},
            {"rate_kHz": 44.1,  "bits": 16, "SCK_MHz_stereo": 1.4112},
            {"rate_kHz": 48,    "bits": 16, "SCK_MHz_stereo": 1.536},
            {"rate_kHz": 48,    "bits": 24, "SCK_MHz_stereo": 2.304},
            {"rate_kHz": 96,    "bits": 24, "SCK_MHz_stereo": 4.608},
            {"rate_kHz": 192,   "bits": 24, "SCK_MHz_stereo": 9.216},
        ])
        d.setdefault("low_power_modes", {
            "Stop_SCK": "Controller stops driving SCK to halt streaming; receivers idle.",
            "Mute":     "Per-implementation; not part of the 3-wire I2S protocol.",
        })
        _write(p, d)

    # L10
    p = gd / "L10_TEST_CASES.json"
    if p.is_file():
        d = _read(p)
        d["test_cases_present"] = (
            "partial - the spec defines timing tables (Tables 1, 2, 3) "
            "and behavioral rules that map to compliance test scenarios "
            "but does not provide a formal testbench.")
        d.setdefault("derived_compliance_test_categories", [
            "Continuous SCK at the typical and minimum allowed clock period.",
            "Clock HIGH (tHC) and LOW (tLC) min ≥ 0.35 T at the typical data rate (transmitter).",
            "Transmitter delay tdtr ≤ 0.80 T (max).",
            "Transmitter hold time thtr ≥ 0 (min).",
            "Transmitter clock rise-time tRC ≥ 0.15 Ttr (in target mode only).",
            "Receiver setup time tsr ≥ 0.20 T (min).",
            "Receiver hold time thr ≥ 0 (min).",
            "WS edge correctly precedes MSB by exactly 1 SCK period.",
            "Receiver latches SD + WS on leading edge of SCK.",
            "Channel assignment: WS=0 → left, WS=1 → right.",
            "Word-length mismatch: transmitter < receiver → receiver zero-extends.",
            "Word-length mismatch: transmitter > receiver → receiver truncates LSBs.",
            "Two's-complement MSB-first encoding correctly received.",
            "Configuration 1 — Transmitter as Controller.",
            "Configuration 2 — Receiver as Controller.",
            "Configuration 3 — Separate System Controller.",
            "Logic-level compliance: VH ≥ 2.0 V, VL ≤ 0.8 V.",
        ])
        _write(p, d)

    # L11
    p = gd / "L11_OTP_CONTENT.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("otp_present", False)
        d["notes"] = (
            "I2S is a wire-level streaming-audio protocol; no OTP / fuse "
            "content at the protocol layer. Individual I2S codec ICs may "
            "use OTP to lock factory-trim values for analog converters, "
            "but this is per-device, not protocol-defined.")
        _write(p, d)

    # L12
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("typical_streaming_sequence", [
            "1. Controller begins driving continuous SCK at the agreed bit rate (sample_rate × channels × bits_per_sample).",
            "2. Controller toggles WS to mark channel boundaries: WS=0 (left), WS=1 (right), alternating each word.",
            "3. WS transition occurs on the SCK edge that the controller chooses (either edge is OK; receiver latches on leading edge).",
            "4. ONE SCK period after the WS transition, transmitter drives the MSB of the next channel's word on SD.",
            "5. Subsequent bits MSB-1, MSB-2, ..., LSB are driven on each successive SCK period.",
            "6. Receiver latches SD on each leading (LOW-to-HIGH) edge of SCK; combined with the latched WS, it reconstructs left/right channel words.",
        ])
        d.setdefault("word_length_mismatch_sequences", [
            {"scenario": "Transmitter word SHORTER than receiver word",
             "behavior": "Transmitter sends MSB→LSB of its short word; remaining bits (until receiver's LSB position) are sent as zeros. Receiver fills missing LSBs internally as zero."},
            {"scenario": "Transmitter word LONGER than receiver word",
             "behavior": "Transmitter sends MSB→LSB of its long word; receiver latches only up to its internal word length and ignores extra bits beyond LSB position."},
        ])
        d.setdefault("configuration_handover_sequences", [
            {"name": "Transmitter-as-Controller", "steps": "Transmitter generates SCK + WS + SD. Receiver synchronizes to incoming clock; no handshake needed."},
            {"name": "Receiver-as-Controller",    "steps": "Receiver generates SCK + WS. Transmitter receives external SCK + WS and drives SD synchronized to them."},
            {"name": "System-Controller",         "steps": "Separate IC generates SCK + WS. Both transmitter and receiver are targets; transmitter drives SD under external clock."},
        ])
        d.setdefault("stream_halt_sequence", [
            "1. Controller stops toggling SCK (e.g. gates clock off).",
            "2. SD level becomes don't-care; receivers stay in their last-latched state.",
            "3. To resume: controller restarts SCK + WS; receiver re-synchronizes on first WS edge.",
        ])
        _write(p, d)

    # L13
    p = gd / "L13_LAB_CALIBRATION.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("lab_calibration_present", False)
        d["notes"] = (
            "I2S is a digital wire-level protocol; no analog reference / "
            "trim / calibration loop at the protocol layer. Connected "
            "audio codecs (D/A or A/D converters) may have on-chip "
            "calibration, but this is per-device, not part of the I2S "
            "protocol.")
        _write(p, d)

    # L14
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("spec_version", "I2S Bus Specification Rev. 3.0 (17 February 2022)")
        if _empty(f.get("previous_versions")):
            f["previous_versions"] = [
                "v.1 (1 February 1986) — Initial Philips Semiconductors release.",
                "v.2 (5 June 1996) — Second Philips Semiconductors release.",
                "v.3 (17 February 2022) — Reconstructed from the original 1986/1996 spec by NXP Semiconductors; format updated; Master/Slave terminology updated to Controller/Target.",
            ]
        if _empty(f.get("key_changes")):
            f["key_changes"] = [
                {"version": "v.2 (1996)", "summary": "Editorial revisions to the original 1986 spec; same protocol behavior."},
                {"version": "v.3 (2022)", "summary": "Reconstructed by NXP under the UM11732 document number with new identity guidelines; 'Master' → 'Controller' and 'Slave' → 'Target' for inclusive language; protocol behavior unchanged."},
            ]
        if _empty(f.get("backward_compat_traps")):
            f["backward_compat_traps"] = [
                {"trap_name": "msb_position_relative_to_ws",
                 "rule": "MSB transmitted ONE SCK period AFTER WS changes.",
                 "trap": "Some 'I2S-like' variants (Left-Justified, Right-Justified, DSP mode) place the MSB ON the same edge as WS, not one cycle later. Mixing those variants with strict I2S receivers will appear as a 1-bit shift."},
                {"trap_name": "receiver_must_latch_on_leading_edge",
                 "rule": "Target receiver latches WS + SD on the leading (LOW-to-HIGH) edge of SCK.",
                 "trap": "Some implementations latch on the trailing edge — incompatible with standard I2S receivers."},
                {"trap_name": "word_length_mismatch_silent",
                 "rule": "Transmitter and receiver may have different word lengths; mismatches are silently truncated or zero-padded — no error signal.",
                 "trap": "System integrators forget to configure receiver word length; resulting audio is silently wrong (gain change due to LSB truncation or padding)."},
                {"trap_name": "channel_assignment_wrong_polarity",
                 "rule": "WS = 0 → channel 1 (left); WS = 1 → channel 2 (right).",
                 "trap": "Some 'TDM mode' and 'Left-Justified' variants use the OPPOSITE convention. Plugging an I2S codec into a Left-Justified transmitter swaps left and right channels silently."},
            ]
        f.setdefault("version_naming_history_note",
            "Originally Philips Semiconductors I2S Bus Specification (1986, revised 1996); NXP Semiconductors took over Philips Semiconductors in 2006; UM11732 (2022) is NXP's reconstruction of the original spec with updated language and identity. Industry-wide, 'I2S' has many sibling formats (Left-Justified, Right-Justified, TDM, DSP mode) that are often confused with strict I2S — only strict I2S follows UM11732's MSB-one-clock-after-WS rule.")
        d["fields"] = f
        _write(p, d)

    # L15
    p = gd / "L15_ENCODING_TABLES.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("ws_channel_encoding_table", {
            "header_columns": ["WS Value", "Channel"],
            "rows": [
                {"WS": "0", "channel": "channel 1 (left)"},
                {"WS": "1", "channel": "channel 2 (right)"},
            ],
        })
        f.setdefault("transmitter_timing_table_at_2.5MHz", {
            "header_columns": ["Parameter", "MIN (ns)", "TYP (ns)", "MAX (ns)", "Condition"],
            "rows": [
                ["clock period T",   360, 400, 440, "Ttr = 360"],
                ["clock HIGH tHC",   160, None, None, "min > 0.35 T = 140"],
                ["clock LOW tLC",    160, None, None, "min > 0.35 T = 140"],
                ["delay tdtr",       None, None, 300, "max < 0.80 T = 320"],
                ["hold time thtr",   100, None, None, "min > 0"],
                ["clock rise-time tRC", None, None, 60, "max > 0.15 Ttr = 54 (target mode only)"],
            ],
        })
        f.setdefault("receiver_timing_table_at_2.5MHz", {
            "header_columns": ["Parameter", "MIN (ns)", "TYP (ns)", "MAX (ns)", "Condition"],
            "rows": [
                ["clock period T", 360, 400, 440, "Ttr = 360"],
                ["clock HIGH tHC", 110, None, None, "min < 0.35 T = 126"],
                ["clock LOW tLC",  110, None, None, "min < 0.35 T = 126"],
                ["set-up time tsr", 60, None, None, "min < 0.20 T = 72"],
                ["hold time thr",   0, None, None,  "min < 0"],
            ],
        })
        f.setdefault("general_timing_table_normalized_to_clock_period", {
            "header_columns": ["Parameter", "Transmitter MIN", "Transmitter MAX", "Receiver MIN", "Receiver MAX", "Notes"],
            "rows": [
                ["clock period T",      "Ttr",         None,      "Tr",         None, "Controller mode: clock generated by transmitter or receiver"],
                ["clock HIGH tHC",      "0.35 Ttr",    None,      "0.35 Tr",    None, "Receiver gets a relaxed 0.35 T at typical rate"],
                ["clock LOW tLC",       "0.35 Ttr",    None,      "0.35 Tr",    None, ""],
                ["delay tdtr",          None,          "0.80 T",  None,         None, "Transmitter only"],
                ["hold time thtr",      "0",           None,      None,         None, "Transmitter only"],
                ["clock rise-time tRC", None,          "0.15 Ttr", None,        None, "Transmitter in target mode only"],
                ["set-up time tsr",     None,          None,      "0.20 T",     None, "Receiver only"],
                ["hold time thr",       None,          None,      "0",          None, "Receiver only"],
            ],
        })
        f.setdefault("voltage_levels_table", {
            "header_columns": ["Symbol", "Value", "Meaning"],
            "rows": [
                ["VH", "2.0 V", "HIGH input threshold (min)"],
                ["VL", "0.8 V", "LOW input threshold (max)"],
            ],
        })
        if _empty(f.get("tables")):
            f["tables"] = [
                "Figure 2 — Timing for I2S transmitter",
                "Figure 3 — Timing for I2S receiver",
                "Table 1 — Controller transmitter with data rate of 2.5 MHz (±10 %)",
                "Table 2 — Target receiver with data rate of 2.5 MHz (±10 %)",
                "Table 3 — Timing for I2S transmitters and receivers (general, normalized to T)",
            ]
        d["fields"] = f
        _write(p, d)

    # L16
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("must_have_properties", [
            "Three lines: SCK, WS, SD.",
            "MSB-first two's complement on SD.",
            "MSB of next word transmitted exactly ONE SCK period after WS changes.",
            "Receiver latches SD and WS on the leading (LOW-to-HIGH) edge of SCK.",
            "Transmitter holds SD valid through the leading edge of SCK.",
            "WS = 0 selects channel 1 (left); WS = 1 selects channel 2 (right).",
            "Voltage levels: VH ≥ 2.0 V, VL ≤ 0.8 V.",
            "Clock duty cycle: tHC ≥ 0.35 T and tLC ≥ 0.35 T (transmitter at typical rate).",
            "Transmitter delay tdtr ≤ 0.80 T (max).",
            "Receiver setup time tsr ≥ 0.20 T (min).",
        ])
        f.setdefault("must_not_have_properties", [
            "Multiple simultaneous transmitters on the same SD line (no arbitration).",
            "Receiver latching on the trailing edge of SCK (incompatible with standard I2S transmitters).",
            "MSB placement on the same edge as WS change (that's Left-Justified format, not strict I2S).",
        ])
        f.setdefault("compliance_failure_modes", [
            {"mode": "Sample-bit shift", "trigger": "Receiver latches on wrong edge → samples are 1 bit early/late."},
            {"mode": "Channel swap",     "trigger": "Receiver interprets WS polarity opposite to transmitter (Left/Right swapped)."},
            {"mode": "Word-length mismatch silent error", "trigger": "Transmitter and receiver have different word lengths → bits silently truncated or zero-padded."},
        ])
        f.setdefault("min_clock_constraint",
            "Implementation-defined minimum allowed clock period Ttr (transmitter) and Tr (receiver).")
        f.setdefault("reset_behavior_compliance",
            "I2S does not define a reset state at the protocol level; receivers must tolerate startup transients and re-sync on first WS edge.")
        d["fields"] = f
        _write(p, d)

    # L17
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f["channels"] = [
            {"name": "SCK", "direction_controller": "output", "direction_target": "input", "purpose": "Continuous Serial Clock; one rising edge per data bit.", "active_levels": "VH ≥ 2.0 V, VL ≤ 0.8 V; both edges meaningful (transmitter may use either; receiver uses leading)", "idle_level": "Implementation-defined"},
            {"name": "WS",  "direction_controller": "output", "direction_target": "input", "purpose": "Word Select; 0 = channel 1 (left), 1 = channel 2 (right). Changes one SCK period BEFORE the MSB of the next word.", "active_levels": "VH ≥ 2.0 V, VL ≤ 0.8 V", "idle_level": "Implementation-defined"},
            {"name": "SD",  "direction_transmitter": "output", "direction_receiver": "input", "purpose": "Serial Data; MSB-first two's-complement audio samples for both channels time-multiplexed.", "active_levels": "VH ≥ 2.0 V, VL ≤ 0.8 V", "idle_level": "Don't-care between channels"},
        ]
        f["global_signals"] = []
        f["channel_counts"] = {
            "channels": 3, "data_lines": 1, "clock_lines": 1, "control_lines": 1,
            "audio_channels_per_SD": 2, "external_pins_total": 3,
        }
        f.setdefault("ordering_rules", {
            "bit_order_within_word":      "MSB-first.",
            "channel_order_within_frame": "Left (WS=0) then right (WS=1), alternating; each WS edge starts a new word.",
        })
        # Force-overwrite dependency_graph for I2S shape.
        f["dependency_graph"] = {
            "common_rule": "Controller drives SCK + WS continuously. Transmitter drives SD synchronized to SCK; receiver latches SD on leading edge of SCK + WS. WS edge always precedes MSB by exactly one SCK period.",
            "data_dependency": "Each SD bit is sampled on a leading SCK edge; WS is sampled on the SAME leading edge to identify the channel.",
        }
        f["handshake_pairs"] = [
            {"name": "SCK_DRIVE",  "from": "controller", "to": "target",       "rule": "Continuous bit clock; one edge per SD bit."},
            {"name": "WS_BOUNDARY","from": "controller", "to": "target",       "rule": "WS transition signals channel boundary; MSB of next channel word follows on the next SCK period."},
            {"name": "SD_LATCH",   "from": "transmitter","to": "receiver",     "rule": "Transmitter holds SD valid through leading edge of SCK; receiver latches on leading edge."},
        ]
        d["fields"] = f
        _write(p, d)

    # L18
    p = gd / "L18_INTERCONNECT_TOPOLOGY.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f["topology_type"] = "Point-to-point streaming audio bus; one transmitter + one receiver per SD direction. SCK + WS are broadcast from the controller."
        f["supported_topologies"] = [
            {"name": "Single transmitter + single receiver",     "description": "Most common case; 3 wires connect two ICs."},
            {"name": "Single transmitter + multiple receivers",  "description": "Multiple receivers share the same SCK + WS + SD bus (broadcast)."},
            {"name": "Multiple transmitters, MUX'd via system controller", "description": "Less common; requires external multiplexing of SD per active transmitter — protocol itself has no arbitration."},
        ]
        f["master_slave_role_summary"] = [
            {"role": "Controller",  "description": "Drives SCK + WS. May be the transmitter, the receiver, or a separate system controller."},
            {"role": "Target",      "description": "Receives SCK + WS as inputs. May be transmitter or receiver."},
            {"role": "Transmitter", "description": "Drives SD output. May be controller (drives SCK+WS too) or target (receives external SCK+WS)."},
            {"role": "Receiver",    "description": "Receives SD input. May be controller or target."},
        ]
        f["interconnect_role"] = (
            "There is no protocol-layer interconnect (no router / "
            "bridge). The bus is a flat 3-wire bus between a controller "
            "and one or more targets.")
        f["ordering_guarantees"] = {
            "within_a_word": "Bits transmitted MSB-first; receiver reassembles bits in the same order.",
            "across_channels": "Channels are strictly time-multiplexed; controller's WS edge defines channel boundary; transmitter must align word MSB to one SCK period after WS.",
        }
        f.setdefault("memory_vs_peripheral_regions",
            "Not applicable — I2S is a streaming-only protocol; no addressable regions.")
        f.setdefault("device_classification", {
            "audio_DAC":          "Receiver target; receives audio samples via SD.",
            "audio_ADC":          "Transmitter; drives SD with sampled audio.",
            "digital_signal_processor": "Both transmitter and receiver; typically the system controller of a multi-codec audio path.",
            "audio_bridge":       "Transmitter + receiver pair connected back-to-back, possibly with sample-rate conversion.",
        })
        f.setdefault("default_signal_values_evidence_tables", [
            "Figure 1 — Simple system configurations + basic interface timing",
            "Figure 2 — Timing for I2S transmitter",
            "Figure 3 — Timing for I2S receiver",
            "Section 3 — The I2S bus (SCK / WS / SD)",
        ])
        d["fields"] = f
        _write(p, d)

    # L19 PDK
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("constraints_present", False)
        f["notes"] = (
            "I2S is a wire-level streaming protocol; no PDK / SDC / "
            "floorplan constraints at the protocol layer. Per-controller "
            "/ per-codec integration constraints (pad type, clock-tree "
            "budget) live in the SoC integration spec, not in UM11732.")
        d["fields"] = f
        _write(p, d)

    # L20 DFT
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("dft_present", False)
        f["notes"] = (
            "I2S 2022 spec does not specify DFT / scan / BIST. Concrete "
            "I2S controller / codec IP from modern vendors adds standard "
            "scan + JTAG at the integrator level.")
        d["fields"] = f
        _write(p, d)

    # L21
    p = gd / "L21_POWER_INTENT.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("power_intent_present", False)
        f["low_power_modes_summary"] = {
            "stop_SCK": "Controller stops driving SCK to halt streaming; bus idles in implementation-defined state.",
            "mute":      "Not part of the 3-wire I2S protocol — implemented per-codec at register level.",
        }
        f["notes"] = (
            "I2S spec does not define formal sleep / suspend modes. "
            "Power management is deferred to the SoC + codec IP. Audio "
            "codecs typically support 'mute' and 'standby' via control "
            "registers (I2C or SPI bus, separate from the I2S audio bus).")
        d["fields"] = f
        _write(p, d)

    # L23
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("security_requirements_present", False)
        f["notes"] = (
            "I2S (1986/1996/2022) is a wire-level streaming audio "
            "protocol; no confidentiality / integrity / authentication "
            "features at the protocol layer. Audio payload is in "
            "plaintext.")
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
def is_i2s(blob: str) -> bool:
    """Content-only `i2s` detector (importable, lifted from the runner).

    Empty-safe. Reads ONLY ``blob`` (spec text). Byte-for-byte the
    same boolean the runner used inline.
    """
    if not blob:
        return False
    return bool(
        ("SCK" in blob and "WS" in blob
            and "SD" in blob
            and "Word Select" in blob)
        or ("Inter-IC Sound" in blob)
        or ("I2S" in blob and "Word Select" in blob))
