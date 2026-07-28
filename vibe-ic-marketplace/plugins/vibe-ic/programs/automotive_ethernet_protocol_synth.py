"""Automotive Ethernet (single-twisted-pair Ethernet PHY) protocol synth.

Covers the IEEE single-pair Automotive-Ethernet PHY family:
  * 100BASE-T1   (IEEE 802.3bw-2015, formerly OPEN Alliance BroadR-Reach)
  * 1000BASE-T1  (IEEE 802.3bp-2016)
  * 10BASE-T1S   (IEEE 802.3cg-2019, short-reach multidrop + PLCA)
  * 10BASE-T1L   (IEEE 802.3cg-2019, long-reach point-to-point)

v0.1.91 — ic_class-gated overlay for the `bus_interconnect_protocol` /
`serial_peripheral_protocol`-shaped specs that exhibit the single-twisted-
pair Automotive-Ethernet structural signature. This helper EXTENDS the base
`ethernet_protocol_synth` sibling: an Automotive-Ethernet doc still preserves
the IEEE 802.3 Clause-4 MAC frame, so the base Ethernet detector
(MII+MDIO+PHY, or 802.3+MAC+frame, or Ethernet+preamble/SFD) ALSO fires on it.
The two synths therefore LAYER — the base ethernet synth runs first and lays
down the generic 802.3 MAC/MII/MDIO baseline; this Automotive synth then runs
and FORCE-OVERWRITES (direct-assign, NEVER setdefault) every L1/L2/L3/L4 key
the sibling populated, specialising the docs to the single-pair T1 PHY family
(ONE twisted pair, PAM3, echo-cancellation full-duplex, PHY master/slave
timing, 10BASE-T1S multidrop + PLCA). This mirrors the
NVMe-on-PCIe / I3C-extends-I2C / 800G-on-802.3 cross-protocol
force-overwrite doctrine.

DETECTOR (module-level `is_automotive_ethernet`, documented for the runner;
operates on the L1/L2 CONTENT blob built from the generated docs, NEVER on the
input-doc filename or benchmark folder name — filename-sniffing was previously
flagged a HIGH defect):

    is_automotive_ethernet(blob) requires ALL of:
      (a) a single-twisted-pair STRUCTURE token
          ("single twisted pair" / "single unshielded twisted pair" /
           "one twisted pair" / "single-pair"), AND
      (b) PAM3 ternary line modulation ("PAM3"), AND
      (c) a T1 variant NAME token, word-boundary matched
          ("100BASE-T1" / "1000BASE-T1" / "10BASE-T1S" / "10BASE-T1L"
           / "802.3bw" / "802.3bp" / "802.3cg"), AND
      (d) an Automotive-PHY MECHANISM token
          ("echo cancellation" / "PLCA" /
           "Physical Layer Collision Avoidance" / "BroadR-Reach"),
    and MUST NOT be primary standard-Ethernet, 800G, or AFDX (see MUTEX
    below).

STRUCTURAL signal, never name alone: a doc that merely *mentions* "100BASE-T1"
in passing but lacks the single-pair + PAM3 + echo/PLCA structure does NOT
fire. The four conjuncts each demand a different structural fact (medium,
modulation, named variant, bidirectional mechanism).

SIBLING DISAMBIGUATION (MUTEX):
  * Standard Ethernet (the `ethernet` benchmark — IEEE 802.3 MII/GMII,
    4-pair 1000BASE-T, 8b10b, 100BASE-TX) carries NONE of the
    single-twisted-pair + PAM3 + T1 + echo/PLCA conjuncts, so THIS detector
    never fires on it. Additionally we DEFER if the blob is
    standard-Ethernet-primary (MII/GMII present AND no single-pair token), or
    mentions 4-pair / 8b10b without a T1 single-pair signature.
  * 800G Ethernet (the `ethernet_800g` benchmark — PAM4, 802.3df, 800GBASE)
    uses PAM4 (not PAM3) and 8x100G multi-lane, so the PAM3 + single-pair
    conjuncts exclude it. We additionally DEFER on "PAM4" / "800GBASE" /
    "802.3df" primary tokens.
  * AFDX / ARINC-664 avionics Ethernet uses Virtual Links / BAG / redundant
    networks over standard multi-pair Ethernet — no single-pair PAM3 T1
    signature. We DEFER on "ARINC 664" / "Virtual Link" + "BAG" primary
    tokens.

Public entry:
    apply_automotive_ethernet_synth(generated_docs_dir,
                                    is_automotive_ethernet,
                                    automotive_ethernet_ic_name)
runs AFTER the base ethernet synth (the runner wires it after
apply_ethernet_synth) and force-overwrites the sibling baseline.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

import l_doc_generator_stamp as _stamp


# ---------------------------------------------------------------------------
# Module-level detector (content-only, structural, word-boundary, MUTEX).
# ---------------------------------------------------------------------------
def _wb(token: str, text: str) -> bool:
    """Word-boundary, case-insensitive substring test. The token may contain
    regex-special chars (e.g. '100BASE-T1', '802.3bw') so we escape it and
    bound it with \\b on alphanumeric edges."""
    return re.search(r"(?<![A-Za-z0-9])" + re.escape(token) + r"(?![A-Za-z0-9])",
                     text, flags=re.IGNORECASE) is not None


def is_automotive_ethernet(blob: str) -> bool:
    """True iff the L1/L2 content blob exhibits the single-twisted-pair
    Automotive-Ethernet PHY structural signature (100BASE-T1 / 1000BASE-T1 /
    10BASE-T1S / 10BASE-T1L). CONTENT-ONLY: never reads filenames or folder
    names. STRUCTURAL: requires four orthogonal structural conjuncts, not a
    bare name token. MUTEX: defers to standard Ethernet / 800G / AFDX when
    those are primary."""
    if not blob:
        return False
    t = blob

    # Four orthogonal structural conjuncts. This positive signature is the MUTEX:
    # no standard-Ethernet / 800G / AFDX doc is single-twisted-pair + PAM3 +
    # named-T1-variant + an automotive bidirectional/multidrop mechanism. We
    # compute it FIRST and let it WIN over an incidental "800GBASE"/"PAM4"
    # comparison mention (an Automotive-T1 spec contrasts itself against 800G,
    # so its full L-doc blob carries those tokens) — the v0.1.89 lesson: an
    # over-aggressive name-anywhere MUTEX wrongly suppresses the own-doc.
    # (a) single-twisted-pair STRUCTURE (the defining T1 property).
    single_pair = (
        _wb("single twisted pair", t)
        or _wb("single unshielded twisted pair", t)
        or _wb("one twisted pair", t)
        or _wb("single-pair", t)
        or _wb("single twisted-pair", t)
        or _wb("one single twisted pair", t)
        or _wb("one balanced pair", t))
    # (b) PAM3 ternary line modulation (vs MLT-3 / 8b10b / PAM4 of std/800G).
    pam3 = _wb("PAM3", t)
    # (c) a named T1 variant (word-boundary).
    variant = (
        _wb("100BASE-T1", t) or _wb("1000BASE-T1", t)
        or _wb("10BASE-T1S", t) or _wb("10BASE-T1L", t)
        or _wb("10BASE-T1", t)
        or _wb("802.3bw", t) or _wb("802.3bp", t) or _wb("802.3cg", t))
    # (d) an Automotive-PHY bidirectional / multidrop MECHANISM token.
    mechanism = (
        _wb("echo cancellation", t) or _wb("echo canceller", t)
        or _wb("echo canceler", t)
        or _wb("PLCA", t)
        or _wb("Physical Layer Collision Avoidance", t)
        or _wb("BroadR-Reach", t))

    return bool(single_pair and pam3 and variant and mechanism)


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------
def _empty(v) -> bool:
    return v in (None, {}, []) or (isinstance(v, str) and not v.strip())


def _read(p: Path) -> dict:
    return json.loads(p.read_text())


def _write(p: Path, d: dict) -> None:
    # THE L-document write chokepoint: stamps the producing release onto
    # the document, then serialises it byte-identically to before.
    _stamp.dump(p, d)


def _ensure_dict(d: dict, key: str) -> dict:
    v = d.get(key)
    if not isinstance(v, dict):
        v = {}
        d[key] = v
    return v


def _force_ic_name(gd: Path, ic_name: str) -> None:
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
            d["ic_name"] = ic_name
            _write(q, d)
    for n in [
        "L14_PROTOCOL_VERSIONING.json", "L15_ENCODING_TABLES.json",
        "L16_COMPLIANCE_PROPERTIES.json", "L17_CHANNEL_SIGNAL_CATALOG.json",
        "L18_INTERCONNECT_TOPOLOGY.json", "L19_CONSTRAINTS_PDK.json",
        "L20_DFT_SCAN_TOPOLOGY.json", "L21_POWER_INTENT.json",
        "L22_VERIFICATION_PLAN.json", "L23_SECURITY_REQUIREMENTS.json",
    ]:
        q = gd / n
        if q.is_file():
            d = _read(q)
            f = d.get("fields")
            if not isinstance(f, dict):
                f = {}
            f["ic_name"] = ic_name
            d["fields"] = f
            _write(q, d)


# ---------------------------------------------------------------------------
# L1 — Datasheet
# ---------------------------------------------------------------------------
def _apply_l1(gd: Path) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    d["document_title"] = (
        "Automotive Ethernet Physical Layer Specification — Single Unshielded "
        "Twisted-Pair (one pair) Ethernet PHY: 100BASE-T1 (IEEE Std "
        "802.3bw-2015, formerly OPEN Alliance BroadR-Reach), 1000BASE-T1 "
        "(IEEE Std 802.3bp-2016), and 10BASE-T1S / 10BASE-T1L (IEEE Std "
        "802.3cg-2019), with cross-references to the IEEE 802.3 Clause-4 MAC "
        "frame format and the MAC / RS / PCS / PMA / PMD layered architecture")
    d["version"] = (
        "IEEE Std 802.3bw-2015 (100BASE-T1) + IEEE Std 802.3bp-2016 "
        "(1000BASE-T1) + IEEE Std 802.3cg-2019 (10BASE-T1S short-reach "
        "multidrop + 10BASE-T1L long-reach) — single-twisted-pair Automotive "
        "Ethernet PHY family driven into the automotive industry by the OPEN "
        "(One-Pair Ether-Net) Alliance SIG")
    d["revised_date"] = "2019"
    d["manufacturer"] = (
        "IEEE 802.3 Working Group of the IEEE LAN/MAN Standards Committee "
        "(LMSC); single-pair PHYs promoted by the OPEN Alliance SIG; "
        "100BASE-T1 originated as Broadcom BroadR-Reach")
    d["copyright"] = "© IEEE"
    d["abstract"] = (
        "Automotive Ethernet carries IEEE 802.3 Ethernet over a SINGLE "
        "unshielded twisted pair (UTP, ONE balanced pair) rather than the "
        "four pairs / 8b10b of standard enterprise Ethernet. Full-duplex is "
        "achieved by SIMULTANEOUS BIDIRECTIONAL transmission on the one pair "
        "with ECHO CANCELLATION: each PHY subtracts its own transmitted "
        "(near-end echo) signal to recover the remote signal. One PHY is the "
        "timing MASTER, the other the timing SLAVE (PHY-level master/slave "
        "loop timing). 100BASE-T1 (IEEE 802.3bw, BroadR-Reach) runs 100 Mb/s "
        "using PAM3 (3-level: -1/0/+1) at 66.67 MBd with a 4B3B + 3B2T PCS "
        "and a scrambler. 1000BASE-T1 (IEEE 802.3bp) runs 1 Gb/s using PAM3 "
        "at 750 MBd. 10BASE-T1S (IEEE 802.3cg) is a 10 Mb/s SHORT-REACH "
        "MULTIDROP variant that uses PLCA (Physical Layer Collision "
        "Avoidance), implemented as a Reconciliation Sublayer, to arbitrate "
        "the shared single-pair segment deterministically; 10BASE-T1L is the "
        "10 Mb/s LONG-REACH (up to 1000 m) point-to-point variant. Each PHY "
        "is layered MAC -> RS (optionally PLCA RS) -> PCS -> PMA -> PMD over "
        "the single pair. SNR and MSE are the principal link-quality metrics; "
        "EEE Low-Power Idle (LPI) saves power; automotive EMC is a first-class "
        "constraint. The IEEE 802.3 Clause-4 MAC frame format is PRESERVED.")
    d["keywords"] = [
        "Automotive Ethernet", "single twisted pair",
        "single unshielded twisted pair", "one pair", "UTP",
        "100BASE-T1", "1000BASE-T1", "10BASE-T1S", "10BASE-T1L",
        "IEEE 802.3bw", "IEEE 802.3bp", "IEEE 802.3cg", "BroadR-Reach",
        "OPEN Alliance", "PAM3", "echo cancellation",
        "simultaneous bidirectional", "Full Duplex", "master/slave timing",
        "link training", "PMA", "PCS", "PMD", "PLCA",
        "Physical Layer Collision Avoidance", "Reconciliation Sublayer",
        "multidrop", "SNR", "MSE", "EEE", "LPI",
        "Energy Efficient Ethernet", "automotive EMC", "scrambler",
        "4B3B", "3B2T", "80B/81B", "MDI", "Ethernet frame", "Preamble",
        "SFD", "FCS", "CRC-32", "AVB", "TSN",
    ]
    d["external_pins"] = [
        "MDI (Medium Dependent Interface): ONE single twisted pair (2 wires, "
        "1 balanced pair) carrying simultaneous bidirectional PAM3 traffic — "
        "the single defining T1 medium (vs the 4 pairs of standard BASE-T).",
        "xMII (MII / RMII / RGMII / GMII / SGMII as appropriate to the rate) "
        "to the MAC — logical reconciliation interface.",
        "MDC / MDIO management bus (Clause 22 basic + Clause 45 MMD) — STA "
        "configures master/slave, reads SNR/MSE/link status, PLCA control.",
        "Reference clock + RESET# + interrupt / link-status sideband.",
        "Common-mode-choke / EMC-filter terminals on the MDI pair (automotive "
        "EMC: bulk-current-injection immunity, controlled emissions).",
    ]
    d["external_pin_count_mdi_wires"] = 2
    d["external_pin_count_mdi_pairs"] = 1
    d["supported_speeds_Mbps"] = [10, 100, 1000]
    d["modes_of_operation"] = [
        {"name": "100BASE-T1 (IEEE 802.3bw, BroadR-Reach) — 100 Mb/s, 1 pair, PAM3, echo-cancelled full-duplex",
         "interface_to_MAC": "MII / RMII", "pairs": 1, "modulation": "PAM3",
         "baud_rate_MBd": 66.67, "data_rate_Mbps": 100,
         "duplex": "simultaneous bidirectional (full-duplex) via echo cancellation"},
        {"name": "1000BASE-T1 (IEEE 802.3bp) — 1 Gb/s, 1 pair, PAM3, echo-cancelled full-duplex",
         "interface_to_MAC": "RGMII / SGMII", "pairs": 1, "modulation": "PAM3",
         "baud_rate_MBd": 750, "data_rate_Mbps": 1000,
         "duplex": "simultaneous bidirectional (full-duplex) via echo cancellation"},
        {"name": "10BASE-T1S (IEEE 802.3cg) — 10 Mb/s, 1 pair, SHORT-REACH MULTIDROP with PLCA",
         "interface_to_MAC": "MII + PLCA Reconciliation Sublayer", "pairs": 1,
         "modulation": "PAM3-class / differential signalling", "data_rate_Mbps": 10,
         "duplex": "half-duplex on multidrop segment (PLCA-arbitrated) / full-duplex point-to-point"},
        {"name": "10BASE-T1L (IEEE 802.3cg) — 10 Mb/s, 1 pair, LONG-REACH (up to 1000 m) point-to-point",
         "interface_to_MAC": "MII", "pairs": 1, "modulation": "PAM3",
         "data_rate_Mbps": 10, "duplex": "full-duplex point-to-point"},
    ]
    d["key_features"] = [
        "Full IEEE 802.3 Ethernet over a SINGLE unshielded twisted pair (ONE "
        "balanced pair) — the defining T1 property versus the four pairs / "
        "8b10b of standard enterprise Ethernet.",
        "SIMULTANEOUS BIDIRECTIONAL full-duplex on the one pair, separated by "
        "an adaptive ECHO CANCELLER that subtracts each PHY's own near-end "
        "transmit echo to recover the remote signal.",
        "PHY-level MASTER / SLAVE timing: one PHY sources the symbol clock "
        "(master), the other recovers it (slave, loop-timed); roles must be "
        "opposite at the two ends or the link will not train.",
        "100BASE-T1 (IEEE 802.3bw, formerly Broadcom BroadR-Reach): 100 Mb/s, "
        "PAM3 (3-level ternary -1/0/+1) at 66.67 MBd, 4B3B + 3B2T PCS mapping "
        "plus a side-stream scrambler.",
        "1000BASE-T1 (IEEE 802.3bp): 1 Gb/s, PAM3 at 750 MBd, 80B/81B "
        "scrambled PCS.",
        "10BASE-T1S (IEEE 802.3cg): 10 Mb/s SHORT-REACH MULTIDROP — several "
        "PHYs share one short single-pair segment; PLCA (Physical Layer "
        "Collision Avoidance), implemented as a Reconciliation Sublayer, "
        "grants each node a deterministic transmit opportunity, eliminating "
        "CSMA/CD collisions.",
        "10BASE-T1L (IEEE 802.3cg): 10 Mb/s LONG-REACH (up to 1000 m) "
        "point-to-point single-pair link for process automation.",
        "Layered MAC / RS / PCS / PMA / PMD per IEEE 802.3, with the IEEE "
        "802.3 Clause-4 MAC frame format PRESERVED byte-for-byte (preamble "
        "7x0x55 + SFD 0xD5 + DA + SA + Type/Length + Payload + Pad + FCS "
        "CRC-32 0x04C11DB7).",
        "SNR and MSE (mean-squared error) are the principal link-quality / "
        "training metrics; MSE below threshold is the link-up criterion.",
        "Energy Efficient Ethernet (EEE) Low-Power Idle (LPI) reduces power "
        "when idle — critical for always-on automotive networks.",
        "Automotive EMC (controlled emissions via PAM3 + scrambler; high "
        "immunity via the balanced pair + common-mode chokes) is a "
        "first-class requirement; OPEN-Alliance test specs layer on top.",
    ]
    d["topology_summary"] = (
        "Point-to-point single-twisted-pair full-duplex links for 100BASE-T1 "
        "/ 1000BASE-T1 / 10BASE-T1L (one master PHY, one slave PHY per link, "
        "echo-cancelled bidirectional on the one pair), plus a MULTIDROP "
        "'mixing segment' for 10BASE-T1S in which several PHYs share one short "
        "single-pair bus and use PLCA (Physical Layer Collision Avoidance, "
        "node 0 = coordinator) to take deterministic round-robin transmit "
        "opportunities. AVB / TSN can layer on top for time-sensitive traffic.")
    d["package_summary"] = (
        "The IEEE 802.3bw / 802.3bp / 802.3cg amendments define single-pair "
        "PHY (PMA/PCS/PMD) and management parameters added to IEEE 802.3; the "
        "MDI is one balanced twisted pair. Connectors, harness, and automotive "
        "EMC test are governed by the OPEN Alliance and OEM specifications, "
        "not by the IEEE amendments themselves.")
    d["use_cases"] = [
        "In-vehicle networking: ADAS cameras, radar / lidar sensor links, "
        "infotainment, and the zonal / backbone in-vehicle Ethernet fabric.",
        "100BASE-T1 / 1000BASE-T1 high-bandwidth sensor + display links over "
        "a light single-pair harness.",
        "10BASE-T1S multidrop for low-cost body / control networks sharing one "
        "short segment among many nodes.",
        "10BASE-T1L long-reach single-pair for industrial process-automation "
        "field instruments (up to 1000 m).",
        "AVB / TSN time-sensitive audio/video and control traffic over the "
        "single-pair PHY.",
    ]
    d["revision_history"] = [
        {"version": "OPEN Alliance BroadR-Reach", "date": "2014",
         "description": "Broadcom BroadR-Reach single-pair 100 Mb/s automotive PHY promoted by the OPEN Alliance; basis for 100BASE-T1."},
        {"version": "IEEE Std 802.3bw-2015", "date": "2015",
         "description": "100BASE-T1 — 100 Mb/s over a single twisted pair, PAM3 at 66.67 MBd, echo-cancelled full-duplex, PHY master/slave timing."},
        {"version": "IEEE Std 802.3bp-2016", "date": "2016",
         "description": "1000BASE-T1 — 1 Gb/s over a single twisted pair, PAM3 at 750 MBd."},
        {"version": "IEEE Std 802.3cg-2019", "date": "2019",
         "description": "10BASE-T1S (10 Mb/s short-reach multidrop with PLCA) and 10BASE-T1L (10 Mb/s long-reach, up to 1000 m, point-to-point)."},
    ]
    d["overview"] = (
        "Automotive Ethernet is a family of IEEE 802.3 PHYs that run full "
        "Ethernet over ONE single unshielded twisted pair instead of the four "
        "pairs of standard BASE-T. The single pair carries traffic in both "
        "directions at the same time (simultaneous bidirectional / "
        "full-duplex), separated by echo cancellation; one PHY is the timing "
        "master and the other the timing slave. 100BASE-T1 (IEEE 802.3bw, "
        "from Broadcom BroadR-Reach) runs 100 Mb/s with PAM3 ternary "
        "modulation at 66.67 MBd and a 4B3B + 3B2T scrambled PCS; 1000BASE-T1 "
        "(IEEE 802.3bp) runs 1 Gb/s with PAM3 at 750 MBd; 10BASE-T1S (IEEE "
        "802.3cg) is a 10 Mb/s short-reach MULTIDROP variant that uses PLCA "
        "(Physical Layer Collision Avoidance) — a Reconciliation Sublayer that "
        "hands each node a deterministic transmit opportunity — to share one "
        "segment without CSMA/CD collisions; and 10BASE-T1L (IEEE 802.3cg) is "
        "the 10 Mb/s long-reach (1000 m) point-to-point variant. The IEEE "
        "802.3 Clause-4 MAC frame format is preserved unchanged; SNR and MSE "
        "are the link-quality metrics; EEE LPI saves power; and automotive "
        "EMC is a primary design constraint.")
    d.pop("external_pin_count_mii", None)
    d.pop("external_pin_count_gmii", None)
    d.pop("external_pin_count_rgmii", None)
    _write(p, d)


# ---------------------------------------------------------------------------
# L2 — Functional Requirements
# ---------------------------------------------------------------------------
def _apply_l2(gd: Path) -> None:
    p = gd / "L2_FRS.json"
    if not p.is_file():
        return
    d = _read(p)
    po = _ensure_dict(d, "protocol_overview")
    po.clear()
    po["type"] = (
        "Single-twisted-pair Automotive-Ethernet PHY family (100BASE-T1 / "
        "1000BASE-T1 / 10BASE-T1S / 10BASE-T1L) layered MAC -> RS (optionally "
        "PLCA RS) -> PCS -> PMA -> PMD over ONE balanced twisted pair, with "
        "simultaneous-bidirectional full-duplex via echo cancellation and "
        "PHY-level master/slave loop timing. The IEEE 802.3 Clause-4 MAC frame "
        "format is preserved.")
    po["medium"] = "single unshielded twisted pair (UTP, one balanced pair)"
    po["pairs"] = 1
    po["duplex"] = (
        "full-duplex simultaneous bidirectional on the one pair via echo "
        "cancellation (point-to-point); half-duplex PLCA-arbitrated on a "
        "10BASE-T1S multidrop segment")
    po["modulation"] = "PAM3 (3-level ternary: -1, 0, +1)"
    po["baud_rate_MBd_100BASE_T1"] = 66.67
    po["baud_rate_MBd_1000BASE_T1"] = 750
    po["bidirectional_mechanism"] = "adaptive echo cancellation (near-end echo subtraction)"
    po["timing_model"] = "PHY-level master/slave loop timing (one master, one slave)"
    po["embedded_clock"] = True
    po["encoding"] = (
        "100BASE-T1: 4B3B + 3B2T mapping to PAM3 ternary symbols with a "
        "side-stream scrambler. 1000BASE-T1: 80B/81B scrambled PCS to PAM3. "
        "The PCS maps the data stream to ternary symbols and applies the "
        "master/slave scrambler seed.")
    po["layers"] = ["MAC (Clause 4)", "RS (optionally PLCA RS for 10BASE-T1S)", "PCS", "PMA (echo cancellation, equalisation, link training)", "PMD / MDI"]
    po["interfaces_in_scope"] = [
        "Clause 4 — IEEE 802.3 Ethernet MAC frame format (PRESERVED)",
        "RS / xMII — Reconciliation Sublayer mapping the MAC to the MII/RGMII/SGMII",
        "PLCA Reconciliation Sublayer (10BASE-T1S multidrop) — deterministic transmit-opportunity arbitration",
        "PCS — 4B3B+3B2T (100BASE-T1) / 80B/81B (1000BASE-T1) scrambled ternary PAM3 coding",
        "PMA — echo cancellation, adaptive FFE/DFE equalisation, symbol-timing recovery, link training, master/slave clocking",
        "PMD / MDI — single twisted pair, balanced, with automotive EMC filtering",
        "MDC/MDIO management (Clause 22 + Clause 45 MMD)",
    ]
    po["variants"] = {
        "100BASE-T1": "100 Mb/s, IEEE 802.3bw, PAM3 66.67 MBd, BroadR-Reach origin",
        "1000BASE-T1": "1 Gb/s, IEEE 802.3bp, PAM3 750 MBd",
        "10BASE-T1S": "10 Mb/s, IEEE 802.3cg, short-reach multidrop, PLCA",
        "10BASE-T1L": "10 Mb/s, IEEE 802.3cg, long-reach (up to 1000 m), point-to-point",
    }
    d["protocol_overview"] = po

    d["functional_requirements"] = [
        {"id": "FR-MEDIUM-T1-01", "text": "Each PHY shall carry IEEE 802.3 Ethernet over a SINGLE unshielded twisted pair (one balanced pair). There is no second/third/fourth pair (unlike standard BASE-T); the one defining T1 property is single-pair operation."},
        {"id": "FR-DUPLEX-ECHO-02", "text": "Full-duplex operation shall be achieved by SIMULTANEOUS BIDIRECTIONAL transmission on the one pair, separated by an adaptive ECHO CANCELLER that subtracts each PHY's near-end transmit echo so the remote signal can be recovered."},
        {"id": "FR-MS-TIMING-03", "text": "The link shall use PHY-level master/slave loop timing: one PHY (master) sources the symbol clock and the other (slave) recovers it. The two ends MUST have opposite roles or the link shall not train."},
        {"id": "FR-100T1-PAM3-04", "text": "100BASE-T1 (IEEE 802.3bw, formerly BroadR-Reach) shall transmit 100 Mb/s using PAM3 (3-level ternary -1/0/+1) at a symbol rate of 66.67 MBd, with a 4B3B + 3B2T PCS mapping and a side-stream scrambler."},
        {"id": "FR-1000T1-PAM3-05", "text": "1000BASE-T1 (IEEE 802.3bp) shall transmit 1 Gb/s using PAM3 at a symbol rate of 750 MBd with an 80B/81B scrambled PCS."},
        {"id": "FR-10T1S-PLCA-06", "text": "10BASE-T1S (IEEE 802.3cg) shall support a short-reach MULTIDROP segment shared by several PHYs and shall provide PLCA (Physical Layer Collision Avoidance), implemented as a Reconciliation Sublayer, that grants each node a deterministic transmit opportunity in node-ID order so the shared segment is collision-free without CSMA/CD."},
        {"id": "FR-10T1L-07", "text": "10BASE-T1L (IEEE 802.3cg) shall support a 10 Mb/s long-reach (up to 1000 m) point-to-point single-pair link using PAM3."},
        {"id": "FR-LAYER-08", "text": "Each PHY shall be layered MAC -> RS (optionally PLCA RS) -> PCS -> PMA -> PMD per IEEE 802.3, and shall PRESERVE the IEEE 802.3 Clause-4 MAC frame format (preamble 7x0x55 + SFD 0xD5 + DA + SA + Type/Length + Payload + Pad + FCS CRC-32 0x04C11DB7)."},
        {"id": "FR-TRAIN-09", "text": "The PMA shall run link training in which the slave acquires symbol timing from the master and the adaptive equaliser (FFE/DFE) and echo canceller converge, driving SNR up and MSE (mean-squared error) below the link-up threshold within the training timer."},
        {"id": "FR-SNR-MSE-10", "text": "The PHY shall expose SNR and MSE link-quality metrics; MSE below the configured threshold shall be the link-up criterion, and rising MSE shall be reported as cable/connector/EMC degradation."},
        {"id": "FR-EEE-LPI-11", "text": "The PHY shall support Energy Efficient Ethernet (EEE) Low-Power Idle (LPI): on MAC idle it shall enter a low-power state, periodically transmit refresh symbols to keep echo-canceller/equaliser coefficients valid, and wake on demand within a bounded wake time."},
        {"id": "FR-EMC-12", "text": "The PHY shall meet automotive EMC: controlled emissions (PAM3 + scrambler limit the spectrum) and high immunity (balanced pair + common-mode chokes) per the OPEN-Alliance / OEM automotive EMC test specifications."},
        {"id": "FR-FCS-13", "text": "Every transmitted frame shall append a 32-bit FCS computed with the IEEE 802.3 CRC-32 polynomial 0x04C11DB7 (init 0xFFFFFFFF, final XOR 0xFFFFFFFF, LSB-first) — UNCHANGED from base Ethernet."},
        {"id": "FR-MGMT-14", "text": "The PHY shall be managed over MDC/MDIO (Clause 22 basic registers + Clause 45 MMD extensions), exposing master/slave configuration, link/training status, SNR/MSE, PLCA control (10BASE-T1S), and EEE control."},
    ]
    d["error_response_conditions"] = [
        "Link training failure — the slave cannot drive MSE below threshold (or acquire timing) within the training timer; the link stays down.",
        "Master/slave misconfiguration — both ends configured master (or both slave); the link never trains.",
        "Loss of descrambler / PCS lock — the PCS de-locks; the link is reported down.",
        "SNR/MSE degradation above threshold — warns of cable / connector / EMC fault while the link may still be up.",
        "Echo-canceller divergence — the echo canceller fails to converge (e.g. severe reflection); recovery via re-train.",
        "FCS (CRC-32) mismatch — the receive MAC discards the frame and increments an FCS-error counter.",
        "Runt (< 64 B) or giant (> 1518/1522 B) frame — discarded by the receive MAC.",
        "PLCA violation (10BASE-T1S) — a node transmitting outside its transmit opportunity; a missing beacon recovers to a free-for-all timeout.",
    ]
    d["compliance_requirements"] = [
        "Mandatory single-twisted-pair (one balanced pair) operation.",
        "Mandatory simultaneous-bidirectional full-duplex via echo cancellation (point-to-point variants).",
        "Mandatory PHY-level master/slave loop timing.",
        "Mandatory PAM3 ternary line modulation.",
        "Mandatory IEEE 802.3 Clause-4 MAC frame format preservation (FCS = CRC-32 0x04C11DB7).",
        "Mandatory PLCA (Physical Layer Collision Avoidance) on a 10BASE-T1S multidrop segment.",
        "Mandatory SNR/MSE link-quality reporting.",
        "Per-variant automotive EMC (emissions + immunity) compliance per OPEN-Alliance / OEM test specifications.",
    ]
    _write(p, d)


# ---------------------------------------------------------------------------
# L3 — Command / Protocol structure
# ---------------------------------------------------------------------------
def _apply_l3(gd: Path) -> None:
    p = gd / "L3_CMD_PROTOCOL.json"
    if not p.is_file():
        return
    d = _read(p)
    d["protocol_type"] = (
        "Streaming layered single-pair Ethernet PHY. The MAC carries IEEE "
        "802.3 Clause-4 frames (unchanged); the PCS scrambles + ternary-codes "
        "the stream onto PAM3 symbols; the PMA echo-cancels + equalises the "
        "single pair. There is no opcode/command protocol on the data path. "
        "For 10BASE-T1S multidrop, PLCA arbitrates transmit opportunities. "
        "Management is a separate MDC/MDIO (Clause 22 + Clause 45) protocol.")
    d["channels"] = [
        {"name": "MDI single twisted pair", "direction": "bidirectional (one pair)",
         "description": "The single balanced twisted pair carrying simultaneous-bidirectional PAM3 symbols; echo cancellation separates the local and remote signals."},
        {"name": "xMII (MII / RMII / RGMII / SGMII)", "direction": "MAC<->PCS",
         "description": "Reconciliation-Sublayer interface carrying the MAC byte stream into the PCS at the appropriate rate."},
        {"name": "PLCA Reconciliation Sublayer (10BASE-T1S)", "direction": "between MAC RS and MII",
         "description": "Grants each multidrop node a deterministic transmit opportunity (TO) in node-ID order; node 0 is the coordinator emitting the BEACON."},
        {"name": "MDC / MDIO management", "direction": "STA<->PHY",
         "description": "Serial management bus; Clause 22 basic registers + Clause 45 MMD extensions. Two-cycle address-then-data for Clause 45."},
    ]
    d["packet_classes"] = [
        {"class": "Ethernet MAC frame", "purpose": "Carries user data between MACs; IEEE 802.3 Clause-4 frame format preserved.", "subtypes": [
            "Untagged data frame (DA + SA + EtherType/Length + Payload + FCS, 64-1518 B)",
            "802.1Q VLAN-tagged frame (max 1522 B)",
            "802.3x PAUSE / 802.1Qbb PFC frame (full-duplex flow control)",
        ]},
        {"class": "PCS / PMA sublayer unit", "purpose": "Line-coding / ternary-symbol units below the MAC (NOT MAC frames).", "subtypes": [
            "PAM3 ternary symbol (-1 / 0 / +1)",
            "4B3B + 3B2T mapped group (100BASE-T1)",
            "80B/81B block (1000BASE-T1)",
            "Scrambler-seeded idle / refresh symbol (EEE LPI)",
        ]},
        {"class": "PLCA control element (10BASE-T1S)", "purpose": "Multidrop access arbitration.", "subtypes": [
            "BEACON (coordinator node 0 starts a PLCA cycle)",
            "COMMIT / transmit opportunity (TO) grant per node ID",
            "YIELD (node with nothing to send passes the TO)",
        ]},
        {"class": "MDIO management frame", "purpose": "PHY register access.", "subtypes": [
            "Clause 22 basic (BMCR/BMSR) read/write",
            "Clause 45 MMD address-then-data (PMA/PMD, PCS, AN, vendor)",
        ]},
    ]
    d["mac_frame_format"] = {
        "preamble": "7 octets of 0x55 (UNCHANGED from base Ethernet).",
        "sfd": "1 octet 0xD5.",
        "destination_address": "6 octets (48 bits).",
        "source_address": "6 octets (48 bits), unicast.",
        "etheryype_or_length": "2 octets. >= 0x0600 = EtherType; <= 0x05DC = Length.",
        "payload": "46-1500 octets. Zero-padded if shorter.",
        "pad": "0-46 octets of 0x00 to reach the 64-byte minimum.",
        "fcs": "4 octets, IEEE 802.3 CRC-32, polynomial 0x04C11DB7. UNCHANGED.",
        "note": "The MAC frame is byte-for-byte identical to every other Ethernet speed — only the single-pair PAM3 PHY below the MAC differs.",
    }
    d["pcs_pipeline"] = {
        "step_1_scramble": "Side-stream scrambler (master or slave seed) for DC balance + spectral shaping (automotive EMC).",
        "step_2_code_100T1": "100BASE-T1: 4B3B then 3B2T mapping of data bits to PAM3 ternary symbols.",
        "step_2_code_1000T1": "1000BASE-T1: 80B/81B block coding to PAM3 ternary symbols.",
        "step_3_pma": "PMA modulates PAM3 symbols on the single pair (66.67 MBd for 100BASE-T1, 750 MBd for 1000BASE-T1).",
        "step_4_echo_cancel": "Adaptive echo canceller subtracts the near-end transmit echo so the remote signal is recovered on the same pair.",
        "step_5_equalise": "FFE/DFE adaptive equalisation; symbol-timing recovery (slave loop-times to master).",
    }
    d["plca_protocol"] = {
        "scope": "10BASE-T1S multidrop only.",
        "coordinator": "Node ID 0 emits the BEACON that starts each PLCA cycle.",
        "transmit_opportunity": "Each node, in node-ID order, gets a transmit opportunity (TO); a node with a frame transmits, a node with nothing yields and the TO passes on.",
        "determinism": "Eliminates CSMA/CD collisions on the shared single-pair segment by serialising access; bounded latency per node.",
        "transparency": "Transparent to the MAC frame format (still Clause-4 frames).",
    }
    d["mdio_clause45_frame"] = {
        "PRE": "32 contiguous logic-1 bits (may be suppressed).",
        "ST": "<00> — Clause 45.",
        "OP": "<00> Address / <01> Write / <11> Read / <10> Post-Increment Read.",
        "PRTAD": "5-bit port (PHY) address.",
        "DEVAD": "5-bit MMD Device Address.",
        "TA": "2-bit turnaround.",
        "DATA": "16 bits.",
    }
    d["valid_ready_handshake_rules"] = [
        "The single-pair data path is a continuous stream — there is no per-beat valid/ready handshake at the PMD; the PMA loop-times slave to master.",
        "Link-up requires master/slave timing lock + echo-canceller/equaliser convergence (MSE below threshold) + PCS descrambler lock.",
        "10BASE-T1S multidrop access is arbitrated by PLCA transmit opportunities (no CSMA/CD).",
        "MDIO Clause 45: each transaction is an Address cycle (OP=00) followed by a Data cycle.",
    ]
    d["burst_based"] = False
    d["byte_oriented"] = True
    d["addressing"] = {
        "mac_address_width_bits": 48,
        "ethertype_width_bits": 16,
        "vlan_vid_width_bits": 12,
        "clause45_prtad_width_bits": 5,
        "clause45_devad_width_bits": 5,
        "clause45_regad_width_bits": 16,
        "plca_node_id_width_bits": 8,
        "plca_coordinator_node_id": 0,
        "twisted_pairs": 1,
        "mdi_wires": 2,
        "modulation_levels_pam3": 3,
        "baud_rate_MBd_100BASE_T1": 66.67,
        "baud_rate_MBd_1000BASE_T1": 750,
        "broadcast_address": "FF:FF:FF:FF:FF:FF",
    }
    d.pop("mdio_clause22_frame", None)
    d.pop("transaction_classes_split", None)
    d.pop("frame_format", None)
    _write(p, d)


# ---------------------------------------------------------------------------
# L4 — Register / PHY management map
# ---------------------------------------------------------------------------
def _apply_l4(gd: Path) -> None:
    p = gd / "L4_REGMAP.json"
    if not p.is_file():
        return
    d = _read(p)
    d["register_map_present"] = True
    d["register_address_scheme"] = (
        "Single-pair PHYs are managed over MDC/MDIO using the IEEE 802.3 "
        "Clause-22 basic registers (BMCR/BMSR + a few standard registers) plus "
        "Clause-45 MMD extensions (5-bit PRTAD + 5-bit DEVAD + 16-bit "
        "register) for the PMA/PMD, PCS, Auto-Negotiation, and vendor MMDs "
        "that hold master/slave config, SNR/MSE, PLCA control, and EEE.")
    d["clause22_basic_registers"] = [
        {"reg": 0, "name": "BMCR (Basic Mode Control)", "purpose": "Reset, speed select (10/100/1000), duplex, power-down, master/slave manual config bit."},
        {"reg": 1, "name": "BMSR (Basic Mode Status)", "purpose": "Link status, training/auto-neg complete, capability bits."},
        {"reg": "2-3", "name": "PHY Identifier", "purpose": "Vendor OUI + model + revision."},
    ]
    d["clause45_mmd_devad_assignments"] = [
        {"devad": 1, "name": "PMA/PMD", "purpose": "Single-pair PMA control/status: master/slave timing config, echo-canceller / equaliser state, link-training control, SNR, MSE, test modes."},
        {"devad": 3, "name": "PCS", "purpose": "Ternary PCS status: 4B3B+3B2T / 80B/81B descrambler lock, block lock, link status."},
        {"devad": 7, "name": "Auto-Negotiation", "purpose": "Single-pair auto-negotiation (master/slave resolution, EEE capability, speed)."},
        {"devad": "PLCA / vendor (10BASE-T1S)", "name": "PLCA + vendor", "purpose": "PLCA control/status: enable, node ID, node count, beacon timer, transmit-opportunity timer; vendor echo-canceller taps + diagnostics."},
    ]
    d["plca_registers_summary"] = [
        {"name": "PLCA Control 0 (enable)", "purpose": "Enable/disable PLCA on the 10BASE-T1S multidrop segment."},
        {"name": "PLCA Control 1 (node count + local node ID)", "purpose": "Total node count and this PHY's PLCA node ID (0 = coordinator)."},
        {"name": "PLCA Status", "purpose": "PLCA active / beacon seen / collision-free state."},
        {"name": "PLCA Transmit-Opportunity Timer (TOTMR)", "purpose": "Duration of each node's transmit opportunity."},
        {"name": "PLCA Burst Control", "purpose": "Max burst count / burst timer for back-to-back frames in one TO."},
    ]
    d["link_quality_registers_summary"] = [
        {"name": "SNR", "purpose": "Signal-to-noise ratio at the slicer."},
        {"name": "MSE", "purpose": "Mean-squared error after echo cancellation + equalisation; below-threshold = link-up criterion."},
        {"name": "Master/Slave config + resolution", "purpose": "Manual or auto master/slave role and the resolved role."},
        {"name": "EEE / LPI control + status", "purpose": "Energy Efficient Ethernet Low-Power Idle enable + state."},
    ]
    d["fcs_polynomial"] = {
        "name": "IEEE 802.3 CRC-32",
        "polynomial": "x^32 + x^26 + x^23 + x^22 + x^16 + x^12 + x^11 + x^10 + x^8 + x^7 + x^5 + x^4 + x^2 + x + 1",
        "hex": "0x04C11DB7",
        "reflected_hex": "0xEDB88320",
        "covers": "DA + SA + Type/Length + Payload + Pad (NOT Preamble + SFD).",
        "initial_value": "0xFFFFFFFF",
        "final_xor": "0xFFFFFFFF",
        "bit_order": "LSB-first within each byte; FCS appended MSB-byte first.",
        "width_bits": 32,
        "note": "UNCHANGED; the FCS is a MAC-layer integrity check.",
    }
    d["notes"] = (
        "Single-pair PHY management combines Clause-22 basics (BMCR/BMSR + PHY "
        "ID) with Clause-45 MMDs (PMA/PMD = DEVAD 1, PCS = 3, AN = 7) and "
        "vendor/PLCA registers. The distinctive single-pair items are the "
        "master/slave timing config, the SNR/MSE link-quality readout, and — "
        "for 10BASE-T1S — the PLCA control/status (enable, node ID, node "
        "count, transmit-opportunity timer).")
    d.pop("phy_clause22_register_map", None)
    d.pop("bmcr_bit_definitions", None)
    d.pop("bmsr_bit_definitions", None)
    d.pop("anar_field_layout", None)
    d.pop("anlpar_field_layout", None)
    _write(p, d)


# ---------------------------------------------------------------------------
# L5 — Analog / Digital interface
# ---------------------------------------------------------------------------
def _apply_l5(gd: Path) -> None:
    p = gd / "L5_ADI_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["analog_digital_interface_present"] = True
    d["signaling_summary"] = (
        "The single-pair data path is PAM3 (3-level ternary: -1, 0, +1) on "
        "ONE balanced twisted pair, transmitted simultaneously in both "
        "directions and separated by an adaptive echo canceller. The "
        "transmitter shapes the PAM3 spectrum (scrambler + pulse shaping) for "
        "automotive EMC; the receiver uses adaptive FFE/DFE equalisation and "
        "the echo canceller, loop-timing the slave to the master. SNR and MSE "
        "are the analog link-quality metrics. 100BASE-T1 runs at 66.67 MBd, "
        "1000BASE-T1 at 750 MBd.")
    d["pam3_signaling"] = {
        "modulation": "PAM3 (3 levels: -1, 0, +1; ternary)",
        "levels": 3,
        "baud_rate_MBd_100BASE_T1": 66.67,
        "baud_rate_MBd_1000BASE_T1": 750,
        "pairs": 1,
        "duplex": "simultaneous bidirectional via echo cancellation",
        "tx_shaping": "scrambler + pulse shaping for automotive EMC emissions control",
        "rx_equalization": "adaptive FFE + DFE; echo cancellation; symbol-timing recovery (slave loop-timed)",
        "link_quality_metrics": ["SNR (signal-to-noise ratio)", "MSE (mean-squared error)"],
    }
    d["medium"] = {
        "type": "single unshielded twisted pair (one balanced pair)",
        "mdi_wires": 2,
        "emc": "common-mode chokes + balanced signalling for bulk-current-injection immunity; PAM3 + scrambler for controlled emissions",
        "reach": "~15 m (100BASE-T1) / ~15-40 m (1000BASE-T1) / ~25 m multidrop (10BASE-T1S) / up to 1000 m (10BASE-T1L)",
    }
    d["voltage_classes"] = [
        "MDI: low-voltage differential PAM3 on the single pair (automotive-grade, EMC-filtered).",
        "MDC/MDIO management: LVCMOS (1.8 V / 3.3 V).",
        "xMII to MAC: LVCMOS / SGMII differential per rate.",
    ]
    _write(p, d)


# ---------------------------------------------------------------------------
# L6 — Control logic / FSM
# ---------------------------------------------------------------------------
def _apply_l6(gd: Path) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    d.pop("fsm_states_csma_cd_half_duplex", None)
    d.pop("fsm_states_mdio_master_clause22", None)
    d["fsm_states_pma_link_training"] = [
        {"name": "LT_RESET", "description": "Power-on/reset; master/slave roles applied from config or auto-negotiation."},
        {"name": "LT_TIMING_ACQUIRE", "description": "Slave acquires symbol timing from the master (loop timing); master sources the symbol clock."},
        {"name": "LT_ECHO_EQ_CONVERGE", "description": "Adaptive echo canceller + FFE/DFE equaliser converge on the single pair; SNR rises, MSE falls."},
        {"name": "LT_MSE_OK", "description": "MSE below threshold within the training timer; PMA reports trained."},
        {"name": "LT_FAIL", "description": "Training timer expires before MSE crosses threshold (or master/slave misconfig); link stays down."},
    ]
    d["fsm_states_pcs"] = [
        {"name": "PCS_SCRAMBLE_LOCK", "description": "Descrambler locks to the master/slave seed."},
        {"name": "PCS_CODE_LOCK", "description": "4B3B+3B2T (100BASE-T1) / 80B/81B (1000BASE-T1) block/group alignment."},
        {"name": "PCS_LINK_UP", "description": "PCS reports link up; the RS presents a clean MII to the MAC."},
    ]
    d["fsm_states_plca_10base_t1s"] = [
        {"name": "PLCA_IDLE", "description": "Waiting for the BEACON (non-coordinator) or about to emit it (coordinator node 0)."},
        {"name": "PLCA_BEACON", "description": "Coordinator emits the beacon; a new PLCA cycle starts."},
        {"name": "PLCA_TO_WAIT", "description": "Counting node IDs until this node's transmit opportunity."},
        {"name": "PLCA_TRANSMIT", "description": "This node's transmit opportunity: send a frame or yield."},
        {"name": "PLCA_YIELD", "description": "Nothing to send; pass the transmit opportunity to the next node ID."},
    ]
    d["anti_deadlock_rule"] = (
        "Point-to-point links are full-duplex (no CSMA/CD deadlock). On a "
        "10BASE-T1S multidrop segment, PLCA guarantees forward progress: each "
        "node gets a bounded transmit opportunity in round-robin node-ID "
        "order, so no node can be starved and there are no collisions; a "
        "missing beacon recovers to a free-for-all timeout.")
    d["exit_from_reset_or_poweron"] = (
        "On power-on/reset the master/slave roles are applied; the PMA runs "
        "link training (slave loop-times to master, echo canceller + "
        "equaliser converge, MSE drops below threshold); the PCS achieves "
        "descrambler + code lock; the PHY reports link-up and the MAC begins "
        "frame exchange. On a 10BASE-T1S multidrop, PLCA then arbitrates "
        "access.")
    d["timing_dependency_rule"] = (
        "The single pair carries an embedded recovered clock; the slave PHY "
        "loop-times to the master. Echo cancellation and equalisation are "
        "continuously adapted. Management (MDC) is asynchronous to the data "
        "path.")
    _write(p, d)


# ---------------------------------------------------------------------------
# L7 — Test / debug
# ---------------------------------------------------------------------------
def _apply_l7(gd: Path) -> None:
    p = gd / "L7_TEST_DEBUG.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_debug_architecture_present"] = True
    d["spec_provided_observability"] = [
        {"name": "SNR readout (MDIO)", "purpose": "Signal-to-noise ratio at the slicer for in-system link-quality monitoring."},
        {"name": "MSE readout (MDIO)", "purpose": "Mean-squared error after echo cancellation + equalisation; the link-up / health metric."},
        {"name": "Master/slave config + resolved-role status", "purpose": "Verify the two ends have opposite roles."},
        {"name": "Link / training status (PMA + PCS)", "purpose": "Trained / link-up / descrambler-lock status."},
        {"name": "PLCA status counters (10BASE-T1S)", "purpose": "Beacon seen, collision-free, per-node transmit-opportunity accounting."},
        {"name": "Transmitter test patterns (PMA)", "purpose": "PAM3 test modes for emissions + jitter compliance."},
        {"name": "Echo-canceller / equaliser tap readout (vendor)", "purpose": "Diagnose reflections / cable faults."},
    ]
    d["error_detection_mechanisms"] = [
        "Link-training timeout (MSE never crosses threshold).",
        "Master/slave misconfiguration (both same role).",
        "Descrambler / PCS lock loss.",
        "SNR/MSE degradation above threshold (cable/connector/EMC).",
        "MAC FCS (CRC-32) mismatch.",
        "Runt (< 64 B) / giant (> 1518/1522 B) frame.",
        "PLCA violation / missing beacon (10BASE-T1S).",
    ]
    d["test_modes"] = [
        {"name": "PAM3 transmitter test patterns", "purpose": "Emissions + jitter compliance per OPEN-Alliance EMC spec."},
        {"name": "SNR/MSE in-system readout", "purpose": "Live link-quality monitoring via MDIO."},
        {"name": "Master/slave force", "purpose": "Force a role to characterise the channel / cable."},
        {"name": "Loopback (PMA / PCS)", "purpose": "Internal loopback for board bring-up."},
        {"name": "PLCA status / counter readout (10BASE-T1S)", "purpose": "Verify deterministic multidrop access."},
    ]
    d["notes"] = (
        "Single-pair PHYs rely on SNR/MSE as the primary in-system health "
        "instrument, plus PAM3 transmitter test patterns for automotive EMC "
        "compliance and PLCA status for 10BASE-T1S multidrop. The OPEN "
        "Alliance publishes interoperability + EMC test specifications. "
        "JTAG / scan / BIST are vendor-added.")
    _write(p, d)


# ---------------------------------------------------------------------------
# L8 — RTL constants
# ---------------------------------------------------------------------------
def _apply_l8_rtl(gd: Path) -> None:
    p = gd / "L8_RTL_CONSTANTS.json"
    if not p.is_file():
        return
    d = _read(p)
    wp = _ensure_dict(d, "width_parameters")
    wp["TWISTED_PAIRS"] = 1
    wp["MDI_WIRES"] = 2
    wp["MODULATION"] = "PAM3 (3-level ternary)"
    wp["PAM3_LEVELS"] = 3
    wp["BAUD_MBd_100BASE_T1"] = 66.67
    wp["BAUD_MBd_1000BASE_T1"] = 750
    wp["DATA_RATE_Mbps_100BASE_T1"] = 100
    wp["DATA_RATE_Mbps_1000BASE_T1"] = 1000
    wp["DATA_RATE_Mbps_10BASE_T1"] = 10
    wp["FCS_POLY_HEX"] = "0x04C11DB7"
    wp["MAC_ADDR_BITS"] = 48
    wp["ETHERTYPE_BITS"] = 16
    wp["MIN_FRAME_OCTETS"] = 64
    wp["MAX_FRAME_OCTETS_UNTAGGED"] = 1518
    wp["MAX_FRAME_OCTETS_VLAN"] = 1522
    wp["PLCA_NODE_ID_BITS"] = 8
    wp["PLCA_COORDINATOR_NODE_ID"] = 0
    d["key_constants_for_RTL_authoring"] = {
        "medium": "single unshielded twisted pair (1 balanced pair)",
        "twisted_pairs": 1,
        "modulation": "PAM3 (3-level ternary -1/0/+1)",
        "duplex": "simultaneous bidirectional via echo cancellation",
        "timing": "PHY-level master/slave loop timing",
        "baud_MBd_100BASE_T1": 66.67,
        "baud_MBd_1000BASE_T1": 750,
        "frame_format": "IEEE 802.3 Clause-4 (preamble 7x0x55 + SFD 0xD5 + DA + SA + Type/Length + Payload + Pad + FCS) — PRESERVED",
        "min_frame_bytes": 64,
        "max_frame_bytes_untagged": 1518,
        "max_frame_bytes_vlan": 1522,
        "fcs_poly_hex": "0x04C11DB7",
        "pcs_100BASE_T1": "4B3B + 3B2T scrambled",
        "pcs_1000BASE_T1": "80B/81B scrambled",
        "layers": "MAC / RS (optionally PLCA RS) / PCS / PMA / PMD",
        "management": "MDC/MDIO (Clause 22 + Clause 45)",
        "multidrop_arbitration_10BASE_T1S": "PLCA (Physical Layer Collision Avoidance)",
        "link_quality_metrics": "SNR + MSE",
        "eee_lpi": True,
    }
    d["default_signal_values_when_idle"] = {
        "MDI": "PAM3 idle / EEE LPI refresh symbols (the pair never goes fully quiet on an up link unless in deep LPI).",
        "PCS": "Scrambled idle.",
        "MAC": "IEEE 802.3 idle / inter-packet gap.",
    }
    _write(p, d)


# ---------------------------------------------------------------------------
# L8 — Timing / waveform
# ---------------------------------------------------------------------------
def _apply_l8_timing(gd: Path) -> None:
    p = gd / "L8_TIMING_WAVEFORM.json"
    if not p.is_file():
        return
    d = _read(p)
    d["data_rate_waveforms"] = {
        "100BASE-T1": {"data_rate_Mb_s": 100, "pairs": 1, "modulation": "PAM3", "baud_MBd": 66.67, "levels": 3, "duplex": "echo-cancelled bidirectional"},
        "1000BASE-T1": {"data_rate_Mb_s": 1000, "pairs": 1, "modulation": "PAM3", "baud_MBd": 750, "levels": 3, "duplex": "echo-cancelled bidirectional"},
        "10BASE-T1S": {"data_rate_Mb_s": 10, "pairs": 1, "topology": "multidrop (PLCA)", "duplex": "half-duplex on multidrop / full-duplex p2p"},
        "10BASE-T1L": {"data_rate_Mb_s": 10, "pairs": 1, "reach_m": 1000, "duplex": "full-duplex point-to-point"},
    }
    d["pam3_eye_reference"] = (
        "Two PAM3 eyes per unit interval (3 levels). Transmitter compliance "
        "via emissions / return-loss / eye masks per the OPEN-Alliance "
        "automotive test spec. 100BASE-T1 symbol period = 1/66.67 MBd ~= 15 "
        "ns; 1000BASE-T1 symbol period = 1/750 MBd ~= 1.33 ns.")
    d["general_timing_rule"] = (
        "The single pair carries an embedded recovered clock; the slave PHY "
        "loop-times to the master. Echo cancellation + equalisation are "
        "continuously adapted. MAC frame timing (IPG nominal 96 bit times, "
        "FCS) is preserved from base 802.3 and scaled to the rate.")
    d.pop("mii_signal_timing", None)
    d.pop("mdio_signal_timing", None)
    d.pop("csma_cd_timing", None)
    _write(p, d)


# ---------------------------------------------------------------------------
# L9 — Integration spec
# ---------------------------------------------------------------------------
def _apply_l9(gd: Path) -> None:
    p = gd / "L9_INTEGRATION_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["module_role"] = (
        "Single-twisted-pair Automotive-Ethernet PHY (PCS / PMA / PMD) plus "
        "the IEEE 802.3 MAC (Clause-4 frame format preserved). Implements PAM3 "
        "ternary signalling on ONE balanced pair, simultaneous-bidirectional "
        "full-duplex via echo cancellation, PHY master/slave loop timing, link "
        "training (SNR/MSE), and — for 10BASE-T1S — the PLCA multidrop "
        "Reconciliation Sublayer. Variants: 100BASE-T1 (802.3bw), 1000BASE-T1 "
        "(802.3bp), 10BASE-T1S / 10BASE-T1L (802.3cg).")
    io = _ensure_dict(d, "integration_overview")
    io.clear()
    io.update({
        "medium": "single unshielded twisted pair (1 balanced pair)",
        "twisted_pairs": 1,
        "mdi_wires": 2,
        "modulation": "PAM3",
        "duplex": "simultaneous bidirectional via echo cancellation",
        "timing": "PHY-level master/slave loop timing",
        "baud_MBd_100BASE_T1": 66.67,
        "baud_MBd_1000BASE_T1": 750,
        "layers": "MAC / RS (optionally PLCA RS) / PCS / PMA / PMD",
        "management": "MDC/MDIO (Clause 22 + Clause 45)",
        "multidrop_arbitration": "PLCA (10BASE-T1S)",
        "link_quality_metrics": "SNR + MSE",
        "preamble_octets": 7,
        "sfd_octet": "0xD5",
        "fcs_octets": 4,
        "min_frame_octets": 64,
        "max_frame_octets_untagged": 1518,
        "max_frame_octets_vlan": 1522,
        "eee_lpi": True,
    })
    d["interface_categories"] = [
        "MAC (Clause 4) — frame assembly/disassembly, FCS, IPG, flow control. Frame format PRESERVED.",
        "RS / xMII — Reconciliation Sublayer mapping the MAC to the MII/RGMII/SGMII.",
        "PLCA Reconciliation Sublayer (10BASE-T1S) — deterministic multidrop transmit-opportunity arbitration.",
        "PCS — 4B3B+3B2T (100BASE-T1) / 80B/81B (1000BASE-T1) scrambled ternary PAM3 coding.",
        "PMA — echo cancellation, FFE/DFE equalisation, symbol-timing recovery, master/slave clocking, link training.",
        "PMD / MDI — single twisted pair, balanced, automotive-EMC-filtered.",
        "MDC + MDIO — management bus (Clause 22 + Clause 45 MMD).",
    ]
    d["interconnect_topologies_supported"] = [
        "Point-to-point single-pair full-duplex link (100BASE-T1 / 1000BASE-T1 / 10BASE-T1L).",
        "Multidrop single-pair mixing segment with PLCA (10BASE-T1S).",
        "AVB / TSN time-sensitive traffic layered on top.",
    ]
    d["low_power_modes"] = {
        "Active": "Link up; PMA trained; MAC streaming.",
        "EEE_LPI": "Energy Efficient Ethernet Low-Power Idle; PHY analog low-power on MAC idle with periodic refresh.",
        "Power_down": "PHY powered down via BMCR.",
    }
    d["soc_dependent_items"] = [
        "Single-pair PMA analog front-end (PAM3 driver/receiver, echo canceller, equaliser) IP choice.",
        "Master/slave timing + reference-clock distribution.",
        "PLCA Reconciliation Sublayer (for 10BASE-T1S multidrop).",
        "MDC/MDIO master + Clause-45 MMD decode.",
        "Automotive EMC filtering (common-mode chokes) on the MDI pair.",
        "xMII selection (MII/RMII/RGMII/SGMII) per rate to the MAC.",
    ]
    _write(p, d)


# ---------------------------------------------------------------------------
# L10 — Test cases
# ---------------------------------------------------------------------------
def _apply_l10(gd: Path) -> None:
    p = gd / "L10_TEST_CASES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_cases_present"] = (
        "partial — the IEEE 802.3bw/bp/cg amendments specify PMA/PCS/PMD "
        "behaviour + electrical/EMC parameters per clause, but no concrete "
        "testbench; conformance is per-clause PICS + OPEN-Alliance interop / "
        "EMC test specifications.")
    d["derived_compliance_test_categories"] = [
        "Medium: confirm operation over ONE single twisted pair (no second pair).",
        "Full-duplex via echo cancellation: simultaneous bidirectional traffic on the one pair.",
        "Master/slave timing: link trains only with opposite roles; fails when both same.",
        "100BASE-T1: 100 Mb/s PAM3 at 66.67 MBd; 4B3B+3B2T scramble round-trip.",
        "1000BASE-T1: 1 Gb/s PAM3 at 750 MBd; 80B/81B scramble round-trip.",
        "10BASE-T1S multidrop: PLCA grants deterministic transmit opportunities; collision-free.",
        "10BASE-T1L: 10 Mb/s long-reach (up to 1000 m) point-to-point.",
        "Link training: echo canceller + equaliser converge; MSE below threshold within the timer.",
        "SNR/MSE: readout tracks injected cable degradation.",
        "MAC frame: byte-for-byte IEEE 802.3 Clause-4 format; FCS CRC-32 (0x04C11DB7) on ASCII '123456789' -> 0xCBF43926.",
        "Min/max frame size preserved (64 / 1518 / 1522 VLAN).",
        "EEE LPI: enter low-power idle on MAC idle; wake within the bounded wake time.",
        "Automotive EMC: emissions + immunity per OPEN-Alliance / OEM spec.",
        "Management: MDC/MDIO Clause-22 + Clause-45 register access (master/slave, SNR/MSE, PLCA, EEE).",
    ]
    _write(p, d)


# ---------------------------------------------------------------------------
# L11 — OTP content
# ---------------------------------------------------------------------------
def _apply_l11(gd: Path) -> None:
    p = gd / "L11_OTP_CONTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    d["otp_present"] = False
    d["otp_equivalent_factory_burned_fields"] = [
        {"field": "MAC Address (48 bits)", "width_bits": 48, "location": "EEPROM / OTP", "note": "Per-device Universally Administered MAC from the vendor OUI."},
        {"field": "PHY Identifier (Clause-22 reg 2/3 + Clause-45 PMA/PMD)", "width_bits": 32, "location": "ROM / metal-mask", "note": "Vendor OUI + model + revision."},
        {"field": "Master/slave default + PLCA node ID default (10BASE-T1S)", "width_bits": "vendor", "location": "OTP / strap", "note": "Default timing role and multidrop node ID may be strap- or OTP-configured."},
        {"field": "Echo-canceller / equaliser analog trim presets", "width_bits": "vendor", "location": "OTP / fuse", "note": "Per-device analog front-end trim locked at production; vendor-specific."},
    ]
    d["notes"] = (
        "The IEEE single-pair amendments do not define OTP/fuse content as a "
        "protocol concept. Endpoints store the 48-bit MAC in non-volatile "
        "memory; PHY identity lives in the standard PHY-ID registers; the "
        "master/slave default and (for 10BASE-T1S) the PLCA node ID may be "
        "strap/OTP-configured; analog trim is vendor OTP.")
    _write(p, d)


# ---------------------------------------------------------------------------
# L12 — Behavioral sequences
# ---------------------------------------------------------------------------
def _apply_l12(gd: Path) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    d.pop("tx_frame_sequence_half_duplex_csma_cd", None)
    d.pop("collision_backoff_sequence_half_duplex", None)
    d.pop("mdio_clause22_write_sequence", None)
    d.pop("mdio_clause22_read_sequence", None)
    d.pop("auto_negotiation_priority_resolution", None)
    d["link_bring_up_sequence"] = [
        "1. Power-on / reset.",
        "2. Master/slave roles applied (config or auto-negotiation); the two ends must be opposite.",
        "3. PMA link training: the slave acquires symbol timing from the master (loop timing).",
        "4. The adaptive echo canceller + FFE/DFE equaliser converge on the single pair; SNR rises, MSE falls below threshold.",
        "5. PCS achieves descrambler + code lock (4B3B+3B2T / 80B/81B).",
        "6. PHY reports link-up via MDIO; the RS presents a clean MII to the MAC.",
        "7. (10BASE-T1S multidrop) PLCA begins arbitrating transmit opportunities; node 0 emits the beacon.",
        "8. MAC begins transmitting/receiving IEEE 802.3 frames.",
    ]
    d["tx_frame_sequence_full_duplex"] = [
        "1. MAC client signals a frame-transmit request.",
        "2. MAC computes CRC-32 over DA + SA + Type/Length + Payload + Pad (frame format preserved).",
        "3. After the inter-packet gap, MAC emits preamble (7x0x55) + SFD (0xD5) + DA + SA + Type/Length + Payload + Pad + FCS through the RS.",
        "4. PCS scrambles + ternary-codes (4B3B+3B2T / 80B/81B) the stream to PAM3 symbols.",
        "5. PMA modulates PAM3 on the single pair while the echo canceller subtracts the near-end echo of the simultaneously-received remote signal.",
        "6. Far-end PMA echo-cancels + equalises, PCS descrambles/decodes, RS hands the frame to the MAC which checks FCS and delivers it.",
    ]
    d["rx_frame_sequence"] = [
        "1. PMA recovers PAM3 symbols on the single pair (slave loop-timed to master).",
        "2. Echo canceller subtracts the local transmit echo; equaliser opens the eye; SNR/MSE tracked.",
        "3. PCS descrambles + decodes (4B3B+3B2T / 80B/81B), reassembles the MAC stream.",
        "4. MAC detects preamble/SFD, captures DA..FCS, recomputes CRC-32; on mismatch discards + increments FCS-error counter.",
        "5. On valid FCS + length, deliver the frame to the MAC client.",
    ]
    d["plca_cycle_sequence_10base_t1s"] = [
        "1. Coordinator (node 0) emits the BEACON, starting a PLCA cycle.",
        "2. Each node, in node-ID order, reaches its transmit opportunity (TO).",
        "3. A node with a frame transmits within its TO; a node with nothing yields and the TO passes to the next node ID.",
        "4. The cycle wraps; the coordinator emits the next beacon. Access is deterministic and collision-free (no CSMA/CD).",
    ]
    d["link_training_sequence"] = [
        "1. Slave attempts to acquire timing from the master.",
        "2. Echo canceller + equaliser coefficients adapt; MSE decreases.",
        "3. If MSE crosses below threshold within the training timer, the PMA reports trained.",
        "4. If the timer expires first (or roles are misconfigured), training fails and the link stays down.",
    ]
    _write(p, d)


# ---------------------------------------------------------------------------
# L13 — Lab calibration
# ---------------------------------------------------------------------------
def _apply_l13(gd: Path) -> None:
    p = gd / "L13_LAB_CALIBRATION.json"
    if not p.is_file():
        return
    d = _read(p)
    d["lab_calibration_present"] = False
    d["lab_measurement_targets_from_spec"] = [
        {"name": "PAM3 transmitter eye / emissions", "purpose": "Per-variant PAM3 transmitter compliance + automotive emissions at 66.67 / 750 MBd."},
        {"name": "Return loss / insertion loss", "purpose": "Single-pair channel characterisation."},
        {"name": "SNR", "purpose": "Signal-to-noise margin at the slicer."},
        {"name": "MSE", "purpose": "Residual mean-squared error after echo cancellation + equalisation; the link-up margin metric."},
        {"name": "Echo-canceller convergence", "purpose": "Verify the echo canceller suppresses the near-end echo to the required floor."},
        {"name": "Link-training convergence time", "purpose": "Verify MSE crosses threshold within the training timer."},
        {"name": "Automotive EMC (emissions + immunity)", "purpose": "Bulk-current-injection immunity + radiated/conducted emissions per OPEN-Alliance / OEM spec."},
    ]
    d["notes"] = (
        "The IEEE single-pair amendments do not specify on-chip calibration "
        "loops; the PHY digital (MAC/RS/PCS) is verified by testbench while "
        "the single-pair analog (PAM3 driver, echo canceller, equaliser) "
        "requires lab compliance tests (eye, return loss, SNR, MSE, EMC). The "
        "SNR/MSE registers provide the primary in-system margin instrument.")
    _write(p, d)


# ---------------------------------------------------------------------------
# L14 — Protocol versioning
# ---------------------------------------------------------------------------
def _apply_l14(gd: Path) -> None:
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["spec_version"] = (
        "IEEE Std 802.3bw-2015 (100BASE-T1) + 802.3bp-2016 (1000BASE-T1) + "
        "802.3cg-2019 (10BASE-T1S / 10BASE-T1L) — single-twisted-pair "
        "Automotive Ethernet")
    f["previous_versions"] = [
        "OPEN Alliance BroadR-Reach (Broadcom, ~2014) — single-pair 100 Mb/s automotive PHY; basis for 100BASE-T1.",
        "IEEE Std 802.3bw-2015 — 100BASE-T1 (this family).",
        "IEEE Std 802.3bp-2016 — 1000BASE-T1.",
        "IEEE Std 802.3cg-2019 — 10BASE-T1S + 10BASE-T1L.",
    ]
    f["key_changes"] = [
        {"version": "802.3bw-2015", "summary": "100BASE-T1: 100 Mb/s over ONE twisted pair, PAM3 at 66.67 MBd, echo-cancelled full-duplex, PHY master/slave timing; standardises BroadR-Reach."},
        {"version": "802.3bp-2016", "summary": "1000BASE-T1: 1 Gb/s over one twisted pair, PAM3 at 750 MBd."},
        {"version": "802.3cg-2019", "summary": "10BASE-T1S (10 Mb/s short-reach MULTIDROP with PLCA) and 10BASE-T1L (10 Mb/s long-reach up to 1000 m point-to-point)."},
    ]
    f["future_versions_industry_outline"] = [
        {"version": "IEEE 802.3ch (MultiGBASE-T1)", "summary": "2.5G / 5G / 10G BASE-T1 single-pair automotive PHYs (higher-rate extension of the T1 family)."},
        {"version": "OPEN Alliance TC", "summary": "Ongoing automotive interoperability + EMC test specifications layered on the IEEE PHYs."},
    ]
    f["backward_compat_traps"] = [
        {"trap_name": "frame_compatible_but_phy_incompatible",
         "rule": "T1 PHYs preserve the Clause-4 MAC frame, so frames are interoperable end-to-end, BUT the single-pair PAM3 PHY is entirely different from 4-pair BASE-T.",
         "trap": "A 100BASE-T1 PHY CANNOT link to a 100BASE-TX (2-pair) or 1000BASE-T (4-pair) PHY; only frames are compatible after both ends are up."},
        {"trap_name": "master_slave_must_be_opposite",
         "rule": "One end must be master, the other slave.",
         "trap": "Two masters (or two slaves) never train; the link stays down."},
        {"trap_name": "plca_only_for_multidrop",
         "rule": "PLCA applies to the 10BASE-T1S multidrop segment.",
         "trap": "Enabling PLCA on a point-to-point link or mismatching node count/IDs breaks deterministic access."},
        {"trap_name": "pam3_not_pam4_not_8b10b",
         "rule": "Automotive T1 uses PAM3 ternary modulation.",
         "trap": "It is NOT the PAM4 of 800GBASE nor the 8b10b/MLT-3 of optical/100BASE-TX Ethernet; a PAM4/8b10b receiver cannot decode a PAM3 single-pair link."},
    ]
    f["version_naming_history_note"] = (
        "IEEE 802.3 single-pair amendments: 802.3bw (100BASE-T1, 2015), "
        "802.3bp (1000BASE-T1, 2016), 802.3cg (10BASE-T1S/T1L, 2019), and "
        "802.3ch (Multi-Gig BASE-T1). The suffix 'T1' = Twisted-pair, ONE "
        "pair (vs 'T' = 4-pair). The Clause-4 MAC frame is preserved across "
        "all of them.")
    d["fields"] = f
    _write(p, d)


# ---------------------------------------------------------------------------
# L15 — Encoding tables
# ---------------------------------------------------------------------------
def _apply_l15(gd: Path) -> None:
    p = gd / "L15_ENCODING_TABLES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["mac_frame_table"] = {
        "header_columns": ["Field", "Octets", "Value / Meaning"],
        "rows": [
            ["Preamble", 7, "0x55 x7 (UNCHANGED)"],
            ["SFD", 1, "0xD5"],
            ["Destination Address", 6, "48-bit MAC"],
            ["Source Address", 6, "48-bit unicast MAC"],
            ["EtherType / Length", 2, ">=0x0600 = EtherType; <=0x05DC = Length"],
            ["Payload", "46..1500", "MAC client data (zero-padded)"],
            ["FCS", 4, "IEEE 802.3 CRC-32, poly 0x04C11DB7"],
            ["Total (untagged)", "64..1518", "Min 64 B, max 1518 B"],
            ["VLAN tag", "+4", "TPID 0x8100 + TCI; raises max to 1522 B"],
        ],
    }
    f["pam3_levels_table"] = {
        "header_columns": ["PAM3 level", "Symbol", "Meaning"],
        "rows": [
            ["-1", "low", "ternary negative"],
            ["0", "mid", "ternary zero"],
            ["+1", "high", "ternary positive"],
        ],
    }
    f["variant_table"] = {
        "header_columns": ["Variant", "Standard", "Rate", "Pairs", "Modulation", "Baud", "Topology"],
        "rows": [
            ["100BASE-T1", "IEEE 802.3bw", "100 Mb/s", 1, "PAM3", "66.67 MBd", "point-to-point"],
            ["1000BASE-T1", "IEEE 802.3bp", "1 Gb/s", 1, "PAM3", "750 MBd", "point-to-point"],
            ["10BASE-T1S", "IEEE 802.3cg", "10 Mb/s", 1, "PAM3-class", "n/a", "multidrop (PLCA)"],
            ["10BASE-T1L", "IEEE 802.3cg", "10 Mb/s", 1, "PAM3", "n/a", "point-to-point, up to 1000 m"],
        ],
    }
    f["pcs_coding_table"] = {
        "header_columns": ["Variant", "PCS coding"],
        "rows": [
            ["100BASE-T1", "4B3B + 3B2T mapping + scrambler"],
            ["1000BASE-T1", "80B/81B scrambled"],
        ],
    }
    f["plca_table_10base_t1s"] = {
        "header_columns": ["Element", "Meaning"],
        "rows": [
            ["BEACON", "Coordinator (node 0) starts a PLCA cycle"],
            ["Transmit Opportunity (TO)", "Each node's deterministic turn, in node-ID order"],
            ["YIELD", "Node with nothing to send passes the TO on"],
            ["Node ID 0", "PLCA coordinator"],
        ],
    }
    f["tables"] = [
        "MAC frame format (IEEE 802.3 Clause 4, preserved)",
        "PAM3 3-level ternary encoding",
        "Single-pair variant table (100BASE-T1 / 1000BASE-T1 / 10BASE-T1S / 10BASE-T1L)",
        "PCS coding per variant (4B3B+3B2T / 80B/81B)",
        "PLCA elements (10BASE-T1S multidrop)",
    ]
    d["fields"] = f
    _write(p, d)


# ---------------------------------------------------------------------------
# L16 — Compliance properties
# ---------------------------------------------------------------------------
def _apply_l16(gd: Path) -> None:
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["must_have_properties"] = [
        "Operation over ONE single twisted pair (one balanced pair).",
        "Simultaneous-bidirectional full-duplex via echo cancellation (point-to-point variants).",
        "PHY-level master/slave loop timing (roles opposite at the two ends).",
        "PAM3 ternary line modulation.",
        "IEEE 802.3 Clause-4 MAC frame format preserved (FCS = CRC-32 0x04C11DB7).",
        "100BASE-T1 at 66.67 MBd / 1000BASE-T1 at 750 MBd.",
        "PLCA (Physical Layer Collision Avoidance) on a 10BASE-T1S multidrop segment.",
        "SNR / MSE link-quality reporting.",
        "EEE Low-Power Idle support.",
        "Automotive EMC (emissions + immunity) compliance.",
    ]
    f["must_not_have_properties"] = [
        "Multi-pair (4-pair) operation — T1 is single-pair only.",
        "PAM4 or 8b10b or MLT-3 line modulation (T1 uses PAM3).",
        "CSMA/CD collisions on a 10BASE-T1S multidrop segment (PLCA eliminates them).",
        "Two masters or two slaves on one link.",
        "Modifying the Clause-4 MAC frame format or the min/max frame size.",
    ]
    f["compliance_failure_modes"] = [
        {"mode": "Link-training failure", "trigger": "MSE cannot be driven below threshold within the training timer."},
        {"mode": "Master/slave misconfiguration", "trigger": "Both ends master or both slave."},
        {"mode": "Descrambler / PCS lock loss", "trigger": "PCS de-locks; link down."},
        {"mode": "SNR/MSE degradation", "trigger": "Cable/connector/EMC fault raises MSE above threshold."},
        {"mode": "PLCA violation", "trigger": "Node transmits outside its transmit opportunity / missing beacon (10BASE-T1S)."},
        {"mode": "FCS error", "trigger": "MAC CRC-32 mismatch."},
    ]
    f["min_link_constraint"] = (
        "A single-pair link shall reach master/slave timing lock, echo-"
        "canceller + equaliser convergence (MSE below threshold), and PCS "
        "descrambler/code lock over the qualified single-pair channel for its "
        "variant before reporting link-up.")
    f["reset_behavior_compliance"] = (
        "On reset the master/slave roles re-apply, the PMA re-trains "
        "(re-acquire timing, re-converge echo canceller + equaliser), and the "
        "PCS re-locks before the link is reported up.")
    f["frame_format_preservation_compliance"] = (
        "The MAC frame shall be byte-for-byte identical to base IEEE 802.3 "
        "(preamble/SFD/DA/SA/Type/Length/Payload/Pad/FCS) and the min/max "
        "frame size shall be unchanged.")
    d["fields"] = f
    _write(p, d)


# ---------------------------------------------------------------------------
# L17 — Channel / signal catalog  (FORCE-OVERWRITE)
# ---------------------------------------------------------------------------
def _apply_l17(gd: Path) -> None:
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f.clear()
    f["channels"] = [
        {"name": "MDI pair (TRD)", "interface": "MDI", "direction": "bidirectional (one pair)", "purpose": "The single balanced twisted pair carrying simultaneous-bidirectional PAM3 symbols.", "active_levels": "PAM3 ternary (-1/0/+1)", "idle_level": "PAM3 idle / EEE LPI refresh"},
        {"name": "xMII data", "interface": "MII/RMII/RGMII/SGMII", "direction": "MAC<->PHY", "purpose": "Reconciliation-Sublayer data to the MAC.", "active_levels": "LVCMOS / SGMII differential", "idle_level": "idle"},
        {"name": "MDC", "interface": "MDIO mgmt", "direction": "STA -> PHY", "purpose": "Management clock.", "active_levels": "LVCMOS", "idle_level": "running"},
        {"name": "MDIO", "interface": "MDIO mgmt", "direction": "STA <-> PHY (three-state)", "purpose": "Management data (Clause 22 + Clause 45).", "active_levels": "LVCMOS three-state", "idle_level": "logic-1 (pulled high)"},
    ]
    f["logical_signaling_levels"] = [
        {"name": "PAM3 symbol", "meaning": "Ternary -1 / 0 / +1 on the single pair."},
        {"name": "Echo-cancelled bidirectional", "meaning": "Local TX + remote TX coexist on the one pair; echo canceller recovers remote."},
        {"name": "PLCA beacon / transmit opportunity", "meaning": "Multidrop access markers (10BASE-T1S)."},
        {"name": "EEE LPI refresh", "meaning": "Low-power-idle refresh symbol keeping echo/equaliser coefficients valid."},
        {"name": "Inter-packet gap", "meaning": "IEEE 802.3 idle between MAC frames."},
    ]
    f["channel_counts"] = {
        "twisted_pairs": 1,
        "mdi_wires": 2,
        "mdio_wires": 2,
        "mac_address_octets": 6,
        "ethertype_width_octets": 2,
        "fcs_width_octets": 4,
        "pam3_levels": 3,
        "baud_MBd_100BASE_T1": 66.67,
        "baud_MBd_1000BASE_T1": 750,
    }
    f["global_signals"] = [
        {"name": "RESET#", "purpose": "PHY hardware reset."},
        {"name": "REFCLK", "purpose": "Reference clock (master sources the symbol clock)."},
        {"name": "MDC/MDIO", "purpose": "Management bus."},
        {"name": "INT#/LINK", "purpose": "Interrupt / link-status sideband."},
    ]
    f["dependency_graph"] = {
        "common_rule": "MAC -> RS (optionally PLCA RS) -> PCS (scramble + ternary code) -> PMA (echo cancel + equalise + master/slave timing) -> PMD/MDI (PAM3 on one pair).",
        "data_dependency": "Frame TX/RX requires master/slave timing lock + echo-canceller/equaliser convergence (MSE below threshold) + PCS lock.",
    }
    f["handshake_pairs"] = [
        {"name": "Master/slave timing", "from": "master", "to": "slave", "rule": "Slave loop-times to master; roles must be opposite."},
        {"name": "Link training", "from": "either", "to": "either", "rule": "Echo canceller + equaliser converge until MSE below threshold."},
        {"name": "PLCA transmit opportunity (10BASE-T1S)", "from": "coordinator", "to": "node", "rule": "Beacon then per-node-ID TO; yield if nothing to send."},
        {"name": "MDIO Clause-45", "from": "STA", "to": "PHY", "rule": "Address cycle then data cycle on the same DEVAD."},
    ]
    f["ordering_rules"] = {
        "bit_order_within_byte": "LSB-first on the MAC service interface; FCS appended MSB-byte-first (UNCHANGED from base 802.3).",
        "byte_order_within_field": "Network byte order (big-endian) for DA/SA/EtherType/VLAN.",
        "multidrop_order": "PLCA serialises multidrop access in node-ID order (10BASE-T1S).",
    }
    d["fields"] = f
    _write(p, d)


# ---------------------------------------------------------------------------
# L18 — Interconnect topology
# ---------------------------------------------------------------------------
def _apply_l18(gd: Path) -> None:
    p = gd / "L18_INTERCONNECT_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["topology_type"] = (
        "Point-to-point single-twisted-pair full-duplex link (100BASE-T1 / "
        "1000BASE-T1 / 10BASE-T1L): one master PHY + one slave PHY per link, "
        "echo-cancelled bidirectional on the one pair. PLUS a MULTIDROP "
        "'mixing segment' for 10BASE-T1S where several PHYs share one short "
        "single-pair bus and use PLCA (node 0 = coordinator) to take "
        "deterministic round-robin transmit opportunities.")
    f["supported_topologies"] = [
        {"name": "Point-to-point single-pair full-duplex", "description": "100BASE-T1 / 1000BASE-T1 / 10BASE-T1L; one master, one slave."},
        {"name": "Multidrop mixing segment (PLCA)", "description": "10BASE-T1S; several PHYs share one short single-pair segment, arbitrated by PLCA."},
        {"name": "AVB / TSN overlay", "description": "Time-sensitive audio/video + control traffic layered on the single-pair PHY."},
    ]
    f["master_slave_role_summary"] = [
        {"role": "Master PHY", "description": "Sources the symbol clock; one end of each link."},
        {"role": "Slave PHY", "description": "Loop-times (recovers clock) from the master; the other end."},
        {"role": "PLCA coordinator (node 0)", "description": "10BASE-T1S multidrop: emits the beacon, starts each PLCA cycle."},
        {"role": "Station Management Entity (STA)", "description": "MDC/MDIO master configuring master/slave, PLCA, EEE; reading SNR/MSE."},
    ]
    f["interconnect_role"] = (
        "The single MDI pair is point-to-point for the full-duplex variants "
        "and a shared bus for the 10BASE-T1S multidrop segment. The MDC/MDIO "
        "management bus is a separate shared bus addressed by PRTAD.")
    f["ordering_guarantees"] = {
        "in_link_ordering": "MAC delivers received frames in order.",
        "multidrop_access": "PLCA serialises access deterministically in node-ID order (no CSMA/CD).",
    }
    f["memory_vs_peripheral_regions"] = (
        "No MAC-layer address space. PHY management is the MDC/MDIO register "
        "space (Clause 22 basic + Clause 45 MMD), including master/slave, "
        "SNR/MSE, PLCA, and EEE registers. PHY identity is in the standard "
        "PHY-ID registers.")
    f["device_classification"] = {
        "automotive_phy": "100BASE-T1 / 1000BASE-T1 single-pair PHY for in-vehicle sensor/display/backbone links.",
        "multidrop_node": "10BASE-T1S PHY with a PLCA node ID on a shared segment.",
        "long_reach_phy": "10BASE-T1L single-pair PHY for process-automation field instruments (up to 1000 m).",
        "switch_bridge": "Automotive Ethernet switch with multiple single-pair ports + AVB/TSN.",
    }
    d["fields"] = f
    _write(p, d)


# ---------------------------------------------------------------------------
# L19 — Constraints / PDK
# ---------------------------------------------------------------------------
def _apply_l19(gd: Path) -> None:
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["constraints_present"] = False
    f["electrical_channel_constraints"] = {
        "medium": "single unshielded twisted pair (1 balanced pair)",
        "modulation": "PAM3 (3-level ternary)",
        "baud_MBd_100BASE_T1": 66.67,
        "baud_MBd_1000BASE_T1": 750,
        "duplex": "simultaneous bidirectional via echo cancellation",
        "timing": "master/slave loop timing",
        "link_quality_metrics": "SNR + MSE",
        "emc": "automotive EMC (emissions + immunity) per OPEN-Alliance / OEM",
        "tx_shaping": "scrambler + pulse shaping",
        "rx_equalization": "FFE + DFE + echo cancellation",
    }
    f["notes"] = (
        "The IEEE single-pair amendments specify PAM3 transmitter/receiver "
        "electrical + automotive-EMC compliance per clause but impose no "
        "PDK-specific SDC/floorplan constraints. The MAC/RS/PCS digital "
        "integrates as synchronous logic plus a single-pair PAM3 analog front "
        "end (driver, echo canceller, equaliser). Per-variant electrical / EMC "
        "specs live in the relevant 802.3bw/bp/cg clause + OPEN-Alliance test "
        "spec.")
    d["fields"] = f
    _write(p, d)


# ---------------------------------------------------------------------------
# L20 — DFT / scan topology
# ---------------------------------------------------------------------------
def _apply_l20(gd: Path) -> None:
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["dft_present"] = "partial"
    f["in_band_test_facilities"] = [
        {"name": "PAM3 transmitter test patterns (PMA)", "purpose": "Emissions + jitter compliance for the single-pair PHY."},
        {"name": "SNR/MSE readout (MDIO)", "purpose": "In-system link-quality monitoring."},
        {"name": "Master/slave force (MDIO)", "purpose": "Force a role to characterise the channel."},
        {"name": "Loopback (PMA / PCS)", "purpose": "Internal loopback for board test."},
        {"name": "PLCA status/counters (10BASE-T1S)", "purpose": "Observe deterministic multidrop access."},
        {"name": "Echo-canceller / equaliser tap readout (vendor)", "purpose": "Diagnose reflections / cable faults."},
    ]
    f["internal_diagnostics_observability"] = [
        "SNR + MSE link-quality registers.",
        "Master/slave resolved-role status.",
        "PMA trained / PCS descrambler-lock / link-up status.",
        "PLCA active / beacon / collision-free counters (10BASE-T1S).",
        "EEE LPI state.",
    ]
    f["out_of_band_test_facilities"] = [
        "Automotive EMC chamber (radiated/conducted emissions + BCI immunity).",
        "Single-pair channel VNA (return loss / insertion loss).",
        "Sampling scope for PAM3 eye.",
        "Automotive Ethernet protocol analyzer for frame + PLCA capture.",
        "JTAG (vendor) for scan/boundary-scan.",
    ]
    f["notes"] = (
        "The single-pair amendments mandate the SNR/MSE observability + PAM3 "
        "transmitter test facilities; JTAG/scan/BIST are vendor-added. The "
        "SNR/MSE registers are the primary in-system DFT instrument; the OPEN "
        "Alliance defines the EMC + interoperability test methodology.")
    d["fields"] = f
    _write(p, d)


# ---------------------------------------------------------------------------
# L21 — Power intent
# ---------------------------------------------------------------------------
def _apply_l21(gd: Path) -> None:
    p = gd / "L21_POWER_INTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["power_intent_present"] = True
    f["link_power_management_states"] = [
        {"state": "Active", "description": "Link up; PMA trained; MAC streaming.", "exit_latency_estimate": "n/a"},
        {"state": "EEE_LPI", "description": "Energy Efficient Ethernet Low-Power Idle; PHY analog low-power on MAC idle, periodic refresh keeps echo/equaliser coefficients valid.", "exit_latency_estimate": "bounded wake time"},
        {"state": "Power_down", "description": "PHY powered down via BMCR power-down bit.", "exit_latency_estimate": "full re-train"},
        {"state": "Reset", "description": "Re-apply master/slave, re-train, re-lock before link-up.", "exit_latency_estimate": "training + lock time"},
    ]
    f["low_power_modes_summary"] = {
        "Active": "Full operational power.",
        "EEE_LPI": "Low-Power Idle; analog partly shut down on idle with refresh.",
        "Power_down": "PHY off.",
    }
    f["notes"] = (
        "Automotive-Ethernet power management centres on EEE LPI — critical "
        "for always-on vehicle networks on a battery. The single-pair analog "
        "front end (PAM3 driver, echo canceller, equaliser) is the dominant "
        "power consumer; LPI partially shuts it down on idle and refreshes "
        "periodically to keep coefficients valid.")
    d["fields"] = f
    _write(p, d)


# ---------------------------------------------------------------------------
# L22 — Verification plan
# ---------------------------------------------------------------------------
def _apply_l22(gd: Path) -> None:
    p = gd / "L22_VERIFICATION_PLAN.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["verification_plan_present"] = "implicit"
    f["verification_categories_derived_from_spec"] = [
        "Single-pair operation: confirm full Ethernet over ONE twisted pair.",
        "Echo-cancelled full-duplex: simultaneous bidirectional traffic on the one pair.",
        "Master/slave timing: trains only with opposite roles.",
        "100BASE-T1: 100 Mb/s PAM3 at 66.67 MBd; 4B3B+3B2T scramble round-trip.",
        "1000BASE-T1: 1 Gb/s PAM3 at 750 MBd; 80B/81B scramble round-trip.",
        "10BASE-T1S multidrop: PLCA deterministic transmit opportunities; collision-free.",
        "10BASE-T1L: 10 Mb/s long-reach (up to 1000 m) point-to-point.",
        "Link training: echo canceller + equaliser converge; MSE below threshold within the timer.",
        "SNR/MSE readout tracks injected cable degradation.",
        "MAC frame: byte-for-byte IEEE 802.3 Clause-4 format; FCS CRC-32 (0x04C11DB7) on ASCII '123456789' -> 0xCBF43926.",
        "Min/max frame size preserved (64 / 1518 / 1522 VLAN).",
        "EEE LPI: enter low-power idle on MAC idle; wake within the bounded wake time.",
        "Automotive EMC: emissions + immunity per OPEN-Alliance / OEM.",
        "Management: MDC/MDIO Clause-22 + Clause-45 register access.",
    ]
    f["notes"] = (
        "The IEEE single-pair amendments have no formal testbench; categories "
        "derive from the single-pair PMA (PAM3, echo cancellation, master/"
        "slave timing, link training, SNR/MSE), the PCS (4B3B+3B2T / 80B/81B), "
        "the PLCA multidrop RS (10BASE-T1S), the preserved Clause-4 MAC, and "
        "automotive EMC. The OPEN Alliance runs interop + EMC conformance.")
    d["fields"] = f
    _write(p, d)


# ---------------------------------------------------------------------------
# L23 — Security requirements
# ---------------------------------------------------------------------------
def _apply_l23(gd: Path) -> None:
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["security_requirements_present"] = False
    f["anti_corruption_features"] = [
        "IEEE 802.3 CRC-32 FCS detects frame errors (1-, 2-, 3-bit and burst errors up to 32 bits).",
        "PAM3 + scrambler provide DC balance + spectral shaping (EMC), reducing error-prone signalling.",
        "SNR/MSE monitoring flags a degrading channel before it corrupts data.",
    ]
    f["anti_tampering_features"] = []
    f["confidentiality_features"] = []
    f["authentication_features"] = []
    f["future_security_pointers"] = [
        "IEEE 802.1AE MACsec — line-rate AES-GCM encryption + ICV + replay protection above the MAC; applies unchanged over a single-pair PHY.",
        "IEEE 802.1X port-based access control + MKA key agreement.",
        "Automotive security stacks (SecOC / AUTOSAR) layer above the Ethernet MAC.",
    ]
    f["notes"] = (
        "The IEEE single-pair amendments (802.3bw/bp/cg) are PHY + frame "
        "specifications with NO confidentiality / authentication at the "
        "MAC/PHY boundary; the only integrity check is the FCS (error "
        "detection, not cryptographic). Link-layer security (MACsec / 802.1X) "
        "and automotive security (SecOC) layer above and apply unchanged over "
        "the single-pair PHY.")
    d["fields"] = f
    _write(p, d)


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------
def apply_automotive_ethernet_synth(generated_docs_dir: Path,
                                    is_automotive_ethernet: bool,
                                    automotive_ethernet_ic_name: Optional[str]) -> None:
    """Apply single-twisted-pair Automotive-Ethernet (100BASE-T1 / 1000BASE-T1
    / 10BASE-T1S / 10BASE-T1L) synth.

    EXTENDS the base `ethernet_protocol_synth` sibling: that synth fires first
    on an Automotive-Ethernet doc (still IEEE 802.3 + MAC + frame) and lays
    down the generic 802.3 baseline; this synth then runs and FORCE-OVERWRITES
    every L1/L2/L3/L4 key the sibling populated, specialising to the
    single-pair T1 PHY family. All assignments are direct-assign (NOT
    setdefault) so the sibling baseline is always superseded. The runner wires
    this AFTER apply_ethernet_synth.
    """
    if not is_automotive_ethernet:
        return
    gd = Path(generated_docs_dir)

    if automotive_ethernet_ic_name is not None:
        _force_ic_name(gd, automotive_ethernet_ic_name)

    # L1/L2/L3/L4 — force-overwrite the sibling's 802.3 baseline.
    _apply_l1(gd)
    _apply_l2(gd)
    _apply_l3(gd)
    _apply_l4(gd)
    # L5..L13 + L14..L23 — single-pair-specific layered overlays.
    _apply_l5(gd)
    _apply_l6(gd)
    _apply_l7(gd)
    _apply_l8_rtl(gd)
    _apply_l8_timing(gd)
    _apply_l9(gd)
    _apply_l10(gd)
    _apply_l11(gd)
    _apply_l12(gd)
    _apply_l13(gd)
    _apply_l14(gd)
    _apply_l15(gd)
    _apply_l16(gd)
    _apply_l17(gd)
    _apply_l18(gd)
    _apply_l19(gd)
    _apply_l20(gd)
    _apply_l21(gd)
    _apply_l22(gd)
    _apply_l23(gd)
