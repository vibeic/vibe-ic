"""Zigbee / IEEE 802.15.4 low-power wireless PAN protocol synth helper.

v0.1.91 — ic_class-gated overlay for a `serial_peripheral_protocol`-shaped
(extended to wireless PAN) spec that exhibits the IEEE 802.15.4 + Zigbee
structural signature. Applies IEEE Std 802.15.4 (PHY + MAC) and Zigbee
(NWK + APS + ZDO + ZCL; Connectivity Standards Alliance) spec-canonical
content to L1-L23.

Doctrine — GENERAL not keyword: detection (``is_zigbee`` below) keys on the
canonical STRUCTURAL signature of an 802.15.4 / Zigbee LR-WPAN read from the
L-doc / input-doc CONTENT blob only. It NEVER reads the input-document
filename or the benchmark folder name. The structural signature is:

  * IEEE 802.15.4 PHY/MAC tokens: O-QPSK + DSSS spreading, 2.4 GHz with the
    16-channel (channel 11-26) plan, CSMA-CA channel access, the four MAC
    frame types (beacon / data / acknowledgement / MAC command), PAN ID,
    16-bit short + 64-bit extended (EUI-64) addresses, the beacon-enabled
    superframe with GTS (Guaranteed Time Slots), and FFD / RFD device types.
  * Zigbee NWK/APS/ZDO/ZCL tokens: mesh/tree/star topology, NWK routing,
    Zigbee Device Object (ZDO), Application Support sublayer (APS), clusters
    + Zigbee Cluster Library (ZCL), Coordinator / Router / End Device roles,
    AES-128-CCM* security with a network key + link key and a Trust Center.

Sibling disambiguation (content-only MUTEX):

  * vs BLE (Bluetooth Low Energy): BLE keys on GAP / GATT / ATT / advertising
    / connection-interval and 40 channels. 802.15.4/Zigbee has PAN ID +
    superframe/GTS + DSSS-O-QPSK + ZDO/APS/clusters/ZCL + mesh + FFD/RFD,
    none of which appear in a BLE spec. ``is_zigbee`` defers if the blob is
    BLE-primary (GAP+GATT+advertising, no 802.15.4/Zigbee superframe/PAN-ID
    structure).
  * vs NFC (ISO 14443): NFC keys on PCD/PICC, ATQA/SAK, 13.56 MHz, MIFARE,
    ISO 14443. None overlap the 802.15.4/Zigbee superframe/mesh/ZCL set.
  * vs LoRa / LoRaWAN: LoRa keys on chirp spread spectrum (CSS) / spreading
    factor / sub-GHz long-range / LoRaWAN. Disjoint from the 802.15.4 O-QPSK
    DSSS + superframe + Zigbee mesh structure; ``is_zigbee`` does not fire on
    a LoRa-primary doc (a parallel agent owns LoRa).

Public entry: ``apply_zigbee_synth(generated_docs_dir, is_zigbee, zigbee_ic_name)``.
Module-level detector: ``is_zigbee(blob: str) -> bool`` (content-only, word
boundaries where a short token could collide).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

import l_doc_generator_stamp as _stamp
import _pack_top_module as _ptm  # L9.top_module: one decision, one provenance stamp


# ----------------------------------------------------------------------
# Module-level CONTENT-ONLY detector (the runner wires this; evaluated on
# the L1/L2/L3 content blob, never on a filename / folder / benchmark name).
# ----------------------------------------------------------------------
def _wb(token: str, blob: str) -> bool:
    """Word-boundary token match (case-sensitive — these are canonical
    spelled-out names / acronyms)."""
    return re.search(r"(?<![A-Za-z0-9])" + re.escape(token) + r"(?![A-Za-z0-9])",
                     blob) is not None


def is_zigbee(blob: str) -> bool:
    """True iff the CONTENT blob carries the IEEE 802.15.4 + Zigbee LR-WPAN
    structural signature. CONTENT-ONLY, structural (never name-token alone),
    with a BLE / NFC / LoRa MUTEX.

    A bare "Zigbee" or "802.15.4" name token is NOT sufficient on its own:
    we require the structural wire-level signature so this generalises and
    does not over-fire on a passing mention.
    """
    if not blob:
        return False
    low = blob.lower()

    # ---- BLE-primary MUTEX: a BLE doc keys on GAP+GATT+advertising and the
    #      40-channel plan, and never carries the 802.15.4 superframe / PAN ID
    #      / DSSS-O-QPSK / Zigbee NWK structure. Defer to BLE. ----
    ble_primary = (
        ("GAP" in blob and "GATT" in blob and "advertising" in low)
        and not ("802.15.4" in blob or "PAN ID" in blob
                 or "superframe" in low or "O-QPSK" in blob)
    )
    if ble_primary:
        return False

    # ---- NFC-primary MUTEX: ISO 14443 PCD/PICC at 13.56 MHz is disjoint. ----
    nfc_primary = (
        ("PCD" in blob and "PICC" in blob)
        or ("ISO 14443" in blob and "13.56" in blob)
    ) and not ("802.15.4" in blob or "Zigbee" in blob or "superframe" in low)
    if nfc_primary:
        return False

    # ---- LoRa-primary MUTEX: chirp spread spectrum / spreading factor /
    #      LoRaWAN sub-GHz long-range is disjoint; defer to the LoRa agent. ----
    lora_primary = (
        ("LoRaWAN" in blob or "LoRa" in blob)
        and ("spreading factor" in low or "chirp" in low
             or "chirp spread spectrum" in low)
        and not ("802.15.4" in blob or "superframe" in low
                 or "PAN ID" in blob or "ZDO" in blob or "ZCL" in blob)
    )
    if lora_primary:
        return False

    # ---- 802.15.4 PHY/MAC structural signal ----
    phy = (
        ("O-QPSK" in blob and ("DSSS" in blob or "spread spectrum" in low))
        or ("DSSS" in blob and ("32-chip" in low or "32 chips" in low
                                or "chip rate" in low))
    )
    mac_frames = (
        "beacon" in low and "MAC command" in blob
        and ("acknowledgement" in low or "acknowledgment" in low)
    )
    csma = "CSMA-CA" in blob or "CSMA/CA" in blob
    superframe = "superframe" in low and (
        "GTS" in blob or "Guaranteed Time Slot" in blob
        or "CAP" in blob or "CFP" in blob)
    pan_addr = (
        "PAN ID" in blob
        and ("short address" in low or "extended address" in low
             or "EUI-64" in blob)
    )
    ffd_rfd = "FFD" in blob and "RFD" in blob
    ieee_name = "802.15.4" in blob

    mac_score = sum(bool(x) for x in
                    (mac_frames, csma, superframe, pan_addr, ffd_rfd))

    # ---- Zigbee NWK/APS/ZDO/ZCL structural signal ----
    zdo_aps = (
        ("ZDO" in blob or "Zigbee Device Object" in blob)
        and ("APS" in blob or "Application Support" in blob)
    )
    cluster = (
        ("ZCL" in blob or "Zigbee Cluster Library" in blob)
        or ("cluster" in low and "endpoint" in low and "binding" in low)
    )
    roles = (
        ("Coordinator" in blob and "Router" in blob and "End Device" in blob)
    )
    mesh = "mesh" in low and ("NWK" in blob or "routing" in low)
    sec = (
        ("AES-128" in blob and ("CCM*" in blob or "CCM star" in low))
        and ("network key" in low or "link key" in low or "Trust Center" in blob)
    )

    zigbee_score = sum(bool(x) for x in
                       (zdo_aps, cluster, roles, mesh, sec))

    # ---- Decision: require the 802.15.4 PHY signature AND a strong MAC
    #      structural score, OR the IEEE name plus a strong combined MAC+Zigbee
    #      structure. This is STRUCTURAL (never name token alone). ----
    if phy and mac_score >= 3:
        return True
    if ieee_name and mac_score >= 3 and zigbee_score >= 2:
        return True
    if mac_score >= 4 and zigbee_score >= 3:
        return True
    return False


# ----------------------------------------------------------------------
# JSON helpers (mirror ucie/ble synth helpers).
# ----------------------------------------------------------------------
def _empty(v) -> bool:
    return v in (None, {}, []) or (isinstance(v, str) and not v.strip())


def _ensure_dict(d: dict, key: str) -> dict:
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

# Canonical numeric facts (IEEE 802.15.4 + Zigbee).
_CHANNELS_24G = list(range(11, 27))            # 16 channels, ch 11..26
_DATA_RATE_KBPS = 250                           # 2.4 GHz O-QPSK
_CHIP_RATE_MCHIP = 2.0                          # 2 Mchip/s
_MAX_PHY_PACKET = 127                           # aMaxPHYPacketSize octets
_UNIT_BACKOFF = 20                              # aUnitBackoffPeriod symbols
_TURNAROUND = 12                                # aTurnaroundTime symbols
_BASE_SLOT = 60                                 # aBaseSlotDuration symbols
_NUM_SF_SLOTS = 16                              # aNumSuperframeSlots
_MAX_GTS = 7                                    # GTS per superframe
_SFD = "0xA7"                                   # 2.4 GHz O-QPSK SFD


def apply_zigbee_synth(generated_docs_dir: Path, is_zigbee: bool,
                       zigbee_ic_name: Optional[str]) -> None:
    """Apply IEEE 802.15.4 + Zigbee synth when the structural signature
    matched. Force-overwrites (direct assign) all canonical keys, since an
    earlier R53 universal serial-peripheral synth or a sibling synth may have
    seeded generic / sibling values (Zigbee runs last in the Tier chain)."""
    if not is_zigbee:
        return
    gd = Path(generated_docs_dir)

    # --- Force ic_name across ALL 24 docs first. ---
    if zigbee_ic_name is not None:
        for n in _MAIN_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                d["ic_name"] = zigbee_ic_name
                _write(q, d)
        for n in _FIELDS_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                f = _ensure_dict(d, "fields")
                f["ic_name"] = zigbee_ic_name
                d["ic_name"] = zigbee_ic_name
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
# L1 — DATASHEET
# ----------------------------------------------------------------------
def _l1(gd: Path) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    d["document_title"] = (
        "IEEE Std 802.15.4 LR-WPAN + Zigbee Specification")
    d["version"] = "IEEE 802.15.4 (2.4 GHz O-QPSK PHY) + Zigbee Pro / Zigbee 3.0"
    d["revised_date"] = "2024"
    d["manufacturer"] = (
        "IEEE 802.15 Working Group; Connectivity Standards Alliance (CSA)")
    d["copyright"] = (
        "© IEEE (802.15.4) and © Connectivity Standards Alliance (Zigbee)")
    d["abstract"] = (
        "A low-rate wireless personal area network (LR-WPAN) SoC built on IEEE "
        "Std 802.15.4 for the Physical and MAC layers and the Zigbee "
        "specification for the Network (NWK), Application Support (APS), Zigbee "
        "Device Object (ZDO) and Zigbee Cluster Library (ZCL) layers. The "
        "2.4 GHz PHY uses Offset-QPSK (O-QPSK) with half-sine pulse shaping "
        "over Direct Sequence Spread Spectrum (DSSS, 32 chips/symbol, "
        "2.0 Mchip/s) across 16 channels (channel 11-26), giving 250 kbps. The "
        "MAC provides CSMA-CA channel access, a beacon-enabled superframe with "
        "Guaranteed Time Slots (GTS), 16-bit PAN IDs, and 16-bit short plus "
        "64-bit extended (EUI-64) addresses, with Full-Function (FFD) and "
        "Reduced-Function (RFD) devices. Zigbee adds star/tree/mesh networking "
        "(Coordinator / Router / End Device roles), endpoint/cluster-based "
        "applications, and AES-128 CCM* security with a network key, link keys "
        "and a Trust Center.")
    d["keywords"] = [
        "IEEE 802.15.4", "Zigbee", "LR-WPAN", "O-QPSK", "DSSS",
        "CSMA-CA", "superframe", "GTS", "PAN ID", "EUI-64", "FFD", "RFD",
        "NWK", "APS", "ZDO", "ZCL", "mesh", "Coordinator", "Router",
        "End Device", "AES-128", "CCM*", "Trust Center", "2.4 GHz",
        "250 kbps", "channel 11-26",
    ]
    d["external_pins"] = [
        "RF_P / RF_N — differential 2.4 GHz RF port to the antenna balun/match",
        "RF_BIAS — RF bias",
        "XTAL_P / XTAL_N — reference crystal (16/32 MHz) for the synthesizer",
        "VDD_RF / VSS — RF supply and ground",
    ]
    d["external_pin_count"] = 7
    d["supported_channels_2g4"] = list(_CHANNELS_24G)
    d["channel_count_2g4"] = 16
    d["data_rate_kbps_2g4"] = _DATA_RATE_KBPS
    d["chip_rate_Mchip_s"] = _CHIP_RATE_MCHIP
    d["modes_of_operation"] = [
        {"name": "Beacon-enabled mode",
         "description": "PAN coordinator bounds the channel with a superframe "
         "delimited by network beacons; slotted CSMA-CA in the CAP and "
         "contention-free GTS in the CFP."},
        {"name": "Non-beacon-enabled mode",
         "description": "No periodic beacons; unslotted CSMA-CA; devices poll "
         "the coordinator with a Data Request MAC command."},
        {"name": "Zigbee mesh network",
         "description": "NWK-layer multi-hop routing (AODV-derived) over FFD "
         "routers; star and cluster-tree topologies also supported."},
    ]
    d["key_features"] = [
        "IEEE 802.15.4 2.4 GHz O-QPSK / DSSS PHY: 16 channels (11-26), "
        "32-chip spreading, 2.0 Mchip/s, 250 kbps.",
        "Also supports 868 MHz (20 kbps) and 915 MHz (40 kbps) sub-GHz PHYs.",
        "CSMA-CA channel access (slotted in beacon-enabled, unslotted "
        "otherwise) with energy-detect / carrier-sense CCA.",
        "Four MAC frame types: beacon, data, acknowledgement, MAC command.",
        "16-bit PAN ID; 16-bit short address + 64-bit extended (EUI-64) "
        "address; broadcast short address 0xFFFF.",
        "Beacon-enabled superframe (16 slots) with CAP / CFP and up to 7 "
        "Guaranteed Time Slots (GTS) for deterministic low-latency traffic.",
        "FFD (Full-Function) and RFD (Reduced-Function) device types; PAN "
        "Coordinator / Coordinator MAC roles.",
        "Zigbee NWK mesh / tree / star routing; ZDO device & service "
        "discovery; APS binding, reliable delivery and fragmentation.",
        "Endpoint (1-240) / cluster application model with the Zigbee Cluster "
        "Library (ZCL) and Zigbee 3.0 / Home Automation profiles.",
        "AES-128 CCM* security: network key (NWK), link keys (APS), 32-bit "
        "anti-replay frame counter, Trust Center, install codes.",
    ]
    d["topology_summary"] = (
        "Star, peer-to-peer/mesh, and cluster-tree topologies. Exactly one "
        "Zigbee Coordinator forms the network and acts as the Trust Center; "
        "Zigbee Routers (FFDs) extend the mesh and relay frames; Zigbee End "
        "Devices (often RFDs) are leaf nodes that communicate only through "
        "their parent and may sleep.")
    d["package_summary"] = (
        "Single-chip 2.4 GHz LR-WPAN SoC integrating the O-QPSK/DSSS radio, an "
        "802.15.4 MAC engine (CSMA-CA, superframe/GTS timer, FCS CRC-16), an "
        "AES-128 CCM* security engine, and the Zigbee NWK/APS/ZDO/ZCL stack. "
        "RF front-end pins connect to an external balun/antenna match.")
    d["use_cases"] = [
        "Home automation and smart lighting (Zigbee 3.0 / Home Automation "
        "profile)",
        "Low-power battery sensors and actuators (sleepy RFD end devices)",
        "Building automation and metering mesh networks",
        "Industrial monitoring with deterministic GTS traffic",
    ]
    d["revision_history"] = [
        {"version": "IEEE 802.15.4-2003", "date": "2003",
         "description": "First LR-WPAN standard: 868/915 MHz BPSK and 2.4 GHz "
         "O-QPSK PHYs, CSMA-CA MAC, beacon superframe, GTS, FFD/RFD."},
        {"version": "IEEE 802.15.4-2006/2011/2015/2020", "date": "2006-2020",
         "description": "Consolidated revisions, additional PHYs and MAC "
         "amendments; the 2.4 GHz O-QPSK PHY and core MAC carried forward."},
        {"version": "Zigbee Pro / Zigbee 3.0",
         "date": "2007 (Pro) / 2015 (3.0)",
         "description": "Zigbee Pro mesh stack; Zigbee 3.0 unified application "
         "profile and install-code commissioning over 802.15.4."},
    ]
    d["overview"] = (
        "This LR-WPAN device implements IEEE 802.15.4 (PHY + MAC) and the "
        "Zigbee stack (NWK + APS + ZDO + ZCL). The 2.4 GHz PHY transmits "
        "O-QPSK over DSSS: each 4-bit symbol selects one of 16 orthogonal "
        "32-chip PN sequences at 2.0 Mchip/s for 250 kbps across 16 channels "
        "(11-26, 5 MHz spacing). The MAC arbitrates the medium with CSMA-CA, "
        "supports a beacon-enabled superframe (16 slots split into a "
        "contention access period and a contention-free period of up to seven "
        "GTS), and uses 16-bit PAN IDs with 16-bit short and 64-bit extended "
        "(EUI-64) addresses. Four MAC frame types (beacon, data, "
        "acknowledgement, MAC command) and FFD/RFD device classes complete the "
        "802.15.4 layer. On top, Zigbee adds the NWK layer (mesh/tree/star "
        "routing with Coordinator / Router / End Device roles), the APS "
        "(binding, reliable delivery, fragmentation), the ZDO (device and "
        "service discovery on endpoint 0), and the ZCL endpoint/cluster "
        "application framework, all secured by AES-128 in CCM* mode with a "
        "network key, link keys, a 32-bit frame counter, and a Trust Center.")
    _write(p, d)


# ----------------------------------------------------------------------
# L2 — FRS
# ----------------------------------------------------------------------
def _l2(gd: Path) -> None:
    p = gd / "L2_FRS.json"
    if not p.is_file():
        return
    d = _read(p)
    po = _ensure_dict(d, "protocol_overview")
    po["type"] = (
        "Low-rate wireless personal area network (LR-WPAN). IEEE 802.15.4 "
        "PHY+MAC carrying the Zigbee NWK/APS/ZDO/ZCL stack; packet-based, "
        "CSMA-CA medium access, with an optional beacon-enabled superframe.")
    po["duplex"] = (
        "half-duplex (a single 2.4 GHz transceiver time-multiplexes transmit "
        "and receive; the radio turns around within aTurnaroundTime = "
        "12 symbols).")
    po["wireless"] = True
    po["band_GHz"] = 2.4
    po["band_MHz_alt"] = [868, 915]
    po["modulation"] = (
        "O-QPSK with half-sine pulse shaping (2.4 GHz); BPSK at 868/915 MHz.")
    po["spreading"] = (
        "Direct Sequence Spread Spectrum (DSSS): 32 chips/symbol, 16 PN "
        "sequences, 2.0 Mchip/s at 2.4 GHz.")
    po["data_rate_kbps"] = _DATA_RATE_KBPS
    po["channels_2g4"] = list(_CHANNELS_24G)
    po["channel_access"] = "CSMA-CA (slotted in beacon-enabled, unslotted otherwise)"
    po["mac_frame_types"] = [
        "beacon", "data", "acknowledgement", "MAC command"]
    po["addressing"] = {
        "pan_id_bits": 16, "short_address_bits": 16,
        "extended_address_bits": 64,
        "extended_address_format": "IEEE EUI-64",
        "broadcast_short_address": "0xFFFF"}
    po["device_types"] = ["FFD (Full-Function Device)",
                          "RFD (Reduced-Function Device)"]
    po["zigbee_roles"] = ["Coordinator", "Router", "End Device"]
    po["topologies"] = ["star", "cluster-tree", "mesh (peer-to-peer)"]
    po["layers"] = [
        "PHY (IEEE 802.15.4): O-QPSK/DSSS radio, ED, CCA, LQI/RSSI",
        "MAC (IEEE 802.15.4): CSMA-CA, superframe/GTS, addressing, FCS CRC-16",
        "NWK (Zigbee): mesh/tree/star routing, network key security",
        "APS (Zigbee): binding, reliable delivery, fragmentation, link keys",
        "ZDO (Zigbee, endpoint 0): device & service discovery, management",
        "ZCL / application: endpoints (1-240), clusters, profiles",
    ]
    po["security"] = (
        "AES-128 in CCM* mode (confidentiality + integrity MIC + 32-bit "
        "anti-replay frame counter); network key (NWK) + link keys (APS); "
        "Trust Center.")
    d["functional_requirements"] = [
        {"id": "FR-PHY-01", "text": "The 2.4 GHz PHY SHALL transmit O-QPSK "
         "with half-sine pulse shaping over DSSS (32 chips/symbol, 16 PN "
         "sequences, 2.0 Mchip/s) on one of 16 channels (channel 11-26, "
         "Fc = 2405 + 5*(k-11) MHz), at 250 kbps."},
        {"id": "FR-PHY-02", "text": "The PHY SHALL provide Energy Detection "
         "(ED), Clear Channel Assessment (CCA modes 1/2/3), Link Quality "
         "Indication (LQI), and transceiver state control (RX_ON / TX_ON / "
         "TRX_OFF) with aTurnaroundTime = 12 symbols."},
        {"id": "FR-PPDU-03", "text": "A PPDU SHALL comprise the SHR (4-octet "
         "preamble + 1-octet SFD = 0xA7), the PHR (7-bit Frame Length, "
         "PSDU <= aMaxPHYPacketSize = 127 octets), and the PSDU (the MPDU)."},
        {"id": "FR-MAC-04", "text": "The MAC SHALL support four frame types — "
         "beacon, data, acknowledgement, and MAC command — with an MHR "
         "(Frame Control, Sequence Number, addressing, optional auxiliary "
         "security header), MAC payload, and a 2-octet FCS (ITU-T CRC-16)."},
        {"id": "FR-CSMA-05", "text": "The MAC SHALL access the channel with "
         "CSMA-CA: slotted (beacon-enabled, aligned to backoff slots) or "
         "unslotted, using NB / BE / CW with macMaxCSMABackoffs = 4, "
         "macMinBE = 3, aMaxBE = 5, and aUnitBackoffPeriod = 20 symbols."},
        {"id": "FR-SF-06", "text": "In beacon-enabled mode the PAN coordinator "
         "SHALL bound the channel with a 16-slot superframe (Beacon Interval "
         "BI = aBaseSuperframeDuration*2^BO; Superframe Duration "
         "SD = aBaseSuperframeDuration*2^SO; 0 <= SO <= BO <= 14) divided into "
         "a Contention Access Period (CAP) and a Contention Free Period (CFP)."},
        {"id": "FR-GTS-07", "text": "The PAN coordinator MAY allocate up to "
         "seven Guaranteed Time Slots (GTS) in the CFP, each one or more "
         "contiguous superframe slots, with transmit or receive direction, "
         "negotiated via a GTS Request MAC command and advertised in the "
         "beacon."},
        {"id": "FR-ADDR-08", "text": "Devices SHALL use a 16-bit PAN ID and "
         "both a 16-bit short address (assigned on association) and a 64-bit "
         "extended IEEE (EUI-64) address; 0xFFFF is the broadcast short "
         "address."},
        {"id": "FR-DEV-09", "text": "The MAC SHALL distinguish Full-Function "
         "Devices (FFD: can be PAN coordinator/coordinator, relay, accept "
         "associations) from Reduced-Function Devices (RFD: single-coordinator "
         "leaf nodes)."},
        {"id": "FR-NWK-10", "text": "The Zigbee NWK layer SHALL join/leave "
         "networks, route frames over star/tree/mesh topologies (AODV-derived "
         "route discovery with RREQ/RREP, tree Cskip addressing, and source "
         "routing), maintain neighbor and routing tables, and apply the "
         "network key."},
        {"id": "FR-APS-11", "text": "The APS SHALL provide endpoint/cluster "
         "addressing (endpoints 1-240, endpoint 0 = ZDO), a binding table, "
         "APS acknowledgements, fragmentation/reassembly, and APS-layer "
         "(link-key) security."},
        {"id": "FR-ZDO-12", "text": "The ZDO (endpoint 0) SHALL provide device "
         "discovery (NWK_addr_req / IEEE_addr_req), service discovery "
         "(Node/Simple descriptor, Active_EP, Match_Desc), binding management "
         "(Bind/Unbind), and network management (Mgmt_* requests)."},
        {"id": "FR-ZCL-13", "text": "The application framework SHALL use the "
         "Zigbee Cluster Library: 16-bit cluster IDs with attributes and "
         "commands, the ZCL general command set (Read/Write Attributes, "
         "Configure/Report, Default Response, Discover), and profile-scoped "
         "endpoints (Simple Descriptor)."},
        {"id": "FR-SEC-14", "text": "Security SHALL use AES-128 in CCM* mode "
         "providing confidentiality, a Message Integrity Code (0/32/64/128 "
         "bits), and a 32-bit monotonically increasing anti-replay frame "
         "counter, with a network key, link keys, a Trust Center, and "
         "install-code commissioning."},
    ]
    d["error_response_conditions"] = [
        "FCS (CRC-16) mismatch — the received frame is discarded (no ACK).",
        "CCA busy across macMaxCSMABackoffs (4) retries — CSMA-CA failure; "
        "transmission is aborted.",
        "No acknowledgement for an AR-flagged frame within macAckWaitDuration "
        "— retransmit up to macMaxFrameRetries (3), then report failure.",
        "PAN ID conflict — PAN ID conflict notification MAC command and "
        "coordinator realignment.",
        "Orphaned device (loss of sync) — orphan notification / orphan scan to "
        "relocate the coordinator.",
        "Security MIC verification failure or frame-counter replay — frame "
        "rejected by the CCM* engine.",
        "Route discovery failure (no RREP) — NWK route error / status report.",
    ]
    d["compliance_requirements"] = [
        "2.4 GHz O-QPSK/DSSS PHY, 16 channels (11-26), 250 kbps; SFD = 0xA7; "
        "aMaxPHYPacketSize = 127.",
        "CSMA-CA medium access with the specified NB/BE/CW defaults.",
        "Four MAC frame types and the MHR/payload/FCS general frame format.",
        "16-bit PAN ID with 16-bit short and 64-bit extended (EUI-64) "
        "addressing.",
        "Beacon-enabled superframe with CAP/CFP and up to seven GTS (if "
        "beacon-enabled).",
        "FFD/RFD device classes; PAN Coordinator / Coordinator roles.",
        "Zigbee NWK mesh/tree/star routing; APS binding & reliable delivery; "
        "ZDO discovery; ZCL clusters.",
        "AES-128 CCM* security with network key + link key, Trust Center, and "
        "32-bit frame counter.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L3 — CMD / PROTOCOL
# ----------------------------------------------------------------------
def _l3(gd: Path) -> None:
    p = gd / "L3_CMD_PROTOCOL.json"
    if not p.is_file():
        return
    d = _read(p)
    d["protocol_type"] = (
        "Layered LR-WPAN protocol. IEEE 802.15.4 PHY (O-QPSK/DSSS PPDU) and "
        "MAC (CSMA-CA, superframe/GTS, four frame types) carry the Zigbee NWK "
        "(routed) / APS (endpoint/cluster) / ZDO / ZCL stack. Packet-based; "
        "not a register read/write bus.")
    d["channels"] = [
        {"name": "2.4 GHz O-QPSK/DSSS radio channel",
         "direction": "half-duplex (TX / RX time-multiplexed)",
         "description": "16 channels (11-26), 5 MHz spacing, "
         "Fc = 2405 + 5*(k-11) MHz, 250 kbps, 32-chip DSSS at 2.0 Mchip/s."},
    ]
    d["phy_layers"] = [
        {"layer": "SHR (Synchronization Header)",
         "fields": "4-octet preamble (all zero) + 1-octet SFD = 0xA7"},
        {"layer": "PHR (PHY Header)",
         "fields": "7-bit Frame Length + 1 reserved bit; PSDU 0-127 octets"},
        {"layer": "PSDU (PHY Service Data Unit)",
         "fields": "the MPDU (MAC frame), 0-127 octets"},
    ]
    d["mac_frame_types"] = [
        {"type": "beacon", "frame_type_bits": "0b000",
         "use": "transmitted by a coordinator to bound the superframe / "
                "advertise the PAN and GTS"},
        {"type": "data", "frame_type_bits": "0b001",
         "use": "carries an MSDU (NWK/APS/application payload)"},
        {"type": "acknowledgement", "frame_type_bits": "0b010",
         "use": "confirms reception of a frame whose Acknowledgment Request "
                "(AR) bit was set"},
        {"type": "MAC command", "frame_type_bits": "0b011",
         "use": "association, data request, GTS request, etc."},
    ]
    d["mac_general_frame_format"] = {
        "MHR": ["Frame Control (2 octets)", "Sequence Number (1 octet)",
                "Destination PAN ID", "Destination Address",
                "Source PAN ID", "Source Address",
                "Auxiliary Security Header (if Security Enabled)"],
        "MAC_payload": "variable",
        "MFR": "Frame Check Sequence (FCS, 2 octets, ITU-T CRC-16)",
    }
    d["frame_control_subfields"] = [
        "Frame Type (3 bits)", "Security Enabled (1)", "Frame Pending (1)",
        "Acknowledgment Request / AR (1)", "PAN ID Compression (1)",
        "Destination Addressing Mode (2)", "Frame Version (2)",
        "Source Addressing Mode (2)",
    ]
    d["mac_command_frames"] = [
        {"id": "0x01", "name": "Association request"},
        {"id": "0x02", "name": "Association response"},
        {"id": "0x03", "name": "Disassociation notification"},
        {"id": "0x04", "name": "Data request"},
        {"id": "0x05", "name": "PAN ID conflict notification"},
        {"id": "0x06", "name": "Orphan notification"},
        {"id": "0x07", "name": "Beacon request"},
        {"id": "0x08", "name": "Coordinator realignment"},
        {"id": "0x09", "name": "GTS request"},
    ]
    d["csma_ca"] = {
        "variants": ["slotted (beacon-enabled)", "unslotted (non-beacon)"],
        "NB_max_macMaxCSMABackoffs": 4,
        "BE_min_macMinBE": 3,
        "BE_max_aMaxBE": 5,
        "CW_slotted_default": 2,
        "aUnitBackoffPeriod_symbols": _UNIT_BACKOFF,
        "algorithm": "wait random (2^BE - 1) backoff periods, perform CCA, "
                     "transmit if idle else increment BE and retry up to NB.",
    }
    d["superframe"] = {
        "slots": _NUM_SF_SLOTS,
        "components": ["Beacon", "CAP (Contention Access Period)",
                       "CFP (Contention Free Period / GTS)",
                       "optional Inactive period"],
        "BI": "aBaseSuperframeDuration * 2^BO (BO = macBeaconOrder)",
        "SD": "aBaseSuperframeDuration * 2^SO (SO = macSuperframeOrder)",
        "constraint": "0 <= macSuperframeOrder <= macBeaconOrder <= 14",
        "aBaseSlotDuration_symbols": _BASE_SLOT,
        "aNumSuperframeSlots": _NUM_SF_SLOTS,
        "aBaseSuperframeDuration_symbols": _BASE_SLOT * _NUM_SF_SLOTS,
        "max_GTS": _MAX_GTS,
    }
    d["addressing"] = {
        "pan_id_bits": 16,
        "short_address_bits": 16,
        "extended_address_bits": 64,
        "extended_address_format": "IEEE EUI-64",
        "broadcast_short_address": "0xFFFF",
        "unallocated_short_address": "0xFFFE",
        "addressing_modes": {"0": "none", "2": "16-bit short",
                             "3": "64-bit extended"},
    }
    d["zigbee_stack_commands"] = {
        "NWK": "join/leave, route discovery (RREQ/RREP), network key",
        "APS": "endpoint/cluster data + ack + binding (Bind/Unbind)",
        "ZDO_ZDP": ["NWK_addr_req", "IEEE_addr_req", "Node_Desc_req",
                    "Simple_Desc_req", "Active_EP_req", "Match_Desc_req",
                    "Bind_req", "Unbind_req", "Mgmt_Lqi_req", "Mgmt_Rtg_req",
                    "Mgmt_Permit_Joining_req", "Mgmt_Leave_req"],
        "ZCL_general": ["Read Attributes", "Write Attributes",
                        "Configure Reporting", "Report Attributes",
                        "Default Response", "Discover Attributes"],
    }
    d["burst_based"] = False
    d["byte_oriented"] = True
    d["packet_based"] = True
    d["frame_format"] = {
        "phy": "SHR (preamble + SFD 0xA7) + PHR (length) + PSDU",
        "mac": "MHR + MAC payload + FCS (CRC-16)",
        "note": "Zigbee NWK / APS / ZCL headers are nested inside the MAC "
                "payload (MSDU).",
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L4 — REGMAP
# ----------------------------------------------------------------------
def _l4(gd: Path) -> None:
    p = gd / "L4_REGMAP.json"
    if not p.is_file():
        return
    d = _read(p)
    d["register_map_present"] = True
    d["notes"] = (
        "The 802.15.4 PHY/MAC are controlled through PIB (PAN Information "
        "Base) attributes accessed via the PLME-SET/GET and MLME-SET/GET SAP "
        "primitives, exposed in this SoC as memory-mapped configuration/status "
        "registers. The Zigbee NWK/APS keep their own NIB/AIB attribute bases "
        "and the binding/neighbor/routing tables.")
    d["register_access"] = {
        "transport": "MLME / PLME SAP primitives mapped to memory-mapped "
                     "registers",
        "purpose": "configure channel, PAN ID, addresses, beacon/superframe "
                   "order, GTS, security keys; read link status / counters.",
    }
    d["phy_pib_attributes"] = [
        {"name": "phyCurrentChannel", "desc": "current channel (11-26 @ 2.4 GHz)"},
        {"name": "phyChannelsSupported", "desc": "bitmap of supported channels"},
        {"name": "phyTransmitPower", "desc": "transmit power level"},
        {"name": "phyCCAMode", "desc": "CCA mode 1 (energy) / 2 (carrier) / "
                                       "3 (carrier+energy)"},
    ]
    d["mac_pib_attributes"] = [
        {"name": "macPANId", "desc": "16-bit PAN identifier"},
        {"name": "macShortAddress", "desc": "16-bit short address"},
        {"name": "macExtendedAddress", "desc": "64-bit IEEE EUI-64 address"},
        {"name": "macBeaconOrder", "desc": "BO; sets Beacon Interval"},
        {"name": "macSuperframeOrder", "desc": "SO; sets Superframe Duration"},
        {"name": "macAssociationPermit", "desc": "allow new associations"},
        {"name": "macMaxCSMABackoffs", "desc": "default 4"},
        {"name": "macMinBE", "desc": "minimum backoff exponent, default 3"},
        {"name": "aMaxBE", "desc": "maximum backoff exponent, default 5"},
        {"name": "macMaxFrameRetries", "desc": "default 3"},
        {"name": "macGTSPermit", "desc": "allow GTS allocation"},
    ]
    d["register_groups"] = [
        {"group": "PHY control/status", "fields": [
            "phyCurrentChannel", "phyTransmitPower", "phyCCAMode",
            "ED result", "LQI", "RSSI", "TRX state (RX_ON/TX_ON/TRX_OFF)"]},
        {"group": "MAC configuration", "fields": [
            "macPANId", "macShortAddress", "macExtendedAddress",
            "macBeaconOrder", "macSuperframeOrder", "macAssociationPermit",
            "macGTSPermit"]},
        {"group": "MAC CSMA-CA parameters", "fields": [
            "macMaxCSMABackoffs", "macMinBE", "aMaxBE", "macMaxFrameRetries",
            "macAckWaitDuration"]},
        {"group": "Security", "fields": [
            "network key", "link key table", "frame counter (32-bit)",
            "security level", "Trust Center address"]},
    ]
    d["zigbee_attribute_bases"] = {
        "NIB": "Network Information Base (NWK attributes)",
        "AIB": "APS Information Base (APS attributes, binding table)",
        "tables": ["binding table", "neighbor table", "routing table"],
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L5 — ADI / analog signaling
# ----------------------------------------------------------------------
def _l5(gd: Path) -> None:
    p = gd / "L5_ADI_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["analog_digital_interface_present"] = True
    d["signaling_summary"] = (
        "2.4 GHz RF: Offset-QPSK (O-QPSK) with half-sine pulse shaping "
        "(equivalent to MSK) over Direct Sequence Spread Spectrum. Each 4-bit "
        "symbol selects one of 16 nearly-orthogonal 32-chip PN sequences; chip "
        "rate 2.0 Mchip/s, symbol rate 62.5 ksymbol/s, 250 kbps. Receiver "
        "provides Energy Detection (ED), Clear Channel Assessment (CCA), Link "
        "Quality Indication (LQI) and RSSI. The RF port is differential "
        "(RF_P/RF_N) to an external balun/antenna match.")
    d["modulation"] = (
        "O-QPSK, half-sine pulse shaping (2.4 GHz); BPSK at 868/915 MHz.")
    d["spreading"] = {
        "type": "DSSS", "chips_per_symbol": 32, "pn_sequences": 16,
        "chip_rate_Mchip_s": _CHIP_RATE_MCHIP, "bits_per_symbol": 4,
        "symbol_rate_ksym_s": 62.5, "data_rate_kbps": _DATA_RATE_KBPS}
    d["channel_plan_2g4"] = {
        "channels": list(_CHANNELS_24G), "spacing_MHz": 5,
        "center_freq_formula_MHz": "2405 + 5*(k-11)",
        "ch11_MHz": 2405, "ch26_MHz": 2480}
    d["sub_ghz_phys"] = [
        {"band_MHz": 868, "modulation": "BPSK", "data_rate_kbps": 20},
        {"band_MHz": 915, "modulation": "BPSK", "data_rate_kbps": 40},
    ]
    d["receiver_metrics"] = ["ED (Energy Detection)", "CCA (modes 1/2/3)",
                             "LQI (0x00-0xFF)", "RSSI"]
    d["rf_pins"] = ["RF_P", "RF_N", "RF_BIAS", "XTAL_P", "XTAL_N",
                    "VDD_RF", "VSS"]
    d["turnaround_time_symbols"] = _TURNAROUND
    _write(p, d)


# ----------------------------------------------------------------------
# L6 — CONTROL LOGIC / FSM
# ----------------------------------------------------------------------
def _l6(gd: Path) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["fsm_states_mac"] = [
        {"name": "IDLE", "description": "Transceiver off or RX_ON; awaiting a "
         "frame to transmit or a received PPDU."},
        {"name": "CSMA_BACKOFF", "description": "CSMA-CA: wait a random "
         "(2^BE - 1) backoff periods (aUnitBackoffPeriod = 20 symbols)."},
        {"name": "CCA", "description": "Clear Channel Assessment; if busy "
         "increment BE and retry up to macMaxCSMABackoffs."},
        {"name": "TX", "description": "Transmit the PPDU (SHR + PHR + PSDU)."},
        {"name": "WAIT_ACK", "description": "If Acknowledgment Request set, "
         "wait macAckWaitDuration for the ACK frame."},
        {"name": "RX", "description": "Receive a PPDU; check FCS; deliver MSDU "
         "or process MAC command/beacon."},
        {"name": "RETRY", "description": "On missing ACK retransmit up to "
         "macMaxFrameRetries (3)."},
    ]
    d["fsm_states_association"] = [
        {"name": "SCAN", "description": "ED / active / passive / orphan scan "
         "to find a PAN / coordinator."},
        {"name": "ASSOCIATE", "description": "Send Association request MAC "
         "command; receive a short address in the Association response."},
        {"name": "JOINED", "description": "Associated; participates in the PAN "
         "(beacon-tracking if beacon-enabled)."},
        {"name": "ORPHAN", "description": "Loss of sync; orphan notification / "
         "orphan scan to relocate the coordinator."},
    ]
    d["fsm_states_nwk_join"] = [
        {"name": "NWK_DISCOVERY", "description": "Discover networks via MAC "
         "scans; select a parent (Coordinator or Router)."},
        {"name": "NWK_JOIN", "description": "Join through the parent; obtain a "
         "16-bit network address; receive the network key from the Trust "
         "Center."},
        {"name": "ROUTING", "description": "Maintain neighbor/routing tables; "
         "AODV route discovery (RREQ/RREP) on demand."},
    ]
    d["superframe_timing"] = {
        "BI_formula": "aBaseSuperframeDuration * 2^BO",
        "SD_formula": "aBaseSuperframeDuration * 2^SO",
        "constraint": "0 <= SO <= BO <= 14",
        "CAP_then_CFP": True}
    _write(p, d)


# ----------------------------------------------------------------------
# L7 — TEST / DEBUG
# ----------------------------------------------------------------------
def _l7(gd: Path) -> None:
    p = gd / "L7_TEST_DEBUG.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_modes"] = [
        "PHY continuous-TX (unmodulated carrier) for spectral compliance",
        "PHY continuous-TX modulated (PN9 / packet) for EVM",
        "PER (Packet Error Rate) receiver sensitivity test",
        "Energy Detection (ED) scan over channels 11-26",
        "CCA self-test (modes 1/2/3)",
        "Loopback of MAC frames through the security (CCM*) engine",
    ]
    d["debug_observability"] = [
        "Per-packet LQI and RSSI readback",
        "CSMA-CA NB/BE counters and CCA-busy count",
        "FCS error counter; ACK-timeout / retry counters",
        "Security MIC-fail and frame-counter-replay counters",
        "Superframe / GTS slot timing markers",
    ]
    d["verification_strategy"] = (
        "Layered verification: PHY (modulation/spreading, channel, "
        "sensitivity/PER), MAC (CSMA-CA backoff, superframe/GTS timing, four "
        "frame types, addressing, FCS), NWK/APS (join, routing, binding, "
        "fragmentation), ZDO/ZCL (discovery, cluster commands), and security "
        "(CCM* encrypt/decrypt/MIC, replay).")
    d["compliance_test_suites"] = [
        "IEEE 802.15.4 PHY/MAC conformance",
        "Zigbee Alliance / CSA certification (ZCL, ZDO, interoperability)",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L8 — RTL CONSTANTS
# ----------------------------------------------------------------------
def _l8_rtl(gd: Path) -> None:
    p = gd / "L8_RTL_CONSTANTS.json"
    if not p.is_file():
        return
    d = _read(p)
    d["parameters"] = {
        "DATA_RATE_KBPS_2G4": _DATA_RATE_KBPS,
        "CHIP_RATE_MCHIP_S": _CHIP_RATE_MCHIP,
        "CHIPS_PER_SYMBOL": 32,
        "BITS_PER_SYMBOL": 4,
        "PN_SEQUENCES": 16,
        "CHANNEL_MIN_2G4": 11,
        "CHANNEL_MAX_2G4": 26,
        "CHANNEL_COUNT_2G4": 16,
        "CHANNEL_SPACING_MHZ": 5,
        "A_MAX_PHY_PACKET_SIZE": _MAX_PHY_PACKET,
        "A_TURNAROUND_TIME_SYMBOLS": _TURNAROUND,
        "A_UNIT_BACKOFF_PERIOD_SYMBOLS": _UNIT_BACKOFF,
        "A_BASE_SLOT_DURATION_SYMBOLS": _BASE_SLOT,
        "A_NUM_SUPERFRAME_SLOTS": _NUM_SF_SLOTS,
        "A_BASE_SUPERFRAME_DURATION_SYMBOLS": _BASE_SLOT * _NUM_SF_SLOTS,
        "MAC_MAX_CSMA_BACKOFFS": 4,
        "MAC_MIN_BE": 3,
        "A_MAX_BE": 5,
        "MAC_MAX_FRAME_RETRIES": 3,
        "MAX_GTS": _MAX_GTS,
        "PAN_ID_BITS": 16,
        "SHORT_ADDR_BITS": 16,
        "EXT_ADDR_BITS": 64,
        "FCS_WIDTH_BITS": 16,
        "AES_KEY_BITS": 128,
        "FRAME_COUNTER_BITS": 32,
        "SFD_HEX": _SFD,
        "BROADCAST_SHORT_ADDR_HEX": "0xFFFF",
    }
    d["clock_domains"] = [
        {"name": "rf_chip_clk", "rate_MHz": 2.0,
         "note": "DSSS chip clock (2.0 Mchip/s)"},
        {"name": "sys_clk", "rate_MHz": 32.0,
         "note": "MAC / digital baseband / crypto"},
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L8 — TIMING WAVEFORM
# ----------------------------------------------------------------------
def _l8_timing(gd: Path) -> None:
    p = gd / "L8_TIMING_WAVEFORM.json"
    if not p.is_file():
        return
    d = _read(p)
    d["timing_constants"] = {
        "chip_period_ns": 500.0,
        "symbol_period_us": 16.0,
        "aTurnaroundTime_symbols": _TURNAROUND,
        "aUnitBackoffPeriod_symbols": _UNIT_BACKOFF,
        "aUnitBackoffPeriod_us": _UNIT_BACKOFF * 16.0,
        "aBaseSlotDuration_symbols": _BASE_SLOT,
        "aBaseSuperframeDuration_symbols": _BASE_SLOT * _NUM_SF_SLOTS,
    }
    d["timing_windows"] = [
        {"name": "Turnaround (Rx<->Tx)", "value": "12 symbols (192 us)"},
        {"name": "Backoff period", "value": "20 symbols (320 us)"},
        {"name": "Superframe slot", "value": "aBaseSlotDuration*2^SO symbols"},
        {"name": "ACK wait", "value": "macAckWaitDuration"},
    ]
    d["waveforms"] = [
        "PPDU: preamble (4 octets) | SFD 0xA7 | PHR (length) | PSDU",
        "Beacon-enabled superframe: Beacon | CAP (slotted CSMA-CA) | CFP "
        "(GTS) | inactive",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L9 — INTEGRATION SPEC
# ----------------------------------------------------------------------
def _l9(gd: Path) -> None:
    p = gd / "L9_INTEGRATION_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    _ptm.apply(d, "ieee802154_zigbee_soc")
    d["module_role"] = (
        "Top-level IEEE 802.15.4 + Zigbee LR-WPAN SoC: O-QPSK/DSSS radio "
        "interface, MAC engine (CSMA-CA, superframe/GTS, FCS), AES-128 CCM* "
        "security engine, and the NWK/APS/ZDO/ZCL stack interface.")
    d["chip_top_interfaces"] = [
        {"name": "rf_if", "type": "analog-digital RF",
         "signals": ["rf_p", "rf_n", "rf_bias", "xtal_p", "xtal_n"]},
        {"name": "host_sap", "type": "SAP message / register",
         "signals": ["mlme_req", "mlme_cfm", "mcps_data", "pd_data"]},
        {"name": "sys", "type": "clock/reset",
         "signals": ["sys_clk", "rst_n"]},
    ]
    d["submodules"] = [
        "phy_oqpsk_dsss (modulator/demodulator, ED/CCA, LQI/RSSI)",
        "mac_csma_ca (backoff/CCA engine)",
        "mac_superframe_gts (beacon/superframe/GTS timer)",
        "mac_framer (MHR build/parse, FCS CRC-16)",
        "sec_aes128_ccm_star (security engine, frame counter)",
        "nwk_router (mesh/tree/star routing, neighbor/routing tables)",
        "aps_layer (binding, ack, fragmentation)",
        "zdo_zcl_fw (device/service discovery, clusters)",
    ]
    d["topology_description"] = (
        "Wireless multi-hop: a single Zigbee Coordinator (Trust Center) forms "
        "the PAN; Routers (FFDs) relay over the mesh; End Devices (RFDs) are "
        "leaf nodes attached to a parent. No wired interconnect between nodes "
        "— the medium is the shared 2.4 GHz channel.")
    _write(p, d)


# ----------------------------------------------------------------------
# L10 — TEST CASES
# ----------------------------------------------------------------------
def _l10(gd: Path) -> None:
    p = gd / "L10_TEST_CASES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_cases"] = [
        {"id": "TC-PHY-01", "name": "O-QPSK/DSSS modulation & channel",
         "desc": "Verify 32-chip DSSS spreading, O-QPSK, 250 kbps on each of "
         "channels 11-26 (Fc = 2405 + 5*(k-11) MHz)."},
        {"id": "TC-PHY-02", "name": "Receiver sensitivity / PER",
         "desc": "Packet Error Rate at specified sensitivity; ED/CCA/LQI/RSSI "
         "readback."},
        {"id": "TC-MAC-03", "name": "CSMA-CA backoff",
         "desc": "Verify NB/BE/CW behaviour: random (2^BE - 1) backoff, CCA, "
         "retry to macMaxCSMABackoffs = 4; abort on persistent busy."},
        {"id": "TC-MAC-04", "name": "Four MAC frame types",
         "desc": "Build/parse beacon, data, acknowledgement, and MAC command "
         "frames; FCS CRC-16 check; AR/ACK handshake and retries (3)."},
        {"id": "TC-MAC-05", "name": "Superframe & GTS",
         "desc": "Beacon-enabled superframe timing (BI/SD, CAP/CFP); allocate "
         "and use up to 7 GTS via GTS Request."},
        {"id": "TC-MAC-06", "name": "Addressing",
         "desc": "16-bit PAN ID, 16-bit short and 64-bit extended (EUI-64) "
         "addressing; broadcast 0xFFFF; PAN ID compression."},
        {"id": "TC-MAC-07", "name": "Association / scanning",
         "desc": "ED/active/passive/orphan scans; Association request/response "
         "obtains a short address."},
        {"id": "TC-NWK-08", "name": "Mesh routing",
         "desc": "AODV route discovery (RREQ/RREP); multi-hop delivery through "
         "Routers; neighbor/routing table maintenance."},
        {"id": "TC-APS-09", "name": "Binding & reliable delivery",
         "desc": "APS binding table, APS acknowledgements, fragmentation/"
         "reassembly across endpoints/clusters."},
        {"id": "TC-ZDO-10", "name": "Discovery",
         "desc": "ZDO device/service discovery (NWK_addr_req, Simple_Desc_req, "
         "Match_Desc_req) and Mgmt_* requests."},
        {"id": "TC-ZCL-11", "name": "Cluster commands",
         "desc": "ZCL Read/Write Attributes, Configure/Report, On/Off cluster "
         "command round-trip."},
        {"id": "TC-SEC-12", "name": "AES-128 CCM* security",
         "desc": "Encrypt/decrypt with MIC verification; 32-bit frame-counter "
         "anti-replay; network key + link key; Trust Center join."},
    ]
    d["bring_up_sequence"] = [
        "Configure phyCurrentChannel and PHY transmit power.",
        "Set macPANId, macShortAddress / macExtendedAddress.",
        "(Beacon-enabled) set macBeaconOrder / macSuperframeOrder and start "
        "the PAN.",
        "Join the Zigbee network; receive the network key from the Trust "
        "Center.",
        "Discover services (ZDO) and bind clusters (APS); exchange ZCL "
        "commands.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L11 — OTP CONTENT (genuine-N/A: no OTP — identity is the EUI-64 + keys)
# ----------------------------------------------------------------------
def _l11(gd: Path) -> None:
    p = gd / "L11_OTP_CONTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    d["otp_present"] = True
    d["notes"] = (
        "Device identity and security material are typically held in "
        "one-time-programmable / non-volatile storage: the 64-bit IEEE "
        "extended address (EUI-64), the pre-configured Trust Center link key "
        "or install code, and (optionally) a factory-provisioned network key. "
        "These are programmed at manufacture/commissioning rather than baked "
        "into a fixed mask ROM table.")
    d["otp_fields"] = [
        {"name": "IEEE extended address (EUI-64)", "width_bits": 64},
        {"name": "Install code", "width_bits": 128,
         "desc": "per-device secret to derive a unique Trust Center link key "
                 "(Zigbee 3.0 commissioning)."},
        {"name": "Pre-configured link key", "width_bits": 128},
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L12 — BEHAVIORAL SEQUENCES
# ----------------------------------------------------------------------
def _l12(gd: Path) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["behavioral_sequences"] = [
        {"name": "Unslotted data transmit (CSMA-CA)",
         "steps": ["Init NB=0, BE=macMinBE(3)",
                   "Wait random (2^BE - 1) backoff periods (20 symbols each)",
                   "Perform CCA",
                   "If idle: turn around (12 symbols) and transmit PPDU",
                   "If AR set: wait macAckWaitDuration for ACK",
                   "If busy: BE = min(BE+1, aMaxBE=5), NB++, retry until "
                   "NB > macMaxCSMABackoffs(4) then fail",
                   "If no ACK: retransmit up to macMaxFrameRetries(3)"]},
        {"name": "Beacon-enabled superframe cycle",
         "steps": ["Coordinator transmits Beacon at superframe start",
                   "Devices contend in the CAP using slotted CSMA-CA",
                   "GTS owners transmit/receive in the CFP without contention",
                   "Optional inactive period (coordinator may sleep)",
                   "Next Beacon after BI = aBaseSuperframeDuration*2^BO"]},
        {"name": "Association",
         "steps": ["Scan (active/passive) for a coordinator",
                   "Send Association request MAC command",
                   "Coordinator replies with Association response + short "
                   "address",
                   "Device adopts macShortAddress and joins the PAN"]},
        {"name": "Zigbee join + secure",
         "steps": ["NWK discovery; select parent (Coordinator/Router)",
                   "MAC associate; obtain 16-bit network address",
                   "Trust Center authenticates and delivers the network key "
                   "(transported under a link key / install code)",
                   "Device is operational on the secured mesh"]},
        {"name": "Mesh route discovery (AODV-derived)",
         "steps": ["Originator broadcasts a Route Request (RREQ)",
                   "Routers rebroadcast, accumulating path cost",
                   "Destination unicasts a Route Reply (RREP)",
                   "Originator installs the next-hop routing-table entry"]},
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L13 — LAB CALIBRATION
# ----------------------------------------------------------------------
def _l13(gd: Path) -> None:
    p = gd / "L13_LAB_CALIBRATION.json"
    if not p.is_file():
        return
    d = _read(p)
    d["lab_calibration_present"] = True
    d["notes"] = (
        "RF calibration for the 2.4 GHz O-QPSK/DSSS transceiver: carrier "
        "frequency / synthesizer trim against the crystal reference, transmit "
        "power level, EVM, and receiver sensitivity (PER). Digital "
        "MAC/security blocks need no analog trim.")
    d["calibration_targets"] = [
        {"name": "Carrier frequency error", "spec": "within band per channel "
         "(2405-2480 MHz, 5 MHz spacing)"},
        {"name": "Transmit power", "spec": "phyTransmitPower setting"},
        {"name": "Receiver sensitivity", "spec": "PER target at rated "
         "sensitivity"},
        {"name": "EVM / modulation accuracy", "spec": "O-QPSK half-sine "
         "shaping compliance"},
    ]
    d["lab_equipment"] = [
        "Vector signal generator / analyzer (2.4 GHz)",
        "802.15.4 protocol/packet sniffer",
        "Reference crystal / frequency counter",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L14 — PROTOCOL VERSIONING
# ----------------------------------------------------------------------
def _l14(gd: Path) -> None:
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["spec_version"] = (
        "IEEE Std 802.15.4 (2.4 GHz O-QPSK PHY) + Zigbee Pro / Zigbee 3.0")
    f["standards_bodies"] = [
        "IEEE 802.15 Working Group (802.15.4 PHY+MAC)",
        "Connectivity Standards Alliance / CSA (Zigbee NWK+APS+ZDO+ZCL)",
    ]
    f["version_history"] = [
        {"version": "802.15.4-2003", "note": "first LR-WPAN standard"},
        {"version": "802.15.4-2006/2011/2015/2020",
         "note": "consolidated revisions; 2.4 GHz O-QPSK PHY carried forward"},
        {"version": "Zigbee 2007 / Zigbee Pro",
         "note": "mesh stack profile"},
        {"version": "Zigbee 3.0", "note": "unified application profile + "
         "install-code commissioning"},
    ]
    f["frame_version_field_bits"] = 2
    _write(p, d)


# ----------------------------------------------------------------------
# L15 — ENCODING TABLES
# ----------------------------------------------------------------------
def _l15(gd: Path) -> None:
    p = gd / "L15_ENCODING_TABLES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["mac_frame_type_encoding"] = {
        "0b000": "beacon", "0b001": "data",
        "0b010": "acknowledgement", "0b011": "MAC command"}
    f["addressing_mode_encoding"] = {
        "0": "no address", "2": "16-bit short", "3": "64-bit extended"}
    f["cca_mode_encoding"] = {
        "1": "energy above threshold", "2": "carrier sense",
        "3": "carrier sense AND energy"}
    f["mac_command_identifiers"] = {
        "0x01": "Association request", "0x02": "Association response",
        "0x03": "Disassociation notification", "0x04": "Data request",
        "0x05": "PAN ID conflict notification", "0x06": "Orphan notification",
        "0x07": "Beacon request", "0x08": "Coordinator realignment",
        "0x09": "GTS request"}
    f["dsss_2g4"] = {
        "chips_per_symbol": 32, "pn_sequences": 16, "bits_per_symbol": 4,
        "chip_rate_Mchip_s": _CHIP_RATE_MCHIP}
    f["sfd_2g4"] = _SFD
    f["security_levels"] = {
        "0x00": "none", "0x01": "MIC-32", "0x02": "MIC-64",
        "0x03": "MIC-128", "0x04": "ENC", "0x05": "ENC-MIC-32",
        "0x06": "ENC-MIC-64", "0x07": "ENC-MIC-128"}
    _write(p, d)


# ----------------------------------------------------------------------
# L16 — COMPLIANCE PROPERTIES
# ----------------------------------------------------------------------
def _l16(gd: Path) -> None:
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["properties"] = [
        "PHY: O-QPSK/DSSS, 16 channels (11-26), 250 kbps, SFD=0xA7, "
        "aMaxPHYPacketSize=127.",
        "MAC: CSMA-CA with NB<=macMaxCSMABackoffs(4), macMinBE(3)<=BE<="
        "aMaxBE(5).",
        "MAC: four frame types; FCS = ITU-T CRC-16; ACK within "
        "macAckWaitDuration; <=macMaxFrameRetries(3).",
        "MAC: 16-bit PAN ID; 16-bit short + 64-bit EUI-64 addresses; "
        "broadcast 0xFFFF.",
        "MAC: beacon-enabled superframe (16 slots, CAP/CFP), 0<=SO<=BO<=14, "
        "<=7 GTS.",
        "NWK: mesh/tree/star routing; AODV route discovery; network-key "
        "secured.",
        "APS: endpoint(1-240)/cluster addressing; binding; APS ACK; "
        "fragmentation; link-key secured.",
        "ZDO: device/service discovery on endpoint 0.",
        "ZCL: 16-bit cluster IDs; general command set; profile-scoped "
        "endpoints.",
        "Security: AES-128 CCM*; MIC 0/32/64/128 bits; 32-bit frame counter; "
        "Trust Center.",
    ]
    f["certification"] = [
        "IEEE 802.15.4 PHY/MAC conformance",
        "Connectivity Standards Alliance (Zigbee) certification",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L17 — CHANNEL / SIGNAL CATALOG (force-overwrite per task)
# ----------------------------------------------------------------------
def _l17(gd: Path) -> None:
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["signals"] = [
        {"name": "RF_P / RF_N", "dir": "bidir (TX/RX)",
         "purpose": "Differential 2.4 GHz RF port to the antenna balun/match; "
         "O-QPSK/DSSS, half-duplex."},
        {"name": "RF_BIAS", "dir": "analog", "purpose": "RF front-end bias."},
        {"name": "XTAL_P / XTAL_N", "dir": "in",
         "purpose": "Reference crystal (16/32 MHz) for the frequency "
         "synthesizer / chip clock."},
        {"name": "VDD_RF / VSS", "dir": "supply",
         "purpose": "RF supply and ground."},
    ]
    f["logical_channel_catalog"] = [
        {"name": "Physical channel (2.4 GHz)",
         "meaning": "One of 16 DSSS channels (11-26), 5 MHz spacing, "
         "Fc = 2405 + 5*(k-11) MHz, 250 kbps."},
        {"name": "Beacon", "meaning": "Superframe-delimiting frame from the "
         "coordinator carrying GTS descriptors and pending-address list."},
        {"name": "CAP (Contention Access Period)",
         "meaning": "Slotted-CSMA-CA contention window within the superframe."},
        {"name": "CFP (Contention Free Period)",
         "meaning": "Guaranteed Time Slots (GTS), contention-free."},
    ]
    f["channel_plan_2g4"] = {
        "channels": list(_CHANNELS_24G), "spacing_MHz": 5,
        "center_freq_formula_MHz": "2405 + 5*(k-11)"}
    f["wire_count"] = 7
    _write(p, d)


# ----------------------------------------------------------------------
# L18 — INTERCONNECT TOPOLOGY
# ----------------------------------------------------------------------
def _l18(gd: Path) -> None:
    p = gd / "L18_INTERCONNECT_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["topology"] = "wireless multi-hop (star / cluster-tree / mesh)"
    f["topologies_supported"] = ["star", "cluster-tree", "mesh (peer-to-peer)"]
    f["node_roles"] = [
        {"role": "Zigbee Coordinator (ZC)",
         "desc": "exactly one; forms the network, Trust Center, FFD, "
         "network address 0x0000"},
        {"role": "Zigbee Router (ZR)",
         "desc": "FFD; relays/routes, permits joins, extends the mesh"},
        {"role": "Zigbee End Device (ZED)",
         "desc": "leaf node (RFD/FFD); talks only through its parent; may "
         "sleep"},
    ]
    f["mac_roles"] = ["PAN Coordinator", "Coordinator", "Device (FFD/RFD)"]
    f["routing"] = (
        "AODV-derived mesh route discovery (RREQ/RREP); tree (Cskip "
        "distributed addressing); source routing for many-to-one "
        "(concentrator) flows.")
    f["medium"] = "shared 2.4 GHz wireless channel (no wired interconnect)"
    _write(p, d)


# ----------------------------------------------------------------------
# L19 — CONSTRAINTS / PDK (genuine N/A for RF/protocol facts)
# ----------------------------------------------------------------------
def _l19(gd: Path) -> None:
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["clock_domains"] = [
        {"name": "rf_chip_clk", "rate_MHz": 2.0,
         "note": "DSSS chip rate"},
        {"name": "sys_clk", "rate_MHz": 32.0,
         "note": "MAC / baseband / crypto"},
    ]
    f["notes"] = (
        "Standard-cell constraints for the digital MAC / NWK / APS / security "
        "blocks; the 2.4 GHz RF front-end is an analog/RF macro with its own "
        "PDK constraints. No protocol-specific PDK rule beyond the chip-rate "
        "and system-clock domains.")
    _write(p, d)


# ----------------------------------------------------------------------
# L20 — DFT SCAN TOPOLOGY (genuine N/A protocol facts)
# ----------------------------------------------------------------------
def _l20(gd: Path) -> None:
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["notes"] = (
        "Digital MAC/NWK/APS/security logic is scan-testable; the AES-128 "
        "CCM* engine uses standard scan with secure-test isolation of the key "
        "registers. The RF macro uses analog/RF production test (PER, EVM) "
        "rather than scan.")
    f["secure_test_isolation"] = (
        "Key/frame-counter registers isolated from scan to prevent key "
        "leakage during test.")
    _write(p, d)


# ----------------------------------------------------------------------
# L21 — POWER INTENT
# ----------------------------------------------------------------------
def _l21(gd: Path) -> None:
    p = gd / "L21_POWER_INTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["power_domains"] = [
        {"name": "VDD_RF", "desc": "2.4 GHz RF front-end supply"},
        {"name": "VDD_DIG", "desc": "digital MAC/NWK/APS/security supply"},
    ]
    f["low_power_modes"] = [
        "Sleepy End Device: RFD sleeps between polls / beacons to save battery",
        "Beacon-enabled inactive period: coordinator/devices sleep between "
        "superframes",
        "TRX_OFF: transceiver powered down when neither RX nor TX is needed",
    ]
    f["notes"] = (
        "Ultra-low-power operation is a core 802.15.4/Zigbee goal: duty-cycled "
        "radio, sleepy end devices, and superframe inactive periods minimize "
        "average current for battery nodes.")
    _write(p, d)


# ----------------------------------------------------------------------
# L22 — VERIFICATION PLAN
# ----------------------------------------------------------------------
def _l22(gd: Path) -> None:
    p = gd / "L22_VERIFICATION_PLAN.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["notes"] = (
        "Verification spans all layers: PHY (O-QPSK/DSSS modulation, channel, "
        "sensitivity/PER, ED/CCA/LQI), MAC (CSMA-CA backoff, superframe/GTS "
        "timing, four frame types, addressing, FCS CRC-16, ACK/retry), NWK/APS "
        "(join, AODV routing, binding, fragmentation), ZDO/ZCL (discovery, "
        "cluster commands), and security (AES-128 CCM* encrypt/decrypt/MIC, "
        "32-bit frame-counter anti-replay).")
    f["coverage_targets"] = [
        "All four MAC frame types built and parsed",
        "CSMA-CA NB/BE/CW boundary cases (busy x macMaxCSMABackoffs)",
        "Superframe BI/SD timing and GTS allocation (1..7)",
        "Short + extended addressing and PAN ID compression",
        "Mesh route discovery success and failure (no-RREP)",
        "CCM* MIC pass/fail and frame-counter replay rejection",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L23 — SECURITY REQUIREMENTS
# ----------------------------------------------------------------------
def _l23(gd: Path) -> None:
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["cipher"] = "AES-128 (128-bit Advanced Encryption Standard)"
    f["mode"] = "CCM* (Counter with CBC-MAC, star variant — allows "\
                "encryption-only / integrity-only)"
    f["services"] = ["confidentiality (encryption)",
                     "data integrity (Message Integrity Code, MIC)",
                     "replay protection (frame counter)"]
    f["mic_length_bits"] = [0, 32, 64, 128]
    f["frame_counter_bits"] = 32
    f["security_levels"] = {
        "0x00": "none", "0x07": "ENC-MIC-128 (max)"}
    f["keys"] = [
        {"name": "Network key", "bits": 128,
         "desc": "shared by all devices; secures NWK frames; distributed by "
         "the Trust Center; supports rotation (key sequence number)."},
        {"name": "Link key", "bits": 128,
         "desc": "pairwise APS-layer key (trust-center link key or application "
         "link key) for end-to-end security."},
    ]
    f["trust_center"] = (
        "A single device (normally the Zigbee Coordinator) that authenticates "
        "joining devices and distributes the network key; manages key "
        "establishment.")
    f["install_code"] = (
        "Per-device pre-configured secret used to derive a unique "
        "trust-center link key during Zigbee 3.0 commissioning.")
    _write(p, d)
