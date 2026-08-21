"""ARM AMBA AXI4-Stream Protocol synth helper (protocol #70).

ic_class-gated overlay for the AXI4-Stream structural signature: the AMBA
AXI4-Stream Protocol (ARM IHI 0051) is a single-channel, point-to-point,
UNIDIRECTIONAL stream protocol that moves a sequence of data transfers from a
master/source (transmitter, TX) to a slave/sink (receiver, RX). Unlike the
memory-mapped AMBA AXI protocol it has NO address phase and NO read/write
transaction model: there is exactly one stream channel, with the TVALID/TREADY
handshake and the T-prefixed payload signals.

  - Handshake: TVALID (master->slave) + TREADY (slave->master); a transfer
    completes on the rising ACLK edge at which both are HIGH.
  - Payload / qualifiers: TDATA (payload), TSTRB (data-byte vs position-byte
    qualifier), TKEEP (null-byte qualifier), TLAST (packet boundary), TID
    (stream identifier), TDEST (routing destination), TUSER (user sideband),
    TWAKEUP (AXI4-Stream v2 / AMBA 5 wake).
  - Concepts: transfer (one TVALID&TREADY cycle), packet (TLAST-delimited),
    frame, stream; byte types data / position / null (TKEEP/TSTRB encoding).
  - Routing: interconnect uses TID/TDEST to route and order multiple streams
    sharing one physical channel.

Doctrine — GENERAL not keyword: detection uses the canonical STRUCTURAL
signature (the AXI4-Stream T-prefixed signal set TVALID/TREADY + TDATA/TLAST
plus at least one of TKEEP/TSTRB/TID/TDEST + the no-address streaming
source/sink model) read from the L-doc / input_doc CONTENT blob only. It NEVER
reads the input-document filename or the benchmark folder name, and it NEVER
fires on the bare word "AXI" alone (the memory-mapped AXI spec contains "AXI"
too).

CRITICAL MUTEX vs memory-mapped AMBA AXI. The existing arm_aix benchmark is
memory-mapped AXI4 + ACE/CHI: five address/data channels (AW/W/B/AR/R) with
ARVALID/AWVALID/RVALID/BVALID/WVALID handshakes, ARADDR/AWADDR address buses,
AWLEN/ARLEN burst lengths, and INCR/WRAP/FIXED burst types — a read/write
transaction protocol to a memory address space. AXI4-Stream is a DIFFERENT
protocol: one unidirectional stream channel, no address. The detector therefore
REQUIRES the AXI4-Stream T-signal structural set AND DEFERS when the doc is
AXI-memory-mapped-primary (address channels / ARADDR/AWADDR / read-write
transactions / INCR-WRAP bursts dominate with no T-stream signature) or
Avalon-ST-primary (startofpacket/endofpacket + Avalon vocabulary). Because the
arm_aix doc also mentions write/read "data channels", the gate keys on the
T-prefixed AXI4-Stream signal NAMES (TVALID/TREADY/TLAST/TKEEP/TSTRB/TID/TDEST)
plus the no-address stream model, NOT on the word "AXI".

Public entry: ``apply_axi_stream_synth(generated_docs_dir, is_axi_stream,
axi_stream_ic_name)``. Module-level ``is_axi_stream(blob)`` is the content-only
detector. The synth FORCE-OVERWRITES (direct-assign, not setdefault) every key
it owns so it wins regardless of any sibling bus synth that ran before it; the
parent wires it to run LAST in the bus-interconnect synth block.
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

# Canonical AXI4-Stream facts (ARM IHI 0051).
_T_SIGNALS = [
    "ACLK", "ARESETn", "TVALID", "TREADY", "TDATA", "TSTRB", "TKEEP",
    "TLAST", "TID", "TDEST", "TUSER", "TWAKEUP",
]
_BYTE_TYPES = [
    "data byte (TKEEP=1, TSTRB=1): a content byte carrying data that must be "
    "transmitted to the destination",
    "position byte (TKEEP=1, TSTRB=0): a byte that holds a position in the "
    "stream to preserve data layout but whose TDATA value carries no data",
    "null byte (TKEEP=0, TSTRB=0): a byte with no meaning that interconnect "
    "may remove from the stream; TKEEP=0,TSTRB=1 is not permitted",
]


def _wb(token: str, low: str) -> bool:
    """Word-boundary token match in lower-cased blob."""
    return re.search(r'\b' + re.escape(token) + r'\b', low) is not None


def is_axi_stream(blob: str) -> bool:
    """Content-only AXI4-Stream detector with a memory-mapped-AXI MUTEX.

    Fire on the AXI4-Stream structural signature: the T-prefixed handshake
    TVALID + TREADY together with the streaming payload TDATA + TLAST and at
    least one of the AXI4-Stream-unique qualifiers TKEEP / TSTRB / TID / TDEST,
    plus the no-address unidirectional source/sink stream model. DEFER if the
    doc is memory-mapped-AXI-primary (the AW/W/B/AR/R address-channel
    xVALID/xREADY set + ARADDR/AWADDR address buses + read/write transactions /
    INCR-WRAP bursts dominate and NO T-stream signature is present) or
    Avalon-ST-primary (startofpacket/endofpacket + Avalon vocabulary). Reads
    ONLY the spec text `blob` — never a filename or benchmark name.
    """
    if not blob:
        return False
    low = blob.lower()

    # --- AXI4-Stream T-prefixed structural signals (word-boundary). ---
    tvalid = _wb("tvalid", low)
    tready = _wb("tready", low)
    tdata = _wb("tdata", low)
    tlast = _wb("tlast", low)
    tkeep = _wb("tkeep", low)
    tstrb = _wb("tstrb", low)
    tid = _wb("tid", low)
    tdest = _wb("tdest", low)
    tuser = _wb("tuser", low)

    # The AXI4-Stream handshake is TVALID + TREADY (both required — this is the
    # stream channel handshake, present in NO other protocol with this exact
    # T-prefix naming).
    t_handshake = tvalid and tready
    # Streaming payload: TDATA carried with a TLAST packet boundary.
    t_payload = tdata and tlast
    # At least one AXI4-Stream-unique qualifier/routing signal. These names are
    # specific to AXI4-Stream (memory-mapped AXI has no TKEEP/TSTRB/TID/TDEST).
    t_qualifier = tkeep or tstrb or tid or tdest or tuser

    # HARD STRUCTURAL GATE. Every path that returns True REQUIRES the
    # AXI4-Stream T-signal handshake + payload + at least one unique qualifier.
    # A name-token-only branch (e.g. the word "stream" or "AXI") would MIS-FIRE
    # on the memory-mapped arm_aix doc and on generic streaming specs, so there
    # is no name-only path.
    has_hard_structure = t_handshake and t_payload and t_qualifier
    if not has_hard_structure:
        return False

    # No-address streaming model corroboration: AXI4-Stream has NO address
    # phase. The memory-mapped AXI address-channel signals are the strongest
    # negative signal.
    araddr = _wb("araddr", low)
    awaddr = _wb("awaddr", low)
    arvalid = _wb("arvalid", low)
    awvalid = _wb("awvalid", low)
    rvalid = _wb("rvalid", low)
    bvalid = _wb("bvalid", low)
    wvalid = _wb("wvalid", low)

    # Sibling MUTEX vs memory-mapped AMBA AXI. The defining structural
    # difference is the NO-address streaming model: a genuine AXI4-Stream
    # interface has no address-channel handshake. A memory-mapped-AXI-PRIMARY
    # doc presents the AW/W/B/AR/R address-channel VALID handshakes
    # (ARVALID / AWVALID / RVALID / BVALID / WVALID) and/or the ARADDR/AWADDR
    # address bus AS the protocol, WITHOUT the AXI4-Stream T-handshake. When
    # the memory-mapped address-channel signature is present AND the
    # AXI4-Stream T-handshake (TVALID + TREADY) is NOT — i.e. the doc is purely
    # memory-mapped — we DEFER to the memory-mapped AXI synth. The real
    # arm_aix memory-mapped AXI/ACE/CHI doc has no T-handshake at all and is
    # already excluded by the hard structural gate above; this guard is
    # belt-and-braces for a doc whose dominant signal set is the memory-mapped
    # address channels. A spec-honest AXI4-Stream doc that merely MENTIONS the
    # memory-mapped valids/addresses in prose to contrast itself (the
    # no-address model is the AXI4-Stream invariant) still presents the
    # T-handshake as its actual protocol, so the `not t_handshake` clause keeps
    # it correctly classified as AXI4-Stream.
    mm_address_signature = (
        arvalid or awvalid or rvalid or bvalid or wvalid or araddr or awaddr)
    axi_mm_primary = mm_address_signature and not t_handshake
    if axi_mm_primary:
        return False

    # Sibling MUTEX vs Avalon Streaming. Avalon-ST keys on
    # startofpacket/endofpacket + the Avalon vocabulary. Defer if the doc is
    # Avalon-ST-primary and the only "T-structure" is an incidental collision.
    avalon_st_primary = (
        "startofpacket" in low and "endofpacket" in low
        and "avalon" in low and not t_handshake)
    if avalon_st_primary:
        return False

    return True


def apply_axi_stream_synth(generated_docs_dir: Path, is_axi_stream_flag: bool,
                           axi_stream_ic_name: Optional[str]) -> None:
    """Apply AXI4-Stream synth when the AXI4-Stream signature matched.

    Because AXI4-Stream classifies as a bus/interconnect-family protocol, a
    sibling synth may have populated L1/L2/... first. This routine
    FORCE-OVERWRITES (direct assignment) every key it owns with the
    AXI4-Stream-canonical value; the parent wires it to run LAST so it wins.
    """
    if not is_axi_stream_flag:
        return
    gd = Path(generated_docs_dir)

    # --- Force ic_name across ALL 24 docs FIRST (main + fields docs). ---
    if axi_stream_ic_name is not None:
        for n in _MAIN_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                d["ic_name"] = axi_stream_ic_name
                _write(q, d)
        for n in _FIELDS_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                f = _ensure_dict(d, "fields")
                f["ic_name"] = axi_stream_ic_name
                d["ic_name"] = axi_stream_ic_name
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
# L1 — AXI4-Stream datasheet header + headline facts.
# ----------------------------------------------------------------------
def _l1(gd: Path) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    d["document_title"] = "AMBA AXI4-Stream Protocol Specification"
    d["version"] = "AMBA AXI4-Stream Protocol Specification (ARM IHI 0051)"
    d["revised_date"] = "ARM AMBA AXI4-Stream Protocol Specification"
    d["manufacturer"] = "Arm Limited"
    d["copyright"] = "© Arm Limited"
    d["abstract"] = (
        "The AMBA AXI4-Stream protocol (ARM IHI 0051) defines a single-channel, "
        "point-to-point, UNIDIRECTIONAL interface that transports a stream of "
        "data from a master (source / transmitter) to a slave (sink / "
        "receiver). Unlike the memory-mapped AMBA AXI protocol, AXI4-Stream has "
        "NO address phase and NO read/write transaction model: there is exactly "
        "one stream channel. Data moves with the TVALID/TREADY handshake — a "
        "transfer completes on the rising ACLK edge at which both are HIGH. The "
        "payload is TDATA, qualified by TSTRB (data byte vs position byte), "
        "TKEEP (null byte), TLAST (packet boundary), TID (stream identifier), "
        "TDEST (routing destination), and TUSER (user sideband); TWAKEUP (v2) "
        "carries low-power wake activity. A sequence of transfers is a stream; "
        "TLAST delimits packets; interconnect routes and orders multiple "
        "streams using TID/TDEST. AXI4-Stream is the streaming companion to the "
        "memory-mapped AMBA AXI protocol and is widely used for video, packet, "
        "DMA, and DSP data paths.")
    d["keywords"] = [
        "AXI4-Stream", "AMBA", "stream", "master", "source", "transmitter",
        "slave", "sink", "receiver", "unidirectional", "no address",
        "TVALID", "TREADY", "TDATA", "TSTRB", "TKEEP", "TLAST", "TID",
        "TDEST", "TUSER", "TWAKEUP", "ACLK", "ARESETn", "transfer", "packet",
        "frame", "byte types", "data byte", "position byte", "null byte",
        "backpressure", "routing", "interconnect",
    ]
    d["external_pins"] = [
        "Global: ACLK (single clock; all signals sampled on its rising edge), "
        "ARESETn (active-LOW reset; TVALID driven LOW during reset)",
        "Handshake: TVALID (master->slave), TREADY (slave->master)",
        "Payload: TDATA (data bytes, TDATA_WIDTH a multiple of 8)",
        "Qualifiers: TSTRB (data vs position byte), TKEEP (null byte), TLAST "
        "(packet boundary)",
        "Routing/sideband: TID (stream identifier), TDEST (routing "
        "destination), TUSER (user sideband)",
        "AXI4-Stream v2 (AMBA 5): TWAKEUP (interface activity / wake)",
    ]
    d["interface_signals"] = list(_T_SIGNALS)
    d["roles"] = {
        "master": "source / transmitter (TX); drives TVALID + payload",
        "slave": "sink / receiver (RX); drives TREADY",
    }
    d["byte_types"] = list(_BYTE_TYPES)
    d["modes_of_operation"] = [
        {"name": "Continuous (fully-packed) stream",
         "roles": "master (source) / slave (sink)",
         "note": "Every byte is a data byte (TKEEP and TSTRB all HIGH); "
                 "back-to-back transfers."},
        {"name": "Sparse / partially-packed stream",
         "roles": "master (source) / slave (sink)",
         "note": "Position bytes (TKEEP=1,TSTRB=0) preserve layout and null "
                 "bytes (TKEEP=0,TSTRB=0) pad partial beats."},
        {"name": "Packetized stream",
         "roles": "master (source) / slave (sink)",
         "note": "TLAST marks the last transfer of each packet; an unframed "
                 "stream is one indefinitely long packet."},
        {"name": "Routed / multiplexed streams",
         "roles": "master / slave through interconnect",
         "note": "TID identifies a stream and TDEST selects the destination; "
                 "interconnect routes/orders multiple streams on one channel."},
    ]
    d["key_features"] = [
        "Single-channel, point-to-point, UNIDIRECTIONAL stream from a master "
        "(source/transmitter) to a slave (sink/receiver); no address phase.",
        "TVALID/TREADY handshake: a transfer completes on a rising ACLK edge "
        "where both are HIGH; master must not wait for TREADY before TVALID.",
        "TDATA is the payload (TDATA_WIDTH a multiple of 8); only TVALID and "
        "TREADY are mandatory, all other signals are optional.",
        "TSTRB qualifies each byte as a data byte vs a position byte; TKEEP "
        "marks null bytes; the three byte types are data / position / null.",
        "TLAST marks the last transfer of a packet; a stream is a sequence of "
        "transfers, optionally framed into packets and frames.",
        "TID identifies a data stream and TDEST provides routing destination; "
        "interconnect uses them to route and order streams sharing a channel.",
        "TUSER carries a user-defined sideband; TWAKEUP (AXI4-Stream v2 / AMBA "
        "5) conveys interface activity for low-power wake handshaking.",
        "TSTRB/TKEEP are one bit per byte lane (TDATA_WIDTH/8); recommended "
        "max TID width is 8 bits and TDEST width is 4 bits.",
        "Strictly distinct from memory-mapped AMBA AXI: no AW/W/B/AR/R "
        "channels, no ARADDR/AWADDR, no read/write transactions, no "
        "INCR/WRAP/FIXED bursts.",
        "The streaming companion to memory-mapped AMBA AXI; commonly paired "
        "(memory-mapped AXI for control, AXI4-Stream for the data pipeline).",
    ]
    d["topology_summary"] = (
        "AXI4-Stream is a direct point-to-point connection from a single master "
        "(source) to a single slave (sink); data and qualifiers flow one way "
        "(master->slave) and only TREADY backpressure flows back. An "
        "AXI4-Stream interconnect (switch / multiplexer) can route and order "
        "multiple streams on shared channels using TID/TDEST.")
    d["use_cases"] = [
        "Video and image pipelines (pixels streamed; TLAST = end-of-line, "
        "TUSER = start-of-frame)",
        "Packet processing (TLAST = end-of-packet, TDEST = egress port)",
        "DMA / accelerator data paths (AXI4-Stream data + memory-mapped AXI "
        "control)",
        "Digital signal processing chains (filters, FFTs streamed block to "
        "block)",
        "Any continuous or bursty producer-to-consumer data path needing "
        "backpressure",
    ]
    d["revision_history"] = [
        {"version": "AMBA AXI4-Stream Protocol Specification (IHI 0051)",
         "date": "Arm Limited",
         "description": "Single-channel unidirectional stream protocol: "
                        "TVALID/TREADY handshake; TDATA/TSTRB/TKEEP/TLAST/TID/"
                        "TDEST/TUSER payload; transfer/packet/frame/stream and "
                        "data/position/null byte types; TID/TDEST routing; "
                        "TWAKEUP added in AXI4-Stream v2 (AMBA 5)."},
    ]
    d["overview"] = (
        "The AMBA AXI4-Stream protocol (ARM IHI 0051) is a single-channel, "
        "point-to-point, unidirectional protocol for transporting a stream of "
        "data from a master (also called the source or transmitter) to a slave "
        "(also called the sink or receiver). It has NO address phase and NO "
        "read/write transaction model — this is the key difference from the "
        "memory-mapped AMBA AXI protocol, which uses five address/data channels "
        "(AW/W/B/AR/R) with ARVALID/AWVALID/RVALID/BVALID/WVALID handshakes and "
        "ARADDR/AWADDR address buses. In AXI4-Stream a transfer moves across the "
        "interface using the TVALID/TREADY handshake: the master asserts TVALID "
        "when it has valid payload, the slave asserts TREADY when it can "
        "accept, and the transfer occurs on the rising ACLK edge at which both "
        "are HIGH. Once asserted, TVALID must stay asserted until the transfer "
        "completes; a slave may wait for TVALID before asserting TREADY but a "
        "master may not wait for TREADY before asserting TVALID. The payload is "
        "TDATA, whose byte lanes are qualified by TSTRB (data byte vs position "
        "byte) and TKEEP (null byte), giving three byte types: data, position, "
        "and null. TLAST marks the last transfer of a packet; the whole "
        "sequence of transfers is a stream, optionally framed into packets and "
        "frames. TID identifies a stream and TDEST provides routing "
        "information, so an interconnect can route and order multiple streams "
        "sharing one physical channel; TUSER carries a user-defined sideband, "
        "and TWAKEUP (AXI4-Stream v2 / AMBA 5) signals interface activity for "
        "low-power wake handshaking. During reset (ARESETn LOW) the master "
        "drives TVALID LOW, and may first assert TVALID one ACLK edge after "
        "ARESETn is HIGH.")
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
        "Single-channel, point-to-point, unidirectional stream protocol "
        "(master/source -> slave/sink) with the TVALID/TREADY handshake and the "
        "T-prefixed payload TDATA/TSTRB/TKEEP/TLAST/TID/TDEST/TUSER. No address "
        "phase, no read/write transaction, no burst type — distinct from "
        "memory-mapped AMBA AXI.")
    po["duplex"] = (
        "Unidirectional: data and qualifiers flow master->slave; only the "
        "TREADY backpressure signal flows slave->master. There is no return "
        "data path and no response channel.")
    po["synchronous_serial"] = False
    po["source_synchronous"] = False
    po["embedded_clock"] = False
    po["forwarded_clock"] = False
    po["parallel_synchronous"] = True
    po["encoding"] = (
        "Parallel synchronous logic interface; no line code. Byte meaning is "
        "encoded by TKEEP/TSTRB (data / position / null bytes); packet framing "
        "by TLAST; routing by TID/TDEST.")
    po["roles"] = {
        "master": "source / transmitter (TX); drives TVALID + payload",
        "slave": "sink / receiver (RX); drives TREADY",
    }
    po["interface_signals"] = list(_T_SIGNALS)
    po["handshake"] = (
        "TVALID (master->slave) + TREADY (slave->master); a transfer completes "
        "on the rising ACLK edge at which both are HIGH. TVALID, once asserted, "
        "holds until the transfer completes; a master must not wait for TREADY "
        "before asserting TVALID; a slave may wait for TVALID before TREADY.")
    po["byte_types"] = list(_BYTE_TYPES)
    po["transfer_concepts"] = [
        "transfer: one TVALID&TREADY cycle moving one beat of TDATA + "
        "qualifiers",
        "packet: one or more transfers delimited by TLAST (last transfer has "
        "TLAST HIGH)",
        "frame: an application-defined grouping of packets (e.g. a video "
        "frame), conveyed via TUSER/TID/TDEST",
        "stream: the whole sequence of transfers from source to sink "
        "(continuous or sparse)",
    ]
    po["routing"] = (
        "TID identifies a data stream; TDEST identifies the routing "
        "destination. An interconnect uses TID to keep per-stream ordering and "
        "TDEST to select an output port. Recommended max TID width 8 bits, "
        "TDEST width 4 bits.")
    d["functional_requirements"] = [
        {"id": "FR-01", "text": "An AXI4-Stream interface connects a single "
         "master (source/transmitter) to a single slave (sink/receiver). Data "
         "and qualifiers flow only master->slave; only TREADY flows back. There "
         "is no address and no read/write transaction."},
        {"id": "FR-02", "text": "A transfer occurs on the rising edge of ACLK "
         "at which both TVALID and TREADY are HIGH. The master asserts TVALID "
         "when it drives valid payload; the slave asserts TREADY when it can "
         "accept a transfer."},
        {"id": "FR-03", "text": "Once TVALID is asserted it must remain "
         "asserted until the transfer completes; the master must hold the "
         "payload stable while TVALID is HIGH and TREADY is not yet HIGH. A "
         "master must NOT wait for TREADY before asserting TVALID."},
        {"id": "FR-04", "text": "A slave is permitted to wait for TVALID before "
         "asserting TREADY, and may assert TREADY before TVALID or deassert it "
         "if no transfer takes place. These rules prevent deadlock and lost "
         "transfers."},
        {"id": "FR-05", "text": "TDATA is the payload, an integer number of "
         "bytes wide (TDATA_WIDTH a multiple of 8). TSTRB marks each byte a "
         "data byte (TSTRB=1) or position byte (TSTRB=0); TKEEP marks each byte "
         "kept (TKEEP=1) or a null byte (TKEEP=0). TKEEP=0,TSTRB=1 is illegal."},
        {"id": "FR-06", "text": "The three byte types are data (TKEEP=1, "
         "TSTRB=1), position (TKEEP=1, TSTRB=0), and null (TKEEP=0, TSTRB=0). "
         "Null bytes may be removed by interconnect; position bytes preserve "
         "layout but carry no data."},
        {"id": "FR-07", "text": "TLAST HIGH marks the last transfer of a "
         "packet. A packet is one or more associated transfers. When TLAST is "
         "not used the stream is a single indefinitely long packet. A frame is "
         "an application-defined grouping of packets."},
        {"id": "FR-08", "text": "TID is the data stream identifier and TDEST is "
         "the routing destination. Interconnect uses TID/TDEST to route and to "
         "preserve per-stream ordering when multiple streams share one physical "
         "channel. Within one TID/TDEST, transfers are in order."},
        {"id": "FR-09", "text": "TUSER carries a user-defined sideband "
         "(per-transfer or per-byte-lane). TWAKEUP (AXI4-Stream v2 / AMBA 5) "
         "indicates interface activity for low-power wake handshaking. All "
         "signals except TVALID and TREADY are optional."},
        {"id": "FR-10", "text": "All signals are sampled on the rising edge of "
         "ACLK. During reset (ARESETn LOW) the master drives TVALID LOW; the "
         "earliest TVALID may be asserted is one ACLK rising edge after ARESETn "
         "is HIGH."},
    ]
    d["error_response_conditions"] = [
        "Illegal byte qualifier TKEEP=0,TSTRB=1 — not permitted (no valid byte "
        "type).",
        "TVALID deasserted before a transfer completes — violates the "
        "handshake (TVALID must hold until TREADY is HIGH).",
        "Payload changed while TVALID HIGH and TREADY not yet HIGH — violates "
        "payload-stability.",
        "Backpressure (TREADY deasserted) — the slave stalls the master; no "
        "data is transferred until TREADY is asserted (not an error, a stall).",
        "TVALID asserted during reset (ARESETn LOW) — illegal; master must "
        "drive TVALID LOW in reset.",
    ]
    d["compliance_requirements"] = [
        "Master/source and slave/sink roles with the TVALID/TREADY handshake "
        "and the declared subset of TDATA/TSTRB/TKEEP/TLAST/TID/TDEST/TUSER.",
        "Transfer completes only when both TVALID and TREADY are HIGH on a "
        "rising ACLK edge; TVALID holds until completion; payload held stable.",
        "Master must not wait for TREADY before asserting TVALID; slave may "
        "wait for TVALID before TREADY.",
        "Correct byte typing (data / position / null) via TKEEP/TSTRB; "
        "TKEEP=0,TSTRB=1 never driven.",
        "TLAST delimits packets; TID/TDEST used consistently for routing and "
        "per-stream ordering.",
        "TVALID LOW during reset; first TVALID only after ARESETn HIGH.",
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
        "Unidirectional single-channel stream transfer protocol. The master "
        "(source) drives TVALID + TDATA + qualifiers (TSTRB/TKEEP/TLAST/TID/"
        "TDEST/TUSER); the slave (sink) drives TREADY. A transfer moves one "
        "beat when both TVALID and TREADY are HIGH on a rising ACLK edge. There "
        "is no address, no read/write command, and no response channel.")
    d["channels"] = [
        {"name": "AXI4-Stream channel (the only channel)",
         "direction": "unidirectional master->slave",
         "description": "Master drives TVALID/TDATA/TSTRB/TKEEP/TLAST/TID/TDEST/"
         "TUSER; slave drives TREADY. One beat transfers when TVALID and TREADY "
         "are both HIGH on a rising ACLK edge."},
    ]
    d["interface_signals"] = {
        "ACLK": "global; single clock, all signals sampled on its rising edge",
        "ARESETn": "global; active-LOW reset; TVALID driven LOW during reset",
        "TVALID": "master->slave; master is driving a valid transfer",
        "TREADY": "slave->master; slave can accept a transfer this cycle",
        "TDATA": "master->slave; payload, TDATA_WIDTH a multiple of 8",
        "TSTRB": "master->slave; per-byte data-byte(1) vs position-byte(0)",
        "TKEEP": "master->slave; per-byte kept(1) vs null-byte(0)",
        "TLAST": "master->slave; last transfer of a packet",
        "TID": "master->slave; data stream identifier (max ~8 bits)",
        "TDEST": "master->slave; routing destination (max ~4 bits)",
        "TUSER": "master->slave; user-defined sideband",
        "TWAKEUP": "master->slave; AXI4-Stream v2 interface-activity / wake",
    }
    d["transfer_types"] = [
        {"name": "Single transfer",
         "description": "One beat of TDATA + qualifiers moves when TVALID and "
         "TREADY are both HIGH on a rising ACLK edge."},
        {"name": "Continuous (fully-packed) stream",
         "description": "Back-to-back transfers where every byte is a data byte "
         "(TKEEP=1, TSTRB=1)."},
        {"name": "Sparse / partially-packed stream",
         "description": "Stream using position bytes (TKEEP=1,TSTRB=0) and null "
         "bytes (TKEEP=0,TSTRB=0) to preserve layout and pad partial beats."},
        {"name": "Packet (TLAST-delimited)",
         "description": "One or more transfers ended by TLAST HIGH on the last "
         "beat; unframed streams are one indefinitely long packet."},
        {"name": "Routed / multiplexed stream",
         "description": "TID identifies the stream and TDEST selects the "
         "destination; interconnect routes and orders streams sharing a "
         "channel."},
    ]
    d["addressing"] = {
        "note": "AXI4-Stream is ADDRESSLESS — there is no address phase and no "
                "read/write transaction. This is the key structural difference "
                "from the memory-mapped AMBA AXI protocol. Routing (not "
                "addressing) is provided by TID (stream id) and TDEST "
                "(destination).",
        "routing": "TID identifies a stream; TDEST selects a destination port.",
    }
    d["byte_oriented"] = True
    d["frame_oriented"] = True
    d["packet_oriented"] = True
    d["bit_stuffing"] = False
    d["arbitration_based"] = True
    d["arbitration_note"] = (
        "An AXI4-Stream interconnect (switch/multiplexer) arbitrates between "
        "multiple input streams contending for a shared output, routing by "
        "TDEST and preserving per-TID ordering; the base point-to-point "
        "interface itself has no arbitration.")
    _write(p, d)


# ----------------------------------------------------------------------
# L4 — register / configuration parameter model.
# ----------------------------------------------------------------------
def _l4(gd: Path) -> None:
    p = gd / "L4_REGMAP.json"
    if not p.is_file():
        return
    d = _read(p)
    d["register_map_present"] = False
    d["notes"] = (
        "AXI4-Stream is an ADDRESSLESS streaming interface — it defines no "
        "register map and no addressable locations (that is the role of the "
        "separate memory-mapped AMBA AXI interface a component may also "
        "expose). The AXI4-Stream specification defines the interface (signal "
        "roles, handshake, byte types, packet framing, routing), not registers. "
        "The configuration below is the set of AXI4-Stream interface "
        "parameters / signal widths an interface declares.")
    d["interface_parameter_groups"] = [
        {"group": "Signal widths", "fields": [
            "TDATA_WIDTH (bits; an integer number of bytes, a multiple of 8)",
            "TSTRB width = TDATA_WIDTH/8 (one bit per byte lane)",
            "TKEEP width = TDATA_WIDTH/8 (one bit per byte lane)",
            "TID_WIDTH (recommended max 8 bits)",
            "TDEST_WIDTH (recommended max 4 bits)",
            "TUSER_WIDTH (application-defined; often per byte lane)"]},
        {"group": "Optional-signal presence", "fields": [
            "TDATA present (a TVALID/TREADY-only interface omits TDATA)",
            "TSTRB present", "TKEEP present", "TLAST present",
            "TID present", "TDEST present", "TUSER present",
            "TWAKEUP present (AXI4-Stream v2)"]},
        {"group": "Stream properties", "fields": [
            "packetized (TLAST used) vs unframed",
            "continuous (fully-packed) vs sparse (position/null bytes)",
            "single-stream vs multiplexed (TID/TDEST routing)"]},
    ]
    d["interface_signal_roles"] = list(_T_SIGNALS)
    _write(p, d)


# ----------------------------------------------------------------------
# L5 — analog / physical signaling spec.
# ----------------------------------------------------------------------
def _l5(gd: Path) -> None:
    p = gd / "L5_ADI_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["analog_digital_interface_present"] = False
    d["signaling_summary"] = (
        "AXI4-Stream is a synchronous-logic on-chip interface, not an "
        "electrical/analog interface. All signals (TVALID, TREADY, TDATA, "
        "TSTRB, TKEEP, TLAST, TID, TDEST, TUSER, TWAKEUP) are single-ended "
        "synchronous-logic signals sampled on the rising edge of the common "
        "ACLK; there is no line code, no differential signaling, and no "
        "physical-layer electrical specification in the AXI4-Stream protocol.")
    d["modulation"] = "n/a (synchronous-logic interface; no modulation)"
    d["clocking"] = (
        "A single shared clock ACLK times the whole interface; both master and "
        "slave use the same ACLK and all signals are sampled on its rising "
        "edge. There is no forwarded or embedded clock.")
    d["signal_levels"] = (
        "Single-ended synchronous-logic levels (on-chip core logic). No "
        "off-chip electrical specification is defined by the protocol.")
    d["encoding_role_in_analog"] = (
        "AXI4-Stream defines no line code. Byte meaning is encoded by "
        "TKEEP/TSTRB (data / position / null bytes); framing by TLAST; routing "
        "by TID/TDEST. Data integrity beyond byte typing is the responsibility "
        "of the connected IP, not of an AXI4-Stream physical layer.")
    _write(p, d)


# ----------------------------------------------------------------------
# L6 — control logic / transfer FSMs.
# ----------------------------------------------------------------------
def _l6(gd: Path) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["fsm_states_master"] = [
        {"name": "M_RESET", "description": "ARESETn LOW: master drives TVALID "
         "LOW; no transfer may be interpreted as valid."},
        {"name": "M_IDLE", "description": "ARESETn HIGH, no payload to send: "
         "TVALID LOW."},
        {"name": "M_VALID", "description": "Master has payload: drives TVALID "
         "HIGH with TDATA + qualifiers and holds them stable until TREADY is "
         "also HIGH."},
        {"name": "M_XFER", "description": "TVALID and TREADY both HIGH on a "
         "rising ACLK edge: the transfer completes; master may present the "
         "next beat or return to M_IDLE."},
    ]
    d["fsm_states_slave"] = [
        {"name": "S_RESET", "description": "ARESETn LOW: slave commonly drives "
         "TREADY LOW."},
        {"name": "S_NOTREADY", "description": "Slave cannot accept: TREADY LOW "
         "(backpressure)."},
        {"name": "S_READY", "description": "Slave can accept a transfer: TREADY "
         "HIGH (may be asserted before or after TVALID)."},
        {"name": "S_XFER", "description": "TVALID and TREADY both HIGH: the "
         "slave captures the beat (TDATA + qualifiers)."},
    ]
    d["fsm_hints"] = {
        "trigger": "A transfer is triggered by the coincidence of TVALID and "
        "TREADY on a rising ACLK edge.",
        "rule": "Once TVALID is asserted it must remain asserted (with stable "
        "payload) until the transfer completes; the master must not wait for "
        "TREADY before asserting TVALID; the slave may wait for TVALID before "
        "TREADY.",
        "abort": "There is no protocol-level abort; a transfer simply stalls "
        "while TREADY is LOW (slave backpressure).",
    }
    d["anti_deadlock_rule"] = (
        "Deadlock is prevented by the asymmetric handshake rule: the master "
        "must NOT wait for TREADY before asserting TVALID, so the master can "
        "always make its data available; the slave is free to wait for TVALID. "
        "A live slave eventually asserts TREADY, completing the transfer.")
    d["exit_from_reset_or_poweron"] = (
        "During reset (ARESETn LOW) the master drives TVALID LOW and the slave "
        "commonly drives TREADY LOW. After ARESETn goes HIGH, the master may "
        "first assert TVALID on the next rising ACLK edge; transfers then "
        "proceed subject to TREADY backpressure.")
    d["default_ready_state_recommendation"] = {
        "master_idle": "TVALID=0; TDATA/qualifiers don't-care.",
        "master_active": "TVALID=1 with stable payload until TREADY=1.",
        "slave": "TREADY reflects acceptance capacity; may be high by default "
        "or gated by buffer space (backpressure).",
    }
    d["configurations"] = [
        {"name": "Point-to-point master->slave", "description": "One source "
         "streaming to one sink (the base AXI4-Stream connection)."},
        {"name": "Packetized stream", "description": "TLAST-delimited packets; "
         "TUSER may mark frame boundaries."},
        {"name": "Multiplexed via interconnect", "description": "Multiple "
         "streams share a channel; TID/TDEST route and order them."},
    ]
    d["timing_dependency_rule"] = (
        "All AXI4-Stream signals are sampled on the rising edge of the single "
        "shared ACLK. A transfer's timing depends only on the coincidence of "
        "TVALID and TREADY; there is no latency model, no read/write phase, and "
        "no forwarded/embedded clock. TVALID may first assert one ACLK edge "
        "after ARESETn is HIGH.")
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
        {"name": "TVALID/TREADY handshake", "purpose": "Observable transfer "
         "and backpressure timing for bring-up and protocol checking."},
        {"name": "TLAST", "purpose": "Observable packet boundaries; mismatched "
         "TLAST indicates a framing error."},
        {"name": "TKEEP/TSTRB byte typing", "purpose": "Observable byte types "
         "(data/position/null); the illegal TKEEP=0,TSTRB=1 is a checkable "
         "violation."},
        {"name": "TID/TDEST", "purpose": "Observable stream id / routing for "
         "verifying interconnect routing and per-stream ordering."},
        {"name": "TUSER", "purpose": "User-defined sideband can carry "
         "debug/marker information."},
    ]
    d["error_detection_mechanisms"] = [
        "Protocol checkers verify the TVALID/TREADY handshake rules (TVALID "
        "holds until TREADY; master does not wait for TREADY; payload stable).",
        "Illegal byte qualifier TKEEP=0,TSTRB=1 is detectable.",
        "Packet-framing checks: TLAST placement vs expected packet length.",
        "Routing checks: TDEST selects the expected destination; per-TID order "
        "preserved.",
        "Reset behavior check: TVALID must be LOW while ARESETn is LOW.",
    ]
    d["test_modes"] = [
        {"name": "BFM / VIP stimulus", "purpose": "AXI4-Stream master/slave "
         "verification IP drive and check the handshake, byte types, packets, "
         "and routing in simulation."},
        {"name": "Protocol assertion checking", "purpose": "Simulation-time "
         "assertions verify handshake legality and byte-type rules."},
        {"name": "On-chip signal capture", "purpose": "Logic-analyzer / "
         "signal-capture of the T-signals for in-system debug."},
    ]
    d["interrupt_or_event_sources"] = [
        {"event": "Packet boundary", "trigger": "TLAST HIGH on the last "
         "transfer of a packet."},
        {"event": "Backpressure", "trigger": "Slave deasserts TREADY."},
        {"event": "Stream start (application)", "trigger": "TUSER marks "
         "start-of-frame in video-style use."},
    ]
    d["notes"] = (
        "AXI4-Stream's protocol-level test surface is the observability of the "
        "T-signals and the checkable handshake/byte-type/framing/routing rules. "
        "There is no in-band register access (the interface is addressless); "
        "chip-level scan/BIST remain device/SoC concerns.")
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
        "AXI_STREAM_SPEC": "AMBA AXI4-Stream Protocol Specification (ARM IHI "
                           "0051)",
        "INTERFACE_FAMILY": "AXI4-Stream (single unidirectional stream "
                            "channel)",
        "SIGNALING": "single-ended synchronous logic",
        "LINE_ENCODING": "none",
        "EMBEDDED_CLOCK": False,
        "FORWARDED_CLOCK": False,
        "PARALLEL_SYNCHRONOUS": True,
        "MASTER_SOURCE_SLAVE_SINK": True,
        "UNIDIRECTIONAL": True,
        "HAS_ADDRESS": False,
        "TVALID_TREADY_HANDSHAKE": True,
        "TLAST_PACKET_FRAMING": True,
        "TKEEP_TSTRB_BYTE_TYPES": True,
        "TID_TDEST_ROUTING": True,
        "TUSER_SIDEBAND": True,
        "TWAKEUP_V2": True,
        "TDATA_WIDTH_MULTIPLE_OF_8": True,
        "TID_WIDTH_RECOMMENDED_MAX_BITS": 8,
        "TDEST_WIDTH_RECOMMENDED_MAX_BITS": 4,
    })
    d["interface_signal_constants"] = {s: True for s in _T_SIGNALS}
    d["byte_type_constants"] = {
        "data_byte": "TKEEP=1, TSTRB=1",
        "position_byte": "TKEEP=1, TSTRB=0",
        "null_byte": "TKEEP=0, TSTRB=0",
        "illegal": "TKEEP=0, TSTRB=1 (not permitted)",
    }
    d["transfer_property_constants"] = {
        "transfer": "one TVALID&TREADY cycle on a rising ACLK edge",
        "packet": "TLAST-delimited group of transfers",
        "stream": "the full sequence of transfers source->sink",
        "tvalid_holds_until_tready": True,
        "master_must_not_wait_for_tready": True,
        "slave_may_wait_for_tvalid": True,
        "tvalid_low_during_reset": True,
    }
    kc = _ensure_dict(d, "key_constants_for_RTL_authoring")
    kc.update({
        "is_serial": False,
        "is_parallel_synchronous": True,
        "embedded_clock": False,
        "forwarded_clock": False,
        "master_source_slave_sink": True,
        "unidirectional": True,
        "has_address": False,
        "tvalid_tready": True,
        "tlast_packet_framing": True,
        "tkeep_tstrb_byte_types": True,
        "tid_tdest_routing": True,
        "tuser_sideband": True,
        "twakeup_v2": True,
        "tdata_width_multiple_of_8": True,
        "mandatory_signals": ["TVALID", "TREADY"],
        "optional_signals": ["TDATA", "TSTRB", "TKEEP", "TLAST", "TID",
                             "TDEST", "TUSER", "TWAKEUP"],
    })
    d["default_signal_values_when_idle"] = {
        "master_idle": "TVALID=0; TDATA/qualifiers don't-care.",
        "slave_idle": "TREADY reflects acceptance capacity.",
        "reset": "TVALID=0 (master); TREADY commonly 0 (slave).",
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
    d["transfer_waveform"] = {
        "single": "Master drives TVALID HIGH with TDATA + qualifiers; slave "
                  "drives TREADY HIGH; on the rising ACLK edge where both are "
                  "HIGH the beat transfers.",
        "master_first": "Master may assert TVALID before TREADY; it holds "
                        "TVALID and stable payload until TREADY is HIGH.",
        "slave_first": "Slave may assert TREADY before TVALID; if no TVALID "
                       "arrives it may deassert TREADY again.",
        "backpressure": "Slave deasserts TREADY to stall the master; no "
                        "transfer occurs until TREADY is HIGH again.",
    }
    d["packet_waveform"] = {
        "tlast": "TLAST is HIGH on the last transfer of a packet; the next "
                 "transfer (TVALID&TREADY) begins the next packet.",
        "byte_types": "Each byte lane is data (TKEEP=1,TSTRB=1), position "
                      "(TKEEP=1,TSTRB=0), or null (TKEEP=0,TSTRB=0) on the "
                      "transferred beat.",
    }
    d["reset_waveform"] = (
        "While ARESETn is LOW the master holds TVALID LOW; the earliest the "
        "master may assert TVALID is one ACLK rising edge after ARESETn is "
        "HIGH.")
    d["clocking_note"] = (
        "All AXI4-Stream signals are sampled on the rising edge of the single "
        "shared ACLK; there is no forwarded or embedded clock and no line "
        "code.")
    d["general_timing_rule"] = (
        "A transfer completes on the rising ACLK edge at which TVALID and "
        "TREADY are both HIGH. TVALID, once asserted, holds with stable payload "
        "until completion; the master must not wait for TREADY before asserting "
        "TVALID; the slave may wait for TVALID before TREADY.")
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
        "AXI4-Stream interface contract: a component exposes an AXI4-Stream "
        "master (source) and/or slave (sink) port carrying a unidirectional "
        "stream. The master drives TVALID + payload; the slave drives TREADY. "
        "An AXI4-Stream interconnect (switch/multiplexer) can connect and route "
        "multiple streams using TID/TDEST. Commonly paired with a "
        "memory-mapped AMBA AXI control interface on the same component.")
    d["topology_description"] = (
        "Point-to-point: one master (source) connects to one slave (sink); "
        "data flows one way with TREADY backpressure flowing back. An "
        "interconnect can fan-in / fan-out / route multiple streams using "
        "TID/TDEST while preserving per-stream ordering.")
    io = _ensure_dict(d, "integration_overview")
    io.update({
        "spec": "AMBA AXI4-Stream Protocol Specification (ARM IHI 0051)",
        "interface_signals": list(_T_SIGNALS),
        "roles": "master (source/transmitter) / slave (sink/receiver)",
        "handshake": "TVALID + TREADY",
        "packet_framing": "TLAST",
        "byte_typing": "TKEEP / TSTRB (data / position / null)",
        "routing": "TID (stream id) / TDEST (destination)",
        "sideband": "TUSER",
        "wake": "TWAKEUP (AXI4-Stream v2 / AMBA 5)",
        "addressless": True,
        "companion": "memory-mapped AMBA AXI for control/configuration",
    })
    d["interface_categories"] = [
        "AXI4-Stream master (source) — drives TVALID + TDATA + qualifiers.",
        "AXI4-Stream slave (sink) — drives TREADY (backpressure).",
        "AXI4-Stream interconnect / switch — routes multiple streams by "
        "TID/TDEST.",
    ]
    d["interconnect_topologies_supported"] = [
        "Single master (source) to single slave (sink) point-to-point.",
        "Fan-out (one source to several sinks) via interconnect.",
        "Fan-in / multiplexing (several sources to one sink) via interconnect "
        "with TID/TDEST routing.",
        "Multi-stream switch routing by TDEST, ordering by TID.",
        "Mixed system: AXI4-Stream data path + memory-mapped AXI control.",
    ]
    d["default_signal_values_when_omitted"] = (
        "Only TVALID and TREADY are mandatory; an interface uses the subset of "
        "TDATA/TSTRB/TKEEP/TLAST/TID/TDEST/TUSER it needs. Omitted TKEEP/TSTRB "
        "default to all bytes being data bytes; omitted TLAST means an "
        "unframed (single indefinitely long packet) stream; omitted TID/TDEST "
        "means a single unrouted stream.")
    d["soc_dependent_items"] = [
        "TDATA_WIDTH (bits, a multiple of 8) and TSTRB/TKEEP widths "
        "(TDATA_WIDTH/8).",
        "Which optional signals are present (TSTRB/TKEEP/TLAST/TID/TDEST/"
        "TUSER/TWAKEUP).",
        "TID_WIDTH (<=8 recommended) and TDEST_WIDTH (<=4 recommended).",
        "TUSER_WIDTH and its meaning (per-transfer or per-byte-lane).",
        "Packetization (use of TLAST) and any frame structure via TUSER.",
        "Interconnect routing map (TDEST -> destination) and per-stream "
        "ordering policy.",
        "Clock (single shared ACLK) and reset (ARESETn) domain.",
    ]
    d["low_power_modes"] = {
        "note": "AXI4-Stream v2 (AMBA 5) adds TWAKEUP, which signals the "
                "presence of interface activity for low-power wake "
                "handshaking; clock gating and power domains are otherwise SoC "
                "concerns.",
    }
    d["device_classes_examples"] = [
        "Video/pixel source (AXI4-Stream master)",
        "DMA engine (AXI4-Stream master and/or slave)",
        "DSP / FFT / filter block (AXI4-Stream slave -> master)",
        "Packet classifier / forwarder (AXI4-Stream with TDEST routing)",
        "AXI4-Stream interconnect / switch (routes streams by TID/TDEST)",
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
        "partial - the AMBA AXI4-Stream specification defines interface timing "
        "and compliance behaviors (handshake, byte types, packet framing, "
        "routing) rather than a packaged testbench; AXI4-Stream BFMs / VIP and "
        "protocol checkers exercise them.")
    d["derived_compliance_test_categories"] = [
        "TVALID/TREADY handshake: transfer only when both HIGH on a rising "
        "ACLK edge.",
        "TVALID held until TREADY HIGH; payload stable while TVALID HIGH and "
        "TREADY LOW.",
        "Master does NOT wait for TREADY before asserting TVALID.",
        "Slave waits for TVALID before asserting TREADY (and may assert TREADY "
        "first).",
        "Backpressure: slave deasserts TREADY; master stalls; no data lost.",
        "Byte types: data (TKEEP=1,TSTRB=1), position (TKEEP=1,TSTRB=0), null "
        "(TKEEP=0,TSTRB=0); illegal TKEEP=0,TSTRB=1 never driven.",
        "Continuous (fully-packed) stream vs sparse (position/null bytes).",
        "Packet framing: TLAST on the last transfer; correct packet lengths.",
        "Routing: TDEST selects destination; TID preserves per-stream order.",
        "TUSER sideband carried correctly (per transfer or per byte lane).",
        "TWAKEUP wake behavior (AXI4-Stream v2).",
        "Reset: TVALID LOW while ARESETn LOW; first TVALID only after ARESETn "
        "HIGH.",
        "TVALID/TREADY-only interface (no TDATA) used purely for TID/TDEST or "
        "transfer counting.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L11 — OTP-equivalent fields (n/a for an interface spec).
# ----------------------------------------------------------------------
def _l11(gd: Path) -> None:
    p = gd / "L11_OTP_CONTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    d["otp_present"] = False
    d["otp_equivalent_factory_burned_fields"] = []
    d["notes"] = (
        "AXI4-Stream is an on-chip interface specification; it defines no "
        "OTP/fuse content. Any configuration (signal widths, optional-signal "
        "presence, packetization, routing) is set at design/elaboration time, "
        "not burned into fuses. This layer is genuinely N/A for the "
        "AXI4-Stream interface contract.")
    _write(p, d)


# ----------------------------------------------------------------------
# L12 — behavioral sequences.
# ----------------------------------------------------------------------
def _l12(gd: Path) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["single_transfer_sequence"] = [
        "1. Master drives TVALID HIGH with TDATA and qualifiers (TSTRB/TKEEP/"
        "TLAST/TID/TDEST/TUSER as used).",
        "2. Master holds TVALID and the payload stable (it must NOT wait for "
        "TREADY before asserting TVALID).",
        "3. Slave asserts TREADY when it can accept (it MAY wait for TVALID "
        "first).",
        "4. On the rising ACLK edge where TVALID and TREADY are both HIGH, the "
        "beat transfers.",
        "5. The master may present the next beat or deassert TVALID.",
    ]
    d["backpressure_sequence"] = [
        "1. Master asserts TVALID with stable payload.",
        "2. Slave holds TREADY LOW (cannot accept).",
        "3. Master keeps TVALID and payload asserted (no transfer occurs).",
        "4. Slave asserts TREADY; the transfer completes on that ACLK edge.",
    ]
    d["packet_sequence"] = [
        "1. Transfers proceed beat by beat (each on a TVALID&TREADY cycle).",
        "2. On the last transfer of the packet the master asserts TLAST HIGH.",
        "3. The next TVALID&TREADY transfer begins the next packet.",
        "4. If TLAST is not used the stream is one indefinitely long packet.",
    ]
    d["byte_type_sequence"] = [
        "1. For each byte lane the master sets TKEEP and TSTRB: data "
        "(TKEEP=1,TSTRB=1), position (TKEEP=1,TSTRB=0), or null "
        "(TKEEP=0,TSTRB=0).",
        "2. Interconnect may remove null bytes; position bytes hold layout but "
        "carry no data.",
        "3. The combination TKEEP=0,TSTRB=1 is never driven.",
    ]
    d["routing_sequence"] = [
        "1. Master sets TID (stream id) and TDEST (destination) on each "
        "transfer.",
        "2. Interconnect routes the transfer to the TDEST output port.",
        "3. Transfers with the same TID/TDEST are delivered in order.",
    ]
    d["reset_sequence"] = [
        "1. ARESETn LOW: master drives TVALID LOW; slave commonly drives "
        "TREADY LOW.",
        "2. ARESETn HIGH: on the next rising ACLK edge the master may assert "
        "TVALID; transfers resume subject to TREADY backpressure.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L13 — lab calibration (n/a; synchronous-logic interface).
# ----------------------------------------------------------------------
def _l13(gd: Path) -> None:
    p = gd / "L13_LAB_CALIBRATION.json"
    if not p.is_file():
        return
    d = _read(p)
    d["lab_calibration_present"] = False
    d["lab_measurement_targets_from_spec"] = [
        {"name": "Handshake timing closure", "purpose": "Verify "
         "TVALID/TREADY and the T-signal payload meet setup/hold at ACLK (an "
         "STA / timing-closure concern, not a lab-bench measurement)."},
    ]
    d["notes"] = (
        "AXI4-Stream is a synchronous-logic on-chip interface; there is no "
        "analog or lab calibration in the specification. Timing is closed by "
        "synthesis/STA at ACLK, not by bench calibration. This layer is "
        "essentially N/A for the AXI4-Stream contract.")
    _write(p, d)


# ----------------------------------------------------------------------
# L14 — versioning + traps.
# ----------------------------------------------------------------------
def _l14(gd: Path) -> None:
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["spec_version"] = "AMBA AXI4-Stream Protocol Specification (ARM IHI 0051)"
    f["previous_versions"] = [
        "AXI4-Stream is part of the AMBA family; the AXI4-Stream protocol was "
        "introduced alongside AMBA AXI4 (AMBA 4) and refined in AMBA 5. The "
        "master/slave roles are also described as source/sink and "
        "transmitter/receiver.",
    ]
    f["key_changes"] = [
        {"version": "AXI4-Stream (AMBA 4)",
         "summary": "Single-channel unidirectional stream: TVALID/TREADY "
         "handshake; TDATA/TSTRB/TKEEP/TLAST/TID/TDEST/TUSER payload; "
         "transfer/packet/stream and data/position/null byte types; TID/TDEST "
         "routing."},
        {"version": "AXI4-Stream v2 (AMBA 5)",
         "summary": "Adds TWAKEUP for low-power wake handshaking (signals the "
         "presence of interface activity)."},
    ]
    f["future_versions_industry_outline"] = [
        {"version": "AMBA evolution",
         "summary": "AXI4-Stream remains the streaming companion to the "
         "memory-mapped AMBA AXI protocol; tooling continues to generate "
         "AXI4-Stream interconnect and AXI4-Stream<->other-streaming bridges."},
    ]
    f["backward_compat_traps"] = [
        {"trap_name": "master_must_not_wait_for_tready",
         "rule": "A master must NOT wait for TREADY before asserting TVALID.",
         "trap": "Gating TVALID on TREADY creates a handshake deadlock."},
        {"trap_name": "tvalid_holds_until_tready",
         "rule": "Once asserted, TVALID and its payload must remain stable "
                 "until the transfer completes (TREADY HIGH).",
         "trap": "Deasserting TVALID or changing payload mid-handshake drops "
                 "or corrupts a transfer."},
        {"trap_name": "illegal_byte_qualifier",
         "rule": "TKEEP=0 with TSTRB=1 is not a valid byte type and is never "
                 "driven.",
         "trap": "Driving TSTRB=1 on a null byte (TKEEP=0) is illegal."},
        {"trap_name": "axi_stream_is_not_memory_mapped_axi",
         "rule": "AXI4-Stream is one unidirectional stream channel with no "
                 "address; memory-mapped AXI uses AW/W/B/AR/R address channels "
                 "with ARADDR/AWADDR and read/write transactions.",
         "trap": "Treating AXI4-Stream as memory-mapped (expecting an address "
                 "phase, read/write channels, or bursts)."},
        {"trap_name": "optional_signals",
         "rule": "Only TVALID and TREADY are mandatory; the rest are optional "
                 "with defined defaults when omitted.",
         "trap": "Assuming TKEEP/TSTRB/TLAST/TID/TDEST/TUSER are always "
                 "present."},
    ]
    f["version_naming_history_note"] = (
        "The AMBA AXI4-Stream Protocol Specification (Arm document IHI 0051) "
        "defines a single-channel, unidirectional stream protocol. Facts here "
        "are grounded in the public ARM AXI4-Stream specification: the "
        "TVALID/TREADY handshake, the payload/qualifier signals (TDATA, TSTRB, "
        "TKEEP, TLAST, TID, TDEST, TUSER, and TWAKEUP in v2), the transfer / "
        "packet / frame / stream concepts, the data / position / null byte "
        "types, TID/TDEST routing, and the no-address streaming model that "
        "distinguishes AXI4-Stream from the memory-mapped AMBA AXI protocol.")
    _write(p, d)


# ----------------------------------------------------------------------
# L15 — encoding / property tables.
# ----------------------------------------------------------------------
def _l15(gd: Path) -> None:
    p = gd / "L15_ENCODING_TABLES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["signal_table"] = {
        "header_columns": ["Signal", "Direction", "Role", "Mandatory"],
        "rows": [
            ["ACLK", "global", "single clock; rising-edge sampled", "yes"],
            ["ARESETn", "global", "active-LOW reset", "yes"],
            ["TVALID", "master->slave", "master driving valid transfer", "yes"],
            ["TREADY", "slave->master", "slave can accept", "yes"],
            ["TDATA", "master->slave", "payload (multiple of 8 bits)", "no"],
            ["TSTRB", "master->slave", "data vs position byte", "no"],
            ["TKEEP", "master->slave", "null byte qualifier", "no"],
            ["TLAST", "master->slave", "packet boundary", "no"],
            ["TID", "master->slave", "stream identifier", "no"],
            ["TDEST", "master->slave", "routing destination", "no"],
            ["TUSER", "master->slave", "user sideband", "no"],
            ["TWAKEUP", "master->slave", "v2 wake / activity", "no"],
        ],
    }
    f["byte_type_table"] = {
        "header_columns": ["Byte type", "TKEEP", "TSTRB", "Meaning"],
        "rows": [
            ["data byte", "1", "1", "content byte; must be transmitted"],
            ["position byte", "1", "0", "holds position; no data value"],
            ["null byte", "0", "0", "no meaning; may be removed"],
            ["(illegal)", "0", "1", "not permitted"],
        ],
    }
    f["concept_table"] = {
        "header_columns": ["Concept", "Definition"],
        "rows": [
            ["transfer", "one TVALID&TREADY cycle moving one beat"],
            ["packet", "one or more transfers delimited by TLAST"],
            ["frame", "application-defined grouping of packets"],
            ["stream", "the full sequence of transfers source->sink"],
        ],
    }
    f["width_table"] = {
        "header_columns": ["Parameter", "Constraint"],
        "rows": [
            ["TDATA_WIDTH", "multiple of 8 (integer number of bytes)"],
            ["TSTRB / TKEEP width", "TDATA_WIDTH / 8 (one bit per byte lane)"],
            ["TID_WIDTH", "recommended maximum 8 bits"],
            ["TDEST_WIDTH", "recommended maximum 4 bits"],
            ["TUSER_WIDTH", "application-defined"],
        ],
    }
    f["encoding_note"] = (
        "AXI4-Stream defines no line code; it is a synchronous-logic "
        "interface. Byte meaning is encoded by TKEEP/TSTRB (data / position / "
        "null bytes); packet framing by TLAST; routing by TID/TDEST. The "
        "'tables' here are the signal, byte-type, concept, and width tables "
        "from the AXI4-Stream specification.")
    f["tables"] = [
        "Signal table (12 AXI4-Stream signals + ACLK/ARESETn)",
        "Byte-type table (data / position / null + illegal)",
        "Concept table (transfer / packet / frame / stream)",
        "Width table (TDATA/TSTRB/TKEEP/TID/TDEST/TUSER constraints)",
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
        "Master (source) / slave (sink) roles with the mandatory TVALID/TREADY "
        "handshake.",
        "A transfer completes only when TVALID and TREADY are both HIGH on a "
        "rising ACLK edge.",
        "TVALID held (with stable payload) until TREADY HIGH; master never "
        "waits for TREADY before asserting TVALID.",
        "Correct byte typing via TKEEP/TSTRB (data / position / null); illegal "
        "TKEEP=0,TSTRB=1 never driven.",
        "TLAST used consistently to delimit packets (when packetized).",
        "TID/TDEST used consistently for routing and per-stream ordering "
        "(when multiplexed).",
        "TVALID LOW during reset (ARESETn LOW); first TVALID only after "
        "ARESETn HIGH.",
    ]
    f["must_not_have_properties"] = [
        "An address phase, read/write transaction, or AW/W/B/AR/R channels "
        "(those belong to memory-mapped AMBA AXI, not AXI4-Stream).",
        "ARADDR/AWADDR address buses or INCR/WRAP/FIXED burst types.",
        "A master waiting for TREADY before asserting TVALID.",
        "Deasserting TVALID or changing payload before a transfer completes.",
        "Driving the illegal byte qualifier TKEEP=0,TSTRB=1.",
        "A line code or differential physical layer (AXI4-Stream is "
        "synchronous-logic).",
    ]
    f["compliance_failure_modes"] = [
        {"mode": "handshake deadlock", "trigger": "Master waits for TREADY "
         "before asserting TVALID."},
        {"mode": "dropped transfer", "trigger": "TVALID deasserted or payload "
         "changed before TREADY HIGH."},
        {"mode": "illegal byte type", "trigger": "TKEEP=0 with TSTRB=1 "
         "driven."},
        {"mode": "framing error", "trigger": "Missing/extra TLAST vs expected "
         "packet boundaries."},
        {"mode": "routing/order error", "trigger": "Wrong TDEST or "
         "out-of-order delivery within a TID."},
        {"mode": "reset violation", "trigger": "TVALID asserted while ARESETn "
         "is LOW."},
    ]
    f["min_link_constraint"] = (
        "A compliant connection requires a master (source) and a slave (sink) "
        "with the TVALID/TREADY handshake on a shared ACLK/ARESETn and "
        "compatible (or adapter-bridgeable) TDATA/qualifier widths.")
    f["reset_behavior_compliance"] = (
        "On reset (ARESETn LOW) the master drives TVALID LOW; after ARESETn "
        "HIGH the master may first assert TVALID one ACLK edge later; transfers "
        "then proceed subject to TREADY backpressure.")
    f["axi_stream_distinguishers"] = (
        "AXI4-Stream is identified by: a single unidirectional stream channel "
        "with the TVALID/TREADY handshake and the T-prefixed payload "
        "TDATA/TSTRB/TKEEP/TLAST/TID/TDEST/TUSER, and the NO-address streaming "
        "source/sink model. This is distinct from memory-mapped AMBA AXI "
        "(AW/W/B/AR/R channels, ARVALID/AWVALID/RVALID/BVALID/WVALID, "
        "ARADDR/AWADDR, read/write transactions, INCR/WRAP bursts) and from "
        "Avalon-ST (startofpacket/endofpacket + Avalon vocabulary).")
    _write(p, d)


# ----------------------------------------------------------------------
# L17 — channel / signal catalog + dependency graph.
# ----------------------------------------------------------------------
def _l17(gd: Path) -> None:
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["channels"] = [
        {"name": "AXI4-Stream (the only channel)",
         "direction": "unidirectional master->slave",
         "purpose": "Transports a stream of data from source to sink.",
         "active_levels": "TVALID/TDATA/TSTRB/TKEEP/TLAST/TID/TDEST/TUSER "
         "master->slave; TREADY slave->master",
         "idle_level": "TVALID=0"},
    ]
    f["logical_signaling_levels"] = [
        {"name": "transfer",
         "meaning": "TVALID and TREADY both HIGH on a rising ACLK edge."},
        {"name": "backpressure",
         "meaning": "TREADY LOW; master stalls (holds TVALID + payload)."},
        {"name": "packet boundary", "meaning": "TLAST HIGH on the last "
         "transfer of a packet."},
        {"name": "byte type", "meaning": "TKEEP/TSTRB encode data / position / "
         "null per byte lane."},
        {"name": "reset", "meaning": "ARESETn LOW; TVALID driven LOW."},
    ]
    f["packet_types_summary"] = [
        {"class": "byte types",
         "members": ["data byte", "position byte", "null byte"], "count": 3},
        {"class": "stream forms",
         "members": ["continuous (fully-packed)", "sparse (position/null)",
                     "packetized (TLAST)"], "count": 3},
    ]
    cc = _ensure_dict(f, "channel_counts")
    cc.update({
        "channel_count": 1,
        "signal_count": len(_T_SIGNALS),
        "mandatory_signal_count": 2,
        "optional_signal_count": len(_T_SIGNALS) - 4,
        "role_pair": "master(source) / slave(sink)",
        "byte_type_count": 3,
    })
    f["global_signals"] = [
        {"name": "ACLK", "purpose": "Single shared clock; all signals sampled "
         "on its rising edge."},
        {"name": "ARESETn", "purpose": "Active-LOW reset; TVALID LOW during "
         "reset."},
    ]
    f["dependency_graph"] = {
        "common_rule": "All AXI4-Stream signals are sampled on the rising edge "
        "of the shared ACLK and respect ARESETn. A transfer depends solely on "
        "the coincidence of TVALID and TREADY; there is no address phase, "
        "latency model, or read/write dependency.",
        "data_dependency": "A beat of TDATA + qualifiers transfers only when "
        "TVALID (master) and TREADY (slave) are both HIGH. TLAST depends on "
        "the packet boundary; routing depends on TID/TDEST.",
    }
    f["handshake_pairs"] = [
        {"name": "TVALID/TREADY", "from": "master", "to": "slave",
         "rule": "Transfer completes when both HIGH on a rising ACLK edge; "
         "TVALID holds until TREADY; master must not wait for TREADY; slave "
         "may wait for TVALID."},
    ]
    f["ordering_rules"] = {
        "stream_order": "Transfers within one stream (one TID/TDEST) are "
        "delivered in order.",
        "interconnect": "An interconnect preserves per-TID ordering while "
        "routing by TDEST; ordering between different TID/TDEST values is not "
        "defined.",
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
        "Point-to-point unidirectional stream from a master (source) to a "
        "slave (sink). An AXI4-Stream interconnect (switch/multiplexer) can "
        "fan-in / fan-out / route multiple streams using TID/TDEST while "
        "preserving per-stream ordering. There is no address-mapped fabric.")
    f["supported_topologies"] = [
        {"name": "Point-to-point", "description": "One master (source) to one "
         "slave (sink)."},
        {"name": "Fan-out", "description": "One source broadcast/routed to "
         "several sinks via interconnect."},
        {"name": "Fan-in / multiplexing", "description": "Several sources "
         "merged to one sink, routed/ordered by TID/TDEST."},
        {"name": "Switch", "description": "Multi-port routing by TDEST, "
         "per-stream ordering by TID."},
        {"name": "Mixed system", "description": "AXI4-Stream data path plus a "
         "memory-mapped AXI control interface."},
    ]
    f["master_slave_role_summary"] = [
        {"role": "AXI4-Stream master (source/transmitter)", "description":
         "Drives TVALID + TDATA + qualifiers; produces the stream."},
        {"role": "AXI4-Stream slave (sink/receiver)", "description":
         "Drives TREADY; consumes the stream (backpressure via TREADY)."},
        {"role": "AXI4-Stream interconnect / switch", "description":
         "Routes streams by TDEST and orders per TID."},
    ]
    f["interconnect_role"] = (
        "An AXI4-Stream interconnect routes streams between sources and sinks "
        "using TDEST (destination) and preserves per-stream ordering using TID. "
        "It may also adapt data widths and insert register slices for timing; "
        "it never adds an address phase (the protocol stays addressless).")
    f["ordering_guarantees"] = {
        "stream_ordering": "Transfers within one TID/TDEST are delivered in "
        "order.",
        "cross_stream": "Ordering between different TID/TDEST values is not "
        "defined by the protocol.",
    }
    f["memory_vs_peripheral_regions"] = (
        "Not applicable — AXI4-Stream is addressless. There are no memory or "
        "peripheral address regions; routing is by TID/TDEST, not by address.")
    dc = _ensure_dict(f, "device_classification")
    dc["master_source"] = ("Data producer (video source, packet generator, "
                           "DMA read).")
    dc["slave_sink"] = ("Data consumer (DMA write, packet processor, DSP "
                        "block).")
    dc["interconnect"] = "Stream switch/multiplexer routing by TID/TDEST."
    f["default_signal_values_evidence_tables"] = [
        "AMBA AXI4-Stream Protocol Specification (ARM IHI 0051) — signal roles "
        "and handshake",
        "Byte-type encoding (TKEEP/TSTRB: data / position / null)",
        "Packet framing (TLAST) and stream forms",
        "TID/TDEST routing and ordering rules",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L19 — constraints / PDK (interface-level, not PDK).
# ----------------------------------------------------------------------
def _l19(gd: Path) -> None:
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["constraints_present"] = True
    f["interface_constraints"] = {
        "signaling": "single-ended synchronous logic (on-chip)",
        "line_encoding": "none",
        "clocking": "single shared ACLK; all signals sampled on its rising "
                    "edge; no forwarded/embedded clock",
        "reset": "active-LOW ARESETn; TVALID LOW during reset",
        "handshake": "TVALID + TREADY",
        "addressless": True,
        "packet_framing": "TLAST",
        "byte_types": "TKEEP/TSTRB (data / position / null)",
        "routing": "TID / TDEST",
        "tdata_width": "multiple of 8 bits",
        "tstrb_tkeep_width": "TDATA_WIDTH / 8",
        "tid_width_max": 8,
        "tdest_width_max": 4,
    }
    f["notes"] = (
        "AXI4-Stream is an on-chip interface specification; it imposes "
        "interface handshake/timing constraints (TVALID/TREADY, payload "
        "stability, reset behavior, byte-type and width rules), not "
        "PDK-specific SDC/floorplan rules. Physical constraints (timing "
        "closure at ACLK) are device/implementation concerns.")
    _write(p, d)


# ----------------------------------------------------------------------
# L20 — DFT / scan (interface-level observability).
# ----------------------------------------------------------------------
def _l20(gd: Path) -> None:
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["dft_present"] = "partial"
    f["in_band_test_facilities"] = [
        {"name": "Handshake observability", "purpose": "TVALID/TREADY timing "
         "is observable for bring-up and protocol checking."},
        {"name": "TLAST / packet observability", "purpose": "Packet boundaries "
         "are observable; mismatches flag framing errors."},
        {"name": "Byte-type observability", "purpose": "TKEEP/TSTRB encode "
         "data/position/null; the illegal combination is detectable."},
        {"name": "Routing observability", "purpose": "TID/TDEST expose stream "
         "id and destination for routing/ordering checks."},
        {"name": "Protocol assertions / VIP", "purpose": "AXI4-Stream "
         "verification IP and assertions check handshake and byte-type "
         "legality."},
    ]
    f["internal_diagnostics_observability"] = [
        "TVALID/TREADY handshake observability (transfers, backpressure).",
        "TLAST packet-boundary observability.",
        "TKEEP/TSTRB byte-type observability.",
        "TID/TDEST routing observability.",
        "TUSER sideband (may carry debug markers).",
    ]
    f["out_of_band_test_facilities"] = [
        "Simulation BFMs / AXI4-Stream verification IP and protocol checkers.",
        "On-chip logic-analyzer capture of the T-signals.",
    ]
    f["notes"] = (
        "AXI4-Stream's protocol-level DFT surface is the observability of the "
        "T-signals and the checkable handshake/byte-type/framing/routing rules. "
        "There is no in-band register access (the interface is addressless); "
        "chip-level scan/BIST remain device/SoC concerns.")
    _write(p, d)


# ----------------------------------------------------------------------
# L21 — power intent (mostly n/a at protocol level; TWAKEUP in v2).
# ----------------------------------------------------------------------
def _l21(gd: Path) -> None:
    p = gd / "L21_POWER_INTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["power_intent_present"] = False
    f["link_power_management_states"] = []
    f["notes"] = (
        "The AXI4-Stream protocol defines no detailed protocol-level power "
        "states. AXI4-Stream v2 (AMBA 5) adds the TWAKEUP signal, which "
        "indicates the presence of interface activity for low-power wake "
        "handshaking, but power domains and clock gating are otherwise SoC / "
        "device concerns and out of scope for the AXI4-Stream interface "
        "contract.")
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
        "TVALID/TREADY handshake legality (transfer only when both HIGH).",
        "TVALID held until TREADY; payload stable while TVALID HIGH.",
        "Master never waits for TREADY before TVALID; slave may wait for "
        "TVALID.",
        "Backpressure (slave deasserts TREADY) with no data loss.",
        "Byte types data / position / null; illegal TKEEP=0,TSTRB=1 absent.",
        "Continuous vs sparse streams.",
        "Packet framing via TLAST.",
        "Routing via TID/TDEST and per-stream ordering.",
        "TUSER sideband fidelity.",
        "TWAKEUP wake behavior (AXI4-Stream v2).",
        "Reset behavior (TVALID LOW during reset; first TVALID after ARESETn "
        "HIGH).",
        "Width/parameter adaptation through an interconnect.",
    ]
    f["notes"] = (
        "The AMBA AXI4-Stream specification does not ship a packaged "
        "testbench, but implies a verification plan covering the TVALID/TREADY "
        "handshake rules, byte typing (TKEEP/TSTRB), packet framing (TLAST), "
        "routing/ordering (TID/TDEST), sideband (TUSER), wake (TWAKEUP), and "
        "reset behavior. AXI4-Stream BFMs / verification IP and protocol "
        "checkers provide the conformance checks.")
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
        "Byte typing (TKEEP/TSTRB) ensures null/position bytes are not "
        "mistaken for data; the illegal TKEEP=0,TSTRB=1 is forbidden.",
        "The TVALID/TREADY handshake guarantees no transfer is lost or "
        "duplicated under backpressure.",
        "TLAST delimits packets so a sink can detect truncated/extended "
        "packets.",
    ]
    f["anti_tampering_features"] = []
    f["confidentiality_features"] = []
    f["authentication_features"] = []
    f["future_security_pointers"] = [
        "Access control / isolation is an interconnect/SoC concern: a stream "
        "switch can restrict which sources reach which sinks by TDEST.",
        "Carried-application security (encryption, authentication, integrity "
        "beyond byte typing) is the responsibility of the connected IP, not of "
        "the AXI4-Stream interface contract.",
    ]
    f["notes"] = (
        "AXI4-Stream is an on-chip interface specification with no built-in "
        "cryptography. Its protections are anti-corruption qualifiers (byte "
        "typing, TLAST framing, the lossless handshake) and the "
        "access-control/isolation provided by an interconnect and the "
        "connected IP. Confidentiality / integrity / authentication are out of "
        "scope for the AXI4-Stream contract.")
    _write(p, d)
