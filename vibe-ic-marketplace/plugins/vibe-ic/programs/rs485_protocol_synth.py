"""RS-485-class protocol synth helper.

v0.1.84 — ic_class-gated overlay for `serial_peripheral_protocol` /
`serial_phy_protocol` specs that exhibit the RS-485 (TIA/EIA-485) structural
signature. Applies Texas Instruments SLLA272D-canonical content to L1-L23.

Detection signature (structural; general within the ic_class):
- (RS-485 + differential + A/B + multi-drop)
- OR (TIA + 485 + transceiver)
- OR (RS-485 + termination + fail-safe + bias)

Doctrine: structural-keyword detection IS general within an ic_class
(mirrors AMBA-AXI / SPI / I2C / UART / CAN / USB / I2S / Modbus synth
approach). Any RS-485-family variant (TIA/EIA-485-A R1998 / R2003 / R2012,
SLLA272 / SLLA272A / B / C / D, derivative profiles such as DL/T645's
physical layer reference, Profibus DP PHY, BACnet MS/TP PHY) exhibits
the same signature — differential A/B pair, multi-drop trunk topology,
±200 mV receiver threshold, -7 V to +12 V common-mode, 32-UL standard
loading, 120 ohm termination at each cable end, failsafe biasing under
LOS, half- vs full-duplex topology, optional galvanic isolation for
robust GPD tolerance.

Public entry: `apply_rs485_synth(generated_docs_dir, is_rs485, rs485_ic_name)`.
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


def _force(d: dict, key: str, value) -> None:
    """v0.1.88 — force-overwrite key with RS-485 value.

    RS-485 docs frequently co-mention UART (the typical host-side framing),
    causing the upstream UART structural sub-detector to fire and pre-fill
    L4/L5/L9/L10/L11/L13/L17/L19/L20/L22/L23 with UART-class content
    BEFORE the RS-485 sub-detector runs. `setdefault` is a no-op when the
    UART pre-fill is already present, so the RS-485 content never lands
    and the parity diff fires VALUE_MISMATCH / HALLUCINATED.

    `_force` is the explicit overwrite used on keys the RS-485 spec
    defines authoritatively. Doctrine: RS-485 has higher specificity than
    UART for this ic_name → RS-485 wins on every contested key."""
    d[key] = value


def _force_nested(d: dict, parent_key: str, child_key: str, value) -> None:
    """v0.1.88 — force a single nested key under a parent dict, preserving
    other siblings the upstream synth may have set. Used for L17
    `dependency_graph.common_rule` style targeted overwrites."""
    sub = d.get(parent_key)
    if not isinstance(sub, dict):
        sub = {}
        d[parent_key] = sub
    sub[child_key] = value


def apply_rs485_synth(generated_docs_dir: Path, is_rs485: bool,
                      rs485_ic_name: Optional[str]) -> None:
    """Apply RS-485-specific synth when the structural signature matched."""
    if not is_rs485:
        return
    gd = generated_docs_dir

    # Force ic_name across the 14 main L docs that carry top-level ic_name
    # (L14..L23 wrap content under "fields" per the protocol-spec template
    # convention and intentionally do NOT carry a top-level ic_name).
    if rs485_ic_name is not None:
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
                d["ic_name"] = rs485_ic_name
                _write(q, d)

    # ---------------- L1 datasheet metadata ----------------
    p = gd / "L1_DATASHEET.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("document_title", "The RS-485 Design Guide")
        d.setdefault("document_number", "SLLA272D")
        d.setdefault("manufacturer", "Texas Instruments Incorporated")
        d.setdefault("author", "Thomas Kugelstadt")
        d.setdefault("department", "HPL - Interface")
        d.setdefault("first_published", "February 2008")
        d.setdefault("revised_date", "May 2021")
        d.setdefault("copyright", "© 2021 Texas Instruments Incorporated")
        d.setdefault("abstract",
            "As a short compendium for successful data transmission design, this application report "
            "discusses the important aspects of the RS-485 standard.")
        d.setdefault("standard_name",
            "RS-485 (originally TIA/EIA-485, approved 1983 by Electronics Industries Association)")
        d.setdefault("standard_origin_year", 1983)
        d.setdefault("standard_owner",
            "Electronics Industries Association (EIA) / Telecommunications Industry Association (TIA)")
        d.setdefault("standard_scope",
            "RS-485 is an electrical-only standard. In contrast to complete interface standards which "
            "define functional, mechanical and electrical specifications, RS-485 ONLY defines the "
            "electrical characteristics of drivers and receivers used to implement a balanced "
            "multipoint transmission line.")
        if _empty(d.get("key_features")):
            d["key_features"] = [
                "Balanced (differential) interface.",
                "Multipoint operation from a single 5-V supply.",
                "-7-V to +12-V bus common-mode range.",
                "Up to 32 unit loads (standard-compliant drivers); up to 256 transceivers with 1/8-UL devices.",
                "10 Mbps maximum data rate (at 40 feet) — standard recommendation; modern interfaces can run up to 40 Mbps at short distances.",
                "4000-foot (~1200 m) maximum cable length at 100 kbps.",
                "Receiver differential input threshold ±200 mV minimum.",
                "Driver differential output minimum 1.5 V into 54-ohm load.",
                "Supports half-duplex 2-wire and full-duplex 4-wire topologies.",
                "Bus topology = daisy-chain / party-line / linear bus with short stubs at each node.",
                "Bus termination 120 ohm at each cable end matching characteristic impedance.",
                "Failsafe biasing (external resistive divider) for open-circuit / short-circuit / idle-bus conditions.",
                "Differential signaling rejects common-mode noise; suitable for long-distance industrial / medical / consumer applications.",
            ]
        if _empty(d.get("domain_of_application")):
            d["domain_of_application"] = [
                "Industrial automation (factory bus, distributed control).",
                "Medical equipment (instrumentation, patient monitoring).",
                "Consumer applications (multi-node serial daisy chains).",
                "Building automation / HVAC.",
                "Higher-level protocols built ON TOP of RS-485 PHY: DL/T645 (Chinese electronic energy meters), Modbus RTU, Profibus DP, BACnet MS/TP, DMX-512, SCSI-1 (differential), DeviceNet-style fieldbuses.",
            ]
        if _empty(d.get("modes_of_operation")):
            d["modes_of_operation"] = [
                {"name": "half-duplex (2-wire)", "description": "Single twisted-pair bus shared by all drivers and receivers; only one driver active at a time; direction control via DE / RE# signals; software-controlled time-multiplexing."},
                {"name": "full-duplex (4-wire)", "description": "Two twisted-pairs: one master-to-slaves and one slaves-to-master; transmitter and receiver operate simultaneously on separate pairs."},
                {"name": "idle / loss-of-signal (LOS)", "description": "No driver active on the bus; receiver must enter a determined output state via fail-safe biasing (internal or external)."},
            ]
        d.setdefault("physical_layer_role",
            "RS-485 is purely a physical-layer (OSI layer 1) electrical standard. It defines driver / "
            "receiver electricals (differential output level, input threshold, common-mode range, "
            "unit-load definition) and the daisy-chain bus topology. It does NOT define data framing, "
            "addressing, CRC or any link-layer protocol — those are layered on top by higher-level "
            "standards.")
        d.setdefault("ti_transceiver_product_examples", [
            "SN65HVD12 — 1 Mbps signal rate, ~100 ns rise time, ~7 ft max stub.",
            "SN65LBC184 — 250 kbps signal rate, ~250 ns rise time, ~19 ft max stub.",
            "SN65HVD3082E — 200 kbps signal rate, ~500 ns rise time, ~38 ft max stub.",
            "Family features: 1/8-UL low loading, high ESD protection (16 kV to 30 kV), integrated open/short/idle-bus fail-safe, isolated DC/DC + digital isolator versions for galvanic isolation across ground-potential differences.",
        ])
        _write(p, d)

    # ---------------- L2 functional requirements ----------------
    p = gd / "L2_FRS.json"
    if p.is_file():
        d = _read(p)
        po = d.setdefault("protocol_overview", {})
        if isinstance(po, dict):
            po.setdefault("type", "Balanced differential multipoint serial transmission line (electrical-only standard).")
            po.setdefault("duplex", "Half-duplex on a 2-wire (1 differential-pair) bus; full-duplex on a 4-wire (2 differential-pairs) bus.")
            po.setdefault("synchronous", False)
            po.setdefault("physical_signaling",
                "Differential pair — non-inverting line A and inverting line B; differential voltage "
                "Vab = Va - Vb encodes the bit. |Vab| > +200 mV at receiver = mark; Vab < -200 mV = space.")
            po.setdefault("bus_topology",
                "Daisy-chain / party-line / linear bus. Drivers, receivers and transceivers connect "
                "to a single main cable trunk via short network stubs.")
            po.setdefault("addressing",
                "RS-485 itself has no addressing; higher-level protocols (Modbus RTU, DL/T645, BACnet "
                "MS/TP, …) carry addresses on top of the byte stream.")
            po.setdefault("multimaster", True)
            po.setdefault("multidrop", True)
            po.setdefault("bus_value_idle_recommendation",
                "Determined by external or internal fail-safe biasing — typically pulls A high and B "
                "low so |Vab| > 200 mV in the marking direction when no driver is active.")
        fr = [
            {"id": "FR-DIFF-01",  "text": "All signaling between bus nodes is differential between non-inverting line A and inverting line B."},
            {"id": "FR-DRV-02",   "text": "RS-485-compliant driver produces a minimum 1.5 V differential output across a 54-ohm test load (= two 120-ohm terminations in parallel + 32 unit loads)."},
            {"id": "FR-RX-03",    "text": "RS-485-compliant receiver detects a differential input as low as ±200 mV across the full common-mode range."},
            {"id": "FR-CMR-04",   "text": "Bus common-mode voltage range is -7 V to +12 V referenced to receiver ground; receiver must operate over this entire range."},
            {"id": "FR-UL-05",    "text": "Standard-compliant driver must be able to drive 32 unit loads (UL); a unit load = ~12 kohm impedance per Section 8 of SLLA272D."},
            {"id": "FR-1UL-06",   "text": "1/8-UL transceivers allow up to 32 / (1/8) = 256 nodes; failsafe biasing consumes up to 20 UL, reducing the practical maximum to (32 - 20) / 0.125 = 96 with 1/8-UL parts."},
            {"id": "FR-TERM-07",  "text": "Cable trunk must be terminated at each end with a resistor matching the characteristic impedance (typically 120 ohm for industrial UTP cable)."},
            {"id": "FR-STUB-08",  "text": "Maximum stub length L_stub ≤ (tr / 10) × v × c where tr = driver 10/90 rise time, v = cable signal velocity factor, c = speed of light. Drivers with longer rise times tolerate longer stubs."},
            {"id": "FR-DIST-09",  "text": "Maximum cable length is limited by transmission-line losses and signal jitter; data reliability sharply decreases beyond ~10 % jitter of the baud period. 4000 ft (1200 m) at 100 kbps is the documented standard upper bound. Conservative rule of thumb: line_length [m] × data_rate [bps] < 10^7."},
            {"id": "FR-FAIL-10",  "text": "Fail-safe operation = receiver assumes a determined output state during loss-of-signal (open-circuit, short-circuit, or idle-bus). Modern transceivers integrate internal biasing; external resistive divider provides higher noise margin in noisy environments."},
            {"id": "FR-DE-11",    "text": "Half-duplex direction control: each transceiver has a DE (driver enable, active HIGH) and RE# (receiver enable, active LOW) input. Only one driver may be enabled at any time; software is responsible for ensuring this."},
            {"id": "FR-4W-12",    "text": "Full-duplex (4-wire) topology uses two differential pairs — one for master-to-slaves transmission, one for slaves-to-master — allowing simultaneous TX and RX without DE/RE# arbitration."},
            {"id": "FR-DR-13",    "text": "Maximum data rate documented in the standard is 10 Mbps at 40 ft; modern transceivers reach 40 Mbps at short stubs."},
            {"id": "FR-GND-14",   "text": "Robust links over long distances or large ground-potential differences (GPD) require galvanic isolation of signal AND supply via digital isolators + isolated DC/DC converter at the transceiver."},
            {"id": "FR-CAP-15",   "text": "Minimum node spacing on the bus d > C_L / (5.25 × C') where C_L = lumped load capacitance per node and C' = media capacitance per unit length; chosen to keep loaded bus impedance Z' > 0.4 × Z0."},
        ]
        if _empty(d.get("functional_requirements")):
            d["functional_requirements"] = fr
        d.setdefault("error_response_conditions", [
            "Loss of signal (open-circuit) — bus disconnected; failsafe biasing must drive receiver output to a determined state.",
            "Loss of signal (short-circuit) — insulation fault shorts A to B or to another wire; failsafe biasing or driver short-circuit current limit handles this.",
            "Loss of signal (idle-bus) — all drivers disabled; receiver sees ~0 V Vab; failsafe biasing required.",
            "Bus contention — two drivers enabled simultaneously in half-duplex; must be prevented by software direction control.",
            "Stub-reflection / impedance-mismatch signal-integrity errors — stubs longer than tr × v × c / 10 cause reflections that distort the eye.",
            "Common-mode noise — large ground-potential differences exceed the -7 V to +12 V receiver common-mode range, causing data errors. Mitigation: galvanic isolation.",
        ])
        if _empty(d.get("compliance_requirements")):
            d["compliance_requirements"] = [
                "Driver minimum differential output ≥ 1.5 V into 54 ohm load.",
                "Receiver minimum differential input sensitivity ±200 mV.",
                "Receiver common-mode range -7 V to +12 V.",
                "Supports at least 32 unit loads (or scaled equivalent with 1/8-UL parts).",
                "Cable characteristic impedance ≥ 100 ohm; industrial UTP typically 120 ohm.",
                "Termination resistor at each cable end matching cable Z0.",
                "Stub length ≤ tr × v × c / 10 to preserve signal integrity.",
                "Higher-level standards built ON TOP of RS-485 (Modbus RTU, DL/T645, …) provide framing / CRC / addressing — RS-485 itself does not.",
            ]
        d.setdefault("external_signal_wire_count",
            "2 (lines A, B) in half-duplex; 4 (TX-A, TX-B, RX-A, RX-B) in full-duplex. Plus driver-side "
            "DE / RE# direction-control digital pins per transceiver.")
        _write(p, d)

    # ---------------- L3 command / channel mapping ----------------
    p = gd / "L3_CMD_PROTOCOL.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("protocol_type",
            "Electrical-only physical-layer standard. RS-485 has NO command set, NO frame format, NO "
            "addressing — it defines only the driver/receiver electricals and bus topology. Framing / "
            "addressing / CRC are layered on top by higher-level protocols (Modbus RTU, DL/T645, BACnet "
            "MS/TP, etc.).")
        d.setdefault("opcodes", [])
        d.setdefault("channels_2_wire_half_duplex", [
            {"name": "A",   "direction": "bidirectional (open-drain / tri-state)", "description": "Non-inverting differential bus line. When the active driver transmits a logical '1' (mark), A is the more positive of the pair."},
            {"name": "B",   "direction": "bidirectional (open-drain / tri-state)", "description": "Inverting differential bus line. When the active driver transmits a logical '1' (mark), B is the more negative of the pair."},
            {"name": "GND-ref", "direction": "shared",                              "description": "Common ground reference between nodes; in long links with ground-potential differences, isolation is required."},
        ])
        d.setdefault("channels_4_wire_full_duplex", [
            {"name": "Y", "direction": "master-to-slaves TX +", "description": "Non-inverting transmit pair line out of the master driver."},
            {"name": "Z", "direction": "master-to-slaves TX -", "description": "Inverting transmit pair line out of the master driver."},
            {"name": "A", "direction": "slaves-to-master RX +", "description": "Non-inverting receive pair line into the master receiver (and into each slave transmitter for upstream)."},
            {"name": "B", "direction": "slaves-to-master RX -", "description": "Inverting receive pair line into the master receiver."},
        ])
        d.setdefault("transceiver_digital_pins", [
            {"name": "D / DI", "direction": "input",  "description": "Driver input from the host UART (TXD). Determines A/B differential polarity when driver is enabled."},
            {"name": "DE",     "direction": "input",  "description": "Driver Enable, active HIGH. When DE=1 the transceiver drives A/B; when DE=0 the driver outputs are high-impedance (tri-stated)."},
            {"name": "RE#",    "direction": "input",  "description": "Receiver Enable, active LOW. When RE#=0 the receiver output R is driven; when RE#=1 R is high-impedance."},
            {"name": "R / RO", "direction": "output", "description": "Receiver output to the host UART (RXD). Reflects the logical bus state when receiver enabled."},
        ])
        d.setdefault("differential_bit_encoding", {
            "header": ["Logical state", "Differential V_AB = V_A - V_B", "Bus condition"],
            "rows": [
                ["mark (logical 1, idle)",  "V_AB > +200 mV", "Failsafe-biased direction; receiver R = HIGH"],
                ["space (logical 0)",       "V_AB < -200 mV", "Receiver R = LOW"],
                ["indeterminate / LOS",     "|V_AB| < 200 mV", "Receiver R = undetermined unless fail-safe biasing forces a determined state"],
            ],
        })
        d.setdefault("valid_ready_handshake_rules", [
            "There is no per-byte VALID/READY handshake on the differential bus — RS-485 is an asynchronous electrical layer.",
            "Half-duplex direction handover requires software-controlled DE / RE# coordination — only one driver may be enabled at any time to avoid bus contention.",
            "Higher-level protocols (Modbus RTU master/slave, DL/T645 request/reply) provide application-level request/response handshaking and per-message timing rules (e.g. Modbus RTU 3.5-char inter-frame gap).",
            "Receiver fail-safe biasing acts as a passive 'idle = mark' handshake when no driver is active.",
        ])
        d.setdefault("burst_based", False)
        d.setdefault("byte_oriented",
            "byte-stream when wrapping UART framing (most common); pure bit-stream otherwise.")
        d.setdefault("frame_format", {
            "note": "RS-485 does NOT define a frame format. The most common usage wraps RS-422-style UART framing (start bit + 5..9 data bits + optional parity + stop bit) on top of the differential bus, then higher protocols (Modbus RTU, DMX-512, …) frame those bytes into messages.",
        })
        _write(p, d)

    # ---------------- L4 register map (intentionally absent) ----------------
    p = gd / "L4_REGMAP.json"
    if p.is_file():
        d = _read(p)
        # v0.1.88: RS-485 is wire-level — force False over any UART pre-fill True.
        _force(d, "register_map_present", False)
        _force(d, "notes",
            "RS-485 is a wire-level electrical standard and not a peripheral block guide. There is no "
            "architectural register map at the protocol layer — drivers and receivers are stateless "
            "analog transceivers. Concrete RS-485 transceiver chips (e.g. TI SN65HVDxx, SN65LBC184, "
            "MAX485) and embedded RS-485 controller IP (e.g. NXP iMX UART with RS-485 mode, Synopsys "
            "DesignWare UART with RS-485 wrapper) define their own register file (typically: UART "
            "config + DE/RE# polarity + half/full-duplex mode + driver-enable timer) at the SoC "
            "integration level. RS-485 itself does not.")
        _write(p, d)

    # ---------------- L5 analog-digital interface ----------------
    p = gd / "L5_ADI_SPEC.json"
    if p.is_file():
        d = _read(p)
        # v0.1.88: RS-485 IS mixed-signal — force True over UART pre-fill (which defaults False).
        _force(d, "analog_digital_interface_present", True)
        _force(d, "signaling_summary",
            "RS-485 IS a mixed-signal analog-digital interface: differential analog bus driven by "
            "digital TTL/CMOS-level driver-input D and producing a digital TTL/CMOS-level "
            "receiver-output R. The bus side carries analog voltages; the host side carries logic levels.")
        d.setdefault("driver_specifications", {
            "min_differential_output_loaded": "1.5 V across a 54-ohm test load (two 120-ohm terminations in parallel + 32 unit loads).",
            "supply": "Single +5 V (most common); 3.3 V variants also widely available.",
            "test_load": "54 ohm differential (matches worst-case bus loading per spec).",
            "rise_time_examples_from_TI": [
                {"part": "SN65HVD12",     "rise_time_ns": 100, "signal_rate_kbps": 1000, "max_stub_ft": 7},
                {"part": "SN65LBC184",    "rise_time_ns": 250, "signal_rate_kbps": 250,  "max_stub_ft": 19},
                {"part": "SN65HVD3082E",  "rise_time_ns": 500, "signal_rate_kbps": 200,  "max_stub_ft": 38},
            ],
            "short_circuit_protection": "Required by all compliant drivers; current-limited to prevent damage on bus contention.",
        })
        d.setdefault("receiver_specifications", {
            "min_differential_input_sensitivity": "±200 mV across the entire common-mode range.",
            "common_mode_range": "-7 V to +12 V referenced to receiver ground.",
            "input_impedance_one_unit_load": "approximately 12 kohm (defines '1 UL').",
            "fractional_unit_loads": "1/2, 1/4, 1/8 UL devices commonly available — 1/8 UL allows 256 transceivers per bus.",
            "input_hysteresis": "Manufacturer-defined; small hysteresis prevents noise-induced output chatter near the ±200 mV threshold.",
            "failsafe": "Modern transceivers integrate open-circuit, short-circuit, and idle-bus failsafe biasing that drives R to a determined HIGH state when V_AB is near zero or the bus is undriven.",
        })
        d.setdefault("noise_margins", {
            "transmitter_margin_per_spec": "1.5 V driver minus 200 mV receiver threshold = 1.3 V differential noise margin in normal operation.",
            "internal_failsafe_worst_case_margin": "approximately 10 mV (drawback of integrated failsafe alone in noisy environments).",
            "external_failsafe_target_VAB": "200 mV + V_noise to restore robust margin in noisy environments.",
        })
        d.setdefault("common_mode_range_engineering", {
            "specified_range_v": [-7, 12],
            "ground_potential_difference_mitigation":
                "Use digital isolators + isolated DC/DC across the transceiver supply and signal lines "
                "when GPD may approach or exceed ±7 V.",
        })
        d.setdefault("failsafe_external_biasing", {
            "purpose": "Generate sufficient differential bus voltage V_AB so that V_AB ≥ 200 mV + V_noise on an idle bus.",
            "formula_RB": "R_B = V_BUS_min / [V_AB × (1 / 375 + 4 / Z0)]  (eq. 2 in SLLA272D)",
            "worked_example_5V_supply": "V_BUS_min = 4.75 V (5 V - 5 %); V_AB target = 0.25 V; Z0 = 120 ohm → R_B ≈ 528 ohm. Insert two ~523 ohm resistors in series with the termination R_T to form the divider.",
            "topology": "Two pull resistors RB at each end of the bus: one from line A to +V_BUS (pull-up), one from line B to GND (pull-down).",
        })
        d.setdefault("esd_protection_examples",
            "Modern TI RS-485 transceivers integrate ESD protection from 16 kV to 30 kV "
            "(IEC 61000-4-2 / HBM).")
        _write(p, d)

    # ---------------- L6 control / FSM ----------------
    p = gd / "L6_CONTROL_LOGIC.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("fsm_states_transceiver_half_duplex", [
            {"name": "TXR_DISABLED",   "description": "DE=0, RE#=1 — both driver and receiver tri-stated; transceiver in shutdown/low-power."},
            {"name": "TXR_RX_ONLY",    "description": "DE=0, RE#=0 — driver tri-stated, receiver enabled. R = digital reflection of V_AB."},
            {"name": "TXR_TX_ONLY",    "description": "DE=1, RE#=1 — driver enabled, receiver tri-stated (or echo-disabled). Bus driven differentially based on D input."},
            {"name": "TXR_TX_AND_LOOPBACK", "description": "DE=1, RE#=0 — both enabled; receiver echoes the transmitted bit back to R (useful for half-duplex collision detection)."},
        ])
        d.setdefault("fsm_states_bus_logical", [
            {"name": "BUS_IDLE",       "description": "No driver enabled; differential bus voltage near zero unless failsafe biasing pulls V_AB > +200 mV → all receivers see R = HIGH (mark)."},
            {"name": "BUS_MARK",       "description": "Active driver pulls V_AB > +200 mV → all receivers see R = HIGH (logical 1)."},
            {"name": "BUS_SPACE",      "description": "Active driver pulls V_AB < -200 mV → all receivers see R = LOW (logical 0)."},
            {"name": "BUS_CONTENTION", "description": "Two or more drivers enabled simultaneously — bus current spikes; data corrupted; relies on driver short-circuit current limit to avoid damage. MUST be prevented by software."},
        ])
        d.setdefault("fsm_hints", {
            "direction_control_owner":     "Higher-level software (e.g. Modbus RTU master/slave timer, half-duplex tester FSM) owns DE / RE# scheduling.",
            "minimum_idle_before_TX":      "Higher-level protocols define inter-frame gaps (Modbus RTU: 3.5 character times) to guarantee bus quietness before next driver enables.",
            "DE_to_first_bit_delay":       "Implementation-specific transceiver propagation delay (typ 50..500 ns) — TX-side software must wait this delay after asserting DE before clocking data into D.",
            "last_bit_to_DE_deassert_delay":"Transmitter must hold DE asserted until last stop bit has left the driver (otherwise the wire is tri-stated mid-stop-bit).",
        })
        d.setdefault("anti_deadlock_rule",
            "Bus arbitration is NOT defined by RS-485 — collisions cause data corruption and rely on "
            "the application-layer protocol to detect and retry. Strict ownership rules at the "
            "application layer (Modbus master polling, time-division-multiplex, token-passing) "
            "substitute for hardware arbitration.")
        d.setdefault("exit_from_reset",
            "On power-up the transceiver power-on-reset (POR) holds DE = LOW (driver disabled). "
            "Software in the host MCU asserts RE# = LOW (receiver enabled) for receive-first "
            "half-duplex initial state. Failsafe biasing keeps R = HIGH (mark / idle UART line) so "
            "the host UART RX does not see a false start bit.")
        d.setdefault("default_ready_state_recommendation", {
            "DE_default": "LOW (driver tri-stated) — prevents bus contention during power-up before software is ready.",
            "RE#_default": "LOW (receiver enabled) — host UART RX sees idle mark, no false start bits.",
            "Bus_idle_V_AB": "> +200 mV (mark) by failsafe biasing, so all receivers report R = HIGH = mark.",
        })
        d.setdefault("loopback_diagnostic_mode", {
            "trigger": "Set DE=1 + RE#=0 simultaneously on a single node while no other driver is active.",
            "behavior": [
                "Transceiver drives V_AB according to D input.",
                "Same transceiver's receiver sees V_AB and produces R reflecting D.",
                "Allows software self-test of TX path + bus stub + RX path without external loopback wiring.",
            ],
        })
        d.setdefault("failsafe_biasing_modes", {
            "internal_failsafe":  "Built into modern transceivers; covers open-circuit / short-circuit / idle-bus; worst-case noise margin ≈ 10 mV.",
            "external_failsafe":  "Resistive divider on each bus end (R_B in series with R_T); engineered for V_AB ≥ 200 mV + V_noise; restores robust noise margin.",
        })
        d.setdefault("isolation_recommendations", [
            "When ground-potential difference (GPD) may approach the -7 V to +12 V common-mode range, insert galvanic isolation (digital isolator + isolated DC/DC).",
            "Direct connection of remote grounds via ground wire is NOT recommended (causes large ground-loop currents).",
            "Resistor-bonded ground separation reduces loop current but leaves the link sensitive to induced noise.",
            "Full signal + supply isolation provides multi-kilovolt GPD tolerance and is the recommended long-distance robust topology.",
        ])
        _write(p, d)

    # ---------------- L7 test / debug ----------------
    p = gd / "L7_TEST_DEBUG.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("test_debug_architecture_present", False)
        d.setdefault("spec_provided_observability", [
            {"name": "Differential bus voltage V_AB",       "purpose": "Direct measurement on an oscilloscope between line A and line B; should swing > ±1.5 V at the driver with 54-ohm load."},
            {"name": "Common-mode bus voltage (V_A+V_B)/2", "purpose": "Should stay within -7 V to +12 V relative to receiver ground; excursions indicate GPD problems."},
            {"name": "Receiver output R / RO",               "purpose": "Logic-level reflection of bus state; observable on the host UART RX pin."},
            {"name": "Driver enable DE pin",                 "purpose": "Probe to confirm timing of driver tri-state vs assert vs idle gap."},
            {"name": "Bus eye diagram",                       "purpose": "Persistence-mode scope capture across many bits — opening width / height directly correlates with jitter budget and BER."},
            {"name": "Loss-of-signal LED / register bit (transceiver-specific)", "purpose": "Some modern transceivers expose a LOS / Bus-Activity status pin or register bit."},
        ])
        d.setdefault("test_debug_features", [
            "Internal node loopback — drive DE=1 + RE#=0 on a single isolated node to TX+RX through itself (without other drivers active).",
            "Bus contention detection — capture V_AB at the loopback receiver while transmitting; mismatch between TX D and RX R indicates external bus contention.",
            "Failsafe verification — disable all drivers and confirm receiver R stays HIGH (mark) via internal or external failsafe biasing.",
            "Termination integrity check — measure DC resistance between A and B with all drivers tri-stated; should equal R_T / 2 = 60 ohm for 120-ohm-terminated bus.",
            "Stub-reflection inspection — single-shot scope capture of the rising edge; visible reflections indicate too-long stubs (L_stub > tr × v × c / 10).",
        ])
        d.setdefault("interrupt_sources", [])
        d.setdefault("interrupt_request",
            "RS-485 has no protocol-level interrupt. Transceiver-level fault outputs (overheating, "
            "bus-fault) are vendor-specific and not part of the standard.")
        d.setdefault("notes",
            "RS-485 is an electrical / wire-level standard and does not specify DFT / scan / BIST. "
            "Conformance testing is conducted at the chip level (driver/receiver electricals) and at "
            "the system level (eye-diagram + BER vs cable length). Industry test suites for "
            "higher-level protocols built on RS-485 (Modbus conformance, DL/T645 conformance) test "
            "the link layer separately.")
        _write(p, d)

    # ---------------- L8 RTL constants ----------------
    p = gd / "L8_RTL_CONSTANTS.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("width_parameters", {
            "DIFFERENTIAL_PAIR_COUNT_HALF_DUPLEX": 1,
            "DIFFERENTIAL_PAIR_COUNT_FULL_DUPLEX": 2,
            "BUS_WIRE_COUNT_HALF_DUPLEX": 2,
            "BUS_WIRE_COUNT_FULL_DUPLEX": 4,
            "TRANSCEIVER_DIGITAL_PIN_COUNT": 4,
            "DRIVER_INPUT_PIN": "D / DI",
            "DRIVER_ENABLE_PIN": "DE (active HIGH)",
            "RECEIVER_ENABLE_PIN": "RE# (active LOW)",
            "RECEIVER_OUTPUT_PIN": "R / RO",
            "BUS_LINE_NAMES": ["A (non-inverting)", "B (inverting)"],
            "FULL_DUPLEX_LINE_NAMES_OPTIONAL": ["Y (TX +)", "Z (TX -)", "A (RX +)", "B (RX -)"],
        })
        d.setdefault("voltage_levels", {
            "supply_5V_typ":              "+5 V ± 5 % (most common); 3.3 V variants also widely available.",
            "driver_min_diff_loaded_V":   1.5,
            "driver_test_load_ohm":       54,
            "receiver_min_diff_input_mV": 200,
            "common_mode_range_V":        [-7, 12],
            "logic_input_levels":         "TTL / CMOS compatible on D, DE, RE# pins.",
        })
        d.setdefault("bus_electrical_constants", {
            "cable_characteristic_impedance_Z0_ohm": 120,
            "cable_capacitance_pF_per_ft":            11,
            "cable_velocity_factor":                  0.78,
            "cable_velocity_ns_per_ft":               1.3,
            "termination_R_T_each_end_ohm":           120,
            "alternative_termination_60_220pF_low_pass": "Two 60-ohm resistors in series + 220 pF to ground for common-mode noise filtering — match values to <= 1 % tolerance.",
            "unit_load_impedance_kohm":               12,
            "max_standard_unit_loads":                32,
            "max_nodes_with_1_8_UL":                  256,
            "max_nodes_with_1_8_UL_and_failsafe":     96,
            "failsafe_biasing_overhead_unit_loads":   20,
        })
        d.setdefault("data_rate_distance_constants", {
            "max_data_rate_bps_at_40ft":   10000000,
            "max_data_rate_bps_modern":    40000000,
            "max_cable_length_m_at_100kbps": 1200,
            "max_cable_length_ft_at_100kbps": 4000,
            "rule_of_thumb_length_x_rate_bound": "length [m] × rate [bps] < 10^7",
            "low_freq_signal_loss_dB":     -6,
            "low_freq_cable_length_m_22AWG_120ohm_minus_6dB": 1200,
            "jitter_BER_threshold_pct_of_baud": 10,
        })
        d.setdefault("stub_constants", {
            "rule":                "L_stub ≤ tr × v × c / 10",
            "c_ft_per_s":          980000000,
            "v_factor":             0.78,
            "examples": [
                {"part": "SN65HVD12",    "tr_ns": 100, "stub_ft_max": 7},
                {"part": "SN65LBC184",   "tr_ns": 250, "stub_ft_max": 19},
                {"part": "SN65HVD3082E", "tr_ns": 500, "stub_ft_max": 38},
            ],
        })
        d.setdefault("minimum_node_spacing_constants", {
            "rule":                  "d > C_L / (5.25 × C')",
            "Z_loaded_min_factor":    0.4,
            "C_L_typical_5V_pF":     7,
            "C_L_typical_3V_pF":     16,
            "C_per_unit_length_pF_per_m_low_cap": 40,
            "C_per_unit_length_pF_per_m_backplane": 70,
        })
        d.setdefault("failsafe_biasing_constants", {
            "RB_formula": "R_B = V_BUS_min / [V_AB × (1 / 375 + 4 / Z0)]",
            "RB_worked_example_ohm": 528,
            "RB_practical_choice_ohm": 523,
            "VAB_target_external_mV": "200 + V_noise",
        })
        d.setdefault("key_constants_for_RTL_authoring", {
            "differential_signaling":  True,
            "duplex_mode":             "configurable: half (2-wire) or full (4-wire)",
            "default_idle_logic":      1,
            "DE_polarity":             "active HIGH",
            "RE_polarity":             "active LOW",
            "DE_default_state":        0,
            "RE_default_state":        0,
            "transceiver_is_external": "RS-485 is an external analog transceiver (e.g. SN65HVDxx, MAX485) — the on-chip RTL is the UART + DE/RE# direction-control FSM, not a differential I/O pad.",
            "uart_framing_on_top":     "Most common usage wraps RS-422-style UART framing (1 start + 5..9 data + optional parity + 1..2 stop) on top of the differential bus.",
        })
        d.setdefault("default_signal_values_after_reset", {
            "DE":  "LOW (driver tri-stated; bus quiet at this node)",
            "RE#": "LOW (receiver enabled; host UART RX sees idle mark via failsafe biasing)",
            "D":   "HIGH (UART idle)",
            "R":   "HIGH (UART idle reflection via failsafe biasing)",
        })
        _write(p, d)

    # ---------------- L8 timing waveform ----------------
    p = gd / "L8_TIMING_WAVEFORM.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("differential_bit_waveform", {
            "logical_one_mark":   "V_A > V_B; V_AB = V_A - V_B > +200 mV at any receiver across the common-mode range. Driver-side minimum |V_AB| = 1.5 V into 54-ohm test load.",
            "logical_zero_space": "V_A < V_B; V_AB < -200 mV at any receiver.",
            "idle":               "All drivers tri-stated; V_AB driven > +200 mV by failsafe biasing → receiver R = HIGH = mark.",
            "transition_rise_time_examples_ns": [100, 250, 500],
        })
        d.setdefault("driver_rise_time_vs_stub_table", {
            "header": ["Device", "Signal Rate [kbps]", "Rise Time tr [ns]", "Max Stub Length [ft]"],
            "rows": [
                ["SN65HVD12",    "1000", "100", "7"],
                ["SN65LBC184",    "250", "250", "19"],
                ["SN65HVD3082E",  "200", "500", "38"],
            ],
            "note": "Drivers with longer rise times tolerate longer stubs and produce less device-generated EMI.",
        })
        d.setdefault("stub_length_equation", {
            "rule": "L_stub ≤ (tr / 10) × v × c",
            "variables": {
                "L_stub": "maximum stub length in ft",
                "tr": "driver 10/90 rise time in ns",
                "v":  "signal velocity of cable as factor of c (typ 0.78)",
                "c":  "speed of light = 9.8e8 ft/s",
            },
        })
        d.setdefault("cable_length_vs_data_rate_regions", [
            {"region": "Section 1 — high data rate / short cable", "rule": "Line losses negligible; data rate limited by driver rise time. Standard recommends 10 Mbps; modern parts reach 40 Mbps."},
            {"region": "Section 2 — transition / medium",          "rule": "Line losses matter; rule-of-thumb length [m] × rate [bps] < 10^7 (conservative)."},
            {"region": "Section 3 — long cable / low data rate",    "rule": "Cable resistance dominates; resistance approaches R_T and attenuates signal by -6 dB. For 22 AWG 120-ohm UTP this happens at ~1200 m."},
        ])
        d.setdefault("minimum_node_spacing_curves", {
            "axes": {"x": "Media distributed capacitance pF/m", "y": "Minimum distance m between nodes"},
            "parameter": "Lumped load capacitance C_L per node (pF)",
            "example_curves": [
                {"C_L_pF": 10,  "shape": "lowest curve — nodes can be closely spaced"},
                {"C_L_pF": 20,  "shape": "increased spacing"},
                {"C_L_pF": 40,  "shape": "further increased"},
                {"C_L_pF": 60,  "shape": "further increased"},
                {"C_L_pF": 100, "shape": "highest curve — widest spacing required"},
            ],
        })
        d.setdefault("failsafe_biasing_waveform", {
            "idle_VAB_target": "≥ 200 mV + V_noise on an undriven bus",
            "RB_topology":     "Pull-up resistor R_B from line A to +V_BUS at each end + pull-down resistor R_B from line B to GND at each end; in series with termination R_T.",
        })
        d.setdefault("common_mode_envelope", {
            "specified_range_V": "-7 V to +12 V",
            "design_pitfalls":   [
                "Direct ground-wire return — large ground-loop current couples GPD noise into data lines.",
                "Resistor-bonded ground separation — reduces loop current but still sensitive to induced noise.",
                "Signal + supply galvanic isolation — robust to multi-kilovolt GPDs and the recommended long-distance approach.",
            ],
        })
        d.setdefault("direction_control_timing_half_duplex", {
            "TX_setup": "DE asserts before first start-bit edge; software waits for transceiver tDE_to_drive propagation delay.",
            "TX_hold":  "DE held asserted until last stop bit has fully exited the driver; tail length is implementation-specific.",
            "RX_to_TX_gap": "Application-layer protocol defines this (Modbus RTU: 3.5 character times of bus quietness).",
        })
        _write(p, d)

    # ---------------- L9 integration spec ----------------
    p = gd / "L9_INTEGRATION_SPEC.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("module_role",
            "Physical-layer (OSI layer 1) electrical interface: a balanced differential bus driven by "
            "half-duplex or full-duplex transceivers connecting multiple nodes in a daisy-chain "
            "topology. Provides robust noise-immune signaling over long distances.")
        # v0.1.88: RS-485 chip-top is the transceiver + DE/RE# direction wrapper, not the UART core.
        _ptm.apply(
            d,
            "RS485_transceiver (external chip) + UART_with_DE/RE#_direction_control (on-chip)")
        d.setdefault("integration_overview", {
            "host_side": "UART TX (D) + UART RX (R) + 2 GPIO direction-control bits (DE active HIGH, RE# active LOW).",
            "bus_side_2_wire": "Differential pair A / B shared by all nodes; one driver enabled at a time.",
            "bus_side_4_wire": "Two differential pairs: master-TX (Y/Z) and master-RX (A/B); no DE/RE# arbitration required.",
            "supply": "Single 5 V (typical) or 3.3 V; transceiver-local LDO often integrated.",
            "reset_source": "Power-on reset internal to transceiver; system reset on host MCU governs DE/RE# defaults.",
            "termination_routing": "120 ohm at each cable end; failsafe biasing R_B in series at each end forms a divider sustaining V_AB > 200 mV idle.",
        })
        d.setdefault("interface_categories", [
            "Differential bus pair A / B (or Y / Z + A / B for full-duplex).",
            "Driver-input D and driver-enable DE.",
            "Receiver-output R and receiver-enable RE#.",
            "Supply VCC + GND (isolated supply for long-distance robust topology).",
            "Cable shield (chassis-bonded or floating per EMC design).",
        ])
        d.setdefault("interconnect_topologies_supported", [
            "Half-duplex 2-wire linear bus (daisy chain) — single twisted pair; one driver at a time; party-line.",
            "Full-duplex 4-wire linear bus — two twisted pairs; master TX on one pair, all slave TX on the other.",
            "Multi-drop with up to 32 standard unit loads (or 96 / 256 with 1/8-UL transceivers).",
            "Isolated multi-node bus — single non-isolated transceiver provides single-ground reference; all other nodes use isolated transceivers.",
            "Layered protocol stacks — Modbus RTU, DL/T645, Profibus DP, BACnet MS/TP, DMX-512 all run on RS-485 PHY.",
        ])
        d.setdefault("default_signal_values_when_omitted",
            "DE = LOW (driver tri-stated), RE# = LOW (receiver enabled), failsafe biasing pulls V_AB > "
            "+200 mV so all receivers see R = HIGH (UART idle mark).")
        d.setdefault("soc_dependent_items", [
            "Choice of transceiver part (SN65HVDxx for high speed; SN65LBC184 / SN65HVD3082E for slow / long-stub tolerance).",
            "Choice of half-duplex vs full-duplex wiring.",
            "Termination strategy (simple 120-ohm vs 60-ohm + 220 pF low-pass).",
            "Failsafe biasing — internal (transceiver-integrated) vs external (R_B resistive divider).",
            "Cable selection (industrial UTP 120 ohm 22 AWG typical; example Belden 3109A).",
            "Stub-length budget per node (driven by transceiver tr).",
            "Galvanic isolation (digital isolator + isolated DC/DC) if GPD likely.",
            "Direction-control timing tuning at the UART software / hardware level.",
            "Higher-level protocol selection (Modbus RTU vs DL/T645 vs Profibus DP vs DMX-512 vs custom).",
        ])
        d.setdefault("low_power_modes", {
            "transceiver_shutdown": "DE=LOW + RE#=HIGH commonly puts transceiver into low-power shutdown / standby (vendor-specific).",
            "host_uart_clock_gating": "On the host MCU, clock-gating the UART block during idle reduces dynamic power.",
            "no_protocol_level_sleep": "RS-485 itself does not define a sleep / wake-up message — that is layered above.",
        })
        d.setdefault("compatibility_notes", [
            "RS-485 receivers are designed to be backward-compatible with RS-422 drivers; an RS-485 receiver can be driven by an RS-422 transmitter as long as common-mode and termination are respected.",
            "Higher-level standards reference RS-485 as the physical layer — DL/T645 (Chinese electronic energy meters per SLLA272D §2), Modbus RTU, BACnet MS/TP, DMX-512, Profibus DP.",
            "Modern RS-485 transceivers are pin-compatible across most vendors for the 8-pin SOIC SN75176-style footprint; capability differences (1/8 UL, integrated failsafe, signaling rate) are reflected in datasheets, not pinout.",
        ])
        _write(p, d)

    # ---------------- L10 test cases ----------------
    p = gd / "L10_TEST_CASES.json"
    if p.is_file():
        d = _read(p)
        # v0.1.88: RS-485 spec is electrical-only — force the test_cases_present
        # description and DROP any UART-pre-fill `test_cases` heuristics
        # (they introduce 0x32 opcode_hex that trips the HALLUCINATED regex).
        _force(d, "test_cases_present",
            "partial - the spec is electrical-only and describes conformance points (driver / receiver "
            "minimums, common-mode range, termination, stub length, failsafe) but does not provide a "
            "formal testbench.")
        if "test_cases" in d:
            del d["test_cases"]
        if _empty(d.get("derived_compliance_test_categories")):
            d["derived_compliance_test_categories"] = [
                "Driver minimum differential output ≥ 1.5 V across a 54-ohm load.",
                "Driver minimum differential output sustained over operating temperature and supply tolerance.",
                "Driver short-circuit current limit when A and B are shorted together.",
                "Receiver minimum sensitivity ±200 mV across -7 V to +12 V common-mode range.",
                "Receiver output transition matches the V_AB polarity at the ±200 mV thresholds.",
                "Common-mode rejection at -7 V and +12 V extremes.",
                "Failsafe operation under open-circuit (cable cut) — R stays HIGH.",
                "Failsafe operation under short-circuit (A shorted to B or to other wire) — R stays HIGH.",
                "Failsafe operation under idle-bus (all drivers tri-stated) — R stays HIGH.",
                "External failsafe biasing — measure V_AB with all drivers tri-stated; verify ≥ 200 mV + V_noise.",
                "Termination correctness — measure differential reflections on a TDR; observe matched cable Z0 = 120 ohm at each end.",
                "Stub-length tolerance — measure eye diagram at the receiver at L_stub = (tr/10) × v × c boundary.",
                "Bus loading — connect 32 standard UL (or N × 1/8 UL) and verify driver V_AB still ≥ 1.5 V.",
                "Half-duplex direction control — DE / RE# sequencing across handover gap.",
                "Bus-contention behavior — two drivers enabled simultaneously; verify driver current limit + no permanent damage.",
                "Maximum data rate vs cable length per the cable-length-vs-data-rate graph.",
                "Cable selection — typical UTP 120 ohm 22-24 AWG (e.g. Belden 3109A); confirm 11 pF/ft, v = 78 % spec.",
                "Ground-potential difference tolerance with isolation: galvanic isolator + isolated DC/DC; confirm operation at multi-kilovolt GPD.",
                "Common-mode-noise rejection test — inject GPD step within ±7 V and verify no bit errors.",
                "Higher-level protocol stack tests — Modbus RTU / DL/T645 / BACnet MS/TP conformance run on top of the validated PHY.",
            ]
        _write(p, d)

    # ---------------- L11 OTP content (none) ----------------
    p = gd / "L11_OTP_CONTENT.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("otp_present", False)
        # v0.1.88: force RS-485 notes over any UART-pre-fill "no OTP for serial peripheral" stub.
        _force(d, "notes",
            "RS-485 is a wire-level electrical standard; no OTP / fuse / configuration ROM at the "
            "protocol layer. Concrete RS-485 transceiver chips are stateless analog parts with no "
            "programmable bits. Higher-level controller IP (UART with RS-485 wrapper) may have "
            "configuration bits at the SoC integration level, but these are not OTP-defined by RS-485.")
        _write(p, d)

    # ---------------- L12 behavioral sequences ----------------
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("typical_half_duplex_transmit_sequence", [
            "1. Wait for inter-frame gap defined by the upper-level protocol (e.g. Modbus RTU 3.5 character times of bus quietness).",
            "2. Assert DE = HIGH on the local transceiver; driver becomes active and starts driving V_AB.",
            "3. Wait for transceiver tDE_to_drive propagation delay (typ tens to hundreds of ns) so the bus is settled before the first start-bit edge.",
            "4. Drive UART start bit (LOW → V_A < V_B → space) through D input.",
            "5. Drive 5..9 data bits LSB-first, optional parity, then 1..2 stop bits HIGH (mark).",
            "6. After the last stop bit, wait for the driver's tHOLD time before deasserting DE.",
            "7. Deassert DE = LOW; driver tri-states. Bus returns to failsafe-biased idle.",
            "8. Optionally assert RE# = LOW (already low if always-listening half-duplex) to enable the receiver path for the next slave reply.",
        ])
        d.setdefault("typical_half_duplex_receive_sequence", [
            "1. RE# = LOW (receiver enabled), DE = LOW (driver disabled).",
            "2. Failsafe biasing holds V_AB > +200 mV idle → R = HIGH = UART idle.",
            "3. Remote driver pulls V_AB < -200 mV → R goes LOW = UART start bit.",
            "4. Host UART samples mid-bit (16× oversampling typical) and captures data bits LSB-first.",
            "5. UART validates stop bit; raises framing-error flag if it failed.",
            "6. Upper-level protocol (Modbus RTU CRC, DL/T645 BCC, …) validates the frame.",
        ])
        d.setdefault("typical_full_duplex_transmit_sequence", [
            "1. Master drives V_AB on the Y/Z pair through its dedicated driver — DE permanently HIGH (or per-frame).",
            "2. Slaves drive V_AB on the A/B pair through their respective drivers when addressed; only one slave at a time, governed by the upper protocol.",
            "3. Master receiver listens on the A/B pair continuously; slave receivers listen on the Y/Z pair continuously.",
        ])
        d.setdefault("loopback_diagnostic_sequence", [
            "1. Disconnect or disable all other drivers on the bus.",
            "2. Set DE = HIGH and RE# = LOW on the local transceiver.",
            "3. Drive D with a test pattern; observe R; expect R = D (logical inversion already cancelled by the transceiver internally).",
            "4. Confirm V_AB swing > ±1.5 V on a scope across the local termination.",
            "5. Set DE = LOW and verify R returns to HIGH (mark) under failsafe biasing.",
        ])
        d.setdefault("failsafe_validation_sequence", [
            "1. Power up all transceivers with DE = LOW (all drivers tri-stated).",
            "2. Measure V_AB across the bus; expect ≥ 200 mV (internal failsafe) or ≥ 200 mV + V_noise (external failsafe).",
            "3. Verify each receiver output R = HIGH = mark.",
            "4. Inject a cable cut (open-circuit) and confirm V_AB and R remain in mark state.",
            "5. Short A to B and confirm receiver R remains in mark state (or reports loss-of-signal per vendor).",
        ])
        d.setdefault("isolation_link_bring_up_sequence", [
            "1. Power up host MCU + non-isolated portion of the transceiver (primary side of digital isolator + isolated DC/DC).",
            "2. Isolated DC/DC starts up the bus-side supply.",
            "3. Digital isolator transmits idle high on D across the barrier; transceiver driver tri-stated (DE = LOW).",
            "4. Receiver path active; system ready for Modbus / DL/T645 / BACnet polling.",
            "5. Confirm GPD tolerance by applying a controlled DC offset on the isolated supply ground vs the host ground.",
        ])
        d.setdefault("bus_contention_diagnostic_sequence", [
            "1. While transmitting through the local driver, simultaneously read back R from the local receiver (loopback).",
            "2. Mismatch between transmitted D and read-back R indicates another driver is overriding the bus.",
            "3. Higher-level protocol must back off, wait inter-frame gap, and retry.",
        ])
        _write(p, d)

    # ---------------- L13 lab calibration (none) ----------------
    p = gd / "L13_LAB_CALIBRATION.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("lab_calibration_present", False)
        # v0.1.88: force the RS-485 stateless-analog notes over any UART pre-fill.
        _force(d, "notes",
            "RS-485 transceivers are stateless analog parts; no chip-level calibration / trim loop is "
            "defined by the standard. System-level engineering parameters (termination resistor "
            "tolerance ≤ 1 %, failsafe resistor selection per eq. 2 of SLLA272D, common-mode envelope, "
            "stub length per L_stub ≤ tr × v × c / 10, minimum node spacing per d > C_L / (5.25 × C')) "
            "substitute for calibration at the link level. Test equipment of choice is an oscilloscope "
            "with differential probe, a TDR for impedance/stub assessment, and a noise generator + GPD "
            "source for common-mode robustness.")
        _write(p, d)

    # ---------------- L14 protocol versioning (wrap under "fields") ----------------
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if p.is_file():
        d = _read(p)
        f = d.setdefault("fields", {})
        if isinstance(f, dict):
            f.setdefault("spec_version",
                "TIA/EIA-485 (RS-485) — TI Application Report SLLA272D, revised May 2021 "
                "(original SLLA272 February 2008)")
            f.setdefault("previous_versions", [
                "TIA/EIA-485-A (1998) — original ANSI/EIA balanced multipoint electrical interface standard, evolved from EIA RS-422.",
                "TIA/EIA-485-A R2003 — reaffirmation of 1998 spec; clarified common-mode range and unit-load definition.",
                "TIA/EIA-485-A R2012 — further reaffirmation; widely used industrial baseline.",
                "Texas Instruments SLLA272 (Feb 2008) — first TI design guide capturing the standard as a practitioner-oriented summary.",
                "Texas Instruments SLLA272D (May 2021) — current revision; tracks decade of new transceiver families (high-ESD, 1/8-UL, integrated failsafe, fast 40 Mbps variants) and modern isolation guidance.",
            ])
            f.setdefault("lineage_above", [
                {"name": "EIA RS-422", "year": "1975", "summary": "Balanced point-to-point or multi-receiver one-driver electrical standard; ±2 V driver into 100-ohm load; ±200 mV receiver. RS-485 generalizes RS-422 to multi-driver multipoint."},
                {"name": "EIA RS-423", "year": "1975", "summary": "Single-ended counterpart; lower noise immunity; less common."},
                {"name": "EIA RS-485", "year": "1983", "summary": "Multi-master / multi-drop generalization of RS-422 with -7 V to +12 V common-mode, 32-UL standard limit, 200 mV receiver threshold."},
                {"name": "TIA-485-A",  "year": "1998", "summary": "Renaming under the TIA umbrella after EIA reorganization."},
            ])
            f.setdefault("key_changes", [
                {"version": "RS-422 → RS-485", "summary": "Added multi-driver multipoint with bitwise driver-enable arbitration handled externally; widened common-mode range; introduced the unit-load concept."},
                {"version": "SLLA272 → SLLA272D", "summary": "Expanded isolation guidance (multi-kV GPD via digital isolator + isolated DC/DC), added 1/8-UL device discussion (256 nodes practical), modern transceiver rise-time-vs-stub table."},
            ])
            # v0.1.88: upstream synth may emit `backward_compat_traps: []`
            # (empty placeholder); setdefault treats that as already-set, so
            # the RS-485 traps never land. Force-overwrite when the existing
            # value is empty / missing / non-list so the RS-485 trap catalog
            # always reaches the doc.
            if _empty(f.get("backward_compat_traps")):
                f["backward_compat_traps"] = [
                {"trap_name": "rs422_driven_rs485_receiver",
                 "RS-422_driver":  "±2 V into 100-ohm load; common-mode 0..6 V.",
                 "RS-485_receiver":"-7 V to +12 V common-mode; ±200 mV threshold.",
                 "trap": "RS-485 receivers accept RS-422 drivers fine; the reverse is NOT true — RS-422 receivers do not tolerate the full -7 V to +12 V common-mode that RS-485 drivers may produce in a multi-master network."},
                {"trap_name": "unit_load_arithmetic_with_failsafe",
                 "standard_drivers": "Drive 32 UL.",
                 "with_failsafe":    "Failsafe biasing consumes up to 20 UL; N = (32 - 20) / UL_per_transceiver remaining transceivers.",
                 "trap": "Designers who forget the 20-UL failsafe overhead overestimate the number of allowed 1/8-UL nodes (calculate 256 instead of 96)."},
                {"trap_name": "internal_vs_external_failsafe_margin",
                 "internal_failsafe":  "Modern transceivers integrate failsafe biasing with worst-case noise margin ≈ 10 mV.",
                 "external_failsafe":  "Engineered resistive divider V_AB = 200 mV + V_noise; restores robust margin.",
                 "trap": "Relying on integrated failsafe alone in noisy industrial environments causes intermittent bit errors at LOS."},
                {"trap_name": "ground_potential_difference_assumption",
                 "designed_for_no_GPD":  "Direct ground-wire return; works on a bench.",
                 "field_reality":        "GPD across building / vehicle distance routinely exceeds the -7 V to +12 V common-mode range.",
                 "trap": "Field robustness needs galvanic isolation (digital isolator + isolated DC/DC), not just shielded twisted-pair."},
                {"trap_name": "stub_length_too_optimistic",
                 "rule":                "L_stub ≤ tr × v × c / 10.",
                 "implication":         "Faster drivers (shorter tr) → shorter allowed stubs; cannot retrofit slow-driver wiring with a fast transceiver swap.",
                 "trap": "Upgrading a working SN65HVD3082E network (38-ft stubs) to SN65HVD12 fast parts will cause reflections on the same wiring."},
            ]
            f.setdefault("version_naming_history_note",
                "RS-485 was approved by EIA in 1983; renamed TIA/EIA-485-A in 1998 under TIA; "
                "reaffirmed multiple times (R2003, R2012). The TI SLLA272 series is a "
                "practitioner-oriented application report — first published Feb 2008, last revised "
                "May 2021 as SLLA272D — that is widely cited as the practical engineering reference "
                "for the standard.")
        _write(p, d)

    # ---------------- L15 encoding tables ----------------
    p = gd / "L15_ENCODING_TABLES.json"
    if p.is_file():
        d = _read(p)
        f = d.setdefault("fields", {})
        if isinstance(f, dict):
            f.setdefault("differential_bit_encoding_table", {
                "header_columns": ["Logical State", "V_AB at receiver", "Driver-side V_AB minimum", "Receiver R output", "Bus condition"],
                "rows": [
                    {"state": "mark (logical 1)",        "vab_receiver": "> +200 mV", "vab_driver_min": "+1.5 V into 54 ohm", "R": "HIGH", "condition": "Idle / UART idle / failsafe-biased rest state"},
                    {"state": "space (logical 0)",       "vab_receiver": "< -200 mV", "vab_driver_min": "-1.5 V into 54 ohm", "R": "LOW",  "condition": "Active driver pulling A < B"},
                    {"state": "indeterminate (no driver)","vab_receiver": "|V_AB| < 200 mV", "vab_driver_min": "n/a — no driver", "R": "undefined unless failsafe", "condition": "Loss-of-signal: open / short / idle bus"},
                ],
            })
            f.setdefault("driver_rise_time_vs_stub_length_table", {
                "header_columns": ["DEVICE", "SIGNAL RATE [kbps]", "RISE TIME tr [ns]", "MAXIMUM STUB LENGTH [ft]"],
                "rows": [
                    ["SN65HVD12",    "1000", "100", "7"],
                    ["SN65LBC184",    "250", "250", "19"],
                    ["SN65HVD3082E",  "200", "500", "38"],
                ],
                "note": "Drivers with longer rise times are well suited for applications requiring long stub lengths and reduced device-generated EMI.",
            })
            f.setdefault("unit_load_and_max_nodes_table", {
                "header_columns": ["Transceiver UL rating", "Max nodes without failsafe", "Max nodes with failsafe overhead (20 UL)"],
                "rows": [
                    ["1 UL (standard)",     "32",   "12"],
                    ["1/2 UL",              "64",   "24"],
                    ["1/4 UL",              "128",  "48"],
                    ["1/8 UL",              "256",  "96"],
                ],
                "formula": "N = (32 UL_STANDARD - 20 UL_FAILSAFE) / UL_per_transceiver",
            })
            f.setdefault("common_mode_envelope_table", {
                "header_columns": ["Parameter", "Min", "Max", "Unit"],
                "rows": [
                    ["Bus common-mode voltage", "-7",  "+12", "V"],
                    ["Receiver differential threshold", "-200", "+200", "mV"],
                    ["Driver differential output (loaded)", "+1.5", "—", "V"],
                    ["Driver test load", "54", "54", "ohm"],
                ],
            })
            f.setdefault("cable_table_example", {
                "header_columns": ["Parameter", "Value"],
                "rows": [
                    ["Cable",        "Belden 3109A"],
                    ["Type",         "4-pair, 22 AWG PLCT/CM"],
                    ["Impedance",    "120 ohm"],
                    ["Capacitance",  "11 pF/ft"],
                    ["Velocity",     "78 % (1.3 ns/ft)"],
                ],
            })
            f.setdefault("termination_options_table", {
                "header_columns": ["Option", "Components", "Use"],
                "rows": [
                    ["Simple R_T",          "1 × 120 ohm at each cable end", "Standard low-noise environment"],
                    ["Common-mode filter",  "Two 60 ohm series + 220 pF to GND at each cable end", "Additional common-mode noise filtering; requires ≤ 1 % resistor tolerance"],
                ],
            })
            f.setdefault("failsafe_biasing_table", {
                "header_columns": ["Parameter", "Symbol", "Value", "Notes"],
                "rows": [
                    ["Minimum bus supply (5 V - 5 %)", "V_BUS_min", "4.75 V", "Worst-case supply"],
                    ["Target idle V_AB",                "V_AB",     "0.25 V (= 200 mV + ~50 mV noise margin)", "Adjust per system noise"],
                    ["Cable impedance",                  "Z0",       "120 ohm", "Industrial UTP"],
                    ["Calculated R_B",                   "R_B",      "≈ 528 ohm", "From eq. 2 in SLLA272D"],
                    ["Practical R_B choice",             "R_B",      "523 ohm",   "1 % tolerance preferred"],
                ],
            })
            f.setdefault("data_rate_vs_length_regions_table", {
                "header_columns": ["Region", "Range", "Dominant limit", "Practical rate / length"],
                "rows": [
                    ["1", "≥ 1 Mbps, ≤ 100 ft",      "Driver rise time / line losses negligible",   "Up to 10 Mbps (standard) or 40 Mbps (modern)"],
                    ["2", "Transition",              "Line losses + jitter; length × rate < 10^7",   "e.g. 1 Mbps at 100 m / 100 kbps at 1000 m"],
                    ["3", "Long cable, ≤ 100 kbps",  "Cable resistance approaches R_T → -6 dB loss", "~1200 m at ≤ 100 kbps (22 AWG, 120 ohm UTP)"],
                ],
            })
            f.setdefault("minimum_node_spacing_table_example", {
                "header_columns": ["C_L per node [pF]", "Media C [pF/m] = 40", "Media C [pF/m] = 70"],
                "rows": [
                    ["10",  "~ 0.05 m", "~ 0.027 m"],
                    ["20",  "~ 0.10 m", "~ 0.055 m"],
                    ["40",  "~ 0.19 m", "~ 0.110 m"],
                    ["60",  "~ 0.29 m", "~ 0.165 m"],
                    ["100", "~ 0.48 m", "~ 0.275 m"],
                ],
                "note": "From d > C_L / (5.25 × C'); ensures loaded bus impedance Z' > 0.4 × Z0.",
            })
            # v0.1.88: upstream synth may emit `tables: []` (empty placeholder);
            # force-overwrite when empty so the RS-485 figure/table catalog lands.
            if _empty(f.get("tables")):
                f["tables"] = [
                    "Table 6-1 Stub Length Versus Rise Time (SLLA272D)",
                    "Figure 4-1 RS-485 Specified Minimum Bus Signal Levels",
                    "Figure 6-1 Proper RS-485 Terminations",
                    "Figure 7-1 External Idle-Bus Failsafe Biasing",
                    "Figure 9-1 Cable Length Versus Data Rate",
                    "Figure 10-1 Minimum Node Spacing With Device and Media Capacitance",
                    "Figure 11-1 Design Pitfalls — ground-loop scenarios",
                    "Figure 11-2 Isolation of Two Remote Transceiver Stations",
                    "Figure 11-3 Isolation of Multiple Fieldbus Transceiver Stations",
                ]
        _write(p, d)

    # ---------------- L16 compliance properties ----------------
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if p.is_file():
        d = _read(p)
        f = d.setdefault("fields", {})
        if isinstance(f, dict):
            if _empty(f.get("must_have_properties")):
                f["must_have_properties"] = [
                    "Balanced differential signaling between lines A (non-inverting) and B (inverting).",
                    "Driver minimum differential output ≥ 1.5 V across a 54-ohm test load over the full operating range.",
                    "Receiver minimum differential input sensitivity ±200 mV.",
                    "Receiver common-mode range -7 V to +12 V referenced to receiver ground.",
                    "Standard-compliant driver capable of driving 32 unit loads (UL); UL ≈ 12 kohm input impedance.",
                    "Cable terminated at each end with a resistor matching characteristic impedance (typically 120 ohm).",
                    "Stub length L_stub ≤ tr × v × c / 10 (with tr in ns, v in factor of c, c = 9.8e8 ft/s).",
                    "Failsafe operation under open-circuit, short-circuit, and idle-bus loss-of-signal conditions — receiver output remains in a determined state.",
                    "Half-duplex direction-control via DE (active HIGH) and RE# (active LOW); only one driver enabled at a time.",
                    "Higher-level protocols handle framing / addressing / CRC on top of the byte stream.",
                    "Differential pair routed close and equidistant on PCB to preserve common-mode rejection.",
                    "Single supply (typically 5 V or 3.3 V) for the transceiver.",
                ]
            if _empty(f.get("must_not_have_properties")):
                f["must_not_have_properties"] = [
                    "Two drivers enabled simultaneously on the same half-duplex bus (bus contention).",
                    "Stub lengths longer than tr × v × c / 10 (causes reflections that close the eye).",
                    "Direct ground-wire return when ground-potential differences may exceed -7 V to +12 V.",
                    "Failsafe biasing that drops V_AB below the 200 mV receiver threshold under noise (insufficient external R_B).",
                    "More than 32 standard-UL transceivers without using fractional-UL parts.",
                    "Missing termination at one or both cable ends (causes severe reflections).",
                    "Mismatched termination resistor tolerance > 1 % when using two-60-ohm + 220 pF low-pass termination (causes corner-frequency mismatch and common-mode → differential conversion).",
                ]
            f.setdefault("compliance_failure_modes", [
                {"mode": "Loss-of-signal (LOS) bit corruption", "trigger": "Bus idle / open / short with no failsafe biasing — receiver output indeterminate; UART RX sees framing errors."},
                {"mode": "Bus contention",                       "trigger": "Two drivers enabled at the same time — V_AB undefined; relies on driver short-circuit current limit to avoid damage."},
                {"mode": "Stub reflection",                       "trigger": "L_stub > tr × v × c / 10 — eye closes; BER rises; intermittent failures."},
                {"mode": "Common-mode out-of-range",              "trigger": "GPD pushes common-mode beyond -7 V to +12 V — receiver may not switch correctly; bit errors."},
                {"mode": "Cable impedance mismatch",              "trigger": "Termination R_T ≠ cable Z0 — partial reflections distort eye."},
                {"mode": "Excess unit loading",                    "trigger": "> 32 UL on the bus — driver V_AB drops below 1.5 V; eye closes."},
            ])
            f.setdefault("max_data_rate_constraint",
                "Standard: 10 Mbps at 40 ft. Modern transceivers: up to 40 Mbps at short stubs.")
            f.setdefault("max_cable_length_constraint",
                "4000 ft (1200 m) at 100 kbps with 22 AWG 120-ohm UTP. Rule of thumb: length [m] × "
                "data_rate [bps] < 10^7.")
            f.setdefault("reset_behavior_compliance",
                "Power-on default: DE = LOW (driver tri-stated), RE# = LOW (receiver enabled), bus "
                "held in mark by failsafe biasing; host UART RX sees idle mark = no spurious start bit.")
        _write(p, d)

    # ---------------- L17 channel / signal catalog ----------------
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if p.is_file():
        d = _read(p)
        f = d.setdefault("fields", {})
        if isinstance(f, dict):
            f.setdefault("channels_bus_side_2_wire", [
                {"name": "A (non-inverting)", "direction": "bidirectional (active-driver / tri-state)", "purpose": "Non-inverting differential bus line; when transmitting mark, A is the more positive line of the pair.", "active_levels": "V_A - V_B > +200 mV at receiver → mark; V_A - V_B < -200 mV → space"},
                {"name": "B (inverting)",     "direction": "bidirectional (active-driver / tri-state)", "purpose": "Inverting differential bus line; complementary to A.",                                                       "active_levels": "see V_AB rule above"},
            ])
            f.setdefault("channels_bus_side_4_wire_full_duplex_optional", [
                {"name": "Y (TX +)", "direction": "output (master) / input (slave)", "purpose": "Non-inverting master-to-slaves transmit pair."},
                {"name": "Z (TX -)", "direction": "output (master) / input (slave)", "purpose": "Inverting master-to-slaves transmit pair."},
                {"name": "A (RX +)", "direction": "input (master) / output (slave)", "purpose": "Non-inverting slave-to-master return pair."},
                {"name": "B (RX -)", "direction": "input (master) / output (slave)", "purpose": "Inverting slave-to-master return pair."},
            ])
            f.setdefault("channels_host_side", [
                {"name": "D / DI",  "direction": "input",  "purpose": "Driver input from host UART TX; logic level."},
                {"name": "DE",      "direction": "input",  "purpose": "Driver Enable (active HIGH); when LOW, driver tri-stated."},
                {"name": "RE# (RE)","direction": "input",  "purpose": "Receiver Enable (active LOW); when HIGH, receiver output tri-stated."},
                {"name": "R / RO",  "direction": "output", "purpose": "Receiver output to host UART RX; logic level."},
            ])
            f.setdefault("channels_supply", [
                {"name": "VCC",     "direction": "supply", "purpose": "Transceiver supply (typically 5 V or 3.3 V)."},
                {"name": "GND",     "direction": "supply", "purpose": "Ground reference."},
            ])
            f.setdefault("logical_signal_states", [
                {"name": "mark / idle / logical 1",  "value": "V_AB > +200 mV; receiver R = HIGH"},
                {"name": "space / logical 0",         "value": "V_AB < -200 mV; receiver R = LOW"},
                {"name": "loss-of-signal (LOS)",       "value": "|V_AB| < 200 mV; receiver R indeterminate unless failsafe-biased"},
            ])
            f.setdefault("bus_field_segments", [
                {"name": "ACTIVE_BIT_DOMINANT_TIME", "type": "data bit",       "form": "1 bit time (= 1 / data rate)"},
                {"name": "RISE_FALL_REGION",         "type": "transition",     "form": "tr ns (transceiver-specific)"},
                {"name": "IDLE_BIASED",              "type": "interframe",     "form": "Driver tri-stated; failsafe holds V_AB > +200 mV"},
                {"name": "DE_GUARD_BAND",            "type": "interframe gap", "form": "Software-controlled blank time between DE deassert and DE reassert"},
            ])
            # v0.1.88: upstream UART/AXI synth may pre-fill `channel_counts`
            # with `{channels:0, signals_per_channel:{}, ...}` (AXI-class
            # shape). RS-485's channel_counts shape is dimensional (pair
            # counts / wire counts) and has higher specificity for this
            # ic_name. Force-overwrite.
            _force(f, "channel_counts", {
                "differential_pairs_half_duplex": 1,
                "differential_pairs_full_duplex": 2,
                "wires_bus_half_duplex":          2,
                "wires_bus_full_duplex":          4,
                "wires_host_per_transceiver":     4,
                "wires_supply_per_transceiver":   2,
                "wires_total_minimum_half_duplex_8pin_xcvr": 8,
            })
            # v0.1.88: upstream synth may pre-fill `dependency_graph` with
            # AXI ARVALID/RVALID rule. Force-overwrite the common_rule and
            # add RS-485 data_dependency / failsafe_dependency siblings.
            _force(f, "dependency_graph", {
                "common_rule":   "Single shared differential bus; all nodes monitor V_AB simultaneously; only one driver may be enabled at a time on half-duplex.",
                "data_dependency": "Receiver R reflects current V_AB only when RE# = LOW; D drives V_AB only when DE = HIGH.",
                "failsafe_dependency": "Idle V_AB is held > +200 mV by external R_B divider or by integrated transceiver failsafe biasing.",
            })
            # v0.1.88: upstream synth may pre-fill `handshake_pairs: {}` as
            # an empty placeholder. Force-overwrite with the RS-485 DE/RE#
            # handshake list (which the agent gold has).
            _force(f, "handshake_pairs", [
                {"name": "DE-to-D",   "from": "host MCU",  "to": "transceiver", "rule": "Software asserts DE before clocking the first start bit into D; deasserts DE after the last stop bit + tHOLD."},
                {"name": "RE#-to-R",   "from": "host MCU", "to": "transceiver", "rule": "Software keeps RE# = LOW during receive windows so the host UART sees the bus."},
                {"name": "Driver-arbitration", "from": "software", "to": "all nodes", "rule": "Application protocol (Modbus master / token / TDM) enforces exclusive DE = HIGH on one node at a time."},
            ])
            f.setdefault("ordering_rules", {
                "byte_order_inherited_from_UART": "LSB-first per byte (typical UART setting).",
                "differential_polarity_convention": "Mark = V_A > V_B; Space = V_A < V_B. Drivers and receivers from different vendors all conform to this convention so that interoperable bus operation is preserved.",
            })
        _write(p, d)

    # ---------------- L18 interconnect topology ----------------
    p = gd / "L18_INTERCONNECT_TOPOLOGY.json"
    if p.is_file():
        d = _read(p)
        f = d.setdefault("fields", {})
        if isinstance(f, dict):
            f.setdefault("topology_type",
                "Linear daisy-chained / party-line multipoint differential bus. Drivers, receivers and "
                "transceivers connect to a single main cable trunk via short network stubs.")
            f.setdefault("supported_topologies", [
                {"name": "Half-duplex 2-wire daisy-chain",   "description": "Single twisted-pair trunk; nodes attached by short stubs; one driver active at a time. Used by Modbus RTU, DL/T645, BACnet MS/TP."},
                {"name": "Full-duplex 4-wire daisy-chain",    "description": "Two twisted-pair trunks: one master-to-slaves (Y/Z) and one slaves-to-master (A/B); no DE/RE# arbitration on master."},
                {"name": "Isolated multi-node",                "description": "All transceivers galvanically isolated except one which provides the single-ground reference (Figure 11-3 of SLLA272D)."},
                {"name": "Standard 32-UL bus",                  "description": "Up to 32 unit-load transceivers in the legacy default."},
                {"name": "Reduced-loading 256-node bus",         "description": "1/8 UL transceivers + lightweight failsafe → up to 96 (with 20-UL failsafe overhead) or 256 (raw) nodes."},
                {"name": "Common-mode filtered bus",              "description": "Two 60-ohm series resistors + 220 pF to GND at each cable end; ≤ 1 % tolerance for matched roll-off."},
            ])
            f.setdefault("master_slave_role_summary", [
                {"role": "MASTER",       "description": "A node that initiates communication; in half-duplex it polls slaves serially. In Modbus RTU there is typically one master and many slaves."},
                {"role": "SLAVE",        "description": "A node that responds to the master's polls; never speaks unprompted."},
                {"role": "PEER",         "description": "In token-passing protocols (BACnet MS/TP) any node may become temporary master while holding the token."},
                {"role": "MONITOR / TAP", "description": "Receive-only node attached to the bus for diagnostic or logging; DE permanently LOW."},
            ])
            f.setdefault("interconnect_role",
                "There is no protocol-layer interconnect (no router / bridge defined by RS-485). Long "
                "buses can be extended via RS-485 repeaters or signal isolators (e.g. TI ISO35 family), "
                "each of which terminates and re-drives the bus on the other side.")
            f.setdefault("ordering_guarantees", {
                "within_a_byte": "LSB-first when UART framing is used.",
                "across_bytes":   "Strictly in transmitter-issue order; the bus is FIFO at the physical layer.",
            })
            f.setdefault("memory_vs_peripheral_regions",
                "Not applicable — RS-485 is electrical-only. Higher-level protocol register maps live "
                "in the SoC integration spec.")
            f.setdefault("slave_classification", {
                "polled_target":   "Modbus RTU style — master polls each slave address; slave responds within a deadline.",
                "interrupt_target": "Slave Triggers polled by master scanning interrupt-status registers in upper protocol.",
                "broadcast_target": "Address 0 in Modbus RTU broadcasts to all slaves (no response).",
            })
            f.setdefault("default_signal_values_evidence_tables", [
                "Section 3 Network Topology of SLLA272D (Figures 3-1 and 3-2)",
                "Section 6 Bus Termination and Stub Length (Figure 6-1)",
                "Section 7 Failsafe (Figure 7-1)",
                "Section 11 Grounding and Isolation (Figures 11-1, 11-2, 11-3)",
            ])
            f.setdefault("isolation_topology", {
                "low_GPD":      "Single shared ground via twisted-pair cable; works for benchtop / single-rack systems.",
                "moderate_GPD": "Resistor-bonded ground separation (100-ohm bonding resistors); reduces loop current but residual noise sensitivity.",
                "high_GPD":     "Full galvanic isolation — digital isolator on data + isolated DC/DC on supply at each remote node; multi-kilovolt GPD tolerance.",
            })
            f.setdefault("repeater_extension",
                "Long RS-485 buses are partitioned by RS-485 repeaters that act as termination and "
                "active re-drivers; each repeater segment respects the standard 32-UL / 1200 m / "
                "stub-length budget independently.")
        _write(p, d)

    # ---------------- L19 constraints / PDK (none) ----------------
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if p.is_file():
        d = _read(p)
        f = d.setdefault("fields", {})
        if isinstance(f, dict):
            f.setdefault("constraints_present", False)
            # v0.1.88: force RS-485 notes over any upstream UART/serial pre-fill.
            _force(f, "notes",
                "RS-485 is a wire-level electrical standard; no PDK / SDC / floorplan constraints at "
                "the protocol layer. Per-transceiver fabrication constraints (BCD process, output "
                "stage current limit, ESD diode stacks) live in the vendor's PDK and not in "
                "TIA/EIA-485 nor in SLLA272D. Higher-level controller integration (UART block with "
                "RS-485 wrapper) carries its own SDC at the SoC integration level.")
        _write(p, d)

    # ---------------- L20 DFT (none) ----------------
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if p.is_file():
        d = _read(p)
        f = d.setdefault("fields", {})
        if isinstance(f, dict):
            f.setdefault("dft_present", False)
            # v0.1.88: force RS-485 DFT notes over any upstream pre-fill.
            _force(f, "notes",
                "RS-485 does not specify DFT / scan / BIST — it is purely an electrical interface "
                "standard. Each RS-485 transceiver chip applies its own analog-DFT (driver current "
                "limit ATPG, receiver threshold trim, ESD protection verification) at the silicon "
                "level. System-level diagnostics rely on differential bus probing (scope), TDR for "
                "stub assessment, and higher-level protocol CRC/BCC for application-layer error "
                "detection. SoC-integrated UART blocks with RS-485 wrappers add standard scan "
                "insertion at the integrator level.")
        _write(p, d)

    # ---------------- L21 power intent ----------------
    p = gd / "L21_POWER_INTENT.json"
    if p.is_file():
        d = _read(p)
        f = d.setdefault("fields", {})
        if isinstance(f, dict):
            f.setdefault("power_intent_present", False)
            f.setdefault("low_power_modes_summary", {
                "active_run":       "Transceiver consumes a few mA from VCC = 5 V (or 3.3 V variants); 32 standard-UL transceivers each load the bus.",
                "shutdown_standby": "DE = LOW + RE# = HIGH puts most modern transceivers into a low-power shutdown / standby state (vendor-specific; typically tens of µA).",
                "no_protocol_level_sleep": "RS-485 itself defines no protocol-level sleep / wake-up message — that is layered above by the application protocol.",
            })
            f.setdefault("isolation_supply_partitioning", {
                "robust_long_distance_topology": "Per-node isolated DC/DC converter feeds the local transceiver bus-side supply; digital isolator separates data signals across the isolation barrier; supplies up to 150 Mbps modern isolation devices, 3 V to 5 V regulated outputs.",
                "single_ground_reference":         "When multiple isolated transceivers share a bus, one non-isolated transceiver provides the single-ground reference for the entire bus (Figure 11-3 of SLLA272D).",
            })
            f.setdefault("esd_protection_examples",
                "Modern TI RS-485 transceivers integrate IEC 61000-4-2 / HBM ESD protection from "
                "16 kV to 30 kV on bus pins.")
            f.setdefault("notes",
                "No protocol-level power-domain partitioning. SoC integration spec carries UPF / "
                "power-intent for the on-chip portion (UART block + DE/RE# control). Off-chip "
                "transceiver power management is vendor-specific.")
        _write(p, d)

    # ---------------- L22 verification plan ----------------
    p = gd / "L22_VERIFICATION_PLAN.json"
    if p.is_file():
        d = _read(p)
        f = d.setdefault("fields", {})
        if isinstance(f, dict):
            f.setdefault("verification_plan_present", "implicit")
            if _empty(f.get("verification_categories_derived_from_spec")):
                f["verification_categories_derived_from_spec"] = [
                    "Driver differential output ≥ 1.5 V across 54-ohm load — chip-level DC measurement.",
                    "Receiver differential threshold ±200 mV across -7 V to +12 V common-mode range — chip-level DC sweep.",
                    "Receiver common-mode rejection at both -7 V and +12 V extremes — chip-level test.",
                    "Driver short-circuit current limit (A to B, A to GND, B to GND) — chip-level test.",
                    "32-UL bus loading: connect 32 standard-UL stubs and verify V_AB still ≥ 1.5 V at the driver.",
                    "1/8-UL bus loading: connect 256 fractional-UL nodes (raw) or 96 with 20-UL failsafe overhead.",
                    "Failsafe under open-circuit (cable cut) — receiver R stays HIGH.",
                    "Failsafe under short-circuit (A to B) — receiver R stays HIGH.",
                    "Failsafe under idle-bus (all drivers tri-stated) — receiver R stays HIGH.",
                    "External failsafe biasing — V_AB ≥ 200 mV + V_noise.",
                    "Termination correctness — TDR measurement across the bus.",
                    "Stub-length tolerance — eye-diagram capture at L_stub = (tr/10) × v × c boundary.",
                    "Cable-length vs data-rate region 1 / 2 / 3 — sweep across data rates and lengths.",
                    "Common-mode noise rejection — inject GPD steps within ±7 V.",
                    "Ground-potential difference robustness with isolation — apply multi-kV GPD across isolated transceivers.",
                    "Half-duplex DE / RE# sequencing — verify no spurious start bit on host UART RX during handover.",
                    "Bus contention safety — assert two drivers simultaneously and verify no permanent damage.",
                    "Higher-level protocol conformance (Modbus RTU, DL/T645) run on top of the validated PHY.",
                ]
            # v0.1.88: force RS-485 verification notes over any upstream pre-fill.
            _force(f, "notes",
                "RS-485 is an electrical-only standard; verification is split into (a) chip-level "
                "transceiver electrical conformance per the TIA/EIA-485-A specification points and "
                "(b) system-level cable / termination / isolation / noise tests per the engineering "
                "practices summarized in SLLA272D. Higher-level link-layer compliance (Modbus RTU "
                "CRC, DL/T645 BCC) is verified separately by industry test suites (e.g. Modbus "
                "Conformance Test Tool).")
        _write(p, d)

    # ---------------- L23 security (none) ----------------
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if p.is_file():
        d = _read(p)
        f = d.setdefault("fields", {})
        if isinstance(f, dict):
            f.setdefault("security_requirements_present", False)
            # v0.1.88: force RS-485 security notes over any upstream pre-fill.
            _force(f, "notes",
                "RS-485 (originally 1983; SLLA272D revised 2021) is an electrical-only standard and "
                "defines no confidentiality / integrity / authentication features. All bus traffic is "
                "in plaintext and visible to every node on the bus. Built-in robustness primitives "
                "(differential signaling, common-mode rejection, ESD protection) protect against "
                "accidental noise and electrical hazards, not against intentional tampering. Modern "
                "industrial security on RS-485-based fieldbuses (Modbus RTU with encrypted tunnel, "
                "BACnet/SC, secure DL/T645) is layered ON TOP of the PHY — not part of the RS-485 "
                "standard itself.")
        _write(p, d)


# ---------------------------------------------------------------------------
# Module-level importable detector (lifted from the inline detector in
# phase1_doc_one_shot_runner.py — ORGANIC-20260531). Byte-for-byte the same
# boolean the runner used inline (`_spi_blob` -> `blob`), so behaviour is
# identical; exposing it module-level lets the universal no-misfire guard
# (tests/test_protocol_detector_no_misfire.py) auto-cover this protocol.
# Reads ONLY the spec text `blob` — never a filename or benchmark name.
# ---------------------------------------------------------------------------
def is_rs485(blob: str) -> bool:
    """Content-only `rs485` detector (importable, lifted from the runner)
    WITH a FOREIGN-PRIMARY DEFER (mirrors the ``is_mipi`` doctrine).

    Empty-safe. Reads ONLY ``blob`` (spec text).

    RS-485 is a pure physical-layer (OSI L1) electrical standard, so the
    APPLICATION-LAYER protocols that ride on it (Modbus RTU, DL/T645,
    Profibus DP, BACnet MS/TP, …) document their own RS-485 PHY: a Modbus
    spec legitimately contains ``RS-485 transceiver`` + ``TIA-485`` and
    therefore trips the loose structural branches below. Conversely the
    RS-485 spec only *names* those higher-level protocols incidentally
    ("higher-level standards built ON TOP of RS-485: Modbus RTU, …") and
    NEVER carries their distinctive application-layer signature.

    Guard (general, content-only, no chip/SKU/benchmark literal as detection
    logic — same shape as ``is_mipi``'s pcie/ufs/dp primary defer): if the
    blob's DOMINANT subject is one of those layered protocols, defer (False),
    so the generic RS-485 synth never fires on a layered spec that merely
    documents RS-485 as its underlying wire.

      - Modbus (the application-layer signature the ``is_modbus`` detector
        keys on: a Function Code + PDU framing model, OR the canonical
        register/coil access function names ``Read Holding Registers`` +
        ``Read Coils``, OR a dense ``Modbus`` subject density that an
        RS-485 PHY spec never reaches by merely citing Modbus as one of the
        protocols layered on top).

    Empirically corpus-clean: the real RS-485 benchmark trips NONE of these
    defers (its incidental ``Modbus`` mentions stay well below the density
    floor and it carries no Function-Code/PDU framing model nor the
    register/coil access function names) and stays True; the modbus
    benchmark trips ``modbus_primary`` and is suppressed.
    """
    if not blob:
        return False
    low = blob.lower()

    # --- FOREIGN-PRIMARY DEFER (the blob's true subject is NOT RS-485, it is
    #     an application-layer protocol that merely rides on the RS-485 PHY). ---
    modbus_primary = (
        ("Function Code" in blob and "PDU" in blob
            and "Modbus" in blob)
        or ("Read Holding Registers" in blob and "Read Coils" in blob)
        or (low.count("modbus") >= 60
            and ("rtu" in low or "ascii" in low or "function code" in low)))
    if modbus_primary:
        return False

    return bool(
        ("TI SLLA272" in blob)
        or ("RS-485 Design Guide" in blob)
        or ("SLLA272" in blob and "RS-485" in blob)
        or ("RS-485 transceiver" in blob
            and ("120 Ω" in blob or "120 ohm" in blob.lower()
                 or "32 unit load" in blob.lower()
                 or "TIA/EIA-485" in blob
                 or "TIA-485" in blob)))
