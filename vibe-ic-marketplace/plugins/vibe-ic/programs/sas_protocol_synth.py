"""Serial Attached SCSI (SAS) protocol synth helper (protocol #53).

ic_class-gated overlay for the SAS structural signature: a point-to-point,
full-duplex, serial differential storage interconnect (phy) standardized by
INCITS T10, that multiplexes THREE transport protocols over the phy — SSP
(Serial SCSI Protocol, SCSI commands), STP (SATA Tunneling Protocol, bridging
SATA devices), and SMP (Serial Management Protocol, expander topology
management) — aggregates phys with the same 64-bit SAS address into wide ports,
grows the topology through edge/fanout expander devices into a SAS domain, is
connection-oriented at the link layer (OPEN address frame, AIP, OPEN_ACCEPT /
OPEN_REJECT, arbitration wait time, rate matching via ALIGN), runs at 3/6/12/
22.5 Gbps (8b10b <=6 Gbps, 128b150b with FEC capability at 12/22.5 Gbps), uses
RRDY/ACK/NAK flow control with a 32-bit CRC and scrambling, and negotiates the
link with OOB (COMINIT/COMSAS/COMWAKE) + the Speed Negotiation Window (SNW).
Applies the INCITS T10 SAS (SAS-3 / SAS-4) spec-canonical content to L1-L23.

Doctrine — GENERAL not keyword: detection uses canonical STRUCTURAL signatures
(SSP + STP + SMP transports + expander + 64-bit SAS address + wide port +
connection / OPEN address frame) read from the L-doc / input_doc CONTENT blob
only. It NEVER reads the input-document filename or the benchmark folder name.

Sibling disambiguation — SAS vs SATA and NVMe (the storage family). SAS, SATA
and NVMe are all storage interconnects, but only SAS has the SSP/STP/SMP triple
transport, expander devices, a 64-bit SAS address, and wide-port aggregation.
SATA is a single host-to-device link (FIS / AHCI, host-device, no expander, no
SSP/SMP, no SAS address); NVMe is a register-level command set over PCI Express
(submission/completion queues + doorbells + namespaces, no SCSI, no expander).
The detector REQUIRES the SAS-only structural vocabulary and DEFERS when the
doc is SATA-primary (FIS/AHCI/host-device only, no expander/SSP/SMP/SAS-address)
or NVMe-primary (submission/completion queue + doorbell + PCIe, no SCSI /
expander), so it cannot false-fire on a SATA or NVMe spec.

Public entry: ``apply_sas_synth(generated_docs_dir, is_sas, sas_ic_name)``.
Module-level ``is_sas(blob)`` is the content-only detector.
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

# Canonical SAS facts (INCITS T10 Serial Attached SCSI, SAS-3 / SAS-4).
_LINK_RATES_GBPS = [1.5, 3, 6, 12, 22.5]
_MAX_LINK_RATE_GBPS = 22.5
_SAS_ADDRESS_BITS = 64
_CRC_BITS = 32
_TRANSPORTS = ["SSP", "STP", "SMP"]
_SSP_FRAME_TYPES = ["COMMAND", "TASK", "XFER_RDY", "DATA", "RESPONSE"]
_PRIMITIVES = [
    "ALIGN", "NOTIFY", "SOF", "EOF", "SOAF", "EOAF", "RRDY", "ACK", "NAK",
    "CREDIT_BLOCKED", "OPEN_ACCEPT", "OPEN_REJECT", "AIP", "CLOSE", "BREAK",
    "DONE", "HARD_RESET",
]


def is_sas(blob: str) -> bool:
    """Content-only SAS detector with a SATA / NVMe sibling MUTEX.

    Fire on the SAS structural signature: the SSP + STP + SMP triple transport
    + expander devices + a 64-bit SAS address + wide-port aggregation +
    connection-oriented OPEN address frame. Defer if the doc is SATA-primary
    (FIS / AHCI / host-device link with NO expander / SSP / SMP / SAS address)
    or NVMe-primary (submission/completion queue + doorbell + PCIe with NO SCSI
    / expander), so a SATA or NVMe spec cannot false-fire. Reads ONLY the spec
    text `blob` — never a filename or benchmark name.
    """
    if not blob:
        return False
    low = blob.lower()

    # SAS-only structural tokens (absent from SATA/NVMe specs).
    ssp = "ssp" in low or "serial scsi protocol" in low
    stp = ("stp" in low or "sata tunneling" in low
           or "sata tunnel" in low)
    smp = "smp" in low or "serial management protocol" in low
    expander = "expander" in low
    sas_address = "sas address" in low
    wide_port = "wide port" in low
    open_addr = ("open address frame" in low
                 or ("open_accept" in low and "open_reject" in low)
                 or ("aip" in low and "arbitration" in low))
    name_token = ("serial attached scsi" in low
                  or "serial-attached scsi" in low)
    scsi = "scsi" in low

    transport_triple = ssp and stp and smp

    sas_structure = (
        transport_triple
        and expander
        and (sas_address or wide_port)
        and (open_addr or sas_address)
    )

    # Sibling MUTEX: NVMe-primary doc keys on queue/doorbell/PCIe and carries
    # NO SCSI / expander. If those dominate and the SAS-only structure is
    # absent, defer (do NOT fire).
    nvme_primary = (
        ("submission queue" in low or "completion queue" in low
         or "doorbell" in low)
        and ("namespace" in low or "pci express" in low or "pcie" in low)
        and not (expander or transport_triple or sas_address or wide_port
                 or name_token or scsi)
    )
    if nvme_primary:
        return False

    # SATA-primary doc keys on FIS / AHCI / host-device link and carries NO
    # expander / SSP / SMP / SAS address. If those dominate and the SAS-only
    # structure is absent, defer.
    sata_primary = (
        ("fis" in low or "ahci" in low or "host bus adapter" in low
         or "advanced host controller" in low)
        and not (expander or smp or sas_address or wide_port
                 or name_token or transport_triple)
    )
    if sata_primary:
        return False

    # Fibre-Channel-primary doc: FC is also a SCSI transport and a comprehensive
    # FC spec's generated L-docs enumerate SAS-adjacent storage terms (ssp/smp/
    # expander/sas address), but the doc is anchored by the FC fabric signature
    # (Fibre Channel + N_Port/F_Port + FLOGI/PLOGI + the FC-2 frame header
    # R_CTL/D_ID/S_ID). A real SAS doc carries none of those. Defer.
    fc_primary = (
        "fibre channel" in low
        and ("n_port" in low or "f_port" in low)
        and ("flogi" in low or "plogi" in low)
        and ("r_ctl" in low and "d_id" in low and "s_id" in low)
        and not name_token
    )
    if fc_primary:
        return False

    return bool(
        sas_structure
        or (name_token and transport_triple and expander)
        or (name_token and expander and sas_address and wide_port)
    )


def apply_sas_synth(generated_docs_dir: Path, is_sas_flag: bool,
                    sas_ic_name: Optional[str]) -> None:
    """Apply INCITS T10 SAS (SAS-3/SAS-4) synth when the SAS signature matched."""
    if not is_sas_flag:
        return
    gd = Path(generated_docs_dir)

    # --- Force ic_name across ALL 24 docs FIRST (main + fields docs). ---
    if sas_ic_name is not None:
        for n in _MAIN_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                d["ic_name"] = sas_ic_name
                _write(q, d)
        for n in _FIELDS_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                f = _ensure_dict(d, "fields")
                f["ic_name"] = sas_ic_name
                d["ic_name"] = sas_ic_name
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
# L1 — SAS datasheet header + headline facts.
# ----------------------------------------------------------------------
def _l1(gd: Path) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    d["document_title"] = "Serial Attached SCSI (SAS) Standard"
    d["version"] = "INCITS T10 Serial Attached SCSI (SAS-3 / SAS-4)"
    d["revised_date"] = "SAS-3 (12 Gbps); SAS-4 (22.5 Gbps)"
    d["manufacturer"] = "INCITS T10 Technical Committee"
    d["copyright"] = "© INCITS T10"
    d["abstract"] = (
        "Serial Attached SCSI (SAS) is a point-to-point, full-duplex, serial "
        "storage interconnect that carries SCSI commands, SATA traffic, and "
        "management traffic over a single differential physical link (phy). "
        "SAS multiplexes three transport protocols over the phy: the Serial "
        "SCSI Protocol (SSP) for SCSI command transport, the SATA Tunneling "
        "Protocol (STP) for bridging Serial ATA (SATA) devices, and the Serial "
        "Management Protocol (SMP) for discovering and managing expander "
        "topology. Phys are aggregated into ports; multiple phys with the same "
        "64-bit SAS address form a wide port. Devices and expander devices "
        "(edge / fanout) interconnect through a SAS domain. SAS is "
        "connection-oriented at the link layer: an OPEN address frame, "
        "arbitration (arbitration wait time), and rate matching (ALIGN) set up "
        "a dedicated full-duplex connection. Link rates are 1.5/3/6/12/22.5 "
        "Gbps with 8b10b coding (<=6 Gbps) or 128b150b coding with forward "
        "error correction capability (12/22.5 Gbps).")
    d["keywords"] = [
        "SAS", "Serial Attached SCSI", "SSP", "STP", "SMP", "phy", "wide port",
        "SAS address", "expander", "edge expander", "fanout expander",
        "SAS domain", "OPEN address frame", "OPEN_ACCEPT", "OPEN_REJECT",
        "AIP", "arbitration wait time", "rate matching", "ALIGN", "RRDY",
        "ACK", "NAK", "8b10b", "128b150b", "forward error correction",
        "scrambling", "CRC", "OOB", "COMINIT", "COMSAS", "COMWAKE",
        "Speed Negotiation Window", "SNW", "12 Gbps", "22.5 Gbps",
    ]
    d["external_pins"] = [
        "TX+ / TX- (per phy): differential transmit pair",
        "RX+ / RX- (per phy): differential receive pair",
        "SAS connector: aggregates the phys of a wide port plus power and "
        "sideband signals",
        "No separate forwarded clock wire — the clock is recovered from the "
        "encoded serial stream (8b10b / 128b150b)",
    ]
    d["supported_link_rates_Gbps"] = list(_LINK_RATES_GBPS)
    d["max_link_rate_Gbps"] = _MAX_LINK_RATE_GBPS
    d["sas_address_bits"] = _SAS_ADDRESS_BITS
    d["modes_of_operation"] = [
        {"name": "SSP (Serial SCSI Protocol)",
         "role": "SCSI command transport",
         "note": "Transports SCSI commands (CDB), task management, data, and "
                 "status between a SAS initiator port and a SAS target port; "
                 "COMMAND / TASK / XFER_RDY / DATA / RESPONSE frames."},
        {"name": "STP (SATA Tunneling Protocol)",
         "role": "SATA bridging",
         "note": "Tunnels SATA Frame Information Structures (FIS) across the "
                 "SAS domain so SATA devices attach behind SAS expanders via "
                 "an STP/SATA bridge."},
        {"name": "SMP (Serial Management Protocol)",
         "role": "topology management",
         "note": "Request/response management protocol to discover and "
                 "configure the SAS topology (REPORT GENERAL, DISCOVER, "
                 "CONFIGURE ROUTE INFORMATION) at expander SMP target ports."},
    ]
    d["key_features"] = [
        "Point-to-point full-duplex serial differential storage interconnect "
        "(phy); INCITS T10 standard.",
        "Link rates 1.5/3/6/12/22.5 Gbps; 8b10b coding at <=6 Gbps, 128b150b "
        "coding with forward error correction capability at 12/22.5 Gbps.",
        "Three transport protocols multiplexed over the phy: SSP (SCSI "
        "commands), STP (SATA tunneling), SMP (management).",
        "64-bit SAS address (NAA worldwide name) per port; phys with the same "
        "SAS address aggregate into a wide port.",
        "Expander devices (edge expander / fanout expander) route connections "
        "and grow the SAS domain; SMP manages the expander route table.",
        "Connection-oriented link layer: OPEN address frame, AIP, "
        "OPEN_ACCEPT/OPEN_REJECT, arbitration wait time, rate matching via "
        "ALIGN, CLOSE / BREAK / DONE.",
        "Flow control with RRDY (Receiver Ready) credit and ACK/NAK on SSP "
        "frames; 32-bit CRC per SSP/SMP frame; data scrambling.",
        "OOB signaling (COMINIT/COMRESET, COMSAS, COMWAKE) and the Speed "
        "Negotiation Window (SNW) to detect attachment and negotiate the link "
        "rate; COMSAS distinguishes SAS from SATA.",
        "SSP frame types: COMMAND, TASK, XFER_RDY, DATA, RESPONSE.",
        "Primitives: ALIGN, NOTIFY, SOF/EOF, SOAF/EOAF, RRDY, ACK/NAK, "
        "CREDIT_BLOCKED, OPEN_ACCEPT/OPEN_REJECT, AIP, CLOSE, BREAK, DONE, "
        "HARD_RESET.",
    ]
    d["topology_summary"] = (
        "Point-to-point phys aggregated into narrow ports (one phy) or wide "
        "ports (multiple phys, same SAS address), interconnected through edge "
        "and fanout expander devices into a SAS domain. An edge expander set "
        "bounds a subtractive routing domain; a fanout expander connects "
        "multiple edge expanders.")
    d["use_cases"] = [
        "Enterprise / data-center disk and SSD storage backplanes",
        "SAS host bus adapters and RAID controllers",
        "Expander-based JBOD enclosures and large drive topologies",
        "SATA drives attached behind SAS expanders via STP",
        "Dual-port wide-port high-availability storage paths",
    ]
    d["revision_history"] = [
        {"version": "SAS-1", "date": "2003-2005",
         "description": "First Serial Attached SCSI standard: 1.5/3 Gbps "
                        "point-to-point serial SCSI, SSP/STP/SMP, expanders, "
                        "64-bit SAS address, 8b10b coding."},
        {"version": "SAS-2", "date": "2009",
         "description": "6 Gbps link rate; expanded expander/zoning and SSC."},
        {"version": "SAS-3", "date": "2013",
         "description": "12 Gbps link rate; 128b150b forward-error-correction "
                        "capable encoding introduced for the higher rate."},
        {"version": "SAS-4", "date": "2017",
         "description": "22.5 Gbps link rate; 128b150b coding with forward "
                        "error correction."},
    ]
    d["overview"] = (
        "Serial Attached SCSI (SAS) is the INCITS T10 serial successor to "
        "parallel SCSI (SPI). It is a point-to-point, full-duplex, "
        "differential serial link (phy) running at 1.5/3/6/12/22.5 Gbps. Below "
        "and at 6 Gbps SAS uses 8b10b encoding with running disparity; at 12 "
        "Gbps (SAS-3) and 22.5 Gbps (SAS-4) it uses 128b150b encoding with a "
        "forward error correction capability. Three transport protocols are "
        "multiplexed over the phy: SSP carries SCSI commands, STP tunnels SATA "
        "traffic to SATA devices behind expanders, and SMP discovers and "
        "manages the topology. Each port has a 64-bit SAS address (an NAA "
        "worldwide name); phys sharing a SAS address form a wide port for "
        "bandwidth and redundancy. Expander devices (edge and fanout) route "
        "connections and grow the SAS domain. SAS is connection-oriented: a "
        "port sends an OPEN address frame (source/destination SAS address, "
        "connection rate, protocol, arbitration wait time); expanders route it "
        "and emit AIP while arbitration proceeds; the destination replies "
        "OPEN_ACCEPT or OPEN_REJECT; once open, frames flow full-duplex until "
        "CLOSE. Flow control uses RRDY credit and ACK/NAK; each SSP/SMP frame "
        "carries a 32-bit CRC; data dwords are scrambled. Before normal "
        "operation, two phys exchange OOB signals (COMINIT/COMSAS/COMWAKE) and "
        "run the Speed Negotiation Window to select the highest common rate.")
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
        "Point-to-point, full-duplex, serial differential storage interconnect "
        "(phy). Three transport protocols (SSP / STP / SMP) are multiplexed "
        "over a connection-oriented link layer; link rates 1.5/3/6/12/22.5 "
        "Gbps. Standardized by INCITS T10.")
    po["duplex"] = (
        "Full-duplex per phy (independent differential TX+/TX- and RX+/RX- "
        "pairs); a connection carries frames in both directions simultaneously.")
    po["synchronous_serial"] = False
    po["source_synchronous"] = False
    po["embedded_clock"] = True
    po["forwarded_clock"] = False
    po["encoding"] = (
        "8b10b with running disparity at 1.5/3/6 Gbps; 128b150b with a forward "
        "error correction capability at 12 Gbps (SAS-3) and 22.5 Gbps "
        "(SAS-4). The clock is recovered from the encoded serial stream; data "
        "dwords are scrambled.")
    po["modulation"] = "Differential NRZ serial on TX+/TX- and RX+/RX- per phy."
    po["link_rates_Gbps"] = list(_LINK_RATES_GBPS)
    po["max_link_rate_Gbps"] = _MAX_LINK_RATE_GBPS
    po["transport_protocols"] = list(_TRANSPORTS)
    po["sas_address_bits"] = _SAS_ADDRESS_BITS
    po["crc_bits"] = _CRC_BITS
    po["connection_oriented"] = True
    po["wide_port"] = (
        "Multiple phys with the same SAS address aggregate into a wide port "
        "(narrow port = one phy); a wide link connects two wide ports.")
    po["topology"] = (
        "phy -> port (wide port) -> expander (edge / fanout) -> SAS domain.")
    d["functional_requirements"] = [
        {"id": "FR-PHY-01", "text": "SAS provides a point-to-point full-duplex "
         "serial differential phy with a TX+/TX- transmit pair and an RX+/RX- "
         "receive pair, running at 1.5/3/6/12/22.5 Gbps."},
        {"id": "FR-CODE-02", "text": "The phy uses 8b10b encoding with running "
         "disparity at <=6 Gbps and 128b150b encoding with a forward error "
         "correction capability at 12 Gbps (SAS-3) and 22.5 Gbps (SAS-4); the "
         "serial stream is organized into dwords."},
        {"id": "FR-ADDR-03", "text": "Every SAS port has a 64-bit SAS address "
         "(an NAA worldwide name) that uniquely identifies it in the SAS "
         "domain."},
        {"id": "FR-PORT-04", "text": "Phys with the same SAS address aggregate "
         "into a port; a port with one phy is a narrow port and a port with "
         "more than one phy is a wide port; a wide link connects two wide "
         "ports."},
        {"id": "FR-XPND-05", "text": "Expander devices route connections among "
         "phys and grow the SAS domain. Edge expanders connect end devices; "
         "fanout expanders connect multiple edge expanders. Expanders perform "
         "table, subtractive, and direct routing using an expander route "
         "table."},
        {"id": "FR-SSP-06", "text": "The Serial SCSI Protocol (SSP) transports "
         "SCSI commands, task management, data, and status with COMMAND, TASK, "
         "XFER_RDY, DATA, and RESPONSE frames between initiator and target "
         "ports."},
        {"id": "FR-STP-07", "text": "The SATA Tunneling Protocol (STP) tunnels "
         "SATA Frame Information Structures (FIS) across the SAS domain so SATA "
         "devices attach behind expanders through an STP/SATA bridge."},
        {"id": "FR-SMP-08", "text": "The Serial Management Protocol (SMP) is a "
         "request/response protocol that discovers and configures the topology "
         "(REPORT GENERAL, DISCOVER, REPORT PHY ERROR LOG, CONFIGURE ROUTE "
         "INFORMATION) at expander SMP target ports."},
        {"id": "FR-CONN-09", "text": "The link layer is connection-oriented: a "
         "port sends an OPEN address frame (source/destination SAS address, "
         "connection rate, protocol, arbitration wait time); the destination "
         "replies OPEN_ACCEPT or OPEN_REJECT; expanders emit AIP during "
         "arbitration; CLOSE closes the connection and BREAK aborts it."},
        {"id": "FR-FLOW-10", "text": "Flow control uses RRDY (Receiver Ready) "
         "to grant frame credit and ACK/NAK to acknowledge SSP frames; each "
         "SSP/SMP frame carries a 32-bit CRC."},
        {"id": "FR-OOB-11", "text": "Before normal operation two phys exchange "
         "OOB signals (COMINIT/COMRESET, COMSAS, COMWAKE) and run the Speed "
         "Negotiation Window (SNW) to detect attachment and negotiate the "
         "highest common link rate; COMSAS distinguishes a SAS phy from SATA."},
        {"id": "FR-RATE-12", "text": "Rate matching inserts ALIGN (and NOTIFY) "
         "primitives when the connection rate is slower than the physical link "
         "rate so the faster phy does not overrun the slower path."},
    ]
    d["error_response_conditions"] = [
        "SSP frame CRC (32-bit) error — the frame is NAKed and retransmitted.",
        "OPEN_REJECT — the connection request is rejected (no destination, "
        "pathway blocked, bad destination, retry).",
        "BREAK — aborts a stalled connection or connection request.",
        "8b10b code violation / running-disparity error — invalid dword, "
        "counted in the phy error log (readable via SMP REPORT PHY ERROR LOG).",
        "Loss of dword synchronization — the phy re-establishes sync (OOB / "
        "ALIGN).",
    ]
    d["compliance_requirements"] = [
        "Point-to-point full-duplex serial differential phy at 1.5/3/6/12/22.5 "
        "Gbps.",
        "8b10b coding (<=6 Gbps) and 128b150b coding with FEC capability "
        "(12/22.5 Gbps); running disparity; scrambling; 32-bit CRC.",
        "64-bit SAS address per port; wide-port aggregation of phys sharing a "
        "SAS address.",
        "SSP, STP, and SMP transport protocols.",
        "Expander-based SAS domain (edge / fanout) with SMP topology "
        "management.",
        "Connection-oriented link layer: OPEN address frame, AIP, "
        "OPEN_ACCEPT/OPEN_REJECT, arbitration wait time, rate matching via "
        "ALIGN, CLOSE/BREAK/DONE.",
        "RRDY credit flow control and ACK/NAK on SSP frames.",
        "OOB (COMINIT/COMSAS/COMWAKE) and the Speed Negotiation Window (SNW).",
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
        "Connection-oriented, frame-based serial protocol multiplexing three "
        "transports (SSP / STP / SMP) over a SAS phy. A port opens a connection "
        "with an OPEN address frame (carrying the destination SAS address, "
        "connection rate, protocol, and arbitration wait time); once "
        "OPEN_ACCEPTed, SSP/STP/SMP frames flow full-duplex with RRDY credit "
        "and ACK/NAK flow control, each protected by a 32-bit CRC, until "
        "CLOSE.")
    d["transport_protocols"] = [
        {"name": "SSP", "full": "Serial SCSI Protocol",
         "purpose": "Transport SCSI commands, task management, data, and "
                    "status between SAS initiator and target ports."},
        {"name": "STP", "full": "SATA Tunneling Protocol",
         "purpose": "Tunnel SATA FIS across the SAS domain to SATA devices "
                    "behind expanders via an STP/SATA bridge."},
        {"name": "SMP", "full": "Serial Management Protocol",
         "purpose": "Discover and configure the SAS topology at expander SMP "
                    "target ports (request/response)."},
    ]
    d["ssp_frame_types"] = [
        {"name": "COMMAND", "purpose": "Carries a SCSI Command Descriptor "
         "Block (CDB)."},
        {"name": "TASK", "purpose": "Carries a task-management function."},
        {"name": "XFER_RDY", "purpose": "Target-to-initiator transfer-ready; "
         "flow control for write data."},
        {"name": "DATA", "purpose": "Carries read or write data."},
        {"name": "RESPONSE", "purpose": "Carries SCSI status and sense data."},
    ]
    d["connection_management"] = {
        "open": "OPEN address frame: source SAS address, destination SAS "
                "address, requested connection rate, protocol (SSP/STP/SMP), "
                "arbitration wait time (AWT).",
        "arbitration": "Expanders route the OPEN frame and emit AIP "
                       "(Arbitration In Progress) while arbitration resolves "
                       "contention by arbitration wait time.",
        "accept_reject": "Destination replies OPEN_ACCEPT (open) or "
                         "OPEN_REJECT (reject: no destination, pathway "
                         "blocked, bad destination, retry).",
        "close": "CLOSE closes an open connection; BREAK aborts a connection "
                 "or connection request; DONE ends frame transmission.",
        "rate_matching": "ALIGN (and NOTIFY) primitives are inserted when the "
                         "connection rate is slower than the physical link "
                         "rate.",
    }
    d["primitives"] = list(_PRIMITIVES)
    d["primitive_descriptions"] = [
        {"name": "ALIGN", "use": "Dword synchronization, rate matching, clock "
         "skew management."},
        {"name": "NOTIFY", "use": "Signals events (e.g. ENABLE SPINUP, power "
         "loss expected)."},
        {"name": "SOF / EOF", "use": "Start / End of Frame delimiters for "
         "SSP/SMP frames."},
        {"name": "SOAF / EOAF", "use": "Start / End of Address Frame."},
        {"name": "RRDY", "use": "Receiver Ready — grants one frame of credit."},
        {"name": "ACK / NAK", "use": "Acknowledge / negative-acknowledge an "
         "SSP frame."},
        {"name": "CREDIT_BLOCKED", "use": "No more credit available."},
        {"name": "OPEN_ACCEPT / OPEN_REJECT", "use": "Connection response."},
        {"name": "AIP", "use": "Arbitration In Progress."},
        {"name": "CLOSE", "use": "Close an open connection."},
        {"name": "BREAK", "use": "Abort a connection or connection request."},
        {"name": "DONE", "use": "End the current connection's frame "
         "transmission."},
        {"name": "HARD_RESET", "use": "Reset the attached phy."},
    ]
    d["smp_functions"] = [
        "REPORT GENERAL", "DISCOVER", "REPORT PHY ERROR LOG",
        "CONFIGURE ROUTE INFORMATION",
    ]
    d["addressing"] = {
        "sas_address_bits": _SAS_ADDRESS_BITS,
        "note": "Each port has a 64-bit SAS address (NAA worldwide name); "
                "connections are addressed by source/destination SAS address "
                "in the OPEN address frame.",
    }
    d["crc"] = {
        "crc_bits": _CRC_BITS,
        "coverage": "SSP and SMP frame contents (frame header + information "
                    "unit).",
        "scrambling": "Data dwords (excluding primitives) are scrambled by a "
                      "linear-feedback scrambler.",
    }
    d["flow_control"] = {
        "credit": "RRDY grants one frame of credit; CREDIT_BLOCKED signals no "
                  "credit.",
        "ack_nak": "ACK acknowledges and NAK negative-acknowledges an SSP "
                   "frame (NAK triggers retransmission).",
    }
    d["byte_oriented"] = True
    d["frame_oriented"] = True
    d["connection_oriented"] = True
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
        "SAS is a transport/interconnect standard rather than a fixed "
        "memory-mapped register IC. Configuration and status are exposed "
        "through SMP functions (the expander route table, phy settings, phy "
        "error log) and through the SCSI mode/log pages reachable over SSP; a "
        "host bus adapter implements vendor host-accessible registers. The "
        "groups below are the canonical SAS configuration/status surfaces.")
    d["register_access"] = {
        "transport": "SMP request/response (management) + SSP SCSI mode/log "
                     "pages (device) + vendor HBA registers",
        "purpose": "Configure expander routing and phy settings; read "
                   "topology, phy state, and error logs.",
    }
    d["register_groups"] = [
        {"group": "Expander (SMP)", "fields": [
            "Expander route table (table / subtractive / direct routing)",
            "Phy configuration (link rate, phy enable/disable)",
            "REPORT GENERAL (number of phys, expander type)",
            "DISCOVER (attached SAS address, attached device type)",
            "REPORT PHY ERROR LOG (invalid dword, running-disparity error, "
            "loss-of-dword-sync, phy reset problem)"]},
        {"group": "Phy / link", "fields": [
            "Negotiated link rate (1.5/3/6/12/22.5 Gbps)",
            "SAS address (64-bit)",
            "Wide-port membership (phys sharing the SAS address)",
            "OOB / speed-negotiation status"]},
        {"group": "Port / device (SSP / SCSI)", "fields": [
            "SCSI mode pages / log pages over SSP",
            "Logical-unit inventory",
            "Task-management state"]},
    ]
    d["protocol_fields"] = {
        "sas_address_bits": _SAS_ADDRESS_BITS,
        "crc_bits": _CRC_BITS,
        "link_rates_Gbps": list(_LINK_RATES_GBPS),
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
        "Each SAS phy is a full-duplex differential serial link: a transmit "
        "pair (TX+/TX-) and an independent receive pair (RX+/RX-). The "
        "transmitter drives differential NRZ; the receiver recovers the clock "
        "from the encoded stream (8b10b at <=6 Gbps, 128b150b at 12/22.5 "
        "Gbps). Spread-spectrum clocking (SSC) may be applied to reduce EMI. "
        "There is no separate forwarded clock wire.")
    d["modulation"] = "Differential NRZ serial (TX+/TX-, RX+/RX-)."
    d["clocking"] = (
        "Embedded clock: the receiver recovers bit/dword timing from the "
        "8b10b or 128b150b encoded serial stream via its CDR. Spread-spectrum "
        "clocking (SSC) is optional for EMI reduction.")
    d["transmitter_specs_canonical"] = {
        "link_rates_Gbps": list(_LINK_RATES_GBPS),
        "max_link_rate_Gbps": _MAX_LINK_RATE_GBPS,
        "modulation": "differential NRZ serial",
        "signaling": "differential (TX+/TX-)",
        "line_encoding": "8b10b (<=6 Gbps) / 128b150b with FEC capability "
                         "(12/22.5 Gbps)",
        "spread_spectrum_clocking": "optional (SSC)",
    }
    d["receiver_specs_canonical"] = {
        "signaling": "differential (RX+/RX-)",
        "clock_recovery": "CDR from the encoded serial stream",
        "dword_sync": "ALIGN / idle dwords maintain dword synchronization.",
    }
    d["oob_signaling"] = {
        "signals": ["COMINIT/COMRESET", "COMSAS", "COMWAKE"],
        "purpose": "Low-speed burst patterns to detect attachment and "
                   "distinguish SAS from SATA; COMSAS identifies a SAS phy.",
        "speed_negotiation": "The Speed Negotiation Window (SNW) sequence "
                             "negotiates the highest common link rate.",
    }
    d["max_link_rate_Gbps"] = _MAX_LINK_RATE_GBPS
    d["link_rates_Gbps"] = list(_LINK_RATES_GBPS)
    d["encoding_role_in_analog"] = (
        "SAS uses 8b10b (DC-balanced, running disparity) up to 6 Gbps and "
        "128b150b with a forward error correction capability at 12/22.5 Gbps. "
        "The line code provides DC balance and transition density for clock "
        "recovery; integrity at the frame level comes from the 32-bit CRC and "
        "scrambling, and OOB/SNW handle attachment detection and rate "
        "negotiation.")
    _write(p, d)


# ----------------------------------------------------------------------
# L6 — control logic / connection + phy FSMs.
# ----------------------------------------------------------------------
def _l6(gd: Path) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["fsm_states_phy"] = [
        {"name": "OOB", "description": "Out-of-band signaling: "
         "COMINIT/COMRESET, COMSAS, COMWAKE detect attachment and distinguish "
         "SAS from SATA."},
        {"name": "SPEED_NEGOTIATION", "description": "The Speed Negotiation "
         "Window (SNW) negotiates the highest common link rate."},
        {"name": "DWORD_SYNC", "description": "The phy achieves dword "
         "synchronization on the encoded stream (ALIGN / idle dwords)."},
        {"name": "READY", "description": "The phy is synchronized and ready to "
         "open or accept connections."},
    ]
    d["fsm_states_connection"] = [
        {"name": "IDLE", "description": "No connection; the phy exchanges idle "
         "dwords."},
        {"name": "OPEN_REQUEST", "description": "A port transmits an OPEN "
         "address frame (source/destination SAS address, rate, protocol, "
         "arbitration wait time)."},
        {"name": "ARBITRATING", "description": "Expanders route the OPEN frame "
         "and emit AIP while arbitration resolves contention."},
        {"name": "CONNECTED", "description": "OPEN_ACCEPT received; a dedicated "
         "full-duplex connection carries SSP/STP/SMP frames with RRDY/ACK/NAK "
         "flow control."},
        {"name": "CLOSING", "description": "CLOSE (or DONE then CLOSE) tears "
         "down the connection; BREAK aborts it."},
    ]
    d["fsm_hints"] = {
        "trigger": "Power-up / reset -> OOB -> SPEED_NEGOTIATION -> DWORD_SYNC "
        "-> READY. A connection request drives OPEN_REQUEST -> ARBITRATING -> "
        "CONNECTED on OPEN_ACCEPT.",
        "rule": "Frames flow only inside an open connection; RRDY credit must "
        "be granted before an SSP frame is sent; each SSP frame is ACK/NAKed.",
        "abort": "OPEN_REJECT denies a request; BREAK aborts a stalled "
        "connection; HARD_RESET resets the phy.",
    }
    d["anti_deadlock_rule"] = (
        "Arbitration uses the arbitration wait time (AWT) carried in the OPEN "
        "address frame to resolve contention fairly across the SAS domain; "
        "expander pathway recovery and BREAK resolve blocked or deadlocked "
        "routing so a connection request cannot stall indefinitely.")
    d["exit_from_reset_or_poweron"] = (
        "On power-up / reset (or HARD_RESET) the phy runs OOB "
        "(COMINIT/COMSAS/COMWAKE), then the Speed Negotiation Window to select "
        "the link rate, then achieves dword synchronization, and becomes ready "
        "to open or accept connections.")
    d["default_ready_state_recommendation"] = {
        "idle": "Exchange idle / ALIGN dwords to keep dword synchronization "
                "between connections.",
        "connection": "Open a connection (OPEN address frame) before sending "
                      "SSP/STP/SMP frames; grant RRDY credit before accepting "
                      "frames.",
    }
    d["configurations"] = [
        {"name": "Narrow port", "description": "A port with a single phy."},
        {"name": "Wide port", "description": "A port with multiple phys "
         "sharing the same SAS address; a wide link connects two wide ports."},
        {"name": "Direct-attach", "description": "Initiator port connected "
         "point-to-point to a target port (no expander)."},
        {"name": "Expander topology", "description": "Edge and fanout "
         "expanders route connections to build a large SAS domain."},
    ]
    d["timing_dependency_rule"] = (
        "Before any frame flows the phy must complete OOB + speed negotiation + "
        "dword synchronization, and a connection must be open. Rate matching "
        "(ALIGN insertion) couples a slower connection rate to a faster "
        "physical link rate so the receiver is not overrun.")
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
        {"name": "SMP REPORT PHY ERROR LOG", "purpose": "Reads per-phy error "
         "counters: invalid dword, running-disparity error, loss-of-dword-"
         "synchronization, phy reset problem."},
        {"name": "SMP DISCOVER", "purpose": "Reports attached SAS address, "
         "attached device type, and negotiated link rate per phy."},
        {"name": "SMP REPORT GENERAL", "purpose": "Reports the number of phys, "
         "expander type, and route-table configuration."},
        {"name": "OOB / speed-negotiation status", "purpose": "Indicates "
         "attachment detection and the negotiated link rate."},
        {"name": "Connection status", "purpose": "OPEN_ACCEPT / OPEN_REJECT / "
         "AIP / BREAK outcomes for connection bring-up."},
        {"name": "CRC / ACK-NAK status", "purpose": "SSP frame CRC pass/fail "
         "and ACK/NAK indicate frame-level errors."},
    ]
    d["error_detection_mechanisms"] = [
        "32-bit CRC per SSP/SMP frame detects frame corruption.",
        "ACK/NAK acknowledges or rejects each SSP frame (NAK -> retransmit).",
        "8b10b code violation / running-disparity error detects invalid "
        "dwords.",
        "Loss of dword synchronization is detected and recovered.",
        "OPEN_REJECT distinguishes connection-setup failures (no destination, "
        "pathway blocked, bad destination, retry).",
        "SMP REPORT PHY ERROR LOG accumulates per-phy error counts.",
    ]
    d["test_modes"] = [
        {"name": "PHY test patterns", "purpose": "Transmit test patterns / "
         "jitter-tolerance patterns for physical-layer characterization."},
        {"name": "Loopback", "purpose": "Phy loopback for link bring-up and "
         "BER measurement."},
        {"name": "OOB / SNW exercise", "purpose": "Exercise the OOB and "
         "speed-negotiation sequences."},
    ]
    d["interrupt_or_event_sources"] = [
        {"event": "Connection opened", "trigger": "OPEN_ACCEPT received."},
        {"event": "Connection rejected", "trigger": "OPEN_REJECT received."},
        {"event": "Frame received", "trigger": "A valid SSP/STP/SMP frame "
         "arrives."},
        {"event": "CRC / NAK error", "trigger": "SSP frame CRC fails or NAK "
         "received."},
        {"event": "Phy error", "trigger": "Invalid dword / running-disparity / "
         "loss of dword sync."},
        {"event": "BREAK", "trigger": "Connection aborted."},
    ]
    d["notes"] = (
        "SAS exposes its protocol-level test/debug surface through SMP "
        "(REPORT GENERAL / DISCOVER / REPORT PHY ERROR LOG), the OOB/speed-"
        "negotiation status, connection outcomes, and per-frame CRC/ACK-NAK "
        "results, plus physical-layer test patterns and loopback. Chip-level "
        "JTAG/scan/BIST remain controller-vendor / SoC concerns.")
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
        "SAS_STANDARD": "INCITS T10 SAS-3 / SAS-4",
        "MODULATION": "differential NRZ serial",
        "SIGNALING": "differential (TX+/TX-, RX+/RX-)",
        "LINE_ENCODING_LE6G": "8b10b",
        "LINE_ENCODING_12G_22G": "128b150b (FEC capable)",
        "LINK_RATES_GBPS": list(_LINK_RATES_GBPS),
        "MAX_LINK_RATE_GBPS": _MAX_LINK_RATE_GBPS,
        "SAS_ADDRESS_BITS": _SAS_ADDRESS_BITS,
        "CRC_BITS": _CRC_BITS,
        "TRANSPORT_COUNT": 3,
        "TRANSPORTS": list(_TRANSPORTS),
        "SSP_FRAME_TYPE_COUNT": len(_SSP_FRAME_TYPES),
        "PRIMITIVE_COUNT": len(_PRIMITIVES),
        "FULL_DUPLEX": True,
        "CONNECTION_ORIENTED": True,
        "EMBEDDED_CLOCK": True,
        "FORWARDED_CLOCK": False,
    })
    d["frame_format_constants"] = {
        "ssp_frame_types": list(_SSP_FRAME_TYPES),
        "crc_bits": _CRC_BITS,
        "scrambling": True,
        "address_frame": "OPEN address frame (SOAF/EOAF delimited)",
    }
    d["crc_constants"] = {
        "ssp_smp_crc": {"width_bits": _CRC_BITS,
                        "coverage": "frame header + information unit"},
    }
    kc = _ensure_dict(d, "key_constants_for_RTL_authoring")
    kc.update({
        "is_serial": True,
        "is_differential": True,
        "is_full_duplex": True,
        "is_connection_oriented": True,
        "embedded_clock": True,
        "forwarded_clock": False,
        "line_encoding_le6g": "8b10b",
        "line_encoding_12g_22g": "128b150b",
        "forward_error_correction_capable": True,
        "scrambling": True,
        "max_link_rate_Gbps": _MAX_LINK_RATE_GBPS,
        "link_rates_Gbps": list(_LINK_RATES_GBPS),
        "sas_address_bits": _SAS_ADDRESS_BITS,
        "crc_bits": _CRC_BITS,
        "transports": list(_TRANSPORTS),
        "ssp_frame_types": list(_SSP_FRAME_TYPES),
        "primitives": list(_PRIMITIVES),
        "wide_port": True,
        "expander": True,
    })
    d["default_signal_values_when_idle"] = {
        "link_idle": "Idle / ALIGN dwords keep dword synchronization between "
                     "connections.",
        "no_connection": "Frames flow only inside an open connection.",
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
        "modulation": "differential NRZ serial on TX+/TX- and RX+/RX-",
        "line_encoding": "8b10b (<=6 Gbps) / 128b150b FEC-capable (12/22.5 "
                         "Gbps)",
        "dword": "4-byte (40-bit 8b10b) dword granularity; ALIGN dwords keep "
                 "synchronization.",
        "clock_recovery": "CDR from the encoded stream; no forwarded clock.",
    }
    d["frame_waveform"] = {
        "ssp_frame": "SOF + frame header + information unit + 32-bit CRC + EOF.",
        "address_frame": "SOAF + OPEN address frame contents + CRC + EOAF.",
        "flow_control": "RRDY grants credit; ACK/NAK follow an SSP frame.",
    }
    d["connection_waveform"] = {
        "open": "OPEN address frame -> AIP (during arbitration) -> "
                "OPEN_ACCEPT / OPEN_REJECT.",
        "close": "DONE then CLOSE; BREAK aborts.",
        "rate_matching": "ALIGN (and NOTIFY) inserted when connection rate < "
                         "physical link rate.",
    }
    d["oob_waveform"] = {
        "oob_signals": ["COMINIT/COMRESET", "COMSAS", "COMWAKE"],
        "speed_negotiation": "Speed Negotiation Window (SNW) bursts negotiate "
                             "the highest common link rate.",
    }
    d["general_timing_rule"] = (
        "After OOB + speed negotiation + dword synchronization, a connection "
        "must be open before frames flow. Rate matching inserts ALIGN dwords "
        "to couple a slower connection rate to a faster physical link rate so "
        "the receiver is not overrun.")
    d["data_rate_waveform"] = {
        "link_rates_Gbps": list(_LINK_RATES_GBPS),
        "encoding": {"1.5": "8b10b", "3": "8b10b", "6": "8b10b",
                     "12": "128b150b", "22.5": "128b150b"},
        "modulation": "differential NRZ serial",
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
        "Serial storage interconnect controller: a point-to-point full-duplex "
        "SAS phy (or wide port of phys) implementing 8b10b/128b150b coding, "
        "OOB + speed negotiation, the connection-oriented link layer (OPEN "
        "address frame, AIP, OPEN_ACCEPT/OPEN_REJECT, arbitration, rate "
        "matching), the SSP/STP/SMP transports, RRDY/ACK/NAK flow control with "
        "32-bit CRC, and expander routing — connecting a host (initiator) to "
        "SAS/SATA targets through a SAS domain.")
    d["topology_description"] = (
        "phy -> port (narrow / wide) -> expander (edge / fanout) -> SAS "
        "domain. Phys sharing a 64-bit SAS address form a wide port; edge and "
        "fanout expanders route connections to build large topologies; SMP "
        "manages the expander route tables.")
    io = _ensure_dict(d, "integration_overview")
    io.update({
        "sas_standard": "INCITS T10 SAS-3 / SAS-4",
        "max_link_rate_Gbps": _MAX_LINK_RATE_GBPS,
        "link_rates_Gbps": list(_LINK_RATES_GBPS),
        "transports": list(_TRANSPORTS),
        "sas_address_bits": _SAS_ADDRESS_BITS,
        "crc_bits": _CRC_BITS,
        "modulation": "differential NRZ serial (TX+/TX-, RX+/RX-)",
        "line_encoding": "8b10b (<=6 Gbps) / 128b150b FEC-capable (12/22.5 "
                         "Gbps)",
        "clocking": "embedded (CDR from the encoded stream)",
        "connection_oriented": True,
        "wide_port": True,
        "expander_types": ["edge expander", "fanout expander"],
        "interfaces": {"phy": "TX+/TX-, RX+/RX-",
                       "SMP": "topology management request/response",
                       "host": "initiator host interface (e.g. HBA)"},
    })
    d["interface_categories"] = [
        "Phy interface — differential TX+/TX- and RX+/RX- serial pairs.",
        "Port interface — narrow or wide port (phys sharing a SAS address).",
        "Transport interface — SSP (SCSI) / STP (SATA tunneling) / SMP "
        "(management).",
        "Expander interface — routing of connections and SMP route-table "
        "management.",
    ]
    d["interconnect_topologies_supported"] = [
        "Direct-attach point-to-point (initiator port <-> target port).",
        "Narrow port (single phy) and wide port (multiple phys, same SAS "
        "address).",
        "Edge-expander topology (edge expander set).",
        "Fanout-expander topology (fanout expander connecting edge "
        "expanders).",
        "STP/SATA bridging of SATA devices behind expanders.",
    ]
    d["default_signal_values_when_omitted"] = (
        "Link idle exchanges idle/ALIGN dwords; frames flow only inside an "
        "open connection. An unused phy of a wide port is simply not part of "
        "an active connection.")
    d["soc_dependent_items"] = [
        "Number of phys and wide-port width.",
        "SAS address assignment (64-bit NAA) per port.",
        "Supported link rates (1.5/3/6/12/22.5 Gbps) and SSC enable.",
        "Initiator / target / expander function set.",
        "Expander routing configuration (table / subtractive / direct).",
        "Physical / connector / backplane design.",
    ]
    d["device_classes_examples"] = [
        "SAS host bus adapter (HBA) / RAID controller (initiator)",
        "SAS disk drive / SSD (target)",
        "Edge expander device",
        "Fanout expander device",
        "STP/SATA bridge",
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
        "Phy bring-up: OOB (COMINIT/COMSAS/COMWAKE) + Speed Negotiation Window "
        "+ dword synchronization.",
        "Link-rate negotiation across 1.5/3/6/12/22.5 Gbps; 8b10b vs 128b150b "
        "coding.",
        "SAS address (64-bit) assignment and matching across a wide port.",
        "Wide-port aggregation: phys sharing a SAS address; connections on any "
        "constituent phy.",
        "Connection management: OPEN address frame, AIP, OPEN_ACCEPT, "
        "OPEN_REJECT (no destination / pathway blocked / bad destination / "
        "retry).",
        "Arbitration by arbitration wait time; rate matching via ALIGN.",
        "SSP frames: COMMAND / TASK / XFER_RDY / DATA / RESPONSE.",
        "STP: SATA FIS tunneling through an STP/SATA bridge.",
        "SMP: REPORT GENERAL / DISCOVER / REPORT PHY ERROR LOG / CONFIGURE "
        "ROUTE INFORMATION.",
        "Flow control: RRDY credit, ACK/NAK, CREDIT_BLOCKED.",
        "32-bit CRC error injection / detection; scrambling.",
        "Expander routing: table / subtractive / direct; edge and fanout "
        "expanders.",
        "Primitive handling: ALIGN / NOTIFY / SOF/EOF / SOAF/EOAF / CLOSE / "
        "BREAK / DONE / HARD_RESET.",
        "Phy power management: partial / slumber via NOTIFY (ENABLE SPINUP).",
        "Error logging: invalid dword / running-disparity / loss-of-dword-sync "
        "in the phy error log.",
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
        {"field": "SAS address (64-bit NAA)",
         "location": "device configuration / NVRAM",
         "note": "The worldwide-unique 64-bit SAS address per port; typically "
                 "factory-assigned, not a protocol-fixed OTP concept."},
        {"field": "Supported link rates / SSC",
         "location": "phy configuration",
         "note": "Which of 1.5/3/6/12/22.5 Gbps and whether SSC is enabled."},
        {"field": "Device function set",
         "location": "device configuration",
         "note": "Initiator / target / expander capability."},
        {"field": "Expander route table",
         "location": "expander configuration (SMP CONFIGURE ROUTE "
                     "INFORMATION)",
         "note": "Routing configuration; programmed, not OTP-fixed."},
    ]
    d["notes"] = (
        "SAS does not define OTP/fuse content as a protocol concept. The SAS "
        "address, supported rates, function set, and expander routing are "
        "device/expander configuration (often in NVRAM and discoverable via "
        "SMP); an implementation may back some defaults with non-volatile "
        "storage, but the standard only requires they be configurable / "
        "discoverable.")
    _write(p, d)


# ----------------------------------------------------------------------
# L12 — behavioral sequences.
# ----------------------------------------------------------------------
def _l12(gd: Path) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["phy_bringup_sequence"] = [
        "1. Power-up / reset -> OOB signaling (COMINIT/COMRESET, COMSAS, "
        "COMWAKE); COMSAS distinguishes SAS from SATA.",
        "2. Run the Speed Negotiation Window (SNW) to select the highest "
        "common link rate (1.5/3/6/12/22.5 Gbps).",
        "3. Achieve dword synchronization (ALIGN / idle dwords) on the encoded "
        "stream.",
        "4. The phy is ready to open or accept connections.",
    ]
    d["connection_open_sequence"] = [
        "1. The originating port transmits an OPEN address frame "
        "(source/destination SAS address, connection rate, protocol "
        "SSP/STP/SMP, arbitration wait time).",
        "2. Expanders route the OPEN frame toward the destination, emitting "
        "AIP while arbitration proceeds.",
        "3. The destination replies OPEN_ACCEPT (open) or OPEN_REJECT "
        "(reject).",
        "4. Once open, the connection is a dedicated full-duplex path.",
    ]
    d["ssp_command_sequence"] = [
        "1. Over an open SSP connection the initiator sends a COMMAND frame "
        "(SCSI CDB) after receiving RRDY credit.",
        "2. For a write, the target returns XFER_RDY; the initiator sends DATA "
        "frames; for a read, the target sends DATA frames.",
        "3. Each SSP frame is CRC-checked and ACK/NAKed (NAK -> retransmit).",
        "4. The target sends a RESPONSE frame with SCSI status and sense "
        "data.",
    ]
    d["smp_management_sequence"] = [
        "1. An SMP initiator opens an SMP connection to an expander SMP target "
        "port.",
        "2. It sends an SMP REQUEST frame (e.g. DISCOVER, REPORT GENERAL).",
        "3. The expander returns an SMP RESPONSE frame.",
        "4. The connection is closed (CLOSE).",
    ]
    d["stp_tunnel_sequence"] = [
        "1. An STP initiator opens an STP connection to an STP/SATA bridge in "
        "an expander.",
        "2. SATA Frame Information Structures (FIS) are tunneled across the "
        "SAS connection to the SATA device.",
        "3. The connection is closed when the SATA exchange completes.",
    ]
    d["connection_close_sequence"] = [
        "1. DONE ends frame transmission on the connection.",
        "2. CLOSE tears down the connection; the phys return to idle dwords.",
        "3. BREAK aborts a stalled connection or connection request.",
    ]
    d["reset_sequence"] = [
        "1. HARD_RESET (or power-up / reset) resets the phy.",
        "2. Re-run OOB -> Speed Negotiation Window -> dword synchronization "
        "before reopening connections.",
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
        {"name": "Serial eye / jitter per link rate", "purpose": "Verify the "
         "differential NRZ eye and jitter budget at 1.5/3/6/12/22.5 Gbps."},
        {"name": "OOB burst timing", "purpose": "Confirm COMINIT/COMSAS/COMWAKE "
         "burst and idle timing and SAS-vs-SATA discrimination."},
        {"name": "Speed negotiation", "purpose": "Validate the Speed "
         "Negotiation Window selects the highest common rate."},
        {"name": "8b10b / 128b150b coding", "purpose": "Confirm running "
         "disparity and dword synchronization; FEC capability at 12/22.5 "
         "Gbps."},
        {"name": "Spread-spectrum clocking", "purpose": "Measure SSC "
         "modulation profile (if enabled) within tolerance."},
        {"name": "CRC coverage", "purpose": "Inject errors and confirm the "
         "32-bit SSP/SMP CRC detects them; ACK/NAK behavior."},
        {"name": "Wide-port aggregation", "purpose": "Verify connections "
         "across phys sharing a SAS address."},
    ]
    d["notes"] = (
        "SAS characterization centers on the serial eye/jitter at each link "
        "rate, OOB burst timing and SAS/SATA discrimination, speed "
        "negotiation, the 8b10b/128b150b coding (running disparity, FEC "
        "capability), optional SSC, and the 32-bit CRC. Per-phy SerDes and "
        "connector/backplane calibration is done at bring-up; conformance is "
        "established by INCITS T10 SAS interoperability/compliance testing.")
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
        "INCITS T10 Serial Attached SCSI — SAS-3 (12 Gbps) and SAS-4 (22.5 "
        "Gbps)")
    f["previous_versions"] = [
        "SAS-1 (2003-2005) — 1.5/3 Gbps; initial Serial Attached SCSI.",
        "SAS-2 (2009) — 6 Gbps; expanded expander/zoning.",
        "SAS-3 (2013) — 12 Gbps; 128b150b FEC-capable encoding.",
    ]
    f["key_changes"] = [
        {"version": "SAS-2", "summary": "Doubled the link rate to 6 Gbps; "
         "added zoning and self-configuring expanders; spread-spectrum "
         "clocking refinements. 8b10b coding retained."},
        {"version": "SAS-3", "summary": "Doubled the link rate to 12 Gbps; "
         "introduced 128b150b encoding with a forward error correction "
         "capability for the higher rate; transmitter training."},
        {"version": "SAS-4", "summary": "Doubled the link rate to 22.5 Gbps "
         "with 128b150b encoding and forward error correction. SSP/STP/SMP "
         "transports, 64-bit SAS address, wide ports, and expanders are "
         "carried forward."},
    ]
    f["future_versions_industry_outline"] = [
        {"version": "SAS-4.x / SAS-5 (industry)", "summary": "Continued INCITS "
         "T10 work on higher link rates and refined PHY/FEC; the SSP/STP/SMP "
         "architecture and expander/wide-port model are preserved."},
    ]
    f["backward_compat_traps"] = [
        {"trap_name": "Coding_changes_at_12G",
         "rule": "8b10b is used at <=6 Gbps; 128b150b (FEC capable) is used at "
                 "12 and 22.5 Gbps.",
         "trap": "Assuming 8b10b at 12/22.5 Gbps is wrong; the coding and FEC "
                 "differ."},
        {"trap_name": "Three_transports_not_one",
         "rule": "SAS multiplexes SSP (SCSI), STP (SATA tunneling), and SMP "
                 "(management) over the phy.",
         "trap": "Treating SAS as SSP-only ignores STP (SATA devices) and SMP "
                 "(topology)."},
        {"trap_name": "Connection_oriented",
         "rule": "A connection (OPEN address frame, OPEN_ACCEPT) must be open "
                 "before frames flow.",
         "trap": "Sending frames without an open connection is invalid."},
        {"trap_name": "Not_SATA_not_NVMe",
         "rule": "SAS has SSP/STP/SMP, expanders, a 64-bit SAS address, and "
                 "wide ports; SATA is a single host-device FIS/AHCI link and "
                 "NVMe is queues/doorbells over PCIe.",
         "trap": "Applying SATA AHCI host-device assumptions or NVMe "
                 "queue/doorbell semantics to SAS is wrong."},
    ]
    f["version_naming_history_note"] = (
        "Serial Attached SCSI is standardized by the INCITS T10 technical "
        "committee as a series of standards: SAS-1 (1.5/3 Gbps), SAS-2 (6 "
        "Gbps), SAS-3 (12 Gbps), and SAS-4 (22.5 Gbps). Each generation "
        "roughly doubles the link rate while preserving the SSP/STP/SMP "
        "transport architecture, the 64-bit SAS address, wide ports, and "
        "expander-based topology. SAS-3 introduced 128b150b FEC-capable "
        "encoding for the higher rates.")
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
    f["link_rate_table"] = {
        "header_columns": ["Generation", "Link Rate (Gbps)", "Coding", "FEC"],
        "rows": [
            ["SAS-1", "1.5", "8b10b", "no"],
            ["SAS-1", "3", "8b10b", "no"],
            ["SAS-2", "6", "8b10b", "no"],
            ["SAS-3", "12", "128b150b", "FEC capable"],
            ["SAS-4", "22.5", "128b150b", "FEC capable"],
        ],
    }
    f["transport_protocol_table"] = {
        "header_columns": ["Protocol", "Full name", "Purpose"],
        "rows": [
            ["SSP", "Serial SCSI Protocol", "SCSI command transport"],
            ["STP", "SATA Tunneling Protocol", "Bridge SATA devices"],
            ["SMP", "Serial Management Protocol", "Expander topology "
             "management"],
        ],
    }
    f["ssp_frame_type_table"] = {
        "header_columns": ["Frame", "Purpose"],
        "rows": [
            ["COMMAND", "SCSI CDB"],
            ["TASK", "task-management function"],
            ["XFER_RDY", "transfer-ready (write flow control)"],
            ["DATA", "read/write data"],
            ["RESPONSE", "SCSI status and sense data"],
        ],
    }
    f["primitive_table"] = {
        "header_columns": ["Primitive", "Meaning"],
        "rows": [
            ["ALIGN", "dword sync / rate matching / skew"],
            ["NOTIFY", "event signal (e.g. ENABLE SPINUP)"],
            ["SOF / EOF", "Start / End of Frame"],
            ["SOAF / EOAF", "Start / End of Address Frame"],
            ["RRDY", "Receiver Ready (frame credit)"],
            ["ACK / NAK", "acknowledge / negative-acknowledge SSP frame"],
            ["CREDIT_BLOCKED", "no credit available"],
            ["OPEN_ACCEPT / OPEN_REJECT", "connection response"],
            ["AIP", "Arbitration In Progress"],
            ["CLOSE", "close connection"],
            ["BREAK", "abort connection / request"],
            ["DONE", "end of frame transmission"],
            ["HARD_RESET", "reset the attached phy"],
        ],
    }
    f["oob_table"] = {
        "header_columns": ["Signal", "Meaning"],
        "rows": [
            ["COMINIT/COMRESET", "initialization / reset OOB burst"],
            ["COMSAS", "identifies a SAS phy (SATA does not respond)"],
            ["COMWAKE", "wake OOB burst"],
            ["SNW", "Speed Negotiation Window (rate negotiation)"],
        ],
    }
    f["crc_table"] = {
        "header_columns": ["CRC", "Width (bits)", "Coverage"],
        "rows": [
            ["SSP/SMP frame CRC", "32", "frame header + information unit"],
        ],
    }
    f["encoding_note"] = (
        "SAS uses 8b10b with running disparity at <=6 Gbps and 128b150b with a "
        "forward error correction capability at 12/22.5 Gbps; data dwords are "
        "scrambled and each SSP/SMP frame carries a 32-bit CRC. OOB "
        "(COMINIT/COMSAS/COMWAKE) plus the Speed Negotiation Window handle "
        "attachment detection and rate negotiation.")
    f["tables"] = [
        "Link-rate / coding table (1.5/3/6/12/22.5 Gbps; 8b10b vs 128b150b)",
        "Transport-protocol table (SSP / STP / SMP)",
        "SSP frame-type table (COMMAND/TASK/XFER_RDY/DATA/RESPONSE)",
        "Primitive table (ALIGN/RRDY/ACK/NAK/OPEN_*/AIP/CLOSE/BREAK/DONE/...)",
        "OOB / speed-negotiation table (COMINIT/COMSAS/COMWAKE/SNW)",
        "CRC table (32-bit SSP/SMP)",
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
        "Point-to-point full-duplex serial differential phy (TX+/TX-, "
        "RX+/RX-) at 1.5/3/6/12/22.5 Gbps.",
        "8b10b coding (<=6 Gbps) and 128b150b coding with FEC capability "
        "(12/22.5 Gbps); running disparity; scrambling; 32-bit CRC.",
        "64-bit SAS address per port; wide-port aggregation of phys sharing a "
        "SAS address.",
        "Three transport protocols: SSP (SCSI), STP (SATA tunneling), SMP "
        "(management).",
        "Expander devices (edge / fanout) and an expander route table; SMP "
        "topology management.",
        "Connection-oriented link layer: OPEN address frame, AIP, "
        "OPEN_ACCEPT/OPEN_REJECT, arbitration wait time, rate matching via "
        "ALIGN, CLOSE/BREAK/DONE.",
        "RRDY credit flow control and ACK/NAK on SSP frames.",
        "OOB (COMINIT/COMSAS/COMWAKE) and the Speed Negotiation Window (SNW).",
    ]
    f["must_not_have_properties"] = [
        "A parallel SCSI (SPI) bus (SAS is point-to-point serial).",
        "A single host-to-device-only link with no expander / SSP / SMP / SAS "
        "address (that is SATA, not SAS).",
        "Submission/completion queues + doorbells over PCIe as the transport "
        "(that is NVMe, not SAS).",
        "A forwarded clock wire (SAS recovers the clock from the encoded "
        "stream).",
    ]
    f["compliance_failure_modes"] = [
        {"mode": "OPEN_REJECT", "trigger": "No destination / pathway blocked / "
         "bad destination / retry; the connection is not established."},
        {"mode": "CRC / NAK error", "trigger": "SSP frame CRC fails; the frame "
         "is NAKed and retransmitted."},
        {"mode": "Speed-negotiation failure", "trigger": "No common link rate "
         "is found in the Speed Negotiation Window."},
        {"mode": "Loss of dword synchronization", "trigger": "Code violations "
         "/ disparity errors break sync; the phy re-OOBs."},
        {"mode": "BREAK", "trigger": "A stalled connection is aborted."},
    ]
    f["min_link_constraint"] = (
        "A SAS connection requires two phys that complete OOB + speed "
        "negotiation + dword synchronization to a common link rate, matching "
        "source/destination SAS addresses, and a successful OPEN_ACCEPT before "
        "SSP/STP/SMP frames flow.")
    f["reset_behavior_compliance"] = (
        "HARD_RESET (or power-up / reset) resets the phy; the phy re-runs OOB "
        "-> Speed Negotiation Window -> dword synchronization before "
        "reopening connections.")
    f["sas_distinguishers"] = (
        "SAS is identified by ALL of: a point-to-point full-duplex serial "
        "differential phy at 1.5/3/6/12/22.5 Gbps (8b10b <=6 Gbps, 128b150b "
        "FEC-capable at 12/22.5 Gbps); three transport protocols SSP/STP/SMP "
        "multiplexed over the phy; a 64-bit SAS address per port with "
        "wide-port aggregation; expander devices (edge / fanout) routing a SAS "
        "domain with SMP management; a connection-oriented link layer (OPEN "
        "address frame, AIP, OPEN_ACCEPT/OPEN_REJECT, arbitration wait time, "
        "rate matching via ALIGN); RRDY/ACK/NAK flow control with a 32-bit "
        "CRC; and OOB (COMINIT/COMSAS/COMWAKE) + Speed Negotiation Window. "
        "This is distinct from SATA (a single host-to-device FIS/AHCI serial "
        "link with no expander, SSP, SMP, or SAS address) and from NVMe "
        "(submission/completion queues + doorbells + namespaces over PCI "
        "Express, with no SCSI or expander).")
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
        {"name": "TX+ / TX- (per phy)",
         "direction": "transmit (differential)",
         "purpose": "Outbound differential NRZ serial data of the phy.",
         "active_levels": "differential", "idle_level": "idle/ALIGN dwords"},
        {"name": "RX+ / RX- (per phy)",
         "direction": "receive (differential)",
         "purpose": "Inbound differential NRZ serial data of the phy.",
         "active_levels": "differential", "idle_level": "idle/ALIGN dwords"},
        {"name": "Wide port (phys sharing a SAS address)",
         "direction": "full-duplex aggregate",
         "purpose": "Aggregates multiple phys with the same SAS address for "
                    "bandwidth and redundancy.",
         "active_levels": "N/A", "idle_level": "N/A"},
    ]
    f["logical_signaling_levels"] = [
        {"name": "Idle / ALIGN dword", "meaning": "Link synchronized but no "
         "frame in flight between connections."},
        {"name": "Active connection", "meaning": "A connection is open; "
         "SSP/STP/SMP frames flow full-duplex."},
    ]
    f["packet_types_summary"] = [
        {"class": "SSP frame", "members": list(_SSP_FRAME_TYPES),
         "count": len(_SSP_FRAME_TYPES)},
        {"class": "Address frame", "members": ["OPEN address frame"],
         "count": 1},
        {"class": "Transport", "members": list(_TRANSPORTS),
         "count": len(_TRANSPORTS)},
    ]
    cc = _ensure_dict(f, "channel_counts")
    cc.update({
        "differential_pairs_per_phy": 2,
        "transport_count": 3,
        "ssp_frame_type_count": len(_SSP_FRAME_TYPES),
        "primitive_count": len(_PRIMITIVES),
        "sas_address_bits": _SAS_ADDRESS_BITS,
        "crc_bits": _CRC_BITS,
        "max_link_rate_Gbps": _MAX_LINK_RATE_GBPS,
        "expander_type_count": 2,
    })
    f["global_signals"] = [
        {"name": "SAS address (64-bit)", "purpose": "Worldwide-unique port "
         "identifier; matches source/destination in the OPEN address frame."},
        {"name": "Connection", "purpose": "A dedicated full-duplex path opened "
         "between two ports."},
        {"name": "SAS domain", "purpose": "The set of devices and expanders "
         "interconnected through the topology."},
    ]
    f["dependency_graph"] = {
        "common_rule": "A phy must complete OOB (COMINIT/COMSAS/COMWAKE) + the "
        "Speed Negotiation Window + dword synchronization before any "
        "connection. A connection must be open (OPEN address frame -> AIP -> "
        "OPEN_ACCEPT) before SSP/STP/SMP frames flow; expanders route the OPEN "
        "frame by SAS address using the expander route table.",
        "data_dependency": "An SSP frame requires: (1) the phy synchronized, "
        "(2) a connection open to the destination SAS address, (3) RRDY credit "
        "granted; each SSP frame is CRC-checked and ACK/NAKed. Rate matching "
        "(ALIGN) couples a slower connection rate to a faster physical link "
        "rate.",
    }
    f["handshake_pairs"] = [
        {"name": "OOB", "from": "phy", "to": "attached phy",
         "rule": "COMINIT/COMSAS/COMWAKE detect attachment and distinguish "
                 "SAS from SATA."},
        {"name": "Speed Negotiation Window", "from": "phy", "to": "attached "
         "phy", "rule": "Negotiate the highest common link rate."},
        {"name": "OPEN / OPEN_ACCEPT", "from": "originating port",
         "to": "destination port", "rule": "OPEN address frame requests a "
                 "connection; OPEN_ACCEPT opens it, OPEN_REJECT denies it."},
        {"name": "RRDY", "from": "receiver", "to": "transmitter",
         "rule": "Grants one frame of credit (flow control)."},
        {"name": "ACK / NAK", "from": "receiver", "to": "transmitter",
         "rule": "Acknowledges or rejects an SSP frame (NAK -> retransmit)."},
    ]
    f["ordering_rules"] = {
        "bit_order_on_wire": "Differential NRZ serial; 8b10b/128b150b dwords; "
        "ALIGN dwords keep synchronization.",
        "connection_order": "Connections are opened by arbitration "
        "(arbitration wait time) and torn down by CLOSE/BREAK/DONE.",
        "wide_port": "A connection may use any phy of a wide port; phys share "
        "the SAS address.",
        "transport": "SSP, STP, and SMP frames are carried inside their "
        "respective connections.",
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
        "Point-to-point serial fabric: phys aggregated into narrow / wide "
        "ports, interconnected through edge and fanout expander devices into a "
        "SAS domain. Connections are routed by 64-bit SAS address; there is no "
        "shared parallel bus.")
    f["supported_topologies"] = [
        {"name": "Direct-attach", "description": "Initiator port connected "
         "point-to-point to a target port (no expander)."},
        {"name": "Narrow port", "description": "A port with a single phy."},
        {"name": "Wide port", "description": "A port with multiple phys "
         "sharing one SAS address; a wide link connects two wide ports."},
        {"name": "Edge expander", "description": "Connects end devices; an "
         "edge expander set bounds a subtractive routing domain."},
        {"name": "Fanout expander", "description": "Connects multiple edge "
         "expander devices to build large topologies."},
    ]
    f["master_slave_role_summary"] = [
        {"role": "SAS initiator device", "description": "Originates "
         "SSP/STP/SMP connection requests and SCSI commands (e.g. an HBA)."},
        {"role": "SAS target device", "description": "Responds to commands "
         "(e.g. a SAS drive); has an SSP target port and logical units."},
        {"role": "Expander device", "description": "Routes connections among "
         "phys; contains the SMP target function and the expander route "
         "table."},
        {"role": "STP/SATA bridge", "description": "Bridges tunneled SATA "
         "traffic to a SATA device behind an expander."},
    ]
    f["interconnect_role"] = (
        "SAS is a serial storage fabric. Connections are opened on demand "
        "between ports identified by 64-bit SAS addresses; expanders route "
        "them (table / subtractive / direct). Wide ports provide aggregate "
        "bandwidth and path redundancy. SSP carries SCSI, STP tunnels SATA, "
        "and SMP manages the topology.")
    f["routing_methods"] = ["table routing", "subtractive routing",
                            "direct routing"]
    f["ordering_guarantees"] = {
        "connection": "A connection is a dedicated full-duplex path until "
        "CLOSE; frames are ordered within the connection.",
        "wide_port": "Connections may be spread across the phys of a wide "
        "port.",
        "arbitration": "Contention is resolved by arbitration wait time across "
        "the SAS domain.",
    }
    f["memory_vs_peripheral_regions"] = (
        "SAS is not memory-mapped; connections and frames are addressed by "
        "64-bit SAS address (and SCSI LUN within an SSP target), not by a "
        "memory or peripheral address. Management uses SMP request/response.")
    dc = _ensure_dict(f, "device_classification")
    dc["initiator"] = "Originates connections and SCSI commands (e.g. HBA)."
    dc["target"] = "Responds to commands; SSP target port + logical units."
    dc["edge_expander"] = "Connects end devices; subtractive routing domain."
    dc["fanout_expander"] = "Connects multiple edge expanders."
    dc["stp_sata_bridge"] = "Bridges tunneled SATA to a SATA device."
    f["default_signal_values_evidence_tables"] = [
        "SAS layered architecture (phy / link / port / transport / "
        "application)",
        "SAS domain topology figure (initiators / targets / edge / fanout "
        "expanders)",
        "Wide-port aggregation figure (phys sharing a SAS address)",
        "Connection-management figure (OPEN address frame / AIP / "
        "OPEN_ACCEPT)",
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
        "signaling": "differential NRZ serial (TX+/TX-, RX+/RX-) per phy",
        "line_encoding": "8b10b (<=6 Gbps) / 128b150b FEC-capable (12/22.5 "
                         "Gbps)",
        "link_rates_Gbps": list(_LINK_RATES_GBPS),
        "max_link_rate_Gbps": _MAX_LINK_RATE_GBPS,
        "clocking": "embedded (CDR); optional spread-spectrum clocking (SSC)",
        "sas_address_bits": _SAS_ADDRESS_BITS,
        "crc_bits": _CRC_BITS,
        "transports": list(_TRANSPORTS),
        "wide_port": True,
        "expander_types": ["edge expander", "fanout expander"],
    }
    f["notes"] = (
        "SAS is a serial interconnect standard (INCITS T10): it fixes the "
        "differential serial phy model (1.5/3/6/12/22.5 Gbps, 8b10b/128b150b, "
        "OOB + speed negotiation, optional SSC), the connection-oriented link "
        "layer, the SSP/STP/SMP transports, the 64-bit SAS address, wide-port "
        "aggregation, and the expander topology. It does NOT impose PDK-"
        "specific SDC / floorplan constraints; SerDes electrical "
        "characterization, connector, and backplane design are physical-layer "
        "/ board concerns. The interoperability-critical constraints are the "
        "coding/FEC, OOB/SNW, connection management, and the 32-bit CRC.")
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
        {"name": "SMP REPORT PHY ERROR LOG", "purpose": "Per-phy error "
         "counters (invalid dword, running-disparity, loss-of-dword-sync, phy "
         "reset problem)."},
        {"name": "SMP DISCOVER / REPORT GENERAL", "purpose": "Topology and phy "
         "state observability."},
        {"name": "PHY test patterns / loopback", "purpose": "Physical-layer "
         "characterization and BER measurement."},
        {"name": "OOB / speed-negotiation status", "purpose": "Attachment and "
         "rate-negotiation observability."},
        {"name": "CRC / ACK-NAK status", "purpose": "Frame-level error "
         "observability."},
    ]
    f["internal_diagnostics_observability"] = [
        "Phy state (OOB / speed negotiation / dword sync / ready).",
        "Negotiated link rate per phy.",
        "Connection outcomes (OPEN_ACCEPT / OPEN_REJECT / AIP / BREAK).",
        "Per-phy error log counters via SMP.",
        "SSP frame CRC / ACK / NAK results.",
    ]
    f["out_of_band_test_facilities"] = [
        "INCITS T10 SAS interoperability / compliance testing.",
        "Vendor SerDes / controller bring-up and characterization tooling "
        "(implementation-defined).",
    ]
    f["notes"] = (
        "SAS's protocol-level DFT surface is SMP (REPORT GENERAL / DISCOVER / "
        "REPORT PHY ERROR LOG), the OOB/speed-negotiation status, connection "
        "outcomes, per-frame CRC/ACK-NAK results, and physical-layer test "
        "patterns / loopback. Chip-level JTAG / scan / BIST remain controller-"
        "vendor / SoC-integrator concerns; conformance is established by "
        "INCITS T10 compliance testing.")
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
        {"state": "Active", "name": "Active", "description": "Phy "
         "synchronized; connections may be open and frames flowing."},
        {"state": "Partial", "name": "Partial", "description": "Phy power "
         "condition with reduced power and fast wake."},
        {"state": "Slumber", "name": "Slumber", "description": "Deeper phy "
         "power condition with longer wake latency."},
    ]
    f["wakeup_mechanism"] = (
        "Phy power management (partial / slumber) is entered and exited via "
        "NOTIFY (ENABLE SPINUP) and the phy power-management primitives; the "
        "phy can reduce power while remaining able to wake on activity (COMWAKE "
        "/ OOB).")
    f["power_rails"] = [
        {"rail": "VDD (SerDes / controller)", "purpose": "Logic and SerDes "
         "supply."},
        {"rail": "Drive / device power", "purpose": "Supplied through the SAS "
         "connector (with ENABLE SPINUP staggered spin-up)."},
        {"rail": "GND", "purpose": "Ground."},
    ]
    f["sas_power_considerations"] = (
        "SAS defines phy power conditions (active / partial / slumber) and "
        "staggered spin-up of drives via NOTIFY (ENABLE SPINUP) to bound "
        "inrush current; most energy management is a SerDes / device concern, "
        "while the protocol contributes the phy power-management primitives.")
    f["notes"] = (
        "SAS's protocol-level power intent is the phy power conditions "
        "(partial / slumber) and staggered spin-up (NOTIFY ENABLE SPINUP) "
        "rather than a fine-grained power-domain spec. Detailed rails and "
        "low-power SerDes behavior are physical-layer / implementation "
        "concerns.")
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
        "Phy bring-up — OOB (COMINIT/COMSAS/COMWAKE) + Speed Negotiation "
        "Window + dword sync.",
        "Link rates — 1.5/3/6/12/22.5 Gbps; 8b10b vs 128b150b coding; FEC "
        "capability.",
        "SAS address — 64-bit assignment and matching; wide-port aggregation.",
        "Connection management — OPEN address frame, AIP, OPEN_ACCEPT, "
        "OPEN_REJECT, arbitration wait time, rate matching via ALIGN.",
        "SSP — COMMAND/TASK/XFER_RDY/DATA/RESPONSE frames; RRDY credit; "
        "ACK/NAK.",
        "STP — SATA FIS tunneling through an STP/SATA bridge.",
        "SMP — REPORT GENERAL / DISCOVER / REPORT PHY ERROR LOG / CONFIGURE "
        "ROUTE INFORMATION.",
        "CRC — 32-bit SSP/SMP CRC error injection and detection; scrambling.",
        "Expander routing — table / subtractive / direct; edge and fanout "
        "expanders.",
        "Primitives — ALIGN/NOTIFY/SOF/EOF/SOAF/EOAF/CLOSE/BREAK/DONE/"
        "HARD_RESET.",
        "Phy power management — partial / slumber; staggered spin-up.",
        "Error handling — OPEN_REJECT classes, BREAK, phy error log.",
    ]
    f["notes"] = (
        "SAS does not ship an embedded testbench, but the standard implies a "
        "verification plan spanning the physical layer (eye/jitter, OOB, "
        "speed negotiation, coding/FEC), the connection-oriented link layer, "
        "the SSP/STP/SMP transports, the 32-bit CRC and flow control, "
        "expander routing, and phy power management. INCITS T10 compliance / "
        "interoperability testing supplies the formal suite.")
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
        "32-bit CRC per SSP/SMP frame detects frame corruption.",
        "ACK/NAK acknowledges or rejects each SSP frame (NAK -> retransmit).",
        "8b10b running-disparity / code-violation detection of invalid "
        "dwords.",
        "128b150b forward error correction capability at 12/22.5 Gbps.",
        "Scrambling spreads spectral energy (EMI), not a security feature.",
        "Expander pathway recovery and BREAK resolve blocked / deadlocked "
        "routing.",
    ]
    f["anti_tampering_features"] = []
    f["confidentiality_features"] = []
    f["authentication_features"] = []
    f["future_security_pointers"] = [
        "SAS's base protocol provides no cryptographic confidentiality or "
        "authentication on the data path; the CRC and FEC are anti-corruption "
        "/ error-correction only.",
        "Storage-level security (e.g. SCSI security commands, T10 protection "
        "information / DIF, self-encrypting drives, zoning for access control) "
        "is layered above the SAS transport.",
    ]
    f["notes"] = (
        "SAS is a serial storage transport: its built-in protections are "
        "anti-corruption and error-correction (32-bit CRC, ACK/NAK, 8b10b "
        "disparity, 128b150b FEC) plus zoning for topology access control. "
        "The link carries plaintext frames. Cryptographic confidentiality / "
        "authentication are NOT part of the base SAS data path; they are "
        "provided by higher-layer SCSI security features or self-encrypting "
        "drives above the protocol.")
    _write(p, d)
