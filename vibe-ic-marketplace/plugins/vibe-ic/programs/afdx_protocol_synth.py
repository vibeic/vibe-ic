"""AFDX / ARINC 664 Part 7 protocol synth helper.

Avionics Full-Duplex Switched Ethernet (AFDX), standardized as ARINC
Specification 664 Part 7 (Aircraft Data Network, Part 7). AFDX is the
deterministic, redundant, profiled-Ethernet avionics data backbone used on
the Airbus A380 / A350 and Boeing 787. It is built on IEEE 802.3
full-duplex switched Ethernet but adds determinism: Virtual Links (VL)
identified by a 16-bit VL ID carried in the destination MAC address (with
Sub-VLs), a Bandwidth Allocation Gap (BAG, a power-of-two 1..128 ms minimum
inter-frame interval) plus jitter bound and traffic shaping/policing, and
dual-network (Network A / Network B) redundancy with a 1-byte Sequence
Number, per-network Integrity Checking, and first-valid-wins Redundancy
Management. End Systems and AFDX Switches carry UDP/IP over the VL with
sampling / queuing communication ports.

Doctrine — GENERAL not keyword: detection uses canonical STRUCTURAL
wire-level signatures (Virtual Link + VL ID in the MAC dest address, BAG,
dual-network redundancy with Sequence Number + Integrity Checking +
Redundancy Management, End System, ARINC 664) PLUS the canonical protocol
NAME / spec-id token read from the L-doc CONTENT blob. It NEVER reads the
input-document filename or the benchmark folder name (a code review flagged
exactly that as a HIGH defect on the AHB+APB detector; this module does not
repeat it — the runner-side detector predicate `is_afdx` is evaluated on
the L-doc CONTENT blob only).

Sibling disambiguation — AFDX EXTENDS IEEE 802.3 Ethernet. Because AFDX is
"profiled Ethernet" the L-docs name "Ethernet" / "802.3" / "MAC" / "frame",
so the base Ethernet structural signature matches and the inline Ethernet
sub-detector in the runner fires FIRST, populating plain-Ethernet
L1/L2/L3/L4 values (MII/GMII, MAC, preamble/SFD, best-effort frames). AFDX
is a DIFFERENT, deterministic profile on top of that Ethernet, so this
module FORCE-OVERWRITES (direct-assign, NOT setdefault) every L1..L23 key
the Ethernet synth populates, replacing the best-effort-Ethernet values
with the AFDX-canonical deterministic values (Virtual Links + BAG +
redundancy + End System + Switch + UDP/IP sampling/queuing ports). The AFDX
detector REQUIRES the AFDX-only structural tokens (Virtual Link + BAG +
Network A/B redundancy management + ARINC 664 + End System) so it does NOT
false-fire on a plain IEEE 802.3 Ethernet spec, an ARINC 429 spec
(32-bit-word / Label / point-to-point — no VL / BAG / switched fabric), or
a PROFINET spec (IO-Controller / GSDML / IRT). The Ethernet detector keys
on plain-802.3 tokens and is harmless here because AFDX runs last and wins
via direct assignment.

SIGNATURE (the runner wires this; evaluated on the L1/L2/L3 content
blob, never on a filename) — see `is_afdx` below.

Public entry: `apply_afdx_synth(generated_docs_dir, is_afdx, afdx_ic_name)`.
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


# ----------------------------------------------------------------------
# DETECTOR — content-only, structural-signal AFDX / ARINC 664 Part 7
# detector with an Ethernet / ARINC-429 / PROFINET sibling MUTEX.
# ----------------------------------------------------------------------
def is_afdx(blob: str) -> bool:
    """Content-only AFDX (ARINC 664 Part 7) detector with sibling MUTEX.

    Fire on the AFDX structural signature: deterministic profiled switched
    Ethernet that REQUIRES a Virtual Link (VL) abstraction PLUS the
    determinism mechanisms that distinguish AFDX from plain Ethernet —
    Bandwidth Allocation Gap (BAG), dual-network (Network A / Network B)
    redundancy with a Sequence Number + Integrity Checking + Redundancy
    Management, and the End System / AFDX Switch component model, anchored
    by the ARINC 664 / AFDX name token.

    Defer (do NOT fire) if the doc is:
      - plain-IEEE-802.3-Ethernet-primary (MII/GMII/802.3 frames with NO
        Virtual Link / BAG / dual-network redundancy),
      - ARINC-429-primary (32-bit word / Label / point-to-point bus with NO
        switched fabric / VL / BAG), or
      - PROFINET-primary (IO-Controller / GSDML / IRT).

    Reads ONLY the spec text `blob` — never a filename or benchmark name.
    Word-boundary / token-anchored throughout.
    """
    if not blob:
        return False
    import re
    low = blob.lower()

    # --- AFDX-only structural tokens (absent from a plain 802.3 spec). ---
    # Name / spec-id anchor.
    name_token = (
        "afdx" in low
        or "avionics full-duplex switched ethernet" in low
        or "avionics full duplex switched ethernet" in low
    )
    arinc664 = (
        "arinc 664" in low or "arinc664" in low
        or "664 part 7" in low or "664p7" in low
        or "664-p7" in low
    )

    # Virtual Link is THE central AFDX abstraction.
    virtual_link = (
        "virtual link" in low
        or "vl id" in low or "vlid" in low
        or "virtual link identifier" in low
    )

    # Bandwidth Allocation Gap — AFDX-specific traffic-shaping mechanism.
    # Require the full term OR the \bbag\b token in genuine BAG context
    # (allocation gap / power-of-two / inter-frame / explicit ms BAG value).
    # The bare 'bag' substring is NOT enough: avionics docs contain unrelated
    # phrases such as "electronic flight bag" that must not trip BAG.
    bag = (
        "bandwidth allocation gap" in low
        or (bool(re.search(r"\bbag\b", low))
            and ("allocation gap" in low
                 or "inter-frame" in low or "interframe" in low
                 or "power of two" in low or "power-of-two" in low
                 or bool(re.search(r"\bbag\b[^.\n]{0,40}\bms\b", low))
                 or "minimum interval between" in low))
    )

    # Dual-network redundancy + redundancy management + integrity checking.
    dual_network = (
        ("network a" in low and "network b" in low)
        or "dual redundant" in low
        or "redundant network" in low
    )
    redundancy_mgmt = (
        "redundancy management" in low
        or ("integrity check" in low and "sequence number" in low)
        or ("first valid" in low and "sequence number" in low)
    )

    # Component model.
    end_system = (
        "end system" in low or "end-system" in low
        or "afdx switch" in low
    )

    # --- Sibling MUTEX (defer when a sibling clearly dominates). ---
    # ARINC-429-primary: 32-bit word + Label + point-to-point bus, with NO
    # AFDX switched-fabric / VL / BAG structure.
    arinc429_primary = (
        ("arinc 429" in low or "mark 33" in low or "dits" in low)
        and ("32-bit word" in low or "label" in low)
        and not (virtual_link or bag or dual_network or name_token
                 or arinc664)
    )
    if arinc429_primary:
        return False

    # PROFINET-primary: IO-Controller / GSDML / IRT, with NO AFDX structure.
    profinet_primary = (
        "profinet" in low
        and ("io-controller" in low or "io controller" in low
             or "gsdml" in low or "irt" in low)
        and not (virtual_link or bag or dual_network or name_token
                 or arinc664)
    )
    if profinet_primary:
        return False

    # Plain-Ethernet-primary: 802.3 / MII / MAC frames, but NONE of the AFDX
    # determinism structure (no VL, no BAG, no dual-network RM). Defer so a
    # vanilla IEEE 802.3 spec cannot false-fire.
    ethernet_primary = (
        ("802.3" in low or "mii" in low or "gmii" in low
         or "preamble" in low or "sfd" in low)
        and not (virtual_link or bag
                 or (dual_network and redundancy_mgmt)
                 or name_token or arinc664)
    )
    if ethernet_primary:
        return False

    # --- AFDX structural fire: REQUIRE the full determinism stack, not just a
    # name token. Virtual Link + BAG + dual-network-redundancy (or redundancy
    # management) + End System, anchored by the AFDX / ARINC 664 name. A doc
    # that merely MENTIONS AFDX (e.g. an ARINC 429 spec comparing itself to
    # AFDX) lacks BAG + dual-network + End System and therefore does NOT fire.
    afdx_structure = (
        virtual_link
        and bag
        and (dual_network or redundancy_mgmt)
        and end_system
    )

    return bool(afdx_structure and (name_token or arinc664))


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

# Canonical AFDX facts (ARINC 664 Part 7).
_BAG_MS = [1, 2, 4, 8, 16, 32, 64, 128]
_VL_ID_BITS = 16
_SN_BITS = 8
_AFDX_PAYLOAD_MIN = 17
_AFDX_PAYLOAD_MAX = 1471
_MAX_SUB_VL = 4
_MAX_JITTER_US = 500


def apply_afdx_synth(generated_docs_dir: Path, is_afdx_flag: bool,
                     afdx_ic_name: Optional[str]) -> None:
    """Apply AFDX / ARINC 664 Part 7 synth when the AFDX signature matched.

    Because AFDX is profiled Ethernet, the inline Ethernet sub-detector
    fires first and populates plain-Ethernet L1..L23 values. This routine
    FORCE-OVERWRITES (direct assignment) the Ethernet-sibling keys with the
    AFDX-canonical deterministic values, so it MUST run AFTER the Ethernet
    synth.
    """
    if not is_afdx_flag:
        return
    gd = Path(generated_docs_dir)

    # --- Force ic_name across ALL 24 docs FIRST (main + fields docs). ---
    if afdx_ic_name is not None:
        for n in _MAIN_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                d["ic_name"] = afdx_ic_name
                _write(q, d)
        for n in _FIELDS_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                f = _ensure_dict(d, "fields")
                f["ic_name"] = afdx_ic_name
                d["ic_name"] = afdx_ic_name  # belt-and-braces top-level
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
# L1 — FORCE-OVERWRITE the Ethernet-sibling datasheet header with the AFDX
# deterministic profiled-Ethernet avionics network datasheet.
# ----------------------------------------------------------------------
def _l1(gd: Path) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    d["document_title"] = (
        "Avionics Full-Duplex Switched Ethernet (AFDX) — ARINC 664 Part 7")
    d["version"] = (
        "ARINC Specification 664 Part 7 (Aircraft Data Network, Part 7)")
    d["revised_date"] = "ARINC 664P7"
    d["manufacturer"] = (
        "Aeronautical Radio, Inc. (ARINC) — Airlines Electronic Engineering "
        "Committee (AEEC)")
    d["copyright"] = "© ARINC / AEEC"
    d["abstract"] = (
        "Avionics Full-Duplex Switched Ethernet (AFDX), standardized as ARINC "
        "664 Part 7, is a deterministic, redundant, profiled-Ethernet avionics "
        "data network used as the backbone of aircraft such as the Airbus "
        "A380/A350 and Boeing 787. AFDX is built on IEEE 802.3 full-duplex "
        "switched Ethernet (no shared medium, no collisions, no CSMA/CD; "
        "point-to-point 10/100 Mbit/s links) but adds determinism on top: "
        "Virtual Links (VL) — unidirectional logical connections from one "
        "source End System to one or more destinations, identified by a "
        "16-bit Virtual Link Identifier (VL ID) carried in the Ethernet "
        "destination MAC address, optionally subdivided into up to four "
        "Sub-Virtual Links (Sub-VLs); a Bandwidth Allocation Gap (BAG) — the "
        "guaranteed minimum interval between frames of a VL, a power of two "
        "from 1 to 128 ms — plus a bounded jitter and traffic "
        "shaping/policing; and dual-network redundancy (independent Network A "
        "and Network B) where every frame is replicated on both networks and "
        "reconciled at the receiver by a 1-byte Sequence Number, per-network "
        "Integrity Checking (IC), and first-valid-wins Redundancy Management "
        "(RM). The network is composed of End Systems (ES) and AFDX Switches, "
        "carrying UDP/IP over the Virtual Link with sampling and queuing "
        "communication ports.")
    d["keywords"] = [
        "AFDX", "ARINC 664", "ARINC 664 Part 7", "Avionics Full-Duplex "
        "Switched Ethernet", "Virtual Link", "VL", "VL ID", "Virtual Link "
        "Identifier", "Sub-VL", "Sub-Virtual Link", "Bandwidth Allocation "
        "Gap", "BAG", "jitter", "traffic shaping", "traffic policing",
        "Network A", "Network B", "dual redundant", "Redundancy Management",
        "Integrity Checking", "Sequence Number", "first valid wins",
        "End System", "AFDX Switch", "sampling port", "queuing port",
        "UDP/IP", "IEEE 802.3", "full-duplex switched Ethernet",
        "deterministic", "Lmax", "100BASE-TX",
    ]
    d["external_pins"] = [
        "Network A port (full-duplex IEEE 802.3, typically 100BASE-TX, "
        "10/100 Mbit/s): TX+/TX-, RX+/RX- differential pairs to Network A",
        "Network B port (full-duplex IEEE 802.3, typically 100BASE-TX, "
        "10/100 Mbit/s): TX+/TX-, RX+/RX- differential pairs to Network B "
        "(physically independent redundant network)",
        "MDIO / MDC management interface to the Ethernet PHY",
        "Host / application interface to the avionics subsystem (LRU)",
        "No shared medium — every link is point-to-point full-duplex (no "
        "collisions, no CSMA/CD)",
    ]
    d["base_technology"] = "IEEE 802.3 full-duplex switched Ethernet"
    d["link_rates_Mbps"] = [10, 100]
    d["vl_id_bits"] = _VL_ID_BITS
    d["sequence_number_bits"] = _SN_BITS
    d["bag_values_ms"] = list(_BAG_MS)
    d["max_sub_vl_per_vl"] = _MAX_SUB_VL
    d["afdx_payload_bytes"] = {"min": _AFDX_PAYLOAD_MIN,
                               "max": _AFDX_PAYLOAD_MAX}
    d["modes_of_operation"] = [
        {"name": "End System (ES)",
         "role": "avionics network interface",
         "note": "Connects an LRU/host to the AFDX network; performs per-VL "
                 "traffic shaping (BAG + jitter), Sub-VL round-robin, "
                 "Sequence-Number insertion, frame replication onto Network "
                 "A/B, and receive-side Integrity Checking + Redundancy "
                 "Management."},
        {"name": "AFDX Switch",
         "role": "deterministic store-and-forward switch",
         "note": "Forwards frames by Virtual Link Identifier using a static "
                 "configuration table (VL ID → output ports); polices each "
                 "VL against its BAG/Lmax (traffic filtering and policing); "
                 "full-duplex point-to-point links; no dynamic MAC learning, "
                 "no spanning tree."},
    ]
    d["key_features"] = [
        "Deterministic, redundant, profiled-Ethernet avionics data network "
        "(ARINC 664 Part 7) built on IEEE 802.3 full-duplex switched "
        "Ethernet — no shared medium, no collisions, no CSMA/CD.",
        "Virtual Links (VL): unidirectional logical connections, one source "
        "End System to one or more destinations (point-to-point or "
        "multicast), identified by a 16-bit Virtual Link Identifier carried "
        "in the destination MAC address.",
        "Sub-Virtual Links (Sub-VLs): up to four per VL, each with its own "
        "FIFO, round-robin multiplexed into the parent VL shaper; Sub-VLs "
        "share the parent VL's BAG and do not appear on the wire.",
        "Bandwidth Allocation Gap (BAG): guaranteed minimum inter-frame "
        "interval per VL, a power of two from 1 to 128 ms; max VL bandwidth "
        "= Lmax / BAG.",
        "Bounded jitter at the End System output (typically ≤ 500 µs) plus "
        "transmit traffic shaping and AFDX-Switch ingress traffic policing.",
        "Dual-network redundancy: independent Network A and Network B; every "
        "frame replicated on both; tolerates loss of one whole network.",
        "Redundancy Management (RM) + Integrity Checking (IC) using a 1-byte "
        "Sequence Number per VL; per-network IC checks the SN window; RM "
        "merges the two streams with a first-valid-frame-wins rule.",
        "End Systems and AFDX Switches; UDP/IP over the Virtual Link.",
        "Sampling ports (single overwriting message with freshness) and "
        "queuing ports (FIFO, lossless) as application communication ports.",
        "Standard IEEE 802.3 Ethernet frame format with the VL ID in the "
        "destination MAC and a 1-byte Sequence Number before the FCS.",
        "Statically configured offline (VL ID, BAG, Lmax/Lmin, Sub-VL count, "
        "source/destination End Systems, switch forwarding + policing) for "
        "offline certification of timing and bandwidth.",
    ]
    d["topology_summary"] = (
        "Star/switched topology: End Systems connect via point-to-point "
        "full-duplex links to AFDX Switches, which interconnect into a "
        "deterministic switched fabric. The whole fabric is duplicated as two "
        "independent networks (Network A and Network B). Virtual Links define "
        "unidirectional source→destination(s) paths over this fabric.")
    d["use_cases"] = [
        "Avionics data backbone on Airbus A380 / A350 and Boeing 787",
        "Deterministic interconnect between line-replaceable units (LRUs)",
        "Safety-critical flight-control, display, and sensor data transport",
        "Replacement of point-to-point ARINC 429 buses with a switched, "
        "bandwidth-guaranteed network",
    ]
    d["revision_history"] = [
        {"version": "ARINC 664 Part 7",
         "date": "Aircraft Data Network, Part 7",
         "description": "Avionics Full-Duplex Switched Ethernet Network — "
                        "deterministic profiled IEEE 802.3 Ethernet with "
                        "Virtual Links, BAG, dual-network redundancy with "
                        "Sequence Number / Integrity Checking / Redundancy "
                        "Management, End Systems and AFDX Switches, UDP/IP."},
    ]
    d["overview"] = (
        "AFDX (ARINC 664 Part 7) is a deterministic, fault-tolerant avionics "
        "data network. It takes commercial IEEE 802.3 full-duplex switched "
        "Ethernet — which is non-deterministic (best-effort, unbounded "
        "latency) — and profiles it for safety-critical use by adding Virtual "
        "Links, the Bandwidth Allocation Gap, bounded jitter, traffic "
        "shaping/policing, and dual-network redundancy with Sequence-Number "
        "Integrity Checking and first-valid-wins Redundancy Management. A "
        "Virtual Link is a unidirectional logical pipe from one source End "
        "System to one or more destinations, identified by a 16-bit VL ID in "
        "the destination MAC address, optionally split into up to four "
        "Sub-VLs. Each VL has a BAG (1..128 ms, power of two) that bounds its "
        "frame rate and an Lmax that bounds frame size, so VL bandwidth = "
        "Lmax / BAG is guaranteed and bounded. Transmitting End Systems shape "
        "traffic to the BAG and jitter; AFDX Switches police each VL and drop "
        "non-conformant frames, protecting the network from a babbling "
        "source. Every frame is sent on both Network A and Network B; the "
        "receiver checks the 1-byte Sequence Number per network (Integrity "
        "Checking) and merges the redundant copies first-valid-wins "
        "(Redundancy Management). UDP/IP rides over the VL, with sampling and "
        "queuing communication ports to the avionics application.")
    _write(p, d)


# ----------------------------------------------------------------------
# L2 — FORCE-OVERWRITE the Ethernet protocol_overview + FRS with the AFDX
# deterministic profiled-Ethernet model.
# ----------------------------------------------------------------------
def _l2(gd: Path) -> None:
    p = gd / "L2_FRS.json"
    if not p.is_file():
        return
    d = _read(p)
    po = _ensure_dict(d, "protocol_overview")
    po["type"] = (
        "Deterministic, redundant, profiled-Ethernet avionics data network "
        "(ARINC 664 Part 7 / AFDX). Built on IEEE 802.3 full-duplex switched "
        "Ethernet; adds Virtual Links, Bandwidth Allocation Gap traffic "
        "shaping, bounded jitter, and dual-network (A/B) redundancy with "
        "Sequence-Number Integrity Checking and first-valid-wins Redundancy "
        "Management.")
    po["base_technology"] = "IEEE 802.3 full-duplex switched Ethernet"
    po["duplex"] = (
        "full-duplex point-to-point links (no shared medium, no collisions, "
        "no CSMA/CD); typically 100BASE-TX at 10/100 Mbit/s.")
    po["deterministic"] = True
    po["redundant"] = True
    po["virtual_link"] = {
        "definition": "Unidirectional logical connection from one source End "
                      "System to one or more destination End Systems "
                      "(point-to-point or point-to-multipoint / multicast).",
        "id_bits": _VL_ID_BITS,
        "id_location": "carried in the Ethernet destination MAC address "
                       "(constant field 0x03:00:00:00 + 16-bit VL ID)",
        "sub_vl_max": _MAX_SUB_VL,
        "sub_vl_note": "Up to 4 Sub-VLs per VL, each with its own FIFO, "
                       "round-robin multiplexed into the parent VL shaper; "
                       "Sub-VLs share the parent BAG and do not appear on "
                       "the wire.",
    }
    po["bandwidth_allocation_gap"] = {
        "definition": "Guaranteed minimum interval between the first bits of "
                      "two consecutive frames on the same Virtual Link.",
        "values_ms": list(_BAG_MS),
        "rule": "BAG = 2^k ms, k = 0..7 (1, 2, 4, 8, 16, 32, 64, 128 ms).",
        "max_vl_bandwidth": "Lmax / BAG",
    }
    po["jitter"] = {
        "definition": "Allowed variation of a frame's presentation time vs "
                      "the ideal BAG-spaced instant at the End System output.",
        "max_us": _MAX_JITTER_US,
        "note": "Bounded as a function of the Lmax values and link rate of "
                "the VLs sharing the physical port.",
    }
    po["traffic_shaping"] = (
        "Performed at the transmitting End System: regulates each VL to its "
        "BAG and jitter before frames enter the network.")
    po["traffic_policing"] = (
        "Performed at the AFDX Switch ingress: polices each VL against its "
        "configured BAG and Lmax (token/leaky-bucket) and drops frames from a "
        "VL exceeding its allocation (babbling-source protection).")
    po["redundancy"] = {
        "networks": ["Network A", "Network B"],
        "scheme": "Two physically independent networks; every frame "
                  "replicated on both.",
        "sequence_number_bits": _SN_BITS,
        "sequence_number_range": "1..255 (0 reserved for reset / first "
                                 "frame)",
        "integrity_checking": "Per-network (A and B) check that each frame's "
                              "Sequence Number is within the expected window "
                              "for its VL; out-of-range frames rejected.",
        "redundancy_management": "Merge the two streams first-valid-wins: the "
                                 "first correctly-received copy of a given "
                                 "Sequence Number is delivered; the duplicate "
                                 "is discarded; can be enabled/disabled "
                                 "per-VL.",
    }
    po["protocol_stack"] = "Ethernet (AFDX) | IP (IPv4) | UDP | AFDX payload | "
    po["protocol_stack"] += "Sequence Number | FCS"
    po["communication_ports"] = {
        "sampling": "Holds a single message; a new message overwrites the "
                    "previous one; reader gets the latest value plus a "
                    "freshness/validity indication.",
        "queuing": "FIFO queue buffering multiple messages delivered in "
                   "order without overwriting (lossless).",
    }
    po["components"] = ["End System (ES)", "AFDX Switch"]
    d["functional_requirements"] = [
        {"id": "FR-BASE-01", "text": "AFDX is built on IEEE 802.3 full-duplex "
         "switched Ethernet — point-to-point links, no shared medium, no "
         "collisions, no CSMA/CD — and preserves the standard Ethernet frame "
         "format."},
        {"id": "FR-VL-02", "text": "Traffic is segregated into Virtual Links "
         "(VL): unidirectional logical connections from one source End System "
         "to one or more destinations, identified by a 16-bit Virtual Link "
         "Identifier carried in the destination MAC address."},
        {"id": "FR-SUBVL-03", "text": "A Virtual Link may be subdivided into "
         "up to four Sub-VLs, each with its own FIFO, round-robin multiplexed "
         "into the parent VL shaper; Sub-VLs share the parent BAG and are not "
         "visible on the wire."},
        {"id": "FR-BAG-04", "text": "Each VL has a Bandwidth Allocation Gap "
         "(BAG), the guaranteed minimum interval between consecutive frames "
         "on that VL, a power of two from 1 to 128 ms; the maximum VL frame "
         "rate is 1/BAG and the maximum VL bandwidth is Lmax/BAG."},
        {"id": "FR-JITTER-05", "text": "The End System bounds the transmit "
         "jitter on each VL (typically ≤ 500 µs), computed from the Lmax and "
         "link rate of the VLs sharing the physical port."},
        {"id": "FR-SHAPE-06", "text": "The transmitting End System shapes each "
         "VL to its BAG and jitter; the AFDX Switch polices each VL against "
         "its BAG/Lmax and drops non-conformant frames."},
        {"id": "FR-REDUN-07", "text": "Two physically independent networks "
         "(Network A and Network B) are deployed; by default every frame is "
         "transmitted on both networks simultaneously."},
        {"id": "FR-SN-08", "text": "A 1-byte Sequence Number is appended to "
         "every frame (after the payload, before the FCS), incrementing per "
         "frame on a VL and wrapping 255→1 (0 reserved)."},
        {"id": "FR-IC-09", "text": "Integrity Checking is performed "
         "independently on Network A and Network B: a frame whose Sequence "
         "Number is outside the expected window for its VL is rejected."},
        {"id": "FR-RM-10", "text": "Redundancy Management merges the two "
         "redundant streams first-valid-wins: the first valid copy of a given "
         "Sequence Number is delivered and the duplicate discarded; RM can be "
         "enabled or disabled per VL."},
        {"id": "FR-SWITCH-11", "text": "AFDX Switches are deterministic "
         "store-and-forward switches that forward by VL ID using a static "
         "configuration table (no dynamic learning, no spanning tree) and "
         "police each VL."},
        {"id": "FR-UDPIP-12", "text": "UDP/IP (IPv4, with IP fragmentation) "
         "rides over the Virtual Link; UDP ports identify the End System's "
         "communication ports."},
        {"id": "FR-PORTS-13", "text": "Two communication-port types are "
         "provided: sampling ports (single overwriting message with freshness "
         "indication) and queuing ports (FIFO, lossless)."},
    ]
    d["error_response_conditions"] = [
        "Frame fails Ethernet FCS (CRC-32) — dropped at the receiver.",
        "Sequence Number out of the expected window on a network — rejected "
        "as an Integrity Check error (per network).",
        "Duplicate of an already-accepted Sequence Number — discarded by "
        "Redundancy Management (first-valid-wins).",
        "VL exceeds its BAG/Lmax allocation at a switch — non-conformant "
        "frame policed (dropped).",
        "One whole network (A or B) fails — redundancy delivers the surviving "
        "copy transparently.",
        "Sampling-port data older than its validity timeout — flagged stale "
        "(not fresh) to the application.",
    ]
    d["compliance_requirements"] = [
        "IEEE 802.3 full-duplex switched Ethernet base (no CSMA/CD).",
        "Virtual Links with 16-bit VL ID in the destination MAC; up to 4 "
        "Sub-VLs per VL.",
        "BAG ∈ {1,2,4,8,16,32,64,128} ms with bounded jitter; transmit "
        "shaping + switch policing.",
        "Dual independent networks A/B with per-frame replication.",
        "1-byte Sequence Number, per-network Integrity Checking, "
        "first-valid-wins Redundancy Management.",
        "Deterministic store-and-forward switches forwarding by VL ID with "
        "static configuration.",
        "UDP/IP over the VL with sampling and queuing communication ports.",
        "Offline static configuration enabling certification of timing and "
        "bandwidth.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L3 — FORCE-OVERWRITE the Ethernet framing/channels with the AFDX
# VL + BAG + redundancy + frame-format model.
# ----------------------------------------------------------------------
def _l3(gd: Path) -> None:
    p = gd / "L3_CMD_PROTOCOL.json"
    if not p.is_file():
        return
    d = _read(p)
    d["protocol_type"] = (
        "Deterministic profiled-Ethernet network protocol (ARINC 664 Part 7 "
        "/ AFDX). Standard IEEE 802.3 frames are segregated into Virtual "
        "Links (16-bit VL ID in the destination MAC), rate-shaped by a "
        "Bandwidth Allocation Gap, tagged with a 1-byte Sequence Number, and "
        "replicated onto two independent networks (A/B) that are reconciled "
        "at the receiver by Integrity Checking + first-valid-wins Redundancy "
        "Management. UDP/IP rides over the VL.")
    d["base_technology"] = "IEEE 802.3 full-duplex switched Ethernet"
    d["channels"] = [
        {"name": "Network A port",
         "direction": "full-duplex (TX + RX)",
         "description": "IEEE 802.3 full-duplex link (typically 100BASE-TX, "
                        "10/100 Mbit/s) to Network A; carries one copy of "
                        "every transmitted frame."},
        {"name": "Network B port",
         "direction": "full-duplex (TX + RX)",
         "description": "Physically independent IEEE 802.3 full-duplex link "
                        "to Network B; carries the redundant copy of every "
                        "frame."},
        {"name": "Host / application interface",
         "direction": "bidirectional",
         "description": "Sampling and queuing communication ports (UDP/IP) "
                        "between the avionics application and the End "
                        "System."},
    ]
    d["frame_format"] = {
        "base": "Standard IEEE 802.3 Ethernet frame.",
        "fields": [
            {"field": "Destination MAC address", "bytes": 6,
             "note": "Constant field (32 bits, 0x03:00:00:00) + 16-bit "
                     "Virtual Link Identifier (VL ID). Switches forward on "
                     "VL ID."},
            {"field": "Source MAC address", "bytes": 6,
             "note": "Constant field + network/equipment identifier of the "
                     "source End System."},
            {"field": "EtherType / Length", "bytes": 2,
             "note": "IP (0x0800)."},
            {"field": "Payload (IP + UDP + AFDX payload)", "bytes": "variable",
             "note": f"AFDX application payload is {_AFDX_PAYLOAD_MIN}..."
                     f"{_AFDX_PAYLOAD_MAX} bytes; IPv4 + UDP headers above."},
            {"field": "Sequence Number", "bytes": 1,
             "note": "AFDX redundancy Sequence Number, after the payload and "
                     "before the FCS; range 1..255 (0 reserved)."},
            {"field": "Frame Check Sequence (FCS)", "bytes": 4,
             "note": "Standard Ethernet CRC-32."},
        ],
        "frame_size": "Standard Ethernet 64..1518 bytes (excluding "
                      "preamble/SFD); short frames padded to 64.",
        "vl_id_in_dest_mac": True,
        "sequence_number_before_fcs": True,
    }
    d["virtual_link"] = {
        "id_bits": _VL_ID_BITS,
        "id_location": "destination MAC address (constant 0x03:00:00:00 + "
                       "16-bit VL ID)",
        "direction": "unidirectional (one source ES → one or more "
                     "destination ES)",
        "multicast": True,
        "sub_vl_max": _MAX_SUB_VL,
        "sub_vl_scheduling": "round-robin across up to 4 Sub-VL FIFOs into "
                             "the parent VL shaper",
        "forwarding": "AFDX switches forward by VL ID using a static "
                      "configuration table (VL ID → output ports); no dynamic "
                      "MAC learning, no spanning tree.",
    }
    d["bandwidth_allocation_gap"] = {
        "values_ms": list(_BAG_MS),
        "rule": "power of two, 1..128 ms (BAG = 2^k ms, k=0..7)",
        "max_frame_rate": "1 / BAG frames per second",
        "max_bandwidth": "Lmax / BAG",
        "lmax_lmin": f"per-VL Lmax / Lmin; AFDX payload "
                     f"{_AFDX_PAYLOAD_MIN}..{_AFDX_PAYLOAD_MAX} bytes",
    }
    d["redundancy"] = {
        "networks": ["Network A", "Network B"],
        "replication": "every frame sent on both networks",
        "sequence_number_bits": _SN_BITS,
        "sequence_number_range": "1..255 (0 reserved)",
        "integrity_checking": "per-network SN-window check",
        "redundancy_management": "first-valid-wins merge of A/B; duplicate "
                                 "discarded; per-VL enable/disable",
    }
    d["protocol_layers"] = [
        {"layer": "Application / communication ports",
         "purpose": "Sampling (overwriting, freshness) and queuing (FIFO, "
                    "lossless) ports."},
        {"layer": "UDP",
         "purpose": "Connectionless; source/destination ports identify the "
                    "communication ports; no retransmission."},
        {"layer": "IP (IPv4)",
         "purpose": "Addressing + fragmentation/reassembly of messages "
                    "larger than Lmax."},
        {"layer": "AFDX MAC / Virtual Link",
         "purpose": "VL ID in dest MAC, Sequence Number, redundancy "
                    "replication, BAG shaping."},
        {"layer": "IEEE 802.3 full-duplex switched Ethernet PHY/MAC",
         "purpose": "Point-to-point full-duplex 10/100 Mbit/s; standard "
                    "frame + FCS."},
    ]
    d["addressing"] = {
        "vl_id_in_dest_mac": True,
        "vl_id_bits": _VL_ID_BITS,
        "udp_ports_identify_communication_ports": True,
        "note": "AFDX forwards on the Virtual Link Identifier (in the dest "
                "MAC); UDP/IP addresses/ports identify the application "
                "communication port within the destination End System.",
    }
    d["flow_control"] = (
        "No link-level retransmission (UDP). Determinism is provided by BAG "
        "rate-shaping + switch policing + offline bandwidth budgeting, not by "
        "backpressure; reliability is provided by dual-network redundancy.")
    _write(p, d)


# ----------------------------------------------------------------------
# L4 — FORCE-OVERWRITE the Ethernet MDIO/MII regmap with the AFDX per-VL
# configuration / status register model.
# ----------------------------------------------------------------------
def _l4(gd: Path) -> None:
    p = gd / "L4_REGMAP.json"
    if not p.is_file():
        return
    d = _read(p)
    d["register_map_present"] = True
    d["notes"] = (
        "AFDX is statically configured offline. The End System and AFDX "
        "Switch expose configuration/status tables (rather than a small "
        "control register file) describing each Virtual Link: VL ID, BAG, "
        "Lmax/Lmin, Sub-VL count, source/destination End Systems, switch "
        "forwarding entries (VL ID → output ports), per-VL policing "
        "parameters, and whether Redundancy Management is enabled. Run-time "
        "status includes per-VL Sequence-Number state, Integrity-Check / "
        "Redundancy-Management counters, and policing-drop counters.")
    d["configuration_tables"] = [
        {"table": "Virtual Link configuration (per VL)", "fields": [
            "VL ID (16-bit Virtual Link Identifier)",
            "BAG (1/2/4/8/16/32/64/128 ms)",
            "Lmax / Lmin (max / min frame size bytes)",
            "Sub-VL count (1..4)",
            "Source End System",
            "Destination End System set (multicast tree)",
            "Redundancy Management enable (per VL)"]},
        {"table": "Switch forwarding / policing (per VL, per switch)",
         "fields": [
            "VL ID → output-port set (static forwarding entry)",
            "Per-VL policing parameters (BAG, Lmax token/leaky-bucket)",
            "Policing action (drop non-conformant frames)"]},
        {"table": "End System communication ports", "fields": [
            "Port type (sampling / queuing)",
            "UDP source/destination port",
            "Associated VL ID",
            "Sampling freshness timeout / queuing depth"]},
    ]
    d["status_counters"] = [
        "Per-VL transmit Sequence-Number state",
        "Per-network (A/B) Integrity-Check pass/reject counters",
        "Redundancy-Management duplicate-discard counter",
        "Per-VL policing drop counter (switch)",
        "Sampling-port freshness / staleness flag",
        "Queuing-port overflow counter",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L5 — overwrite the Ethernet PHY analog spec with the AFDX dual-port
# 100BASE-TX physical-link spec.
# ----------------------------------------------------------------------
def _l5(gd: Path) -> None:
    p = gd / "L5_ADI_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["analog_digital_interface_present"] = True
    d["signaling_summary"] = (
        "AFDX uses standard IEEE 802.3 full-duplex Ethernet at the physical "
        "layer — typically 100BASE-TX (100 Mbit/s, MLT-3 over twisted pair) "
        "or 10BASE-T, point-to-point full-duplex (no shared medium, no "
        "collisions, no CSMA/CD). Each End System has TWO physical ports — "
        "one to Network A and one to Network B — that are electrically "
        "independent so a single physical-layer fault affects only one "
        "network. Determinism is enforced above the PHY (BAG shaping, "
        "policing); the analog layer is commercial Ethernet.")
    d["link_rates_Mbps"] = [10, 100]
    d["physical_layer"] = {
        "base": "IEEE 802.3 full-duplex switched Ethernet",
        "typical_phy": "100BASE-TX (MLT-3, twisted pair) / 10BASE-T",
        "duplex": "full-duplex point-to-point (no CSMA/CD)",
        "ports_per_end_system": 2,
        "ports_note": "one to Network A, one to Network B (independent)",
    }
    d["dual_network_independence"] = (
        "Network A and Network B use physically separate switches and cabling "
        "so a single physical fault (cut cable, failed port/switch) is "
        "confined to one network; the redundant copy survives.")
    d["clocking"] = (
        "Standard Ethernet PHY clock recovery from the encoded line (e.g. "
        "MLT-3 / 4B5B for 100BASE-TX); no special AFDX clocking — determinism "
        "is timing-budgeted at the network/VL level, not at the symbol "
        "level.")
    _write(p, d)


# ----------------------------------------------------------------------
# L6 — overwrite the Ethernet control logic with the AFDX End-System TX/RX
# FSMs (VL shaper, redundancy management, integrity checking).
# ----------------------------------------------------------------------
def _l6(gd: Path) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["fsm_states_vl_traffic_shaper"] = [
        {"name": "SUBVL_RR", "description": "Round-robin read across up to 4 "
         "Sub-VL FIFOs to pick the next frame for this Virtual Link."},
        {"name": "BAG_WAIT", "description": "Enforce the Bandwidth Allocation "
         "Gap: hold until at least BAG since the previous frame on this VL "
         "(within the jitter bound)."},
        {"name": "TX_REPLICATE", "description": "Append the 1-byte Sequence "
         "Number, then replicate the frame onto Network A and Network B."},
        {"name": "SN_INCREMENT", "description": "Advance the VL Sequence "
         "Number (wrap 255→1; 0 reserved)."},
    ]
    d["fsm_states_redundancy_rx"] = [
        {"name": "RX_A", "description": "Receive a frame on Network A; check "
         "Ethernet FCS."},
        {"name": "RX_B", "description": "Receive a frame on Network B; check "
         "Ethernet FCS."},
        {"name": "INTEGRITY_CHECK", "description": "Per network, verify the "
         "Sequence Number is within the expected window for the VL; reject "
         "out-of-range frames."},
        {"name": "REDUNDANCY_MERGE", "description": "First-valid-wins: accept "
         "the first valid copy of a given Sequence Number; discard the "
         "duplicate from the other network."},
        {"name": "DELIVER", "description": "Deliver the accepted frame's "
         "payload to the destination communication port (sampling overwrite "
         "or queuing enqueue)."},
    ]
    d["fsm_states_switch"] = [
        {"name": "INGRESS", "description": "Receive a frame on a full-duplex "
         "port; check FCS."},
        {"name": "POLICE", "description": "Police the frame's VL against its "
         "configured BAG/Lmax (token/leaky-bucket); drop if non-conformant."},
        {"name": "LOOKUP", "description": "Look up the VL ID in the static "
         "forwarding table to get the output-port set."},
        {"name": "FORWARD", "description": "Store-and-forward the frame to "
         "each output port (multicast to the VL's destinations)."},
    ]
    d["fsm_hints"] = {
        "trigger": "On each application write, the source Sub-VL FIFO is "
        "filled; the VL shaper round-robins Sub-VLs and gates on the BAG.",
        "rule": "Exactly one frame per VL per BAG (within jitter); every "
        "frame is replicated A/B with an incrementing Sequence Number.",
        "merge": "Receiver runs Integrity Checking per network then "
        "first-valid-wins Redundancy Management before delivery.",
    }
    d["anti_deadlock_rule"] = (
        "BAG shaping bounds each VL's rate and switch buffers are sized to "
        "the offline traffic budget, so no VL can starve others or overflow "
        "buffers; UDP is connectionless so there is no blocking handshake.")
    d["exit_from_reset_or_poweron"] = (
        "After reset the End System initializes per-VL Sequence Numbers (next "
        "frame uses the reset/first-frame convention), brings up both Network "
        "A and Network B Ethernet links, and begins BAG-shaped transmission; "
        "switches load their static forwarding/policing tables.")
    _write(p, d)


# ----------------------------------------------------------------------
# L7 — overwrite the Ethernet observability with AFDX VL/redundancy/policing
# observability.
# ----------------------------------------------------------------------
def _l7(gd: Path) -> None:
    p = gd / "L7_TEST_DEBUG.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_debug_architecture_present"] = True
    d["spec_provided_observability"] = [
        {"name": "Per-VL Sequence-Number state", "purpose": "Observe the "
         "transmit/receive Sequence Number per Virtual Link for redundancy "
         "debug."},
        {"name": "Integrity-Check counters (per network)", "purpose": "Count "
         "accepted vs rejected frames on Network A and Network B "
         "independently."},
        {"name": "Redundancy-Management duplicate discards", "purpose": "Count "
         "first-valid-wins duplicate discards to confirm both networks are "
         "delivering."},
        {"name": "Switch policing drops (per VL)", "purpose": "Count frames "
         "dropped by traffic policing to detect a babbling / over-rate VL."},
        {"name": "Sampling-port freshness", "purpose": "Per sampling port, a "
         "fresh/stale indication and validity timeout."},
        {"name": "Queuing-port depth / overflow", "purpose": "Observe FIFO "
         "occupancy and overflow on lossless queuing ports."},
    ]
    d["error_detection_mechanisms"] = [
        "Ethernet FCS (CRC-32) detects bit errors on each network.",
        "Per-network Integrity Checking detects out-of-window Sequence "
        "Numbers.",
        "Traffic policing at the switch detects/limits over-rate VLs.",
        "Sampling-port validity timeout detects stale data.",
        "Loss of one network is detected by the absence of one redundant "
        "copy (handled transparently by Redundancy Management).",
    ]
    d["notes"] = (
        "AFDX observability centers on per-VL Sequence-Number / "
        "Integrity-Check / Redundancy-Management counters at the End System "
        "and per-VL policing counters at the AFDX Switch, plus communication-"
        "port freshness/occupancy. The static offline configuration makes the "
        "expected timing/bandwidth deterministic and therefore verifiable.")
    _write(p, d)


# ----------------------------------------------------------------------
# L8 RTL constants — overwrite Ethernet constants with AFDX VL/BAG/SN/redun
# constants.
# ----------------------------------------------------------------------
def _l8_rtl(gd: Path) -> None:
    p = gd / "L8_RTL_CONSTANTS.json"
    if not p.is_file():
        return
    d = _read(p)
    wp = _ensure_dict(d, "width_parameters")
    wp.update({
        "SPEC": "ARINC 664 Part 7 (AFDX)",
        "BASE_TECHNOLOGY": "IEEE 802.3 full-duplex switched Ethernet",
        "VL_ID_WIDTH_BITS": _VL_ID_BITS,
        "SEQUENCE_NUMBER_WIDTH_BITS": _SN_BITS,
        "SEQUENCE_NUMBER_MIN": 1,
        "SEQUENCE_NUMBER_MAX": 255,
        "SEQUENCE_NUMBER_RESET": 0,
        "BAG_VALUES_MS": list(_BAG_MS),
        "BAG_MIN_MS": 1,
        "BAG_MAX_MS": 128,
        "MAX_SUB_VL_PER_VL": _MAX_SUB_VL,
        "MAX_JITTER_US": _MAX_JITTER_US,
        "AFDX_PAYLOAD_MIN_BYTES": _AFDX_PAYLOAD_MIN,
        "AFDX_PAYLOAD_MAX_BYTES": _AFDX_PAYLOAD_MAX,
        "ETHERNET_FRAME_MIN_BYTES": 64,
        "ETHERNET_FRAME_MAX_BYTES": 1518,
        "FCS_WIDTH_BITS": 32,
        "DEST_MAC_CONST_FIELD": "0x03000000",
        "NUM_REDUNDANT_NETWORKS": 2,
        "LINK_RATES_MBPS": [10, 100],
    })
    kc = _ensure_dict(d, "key_constants_for_RTL_authoring")
    kc.update({
        "is_deterministic_ethernet": True,
        "is_full_duplex_switched": True,
        "is_redundant_dual_network": True,
        "vl_id_in_dest_mac": True,
        "vl_id_bits": _VL_ID_BITS,
        "sequence_number_bits": _SN_BITS,
        "bag_power_of_two_ms": list(_BAG_MS),
        "max_sub_vl": _MAX_SUB_VL,
        "redundancy_first_valid_wins": True,
        "integrity_check_per_network": True,
        "traffic_shaping_at_end_system": True,
        "traffic_policing_at_switch": True,
        "udp_ip_over_vl": True,
        "no_csma_cd": True,
    })
    d["bag_constants"] = {
        "values_ms": list(_BAG_MS),
        "rule": "BAG = 2^k ms, k = 0..7",
        "max_bandwidth_per_vl": "Lmax / BAG",
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L8 timing — overwrite Ethernet timing with AFDX BAG / jitter / redundancy
# timing.
# ----------------------------------------------------------------------
def _l8_timing(gd: Path) -> None:
    p = gd / "L8_TIMING_WAVEFORM.json"
    if not p.is_file():
        return
    d = _read(p)
    d["bag_waveform"] = {
        "definition": "Minimum interval between the first bits of two "
                      "consecutive frames on the same Virtual Link.",
        "values_ms": list(_BAG_MS),
        "rule": "power of two, 1..128 ms",
        "max_frame_rate": "1 / BAG frames per second",
    }
    d["jitter_waveform"] = {
        "definition": "Variation of a frame's presentation time vs the ideal "
                      "BAG-spaced instant at the End System output.",
        "max_us": _MAX_JITTER_US,
        "note": "computed from Lmax + link rate of the VLs sharing the port",
    }
    d["redundancy_waveform"] = {
        "replication": "frame sent on Network A and Network B (near-"
                       "simultaneously)",
        "sequence_number": "1 byte appended before FCS; increments per VL "
                           "frame; wraps 255→1 (0 reserved)",
        "first_valid_wins": "receiver delivers the first valid copy of a "
                            "given Sequence Number; discards the duplicate",
    }
    d["frame_timing"] = {
        "base": "IEEE 802.3 full-duplex; no inter-frame collisions",
        "link_rates_Mbps": [10, 100],
        "shaping": "transmit shaping to BAG + jitter; switch ingress policing "
                   "(token/leaky-bucket)",
    }
    d["general_timing_rule"] = (
        "AFDX timing is deterministic and budgeted offline: each VL emits at "
        "most one frame per BAG (within the jitter bound); switches add "
        "bounded store-and-forward latency; the network is dimensioned so "
        "worst-case end-to-end latency is bounded for every VL. The redundant "
        "A/B copies are reconciled by Sequence-Number Integrity Checking and "
        "first-valid-wins Redundancy Management.")
    _write(p, d)


# ----------------------------------------------------------------------
# L9 — overwrite Ethernet integration spec with AFDX End-System / Switch
# integration model.
# ----------------------------------------------------------------------
def _l9(gd: Path) -> None:
    p = gd / "L9_INTEGRATION_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["module_role"] = (
        "Deterministic, redundant avionics network interface (AFDX / ARINC "
        "664 Part 7). An End System connects an LRU to two independent "
        "IEEE 802.3 networks (A/B), shapes each Virtual Link to its BAG + "
        "jitter, replicates frames with a Sequence Number, and on receive "
        "runs per-network Integrity Checking + first-valid-wins Redundancy "
        "Management; AFDX Switches forward by VL ID and police each VL.")
    d["topology_description"] = (
        "Switched star duplicated as Network A and Network B: End Systems "
        "attach by point-to-point full-duplex links to AFDX Switches; Virtual "
        "Links define unidirectional source→destination(s) paths over the "
        "fabric. UDP/IP rides over the VL.")
    io = _ensure_dict(d, "integration_overview")
    io.update({
        "spec": "ARINC 664 Part 7 (AFDX)",
        "base_technology": "IEEE 802.3 full-duplex switched Ethernet",
        "link_rates_Mbps": [10, 100],
        "vl_id_bits": _VL_ID_BITS,
        "vl_id_in_dest_mac": True,
        "sequence_number_bits": _SN_BITS,
        "bag_values_ms": list(_BAG_MS),
        "max_sub_vl": _MAX_SUB_VL,
        "max_jitter_us": _MAX_JITTER_US,
        "redundant_networks": ["Network A", "Network B"],
        "redundancy_management": "first-valid-wins (per-VL enable)",
        "integrity_checking": "per-network Sequence-Number window",
        "transport": "UDP/IP (IPv4, fragmentation) over the VL",
        "communication_ports": ["sampling", "queuing"],
        "components": ["End System", "AFDX Switch"],
        "host_side_register_spec": "Static per-VL configuration tables (VL "
        "ID, BAG, Lmax/Lmin, Sub-VL count, source/destination ES, switch "
        "forwarding + policing, RM enable) plus run-time status counters.",
    })
    d["interface_categories"] = [
        "End System host/application interface — sampling and queuing "
        "communication ports (UDP/IP).",
        "Network A Ethernet port — full-duplex IEEE 802.3 link to Network A.",
        "Network B Ethernet port — full-duplex IEEE 802.3 link to Network B.",
        "AFDX Switch ports — full-duplex point-to-point links with per-VL "
        "policing and static VL-ID forwarding.",
    ]
    d["interconnect_topologies_supported"] = [
        "Single End System to switch (point-to-point full-duplex).",
        "Multi-switch deterministic switched fabric.",
        "Dual fabric: Network A and Network B fully independent.",
        "Virtual Link multicast (one source ES → multiple destination ES).",
    ]
    d["soc_dependent_items"] = [
        "Number of Virtual Links and their BAG / Lmax / Sub-VL allocation.",
        "Static switch forwarding tables (VL ID → output ports) and policing "
        "parameters.",
        "Communication-port map (sampling/queuing, UDP ports, VL binding).",
        "Per-VL Redundancy-Management enable.",
        "Ethernet PHY selection (100BASE-TX / 10BASE-T) for both network "
        "ports.",
        "Offline timing/bandwidth budget for certification.",
    ]
    d["device_classes_examples"] = [
        "Avionics End System (LRU network interface)",
        "AFDX Switch (deterministic store-and-forward)",
        "Flight-control / display / sensor LRUs on the AFDX backbone",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L10 — overwrite Ethernet compliance categories with AFDX categories.
# ----------------------------------------------------------------------
def _l10(gd: Path) -> None:
    p = gd / "L10_TEST_CASES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_cases_present"] = (
        "partial — ARINC 664 Part 7 defines deterministic behaviors (VL "
        "shaping, redundancy management, integrity checking, policing) that "
        "map to a conformance/verification plan; the network is statically "
        "budgeted offline for certification.")
    d["derived_compliance_test_categories"] = [
        "Full-duplex switched Ethernet base: point-to-point, no collisions, "
        "no CSMA/CD.",
        "Virtual Link forwarding: VL ID (16-bit) in the destination MAC; "
        "switch forwards by VL ID via static table.",
        "Sub-VL round-robin: up to 4 Sub-VL FIFOs multiplexed into the parent "
        "VL shaper; share the parent BAG.",
        "BAG shaping: minimum inter-frame interval per VL = BAG ∈ "
        "{1,2,4,8,16,32,64,128} ms; max rate = 1/BAG.",
        "Jitter bound at End System output (≤ 500 µs).",
        "Traffic policing at switch: drop frames from an over-rate VL "
        "(token/leaky-bucket on BAG/Lmax).",
        "Dual-network redundancy: every frame replicated on Network A and "
        "Network B.",
        "Sequence Number: 1-byte SN appended before FCS; increments per VL; "
        "wraps 255→1 (0 reserved).",
        "Integrity Checking: per-network SN-window acceptance/rejection.",
        "Redundancy Management: first-valid-wins merge; duplicate discarded; "
        "per-VL enable/disable.",
        "Single-network-failure tolerance: lose Network A or B, traffic "
        "survives transparently.",
        "UDP/IP over VL: IPv4 fragmentation/reassembly for messages > Lmax.",
        "Sampling port: overwriting single message with freshness/validity "
        "timeout.",
        "Queuing port: FIFO lossless delivery in order.",
        "Frame format: dest MAC = 0x03:00:00:00 + VL ID; payload "
        "17..1471 bytes; SN before FCS; CRC-32 FCS.",
        "Static offline configuration: certifiable bounded latency / "
        "bandwidth.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L11 — overwrite Ethernet OTP-equivalent fields with AFDX static-config
# identity fields.
# ----------------------------------------------------------------------
def _l11(gd: Path) -> None:
    p = gd / "L11_OTP_CONTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    d["otp_present"] = False
    d["otp_equivalent_factory_burned_fields"] = [
        {"field": "End System / equipment identifier",
         "width_bits": "implementation-defined",
         "location": "source MAC address field",
         "note": "Identifies the transmitting End System on the network."},
        {"field": "VL configuration set", "width_bits": "table",
         "location": "static offline configuration loaded into the ES/switch",
         "note": "Per-VL VL ID, BAG, Lmax/Lmin, Sub-VL count, "
                 "source/destination ES, RM enable."},
        {"field": "Switch forwarding/policing table", "width_bits": "table",
         "location": "static offline configuration loaded into the switch",
         "note": "VL ID → output ports and per-VL policing parameters."},
    ]
    d["notes"] = (
        "AFDX has no OTP/fuse concept in the protocol; the "
        "interoperability-relevant facts are the statically-configured, "
        "offline-loaded Virtual Link and switch tables (VL ID, BAG, Lmax, "
        "Sub-VL count, forwarding, policing, RM enable). An implementation "
        "may back the equipment identifier or config with non-volatile "
        "storage, but the spec only requires the configuration be loaded and "
        "consistent across End Systems and switches.")
    _write(p, d)


# ----------------------------------------------------------------------
# L12 — overwrite Ethernet sequences with AFDX TX/RX/redundancy/policing
# sequences.
# ----------------------------------------------------------------------
def _l12(gd: Path) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["transmit_sequence"] = [
        "1. Application writes a message to a communication port (sampling "
        "overwrite or queuing enqueue).",
        "2. The message is placed into the appropriate Sub-VL FIFO of its "
        "Virtual Link.",
        "3. The VL shaper round-robins across up to 4 Sub-VL FIFOs to select "
        "the next frame.",
        "4. The shaper gates on the Bandwidth Allocation Gap: it waits until "
        "≥ BAG since the previous frame on this VL (within the jitter bound).",
        "5. The End System appends the 1-byte Sequence Number (incrementing "
        "per VL; wrap 255→1, 0 reserved).",
        "6. The frame is replicated and transmitted on BOTH Network A and "
        "Network B.",
    ]
    d["receive_redundancy_sequence"] = [
        "1. A frame arrives on Network A and/or Network B; Ethernet FCS is "
        "checked on each.",
        "2. Integrity Checking (per network): the Sequence Number is verified "
        "to be within the expected window for the VL; out-of-range frames are "
        "rejected.",
        "3. Redundancy Management merges the two streams first-valid-wins: the "
        "first valid copy of a given Sequence Number is accepted; the "
        "duplicate (same SN from the other network) is discarded.",
        "4. The accepted payload is delivered to the destination "
        "communication port (sampling overwrite + freshness, or queuing "
        "enqueue).",
    ]
    d["switch_forwarding_sequence"] = [
        "1. A frame arrives at an AFDX Switch ingress port; FCS checked.",
        "2. The switch polices the frame's VL against its configured BAG/Lmax "
        "(token/leaky-bucket); a non-conformant frame is dropped.",
        "3. The switch looks up the VL ID in its static forwarding table to "
        "get the output-port set.",
        "4. The frame is store-and-forwarded to each output port (multicast "
        "to the VL's destinations).",
    ]
    d["redundancy_failure_sequence"] = [
        "1. One network (A or B) fails (cut cable / failed switch / port).",
        "2. Frames continue to arrive on the surviving network.",
        "3. Integrity Checking + Redundancy Management deliver the surviving "
        "copy; the application sees no loss (transparent redundancy).",
    ]
    d["reset_sequence"] = [
        "1. Reset asserted; End System holds transmission.",
        "2. Reset deasserted: per-VL Sequence Numbers initialized (reset/"
        "first-frame convention), both Network A/B Ethernet links brought up, "
        "switch static tables loaded.",
        "3. BAG-shaped transmission resumes.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L13 — overwrite Ethernet lab targets with AFDX characterization targets.
# ----------------------------------------------------------------------
def _l13(gd: Path) -> None:
    p = gd / "L13_LAB_CALIBRATION.json"
    if not p.is_file():
        return
    d = _read(p)
    d["lab_calibration_present"] = False
    d["lab_measurement_targets_from_spec"] = [
        {"name": "BAG conformance", "purpose": "Verify the inter-frame "
         "interval on each VL is ≥ its BAG (1..128 ms) within the jitter "
         "bound."},
        {"name": "Jitter bound", "purpose": "Confirm End-System output jitter "
         "≤ the allocated bound (e.g. ≤ 500 µs)."},
        {"name": "Policing", "purpose": "Inject an over-rate VL and confirm "
         "the switch drops non-conformant frames."},
        {"name": "Redundancy (A/B)", "purpose": "Confirm every frame appears "
         "on both networks and that first-valid-wins delivers one copy."},
        {"name": "Sequence-Number / Integrity Checking", "purpose": "Inject "
         "out-of-window Sequence Numbers and confirm per-network rejection."},
        {"name": "Single-network-failure", "purpose": "Disconnect one network "
         "and confirm transparent continued delivery."},
        {"name": "Bounded end-to-end latency", "purpose": "Confirm worst-case "
         "VL latency stays within the offline budget."},
    ]
    d["notes"] = (
        "AFDX characterization verifies the deterministic contract — BAG, "
        "jitter, policing, bounded latency — and the redundancy contract — "
        "dual-network delivery, Integrity Checking, first-valid-wins "
        "Redundancy Management. Because the network is statically configured "
        "offline, expected timing/bandwidth are deterministic and "
        "certifiable.")
    _write(p, d)


# ----------------------------------------------------------------------
# L14 — overwrite Ethernet versioning with AFDX / ARINC 664 versioning.
# ----------------------------------------------------------------------
def _l14(gd: Path) -> None:
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["spec_version"] = (
        "ARINC Specification 664 Part 7 — Aircraft Data Network, Part 7: "
        "Avionics Full-Duplex Switched Ethernet (AFDX) Network")
    f["base_standard"] = "IEEE 802.3 full-duplex switched Ethernet"
    f["related_standards"] = [
        "ARINC 664 (Aircraft Data Network) — the multi-part family; Part 7 "
        "specifies AFDX.",
        "IEEE 802.3 — the underlying Ethernet base.",
        "ARINC 429 (Mark 33 DITS) — the legacy point-to-point avionics bus "
        "that AFDX largely supersedes for high-bandwidth data.",
    ]
    f["key_changes"] = [
        {"version": "ARINC 664 Part 7", "summary": "Defines AFDX: "
         "deterministic profiled IEEE 802.3 switched Ethernet adding Virtual "
         "Links (16-bit VL ID in the dest MAC, Sub-VLs), Bandwidth Allocation "
         "Gap (1..128 ms) with bounded jitter and traffic shaping/policing, "
         "dual-network (A/B) redundancy with a 1-byte Sequence Number, "
         "per-network Integrity Checking and first-valid-wins Redundancy "
         "Management, End Systems and AFDX Switches, and UDP/IP over the VL "
         "with sampling/queuing ports."},
    ]
    f["backward_compat_traps"] = [
        {"trap_name": "VL_ID_is_in_the_dest_MAC",
         "rule": "The 16-bit Virtual Link Identifier is carried in the lower "
                 "16 bits of the destination MAC (constant 0x03:00:00:00 + "
                 "VL ID); switches forward on VL ID, not on learned MACs.",
         "trap": "Treating AFDX like learning/spanning-tree Ethernet is "
                 "wrong — forwarding is static, VL-ID based."},
        {"trap_name": "BAG_is_power_of_two_1_to_128_ms",
         "rule": "BAG ∈ {1,2,4,8,16,32,64,128} ms.",
         "trap": "Arbitrary inter-frame intervals are not allowed; the BAG "
                 "must be a power of two in 1..128 ms."},
        {"trap_name": "Sub_VLs_share_the_parent_BAG",
         "rule": "Sub-VLs round-robin into the parent VL shaper and share its "
                 "BAG; they do not appear on the wire.",
         "trap": "Assuming each Sub-VL has its own BAG over-allocates "
                 "bandwidth."},
        {"trap_name": "Sequence_Number_is_one_byte_wrapping_255_to_1",
         "rule": "The redundancy Sequence Number is 1 byte, range 1..255 "
                 "(0 reserved for reset/first frame).",
         "trap": "Using a wider SN or wrapping through 0 breaks Integrity "
                 "Checking / Redundancy Management."},
        {"trap_name": "Redundancy_is_first_valid_wins",
         "rule": "Both networks carry every frame; the receiver delivers the "
                 "first valid copy and discards the duplicate.",
         "trap": "Expecting retransmission (TCP-style) is wrong — AFDX uses "
                 "spatial redundancy + UDP, not retransmission."},
    ]
    f["version_naming_history_note"] = (
        "AFDX is the trademarked Airbus implementation of the ARINC 664 "
        "Part 7 standard (Aircraft Data Network, Part 7), itself a "
        "deterministic profile of IEEE 802.3 Ethernet. It is the avionics "
        "backbone of aircraft such as the Airbus A380/A350 and Boeing 787. "
        "Facts here are grounded in the ARINC 664 Part 7 specification "
        "structure (Virtual Links, BAG, redundancy management, End Systems "
        "and switches, UDP/IP).")
    _write(p, d)


# ----------------------------------------------------------------------
# L15 — overwrite Ethernet encoding tables with AFDX BAG / frame / VL /
# redundancy tables.
# ----------------------------------------------------------------------
def _l15(gd: Path) -> None:
    p = gd / "L15_ENCODING_TABLES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["bag_table"] = {
        "header_columns": ["k", "BAG (ms)", "Max frame rate (frames/s)"],
        "rows": [
            ["0", "1", "1000"],
            ["1", "2", "500"],
            ["2", "4", "250"],
            ["3", "8", "125"],
            ["4", "16", "62.5"],
            ["5", "32", "31.25"],
            ["6", "64", "15.625"],
            ["7", "128", "7.8125"],
        ],
    }
    f["frame_format_table"] = {
        "header_columns": ["Field", "Bytes", "Note"],
        "rows": [
            ["Destination MAC", "6", "0x03:00:00:00 (const) + 16-bit VL ID"],
            ["Source MAC", "6", "const + source End System identifier"],
            ["EtherType", "2", "IP = 0x0800"],
            ["IP + UDP + AFDX payload", "variable",
             "AFDX payload 17..1471 bytes"],
            ["Sequence Number", "1", "1..255 (0 reserved), before FCS"],
            ["FCS", "4", "Ethernet CRC-32"],
        ],
    }
    f["virtual_link_table"] = {
        "header_columns": ["Property", "Value"],
        "rows": [
            ["VL ID width", "16 bits"],
            ["VL ID location", "destination MAC (lower 16 bits)"],
            ["Direction", "unidirectional (1 source → 1+ destinations)"],
            ["Sub-VLs per VL", "up to 4 (round-robin, share parent BAG)"],
            ["Forwarding", "static VL-ID table (no learning, no STP)"],
        ],
    }
    f["redundancy_table"] = {
        "header_columns": ["Property", "Value"],
        "rows": [
            ["Networks", "Network A + Network B (independent)"],
            ["Replication", "every frame on both networks"],
            ["Sequence Number", "1 byte, 1..255 (0 reserved)"],
            ["Integrity Checking", "per-network SN-window"],
            ["Redundancy Management", "first-valid-wins; per-VL enable"],
        ],
    }
    f["communication_port_table"] = {
        "header_columns": ["Port type", "Semantics"],
        "rows": [
            ["Sampling", "single overwriting message + freshness/validity "
             "timeout"],
            ["Queuing", "FIFO, lossless, in-order"],
        ],
    }
    f["tables"] = [
        "BAG table (1..128 ms power of two → max frame rate)",
        "AFDX frame-format table (dest MAC + VL ID, SN before FCS)",
        "Virtual Link table (VL ID, Sub-VLs, static forwarding)",
        "Redundancy table (Network A/B, SN, IC, RM)",
        "Communication-port table (sampling / queuing)",
    ]
    f["encoding_note"] = (
        "AFDX uses the standard IEEE 802.3 line encoding of the underlying "
        "PHY (e.g. MLT-3 / 4B5B for 100BASE-TX). The AFDX-specific 'encoding' "
        "is structural: the VL ID embedded in the destination MAC, the 1-byte "
        "Sequence Number before the FCS, and the BAG-based traffic shaping — "
        "not a special line code.")
    _write(p, d)


# ----------------------------------------------------------------------
# L16 — overwrite Ethernet compliance properties with AFDX ones.
# ----------------------------------------------------------------------
def _l16(gd: Path) -> None:
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["must_have_properties"] = [
        "IEEE 802.3 full-duplex switched Ethernet base (point-to-point, no "
        "collisions, no CSMA/CD).",
        "Virtual Links: 16-bit VL ID in the destination MAC; unidirectional "
        "source→destination(s); up to 4 Sub-VLs.",
        "Bandwidth Allocation Gap per VL: power of two 1..128 ms; max "
        "bandwidth = Lmax/BAG.",
        "Bounded jitter at the End System output; transmit traffic shaping.",
        "AFDX Switch traffic policing per VL (drop non-conformant frames).",
        "Dual independent networks (A/B) with per-frame replication.",
        "1-byte Sequence Number with per-network Integrity Checking and "
        "first-valid-wins Redundancy Management.",
        "Deterministic store-and-forward switching by VL ID with static "
        "configuration.",
        "UDP/IP over the VL with sampling and queuing communication ports.",
    ]
    f["must_not_have_properties"] = [
        "CSMA/CD or a shared/half-duplex medium (AFDX is full-duplex "
        "switched).",
        "Dynamic MAC learning or spanning tree (forwarding is static, VL-ID "
        "based).",
        "Arbitrary (non power-of-two, out-of-range) BAG values.",
        "A Sequence Number wider than 1 byte or wrapping through 0.",
        "TCP-style retransmission for reliability (AFDX uses spatial "
        "redundancy + UDP).",
        "Per-Sub-VL BAG (Sub-VLs share the parent VL's BAG).",
    ]
    f["afdx_distinguishers"] = (
        "AFDX (ARINC 664 Part 7) is identified by ALL of: a deterministic "
        "profiled IEEE 802.3 full-duplex switched Ethernet base; Virtual "
        "Links with a 16-bit VL ID carried in the destination MAC (and "
        "Sub-VLs); the Bandwidth Allocation Gap (power-of-two 1..128 ms) with "
        "bounded jitter and traffic shaping/policing; dual-network (A/B) "
        "redundancy with a 1-byte Sequence Number, per-network Integrity "
        "Checking, and first-valid-wins Redundancy Management; End Systems and "
        "AFDX Switches; and UDP/IP over the VL with sampling/queuing ports. "
        "This is distinct from plain IEEE 802.3 Ethernet (best-effort, "
        "learning/STP, no VL/BAG/redundancy), ARINC 429 (32-bit-word "
        "point-to-point avionics bus), and PROFINET (IO-Controller / GSDML / "
        "IRT industrial Ethernet).")
    f["min_link_constraint"] = (
        "An AFDX link must operate as full-duplex switched Ethernet carrying "
        "BAG-shaped, Sequence-Numbered Virtual-Link frames on at least one of "
        "Network A / Network B, with the receiver performing Integrity "
        "Checking and (if RM enabled) first-valid-wins Redundancy "
        "Management.")
    _write(p, d)


# ----------------------------------------------------------------------
# L17 — overwrite Ethernet channels with AFDX network-port / VL channels.
# ----------------------------------------------------------------------
def _l17(gd: Path) -> None:
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["channels"] = [
        {"name": "Network A port",
         "direction": "full-duplex (TX + RX)",
         "purpose": "IEEE 802.3 link to Network A; carries one copy of every "
                    "frame.",
         "active_levels": "100BASE-TX / 10BASE-T differential",
         "idle_level": "Ethernet idle"},
        {"name": "Network B port",
         "direction": "full-duplex (TX + RX)",
         "purpose": "Independent IEEE 802.3 link to Network B; carries the "
                    "redundant copy.",
         "active_levels": "100BASE-TX / 10BASE-T differential",
         "idle_level": "Ethernet idle"},
        {"name": "Host / application interface",
         "direction": "bidirectional",
         "purpose": "Sampling and queuing communication ports (UDP/IP) to the "
                    "avionics application.",
         "active_levels": "n/a (logical)", "idle_level": "n/a"},
    ]
    f["logical_signaling_levels"] = [
        {"name": "Virtual Link frame", "meaning": "Standard Ethernet frame "
         "with VL ID in the dest MAC and a 1-byte Sequence Number before "
         "the FCS."},
        {"name": "Replicated A/B", "meaning": "The same frame transmitted on "
         "both Network A and Network B."},
    ]
    f["packet_types_summary"] = [
        {"class": "Virtual Link frame",
         "members": ["sampling-port message", "queuing-port message"],
         "count": 2},
    ]
    cc = _ensure_dict(f, "channel_counts")
    cc.update({
        "network_ports": 2,
        "redundant_networks": 2,
        "vl_id_bits": _VL_ID_BITS,
        "sequence_number_bits": _SN_BITS,
        "max_sub_vl_per_vl": _MAX_SUB_VL,
        "bag_value_count": len(_BAG_MS),
    })
    f["global_signals"] = [
        {"name": "Network A", "purpose": "Independent redundant network A."},
        {"name": "Network B", "purpose": "Independent redundant network B."},
        {"name": "RESET", "purpose": "End System / switch reset."},
    ]
    f["dependency_graph"] = {
        "common_rule": "Every VL frame is replicated onto Network A and "
        "Network B; the receiver reconciles them by Sequence-Number Integrity "
        "Checking + first-valid-wins Redundancy Management.",
        "data_dependency": "Transmission requires the VL shaper to satisfy "
        "the BAG (within jitter); delivery requires a valid Sequence Number "
        "passing Integrity Checking on at least one network.",
    }
    f["handshake_pairs"] = [
        {"name": "Replicate-A/B", "from": "End System TX",
         "to": "Network A + Network B", "rule": "send every frame on both "
         "networks."},
        {"name": "IC+RM", "from": "Network A/B RX", "to": "application port",
         "rule": "per-network Integrity Check then first-valid-wins "
         "Redundancy Management."},
        {"name": "Police", "from": "switch ingress", "to": "switch egress",
         "rule": "drop frames from a VL exceeding its BAG/Lmax."},
        {"name": "VL-forward", "from": "switch", "to": "output ports",
         "rule": "static VL-ID lookup → output-port set (multicast)."},
    ]
    f["ordering_rules"] = {
        "frame_order": "Frames on a VL carry an incrementing Sequence Number; "
        "ordering/duplicate-suppression is by SN.",
        "tx_rx_simultaneity": "Full-duplex; A and B carry the same frame "
        "near-simultaneously.",
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L18 — overwrite Ethernet topology with AFDX dual-fabric switched topology.
# ----------------------------------------------------------------------
def _l18(gd: Path) -> None:
    p = gd / "L18_INTERCONNECT_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["topology_type"] = (
        "Deterministic full-duplex switched Ethernet star, duplicated as two "
        "physically independent networks (Network A and Network B). End "
        "Systems attach to AFDX Switches by point-to-point full-duplex links; "
        "Virtual Links define unidirectional source→destination(s) paths over "
        "the fabric.")
    f["supported_topologies"] = [
        {"name": "Point-to-point ES↔switch", "description": "Full-duplex "
         "10/100 Mbit/s link between an End System and an AFDX Switch."},
        {"name": "Multi-switch fabric", "description": "AFDX Switches "
         "interconnect into a deterministic switched fabric."},
        {"name": "Dual redundant fabric", "description": "Network A and "
         "Network B are fully independent (separate switches and cabling)."},
        {"name": "Virtual Link multicast", "description": "One source End "
         "System to one or more destination End Systems over a VL."},
    ]
    f["master_slave_role_summary"] = [
        {"role": "End System", "description": "Avionics network interface: "
         "VL shaping (BAG/jitter), Sub-VL round-robin, Sequence-Number "
         "insertion, A/B replication, receive IC + RM."},
        {"role": "AFDX Switch", "description": "Deterministic "
         "store-and-forward: VL-ID forwarding (static), per-VL policing, "
         "full-duplex links."},
        {"role": "Virtual Link", "description": "Unidirectional logical "
         "connection identified by a 16-bit VL ID in the dest MAC."},
    ]
    f["interconnect_role"] = (
        "AFDX is a deterministic, redundant avionics network. Switches "
        "forward by VL ID and police each VL; End Systems shape to the BAG "
        "and reconcile the redundant A/B copies. Worst-case latency and "
        "bandwidth are bounded by offline configuration for certification.")
    f["ordering_guarantees"] = {
        "vl_sequence": "Frames on a VL carry an incrementing Sequence Number "
        "used for Integrity Checking and duplicate suppression.",
        "redundancy": "First-valid-wins delivery makes A/B redundancy "
        "transparent to the application.",
    }
    f["memory_vs_peripheral_regions"] = (
        "Not memory-mapped: AFDX is a network. Addressing is the Virtual Link "
        "Identifier (in the dest MAC) plus UDP/IP ports identifying "
        "communication ports within an End System.")
    dc = _ensure_dict(f, "device_classification")
    dc["end_system"] = ("Avionics LRU network interface performing VL "
                        "shaping, redundancy, and integrity checking.")
    dc["afdx_switch"] = ("Deterministic store-and-forward switch forwarding "
                         "by VL ID and policing each VL.")
    f["default_signal_values_evidence_tables"] = [
        "ARINC 664 Part 7 Virtual Link / BAG / redundancy definitions",
        "AFDX frame format (dest MAC = const + VL ID; SN before FCS)",
        "Dual-network (A/B) redundancy management + integrity checking",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L19 — overwrite Ethernet channel constraints with AFDX deterministic
# network constraints.
# ----------------------------------------------------------------------
def _l19(gd: Path) -> None:
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["constraints_present"] = True
    f["network_constraints"] = {
        "base_technology": "IEEE 802.3 full-duplex switched Ethernet",
        "link_rates_Mbps": [10, 100],
        "duplex": "full-duplex point-to-point (no CSMA/CD)",
        "vl_id_bits": _VL_ID_BITS,
        "bag_values_ms": list(_BAG_MS),
        "bag_rule": "power of two 1..128 ms",
        "max_sub_vl": _MAX_SUB_VL,
        "max_jitter_us": _MAX_JITTER_US,
        "afdx_payload_bytes": {"min": _AFDX_PAYLOAD_MIN,
                               "max": _AFDX_PAYLOAD_MAX},
        "ethernet_frame_bytes": {"min": 64, "max": 1518},
        "sequence_number_bits": _SN_BITS,
        "redundant_networks": 2,
        "max_bandwidth_per_vl": "Lmax / BAG",
    }
    f["notes"] = (
        "AFDX is a network specification (ARINC 664 Part 7), not a silicon "
        "PDK. Its binding constraints are the deterministic contract — BAG "
        "(power-of-two 1..128 ms), bounded jitter (≤ 500 µs), Lmax/BAG "
        "bandwidth, bounded store-and-forward latency — and the redundancy "
        "contract (dual independent networks, 1-byte Sequence Number, "
        "Integrity Checking, first-valid-wins Redundancy Management). "
        "Floorplan/PDK constraints belong to the implementing ASIC/FPGA "
        "End-System or switch silicon, not to the AFDX standard.")
    _write(p, d)


# ----------------------------------------------------------------------
# L20 — overwrite Ethernet DFT with AFDX counter/observability DFT.
# ----------------------------------------------------------------------
def _l20(gd: Path) -> None:
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["dft_present"] = "partial"
    f["in_band_test_facilities"] = [
        {"name": "Per-VL Integrity-Check / Redundancy-Management counters",
         "purpose": "Observe per-network accept/reject and duplicate-discard "
                    "counts."},
        {"name": "Per-VL policing counters (switch)",
         "purpose": "Observe dropped frames from over-rate VLs."},
        {"name": "Sequence-Number state", "purpose": "Observe per-VL "
         "transmit/receive Sequence Numbers."},
        {"name": "Communication-port status", "purpose": "Sampling-port "
         "freshness and queuing-port occupancy/overflow."},
        {"name": "Link status (A/B)", "purpose": "Up/down status of each "
         "redundant network port."},
    ]
    f["internal_diagnostics_observability"] = [
        "VL shaper / BAG timer state.",
        "Per-network Integrity-Check pass/reject counters.",
        "Redundancy-Management duplicate-discard counter.",
        "Switch per-VL policing drop counter.",
        "Sampling/queuing port freshness / occupancy.",
    ]
    f["notes"] = (
        "AFDX's protocol-level test surface is its run-time counters "
        "(per-VL Integrity Checking, Redundancy Management, policing) and "
        "communication-port status, plus per-network link status. Chip-level "
        "JTAG/scan/BIST remain implementation concerns of the End-System / "
        "switch silicon.")
    _write(p, d)


# ----------------------------------------------------------------------
# L21 — overwrite Ethernet power with AFDX (network-level) power notes.
# ----------------------------------------------------------------------
def _l21(gd: Path) -> None:
    p = gd / "L21_POWER_INTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["power_intent_present"] = True
    f["power_domains"] = [
        {"domain": "Network A port", "purpose": "PHY/MAC for the Network A "
         "Ethernet link."},
        {"domain": "Network B port", "purpose": "Independent PHY/MAC for the "
         "Network B Ethernet link (redundancy isolation)."},
        {"domain": "End System core", "purpose": "VL shaping, redundancy "
         "management, integrity checking, communication ports."},
    ]
    f["notes"] = (
        "AFDX is a network standard; it does not define silicon power states. "
        "For fault containment the two redundant network ports (A and B) are "
        "kept independent so a fault in one does not bring down the other. "
        "Power management of the implementing End-System / switch silicon is "
        "an implementation concern (e.g. always-on for safety-critical "
        "avionics).")
    _write(p, d)


# ----------------------------------------------------------------------
# L22 — overwrite Ethernet verification categories with AFDX ones.
# ----------------------------------------------------------------------
def _l22(gd: Path) -> None:
    p = gd / "L22_VERIFICATION_PLAN.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["verification_plan_present"] = "implicit"
    f["verification_categories_derived_from_spec"] = [
        "Full-duplex switched Ethernet base (no CSMA/CD).",
        "VL forwarding by 16-bit VL ID (static switch table).",
        "Sub-VL round-robin (up to 4) sharing the parent BAG.",
        "BAG shaping (power-of-two 1..128 ms) and max rate = 1/BAG.",
        "Jitter bound (≤ 500 µs) at the End System output.",
        "Traffic policing at the switch (drop over-rate VL frames).",
        "Dual-network (A/B) replication of every frame.",
        "1-byte Sequence Number; per-network Integrity Checking.",
        "First-valid-wins Redundancy Management; per-VL enable.",
        "Single-network-failure tolerance (transparent to application).",
        "UDP/IP over VL; IPv4 fragmentation for messages > Lmax.",
        "Sampling ports (overwrite + freshness) and queuing ports (FIFO "
        "lossless).",
        "Frame format (dest MAC const + VL ID; SN before FCS; CRC-32 FCS; "
        "payload 17..1471 bytes).",
        "Bounded end-to-end latency from offline budgeting.",
    ]
    f["notes"] = (
        "ARINC 664 Part 7 does not ship a single testbench, but the standard "
        "implies a verification plan spanning the deterministic contract (VL "
        "shaping, BAG, jitter, policing, bounded latency) and the redundancy "
        "contract (dual networks, Sequence Number, Integrity Checking, "
        "first-valid-wins Redundancy Management), plus the End-System "
        "communication ports and the AFDX-Switch forwarding/policing.")
    _write(p, d)


# ----------------------------------------------------------------------
# L23 — overwrite Ethernet security with AFDX integrity/redundancy + pointers.
# ----------------------------------------------------------------------
def _l23(gd: Path) -> None:
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["security_requirements_present"] = False
    f["anti_corruption_features"] = [
        "Ethernet FCS (CRC-32) detects bit errors on each network.",
        "Per-network Integrity Checking rejects out-of-window Sequence "
        "Numbers.",
        "First-valid-wins Redundancy Management tolerates loss/corruption on "
        "one whole network.",
        "Traffic policing at the switch isolates a babbling / over-rate VL so "
        "it cannot starve other VLs.",
        "Static offline configuration bounds the traffic and prevents "
        "unplanned flows.",
    ]
    f["anti_tampering_features"] = []
    f["confidentiality_features"] = []
    f["authentication_features"] = []
    f["future_security_pointers"] = [
        "AFDX provides determinism + fault tolerance, not cryptography; the "
        "data is plaintext on the (physically protected) aircraft network.",
        "Higher-layer avionics security (e.g. ARINC 664 Part 5 / domain "
        "segregation, application-level authentication) is layered above "
        "AFDX where required.",
        "Network segregation and the closed, statically-configured nature of "
        "the avionics fabric are the primary security posture.",
    ]
    f["notes"] = (
        "AFDX's built-in protections are anti-corruption and fault-tolerance "
        "(FCS, per-network Integrity Checking, first-valid-wins Redundancy "
        "Management, traffic policing, static configuration), not "
        "cryptographic confidentiality/integrity/authentication. The closed, "
        "physically-protected, statically-configured avionics network is the "
        "security context; cryptographic protection, where required, is "
        "provided by higher layers above AFDX.")
    _write(p, d)
