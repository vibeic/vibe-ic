"""IEEE 802.3df 800 Gigabit Ethernet (800GBASE) protocol synth helper.

v0.1.89 — ic_class-gated overlay for `bus_interconnect_protocol`-shaped
specs that exhibit the IEEE 802.3df / 800GBASE structural signature. This
helper EXTENDS the base `ethernet_protocol_synth` sibling: the base
Ethernet detector (MII + MDIO + MAC + frame) ALSO fires on an 800G doc
(800GbE is still IEEE 802.3, with the same Clause-4 MAC frame), so the
two synths LAYER. The base ethernet synth runs first and populates the
generic 802.3 MAC / MII / MDIO content; this 800G synth then runs and
FORCE-OVERWRITES (direct-assign, never setdefault) every L1/L2/L3/L4 key
the sibling populates, specialising the docs to the 800G PHY family
(8x100G or 4x200G electrical lanes, PAM4, 106.25 GBd/lane, RS-FEC
(544,514) KP4, RS/PCS/PMA/PMD layering, 800GBASE-DR8/SR8/VR8/2xFR4).

DETECTOR (documented for the runner; operates on the L1/L2 CONTENT blob
`_spi_blob`, NEVER on the input-doc filename or benchmark folder name —
a code review previously flagged filename-sniffing as a HIGH defect):

    is_ethernet_800g = (
        "800GBASE" in blob
        or "802.3df" in blob
        or ("800G" in blob and "PAM4" in blob)
        or "800 Gigabit Ethernet" in blob
    )

where `blob` is the lowercase-normalised concatenation of the canonical
protocol NAME + spec-id strings extracted from the generated L1/L2 docs
(ic_name, document_title, version, keywords, abstract, protocol_overview).
The structural tokens "800GBASE" / "802.3df" / "PAM4" / "106.25" /
"RS-FEC" / "800 Gigabit Ethernet" are version-specific to this PHY family.

SIBLING DISAMBIGUATION (MUTEX): a base-802.3 doc (MII / GMII, 10/100/1000
Mb/s — the `ethernet` benchmark) carries NONE of the 800G/PAM4/802.3df
tokens, so THIS detector never fires on the `ethernet` benchmark. The
reverse is layered: the base `ethernet` detector DOES fire on an 800G doc
(still 802.3 + MAC + frame), so both run and 800G OVERRIDES via
force-assign. This mirrors the NVMe-on-PCIe / I3C-extends-I2C cross-
protocol force-overwrite doctrine.

Public entry:
    `apply_ethernet_800g_synth(generated_docs_dir, is_ethernet_800g,
                               ethernet_800g_ic_name)`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import l_doc_generator_stamp as _stamp


def _empty(v) -> bool:
    return v in (None, {}, []) or (isinstance(v, str) and not v.strip())


def _read(p: Path) -> dict:
    return json.loads(p.read_text())


def _write(p: Path, d: dict) -> None:
    # THE L-document write chokepoint: stamps the producing release onto
    # the document, then serialises it byte-identically to before.
    _stamp.dump(p, d)


def _ensure_dict(d: dict, key: str) -> dict:
    """Replace a pre-existing None/empty/non-dict value with a fresh dict.

    setdefault() on a pre-existing None is a no-op, so we explicitly
    normalise before populating subkeys (i2s-synth lesson)."""
    v = d.get(key)
    if not isinstance(v, dict):
        v = {}
        d[key] = v
    return v


def _force_ic_name(gd: Path, ic_name: str) -> None:
    """FORCE-OVERWRITE ic_name across all 24 L docs (top-level for the 14
    main docs, inside `fields` for L14-L23)."""
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
# L1 — Datasheet  (FORCE-OVERWRITE the sibling 802.3 baseline)
# ---------------------------------------------------------------------------
def _apply_l1(gd: Path) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    d["document_title"] = (
        "IEEE Std 802.3df-2024 — IEEE Standard for Ethernet Amendment: "
        "Physical Layer Specifications and Management Parameters for 800 "
        "Gb/s Operation (and 400 Gb/s and 800 Gb/s PHYs using 100 Gb/s "
        "lanes), with cross-references to the IEEE 802.3 Clause-4 MAC frame "
        "format and the MAC/RS/PCS/PMA/PMD layered architecture")
    d["version"] = (
        "IEEE Std 802.3df-2024 (approved 16 February 2024) — 800GBASE PHY "
        "family using 100 Gb/s electrical lanes (8x100G or 4x200G); "
        "companion IEEE P802.3dj (1.6 Tb/s + 200 Gb/s/lane PHYs, targeted "
        "completion July 2026)")
    d["revised_date"] = "2024"
    d["manufacturer"] = (
        "IEEE — LAN/MAN Standards Committee of the IEEE Computer Society "
        "(IEEE P802.3df Task Force, work started January 2022)")
    d["copyright"] = "© 2024 IEEE"
    d["abstract"] = (
        "IEEE 802.3df specifies 800 Gigabit Ethernet (800GbE): the MAC "
        "operates at 800 Gb/s while PRESERVING the IEEE 802.3 Clause-4 "
        "Ethernet MAC frame format and the existing minimum/maximum frame "
        "size of current Ethernet. The PHY is realised over 8 electrical "
        "lanes of 100 Gb/s (8x100G) or 4 lanes of 200 Gb/s (4x200G) using "
        "PAM4 modulation at 106.25 GBd per 100G lane, protected by a "
        "Reed-Solomon RS-FEC(544,514) KP4 forward error correction code, "
        "and is layered MAC → RS (Reconciliation Sublayer, 800GMII) → PCS "
        "(64b/66b + RS-FEC, 256b/257b transcoding) → PMA → PMD per IEEE "
        "802.3. Optical and electrical variants include 800GBASE-DR8 "
        "(8x100G SMF), 800GBASE-SR8 (8x100G MMF), 800GBASE-VR8 (very-short "
        "MMF) and 800GBASE-2xFR4 (2x400GBASE-FR4 CWDM SMF). Target bit "
        "error ratio is 1e-13 (improved over the 1e-12 of 10/40 GbE).")
    d["keywords"] = [
        "IEEE 802.3df", "IEEE 802.3dj", "800 Gigabit Ethernet", "800GbE",
        "800GBASE", "800GBASE-DR8", "800GBASE-SR8", "800GBASE-VR8",
        "800GBASE-2xFR4", "PAM4", "106.25 GBd", "RS-FEC", "RS-FEC(544,514)",
        "KP4 FEC", "100 Gb/s lane", "200 Gb/s lane", "8x100G", "4x200G",
        "MAC", "RS", "PCS", "PMA", "PMD", "800GMII", "Ethernet frame",
        "Preamble", "SFD", "EtherType", "FCS", "CRC-32", "BER 1e-13",
        "Full Duplex", "Terabit Ethernet",
    ]
    d["external_pins"] = [
        "800GMII (800 Gb/s Media-Independent Interface, logical) — MAC↔PCS "
        "reconciliation; carries the 800 Gb/s MAC byte stream into the PCS "
        "(implemented internally; no exposed parallel pin bus at 800G).",
        "Electrical-lane interface (AUI-class, e.g. 800GAUI-8 C2M/C2C): 8 "
        "differential TX pairs + 8 differential RX pairs of 100 Gb/s each "
        "(PAM4, 106.25 GBd), OR 800GAUI-4 with 4 lanes of 200 Gb/s.",
        "PMD service interface to the medium: 8-lane MMF/SMF parallel-fiber "
        "ribbon (DR8/SR8/VR8) or 8 wavelengths / 2x4-wavelength CWDM "
        "(2xFR4) on single-mode fiber.",
        "MDC / MDIO Clause-45 management bus (5-bit PRTAD + 5-bit DEVAD + "
        "16-bit register) — 800G PHYs are managed exclusively via Clause-45 "
        "MMDs (PMA/PMD=1, PCS=3, AN=7); no Clause-22 register file.",
        "Reference clock + reset + low-speed sideband (per AUI / module "
        "form-factor, e.g. OSFP / QSFP-DD800).",
    ]
    d["external_pin_count_electrical_lanes_8x100G"] = 8
    d["external_pin_count_electrical_lanes_4x200G"] = 4
    d["external_pin_count_optical_lanes_DR8_SR8"] = 8
    d["supported_speeds_Gbps"] = [800]
    d["companion_speeds_Gbps"] = [400, 800, 1600]
    d["modes_of_operation"] = [
        {"name": "800GBASE-DR8 (800 Gb/s, 8x100G PAM4, parallel single-mode fiber, ≥500 m)",
         "interface_to_MAC": "800GMII / RS / PCS", "lanes": 8, "modulation": "PAM4", "line_rate_GBd_per_lane": 106.25, "medium": "SMF (8 parallel fibers)", "data_rate_Gbps": 800},
        {"name": "800GBASE-SR8 (800 Gb/s, 8x100G PAM4, parallel multimode fiber, ≥50-100 m)",
         "interface_to_MAC": "800GMII / RS / PCS", "lanes": 8, "modulation": "PAM4", "line_rate_GBd_per_lane": 106.25, "medium": "MMF (8 parallel fibers, OM3/OM4/OM5)", "data_rate_Gbps": 800},
        {"name": "800GBASE-VR8 (800 Gb/s, 8x100G PAM4, very-short-reach multimode fiber)",
         "interface_to_MAC": "800GMII / RS / PCS", "lanes": 8, "modulation": "PAM4", "line_rate_GBd_per_lane": 106.25, "medium": "MMF (8 parallel fibers, very short reach)", "data_rate_Gbps": 800},
        {"name": "800GBASE-2xFR4 (800 Gb/s = 2x 400GBASE-FR4, 4-wavelength CWDM SMF, ≥2 km)",
         "interface_to_MAC": "800GMII / RS / PCS", "lanes": "2x4 wavelengths", "modulation": "PAM4", "line_rate_GBd_per_lane": 106.25, "medium": "SMF (2x4 CWDM wavelengths)", "data_rate_Gbps": 800},
    ]
    d["key_features"] = [
        "MAC operates at 800 Gb/s while PRESERVING the IEEE 802.3 Clause-4 "
        "Ethernet MAC frame format: Preamble (7x0x55) + SFD (0xD5) + DA (6B) "
        "+ SA (6B) + EtherType/Length (2B) + Payload + Pad + FCS (4B CRC-32, "
        "polynomial 0x04C11DB7) — IDENTICAL to all earlier Ethernet speeds.",
        "PRESERVES the current Ethernet minimum (64-byte) and maximum "
        "(1518-byte untagged / 1522-byte VLAN-tagged) frame size — a "
        "mandatory IEEE P802.3df project objective.",
        "Target bit error ratio (BER) of 1e-13 after FEC — an improvement "
        "over the 1e-12 specified for 10GbE / 40GbE.",
        "PHY realised over 8 electrical lanes of 100 Gb/s (8x100G) or 4 "
        "lanes of 200 Gb/s (4x200G); 8x100G is the dominant first-generation "
        "implementation using existing 100 Gb/s/lane SerDes.",
        "PAM4 (4-level pulse-amplitude modulation) carries 2 bits per "
        "symbol, so each 100 Gb/s lane runs at 106.25 GBd (gigabaud) — half "
        "the symbol rate that NRZ would require, at a higher SNR cost.",
        "Reed-Solomon forward error correction RS-FEC(544,514) — the KP4 FEC "
        "(GF(2^10), 10-bit symbols, 514 message + 30 parity = 544 symbols) "
        "provides the coding gain needed to hit 1e-13 post-FEC over a "
        "1e-4..1e-5 raw-lane error rate.",
        "Layered MAC / RS / PCS / PMA / PMD architecture per IEEE 802.3: RS "
        "= Reconciliation Sublayer mapping MAC to 800GMII; PCS = 64b/66b "
        "line coding + 256b/257b transcoding + RS-FEC + lane "
        "distribution/alignment-marker insertion; PMA = bit-mux / "
        "retiming / lane reorder; PMD = electro-optical medium attachment.",
        "Optical/electrical variants: 800GBASE-DR8 (8x100G SMF, ≥500 m), "
        "800GBASE-SR8 (8x100G MMF), 800GBASE-VR8 (very-short MMF), "
        "800GBASE-2xFR4 (2x 400GBASE-FR4, 4-wavelength CWDM SMF, ≥2 km).",
        "Full-duplex only — there is no half-duplex / CSMA/CD at 800G; "
        "every 800GbE link is a switched point-to-point collision-free link "
        "with PAUSE / priority-based flow control (Clause 31 / 802.1Qbb).",
        "Managed exclusively via Clause-45 MDIO MMDs (PMA/PMD = DEVAD 1, PCS "
        "= DEVAD 3, Auto-Negotiation = DEVAD 7); no Clause-22 register file "
        "at 800G.",
        "Link training + Auto-Negotiation (Clause 73/136-class) on the "
        "electrical lanes adapts the SerDes equaliser (FFE/DFE) coefficients "
        "before the PCS achieves block + alignment-marker lock.",
        "IEEE P802.3df started January 2022; in November 2022 the project "
        "was split — 1.6 Tb/s and 200 Gb/s/lane work moved to IEEE "
        "P802.3dj; the 802.3df standard was approved 16 February 2024.",
    ]
    d["topology_summary"] = (
        "Switched point-to-point full-duplex link (the only modern Ethernet "
        "topology at 800G — there is no shared medium / CSMA/CD). Each MAC "
        "connects through its RS / PCS / PMA / PMD to one PMD-class medium: "
        "8 parallel fibers (DR8/SR8/VR8) or 2x4 CWDM wavelengths (2xFR4) on "
        "single-mode fiber, typically inside an OSFP or QSFP-DD800 pluggable "
        "module. PHY-internal lane distribution spreads the 800 Gb/s MAC "
        "stream across 8 PCS lanes with periodic alignment markers so the "
        "receiver can deskew and reorder the lanes.")
    d["package_summary"] = (
        "IEEE Std 802.3df-2024 is a PHY-layer + management-parameter "
        "amendment to IEEE 802.3; it defines the 800 Gb/s RS / PCS / PMA / "
        "PMD and the 800GAUI electrical interfaces. Module mechanicals "
        "(OSFP, QSFP-DD800), connectors and fiber ribbons are governed by "
        "the relevant MSA / form-factor bodies, not by 802.3df itself.")
    d["use_cases"] = [
        "Hyperscale data-center spine/leaf and AI/ML training-cluster "
        "fabrics (GPU-to-switch and switch-to-switch 800G links)",
        "Data-center interconnect (DCI) over single-mode fiber (DR8 / 2xFR4)",
        "High-radix switch ASIC uplinks (51.2 Tb/s switch silicon = 64 x "
        "800G ports)",
        "800G pluggable optics (OSFP / QSFP-DD800) and active electrical / "
        "active optical cables",
        "Breakout to 8x100G or 2x400G / 4x200G via the lane-granular PHY",
    ]
    d["revision_history"] = [
        {"version": "IEEE P802.3df (project start)", "date": "2022-01",
         "description": "IEEE P802.3df Task Force started work to standardize 800 Gb/s and 1.6 Tb/s Ethernet."},
        {"version": "IEEE P802.3df (scope split)", "date": "2022-11",
         "description": "Project objectives split: 1.6 Tb/s and 200 Gb/s/lane work moved to the new IEEE P802.3dj project; 802.3df reduced to 800G Ethernet (and 400G/800G PHYs) using 100 Gb/s lanes."},
        {"version": "IEEE Std 802.3df-2024", "date": "2024-02-16",
         "description": "Standard approved. Defines 800 Gb/s MAC operation preserving the Ethernet frame format + min/max frame size, BER 1e-13, and the 800GBASE PHY family (DR8/SR8/VR8/2xFR4) over 100 Gb/s PAM4 lanes with RS-FEC(544,514)."},
    ]
    d["overview"] = (
        "IEEE 802.3df defines 800 Gigabit Ethernet — the MAC runs at 800 "
        "Gb/s while keeping the IEEE 802.3 Clause-4 Ethernet MAC frame "
        "format and the existing minimum/maximum frame size completely "
        "unchanged, so 800GbE is fully frame-compatible with every prior "
        "Ethernet speed. What changes is entirely below the MAC: the PHY is "
        "built from 8 electrical lanes of 100 Gb/s (8x100G) or 4 lanes of "
        "200 Gb/s (4x200G), each lane using PAM4 modulation at 106.25 GBd "
        "and protected by a Reed-Solomon RS-FEC(544,514) KP4 forward error "
        "correction code to reach a post-FEC bit error ratio of 1e-13. The "
        "MAC / RS / PCS / PMA / PMD layering is preserved: the PCS performs "
        "64b/66b + 256b/257b transcoding, RS-FEC, and distribution of the "
        "stream onto multiple PCS lanes with alignment markers; the PMA "
        "bit-muxes and retimes the lanes; and the PMD attaches to the "
        "medium as 800GBASE-DR8 / SR8 / VR8 (8 parallel fibers) or "
        "800GBASE-2xFR4 (CWDM single-mode fiber). The IEEE P802.3df Task "
        "Force, formed in January 2022, split off the 1.6 Tb/s and 200 "
        "Gb/s/lane work to IEEE P802.3dj in November 2022, and the 802.3df "
        "standard was approved on 16 February 2024.")
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
    po["type"] = (
        "Layered IEEE 802.3 Ethernet at 800 Gb/s: a single 800 Gb/s MAC "
        "(Clause-4 frame format preserved) over RS (Reconciliation "
        "Sublayer / 800GMII) → PCS (64b/66b + 256b/257b transcoding + "
        "RS-FEC(544,514) + multi-lane distribution with alignment markers) "
        "→ PMA (bit-mux / retime / lane reorder) → PMD (8x100G or 4x200G "
        "PAM4 electrical/optical lanes). Managed via Clause-45 MDIO MMDs.")
    po["duplex"] = "full duplex only (no half-duplex / CSMA/CD at 800G)"
    po["mac_rate_Gb_s"] = 800
    po["modulation"] = "PAM4 (2 bits/symbol)"
    po["baud_rate_GBd_per_100G_lane"] = 106.25
    po["lane_options"] = ["8x100G (8 lanes x 100 Gb/s)", "4x200G (4 lanes x 200 Gb/s)"]
    po["fec"] = "Reed-Solomon RS-FEC(544,514), KP4, GF(2^10) 10-bit symbols, 30 parity symbols"
    po["target_BER_post_fec"] = "1e-13"
    po["embedded_clock"] = True
    po["encoding"] = (
        "PCS: 64b/66b block coding then 256b/257b transcoding, scrambled, "
        "RS-FEC(544,514) applied, then distributed across PCS lanes with "
        "periodic alignment markers; PMD line modulation is PAM4 on each "
        "electrical/optical lane.")
    po["layers"] = ["MAC (Clause 4)", "RS / 800GMII", "PCS", "PMA", "PMD"]
    po["interfaces_in_scope"] = [
        "Clause 4 — Ethernet MAC frame format (PRESERVED at 800 Gb/s)",
        "RS / 800GMII — Reconciliation Sublayer mapping the 800 Gb/s MAC stream to the PCS",
        "PCS — 64b/66b + 256b/257b transcoding, scrambling, RS-FEC(544,514), PCS-lane distribution + alignment markers",
        "PMA — bit-muxing, retiming, lane reordering between PCS-lane count and physical-lane count",
        "PMD — 800GBASE-DR8 / SR8 / VR8 / 2xFR4 electro-optical medium attachment, PAM4 at 106.25 GBd/lane",
        "800GAUI-8 / 800GAUI-4 — chip-to-module / chip-to-chip electrical attachment-unit interface",
        "Clause-45 MDIO management (PMA/PMD = DEVAD 1, PCS = DEVAD 3, AN = DEVAD 7)",
        "Auto-Negotiation + link training (Clause 73/136-class) on the electrical lanes",
    ]
    po["frame_classes"] = {
        "Data_frame": "Preamble + SFD + DA + SA + EtherType/Length + Payload + Pad + FCS (IEEE 802.3 Clause-4 frame, UNCHANGED at 800G)",
        "VLAN_tagged_frame": "Preamble + SFD + DA + SA + VLAN tag (TPID 0x8100 + TCI) + EtherType/Length + Payload + Pad + FCS (max 1522 B)",
        "PAUSE_frame": "DA = 01:80:C2:00:00:01 + SA + EtherType 0x8808 + opcode 0x0001 + Pause Quanta + pad to 64 B + FCS (full-duplex flow control, Clause 31)",
        "PCS_alignment_marker": "Periodic per-PCS-lane alignment-marker code groups inserted by the PCS so the receiver can deskew + reorder lanes (NOT a MAC frame)",
        "FEC_codeword": "RS-FEC(544,514) codeword: 514 message symbols + 30 parity symbols = 544 ten-bit symbols (GF(2^10)) (NOT a MAC frame)",
    }
    d["protocol_overview"] = po

    d["functional_requirements"] = [
        {"id": "FR-MAC-800G-01", "text": "The MAC sublayer shall operate at 800 Gb/s and shall PRESERVE the IEEE 802.3 Clause-4 Ethernet MAC frame format: Preamble (7 octets of 0x55) + SFD (0xD5) + DA (6 B) + SA (6 B) + EtherType/Length (2 B) + Payload + Pad + FCS (4 B CRC-32, polynomial 0x04C11DB7). This is mandated by the IEEE P802.3df objective 'Preserve the Ethernet frame format utilizing the Ethernet MAC'."},
        {"id": "FR-FRAMESIZE-02", "text": "The 800 Gb/s MAC shall PRESERVE the minimum (64 B) and maximum (1518 B untagged / 1522 B VLAN-tagged) frame size of the current Ethernet standard, per the IEEE P802.3df objective 'Preserve minimum and maximum frame size of current Ethernet standard'."},
        {"id": "FR-BER-03", "text": "The PHY shall support a post-FEC bit error ratio (BER) of 1e-13 — an improvement over the 1e-12 BER specified for 10GbE / 40GbE."},
        {"id": "FR-FEC-04", "text": "The PCS shall apply Reed-Solomon forward error correction RS-FEC(544,514) (KP4): 514 message symbols + 30 parity symbols = 544 ten-bit symbols over GF(2^10). The FEC provides the coding gain to reach 1e-13 post-FEC from a raw per-lane error ratio in the 1e-4..1e-5 range."},
        {"id": "FR-LANES-05", "text": "The PHY shall realise 800 Gb/s over 8 electrical lanes of 100 Gb/s (8x100G) or 4 lanes of 200 Gb/s (4x200G). 8x100G is the dominant first-generation implementation using existing 100 Gb/s/lane SerDes."},
        {"id": "FR-PAM4-06", "text": "Each 100 Gb/s lane shall use PAM4 (4-level pulse-amplitude modulation, 2 bits per symbol) at a symbol rate of 106.25 GBd, halving the baud rate relative to NRZ at the cost of reduced per-symbol SNR."},
        {"id": "FR-LAYER-07", "text": "The PHY shall be layered MAC → RS (Reconciliation Sublayer / 800GMII) → PCS → PMA → PMD per IEEE 802.3. The PCS shall perform 64b/66b coding, 256b/257b transcoding, scrambling, RS-FEC, and distribution of the encoded stream across PCS lanes with periodic alignment markers."},
        {"id": "FR-PCSLANE-08", "text": "The PCS shall distribute the encoded 800 Gb/s stream across multiple PCS lanes and insert periodic per-lane alignment markers so the receiver can deskew, reorder, and reassemble the lanes regardless of inter-lane skew introduced by the medium."},
        {"id": "FR-PMD-09", "text": "The PMD shall implement one of 800GBASE-DR8 (8x100G PAM4, parallel single-mode fiber, ≥500 m), 800GBASE-SR8 (8x100G PAM4, parallel multimode fiber), 800GBASE-VR8 (very-short-reach MMF), or 800GBASE-2xFR4 (2x 400GBASE-FR4, 4-wavelength CWDM single-mode fiber, ≥2 km)."},
        {"id": "FR-AUI-10", "text": "The chip-to-module / chip-to-chip electrical attachment shall use the 800GAUI-8 (8x100G) or 800GAUI-4 (4x200G) Attachment Unit Interface with PAM4 signaling and the associated transmitter / receiver electrical compliance and link-training requirements."},
        {"id": "FR-FULLDUPLEX-11", "text": "800GbE shall operate full-duplex only. There is no half-duplex or CSMA/CD at 800 Gb/s; every link is a switched point-to-point collision-free link with PAUSE / priority-based flow control."},
        {"id": "FR-MDIO-12", "text": "Management shall be performed exclusively via Clause-45 MDIO MMDs: PMA/PMD = DEVAD 1, PCS = DEVAD 3, Auto-Negotiation = DEVAD 7. There is no Clause-22 register file at 800G."},
        {"id": "FR-AN-LT-13", "text": "Auto-Negotiation and link training (Clause 73/136-class) shall run on the electrical lanes to adapt the SerDes equaliser (FFE/DFE) coefficients before the PCS achieves block lock + alignment-marker lock."},
        {"id": "FR-FCS-14", "text": "Every transmitted frame shall append a 32-bit Frame Check Sequence computed with the IEEE 802.3 CRC-32 polynomial 0x04C11DB7 (init 0xFFFFFFFF, final XOR 0xFFFFFFFF, LSB-first). This is UNCHANGED from base Ethernet — the FCS is a MAC-layer mechanism, orthogonal to the RS-FEC applied in the PCS."},
        {"id": "FR-IFG-15", "text": "The MAC shall enforce the inter-packet gap rules of IEEE 802.3 (nominal 96 bit times, adapted by the deficit-idle-count mechanism for the multi-lane PCS) between back-to-back frames."},
    ]
    d["error_response_conditions"] = [
        "Post-FEC uncorrectable codeword — RS-FEC(544,514) can correct up to 15 symbol errors per codeword; a codeword with more than 15 erred symbols is uncorrectable, marked, and the affected 66b blocks are flagged so the MAC discards the frame (FCS will also fail).",
        "Loss of PCS block lock — the PCS de-locks if 64b/66b sync-header errors exceed the threshold; link reported down via Clause-45 PCS status.",
        "Loss of alignment-marker lock — receiver cannot deskew/reorder PCS lanes; link reported down.",
        "FCS (CRC-32) mismatch — receive MAC discards the frame and increments an FCS-error counter (MAC-layer, downstream of FEC).",
        "Frame too short (< 64 B) — receive MAC discards as a runt.",
        "Frame too long (> 1518 B untagged / > 1522 B VLAN-tagged) — receive MAC may discard as a giant unless jumbo support is enabled.",
        "Link-training failure — SerDes equaliser fails to converge within the training timer; the lane (and link) is reported as not trained / not up.",
        "PAUSE timer running (full-duplex) — MAC holds off data-frame transmission until the timer expires.",
        "Excessive raw-lane BER above the FEC budget — sustained pre-FEC error ratio worse than ~1e-4..1e-5 exhausts the FEC and drives post-FEC BER above the 1e-13 target; reported via FEC symbol-error / corrected/uncorrected counters.",
    ]
    d["compliance_requirements"] = [
        "Mandatory preservation of the IEEE 802.3 Clause-4 MAC frame format (preamble 7x0x55 + SFD 0xD5 + DA + SA + Type/Length + Payload + Pad + FCS) at 800 Gb/s.",
        "Mandatory preservation of the current min (64 B) and max (1518 B / 1522 B VLAN) frame size.",
        "Mandatory post-FEC BER of 1e-13.",
        "Mandatory RS-FEC(544,514) KP4 forward error correction in the PCS.",
        "Mandatory PAM4 modulation at 106.25 GBd per 100 Gb/s lane.",
        "Mandatory MAC / RS / PCS / PMA / PMD layering per IEEE 802.3.",
        "Mandatory FCS = IEEE 802.3 CRC-32 (polynomial 0x04C11DB7) over DA + SA + Type/Length + Payload + Pad.",
        "Mandatory Clause-45 MDIO management (no Clause-22 register file).",
        "Mandatory full-duplex operation (no CSMA/CD).",
        "Per-PMD transmitter / receiver optical or electrical compliance (TDECQ, eye, return loss) per the 800GBASE-DR8/SR8/VR8/2xFR4 PMD specification.",
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
        "Streaming layered Ethernet PHY at 800 Gb/s. The MAC carries "
        "IEEE 802.3 Clause-4 frames (unchanged); the PCS encodes + "
        "FEC-protects + distributes the stream across multiple PCS lanes "
        "with alignment markers; the PMA/PMD carry PAM4 symbols across "
        "8x100G or 4x200G electrical/optical lanes. There is no opcode / "
        "command protocol on the data path. Management is a separate "
        "Clause-45 MDIO two-cycle address-then-data protocol.")
    d["channels"] = [
        {"name": "800GMII (logical RS interface)", "direction": "MAC↔PCS",
         "description": "Reconciliation-Sublayer interface carrying the 800 Gb/s MAC byte stream into the PCS. Logical at 800G — no exposed wide parallel pin bus."},
        {"name": "PCS lanes", "direction": "internal PCS↔PMA",
         "description": "The encoded + FEC-protected stream is distributed across multiple PCS lanes, each carrying 64b/66b blocks plus periodic alignment markers for receiver deskew/reorder."},
        {"name": "800GAUI-8 electrical lanes", "direction": "chip↔module / chip↔chip",
         "description": "8 differential TX + 8 differential RX pairs, each 100 Gb/s PAM4 at 106.25 GBd. The 4x200G variant uses 800GAUI-4 (4 lanes of 200 Gb/s)."},
        {"name": "PMD medium lanes", "direction": "PMD↔fiber",
         "description": "DR8/SR8/VR8 = 8 parallel fibers; 2xFR4 = 2x4 CWDM wavelengths on single-mode fiber. PAM4 line modulation."},
        {"name": "MDC / MDIO (Clause 45)", "direction": "STA↔PHY MMDs",
         "description": "Serial management bus; MDC ≤ 2.5 MHz (or faster per vendor), MDIO bidirectional three-state. Two-cycle address-then-data per Clause 45 (PMA/PMD/PCS/AN MMDs)."},
    ]
    d["packet_classes"] = [
        {"class": "Ethernet MAC frame (800 Gb/s)", "purpose": "Carries user data between MACs; Clause-4 frame format preserved.", "subtypes": [
            "Untagged data frame (DA + SA + EtherType/Length + Payload + FCS, 64-1518 B)",
            "802.1Q VLAN-tagged frame (max 1522 B)",
            "802.3x PAUSE frame (DA = 01:80:C2:00:00:01, EtherType 0x8808, 64 B)",
            "Priority-based flow-control frame (802.1Qbb, EtherType 0x8808 opcode 0x0101)",
        ]},
        {"class": "PCS sublayer unit", "purpose": "Line-coding + FEC + lane-distribution units below the MAC (NOT MAC frames).", "subtypes": [
            "64b/66b block (2-bit sync header + 64-bit payload)",
            "256b/257b transcoded block",
            "RS-FEC(544,514) codeword (544 ten-bit symbols)",
            "Per-PCS-lane alignment marker",
        ]},
        {"class": "MDIO management frame (Clause 45)", "purpose": "MMD-extended PHY register access via two-cycle address-then-data.", "subtypes": [
            "Address (ST=00, OP=00, PRTAD(5), DEVAD(5), ADDR(16))",
            "Write (OP=01)", "Read (OP=11)", "Post-Increment Read (OP=10)",
        ]},
        {"class": "Auto-Negotiation / link training", "purpose": "Electrical-lane equaliser adaptation + capability exchange before PCS lock.", "subtypes": [
            "AN base/next pages (Clause 73-class)",
            "PMD link-training frames (FFE/DFE coefficient request/response)",
        ]},
    ]
    d["mac_frame_format"] = {
        "preamble": "7 octets of 0x55 (UNCHANGED from base Ethernet).",
        "sfd": "1 octet 0xD5.",
        "destination_address": "6 octets (48 bits). I/G + U/L bits as in base 802.3.",
        "source_address": "6 octets (48 bits), unicast.",
        "etheryype_or_length": "2 octets. >= 0x0600 = EtherType; <= 0x05DC = Length.",
        "payload": "46-1500 octets (42-1500 in a VLAN-tagged frame). Zero-padded if shorter.",
        "pad": "0-46 octets of 0x00 to reach the 64-byte minimum.",
        "fcs": "4 octets, IEEE 802.3 CRC-32, polynomial 0x04C11DB7. UNCHANGED at 800G; orthogonal to the PCS RS-FEC.",
        "note": "The 800 Gb/s MAC frame is byte-for-byte identical to every prior Ethernet speed — only the rate and the underlying PCS/PMA/PMD differ.",
    }
    d["pcs_pipeline"] = {
        "step_1_64b66b": "MAC stream blocked into 64b/66b (2-bit sync header + 64-bit payload).",
        "step_2_transcode": "256b/257b transcoding reduces the coding overhead before FEC.",
        "step_3_scramble": "Self-synchronous scrambling for DC balance + transition density.",
        "step_4_rs_fec": "RS-FEC(544,514) over GF(2^10): 514 message + 30 parity = 544 ten-bit symbols; corrects up to 15 symbol errors/codeword.",
        "step_5_distribute": "Round-robin distribution across PCS lanes with periodic per-lane alignment markers.",
        "step_6_pma_pmd": "PMA bit-muxes PCS lanes onto physical lanes; PMD PAM4-modulates each lane at 106.25 GBd.",
    }
    d["mdio_clause45_frame"] = {
        "PRE": "32 contiguous logic-1 bits (may be suppressed).",
        "ST": "<00> — Clause 45.",
        "OP": "<00> Address / <01> Write / <11> Read / <10> Post-Increment Read.",
        "PRTAD": "5-bit port (PHY) address.",
        "DEVAD": "5-bit MMD Device Address: 1 = PMA/PMD, 3 = PCS, 7 = Auto-Negotiation.",
        "TA": "2-bit turnaround.",
        "DATA": "16 bits. Address cycle writes the indirect register address; data cycle accesses it.",
    }
    d["valid_ready_handshake_rules"] = [
        "The 800G data path is a continuous stream — there is no per-beat valid/ready handshake at the PMD; flow control is end-to-end via PAUSE / PFC frames at the MAC.",
        "Receiver achieves PCS block lock (64b/66b sync) then alignment-marker lock (per-PCS-lane deskew + reorder) before delivering reassembled blocks to the MAC.",
        "RS-FEC corrects up to 15 symbol errors per (544,514) codeword; uncorrectable codewords are marked and the spanning 66b blocks flagged.",
        "MDIO Clause 45: each transaction is an Address cycle (OP=00) followed by a Data cycle (OP=01/11/10) on the same DEVAD.",
        "Link training (electrical lanes) converges the FFE/DFE coefficients before the PCS attempts block lock.",
    ]
    d["burst_based"] = False
    d["byte_oriented"] = True
    d["addressing"] = {
        "mac_address_width_bits": 48,
        "clause45_prtad_width_bits": 5,
        "clause45_devad_width_bits": 5,
        "clause45_regad_width_bits": 16,
        "ethertype_width_bits": 16,
        "vlan_vid_width_bits": 12,
        "vlan_pcp_width_bits": 3,
        "broadcast_address": "FF:FF:FF:FF:FF:FF",
        "pause_multicast_address": "01:80:C2:00:00:01",
        "fec_symbol_field_GF": "GF(2^10) — 10-bit RS-FEC symbols",
        "rs_fec_n": 544,
        "rs_fec_k": 514,
        "rs_fec_parity_symbols": 30,
        "rs_fec_correctable_symbol_errors": 15,
        "pcs_lane_count_8x100G": 8,
        "physical_lane_count_8x100G": 8,
        "physical_lane_count_4x200G": 4,
        "baud_rate_GBd_per_100G_lane": 106.25,
    }
    _write(p, d)


# ---------------------------------------------------------------------------
# L4 — Register / PHY management map (Clause-45 MMD, no Clause-22)
# ---------------------------------------------------------------------------
def _apply_l4(gd: Path) -> None:
    p = gd / "L4_REGMAP.json"
    if not p.is_file():
        return
    d = _read(p)
    d["register_map_present"] = True
    d["register_address_scheme"] = (
        "800G PHYs are managed exclusively via the Clause-45 MDIO MMD "
        "address space (5-bit PRTAD + 5-bit DEVAD + 16-bit register), "
        "giving a 32 x 32 x 65536 register space per MDIO bus segment. "
        "There is NO Clause-22 16-bit register file (BMCR/BMSR) at 800G — "
        "the gigabit/10G-era basic register set does not scale to a "
        "multi-lane FEC PHY.")
    d.pop("phy_clause22_register_map", None)
    d.pop("bmcr_bit_definitions", None)
    d.pop("bmsr_bit_definitions", None)
    d.pop("anar_field_layout", None)
    d.pop("anlpar_field_layout", None)
    d["clause45_mmd_devad_assignments"] = [
        {"devad": 1, "name": "PMA/PMD", "purpose": "Physical Medium Attachment + Physical Medium Dependent: per-lane control/status, PMD transmit disable, fault, link-training, electrical/optical compliance status for 800GBASE-DR8/SR8/VR8/2xFR4."},
        {"devad": 3, "name": "PCS", "purpose": "Physical Coding Sublayer: 64b/66b + 256b/257b status, RS-FEC(544,514) control + corrected/uncorrected codeword + symbol-error counters, PCS-lane alignment-marker lock + lane-mapping, BER monitor."},
        {"devad": 7, "name": "Auto-Negotiation", "purpose": "Clause-73-class Auto-Negotiation MMD: base/next page exchange, resolved technology, link-training control/status."},
        {"devad": "1 (per-lane sub-blocks)", "name": "PMA per-lane", "purpose": "Per-physical-lane PMA control/status (lane 0..7) for the 8x100G PMD."},
        {"devad": "30..31", "name": "Vendor-specific", "purpose": "Vendor-defined MMDs (SerDes equaliser taps, eye monitors, temperature, diagnostics)."},
    ]
    d["pcs_status_registers_summary"] = [
        {"name": "PCS Status (RS-FEC)", "purpose": "FEC bypass-correction/indication enable, FEC-aligned, hi-SER (high symbol-error-rate) flag."},
        {"name": "RS-FEC corrected codewords counter", "purpose": "Count of RS-FEC(544,514) codewords with <=15 symbol errors that were corrected."},
        {"name": "RS-FEC uncorrected codewords counter", "purpose": "Count of codewords with >15 symbol errors (uncorrectable)."},
        {"name": "RS-FEC symbol-error counters (per lane)", "purpose": "Per-FEC-lane corrected-symbol counts used to monitor the pre-FEC margin against the 1e-13 post-FEC target."},
        {"name": "PCS-lane alignment-marker lock + mapping", "purpose": "Per-PCS-lane lock status + the physical-lane-to-PCS-lane mapping after receiver deskew/reorder."},
        {"name": "BER monitor", "purpose": "Estimated post-FEC bit error ratio; compared against the 1e-13 objective."},
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
        "note": "UNCHANGED at 800G; the FCS is a MAC-layer integrity check, orthogonal to the PCS RS-FEC(544,514).",
    }
    d["notes"] = (
        "800GbE management is Clause-45-only. The dominant MMDs are PMA/PMD "
        "(DEVAD 1), PCS (DEVAD 3, hosting the RS-FEC(544,514) control + "
        "corrected/uncorrected codeword + symbol-error counters + PCS-lane "
        "alignment status), and Auto-Negotiation (DEVAD 7). PHY identity "
        "(PHY ID, vendor OUI) lives in the standard Clause-45 PMA/PMD "
        "identifier registers; there is no Clause-22 BMCR/BMSR pair.")
    _write(p, d)


# ---------------------------------------------------------------------------
# L5..L13 + L14..L23 — layered/spec-grounded overlays (force key sections)
# ---------------------------------------------------------------------------
def _apply_l5(gd: Path) -> None:
    p = gd / "L5_ADI_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["analog_digital_interface_present"] = True
    d["signaling_summary"] = (
        "The 800G data path is PAM4 (4-level pulse-amplitude modulation) on "
        "each electrical/optical lane at 106.25 GBd. The electrical "
        "attachment (800GAUI-8 / 800GAUI-4) is differential PAM4 with "
        "transmitter FFE pre-emphasis + receiver CTLE/DFE equalisation and "
        "link training; compliance is measured via TDECQ-class eye / "
        "amplitude / return-loss metrics. The optical PMD modulates PAM4 "
        "onto 8 parallel fibers (DR8/SR8/VR8) or 2x4 CWDM wavelengths "
        "(2xFR4) on single-mode fiber. RS-FEC(544,514) is required because "
        "the raw PAM4 per-lane error ratio (~1e-4..1e-5) is far above the "
        "1e-13 link target.")
    d["pam4_signaling"] = {
        "modulation": "PAM4 (4 levels: 00/01/11/10 Gray-coded, 2 bits/symbol)",
        "baud_rate_GBd_per_100G_lane": 106.25,
        "lanes_8x100G": 8,
        "lanes_4x200G": 4,
        "fec": "RS-FEC(544,514) KP4 mandatory",
        "raw_lane_BER_pre_fec": "~1e-4 to 1e-5",
        "target_BER_post_fec": "1e-13",
        "tx_equalization": "Transmitter FFE (feed-forward equaliser) pre-emphasis",
        "rx_equalization": "Receiver CTLE + DFE (decision-feedback equaliser), adapted by link training",
        "compliance_metric": "TDECQ (Transmitter Dispersion Eye Closure Quaternary) for optical; eye-height/width + return loss for electrical",
    }
    d["pmd_variants"] = [
        {"variant": "800GBASE-DR8", "lanes": 8, "medium": "parallel single-mode fiber", "reach_min": ">=500 m", "wavelength": "~1310 nm O-band per lane"},
        {"variant": "800GBASE-SR8", "lanes": 8, "medium": "parallel multimode fiber (OM3/OM4/OM5)", "reach_min": ">=50-100 m", "wavelength": "~850 nm VCSEL per lane"},
        {"variant": "800GBASE-VR8", "lanes": 8, "medium": "very-short-reach multimode fiber", "reach_min": "very short (intra-rack)", "wavelength": "~850 nm VCSEL per lane"},
        {"variant": "800GBASE-2xFR4", "lanes": "2x4 CWDM wavelengths", "medium": "single-mode fiber", "reach_min": ">=2 km", "wavelength": "4-wavelength CWDM grid x2"},
    ]
    d["voltage_classes"] = [
        "800GAUI-8 / 800GAUI-4: low-voltage differential PAM4 SerDes I/O (typ ~0.8-1.2 V swing differential, process-node dependent).",
        "Optical PMD: PAM4-modulated optical power; transmitter optical modulation amplitude (OMA) + TDECQ per the DR8/SR8/VR8/2xFR4 PMD spec.",
        "MDC/MDIO management: 1.8 V / 1.2 V LVCMOS (modern node).",
    ]
    _write(p, d)


def _apply_l6(gd: Path) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    d.pop("fsm_states_csma_cd_half_duplex", None)
    d.pop("fsm_states_mdio_master_clause22", None)
    d["fsm_states_mac_tx"] = [
        {"name": "TX_IDLE", "description": "No frame to transmit; MAC emits idle; full-duplex so no carrier-sense deferral."},
        {"name": "TX_IPG", "description": "Inter-packet gap (nominal 96 BT, adjusted by deficit-idle-count for the multi-lane PCS) before the next frame."},
        {"name": "TX_PREAMBLE_SFD", "description": "Emit 7x0x55 preamble + 0xD5 SFD; arm CRC-32 for the next octet."},
        {"name": "TX_FRAME", "description": "Emit DA + SA + Type/Length + Payload + Pad; CRC-32 updates each octet."},
        {"name": "TX_FCS", "description": "Emit the 4-octet CRC-32 FCS."},
        {"name": "TX_TO_PCS", "description": "Stream the frame through the RS into the PCS, which 64b/66b-codes, transcodes, scrambles, RS-FEC-encodes and distributes across PCS lanes with alignment markers."},
    ]
    d["fsm_states_pcs"] = [
        {"name": "PCS_ENCODE", "description": "64b/66b block, 256b/257b transcode, scramble, RS-FEC(544,514) encode."},
        {"name": "PCS_DISTRIBUTE", "description": "Round-robin distribute encoded blocks across PCS lanes; insert periodic per-lane alignment markers."},
        {"name": "PCS_RX_BLOCK_LOCK", "description": "Receiver acquires 64b/66b sync-header lock per lane."},
        {"name": "PCS_RX_AM_LOCK", "description": "Receiver acquires alignment-marker lock; deskews and reorders PCS lanes."},
        {"name": "PCS_RX_FEC_DECODE", "description": "RS-FEC(544,514) decode: correct up to 15 symbol errors/codeword; mark uncorrectable codewords; update corrected/uncorrected + symbol-error counters."},
        {"name": "PCS_RX_DESCRAMBLE_DECODE", "description": "Descramble, 257b/256b un-transcode, 66b/64b decode, reassemble the MAC stream for the RS."},
    ]
    d["fsm_states_link_training"] = [
        {"name": "LT_FRAME_LOCK", "description": "Acquire training-frame lock on the electrical lane."},
        {"name": "LT_ADAPT", "description": "Exchange FFE/DFE coefficient request/response; adapt transmitter pre-emphasis + receiver equaliser."},
        {"name": "LT_DONE", "description": "Receiver-ready exchanged; equaliser converged; release lane to the PCS."},
        {"name": "LT_FAIL", "description": "Training timer expires before convergence; lane reported not-trained."},
    ]
    d["anti_deadlock_rule"] = (
        "800GbE is full-duplex only, so there is no CSMA/CD collision "
        "deadlock case. Progress under congestion is guaranteed by PAUSE / "
        "priority-based flow control (the receiver stalls the sender for a "
        "bounded pause-quanta interval rather than dropping frames). The "
        "PCS guarantees forward progress by deskewing + reordering lanes "
        "and by RS-FEC-correcting up to 15 symbol errors per codeword.")
    d["exit_from_reset_or_poweron"] = (
        "On power-on / reset: the PMA SerDes run link training to converge "
        "the equaliser on each electrical lane; the PCS then acquires "
        "64b/66b block lock and alignment-marker lock, deskews/reorders the "
        "PCS lanes, and enables RS-FEC decode; once the PCS is fully locked "
        "and FEC-aligned, the link is reported up via the Clause-45 PCS "
        "status MMD and the MAC begins transmitting frames.")
    d["timing_dependency_rule"] = (
        "All lanes are recovered clocks (embedded clock per PAM4 lane). The "
        "PCS tolerates bounded inter-lane skew via alignment markers + "
        "per-lane FIFOs; the RS adapts the 800 Gb/s MAC stream to the PCS "
        "lane structure. Management (MDC) is asynchronous to the data path.")
    _write(p, d)


def _apply_l7(gd: Path) -> None:
    p = gd / "L7_TEST_DEBUG.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_debug_architecture_present"] = True
    d["spec_provided_observability"] = [
        {"name": "RS-FEC corrected-codeword counter (PCS MMD)", "purpose": "Monitor how many (544,514) codewords were corrected; a proxy for raw-lane margin."},
        {"name": "RS-FEC uncorrected-codeword counter (PCS MMD)", "purpose": "Codewords with >15 symbol errors; directly impacts post-FEC BER."},
        {"name": "RS-FEC per-lane symbol-error counters (PCS MMD)", "purpose": "Per-FEC-lane corrected-symbol histogram; localises a weak physical lane."},
        {"name": "PCS-lane alignment-marker lock + mapping (PCS MMD)", "purpose": "Per-PCS-lane lock + the recovered physical-to-PCS lane mapping after deskew/reorder."},
        {"name": "PCS block-lock / hi-SER status (PCS MMD)", "purpose": "64b/66b sync lock + high-symbol-error-rate flag."},
        {"name": "Link-training status (PMA/PMD + AN MMD)", "purpose": "Per-lane training converged / failed; resolved technology from Auto-Negotiation."},
        {"name": "PRBS / square-wave test-pattern generators + checkers (PMA)", "purpose": "Per-lane PRBS13/PRBS31-class pattern generation + error checking for electrical/optical lane bring-up."},
        {"name": "Eye / TDECQ monitor (vendor MMD)", "purpose": "PAM4 eye-height/width or TDECQ estimate per lane."},
    ]
    d["error_detection_mechanisms"] = [
        "RS-FEC(544,514) uncorrectable codeword detection (>15 symbol errors).",
        "PCS 64b/66b sync-header / block-lock loss.",
        "PCS alignment-marker lock loss (deskew failure).",
        "MAC FCS (CRC-32) mismatch (downstream of FEC).",
        "Runt (< 64 B) and giant (> 1518/1522 B) frame detection.",
        "Link-training convergence-timer expiry.",
        "Per-lane PRBS error count above threshold.",
    ]
    d["test_modes"] = [
        {"name": "PRBS test patterns", "purpose": "Per-lane pseudo-random bit-sequence generation + checking for SerDes / optical bring-up."},
        {"name": "PCS scrambled-idle / local-fault test", "purpose": "Exercise the PCS encode/decode + lane-distribution path without a live MAC stream."},
        {"name": "RS-FEC error-injection", "purpose": "Inject up to 15 (correctable) and >15 (uncorrectable) symbol errors per codeword to validate the decoder + counters."},
        {"name": "Loopback (PMA / PCS / shallow)", "purpose": "Internal loopback at the PMA or PCS boundary for board test."},
        {"name": "Link-training force / disable", "purpose": "Force fixed equaliser coefficients to characterise the channel."},
    ]
    d["notes"] = (
        "800GbE relies heavily on PCS/FEC-level observability: the RS-FEC "
        "corrected/uncorrected codeword and per-lane symbol-error counters "
        "are the primary health metric, since the 1e-13 post-FEC target is "
        "achieved on top of a much worse (~1e-4..1e-5) raw PAM4 lane error "
        "ratio. PRBS generators/checkers and eye/TDECQ monitors provide "
        "physical-lane visibility. JTAG / scan / BIST are vendor-added.")
    _write(p, d)


def _apply_l8_rtl(gd: Path) -> None:
    p = gd / "L8_RTL_CONSTANTS.json"
    if not p.is_file():
        return
    d = _read(p)
    wp = _ensure_dict(d, "width_parameters")
    wp["MAC_RATE_Gbps"] = 800
    wp["PCS_LANES_8x100G"] = 8
    wp["PHYS_LANES_8x100G"] = 8
    wp["PHYS_LANES_4x200G"] = 4
    wp["BAUD_GBd_PER_100G_LANE"] = 106.25
    wp["MODULATION"] = "PAM4 (2 bits/symbol)"
    wp["RS_FEC_N"] = 544
    wp["RS_FEC_K"] = 514
    wp["RS_FEC_PARITY_SYMBOLS"] = 30
    wp["RS_FEC_SYMBOL_BITS"] = 10
    wp["RS_FEC_CORRECTABLE_SYMBOLS"] = 15
    wp["RS_FEC_GF"] = "GF(2^10)"
    wp["FCS_POLY_HEX"] = "0x04C11DB7"
    wp["MAC_ADDR_BITS"] = 48
    wp["ETHERTYPE_BITS"] = 16
    wp["MIN_FRAME_OCTETS"] = 64
    wp["MAX_FRAME_OCTETS_UNTAGGED"] = 1518
    wp["MAX_FRAME_OCTETS_VLAN"] = 1522
    wp["TARGET_BER_POST_FEC"] = "1e-13"
    d["key_constants_for_RTL_authoring"] = {
        "mac_rate_Gbps": 800,
        "frame_format": "IEEE 802.3 Clause-4 (preamble 7x0x55 + SFD 0xD5 + DA + SA + Type/Length + Payload + Pad + FCS) — PRESERVED",
        "min_frame_bytes": 64,
        "max_frame_bytes_untagged": 1518,
        "max_frame_bytes_vlan": 1522,
        "fcs_poly_hex": "0x04C11DB7",
        "fec": "RS-FEC(544,514) KP4 over GF(2^10), 30 parity symbols, corrects up to 15 symbol errors/codeword",
        "modulation": "PAM4",
        "baud_per_100G_lane_GBd": 106.25,
        "lanes": "8x100G or 4x200G",
        "layers": "MAC / RS / PCS / PMA / PMD",
        "management": "Clause-45 MDIO only (PMA/PMD=1, PCS=3, AN=7)",
        "is_full_duplex_only": True,
        "no_csma_cd": True,
        "no_clause22_registers": True,
    }
    d["default_signal_values_when_idle"] = {
        "MAC": "Emits IEEE 802.3 idle / inter-packet gap when no frame is pending.",
        "PCS": "Transmits scrambled idle + periodic alignment markers; FEC-encoded.",
        "PMD": "Continuous PAM4 modulation (idle symbols); lanes never go quiet on an up link.",
    }
    _write(p, d)


def _apply_l8_timing(gd: Path) -> None:
    p = gd / "L8_TIMING_WAVEFORM.json"
    if not p.is_file():
        return
    d = _read(p)
    d["data_rate_waveforms"] = {
        "800GBASE-8x100G": {"mac_rate_Gb_s": 800, "lanes": 8, "per_lane_Gb_s": 100, "modulation": "PAM4", "baud_GBd_per_lane": 106.25, "bits_per_symbol": 2},
        "800GBASE-4x200G": {"mac_rate_Gb_s": 800, "lanes": 4, "per_lane_Gb_s": 200, "modulation": "PAM4", "baud_GBd_per_lane": 106.25, "note": "200G/lane realised as 2x106.25 GBd PAM4 (companion 802.3dj uses true 200G/lane)"},
    }
    d["pam4_eye_reference"] = (
        "Three PAM4 eyes per unit interval (4 levels). Transmitter "
        "compliance via TDECQ (optical) or eye-height/width + return loss "
        "(electrical 800GAUI). Per-lane symbol period = 1 / 106.25 GBd "
        "~= 9.41 ps.")
    d["fec_timing"] = {
        "rs_fec": "RS-FEC(544,514)",
        "symbol_bits": 10,
        "codeword_symbols": 544,
        "parity_symbols": 30,
        "correctable_symbols_per_codeword": 15,
        "note": "FEC latency is part of the PCS budget; corrected/uncorrected codeword + symbol-error counters expose the FEC margin.",
    }
    d["general_timing_rule"] = (
        "Each PAM4 lane carries an embedded recovered clock at 106.25 GBd; "
        "the PCS tolerates bounded inter-lane skew via alignment markers + "
        "per-lane deskew FIFOs. The MAC frame timing (IPG nominal 96 BT, "
        "FCS) is preserved from base 802.3 and scaled to the 800 Gb/s rate.")
    d.pop("mii_signal_timing", None)
    d.pop("mdio_signal_timing", None)
    d.pop("csma_cd_timing", None)
    _write(p, d)


def _apply_l9(gd: Path) -> None:
    p = gd / "L9_INTEGRATION_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["module_role"] = (
        "800 Gb/s Ethernet PHY (RS / PCS / PMA / PMD) plus the 800 Gb/s MAC "
        "that preserves the IEEE 802.3 Clause-4 frame format. Defines the "
        "800GMII reconciliation, the PCS (64b/66b + 256b/257b + "
        "RS-FEC(544,514) + multi-lane distribution), the PMA bit-mux/retime, "
        "and the PMD (800GBASE-DR8/SR8/VR8/2xFR4) over 8x100G or 4x200G "
        "PAM4 lanes. Management is Clause-45-only.")
    io = _ensure_dict(d, "integration_overview")
    io.clear()
    io.update({
        "mac_rate_Gbps": 800,
        "electrical_lanes_8x100G": 8,
        "electrical_lanes_4x200G": 4,
        "optical_lanes_DR8_SR8_VR8": 8,
        "baud_GBd_per_100G_lane": 106.25,
        "modulation": "PAM4",
        "fec": "RS-FEC(544,514) KP4",
        "target_BER_post_fec": "1e-13",
        "layers": "MAC / RS / PCS / PMA / PMD",
        "management": "Clause-45 MDIO (PMA/PMD=1, PCS=3, AN=7)",
        "preamble_octets": 7,
        "sfd_octet": "0xD5",
        "fcs_octets": 4,
        "min_frame_octets": 64,
        "max_frame_octets_untagged": 1518,
        "max_frame_octets_vlan": 1522,
        "full_duplex_only": True,
    })
    d["interface_categories"] = [
        "MAC (Clause 4) at 800 Gb/s — frame assembly/disassembly, FCS, address recognition, IPG, PAUSE/PFC flow control. Frame format PRESERVED.",
        "RS / 800GMII — Reconciliation Sublayer mapping the 800 Gb/s MAC stream to the PCS.",
        "PCS — 64b/66b + 256b/257b transcoding, scrambling, RS-FEC(544,514), multi-PCS-lane distribution with alignment markers.",
        "PMA — bit-mux / retime / lane reorder between PCS lanes and physical lanes.",
        "PMD — 800GBASE-DR8/SR8/VR8/2xFR4 electro-optical attachment; PAM4 at 106.25 GBd/lane.",
        "800GAUI-8 / 800GAUI-4 — chip-to-module / chip-to-chip electrical AUI.",
        "MDC + MDIO (Clause 45) — management bus for the PMA/PMD, PCS, and AN MMDs.",
    ]
    d["interconnect_topologies_supported"] = [
        "Switched point-to-point full-duplex link (the only 800G topology).",
        "Pluggable-optics link (OSFP / QSFP-DD800) carrying one 800G channel.",
        "Breakout: one 800G port to 8x100G or 2x400G / 4x200G via the lane-granular PHY.",
        "Active electrical cable (AEC) / active optical cable (AOC) for short reach.",
    ]
    d["low_power_modes"] = {
        "Active": "All lanes up; PCS locked + FEC-aligned; MAC streaming.",
        "Low_Power_Idle_EEE": "Per Clause-78-class EEE if supported at 800G (PHY analog deep-sleep when MAC has no traffic).",
        "PMD_TX_disable": "Per-lane transmit disable via the Clause-45 PMA/PMD MMD for module power-down / safety.",
    }
    d["soc_dependent_items"] = [
        "SerDes IP choice (100 Gb/s/lane PAM4 SerDes for 8x100G, or 200 Gb/s/lane for 4x200G).",
        "RS-FEC(544,514) hard-macro placement + latency budget.",
        "PCS lane-distribution + deskew FIFO depth sizing for the target inter-lane skew.",
        "Pluggable-module form factor (OSFP / QSFP-DD800) + management (CMIS).",
        "Link-training engine + Auto-Negotiation (Clause 73/136-class).",
        "Clause-45 MDIO master + MMD address decode.",
        "Reference-clock + reset distribution to all lanes.",
    ]
    _write(p, d)


def _apply_l10(gd: Path) -> None:
    p = gd / "L10_TEST_CASES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_cases_present"] = (
        "partial — IEEE Std 802.3df-2024 specifies PCS / FEC / PMD "
        "behavioral + electrical/optical compliance per clause, but no "
        "concrete testbench. Conformance is per-clause PICS + industry "
        "interop (Ethernet Alliance / UNH-IOL 800G).")
    d["derived_compliance_test_categories"] = [
        "MAC: transmit/receive a 64-byte minimum frame at 800 Gb/s.",
        "MAC: transmit/receive a 1518-byte max untagged + 1522-byte VLAN frame.",
        "MAC: FCS (CRC-32, 0x04C11DB7) verified on a known vector (ASCII '123456789' -> 0xCBF43926).",
        "MAC: frame format byte-for-byte identical to base 802.3 (preamble/SFD/DA/SA/Type/Payload/FCS).",
        "PCS: 64b/66b block lock acquisition.",
        "PCS: 256b/257b transcode round-trip.",
        "PCS: alignment-marker lock + PCS-lane deskew/reorder under injected skew.",
        "RS-FEC: correct up to 15 symbol errors per (544,514) codeword.",
        "RS-FEC: mark uncorrectable codeword (>15 symbol errors) + increment uncorrected counter.",
        "RS-FEC: corrected/uncorrected codeword + per-lane symbol-error counters increment correctly.",
        "PAM4: 4-level eye / TDECQ compliance at 106.25 GBd per lane.",
        "PMD: 800GBASE-DR8 (8x100G SMF >=500 m) transmitter/receiver optical compliance.",
        "PMD: 800GBASE-SR8 (8x100G MMF) compliance.",
        "PMD: 800GBASE-VR8 (very-short MMF) compliance.",
        "PMD: 800GBASE-2xFR4 (2x4 CWDM SMF >=2 km) compliance.",
        "Link: post-FEC BER <= 1e-13 over the compliance channel.",
        "Link training: FFE/DFE coefficient adaptation converges within the training timer on each electrical lane.",
        "Auto-Negotiation: Clause-73-class base/next page exchange + resolved technology.",
        "Management: Clause-45 MDIO address-then-data to PMA/PMD (1), PCS (3), AN (7) MMDs.",
        "Full-duplex: independent simultaneous TX + RX; no CSMA/CD.",
        "PAUSE / PFC: 802.3x / 802.1Qbb flow control honored in full-duplex.",
        "Breakout: 800G to 8x100G / 4x200G lane mapping.",
    ]
    _write(p, d)


def _apply_l11(gd: Path) -> None:
    p = gd / "L11_OTP_CONTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    d["otp_present"] = False
    d["otp_equivalent_factory_burned_fields"] = [
        {"field": "MAC Address (48 bits)", "width_bits": 48, "location": "EEPROM / OTP / module EEPROM", "note": "Per-device Universally Administered MAC from the vendor OUI; I/G=0, U/L=0."},
        {"field": "PMA/PMD PHY Identifier (Clause-45 DEVAD 1)", "width_bits": 32, "location": "ROM / metal-mask", "note": "Vendor OUI + model + revision in the Clause-45 PMA/PMD identifier registers (no Clause-22 PHY ID at 800G)."},
        {"field": "Module identity / CMIS (pluggable EEPROM)", "width_bits": "N/A", "location": "Module EEPROM (CMIS)", "note": "OSFP / QSFP-DD800 module type, supported 800GBASE PMD variant, vendor + serial — read over the module two-wire interface, not part of 802.3df itself."},
        {"field": "SerDes / FEC trim + default equaliser presets", "width_bits": "vendor", "location": "OTP / fuse", "note": "Per-lane analog trim + default FFE/DFE presets locked at production; vendor-specific."},
    ]
    d["notes"] = (
        "IEEE 802.3df does not define OTP/fuse content as a protocol "
        "concept. 800G endpoints store the 48-bit MAC in non-volatile "
        "memory; PHY identity lives in the Clause-45 PMA/PMD identifier "
        "registers; pluggable-module identity is in the CMIS module EEPROM. "
        "SerDes/FEC analog trim is vendor OTP.")
    _write(p, d)


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
        "1. Power-on / reset; PMA SerDes start per-lane link training on the 8x100G (or 4x200G) electrical lanes.",
        "2. Link training exchanges FFE/DFE coefficient requests/responses; transmitter pre-emphasis + receiver equaliser converge; receiver-ready exchanged per lane.",
        "3. Auto-Negotiation (Clause-73-class) resolves the technology + FEC.",
        "4. PCS acquires 64b/66b block lock on each PCS lane.",
        "5. PCS acquires alignment-marker lock; deskews + reorders the PCS lanes onto their physical lanes.",
        "6. RS-FEC(544,514) decode is enabled + FEC-aligned; corrected/uncorrected codeword counters begin tracking margin.",
        "7. PCS reports link up via the Clause-45 PCS status MMD; the RS presents a clean 800GMII to the MAC.",
        "8. MAC begins transmitting/receiving IEEE 802.3 frames at 800 Gb/s.",
    ]
    d["tx_frame_sequence_full_duplex"] = [
        "1. MAC client signals a frame-transmit request.",
        "2. MAC computes CRC-32 over DA + SA + Type/Length + Payload + Pad as it streams (frame format preserved).",
        "3. After the inter-packet gap, MAC emits preamble (7x0x55) + SFD (0xD5) + DA + SA + Type/Length + Payload + Pad + FCS through the RS.",
        "4. PCS 64b/66b-codes, 256b/257b-transcodes, scrambles, RS-FEC(544,514)-encodes, and distributes the blocks across PCS lanes with alignment markers.",
        "5. PMA bit-muxes the PCS lanes onto the physical lanes; PMD PAM4-modulates each lane at 106.25 GBd.",
        "6. Far-end PMD/PMA recover + deskew; PCS FEC-decodes + reassembles; RS hands the frame to the MAC which checks FCS and delivers it.",
    ]
    d["rx_frame_sequence"] = [
        "1. PMD/PMA recover PAM4 symbols per lane (embedded clock).",
        "2. PCS achieves block lock + alignment-marker lock; deskews/reorders PCS lanes.",
        "3. RS-FEC(544,514) decode corrects up to 15 symbol errors/codeword; marks uncorrectable codewords.",
        "4. PCS descrambles, un-transcodes, 66b/64b-decodes, reassembles the MAC stream.",
        "5. MAC detects preamble/SFD, captures DA..FCS, recomputes CRC-32; on mismatch discards + increments FCS-error counter.",
        "6. On valid FCS + length, deliver the frame to the MAC client.",
    ]
    d["fec_decode_sequence"] = [
        "1. Receive a complete RS-FEC(544,514) codeword (544 ten-bit symbols).",
        "2. Compute syndromes; if all zero, codeword is clean.",
        "3. If <=15 symbols erred, locate + correct them (Berlekamp-Massey / Chien / Forney); increment corrected-codeword + per-lane symbol-error counters.",
        "4. If >15 symbols erred, codeword is uncorrectable: mark it, flag the spanning 66b blocks, increment the uncorrected-codeword counter.",
        "5. Aggregate counters drive the post-FEC BER estimate against the 1e-13 target.",
    ]
    d["pause_frame_sequence"] = [
        "1. Receive-side congestion crosses the high watermark.",
        "2. MAC Control builds a PAUSE frame (DA = 01:80:C2:00:00:01, EtherType 0x8808, opcode 0x0001, pause_quanta) or a PFC frame (802.1Qbb).",
        "3. The frame traverses the same RS/PCS/PMA/PMD path at 800 Gb/s.",
        "4. The partner MAC stalls transmission for the indicated quanta; resumes on expiry or on a quanta=0 frame.",
    ]
    _write(p, d)


def _apply_l13(gd: Path) -> None:
    p = gd / "L13_LAB_CALIBRATION.json"
    if not p.is_file():
        return
    d = _read(p)
    d["lab_calibration_present"] = False
    d["lab_measurement_targets_from_spec"] = [
        {"name": "PAM4 transmitter eye / TDECQ", "purpose": "Per-lane PAM4 transmitter compliance (TDECQ for optical; eye + return loss for electrical 800GAUI) at 106.25 GBd."},
        {"name": "Post-FEC BER", "purpose": "Verify <=1e-13 post-FEC over the compliance channel using the RS-FEC(544,514) corrected/uncorrected counters."},
        {"name": "Pre-FEC raw-lane BER margin", "purpose": "Measure per-lane raw error ratio (~1e-4..1e-5) against the FEC budget."},
        {"name": "RS-FEC symbol-error distribution", "purpose": "Per-lane corrected-symbol histogram to localise a weak lane."},
        {"name": "Inter-lane skew + deskew margin", "purpose": "Verify the PCS deskew FIFOs absorb the worst-case medium skew."},
        {"name": "PMD optical power / OMA (per variant)", "purpose": "DR8/SR8/VR8/2xFR4 transmitter optical modulation amplitude + extinction ratio."},
        {"name": "Link-training convergence time", "purpose": "Verify FFE/DFE adapt within the training timer on each lane."},
    ]
    d["notes"] = (
        "IEEE 802.3df does not specify on-chip calibration loops; the PHY "
        "digital (MAC/RS/PCS) is verified by testbench, while the PAM4 "
        "analog (SerDes, optics) requires per-PMD compliance lab tests "
        "(TDECQ, eye, return loss, OMA, BER) per the relevant 800GBASE PMD "
        "clause. The RS-FEC counters provide the primary in-system margin "
        "instrument.")
    _write(p, d)


def _apply_l14(gd: Path) -> None:
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["spec_version"] = "IEEE Std 802.3df-2024 (800 Gigabit Ethernet, approved 16 February 2024)"
    f["previous_versions"] = [
        "IEEE Std 802.3ba-2010 — 40 GbE + 100 GbE, multi-lane fiber, introduced the multi-PCS-lane / alignment-marker architecture.",
        "IEEE Std 802.3bj-2014 — 100GBASE-KR4/CR4 backplane + twinax with RS-FEC.",
        "IEEE Std 802.3by-2016 — 25 GbE single-lane.",
        "IEEE Std 802.3bs-2017 — 200 GbE + 400 GbE, first PAM4 + RS-FEC(544,514) multi-lane PHYs (200GBASE-*, 400GBASE-*).",
        "IEEE Std 802.3ck-2022 — 100 Gb/s/lane PAM4 electrical (CR/KR/DR), the lane technology underpinning 800GBASE 8x100G.",
        "IEEE Std 802.3df-2024 — 800 Gigabit Ethernet (this spec) using 100 Gb/s lanes.",
    ]
    f["key_changes"] = [
        {"version": "802.3df-2024", "summary": "First 800 Gb/s Ethernet. MAC at 800 Gb/s preserving the Clause-4 frame format + min/max frame size; PHY over 8x100G or 4x200G PAM4 lanes at 106.25 GBd with RS-FEC(544,514); BER target 1e-13; PMD variants 800GBASE-DR8/SR8/VR8/2xFR4. Project started Jan 2022; scope split Nov 2022 (1.6T + 200G/lane to 802.3dj); approved 16 Feb 2024."},
    ]
    f["future_versions_industry_outline"] = [
        {"version": "IEEE P802.3dj", "summary": "1.6 Tb/s Ethernet + 200/400/800 Gb/s + 1.6 Tb/s PHYs using 200 Gb/s/lane; split from 802.3df in Nov 2022; timeline targets completion July 2026."},
        {"version": "IEEE P802.3dj 200G/lane PMDs", "summary": "256b/257b x RS-FEC(544,514) (optionally concatenated inner Hamming (128,120)) x PAM4 at ~113.4375 GBd, raising per-lane rate to 200 Gb/s and enabling 4x200G 800GbE + 8x200G 1.6TbE."},
    ]
    f["backward_compat_traps"] = [
        {"trap_name": "frame_format_preserved_but_phy_incompatible",
         "rule": "800GbE keeps the Clause-4 MAC frame, so frames are interoperable end-to-end, BUT the PHY (PAM4, RS-FEC(544,514), multi-lane) is entirely different from 10/100/1000 Mb/s MII/GMII PHYs.",
         "trap": "An 800G PHY cannot link to a base-802.3 MII/GMII PHY — only the frames are compatible after both ends are up."},
        {"trap_name": "8x100G_vs_4x200G_lane_mismatch",
         "rule": "800GbE can be 8 lanes of 100 Gb/s OR 4 lanes of 200 Gb/s; 802.3df targets 100 Gb/s lanes while 802.3dj adds true 200 Gb/s lanes.",
         "trap": "An 8x100G module and a 4x200G module are not directly interoperable at the electrical lane level without a gearbox/retimer."},
        {"trap_name": "fec_must_match",
         "rule": "RS-FEC(544,514) KP4 is mandatory; 802.3dj 200G/lane may add a concatenated inner Hamming(128,120) FEC.",
         "trap": "Mismatched FEC schemes between link partners prevent FEC alignment and the link never comes up despite clean SerDes."},
        {"trap_name": "clause45_only_management",
         "rule": "800G PHYs expose only Clause-45 MMDs; there is no Clause-22 BMCR/BMSR.",
         "trap": "Legacy management software that pokes Clause-22 register 0/1 will get no response from an 800G PHY."},
    ]
    f["version_naming_history_note"] = (
        "IEEE 802.3 amendments use letter suffixes. The high-speed PAM4 "
        "lineage is 802.3bs (200/400G, 2017) -> 802.3ck (100G/lane "
        "electrical, 2022) -> 802.3df (800G using 100G lanes, 2024) -> "
        "802.3dj (1.6T + 200G/lane, ~2026). The Clause-4 MAC frame format "
        "is preserved across all of them.")
    d["fields"] = f
    _write(p, d)


def _apply_l15(gd: Path) -> None:
    p = gd / "L15_ENCODING_TABLES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["mac_frame_table"] = {
        "header_columns": ["Field", "Octets", "Value / Meaning"],
        "rows": [
            ["Preamble", 7, "0x55 x7 (UNCHANGED at 800G)"],
            ["SFD", 1, "0xD5"],
            ["Destination Address", 6, "48-bit MAC; I/G + U/L bits"],
            ["Source Address", 6, "48-bit unicast MAC"],
            ["EtherType / Length", 2, ">=0x0600 = EtherType; <=0x05DC = Length"],
            ["Payload", "46..1500", "MAC client data (zero-padded)"],
            ["FCS", 4, "IEEE 802.3 CRC-32, poly 0x04C11DB7 (orthogonal to PCS RS-FEC)"],
            ["Total (untagged)", "64..1518", "Min 64 B, max 1518 B (PRESERVED at 800G)"],
            ["VLAN tag", "+4", "TPID 0x8100 + TCI; raises max to 1522 B"],
        ],
    }
    f["pam4_levels_table"] = {
        "header_columns": ["PAM4 symbol (Gray)", "Bits", "Relative level"],
        "rows": [
            ["00", "0,0", "level 0 (lowest)"],
            ["01", "0,1", "level 1"],
            ["11", "1,1", "level 2"],
            ["10", "1,0", "level 3 (highest)"],
        ],
    }
    f["rs_fec_table"] = {
        "header_columns": ["Parameter", "Value"],
        "rows": [
            ["FEC", "Reed-Solomon RS-FEC(544,514) (KP4)"],
            ["Galois field", "GF(2^10) — 10-bit symbols"],
            ["Codeword length n", "544 symbols"],
            ["Message length k", "514 symbols"],
            ["Parity symbols", "30"],
            ["Correctable symbol errors / codeword", "15"],
            ["Target post-FEC BER", "1e-13"],
        ],
    }
    f["lane_options_table"] = {
        "header_columns": ["Option", "Lanes", "Per-lane rate", "Modulation", "Baud/lane"],
        "rows": [
            ["8x100G", 8, "100 Gb/s", "PAM4", "106.25 GBd"],
            ["4x200G", 4, "200 Gb/s", "PAM4", "106.25 GBd x2 (802.3df) / 113.4375 GBd (802.3dj 200G/lane)"],
        ],
    }
    f["pmd_variants_table"] = {
        "header_columns": ["Variant", "Lanes", "Medium", "Reach (min)"],
        "rows": [
            ["800GBASE-DR8", 8, "parallel single-mode fiber", ">=500 m"],
            ["800GBASE-SR8", 8, "parallel multimode fiber", ">=50-100 m"],
            ["800GBASE-VR8", 8, "very-short-reach MMF", "intra-rack"],
            ["800GBASE-2xFR4", "2x4 CWDM", "single-mode fiber", ">=2 km"],
        ],
    }
    f["clause45_devad_table"] = {
        "header_columns": ["DEVAD", "MMD", "Purpose"],
        "rows": [
            [1, "PMA/PMD", "Per-lane control/status, link training, PMD compliance"],
            [3, "PCS", "64b/66b + 256b/257b + RS-FEC(544,514) control + counters + alignment status"],
            [7, "Auto-Negotiation", "Clause-73-class base/next page + resolved technology"],
            ["30-31", "Vendor-specific", "SerDes/eye/temperature diagnostics"],
        ],
    }
    f["tables"] = [
        "MAC frame format (IEEE 802.3 Clause 4, preserved at 800G)",
        "PAM4 4-level encoding (2 bits/symbol)",
        "RS-FEC(544,514) parameters",
        "800GBASE PMD variants (DR8/SR8/VR8/2xFR4)",
        "Clause-45 MMD DEVAD assignments",
    ]
    d["fields"] = f
    _write(p, d)


def _apply_l16(gd: Path) -> None:
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["must_have_properties"] = [
        "800 Gb/s MAC PRESERVING the IEEE 802.3 Clause-4 frame format (preamble 7x0x55 + SFD 0xD5 + DA + SA + Type/Length + Payload + Pad + FCS).",
        "PRESERVED min (64 B) and max (1518 B / 1522 B VLAN) frame size.",
        "FCS = IEEE 802.3 CRC-32, polynomial 0x04C11DB7.",
        "RS-FEC(544,514) KP4 forward error correction in the PCS.",
        "PAM4 modulation at 106.25 GBd per 100 Gb/s lane.",
        "8x100G or 4x200G lane structure.",
        "MAC / RS / PCS / PMA / PMD layering per IEEE 802.3.",
        "PCS 64b/66b + 256b/257b transcoding + multi-lane distribution with alignment markers.",
        "Post-FEC BER <= 1e-13.",
        "Clause-45 MDIO management (PMA/PMD=1, PCS=3, AN=7).",
        "Full-duplex operation only (no CSMA/CD).",
        "PAUSE / PFC flow control (802.3x / 802.1Qbb).",
        "One of the 800GBASE-DR8 / SR8 / VR8 / 2xFR4 PMDs.",
    ]
    f["must_not_have_properties"] = [
        "Any CSMA/CD or half-duplex operation at 800 Gb/s.",
        "A Clause-22 BMCR/BMSR register file (800G is Clause-45-only).",
        "Operation without RS-FEC (the raw PAM4 lane BER is far above target).",
        "Modifying the Clause-4 MAC frame format or the min/max frame size.",
        "NRZ line modulation on the 100 Gb/s lanes (800GBASE uses PAM4).",
    ]
    f["compliance_failure_modes"] = [
        {"mode": "Uncorrectable FEC codeword", "trigger": ">15 symbol errors in an RS-FEC(544,514) codeword; frame discarded; uncorrected counter increments."},
        {"mode": "PCS block-lock loss", "trigger": "64b/66b sync-header errors exceed threshold."},
        {"mode": "Alignment-marker lock loss", "trigger": "Receiver cannot deskew/reorder PCS lanes."},
        {"mode": "Link-training failure", "trigger": "SerDes equaliser fails to converge within the training timer."},
        {"mode": "Post-FEC BER above 1e-13", "trigger": "Sustained pre-FEC error ratio exceeds the FEC budget."},
        {"mode": "FCS error", "trigger": "MAC CRC-32 mismatch (downstream of FEC)."},
    ]
    f["min_link_constraint"] = (
        "An 800GBASE link shall reach PCS block + alignment-marker lock and "
        "FEC alignment, with post-FEC BER <= 1e-13, over the compliance "
        "channel for its PMD variant (DR8/SR8/VR8/2xFR4).")
    f["reset_behavior_compliance"] = (
        "On reset the SerDes re-train, the PCS re-acquires block + "
        "alignment lock, and FEC re-aligns before the link is reported up "
        "via the Clause-45 PCS status MMD.")
    f["frame_format_preservation_compliance"] = (
        "The 800 Gb/s MAC frame shall be byte-for-byte identical to base "
        "IEEE 802.3 (preamble/SFD/DA/SA/Type/Length/Payload/Pad/FCS) and "
        "the min/max frame size shall be unchanged — a mandatory P802.3df "
        "objective.")
    d["fields"] = f
    _write(p, d)


def _apply_l17(gd: Path) -> None:
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["channels"] = [
        {"name": "800GAUI-8 TX[0..7]", "interface": "800GAUI-8", "direction": "chip -> module/chip", "purpose": "8 differential PAM4 transmit lanes, 100 Gb/s each, 106.25 GBd.", "active_levels": "differential PAM4 (4 levels)", "idle_level": "continuous PAM4 idle (never quiet on up link)"},
        {"name": "800GAUI-8 RX[0..7]", "interface": "800GAUI-8", "direction": "module/chip -> chip", "purpose": "8 differential PAM4 receive lanes, 100 Gb/s each.", "active_levels": "differential PAM4", "idle_level": "continuous PAM4 idle"},
        {"name": "800GAUI-4 TX/RX[0..3]", "interface": "800GAUI-4", "direction": "bidirectional (per pair)", "purpose": "4 differential PAM4 lanes, 200 Gb/s each (4x200G option).", "active_levels": "differential PAM4", "idle_level": "continuous PAM4 idle"},
        {"name": "PMD fiber lanes", "interface": "PMD (DR8/SR8/VR8/2xFR4)", "direction": "PHY <-> fiber", "purpose": "8 parallel fibers (DR8/SR8/VR8) or 2x4 CWDM wavelengths (2xFR4), PAM4 optical.", "active_levels": "PAM4 optical OMA", "idle_level": "PAM4 idle symbols"},
        {"name": "MDC", "interface": "Clause-45 MDIO", "direction": "STA -> PHY", "purpose": "Management clock.", "active_levels": "LVCMOS", "idle_level": "running"},
        {"name": "MDIO", "interface": "Clause-45 MDIO", "direction": "STA <-> PHY (three-state)", "purpose": "Management data (two-cycle address-then-data).", "active_levels": "LVCMOS three-state", "idle_level": "logic-1 (pulled high)"},
    ]
    f["logical_signaling_levels"] = [
        {"name": "Active PAM4 lane", "meaning": "Continuous 4-level PAM4 symbols at 106.25 GBd carrying FEC-encoded PCS blocks."},
        {"name": "PCS alignment marker", "meaning": "Periodic per-PCS-lane code group for receiver deskew/reorder."},
        {"name": "FEC codeword", "meaning": "RS-FEC(544,514): 544 ten-bit symbols (514 message + 30 parity)."},
        {"name": "Inter-packet gap", "meaning": "IEEE 802.3 idle between MAC frames (full-duplex)."},
        {"name": "Link-training frame", "meaning": "Electrical-lane FFE/DFE coefficient request/response during bring-up."},
    ]
    f["channel_counts"] = {
        "electrical_lanes_8x100G": 8,
        "electrical_lanes_4x200G": 4,
        "optical_lanes_DR8_SR8_VR8": 8,
        "cwdm_wavelengths_2xFR4": 8,
        "mdio_wires": 2,
        "mac_address_octets": 6,
        "ethertype_width_octets": 2,
        "fcs_width_octets": 4,
        "rs_fec_n": 544,
        "rs_fec_k": 514,
        "baud_GBd_per_100G_lane": 106.25,
    }
    f["global_signals"] = [
        {"name": "RESET#", "purpose": "PHY hardware reset."},
        {"name": "REFCLK", "purpose": "Reference clock for the SerDes lanes."},
        {"name": "MDC/MDIO", "purpose": "Clause-45 management bus."},
        {"name": "MOD sidebands", "purpose": "Pluggable-module low-speed control (CMIS) for OSFP/QSFP-DD800."},
    ]
    f["dependency_graph"] = {
        "common_rule": "MAC -> RS (800GMII) -> PCS (encode + FEC + lane-distribute) -> PMA (bit-mux/retime) -> PMD (PAM4). Each lane carries an embedded clock; the PCS deskews/reorders via alignment markers.",
        "data_dependency": "Frame TX requires PCS lock + FEC alignment on the far end; RX requires PMD symbol recovery -> PCS block/AM lock -> FEC decode -> MAC reassembly.",
    }
    f["handshake_pairs"] = [
        {"name": "Link training", "from": "either", "to": "either", "rule": "Per-lane FFE/DFE coefficient exchange until receiver-ready."},
        {"name": "PCS lock", "from": "PHY", "to": "PHY", "rule": "Block lock then alignment-marker lock then FEC alignment."},
        {"name": "MDIO Clause-45", "from": "STA", "to": "PHY", "rule": "Address cycle then data cycle on the same DEVAD."},
        {"name": "PAUSE/PFC", "from": "either", "to": "either", "rule": "Flow control via 802.3x / 802.1Qbb frames (full-duplex)."},
    ]
    f["ordering_rules"] = {
        "bit_order_within_byte": "LSB-first on the MAC service interface; FCS appended MSB-byte-first (UNCHANGED from base 802.3).",
        "byte_order_within_field": "Network byte order (big-endian) for DA/SA/EtherType/VLAN.",
        "lane_order": "PCS distributes blocks round-robin across PCS lanes; alignment markers let the receiver recover the original order regardless of physical-lane skew/reorder.",
    }
    d["fields"] = f
    _write(p, d)


def _apply_l18(gd: Path) -> None:
    p = gd / "L18_INTERCONNECT_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["topology_type"] = (
        "Switched point-to-point full-duplex link only (no shared medium / "
        "CSMA/CD at 800G). One 800 Gb/s MAC per port, connected through its "
        "RS/PCS/PMA/PMD to one PMD-class medium (8 parallel fibers or 2x4 "
        "CWDM wavelengths), typically inside an OSFP / QSFP-DD800 module. "
        "The PHY internally spreads the 800 Gb/s stream across multiple PCS "
        "lanes with alignment markers.")
    f["supported_topologies"] = [
        {"name": "Switched point-to-point full-duplex", "description": "The only 800G topology; every link is collision-free."},
        {"name": "Pluggable-optics link", "description": "OSFP / QSFP-DD800 module carrying one 800G channel over DR8/SR8/VR8/2xFR4."},
        {"name": "Breakout", "description": "One 800G port broken out to 8x100G or 2x400G / 4x200G via the lane-granular PHY."},
        {"name": "AEC / AOC", "description": "Active electrical / active optical cable for short reach."},
    ]
    f["master_slave_role_summary"] = [
        {"role": "MAC (DTE)", "description": "Owns 800 Gb/s frame assembly + CRC-32; full-duplex (no carrier sense)."},
        {"role": "PCS", "description": "64b/66b + 256b/257b + RS-FEC(544,514) + lane distribution/deskew."},
        {"role": "PMA/PMD", "description": "Bit-mux/retime + PAM4 electro-optical attachment over 8x100G or 4x200G lanes."},
        {"role": "Station Management Entity (STA)", "description": "Clause-45 MDIO master configuring/monitoring the PMA/PMD, PCS, and AN MMDs."},
    ]
    f["interconnect_role"] = (
        "The 800GAUI electrical lanes and the PMD fiber lanes are strictly "
        "point-to-point; there is no fan-out on the data path. The Clause-45 "
        "MDIO bus is a shared management bus addressed by PRTAD.")
    f["ordering_guarantees"] = {
        "in_link_ordering": "MAC delivers received frames in order; the PCS recovers lane order via alignment markers.",
        "flow_control": "PAUSE applies to all traffic on a link; PFC (802.1Qbb) is per-priority.",
    }
    f["memory_vs_peripheral_regions"] = (
        "No MAC-layer address space. PHY management is the Clause-45 MMD "
        "register space (PMA/PMD, PCS, AN). PHY identity is in the "
        "Clause-45 PMA/PMD identifier registers; module identity is in the "
        "CMIS module EEPROM.")
    f["device_classification"] = {
        "switch_ASIC_port": "One 800G MAC + PHY per port; 51.2 Tb/s silicon = 64 x 800G.",
        "pluggable_module": "OSFP / QSFP-DD800 optics implementing a DR8/SR8/VR8/2xFR4 PMD.",
        "NIC_DPU": "800G host adapter (MAC + PHY + PCIe / chiplet host interface).",
        "AEC_AOC": "Active cable with retimer + PHY at each end.",
    }
    d["fields"] = f
    _write(p, d)


def _apply_l19(gd: Path) -> None:
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["constraints_present"] = False
    f["electrical_channel_constraints"] = {
        "modulation": "PAM4",
        "baud_GBd_per_100G_lane": 106.25,
        "lanes_8x100G": 8,
        "lanes_4x200G": 4,
        "fec": "RS-FEC(544,514) KP4 mandatory",
        "target_BER_post_fec": "1e-13",
        "raw_lane_BER_pre_fec": "~1e-4 to 1e-5",
        "tx_equalization": "FFE pre-emphasis",
        "rx_equalization": "CTLE + DFE adapted by link training",
        "compliance_metric": "TDECQ (optical) / eye + return loss (electrical 800GAUI)",
        "aui": "800GAUI-8 (8x100G) / 800GAUI-4 (4x200G)",
    }
    f["notes"] = (
        "IEEE 802.3df specifies PAM4 transmitter/receiver electrical + "
        "optical compliance per PMD/AUI clause but imposes no PDK-specific "
        "SDC/floorplan constraints. The MAC/RS/PCS digital integrates as "
        "synchronous logic + a 100 Gb/s/lane PAM4 SerDes + an RS-FEC(544,514) "
        "macro. Per-PMD optical/electrical specs (TDECQ, OMA, return loss) "
        "live in the relevant 800GBASE-DR8/SR8/VR8/2xFR4 PMD clause.")
    d["fields"] = f
    _write(p, d)


def _apply_l20(gd: Path) -> None:
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["dft_present"] = "partial"
    f["in_band_test_facilities"] = [
        {"name": "PRBS generators/checkers (PMA)", "purpose": "Per-lane PRBS13/PRBS31-class pattern for SerDes/optical bring-up."},
        {"name": "RS-FEC error-injection + counters (PCS MMD)", "purpose": "Inject correctable/uncorrectable symbol errors; read corrected/uncorrected + per-lane symbol-error counters."},
        {"name": "PCS block-lock / alignment-marker status (PCS MMD)", "purpose": "Observe lock + lane-mapping via Clause-45."},
        {"name": "Loopback (PMA / PCS)", "purpose": "Internal loopback for board test."},
        {"name": "Link-training force/disable (PMA/PMD MMD)", "purpose": "Fix equaliser coefficients to characterise the channel."},
        {"name": "Eye / TDECQ monitor (vendor MMD)", "purpose": "Per-lane PAM4 eye estimate."},
    ]
    f["internal_diagnostics_observability"] = [
        "RS-FEC(544,514) corrected/uncorrected codeword counters.",
        "RS-FEC per-lane symbol-error counters.",
        "PCS block-lock, alignment-marker lock, hi-SER flags.",
        "Link-training converged/failed per lane.",
        "Per-lane PRBS error counts.",
        "Estimated post-FEC BER vs 1e-13 target.",
    ]
    f["out_of_band_test_facilities"] = [
        "BERT (bit error rate tester) for per-lane PAM4 margin.",
        "Sampling/real-time scope for TDECQ / eye.",
        "Optical reference receiver for DR8/SR8/VR8/2xFR4 PMD compliance.",
        "800G protocol analyzer for frame + PCS capture.",
        "JTAG (vendor) for scan/boundary-scan.",
    ]
    f["notes"] = (
        "IEEE 802.3df mandates the PCS/FEC observability (lock + counters) "
        "and PMA PRBS facilities; JTAG/scan/BIST are vendor-added. The "
        "RS-FEC counters are the primary in-system DFT instrument because "
        "the 1e-13 target rides on a much worse raw PAM4 lane error ratio.")
    d["fields"] = f
    _write(p, d)


def _apply_l21(gd: Path) -> None:
    p = gd / "L21_POWER_INTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["power_intent_present"] = True
    f["link_power_management_states"] = [
        {"state": "Active", "description": "All lanes up; PCS locked + FEC-aligned; MAC streaming at 800 Gb/s.", "exit_latency_estimate": "n/a"},
        {"state": "EEE_LPI", "description": "Energy Efficient Ethernet Low-Power Idle (Clause-78-class) if supported at 800G; PHY analog deep-sleep when the MAC has no traffic.", "exit_latency_estimate": "implementation-defined wake timer"},
        {"state": "PMD_TX_disable", "description": "Per-lane transmitter disable via the Clause-45 PMA/PMD MMD for module power-down / eye-safety.", "exit_latency_estimate": "implementation-defined"},
        {"state": "Reset", "description": "SerDes re-train + PCS re-lock + FEC re-align before link-up.", "exit_latency_estimate": "training + lock time"},
    ]
    f["low_power_modes_summary"] = {
        "Active": "Full operational power.",
        "EEE_LPI": "Per-direction LPI; PHY analog low-power on idle.",
        "PMD_TX_disable": "Per-lane TX off; rest of PHY may remain configured.",
    }
    f["pause_flow_control_summary"] = {
        "PAUSE_quantum_BT": 512,
        "max_pause_quanta": 65535,
        "PAUSE_direction": "802.3x symmetric PAUSE + 802.1Qbb priority-based flow control (PFC); full-duplex only.",
    }
    f["notes"] = (
        "800GbE power management centers on the SerDes + optics (the "
        "dominant power consumers) and on optional EEE LPI. Pluggable "
        "modules expose power-class + low-power-mode control via CMIS. "
        "Wake-on-LAN-class features are NIC/host concerns, not part of "
        "802.3df.")
    d["fields"] = f
    _write(p, d)


def _apply_l22(gd: Path) -> None:
    p = gd / "L22_VERIFICATION_PLAN.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["verification_plan_present"] = "implicit"
    f["verification_categories_derived_from_spec"] = [
        "MAC frame structure preserved: preamble/SFD/DA/SA/Type/Payload/Pad/FCS for sizes 64, 256, 1518, 1522 (VLAN).",
        "FCS: bit-true CRC-32 (0x04C11DB7) on ASCII '123456789' -> 0xCBF43926.",
        "Min/max frame-size preservation (64 B / 1518 B / 1522 B VLAN).",
        "PCS 64b/66b block lock.",
        "PCS 256b/257b transcode round-trip.",
        "PCS alignment-marker lock + lane deskew/reorder under injected inter-lane skew.",
        "RS-FEC(544,514): correct up to 15 symbol errors/codeword; mark uncorrectable (>15).",
        "RS-FEC corrected/uncorrected codeword + per-lane symbol-error counter accuracy.",
        "PAM4 transmitter eye / TDECQ at 106.25 GBd per lane.",
        "Per-PMD compliance: 800GBASE-DR8, SR8, VR8, 2xFR4.",
        "Post-FEC BER <= 1e-13 over the compliance channel.",
        "Link-training FFE/DFE convergence within the training timer per lane.",
        "Auto-Negotiation (Clause-73-class) base/next page + resolved technology.",
        "Clause-45 MDIO address-then-data to PMA/PMD (1), PCS (3), AN (7).",
        "Full-duplex independent TX + RX; no CSMA/CD.",
        "PAUSE / PFC flow control.",
        "8x100G and 4x200G lane structures + breakout mapping.",
    ]
    f["notes"] = (
        "IEEE 802.3df has no formal testbench; categories derive from the "
        "MAC (Clause 4, preserved), the 800G RS/PCS (64b/66b + 256b/257b + "
        "RS-FEC(544,514) + multi-lane), the PMA/PMD (PAM4, DR8/SR8/VR8/"
        "2xFR4), and Clause-45 management. Ethernet Alliance / UNH-IOL run "
        "800G interop + conformance.")
    d["fields"] = f
    _write(p, d)


def _apply_l23(gd: Path) -> None:
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["security_requirements_present"] = False
    f["anti_corruption_features"] = [
        "RS-FEC(544,514) corrects up to 15 symbol errors per codeword, drastically reducing the residual error rate (target post-FEC BER 1e-13) — an error-correction, not a cryptographic, mechanism.",
        "IEEE 802.3 CRC-32 FCS detects residual frame errors that survive FEC (1-, 2-, 3-bit and burst errors up to 32 bits).",
        "PAM4 + 64b/66b + scrambling provide DC balance, transition density and invalid-symbol detection.",
        "PCS alignment markers guarantee correct lane reassembly under skew/reorder.",
    ]
    f["anti_tampering_features"] = []
    f["confidentiality_features"] = []
    f["authentication_features"] = []
    f["future_security_pointers"] = [
        "IEEE 802.1AE MACsec — line-rate AES-GCM encryption + ICV + replay protection above the MAC; applies unchanged at 800 Gb/s (transparent to the 800G PHY).",
        "IEEE 802.1X port-based access control + MKA key agreement.",
        "IEEE 802.1AR Secure Device Identity (DevID).",
    ]
    f["notes"] = (
        "IEEE 802.3df (like all 802.3 base specs) is a PHY + frame "
        "specification with NO confidentiality / authentication / "
        "anti-replay at the MAC/PHY boundary. The only integrity check is "
        "the FCS (error detection, not cryptographic); RS-FEC is error "
        "correction. Link-layer security (MACsec/802.1X/MKA) is layered "
        "above 802.3 and applies unchanged at 800 Gb/s.")
    d["fields"] = f
    _write(p, d)


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------
def apply_ethernet_800g_synth(generated_docs_dir: Path,
                              is_ethernet_800g: bool,
                              ethernet_800g_ic_name: Optional[str]) -> None:
    """Apply 800 Gigabit Ethernet (IEEE 802.3df / 800GBASE) synth.

    EXTENDS the base `ethernet_protocol_synth` sibling: that synth fires
    first on an 800G doc (still IEEE 802.3 + MAC + frame) and lays down the
    generic 802.3 baseline; this synth then runs and FORCE-OVERWRITES every
    L1/L2/L3/L4 key the sibling populates, specialising to the 800G PHY
    family. All assignments here are direct-assign (NOT setdefault) so the
    sibling baseline is always superseded.
    """
    if not is_ethernet_800g:
        return
    gd = Path(generated_docs_dir)

    if ethernet_800g_ic_name is not None:
        _force_ic_name(gd, ethernet_800g_ic_name)

    # L1/L2/L3/L4 — force-overwrite the sibling's 802.3 baseline.
    _apply_l1(gd)
    _apply_l2(gd)
    _apply_l3(gd)
    _apply_l4(gd)
    # L5..L13 + L14..L23 — 800G-specific layered overlays.
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


# ---------------------------------------------------------------------------
# Module-level importable detector (lifted from the inline detector in
# phase1_doc_one_shot_runner.py — ORGANIC-20260531). Re-exports the canonical single-source predicate (same
# boolean the runner used inline (`_spi_blob` -> `blob`), so behaviour is
# identical; exposing it module-level lets the universal no-misfire guard
# (tests/test_protocol_detector_no_misfire.py) auto-cover this protocol.
# Reads ONLY the spec text `blob` — never a filename or benchmark name.
# ---------------------------------------------------------------------------
# Single source of truth: tier_d_interconnect_detect (the runner imports the
# same callable). We empty-guard then delegate, so behaviour is identical and
# the no-misfire guard auto-discovers is_ethernet_800g here.
from tier_d_interconnect_detect import is_ethernet_800g as _det_ethernet_800g  # noqa: E402


def _wb_e8(tok: str, blob: str) -> bool:
    """Word-boundary token match (avoids substring false-positives)."""
    import re
    return re.search(r"\b" + re.escape(tok) + r"\b", blob) is not None


def is_ethernet_800g(blob: str) -> bool:
    """Content-only `ethernet_800g` detector with a FOREIGN-PRIMARY DEFER.

    The structural 800G signature ("800GBASE" / "802.3df" / 800G+PAM4 /
    "800 Gigabit Ethernet") is necessary but NOT sufficient: two foreign
    protocols carry incidental 800G/PAM4 comparison tokens and would
    otherwise trip the loose `800G`+`PAM4` branch and have the generic 800G
    synth FORCE-OVERWRITE their L-docs with 800GBASE PHY content:

      - Automotive Ethernet (a single-twisted-pair T1 PHY spec that contrasts
        itself against 800G/PAM4, so its L-doc blob carries those tokens).
      - PCIe Gen5 (a Gen5 SerDes spec whose PAM4 / 800G comparison vocabulary
        trips the same branch).

    Guard (mirrors `is_mipi`'s foreign-primary defer doctrine — general,
    content-only, ZERO chip/SKU/benchmark-name literal as detection logic):
    if the blob's DOMINANT subject is one of those foreign protocols, defer
    (False). Each defer condition is the foreign's OWN distinctive structural
    signature, reproduced from its synth detector:

      - automotive_ethernet: single-twisted-pair STRUCTURE + PAM3 ternary line
        code + a named T1 variant (100BASE-T1 / 10BASE-T1S / 802.3bp …) + an
        automotive bidirectional/multidrop MECHANISM (echo cancellation / PLCA
        / BroadR-Reach). 800G is full-duplex multi-pair PAM4, so its own doc
        carries NONE of PAM3 or the automotive mechanism — the full conjunct
        is absent from the 800G benchmark and own-fire is preserved.
      - pcie_gen5: the Gen5 PHY electrical signature (retimer / lane margining
        / equalization) AND a PCIe-5 SUBJECT token (32 GT/s + PCI Express, or
        "PCIe 5.0", or "PCI Express Base 5"). The 800G own doc may cite generic
        "equalization"/"retimer" but carries NO PCIe-5 subject token, so the
        conjunct stays False on the 800G benchmark.

    Empirically corpus-verified: ethernet_800g trips NEITHER defer (stays
    True); automotive_ethernet trips auto_primary; pcie_gen5 trips pcie5_primary
    (both suppressed). See test_protocol_detector_no_misfire.py.
    """
    if not blob:
        return False
    low = blob.lower()

    # --- FOREIGN-PRIMARY DEFER (the blob's true subject is NOT 800G). ---
    # Automotive-Ethernet single-twisted-pair T1 PHY structural signature.
    _auto_single_pair = (
        _wb_e8("single twisted pair", blob)
        or _wb_e8("single unshielded twisted pair", blob)
        or _wb_e8("one twisted pair", blob)
        or _wb_e8("single-pair", blob)
        or _wb_e8("single twisted-pair", blob)
        or _wb_e8("one single twisted pair", blob)
        or _wb_e8("one balanced pair", blob))
    _auto_pam3 = _wb_e8("PAM3", blob)
    _auto_variant = (
        _wb_e8("100BASE-T1", blob) or _wb_e8("1000BASE-T1", blob)
        or _wb_e8("10BASE-T1S", blob) or _wb_e8("10BASE-T1L", blob)
        or _wb_e8("10BASE-T1", blob)
        or _wb_e8("802.3bw", blob) or _wb_e8("802.3bp", blob)
        or _wb_e8("802.3cg", blob))
    _auto_mechanism = (
        _wb_e8("echo cancellation", blob) or _wb_e8("echo canceller", blob)
        or _wb_e8("echo canceler", blob)
        or _wb_e8("PLCA", blob)
        or _wb_e8("Physical Layer Collision Avoidance", blob)
        or _wb_e8("BroadR-Reach", blob))
    auto_primary = (
        _auto_single_pair and _auto_pam3 and _auto_variant and _auto_mechanism)

    # PCIe-Gen5 SerDes structural signature (PHY electrical + PCIe-5 subject).
    _pcie5_phy = (
        "retimer" in low
        or "lane margining" in low
        or "equalization" in low)
    _pcie5_subject = (
        ("32 GT/s" in blob and "PCI Express" in blob)
        or ("PCIe 5.0" in blob)
        or ("PCI Express Base 5" in blob))
    pcie5_primary = _pcie5_phy and _pcie5_subject

    if auto_primary or pcie5_primary:
        return False

    # --- STRUCTURAL 800G signature (unchanged shared predicate). ---
    return bool(_det_ethernet_800g(blob))
