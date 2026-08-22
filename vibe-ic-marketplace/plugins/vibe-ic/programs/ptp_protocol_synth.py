"""IEEE 1588 Precision Time Protocol (PTP) synth helper (protocol #76).

ic_class-gated overlay for the PTP structural signature: sub-microsecond
clock synchronization of distributed real-time clocks over a packet network,
standardized by IEEE 1588 (PTPv2: IEEE 1588-2008/2019) with the IEEE 802.1AS
(gPTP) profile. A master-slave clock hierarchy is elected by the Best Master
Clock Algorithm (BMCA); the root is the Grandmaster. Event messages (Sync,
Delay_Req, Pdelay_Req, Pdelay_Resp) are hardware-timestamped at the MAC/PHY
plane to capture T1/T2/T3/T4; the slave computes offsetFromMaster and
meanPathDelay and disciplines its local clock. General messages (Follow_Up,
Delay_Resp, Pdelay_Resp_Follow_Up, Announce, Signaling, Management) carry data.
PTP clock types are the Ordinary Clock (OC), Boundary Clock (BC), and
Transparent Clock (TC, end-to-end / peer-to-peer) which adds residence time to
the message correctionField. Transport is over Ethernet (Layer 2, EtherType
0x88F7) or UDP/IPv4/IPv6 (event port 319, general port 320). Applies the IEEE
1588 / 802.1AS spec-canonical content to L1-L23.

Doctrine — GENERAL not keyword: detection uses canonical STRUCTURAL signatures
(Sync/Follow_Up + Delay_Req/Delay_Resp or Pdelay messages + BMCA + Grandmaster
+ Ordinary/Boundary/Transparent Clock + T1..T4 timestamps with
offsetFromMaster/meanPathDelay + correctionField) read from the L-doc /
input_doc CONTENT blob only. It NEVER reads the input-document filename or the
benchmark folder name, and it does NOT fire on the bare token "ptp" alone — a
real PTP timing structure is required.

Sibling disambiguation — PTP rides ON Ethernet (and over UDP), so a PTP spec
will inevitably mention Ethernet / MAC / frame / 802.3. The runner's inline
is_ethernet sub-detector therefore fires first; this synth runs AFTER the
Ethernet synth and force-overwrites. The detector DEFERS when the document is
plain-Ethernet-primary (MII/MDIO/MAC/frame transport with NO PTP messages,
BMCA, Grandmaster, or PTP clock types) or AFDX-primary (Virtual Link / BAG /
ARINC 664), so it cannot false-fire on a plain-Ethernet or AFDX spec. It
REQUIRES the PTP timing structure, not the Ethernet transport.

Public entry: ``apply_ptp_synth(generated_docs_dir, is_ptp, ptp_ic_name)``.
Module-level ``is_ptp(blob)`` is the content-only detector.
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

# Canonical IEEE 1588 PTP facts (IEEE 1588-2008/2019 PTPv2; IEEE 802.1AS gPTP).
_EVENT_MESSAGES = ["Sync", "Delay_Req", "Pdelay_Req", "Pdelay_Resp"]
_GENERAL_MESSAGES = [
    "Follow_Up", "Delay_Resp", "Pdelay_Resp_Follow_Up", "Announce",
    "Signaling", "Management",
]
_ALL_MESSAGES = _EVENT_MESSAGES + _GENERAL_MESSAGES
_CLOCK_TYPES = [
    "Ordinary Clock (OC)", "Boundary Clock (BC)",
    "Transparent Clock (TC, end-to-end / peer-to-peer)",
]
_TIMESTAMPS = ["T1", "T2", "T3", "T4"]
_ETHERTYPE = "0x88F7"
_UDP_EVENT_PORT = 319
_UDP_GENERAL_PORT = 320
_CORRECTION_FIELD_BITS = 64
_PORT_STATES = [
    "INITIALIZING", "LISTENING", "PRE_MASTER", "MASTER", "PASSIVE",
    "UNCALIBRATED", "SLAVE", "FAULTY", "DISABLED",
]


def _wb(token: str, low: str) -> bool:
    """Word-boundary token test (case-insensitive; token already lowered)."""
    return re.search(r"\b" + re.escape(token) + r"\b", low) is not None


def is_ptp(blob: str) -> bool:
    """Content-only IEEE 1588 PTP detector with a plain-Ethernet / AFDX MUTEX.

    Fire on the PTP structural signature: the Sync / Follow_Up + Delay_Req /
    Delay_Resp (or the Pdelay) message exchange + the Best Master Clock
    Algorithm + a Grandmaster + the Ordinary / Boundary / Transparent clock
    types + the T1..T4 timestamps with offsetFromMaster / meanPathDelay + the
    correctionField. Defer if the doc is plain-Ethernet-primary (MII / MDIO /
    MAC / frame transport with NO PTP messages, BMCA, Grandmaster, or PTP clock
    types) or AFDX-primary (Virtual Link / BAG / ARINC 664), so a plain
    Ethernet or AFDX spec cannot false-fire. PTP rides on Ethernet so it WILL
    mention Ethernet — this detector requires the PTP timing structure, not the
    Ethernet transport. Reads ONLY the spec text `blob` — never a filename or
    benchmark name; the bare token "ptp" alone is never sufficient.
    """
    if not blob:
        return False
    low = blob.lower()

    # --- PTP-only structural tokens (absent from a plain-Ethernet/AFDX spec). ---
    # Synchronization messages (word-boundary; underscores are word chars).
    sync_msg = _wb("sync", low)
    follow_up = "follow_up" in low or "follow-up" in low or "followup" in low
    delay_req = "delay_req" in low or "delay request" in low or "delay-request" in low
    delay_resp = "delay_resp" in low or "delay response" in low or "delay-response" in low
    pdelay = ("pdelay_req" in low or "pdelay_resp" in low
              or "peer delay" in low or "peer-delay" in low
              or "pdelay" in low)
    announce = "announce" in low

    # The delay-request-response OR the peer-delay mechanism must be present.
    delay_mechanism = (delay_req and delay_resp) or pdelay

    # BMCA + grandmaster + clock types.
    bmca = ("best master clock" in low or "bmca" in low)
    grandmaster = ("grandmaster" in low or "grand master" in low)
    ordinary_clock = ("ordinary clock" in low
                      or _wb("oc", low) and "boundary clock" in low)
    boundary_clock = "boundary clock" in low
    transparent_clock = ("transparent clock" in low
                         or "residence time" in low)
    clock_types = sum(bool(x) for x in
                      (ordinary_clock, boundary_clock, transparent_clock)) >= 2

    # T1..T4 timestamps + offset/delay computation.
    timestamps = (("t1" in low and "t2" in low and "t3" in low and "t4" in low)
                  or "offsetfrommaster" in low or "offset from master" in low
                  or "meanpathdelay" in low or "mean path delay" in low)
    offset_delay = ("offsetfrommaster" in low or "offset from master" in low
                    or "meanpathdelay" in low or "mean path delay" in low)
    correction_field = "correctionfield" in low or "correction field" in low

    # PTP / IEEE 1588 name anchors (not sufficient alone — used as a corroborator).
    name_token = ("ieee 1588" in low or "ieee1588" in low
                  or "precision time protocol" in low
                  or "ptpv2" in low or "802.1as" in low or "gptp" in low)

    # Master-slave timing hierarchy (PTP-specific phrasing).
    master_slave = ("master-slave" in low or "master slave" in low
                    or ("master" in low and "slave" in low
                        and ("clock" in low or "port" in low)))

    # ---- Sibling MUTEX: AFDX-primary doc (defer). --------------------------
    # AFDX (ARINC 664 Part 7) is an avionics Ethernet variant keyed on Virtual
    # Links + Bandwidth Allocation Gap. A real PTP doc carries none of those.
    afdx_primary = (
        ("virtual link" in low or "afdx" in low or "arinc 664" in low
         or "arinc664" in low or "bandwidth allocation gap" in low
         or _wb("bag", low) and "virtual link" in low)
        and not (bmca or grandmaster or delay_mechanism
                 or correction_field or name_token)
    )
    if afdx_primary:
        return False

    # ---- Sibling MUTEX: plain-Ethernet-primary doc (defer). ----------------
    # A plain Ethernet MAC/PHY spec is keyed on MII/MDIO/PHY/MAC/frame/preamble
    # and carries NO PTP message set, BMCA, Grandmaster, or PTP clock types.
    ethernet_primary = (
        ("mii" in low or "mdio" in low or "preamble" in low
         or "media access control" in low or "802.3" in low)
        and not (bmca or grandmaster or delay_mechanism
                 or transparent_clock or correction_field
                 or (sync_msg and follow_up))
    )
    if ethernet_primary:
        return False

    # ---- Core PTP structural signature. -----------------------------------
    # Require the timing-protocol substance, not merely the Ethernet carrier:
    #   (1) the Sync/Follow_Up + a delay (E2E or P2P) mechanism,
    #   (2) the BMCA + a Grandmaster (the master-slave election), and
    #   (3) at least two PTP clock types OR the T1..T4 / offset+delay /
    #       correctionField timing computation.
    ptp_messages = (sync_msg and (follow_up or announce)) and delay_mechanism
    ptp_hierarchy = bmca and grandmaster and master_slave
    ptp_timing = clock_types or (timestamps and offset_delay) or correction_field

    ptp_structure = ptp_messages and ptp_hierarchy and ptp_timing

    return bool(
        ptp_structure
        # Name-anchored fallback still REQUIRES real PTP structure (not bare
        # "ptp"): the message exchange + the master/grandmaster hierarchy.
        or (name_token and ptp_messages and (grandmaster or bmca)
            and (clock_types or correction_field or offset_delay))
    )


def apply_ptp_synth(generated_docs_dir: Path, is_ptp_flag: bool,
                    ptp_ic_name: Optional[str]) -> None:
    """Apply IEEE 1588 PTP (PTPv2 / 802.1AS) synth when the PTP signature matched."""
    if not is_ptp_flag:
        return
    gd = Path(generated_docs_dir)

    # --- Force ic_name across ALL 24 docs FIRST (main + fields docs). ---
    if ptp_ic_name is not None:
        for n in _MAIN_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                d["ic_name"] = ptp_ic_name
                _write(q, d)
        for n in _FIELDS_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                f = _ensure_dict(d, "fields")
                f["ic_name"] = ptp_ic_name
                d["ic_name"] = ptp_ic_name
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
# L1 — PTP datasheet header + headline facts.
# ----------------------------------------------------------------------
def _l1(gd: Path) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    d["document_title"] = ("IEEE 1588 Precision Time Protocol (PTP) Clock "
                           "Synchronization Engine")
    d["version"] = ("IEEE Std 1588-2008 / IEEE Std 1588-2019 (PTPv2); IEEE "
                    "802.1AS (gPTP) profile")
    d["revised_date"] = "IEEE 1588-2008 (PTPv2); IEEE 1588-2019; 802.1AS"
    d["manufacturer"] = "IEEE 1588 Working Group"
    d["copyright"] = "© IEEE — Precision Time Protocol"
    d["abstract"] = (
        "The Precision Time Protocol (PTP), standardized as IEEE 1588 (PTPv2: "
        "IEEE 1588-2008/2019), synchronizes the real-time clocks of networked "
        "nodes to sub-microsecond accuracy over a packet network. A "
        "master-slave clock hierarchy is established by the Best Master Clock "
        "Algorithm (BMCA); the root of the hierarchy is the Grandmaster clock. "
        "Event messages (Sync, Delay_Req, Pdelay_Req, Pdelay_Resp) are "
        "hardware-timestamped at the MAC/PHY plane to capture T1/T2/T3/T4; the "
        "slave computes the offset from master and the mean path delay and "
        "disciplines its local clock with a servo. General messages (Follow_Up, "
        "Delay_Resp, Pdelay_Resp_Follow_Up, Announce, Signaling, Management) "
        "carry data. PTP nodes are Ordinary Clocks (OC), Boundary Clocks (BC), "
        "or Transparent Clocks (TC, end-to-end / peer-to-peer); a Transparent "
        "Clock adds its residence time to the message correctionField. PTP is "
        "carried over Ethernet (Layer 2, EtherType 0x88F7) or UDP/IPv4/IPv6 "
        "(event port 319, general port 320), and the IEEE 802.1AS (gPTP) "
        "profile adapts it for AVB/TSN.")
    d["keywords"] = [
        "PTP", "IEEE 1588", "Precision Time Protocol", "PTPv2", "802.1AS",
        "gPTP", "Best Master Clock Algorithm", "BMCA", "Grandmaster",
        "master-slave", "Sync", "Follow_Up", "Delay_Req", "Delay_Resp",
        "Pdelay_Req", "Pdelay_Resp", "Pdelay_Resp_Follow_Up", "Announce",
        "Signaling", "Management", "Ordinary Clock", "Boundary Clock",
        "Transparent Clock", "residence time", "correctionField",
        "offsetFromMaster", "meanPathDelay", "T1", "T2", "T3", "T4",
        "hardware timestamping", "EtherType 0x88F7", "UDP 319", "UDP 320",
        "domain", "clockClass", "clockAccuracy", "servo", "PI controller",
    ]
    d["external_pins"] = [
        "Network MAC/PHY interface (PTP messages are carried over Ethernet "
        "0x88F7 or UDP/IPv4/IPv6)",
        "Hardware-timestamp capture strobe at the MAC/PHY reference plane "
        "(samples the PTP clock counter on event-message start)",
        "PTP clock / 1PPS + ToD output (the disciplined local time, e.g. a "
        "1-pulse-per-second and time-of-day output)",
        "Reference oscillator input to the local clock that the servo "
        "disciplines",
    ]
    d["ptp_versions"] = ["IEEE 1588-2002 (PTPv1)", "IEEE 1588-2008 (PTPv2)",
                         "IEEE 1588-2019", "IEEE 802.1AS (gPTP)"]
    d["event_messages"] = list(_EVENT_MESSAGES)
    d["general_messages"] = list(_GENERAL_MESSAGES)
    d["clock_types"] = list(_CLOCK_TYPES)
    d["transport_ethertype"] = _ETHERTYPE
    d["udp_event_port"] = _UDP_EVENT_PORT
    d["udp_general_port"] = _UDP_GENERAL_PORT
    d["modes_of_operation"] = [
        {"name": "Ordinary Clock (OC)",
         "role": "single-port end node (Grandmaster or slave)",
         "note": "A clock with one PTP port; either the Grandmaster time "
                 "source or a slave-only node that synchronizes to its "
                 "master."},
        {"name": "Boundary Clock (BC)",
         "role": "multi-port clock that terminates and regenerates PTP",
         "note": "One port is SLAVE to an upstream master; the other ports are "
                 "MASTER to downstream slaves, isolating timing domains."},
        {"name": "Transparent Clock (TC)",
         "role": "switch/bridge that corrects residence time",
         "note": "Measures the residence time of each event message and adds "
                 "it to the correctionField; end-to-end (E2E) or peer-to-peer "
                 "(P2P) variant."},
        {"name": "One-step vs two-step",
         "role": "Sync timestamping mode",
         "note": "A one-step clock writes T1 into the Sync on the fly; a "
                 "two-step clock sends the precise T1 in a Follow_Up message."},
    ]
    d["key_features"] = [
        "Sub-microsecond clock synchronization over a packet network "
        "(IEEE 1588 PTPv2); typically tens of nanoseconds with hardware "
        "timestamping.",
        "Master-slave clock hierarchy elected by the Best Master Clock "
        "Algorithm (BMCA); the root is the Grandmaster.",
        "Event messages Sync / Delay_Req / Pdelay_Req / Pdelay_Resp are "
        "timestamped; general messages Follow_Up / Delay_Resp / "
        "Pdelay_Resp_Follow_Up / Announce / Signaling / Management carry data.",
        "Delay-request-response (end-to-end) mechanism uses T1/T2/T3/T4 to "
        "compute offsetFromMaster and meanPathDelay; the peer-delay (P2P) "
        "mechanism measures link delay.",
        "Clock types: Ordinary Clock (OC), Boundary Clock (BC), Transparent "
        "Clock (TC end-to-end / peer-to-peer) with residence-time correction "
        "via the correctionField.",
        "Hardware timestamping at the MAC/PHY reference plane removes variable "
        "software/queueing latency from the T1..T4 captures.",
        "A servo / PI controller disciplines the local clock frequency and "
        "phase to drive offsetFromMaster toward zero.",
        "Transport over Ethernet (Layer 2, EtherType 0x88F7) or UDP/IPv4/IPv6 "
        "(event port 319, general port 320); PTP domains (domainNumber) keep "
        "independent hierarchies.",
        "Profiles: default delay-request-response (E2E) and peer-to-peer "
        "(P2P), IEEE 802.1AS (gPTP) for AVB/TSN, power (C37.238), telecom "
        "(ITU-T G.8275).",
    ]
    d["topology_summary"] = (
        "A master-slave hierarchy rooted at the Grandmaster, elected by the "
        "BMCA. Ordinary Clocks are leaf/source nodes; Boundary Clocks "
        "terminate and regenerate PTP at network boundaries; Transparent "
        "Clocks correct residence time as messages transit switches. The "
        "hierarchy spans a PTP domain.")
    d["use_cases"] = [
        "Time-Sensitive Networking (TSN) and Audio/Video Bridging (AVB) via "
        "IEEE 802.1AS (gPTP)",
        "Telecom / mobile backhaul frequency and phase/time sync (ITU-T "
        "G.8275)",
        "Electric power system synchronization (IEEE C37.238 power profile)",
        "Industrial automation and motion control",
        "Test and measurement / data-acquisition time alignment",
        "Financial-trading timestamp traceability",
    ]
    d["revision_history"] = [
        {"version": "IEEE 1588-2002 (PTPv1)", "date": "2002",
         "description": "Original Precision Time Protocol."},
        {"version": "IEEE 1588-2008 (PTPv2)", "date": "2008",
         "description": "Redesigned message set, Transparent Clocks, peer "
                        "delay mechanism, correctionField, profiles."},
        {"version": "IEEE 802.1AS (gPTP)", "date": "2011 / 2020",
         "description": "Generalized PTP profile for TSN/AVB: peer delay on "
                        "every link, two-step Sync+Follow_Up, Layer-2 0x88F7."},
        {"version": "IEEE 1588-2019", "date": "2019",
         "description": "High-accuracy enhancements, modular profiles, "
                        "security TLVs."},
    ]
    d["overview"] = (
        "IEEE 1588 PTP is a master-slave protocol that synchronizes "
        "distributed clocks to a single reference — the Grandmaster — elected "
        "by the Best Master Clock Algorithm. In each communication path one "
        "port is MASTER (time source) and one is SLAVE (time receiver). The "
        "master periodically sends a Sync message; its precise transmit time "
        "T1 is either embedded (one-step) or sent in a Follow_Up (two-step). "
        "The slave timestamps Sync arrival as T2, sends a Delay_Req at T3, and "
        "the master returns the receive time T4 in a Delay_Resp. With a "
        "symmetric link the slave computes meanPathDelay = [(T2-T1)+(T4-T3)]/2 "
        "and offsetFromMaster = [(T2-T1)-(T4-T3)]/2, then disciplines its local "
        "clock to drive the offset to zero. The peer-delay mechanism "
        "(Pdelay_Req/Pdelay_Resp/Pdelay_Resp_Follow_Up) instead measures the "
        "delay of each link directly and is used by the peer-to-peer profile "
        "and IEEE 802.1AS. Transparent Clocks add their residence time to the "
        "correctionField so switching delay does not bias the result. Accuracy "
        "depends on timestamping event messages in hardware at the MAC/PHY "
        "plane. PTP is carried over Ethernet (EtherType 0x88F7) or "
        "UDP/IPv4/IPv6 (ports 319/320), organized into independent domains.")
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
        "Distributed clock-synchronization protocol (IEEE 1588 PTPv2): a "
        "master-slave hierarchy elected by the BMCA, rooted at the "
        "Grandmaster, exchanging timestamped event messages to synchronize "
        "real-time clocks to sub-microsecond accuracy over a packet network.")
    po["duplex"] = (
        "Bidirectional message exchange: the master sends Sync (and Announce); "
        "the slave sends Delay_Req; the peer-delay mechanism is symmetric per "
        "link. Carried over the underlying full-duplex Ethernet / UDP link.")
    po["synchronous_serial"] = False
    po["source_synchronous"] = False
    po["embedded_clock"] = False
    po["forwarded_clock"] = False
    po["packet_based"] = True
    po["clock_synchronization"] = True
    po["accuracy"] = ("sub-microsecond (tens of nanoseconds with hardware "
                      "timestamping)")
    po["master_slave"] = (
        "Per port and per domain, the BMCA assigns the MASTER (time source), "
        "SLAVE (time receiver), or PASSIVE state; the root is the "
        "Grandmaster.")
    po["sync_mechanisms"] = [
        "delay-request-response (end-to-end): Sync/Follow_Up + "
        "Delay_Req/Delay_Resp with T1/T2/T3/T4",
        "peer-delay (peer-to-peer): Pdelay_Req/Pdelay_Resp/"
        "Pdelay_Resp_Follow_Up measuring link delay",
    ]
    po["event_messages"] = list(_EVENT_MESSAGES)
    po["general_messages"] = list(_GENERAL_MESSAGES)
    po["clock_types"] = list(_CLOCK_TYPES)
    po["timestamps"] = list(_TIMESTAMPS)
    po["correction_field_bits"] = _CORRECTION_FIELD_BITS
    po["transport"] = (
        "Ethernet Layer 2 (EtherType 0x88F7) or UDP/IPv4/IPv6 (event port "
        "319, general port 320); organized into PTP domains.")
    po["topology"] = (
        "Grandmaster -> (Transparent / Boundary Clocks) -> Ordinary Clock "
        "slaves; a master-slave hierarchy within a PTP domain.")
    d["functional_requirements"] = [
        {"id": "FR-SYNC-01", "text": "The node shall implement the "
         "Sync / Follow_Up exchange and the Delay_Req / Delay_Resp exchange "
         "(the delay-request-response mechanism), capturing the event "
         "timestamps T1, T2, T3, and T4."},
        {"id": "FR-PDELAY-02", "text": "The node shall implement the peer "
         "delay mechanism (Pdelay_Req / Pdelay_Resp / Pdelay_Resp_Follow_Up) "
         "for the peer-to-peer profile and IEEE 802.1AS."},
        {"id": "FR-OFFSET-03", "text": "The node shall compute offsetFromMaster "
         "and meanPathDelay from the captured timestamps and subtract the "
         "accumulated correctionField."},
        {"id": "FR-SERVO-04", "text": "The node shall discipline its local "
         "clock (frequency and phase) via a servo / PI controller to drive "
         "offsetFromMaster toward zero."},
        {"id": "FR-BMCA-05", "text": "The node shall run the Best Master Clock "
         "Algorithm using received Announce messages to determine the "
         "Grandmaster and the MASTER / SLAVE / PASSIVE state of each port."},
        {"id": "FR-CLKTYPE-06", "text": "The node shall be configurable as an "
         "Ordinary Clock, a Boundary Clock, or a Transparent Clock "
         "(end-to-end or peer-to-peer)."},
        {"id": "FR-TC-07", "text": "When configured as a Transparent Clock the "
         "node shall measure the residence time of each event message and add "
         "it to the correctionField."},
        {"id": "FR-TS-08", "text": "The node shall timestamp event messages in "
         "hardware at the MAC/PHY reference plane (hardware timestamping) for "
         "sub-microsecond accuracy."},
        {"id": "FR-XPORT-09", "text": "The node shall support PTP over Ethernet "
         "(EtherType 0x88F7) and/or UDP/IPv4/IPv6 (event port 319, general "
         "port 320)."},
        {"id": "FR-DOMAIN-10", "text": "The node shall support PTP domains "
         "(domainNumber); clocks in distinct domains shall not interact."},
        {"id": "FR-PROFILE-11", "text": "The node shall support the default "
         "delay-request-response and peer-to-peer profiles and the IEEE "
         "802.1AS (gPTP) profile."},
        {"id": "FR-MSG-12", "text": "The node shall encode/decode the PTP "
         "common header and all PTP message types (Sync, Delay_Req, "
         "Pdelay_Req, Pdelay_Resp, Follow_Up, Delay_Resp, "
         "Pdelay_Resp_Follow_Up, Announce, Signaling, Management)."},
    ]
    d["error_response_conditions"] = [
        "announceReceiptTimeout — the slave no longer hears its master; the "
        "BMCA re-runs and may re-elect a Grandmaster.",
        "syncReceiptTimeout — synchronization is lost; the port enters "
        "UNCALIBRATED / LISTENING.",
        "Asymmetry error — an asymmetric link delay biases offsetFromMaster "
        "(corrected by a configured asymmetry value or the peer delay "
        "mechanism).",
        "Domain mismatch — a message with a foreign domainNumber is ignored.",
        "Holdover — if the master is lost the servo holds over on the local "
        "oscillator.",
    ]
    d["compliance_requirements"] = [
        "Exchange Sync / Follow_Up and Delay_Req / Delay_Resp (or the Pdelay "
        "mechanism) and capture T1/T2/T3/T4.",
        "Compute offsetFromMaster and meanPathDelay and subtract the "
        "correctionField.",
        "Run the BMCA and converge deterministically on the correct "
        "Grandmaster.",
        "Provide hardware timestamps at the MAC/PHY plane with the specified "
        "resolution.",
        "Maintain synchronization within the profile's accuracy budget "
        "(sub-microsecond for default / 802.1AS).",
        "When a Transparent Clock, accumulate residence time into the "
        "correctionField.",
        "Support Ethernet (0x88F7) and/or UDP (319/320) transport and PTP "
        "domains.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L3 — message / protocol model.
# ----------------------------------------------------------------------
def _l3(gd: Path) -> None:
    p = gd / "L3_CMD_PROTOCOL.json"
    if not p.is_file():
        return
    d = _read(p)
    d["protocol_type"] = (
        "Message-based clock-synchronization protocol (IEEE 1588 PTPv2). Event "
        "messages (Sync, Delay_Req, Pdelay_Req, Pdelay_Resp) are timestamped "
        "on TX/RX; general messages (Follow_Up, Delay_Resp, "
        "Pdelay_Resp_Follow_Up, Announce, Signaling, Management) carry data. A "
        "master-slave hierarchy elected by the BMCA, rooted at the "
        "Grandmaster, exchanges these messages to compute offsetFromMaster and "
        "meanPathDelay and discipline each slave's clock.")
    d["message_classes"] = [
        {"class": "Event", "timestamped": True,
         "members": list(_EVENT_MESSAGES),
         "note": "Timestamped on transmission and reception; PTP accuracy "
                 "depends on their timestamp precision."},
        {"class": "General", "timestamped": False,
         "members": list(_GENERAL_MESSAGES),
         "note": "Carry data; not timestamped."},
    ]
    d["message_types"] = [
        {"name": "Sync", "messageType_hex": "0x0", "class": "event",
         "purpose": "Master broadcasts the synchronization message carrying or "
                    "referencing the transmit timestamp T1."},
        {"name": "Delay_Req", "messageType_hex": "0x1", "class": "event",
         "purpose": "Slave sends a delay request; its transmit time is T3."},
        {"name": "Pdelay_Req", "messageType_hex": "0x2", "class": "event",
         "purpose": "Peer delay request (peer-to-peer mechanism)."},
        {"name": "Pdelay_Resp", "messageType_hex": "0x3", "class": "event",
         "purpose": "Peer delay response (peer-to-peer mechanism)."},
        {"name": "Follow_Up", "messageType_hex": "0x8", "class": "general",
         "purpose": "Two-step: carries the precise transmit timestamp T1 of "
                    "the preceding Sync."},
        {"name": "Delay_Resp", "messageType_hex": "0x9", "class": "general",
         "purpose": "Master returns T4, the receive time of the slave's "
                    "Delay_Req."},
        {"name": "Pdelay_Resp_Follow_Up", "messageType_hex": "0xA",
         "class": "general",
         "purpose": "Carries the precise turnaround timestamps for the "
                    "peer-to-peer mechanism."},
        {"name": "Announce", "messageType_hex": "0xB", "class": "general",
         "purpose": "Carries the clock-quality attributes (clockClass, "
                    "clockAccuracy, offsetScaledLogVariance, priority1, "
                    "priority2, grandmasterIdentity) used by the BMCA."},
        {"name": "Signaling", "messageType_hex": "0xC", "class": "general",
         "purpose": "Negotiation of unicast and other options."},
        {"name": "Management", "messageType_hex": "0xD", "class": "general",
         "purpose": "Read/write of clock data sets."},
    ]
    d["common_header_fields"] = [
        "messageType", "versionPTP", "messageLength", "domainNumber", "flags",
        "correctionField", "sourcePortIdentity", "sequenceId", "controlField",
        "logMessageInterval",
    ]
    d["synchronization_mechanisms"] = {
        "delay_request_response_e2e": {
            "timestamps": list(_TIMESTAMPS),
            "T1": "master transmits Sync",
            "T2": "slave receives Sync",
            "T3": "slave transmits Delay_Req",
            "T4": "master receives Delay_Req (returned in Delay_Resp)",
            "meanPathDelay": "[(T2-T1)+(T4-T3)]/2",
            "offsetFromMaster": "[(T2-T1)-(T4-T3)]/2",
        },
        "peer_delay_p2p": {
            "messages": ["Pdelay_Req", "Pdelay_Resp",
                         "Pdelay_Resp_Follow_Up"],
            "meanLinkDelay": "[(t4-t1)-(t3-t2)]/2",
            "note": "Measures link delay directly; used by the P2P profile "
                    "and IEEE 802.1AS.",
        },
        "one_step_vs_two_step": (
            "One-step: T1 is written into the Sync originTimestamp on the fly. "
            "Two-step: the precise T1 is sent afterwards in a Follow_Up."),
    }
    d["correction_field"] = {
        "width_bits": _CORRECTION_FIELD_BITS,
        "units": "scaled nanoseconds (signed)",
        "purpose": "Transparent Clocks add their residence time so downstream "
                   "clocks can subtract switching delay.",
    }
    d["addressing"] = {
        "domain": "domainNumber selects an independent synchronization "
                  "hierarchy; clocks in different domains do not interact.",
        "sourcePortIdentity": "clockIdentity (EUI-64) + portNumber identifies "
                              "the sending port.",
    }
    d["byte_oriented"] = True
    d["frame_oriented"] = True
    d["packet_based"] = True
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
        "PTP is a protocol standard rather than a fixed memory-mapped register "
        "IC. Its configuration and status are exposed through PTP data sets "
        "(defaultDS, currentDS, parentDS, timePropertiesDS, portDS) reachable "
        "via Management messages, plus the implementation's hardware-"
        "timestamp-unit and servo registers. The groups below are the "
        "canonical PTP configuration/status surfaces.")
    d["register_access"] = {
        "transport": "PTP Management messages (data sets) + implementation "
                     "hardware-timestamp / servo registers",
        "purpose": "Configure the clock type, domain, priorities and profile; "
                   "read clock quality, offset, and port state.",
    }
    d["register_groups"] = [
        {"group": "defaultDS (clock defaults)", "fields": [
            "twoStepFlag (one-step / two-step)",
            "clockIdentity (EUI-64)",
            "numberPorts",
            "clockQuality (clockClass, clockAccuracy, "
            "offsetScaledLogVariance)",
            "priority1", "priority2", "domainNumber",
            "slaveOnly"]},
        {"group": "currentDS (synchronization state)", "fields": [
            "stepsRemoved (hops to the Grandmaster)",
            "offsetFromMaster",
            "meanPathDelay"]},
        {"group": "parentDS (master) / timePropertiesDS", "fields": [
            "parentPortIdentity",
            "grandmasterIdentity",
            "grandmasterClockQuality",
            "grandmasterPriority1 / grandmasterPriority2",
            "currentUtcOffset", "timeTraceable", "frequencyTraceable",
            "timeSource"]},
        {"group": "portDS (per port)", "fields": [
            "portState (INITIALIZING/LISTENING/MASTER/SLAVE/PASSIVE/...)",
            "logSyncInterval", "logAnnounceInterval", "logMinDelayReqInterval",
            "announceReceiptTimeout",
            "delayMechanism (E2E / P2P)",
            "peerMeanPathDelay (P2P)"]},
        {"group": "Hardware timestamp / servo", "fields": [
            "PTP clock counter (seconds + nanoseconds)",
            "TX/RX timestamp capture (T1/T2/T3/T4)",
            "servo / PI controller (frequency + phase adjust)",
            "asymmetry correction"]},
    ]
    d["protocol_fields"] = {
        "correction_field_bits": _CORRECTION_FIELD_BITS,
        "udp_event_port": _UDP_EVENT_PORT,
        "udp_general_port": _UDP_GENERAL_PORT,
        "ethertype": _ETHERTYPE,
        "message_types": list(_ALL_MESSAGES),
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
        "PTP is a packet protocol carried over an underlying Ethernet (Layer "
        "2, EtherType 0x88F7) or UDP/IPv4/IPv6 link; it does not define its "
        "own line signaling. The accuracy-critical analog/timing element is the "
        "hardware-timestamp unit: a free-running PTP clock counter (seconds + "
        "nanoseconds) sampled at the MAC/PHY reference plane on the start of an "
        "event message, and a servo (PI controller) that disciplines the local "
        "oscillator's frequency and phase. A 1PPS / time-of-day output exposes "
        "the disciplined local time.")
    d["modulation"] = ("None of its own — PTP rides on the carrier's signaling "
                       "(Ethernet / UDP).")
    d["clocking"] = (
        "A free-running hardware PTP clock counter (e.g. 48-bit seconds + "
        "32-bit nanoseconds) is disciplined by the servo to track the "
        "Grandmaster. Event messages are timestamped against this counter at "
        "the MAC/PHY plane.")
    d["hardware_timestamping"] = {
        "reference_plane": "MAC/PHY (ideally at the PHY) — excludes variable "
                           "MAC FIFO / queueing / software latency.",
        "captured_events": list(_EVENT_MESSAGES),
        "captured_timestamps": list(_TIMESTAMPS) + ["t1", "t2", "t3", "t4 "
                                                    "(peer-delay)"],
        "counter": "free-running PTP clock counter (seconds + nanoseconds; "
                   "e.g. 48-bit seconds + 32-bit nanoseconds or 80-bit "
                   "timestamp)",
    }
    d["servo"] = {
        "type": "PI controller / clock-disciplining loop",
        "adjusts": ["local oscillator frequency (rate)",
                    "local clock offset (phase)"],
        "objective": "drive offsetFromMaster toward zero",
    }
    d["transport_layers"] = [
        "Ethernet Layer 2 — EtherType 0x88F7 (used by IEEE 802.1AS)",
        "UDP/IPv4 and UDP/IPv6 — event port 319, general port 320",
    ]
    d["encoding_role_in_analog"] = (
        "PTP itself defines no line code; integrity and timing come from "
        "hardware timestamping at the MAC/PHY plane plus the servo. The "
        "carrier (Ethernet / UDP) provides the actual physical signaling.")
    _write(p, d)


# ----------------------------------------------------------------------
# L6 — control logic / state machines.
# ----------------------------------------------------------------------
def _l6(gd: Path) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["fsm_states_port"] = [
        {"name": "INITIALIZING", "description": "Port initializing; data sets "
         "are being set up."},
        {"name": "LISTENING", "description": "Collecting Announce messages for "
         "the BMCA before being assigned MASTER or SLAVE."},
        {"name": "PRE_MASTER", "description": "Transitional state before "
         "becoming MASTER (qualification timeout)."},
        {"name": "MASTER", "description": "The port is the time source for "
         "this communication path (BMCA elected it best)."},
        {"name": "PASSIVE", "description": "Another port is the master on this "
         "path; this port neither masters nor slaves."},
        {"name": "UNCALIBRATED", "description": "A new master was selected; the "
         "port is synchronizing but not yet locked."},
        {"name": "SLAVE", "description": "The port synchronizes its clock to "
         "the selected master."},
        {"name": "FAULTY", "description": "A fault has been detected on the "
         "port."},
        {"name": "DISABLED", "description": "The port is administratively "
         "disabled."},
    ]
    d["fsm_states_bmca"] = [
        {"name": "Announce collection", "description": "Receive Announce "
         "messages; build the foreign-master data set."},
        {"name": "Dataset comparison", "description": "Compare clocks by "
         "priority1, clockClass, clockAccuracy, offsetScaledLogVariance, "
         "priority2, then clockIdentity."},
        {"name": "State decision", "description": "Recommend MASTER / SLAVE / "
         "PASSIVE per port; elect the Grandmaster."},
    ]
    d["fsm_hints"] = {
        "trigger": "Power-up / reset -> INITIALIZING -> LISTENING, where the "
        "BMCA runs on collected Announce messages and assigns MASTER or "
        "SLAVE/UNCALIBRATED.",
        "rule": "A slave synchronizes only after the BMCA selects its master; "
        "event messages (Sync/Delay_Req) drive the T1..T4 capture and the "
        "servo.",
        "timeouts": "announceReceiptTimeout (master lost -> re-run BMCA) and "
        "syncReceiptTimeout (sync lost -> UNCALIBRATED/LISTENING).",
    }
    d["bmca_comparison_order"] = [
        "priority1", "clockClass", "clockAccuracy",
        "offsetScaledLogVariance", "priority2", "clockIdentity",
    ]
    d["anti_deadlock_rule"] = (
        "The BMCA's final tie-break on clockIdentity guarantees a "
        "deterministic, unique Grandmaster so the election always converges; "
        "announceReceiptTimeout prevents a node from waiting forever on a lost "
        "master.")
    d["exit_from_reset_or_poweron"] = (
        "On power-up / reset the port enters INITIALIZING, then LISTENING; it "
        "collects Announce messages and runs the BMCA before being assigned "
        "the MASTER or SLAVE state.")
    d["default_ready_state_recommendation"] = {
        "listening": "Collect Announce messages and run the BMCA before "
                     "mastering or slaving.",
        "synchronizing": "A slave enters UNCALIBRATED then SLAVE once it is "
                         "locked to its master.",
    }
    d["configurations"] = [
        {"name": "Ordinary Clock", "description": "Single PTP port; "
         "Grandmaster or slave-only end node."},
        {"name": "Boundary Clock", "description": "Multiple ports; one SLAVE "
         "upstream, others MASTER downstream."},
        {"name": "Transparent Clock (E2E)", "description": "Corrects residence "
         "time; forwards delay-request-response transparently."},
        {"name": "Transparent Clock (P2P)", "description": "Corrects residence "
         "time and measures link delay via the peer delay mechanism."},
    ]
    d["timing_dependency_rule"] = (
        "A slave can compute offsetFromMaster only after it has both a Sync "
        "(T1, T2) and a Delay_Req/Delay_Resp (T3, T4) — or the peer-delay "
        "measurement — and after the BMCA has selected its master. Transparent "
        "Clocks must accumulate residence time into the correctionField before "
        "forwarding event messages.")
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
        {"name": "currentDS (offsetFromMaster / meanPathDelay)",
         "purpose": "Read the live synchronization error and path delay."},
        {"name": "portDS (portState)",
         "purpose": "Observe each port's BMCA state (MASTER/SLAVE/PASSIVE/...)."},
        {"name": "parentDS (grandmasterIdentity / stepsRemoved)",
         "purpose": "Identify the elected Grandmaster and the hop count."},
        {"name": "Management messages",
         "purpose": "Read/write clock data sets for monitoring and "
                    "configuration."},
        {"name": "Timestamp capture (T1/T2/T3/T4)",
         "purpose": "Inspect the raw event-message timestamps and the "
                    "correctionField."},
        {"name": "1PPS / ToD output",
         "purpose": "Externally measure the disciplined local time against a "
                    "reference."},
    ]
    d["error_detection_mechanisms"] = [
        "announceReceiptTimeout detects loss of the master (re-run BMCA).",
        "syncReceiptTimeout detects loss of synchronization.",
        "sequenceId gaps detect lost messages.",
        "Excessive offsetFromMaster indicates servo divergence / asymmetry.",
        "Domain mismatch (foreign domainNumber) is ignored.",
        "checksum/FCS of the carrier (Ethernet FCS / UDP checksum) detects "
        "corruption.",
    ]
    d["test_modes"] = [
        {"name": "1PPS comparison", "purpose": "Measure the disciplined "
         "1-pulse-per-second against a reference to quantify sync error."},
        {"name": "Master / slave emulation", "purpose": "Drive the node with a "
         "PTP master or slave emulator to exercise the message exchange."},
        {"name": "Asymmetry / delay injection", "purpose": "Inject link "
         "asymmetry to verify the correction and the servo response."},
        {"name": "BMCA scenario test", "purpose": "Present competing Announce "
         "messages to verify Grandmaster election."},
    ]
    d["interrupt_or_event_sources"] = [
        {"event": "Sync received", "trigger": "A Sync (and T2 capture) "
         "arrives."},
        {"event": "Delay_Resp received", "trigger": "T4 returned from the "
         "master."},
        {"event": "Announce received", "trigger": "BMCA input updated."},
        {"event": "Timestamp captured", "trigger": "An event message is "
         "hardware-timestamped."},
        {"event": "Timeout", "trigger": "announceReceiptTimeout / "
         "syncReceiptTimeout."},
        {"event": "State change", "trigger": "A port transitions MASTER / "
         "SLAVE / PASSIVE."},
    ]
    d["notes"] = (
        "PTP's protocol-level test/debug surface is the data sets (currentDS / "
        "portDS / parentDS) read via Management messages, the raw T1..T4 "
        "timestamps and correctionField, and the 1PPS/ToD output for external "
        "measurement. Chip-level JTAG/scan/BIST remain SoC concerns.")
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
        "PTP_STANDARD": "IEEE 1588-2008 / 1588-2019 (PTPv2); IEEE 802.1AS",
        "PROTOCOL_CLASS": "clock synchronization (packet-based)",
        "EVENT_MESSAGE_COUNT": len(_EVENT_MESSAGES),
        "GENERAL_MESSAGE_COUNT": len(_GENERAL_MESSAGES),
        "MESSAGE_TYPE_COUNT": len(_ALL_MESSAGES),
        "CLOCK_TYPE_COUNT": len(_CLOCK_TYPES),
        "TIMESTAMP_COUNT": len(_TIMESTAMPS),
        "CORRECTION_FIELD_BITS": _CORRECTION_FIELD_BITS,
        "ETHERTYPE": _ETHERTYPE,
        "UDP_EVENT_PORT": _UDP_EVENT_PORT,
        "UDP_GENERAL_PORT": _UDP_GENERAL_PORT,
        "MASTER_SLAVE": True,
        "BMCA": True,
        "GRANDMASTER": True,
        "HARDWARE_TIMESTAMPING": True,
        "EMBEDDED_CLOCK": False,
        "FORWARDED_CLOCK": False,
    })
    d["message_format_constants"] = {
        "event_messages": list(_EVENT_MESSAGES),
        "general_messages": list(_GENERAL_MESSAGES),
        "common_header_fields": [
            "messageType", "versionPTP", "messageLength", "domainNumber",
            "flags", "correctionField", "sourcePortIdentity", "sequenceId",
            "controlField", "logMessageInterval",
        ],
        "correction_field_bits": _CORRECTION_FIELD_BITS,
    }
    d["timestamp_constants"] = {
        "timestamps": list(_TIMESTAMPS),
        "meanPathDelay": "[(T2-T1)+(T4-T3)]/2",
        "offsetFromMaster": "[(T2-T1)-(T4-T3)]/2",
        "meanLinkDelay_p2p": "[(t4-t1)-(t3-t2)]/2",
    }
    kc = _ensure_dict(d, "key_constants_for_RTL_authoring")
    kc.update({
        "is_serial": False,
        "is_packet_based": True,
        "is_clock_sync": True,
        "master_slave": True,
        "bmca": True,
        "grandmaster": True,
        "hardware_timestamping": True,
        "embedded_clock": False,
        "forwarded_clock": False,
        "event_messages": list(_EVENT_MESSAGES),
        "general_messages": list(_GENERAL_MESSAGES),
        "clock_types": list(_CLOCK_TYPES),
        "timestamps": list(_TIMESTAMPS),
        "correction_field_bits": _CORRECTION_FIELD_BITS,
        "ethertype": _ETHERTYPE,
        "udp_event_port": _UDP_EVENT_PORT,
        "udp_general_port": _UDP_GENERAL_PORT,
        "delay_mechanisms": ["delay-request-response (E2E)",
                             "peer-delay (P2P)"],
        "one_step_two_step": True,
        "servo": "PI controller",
    })
    d["default_signal_values_when_idle"] = {
        "no_master": "Before the BMCA selects a master the port is LISTENING; "
                     "the servo holds the free-running local clock.",
        "between_sync": "The disciplined PTP clock counter free-runs between "
                        "Sync messages.",
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
    d["message_waveform"] = {
        "transport": "PTP messages over Ethernet (0x88F7) or UDP (319/320); "
                     "no PTP-specific line code.",
        "event_messages": list(_EVENT_MESSAGES),
        "general_messages": list(_GENERAL_MESSAGES),
        "timestamp_point": "Event messages are hardware-timestamped at the "
                           "MAC/PHY reference plane on message start.",
    }
    d["sync_exchange_waveform"] = {
        "two_step": "Sync (carries estimate) -> Follow_Up (precise T1).",
        "one_step": "Sync carries T1 in originTimestamp on the fly.",
        "delay_request": "Delay_Req (T3) -> Delay_Resp (T4).",
        "timestamps": {"T1": "master TX Sync", "T2": "slave RX Sync",
                       "T3": "slave TX Delay_Req",
                       "T4": "master RX Delay_Req"},
    }
    d["peer_delay_waveform"] = {
        "sequence": "Pdelay_Req (t1) -> Pdelay_Resp (t2/t3) -> "
                    "Pdelay_Resp_Follow_Up; requestor captures t4.",
        "meanLinkDelay": "[(t4-t1)-(t3-t2)]/2",
    }
    d["computation_waveform"] = {
        "meanPathDelay": "[(T2-T1)+(T4-T3)]/2",
        "offsetFromMaster": "[(T2-T1)-(T4-T3)]/2",
        "correction": "subtract the accumulated correctionField (Transparent "
                      "Clock residence time).",
    }
    d["general_timing_rule"] = (
        "Sync is sent at logSyncInterval; Announce at logAnnounceInterval; "
        "Delay_Req at logMinDelayReqInterval. A slave needs one Sync (T1/T2) "
        "and one Delay_Req/Resp (T3/T4) — or one peer-delay round — to compute "
        "offsetFromMaster, then the servo continuously corrects it.")
    d["interval_waveform"] = {
        "logSyncInterval": "rate of Sync (master -> slave)",
        "logAnnounceInterval": "rate of Announce (BMCA)",
        "logMinDelayReqInterval": "minimum Delay_Req spacing (slave)",
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
        "Clock-synchronization engine: an IEEE 1588 PTP node implementing the "
        "PTP message exchange (Sync/Follow_Up, Delay_Req/Delay_Resp, the peer "
        "delay mechanism), hardware timestamping at the MAC/PHY plane, the "
        "offsetFromMaster / meanPathDelay computation, the servo that "
        "disciplines the local clock, the BMCA that elects the Grandmaster, "
        "and the Ordinary / Boundary / Transparent clock behaviors — "
        "synchronizing the node's local time to the Grandmaster over an "
        "Ethernet or UDP network.")
    d["topology_description"] = (
        "Grandmaster -> Transparent / Boundary Clocks -> Ordinary Clock "
        "slaves. The BMCA elects the Grandmaster; Boundary Clocks terminate "
        "and regenerate PTP at boundaries; Transparent Clocks correct "
        "residence time in transit. The hierarchy spans a PTP domain.")
    io = _ensure_dict(d, "integration_overview")
    io.update({
        "ptp_standard": "IEEE 1588-2008 / 1588-2019 (PTPv2); IEEE 802.1AS",
        "event_messages": list(_EVENT_MESSAGES),
        "general_messages": list(_GENERAL_MESSAGES),
        "clock_types": list(_CLOCK_TYPES),
        "timestamps": list(_TIMESTAMPS),
        "correction_field_bits": _CORRECTION_FIELD_BITS,
        "transport": "Ethernet (0x88F7) or UDP/IPv4/IPv6 (319/320)",
        "hardware_timestamping": True,
        "bmca": True,
        "grandmaster": True,
        "servo": "PI controller (frequency + phase)",
        "interfaces": {"network": "MAC/PHY (Ethernet / UDP)",
                       "timestamp": "hardware-timestamp capture at MAC/PHY",
                       "clock_out": "1PPS + time-of-day"},
    })
    d["interface_categories"] = [
        "Network interface — PTP messages over Ethernet (0x88F7) or "
        "UDP/IPv4/IPv6 (ports 319/320).",
        "Timestamp interface — hardware-timestamp capture of event messages at "
        "the MAC/PHY plane.",
        "Clock interface — the disciplined PTP clock counter and 1PPS / ToD "
        "output.",
        "Management interface — PTP data sets (defaultDS / currentDS / "
        "portDS / parentDS) via Management messages.",
    ]
    d["interconnect_topologies_supported"] = [
        "Master-slave hierarchy rooted at the Grandmaster (BMCA-elected).",
        "Ordinary Clock end node (single port).",
        "Boundary Clock (multi-port; terminates and regenerates PTP).",
        "End-to-end Transparent Clock (residence-time correction).",
        "Peer-to-peer Transparent Clock (residence + link delay).",
        "IEEE 802.1AS time-aware bridged network (gPTP).",
    ]
    d["default_signal_values_when_omitted"] = (
        "Before the BMCA elects a master the port is LISTENING and the local "
        "clock free-runs; an unsynchronized slave is UNCALIBRATED until it "
        "locks.")
    d["soc_dependent_items"] = [
        "Number of PTP ports (Ordinary vs Boundary vs Transparent Clock).",
        "Clock identity (EUI-64) and priority1 / priority2.",
        "Transport selection (Ethernet 0x88F7 and/or UDP 319/320).",
        "Profile (default E2E / P2P, IEEE 802.1AS, power, telecom).",
        "Hardware-timestamp resolution and the local oscillator.",
        "Servo / PI controller tuning.",
    ]
    d["device_classes_examples"] = [
        "PTP Grandmaster clock (GPS-disciplined time source)",
        "PTP Ordinary Clock slave (end device)",
        "PTP Boundary Clock (switch/router)",
        "PTP Transparent Clock switch (E2E / P2P)",
        "IEEE 802.1AS time-aware bridge / endpoint (TSN)",
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
        "Sync / Follow_Up exchange (one-step and two-step); T1 / T2 capture.",
        "Delay_Req / Delay_Resp exchange; T3 / T4 capture.",
        "Peer delay mechanism: Pdelay_Req / Pdelay_Resp / "
        "Pdelay_Resp_Follow_Up; link-delay measurement.",
        "offsetFromMaster and meanPathDelay computation; correctionField "
        "subtraction.",
        "BMCA Grandmaster election (priority1 / clockClass / clockAccuracy / "
        "offsetScaledLogVariance / priority2 / clockIdentity).",
        "Port state machine: INITIALIZING / LISTENING / MASTER / SLAVE / "
        "PASSIVE / UNCALIBRATED transitions.",
        "Ordinary / Boundary / Transparent Clock behaviors; residence-time "
        "correction.",
        "Hardware timestamping accuracy at the MAC/PHY plane.",
        "Servo lock and holdover; asymmetry correction.",
        "Transport: Ethernet (0x88F7) and UDP (319/320); domain isolation.",
        "Timeouts: announceReceiptTimeout and syncReceiptTimeout.",
        "Sub-microsecond accuracy budget under the default / 802.1AS profile.",
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
        {"field": "clockIdentity (EUI-64)",
         "location": "device configuration / NVRAM",
         "note": "The unique 64-bit clock identity (often derived from a MAC "
                 "EUI); typically factory-assigned, not a protocol-fixed OTP "
                 "concept."},
        {"field": "priority1 / priority2",
         "location": "clock configuration",
         "note": "User/operator-configurable BMCA preference values."},
        {"field": "Default clockQuality",
         "location": "clock configuration",
         "note": "clockClass / clockAccuracy / offsetScaledLogVariance "
                 "defaults for the time source."},
        {"field": "Profile / domainNumber",
         "location": "clock configuration",
         "note": "Selected profile (default / 802.1AS / power / telecom) and "
                 "PTP domain; programmed, not OTP-fixed."},
    ]
    d["notes"] = (
        "PTP does not define OTP/fuse content as a protocol concept. The "
        "clockIdentity, priorities, default clock quality, profile, and domain "
        "are clock configuration (often in NVRAM and reachable via Management "
        "messages); an implementation may back some defaults with non-volatile "
        "storage, but the standard only requires they be configurable.")
    _write(p, d)


# ----------------------------------------------------------------------
# L12 — behavioral sequences.
# ----------------------------------------------------------------------
def _l12(gd: Path) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["bmca_election_sequence"] = [
        "1. Power-up / reset -> INITIALIZING -> LISTENING.",
        "2. Collect Announce messages from candidate masters.",
        "3. Run the dataset comparison (priority1, clockClass, clockAccuracy, "
        "offsetScaledLogVariance, priority2, clockIdentity).",
        "4. Elect the Grandmaster; assign each port MASTER / SLAVE / PASSIVE.",
    ]
    d["sync_exchange_sequence"] = [
        "1. The master sends a Sync message and captures the egress timestamp "
        "T1 (one-step embeds T1; two-step sends T1 in a Follow_Up).",
        "2. The slave timestamps Sync arrival as T2.",
        "3. (Two-step) the slave reads the precise T1 from the Follow_Up.",
    ]
    d["delay_request_sequence"] = [
        "1. The slave sends a Delay_Req and captures the egress timestamp T3.",
        "2. The master timestamps Delay_Req arrival as T4.",
        "3. The master returns T4 to the slave in a Delay_Resp.",
        "4. The slave computes meanPathDelay = [(T2-T1)+(T4-T3)]/2 and "
        "offsetFromMaster = [(T2-T1)-(T4-T3)]/2.",
    ]
    d["peer_delay_sequence"] = [
        "1. A port sends Pdelay_Req and captures t1.",
        "2. The peer captures t2, sends Pdelay_Resp capturing t3, and reports "
        "t2/t3 (Pdelay_Resp + Pdelay_Resp_Follow_Up).",
        "3. The requestor captures t4 and computes the link delay = "
        "[(t4-t1)-(t3-t2)]/2.",
    ]
    d["servo_sequence"] = [
        "1. From offsetFromMaster the servo (PI controller) adjusts the local "
        "clock phase.",
        "2. From the rate of change it adjusts the local oscillator frequency.",
        "3. The loop drives offsetFromMaster toward zero and tracks the "
        "master.",
    ]
    d["transparent_clock_sequence"] = [
        "1. An event message enters the Transparent Clock; the ingress time is "
        "captured.",
        "2. The egress time is captured when the message leaves.",
        "3. The residence time (egress - ingress) is added to the message "
        "correctionField.",
    ]
    d["reset_sequence"] = [
        "1. On power-up / reset the port enters INITIALIZING.",
        "2. It moves to LISTENING and runs the BMCA before mastering or "
        "slaving.",
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
        {"name": "1PPS sync error", "purpose": "Measure the disciplined "
         "1-pulse-per-second against a reference (target sub-microsecond, "
         "typically tens of ns)."},
        {"name": "offsetFromMaster convergence", "purpose": "Verify the servo "
         "drives offsetFromMaster to zero and holds lock."},
        {"name": "meanPathDelay accuracy", "purpose": "Validate path-delay "
         "measurement under symmetric and asymmetric links."},
        {"name": "Hardware-timestamp resolution", "purpose": "Confirm the "
         "MAC/PHY timestamp granularity and stability."},
        {"name": "Transparent-clock residence time", "purpose": "Verify "
         "residence-time correction into the correctionField."},
        {"name": "BMCA convergence", "purpose": "Confirm deterministic "
         "Grandmaster election and re-election on master loss."},
        {"name": "Holdover stability", "purpose": "Measure local-oscillator "
         "holdover after the master is removed."},
    ]
    d["notes"] = (
        "PTP characterization centers on the sync error (1PPS vs reference), "
        "offsetFromMaster convergence and servo lock, path-delay accuracy "
        "(including asymmetry), the hardware-timestamp resolution at the "
        "MAC/PHY plane, Transparent-Clock residence-time correction, BMCA "
        "convergence, and holdover. Conformance is established by IEEE 1588 / "
        "IEEE 802.1AS test suites.")
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
    f["spec_version"] = ("IEEE Std 1588-2008 / IEEE Std 1588-2019 (PTPv2); "
                         "IEEE 802.1AS (gPTP)")
    f["previous_versions"] = [
        "IEEE 1588-2002 (PTPv1) — original Precision Time Protocol.",
        "IEEE 1588-2008 (PTPv2) — redesigned message set, Transparent Clocks, "
        "peer delay, correctionField, profiles.",
        "IEEE 802.1AS-2011 (gPTP) — first TSN/AVB profile of PTP.",
    ]
    f["key_changes"] = [
        {"version": "IEEE 1588-2008 (PTPv2)", "summary": "Replaced PTPv1's "
         "message set; added Transparent Clocks and the correctionField, the "
         "peer delay mechanism, one-step/two-step Sync, profiles, and "
         "Ethernet (0x88F7) transport. NOT wire-compatible with PTPv1."},
        {"version": "IEEE 802.1AS (gPTP)", "summary": "A constrained PTP "
         "profile for TSN/AVB: peer delay on every link, two-step "
         "Sync+Follow_Up, an alternate BMCA, and Layer-2 0x88F7 only; every "
         "bridge is a time-aware system."},
        {"version": "IEEE 1588-2019", "summary": "High-accuracy enhancements, "
         "modular optional features, and security TLVs; backward compatible "
         "framework with PTPv2."},
    ]
    f["future_versions_industry_outline"] = [
        {"version": "IEEE 802.1AS-2020 / TSN", "summary": "Continued "
         "refinement of gPTP for time-aware networks; multiple time domains "
         "and improved fault tolerance."},
    ]
    f["backward_compat_traps"] = [
        {"trap_name": "v1_v2_not_interoperable",
         "rule": "PTPv2 (1588-2008) is not wire-compatible with PTPv1 "
                 "(1588-2002).",
         "trap": "Assuming a v1 node can sync to a v2 node is wrong; versionPTP "
                 "differs."},
        {"trap_name": "one_step_vs_two_step",
         "rule": "Two-step clocks send T1 in a Follow_Up; one-step embed it in "
                 "Sync.",
         "trap": "Ignoring the Follow_Up on a two-step master loses the "
                 "precise T1."},
        {"trap_name": "e2e_vs_p2p_delay",
         "rule": "The end-to-end (Delay_Req/Resp) and peer-to-peer (Pdelay) "
                 "delay mechanisms are mutually exclusive on a path.",
         "trap": "Mixing E2E and P2P on the same link is invalid; 802.1AS uses "
                 "P2P only."},
        {"trap_name": "not_plain_ethernet",
         "rule": "PTP rides over Ethernet/UDP but is a clock-sync protocol "
                 "(Sync/Delay/BMCA/Grandmaster), not an Ethernet MAC/PHY.",
         "trap": "Treating PTP as just an Ethernet frame ignores the timing "
                 "structure (T1..T4, offset, correctionField)."},
    ]
    f["version_naming_history_note"] = (
        "The Precision Time Protocol is standardized by the IEEE 1588 Working "
        "Group. PTPv1 (IEEE 1588-2002) was superseded by PTPv2 (IEEE "
        "1588-2008), which redesigned the message set and added Transparent "
        "Clocks, the correctionField, the peer delay mechanism, and profiles. "
        "IEEE 802.1AS (gPTP) is a constrained PTP profile for TSN/AVB, and "
        "IEEE 1588-2019 added high-accuracy and security enhancements while "
        "preserving the PTPv2 framework.")
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
    f["message_type_table"] = {
        "header_columns": ["Message", "messageType", "Class", "Purpose"],
        "rows": [
            ["Sync", "0x0", "event", "synchronization message (T1)"],
            ["Delay_Req", "0x1", "event", "delay request (T3)"],
            ["Pdelay_Req", "0x2", "event", "peer delay request"],
            ["Pdelay_Resp", "0x3", "event", "peer delay response"],
            ["Follow_Up", "0x8", "general", "precise T1 (two-step)"],
            ["Delay_Resp", "0x9", "general", "returns T4"],
            ["Pdelay_Resp_Follow_Up", "0xA", "general",
             "peer-delay turnaround timestamps"],
            ["Announce", "0xB", "general", "BMCA clock-quality attributes"],
            ["Signaling", "0xC", "general", "unicast / option negotiation"],
            ["Management", "0xD", "general", "read/write data sets"],
        ],
    }
    f["clock_type_table"] = {
        "header_columns": ["Clock type", "Ports", "Role"],
        "rows": [
            ["Ordinary Clock (OC)", "1", "Grandmaster or slave-only end node"],
            ["Boundary Clock (BC)", "many",
             "SLAVE upstream, MASTER downstream"],
            ["Transparent Clock E2E", "many",
             "residence-time correction (end-to-end)"],
            ["Transparent Clock P2P", "many",
             "residence + link delay (peer-to-peer)"],
        ],
    }
    f["timestamp_table"] = {
        "header_columns": ["Timestamp", "Captured at"],
        "rows": [
            ["T1", "master transmits Sync"],
            ["T2", "slave receives Sync"],
            ["T3", "slave transmits Delay_Req"],
            ["T4", "master receives Delay_Req (returned in Delay_Resp)"],
        ],
    }
    f["bmca_attribute_table"] = {
        "header_columns": ["Order", "Attribute"],
        "rows": [
            ["1", "priority1"],
            ["2", "clockClass"],
            ["3", "clockAccuracy"],
            ["4", "offsetScaledLogVariance"],
            ["5", "priority2"],
            ["6", "clockIdentity (tie-break)"],
        ],
    }
    f["transport_table"] = {
        "header_columns": ["Transport", "Identifier", "Event / General"],
        "rows": [
            ["Ethernet L2", "EtherType 0x88F7", "both (multicast MAC)"],
            ["UDP/IPv4/IPv6 (event)", "port 319", "event messages"],
            ["UDP/IPv4/IPv6 (general)", "port 320", "general messages"],
        ],
    }
    f["computation_table"] = {
        "header_columns": ["Quantity", "Formula"],
        "rows": [
            ["meanPathDelay (E2E)", "[(T2-T1)+(T4-T3)]/2"],
            ["offsetFromMaster", "[(T2-T1)-(T4-T3)]/2"],
            ["meanLinkDelay (P2P)", "[(t4-t1)-(t3-t2)]/2"],
        ],
    }
    f["encoding_note"] = (
        "PTP messages share a common header (messageType, versionPTP, "
        "domainNumber, flags, correctionField, sourcePortIdentity, "
        "sequenceId, ...). Event messages (Sync/Delay_Req/Pdelay_Req/"
        "Pdelay_Resp) are timestamped; general messages carry data. The "
        "correctionField (64-bit signed scaled-ns) accumulates Transparent-"
        "Clock residence time. Transport is Ethernet 0x88F7 or UDP 319/320.")
    f["tables"] = [
        "Message-type table (Sync/Delay_Req/.../Management; messageType hex)",
        "Clock-type table (OC / BC / TC E2E / TC P2P)",
        "Timestamp table (T1/T2/T3/T4)",
        "BMCA attribute table (priority1/clockClass/.../clockIdentity)",
        "Transport table (Ethernet 0x88F7 / UDP 319 / UDP 320)",
        "Computation table (meanPathDelay / offsetFromMaster / meanLinkDelay)",
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
        "Sync / Follow_Up exchange and Delay_Req / Delay_Resp exchange (the "
        "delay-request-response mechanism) capturing T1/T2/T3/T4.",
        "Peer delay mechanism (Pdelay_Req / Pdelay_Resp / "
        "Pdelay_Resp_Follow_Up) for the P2P profile and IEEE 802.1AS.",
        "offsetFromMaster and meanPathDelay computation with correctionField "
        "subtraction.",
        "Best Master Clock Algorithm electing a deterministic Grandmaster and "
        "assigning MASTER / SLAVE / PASSIVE per port.",
        "Configurable Ordinary / Boundary / Transparent (E2E / P2P) clock "
        "types; Transparent Clocks correct residence time.",
        "Hardware timestamping of event messages at the MAC/PHY reference "
        "plane.",
        "A servo / PI controller disciplining local clock frequency and "
        "phase.",
        "Transport over Ethernet (0x88F7) and/or UDP/IPv4/IPv6 (319/320); PTP "
        "domains.",
    ]
    f["must_not_have_properties"] = [
        "A plain Ethernet MAC/PHY with no PTP message set, BMCA, Grandmaster, "
        "or PTP clock types (that is Ethernet, not PTP).",
        "Virtual Links / Bandwidth Allocation Gap / ARINC 664 framing (that is "
        "AFDX, not PTP).",
        "Wire-compatibility with PTPv1 (IEEE 1588-2002) — PTPv2 is a different "
        "message set.",
        "Mixing the end-to-end and peer-to-peer delay mechanisms on the same "
        "path.",
    ]
    f["compliance_failure_modes"] = [
        {"mode": "announceReceiptTimeout", "trigger": "Master lost; the BMCA "
         "re-runs and may re-elect a Grandmaster."},
        {"mode": "syncReceiptTimeout", "trigger": "Synchronization lost; the "
         "port enters UNCALIBRATED / LISTENING."},
        {"mode": "Asymmetry bias", "trigger": "An asymmetric link delay biases "
         "offsetFromMaster; corrected by asymmetry value or P2P."},
        {"mode": "Servo divergence", "trigger": "Excessive offsetFromMaster; "
         "the loop fails to lock."},
        {"mode": "Domain mismatch", "trigger": "A foreign domainNumber message "
         "is ignored."},
    ]
    f["min_link_constraint"] = (
        "A PTP slave requires a Sync (T1, T2) and either a Delay_Req/Delay_Resp "
        "(T3, T4) or a peer-delay round, plus a BMCA-selected master, before it "
        "can compute offsetFromMaster and discipline its clock.")
    f["reset_behavior_compliance"] = (
        "On power-up / reset the port enters INITIALIZING -> LISTENING and runs "
        "the BMCA before being assigned MASTER or SLAVE.")
    f["ptp_distinguishers"] = (
        "PTP (IEEE 1588) is identified by ALL of: a master-slave clock "
        "hierarchy elected by the Best Master Clock Algorithm with a "
        "Grandmaster root; the Sync / Follow_Up + Delay_Req / Delay_Resp (or "
        "the Pdelay) message exchange; the T1/T2/T3/T4 timestamps with "
        "offsetFromMaster and meanPathDelay computation; the Ordinary / "
        "Boundary / Transparent clock types with residence-time correction via "
        "the correctionField; hardware timestamping at the MAC/PHY plane; and "
        "transport over Ethernet (EtherType 0x88F7) or UDP/IPv4/IPv6 (event "
        "port 319, general port 320). It rides over Ethernet but is a clock-"
        "synchronization protocol, NOT a plain Ethernet MAC/PHY (no PTP "
        "messages, BMCA, Grandmaster, or clock types) and NOT AFDX (no Virtual "
        "Links / BAG / ARINC 664).")
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
        {"name": "Network port (Ethernet / UDP)",
         "direction": "bidirectional",
         "purpose": "Carries PTP event and general messages (Ethernet 0x88F7 "
                    "or UDP 319/320).",
         "active_levels": "carrier-defined", "idle_level": "carrier idle"},
        {"name": "Hardware-timestamp capture",
         "direction": "input (to the timestamp unit)",
         "purpose": "Samples the PTP clock counter on event-message start at "
                    "the MAC/PHY plane (T1/T2/T3/T4).",
         "active_levels": "strobe", "idle_level": "no capture"},
        {"name": "1PPS / time-of-day output",
         "direction": "output",
         "purpose": "Exposes the disciplined local time.",
         "active_levels": "pulse + ToD", "idle_level": "between pulses"},
    ]
    f["logical_signaling_levels"] = [
        {"name": "Event message", "meaning": "Timestamped on TX/RX "
         "(Sync/Delay_Req/Pdelay_Req/Pdelay_Resp)."},
        {"name": "General message", "meaning": "Carries data, not timestamped "
         "(Follow_Up/Delay_Resp/Announce/...)."},
    ]
    f["packet_types_summary"] = [
        {"class": "Event message", "members": list(_EVENT_MESSAGES),
         "count": len(_EVENT_MESSAGES)},
        {"class": "General message", "members": list(_GENERAL_MESSAGES),
         "count": len(_GENERAL_MESSAGES)},
        {"class": "Clock type", "members": list(_CLOCK_TYPES),
         "count": len(_CLOCK_TYPES)},
    ]
    cc = _ensure_dict(f, "channel_counts")
    cc.update({
        "event_message_count": len(_EVENT_MESSAGES),
        "general_message_count": len(_GENERAL_MESSAGES),
        "message_type_count": len(_ALL_MESSAGES),
        "clock_type_count": len(_CLOCK_TYPES),
        "timestamp_count": len(_TIMESTAMPS),
        "correction_field_bits": _CORRECTION_FIELD_BITS,
        "udp_event_port": _UDP_EVENT_PORT,
        "udp_general_port": _UDP_GENERAL_PORT,
        "port_state_count": len(_PORT_STATES),
    })
    f["global_signals"] = [
        {"name": "Grandmaster", "purpose": "The BMCA-elected root of the "
         "master-slave hierarchy; the time reference for the domain."},
        {"name": "PTP domain (domainNumber)", "purpose": "Selects an "
         "independent synchronization hierarchy."},
        {"name": "correctionField (64-bit)", "purpose": "Accumulates "
         "Transparent-Clock residence time."},
    ]
    f["dependency_graph"] = {
        "common_rule": "The BMCA must elect a master (from Announce messages) "
        "before a port slaves. A slave needs both a Sync (T1/T2) and a "
        "Delay_Req/Delay_Resp (T3/T4) — or a peer-delay round — to compute "
        "offsetFromMaster and meanPathDelay.",
        "data_dependency": "offsetFromMaster depends on T1, T2, T3, T4 and the "
        "accumulated correctionField; the servo depends on offsetFromMaster; "
        "Transparent-Clock correction depends on the measured residence "
        "time.",
    }
    f["handshake_pairs"] = [
        {"name": "Sync / Follow_Up", "from": "master", "to": "slave",
         "rule": "Sync carries/references T1; two-step Follow_Up carries the "
                 "precise T1."},
        {"name": "Delay_Req / Delay_Resp", "from": "slave", "to": "master",
         "rule": "Delay_Req (T3) -> Delay_Resp (T4) measures the reverse "
                 "path."},
        {"name": "Pdelay_Req / Pdelay_Resp", "from": "port", "to": "peer",
         "rule": "Peer delay round measures link delay (t1..t4)."},
        {"name": "Announce / BMCA", "from": "candidate master",
         "to": "all clocks", "rule": "Announce carries clock quality; the BMCA "
                 "elects the Grandmaster."},
    ]
    f["ordering_rules"] = {
        "message_order": "Sync precedes its Follow_Up (two-step); Delay_Req "
        "precedes Delay_Resp; sequenceId orders messages.",
        "election_order": "Announce collection precedes the BMCA decision "
        "precedes port-state assignment.",
        "domain": "Messages are processed only within the matching "
        "domainNumber.",
        "transport": "Event messages use UDP 319 / Ethernet 0x88F7; general "
        "messages use UDP 320 / Ethernet 0x88F7.",
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
        "Master-slave clock hierarchy over a packet network, rooted at the "
        "BMCA-elected Grandmaster. Ordinary Clocks are leaf/source nodes; "
        "Boundary Clocks terminate and regenerate PTP at boundaries; "
        "Transparent Clocks correct residence time in transit. The hierarchy "
        "spans a PTP domain over Ethernet or UDP.")
    f["supported_topologies"] = [
        {"name": "Grandmaster-rooted hierarchy", "description": "The BMCA "
         "elects the Grandmaster; slaves discipline to it through a tree of "
         "Boundary / Transparent Clocks."},
        {"name": "Ordinary Clock", "description": "Single-port end node "
         "(Grandmaster or slave)."},
        {"name": "Boundary Clock", "description": "Multi-port; one SLAVE "
         "upstream, others MASTER downstream."},
        {"name": "Transparent Clock (E2E)", "description": "Switch correcting "
         "residence time end-to-end."},
        {"name": "Transparent Clock (P2P)", "description": "Switch correcting "
         "residence time and measuring link delay (802.1AS)."},
    ]
    f["master_slave_role_summary"] = [
        {"role": "Grandmaster", "description": "BMCA-elected root and time "
         "reference for the domain."},
        {"role": "Master port", "description": "Time source on a "
         "communication path; sends Sync / Announce."},
        {"role": "Slave port", "description": "Time receiver; sends Delay_Req "
         "and disciplines its clock."},
        {"role": "Passive port", "description": "Neither master nor slave on a "
         "path where another port is master."},
        {"role": "Transparent Clock", "description": "Corrects residence time "
         "via the correctionField in transit."},
    ]
    f["interconnect_role"] = (
        "PTP overlays a timing hierarchy on a packet network. The Grandmaster "
        "is the reference; Boundary Clocks segment the network and regenerate "
        "PTP; Transparent Clocks correct switching delay so accuracy is "
        "preserved across hops. Slaves compute offsetFromMaster and discipline "
        "their clocks.")
    f["routing_methods"] = ["BMCA-elected master-slave hierarchy",
                            "Boundary Clock regeneration",
                            "Transparent Clock residence-time correction"]
    f["ordering_guarantees"] = {
        "sync": "A Sync (and its Follow_Up) precedes the corresponding "
        "Delay_Resp use; sequenceId orders messages.",
        "election": "Announce collection -> BMCA decision -> port-state "
        "assignment.",
        "domain": "Clocks in different domains do not interact.",
    }
    f["memory_vs_peripheral_regions"] = (
        "PTP is not memory-mapped; nodes are identified by clockIdentity "
        "(EUI-64) + portNumber and grouped by domainNumber. Configuration and "
        "status use PTP data sets via Management messages, not a memory or "
        "peripheral address.")
    dc = _ensure_dict(f, "device_classification")
    dc["grandmaster"] = "BMCA-elected root / time reference for the domain."
    dc["ordinary_clock"] = "Single-port end node (Grandmaster or slave)."
    dc["boundary_clock"] = "Multi-port; SLAVE upstream, MASTER downstream."
    dc["transparent_clock_e2e"] = "Residence-time correction (end-to-end)."
    dc["transparent_clock_p2p"] = "Residence + link-delay (peer-to-peer)."
    f["default_signal_values_evidence_tables"] = [
        "PTP master-slave hierarchy figure (Grandmaster -> BC/TC -> OC "
        "slaves)",
        "Delay-request-response timing diagram (T1/T2/T3/T4)",
        "Peer-delay timing diagram (t1..t4)",
        "BMCA dataset-comparison figure (priority1/clockClass/...)",
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
        "transport": "Ethernet Layer 2 (EtherType 0x88F7) or UDP/IPv4/IPv6 "
                     "(event port 319, general port 320)",
        "no_ptp_specific_line_code": True,
        "hardware_timestamp_plane": "MAC/PHY reference plane",
        "clock_counter": "free-running PTP clock counter (seconds + "
                         "nanoseconds)",
        "servo": "PI controller (frequency + phase)",
        "correction_field_bits": _CORRECTION_FIELD_BITS,
        "accuracy_target": "sub-microsecond (default / 802.1AS)",
    }
    f["notes"] = (
        "PTP is a protocol standard (IEEE 1588): it fixes the message set, the "
        "BMCA, the clock types, the timestamp/offset/delay computation, the "
        "correctionField, and the Ethernet (0x88F7) / UDP (319/320) transport "
        "mappings. It does NOT impose PDK-specific SDC / floorplan "
        "constraints; the accuracy-critical implementation constraint is the "
        "placement of the hardware-timestamp unit at the MAC/PHY plane and the "
        "servo / oscillator quality. Carrier (Ethernet / UDP) electricals are "
        "physical-layer concerns.")
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
        {"name": "Management messages (data sets)", "purpose": "Read/write "
         "defaultDS / currentDS / portDS / parentDS for monitoring and "
         "configuration."},
        {"name": "currentDS (offsetFromMaster / meanPathDelay)",
         "purpose": "Live synchronization-error observability."},
        {"name": "portDS (portState)", "purpose": "BMCA state observability "
         "per port."},
        {"name": "Timestamp / correctionField inspection",
         "purpose": "Raw T1..T4 and Transparent-Clock residence observability."},
        {"name": "1PPS / ToD output", "purpose": "External sync-error "
         "measurement."},
    ]
    f["internal_diagnostics_observability"] = [
        "Port state (INITIALIZING / LISTENING / MASTER / SLAVE / PASSIVE / "
        "UNCALIBRATED).",
        "offsetFromMaster and meanPathDelay (currentDS).",
        "Grandmaster identity and stepsRemoved (parentDS).",
        "Servo lock / holdover status.",
        "Hardware-timestamp captures (T1/T2/T3/T4).",
    ]
    f["out_of_band_test_facilities"] = [
        "IEEE 1588 / IEEE 802.1AS conformance and interoperability testing.",
        "Vendor SoC JTAG / scan / BIST (implementation-defined).",
    ]
    f["notes"] = (
        "PTP's protocol-level DFT surface is the data sets via Management "
        "messages (currentDS / portDS / parentDS), the raw timestamps and "
        "correctionField, and the 1PPS/ToD output for external measurement. "
        "Chip-level JTAG / scan / BIST remain SoC-integrator concerns; "
        "conformance is established by IEEE 1588 / 802.1AS testing.")
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
        {"state": "Active", "name": "Synchronized", "description": "The clock "
         "is locked and exchanging PTP messages; the servo is tracking."},
        {"state": "Holdover", "name": "Holdover", "description": "The master "
         "is lost; the servo holds over on the local oscillator."},
        {"state": "Listening", "name": "Listening", "description": "Collecting "
         "Announce messages for the BMCA; reduced activity."},
    ]
    f["wakeup_mechanism"] = (
        "PTP defines no link-level power-down of its own; the node remains "
        "able to receive Announce / Sync messages. On master loss the servo "
        "enters holdover rather than powering down, to preserve time.")
    f["power_rails"] = [
        {"rail": "VDD (logic / timestamp unit)", "purpose": "Protocol engine, "
         "hardware-timestamp counter, and servo supply."},
        {"rail": "Oscillator supply", "purpose": "The local oscillator that "
         "the servo disciplines."},
        {"rail": "GND", "purpose": "Ground."},
    ]
    f["ptp_power_considerations"] = (
        "PTP's main power-relevant behavior is keeping the hardware-timestamp "
        "counter and oscillator running so time is preserved; holdover after "
        "master loss is a timing-quality concern, not a low-power sleep. Most "
        "energy management is an SoC / implementation concern.")
    f["notes"] = (
        "PTP does not define a fine-grained power-domain spec. Its "
        "power-relevant states are synchronized / holdover / listening; the "
        "timestamp counter and oscillator must keep running to preserve time. "
        "Detailed rails and low-power behavior are implementation concerns.")
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
        "Sync / Follow_Up exchange (one-step and two-step) — T1 / T2 capture.",
        "Delay_Req / Delay_Resp exchange — T3 / T4 capture.",
        "Peer delay mechanism — Pdelay_Req / Pdelay_Resp / "
        "Pdelay_Resp_Follow_Up; link delay.",
        "offsetFromMaster / meanPathDelay computation; correctionField "
        "subtraction.",
        "BMCA Grandmaster election (priority1 / clockClass / clockAccuracy / "
        "offsetScaledLogVariance / priority2 / clockIdentity).",
        "Port state machine transitions (MASTER / SLAVE / PASSIVE / "
        "UNCALIBRATED).",
        "Clock types — Ordinary / Boundary / Transparent (E2E / P2P); "
        "residence-time correction.",
        "Hardware-timestamp accuracy at the MAC/PHY plane.",
        "Servo lock, asymmetry correction, and holdover.",
        "Transport — Ethernet (0x88F7) and UDP (319/320); domain isolation.",
        "Timeouts — announceReceiptTimeout / syncReceiptTimeout.",
        "Sub-microsecond accuracy budget (default / 802.1AS).",
    ]
    f["notes"] = (
        "PTP does not ship an embedded testbench, but the standard implies a "
        "verification plan spanning the message exchange (Sync/Delay/Pdelay), "
        "the offset/delay computation and correctionField, the BMCA, the port "
        "state machine, the clock types, hardware timestamping, the servo, and "
        "the transport mappings. IEEE 1588 / IEEE 802.1AS conformance suites "
        "supply the formal tests.")
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
    f["security_requirements_present"] = "partial"
    f["anti_corruption_features"] = [
        "sequenceId detects lost or reordered messages.",
        "domainNumber isolates synchronization hierarchies.",
        "announceReceiptTimeout / syncReceiptTimeout detect loss of master / "
        "sync.",
        "The carrier's FCS / UDP checksum detects message corruption.",
    ]
    f["anti_tampering_features"] = [
        "IEEE 1588-2019 defines optional security TLVs (an integrity / "
        "authentication mechanism) to protect PTP messages.",
    ]
    f["confidentiality_features"] = []
    f["authentication_features"] = [
        "IEEE 1588-2019 Annex security mechanism (TLV-based message "
        "authentication / integrity), optional.",
    ]
    f["future_security_pointers"] = [
        "PTPv2 (1588-2008) has no built-in cryptographic protection; a forged "
        "Announce or Sync can mislead the BMCA or the servo (a time-spoofing "
        "attack).",
        "IEEE 1588-2019 adds optional security TLVs; deployments may also use "
        "MACsec / IPsec on the carrier to protect PTP messages.",
    ]
    f["notes"] = (
        "Base PTPv2 provides no confidentiality or authentication; its native "
        "protections are anti-corruption (sequenceId, domain isolation, "
        "timeouts) plus the carrier FCS/checksum. IEEE 1588-2019 introduces "
        "optional security TLVs for message authentication / integrity. "
        "Time-spoofing (forged Announce / Sync) is the principal threat, "
        "mitigated by the security TLVs or by securing the carrier "
        "(MACsec / IPsec).")
    _write(p, d)
