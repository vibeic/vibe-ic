"""InfiniBand Architecture (IBTA) protocol synth helper.

New protocol class — an OPEN, SWITCHED-FABRIC, channel-based serial HPC /
data-center interconnect standardized by the InfiniBand Trade Association
(IBTA). End nodes attach as Channel Adapters (HCA = Host CA, TCA = Target
CA); the fabric is built of switches + routers and is managed by a Subnet
Manager (SM) that assigns 16-bit Local Identifiers (LIDs). The stack is
Physical / Link / Network / Transport / Upper (verbs). The Link Layer uses
the Local Route Header (LRH: SLID/DLID/SL/VL), Virtual Lanes (VL0..VL15)
with VL arbitration and absolute credit-based flow control. The Network
Layer uses the Global Route Header (GRH: 128-bit GIDs). The Transport
Layer uses Queue Pairs (Send + Receive queues), Completion Queues, the
verbs interface, service types RC/UC/UD/RD, SEND/RECEIVE + RDMA
READ/WRITE + Atomics, and the Base Transport Header (BTH) with a 24-bit
Packet Sequence Number (PSN).

Doctrine — GENERAL not keyword: detection (`is_infiniband`) uses canonical
STRUCTURAL signatures read from the L-doc / input-doc CONTENT blob ONLY —
the InfiniBand transport object (Queue Pair) PLUS the IB-specific
link/network addressing (LID/LRH + Virtual Lanes + Subnet Manager) PLUS
the Channel-Adapter end-node model PLUS the verbs/RDMA-over-IB transport
and the BTH/GRH headers. It NEVER reads a filename or a benchmark-folder
name. Tokens are matched on WORD BOUNDARIES so substrings such as the
"LID" inside "VALID"/"INVALID"/"consolidate" cannot trip the detector
(this is why the plain Ethernet spec — which contains 385 "LID"
substrings but zero Queue-Pair / LRH / Virtual-Lane / Subnet-Manager
tokens — does NOT false-fire).

Sibling MUTEX — InfiniBand sits next to the Ethernet family in the
benchmark tree. The detector DEFERS (returns False) when the document is:
  * Ethernet-primary  — MAC / MII / preamble / 802.3 framing with NO
    Queue Pair / LID-via-LRH / Virtual Lane / Subnet Manager (a plain
    Ethernet or 800G-Ethernet spec).
  * Fibre-Channel-primary — N_Port / FLOGI / FC frame vocabulary with no
    IB QP/LRH/VL/SM structure (a parallel agent is adding FibreChannel;
    defer to it).
  * RoCE-only — "RDMA over Converged Ethernet" that carries an Ethernet
    MAC + UDP but LACKS the IB Link/Network headers (LRH/LID/SM). RoCE
    reuses the IB transport (QP/BTH) over Ethernet, so the IB-specific
    LINK-layer signature (LRH/LID + Virtual Lanes + Subnet Manager) is
    what distinguishes a native InfiniBand fabric from RoCE.

The IB structural predicate REQUIRES the native IB link/network signature
(LRH/LID + Virtual Lanes + Subnet Manager + Channel Adapter), so an
Ethernet, Fibre-Channel, or RoCE-only document cannot satisfy it.

Public entry: `apply_infiniband_synth(generated_docs_dir, is_infiniband,
infiniband_ic_name)`.  Module-level detector: `is_infiniband(blob)`.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

import l_doc_generator_stamp as _stamp


# ----------------------------------------------------------------------
# Module-level detector (content-only, word-boundary, with sibling MUTEX).
# ----------------------------------------------------------------------
def _wb(blob_low: str, *tokens: str) -> bool:
    """True iff EVERY token appears as a whole word (word boundary) in the
    lowercased blob. General word-boundary match — no filename reads."""
    for t in tokens:
        if not re.search(r"\b" + re.escape(t.lower()) + r"\b", blob_low):
            return False
    return True


def is_infiniband(blob: str) -> bool:
    """Content-only InfiniBand detector with an Ethernet / Fibre-Channel /
    RoCE sibling MUTEX. Reads ONLY the spec text `blob` — never a filename
    or a benchmark name. All structural tokens are matched on word
    boundaries.
    """
    if not blob:
        return False
    low = blob.lower()

    # --- IB-specific structural signals (whole-word) ---
    queue_pair = _wb(low, "queue pair") or _wb(low, "queue pairs")
    # LID delivered via the Local Route Header (NOT a bare "LID" substring).
    lrh = (_wb(low, "local route header")
           or _wb(low, "lrh")
           or (_wb(low, "slid") and _wb(low, "dlid")))
    virtual_lane = _wb(low, "virtual lane") or _wb(low, "virtual lanes")
    subnet_manager = (_wb(low, "subnet manager")
                      or _wb(low, "subnet management"))
    channel_adapter = (_wb(low, "channel adapter")
                       or _wb(low, "channel adapters")
                       or (_wb(low, "hca") and _wb(low, "tca")))
    grh_gid = (_wb(low, "global route header")
               or _wb(low, "grh")
               or _wb(low, "global identifier"))
    bth = (_wb(low, "base transport header")
           or _wb(low, "bth")
           or _wb(low, "packet sequence number")
           or _wb(low, "psn"))
    verbs_rdma = (_wb(low, "verbs")
                  or (_wb(low, "rdma")
                      and (_wb(low, "completion queue")
                           or queue_pair)))
    name_token = (_wb(low, "infiniband")
                  or _wb(low, "infiniband architecture")
                  or _wb(low, "ibta"))

    # The native IB link/network signature — present in a real InfiniBand
    # fabric spec, ABSENT from Ethernet / Fibre-Channel / RoCE-only docs.
    ib_link_network = lrh and virtual_lane and subnet_manager

    ib_structure = (
        queue_pair
        and ib_link_network
        and channel_adapter
        and (bth or verbs_rdma)
        and grh_gid
    )

    # --- Sibling MUTEX: Ethernet-primary ---
    ethernet_primary = (
        (_wb(low, "mii") or _wb(low, "gmii") or _wb(low, "preamble")
         or _wb(low, "802.3") or _wb(low, "media access control"))
        and not (queue_pair or lrh or virtual_lane or subnet_manager
                 or channel_adapter or name_token)
    )
    if ethernet_primary:
        return False

    # --- Sibling MUTEX: Fibre-Channel-primary ---
    fibre_channel_primary = (
        (_wb(low, "n_port") or _wb(low, "flogi") or _wb(low, "plogi")
         or _wb(low, "fibre channel") or _wb(low, "fibre-channel"))
        and not (queue_pair or lrh or virtual_lane or subnet_manager
                 or channel_adapter or name_token)
    )
    if fibre_channel_primary:
        return False

    # --- Sibling MUTEX: RoCE-only (RDMA over Ethernet, no IB link layer) ---
    roce_only = (
        (_wb(low, "roce")
         or _wb(low, "rdma over converged ethernet")
         or _wb(low, "rdma over ethernet"))
        and (_wb(low, "ethernet") and (_wb(low, "udp") or _wb(low, "mac")))
        and not ib_link_network
    )
    if roce_only:
        return False

    return bool(
        ib_structure
        or (name_token and queue_pair and ib_link_network)
        or (name_token and channel_adapter and lrh and virtual_lane)
    )


# ----------------------------------------------------------------------
# Synth plumbing.
# ----------------------------------------------------------------------
def _read(p: Path) -> dict:
    return json.loads(p.read_text())


def _write(p: Path, d: dict) -> None:
    # THE L-document write chokepoint: stamps the producing release onto
    # the document, then serialises it byte-identically to before.
    _stamp.dump(p, d)


def _ensure_dict(d: dict, key: str) -> dict:
    """Return d[key] as a dict, replacing a pre-existing None/empty/non-dict.
    (Mirrors the i2s/_l2 setdefault-None fix.)"""
    v = d.get(key)
    if not isinstance(v, dict):
        v = {}
        d[key] = v
    return v


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

# Canonical IBTA structural facts.
_LINK_SPEEDS = [
    {"name": "SDR", "long": "Single Data Rate", "per_lane_Gbps": 2.5,
     "line_code": "8b/10b"},
    {"name": "DDR", "long": "Double Data Rate", "per_lane_Gbps": 5,
     "line_code": "8b/10b"},
    {"name": "QDR", "long": "Quad Data Rate", "per_lane_Gbps": 10,
     "line_code": "8b/10b"},
    {"name": "FDR", "long": "Fourteen Data Rate", "per_lane_Gbps": 14,
     "line_code": "64b/66b"},
    {"name": "EDR", "long": "Enhanced Data Rate", "per_lane_Gbps": 25,
     "line_code": "64b/66b"},
    {"name": "HDR", "long": "High Data Rate", "per_lane_Gbps": 50,
     "line_code": "64b/66b (PAM4)"},
    {"name": "NDR", "long": "Next Data Rate", "per_lane_Gbps": 100,
     "line_code": "PAM4"},
]
_LINK_WIDTHS = ["1x", "4x", "12x"]
_MTU_BYTES = [256, 512, 1024, 2048, 4096]
_SERVICE_TYPES = ["RC", "UC", "UD", "RD"]


def apply_infiniband_synth(generated_docs_dir: Path, is_infiniband: bool,
                           infiniband_ic_name: Optional[str]) -> None:
    """Apply the InfiniBand (IBTA) synth when the IB signature matched.

    Force-assigns (direct assignment, NOT setdefault) the IB-canonical
    values across all 24 L docs. L17 channels are force-overwritten.
    """
    if not is_infiniband:
        return
    gd = Path(generated_docs_dir)

    # --- Force ic_name across ALL 24 docs FIRST. ---
    if infiniband_ic_name is not None:
        for n in _MAIN_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                d["ic_name"] = infiniband_ic_name
                _write(q, d)
        for n in _FIELDS_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                f = _ensure_dict(d, "fields")
                f["ic_name"] = infiniband_ic_name
                d["ic_name"] = infiniband_ic_name  # belt-and-braces
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
# L1 — datasheet.
# ----------------------------------------------------------------------
def _l1(gd: Path) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    d["document_title"] = "InfiniBand Architecture Specification (IBTA)"
    d["version"] = "InfiniBand Architecture Release 1.x"
    d["revised_date"] = "InfiniBand Trade Association (IBTA)"
    d["manufacturer"] = "InfiniBand Trade Association (IBTA)"
    d["copyright"] = "© InfiniBand Trade Association"
    d["abstract"] = (
        "InfiniBand (IB) is an open, switched-fabric, channel-based serial "
        "point-to-point I/O interconnect standardized by the InfiniBand "
        "Trade Association (IBTA) for high-performance computing, "
        "data-center clustering, and storage. End nodes attach to the fabric "
        "through Channel Adapters — a Host Channel Adapter (HCA) in a "
        "processor node and a Target Channel Adapter (TCA) in an I/O node. "
        "The fabric is built from switches (which forward within a subnet on "
        "the 16-bit Local Identifier / LID) and routers (which forward "
        "between subnets on the 128-bit Global Identifier / GID), and is "
        "managed by a Subnet Manager (SM) that assigns LIDs and programs the "
        "forwarding tables. The architecture is layered: Physical, Link "
        "(Local Route Header with SLID/DLID/SL/VL, Virtual Lanes, "
        "credit-based flow control), Network (Global Route Header), "
        "Transport (Queue Pairs, Completion Queues, the verbs interface, "
        "service types RC/UC/UD/RD, SEND/RECEIVE + RDMA READ/WRITE + "
        "Atomics, Base Transport Header with a 24-bit Packet Sequence "
        "Number), and the Upper Layers (verbs / ULPs). Per-lane signaling "
        "rates span SDR 2.5 to NDR 100 Gbps; link widths are 1x/4x/12x.")
    d["keywords"] = [
        "InfiniBand", "IBTA", "Channel Adapter", "HCA", "TCA", "switch",
        "router", "Subnet Manager", "LID", "Local Route Header", "LRH",
        "Service Level", "Virtual Lane", "credit-based flow control",
        "Global Route Header", "GRH", "GID", "Queue Pair", "QP",
        "Completion Queue", "verbs", "RC", "UC", "UD", "RD", "RDMA",
        "Base Transport Header", "BTH", "Packet Sequence Number", "PSN",
        "MTU", "8b/10b", "64b/66b",
    ]
    d["external_pins"] = [
        "Serial differential lanes (transmit + receive pairs) — 1x / 4x / "
        "12x link width; per-lane 2.5-100 Gbps (SDR..NDR)",
        "Link training / management signals (Physical-Layer link states: "
        "Down, Polling, Configuration, LinkUp)",
        "Reference clock / power / ground (implementation-defined)",
    ]
    d["supported_link_speeds"] = [s["name"] for s in _LINK_SPEEDS]
    d["supported_link_widths"] = list(_LINK_WIDTHS)
    d["supported_mtu_bytes"] = list(_MTU_BYTES)
    d["modes_of_operation"] = [
        {"name": "Reliable Connected (RC)",
         "note": "Connection between two QPs; hardware-acknowledged, "
                 "in-order, reliable delivery."},
        {"name": "Unreliable Connected (UC)",
         "note": "Connection without acknowledgement."},
        {"name": "Unreliable Datagram (UD)",
         "note": "Connectionless; single-MTU messages; used by management "
                 "and multicast."},
        {"name": "Reliable Datagram (RD)",
         "note": "Reliable delivery without a per-peer connection (uses an "
                 "End-to-End Context, EEC)."},
    ]
    d["key_features"] = [
        "Open, switched-fabric, channel-based serial interconnect (IBTA).",
        "End nodes are Channel Adapters: Host Channel Adapter (HCA) in a "
        "host, Target Channel Adapter (TCA) in an I/O node.",
        "Fabric of switches (forward within a subnet on the 16-bit LID) and "
        "routers (forward between subnets on the 128-bit GID).",
        "Subnet Manager (SM) discovers topology, assigns 16-bit LIDs, "
        "programs switch forwarding tables; SMPs ride VL15 / QP0.",
        "Layered stack: Physical / Link / Network / Transport / Upper "
        "(verbs).",
        "Link Layer: Local Route Header (LRH) with SLID, DLID, Service Level "
        "(SL), Virtual Lane (VL).",
        "Up to 15 data Virtual Lanes (VL0..VL14) plus management VL15, with "
        "SL-to-VL mapping and VL arbitration.",
        "Absolute, credit-based, per-VL flow control (self-correcting "
        "cumulative credits).",
        "Network Layer: Global Route Header (GRH, 40 B) with 128-bit GIDs "
        "(IPv6-style: 64-bit subnet prefix + 64-bit GUID).",
        "Transport Layer: Queue Pairs (Send + Receive Queues), Completion "
        "Queues, and the verbs interface.",
        "Four service types: RC / UC / UD / RD.",
        "Operations: SEND/RECEIVE (channel semantics) and RDMA WRITE / RDMA "
        "READ (memory semantics) + Atomics (CmpSwap, FetchAdd).",
        "Base Transport Header (BTH) with OpCode, 24-bit destination QPN, "
        "24-bit Packet Sequence Number (PSN), and Partition Key (P_Key).",
        "Per-lane signaling SDR 2.5 / DDR 5 / QDR 10 / FDR 14 / EDR 25 / "
        "HDR 50 / NDR 100 Gbps; widths 1x/4x/12x; 8b/10b (<=QDR) or "
        "64b/66b (>=FDR).",
        "Path MTU one of 256 / 512 / 1024 / 2048 / 4096 bytes; messages "
        "segmented First/Middle/Last/Only.",
        "16-bit Variant CRC (VCRC, per hop) + 32-bit Invariant CRC (ICRC, "
        "end-to-end).",
    ]
    d["topology_summary"] = (
        "Switched fabric: processor nodes and I/O nodes attach as Channel "
        "Adapters and are interconnected by switches (intra-subnet) and "
        "routers (inter-subnet). A subnet is managed by a Subnet Manager "
        "that assigns 16-bit LIDs. Multiple subnets are joined by routers "
        "using 128-bit GIDs.")
    d["package_summary"] = (
        "InfiniBand is an interconnect-architecture specification (IBTA), "
        "not a single packaged part. It defines the layered protocol "
        "(Physical/Link/Network/Transport), the Channel-Adapter end-node "
        "model, the switch/router fabric, the Subnet Manager, and the verbs "
        "interface. Physical packaging (HCA cards, switch silicon, cabling/"
        "backplane) is implementation-specific.")
    d["use_cases"] = [
        "HPC compute clusters (MPI over RDMA, low latency)",
        "Data-center server-to-server clustering",
        "Storage networking (SRP, iSER, NVMe-oF over IB)",
        "GPU / accelerator clustering (GPUDirect RDMA)",
        "Lossless, congestion-managed fabrics requiring guaranteed delivery",
    ]
    d["revision_history"] = [
        {"version": "InfiniBand Architecture Release 1.x",
         "date": "IBTA",
         "description": "Core Architecture (Volume 1) + Physical "
                        "Specification (Volume 2): layered "
                        "Physical/Link/Network/Transport stack, Channel "
                        "Adapters, switches/routers, Subnet Manager, LRH/GRH/"
                        "BTH, Queue Pairs, verbs, RC/UC/UD/RD, RDMA, "
                        "SDR..NDR link speeds."},
    ]
    d["overview"] = (
        "InfiniBand (IB) is an open, switched-fabric, channel-based serial "
        "interconnect standardized by the InfiniBand Trade Association "
        "(IBTA). Processor and I/O nodes attach to the fabric as Channel "
        "Adapters: a Host Channel Adapter (HCA) implements the verbs "
        "interface for host software, while a Target Channel Adapter (TCA) "
        "serves an I/O node. Switches forward packets within a subnet using "
        "the 16-bit Local Identifier (LID) carried in the Local Route Header "
        "(LRH); routers forward between subnets using the 128-bit Global "
        "Identifier (GID) carried in the Global Route Header (GRH). A Subnet "
        "Manager (SM) discovers the topology, assigns LIDs, and programs the "
        "forwarding tables, exchanging Subnet Management Packets (SMPs) on "
        "QP0 over the management Virtual Lane VL15. The Link Layer divides a "
        "physical link into Virtual Lanes (VL0..VL14 data plus VL15 "
        "management), maps the Service Level (SL) to a VL, arbitrates VLs, "
        "and applies absolute credit-based flow control per VL. The "
        "Transport Layer delivers messages end-to-end through Queue Pairs "
        "(a Send Queue + a Receive Queue), posts completions to Completion "
        "Queues, and is driven by the verbs interface; it supports four "
        "service types (RC/UC/UD/RD), SEND/RECEIVE and RDMA READ/WRITE plus "
        "Atomics, and uses the Base Transport Header (BTH) whose 24-bit "
        "Packet Sequence Number (PSN) drives reliable delivery. Links run "
        "from SDR (2.5 Gbps/lane) to NDR (100 Gbps/lane) at widths "
        "1x/4x/12x, and the path MTU is one of 256/512/1024/2048/4096 "
        "bytes.")
    _write(p, d)


# ----------------------------------------------------------------------
# L2 — FRS.
# ----------------------------------------------------------------------
def _l2(gd: Path) -> None:
    p = gd / "L2_FRS.json"
    if not p.is_file():
        return
    d = _read(p)
    po = _ensure_dict(d, "protocol_overview")
    po["type"] = (
        "Open, switched-fabric, channel-based serial point-to-point I/O "
        "interconnect (IBTA). Layered Physical / Link / Network / Transport "
        "/ Upper stack; end nodes are Channel Adapters (HCA/TCA); fabric of "
        "switches + routers; managed by a Subnet Manager.")
    po["duplex"] = (
        "full-duplex serial links (separate transmit and receive "
        "differential lane pairs per lane).")
    po["serial"] = True
    po["source_synchronous"] = False
    po["embedded_clock"] = True
    po["encoding"] = (
        "8b/10b for SDR/DDR/QDR; 64b/66b for FDR/EDR/HDR; PAM4 modulation "
        "for HDR/NDR. Integrity via per-hop 16-bit VCRC and end-to-end "
        "32-bit ICRC.")
    po["per_lane_signaling_Gbps"] = {s["name"]: s["per_lane_Gbps"]
                                     for s in _LINK_SPEEDS}
    po["link_widths"] = list(_LINK_WIDTHS)
    po["mtu_bytes"] = list(_MTU_BYTES)
    po["layers"] = [
        "Upper Layers (verbs / consumer interface, ULPs: IPoIB, SRP, iSER, "
        "MPI)",
        "Transport Layer (Queue Pairs, Completion Queues, BTH, PSN, "
        "end-to-end reliability, RC/UC/UD/RD)",
        "Network Layer (Global Route Header, 128-bit GIDs, inter-subnet "
        "routing)",
        "Link Layer (Local Route Header: LID/SL/VL, Virtual Lanes, "
        "credit-based flow control, VCRC)",
        "Physical Layer (serial lanes, 8b/10b or 64b/66b, link training)",
    ]
    po["end_nodes"] = {
        "HCA": "Host Channel Adapter — channel adapter in a processor node; "
               "implements the verbs interface.",
        "TCA": "Target Channel Adapter — channel adapter in an I/O node; "
               "presents a device-specific I/O Controller interface.",
    }
    po["fabric_devices"] = {
        "switch": "Forwards packets within a subnet using the DLID in the "
                  "LRH.",
        "router": "Forwards packets between subnets using the DGID in the "
                  "GRH.",
    }
    po["subnet_manager"] = (
        "Discovers the topology, assigns each port a 16-bit LID, programs "
        "switch forwarding tables, establishes paths; exchanges SMPs on QP0 "
        "over VL15.")
    po["packet_format"] = (
        "LRH | (GRH) | BTH | (extended transport headers) | Payload | ICRC "
        "| VCRC")
    po["flow_control"] = (
        "Absolute (cumulative) credit-based, per Virtual Lane; receiver "
        "advertises credits in Flow Control Packets; VL15 (management) is "
        "not flow controlled.")
    po["service_types"] = list(_SERVICE_TYPES)
    po["operations"] = [
        "SEND / RECEIVE (channel semantics)",
        "RDMA WRITE / RDMA READ (memory semantics)",
        "Atomic (Compare-and-Swap, Fetch-and-Add)",
    ]
    d["functional_requirements"] = [
        {"id": "FR-CA-01", "text": "End nodes attach as Channel Adapters: a "
         "Host Channel Adapter (HCA) in a processor node implementing the "
         "verbs interface, and a Target Channel Adapter (TCA) in an I/O "
         "node."},
        {"id": "FR-FABRIC-02", "text": "The fabric is built from switches "
         "(forward within a subnet on the LID) and routers (forward between "
         "subnets on the GID)."},
        {"id": "FR-SM-03", "text": "Each subnet is managed by a Subnet "
         "Manager that assigns 16-bit Local Identifiers (LIDs) and programs "
         "switch forwarding tables; SMPs ride QP0 / VL15."},
        {"id": "FR-LRH-04", "text": "Every packet carries an 8-byte Local "
         "Route Header (LRH) with SLID, DLID, a 4-bit Service Level (SL), "
         "and a 4-bit Virtual Lane (VL)."},
        {"id": "FR-VL-05", "text": "Each link supports data Virtual Lanes "
         "VL0..VL14 plus management VL15, with an SL-to-VL mapping table and "
         "a VL Arbitration Table (high/low priority + limit-of-high)."},
        {"id": "FR-FC-06", "text": "The Link Layer applies absolute "
         "credit-based flow control per Virtual Lane; VL15 is not flow "
         "controlled."},
        {"id": "FR-GRH-07", "text": "Inter-subnet packets carry a 40-byte "
         "Global Route Header (GRH) with 128-bit Source/Destination GIDs "
         "(64-bit subnet prefix + 64-bit GUID)."},
        {"id": "FR-QP-08", "text": "The Transport Layer delivers messages "
         "through Queue Pairs (a Send Queue + a Receive Queue); completions "
         "are posted to a Completion Queue; each QP has a 24-bit QPN (QP0 = "
         "subnet management, QP1 = general management)."},
        {"id": "FR-VERBS-09", "text": "A consumer interacts with an HCA "
         "through the verbs interface: create QPs/CQs, register Memory "
         "Regions, post Work Requests, reap completions."},
        {"id": "FR-SVC-10", "text": "Four transport service types are "
         "selectable per QP: Reliable Connected (RC), Unreliable Connected "
         "(UC), Unreliable Datagram (UD), and Reliable Datagram (RD)."},
        {"id": "FR-OPS-11", "text": "Operations include SEND/RECEIVE "
         "(channel semantics) and RDMA WRITE / RDMA READ (memory semantics) "
         "plus Atomics (Compare-and-Swap, Fetch-and-Add)."},
        {"id": "FR-BTH-12", "text": "IBA transport packets carry a 12-byte "
         "Base Transport Header (BTH) with OpCode, 24-bit destination QPN, "
         "24-bit Packet Sequence Number (PSN), and P_Key; the PSN drives "
         "reliable delivery (ACK/NAK + retransmission)."},
        {"id": "FR-PHY-13", "text": "Per-lane signaling is one of SDR 2.5 / "
         "DDR 5 / QDR 10 / FDR 14 / EDR 25 / HDR 50 / NDR 100 Gbps; widths "
         "1x/4x/12x; line code 8b/10b (<=QDR) or 64b/66b (>=FDR)."},
        {"id": "FR-MTU-14", "text": "The path MTU is one of 256/512/1024/"
         "2048/4096 bytes; a message larger than the MTU is segmented "
         "(First/Middle/Last/Only) and reassembled."},
        {"id": "FR-CRC-15", "text": "Packets are protected by a 16-bit "
         "Variant CRC (VCRC, recomputed per hop) and a 32-bit Invariant CRC "
         "(ICRC, end-to-end)."},
    ]
    d["error_response_conditions"] = [
        "VCRC error at a hop — packet discarded at the Link Layer.",
        "ICRC error at the destination — packet discarded end-to-end.",
        "PSN gap / out-of-sequence on a reliable QP — receiver returns NAK; "
        "sender retransmits from the PSN.",
        "Credit exhaustion on a VL — transmitter stalls that VL until "
        "credits are advertised.",
        "P_Key mismatch — packet rejected (partition violation).",
        "Resource error (RNR — Receiver Not Ready) on RC — RNR NAK with a "
        "retry timer.",
    ]
    d["compliance_requirements"] = [
        "Layered Physical/Link/Network/Transport stack with the LRH on "
        "every packet and the GRH for inter-subnet packets.",
        "Channel-Adapter end-node model (HCA + TCA) and switch/router "
        "fabric managed by a Subnet Manager assigning 16-bit LIDs.",
        "Virtual Lanes (VL0..VL14 data + VL15 management) with SL-to-VL "
        "mapping, VL arbitration, and absolute credit-based per-VL flow "
        "control.",
        "Queue Pairs (Send + Receive), Completion Queues, and the verbs "
        "interface; service types RC/UC/UD/RD.",
        "SEND/RECEIVE and RDMA READ/WRITE + Atomics; BTH with a 24-bit PSN "
        "for reliable delivery.",
        "A per-lane signaling rate from {SDR,DDR,QDR,FDR,EDR,HDR,NDR}, a "
        "width from {1x,4x,12x}, and the matching 8b/10b or 64b/66b code.",
        "A path MTU from {256,512,1024,2048,4096} bytes.",
        "16-bit VCRC (per hop) + 32-bit ICRC (end-to-end).",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L3 — command/packet protocol.
# ----------------------------------------------------------------------
def _l3(gd: Path) -> None:
    p = gd / "L3_CMD_PROTOCOL.json"
    if not p.is_file():
        return
    d = _read(p)
    d["protocol_type"] = (
        "Layered, packet-based switched-fabric transport. A consumer posts "
        "Work Requests onto a Queue Pair through the verbs interface; the "
        "HCA segments the message into packets, each framed by a Local Route "
        "Header (LRH: SLID/DLID/SL/VL), optionally a Global Route Header "
        "(GRH) for inter-subnet routing, and a Base Transport Header (BTH: "
        "OpCode/QPN/PSN/P_Key); switches forward on the DLID and routers on "
        "the DGID; the destination HCA reassembles, validates ICRC/VCRC, and "
        "(for reliable service) acknowledges by PSN.")
    d["channels"] = [
        {"name": "Serial differential lanes",
         "direction": "full-duplex (TX pair + RX pair per lane)",
         "description": "1x / 4x / 12x lanes carrying 8b/10b or 64b/66b "
         "encoded symbols at 2.5-100 Gbps/lane (SDR..NDR)."},
        {"name": "Virtual Lanes (VL0..VL14 data, VL15 management)",
         "direction": "logical, multiplexed over the physical link",
         "description": "Independent buffered lanes for QoS / deadlock "
         "avoidance; SL maps to VL; VL arbitration shares link bandwidth; "
         "VL15 carries SMPs and is not flow controlled."},
    ]
    d["layer_stack"] = [
        {"layer": "Transport Layer",
         "purpose": "Queue Pairs, Completion Queues, verbs, RC/UC/UD/RD, "
                    "BTH, PSN, end-to-end reliability."},
        {"layer": "Network Layer",
         "purpose": "Global Route Header (128-bit GIDs); inter-subnet "
                    "routing by routers."},
        {"layer": "Link Layer",
         "purpose": "Local Route Header (LID/SL/VL), Virtual Lanes, "
                    "credit-based flow control, VCRC; intra-subnet "
                    "forwarding by switches."},
        {"layer": "Physical Layer",
         "purpose": "Serial lanes, 8b/10b or 64b/66b, link training/"
                    "states."},
    ]
    d["packet_format"] = {
        "order": ["LRH", "GRH (optional)", "BTH",
                  "extended transport headers (optional)", "Payload",
                  "ICRC", "VCRC"],
        "LRH": {"bytes": 8, "present": "always",
                "fields": ["VL (4b)", "LVer", "SL (4b)", "LNH",
                           "DLID (16b)", "SLID (16b)", "PktLen"]},
        "GRH": {"bytes": 40, "present": "inter-subnet only (IPv6-style)",
                "fields": ["IPVer", "TClass", "FlowLabel", "PayLen",
                           "NxtHdr", "HopLmt", "SGID (128b)", "DGID (128b)"]},
        "BTH": {"bytes": 12, "present": "IBA transport packets",
                "fields": ["OpCode (8b)", "SE", "MigReq", "PadCnt", "TVer",
                           "P_Key (16b)", "Destination QP (24b)",
                           "AckReq", "PSN (24b)"]},
        "ICRC": {"bits": 32, "scope": "invariant fields, end-to-end"},
        "VCRC": {"bits": 16, "scope": "all fields, per hop"},
    }
    d["addressing"] = {
        "LID": "16-bit Local Identifier; assigned by the Subnet Manager; "
               "switches forward within a subnet on the DLID.",
        "GID": "128-bit Global Identifier (64-bit subnet prefix + 64-bit "
               "GUID); routers forward between subnets on the DGID.",
        "QPN": "24-bit Queue Pair Number identifies the destination QP "
               "(QP0 = subnet management, QP1 = general management).",
        "PSN": "24-bit Packet Sequence Number orders packets within a "
               "message and drives reliable-delivery ACK/NAK / "
               "retransmission.",
        "P_Key": "16-bit Partition Key enforces fabric partitioning.",
    }
    d["service_types"] = [
        {"type": "RC", "name": "Reliable Connected",
         "delivery": "connection between two QPs; acknowledged, in-order, "
                     "reliable."},
        {"type": "UC", "name": "Unreliable Connected",
         "delivery": "connection without acknowledgement."},
        {"type": "UD", "name": "Unreliable Datagram",
         "delivery": "connectionless; single-MTU messages; multicast / "
                     "management."},
        {"type": "RD", "name": "Reliable Datagram",
         "delivery": "reliable without a per-peer connection (End-to-End "
                     "Context)."},
    ]
    d["operations"] = [
        {"op": "SEND / RECEIVE", "semantics": "channel (receiver consumes a "
         "posted Receive WQE)."},
        {"op": "RDMA WRITE", "semantics": "memory (write remote memory; "
         "remote CPU not involved)."},
        {"op": "RDMA READ", "semantics": "memory (read remote memory; "
         "remote CPU not involved)."},
        {"op": "Atomic", "semantics": "Compare-and-Swap / Fetch-and-Add on "
         "remote memory."},
    ]
    d["valid_ready_handshake_rules"] = [
        "Consumer posts Work Queue Elements (WQEs) to the Send/Receive "
        "Queue of a QP via verbs.",
        "Absolute credit-based per-VL flow control gates transmission on "
        "each Virtual Lane.",
        "Reliable service (RC/RD) acknowledges by PSN with ACK/NAK and "
        "retransmits on loss or RNR.",
        "Switches forward on DLID; routers forward on DGID; the SM "
        "establishes the paths.",
        "Completions are posted as CQEs to the Completion Queue.",
    ]
    d["byte_oriented"] = False
    d["packet_oriented"] = True
    d["frame_format"] = {
        "framing": "Packets are delimited at the Physical Layer (8b/10b "
        "control symbols / 64b/66b block framing); the LRH PktLen gives the "
        "length; VCRC terminates each packet.",
        "segmentation": "Messages larger than the MTU are segmented into "
        "First/Middle/Last/Only packets and sequenced by PSN.",
        "note": "VL15 management packets (SMPs) are framed identically but "
        "ride the non-flow-controlled management VL.",
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L4 — register/attribute map (IB management attributes, not a MMIO map).
# ----------------------------------------------------------------------
def _l4(gd: Path) -> None:
    p = gd / "L4_REGMAP.json"
    if not p.is_file():
        return
    d = _read(p)
    d["register_map_present"] = True
    d["notes"] = (
        "InfiniBand exposes management state as Subnet-Management and "
        "General-Services attributes accessed via Management Datagrams "
        "(MADs) on QP0 (SMPs over VL15) and QP1 (GMPs), rather than as a "
        "host MMIO register map. These attributes (PortInfo, NodeInfo, "
        "SL-to-VL mapping table, VL Arbitration table, P_Key table, "
        "forwarding tables) are read/written by the Subnet Manager and "
        "Subnet Management Agents.")
    d["management_interfaces"] = {
        "QP0": "Subnet Management — Subnet Management Packets (SMPs) over "
               "VL15; used by the SM and SMAs.",
        "QP1": "General Services — General Management Packets (GMPs): "
               "performance, communication management, device management, "
               "Subnet Administration (SA).",
        "MAD_size_bytes": 256,
    }
    d["register_groups"] = [
        {"group": "Subnet-Management Attributes (via SMP / QP0)", "fields": [
            "NodeInfo / NodeDescription",
            "PortInfo (LID, LMC, link width/speed, VL caps, MTU, SL-to-VL)",
            "SwitchInfo and Linear/Random Forwarding Tables",
            "SL-to-VL Mapping Table",
            "VL Arbitration Table (high/low priority + Limit-of-High)",
            "P_Key (Partition) Table",
            "GUIDInfo"]},
        {"group": "General-Services Attributes (via GMP / QP1)", "fields": [
            "Performance counters (PortCounters: errors, data, packets)",
            "Communication Management (connection request/reply/ready)",
            "Subnet Administration (SA) path-record / service-record "
            "queries",
            "Device Management"]},
        {"group": "Per-QP Context (verbs-managed)", "fields": [
            "Queue Pair Number (24-bit) and state (RESET/INIT/RTR/RTS/...)",
            "Service type (RC/UC/UD/RD)",
            "Send/Receive Queue depths",
            "Send/Receive PSN",
            "Path MTU, primary/alternate path (LID/GID, SL)",
            "Associated Completion Queue(s)"]},
    ]
    d["well_known_qps"] = {
        "QP0": "Subnet Management Interface (SMI) — SMPs on VL15.",
        "QP1": "General Service Interface (GSI) — GMPs.",
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L5 — analog/physical signaling.
# ----------------------------------------------------------------------
def _l5(gd: Path) -> None:
    p = gd / "L5_ADI_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["analog_digital_interface_present"] = True
    d["signaling_summary"] = (
        "Serial, differential, point-to-point lanes with an embedded clock "
        "recovered from the line code. Per-lane signaling rates: SDR 2.5, "
        "DDR 5, QDR 10 (8b/10b); FDR 14, EDR 25 (64b/66b); HDR 50, NDR 100 "
        "Gbps (PAM4). Links aggregate 1, 4, or 12 lanes (1x/4x/12x). For "
        "example a 4x QDR link is 40 Gbps signaling (32 Gbps data after "
        "8b/10b).")
    d["modulation"] = ("NRZ for SDR/DDR/QDR/FDR/EDR; PAM4 for HDR/NDR.")
    d["clocking"] = ("Embedded clock recovered by the receiver from the "
                     "8b/10b or 64b/66b encoded serial stream (clock-data "
                     "recovery).")
    d["line_speeds"] = list(_LINK_SPEEDS)
    d["link_widths"] = list(_LINK_WIDTHS)
    d["line_coding"] = {
        "8b/10b": "SDR / DDR / QDR (25% overhead)",
        "64b/66b": "FDR / EDR / HDR (~3% overhead)",
        "PAM4": "HDR / NDR (4-level modulation, doubles bits per symbol)",
    }
    d["transmitter_specs_canonical"] = {
        "signaling": "differential serial",
        "per_lane_Gbps": {s["name"]: s["per_lane_Gbps"]
                          for s in _LINK_SPEEDS},
        "widths": list(_LINK_WIDTHS),
        "modulation": "NRZ (<=EDR) / PAM4 (HDR, NDR)",
        "line_code": "8b/10b (<=QDR) / 64b/66b (>=FDR)",
        "embedded_clock": True,
    }
    d["receiver_specs_canonical"] = {
        "clock_recovery": "CDR from the encoded stream",
        "lane_deskew": "Multi-lane (4x/12x) de-skew at the Physical Layer",
        "link_training": "Down -> Polling -> Configuration -> LinkUp",
    }
    d["encoding_role_in_analog"] = (
        "8b/10b (SDR/DDR/QDR) and 64b/66b (FDR and above) provide DC balance "
        "and transition density for clock recovery; HDR/NDR use PAM4 "
        "modulation to double the per-symbol data rate. Data integrity is "
        "handled digitally by the 16-bit VCRC (per hop) and 32-bit ICRC "
        "(end-to-end).")
    _write(p, d)


# ----------------------------------------------------------------------
# L6 — control logic / FSMs (link state + QP state machine).
# ----------------------------------------------------------------------
def _l6(gd: Path) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["fsm_states_physical_link"] = [
        {"name": "Down", "description": "Link not established; no symbols."},
        {"name": "Polling", "description": "Port attempts to discover a "
         "peer; exchanges training sequences."},
        {"name": "Configuration", "description": "Negotiate link width / "
         "speed; lane de-skew."},
        {"name": "LinkUp", "description": "Physical link operational; "
         "symbols flow."},
    ]
    d["fsm_states_qp"] = [
        {"name": "RESET", "description": "QP created; no traffic."},
        {"name": "INIT", "description": "QP initialized; receive WQEs may be "
         "posted; cannot send/receive packets yet."},
        {"name": "RTR", "description": "Ready to Receive — remote QPN, PSN, "
         "and path configured; can receive packets."},
        {"name": "RTS", "description": "Ready to Send — can transmit packets "
         "and process send WQEs."},
        {"name": "SQD", "description": "Send Queue Drained (for path "
         "migration)."},
        {"name": "SQErr", "description": "Send Queue Error (UC/UD)."},
        {"name": "Error", "description": "QP error — flushes WQEs with error "
         "completions; requires reset to recover."},
    ]
    d["fsm_states_reliable_delivery"] = [
        {"name": "TX_SEQUENCE", "description": "Transmit packets stamped with "
         "increasing PSN; hold unacknowledged packets."},
        {"name": "WAIT_ACK", "description": "Await ACK up to a PSN; advance "
         "the unacknowledged window on ACK."},
        {"name": "RETRANSMIT", "description": "On NAK or timeout, retransmit "
         "from the failing PSN."},
        {"name": "RNR_WAIT", "description": "On Receiver-Not-Ready NAK, wait "
         "the RNR timer then retransmit."},
    ]
    d["fsm_hints"] = {
        "trigger": "Physical link trains Down -> Polling -> Configuration -> "
        "LinkUp; the QP is driven RESET -> INIT -> RTR -> RTS by verbs "
        "Modify-QP before data transfer.",
        "rule": "On a reliable QP each packet carries an increasing PSN; the "
        "receiver ACKs by PSN and NAKs gaps; the sender retransmits from the "
        "first un-ACKed PSN.",
        "abort": "Unrecoverable errors drive the QP to Error, flushing WQEs "
        "with error completions.",
    }
    d["flow_control_rule"] = (
        "Absolute credit-based flow control per Virtual Lane: a transmitter "
        "may send on a VL only while it holds credits for that VL; the "
        "receiver advertises an absolute (cumulative) credit count in Flow "
        "Control Packets, so a lost update self-corrects. VL15 is not flow "
        "controlled.")
    d["vl_arbitration_rule"] = (
        "Data VLs share the physical link via a VL Arbitration Table with a "
        "high-priority list, a low-priority list, and a "
        "Limit-of-High-Priority counter (weighted round-robin). The Service "
        "Level selects a VL through the SL-to-VL mapping table.")
    d["anti_deadlock_rule"] = (
        "Independent per-VL buffering plus credit-based flow control "
        "prevents head-of-line blocking and provides deadlock avoidance; "
        "the SM can assign SLs/VLs to break routing-dependency cycles.")
    d["exit_from_reset_or_poweron"] = (
        "On power-up the port trains the physical link (Down->Polling->"
        "Configuration->LinkUp); the Subnet Manager then assigns a LID and "
        "configures PortInfo (VLs, MTU, SL-to-VL). QPs are brought up by "
        "verbs (RESET->INIT->RTR->RTS).")
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
        {"name": "Performance counters (PortCounters)", "purpose": "Per-port "
         "error and traffic counters (symbol errors, link recovery, "
         "received/transmitted data + packets) read via GMP on QP1."},
        {"name": "Subnet Management attributes (PortInfo/NodeInfo)",
         "purpose": "Read/write link width/speed, LID, VL caps, MTU, "
         "SL-to-VL, and forwarding tables via SMP on QP0."},
        {"name": "VCRC / ICRC", "purpose": "Per-hop and end-to-end CRC "
         "detect packet corruption."},
        {"name": "PSN sequencing", "purpose": "ACK/NAK by PSN exposes lost / "
         "out-of-sequence packets on reliable QPs."},
        {"name": "Subnet Administration (SA)", "purpose": "Query path "
         "records, service records, and topology for diagnostics."},
    ]
    d["error_detection_mechanisms"] = [
        "16-bit Variant CRC (VCRC) checked at every hop.",
        "32-bit Invariant CRC (ICRC) checked end-to-end.",
        "PSN gap detection -> NAK + retransmission on reliable QPs.",
        "P_Key mismatch -> partition violation.",
        "Symbol / link-recovery error counters at the Physical Layer.",
        "RNR NAK when the receiver has no posted Receive WQE.",
    ]
    d["interrupt_or_event_sources"] = [
        {"event": "Completion", "trigger": "A WQE completes -> CQE posted to "
         "the CQ; optional CQ event/interrupt (solicited)."},
        {"event": "Async error", "trigger": "QP/CQ error, local protection "
         "error, path migration."},
        {"event": "Link state change", "trigger": "Physical link up/down; SM "
         "trap."},
    ]
    d["notes"] = (
        "InfiniBand's observability is in-band through Management Datagrams "
        "(SMPs on QP0, GMPs on QP1): PortCounters, PortInfo/NodeInfo, and "
        "Subnet Administration queries, complemented by the VCRC/ICRC and "
        "PSN ACK/NAK telemetry. Chip-level JTAG/scan/BIST remain "
        "implementation concerns.")
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
        "LID_WIDTH_BITS": 16,
        "GID_WIDTH_BITS": 128,
        "GUID_WIDTH_BITS": 64,
        "SUBNET_PREFIX_WIDTH_BITS": 64,
        "QPN_WIDTH_BITS": 24,
        "PSN_WIDTH_BITS": 24,
        "P_KEY_WIDTH_BITS": 16,
        "SL_WIDTH_BITS": 4,
        "VL_WIDTH_BITS": 4,
        "DATA_VLS_MAX": 15,
        "MANAGEMENT_VL": 15,
        "LRH_BYTES": 8,
        "GRH_BYTES": 40,
        "BTH_BYTES": 12,
        "VCRC_WIDTH_BITS": 16,
        "ICRC_WIDTH_BITS": 32,
        "MAD_BYTES": 256,
        "MTU_BYTES_OPTIONS": list(_MTU_BYTES),
        "LINK_WIDTHS": list(_LINK_WIDTHS),
        "PER_LANE_GBPS": {s["name"]: s["per_lane_Gbps"]
                          for s in _LINK_SPEEDS},
        "WELL_KNOWN_QP_SUBNET_MGMT": 0,
        "WELL_KNOWN_QP_GENERAL_MGMT": 1,
    })
    d["service_type_constants"] = {
        "RC": "Reliable Connected", "UC": "Unreliable Connected",
        "UD": "Unreliable Datagram", "RD": "Reliable Datagram",
    }
    d["crc_constants"] = {
        "VCRC": {"width_bits": 16, "scope": "per hop, all fields"},
        "ICRC": {"width_bits": 32, "scope": "end-to-end, invariant fields"},
    }
    kc = _ensure_dict(d, "key_constants_for_RTL_authoring")
    kc.update({
        "is_serial": True,
        "is_differential": True,
        "embedded_clock": True,
        "line_code": "8b/10b (<=QDR) / 64b/66b (>=FDR)",
        "modulation": "NRZ (<=EDR) / PAM4 (HDR,NDR)",
        "lid_width_bits": 16,
        "gid_width_bits": 128,
        "qpn_width_bits": 24,
        "psn_width_bits": 24,
        "sl_width_bits": 4,
        "vl_width_bits": 4,
        "data_vls_max": 15,
        "management_vl": 15,
        "credit_based_flow_control": True,
        "flow_control_absolute": True,
        "service_types": list(_SERVICE_TYPES),
        "mtu_bytes_options": list(_MTU_BYTES),
        "link_widths": list(_LINK_WIDTHS),
        "switched_fabric": True,
        "rdma_supported": True,
    })
    d["default_signal_values_when_idle"] = {
        "physical_idle": "Idle / training symbols when no packet; link kept "
                         "in LinkUp.",
        "vl15_management": "Always available (not flow controlled) for SMPs.",
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
    d["physical_waveform"] = {
        "signaling": "differential serial; NRZ (<=EDR) / PAM4 (HDR,NDR).",
        "line_code": "8b/10b (<=QDR) / 64b/66b (>=FDR).",
        "clocking": "embedded clock; receiver CDR recovers the clock.",
        "per_lane_Gbps": {s["name"]: s["per_lane_Gbps"]
                          for s in _LINK_SPEEDS},
        "widths": list(_LINK_WIDTHS),
    }
    d["packet_waveform"] = {
        "order": "LRH | (GRH) | BTH | payload | ICRC | VCRC",
        "segmentation": "Message > MTU split into First/Middle/Last/Only "
                        "packets sequenced by PSN.",
        "vl_multiplexing": "Packets of different VLs interleave on the link "
                           "per VL arbitration.",
    }
    d["flow_control_waveform"] = {
        "type": "absolute credit-based, per VL",
        "rule": "Flow Control Packets advertise cumulative credits per VL; "
                "the transmitter sends on a VL only with available credits.",
        "vl15": "management VL not flow controlled.",
    }
    d["link_state_transition_trigger_waveform"] = {
        "Down_to_Polling": "Port begins peer discovery / training.",
        "Polling_to_Configuration": "Peer detected; negotiate width/speed.",
        "Configuration_to_LinkUp": "Lanes de-skewed; link operational.",
        "qp_RESET_to_INIT_to_RTR_to_RTS": "verbs Modify-QP brings the QP up "
                                          "before data transfer.",
    }
    d["reliable_delivery_waveform"] = {
        "psn": "Each reliable packet carries an increasing 24-bit PSN.",
        "ack_nak": "Receiver returns ACK up to a PSN, or NAK (PSN-seq / RNR "
                   "/ remote-access) carried in the AETH.",
        "retransmit": "Sender retransmits from the first un-ACKed PSN.",
    }
    d["general_timing_rule"] = (
        "Bit timing is set by the per-lane signaling rate (e.g. 400 ps UI at "
        "2.5 Gbps SDR, 100 ps at 10 Gbps QDR, 40 ps at 25 Gbps EDR). The "
        "Link Layer (VL arbitration, credits, VCRC) and Transport Layer (PSN "
        "ACK/NAK) run at the internal device clock, decoupled from the "
        "per-lane UI.")
    d["data_rate_waveform"] = {
        "per_lane_Gbps": {s["name"]: s["per_lane_Gbps"]
                          for s in _LINK_SPEEDS},
        "widths": list(_LINK_WIDTHS),
        "example_4x_QDR_Gbps_signaling": 40,
        "example_4x_QDR_Gbps_data_after_8b10b": 32,
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
        "Switched-fabric I/O interconnect: a Channel Adapter (HCA in a host, "
        "TCA in an I/O node) attaching an end node to a fabric of switches "
        "and routers managed by a Subnet Manager, carrying RDMA and "
        "SEND/RECEIVE traffic over Queue Pairs with a layered LRH/GRH/BTH "
        "packet stack at 2.5-100 Gbps/lane (1x/4x/12x).")
    d["topology_description"] = (
        "End nodes (Channel Adapters) connect to switches; switches forward "
        "within a subnet by LID; routers connect subnets and forward by GID. "
        "A Subnet Manager owns each subnet and assigns LIDs.")
    io = _ensure_dict(d, "integration_overview")
    io.update({
        "spec": "InfiniBand Architecture (IBTA)",
        "end_node": "Channel Adapter (HCA / TCA)",
        "fabric": "switches (intra-subnet, LID) + routers (inter-subnet, "
                  "GID)",
        "managed_by": "Subnet Manager (assigns 16-bit LIDs)",
        "per_lane_Gbps": {s["name"]: s["per_lane_Gbps"]
                          for s in _LINK_SPEEDS},
        "link_widths": list(_LINK_WIDTHS),
        "mtu_bytes": list(_MTU_BYTES),
        "service_types": list(_SERVICE_TYPES),
        "transport_object": "Queue Pair (Send Queue + Receive Queue)",
        "completion": "Completion Queue (CQE)",
        "consumer_interface": "verbs",
        "headers": {"LRH": 8, "GRH": 40, "BTH": 12},
        "crc": {"VCRC_bits": 16, "ICRC_bits": 32},
        "lid_width_bits": 16, "gid_width_bits": 128,
        "qpn_width_bits": 24, "psn_width_bits": 24,
        "well_known_qps": {"QP0": "subnet management", "QP1": "general "
                           "management"},
        "flow_control": "absolute credit-based per VL",
    })
    d["interface_categories"] = [
        "Upper Layer (verbs / consumer) — QP/CQ creation, memory "
        "registration, Work Requests, completions.",
        "Transport Layer — Queue Pairs, RC/UC/UD/RD, BTH, PSN reliability.",
        "Network Layer — GRH (128-bit GIDs), inter-subnet routing.",
        "Link Layer — LRH (LID/SL/VL), Virtual Lanes, credit-based flow "
        "control.",
        "Physical Layer — serial lanes, 8b/10b or 64b/66b, link training.",
        "Management — SMPs (QP0/VL15) and GMPs (QP1).",
    ]
    d["interconnect_topologies_supported"] = [
        "Single subnet: end nodes + switches managed by one SM.",
        "Multi-subnet: subnets joined by routers (GID routing).",
        "Fat-tree / Clos / torus fabrics built from switches.",
        "Wide links: 1x / 4x / 12x lane aggregation.",
    ]
    d["soc_dependent_items"] = [
        "Channel-Adapter role (HCA vs TCA) and the verbs / I/O-Controller "
        "interface.",
        "Link width (1x/4x/12x) and target speed (SDR..NDR) and the "
        "matching line code.",
        "Number of supported data Virtual Lanes (1/2/4/8/15) and buffer "
        "sizing.",
        "Supported service types (RC/UC/UD/RD) and path MTU.",
        "Subnet Management Agent and the management-QP (QP0/QP1) handling.",
        "Power/clock domains and CDR/SerDes PHY implementation.",
    ]
    d["device_classes_examples"] = [
        "Host Channel Adapter (HCA) on a compute server",
        "Target Channel Adapter (TCA) on a storage controller",
        "InfiniBand switch (intra-subnet, LID forwarding)",
        "InfiniBand router (inter-subnet, GID routing)",
        "Subnet Manager appliance / embedded SM",
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
        "partial - the IBTA specification defines compliance behaviors "
        "(electrical, link, transport, management) verified by IBTA "
        "Plugfest / Integrators' List interoperability testing; the "
        "architecture text itself is not a single testbench.")
    d["derived_compliance_test_categories"] = [
        "Physical link training: Down -> Polling -> Configuration -> LinkUp "
        "at each supported width/speed (SDR..NDR, 1x/4x/12x).",
        "Line-code correctness: 8b/10b (<=QDR) / 64b/66b (>=FDR); PAM4 "
        "(HDR/NDR).",
        "LRH framing: SLID/DLID/SL/VL fields and switch forwarding by DLID.",
        "Virtual Lanes: VL0..VL14 data + VL15 management; SL-to-VL mapping; "
        "VL arbitration (high/low priority + Limit-of-High).",
        "Credit-based flow control: per-VL absolute credits; VL15 not flow "
        "controlled; lost-credit self-correction.",
        "GRH / inter-subnet routing: 128-bit GIDs; router forwarding by "
        "DGID.",
        "Queue Pairs: RESET->INIT->RTR->RTS bring-up via verbs; CQ "
        "completions.",
        "Service types: RC / UC / UD / RD behavior.",
        "Operations: SEND/RECEIVE and RDMA WRITE / RDMA READ + Atomics "
        "(CmpSwap, FetchAdd).",
        "BTH + PSN: reliable delivery ACK/NAK, retransmission, RNR.",
        "MTU & segmentation: 256/512/1024/2048/4096 B; First/Middle/Last/"
        "Only.",
        "CRC: VCRC (per hop) and ICRC (end-to-end) error detection.",
        "Subnet Manager: LID assignment, forwarding-table programming, SMP "
        "on QP0/VL15.",
        "Management: GMP on QP1 (PortCounters, Communication Management, "
        "Subnet Administration).",
        "Partitioning: P_Key enforcement (full / limited membership).",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L11 — OTP / factory-burned capability fields.
# ----------------------------------------------------------------------
def _l11(gd: Path) -> None:
    p = gd / "L11_OTP_CONTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    d["otp_present"] = False
    d["otp_equivalent_factory_burned_fields"] = [
        {"field": "Node GUID", "width_bits": 64,
         "location": "NodeInfo (SM-readable)",
         "note": "64-bit Globally Unique Identifier; hardware-assigned, used "
                 "to form the GID with the subnet prefix."},
        {"field": "Port GUID(s)", "width_bits": 64,
         "location": "GUIDInfo / PortInfo",
         "note": "Per-port GUID(s); hardware-assigned."},
        {"field": "Channel-Adapter capabilities",
         "width_bits": "implementation-defined",
         "location": "NodeInfo / PortInfo",
         "note": "Supported link width/speed, VL count, MTU, service "
                 "types — discoverable by the SM."},
    ]
    d["notes"] = (
        "InfiniBand does not define OTP as a protocol concept. The "
        "hardware-fixed, interoperability-relevant facts are the 64-bit "
        "node/port GUIDs and the Channel-Adapter capability set, which are "
        "discoverable by the Subnet Manager via NodeInfo/PortInfo/GUIDInfo "
        "attributes. The 16-bit LID, by contrast, is assigned at runtime by "
        "the SM (not hardware-fixed). An implementation may back GUIDs with "
        "fuses, but the spec only requires they be discoverable.")
    _write(p, d)


# ----------------------------------------------------------------------
# L12 — behavioral sequences.
# ----------------------------------------------------------------------
def _l12(gd: Path) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["link_bring_up_sequence"] = [
        "1. Physical link trains: Down -> Polling -> Configuration -> "
        "LinkUp (negotiate width/speed, de-skew lanes).",
        "2. Subnet Manager sweeps, reads NodeInfo/PortInfo, assigns a 16-bit "
        "LID, configures VLs / MTU / SL-to-VL, programs forwarding tables.",
        "3. Management (SMPs on QP0/VL15) establishes the managed subnet.",
        "4. Consumers create QPs/CQs and register Memory Regions via verbs.",
        "5. QP brought up RESET -> INIT -> RTR -> RTS (Modify-QP supplies "
        "remote QPN, PSN, path).",
        "6. Data transfer begins on the configured service type.",
    ]
    d["send_receive_sequence"] = [
        "1. Consumer posts a Receive WQE on the destination QP and a Send "
        "WQE on the source QP (verbs).",
        "2. Source HCA segments the message by MTU, stamps each packet with "
        "LRH/(GRH)/BTH and an increasing PSN.",
        "3. Switches forward by DLID; routers by DGID; VL arbitration "
        "interleaves VLs subject to credits.",
        "4. Destination HCA checks VCRC per hop and ICRC end-to-end, "
        "reassembles, and consumes the posted Receive WQE.",
        "5. For reliable service the receiver ACKs by PSN; both sides post "
        "CQEs to their Completion Queues.",
    ]
    d["rdma_sequence"] = [
        "1. Remote memory is registered (Memory Region + R_Key) and the "
        "R_Key/address shared.",
        "2. RDMA WRITE: source posts a Send WQE with remote address + R_Key; "
        "the HCA writes remote memory directly (remote CPU not involved).",
        "3. RDMA READ: source posts a READ WQE; the responder returns the "
        "data; the requester's CQ signals completion.",
        "4. Reliable service sequences/ACKs the operation by PSN.",
    ]
    d["reliable_retransmit_sequence"] = [
        "1. Each reliable packet carries an increasing PSN.",
        "2. Receiver ACKs up to a PSN; a gap triggers a PSN-Sequence NAK; "
        "no Receive WQE triggers an RNR NAK.",
        "3. Sender retransmits from the first un-ACKed PSN (after the RNR "
        "timer for RNR).",
        "4. Exhausted retries drive the QP to Error.",
    ]
    d["flow_control_sequence"] = [
        "1. Receiver advertises absolute (cumulative) credits per VL in Flow "
        "Control Packets.",
        "2. Transmitter sends on a VL only while credits remain.",
        "3. A lost Flow Control Packet self-corrects on the next absolute "
        "update.",
        "4. VL15 (management) bypasses flow control.",
    ]
    d["reset_sequence"] = [
        "1. Link reset / power-up -> physical link retrains "
        "(Down->...->LinkUp).",
        "2. SM re-assigns the LID and reconfigures PortInfo.",
        "3. QPs are re-driven RESET->INIT->RTR->RTS via verbs.",
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
        {"name": "Per-lane data eye", "purpose": "Verify the differential "
         "serial eye at the target rate (SDR 2.5 .. NDR 100 Gbps/lane), "
         "NRZ or PAM4."},
        {"name": "Link training", "purpose": "Confirm Down->Polling->"
         "Configuration->LinkUp at each width/speed and lane de-skew."},
        {"name": "BER / CRC", "purpose": "Measure bit-error rate; confirm "
         "VCRC (per hop) and ICRC (end-to-end) detect injected errors."},
        {"name": "Credit-based flow control", "purpose": "Validate per-VL "
         "absolute credit accounting and self-correction."},
        {"name": "VL arbitration", "purpose": "Confirm SL-to-VL mapping and "
         "weighted round-robin (high/low priority + Limit-of-High)."},
        {"name": "Reliable delivery", "purpose": "Inject loss; confirm "
         "PSN-based ACK/NAK and retransmission."},
        {"name": "RDMA latency / bandwidth", "purpose": "Characterize "
         "end-to-end RDMA READ/WRITE latency and throughput at each "
         "width/speed."},
    ]
    d["notes"] = (
        "InfiniBand characterization spans the SerDes lanes (eye, CDR, "
        "de-skew), Link-Layer credits/VL arbitration/VCRC, and "
        "Transport-Layer PSN reliability. Interoperability is established by "
        "IBTA Plugfest / Integrators' List testing.")
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
    f["spec_version"] = ("InfiniBand Architecture Specification (IBTA), "
                         "Volume 1 Core Architecture + Volume 2 Physical, "
                         "Release 1.x")
    f["previous_versions"] = [
        "InfiniBand 1.0 — initial IBTA release establishing the layered "
        "fabric (Channel Adapters, switches/routers, Subnet Manager, "
        "LRH/GRH/BTH, Queue Pairs, verbs, SDR).",
    ]
    f["key_changes"] = [
        {"version": "Link-speed generations", "summary": "Successive IBTA "
         "releases added DDR (5), QDR (10) on 8b/10b, then FDR (14), EDR "
         "(25), HDR (50), NDR (100) Gbps/lane on 64b/66b with PAM4 for "
         "HDR/NDR — the layered architecture (CAs, switches/routers, SM, "
         "LRH/GRH/BTH, Queue Pairs, verbs, RC/UC/UD/RD) is carried forward "
         "unchanged."},
    ]
    f["backward_compat_traps"] = [
        {"trap_name": "LID_is_subnet_local",
         "rule": "The 16-bit LID is unique only within a subnet; "
                 "cross-subnet forwarding uses the 128-bit GID in the GRH.",
         "trap": "Using a LID across subnets fails — routers forward on the "
                 "GID, switches on the LID."},
        {"trap_name": "VL15_not_flow_controlled",
         "rule": "VL15 carries management (SMPs) and is never flow "
                 "controlled.",
         "trap": "Applying data-VL credit accounting to VL15 is wrong."},
        {"trap_name": "Absolute_not_incremental_credits",
         "rule": "Flow-control credits are absolute (cumulative).",
         "trap": "Treating credits as incremental breaks recovery after a "
                 "lost Flow Control Packet."},
        {"trap_name": "Service_type_capability",
         "rule": "RC/UC/UD/RD are per-QP; UD is single-MTU and "
                 "connectionless.",
         "trap": "Assuming RDMA on UD, or multi-MTU messages on UD, is "
                 "invalid."},
        {"trap_name": "Line_code_by_speed",
         "rule": "8b/10b for SDR/DDR/QDR; 64b/66b for FDR and above; PAM4 "
                 "for HDR/NDR.",
         "trap": "Assuming 8b/10b at EDR/HDR (it is 64b/66b) miscomputes the "
                 "effective data rate."},
    ]
    f["version_naming_history_note"] = (
        "InfiniBand is maintained by the InfiniBand Trade Association "
        "(IBTA). The architecture is split into Volume 1 (Core Architecture) "
        "and Volume 2 (Physical). Link-speed generations are named SDR / DDR "
        "/ QDR / FDR / EDR / HDR / NDR (2.5 / 5 / 10 / 14 / 25 / 50 / 100 "
        "Gbps per lane). Facts here are grounded in the IBTA InfiniBand "
        "Architecture Specification.")
    _write(p, d)


# ----------------------------------------------------------------------
# L15 — encoding / fact tables.
# ----------------------------------------------------------------------
def _l15(gd: Path) -> None:
    p = gd / "L15_ENCODING_TABLES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["link_speed_table"] = {
        "header_columns": ["Name", "Long name", "Per-lane (Gbps)",
                           "Line code"],
        "rows": [[s["name"], s["long"], str(s["per_lane_Gbps"]),
                  s["line_code"]] for s in _LINK_SPEEDS],
    }
    f["link_width_table"] = {
        "header_columns": ["Width", "Lanes"],
        "rows": [["1x", "1"], ["4x", "4"], ["12x", "12"]],
    }
    f["header_table"] = {
        "header_columns": ["Header", "Bytes", "Present", "Key fields"],
        "rows": [
            ["LRH (Local Route Header)", "8", "always",
             "VL, SL, DLID, SLID, LNH, PktLen"],
            ["GRH (Global Route Header)", "40", "inter-subnet",
             "SGID(128), DGID(128), TClass, FlowLabel, HopLmt"],
            ["BTH (Base Transport Header)", "12", "IBA transport",
             "OpCode, Dest QP(24), PSN(24), P_Key"],
            ["ICRC", "4", "transport", "32-bit invariant CRC"],
            ["VCRC", "2", "always", "16-bit variant CRC"],
        ],
    }
    f["service_type_table"] = {
        "header_columns": ["Code", "Name", "Connected", "Reliable"],
        "rows": [
            ["RC", "Reliable Connected", "yes", "yes"],
            ["UC", "Unreliable Connected", "yes", "no"],
            ["UD", "Unreliable Datagram", "no", "no"],
            ["RD", "Reliable Datagram", "no", "yes"],
        ],
    }
    f["virtual_lane_table"] = {
        "header_columns": ["VL", "Use"],
        "rows": [
            ["VL0..VL14", "data (1/2/4/8/15 implemented; SL-to-VL mapped)"],
            ["VL15", "management (SMPs); not flow controlled"],
        ],
    }
    f["mtu_table"] = {
        "header_columns": ["MTU (bytes)"],
        "rows": [["256"], ["512"], ["1024"], ["2048"], ["4096"]],
    }
    f["address_width_table"] = {
        "header_columns": ["Identifier", "Width (bits)", "Scope"],
        "rows": [
            ["LID (Local Identifier)", "16", "subnet"],
            ["GID (Global Identifier)", "128", "fabric (IPv6-style)"],
            ["GUID", "64", "global hardware ID"],
            ["QPN (Queue Pair Number)", "24", "node"],
            ["PSN (Packet Sequence Number)", "24", "per QP"],
            ["P_Key (Partition Key)", "16", "fabric"],
        ],
    }
    f["encoding_note"] = (
        "InfiniBand uses 8b/10b line coding for SDR/DDR/QDR and 64b/66b for "
        "FDR/EDR/HDR, with PAM4 modulation at HDR/NDR. Data integrity is "
        "provided by a 16-bit Variant CRC (per hop) and a 32-bit Invariant "
        "CRC (end-to-end), not by the line code.")
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
        "Layered stack: Physical / Link / Network / Transport / Upper "
        "(verbs).",
        "Channel-Adapter end nodes (HCA + TCA); switch/router fabric.",
        "Subnet Manager that assigns 16-bit LIDs and programs forwarding "
        "tables; SMPs on QP0 / VL15.",
        "Local Route Header (LRH) on every packet with SLID, DLID, SL, VL.",
        "Virtual Lanes VL0..VL14 (data) + VL15 (management); SL-to-VL "
        "mapping; VL arbitration.",
        "Absolute credit-based flow control per VL (VL15 excepted).",
        "Global Route Header (GRH) with 128-bit GIDs for inter-subnet "
        "routing.",
        "Queue Pairs (Send + Receive), Completion Queues, and the verbs "
        "interface.",
        "Service types RC/UC/UD/RD; SEND/RECEIVE and RDMA READ/WRITE + "
        "Atomics.",
        "Base Transport Header with OpCode, 24-bit QPN, 24-bit PSN, P_Key; "
        "PSN-driven reliable delivery.",
        "A per-lane speed from {SDR,DDR,QDR,FDR,EDR,HDR,NDR}, width "
        "{1x,4x,12x}, matching 8b/10b or 64b/66b code.",
        "Path MTU from {256,512,1024,2048,4096} bytes; 16-bit VCRC + 32-bit "
        "ICRC.",
    ]
    f["must_not_have_properties"] = [
        "Forwarding across subnets on the LID (cross-subnet uses the GID).",
        "Flow-controlling VL15 (management is exempt).",
        "Incremental (non-absolute) link-layer credits.",
        "An Ethernet MAC / 802.3 framing as the native link layer (that is "
        "Ethernet or RoCE, not native InfiniBand).",
        "Multi-MTU or connection-oriented Unreliable Datagram (UD is "
        "single-MTU, connectionless).",
    ]
    f["compliance_failure_modes"] = [
        {"mode": "Link training failure", "trigger": "Physical link cannot "
         "reach LinkUp at the negotiated width/speed."},
        {"mode": "VCRC/ICRC error storm", "trigger": "Persistent CRC errors "
         "from a marginal lane."},
        {"mode": "Credit deadlock", "trigger": "Misconfigured VL buffers / "
         "SL-to-VL causing head-of-line blocking."},
        {"mode": "PSN sequence error", "trigger": "Lost packets exhaust "
         "retransmission; QP -> Error."},
        {"mode": "Partition violation", "trigger": "P_Key mismatch between "
         "communicating ports."},
        {"mode": "LID exhaustion / misassignment", "trigger": "SM assigns "
         "duplicate/invalid LIDs."},
    ]
    f["min_link_constraint"] = (
        "A compliant link must train to LinkUp at the lowest common "
        "width/speed, be assigned a LID by the SM, support at least one data "
        "VL plus VL15, apply credit-based flow control, and bring up at "
        "least one Queue Pair through verbs.")
    f["reset_behavior_compliance"] = (
        "Reset/power-up retrains the physical link (Down->Polling->"
        "Configuration->LinkUp); the SM re-assigns the LID and reconfigures "
        "PortInfo; QPs are re-driven RESET->INIT->RTR->RTS.")
    f["infiniband_distinguishers"] = (
        "InfiniBand is identified by ALL of: an open switched-fabric "
        "channel-based serial interconnect (IBTA); Channel-Adapter end nodes "
        "(HCA/TCA) plus a switch/router fabric; a Subnet Manager assigning "
        "16-bit LIDs; the Local Route Header (LRH with SLID/DLID/SL/VL); "
        "Virtual Lanes (VL0..VL14 + VL15) with SL-to-VL mapping, VL "
        "arbitration, and absolute credit-based per-VL flow control; the "
        "Global Route Header (GRH) with 128-bit GIDs; Queue Pairs + "
        "Completion Queues + verbs; service types RC/UC/UD/RD; SEND/RECEIVE "
        "+ RDMA + Atomics; and the Base Transport Header with a 24-bit PSN. "
        "This native link/network signature (LRH/LID + VL + SM) distinguishes "
        "InfiniBand from Ethernet (MAC/802.3), Fibre Channel (N_Port/FLOGI), "
        "and RoCE (which reuses the IB transport over an Ethernet MAC + UDP "
        "and therefore lacks the LRH/LID/SM link layer).")
    _write(p, d)


# ----------------------------------------------------------------------
# L17 — channel / signal catalog (FORCE-OVERWRITE channels).
# ----------------------------------------------------------------------
def _l17(gd: Path) -> None:
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["channels"] = [
        {"name": "Serial lane (TX/RX differential pair)",
         "direction": "full-duplex per lane",
         "purpose": "Carry 8b/10b or 64b/66b encoded packets between ports.",
         "active_levels": "differential serial, 2.5-100 Gbps/lane "
         "(SDR..NDR), NRZ or PAM4",
         "idle_level": "idle/training symbols when no packet"},
        {"name": "Virtual Lane (logical)",
         "direction": "multiplexed over the physical link",
         "purpose": "Independent buffered lane (VL0..VL14 data, VL15 "
         "management) for QoS / deadlock avoidance.",
         "active_levels": "selected by SL-to-VL mapping; shared by VL "
         "arbitration",
         "idle_level": "no packet on that VL"},
        {"name": "Flow Control Packet",
         "direction": "per direction, per VL",
         "purpose": "Advertise absolute per-VL credits.",
         "active_levels": "cumulative credit count",
         "idle_level": "periodic update"},
    ]
    f["logical_signaling_levels"] = [
        {"name": "Active packet", "meaning": "LRH|(GRH)|BTH|payload|ICRC|"
         "VCRC on a data VL, subject to credits and VL arbitration."},
        {"name": "Management packet", "meaning": "SMP on VL15 (QP0) — not "
         "flow controlled."},
        {"name": "Link idle", "meaning": "Idle/training symbols; link in "
         "LinkUp."},
    ]
    f["packet_types_summary"] = [
        {"class": "Header", "members": ["LRH", "GRH", "BTH"], "count": 3},
        {"class": "Service type", "members": list(_SERVICE_TYPES),
         "count": 4},
        {"class": "Operation",
         "members": ["SEND", "RECEIVE", "RDMA WRITE", "RDMA READ", "Atomic"],
         "count": 5},
    ]
    cc = _ensure_dict(f, "channel_counts")
    cc.update({
        "link_widths_lanes": {"1x": 1, "4x": 4, "12x": 12},
        "data_vls_max": 15,
        "management_vl": 15,
        "lid_width_bits": 16,
        "gid_width_bits": 128,
        "qpn_width_bits": 24,
        "psn_width_bits": 24,
        "header_count": 3,
        "service_type_count": 4,
    })
    f["global_signals"] = [
        {"name": "VL15 (management)", "purpose": "Always-available "
         "(non-flow-controlled) channel for SMPs."},
        {"name": "Link state", "purpose": "Physical link state "
         "(Down/Polling/Configuration/LinkUp)."},
    ]
    f["dependency_graph"] = {
        "common_rule": "Packets carry an LRH (always) and a GRH only when "
        "crossing subnets; transport packets carry a BTH. Switches forward "
        "by DLID, routers by DGID. The SM must have assigned LIDs and "
        "configured VLs before data flows.",
        "data_dependency": "Transmission on a VL requires available credits; "
        "reliable delivery requires PSN-based ACK/NAK; the QP must be in RTS "
        "(send) / RTR (receive).",
    }
    f["handshake_pairs"] = [
        {"name": "Credit-flow-control", "from": "receiver", "to": "sender",
         "rule": "per-VL absolute credit advertisement gates transmission."},
        {"name": "PSN-ACK-NAK", "from": "responder", "to": "requester",
         "rule": "reliable QP acknowledges/NAKs by PSN; retransmit on loss."},
        {"name": "verbs-WQE", "from": "consumer", "to": "HCA",
         "rule": "post Work Requests to the Send/Receive Queue; reap CQEs."},
        {"name": "SM-SMP", "from": "Subnet Manager", "to": "SMA",
         "rule": "assign LID, program forwarding tables over QP0/VL15."},
    ]
    f["ordering_rules"] = {
        "bit_order_on_wire": "Serial per lane; multi-lane (4x/12x) striped "
        "and de-skewed; 8b/10b or 64b/66b coded.",
        "packet_order": "PSN orders packets within a message on a reliable "
        "QP; First/Middle/Last/Only segments reassemble in order.",
        "vl_interleave": "VL arbitration interleaves packets of different "
        "VLs on the shared link.",
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
        "Switched fabric. End nodes (Channel Adapters) connect to switches; "
        "switches forward within a subnet by LID; routers join subnets and "
        "forward by GID. Each subnet is owned by a Subnet Manager that "
        "assigns 16-bit LIDs. Common physical topologies are fat-tree / Clos "
        "and torus.")
    f["supported_topologies"] = [
        {"name": "Single subnet", "description": "Channel Adapters + "
         "switches managed by one Subnet Manager (LID forwarding)."},
        {"name": "Multi-subnet", "description": "Subnets joined by routers; "
         "GID (128-bit) inter-subnet routing."},
        {"name": "Fat-tree / Clos", "description": "Non-blocking "
         "multi-stage switch fabric for HPC."},
        {"name": "Torus / mesh", "description": "Direct switch topology for "
         "large clusters."},
    ]
    f["master_slave_role_summary"] = [
        {"role": "Host Channel Adapter (HCA)", "description": "Host end node; "
         "verbs interface; originates/terminates RDMA + SEND/RECEIVE."},
        {"role": "Target Channel Adapter (TCA)", "description": "I/O end "
         "node; device-specific I/O Controller interface."},
        {"role": "Switch", "description": "Intra-subnet forwarding by DLID."},
        {"role": "Router", "description": "Inter-subnet forwarding by DGID."},
        {"role": "Subnet Manager", "description": "Assigns LIDs; programs "
         "forwarding tables; owns the subnet."},
    ]
    f["interconnect_role"] = (
        "InfiniBand is a switched, channel-based fabric. The Link Layer "
        "moves packets hop-by-hop within a subnet (LID, per-VL credits, "
        "VCRC); the Network Layer routes between subnets (GID); the "
        "Transport Layer delivers messages end-to-end over Queue Pairs with "
        "PSN-based reliability for RC/RD.")
    f["ordering_guarantees"] = {
        "packet_sequence": "PSN orders packets within a message on a "
        "reliable QP.",
        "vl_arbitration": "VL arbitration shares the link fairly; SL-to-VL "
        "mapping isolates traffic classes.",
        "unreliable": "UC/UD give no delivery/ordering guarantee beyond a "
        "single packet/MTU.",
    }
    f["memory_vs_peripheral_regions"] = (
        "InfiniBand transports messages, not a memory map; RDMA targets a "
        "registered Memory Region addressed by virtual address + R_Key on "
        "the remote node. Fabric addressing is LID (subnet) / GID (global) / "
        "QPN (node).")
    dc = _ensure_dict(f, "device_classification")
    dc["host_channel_adapter"] = "Compute-node end point (verbs)."
    dc["target_channel_adapter"] = "I/O-node end point (I/O Controller)."
    dc["switch"] = "Intra-subnet LID forwarding."
    dc["router"] = "Inter-subnet GID routing."
    dc["subnet_manager"] = "LID assignment + forwarding-table programming."
    f["default_signal_values_evidence_tables"] = [
        "IBTA InfiniBand Architecture Specification — layered stack, "
        "Channel Adapters, switches/routers, Subnet Manager",
        "Link-speed table (SDR..NDR, 8b/10b vs 64b/66b, widths 1x/4x/12x)",
        "Packet-format figure (LRH/GRH/BTH, ICRC/VCRC)",
        "Transport service-type table (RC/UC/UD/RD)",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L19 — channel constraints.
# ----------------------------------------------------------------------
def _l19(gd: Path) -> None:
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["constraints_present"] = True
    f["electrical_channel_constraints"] = {
        "signaling": "differential serial; NRZ (<=EDR) / PAM4 (HDR,NDR)",
        "line_code": "8b/10b (<=QDR) / 64b/66b (>=FDR)",
        "per_lane_Gbps": {s["name"]: s["per_lane_Gbps"]
                          for s in _LINK_SPEEDS},
        "link_widths": list(_LINK_WIDTHS),
        "embedded_clock": True,
        "mtu_bytes": list(_MTU_BYTES),
        "vcrc_bits": 16,
        "icrc_bits": 32,
        "flow_control": "absolute credit-based per VL",
        "data_vls_max": 15,
        "management_vl": 15,
    }
    f["notes"] = (
        "InfiniBand is an interconnect architecture (IBTA); it fixes the "
        "electrical signaling (differential serial, 8b/10b or 64b/66b, "
        "SDR..NDR per-lane rates, 1x/4x/12x widths), the packet/header "
        "structure, the VL / credit model, and the MTU set. It does not "
        "impose PDK-specific SDC/floorplan constraints — SerDes "
        "characterization, package, and board routing are "
        "implementation/integrator concerns.")
    _write(p, d)


# ----------------------------------------------------------------------
# L20 — DFT / in-band test.
# ----------------------------------------------------------------------
def _l20(gd: Path) -> None:
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["dft_present"] = "partial"
    f["in_band_test_facilities"] = [
        {"name": "Subnet Management (SMP / QP0 / VL15)", "purpose": "Read/"
         "write PortInfo/NodeInfo, forwarding tables, SL-to-VL, VL arb — "
         "in-band controllability/observability."},
        {"name": "General Services (GMP / QP1)", "purpose": "PortCounters, "
         "Communication Management, Subnet Administration, Device "
         "Management."},
        {"name": "Performance counters", "purpose": "Symbol errors, link "
         "recovery, received/transmitted data + packets per port."},
        {"name": "VCRC / ICRC", "purpose": "Per-hop and end-to-end error "
         "detection telemetry."},
        {"name": "PSN ACK/NAK", "purpose": "Reliable-delivery sequencing "
         "exposes loss / out-of-sequence."},
    ]
    f["internal_diagnostics_observability"] = [
        "Physical link state (Down/Polling/Configuration/LinkUp).",
        "Negotiated link width / speed.",
        "Per-VL credit and arbitration state.",
        "QP state (RESET/INIT/RTR/RTS/Error) and PSN.",
        "PortCounters (errors, data, packets).",
    ]
    f["out_of_band_test_facilities"] = [
        "IBTA Plugfest / Integrators' List interoperability testing.",
        "Vendor SerDes bring-up / BER probes (implementation-defined).",
    ]
    f["notes"] = (
        "InfiniBand's test surface is in-band management (SMPs on QP0/VL15, "
        "GMPs on QP1) plus PortCounters and the VCRC/ICRC + PSN telemetry. "
        "Chip-level JTAG/scan/BIST remain implementation concerns; "
        "interoperability is established by IBTA Plugfests.")
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
    f["link_power_management_states"] = [
        {"state": "LinkUp", "name": "Active", "description": "Link "
         "operational; packets flow.",
         "exit_latency_estimate": "n/a"},
        {"state": "Down", "name": "Down", "description": "Link not "
         "established; retrain required to resume.",
         "exit_latency_estimate": "training-dominated"},
    ]
    f["notes"] = (
        "The InfiniBand Architecture focuses on the link/transport protocol; "
        "detailed link power states are largely implementation-defined. The "
        "Physical Layer link states (Down/Polling/Configuration/LinkUp) "
        "govern bring-up, and a link that drops to Down must retrain to "
        "resume. SerDes power scaling and lane shutdown are vendor "
        "concerns.")
    f["power_considerations"] = (
        "Higher per-lane rates (HDR/NDR PAM4) and wider links (4x/12x) trade "
        "power for bandwidth; idle links may be brought Down and retrained. "
        "Energy-per-bit is an implementation property, not fixed by the "
        "architecture.")
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
        "Physical link training and per-lane eye at each width/speed "
        "(SDR..NDR, 1x/4x/12x).",
        "Line code 8b/10b vs 64b/66b; PAM4 at HDR/NDR.",
        "LRH framing + switch DLID forwarding.",
        "GRH + router DGID inter-subnet routing.",
        "Virtual Lanes: VL0..VL14 + VL15, SL-to-VL mapping, VL arbitration.",
        "Absolute credit-based per-VL flow control (VL15 exempt).",
        "Queue-Pair bring-up RESET->INIT->RTR->RTS via verbs; CQ "
        "completions.",
        "Service types RC/UC/UD/RD.",
        "SEND/RECEIVE and RDMA WRITE/READ + Atomics.",
        "BTH + PSN reliable delivery: ACK/NAK, retransmission, RNR.",
        "MTU set 256/512/1024/2048/4096 and segmentation.",
        "VCRC (per hop) + ICRC (end-to-end) error detection.",
        "Subnet Manager LID assignment + forwarding-table programming; SMP "
        "on QP0/VL15.",
        "General management on QP1 (PortCounters, CM, SA).",
        "Partitioning (P_Key) enforcement.",
    ]
    f["notes"] = (
        "The IBTA specification implies a verification plan spanning the "
        "Physical (training, eye), Link (LRH, VL, credits, VCRC), Network "
        "(GRH routing), and Transport (QP, PSN, RC/UC/UD/RD, RDMA) layers "
        "plus management (SMP/GMP). Interoperability is established by IBTA "
        "Plugfest / Integrators' List testing.")
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
        "16-bit Variant CRC (VCRC) checked at every hop.",
        "32-bit Invariant CRC (ICRC) checked end-to-end.",
        "PSN-based ACK/NAK + retransmission on reliable QPs.",
        "Credit-based flow control prevents buffer overrun.",
    ]
    f["access_control_features"] = [
        "Partition Keys (P_Key) restrict which ports may communicate "
        "(full/limited membership).",
        "Memory Region keys (L_Key / R_Key) gate local and remote (RDMA) "
        "memory access.",
        "Q_Key authorizes access to UD queue pairs.",
    ]
    f["anti_tampering_features"] = []
    f["confidentiality_features"] = []
    f["authentication_features"] = []
    f["future_security_pointers"] = [
        "Management-key (M_Key) protection of Subnet-Management attributes.",
        "Upper-Layer / fabric-level encryption is implementation- or "
        "ULP-defined; the base architecture provides partitioning and "
        "memory keys, not link encryption.",
    ]
    f["notes"] = (
        "InfiniBand's built-in protections are anti-corruption (VCRC/ICRC, "
        "PSN retransmission, credit flow control) and access control via "
        "Partition Keys (P_Key), Memory keys (L_Key/R_Key), Q_Keys, and the "
        "Management Key (M_Key). Cryptographic confidentiality/authentication "
        "of the data path is not part of the base architecture; the fabric "
        "is typically physically secured and any encryption is provided by "
        "upper layers.")
    _write(p, d)
