"""VESA DisplayPort (DP) protocol synth helper.

v0.1.91 — ic_class-gated overlay for display-interface specs that exhibit the
DisplayPort structural signature: a VESA digital display interface that carries
isochronous video from a Source to a Sink over a Main Link (1/2/4 self-clocked
AC-coupled differential lanes, 8b/10b for RBR/HBR/HBR2/HBR3 and 128b/132b for
UHBR), managed by a bidirectional half-duplex AUX channel (Manchester-II native
AUX transactions into the DPCD register space + I2C-over-AUX for EDID), with a
two-phase Link Training (Clock-Recovery + Channel-Equalization, voltage-swing /
pre-emphasis), Main Stream Attributes (MSA), Transfer Units (TU), the
micro-packet stream, Multi-Stream Transport (MST), and HDCP/FEC/DSC. Applies
VESA DisplayPort Standard (DP 1.4a / 2.0 / 2.1) spec-canonical content to
L1-L23.

Doctrine — GENERAL not keyword: detection (``is_displayport``) uses canonical
STRUCTURAL wire-level signatures (Main Link lanes + RBR/HBR/HBR2/HBR3 rate
vocabulary + a bidirectional AUX channel + the DPCD register space + two-phase
CR/EQ Link Training) read ONLY from the L-doc CONTENT blob. It NEVER reads the
input-document filename or the benchmark folder name.

Sibling MUTEX — DisplayPort is in the digital-display family with HDMI (TMDS)
and MIPI-DSI (D-PHY). Those siblings can superficially match a "display
interface" intent, so ``is_displayport`` REQUIRES the DisplayPort-only
vocabulary that HDMI and DSI lack:

  * HDMI / DVI uses TMDS (Transition-Minimized Differential Signaling), a CEC
    control line, and an I2C DDC channel — it has NO AUX channel, NO DPCD, NO
    two-phase CR/EQ link training, and NO RBR/HBR rate names. ``is_displayport``
    therefore DEFERS when the doc is HDMI-primary (TMDS present while AUX/DPCD
    are absent).
  * MIPI-DSI uses the D-PHY (HS / LP escape-mode lane distribution), not a Main
    Link with AUX/DPCD. ``is_displayport`` DEFERS when the doc is DSI-primary
    (D-PHY / escape-mode present while Main-Link/AUX are absent).

Sibling collision note: a base-doc synth (e.g. USB4, because DP 2.1 mentions
"alignment with USB4") may fire first and populate the L-docs with the sibling's
values. Because DisplayPort is a DIFFERENT protocol, this module FORCE-OVERWRITES
(direct assignment, NOT setdefault) every L1-L23 key with the DisplayPort
canonical value, and the runner calls ``apply_displayport_synth`` LAST so the
DisplayPort overwrites win.

SIGNATURE (the runner wires this; evaluated on the L1/L2/L3 content blob,
never on a filename) — see ``is_displayport`` below.

Public entry: ``apply_displayport_synth(generated_docs_dir, is_displayport,
displayport_ic_name)``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import l_doc_generator_stamp as _stamp


def _empty(v) -> bool:
    return v in (None, {}, []) or (isinstance(v, str) and not v.strip())


def _ensure_dict(d: dict, key: str) -> dict:
    """Return d[key] as a dict, replacing a pre-existing None/empty/non-dict."""
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

# Canonical DisplayPort structural facts (VESA DP 1.4a / 2.0 / 2.1).
_LANE_COUNTS = [1, 2, 4]
_RATES_8B10B = {
    "RBR": 1.62, "HBR": 2.70, "HBR2": 5.40, "HBR3": 8.10,
}
_RATES_UHBR = {
    "UHBR10": 10.0, "UHBR13.5": 13.5, "UHBR20": 20.0,
}


# ----------------------------------------------------------------------
# Detector — content-only, sibling-MUTEX vs HDMI (TMDS) and MIPI-DSI (D-PHY).
# ----------------------------------------------------------------------
def is_displayport(blob: str) -> bool:
    """VESA DisplayPort — Source/Sink digital display interface.

    Content-only structural signature. MUTEX defers when the doc is HDMI-primary
    (TMDS without AUX/DPCD) or MIPI-DSI-primary (D-PHY/escape-mode without
    Main-Link/AUX).
    """
    if not blob:
        return False
    low = blob.lower()

    # --- DisplayPort-only structural tokens ---
    has_main_link = "main link" in low
    has_aux = "aux ch" in low or "aux channel" in low or "i2c-over-aux" in low
    has_dpcd = "dpcd" in low or "displayport configuration data" in low
    has_cr_eq = (
        ("clock recovery" in low or "clock-recovery" in low)
        and ("channel equalization" in low or "channel-equalization" in low)
    ) or ("link training" in low and "training_pattern_set" in low)
    has_rate_vocab = (
        ("rbr" in low and "hbr" in low)
        or "hbr2" in low or "hbr3" in low
        or ("link_bw_set" in low)
    )

    # The DisplayPort signature: a Main Link + AUX + DPCD + CR/EQ training +
    # the RBR/HBR rate vocabulary. Require the core trio (Main Link + AUX +
    # DPCD) plus at least one of the DP-only discriminators (CR/EQ training or
    # the RBR/HBR rate vocabulary) so neither HDMI nor DSI can satisfy it.
    dp_signature = (
        has_main_link and has_aux and has_dpcd
        and (has_cr_eq or has_rate_vocab)
    )
    if not dp_signature:
        return False

    # --- Sibling MUTEX ---
    # HDMI-primary: TMDS present and AUX/DPCD absent (DisplayPort never uses
    # TMDS; HDMI never uses AUX/DPCD). If the DP signature is present the doc is
    # DP, but guard against a TMDS-only doc that lacks AUX/DPCD.
    hdmi_primary = ("tmds" in low) and (not has_aux) and (not has_dpcd)
    if hdmi_primary:
        return False
    # MIPI-DSI-primary: D-PHY / escape-mode lane distribution present while the
    # DisplayPort Main-Link / AUX are absent.
    dsi_primary = (
        ("d-phy" in low or "escape mode" in low or "escape-mode" in low)
        and (not has_main_link)
        and (not has_aux)
    )
    if dsi_primary:
        return False

    return True


def apply_displayport_synth(generated_docs_dir: Path, is_displayport: bool,
                            displayport_ic_name: Optional[str]) -> None:
    """Apply VESA DisplayPort synth when the DisplayPort signature matched.

    FORCE-OVERWRITES (direct assignment) every L1-L23 key a sibling base-doc
    synth (e.g. USB4, fired by the DP 2.1 "alignment with USB4" mention) may
    have populated, with the DisplayPort-canonical value. The runner calls this
    LAST so the DisplayPort overwrites win.
    """
    if not is_displayport:
        return
    gd = Path(generated_docs_dir)

    # --- Force ic_name across ALL 24 docs FIRST (main + fields docs). ---
    if displayport_ic_name is not None:
        for n in _MAIN_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                d["ic_name"] = displayport_ic_name
                _write(q, d)
        for n in _FIELDS_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                f = _ensure_dict(d, "fields")
                f["ic_name"] = displayport_ic_name
                d["ic_name"] = displayport_ic_name  # belt-and-braces top-level
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
# L1 — DisplayPort datasheet header + Main Link / AUX / rate facts.
# ----------------------------------------------------------------------
def _l1(gd: Path) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    d["document_title"] = "VESA DisplayPort (DP) Standard"
    d["version"] = "DP 1.4a / 2.0 / 2.1"
    d["revised_date"] = "2018 (1.4a) / 2019 (2.0) / 2022 (2.1)"
    d["manufacturer"] = "Video Electronics Standards Association (VESA)"
    d["copyright"] = "© VESA"
    d["abstract"] = (
        "DisplayPort (DP) is a VESA digital display interface that carries "
        "isochronous video and audio from a Source (e.g. a GPU) to a Sink "
        "(e.g. a monitor/panel) over three functional channels: a Main Link "
        "(1/2/4 self-clocked AC-coupled differential lanes carrying the "
        "micro-packet video stream), a bidirectional half-duplex AUX channel "
        "(Manchester-II native AUX transactions into the sink's DPCD register "
        "space plus I2C-over-AUX for EDID), and Hot Plug Detect (HPD). The "
        "Main Link runs at RBR 1.62, HBR 2.7, HBR2 5.4, or HBR3 8.1 Gbps/lane "
        "with 8b/10b coding; DP 2.0/2.1 adds the UHBR tier (UHBR10/13.5/20 "
        "Gbps/lane) with 128b/132b coding and mandatory FEC. The Source trains "
        "the Main Link in two phases — Clock Recovery (CR) and Channel "
        "Equalization (EQ) — adjusting per-lane voltage swing and "
        "pre-emphasis. The stream is framed as micro-packets with Main Stream "
        "Attributes (MSA) and Transfer Units (TU). DisplayPort supports "
        "Single-Stream (SST) and Multi-Stream Transport (MST), and carries "
        "HDCP content protection, FEC, and Display Stream Compression (DSC).")
    d["keywords"] = [
        "DisplayPort", "DP", "VESA", "Main Link", "AUX channel", "DPCD",
        "EDID", "I2C-over-AUX", "link training", "Clock Recovery",
        "Channel Equalization", "voltage swing", "pre-emphasis", "RBR", "HBR",
        "HBR2", "HBR3", "UHBR", "8b/10b", "128b/132b", "MSA", "Transfer Unit",
        "micro-packet", "MST", "HDCP", "FEC", "DSC", "HPD", "Source", "Sink",
    ]
    d["external_pins"] = [
        "ML_Lane0(+/-), ML_Lane1(+/-), ML_Lane2(+/-), ML_Lane3(+/-) — four "
        "Main Link differential pairs (AC-coupled, self-clocked, embedded "
        "clock; 1/2/4 lanes used)",
        "AUX_CH(+/-) — one bidirectional half-duplex differential pair "
        "(Manchester-II, 1 Mbps) for DPCD / link-training / I2C-over-AUX / "
        "MST-sideband / HDCP",
        "HPD — Hot Plug Detect, single-ended sideband input to the Source "
        "(plug presence + IRQ_HPD events)",
        "CONFIG1 / CONFIG2 — connector configuration / cable-orientation pins",
        "DP_PWR (3.3 V), GND — auxiliary power and ground",
    ]
    d.pop("external_pin_count", None)
    d["external_main_link_lanes_max"] = 4
    d["supported_lane_counts"] = list(_LANE_COUNTS)
    d["supported_link_rates_Gbps_per_lane"] = {
        "RBR": 1.62, "HBR": 2.70, "HBR2": 5.40, "HBR3": 8.10,
        "UHBR10": 10.0, "UHBR13.5": 13.5, "UHBR20": 20.0,
    }
    d["modes_of_operation"] = [
        {"name": "Single-Stream Transport (SST)",
         "description": "Default mode — one video stream to one Sink over the "
         "Main Link."},
        {"name": "Multi-Stream Transport (MST)",
         "description": "Multiple independent video streams to multiple Sinks "
         "through a branch device / daisy chain, using virtual channels and a "
         "64-slot time-slot allocation (negotiated via MSTM_CTRL)."},
        {"name": "8b/10b legacy rates (RBR/HBR/HBR2/HBR3)",
         "description": "1.62 / 2.7 / 5.4 / 8.1 Gbps/lane with ANSI 8b/10b "
         "coding (80% efficiency) and LFSR scrambling."},
        {"name": "UHBR (DP 2.0/2.1)",
         "description": "UHBR10/13.5/20 Gbps/lane with 128b/132b coding "
         "(~96.97% efficient); FEC mandatory."},
    ]
    d["key_features"] = [
        "VESA digital display interface: Source-to-Sink isochronous video/"
        "audio over a packetized Main Link.",
        "Three functional channels: Main Link (data), AUX channel "
        "(bidirectional half-duplex management), Hot Plug Detect (HPD).",
        "Main Link: 1, 2, or 4 self-clocked AC-coupled differential lanes "
        "(ML_Lane0..3); embedded clock recovered during training (no separate "
        "clock lane).",
        "Link rates RBR 1.62 / HBR 2.7 / HBR2 5.4 / HBR3 8.1 Gbps/lane (8b/10b)"
        "; DP 2.0/2.1 UHBR10/13.5/20 Gbps/lane (128b/132b).",
        "Two-phase Link Training: Clock Recovery (CR) then Channel "
        "Equalization (EQ), with 4 voltage-swing and 4 pre-emphasis levels, "
        "driven over AUX (TRAINING_PATTERN_SET / status readback).",
        "AUX channel: Manchester-II bi-phase, ~1 Mbps, request/reply native "
        "AUX transactions (4-bit command, 20-bit address, length) into the "
        "DPCD register space.",
        "I2C-over-AUX tunnels I2C to read the Sink EDID (I2C address A0h) and "
        "legacy I2C peripherals; MOT bit chains multi-byte bursts.",
        "DPCD (DisplayPort Configuration Data): Receiver-Capability / "
        "Link-Configuration / Link-Status register fields.",
        "Micro-packet stream: Main Stream Attributes (MSA per frame, Mvid/"
        "Nvid), Transfer Units (TU), BS/BE blanking framing, secondary-data "
        "(audio/SDP) packets.",
        "Single-Stream (SST) and Multi-Stream Transport (MST) with virtual "
        "channels + Sideband MSG over AUX.",
        "Content protection (HDCP 1.3 / 2.2-2.3), Forward Error Correction "
        "(FEC, required with DSC and for UHBR), and Display Stream Compression "
        "(DSC).",
    ]
    d["topology_summary"] = (
        "Point-to-point Source -> Sink over the Main Link (uni-directional "
        "video) and a bidirectional AUX channel for management. MST extends "
        "this to a tree of Sinks via branch devices (hubs / daisy chain), each "
        "stream assigned a virtual channel and a share of the 64 MST time "
        "slots.")
    d["package_summary"] = (
        "DisplayPort is an interface standard, not a single packaged IC; it "
        "specifies the connector pin-out (4 Main Link pairs, 1 AUX pair, HPD, "
        "CONFIG, DP_PWR), the Main Link electrical/coding (8b/10b or "
        "128b/132b), the AUX protocol, and the DPCD register space. Source and "
        "Sink silicon implement it. Embedded DisplayPort (eDP) is the internal-"
        "panel variant.")
    d["use_cases"] = [
        "GPU-to-monitor external display link (desktop / workstation)",
        "Embedded DisplayPort (eDP) internal notebook / all-in-one panel link",
        "Multi-monitor daisy chains and hubs via MST",
        "High-resolution / high-refresh / HDR display with DSC + FEC",
        "DisplayPort-Alt-Mode over USB-C / USB4 tunneling",
        "Protected (HDCP) premium-content playback",
    ]
    d["revision_history"] = [
        {"version": "1.0", "date": "2006",
         "description": "First release: RBR/HBR 8b/10b, AUX/DPCD, link "
         "training, SST."},
        {"version": "1.1", "date": "2007",
         "description": "HDCP, fiber; clarifications."},
        {"version": "1.2", "date": "2010",
         "description": "HBR2 (5.4 Gbps/lane), MST (Multi-Stream Transport), "
         "stereo 3D."},
        {"version": "1.3", "date": "2014",
         "description": "HBR3 (8.1 Gbps/lane), 32.4 Gbps total; DP-to-HDMI "
         "2.0."},
        {"version": "1.4", "date": "2016",
         "description": "DSC (Display Stream Compression), FEC, HDR (HDR10), "
         "DSC 1.2."},
        {"version": "1.4a", "date": "2018", "description": "DSC 1.2a "
         "corrections."},
        {"version": "2.0", "date": "2019",
         "description": "UHBR10/13.5/20 (128b/132b), up to 80 Gbps total; FEC "
         "mandatory for UHBR; Panel Replay."},
        {"version": "2.1", "date": "2022",
         "description": "Alignment with USB4, DP40/DP80 cable certification, "
         "tighter UHBR conformance; same UHBR rates/architecture."},
    ]
    d["overview"] = (
        "DisplayPort (DP) is the VESA digital display interface that carries "
        "isochronous video/audio from a Source to a Sink over a Main Link of "
        "1, 2, or 4 self-clocked AC-coupled differential lanes, managed by a "
        "bidirectional half-duplex AUX channel and a Hot Plug Detect (HPD) "
        "sideband. The Main Link is a packetized ('micro-packet') stream: "
        "active video is packed into Transfer Units, the Main Stream "
        "Attributes (MSA) describe the timing once per frame, and the stream "
        "is 8b/10b-coded (RBR 1.62 / HBR 2.7 / HBR2 5.4 / HBR3 8.1 Gbps/lane) "
        "or, in DP 2.0/2.1, 128b/132b-coded for UHBR (10/13.5/20 Gbps/lane) "
        "with mandatory FEC. The clock is embedded and recovered by the Sink "
        "during a two-phase Link Training — Clock Recovery (CR, TPS1, adjust "
        "voltage swing / pre-emphasis) then Channel Equalization (EQ, TPS2/3/4) "
        "— performed by writing TRAINING_PATTERN_SET in the DPCD and reading "
        "back the per-lane status. The AUX channel runs Manchester-II native "
        "AUX transactions (4-bit command, 20-bit address, length) into the "
        "sink's DPCD register space and tunnels I2C-over-AUX to fetch the EDID. "
        "DisplayPort supports Single-Stream (SST) and Multi-Stream Transport "
        "(MST, virtual channels + 64 time slots + Sideband MSG), and carries "
        "HDCP content protection, FEC, and DSC.")
    _write(p, d)


# ----------------------------------------------------------------------
# L2 — FRS: three-channel Source/Sink model.
# ----------------------------------------------------------------------
def _l2(gd: Path) -> None:
    p = gd / "L2_FRS.json"
    if not p.is_file():
        return
    d = _read(p)
    po = _ensure_dict(d, "protocol_overview")
    po["type"] = (
        "VESA digital display interface. Source -> Sink isochronous video over "
        "a packetized Main Link (1/2/4 self-clocked differential lanes), with "
        "a bidirectional half-duplex AUX channel for management (DPCD / link "
        "training / I2C-over-AUX / MST sideband) and a Hot Plug Detect (HPD) "
        "sideband.")
    po["duplex"] = (
        "Main Link is uni-directional (Source -> Sink). AUX channel is "
        "bidirectional half-duplex (request from Source, reply from Sink over "
        "the same differential pair). HPD is a Sink -> Source sideband.")
    po["synchronous_serial"] = False
    po["source_synchronous"] = False
    po["embedded_clock"] = True
    po["forwarded_clock"] = False
    po["encoding"] = (
        "Main Link: ANSI 8b/10b for RBR/HBR/HBR2/HBR3 (DC-balanced, "
        "transition-rich, 80% efficient, LFSR-scrambled) with the clock "
        "embedded and recovered by the Sink during training; 128b/132b for "
        "UHBR (DP 2.0/2.1, ~96.97% efficient, FEC mandatory). AUX channel: "
        "Manchester-II bi-phase coding at ~1 Mbps.")
    po["modulation"] = "NRZ (two-level) differential on Main Link and AUX."
    po["main_link_lanes_supported"] = list(_LANE_COUNTS)
    po["link_rates_Gbps_per_lane"] = {
        "RBR": 1.62, "HBR": 2.70, "HBR2": 5.40, "HBR3": 8.10,
        "UHBR10": 10.0, "UHBR13.5": 13.5, "UHBR20": 20.0,
    }
    po["channels"] = ["Main Link", "AUX CH", "Hot Plug Detect (HPD)"]
    po["aux_channel"] = {
        "type": "bidirectional half-duplex differential pair (AUX+/AUX-)",
        "coding": "Manchester-II bi-phase",
        "rate_Mbps": 1,
        "model": "request/reply native AUX transactions into DPCD; "
                 "I2C-over-AUX for EDID",
    }
    po["link_training"] = {
        "phase_1": "Clock Recovery (CR) — TPS1, adjust voltage swing / "
                   "pre-emphasis until CR_DONE on all active lanes",
        "phase_2": "Channel Equalization (EQ) — TPS2/3/4, until "
                   "CHANNEL_EQ_DONE + SYMBOL_LOCKED + INTERLANE_ALIGN_DONE",
        "control": "over AUX via TRAINING_PATTERN_SET and per-lane status "
                   "readback in DPCD",
        "fallback": "lower link rate and/or fewer lanes on failure",
    }
    po["stream_framing"] = (
        "micro-packet stream: Main Stream Attributes (MSA) per frame, Transfer "
        "Units (TU) for active video, BS/BE blanking-symbol framing, "
        "secondary-data (audio / SDP) packets in the blanking intervals.")
    po["transport_modes"] = ["Single-Stream Transport (SST)",
                             "Multi-Stream Transport (MST)"]
    d["functional_requirements"] = [
        {"id": "FR-CH-01", "text": "A DisplayPort link comprises three "
         "channels: a uni-directional Main Link (1/2/4 lanes) for video, a "
         "bidirectional half-duplex AUX channel for management, and a Hot Plug "
         "Detect (HPD) sideband."},
        {"id": "FR-LANE-02", "text": "The Main Link is configurable to 1, 2, "
         "or 4 lanes; the active lane count is set in LANE_COUNT_SET (DPCD). "
         "Each lane is a self-clocked AC-coupled differential pair."},
        {"id": "FR-RATE-03", "text": "The Main Link runs at one of RBR 1.62, "
         "HBR 2.7, HBR2 5.4, or HBR3 8.1 Gbps/lane (8b/10b), or — in DP "
         "2.0/2.1 — UHBR10/13.5/20 Gbps/lane (128b/132b). The rate is set in "
         "LINK_BW_SET (or LINK_RATE_SET for UHBR)."},
        {"id": "FR-CODE-04", "text": "RBR/HBR/HBR2/HBR3 use ANSI 8b/10b coding "
         "(DC-balanced, transition-rich, LFSR-scrambled) with the clock "
         "embedded; UHBR uses 128b/132b coding with mandatory FEC."},
        {"id": "FR-TRAIN-05", "text": "Before video, the Source trains the "
         "Main Link in two phases — Clock Recovery (CR) and Channel "
         "Equalization (EQ) — adjusting per-lane voltage swing and "
         "pre-emphasis, driven over AUX via TRAINING_PATTERN_SET and per-lane "
         "status readback."},
        {"id": "FR-AUX-06", "text": "The AUX channel is a bidirectional "
         "half-duplex differential pair using Manchester-II coding at ~1 Mbps "
         "with a request/reply transaction model (4-bit command, 20-bit "
         "address, length)."},
        {"id": "FR-DPCD-07", "text": "Native AUX transactions read/write the "
         "Sink's DPCD register space (Receiver Capability at 00000h, Link "
         "Configuration at 00100h, Link/Sink Status at 00200h)."},
        {"id": "FR-EDID-08", "text": "I2C-over-AUX tunnels I2C transactions "
         "(with the MOT bit to chain bursts) to read the Sink EDID (I2C "
         "address A0h) and legacy I2C peripherals."},
        {"id": "FR-STREAM-09", "text": "Active video is carried as a "
         "micro-packet stream: packed into Transfer Units, framed by BS/BE "
         "blanking symbols, with Main Stream Attributes (MSA) sent once per "
         "frame (Mvid/Nvid time-stamp pair for asynchronous clocking)."},
        {"id": "FR-MST-10", "text": "DisplayPort supports Single-Stream "
         "Transport (SST, default) and Multi-Stream Transport (MST): multiple "
         "streams to multiple Sinks via branch devices, each stream assigned a "
         "virtual channel and a share of the 64 MST time slots, using Sideband "
         "MSG over AUX."},
        {"id": "FR-HPD-11", "text": "The Sink drives Hot Plug Detect (HPD) to "
         "indicate connection presence; a short HPD pulse (IRQ_HPD) signals "
         "link-status-change or content-protection events requiring a status "
         "re-read."},
        {"id": "FR-CP-12", "text": "DisplayPort carries HDCP (1.3 and "
         "2.2/2.3) content protection (authentication over AUX, cipher on the "
         "Main Link), FEC (required with DSC and for UHBR), and Display Stream "
         "Compression (DSC)."},
    ]
    d["error_response_conditions"] = [
        "AUX reply NACK / DEFER — Sink rejects or defers a native AUX "
        "transaction; the Source retries.",
        "I2C-over-AUX I2C_NACK / I2C_DEFER — the tunneled I2C slave (e.g. EDID "
        "ROM) NACKs/defers.",
        "Clock Recovery failure — a lane never reports CR_DONE; the Source "
        "raises swing/pre-emphasis or falls back rate/lane-count.",
        "Channel Equalization failure — CHANNEL_EQ_DONE / SYMBOL_LOCKED / "
        "INTERLANE_ALIGN_DONE not all set; fall back and re-train.",
        "Loss of lock during ACTIVE — status registers clear CR/EQ; an IRQ_HPD "
        "prompts the Source to re-read status and re-train.",
        "MST allocation failure — insufficient time slots / ALLOCATE_PAYLOAD "
        "rejected for a virtual channel.",
    ]
    d["compliance_requirements"] = [
        "Main Link of 1/2/4 self-clocked AC-coupled differential lanes with "
        "8b/10b (RBR..HBR3) or 128b/132b (UHBR) coding.",
        "Bidirectional half-duplex Manchester-II AUX channel with the native "
        "AUX request/reply transaction model.",
        "DPCD register space accessible by native AUX (Receiver Capability, "
        "Link Configuration, Link Status).",
        "I2C-over-AUX for EDID retrieval.",
        "Two-phase Link Training (CR then EQ) with voltage-swing / "
        "pre-emphasis adjustment and rate/lane fallback.",
        "Micro-packet stream with MSA per frame and Transfer-Unit packing.",
        "SST mandatory; MST optional (virtual channels + 64 time slots + "
        "Sideband MSG).",
        "HDCP support for protected content; FEC mandatory with DSC and for "
        "UHBR.",
        "Hot Plug Detect (HPD) including IRQ_HPD short-pulse event signaling.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L3 — channels / AUX transaction / micro-packet framing.
# ----------------------------------------------------------------------
def _l3(gd: Path) -> None:
    p = gd / "L3_CMD_PROTOCOL.json"
    if not p.is_file():
        return
    d = _read(p)
    d["protocol_type"] = (
        "Packetized display protocol with two transports. The Main Link is a "
        "uni-directional micro-packet video stream (Transfer Units + MSA, "
        "8b/10b or 128b/132b coded, embedded clock). The AUX channel is a "
        "bidirectional half-duplex request/reply transaction protocol "
        "(Manchester-II, ~1 Mbps) carrying native AUX accesses to the DPCD "
        "register space, I2C-over-AUX (EDID), MST Sideband MSG, and "
        "link-training control.")
    d["channels"] = [
        {"name": "Main Link (ML_Lane0..3)",
         "direction": "uni-directional Source -> Sink",
         "description": "1/2/4 self-clocked AC-coupled differential lanes; "
         "8b/10b at RBR/HBR/HBR2/HBR3 or 128b/132b at UHBR; embedded clock "
         "recovered by the Sink during training; carries the micro-packet "
         "video/audio stream."},
        {"name": "AUX CH (AUX+/AUX-)",
         "direction": "bidirectional half-duplex",
         "description": "Manchester-II bi-phase differential pair at ~1 Mbps; "
         "native AUX request/reply transactions into DPCD, I2C-over-AUX, MST "
         "sideband, and link-training control."},
        {"name": "Hot Plug Detect (HPD)",
         "direction": "Sink -> Source sideband",
         "description": "Indicates connection presence; a short pulse "
         "(IRQ_HPD) signals link-status-change / content-protection events."},
    ]
    d["aux_transaction_format"] = {
        "request": {
            "command_bits": 4,
            "commands": ["native Read (1001b)", "native Write (1000b)",
                         "I2C-over-AUX Read", "I2C-over-AUX Write",
                         "I2C MOT (Middle-Of-Transaction) variants"],
            "address_bits": 20,
            "length_field": "bytes minus one (0..15 -> 1..16 bytes per "
                            "transaction)",
            "framing": "SYNC preamble (consecutive zeros) + START/STOP "
                       "delimiting the Manchester-coded payload",
        },
        "reply": {
            "reply_command_bits": 4,
            "native_codes": ["ACK", "NACK", "DEFER"],
            "i2c_codes": ["I2C_ACK", "I2C_NACK", "I2C_DEFER"],
        },
    }
    d["dpcd_regions"] = [
        {"name": "Receiver Capability", "base": "00000h",
         "fields": "DPCD_REV, MAX_LINK_RATE, MAX_LANE_COUNT, MAX_DOWNSPREAD, "
                   "training-pattern / FEC / DSC capabilities"},
        {"name": "Link Configuration", "base": "00100h",
         "fields": "LINK_BW_SET, LANE_COUNT_SET, TRAINING_PATTERN_SET, "
                   "TRAINING_LANE0_SET..LANE3_SET, DOWNSPREAD_CTRL"},
        {"name": "Link/Sink Status", "base": "00200h",
         "fields": "SINK_COUNT, LANE0_1_STATUS, LANE2_3_STATUS, "
                   "LANE_ALIGN_STATUS_UPDATED, ADJUST_REQUEST_LANE0_1/2_3"},
        {"name": "Device Service IRQ / HDCP / MST",
         "base": "00200h+ / 06000h+ (HDCP) / sideband buffers",
         "fields": "Device Service IRQ Vector, HDCP registers, MST sideband "
                   "DOWN_REQ / UP_REP / DOWN_REP / UP_REQ buffers"},
    ]
    d["i2c_over_aux"] = {
        "purpose": "tunnel I2C transactions over AUX to reach the Sink EDID "
                   "and legacy I2C peripherals",
        "edid_i2c_address": "A0h (read A1h)",
        "mot_bit": "Middle-Of-Transaction bit chains a multi-byte I2C burst",
        "edid_block_bytes": 128,
    }
    d["main_link_framing"] = {
        "active_video": "packed into Transfer Units (TU, typically 32 or 64 "
                        "symbols/lane; only the symbols required by "
                        "pixel-rate/link-rate are active, remainder stuffed "
                        "with Fill)",
        "blanking_framing": "BS (Blanking Start) / BE (Blanking End) control "
                            "(K) symbols delimit active line data",
        "secondary_data": "SS/SE delimit secondary-data packets (audio sample "
                          "packets, MSA, VSC SDP / InfoFrames) in the blanking "
                          "intervals",
        "msa": "Main Stream Attributes once per frame (Mvid/Nvid, Htotal/"
               "Vtotal, HSP/HSW, active width/height, MISC0/MISC1)",
        "control_symbols": ["BS", "BE", "SR (Scrambler Reset)", "SS", "SE",
                            "FS", "FE"],
    }
    d["mst_messaging"] = {
        "transport": "Sideband MSG over AUX (DOWN_REQ / UP_REP / DOWN_REP / "
                     "UP_REQ)",
        "messages": ["LINK_ADDRESS", "ENUM_PATH_RESOURCES", "ALLOCATE_PAYLOAD"],
        "time_slots": 64,
        "virtual_channels": "one per stream",
        "negotiated_via": "MSTM_CTRL DPCD register",
    }
    d["burst_based"] = False
    d["byte_oriented"] = True
    d["packet_oriented"] = True
    d["addressing"] = {
        "aux_address_bits": 20,
        "space": "DPCD register address space (and I2C address space for "
                 "I2C-over-AUX)",
        "note": "The Main Link video stream is addressless isochronous data; "
                "addressing applies to the AUX/DPCD management plane.",
    }
    d["frame_format"] = {
        "main_link": "micro-packet stream — Transfer Units of active video "
                     "framed by BS/BE, MSA per frame, secondary-data packets "
                     "in blanking; 8b/10b (or 128b/132b for UHBR) symbols.",
        "aux": "Manchester-II request/reply: SYNC + START + (command[4] + "
               "address[20] + length) / reply(command[4] + data) + STOP.",
        "note": "The Main Link clock is embedded (recovered during training); "
                "there is no dedicated Main Link clock lane.",
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L4 — DPCD register map (AUX-accessible).
# ----------------------------------------------------------------------
def _l4(gd: Path) -> None:
    p = gd / "L4_REGMAP.json"
    if not p.is_file():
        return
    d = _read(p)
    d["register_map_present"] = True
    d["notes"] = (
        "The DisplayPort register space is the DPCD (DisplayPort Configuration "
        "Data) in the Sink, accessed by native AUX read/write over the AUX "
        "channel (20-bit address). The Source uses it for capability "
        "discovery, link configuration, link training, status readback, "
        "content protection, and MST. The Sink's EDID is a separate I2C ROM "
        "reached by I2C-over-AUX, not part of the DPCD.")
    d["register_access"] = {
        "transport": "Native AUX (Manchester-II, ~1 Mbps) over the AUX "
                     "channel",
        "address_bits": 20,
        "transaction": "request (4-bit command + 20-bit address + length) / "
                       "reply (ACK/NACK/DEFER + data)",
        "available_before_main_link_up": True,
    }
    d["register_groups"] = [
        {"group": "Receiver Capability (base 00000h)", "fields": [
            "DPCD_REV (DPCD revision)",
            "MAX_LINK_RATE (RBR/HBR/HBR2/HBR3 max)",
            "MAX_LANE_COUNT (1/2/4)",
            "MAX_DOWNSPREAD (spread-spectrum support)",
            "supported training patterns (TPS1..TPS4)",
            "FEC capability, DSC capability"]},
        {"group": "Link Configuration (base 00100h)", "fields": [
            "LINK_BW_SET (selected link rate)",
            "LANE_COUNT_SET (selected lane count)",
            "TRAINING_PATTERN_SET (TPS1/2/3/4 select)",
            "TRAINING_LANE0_SET..TRAINING_LANE3_SET (voltage swing + "
            "pre-emphasis)",
            "DOWNSPREAD_CTRL",
            "FEC_CONFIGURATION (FEC enable)"]},
        {"group": "Link/Sink Status (base 00200h)", "fields": [
            "SINK_COUNT",
            "LANE0_1_STATUS / LANE2_3_STATUS (CR_DONE, CHANNEL_EQ_DONE, "
            "SYMBOL_LOCKED)",
            "LANE_ALIGN_STATUS_UPDATED (INTERLANE_ALIGN_DONE)",
            "ADJUST_REQUEST_LANE0_1 / ADJUST_REQUEST_LANE2_3 (requested swing "
            "/ pre-emphasis)",
            "Device Service IRQ Vector"]},
        {"group": "Content Protection / MST", "fields": [
            "HDCP 1.3 / 2.2-2.3 registers (authentication, CP_IRQ)",
            "MSTM_CTRL (MST enable)",
            "MST Sideband MSG buffers (DOWN_REQ / UP_REP / DOWN_REP / "
            "UP_REQ)",
            "PAYLOAD_ALLOCATE / time-slot table"]},
    ]
    d["edid_via_i2c_over_aux"] = {
        "note": "EDID is read from the Sink's I2C ROM (I2C address A0h) by "
                "tunneling I2C over AUX; it is NOT in the DPCD address space.",
        "edid_block_bytes": 128,
    }
    d["aux_command_fields"] = {
        "command_width_bits": 4,
        "address_width_bits": 20,
        "length_encoding": "bytes minus one (1..16 bytes per transaction)",
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L5 — analog/electrical: Main Link differential + AUX.
# ----------------------------------------------------------------------
def _l5(gd: Path) -> None:
    p = gd / "L5_ADI_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["analog_digital_interface_present"] = True
    d["signaling_summary"] = (
        "Main Link: 1/2/4 AC-coupled differential pairs carrying NRZ at RBR "
        "1.62 / HBR 2.7 / HBR2 5.4 / HBR3 8.1 Gbps/lane with ANSI 8b/10b "
        "coding (DC-balanced, transition-rich, LFSR-scrambled) so the Sink can "
        "recover the embedded clock; DP 2.0/2.1 UHBR10/13.5/20 Gbps/lane uses "
        "128b/132b coding with mandatory FEC. Each lane carries per-lane "
        "voltage-swing (4 levels) and pre-emphasis (4 levels) set during "
        "training. AUX: one AC-coupled bidirectional half-duplex differential "
        "pair, Manchester-II coded at ~1 Mbps.")
    d["modulation"] = "NRZ (two-level), differential, AC-coupled."
    d["clocking"] = (
        "Embedded clock on the Main Link — recovered by the Sink's CDR during "
        "Clock Recovery (there is no dedicated Main Link clock lane). The Mvid/"
        "Nvid pair in the MSA lets the Sink regenerate the pixel clock from the "
        "recovered link clock (asynchronous clocking).")
    d["transmitter_specs_canonical"] = {
        "link_rates_Gbps_per_lane": {
            "RBR": 1.62, "HBR": 2.70, "HBR2": 5.40, "HBR3": 8.10,
            "UHBR10": 10.0, "UHBR13.5": 13.5, "UHBR20": 20.0},
        "modulation": "NRZ",
        "signaling": "differential (AC-coupled)",
        "line_encoding": "8b/10b (RBR..HBR3) / 128b/132b (UHBR)",
        "lanes": list(_LANE_COUNTS),
        "voltage_swing_levels": 4,
        "pre_emphasis_levels": 4,
        "embedded_clock": True,
        "scrambling": "LFSR (reset by the SR scrambler-reset symbol)",
    }
    d["receiver_specs_canonical"] = {
        "clock_recovery": "Sink CDR recovers the embedded clock per lane "
                          "during the CR training phase.",
        "equalization": "Channel Equalization (EQ) phase trains the receiver "
                        "to CHANNEL_EQ_DONE + SYMBOL_LOCKED + "
                        "INTERLANE_ALIGN_DONE.",
        "interlane_align": "De-skews and aligns lanes (INTERLANE_ALIGN_DONE).",
        "status_reporting": "Reports CR_DONE / CHANNEL_EQ_DONE / SYMBOL_LOCKED "
                           "/ INTERLANE_ALIGN_DONE and ADJUST_REQUEST in DPCD.",
    }
    d["aux_electrical"] = {
        "pair": "AUX+/AUX- (bidirectional half-duplex, AC-coupled)",
        "coding": "Manchester-II bi-phase",
        "rate_Mbps": 1,
        "framing": "SYNC preamble + START/STOP",
    }
    d["channel_coding"] = {
        "8b10b": {"rates": ["RBR", "HBR", "HBR2", "HBR3"], "efficiency": "80%",
                  "note": "10-bit DC-balanced symbol per 8-bit char; control "
                          "(K) symbols frame the stream."},
        "128b132b": {"rates": ["UHBR10", "UHBR13.5", "UHBR20"],
                     "efficiency": "~96.97%", "fec": "mandatory",
                     "note": "4-byte sync per 128-bit block (DP 2.0/2.1)."},
    }
    d["downspread"] = (
        "Spread-spectrum clocking (down-spread) is supported (MAX_DOWNSPREAD / "
        "DOWNSPREAD_CTRL in DPCD) to reduce EMI.")
    d["encoding_role_in_analog"] = (
        "8b/10b provides DC balance and transition density so the Sink CDR can "
        "recover the embedded Main Link clock without a forwarded clock lane; "
        "scrambling spreads the spectrum. UHBR's 128b/132b raises efficiency "
        "but relies on FEC (Reed-Solomon) for error correction. AUX uses "
        "Manchester-II so the low-rate management channel is self-clocked.")
    _write(p, d)


# ----------------------------------------------------------------------
# L6 — control logic: link-policy FSM + AUX + training FSMs.
# ----------------------------------------------------------------------
def _l6(gd: Path) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["fsm_states_link_policy"] = [
        {"name": "POWER_ON / RESET", "description": "Source idle; waiting for "
         "the Sink to assert HPD (plug detect)."},
        {"name": "CAPABILITY_READ", "description": "On HPD, read the DPCD "
         "Receiver Capability (MAX_LINK_RATE, MAX_LANE_COUNT, FEC/DSC caps) "
         "over native AUX."},
        {"name": "EDID_READ", "description": "Read the Sink EDID via "
         "I2C-over-AUX to learn supported timings."},
        {"name": "LINK_TRAINING", "description": "Run Clock Recovery then "
         "Channel Equalization, setting TRAINING_PATTERN_SET and adjusting "
         "swing/pre-emphasis; fall back rate/lane-count on failure."},
        {"name": "ACTIVE", "description": "Stream video as micro-packets / "
         "Transfer Units; send MSA per frame; maintain audio / secondary "
         "data."},
        {"name": "IRQ_HPD", "description": "On a short HPD pulse, re-read "
         "status (LANE*_STATUS, Device Service IRQ Vector); re-train or handle "
         "CP_IRQ as needed."},
        {"name": "POWER_DOWN", "description": "Write SET_POWER (D3) in DPCD; "
         "Main Link idle."},
    ]
    d["fsm_states_clock_recovery"] = [
        {"name": "CR_START", "description": "Set TRAINING_PATTERN_SET=TPS1; "
         "drive initial voltage swing / pre-emphasis on all active lanes."},
        {"name": "CR_ADJUST", "description": "Read ADJUST_REQUEST per lane; "
         "apply requested swing / pre-emphasis; wait the training interval."},
        {"name": "CR_CHECK", "description": "Read LANE*_STATUS; if all active "
         "lanes report CR_DONE proceed to EQ; else adjust or fall back."},
    ]
    d["fsm_states_channel_eq"] = [
        {"name": "EQ_START", "description": "Set TRAINING_PATTERN_SET=TPS2/3/4 "
         "(or UHBR pattern)."},
        {"name": "EQ_CHECK", "description": "Read LANE*_STATUS + "
         "LANE_ALIGN_STATUS_UPDATED; success requires CHANNEL_EQ_DONE + "
         "SYMBOL_LOCKED + INTERLANE_ALIGN_DONE on all active lanes."},
        {"name": "EQ_DONE", "description": "Set TRAINING_PATTERN_SET=0 (stop "
         "training); link is trained, enter ACTIVE."},
        {"name": "EQ_FALLBACK", "description": "On failure, reduce link rate "
         "and/or lane count and restart Clock Recovery."},
    ]
    d["fsm_states_aux_transaction"] = [
        {"name": "AUX_IDLE", "description": "AUX bus idle (half-duplex)."},
        {"name": "AUX_REQUEST", "description": "Source drives SYNC + START + "
         "command[4] + address[20] + length (+ write data)."},
        {"name": "AUX_REPLY", "description": "Sink drives reply command "
         "(ACK/NACK/DEFER or I2C_*) + read data."},
        {"name": "AUX_RETRY", "description": "On NACK/DEFER or timeout, the "
         "Source retries the transaction."},
    ]
    d["fsm_hints"] = {
        "trigger": "HPD assertion starts CAPABILITY_READ -> EDID_READ -> "
        "LINK_TRAINING -> ACTIVE. All control rides the AUX channel; the Main "
        "Link only carries video once trained.",
        "rule": "Link training is strictly CR (TPS1) before EQ (TPS2/3/4); EQ "
        "success requires CHANNEL_EQ_DONE + SYMBOL_LOCKED + "
        "INTERLANE_ALIGN_DONE on every active lane.",
        "abort": "Repeated CR/EQ failure triggers fallback to a lower rate "
        "and/or fewer lanes; persistent failure leaves the link untrained.",
    }
    d["anti_deadlock_rule"] = (
        "AUX transactions are half-duplex request/reply with retry on "
        "NACK/DEFER/timeout, so the bus cannot lock up; link training has a "
        "bounded loop-count before rate/lane fallback; MST time-slot "
        "allocation is bounded by the 64-slot table.")
    d["exit_from_reset_or_poweron"] = (
        "After power-on the Source waits for HPD, then reads DPCD capability "
        "and EDID over AUX, trains the Main Link (CR then EQ with swing/"
        "pre-emphasis adjustment and rate/lane fallback), and enters ACTIVE to "
        "stream video; an IRQ_HPD prompts status re-read and possible "
        "re-training.")
    d["default_ready_state_recommendation"] = {
        "main_link_idle": "Send blanking / idle symbols (BS framing) with no "
                          "active video until trained and streaming.",
        "aux_idle": "AUX bus released (half-duplex), ready for the next "
                    "request.",
        "hpd": "Sink keeps HPD asserted while connected; pulses IRQ_HPD on "
               "events.",
    }
    d["configurations"] = [
        {"name": "1-lane link", "description": "Single Main Link lane "
         "(ML_Lane0)."},
        {"name": "2-lane link", "description": "Two Main Link lanes."},
        {"name": "4-lane link", "description": "Four Main Link lanes (typical "
         "external connector)."},
    ]
    d["timing_dependency_rule"] = (
        "The Main Link clock is embedded and recovered per lane during CR; "
        "multi-lane links are de-skewed/aligned during EQ "
        "(INTERLANE_ALIGN_DONE). The Mvid/Nvid pair lets the Sink regenerate "
        "the pixel clock from the recovered link clock. AUX runs independently "
        "at ~1 Mbps Manchester-II.")
    _write(p, d)


# ----------------------------------------------------------------------
# L7 — test/debug: AUX/DPCD observability + training status.
# ----------------------------------------------------------------------
def _l7(gd: Path) -> None:
    p = gd / "L7_TEST_DEBUG.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_debug_architecture_present"] = True
    d["spec_provided_observability"] = [
        {"name": "DPCD status registers", "purpose": "Read LANE0_1_STATUS / "
         "LANE2_3_STATUS / LANE_ALIGN_STATUS_UPDATED for CR_DONE / "
         "CHANNEL_EQ_DONE / SYMBOL_LOCKED / INTERLANE_ALIGN_DONE per lane over "
         "AUX."},
        {"name": "ADJUST_REQUEST", "purpose": "Sink reports the requested "
         "voltage swing / pre-emphasis per lane during training."},
        {"name": "Device Service IRQ Vector", "purpose": "Identifies the "
         "source of an IRQ_HPD (link-status change, CP_IRQ, sink-specific "
         "events)."},
        {"name": "TEST_ automation registers", "purpose": "DPCD test "
         "automation (TEST_REQUEST / TEST_LINK_RATE / TEST_LANE_COUNT / "
         "TEST_PATTERN) lets a compliance tester drive defined link/video "
         "patterns."},
        {"name": "SINK_COUNT", "purpose": "Reports the number of downstream "
         "Sinks (branch/MST topology)."},
        {"name": "HPD / IRQ_HPD", "purpose": "Hot-plug presence and short-"
         "pulse event signaling to the Source."},
    ]
    d["error_detection_mechanisms"] = [
        "Per-lane training status (CR_DONE / CHANNEL_EQ_DONE / SYMBOL_LOCKED) "
        "detects loss of lock.",
        "8b/10b disparity / invalid-symbol detection on the Main Link.",
        "FEC (Reed-Solomon) corrects symbol errors when DSC/UHBR is active "
        "(FEC_CONFIGURATION).",
        "AUX reply NACK/DEFER and CRC on AUX transactions detect management "
        "errors.",
        "ERROR_COUNT (symbol-error / FEC-error counters) in DPCD report "
        "Main-Link integrity.",
    ]
    d["test_modes"] = [
        {"name": "Link/compliance test automation", "purpose": "DPCD TEST_* "
         "registers drive defined link rates, lane counts, and test patterns "
         "for a compliance tester."},
        {"name": "PHY test patterns (TPS1..TPS4 / UHBR patterns)",
         "purpose": "Drive defined training/test patterns to characterize the "
         "Main Link eye."},
        {"name": "AUX loopback / read-write", "purpose": "Exercise the AUX "
         "channel and DPCD independently of the Main Link."},
        {"name": "Symbol-error-rate measurement", "purpose": "Count Main-Link "
         "symbol / FEC errors via DPCD error counters."},
    ]
    d["interrupt_or_event_sources"] = [
        {"event": "HPD assert / de-assert", "trigger": "Plug / unplug "
         "detected by the Sink."},
        {"event": "IRQ_HPD (short pulse)", "trigger": "Link-status change, "
         "CP_IRQ, or sink event — Source re-reads DPCD."},
        {"event": "Loss of lock", "trigger": "CR/EQ status clears during "
         "ACTIVE; re-train."},
        {"event": "CP_IRQ", "trigger": "HDCP content-protection event."},
        {"event": "MST topology change", "trigger": "Sideband UP_REQ "
         "(CONNECTION_STATUS_NOTIFY)."},
    ]
    d["notes"] = (
        "DisplayPort's protocol-level test/debug surface is the AUX channel + "
        "DPCD (status, ADJUST_REQUEST, Device Service IRQ Vector, TEST_* "
        "automation) plus the Main-Link training/test patterns and FEC/symbol "
        "error counters. Chip-level JTAG/scan/BIST remain Source/Sink-silicon "
        "concerns; conformance is established by the VESA DisplayPort "
        "Compliance Test Specification (CTS).")
    _write(p, d)


# ----------------------------------------------------------------------
# L8 RTL constants — DisplayPort lane/rate/AUX/coding constants.
# ----------------------------------------------------------------------
def _l8_rtl(gd: Path) -> None:
    p = gd / "L8_RTL_CONSTANTS.json"
    if not p.is_file():
        return
    d = _read(p)
    wp = _ensure_dict(d, "width_parameters")
    wp.update({
        "DP_SPEC_VERSION": "1.4a / 2.0 / 2.1",
        "MODULATION": "NRZ",
        "SIGNALING": "differential (AC-coupled)",
        "MAIN_LINK_LANES_SUPPORTED": list(_LANE_COUNTS),
        "MAIN_LINK_LANES_MAX": 4,
        "LINK_RATE_RBR_GBPS": 1.62,
        "LINK_RATE_HBR_GBPS": 2.70,
        "LINK_RATE_HBR2_GBPS": 5.40,
        "LINK_RATE_HBR3_GBPS": 8.10,
        "LINK_RATE_UHBR10_GBPS": 10.0,
        "LINK_RATE_UHBR13_5_GBPS": 13.5,
        "LINK_RATE_UHBR20_GBPS": 20.0,
        "CHANNEL_CODING_8B10B_RATES": ["RBR", "HBR", "HBR2", "HBR3"],
        "CHANNEL_CODING_128B132B_RATES": ["UHBR10", "UHBR13.5", "UHBR20"],
        "CODING_8B10B_EFFICIENCY": "80%",
        "CODING_128B132B_EFFICIENCY": "~96.97%",
        "VOLTAGE_SWING_LEVELS": 4,
        "PRE_EMPHASIS_LEVELS": 4,
        "EMBEDDED_CLOCK": True,
        "FORWARDED_CLOCK": False,
        "AUX_CODING": "Manchester-II",
        "AUX_RATE_MBPS": 1,
        "AUX_COMMAND_WIDTH_BITS": 4,
        "AUX_ADDRESS_WIDTH_BITS": 20,
        "AUX_LENGTH_ENCODING": "bytes minus one (1..16)",
        "DPCD_RECEIVER_CAP_BASE": "00000h",
        "DPCD_LINK_CONFIG_BASE": "00100h",
        "DPCD_LINK_STATUS_BASE": "00200h",
        "EDID_I2C_ADDRESS": "A0h",
        "EDID_BLOCK_BYTES": 128,
        "MST_TIME_SLOTS": 64,
        "TRANSFER_UNIT_SYMBOLS": "32 or 64",
        "TRAINING_PATTERNS": ["TPS1", "TPS2", "TPS3", "TPS4"],
        "FEC_REQUIRED_WITH_DSC": True,
        "FEC_REQUIRED_FOR_UHBR": True,
    })
    d["channel_coding_constants"] = {
        "8b10b": {"symbol_bits": 10, "char_bits": 8, "efficiency": "80%",
                  "scrambled": True},
        "128b132b": {"block_bits": 128, "sync_bytes": 4,
                     "efficiency": "~96.97%", "fec": "mandatory"},
    }
    d["aux_constants"] = {
        "coding": "Manchester-II", "rate_Mbps": 1,
        "command_bits": 4, "address_bits": 20,
        "native_replies": ["ACK", "NACK", "DEFER"],
        "i2c_replies": ["I2C_ACK", "I2C_NACK", "I2C_DEFER"],
    }
    kc = _ensure_dict(d, "key_constants_for_RTL_authoring")
    kc.update({
        "is_serial": True,
        "is_differential": True,
        "embedded_clock": True,
        "forwarded_clock": False,
        "modulation": "NRZ",
        "main_link_coding": "8b/10b (RBR..HBR3) / 128b/132b (UHBR)",
        "main_link_lanes": list(_LANE_COUNTS),
        "link_rates_Gbps_per_lane": [1.62, 2.70, 5.40, 8.10, 10.0, 13.5, 20.0],
        "voltage_swing_levels": 4,
        "pre_emphasis_levels": 4,
        "aux_coding": "Manchester-II",
        "aux_rate_Mbps": 1,
        "aux_command_bits": 4,
        "aux_address_bits": 20,
        "dpcd_register_space": True,
        "i2c_over_aux": True,
        "two_phase_training_cr_eq": True,
        "mst_supported": True,
        "mst_time_slots": 64,
        "fec_with_dsc": True,
        "hdcp_supported": True,
    })
    d["default_signal_values_when_idle"] = {
        "main_link_idle": "Blanking / idle symbols (BS framing); no active "
                          "video before training / streaming.",
        "aux_idle": "AUX bus released (half-duplex); ready for next request.",
        "hpd": "Asserted while connected; IRQ_HPD pulses on events.",
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L8 timing — Main Link / AUX / training timing.
# ----------------------------------------------------------------------
def _l8_timing(gd: Path) -> None:
    p = gd / "L8_TIMING_WAVEFORM.json"
    if not p.is_file():
        return
    d = _read(p)
    d["main_link_waveform"] = {
        "signaling": "differential NRZ per lane, AC-coupled, embedded clock.",
        "coding": "8b/10b (RBR/HBR/HBR2/HBR3) or 128b/132b (UHBR).",
        "framing": "Transfer Units of active video framed by BS/BE control "
                   "symbols; MSA per frame; secondary-data packets (SS/SE) in "
                   "blanking.",
        "clocking": "Sink recovers the embedded clock with a CDR; no dedicated "
                    "clock lane.",
        "link_rates_Gbps_per_lane": [1.62, 2.70, 5.40, 8.10, 10.0, 13.5, 20.0],
    }
    d["aux_waveform"] = {
        "coding": "Manchester-II bi-phase", "rate_Mbps": 1,
        "transaction": "SYNC preamble + START + (command[4] + address[20] + "
                       "length) request, then Sink reply, then STOP.",
        "half_duplex": True,
    }
    d["link_training_waveform"] = {
        "CR_phase": "TPS1 on all active lanes; adjust voltage swing / "
                    "pre-emphasis until CR_DONE.",
        "EQ_phase": "TPS2/3/4 (or UHBR pattern) until CHANNEL_EQ_DONE + "
                    "SYMBOL_LOCKED + INTERLANE_ALIGN_DONE.",
        "stop": "TRAINING_PATTERN_SET=0 stops training; stream begins.",
        "control_over_aux": True,
    }
    d["msa_waveform"] = {
        "msa": "Main Stream Attributes sent once per frame in vertical "
               "blanking: Mvid/Nvid, Htotal/Vtotal, HSP/HSW, active "
               "width/height, MISC0/MISC1.",
        "purpose": "Lets the Sink regenerate the pixel clock from the link "
                   "clock (asynchronous clocking).",
    }
    d["hpd_waveform"] = {
        "assert": "Sink asserts HPD on connect.",
        "irq_hpd": "Short pulse (>= ~0.5 ms, <= ~1 ms) signals an event; "
                   "Source re-reads DPCD.",
    }
    d["general_timing_rule"] = (
        "The Main Link unit interval is set by the link rate (e.g. ~123.5 ps "
        "UI at 8.1 Gbps HBR3). The embedded clock is recovered per lane during "
        "CR; multi-lane links are de-skewed during EQ. The pixel clock is "
        "regenerated from Mvid/Nvid. AUX runs at a fixed ~1 Mbps Manchester-II "
        "independent of the Main Link rate.")
    d["voltage_levels"] = {
        "modulation": "NRZ differential, AC-coupled.",
        "voltage_swing_levels": 4,
        "pre_emphasis_levels": 4,
        "note": "Swing + pre-emphasis selected per lane during CR; bounded "
                "combinations.",
    }
    d["link_rate_waveform"] = {
        "rates_Gbps_per_lane": {
            "RBR": 1.62, "HBR": 2.70, "HBR2": 5.40, "HBR3": 8.10,
            "UHBR10": 10.0, "UHBR13.5": 13.5, "UHBR20": 20.0},
        "coding": {"RBR/HBR/HBR2/HBR3": "8b/10b", "UHBR": "128b/132b"},
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
        "DisplayPort Source or Sink display-interface controller: drives/"
        "receives the Main Link (1/2/4 differential lanes, 8b/10b or 128b/132b "
        "video micro-packets), runs the AUX channel (DPCD / link training / "
        "I2C-over-AUX / MST sideband), and handles HPD, HDCP, FEC, and DSC.")
    d["topology_description"] = (
        "Point-to-point Source -> Sink over the Main Link plus a bidirectional "
        "AUX channel and an HPD sideband. MST extends this to a tree of Sinks "
        "via branch devices (hubs / daisy chain) with virtual channels and a "
        "64-slot time-slot allocation.")
    io = _ensure_dict(d, "integration_overview")
    io.update({
        "dp_spec_version": "1.4a / 2.0 / 2.1",
        "main_link_lanes_supported": list(_LANE_COUNTS),
        "link_rates_Gbps_per_lane": [1.62, 2.70, 5.40, 8.10, 10.0, 13.5, 20.0],
        "main_link_coding": "8b/10b (RBR..HBR3) / 128b/132b (UHBR)",
        "clocking": "embedded clock recovered by the Sink (no clock lane)",
        "aux_channel": "bidirectional half-duplex Manchester-II ~1 Mbps",
        "aux_address_bits": 20,
        "dpcd_register_space": True,
        "i2c_over_aux_edid": True,
        "edid_i2c_address": "A0h",
        "two_phase_training": "Clock Recovery + Channel Equalization",
        "voltage_swing_levels": 4,
        "pre_emphasis_levels": 4,
        "transport_modes": ["SST", "MST"],
        "mst_time_slots": 64,
        "fec_required_with_dsc": True,
        "hdcp": "1.3 / 2.2-2.3",
        "host_side_register_spec": "DPCD accessed over AUX (Receiver "
        "Capability / Link Configuration / Link Status); EDID via "
        "I2C-over-AUX.",
    })
    d["interface_categories"] = [
        "Main Link — 1/2/4 differential lanes carrying the video micro-packet "
        "stream (8b/10b or 128b/132b).",
        "AUX channel — bidirectional half-duplex Manchester-II management "
        "channel (DPCD / training / I2C-over-AUX / MST sideband).",
        "HPD — Hot Plug Detect sideband (presence + IRQ_HPD).",
        "DPCD — register space for capability / configuration / status / CP / "
        "MST.",
        "Stream interface — pixel/audio source into Transfer Units + MSA.",
    ]
    d["interconnect_topologies_supported"] = [
        "Single Source -> single Sink (SST).",
        "Source -> branch device -> multiple Sinks (MST tree).",
        "Daisy-chained Sinks (MST).",
        "Embedded DisplayPort (eDP) Source -> internal panel.",
        "DisplayPort-Alt-Mode over USB-C / USB4 tunneling.",
    ]
    d["default_signal_values_when_omitted"] = (
        "Main Link idle = blanking/idle symbols, no active video until "
        "trained; AUX bus released; HPD asserted while connected. SST is the "
        "default transport mode unless MST is enabled via MSTM_CTRL.")
    d["soc_dependent_items"] = [
        "Source vs Sink role and number of Main Link lanes (1/2/4).",
        "Maximum link rate supported (RBR..HBR3, optionally UHBR).",
        "PHY (SerDes / CDR, 8b/10b or 128b/132b, swing/pre-emphasis) "
        "implementation.",
        "AUX PHY (Manchester-II, bidirectional half-duplex).",
        "DPCD register implementation and EDID I2C ROM (Sink).",
        "SST-only vs MST (branch device) support.",
        "HDCP, FEC, and DSC inclusion.",
        "Power/clock domains and DP_PWR / HPD handling.",
    ]
    d["low_power_modes"] = {
        "ACTIVE": "Streaming video on the Main Link.",
        "SET_POWER_D3": "Sink/Source low-power (SET_POWER DPCD = D3); Main "
                        "Link idle.",
        "Panel_Replay_eDP": "eDP panel self-refresh / Panel Replay reduces "
                            "link activity for static frames.",
    }
    d["device_classes_examples"] = [
        "GPU / SoC DisplayPort Source",
        "Monitor / panel DisplayPort Sink",
        "DisplayPort MST branch device (hub)",
        "Embedded DisplayPort (eDP) panel",
        "DP-to-HDMI / DP-to-VGA protocol converter (dongle)",
        "USB-C / USB4 DisplayPort-Alt-Mode bridge",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L10 — compliance / test categories.
# ----------------------------------------------------------------------
def _l10(gd: Path) -> None:
    p = gd / "L10_TEST_CASES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_cases_present"] = (
        "partial - the VESA DisplayPort Compliance Test Specification (CTS) "
        "defines link-layer, PHY, AUX, EDID, and protocol conformance "
        "behaviors; the standard itself defines the behaviors but does not "
        "ship an RTL testbench.")
    d["derived_compliance_test_categories"] = [
        "HPD detect: Sink asserts HPD on connect; Source begins capability "
        "read.",
        "AUX transactions: native Read/Write (4-bit command, 20-bit address, "
        "length) with ACK/NACK/DEFER replies.",
        "DPCD capability read: MAX_LINK_RATE, MAX_LANE_COUNT, FEC/DSC caps.",
        "I2C-over-AUX EDID read (I2C address A0h, MOT chaining).",
        "Link training Clock Recovery: TPS1, swing/pre-emphasis adjust, "
        "CR_DONE on all active lanes.",
        "Link training Channel Equalization: TPS2/3/4, CHANNEL_EQ_DONE + "
        "SYMBOL_LOCKED + INTERLANE_ALIGN_DONE.",
        "Link rate coverage: RBR 1.62 / HBR 2.7 / HBR2 5.4 / HBR3 8.1; UHBR "
        "10/13.5/20.",
        "Lane-count coverage: 1, 2, 4 lanes.",
        "Rate/lane fallback on training failure.",
        "8b/10b coding + scrambling; 128b/132b + FEC for UHBR.",
        "Micro-packet stream: Transfer-Unit packing, BS/BE framing, MSA per "
        "frame (Mvid/Nvid).",
        "Secondary-data packets: audio sample packets, SDP / InfoFrames.",
        "MST: virtual channels, 64 time-slot allocation, Sideband MSG "
        "(LINK_ADDRESS / ENUM_PATH_RESOURCES / ALLOCATE_PAYLOAD).",
        "HDCP 1.3 / 2.2-2.3 authentication over AUX and Main-Link encryption.",
        "FEC enable (FEC_CONFIGURATION) with DSC.",
        "DSC capability / configuration via DPCD.",
        "IRQ_HPD short-pulse handling: status re-read, re-train, CP_IRQ.",
        "Voltage-swing (4) and pre-emphasis (4) level coverage.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L11 — OTP-equivalent / capability fields.
# ----------------------------------------------------------------------
def _l11(gd: Path) -> None:
    p = gd / "L11_OTP_CONTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    d["otp_present"] = False
    d["otp_equivalent_factory_burned_fields"] = [
        {"field": "DPCD_REV", "width_bits": 8,
         "location": "DPCD 00000h",
         "note": "DPCD revision advertised by the Sink."},
        {"field": "MAX_LINK_RATE", "width_bits": 8,
         "location": "DPCD 00001h",
         "note": "Maximum Main Link rate the Sink supports (RBR/HBR/HBR2/"
                 "HBR3)."},
        {"field": "MAX_LANE_COUNT", "width_bits": "5 (+ enhanced-framing/"
         "TPS3 flags)", "location": "DPCD 00002h",
         "note": "Maximum Main Link lane count (1/2/4)."},
        {"field": "EDID", "width_bits": "128-byte block (+ extensions)",
         "location": "Sink I2C ROM (I2C address A0h, via I2C-over-AUX)",
         "note": "Display capability/timing descriptor; factory-programmed in "
                 "the Sink."},
        {"field": "HDCP keys / receiver ID",
         "width_bits": "implementation-defined",
         "location": "Sink HDCP store",
         "note": "Per-device content-protection keys (when HDCP supported)."},
    ]
    d["notes"] = (
        "DisplayPort does not define OTP/fuse content as a protocol concept. "
        "The interoperability-relevant facts are the DPCD capability registers "
        "(DPCD_REV, MAX_LINK_RATE, MAX_LANE_COUNT, FEC/DSC caps) read over AUX "
        "and the Sink's EDID read by I2C-over-AUX; an implementation may back "
        "these with ROM/fuses, but the spec only requires they be "
        "discoverable. HDCP devices also hold factory keys.")
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
        "1. Sink asserts HPD on connect.",
        "2. Source reads DPCD Receiver Capability (MAX_LINK_RATE, "
        "MAX_LANE_COUNT, FEC/DSC) over native AUX.",
        "3. Source reads the Sink EDID via I2C-over-AUX (I2C address A0h).",
        "4. Source writes LINK_BW_SET and LANE_COUNT_SET to the chosen rate / "
        "lane count.",
        "5. Clock Recovery: set TRAINING_PATTERN_SET=TPS1; adjust per-lane "
        "voltage swing / pre-emphasis from ADJUST_REQUEST until CR_DONE.",
        "6. Channel Equalization: set TPS2/3/4 (or UHBR pattern); wait for "
        "CHANNEL_EQ_DONE + SYMBOL_LOCKED + INTERLANE_ALIGN_DONE on all active "
        "lanes.",
        "7. Stop training (TRAINING_PATTERN_SET=0); enable FEC if DSC/UHBR.",
        "8. ACTIVE: stream video as Transfer Units with MSA per frame.",
    ]
    d["aux_transaction_sequence"] = [
        "1. Source drives SYNC + START on the AUX pair.",
        "2. Source sends command[4] + address[20] + length (+ write data for "
        "a write).",
        "3. Source releases the bus (half-duplex turnaround).",
        "4. Sink replies with ACK/NACK/DEFER (or I2C_* for I2C-over-AUX) + "
        "read data.",
        "5. STOP; on NACK/DEFER/timeout the Source retries.",
    ]
    d["edid_read_sequence"] = [
        "1. Source issues an I2C-over-AUX write to set the EDID offset (I2C "
        "address A0h) with the MOT bit set.",
        "2. Source issues I2C-over-AUX reads (MOT chaining) to fetch the "
        "128-byte EDID block (and extension blocks).",
        "3. Final read clears MOT to end the I2C transaction.",
    ]
    d["clock_recovery_sequence"] = [
        "1. Set TRAINING_PATTERN_SET=TPS1; drive initial swing/pre-emphasis.",
        "2. Wait the training interval; read LANE*_STATUS and "
        "ADJUST_REQUEST.",
        "3. Apply requested swing/pre-emphasis; repeat until all active lanes "
        "report CR_DONE or the loop-count is exhausted (then fall back).",
    ]
    d["channel_eq_sequence"] = [
        "1. Set TRAINING_PATTERN_SET=TPS2/3/4 (or UHBR pattern).",
        "2. Wait; read LANE*_STATUS + LANE_ALIGN_STATUS_UPDATED.",
        "3. Success when CHANNEL_EQ_DONE + SYMBOL_LOCKED + INTERLANE_ALIGN_DONE "
        "are set on all active lanes; else adjust or fall back.",
    ]
    d["fallback_sequence"] = [
        "1. CR or EQ fails at the requested rate/lane count.",
        "2. Reduce link rate (e.g. HBR3 -> HBR2 -> HBR -> RBR) and/or lane "
        "count.",
        "3. Restart Clock Recovery; repeat until trained or no configuration "
        "works.",
    ]
    d["mst_setup_sequence"] = [
        "1. Enable MST via MSTM_CTRL in DPCD.",
        "2. Discover topology with Sideband MSG LINK_ADDRESS / "
        "ENUM_PATH_RESOURCES.",
        "3. Allocate time slots per stream with ALLOCATE_PAYLOAD (64-slot "
        "table) and assign virtual channels.",
        "4. Stream each virtual channel in its allocated slots.",
    ]
    d["irq_hpd_sequence"] = [
        "1. Sink pulses HPD (IRQ_HPD).",
        "2. Source reads the Device Service IRQ Vector + LANE*_STATUS.",
        "3. Handle: re-train on loss of lock, service CP_IRQ for HDCP, or "
        "handle MST CONNECTION_STATUS_NOTIFY.",
    ]
    d["reset_sequence"] = [
        "1. Power-on / unplug -> Source idle, Main Link off.",
        "2. On HPD assert, re-run capability read -> EDID read -> link "
        "training -> ACTIVE.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L13 — lab / characterization targets.
# ----------------------------------------------------------------------
def _l13(gd: Path) -> None:
    p = gd / "L13_LAB_CALIBRATION.json"
    if not p.is_file():
        return
    d = _read(p)
    d["lab_calibration_present"] = False
    d["lab_measurement_targets_from_spec"] = [
        {"name": "Main Link eye diagram per rate", "purpose": "Verify the "
         "differential NRZ eye meets the budget at RBR/HBR/HBR2/HBR3 (8b/10b) "
         "and UHBR (128b/132b)."},
        {"name": "Voltage swing / pre-emphasis", "purpose": "Confirm the 4 "
         "swing and 4 pre-emphasis levels and their bounded combinations."},
        {"name": "Clock recovery / jitter", "purpose": "Confirm the Sink CDR "
         "locks (CR_DONE) and meets jitter tolerance at each rate."},
        {"name": "Inter-lane skew / alignment", "purpose": "Verify "
         "de-skew/alignment (INTERLANE_ALIGN_DONE) across active lanes."},
        {"name": "AUX channel timing", "purpose": "Validate Manchester-II "
         "~1 Mbps request/reply timing and half-duplex turnaround."},
        {"name": "EDID read", "purpose": "Confirm I2C-over-AUX EDID retrieval "
         "(I2C address A0h)."},
        {"name": "FEC / symbol-error rate", "purpose": "Confirm FEC correction "
         "and symbol/FEC-error counters when DSC/UHBR is active."},
        {"name": "Compliance (CTS)", "purpose": "Run the VESA DisplayPort "
         "Compliance Test Specification link/PHY/AUX/protocol suite."},
    ]
    d["notes"] = (
        "DisplayPort characterization centers on the Main Link PHY (eye, "
        "jitter, swing/pre-emphasis, inter-lane skew per rate), the AUX "
        "channel (Manchester-II timing), EDID/DPCD access, and FEC/error "
        "counters. Conformance is established by the VESA DisplayPort "
        "Compliance Test Specification (CTS); per-implementation PHY "
        "calibration is done at bring-up via the DPCD TEST_* automation "
        "registers.")
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
    f["spec_version"] = (
        "VESA DisplayPort (DP) Standard — DP 1.4a (2018) / DP 2.0 (2019) / "
        "DP 2.1 (2022)")
    f["previous_versions"] = [
        "DP 1.0 (2006) — RBR/HBR 8b/10b, AUX/DPCD, link training, SST.",
        "DP 1.1 (2007) — HDCP, fiber.",
        "DP 1.2 (2010) — HBR2 (5.4 Gbps/lane), MST, stereo 3D.",
        "DP 1.3 (2014) — HBR3 (8.1 Gbps/lane), 32.4 Gbps total.",
        "DP 1.4 (2016) — DSC, FEC, HDR.",
    ]
    f["key_changes"] = [
        {"version": "1.4a", "summary": "DSC 1.2a corrections on top of DP 1.4 "
         "(DSC + FEC + HDR; HBR3 8.1 Gbps/lane)."},
        {"version": "2.0", "summary": "Adds the UHBR tier (UHBR10/13.5/20 "
         "Gbps/lane) with 128b/132b coding and mandatory FEC, up to 80 Gbps "
         "total; Panel Replay; new VSC SDP usage. The 8b/10b RBR..HBR3 rates, "
         "AUX/DPCD, two-phase CR/EQ training, MSA/TU micro-packet stream, MST, "
         "and HDCP are carried forward."},
        {"version": "2.1", "summary": "Aligns DisplayPort with USB4 (DP-Alt-"
         "Mode tunneling), adds DP40/DP80 cable certification, and tightens "
         "UHBR conformance; same UHBR rates and architecture."},
    ]
    f["future_versions_industry_outline"] = [
        {"version": "Embedded DisplayPort (eDP)", "summary": "VESA's internal-"
         "panel variant with Panel Self-Refresh / Panel Replay and additional "
         "low-power features; tracks the DP main-spec generations."},
    ]
    f["backward_compat_traps"] = [
        {"trap_name": "Train_CR_before_EQ",
         "rule": "Link training is strictly Clock Recovery (TPS1) THEN Channel "
                 "Equalization (TPS2/3/4).",
         "trap": "Skipping CR or starting EQ before CR_DONE on all lanes leaves "
                 "the link untrained."},
        {"trap_name": "8b10b_vs_128b132b",
         "rule": "RBR/HBR/HBR2/HBR3 use 8b/10b; UHBR uses 128b/132b with "
                 "mandatory FEC.",
         "trap": "Assuming 8b/10b at UHBR rates (or omitting FEC at UHBR) "
                 "breaks the link."},
        {"trap_name": "FEC_required_with_DSC",
         "rule": "FEC must be enabled whenever DSC is used (and always for "
                 "UHBR).",
         "trap": "Running DSC without FEC corrupts compressed video on symbol "
                 "errors."},
        {"trap_name": "EDID_is_I2C_over_AUX_not_DPCD",
         "rule": "EDID lives in the Sink's I2C ROM (A0h) reached by "
                 "I2C-over-AUX; DPCD is a separate native-AUX space.",
         "trap": "Trying to read EDID from the DPCD address space (or vice "
                 "versa) fails."},
        {"trap_name": "Embedded_clock_not_forwarded",
         "rule": "The Main Link clock is embedded and recovered by the Sink "
                 "(no clock lane).",
         "trap": "Designing for a forwarded/source-synchronous Main Link clock "
                 "is wrong for DisplayPort."},
        {"trap_name": "Rate_lane_fallback_required",
         "rule": "On training failure the Source must fall back to a lower "
                 "rate and/or fewer lanes.",
         "trap": "Failing to implement fallback breaks interop with marginal "
                 "cables/sinks."},
    ]
    f["version_naming_history_note"] = (
        "DisplayPort is a VESA standard. DP 1.0 (2006) established the Main "
        "Link + AUX/DPCD + 8b/10b + two-phase training + SST; MST arrived in "
        "1.2 (with HBR2), HBR3 in 1.3, DSC/FEC/HDR in 1.4/1.4a, and the UHBR "
        "(128b/132b) tier in 2.0, with USB4 alignment + DP40/DP80 in 2.1. "
        "Facts here are grounded in the public VESA DisplayPort Standard "
        "(rates RBR/HBR/HBR2/HBR3 + UHBR10/13.5/20, AUX/DPCD, CR/EQ training, "
        "MSA/TU micro-packets, MST, HDCP/FEC/DSC).")
    _write(p, d)


# ----------------------------------------------------------------------
# L15 — encoding / rate / coding tables.
# ----------------------------------------------------------------------
def _l15(gd: Path) -> None:
    p = gd / "L15_ENCODING_TABLES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["link_rate_table"] = {
        "header_columns": ["Rate name", "Gbps/lane", "Channel coding",
                           "Introduced"],
        "rows": [
            ["RBR", "1.62", "8b/10b", "DP 1.0"],
            ["HBR", "2.70", "8b/10b", "DP 1.0"],
            ["HBR2", "5.40", "8b/10b", "DP 1.2"],
            ["HBR3", "8.10", "8b/10b", "DP 1.3"],
            ["UHBR10", "10.0", "128b/132b", "DP 2.0"],
            ["UHBR13.5", "13.5", "128b/132b", "DP 2.0"],
            ["UHBR20", "20.0", "128b/132b", "DP 2.0"],
        ],
    }
    f["channel_coding_table"] = {
        "header_columns": ["Coding", "Used at", "Efficiency", "FEC"],
        "rows": [
            ["8b/10b", "RBR / HBR / HBR2 / HBR3", "80%",
             "optional (required with DSC)"],
            ["128b/132b", "UHBR10 / UHBR13.5 / UHBR20", "~96.97%",
             "mandatory"],
        ],
    }
    f["aux_command_table"] = {
        "header_columns": ["Request command", "Meaning"],
        "rows": [
            ["1000b", "native Write"],
            ["1001b", "native Read"],
            ["I2C Write", "I2C-over-AUX Write"],
            ["I2C Read", "I2C-over-AUX Read"],
            ["MOT", "Middle-Of-Transaction (chain I2C burst)"],
        ],
    }
    f["aux_reply_table"] = {
        "header_columns": ["Reply", "Meaning"],
        "rows": [
            ["ACK", "native transaction accepted"],
            ["NACK", "native transaction rejected"],
            ["DEFER", "Sink busy; retry"],
            ["I2C_ACK", "I2C-over-AUX accepted"],
            ["I2C_NACK", "I2C-over-AUX rejected"],
            ["I2C_DEFER", "I2C-over-AUX busy; retry"],
        ],
    }
    f["training_pattern_table"] = {
        "header_columns": ["Pattern", "Phase", "Used at"],
        "rows": [
            ["TPS1", "Clock Recovery", "all 8b/10b rates"],
            ["TPS2", "Channel Equalization", "HBR/HBR2"],
            ["TPS3", "Channel Equalization", "HBR2"],
            ["TPS4", "Channel Equalization", "HBR3"],
            ["UHBR pattern", "CR + EQ", "UHBR (128b/132b)"],
        ],
    }
    f["dpcd_region_table"] = {
        "header_columns": ["Region", "Base address", "Key fields"],
        "rows": [
            ["Receiver Capability", "00000h",
             "DPCD_REV / MAX_LINK_RATE / MAX_LANE_COUNT / FEC / DSC"],
            ["Link Configuration", "00100h",
             "LINK_BW_SET / LANE_COUNT_SET / TRAINING_PATTERN_SET / "
             "TRAINING_LANE*_SET"],
            ["Link/Sink Status", "00200h",
             "LANE*_STATUS / LANE_ALIGN_STATUS_UPDATED / ADJUST_REQUEST / "
             "Device Service IRQ"],
        ],
    }
    f["drive_level_table"] = {
        "header_columns": ["Parameter", "Levels"],
        "rows": [
            ["Voltage swing", "4 (Level 0..3)"],
            ["Pre-emphasis", "4 (Level 0..3)"],
        ],
    }
    f["encoding_note"] = (
        "DisplayPort uses ANSI 8b/10b on the Main Link for RBR/HBR/HBR2/HBR3 "
        "(DC-balanced, transition-rich so the Sink recovers the embedded "
        "clock; 80% efficient; LFSR-scrambled) and 128b/132b for UHBR "
        "(~96.97%, FEC mandatory). The AUX channel uses Manchester-II bi-phase "
        "at ~1 Mbps. EDID is fetched by tunneling I2C-over-AUX (I2C address "
        "A0h).")
    f["tables"] = [
        "Link-rate table (RBR/HBR/HBR2/HBR3 + UHBR10/13.5/20)",
        "Channel-coding table (8b/10b vs 128b/132b)",
        "AUX command table",
        "AUX reply table",
        "Training-pattern table (TPS1..TPS4 / UHBR)",
        "DPCD region table",
        "Drive-level table (swing / pre-emphasis)",
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
        "Three channels: uni-directional Main Link (1/2/4 differential lanes), "
        "bidirectional half-duplex AUX channel, Hot Plug Detect (HPD).",
        "Main Link 8b/10b coding for RBR/HBR/HBR2/HBR3 (and 128b/132b for "
        "UHBR) with the clock embedded and recovered by the Sink.",
        "AUX channel Manchester-II at ~1 Mbps with native AUX request/reply "
        "transactions (4-bit command, 20-bit address, length).",
        "DPCD register space (Receiver Capability / Link Configuration / Link "
        "Status) accessible over native AUX.",
        "I2C-over-AUX for EDID retrieval (I2C address A0h).",
        "Two-phase Link Training: Clock Recovery (TPS1) then Channel "
        "Equalization (TPS2/3/4) with 4 voltage-swing + 4 pre-emphasis "
        "levels.",
        "Rate/lane fallback on training failure.",
        "Micro-packet stream with Transfer Units, BS/BE framing, and MSA per "
        "frame (Mvid/Nvid).",
        "SST mandatory; FEC mandatory with DSC and for UHBR.",
        "HPD with IRQ_HPD short-pulse event signaling.",
    ]
    f["must_not_have_properties"] = [
        "TMDS signaling (that is HDMI/DVI, not DisplayPort).",
        "A forwarded/source-synchronous Main Link clock lane (DisplayPort "
        "embeds and recovers the clock).",
        "Reading EDID from the DPCD address space (EDID is I2C-over-AUX).",
        "8b/10b coding at UHBR rates, or UHBR without FEC.",
        "DSC without FEC enabled.",
        "A D-PHY HS/LP escape-mode lane model (that is MIPI-DSI, not "
        "DisplayPort).",
    ]
    f["compliance_failure_modes"] = [
        {"mode": "Clock Recovery failure", "trigger": "A lane never reports "
         "CR_DONE despite swing/pre-emphasis adjustment."},
        {"mode": "Channel Equalization failure", "trigger": "CHANNEL_EQ_DONE / "
         "SYMBOL_LOCKED / INTERLANE_ALIGN_DONE not all set."},
        {"mode": "No fallback", "trigger": "Source fails to reduce rate/lane "
         "count after a training failure."},
        {"mode": "EDID read failure", "trigger": "I2C-over-AUX to A0h "
         "NACKs/defers; no display capability."},
        {"mode": "Missing FEC with DSC", "trigger": "DSC active but FEC not "
         "enabled — compressed video corrupts."},
        {"mode": "AUX transaction errors", "trigger": "Persistent NACK/DEFER "
         "or malformed Manchester framing."},
    ]
    f["min_link_constraint"] = (
        "A DisplayPort link must train at least one Main Link lane to CR_DONE "
        "+ Channel-EQ at the lowest common supported rate (RBR), with the AUX "
        "channel/DPCD operational, or it must fall back rate/lane-count; "
        "otherwise it fails to bring up.")
    f["reset_behavior_compliance"] = (
        "On HPD assert the Source reads DPCD capability and EDID, then trains "
        "the Main Link (CR then EQ, swing/pre-emphasis, rate/lane fallback) and "
        "enters ACTIVE. An IRQ_HPD prompts status re-read and possible "
        "re-training.")
    f["displayport_distinguishers"] = (
        "DisplayPort is identified by ALL of: a uni-directional Main Link of "
        "1/2/4 self-clocked AC-coupled differential lanes with an EMBEDDED "
        "clock; the RBR/HBR/HBR2/HBR3 (8b/10b) + UHBR (128b/132b) rate "
        "vocabulary; a bidirectional half-duplex Manchester-II AUX channel; "
        "the DPCD register space accessed by native AUX; I2C-over-AUX EDID "
        "retrieval; a two-phase Clock-Recovery/Channel-Equalization link "
        "training with voltage-swing/pre-emphasis; MSA/Transfer-Unit "
        "micro-packets; and MST. This is distinct from HDMI/DVI (which use "
        "TMDS, a CEC line, and an I2C DDC channel with NO AUX/DPCD) and from "
        "MIPI-DSI (which uses the D-PHY HS/LP escape-mode lane model with NO "
        "Main Link / AUX / DPCD).")
    _write(p, d)


# ----------------------------------------------------------------------
# L17 — channel / signal catalog + dependency graph.
# ----------------------------------------------------------------------
def _l17(gd: Path) -> None:
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["channels"] = [
        {"name": "Main Link (ML_Lane0..3 +/-)",
         "direction": "uni-directional Source -> Sink",
         "purpose": "Carry the video micro-packet stream.",
         "active_levels": "differential NRZ, 8b/10b (RBR..HBR3) or 128b/132b "
         "(UHBR); 1/2/4 lanes",
         "idle_level": "blanking / idle symbols; no active video until "
         "trained"},
        {"name": "AUX CH (AUX+/AUX-)",
         "direction": "bidirectional half-duplex",
         "purpose": "DPCD access / link training / I2C-over-AUX / MST "
         "sideband.",
         "active_levels": "Manchester-II ~1 Mbps request/reply",
         "idle_level": "bus released"},
        {"name": "HPD", "direction": "Sink -> Source",
         "purpose": "Hot-plug presence + IRQ_HPD event signaling.",
         "active_levels": "asserted on connect; short pulse = IRQ_HPD",
         "idle_level": "de-asserted when disconnected"},
        {"name": "CONFIG1 / CONFIG2", "direction": "connector",
         "purpose": "Cable orientation / configuration.",
         "active_levels": "static", "idle_level": "n/a"},
        {"name": "DP_PWR / GND", "direction": "supply",
         "purpose": "Auxiliary 3.3 V power and ground.",
         "active_levels": "DC rails", "idle_level": "n/a; always driven"},
    ]
    f["logical_signaling_levels"] = [
        {"name": "Active Main Link", "meaning": "Differential NRZ video "
         "micro-packets (8b/10b or 128b/132b), embedded clock."},
        {"name": "Main Link idle", "meaning": "Blanking/idle symbols (BS "
         "framing); no active video."},
        {"name": "AUX request", "meaning": "Manchester-II native/I2C request "
         "from the Source."},
        {"name": "AUX reply", "meaning": "Manchester-II ACK/NACK/DEFER reply "
         "from the Sink."},
    ]
    f["packet_types_summary"] = [
        {"class": "Main Link", "members": ["Transfer Unit (active video)",
                                           "MSA (Main Stream Attributes)",
                                           "Secondary-data packet (audio / "
                                           "SDP / InfoFrame)"], "count": 3},
        {"class": "AUX", "members": ["native AUX Read/Write",
                                     "I2C-over-AUX Read/Write",
                                     "MST Sideband MSG"], "count": 3},
    ]
    cc = _ensure_dict(f, "channel_counts")
    cc.update({
        "main_link_lanes_min": 1,
        "main_link_lanes_max": 4,
        "main_link_diff_pairs_per_lane": 1,
        "aux_pairs": 1,
        "hpd_lines": 1,
        "link_rates_count": 7,
        "voltage_swing_levels": 4,
        "pre_emphasis_levels": 4,
        "mst_time_slots": 64,
        "aux_address_bits": 20,
        "aux_command_bits": 4,
    })
    f["global_signals"] = [
        {"name": "AUX CH", "purpose": "Bidirectional half-duplex management "
         "channel for the whole link (DPCD / training / EDID / MST)."},
        {"name": "HPD", "purpose": "Hot-plug presence + IRQ_HPD events."},
        {"name": "DP_PWR", "purpose": "Auxiliary 3.3 V power rail."},
    ]
    f["dependency_graph"] = {
        "common_rule": "The AUX channel must be operational first: the Source "
        "reads DPCD capability and EDID, then trains the Main Link. The Main "
        "Link clock is embedded and recovered per lane during Clock Recovery; "
        "multi-lane links are de-skewed/aligned during Channel Equalization. "
        "HPD gates the whole sequence (no HPD -> no link).",
        "data_dependency": "Active video on the Main Link requires: (1) HPD "
        "asserted, (2) DPCD capability read, (3) link trained (CR + EQ on all "
        "active lanes), (4) FEC enabled if DSC/UHBR. The pixel clock is "
        "regenerated from the MSA Mvid/Nvid.",
    }
    f["handshake_pairs"] = [
        {"name": "AUX request/reply", "from": "Source", "to": "Sink",
         "rule": "Half-duplex native/I2C AUX transaction; reply ACK/NACK/"
         "DEFER."},
        {"name": "CR status", "from": "Sink", "to": "Source",
         "rule": "CR_DONE per lane in LANE*_STATUS gates the EQ phase."},
        {"name": "EQ status", "from": "Sink", "to": "Source",
         "rule": "CHANNEL_EQ_DONE + SYMBOL_LOCKED + INTERLANE_ALIGN_DONE gate "
         "ACTIVE."},
        {"name": "ADJUST_REQUEST", "from": "Sink", "to": "Source",
         "rule": "Sink requests per-lane voltage swing / pre-emphasis."},
        {"name": "HPD / IRQ_HPD", "from": "Sink", "to": "Source",
         "rule": "Presence + event signaling triggering status re-read."},
        {"name": "MST ALLOCATE_PAYLOAD", "from": "Source", "to": "branch",
         "rule": "Allocate time slots / virtual channel via Sideband MSG."},
    ]
    f["ordering_rules"] = {
        "bit_order_on_wire": "Differential NRZ per lane; 8b/10b 10-bit symbols "
        "(or 128b/132b blocks); LFSR-scrambled; clock embedded.",
        "stream_order": "Active video packed into Transfer Units, framed by "
        "BS/BE; MSA once per frame in vertical blanking.",
        "lane_striping": "Pixel data striped across the active Main Link lanes "
        "(1/2/4); de-skewed during EQ.",
        "aux_order": "Half-duplex: request then reply, one transaction at a "
        "time.",
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
        "Point-to-point Source -> Sink over the Main Link (1/2/4 lanes) plus a "
        "bidirectional AUX channel and HPD sideband (SST). MST extends this to "
        "a tree of Sinks via branch devices (hubs / daisy chain) with virtual "
        "channels and a 64-slot time-slot allocation.")
    f["supported_topologies"] = [
        {"name": "SST point-to-point", "description": "One Source -> one Sink "
         "over 1/2/4 Main Link lanes."},
        {"name": "MST tree", "description": "Source -> branch device -> "
         "multiple Sinks; each stream a virtual channel with allocated time "
         "slots."},
        {"name": "MST daisy chain", "description": "Sinks chained through "
         "DisplayPort-out ports (branch function)."},
        {"name": "Embedded DisplayPort (eDP)", "description": "Source -> "
         "internal panel with Panel Self-Refresh / Panel Replay."},
        {"name": "DP-Alt-Mode / USB4 tunnel", "description": "DisplayPort "
         "carried over USB-C / USB4."},
    ]
    f["master_slave_role_summary"] = [
        {"role": "Source", "description": "Drives the Main Link, masters the "
         "AUX channel, reads DPCD/EDID, trains the link, streams video."},
        {"role": "Sink", "description": "Receives the Main Link, replies on "
         "AUX, exposes DPCD + EDID, reports training status, drives HPD."},
        {"role": "Branch device", "description": "MST hub/repeater routing "
         "multiple streams via Sideband MSG and the time-slot table."},
        {"role": "AUX channel", "description": "Bidirectional half-duplex "
         "management channel shared by the link."},
    ]
    f["interconnect_role"] = (
        "DisplayPort is a Source-to-Sink display transport. The Main Link "
        "carries isochronous video uni-directionally; the AUX channel carries "
        "all management (DPCD, training, EDID, MST sideband, HDCP) "
        "bidirectionally. In MST the branch device routes multiple streams to "
        "multiple Sinks.")
    f["ordering_guarantees"] = {
        "stream_order": "Per-stream video is isochronous and in-order; "
        "Transfer-Unit / MSA framing preserves the raster.",
        "mst_arbitration": "MST allocates fixed time slots per virtual "
        "channel so streams do not starve each other.",
        "aux_order": "AUX is strictly half-duplex request/reply, one "
        "transaction at a time.",
    }
    f["memory_vs_peripheral_regions"] = (
        "DisplayPort's addressable space is the DPCD register map (20-bit AUX "
        "address) plus the I2C address space reached by I2C-over-AUX (EDID at "
        "A0h). The Main Link video stream is addressless isochronous data.")
    dc = _ensure_dict(f, "device_classification")
    dc["source"] = ("GPU/SoC DisplayPort transmitter: masters AUX, trains the "
                    "Main Link, streams video.")
    dc["sink"] = ("Monitor/panel DisplayPort receiver: exposes DPCD + EDID, "
                  "reports status, drives HPD.")
    dc["branch_device"] = ("MST hub/daisy-chain router using Sideband MSG and "
                           "the 64-slot table.")
    dc["edp_panel"] = ("Embedded DisplayPort internal panel with Panel "
                       "Replay.")
    dc["converter_dongle"] = ("DP-to-HDMI / DP-to-VGA protocol converter.")
    f["default_signal_values_evidence_tables"] = [
        "VESA DisplayPort Standard — Main Link rates (RBR/HBR/HBR2/HBR3, "
        "UHBR10/13.5/20) and lane counts (1/2/4)",
        "DPCD register-map structure (Receiver Capability / Link Configuration "
        "/ Link Status)",
        "Link-training procedure (Clock Recovery + Channel Equalization, "
        "swing/pre-emphasis)",
        "AUX transaction format (4-bit command, 20-bit address, ACK/NACK/"
        "DEFER) and I2C-over-AUX EDID",
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
        "main_link_signaling": "differential NRZ, AC-coupled, embedded clock",
        "main_link_coding": "8b/10b (RBR/HBR/HBR2/HBR3) / 128b/132b (UHBR)",
        "main_link_lanes": list(_LANE_COUNTS),
        "link_rates_Gbps_per_lane": {
            "RBR": 1.62, "HBR": 2.70, "HBR2": 5.40, "HBR3": 8.10,
            "UHBR10": 10.0, "UHBR13.5": 13.5, "UHBR20": 20.0},
        "voltage_swing_levels": 4,
        "pre_emphasis_levels": 4,
        "scrambling": "LFSR (SR scrambler-reset symbol)",
        "downspread": "supported (MAX_DOWNSPREAD / DOWNSPREAD_CTRL)",
        "aux_channel": {
            "pair": "AUX+/AUX- bidirectional half-duplex AC-coupled",
            "coding": "Manchester-II", "rate_Mbps": 1},
        "fec": "Reed-Solomon; mandatory with DSC and for UHBR",
        "connector_pins": "4 Main Link pairs + 1 AUX pair + HPD + CONFIG1/2 + "
                          "DP_PWR (3.3 V) + GND",
    }
    f["notes"] = (
        "DisplayPort is an interface specification; it fixes the Main Link "
        "electrical/coding (differential NRZ, 8b/10b or 128b/132b, embedded "
        "clock, 4 swing + 4 pre-emphasis levels), the AUX channel "
        "(Manchester-II ~1 Mbps), the DPCD register space, and the connector "
        "pin-out. It does NOT impose PDK-specific SDC/floorplan constraints — "
        "PHY characterization (SerDes/CDR, eye, jitter) and board/cable design "
        "are Source/Sink-silicon and system concerns. The "
        "interoperability-critical constraints are the link rates, lane "
        "counts, coding, training, AUX/DPCD, and connector pin-out.")
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
        {"name": "AUX channel + DPCD", "purpose": "Primary in-band "
         "controllability/observability: read capability/status, write link "
         "config, drive training — available before the Main Link is up."},
        {"name": "DPCD TEST_ automation registers", "purpose": "TEST_REQUEST "
         "/ TEST_LINK_RATE / TEST_LANE_COUNT / TEST_PATTERN let a compliance "
         "tester drive defined link/video patterns."},
        {"name": "Training/test patterns (TPS1..TPS4 / UHBR)", "purpose": "PHY "
         "eye/jitter characterization on the Main Link."},
        {"name": "Link status registers", "purpose": "CR_DONE / "
         "CHANNEL_EQ_DONE / SYMBOL_LOCKED / INTERLANE_ALIGN_DONE / "
         "ADJUST_REQUEST per lane."},
        {"name": "FEC / symbol-error counters", "purpose": "Run-time "
         "Main-Link integrity monitoring (with DSC/UHBR)."},
        {"name": "Device Service IRQ Vector", "purpose": "Identify the source "
         "of an IRQ_HPD event."},
    ]
    f["internal_diagnostics_observability"] = [
        "Link-policy state (capability-read / EDID-read / training / active).",
        "Per-lane CR/EQ training status and ADJUST_REQUEST.",
        "Negotiated link rate / lane count.",
        "FEC / symbol-error counters.",
        "MST topology (SINK_COUNT, Sideband MSG state).",
        "HDCP authentication / CP_IRQ state.",
    ]
    f["out_of_band_test_facilities"] = [
        "VESA DisplayPort Compliance Test Specification (CTS) "
        "link/PHY/AUX/protocol tools.",
        "Vendor PHY bring-up / eye-scan probes — implementation-defined.",
    ]
    f["notes"] = (
        "DisplayPort's protocol-level DFT surface is the AUX channel + DPCD "
        "(status, ADJUST_REQUEST, Device Service IRQ Vector, TEST_* "
        "automation) plus the Main-Link training/test patterns and FEC/symbol "
        "error counters. Chip-level JTAG/scan/BIST remain Source/Sink-silicon "
        "concerns; conformance is established by the VESA DisplayPort "
        "Compliance Test Specification (CTS).")
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
        {"state": "ACTIVE", "name": "Active", "description": "Main Link "
         "trained and streaming video; AUX available.",
         "exit_latency_estimate": "n/a (already active)"},
        {"state": "D3 (SET_POWER)", "name": "Low power", "description": "Sink/"
         "Source powered down via SET_POWER DPCD = D3; Main Link idle; AUX "
         "wakes it.",
         "exit_latency_estimate": "re-train on wake"},
        {"state": "Panel Replay / PSR (eDP)", "name": "Panel self-refresh",
         "description": "eDP panel holds a static frame from its own memory; "
         "the Main Link can quiesce.",
         "exit_latency_estimate": "frame-update-dominated"},
    ]
    f["low_power_modes_summary"] = {
        "active": "Full operation; Main Link streaming.",
        "d3": "SET_POWER D3 low-power; Main Link idle; AUX wake.",
        "panel_replay": "eDP self-refresh of static frames to quiesce the "
                        "link.",
    }
    f["power_rails"] = [
        {"rail": "DP_PWR", "purpose": "Auxiliary 3.3 V (e.g. for AUX / dongle "
         "/ branch device)."},
        {"rail": "core/IO", "purpose": "Source/Sink PHY and logic supplies "
         "(implementation-defined)."},
        {"rail": "GND", "purpose": "Ground."},
    ]
    f["displayport_power_considerations"] = (
        "DisplayPort manages power via the SET_POWER DPCD register (D0 active / "
        "D3 low-power) and, for eDP, Panel Self-Refresh / Panel Replay that "
        "let the panel hold a static frame so the Main Link can quiesce. The "
        "AUX channel stays available to wake the link. UHBR rates trade higher "
        "bandwidth for higher PHY power; FEC adds modest overhead.")
    f["notes"] = (
        "DisplayPort provides a link power-management framework (SET_POWER "
        "D0/D3 over DPCD; eDP Panel Replay / PSR). The AUX channel is the wake "
        "and management path. Detailed rail/domain power is a Source/Sink "
        "silicon concern; the spec defines the protocol-level power states.")
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
        "HPD detect and capability read over AUX.",
        "Native AUX transactions (Read/Write, ACK/NACK/DEFER, 20-bit "
        "address).",
        "I2C-over-AUX EDID read (A0h, MOT chaining).",
        "Link training Clock Recovery (TPS1, swing/pre-emphasis, CR_DONE).",
        "Link training Channel Equalization (TPS2/3/4, CHANNEL_EQ_DONE + "
        "SYMBOL_LOCKED + INTERLANE_ALIGN_DONE).",
        "Link-rate coverage RBR/HBR/HBR2/HBR3 + UHBR10/13.5/20.",
        "Lane-count coverage 1/2/4 and rate/lane fallback.",
        "8b/10b coding + scrambling; 128b/132b + FEC for UHBR.",
        "Micro-packet stream: Transfer Units, BS/BE framing, MSA per frame "
        "(Mvid/Nvid).",
        "Secondary-data packets (audio / SDP / InfoFrame).",
        "MST: virtual channels, 64 time-slot allocation, Sideband MSG.",
        "HDCP 1.3 / 2.2-2.3 authentication and Main-Link encryption.",
        "FEC enable with DSC; DSC capability/config via DPCD.",
        "IRQ_HPD short-pulse handling (status re-read, re-train, CP_IRQ).",
        "Power management (SET_POWER D0/D3; eDP Panel Replay).",
        "Compliance — VESA DisplayPort CTS (link / PHY / AUX / protocol).",
    ]
    f["notes"] = (
        "DisplayPort does not ship a formal RTL testbench, but the standard "
        "implies a verification plan spanning the Main Link PHY (rates, "
        "coding, training, swing/pre-emphasis, inter-lane skew), the AUX "
        "channel / DPCD (transactions, capability, status, EDID via "
        "I2C-over-AUX), the micro-packet stream (TU / MSA / secondary data), "
        "MST, and HDCP/FEC/DSC. The VESA DisplayPort Compliance Test "
        "Specification (CTS) supplies the formal conformance suite.")
    _write(p, d)


# ----------------------------------------------------------------------
# L23 — security / content protection.
# ----------------------------------------------------------------------
def _l23(gd: Path) -> None:
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["security_requirements_present"] = True
    f["anti_corruption_features"] = [
        "8b/10b disparity / invalid-symbol detection on the Main Link.",
        "FEC (Reed-Solomon) corrects symbol errors when DSC/UHBR is active "
        "(FEC_CONFIGURATION).",
        "Link-training status (CR/EQ) detects loss of lock and triggers "
        "re-training.",
        "AUX reply NACK/DEFER + retry handles management-channel errors.",
        "Symbol-error / FEC-error counters in DPCD for run-time integrity "
        "monitoring.",
    ]
    f["anti_tampering_features"] = [
        "HDCP cipher on the Main Link prevents passive interception of "
        "protected content.",
    ]
    f["confidentiality_features"] = [
        "HDCP 1.3 and 2.2/2.3 encrypt the Main Link video stream for protected "
        "content.",
    ]
    f["authentication_features"] = [
        "HDCP authentication / key exchange over the AUX channel "
        "(HDCP registers in DPCD / I2C-over-AUX HDCP port); CP_IRQ signals "
        "content-protection events.",
    ]
    f["future_security_pointers"] = [
        "HDCP 2.3 strengthens the authentication/locality checks over the "
        "earlier HDCP versions.",
        "DisplayPort over USB4 inherits USB4 tunneling security at the "
        "transport layer.",
    ]
    f["notes"] = (
        "DisplayPort's content security is HDCP (1.3 and 2.2/2.3): "
        "authentication and key exchange ride the AUX channel and the cipher "
        "encrypts the Main Link stream; CP_IRQ events are signaled via the "
        "Device Service IRQ Vector / IRQ_HPD. Link integrity is provided by "
        "8b/10b disparity checking and FEC (with DSC/UHBR). The base "
        "DisplayPort data path is otherwise plaintext display data; "
        "confidentiality is provided only when HDCP is enabled.")
    _write(p, d)
