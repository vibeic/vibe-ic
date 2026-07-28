"""FlexRay Communications System protocol synth helper (protocol #49).

ic_class-gated overlay for the FlexRay structural signature: a deterministic,
fault-tolerant, dual-channel (Channel A / Channel B) time-triggered automotive
serial bus at 10 Mbit/s per channel, organized as a periodic communication
cycle made of a TDMA static segment + an FTDMA (minislot) dynamic segment +
symbol window + Network Idle Time (NIT), with a microtick/macrotick/slot/cycle
timing hierarchy, a distributed fault-tolerant clock synchronization (offset +
rate correction via the Fault-Tolerant Midpoint algorithm over sync frames), a
5-byte header frame (Frame ID 11-bit, Payload Length 7-bit, Header CRC 11-bit,
Cycle Count 6-bit, plus reserved/payload-preamble/null/sync/startup indicator
bits), 0..254-byte payload, 24-bit Frame CRC trailer, CAS-based coldstart and
WUP/WUS wakeup, the Communication Controller + Bus Driver + optional Bus
Guardian node structure, BP/BM differential signaling with TxD/TxEN/RxD between
CC and BD, and the POC (Protocol Operation Control) state machine
(DEFAULT_CONFIG / CONFIG / READY / WAKEUP / STARTUP / NORMAL_ACTIVE /
NORMAL_PASSIVE / HALT). Applies the Bosch FlexRay Protocol Specification v2.1A
(ISO 17458) spec-canonical content to L1-L23.

Doctrine — GENERAL not keyword: detection uses canonical STRUCTURAL signatures
(dual channel + static/dynamic segment + communication cycle + macrotick /
microtick + POC states) read from the L-doc / input_doc CONTENT blob only. It
NEVER reads the input-document filename or the benchmark folder name.

Sibling disambiguation — FlexRay vs CAN / CAN-FD / LIN. FlexRay is a different
automotive serial bus from CAN/CAN-FD/LIN. CAN is event-triggered CSMA/CR with
identifier-based bitwise arbitration and bit stuffing, single channel; LIN is a
single-wire single-master/multi-slave polled sub-bus at <=20 kbit/s. Neither
CAN nor LIN has FlexRay's dual channel + TDMA static/dynamic segment +
communication cycle + macrotick/microtick hierarchy + Fault-Tolerant Midpoint
sync. The detector therefore REQUIRES the FlexRay-only structural vocabulary
(channel A/B + static segment + dynamic segment + macrotick) and DEFERS when the
doc is CAN-primary (dominant arbitration / CAN identifier / bit stuffing without
any FlexRay slot/cycle/macrotick terms), so it cannot false-fire on a CAN or LIN
spec.

Public entry: ``apply_flexray_synth(generated_docs_dir, is_flexray,
flexray_ic_name)``. Module-level ``is_flexray(blob)`` is the content-only
detector.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import l_doc_generator_stamp as _stamp


def _empty(v) -> bool:
    return v in (None, {}, []) or (isinstance(v, str) and not v.strip())


def _ensure_dict(d: dict, key: str) -> dict:
    """Return d[key] as a dict, replacing a pre-existing None/empty/non-dict.

    A plain setdefault on a key whose existing value is None is a no-op and
    would leave the subkey synth skipped, so coerce to an empty dict first.
    """
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

# Canonical FlexRay facts (Bosch FlexRay Protocol Spec v2.1A / ISO 17458).
_DATA_RATES_MBPS = [2.5, 5, 10]            # configurable gross bit rates
_MAX_DATA_RATE_MBPS = 10
_CHANNELS = ["Channel A", "Channel B"]
_CYCLE_COUNTER_BITS = 6                     # 0..63
_FRAME_ID_BITS = 11                         # 1..2047
_PAYLOAD_LENGTH_BITS = 7                    # 0..127 words
_HEADER_CRC_BITS = 11
_FRAME_CRC_BITS = 24
_HEADER_BYTES = 5
_MAX_PAYLOAD_BYTES = 254
_POC_STATES = [
    "DEFAULT_CONFIG", "CONFIG", "READY", "WAKEUP", "STARTUP",
    "NORMAL_ACTIVE", "NORMAL_PASSIVE", "HALT",
]


def is_flexray(blob: str) -> bool:
    """Content-only FlexRay detector with a CAN/CAN-FD/LIN sibling MUTEX.

    Fire on the FlexRay structural signature: dual channel (Channel A / B) +
    a static segment + a dynamic segment + the communication cycle + the
    macrotick/microtick timing hierarchy (and/or the FlexRay name + POC). Defer
    if the doc is CAN-primary (identifier-based arbitration / bit stuffing
    vocabulary with NO FlexRay slot/cycle/macrotick terms), so a CAN or LIN
    spec cannot false-fire. Reads ONLY the spec text `blob` — never a filename
    or benchmark name.
    """
    if not blob:
        return False
    low = blob.lower()

    # FlexRay-only structural tokens (absent from CAN/CAN-FD/LIN).
    dual_channel = (
        ("channel a" in low and "channel b" in low)
        or "dual channel" in low
        or ("dual-channel" in low)
    )
    static_seg = "static segment" in low
    dynamic_seg = "dynamic segment" in low
    comm_cycle = "communication cycle" in low
    macro_micro = ("macrotick" in low or "microtick" in low)
    tdma = ("tdma" in low or "minislot" in low or "ftdma" in low)
    poc = (
        "normal_active" in low
        or ("protocol operation control" in low)
        or ("poc" in low and "normal" in low)
    )
    name_token = "flexray" in low

    flexray_structure = (
        (static_seg and dynamic_seg)
        and (comm_cycle or tdma)
        and (macro_micro or dual_channel)
    )

    # Sibling MUTEX: a CAN-primary doc keys on bitwise arbitration / CAN
    # identifier / bit stuffing. If those dominate AND none of the FlexRay
    # slot/cycle/macrotick structure is present, defer (do NOT fire).
    can_primary = (
        ("bit stuffing" in low or "bitwise arbitration" in low
         or "can identifier" in low or "arbitration field" in low
         or ("csma" in low))
        and not (static_seg or dynamic_seg or macro_micro
                 or comm_cycle or name_token)
    )
    if can_primary:
        return False

    return bool(
        flexray_structure
        or (name_token and (static_seg or dynamic_seg or macro_micro or poc))
        or (name_token and dual_channel and tdma)
    )


def apply_flexray_synth(generated_docs_dir: Path, is_flexray_flag: bool,
                        flexray_ic_name: Optional[str]) -> None:
    """Apply FlexRay v2.1A synth when the FlexRay signature matched."""
    if not is_flexray_flag:
        return
    gd = Path(generated_docs_dir)

    # --- Force ic_name across ALL 24 docs FIRST (main + fields docs). ---
    if flexray_ic_name is not None:
        for n in _MAIN_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                d["ic_name"] = flexray_ic_name
                _write(q, d)
        for n in _FIELDS_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                f = _ensure_dict(d, "fields")
                f["ic_name"] = flexray_ic_name
                d["ic_name"] = flexray_ic_name
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
# L1 — FlexRay datasheet header + headline facts.
# ----------------------------------------------------------------------
def _l1(gd: Path) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    d["document_title"] = "FlexRay Communications System Protocol Specification"
    d["version"] = "Version 2.1 Revision A (Bosch v2.1A; ISO 17458)"
    d["revised_date"] = "2005 (v2.1A); ISO 17458 (2013)"
    d["manufacturer"] = "FlexRay Consortium"
    d["copyright"] = "© FlexRay Consortium"
    d["abstract"] = (
        "FlexRay is a deterministic, fault-tolerant, high-speed serial "
        "communication system for advanced automotive in-vehicle networking "
        "(x-by-wire, advanced powertrain, chassis control). It runs at up to "
        "10 Mbit/s per channel over two independent channels (Channel A and "
        "Channel B) that may be used for redundancy or doubled bandwidth. "
        "Media access is time-triggered: each periodic communication cycle "
        "contains a TDMA static segment (fixed-length static slots, "
        "collision-free, deterministic) plus an optional FTDMA / minislot "
        "dynamic segment (priority/event-triggered), an optional symbol "
        "window, and the Network Idle Time (NIT). A global, distributed, "
        "fault-tolerant clock synchronization (offset + rate correction using "
        "the Fault-Tolerant Midpoint algorithm over sync frames) gives every "
        "node a common time base without a central master. A node consists of "
        "a Communication Controller (CC), one Bus Driver (BD) per channel, and "
        "an optional Bus Guardian (BG).")
    d["keywords"] = [
        "FlexRay", "Channel A", "Channel B", "dual channel", "time-triggered",
        "TDMA", "static segment", "dynamic segment", "minislot", "FTDMA",
        "communication cycle", "macrotick", "microtick", "cycle counter",
        "clock synchronization", "offset correction", "rate correction",
        "Fault-Tolerant Midpoint", "Communication Controller", "Bus Driver",
        "Bus Guardian", "coldstart", "CAS", "wakeup", "WUP", "WUS",
        "Frame ID", "Header CRC", "Frame CRC", "POC", "10 Mbit/s", "BP", "BM",
    ]
    d["external_pins"] = [
        "BP / BM (Channel A): differential bus pair (Bus Plus / Bus Minus) for "
        "Channel A",
        "BP / BM (Channel B): differential bus pair for Channel B (optional; a "
        "node may connect to one or both channels)",
        "TxD (CC -> Bus Driver): transmit serial data",
        "TxEN (CC -> Bus Driver): transmit enable (gates the bus driver so the "
        "node only drives during its own slots)",
        "RxD (Bus Driver -> CC): received serial data recovered from the bus",
        "Controller Host Interface (CHI): CC <-> host processor control / data "
        "interface",
        "Power and ground; optional Bus Guardian control",
    ]
    d["supported_channels"] = list(_CHANNELS)
    d["supported_data_rates_Mbps"] = list(_DATA_RATES_MBPS)
    d["max_data_rate_Mbps"] = _MAX_DATA_RATE_MBPS
    d["modes_of_operation"] = [
        {"name": "Static segment (TDMA)",
         "access": "time-triggered, collision-free",
         "note": "Equal-length static slots; one configured sender per slot "
                 "per channel; Frame ID = slot number; deterministic bounded "
                 "latency; carries periodic safety-critical data and the sync "
                 "frames."},
        {"name": "Dynamic segment (FTDMA / minislotting)",
         "access": "event-triggered, priority-based",
         "note": "Minislots in priority order (lower Frame ID = higher "
                 "priority = earlier minislot); on-demand bandwidth for "
                 "sporadic / bursty data."},
        {"name": "Symbol window",
         "access": "network-management symbols",
         "note": "Optional; carries CAS / MTS / WUS symbols."},
        {"name": "Network Idle Time (NIT)",
         "access": "communication-free",
         "note": "Mandatory; clock-sync calculation and offset correction "
                 "applied here; no frames sent."},
    ]
    d["key_features"] = [
        "Deterministic fault-tolerant automotive serial bus; up to 10 Mbit/s "
        "per channel.",
        "Two independent channels (Channel A / Channel B) for redundancy or "
        "doubled bandwidth (up to 20 Mbit/s aggregate).",
        "Time-triggered TDMA static segment: fixed-length static slots, "
        "collision-free, bounded latency, deterministic.",
        "FTDMA (minislot) dynamic segment: priority-based event-triggered "
        "on-demand bandwidth.",
        "Periodic communication cycle = static segment + dynamic segment + "
        "symbol window + Network Idle Time (NIT); cycles counted by a 6-bit "
        "cycle counter (0..63).",
        "Timing hierarchy microtick -> macrotick -> slot -> cycle; macrotick "
        "is the synchronized cluster-wide time unit.",
        "Distributed fault-tolerant clock synchronization: offset correction "
        "(phase) + rate correction (frequency) via the Fault-Tolerant Midpoint "
        "(FTM) algorithm over sync frames; no central master.",
        "Frame: 5-byte header (Frame ID 11-bit, Payload Length 7-bit, Header "
        "CRC 11-bit, Cycle Count 6-bit + indicator bits) + 0..254-byte payload "
        "+ 24-bit Frame CRC trailer.",
        "Coldstart/startup via Collision Avoidance Symbol (CAS) + startup "
        "frames; wakeup via Wakeup Pattern (WUP) of Wakeup Symbols (WUS).",
        "Node = Communication Controller (CC) + Bus Driver (BD) per channel + "
        "optional Bus Guardian (BG); CC<->BD via TxD/TxEN/RxD; BP/BM "
        "differential bus.",
        "POC (Protocol Operation Control) state machine: DEFAULT_CONFIG, "
        "CONFIG, READY, WAKEUP, STARTUP, NORMAL_ACTIVE, NORMAL_PASSIVE, HALT.",
        "NRZ coding, 8x oversampling with majority voting; per-byte Byte Start "
        "Sequence re-strobing instead of bit stuffing.",
    ]
    d["topology_summary"] = (
        "Per channel: passive bus (linear multidrop), passive star, or active "
        "star (active star couplers regenerate the signal and isolate "
        "branches; cascaded active stars are permitted within timing limits). "
        "A node may be attached to one or both channels.")
    d["use_cases"] = [
        "X-by-wire: brake-by-wire, steer-by-wire (safety-critical, "
        "deterministic, redundant)",
        "Advanced powertrain and engine control requiring bounded latency",
        "Chassis and active suspension control",
        "Driver-assistance / sensor fusion backbones needing high bandwidth",
        "Redundant safety buses where dual-channel fault tolerance is "
        "required",
    ]
    d["revision_history"] = [
        {"version": "2.0", "date": "2004",
         "description": "FlexRay Communications System Protocol Specification "
                        "2.0: dual-channel time-triggered TDMA, communication "
                        "cycle, clock sync, startup/wakeup."},
        {"version": "2.1 Rev A", "date": "2005",
         "description": "FlexRay v2.1A: refined frame format, startup / "
                        "coldstart, clock synchronization, and electrical / "
                        "physical-layer definitions; the widely deployed "
                        "automotive revision."},
        {"version": "ISO 17458-1..5", "date": "2013",
         "description": "International standardization of FlexRay "
                        "(communication system, data link layer, physical "
                        "layer, conformance test) based on the Consortium "
                        "specification."},
    ]
    d["overview"] = (
        "FlexRay is a deterministic, fault-tolerant automotive communication "
        "system designed for safety-critical distributed control where "
        "event-triggered CAN and low-speed LIN are insufficient. Each of its "
        "two channels (Channel A and Channel B) runs at up to 10 Mbit/s. Time "
        "is globally synchronized: a periodic communication cycle is divided "
        "into a TDMA static segment of equal-length static slots (one "
        "configured sender per slot, collision-free, deterministic), an "
        "optional FTDMA dynamic segment of minislots (priority-based, "
        "event-triggered), an optional symbol window, and the mandatory "
        "Network Idle Time during which clock synchronization is computed. The "
        "time hierarchy runs microtick -> macrotick -> slot -> cycle, with the "
        "macrotick as the synchronized cluster-wide unit and a 6-bit cycle "
        "counter (0..63). A distributed fault-tolerant clock synchronization "
        "applies offset (phase) and rate (frequency) corrections derived from "
        "sync frames using the Fault-Tolerant Midpoint algorithm, so the "
        "cluster shares one time base with no central master. Frames carry a "
        "5-byte header (Frame ID 11-bit, Payload Length 7-bit, Header CRC "
        "11-bit, Cycle Count 6-bit, plus reserved/payload-preamble/null/sync/"
        "startup indicator bits), 0..254 bytes of payload, and a 24-bit Frame "
        "CRC trailer. Nodes wake a channel with a Wakeup Pattern (WUP) and "
        "establish the schedule via the coldstart procedure (Collision "
        "Avoidance Symbol + startup frames). The Communication Controller's "
        "behavior is governed by the POC state machine (DEFAULT_CONFIG, "
        "CONFIG, READY, WAKEUP, STARTUP, NORMAL_ACTIVE, NORMAL_PASSIVE, "
        "HALT).")
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
        "Deterministic, fault-tolerant, dual-channel (Channel A / Channel B) "
        "time-triggered automotive serial bus at up to 10 Mbit/s per channel. "
        "Media access is TDMA in the static segment and FTDMA (minislotting) "
        "in the dynamic segment, within a periodic communication cycle.")
    po["duplex"] = (
        "Half-duplex per channel (a single differential bus pair BP/BM is "
        "shared; only the slot owner drives at a time). Two channels operate "
        "in parallel for redundancy or doubled bandwidth.")
    po["synchronous_serial"] = False
    po["source_synchronous"] = False
    po["embedded_clock"] = True
    po["forwarded_clock"] = False
    po["encoding"] = (
        "NRZ (Non-Return-to-Zero). No separate clock wire; the receiver "
        "oversamples each bit 8x and majority-votes a 5-sample window, and "
        "re-strobes bit timing on each Byte Start Sequence (BSS). FlexRay does "
        "NOT use bit stuffing.")
    po["modulation"] = "Differential NRZ (two-level) on BP/BM."
    po["data_rates_Mbps"] = list(_DATA_RATES_MBPS)
    po["max_data_rate_Mbps"] = _MAX_DATA_RATE_MBPS
    po["channels"] = list(_CHANNELS)
    po["bit_time_ns_at_10Mbps"] = 100
    po["samples_per_bit"] = 8
    po["voting_window_samples"] = 5
    po["communication_cycle_segments"] = [
        "Static segment (TDMA, mandatory)",
        "Dynamic segment (FTDMA / minislotting, optional)",
        "Symbol window (optional)",
        "Network Idle Time (NIT, mandatory)",
    ]
    po["cycle_counter_bits"] = _CYCLE_COUNTER_BITS
    po["timing_hierarchy"] = ["microtick", "macrotick", "slot", "cycle"]
    po["clock_synchronization"] = (
        "Distributed fault-tolerant: offset correction (phase, computed in the "
        "NIT and applied per cycle) + rate correction (frequency, computed "
        "over an even/odd cycle pair) using the Fault-Tolerant Midpoint (FTM) "
        "algorithm over received sync frames; no central master.")
    po["node_structure"] = (
        "Host + Communication Controller (CC) + one Bus Driver (BD) per "
        "channel + optional Bus Guardian (BG).")
    d["functional_requirements"] = [
        {"id": "FR-CHAN-01", "text": "FlexRay provides two independent "
         "channels (Channel A and Channel B), each a differential BP/BM bus at "
         "up to 10 Mbit/s, usable for redundancy or doubled bandwidth. A node "
         "may connect to one or both channels."},
        {"id": "FR-CYCLE-02", "text": "Communication is organized into a "
         "periodic communication cycle composed, in time order, of a static "
         "segment, an optional dynamic segment, an optional symbol window, and "
         "a mandatory Network Idle Time (NIT). A 6-bit cycle counter counts "
         "cycles 0..63."},
        {"id": "FR-STATIC-03", "text": "The static segment is a TDMA region of "
         "equally-sized static slots. Each static slot is assigned to at most "
         "one sending node per channel; the Frame ID equals the static slot "
         "number; transmissions are collision-free and deterministic."},
        {"id": "FR-DYN-04", "text": "The dynamic segment uses FTDMA "
         "(minislotting): minislots are traversed in Frame-ID priority order "
         "(lower Frame ID = higher priority = earlier minislot); a sender with "
         "data holds the minislot counter for its frame, otherwise the "
         "minislot elapses."},
        {"id": "FR-TIME-05", "text": "Time is a hierarchy microtick -> "
         "macrotick -> slot -> cycle. The macrotick is an integer number of "
         "microticks adjusted by rate correction so it has the same duration "
         "cluster-wide; node time is the pair {cycle counter, macrotick}."},
        {"id": "FR-SYNC-06", "text": "A distributed fault-tolerant clock "
         "synchronization applies offset correction (phase) and rate "
         "correction (frequency) computed from received sync frames using the "
         "Fault-Tolerant Midpoint algorithm; offset correction is applied "
         "during the NIT. At least two sync nodes are required."},
        {"id": "FR-FRAME-07", "text": "A frame has a 5-byte header (reserved "
         "bit, payload-preamble, null, sync, startup indicators; Frame ID "
         "11-bit; Payload Length 7-bit; Header CRC 11-bit; Cycle Count 6-bit), "
         "a 0..254-byte payload, and a 24-bit Frame CRC trailer."},
        {"id": "FR-WAKE-08", "text": "A node wakes a channel by transmitting a "
         "Wakeup Pattern (WUP), a configured number of Wakeup Symbols (WUS); "
         "wakeup is performed one channel at a time."},
        {"id": "FR-START-09", "text": "Startup (coldstart): a leading "
         "coldstart node transmits the Collision Avoidance Symbol (CAS) then "
         "startup frames (sync frames with the startup indicator); following "
         "nodes integrate to the schedule; at least two coldstart nodes must "
         "agree before normal operation."},
        {"id": "FR-POC-10", "text": "The Communication Controller behavior is "
         "governed by the POC state machine: DEFAULT_CONFIG, CONFIG, READY, "
         "WAKEUP, STARTUP, NORMAL_ACTIVE, NORMAL_PASSIVE, HALT."},
        {"id": "FR-PHY-11", "text": "The physical interface is BP/BM "
         "differential NRZ; the CC connects to each Bus Driver via TxD, TxEN, "
         "and RxD; supported topologies are passive bus, passive star, and "
         "active star."},
        {"id": "FR-GUARD-12", "text": "An optional Bus Guardian independently "
         "enforces the schedule, permitting transmission only in the node's "
         "assigned slots to prevent babbling-idiot faults."},
    ]
    d["error_response_conditions"] = [
        "Header CRC (11-bit) mismatch — header is corrupt; the frame is "
        "rejected.",
        "Frame CRC (24-bit) mismatch — whole frame corrupt; the frame is "
        "discarded.",
        "Null Frame Indicator set — the slot was transmitted but carries no "
        "valid application data.",
        "Too few valid sync frames — clock-sync status degrades the node from "
        "NORMAL_ACTIVE to NORMAL_PASSIVE (and ultimately HALT).",
        "Coldstart / integration failure — fewer than two coldstart nodes "
        "agree; the cluster does not reach normal operation.",
        "Transmission outside an assigned slot — blocked by the Bus Guardian "
        "(babbling-idiot protection).",
    ]
    d["compliance_requirements"] = [
        "Dual-channel BP/BM differential NRZ physical layer at the configured "
        "rate (<=10 Mbit/s).",
        "Periodic communication cycle: static segment + optional dynamic "
        "segment + optional symbol window + mandatory NIT; 6-bit cycle "
        "counter.",
        "TDMA static slots (Frame ID = slot number) and FTDMA minislot dynamic "
        "segment.",
        "Timing hierarchy microtick/macrotick/slot/cycle with a synchronized "
        "macrotick.",
        "Distributed fault-tolerant clock synchronization (offset + rate, "
        "Fault-Tolerant Midpoint over sync frames).",
        "Frame format: 5-byte header (11-bit Frame ID, 7-bit Payload Length, "
        "11-bit Header CRC, 6-bit Cycle Count + indicator bits), 0..254-byte "
        "payload, 24-bit Frame CRC.",
        "Coldstart (CAS + startup frames, >=2 coldstart nodes) and wakeup "
        "(WUP/WUS).",
        "POC state machine (DEFAULT_CONFIG/CONFIG/READY/WAKEUP/STARTUP/"
        "NORMAL_ACTIVE/NORMAL_PASSIVE/HALT).",
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
        "Time-triggered TDMA + FTDMA frame protocol. The host hands frame data "
        "to the Communication Controller over the CHI; the CC schedules the "
        "frame into its assigned static slot (TDMA) or its priority minislot "
        "(FTDMA dynamic), builds the frame (5-byte header + payload + 24-bit "
        "Frame CRC), and the Bus Driver serializes it as differential NRZ on "
        "BP/BM at up to 10 Mbit/s. The receiver oversamples 8x, majority-votes, "
        "re-strobes per Byte Start Sequence, and checks the Header and Frame "
        "CRCs.")
    d["channels"] = [
        {"name": "Channel A (BP/BM)",
         "direction": "half-duplex differential bus",
         "description": "Differential NRZ automotive bus at up to 10 Mbit/s; "
         "shared TDMA/FTDMA media access; one slot owner drives at a time."},
        {"name": "Channel B (BP/BM)",
         "direction": "half-duplex differential bus",
         "description": "Independent second channel; redundancy or doubled "
         "bandwidth. A node may use one or both channels."},
        {"name": "TxD / TxEN / RxD (CC <-> Bus Driver)",
         "direction": "digital CC-to-BD interface",
         "description": "TxD = transmit data, TxEN = transmit enable (gates "
         "the bus driver to the node's own slots), RxD = received data."},
    ]
    d["communication_cycle"] = {
        "segments": [
            "Static segment (TDMA, mandatory)",
            "Dynamic segment (FTDMA / minislotting, optional)",
            "Symbol window (optional)",
            "Network Idle Time (NIT, mandatory)",
        ],
        "cycle_counter_bits": _CYCLE_COUNTER_BITS,
        "cycle_counter_range": "0..63",
        "note": "All segment boundaries are defined in macroticks and are "
                "statically configured identically across the cluster.",
    }
    d["media_access"] = {
        "static_segment": "TDMA — each static slot owned by one configured "
        "node per channel; Frame ID = slot number; collision-free, "
        "deterministic; the slot counter advances every static slot.",
        "dynamic_segment": "FTDMA / minislotting — minislots traversed in "
        "Frame-ID priority order (lower ID = higher priority); a transmitting "
        "node holds the minislot counter for its frame, otherwise the minislot "
        "elapses.",
    }
    d["frame_format"] = {
        "header_bytes": _HEADER_BYTES,
        "header_fields": {
            "reserved_bit": 1,
            "payload_preamble_indicator_bit": 1,
            "null_frame_indicator_bit": 1,
            "sync_frame_indicator_bit": 1,
            "startup_frame_indicator_bit": 1,
            "frame_id_bits": _FRAME_ID_BITS,
            "payload_length_bits": _PAYLOAD_LENGTH_BITS,
            "header_crc_bits": _HEADER_CRC_BITS,
            "cycle_count_bits": _CYCLE_COUNTER_BITS,
        },
        "frame_id_range": "1..2047 (0 reserved); in static segment Frame ID = "
                          "slot number",
        "payload_length_range_words": "0..127 (16-bit words)",
        "payload_bytes_range": "0..254 (even)",
        "trailer_frame_crc_bits": _FRAME_CRC_BITS,
        "framing": "TSS (Transmission Start Sequence) + FSS (Frame Start "
                   "Sequence) + per-byte BSS (Byte Start Sequence) + FES "
                   "(Frame End Sequence); no bit stuffing.",
    }
    d["frame_indicator_bits"] = [
        "Reserved bit (transmitted as 0)",
        "Payload Preamble Indicator (Network Management Vector in static / "
        "Message ID in dynamic)",
        "Null Frame Indicator (slot transmitted but no valid application "
        "data)",
        "Sync Frame Indicator (frame used by clock synchronization; static "
        "segment only)",
        "Startup Frame Indicator (frame used during coldstart; always also a "
        "sync frame)",
    ]
    d["crc"] = {
        "header_crc_bits": _HEADER_CRC_BITS,
        "header_crc_coverage": "sync indicator, startup indicator, Frame ID, "
                               "Payload Length",
        "frame_crc_bits": _FRAME_CRC_BITS,
        "frame_crc_coverage": "entire header + payload",
        "channel_specific_crc_init": True,
    }
    d["symbols"] = [
        {"name": "CAS", "full": "Collision Avoidance Symbol",
         "use": "Sent by the leading coldstart node before startup frames to "
                "claim an idle channel."},
        {"name": "MTS", "full": "Media access Test Symbol",
         "use": "Network-management test symbol in the symbol window."},
        {"name": "WUS / WUP", "full": "Wakeup Symbol / Wakeup Pattern",
         "use": "WUP = repeated WUS; wakes a channel before communication."},
    ]
    d["addressing"] = {
        "note": "FlexRay is slot/Frame-ID addressed, not node-address "
                "addressed: a frame is identified by its Frame ID (11-bit) and "
                "the slot/cycle in which it appears, not by a destination "
                "address. In the static segment Frame ID = slot number.",
        "frame_id_bits": _FRAME_ID_BITS,
    }
    d["byte_oriented"] = True
    d["frame_oriented"] = True
    d["bit_stuffing"] = False
    d["arbitration_based"] = False
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
        "FlexRay defines a Communication Controller configuration parameter "
        "set (programmed by the host in the CONFIG state via the CHI) rather "
        "than a fixed memory-mapped register map; the parameter names below "
        "are the canonical FlexRay g* (cluster-global), p* (node-local), and "
        "v* (status) parameters. A vendor CC exposes them as host-accessible "
        "registers.")
    d["register_access"] = {
        "transport": "Controller Host Interface (CHI) between host and CC",
        "purpose": "Configure schedule, slot assignment, timing, sync/"
                   "coldstart role, CRC init; read protocol status.",
        "configured_in_state": "CONFIG (POC)",
    }
    d["register_groups"] = [
        {"group": "Cluster-global timing (g*)", "fields": [
            "gdCycle (communication cycle duration)",
            "gMacroPerCycle (macroticks per cycle)",
            "gdMacrotick (macrotick duration)",
            "gNumberOfStaticSlots", "gdStaticSlot (static slot length, MT)",
            "gNumberOfMinislots", "gdMinislot (minislot length, MT)",
            "gPayloadLengthStatic (static payload, words)",
            "gdNIT (Network Idle Time, MT)", "gColdstartAttempts"]},
        {"group": "Node-local parameters (p*)", "fields": [
            "pMicroPerCycle (microticks per cycle, node-local)",
            "pKeySlotId (slot for this node's sync/startup key frame)",
            "pKeySlotUsedForSync (is a sync node)",
            "pKeySlotUsedForStartup (is a coldstart node)",
            "pdWakeupSymbol* (wakeup symbol timing)"]},
        {"group": "Status variables (v*)", "fields": [
            "vCycleCounter (current cycle counter 0..63)",
            "vPOC!State (current POC state)",
            "clock-sync error / correction status",
            "slot counter, macrotick counter"]},
    ]
    d["frame_protocol_fields"] = {
        "frame_id_bits": _FRAME_ID_BITS,
        "payload_length_bits": _PAYLOAD_LENGTH_BITS,
        "header_crc_bits": _HEADER_CRC_BITS,
        "cycle_count_bits": _CYCLE_COUNTER_BITS,
        "frame_crc_bits": _FRAME_CRC_BITS,
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
        "Each channel is a differential pair (BP = Bus Plus, BM = Bus Minus) "
        "carrying Non-Return-to-Zero (NRZ) signaling at up to 10 Mbit/s "
        "(nominal 100 ns bit time). The idle bus rests in a recessive/idle "
        "differential state; an active driver forces the Data_0 / Data_1 "
        "differential states. There is no separate clock wire — bit timing is "
        "recovered by 8x oversampling with a 5-sample majority vote and "
        "re-strobed on each Byte Start Sequence. The Bus Driver converts the "
        "CC's TxD/TxEN into the BP/BM bus and the bus back into RxD.")
    d["modulation"] = "Differential NRZ (two-level) on BP/BM."
    d["clocking"] = (
        "No forwarded/separate clock wire; the receiver derives bit timing "
        "from the data stream by 8x oversampling and per-byte (BSS) "
        "re-strobing. The global cluster time is maintained by clock "
        "synchronization, not by a transmitted clock.")
    d["transmitter_specs_canonical"] = {
        "data_rates_Mbps": list(_DATA_RATES_MBPS),
        "max_data_rate_Mbps": _MAX_DATA_RATE_MBPS,
        "modulation": "NRZ",
        "signaling": "differential (BP/BM)",
        "line_encoding": "NRZ; no bit stuffing (per-byte BSS re-strobing)",
        "bus_states": "Idle/recessive vs Data_0 / Data_1 differential",
        "drive_gating": "TxEN enables the driver only during the node's "
                        "assigned slot(s)",
    }
    d["receiver_specs_canonical"] = {
        "samples_per_bit": 8,
        "voting_window_samples": 5,
        "strobing": "Resynchronizes the bit strobe on the falling edge at the "
                    "start of each Byte Start Sequence (BSS).",
        "channels_monitored": "Both channels (A and B) where connected; a "
                              "valid frame may be taken from either channel.",
    }
    d["topologies"] = {
        "passive_bus": "Linear multidrop passive bus.",
        "passive_star": "Passive star coupling.",
        "active_star": "Active star coupler(s) regenerate the signal and "
                       "isolate branches; cascaded active stars allowed within "
                       "timing limits.",
    }
    d["bit_time_ns_at_10Mbps"] = 100
    d["channels"] = list(_CHANNELS)
    d["encoding_role_in_analog"] = (
        "FlexRay uses NRZ with oversampling-based clock recovery rather than a "
        "DC-balancing line code. Robustness comes from the per-byte Byte Start "
        "Sequence re-strobing (bounding accumulated phase error over a frame) "
        "and from the global clock synchronization; integrity comes from the "
        "11-bit Header CRC and 24-bit Frame CRC, not from a line code.")
    _write(p, d)


# ----------------------------------------------------------------------
# L6 — control logic / POC + per-cycle FSMs.
# ----------------------------------------------------------------------
def _l6(gd: Path) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["fsm_states_poc"] = [
        {"name": "DEFAULT_CONFIG", "description": "Entered after reset / "
         "power-up; the Communication Controller is unconfigured."},
        {"name": "CONFIG", "description": "The host configures the CC: "
         "schedule, slot assignment, timing parameters, sync/coldstart role, "
         "CRC initialization."},
        {"name": "READY", "description": "Configuration complete; the CC "
         "awaits a command to start wakeup or startup."},
        {"name": "WAKEUP", "description": "The CC performs the wakeup "
         "procedure (transmit/detect the Wakeup Pattern) to wake the "
         "channel(s)."},
        {"name": "STARTUP", "description": "The CC runs coldstart / "
         "integration (CAS, startup frames, schedule integration, initial "
         "clock synchronization)."},
        {"name": "NORMAL_ACTIVE", "description": "Fully operational steady "
         "state: the node follows the TDMA schedule, sends/receives frames, "
         "and contributes to and follows clock synchronization."},
        {"name": "NORMAL_PASSIVE", "description": "Degraded synchronization "
         "status (e.g. too few sync frames): the node still receives and keeps "
         "time but does not actively transmit until it recovers."},
        {"name": "HALT", "description": "Communication stopped (fatal error or "
         "host halt command); the CC leaves the schedule."},
    ]
    d["fsm_states_media_access"] = [
        {"name": "STATIC_SLOT", "description": "TDMA: on each static slot the "
         "slot owner transmits its frame; the slot counter advances every "
         "static slot regardless of whether a frame was sent."},
        {"name": "DYNAMIC_MINISLOT", "description": "FTDMA: the minislot "
         "counter advances; the node whose dynamic Frame ID matches the "
         "current minislot may transmit, holding the counter for its frame."},
        {"name": "SYMBOL_WINDOW", "description": "Optional segment for "
         "network-management symbols (CAS / MTS / WUS)."},
        {"name": "NIT", "description": "Network Idle Time: no frames; "
         "clock-sync calculation and offset correction applied."},
    ]
    d["fsm_states_clock_sync"] = [
        {"name": "MEASURE", "description": "Measure arrival timing of received "
         "sync frames on both channels during the static segment."},
        {"name": "OFFSET_CORRECTION", "description": "Compute the phase "
         "correction using the Fault-Tolerant Midpoint algorithm; apply it "
         "during the NIT for the next cycle."},
        {"name": "RATE_CORRECTION", "description": "Compute the frequency "
         "correction over an even/odd cycle pair and apply it gradually "
         "(microticks per cycle)."},
    ]
    d["fsm_hints"] = {
        "trigger": "Reset -> DEFAULT_CONFIG. Host configures (CONFIG) then "
        "READY; a start command drives WAKEUP then STARTUP; successful "
        "coldstart/integration reaches NORMAL_ACTIVE.",
        "rule": "Only sync frames (sync indicator set, static segment, "
        "configured sync nodes) feed clock synchronization; at least two sync "
        "nodes and two coldstart nodes are required.",
        "abort": "Insufficient valid sync frames degrade NORMAL_ACTIVE -> "
        "NORMAL_PASSIVE -> HALT; a fatal error or host halt forces HALT.",
    }
    d["anti_deadlock_rule"] = (
        "The TDMA schedule is collision-free by construction (one configured "
        "sender per static slot); the optional Bus Guardian enforces it, "
        "preventing a babbling node from holding the bus. The FTDMA minislot "
        "counter always advances when a minislot is empty, so the dynamic "
        "segment cannot stall.")
    d["exit_from_reset_or_poweron"] = (
        "On reset the CC enters DEFAULT_CONFIG. The host moves it through "
        "CONFIG (load schedule/timing/role) to READY, then commands WAKEUP "
        "(WUP/WUS) and STARTUP (CAS + startup frames + integration + initial "
        "clock sync); once >=2 coldstart nodes agree and synchronization is "
        "running the node reaches NORMAL_ACTIVE.")
    d["default_ready_state_recommendation"] = {
        "TX_idle": "TxEN de-asserted (driver off) outside the node's assigned "
        "slot; bus left in the idle/recessive differential state.",
        "TX_active": "Assert TxEN and drive TxD only during the assigned "
        "static slot or won dynamic minislot.",
        "RX_idle": "Continuously sample RxD on both channels; accept frames "
        "passing Header and Frame CRC.",
    }
    d["configurations"] = [
        {"name": "Single-channel node", "description": "Connected to Channel A "
         "or B only."},
        {"name": "Dual-channel redundant", "description": "Connected to both "
         "channels; same frame on A and B for fault tolerance."},
        {"name": "Dual-channel bandwidth", "description": "Connected to both "
         "channels carrying different traffic for doubled bandwidth."},
    ]
    d["timing_dependency_rule"] = (
        "Every node derives the global time {cycle counter, macrotick} from "
        "clock synchronization; all slot and segment boundaries are fixed in "
        "macroticks and identical cluster-wide. The macrotick (an integer "
        "number of microticks adjusted by rate correction) is the synchronized "
        "unit, so slot timing is deterministic across the cluster.")
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
        {"name": "POC state (vPOC!State)", "purpose": "The current Protocol "
         "Operation Control state is host-readable for bring-up and fault "
         "diagnosis."},
        {"name": "Cycle / macrotick / slot counters", "purpose": "vCycleCounter "
         "(0..63), the macrotick counter, and the slot counter expose the "
         "node's position in the schedule."},
        {"name": "Clock-sync status", "purpose": "Offset/rate correction "
         "values and sync-frame counts indicate synchronization health and "
         "drive NORMAL_ACTIVE/NORMAL_PASSIVE degradation."},
        {"name": "Header / Frame CRC error status", "purpose": "CRC error "
         "flags identify corrupt frames per channel."},
        {"name": "Per-channel frame status", "purpose": "Valid/null/sync/"
         "startup frame status per slot per channel."},
        {"name": "Media access Test Symbol (MTS)", "purpose": "Network-"
         "management test symbol used to probe media access in the symbol "
         "window."},
    ]
    d["error_detection_mechanisms"] = [
        "11-bit Header CRC detects header corruption.",
        "24-bit Frame CRC detects whole-frame corruption.",
        "Null Frame Indicator distinguishes an application-empty slot from a "
        "missing frame.",
        "Dual-channel comparison: a receiver may take a valid frame from "
        "either channel.",
        "Clock-sync degradation (too few valid sync frames) trips "
        "NORMAL_PASSIVE / HALT.",
        "Bus Guardian blocks out-of-slot transmission (babbling-idiot "
        "protection).",
    ]
    d["test_modes"] = [
        {"name": "Conformance test", "purpose": "FlexRay conformance test "
         "suite (ISO 17458-5) validates protocol behavior."},
        {"name": "Loopback / monitoring", "purpose": "CC monitor mode observes "
         "the bus without transmitting."},
        {"name": "Wakeup/startup test", "purpose": "Exercise WUP/WUS and "
         "CAS/coldstart sequences."},
    ]
    d["interrupt_or_event_sources"] = [
        {"event": "Cycle start", "trigger": "Start of a new communication "
         "cycle (cycle counter increment)."},
        {"event": "Slot / frame received", "trigger": "A frame is received in "
         "a slot on a channel."},
        {"event": "CRC error", "trigger": "Header or Frame CRC mismatch."},
        {"event": "Sync status change", "trigger": "NORMAL_ACTIVE <-> "
         "NORMAL_PASSIVE transition from clock-sync status."},
        {"event": "Wakeup detected", "trigger": "Bus Driver detects a Wakeup "
         "Pattern."},
        {"event": "Startup / integration complete", "trigger": "Coldstart "
         "succeeds and the node reaches NORMAL_ACTIVE."},
    ]
    d["notes"] = (
        "FlexRay's protocol-level test surface is the Controller Host "
        "Interface status (POC state, counters, clock-sync status, CRC error "
        "flags) plus the symbol-window MTS and the conformance test suite. "
        "Chip-level JTAG/scan/BIST remain CC-vendor / SoC-integrator "
        "concerns.")
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
        "FLEXRAY_SPEC_VERSION": "2.1A",
        "MODULATION": "NRZ",
        "SIGNALING": "differential (BP/BM)",
        "LINE_ENCODING": "NRZ; no bit stuffing",
        "DATA_RATES_MBPS": list(_DATA_RATES_MBPS),
        "MAX_DATA_RATE_MBPS": _MAX_DATA_RATE_MBPS,
        "BIT_TIME_NS_AT_10MBPS": 100,
        "SAMPLES_PER_BIT": 8,
        "VOTING_WINDOW_SAMPLES": 5,
        "CHANNEL_COUNT": 2,
        "CYCLE_COUNTER_BITS": _CYCLE_COUNTER_BITS,
        "CYCLE_COUNTER_MODULO": 64,
        "FRAME_ID_BITS": _FRAME_ID_BITS,
        "FRAME_ID_MAX": 2047,
        "PAYLOAD_LENGTH_BITS": _PAYLOAD_LENGTH_BITS,
        "PAYLOAD_LENGTH_MAX_WORDS": 127,
        "MAX_PAYLOAD_BYTES": _MAX_PAYLOAD_BYTES,
        "HEADER_BYTES": _HEADER_BYTES,
        "HEADER_CRC_BITS": _HEADER_CRC_BITS,
        "FRAME_CRC_BITS": _FRAME_CRC_BITS,
        "EMBEDDED_CLOCK": True,
        "FORWARDED_CLOCK": False,
    })
    d["frame_format_constants"] = {
        "header_bytes": _HEADER_BYTES,
        "reserved_bit": 1,
        "payload_preamble_indicator_bit": 1,
        "null_frame_indicator_bit": 1,
        "sync_frame_indicator_bit": 1,
        "startup_frame_indicator_bit": 1,
        "frame_id_bits": _FRAME_ID_BITS,
        "payload_length_bits": _PAYLOAD_LENGTH_BITS,
        "header_crc_bits": _HEADER_CRC_BITS,
        "cycle_count_bits": _CYCLE_COUNTER_BITS,
        "frame_crc_bits": _FRAME_CRC_BITS,
        "max_payload_bytes": _MAX_PAYLOAD_BYTES,
    }
    d["crc_constants"] = {
        "header_crc": {"width_bits": _HEADER_CRC_BITS,
                       "coverage": "sync indicator, startup indicator, Frame "
                                   "ID, Payload Length",
                       "generator_degree": 11},
        "frame_crc": {"width_bits": _FRAME_CRC_BITS,
                      "coverage": "entire header + payload",
                      "generator_degree": 24,
                      "channel_specific_init": True},
    }
    kc = _ensure_dict(d, "key_constants_for_RTL_authoring")
    kc.update({
        "is_serial": True,
        "is_differential": True,
        "is_dual_channel": True,
        "embedded_clock": True,
        "forwarded_clock": False,
        "modulation": "NRZ",
        "bit_stuffing": False,
        "samples_per_bit": 8,
        "voting_window_samples": 5,
        "max_data_rate_Mbps": _MAX_DATA_RATE_MBPS,
        "cycle_counter_bits": _CYCLE_COUNTER_BITS,
        "frame_id_bits": _FRAME_ID_BITS,
        "payload_length_bits": _PAYLOAD_LENGTH_BITS,
        "header_crc_bits": _HEADER_CRC_BITS,
        "frame_crc_bits": _FRAME_CRC_BITS,
        "tdma_static_segment": True,
        "ftdma_dynamic_segment": True,
        "clock_sync_offset_and_rate": True,
        "fault_tolerant_midpoint": True,
        "poc_states": list(_POC_STATES),
    })
    d["default_signal_values_when_idle"] = {
        "bus_idle": "Idle/recessive differential state on BP/BM; TxEN "
                    "de-asserted (driver off).",
        "tx_gating": "TxEN asserted only during the node's assigned static "
                     "slot or won dynamic minislot.",
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
        "modulation": "differential NRZ on BP/BM",
        "bit_time_ns_at_10Mbps": 100,
        "samples_per_bit": 8,
        "voting_window_samples": 5,
        "strobing": "re-strobe on the falling edge at the start of each Byte "
                    "Start Sequence (BSS).",
        "note": "No bit stuffing; no separate clock wire.",
    }
    d["frame_waveform"] = {
        "framing": "TSS + FSS + (per-byte BSS + 8 data bits) ... + FES",
        "header": "5 bytes: indicator bits + Frame ID (11) + Payload Length "
                  "(7) + Header CRC (11) + Cycle Count (6).",
        "payload": "0..254 bytes (0..127 16-bit words).",
        "trailer": "24-bit Frame CRC.",
    }
    d["communication_cycle_waveform"] = {
        "segment_order": ["Static segment", "Dynamic segment", "Symbol "
                          "window", "Network Idle Time (NIT)"],
        "static_segment": "Equal-length static slots in macroticks; one "
                          "sender per slot per channel.",
        "dynamic_segment": "Minislots; counter holds during a transmitted "
                           "frame, advances on an empty minislot.",
        "nit": "Communication-free; clock-sync calculation + offset correction "
               "applied.",
        "cycle_counter": "6-bit, 0..63, wraps.",
    }
    d["clock_sync_waveform"] = {
        "offset_correction": "phase correction computed in the NIT and applied "
                             "at cycle end.",
        "rate_correction": "frequency correction computed over an even/odd "
                           "cycle pair, applied gradually.",
        "algorithm": "Fault-Tolerant Midpoint over received sync frames.",
    }
    d["startup_waveform"] = {
        "wakeup": "Wakeup Pattern (WUP) = repeated Wakeup Symbols (WUS), one "
                  "channel at a time.",
        "coldstart": "Leading coldstart node sends CAS then startup frames; "
                     "followers integrate over several cycles; >=2 coldstart "
                     "nodes agree.",
    }
    d["general_timing_rule"] = (
        "All slot and segment boundaries are fixed in macroticks and identical "
        "cluster-wide. The macrotick is an integer number of microticks "
        "adjusted by rate correction so it has the same duration in every "
        "node. Bit time is 100 ns at 10 Mbit/s; the receiver oversamples 8x "
        "and re-strobes per byte.")
    d["voltage_levels"] = {
        "modulation": "differential NRZ; idle/recessive vs Data_0 / Data_1.",
        "termination": "differential bus termination per the FlexRay "
                       "electrical physical layer.",
    }
    d["data_rate_waveform"] = {
        "data_rates_Mbps": list(_DATA_RATES_MBPS),
        "bit_time_ns": {"2.5": 400.0, "5": 200.0, "10": 100.0},
        "modulation": "NRZ (two-level differential)",
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
        "Automotive in-vehicle communication controller: a dual-channel "
        "(Channel A / B) time-triggered serial bus interface implementing the "
        "FlexRay communication cycle (TDMA static + FTDMA dynamic + symbol "
        "window + NIT), distributed fault-tolerant clock synchronization, "
        "frame coding (5-byte header + payload + 24-bit Frame CRC), wakeup/"
        "coldstart, and the POC state machine, connecting a host to the BP/BM "
        "bus via Bus Driver(s).")
    d["topology_description"] = (
        "Multidrop dual-channel cluster: nodes (CC + Bus Driver per channel + "
        "optional Bus Guardian) connect to Channel A and/or Channel B over a "
        "passive bus, passive star, or active star. The schedule and time base "
        "are distributed; there is no central bus master.")
    io = _ensure_dict(d, "integration_overview")
    io.update({
        "flexray_spec_version": "2.1A",
        "max_data_rate_Mbps": _MAX_DATA_RATE_MBPS,
        "data_rates_Mbps": list(_DATA_RATES_MBPS),
        "channel_count": 2,
        "channels": list(_CHANNELS),
        "modulation": "differential NRZ (BP/BM)",
        "clocking": "embedded (oversampled bit recovery) + global clock "
                    "synchronization",
        "communication_cycle_segments": ["Static", "Dynamic", "Symbol window",
                                         "NIT"],
        "cycle_counter_bits": _CYCLE_COUNTER_BITS,
        "frame_id_bits": _FRAME_ID_BITS,
        "payload_length_bits": _PAYLOAD_LENGTH_BITS,
        "header_crc_bits": _HEADER_CRC_BITS,
        "frame_crc_bits": _FRAME_CRC_BITS,
        "max_payload_bytes": _MAX_PAYLOAD_BYTES,
        "node_interfaces": {"CHI": "host <-> CC",
                            "TxD/TxEN/RxD": "CC <-> Bus Driver",
                            "BP/BM": "Bus Driver <-> bus"},
        "host_side_register_spec": "FlexRay CC configuration parameter set "
        "(g*/p*/v*) over the Controller Host Interface (CHI).",
    })
    d["interface_categories"] = [
        "Host interface — Controller Host Interface (CHI) between host and CC.",
        "CC <-> Bus Driver — digital TxD (transmit data), TxEN (transmit "
        "enable), RxD (receive data).",
        "Bus Driver <-> bus — differential BP/BM per channel.",
        "Optional Bus Guardian — schedule-enforcement / babbling-idiot "
        "protection.",
    ]
    d["interconnect_topologies_supported"] = [
        "Passive bus (linear multidrop) per channel.",
        "Passive star per channel.",
        "Active star (one or more couplers; cascaded within timing limits).",
        "Dual-channel redundant (same data on A and B).",
        "Dual-channel doubled-bandwidth (different data on A and B).",
    ]
    d["default_signal_values_when_omitted"] = (
        "Bus idle/recessive; TxEN de-asserted; the node drives only during its "
        "configured slots. A node connected to one channel leaves the other "
        "channel's signals unused.")
    d["soc_dependent_items"] = [
        "Cluster schedule: number/length of static slots and minislots, cycle "
        "length, payload length (g* parameters).",
        "Sync / coldstart node role assignment (pKeySlotUsedForSync / "
        "ForStartup).",
        "Channel usage: single vs dual channel; redundancy vs bandwidth.",
        "Physical topology (passive bus / passive star / active star) and Bus "
        "Driver selection.",
        "Optional Bus Guardian integration.",
        "Oscillator tolerance budget feeding clock synchronization.",
    ]
    d["node_components"] = {
        "host": "Application processor; configures the CC, exchanges frame "
                "data over the CHI.",
        "communication_controller": "Implements the FlexRay protocol (media "
                                     "access, frame coding, cycle, clock sync, "
                                     "startup/wakeup, POC).",
        "bus_driver": "Physical-layer transceiver per channel; TxD/TxEN/RxD "
                      "<-> BP/BM.",
        "bus_guardian": "Optional independent schedule enforcer.",
    }
    d["device_classes_examples"] = [
        "Brake/steer-by-wire ECU",
        "Powertrain / engine-control ECU",
        "Chassis / active-suspension controller",
        "Gateway ECU bridging FlexRay to CAN/LIN/Ethernet",
        "Active star coupler",
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
        "partial - the specification defines protocol behaviors and a "
        "conformance test (ISO 17458-5) rather than an embedded testbench; the "
        "categories below are derived from the spec.")
    d["derived_compliance_test_categories"] = [
        "Dual-channel operation: Channel A and Channel B, redundancy and "
        "doubled-bandwidth modes.",
        "Static segment TDMA: equal-length static slots, Frame ID = slot "
        "number, collision-free transmission.",
        "Dynamic segment FTDMA: minislot priority order, counter hold during a "
        "frame, empty-minislot advance.",
        "Communication cycle: static + dynamic + symbol window + NIT; 6-bit "
        "cycle counter 0..63 wrap.",
        "Timing hierarchy: microtick/macrotick/slot/cycle; synchronized "
        "macrotick across nodes.",
        "Clock synchronization: offset correction (NIT) + rate correction "
        "(even/odd cycle pair) via Fault-Tolerant Midpoint over sync frames.",
        "Frame format: 5-byte header (Frame ID 11, Payload Length 7, Header "
        "CRC 11, Cycle Count 6 + indicators), 0..254-byte payload, 24-bit "
        "Frame CRC.",
        "Header CRC and Frame CRC error injection / detection.",
        "Null / sync / startup / payload-preamble indicator handling.",
        "Wakeup: WUP/WUS, one channel at a time, Bus Driver wake detection.",
        "Coldstart/startup: CAS + startup frames, integration, >=2 coldstart "
        "nodes agree.",
        "POC state machine coverage: DEFAULT_CONFIG -> CONFIG -> READY -> "
        "WAKEUP -> STARTUP -> NORMAL_ACTIVE; degradation to NORMAL_PASSIVE / "
        "HALT.",
        "Bus Guardian: out-of-slot transmission blocked.",
        "Bit timing: 8x oversampling, 5-sample majority vote, per-byte (BSS) "
        "re-strobing; no bit stuffing.",
        "Physical topologies: passive bus, passive star, active star.",
        "Sync-frame degradation: too few sync frames -> NORMAL_PASSIVE.",
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
        {"field": "Node sync/coldstart role",
         "location": "CC configuration (pKeySlotUsedForSync / ForStartup)",
         "note": "Whether the node is a sync node and/or a coldstart node; "
                 "configured, not protocol-fixed."},
        {"field": "Key slot ID",
         "location": "CC configuration (pKeySlotId)",
         "note": "The static slot in which the node sends its sync/startup key "
                 "frame."},
        {"field": "Cluster schedule (g* parameters)",
         "location": "CC configuration",
         "note": "Static-slot count/length, minislot count/length, cycle "
                 "length, payload length — identical cluster-wide."},
        {"field": "Channel usage",
         "location": "CC configuration",
         "note": "Single vs dual channel; which of A/B the node uses."},
    ]
    d["notes"] = (
        "FlexRay does not define OTP/fuse content as a protocol concept. The "
        "schedule, slot assignment, timing, and sync/coldstart role are host-"
        "programmed configuration parameters (g*/p*) loaded in the CONFIG "
        "state; an implementation may back some defaults with non-volatile "
        "storage, but the spec only requires they be configurable.")
    _write(p, d)


# ----------------------------------------------------------------------
# L12 — behavioral sequences.
# ----------------------------------------------------------------------
def _l12(gd: Path) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["configuration_sequence"] = [
        "1. Reset -> POC DEFAULT_CONFIG.",
        "2. Host enters CONFIG: load schedule (static slots, minislots, cycle "
        "length), timing (gdMacrotick, pMicroPerCycle), CRC init, sync/"
        "coldstart role.",
        "3. Host moves the CC to READY.",
    ]
    d["wakeup_sequence"] = [
        "1. POC enters WAKEUP on host command.",
        "2. The CC transmits a Wakeup Pattern (WUP = repeated Wakeup Symbols "
        "WUS) on one channel.",
        "3. Other nodes' Bus Drivers detect bus activity and wake their "
        "hosts/CCs.",
        "4. Wakeup is repeated per channel, one channel at a time.",
    ]
    d["startup_coldstart_sequence"] = [
        "1. POC enters STARTUP.",
        "2. A leading coldstart node ensures the channel is idle, transmits "
        "the Collision Avoidance Symbol (CAS), then begins sending startup "
        "frames (sync frames with the startup indicator), establishing cycle "
        "0, 1, ...",
        "3. Following nodes listen and integrate to the schedule by observing "
        "startup/sync frames over several cycles.",
        "4. At least two coldstart nodes must agree; once consistent, clock "
        "synchronization starts and the nodes enter NORMAL_ACTIVE.",
    ]
    d["communication_cycle_sequence"] = [
        "1. Static segment: each static slot's owner transmits its frame "
        "(Frame ID = slot number); the slot counter advances every slot.",
        "2. Dynamic segment: the minislot counter advances; a node whose "
        "dynamic Frame ID matches the current minislot transmits (holding the "
        "counter); empty minislots elapse.",
        "3. Symbol window: optional network-management symbols (MTS).",
        "4. Network Idle Time: no frames; compute clock sync and apply offset "
        "correction; increment the cycle counter (mod 64).",
    ]
    d["frame_transmission_sequence"] = [
        "1. Host writes frame data to the CC over the CHI.",
        "2. In the assigned slot/minislot the CC builds the frame: 5-byte "
        "header (indicators + Frame ID + Payload Length + Header CRC + Cycle "
        "Count), payload, 24-bit Frame CRC.",
        "3. The CC asserts TxEN and drives TxD; the Bus Driver puts the NRZ "
        "frame on BP/BM (framed by TSS/FSS/BSS/FES).",
        "4. Receivers oversample RxD 8x, majority-vote, re-strobe per BSS, "
        "check Header and Frame CRC, and deliver valid frames to their hosts.",
    ]
    d["clock_sync_sequence"] = [
        "1. During the static segment the node measures arrival timing of "
        "received sync frames on both channels.",
        "2. In the NIT the node computes offset correction (phase) via the "
        "Fault-Tolerant Midpoint algorithm and applies it for the next cycle.",
        "3. Over an even/odd cycle pair the node computes rate correction "
        "(frequency / microticks per cycle) and applies it gradually.",
    ]
    d["error_degradation_sequence"] = [
        "1. Too few valid sync frames are received.",
        "2. Clock-sync status degrades the node from NORMAL_ACTIVE to "
        "NORMAL_PASSIVE (receive/keep time, do not actively transmit).",
        "3. Continued loss of synchronization forces HALT.",
    ]
    d["reset_sequence"] = [
        "1. Reset asserted -> POC DEFAULT_CONFIG; the CC leaves the schedule.",
        "2. Re-run CONFIG -> READY -> WAKEUP -> STARTUP -> NORMAL_ACTIVE.",
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
        {"name": "Bit timing / eye at 10 Mbit/s", "purpose": "Verify the 100 "
         "ns bit time and differential NRZ eye on BP/BM; confirm 8x "
         "oversampling and 5-sample majority voting recover bits correctly."},
        {"name": "Macrotick / clock-sync accuracy", "purpose": "Confirm the "
         "macrotick has the same duration cluster-wide and that offset/rate "
         "correction keeps nodes synchronized within tolerance."},
        {"name": "Static-slot timing", "purpose": "Verify each static slot's "
         "macrotick boundaries and that the slot owner transmits exactly in "
         "its window."},
        {"name": "Dynamic-segment minislotting", "purpose": "Confirm minislot "
         "counter hold/advance behavior and priority ordering."},
        {"name": "Wakeup / coldstart", "purpose": "Validate WUP/WUS detection "
         "and CAS + startup-frame coldstart with >=2 coldstart nodes."},
        {"name": "CRC coverage", "purpose": "Inject errors and confirm the "
         "11-bit Header CRC and 24-bit Frame CRC detect them."},
        {"name": "Active-star timing", "purpose": "Measure propagation through "
         "active star couplers within the configured timing limits."},
    ]
    d["notes"] = (
        "FlexRay characterization centers on bit timing (10 Mbit/s differential "
        "NRZ, 8x oversampling), the synchronized macrotick / clock "
        "synchronization, the TDMA/FTDMA slot timing, and wakeup/coldstart. "
        "Conformance is established by the FlexRay conformance test (ISO "
        "17458-5). Per-node oscillator and PHY calibration is done at "
        "bring-up.")
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
        "FlexRay Communications System Protocol Specification Version 2.1 "
        "Revision A (Bosch v2.1A); standardized as ISO 17458-1..5 (2013)")
    f["previous_versions"] = [
        "FlexRay 2.0 (2004) — initial published protocol specification.",
        "FlexRay 2.1 (2005) — frame/startup/clock-sync refinements (2.1A is "
        "the deployed revision).",
    ]
    f["key_changes"] = [
        {"version": "2.1 Rev A", "summary": "Refined frame format, startup / "
         "coldstart procedure, clock synchronization, and electrical physical "
         "layer; the widely deployed automotive revision. Dual-channel "
         "time-triggered TDMA + FTDMA, communication cycle, macrotick/microtick "
         "hierarchy, and POC state machine are carried forward."},
        {"version": "ISO 17458 (2013)", "summary": "International "
         "standardization of FlexRay across five parts: general / use cases, "
         "data link layer, data link layer conformance test, electrical "
         "physical layer, electrical physical layer conformance test."},
    ]
    f["future_versions_industry_outline"] = [
        {"version": "FlexRay 3.0 (2010)", "summary": "Later Consortium "
         "revision adding more flexible configuration and extended payload / "
         "scheduling options; the Consortium disbanded in 2009-2010 and ISO "
         "17458 carried the standard forward."},
    ]
    f["backward_compat_traps"] = [
        {"trap_name": "Static_vs_dynamic_segment",
         "rule": "The static segment is TDMA (fixed slots, Frame ID = slot "
                 "number); the dynamic segment is FTDMA (minislots, priority).",
         "trap": "Treating dynamic-segment frames as fixed-latency or "
                 "static-segment frames as on-demand breaks determinism."},
        {"trap_name": "Sync_frames_static_only",
         "rule": "Only sync frames (sync indicator set), sent only in the "
                 "static segment by configured sync nodes, drive clock "
                 "synchronization.",
         "trap": "Expecting dynamic-segment frames to contribute to clock sync "
                 "is wrong."},
        {"trap_name": "Two_coldstart_nodes_required",
         "rule": "At least two coldstart nodes must agree to start the "
                 "cluster.",
         "trap": "A single coldstart node cannot bring up the cluster alone."},
        {"trap_name": "Not_CAN_no_bit_stuffing",
         "rule": "FlexRay uses NRZ with per-byte BSS re-strobing, not CAN-style "
                 "bitwise arbitration or bit stuffing.",
         "trap": "Applying CAN identifier arbitration / bit stuffing to "
                 "FlexRay is wrong."},
    ]
    f["version_naming_history_note"] = (
        "FlexRay was developed by the FlexRay Consortium (founded 2000 by BMW, "
        "DaimlerChrysler, and others; later including Bosch, NXP/Freescale, "
        "VW, GM). The Bosch FlexRay Protocol Specification v2.1A (2005) is the "
        "deployed automotive revision; FlexRay 3.0 followed in 2010, and the "
        "protocol was standardized as ISO 17458-1..5 in 2013.")
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
    f["data_rate_table"] = {
        "header_columns": ["Data Rate (Mbit/s)", "Bit Time (ns)",
                           "Modulation", "Coding"],
        "rows": [
            ["2.5", "400.0", "NRZ", "differential, 8x oversampled"],
            ["5", "200.0", "NRZ", "differential, 8x oversampled"],
            ["10", "100.0", "NRZ", "differential, 8x oversampled"],
        ],
    }
    f["frame_header_field_table"] = {
        "header_columns": ["Field", "Width (bits)", "Notes"],
        "rows": [
            ["Reserved bit", "1", "transmitted as 0"],
            ["Payload Preamble Indicator", "1", "NM Vector / Message ID"],
            ["Null Frame Indicator", "1", "no valid application data"],
            ["Sync Frame Indicator", "1", "used by clock sync (static only)"],
            ["Startup Frame Indicator", "1", "used during coldstart"],
            ["Frame ID", "11", "1..2047; = slot number in static segment"],
            ["Payload Length", "7", "0..127 words (0..254 bytes)"],
            ["Header CRC", "11", "over sync/startup ind., Frame ID, length"],
            ["Cycle Count", "6", "0..63"],
        ],
    }
    f["communication_cycle_table"] = {
        "header_columns": ["Segment", "Mandatory?", "Media access"],
        "rows": [
            ["Static segment", "yes", "TDMA (fixed static slots)"],
            ["Dynamic segment", "no", "FTDMA / minislotting (priority)"],
            ["Symbol window", "no", "network-management symbols"],
            ["Network Idle Time (NIT)", "yes", "none (clock sync calc)"],
        ],
    }
    f["timing_hierarchy_table"] = {
        "header_columns": ["Unit", "Definition"],
        "rows": [
            ["Microtick", "smallest local unit, from the node oscillator"],
            ["Macrotick", "synchronized cluster unit = integer microticks "
             "(rate-corrected)"],
            ["Slot", "static slot or minislot = integer macroticks"],
            ["Cycle", "whole communication cycle, counted 0..63"],
        ],
    }
    f["crc_table"] = {
        "header_columns": ["CRC", "Width (bits)", "Coverage"],
        "rows": [
            ["Header CRC", "11", "sync/startup indicators, Frame ID, Payload "
             "Length"],
            ["Frame CRC", "24", "entire header + payload"],
        ],
    }
    f["symbol_table"] = {
        "header_columns": ["Symbol", "Meaning"],
        "rows": [
            ["CAS", "Collision Avoidance Symbol (coldstart)"],
            ["MTS", "Media access Test Symbol"],
            ["WUS", "Wakeup Symbol"],
            ["WUP", "Wakeup Pattern (repeated WUS)"],
        ],
    }
    f["encoding_note"] = (
        "FlexRay uses differential NRZ with 8x oversampling and a 5-sample "
        "majority vote; bit timing is re-strobed on each Byte Start Sequence "
        "(BSS) rather than maintained by bit stuffing. Frame integrity is "
        "provided by the 11-bit Header CRC and 24-bit Frame CRC.")
    f["tables"] = [
        "Data-rate / bit-time table (2.5 / 5 / 10 Mbit/s)",
        "Frame header field table (Frame ID 11 / Payload Length 7 / Header CRC "
        "11 / Cycle Count 6 + indicators)",
        "Communication-cycle segment table",
        "Timing-hierarchy table (microtick/macrotick/slot/cycle)",
        "CRC table (Header 11-bit / Frame 24-bit)",
        "Symbol table (CAS / MTS / WUS / WUP)",
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
        "Two channels (Channel A / Channel B), each a differential BP/BM NRZ "
        "bus at up to 10 Mbit/s.",
        "Periodic communication cycle: TDMA static segment + optional FTDMA "
        "dynamic segment + optional symbol window + mandatory NIT; 6-bit cycle "
        "counter.",
        "Static slots of equal length (Frame ID = slot number) and dynamic "
        "minislots in priority order.",
        "Timing hierarchy microtick/macrotick/slot/cycle with a synchronized "
        "macrotick.",
        "Distributed fault-tolerant clock synchronization: offset + rate "
        "correction via the Fault-Tolerant Midpoint over sync frames; >=2 sync "
        "nodes.",
        "Frame format: 5-byte header (Frame ID 11, Payload Length 7, Header "
        "CRC 11, Cycle Count 6 + indicators), 0..254-byte payload, 24-bit "
        "Frame CRC.",
        "Wakeup (WUP/WUS) and coldstart (CAS + startup frames, >=2 coldstart "
        "nodes).",
        "POC state machine: DEFAULT_CONFIG/CONFIG/READY/WAKEUP/STARTUP/"
        "NORMAL_ACTIVE/NORMAL_PASSIVE/HALT.",
        "CC <-> Bus Driver via TxD/TxEN/RxD; optional Bus Guardian.",
    ]
    f["must_not_have_properties"] = [
        "CAN-style identifier-based bitwise arbitration (FlexRay is "
        "time-triggered TDMA, collision-free by schedule).",
        "Bit stuffing (FlexRay re-strobes per Byte Start Sequence instead).",
        "A single shared channel as the only medium (FlexRay defines two "
        "independent channels).",
        "A central bus master (the schedule and time base are distributed).",
        "A separate transmitted clock wire (bit timing is recovered by "
        "oversampling).",
    ]
    f["compliance_failure_modes"] = [
        {"mode": "Loss of synchronization", "trigger": "Too few valid sync "
         "frames; node degrades to NORMAL_PASSIVE / HALT."},
        {"mode": "Coldstart failure", "trigger": "Fewer than two coldstart "
         "nodes agree; cluster never reaches normal operation."},
        {"mode": "CRC error", "trigger": "Header or Frame CRC mismatch; frame "
         "discarded."},
        {"mode": "Schedule violation", "trigger": "Transmission outside an "
         "assigned slot; blocked by the Bus Guardian."},
        {"mode": "Wakeup failure", "trigger": "Wakeup Pattern not detected; "
         "channel stays asleep."},
    ]
    f["min_link_constraint"] = (
        "A FlexRay cluster requires at least two coldstart (and sync) nodes to "
        "start and maintain the global time base; a node must reach "
        "NORMAL_ACTIVE via CONFIG -> READY -> WAKEUP -> STARTUP with the "
        "schedule integrated and clock synchronization running.")
    f["reset_behavior_compliance"] = (
        "Reset drives the POC to DEFAULT_CONFIG; the host re-runs CONFIG -> "
        "READY -> WAKEUP -> STARTUP, integrating to the schedule and "
        "re-establishing clock synchronization before NORMAL_ACTIVE.")
    f["flexray_distinguishers"] = (
        "FlexRay is identified by ALL of: dual independent channels (A/B); a "
        "time-triggered TDMA static segment plus an FTDMA minislot dynamic "
        "segment within a periodic communication cycle (6-bit cycle counter); "
        "the microtick/macrotick/slot/cycle timing hierarchy; distributed "
        "fault-tolerant clock synchronization (offset + rate, Fault-Tolerant "
        "Midpoint over sync frames); a 5-byte header (11-bit Frame ID, 7-bit "
        "Payload Length, 11-bit Header CRC, 6-bit Cycle Count + indicator "
        "bits), 0..254-byte payload, 24-bit Frame CRC; CAS coldstart and "
        "WUP/WUS wakeup; the CC + Bus Driver + optional Bus Guardian node; "
        "BP/BM differential signaling; and the POC state machine. This is "
        "distinct from CAN (event-triggered CSMA/CR, identifier arbitration, "
        "bit stuffing, single channel) and LIN (single-wire master/slave "
        "polled sub-bus).")
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
        {"name": "Channel A (BP/BM)",
         "direction": "half-duplex differential bus",
         "purpose": "Primary FlexRay channel; differential NRZ at up to 10 "
                    "Mbit/s.",
         "active_levels": "Data_0 / Data_1 differential states",
         "idle_level": "idle/recessive"},
        {"name": "Channel B (BP/BM)",
         "direction": "half-duplex differential bus",
         "purpose": "Second independent channel (redundancy or doubled "
                    "bandwidth).",
         "active_levels": "Data_0 / Data_1 differential states",
         "idle_level": "idle/recessive"},
        {"name": "TxD", "direction": "CC -> Bus Driver",
         "purpose": "Transmit serial data to the bus driver.",
         "active_levels": "digital", "idle_level": "recessive"},
        {"name": "TxEN", "direction": "CC -> Bus Driver",
         "purpose": "Transmit enable; gates the driver to the node's slots.",
         "active_levels": "asserted during the node's slot",
         "idle_level": "de-asserted"},
        {"name": "RxD", "direction": "Bus Driver -> CC",
         "purpose": "Received serial data recovered from the bus.",
         "active_levels": "digital", "idle_level": "recessive"},
    ]
    f["logical_signaling_levels"] = [
        {"name": "Idle/recessive", "meaning": "No active driver on the "
         "channel; bus rests in the idle differential state."},
        {"name": "Data_0 / Data_1", "meaning": "Active differential NRZ data "
         "states forced by the slot owner's driver."},
    ]
    f["packet_types_summary"] = [
        {"class": "Frame", "members": ["Static frame", "Dynamic frame",
                                       "Null frame", "Sync frame",
                                       "Startup frame"], "count": 5},
        {"class": "Symbol", "members": ["CAS", "MTS", "WUS", "WUP"],
         "count": 4},
    ]
    cc = _ensure_dict(f, "channel_counts")
    cc.update({
        "channel_count": 2,
        "differential_pairs_per_channel": 1,
        "cc_to_bd_signals": 3,
        "max_data_rate_Mbps": _MAX_DATA_RATE_MBPS,
        "cycle_counter_bits": _CYCLE_COUNTER_BITS,
        "frame_id_bits": _FRAME_ID_BITS,
        "payload_length_bits": _PAYLOAD_LENGTH_BITS,
        "header_crc_bits": _HEADER_CRC_BITS,
        "frame_crc_bits": _FRAME_CRC_BITS,
        "header_bytes": _HEADER_BYTES,
        "max_payload_bytes": _MAX_PAYLOAD_BYTES,
        "frame_type_count": 5,
        "symbol_count": 4,
    })
    f["global_signals"] = [
        {"name": "Communication cycle", "purpose": "Cluster-wide synchronized "
         "periodic schedule (static + dynamic + symbol window + NIT)."},
        {"name": "Global time {cycle, macrotick}", "purpose": "Synchronized "
         "time base shared by all nodes."},
        {"name": "Wakeup Pattern (WUP)", "purpose": "Wakes a channel before "
         "communication."},
    ]
    f["dependency_graph"] = {
        "common_rule": "Every node derives the global time {cycle counter, "
        "macrotick} from clock synchronization; all slot/segment boundaries "
        "are fixed in macroticks identically cluster-wide. The static segment "
        "must run (carrying sync frames) for clock synchronization; the NIT "
        "applies offset correction.",
        "data_dependency": "Transmission in a slot requires: (1) the node "
        "synchronized (NORMAL_ACTIVE), (2) the slot/minislot assigned to the "
        "node, (3) TxEN gating to the slot. Coldstart (>=2 nodes) must "
        "complete before normal frames flow.",
    }
    f["handshake_pairs"] = [
        {"name": "CHI", "from": "host", "to": "Communication Controller",
         "rule": "Controller Host Interface carries configuration and frame "
                 "data between host and CC."},
        {"name": "TxD/TxEN/RxD", "from": "Communication Controller",
         "to": "Bus Driver", "rule": "Digital data + transmit-enable + receive "
                 "data between CC and Bus Driver."},
        {"name": "Sync-frame timing", "from": "sync node", "to": "all nodes",
         "rule": "Sync frames in the static segment provide the timing "
                 "references for clock synchronization."},
        {"name": "Coldstart", "from": "leading coldstart node",
         "to": "following nodes", "rule": "CAS + startup frames establish the "
                 "schedule; >=2 coldstart nodes must agree."},
        {"name": "Wakeup", "from": "any node", "to": "channel",
         "rule": "Wakeup Pattern (WUP) wakes a channel one at a time."},
    ]
    f["ordering_rules"] = {
        "bit_order_on_wire": "Differential NRZ per bit; bytes framed by Byte "
        "Start Sequences; no bit stuffing.",
        "slot_order": "Static slots in slot-number order (Frame ID = slot "
        "number); dynamic minislots in Frame-ID priority order.",
        "channel_independence": "Channel A and Channel B operate "
        "independently; a receiver may use whichever channel carries a valid "
        "frame.",
        "cycle_order": "Cycles repeat with the 6-bit cycle counter (0..63).",
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
        "Multidrop dual-channel automotive bus. Per channel: passive bus "
        "(linear multidrop), passive star, or active star (active couplers "
        "regenerate the signal; cascaded within timing limits). The schedule "
        "and time base are distributed across all nodes; there is no central "
        "master.")
    f["supported_topologies"] = [
        {"name": "Passive bus", "description": "Linear multidrop passive bus "
         "per channel."},
        {"name": "Passive star", "description": "Passive star coupling per "
         "channel."},
        {"name": "Active star", "description": "One or more active star "
         "couplers regenerate the signal and isolate branches; cascaded active "
         "stars allowed within timing limits."},
        {"name": "Dual-channel redundant", "description": "Both channels carry "
         "the same data for fault tolerance."},
        {"name": "Dual-channel bandwidth", "description": "Channels carry "
         "different data for doubled bandwidth."},
    ]
    f["master_slave_role_summary"] = [
        {"role": "Communication Controller (CC)", "description": "Implements "
         "the FlexRay protocol; follows the distributed TDMA schedule; no "
         "single CC is a master."},
        {"role": "Bus Driver (BD)", "description": "Per-channel physical-layer "
         "transceiver (TxD/TxEN/RxD <-> BP/BM)."},
        {"role": "Bus Guardian (BG)", "description": "Optional independent "
         "schedule enforcer (babbling-idiot protection)."},
        {"role": "Sync node", "description": "Sends sync frames that provide "
         "clock-synchronization timing references."},
        {"role": "Coldstart node", "description": "Sends startup frames (and "
         "CAS for the leader) to start the cluster; >=2 required."},
    ]
    f["interconnect_role"] = (
        "FlexRay is a deterministic dual-channel automotive backbone. The TDMA "
        "schedule guarantees collision-free, bounded-latency delivery in the "
        "static segment; the FTDMA dynamic segment grants prioritized on-demand "
        "bandwidth. Clock synchronization keeps every node on a common "
        "{cycle, macrotick} time base.")
    f["ordering_guarantees"] = {
        "static_segment": "Strict TDMA order by slot number; bounded latency "
        "and jitter.",
        "dynamic_segment": "Priority order by Frame ID (lower = higher "
        "priority); a low-priority frame may be deferred in a busy cycle.",
        "channel": "Channels A and B are independent; redundant frames are "
        "compared at the receiver.",
        "cycle": "Cycles ordered by the 6-bit cycle counter; cycle-multiplexed "
        "scheduling supported.",
    }
    f["memory_vs_peripheral_regions"] = (
        "FlexRay is not memory-mapped; frames are addressed by Frame ID and "
        "slot/cycle, not by a memory or peripheral address. The host exchanges "
        "frame buffers with the CC over the Controller Host Interface (CHI).")
    dc = _ensure_dict(f, "device_classification")
    dc["communication_controller"] = ("Protocol engine node attached to one "
                                       "or both channels.")
    dc["bus_driver"] = "Per-channel transceiver between CC and BP/BM."
    dc["bus_guardian"] = "Optional schedule-enforcement device."
    dc["active_star_coupler"] = ("Regenerates and isolates branch signals on a "
                                 "channel.")
    dc["gateway"] = "Node bridging FlexRay to CAN/LIN/Ethernet."
    f["default_signal_values_evidence_tables"] = [
        "FlexRay communication-cycle figure (static + dynamic + symbol window "
        "+ NIT)",
        "FlexRay frame-format figure (5-byte header + payload + 24-bit Frame "
        "CRC)",
        "FlexRay node architecture (host + CC + Bus Driver + Bus Guardian)",
        "FlexRay timing hierarchy (microtick/macrotick/slot/cycle)",
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
        "signaling": "differential NRZ on BP/BM",
        "line_encoding": "NRZ; no bit stuffing (per-byte BSS re-strobing)",
        "data_rates_Mbps": list(_DATA_RATES_MBPS),
        "max_data_rate_Mbps": _MAX_DATA_RATE_MBPS,
        "bit_time_ns_at_10Mbps": 100,
        "samples_per_bit": 8,
        "voting_window_samples": 5,
        "channels": list(_CHANNELS),
        "topologies": ["passive bus", "passive star", "active star"],
        "cc_to_bd_signals": ["TxD", "TxEN", "RxD"],
        "macrotick_unit": "integer microticks, rate-corrected; synchronized "
                          "cluster-wide (typically ~1 us)",
        "cycle_counter_bits": _CYCLE_COUNTER_BITS,
        "min_sync_nodes": 2,
        "min_coldstart_nodes": 2,
    }
    f["notes"] = (
        "FlexRay is a communication-system / data-link + physical-layer "
        "specification; it fixes the electrical channel model (differential "
        "NRZ BP/BM, <=10 Mbit/s, 8x oversampling), the dual-channel topology, "
        "the communication-cycle/macrotick timing, the frame format, and the "
        "clock-synchronization rules. It does NOT impose PDK-specific SDC / "
        "floorplan constraints — transceiver electrical characterization, "
        "termination, and wiring are physical-layer / board concerns (ISO "
        "17458-4). The interoperability-critical constraints are the "
        "communication-cycle schedule, the macrotick timing, and the frame / "
        "CRC formats.")
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
        {"name": "Controller Host Interface (CHI)", "purpose": "Primary "
         "in-band controllability/observability: configure the CC and read "
         "POC state, counters, clock-sync status, and CRC error flags."},
        {"name": "POC status (vPOC!State)", "purpose": "Observe the protocol "
         "state machine for bring-up and fault diagnosis."},
        {"name": "Clock-sync status", "purpose": "Offset/rate correction "
         "values and sync-frame counts for synchronization health."},
        {"name": "Media access Test Symbol (MTS)", "purpose": "Probe media "
         "access in the symbol window."},
        {"name": "CC monitor / loopback mode", "purpose": "Observe the bus "
         "without transmitting."},
    ]
    f["internal_diagnostics_observability"] = [
        "POC state (DEFAULT_CONFIG/CONFIG/READY/WAKEUP/STARTUP/NORMAL_ACTIVE/"
        "NORMAL_PASSIVE/HALT).",
        "Cycle counter (0..63), macrotick counter, slot counter.",
        "Clock-sync offset/rate correction values and sync-frame counts.",
        "Header / Frame CRC error flags per channel.",
        "Per-slot per-channel frame status (valid/null/sync/startup).",
        "Wakeup / coldstart / integration status.",
    ]
    f["out_of_band_test_facilities"] = [
        "FlexRay conformance test suite (ISO 17458-3 data-link, ISO 17458-5 "
        "physical-layer conformance).",
        "Vendor CC / transceiver bring-up and characterization tooling "
        "(implementation-defined).",
    ]
    f["notes"] = (
        "FlexRay's protocol-level DFT surface is the Controller Host Interface "
        "status (POC state, counters, clock-sync, CRC flags) plus the "
        "symbol-window MTS and monitor/loopback modes. Chip-level JTAG / scan "
        "/ BIST remain CC-vendor / SoC-integrator concerns. Conformance is "
        "established by the FlexRay conformance test.")
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
        {"state": "NORMAL_ACTIVE", "name": "Active", "description": "Fully "
         "operational; node participates in the schedule and clock sync."},
        {"state": "READY", "name": "Ready", "description": "Configured and "
         "idle, awaiting a start command."},
        {"state": "Sleep / bus-off", "name": "Sleep", "description": "Bus "
         "asleep; the node waits for a Wakeup Pattern (WUP) to wake."},
        {"state": "HALT", "name": "Halt", "description": "Communication "
         "stopped; the CC has left the schedule."},
    ]
    f["wakeup_mechanism"] = (
        "A node wakes a channel by transmitting a Wakeup Pattern (WUP), a "
        "configured number of Wakeup Symbols (WUS); the Bus Driver detects bus "
        "activity and wakes the host/CC. Wakeup is performed one channel at a "
        "time.")
    f["power_rails"] = [
        {"rail": "VCC (CC / Bus Driver)", "purpose": "Logic and transceiver "
         "supply."},
        {"rail": "Bus Driver standby supply", "purpose": "Keeps wakeup "
         "detection alive while the bus sleeps."},
        {"rail": "GND", "purpose": "Ground."},
    ]
    f["flexray_power_considerations"] = (
        "FlexRay defines a sleep/wakeup framework: the bus can sleep with the "
        "Bus Driver retaining wakeup-pattern detection, and a WUP wakes a "
        "channel before coldstart. Energy management is largely a transceiver "
        "(Bus Driver) and ECU concern; the protocol contributes the "
        "wakeup-symbol/pattern mechanism and the POC WAKEUP state.")
    f["notes"] = (
        "FlexRay's protocol-level power intent is the wakeup/sleep mechanism "
        "(WUP/WUS detection by the Bus Driver, POC WAKEUP state) rather than a "
        "fine-grained power-domain spec. Detailed power rails and low-power "
        "transceiver behavior are defined by the electrical physical layer "
        "(ISO 17458-4) and the Bus Driver implementation.")
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
        "Dual-channel operation (A/B) — redundancy and doubled bandwidth.",
        "Static segment TDMA — equal slots, Frame ID = slot number, "
        "collision-free.",
        "Dynamic segment FTDMA — minislot priority, counter hold/advance.",
        "Communication cycle — static + dynamic + symbol window + NIT; 6-bit "
        "cycle counter.",
        "Timing hierarchy — microtick/macrotick/slot/cycle; synchronized "
        "macrotick.",
        "Clock synchronization — offset + rate correction via Fault-Tolerant "
        "Midpoint over sync frames.",
        "Frame format — 5-byte header (Frame ID 11, Payload Length 7, Header "
        "CRC 11, Cycle Count 6), 0..254-byte payload, 24-bit Frame CRC.",
        "Header / Frame CRC error injection and detection.",
        "Indicator-bit handling — null / sync / startup / payload-preamble.",
        "Wakeup — WUP/WUS, one channel at a time.",
        "Coldstart/startup — CAS + startup frames, >=2 coldstart nodes, "
        "integration.",
        "POC state machine coverage and degradation (NORMAL_PASSIVE / HALT).",
        "Bus Guardian — out-of-slot transmission blocked.",
        "Bit timing — 8x oversampling, 5-sample majority vote, BSS re-strobe.",
        "Topologies — passive bus / passive star / active star.",
    ]
    f["notes"] = (
        "FlexRay does not ship an embedded testbench, but the specification "
        "implies a verification plan spanning the physical layer (bit timing, "
        "topologies), media access (static TDMA + dynamic FTDMA), the "
        "communication cycle and timing, clock synchronization, frame coding "
        "and CRCs, wakeup/coldstart, and the POC state machine. The FlexRay "
        "conformance test (ISO 17458-3 / -5) supplies the formal conformance "
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
        "11-bit Header CRC detects header corruption.",
        "24-bit Frame CRC detects whole-frame corruption (channel-specific CRC "
        "initialization distinguishes channels).",
        "Dual-channel redundancy: a valid frame may be taken from either "
        "channel.",
        "Bus Guardian prevents out-of-slot (babbling-idiot) transmission.",
        "Fault-Tolerant Midpoint clock sync tolerates a bounded number of "
        "faulty sync sources.",
        "Clock-sync degradation (NORMAL_PASSIVE / HALT) isolates an "
        "unsynchronized node.",
    ]
    f["anti_tampering_features"] = []
    f["confidentiality_features"] = []
    f["authentication_features"] = []
    f["future_security_pointers"] = [
        "FlexRay's base protocol provides no cryptographic confidentiality, "
        "integrity, or authentication; the CRCs are anti-corruption only.",
        "Vehicle-network security (e.g. AUTOSAR SecOC message authentication, "
        "gateway firewalling) is layered above FlexRay by the ECU software, "
        "not by the FlexRay protocol.",
    ]
    f["notes"] = (
        "FlexRay is a deterministic fault-tolerant transport: its built-in "
        "protections are anti-corruption and fault-tolerance only (Header / "
        "Frame CRC, dual-channel redundancy, Bus Guardian, Fault-Tolerant "
        "Midpoint clock sync). The bus carries plaintext frames. "
        "Cryptographic confidentiality / integrity / authentication are NOT "
        "part of the base FlexRay data path; they are provided by higher-layer "
        "ECU software (e.g. AUTOSAR SecOC) above the protocol.")
    _write(p, d)
