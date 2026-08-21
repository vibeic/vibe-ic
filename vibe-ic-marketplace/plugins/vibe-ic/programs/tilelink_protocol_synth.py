"""TileLink-class protocol synth helper.

v0.1.84 — ic_class-gated overlay for `bus_interconnect_protocol` specs that
exhibit the SiFive TileLink 1.7.x structural signature.

Applies SiFive TileLink Specification 1.7.1 (December 3, 2018) spec-canonical
content to L1-L23 + L8 timing + L14-L23.

Doctrine: structural-signature detection IS general within an ic_class
(mirrors the AMBA-AXI / SPI / I2C / UART / CAN / USB / I2S / AHB-APB synth
approach). Any TileLink-conformance-level variant — TL-UL, TL-UH, TL-C, or a
SoC-level TileLink crossbar / adapter — exhibits the same channel signature
(A + D mandatory; B + C + E added at TL-C; *_opcode/*_param/*_size/*_source/
*_address/*_mask/*_data fields).

Detection signature: (TileLink + Get + Put) OR (TL-UL + TL-UH + TL-C) OR
(Acquire + Release + Grant + Probe) OR (TileLink + SiFive).

Public entry: `apply_tilelink_synth(generated_docs_dir, is_tilelink,
                                    tilelink_ic_name)`.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

import l_doc_generator_stamp as _stamp


# ============================================================
# Generic helpers
# ============================================================
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


def _ensure_full(d: dict, key: str, value):
    """Force-set when key missing or value empty (None/""/[]/{})."""
    cur = d.get(key)
    if cur is None or cur == "" or cur == [] or cur == {}:
        d[key] = value
    return d[key]


# ============================================================
# Public entry
# ============================================================
def apply_tilelink_synth(generated_docs_dir: Path,
                         is_tilelink: bool,
                         tilelink_ic_name: Optional[str]) -> None:
    """Apply TileLink-specific synth when the structural signature matched.

    fail-open contract: print errors but never raise.
    """
    if not is_tilelink:
        return
    gd = Path(generated_docs_dir)

    try:
        # Force ic_name across the 14 main L docs (L1-L23 + L8 timing).
        if tilelink_ic_name is not None:
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
                    d["ic_name"] = tilelink_ic_name
                    _write(q, d)

            # L14-L23 keep ic_name inside the inner `fields` dict.
            for n in [
                "L14_PROTOCOL_VERSIONING.json", "L15_ENCODING_TABLES.json",
                "L16_COMPLIANCE_PROPERTIES.json",
                "L17_CHANNEL_SIGNAL_CATALOG.json",
                "L18_INTERCONNECT_TOPOLOGY.json",
                "L19_CONSTRAINTS_PDK.json", "L20_DFT_SCAN_TOPOLOGY.json",
                "L21_POWER_INTENT.json", "L22_VERIFICATION_PLAN.json",
                "L23_SECURITY_REQUIREMENTS.json",
            ]:
                q = gd / n
                if q.is_file():
                    d = _read(q)
                    f = _ensure_dict(d, "fields")
                    f["ic_name"] = tilelink_ic_name
                    d["fields"] = f
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
        print(f"[tilelink_protocol_synth] WARN: {exc}")


# ============================================================
# L1 DATASHEET
# ============================================================
def _l1(gd: Path) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("document_title", "SiFive TileLink Specification")
    d.setdefault("document_id", "TileLink Specification, Version 1.7.1")
    d.setdefault("issuer", "SiFive, Inc.")
    d.setdefault("copyright",
        "Copyright (c) 2016/2018 SiFive Inc. All rights reserved.")
    d.setdefault("confidentiality", "Public / Open-source standard")
    d.setdefault("issue_date", "December 3, 2018")
    d.setdefault("release_history", [
        {"date": "August 22, 2017",  "version": "1.7.1-draft",
         "change": "Pre-Release version."},
        {"date": "December 3, 2018", "version": "1.7.1",
         "change": "Release version."},
    ])
    d.setdefault("protocol_variants_described", [
        "TL-UL (TileLink Uncached Lightweight) — minimal Get/Put for low-performance peripherals",
        "TL-UH (TileLink Uncached Heavyweight) — adds atomics, hints, burst messages",
        "TL-C (TileLink Cached) — adds cache-coherence permissions transfer (Acquire/Release/Probe)",
    ])
    d.setdefault("purpose",
        "TileLink is a chip-scale interconnect standard providing multiple "
        "masters with coherent memory-mapped access to memory and other slave "
        "devices. Designed for use in a System-on-Chip (SoC) to connect "
        "general-purpose multiprocessors, co-processors, accelerators, DMA "
        "engines, and simple or complex devices, providing low-latency and "
        "high-throughput transfers. Free and open standard for tightly "
        "coupled, low-latency SoC buses. Designed for RISC-V but supports "
        "other ISAs. Provides a physically addressed, shared-memory system "
        "with verifiable deadlock freedom.")
    d.setdefault("key_features", [
        "Free and open standard for tightly coupled, low-latency SoC buses",
        "Designed for RISC-V but supports other ISAs",
        "Physically addressed, shared-memory system",
        "Implementable over scalable, hierarchically composable, point-to-point networks",
        "Coherent access for an arbitrary mix of caching or non-caching masters",
        "Scales down to simple slave devices or up to high-throughput slaves",
        "Cache-coherent shared memory, supporting a MOESI-equivalent protocol",
        "Verifiable deadlock freedom for any conforming SoC",
        "Out-of-order completion to improve throughput for concurrent operations",
        "Decoupled interfaces, easing register-stage insertion",
        "Stateless bus-width adaptation and burst fragmentation",
        "Power-aware signal encoding",
        "Five-channel architecture (A/B/C/D/E) with strict priority ordering",
        "Symmetric ready/valid handshake on every channel",
        "Hierarchically composable Directed Acyclic Graph (DAG) topology",
    ])
    d.setdefault("conformance_levels_table", [
        {"feature": "Read/Write operations",    "TL-UL": True,  "TL-UH": True, "TL-C": True},
        {"feature": "Multibeat messages",       "TL-UL": False, "TL-UH": True, "TL-C": True},
        {"feature": "Atomic operations",        "TL-UL": False, "TL-UH": True, "TL-C": True},
        {"feature": "Hint operations",          "TL-UL": False, "TL-UH": True, "TL-C": True},
        {"feature": "Cache block transfers",    "TL-UL": False, "TL-UH": False, "TL-C": True},
        {"feature": "Channels B+C+E",           "TL-UL": False, "TL-UH": False, "TL-C": True},
    ])
    d.setdefault("channel_summary", [
        {"channel": "A", "direction": "Master to Slave",
         "purpose": "Request messages sent to an address",
         "tl_level": "Mandatory (all)"},
        {"channel": "B", "direction": "Slave to Master",
         "purpose": "Request messages sent to a cached block",
         "tl_level": "TL-C only"},
        {"channel": "C", "direction": "Master to Slave",
         "purpose": "Response messages from a cached block",
         "tl_level": "TL-C only"},
        {"channel": "D", "direction": "Slave to Master",
         "purpose": "Response messages from an address",
         "tl_level": "Mandatory (all)"},
        {"channel": "E", "direction": "Master to Slave",
         "purpose": "Final handshake for cache block transfer",
         "tl_level": "TL-C only"},
    ])
    d.setdefault("operations_summary", [
        {"operation": "Get",     "type": "Access (A)",   "TL-UL": True,  "TL-UH": True, "TL-C": True,
         "purpose": "read from an address range"},
        {"operation": "Put",     "type": "Access (A)",   "TL-UL": True,  "TL-UH": True, "TL-C": True,
         "purpose": "write to an address range"},
        {"operation": "Atomic",  "type": "Access (A)",   "TL-UL": False, "TL-UH": True, "TL-C": True,
         "purpose": "read-modify-write an address range"},
        {"operation": "Intent",  "type": "Hint (H)",     "TL-UL": False, "TL-UH": True, "TL-C": True,
         "purpose": "advance notification of likely future operations"},
        {"operation": "Acquire", "type": "Transfer (T)", "TL-UL": False, "TL-UH": False, "TL-C": True,
         "purpose": "cache a copy of an address range or increase permissions"},
        {"operation": "Release", "type": "Transfer (T)", "TL-UL": False, "TL-UH": False, "TL-C": True,
         "purpose": "write-back a cached copy or relinquish permissions"},
    ])
    d.setdefault("channel_priority",
        "A < B < C < D < E (increasing priority). Responses always have higher "
        "priority than their initiating requests.")
    d.setdefault("external_signal_count_tl_ul_min", 12)
    d.setdefault("external_signal_count_tl_c_min", 32)
    _write(p, d)


# ============================================================
# L2 FRS
# ============================================================
def _l2(gd: Path) -> None:
    p = gd / "L2_FRS.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("functional_requirements", [
        {"id": "FR-HANDSHAKE-01",
         "text": "Each channel uses a ready/valid handshake. A beat is exchanged only when both ready and valid are HIGH on a rising clock edge.",
         "source": "4.1 Flow Control Rules"},
        {"id": "FR-HANDSHAKE-02",
         "text": "valid must never depend on ready. If a sender wishes to send a beat, it must assert valid independently of whether the receiver signals ready.",
         "source": "4.1 Flow Control Rules"},
        {"id": "FR-HANDSHAKE-03",
         "text": "There must be no combinational path from ready to valid or any of the control and data signals.",
         "source": "4.1 Flow Control Rules"},
        {"id": "FR-CLOCK-01",
         "text": "TileLink is a synchronous bus protocol. Every channel samples its signals on the rising edge of the clock. Both master interface and slave interface on a TileLink link must share the same clock, reset, and power.",
         "source": "3.2 Clocking, Reset, and Power"},
        {"id": "FR-RESET-01",
         "text": "Bus reset is active HIGH. Reset may be asserted asynchronously but must be deasserted synchronous with a rising edge of clock.",
         "source": "3.2.2 Reset"},
        {"id": "FR-RESET-02",
         "text": "Before deasserting reset, a_valid, c_valid, and e_valid must be driven LOW by the master, while b_valid and d_valid must be driven LOW by the slave. The valid signals must be driven LOW for at least 100 cycles while reset is asserted.",
         "source": "3.2.2 Reset"},
        {"id": "FR-BURST-01",
         "text": "It is forbidden in TileLink to interleave the beats of different messages on a channel. Once a burst has begun, the sender must not send beats for any other message until the last beat of the burst has been accepted by the receiver.",
         "source": "Chapter 4 Serialization"},
        {"id": "FR-DEADLOCK-01",
         "text": "TileLink is designed to be deadlock-free by construction. A legal TileLink system must have a Directed Acyclic Graph (DAG) of agents and links. Combined with strict channel prioritization (A < B < C < D < E), deadlock is provably impossible.",
         "source": "4.2 Deadlock Freedom"},
        {"id": "FR-PROGRESS-01",
         "text": "A receiver is under no obligation to present ready HIGH when valid is LOW. When a sender presents valid HIGH, ready must be HIGH unless one of four legitimate exceptions applies (bounded busy period, blocked response to a request, blocked recursive message, blocked response on a sent message).",
         "source": "4.2.2 Forward Progress Rules for Agents"},
        {"id": "FR-BYTELANE-01",
         "text": "TileLink channels which carry a data field always carry payload data little-endian naturally aligned. If the data bus width is w bytes, then (address & !(w-1)) is the address of the data found in the zeroth byte lane.",
         "source": "4.6 Byte Lanes"},
        {"id": "FR-BYTELANE-02",
         "text": "TileLink operations always describe power-of-two-sized byte ranges with an aligned address. On Channels A and B the mask must be LOW for all inactive byte lanes; for messages other than PutPartialData, the bits of mask for all active byte lanes must be HIGH.",
         "source": "4.6 Byte Lanes"},
        {"id": "FR-ERROR-01",
         "text": "C and D channels contain a single-bit error field. The error field can only be raised HIGH a single time within a burst. Once raised HIGH it must remain HIGH for the duration of the burst.",
         "source": "4.5 Errors"},
        {"id": "FR-PRIORITY-01",
         "text": "Within each network link, TileLink defines five logically independent channels. The priority must be strictly enforced: A < B < C < D < E in order of increasing priority.",
         "source": "2.2 Channel Priorities"},
        {"id": "FR-FORWARD-01",
         "text": "Every request message must eventually be answered with a response message. A response message always has higher priority than its initiating request message.",
         "source": "4.2.1 Definitions Used in Rules"},
        {"id": "FR-TLC-PERMS-01",
         "text": "In TL-C, the fundamental permissions for a particular agent's copy of a block are None (N), Branch (B), or Trunk (T). Acquire grows the tree; Release prunes it; Probe forcibly removes copies from a master.",
         "source": "8.1 Implementing Cache Coherence Using TileLink"},
        {"id": "FR-TLC-COHERENCE-01",
         "text": "TileLink supports a MOESI-equivalent coherence protocol. Coherence policies are implementation-defined; the TileLink protocol defines only the substrate (operations + messages + permissions).",
         "source": "Chapter 8 TileLink Cached"},
    ])
    d.setdefault("non_functional_requirements", [
        {"id": "NFR-LATENCY",
         "text": "Low-latency, high-throughput on-chip interconnect optimized for SoC use."},
        {"id": "NFR-DEADLOCK",
         "text": "Provable deadlock-freedom under conformance rules."},
        {"id": "NFR-COMPOSABILITY",
         "text": "Hierarchically composable: TileLink networks can be assembled from per-link master/slave pairs and bridges."},
        {"id": "NFR-POWER",
         "text": "Power-aware signal encoding; channels remain quiescent when no messages are sent."},
        {"id": "NFR-ADAPTABILITY",
         "text": "Stateless bus-width adaptation: messages can be reformatted across bus widths without per-transaction state."},
    ])
    _write(p, d)


# ============================================================
# L3 CMD_PROTOCOL
# ============================================================
def _l3(gd: Path) -> None:
    p = gd / "L3_CMD_PROTOCOL.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("rationale",
        "TileLink is not an 8-bit byte-oriented command protocol. It is a "
        "5-channel concurrent ready/valid protocol where 'commands' are "
        "encoded as multi-bit field tuples on each channel's opcode + param "
        "+ size + source + address. Each channel has an independent opcode "
        "namespace; the same opcode value (e.g. 6) can carry different "
        "meanings on different channels.")
    d.setdefault("channels", [
        {"name": "A", "direction": "Master to Slave",
         "tl_level": "Mandatory (all conformance levels)",
         "signals": ["a_opcode", "a_param", "a_size", "a_source",
                     "a_address", "a_mask", "a_data", "a_valid", "a_ready"]},
        {"name": "B", "direction": "Slave to Master",
         "tl_level": "TL-C only",
         "signals": ["b_opcode", "b_param", "b_size", "b_source",
                     "b_address", "b_mask", "b_data", "b_valid", "b_ready"]},
        {"name": "C", "direction": "Master to Slave",
         "tl_level": "TL-C only",
         "signals": ["c_opcode", "c_param", "c_size", "c_source",
                     "c_address", "c_data", "c_error", "c_valid", "c_ready"]},
        {"name": "D", "direction": "Slave to Master",
         "tl_level": "Mandatory (all conformance levels)",
         "signals": ["d_opcode", "d_param", "d_size", "d_source",
                     "d_sink", "d_data", "d_error", "d_valid", "d_ready"]},
        {"name": "E", "direction": "Master to Slave",
         "tl_level": "TL-C only",
         "signals": ["e_sink", "e_valid", "e_ready"]},
    ])
    d.setdefault("channel_a_opcodes", [
        {"opcode": 0, "message": "PutFullData",    "operation": "Put",     "response": "AccessAck"},
        {"opcode": 1, "message": "PutPartialData", "operation": "Put",     "response": "AccessAck"},
        {"opcode": 2, "message": "ArithmeticData", "operation": "Atomic",  "response": "AccessAckData"},
        {"opcode": 3, "message": "LogicalData",    "operation": "Atomic",  "response": "AccessAckData"},
        {"opcode": 4, "message": "Get",            "operation": "Get",     "response": "AccessAckData"},
        {"opcode": 5, "message": "Intent",         "operation": "Intent",  "response": "HintAck"},
        {"opcode": 6, "message": "Acquire",        "operation": "Acquire", "response": "Grant or GrantData"},
    ])
    d.setdefault("channel_b_opcodes", [
        {"opcode": 0, "message": "PutFullData",    "operation": "Put"},
        {"opcode": 1, "message": "PutPartialData", "operation": "Put"},
        {"opcode": 2, "message": "ArithmeticData", "operation": "Atomic"},
        {"opcode": 3, "message": "LogicalData",    "operation": "Atomic"},
        {"opcode": 4, "message": "Get",            "operation": "Get"},
        {"opcode": 5, "message": "Intent",         "operation": "Intent"},
        {"opcode": 6, "message": "Probe",          "operation": "Probe",
         "response": "ProbeAck or ProbeAckData"},
    ])
    d.setdefault("channel_c_opcodes", [
        {"opcode": 0, "message": "AccessAck",      "operation": "Put response"},
        {"opcode": 1, "message": "AccessAckData",  "operation": "Get/Atomic response"},
        {"opcode": 2, "message": "HintAck",        "operation": "Intent response"},
        {"opcode": 4, "message": "ProbeAck",       "operation": "Acquire (Probe response)"},
        {"opcode": 5, "message": "ProbeAckData",   "operation": "Acquire (Probe response with data)"},
        {"opcode": 6, "message": "Release",        "operation": "Release",  "response": "ReleaseAck"},
        {"opcode": 7, "message": "ReleaseData",    "operation": "Release",  "response": "ReleaseAck"},
    ])
    d.setdefault("channel_d_opcodes", [
        {"opcode": 0, "message": "AccessAck",      "operation": "Put response"},
        {"opcode": 1, "message": "AccessAckData",  "operation": "Get/Atomic response"},
        {"opcode": 2, "message": "HintAck",        "operation": "Intent response"},
        {"opcode": 4, "message": "Grant",          "operation": "Acquire response",
         "response": "GrantAck"},
        {"opcode": 5, "message": "GrantData",      "operation": "Acquire response with data",
         "response": "GrantAck"},
        {"opcode": 6, "message": "ReleaseAck",     "operation": "Release ack"},
    ])
    d.setdefault("channel_e_opcodes", [
        {"opcode": None, "message": "GrantAck", "operation": "Acquire",
         "description": "Channel E carries only e_sink + e_valid + e_ready (no opcode field). Used to acknowledge Grant/GrantData and serialize TL-C transactions."},
    ])
    d.setdefault("param_field_arithmeticdata", [
        {"name": "MIN",  "param": 0, "effect": "Write the signed minimum; return old value."},
        {"name": "MAX",  "param": 1, "effect": "Write the signed maximum; return old value."},
        {"name": "MINU", "param": 2, "effect": "Write the unsigned minimum; return old value."},
        {"name": "MAXU", "param": 3, "effect": "Write the unsigned maximum; return old value."},
        {"name": "ADD",  "param": 4, "effect": "Write the sum; return old value."},
    ])
    d.setdefault("param_field_logicaldata", [
        {"name": "XOR",  "param": 0, "effect": "Bitwise XOR; return old value."},
        {"name": "OR",   "param": 1, "effect": "Bitwise OR; return old value."},
        {"name": "AND",  "param": 2, "effect": "Bitwise AND; return old value."},
        {"name": "SWAP", "param": 3, "effect": "Swap the two operands; return old value."},
    ])
    d.setdefault("param_field_intent", [
        {"name": "PrefetchRead",  "param": 0,
         "effect": "Issuing agent intends to read target data."},
        {"name": "PrefetchWrite", "param": 1,
         "effect": "Issuing agent intends to write target data."},
    ])
    d.setdefault("param_field_permissions_categories", {
        "Permissions": ["None (N)", "Branch (B)", "Trunk (T)"],
        "Cap":    ["toT", "toB", "toN"],
        "Grow":   ["NtoB", "NtoT", "BtoT"],
        "Prune":  ["TtoB", "TtoN", "BtoN"],
        "Report": ["TtoT", "BtoB", "NtoN"],
    })
    d.setdefault("request_response_pairing", [
        {"request": "Get",            "channel_req": "A", "response": "AccessAckData",          "channel_resp": "D"},
        {"request": "PutFullData",    "channel_req": "A", "response": "AccessAck",              "channel_resp": "D"},
        {"request": "PutPartialData", "channel_req": "A", "response": "AccessAck",              "channel_resp": "D"},
        {"request": "ArithmeticData", "channel_req": "A", "response": "AccessAckData",          "channel_resp": "D"},
        {"request": "LogicalData",    "channel_req": "A", "response": "AccessAckData",          "channel_resp": "D"},
        {"request": "Intent",         "channel_req": "A", "response": "HintAck",                "channel_resp": "D"},
        {"request": "Acquire",        "channel_req": "A", "response": "Grant or GrantData",     "channel_resp": "D"},
        {"request": "Probe",          "channel_req": "B", "response": "ProbeAck or ProbeAckData","channel_resp": "C"},
        {"request": "Release",        "channel_req": "C", "response": "ReleaseAck",             "channel_resp": "D"},
        {"request": "ReleaseData",    "channel_req": "C", "response": "ReleaseAck",             "channel_resp": "D"},
        {"request": "GrantAck",       "channel_req": "E", "response": None,                     "channel_resp": None},
    ])
    _write(p, d)


# ============================================================
# L4 REGMAP — N/A
# ============================================================
def _l4(gd: Path) -> None:
    p = gd / "L4_REGMAP.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("register_map_present", False)
    d.setdefault("rationale",
        "TileLink is a chip-scale interconnect protocol, not a peripheral "
        "with an MMIO register file. There is no fixed register map in the "
        "spec. TileLink carries the integrator-defined slave address on "
        "a_address / b_address / c_address. Address-space properties "
        "(cacheability, FIFO ordering, executeability, privilege, QoS) are "
        "configured per-address-region by the SoC integrator.")
    d.setdefault("address_side_field_widths", {
        "a_z_size_log2_bytes":   "z bits (per-link parameter)",
        "a_o_source_id_width":   "o bits (per-link, unique per master interface)",
        "d_i_sink_id_width":     "i bits (per-link, unique per slave interface)",
        "a_a_address_width":     "a bits (per-link, carries byte address)",
        "w_data_bus_width":      "w bytes (power of two, per-link)",
    })
    d.setdefault("address_space_properties", [
        "TileLink conformance level (TL-UL / TL-UH / TL-C)",
        "Memory consistency model",
        "Cacheability",
        "FIFO ordering requirements (optional FIFO domain identifier)",
        "Executeability",
        "Privilege level",
        "Quality-of-Service guarantees",
    ])
    # v0.1.86 — TileLink synth is authoritative; overwrite any AXI-flavored
    # `notes` (AxADDR/AxREGION/AxQOS) the universal bus-interconnect
    # extractor may have set.
    d["notes"] = (
        "If a future system-integration L4 is required, the canonical "
        "'address-side fields' to capture would be: address-map regions "
        "per slave, per-region TileLink conformance level, per-region "
        "cacheability / FIFO / executeability / privilege / QoS, source "
        "ID width (o bits per master interface), sink ID width (i bits "
        "per slave interface), address width (a bits per link), and data "
        "bus width (w bytes per link). The TileLink protocol spec itself "
        "carries no architectural register map; implementation-side "
        "configuration registers (if any) are exposed through the second "
        "TileLink agent inside an interconnect module rather than via "
        "this layer.")
    _write(p, d)


# ============================================================
# L5 ADI_SPEC — N/A
# ============================================================
def _l5(gd: Path) -> None:
    p = gd / "L5_ADI_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("analog_digital_interface_present", False)
    d.setdefault("rationale",
        "TileLink is a purely digital, synchronous on-chip interconnect "
        "protocol. It does not specify any analog signaling, DC electrical "
        "specifications, AC timing parameters (Vih/Vil/tsu/th/etc.), or IO "
        "standards (LVCMOS / LVDS / etc.). All channels are defined in terms "
        "of logical levels sampled on the rising edge of the shared clock "
        "signal.")
    d.setdefault("signaling_summary", {
        "clock": "Single 'clock' input signal per TileLink link; both master and slave sample on the rising edge.",
        "reset": "Single 'reset' input signal, active HIGH; may be asserted asynchronously, must be deasserted synchronous with rising clock.",
        "signal_naming_convention": "All TileLink signals other than clock and reset consist of the channel identifier (a-e) followed by an underscore followed by the signal name. For devices with multiple TileLink interfaces, signal names should be prefixed with a descriptive token plus underscore.",
        "io_count_per_channel": "Each channel is unidirectional. Bus is non-tristate.",
        "default_state_during_reset": "All valid signals must be LOW during reset for at least 100 cycles; ready/control/data signals are free to take any value during reset.",
    })
    d.setdefault("notes",
        "Per-implementation electrical specs (clock period, IO standards, "
        "signal integrity, max-skew, max-fanout) are defined by the SoC "
        "integrator outside the TileLink protocol spec. The TileLink "
        "Specification 1.7.1 is a purely logical / cycle-level spec; it "
        "defines what each signal does on each rising clock edge but does "
        "not constrain any analog parameter. Drive strengths, voltage "
        "levels, IO buffer type (LVCMOS / LVDS), pad capacitance, and "
        "noise margin budgets are all integration choices.")
    _write(p, d)


# ============================================================
# L6 CONTROL_LOGIC
# ============================================================
def _l6(gd: Path) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    fsm = _ensure_dict(d, "fsm_hints")
    fsm.setdefault("per_beat_handshake", [
        "valid HIGH presents control + data fields.",
        "ready HIGH indicates receiver accepts the beat at the next rising clock edge.",
        "A beat is exchanged only when both valid and ready are HIGH at the rising clock edge.",
        "valid must not depend on ready (no combinational path from ready to valid or any control/data signal).",
        "Receivers may drive ready in response to valid, but it is recommended that ready be driven independently to reduce handshaking-circuit depth.",
    ])
    fsm.setdefault("burst_in_progress_rules", [
        "A burst is in progress after the first beat has been accepted and until the last beat has been accepted.",
        "When in progress, if valid is HIGH the sender must present only beats from the same message burst.",
        "Control signals are identical to those of the first beat (size, source, address, opcode, param).",
        "Data signals correspond to the previous beat's address plus the data bus width in bytes.",
        "Final signals (c_error / d_error) change only once within each burst.",
    ])
    fsm.setdefault("reset_protocol_fsm", [
        "RESET asserted (HIGH): master drives a_valid=0, c_valid=0, e_valid=0; slave drives b_valid=0, d_valid=0; held LOW for at least 100 cycles.",
        "RESET deasserted (synchronous with rising clock edge while reset was HIGH).",
        "First rising clock edge after reset deassertion: valid signals may now be driven HIGH.",
    ])
    fsm.setdefault("channel_priority_fsm_rule",
        "Sender must respect strict channel priority A < B < C < D < E when "
        "allocating internal resources / arbiters. Higher-priority messages "
        "must be able to bypass lower-priority ones, even when targeting the "
        "same agent.")
    fsm.setdefault("forward_progress_legitimate_low_ready", [
        "1. Bounded busy period: receiver enters a fixed-cycle busy window, between busy periods must accept at least one beat.",
        "2. Blocked response: while a response on channel X is being rejected, the responding agent may lower ready on all channels with priority <= X.",
        "3. Blocked recursive message: while a recursive request from channel X is being rejected, the sender may lower ready on all channels with priority <= X.",
        "4. Blocked sent response: while a response on channel X has not been received, the receiver may lower ready on all channels with priority <= X.",
    ])

    tlc = _ensure_dict(d, "tl_c_transfer_fsm")
    tlc.setdefault("acquire_flow", [
        "M sends Acquire (channel A, opcode 6, param Grow {NtoB, NtoT, BtoT}).",
        "S optionally probes other masters (channel B Probe + channel C ProbeAck/ProbeAckData).",
        "S sends Grant or GrantData (channel D, opcode 4 or 5, param Cap {toT, toB, toN}).",
        "M sends GrantAck (channel E) to finalize transaction.",
    ])
    tlc.setdefault("release_flow", [
        "M sends Release (channel C, opcode 6, param Prune {TtoB, TtoN, BtoN}) or ReleaseData (opcode 7) to write back dirty data.",
        "S sends ReleaseAck (channel D, opcode 6).",
    ])
    tlc.setdefault("probe_flow", [
        "S sends Probe (channel B, opcode 6, param Cap {toN, toB, toT}).",
        "M sends ProbeAck (channel C, opcode 4) or ProbeAckData (opcode 5) with Shrink {TtoB, TtoN, BtoN} or Report {TtoT, BtoB, NtoN}.",
    ])
    tlc.setdefault("concurrency_rules", [
        "Master should not issue an Acquire if there is a pending Grant on the block.",
        "Slave should not issue a Grant if there is a pending ProbeAck on the block.",
        "Master should not issue a Release if there is a pending Grant on the block.",
        "Slave should not issue a Probe if there is a pending GrantAck on the block.",
    ])
    tlc.setdefault("permissions_state_machine", [
        "States: Nothing (N), Trunk (T — read perms, on path to Tip), Tip (TT — read+write, root of address), Branch (B — read-only shared copy).",
        "Acquire grows the tree from N to B/T or B to T.",
        "Probe shrinks the tree from T to B/N or B to N.",
        "Release voluntarily prunes from T to B/N or B to N.",
    ])

    d.setdefault("operation_taxonomy_fsm", {
        "access_operations": "Get / Put / Atomic — request/response pair, may interleave.",
        "hint_operations": "Intent — request/response pair, informational only.",
        "transfer_operations": "Acquire / Release / Probe — TL-C only, transfer permissions through the coherence tree.",
    })
    d.setdefault("deadlock_freedom_invariants", [
        "Agent graph is a Directed Acyclic Graph (DAG).",
        "Strict channel priority enforced everywhere: A < B < C < D < E.",
        "Each receiver must respect one of four legitimate low-ready exceptions.",
        "Higher-priority messages may bypass lower-priority ones in transit.",
        "No timeouts within the TileLink network itself.",
        "Bridges to legacy buses (e.g. AXI) must include timeouts.",
    ])
    _write(p, d)


# ============================================================
# L7 TEST_DEBUG — N/A
# ============================================================
def _l7(gd: Path) -> None:
    p = gd / "L7_TEST_DEBUG.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("test_debug_architecture_present", False)
    d.setdefault("rationale",
        "The TileLink Specification 1.7.1 does not define a JTAG / scan / "
        "BIST / MBIST / boundary-scan / debug architecture. There is no "
        "dedicated debug interface in the TileLink protocol. Debug "
        "visibility, if any, must be added by the integrator outside the "
        "spec (e.g. via RISC-V Debug Module, JTAG TAP, or ARM CoreSight on "
        "an SoC that consumes TileLink).")
    d.setdefault("spec_provided_observability", [
        {"name": "d_error bit on channel D",
         "purpose": "Signals that the slave was unable to service the request. May be raised once HIGH within a burst and must stay HIGH for the rest of the burst."},
        {"name": "c_error bit on channel C",
         "purpose": "TL-C. Signals that the master was unable to service the request (e.g. data corruption detected during ProbeAckData write-back)."},
    ])
    d.setdefault("implementation_notes", [
        "Source identifier widths are local to a particular TileLink link, so monitors can use unique inflight (source, channel) pairs to track operations.",
        "GrantAck d_sink + e_sink pairings enable monitors to verify TL-C transaction completion ordering.",
        "Bridges between TileLink and legacy buses must include timeouts; these timeouts may be observed for fault-injection / monitoring.",
        "TileLink only deadlock-free when all agents conform; a watchdog can trigger reset if implementation quality is uncertain.",
    ])
    _write(p, d)


# ============================================================
# L8 RTL_CONSTANTS
# ============================================================
def _l8_rtl_constants(gd: Path) -> None:
    p = gd / "L8_RTL_CONSTANTS.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("per_link_parameters", {
        "w": {
            "description": "Width of the data bus in bytes. Must be a power of two.",
            "signal": "*_data is 8*w bits wide; *_mask is w bits wide (channel A/B).",
            "typical_values": [4, 8, 16, 32, 64],
        },
        "a": {
            "description": "Width of each address field in bits.",
            "signal": "a_address, b_address, c_address",
            "typical_values": [32, 36, 40, 48, 64],
        },
        "z": {
            "description": "Width of each size field in bits. Encodes log2(operation size in bytes).",
            "signal": "a_size, b_size, c_size, d_size",
            "typical_values": [3, 4, 5, 6],
            "max_operation_size_bytes": "2**(2**z - 1) bytes per beat",
        },
        "o": {
            "description": "Number of bits needed to disambiguate per-link master sources.",
            "signal": "a_source, b_source, c_source, d_source",
            "typical_values": [3, 4, 5, 6, 8],
            "note": "Width is local to the link; can vary between links.",
        },
        "i": {
            "description": "Number of bits needed to disambiguate per-link slave sinks.",
            "signal": "d_sink, e_sink",
            "typical_values": [3, 4, 5, 6],
            "note": "Width is local to the link; can vary between links.",
        },
    })
    d.setdefault("fixed_widths", {
        "a_opcode": 3, "b_opcode": 3, "c_opcode": 3, "d_opcode": 3,
        "a_param": 3, "b_param": 3, "c_param": 3, "d_param": 2,
        "c_error": 1, "d_error": 1,
        "clock": 1, "reset": 1,
        "*_valid": 1, "*_ready": 1,
    })
    d.setdefault("channel_a_field_widths", {
        "a_opcode": 3, "a_param": 3, "a_size": "z", "a_source": "o",
        "a_address": "a", "a_mask": "w", "a_data": "8*w",
        "a_valid": 1, "a_ready": 1,
    })
    d.setdefault("channel_b_field_widths", {
        "b_opcode": 3, "b_param": 3, "b_size": "z", "b_source": "o",
        "b_address": "a", "b_mask": "w", "b_data": "8*w",
        "b_valid": 1, "b_ready": 1,
    })
    d.setdefault("channel_c_field_widths", {
        "c_opcode": 3, "c_param": 3, "c_size": "z", "c_source": "o",
        "c_address": "a", "c_data": "8*w", "c_error": 1,
        "c_valid": 1, "c_ready": 1,
    })
    d.setdefault("channel_d_field_widths", {
        "d_opcode": 3, "d_param": 2, "d_size": "z", "d_source": "o",
        "d_sink": "i", "d_data": "8*w", "d_error": 1,
        "d_valid": 1, "d_ready": 1,
    })
    d.setdefault("channel_e_field_widths", {
        "e_sink": "i", "e_valid": 1, "e_ready": 1,
    })
    d.setdefault("constants", {
        "MIN_RESET_CYCLES_VALID_LOW": 100,
        "CHANNEL_PRIORITY_ORDER": "A < B < C < D < E",
    })
    d.setdefault("signal_type_categories", [
        {"type": "X", "description": "Clock or reset signal",                 "direction": "Input"},
        {"type": "C", "description": "Control signals, constant within burst","direction": "Channel direction"},
        {"type": "D", "description": "Data signals, change each beat",        "direction": "Channel direction"},
        {"type": "F", "description": "Final signals, change once per burst",  "direction": "Channel direction"},
        {"type": "V", "description": "Valid signal",                          "direction": "Channel direction"},
        {"type": "R", "description": "Ready signal",                          "direction": "Reverse direction"},
    ])
    _write(p, d)


# ============================================================
# L8 TIMING_WAVEFORM
# ============================================================
def _l8_timing_waveform(gd: Path) -> None:
    p = gd / "L8_TIMING_WAVEFORM.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("clock_and_reset_waveform", {
        "clock": "Single rising-edge clock per TileLink link, shared by master and slave interfaces. All signal timings relate to the rising edge.",
        "reset": "Active HIGH. May be asserted asynchronously; must be deasserted synchronous with rising clock edge. Drive valid signals LOW for at least 100 cycles during reset.",
        "reference_section": "3.2 Clocking, Reset, and Power",
    })
    d.setdefault("basic_handshake_waveform", {
        "case": "Single-beat Get request on channel A and AccessAckData response on channel D",
        "sequence": [
            "T0: master drives a_valid=1, a_opcode=4 (Get), a_address=A, a_size=size, a_source=S; slave drives a_ready=1.",
            "T1 (rising edge): handshake completes; slave samples request.",
            "Tk (arbitrary delay): slave drives d_valid=1, d_opcode=1 (AccessAckData), d_source=S, d_data=data; master drives d_ready=1.",
            "Tk+1 (rising edge): master samples response.",
        ],
        "reference_figure": "Figure 6.1 / Figure 6.2",
    })
    d.setdefault("burst_request_waveform", {
        "case": "PutFullData (opcode 0) with size=5 (32 bytes) on an 8-byte data bus → 4 beats",
        "sequence": [
            "T0: master drives a_valid=1, a_opcode=0, a_size=5, a_data=beat0, a_mask=0xFF.",
            "T0..T1: until a_ready=1, master continues to present a_valid=1 with beat0.",
            "After beat0 accepted: a_valid=1 with beat1, a_address unchanged, a_data=beat1.",
            "After beat1 accepted: beat2, beat3.",
            "After beat3 (last beat) accepted: burst complete; master may begin next message.",
            "Slave then sends AccessAck (single-beat) on channel D.",
        ],
        "reference_figure": "Figure 4.4 Max and min delay between a PutFullData (0) and an AccessAck (0)",
    })
    d.setdefault("burst_response_waveform", {
        "case": "Get (opcode 4) request size=5 (32 bytes) → AccessAckData burst response on 8-byte channel D (4 beats)",
        "sequence": [
            "T0: master a_valid=1, a_opcode=4 (Get), a_size=5; single-beat request, accepted immediately when a_ready=1.",
            "Tk (arbitrary delay): slave drives d_valid=1, d_opcode=1 (AccessAckData), d_data=beat0; master drives d_ready=1.",
            "Tk+1..Tk+3: subsequent beats beat1, beat2, beat3; beats may not be interleaved with other messages.",
        ],
        "reference_figure": "Figure 4.3 Max and min delay between a Get (4) and an AccessAckData (1)",
    })
    d.setdefault("atomic_waveform", {
        "case": "ArithmeticData ADD on 16-byte operand (size=4) on 8-byte bus (2-beat request, 2-beat response)",
        "sequence": [
            "T0..T1: master sends 2 beats of ArithmeticData (a_opcode=2, a_param=4 ADD).",
            "Tk..Tk+1: slave performs read-modify-write at backing memory, sends 2 beats of AccessAckData.",
            "Response beats may overlap request beats.",
        ],
        "reference_figure": "Figure 4.5 Delay between an ArithmeticData (2) and an AccessAckData (1)",
    })
    d.setdefault("tl_c_acquire_waveform", {
        "case": "Master Acquire (NtoT) followed by Grant + GrantAck",
        "sequence": [
            "M sends Acquire on channel A (a_opcode=6, a_param=NtoT).",
            "S optionally Probes other masters on channel B; M sends ProbeAck/ProbeAckData on channel C.",
            "S sends Grant on channel D (d_opcode=4, d_param=toT) with d_sink=K.",
            "M sends GrantAck on channel E (e_sink=K).",
        ],
        "reference_figure": "Figure 8.3 Overview of a transaction flow containing all three transfer operations",
    })
    _blw = d.setdefault("byte_lanes_waveform", {})
    _blw.setdefault("case", "Byte-lane data layout")
    _blw.setdefault("rule",
        "If data bus width = w bytes, then (address & !(w-1)) is the "
        "address of the data in the zeroth byte lane. Byte lanes are "
        "little-endian naturally aligned.")
    _blw.setdefault("reference_figure",
        "Figure 4.6 Example of the mask bits carried by byte lanes")
    _blw.setdefault("mask_examples", [
        {"opcode": "PutFullData (0)", "size": 3,
         "a_mask_first_beat": "0xFF (8-byte op covers all of 8-byte bus)"},
        {"opcode": "PutPartialData (1)", "size": 3,
         "a_mask_first_beat": "0xFC (top 6 bytes only)"},
        {"opcode": "Get (4)", "size": 3,
         "a_mask_first_beat": "0xFF (mask drives all active byte lanes HIGH even though Get carries no payload)"},
    ])
    d.setdefault("max_min_delay_rules", [
        "First beat of response message may be presented on the same cycle the first beat of the request message is accepted, but not before.",
        "Response beats may be delayed for an arbitrarily long time.",
        "Response beats may be presented before all beats of a burst request have been accepted.",
    ])
    _write(p, d)


# ============================================================
# L9 INTEGRATION_SPEC
# ============================================================
def _l9(gd: Path) -> None:
    p = gd / "L9_INTEGRATION_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("interconnect_topology_options", [
        "Point-to-point single master + single slave (Figure 2.1).",
        "Crossbar with one slave port and multiple master ports.",
        "Hierarchical: master → crossbar → cache → memory controller (Figure 2.2).",
        "Crossbar module containing multiple agents (Figure 2.3).",
        "Clock-domain crossing via a TileLink-to-TileLink adapter.",
        "Power-domain crossing via a TileLink-to-TileLink adapter.",
        "Legacy-bus bridging: TileLink-to-AXI / AHB / APB / PCIe bridges.",
    ])
    d.setdefault("interconnect_rules", [
        "Pairs of agents are connected by links. One end connects to a master interface; the other connects to a slave interface.",
        "Any topology that can be described as a Directed Acyclic Graph (DAG) is a legal topology.",
        "Agents are graph vertices; links are graph edges directed from master interface to slave interface.",
        "A single hardware module may contain multiple independent TileLink agents.",
        "Both ends of a TileLink link must share the same clock / reset / power.",
        "It is forbidden for one side of a TileLink link to power down while its opposite is powered on.",
    ])
    d.setdefault("agents_and_links_definitions", {
        "operation": "A change to an address range's data values, permissions or location in the memory hierarchy.",
        "agent": "An active participant in the protocol that sends and receives messages.",
        "channel": "A one-way communication connection between a master interface and a slave interface.",
        "message": "A set of control and data values sent over a particular channel.",
        "link": "The set of channels required to complete operations between two agents.",
        "master_interface": "Initiates request messages; receives response messages.",
        "slave_interface": "Receives request messages; sends response messages.",
        "DAG_topology_rule": "A legal TileLink system must have a directed acyclic agent graph.",
    })
    d.setdefault("address_map_recommendations", [
        "Local address map describes which regions of memory have side effects (cacheability, FIFO, executeability, privilege, QoS).",
        "Recommend the address map not be a single global map — properties may change per agent or per region; each agent should be aware of its locally-relevant subset.",
        "Address ranges should be aligned and partitioned by attribute (cacheable / device / configuration); attributes can be enforced by checking the TL message against local address-region tables.",
        "When the address falls outside any decoded region, the slave (or interconnect) should respond with an error.",
        "Address maps and per-region access permissions are programmed at SoC integration time and are out of scope of the wire-level TileLink spec.",
    ])
    d.setdefault("request_response_ordering_rules", [
        "Operations may complete out-of-order; multiple operations may be inflight at any given time (Figure 5.3).",
        "Slaves only send a response message once the effect of the operation is completed.",
        "Responses on a given channel may be returned in any order if the source IDs differ.",
        "Responses with the same source ID must be returned in the order they were issued.",
        "Bursts cannot be interleaved with other messages on the same channel.",
        "TileLink does not require any specific ordering between channels other than the dependency arrows in the channel-dependency diagram.",
    ])
    d.setdefault("source_sink_id_management", [
        "source IDs uniquely identify inflight requests; local to a link.",
        "Within a channel each inflight identifier must be unique; once a response is received the id may be reused.",
        "Channel A and C requests can share source ID values across channels.",
        "Channel D Grant responses must provide unique d_sink IDs; channel E GrantAck uses e_sink to acknowledge.",
        "ID widths (o, i) can vary between links. Crossbars must remap source IDs.",
    ])
    d.setdefault("legacy_bus_bridging_rules", [
        "TileLink-to-legacy-bus bridges must include a timeout to fit within the first forward-progress rule.",
        "If a legacy bus does not accept a request within the timeout, the bridge must discard the request and inject a TileLink error response.",
        "If a legacy bus exceeds the response timeout, the bridge must cancel the outstanding request and inject a TileLink error response.",
    ])
    d.setdefault("burst_in_progress_constraints", [
        "Bursts cannot be interleaved with beats of other messages on the same channel.",
        "Control signals (opcode/param/size/source/address) constant across all beats of a burst.",
        "Data addresses auto-increment per beat by the data bus width.",
        "Final signals (c_error, d_error) may change at most once per burst and must stay HIGH once asserted.",
    ])
    _write(p, d)


# ============================================================
# L10 TEST_CASES
# ============================================================
def _l10(gd: Path) -> None:
    p = gd / "L10_TEST_CASES.json"
    if not p.is_file():
        return
    d = _read(p)
    # v0.1.86 — TileLink synth is authoritative; overwrite any earlier
    # ASCII-dash variant emitted by the universal extractor.
    d["test_cases_present"] = (
        "partial — spec describes protocol-compliance requirements and "
        "example waveforms; no formal verification plan is included.")
    d.setdefault("derived_compliance_test_categories", [
        {"id": "TC-TL-RESET",            "name": "Reset behavior"},
        {"id": "TC-TL-UL-GET",           "name": "TL-UL Get single beat"},
        {"id": "TC-TL-UL-PUTFULL",       "name": "TL-UL PutFullData single beat"},
        {"id": "TC-TL-UL-PUTPARTIAL",    "name": "TL-UL PutPartialData byte-strobed"},
        {"id": "TC-TL-UH-ATOMIC-ARITH",  "name": "TL-UH ArithmeticData {MIN/MAX/MINU/MAXU/ADD}"},
        {"id": "TC-TL-UH-ATOMIC-LOGIC",  "name": "TL-UH LogicalData {XOR/OR/AND/SWAP}"},
        {"id": "TC-TL-UH-INTENT",        "name": "TL-UH Intent / HintAck"},
        {"id": "TC-TL-UH-BURST-GET",     "name": "TL-UH burst Get"},
        {"id": "TC-TL-UH-BURST-PUT",     "name": "TL-UH burst PutFullData / PutPartialData"},
        {"id": "TC-TL-C-ACQUIRE-NTOT",   "name": "TL-C Acquire NtoT followed by Grant + GrantAck"},
        {"id": "TC-TL-C-ACQUIRE-NTOB",   "name": "TL-C Acquire NtoB followed by GrantData + GrantAck"},
        {"id": "TC-TL-C-PROBE-CAP",      "name": "TL-C Probe forcing master to cap permissions"},
        {"id": "TC-TL-C-RELEASE",        "name": "TL-C voluntary Release"},
        {"id": "TC-TL-DEADLOCK-PRIORITY","name": "Channel priority enforcement"},
        {"id": "TC-TL-BURST-INTERLEAVE-FORBIDDEN", "name": "Burst beats may not be interleaved"},
        {"id": "TC-TL-ERROR-BIT",        "name": "c_error / d_error sticky-after-rise"},
        {"id": "TC-TL-BYTE-LANES",       "name": "Byte-lane layout little-endian naturally aligned"},
        {"id": "TC-TL-SOURCE-UNIQUE",    "name": "Source identifier uniqueness in-flight"},
        {"id": "TC-TL-LEGACY-BRIDGE-TIMEOUT", "name": "Legacy-bus bridge timeout"},
        {"id": "TC-TL-FORWARD-PROGRESS", "name": "Forward-progress 4-rule legitimate-low-ready coverage"},
    ])
    d.setdefault("verification_methodology_notes", [
        "Industry implementations (SiFive Diplomacy, Rocket Chip, BOOM) include TLMonitor SystemVerilog protocol-checker modules.",
        "Random-instruction Bringup tests exercise TL-UL/TL-UH/TL-C flows through the cache hierarchy.",
        "Coherence-policy verification (MOESI-equivalent) is performed against the spec's permissions state machine plus a chosen policy.",
    ])
    _write(p, d)


# ============================================================
# L11 OTP_CONTENT — N/A
# ============================================================
def _l11(gd: Path) -> None:
    p = gd / "L11_OTP_CONTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("otp_present", False)
    d.setdefault("rationale",
        "TileLink is a chip-scale interconnect protocol specification. It "
        "has no one-time-programmable fuses, factory-trim values, or "
        "calibration codes at the protocol layer. Not applicable.")
    _write(p, d)


# ============================================================
# L12 BEHAVIORAL_SEQUENCES
# ============================================================
def _l12(gd: Path) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("tl_ul_get_sequence", [
        "1. Master drives a_valid=1, a_opcode=4 (Get), a_param=0, a_size=size, a_source=S, a_address=A, a_mask=byte_lane_mask.",
        "2. Slave drives a_ready=1; handshake completes at next rising clock edge.",
        "3. Slave reads backing memory.",
        "4. Slave drives d_valid=1, d_opcode=1 (AccessAckData), d_param=0, d_size=size, d_source=S, d_data=data, d_error=0/1.",
        "5. Master drives d_ready=1; handshake completes; master samples response.",
    ])
    d.setdefault("tl_ul_put_sequence", [
        "1. Master drives a_valid=1, a_opcode=0 (PutFullData) or 1 (PutPartialData), a_size=size, a_source=S, a_address=A, a_mask, a_data.",
        "2. Slave drives a_ready=1; handshake completes.",
        "3. Slave writes backing memory.",
        "4. Slave drives d_valid=1, d_opcode=0 (AccessAck), d_size=size, d_source=S, d_error=0/1.",
        "5. Master drives d_ready=1; handshake completes.",
    ])
    d.setdefault("tl_uh_atomic_sequence", [
        "1. Master drives a_valid=1, a_opcode=2 (ArithmeticData) or 3 (LogicalData), a_param=op, a_data=operand.",
        "2. Slave drives a_ready=1; if size>w*8, burst all beats.",
        "3. Slave atomically reads old value, applies op, writes new value.",
        "4. Slave drives d_valid=1, d_opcode=1 (AccessAckData), d_data=old_value.",
        "5. Master drives d_ready=1.",
    ])
    d.setdefault("tl_uh_intent_sequence", [
        "1. Master drives a_valid=1, a_opcode=5 (Intent), a_param=0 (PrefetchRead) or 1 (PrefetchWrite).",
        "2. Slave drives a_ready=1; slave may process or ignore the hint.",
        "3. Slave drives d_valid=1, d_opcode=2 (HintAck).",
        "4. Master drives d_ready=1.",
    ])
    d.setdefault("tl_c_acquire_full_flow", [
        "1. Master M sends Acquire on channel A (a_opcode=6, a_param=NtoT, a_size=block_size).",
        "2. Slave S has master B with current Trunk permissions; S sends Probe on channel B to B (b_opcode=6, b_param=toN).",
        "3. Master B responds on channel C with ProbeAckData (c_opcode=5, c_param=TtoN, c_data=dirty_data).",
        "4. Slave S writes back data to backing memory (if needed).",
        "5. Slave S sends Grant on channel D to M (d_opcode=4, d_param=toT, d_sink=K).",
        "6. Master M sends GrantAck on channel E (e_sink=K) to finalize the transaction.",
    ])
    d.setdefault("tl_c_release_sequence", [
        "1. Master M evicts a clean block: sends Release on channel C (c_opcode=6, c_param=TtoN).",
        "2. Slave S sends ReleaseAck on channel D (d_opcode=6).",
        "1'. OR Master M evicts a dirty block: sends ReleaseData on channel C (c_opcode=7, c_param=TtoN, c_data=dirty_data).",
        "2'. Slave S writes back to backing memory and sends ReleaseAck.",
    ])
    d.setdefault("tl_c_probe_sequence", [
        "1. Slave S decides to probe master M for an address: sends Probe on channel B (b_opcode=6, b_param=toN/toB/toT).",
        "2. Master M evaluates current permissions for that block.",
        "3. Master M sends ProbeAck on channel C (c_opcode=4) if no dirty data, c_param from Shrink/Report.",
        "3'. OR Master M sends ProbeAckData on channel C (c_opcode=5) with dirty data, c_param from Shrink/Report.",
    ])
    d.setdefault("tl_uh_burst_get_sequence", [
        "1. Master drives a_valid=1, a_opcode=4 (Get), a_size=5 (32 bytes on 8-byte bus).",
        "2. Slave drives a_ready=1; request is single-beat (Get has no data) and accepted at next rising clock edge.",
        "3. Slave reads 32 bytes from backing memory at the address.",
        "4. Slave drives d_valid=1, d_opcode=1 (AccessAckData), d_size=5, beat 0 of data.",
        "5. Master drives d_ready=1; subsequent rising-clock edges present beats 1, 2, 3 of d_data.",
        "6. Beats may not be interleaved with other messages on the same channel.",
        "7. After the final beat is accepted, the burst response is complete.",
    ])
    d.setdefault("tl_uh_burst_put_sequence", [
        "1. Master drives a_valid=1, a_opcode=0 (PutFullData), a_size=5; presents beat 0.",
        "2. Slave drives a_ready=1; beats 1, 2, 3 follow with constant a_address / a_size / a_source / a_opcode and incrementing data.",
        "3. After the final beat is accepted, the master may begin the next message.",
        "4. Slave writes all 32 bytes to backing memory at the address.",
        "5. Slave drives d_valid=1, d_opcode=0 (AccessAck), d_size=5; single-beat response on channel D.",
        "6. Master drives d_ready=1; handshake completes.",
    ])
    d.setdefault("tl_c_interleaved_probe_acquire_flow", [
        "Master A sends Acquire (delayed in network).",
        "Master B sends Acquire (arrives at slave first, serialized first).",
        "Slave probes Master A (must probe to revoke A's permissions before granting to B).",
        "Master A ProbeAck (or ProbeAckData if dirty) is observed by Slave.",
        "Slave sends Grant to Master B.",
        "Master B sends GrantAck (transaction B closes).",
        "Slave now serves Master A's original Acquire.",
        "Slave probes Master B, B ProbeAcks, Slave Grants A, A GrantAcks.",
        "Both transactions serialized but interleaved by interconnect ordering.",
    ])
    d.setdefault("tl_c_release_during_acquire_flow", [
        "Master A sends Acquire.",
        "Master B simultaneously evicts the same block: sends voluntary Release.",
        "Slave sends Probe to Master B.",
        "Slave sends Grant to Master A (after observing B's Release).",
        "Master B sends ProbeAck/ProbeAckData — slave merges with the already-received Release (Release+Probe race).",
        "Master B sends ReleaseAck wait completes.",
        "Master A sends GrantAck.",
    ])
    d.setdefault("hierarchical_flow_sequence", [
        "Master --> Hierarchical Agent --> Outer Slave: master sends Get on master-side link.",
        "Hierarchical agent forwards Get on outer link to outer slave (source ID may be remapped).",
        "Outer slave sends AccessAckData on outer link.",
        "Hierarchical agent forwards AccessAckData on master-side link with original source ID.",
        "Master receives AccessAckData; the hierarchy is transparent to the master.",
        "Hierarchical agent acts as one TileLink slave on its master-side and one TileLink master on its outer-side; both ends operate independently but the agent must preserve TileLink-level ordering invariants per (channel, source ID).",
    ])
    _write(p, d)


# ============================================================
# L13 LAB_CALIBRATION — N/A
# ============================================================
def _l13(gd: Path) -> None:
    p = gd / "L13_LAB_CALIBRATION.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("lab_calibration_present", False)
    d.setdefault("rationale",
        "TileLink is a digital bus protocol with no analog content, no "
        "measurement-based calibration, and no lab-trim steps at the "
        "protocol layer. Not applicable.")
    _write(p, d)


# ============================================================
# L14 PROTOCOL_VERSIONING
# ============================================================
def _l14(gd: Path) -> None:
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    _ensure_full(f, "versions", [
        {"release_date": "August 22, 2017",  "issue": "1.7.1-draft",
         "change": "Pre-Release version."},
        {"release_date": "December 3, 2018", "issue": "1.7.1",
         "change": "Release version of TileLink Specification 1.7.1."},
    ])
    f.setdefault("conformance_levels", [
        {"level": "TL-UL", "full_name": "TileLink Uncached Lightweight",
         "supported_operations": ["Get", "Put (PutFullData, PutPartialData)"],
         "channels_used": ["A", "D"],
         "use_case": "Low-performance peripherals, register-mapped slaves; minimizes area."},
        {"level": "TL-UH", "full_name": "TileLink Uncached Heavyweight",
         "supported_operations": ["Get", "Put", "Atomic (ArithmeticData, LogicalData)",
                                  "Intent (PrefetchRead, PrefetchWrite)"],
         "channels_used": ["A", "D"],
         "use_case": "Outermost cache layer, DMA engines, accelerators that need atomics + bursts but not coherence."},
        {"level": "TL-C", "full_name": "TileLink Cached",
         "supported_operations": ["Get", "Put", "Atomic", "Intent", "Acquire", "Release", "Probe"],
         "channels_used": ["A", "B", "C", "D", "E"],
         "use_case": "Cache-coherent multi-processor SoCs; supports MOESI-equivalent coherence."},
    ])
    f.setdefault("deprecated_features", [])
    f.setdefault("backward_compat_traps", [
        {"trap_name": "TL-C agent talking to TL-UL device",
         "issue": "TL-C masters may attempt to use Acquire/Release on a TL-UL slave that does not understand transfer operations.",
         "remediation": "Either the TL-C processor agent must refrain from using advanced features, or a TL-C-to-TL-UL adapter must be placed in the network between them."},
        {"trap_name": "Per-link parameter variability",
         "issue": "Per-link parameters w, a, z, o, i can vary between links in the same SoC.",
         "remediation": "Crossbars must combine source identifiers into a common namespace for the messages they send to slaves."},
        {"trap_name": "TL-UL a_size <= log2(w) only",
         "issue": "In TL-UL, a_size cannot be larger than the width of the physical data bus (no bursts).",
         "remediation": "TL-UH and TL-C allow a_size > log2(w) with burst splitting; conversion adapters must downsize."},
    ])
    f.setdefault("extensibility_notes", [
        "Future editions of the spec reserve the right to add further opcodes.",
        "Within a given channel each possible message type has a unique opcode.",
        "Channel E carries only e_sink + e_valid + e_ready (no opcode), so no encoding-space extension is possible without a spec change.",
    ])
    f.setdefault("adoption_notes", [
        "TileLink is the canonical on-chip interconnect for SiFive RISC-V cores and the Chipyard / Rocket Chip / BOOM open-source RISC-V ecosystem.",
        "Implemented as the SiFive Diplomacy framework which automates per-link parameter negotiation.",
        "Adopted by multiple commercial and academic RISC-V SoCs.",
    ])
    d["fields"] = f
    _write(p, d)


# ============================================================
# L15 ENCODING_TABLES
# ============================================================
def _l15(gd: Path) -> None:
    p = gd / "L15_ENCODING_TABLES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    _ensure_full(f, "tables", [
        {"table_id": "Table 5.2 / 5.3 Channel A opcode",
         "name": "Channel A opcode encoding (a_opcode[2:0])",
         "field_bits": "a_opcode[2:0]",
         "encoding": [
             {"value": "3'd0", "name": "PutFullData",    "operation": "Put",     "response_opcode": "AccessAck (0)"},
             {"value": "3'd1", "name": "PutPartialData", "operation": "Put",     "response_opcode": "AccessAck (0)"},
             {"value": "3'd2", "name": "ArithmeticData", "operation": "Atomic",  "response_opcode": "AccessAckData (1)", "tl_level": "TL-UH+"},
             {"value": "3'd3", "name": "LogicalData",    "operation": "Atomic",  "response_opcode": "AccessAckData (1)", "tl_level": "TL-UH+"},
             {"value": "3'd4", "name": "Get",            "operation": "Get",     "response_opcode": "AccessAckData (1)"},
             {"value": "3'd5", "name": "Intent",         "operation": "Intent",  "response_opcode": "HintAck (2)",       "tl_level": "TL-UH+"},
             {"value": "3'd6", "name": "Acquire",        "operation": "Acquire", "response_opcode": "Grant (4) or GrantData (5)", "tl_level": "TL-C only"},
             {"value": "3'd7", "name": "(reserved)",     "operation": "reserved for future extension"},
         ]},
        {"table_id": "Table 5.3 Channel B opcode",
         "name": "Channel B opcode encoding (b_opcode[2:0])",
         "field_bits": "b_opcode[2:0]",
         "tl_level": "TL-C only",
         "encoding": [
             {"value": "3'd0", "name": "PutFullData",    "operation": "Put"},
             {"value": "3'd1", "name": "PutPartialData", "operation": "Put"},
             {"value": "3'd2", "name": "ArithmeticData", "operation": "Atomic"},
             {"value": "3'd3", "name": "LogicalData",    "operation": "Atomic"},
             {"value": "3'd4", "name": "Get",            "operation": "Get"},
             {"value": "3'd5", "name": "Intent",         "operation": "Intent"},
             {"value": "3'd6", "name": "Probe",          "operation": "Probe"},
         ]},
        {"table_id": "Table 5.3 Channel C opcode",
         "name": "Channel C opcode encoding (c_opcode[2:0])",
         "field_bits": "c_opcode[2:0]",
         "encoding": [
             {"value": "3'd0", "name": "AccessAck",      "operation": "Put response"},
             {"value": "3'd1", "name": "AccessAckData",  "operation": "Get/Atomic response"},
             {"value": "3'd2", "name": "HintAck",        "operation": "Intent response"},
             {"value": "3'd4", "name": "ProbeAck",       "operation": "Acquire (Probe response)",                                       "tl_level": "TL-C only"},
             {"value": "3'd5", "name": "ProbeAckData",   "operation": "Acquire (Probe response with dirty data)",                        "tl_level": "TL-C only"},
             {"value": "3'd6", "name": "Release",        "operation": "Release (voluntary)",                                             "tl_level": "TL-C only"},
             {"value": "3'd7", "name": "ReleaseData",    "operation": "Release with dirty data",                                         "tl_level": "TL-C only"},
         ]},
        {"table_id": "Table 5.3 Channel D opcode",
         "name": "Channel D opcode encoding (d_opcode[2:0])",
         "field_bits": "d_opcode[2:0]",
         "encoding": [
             {"value": "3'd0", "name": "AccessAck",      "operation": "Put response"},
             {"value": "3'd1", "name": "AccessAckData",  "operation": "Get/Atomic response"},
             {"value": "3'd2", "name": "HintAck",        "operation": "Intent response"},
             {"value": "3'd4", "name": "Grant",          "operation": "Acquire response (permission only)",                              "tl_level": "TL-C only"},
             {"value": "3'd5", "name": "GrantData",      "operation": "Acquire response with cache block data",                          "tl_level": "TL-C only"},
             {"value": "3'd6", "name": "ReleaseAck",     "operation": "Release ack",                                                     "tl_level": "TL-C only"},
         ]},
        {"table_id": "Channel E (no opcode field)",
         "name": "Channel E carries only e_sink + e_valid + e_ready",
         "tl_level": "TL-C only",
         "note": "There is no opcode on channel E. The only message is GrantAck, which carries an e_sink to identify the inflight Grant being acknowledged."},
        {"table_id": "Table 7.3 ArithmeticData param",
         "name": "ArithmeticData param encoding (a_param[2:0])",
         "field_bits": "a_param[2:0]",
         "tl_level": "TL-UH+",
         "encoding": [
             {"value": "3'd0", "name": "MIN",  "effect": "Write signed minimum; return old value."},
             {"value": "3'd1", "name": "MAX",  "effect": "Write signed maximum; return old value."},
             {"value": "3'd2", "name": "MINU", "effect": "Write unsigned minimum; return old value."},
             {"value": "3'd3", "name": "MAXU", "effect": "Write unsigned maximum; return old value."},
             {"value": "3'd4", "name": "ADD",  "effect": "Write the sum; return old value."},
         ]},
        {"table_id": "Table 7.5 LogicalData param",
         "name": "LogicalData param encoding (a_param[2:0])",
         "field_bits": "a_param[2:0]",
         "tl_level": "TL-UH+",
         "encoding": [
             {"value": "3'd0", "name": "XOR",  "effect": "Bitwise XOR; return old value."},
             {"value": "3'd1", "name": "OR",   "effect": "Bitwise OR; return old value."},
             {"value": "3'd2", "name": "AND",  "effect": "Bitwise AND; return old value."},
             {"value": "3'd3", "name": "SWAP", "effect": "Swap the two operands; return old value."},
         ]},
        {"table_id": "Table 7.7 Intent param",
         "name": "Intent param encoding (a_param[2:0])",
         "field_bits": "a_param[2:0]",
         "tl_level": "TL-UH+",
         "encoding": [
             {"value": "3'd0", "name": "PrefetchRead",  "effect": "Issuing agent intends to read target data."},
             {"value": "3'd1", "name": "PrefetchWrite", "effect": "Issuing agent intends to write target data."},
         ]},
        {"table_id": "Table 8.3 Permissions transitions categories",
         "name": "Cache permissions transitions categories (TL-C only)",
         "tl_level": "TL-C only",
         "encoding": [
             {"category": "Permissions", "contents": ["N (None)", "B (Branch)", "T (Trunk)"]},
             {"category": "Cap",    "contents": ["toT", "toB", "toN"],
              "used_on": ["Probe (b_param)", "Grant (d_param)", "GrantData (d_param)"]},
             {"category": "Grow",   "contents": ["NtoB", "NtoT", "BtoT"],
              "used_on": ["Acquire (a_param)"]},
             {"category": "Prune",  "contents": ["TtoB", "TtoN", "BtoN"],
              "used_on": ["Release (c_param)", "ReleaseData (c_param)"]},
             {"category": "Report", "contents": ["TtoT", "BtoB", "NtoN"],
              "used_on": ["ProbeAck (c_param)", "ProbeAckData (c_param)"]},
             {"category": "Shrink", "contents": ["TtoB", "TtoN", "BtoN"],
              "used_on": ["ProbeAck (c_param)", "ProbeAckData (c_param)"]},
         ]},
        {"table_id": "Table 3.2 Signal Types",
         "name": "TileLink signal type encoding",
         "encoding": [
             {"type": "X", "description": "Clock or reset signal",                 "direction": "Input"},
             {"type": "C", "description": "Control signals, constant within burst","direction": "Channel direction"},
             {"type": "D", "description": "Data signals, change each beat",        "direction": "Channel direction"},
             {"type": "F", "description": "Final signals, change once per burst",  "direction": "Channel direction"},
             {"type": "V", "description": "Valid signal",                          "direction": "Channel direction"},
             {"type": "R", "description": "Ready signal",                          "direction": "Reverse direction"},
         ]},
        {"table_id": "Table 8.1 Permissions ↔ Supported accesses",
         "name": "Relationship between permissions and access operations (TL-C)",
         "encoding": [
             {"permission": "None",   "supported_accesses": "None"},
             {"permission": "Branch", "supported_accesses": "Get"},
             {"permission": "Trunk",  "supported_accesses": "Get"},
             {"permission": "Tip",    "supported_accesses": "Get, PutPartial, PutFull, Logical, Arithmetic"},
         ]},
    ])
    f.setdefault("size_field_encoding_rule",
        "*_size carries log2(operation size in bytes). For non-burst "
        "messages, log2(w) >= *_size. For burst-capable channels, number "
        "of beats = ceil(2^*_size / w).")
    d["fields"] = f
    _write(p, d)


# ============================================================
# L16 COMPLIANCE_PROPERTIES
# ============================================================
def _l16(gd: Path) -> None:
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f.setdefault("properties", [
        {"id": "p_tl_handshake_valid_independent",
         "scope": "TL_sender",
         "english_form": "valid must never depend on ready. A sender must assert valid independently of whether the receiver signals ready.",
         "citation": "4.1 Flow Control Rules page 18"},
        {"id": "p_tl_handshake_no_comb_path",
         "scope": "TL_sender",
         "english_form": "There must be no combinational path from ready to valid or any of the control and data signals.",
         "citation": "4.1 Flow Control Rules page 18"},
        {"id": "p_tl_burst_no_interleave",
         "scope": "TL_sender",
         "english_form": "It is forbidden to interleave the beats of different messages on a channel.",
         "citation": "Chapter 4 Serialization page 17"},
        {"id": "p_tl_burst_control_constancy",
         "scope": "TL_sender",
         "english_form": "When a burst is in progress, control signals (opcode/param/size/source/address) must remain constant beat-to-beat.",
         "citation": "4.1 Flow Control Rules page 18"},
        {"id": "p_tl_size_address_alignment",
         "scope": "TL_sender_channel_A",
         "english_form": "Address must be aligned to size: (a_address & ((1 << a_size) - 1)) == 0.",
         "citation": "4.6 Byte Lanes page 30"},
        {"id": "p_tl_putfull_mask_all_high",
         "scope": "TL_sender_channel_A",
         "english_form": "For PutFullData, mask bits for all active byte lanes must be HIGH.",
         "citation": "4.6 Byte Lanes / Table 6.3 page 48"},
        {"id": "p_tl_mask_inactive_lanes_low",
         "scope": "TL_sender_channel_A_B",
         "english_form": "mask bits for all inactive byte lanes must be LOW (on channels A and B).",
         "citation": "4.6 Byte Lanes page 30"},
        {"id": "p_tl_reset_valid_low_100cycles",
         "scope": "TL_master_and_slave",
         "english_form": "While reset is asserted, valid signals must be LOW for at least 100 cycles.",
         "citation": "3.2.2 Reset page 11"},
        {"id": "p_tl_response_pairing_d_source_match",
         "scope": "TL_slave",
         "english_form": "Response on channel D must echo a_source: d_source == a_source of paired request.",
         "citation": "5.4 Source and Sink Identifiers page 39"},
        {"id": "p_tl_source_in_flight_unique",
         "scope": "TL_master",
         "english_form": "Inflight a_source identifiers within channel A must be unique.",
         "citation": "5.4 Source and Sink Identifiers page 39"},
        {"id": "p_tl_error_sticky_after_rise",
         "scope": "TL_sender_channel_C_D",
         "english_form": "The error field can only be raised HIGH a single time within a burst, and must remain HIGH for the rest of the burst.",
         "citation": "4.5 Errors page 29"},
        {"id": "p_tl_channel_priority_strict",
         "scope": "TL_receiver",
         "english_form": "Channels A < B < C < D < E in strict priority. Higher-priority messages must be able to bypass lower-priority ones.",
         "citation": "2.2 Channel Priorities page 6"},
        {"id": "p_tl_dag_topology",
         "scope": "TL_network",
         "english_form": "A legal TileLink system must have a directed acyclic agent graph (DAG).",
         "citation": "4.2.3 Topology Rules for Networks page 23"},
        {"id": "p_tl_response_priority_higher_than_request",
         "scope": "TL_network",
         "english_form": "A response message always has higher priority than its initiating request message.",
         "citation": "4.2.1 Definitions Used in Rules page 20"},
        {"id": "p_tl_no_timeout_inside_network",
         "scope": "TL_agent",
         "english_form": "Timeouts that cause alternative messages to be generated are expressly forbidden inside the TileLink network.",
         "citation": "4.4 Interfacing with Legacy Buses page 28"},
        {"id": "p_tl_tl_c_acquire_grow_param_only",
         "scope": "TL_C_master",
         "english_form": "On Acquire (a_opcode=6), a_param must be from the Grow category: {NtoB, NtoT, BtoT}.",
         "citation": "8.3.1 Acquire page 77"},
        {"id": "p_tl_tl_c_probe_cap_param_only",
         "scope": "TL_C_slave",
         "english_form": "On Probe (b_opcode=6), b_param must be from the Cap category: {toN, toB, toT}.",
         "citation": "8.3.2 Probe page 78"},
        {"id": "p_tl_tl_c_release_prune_param_only",
         "scope": "TL_C_master",
         "english_form": "On Release / ReleaseData (c_opcode=6/7), c_param must be from the Prune category: {TtoB, TtoN, BtoN}.",
         "citation": "8.3.8/8.3.9 Release/ReleaseData page 84-85"},
        {"id": "p_tl_tl_c_probeack_shrink_or_report_param",
         "scope": "TL_C_master",
         "english_form": "On ProbeAck / ProbeAckData (c_opcode=4/5), c_param must be from the Shrink or Report category: {TtoB, TtoN, BtoN, TtoT, BtoB, NtoN}.",
         "citation": "8.3.3/8.3.4 ProbeAck/ProbeAckData page 79-80"},
        {"id": "p_tl_tl_c_grant_cap_param_only",
         "scope": "TL_C_slave",
         "english_form": "On Grant / GrantData (d_opcode=4/5), d_param must be from the Cap category: {toT, toB, toN}.",
         "citation": "8.3.5/8.3.6 Grant/GrantData page 81-82"},
        {"id": "p_tl_tl_c_grantack_e_sink_matches",
         "scope": "TL_C_master",
         "english_form": "On GrantAck (channel E), e_sink must match d_sink of the previously received Grant.",
         "citation": "5.4 Source and Sink Identifiers page 39-40"},
        {"id": "p_tl_tl_c_acquire_no_double_issue",
         "scope": "TL_C_master",
         "english_form": "Master should not issue an Acquire if there is a pending Grant on the same block.",
         "citation": "8.2 Flows and Waves page 72"},
        {"id": "p_tl_tl_c_release_no_double_issue",
         "scope": "TL_C_master",
         "english_form": "Master should not issue a Release if there is a pending Grant on the block.",
         "citation": "8.2 Flows and Waves page 72"},
    ])
    d["fields"] = f
    _write(p, d)


# ============================================================
# L17 CHANNEL_SIGNAL_CATALOG
# ============================================================
def _l17(gd: Path) -> None:
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    _ensure_full(f, "global_signals", [
        {"name": "clock", "width": "1", "type": "X", "direction": "Input to both agents",
         "semantics": "Bus clock. Inputs are sampled on the rising edge. Both master and slave use the same clock."},
        {"name": "reset", "width": "1", "type": "X", "direction": "Input to both agents",
         "semantics": "Bus reset. Active HIGH. Asynchronously asserted, synchronously deasserted with rising clock."},
    ])
    _ensure_full(f, "channels", [
        {"name": "A",
         "full_name": "Channel A — Master-to-Slave Request",
         "direction": "Master to Slave",
         "tl_level": "Mandatory (all conformance levels)",
         "purpose": "Carries request messages sent to a particular address.",
         "signals": [
             {"name": "a_opcode",  "width": "3",   "type": "C", "direction": "Master",
              "semantics": "Operation code per Table 5.2."},
             {"name": "a_param",   "width": "3",   "type": "C", "direction": "Master",
              "semantics": "Parameter code; sub-opcode or permissions Grow category."},
             {"name": "a_size",    "width": "z",   "type": "C", "direction": "Master",
              "semantics": "Log2 of operation size in bytes."},
             {"name": "a_source",  "width": "o",   "type": "C", "direction": "Master",
              "semantics": "Unique, per-link master source identifier."},
             {"name": "a_address", "width": "a",   "type": "C", "direction": "Master",
              "semantics": "Target byte address; must be aligned to a_size."},
             {"name": "a_mask",    "width": "w",   "type": "D", "direction": "Master",
              "semantics": "Byte lane select for messages with data."},
             {"name": "a_data",    "width": "8*w", "type": "D", "direction": "Master",
              "semantics": "Data payload for messages with data."},
             {"name": "a_valid",   "width": "1",   "type": "V", "direction": "Master"},
             {"name": "a_ready",   "width": "1",   "type": "R", "direction": "Slave"},
         ]},
        {"name": "B",
         "full_name": "Channel B — Slave-to-Master Request (TL-C only)",
         "direction": "Slave to Master",
         "tl_level": "TL-C only",
         "purpose": "Carries request messages sent to a cached data block held by a master.",
         "signals": [
             {"name": "b_opcode",  "width": "3",   "type": "C", "direction": "Slave"},
             {"name": "b_param",   "width": "3",   "type": "C", "direction": "Slave",
              "semantics": "Cap category {toN, toB, toT} for Probe."},
             {"name": "b_size",    "width": "z",   "type": "C", "direction": "Slave"},
             {"name": "b_source",  "width": "o",   "type": "C", "direction": "Slave"},
             {"name": "b_address", "width": "a",   "type": "C", "direction": "Slave"},
             {"name": "b_mask",    "width": "w",   "type": "D", "direction": "Slave"},
             {"name": "b_data",    "width": "8*w", "type": "D", "direction": "Slave"},
             {"name": "b_valid",   "width": "1",   "type": "V", "direction": "Slave"},
             {"name": "b_ready",   "width": "1",   "type": "R", "direction": "Master"},
         ]},
        {"name": "C",
         "full_name": "Channel C — Master-to-Slave Response/Release (TL-C only)",
         "direction": "Master to Slave",
         "tl_level": "TL-C only",
         "purpose": "Carries response messages to channel-B requests and voluntary write-backs.",
         "signals": [
             {"name": "c_opcode",  "width": "3",   "type": "C", "direction": "Master"},
             {"name": "c_param",   "width": "3",   "type": "C", "direction": "Master",
              "semantics": "Prune category for Release; Shrink or Report for ProbeAck."},
             {"name": "c_size",    "width": "z",   "type": "C", "direction": "Master"},
             {"name": "c_source",  "width": "o",   "type": "C", "direction": "Master"},
             {"name": "c_address", "width": "a",   "type": "C", "direction": "Master"},
             {"name": "c_data",    "width": "8*w", "type": "D", "direction": "Master"},
             {"name": "c_error",   "width": "1",   "type": "F", "direction": "Master",
              "semantics": "Master agent was unable to service the request."},
             {"name": "c_valid",   "width": "1",   "type": "V", "direction": "Master"},
             {"name": "c_ready",   "width": "1",   "type": "R", "direction": "Slave"},
         ]},
        {"name": "D",
         "full_name": "Channel D — Slave-to-Master Response",
         "direction": "Slave to Master",
         "tl_level": "Mandatory (all conformance levels)",
         "purpose": "Carries response messages for channel-A requests, ReleaseAck for channel-C voluntary writebacks, and Grant/GrantData for Acquires.",
         "signals": [
             {"name": "d_opcode",  "width": "3",   "type": "C", "direction": "Slave"},
             {"name": "d_param",   "width": "2",   "type": "C", "direction": "Slave",
              "semantics": "Cap category for Grant/GrantData; reserved 0 elsewhere."},
             {"name": "d_size",    "width": "z",   "type": "C", "direction": "Slave"},
             {"name": "d_source",  "width": "o",   "type": "C", "direction": "Slave",
              "semantics": "Echoes a_source / c_source."},
             {"name": "d_sink",    "width": "i",   "type": "C", "direction": "Slave",
              "semantics": "Unique per-link slave sink identifier; used for GrantAck pairing."},
             {"name": "d_data",    "width": "8*w", "type": "D", "direction": "Slave"},
             {"name": "d_error",   "width": "1",   "type": "F", "direction": "Slave",
              "semantics": "Slave was unable to service the request."},
             {"name": "d_valid",   "width": "1",   "type": "V", "direction": "Slave"},
             {"name": "d_ready",   "width": "1",   "type": "R", "direction": "Master"},
         ]},
        {"name": "E",
         "full_name": "Channel E — Master-to-Slave Final Handshake (TL-C only)",
         "direction": "Master to Slave",
         "tl_level": "TL-C only",
         "purpose": "Carries acknowledgements of channel-D Grant/GrantData (GrantAck), used for operation serialization.",
         "signals": [
             {"name": "e_sink",  "width": "i", "type": "C", "direction": "Master",
              "semantics": "Echoes d_sink of the Grant being acknowledged."},
             {"name": "e_valid", "width": "1", "type": "V", "direction": "Master"},
             {"name": "e_ready", "width": "1", "type": "R", "direction": "Slave"},
         ]},
    ])
    f.setdefault("signal_naming_convention",
        "Other than clock and reset, TileLink signal names consist of the "
        "channel identifier (a-e) followed by an underscore, followed by "
        "the name of the signal. For devices with multiple TileLink "
        "interfaces, signal names should be prefixed with a descriptive "
        "token plus underscore (e.g. gpio_a_opcode).")
    f.setdefault("signal_type_summary", [
        {"type": "X", "description": "Clock or reset",                       "direction": "Input"},
        {"type": "C", "description": "Control signal, constant within burst","direction": "Channel direction"},
        {"type": "D", "description": "Data signal, changes each beat",       "direction": "Channel direction"},
        {"type": "F", "description": "Final signal, changes once per burst", "direction": "Channel direction"},
        {"type": "V", "description": "Valid",                                "direction": "Channel direction"},
        {"type": "R", "description": "Ready",                                "direction": "Reverse direction"},
    ])
    f.setdefault("per_link_parameter_summary", [
        {"parameter": "w", "description": "Width of data bus in bytes (power of two)"},
        {"parameter": "a", "description": "Width of address field in bits"},
        {"parameter": "z", "description": "Width of size field in bits"},
        {"parameter": "o", "description": "Width of master source identifier in bits"},
        {"parameter": "i", "description": "Width of slave sink identifier in bits"},
    ])
    d["fields"] = f
    _write(p, d)


# ============================================================
# L18 INTERCONNECT_TOPOLOGY
# ============================================================
def _l18(gd: Path) -> None:
    p = gd / "L18_INTERCONNECT_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f.setdefault("typical_topologies", [
        "Point-to-point link: one master + one slave (Figure 2.1).",
        "Hierarchical: master → crossbar → cache → memory controller (Figure 2.2).",
        "Crossbar module containing multiple agents — routing + config-access (Figure 2.3).",
        "AXI bridge → crossbar → clock-crossing → crossbar → SPI slave + SRAM + PCIe bridge (Figure 4.2).",
    ])
    _ir_l18 = _ensure_dict(f, "interconnect_role")
    _ir_l18.setdefault("crossbar_routing",
        "A TileLink crossbar is one TileLink agent with multiple master-side and multiple slave-side links. Messages received on a master interface are routed to one of the slave interfaces based on the per-region address-map.")
    _ir_l18.setdefault("adapter_bridge",
        "A TileLink-to-TileLink adapter (slave on one side, master on the other) is two independent agents inside one RTL module. Messages do not directly cross — they pass through an internal queue. Used for clock / power crossings.")
    _ir_l18.setdefault("legacy_bus_bridge",
        "A TileLink-to-{AXI,AHB,APB,PCIe} bridge is also two independent agents. The legacy-bus side must include timeouts to fit within the TileLink forward-progress rule, and any uncompleted legacy access must be reported as an error response on the TileLink side.")
    _ir_l18.setdefault("address_decode",
        "Per-link parameters and per-region address-map determine which slave receives a message. From any node in the DAG, every legal address must decode to exactly one downstream slave, otherwise the interconnect responds with an error.")
    _ir_l18.setdefault("configuration_agent",
        "Crossbars or other interconnect modules may contain a second agent with a single slave interface providing access to configuration state (region tables, status registers).")
    _ensure_full(f, "interconnect_rules", [
        "Pairs of agents are connected by links. One end of each link connects to a master interface on one agent; the other connects to a slave interface on another agent.",
        "Any topology that can be described as a Directed Acyclic Graph (DAG) is a legal topology. Agents are graph vertices; links are graph edges directed from master interface to slave interface.",
        "A single hardware module may contain multiple independent TileLink agents.",
        "If two links connect to the same module but messages from one cannot result in recursive messages on the other without first passing through a third link, the module contains two distinct agents.",
        "Both ends of a TileLink link must share the same clock, reset, and power domain.",
        "It is forbidden for one side of a TileLink link to power down while its opposite is powered on; clock-domain or power-domain crossings require a dedicated TileLink-to-TileLink adapter that acts as two distinct agents.",
        "Crossbars must combine source identifiers from their input links into a unique source-ID space on every output link, and reverse-translate on returning responses.",
    ])
    f.setdefault("deadlock_freedom_proof_sketch", [
        "1. Agent graph is a DAG by construction.",
        "2. Strict channel priority A < B < C < D < E enforced on every receiver.",
        "3. Higher-priority messages may bypass lower-priority ones.",
        "4. Each receiver only lowers ready according to the 4 legitimate exceptions.",
        "5. Combined, the message flow remains acyclic, so no hold-and-wait loop is possible.",
        "6. Therefore correct TileLink implementations are provably deadlock-free.",
    ])
    _ccpls = _ensure_dict(f, "channel_count_per_link_summary")
    _ccpls_ul = _ensure_dict(_ccpls, "TL_UL")
    _ccpls_ul.setdefault("channels", ["A", "D"])
    _ccpls_ul.setdefault("signal_count_min", 12)
    _ccpls_ul.setdefault("note",
        "12 signals = clock + reset + 7 channel-A control/data + 7 channel-D control/data (some shared widths).")
    _ccpls_uh = _ensure_dict(_ccpls, "TL_UH")
    _ccpls_uh.setdefault("channels", ["A", "D"])
    _ccpls_uh.setdefault("signal_count_min", 12)
    _ccpls_uh.setdefault("note",
        "Same as TL-UL but with bursts (size > log2(w)) and atomic param encodings used.")
    _ccpls_c = _ensure_dict(_ccpls, "TL_C")
    _ccpls_c.setdefault("channels", ["A", "B", "C", "D", "E"])
    _ccpls_c.setdefault("signal_count_min", 32)
    _ccpls_c.setdefault("note",
        "Adds B + C + E channels.")
    f.setdefault("interfacing_with_legacy_buses", [
        "Bridges to legacy buses must include a timeout to fit within the first forward-progress rule.",
        "If legacy bus does not accept a request within timeout, bridge discards request and injects TileLink error response.",
        "If legacy bus exceeds response timeout, bridge cancels outstanding request and injects TileLink error response.",
        "TileLink agents waiting on other TileLink agents must be infinitely patient.",
    ])
    f.setdefault("address_space_recommendation", [
        "Address map need not be a single global map.",
        "Recommend regions with side effects be aligned to 4kB multiples for TLB management.",
        "Optional FIFO domain identifier annotates regions that respond in FIFO order.",
        "Slaves must declare maximum burst support (recommended >= 4kB).",
    ])
    d["fields"] = f
    _write(p, d)


# ============================================================
# L19 CONSTRAINTS_PDK — N/A
# ============================================================
def _l19(gd: Path) -> None:
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("applicability", "NOT_APPLICABLE")
    d.setdefault("ic_class", "bus_interconnect_protocol")
    f = _ensure_dict(d, "fields")
    f.setdefault("constraints_present", False)
    # v0.1.86 — TileLink synth is authoritative for this protocol spec;
    # overwrite any earlier generic "block guide" / "peripheral spec"
    # notes with TileLink-specific text.
    f["notes"] = (
        "The TileLink Specification 1.7.1 is a wire-level / cycle-level "
        "interconnect protocol spec. It defines logical signal semantics "
        "and timing rules relative to the shared 'clock' signal only — no "
        "PDK-specific SDC, no floorplan / placement constraints, no "
        "clock-tree budget. Per-implementation timing closure is the "
        "responsibility of the SoC integrator.")
    d["fields"] = f
    _write(p, d)


# ============================================================
# L20 DFT_SCAN_TOPOLOGY — N/A
# ============================================================
def _l20(gd: Path) -> None:
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("applicability", "NOT_APPLICABLE")
    d.setdefault("ic_class", "bus_interconnect_protocol")
    f = _ensure_dict(d, "fields")
    f.setdefault("dft_present", False)
    # v0.1.86 — TileLink synth is authoritative.
    f["notes"] = (
        "The TileLink Specification 1.7.1 does not specify DFT / scan / "
        "BIST / MBIST / boundary scan. The protocol only specifies "
        "functional signaling. Concrete TileLink master / slave / "
        "crossbar / cache IPs add scan insertion + DFT compression + "
        "boundary-scan during SoC integration; debug visibility is "
        "typically provided via the RISC-V Debug Module, JTAG, and "
        "trace components — all outside the scope of this protocol spec.")
    f.setdefault("protocol_defined_fault_observation", [
        "c_error on channel C (master-side): single-bit signal that the master agent was unable to service a request.",
        "d_error on channel D (slave-side): single-bit signal that the slave was unable to service a request.",
    ])
    d["fields"] = f
    _write(p, d)


# ============================================================
# L21 POWER_INTENT — N/A
# ============================================================
def _l21(gd: Path) -> None:
    p = gd / "L21_POWER_INTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("applicability", "NOT_APPLICABLE")
    d.setdefault("ic_class", "bus_interconnect_protocol")
    f = _ensure_dict(d, "fields")
    f.setdefault("power_intent_present", False)
    f.setdefault("low_power_modes_summary", {
        "idle_channel": "When no messages are sent on a channel, *_valid stays LOW and the channel is quiescent. Power-aware signal encoding minimizes toggling on inactive channels.",
        "cross_domain_adapter": "Power-domain crossings require a TileLink-to-TileLink adapter; both interfaces can be safely powered, clocked, and reset separately.",
        "spec_invariant": "It is forbidden for one side of a TileLink link to power down while its opposite is powered on.",
    })
    f.setdefault("notes",
        "Power-domain partitioning, voltage-domain crossings, power-gate "
        "sequencing, isolation cells, retention registers are deferred to "
        "the SoC integration spec (UPF / CPF).")
    d["fields"] = f
    _write(p, d)


# ============================================================
# L22 VERIFICATION_PLAN
# ============================================================
def _l22(gd: Path) -> None:
    p = gd / "L22_VERIFICATION_PLAN.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f.setdefault("verification_plan_present", "implicit")
    f.setdefault("verification_categories_derived_from_spec", [
        "Reset behavior: reset active HIGH, deasserted synchronous with rising clock, valid signals LOW for at least 100 cycles.",
        "Ready/Valid handshake correctness: valid must not depend on ready; no combinational paths.",
        "TL-UL Get / PutFullData / PutPartialData single-beat coverage on channel A → D.",
        "TL-UH ArithmeticData {MIN, MAX, MINU, MAXU, ADD} param coverage.",
        "TL-UH LogicalData {XOR, OR, AND, SWAP} param coverage.",
        "TL-UH Intent {PrefetchRead, PrefetchWrite} param coverage.",
        "TL-UH burst Get (multi-beat AccessAckData) coverage.",
        "TL-UH burst PutFullData / PutPartialData (multi-beat request) coverage.",
        "TL-C Acquire {NtoB, NtoT, BtoT} a_param coverage and Grant/GrantData responses.",
        "TL-C Probe {toN, toB, toT} b_param coverage and ProbeAck/ProbeAckData responses.",
        "TL-C Release / ReleaseData {TtoB, TtoN, BtoN} c_param coverage and ReleaseAck.",
        "TL-C ProbeAck Shrink {TtoB, TtoN, BtoN} + Report {TtoT, BtoB, NtoN} c_param coverage.",
        "Burst beats may not be interleaved on a channel.",
        "Control signal constancy across a burst.",
        "Address alignment: (address & ((1<<size)-1)) == 0 enforcement.",
        "Byte-lane mask correctness.",
        "PutFullData mask all-HIGH enforcement.",
        "Error bit sticky-after-rise within a burst on channels C and D.",
        "Channel priority A < B < C < D < E strict enforcement.",
        "Forward progress 4-rule legitimate-low-ready exceptions.",
        "DAG topology invariant (architecture-level review).",
        "Out-of-order completion: multiple inflight requests with non-unique d_source must be supported.",
        "Source identifier uniqueness within a channel.",
        "TL-C GrantAck e_sink ↔ d_sink pairing.",
        "TL-C concurrency constraints.",
        "Hierarchical agent flow correctness.",
        "Legacy-bus bridge timeout behavior.",
        "Clock / power crossing adapter behavior.",
        "Coherence policy verification.",
    ])
    f.setdefault("reference_test_environments", [
        "SiFive Rocket Chip TLMonitor — SystemVerilog protocol-checker bound to each TileLink link.",
        "Chipyard test harness — chained TileLink-to-AXI bridge testing.",
        "BOOM core integration tests — multi-master TL-C coherence stress.",
        "Open-source diplomatic-monitor blocks emit SystemVerilog assertions.",
    ])
    f.setdefault("coverage_metrics_recommended", [
        "Cross-coverage: (channel × opcode × param × size × source) per channel.",
        "Cross-coverage: TL-C permissions transition matrix.",
        "Functional coverage: each of the 4 forward-progress legitimate-low-ready exceptions.",
        "Bursts of every length from 1 beat up to maximum allowed by z and w.",
        "Multiple inflight requests up to 2^o on each link.",
    ])
    d["fields"] = f
    _write(p, d)


# ============================================================
# L23 SECURITY_REQUIREMENTS
# ============================================================
def _l23(gd: Path) -> None:
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    # v0.1.86 — TileLink synth is authoritative; overwrite any earlier
    # generic `False` with the actual "minimal" classification (TileLink
    # provides address-space privilege + c_error/d_error bits, so it has
    # 'minimal' security features rather than none).
    f["security_requirements_present"] = "minimal"
    f.setdefault("spec_provided_security_features", [
        {"name": "Address-space privilege property",
         "purpose": "TileLink address-space properties include 'privilege level' as a per-region property, allowing slave-side privilege checks at the bus layer."},
        {"name": "c_error / d_error bits",
         "purpose": "Single-bit error fields allow compliant response generation even when data corruption is detected."},
    ])
    f.setdefault("what_is_NOT_in_the_spec", [
        "No confidentiality / encryption at the protocol layer.",
        "No data-integrity / authentication.",
        "No replay protection.",
        "No anti-rollback mechanism.",
        "No attestation features.",
        "No secure-vs-nonsecure transaction marker (unlike AXI's AxPROT[1]).",
        "No interface parity / fault-detection bits (unlike AHB5's optional parity).",
        "No source-identity authentication; a_source identifiers are not cryptographically bound to issuing master.",
        "No hardware-enforced access-control or sandbox (deferred to PMP / IOPMP / firewall at SoC level).",
    ])
    f.setdefault("integrator_responsibility_summary", [
        "Privilege / secure-vs-nonsecure / cacheability / FIFO ordering are per-region properties declared at SoC integration time.",
        "Combine TileLink with external firewalls (e.g. RISC-V IOPMP, ARM TZASC) to enforce confidentiality and integrity per address range.",
        "Cryptographic guarantees must be added at the master agent or at a memory-protection-unit slave — not inside the TileLink network.",
    ])
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
def is_tilelink(blob: str) -> bool:
    """Content-only `tilelink` detector (importable, lifted from the runner).

    Empty-safe. Reads ONLY ``blob`` (spec text).

    FOREIGN-PRIMARY DEFER (mirrors the `is_mipi` / OCP-`_axi_primary`
    doctrine — general, content-only, no chip/SKU/benchmark-name literal as
    detection logic): the original structural signature below is loose enough
    that an OCP spec which cites TileLink as a comparison sibling (and uses
    the generic English words "Get"/"Put", or "Acquire"/"Release"/"Grant")
    would trip the first/third branches and have the generic TileLink synth
    fire on it. So if the blob's DOMINANT subject is OCP, defer (False).

    OCP-primary signature: the Open Core Protocol M/S-prefixed handshake
    model — MCmd (master command) + SCmdAccept (slave request accept) +
    SResp (slave response). This mixed-case M/S-prefixed signal trio is
    unique to OCP among the SoC buses (AXI/AHB/Wishbone/Avalon/TileLink use
    entirely different signal names) and is ABSENT from every real TileLink
    benchmark (which uses Channels A-E / Acquire / Grant / Probe naming).
    Corroborate with MData/SData/MAddr or MRespAccept so a stray single token
    cannot defer. Mirrors `ocp_protocol_synth.is_ocp`'s own hard structural
    gate, so the two detectors are mutually exclusive by construction.
    """
    if not blob:
        return False

    # --- FOREIGN-PRIMARY DEFER (the blob's true subject is OCP, not TileLink).
    def _has(tok: str) -> bool:
        return re.search(r"\b" + re.escape(tok) + r"\b", blob) is not None

    _ocp_command_core = _has("MCmd") and _has("SCmdAccept") and _has("SResp")
    _ocp_data_signals = _has("MData") and _has("SData") and _has("MAddr")
    ocp_primary = _ocp_command_core and (
        _has("MRespAccept") or _ocp_data_signals)
    if ocp_primary:
        return False

    return bool(
        ("TileLink" in blob and "Get" in blob
            and "Put" in blob)
        or ("TL-UL" in blob and "TL-UH" in blob
            and "TL-C" in blob)
        or ("Acquire" in blob and "Release" in blob
            and "Grant" in blob and "Probe" in blob)
        or ("TileLink" in blob and "SiFive" in blob))
