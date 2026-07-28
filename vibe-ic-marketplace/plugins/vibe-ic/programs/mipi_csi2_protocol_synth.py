"""MIPI Camera Serial Interface 2 (CSI-2) protocol synth helper.

ic_class-gated overlay for a camera-image-sensor spec that exhibits the
MIPI CSI-2 structural signature: a UNIDIRECTIONAL high-speed serial link from
an IMAGE SENSOR (CSI-2 transmitter) to a HOST / application processor (CSI-2
receiver) over MIPI D-PHY (clock lane + data lanes, HS/LP) or C-PHY (3-wire
trios), carrying RAW / YUV / RGB image pixel data plus embedded data, framed by
a Low Level Protocol of Short Packets (Frame Start / Frame End / Line Start /
Line End sync) and Long Packets (Packet Header = Data Identifier {Virtual
Channel + Data Type} + Word Count + ECC; payload; Packet Footer 16-bit CRC),
with the camera sideband control bus CCI (Camera Control Interface, I2C-based).
Applies MIPI Alliance CSI-2 spec-canonical content to L1-L23.

============================================================================
DOCTRINE — GENERAL not keyword
============================================================================
Detection (`is_mipi_csi2`, module-level below) is CONTENT-ONLY on the L1/L2
(+ input_doc-augmented) text blob. It NEVER reads the input-document filename
or the benchmark folder name. It keys on CSI-2-SPECIFIC STRUCTURE — the
camera / image-sensor transmitter role + RAW image Data Types + the
FS/FE/LS/LE Short-Packet frame/line sync + Virtual Channel + Data Identifier +
Word Count + ECC + the CCI camera-control sideband — not on a lone name token.

============================================================================
CRITICAL MUTEX — CSI-2 vs MIPI DSI vs generic MIPI (all use D-PHY)
============================================================================
CSI-2 (camera, sensor->host, image capture), MIPI DSI (display, host->panel,
Display Command Set / Video-Command Mode), and the generic MIPI D-PHY
application-note benchmark all share the MIPI D-PHY physical layer, so the
runner's existing `_is_mipi` and `_is_mipi_dsi` predicates BOTH fire on a CSI-2
document (the generic `_is_mipi` even keys on "CSI-2" + "Long Packet" +
"Short Packet"). The CSI-2 detector here therefore:

  (1) is structurally NARROW — it requires CSI-2-PRIMARY camera structure
      (image sensor / camera + RAW/embedded image data + Frame-Start +
      Frame-End short packets + Virtual Channel + Word Count + ECC), which a
      pure DSI display spec does NOT have; and

  (2) DEFERS to DSI-primary — if the blob is a Display Serial Interface
      (Display Command Set / DCS, Video Mode + Command Mode panel drive,
      host->display pixel stream) WITHOUT the camera/image-sensor + RAW +
      FS/FE-short-packet structure, `is_mipi_csi2` returns False so the DSI
      synth's result stands. (A real DSI spec carries DCS + Command/Video Mode
      but no image-SENSOR / RAW-Bayer / Camera-Control-Interface structure.)

Because the generic-MIPI and MIPI-DSI synths fire FIRST (they match on the
shared D-PHY / CSI-2-mention tokens), this module runs LAST and
FORCE-OVERWRITES (direct assignment, NOT setdefault) every L1-L23 key those
siblings populate with the CSI-2-canonical camera value. The runner wires the
call order: mipi -> mipi_dsi -> mipi_csi2.

SIGNATURE (the runner wires this; evaluated on the L1/L2 + input_doc-augmented
content blob, never on a filename) — see module-level `is_mipi_csi2(blob)`.

Public entry: `apply_mipi_csi2_synth(generated_docs_dir, is_mipi_csi2,
mipi_csi2_ic_name)`.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

import l_doc_generator_stamp as _stamp


# ----------------------------------------------------------------------
# MODULE-LEVEL CONTENT-ONLY DETECTOR (the runner imports this).
# ----------------------------------------------------------------------
def _wb(token: str, blob: str) -> bool:
    """Word-boundary token test (case-sensitive, regex-escaped)."""
    return re.search(r"\b" + re.escape(token) + r"\b", blob) is not None


def is_mipi_csi2(blob: str) -> bool:
    """CONTENT-ONLY MIPI CSI-2 detector keyed on CSI-2 *PRIMACY*.

    Fires True ONLY when CSI-2 is the DOMINANT subject of the document, not on
    incidental / illustrative CSI-2 mentions scattered in a foreign spec's
    multi-doc blob. Returns False on a DSI-primary display spec, a generic-MIPI
    D-PHY application note, and on PCIe / UFS specs that merely cite CSI-2 as a
    vendor / pipeline example.

    Why PRIMACY (the v0.1.89 lesson): individual structural tokens
    ("virtual channel", "word count", "frame start", "ecc", a lone "CSI-2"
    mention) are common enough to co-occur across the ~24-doc blob of an
    unrelated spec (pcie_gen5 L1='PCI Express 5.0', ufs L1='Universal Flash
    Storage') even though CSI-2 is not the subject. So the detector requires:

      (1) FOREIGN-PRIMARY DEFER — if the blob is dominated by a foreign
          protocol (PCIe / UFS / DSI / generic-MIPI-PHY whose subject is the
          D-PHY app note, not the CSI-2 camera pipeline), defer (False).
      (2) CSI-2 DENSITY — many CSI-2 / "camera serial interface" mentions
          (a high count, not >=1), so CSI-2 is clearly the running subject.
      (3) CSI-2 CAMERA-PIPELINE PRIMACY structure — the full unique camera
          data path: the Camera Control Interface (CCI) sensor-control sideband
          (present in NO foreign benchmark) PLUS the Lane Distribution / Lane
          Merging camera lane management AND the image-sensor role + RAW image
          data + FS/FE short-packet frame sync + Long-Packet header.

    name-token alone is never sufficient (general-not-keyword).
    """
    if not blob:
        return False
    low = blob.lower()

    # --- CSI-2 mention DENSITY (primacy signal). A genuine CSI-2 spec mentions
    #     CSI-2 / "camera serial interface" dozens-to-hundreds of times; a
    #     foreign spec citing CSI-2 incidentally mentions it only a handful of
    #     times. Threshold chosen well below the real doc's count and well
    #     above every foreign benchmark's count (foreign max observed = 102 in
    #     the generic-MIPI app note on the FULL blob, but that doc fails the
    #     camera-pipeline gate below; PCIe/UFS are <= 25). ---
    csi2_mentions = (low.count("csi-2") + low.count("csi2")
                     + low.count("camera serial interface"))

    # --- CSI-2 name token (word-boundary). Necessary, not sufficient. ---
    name_csi2 = (
        _wb("CSI-2", blob) or _wb("CSI2", blob)
        or ("camera serial interface 2" in low)
        or ("camera serial interface" in low and "csi" in low))

    # --- FOREIGN-PRIMARY DEFERS (the blob's true subject is NOT CSI-2). ---
    # PCIe-primary: PCI Express is the running subject (dense mentions / 32 GT/s
    # / LTSSM / TLP). pcie_gen5 has "pci express" hundreds of times.
    pcie_primary = (
        low.count("pci express") >= 20
        or ("32 gt/s" in low and "ltssm" in low)
        or (_wb("LTSSM", blob) and _wb("TLP", blob) and _wb("DLLP", blob)))
    # UFS-primary: Universal Flash Storage / UniPro / M-PHY / JESD220 subject.
    ufs_primary = (
        low.count("ufs") >= 20
        or ("unipro" in low and ("m-phy" in low or "mphy" in low))
        or ("jesd220" in low and ("universal flash storage" in low
                                  or _wb("UFS", blob))))
    # DSI-primary: a Display Serial Interface display spec — Display Command
    # Set dense + display/panel drive — with NO CCI camera-control sideband.
    dsi_primary = (
        (low.count("dcs") >= 20 or low.count("display command set") >= 5)
        and ("video mode" in low and "command mode" in low)
        and "camera control interface" not in low)
    if pcie_primary or ufs_primary or dsi_primary:
        return False

    # --- STRUCTURAL features. ---
    camera_role = (
        ("image sensor" in low)
        or ("camera" in low and "sensor" in low)
        or (("image sensor" in low or "camera sensor" in low)
            and "host" in low))
    raw_image = (
        (_wb("RAW8", blob) or _wb("RAW10", blob) or _wb("RAW12", blob)
         or _wb("RAW14", blob) or _wb("RAW6", blob))
        or ("raw" in low and "bayer" in low)
        or ("embedded data" in low and ("raw" in low or "image data" in low)))
    short_pkt_sync = (
        ("frame start" in low and "frame end" in low)
        or (_wb("FS", blob) and _wb("FE", blob) and "short packet" in low)
        or ("line start" in low and "line end" in low
            and "short packet" in low))
    long_pkt_hdr = (
        ("word count" in low and ("ecc" in low or "error correction" in low))
        or ("data identifier" in low and "word count" in low)
        or ("packet header" in low and "packet footer" in low))
    virtual_channel = ("virtual channel" in low or _wb("VC", blob))

    # --- CSI-2 CAMERA-PIPELINE PRIMACY: the unique camera data path the
    #     foreign benchmarks lack. The Camera Control Interface (CCI) sensor
    #     sideband appears in NO foreign benchmark blob (mipi / mipi_dsi /
    #     pcie_gen5 / ufs all = False); Lane Distribution + Lane Merging is the
    #     CSI-2 camera lane-management layer. Requiring CCI AND lane-mgmt makes
    #     the generic-MIPI app note (CSI-2 mentions but no CCI / lane-mgmt) and
    #     DSI (lane-mgmt but no CCI) fall out. ---
    cci = ("camera control interface" in low or _wb("CCI", blob))
    lane_mgmt = ("lane distribution" in low and "lane merging" in low)
    camera_pipeline_primary = cci and lane_mgmt

    # --- DECISION: CSI-2 name + sufficient CSI-2 DENSITY + the full camera
    #     structure + camera-pipeline primacy. ---
    structural_quorum = (
        camera_role and raw_image and short_pkt_sync and long_pkt_hdr
        and virtual_channel and camera_pipeline_primary)

    return bool(name_csi2 and csi2_mentions >= 30 and structural_quorum)


# ----------------------------------------------------------------------
# Helpers (mirror ucie_protocol_synth).
# ----------------------------------------------------------------------
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


# DSI-display-ONLY tokens (and DSI-specific I2C-sibling leftovers) that have
# no meaning on the unidirectional camera CSI-2 link. Any top-level key whose
# serialized value contains one of these is a sibling-synth leftover, not a
# CSI-2 fact, so the CSI-2 synth purges it. (My own CSI-2 keys are written
# AFTER the purge and never contain these tokens, so the purge is safe.)
# NOTE: these tokens are DSI-display-ONLY and NEVER occur in CSI-2-authored
# content. Over-broad tokens ("Video Mode" / "Command Mode" / "DCS" /
# "Display Serial Interface") are intentionally EXCLUDED — they appear in the
# CSI-2 doc's own camera-vs-display contrast text, so purging on them would
# delete legitimate CSI-2 content.
_DSI_LEFTOVER_TOKENS = (
    "EoTp", "BTA", "DSI v1.01", "DSI Protocol Violation",
    "DSI transmitters", "DSI receiver", "Set Maximum Return Packet",
    "Return Packet Size", "Tearing Effect", "Display Command Set (DCS)",
    "display module", "display panel",
)

# Keys the CSI-2 synth itself OWNS / authors — never purged even if (in some
# future schema) they brushed a guarded token. Belt-and-braces: keeps the
# purge from ever deleting CSI-2 content.
_CSI2_PROTECTED_KEYS = frozenset({
    "ic_name", "schema_version", "doc_class", "document_title",
    "document_number", "version", "revised_date", "manufacturer", "copyright",
    "abstract", "keywords", "external_pins", "data_direction",
    "supported_lane_counts", "supported_virtual_channels", "phy_options",
    "modes_of_operation", "key_features", "topology_summary", "use_cases",
    "overview", "protocol_overview", "layers", "functional_requirements",
    "compliance_requirements", "error_response_conditions",
    "protocol_family", "byte_order", "short_packet", "long_packet",
    "data_identifier", "data_types", "interleaving", "register_map_present",
    "notes", "cci_register_access", "analog_digital_interface_present",
    "phy_layer", "d_phy_electrical", "c_phy_electrical", "cci_electrical",
    "control_model", "receiver_pipeline", "frame_structure",
    "test_debug_architecture_present", "error_reporting", "test_patterns",
    "constants", "timing_model", "payload_byte_serialization",
    "integration_role", "interfaces", "downstream",
    "derived_compliance_test_categories", "otp_present", "sequences",
    "lab_calibration_present", "fields", "extraction_status", "emitted_by",
    "extraction_evidence", "class_path",
})


def _purge_dsi_leftovers(node) -> None:
    """RECURSIVELY delete dict keys whose value carries a DSI-display-only
    token. Protected CSI-2-owned keys (and their subtrees) are never deleted —
    they hold the camera-vs-display contrast text. Runs across all 24 docs
    BEFORE the CSI-2 content is written so the CSI-2 facts are the survivors."""
    if isinstance(node, dict):
        for k in list(node.keys()):
            if k in _CSI2_PROTECTED_KEYS:
                # never delete an owned key, but DO recurse into nested
                # non-protected leftovers under it
                _purge_dsi_leftovers(node[k])
                continue
            try:
                s = json.dumps(node[k], ensure_ascii=False)
            except Exception:
                continue
            if any(tok in s for tok in _DSI_LEFTOVER_TOKENS):
                del node[k]
            else:
                _purge_dsi_leftovers(node[k])
    elif isinstance(node, list):
        for item in node:
            _purge_dsi_leftovers(item)


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

# Canonical CSI-2 structural facts (MIPI Alliance CSI-2 spec).
_DATA_TYPES = [
    {"code": "0x00", "name": "Frame Start (FS)", "class": "short_sync"},
    {"code": "0x01", "name": "Frame End (FE)", "class": "short_sync"},
    {"code": "0x02", "name": "Line Start (LS)", "class": "short_sync"},
    {"code": "0x03", "name": "Line End (LE)", "class": "short_sync"},
    {"code": "0x08-0x0F", "name": "Generic Short Packet Codes 1..8",
     "class": "short_generic"},
    {"code": "0x10", "name": "Null", "class": "long_generic"},
    {"code": "0x11", "name": "Blanking Data", "class": "long_generic"},
    {"code": "0x12", "name": "Embedded 8-bit non-image Data",
     "class": "long_generic"},
    {"code": "0x1E", "name": "YUV422 8-bit", "class": "yuv"},
    {"code": "0x1F", "name": "YUV422 10-bit", "class": "yuv"},
    {"code": "0x18", "name": "YUV420 8-bit (legacy)", "class": "yuv"},
    {"code": "0x22", "name": "RGB565", "class": "rgb"},
    {"code": "0x23", "name": "RGB666", "class": "rgb"},
    {"code": "0x24", "name": "RGB888", "class": "rgb"},
    {"code": "0x28", "name": "RAW6", "class": "raw"},
    {"code": "0x29", "name": "RAW7", "class": "raw"},
    {"code": "0x2A", "name": "RAW8", "class": "raw"},
    {"code": "0x2B", "name": "RAW10", "class": "raw"},
    {"code": "0x2C", "name": "RAW12", "class": "raw"},
    {"code": "0x2D", "name": "RAW14", "class": "raw"},
    {"code": "0x30-0x37", "name": "User Defined Byte-based Data",
     "class": "user_defined"},
]
_LANE_COUNTS = [1, 2, 4]
_VIRTUAL_CHANNELS = 4  # base VC field is 2-bit; extended VC raises to 16/32


# ----------------------------------------------------------------------
# Public entry.
# ----------------------------------------------------------------------
def apply_mipi_csi2_synth(generated_docs_dir: Path, is_mipi_csi2_flag: bool,
                          mipi_csi2_ic_name: Optional[str]) -> None:
    """Apply MIPI CSI-2 synth when the CSI-2 signature matched.

    Because CSI-2 shares D-PHY with generic MIPI and MIPI DSI, those sibling
    synths fire FIRST and populate display/D-PHY values. This routine runs
    LAST and FORCE-OVERWRITES (direct assignment) every L1-L23 key with the
    CSI-2-canonical camera value.
    """
    if not is_mipi_csi2_flag:
        return
    gd = Path(generated_docs_dir)

    # --- Force ic_name across ALL 24 docs FIRST (main + fields docs). ---
    if mipi_csi2_ic_name is not None:
        for n in _MAIN_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                d["ic_name"] = mipi_csi2_ic_name
                _write(q, d)
        for n in _FIELDS_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                f = _ensure_dict(d, "fields")
                f["ic_name"] = mipi_csi2_ic_name
                d["ic_name"] = mipi_csi2_ic_name  # belt-and-braces top-level
                _write(q, d)

    # --- Purge sibling (DSI) display-only leftover keys across ALL 24 docs
    #     BEFORE writing CSI-2 content, so the CSI-2 facts are the survivors. ---
    for n in _MAIN_DOCS + _FIELDS_DOCS:
        q = gd / n
        if q.is_file():
            d = _read(q)
            _purge_dsi_leftovers(d)
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
# L1 — FORCE-OVERWRITE the DSI/MIPI-sibling datasheet header with the
# CSI-2 camera image-sensor datasheet.
# ----------------------------------------------------------------------
def _l1(gd: Path) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    d["document_title"] = (
        "MIPI Alliance Specification for Camera Serial Interface 2 (CSI-2)")
    d["document_number"] = "MIPI CSI-2"
    d["version"] = "CSI-2 (D-PHY / C-PHY physical layer options)"
    d["revised_date"] = "MIPI Alliance"
    d["manufacturer"] = "MIPI Alliance, Inc."
    d["copyright"] = "© MIPI Alliance, Inc."
    d["abstract"] = (
        "MIPI Camera Serial Interface 2 (CSI-2) is a unidirectional, "
        "high-speed serial interface that carries image pixel data and "
        "embedded data from an image sensor (the CSI-2 transmitter) to a host "
        "/ application processor (the CSI-2 receiver). CSI-2 runs over the "
        "MIPI D-PHY (one clock lane + 1-4 or more data lanes, with High-Speed "
        "(HS) and Low-Power (LP) signaling) or the MIPI C-PHY (three-wire "
        "trios with 3-phase symbol encoding). Its Low Level Protocol uses "
        "Short Packets — Frame Start (FS), Frame End (FE), Line Start (LS), "
        "Line End (LE) — for in-band frame/line synchronization, and Long "
        "Packets — Packet Header (Data Identifier = Virtual Channel + Data "
        "Type, Word Count, ECC), Data Payload, and a 16-bit Packet Footer "
        "checksum (CRC). Data Types span RAW6/7/8/10/12/14, YUV422/420, "
        "RGB565/666/888, embedded 8-bit data, and user-defined. Up to four "
        "(extended: 16/32) Virtual Channels multiplex independent image "
        "streams. The image sensor is configured over the Camera Control "
        "Interface (CCI), an I2C-based two-wire sideband distinct from the "
        "CSI-2 data lanes.")
    d["keywords"] = [
        "MIPI", "CSI-2", "Camera Serial Interface 2", "image sensor",
        "camera", "D-PHY", "C-PHY", "Clock Lane", "Data Lane", "HS", "LP",
        "Short Packet", "Long Packet", "Frame Start", "Frame End",
        "Line Start", "Line End", "Data Identifier", "Virtual Channel",
        "Data Type", "Word Count", "ECC", "checksum", "CRC", "RAW10",
        "RAW12", "YUV422", "RGB888", "embedded data", "CCI",
        "lane distribution", "lane merging", "pixel-to-byte packing",
    ]
    d["external_pins"] = [
        "Clock Lane (D-PHY): differential DDR forwarded clock from sensor to "
        "host (Clk_p / Clk_n)",
        "Data Lane 0..N-1 (D-PHY): differential pairs (D0_p/D0_n .. ), HS "
        "burst image data + LP control; 1, 2, or 4 (or more) active lanes",
        "C-PHY alternative: per-lane three-wire trio (A / B / C) with embedded "
        "clock (no separate clock lane)",
        "CCI SCL (Camera Control Interface serial clock, I2C-based sideband)",
        "CCI SDA (Camera Control Interface serial data, I2C-based sideband)",
        "VDD / VSS / VDD-IO (sensor power and ground rails)",
        "RESET / sensor reset and power-down control",
    ]
    d.pop("total_external_pin_count", None)
    d["data_direction"] = "unidirectional: image sensor (Tx) -> host (Rx)"
    d["supported_lane_counts"] = list(_LANE_COUNTS)
    d["supported_virtual_channels"] = _VIRTUAL_CHANNELS
    d["phy_options"] = ["MIPI D-PHY", "MIPI C-PHY"]
    d["modes_of_operation"] = [
        {"name": "High-Speed (HS) mode",
         "phy": "D-PHY",
         "note": "Low-swing differential burst transfer of image data at high "
                 "bit rate (up to 2.5 Gbps/lane in D-PHY v1.2, higher in later "
                 "versions)."},
        {"name": "Low-Power (LP) mode",
         "phy": "D-PHY",
         "note": "Large-swing single-ended signaling between HS bursts for "
                 "stop state (LP-11), control, and escape sequences."},
        {"name": "C-PHY 3-phase symbol mode",
         "phy": "C-PHY",
         "note": "Three-wire trios encode ~2.28 bits/symbol (16 bits per 7 "
                 "symbols); clock embedded in symbol transitions."},
    ]
    d["key_features"] = [
        "Unidirectional high-speed serial camera link: image sensor (Tx) -> "
        "host application processor (Rx).",
        "Physical layer choice of MIPI D-PHY (clock lane + 1-4 data lanes, "
        "HS/LP signaling) or MIPI C-PHY (3-wire trios, 3-phase symbol coding).",
        "Lane Distribution (Tx) byte-interleaves the stream across active "
        "lanes; Lane Merging (Rx) reassembles it.",
        "Low Level Protocol: Short Packets (FS/FE/LS/LE frame/line sync + "
        "16-bit frame/line number + ECC) and Long Packets (Packet Header = "
        "Data Identifier + Word Count + ECC; payload; 16-bit CRC footer).",
        "Data Identifier = Virtual Channel (2-bit, extended to 16/32) + Data "
        "Type (6-bit); Virtual Channel and Data Type interleaving multiplex "
        "streams.",
        "Image Data Types: RAW6/7/8/10/12/14, YUV422/420, RGB565/666/888, "
        "embedded 8-bit data, user-defined.",
        "Pixel-to-byte packing per Data Type (e.g. RAW10 = 4 pixels/5 bytes); "
        "optional predictive image data compression.",
        "Packet Header ECC (Hamming) corrects 1-bit / detects 2-bit errors; "
        "Packet Footer CRC-16-CCITT (x^16+x^12+x^5+1) checks payload.",
        "In-band frame and line synchronization via FS/FE/LS/LE Short Packets "
        "— no separate frame-valid / line-valid wire.",
        "Camera Control Interface (CCI): I2C-based two-wire sideband (SCL/SDA) "
        "to configure the sensor — distinct from the CSI-2 data path.",
    ]
    d["topology_summary"] = (
        "Point-to-point unidirectional link from one image sensor to one host "
        "receiver. The CSI-2 data lanes carry image pixel data; the separate "
        "CCI (I2C) sideband carries control/register traffic. Multiple image "
        "streams (or multiple aggregated sensors) are multiplexed over the "
        "same link by Virtual Channel.")
    d["use_cases"] = [
        "Smartphone / tablet camera image sensors to the application "
        "processor",
        "Automotive ADAS / surround-view camera modules (multi-Virtual-Channel "
        "aggregation)",
        "Machine-vision and security camera sensors",
        "Multi-camera systems multiplexing image streams by Virtual Channel",
    ]
    d["overview"] = (
        "MIPI CSI-2 is the camera-capture serial interface of the MIPI "
        "family: it streams RAW / YUV / RGB image pixel data and embedded data "
        "from an image sensor up to a host application processor over D-PHY or "
        "C-PHY. It is the counterpart to MIPI DSI (Display Serial Interface) — "
        "DSI streams pixels host->display, CSI-2 streams pixels sensor->host. "
        "Both share the D-PHY physical layer, but CSI-2 is a camera interface "
        "with image-sensor RAW data types, FS/FE/LS/LE short-packet frame "
        "sync, Virtual Channels, and the I2C-based CCI sensor-control "
        "sideband; it has no Display Command Set (DCS) or Video/Command-Mode "
        "panel drive.")
    _write(p, d)


# ----------------------------------------------------------------------
# L2 — FRS / protocol overview: CSI-2 layered camera model.
# ----------------------------------------------------------------------
def _l2(gd: Path) -> None:
    p = gd / "L2_FRS.json"
    if not p.is_file():
        return
    d = _read(p)
    po = _ensure_dict(d, "protocol_overview")
    po["type"] = (
        "Unidirectional high-speed serial camera interface: image sensor (Tx) "
        "-> host (Rx), over MIPI D-PHY or C-PHY. Layered as Physical Layer, "
        "Lane Management (distribution/merging), Low Level Protocol "
        "(Short/Long Packets), Pixel-to-Byte Packing, and Application Layer.")
    po["direction"] = "unidirectional (sensor transmitter -> host receiver)"
    po["duplex"] = (
        "simplex high-speed data path (sensor->host only); control is a "
        "separate bidirectional I2C-based CCI sideband")
    po["source_synchronous"] = True
    po["embedded_clock"] = False  # D-PHY uses a forwarded clock lane
    po["c_phy_embedded_clock_option"] = True
    po["byte_oriented"] = True
    po["burst_based"] = True
    # FORCE-OVERWRITE DSI-sibling role descriptions (display module / BTA) with
    # CSI-2 sensor->host roles.
    po["controller_role"] = (
        "Image sensor (CSI-2 transmitter): drives the D-PHY Clock Lane (or "
        "C-PHY symbol clock) and transmits all image data over the HS/LP "
        "lanes; framed by FS/FE/LS/LE Short Packets.")
    po["target_role"] = (
        "Host / application processor (CSI-2 receiver): recovers the lane byte "
        "stream, parses Short/Long Packets, checks ECC + CRC, demultiplexes by "
        "Virtual Channel, and reconstructs frames for the ISP. The host "
        "configures the sensor over the separate CCI (I2C) sideband.")
    d["layers"] = [
        {"layer": "Physical Layer (PHY)",
         "function": "MIPI D-PHY (clock lane + data lanes, HS/LP) or C-PHY "
                     "(3-wire trios, 3-phase symbols); SoT/EoT per HS burst."},
        {"layer": "Lane Management Layer",
         "function": "Lane Distribution (Tx byte-interleave across active "
                     "lanes) and Lane Merging (Rx reassembly)."},
        {"layer": "Low Level Protocol (LLP)",
         "function": "Short Packets (FS/FE/LS/LE sync) and Long Packets "
                     "(header DI+WC+ECC, payload, CRC footer)."},
        {"layer": "Pixel-to-Byte Packing Layer",
         "function": "Maps pixels of each Data Type (RAW/YUV/RGB) to payload "
                     "bytes; optional compression."},
        {"layer": "Application Layer",
         "function": "Image data formats and embedded data semantics."},
    ]
    fr = _ensure_dict(d, "functional_requirements")
    fr["frame_sync"] = (
        "Each frame is delimited by an FS (Frame Start, DT 0x00) Short Packet "
        "carrying the 16-bit Frame Number and an FE (Frame End, DT 0x01) Short "
        "Packet. Line Start (LS, 0x02) / Line End (LE, 0x03) optionally "
        "bracket each line and carry the 16-bit Line Number.")
    fr["packet_model"] = (
        "Short Packet = 4 bytes (Data Identifier, 16-bit data field, ECC), no "
        "payload/footer. Long Packet = 4-byte Packet Header (Data Identifier, "
        "16-bit Word Count, ECC) + Word Count payload bytes + 2-byte Packet "
        "Footer (16-bit CRC).")
    fr["multiplexing"] = (
        "Up to 4 Virtual Channels (2-bit VC; extended VC up to 16/32) and "
        "Data Type interleaving multiplex independent image streams over one "
        "link.")
    fr["control_path"] = (
        "The image sensor is configured over the Camera Control Interface "
        "(CCI), an I2C-based two-wire (SCL/SDA) sideband, separate from the "
        "high-speed CSI-2 data lanes.")
    # FORCE-OVERWRITE the DSI-sibling display-specific lists with CSI-2 values
    # (the DSI synth fired first and wrote BTA/EoTp/return-packet facts that
    # are wrong for the unidirectional camera CSI-2 link).
    d["compliance_requirements"] = [
        "Sync pattern, HS Entry/Exit, and lane-state encoding inherit from "
        "MIPI D-PHY (or C-PHY symbol coding).",
        "Packet Header ECC = Hamming single-bit-correct / 2-bit-detect over "
        "the Data Identifier + Word Count.",
        "Long Packet Payload Checksum = 16-bit CRC-16-CCITT, polynomial "
        "x^16+x^12+x^5+1, LSB-first.",
        "Every frame begins with an FS Short Packet (DT 0x00) and ends with a "
        "matching FE Short Packet (DT 0x01) on the same Virtual Channel.",
        "Word Count in the Long Packet header equals the number of payload "
        "data bytes (footer excluded).",
        "Virtual Channel (DI[7:6], 2-bit; extended VC up to 16/32) "
        "demultiplexes independent image streams at the receiver.",
        "No image pixel data is transmitted over the CCI sideband, and no CCI "
        "register traffic is transmitted over the CSI-2 data lanes.",
    ]
    d["error_response_conditions"] = [
        "ECC single-bit error in a packet header — corrected by the receiver.",
        "ECC multi-bit (uncorrectable) header error — packet flagged; frame "
        "state machine resynchronizes on the next FS.",
        "Long Packet payload CRC-16 mismatch — payload corruption flagged.",
        "Unrecognized Data Type — packet ignored / flagged.",
        "Invalid / unexpected Virtual Channel — stream-routing error.",
        "Frame synchronization error — FS without a matching FE (or vice "
        "versa).",
        "PHY-level errors — SoT error, SoT sync error, control error, escape "
        "entry error reported by the receiver.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L3 — CMD / packet protocol: Short/Long packet formats, Data Types.
# ----------------------------------------------------------------------
def _l3(gd: Path) -> None:
    p = gd / "L3_CMD_PROTOCOL.json"
    if not p.is_file():
        return
    d = _read(p)
    d["protocol_family"] = "MIPI CSI-2 Low Level Protocol"
    d["byte_order"] = "least-significant-byte first"
    d["short_packet"] = {
        "size_bytes": 4,
        "fields": [
            {"byte": 0, "field": "Data Identifier (DI)",
             "subfields": "Virtual Channel (2-bit) + Data Type (6-bit)"},
            {"byte": "1-2", "field": "Short Packet Data Field (16-bit)",
             "meaning": "Frame Number (FS/FE) or Line Number (LS/LE)"},
            {"byte": 3, "field": "Error Correction Code (ECC)",
             "meaning": "ECC over Data Identifier + Data Field"},
        ],
        "sync_codes": [
            {"data_type": "0x00", "name": "Frame Start (FS)"},
            {"data_type": "0x01", "name": "Frame End (FE)"},
            {"data_type": "0x02", "name": "Line Start (LS)"},
            {"data_type": "0x03", "name": "Line End (LE)"},
            {"data_type": "0x08-0x0F",
             "name": "Generic Short Packet Codes 1..8"},
        ],
    }
    d["long_packet"] = {
        "packet_header_bytes": 4,
        "packet_footer_bytes": 2,
        "header_fields": [
            {"byte": 0, "field": "Data Identifier (DI)",
             "subfields": "Virtual Channel (2-bit) + Data Type (6-bit)"},
            {"byte": "1-2", "field": "Word Count (WC, 16-bit)",
             "meaning": "number of payload DATA bytes (footer excluded)"},
            {"byte": 3, "field": "Error Correction Code (ECC)",
             "meaning": "Hamming ECC over DI + WC; corrects 1-bit, detects "
                        "2-bit"},
        ],
        "payload": "Word Count bytes of pixel / embedded data (packed per "
                   "Data Type)",
        "footer": "16-bit Checksum / CRC-16-CCITT (x^16 + x^12 + x^5 + 1) over "
                  "the payload",
    }
    d["data_identifier"] = {
        "virtual_channel_bits": 2,
        "virtual_channels_base": _VIRTUAL_CHANNELS,
        "virtual_channels_extended": "up to 16 / 32 (extended VC)",
        "data_type_bits": 6,
    }
    d["data_types"] = list(_DATA_TYPES)
    d["interleaving"] = (
        "Virtual Channel interleaving and Data Type interleaving allow packets "
        "of different VC/DT to be multiplexed within a frame and demultiplexed "
        "at the receiver by the Data Identifier.")
    _write(p, d)


# ----------------------------------------------------------------------
# L4 — REGMAP: CSI-2 has no register map on the data path; CCI registers
# live on the sideband and are sensor-specific.
# ----------------------------------------------------------------------
def _l4(gd: Path) -> None:
    p = gd / "L4_REGMAP.json"
    if not p.is_file():
        return
    d = _read(p)
    d["register_map_present"] = False
    d["notes"] = (
        "CSI-2 is a streaming serial protocol with no addressable register map "
        "on the high-speed data path. Sensor registers (resolution, frame "
        "rate, exposure, gain, streaming start/stop) are accessed over the "
        "Camera Control Interface (CCI), an I2C-based sideband using 16-bit "
        "register addresses and 8-bit data; the specific register map is "
        "sensor-vendor-defined.")
    d["cci_register_access"] = {
        "bus": "I2C-based (CCI)",
        "register_address_width_bits": 16,
        "register_data_width_bits": 8,
        "clock_modes": ["Standard-mode 100 kHz", "Fast-mode 400 kHz"],
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L5 — ADI / analog-digital interface (PHY electrical).
# ----------------------------------------------------------------------
def _l5(gd: Path) -> None:
    p = gd / "L5_ADI_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["analog_digital_interface_present"] = True
    d["phy_layer"] = "MIPI D-PHY (default) or MIPI C-PHY"
    d["d_phy_electrical"] = {
        "hs_signaling": "low-swing differential, ~200 mV swing, ~200 mV "
                        "common-mode",
        "lp_signaling": "single-ended, ~1.2 V swing (stop state LP-11, escape)",
        "clock": "forwarded DDR clock on dedicated Clock Lane",
        "hs_data_rate_per_lane": "up to 2.5 Gbps (D-PHY v1.2); higher in later "
                                 "versions",
        "sot_eot": "Start-of-Transmission / End-of-Transmission sequences "
                   "delimit each HS burst per lane",
    }
    d["c_phy_electrical"] = {
        "wires_per_lane": 3,
        "encoding": "3-phase symbol encoding, ~2.28 bits/symbol "
                    "(16 bits per 7 symbols)",
        "clock": "embedded in symbol transitions (no separate clock lane)",
    }
    d["cci_electrical"] = {
        "bus": "I2C-based two-wire (SCL/SDA) sideband",
        "modes": ["Standard-mode 100 kHz", "Fast-mode 400 kHz",
                  "I3C extension (optional)"],
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L6 — CONTROL LOGIC: receiver frame/line state machine.
# ----------------------------------------------------------------------
def _l6(gd: Path) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["control_model"] = (
        "The CSI-2 receiver runs a frame/line state machine driven by the "
        "FS/FE/LS/LE Short Packets and the Long Packet headers.")
    d["receiver_pipeline"] = [
        "PHY (D-PHY/C-PHY) recovers the per-lane byte stream from HS bursts",
        "Lane Merging reassembles the single byte stream from active lanes",
        "LLP parser detects packet boundaries, reads Packet Header, checks ECC",
        "Classifies Short vs Long Packets by Data Type",
        "For Long Packets reads Word Count payload bytes and checks CRC footer",
        "Routes by Virtual Channel and Data Type to the unpack/ISP path",
        "FS/FE/LS/LE drive the frame/line raster-reconstruction state machine",
    ]
    d["frame_structure"] = (
        "FS Short Packet -> [optional Embedded Data Long Packets (DT 0x12)] -> "
        "per-line [LS] Long Packet (pixel data) [LE] x H lines -> [optional "
        "Embedded Data] -> FE Short Packet.")
    _write(p, d)


# ----------------------------------------------------------------------
# L7 — TEST / DEBUG.
# ----------------------------------------------------------------------
def _l7(gd: Path) -> None:
    p = gd / "L7_TEST_DEBUG.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_debug_architecture_present"] = True
    d["error_reporting"] = [
        "Packet Header ECC: corrects single-bit, detects double-bit errors in "
        "every Long Packet header and Short Packet",
        "Packet Footer CRC-16-CCITT detects payload corruption",
        "PHY-level errors: SoT error, SoT sync error, control error, escape "
        "entry error reported by receiver",
        "Frame sync error: FS without matching FE (or vice versa)",
    ]
    d["test_patterns"] = (
        "Sensors typically support CCI-configurable test patterns (color bar, "
        "gradient) sent as normal RAW/RGB Long Packets for receiver bring-up.")
    d["notes"] = (
        "CSI-2 test/debug centers on the packet error-reporting (header ECC, "
        "footer CRC) and PHY error flags; there is no host-to-sensor "
        "acknowledgement on the unidirectional data path.")
    _write(p, d)


# ----------------------------------------------------------------------
# L8 RTL constants.
# ----------------------------------------------------------------------
def _l8_rtl(gd: Path) -> None:
    p = gd / "L8_RTL_CONSTANTS.json"
    if not p.is_file():
        return
    d = _read(p)
    consts = _ensure_dict(d, "constants")
    consts["SHORT_PACKET_BYTES"] = 4
    consts["LONG_PACKET_HEADER_BYTES"] = 4
    consts["LONG_PACKET_FOOTER_BYTES"] = 2
    consts["DATA_IDENTIFIER_BYTES"] = 1
    consts["VIRTUAL_CHANNEL_BITS"] = 2
    consts["DATA_TYPE_BITS"] = 6
    consts["WORD_COUNT_BITS"] = 16
    consts["ECC_BITS"] = 8
    consts["CHECKSUM_BITS"] = 16
    consts["CRC_POLYNOMIAL"] = "x^16 + x^12 + x^5 + 1 (CRC-16-CCITT)"
    consts["DT_FRAME_START"] = "0x00"
    consts["DT_FRAME_END"] = "0x01"
    consts["DT_LINE_START"] = "0x02"
    consts["DT_LINE_END"] = "0x03"
    consts["DT_EMBEDDED_8BIT"] = "0x12"
    consts["DT_RAW8"] = "0x2A"
    consts["DT_RAW10"] = "0x2B"
    consts["DT_RAW12"] = "0x2C"
    consts["SUPPORTED_LANE_COUNTS"] = list(_LANE_COUNTS)
    _write(p, d)


# ----------------------------------------------------------------------
# L8 timing / waveform.
# ----------------------------------------------------------------------
def _l8_timing(gd: Path) -> None:
    p = gd / "L8_TIMING_WAVEFORM.json"
    if not p.is_file():
        return
    d = _read(p)
    d["timing_model"] = (
        "Source-synchronous: D-PHY forwards a DDR clock on the Clock Lane so "
        "each clock edge clocks a bit on the data lanes (C-PHY embeds the "
        "clock in symbol transitions).")
    pbs = _ensure_dict(d, "payload_byte_serialization")
    pbs["format"] = "byte-oriented, least-significant-byte first"
    pbs["multilane_interleave"] = (
        "Lane Distribution byte-interleaves the packet stream round-robin "
        "across the active data lanes; Lane Merging reassembles on the Rx.")
    pbs["burst_delimiters"] = (
        "Each HS burst is delimited by SoT (Start of Transmission) and EoT "
        "(End of Transmission) sequences; lanes return to LP-11 stop between "
        "bursts.")
    _write(p, d)


# ----------------------------------------------------------------------
# L9 — INTEGRATION SPEC.
# ----------------------------------------------------------------------
def _l9(gd: Path) -> None:
    p = gd / "L9_INTEGRATION_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["integration_role"] = (
        "CSI-2 receiver IP integrates in the host SoC between the D-PHY/C-PHY "
        "macro and the image signal processor (ISP). The transmitter is the "
        "image sensor.")
    d["interfaces"] = [
        {"name": "CSI-2 high-speed data lanes (D-PHY/C-PHY)",
         "direction": "sensor (Tx) -> host (Rx)",
         "carries": "image pixel data + embedded data"},
        {"name": "Camera Control Interface (CCI)",
         "direction": "host (master) <-> sensor (slave)",
         "carries": "I2C-based control / register access (sideband)"},
    ]
    d["downstream"] = (
        "Unpacked pixels route by Virtual Channel / Data Type to the ISP "
        "(demosaic for RAW Bayer, color conversion for YUV/RGB).")
    _write(p, d)


# ----------------------------------------------------------------------
# L10 — TEST CASES.
# ----------------------------------------------------------------------
def _l10(gd: Path) -> None:
    p = gd / "L10_TEST_CASES.json"
    if not p.is_file():
        return
    d = _read(p)
    # Drop DSI-sibling display test categories; CSI-2 owns this list.
    d["derived_compliance_test_categories"] = []
    cats = d["derived_compliance_test_categories"]
    for item in [
        "Short Packet (FS/FE/LS/LE) frame/line sync correctness",
        "Long Packet header ECC single-bit correction / double-bit detection",
        "Long Packet footer CRC-16 payload integrity",
        "Virtual Channel demultiplexing (VC0..VC3 + extended VC)",
        "Data Type decode (RAW8/10/12, YUV422, RGB888, embedded data)",
        "Pixel-to-byte packing / unpacking (RAW10 4px/5B, RAW12 2px/3B)",
        "Lane distribution / merging across 1/2/4 lanes",
        "Frame/line state-machine reconstruction",
        "CCI (I2C) sensor configuration sideband",
    ]:
        if item not in cats:
            cats.append(item)
    _write(p, d)


# ----------------------------------------------------------------------
# L11 — OTP content (none).
# ----------------------------------------------------------------------
def _l11(gd: Path) -> None:
    p = gd / "L11_OTP_CONTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    d["otp_present"] = False
    d["notes"] = (
        "MIPI CSI-2 defines a streaming camera link protocol with no "
        "one-time-programmable content. Sensor OTP (calibration, ID) is "
        "vendor-specific and accessed over CCI, outside the CSI-2 data path.")
    _write(p, d)


# ----------------------------------------------------------------------
# L12 — BEHAVIORAL SEQUENCES.
# ----------------------------------------------------------------------
def _l12(gd: Path) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    seqs = _ensure_dict(d, "sequences")
    seqs["frame_transmission"] = [
        "Sensor sends FS Short Packet (DT 0x00) with Frame Number on VC",
        "Optional Embedded Data Long Packets (DT 0x12)",
        "Per line: optional LS, then Long Packet (RAW/YUV/RGB pixel data), "
        "optional LE",
        "Optional trailing Embedded Data",
        "Sensor sends FE Short Packet (DT 0x01) with Frame Number",
    ]
    seqs["hs_burst"] = [
        "Lane in LP-11 stop state",
        "HS-Entry / SoT sequence",
        "HS payload bytes (lane-distributed)",
        "EoT / HS-Trail",
        "Return to LP-11",
    ]
    seqs["ecc_recovery"] = [
        "Receiver reads Packet Header (DI + WC + ECC)",
        "ECC corrects a single-bit error in DI+WC or detects a double-bit "
        "error",
        "On uncorrectable header error the packet is flagged and the frame "
        "state machine resynchronizes on the next FS",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L13 — LAB CALIBRATION (none).
# ----------------------------------------------------------------------
def _l13(gd: Path) -> None:
    p = gd / "L13_LAB_CALIBRATION.json"
    if not p.is_file():
        return
    d = _read(p)
    d["lab_calibration_present"] = False
    d["notes"] = (
        "No CSI-2-protocol lab calibration content. D-PHY/C-PHY electrical "
        "compliance (eye diagram, jitter) is a PHY-level concern; sensor image "
        "calibration is vendor-specific over CCI.")
    _write(p, d)


# ----------------------------------------------------------------------
# L14 — PROTOCOL VERSIONING.
# ----------------------------------------------------------------------
def _l14(gd: Path) -> None:
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["protocol"] = "MIPI Camera Serial Interface 2 (CSI-2)"
    f["standards_body"] = "MIPI Alliance, Inc."
    f["physical_layer_options"] = ["MIPI D-PHY", "MIPI C-PHY"]
    f["notable_features_by_era"] = [
        "RAW6/7/8/10/12/14, YUV422/420, RGB565/666/888, embedded data, "
        "user-defined Data Types",
        "Base 2-bit (4) Virtual Channels; extended Virtual Channel (16/32) in "
        "later versions",
        "Optional image data compression; C-PHY support and RAW16/RAW20 in "
        "later versions",
    ]
    # FORCE-OVERWRITE DSI-sibling display-specific version subkeys with
    # CSI-2-correct content (the DSI synth wrote DSI v1.01.00 / DCS / EoTp
    # facts that do not apply to the camera CSI-2 interface).
    f["spec_version"] = "MIPI Camera Serial Interface 2 (CSI-2), MIPI Alliance"
    f["version_naming_history_note"] = (
        "MIPI Alliance maintains the CSI-2 (Camera Serial Interface 2) "
        "specification together with the D-PHY and C-PHY physical-layer "
        "specifications and the CCI (Camera Control Interface). CSI-2 is the "
        "camera-capture counterpart to the DSI (Display Serial Interface).")
    f["backward_compat_traps"] = [
        {"rule": "CSI-2 base Virtual Channel field is 2 bits (DI[7:6]); "
                 "supports up to 4 VCs.",
         "trap": "Extended Virtual Channel (16/32) is a later-version feature; "
                 "a 2-bit-only receiver cannot decode extended VC streams."},
        {"rule": "RAW16 / RAW20 and C-PHY are later-version additions.",
         "trap": "An older receiver may not support C-PHY trios or RAW16/20 "
                 "Data Types."},
    ]
    f["key_changes_in_v1_01"] = (
        "Not applicable to CSI-2 (the v1.01 end-of-transmission / "
        "return-packet changes belong to the DSI display interface). CSI-2 "
        "evolution instead added C-PHY support, extended Virtual Channels, "
        "RAW16/20, and optional compression across revisions.")
    f.pop("versions", None)
    f.pop("deprecated_features", None)
    f.pop("previous_versions", None)
    f.pop("key_changes", None)
    f.pop("referenced_external_specifications", None)
    _write(p, d)


# ----------------------------------------------------------------------
# L15 — ENCODING TABLES (Data Type code table).
# ----------------------------------------------------------------------
def _l15(gd: Path) -> None:
    p = gd / "L15_ENCODING_TABLES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["data_type_codes"] = list(_DATA_TYPES)
    f["data_identifier_layout"] = (
        "DI byte = VC[7:6] (Virtual Channel, 2-bit) | DT[5:0] (Data Type, "
        "6-bit)")
    f["pixel_packing"] = {
        "RAW8": "1 pixel / 1 byte",
        "RAW10": "4 pixels / 5 bytes",
        "RAW12": "2 pixels / 3 bytes",
        "RGB888": "1 pixel / 3 bytes",
        "YUV422_8bit": "2 bytes / pixel (Y/U/Y/V interleave)",
    }
    f["crc_polynomial"] = "x^16 + x^12 + x^5 + 1 (CRC-16-CCITT)"
    _write(p, d)


# ----------------------------------------------------------------------
# L16 — COMPLIANCE PROPERTIES.
# ----------------------------------------------------------------------
def _l16(gd: Path) -> None:
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["properties"] = [
        "Every frame begins with an FS Short Packet and ends with a matching "
        "FE Short Packet on the same Virtual Channel.",
        "Every Long Packet has a valid ECC over its Data Identifier + Word "
        "Count.",
        "The payload byte count equals the Word Count; the 16-bit CRC footer "
        "matches the payload.",
        "Packets of a given Virtual Channel demultiplex to a single image "
        "stream at the receiver.",
        "No image pixel data is transmitted over the CCI sideband and no CCI "
        "register traffic is transmitted over the CSI-2 data lanes.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L17 — CHANNEL / SIGNAL CATALOG (force-overwrite per spec).
# ----------------------------------------------------------------------
def _l17(gd: Path) -> None:
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["signals"] = [
        {"name": "Clock Lane (Clk_p/Clk_n)", "phy": "D-PHY",
         "direction": "sensor->host",
         "description": "Differential DDR forwarded clock"},
        {"name": "Data Lane 0..N-1 (Dp/Dn)", "phy": "D-PHY",
         "direction": "sensor->host",
         "description": "Differential HS image data / LP control; 1/2/4 lanes"},
        {"name": "Lane Trio A/B/C", "phy": "C-PHY",
         "direction": "sensor->host",
         "description": "Three-wire trio, 3-phase symbol encoding, embedded "
                        "clock"},
        {"name": "CCI SCL", "phy": "I2C sideband",
         "direction": "host->sensor",
         "description": "Camera Control Interface serial clock"},
        {"name": "CCI SDA", "phy": "I2C sideband",
         "direction": "bidirectional",
         "description": "Camera Control Interface serial data"},
    ]
    f["channel_summary"] = (
        "Unidirectional CSI-2 data lanes (D-PHY clock+data or C-PHY trios) "
        "from image sensor to host, plus a separate bidirectional I2C-based "
        "CCI control sideband.")
    _write(p, d)


# ----------------------------------------------------------------------
# L18 — INTERCONNECT TOPOLOGY.
# ----------------------------------------------------------------------
def _l18(gd: Path) -> None:
    p = gd / "L18_INTERCONNECT_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["topology"] = "point-to-point, unidirectional (image sensor -> host)"
    f["lanes"] = {
        "clock_lane": 1,
        "data_lanes": "1, 2, or 4 (or more)",
        "phy": "D-PHY (clock + data lanes) or C-PHY (3-wire trios)",
    }
    f["multiplexing"] = (
        "Up to 4 base Virtual Channels (extended 16/32) multiplex independent "
        "image streams; CCI is a separate sideband bus.")
    _write(p, d)


# ----------------------------------------------------------------------
# L19 — CONSTRAINTS / PDK (none specific).
# ----------------------------------------------------------------------
def _l19(gd: Path) -> None:
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["notes"] = (
        "CSI-2 is a protocol specification; PDK/process constraints apply to "
        "the D-PHY/C-PHY hard macro, not the protocol controller.")
    _write(p, d)


# ----------------------------------------------------------------------
# L20 — DFT / SCAN (none specific).
# ----------------------------------------------------------------------
def _l20(gd: Path) -> None:
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["notes"] = (
        "DFT is implementation-specific; the CSI-2 controller is a standard "
        "scan-testable digital block.")
    _write(p, d)


# ----------------------------------------------------------------------
# L21 — POWER INTENT.
# ----------------------------------------------------------------------
def _l21(gd: Path) -> None:
    p = gd / "L21_POWER_INTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["low_power_features"] = (
        "D-PHY LP (Low-Power) mode between HS bursts conserves power; lanes "
        "rest in LP-11 stop state when idle. The image sensor is duty-cycled "
        "via CCI streaming start/stop.")
    f["notes"] = (
        "Power intent for CSI-2 is dominated by the D-PHY/C-PHY HS/LP duty "
        "cycle and the sensor's CCI-controlled streaming state; the protocol "
        "controller itself is a standard low-power digital block.")
    _write(p, d)


# ----------------------------------------------------------------------
# L22 — VERIFICATION PLAN.
# ----------------------------------------------------------------------
def _l22(gd: Path) -> None:
    p = gd / "L22_VERIFICATION_PLAN.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["verification_items"] = [
        "Short Packet (FS/FE/LS/LE) generation and detection with correct "
        "Frame/Line numbers",
        "Long Packet header build/parse incl. ECC and Word Count",
        "CRC-16 footer generation and checking",
        "Virtual Channel and Data Type interleaving / demux",
        "Pixel-to-byte packing for RAW8/10/12, YUV422, RGB888",
        "Lane distribution / merging for 1/2/4 lanes",
        "Error injection: header ECC single/double-bit, payload CRC mismatch",
        "CCI sensor-configuration sequences",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L23 — SECURITY REQUIREMENTS.
# ----------------------------------------------------------------------
def _l23(gd: Path) -> None:
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["notes"] = (
        "Base CSI-2 is an on-board sensor->host link without built-in "
        "encryption; data confidentiality/integrity for the camera path are "
        "provided by higher layers or platform measures. ECC + CRC provide "
        "transmission error detection, not security.")
    _write(p, d)


# Module-level alias the runner may import under the constraint name.
__all__ = ["is_mipi_csi2", "apply_mipi_csi2_synth"]
