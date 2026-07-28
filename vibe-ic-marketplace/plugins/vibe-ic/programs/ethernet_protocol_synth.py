"""IEEE 802.3 Ethernet-class protocol synth helper.

v0.1.84 — ic_class-gated overlay for `bus_interconnect_protocol`-shaped
specs that exhibit the IEEE 802.3 Ethernet structural signature
(MII + MDIO + PHY, OR 802.3 + MAC + frame, OR Ethernet + (preamble or SFD)).
Applies IEEE Std 802.3-2005 spec-canonical content (Clause 4 MAC frame,
Clause 22 MII + MDIO, Clause 35 GMII, Clause 45 MDIO MMD, Clause 28
Auto-Negotiation, Clause 31 PAUSE) to L1-L18 + L21.

Doctrine: structural-keyword detection IS general within an ic_class
(mirrors AMBA-AXI / SPI / I2C / UART / CAN / USB / I2S / PCIe synth).
Any IEEE 802.3 family variant (10/100 Mb/s + 1 Gb/s + 10 Gb/s base specs;
MAC + PHY IPs; Clause-22 or Clause-45 MDIO; switch ASICs; NICs) exhibits
the same structural MAC + MII + MDIO signature.

Public entry: `apply_ethernet_synth(generated_docs_dir, is_ethernet,
                                    ethernet_ic_name)`.
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
    # L14-L23 carry ic_name inside fields
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
            f = d.get("fields") or {}
            f["ic_name"] = ic_name
            d["fields"] = f
            _write(q, d)


def _apply_l1(gd: Path) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("document_title",
        "IEEE Std 802.3-2005 — Information technology — Telecommunications and information exchange between systems — Local and metropolitan area networks — Specific requirements — Part 3: Carrier Sense Multiple Access with Collision Detection (CSMA/CD) access method and physical layer specifications")
    d.setdefault("version",
        "IEEE Std 802.3-2005 (Section Two: Clauses 21 through 33 + Annex 22A through 32A; with cross-references to Clause 4 MAC, Clause 22 MII, Clause 35 GMII, Clause 45 MDIO/MMD)")
    d.setdefault("revised_date", "2005")
    d.setdefault("manufacturer",
        "IEEE — LAN/MAN Standards Committee of the IEEE Computer Society (IEEE 802.3 Working Group)")
    d.setdefault("copyright", "© 2005 IEEE")
    d.setdefault("abstract",
        "IEEE 802.3 specifies a CSMA/CD-based Local Area Network with a common Media Access Control (MAC) layer (Clause 4) and a family of Physical Layer (PHY) sublayers (PCS / PMA / PMD / Auto-Negotiation) connected through one of several media-independent interfaces — MII (Clause 22, 10/100 Mb/s, nibble-wide), GMII (Clause 35, 1000 Mb/s, byte-wide), and RGMII (industry de-facto reduced-pin variant of GMII). A serial Station Management bus (MDC / MDIO) provides access to per-PHY register space — Clause 22 (basic, 5-bit PHY address + 5-bit register, 32 registers) and Clause 45 (MMD-extended, 5-bit PHY + 5-bit MMD + 16-bit register). All Ethernet frames carry the canonical preamble (7×0x55) + SFD (0xD5) + Destination MAC (6B) + Source MAC (6B) + EtherType/Length (2B) + Payload (46-1500 B with VLAN-aware extension to 1504 B) + FCS (32-bit CRC, polynomial 0x04C11DB7).")
    d.setdefault("keywords", [
        "IEEE 802.3", "Ethernet", "CSMA/CD", "MAC", "PHY",
        "MII", "GMII", "RGMII", "MDIO", "MMD",
        "Clause 22", "Clause 35", "Clause 45",
        "Reconciliation Sublayer", "Station Management (STA)",
        "Auto-Negotiation", "Preamble", "SFD", "EtherType",
        "FCS", "CRC-32",
        "Full Duplex", "Half Duplex", "PAUSE frame", "VLAN 802.1Q",
    ])
    d.setdefault("external_pins", [
        "MII signals (Clause 22): TX_CLK (PHY→MAC, 25 MHz for 100 Mb/s or 2.5 MHz for 10 Mb/s), TXD[3:0] (MAC→PHY), TX_EN (MAC→PHY), TX_ER (MAC→PHY), RX_CLK (PHY→MAC), RXD[3:0] (PHY→MAC), RX_DV (PHY→MAC), RX_ER (PHY→MAC), CRS (PHY→MAC), COL (PHY→MAC)",
        "MII management (Clause 22.2.4): MDC (STA→PHY, ≤ 2.5 MHz, period ≥ 400 ns), MDIO (bidirectional, three-state, 1.5 kΩ pull-up at PHY, 2 kΩ pull-down at STA)",
        "GMII signals (Clause 35): GTX_CLK (MAC→PHY, 125 MHz), TXD[7:0], TX_EN, TX_ER, RX_CLK (PHY→MAC, 125 MHz), RXD[7:0], RX_DV, RX_ER, CRS, COL — plus MDC / MDIO",
        "RGMII signals (industry de-facto reduced-pin): TX_CLK (DDR, 125 MHz at 1 Gb/s), TXD[3:0], TX_CTL, RX_CLK (DDR), RXD[3:0], RX_CTL — 12 wires total per direction, plus MDC / MDIO",
        "MDI (Medium Dependent Interface) — to the cable / fiber medium per PMD class (10/100/1000BASE-T copper, BASE-X fiber, BASE-FX fiber, etc.)",
    ])
    d.setdefault("external_pin_count_mii", 16)
    d.setdefault("external_pin_count_gmii", 24)
    d.setdefault("external_pin_count_rgmii", 12)
    d.setdefault("supported_speeds_Mbps", [10, 100, 1000, 10000])
    d.setdefault("modes_of_operation", [
        {"name": "10BASE-T  (10 Mb/s,  half + full duplex, twisted pair, Clause 14)", "interface_to_MAC": "MII (optional)", "line_rate_Mbps": 10},
        {"name": "100BASE-TX (100 Mb/s, Cat 5 UTP, Clauses 24-25)",                   "interface_to_MAC": "MII",            "line_rate_Mbps": 100},
        {"name": "100BASE-FX (100 Mb/s, multimode fiber, Clauses 24-26)",             "interface_to_MAC": "MII",            "line_rate_Mbps": 100},
        {"name": "100BASE-T4 (100 Mb/s, Cat 3/4/5 UTP, Clause 23)",                   "interface_to_MAC": "MII",            "line_rate_Mbps": 100},
        {"name": "100BASE-T2 (100 Mb/s, Cat 3/4/5 UTP, Clause 32)",                   "interface_to_MAC": "MII",            "line_rate_Mbps": 100},
        {"name": "1000BASE-T (1 Gb/s, Cat 5e UTP, Clause 40)",                        "interface_to_MAC": "GMII / RGMII",   "line_rate_Mbps": 1000},
        {"name": "1000BASE-X (1 Gb/s, fiber / shielded copper, Clause 36)",           "interface_to_MAC": "GMII / TBI",     "line_rate_Mbps": 1000},
    ])
    d.setdefault("key_features", [
        "MAC frame structure is identical across all speeds: Preamble (7×0x55) + SFD (0xD5) + DA (6B) + SA (6B) + EtherType/Length (2B) + Payload (46-1500B) + Pad-to-minimum (0-46B) + FCS (4B CRC-32).",
        "Common MAC service interface (PLS_DATA.request / PLS_DATA.indication) is preserved across 10/100/1000 Mb/s — only the Reconciliation Sublayer (RS) maps it onto the speed-specific MII / GMII signals.",
        "Media-Independent Interface (MII, Clause 22) provides a 4-bit (nibble-wide) data path at 25 MHz (100 Mb/s) or 2.5 MHz (10 Mb/s) with separate TX_CLK and RX_CLK both sourced by the PHY.",
        "Gigabit Media-Independent Interface (GMII, Clause 35) provides an 8-bit data path at 125 MHz with GTX_CLK sourced by the MAC and RX_CLK sourced by the PHY.",
        "Reduced Gigabit Media-Independent Interface (RGMII) halves the pin count by using DDR on a 4-bit data path at 125 MHz (effective 1 Gb/s) with TX_CTL / RX_CTL replacing the four control signals.",
        "Serial management bus (MDC + MDIO) provides up to 32 PHY × 32 registers (Clause 22) or 32 PHY × 32 MMDs × 65536 registers (Clause 45) at MDC ≤ 2.5 MHz.",
        "CSMA/CD (half duplex legacy): Carrier Sense (CRS) + Multiple Access + Collision Detect (COL) with truncated-binary-exponential backoff after collision; never used in full-duplex modes.",
        "Full-duplex operation: independent simultaneous transmit and receive on dedicated wire pairs; CRS / COL behavior undefined and ignored. IEEE 802.3x PAUSE frame is the link-level flow-control mechanism in full duplex.",
        "Auto-Negotiation (Clause 28) — out-of-band Fast-Link-Pulse-encoded 16-bit Base Page exchange advertising speed (10 / 100 / 1000), duplex (half / full), and PAUSE capability; performed before normal data exchange begins.",
        "EtherType (DA + SA + 16-bit Type/Length): if value ≥ 0x0600 (1536) it is interpreted as an EtherType (e.g. 0x0800 IPv4, 0x0806 ARP, 0x8100 802.1Q VLAN, 0x86DD IPv6, 0x88CC LLDP, 0x8808 PAUSE/MAC-Control); if value < 0x0600 it is a Length (IEEE 802.3 LLC encapsulation).",
        "IEEE 802.1Q VLAN tag (4 B inserted between SA and EtherType): TPID (0x8100) + TCI [PCP[3] + DEI[1] + VID[12]]. Maximum frame size grows from 1518 to 1522 B (with FCS).",
        "Frame Check Sequence: IEEE 802.3 CRC-32 with polynomial 0x04C11DB7 (reflected representation 0xEDB88320, init 0xFFFFFFFF, final XOR 0xFFFFFFFF, processed LSB-first within each byte).",
        "Inter-Frame Gap (IFG) = 96 bit times (9.6 µs at 10 Mb/s, 0.96 µs at 100 Mb/s, 96 ns at 1000 Mb/s) — minimum required between back-to-back frame transmissions.",
        "Minimum frame size (including FCS, excluding preamble/SFD) = 64 bytes; maximum (untagged) = 1518 bytes; maximum (VLAN-tagged) = 1522 bytes.",
    ])
    d.setdefault("topology_summary",
        "Switched point-to-point full-duplex star (modern dominant case) or shared half-duplex CSMA/CD bus / repeater hub (legacy). Each MAC connects via a single MII / GMII / RGMII to one PHY, and the PHY's MDI connects to the medium (copper / fiber). In switched topologies every link is its own full-duplex collision domain (i.e. no collisions).")
    d.setdefault("package_summary",
        "IEEE Std 802.3-2005 is a wire-level + frame-level + management-interface specification. Connector / cabling / fiber mechanicals are specified per-PMD in dedicated clauses (Clause 14 for 10BASE-T, Clauses 24-26 for 100BASE-X / 100BASE-FX, Clause 40 for 1000BASE-T, Clause 38 for 1000BASE-X). Section Two of the 2005 base spec (Clauses 21-33) covers the 100 Mb/s family.")
    d.setdefault("use_cases", [
        "Workgroup + enterprise LAN — switched 100 Mb/s, 1 Gb/s, 10 Gb/s desktop and server connectivity",
        "Data center top-of-rack and backbone fabric (1 / 10 / 25 / 40 / 100 GbE)",
        "Industrial automation (Industrial Ethernet, EtherCAT, PROFINET, EtherNet/IP)",
        "Carrier Metro Ethernet / Carrier Ethernet (E-LINE / E-LAN / E-TREE)",
        "Automotive Ethernet (100BASE-T1 / 1000BASE-T1 single-pair variants — out of base spec scope but inherit the same MAC frame)",
        "MAC + PHY integration into SoCs as a packet-IO peripheral, behind MII / GMII / RGMII / XGMII",
    ])
    d.setdefault("revision_history", [
        {"version": "IEEE Std 802.3-2005", "date": "2005",
         "description": "Consolidated revision of IEEE Std 802.3. Section Two covers the 100 Mb/s baseband family (Clauses 21-33). Earlier 10 Mb/s + Ethernet II + LLC content is in Section One; later gigabit / 10G / EPON / OAM clauses are in Section Three+. Cross-referenced with Clause 4 (MAC), Clause 22 (MII), Clause 35 (GMII), Clause 45 (MDIO MMD)."},
    ])
    d.setdefault("overview",
        "IEEE 802.3 — colloquially 'Ethernet' — is the dominant wired LAN protocol family. Its two enduring contributions are (a) a uniform MAC frame format with a 6-byte source + destination address, a 2-byte EtherType / Length, and a 4-byte CRC-32 Frame Check Sequence; and (b) a clean MAC ↔ PHY split via the Media-Independent Interface (MII, Clause 22), which lets a single MAC implementation drive a family of PHY sublayers (10 Mb/s, 100 Mb/s, 1 Gb/s, 10 Gb/s, and beyond) without functional change. The MII was extended to GMII (Clause 35) for 1 Gb/s — wider data path, MAC-sourced TX clock — and to industry RGMII / SGMII / XGMII variants for higher speeds and lower pin count. PHY-internal control / status / capability lives in a register file accessed serially over the MDIO management bus, governed by either Clause 22 (basic 5+5 addressing, 32 registers) or Clause 45 (MMD-extended 5+5+16 addressing). Auto-Negotiation (Clause 28) lets two link partners discover their highest common speed and duplex mode before frames are exchanged. The MAC supports full-duplex switched operation (no collisions) with PAUSE-frame flow control, and a legacy half-duplex CSMA/CD mode with truncated-binary-exponential collision backoff.")
    _write(p, d)


def _apply_l2(gd: Path) -> None:
    p = gd / "L2_FRS.json"
    if not p.is_file():
        return
    d = _read(p)
    if d.get("protocol_overview") in (None, "", []):
        d["protocol_overview"] = {}
    po = d["protocol_overview"]
    if isinstance(po, dict):
        po.setdefault("type",
            "Layered LAN protocol: common Media Access Control (Clause 4 MAC) over a family of Physical Layer (PHY) sublayers (PCS + PMA + PMD + Auto-Negotiation), connected through a Media-Independent Interface (MII Clause 22 for 10/100 Mb/s; GMII Clause 35 for 1 Gb/s; RGMII industry de-facto reduced variant; XGMII for 10 Gb/s). Per-PHY register access is provided by a separate serial management bus (MDC + MDIO) per Clause 22 (basic) or Clause 45 (MMD-extended).")
        po.setdefault("duplex",
            "full duplex (modern switched dominant case) or half duplex (legacy CSMA/CD shared medium)")
        po.setdefault("synchronous_serial", False)
        po.setdefault("embedded_clock", False)
        po.setdefault("encoding",
            "PHY-class specific: 100BASE-TX uses 4B/5B then MLT-3; 100BASE-FX uses 4B/5B then NRZI; 1000BASE-T uses PAM5 with 8B1Q4 + Trellis coding; 1000BASE-X uses 8B/10B (same code as Fibre Channel / PCIe 1.x); 10BASE-T uses Manchester. MII/GMII/RGMII themselves carry plain LVTTL/LVCMOS nibble or byte data — encoding happens entirely inside the PHY.")
        po.setdefault("MII_data_rate_Mb_s_per_speed",
            {"10 Mb/s": "2.5 MHz × 4 bits", "100 Mb/s": "25 MHz × 4 bits"})
        po.setdefault("GMII_data_rate_Mb_s", "125 MHz × 8 bits = 1000 Mb/s")
        po.setdefault("RGMII_data_rate_Mb_s",
            "DDR 125 MHz × 4 bits = 1000 Mb/s")
        po.setdefault("MDIO_max_clock_MHz", 2.5)
        po.setdefault("MDIO_min_period_ns", 400)
        po.setdefault("MDIO_min_high_low_ns", 160)
        po.setdefault("interfaces_in_scope", [
            "Clause 4 — MAC frame format + CSMA/CD + full-duplex operation",
            "Clause 22 — Reconciliation Sublayer (RS) + MII (10/100 Mb/s) + MDC/MDIO + Clause-22 management registers",
            "Clause 35 — Reconciliation Sublayer + GMII (1 Gb/s)",
            "Clause 45 — MMD-extended MDIO management (5-bit MMD + 16-bit register address per PHY)",
            "Clause 28 — Auto-Negotiation (out-of-band Fast Link Pulse / Base Page exchange)",
            "Clause 31 — MAC Control sublayer (PAUSE frame mechanism for full-duplex flow control)",
        ])
        po.setdefault("frame_classes", {
            "Data_frame":        "Preamble + SFD + DA + SA + EtherType/Length + Payload + Pad + FCS",
            "VLAN_tagged_frame": "Preamble + SFD + DA + SA + VLAN tag (TPID 0x8100 + TCI) + EtherType/Length + Payload + Pad + FCS (max 1522 B)",
            "PAUSE_frame":       "DA = 01:80:C2:00:00:01 (Slow Protocols Multicast) + SA + EtherType 0x8808 + Opcode 0x0001 + Pause Quanta (16b) + zero pad to 64 B + FCS",
            "MDIO_C22_frame":    "PRE(32) + ST(01) + OP(read=10/write=01) + PHYAD(5) + REGAD(5) + TA(2) + DATA(16)",
            "MDIO_C45_frame":    "PRE(32) + ST(00) + OP(addr=00/write=01/read=11/postRead=10) + PRTAD(5) + DEVAD(5) + TA(2) + DATA(16) — two-cycle protocol: address then read/write",
            "Auto-Negotiation":  "16-bit Base Page (Clause 28.2.1) advertised via Fast Link Pulse (FLP) bursts; encodes Selector / Tech Ability / Acknowledge / Remote Fault / Next Page",
        })
    fr = [
        {"id": "FR-MAC-01",   "text": "The MAC sublayer (Clause 4) shall transmit and receive Ethernet frames with the canonical Preamble (7 octets of 0x55) + SFD (single octet 0xD5) + DA (6 B) + SA (6 B) + EtherType/Length (2 B) + Payload + Pad + FCS (4 B CRC-32) structure, irrespective of the underlying PHY."},
        {"id": "FR-FCS-02",   "text": "Every transmitted frame shall append a 32-bit Frame Check Sequence computed with the IEEE 802.3 CRC-32 polynomial 0x04C11DB7 (reflected 0xEDB88320, initial value 0xFFFFFFFF, final XOR 0xFFFFFFFF). Each byte is processed LSB-first. Received frames whose recomputed CRC does not equal the received FCS shall be discarded and reported as an FCS error."},
        {"id": "FR-MINMAX-03","text": "Untagged frames shall be at least 64 octets (DA + SA + Type/Length + Payload + FCS, excluding Preamble + SFD) and at most 1518 octets. VLAN-tagged frames shall be at most 1522 octets. Frames shorter than the minimum shall be zero-padded by the MAC before FCS computation."},
        {"id": "FR-IFG-04",   "text": "The MAC shall enforce a minimum Inter-Frame Gap of 96 bit times between back-to-back frames (9.6 µs @10 Mb/s, 0.96 µs @100 Mb/s, 96 ns @1000 Mb/s)."},
        {"id": "FR-MII-05",   "text": "The MII (Clause 22) shall provide nibble-wide TXD[3:0] + TX_EN + TX_ER signals (MAC→PHY) and RXD[3:0] + RX_DV + RX_ER signals (PHY→MAC), each synchronous to a clock provided by the PHY (TX_CLK / RX_CLK). TX_CLK shall be 25 MHz at 100 Mb/s, 2.5 MHz at 10 Mb/s, with duty cycle 35-65 % and ±100 ppm tolerance."},
        {"id": "FR-CRSCOL-06","text": "The PHY shall assert CRS whenever either the transmit or receive medium is non-idle and shall maintain CRS throughout a collision condition. The PHY shall assert COL upon collision detection (half-duplex only). In full-duplex modes the behaviour of CRS and COL is implementation-defined and shall be ignored by the MAC."},
        {"id": "FR-GMII-07",  "text": "The GMII (Clause 35) shall provide byte-wide TXD[7:0] + TX_EN + TX_ER (MAC→PHY) and RXD[7:0] + RX_DV + RX_ER (PHY→MAC), with GTX_CLK driven by the MAC and RX_CLK driven by the PHY, both at 125 MHz."},
        {"id": "FR-RGMII-08", "text": "RGMII shall halve the pin count vs GMII by clocking TXD[3:0] and RXD[3:0] on both edges of a 125 MHz clock, replacing TX_EN + TX_ER with a single TX_CTL signal (TX_EN on rising edge, TX_ERR on falling edge) and similarly RX_DV + RX_ER → RX_CTL."},
        {"id": "FR-MDIO-09",  "text": "The serial Management Interface shall consist of MDC (sourced by the STA, ≤ 2.5 MHz, minimum period 400 ns, minimum high and low time 160 ns each) and MDIO (bidirectional, three-state, 1.5 kΩ pull-up at the PHY). A Clause-22 management frame is PRE(32 ones) + ST(01) + OP(write=01 / read=10) + PHYAD(5) + REGAD(5) + TA(2) + DATA(16). Clause-45 frames use ST(00) and a two-cycle (address-then-data) protocol with 5-bit MMD + 16-bit register."},
        {"id": "FR-AUTONEG-10","text": "Auto-Negotiation (Clause 28), when supported, shall exchange a 16-bit Base Page advertising Selector + Tech Ability (10BASE-T HD/FD, 100BASE-TX HD/FD, 100BASE-T4, PAUSE, Asym-PAUSE) + Remote Fault + Acknowledge + Next Page. The highest common ability is selected; if either end disables AutoNeg, the parallel-detect fallback determines speed only."},
        {"id": "FR-DUPLEX-11","text": "Full-duplex operation shall send and receive frames independently and simultaneously on dedicated wire pairs; CSMA/CD shall be disabled. Half-duplex operation shall run the CSMA/CD algorithm with truncated-binary-exponential backoff on collision (retry up to 16 attempts then abort)."},
        {"id": "FR-PAUSE-12", "text": "The MAC Control sublayer (Clause 31) shall recognise PAUSE frames (DA 01:80:C2:00:00:01, EtherType 0x8808, opcode 0x0001) and stop transmitting data frames for the indicated Pause Quanta (1 quantum = 512 bit times). PAUSE frames are valid only in full-duplex mode."},
        {"id": "FR-VLAN-13",  "text": "If 802.1Q VLAN tagging is supported, a 4-byte tag (TPID 0x8100 + TCI[PCP[3]+DEI[1]+VID[12]]) shall be inserted between SA and EtherType/Length. The MAC shall accept up to 1522-byte VLAN-tagged frames."},
        {"id": "FR-ETHERTYPE-14","text": "The 2-byte Type/Length field shall be interpreted as an EtherType when its value is ≥ 0x0600 (1536) and as an LLC payload Length when its value is ≤ 1500 (0x05DC). Common EtherType assignments include 0x0800 IPv4, 0x0806 ARP, 0x86DD IPv6, 0x8100 VLAN, 0x8808 MAC Control/PAUSE, 0x88CC LLDP."},
        {"id": "FR-CLAUSE45-15","text": "Clause 45 MDIO Management shall extend the C22 addressing by inserting an MMD Device Address (5 bits) between PHYAD and REGAD, and shall replace the single-cycle read/write with a two-cycle protocol: first an Address cycle (OP=00) writes the 16-bit register address into the MMD-selected indirect-address register, then a Data cycle (OP=01 write, OP=11 read, OP=10 post-increment read) accesses the data. This enables 32 × 32 × 65 536 register space per MDIO bus."},
        {"id": "FR-RECONC-16","text": "The Reconciliation Sublayer (RS) shall map the MAC's PLS_DATA.request / PLS_DATA.indication / PLS_CARRIER.indication / PLS_SIGNAL.indication service primitives onto the MII or GMII signals so the same MAC implementation drives 10 / 100 / 1000 Mb/s without functional change."},
    ]
    if _empty(d.get("functional_requirements")):
        d["functional_requirements"] = fr
    d.setdefault("error_response_conditions", [
        "FCS (CRC-32) mismatch — receive MAC shall discard the frame and increment a frame-check-sequence-error counter.",
        "Frame too short (< 64 B excluding preamble/SFD) — receive MAC shall discard as a runt frame.",
        "Frame too long (> 1518 B untagged or > 1522 B VLAN-tagged) — receive MAC may discard as a giant / jumbo frame (unless jumbo support is enabled by the implementation).",
        "TX_ER asserted during transmission — PHY shall emit one or more invalid symbols somewhere in the outgoing frame so the far end will mark it as RX_ER.",
        "RX_ER asserted during reception — receive MAC shall mark the in-progress frame as corrupted and discard it (and optionally raise a coding-error counter).",
        "False Carrier indication on the MII (RX_DV = 0, RX_ER = 1, RXD = 0x1110) — receive MAC sees carrier activity but no valid frame; counted as a False Carrier Event.",
        "Collision (half-duplex only) — MAC aborts current transmission, sends a 32/48-bit JAM pattern, applies truncated-binary-exponential backoff, retries up to 16 attempts then declares Excessive Collisions.",
        "Late Collision (collision after 512 bit times into the frame, half-duplex only) — frame is aborted and the Late Collisions counter is incremented; no retry is performed.",
        "Carrier Sense lost during transmission (half-duplex only) — MAC reports Carrier Sense Lost.",
        "PAUSE timer running (full-duplex only) — MAC must hold off data-frame transmission until the timer expires.",
        "MDIO bus contention — Clause-22 read transactions reserve a 2-bit turnaround (TA = Z0) to allow the bus to switch from STA-driven to PHY-driven; a PHY that drives during the first TA bit is non-conforming.",
    ])
    if _empty(d.get("compliance_requirements")):
        d["compliance_requirements"] = [
            "Mandatory preamble of 7 octets of 0x55 followed by a single SFD octet of 0xD5, transmitted LSB-first within each octet at the MAC↔PHY boundary.",
            "Mandatory FCS = IEEE 802.3 CRC-32 with polynomial 0x04C11DB7 covering DA + SA + Type/Length + Payload + Pad.",
            "Mandatory 96-bit-time Inter-Frame Gap between back-to-back transmitted frames.",
            "Mandatory MAC Address structure: 6 octets, transmitted MSB-byte first, LSB-bit first within each byte; bit 0 of the first byte = Individual (0) / Group (1); bit 1 of the first byte = Universally (0) / Locally (1) administered.",
            "Mandatory recognition of the all-ones MAC address (FF:FF:FF:FF:FF:FF) as Broadcast.",
            "Mandatory recognition of the Slow Protocols multicast addresses 01:80:C2:00:00:0X (PAUSE = 01:80:C2:00:00:01).",
            "Mandatory MII frame structure on the management bus: PRE(32 ones) + ST(01 for C22 / 00 for C45) + OP + PHYAD(5) + REGAD/DEVAD(5) + TA(Z0 for read / 10 for write) + DATA(16).",
            "Mandatory Clause-22 register 0 (Control / BMCR) and register 1 (Status / BMSR) at PHYAD-selected addresses, both 16 bits wide.",
            "Mandatory Auto-Negotiation Base Page format (16 bits) for any PHY that advertises Auto-Negotiation capability via bit 1.3 of BMSR.",
            "TX_CLK / RX_CLK duty cycle in the 35-65 % range; tolerance ±100 ppm; MII signals shall switch monotonically within the 0.40 V to 2.40 V LVTTL window.",
        ]
    _write(p, d)


def _apply_l3(gd: Path) -> None:
    p = gd / "L3_CMD_PROTOCOL.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("protocol_type",
        "Two distinct framed protocols share the Ethernet stack: (a) Ethernet MAC frames carry user data and control between MACs (Preamble + SFD + DA + SA + Type/Length + Payload + Pad + FCS); (b) MDIO management frames (Clause 22 single-cycle or Clause 45 two-cycle) access PHY registers from the Station Management entity. Auto-Negotiation (Clause 28) is a third, out-of-band protocol exchanged via Fast Link Pulse bursts before normal MII/GMII data flow begins.")
    d.setdefault("channels", [
        {"name": "MII data path",       "direction": "MAC↔PHY",  "description": "10/100 Mb/s. TX side: TX_CLK (PHY→MAC) + TXD[3:0] + TX_EN + TX_ER (MAC→PHY). RX side: RX_CLK (PHY→MAC) + RXD[3:0] + RX_DV + RX_ER (PHY→MAC). Half-duplex extras: CRS + COL (PHY→MAC)."},
        {"name": "GMII data path",      "direction": "MAC↔PHY",  "description": "1 Gb/s. TX side: GTX_CLK (MAC→PHY, 125 MHz) + TXD[7:0] + TX_EN + TX_ER. RX side: RX_CLK (PHY→MAC, 125 MHz) + RXD[7:0] + RX_DV + RX_ER. Half-duplex extras: CRS + COL."},
        {"name": "RGMII data path",     "direction": "MAC↔PHY",  "description": "1 Gb/s reduced-pin. TX side: TX_CLK + TXD[3:0] + TX_CTL (DDR, 125 MHz). RX side: RX_CLK + RXD[3:0] + RX_CTL (DDR, 125 MHz). TX_CTL = TX_EN on rising edge, TX_ERR XOR TX_EN on falling edge; similarly for RX_CTL."},
        {"name": "MDIO management bus", "direction": "STA↔PHY",  "description": "MDC (STA→PHY, ≤ 2.5 MHz, period ≥ 400 ns, min H+L = 160 ns each) + MDIO (bidirectional three-state, 1.5 kΩ pull-up at PHY, 2 kΩ pull-down at STA)."},
        {"name": "MDI (Medium Dependent Interface)", "direction": "PHY↔medium", "description": "Wire-level interface to the copper / fiber medium per PMD class (e.g. RJ-45 8P8C connector with 2 or 4 twisted pairs for 100BASE-TX / 1000BASE-T; SC/LC duplex for 100BASE-FX / 1000BASE-X fiber)."},
    ])
    d.setdefault("packet_classes", [
        {"class": "Ethernet MAC frame", "purpose": "Carries user data + protocol-stack frames between MACs.", "subtypes": [
            "Untagged data frame (DA + SA + EtherType/Length + Payload + FCS, 64-1518 B)",
            "802.1Q VLAN-tagged frame (DA + SA + 0x8100 TPID + TCI + EtherType/Length + Payload + FCS, max 1522 B)",
            "802.3x PAUSE frame (DA = 01:80:C2:00:00:01, EtherType 0x8808, opcode 0x0001, 64 B fixed)",
            "Slow Protocols frame (DA = 01:80:C2:00:00:02 — LACP / Marker / OAM)",
            "Broadcast frame (DA = FF:FF:FF:FF:FF:FF — delivered to every station in the broadcast domain)",
        ]},
        {"class": "MDIO management frame (Clause 22)", "purpose": "Single-cycle PHY register access.", "subtypes": [
            "Read  (PRE + ST=01 + OP=10 + PHYAD(5) + REGAD(5) + TA=Z0 + DATA(16, PHY-driven))",
            "Write (PRE + ST=01 + OP=01 + PHYAD(5) + REGAD(5) + TA=10 + DATA(16, STA-driven))",
        ]},
        {"class": "MDIO management frame (Clause 45)", "purpose": "MMD-extended PHY register access via a two-cycle address-then-data protocol.", "subtypes": [
            "Address (PRE + ST=00 + OP=00 + PRTAD(5) + DEVAD(5) + TA=10 + ADDRESS(16))",
            "Write   (PRE + ST=00 + OP=01 + PRTAD(5) + DEVAD(5) + TA=10 + DATA(16))",
            "Read    (PRE + ST=00 + OP=11 + PRTAD(5) + DEVAD(5) + TA=Z0 + DATA(16))",
            "Post-Increment Read (PRE + ST=00 + OP=10 + PRTAD(5) + DEVAD(5) + TA=Z0 + DATA(16); internal address auto-increments)",
        ]},
        {"class": "Auto-Negotiation Base Page (Clause 28)", "purpose": "16-bit capability-advertisement exchanged via Fast Link Pulse bursts before normal data signaling begins.", "subtypes": [
            "Base Page (Selector[4:0] + Tech Ability[7:0] + Remote Fault + Acknowledge + Next Page)",
            "Message Page + Unformatted Pages (when Next Page bit is set)",
        ]},
    ])
    d.setdefault("mac_frame_format", {
        "preamble":            "7 octets of 0x55 (binary 01010101)",
        "sfd":                 "1 octet 0xD5 (binary 11010101) — Start Frame Delimiter; marks the end of the preamble and the start of the destination-address byte.",
        "destination_address": "6 octets (48 bits). Bit 0 of byte 0 = I/G (0=Individual, 1=Group); bit 1 of byte 0 = U/L (0=Universally administered, 1=Locally administered). Reserved values: FF:FF:FF:FF:FF:FF = Broadcast; 01:80:C2:00:00:0X = Slow Protocols multicast.",
        "source_address":      "6 octets (48 bits). Must be a unicast address (I/G bit = 0).",
        "etheryype_or_length": "2 octets. If value ≥ 0x0600 (1536) it is an EtherType; if ≤ 1500 (0x05DC) it is a payload Length (IEEE 802.3 LLC encapsulation).",
        "payload":             "46-1500 octets of MAC client data (or 42-1500 in a VLAN-tagged frame). Shorter payloads must be zero-padded by the MAC.",
        "pad":                 "0-46 octets of 0x00 to reach the 64-byte minimum frame length (excluding preamble + SFD).",
        "fcs":                 "4 octets (32 bits). IEEE 802.3 CRC-32 over DA + SA + Type/Length + Payload + Pad. Polynomial 0x04C11DB7; reflected representation 0xEDB88320; initial value 0xFFFFFFFF; final XOR 0xFFFFFFFF; LSB-first byte processing.",
        "ifg":                 "Inter-Frame Gap: minimum 96 bit times (9.6 µs @10 Mb/s, 0.96 µs @100 Mb/s, 96 ns @1 Gb/s) between back-to-back frames.",
    })
    d.setdefault("mdio_clause22_frame", {
        "PRE":   "32 contiguous logic-1 bits on MDIO with 32 corresponding MDC cycles. May be suppressed if both ends support preamble suppression (BMSR bit 1.6).",
        "ST":    "<01> — start of frame, ensures transitions from default-1 line state.",
        "OP":    "<10> = Read; <01> = Write.",
        "PHYAD": "5 bits, MSB first. 32 unique addresses; PHYAD 00000 always responded to by a single-PHY connection.",
        "REGAD": "5 bits, MSB first. 32 registers; register 0 = BMCR, register 1 = BMSR, register 2/3 = PHY ID, register 4 = ANAR, register 5 = ANLPAR, register 6 = ANER, register 9 = 1000BASE-T Control, register 10 = 1000BASE-T Status, register 15 = Extended Status.",
        "TA":    "2 bits. Read: bit-0 = high-impedance (both sides), bit-1 = 0 driven by PHY. Write: <10> driven by STA.",
        "DATA":  "16 bits. First bit on the wire = bit 15 of the register being accessed.",
    })
    d.setdefault("mdio_clause45_frame", {
        "PRE":   "32 contiguous logic-1 bits.",
        "ST":    "<00> — distinguishes Clause 45 from Clause 22.",
        "OP":    "<00> = Address (write 16-bit register address into the MMD), <01> = Write data, <11> = Read data, <10> = Post-Increment Read.",
        "PRTAD": "5-bit port (PHY) address.",
        "DEVAD": "5-bit MMD Device Address. Defined MMDs: 1 PMA/PMD, 2 WIS, 3 PCS, 4 PHY XS, 5 DTE XS, 6 TC, 7 Auto-Negotiation, 13/14 EEE, 29 Clause 22 register access, 30/31 Vendor-specific.",
        "TA":    "Same conventions as Clause 22.",
        "DATA":  "Address cycle: 16-bit register address. Data cycle: 16-bit register value (the previously written address selects the register).",
    })
    d.setdefault("transaction_classes_split", [
        {"class": "Data plane",       "transactions": ["MAC data frame transmit + receive", "VLAN-tagged frame", "Broadcast / multicast / unicast"], "interface": "MII / GMII / RGMII / XGMII"},
        {"class": "Flow control",     "transactions": ["PAUSE frame (EtherType 0x8808)"],                            "interface": "MII / GMII / RGMII (full-duplex only)"},
        {"class": "Management",       "transactions": ["MDIO C22 Read", "MDIO C22 Write", "MDIO C45 Address/Read/Write/PostInc"], "interface": "MDC + MDIO"},
        {"class": "Negotiation",      "transactions": ["Auto-Negotiation Base Page", "Next Page exchange", "Parallel Detect fallback"], "interface": "Out-of-band Fast Link Pulse on MDI before data signaling begins"},
    ])
    d.setdefault("valid_ready_handshake_rules", [
        "MII TX path: TX_EN must be asserted synchronously with the first nibble of the preamble and remain asserted while all nibbles are presented. TX_EN must de-assert before the first TX_CLK after the final nibble.",
        "MII RX path: RX_DV must remain asserted continuously from the first recovered nibble through the final recovered nibble, and de-assert before the first RX_CLK that follows the final nibble. RX_DV must encompass the frame starting no later than the SFD.",
        "MII CRS: asserted whenever either TX or RX medium is non-idle; remains asserted throughout a collision condition. Need not be synchronous to TX_CLK or RX_CLK.",
        "MII COL: asserted on collision detection (half-duplex only); behaviour is unspecified in full-duplex modes.",
        "GMII: same handshake rules as MII, but on a byte-wide path at 125 MHz with GTX_CLK driven by the MAC.",
        "MDIO Clause 22: STA drives PRE + ST + OP + PHYAD + REGAD; on a Read, both sides go high-Z during the first TA bit and the PHY drives a 0 during the second TA bit before driving 16 data bits MSB first. On a Write, STA drives 10 during TA then 16 data bits.",
        "MDIO Clause 45: each transaction is two consecutive 64-bit cycles — an Address cycle (OP=00) writes the 16-bit indirect address, then a Data cycle (OP=01 / 11 / 10) accesses the selected register.",
        "PAUSE frame: receiver checks DA = 01:80:C2:00:00:01 and EtherType = 0x8808 and opcode = 0x0001 before entering the paused state for the indicated number of pause quanta (1 quantum = 512 bit times).",
    ])
    d.setdefault("burst_based", False)
    d.setdefault("byte_oriented", True)
    d.setdefault("addressing", {
        "mac_address_width_bits":      48,
        "phyad_width_bits":            5,
        "regad_clause22_width_bits":   5,
        "devad_clause45_width_bits":   5,
        "regad_clause45_width_bits":   16,
        "ethertype_width_bits":        16,
        "vlan_vid_width_bits":         12,
        "vlan_pcp_width_bits":         3,
        "broadcast_address":           "FF:FF:FF:FF:FF:FF",
        "pause_multicast_address":     "01:80:C2:00:00:01",
        "slow_protocols_multicast":    "01:80:C2:00:00:02",
        "lldp_multicast_addresses":    ["01:80:C2:00:00:0E (nearest bridge)", "01:80:C2:00:00:03 (nearest non-TPMR bridge)", "01:80:C2:00:00:00 (nearest customer bridge)"],
    })
    d.setdefault("frame_format", {
        "mac_data_frame":     "Preamble(7×0x55) + SFD(0xD5) + DA(6 B) + SA(6 B) + Type/Length(2 B) + Payload(46-1500 B) + Pad(0-46 B) + FCS(4 B CRC-32).",
        "vlan_tagged_frame":  "Preamble + SFD + DA(6 B) + SA(6 B) + TPID(0x8100, 2 B) + TCI(2 B = PCP[3] + DEI[1] + VID[12]) + EtherType/Length(2 B) + Payload + FCS — max 1522 B.",
        "pause_frame":        "DA = 01:80:C2:00:00:01, EtherType = 0x8808, MAC Control Opcode = 0x0001, Pause Quanta (16 b), pad to 64 B, FCS.",
        "mdio_c22_frame":     "PRE(32) + ST(01) + OP(10/01) + PHYAD(5) + REGAD(5) + TA(2) + DATA(16) — total 64 MDC cycles (32 PRE + 32 frame).",
        "mdio_c45_address":   "PRE(32) + ST(00) + OP(00) + PRTAD(5) + DEVAD(5) + TA(10) + ADDR(16) — 64 MDC cycles.",
        "mdio_c45_data":      "PRE(32) + ST(00) + OP(01/11/10) + PRTAD(5) + DEVAD(5) + TA + DATA(16) — 64 MDC cycles, must follow an Address cycle on the same DEVAD.",
    })
    _write(p, d)


def _apply_l4(gd: Path) -> None:
    p = gd / "L4_REGMAP.json"
    if not p.is_file():
        return
    d = _read(p)
    d["register_map_present"] = True
    d.setdefault("register_address_scheme",
        "Each PHY exposes a 32-entry × 16-bit Clause-22 register file accessed via the MDIO management bus (PHYAD 5 bits + REGAD 5 bits). MMD-extended access (Clause 45) widens the addressing to PHYAD 5 + DEVAD 5 + 16-bit register, enabling a 32 × 32 × 65 536 register space per MDIO bus segment.")
    d.setdefault("phy_clause22_register_map", [
        {"reg": 0,  "name": "Control Register (BMCR)",                          "width_bits": 16, "access": "R/W (some bits Self-Clearing)", "purpose": "PHY Reset, Loopback, Speed Selection (10/100/1000), AutoNeg Enable + Restart, Power Down, Isolate, Duplex Mode, Collision Test, Unidirectional Enable."},
        {"reg": 1,  "name": "Status Register (BMSR)",                           "width_bits": 16, "access": "RO + RO/LH",  "purpose": "Capability + status: 100BASE-T4/X HD+FD, 10BASE-T HD+FD, 100BASE-T2 HD+FD, Extended Status, MF Preamble Suppression, AutoNeg Complete, Remote Fault, AutoNeg Ability, Link Status, Jabber Detect, Extended Capability."},
        {"reg": 2,  "name": "PHY Identifier 1",                                 "width_bits": 16, "access": "RO",          "purpose": "Bits 3-18 of the manufacturer's OUI (24-bit IEEE-assigned)."},
        {"reg": 3,  "name": "PHY Identifier 2",                                 "width_bits": 16, "access": "RO",          "purpose": "Bits 19-24 of OUI (6 b) + Model Number (6 b) + Revision Number (4 b)."},
        {"reg": 4,  "name": "Auto-Negotiation Advertisement (ANAR)",            "width_bits": 16, "access": "R/W",         "purpose": "Local-side Base Page advertised on the link: Selector[4:0], Tech Ability[7:0], PAUSE, Asym-PAUSE, Remote Fault, Acknowledge, Next Page."},
        {"reg": 5,  "name": "Auto-Negotiation Link Partner Ability (ANLPAR)",   "width_bits": 16, "access": "RO",          "purpose": "Base Page received from the link partner. Same field layout as ANAR."},
        {"reg": 6,  "name": "Auto-Negotiation Expansion (ANER)",                "width_bits": 16, "access": "RO + RO/LH",  "purpose": "Link Partner AutoNeg Able, Page Received, Next Page Able, Link Partner Next Page Able, Parallel Detection Fault."},
        {"reg": 7,  "name": "Auto-Negotiation Next Page Transmit (ANNPTR)",     "width_bits": 16, "access": "R/W",         "purpose": "Outbound Next Page message (Message Code or Unformatted)."},
        {"reg": 8,  "name": "Auto-Negotiation Link Partner Received Next Page", "width_bits": 16, "access": "RO",          "purpose": "Inbound Next Page from link partner."},
        {"reg": 9,  "name": "MASTER-SLAVE Control Register (1000BASE-T)",       "width_bits": 16, "access": "R/W",         "purpose": "1000BASE-T Master/Slave manual mode + value, Port Type (Multi/Single), 1000BASE-T HD/FD ability, Test mode."},
        {"reg": 10, "name": "MASTER-SLAVE Status Register (1000BASE-T)",        "width_bits": 16, "access": "RO + RO/LH",  "purpose": "MASTER-SLAVE Configuration Resolution, Fault, Local + Remote Receiver Status, LP 1000BASE-T HD+FD, Idle Error Count."},
        {"reg": 11, "name": "Reserved (10-14)",                                  "width_bits": 16, "access": "Reserved",     "purpose": "Reserved for future IEEE 802.3 standardization."},
        {"reg": 15, "name": "Extended Status Register",                          "width_bits": 16, "access": "RO",          "purpose": "1000BASE-X FD+HD ability, 1000BASE-T FD+HD ability, 10G-class extensions."},
        {"reg": 16, "name": "Vendor-specific (16-31)",                           "width_bits": 16, "access": "Implementation","purpose": "Vendor-defined; commonly used for PHY-specific control / status / interrupt / LED / energy-detect / Smart-EEE."},
    ])
    d.setdefault("bmcr_bit_definitions", [
        {"bit": "0.15", "name": "Reset",                       "description": "1 = PHY reset (self-clearing); 0 = normal operation. Reset must complete within 0.5 s."},
        {"bit": "0.14", "name": "Loopback",                    "description": "1 = enable PHY internal loopback (TX path → RX path, isolating from medium); 0 = normal."},
        {"bit": "0.13", "name": "Speed Selection LSB",         "description": "{0.6,0.13} = 00 → 10 Mb/s, 01 → 100 Mb/s, 10 → 1000 Mb/s, 11 → Reserved. Ignored when AutoNeg Enable (0.12) = 1."},
        {"bit": "0.12", "name": "Auto-Negotiation Enable",     "description": "1 = enable AutoNeg process (0.6/0.13/0.8 ignored); 0 = manual configuration."},
        {"bit": "0.11", "name": "Power Down",                  "description": "1 = low-power state, PHY still responds to MDIO; 0 = normal."},
        {"bit": "0.10", "name": "Isolate",                     "description": "1 = electrically isolate PHY data paths from MII / GMII; PHY still responds to MDIO."},
        {"bit": "0.9",  "name": "Restart Auto-Negotiation",    "description": "1 = restart AutoNeg (self-clearing); 0 = normal."},
        {"bit": "0.8",  "name": "Duplex Mode",                 "description": "1 = full duplex; 0 = half duplex. Ignored when AutoNeg Enable (0.12) = 1."},
        {"bit": "0.7",  "name": "Collision Test",              "description": "1 = COL signal test mode (PHY asserts COL on TX_EN); 0 = normal."},
        {"bit": "0.6",  "name": "Speed Selection MSB",         "description": "Used with 0.13 to encode 10 / 100 / 1000 Mb/s manual selection."},
        {"bit": "0.5",  "name": "Unidirectional Enable",       "description": "1 = enable transmit regardless of link valid (full-duplex + AutoNeg off only)."},
        {"bit": "0.4:0","name": "Reserved",                    "description": "Write as 0; read as 0."},
    ])
    d.setdefault("bmsr_bit_definitions", [
        {"bit": "1.15", "name": "100BASE-T4",                  "description": "1 = PHY able to perform 100BASE-T4."},
        {"bit": "1.14", "name": "100BASE-X Full Duplex",       "description": "1 = PHY able to perform 100BASE-TX/FX in full duplex."},
        {"bit": "1.13", "name": "100BASE-X Half Duplex",       "description": "1 = PHY able to perform 100BASE-TX/FX in half duplex."},
        {"bit": "1.12", "name": "10 Mb/s Full Duplex",         "description": "1 = PHY able to perform 10BASE-T in full duplex."},
        {"bit": "1.11", "name": "10 Mb/s Half Duplex",         "description": "1 = PHY able to perform 10BASE-T in half duplex."},
        {"bit": "1.10", "name": "100BASE-T2 Full Duplex",      "description": "1 = PHY able to perform 100BASE-T2 in full duplex."},
        {"bit": "1.9",  "name": "100BASE-T2 Half Duplex",      "description": "1 = PHY able to perform 100BASE-T2 in half duplex."},
        {"bit": "1.8",  "name": "Extended Status",             "description": "1 = Extended Status register (15) is implemented; consult it for gigabit + 10G abilities."},
        {"bit": "1.7",  "name": "Unidirectional Ability",      "description": "1 = PHY can encode + transmit when no valid link is established."},
        {"bit": "1.6",  "name": "MF Preamble Suppression",     "description": "1 = PHY accepts management frames without the 32-bit preamble."},
        {"bit": "1.5",  "name": "Auto-Negotiation Complete",   "description": "1 = AutoNeg process has completed."},
        {"bit": "1.4",  "name": "Remote Fault",                "description": "1 = remote fault detected (latching high)."},
        {"bit": "1.3",  "name": "Auto-Negotiation Ability",    "description": "1 = PHY is able to perform AutoNeg."},
        {"bit": "1.2",  "name": "Link Status",                 "description": "1 = link is up (latching low — sticky-low until re-read after link goes down)."},
        {"bit": "1.1",  "name": "Jabber Detect",               "description": "1 = jabber condition detected (10BASE-T only, latching high)."},
        {"bit": "1.0",  "name": "Extended Capability",         "description": "1 = extended register set is provided (registers 4-15)."},
    ])
    d.setdefault("anar_field_layout",
        "ANAR (reg 4) carries the Base Page advertised on the link: [15] Next Page, [14] reserved, [13] Remote Fault, [12] reserved, [11] Asymmetric PAUSE, [10] PAUSE (symmetric), [9] 100BASE-T4, [8] 100BASE-TX Full Duplex, [7] 100BASE-TX, [6] 10BASE-T Full Duplex, [5] 10BASE-T, [4:0] Selector Field (00001 = IEEE 802.3).")
    d.setdefault("anlpar_field_layout",
        "ANLPAR (reg 5) carries the link partner's received Base Page; same field layout as ANAR plus [14] Acknowledge bit set by the partner.")
    d.setdefault("fcs_polynomial", {
        "name":          "IEEE 802.3 CRC-32",
        "polynomial":    "x^32 + x^26 + x^23 + x^22 + x^16 + x^12 + x^11 + x^10 + x^8 + x^7 + x^5 + x^4 + x^2 + x + 1",
        "hex":           "0x04C11DB7",
        "reflected_hex": "0xEDB88320",
        "covers":        "DA + SA + Type/Length + Payload + Pad (NOT including Preamble + SFD).",
        "initial_value": "0xFFFFFFFF",
        "final_xor":     "0xFFFFFFFF",
        "bit_order":     "LSB-first within each byte; FCS is appended MSB-byte first on the wire.",
        "width_bits":    32,
    })
    d.setdefault("clause45_mmd_devad_assignments", [
        {"devad": 1,  "name": "PMA/PMD",       "purpose": "Physical Medium Attachment + Physical Medium Dependent sublayer registers."},
        {"devad": 2,  "name": "WIS",           "purpose": "WAN Interface Sublayer (10GBASE-W only)."},
        {"devad": 3,  "name": "PCS",           "purpose": "Physical Coding Sublayer registers."},
        {"devad": 4,  "name": "PHY XS",        "purpose": "PHY Extender Sublayer (XAUI / XGXS)."},
        {"devad": 5,  "name": "DTE XS",        "purpose": "DTE Extender Sublayer."},
        {"devad": 6,  "name": "TC",            "purpose": "Transmission Convergence (BASE-T1 / PON)."},
        {"devad": 7,  "name": "Auto-Negotiation","purpose": "Clause 45 Auto-Negotiation MMD."},
        {"devad": 8,  "name": "Separated PMA 1","purpose": "Per-lane PMA (multi-lane PHYs)."},
        {"devad": 13, "name": "EEE",           "purpose": "Energy Efficient Ethernet (Clause 78) registers."},
        {"devad": 29, "name": "Clause 22 Access","purpose": "Tunnel for Clause-22 register space through a Clause-45 bus."},
        {"devad": "30..31", "name": "Vendor-specific","purpose": "Vendor-defined MMDs."},
    ])
    d["notes"] = (
        "Clause 22 defines registers 0-7 as mandatory + reserves 8-15 for "
        "standardization; many gigabit / 10G / EEE / TPS-1 features moved "
        "to Clause 45 MMD space. Vendor-specific registers live in 16-31 "
        "(Clause 22) or DEVAD 30-31 (Clause 45). The PHY ID (registers "
        "2/3) is OTP / metal-mask burned and reflects the IEEE-assigned "
        "manufacturer OUI.")
    _write(p, d)


def _apply_l5(gd: Path) -> None:
    p = gd / "L5_ADI_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["analog_digital_interface_present"] = True
    d["signaling_summary"] = (
        "The MII (Clause 22), GMII (Clause 35), and MDIO (Clauses 22 + 45) themselves carry only single-ended LVTTL / LVCMOS digital signals — the analog signaling is entirely encapsulated inside the PHY, on the MDI side. Per Clause 22.4.4, MII receivers interpret Vi ≥ 2.00 V as logic-1 and Vi ≤ 0.80 V as logic-0; MII drivers must produce Voh ≥ 2.40 V at Ioh = -4.0 mA and Vol ≤ 0.40 V at Iol = 4.0 mA. The MDI-side line coding is PMD-specific: 10BASE-T uses Manchester @ 10 Mbaud with ±2.5 V differential pulses on Cat 3 UTP; 100BASE-TX uses 4B/5B + MLT-3 @ 125 Mbaud with three-level (~±1 V) signaling on Cat 5 UTP; 100BASE-FX uses 4B/5B + NRZI on multimode fiber; 1000BASE-T uses PAM5 (5-level, ±2 V / ±1 V / 0) @ 125 Mbaud on each of 4 Cat 5e pairs simultaneously (8B1Q4 + Trellis coding); 1000BASE-X uses 8B/10B @ 1.25 GBd on fiber or shielded copper.")
    d.setdefault("mii_dc_characteristics", {
        "logic_high_output_voltage_V_min": 2.40,
        "logic_low_output_voltage_V_max":  0.40,
        "drive_current_Ioh_mA": -4.0,
        "drive_current_Iol_mA":  4.0,
        "receiver_logic_high_threshold_V_min": 2.00,
        "receiver_logic_low_threshold_V_max":  0.80,
        "supply_voltage_V_nominal": 5.0,
        "supply_voltage_tolerance_percent": 5,
        "load_current_max_per_PHY_mA": 750,
        "input_capacitance_max_pF":   8,
        "mdio_input_capacitance_max_pF": 10,
    })
    d.setdefault("mii_ac_characteristics", {
        "TX_CLK_freq_MHz_at_100Mb_s": 25,
        "TX_CLK_freq_MHz_at_10Mb_s":  2.5,
        "TX_CLK_duty_cycle_min_percent": 35,
        "TX_CLK_duty_cycle_max_percent": 65,
        "TX_CLK_tolerance_ppm": 100,
        "RX_CLK_duty_cycle_min_percent": 35,
        "RX_CLK_duty_cycle_max_percent": 65,
        "MII_setup_time_ns_min":   10,
        "MII_hold_time_ns_min":     0,
        "MII_clock_to_output_ns_min": 0,
        "MII_clock_to_output_ns_max": 25,
        "MDC_max_freq_MHz": 2.5,
        "MDC_min_period_ns": 400,
        "MDC_min_high_low_ns": 160,
    })
    d.setdefault("gmii_ac_characteristics", {
        "GTX_CLK_freq_MHz": 125,
        "RX_CLK_freq_MHz":  125,
        "data_path_width_bits": 8,
        "GMII_setup_time_ns_min": 2.0,
        "GMII_hold_time_ns_min":  0.5,
    })
    d.setdefault("rgmii_ac_characteristics", {
        "TX_CLK_freq_MHz_at_1Gb_s":   125,
        "TX_CLK_freq_MHz_at_100Mb_s":  25,
        "TX_CLK_freq_MHz_at_10Mb_s":   2.5,
        "data_path_width_bits": 4,
        "clocking": "DDR — TXD[3:0] / RXD[3:0] sampled on both edges of TX_CLK / RX_CLK",
        "ctl_encoding": "TX_CTL on rising edge = TX_EN; TX_CTL on falling edge = TX_EN XOR TX_ERR (same for RX_CTL / RX_DV / RX_ER)",
        "ck_data_skew_ns_min": -0.5,
        "ck_data_skew_ns_max":  0.5,
        "ck_data_skew_with_internal_delay_ns": 1.0,
        "ck_data_skew_with_internal_delay_tolerance_ns": 0.5,
    })
    d.setdefault("phy_mdi_signaling", [
        {"phy_class": "10BASE-T",      "line_code": "Manchester",                   "symbol_rate_MBd": 10,    "levels": "differential ±2.5 V pulses", "medium": "Cat 3/4/5 UTP, 2 pairs", "max_segment_m": 100},
        {"phy_class": "100BASE-TX",    "line_code": "4B/5B + MLT-3",                "symbol_rate_MBd": 125,   "levels": "three-level (±1 V, 0 V)",   "medium": "Cat 5 UTP, 2 pairs",   "max_segment_m": 100},
        {"phy_class": "100BASE-FX",    "line_code": "4B/5B + NRZI",                 "symbol_rate_MBd": 125,   "levels": "ON / OFF optical (~1300 nm)", "medium": "62.5/125 µm multimode fiber", "max_segment_m": 2000},
        {"phy_class": "1000BASE-T",    "line_code": "8B1Q4 + PAM5 + Trellis coding","symbol_rate_MBd_per_pair": 125, "levels": "five-level (-2,-1,0,+1,+2 V scaled)", "medium": "Cat 5e UTP, 4 pairs (full-duplex on each)", "max_segment_m": 100},
        {"phy_class": "1000BASE-X (LX/SX/CX)", "line_code": "8B/10B + NRZ",         "symbol_rate_GBd": 1.25,  "levels": "differential ±400 mV typical","medium": "Multimode/single-mode fiber or shielded copper", "max_segment_m_LX": 5000},
    ])
    d.setdefault("auto_negotiation_signaling", {
        "encoding": "Fast Link Pulse (FLP) bursts. Each burst contains a sequence of 17-33 link pulses spaced 62.5 ± 7 µs apart; alternating positions carry clock pulses and data pulses, encoding a 16-bit Base Page (Selector + Tech Ability + Remote Fault + Acknowledge + Next Page).",
        "burst_interval_ms_min": 8,
        "burst_interval_ms_max": 24,
        "link_integrity_compat": "10BASE-T Normal Link Pulse (NLP) is a single pulse every 16 ± 8 ms; a 10BASE-T-only partner is detected by Parallel Detect.",
    })
    d.setdefault("isolate_state", {
        "definition":     "BMCR bit 0.10 = 1. PHY drives no MII / GMII outputs (TX_CLK, RX_CLK, RX_DV, RX_ER, RXD, COL, CRS are high-impedance) and ignores all MII inputs (TXD, TX_EN, TX_ER, GTX_CLK). MDIO remains active.",
        "default_value":  "0.10 default = 1 when PHY is attached via the 22.6 mechanical interface (to avoid multi-driver contention).",
    })
    d.setdefault("power_down_state", {
        "definition":     "BMCR bit 0.11 = 1. PHY enters low-power state; specific behaviour implementation-defined; MDIO must remain responsive. PHY shall not emit spurious signals on the MII / GMII while in or transitioning to power-down.",
        "exit_latency_s_max": 0.5,
    })
    d.setdefault("voltage_classes", [
        "MII / GMII / MDIO: 5 V LVTTL (Clause 22-vintage) or 3.3 V / 2.5 V / 1.8 V LVCMOS for modern integrations.",
        "10BASE-T: ±2.5 V differential pulses on twisted pair.",
        "100BASE-TX: ~±1 V three-level MLT-3.",
        "1000BASE-T: five-level PAM5 with scaled amplitude, ~2 V differential peak.",
        "1000BASE-X fiber: AC-coupled differential NRZ at ~400-800 mV pp, 1.25 GBd.",
        "Auto-Negotiation FLP: same line driver as 10BASE-T NLP — ±2.5 V pulses on twisted pair.",
    ])
    _write(p, d)


def _apply_l6(gd: Path) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("fsm_states_mac_tx", [
        {"name": "TX_IDLE",         "description": "MAC has no frame to transmit; TX_EN held de-asserted; TXD driven to don't-care; CRS / COL monitored for medium activity (half-duplex)."},
        {"name": "TX_DEFER",        "description": "(Half-duplex only) CRS is asserted; MAC waits until the medium is idle for at least one inter-frame gap (96 BT) before proceeding to TX_PREAMBLE."},
        {"name": "TX_IFG",          "description": "Counting down the 96-bit-time inter-frame gap after the previous frame; TX_EN held de-asserted."},
        {"name": "TX_PREAMBLE",     "description": "Assert TX_EN synchronously with the first nibble (or byte) of the 7-octet preamble (0x55). Counter steps through 14 nibbles (or 7 bytes) of preamble."},
        {"name": "TX_SFD",          "description": "Drive the 1-octet SFD (0xD5) — 2 nibbles or 1 byte — and arm the FCS engine to start CRC-32 computation on the next octet (DA byte 0)."},
        {"name": "TX_DA_SA_TYPE_DATA","description": "Drive Destination Address (6 B) + Source Address (6 B) + Type/Length (2 B) + Payload (≥ 46 B after pad) onto TXD; CRC engine updates each cycle. TX_EN stays asserted."},
        {"name": "TX_PAD",          "description": "If the frame length excluding FCS is < 60 B, zero-pad with 0x00 octets until 60 B have been driven post-SFD. CRC engine continues over pad bytes."},
        {"name": "TX_FCS",          "description": "Drive the 4 octets of FCS (CRC-32 result, MSB-byte first, LSB-bit first within each byte) onto TXD; TX_EN still asserted."},
        {"name": "TX_EPD",          "description": "De-assert TX_EN before the next TX_CLK edge after the final FCS nibble; PHY emits End-of-Frame delimiter per its PMD class (e.g. /T//R/ for 100BASE-X)."},
        {"name": "TX_BACKOFF",      "description": "(Half-duplex only) On collision, send JAM pattern, then compute backoff = random(0, 2^min(N,10)) × 512 BT for attempt number N (1-16), wait, and return to TX_DEFER. After 16 attempts, abort with Excessive Collisions."},
    ])
    d.setdefault("fsm_states_mac_rx", [
        {"name": "RX_IDLE",        "description": "Waiting for CRS or RX_DV from the PHY. RXD ignored."},
        {"name": "RX_PREAMBLE_LOCK","description": "RX_DV asserted; scanning incoming RXD nibbles for the SFD nibble pattern 0xD (last nibble of SFD = 1101). Until SFD is found, accumulate preamble bytes."},
        {"name": "RX_SFD",         "description": "SFD nibble (0xD) detected; arm CRC-32 engine and start byte-aligned capture into the frame buffer beginning with DA byte 0."},
        {"name": "RX_FRAME",       "description": "Stream RXD nibbles (or bytes) into the receive FIFO, MAC client framing, and CRC engine. Track byte count for min/max enforcement."},
        {"name": "RX_FCS_CHECK",   "description": "RX_DV de-asserted (PHY signalled end-of-frame). Compare last 4 captured octets against the CRC-32 of DA + SA + Type/Length + Payload + Pad. On mismatch raise an FCS-error indication."},
        {"name": "RX_DELIVER",     "description": "FCS good and (length within 64-1518 B for untagged, or 64-1522 B for VLAN-tagged): deliver MAC client data + (DA, SA, Type/Length) tuple to the LLC / IP / VLAN layer."},
        {"name": "RX_ERROR",       "description": "RX_ER asserted, FCS bad, runt (< 64 B), giant (> 1518/1522 B), or False-Carrier (RXD = 0x1110 with RX_DV = 0 and RX_ER = 1): discard frame, increment the appropriate error counter."},
    ])
    d.setdefault("fsm_states_csma_cd_half_duplex", [
        {"name": "Sense",        "description": "Monitor CRS. If asserted, defer; if not asserted for ≥ 96 BT, proceed."},
        {"name": "Transmit",     "description": "Drive preamble..FCS onto TXD with TX_EN asserted; sample COL each TX_CLK."},
        {"name": "Collision",    "description": "COL asserted while TX_EN is asserted: immediately transmit a 32-bit JAM pattern, then enter Backoff. If the collision was detected after 512 BT into the frame it is a Late Collision (no backoff retry; just abort)."},
        {"name": "Backoff",      "description": "Truncated-binary-exponential: backoff slots = uniform-random(0, 2^min(N,10)) where N = attempt # (1..16); each slot = 512 BT. Wait then return to Sense."},
        {"name": "Abort",        "description": "After 16 unsuccessful attempts, abort with Excessive Collisions error; raise a MAC error indication to the upper layer."},
    ])
    d.setdefault("fsm_states_mdio_master_clause22", [
        {"name": "MDIO_IDLE",     "description": "MDC running; MDIO driven high (or high-Z observed as 1 due to PHY pull-up)."},
        {"name": "MDIO_PRE",      "description": "STA drives 32 logic-1 bits on MDIO during 32 MDC cycles to wake the PHY (may be suppressed if BMSR bit 1.6 indicates preamble suppression)."},
        {"name": "MDIO_ST_OP",    "description": "Drive ST (01) + OP (10 read / 01 write) — 4 MDC cycles, MSB first."},
        {"name": "MDIO_PHYAD",    "description": "Drive PHYAD[4:0] MSB first over 5 MDC cycles."},
        {"name": "MDIO_REGAD",    "description": "Drive REGAD[4:0] MSB first over 5 MDC cycles."},
        {"name": "MDIO_TA",       "description": "Write: drive 10. Read: tri-state for the first bit and let the PHY drive 0 on the second."},
        {"name": "MDIO_DATA",     "description": "16 MDC cycles. Write: STA drives data bit 15 → bit 0 MSB first. Read: PHY drives data bit 15 → bit 0."},
        {"name": "MDIO_DONE",     "description": "Return to MDIO_IDLE; MDIO floats to logic-1."},
    ])
    d.setdefault("fsm_states_auto_negotiation_clause28", [
        {"name": "AN_DISABLE",       "description": "AutoNeg disabled (BMCR 0.12 = 0). Use manual speed + duplex settings."},
        {"name": "AN_ENABLE",        "description": "AutoNeg enabled. Reset state machine; arm AN_TRANSMIT_DISABLE."},
        {"name": "AN_ABILITY_DETECT","description": "Begin transmitting FLP bursts encoding ANAR (reg 4) Base Page. Listen for FLP bursts from the partner."},
        {"name": "AN_ACK_DETECT",    "description": "Once at least one full Base Page received, set Acknowledge bit, re-send Base Page until partner acknowledges back."},
        {"name": "AN_COMPLETE_ACK",  "description": "Both ends have acknowledged. If either side has Next-Page bit set, transition to NEXT_PAGE_WAIT; else proceed to IDLE_DETECT."},
        {"name": "AN_NEXT_PAGE_WAIT","description": "Exchange Next Page messages (one or more) until both sides clear Next-Page bit."},
        {"name": "AN_IDLE_DETECT",   "description": "Stop FLP transmission; expect a quiet period; resolve the highest common ability via priority table; configure PHY accordingly."},
        {"name": "AN_LINK_OK",       "description": "Move to the negotiated PMA / PMD; BMSR bit 1.5 set; data signaling begins. BMCR 0.9 (Restart AutoNeg) returns the FSM to AN_ABILITY_DETECT."},
        {"name": "AN_PARALLEL_DETECT","description": "Fallback when partner does not emit FLP bursts: detect partner's data-link integrity tone (10BASE-T NLP or 100BASE-TX scrambled idle or 100BASE-T4 link beat) and bring up the link in that PMA only (no duplex negotiation; default to half-duplex)."},
    ])
    d.setdefault("fsm_hints", {
        "trigger": "TX FSM: leaves TX_IDLE when MAC client asserts a frame-transmit request and the medium is idle (half-duplex) or always (full-duplex). RX FSM: leaves RX_IDLE on RX_DV assertion (or on RX_ER/RXD=0x1110 False Carrier indication). MDIO FSM: STA initiates each transaction; PHY is purely reactive.",
        "rule":    "The MAC enforces 96-BT IFG between back-to-back transmits. The PHY emits TX_CLK (MII) or accepts GTX_CLK (GMII) and is responsible for line-coding the nibble/byte stream onto the medium. CRC-32 is computed over DA + SA + Type/Length + Payload + Pad (NOT including preamble + SFD + FCS itself).",
        "abort":   "Excessive Collisions (16 retries in half-duplex), Late Collision (post-512-BT), FCS error on RX, RX_ER asserted, Power Down (BMCR 0.11), or Isolate (BMCR 0.10) all force the MAC ↔ PHY data path into an inactive state.",
    })
    d.setdefault("anti_deadlock_rule",
        "Full-duplex operation eliminates the CSMA/CD collision-deadlock case entirely — independent TX and RX wire pairs cannot collide. In half-duplex, the truncated-binary-exponential backoff with a hard 16-retry cap ensures progress under contention: each colliding station waits a different random slot, so the probability of repeated collisions decays geometrically. The PAUSE-frame mechanism (Clause 31) prevents receiver-overflow deadlock by allowing the receiver to stall the sender for a specified pause-quanta interval rather than dropping frames.")
    d.setdefault("exit_from_reset_or_poweron",
        "BMCR Reset (0.15 = 1) or PHY power-on: PHY clears BMCR + BMSR to defaults; AutoNeg Enable (0.12) defaults to 1 if the PHY supports AutoNeg, else 0. PHY runs the AutoNeg state machine (if enabled), then on completion the negotiated PMA / PMD takes the link to Link Up and BMSR bit 1.5 + bit 1.2 are set. The MAC is held in RX_IDLE / TX_IDLE until the MAC client and the PHY both signal Link Up.")
    d.setdefault("default_ready_state_recommendation", {
        "TX_idle":  "TX_EN = 0; TXD = 0x0; TX_ER = 0; PHY in normal-IDLE on the medium (e.g. continuous /I/ /I/ idle code-groups for 100BASE-TX, or no FLP between AutoNeg bursts).",
        "RX_idle":  "RX_DV = 0; RXD = 0x0; RX_ER = 0; CRS = 0; COL = 0. PHY's receiver still tracks line activity to assert CRS / generate False Carrier.",
        "MDIO_idle":"MDC running; MDIO line idle-high (1.5 kΩ PHY pull-up) — no STA driver active.",
    })
    d.setdefault("configurations", [
        {"name": "Half-duplex 10BASE-T / 100BASE-TX",      "description": "CSMA/CD; CRS + COL active; backoff on collision; max 1 collision domain per shared segment / repeater hub."},
        {"name": "Full-duplex 10/100/1000 Mb/s switched",  "description": "No CSMA/CD; independent TX + RX; CRS / COL ignored; PAUSE-frame flow control."},
        {"name": "1000BASE-T MASTER / SLAVE",              "description": "1000BASE-T PHY pair runs a Master/Slave configuration (resolved by reg 9 manual setting or AutoNeg); master sources the symbol clock, slave recovers it; full-duplex on all 4 pairs simultaneously."},
        {"name": "MDIO single-PHY / multi-PHY",            "description": "PHYAD = 00000 always responds (single-PHY); multi-PHY topologies require unique PHYAD per device with the STA driving the MDC + MDIO bus to all of them."},
        {"name": "Clause 22 management",                    "description": "32 × 16-bit register file per PHY; mandatory BMCR + BMSR + PHY ID + ANAR / ANLPAR + ANER."},
        {"name": "Clause 45 MMD management",               "description": "32 × 32 × 65 536 register file per PHY for gigabit / 10G / EEE / TPS-1 — two-cycle address-then-data MDIO protocol."},
    ])
    d.setdefault("timing_dependency_rule",
        "MII TX path is synchronous to TX_CLK (PHY-sourced, 25 MHz @100 Mb/s or 2.5 MHz @10 Mb/s). MII RX path is synchronous to RX_CLK (PHY-sourced, may be recovered from received data or a nominal clock). Per Clause 22.2.2.2, RX_CLK and TX_CLK are NOT required to maintain any guaranteed phase relationship. GMII TX path is synchronous to GTX_CLK (MAC-sourced, 125 MHz); GMII RX path is synchronous to RX_CLK (PHY-sourced, 125 MHz). MDC is asynchronous with respect to TX_CLK and RX_CLK; the MDC frequency may differ from any data-path clock.")
    _write(p, d)


def _apply_l7(gd: Path) -> None:
    p = gd / "L7_TEST_DEBUG.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_debug_architecture_present"] = True
    d.setdefault("spec_provided_observability", [
        {"name": "BMSR.Link Status (bit 1.2)",         "purpose": "Latching-low link-up indication; provides software-readable link state. Clears (re-reads to 0) after a link-down event."},
        {"name": "BMSR.AutoNeg Complete (bit 1.5)",   "purpose": "Indicates AutoNeg has finished and the negotiated speed/duplex is in effect."},
        {"name": "BMSR.Remote Fault (bit 1.4)",        "purpose": "Latching-high remote-fault indication from the link partner (e.g. 100BASE-X far-end fault)."},
        {"name": "BMSR.Jabber Detect (bit 1.1)",       "purpose": "Latching-high jabber-detected indication (10BASE-T only — frame too long)."},
        {"name": "ANER (reg 6)",                       "purpose": "AutoNeg expansion: Page Received (latching), LP AutoNeg Able, Parallel Detection Fault (latching), Next Page Able."},
        {"name": "MASTER-SLAVE Status (reg 10)",       "purpose": "1000BASE-T MS resolution, configuration fault, local + remote receiver status, idle error counter."},
        {"name": "MII signals at the connector",       "purpose": "TX_CLK, RX_CLK, TXD[3:0], RXD[3:0], TX_EN, RX_DV, TX_ER, RX_ER, CRS, COL all probeable at the Clause-22 mechanical interface."},
        {"name": "MDIO bus capture",                    "purpose": "A logic analyzer on MDC + MDIO can record every C22 / C45 management transaction — supports replaying register accesses."},
        {"name": "Counters in PHY vendor-specific registers", "purpose": "Optional but ubiquitous: FCS error count, alignment error count, false-carrier count, late-collision count, excessive-collision count, jabber count, RX_ER count, single + multiple-collision counts."},
    ])
    d.setdefault("error_detection_mechanisms", [
        "FCS (CRC-32) mismatch — frame discarded, FCS-error counter incremented.",
        "Alignment error — frame ends on a non-octet boundary (RX_DV de-asserts mid-octet).",
        "Runt frame — total octets < 64 B (excluding preamble + SFD).",
        "Giant / jumbo frame — total octets > 1518 B (untagged) or > 1522 B (VLAN-tagged); discarded unless implementation supports jumbo frames.",
        "RX_ER asserted during reception — coding-error counter incremented; frame discarded.",
        "False Carrier (RX_DV = 0, RX_ER = 1, RXD = 1110) — false-carrier-event counter incremented; line activity is not a valid frame.",
        "Collision (half-duplex) — single, multiple, and excessive-collision counters; late-collision counter for collisions detected after 512 BT into the frame.",
        "Jabber (10BASE-T only) — PHY detects a transmission > 25-150 ms and asserts a jabber condition, latching BMSR bit 1.1.",
        "MDIO bus contention — STA + PHY both attempting to drive MDIO during TA (read transaction); recoverable via the high-Z TA bit.",
        "Parallel Detection Fault — AutoNeg expansion register bit set when parallel-detect logic resolves multiple PHY types simultaneously.",
    ])
    if _empty(d.get("test_modes")):
        d["test_modes"] = [
            {"name": "BMCR Loopback (bit 0.14)",            "purpose": "PHY internal MII / GMII transmit-path → receive-path loopback. Receive circuit isolated from medium; MAC TX_EN must result in RX_DV within 512 BT."},
            {"name": "BMCR Isolate (bit 0.10)",             "purpose": "Force MII / GMII data signals to high-impedance for multi-PHY board test or hot-insertion staging."},
            {"name": "BMCR Collision Test (bit 0.7)",       "purpose": "Force PHY to assert COL within 512 BT of TX_EN assertion to exercise the half-duplex collision path."},
            {"name": "BMCR Power Down (bit 0.11)",          "purpose": "Low-power state; MDIO still responsive — useful for board-level power-sequencing test."},
            {"name": "MS Test Mode (1000BASE-T reg 9.15:13)","purpose": "1000BASE-T test modes 1-4: distortion / jitter / waveform / wander measurement at the MDI."},
            {"name": "AutoNeg Restart (BMCR bit 0.9)",      "purpose": "Re-run AutoNeg to verify state-machine restart + Base-Page exchange behavior."},
            {"name": "Vendor-specific BIST register",        "purpose": "Many silicon PHYs add a built-in self-test mode in registers 16-31 (Clause 22) or vendor-specific MMDs (Clause 45 DEVAD 30-31)."},
        ]
    d.setdefault("interrupt_or_event_sources", [
        {"event": "Link Status change",      "trigger": "BMSR bit 1.2 transitions 1→0 (link down) or 0→1 (link up) — many PHYs route this to an open-drain INT# pin."},
        {"event": "AutoNeg Complete",        "trigger": "BMSR bit 1.5 transitions to 1 after AutoNeg finishes."},
        {"event": "Remote Fault",            "trigger": "BMSR bit 1.4 set."},
        {"event": "Jabber Detect",           "trigger": "10BASE-T jabber timer expiration; BMSR bit 1.1 set."},
        {"event": "Energy Detect",           "trigger": "Vendor-specific Energy Efficient Ethernet wake event (Clause 78)."},
        {"event": "PAUSE frame received",    "trigger": "MAC Control sublayer recognises a valid 0x8808 / opcode 0x0001 frame; MAC stalls TX for the indicated pause quanta."},
        {"event": "Excessive Collisions",    "trigger": "Half-duplex MAC TX FSM aborts after 16 retries — raises a MAC-error indication."},
        {"event": "FCS error",                "trigger": "Per-frame error indication from the receive MAC."},
    ])
    d.setdefault("loopback_modes_summary", [
        {"name": "Near-end MAC loopback",   "scope": "MAC TX → MAC RX inside the MAC; PHY not exercised."},
        {"name": "PCS loopback (BMCR 0.14)","scope": "MII / GMII TX path → MII / GMII RX path inside the PHY; medium not driven."},
        {"name": "PMA / PMD loopback",      "scope": "Vendor-specific; loops back on the analog side of the PHY (e.g. after the MLT-3 encoder)."},
        {"name": "External cable loopback", "scope": "Physical RJ-45 / fiber loopback plug at the MDI; exercises the entire TX + RX analog chain."},
    ])
    d["notes"] = (
        "IEEE 802.3-2005 does NOT specify JTAG / scan-chain / on-chip BIST "
        "at the protocol level. PHY vendors universally add scan + BIST + "
        "I/O voltage trim + impedance trim in vendor-specific register "
        "space. The Clause-22 BMCR (Loopback, Isolate, Collision Test, "
        "Power Down) and BMSR (Link Status, AutoNeg Complete, Remote "
        "Fault, Jabber) provide a minimum standardized observability + "
        "controllability surface that every conforming PHY must "
        "implement.")
    _write(p, d)


def _apply_l8_consts(gd: Path) -> None:
    p = gd / "L8_RTL_CONSTANTS.json"
    if not p.is_file():
        return
    d = _read(p)
    wp = d.setdefault("width_parameters", {})
    if isinstance(wp, dict):
        for k, v in {
            "PREAMBLE_OCTET_COUNT": 7,
            "PREAMBLE_OCTET_VALUE": "0x55",
            "SFD_OCTET_VALUE": "0xD5",
            "MAC_ADDRESS_WIDTH_BITS": 48,
            "MAC_ADDRESS_OCTETS": 6,
            "ETHERTYPE_WIDTH_BITS": 16,
            "ETHERTYPE_TYPE_THRESHOLD_DEC": 1536,
            "ETHERTYPE_LENGTH_MAX_DEC": 1500,
            "PAYLOAD_MIN_OCTETS": 46,
            "PAYLOAD_MAX_OCTETS": 1500,
            "MIN_FRAME_OCTETS_NO_PREAMBLE": 64,
            "MAX_FRAME_OCTETS_NO_PREAMBLE_UNTAGGED": 1518,
            "MAX_FRAME_OCTETS_NO_PREAMBLE_VLAN": 1522,
            "FCS_WIDTH_BITS": 32,
            "FCS_OCTETS": 4,
            "IFG_BIT_TIMES": 96,
            "MII_DATA_WIDTH_BITS": 4,
            "GMII_DATA_WIDTH_BITS": 8,
            "RGMII_DATA_WIDTH_BITS": 4,
            "RGMII_DDR": True,
            "MII_TX_CLK_MHZ_AT_100M": 25,
            "MII_TX_CLK_MHZ_AT_10M": 2.5,
            "GMII_GTX_CLK_MHZ": 125,
            "RGMII_TX_CLK_MHZ_AT_1G": 125,
            "MDC_MAX_FREQ_MHZ": 2.5,
            "MDC_MIN_PERIOD_NS": 400,
            "MDC_MIN_HIGH_LOW_NS": 160,
            "PHYAD_WIDTH_BITS": 5,
            "REGAD_CLAUSE22_WIDTH_BITS": 5,
            "DEVAD_CLAUSE45_WIDTH_BITS": 5,
            "REGAD_CLAUSE45_WIDTH_BITS": 16,
            "MDIO_PREAMBLE_BITS": 32,
            "MDIO_DATA_WIDTH_BITS": 16,
            "MDIO_C22_FRAME_BITS_POST_PRE": 32,
            "MDIO_C22_TOTAL_BITS": 64,
            "VLAN_TAG_OCTETS": 4,
            "VLAN_TPID": "0x8100",
            "VLAN_PCP_WIDTH_BITS": 3,
            "VLAN_DEI_WIDTH_BITS": 1,
            "VLAN_VID_WIDTH_BITS": 12,
            "PAUSE_DA": "01:80:C2:00:00:01",
            "PAUSE_ETHERTYPE": "0x8808",
            "PAUSE_OPCODE": "0x0001",
            "PAUSE_QUANTUM_BIT_TIMES": 512,
            "JAM_PATTERN_BITS": 32,
            "SLOT_TIME_BIT_TIMES_10_100M": 512,
            "SLOT_TIME_BIT_TIMES_1000M": 4096,
            "MAX_COLLISION_RETRIES": 16,
            "BACKOFF_TRUNCATION_LIMIT": 10,
            "LATE_COLLISION_THRESHOLD_BT": 512,
            "AUTO_NEG_BASE_PAGE_BITS": 16,
            "AUTO_NEG_SELECTOR_IEEE_802_3": "00001",
            "FLP_BURST_PULSE_SPACING_US": 62.5,
            "FLP_BURST_INTERVAL_MS_MIN": 8,
            "FLP_BURST_INTERVAL_MS_MAX": 24,
        }.items():
            wp.setdefault(k, v)
    d.setdefault("mac_frame_field_offsets_bytes_from_da_byte0", {
        "DA":           {"offset": 0,  "octets": 6},
        "SA":           {"offset": 6,  "octets": 6},
        "TYPE_LENGTH":  {"offset": 12, "octets": 2},
        "PAYLOAD_START":{"offset": 14, "octets": "46..1500"},
        "FCS":          {"offset": "frame_end-4", "octets": 4},
    })
    d.setdefault("vlan_tagged_field_offsets_bytes_from_da_byte0", {
        "DA":           {"offset": 0,  "octets": 6},
        "SA":           {"offset": 6,  "octets": 6},
        "VLAN_TPID":    {"offset": 12, "octets": 2, "value": "0x8100"},
        "VLAN_TCI":     {"offset": 14, "octets": 2, "fields": "PCP[15:13] + DEI[12] + VID[11:0]"},
        "TYPE_LENGTH":  {"offset": 16, "octets": 2},
        "PAYLOAD_START":{"offset": 18, "octets": "42..1500"},
        "FCS":          {"offset": "frame_end-4", "octets": 4},
    })
    d.setdefault("fcs_polynomial", {
        "name":          "IEEE 802.3 CRC-32 (Frame Check Sequence)",
        "polynomial":    "x^32 + x^26 + x^23 + x^22 + x^16 + x^12 + x^11 + x^10 + x^8 + x^7 + x^5 + x^4 + x^2 + x + 1",
        "hex":           "0x04C11DB7",
        "reflected_hex": "0xEDB88320",
        "initial_value": "0xFFFFFFFF",
        "final_xor":     "0xFFFFFFFF",
        "input_bit_order": "LSB-first within each byte",
        "output_bit_order":"Complemented and serialised; appended to the frame MSB-byte first",
        "covers":        "DA + SA + Type/Length + Payload + Pad — NOT including Preamble + SFD + FCS itself",
        "width_bits":    32,
    })
    d.setdefault("mdio_clause22_frame_bit_order", {
        "field_order":      ["PRE(32)", "ST(2)", "OP(2)", "PHYAD(5)", "REGAD(5)", "TA(2)", "DATA(16)"],
        "PRE_value":        "all-ones; may be suppressed if both ends support preamble suppression (BMSR 1.6)",
        "ST_value":         "01",
        "OP_read_value":    "10",
        "OP_write_value":   "01",
        "TA_read_value":    "first bit = Z (both sides high-Z), second bit = 0 (driven by PHY)",
        "TA_write_value":   "10 (STA-driven)",
        "DATA_bit_order":   "MSB-first (bit 15 first)",
    })
    d.setdefault("mdio_clause45_frame_bit_order", {
        "field_order":      ["PRE(32)", "ST(2)", "OP(2)", "PRTAD(5)", "DEVAD(5)", "TA(2)", "DATA(16)"],
        "ST_value":         "00",
        "OP_address_value": "00",
        "OP_write_value":   "01",
        "OP_read_value":    "11",
        "OP_post_inc_read": "10",
        "two_cycle_protocol":"Each access is Address cycle (OP=00 writes 16-bit register address into selected MMD) followed by Data cycle (OP=01 / 11 / 10 accesses the selected register)",
    })
    d.setdefault("key_constants_for_RTL_authoring", {
        "is_layered_protocol":       True,
        "has_csma_cd_half_duplex":   True,
        "has_full_duplex":           True,
        "frame_oriented":            True,
        "byte_oriented_at_MAC":      True,
        "nibble_oriented_at_MII":    True,
        "preamble_octets":            7,
        "preamble_value":            "0x55",
        "sfd_value":                 "0xD5",
        "ifg_bit_times":             96,
        "fcs_polynomial_hex":        "0x04C11DB7",
        "fcs_reflected_hex":         "0xEDB88320",
        "fcs_init":                  "0xFFFFFFFF",
        "fcs_final_xor":             "0xFFFFFFFF",
        "ethertype_threshold_dec":   1536,
        "broadcast_mac":             "FF:FF:FF:FF:FF:FF",
        "pause_multicast_mac":       "01:80:C2:00:00:01",
        "pause_ethertype":           "0x8808",
        "vlan_tpid":                 "0x8100",
        "vlan_vid_bits":             12,
        "mdio_pre_bits":             32,
        "mdio_c22_st":               "01",
        "mdio_c45_st":               "00",
    })
    d.setdefault("default_signal_values_when_idle", {
        "TX_EN":  "0 (de-asserted)",
        "TX_ER":  "0 (de-asserted)",
        "TXD":    "0x0 (don't-care; conventionally driven to 0)",
        "RX_DV":  "0 (de-asserted)",
        "RX_ER":  "0 (de-asserted)",
        "RXD":    "0x0 (don't-care; conventionally driven to 0)",
        "CRS":    "0 (de-asserted) when both TX + RX media are idle",
        "COL":    "0 (de-asserted) — only meaningful in half-duplex",
        "MDIO":   "logic-1 (PHY 1.5 kΩ pull-up); STA pull-down may be present",
    })
    _write(p, d)


def _apply_l8_timing(gd: Path) -> None:
    p = gd / "L8_TIMING_WAVEFORM.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("data_rate_waveforms", {
        "10BASE-T":   {"line_rate_Mb_s": 10,   "MII_TX_CLK_MHz":  2.5, "nibble_clock_period_ns": 400, "bit_time_ns": 100},
        "100BASE-X":  {"line_rate_Mb_s": 100,  "MII_TX_CLK_MHz":   25, "nibble_clock_period_ns":  40, "bit_time_ns":  10},
        "1000BASE-T": {"line_rate_Mb_s": 1000, "GMII_GTX_CLK_MHz":125, "byte_clock_period_ns":     8, "bit_time_ns":   1},
        "10GBASE-X":  {"line_rate_Mb_s":10000, "XGMII_clock_MHz":  156.25, "DDR": True, "byte_clock_period_ns": 3.2, "bit_time_ns": 0.1},
    })
    d.setdefault("mii_signal_timing", {
        "TX_CLK_to_TXD_TX_EN_TX_ER_setup_ns_min": 10,
        "TX_CLK_to_TXD_TX_EN_TX_ER_hold_ns_min":   0,
        "TX_CLK_duty_cycle_min_percent":          35,
        "TX_CLK_duty_cycle_max_percent":          65,
        "TX_CLK_freq_tolerance_ppm":             100,
        "RX_CLK_to_RXD_RX_DV_RX_ER_clock_to_output_min_ns": 0,
        "RX_CLK_to_RXD_RX_DV_RX_ER_clock_to_output_max_ns": 25,
        "RX_CLK_duty_cycle_min_percent":          35,
        "RX_CLK_duty_cycle_max_percent":          65,
        "RX_CLK_TX_CLK_phase_relationship":      "None — not guaranteed (per Clause 22.2.2.2 NOTE)",
    })
    d.setdefault("mdio_signal_timing", {
        "MDC_max_freq_MHz":   2.5,
        "MDC_min_period_ns":  400,
        "MDC_min_high_ns":    160,
        "MDC_min_low_ns":     160,
        "MDIO_setup_to_MDC_rising_ns_min": 10,
        "MDIO_hold_after_MDC_rising_ns_min": 10,
        "MDIO_TA_high_Z_window_clauses":  "Read transactions only; first TA bit must be high-Z on both ends, second TA bit driven 0 by PHY",
        "PRE_bit_count":       32,
        "C22_frame_bit_count_no_pre": 32,
        "C22_frame_bit_count_with_pre": 64,
        "C45_frame_bit_count_no_pre": 32,
        "C45_frame_bit_count_with_pre": 64,
    })
    d.setdefault("frame_waveform", {
        "transmit": "TX_EN ↑ on first preamble nibble → TXD shifts 7×0x55 + 0xD5 + DA + SA + Type/Length + Payload + Pad + FCS nibble-by-nibble → TX_EN ↓ on next TX_CLK after final FCS nibble → IFG (96 BT) before next TX_EN ↑.",
        "receive":  "PHY raises CRS as soon as line activity is detected → RX_DV ↑ aligned with first preamble nibble (or sometimes within the preamble) → RXD streams preamble + SFD + DA + ... + FCS → RX_DV ↓ before next RX_CLK after final FCS nibble → CRS ↓ shortly after.",
        "collision_half_duplex": "(half-duplex only) During TX_EN, COL asserts as soon as the PHY detects a colliding signal; MAC immediately switches TXD to a 32-bit JAM pattern, then de-asserts TX_EN. After backoff slots, retry from TX_DEFER.",
    })
    d.setdefault("auto_negotiation_waveform", {
        "FLP_burst_pulse_count_max":      33,
        "FLP_burst_pulse_count_min":      17,
        "FLP_burst_pulse_spacing_us":     62.5,
        "FLP_burst_pulse_spacing_tolerance_us": 7,
        "FLP_burst_interval_ms_min":       8,
        "FLP_burst_interval_ms_max":      24,
        "Base_Page_field_count":          16,
        "Acknowledge_propagation_pages": "At least three identical Base Pages with Acknowledge bit set",
    })
    d.setdefault("csma_cd_timing", {
        "ifg_BT":            96,
        "slot_time_BT_10_100":  512,
        "slot_time_BT_1000":   4096,
        "jam_size_BT":         32,
        "max_attempts":        16,
        "backoff_slot_BT":    512,
        "late_collision_threshold_BT": 512,
    })
    d.setdefault("pause_frame_timing", {
        "pause_quantum_BT":   512,
        "pause_field_octets":   2,
        "max_pause_quanta":  65535,
        "pause_window_at_1Gb_s_us_max": 33.55,
        "pause_window_at_100Mb_s_us_max": 335.5,
        "pause_window_at_10Mb_s_us_max":  3355,
    })
    d.setdefault("transmitter_eye_reference_per_phy",
        "MDI compliance eyes are specified per PMD clause: Figure 14-9 for 10BASE-T, Figure 25-? for 100BASE-TX, Figures 40-19..40-28 for 1000BASE-T. RJ-45 MDI return loss / NEXT specifications are also per PMD clause.")
    d.setdefault("voltage_levels", {
        "MII_LVTTL_Voh_min_V":  2.40,
        "MII_LVTTL_Vol_max_V":  0.40,
        "MII_LVTTL_Vih_min_V":  2.00,
        "MII_LVTTL_Vil_max_V":  0.80,
        "MII_supply_V_nominal": 5.0,
        "MII_supply_V_tolerance_percent": 5,
    })
    d.setdefault("general_timing_rule",
        "All MII / GMII signals are synchronous to TX_CLK (TX path) or RX_CLK (RX path); MDC is asynchronous. Bit times scale linearly with line rate (100 ns at 10 Mb/s, 10 ns at 100 Mb/s, 1 ns at 1 Gb/s); inter-frame gap = 96 BT and slot time = 512 BT (10/100 Mb/s) or 4096 BT (1 Gb/s) are both expressed in bit times so the same MAC FSM scales across the speed range.")
    _write(p, d)


def _apply_l9(gd: Path) -> None:
    p = gd / "L9_INTEGRATION_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("module_role",
        "Wire-level + frame-level + management-interface specification for the Ethernet MAC ↔ PHY boundary. Defines the MAC sublayer (Clause 4) which transmits and receives canonical Ethernet frames; the Reconciliation Sublayer + MII (Clause 22) and GMII (Clause 35) that connect the MAC to any 10/100/1000 Mb/s PHY without re-coding; the MDC + MDIO management bus (Clauses 22 + 45) for per-PHY register access; and the Auto-Negotiation protocol (Clause 28) that brings the link up at the highest common speed and duplex before normal frames flow. PMD-specific clauses (10BASE-T, 100BASE-TX/FX/T4/T2, 1000BASE-T/X, …) and the MDI connector/cabling specs are out of scope of the MAC + RS + MII / GMII / MDIO subset.")
    d.setdefault("topology_description",
        "Each MAC is connected to exactly one PHY via a single MII / GMII / RGMII / XGMII data path. The PHY's MDI side connects to one network medium (twisted pair / fiber). At the network level, every modern Ethernet link is point-to-point and full-duplex behind a switch; legacy CSMA/CD shared-medium half-duplex topologies (repeater hubs, coax) remain spec-compliant but are deprecated.")
    d.setdefault("integration_overview", {
        "mac_per_phy":                       1,
        "phy_per_mac":                       1,
        "mii_data_path_width_bits":          4,
        "gmii_data_path_width_bits":         8,
        "rgmii_data_path_width_bits":        4,
        "rgmii_uses_DDR":                   True,
        "mii_max_clk_MHz":                   25,
        "gmii_max_clk_MHz":                 125,
        "rgmii_max_clk_MHz":                125,
        "mdio_max_clk_MHz":                 2.5,
        "mdio_addr_clause22_phy":             5,
        "mdio_addr_clause22_reg":             5,
        "mdio_addr_clause45_phy":             5,
        "mdio_addr_clause45_devad":           5,
        "mdio_addr_clause45_reg":            16,
        "ifg_BT":                            96,
        "preamble_octets":                    7,
        "sfd_octet":                     "0xD5",
        "fcs_octets":                         4,
        "min_frame_octets_no_preamble":      64,
        "max_frame_octets_no_preamble":    1518,
        "max_frame_octets_no_preamble_vlan":1522,
    })
    d.setdefault("interface_categories", [
        "MAC (Clause 4) — frame assembly + disassembly, FCS, address recognition, IFG enforcement, optional CSMA/CD (half-duplex) and PAUSE-frame flow control (full-duplex).",
        "Reconciliation Sublayer (Clauses 22 + 35) — maps the MAC's PLS_DATA service primitives onto MII or GMII signals; speed-agnostic from the MAC's point of view.",
        "MII (Clause 22, 10/100 Mb/s) — nibble-wide TX + RX data path with PHY-sourced TX_CLK and RX_CLK; CRS + COL for half-duplex.",
        "GMII (Clause 35, 1 Gb/s) — byte-wide path with MAC-sourced GTX_CLK and PHY-sourced RX_CLK at 125 MHz.",
        "RGMII / SGMII / XGMII — industry de-facto reduced-pin / SerDes-attached variants of GMII for board-level interconnect.",
        "MDC + MDIO (Clauses 22 + 45) — single serial management bus shared by 1-32 PHYs per STA.",
        "MDI (PMD-specific) — wire-side interface to the network medium; out of scope of the MAC + RS + MII spec subset.",
    ])
    d.setdefault("interconnect_topologies_supported", [
        "Switched point-to-point full-duplex star (modern dominant case) — one MAC per switch port, one PHY per MAC.",
        "Legacy half-duplex CSMA/CD shared medium via repeater hubs (Clause 27) — deprecated but still in the standard.",
        "Aggregated link (IEEE 802.1AX Link Aggregation Control Protocol, LACP) — multiple parallel point-to-point links treated as one logical channel.",
        "Direct point-to-point full-duplex (DTE ↔ DTE via cross-over cable or AutoMDIX) — the simplest two-station Ethernet.",
        "Daisy-chained PHYs on the MDIO bus — one STA + multiple PHYs at distinct PHYAD addresses.",
    ])
    d.setdefault("default_signal_values_when_omitted",
        "MII / GMII: TX_EN, TX_ER, RX_DV, RX_ER, CRS, COL default to 0 (de-asserted); TXD / RXD default to 0x0. MDIO defaults to logic-1 (pulled up by the PHY's 1.5 kΩ resistor) when no STA driver is active. After BMCR Reset (0.15 = 1) the PHY restores BMCR + BMSR to spec-defined defaults (AutoNeg Enable = 1 if supported, Isolate = 1 if attached via 22.6 connector).")
    d.setdefault("soc_dependent_items", [
        "Whether the MAC + PHY are integrated on the same die (most modern SoCs) or split across an MAC SoC + external PHY chip.",
        "PHY transceiver implementation (analog: differential drivers, hybrid coupler, line equaliser, clock recovery, energy detect).",
        "Choice of MII / GMII / RGMII / RGMII-internal-delay / SGMII / XGMII / XAUI interface (pin count + signal-integrity tradeoff).",
        "MDC source — typically the SoC's MAC controller (sometimes derived by dividing the CPU bus clock down to ≤ 2.5 MHz).",
        "MDIO bus topology — one STA per bus segment; up to 32 PHYs per bus; weak pull-up + pull-down values per Clause 22.4.4.2.",
        "Reset distribution — PHY hardware reset (RESET#) plus AutoNeg restart (BMCR 0.9) plus full BMCR reset (0.15).",
        "Energy Efficient Ethernet (Clause 78) sleep / wake signalling (LPI = Low-Power Idle), present in 100BASE-TX, 1000BASE-T, 10GBASE-T.",
        "Connector + magnetics + ESD-protection design — board-level; not in the protocol spec.",
        "Frame buffering depth (RX FIFO + TX FIFO) inside the MAC for PAUSE / cut-through forwarding.",
        "Interrupt routing for Link Status change, AutoNeg Complete, Remote Fault, jabber, PAUSE-received, FCS-error, excessive-collision events.",
        "DMA descriptor format + scatter-gather support — outside the MAC ↔ PHY boundary.",
    ])
    d.setdefault("low_power_modes", {
        "Active":         "Normal operation; MAC + PHY both running.",
        "Power_Down_BMCR_0_11": "PHY in low-power state; MDIO remains responsive; PHY shall not generate spurious MII / GMII activity. Exit latency ≤ 0.5 s.",
        "Isolate_BMCR_0_10":    "PHY data paths to MII / GMII are high-Z; PHY remains MDIO-addressable.",
        "EEE_LPI_Clause_78":    "Energy Efficient Ethernet Low-Power Idle: PHY signals LPI on the link when MAC has no traffic; transmitter sleep + receiver alert + refresh cycles; not in 802.3-2005 — added in Clause 78.",
    })
    d.setdefault("device_classes_examples", [
        "Standalone PHY chip (e.g. 100BASE-TX or 1000BASE-T transceiver behind MII / GMII / RGMII).",
        "SoC-integrated MAC + PHY (single-die Ethernet controller).",
        "Multi-port Switch ASIC — N MACs + N PHYs + a per-port FIFO + a forwarding engine; each external port is one Ethernet link.",
        "Network Interface Controller (NIC) — MAC + PHY + DMA engine + host bus interface (PCIe).",
        "Industrial-Ethernet PHY (TPS-1 / PROFINET / EtherCAT) — same MAC + RS + MII + MDIO; added IRT scheduling at MAC client.",
        "Automotive Ethernet PHY (100BASE-T1 / 1000BASE-T1) — single-pair full-duplex; same MAC + MII; PMD differs.",
    ])
    _write(p, d)


def _apply_l10(gd: Path) -> None:
    p = gd / "L10_TEST_CASES.json"
    if not p.is_file():
        return
    d = _read(p)
    # Strip runner-emitted opcode_hex / addr_hex / len_hex host-byte test cases
    # — Ethernet frame-class protocols carry no host-byte opcode. Leaving these
    # in trips the parity diff's opcode_hex hallucination heuristic.
    tcs = d.get("test_cases")
    if isinstance(tcs, list) and tcs:
        d["test_cases"] = [tc for tc in tcs
                           if not (isinstance(tc, dict) and
                                   ("opcode_hex" in tc or "addr_hex" in tc
                                    or "len_hex" in tc))]
    d["test_cases_present"] = (
        "partial — IEEE Std 802.3-2005 specifies detailed behavioral and "
        "electrical conformance requirements (CSMA/CD MAC state machine "
        "in Clause 4, MII signal timing in Clause 22, AutoNeg state "
        "machine in Clause 28, PMD electrical compliance per individual "
        "PHY clause) but no concrete testbench. Conformance is determined "
        "by the per-clause PICS (Protocol Implementation Conformance "
        "Statement) proforma and by vendor compliance programs (UNH-IOL, "
        "ANSI / TIA-1096, Auto-Neg Compliance Test).")
    d.setdefault("derived_compliance_test_categories", [
        "MAC: Transmit and receive a 64-byte minimum frame (all-zero payload, smallest legal).",
        "MAC: Transmit and receive a 1518-byte maximum untagged frame.",
        "MAC: Transmit and receive a 1522-byte maximum 802.1Q VLAN-tagged frame (TPID 0x8100).",
        "MAC: Inject one-bit FCS error into a received frame — MAC must discard and increment FCS-error counter.",
        "MAC: Inject a runt (< 64 B) — MAC must discard.",
        "MAC: Inject a giant (> 1518 B / > 1522 B VLAN) — MAC must discard (unless jumbo support is enabled).",
        "MAC: Enforce 96-BT IFG between back-to-back transmits — verify no IFG violation.",
        "MAC TX: Auto-pad short payloads to 46 B and recompute FCS.",
        "MAC RX: Detect SFD nibble (0xD) and byte-align the receive FIFO correctly.",
        "MAC FCS: Verify CRC-32 with polynomial 0x04C11DB7, init 0xFFFFFFFF, final XOR 0xFFFFFFFF on a known-good test vector (e.g. ASCII '123456789' → CRC-32 = 0xCBF43926).",
        "MII: TX_CLK frequency 25 MHz ±100 ppm at 100 Mb/s; 2.5 MHz at 10 Mb/s; duty cycle 35-65 %.",
        "MII: RX_CLK frequency tracking and 35-65 % duty cycle under valid received signal.",
        "MII: TX_EN asserts synchronous with first preamble nibble; de-asserts before next TX_CLK after final FCS nibble.",
        "MII: RX_DV asserts encompassing the frame starting no later than SFD; de-asserts after final FCS nibble.",
        "MII: TX_ER asserted mid-frame → PHY must emit at least one invalid symbol on the medium.",
        "MII: RX_ER asserted mid-frame → MAC discards.",
        "MII: False Carrier — RX_DV = 0, RX_ER = 1, RXD = 0x1110 → MAC increments False Carrier counter; no data delivered.",
        "MII CRS: assert when either TX or RX medium is non-idle; remain asserted throughout a collision condition.",
        "MII COL: assert on half-duplex collision; behaviour undefined in full-duplex.",
        "GMII: GTX_CLK 125 MHz from MAC; RX_CLK 125 MHz from PHY; byte-wide data path verified.",
        "RGMII: DDR sampling on rising AND falling edge; TX_CTL encoding (TX_EN on rising, TX_ERR XOR TX_EN on falling).",
        "CSMA/CD (half-duplex): collision detected → JAM pattern + truncated-binary-exponential backoff up to 16 retries.",
        "CSMA/CD: Late Collision (after 512 BT) — frame aborted; Late Collisions counter incremented; no retry.",
        "Full-duplex: independent simultaneous transmit and receive; CRS / COL ignored.",
        "MDIO C22 Read: PRE(32) + ST(01) + OP(10) + PHYAD(5) + REGAD(5) + TA(Z0) + DATA(16) — PHY drives the 16 data bits MSB first.",
        "MDIO C22 Write: PRE(32) + ST(01) + OP(01) + PHYAD(5) + REGAD(5) + TA(10) + DATA(16) — STA drives the 16 data bits MSB first.",
        "MDIO C45 Address-then-Data: two-cycle protocol; verify address register sticks across the address cycle and is consumed by the subsequent data cycle.",
        "MDIO C45 Post-Increment Read (OP=10): internal address increments after each read.",
        "BMCR Reset (0.15 = 1): self-clearing within 0.5 s; BMCR + BMSR restored to defaults.",
        "BMCR Loopback (0.14 = 1): TX_EN ↑ produces RX_DV ↑ within 512 BT.",
        "BMCR Isolate (0.10 = 1): MII / GMII data signals high-Z; MDIO still responsive.",
        "BMCR Power Down (0.11 = 1): MDIO still responsive; no spurious MII / GMII activity.",
        "BMCR Collision Test (0.7 = 1): TX_EN ↑ → COL asserts within 512 BT.",
        "BMSR Link Status (1.2) latching-low behaviour: stays 0 after link-down event until re-read.",
        "AutoNeg: ANAR ↔ ANLPAR exchange; verify highest common ability selected per priority table (1000-FD > 1000-HD > 100-T2-FD > 100-TX-FD > 100-T2-HD > 100-T4 > 100-TX-HD > 10-FD > 10-HD).",
        "AutoNeg: PAUSE + Asym-PAUSE resolution table.",
        "AutoNeg Parallel Detect: link partner without FLP detected via 10BASE-T NLP or 100BASE-TX scrambled idle; configure to that PMA in half-duplex.",
        "AutoNeg Restart (BMCR 0.9 = 1): self-clearing; FSM returns to AN_ABILITY_DETECT.",
        "AutoNeg Next Page: exchange one or more Next Page messages (for 1000BASE-T MASTER/SLAVE resolution).",
        "PAUSE: receive valid PAUSE frame (DA = 01:80:C2:00:00:01, EtherType 0x8808, opcode 0x0001) → MAC stalls TX for the indicated quanta.",
        "PAUSE: PAUSE with quanta = 0 immediately resumes TX.",
        "PAUSE: invalid PAUSE (wrong opcode / wrong DA) ignored.",
        "VLAN: parse 0x8100 TPID + TCI; deliver PCP + VID to upper layer; transmit max-size 1522 B frame.",
        "EtherType disambiguation: value ≥ 0x0600 → EtherType; value ≤ 0x05DC → IEEE 802.3 Length field.",
        "Broadcast: DA = FF:FF:FF:FF:FF:FF accepted regardless of unicast MAC.",
        "Multicast filter: hash-based or perfect-match destination-address filter (vendor implementation; standard requires only that unicast + broadcast + own-multicast be receivable).",
    ])
    _write(p, d)


def _apply_l11(gd: Path) -> None:
    p = gd / "L11_OTP_CONTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("otp_present", False)
    d.setdefault("otp_equivalent_factory_burned_fields", [
        {"field": "MAC Address (48 bits)",                   "width_bits": 48, "location": "EEPROM / metal-mask / OTP", "note": "Per-device Universally Administered MAC address from the manufacturer's IEEE-assigned OUI; first 24 bits = OUI, last 24 bits = vendor-assigned. The I/G bit (bit 0 of byte 0) must be 0 (Individual), the U/L bit (bit 1 of byte 0) must be 0 (Universally administered)."},
        {"field": "PHY Identifier 1 (Clause 22 reg 2)",      "width_bits": 16, "location": "ROM / metal-mask",          "note": "Bits 3-18 of the manufacturer's 24-bit IEEE-assigned OUI."},
        {"field": "PHY Identifier 2 (Clause 22 reg 3)",      "width_bits": 16, "location": "ROM / metal-mask",          "note": "Bits 19-24 of OUI (6 b) + Model Number (6 b) + Revision Number (4 b). Together regs 2+3 give the full 32-bit PHY ID."},
        {"field": "Capability bits in BMSR (reg 1.15:7)",    "width_bits": 9,  "location": "Hard-wired in PHY logic",  "note": "100BASE-T4 / 100BASE-X HD / 100BASE-X FD / 10BASE-T HD / 10BASE-T FD / 100BASE-T2 HD / 100BASE-T2 FD / Extended Status / Unidirectional Ability — set by the silicon to reflect what this PHY supports."},
        {"field": "Extended Status capability (reg 15)",     "width_bits": 16, "location": "Hard-wired in PHY logic",  "note": "1000BASE-T HD + FD, 1000BASE-X HD + FD, 10GBASE-T, etc. — also strapped to silicon capability."},
        {"field": "AutoNeg default ANAR (reg 4 default)",    "width_bits": 16, "location": "Hard-wired strap or OTP",  "note": "Power-on default for advertised abilities; many PHYs allow strap pins to disable specific abilities at boot."},
        {"field": "PHY Address (PHYAD strap)",               "width_bits": 5,  "location": "Hardware strap pins",       "note": "5-bit PHY Address sampled from board pull-ups / pull-downs at reset; selects which Clause-22 / Clause-45 PHYAD this PHY responds to on the shared MDIO bus."},
    ])
    d["notes"] = (
        "IEEE 802.3-2005 does NOT define OTP / fuse content as a protocol "
        "concept. Practically every Ethernet endpoint must store its "
        "48-bit Universally Administered MAC Address in non-volatile "
        "memory (EEPROM, OTP, or motherboard SPI flash) so the MAC "
        "reports the same address across reboots. PHY-level identity "
        "(PHY ID 1 + PHY ID 2 + BMSR capability bits) is silicon-mask "
        "burned and never changes. PHYAD is typically strapped by "
        "external pull-ups / pull-downs sampled at reset, allowing the "
        "same silicon to occupy any of 32 addresses on a shared MDIO "
        "bus.")
    _write(p, d)


def _apply_l12(gd: Path) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("link_bring_up_sequence", [
        "1. PHY hardware reset (RESET#) or BMCR.Reset (0.15 = 1). PHY clears BMCR + BMSR to defaults; PHYAD is sampled from strap pins.",
        "2. If AutoNeg is enabled (BMCR 0.12 = 1), PHY enters AN_ABILITY_DETECT and starts transmitting Fast Link Pulse bursts encoding ANAR (reg 4) — Base Page advertising local capabilities.",
        "3. PHY receives FLP bursts from the link partner; assembles received Base Page in ANLPAR (reg 5). After three identical Base Pages received with consistent contents, sets the Acknowledge bit.",
        "4. Both sides send Base Pages with Acknowledge set (AN_ACK_DETECT → AN_COMPLETE_ACK).",
        "5. If either side has Next-Page bit set, exchange one or more Next Page messages (used by 1000BASE-T for MASTER/SLAVE resolution).",
        "6. Resolve highest common ability via priority table: 1000-FD > 1000-HD > 100-T2-FD > 100-TX-FD > 100-T2-HD > 100-T4 > 100-TX-HD > 10-FD > 10-HD.",
        "7. PHY transitions to AN_LINK_OK; BMSR bit 1.5 (AutoNeg Complete) set; configure PMA / PMD for negotiated speed + duplex.",
        "8. PMA + PMD acquire bit + symbol + frame lock on the medium; BMSR bit 1.2 (Link Status) set.",
        "9. MAC sees Link Up indication (from PHY status pin or by polling BMSR bit 1.2); enables TX_EN driver and starts emitting frames on the MII / GMII. CRS / COL behaviour follows configured duplex mode.",
    ])
    d.setdefault("tx_frame_sequence_full_duplex", [
        "1. MAC client signals frame-transmit request with a frame buffer.",
        "2. MAC reads buffer; computes CRC-32 over DA + SA + Type/Length + Payload + Pad as it streams.",
        "3. After previous-frame IFG (96 BT) has elapsed, MAC asserts TX_EN synchronously with the first preamble nibble.",
        "4. Drive 7 × 0x55 preamble + 1 × 0xD5 SFD (14 nibbles + 2 nibbles in MII, or 7 + 1 byte in GMII).",
        "5. Drive DA byte 0..5, SA byte 0..5, Type/Length 0..1, payload 0..N, pad 0..M, FCS byte 0..3 onto TXD. CRC-32 engine updates each cycle.",
        "6. De-assert TX_EN before the next TX_CLK after the final FCS nibble.",
        "7. Start IFG counter for the next frame.",
        "8. PHY 4B/5B (or 8B/10B / PAM5 / Manchester / NRZ) encodes the byte stream onto the medium.",
    ])
    d.setdefault("tx_frame_sequence_half_duplex_csma_cd", [
        "1. MAC client signals frame-transmit request.",
        "2. MAC samples CRS. If CRS asserted (medium busy), enter Defer state and wait for CRS de-assertion + IFG.",
        "3. After CRS = 0 for ≥ 96 BT, assert TX_EN; begin preamble..FCS transmission (same as full-duplex step 4-6).",
        "4. While TX_EN asserted, sample COL each cycle.",
        "5. If COL ↑: switch TXD to a 32-bit JAM pattern; complete JAM; de-assert TX_EN.",
        "6. Compute backoff slots = uniform-random(0, 2^min(N,10)) for attempt N; wait that many × 512 BT slot times.",
        "7. Return to step 2 (re-test CRS) unless N = 16 — then abort with Excessive Collisions error.",
        "8. If TX_EN de-asserted normally with no collision, start IFG and return to idle.",
        "9. If COL ↑ after 512 BT into the frame (Late Collision): abort, increment Late Collisions counter, do NOT retry.",
    ])
    d.setdefault("rx_frame_sequence", [
        "1. PHY detects medium activity → asserts CRS (and, on the next valid alignment, asserts RX_DV).",
        "2. RX_DV ↑ synchronous with the first received nibble; preamble nibbles (0x5 0x5 …) shift into the RX shift register.",
        "3. MAC scans for SFD nibble pattern 0xD; on match, arm CRC-32 engine, byte-align the FIFO write pointer.",
        "4. Stream DA byte 0..5 (apply address filter), SA byte 0..5, Type/Length byte 0..1, payload byte 0..N into RX FIFO. CRC engine updates each byte.",
        "5. RX_DV ↓ — PHY signals end-of-frame.",
        "6. Compare last 4 bytes received against recomputed CRC-32. On mismatch, increment FCS-error counter; discard frame.",
        "7. On length out of range (< 64 B or > 1518 B untagged / > 1522 B VLAN), discard as Runt / Giant.",
        "8. If FCS good + length valid + address-filter passed, deliver MAC client data (DA, SA, Type/Length, Payload) to LLC / IP / VLAN.",
    ])
    d.setdefault("mdio_clause22_write_sequence", [
        "1. STA waits MDIO bus idle (≥ 1 MDC cycle high-Z high).",
        "2. STA drives 32 consecutive logic-1 bits on MDIO during 32 MDC cycles (preamble) — may be suppressed if BMSR 1.6 indicates preamble suppression.",
        "3. STA drives ST (01), then OP (01 = write) — 4 MDC cycles.",
        "4. STA drives PHYAD[4:0] MSB first — 5 MDC cycles.",
        "5. STA drives REGAD[4:0] MSB first — 5 MDC cycles.",
        "6. STA drives TA = 10 — 2 MDC cycles.",
        "7. STA drives DATA[15:0] MSB first — 16 MDC cycles. PHY samples on MDC rising.",
        "8. PHY stores DATA into the addressed register; STA returns MDIO to high-Z; bus idle high.",
    ])
    d.setdefault("mdio_clause22_read_sequence", [
        "1. STA waits MDIO bus idle.",
        "2. STA drives 32-bit preamble (or suppresses).",
        "3. STA drives ST (01), OP (10 = read), PHYAD(5), REGAD(5) — 14 MDC cycles.",
        "4. STA tri-states MDIO for the first TA bit; PHY drives MDIO = 0 on the second TA bit.",
        "5. PHY drives DATA[15:0] MSB first — 16 MDC cycles. STA samples on MDC rising.",
        "6. After bit 0, PHY returns MDIO to high-Z; bus idles high.",
    ])
    d.setdefault("mdio_clause45_read_sequence", [
        "1. Address cycle: STA sends PRE(32) + ST(00) + OP(00) + PRTAD(5) + DEVAD(5) + TA(10) + ADDR(16) — STA-driven throughout.",
        "2. PHY records ADDR into the indirect-address register of the selected MMD.",
        "3. Data cycle: STA sends PRE(32) + ST(00) + OP(11) + PRTAD(5) + DEVAD(5).",
        "4. TA bit 1 = STA tri-state; TA bit 2 = PHY drives 0.",
        "5. PHY drives DATA[15:0] MSB first.",
        "6. (Optional post-increment read: subsequent OP=10 cycles auto-increment the internal address).",
    ])
    d.setdefault("pause_frame_sequence", [
        "1. Receive MAC's RX FIFO crosses high-watermark; MAC Control sublayer constructs a PAUSE frame with DA = 01:80:C2:00:00:01, SA = own MAC, EtherType = 0x8808, opcode = 0x0001, pause_quanta = N (1 quantum = 512 BT).",
        "2. PAUSE frame transmitted; partner receive MAC recognises and signals MAC Control.",
        "3. Partner MAC Control stops the MAC's transmit FSM for N × 512 BT, allowing only previously-started frames to complete.",
        "4. When the pause timer expires (or a PAUSE with quanta = 0 arrives), partner resumes transmission.",
        "5. When the original receive FIFO drops below low-watermark, the receive-side MAC may send PAUSE with quanta = 0 to release.",
    ])
    d.setdefault("collision_backoff_sequence_half_duplex", [
        "1. COL asserts while TX_EN is asserted (collision during frame transmission).",
        "2. MAC switches TXD to the 32-bit JAM pattern (any non-preamble pattern; spec recommends all-ones).",
        "3. After JAM, de-assert TX_EN.",
        "4. Increment collision counter N (starting at 1).",
        "5. Compute backoff slots = uniform-random(0, 2^min(N,10)) — i.e. up to 2^N slots for N ≤ 10, capped at 1024 slots thereafter.",
        "6. Wait backoff_slots × 512 BT.",
        "7. Return to TX_DEFER (wait for CRS = 0 + IFG) and retry the frame transmission.",
        "8. If N reaches 16, abort and signal Excessive Collisions.",
    ])
    d.setdefault("auto_negotiation_priority_resolution", [
        "After both sides have completed Base Page (+ optional Next Page) exchange, resolve highest common ability via the canonical priority order (decreasing): 1000BASE-T Full Duplex → 1000BASE-T Half Duplex → 100BASE-T2 Full Duplex → 100BASE-TX Full Duplex → 100BASE-T2 Half Duplex → 100BASE-T4 → 100BASE-TX Half Duplex → 10BASE-T Full Duplex → 10BASE-T Half Duplex.",
        "PAUSE / Asym-PAUSE resolution per Annex 28B Table 28B-3: encode the combination of local + remote PAUSE bits into one of four states (TX_PAUSE on/off, RX_PAUSE on/off).",
        "Once highest common ability is chosen, both ends configure their PMA / PMD accordingly and assert AutoNeg Complete (BMSR bit 1.5).",
    ])
    _write(p, d)


def _apply_l13(gd: Path) -> None:
    p = gd / "L13_LAB_CALIBRATION.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("lab_calibration_present", False)
    d.setdefault("lab_measurement_targets_from_spec", [
        {"name": "MII / GMII output drive (Voh / Vol)",       "purpose": "Verify Clause 22.4.3.1 DC characteristics — Voh ≥ 2.40 V at Ioh = -4 mA; Vol ≤ 0.40 V at Iol = 4 mA."},
        {"name": "MII / GMII input thresholds (Vih / Vil)",   "purpose": "Verify Clause 22.4.4.1 — Vih(min) = 2.00 V; Vil(max) = 0.80 V; receiver behaviour undefined in the switching region."},
        {"name": "TX_CLK / RX_CLK frequency + tolerance",     "purpose": "Measure 25 MHz ±100 ppm at 100 Mb/s, 2.5 MHz at 10 Mb/s, 125 MHz GTX_CLK at 1 Gb/s; verify duty cycle in 35-65 %."},
        {"name": "MII setup / hold timing",                    "purpose": "Verify TXD / TX_EN / TX_ER setup ≥ 10 ns and hold ≥ 0 ns relative to TX_CLK; clock-to-output ≤ 25 ns on RX side."},
        {"name": "MDC / MDIO timing",                          "purpose": "Verify MDC period ≥ 400 ns, high + low ≥ 160 ns; MDIO setup + hold relative to MDC rising edge."},
        {"name": "PHY MDI signaling eye + amplitude",         "purpose": "Per-PMD class eye-diagram + return-loss + far-end NEXT compliance: 10BASE-T (Clause 14), 100BASE-TX (Clause 25), 1000BASE-T (Clause 40 + Annex 40C)."},
        {"name": "AutoNeg FLP pulse spacing + burst timing",  "purpose": "Pulse spacing 62.5 ± 7 µs; burst interval 8-24 ms; verify on twisted pair with a digital oscilloscope before line-coded data signaling begins."},
        {"name": "Frame-level FCS check",                     "purpose": "Inject known test vector (e.g. ASCII '123456789' → CRC-32 0xCBF43926; or a captured Ethernet frame against external utility) and compare RTL CRC engine output."},
        {"name": "Inter-Frame Gap measurement",                "purpose": "On the wire (or on the MII), measure the time between TX_EN ↓ of one frame and TX_EN ↑ of the next; must be ≥ 96 BT for the configured speed."},
        {"name": "Protocol analyzer (Wireshark / Keysight)",   "purpose": "Capture and decode Ethernet frames + VLAN tags + PAUSE frames + AutoNeg pages on the MDI; cross-check against the RTL transmit / receive output."},
    ])
    d["notes"] = (
        "IEEE Std 802.3-2005 does NOT specify on-chip calibration loops. "
        "The MAC + RS + MII subset is purely digital and is verified by "
        "directed and randomized testbench stimulus. The PHY-side analog "
        "(line drivers, hybrids, ADC, DAC, equaliser, clock recovery) "
        "requires per-PMD compliance lab tests (oscilloscope eye-diagram "
        "+ return-loss + NEXT + jitter / wander measurement) per the "
        "relevant clause's PMD specification. Vendor PHYs implement "
        "closed-loop adaptive equalization + impedance trim + amplitude "
        "trim as implementation-defined features outside the protocol "
        "scope.")
    _write(p, d)


def _apply_l14(gd: Path) -> None:
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if not p.is_file():
        return
    d = _read(p)
    f = d.get("fields") or {}
    f.setdefault("spec_version",
        "IEEE Std 802.3-2005 (Section Two: Clauses 21 through 33 + Annex 22A through 32A; with cross-references to Clause 4 MAC, Clause 22 MII, Clause 35 GMII, Clause 45 MDIO/MMD)")
    if _empty(f.get("previous_versions")):
        f["previous_versions"] = [
            "IEEE Std 802.3-1985 (original 10BASE5 Thick Ethernet — DEC + Intel + Xerox 'DIX Ethernet II' commercial precursor 1980)",
            "IEEE Std 802.3a-1988 (10BASE2 Thin Ethernet 'cheapernet')",
            "IEEE Std 802.3i-1990 (10BASE-T over twisted pair — birth of the structured wiring + hub topology)",
            "IEEE Std 802.3u-1995 (Fast Ethernet — 100BASE-T family: 100BASE-TX, 100BASE-T4, 100BASE-FX, introduced MII Clause 22 + AutoNeg Clause 28)",
            "IEEE Std 802.3x-1997 (Full-duplex + PAUSE-frame flow control — MAC Control sublayer Clause 31)",
            "IEEE Std 802.3z-1998 (1000BASE-X gigabit fiber — Clause 36)",
            "IEEE Std 802.3ab-1999 (1000BASE-T gigabit copper over Cat 5e UTP — Clause 40)",
            "IEEE Std 802.3ac-1998 (4-byte VLAN tag — increased max frame size to 1522 B; tags integrated with 802.1Q)",
            "IEEE Std 802.3ad-2000 (Link Aggregation — later moved to IEEE 802.1AX)",
            "IEEE Std 802.3ae-2002 (10 Gigabit Ethernet — 10GBASE-X family + XGMII Clause 46 + Clause 45 MMD addressing)",
            "IEEE Std 802.3-2002 (consolidated revision)",
        ]
    if _empty(f.get("key_changes")):
        f["key_changes"] = [
            {"version": "802.3-2005",
             "summary": "Consolidated revision of the entire base standard up to mid-2005. Includes Clauses 1-74 covering 1 Mb/s, 10 Mb/s, 100 Mb/s, 1 Gb/s, and 10 Gb/s baseband Ethernet, plus all MII / GMII / XGMII / RGMII reconciliation sublayers, Clause 22 + 45 MDIO management, Clause 28 Auto-Negotiation, Clause 31 MAC Control + PAUSE, Clause 36 1000BASE-X, Clause 40 1000BASE-T, and Clause 46-49 10 Gigabit Ethernet."},
        ]
    if _empty(f.get("future_versions_industry_outline")):
        f["future_versions_industry_outline"] = [
            {"version": "IEEE 802.3an-2006 (10GBASE-T)",           "summary": "10 Gb/s over 4-pair Cat 6a / Cat 7 UTP using LDPC + DSQ128 modulation; introduces Clause 55 PHY."},
            {"version": "IEEE 802.3az-2010 (Energy Efficient Ethernet)", "summary": "Adds Low-Power Idle (LPI) signaling for 100BASE-TX, 1000BASE-T, 10GBASE-T — Clause 78."},
            {"version": "IEEE 802.3ba-2010 (40/100 GbE)",          "summary": "Introduces 40 Gb/s and 100 Gb/s over multi-lane fiber (40GBASE-SR4, 100GBASE-LR4, etc.) and Clause 81 XLGMII / CGMII."},
            {"version": "IEEE 802.3bj-2014 (100GBASE-KR4 / CR4)",  "summary": "100 Gb/s over backplane + twinax with FEC."},
            {"version": "IEEE 802.3by-2016 (25 GbE)",              "summary": "Single-lane 25 Gb/s over twinax / fiber."},
            {"version": "IEEE 802.3bs-2017 (200 / 400 GbE)",       "summary": "Multi-lane PAM4 — 200GBASE-FR4, 400GBASE-DR4, etc."},
            {"version": "IEEE 802.3bp-2016 (1000BASE-T1) + 802.3bw (100BASE-T1)", "summary": "Single-pair automotive Ethernet PHYs sharing the same Clause 4 MAC."},
            {"version": "IEEE 802.3ck-2022 (200 GbE per lane)",   "summary": "Higher per-lane PAM4 rates targeting 800 GbE / 1.6 TbE."},
        ]
    if _empty(f.get("backward_compat_traps")):
        f["backward_compat_traps"] = [
            {"trap_name": "AutoNeg_disabled_at_one_end_only",
             "rule":      "AutoNeg is enabled by default on most PHYs; if one end is forced into manual mode (BMCR 0.12 = 0) the AutoNeg partner sees no FLP bursts and falls back to Parallel Detect — which always defaults to HALF DUPLEX.",
             "trap":      "Half-duplex mismatch: one end forced 100/Full, partner Parallel-Detects to 100/Half → very high error rate + late collisions. Symptom: link 'works' but throughput is terrible."},
            {"trap_name": "Speed_downshift_silent",
             "rule":      "AutoNeg resolves to the highest common ability; if the 1000BASE-T cable is degraded the PHY may unilaterally downshift to 100BASE-TX without informing higher layers.",
             "trap":      "User expects 1 Gb/s but link runs at 100 Mb/s; visible only via BMSR + MASTER-SLAVE Status registers."},
            {"trap_name": "C22_vs_C45_MDIO_protocol_mismatch",
             "rule":      "Clause 22 uses ST=01; Clause 45 uses ST=00 and is a two-cycle protocol.",
             "trap":      "A Clause-22 STA addressing a Clause-45 PHY will either read garbage or get no response; many PHYs implement both protocols with a vendor-specific mode bit."},
            {"trap_name": "RGMII_internal_delay_negotiation",
             "rule":      "RGMII at 1 Gb/s requires ~2 ns clock-to-data skew; whether the delay is in the MAC, the PHY, the PCB, or 'RGMII v2.0 internal delay' is per-board.",
             "trap":      "Both ends 'internal-delay-on' or both 'internal-delay-off' → bit errors on TX or RX; symptom is excessive FCS errors only at gigabit, link runs cleanly at 100/10 Mb/s."},
            {"trap_name": "VLAN_tag_silent_drop_at_legacy_switch",
             "rule":      "VLAN tags raise the max frame size to 1522 B; legacy switches with a hard 1518 B MTU silently drop tagged frames.",
             "trap":      "Mixed-vintage networks see VLAN-tagged frames disappear at certain hops; only diagnosable with a protocol analyzer."},
            {"trap_name": "Preamble_suppression_only_when_both_sides_agree",
             "rule":      "Clause 22 PRE may be suppressed only if BMSR bit 1.6 indicates the PHY supports it AND the STA elects to suppress.",
             "trap":      "STA suppresses PRE but PHY does not support it → PHY does not respond → STA times out."},
            {"trap_name": "Full_vs_half_duplex_PAUSE_misuse",
             "rule":      "IEEE 802.3x PAUSE is valid only in full-duplex mode; in half-duplex the multicast PAUSE address is just another broadcast frame.",
             "trap":      "Sending PAUSE in a half-duplex CSMA/CD domain has no effect; the sender assumes the receiver paused but the receiver did not."},
        ]
    f.setdefault("version_naming_history_note",
        "The IEEE 802.3 standard is maintained by the IEEE 802 LAN/MAN Standards Committee. Each amendment is named with a letter suffix (a-z, then aa-zz). Major rev years (1985, 1995, 1998, 2002, 2005, 2008, 2012, 2015, 2018, 2022) consolidate prior amendments into a fresh single document. The MAC frame format (Clause 4) has remained substantially unchanged since the original 1980 DEC-Intel-Xerox 'Ethernet II' commercial spec — only the EtherType / Length disambiguation (≥ 0x0600 = type) and the optional 4-byte VLAN tag have been added.")
    d["fields"] = f
    _write(p, d)


def _apply_l15(gd: Path) -> None:
    p = gd / "L15_ENCODING_TABLES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = d.get("fields") or {}
    f.setdefault("mac_frame_table", {
        "header_columns": ["Field", "Octets", "Value / Meaning"],
        "rows": [
            ["Preamble",                7,                  "0x55 0x55 0x55 0x55 0x55 0x55 0x55 (binary 01010101 × 7)"],
            ["SFD (Start Frame Delim)", 1,                  "0xD5 (binary 11010101)"],
            ["Destination Address",      6,                  "6-octet MAC; bit 0 of byte 0 = I/G (0=Individual, 1=Group); bit 1 = U/L (0=Universal, 1=Local)"],
            ["Source Address",            6,                  "6-octet unicast MAC of the transmitting station"],
            ["EtherType / Length",       2,                  "≥ 0x0600 (1536) = EtherType (Ethernet II framing); ≤ 0x05DC (1500) = LLC Length (IEEE 802.3 framing)"],
            ["Payload",                  "46..1500",        "MAC client data (zero-padded to 46 B if shorter)"],
            ["FCS",                       4,                  "IEEE 802.3 CRC-32 over DA + SA + Type/Length + Payload + Pad; polynomial 0x04C11DB7; init 0xFFFFFFFF; final XOR 0xFFFFFFFF; LSB-first"],
            ["Total (untagged)",          "64..1518",        "Minimum 64 B, maximum 1518 B (excluding preamble + SFD)"],
            ["VLAN tag insertion",        "+4",              "TPID 0x8100 + TCI (PCP[3] + DEI[1] + VID[12]) between SA and EtherType; raises max to 1522 B"],
        ],
    })
    f.setdefault("ethertype_table", {
        "header_columns": ["EtherType (hex)", "Protocol"],
        "rows": [
            ["0x0800", "Internet Protocol version 4 (IPv4)"],
            ["0x0806", "Address Resolution Protocol (ARP)"],
            ["0x8035", "Reverse ARP (RARP)"],
            ["0x8100", "IEEE 802.1Q VLAN-tagged frame"],
            ["0x8137", "IPX / Novell NetWare"],
            ["0x86DD", "Internet Protocol version 6 (IPv6)"],
            ["0x8808", "IEEE 802.3x MAC Control / PAUSE"],
            ["0x8809", "IEEE 802.3ad Slow Protocols (LACP / LAMP / OAM)"],
            ["0x8847", "MPLS unicast"],
            ["0x8848", "MPLS multicast"],
            ["0x8863", "PPPoE Discovery"],
            ["0x8864", "PPPoE Session"],
            ["0x88A8", "IEEE 802.1ad Provider Bridging / Q-in-Q"],
            ["0x88CC", "IEEE 802.1AB Link Layer Discovery Protocol (LLDP)"],
            ["0x88E5", "IEEE 802.1AE MAC Security (MACsec)"],
            ["0x88F7", "IEEE 1588 Precision Time Protocol (PTP)"],
        ],
    })
    f.setdefault("mii_txd_encoding_table", {
        "header_columns": ["TX_EN", "TX_ER", "TXD<3:0>", "Indication"],
        "rows": [
            ["0", "0", "0000-1111", "Normal inter-frame"],
            ["0", "1", "0000-1111", "Reserved"],
            ["1", "0", "0000-1111", "Normal data transmission"],
            ["1", "1", "0000-1111", "Transmit error propagation (PHY must emit an invalid line symbol)"],
        ],
    })
    f.setdefault("mii_rxd_encoding_table", {
        "header_columns": ["RX_DV", "RX_ER", "RXD<3:0>", "Indication"],
        "rows": [
            ["0", "0", "0000-1111",     "Normal inter-frame"],
            ["0", "1", "0000",           "Normal inter-frame"],
            ["0", "1", "0001-1101",     "Reserved"],
            ["0", "1", "1110",           "False Carrier indication"],
            ["0", "1", "1111",           "Reserved"],
            ["1", "0", "0000-1111",     "Normal data reception"],
            ["1", "1", "0000-1111",     "Data reception with errors"],
        ],
    })
    f.setdefault("mdio_c22_frame_table", {
        "header_columns": ["Field", "Width (bits)", "READ value", "WRITE value"],
        "rows": [
            ["PRE",   32, "1 × 32", "1 × 32"],
            ["ST",     2, "01",    "01"],
            ["OP",     2, "10",    "01"],
            ["PHYAD",  5, "AAAAA", "AAAAA"],
            ["REGAD",  5, "RRRRR", "RRRRR"],
            ["TA",     2, "Z0 (high-Z then PHY-0)", "10 (STA-driven)"],
            ["DATA",  16, "DDDDDDDDDDDDDDDD (PHY-driven)", "DDDDDDDDDDDDDDDD (STA-driven)"],
            ["IDLE",  "≥1", "Z (high-Z, pulled high)", "Z (high-Z, pulled high)"],
        ],
    })
    f.setdefault("mdio_c45_frame_table", {
        "header_columns": ["OP value", "Meaning"],
        "rows": [
            ["00", "Address — STA writes 16-bit register address into the addressed MMD's indirect-address register"],
            ["01", "Write — STA writes 16-bit data into the previously-addressed register"],
            ["10", "Post-Increment Read — PHY drives 16-bit data; internal address auto-increments for the next access"],
            ["11", "Read — PHY drives 16-bit data; internal address unchanged"],
        ],
    })
    f.setdefault("clause22_register_summary_table", {
        "header_columns": ["REGAD (decimal)", "Register Name", "Mandatory?"],
        "rows": [
            [0,  "Control (BMCR)",                     "Mandatory"],
            [1,  "Status (BMSR)",                      "Mandatory"],
            [2,  "PHY Identifier 1",                   "Mandatory"],
            [3,  "PHY Identifier 2",                   "Mandatory"],
            [4,  "AutoNeg Advertisement (ANAR)",       "Mandatory if AutoNeg supported"],
            [5,  "AutoNeg Link Partner Ability (ANLPAR)", "Mandatory if AutoNeg supported"],
            [6,  "AutoNeg Expansion (ANER)",           "Mandatory if AutoNeg supported"],
            [7,  "AutoNeg Next Page Transmit (ANNPTR)","Optional"],
            [8,  "AutoNeg LP Received Next Page",      "Optional"],
            [9,  "1000BASE-T Control (MS Control)",    "Mandatory if 1000BASE-T supported"],
            [10, "1000BASE-T Status (MS Status)",      "Mandatory if 1000BASE-T supported"],
            ["11-14", "Reserved",                      "Reserved"],
            [15, "Extended Status",                    "Mandatory if BMSR bit 1.8 = 1"],
            ["16-31", "Vendor-specific",              "Implementation"],
        ],
    })
    f.setdefault("clause45_devad_table", {
        "header_columns": ["DEVAD (decimal)", "MMD Name", "Purpose"],
        "rows": [
            [1,  "PMA/PMD",          "Physical Medium Attachment + Physical Medium Dependent registers"],
            [2,  "WIS",              "WAN Interface Sublayer (10GBASE-W only)"],
            [3,  "PCS",              "Physical Coding Sublayer"],
            [4,  "PHY XS",           "PHY Extender Sublayer (XAUI / XGXS)"],
            [5,  "DTE XS",           "DTE Extender Sublayer"],
            [6,  "TC",               "Transmission Convergence (BASE-T1 / PON)"],
            [7,  "AutoNeg",          "Clause 45 AutoNeg MMD"],
            [13, "EEE",              "Energy Efficient Ethernet (Clause 78)"],
            [29, "C22 access",       "Tunnel for Clause-22 register space through a Clause-45 bus"],
            ["30-31", "Vendor-specific", "Vendor-defined MMDs"],
        ],
    })
    f.setdefault("auto_neg_base_page_table", {
        "header_columns": ["Bit", "Field", "Meaning"],
        "rows": [
            ["15",   "NP",            "Next Page"],
            ["14",   "ACK",           "Acknowledge"],
            ["13",   "RF",            "Remote Fault"],
            ["12",   "reserved",      "Reserved"],
            ["11",   "Asym-PAUSE",    "Asymmetric PAUSE capability"],
            ["10",   "PAUSE",         "Symmetric PAUSE (802.3x flow control)"],
            ["9",    "100BASE-T4",    "PHY supports 100BASE-T4"],
            ["8",    "100BASE-TX FD", "PHY supports 100BASE-TX full duplex"],
            ["7",    "100BASE-TX",    "PHY supports 100BASE-TX (half duplex)"],
            ["6",    "10BASE-T FD",   "PHY supports 10BASE-T full duplex"],
            ["5",    "10BASE-T",      "PHY supports 10BASE-T (half duplex)"],
            ["4:0",  "Selector",      "00001 = IEEE 802.3; other values reserved"],
        ],
    })
    f.setdefault("fcs_polynomial_table", {
        "header_columns": ["Field", "Value"],
        "rows": [
            ["Polynomial",    "x^32 + x^26 + x^23 + x^22 + x^16 + x^12 + x^11 + x^10 + x^8 + x^7 + x^5 + x^4 + x^2 + x + 1"],
            ["Hex",           "0x04C11DB7"],
            ["Reflected hex", "0xEDB88320"],
            ["Initial value", "0xFFFFFFFF"],
            ["Final XOR",     "0xFFFFFFFF"],
            ["Width",         "32 bits"],
            ["Covers",        "DA + SA + Type/Length + Payload + Pad (not Preamble/SFD)"],
        ],
    })
    if _empty(f.get("tables")):
        f["tables"] = [
            "Table 22-1 — Permissible encodings of TXD<3:0>, TX_EN, and TX_ER (MII transmit)",
            "Table 22-2 — Permissible encoding of RXD<3:0>, RX_ER, and RX_DV (MII receive)",
            "Table 22-7 — Control Register (BMCR) bit definitions",
            "Table 22-8 — Status Register (BMSR) bit definitions",
            "Table 22-11 — Auto-Negotiation register bit definitions (ANAR / ANLPAR / ANER)",
            "Table 22-12 — MII Management Frame format (Clause 22 read + write)",
            "Table 22-13 — Input current limits at MII connector",
            "Table 4-1 — MAC frame format (Clause 4)",
            "Table 28-1 — Auto-Negotiation Base Page Selector Field encodings",
            "Table 35-1 — GMII signal names + descriptions",
        ]
    d["fields"] = f
    _write(p, d)


def _apply_l16(gd: Path) -> None:
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = d.get("fields") or {}
    f.setdefault("must_have_properties", [
        "Common MAC frame format: Preamble (7×0x55) + SFD (0xD5) + DA (6 B) + SA (6 B) + EtherType/Length (2 B) + Payload (46-1500 B with zero-pad) + FCS (4 B CRC-32) across all speeds.",
        "Frame Check Sequence: IEEE 802.3 CRC-32 with polynomial 0x04C11DB7, initial 0xFFFFFFFF, final XOR 0xFFFFFFFF, LSB-first bit order, over DA + SA + Type/Length + Payload + Pad (NOT Preamble + SFD + FCS).",
        "Minimum frame length 64 B (excluding preamble + SFD); maximum 1518 B untagged, 1522 B VLAN-tagged.",
        "Inter-Frame Gap of at least 96 bit times between back-to-back transmitted frames.",
        "EtherType disambiguation: value ≥ 0x0600 (1536) = EtherType, value ≤ 0x05DC (1500) = LLC Length.",
        "MAC Address: 48-bit, transmitted MSB-byte-first / LSB-bit-first within each byte; I/G bit (byte 0 bit 0) distinguishes individual vs group; U/L bit (byte 0 bit 1) distinguishes universally vs locally administered.",
        "Broadcast address FF:FF:FF:FF:FF:FF must be received unconditionally.",
        "MII (Clause 22): TXD[3:0] / TX_EN / TX_ER (MAC→PHY) and RXD[3:0] / RX_DV / RX_ER (PHY→MAC), synchronous to TX_CLK / RX_CLK (PHY-sourced).",
        "TX_CLK = 25 MHz at 100 Mb/s (±100 ppm, duty 35-65 %) or 2.5 MHz at 10 Mb/s.",
        "GMII (Clause 35): TXD[7:0] / TX_EN / TX_ER (MAC→PHY) and RXD[7:0] / RX_DV / RX_ER (PHY→MAC); GTX_CLK (MAC-sourced 125 MHz) + RX_CLK (PHY-sourced 125 MHz).",
        "MDIO management bus: MDC (≤ 2.5 MHz, period ≥ 400 ns, high+low ≥ 160 ns) + MDIO (bidirectional three-state with PHY 1.5 kΩ pull-up).",
        "Clause 22 MDIO frame: PRE(32) + ST(01) + OP(10 read / 01 write) + PHYAD(5) + REGAD(5) + TA(Z0 read / 10 write) + DATA(16).",
        "Clause 22 mandatory registers: BMCR (reg 0), BMSR (reg 1), PHY Identifier 1+2 (regs 2+3), ANAR (reg 4) + ANLPAR (reg 5) + ANER (reg 6) if AutoNeg supported.",
        "Clause 45 MDIO frame: PRE(32) + ST(00) + OP(00/01/10/11) + PRTAD(5) + DEVAD(5) + TA + DATA(16), two-cycle (address-then-data) protocol.",
        "Auto-Negotiation Base Page (Clause 28): 16-bit advertisement encoding Selector + Tech Ability + RF + ACK + NP, exchanged via Fast Link Pulse bursts at 8-24 ms intervals.",
        "AutoNeg priority resolution: 1000-FD > 1000-HD > 100-T2-FD > 100-TX-FD > 100-T2-HD > 100-T4 > 100-TX-HD > 10-FD > 10-HD.",
        "Full-duplex operation must disable CSMA/CD and ignore CRS / COL.",
        "Half-duplex CSMA/CD: defer on CRS, transmit, on COL emit 32-bit JAM and back off (truncated-binary-exponential, ≤ 16 retries).",
        "Late Collision (collision after 512 BT): abort frame, increment Late Collisions counter, do NOT retry.",
        "PAUSE frame (Clause 31): valid only in full-duplex; DA = 01:80:C2:00:00:01, EtherType = 0x8808, opcode = 0x0001; 1 pause quantum = 512 BT.",
    ])
    f.setdefault("must_not_have_properties", [
        "Transmitting a frame with Source Address bit 0 = 1 (Group address as source) — not permitted.",
        "Transmitting a frame shorter than 64 B (excluding preamble + SFD) — MAC must zero-pad.",
        "Transmitting more than 1518 B untagged (or 1522 B VLAN-tagged) — unless jumbo support is implementation-defined.",
        "Sending a PAUSE frame in half-duplex mode — the multicast address has no effect.",
        "Running CSMA/CD in full-duplex mode.",
        "Driving the MDIO line during the first TA bit of a read transaction (must be high-Z).",
        "Using ST = 01 for Clause-45 MDIO frames (Clause 45 must use ST = 00).",
        "Treating EtherType / Length values in the reserved range (1501-1535 / 0x05DD-0x05FF) as either EtherType or Length.",
        "Generating spurious MII / GMII activity while BMCR Power Down (0.11 = 1) is set.",
        "Driving MII outputs while BMCR Isolate (0.10 = 1) is set.",
    ])
    f.setdefault("compliance_failure_modes", [
        {"mode": "FCS error",            "trigger": "Received CRC-32 does not match recomputed; frame discarded, FCS-error counter incremented."},
        {"mode": "Alignment error",      "trigger": "RX_DV de-asserts on a non-octet boundary."},
        {"mode": "Runt frame",            "trigger": "Frame length (excluding preamble + SFD) < 64 B."},
        {"mode": "Giant frame",           "trigger": "Frame length > 1518 B untagged or > 1522 B VLAN-tagged (and jumbo support not enabled)."},
        {"mode": "False Carrier",         "trigger": "PHY asserts RX_ER with RX_DV de-asserted and RXD = 0x1110; line activity that is not a valid frame."},
        {"mode": "Collision",             "trigger": "(half-duplex) PHY asserts COL while MAC is transmitting; backoff + retry."},
        {"mode": "Late Collision",        "trigger": "(half-duplex) COL asserts after 512 BT; frame aborted, no retry."},
        {"mode": "Excessive Collisions",  "trigger": "(half-duplex) 16 consecutive collision retries; frame discarded."},
        {"mode": "Carrier Sense Lost",    "trigger": "(half-duplex) CRS de-asserts mid-transmission unexpectedly."},
        {"mode": "Jabber",                "trigger": "(10BASE-T) transmission longer than 25-150 ms; BMSR bit 1.1 latches high."},
        {"mode": "Remote Fault",          "trigger": "Link partner signals fault (e.g. 100BASE-X far-end fault); BMSR bit 1.4 latches high."},
        {"mode": "Parallel Detection Fault","trigger": "AutoNeg parallel-detect logic finds inconsistent abilities; ANER bit set."},
        {"mode": "RX_ER coding error",   "trigger": "PHY signals coding error mid-frame via RX_ER assertion."},
    ])
    f.setdefault("min_link_constraint",
        "Every PHY shall be able to bring up its link at least at one of the supported PMD speeds (10 / 100 / 1000 Mb/s) in either half- or full-duplex. AutoNeg-capable PHYs shall always reach AN_LINK_OK within the spec's break_link_timer when at least one PMD is in common with the partner.")
    f.setdefault("reset_behavior_compliance",
        "BMCR bit 0.15 (Reset) is self-clearing; reset must complete within 0.5 s. After reset, all read-write bits in BMCR + BMSR + ANAR + ANER return to their spec-defined defaults; vendor-specific registers are unspecified. PHY hardware reset (RESET#) has the same effect as BMCR Reset.")
    f.setdefault("frame_boundary_compliance",
        "TX_EN must assert synchronous with the first preamble nibble and remain asserted continuously through all nibbles of the frame; must de-assert before the next TX_CLK rising edge after the final FCS nibble. RX_DV must encompass the frame starting no later than the SFD and de-assert before the next RX_CLK after the final FCS nibble.")
    f.setdefault("address_filter_compliance",
        "Receive MAC must accept (a) its own unicast MAC, (b) the broadcast address FF:FF:FF:FF:FF:FF, (c) any multicast address it has been programmed to listen for, and (d) all frames in promiscuous mode (when enabled). Hash-based filtering of the multicast superset is implementation-defined.")
    d["fields"] = f
    _write(p, d)


def _apply_l17(gd: Path) -> None:
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if not p.is_file():
        return
    d = _read(p)
    f = d.get("fields") or {}
    f["channels"] = [
        {"name": "TX_CLK",   "interface": "MII",   "direction": "PHY → MAC",  "purpose": "Transmit-side clock reference. 25 MHz at 100 Mb/s, 2.5 MHz at 10 Mb/s. Duty cycle 35-65 %, tolerance ±100 ppm.", "active_levels": "LVTTL/LVCMOS — Voh ≥ 2.40 V, Vol ≤ 0.40 V", "idle_level": "Always running"},
        {"name": "TXD[3:0]", "interface": "MII",   "direction": "MAC → PHY",  "purpose": "Nibble-wide transmit data. TXD[0] is LSB. Synchronous to TX_CLK.",            "active_levels": "LVTTL/LVCMOS",                                "idle_level": "Don't-care (TX_EN = 0)"},
        {"name": "TX_EN",    "interface": "MII",   "direction": "MAC → PHY",  "purpose": "Transmit Enable. Asserted with first preamble nibble; de-asserted after final FCS nibble.", "active_levels": "Active HIGH",                                                  "idle_level": "0"},
        {"name": "TX_ER",    "interface": "MII",   "direction": "MAC → PHY",  "purpose": "Transmit coding-error indication; PHY emits at least one invalid symbol when asserted with TX_EN.", "active_levels": "Active HIGH",                            "idle_level": "0"},
        {"name": "RX_CLK",   "interface": "MII",   "direction": "PHY → MAC",  "purpose": "Receive-side clock recovered from RX data (or nominal when no signal). 25 MHz at 100 Mb/s, 2.5 MHz at 10 Mb/s; 35-65 % duty.", "active_levels": "LVTTL/LVCMOS", "idle_level": "Running on nominal clock if recovered clock unavailable"},
        {"name": "RXD[3:0]", "interface": "MII",   "direction": "PHY → MAC",  "purpose": "Nibble-wide receive data. RXD[0] is LSB. Synchronous to RX_CLK.",                "active_levels": "LVTTL/LVCMOS",                                "idle_level": "Don't-care (RX_DV = 0)"},
        {"name": "RX_DV",    "interface": "MII",   "direction": "PHY → MAC",  "purpose": "Receive Data Valid. Encompasses the frame from first preamble nibble through final FCS nibble.", "active_levels": "Active HIGH",                                       "idle_level": "0"},
        {"name": "RX_ER",    "interface": "MII",   "direction": "PHY → MAC",  "purpose": "Receive coding error. Asserted by PHY to flag invalid line symbols in the current frame. Also used (with RXD = 1110, RX_DV = 0) to signal False Carrier.", "active_levels": "Active HIGH", "idle_level": "0"},
        {"name": "CRS",      "interface": "MII",   "direction": "PHY → MAC",  "purpose": "Carrier Sense. Asserted whenever TX or RX medium is non-idle; held throughout a collision condition. Half-duplex only (ignored in full-duplex).", "active_levels": "Active HIGH", "idle_level": "0"},
        {"name": "COL",      "interface": "MII",   "direction": "PHY → MAC",  "purpose": "Collision Detect. Asserted on half-duplex collision; behaviour undefined in full-duplex.",     "active_levels": "Active HIGH", "idle_level": "0"},
        {"name": "GTX_CLK",  "interface": "GMII",  "direction": "MAC → PHY",  "purpose": "Gigabit transmit clock — 125 MHz, sourced by MAC. Used at 1 Gb/s; replaces TX_CLK direction.",     "active_levels": "LVCMOS / HSTL", "idle_level": "Always running"},
        {"name": "TXD[7:0]", "interface": "GMII",  "direction": "MAC → PHY",  "purpose": "Byte-wide transmit data at 1 Gb/s.",                                                              "active_levels": "LVCMOS / HSTL", "idle_level": "Don't-care"},
        {"name": "RXD[7:0]", "interface": "GMII",  "direction": "PHY → MAC",  "purpose": "Byte-wide receive data at 1 Gb/s.",                                                                "active_levels": "LVCMOS / HSTL", "idle_level": "Don't-care"},
        {"name": "RGMII", "interface": "RGMII", "direction": "MAC ↔ PHY", "purpose": "Reduced-pin GMII — DDR data path at 125 MHz; 12 wires total (vs GMII's 24).", "active_levels": "LVCMOS / HSTL", "idle_level": "Per RGMII spec"},
        {"name": "MDC",      "interface": "MDIO management", "direction": "STA → PHY", "purpose": "Management Data Clock; ≤ 2.5 MHz; aperiodic; period ≥ 400 ns; H + L ≥ 160 ns each.",       "active_levels": "LVTTL/LVCMOS",   "idle_level": "Running"},
        {"name": "MDIO",     "interface": "MDIO management", "direction": "STA ↔ PHY (bidirectional, three-state)", "purpose": "Serial management data. 1.5 kΩ pull-up at PHY; 2 kΩ pull-down at STA (per Clause 22.4.4.2).", "active_levels": "LVTTL/LVCMOS, three-state", "idle_level": "Logic-1 (pulled high)"},
        {"name": "MDI pair(s)", "interface": "PHY ↔ medium", "direction": "Bidirectional (full-duplex) or half-duplex shared", "purpose": "Line-coded signal to the network medium per PMD class (Manchester / MLT-3 / NRZI / PAM5 / 8B/10B-NRZ / PAM4).", "active_levels": "PMD-specific differential", "idle_level": "Continuous idle symbols (e.g. /I/ for 100BASE-X)"},
    ]
    f["logical_signaling_levels"] = [
        {"name": "Active TX nibble / byte stream", "meaning": "TX_EN asserted; TXD carrying preamble / SFD / DA / SA / Type/Length / Payload / Pad / FCS data."},
        {"name": "Active RX nibble / byte stream", "meaning": "RX_DV asserted; RXD carrying the received frame."},
        {"name": "Inter-Frame Gap (IFG)",         "meaning": "TX_EN = 0 and (optionally) RX_DV = 0 for ≥ 96 BT; required between back-to-back frames."},
        {"name": "False Carrier",                  "meaning": "RX_DV = 0, RX_ER = 1, RXD = 0x1110 — PHY detected line activity that is not a valid frame."},
        {"name": "Carrier Sense (half-duplex)",   "meaning": "CRS = 1 whenever the medium is non-idle."},
        {"name": "Collision (half-duplex)",       "meaning": "COL = 1 while medium is being driven by another station simultaneously."},
        {"name": "Electrical Idle (MDIO)",        "meaning": "MDIO line at logic-1 (PHY pull-up), no STA driver active."},
        {"name": "AutoNeg FLP burst",             "meaning": "Sequence of 17-33 link pulses on the twisted pair encoding the 16-bit Base Page; transmitted before line-coded data signaling begins."},
    ]
    f["packet_types_summary"] = [
        {"class": "MAC frame", "members": ["Untagged data", "VLAN-tagged data (TPID 0x8100)", "PAUSE (0x8808)", "Slow Protocols (0x8809 / LACP)", "LLDP (0x88CC)", "MACsec (0x88E5)", "PTP (0x88F7)", "ARP (0x0806)", "IPv4 (0x0800)", "IPv6 (0x86DD)"], "count": "10+ canonical EtherTypes; full IEEE EtherType registry has hundreds"},
        {"class": "MDIO frame", "members": ["C22 Read", "C22 Write", "C45 Address", "C45 Write", "C45 Read", "C45 Post-Increment Read"], "count": 6},
        {"class": "AutoNeg",    "members": ["Base Page (16 b)", "Message Page", "Unformatted Next Page"],     "count": 3},
    ]
    f["channel_counts"] = {
        "MII_wires_per_direction":  10,
        "MII_data_wires_per_direction": 4,
        "GMII_wires_per_direction": 12,
        "GMII_data_wires_per_direction": 8,
        "RGMII_total_wires": 12,
        "MDIO_wires_per_bus": 2,
        "phys_per_mdio_bus_max": 32,
        "registers_per_phy_clause22": 32,
        "register_width_bits": 16,
        "mac_address_octets": 6,
        "ethertype_width_octets": 2,
        "fcs_width_octets": 4,
    }
    f["global_signals"] = [
        {"name": "RESET#",   "purpose": "PHY hardware reset (active LOW); equivalent to BMCR bit 0.15."},
        {"name": "INT#",     "purpose": "Optional open-drain interrupt — Link Status change, AutoNeg Complete, Remote Fault, etc."},
        {"name": "MDC",      "purpose": "Shared management clock for all PHYs on the MDIO bus."},
        {"name": "MDIO",     "purpose": "Shared management data line (bidirectional, three-state)."},
        {"name": "VDD/GND",  "purpose": "Power. Clause 22.5: 5 V ±5 % @ ≤ 750 mA; modern silicon uses 3.3 / 2.5 / 1.8 V I/O."},
    ]
    f["dependency_graph"] = {
        "common_rule": "TX path (MII / GMII) is synchronous to TX_CLK or GTX_CLK; RX path is synchronous to RX_CLK; MDC is asynchronous to both. The MAC owns frame assembly + CRC; the PHY owns line coding + clock recovery. MII / GMII do not by themselves contain encoding — the PHY adds 4B/5B / MLT-3 / 8B/10B / PAM5 on the MDI side.",
        "data_dependency": "Frame transmission requires: (1) BMSR Link Status (1.2) = 1, (2) AutoNeg Complete (1.5) = 1 if AutoNeg was enabled, (3) for half-duplex: CRS = 0 for ≥ 96 BT. Frame reception requires: (1) RX_DV ↑ with PHY-detected line activity, (2) byte-aligned SFD detection, (3) full FCS-32 validation after RX_DV ↓.",
    }
    f["handshake_pairs"] = [
        {"name": "TX_EN ↔ TX_CLK",   "from": "MAC", "to": "PHY",  "rule": "TX_EN transitions synchronous to TX_CLK; PHY samples TXD on each TX_CLK rising edge."},
        {"name": "RX_DV ↔ RX_CLK",   "from": "PHY", "to": "MAC",  "rule": "RX_DV transitions synchronous to RX_CLK; MAC samples RXD on each RX_CLK rising edge."},
        {"name": "CRS / COL ↔ MAC FSM", "from": "PHY", "to": "MAC", "rule": "Asynchronous indications (need not align to TX_CLK / RX_CLK)."},
        {"name": "MDIO read TA",      "from": "PHY", "to": "STA",  "rule": "On a read, STA tri-states first TA bit; PHY drives second TA bit to 0; PHY then drives 16 data bits MSB-first."},
        {"name": "MDIO write TA",     "from": "STA", "to": "PHY",  "rule": "On a write, STA drives 10 during TA, then 16 data bits MSB-first."},
        {"name": "AutoNeg FLP exchange", "from": "either", "to": "either", "rule": "Each side transmits FLP bursts encoding its Base Page; convergence = three identical Base Pages received with Acknowledge set."},
        {"name": "PAUSE frame",      "from": "either", "to": "either", "rule": "Receiver-overflow → send PAUSE with quanta = N; partner stalls TX for N × 512 BT (full-duplex only)."},
    ]
    f.setdefault("ordering_rules", {
        "bit_order_within_byte":     "LSB-first on the MII / GMII wire — first bit transmitted is bit 0 of the octet, except FCS which is processed LSB-first by the CRC engine then appended as 4 octets MSB-byte-first.",
        "byte_order_within_field":   "Network byte order (MSB-first / big-endian) for multi-byte protocol fields such as DA, SA, EtherType, VLAN TCI, IPv4 header.",
        "frame_boundary":            "TX_EN edges define frame boundaries on the MII; the PHY emits PMD-specific start-of-stream + end-of-stream delimiters on the MDI (e.g. /J/K/ start + /T/R/ end for 100BASE-X).",
        "mdio_bit_order":            "MSB-first for PHYAD, REGAD, DATA — first bit on the wire is the MSB.",
    })
    d["fields"] = f
    _write(p, d)


def _apply_l18(gd: Path) -> None:
    p = gd / "L18_INTERCONNECT_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = d.get("fields") or {}
    f["topology_type"] = (
        "Two distinct topology families coexist in the IEEE 802.3 standard: "
        "(a) the modern switched point-to-point full-duplex star (one MAC "
        "per switch port, one PHY per MAC, every link its own collision-"
        "free domain) and (b) the legacy shared-medium half-duplex CSMA/CD "
        "bus / repeater-hub topology (multiple stations share a collision "
        "domain, contend via Carrier Sense + Multiple Access + Collision "
        "Detect with truncated-binary-exponential backoff). On the MAC↔PHY "
        "boundary itself every link is point-to-point: one MAC ↔ one PHY "
        "via MII / GMII / RGMII / XGMII, plus a shared MDIO bus carrying "
        "up to 32 PHYs to one Station Management Entity.")
    f["supported_topologies"] = [
        {"name": "Switched full-duplex star",     "description": "Each station is connected to a switch via a dedicated full-duplex link. No CSMA/CD. PAUSE-frame flow control. This is the dominant modern topology (>99 % of installed Ethernet links)."},
        {"name": "Half-duplex repeater hub",      "description": "(Legacy) Multiple stations share one collision domain through a Clause 27 repeater. CSMA/CD with truncated-binary-exponential backoff. Spec-compliant but no longer deployed."},
        {"name": "Direct DTE↔DTE",                "description": "Two stations connected directly via a cross-over cable or auto-MDIX PHY. Full-duplex with AutoNeg."},
        {"name": "Aggregated link (LACP, 802.1AX)","description": "Multiple parallel point-to-point Ethernet links treated as one logical channel; load-balanced and failed-over per IEEE 802.1AX (originally IEEE 802.3ad)."},
        {"name": "Cascaded switches",              "description": "Tree of switches and aggregation switches; spanning-tree (IEEE 802.1D / 802.1w / 802.1s) prevents loops."},
        {"name": "Shared MDIO management bus",    "description": "Up to 32 PHYs on one MDC + MDIO bus driven by a single STA; each PHY at a distinct PHYAD strapped at reset."},
    ]
    f["master_slave_role_summary"] = [
        {"role": "MAC (DTE)",                "description": "Initiates frame transmits (subject to CSMA/CD if half-duplex), recognises incoming frames, owns CRC-32 computation + verification."},
        {"role": "PHY",                       "description": "Line-codes the MII / GMII byte stream onto the medium (and decodes incoming); responds to BMCR Reset / Loopback / Power Down / Isolate; sources TX_CLK + RX_CLK (MII) or RX_CLK (GMII); responds to MDC + MDIO management transactions."},
        {"role": "Station Management Entity (STA)","description": "Master of the MDIO bus; initiates all C22 / C45 read / write transactions; configures + monitors PHYs."},
        {"role": "Reconciliation Sublayer (RS)","description": "Adaptation layer that maps the speed-agnostic MAC service primitives to the speed-specific MII / GMII signals."},
        {"role": "1000BASE-T MASTER / SLAVE (Clause 40)","description": "1000BASE-T link partners select MASTER (sources symbol clock) and SLAVE (recovers it) either by manual setting (reg 9) or by AutoNeg Next Page exchange."},
    ]
    f["interconnect_role"] = (
        "The MII / GMII / RGMII are purely point-to-point MAC↔PHY "
        "interfaces; no fan-out is permitted. The MDIO management bus is "
        "a shared multi-drop bus with one STA master and up to 32 PHY "
        "slaves addressed by the 5-bit PHYAD. The MDI (medium) topology "
        "is governed by the PMD class — twisted pair is always point-"
        "to-point (full-duplex) in modern installations; fiber is always "
        "point-to-point; coax was the original shared-bus medium (10BASE2 "
        "/ 10BASE5) but is no longer deployed.")
    f["ordering_guarantees"] = {
        "in_link_ordering":      "MAC delivers received frames to the upper layer in the order they were received from the PHY; no re-ordering at the MAC.",
        "vlan_priority":          "802.1Q PCP[2:0] carries 8 traffic classes; switches may apply per-PCP queues + scheduling — at the MAC the PCP is just data.",
        "pause_flow_control":     "PAUSE applies to all traffic equally on a link (Clause 31); per-class PFC (priority-based flow control) is a separate IEEE 802.1Qbb extension above the base 802.3.",
        "broadcast_delivery":     "Broadcast and multicast frames are delivered to every station in the broadcast / multicast domain; switches replicate at egress ports.",
    }
    f.setdefault("memory_vs_peripheral_regions",
        "There is no MAC-layer address-space split. Each PHY exposes a 16-bit-wide register file (32 entries for Clause 22, 32 MMDs × 65536 entries for Clause 45) accessed via the MDIO bus. PHY identity (PHY ID 1 + PHY ID 2) is silicon-mask burned. Per-device 48-bit MAC Address is typically stored in board-level EEPROM and loaded into the MAC by firmware at boot; it is NOT in the PHY's register file.")
    f.setdefault("device_classification", {
        "DTE":             "Data Terminal Equipment — endpoint host (PC, server, IP camera, IoT device).",
        "DCE":             "Data Circuit-terminating Equipment — switch port, router port, repeater port.",
        "PHY":             "Single-port PHY transceiver; one MII / GMII / RGMII data path + one MDI port + management bus interface.",
        "Multi-port_PHY":  "N MII / GMII ports on one chip with internal switch fabric.",
        "Switch_ASIC":     "Many ports + forwarding engine; one MAC + PHY pair per port; STA bus drives all PHYs.",
        "NIC":             "Network Interface Controller — MAC + PHY + DMA engine + host bus interface (PCIe).",
    })
    f.setdefault("default_signal_values_evidence_tables", [
        "Figure 21-1 — Architectural positioning of 100BASE-T (Section Two, Clause 21)",
        "Figure 22-1 — MII relationship to the OSI reference model and IEEE 802.3 CSMA/CD LAN model",
        "Figure 22-2 — MII signal interface diagram",
        "Figure 22-10 — MII frame format",
        "Figure 22-13 — Behaviour of MDIO during TA field of a read transaction",
        "Table 22-12 — Management frame format (Clause 22)",
        "Figure 28-1 — Auto-Negotiation reference diagram (Clause 28)",
        "Figure 35-1 — GMII reference diagram (Clause 35)",
        "Figure 4-1 — MAC frame format (Clause 4)",
    ])
    d["fields"] = f
    _write(p, d)


def _apply_l21(gd: Path) -> None:
    p = gd / "L21_POWER_INTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    f = d.get("fields") or {}
    f["power_intent_present"] = True
    f.setdefault("link_power_management_states", [
        {"state": "Active",                  "description": "MAC + PHY both running; AutoNeg complete; link up; normal frame TX + RX in progress.", "exit_latency_estimate": "n/a (already active)"},
        {"state": "Power_Down_BMCR_0_11",   "description": "PHY in low-power state. MDIO bus remains responsive (PHY still answers C22 / C45 register accesses). PHY shall NOT generate spurious MII / GMII activity. RX_CLK / TX_CLK signal-quality requirements are relaxed.", "exit_latency_estimate": "≤ 0.5 s after both BMCR 0.11 and 0.10 are cleared"},
        {"state": "Isolate_BMCR_0_10",      "description": "PHY data paths to MII / GMII are high-Z (TX_CLK, RX_CLK, RX_DV, RX_ER, RXD, COL, CRS); PHY ignores TXD / TX_EN / TX_ER / GTX_CLK; MDIO still responsive. Used for multi-PHY hot-insertion and board test.", "exit_latency_estimate": "≤ 0.5 s after BMCR 0.10 cleared"},
        {"state": "Reset_BMCR_0_15",        "description": "PHY reset in progress; BMCR + BMSR restored to defaults; PHY is unresponsive to writes other than 0.15 itself. Self-clearing.", "exit_latency_estimate": "≤ 0.5 s from setting bit 0.15"},
        {"state": "EEE_LPI (Clause 78, post-2005)", "description": "Energy Efficient Ethernet Low-Power Idle. When MAC has no traffic, PHY transmits LPI symbols (refresh + sleep + quiet); receiver wakes on a refresh tone. Reduces PHY analog power during idle periods.", "exit_latency_estimate": "10-20 µs (TX_LPI_WAKE_TIMER) for 100BASE-TX; longer for 1000BASE-T (16.5 µs); much longer for 10GBASE-T (~5 µs typical + alignment)"},
    ])
    f["low_power_modes_summary"] = {
        "Active":              "Full operational power.",
        "Power_Down":          "PHY analog OFF (mostly); MDIO responsive; ≤ 0.5 s exit.",
        "Isolate":             "MII / GMII drivers high-Z; PHY still consumes baseline + analog standby; MDIO responsive.",
        "EEE_LPI":             "(Post-2005) Per-direction LPI signaling; PHY analog enters low-power; quick wake on traffic-pending.",
    }
    f.setdefault("device_states_d0_d3_analog", [
        {"state": "PHY operational", "description": "BMCR.Power Down = 0 and Isolate = 0. PHY analog + digital fully on. Equivalent to ACPI D0."},
        {"state": "PHY isolate",    "description": "BMCR.Isolate = 1. Equivalent to D2 — PHY logic on, MII drivers off."},
        {"state": "PHY power-down", "description": "BMCR.Power Down = 1. Most PHY analog gated off. MDIO responsive. Equivalent to D3hot."},
        {"state": "PHY hardware reset","description": "RESET# asserted. All PHY logic in reset. Equivalent to D3cold."},
    ])
    f.setdefault("auxiliary_power_for_wake_on_lan", {
        "Vaux_support":    "Implementation-defined. Many PHYs accept a separate Vaux rail so they can stay alive in D3cold and emit a Magic Packet wake-up event to the host (Wake-on-LAN).",
        "Vaux_usage_hint": "Required for any deployment that must wake the system on receipt of a designated frame (Magic Packet) while main power is off.",
    })
    f.setdefault("pause_flow_control_summary", {
        "PAUSE_quantum_BT":    512,
        "max_pause_quanta":  65535,
        "PAUSE_direction":   "Per-direction (one or both); IEEE 802.3x specifies symmetric PAUSE only; Asymmetric PAUSE (PFC) requires negotiation per Annex 28B.",
    })
    f["notes"] = (
        "IEEE Std 802.3-2005 specifies a minimal but mandatory power-"
        "management surface in BMCR (Reset / Loopback / Power Down / "
        "Isolate). Energy Efficient Ethernet (Clause 78, added in IEEE "
        "802.3az-2010) extended this with the LPI signalling that lets "
        "the PHY analog enter a deeper sleep when the MAC has no "
        "traffic, and Clause 22 + 45 management registers were extended "
        "to control + observe the EEE state machine. Wake-on-LAN is an "
        "industry feature not part of the IEEE 802.3 standard but widely "
        "supported across NICs and integrated PHYs.")
    d["fields"] = f
    _write(p, d)


def _apply_l19(gd: Path) -> None:
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if not p.is_file():
        return
    d = _read(p)
    f = d.get("fields") or {}
    f["constraints_present"] = False
    f.setdefault("electrical_channel_constraints", {
        "mii_signal_logic_family": "LVTTL (Clause 22 era); modern integrations use 3.3 V / 2.5 V / 1.8 V LVCMOS",
        "mii_Voh_min_V": 2.4,
        "mii_Vol_max_V": 0.4,
        "mii_Ioh_drive_mA": -4.0,
        "mii_Iol_drive_mA": 4.0,
        "mii_Vih_min_V": 2.0,
        "mii_Vil_max_V": 0.8,
        "mii_supply_V_nominal": 5.0,
        "mii_supply_V_tolerance_percent": 5,
        "mii_load_current_max_per_PHY_mA": 750,
        "mii_input_capacitance_max_pF": 8,
        "mdio_input_capacitance_max_pF": 10,
        "mdio_phy_pullup_kohm": 1.5,
        "mdio_sta_pulldown_kohm": 2.0,
        "mii_cable_zo_ohm_singleended": 68,
        "mii_cable_zo_tolerance_percent": 10,
        "mii_cable_max_prop_delay_ns": 2.5,
        "mii_cable_delay_variation_max_ns": 0.1,
        "mii_cable_dc_resistance_max_mohm": 150,
        "mii_cable_AWG": 28,
        "mdc_max_freq_MHz": 2.5,
        "mdc_min_period_ns": 400,
        "mdc_min_high_low_ns": 160,
        "mii_setup_time_ns_min": 10,
        "mii_hold_time_ns_min": 0,
        "rgmii_ck_data_skew_ns_min": -0.5,
        "rgmii_ck_data_skew_ns_max": 0.5,
        "rgmii_internal_delay_ns_typical": 1.0,
        "rgmii_internal_delay_tolerance_ns": 0.5,
        "esd_recommended": "≥ Class 2 (2 kV HBM) per industry practice; IEEE Std 802.3-2005 does not specify ESD class at the MII / GMII pins",
    })
    f["notes"] = (
        "IEEE Std 802.3-2005 specifies MII / GMII / MDIO signal logic levels, "
        "drive strengths, capacitive load limits, and cable characteristics in "
        "Clause 22.4 (DC + AC characteristics, input current limits, receiver "
        "thresholds) and Clause 35.4 (for GMII), but it does NOT impose any "
        "PDK-specific SDC / floorplan / placement constraints. The MAC + RS + "
        "MII modules are pure synchronous digital logic and integrate cleanly "
        "into any process node with standard 0/1.8/2.5/3.3 V LVCMOS pads. "
        "Per-PMD electrical specifications (PHY MDI eye, return loss, NEXT, "
        "ELFEXT, AC coupling, transformer characteristics) live in the "
        "relevant PMD clause (Clause 14 for 10BASE-T, Clause 25 for "
        "100BASE-TX, Clause 40 for 1000BASE-T, etc.), not in the MAC + RS + "
        "MII subset. RGMII (industry de-facto) requires careful clock-to-data "
        "skew matching at gigabit — the well-known 'RGMII internal delay' "
        "option (~2 ns clock + data delay) lets either the MAC or the PHY add "
        "the skew so the other end sees timing-aligned signals.")
    d["fields"] = f
    _write(p, d)


def _apply_l20(gd: Path) -> None:
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = d.get("fields") or {}
    f["dft_present"] = "partial"
    f.setdefault("in_band_test_facilities", [
        {"name": "BMCR.Loopback (bit 0.14)",              "purpose": "PHY internal loopback — MII / GMII TX path → MII / GMII RX path; receive circuit isolated from medium. TX_EN ↑ must cause RX_DV ↑ within 512 BT."},
        {"name": "BMCR.Isolate (bit 0.10)",               "purpose": "Force MII / GMII data outputs to high-Z for multi-PHY board test and hot-insertion staging; MDIO remains responsive."},
        {"name": "BMCR.Power Down (bit 0.11)",            "purpose": "Low-power state; MDIO still responsive; PHY shall not generate spurious MII / GMII activity."},
        {"name": "BMCR.Collision Test (bit 0.7)",         "purpose": "Half-duplex COL signal exerciser — PHY asserts COL within 512 BT of TX_EN assertion."},
        {"name": "BMCR.Restart Auto-Negotiation (0.9)",   "purpose": "Force AutoNeg state machine restart to verify re-training behaviour."},
        {"name": "BMSR latching bits (1.4 RF / 1.2 Link / 1.1 Jabber)", "purpose": "Latching-status bits allow software to capture transient events and clear them by reading the register."},
        {"name": "1000BASE-T Test Mode bits (reg 9.15:13)","purpose": "Distortion / jitter / waveform / wander production-test modes per Clause 40 Annex 40C."},
        {"name": "Compliance test patterns (PMD-specific)","purpose": "Each PMD clause defines its own scrambled-idle / continuous-IDLE / repeated-symbol test pattern."},
        {"name": "MDIO loopback / SCAN tunnel",           "purpose": "Vendor-specific MMD lets ATE drive scan chains through the MDIO bus."},
    ])
    f.setdefault("internal_diagnostics_observability", [
        "BMSR Link Status (1.2) — latching-low, sticky until cleared by re-read.",
        "BMSR AutoNeg Complete (1.5) — set once AutoNeg has fully resolved.",
        "BMSR Remote Fault (1.4) — latching-high.",
        "BMSR Jabber Detect (1.1) — latching-high (10BASE-T only).",
        "ANER (reg 6) — AutoNeg expansion: LP AutoNeg Able, Page Received (latching), Next Page Able, LP Next Page Able, Parallel Detection Fault (latching).",
        "MS Status (reg 10) — 1000BASE-T MASTER/SLAVE configuration, fault, local + remote receiver status, idle error count.",
        "Per-MAC counters (vendor-implemented): FCS errors, alignment errors, runts, giants, false carriers, single collisions, multiple collisions, late collisions, excessive collisions, deferred transmissions, octets sent / received, broadcast / multicast frames sent / received.",
        "MII signals at the connector (TX_EN / TX_ER / RX_DV / RX_ER / CRS / COL) — directly probeable.",
        "MDIO bus trace — every register access is observable on MDC + MDIO.",
    ])
    f.setdefault("out_of_band_test_facilities", [
        "External RJ-45 loopback plug (TX pair shorted to RX pair) — exercises full TX + RX analog path.",
        "External fiber loopback for 100BASE-FX / 1000BASE-X / 10GBASE-X.",
        "Ethernet protocol analyzer (Wireshark + tap, or LeCroy / Keysight inline) — capture and decode every transmitted and received frame at line rate.",
        "Bit Error Rate Tester (BERT) — for PMA / PMD eye margin and jitter characterization at the MDI.",
        "Vector Network Analyzer (VNA) — for MDI return-loss, NEXT, ELFEXT compliance per Clause 40 / 14 / 25.",
        "JTAG (IEEE 1149.1) — supported by most silicon PHYs for boundary scan and scan-chain access; not specified in the 802.3 standard itself.",
        "Vendor-specific BIST register — many PHYs add a self-test mode controllable through registers 16-31 (Clause 22) or vendor MMDs (DEVAD 30-31).",
    ])
    f["notes"] = (
        "IEEE Std 802.3-2005 specifies the in-band test facilities listed in "
        "Clause 22.2.4.1 (BMCR Loopback / Isolate / Collision Test / Power "
        "Down) and Clause 28 (AutoNeg Restart) as MANDATORY for any "
        "conforming PHY. JTAG / scan-chain / on-chip BIST are NOT in the "
        "protocol scope — every PHY vendor adds those as implementation "
        "features. The MII / GMII / MDIO signals are universally probeable "
        "at the connector; protocol analyzers + BERTs + VNAs supply the "
        "analog observability at the MDI.")
    d["fields"] = f
    _write(p, d)


def _apply_l23(gd: Path) -> None:
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if not p.is_file():
        return
    d = _read(p)
    f = d.get("fields") or {}
    f["security_requirements_present"] = False
    f.setdefault("anti_corruption_features", [
        "IEEE 802.3 CRC-32 Frame Check Sequence (polynomial 0x04C11DB7) detects all 1-bit, 2-bit, and 3-bit errors, all burst errors up to 32 bits in length, and statistically catches longer multi-bit errors with probability 1 - 2^-32.",
        "PHY line coding (Manchester / 4B/5B / 8B/10B / PAM5 / PAM4) provides intrinsic DC balance and transition density, enabling clock recovery and inherent invalid-symbol detection (the PHY's RX_ER signals coding errors before they reach the MAC).",
        "Preamble + SFD framing — the MAC byte-aligns on the SFD nibble (0xD), guaranteeing that bit-slip recovery happens at known boundaries.",
        "False Carrier indication (RX_DV = 0, RX_ER = 1, RXD = 0x1110) explicitly distinguishes spurious medium activity from a valid frame, preventing the MAC from delivering nonsense data.",
    ])
    f.setdefault("future_security_pointers", [
        "IEEE 802.1AE MACsec (added 2006) — line-rate AES-GCM encryption + 64-bit ICV + replay protection on top of the Ethernet MAC. Operates between the LLC client and the MAC; transparent to PHYs.",
        "IEEE 802.1X Port-Based Network Access Control — EAP-based authentication before a port is allowed to forward user frames; controls MACsec key agreement (MKA).",
        "IEEE 802.1AR Secure Device Identity (DevID) — X.509 device certificate provisioning.",
        "IETF MACsec Key Agreement (MKA) — EAPOL-based negotiation of the SecY shared key.",
        "Time-Sensitive Networking (IEEE 802.1 TSN) — gate-control + per-stream filtering (802.1Qci) adds availability protection against malformed / mistimed frames but is not cryptographic.",
        "VLAN-based isolation (802.1Q) and Provider Bridging (802.1ad) — administrative isolation, not cryptographic.",
    ])
    f["notes"] = (
        "IEEE Std 802.3-2005 (and all earlier base specs) is a wire-level + "
        "frame-level + management-interface specification with NO "
        "confidentiality, authentication, or anti-replay features at the MAC "
        "+ RS + MII / GMII / MDIO boundary. The only integrity protection is "
        "the 32-bit FCS, which is an error-detection mechanism, not a "
        "cryptographic MAC. Modern link-layer security (MACsec, 802.1X, MKA, "
        "DevID) is built on top of 802.3 at higher OSI layers and was added "
        "in IEEE 802.1AE-2006 and subsequent standards. The base 802.3 frame "
        "format itself (DA + SA + Type/Length + Payload + FCS) does not "
        "natively carry an integrity tag, sequence number, or initialisation "
        "vector; MACsec adds these in a Security Tag inserted between SA and "
        "Payload.")
    d["fields"] = f
    _write(p, d)


def apply_ethernet_synth(generated_docs_dir: Path, is_ethernet: bool,
                         ethernet_ic_name: Optional[str]) -> None:
    """Apply IEEE 802.3 Ethernet-specific synth when the structural signature matched."""
    if not is_ethernet:
        return
    gd = Path(generated_docs_dir)
    if ethernet_ic_name is not None:
        _force_ic_name(gd, ethernet_ic_name)
    _apply_l1(gd)
    _apply_l2(gd)
    _apply_l3(gd)
    _apply_l4(gd)
    _apply_l5(gd)
    _apply_l6(gd)
    _apply_l7(gd)
    _apply_l8_consts(gd)
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
    _apply_l23(gd)


# ---------------------------------------------------------------------------
# Module-level importable detector (lifted from the inline detector in
# phase1_doc_one_shot_runner.py — ORGANIC-20260531). Byte-for-byte the same
# boolean the runner used inline (`_spi_blob` -> `blob`), so behaviour is
# identical; exposing it module-level lets the universal no-misfire guard
# (tests/test_protocol_detector_no_misfire.py) auto-cover this protocol.
# Reads ONLY the spec text `blob` — never a filename or benchmark name.
# ---------------------------------------------------------------------------
def is_ethernet(blob: str) -> bool:
    """Content-only `ethernet` (IEEE 802.3) detector with a FOREIGN-PRIMARY DEFER.

    The base structural signature (MII+MDIO+PHY, or 802.3+MAC+frame, or
    Ethernet+preamble/SFD) is necessary but NOT sufficient: a very large
    family of protocols either RIDE ON Ethernet (PTP / PROFINET / EtherCAT /
    AFDX / automotive-Ethernet / 800G), CITE Ethernet as a comparison or
    transport (Fibre Channel / InfiniBand / Interlaken / SGMII / MDIO / NVMe /
    PCIe / USB / USB-PD / HDMI / SpaceWire / FlexRay / ARINC-429 / Modbus /
    BLE), or are derived CHILDREN that share the 802.3 base (800G, automotive
    single-pair PHYs, PCIe-Gen5). Their generated L-docs carry the MII / MDIO /
    PHY / 802.3 / MAC / frame / preamble tokens that trip the loose branches
    below, so the generic Ethernet synth would false-fire on a spec whose true
    subject is one of those protocols.

    Guard (mirrors the `is_mipi` foreign-primary defer doctrine and the AHB+APB
    `_axi_primary` doctrine — GENERAL, content-only, NO chip / SKU / benchmark-
    name literal as detection logic): if the blob's DOMINANT subject is a
    foreign protocol — detected via that protocol's OWN distinctive structural
    signature (frame-field names, register/role tokens, encoding/timing terms,
    density counts) — defer (return False) before the base 802.3 signature can
    fire. For a derived CHILD the defer keys on the child's distinctive
    discriminator (a sibling-MUTEX), which is correct hardening.

    Empirically verified corpus-clean: the real `ethernet` benchmark trips NONE
    of these defers (own-fire preserved); every Ethernet-adjacent foreign trips
    its own protocol's defer and is suppressed.
    """
    if not blob:
        return False
    import re

    low = blob.lower()
    head = low[:3500]  # input_doc-first: a real spec names its subject up front

    def _wb(tok: str) -> bool:
        return re.search(r"\b" + re.escape(tok) + r"\b", low) is not None

    # --- FOREIGN-PRIMARY DEFER (the blob's true subject is NOT plain 802.3). ---

    # AFDX (ARINC 664 Part 7): Virtual Link + BAG / dual-network redundancy.
    afdx_primary = (
        ("virtual link" in low or "vl id" in low or "vlid" in low)
        and ("bandwidth allocation gap" in low or "arinc 664" in low
             or "arinc664" in low
             or ("network a" in low and "network b" in low)))

    # ARINC-429: Mark 33 DITS 32-bit word with Label + SSM / BNR / BCD.
    arinc429_primary = (
        ("arinc 429" in low or "mark 33" in low)
        and ("dits" in low or "label" in low)
        and ("ssm" in low or "sign/status" in low or "32-bit word" in low
             or "bnr" in low or "bcd" in low))

    # Automotive single-pair PHY (100/1000BASE-T1, 10BASE-T1S/L): PAM3 +
    # named T1 variant + single-twisted-pair / PLCA / echo-cancellation.
    automotive_eth_primary = (
        _wb("pam3")
        and ("100base-t1" in low or "1000base-t1" in low
             or "10base-t1s" in low or "10base-t1l" in low
             or "broadr-reach" in low)
        and ("single twisted pair" in low or "single-pair" in low
             or "plca" in low or "echo cancel" in low))

    # Bluetooth Low Energy: BLE name anchor + GAP/GATT or advertising/connection.
    ble_primary = (
        ("bluetooth low energy" in low or "bluetooth le" in low)
        and (("gap" in low and "gatt" in low)
             or ("advertising" in low and "connection" in low)))

    # EtherCAT: ESC + FMMU/SyncManager / EtherType 0x88A4 / datagram fieldbus.
    ethercat_primary = (
        "ethercat" in low
        and (("fmmu" in low and "syncmanager" in low)
             or "0x88a4" in low
             or ("esc" in low and "datagram" in low)))

    # 800G Ethernet child: the 800GBASE / 802.3df naming, or PAM4 + KP4/RS-FEC
    # at the 100G-per-lane (106.25 / 112.5 GBd) rate that plain 802.3 lacks.
    ethernet_800g_primary = (
        "800gbase" in low or "800gbe" in low or "800g ethernet" in low
        or "802.3df" in low
        or (("pam4" in low)
            and ("106.25" in low or "kp4" in low or "rs-fec" in low
                 or "rs(544" in low)
            and ("800g" in low or "800 gb" in low or "112.5" in low)))

    # Fibre Channel: N_Port/F_Port port-type triple + FLOGI/PLOGI + FC-2 header.
    fibre_channel_primary = (
        _wb("n_port") and _wb("f_port")
        and ("flogi" in low or "plogi" in low)
        and ("fc-2" in low or "r_ctl" in low))

    # FlexRay: static + dynamic segment + communication cycle / macrotick.
    flexray_primary = (
        "static segment" in low and "dynamic segment" in low
        and ("communication cycle" in low or "macrotick" in low
             or "microtick" in low))

    # HDMI: TMDS line code + DDC/EDID + HPD / HDMI sink discovery.
    hdmi_primary = (
        "tmds" in low and "ddc" in low and "edid" in low
        and ("hpd" in low or "hdmi" in low))

    # InfiniBand: Queue Pair + Virtual Lane + Subnet Manager + LRH (LID).
    infiniband_primary = (
        "queue pair" in low and "virtual lane" in low
        and ("subnet manager" in low or "subnet management" in low)
        and ("local route header" in low or "lrh" in low
             or ("slid" in low and "dlid" in low)))

    # Interlaken: 64B/67B encoding + metaframe (the chip-to-chip SerDes IF).
    interlaken_primary = (
        "interlaken" in low
        and ("64b/67b" in low or "64b67b" in low)
        and "metaframe" in low)

    # MDIO: head-named MDC/MDIO management interface with the Clause 22
    # frame-field model (PHYAD/REGAD) — distinct from the MII data path.
    mdio_primary = (
        ("mdio" in head or "management data input" in head)
        and "mdc" in low
        and ((("phyad" in low or "phy address" in low)
              and ("regad" in low or "register address" in low))
             or "clause 22" in low))

    # Modbus: Function Code + PDU / Read Holding Registers + Read Coils.
    modbus_primary = (
        "modbus" in low
        and (("function code" in low and "pdu" in low)
             or ("read holding registers" in low and "read coils" in low)))

    # NVMe: Submission/Completion Queue + doorbell, or NVM Express command set.
    nvme_primary = (
        ("submission queue" in low and "completion queue" in low
         and "doorbell" in low)
        or ("nvm express" in low
            and ("admin command" in low or "i/o command" in low)))

    # PCIe: TLP/DLLP/LTSSM layer triple, dense "pci express", or the
    # Transaction+Data-Link layer naming (covers the PCIe-Gen5 child too).
    pcie_primary = (
        ("tlp" in low and "dllp" in low and "ltssm" in low)
        or (low.count("pci express") >= 20)
        or ("pci express" in low and "transaction layer" in low
            and "data link layer" in low)
        or ("32 gt/s" in low
            and ("retimer" in low or "lane margining" in low
                 or "pcie 5.0" in low)))

    # PROFINET: name + GSDML / IO-Controller+IO-Device roles / RT EtherType.
    profinet_primary = (
        "profinet" in low
        and ("gsdml" in low
             or (("io-controller" in low or "io controller" in low)
                 and ("io-device" in low or "io device" in low))
             or "0x8892" in low))

    # PTP (IEEE 1588): Sync + Follow_Up + Delay_Req/Resp (or Pdelay) + BMCA.
    ptp_primary = (
        (("sync" in low and ("follow_up" in low or "follow-up" in low))
         and (("delay_req" in low and "delay_resp" in low)
              or "pdelay" in low))
        and ("best master clock" in low or "bmca" in low
             or "grandmaster" in low))

    # SGMII: head-named GMII-over-SerDes + 1.25 GBd / 8B10B + Config_Reg word.
    sgmii_primary = (
        ("sgmii" in head or "serial-gmii" in head or "serial gmii" in head)
        and ("1.25 gbd" in low or "1.25 gbaud" in low or "625 mhz" in low
             or "8b/10b" in low or "8b10b" in low)
        and ("config_reg" in low or "tx_config_reg" in low
             or "configuration ordered set" in low))

    # SpaceWire: Data-Strobe encoding + FCT control char + EOP/EEP.
    spacewire_primary = (
        (("data-strobe" in low or "data strobe" in low)
         or ("strobe" in low
             and ("xor" in low or "exclusive-or" in low)))
        and (_wb("fct") or "flow control token" in low)
        and (_wb("eop") or "end of packet" in low or _wb("eep")))

    # USB (2.0): VBUS + D+/D- NRZI, or NRZI endpoint host-controller model.
    usb_primary = (
        "vbus" in low
        and (("d+" in low and "d-" in low and "nrzi" in low)
             or ("nrzi" in low and "endpoint" in low
                 and ("packet id" in low or "pid" in low)
                 and "host controller" in low)))

    # USB Power Delivery child: BMC line code + PDO/RDO power-object contract.
    usb_pd_primary = (
        ("power delivery" in low or "usb-pd" in low or "usb pd" in low)
        and "biphase mark" in low
        and (("power data object" in low or _wb("pdo"))
             and ("request data object" in low or _wb("rdo"))))

    if (afdx_primary or arinc429_primary or automotive_eth_primary
            or ble_primary or ethercat_primary or ethernet_800g_primary
            or fibre_channel_primary or flexray_primary or hdmi_primary
            or infiniband_primary or interlaken_primary or mdio_primary
            or modbus_primary or nvme_primary or pcie_primary
            or profinet_primary or ptp_primary or sgmii_primary
            or spacewire_primary or usb_primary or usb_pd_primary):
        return False

    # --- STRUCTURAL IEEE 802.3 ETHERNET signature (unchanged from the runner's
    #     inline detector). ---
    return bool(
        ("MII" in blob and "MDIO" in blob
            and "PHY" in blob)
        or ("802.3" in blob and "MAC" in blob
            and "frame" in blob.lower())
        or ("Ethernet" in blob
            and ("preamble" in blob.lower()
                 or "SFD" in blob)))
