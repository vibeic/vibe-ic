"""Fibre Channel (INCITS T11 FC-FS / FC-PH) protocol synth helper.

ic_class-gated overlay for the Fibre Channel structural signature: a
high-speed serial storage / SAN networking interconnect standardized by
INCITS T11 (FC-PH, FC-FS family). Fibre Channel is organized as five
functional levels FC-0 (physical) .. FC-1 (8b/10b or 64b/66b encoding +
ordered sets) .. FC-2 (framing / sequences / exchanges / flow control) ..
FC-3 (common services) .. FC-4 (upper-level-protocol mapping, e.g. FCP =
SCSI over FC). It connects N_Port (node) / F_Port (fabric) / E_Port
(expansion) ports over point-to-point, arbitrated-loop (FC-AL), and
switched-fabric topologies, addresses ports with a 24-bit FC address
identifier (Domain/Area/Port) acquired at login plus a 64-bit World Wide
Name (WWN), frames data with SOF/EOF ordered sets + a 24-byte frame header
(R_CTL/D_ID/S_ID/TYPE/F_CTL/SEQ_ID/OX_ID/RX_ID) + <=2112 B payload + 32-bit
CRC, groups frames into sequences and exchanges, offers classes of service
1/2/3/F, uses buffer-to-buffer (BB_Credit) + end-to-end (EE_Credit) flow
control, logs in with FLOGI/PLOGI/PRLI, and carries SCSI through the FCP
FC-4 mapping (with FCoE as an Ethernet-encapsulation extension).

Doctrine — GENERAL not keyword: detection uses canonical STRUCTURAL
signatures read from the L-doc / input_doc CONTENT blob only — the
FC-0..FC-4 layering, the N_Port/F_Port/E_Port port-type triple, the FLOGI/
PLOGI login services, the FC-2 frame header (R_CTL/D_ID/S_ID), the
sequence/exchange hierarchy, the 24-bit FC address + 64-bit WWN, the
classes of service, and BB_Credit/FCP. It NEVER reads the input-document
filename or the benchmark folder name (word-boundary tokens only).

Sibling disambiguation — Fibre Channel vs SAS, SATA, Ethernet, and
InfiniBand (the storage / fabric family). All carry storage or fabric
traffic, but only Fibre Channel has the FC-0..FC-4 layering with the
N_Port/F_Port/E_Port triple, FLOGI/PLOGI, the FC-2 R_CTL/D_ID/S_ID frame
header with sequences/exchanges, a 24-bit FC address + 64-bit WWN, classes
of service 1/2/3/F, and BB_Credit. The detector DEFERS when the doc is
SAS-primary (SSP/STP/SMP + expander + SAS address), SATA-primary
(AHCI/FIS host-device), Ethernet-primary (MAC/MII frame, not FC), or
InfiniBand-primary (Queue Pairs/LID/Virtual Lanes/Subnet Manager), so it
cannot false-fire on those siblings. (FCoE intentionally CARRIES FC over
Ethernet — an FCoE doc that still names the FC-2 frame / N_Port / FLOGI
remains Fibre Channel, while a pure 802.3 MAC/MII doc with none of the FC
signature defers.)

Public entry:
``apply_fibre_channel_synth(generated_docs_dir, is_fibre_channel,
fibre_channel_ic_name)``. Module-level ``is_fibre_channel(blob)`` is the
content-only detector.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

import l_doc_generator_stamp as _stamp


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

# Canonical Fibre Channel facts (INCITS T11 FC-FS / FC-PH).
_GFC_RATES = ["1GFC", "2GFC", "4GFC", "8GFC", "16GFC", "32GFC", "64GFC",
              "128GFC"]
_FRAME_HEADER_BYTES = 24
_MAX_PAYLOAD_BYTES = 2112
_CRC_BITS = 32
_FC_ADDRESS_BITS = 24
_WWN_BITS = 64
_PORT_TYPES = ["N_Port", "F_Port", "E_Port", "NL_Port", "FL_Port", "G_Port"]
_CLASSES_OF_SERVICE = ["Class 1", "Class 2", "Class 3", "Class F"]
_TOPOLOGIES = ["point-to-point", "arbitrated loop (FC-AL)", "switched fabric"]
_LOGIN_SERVICES = ["FLOGI", "PLOGI", "PRLI", "LOGO"]
_FC_LAYERS = ["FC-0", "FC-1", "FC-2", "FC-3", "FC-4"]


def _w(s: str) -> "re.Pattern":
    return re.compile(r"\b" + re.escape(s) + r"\b", re.IGNORECASE)


def is_fibre_channel(blob: str) -> bool:
    """Content-only Fibre Channel detector with a SAS / SATA / Ethernet /
    InfiniBand sibling MUTEX.

    Fire on the canonical FC structural signature: the FC-0..FC-4 layering,
    the N_Port/F_Port/E_Port port-type triple, the FLOGI/PLOGI login
    services, the FC-2 frame header (R_CTL/D_ID/S_ID) with sequences/
    exchanges, the 24-bit FC address + 64-bit WWN, classes of service, and
    BB_Credit/FCP. Defer when the doc is SAS-primary (SSP/STP/SMP +
    expander + SAS address), SATA-primary (AHCI/FIS host-device with NO FC
    signature), Ethernet-primary (802.3 MAC/MII frame with NO FC
    signature), or InfiniBand-primary (Queue Pairs/LID/Virtual Lanes/Subnet
    Manager with NO FC signature). Reads ONLY the spec text ``blob`` — never
    a filename or benchmark name. Uses word-boundary tokens.
    """
    if not blob:
        return False
    low = blob.lower()

    def has(*words: str) -> bool:
        return all(_w(w).search(blob) for w in words)

    def any_of(*words: str) -> bool:
        return any(_w(w).search(blob) for w in words)

    # --- FC-only structural tokens (word-boundary) ---
    # FC-0..FC-4 layering: require at least the core FC-2 plus one neighbour.
    fc_layers = (_w("FC-2").search(blob) is not None) and any_of(
        "FC-0", "FC-1", "FC-3", "FC-4")
    # Port-type triple (the FC role vocabulary).
    port_types = (any_of("N_Port") and any_of("F_Port")
                  and any_of("E_Port"))
    # Login services (Extended Link Services). login2 = at least two of the
    # FLOGI/PLOGI/PRLI Extended Link Services named.
    login2 = sum(1 for t in ("FLOGI", "PLOGI", "PRLI") if any_of(t)) >= 2
    # FC-2 frame header structural fields.
    frame_header = (any_of("R_CTL") and any_of("D_ID") and any_of("S_ID"))
    # Sequence / exchange hierarchy (with OX_ID/RX_ID exchange identifiers).
    seq_exch = (("sequence" in low and "exchange" in low)
                and (any_of("OX_ID", "RX_ID", "SEQ_ID")))
    # 24-bit FC address identifier (+ Domain/Area/Port structuring).
    fc_addr = (("24-bit" in low and ("fibre channel address" in low
                                     or "address identifier" in low
                                     or "port_id" in low or "n_port_id" in low))
               or ("domain" in low and "area" in low
                   and ("port_id" in low or "address identifier" in low)))
    # 64-bit World Wide Name.
    wwn = (any_of("WWN", "WWNN", "WWPN")
           or "world wide name" in low or "world wide port name" in low
           or "world wide node name" in low)
    # Classes of service 1/2/3/F.
    cos = ("class of service" in low or "classes of service" in low
           or (any_of("Class 1") and any_of("Class 3"))
           or any_of("Class F"))
    # Buffer-to-buffer credit flow control.
    bb_credit = ("bb_credit" in low or "buffer-to-buffer credit" in low
                 or "buffer to buffer credit" in low)
    # FCP (SCSI over FC) FC-4 mapping.
    fcp = (_w("FCP").search(blob) is not None
           or "fibre channel protocol" in low)
    # Name token (canonical, word-boundary; never filename).
    name_token = ("fibre channel" in low or "fibre-channel" in low
                  or _w("FC-FS").search(blob) is not None
                  or _w("FC-PH").search(blob) is not None)

    # STRUCTURAL signal — require the FC-2 frame header + sequence/exchange +
    # the port-type / login / addressing identity, NOT a name token alone.
    fc_structure = (
        frame_header
        and seq_exch
        and (port_types or login2)
        and (fc_addr or wwn)
        and (cos or bb_credit or fcp)
    )

    # --- Sibling MUTEX ---
    # SAS-primary: SSP + STP + SMP transports + expander + SAS address, and
    # NONE of the FC-2 frame-header / N_Port / FLOGI signature.
    sas_ssp = "ssp" in low or "serial scsi protocol" in low
    sas_stp = ("stp" in low or "sata tunneling" in low)
    sas_smp = "smp" in low or "serial management protocol" in low
    sas_primary = (
        sas_ssp and sas_stp and sas_smp and ("expander" in low)
        and ("sas address" in low or "wide port" in low)
        and not (frame_header or port_types or login2 or name_token)
    )
    if sas_primary:
        return False

    # SATA-primary: AHCI / FIS host-device link with NO FC signature.
    sata_primary = (
        ("ahci" in low or _w("FIS").search(blob) is not None
         or "advanced host controller" in low)
        and not (frame_header or port_types or login2 or wwn or name_token
                 or seq_exch)
    )
    if sata_primary:
        return False

    # Ethernet-primary: 802.3 MAC/MII frame with NO FC signature. (An FCoE
    # doc that still names the FC-2 frame / N_Port / FLOGI stays FC.)
    ethernet_primary = (
        ("802.3" in low or any_of("MII", "GMII", "RGMII", "MAC")
         or "media access control" in low)
        and not (frame_header or port_types or login2 or fc_addr or wwn
                 or name_token or seq_exch)
    )
    if ethernet_primary:
        return False

    # InfiniBand-primary: Queue Pairs / LID / Virtual Lanes / Subnet Manager
    # with NO FC signature.
    infiniband_primary = (
        (any_of("LID") or "queue pair" in low or "virtual lane" in low
         or "subnet manager" in low or "infiniband" in low)
        and not (frame_header or port_types or login2 or fc_addr or wwn
                 or name_token or seq_exch)
    )
    if infiniband_primary:
        return False

    return bool(
        fc_structure
        or (name_token and fc_layers and (port_types or login2)
            and (frame_header or seq_exch))
        or (name_token and frame_header and seq_exch and (fc_addr or wwn))
    )


def apply_fibre_channel_synth(generated_docs_dir: Path,
                              is_fibre_channel: bool,
                              fibre_channel_ic_name: Optional[str]) -> None:
    """Apply INCITS T11 Fibre Channel (FC-FS) synth when the FC signature
    matched. Force-assigns (direct assignment, not setdefault) the FC
    canonical content into L1-L23."""
    if not is_fibre_channel:
        return
    gd = Path(generated_docs_dir)

    # --- Force ic_name across ALL 24 docs FIRST (main + fields docs). ---
    if fibre_channel_ic_name is not None:
        for n in _MAIN_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                d["ic_name"] = fibre_channel_ic_name
                _write(q, d)
        for n in _FIELDS_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                f = _ensure_dict(d, "fields")
                f["ic_name"] = fibre_channel_ic_name
                d["ic_name"] = fibre_channel_ic_name  # belt-and-braces
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
# L1 — Fibre Channel datasheet header + FC-0..FC-4 architecture.
# ----------------------------------------------------------------------
def _l1(gd: Path) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    d["document_title"] = (
        "Fibre Channel Framing and Signaling Interface (FC-FS)")
    d["version"] = "INCITS T11 FC-FS / FC-PH"
    d["manufacturer"] = "INCITS T11"
    d["standards_body"] = "INCITS T11 (ANSI)"
    d["abstract"] = (
        "Fibre Channel is a high-speed serial storage and networking "
        "interconnect for Storage Area Networks (SAN), standardized by the "
        "INCITS T11 technical committee (FC-PH, FC-FS family). It is "
        "organized as five functional levels: FC-0 (physical layer: media, "
        "transmitters/receivers, gigabaud signaling rates), FC-1 "
        "(transmission layer: 8b/10b encoding at 1/2/4/8 GFC and 64b/66b at "
        "16 GFC and above, plus ordered sets), FC-2 (framing and signaling: "
        "the frame, the sequence, the exchange, flow control, classes of "
        "service, and login), FC-3 (common services across the ports of a "
        "node), and FC-4 (upper-level-protocol mapping, dominantly FCP which "
        "carries SCSI over Fibre Channel). Fibre Channel connects N_Ports "
        "(node), F_Ports (fabric), and E_Ports (inter-switch expansion) over "
        "point-to-point, arbitrated-loop (FC-AL), and switched-fabric "
        "topologies. A port acquires a 24-bit Fibre Channel address "
        "identifier (Domain/Area/Port) at login and is uniquely named by a "
        "64-bit World Wide Name (WWN). Frames are bounded by SOF/EOF ordered "
        "sets, carry a 24-byte frame header and up to 2112 bytes of payload, "
        "and are protected by a 32-bit CRC. Flow control uses "
        "buffer-to-buffer credit (BB_Credit) and end-to-end credit "
        "(EE_Credit). Login uses FLOGI (fabric), PLOGI (port), and PRLI "
        "(process). FCoE extends Fibre Channel framing over lossless "
        "Ethernet.")
    d["keywords"] = [
        "Fibre Channel", "INCITS T11", "FC-FS", "FC-PH", "FC-0", "FC-1",
        "FC-2", "FC-3", "FC-4", "N_Port", "F_Port", "E_Port", "NL_Port",
        "FL_Port", "arbitrated loop", "FC-AL", "switched fabric",
        "World Wide Name", "WWN", "24-bit FC address", "frame header",
        "R_CTL", "D_ID", "S_ID", "sequence", "exchange", "OX_ID", "RX_ID",
        "class of service", "BB_Credit", "EE_Credit", "FLOGI", "PLOGI",
        "PRLI", "FCP", "SCSI", "FCoE", "SAN", "GFC", "32-bit CRC",
    ]
    d["external_pins"] = [
        "TX (transmit serial differential pair / optical Tx) — unidirectional "
        "FC-0 transmit lane at the negotiated GFC rate",
        "RX (receive serial differential pair / optical Rx) — unidirectional "
        "FC-0 receive lane at the negotiated GFC rate",
        "REFCLK — reference clock for the SerDes",
        "Power / ground rails (analog SerDes + digital core)",
        "RESET / link-init control",
    ]
    d["external_pin_count_per_link"] = (
        "1 transmit + 1 receive serial lane (a full-duplex link is one "
        "Tx + one Rx); 128GFC aggregates 4 lanes per direction")
    d["supported_signaling_rates_GFC"] = list(_GFC_RATES)
    d["modes_of_operation"] = [
        {"name": "Point-to-point", "description": "Direct N_Port-to-N_Port "
         "link between exactly two devices; full link bandwidth dedicated to "
         "the pair."},
        {"name": "Arbitrated Loop (FC-AL)", "description": "Up to 126 "
         "NL_Ports (plus one optional FL_Port) share a loop; ports arbitrate "
         "with the ARB ordered set and use an 8-bit AL_PA assigned at loop "
         "initialization."},
        {"name": "Switched Fabric", "description": "One or more switches "
         "interconnect N_Ports through F_Ports and route by 24-bit "
         "destination address; provides fabric services (Name Server, Fabric "
         "Controller, Management Server)."},
    ]
    d["key_features"] = [
        "Five-level layered architecture FC-0 (physical) / FC-1 (encoding + "
        "ordered sets) / FC-2 (framing, sequences, exchanges, flow control) "
        "/ FC-3 (common services) / FC-4 (ULP mapping such as FCP).",
        "Port types: N_Port (node), F_Port (fabric), E_Port (inter-switch "
        "expansion), NL_Port / FL_Port (arbitrated loop), G_Port (generic).",
        "Three topologies: point-to-point, arbitrated loop (FC-AL), and "
        "switched fabric.",
        "24-bit Fibre Channel address identifier (Domain_ID / Area_ID / "
        "Port_ID) assigned by the fabric at FLOGI; well-known service "
        "addresses 0xFFFFF0..0xFFFFFE.",
        "64-bit World Wide Name (WWN) — WWNN per node and WWPN per port — "
        "for permanent naming, zoning, and authentication.",
        "FC-2 frame: SOF | 24-byte header (R_CTL/D_ID/S_ID/TYPE/F_CTL/"
        "SEQ_ID/SEQ_CNT/OX_ID/RX_ID) | up to 2112-byte payload | 32-bit CRC "
        "| EOF.",
        "Hierarchical transfer: frame -> sequence (same SEQ_ID, ordered by "
        "SEQ_CNT) -> exchange (OX_ID/RX_ID, one ULP operation).",
        "Classes of service: Class 1 (dedicated connection, acknowledged), "
        "Class 2 (connectionless, acknowledged), Class 3 (connectionless, "
        "datagram), Class F (inter-switch fabric).",
        "Credit-based flow control: buffer-to-buffer credit (BB_Credit, "
        "link-by-link, R_RDY) and end-to-end credit (EE_Credit, ACK, for "
        "acknowledged classes).",
        "Login protocol: FLOGI (fabric login), PLOGI (port login), PRLI "
        "(process login), LOGO (logout) via Extended Link Services.",
        "FC-1 encoding: 8b/10b at 1/2/4/8 GFC, 64b/66b at 16/32/64 GFC; "
        "ordered sets (K28.5-based) for frame delimiters, primitive signals "
        "(IDLE, R_RDY), and primitive sequences (NOS/OLS/LR/LRR).",
        "FC-4 mappings: FCP (SCSI over FC), FC-NVMe, IP over FC, FICON.",
        "Signaling rates 1/2/4/8/16/32/64/128 GFC with speed negotiation and "
        "backward compatibility.",
        "FCoE extension: encapsulates FC frames in Ethernet (EtherType "
        "0x8906) over lossless Ethernet, with FIP (0x8914) for discovery / "
        "login.",
    ]
    d["topology_summary"] = (
        "Fibre Channel supports point-to-point (direct N_Port to N_Port), "
        "arbitrated loop (FC-AL, up to 126 NL_Ports sharing the medium with "
        "ARB-based arbitration and 8-bit AL_PAs), and switched fabric (N_Ports "
        "attach to F_Ports on switches that route frames by 24-bit address; "
        "switches interconnect via E_Ports / Inter-Switch Links).")
    d["use_cases"] = [
        "Enterprise Storage Area Networks (SAN) carrying SCSI over FCP",
        "All-flash and disk arrays attached to host bus adapters (HBAs)",
        "FC-NVMe for low-latency NVMe-over-Fabrics storage",
        "FICON mainframe storage connectivity",
        "Switched fabrics scaling to large addressable port counts with "
        "Name Server discovery and zoning",
        "FCoE convergence of SAN and LAN onto lossless Ethernet",
    ]
    d["revision_history"] = [
        {"version": "FC-PH", "description": "ANSI X3.230 Fibre Channel "
         "Physical and Signaling Interface — original FC-0/FC-1/FC-2 "
         "definition (frame, sequence, exchange, classes of service, login)."},
        {"version": "FC-FS / FC-FS-2..FC-FS-5", "description": "INCITS T11 "
         "Fibre Channel Framing and Signaling — consolidates and extends the "
         "FC-1/FC-2 framing and signaling, adding higher GFC rates "
         "(16/32/64/128 GFC) and 64b/66b encoding."},
    ]
    d["overview"] = (
        "Fibre Channel (FC) is a gigabit-speed, serial, full-duplex "
        "interconnect for storage and SAN networking, standardized by INCITS "
        "T11. A link is a pair of unidirectional fibres or copper "
        "differential pairs (one transmit, one receive). Fibre Channel is "
        "organized as five levels FC-0..FC-4: FC-0 is the physical media and "
        "gigabaud signaling; FC-1 is byte encoding (8b/10b at 1/2/4/8 GFC, "
        "64b/66b at 16 GFC and above) and ordered sets; FC-2 is the framing "
        "and signaling heart of the protocol (the frame with its 24-byte "
        "header, the sequence, the exchange, flow control, classes of "
        "service, and the login protocol); FC-3 provides common services "
        "across a node's ports; and FC-4 maps an upper-level protocol onto "
        "Fibre Channel (most commonly FCP, which carries SCSI). Ports are "
        "classified as N_Port (node), F_Port (fabric), E_Port (inter-switch "
        "expansion), and the loop variants NL_Port / FL_Port. Three "
        "topologies are defined: point-to-point, arbitrated loop (FC-AL), "
        "and switched fabric. A port acquires a 24-bit Fibre Channel address "
        "identifier (Domain/Area/Port) during FLOGI and is permanently named "
        "by a 64-bit World Wide Name. Frames are delimited by SOF/EOF ordered "
        "sets, carry up to 2112 bytes of payload, and are protected by a "
        "32-bit CRC. Flow control uses buffer-to-buffer credit (BB_Credit) "
        "and end-to-end credit (EE_Credit). FCoE extends the FC-2 frame model "
        "across lossless Ethernet.")
    _write(p, d)


# ----------------------------------------------------------------------
# L2 — FRS / protocol overview (the FC-2 framing + login + flow-control
# model).
# ----------------------------------------------------------------------
def _l2(gd: Path) -> None:
    p = gd / "L2_FRS.json"
    if not p.is_file():
        return
    d = _read(p)
    po = _ensure_dict(d, "protocol_overview")
    po["type"] = (
        "High-speed serial storage / SAN interconnect (INCITS T11 Fibre "
        "Channel). Five-level architecture FC-0 (physical) / FC-1 (encoding "
        "+ ordered sets) / FC-2 (framing, sequences, exchanges, flow "
        "control, classes of service, login) / FC-3 (common services) / FC-4 "
        "(ULP mapping such as FCP=SCSI). Signaling 1-128 GFC.")
    po["duplex"] = (
        "full-duplex: each link is one unidirectional transmit lane and one "
        "unidirectional receive lane, so both directions are simultaneous "
        "and continuous.")
    po["source_synchronous"] = False
    po["embedded_clock"] = True
    po["encoding"] = (
        "FC-1: 8b/10b line encoding at 1/2/4/8 GFC, 64b/66b at 16/32/64 GFC "
        "(PAM-4 at 64GFC). Ordered sets are 4-byte transmission words "
        "beginning with the K28.5 special character: frame delimiters "
        "(SOF/EOF), primitive signals (IDLE, R_RDY), and primitive sequences "
        "(NOS/OLS/LR/LRR).")
    po["modulation"] = (
        "NRZ at 1/2/4/8/16/32 GFC; PAM-4 at 64GFC; embedded-clock with "
        "clock-data recovery at the receiver.")
    po["layers"] = [
        "FC-4 Upper-Level-Protocol mapping (FCP = SCSI, FC-NVMe, IP over FC, "
        "FICON)",
        "FC-3 Common Services (striping, hunt groups, multicast across a "
        "node's ports)",
        "FC-2 Framing and Signaling (frame, sequence, exchange, flow control, "
        "classes of service, login)",
        "FC-1 Transmission (8b/10b or 64b/66b encoding, ordered sets, running "
        "disparity, word synchronization)",
        "FC-0 Physical (media, transmitters/receivers, connectors, gigabaud "
        "signaling rates)",
    ]
    po["port_types"] = list(_PORT_TYPES)
    po["topologies"] = list(_TOPOLOGIES)
    po["address_identifier_bits"] = _FC_ADDRESS_BITS
    po["world_wide_name_bits"] = _WWN_BITS
    po["frame_header_bytes"] = _FRAME_HEADER_BYTES
    po["max_payload_bytes"] = _MAX_PAYLOAD_BYTES
    po["crc_width_bits"] = _CRC_BITS
    po["classes_of_service"] = list(_CLASSES_OF_SERVICE)
    po["login_services"] = list(_LOGIN_SERVICES)
    po["flow_control"] = (
        "Credit-based: buffer-to-buffer credit (BB_Credit) managed link-by-"
        "link with R_RDY primitive signals; end-to-end credit (EE_Credit) "
        "managed N_Port-to-N_Port with ACK frames for the acknowledged "
        "classes (Class 1 and Class 2). Class 3 uses only BB_Credit.")
    po["signaling_rates_GFC"] = list(_GFC_RATES)
    po["fc4_mappings"] = ["FCP (SCSI over FC)", "FC-NVMe", "IP over FC",
                          "FICON"]
    po["frame_based"] = True
    po["sequence_exchange_model"] = (
        "Frame (header + payload + CRC, tagged SEQ_ID/SEQ_CNT) -> Sequence "
        "(related frames, same SEQ_ID, ordered by SEQ_CNT, unit of error "
        "recovery) -> Exchange (related sequences for one ULP operation, "
        "identified by OX_ID/RX_ID).")
    d["functional_requirements"] = [
        {"id": "FR-LAYER-01", "text": "Fibre Channel is organized as five "
         "functional levels FC-0 (physical) / FC-1 (encoding + ordered sets) "
         "/ FC-2 (framing, sequences, exchanges, flow control, classes of "
         "service, login) / FC-3 (common services) / FC-4 (ULP mapping)."},
        {"id": "FR-PORT-02", "text": "Define port types N_Port (node), "
         "F_Port (fabric), E_Port (inter-switch expansion), NL_Port / "
         "FL_Port (arbitrated loop), and G_Port (generic) with the "
         "point-to-point, arbitrated-loop (FC-AL), and switched-fabric "
         "topologies."},
        {"id": "FR-ADDR-03", "text": "A port acquires a 24-bit Fibre Channel "
         "address identifier (Domain_ID bits 23..16 / Area_ID bits 15..8 / "
         "Port_ID bits 7..0) assigned by the fabric at FLOGI, and is named by "
         "a 64-bit World Wide Name (WWNN per node, WWPN per port)."},
        {"id": "FR-FRAME-04", "text": "The FC-2 frame is SOF | 24-byte frame "
         "header (R_CTL, D_ID, CS_CTL, S_ID, TYPE, F_CTL, SEQ_ID, DF_CTL, "
         "SEQ_CNT, OX_ID, RX_ID, Parameter) | payload up to 2112 bytes | "
         "32-bit CRC | EOF."},
        {"id": "FR-SEQEXCH-05", "text": "Frames are grouped into sequences "
         "(same SEQ_ID, ordered by SEQ_CNT, the unit of error recovery) and "
         "sequences into exchanges (OX_ID/RX_ID, one ULP operation); sequence "
         "initiative is passed via F_CTL."},
        {"id": "FR-COS-06", "text": "Provide classes of service: Class 1 "
         "(dedicated acknowledged connection), Class 2 (connectionless "
         "acknowledged), Class 3 (connectionless datagram, the common SCSI "
         "class), and Class F (inter-switch fabric control)."},
        {"id": "FR-FLOW-07", "text": "Implement credit-based flow control: "
         "buffer-to-buffer credit (BB_Credit, link-by-link, R_RDY) and "
         "end-to-end credit (EE_Credit, ACK) for acknowledged classes; Class "
         "3 uses BB_Credit only."},
        {"id": "FR-LOGIN-08", "text": "Provide the login protocol via "
         "Extended Link Services: FLOGI (fabric login, the fabric assigns the "
         "24-bit address and exchanges service parameters), PLOGI (port "
         "login, exchanges WWN/EE_Credit/classes/max payload), PRLI (process "
         "login, establishes the FC-4 session), and LOGO (logout)."},
        {"id": "FR-ENCODE-09", "text": "FC-1 uses 8b/10b encoding at "
         "1/2/4/8 GFC and 64b/66b at 16 GFC and above, with ordered sets "
         "(K28.5-based) for frame delimiters, primitive signals (IDLE, "
         "R_RDY), and primitive sequences (NOS/OLS/LR/LRR)."},
        {"id": "FR-FC4-10", "text": "Map at least one upper-level protocol "
         "via FC-4; FCP carries SCSI through the IUs FCP_CMND / FCP_XFER_RDY "
         "/ FCP_DATA / FCP_RSP, one I/O per exchange, TYPE=0x08."},
        {"id": "FR-SVC-11", "text": "Provide fabric services at well-known "
         "addresses: Name Server (0xFFFFFC) for discovery, Fabric Controller "
         "(0xFFFFFD) for State Change Notification (RSCN), Management Server "
         "(0xFFFFFA)."},
        {"id": "FR-RATE-12", "text": "Support signaling rates 1/2/4/8/16/32/"
         "64/128 GFC with speed negotiation to the highest mutually supported "
         "rate and backward compatibility to lower rates."},
        {"id": "FR-FCOE-13", "text": "Optionally support FCoE: encapsulate FC "
         "frames in Ethernet (EtherType 0x8906) over lossless Ethernet, with "
         "FIP (0x8914) for discovery and login, preserving the FC-2 frame / "
         "sequence / exchange / login model."},
    ]
    d["error_response_conditions"] = [
        "Bad frame CRC -> frame discarded; the sequence is aborted and "
        "recovered at the sequence/exchange level (ABTS).",
        "Lost or out-of-order frame (SEQ_CNT gap) -> sequence error; "
        "recovery per class of service.",
        "Missing R_RDY / BB_Credit exhaustion -> transmitter stalls until "
        "credit is returned (avoids receiver buffer overflow).",
        "Missing ACK / EE_Credit exhaustion (acknowledged classes) -> "
        "end-to-end recovery / timeout.",
        "Link not operational -> primitive-sequence protocol (NOS -> OLS -> "
        "LR -> LRR) re-initializes the link.",
        "Login failure / parameter mismatch (FLOGI/PLOGI/PRLI reject) -> "
        "port cannot enter the fabric or open a session.",
    ]
    d["compliance_requirements"] = [
        "Implement FC-0..FC-2 (minimum) plus at least one FC-4 mapping "
        "(typically FCP).",
        "Support the 24-byte frame header (R_CTL/D_ID/S_ID/TYPE/F_CTL/SEQ_ID/"
        "SEQ_CNT/OX_ID/RX_ID), <=2112-byte payload, and 32-bit CRC.",
        "Support sequences and exchanges with SEQ_ID/SEQ_CNT and OX_ID/RX_ID.",
        "Implement buffer-to-buffer credit flow control (and end-to-end "
        "credit for the acknowledged classes).",
        "Support the login protocol (FLOGI/PLOGI/PRLI) and well-known fabric "
        "service addresses.",
        "Use 8b/10b (<=8 GFC) or 64b/66b (>=16 GFC) encoding with the defined "
        "ordered sets.",
        "Negotiate signaling rate and service parameters; provide a 24-bit "
        "address identifier and a 64-bit WWN.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L3 — FC-2 frame format / channels / sequence-exchange / login protocol.
# ----------------------------------------------------------------------
def _l3(gd: Path) -> None:
    p = gd / "L3_CMD_PROTOCOL.json"
    if not p.is_file():
        return
    d = _read(p)
    d["protocol_type"] = (
        "Layered serial frame protocol (INCITS T11 Fibre Channel FC-2). The "
        "FC-4 ULP (e.g. FCP) hands an operation to FC-2, which frames it: "
        "each frame is SOF | 24-byte header | payload (<=2112 B) | 32-bit CRC "
        "| EOF, tagged with SEQ_ID/SEQ_CNT and the exchange OX_ID/RX_ID. "
        "Frames form sequences and sequences form exchanges. FC-1 encodes the "
        "frame (8b/10b or 64b/66b) with ordered sets; FC-0 serializes it at "
        "1-128 GFC. Flow control is credit-based (BB_Credit + EE_Credit).")
    d["channels"] = [
        {"name": "Transmit serial lane (TX)",
         "direction": "unidirectional (output)",
         "description": "FC-0 transmit lane carrying encoded frames and "
         "ordered sets at the negotiated GFC rate (8b/10b <=8 GFC, 64b/66b "
         ">=16 GFC); 128GFC aggregates 4 lanes."},
        {"name": "Receive serial lane (RX)",
         "direction": "unidirectional (input)",
         "description": "FC-0 receive lane recovering encoded frames and "
         "ordered sets; embedded-clock with CDR."},
        {"name": "Ordered sets (FC-1)", "direction": "in-band on TX/RX",
         "description": "4-byte K28.5-based transmission words: frame "
         "delimiters (SOF/EOF), primitive signals (IDLE, R_RDY), primitive "
         "sequences (NOS/OLS/LR/LRR)."},
    ]
    d["layer_stack"] = [
        {"layer": "FC-4 (ULP mapping)",
         "purpose": "Map an upper-level protocol onto Fibre Channel; FCP "
         "carries SCSI (FCP_CMND/XFER_RDY/DATA/RSP), also FC-NVMe / IP / "
         "FICON."},
        {"layer": "FC-3 (Common Services)",
         "purpose": "Services across a node's ports: striping, hunt groups, "
         "multicast."},
        {"layer": "FC-2 (Framing and Signaling)",
         "purpose": "Frame / sequence / exchange constructs, flow control "
         "(BB_Credit/EE_Credit), classes of service, login."},
        {"layer": "FC-1 (Transmission)",
         "purpose": "8b/10b or 64b/66b encoding, ordered sets, running "
         "disparity, word synchronization."},
        {"layer": "FC-0 (Physical)",
         "purpose": "Media, transmitters/receivers, connectors, gigabaud "
         "signaling rates (1-128 GFC)."},
    ]
    d["frame_format"] = {
        "structure": "SOF | Frame Header (24 bytes) | Optional Headers | "
                     "Data Field (0..2112 bytes) | CRC (4 bytes) | EOF",
        "sof_eof": "SOF and EOF are FC-1 ordered sets; SOF variants by class "
                   "(SOFi1/SOFn1/SOFi2/SOFn2/SOFi3/SOFn3/SOFf), EOF variants "
                   "(EOFn/EOFt/EOFa).",
        "frame_header_bytes": _FRAME_HEADER_BYTES,
        "max_payload_bytes": _MAX_PAYLOAD_BYTES,
        "crc_width_bits": _CRC_BITS,
    }
    d["frame_header_fields"] = [
        {"field": "R_CTL", "bytes": 1, "description": "Routing Control — "
         "frame category (FC-4 device data, link control, extended/basic link "
         "service) and information category."},
        {"field": "D_ID", "bytes": 3, "description": "Destination address "
         "identifier (24-bit FC address of the destination port)."},
        {"field": "CS_CTL/Priority", "bytes": 1, "description": "Class-"
         "specific control or priority."},
        {"field": "S_ID", "bytes": 3, "description": "Source address "
         "identifier (24-bit FC address of the source port)."},
        {"field": "TYPE", "bytes": 1, "description": "FC-4 upper-level-"
         "protocol type (0x08 = FCP, 0x05 = IP over FC, 0x20 = FC-CT)."},
        {"field": "F_CTL", "bytes": 3, "description": "Frame Control — "
         "first/last sequence, exchange originator/responder context, "
         "sequence initiative, relative offset present, end-of-sequence, "
         "abort condition."},
        {"field": "SEQ_ID", "bytes": 1, "description": "Sequence Identifier "
         "— identifies the sequence this frame belongs to."},
        {"field": "DF_CTL", "bytes": 1, "description": "Data Field Control — "
         "which optional headers are present."},
        {"field": "SEQ_CNT", "bytes": 2, "description": "Sequence Count — "
         "sequential index of the frame within its sequence."},
        {"field": "OX_ID", "bytes": 2, "description": "Originator Exchange "
         "Identifier — assigned by the exchange originator."},
        {"field": "RX_ID", "bytes": 2, "description": "Responder Exchange "
         "Identifier — assigned by the responder."},
        {"field": "Parameter", "bytes": 4, "description": "Relative offset of "
         "the payload, or a link-control parameter, depending on frame type."},
    ]
    d["sequence_exchange"] = {
        "frame": "Smallest indivisible unit (header + payload + CRC), tagged "
                 "with SEQ_ID and SEQ_CNT.",
        "sequence": "One or more related frames in the same direction with "
                    "the same SEQ_ID, ordered by SEQ_CNT; the unit of error "
                    "recovery.",
        "exchange": "One or more nonconcurrent sequences for a single ULP "
                    "operation, identified by the OX_ID/RX_ID pair (originator "
                    "allocates OX_ID, responder allocates RX_ID).",
        "sequence_initiative": "Passed via F_CTL; governs which side may "
                               "transmit the next sequence in the exchange.",
    }
    d["addressing"] = {
        "fc_address_identifier_bits": _FC_ADDRESS_BITS,
        "structure": {
            "Domain_ID": "bits 23..16 — identifies the switch (domain)",
            "Area_ID": "bits 15..8 — group of ports within a domain",
            "Port_ID": "bits 7..0 — individual port within an area"},
        "assigned_at": "FLOGI (fabric login)",
        "world_wide_name_bits": _WWN_BITS,
        "wwn_kinds": {"WWNN": "World Wide Node Name (per node)",
                      "WWPN": "World Wide Port Name (per port)"},
        "well_known_addresses": {
            "0xFFFFFE": "Fabric F_Port (FLOGI)",
            "0xFFFFFD": "Fabric Controller (RSCN)",
            "0xFFFFFC": "Name Server (discovery)",
            "0xFFFFFB": "Time Server",
            "0xFFFFFA": "Management Server",
            "0xFFFFFF": "Broadcast"},
    }
    d["classes_of_service"] = [
        {"class": "Class 1", "description": "Dedicated connection between two "
         "N_Ports with confirmed (acknowledged) delivery; full path bandwidth "
         "reserved for the duration."},
        {"class": "Class 2", "description": "Connectionless, frame-switched, "
         "acknowledged delivery; each frame is ACKed and uses end-to-end "
         "credit; frames may take different routes."},
        {"class": "Class 3", "description": "Connectionless, frame-switched, "
         "unacknowledged ('datagram') delivery; no ACK, only buffer-to-buffer "
         "credit; the common class for SCSI/FCP."},
        {"class": "Class F", "description": "Inter-switch (E_Port to E_Port) "
         "control traffic for fabric routing and management; connectionless, "
         "acknowledged."},
    ]
    d["flow_control"] = {
        "buffer_to_buffer_credit": "BB_Credit — managed link-by-link; the "
        "receiver advertises buffers at login and returns an R_RDY primitive "
        "for each freed buffer; essential over long-distance links.",
        "end_to_end_credit": "EE_Credit — managed N_Port-to-N_Port for the "
        "acknowledged classes (1 and 2); the destination returns an ACK frame "
        "to replenish credit. Class 3 has no EE_Credit and no ACK.",
    }
    d["login_protocol"] = [
        {"els": "FLOGI", "name": "Fabric Login", "description": "N_Port logs "
         "in to the fabric (F_Port at 0xFFFFFE); the fabric assigns the "
         "24-bit FC address and exchanges service parameters (BB_Credit, "
         "classes, max frame size)."},
        {"els": "PLOGI", "name": "Port Login", "description": "N_Port logs in "
         "to another N_Port (or well-known service such as Name Server "
         "0xFFFFFC) to exchange WWN/EE_Credit/classes/max payload and "
         "establish an end-to-end session."},
        {"els": "PRLI", "name": "Process Login", "description": "Establishes "
         "the FC-4 (ULP) session; for FCP it negotiates initiator/target "
         "roles and FCP service parameters."},
        {"els": "LOGO", "name": "Logout", "description": "Tears down a "
         "login."},
    ]
    d["fc4_fcp"] = {
        "type_field": "0x08",
        "io_is_one_exchange": True,
        "information_units": [
            {"iu": "FCP_CMND", "description": "SCSI CDB + LUN + task "
             "attributes (initiator -> target)."},
            {"iu": "FCP_XFER_RDY", "description": "Target signals readiness "
             "for a data burst (target -> initiator)."},
            {"iu": "FCP_DATA", "description": "SCSI data (one or more "
             "sequences, either direction)."},
            {"iu": "FCP_RSP", "description": "SCSI status, sense data, "
             "residual counts (target -> initiator)."}],
    }
    d["ordered_sets"] = {
        "frame_delimiters": ["SOFi1", "SOFn1", "SOFi2", "SOFn2", "SOFi3",
                             "SOFn3", "SOFf", "EOFn", "EOFt", "EOFa"],
        "primitive_signals": ["IDLE", "R_RDY", "ARB"],
        "primitive_sequences": ["NOS", "OLS", "LR", "LRR", "LIP"],
        "note": "Ordered sets are 4-byte transmission words beginning with "
                "the K28.5 special character.",
    }
    d["byte_oriented"] = False
    d["frame_oriented"] = True
    _write(p, d)


# ----------------------------------------------------------------------
# L4 — register/parameter model (login service parameters + FCP).
# ----------------------------------------------------------------------
def _l4(gd: Path) -> None:
    p = gd / "L4_REGMAP.json"
    if not p.is_file():
        return
    d = _read(p)
    d["register_map_present"] = True
    d["notes"] = (
        "Fibre Channel is a frame protocol, not a memory-mapped register "
        "device; its 'register' surface is the set of login service "
        "parameters exchanged via Extended Link Services (FLOGI/PLOGI/PRLI) "
        "and the FCP information units, plus an HBA/controller's "
        "implementation-defined control/status registers. Service parameters "
        "(Common Service Parameters and Class Service Parameters) are carried "
        "in the FLOGI/PLOGI payload.")
    d["service_parameter_groups"] = [
        {"group": "Common Service Parameters (FLOGI/PLOGI payload)",
         "fields": [
             "FC-PH / FC-FS version supported",
             "BB_Credit (buffer-to-buffer credit)",
             "BB_Credit management / receive data field size (max frame "
             "payload, up to 2112 bytes)",
             "N_Port / F_Port indicator and supported classes",
             "64-bit World Wide Node Name (WWNN)",
             "64-bit World Wide Port Name (WWPN)"]},
        {"group": "Class Service Parameters (per Class 1/2/3)", "fields": [
            "Class validity (supported / not supported)",
            "EE_Credit (end-to-end credit, acknowledged classes)",
            "Receive data field size for the class",
            "ACK capability / in-order delivery"]},
        {"group": "FCP Service Parameters (PRLI)", "fields": [
            "Initiator function bit",
            "Target function bit",
            "Read/Write FCP_XFER_RDY disable",
            "Data overlay / retry capability"]},
        {"group": "HBA / controller control-status (implementation-defined)",
         "fields": [
            "Link control (rate select, reset, loopback)",
            "Link status (login state, current 24-bit address, current GFC "
            "rate, BB_Credit)",
            "Error / CRC / loss-of-sync counters",
            "Interrupt / event status (Link Up/Down, RSCN, frame received)"]},
    ]
    d["assigned_24bit_address"] = {
        "note": "Acquired at FLOGI; runtime-readable from the controller as "
                "the current Domain/Area/Port_ID.",
        "bits": _FC_ADDRESS_BITS,
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L5 — analog/physical (FC-0 SerDes signaling, GFC rates, encoding).
# ----------------------------------------------------------------------
def _l5(gd: Path) -> None:
    p = gd / "L5_ADI_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["analog_digital_interface_present"] = True
    d["signaling_summary"] = (
        "FC-0 physical layer: a serial, full-duplex link of one transmit and "
        "one receive lane (differential copper or optical fibre). NRZ "
        "signaling at 1/2/4/8/16/32 GFC and PAM-4 at 64GFC; 128GFC aggregates "
        "four 32GFC lanes. The clock is embedded (recovered at the receiver "
        "with CDR). FC-1 line encoding is 8b/10b (1/2/4/8 GFC) or 64b/66b "
        "(16 GFC and above) with running disparity and word synchronization. "
        "Signaling rate is negotiated to the highest mutually supported rate, "
        "with backward compatibility to lower rates.")
    d["modulation"] = (
        "NRZ at 1/2/4/8/16/32 GFC; PAM-4 at 64GFC; differential/optical, "
        "embedded-clock.")
    d["clocking"] = (
        "Embedded clock recovered by the receiver (clock-data recovery); "
        "spread-spectrum clocking optional. NOT a forwarded/source-synchronous "
        "clock.")
    d["gfc_rate_table"] = [
        {"rate": "1GFC", "gbaud": "1.0625", "encoding": "8b/10b"},
        {"rate": "2GFC", "gbaud": "2.125", "encoding": "8b/10b"},
        {"rate": "4GFC", "gbaud": "4.25", "encoding": "8b/10b"},
        {"rate": "8GFC", "gbaud": "8.5", "encoding": "8b/10b"},
        {"rate": "16GFC", "gbaud": "14.025", "encoding": "64b/66b"},
        {"rate": "32GFC", "gbaud": "28.05", "encoding": "64b/66b"},
        {"rate": "64GFC", "gbaud": "56.1", "encoding": "64b/66b (PAM-4)"},
        {"rate": "128GFC", "gbaud": "4x 28.05", "encoding": "64b/66b, 4 "
         "lanes"},
    ]
    d["transmitter_specs_canonical"] = {
        "rates_GFC": list(_GFC_RATES),
        "modulation": "NRZ (PAM-4 at 64GFC)",
        "signaling": "differential copper or optical",
        "line_encoding": "8b/10b (<=8 GFC) / 64b/66b (>=16 GFC)",
        "embedded_clock": True,
        "interop_rule": "Negotiate the highest common rate; support backward "
                        "compatibility to lower rates.",
    }
    d["receiver_specs_canonical"] = {
        "clock_recovery": "Clock-data recovery (embedded clock).",
        "word_synchronization": "Aligns on the K28.5-based comma character / "
                                "ordered-set boundary.",
        "running_disparity": "Tracked for 8b/10b; 64b/66b uses scrambling + "
                             "sync header.",
    }
    d["encoding_role_in_analog"] = (
        "8b/10b (<=8 GFC) provides DC balance and transition density for "
        "clock recovery and word alignment; 64b/66b (>=16 GFC) uses a 2-bit "
        "sync header plus scrambling for lower overhead at high rate. Frame "
        "integrity is provided digitally by the 32-bit CRC over the FC-2 "
        "frame header + payload.")
    d["crc"] = {"width_bits": _CRC_BITS, "scope": "FC-2 frame header + data "
                "field", "name": "Fibre Channel 32-bit CRC"}
    _write(p, d)


# ----------------------------------------------------------------------
# L6 — control logic / FSMs (link-init primitive-sequence FSM, login FSM,
# loop arbitration, exchange/sequence FSM).
# ----------------------------------------------------------------------
def _l6(gd: Path) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["fsm_states_link_initialization"] = [
        {"name": "OFFLINE", "description": "Link not operational; the port "
         "transmits OLS (Offline) primitive sequence."},
        {"name": "NOS_RECEIVED", "description": "A not-operational partner is "
         "transmitting NOS (Not Operational); begin the primitive-sequence "
         "handshake."},
        {"name": "LINK_RESET", "description": "Port transmits LR (Link "
         "Reset)."},
        {"name": "LINK_RESET_RESPONSE", "description": "Partner responds with "
         "LRR (Link Reset Response)."},
        {"name": "ACTIVE", "description": "Both ends operational; IDLEs "
         "exchanged; frames may flow."},
        {"name": "LOOP_INIT (LIP)", "description": "FC-AL only: loop "
         "initialization resets the loop and assigns 8-bit AL_PAs."},
    ]
    d["fsm_states_login"] = [
        {"name": "LOGGED_OUT", "description": "No fabric/port login; only "
         "link-level primitives."},
        {"name": "FLOGI_SENT", "description": "Fabric login request sent to "
         "0xFFFFFE; awaiting the assigned 24-bit address + service "
         "parameters."},
        {"name": "FABRIC_LOGGED_IN", "description": "FLOGI accepted; the port "
         "holds its 24-bit FC address."},
        {"name": "PLOGI_SENT", "description": "Port login to a peer N_Port or "
         "Name Server; exchanging WWN/EE_Credit/classes."},
        {"name": "PORT_LOGGED_IN", "description": "PLOGI accepted; end-to-end "
         "session established."},
        {"name": "PROCESS_LOGGED_IN", "description": "PRLI accepted; FC-4 "
         "(FCP) session established with negotiated initiator/target roles."},
    ]
    d["fsm_states_loop_arbitration"] = [
        {"name": "MONITORING", "description": "NL_Port watches the loop for "
         "ARB and OPN."},
        {"name": "ARBITRATING", "description": "Transmits ARB(AL_PA) to win "
         "loop access."},
        {"name": "OPEN", "description": "Won arbitration; sends OPN to a "
         "destination AL_PA and opens a loop connection."},
        {"name": "TRANSFER", "description": "Frames flow on the open loop "
         "connection."},
        {"name": "CLOSE", "description": "Sends CLS to close the loop "
         "connection and release the loop."},
    ]
    d["fsm_states_sequence_exchange"] = [
        {"name": "EXCHANGE_OPEN", "description": "Originator allocates OX_ID "
         "and starts the first sequence."},
        {"name": "SEQUENCE_ACTIVE", "description": "Frames of the current "
         "sequence (same SEQ_ID) flow, ordered by SEQ_CNT."},
        {"name": "SEQUENCE_INITIATIVE_TRANSFER", "description": "F_CTL passes "
         "sequence initiative to the other side."},
        {"name": "EXCHANGE_CLOSE", "description": "Last sequence completes; "
         "exchange closed (OX_ID/RX_ID freed)."},
        {"name": "ABORT (ABTS)", "description": "On error, the originator "
         "issues ABTS to abort the sequence/exchange."},
    ]
    d["fsm_hints"] = {
        "trigger": "On power-up a port runs the primitive-sequence link-init "
        "(OLS/NOS -> LR -> LRR -> ACTIVE), then logs in (FLOGI to the fabric "
        "for a 24-bit address, PLOGI to peers, PRLI for FC-4). On FC-AL it "
        "first runs LIP loop initialization and AL_PA assignment.",
        "rule": "Each frame carries SEQ_ID/SEQ_CNT and OX_ID/RX_ID; the "
        "sequence is the unit of recovery; sequence initiative is held by one "
        "side at a time (F_CTL).",
        "abort": "A CRC error / lost frame aborts the sequence; the "
        "originator issues ABTS; persistent link failure drops to the "
        "primitive-sequence protocol to re-initialize.",
    }
    d["anti_deadlock_rule"] = (
        "Credit-based flow control (BB_Credit per link via R_RDY, EE_Credit "
        "end-to-end via ACK) bounds outstanding frames so a slow receiver "
        "cannot overflow; the transmitter blocks on zero credit rather than "
        "dropping frames. Loop arbitration (ARB / access fairness) prevents a "
        "single NL_Port from monopolizing the loop.")
    d["exit_from_reset_or_poweron"] = (
        "Reset/power-up -> OFFLINE (transmit OLS) -> primitive-sequence "
        "handshake (NOS/OLS -> LR -> LRR) -> ACTIVE (exchange IDLEs) -> FLOGI "
        "(fabric, acquire 24-bit address) -> PLOGI/PRLI (sessions). On FC-AL, "
        "LIP loop initialization and AL_PA assignment precede login.")
    d["configurations"] = [
        {"name": "Point-to-point", "description": "Two N_Ports, no fabric; "
         "FLOGI not used (or rejected); direct parameter negotiation."},
        {"name": "Arbitrated loop (FC-AL)", "description": "Up to 126 "
         "NL_Ports share the loop with ARB-based arbitration and 8-bit "
         "AL_PAs."},
        {"name": "Switched fabric", "description": "N_Ports attach to F_Ports "
         "on switches that route by 24-bit address; E_Ports link switches."},
    ]
    d["timing_dependency_rule"] = (
        "FC-0/FC-1 are embedded-clock (receiver CDR), so each direction "
        "self-clocks from the encoded stream; word synchronization aligns on "
        "the K28.5 comma. FC-2 framing, sequence/exchange tracking, credit "
        "accounting, and the login/exchange FSMs run in the controller clock "
        "domain decoupled from the line rate.")
    _write(p, d)


# ----------------------------------------------------------------------
# L7 — test / debug observability.
# ----------------------------------------------------------------------
def _l7(gd: Path) -> None:
    p = gd / "L7_TEST_DEBUG.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_debug_architecture_present"] = True
    d["spec_provided_observability"] = [
        {"name": "Link status / state", "purpose": "Login state, current "
         "24-bit FC address, negotiated GFC rate, BB_Credit, and Link "
         "Up/Down are observable in the controller status registers."},
        {"name": "Loss-of-sync / 8b10b / 64b66b code-violation counters",
         "purpose": "FC-1 error counters surface physical-layer signal "
         "integrity problems."},
        {"name": "CRC error counters", "purpose": "FC-2 32-bit CRC failures "
         "per frame are counted for reliability observability."},
        {"name": "Credit / R_RDY / ACK observability", "purpose": "BB_Credit "
         "and EE_Credit accounting and primitive counts expose flow-control "
         "stalls."},
        {"name": "RSCN / State Change Notification", "purpose": "Fabric "
         "Controller (0xFFFFFD) RSCN events report topology changes."},
        {"name": "Name Server query", "purpose": "Name Server (0xFFFFFC) "
         "queries enumerate the fabric for debug/discovery."},
    ]
    d["error_detection_mechanisms"] = [
        "32-bit CRC over the FC-2 frame header + data field detects frame "
        "corruption.",
        "8b/10b running-disparity / code-violation detection (and 64b/66b "
        "sync-header errors) at FC-1.",
        "Loss-of-synchronization detection at the receiver.",
        "Sequence-count (SEQ_CNT) gap detection for lost/out-of-order frames.",
        "Credit-exhaustion / missing-R_RDY / missing-ACK detection for "
        "flow-control faults.",
        "Login reject (FLOGI/PLOGI/PRLI) for parameter mismatch.",
    ]
    d["test_modes"] = [
        {"name": "Loopback (FC-0/FC-1)", "purpose": "Serial loopback to "
         "characterize the SerDes / encoding without a link partner."},
        {"name": "Link-init test", "purpose": "Exercise the primitive-"
         "sequence protocol (NOS/OLS/LR/LRR) and IDLE exchange."},
        {"name": "Login test", "purpose": "Verify FLOGI/PLOGI/PRLI and "
         "service-parameter negotiation."},
        {"name": "Frame / CRC injection", "purpose": "Inject CRC errors and "
         "verify discard + sequence recovery (ABTS)."},
    ]
    d["interrupt_or_event_sources"] = [
        {"event": "Link Up / Link Down", "trigger": "Primitive-sequence FSM "
         "enters/leaves ACTIVE."},
        {"event": "RSCN", "trigger": "Fabric Controller notifies a topology "
         "change."},
        {"event": "Frame received / sequence complete", "trigger": "FC-2 "
         "delivers a frame / completes a sequence."},
        {"event": "CRC / code-violation error", "trigger": "FC-1/FC-2 error "
         "detection."},
        {"event": "Credit stall", "trigger": "BB_Credit or EE_Credit "
         "exhausted."},
    ]
    d["notes"] = (
        "Fibre Channel observability centers on link state, the FC-1 "
        "code/loss-of-sync counters, the FC-2 CRC counters, credit "
        "accounting, and fabric services (Name Server discovery, Fabric "
        "Controller RSCN). Chip-level JTAG/scan/BIST remain HBA/controller "
        "integrator concerns.")
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
        "FC_STANDARD": "INCITS T11 FC-FS / FC-PH",
        "FRAME_HEADER_BYTES": _FRAME_HEADER_BYTES,
        "MAX_PAYLOAD_BYTES": _MAX_PAYLOAD_BYTES,
        "CRC_WIDTH_BITS": _CRC_BITS,
        "FC_ADDRESS_BITS": _FC_ADDRESS_BITS,
        "DOMAIN_ID_BITS": 8,
        "AREA_ID_BITS": 8,
        "PORT_ID_BITS": 8,
        "WWN_BITS": _WWN_BITS,
        "SEQ_ID_BITS": 8,
        "SEQ_CNT_BITS": 16,
        "OX_ID_BITS": 16,
        "RX_ID_BITS": 16,
        "R_CTL_BITS": 8,
        "TYPE_BITS": 8,
        "F_CTL_BITS": 24,
        "AL_PA_BITS": 8,
        "FCP_TYPE_HEX": "0x08",
        "SIGNALING_RATES_GFC": list(_GFC_RATES),
        "MAX_RATE_GFC": "128GFC",
        "ENCODING_LOW_RATE": "8b/10b (1/2/4/8 GFC)",
        "ENCODING_HIGH_RATE": "64b/66b (16/32/64/128 GFC)",
        "EMBEDDED_CLOCK": True,
        "FORWARDED_CLOCK": False,
    })
    d["frame_format_constants"] = {
        "sof_eof": "FC-1 ordered sets (K28.5-based)",
        "header_bytes": _FRAME_HEADER_BYTES,
        "max_payload_bytes": _MAX_PAYLOAD_BYTES,
        "crc_width_bits": _CRC_BITS,
    }
    d["crc_constants"] = {
        "name": "Fibre Channel 32-bit CRC",
        "width_bits": _CRC_BITS,
        "scope": "FC-2 frame header + data field",
    }
    kc = _ensure_dict(d, "key_constants_for_RTL_authoring")
    kc.update({
        "is_serial": True,
        "is_differential": True,
        "embedded_clock": True,
        "forwarded_clock": False,
        "encoding_low_rate": "8b/10b",
        "encoding_high_rate": "64b/66b",
        "frame_header_bytes": _FRAME_HEADER_BYTES,
        "max_payload_bytes": _MAX_PAYLOAD_BYTES,
        "crc_width_bits": _CRC_BITS,
        "fc_address_bits": _FC_ADDRESS_BITS,
        "wwn_bits": _WWN_BITS,
        "seq_id_bits": 8,
        "seq_cnt_bits": 16,
        "ox_id_bits": 16,
        "rx_id_bits": 16,
        "classes_of_service": list(_CLASSES_OF_SERVICE),
        "flow_control": "BB_Credit (R_RDY) + EE_Credit (ACK)",
        "login_services": list(_LOGIN_SERVICES),
        "fcp_type_hex": "0x08",
        "port_types": list(_PORT_TYPES),
        "topologies": list(_TOPOLOGIES),
        "interop_rule": "negotiate highest common GFC rate; backward "
                        "compatible to lower rates",
    })
    d["default_signal_values_when_idle"] = {
        "line_idle": "Transmit the IDLE ordered set when no frames flow "
                     "(keeps the link synchronized).",
        "not_operational": "Transmit NOS/OLS primitive sequence when the "
                           "link is not operational.",
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
    d["serial_waveform"] = {
        "signaling": "differential / optical NRZ (PAM-4 at 64GFC), "
                     "embedded-clock with receiver CDR.",
        "encoding": "8b/10b (<=8 GFC) or 64b/66b (>=16 GFC).",
        "rates_GFC": list(_GFC_RATES),
        "word_sync": "Receiver aligns on the K28.5 comma / ordered-set "
                     "boundary.",
    }
    d["frame_waveform"] = {
        "structure": "SOF ordered set -> 24-byte header -> payload (<=2112 B) "
                     "-> 32-bit CRC -> EOF ordered set.",
        "delimiters": "SOF/EOF are FC-1 ordered sets bounding each frame.",
        "idle": "IDLE ordered sets fill the link between frames.",
    }
    d["ordered_set_waveform"] = {
        "transmission_word_bytes": 4,
        "leading_char": "K28.5 special character",
        "kinds": ["frame delimiters (SOF/EOF)",
                  "primitive signals (IDLE, R_RDY, ARB)",
                  "primitive sequences (NOS/OLS/LR/LRR/LIP)"],
    }
    d["link_init_transition_trigger_waveform"] = {
        "OFFLINE_to_handshake": "A not-operational port transmits OLS; the "
        "partner transmits NOS.",
        "to_LR": "Port transmits LR (Link Reset).",
        "to_LRR": "Partner responds with LRR (Link Reset Response).",
        "to_ACTIVE": "Both ends operational; exchange IDLEs; frames may flow.",
        "loop_LIP": "FC-AL: LIP resets the loop and triggers AL_PA "
                    "assignment.",
    }
    d["gfc_rate_waveform"] = {
        "rates_GFC": list(_GFC_RATES),
        "gbaud": {"1GFC": "1.0625", "2GFC": "2.125", "4GFC": "4.25",
                  "8GFC": "8.5", "16GFC": "14.025", "32GFC": "28.05",
                  "64GFC": "56.1", "128GFC": "4x 28.05"},
        "modulation": "NRZ (PAM-4 at 64GFC)",
    }
    d["general_timing_rule"] = (
        "Fibre Channel is embedded-clock: each direction self-clocks via "
        "receiver CDR; word synchronization aligns on the K28.5 comma. The "
        "unit interval is set by the negotiated GFC baud rate. FC-2 framing, "
        "credit accounting, and the login/exchange FSMs run in the controller "
        "clock domain decoupled from the line rate.")
    d["voltage_levels"] = {
        "modulation": "NRZ (PAM-4 at 64GFC); differential copper or optical.",
        "termination": "Controlled-impedance differential pair or optical "
                       "transceiver.",
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
        "Fibre Channel controller / host bus adapter (HBA) datapath: a "
        "five-level FC-0..FC-4 stack that frames upper-level-protocol traffic "
        "(FCP=SCSI, FC-NVMe, IP, FICON) into FC-2 frames (24-byte header + "
        "<=2112 B payload + 32-bit CRC), groups them into sequences and "
        "exchanges, applies BB_Credit/EE_Credit flow control and classes of "
        "service, performs FLOGI/PLOGI/PRLI login, and serializes over an "
        "FC-0 SerDes at 1-128 GFC with 8b/10b or 64b/66b encoding.")
    d["topology_description"] = (
        "A full-duplex serial link (one Tx + one Rx lane). Deployed "
        "point-to-point (two N_Ports), as an arbitrated loop (FC-AL, up to "
        "126 NL_Ports), or attached to a switched fabric via F_Ports "
        "(switches route by 24-bit address and interconnect through "
        "E_Ports).")
    io = _ensure_dict(d, "integration_overview")
    io.update({
        "fc_standard": "INCITS T11 FC-FS / FC-PH",
        "signaling_rates_GFC": list(_GFC_RATES),
        "max_rate_GFC": "128GFC",
        "encoding": "8b/10b (<=8 GFC) / 64b/66b (>=16 GFC)",
        "clocking": "embedded (receiver CDR)",
        "frame_header_bytes": _FRAME_HEADER_BYTES,
        "max_payload_bytes": _MAX_PAYLOAD_BYTES,
        "crc_width_bits": _CRC_BITS,
        "fc_address_bits": _FC_ADDRESS_BITS,
        "wwn_bits": _WWN_BITS,
        "classes_of_service": list(_CLASSES_OF_SERVICE),
        "flow_control": "BB_Credit (R_RDY) + EE_Credit (ACK)",
        "login_services": list(_LOGIN_SERVICES),
        "port_types": list(_PORT_TYPES),
        "topologies": list(_TOPOLOGIES),
        "fc4_mappings": ["FCP (SCSI)", "FC-NVMe", "IP over FC", "FICON"],
        "host_side_register_spec": "Login service parameters (FLOGI/PLOGI/"
        "PRLI Common + Class + FCP Service Parameters) plus an HBA/controller "
        "implementation-defined control/status register set.",
    })
    d["interface_categories"] = [
        "FC-4 ULP mapping — FCP (SCSI), FC-NVMe, IP over FC, FICON.",
        "FC-3 common services — striping, hunt groups, multicast.",
        "FC-2 framing/signaling — frame, sequence, exchange, flow control, "
        "classes of service, login.",
        "FC-1 transmission — 8b/10b or 64b/66b encoding, ordered sets.",
        "FC-0 physical — SerDes Tx/Rx, REFCLK, gigabaud signaling.",
    ]
    d["interconnect_topologies_supported"] = list(_TOPOLOGIES)
    d["default_signal_values_when_omitted"] = (
        "Transmit IDLE ordered sets when no frames flow; NOS/OLS when the "
        "link is not operational.")
    d["soc_dependent_items"] = [
        "Port type (N_Port for an end device; F/E_Port for a switch).",
        "Topology (point-to-point / FC-AL / switched fabric).",
        "Maximum GFC rate and encoding (8b/10b vs 64b/66b SerDes).",
        "FC-4 mapping (FCP / FC-NVMe / IP / FICON).",
        "BB_Credit depth (buffer count) and supported classes of service.",
        "WWN assignment (WWNN/WWPN) and zoning.",
        "Optional FCoE encapsulation over lossless Ethernet.",
    ]
    d["device_classes_examples"] = [
        "Host Bus Adapter (HBA) initiator with N_Port",
        "Storage array target with N_Port",
        "Fibre Channel switch (F_Ports + E_Ports)",
        "Arbitrated-loop device (NL_Port) and loop hub (FL_Port)",
        "FC-NVMe storage controller",
        "FCoE Converged Network Adapter (CNA)",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L10 — compliance / test cases.
# ----------------------------------------------------------------------
def _l10(gd: Path) -> None:
    p = gd / "L10_TEST_CASES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_cases_present"] = (
        "partial - the INCITS T11 standard defines conformance behaviors "
        "(FC-0..FC-2 framing/signaling, login, flow control, classes of "
        "service, FC-4 mapping) but the document is a standard, not a "
        "testbench; the categories below are derived from the spec.")
    d["derived_compliance_test_categories"] = [
        "FC-0/FC-1 SerDes + encoding: 8b/10b (<=8 GFC) and 64b/66b "
        "(>=16 GFC), word synchronization, running disparity.",
        "Signaling-rate negotiation: highest common rate among "
        "1/2/4/8/16/32/64/128 GFC with backward compatibility.",
        "Link initialization: primitive-sequence protocol (NOS/OLS/LR/LRR) "
        "and IDLE exchange to ACTIVE.",
        "FC-AL loop initialization (LIP) and 8-bit AL_PA assignment; ARB "
        "arbitration / OPN / CLS.",
        "Frame format: SOF | 24-byte header (R_CTL/D_ID/S_ID/TYPE/F_CTL/"
        "SEQ_ID/SEQ_CNT/OX_ID/RX_ID) | <=2112 B payload | 32-bit CRC | EOF.",
        "32-bit CRC error injection -> frame discard -> sequence recovery "
        "(ABTS).",
        "Sequence/exchange handling: SEQ_ID/SEQ_CNT ordering, OX_ID/RX_ID "
        "exchange, sequence initiative via F_CTL.",
        "Classes of service: Class 1 (connection), Class 2 (acknowledged), "
        "Class 3 (datagram), Class F (inter-switch).",
        "Flow control: BB_Credit (R_RDY) link-by-link and EE_Credit (ACK) "
        "end-to-end; credit exhaustion behavior.",
        "Login: FLOGI (24-bit address assignment), PLOGI (service "
        "parameters), PRLI (FC-4 session), LOGO.",
        "Addressing: 24-bit Domain/Area/Port_ID and well-known service "
        "addresses (Name Server 0xFFFFFC, Fabric Controller 0xFFFFFD).",
        "64-bit WWN (WWNN/WWPN) naming and zoning.",
        "FC-4 FCP: FCP_CMND/XFER_RDY/DATA/RSP IUs, one I/O per exchange, "
        "TYPE=0x08.",
        "Fabric services: Name Server discovery, RSCN State Change "
        "Notification.",
        "FCoE: FC-frame encapsulation in Ethernet (0x8906) + FIP (0x8914) "
        "discovery/login.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L11 — OTP / factory-burned identity (WWN).
# ----------------------------------------------------------------------
def _l11(gd: Path) -> None:
    p = gd / "L11_OTP_CONTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    d["otp_present"] = False
    d["otp_equivalent_factory_burned_fields"] = [
        {"field": "World Wide Node Name (WWNN)", "width_bits": _WWN_BITS,
         "location": "factory-assigned node identifier",
         "note": "Globally unique 64-bit node name, burned in by the "
                 "manufacturer (analogous to a MAC address)."},
        {"field": "World Wide Port Name (WWPN)", "width_bits": _WWN_BITS,
         "location": "factory-assigned per-port identifier",
         "note": "Globally unique 64-bit port name used for naming, zoning, "
                 "and authentication."},
        {"field": "Supported maximum GFC rate",
         "width_bits": "implementation-defined",
         "location": "controller capability",
         "note": "Advertised during speed negotiation / login."},
    ]
    d["notes"] = (
        "Fibre Channel does not define OTP/fuse content as a protocol "
        "concept, but the 64-bit World Wide Names (WWNN/WWPN) are permanent, "
        "factory-assigned, globally unique identifiers — the functional "
        "equivalent of burned-in identity — exchanged at login (FLOGI/PLOGI) "
        "and used for naming, zoning, and authentication. The 24-bit FC "
        "address, by contrast, is assigned dynamically by the fabric at "
        "FLOGI, not burned in.")
    _write(p, d)


# ----------------------------------------------------------------------
# L12 — behavioral sequences (link bring-up, login, FCP I/O, loop,
# error recovery).
# ----------------------------------------------------------------------
def _l12(gd: Path) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["link_bring_up_sequence"] = [
        "1. Power-up: port is OFFLINE, transmits OLS (Offline) primitive "
        "sequence.",
        "2. Primitive-sequence handshake: NOS/OLS -> LR (Link Reset) -> LRR "
        "(Link Reset Response).",
        "3. ACTIVE: both ends operational; IDLE ordered sets exchanged; word "
        "synchronization achieved.",
        "4. (Switched fabric) FLOGI to 0xFFFFFE: the fabric assigns the "
        "24-bit FC address and exchanges service parameters (BB_Credit, "
        "classes, max frame size).",
        "5. PLOGI to peer N_Port (or Name Server 0xFFFFFC): exchange "
        "WWN/EE_Credit/classes/max payload; establish the end-to-end "
        "session.",
        "6. PRLI: establish the FC-4 (FCP) session; negotiate "
        "initiator/target roles.",
    ]
    d["loop_initialization_sequence"] = [
        "1. (FC-AL) A port forces LIP to reset the loop.",
        "2. Loop initialization selects a master and assigns 8-bit AL_PAs to "
        "all NL_Ports.",
        "3. A port arbitrates with ARB(AL_PA); on winning it sends OPN to a "
        "destination AL_PA, transfers frames, then CLS to release the loop.",
    ]
    d["fcp_io_sequence"] = [
        "1. Initiator opens an exchange (allocate OX_ID) and sends FCP_CMND "
        "(SCSI CDB + LUN) as one sequence; TYPE=0x08.",
        "2. (Write) Target returns FCP_XFER_RDY indicating it is ready for a "
        "data burst.",
        "3. FCP_DATA sequences transfer the SCSI data (initiator->target for "
        "write, target->initiator for read).",
        "4. Target returns FCP_RSP with SCSI status, sense, and residual; the "
        "exchange closes.",
    ]
    d["frame_transmission_sequence"] = [
        "1. FC-2 builds a frame: SOF | 24-byte header (SEQ_ID/SEQ_CNT, "
        "OX_ID/RX_ID, D_ID/S_ID) | payload | 32-bit CRC | EOF.",
        "2. The transmitter consumes BB_Credit (must have an R_RDY-granted "
        "buffer) before sending.",
        "3. FC-1 encodes (8b/10b or 64b/66b); FC-0 serializes at the "
        "negotiated GFC rate.",
        "4. Receiver recovers the clock, word-synchronizes, decodes, checks "
        "the 32-bit CRC, and returns R_RDY for the freed buffer.",
        "5. (Acknowledged classes) the destination returns an ACK to "
        "replenish EE_Credit.",
    ]
    d["error_recovery_sequence"] = [
        "1. A bad-CRC, lost, or out-of-order frame fails the sequence.",
        "2. The exchange originator issues ABTS (Abort Sequence) to abort "
        "the sequence/exchange.",
        "3. The recipient responds (BA_ACC / BA_RJT); the FC-4 ULP (e.g. FCP "
        "retry) re-drives the operation.",
        "4. Persistent link failure drops to the primitive-sequence protocol "
        "(NOS/OLS -> LR -> LRR) to re-initialize.",
    ]
    d["reset_sequence"] = [
        "1. Reset asserted -> OFFLINE (transmit OLS).",
        "2. Reset deasserted -> primitive-sequence handshake -> ACTIVE -> "
        "FLOGI/PLOGI/PRLI re-login.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L13 — lab calibration / characterization.
# ----------------------------------------------------------------------
def _l13(gd: Path) -> None:
    p = gd / "L13_LAB_CALIBRATION.json"
    if not p.is_file():
        return
    d = _read(p)
    d["lab_calibration_present"] = False
    d["lab_measurement_targets_from_spec"] = [
        {"name": "Serial eye / jitter at the target GFC rate", "purpose": "FC-0 "
         "transmitter/receiver compliance at 1/2/4/8/16/32/64 GFC (NRZ, PAM-4 "
         "at 64GFC)."},
        {"name": "Receiver CDR lock / word synchronization", "purpose": "Verify "
         "embedded-clock recovery and K28.5 comma alignment."},
        {"name": "8b/10b and 64b/66b code integrity", "purpose": "Running "
         "disparity (8b/10b) and sync-header/scrambling (64b/66b) "
         "correctness."},
        {"name": "Link initialization", "purpose": "Primitive-sequence "
         "protocol (NOS/OLS/LR/LRR) and IDLE exchange to ACTIVE."},
        {"name": "32-bit CRC", "purpose": "Inject errors and confirm frame "
         "discard + sequence recovery (ABTS)."},
        {"name": "Credit flow control", "purpose": "BB_Credit (R_RDY) and "
         "EE_Credit (ACK) accounting, including long-distance BB_Credit."},
        {"name": "Login + addressing", "purpose": "FLOGI 24-bit-address "
         "assignment, PLOGI/PRLI parameter negotiation, WWN exchange."},
    ]
    d["notes"] = (
        "Fibre Channel characterization centers on the FC-0 SerDes (eye/"
        "jitter at the GFC rate), FC-1 encoding (8b/10b / 64b/66b, word "
        "sync), FC-2 framing/CRC/credit, and the login protocol. Conformance "
        "follows the INCITS T11 standards (FC-FS framing/signaling, FC-LS "
        "link services, FC-SW switch fabric, FC-GS generic services, FCP).")
    _write(p, d)


# ----------------------------------------------------------------------
# L14 — protocol versioning (INCITS T11 family).
# ----------------------------------------------------------------------
def _l14(gd: Path) -> None:
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["spec_version"] = (
        "INCITS T11 Fibre Channel Framing and Signaling (FC-FS) / Physical "
        "and Signaling Interface (FC-PH)")
    f["previous_versions"] = [
        "FC-PH (ANSI X3.230) — original Physical and Signaling Interface: "
        "FC-0/FC-1/FC-2, frame/sequence/exchange, classes of service, login.",
        "FC-FS / FC-FS-2 / FC-FS-3 / FC-FS-4 / FC-FS-5 — successive Framing "
        "and Signaling revisions adding higher GFC rates and 64b/66b "
        "encoding.",
    ]
    f["key_changes"] = [
        {"version": "FC-PH", "summary": "Defined the original Fibre Channel "
         "physical and signaling interface: FC-0 media/rates, FC-1 8b/10b "
         "encoding and ordered sets, FC-2 frame/sequence/exchange, classes of "
         "service 1/2/3, and the login protocol."},
        {"version": "FC-FS (and -2..-5)", "summary": "Consolidated FC-1/FC-2 "
         "framing and signaling; added 16/32/64/128 GFC rates and 64b/66b "
         "encoding while preserving the 24-byte frame header, sequence/"
         "exchange model, classes of service, BB_Credit/EE_Credit, and "
         "FLOGI/PLOGI/PRLI login."},
    ]
    f["related_standards"] = [
        "FC-LS — Link Services (Extended/Basic Link Services incl. FLOGI/"
        "PLOGI/PRLI/LOGO).",
        "FC-SW — Switch Fabric (E_Port / inter-switch routing).",
        "FC-GS — Generic Services (Name Server, Management Server).",
        "FCP — Fibre Channel Protocol for SCSI (FC-4 mapping).",
        "FC-BB — Backbone, including FCoE (FC over Ethernet).",
    ]
    f["backward_compat_traps"] = [
        {"trap_name": "Encoding_changes_at_16GFC",
         "rule": "8b/10b is used at 1/2/4/8 GFC; 64b/66b at 16 GFC and "
                 "above.",
         "trap": "Assuming 8b/10b at all rates is wrong; a 16GFC-or-faster "
                 "link uses 64b/66b with a different sync/scrambling model."},
        {"trap_name": "Class_3_has_no_ACK",
         "rule": "Class 3 is connectionless datagram with BB_Credit only — no "
                 "ACK and no EE_Credit.",
         "trap": "Expecting end-to-end acknowledgement in Class 3 (the common "
                 "SCSI class) is wrong; reliability is left to the ULP."},
        {"trap_name": "24bit_address_is_assigned_not_fixed",
         "rule": "The 24-bit FC address is assigned by the fabric at FLOGI; "
                 "the 64-bit WWN is the permanent identity.",
         "trap": "Treating the 24-bit address as a fixed device identity "
                 "breaks across fabric re-logins; use the WWN for "
                 "persistence."},
        {"trap_name": "FLOGI_only_in_fabric",
         "rule": "FLOGI is used to log in to a switched fabric; "
                 "point-to-point / loop without a fabric negotiate "
                 "directly.",
         "trap": "Requiring FLOGI on a direct point-to-point link is wrong."},
        {"trap_name": "Payload_max_2112",
         "rule": "The FC-2 data field is at most 2112 bytes.",
         "trap": "Assuming arbitrary frame size breaks segmentation; large "
                 "transfers are split across a sequence of frames."},
    ]
    f["version_naming_history_note"] = (
        "Fibre Channel is standardized by the INCITS T11 technical committee "
        "(formerly ANSI X3T11). FC-PH (ANSI X3.230) defined the original "
        "physical and signaling interface; the FC-FS series consolidated and "
        "extended FC-1/FC-2 framing and signaling and raised rates to "
        "16/32/64/128 GFC with 64b/66b encoding. Companion standards FC-LS "
        "(link services), FC-SW (switch fabric), FC-GS (generic services), "
        "FCP (SCSI mapping), and FC-BB (FCoE) complete the family.")
    _write(p, d)


# ----------------------------------------------------------------------
# L15 — encoding tables (GFC rates, frame header, classes, login, ordered
# sets, well-known addresses).
# ----------------------------------------------------------------------
def _l15(gd: Path) -> None:
    p = gd / "L15_ENCODING_TABLES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["gfc_rate_table"] = {
        "header_columns": ["Rate", "Gigabaud (approx)", "FC-1 Encoding"],
        "rows": [
            ["1GFC", "1.0625", "8b/10b"],
            ["2GFC", "2.125", "8b/10b"],
            ["4GFC", "4.25", "8b/10b"],
            ["8GFC", "8.5", "8b/10b"],
            ["16GFC", "14.025", "64b/66b"],
            ["32GFC", "28.05", "64b/66b"],
            ["64GFC", "56.1", "64b/66b (PAM-4)"],
            ["128GFC", "4x 28.05", "64b/66b, 4 lanes"],
        ],
    }
    f["frame_header_table"] = {
        "header_columns": ["Field", "Bytes", "Meaning"],
        "rows": [
            ["R_CTL", "1", "Routing Control (frame/information category)"],
            ["D_ID", "3", "Destination 24-bit FC address"],
            ["CS_CTL/Priority", "1", "Class-specific control / priority"],
            ["S_ID", "3", "Source 24-bit FC address"],
            ["TYPE", "1", "FC-4 protocol type (0x08 = FCP)"],
            ["F_CTL", "3", "Frame Control bits"],
            ["SEQ_ID", "1", "Sequence Identifier"],
            ["DF_CTL", "1", "Data Field Control (optional headers)"],
            ["SEQ_CNT", "2", "Sequence Count"],
            ["OX_ID", "2", "Originator Exchange ID"],
            ["RX_ID", "2", "Responder Exchange ID"],
            ["Parameter", "4", "Relative offset / link-control parameter"],
        ],
    }
    f["classes_of_service_table"] = {
        "header_columns": ["Class", "Connection", "Acknowledged", "Credit"],
        "rows": [
            ["Class 1", "Dedicated connection", "Yes", "EE_Credit"],
            ["Class 2", "Connectionless", "Yes", "BB + EE_Credit"],
            ["Class 3", "Connectionless (datagram)", "No", "BB_Credit only"],
            ["Class F", "Inter-switch (E_Port)", "Yes", "fabric internal"],
        ],
    }
    f["login_services_table"] = {
        "header_columns": ["ELS", "Name", "Purpose"],
        "rows": [
            ["FLOGI", "Fabric Login", "Acquire 24-bit address + service "
             "parameters from the fabric"],
            ["PLOGI", "Port Login", "Exchange WWN/EE_Credit/classes with a "
             "peer N_Port or service"],
            ["PRLI", "Process Login", "Establish the FC-4 (FCP) session"],
            ["LOGO", "Logout", "Tear down a login"],
        ],
    }
    f["ordered_set_table"] = {
        "header_columns": ["Kind", "Examples", "Purpose"],
        "rows": [
            ["Frame delimiter", "SOFi1/SOFn1/SOFi2/SOFn2/SOFi3/SOFn3/SOFf, "
             "EOFn/EOFt/EOFa", "Bound each frame (start/end)"],
            ["Primitive signal", "IDLE, R_RDY, ARB", "Standalone meaning "
             "(idle, buffer credit, loop arbitration)"],
            ["Primitive sequence", "NOS, OLS, LR, LRR, LIP", "Repeated set "
             "signaling a link condition / initialization"],
        ],
    }
    f["well_known_address_table"] = {
        "header_columns": ["Address", "Service"],
        "rows": [
            ["0xFFFFFE", "Fabric F_Port (FLOGI)"],
            ["0xFFFFFD", "Fabric Controller (RSCN)"],
            ["0xFFFFFC", "Name Server (discovery)"],
            ["0xFFFFFB", "Time Server"],
            ["0xFFFFFA", "Management Server"],
            ["0xFFFFFF", "Broadcast"],
        ],
    }
    f["fc4_type_table"] = {
        "header_columns": ["TYPE", "FC-4 Protocol"],
        "rows": [
            ["0x08", "FCP (SCSI)"],
            ["0x05", "IP over Fibre Channel"],
            ["0x20", "FC-CT (Common Transport, e.g. Name Server)"],
        ],
    }
    f["encoding_note"] = (
        "FC-1 uses 8b/10b at 1/2/4/8 GFC (running disparity, DC balance for "
        "clock recovery) and 64b/66b at 16 GFC and above (2-bit sync header + "
        "scrambling for low overhead). Ordered sets are 4-byte K28.5-based "
        "transmission words. Frame integrity is a 32-bit CRC over the FC-2 "
        "header + data field.")
    f["tables"] = [
        "GFC signaling-rate / encoding table (1-128 GFC)",
        "24-byte FC-2 frame header field table",
        "Classes-of-service table (1/2/3/F)",
        "Login Extended-Link-Services table (FLOGI/PLOGI/PRLI/LOGO)",
        "Ordered-set table (delimiters / signals / sequences)",
        "Well-known fabric service address table",
        "FC-4 TYPE table",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L16 — compliance properties / distinguishers.
# ----------------------------------------------------------------------
def _l16(gd: Path) -> None:
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["must_have_properties"] = [
        "Five-level FC-0..FC-4 architecture (physical / encoding / framing / "
        "common services / ULP mapping).",
        "Port types N_Port / F_Port / E_Port (and loop NL_Port / FL_Port) "
        "with point-to-point, FC-AL, and switched-fabric topologies.",
        "24-bit Fibre Channel address identifier (Domain/Area/Port) assigned "
        "at FLOGI, plus a 64-bit World Wide Name.",
        "FC-2 frame: SOF | 24-byte header (R_CTL/D_ID/S_ID/TYPE/F_CTL/SEQ_ID/"
        "SEQ_CNT/OX_ID/RX_ID) | <=2112 B payload | 32-bit CRC | EOF.",
        "Sequence (SEQ_ID/SEQ_CNT) and exchange (OX_ID/RX_ID) hierarchy with "
        "F_CTL sequence initiative.",
        "Classes of service 1/2/3/F.",
        "Buffer-to-buffer credit (BB_Credit, R_RDY) and end-to-end credit "
        "(EE_Credit, ACK) flow control.",
        "Login protocol FLOGI/PLOGI/PRLI (and LOGO) via Extended Link "
        "Services.",
        "FC-1 8b/10b (<=8 GFC) or 64b/66b (>=16 GFC) encoding with ordered "
        "sets (SOF/EOF, IDLE/R_RDY, NOS/OLS/LR/LRR).",
        "At least one FC-4 mapping (typically FCP for SCSI, TYPE=0x08).",
        "Well-known fabric service addresses (Name Server 0xFFFFFC, Fabric "
        "Controller 0xFFFFFD).",
    ]
    f["must_not_have_properties"] = [
        "A forwarded/source-synchronous mainband clock (Fibre Channel is "
        "embedded-clock with receiver CDR).",
        "SAS SSP/STP/SMP transports, expander devices, or a 64-bit SAS "
        "address (that is SAS, not FC).",
        "AHCI/FIS host-device-only framing with no N_Port/FLOGI/exchange "
        "(that is SATA).",
        "An 802.3 MAC/MII Ethernet frame as the native FC-2 frame (FCoE "
        "encapsulates the FC frame; it does not replace it).",
        "InfiniBand Queue Pairs / LIDs / Virtual Lanes / Subnet Manager "
        "(that is InfiniBand).",
        "Frame payloads larger than 2112 bytes.",
    ]
    f["compliance_failure_modes"] = [
        {"mode": "Link-init failure", "trigger": "Primitive-sequence "
         "protocol (NOS/OLS/LR/LRR) never reaches ACTIVE."},
        {"mode": "Login reject", "trigger": "FLOGI/PLOGI/PRLI parameter "
         "mismatch; no 24-bit address or session."},
        {"mode": "CRC error storm", "trigger": "Persistent 32-bit CRC "
         "failures abort sequences (ABTS)."},
        {"mode": "Credit stall", "trigger": "BB_Credit / EE_Credit exhaustion "
         "blocks transmission."},
        {"mode": "Rate/encoding mismatch", "trigger": "Speed negotiation "
         "fails or 8b/10b-vs-64b/66b mismatch at 16 GFC boundary."},
        {"mode": "Class mismatch", "trigger": "Two ports do not share a "
         "common class of service."},
    ]
    f["min_link_constraint"] = (
        "A link must reach ACTIVE via the primitive-sequence protocol at a "
        "mutually supported GFC rate, then complete login (FLOGI in a fabric, "
        "or direct negotiation point-to-point/loop), with a shared class of "
        "service and non-zero BB_Credit; otherwise it cannot carry frames.")
    f["reset_behavior_compliance"] = (
        "Reset deassertion drives OFFLINE (OLS) -> primitive-sequence "
        "handshake (NOS/OLS -> LR -> LRR) -> ACTIVE -> FLOGI/PLOGI/PRLI "
        "re-login; FC-AL re-runs LIP and AL_PA assignment first.")
    f["fibre_channel_distinguishers"] = (
        "Fibre Channel is identified by ALL of: the five-level FC-0..FC-4 "
        "architecture; the N_Port/F_Port/E_Port port-type vocabulary with "
        "point-to-point / arbitrated-loop (FC-AL) / switched-fabric "
        "topologies; the FC-2 frame with a 24-byte header "
        "(R_CTL/D_ID/S_ID/TYPE/F_CTL/SEQ_ID/SEQ_CNT/OX_ID/RX_ID), <=2112 B "
        "payload, and 32-bit CRC; the sequence (SEQ_ID/SEQ_CNT) and exchange "
        "(OX_ID/RX_ID) hierarchy; classes of service 1/2/3/F; BB_Credit + "
        "EE_Credit flow control; the FLOGI/PLOGI/PRLI login protocol; a "
        "24-bit FC address + 64-bit WWN; and FC-4 mappings such as FCP "
        "(SCSI). This is distinct from SAS (SSP/STP/SMP + expander + SAS "
        "address), SATA (AHCI/FIS host-device), Ethernet (802.3 MAC/MII), "
        "and InfiniBand (Queue Pairs/LID/Virtual Lanes/Subnet Manager).")
    _write(p, d)


# ----------------------------------------------------------------------
# L17 — channel / signal catalog (FORCE-OVERWRITE).
# ----------------------------------------------------------------------
def _l17(gd: Path) -> None:
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["channels"] = [
        {"name": "Transmit serial lane (TX)",
         "direction": "unidirectional (output)",
         "purpose": "FC-0 transmit lane carrying encoded frames + ordered "
                    "sets.",
         "active_levels": "differential / optical NRZ (PAM-4 at 64GFC) at the "
         "negotiated GFC rate", "idle_level": "IDLE ordered sets"},
        {"name": "Receive serial lane (RX)",
         "direction": "unidirectional (input)",
         "purpose": "FC-0 receive lane recovering encoded frames + ordered "
                    "sets (embedded-clock CDR).",
         "active_levels": "differential / optical NRZ (PAM-4 at 64GFC)",
         "idle_level": "IDLE ordered sets"},
        {"name": "REFCLK", "direction": "input",
         "purpose": "Reference clock for the SerDes.",
         "active_levels": "reference oscillator", "idle_level": "free-"
         "running"},
        {"name": "Power / ground (analog + digital)", "direction": "supply",
         "purpose": "SerDes analog rails and digital core supply.",
         "active_levels": "DC rails", "idle_level": "n/a; always driven"},
    ]
    f["logical_signaling_levels"] = [
        {"name": "Active frame", "meaning": "SOF .. 24-byte header .. payload "
         ".. 32-bit CRC .. EOF on the serial lane."},
        {"name": "Idle", "meaning": "IDLE ordered sets between frames "
         "(maintains synchronization)."},
        {"name": "Not operational", "meaning": "NOS/OLS primitive sequence "
         "when the link is down."},
    ]
    f["packet_types_summary"] = [
        {"class": "Ordered sets", "members": ["frame delimiters (SOF/EOF)",
         "primitive signals (IDLE/R_RDY/ARB)",
         "primitive sequences (NOS/OLS/LR/LRR/LIP)"], "count": 3},
        {"class": "Classes of service",
         "members": list(_CLASSES_OF_SERVICE), "count": 4},
        {"class": "Login ELS", "members": list(_LOGIN_SERVICES), "count": 4},
    ]
    cc = _ensure_dict(f, "channel_counts")
    cc["serial_lanes_per_link"] = 2
    cc["port_types"] = len(_PORT_TYPES)
    cc["classes_of_service"] = len(_CLASSES_OF_SERVICE)
    f["frame_header_bytes"] = _FRAME_HEADER_BYTES
    f["max_payload_bytes"] = _MAX_PAYLOAD_BYTES
    f["crc_width_bits"] = _CRC_BITS
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
    f["topologies"] = [
        {"name": "Point-to-point", "description": "Direct N_Port-to-N_Port "
         "link between two devices; full bandwidth dedicated; no fabric / no "
         "FLOGI."},
        {"name": "Arbitrated Loop (FC-AL)", "description": "Up to 126 "
         "NL_Ports (plus an optional FL_Port) share a loop; ARB-based "
         "arbitration; 8-bit AL_PAs assigned at LIP."},
        {"name": "Switched Fabric", "description": "N_Ports attach to F_Ports "
         "on switches that route frames by 24-bit address; switches "
         "interconnect via E_Ports (Inter-Switch Links); fabric services "
         "(Name Server, Fabric Controller, Management Server)."},
    ]
    f["port_types"] = [
        {"port": "N_Port", "role": "Node port on an end device (HBA / "
         "target)."},
        {"port": "F_Port", "role": "Fabric port on a switch attaching an "
         "N_Port."},
        {"port": "E_Port", "role": "Expansion / inter-switch port (ISL "
         "between switches)."},
        {"port": "NL_Port", "role": "Node loop port (arbitrated loop)."},
        {"port": "FL_Port", "role": "Fabric loop port (loop attached to a "
         "fabric)."},
        {"port": "G_Port", "role": "Generic switch port that becomes F or E "
         "after discovery."},
    ]
    f["addressing"] = {
        "fc_address_bits": _FC_ADDRESS_BITS,
        "structure": "Domain_ID (23..16) / Area_ID (15..8) / Port_ID (7..0)",
        "assigned_at": "FLOGI",
        "wwn_bits": _WWN_BITS,
        "max_fabric_ports": "up to ~16 million (24-bit address space)",
        "loop_addresses": "8-bit AL_PA, up to 126 NL_Ports + 1 FL_Port",
    }
    f["fabric_services"] = [
        {"service": "Name Server", "address": "0xFFFFFC",
         "purpose": "Device discovery and name-to-address resolution."},
        {"service": "Fabric Controller", "address": "0xFFFFFD",
         "purpose": "State Change Notification (RSCN)."},
        {"service": "Management Server", "address": "0xFFFFFA",
         "purpose": "Fabric management."},
        {"service": "Fabric F_Port", "address": "0xFFFFFE",
         "purpose": "FLOGI target."},
    ]
    f["notes"] = (
        "Fibre Channel scales from a single point-to-point link, through a "
        "shared arbitrated loop (FC-AL, up to 126 NL_Ports), to a switched "
        "fabric of millions of addressable ports interconnected by E_Port "
        "Inter-Switch Links and discovered through the Name Server.")
    _write(p, d)


# ----------------------------------------------------------------------
# L19 — constraints / PDK (frame protocol → mostly N/A).
# ----------------------------------------------------------------------
def _l19(gd: Path) -> None:
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["constraints_present"] = False
    f["protocol_timing_constraints"] = [
        "FC-0 SerDes meets the eye/jitter mask at the negotiated GFC rate "
        "(1/2/4/8/16/32/64 GFC; 128GFC = 4 lanes).",
        "Receiver CDR locks and word-synchronizes on the K28.5 comma.",
        "FC-2 framing, CRC, and credit logic run in the controller clock "
        "domain decoupled from the line rate.",
    ]
    f["notes"] = (
        "Fibre Channel is a protocol/interface standard; PDK/physical "
        "constraints are implementation-specific to the HBA/controller "
        "silicon and the chosen SerDes. The protocol fixes the encoding "
        "(8b/10b / 64b/66b), the 24-byte frame header, the 2112-byte payload "
        "cap, and the 32-bit CRC.")
    _write(p, d)


# ----------------------------------------------------------------------
# L20 — DFT / scan (implementation-defined).
# ----------------------------------------------------------------------
def _l20(gd: Path) -> None:
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["dft_present"] = False
    f["spec_provided_test_features"] = [
        "FC-0/FC-1 serial loopback for SerDes / encoding characterization.",
        "Link-init (NOS/OLS/LR/LRR) and IDLE exchange as a functional "
        "self-test.",
        "Login (FLOGI/PLOGI/PRLI) and CRC-error injection as functional "
        "tests.",
    ]
    f["notes"] = (
        "Fibre Channel defines protocol-level test features (loopback, "
        "link-init, login, CRC injection); chip-level DFT (scan, BIST, JTAG) "
        "is an HBA/controller integrator concern, not part of the protocol "
        "standard.")
    _write(p, d)


# ----------------------------------------------------------------------
# L21 — power intent (implementation-defined).
# ----------------------------------------------------------------------
def _l21(gd: Path) -> None:
    p = gd / "L21_POWER_INTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["power_intent_present"] = False
    f["power_relevant_features"] = [
        "Link rate scaling (1-128 GFC) trades power for bandwidth.",
        "OFFLINE / not-operational state (OLS) when the link is idle/down.",
        "Optical vs copper FC-0 media have different transceiver power "
        "profiles.",
    ]
    f["notes"] = (
        "Fibre Channel does not define a formal low-power/power-intent "
        "framework as a protocol concept; power is an HBA/controller and "
        "transceiver implementation concern. The dominant knobs are the "
        "selected GFC rate and the media (copper vs optical).")
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
        "FC-0/FC-1 SerDes + encoding (8b/10b <=8 GFC, 64b/66b >=16 GFC), word "
        "sync, running disparity.",
        "Signaling-rate negotiation across 1/2/4/8/16/32/64/128 GFC.",
        "Link initialization: NOS/OLS/LR/LRR primitive-sequence protocol to "
        "ACTIVE.",
        "FC-AL loop init (LIP), AL_PA assignment, ARB/OPN/CLS.",
        "Frame format + 24-byte header field coverage "
        "(R_CTL/D_ID/S_ID/TYPE/F_CTL/SEQ_ID/SEQ_CNT/OX_ID/RX_ID).",
        "32-bit CRC error injection -> discard -> ABTS recovery.",
        "Sequence (SEQ_ID/SEQ_CNT) and exchange (OX_ID/RX_ID) handling; "
        "sequence initiative.",
        "Classes of service 1/2/3/F.",
        "Flow control: BB_Credit (R_RDY) and EE_Credit (ACK), credit "
        "exhaustion.",
        "Login: FLOGI 24-bit-address assignment, PLOGI/PRLI parameter "
        "negotiation.",
        "Addressing: 24-bit Domain/Area/Port and well-known service "
        "addresses.",
        "64-bit WWN (WWNN/WWPN) naming.",
        "FC-4 FCP I/O: FCP_CMND/XFER_RDY/DATA/RSP, one exchange per I/O, "
        "TYPE=0x08.",
        "Fabric services: Name Server discovery, RSCN.",
        "FCoE encapsulation (0x8906) + FIP (0x8914).",
    ]
    f["notes"] = (
        "Fibre Channel does not ship a testbench, but the INCITS T11 "
        "standards imply a verification plan spanning FC-0..FC-2 (SerDes, "
        "encoding, framing, CRC, credit), login/addressing, classes of "
        "service, and the FC-4 mapping (FCP). Conformance follows the FC-FS / "
        "FC-LS / FC-SW / FC-GS / FCP standards.")
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
        "32-bit CRC over the FC-2 frame header + data field detects frame "
        "corruption.",
        "8b/10b running-disparity / 64b/66b sync-header detection catches "
        "code violations.",
        "Sequence-count (SEQ_CNT) ordering detects lost/out-of-order frames; "
        "ABTS recovers the sequence/exchange.",
        "Credit-based flow control prevents receiver buffer overflow.",
    ]
    f["anti_tampering_features"] = []
    f["confidentiality_features"] = []
    f["authentication_features"] = [
        "World Wide Name (WWN) based zoning and authentication identify "
        "permitted ports.",
        "FC-SP (Fibre Channel Security Protocol, a companion INCITS T11 "
        "standard) adds DH-CHAP / FCAP authentication and ESP_Header frame "
        "encryption above the base data path.",
    ]
    f["future_security_pointers"] = [
        "FC-SP-2 provides authentication (DH-CHAP, FCAP) and per-frame "
        "confidentiality/integrity (ESP_Header) for hardened fabrics.",
        "Fabric zoning (hard/soft) restricts which WWNs/ports may "
        "communicate.",
    ]
    f["notes"] = (
        "Base Fibre Channel (FC-FS) provides anti-corruption only (32-bit "
        "CRC, code-violation detection, sequence recovery, credit flow "
        "control); the native frame is not encrypted. WWN-based zoning "
        "restricts connectivity, and the companion FC-SP standard adds "
        "authentication (DH-CHAP/FCAP) and frame-level confidentiality/"
        "integrity (ESP_Header) for environments that require it.")
    _write(p, d)
