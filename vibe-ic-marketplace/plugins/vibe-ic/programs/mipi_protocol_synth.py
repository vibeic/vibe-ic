"""MIPI D-PHY / CSI-2 protocol synth helper.

v0.1.84 — ic_class-gated overlay for `bus_interconnect_protocol` /
`serial_peripheral_protocol` specs that exhibit the MIPI D-PHY / CSI-2
structural signature (Clock Lane + Data Lane + HS + LP + sub-LVDS, OR
Long Packet + Short Packet + DI + ECC + CRC-16). Applies MIPI Alliance
D-PHY v1.2 + CSI-2 v1.3 spec-canonical content to L1-L23.

Doctrine: structural-keyword detection IS general within an ic_class
(mirrors AMBA-AXI / SPI / I2C / UART / CAN / USB / I2S synth approach).
Any D-PHY / CSI-2 family variant (D-PHY v1.x / v2.x base spec, CSI-2
v1.x / v2.x, DSI sharing D-PHY) exhibits the same structural signature.

Public entry: `apply_mipi_synth(generated_docs_dir, is_mipi, mipi_ic_name)`.
Public detector: `is_mipi(blob)` — structural MIPI signature WITH a
foreign-primary defer (the v0.1.94 ORGANIC-csi2-mentions guard).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

import l_doc_generator_stamp as _stamp


# ----- helpers --------------------------------------------------------------

def _wb(tok: str, blob: str) -> bool:
    """Word-boundary token match (avoids substring false-positives)."""
    return re.search(r"\b" + re.escape(tok) + r"\b", blob) is not None


def is_mipi(blob: str) -> bool:
    """CONTENT-ONLY MIPI D-PHY / CSI-2 detector with a FOREIGN-PRIMARY DEFER.

    The structural signature (raw "MIPI"+"D-PHY", or CSI-2 Long/Short Packet,
    or D-PHY Clock/Data Lane, or MIPI+HS+LP) is necessary but NOT sufficient:
    UFS (built on MIPI UniPro + M-PHY, which the spec calls "based on D-PHY")
    and PCIe specs that cite MIPI/CSI-2 as an incidental pipeline / vendor
    example would otherwise trip it and have the generic-MIPI synth inject
    CSI-2 camera-pipeline example text ("consumes CSI-2 packets", "CSI-2 RX
    IP cores") into their L-docs (the v0.1.94 ORGANIC-csi2-mentions backlog).

    Guard (mirrors `is_mipi_csi2`'s foreign-primary defer doctrine and the
    AHB+APB `_axi_primary` doctrine — general, content-only, no chip/SKU
    literal as detection logic): if the blob's DOMINANT subject is a foreign
    protocol, defer (False), so the generic MIPI synth never fires on a
    foreign spec that only mentions MIPI / D-PHY / CSI-2 incidentally:
      - PCIe (TLP/DLLP/LTSSM, or dense "pci express", or 32 GT/s + LTSSM)
      - UFS  (UniPro+M-PHY, or JESD220+UFS, or dense "ufs")
      - DisplayPort / eDP (the VESA DP structural signature: Main Link + AUX
        + DPCD + CR/EQ training or RBR/HBR rate vocabulary). DisplayPort is a
        display interface that cites MIPI DSI as a comparison; its generated
        L-docs carry incidental "MIPI"/"D-PHY" tokens that trip the loose
        structural branches below. The DP signature is absent from every real
        MIPI benchmark, so deferring on it is safe.

    Empirically verified corpus-clean: the three real MIPI benchmarks
    (mipi / mipi_csi2 / mipi_dsi) trip NONE of these defers and stay True;
    pcie_gen5 trips pcie_primary, ufs trips ufs_primary, displayport/edp trip
    dp_primary, so all are suppressed. See test_mipi_foreign_primary_defer.py.
    """
    if not blob:
        return False
    low = blob.lower()

    # --- FOREIGN-PRIMARY DEFER (the blob's true subject is NOT MIPI). ---
    pcie_primary = (
        low.count("pci express") >= 20
        or ("32 gt/s" in low and "ltssm" in low)
        or (_wb("LTSSM", blob) and _wb("TLP", blob) and _wb("DLLP", blob)))
    ufs_primary = (
        low.count("ufs") >= 20
        or ("unipro" in low and ("m-phy" in low or "mphy" in low))
        or ("jesd220" in low and ("universal flash storage" in low
                                  or _wb("UFS", blob))))
    # DisplayPort-primary: the VESA DP structural signature (Main Link + AUX +
    # DPCD + a DP-only discriminator). Mirrors displayport_protocol_synth.
    _dp_main_link = "main link" in low
    _dp_aux = ("aux ch" in low or "aux channel" in low
               or "i2c-over-aux" in low)
    _dp_dpcd = ("dpcd" in low
                or "displayport configuration data" in low)
    _dp_cr_eq = (
        (("clock recovery" in low or "clock-recovery" in low)
         and ("channel equalization" in low
              or "channel-equalization" in low))
        or ("link training" in low and "training_pattern_set" in low))
    _dp_rate = (("rbr" in low and "hbr" in low) or "hbr2" in low
                or "hbr3" in low or "link_bw_set" in low)
    dp_primary = (_dp_main_link and _dp_aux and _dp_dpcd
                  and (_dp_cr_eq or _dp_rate))
    if pcie_primary or ufs_primary or dp_primary:
        return False

    # --- STRUCTURAL MIPI D-PHY / CSI-2 signature (unchanged from the runner's
    #     v0.1.84 inline detector). ---
    return (
        ("MIPI" in blob
            and ("D-PHY" in blob or "DPHY" in blob))
        or ("CSI-2" in blob and "Long Packet" in blob
            and "Short Packet" in blob)
        or ("D-PHY" in blob and "Clock Lane" in blob
            and "Data Lane" in blob)
        or ("MIPI" in blob and "HS" in blob
            and "LP" in blob
            and ("D-PHY" in blob or "CSI" in blob)))


def _empty(v) -> bool:
    return v in (None, {}, []) or (isinstance(v, str) and not v.strip())


def _read(p: Path) -> dict:
    return json.loads(p.read_text())


def _write(p: Path, d: dict) -> None:
    # THE L-document write chokepoint: stamps the producing release onto
    # the document, then serialises it byte-identically to before.
    _stamp.dump(p, d)


def _ensure_dict(d: dict, key: str) -> dict:
    """setdefault-None-safe: if the key holds None / '' / [] replace with {}."""
    if d.get(key) in (None, "", []):
        d[key] = {}
    return d[key]


# ----- per-layer overlays ---------------------------------------------------

def _l1(gd: Path, ic_name: str) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("document_title",
                 "MIPI D-PHY Physical Layer + Camera Serial Interface 2 (CSI-2) Protocol Layer")
    d.setdefault("document_number",
                 "MIPI Alliance D-PHY v1.2 + CSI-2 v1.3 (TI SLLA414 application note overlay)")
    d.setdefault("version", "D-PHY v1.2 + CSI-2 v1.3")
    d.setdefault("revised_date",
                 "Application note revised; D-PHY v1.2 (2014) + CSI-2 v1.3 (2014)")
    d.setdefault("original_release_date",
                 "D-PHY v0.9 (2007) + CSI-2 v1.0 (2005)")
    d.setdefault("manufacturer",
                 "MIPI Alliance (specification owner); Texas Instruments (application-note publisher)")
    d.setdefault("copyright",
                 "© MIPI Alliance / © Texas Instruments Incorporated")
    d.setdefault("abstract",
                 "MIPI D-PHY is a low-power, source-synchronous, differential physical layer for connecting cameras and displays to mobile application processors. CSI-2 is the packet-based protocol layer for camera traffic that runs on top of D-PHY. The pair together defines a 1 Clock Lane + 1-to-4 Data Lane sub-LVDS interface with dual-mode (HS / LP) signaling and ECC + CRC-16 protected packets.")
    d.setdefault("keywords", [
        "MIPI", "D-PHY", "CSI-2", "Clock Lane", "Data Lane", "HS", "LP",
        "Long Packet", "Short Packet", "ECC", "CRC-16",
        "Data Identifier", "Virtual Channel", "Data Type",
    ])
    d.setdefault("external_pins", [
        "CLK_P (Clock Lane positive, differential)",
        "CLK_N (Clock Lane negative, differential)",
        "DAT0_P (Data Lane 0 positive)",
        "DAT0_N (Data Lane 0 negative)",
        "DAT1_P / DAT1_N (Data Lane 1, optional)",
        "DAT2_P / DAT2_N (Data Lane 2, optional)",
        "DAT3_P / DAT3_N (Data Lane 3, optional)",
    ])
    d.setdefault("external_pin_count",
                 "2..10 (1 Clock Lane pair + 1..4 Data Lane pairs)")
    d.setdefault("key_features", [
        "Source-synchronous differential serial physical layer (1 Clock Lane + 1..4 Data Lanes).",
        "Dual signaling modes per lane: HS (High-Speed, 80 Mbps to 1.5 Gbps per lane; D-PHY v1.2 raises to 2.5 Gbps) + LP (Low-Power, ≤ 10 Mbps single-ended).",
        "DDR Clock Lane: both edges of CLK_P/CLK_N latch one bit on each Data Lane; Data-rate = 2 × Clock-Lane-Hz.",
        "HS signaling: 100-200 mV differential swing on terminated (100 Ω) lines; sub-LVDS.",
        "LP signaling: 1.2 V CMOS swing, unterminated; used for control / escape / ULPS.",
        "Lane states LP-00 / LP-01 / LP-10 / LP-11; HS-0 / HS-1.",
        "LP-11 = Stop state (idle); LP-01 → LP-00 = HS request; LP-10 → LP-00 = Escape request.",
        "HS Entry sequence: LP-11 → LP-01 → LP-00 → HS-0 (zero) → Sync (00011101) → HS payload.",
        "HS Exit / Trail: payload → HS-Trail → LP-11.",
        "CSI-2 protocol layer carried on D-PHY HS payload: Long Packet (4-byte header DI+WC+ECC + payload + 2-byte CRC-16) + Short Packet (4-byte DI+Data+ECC, used for FS/FE/LS/LE sync).",
        "Data Identifier (DI) byte = VC[7:6] (Virtual Channel) + DT[5:0] (Data Type — RAW6/7/8/10/12/14, YUV420/422-8/10, RGB444/555/565/666/888, generic).",
        "Header ECC: extended Hamming(8,4) — single-bit correct, double-bit detect over DI + WC.",
        "Payload Checksum: CRC-16 polynomial 0x1021, init 0xFFFF, MSB-first.",
        "4 Virtual Channels (v1.1) / 16 (v1.2+) for time-multiplexing multiple image sources on one physical bus.",
        "Frame-sync short packets FS (Frame Start) / FE (Frame End) / LS (Line Start) / LE (Line End).",
    ])
    d.setdefault("topology_summary",
                 "Point-to-point unidirectional source → sink only (no bus, no daisy chain). 1 camera/display source ↔ 1 application-processor sink per physical interface. During HS, the Data Lanes are unidirectional source → sink; during LP, they are bidirectional (both ends can drive LP states for ULPS/Trigger/Reset).")
    d.setdefault("package_summary",
                 "Application-processor SoC + image sensor / display panel side; physical interconnect is PCB-trace or short FFC cable (≤ 30 cm at low rates; shorter at 1.5+ Gbps).")
    d.setdefault("revision_history", [
        {"version": "D-PHY v0.9", "date": "2007", "description": "Initial D-PHY release; HS up to 1 Gbps per lane."},
        {"version": "D-PHY v1.0", "date": "2009", "description": "First production release; locked HS / LP definitions."},
        {"version": "D-PHY v1.1", "date": "2011", "description": "Added ULPS clarification; 4 Virtual Channels."},
        {"version": "D-PHY v1.2", "date": "2014", "description": "Raised HS data-rate ceiling to 2.5 Gbps per lane; expanded VC to 16."},
        {"version": "CSI-2 v1.0", "date": "2005", "description": "Initial CSI-2 release on D-PHY v0.9."},
        {"version": "CSI-2 v1.3", "date": "2014", "description": "Aligned with D-PHY v1.2; added RAW20/24, scrambling foundation."},
    ])
    d.setdefault("use_cases", [
        "Mobile-phone main + front camera (CSI-2)",
        "Tablet camera modules",
        "Automotive camera + display links",
        "Application-processor → image sensor interface",
        "Application-processor → display panel (DSI uses same D-PHY)",
        "Multi-sensor time-multiplexed capture via Virtual Channels",
    ])
    d.setdefault("overview",
                 "MIPI Alliance specified D-PHY as a sub-LVDS, source-synchronous, differential physical layer to interconnect mobile-application processors with image sensors (CSI-2 protocol layer) and display panels (DSI protocol layer). D-PHY operates in two modes — HS (high-speed, terminated 100 Ω differential, 80 Mbps to 1.5 / 2.5 Gbps per lane) and LP (low-power, single-ended 1.2 V CMOS, ≤ 10 Mbps) — sharing the same two wires per lane. CSI-2 runs on top of D-PHY HS payload as a packet-based protocol: Long Packets carry image data (header + payload + CRC-16 footer), Short Packets carry frame/line sync (header only with ECC). The header is protected by extended Hamming(8,4) ECC (single-bit correct, double-bit detect); the payload is protected by CRC-16 polynomial 0x1021. Each packet's first byte (Data Identifier = DI) encodes a 2-bit Virtual Channel + 6-bit Data Type that names the image format (RAW, YUV, RGB, generic, sync).")
    _write(p, d)


def _l2(gd: Path, ic_name: str) -> None:
    p = gd / "L2_FRS.json"
    if not p.is_file():
        return
    d = _read(p)
    po = _ensure_dict(d, "protocol_overview")
    po.setdefault("type",
                  "Source-synchronous, half-duplex (per lane), packet-based serial protocol stack. D-PHY (physical layer) + CSI-2 (protocol layer).")
    po.setdefault("duplex",
                  "half-duplex per lane; Data Lanes carry source→sink HS payload but allow source↔sink LP escape (e.g. ULPS).")
    po.setdefault("synchronous", True)
    po.setdefault("wire_names", [
        "CLK_P / CLK_N (Clock Lane differential pair)",
        "DAT0_P / DAT0_N (Data Lane 0 differential pair)",
        "DAT1.. (optional additional Data Lanes)",
    ])
    # FORCE-OVERWRITE: the runner's broad keyword heuristic at
    # phase1_doc_one_shot_runner.py L17918 pre-sets wire_count=2 (default
    # for non-SPI serial); MIPI's structural detector is more specific
    # (Clock Lane pair + N Data Lane pairs, N=1..4) so overwrite here.
    # Mirrors HDMI synth pattern (hdmi_protocol_synth.py L290).
    po["wire_count"] = "2 + 2 × N_data_lanes (N = 1..4)"
    po.setdefault("dual_mode_signaling",
                  "HS (high-speed terminated differential 100-200 mV) + LP (low-power single-ended 1.2 V CMOS); share same wires.")
    po.setdefault("DDR_clock",
                  "Both edges of Clock Lane latch one bit per Data Lane; Data-rate = 2 × Clock-Lane-frequency.")
    po.setdefault("controller_role",
                  "Source (image sensor / display panel side) drives all HS payload; both ends can initiate LP escape.")
    po.setdefault("target_role",
                  "Sink (application processor) receives HS payload, decodes CSI-2 packets, may participate in LP escape (e.g. acknowledge ULPS exit).")
    fr = [
        {"id": "FR-PHY-LANES-01", "text": "D-PHY shall use exactly 1 Clock Lane + N Data Lanes, N ∈ {1,2,3,4}. Each lane is a single differential pair (Dp/Dn)."},
        {"id": "FR-PHY-HS-02",    "text": "HS mode: differential terminated signaling, 100-200 mV swing, 100 Ω differential termination, 80 Mbps to 1.5 Gbps per lane (D-PHY v1.2 raises ceiling to 2.5 Gbps)."},
        {"id": "FR-PHY-LP-03",    "text": "LP mode: single-ended 1.2 V CMOS signaling, unterminated, ≤ 10 Mbps; used for control / escape / Stop state."},
        {"id": "FR-PHY-DDR-04",   "text": "Clock Lane is DDR — both rising and falling edges of Clock Lane latch one bit on each Data Lane. Data-rate (per lane) = 2 × Clock-Lane Hz."},
        {"id": "FR-PHY-STATES-05","text": "Lane states: LP-00, LP-01, LP-10, LP-11 (Stop), HS-0, HS-1. LP-11 = idle (Stop state)."},
        {"id": "FR-PHY-HS-ENTRY-06","text": "HS Entry sequence: LP-11 → LP-01 → LP-00 → HS-0 (zero, called HS-Zero state) → Sync pattern 8'b00011101 → HS payload."},
        {"id": "FR-PHY-HS-EXIT-07", "text": "HS Exit sequence: HS payload → HS-Trail (last bit held one bit-period longer) → LP-11 (return to Stop state)."},
        {"id": "FR-PHY-ESCAPE-08", "text": "LP Escape Entry sequence: LP-11 → LP-10 → LP-00 → LP-00 Escape Mode pattern. Used for ULPS (Ultra-Low Power State), Trigger, Reset."},
        {"id": "FR-PROTO-PACKET-09","text": "CSI-2 protocol layer is packet-based: Long Packet (4-byte header DI + WC[15:0] + ECC[7:0] + payload + 2-byte CRC-16 footer) and Short Packet (4-byte DI + Data[15:0] + ECC[7:0], no payload)."},
        {"id": "FR-PROTO-DI-10",   "text": "Data Identifier byte DI = VC[7:6] (Virtual Channel) + DT[5:0] (Data Type). VC = 0..3 (D-PHY v1.1) or 0..15 (v1.2+). DT enumerates RAW6/7/8/10/12/14, YUV420/422-8/10, RGB444/555/565/666/888, generic 8-bit, and sync short-packet types FS/FE/LS/LE."},
        {"id": "FR-PROTO-ECC-11",  "text": "Header ECC is extended Hamming(8,4): single-bit-error correct + double-bit-error detect over the 24-bit DI+WC (or DI+Data) header."},
        {"id": "FR-PROTO-CRC-12",  "text": "Long-Packet payload checksum is CRC-16 polynomial 0x1021 (x^16+x^12+x^5+1), initial value 0xFFFF, MSB-first, computed over payload bytes only (not header)."},
        {"id": "FR-PROTO-SYNC-13", "text": "Sync pattern for HS payload entry is 8'b00011101 (LSB-first on the wire = 10111000)."},
        {"id": "FR-PROTO-FS-FE-14","text": "Frame sync uses Short Packets: FS (Frame Start, DT=0x00) → line {LS (Line Start, DT=0x02) → Long Packet payload → LE (Line End, DT=0x03)} × N_lines → FE (Frame End, DT=0x01)."},
        {"id": "FR-PROTO-VC-15",   "text": "Up to 4 (D-PHY v1.1) or 16 (v1.2+) Virtual Channels time-multiplexed on the same physical lanes; each VC carries an independent stream."},
        {"id": "FR-PHY-MULTILANE-16","text": "When N_data_lanes > 1, payload bytes are interleaved across lanes (byte 0 → lane 0, byte 1 → lane 1, ..., byte N → lane 0, ...)."},
        {"id": "FR-PHY-TIMING-17", "text": "Named D-PHY timing parameters: T-LPX (LP transmit length), T-HS-PREPARE (driver settle), T-HS-ZERO (HS-Zero state length), T-HS-TRAIL (trailing bit hold), T-EOT (end-of-transmission), T-CLK-PRE / T-CLK-POST (clock relative to data)."},
    ]
    if _empty(d.get("functional_requirements")):
        d["functional_requirements"] = fr
    d.setdefault("configurations", [
        {"name": "1 Data Lane",  "description": "Smallest config: 1 Clock Lane + 1 Data Lane. Single byte stream."},
        {"name": "2 Data Lanes", "description": "1 Clock Lane + 2 Data Lanes interleaved byte 0/byte 1."},
        {"name": "3 Data Lanes", "description": "1 Clock Lane + 3 Data Lanes (less common)."},
        {"name": "4 Data Lanes", "description": "Maximum: 1 Clock Lane + 4 Data Lanes; 4 × per-lane bandwidth."},
    ])
    d.setdefault("error_response_conditions", [
        "Header ECC single-bit error — corrected silently.",
        "Header ECC double-bit error — packet dropped, error reported.",
        "Payload CRC-16 mismatch — packet payload flagged but length still respected (per WC).",
        "Sync-pattern miss — HS receiver fails to lock; data is lost until next HS Entry.",
        "LP-Contention — both source and sink drive conflicting LP states simultaneously.",
        "T-HS-* timing violation — receiver may sample incorrect bits; per-lane bit error.",
        "Lane-skew exceeding tolerance — multi-lane payload misaligned at receiver.",
    ])
    if _empty(d.get("compliance_requirements")):
        d["compliance_requirements"] = [
            "HS swing 100-200 mV differential; LP swing 1.2 V single-ended.",
            "DDR Clock Lane: both edges of CLK_P/CLK_N produce one Data-Lane bit each.",
            "Sync pattern 8'b00011101 (LSB-first on the wire) must immediately precede HS payload.",
            "Header ECC = extended Hamming(8,4) — must correct 1 bit, detect 2.",
            "Payload CRC-16 polynomial 0x1021, init 0xFFFF, MSB-first.",
            "Stop state = LP-11 ≥ T-LPX after every HS / Escape burst.",
            "Multi-lane: byte 0 → lane 0, byte 1 → lane 1, ..., byte N → lane (N mod N_lanes); inter-pair skew ≤ 100 ps.",
            "Intra-pair skew of Dp/Dn ≤ 5 ps.",
        ]
    _write(p, d)


def _l3(gd: Path, ic_name: str) -> None:
    p = gd / "L3_CMD_PROTOCOL.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("protocol_type",
                 "Packet-based source→sink streaming protocol on top of source-synchronous DDR physical layer; each packet is self-identifying via a 6-bit Data Type encoded inside the 4-byte header. CSI-2 has no opcode/register protocol — only image-data carrying packets + frame/line sync short packets.")
    d.setdefault("channels", [
        {"name": "CLK_P / CLK_N",   "direction": "source → sink (HS); both ends idle LP-11 between bursts", "purpose": "Differential DDR Clock Lane; both edges latch one bit per Data Lane."},
        {"name": "DAT0_P / DAT0_N", "direction": "source → sink (HS); bidirectional during LP/escape",      "purpose": "Differential Data Lane 0; carries CSI-2 packet bytes during HS."},
        {"name": "DAT1..DAT3 (optional)", "direction": "same as DAT0",                                       "purpose": "Additional Data Lanes for higher bandwidth; interleave bytes round-robin across lanes."},
    ])
    d.setdefault("packet_classes", [
        {"class": "Long Packet",  "purpose": "Carries image-data payload (RAW/YUV/RGB/generic). Has header + payload + CRC-16 footer.",
         "header_layout": "DI (1 byte) + WC[15:0] Word Count (2 bytes) + ECC (1 byte) — total 32 bits.",
         "payload_layout": "WC bytes of image data, byte-interleaved across N Data Lanes when N > 1.",
         "footer_layout": "16-bit CRC-16 over payload bytes only (polynomial 0x1021, init 0xFFFF, MSB-first)."},
        {"class": "Short Packet", "purpose": "Frame / line synchronization markers and generic short signaling. No payload, no footer.",
         "header_layout": "DI (1 byte) + Data[15:0] (2 bytes; e.g. frame number for FS) + ECC (1 byte) — total 32 bits.",
         "members": ["FS (Frame Start, DT=0x00)", "FE (Frame End, DT=0x01)", "LS (Line Start, DT=0x02)", "LE (Line End, DT=0x03)", "Generic Short Packet 0x08..0x0F (vendor-defined)"]},
    ])
    d.setdefault("data_identifier_byte", {
        "width_bits": 8,
        "structure": "DI = { VC[1:0] : DT[5:0] } in v1.1 (4 VCs); DI = { VC[3:0] (split across reserved bits) : DT[5:0] } in v1.2+ (16 VCs via VC extension).",
        "VC_field_bits": [7, 6],
        "DT_field_bits": [5, 0],
        "VC_count_v1_1": 4,
        "VC_count_v1_2_plus": 16,
    })
    d.setdefault("data_types_enum", {
        "synchronization_short_packets": [
            {"DT_hex": "0x00", "name": "Frame Start (FS)",       "category": "Short Sync"},
            {"DT_hex": "0x01", "name": "Frame End (FE)",         "category": "Short Sync"},
            {"DT_hex": "0x02", "name": "Line Start (LS)",        "category": "Short Sync (optional)"},
            {"DT_hex": "0x03", "name": "Line End (LE)",          "category": "Short Sync (optional)"},
        ],
        "generic_short_packets": "DT 0x08..0x0F reserved for generic short packets (vendor-defined Data[15:0]).",
        "yuv_formats": [
            {"DT_hex": "0x18", "name": "YUV420 8-bit"},
            {"DT_hex": "0x19", "name": "YUV420 10-bit"},
            {"DT_hex": "0x1A", "name": "YUV420 8-bit Legacy"},
            {"DT_hex": "0x1C", "name": "YUV420 8-bit CSPS"},
            {"DT_hex": "0x1D", "name": "YUV420 10-bit CSPS"},
            {"DT_hex": "0x1E", "name": "YUV422 8-bit"},
            {"DT_hex": "0x1F", "name": "YUV422 10-bit"},
        ],
        "rgb_formats": [
            {"DT_hex": "0x20", "name": "RGB444"},
            {"DT_hex": "0x21", "name": "RGB555"},
            {"DT_hex": "0x22", "name": "RGB565"},
            {"DT_hex": "0x23", "name": "RGB666"},
            {"DT_hex": "0x24", "name": "RGB888"},
        ],
        "raw_formats": [
            {"DT_hex": "0x28", "name": "RAW6"},
            {"DT_hex": "0x29", "name": "RAW7"},
            {"DT_hex": "0x2A", "name": "RAW8"},
            {"DT_hex": "0x2B", "name": "RAW10"},
            {"DT_hex": "0x2C", "name": "RAW12"},
            {"DT_hex": "0x2D", "name": "RAW14"},
        ],
        "generic_long_packets": "DT 0x30..0x37 reserved for user-defined 8-bit data (long packets).",
    })
    d.setdefault("header_ecc_field", {
        "width_bits": 8,
        "structure": "Extended Hamming(8,4): 6 parity bits over 24 data bits (DI + WC[7:0] + WC[15:8]) + 2 extra bits for double-bit detect.",
        "correction_capability": "1-bit error — corrected automatically.",
        "detection_capability": "2-bit error — detected; packet discarded.",
    })
    d.setdefault("payload_crc_field", {
        "width_bits": 16,
        "polynomial_hex": "0x1021",
        "polynomial_equation": "x^16 + x^12 + x^5 + 1",
        "initial_value_hex": "0xFFFF",
        "shift_direction": "MSB-first",
        "covers": "Long Packet payload bytes only (does NOT cover header).",
    })
    d.setdefault("transaction_phases", [
        "HS Entry — source drives LP-11 → LP-01 → LP-00 → HS-0 → Sync pattern 8'b00011101.",
        "Packet Stream — one or more Long / Short Packets back-to-back on HS payload (header → payload → footer per Long Packet).",
        "HS Exit — HS-Trail → LP-11 (Stop state).",
        "Optional Escape — LP-11 → LP-10 → LP-00 → escape-pattern for ULPS / Trigger / Reset.",
    ])
    d.setdefault("addressing", {
        "device_address": "None — CSI-2 is strictly point-to-point source→sink; one transmitter + one receiver per physical interface.",
        "virtual_channel_width_bits_v1_1": 2,
        "virtual_channel_width_bits_v1_2_plus": 4,
        "default_VC_at_reset": 0,
        "VC_role": "Time-multiplex multiple logical streams (e.g. left + right sensor) onto the same physical D-PHY.",
    })
    d.setdefault("valid_ready_handshake_rules", [
        "There is no ACK / NAK / retry — CSI-2 is one-way source→sink streaming.",
        "HS Entry sync pattern (8'b00011101) marks start of payload; receiver locks here.",
        "Header ECC validates DI + WC; corrupt headers are dropped silently (after correction or detect).",
        "Payload CRC-16 mismatch is reported to upper layers but does not trigger retransmission — host application decides.",
        "LP-11 Stop state separates bursts; LP-Contention is an error case detected by both endpoints.",
    ])
    d.setdefault("burst_based", True)
    d.setdefault("byte_oriented", True)
    _write(p, d)


def _l4(gd: Path, ic_name: str) -> None:
    p = gd / "L4_REGMAP.json"
    if not p.is_file():
        return
    d = _read(p)
    d["register_map_present"] = False
    d["notes"] = (
        "MIPI D-PHY (physical layer) + CSI-2 (protocol layer) define NO "
        "conventional register file at the protocol layer. CSI-2 packets "
        "are wire-level image data; there is no opcode/register transport "
        "over CSI-2 itself. Image-sensor implementations expose vendor-"
        "specific control registers (gain / exposure / ROI / lens-shading "
        "/ black-level / frame-rate / Virtual-Channel assignment / Data-"
        "Type select / lane-count select / etc.) over a SEPARATE sideband "
        "bus — typically I2C (SCCB variant from OmniVision, or generic "
        "I2C with sensor-specific register maps from Sony / ON Semi / "
        "etc.). These sideband register maps are documented per sensor "
        "datasheet, not in the MIPI D-PHY / CSI-2 specifications.")
    _write(p, d)


def _l5(gd: Path, ic_name: str) -> None:
    p = gd / "L5_ADI_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["analog_digital_interface_present"] = True
    # FORCE-OVERWRITE: the SPI-class `_apply_universal` helper in
    # spi_protocol_synth.py L63 fires before structural sub-detection
    # refines the ic_class, pre-emitting a "Pure digital ..." string.
    # MIPI D-PHY is firmly mixed-signal (dual-mode HS + LP); the MIPI
    # structural detector knows better, so overwrite unconditionally.
    d["signaling_summary"] = (
        "D-PHY is a dual-mode analog/mixed-signal physical layer. HS (High-Speed) mode: terminated 100 Ω differential signaling, 100-200 mV differential swing on top of a common-mode voltage (~200 mV); sub-LVDS class; both ends terminate so the receiver sees a clean eye at multi-gigabit rates. LP (Low-Power) mode: 1.2 V CMOS single-ended swing, unterminated, ≤ 10 Mbps; uses standard CMOS rail-to-rail drivers. The same two wires (Dp/Dn) carry both modes — the HS driver is current-mode while the LP driver is voltage-mode, and they are arbitrated by the lane-state controller. DC-coupled (no AC-coupling capacitors are used on D-PHY). Termination: 100 Ω differential across Dp/Dn at the sink end during HS; high-impedance during LP.")
    d.setdefault("voltage_levels", {
        "HS_differential_swing_mV": [100, 200],
        "HS_common_mode_V_typ": 0.2,
        "HS_termination_ohm": 100,
        "LP_swing_V": 1.2,
        "LP_termination": "unterminated (high-impedance)",
    })
    d.setdefault("data_rate_ranges", {
        "HS_min_Mbps_per_lane": 80,
        "HS_max_Mbps_per_lane_v1_0": 1000,
        "HS_max_Mbps_per_lane_v1_2": 2500,
        "LP_max_Mbps_per_lane": 10,
    })
    d.setdefault("analog_components_per_lane", [
        "HS differential driver (current-mode, 100-200 mV differential)",
        "HS differential receiver with 100 Ω internal differential termination + threshold comparator",
        "LP push-pull CMOS driver (1.2 V rail-to-rail)",
        "LP receiver — two single-ended CMOS Schmitt inputs (one per Dp, one per Dn)",
        "LP contention detector",
        "Lane-state controller — selects HS vs LP driver/receiver based on lane state",
    ])
    d["notes"] = (
        "Although CSI-2 protocol is purely digital, D-PHY is firmly "
        "mixed-signal: the HS driver is current-mode at multi-gigabit "
        "and requires careful analog design (output impedance, common-"
        "mode, jitter). The LP path is standard CMOS but must coexist "
        "with the HS path on the same pins. The lane-state controller "
        "arbitrates the two.")
    _write(p, d)


def _l6(gd: Path, ic_name: str) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("fsm_states_transmitter", [
        {"name": "TX_LP11_STOP",      "description": "Idle Stop state; LP-11 driven on both Dp and Dn; bus is free."},
        {"name": "TX_LP_REQUEST",     "description": "HS-Request: drive LP-01 (Dp HIGH, Dn LOW) for T-LPX duration."},
        {"name": "TX_LP_BRIDGE",      "description": "Bridge state: drive LP-00 (both LOW) for T-LPX; final LP step before HS entry."},
        {"name": "TX_HS_PREPARE",     "description": "Switch on HS driver, hold differential 0 (HS-0) for T-HS-PREPARE; receiver enables HS termination."},
        {"name": "TX_HS_ZERO",        "description": "Continue HS-0 state for T-HS-ZERO; gives receiver time to lock HS clock recovery."},
        {"name": "TX_HS_SYNC",        "description": "Transmit 8-bit Sync pattern 8'b00011101 (LSB-first on wire = 10111000) to mark start of payload."},
        {"name": "TX_HS_PAYLOAD",     "description": "Stream CSI-2 packet bytes at full HS data rate; bytes interleaved across lanes when N > 1."},
        {"name": "TX_HS_TRAIL",       "description": "Last payload bit is held for T-HS-TRAIL (~ 60 ns or 8 × UI, whichever is larger)."},
        {"name": "TX_HS_EXIT",        "description": "Disable HS driver; LP driver takes over and forces LP-11 (Stop)."},
        {"name": "TX_LP_ESCAPE_REQ",  "description": "Escape Request: drive LP-10 (Dp LOW, Dn HIGH) for T-LPX, then LP-00 → LP-00 → Escape pattern."},
        {"name": "TX_ESC_ULPS",       "description": "Ultra-Low Power State: drive LP-00 continuously; can stay indefinitely."},
        {"name": "TX_ESC_TRIGGER",    "description": "Send LP escape Trigger command (4-bit code)."},
        {"name": "TX_ESC_RESET",      "description": "Send LP escape Reset command (force receiver to known state)."},
    ])
    d.setdefault("fsm_states_receiver", [
        {"name": "RX_LP11_DETECT",    "description": "Wait for LP-11 → LP-01 → LP-00 sequence (HS Request)."},
        {"name": "RX_HS_PREP_DETECT", "description": "Enable HS receiver termination + comparator on detecting LP-00 → HS-0 transition."},
        {"name": "RX_SYNC_LOCK",      "description": "Hunt for Sync pattern 8'b00011101 (LSB-first 10111000); declare byte-boundary lock on match."},
        {"name": "RX_HS_PAYLOAD",     "description": "Sample each Data Lane on both edges of Clock Lane; deinterleave across lanes; assemble byte stream."},
        {"name": "RX_PACKET_DECODE",  "description": "Parse 4-byte header (DI + WC + ECC), validate ECC; if Long Packet, read WC payload bytes + 2-byte CRC-16 footer; if Short Packet, packet ends after header."},
        {"name": "RX_HS_TRAIL_DETECT","description": "Detect end-of-payload via HS-Trail timing + LP-11 transition."},
        {"name": "RX_LP_ESCAPE_DETECT","description": "Detect LP-11 → LP-10 → LP-00 → LP-00 escape pattern; decode escape command."},
    ])
    d.setdefault("fsm_hints", {
        "trigger":      "HS Entry begins when source drives LP-11 → LP-01 → LP-00. Escape Mode begins LP-11 → LP-10 → LP-00. Receiver discriminates by the second LP state.",
        "rule":         "Sync pattern 8'b00011101 (LSB-first on wire) immediately precedes HS payload. Receiver byte-aligns on Sync. Packet boundaries are determined by header WC field (Long) or fixed 4-byte length (Short).",
        "abort":        "HS Exit (HS-Trail → LP-11) cleanly terminates an HS burst. Lane-skew, T-HS-* violation, or LP-Contention causes burst loss; transmitter retries on next frame.",
    })
    d.setdefault("anti_deadlock_rule",
                 "Source is the unique HS driver; sink only drives LP states for ULPS exit handshake or escape acknowledgment. No multi-master arbitration on the HS path. LP path uses LP-Contention detection to recover from transient conflicts.")
    d.setdefault("exit_from_reset_or_poweron",
                 "On power-on or LP escape Reset: both ends drive LP-11 Stop state. Source initiates first HS Entry when image data is ready; sink remains in RX_LP11_DETECT until then.")
    d.setdefault("default_ready_state_recommendation", {
        "Clock_Lane_idle": "LP-11 (Stop state) between HS clock bursts; or HS-0 continuous clock if Continuous-Clock-Mode is enabled.",
        "Data_Lane_idle":  "LP-11 (Stop state) between HS payload bursts.",
    })
    d.setdefault("lane_states_table", [
        {"state": "LP-00", "Dp": 0, "Dn": 0, "meaning": "Bridge before HS / Escape entry; also Escape Mode signaling"},
        {"state": "LP-01", "Dp": 0, "Dn": 1, "meaning": "HS Request (Dn HIGH, Dp LOW)"},
        {"state": "LP-10", "Dp": 1, "Dn": 0, "meaning": "Escape Request / LP signaling"},
        {"state": "LP-11", "Dp": 1, "Dn": 1, "meaning": "Stop state (idle); bus free"},
        {"state": "HS-0",  "Dp": 0, "Dn": 1, "meaning": "HS differential zero (during HS-Prepare / HS-Zero / payload bit '0')"},
        {"state": "HS-1",  "Dp": 1, "Dn": 0, "meaning": "HS differential one (payload bit '1')"},
    ])
    d.setdefault("configurations", [
        {"name": "Continuous Clock Mode",     "description": "Clock Lane stays in HS forever; Data Lanes alternate HS/LP per frame."},
        {"name": "Non-Continuous Clock Mode", "description": "Clock Lane returns to LP-11 between bursts; saves power."},
    ])
    d.setdefault("timing_dependency_rule",
                 "Source drives the Clock Lane DDR — receiver uses both edges to latch one Data-Lane bit each. Sync pattern (8'b00011101 LSB-first) byte-aligns the receiver. Sink's HS receiver must terminate (100 Ω differential) within T-HS-PREPARE so the eye is clean by Sync time.")
    _write(p, d)


def _l7(gd: Path, ic_name: str) -> None:
    p = gd / "L7_TEST_DEBUG.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_debug_architecture_present"] = True
    d.setdefault("spec_provided_observability", [
        {"name": "Eye diagram (HS pair)",       "purpose": "Verify HS driver / receiver / channel quality at multi-gigabit; jitter, opening, common-mode."},
        {"name": "Sync pattern integrity",      "purpose": "Confirm receiver locks on 8'b00011101 (LSB-first 10111000); miss-lock indicates clock-recovery or skew issue."},
        {"name": "ECC parity coverage",         "purpose": "Header ECC = extended Hamming(8,4); single-bit-correct & double-bit-detect over DI + WC."},
        {"name": "CRC-16 verification",         "purpose": "Long-Packet payload integrity; polynomial 0x1021 init 0xFFFF; mismatch reported but not retransmitted."},
        {"name": "Lane skew / deskew",          "purpose": "Inter-pair skew across N Data Lanes must be ≤ 100 ps; intra-pair skew Dp/Dn ≤ 5 ps; trained at HS Entry."},
        {"name": "LP/HS mode transition timing","purpose": "T-LPX, T-HS-PREPARE, T-HS-ZERO, T-HS-TRAIL, T-EOT must all meet D-PHY v1.x bounds."},
        {"name": "LP-Contention detection",      "purpose": "Reported by lane-state controller when both ends drive conflicting LP states."},
        {"name": "Frame / line counters",        "purpose": "FS / FE short packets carry frame number; receiver counts FS/FE matches to verify completeness."},
        {"name": "Virtual Channel decode",       "purpose": "DI[7:6] (or DI[7:6]+extension in v1.2+) identifies VC; receiver routes to correct decoder."},
    ])
    d.setdefault("error_detection_mechanisms", [
        "Header ECC (Hamming 8,4) single-bit-correct / double-bit-detect on every packet header.",
        "Payload CRC-16 (poly 0x1021, init 0xFFFF, MSB-first) on every Long-Packet payload.",
        "Sync-pattern miss-lock — receiver fails to find 8'b00011101 within HS-Zero window; entire burst lost.",
        "T-HS-* timing violation — per-lane bit errors; usually surface as ECC / CRC failures.",
        "Lane-skew exceeded — multi-lane payload de-interleave misalignment; ECC / CRC failures.",
        "LP-Contention — both endpoints assert mutually exclusive LP states.",
        "False EoT (End-of-Transmission) — HS-Trail violated or missing LP-11 return.",
    ])
    d.setdefault("interrupt_or_event_sources", [
        {"event": "FS detected",         "trigger": "Short Packet DT=0x00 received with valid ECC."},
        {"event": "FE detected",         "trigger": "Short Packet DT=0x01 received with valid ECC."},
        {"event": "LS / LE detected",    "trigger": "Short Packet DT=0x02 / 0x03 (optional)."},
        {"event": "ECC corrected",       "trigger": "1-bit error in header ECC was corrected."},
        {"event": "ECC double-bit error","trigger": "2-bit error in header ECC was detected; packet dropped."},
        {"event": "CRC mismatch",        "trigger": "Long-Packet payload CRC-16 mismatch."},
        {"event": "Sync miss-lock",      "trigger": "Receiver did not find Sync within HS-Zero window."},
        {"event": "ULPS entry / exit",   "trigger": "Source / sink escape commands; bus enters / exits Ultra-Low Power State."},
    ])
    d["notes"] = (
        "CSI-2 specifies a rich set of in-band error-detection mechanisms "
        "(ECC, CRC) but provides NO retransmission — host application + "
        "ISP decide whether to drop / interpolate / log a corrupted line. "
        "Production-line characterization relies on eye-diagram "
        "measurements on the HS pair and on running the receiver through "
        "stress patterns (lane skew, jitter, voltage margin) per MIPI "
        "D-PHY conformance test suite.")
    _write(p, d)


def _l8_rtl(gd: Path, ic_name: str) -> None:
    p = gd / "L8_RTL_CONSTANTS.json"
    if not p.is_file():
        return
    d = _read(p)
    wp = _ensure_dict(d, "width_parameters")
    for k, v in {
        "CLOCK_LANE_PAIRS": 1,
        "DATA_LANE_PAIRS_MIN": 1,
        "DATA_LANE_PAIRS_MAX": 4,
        "DIFFERENTIAL_PAIR_WIDTH_bits": 2,
        "HEADER_TOTAL_BYTES": 4,
        "HEADER_DI_BYTES": 1,
        "HEADER_WC_BYTES": 2,
        "HEADER_ECC_BYTES": 1,
        "SHORT_PACKET_TOTAL_BYTES": 4,
        "LONG_PACKET_FOOTER_BYTES": 2,
        "DI_FIELD_WIDTH_bits": 8,
        "VC_FIELD_WIDTH_bits_v1_1": 2,
        "VC_FIELD_WIDTH_bits_v1_2_plus": 4,
        "DT_FIELD_WIDTH_bits": 6,
        "WC_FIELD_WIDTH_bits": 16,
        "ECC_FIELD_WIDTH_bits": 8,
        "CRC_FIELD_WIDTH_bits": 16,
        "SYNC_PATTERN_WIDTH_bits": 8,
        "MAX_VC_COUNT_v1_1": 4,
        "MAX_VC_COUNT_v1_2_plus": 16,
    }.items():
        wp.setdefault(k, v)
    d.setdefault("voltage_levels", {
        "HS_differential_swing_mV_min": 100,
        "HS_differential_swing_mV_max": 200,
        "HS_termination_ohm": 100,
        "LP_swing_V": 1.2,
        "LP_termination": "unterminated",
    })
    d.setdefault("data_rate_constants", {
        "HS_min_Mbps_per_lane": 80,
        "HS_max_Mbps_per_lane_v1_0": 1000,
        "HS_max_Mbps_per_lane_v1_1": 1500,
        "HS_max_Mbps_per_lane_v1_2": 2500,
        "LP_max_Mbps_per_lane": 10,
    })
    d.setdefault("key_constants_for_RTL_authoring", {
        "SYNC_PATTERN_8bit_value": "8'b00011101",
        "SYNC_PATTERN_on_the_wire_LSB_first": "10111000",
        "SYNC_PATTERN_hex": "0x1D",
        "ECC_polynomial_class": "Extended Hamming(8,4) — single-bit correct, double-bit detect.",
        "ECC_data_bits_protected": 24,
        "ECC_parity_bits": 6,
        "ECC_extension_bits": 2,
        "CRC_polynomial": "x^16 + x^12 + x^5 + 1",
        "CRC_polynomial_hex": "0x1021",
        "CRC_initial_value_hex": "0xFFFF",
        "CRC_shift_direction": "MSB-first",
        "CRC_covers": "Long Packet payload bytes only (not header).",
        "multilane_byte_interleave_rule": "byte N → lane (N mod N_data_lanes); byte 0 → lane 0; byte 1 → lane 1; ...",
        "DDR_clock_lane": True,
        "data_rate_to_clock_rate_ratio": 2,
        "is_packet_based": True,
        "is_streaming": True,
        "burst_based": True,
        "byte_oriented": True,
        "no_handshake_no_retry": True,
        "is_source_synchronous": True,
        "data_lane_LSB_first_within_byte": True,
        "header_byte_order": "DI (byte 0), WC[7:0] (byte 1), WC[15:8] (byte 2), ECC (byte 3); little-endian over the wire.",
    })
    d.setdefault("named_timing_parameters_D_PHY", {
        "T_LPX_ns_typ":          "50 (min) — LP transmit length",
        "T_HS_PREPARE_ns":       "40 + 4 × UI .. 85 + 6 × UI — HS driver prepare time",
        "T_HS_ZERO_ns_min":      "105 + 6 × UI — HS-0 state minimum before Sync",
        "T_HS_TRAIL_ns_min":     "max(8 × UI, 60 + 4 × UI) — trailing-bit hold",
        "T_HS_EXIT_ns_min":      "100 — minimum LP-11 after HS Exit",
        "T_EOT_ns_max":          "105 + 12 × UI — total end-of-transmission",
        "T_CLK_PRE_ns_min":      "8 × UI — Clock Lane HS active before Data Lane HS",
        "T_CLK_POST_ns_min":     "60 + 52 × UI — Clock Lane HS active after last Data-Lane bit",
        "UI_definition":         "Unit Interval = 1 / (2 × Clock-Lane-Hz) = 1 / data-rate-per-lane",
    })
    d.setdefault("default_signal_values_when_idle", {
        "Clock_Lane": "LP-11 (Dp=1, Dn=1) if Non-Continuous Clock Mode; HS-0 if Continuous Clock Mode.",
        "Data_Lane":  "LP-11 (Dp=1, Dn=1) — Stop state.",
    })
    _write(p, d)


def _l8_timing(gd: Path, ic_name: str) -> None:
    p = gd / "L8_TIMING_WAVEFORM.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("clock_waveform", {
        "Clock_Lane_DDR":         "Source drives differential Clock Lane (CLK_P / CLK_N). Both rising and falling edges latch one bit per Data Lane → Data-rate = 2 × Clock-Lane-Hz.",
        "HS_clock_swing_mV":      "100-200 differential (sub-LVDS, 100 Ω terminated).",
        "Continuous_Clock_Mode":  "Clock Lane remains in HS forever; Data Lanes alternate HS/LP per frame.",
        "Non_Continuous_Clock_Mode":"Clock Lane returns to LP-11 between HS bursts to save power.",
        "leading_edge":           "LOW-to-HIGH on CLK_P (rising edge of CLK_P - CLK_N differential).",
        "trailing_edge":          "HIGH-to-LOW on CLK_P (falling edge).",
        "T_CLK_PRE_min_ns":       "8 × UI — Clock Lane HS active before Data Lane HS payload begins.",
        "T_CLK_POST_min_ns":      "60 + 52 × UI — Clock Lane HS active after last Data-Lane payload bit before LP-11 return.",
    })
    d.setdefault("hs_entry_waveform", {
        "step_1_stop":     "LP-11 on both Dp and Dn (idle Stop state).",
        "step_2_request":  "LP-01 (Dp LOW, Dn HIGH) for T-LPX (~50 ns min).",
        "step_3_bridge":   "LP-00 (both LOW) for T-LPX (~50 ns min).",
        "step_4_prepare":  "HS driver switches on; drive HS-0 (differential zero) for T-HS-PREPARE (40+4UI .. 85+6UI ns).",
        "step_5_zero":     "Continue HS-0 for T-HS-ZERO (≥ 105 + 6 × UI ns) — receiver locks HS clock-data alignment.",
        "step_6_sync":     "Transmit 8-bit Sync pattern 8'b00011101 (LSB-first on the wire = 10111000).",
        "step_7_payload":  "Stream CSI-2 packet bytes at full HS rate; byte 0 → lane 0, byte 1 → lane 1, ...",
        "step_8_trail":    "Hold last bit for T-HS-TRAIL (max(8UI, 60+4UI) ns).",
        "step_9_exit":     "Disable HS driver; LP driver forces LP-11 (Stop). T-HS-EXIT ≥ 100 ns of LP-11 before next transaction.",
    })
    d.setdefault("escape_entry_waveform", {
        "step_1_stop":     "LP-11.",
        "step_2_request":  "LP-10 (Dp HIGH, Dn LOW) for T-LPX.",
        "step_3_bridge":   "LP-00 for T-LPX.",
        "step_4_escape_pattern": "Transmit escape pattern (ULPS / Trigger / Reset code) at LP rate (≤ 10 Mbps).",
        "step_5_exit":     "LP-11 to return to Stop.",
    })
    d.setdefault("payload_byte_serialization", {
        "format":              "Each byte transmitted LSB-first on the wire (bit 0 first, bit 7 last).",
        "header_byte_order":   "DI (byte 0), WC[7:0] (byte 1), WC[15:8] (byte 2), ECC (byte 3).",
        "ecc_byte_order":      "Single ECC byte covers DI + WC[7:0] + WC[15:8].",
        "crc_byte_order":      "CRC-16 footer: CRC[7:0] first, then CRC[15:8] (little-endian on the wire over bytes; but computed MSB-first over payload).",
        "multilane_interleave":"With N lanes: byte k → lane (k mod N), byte k+N → lane (k mod N), ...; sync byte is replicated on every active lane.",
    })
    d.setdefault("data_signaling_waveforms", {
        "HS_0":  "differential 0 (CLK_P - CLK_N < 0, i.e. Dn HIGH, Dp LOW)",
        "HS_1":  "differential 1 (CLK_P - CLK_N > 0, i.e. Dp HIGH, Dn LOW)",
        "LP_11": "Stop state — both Dp and Dn at 1.2 V (CMOS HIGH)",
        "LP_01": "HS Request — Dp LOW, Dn HIGH",
        "LP_10": "Escape Request — Dp HIGH, Dn LOW",
        "LP_00": "Bridge / Escape — both LOW",
    })
    d.setdefault("named_timing_parameters_table", {
        "header": ["Parameter", "Value (ns)", "Notes"],
        "rows": [
            ["T-LPX",          ">= 50",                "Minimum LP transmit length"],
            ["T-HS-PREPARE",   "40 + 4×UI .. 85 + 6×UI", "HS driver settle window"],
            ["T-HS-ZERO",      ">= 105 + 6×UI",        "HS-0 dwell before Sync"],
            ["T-HS-TRAIL",     ">= max(8×UI, 60 + 4×UI)", "Last-bit hold"],
            ["T-HS-EXIT",      ">= 100",               "LP-11 minimum after HS Exit"],
            ["T-EOT",          "<= 105 + 12×UI",       "Total end-of-transmission"],
            ["T-CLK-PRE",      ">= 8×UI",              "Clock-active before data HS"],
            ["T-CLK-POST",     ">= 60 + 52×UI",        "Clock-active after data HS"],
        ],
    })
    d.setdefault("general_timing_rule",
                 "All HS payload bit timings are derived from UI = 1 / data-rate-per-lane = 1 / (2 × Clock-Lane-Hz). DDR clock: both edges of CLK_P/CLK_N latch one Data-Lane bit. Intra-pair skew Dp/Dn ≤ 5 ps; inter-pair skew Lane0/Lane1/... ≤ 100 ps.")
    d.setdefault("voltage_levels", {
        "HS_swing_diff_mV":     [100, 200],
        "HS_common_mode_V_typ": 0.2,
        "LP_VOH_V":             1.2,
        "LP_VOL_V":             0.0,
    })
    _write(p, d)


def _l9(gd: Path, ic_name: str) -> None:
    p = gd / "L9_INTEGRATION_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("module_role",
                 "Wire-level + packet-based protocol stack connecting a source (image sensor / display panel / serializer) to a sink (application processor / ISP / deserializer). D-PHY (physical layer) + CSI-2 (protocol layer) are MIPI Alliance specifications; the implementation lives in the SoC's CSI-2 receiver IP plus an external PHY block.")
    d.setdefault("integration_overview", {
        "wire_count":          "2 + 2 × N_data_lanes (N=1..4); plus a sideband I2C for sensor control.",
        "wire_directions":     "Clock Lane + Data Lanes: source → sink during HS; bidirectional during LP escape. Sideband I2C: bidirectional.",
        "no_chip_select":      "No CS line; point-to-point pair is the only addressing.",
        "no_addressing":       "No device address on CSI-2; Virtual Channel (VC) field on each packet provides 4 / 16 logical streams over one physical bus.",
        "controller_choices":  "Source (sensor / display TX) is always the HS-payload driver; sink only receives HS and may drive LP for escape acknowledgment.",
        "handshake_at_protocol_layer": "None — CSI-2 has no ACK / NAK / retry. ECC corrects 1-bit header errors; CRC reports payload errors; upper layer decides.",
    })
    d.setdefault("interface_categories", [
        "Source D-PHY transmitter (HS driver + LP driver + lane controller + Clock-Lane DDR generator)",
        "Sink D-PHY receiver (HS receiver with 100 Ω termination + LP receiver + sync-pattern hunter + clock recovery)",
        "Source CSI-2 protocol packetizer (header builder + ECC computer + payload serializer + CRC computer)",
        "Sink CSI-2 protocol depacketizer (header parser + ECC verify + payload de-serializer + CRC verify + VC demux)",
        "Sideband I2C controller (for sensor register access — gain, exposure, ROI, ...)",
    ])
    d.setdefault("interconnect_topologies_supported", [
        "Point-to-point only — 1 source ↔ 1 sink per physical interface.",
        "Multi-stream via Virtual Channels (one physical bus carries up to 4 / 16 independent logical streams).",
    ])
    d.setdefault("default_signal_values_when_omitted",
                 "All lanes idle in LP-11 (Stop state) when source has no data. Clock Lane may remain HS in Continuous Clock Mode.")
    d.setdefault("soc_dependent_items", [
        "Number of Data Lanes (1, 2, 3, or 4) — chosen to match required image bandwidth.",
        "Clock-Lane mode: Continuous vs Non-Continuous.",
        "PHY block: standalone D-PHY transceiver IP or integrated CSI-2 RX/TX subsystem.",
        "CSI-2 receiver IP: line buffer, VC demux, ISP feed.",
        "Sideband I2C controller for sensor configuration (gain/exposure/ROI/lane-count select).",
        "PLL providing Clock Lane DDR frequency (sensor side) + receiver DLL/CDR (sink side).",
        "ESD protection on differential pairs.",
        "Interrupt routing for FS / FE / ECC error / CRC error events.",
        "Power management for ULPS entry/exit.",
    ])
    d.setdefault("pcb_integration_constraints", {
        "differential_pair_impedance_ohm": 100,
        "intra_pair_skew_ps_max":          5,
        "inter_pair_skew_ps_max":          100,
        "max_trace_length_cm":             "≤ 30 (depends on data rate; shorter at 1.5+ Gbps).",
        "AC_coupling":                     "NOT used — D-PHY is DC-coupled differential.",
        "ESD_protection_class":            "Class 2 minimum (HBM 2 kV).",
    })
    d.setdefault("low_power_modes", {
        "Stop_state":           "LP-11 between bursts — minimal current.",
        "ULPS":                 "Ultra-Low Power State; lane held LP-00 indefinitely; deep sleep.",
        "Non_Continuous_Clock": "Clock Lane returns to LP-11 between bursts; saves clock-tree power.",
    })
    d.setdefault("typical_use_cases", [
        "Mobile-phone main + front camera (single CSI-2 interface to ISP).",
        "Multi-camera mobile (front + main + ultra-wide) muxed via VC into a single CSI-2 RX.",
        "Automotive front / rear / surround camera modules → vision SoC.",
        "Tablet / laptop webcam.",
        "Application-processor → display panel (DSI shares the same D-PHY physical layer).",
    ])
    _write(p, d)


def _l10(gd: Path, ic_name: str) -> None:
    p = gd / "L10_TEST_CASES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_cases_present"] = (
        "partial — the MIPI D-PHY + CSI-2 specs define detailed compliance "
        "behaviors (lane states, timing parameters, ECC + CRC algorithms, "
        "packet formats) that map to the MIPI Alliance Conformance Test "
        "Suite, but the spec itself is not a self-contained testbench.")
    d.setdefault("derived_compliance_test_categories", [
        "HS Entry sequence: LP-11 → LP-01 → LP-00 → HS-0 → Sync 8'b00011101 → payload — verify state transitions and durations T-LPX / T-HS-PREPARE / T-HS-ZERO.",
        "HS Exit / Trail: payload → HS-Trail (max(8 UI, 60+4 UI) ns) → LP-11 (≥ T-HS-EXIT = 100 ns).",
        "Sync-pattern lock: receiver byte-aligns on 8'b00011101 (LSB-first 10111000) at every HS Entry; miss-lock → burst lost.",
        "Long Packet receive: header (DI + WC + ECC) → WC payload bytes → CRC-16 footer; verify ECC corrects 1-bit / detects 2-bit; verify CRC-16 polynomial 0x1021, init 0xFFFF, MSB-first.",
        "Short Packet receive: header (DI + Data[15:0] + ECC) for FS (DT=0x00), FE (DT=0x01), LS (DT=0x02), LE (DT=0x03), and generic 0x08..0x0F.",
        "Multi-lane interleaving: byte 0 → lane 0, byte 1 → lane 1, ...; verify de-interleave with N=1,2,3,4.",
        "Virtual Channel demux: 4 VCs (v1.1) or 16 VCs (v1.2+); verify each VC routed to correct decoder.",
        "Data Type enum coverage: RAW6/7/8/10/12/14, YUV420/422-8/10, RGB444/555/565/666/888, generic, sync.",
        "LP Escape Entry: LP-11 → LP-10 → LP-00 → escape pattern; verify ULPS / Trigger / Reset commands.",
        "ULPS entry: source drives LP-00 indefinitely; sink enters deep sleep; verify ULPS exit handshake.",
        "Continuous vs Non-Continuous Clock Mode: verify Clock Lane returns to LP-11 in Non-Continuous and stays HS in Continuous.",
        "Lane skew: intra-pair Dp/Dn ≤ 5 ps; inter-pair Lane0 / Lane1 / ... ≤ 100 ps.",
        "T-CLK-PRE ≥ 8 UI: Clock Lane HS active before Data Lane HS.",
        "T-CLK-POST ≥ 60 + 52 UI: Clock Lane HS active after last Data-Lane bit.",
        "ECC injection: inject 1-bit header error → corrected; 2-bit error → detected + dropped.",
        "CRC injection: inject CRC-16 mismatch → reported; payload still consumed (per WC) but flagged.",
        "Eye-diagram on HS pair at minimum and maximum data rate (80 Mbps and 1.5 / 2.5 Gbps).",
        "Frame-sync sequence: FS → LS → Long Packet → LE → ... → FE; verify frame number increments.",
        "LP-Contention: simulate both ends driving conflicting LP states; verify detection.",
    ])
    _write(p, d)


def _l11(gd: Path, ic_name: str) -> None:
    p = gd / "L11_OTP_CONTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    d["otp_present"] = False
    d["notes"] = (
        "MIPI D-PHY / CSI-2 specifications do NOT define any OTP (One-"
        "Time-Programmable) / fuse content at the protocol or physical "
        "layer. CSI-2 packets are wire-level image data and carry no "
        "calibration constants. Vendor-specific data — e.g. per-lane "
        "skew trim, HS swing trim, LP threshold calibration, or PHY PLL "
        "trim — may be stored in an implementation's local OTP / fuse "
        "bank, but those values are entirely per-device-design (Synopsys "
        "/ Cadence / Lattice / silicon-vendor PHY IP each define their "
        "own fuse map). Therefore this item is reported as NOT "
        "APPLICABLE at the MIPI specification level.")
    _write(p, d)


def _l12(gd: Path, ic_name: str) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("frame_transmit_sequence", [
        "1. Source completes any prior burst and forces all lanes to LP-11 (Stop state).",
        "2. Source initiates HS Entry: LP-11 → LP-01 (T-LPX) → LP-00 (T-LPX) → HS-0 (T-HS-PREPARE + T-HS-ZERO) → Sync pattern 8'b00011101.",
        "3. Source transmits FS Short Packet (DI with DT=0x00, Data[15:0] = frame number, ECC).",
        "4. (Optional LS-LE mode) For each line of the frame: Source transmits LS Short Packet (DT=0x02) → Long Packet (header DI+WC+ECC + WC payload bytes + CRC-16 footer) → LE Short Packet (DT=0x03).",
        "5. (Long-Packet-only mode) For each line, just transmit Long Packet without LS/LE.",
        "6. After last line, Source transmits FE Short Packet (DT=0x01).",
        "7. Source executes HS Exit: HS-Trail (≥ max(8 UI, 60+4 UI) ns) → LP-11 (≥ T-HS-EXIT = 100 ns).",
        "8. Lanes return to Stop state until next frame.",
    ])
    d.setdefault("receiver_state_machine_sequence", [
        "1. Sink RX is in RX_LP11_DETECT; both Dp and Dn idle at LP-11.",
        "2. Sink detects LP-11 → LP-01 → LP-00 sequence; recognises HS Request; enables HS termination + comparator.",
        "3. Sink waits T-HS-PREPARE for HS driver settle; locks DDR clock recovery on HS-0 dwell of T-HS-ZERO.",
        "4. Sink hunts for Sync pattern 8'b00011101 (LSB-first 10111000); declares byte-boundary lock on match.",
        "5. Sink samples each Data Lane on both edges of Clock Lane; deinterleaves across N lanes.",
        "6. Sink parses 4-byte header (DI + WC + ECC); ECC corrects 1-bit / detects 2-bit; extracts VC + DT + (WC or Data).",
        "7. If Long Packet: read WC payload bytes; compute CRC-16; compare with 2-byte footer; report mismatch.",
        "8. If Short Packet (DT 0x00..0x0F): packet ends after header; route to FS/FE/LS/LE/generic handler.",
        "9. Repeat 6-8 for next packet until HS Exit detected (HS-Trail + LP-11).",
        "10. Sink returns to RX_LP11_DETECT until next HS Entry.",
    ])
    d.setdefault("escape_mode_sequence", [
        "1. Source initiates LP Escape Entry: LP-11 → LP-10 → LP-00 → LP-00.",
        "2. Source transmits 4-bit escape command (e.g. ULPS=0x1E, Trigger 1/2/3/4, Reset).",
        "3. For ULPS: source holds LP-00 indefinitely; sink enters deep sleep.",
        "4. For Trigger / Reset: source returns to LP-11 immediately after command.",
        "5. ULPS exit: source drives MarkOne (LP-10) for T-WAKEUP (≥ 1 ms); sink wakes; both return to LP-11.",
    ])
    d.setdefault("lane_skew_training_sequence", [
        "1. At HS Entry, all active Data Lanes drive HS-0 together; receiver measures arrival-time skew per lane.",
        "2. Receiver applies per-lane delay-line trim to align all lanes to within ≤ 100 ps inter-pair skew.",
        "3. Sync byte (8'b00011101) is replicated on every active lane; receiver uses Sync as a per-lane byte-boundary marker.",
    ])
    d.setdefault("ecc_recovery_sequence", [
        "1. Receiver computes Hamming(8,4) syndromes over DI + WC[7:0] + WC[15:8].",
        "2. If syndrome = 0: header is clean, proceed.",
        "3. If syndrome != 0 and 1-bit detected: correct the indicated bit, proceed.",
        "4. If syndrome != 0 and 2-bit detected: discard packet; report ECC double-bit-error event.",
        "5. CRC-16 still computed over payload if present; reported independently.",
    ])
    d.setdefault("multi_vc_demux_sequence", [
        "1. Source interleaves packets from different Virtual Channels on the same physical lanes.",
        "2. Each packet's DI byte carries VC[7:6] (or extended VC in v1.2+).",
        "3. Receiver routes packet to per-VC decoder / line buffer based on VC field.",
        "4. Each VC may have its own FS / FE / LS / LE counters maintained by the receiver.",
    ])
    _write(p, d)


def _l13(gd: Path, ic_name: str) -> None:
    p = gd / "L13_LAB_CALIBRATION.json"
    if not p.is_file():
        return
    d = _read(p)
    d["lab_calibration_present"] = True
    d.setdefault("calibration_categories", [
        {"name": "Eye diagram (HS pair)",        "purpose": "Verify HS driver/receiver/channel quality at the target data rate; measure jitter, eye height, eye width, common-mode."},
        {"name": "HS swing trim",                "purpose": "Adjust HS driver current to land in 100-200 mV differential swing across PVT."},
        {"name": "Lane delay-line trim",         "purpose": "Per-lane programmable delay to bring inter-pair skew ≤ 100 ps; usually trained on Sync."},
        {"name": "T-HS-EXIT measurement",        "purpose": "Verify LP-11 dwell ≥ 100 ns after every HS Exit."},
        {"name": "LP rise / fall time",          "purpose": "Confirm LP swing meets 1.2 V CMOS thresholds at target data rate (≤ 10 Mbps)."},
        {"name": "Sync-pattern detection threshold","purpose": "Sweep input voltage / noise to verify receiver locks on 8'b00011101 at minimum margin."},
        {"name": "Clock-Lane PLL lock",           "purpose": "Confirm source PLL hits target DDR frequency = data-rate / 2 within ppm tolerance."},
        {"name": "ECC self-check",                "purpose": "Inject 1-bit / 2-bit errors into header; confirm correction + detection."},
        {"name": "CRC self-check",                "purpose": "Inject CRC-16 mismatch into payload; confirm receiver reports error."},
        {"name": "Vendor sideband I2C config",    "purpose": "Apply per-sensor register config (gain / exposure / ROI / VC / DT / lane count) over I2C before enabling HS payload."},
    ])
    d["notes"] = (
        "MIPI D-PHY is mixed-signal at multi-gigabit; lab characterization "
        "is mandatory for any new sensor / receiver pair. The CSI-2 "
        "protocol layer is digital but inherits PHY-level analog risks. "
        "Sensors expose all settable parameters via the sideband I2C bus, "
        "not via CSI-2 packets themselves.")
    _write(p, d)


def _l14(gd: Path, ic_name: str) -> None:
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f.setdefault("spec_version", "MIPI D-PHY v1.2 + CSI-2 v1.3 (2014)")
    if _empty(f.get("previous_versions")):
        f["previous_versions"] = [
            "D-PHY v0.9 (2007) — initial release; HS up to ~1 Gbps per lane.",
            "D-PHY v1.0 (2009) — first production release; HS / LP definitions locked.",
            "D-PHY v1.1 (2011) — added ULPS clarification; 4 Virtual Channels formalized.",
            "D-PHY v1.2 (2014) — raised HS data-rate ceiling to 2.5 Gbps per lane; 16 Virtual Channels via VC extension.",
            "CSI-2 v1.0 (2005) — initial CSI-2 release on D-PHY v0.9.",
            "CSI-2 v1.1 (2009) — 4 VC; aligned with D-PHY v1.0.",
            "CSI-2 v1.2 (2012) — Added RAW20, scrambling foundation.",
            "CSI-2 v1.3 (2014) — Added RAW24; aligned with D-PHY v1.2.",
        ]
    if _empty(f.get("key_changes")):
        f["key_changes"] = [
            {"version": "D-PHY v1.1", "summary": "ULPS state clarified; 4 VC enumerated; new T-CLK-PRE / T-CLK-POST constraints."},
            {"version": "D-PHY v1.2", "summary": "HS rate up to 2.5 Gbps; 16 VC via VC extension; deskew-pattern framework for >1.5 Gbps."},
            {"version": "CSI-2 v1.2", "summary": "Added RAW20 data type; scrambling concept introduced for EMI reduction."},
            {"version": "CSI-2 v1.3", "summary": "Added RAW24 data type; further scrambling support; aligned with D-PHY v1.2."},
            {"version": "CSI-2 v2.x (later)", "summary": "Added optional scrambling, improved error-handling, more data types."},
        ]
    if _empty(f.get("backward_compat_traps")):
        f["backward_compat_traps"] = [
            {
                "trap_name": "DPHY_v2_C_PHY_confusion",
                "rule": "D-PHY v1.x is differential (Dp/Dn pair); D-PHY v2.x and C-PHY use different signaling (3-phase encoded trio).",
                "trap": "Mixing v1.x D-PHY transmitter with C-PHY receiver yields no signal; sensors must declare which physical layer they use.",
            },
            {
                "trap_name": "vc_field_widened_v1_2",
                "rule": "v1.1 has VC[1:0] (4 channels); v1.2+ widens to VC[3:0] (16 channels) via VC extension byte.",
                "trap": "Older receiver decoding only VC[1:0] will mis-route packets from extended-VC sources; always check spec version.",
            },
            {
                "trap_name": "scrambling_v2",
                "rule": "CSI-2 v2.x introduces optional scrambling for EMI reduction (not for security).",
                "trap": "Receiver must descramble; legacy receivers see garbled payload if scrambling enabled.",
            },
            {
                "trap_name": "sync_pattern_byte_order",
                "rule": "Sync pattern is 8'b00011101 (LSB-first on the wire = 10111000); the spec is bit-LSB-first within each byte.",
                "trap": "Implementations that drive MSB-first see scrambled Sync and never lock.",
            },
            {
                "trap_name": "header_ecc_double_bit_detect_not_correct",
                "rule": "Hamming(8,4) extended ECC corrects 1 bit and detects 2; it does NOT correct 2 bits.",
                "trap": "Optimistic implementations that try to 'correct' a 2-bit error produce silently-wrong DI / WC.",
            },
        ]
    f.setdefault("version_naming_history_note",
                 "MIPI Alliance maintains the D-PHY (physical-layer) and CSI-2 (camera protocol) specifications. DSI (Display Serial Interface) shares the same D-PHY physical layer; D-PHY v2.x and C-PHY are sibling physical layers with different signaling. Modern image sensors increasingly support C-PHY for higher per-trio data rates; this document covers the D-PHY v1.2 + CSI-2 v1.3 family. TI SLLA414 application note is a layout-side companion for high-speed differential routing applicable to D-PHY-class signaling.")
    d["fields"] = f
    _write(p, d)


def _l15(gd: Path, ic_name: str) -> None:
    p = gd / "L15_ENCODING_TABLES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f.setdefault("sync_pattern_encoding", {
        "header_columns": ["Field", "Value", "Notes"],
        "rows": [
            ["Sync byte value (8-bit)",        "8'b00011101", "0x1D in hex"],
            ["Sync on-the-wire order (LSB-first)", "10111000",   "First bit on wire = LSB"],
            ["Sync location",                   "After T-HS-ZERO, before payload", "Marks byte-boundary"],
        ],
    })
    f.setdefault("data_identifier_byte_encoding", {
        "header_columns": ["Bit", "Field", "Description"],
        "rows": [
            ["7:6", "VC (Virtual Channel)",     "0..3 in v1.1; 0..15 via VC extension in v1.2+"],
            ["5:0", "DT (Data Type)",            "Enumerates RAW / YUV / RGB / generic / sync types"],
        ],
    })
    f.setdefault("data_type_enum_table", {
        "header_columns": ["DT (hex)", "Category", "Name"],
        "rows": [
            ["0x00", "Short Sync",  "Frame Start (FS)"],
            ["0x01", "Short Sync",  "Frame End (FE)"],
            ["0x02", "Short Sync",  "Line Start (LS)"],
            ["0x03", "Short Sync",  "Line End (LE)"],
            ["0x08", "Generic Short", "Generic Short Packet code 1"],
            ["0x09", "Generic Short", "Generic Short Packet code 2"],
            ["0x0A", "Generic Short", "Generic Short Packet code 3"],
            ["0x0B", "Generic Short", "Generic Short Packet code 4"],
            ["0x0C", "Generic Short", "Generic Short Packet code 5"],
            ["0x0D", "Generic Short", "Generic Short Packet code 6"],
            ["0x0E", "Generic Short", "Generic Short Packet code 7"],
            ["0x0F", "Generic Short", "Generic Short Packet code 8"],
            ["0x18", "YUV",          "YUV420 8-bit"],
            ["0x19", "YUV",          "YUV420 10-bit"],
            ["0x1A", "YUV",          "YUV420 8-bit Legacy"],
            ["0x1C", "YUV",          "YUV420 8-bit CSPS"],
            ["0x1D", "YUV",          "YUV420 10-bit CSPS"],
            ["0x1E", "YUV",          "YUV422 8-bit"],
            ["0x1F", "YUV",          "YUV422 10-bit"],
            ["0x20", "RGB",          "RGB444"],
            ["0x21", "RGB",          "RGB555"],
            ["0x22", "RGB",          "RGB565"],
            ["0x23", "RGB",          "RGB666"],
            ["0x24", "RGB",          "RGB888"],
            ["0x28", "RAW",          "RAW6"],
            ["0x29", "RAW",          "RAW7"],
            ["0x2A", "RAW",          "RAW8"],
            ["0x2B", "RAW",          "RAW10"],
            ["0x2C", "RAW",          "RAW12"],
            ["0x2D", "RAW",          "RAW14"],
            ["0x30..0x37", "Generic", "User-defined 8-bit data (long packet)"],
        ],
    })
    f.setdefault("ecc_hamming_8_4_table", {
        "header_columns": ["Bit", "Parity Function", "Description"],
        "rows": [
            ["P0", "XOR of bits 0,1,3,4,6,8,10,11,13,15,17,19,21,23", "Hamming parity bit 0"],
            ["P1", "XOR of bits 0,2,3,5,6,9,10,12,13,16,17,20,21",     "Hamming parity bit 1"],
            ["P2", "XOR of bits 1,2,3,7,8,9,10,14,15,16,17,22,23",     "Hamming parity bit 2"],
            ["P3", "XOR of bits 4,5,6,7,8,9,10,18,19,20,21,22,23",     "Hamming parity bit 3"],
            ["P4", "XOR of bits 11,12,13,14,15,16,17,18,19,20,21,22,23","Hamming parity bit 4"],
            ["P5", "XOR of all 24 data bits + P0..P4",                  "Hamming parity bit 5 + extension"],
            ["P6", "extension bit",                                     "Even-parity over P0..P5 (double-bit detect)"],
            ["P7", "extension bit",                                     "Even-parity over all 24 data + 7 parity bits"],
        ],
        "note": "Standard MIPI CSI-2 ECC algorithm — extended Hamming(8,4) over the 24-bit header (DI+WC). Single-bit correct, double-bit detect.",
    })
    f.setdefault("crc_16_polynomial_table", {
        "header_columns": ["Field", "Value"],
        "rows": [
            ["Polynomial",     "x^16 + x^12 + x^5 + 1"],
            ["Polynomial hex", "0x1021"],
            ["Initial value",  "0xFFFF"],
            ["Shift direction","MSB-first"],
            ["Coverage",       "Long Packet payload bytes only (not header)"],
            ["Output order",   "CRC[7:0] first, then CRC[15:8] on the wire (2 bytes appended)"],
        ],
    })
    f.setdefault("lane_state_encoding_table", {
        "header_columns": ["State", "Dp", "Dn", "Meaning"],
        "rows": [
            ["LP-00", "0", "0", "Bridge (HS or Escape entry); also Escape signaling"],
            ["LP-01", "0", "1", "HS Request"],
            ["LP-10", "1", "0", "Escape Request"],
            ["LP-11", "1", "1", "Stop state (idle)"],
            ["HS-0",  "0 (diff)", "1 (diff)", "HS differential zero"],
            ["HS-1",  "1 (diff)", "0 (diff)", "HS differential one"],
        ],
    })
    f.setdefault("vc_range_table", {
        "header_columns": ["Spec Version", "VC width (bits)", "VC count"],
        "rows": [
            ["D-PHY/CSI-2 v1.0", "2", "4"],
            ["D-PHY/CSI-2 v1.1", "2", "4"],
            ["D-PHY/CSI-2 v1.2", "4 (via VC extension)", "16"],
            ["D-PHY/CSI-2 v1.3+", "4 (via VC extension)", "16"],
        ],
    })
    f.setdefault("voltage_levels_table", {
        "header_columns": ["Mode", "Swing", "Termination"],
        "rows": [
            ["HS",  "100-200 mV differential", "100 Ω at sink"],
            ["LP",  "1.2 V single-ended",      "unterminated (high-Z)"],
        ],
    })
    if _empty(f.get("tables")):
        f["tables"] = [
            "Section 5 — D-PHY Lane States (LP-00 / LP-01 / LP-10 / LP-11 / HS-0 / HS-1)",
            "Section 6 — HS Entry / Exit Sequences",
            "Section 7 — Sync Pattern (8'b00011101)",
            "Section 8 — CSI-2 Packet Formats (Long + Short)",
            "Section 9 — Data Identifier (DI = VC + DT) Encoding",
            "Section 10 — Header ECC Algorithm (Hamming 8,4)",
            "Section 11 — Payload CRC-16 (poly 0x1021, init 0xFFFF, MSB-first)",
            "Section 12 — Named D-PHY Timing Parameters",
        ]
    d["fields"] = f
    _write(p, d)


def _l16(gd: Path, ic_name: str) -> None:
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f.setdefault("must_have_properties", [
        "Exactly 1 Clock Lane (differential pair) + 1..4 Data Lanes (differential pairs).",
        "HS mode swing: 100-200 mV differential; 100 Ω termination at sink.",
        "LP mode swing: 1.2 V single-ended CMOS; unterminated.",
        "DDR Clock Lane: data-rate-per-lane = 2 × Clock-Lane Hz; both edges latch one Data-Lane bit.",
        "HS Entry: LP-11 → LP-01 → LP-00 → HS-0 → Sync 8'b00011101 → payload.",
        "HS Exit: payload → HS-Trail → LP-11.",
        "Sync byte 8'b00011101 on every HS Entry, replicated on every active Data Lane.",
        "Header layout: DI (1B) + WC[15:0] (2B) + ECC (1B) for Long Packet; DI + Data[15:0] + ECC for Short Packet.",
        "Header ECC: extended Hamming(8,4) — must correct 1 bit, must detect 2 bits.",
        "Payload CRC-16: polynomial 0x1021 (x^16+x^12+x^5+1), init 0xFFFF, MSB-first, covers payload only.",
        "Multi-lane byte interleave: byte k → lane (k mod N).",
        "Inter-pair skew across lanes ≤ 100 ps; intra-pair Dp/Dn skew ≤ 5 ps.",
        "T-CLK-PRE ≥ 8 UI; T-CLK-POST ≥ 60 + 52 UI.",
        "T-HS-PREPARE / T-HS-ZERO / T-HS-TRAIL within D-PHY v1.x bounds.",
        "Frame sync: FS Short Packet (DT=0x00) at frame start; FE Short Packet (DT=0x01) at frame end.",
        "Stop state LP-11 ≥ T-HS-EXIT (100 ns) after every HS Exit.",
    ])
    f.setdefault("must_not_have_properties", [
        "Mixing D-PHY v1.x (differential pair) with C-PHY (3-phase trio) — incompatible.",
        "Driving HS mode without 100 Ω sink termination (eye collapses).",
        "Sending Sync MSB-first (must be LSB-first on the wire).",
        "Attempting to 'correct' a 2-bit header ECC error (only 1-bit correction is valid).",
        "Computing CRC-16 over the header (CRC covers payload only).",
        "Using AC coupling on D-PHY lines (DC-coupled only).",
        "Driving both ends of a Data Lane in HS simultaneously (point-to-point only).",
    ])
    f.setdefault("compliance_failure_modes", [
        {"mode": "Sync miss-lock",          "trigger": "Receiver did not find 8'b00011101 within HS-Zero window → entire burst lost."},
        {"mode": "ECC double-bit error",    "trigger": "2-bit error detected in header → packet dropped."},
        {"mode": "CRC-16 mismatch",         "trigger": "Payload corruption; reported to upper layer; NOT retransmitted."},
        {"mode": "Lane-skew exceeded",      "trigger": "Inter-pair skew > 100 ps → de-interleave misalignment → ECC/CRC failures."},
        {"mode": "T-HS-* timing violation", "trigger": "T-HS-PREPARE / T-HS-ZERO / T-HS-TRAIL out of spec → per-lane bit errors."},
        {"mode": "LP-Contention",           "trigger": "Both endpoints drive conflicting LP states."},
        {"mode": "False EoT",               "trigger": "HS-Trail not present or LP-11 not asserted after HS Exit."},
    ])
    f.setdefault("min_clock_constraint",
                 "Implementation-defined PHY PLL — typically ≥ 40 MHz Clock Lane (80 Mbps data rate); max 1.25 GHz Clock Lane (2.5 Gbps data rate, D-PHY v1.2).")
    f.setdefault("reset_behavior_compliance",
                 "On power-on or LP-escape Reset: both ends drive LP-11 Stop state; source initiates next HS Entry when ready; no protocol-level state survives reset.")
    d["fields"] = f
    _write(p, d)


def _l17(gd: Path, ic_name: str) -> None:
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["channels"] = [
        {"name": "CLK_P",   "direction_source": "output (HS)", "direction_sink": "input",  "purpose": "Differential Clock Lane positive; DDR — both edges latch one Data-Lane bit.", "active_levels": "HS differential 100-200 mV; LP 1.2 V single-ended", "idle_level": "LP-11 (HIGH); HS-0 in Continuous Clock Mode"},
        {"name": "CLK_N",   "direction_source": "output (HS)", "direction_sink": "input",  "purpose": "Differential Clock Lane negative."},
        {"name": "DAT0_P",  "direction_source": "output (HS) / I/O (LP)", "direction_sink": "input (HS) / I/O (LP)", "purpose": "Differential Data Lane 0 positive; carries CSI-2 packet bytes during HS.", "active_levels": "HS 100-200 mV diff; LP 1.2 V", "idle_level": "LP-11"},
        {"name": "DAT0_N",  "direction_source": "output (HS) / I/O (LP)", "direction_sink": "input (HS) / I/O (LP)", "purpose": "Differential Data Lane 0 negative."},
        {"name": "DAT1_P / DAT1_N (optional)", "direction_source": "same as DAT0", "purpose": "Data Lane 1 — present when N_data_lanes ≥ 2."},
        {"name": "DAT2_P / DAT2_N (optional)", "direction_source": "same as DAT0", "purpose": "Data Lane 2 — present when N_data_lanes ≥ 3."},
        {"name": "DAT3_P / DAT3_N (optional)", "direction_source": "same as DAT0", "purpose": "Data Lane 3 — present when N_data_lanes = 4."},
    ]
    f["logical_signaling_levels"] = [
        {"name": "LP-00", "Dp": "0", "Dn": "0", "meaning": "Bridge state before HS or Escape entry"},
        {"name": "LP-01", "Dp": "0", "Dn": "1", "meaning": "HS Request"},
        {"name": "LP-10", "Dp": "1", "Dn": "0", "meaning": "Escape Request / ULPS Mark"},
        {"name": "LP-11", "Dp": "1", "Dn": "1", "meaning": "Stop state (idle)"},
        {"name": "HS-0",  "Dp": "diff-LOW",  "Dn": "diff-HIGH", "meaning": "HS differential 0"},
        {"name": "HS-1",  "Dp": "diff-HIGH", "Dn": "diff-LOW",  "meaning": "HS differential 1"},
    ]
    f["packet_types_summary"] = [
        {"class": "Long Packet",  "members": ["RAW8/10/12/14", "YUV420/422-8/10", "RGB444/555/565/666/888", "generic 0x30..0x37"], "count_approx": 22},
        {"class": "Short Packet", "members": ["FS (DT=0x00)", "FE (DT=0x01)", "LS (DT=0x02)", "LE (DT=0x03)", "generic 0x08..0x0F"], "count_approx": 12},
    ]
    f["channel_counts"] = {
        "external_wire_count":          "2 + 2 × N_data_lanes (N=1..4); 4..10 pins.",
        "differential_pairs":           "1 Clock + N Data (N=1..4); 2..5 pairs.",
        "max_devices_per_link":         1,
        "max_VC_v1_1":                  4,
        "max_VC_v1_2_plus":             16,
        "packet_types_total_approx":   34,
        "sideband_buses":               "1 (I2C / SCCB) — separate from CSI-2 wires.",
    }
    f["global_signals"] = []
    f.setdefault("ordering_rules", {
        "bit_order_within_byte":  "LSB-first on the wire (bit 0 first, bit 7 last).",
        "byte_order_within_header": "DI (byte 0) → WC[7:0] (byte 1) → WC[15:8] (byte 2) → ECC (byte 3); little-endian over the wire.",
        "byte_order_within_crc":    "CRC[7:0] first, then CRC[15:8] appended; CRC computed MSB-first over payload.",
        "multilane_byte_order":     "byte k → lane (k mod N); Sync byte replicated on every active lane.",
        "tx_rx_simultaneity":       "Source → sink during HS payload; bidirectional during LP escape; never both HS-driving at the same time.",
    })
    # Force-overwrite dependency_graph for MIPI shape.
    f["dependency_graph"] = {
        "common_rule": "Source drives Clock Lane (DDR) and all Data Lanes during HS; sink only receives HS. Both endpoints can drive LP states for escape signaling.",
        "data_dependency": "Each Data-Lane bit is sampled on a Clock-Lane edge (both edges, DDR). Header ECC validates DI+WC; payload CRC-16 validates payload.",
    }
    f["handshake_pairs"] = [
        {"name": "HS_ENTRY",       "from": "source", "to": "sink",  "rule": "LP-11 → LP-01 → LP-00 → HS-0 → Sync 8'b00011101; sink locks byte boundary on Sync."},
        {"name": "HS_EXIT",        "from": "source", "to": "sink",  "rule": "Payload → HS-Trail (≥ max(8UI, 60+4UI) ns) → LP-11."},
        {"name": "ESCAPE_REQUEST", "from": "either", "to": "other", "rule": "LP-11 → LP-10 → LP-00 → escape pattern."},
        {"name": "ULPS_ENTRY",     "from": "source", "to": "sink",  "rule": "Escape command code (e.g. 0x1E) → LP-00 held indefinitely."},
        {"name": "ULPS_EXIT",      "from": "source", "to": "sink",  "rule": "LP-10 (MarkOne) for ≥ T-WAKEUP (1 ms) → LP-11."},
    ]
    d["fields"] = f
    _write(p, d)


def _l18(gd: Path, ic_name: str) -> None:
    p = gd / "L18_INTERCONNECT_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["topology_type"] = "Point-to-point only — 1 source (sensor / display TX / serializer) ↔ 1 sink (application processor / ISP / deserializer) per physical interface. No bus, no daisy chain, no multi-drop."
    f["supported_topologies"] = [
        {"name": "Single source ↔ single sink", "description": "Canonical CSI-2 link; one camera module to one host."},
        {"name": "Multi-stream via Virtual Channel", "description": "One physical D-PHY interface carries up to 4 (v1.1) / 16 (v1.2+) Virtual Channels; allows time-multiplexing of multiple logical sources."},
        {"name": "External MIPI aggregator / serializer", "description": "Some vendors offer aggregators (e.g. multi-camera-to-one-CSI-2) but the physical CSI-2 link itself is still point-to-point."},
    ]
    f["master_slave_role_summary"] = [
        {"role": "Source",     "description": "Image sensor / display TX / serializer; drives Clock Lane DDR + Data Lane HS payload; initiates HS Entry / Exit."},
        {"role": "Sink",       "description": "Application processor / ISP / deserializer; receives HS payload; decodes CSI-2 packets; may participate in LP escape (e.g. ULPS exit handshake)."},
        {"role": "Sideband Controller", "description": "I2C / SCCB master (on the host SoC side) that configures the sensor over a SEPARATE bus — gain, exposure, ROI, VC/DT/lane-count select."},
    ]
    f["interconnect_role"] = (
        "There is no protocol-layer router or hub. The link is a flat "
        "point-to-point pair (Clock Lane + N Data Lanes). Aggregation "
        "across multiple cameras happens at the host SoC's multi-port "
        "CSI-2 RX subsystem, not on the D-PHY wires.")
    f["ordering_guarantees"] = {
        "within_a_packet":     "Bytes transmitted byte-0 first; within each byte, LSB-first on the wire.",
        "within_a_frame":      "FS at start → LS+Long+LE per line → FE at end; receiver enforces ordering via DT field.",
        "across_VCs":          "VCs interleave at packet boundary; no ordering between VCs.",
        "across_lanes":        "byte k → lane (k mod N); receiver de-interleaves by lane index and timestamps with Clock-Lane edges.",
    }
    f.setdefault("memory_vs_peripheral_regions",
                 "Not applicable — CSI-2 is a streaming protocol; no addressable memory or register region on the CSI-2 wires themselves. Sensor registers live on the sideband I2C bus.")
    f.setdefault("device_classification", {
        "image_sensor":            "Source; drives Clock Lane + Data Lane HS payload.",
        "display_panel":           "Source (when using DSI which shares D-PHY); drives Clock + Data HS payload toward the panel.",
        "application_processor":   "Sink; integrates CSI-2 RX + DSI TX subsystems.",
        "ISP / image processor":   "Sink; consumes CSI-2 packets; may include de-Bayer, color, etc.",
        "MIPI bridge / serializer":"Both source and sink; converts MIPI-CSI-2 to other formats (e.g. GMSL, FPD-Link).",
    })
    f.setdefault("max_link_length", {
        "PCB_trace_cm_at_400Mbps":   30,
        "PCB_trace_cm_at_1500Mbps":  10,
        "FFC_cable_cm_typical":      20,
    })
    f.setdefault("default_signal_values_evidence_tables", [
        "Section 5 — D-PHY Lane Configuration",
        "Section 6 — CSI-2 Packet Layer",
        "Section 7 — Virtual Channel Multiplexing",
        "Section 8 — Frame / Line Sync Sequence",
    ])
    d["fields"] = f
    _write(p, d)


def _l19(gd: Path, ic_name: str) -> None:
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["constraints_present"] = True
    f.setdefault("pcb_constraints", {
        "differential_pair_impedance_ohm": 100,
        "differential_pair_impedance_tolerance_pct": 10,
        "intra_pair_skew_ps_max":            5,
        "inter_pair_skew_ps_max":            100,
        "max_trace_length_cm_at_low_rate":   30,
        "max_trace_length_cm_at_high_rate":  10,
        "AC_coupling":                       "NOT used — D-PHY is DC-coupled differential",
        "common_mode_choke":                 "Not recommended; degrades HS eye",
        "ESD_protection_class":              "HBM 2 kV minimum (Class 2); diodes placed close to connector",
    })
    f.setdefault("pad_constraints", {
        "HS_termination_internal_ohm":   100,
        "HS_swing_diff_mV_target":       [100, 200],
        "LP_swing_V_target":             1.2,
        "ESD_clamp_present":             True,
        "shared_HS_LP_pad":              "Same Dp/Dn pair carries both modes; lane-state controller arbitrates",
    })
    f.setdefault("sdc_floorplan_hints", {
        "Clock_Lane_PLL_placement":     "Close to source pads; minimize jitter.",
        "Per_lane_delay_line_placement":"Close to receiver pads; programmable for deskew.",
        "Sync_hunter_placement":        "Receiver-side; pipelined to meet Clock-Lane DDR rate.",
    })
    f["notes"] = (
        "Although the MIPI D-PHY / CSI-2 specs don't enforce PDK "
        "constraints per se, the PCB-level differential routing rules "
        "(100 Ω, ≤ 5 ps intra-pair, ≤ 100 ps inter-pair, DC-coupled) "
        "are essential to meet HS eye at multi-gigabit. TI's SLLA414 "
        "application note provides general high-speed differential "
        "layout guidelines (impedance, skew, via stubs, reference "
        "planes) that apply directly to D-PHY routing.")
    d["fields"] = f
    _write(p, d)


def _l20(gd: Path, ic_name: str) -> None:
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["dft_present"] = "partial"
    f.setdefault("internal_diagnostics", [
        "In-band error reporting via ECC (1-bit correct / 2-bit detect) and CRC-16 (payload mismatch).",
        "Sync-pattern miss-lock detector reports loss of receiver alignment.",
        "Lane-skew calibration during HS Entry trains per-lane delay-lines.",
        "FS / FE / LS / LE short-packet counters validate frame completeness.",
    ])
    f.setdefault("scan_topology", {
        "standard_scan_chain_present": False,
        "JTAG_present_at_protocol_layer": False,
        "vendor_BIST_extensions": "Some commercial CSI-2 RX IP cores (e.g. Synopsys, Cadence) add MIPI CSI-2 BIST and PHY loopback test modes, but these are NOT part of the MIPI D-PHY / CSI-2 specs.",
    })
    f["notes"] = (
        "MIPI D-PHY / CSI-2 specs do NOT define standard scan or JTAG. "
        "Debug relies on in-band integrity: Sync pattern lock, ECC "
        "syndrome, CRC-16. Production characterization uses eye "
        "diagrams + PHY conformance tests (MIPI Alliance test suite). "
        "Vendor PHY IP commonly adds optional BIST modes, loopback "
        "paths, and eye-monitor circuitry — these are per-"
        "implementation.")
    d["fields"] = f
    _write(p, d)


def _l21(gd: Path, ic_name: str) -> None:
    p = gd / "L21_POWER_INTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["power_intent_present"] = True
    f["low_power_modes_summary"] = {
        "HS_active":         "HS payload streaming on Data Lanes + DDR Clock Lane; consumes the most current (typ ~10× LP).",
        "LP_active":         "Low-Power signaling (≤ 10 Mbps); ~10% of HS current; used for escape and inter-burst Stop state.",
        "Stop_state_LP11":   "Both Dp and Dn driven HIGH (1.2 V CMOS); near-static; minimal current.",
        "ULPS":              "Ultra-Low Power State; lane held LP-00 indefinitely; receiver in deep sleep; lowest current state.",
        "Non_Continuous_Clock_Mode": "Clock Lane returns to LP-11 between bursts to save clock-tree power.",
    }
    f.setdefault("current_estimates", {
        "HS_per_lane_mA_typ":    8,
        "LP_per_lane_mA_typ":    1,
        "Stop_LP11_per_lane_uA": 100,
        "ULPS_per_lane_uA":      10,
    })
    f.setdefault("ulps_specification", {
        "entry_command_byte":   "0x1E (LP escape ULPS command)",
        "exit_signaling":       "Source drives LP-10 (MarkOne) for ≥ T-WAKEUP (1 ms minimum); both ends return to LP-11.",
        "minimum_duration":     "Unbounded — can stay in ULPS indefinitely for deep sleep.",
    })
    f.setdefault("power_classes_of_implementations", [
        "Mobile camera sensor — aggressive Non-Continuous Clock + ULPS for battery life.",
        "Automotive surround camera — Continuous Clock + permanent HS streaming for low latency.",
        "Display panel TX (DSI) — similar power options; uses same D-PHY power modes.",
    ])
    f["notes"] = (
        "MIPI D-PHY explicitly specifies power modes (HS / LP / Stop / "
        "ULPS) AS PART OF THE PROTOCOL because mobile devices require "
        "fine-grained power gating. ULPS is the protocol-defined deep-"
        "sleep state and is critical to camera-module battery life. "
        "Continuous vs Non-Continuous Clock Mode is also a power-vs-"
        "latency trade-off the integrator chooses per application.")
    d["fields"] = f
    _write(p, d)


def _l22(gd: Path, ic_name: str) -> None:
    p = gd / "L22_VERIFICATION_PLAN.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["verification_plan_present"] = "implicit"
    f.setdefault("verification_categories_derived_from_spec", [
        "HS-LP-HS round-trip — source enters HS, transmits payload, exits HS, returns to LP-11.",
        "All Data Type enumeration — RAW6/7/8/10/12/14, YUV420/422-8/10, RGB444/555/565/666/888, generic 0x30..0x37, sync 0x00..0x03, generic short 0x08..0x0F.",
        "Sync-pattern lock — receiver locks on 8'b00011101 (LSB-first 10111000) at every HS Entry.",
        "Sync-pattern miss-lock — inject Sync error; verify burst discarded.",
        "Header ECC single-bit correct — inject 1-bit error; verify auto-correction.",
        "Header ECC double-bit detect — inject 2-bit error; verify packet dropped.",
        "Payload CRC-16 correct — verify CRC matches across multi-byte payloads.",
        "Payload CRC-16 mismatch — inject CRC error; verify reporting (no retry).",
        "ULPS entry — escape command 0x1E; verify both ends in LP-00 deep sleep.",
        "ULPS exit — source drives LP-10 ≥ T-WAKEUP; verify both ends return to LP-11.",
        "Multi-lane byte interleave — verify N=1, N=2, N=3, N=4 configurations.",
        "Multi-lane skew tolerance — train per-lane delay-lines; verify ≤ 100 ps inter-pair skew handled.",
        "Multi-VC demux — interleave packets from 2..16 VCs; verify routing per DI[7:6] (or extension).",
        "FS / FE frame counter — verify FS and FE pairs match per frame; verify frame-number increment.",
        "LS / LE optional — verify both with and without LS/LE per frame.",
        "Continuous Clock Mode — Clock Lane stays HS; verify Data Lanes alternate HS/LP.",
        "Non-Continuous Clock Mode — Clock Lane returns LP-11 between bursts.",
        "T-LPX / T-HS-PREPARE / T-HS-ZERO / T-HS-TRAIL bounds — sweep at min, typ, max.",
        "T-CLK-PRE ≥ 8 UI / T-CLK-POST ≥ 60 + 52 UI bounds.",
        "LP-Contention — both ends drive conflicting LP; verify detection.",
        "Eye-diagram on HS pair at min (80 Mbps) and max (1.5 / 2.5 Gbps) data rate.",
    ])
    f["notes"] = (
        "The MIPI Alliance Conformance Test Suite (CTS) provides a "
        "formal verification programme; this list captures the design-"
        "time verification categories derivable from the D-PHY + CSI-2 "
        "specs themselves.")
    d["fields"] = f
    _write(p, d)


def _l23(gd: Path, ic_name: str) -> None:
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["security_requirements_present"] = False
    f.setdefault("anti_corruption_mechanisms", [
        "Header ECC: extended Hamming(8,4); single-bit-correct, double-bit-detect over DI + WC.",
        "Payload CRC-16: polynomial 0x1021, init 0xFFFF, MSB-first; reports payload corruption (no retry).",
        "Sync-pattern lock: receiver only consumes payload after matching 8'b00011101.",
        "Scrambling (CSI-2 v2.x optional): EMI-reduction scrambler over payload bytes — NOT cryptographic.",
    ])
    f["notes"] = (
        "MIPI D-PHY (physical layer) and CSI-2 (camera protocol) provide "
        "NO confidentiality, integrity-against-tampering, or "
        "authentication features. The wire-level ECC + CRC-16 are noise "
        "/ bit-error mitigations only. CSI-2 v2.x scrambling is for EMI "
        "reduction, NOT for cryptographic protection. Application-layer "
        "security (e.g. HDCP for protected display content over DSI / "
        "HDMI, DRM for protected video) is layered above CSI-2 / DSI "
        "and is NOT part of the D-PHY or CSI-2 specifications. For "
        "automotive / industrial use cases that require tamper-evident "
        "or authenticated camera streams, vendors layer their own "
        "secure-CSI-2 extensions (e.g. encryption-at-rest, signed-"
        "frame proofs) on top of the standard packet stream.")
    d["fields"] = f
    _write(p, d)


# ----- public entry ---------------------------------------------------------

def apply_mipi_synth(generated_docs_dir, is_mipi: bool,
                     mipi_ic_name: Optional[str]) -> None:
    """Apply MIPI D-PHY / CSI-2-specific synth when the structural
    signature matched."""
    if not is_mipi:
        return
    gd = Path(generated_docs_dir)

    # Force ic_name across the 14 main L docs (L1-L23).
    if mipi_ic_name is not None:
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
                d["ic_name"] = mipi_ic_name
                _write(q, d)

    # Per-layer overlays.
    name = mipi_ic_name or "MIPI D-PHY / CSI-2"
    _l1(gd, name)
    _l2(gd, name)
    _l3(gd, name)
    _l4(gd, name)
    _l5(gd, name)
    _l6(gd, name)
    _l7(gd, name)
    _l8_rtl(gd, name)
    _l8_timing(gd, name)
    _l9(gd, name)
    _l10(gd, name)
    _l11(gd, name)
    _l12(gd, name)
    _l13(gd, name)
    _l14(gd, name)
    _l15(gd, name)
    _l16(gd, name)
    _l17(gd, name)
    _l18(gd, name)
    _l19(gd, name)
    _l20(gd, name)
    _l21(gd, name)
    _l22(gd, name)
    _l23(gd, name)
