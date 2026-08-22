"""VESA Embedded DisplayPort (eDP) protocol synth helper.

v0.1.95 — ic_class-gated overlay for the EMBEDDED variant of DisplayPort: a
VESA digital display interface for the INTERNAL panel connection (laptop /
tablet / all-in-one / embedded). eDP reuses the DisplayPort base — Main Link
(1/2/4 self-clocked AC-coupled differential lanes, RBR/HBR/HBR2/HBR3 8b/10b),
a bidirectional half-duplex Manchester-II AUX channel into the DPCD register
space, I2C-over-AUX EDID, and two-phase Clock-Recovery / Channel-Equalization
link training — and ADDS the eDP-EXCLUSIVE feature set that an external
DisplayPort link does not have:

  * Panel Self Refresh (PSR / PSR2): the panel keeps a local copy of the last
    frame in a Remote Frame Buffer (RFB) and refreshes the display from the RFB
    while the Source GPU and the Main Link sleep; PSR2 adds selective update.
  * Backlight control over AUX: panel backlight brightness via the eDP backlight
    DPCD registers (PWM + AUX brightness).
  * Fast Link Training (FLT): an abbreviated training sequence for an embedded
    panel whose channel is fixed/characterized.
  * ASSR (Alternate Scrambler Seed Reset): the eDP content-protection scrambler
    seed used in place of the standard DisplayPort seed.
  * an eDP-specific DPCD register block (eDP Configuration Capability, eDP
    revision, backlight, PSR, RFB) and embedded-panel low-power states.

eDP DROPS the external-connector DisplayPort features: there is NO external
connector, NO Multi-Stream Transport (MST) / multi-monitor daisy chain, and NO
cable-orientation. Applies VESA Embedded DisplayPort (eDP 1.4b / 1.5) canonical
content to L1-L23.

Doctrine — GENERAL not keyword: detection (``is_edp``) uses canonical STRUCTURAL
signatures read ONLY from the L-doc CONTENT blob. It requires the DisplayPort
base (Main Link + AUX + DPCD) AND eDP-EXCLUSIVE structure (PSR/RFB +
backlight-over-AUX + ASSR + Fast Link Training + embedded panel). It NEVER reads
the input-document filename or the benchmark folder name.

Sibling MUTEX — eDP EXTENDS DisplayPort. The existing ``displayport`` detector
covers the EXTERNAL variant and fires on the shared Main Link + AUX + DPCD +
CR/EQ base. ``is_edp`` therefore REQUIRES the eDP-only vocabulary that a plain
external-DisplayPort spec LACKS — Panel Self Refresh / Remote Frame Buffer,
backlight-over-AUX, ASSR, Fast Link Training, and an embedded panel — and
DEFERS when the doc is external-DisplayPort-primary (MST / external connector /
no PSR / no ASSR / no embedded panel). It also DEFERS for HDMI-primary (TMDS)
and MIPI-DSI-primary (D-PHY escape-mode) display siblings, which lack the
DisplayPort Main-Link/AUX base entirely.

Sibling collision note: ``is_displayport`` DOES fire on an eDP doc (the shared
Main Link + AUX + DPCD + CR/EQ base satisfies the DisplayPort signature), so the
DisplayPort synth will populate the L-docs with DisplayPort-canonical values
FIRST. Because eDP is a DIFFERENT (derived) protocol, this module
FORCE-OVERWRITES (direct assignment, NOT setdefault) every L1-L23 key with the
eDP-canonical value, and the runner calls ``apply_edp_synth`` AFTER
``apply_displayport_synth`` so the eDP overwrites win.

Public entry: ``apply_edp_synth(generated_docs_dir, is_edp, edp_ic_name)``.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

import l_doc_generator_stamp as _stamp


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


def _has_word(blob_low: str, *tokens: str) -> bool:
    """Word-boundary token search (case-insensitive blob already lowered)."""
    for t in tokens:
        if re.search(r"(?<![a-z0-9])" + re.escape(t.lower()) + r"(?![a-z0-9])",
                     blob_low):
            return True
    return False


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

# Canonical eDP structural facts (VESA eDP 1.4b / 1.5).
_LANE_COUNTS = [1, 2, 4]
_RATES_8B10B = {"RBR": 1.62, "HBR": 2.70, "HBR2": 5.40, "HBR3": 8.10}


# ----------------------------------------------------------------------
# Detector — content-only; DisplayPort-MUTEX (eDP EXTENDS DisplayPort).
# ----------------------------------------------------------------------
def is_edp(blob: str) -> bool:
    """VESA Embedded DisplayPort (eDP) — internal-panel display interface.

    Content-only structural signature. Requires the DisplayPort base (Main Link
    + AUX + DPCD) AND eDP-EXCLUSIVE structure (Panel Self Refresh / Remote Frame
    Buffer + backlight-over-AUX + ASSR + Fast Link Training + embedded panel).

    MUTEX:
      * external-DisplayPort-primary -> DEFER (MST / external connector with NO
        PSR / NO ASSR / NO embedded panel).
      * HDMI-primary (TMDS, no AUX/DPCD) -> DEFER.
      * MIPI-DSI-primary (D-PHY escape-mode, no Main-Link/AUX) -> DEFER.
    """
    if not blob:
        return False
    low = blob.lower()

    # --- DisplayPort base (shared with external DP) ---
    has_main_link = "main link" in low
    has_aux = "aux ch" in low or "aux channel" in low or "i2c-over-aux" in low
    has_dpcd = "dpcd" in low or "displayport configuration data" in low
    dp_base = has_main_link and has_aux and has_dpcd
    if not dp_base:
        return False

    # --- eDP-EXCLUSIVE structural discriminators ---
    # Panel Self Refresh + Remote Frame Buffer (the defining eDP feature).
    has_psr = (
        "panel self refresh" in low or "panel self-refresh" in low
        or _has_word(low, "psr", "psr2")
    )
    has_rfb = (
        "remote frame buffer" in low or _has_word(low, "rfb")
    )
    psr_rfb = has_psr and has_rfb
    # Backlight control over AUX (eDP backlight DPCD).
    has_backlight_aux = (
        ("backlight" in low and ("over aux" in low or "aux" in low) and
         ("dpcd" in low or "edp_backlight" in low or "brightness" in low))
        or "edp_backlight_brightness" in low
        or "edp_backlight_mode_set" in low
    )
    # ASSR (Alternate Scrambler Seed Reset) — eDP scrambler.
    has_assr = (
        _has_word(low, "assr")
        or "alternate scrambler seed reset" in low
        or "alternate scrambler seed" in low
    )
    # Fast Link Training (eDP abbreviated training).
    has_flt = (
        "fast link training" in low or _has_word(low, "flt")
        or "fast_link_training" in low
    )
    # Embedded panel context.
    has_embedded_panel = (
        "embedded displayport" in low or "embedded panel" in low
        or "internal panel" in low
        or ("embedded" in low and "panel" in low and "edp" in low)
        or ("edp" in low and "tcon" in low)
    )

    # eDP signature: the DisplayPort base PLUS strong eDP-exclusive evidence.
    # Require PSR+RFB (the defining feature) AND at least two of the other
    # eDP-only discriminators so neither a plain external-DisplayPort spec nor a
    # DP spec that merely mentions "eDP" in passing can satisfy it.
    edp_exclusive_extra = sum(
        [bool(has_backlight_aux), bool(has_assr), bool(has_flt),
         bool(has_embedded_panel)]
    )
    edp_signature = psr_rfb and edp_exclusive_extra >= 2
    if not edp_signature:
        return False

    # --- Sibling MUTEX ---
    # HDMI-primary: TMDS present and AUX/DPCD absent. (dp_base already requires
    # AUX+DPCD, so this is a belt-and-braces guard.)
    hdmi_primary = ("tmds" in low) and (not has_aux) and (not has_dpcd)
    if hdmi_primary:
        return False
    # MIPI-DSI-primary: D-PHY / escape-mode while the DP Main-Link / AUX absent.
    dsi_primary = (
        ("d-phy" in low or "escape mode" in low or "escape-mode" in low)
        and (not has_main_link) and (not has_aux)
    )
    if dsi_primary:
        return False
    # External-DisplayPort-primary: an external connector / MST-centric doc that
    # has NONE of the eDP-exclusive features. Because edp_signature already
    # demanded PSR+RFB + 2 more eDP-only features, an external-DP-primary doc
    # cannot reach here; this final guard makes the intent explicit — if the doc
    # is unmistakably the external connector standard with MST AND lacks the
    # eDP-defining PSR/RFB, defer.
    external_dp_primary = (
        ("multi-stream transport" in low or _has_word(low, "mst"))
        and ("external connector" in low or "external displayport" in low)
        and not psr_rfb
    )
    if external_dp_primary:
        return False

    return True


def apply_edp_synth(generated_docs_dir: Path, is_edp: bool,
                    edp_ic_name: Optional[str]) -> None:
    """Apply VESA Embedded DisplayPort (eDP) synth when the eDP signature matched.

    FORCE-OVERWRITES (direct assignment) every L1-L23 key. Because
    ``is_displayport`` also fires on an eDP doc and the DisplayPort synth runs
    FIRST (populating the docs with external-DisplayPort values), the runner
    calls this AFTER ``apply_displayport_synth`` so the eDP-canonical overwrites
    win.
    """
    if not is_edp:
        return
    gd = Path(generated_docs_dir)

    # --- Force ic_name across ALL 24 docs FIRST (main + fields docs). ---
    if edp_ic_name is not None:
        for n in _MAIN_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                d["ic_name"] = edp_ic_name
                _write(q, d)
        for n in _FIELDS_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                f = _ensure_dict(d, "fields")
                f["ic_name"] = edp_ic_name
                d["ic_name"] = edp_ic_name  # belt-and-braces top-level
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
# L1 — eDP datasheet header + Main Link / AUX / PSR / backlight facts.
# ----------------------------------------------------------------------
def _l1(gd: Path) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    d["document_title"] = "VESA Embedded DisplayPort (eDP) Standard"
    d["version"] = "eDP 1.4b / 1.5"
    d["revised_date"] = "2015 (1.4b) / 2021 (1.5)"
    d["manufacturer"] = "Video Electronics Standards Association (VESA)"
    d["copyright"] = "© VESA"
    d["abstract"] = (
        "Embedded DisplayPort (eDP) is the VESA digital display interface for "
        "the INTERNAL panel connection inside a notebook, tablet, all-in-one, "
        "or embedded system. It connects an on-board display Source (GPU / SoC "
        "display controller) to the integrated panel (the eDP Sink / Timing "
        "Controller, TCON) over a short internal flex cable, replacing the "
        "legacy internal LVDS panel interface. eDP is built on the VESA "
        "DisplayPort base and reuses the Main Link (1/2/4 self-clocked "
        "AC-coupled differential lanes, RBR 1.62 / HBR 2.7 / HBR2 5.4 / HBR3 "
        "8.1 Gbps/lane, 8b/10b, embedded clock), the bidirectional half-duplex "
        "Manchester-II AUX channel into the DPCD register space, I2C-over-AUX "
        "EDID, and two-phase Clock-Recovery / Channel-Equalization link "
        "training. eDP ADDS the eDP-EXCLUSIVE feature set: Panel Self Refresh "
        "(PSR / PSR2) with a panel-local Remote Frame Buffer (RFB) so the panel "
        "refreshes itself while the Source and Main Link sleep, backlight "
        "control over AUX (eDP backlight DPCD registers + PWM), Fast Link "
        "Training (FLT), ASSR (Alternate Scrambler Seed Reset) content "
        "protection, and an eDP-specific DPCD register block. eDP DROPS the "
        "external-connector DisplayPort features — there is NO external "
        "connector and NO Multi-Stream Transport (MST).")
    d["keywords"] = [
        "Embedded DisplayPort", "eDP", "VESA", "internal panel", "Main Link",
        "AUX channel", "DPCD", "EDID", "I2C-over-AUX", "link training",
        "Clock Recovery", "Channel Equalization", "Fast Link Training", "FLT",
        "Panel Self Refresh", "PSR", "PSR2", "Remote Frame Buffer", "RFB",
        "selective update", "backlight over AUX", "ASSR",
        "Alternate Scrambler Seed Reset", "voltage swing", "pre-emphasis",
        "RBR", "HBR", "HBR2", "HBR3", "8b/10b", "MSA", "Transfer Unit",
        "micro-packet", "TCON", "Source", "Sink", "HPD",
    ]
    d["external_pins"] = [
        "ML_Lane0(+/-), ML_Lane1(+/-), ML_Lane2(+/-), ML_Lane3(+/-) — up to "
        "four Main Link differential pairs (AC-coupled, self-clocked, embedded "
        "clock; 1/2/4 lanes used per panel)",
        "AUX_CH(+/-) — one bidirectional half-duplex differential pair "
        "(Manchester-II, 1 Mbps) for DPCD / link-training / I2C-over-AUX / "
        "backlight-over-AUX / PSR control",
        "HPD — Hot Plug Detect, single-ended sideband input to the Source "
        "(presence + IRQ_HPD events)",
        "BL_PWM / BL_EN — optional backlight PWM and enable (when the backlight "
        "is not fully AUX-controlled)",
        "VDD (panel logic), VBL (backlight), GND — panel and backlight power "
        "and ground",
    ]
    d.pop("external_pin_count", None)
    d["external_main_link_lanes_max"] = 4
    d["supported_lane_counts"] = list(_LANE_COUNTS)
    d["supported_link_rates_Gbps_per_lane"] = dict(_RATES_8B10B)
    d["modes_of_operation"] = [
        {"name": "Active (live refresh)",
         "description": "The Source streams video to the panel over the Main "
         "Link; one Sink (the integrated panel)."},
        {"name": "Panel Self Refresh (PSR)",
         "description": "On a static screen the panel refreshes from its local "
         "Remote Frame Buffer (RFB) while the Source GPU and Main Link sleep."},
        {"name": "PSR2 (selective update)",
         "description": "On exit only the changed rectangular region(s) "
         "(Selective Update / SU region) are re-transmitted into the RFB."},
        {"name": "Fast Link Training",
         "description": "Abbreviated training using stored drive settings for "
         "the fixed embedded channel (fast panel power-on / PSR exit)."},
        {"name": "8b/10b legacy rates (RBR/HBR/HBR2/HBR3)",
         "description": "1.62 / 2.7 / 5.4 / 8.1 Gbps/lane, ANSI 8b/10b, LFSR "
         "scrambled (ASSR alternate seed when enabled)."},
    ]
    d["key_features"] = [
        "VESA embedded digital display interface: Source-to-internal-panel "
        "isochronous video over a packetized Main Link (DisplayPort base).",
        "Three functional channels: Main Link (1/2/4 self-clocked AC-coupled "
        "differential lanes), bidirectional half-duplex AUX channel, HPD.",
        "Link rates RBR 1.62 / HBR 2.7 / HBR2 5.4 / HBR3 8.1 Gbps/lane with "
        "ANSI 8b/10b coding and embedded clock recovery.",
        "AUX channel: Manchester-II bi-phase ~1 Mbps native AUX transactions "
        "(4-bit command, 20-bit address, length) into the DPCD register space, "
        "plus I2C-over-AUX for EDID.",
        "Two-phase Link Training (Clock Recovery then Channel Equalization with "
        "4 voltage-swing / 4 pre-emphasis levels) AND Fast Link Training (FLT) "
        "for the fixed embedded channel.",
        "Panel Self Refresh (PSR): the panel keeps the last frame in a local "
        "Remote Frame Buffer (RFB) and refreshes itself while the Source and "
        "Main Link sleep — major battery saving.",
        "PSR2 selective update: only the changed region(s) are re-transmitted "
        "into the RFB on exit.",
        "Backlight control over AUX: panel backlight brightness via the eDP "
        "backlight DPCD registers (EDP_BACKLIGHT_MODE_SET / "
        "EDP_BACKLIGHT_BRIGHTNESS / PWM generator config).",
        "ASSR (Alternate Scrambler Seed Reset): eDP content-protection "
        "scrambler seed used in place of the standard DisplayPort seed.",
        "eDP-specific DPCD register block (base 00700h): eDP_DPCD_REV, "
        "eDP_CONFIGURATION_CAP (ASSR / Fast-Link-Training), eDP_GENERAL_CAP "
        "(PSR / backlight), backlight + PSR registers.",
        "NO external connector and NO Multi-Stream Transport (MST): the "
        "embedded panel is a single Sink.",
    ]
    d["topology_summary"] = (
        "Point-to-point Source -> single embedded panel Sink over the Main Link "
        "(1/2/4 lanes) plus a bidirectional AUX channel and an HPD sideband, "
        "carried on a short internal flex cable. There is no external connector "
        "and no MST tree — the panel is a fixed, co-designed internal device.")
    d["package_summary"] = (
        "eDP is an interface standard, not a single packaged IC; it specifies "
        "the internal flex / board-to-board connection (up to 4 Main Link "
        "pairs, 1 AUX pair, HPD, optional backlight PWM, panel/backlight power), "
        "the Main Link electrical/coding (8b/10b), the AUX protocol, the DPCD "
        "register space including the eDP-specific block (PSR / backlight / "
        "ASSR / Fast Link Training), and the PSR/RFB self-refresh architecture. "
        "The Source display controller and the panel TCON (eDP Sink) implement "
        "it.")
    d["use_cases"] = [
        "Notebook / laptop internal panel link (replacing LVDS)",
        "Tablet and 2-in-1 integrated display link",
        "All-in-one (AIO) desktop integrated panel",
        "Embedded / industrial / automotive integrated display",
        "Battery-optimized static-screen operation via Panel Self Refresh",
        "High-resolution panels with DSC over the embedded link",
    ]
    d["revision_history"] = [
        {"version": "1.0", "date": "2008",
         "description": "First embedded variant of DisplayPort for internal "
         "panels."},
        {"version": "1.1", "date": "2009",
         "description": "Backlight control, ASSR, additional panel power "
         "features."},
        {"version": "1.2", "date": "2010",
         "description": "Additional link rates, multi-touch sideband."},
        {"version": "1.3", "date": "2011",
         "description": "Panel Self Refresh (PSR) introduced; Remote Frame "
         "Buffer (RFB)."},
        {"version": "1.4", "date": "2013",
         "description": "PSR2 (selective update), additional link rates, DSC, "
         "reduced-swing electrical option."},
        {"version": "1.4a", "date": "2015",
         "description": "PSR2 selective-update clarifications."},
        {"version": "1.4b", "date": "2015", "description": "Corrections / "
         "errata."},
        {"version": "1.5", "date": "2021",
         "description": "Panel Replay alignment with DP 2.0, enhanced PSR2, "
         "additional panel power-optimization features."},
    ]
    d["overview"] = (
        "Embedded DisplayPort (eDP) is the VESA digital display interface for "
        "the INTERNAL panel of a notebook / tablet / all-in-one / embedded "
        "system. It connects an on-board Source (GPU / SoC display controller) "
        "to the integrated panel Sink (Timing Controller, TCON) over a short "
        "internal flex cable. eDP reuses the DisplayPort base — a Main Link of "
        "1/2/4 self-clocked AC-coupled differential lanes (RBR 1.62 / HBR 2.7 / "
        "HBR2 5.4 / HBR3 8.1 Gbps/lane, 8b/10b, embedded clock recovered during "
        "training), a bidirectional half-duplex Manchester-II AUX channel into "
        "the DPCD register space, I2C-over-AUX EDID, and two-phase Clock-"
        "Recovery / Channel-Equalization training — and ADDS the eDP-EXCLUSIVE "
        "feature set: Panel Self Refresh (PSR / PSR2), where the panel keeps the "
        "last frame in a local Remote Frame Buffer (RFB) and refreshes itself "
        "while the Source and Main Link sleep (PSR2 adds selective update of "
        "only the changed region); backlight control over AUX through eDP "
        "backlight DPCD registers; Fast Link Training (FLT) using stored drive "
        "settings for the fixed embedded channel; ASSR (Alternate Scrambler "
        "Seed Reset) content protection; and an eDP-specific DPCD register "
        "block. eDP DROPS the external DisplayPort connector and Multi-Stream "
        "Transport — the embedded panel is a single Sink.")
    _write(p, d)


# ----------------------------------------------------------------------
# L2 — FRS: three-channel embedded Source/panel model + eDP features.
# ----------------------------------------------------------------------
def _l2(gd: Path) -> None:
    p = gd / "L2_FRS.json"
    if not p.is_file():
        return
    d = _read(p)
    po = _ensure_dict(d, "protocol_overview")
    po["type"] = (
        "VESA embedded digital display interface (Embedded DisplayPort). "
        "Source -> single internal-panel Sink isochronous video over a "
        "packetized Main Link (1/2/4 self-clocked differential lanes), with a "
        "bidirectional half-duplex AUX channel for management (DPCD / link "
        "training / I2C-over-AUX EDID / backlight-over-AUX / PSR control) and a "
        "Hot Plug Detect (HPD) sideband.")
    po["duplex"] = (
        "Main Link is uni-directional (Source -> panel). AUX channel is "
        "bidirectional half-duplex (request from Source, reply from panel Sink "
        "over the same pair). HPD is a Sink -> Source sideband.")
    po["synchronous_serial"] = False
    po["source_synchronous"] = False
    po["embedded_clock"] = True
    po["forwarded_clock"] = False
    po["encoding"] = (
        "Main Link: ANSI 8b/10b for RBR/HBR/HBR2/HBR3 (DC-balanced, "
        "transition-rich, 80% efficient, LFSR-scrambled with the ASSR alternate "
        "seed when enabled) with the clock embedded and recovered by the panel "
        "Sink during training. AUX channel: Manchester-II bi-phase at ~1 Mbps.")
    po["modulation"] = "NRZ (two-level) differential on Main Link and AUX."
    po["main_link_lanes_supported"] = list(_LANE_COUNTS)
    po["link_rates_Gbps_per_lane"] = dict(_RATES_8B10B)
    po["channels"] = ["Main Link", "AUX CH", "Hot Plug Detect (HPD)"]
    po["aux_channel"] = {
        "type": "bidirectional half-duplex differential pair (AUX+/AUX-)",
        "coding": "Manchester-II bi-phase",
        "rate_Mbps": 1,
        "model": "request/reply native AUX transactions into DPCD; "
                 "I2C-over-AUX for EDID; backlight-over-AUX; PSR control",
    }
    po["link_training"] = {
        "full_phase_1": "Clock Recovery (CR) — TPS1, adjust voltage swing / "
                        "pre-emphasis until CR_DONE on all active lanes",
        "full_phase_2": "Channel Equalization (EQ) — TPS2/3/4, until "
                        "CHANNEL_EQ_DONE + SYMBOL_LOCKED + INTERLANE_ALIGN_DONE",
        "fast_link_training": "FLT — apply stored drive/rate/lane settings and "
                              "send training patterns for a short fixed "
                              "interval (fixed embedded channel)",
        "control": "over AUX via TRAINING_PATTERN_SET and per-lane status "
                   "readback in DPCD",
        "fallback": "FLT -> full CR/EQ; then lower link rate and/or fewer lanes",
    }
    po["edp_exclusive_features"] = {
        "panel_self_refresh": "PSR / PSR2 — panel refreshes from a local Remote "
                              "Frame Buffer (RFB) while the Source and Main Link "
                              "sleep; PSR2 adds selective update.",
        "remote_frame_buffer": "RFB — panel-local store of the last frame.",
        "backlight_over_aux": "Panel backlight brightness set via eDP backlight "
                              "DPCD registers (PWM + AUX brightness).",
        "assr": "Alternate Scrambler Seed Reset — eDP scrambler seed for "
                "content protection.",
        "fast_link_training": "Abbreviated training for the fixed embedded "
                              "channel.",
        "edp_specific_dpcd": "eDP Configuration Capability block (base 00700h).",
    }
    po["stream_framing"] = (
        "micro-packet stream: Main Stream Attributes (MSA) per frame, Transfer "
        "Units (TU) for active video, BS/BE blanking-symbol framing, "
        "secondary-data (audio / SDP / PSR-setup) packets in the blanking "
        "intervals.")
    po["transport_modes"] = ["Single embedded panel (no MST)"]
    d["functional_requirements"] = [
        {"id": "FR-CH-01", "text": "An eDP link comprises three channels: a "
         "uni-directional Main Link (1/2/4 lanes) for video, a bidirectional "
         "half-duplex AUX channel for management, and a Hot Plug Detect (HPD) "
         "sideband — connecting the Source to a single internal panel Sink."},
        {"id": "FR-LANE-02", "text": "The Main Link is configurable to 1, 2, or "
         "4 lanes (LANE_COUNT_SET in DPCD); each lane is a self-clocked "
         "AC-coupled differential pair on the internal flex."},
        {"id": "FR-RATE-03", "text": "The Main Link runs at one of RBR 1.62, "
         "HBR 2.7, HBR2 5.4, or HBR3 8.1 Gbps/lane (8b/10b), set in LINK_BW_SET "
         "(eDP may also use intermediate eDP link rates from the eDP "
         "supported-rates table)."},
        {"id": "FR-CODE-04", "text": "RBR/HBR/HBR2/HBR3 use ANSI 8b/10b coding "
         "(DC-balanced, transition-rich, LFSR-scrambled) with the clock "
         "embedded; the ASSR alternate scrambler seed is used when enabled."},
        {"id": "FR-TRAIN-05", "text": "Before video the Source trains the Main "
         "Link, either by Fast Link Training (apply stored drive settings for "
         "the fixed channel) or by full two-phase Clock Recovery + Channel "
         "Equalization, falling back FLT -> full -> lower rate/lane on "
         "failure."},
        {"id": "FR-AUX-06", "text": "The AUX channel is a bidirectional "
         "half-duplex differential pair using Manchester-II coding at ~1 Mbps "
         "with a request/reply transaction model (4-bit command, 20-bit "
         "address, length)."},
        {"id": "FR-DPCD-07", "text": "Native AUX transactions read/write the "
         "panel's DPCD (Receiver Capability 00000h, Link Configuration 00100h, "
         "Link/Sink Status 00200h) AND the eDP-specific DPCD block at 00700h."},
        {"id": "FR-EDID-08", "text": "I2C-over-AUX tunnels I2C transactions "
         "(MOT bit chains bursts) to read the panel EDID (I2C address A0h)."},
        {"id": "FR-PSR-09", "text": "eDP provides Panel Self Refresh (PSR): the "
         "panel stores the last frame in a local Remote Frame Buffer (RFB) and "
         "refreshes from it while the Source and Main Link sleep; PSR2 adds "
         "selective update of only the changed region. PSR is controlled via "
         "the eDP DPCD (PSR_ENABLE / PSR_CONFIGURATION / PSR_STATUS)."},
        {"id": "FR-BL-10", "text": "eDP controls the panel backlight over AUX "
         "via the eDP backlight DPCD registers (EDP_BACKLIGHT_MODE_SET, "
         "EDP_BACKLIGHT_BRIGHTNESS, EDP_PWMGEN_BIT_COUNT, EDP_BACKLIGHT_FREQ_"
         "SET) and/or a backlight PWM pin."},
        {"id": "FR-ASSR-11", "text": "eDP supports ASSR (Alternate Scrambler "
         "Seed Reset): when enabled (eDP_CONFIGURATION_CAP) the Main Link "
         "scrambler is reset with the alternate seed for content protection "
         "between the co-designed Source and panel."},
        {"id": "FR-NOMST-12", "text": "eDP does NOT implement Multi-Stream "
         "Transport: the embedded panel is a single Sink, so there are no "
         "virtual channels, no MST time-slot table, and no branch / daisy-chain "
         "devices; there is no external connector."},
        {"id": "FR-HPD-13", "text": "The panel Sink drives HPD to indicate "
         "presence; a short HPD pulse (IRQ_HPD) signals link-status-change or "
         "PSR-state-change events requiring a status re-read."},
    ]
    d["error_response_conditions"] = [
        "AUX reply NACK / DEFER — panel rejects or defers a native AUX "
        "transaction; the Source retries.",
        "I2C-over-AUX I2C_NACK / I2C_DEFER — the tunneled EDID I2C ROM "
        "NACKs/defers.",
        "Fast Link Training failure — stored settings do not lock; fall back to "
        "full CR/EQ training.",
        "Clock Recovery failure — a lane never reports CR_DONE; raise "
        "swing/pre-emphasis or fall back rate/lane-count.",
        "Channel Equalization failure — CHANNEL_EQ_DONE / SYMBOL_LOCKED / "
        "INTERLANE_ALIGN_DONE not all set; fall back and re-train.",
        "PSR exit failure — panel fails to re-establish the link on update; the "
        "Source re-trains (Fast Link Training) and re-transmits.",
    ]
    d["compliance_requirements"] = [
        "Main Link of 1/2/4 self-clocked AC-coupled differential lanes with "
        "8b/10b coding (RBR..HBR3) and embedded clock.",
        "Bidirectional half-duplex Manchester-II AUX channel with the native "
        "AUX request/reply transaction model.",
        "DPCD register space (Receiver Capability / Link Configuration / Link "
        "Status) plus the eDP-specific DPCD block (eDP_CONFIGURATION_CAP / "
        "backlight / PSR).",
        "I2C-over-AUX for panel EDID retrieval.",
        "Link Training: full two-phase CR/EQ and Fast Link Training (FLT).",
        "Panel Self Refresh (PSR / PSR2) with a Remote Frame Buffer (RFB).",
        "Backlight control over AUX (eDP backlight DPCD registers / PWM).",
        "ASSR (Alternate Scrambler Seed Reset) when enabled.",
        "Single embedded panel Sink — NO Multi-Stream Transport, NO external "
        "connector.",
        "Hot Plug Detect (HPD) including IRQ_HPD short-pulse event signaling.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L3 — channels / AUX transaction / PSR / micro-packet framing.
# ----------------------------------------------------------------------
def _l3(gd: Path) -> None:
    p = gd / "L3_CMD_PROTOCOL.json"
    if not p.is_file():
        return
    d = _read(p)
    d["protocol_type"] = (
        "Packetized embedded-display protocol with two transports. The Main "
        "Link is a uni-directional micro-packet video stream (Transfer Units + "
        "MSA, 8b/10b coded, embedded clock) to a single internal panel. The AUX "
        "channel is a bidirectional half-duplex request/reply transaction "
        "protocol (Manchester-II, ~1 Mbps) carrying native AUX accesses to the "
        "DPCD (including the eDP-specific block), I2C-over-AUX (EDID), backlight "
        "control, PSR control, and link-training control.")
    d["channels"] = [
        {"name": "Main Link (ML_Lane0..3)",
         "direction": "uni-directional Source -> panel Sink",
         "description": "1/2/4 self-clocked AC-coupled differential lanes; "
         "8b/10b at RBR/HBR/HBR2/HBR3; embedded clock recovered by the panel "
         "during training; carries the micro-packet video stream."},
        {"name": "AUX CH (AUX+/AUX-)",
         "direction": "bidirectional half-duplex",
         "description": "Manchester-II bi-phase differential pair at ~1 Mbps; "
         "native AUX request/reply transactions into DPCD + eDP-specific block, "
         "I2C-over-AUX EDID, backlight-over-AUX, and PSR control."},
        {"name": "Hot Plug Detect (HPD)",
         "direction": "panel Sink -> Source sideband",
         "description": "Indicates presence; a short pulse (IRQ_HPD) signals "
         "link-status-change / PSR-state-change events."},
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
        {"name": "eDP-specific DPCD block", "base": "00700h",
         "fields": "eDP_DPCD_REV, eDP_CONFIGURATION_CAP (ASSR / Fast Link "
                   "Training / OUI), eDP_GENERAL_CAP (PSR / backlight), "
                   "backlight registers (EDP_BACKLIGHT_MODE_SET / "
                   "EDP_BACKLIGHT_BRIGHTNESS / EDP_PWMGEN_BIT_COUNT / "
                   "EDP_BACKLIGHT_FREQ_SET), PSR registers (PSR_ENABLE / "
                   "PSR_CONFIGURATION / PSR_STATUS / PSR2_ENABLE / SU region / "
                   "RFB control)"},
    ]
    d["i2c_over_aux"] = {
        "purpose": "tunnel I2C transactions over AUX to reach the panel EDID",
        "edid_i2c_address": "A0h (read A1h)",
        "mot_bit": "Middle-Of-Transaction bit chains a multi-byte I2C burst",
        "edid_block_bytes": 128,
    }
    d["main_link_framing"] = {
        "active_video": "packed into Transfer Units (TU, typically 32 or 64 "
                        "symbols/lane; remainder stuffed with Fill)",
        "blanking_framing": "BS (Blanking Start) / BE (Blanking End) control "
                            "(K) symbols delimit active line data",
        "secondary_data": "SS/SE delimit secondary-data packets (audio sample "
                          "packets, MSA, VSC SDP / InfoFrames, PSR-setup "
                          "packets) in the blanking intervals",
        "msa": "Main Stream Attributes once per frame (Mvid/Nvid, Htotal/"
               "Vtotal, HSP/HSW, active width/height, MISC0/MISC1)",
        "control_symbols": ["BS", "BE", "SR (Scrambler Reset)", "SS", "SE",
                            "FS", "FE"],
    }
    d["psr_control"] = {
        "transport": "eDP DPCD over AUX (PSR_ENABLE / PSR_CONFIGURATION / "
                     "PSR_STATUS / PSR2_ENABLE)",
        "remote_frame_buffer": "panel-local RFB stores the last frame",
        "entry": "Source enables PSR, transmits a final frame, quiesces the "
                 "Main Link; panel latches the RFB and self-refreshes",
        "exit": "on update / IRQ_HPD, Source re-trains (Fast Link Training) and "
                "re-transmits (full frame, or PSR2 selective-update region)",
        "psr2_selective_update": "only the changed rectangular SU region(s) are "
                                 "re-transmitted into the RFB",
    }
    d["backlight_control"] = {
        "transport": "eDP backlight DPCD registers over AUX",
        "registers": ["EDP_BACKLIGHT_MODE_SET", "EDP_BACKLIGHT_BRIGHTNESS_MSB",
                      "EDP_BACKLIGHT_BRIGHTNESS_LSB", "EDP_PWMGEN_BIT_COUNT",
                      "EDP_BACKLIGHT_FREQ_SET"],
        "pwm": "panel PWM generator under AUX/DPCD control, or a dedicated "
               "backlight PWM pin",
    }
    d["mst_messaging"] = None
    d["mst_supported"] = False
    d["burst_based"] = False
    d["byte_oriented"] = True
    d["packet_oriented"] = True
    d["addressing"] = {
        "aux_address_bits": 20,
        "space": "DPCD register address space (incl. eDP-specific block at "
                 "00700h) and the I2C address space for I2C-over-AUX",
        "note": "The Main Link video stream is addressless isochronous data; "
                "addressing applies to the AUX/DPCD management plane.",
    }
    d["frame_format"] = {
        "main_link": "micro-packet stream — Transfer Units of active video "
                     "framed by BS/BE, MSA per frame, secondary-data packets "
                     "(incl. PSR setup) in blanking; 8b/10b symbols.",
        "aux": "Manchester-II request/reply: SYNC + START + (command[4] + "
               "address[20] + length) / reply(command[4] + data) + STOP.",
        "note": "The Main Link clock is embedded (recovered during training); "
                "there is no dedicated Main Link clock lane.",
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L4 — DPCD register map (AUX-accessible) incl. eDP-specific block.
# ----------------------------------------------------------------------
def _l4(gd: Path) -> None:
    p = gd / "L4_REGMAP.json"
    if not p.is_file():
        return
    d = _read(p)
    d["register_map_present"] = True
    d["notes"] = (
        "The eDP register space is the DPCD (DisplayPort Configuration Data) in "
        "the panel Sink, accessed by native AUX read/write over the AUX channel "
        "(20-bit address). In addition to the DisplayPort base regions, eDP "
        "defines an eDP-specific DPCD block (base 00700h) carrying the eDP "
        "Configuration Capability (ASSR / Fast Link Training), backlight "
        "registers, and PSR / Remote-Frame-Buffer control. The panel EDID is a "
        "separate I2C ROM reached by I2C-over-AUX, not part of the DPCD.")
    d["register_access"] = {
        "transport": "Native AUX (Manchester-II, ~1 Mbps) over the AUX channel",
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
            "DSC capability"]},
        {"group": "Link Configuration (base 00100h)", "fields": [
            "LINK_BW_SET (selected link rate)",
            "LANE_COUNT_SET (selected lane count)",
            "TRAINING_PATTERN_SET (TPS1/2/3/4 select)",
            "TRAINING_LANE0_SET..TRAINING_LANE3_SET (voltage swing + "
            "pre-emphasis)",
            "DOWNSPREAD_CTRL"]},
        {"group": "Link/Sink Status (base 00200h)", "fields": [
            "SINK_COUNT",
            "LANE0_1_STATUS / LANE2_3_STATUS (CR_DONE, CHANNEL_EQ_DONE, "
            "SYMBOL_LOCKED)",
            "LANE_ALIGN_STATUS_UPDATED (INTERLANE_ALIGN_DONE)",
            "ADJUST_REQUEST_LANE0_1 / ADJUST_REQUEST_LANE2_3",
            "Device Service IRQ Vector"]},
        {"group": "eDP-specific DPCD block (base 00700h)", "fields": [
            "eDP_DPCD_REV (eDP revision 1.4 / 1.4b / 1.5)",
            "eDP_CONFIGURATION_CAP (ASSR support, Fast Link Training support, "
            "OUI, alternate-scrambler-seed enable)",
            "eDP_GENERAL_CAP (PSR / PSR2 capability, backlight-adjustment "
            "capability, frame-buffer capability)",
            "EDP_BACKLIGHT_MODE_SET / EDP_BACKLIGHT_BRIGHTNESS_MSB/LSB / "
            "EDP_PWMGEN_BIT_COUNT / EDP_BACKLIGHT_FREQ_SET (backlight)",
            "PSR_ENABLE / PSR_CONFIGURATION / PSR_STATUS / PSR2_ENABLE / "
            "selective-update (SU) region / RFB control"]},
    ]
    d["edid_via_i2c_over_aux"] = {
        "note": "Panel EDID is read from the panel's I2C ROM (I2C address A0h) "
                "by tunneling I2C over AUX; it is NOT in the DPCD address "
                "space.",
        "edid_block_bytes": 128,
    }
    d["aux_command_fields"] = {
        "command_width_bits": 4,
        "address_width_bits": 20,
        "length_encoding": "bytes minus one (1..16 bytes per transaction)",
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L5 — analog/electrical: Main Link differential + AUX (no UHBR for eDP base).
# ----------------------------------------------------------------------
def _l5(gd: Path) -> None:
    p = gd / "L5_ADI_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["analog_digital_interface_present"] = True
    d["signaling_summary"] = (
        "Main Link: 1/2/4 AC-coupled differential pairs carrying NRZ at RBR "
        "1.62 / HBR 2.7 / HBR2 5.4 / HBR3 8.1 Gbps/lane with ANSI 8b/10b coding "
        "(DC-balanced, transition-rich, LFSR-scrambled) so the panel Sink can "
        "recover the embedded clock; the ASSR alternate scrambler seed is used "
        "when enabled. eDP also defines a reduced-swing electrical option for "
        "panel power saving. Each lane carries per-lane voltage-swing (4 levels) "
        "and pre-emphasis (4 levels). AUX: one AC-coupled bidirectional "
        "half-duplex differential pair, Manchester-II coded at ~1 Mbps.")
    d["modulation"] = "NRZ (two-level), differential, AC-coupled."
    d["clocking"] = (
        "Embedded clock on the Main Link — recovered by the panel Sink's CDR "
        "during Clock Recovery (no dedicated Main Link clock lane). The Mvid/"
        "Nvid pair in the MSA lets the panel regenerate the pixel clock from the "
        "recovered link clock; during PSR the panel runs its own timing.")
    d["transmitter_specs_canonical"] = {
        "link_rates_Gbps_per_lane": dict(_RATES_8B10B),
        "modulation": "NRZ",
        "signaling": "differential (AC-coupled)",
        "line_encoding": "8b/10b (RBR..HBR3)",
        "lanes": list(_LANE_COUNTS),
        "voltage_swing_levels": 4,
        "pre_emphasis_levels": 4,
        "embedded_clock": True,
        "scrambling": "LFSR (reset by the SR symbol; ASSR alternate seed when "
                      "enabled)",
        "reduced_swing_option": True,
    }
    d["receiver_specs_canonical"] = {
        "clock_recovery": "Panel Sink CDR recovers the embedded clock per lane "
                          "during the CR training phase.",
        "equalization": "Channel Equalization (EQ) phase trains the receiver to "
                        "CHANNEL_EQ_DONE + SYMBOL_LOCKED + INTERLANE_ALIGN_DONE.",
        "interlane_align": "De-skews and aligns lanes (INTERLANE_ALIGN_DONE).",
        "status_reporting": "Reports CR_DONE / CHANNEL_EQ_DONE / SYMBOL_LOCKED "
                           "/ INTERLANE_ALIGN_DONE and ADJUST_REQUEST in DPCD.",
        "fast_link_training": "FLT applies stored drive settings for the fixed "
                             "embedded channel without iterative adjustment.",
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
                          "(K) symbols frame the stream; ASSR alternate seed "
                          "when enabled."},
    }
    d["downspread"] = (
        "Spread-spectrum clocking (down-spread) is supported (MAX_DOWNSPREAD / "
        "DOWNSPREAD_CTRL in DPCD) to reduce EMI.")
    d["encoding_role_in_analog"] = (
        "8b/10b provides DC balance and transition density so the panel Sink "
        "CDR can recover the embedded Main Link clock without a forwarded clock "
        "lane; scrambling (with the ASSR alternate seed when enabled) spreads "
        "the spectrum and provides basic content protection. AUX uses "
        "Manchester-II so the low-rate management channel is self-clocked.")
    d["backlight_electrical"] = {
        "control": "panel backlight set over AUX (eDP backlight DPCD) or a "
                   "dedicated backlight PWM pin",
        "pwm_generator": "EDP_PWMGEN_BIT_COUNT / EDP_BACKLIGHT_FREQ_SET "
                         "configure the panel PWM frequency / resolution",
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L6 — control logic: link-policy + PSR + training + AUX FSMs.
# ----------------------------------------------------------------------
def _l6(gd: Path) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["fsm_states_link_policy"] = [
        {"name": "POWER_ON / RESET", "description": "Source idle; waiting for "
         "the panel Sink to assert HPD."},
        {"name": "CAPABILITY_READ", "description": "Read DPCD Receiver "
         "Capability and the eDP_CONFIGURATION_CAP (ASSR / Fast Link Training / "
         "PSR caps) over native AUX."},
        {"name": "PANEL_POWER_ON", "description": "Sequence panel VDD / "
         "backlight per the panel power timing."},
        {"name": "LINK_TRAINING", "description": "Fast Link Training "
         "(preferred — apply stored settings) or full CR then EQ; fall back FLT "
         "-> full -> lower rate/lane on failure."},
        {"name": "ACTIVE", "description": "Stream video as micro-packets / "
         "Transfer Units; MSA per frame; set backlight brightness over AUX."},
        {"name": "PSR_ACTIVE", "description": "On a static screen, enter Panel "
         "Self Refresh: the panel refreshes from its Remote Frame Buffer (RFB) "
         "while the Main Link sleeps and the Source GPU may sleep."},
        {"name": "PSR_EXIT", "description": "On update / IRQ_HPD, re-train "
         "(Fast Link Training) and re-transmit — full frame, or PSR2 "
         "selective-update region."},
        {"name": "IRQ_HPD", "description": "On a short HPD pulse, re-read "
         "status (LANE*_STATUS, PSR_STATUS, Device Service IRQ Vector)."},
        {"name": "POWER_DOWN", "description": "Write SET_POWER (D3) in DPCD; "
         "Main Link idle; panel / backlight off."},
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
        {"name": "EQ_START", "description": "Set TRAINING_PATTERN_SET=TPS2/3/4."},
        {"name": "EQ_CHECK", "description": "Read LANE*_STATUS + "
         "LANE_ALIGN_STATUS_UPDATED; success requires CHANNEL_EQ_DONE + "
         "SYMBOL_LOCKED + INTERLANE_ALIGN_DONE on all active lanes."},
        {"name": "EQ_DONE", "description": "Set TRAINING_PATTERN_SET=0; link is "
         "trained, enter ACTIVE."},
        {"name": "EQ_FALLBACK", "description": "On failure reduce link rate "
         "and/or lane count and restart Clock Recovery."},
    ]
    d["fsm_states_fast_link_training"] = [
        {"name": "FLT_APPLY", "description": "Apply previously-stored drive "
         "settings (swing / pre-emphasis) and rate/lane configuration for the "
         "fixed embedded channel."},
        {"name": "FLT_PATTERN", "description": "Send the training patterns for a "
         "short fixed interval."},
        {"name": "FLT_CHECK", "description": "Confirm lock; on failure fall back "
         "to full CR/EQ link training."},
    ]
    d["fsm_states_psr"] = [
        {"name": "PSR_IDLE", "description": "PSR disabled; live externally-"
         "driven refresh."},
        {"name": "PSR_ENTRY", "description": "Source enables PSR, transmits a "
         "final frame, asserts PSR entry, and quiesces the Main Link; panel "
         "latches the RFB."},
        {"name": "PSR_SELF_REFRESH", "description": "Main Link idle; panel "
         "refreshes from the RFB; Source GPU may sleep."},
        {"name": "PSR_EXIT", "description": "On update / IRQ_HPD, re-establish "
         "the Main Link (Fast Link Training) and re-transmit (full frame, or "
         "PSR2 selective-update region)."},
    ]
    d["fsm_states_aux_transaction"] = [
        {"name": "AUX_IDLE", "description": "AUX bus idle (half-duplex)."},
        {"name": "AUX_REQUEST", "description": "Source drives SYNC + START + "
         "command[4] + address[20] + length (+ write data)."},
        {"name": "AUX_REPLY", "description": "Panel drives reply command "
         "(ACK/NACK/DEFER or I2C_*) + read data."},
        {"name": "AUX_RETRY", "description": "On NACK/DEFER or timeout, the "
         "Source retries."},
    ]
    d["fsm_hints"] = {
        "trigger": "HPD assertion starts CAPABILITY_READ -> PANEL_POWER_ON -> "
        "LINK_TRAINING -> ACTIVE. All control rides the AUX channel; the Main "
        "Link only carries video once trained. On a static screen the link "
        "enters PSR and the panel self-refreshes from the RFB.",
        "rule": "Link training prefers Fast Link Training for the fixed "
        "embedded channel; full training is strictly CR (TPS1) before EQ "
        "(TPS2/3/4). PSR exit re-establishes the link before re-transmitting.",
        "abort": "FLT failure falls back to full CR/EQ; repeated CR/EQ failure "
        "falls back to a lower rate and/or fewer lanes.",
    }
    d["anti_deadlock_rule"] = (
        "AUX transactions are half-duplex request/reply with retry on "
        "NACK/DEFER/timeout, so the bus cannot lock up; link training has a "
        "bounded loop-count before fallback; PSR entry/exit is bounded by the "
        "frame interval. There is no MST time-slot arbitration in eDP.")
    d["exit_from_reset_or_poweron"] = (
        "After power-on the Source waits for HPD, reads DPCD capability and the "
        "eDP_CONFIGURATION_CAP, sequences panel power, trains the Main Link "
        "(Fast Link Training preferred, else full CR/EQ with fallback), and "
        "enters ACTIVE to stream video; on a static screen it enters PSR.")
    d["default_ready_state_recommendation"] = {
        "main_link_idle": "Blanking / idle symbols before training; quiescent "
                          "during PSR self-refresh.",
        "aux_idle": "AUX bus released (half-duplex), ready for the next "
                    "request.",
        "hpd": "Panel keeps HPD asserted while present; pulses IRQ_HPD on "
               "events.",
    }
    d["configurations"] = [
        {"name": "1-lane link", "description": "Single Main Link lane "
         "(ML_Lane0) — low-resolution panel."},
        {"name": "2-lane link", "description": "Two Main Link lanes."},
        {"name": "4-lane link", "description": "Four Main Link lanes — "
         "high-resolution panel."},
    ]
    d["timing_dependency_rule"] = (
        "The Main Link clock is embedded and recovered per lane during CR (or "
        "applied directly in Fast Link Training); multi-lane links are de-skewed "
        "during EQ (INTERLANE_ALIGN_DONE). The Mvid/Nvid pair lets the panel "
        "regenerate the pixel clock; during PSR the panel uses its own timing. "
        "AUX runs independently at ~1 Mbps Manchester-II.")
    _write(p, d)


# ----------------------------------------------------------------------
# L7 — test/debug: AUX/DPCD observability + PSR + training status.
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
        {"name": "eDP_CONFIGURATION_CAP / eDP_GENERAL_CAP", "purpose": "Read "
         "ASSR / Fast-Link-Training / PSR / backlight capabilities."},
        {"name": "PSR_STATUS", "purpose": "Read the panel's Panel-Self-Refresh "
         "state (idle / entry / self-refresh / exit)."},
        {"name": "ADJUST_REQUEST", "purpose": "Panel reports the requested "
         "voltage swing / pre-emphasis per lane during training."},
        {"name": "Device Service IRQ Vector", "purpose": "Identifies the source "
         "of an IRQ_HPD (link-status change, PSR event, sink-specific)."},
        {"name": "HPD / IRQ_HPD", "purpose": "Presence and short-pulse event "
         "signaling to the Source."},
    ]
    d["error_detection_mechanisms"] = [
        "Per-lane training status (CR_DONE / CHANNEL_EQ_DONE / SYMBOL_LOCKED) "
        "detects loss of lock.",
        "8b/10b disparity / invalid-symbol detection on the Main Link.",
        "AUX reply NACK/DEFER and CRC on AUX transactions detect management "
        "errors.",
        "PSR_STATUS detects PSR entry/exit faults.",
        "Fast Link Training failure detection -> fall back to full CR/EQ.",
    ]
    d["test_modes"] = [
        {"name": "Link/compliance test automation", "purpose": "DPCD TEST_* "
         "registers drive defined link rates, lane counts, and test patterns "
         "for a compliance tester."},
        {"name": "PHY test patterns (TPS1..TPS4)", "purpose": "Drive defined "
         "training/test patterns to characterize the embedded Main Link eye."},
        {"name": "AUX loopback / read-write", "purpose": "Exercise the AUX "
         "channel and DPCD (incl. eDP block) independently of the Main Link."},
        {"name": "PSR entry/exit test", "purpose": "Exercise Panel Self Refresh "
         "entry, self-refresh, and exit with the RFB."},
        {"name": "Backlight control test", "purpose": "Exercise backlight "
         "brightness over AUX and the PWM generator."},
    ]
    d["interrupt_or_event_sources"] = [
        {"event": "HPD assert / de-assert", "trigger": "Panel presence "
         "detected by the Sink."},
        {"event": "IRQ_HPD (short pulse)", "trigger": "Link-status change, PSR "
         "event, or sink event — Source re-reads DPCD."},
        {"event": "Loss of lock", "trigger": "CR/EQ status clears during "
         "ACTIVE; re-train."},
        {"event": "PSR state change", "trigger": "Panel enters/exits "
         "self-refresh."},
    ]
    d["notes"] = (
        "eDP's protocol-level test/debug surface is the AUX channel + DPCD "
        "(status, ADJUST_REQUEST, Device Service IRQ Vector, the eDP-specific "
        "block with PSR_STATUS / backlight, TEST_* automation) plus the "
        "Main-Link training/test patterns. Chip-level JTAG/scan/BIST remain "
        "Source / panel-TCON silicon concerns; conformance is established by "
        "the VESA eDP / DisplayPort Compliance Test Specification (CTS).")
    _write(p, d)


# ----------------------------------------------------------------------
# L8 RTL constants — eDP lane/rate/AUX/PSR/backlight constants.
# ----------------------------------------------------------------------
def _l8_rtl(gd: Path) -> None:
    p = gd / "L8_RTL_CONSTANTS.json"
    if not p.is_file():
        return
    d = _read(p)
    wp = _ensure_dict(d, "width_parameters")
    wp.update({
        "EDP_SPEC_VERSION": "1.4b / 1.5",
        "MODULATION": "NRZ",
        "SIGNALING": "differential (AC-coupled)",
        "MAIN_LINK_LANES_SUPPORTED": list(_LANE_COUNTS),
        "MAIN_LINK_LANES_MAX": 4,
        "LINK_RATE_RBR_GBPS": 1.62,
        "LINK_RATE_HBR_GBPS": 2.70,
        "LINK_RATE_HBR2_GBPS": 5.40,
        "LINK_RATE_HBR3_GBPS": 8.10,
        "CHANNEL_CODING_8B10B_RATES": ["RBR", "HBR", "HBR2", "HBR3"],
        "CODING_8B10B_EFFICIENCY": "80%",
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
        "EDP_SPECIFIC_DPCD_BASE": "00700h",
        "EDID_I2C_ADDRESS": "A0h",
        "EDID_BLOCK_BYTES": 128,
        "TRANSFER_UNIT_SYMBOLS": "32 or 64",
        "TRAINING_PATTERNS": ["TPS1", "TPS2", "TPS3", "TPS4"],
        "FAST_LINK_TRAINING": True,
        "ASSR_SUPPORTED": True,
        "PSR_SUPPORTED": True,
        "PSR2_SUPPORTED": True,
        "REMOTE_FRAME_BUFFER": True,
        "BACKLIGHT_OVER_AUX": True,
        "MST_SUPPORTED": False,
    })
    d["channel_coding_constants"] = {
        "8b10b": {"symbol_bits": 10, "char_bits": 8, "efficiency": "80%",
                  "scrambled": True, "assr_alternate_seed": True},
    }
    d["aux_constants"] = {
        "coding": "Manchester-II", "rate_Mbps": 1,
        "command_bits": 4, "address_bits": 20,
        "native_replies": ["ACK", "NACK", "DEFER"],
        "i2c_replies": ["I2C_ACK", "I2C_NACK", "I2C_DEFER"],
    }
    d["edp_feature_constants"] = {
        "panel_self_refresh": True,
        "psr2_selective_update": True,
        "remote_frame_buffer": True,
        "backlight_over_aux": True,
        "assr": True,
        "fast_link_training": True,
        "edp_specific_dpcd_base": "00700h",
        "mst_supported": False,
    }
    kc = _ensure_dict(d, "key_constants_for_RTL_authoring")
    kc.update({
        "is_serial": True,
        "is_differential": True,
        "embedded_clock": True,
        "forwarded_clock": False,
        "modulation": "NRZ",
        "main_link_coding": "8b/10b (RBR..HBR3)",
        "main_link_lanes": list(_LANE_COUNTS),
        "link_rates_Gbps_per_lane": [1.62, 2.70, 5.40, 8.10],
        "voltage_swing_levels": 4,
        "pre_emphasis_levels": 4,
        "aux_coding": "Manchester-II",
        "aux_rate_Mbps": 1,
        "aux_command_bits": 4,
        "aux_address_bits": 20,
        "dpcd_register_space": True,
        "edp_specific_dpcd_block": True,
        "i2c_over_aux": True,
        "two_phase_training_cr_eq": True,
        "fast_link_training": True,
        "panel_self_refresh": True,
        "psr2": True,
        "remote_frame_buffer": True,
        "backlight_over_aux": True,
        "assr": True,
        "mst_supported": False,
    })
    d["default_signal_values_when_idle"] = {
        "main_link_idle": "Blanking / idle symbols before training; quiescent "
                          "during PSR self-refresh.",
        "aux_idle": "AUX bus released (half-duplex); ready for next request.",
        "hpd": "Asserted while the panel is present; IRQ_HPD pulses on events.",
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L8 timing — Main Link / AUX / training / PSR timing.
# ----------------------------------------------------------------------
def _l8_timing(gd: Path) -> None:
    p = gd / "L8_TIMING_WAVEFORM.json"
    if not p.is_file():
        return
    d = _read(p)
    d["main_link_waveform"] = {
        "signaling": "differential NRZ per lane, AC-coupled, embedded clock.",
        "coding": "8b/10b (RBR/HBR/HBR2/HBR3).",
        "framing": "Transfer Units of active video framed by BS/BE control "
                   "symbols; MSA per frame; secondary-data packets (SS/SE) in "
                   "blanking.",
        "clocking": "Panel Sink recovers the embedded clock with a CDR; no "
                    "dedicated clock lane.",
        "link_rates_Gbps_per_lane": [1.62, 2.70, 5.40, 8.10],
    }
    d["aux_waveform"] = {
        "coding": "Manchester-II bi-phase", "rate_Mbps": 1,
        "transaction": "SYNC preamble + START + (command[4] + address[20] + "
                       "length) request, then panel reply, then STOP.",
        "half_duplex": True,
    }
    d["link_training_waveform"] = {
        "fast_link_training": "Apply stored drive settings for the fixed "
                              "embedded channel; send training patterns a short "
                              "fixed interval.",
        "CR_phase": "TPS1 on all active lanes; adjust voltage swing / "
                    "pre-emphasis until CR_DONE (full training).",
        "EQ_phase": "TPS2/3/4 until CHANNEL_EQ_DONE + SYMBOL_LOCKED + "
                    "INTERLANE_ALIGN_DONE (full training).",
        "stop": "TRAINING_PATTERN_SET=0 stops training; stream begins.",
        "control_over_aux": True,
    }
    d["psr_waveform"] = {
        "entry": "Source enables PSR, transmits a final frame, quiesces the "
                 "Main Link; panel latches the RFB.",
        "self_refresh": "Main Link electrically idle; panel refreshes from the "
                        "RFB at its own timing.",
        "exit": "On update / IRQ_HPD: Fast Link Training + re-transmit (full "
                "frame, or PSR2 selective-update region).",
    }
    d["msa_waveform"] = {
        "msa": "Main Stream Attributes sent once per frame in vertical "
               "blanking: Mvid/Nvid, Htotal/Vtotal, HSP/HSW, active "
               "width/height, MISC0/MISC1.",
        "purpose": "Lets the panel regenerate the pixel clock from the link "
                   "clock; during PSR the panel uses its own timing.",
    }
    d["hpd_waveform"] = {
        "assert": "Panel asserts HPD while present.",
        "irq_hpd": "Short pulse signals a link-status / PSR event; Source "
                   "re-reads DPCD.",
    }
    d["general_timing_rule"] = (
        "The Main Link unit interval is set by the link rate (e.g. ~123.5 ps UI "
        "at 8.1 Gbps HBR3). The embedded clock is recovered per lane during CR "
        "(or applied directly in Fast Link Training); multi-lane links are "
        "de-skewed during EQ. The pixel clock is regenerated from Mvid/Nvid. "
        "PSR exit latency is minimized by Fast Link Training. AUX runs at a "
        "fixed ~1 Mbps Manchester-II independent of the Main Link rate.")
    d["voltage_levels"] = {
        "modulation": "NRZ differential, AC-coupled.",
        "voltage_swing_levels": 4,
        "pre_emphasis_levels": 4,
        "note": "Swing + pre-emphasis selected per lane during CR (or stored "
                "for Fast Link Training); reduced-swing option for panel power.",
    }
    d["link_rate_waveform"] = {
        "rates_Gbps_per_lane": dict(_RATES_8B10B),
        "coding": {"RBR/HBR/HBR2/HBR3": "8b/10b"},
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
        "Embedded DisplayPort Source or panel-Sink controller: drives/receives "
        "the Main Link (1/2/4 differential lanes, 8b/10b video micro-packets), "
        "runs the AUX channel (DPCD + eDP-specific block / link training / "
        "I2C-over-AUX EDID / backlight-over-AUX / PSR control), and handles HPD, "
        "Fast Link Training, Panel Self Refresh (RFB), and ASSR.")
    d["topology_description"] = (
        "Point-to-point Source -> single embedded panel Sink over the Main Link "
        "(1/2/4 lanes) plus a bidirectional AUX channel and an HPD sideband, on "
        "a short internal flex. No external connector and no MST tree.")
    io = _ensure_dict(d, "integration_overview")
    io.update({
        "edp_spec_version": "1.4b / 1.5",
        "main_link_lanes_supported": list(_LANE_COUNTS),
        "link_rates_Gbps_per_lane": [1.62, 2.70, 5.40, 8.10],
        "main_link_coding": "8b/10b (RBR..HBR3)",
        "clocking": "embedded clock recovered by the panel Sink (no clock "
                    "lane)",
        "aux_channel": "bidirectional half-duplex Manchester-II ~1 Mbps",
        "aux_address_bits": 20,
        "dpcd_register_space": True,
        "edp_specific_dpcd_base": "00700h",
        "i2c_over_aux_edid": True,
        "edid_i2c_address": "A0h",
        "link_training": "Fast Link Training + full Clock Recovery + Channel "
                         "Equalization",
        "voltage_swing_levels": 4,
        "pre_emphasis_levels": 4,
        "panel_self_refresh": True,
        "psr2_selective_update": True,
        "remote_frame_buffer": True,
        "backlight_over_aux": True,
        "assr": True,
        "mst_supported": False,
        "host_side_register_spec": "DPCD over AUX (Receiver Capability / Link "
        "Configuration / Link Status + eDP-specific block at 00700h); panel "
        "EDID via I2C-over-AUX.",
    })
    d["interface_categories"] = [
        "Main Link — 1/2/4 differential lanes carrying the video micro-packet "
        "stream (8b/10b).",
        "AUX channel — bidirectional half-duplex Manchester-II management "
        "channel (DPCD + eDP block / training / EDID / backlight / PSR).",
        "HPD — Hot Plug Detect sideband (presence + IRQ_HPD).",
        "DPCD — register space (incl. eDP-specific block) for capability / "
        "configuration / status / backlight / PSR.",
        "Backlight — backlight control over AUX (and optional PWM pin).",
        "Stream interface — pixel/audio source into Transfer Units + MSA.",
    ]
    d["interconnect_topologies_supported"] = [
        "Single Source -> single embedded panel Sink over 1/2/4 Main Link "
        "lanes.",
        "Source with Panel Self Refresh (RFB) for static-screen power saving.",
    ]
    d["default_signal_values_when_omitted"] = (
        "Main Link idle = blanking/idle symbols, no active video until trained; "
        "quiescent during PSR self-refresh; AUX bus released; HPD asserted while "
        "the panel is present. eDP is single-Sink (no MST).")
    d["soc_dependent_items"] = [
        "Source vs panel-Sink role and number of Main Link lanes (1/2/4).",
        "Maximum link rate supported (RBR..HBR3).",
        "PHY (SerDes / CDR, 8b/10b, swing/pre-emphasis, reduced-swing option) "
        "implementation.",
        "AUX PHY (Manchester-II, bidirectional half-duplex).",
        "DPCD implementation including the eDP-specific block, and the panel "
        "EDID I2C ROM.",
        "Panel Self Refresh / Remote Frame Buffer (RFB) support and PSR2 "
        "selective update.",
        "Backlight control method (AUX brightness vs PWM pin).",
        "ASSR and Fast Link Training support.",
        "Panel power / backlight sequencing and HPD handling.",
    ]
    d["low_power_modes"] = {
        "ACTIVE": "Streaming video on the Main Link.",
        "PSR": "Panel Self Refresh — panel refreshes from the RFB while the "
               "Main Link sleeps and the Source GPU may sleep.",
        "PSR2": "Selective update — only changed regions re-transmitted on "
                "exit.",
        "SET_POWER_D3": "Low power (SET_POWER DPCD = D3); Main Link idle; panel "
                        "/ backlight off.",
    }
    d["device_classes_examples"] = [
        "GPU / SoC eDP display Source",
        "Notebook / tablet / AIO internal panel (eDP Sink / TCON)",
        "Embedded / industrial / automotive integrated display panel",
        "eDP-to-LVDS or eDP-to-MIPI panel bridge IC",
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
        "partial - the VESA Embedded DisplayPort / DisplayPort Compliance Test "
        "Specification (CTS) defines link-layer, PHY, AUX, EDID, PSR, "
        "backlight, and protocol conformance behaviors; the standard defines "
        "the behaviors but does not ship an RTL testbench.")
    d["derived_compliance_test_categories"] = [
        "HPD detect: panel asserts HPD on power; Source begins capability "
        "read.",
        "AUX transactions: native Read/Write (4-bit command, 20-bit address, "
        "length) with ACK/NACK/DEFER replies.",
        "DPCD capability read: MAX_LINK_RATE, MAX_LANE_COUNT, "
        "eDP_CONFIGURATION_CAP (ASSR / Fast Link Training), eDP_GENERAL_CAP "
        "(PSR / backlight).",
        "I2C-over-AUX panel EDID read (I2C address A0h, MOT chaining).",
        "Fast Link Training: apply stored settings, confirm lock, fall back to "
        "full CR/EQ.",
        "Full link training Clock Recovery: TPS1, swing/pre-emphasis adjust, "
        "CR_DONE on all active lanes.",
        "Full link training Channel Equalization: TPS2/3/4, CHANNEL_EQ_DONE + "
        "SYMBOL_LOCKED + INTERLANE_ALIGN_DONE.",
        "Link rate coverage: RBR 1.62 / HBR 2.7 / HBR2 5.4 / HBR3 8.1.",
        "Lane-count coverage: 1, 2, 4 lanes.",
        "8b/10b coding + scrambling; ASSR alternate scrambler seed.",
        "Micro-packet stream: Transfer-Unit packing, BS/BE framing, MSA per "
        "frame (Mvid/Nvid).",
        "Panel Self Refresh (PSR): entry, self-refresh from RFB, exit.",
        "PSR2 selective update: re-transmit only the changed region.",
        "Backlight control over AUX: brightness, PWM generator config.",
        "IRQ_HPD short-pulse handling: status re-read, re-train, PSR event.",
        "Voltage-swing (4) and pre-emphasis (4) level coverage; reduced-swing "
        "option.",
        "Single-Sink operation (no MST).",
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
        {"field": "DPCD_REV", "width_bits": 8, "location": "DPCD 00000h",
         "note": "DPCD revision advertised by the panel Sink."},
        {"field": "MAX_LINK_RATE", "width_bits": 8, "location": "DPCD 00001h",
         "note": "Maximum Main Link rate the panel supports (RBR/HBR/HBR2/"
                 "HBR3)."},
        {"field": "MAX_LANE_COUNT", "width_bits": "5 (+ flags)",
         "location": "DPCD 00002h",
         "note": "Maximum Main Link lane count (1/2/4)."},
        {"field": "eDP_DPCD_REV / eDP_CONFIGURATION_CAP / eDP_GENERAL_CAP",
         "width_bits": "8 each", "location": "eDP-specific DPCD block 00700h",
         "note": "eDP revision and capability flags (ASSR, Fast Link Training, "
                 "PSR / PSR2, backlight adjustment, frame-buffer)."},
        {"field": "EDID", "width_bits": "128-byte block (+ extensions)",
         "location": "Panel I2C ROM (I2C address A0h, via I2C-over-AUX)",
         "note": "Panel capability/timing descriptor; factory-programmed in "
                 "the panel."},
    ]
    d["notes"] = (
        "eDP does not define OTP/fuse content as a protocol concept. The "
        "interoperability-relevant facts are the DPCD capability registers "
        "(DPCD_REV, MAX_LINK_RATE, MAX_LANE_COUNT) plus the eDP-specific block "
        "(eDP_CONFIGURATION_CAP / eDP_GENERAL_CAP advertising ASSR / Fast Link "
        "Training / PSR / backlight) read over AUX, and the panel EDID read by "
        "I2C-over-AUX; an implementation may back these with ROM/fuses, but the "
        "spec only requires they be discoverable.")
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
        "1. Panel asserts HPD on power.",
        "2. Source reads DPCD Receiver Capability + eDP_CONFIGURATION_CAP "
        "(MAX_LINK_RATE, MAX_LANE_COUNT, ASSR, Fast Link Training, PSR) over "
        "native AUX.",
        "3. Source reads the panel EDID via I2C-over-AUX (I2C address A0h).",
        "4. Source sequences panel VDD / backlight per the panel power timing.",
        "5. Source writes LINK_BW_SET and LANE_COUNT_SET to the chosen rate / "
        "lane count.",
        "6. Link training: Fast Link Training (apply stored drive settings) if "
        "available, else full Clock Recovery (TPS1) then Channel Equalization "
        "(TPS2/3/4).",
        "7. Stop training (TRAINING_PATTERN_SET=0); enable ASSR if supported.",
        "8. ACTIVE: stream video as Transfer Units with MSA per frame; set "
        "backlight brightness over AUX.",
    ]
    d["aux_transaction_sequence"] = [
        "1. Source drives SYNC + START on the AUX pair.",
        "2. Source sends command[4] + address[20] + length (+ write data for a "
        "write).",
        "3. Source releases the bus (half-duplex turnaround).",
        "4. Panel replies with ACK/NACK/DEFER (or I2C_* for I2C-over-AUX) + "
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
    d["fast_link_training_sequence"] = [
        "1. Read eDP_CONFIGURATION_CAP to confirm Fast Link Training support.",
        "2. Apply the previously-stored voltage swing / pre-emphasis and "
        "rate/lane configuration for the fixed embedded channel.",
        "3. Send the training patterns for a short fixed interval; confirm "
        "lock.",
        "4. On failure, fall back to full Clock Recovery + Channel "
        "Equalization.",
    ]
    d["clock_recovery_sequence"] = [
        "1. Set TRAINING_PATTERN_SET=TPS1; drive initial swing/pre-emphasis.",
        "2. Wait the training interval; read LANE*_STATUS and ADJUST_REQUEST.",
        "3. Apply requested swing/pre-emphasis; repeat until all active lanes "
        "report CR_DONE or the loop-count is exhausted (then fall back).",
    ]
    d["channel_eq_sequence"] = [
        "1. Set TRAINING_PATTERN_SET=TPS2/3/4.",
        "2. Wait; read LANE*_STATUS + LANE_ALIGN_STATUS_UPDATED.",
        "3. Success when CHANNEL_EQ_DONE + SYMBOL_LOCKED + INTERLANE_ALIGN_DONE "
        "are set on all active lanes; else adjust or fall back.",
    ]
    d["psr_entry_sequence"] = [
        "1. Detect a static screen.",
        "2. Source writes PSR_ENABLE / PSR_CONFIGURATION in the eDP DPCD.",
        "3. Source transmits a final frame and asserts PSR entry; panel latches "
        "the last frame into the Remote Frame Buffer (RFB).",
        "4. Source quiesces the Main Link; the panel self-refreshes from the "
        "RFB; the Source GPU may sleep.",
    ]
    d["psr_exit_sequence"] = [
        "1. A screen update (or IRQ_HPD) occurs.",
        "2. Source re-establishes the Main Link using Fast Link Training.",
        "3. Source re-transmits the updated frame (full frame), or for PSR2 "
        "transmits only the changed Selective-Update region into the RFB.",
        "4. Panel returns to live (externally-driven) refresh.",
    ]
    d["backlight_control_sequence"] = [
        "1. Source reads eDP_GENERAL_CAP backlight-adjustment capability.",
        "2. Source writes EDP_BACKLIGHT_MODE_SET to choose AUX-brightness / PWM "
        "mode.",
        "3. Source writes EDP_BACKLIGHT_BRIGHTNESS (MSB/LSB) and configures "
        "EDP_PWMGEN_BIT_COUNT / EDP_BACKLIGHT_FREQ_SET.",
    ]
    d["irq_hpd_sequence"] = [
        "1. Panel pulses HPD (IRQ_HPD).",
        "2. Source reads the Device Service IRQ Vector + LANE*_STATUS + "
        "PSR_STATUS.",
        "3. Handle: re-train on loss of lock, or service a PSR state change.",
    ]
    d["reset_sequence"] = [
        "1. Power-on / panel-off -> Source idle, Main Link off.",
        "2. On HPD assert, re-run capability read -> panel power -> link "
        "training (Fast Link Training preferred) -> ACTIVE.",
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
         "over the internal flex channel."},
        {"name": "Voltage swing / pre-emphasis", "purpose": "Confirm the 4 "
         "swing and 4 pre-emphasis levels (and the reduced-swing option) and "
         "their bounded combinations."},
        {"name": "Clock recovery / jitter", "purpose": "Confirm the panel Sink "
         "CDR locks (CR_DONE) and meets jitter tolerance at each rate."},
        {"name": "Fast Link Training", "purpose": "Confirm the stored-settings "
         "FLT achieves lock for the fixed channel and the fallback to full "
         "CR/EQ works."},
        {"name": "AUX channel timing", "purpose": "Validate Manchester-II "
         "~1 Mbps request/reply timing and half-duplex turnaround."},
        {"name": "EDID read", "purpose": "Confirm I2C-over-AUX panel EDID "
         "retrieval (I2C address A0h)."},
        {"name": "PSR entry/exit latency", "purpose": "Measure Panel Self "
         "Refresh entry, self-refresh, and exit timing (RFB) and PSR2 "
         "selective-update latency."},
        {"name": "Backlight over AUX", "purpose": "Confirm backlight brightness "
         "control over AUX and the PWM generator frequency / resolution."},
        {"name": "Compliance (CTS)", "purpose": "Run the VESA eDP / DisplayPort "
         "Compliance Test Specification link/PHY/AUX/PSR/backlight suite."},
    ]
    d["notes"] = (
        "eDP characterization centers on the embedded Main Link PHY (eye, "
        "jitter, swing/pre-emphasis, reduced-swing) over the internal flex, the "
        "AUX channel (Manchester-II timing), EDID/DPCD access (incl. the "
        "eDP-specific block), Fast Link Training, PSR entry/exit latency with "
        "the RFB, and backlight-over-AUX. Conformance is established by the VESA "
        "eDP / DisplayPort Compliance Test Specification (CTS); per-panel PHY "
        "calibration is done at bring-up.")
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
        "VESA Embedded DisplayPort (eDP) Standard — eDP 1.4b (2015) / eDP 1.5 "
        "(2021)")
    f["previous_versions"] = [
        "eDP 1.0 (2008) — first embedded variant of DisplayPort.",
        "eDP 1.1 (2009) — backlight control, ASSR, panel power features.",
        "eDP 1.2 (2010) — additional link rates, multi-touch sideband.",
        "eDP 1.3 (2011) — Panel Self Refresh (PSR), Remote Frame Buffer (RFB).",
        "eDP 1.4 (2013) — PSR2 (selective update), DSC, reduced-swing option.",
        "eDP 1.4a (2015) — PSR2 selective-update clarifications.",
    ]
    f["key_changes"] = [
        {"version": "1.4b", "summary": "Corrections / errata on top of eDP 1.4 "
         "(PSR2 selective update, DSC, reduced-swing electrical, additional eDP "
         "link rates). Carries forward the DisplayPort Main Link + AUX/DPCD + "
         "8b/10b + two-phase training base plus the eDP-exclusive PSR / RFB / "
         "backlight-over-AUX / ASSR / Fast Link Training features."},
        {"version": "1.5", "summary": "Aligns eDP Panel Self Refresh with DP "
         "2.0 Panel Replay, enhances PSR2, and adds further panel "
         "power-optimization features; same embedded Main Link / AUX / DPCD "
         "architecture."},
    ]
    f["future_versions_industry_outline"] = [
        {"version": "DP 2.x Panel Replay alignment", "summary": "eDP Panel Self "
         "Refresh converges with the DisplayPort 2.0 Panel Replay feature for "
         "external and embedded sinks."},
    ]
    f["backward_compat_traps"] = [
        {"trap_name": "eDP_is_embedded_no_MST",
         "rule": "eDP is the embedded single-panel variant — it has NO external "
                 "connector and NO Multi-Stream Transport.",
         "trap": "Designing eDP with MST virtual channels / branch devices is "
                 "wrong; an embedded panel is a single Sink."},
        {"trap_name": "Fast_Link_Training_fallback",
         "rule": "Fast Link Training applies stored settings for the fixed "
                 "channel; on failure fall back to full CR/EQ.",
         "trap": "Relying on FLT with no full-training fallback breaks bring-up "
                 "when the stored settings are stale."},
        {"trap_name": "PSR_needs_RFB",
         "rule": "Panel Self Refresh requires a panel-local Remote Frame Buffer "
                 "(RFB) to hold the last frame.",
         "trap": "Claiming PSR without an RFB cannot self-refresh; PSR2 "
                 "selective update further requires SU-region support."},
        {"trap_name": "Backlight_is_over_AUX",
         "rule": "eDP controls the panel backlight over AUX via the eDP "
                 "backlight DPCD registers (and/or a PWM pin).",
         "trap": "Assuming a separate proprietary backlight bus instead of the "
                 "eDP backlight DPCD interface."},
        {"trap_name": "ASSR_not_standard_seed",
         "rule": "When ASSR is enabled the Main Link scrambler uses the "
                 "alternate seed, not the standard DisplayPort seed.",
         "trap": "Mixing the standard DP scrambler seed with an ASSR panel "
                 "corrupts the descrambled stream."},
        {"trap_name": "Embedded_clock_not_forwarded",
         "rule": "The Main Link clock is embedded and recovered by the panel "
                 "(no clock lane).",
         "trap": "Designing for a forwarded/source-synchronous Main Link clock "
                 "is wrong for eDP."},
    ]
    f["version_naming_history_note"] = (
        "Embedded DisplayPort (eDP) is the VESA internal-panel variant of "
        "DisplayPort. eDP 1.0 (2008) established the embedded Main Link + "
        "AUX/DPCD base; backlight-over-AUX and ASSR arrived in 1.1, Panel Self "
        "Refresh + the Remote Frame Buffer in 1.3, PSR2 selective update + DSC "
        "in 1.4, and Panel Replay alignment in 1.5. Facts here are grounded in "
        "the public VESA Embedded DisplayPort Standard (RBR/HBR/HBR2/HBR3 "
        "8b/10b rates, AUX/DPCD incl. the eDP-specific block, CR/EQ + Fast Link "
        "Training, MSA/TU micro-packets, PSR/PSR2 + RFB, backlight-over-AUX, "
        "ASSR).")
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
            ["RBR", "1.62", "8b/10b", "eDP 1.0 (DP base)"],
            ["HBR", "2.70", "8b/10b", "eDP 1.0 (DP base)"],
            ["HBR2", "5.40", "8b/10b", "eDP base (DP 1.2)"],
            ["HBR3", "8.10", "8b/10b", "eDP base (DP 1.3)"],
        ],
    }
    f["channel_coding_table"] = {
        "header_columns": ["Coding", "Used at", "Efficiency", "Scrambler"],
        "rows": [
            ["8b/10b", "RBR / HBR / HBR2 / HBR3", "80%",
             "LFSR (ASSR alternate seed when enabled)"],
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
            ["DEFER", "panel busy; retry"],
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
            ["Fast Link Training", "stored-settings", "fixed embedded channel"],
        ],
    }
    f["dpcd_region_table"] = {
        "header_columns": ["Region", "Base address", "Key fields"],
        "rows": [
            ["Receiver Capability", "00000h",
             "DPCD_REV / MAX_LINK_RATE / MAX_LANE_COUNT / DSC"],
            ["Link Configuration", "00100h",
             "LINK_BW_SET / LANE_COUNT_SET / TRAINING_PATTERN_SET / "
             "TRAINING_LANE*_SET"],
            ["Link/Sink Status", "00200h",
             "LANE*_STATUS / LANE_ALIGN_STATUS_UPDATED / ADJUST_REQUEST"],
            ["eDP-specific DPCD block", "00700h",
             "eDP_DPCD_REV / eDP_CONFIGURATION_CAP (ASSR / FLT) / "
             "eDP_GENERAL_CAP (PSR / backlight) / backlight regs / PSR regs"],
        ],
    }
    f["drive_level_table"] = {
        "header_columns": ["Parameter", "Levels"],
        "rows": [
            ["Voltage swing", "4 (Level 0..3)"],
            ["Pre-emphasis", "4 (Level 0..3)"],
        ],
    }
    f["edp_feature_table"] = {
        "header_columns": ["Feature", "DPCD control", "Purpose"],
        "rows": [
            ["Panel Self Refresh (PSR)", "PSR_ENABLE / PSR_STATUS",
             "panel refreshes from RFB while Main Link sleeps"],
            ["PSR2", "PSR2_ENABLE / SU region",
             "selective update of changed region only"],
            ["Backlight over AUX", "EDP_BACKLIGHT_MODE_SET / _BRIGHTNESS",
             "panel backlight brightness over AUX / PWM"],
            ["ASSR", "eDP_CONFIGURATION_CAP",
             "alternate scrambler seed content protection"],
            ["Fast Link Training", "eDP_CONFIGURATION_CAP",
             "abbreviated training for fixed channel"],
        ],
    }
    f["encoding_note"] = (
        "eDP uses ANSI 8b/10b on the Main Link for RBR/HBR/HBR2/HBR3 "
        "(DC-balanced, transition-rich so the panel recovers the embedded "
        "clock; 80% efficient; LFSR-scrambled, with the ASSR alternate seed "
        "when enabled). The AUX channel uses Manchester-II bi-phase at ~1 Mbps. "
        "Panel EDID is fetched by tunneling I2C-over-AUX (I2C address A0h). eDP "
        "adds the eDP-specific DPCD block (PSR / backlight / ASSR / Fast Link "
        "Training) and does not use the UHBR (128b/132b) tier in its base.")
    f["tables"] = [
        "Link-rate table (RBR/HBR/HBR2/HBR3)",
        "Channel-coding table (8b/10b + ASSR seed)",
        "AUX command table",
        "AUX reply table",
        "Training-pattern table (TPS1..TPS4 / Fast Link Training)",
        "DPCD region table (incl. eDP-specific block)",
        "Drive-level table (swing / pre-emphasis)",
        "eDP feature table (PSR / PSR2 / backlight / ASSR / FLT)",
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
        "bidirectional half-duplex AUX channel, Hot Plug Detect (HPD), to a "
        "single embedded panel Sink.",
        "Main Link 8b/10b coding for RBR/HBR/HBR2/HBR3 with the clock embedded "
        "and recovered by the panel.",
        "AUX channel Manchester-II at ~1 Mbps with native AUX request/reply "
        "transactions (4-bit command, 20-bit address, length).",
        "DPCD register space (Receiver Capability / Link Configuration / Link "
        "Status) PLUS the eDP-specific DPCD block (eDP_CONFIGURATION_CAP / "
        "eDP_GENERAL_CAP / backlight / PSR).",
        "I2C-over-AUX for panel EDID retrieval (I2C address A0h).",
        "Link Training: full two-phase Clock Recovery (TPS1) then Channel "
        "Equalization (TPS2/3/4), AND Fast Link Training (FLT).",
        "Panel Self Refresh (PSR / PSR2) with a Remote Frame Buffer (RFB).",
        "Backlight control over AUX (eDP backlight DPCD registers / PWM).",
        "ASSR (Alternate Scrambler Seed Reset) when enabled.",
        "HPD with IRQ_HPD short-pulse event signaling.",
    ]
    f["must_not_have_properties"] = [
        "Multi-Stream Transport (MST) virtual channels / branch devices (eDP is "
        "a single embedded panel — that is external DisplayPort).",
        "An external DisplayPort connector / cable-orientation CONFIG pins.",
        "TMDS signaling (that is HDMI/DVI, not eDP).",
        "A forwarded/source-synchronous Main Link clock lane (eDP embeds and "
        "recovers the clock).",
        "Reading panel EDID from the DPCD address space (EDID is "
        "I2C-over-AUX).",
        "A D-PHY HS/LP escape-mode lane model (that is MIPI-DSI, not eDP).",
    ]
    f["compliance_failure_modes"] = [
        {"mode": "Fast Link Training failure", "trigger": "Stored settings do "
         "not lock and there is no fallback to full CR/EQ."},
        {"mode": "Clock Recovery failure", "trigger": "A lane never reports "
         "CR_DONE despite swing/pre-emphasis adjustment."},
        {"mode": "Channel Equalization failure", "trigger": "CHANNEL_EQ_DONE / "
         "SYMBOL_LOCKED / INTERLANE_ALIGN_DONE not all set."},
        {"mode": "PSR exit failure", "trigger": "Panel fails to re-establish "
         "the link / re-transmit on a screen update."},
        {"mode": "EDID read failure", "trigger": "I2C-over-AUX to A0h "
         "NACKs/defers; no panel capability."},
        {"mode": "Backlight control failure", "trigger": "Backlight DPCD "
         "registers not honored over AUX."},
    ]
    f["min_link_constraint"] = (
        "An eDP link must train at least one Main Link lane to CR_DONE + "
        "Channel-EQ (or via Fast Link Training) at the lowest common supported "
        "rate (RBR), with the AUX channel/DPCD operational, or it must fall "
        "back rate/lane-count; otherwise it fails to bring up the panel.")
    f["reset_behavior_compliance"] = (
        "On HPD assert the Source reads DPCD capability + eDP_CONFIGURATION_CAP, "
        "sequences panel power, trains the Main Link (Fast Link Training "
        "preferred, else full CR/EQ with fallback), and enters ACTIVE. A static "
        "screen enters PSR; an IRQ_HPD prompts status re-read and possible "
        "re-training.")
    f["edp_distinguishers"] = (
        "Embedded DisplayPort is identified by the DisplayPort base — a "
        "uni-directional Main Link of 1/2/4 self-clocked AC-coupled differential "
        "lanes with an EMBEDDED clock, the RBR/HBR/HBR2/HBR3 (8b/10b) rate "
        "vocabulary, a bidirectional half-duplex Manchester-II AUX channel, the "
        "DPCD register space, I2C-over-AUX EDID, and two-phase CR/EQ training — "
        "PLUS the eDP-EXCLUSIVE features that external DisplayPort lacks: Panel "
        "Self Refresh (PSR / PSR2) with a panel-local Remote Frame Buffer (RFB), "
        "backlight control over AUX, ASSR (Alternate Scrambler Seed Reset), "
        "Fast Link Training, and an eDP-specific DPCD block — AND the embedded "
        "single-panel topology (NO external connector, NO MST). This is distinct "
        "from external DisplayPort (external connector + MST, no PSR/ASSR/"
        "backlight-over-AUX), from HDMI/DVI (TMDS, no AUX/DPCD), and from "
        "MIPI-DSI (D-PHY HS/LP escape-mode, no Main Link / AUX / DPCD).")
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
         "direction": "uni-directional Source -> panel Sink",
         "purpose": "Carry the video micro-packet stream.",
         "active_levels": "differential NRZ, 8b/10b (RBR..HBR3); 1/2/4 lanes",
         "idle_level": "blanking / idle symbols; quiescent during PSR"},
        {"name": "AUX CH (AUX+/AUX-)",
         "direction": "bidirectional half-duplex",
         "purpose": "DPCD (incl. eDP block) access / link training / "
         "I2C-over-AUX / backlight / PSR control.",
         "active_levels": "Manchester-II ~1 Mbps request/reply",
         "idle_level": "bus released"},
        {"name": "HPD", "direction": "panel Sink -> Source",
         "purpose": "Presence + IRQ_HPD event signaling.",
         "active_levels": "asserted while present; short pulse = IRQ_HPD",
         "idle_level": "de-asserted when off"},
        {"name": "BL_PWM / BL_EN", "direction": "Source -> panel backlight",
         "purpose": "Optional backlight PWM / enable when not fully "
         "AUX-controlled.",
         "active_levels": "PWM duty cycle", "idle_level": "off"},
        {"name": "VDD / VBL / GND", "direction": "supply",
         "purpose": "Panel logic / backlight power and ground.",
         "active_levels": "DC rails", "idle_level": "n/a; always driven when "
         "on"},
    ]
    f["logical_signaling_levels"] = [
        {"name": "Active Main Link", "meaning": "Differential NRZ video "
         "micro-packets (8b/10b), embedded clock."},
        {"name": "Main Link idle", "meaning": "Blanking/idle symbols; quiescent "
         "during PSR self-refresh."},
        {"name": "AUX request", "meaning": "Manchester-II native/I2C request "
         "from the Source."},
        {"name": "AUX reply", "meaning": "Manchester-II ACK/NACK/DEFER reply "
         "from the panel Sink."},
    ]
    f["packet_types_summary"] = [
        {"class": "Main Link", "members": ["Transfer Unit (active video)",
                                           "MSA (Main Stream Attributes)",
                                           "Secondary-data packet (audio / SDP "
                                           "/ PSR setup)"], "count": 3},
        {"class": "AUX", "members": ["native AUX Read/Write",
                                     "I2C-over-AUX Read/Write",
                                     "eDP backlight / PSR control"], "count": 3},
    ]
    cc = _ensure_dict(f, "channel_counts")
    cc.update({
        "main_link_lanes_min": 1,
        "main_link_lanes_max": 4,
        "main_link_diff_pairs_per_lane": 1,
        "aux_pairs": 1,
        "hpd_lines": 1,
        "link_rates_count": 4,
        "voltage_swing_levels": 4,
        "pre_emphasis_levels": 4,
        "aux_address_bits": 20,
        "aux_command_bits": 4,
        "mst_supported": False,
    })
    f["global_signals"] = [
        {"name": "AUX CH", "purpose": "Bidirectional half-duplex management "
         "channel for the whole link (DPCD + eDP block / training / EDID / "
         "backlight / PSR)."},
        {"name": "HPD", "purpose": "Presence + IRQ_HPD events."},
        {"name": "VDD / VBL", "purpose": "Panel logic and backlight power."},
    ]
    f["dependency_graph"] = {
        "common_rule": "The AUX channel must be operational first: the Source "
        "reads DPCD capability + eDP_CONFIGURATION_CAP and EDID, then trains the "
        "Main Link (Fast Link Training or full CR/EQ). The Main Link clock is "
        "embedded and recovered per lane during CR; multi-lane links are "
        "de-skewed during EQ. HPD gates the whole sequence (no HPD -> no link). "
        "PSR depends on a panel-local Remote Frame Buffer (RFB).",
        "data_dependency": "Active video on the Main Link requires: (1) HPD "
        "asserted, (2) DPCD capability read, (3) panel power sequenced, (4) link "
        "trained. The pixel clock is regenerated from the MSA Mvid/Nvid; during "
        "PSR the panel refreshes from the RFB.",
    }
    f["handshake_pairs"] = [
        {"name": "AUX request/reply", "from": "Source", "to": "panel Sink",
         "rule": "Half-duplex native/I2C AUX transaction; reply ACK/NACK/"
         "DEFER."},
        {"name": "CR status", "from": "panel", "to": "Source",
         "rule": "CR_DONE per lane in LANE*_STATUS gates the EQ phase."},
        {"name": "EQ status", "from": "panel", "to": "Source",
         "rule": "CHANNEL_EQ_DONE + SYMBOL_LOCKED + INTERLANE_ALIGN_DONE gate "
         "ACTIVE."},
        {"name": "ADJUST_REQUEST", "from": "panel", "to": "Source",
         "rule": "Panel requests per-lane voltage swing / pre-emphasis."},
        {"name": "HPD / IRQ_HPD", "from": "panel", "to": "Source",
         "rule": "Presence + event signaling triggering status re-read."},
        {"name": "PSR entry/exit", "from": "Source", "to": "panel",
         "rule": "Source enables PSR / re-establishes the link; panel "
         "self-refreshes from the RFB."},
    ]
    f["ordering_rules"] = {
        "bit_order_on_wire": "Differential NRZ per lane; 8b/10b 10-bit symbols; "
        "LFSR-scrambled (ASSR alternate seed when enabled); clock embedded.",
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
        "Point-to-point Source -> single embedded panel Sink over the Main Link "
        "(1/2/4 lanes) plus a bidirectional AUX channel and HPD sideband, on a "
        "short internal flex. There is NO external connector and NO MST tree.")
    f["supported_topologies"] = [
        {"name": "Embedded single-panel link", "description": "One Source -> "
         "one internal panel Sink over 1/2/4 Main Link lanes."},
        {"name": "Panel Self Refresh", "description": "Source quiesces the Main "
         "Link; the panel refreshes from its Remote Frame Buffer (RFB)."},
    ]
    f["master_slave_role_summary"] = [
        {"role": "Source", "description": "On-board display controller: drives "
         "the Main Link, masters the AUX channel, reads DPCD/EDID, trains the "
         "link, streams video, controls backlight + PSR."},
        {"role": "panel Sink (TCON)", "description": "Receives the Main Link, "
         "replies on AUX, exposes DPCD + eDP block + EDID, reports training + "
         "PSR status, drives HPD, holds the RFB."},
        {"role": "AUX channel", "description": "Bidirectional half-duplex "
         "management channel shared by the link."},
    ]
    f["interconnect_role"] = (
        "eDP is a Source-to-internal-panel display transport. The Main Link "
        "carries isochronous video uni-directionally; the AUX channel carries "
        "all management (DPCD + eDP block, training, EDID, backlight, PSR) "
        "bidirectionally. There is a single Sink (the embedded panel) — no "
        "branch devices or MST routing.")
    f["ordering_guarantees"] = {
        "stream_order": "Per-frame video is isochronous and in-order; "
        "Transfer-Unit / MSA framing preserves the raster.",
        "psr": "During PSR the panel refreshes from the RFB; on exit the Source "
        "re-transmits (full frame or PSR2 selective-update region).",
        "aux_order": "AUX is strictly half-duplex request/reply, one "
        "transaction at a time.",
    }
    f["memory_vs_peripheral_regions"] = (
        "eDP's addressable space is the DPCD register map (20-bit AUX address), "
        "including the eDP-specific block at 00700h, plus the I2C address space "
        "reached by I2C-over-AUX (panel EDID at A0h). The Main Link video "
        "stream is addressless isochronous data; the panel-local RFB is internal "
        "to the Sink.")
    dc = _ensure_dict(f, "device_classification")
    dc["source"] = ("GPU/SoC eDP transmitter: masters AUX, trains the Main "
                    "Link, streams video, controls backlight + PSR.")
    dc["sink"] = ("Embedded panel TCON (eDP Sink): exposes DPCD + eDP block + "
                  "EDID, reports status + PSR_STATUS, drives HPD, holds RFB.")
    dc["panel_bridge"] = ("eDP-to-LVDS / eDP-to-MIPI panel bridge IC.")
    f["default_signal_values_evidence_tables"] = [
        "VESA Embedded DisplayPort Standard — Main Link rates "
        "(RBR/HBR/HBR2/HBR3) and lane counts (1/2/4)",
        "DPCD register-map structure (Receiver Capability / Link Configuration "
        "/ Link Status + eDP-specific block at 00700h)",
        "Link-training procedure (Fast Link Training + Clock Recovery + Channel "
        "Equalization, swing/pre-emphasis)",
        "eDP-exclusive features (PSR / PSR2 + RFB, backlight-over-AUX, ASSR)",
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
        "main_link_coding": "8b/10b (RBR/HBR/HBR2/HBR3)",
        "main_link_lanes": list(_LANE_COUNTS),
        "link_rates_Gbps_per_lane": dict(_RATES_8B10B),
        "voltage_swing_levels": 4,
        "pre_emphasis_levels": 4,
        "reduced_swing_option": True,
        "scrambling": "LFSR (SR symbol; ASSR alternate seed when enabled)",
        "downspread": "supported (MAX_DOWNSPREAD / DOWNSPREAD_CTRL)",
        "aux_channel": {
            "pair": "AUX+/AUX- bidirectional half-duplex AC-coupled",
            "coding": "Manchester-II", "rate_Mbps": 1},
        "connector": "internal flex / board-to-board: up to 4 Main Link pairs + "
                     "1 AUX pair + HPD + optional BL_PWM/BL_EN + VDD/VBL/GND "
                     "(NO external connector)",
    }
    f["notes"] = (
        "eDP is an interface specification for an internal panel; it fixes the "
        "Main Link electrical/coding (differential NRZ, 8b/10b, embedded clock, "
        "4 swing + 4 pre-emphasis levels, reduced-swing option), the AUX channel "
        "(Manchester-II ~1 Mbps), the DPCD register space (incl. the eDP block), "
        "the PSR / RFB architecture, backlight-over-AUX, and the internal flex "
        "pin-out. It does NOT impose PDK-specific SDC/floorplan constraints — "
        "PHY characterization (SerDes/CDR, eye, jitter) and the flex channel are "
        "Source / panel-TCON silicon and system concerns. The "
        "interoperability-critical constraints are the link rates, lane counts, "
        "coding, training (incl. Fast Link Training), AUX/DPCD, PSR/RFB, "
        "backlight, and the flex pin-out.")
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
         "controllability/observability: read capability/status (incl. eDP "
         "block), write link config, drive training, control backlight + PSR — "
         "available before the Main Link is up."},
        {"name": "eDP_CONFIGURATION_CAP / eDP_GENERAL_CAP / PSR_STATUS",
         "purpose": "Read ASSR / Fast-Link-Training / PSR / backlight "
         "capabilities and the panel PSR state."},
        {"name": "DPCD TEST_ automation registers", "purpose": "TEST_REQUEST / "
         "TEST_LINK_RATE / TEST_LANE_COUNT / TEST_PATTERN let a compliance "
         "tester drive defined link/video patterns."},
        {"name": "Training/test patterns (TPS1..TPS4)", "purpose": "PHY "
         "eye/jitter characterization on the embedded Main Link."},
        {"name": "Link status registers", "purpose": "CR_DONE / "
         "CHANNEL_EQ_DONE / SYMBOL_LOCKED / INTERLANE_ALIGN_DONE / "
         "ADJUST_REQUEST per lane."},
        {"name": "Device Service IRQ Vector", "purpose": "Identify the source "
         "of an IRQ_HPD event."},
    ]
    f["internal_diagnostics_observability"] = [
        "Link-policy state (capability-read / panel-power / training / active / "
        "PSR).",
        "Per-lane CR/EQ training status and ADJUST_REQUEST.",
        "Negotiated link rate / lane count; Fast-Link-Training state.",
        "PSR / PSR2 state (PSR_STATUS) and RFB usage.",
        "Backlight brightness / PWM state.",
    ]
    f["out_of_band_test_facilities"] = [
        "VESA eDP / DisplayPort Compliance Test Specification (CTS) "
        "link/PHY/AUX/PSR/backlight tools.",
        "Vendor PHY bring-up / eye-scan probes — implementation-defined.",
    ]
    f["notes"] = (
        "eDP's protocol-level DFT surface is the AUX channel + DPCD (status, "
        "ADJUST_REQUEST, Device Service IRQ Vector, the eDP-specific block with "
        "PSR_STATUS / backlight, TEST_* automation) plus the Main-Link "
        "training/test patterns. Chip-level JTAG/scan/BIST remain Source / "
        "panel-TCON silicon concerns; conformance is established by the VESA "
        "eDP / DisplayPort Compliance Test Specification (CTS).")
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
        {"state": "ACTIVE", "name": "Active", "description": "Main Link trained "
         "and streaming video; AUX available; backlight on.",
         "exit_latency_estimate": "n/a (already active)"},
        {"state": "PSR", "name": "Panel Self Refresh", "description": "Panel "
         "refreshes from the Remote Frame Buffer (RFB); the Main Link is "
         "quiescent and the Source GPU may sleep.",
         "exit_latency_estimate": "Fast-Link-Training-dominated (short)"},
        {"state": "PSR2", "name": "Panel Self Refresh 2", "description": "As "
         "PSR but on exit only the changed region is re-transmitted (selective "
         "update).",
         "exit_latency_estimate": "selective-update-region-dominated"},
        {"state": "D3 (SET_POWER)", "name": "Low power", "description": "Panel/"
         "Source powered down via SET_POWER DPCD = D3; Main Link idle; "
         "backlight off.",
         "exit_latency_estimate": "re-train on wake"},
    ]
    f["low_power_modes_summary"] = {
        "active": "Full operation; Main Link streaming.",
        "psr": "Panel self-refresh from the RFB; Main Link quiescent; GPU may "
               "sleep.",
        "psr2": "Selective-update self-refresh (changed region only on exit).",
        "d3": "SET_POWER D3 low-power; Main Link idle; backlight off.",
    }
    f["power_rails"] = [
        {"rail": "VDD", "purpose": "Panel logic / TCON supply."},
        {"rail": "VBL", "purpose": "Backlight supply (LED string / driver)."},
        {"rail": "core/IO", "purpose": "Source/panel PHY and logic supplies "
         "(implementation-defined)."},
        {"rail": "GND", "purpose": "Ground."},
    ]
    f["edp_power_considerations"] = (
        "eDP is designed for battery-powered systems: its DEFINING power feature "
        "is Panel Self Refresh (PSR / PSR2), where the panel holds the last "
        "frame in a local Remote Frame Buffer (RFB) and refreshes itself so the "
        "Source GPU, the Main Link PHY, and much of the Source clock tree can "
        "power down while the screen is static. Fast Link Training minimizes PSR "
        "exit latency. Backlight power is managed over AUX. The reduced-swing "
        "electrical option further lowers PHY power. SET_POWER D0/D3 over DPCD "
        "provides a deeper low-power state.")
    f["notes"] = (
        "eDP provides a rich link power-management framework centered on Panel "
        "Self Refresh (PSR / PSR2 + RFB) plus SET_POWER D0/D3 over DPCD and "
        "AUX-managed backlight power. The AUX channel is the wake and management "
        "path. Detailed rail/domain power is a Source / panel-TCON silicon "
        "concern; the spec defines the protocol-level power states.")
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
        "HPD detect and capability read over AUX (incl. eDP_CONFIGURATION_CAP).",
        "Native AUX transactions (Read/Write, ACK/NACK/DEFER, 20-bit address).",
        "I2C-over-AUX panel EDID read (A0h, MOT chaining).",
        "Fast Link Training (stored settings, lock, fallback to full CR/EQ).",
        "Full link training Clock Recovery (TPS1, swing/pre-emphasis, "
        "CR_DONE).",
        "Full link training Channel Equalization (TPS2/3/4, CHANNEL_EQ_DONE + "
        "SYMBOL_LOCKED + INTERLANE_ALIGN_DONE).",
        "Link-rate coverage RBR/HBR/HBR2/HBR3; lane-count coverage 1/2/4 with "
        "fallback.",
        "8b/10b coding + scrambling; ASSR alternate scrambler seed.",
        "Micro-packet stream: Transfer Units, BS/BE framing, MSA per frame "
        "(Mvid/Nvid).",
        "Panel Self Refresh (PSR): entry, self-refresh from RFB, exit.",
        "PSR2 selective update (changed-region re-transmit).",
        "Backlight control over AUX (brightness, PWM generator config).",
        "IRQ_HPD short-pulse handling (status re-read, re-train, PSR event).",
        "Power management (PSR / PSR2; SET_POWER D0/D3; backlight power).",
        "Single-Sink operation (no MST).",
        "Compliance — VESA eDP / DisplayPort CTS (link / PHY / AUX / PSR / "
        "backlight).",
    ]
    f["notes"] = (
        "eDP does not ship a formal RTL testbench, but the standard implies a "
        "verification plan spanning the embedded Main Link PHY (rates, coding, "
        "training incl. Fast Link Training, swing/pre-emphasis, reduced-swing), "
        "the AUX channel / DPCD incl. the eDP-specific block (transactions, "
        "capability, status, EDID via I2C-over-AUX), the micro-packet stream "
        "(TU / MSA / secondary data), and the eDP-exclusive features (PSR / "
        "PSR2 + RFB, backlight-over-AUX, ASSR). The VESA eDP / DisplayPort "
        "Compliance Test Specification (CTS) supplies the formal conformance "
        "suite.")
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
        "Link-training status (CR/EQ) detects loss of lock and triggers "
        "re-training.",
        "AUX reply NACK/DEFER + retry handles management-channel errors.",
        "PSR_STATUS detects PSR entry/exit faults.",
    ]
    f["anti_tampering_features"] = [
        "ASSR (Alternate Scrambler Seed Reset) — the eDP Main Link scrambler is "
        "reset with an alternate seed so only a Source using that seed produces "
        "a correctly-descrambled stream, providing basic embedded-panel content "
        "protection without full HDCP.",
    ]
    f["confidentiality_features"] = [
        "ASSR provides a lightweight scrambler-seed-based content-protection "
        "measure between the co-designed Source and embedded panel; HDCP may "
        "also be carried for protected content.",
    ]
    f["authentication_features"] = [
        "ASSR is negotiated during eDP link setup (advertised in "
        "eDP_CONFIGURATION_CAP); if the panel does not support ASSR the Source "
        "uses the standard scrambler seed. HDCP authentication (when present) "
        "rides the AUX channel.",
    ]
    f["future_security_pointers"] = [
        "eDP 1.5 Panel Replay alignment carries the eDP self-refresh / content "
        "model forward with DP 2.0.",
        "HDCP 2.x may be layered for premium-content embedded panels.",
    ]
    f["notes"] = (
        "eDP's primary content-protection mechanism is ASSR (Alternate "
        "Scrambler Seed Reset): the Main Link LFSR scrambler is reset with an "
        "alternate seed (negotiated via eDP_CONFIGURATION_CAP) so a panel only "
        "correctly descrambles a stream from a Source using that seed — a basic "
        "measure for the co-designed embedded Source/panel without the full "
        "HDCP machinery. HDCP may additionally be carried over AUX for protected "
        "content. Link integrity is provided by 8b/10b disparity checking. The "
        "base eDP data path is otherwise plaintext display data; confidentiality "
        "is provided by ASSR (and HDCP when enabled).")
    _write(p, d)
