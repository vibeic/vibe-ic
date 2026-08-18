"""JESD204B / JESD204C converter-to-logic serial-interface protocol synth.

v0.1.91 — ic_class-gated overlay for a `bus_interconnect_protocol`-shaped
spec that exhibits the JESD204 structural signature: a high-speed SERIAL
link between one or more DATA CONVERTERS (ADC/DAC) and a LOGIC device
(FPGA/ASIC), built from L SerDes lanes carrying converter samples mapped
into the L/M/F/S/N/N'/K frame parameter set, brought up through Code Group
Synchronization (CGS, /K28.5/ comma) -> Initial Lane Alignment Sequence
(ILAS, four multiframes carrying the link config) -> user-data phase, with
a Local MultiFrame Clock (LMFC) / multiframe alignment, optional
scrambling, and Subclass 0/1/2 deterministic-latency (SYSREF / SYNC~).
Applies JEDEC JESD204B (2011) and JESD204C (2017) spec-canonical content
to L1-L23.

Doctrine — GENERAL not keyword: detection uses the canonical STRUCTURAL
signature of the standard (data converters + ILAS + multiframe + the
L/M/F/S/K converter parameter vocabulary + SYSREF/SYNC + subclass +
CGS/comma) read from the L1/L2/L3 CONTENT blob only. It NEVER reads the
input-document filename or the benchmark folder name (a code review flagged
exactly that as a HIGH defect on the AHB+APB detector). The runner-side
predicate `is_jesd204(blob)` defined at the bottom of this module is
evaluated on the L-doc CONTENT blob only.

NEW domain — JESD204 lives in the data-converter interface space, which no
existing sibling protocol class occupies, so collision risk is low. A LIGHT
MUTEX is nonetheless applied so the detector cannot fire on a generic SerDes
/ PCIe / Ethernet document that merely says "lane" or "8b/10b": the
predicate REQUIRES the converter + ILAS/CGS + multiframe + converter-frame-
parameter vocabulary, none of which a plain PCIe/CXL/Ethernet/SerDes spec
carries. Because JESD204 is its own domain it does NOT force-overwrite a
sibling's L-docs; it simply populates the JESD204-canonical content on the
generic base the runner produced.

Public entry: `apply_jesd204_synth(generated_docs_dir, is_jesd204,
jesd204_ic_name)`.
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

# Canonical JESD204 structural facts (JEDEC JESD204B 2011 / JESD204C 2017).
_LANES_SUPPORTED = [1, 2, 4, 8]            # common L (standard allows up to 32)
_SPEED_GRADES_GBPS = {"grade_1": "0.3125-6.375", "grade_2": "6.375-8",
                      "grade_3": "8-12.5"}
_MAX_LANE_RATE_B_GBPS = 12.5
_MAX_LANE_RATE_C_GBPS = 32.0
_SUBCLASSES = [0, 1, 2]
_CONTROL_CHARS = {
    "K": "K28.5 (CGS comma / code group synchronization)",
    "R": "K28.0 (start of multiframe in ILAS / data)",
    "A": "K28.3 (end of multiframe / lane alignment)",
    "Q": "K28.4 (start of link configuration data in ILAS multiframe 2)",
    "F": "K28.7 (frame alignment character)",
}
_LINK_PARAMS = ["L", "M", "F", "S", "N", "N'", "K", "CS", "CF", "HD", "SCR",
                "JESDV", "SUBCLASSV"]


def apply_jesd204_synth(generated_docs_dir: Path, is_jesd204: bool,
                        jesd204_ic_name: Optional[str]) -> None:
    """Apply the JESD204B/C synth when the JESD204 signature matched.

    JESD204 is its own data-converter-interface domain, so this does NOT
    overwrite a sibling's protocol values; it populates the JESD204-canonical
    content on the generic base the runner emitted. ic_name is forced across
    all 24 docs and the L17 dependency_graph is force-overwritten.
    """
    if not is_jesd204:
        return
    gd = Path(generated_docs_dir)

    # --- Force ic_name across ALL 24 docs FIRST (main + fields docs). ---
    if jesd204_ic_name is not None:
        for n in _MAIN_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                d["ic_name"] = jesd204_ic_name
                _write(q, d)
        for n in _FIELDS_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                f = _ensure_dict(d, "fields")
                f["ic_name"] = jesd204_ic_name
                d["ic_name"] = jesd204_ic_name  # belt-and-braces top-level
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
# L1 — JESD204 converter-to-logic serial-interface datasheet.
# ----------------------------------------------------------------------
def _l1(gd: Path) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    d["document_title"] = (
        "JESD204 Serial Interface for Data Converters (JESD204B / JESD204C)")
    d["version"] = "JESD204B (2011) / JESD204C (2017)"
    d["revised_date"] = "2011 (204B) / 2017 (204C)"
    d["manufacturer"] = "JEDEC Solid State Technology Association"
    d["copyright"] = "© JEDEC (JC-16 Committee on Interface Technology)"
    d["abstract"] = (
        "JESD204 is a JEDEC high-speed SERIAL interface standard between one "
        "or more DATA CONVERTERS (ADCs / DACs) in a Converter Device and a "
        "LOGIC Device (FPGA/ASIC). It replaces wide parallel LVDS/CMOS "
        "converter buses with L unidirectional differential SerDes lanes, "
        "cutting pin count as converter resolution and sample rate rise. "
        "Converter samples are mapped into octets, optionally scrambled, "
        "line-coded, and serialized; a link is fully described by the "
        "L/M/F/S/N/N'/K frame parameter set. JESD204B (2011) uses 8b/10b "
        "coding up to 12.5 Gbps/lane and defines Subclass 0/1/2 for "
        "deterministic latency (SYSREF in Subclass 1, SYNC~ in Subclass 2). "
        "The link is brought up through Code Group Synchronization (CGS, "
        "/K28.5/ comma) -> Initial Lane Alignment Sequence (ILAS, four "
        "multiframes carrying the link configuration) -> user data, aligned "
        "on the Local MultiFrame Clock (LMFC). JESD204C (2017) adds a "
        "64b/66b (and optional 64b/80b) link layer up to 32 Gbps/lane, "
        "optional Reed-Solomon forward error correction (FEC), and an in-band "
        "command channel.")
    d["keywords"] = [
        "JESD204", "JESD204B", "JESD204C", "data converter", "ADC", "DAC",
        "converter device", "logic device", "lane", "SerDes", "ILAS", "CGS",
        "multiframe", "LMFC", "SYSREF", "SYNC~", "subclass", "8b/10b",
        "64b/66b", "deterministic latency", "scrambling", "L", "M", "F", "S",
        "N", "N'", "K", "K28.5",
    ]
    d["external_pins"] = [
        "Serial lane differential pairs (L pairs, unidirectional CML, "
        "AC-coupled): converter->logic on an ADC link, logic->converter on a "
        "DAC link; carry the line-coded sample payload",
        "Device Clock (DEVCLK): common master clock from which the frame "
        "clock and LMFC are derived at both ends",
        "SYSREF: Subclass 1 deterministic-latency timing reference that "
        "aligns the LMFC at TX and RX (single / periodic / gapped-periodic)",
        "SYNC~ (active-low): JESD204B RX->TX synchronization request — assert "
        "to request CGS, de-assert to start ILAS; also used for error "
        "reporting (in JESD204C the SYNC function moves into the sync header "
        "/ command channel)",
        "Optional command channel (JESD204C): in-band control/status",
    ]
    d["lanes_supported"] = list(_LANES_SUPPORTED)
    d["lanes_max"] = 32
    d["max_lane_rate_Gbps"] = {"jesd204b": _MAX_LANE_RATE_B_GBPS,
                               "jesd204c": _MAX_LANE_RATE_C_GBPS}
    d["link_parameters"] = list(_LINK_PARAMS)
    d["subclasses_supported"] = list(_SUBCLASSES)
    d["modes_of_operation"] = [
        {"name": "Subclass 0", "deterministic_latency": False,
         "alignment": "SYNC~ initiates CGS only",
         "note": "No deterministic latency; backward-compatible with "
                 "JESD204A multi-lane alignment."},
        {"name": "Subclass 1", "deterministic_latency": True,
         "alignment": "SYSREF aligns LMFC at TX and RX",
         "note": "Primary deterministic-latency mechanism; SYSREF distributed "
                 "from a common clock device; preferred at high lane rates."},
        {"name": "Subclass 2", "deterministic_latency": True,
         "alignment": "SYNC~ timing aligns LMFC",
         "note": "Deterministic latency without a routed SYSREF; used at "
                 "lower lane rates."},
        {"name": "JESD204B 8b/10b link layer",
         "max_lane_rate_Gbps": _MAX_LANE_RATE_B_GBPS,
         "note": "8b/10b coding; /K/R/A/Q/F/ control characters; CGS+ILAS."},
        {"name": "JESD204C 64b/66b link layer",
         "max_lane_rate_Gbps": _MAX_LANE_RATE_C_GBPS,
         "note": "64b/66b (or 64b/80b) sync-header block alignment; optional "
                 "Reed-Solomon FEC; command channel."},
    ]
    d["key_features"] = [
        "High-speed serial converter-to-logic interface replacing wide "
        "parallel LVDS/CMOS converter buses.",
        "L unidirectional differential SerDes lanes (L in {1,2,4,8}, up to "
        "32); converter->logic for ADC links, logic->converter for DAC "
        "links.",
        "Converter samples mapped into octets/frames/multiframes via the "
        "L/M/F/S/N/N'/K parameter set (M converters, F octets/frame, S "
        "samples/converter/frame, N resolution, N' bits/sample, K "
        "frames/multiframe).",
        "JESD204B: 8b/10b line coding, up to 12.5 Gbps/lane, three speed "
        "grades; embedded clock recovered by the lane CDR.",
        "JESD204C: 64b/66b (optional 64b/80b) link layer up to 32 Gbps/lane "
        "(~97% efficiency), optional Reed-Solomon FEC, in-band command "
        "channel.",
        "Three-phase bring-up: Code Group Synchronization (CGS, /K28.5/ "
        "comma) -> Initial Lane Alignment Sequence (ILAS, four multiframes "
        "with the link configuration) -> user-data phase.",
        "Subclass 0/1/2 deterministic-latency options: SYSREF (Subclass 1) "
        "or SYNC~ (Subclass 2) align the Local MultiFrame Clock (LMFC).",
        "Optional self-synchronous scrambling (1 + x^14 + x^15) to spread "
        "spectrum and remove data-dependent patterns/spurs.",
        "Multiframe-based lane alignment with an elastic buffer released at "
        "the LMFC boundary for repeatable latency.",
        "Common Device Clock shared by converter and logic device.",
        "8b/10b control characters /K/=K28.5, /R/=K28.0, /A/=K28.3, "
        "/Q/=K28.4, /F/=K28.7 for sync, framing, and alignment.",
        "Error monitoring: disparity / not-in-table / unexpected-control "
        "errors and the ILAS configuration checksum (FCHK).",
    ]
    d["topology_summary"] = (
        "Point-to-point (or point-to-multipoint) link between a Converter "
        "Device (M converters) and a Logic Device over L lanes. ADC links run "
        "converter->logic; DAC links run logic->converter. Multiple converters "
        "may align to one logic device; one converter device may host multiple "
        "links. A shared Device Clock and (Subclass 1) SYSREF provide the "
        "common timing.")
    d["package_summary"] = (
        "JESD204 is an electrical/logical interface standard, not a package "
        "specification. It fixes the lane electrical (CML differential, "
        "AC-coupled, speed grades), the line coding (8b/10b for 204B, 64b/66b "
        "for 204C), the framing/parameter set, and the bring-up/alignment "
        "procedure. Physical packaging of the ADC/DAC and FPGA is a "
        "device/board concern.")
    d["use_cases"] = [
        "Wideband ADCs for software-defined radio, 5G base stations, radar "
        "and instrumentation feeding an FPGA",
        "High-speed DACs for direct RF synthesis driven by an FPGA",
        "Multi-converter, multi-lane phased-array / beamforming systems "
        "requiring deterministic repeatable latency",
        "Synchronized multi-channel data acquisition",
        "Pin-count and routing reduction vs wide parallel LVDS converter "
        "buses",
    ]
    d["revision_history"] = [
        {"version": "JESD204 (2006)",
         "description": "Initial release: single lane, up to 3.125 Gbps, no "
                        "multi-lane alignment."},
        {"version": "JESD204A (2008)",
         "description": "Multiple lanes and multi-lane alignment, up to "
                        "3.125 Gbps."},
        {"version": "JESD204B (2011)",
         "description": "Up to 12.5 Gbps/lane, 8b/10b coding, deterministic "
                        "latency via Subclass 0/1/2 (SYSREF / SYNC~), "
                        "CGS+ILAS bring-up, LMFC/multiframe alignment, "
                        "optional scrambling."},
        {"version": "JESD204C (2017)",
         "description": "Up to 32 Gbps/lane, 64b/66b (optional 64b/80b) link "
                        "layer (~97% efficiency), optional Reed-Solomon FEC, "
                        "in-band command channel; deterministic latency via "
                        "SYSREF retained; dual-mode interop with 204B."},
    ]
    d["overview"] = (
        "JESD204 is a JEDEC standard for a high-speed serial link between data "
        "converters (ADCs/DACs) and a logic device (FPGA/ASIC). Sample data "
        "from M converters is mapped into octets and frames, optionally "
        "scrambled, line-coded, and serialized across L differential SerDes "
        "lanes. The full link is described by the L/M/F/S/N/N'/K parameter set. "
        "JESD204B uses 8b/10b coding up to 12.5 Gbps/lane and defines three "
        "subclasses for deterministic latency (Subclass 1 uses a distributed "
        "SYSREF, Subclass 2 uses the SYNC~ timing, Subclass 0 has none). The "
        "link is brought up by Code Group Synchronization (the receiver "
        "asserts SYNC~, the transmitter streams /K28.5/ commas until character "
        "alignment is achieved on all lanes), then the Initial Lane Alignment "
        "Sequence (four multiframes that align the lanes and carry the link "
        "configuration octets), then the user-data phase aligned on the Local "
        "MultiFrame Clock. JESD204C raises the lane rate to 32 Gbps with a "
        "64b/66b link layer, optional Reed-Solomon FEC, and a command "
        "channel, while preserving deterministic latency via SYSREF.")
    _write(p, d)


# ----------------------------------------------------------------------
# L2 — JESD204 functional model (serial converter link, three-phase
# bring-up, framing parameters, subclasses).
# ----------------------------------------------------------------------
def _l2(gd: Path) -> None:
    p = gd / "L2_FRS.json"
    if not p.is_file():
        return
    d = _read(p)
    po = _ensure_dict(d, "protocol_overview")
    po["type"] = (
        "High-speed serial link between data converters (ADC/DAC) and a logic "
        "device (FPGA/ASIC), over L unidirectional differential SerDes lanes; "
        "samples mapped into the L/M/F/S/N/N'/K frame structure; brought up "
        "via CGS -> ILAS -> data; deterministic latency via Subclass 0/1/2.")
    po["duplex"] = (
        "Unidirectional payload per link (converter->logic for ADC, "
        "logic->converter for DAC); the low-speed SYNC~ runs the opposite "
        "direction (RX->TX) for the synchronization request in JESD204B.")
    po["synchronous_serial"] = True
    po["source_synchronous"] = False
    po["embedded_clock"] = True
    po["forwarded_clock"] = False
    po["encoding"] = (
        "JESD204B: 8b/10b (DC-balanced, run-length-limited) with /K/R/A/Q/F/ "
        "control characters; clock embedded in the serial stream and recovered "
        "by the lane CDR. JESD204C: 64b/66b (optional 64b/80b) with a 2-bit "
        "sync header for block alignment; ~97% efficiency; optional "
        "Reed-Solomon FEC.")
    po["modulation"] = "NRZ differential CML (AC-coupled)."
    po["lanes_supported"] = list(_LANES_SUPPORTED)
    po["lanes_max"] = 32
    po["max_lane_rate_Gbps"] = {"jesd204b": _MAX_LANE_RATE_B_GBPS,
                                "jesd204c": _MAX_LANE_RATE_C_GBPS}
    po["speed_grades_jesd204b_Gbps"] = dict(_SPEED_GRADES_GBPS)
    po["link_parameters"] = {
        "L": "lanes per converter device (per link)",
        "M": "converters per device",
        "F": "octets per frame (per lane)",
        "S": "samples per converter per frame",
        "N": "converter resolution in bits",
        "N'": "total bits per sample (N + control/tail; multiple of 4)",
        "K": "frames per multiframe (1..32; F*K = 4..1024 octets, mult. of 4)",
        "CS": "control bits per sample",
        "CF": "control words per frame per link",
        "HD": "high-density format flag (sample may span lanes)",
        "SCR": "scrambling enable",
        "JESDV": "JESD204 version (0=204A, 1=204B, 2=204C)",
        "SUBCLASSV": "device subclass (0, 1, 2)",
    }
    po["subclasses"] = {
        "0": "No deterministic latency; JESD204A-compatible alignment; SYNC~ "
             "initiates CGS only.",
        "1": "Deterministic latency via distributed SYSREF aligning the LMFC.",
        "2": "Deterministic latency via the SYNC~ timing aligning the LMFC.",
    }
    po["bring_up_phases"] = [
        "CGS (Code Group Synchronization): RX asserts SYNC~, TX streams "
        "/K28.5/ commas, RX achieves character alignment on all lanes.",
        "ILAS (Initial Lane Alignment Sequence): four multiframes that align "
        "lanes to a common multiframe boundary and carry the link "
        "configuration octets (L/M/F/S/N/N'/K/... + FCHK).",
        "Data phase: user converter samples, optionally scrambled, with "
        "/A/ and /F/ alignment characters at multiframe/frame boundaries.",
    ]
    po["lmfc_multiframe"] = (
        "Local MultiFrame Clock with a period of F*K frame clocks (one "
        "multiframe); aligned to SYSREF (Subclass 1) or SYNC~ (Subclass 2); "
        "the receiver elastic buffer releases aligned data at the LMFC "
        "boundary for deterministic latency.")
    po["scrambling"] = (
        "Optional (SCR flag): self-synchronous scrambler 1 + x^14 + x^15 to "
        "spread spectrum and remove data-dependent patterns/spurs; "
        "descrambler is self-synchronizing.")
    po["clocking"] = (
        "Common Device Clock (DEVCLK) at both ends derives the frame clock "
        "and LMFC; the lane bit clock is embedded and recovered by the CDR.")
    d["functional_requirements"] = [
        {"id": "FR-LINK-01", "text": "The link transports M-converter sample "
         "data from a Converter Device to a Logic Device (or vice versa for "
         "DAC) over L unidirectional differential SerDes lanes, framed by the "
         "L/M/F/S/N/N'/K parameter set."},
        {"id": "FR-CODE-02", "text": "JESD204B encodes the lane with 8b/10b "
         "and uses /K28.5/ commas for CGS; JESD204C uses a 64b/66b (optional "
         "64b/80b) link layer with sync-header block alignment and optional "
         "Reed-Solomon FEC."},
        {"id": "FR-BRINGUP-03", "text": "Link bring-up proceeds CGS -> ILAS "
         "-> data: the receiver asserts SYNC~ to request CGS, the transmitter "
         "streams commas, then on a multiframe boundary sends the four-"
         "multiframe ILAS carrying the link configuration, then user data."},
        {"id": "FR-DETLAT-04", "text": "Deterministic latency is provided per "
         "Subclass: Subclass 1 aligns the LMFC to a distributed SYSREF; "
         "Subclass 2 aligns it to the SYNC~ timing; Subclass 0 provides no "
         "deterministic latency."},
        {"id": "FR-SCR-05", "text": "Scrambling is optional (SCR); when "
         "enabled, octets are scrambled with 1 + x^14 + x^15."},
        {"id": "FR-ERR-06", "text": "The receiver detects 8b/10b disparity / "
         "not-in-table / unexpected-control-character errors and validates "
         "the ILAS configuration checksum FCHK; errors may be reported by "
         "re-asserting SYNC~ (204B) or via the command channel (204C)."},
        {"id": "FR-ALIGN-07", "text": "Lane and multiframe alignment is "
         "maintained in the data phase using /A/ (K28.3) at multiframe "
         "boundaries and /F/ (K28.7) at frame boundaries (204B), or "
         "multiblock/extended-multiblock alignment (204C)."},
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L3 — JESD204 link/framing protocol (CGS/ILAS/data, control chars,
# frame->multiframe, scrambling).
# ----------------------------------------------------------------------
def _l3(gd: Path) -> None:
    p = gd / "L3_CMD_PROTOCOL.json"
    if not p.is_file():
        return
    d = _read(p)
    d["protocol_type"] = (
        "Framed serial converter-link protocol. Converter samples are mapped "
        "into N'-bit words, packed S samples/converter into F-octet frames and "
        "K frames into a multiframe, optionally scrambled (1+x^14+x^15), "
        "line-coded (8b/10b for 204B, 64b/66b for 204C) and serialized across "
        "L lanes. Bring-up runs CGS (/K28.5/ commas) -> ILAS (four multiframes "
        "with the link-config octets) -> user data; the LMFC/multiframe "
        "boundary drives lane alignment and deterministic latency.")
    d["channels"] = [
        {"name": "Serial lanes (L differential pairs)",
         "direction": "unidirectional (converter->logic for ADC; "
                      "logic->converter for DAC)",
         "description": "8b/10b (204B) or 64b/66b (204C) line-coded NRZ CML, "
         "AC-coupled, up to 12.5 Gbps (204B) / 32 Gbps (204C); embedded clock "
         "recovered by the lane CDR."},
        {"name": "Device Clock (DEVCLK)", "direction": "input (both ends)",
         "description": "Common master clock; frame clock and LMFC derived "
         "from it."},
        {"name": "SYSREF", "direction": "input (both ends, Subclass 1)",
         "description": "Deterministic-latency timing reference that aligns "
         "the LMFC; single / periodic / gapped-periodic; sampled by DEVCLK."},
        {"name": "SYNC~ (active-low)",
         "direction": "RX -> TX (JESD204B)",
         "description": "Synchronization request: assert to request CGS, "
         "de-assert to start ILAS; also error reporting. In 204C the SYNC "
         "function moves into the sync header / command channel."},
        {"name": "Command channel (JESD204C, optional)",
         "direction": "in-band",
         "description": "In-band control/status signaling in the 64b/66b "
         "link layer."},
    ]
    d["bring_up_phases"] = [
        {"phase": "CGS", "description": "RX asserts SYNC~; TX streams "
         "continuous /K28.5/ commas; RX CDR locks and achieves character "
         "(code-group) alignment; after the required consecutive /K/ on all "
         "lanes RX de-asserts SYNC~."},
        {"phase": "ILAS", "description": "On the next multiframe boundary TX "
         "sends four multiframes. MF1/3/4: /R/(K28.0) ... /A/(K28.3). MF2: "
         "/R/(K28.0) /Q/(K28.4) <link configuration octets> ... /A/(K28.3). "
         "Aligns all lanes and conveys the link config for RX verification."},
        {"phase": "Data", "description": "User converter samples, optionally "
         "scrambled, with /A/ at multiframe boundaries and /F/ at frame "
         "boundaries for alignment monitoring and realignment."},
    ]
    d["frame_structure"] = {
        "sample_word_bits": "N' (N resolution + CS control + tail/dummy; "
                            "multiple of 4)",
        "samples_per_frame_per_converter": "S",
        "octets_per_frame_per_lane": "F",
        "frames_per_multiframe": "K (1..32)",
        "octets_per_multiframe": "F*K (4..1024, multiple of 4)",
        "converters": "M",
        "lanes": "L",
        "high_density": "HD flag — a sample may span lane boundaries",
        "control_words_per_frame": "CF",
    }
    d["control_characters"] = dict(_CONTROL_CHARS)
    d["control_characters_note"] = (
        "These /K/R/A/Q/F/ control characters are 8b/10b (JESD204B/A) "
        "constructs. JESD204C's 64b/66b link layer uses the 2-bit sync header "
        "and multiblock / extended-multiblock alignment instead of "
        "/K/A/F/ characters.")
    d["link_configuration_octets"] = [
        "DID (device ID), BID (bank ID), LID (lane ID)",
        "L (lanes), F (octets/frame), K (frames/multiframe)",
        "M (converters), N (resolution), N' (bits/sample)",
        "CS (control bits/sample), CF (control words/frame)",
        "HD (high density), SCR (scrambling)",
        "JESDV (version), SUBCLASSV (subclass)",
        "ADJCNT / ADJDIR / PHADJ (Subclass 2 LMFC phase adjust)",
        "FCHK (configuration checksum)",
    ]
    d["scrambling"] = {
        "optional": True, "flag": "SCR",
        "polynomial": "1 + x^14 + x^15 (self-synchronous)",
        "purpose": "spread spectrum, remove data-dependent patterns/spurs",
        "descrambler": "self-synchronizing at the receiver",
    }
    d["line_coding"] = {
        "jesd204b": "8b/10b (embedded clock, /K/ comma alignment, control "
                    "characters)",
        "jesd204c": "64b/66b (optional 64b/80b): 2-bit sync header block "
                    "alignment, ~97% efficiency, optional Reed-Solomon FEC, "
                    "command channel",
    }
    d["deterministic_latency"] = {
        "subclass_0": "none (SYNC~ initiates CGS only)",
        "subclass_1": "SYSREF aligns the LMFC at TX and RX",
        "subclass_2": "SYNC~ timing aligns the LMFC",
        "mechanism": "LMFC (period F*K frame clocks) + receiver elastic "
                     "buffer released at the LMFC boundary",
    }
    d["frame_oriented"] = True
    d["byte_oriented"] = True
    d["addressing"] = {
        "note": "JESD204 is an addressless streaming converter link; data is "
                "ordered by lane / converter / sample position within the "
                "frame and multiframe, not by an address.",
        "device_ids": ["DID", "BID", "LID"],
    }
    d["frame_format"] = {
        "lane_framing": "8b/10b characters (204B) framed into F-octet frames "
        "and K-frame multiframes; /A/ at multiframe boundary, /F/ at frame "
        "boundary.",
        "block_framing_204c": "64b/66b blocks with a 2-bit sync header; 32 "
        "blocks per multiblock; extended-multiblock alignment.",
        "ilas_framing": "Four multiframes; MF2 carries the link-config octets "
        "between /Q/(K28.4) and /A/(K28.3).",
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L4 — JESD204 link-configuration / converter-control register model.
# ----------------------------------------------------------------------
def _l4(gd: Path) -> None:
    p = gd / "L4_REGMAP.json"
    if not p.is_file():
        return
    d = _read(p)
    d["register_map_present"] = True
    d["notes"] = (
        "JESD204 link parameters are programmed through the converter's "
        "device control interface (commonly SPI) and are also transmitted "
        "in-band as the ILAS link-configuration octets. The standard fixes the "
        "ILAS octet format; the exact SPI register addresses are "
        "vendor-defined.")
    d["register_access"] = {
        "transport": "Vendor device control bus (typically SPI) plus in-band "
                     "ILAS link-configuration octets",
        "purpose": "Configure and verify the L/M/F/S/N/N'/K link parameters, "
                   "subclass, scrambling, version, and device IDs.",
        "in_band_mirror": "ILAS multiframe 2 carries the link config for RX "
                          "verification.",
    }
    d["register_groups"] = [
        {"group": "Link Geometry", "fields": [
            "L (lanes per device)", "M (converters)", "F (octets/frame)",
            "S (samples/converter/frame)", "K (frames/multiframe)"]},
        {"group": "Sample Format", "fields": [
            "N (converter resolution)", "N' (bits/sample)",
            "CS (control bits/sample)", "CF (control words/frame)",
            "HD (high density)"]},
        {"group": "Link Options", "fields": [
            "SCR (scrambling enable)", "JESDV (version)",
            "SUBCLASSV (subclass 0/1/2)"]},
        {"group": "Device Identification", "fields": [
            "DID (device ID)", "BID (bank ID)", "LID (lane ID)"]},
        {"group": "Subclass 2 Phase Adjust", "fields": [
            "ADJCNT", "ADJDIR", "PHADJ"]},
        {"group": "Integrity", "fields": [
            "FCHK (ILAS configuration checksum)"]},
    ]
    d["ilas_link_config_octets"] = [
        "DID", "BID", "LID", "L", "F", "K", "M", "N", "N'", "CS", "CF", "HD",
        "SCR", "JESDV", "SUBCLASSV", "ADJCNT", "ADJDIR", "PHADJ", "FCHK",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L5 — JESD204 lane electrical / SerDes analog interface.
# ----------------------------------------------------------------------
def _l5(gd: Path) -> None:
    p = gd / "L5_ADI_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["analog_digital_interface_present"] = True
    d["signaling_summary"] = (
        "Each lane is a unidirectional differential CML pair, AC-coupled, "
        "carrying NRZ at the lane bit rate. JESD204B runs up to 12.5 Gbps/lane "
        "in three speed grades (Grade 1: 0.3125-6.375, Grade 2: 6.375-8, "
        "Grade 3: 8-12.5 Gbps) with 8b/10b coding and an embedded clock "
        "recovered by the receiver CDR. JESD204C runs up to 32 Gbps/lane with "
        "a 64b/66b link layer. A common Device Clock and (Subclass 1) SYSREF "
        "provide the deterministic-latency timing references.")
    d["modulation"] = "NRZ differential CML, AC-coupled."
    d["clocking"] = (
        "Embedded clock recovered by the lane CDR for the bit clock; a shared "
        "Device Clock (DEVCLK) derives the frame clock and the Local "
        "MultiFrame Clock at both ends. SYSREF (Subclass 1) is sampled by "
        "DEVCLK to align the LMFC.")
    d["transmitter_specs_canonical"] = {
        "signaling": "differential CML, AC-coupled",
        "modulation": "NRZ",
        "line_encoding_jesd204b": "8b/10b",
        "line_encoding_jesd204c": "64b/66b (optional 64b/80b)",
        "max_lane_rate_Gbps_jesd204b": _MAX_LANE_RATE_B_GBPS,
        "max_lane_rate_Gbps_jesd204c": _MAX_LANE_RATE_C_GBPS,
        "speed_grades_jesd204b_Gbps": dict(_SPEED_GRADES_GBPS),
        "lanes_supported": list(_LANES_SUPPORTED),
        "embedded_clock": True,
        "forwarded_clock": False,
    }
    d["receiver_specs_canonical"] = {
        "clock_recovery": "CDR recovers the embedded bit clock from the lane.",
        "alignment": "Character alignment on /K28.5/ (CGS), then multiframe "
                     "alignment via ILAS and /A//F/ characters (204B) or "
                     "sync-header blocks (204C).",
        "elastic_buffer": "Releases aligned data at the LMFC boundary for "
                          "deterministic latency.",
        "error_monitoring": "disparity / not-in-table / unexpected-control / "
                            "FCHK checksum.",
    }
    d["clock_signals"] = {
        "device_clock": "Common DEVCLK at both ends; source of frame clock "
                        "and LMFC.",
        "sysref": "Subclass 1 deterministic-latency reference; single / "
                  "periodic / gapped-periodic; sampled by DEVCLK.",
        "sync_n": "Active-low RX->TX sync request (204B); also Subclass 2 "
                  "LMFC alignment reference.",
    }
    d["scrambling"] = {
        "optional": True, "polynomial": "1 + x^14 + x^15",
        "purpose": "spectrum spreading, spur reduction at the converter",
    }
    d["encoding_role_in_analog"] = (
        "JESD204B uses 8b/10b for DC balance and run-length limiting so the "
        "receiver CDR can recover the embedded clock; JESD204C uses 64b/66b "
        "with a scrambler for transition density and far lower coding "
        "overhead (~97% efficiency vs 80% for 8b/10b), enabling higher lane "
        "rates and optional Reed-Solomon FEC.")
    _write(p, d)


# ----------------------------------------------------------------------
# L6 — JESD204 link state machine (CGS / ILAS / DATA) + TX/RX framing FSM.
# ----------------------------------------------------------------------
def _l6(gd: Path) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["fsm_states_link"] = [
        {"name": "RESET", "description": "Power-up/reset; link held; Device "
         "Clock and (Subclass 1) SYSREF establishing the LMFC phase."},
        {"name": "CGS", "description": "Code Group Synchronization: RX asserts "
         "SYNC~; TX streams /K28.5/ commas; RX CDR locks and achieves "
         "character alignment on all lanes."},
        {"name": "ILAS", "description": "Initial Lane Alignment Sequence: TX "
         "sends four multiframes aligning lanes and carrying the link-config "
         "octets (verified against RX configuration via FCHK)."},
        {"name": "DATA", "description": "User-data phase: converter samples "
         "(optionally scrambled) framed into frames/multiframes; /A/ and /F/ "
         "maintain alignment (204B)."},
        {"name": "ERROR/RESYNC", "description": "On disparity / not-in-table / "
         "unexpected-control / alignment loss, RX re-asserts SYNC~ (204B) to "
         "force re-synchronization (CGS again) or reports via the command "
         "channel (204C)."},
    ]
    d["fsm_states_tx_framer"] = [
        {"name": "TX_MAP", "description": "Map converter samples into N'-bit "
         "words, S samples/converter/frame."},
        {"name": "TX_FRAME", "description": "Pack F octets/frame, K "
         "frames/multiframe across L lanes; insert /A//F/ at boundaries."},
        {"name": "TX_SCRAMBLE", "description": "Optionally scramble octets "
         "(1+x^14+x^15) when SCR=1."},
        {"name": "TX_ENCODE", "description": "8b/10b encode (204B) or 64b/66b "
         "block-encode (204C) and serialize across the lanes."},
    ]
    d["fsm_states_rx_deframer"] = [
        {"name": "RX_ALIGN", "description": "Recover the clock, align on "
         "/K28.5/, then on the multiframe via ILAS."},
        {"name": "RX_DECODE", "description": "8b/10b decode (204B) or 64b/66b "
         "block-decode (204C); flag disparity / not-in-table errors."},
        {"name": "RX_DESCRAMBLE", "description": "Self-synchronizing "
         "descramble when SCR=1."},
        {"name": "RX_DEFRAME", "description": "Recover samples by lane / "
         "converter / position; release at the LMFC boundary from the elastic "
         "buffer for deterministic latency."},
    ]
    d["fsm_hints"] = {
        "trigger": "RX asserts SYNC~ -> TX enters CGS (commas) -> RX "
        "de-asserts SYNC~ -> TX starts ILAS on the next multiframe boundary "
        "-> after four multiframes both enter DATA.",
        "rule": "The LMFC (period F*K frame clocks) is aligned to SYSREF "
        "(Subclass 1) or SYNC~ (Subclass 2); ILAS begins on an LMFC/multiframe "
        "boundary so latency is deterministic.",
        "abort": "Repeated decode/alignment errors re-assert SYNC~ to restart "
        "CGS (204B) or are reported on the command channel (204C).",
    }
    d["anti_deadlock_rule"] = (
        "The SYNC~ handshake bounds CGS: TX streams commas only while SYNC~ is "
        "asserted, and starts ILAS deterministically on the next multiframe "
        "boundary after SYNC~ de-asserts; the receiver elastic buffer is "
        "bounded by the LMFC period.")
    d["exit_from_reset_or_poweron"] = (
        "After reset, the Device Clock and (Subclass 1) SYSREF establish the "
        "LMFC phase; the receiver asserts SYNC~ to request CGS; the link then "
        "proceeds CGS -> ILAS -> DATA. Deterministic latency holds across "
        "power cycles when the LMFC is SYSREF-aligned.")
    d["default_ready_state_recommendation"] = {
        "TX_idle": "Stream /K28.5/ commas (CGS) while SYNC~ is asserted; idle "
        "to the data phase only after ILAS completes.",
        "RX_idle": "Assert SYNC~ until character + multiframe alignment is "
        "achieved; then de-assert and accept ILAS, then data.",
    }
    d["configurations"] = [
        {"name": "Single-lane link (L=1)", "description": "One lane; "
         "multi-lane alignment trivial."},
        {"name": "Multi-lane link (L=2/4/8)", "description": "Lanes aligned to "
         "a common multiframe boundary via ILAS and /A/ characters."},
        {"name": "Subclass 1 (SYSREF)", "description": "Deterministic latency "
         "via distributed SYSREF aligning the LMFC."},
        {"name": "Subclass 2 (SYNC~)", "description": "Deterministic latency "
         "via the SYNC~ timing aligning the LMFC."},
    ]
    d["timing_dependency_rule"] = (
        "All lanes share the Device Clock; the frame clock and LMFC are "
        "derived from it. The LMFC boundary drives multiframe alignment and "
        "elastic-buffer release; SYSREF/SYNC~ fix the LMFC phase for "
        "deterministic latency.")
    _write(p, d)


# ----------------------------------------------------------------------
# L7 — JESD204 observability (SYNC~ error reporting, FCHK, error counters).
# ----------------------------------------------------------------------
def _l7(gd: Path) -> None:
    p = gd / "L7_TEST_DEBUG.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_debug_architecture_present"] = True
    d["spec_provided_observability"] = [
        {"name": "SYNC~ error reporting", "purpose": "JESD204B receivers can "
         "re-assert SYNC~ (with defined timing) to report link errors and "
         "force re-synchronization."},
        {"name": "ILAS configuration checksum (FCHK)", "purpose": "The "
         "receiver verifies the in-band link configuration against its own; a "
         "checksum mismatch flags a misconfigured link."},
        {"name": "8b/10b error monitoring", "purpose": "Disparity errors, "
         "not-in-table (invalid code) errors, and unexpected control "
         "characters are detected and counted (204B)."},
        {"name": "Command channel / CRC / FEC status (204C)", "purpose": "In "
         "JESD204C the command channel and CRC/FEC report payload integrity "
         "and status in-band."},
        {"name": "Alignment monitoring", "purpose": "/A/ (multiframe) and /F/ "
         "(frame) characters allow continuous lane/frame alignment checking "
         "and realignment (204B)."},
    ]
    d["error_detection_mechanisms"] = [
        "8b/10b disparity errors (204B).",
        "8b/10b not-in-table (invalid code group) errors (204B).",
        "Unexpected control character errors (a /K/A/F/ out of place).",
        "ILAS configuration checksum (FCHK) mismatch.",
        "Lane/multiframe alignment loss (missing /A/ or /F/).",
        "JESD204C: CRC and optional Reed-Solomon FEC on the payload.",
    ]
    d["test_modes"] = [
        {"name": "CGS / sync-pattern test", "purpose": "Verify /K28.5/ comma "
         "alignment and the SYNC~ handshake."},
        {"name": "ILAS verification", "purpose": "Check the four-multiframe "
         "ILAS content and the FCHK checksum."},
        {"name": "Error-injection", "purpose": "Inject disparity / invalid "
         "code / misalignment and confirm detection and SYNC~ re-assertion."},
        {"name": "Deterministic-latency test", "purpose": "Verify repeatable "
         "latency across power cycles in Subclass 1/2."},
    ]
    d["interrupt_or_event_sources"] = [
        {"event": "Sync request / loss", "trigger": "SYNC~ asserted by RX."},
        {"event": "Code error", "trigger": "disparity / not-in-table / "
         "unexpected control character."},
        {"event": "Config mismatch", "trigger": "FCHK checksum mismatch."},
        {"event": "Alignment loss", "trigger": "missing /A/ or /F/ at a "
         "boundary."},
    ]
    d["notes"] = (
        "JESD204's protocol-level observability is the SYNC~ error-reporting "
        "path, the ILAS FCHK checksum, the 8b/10b error monitors (204B), and "
        "the command channel / CRC / FEC status (204C). Chip-level JTAG/scan/"
        "BIST remain device-integrator concerns.")
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
        "JESD204_VERSIONS": "B (2011) / C (2017)",
        "LANES_SUPPORTED": list(_LANES_SUPPORTED),
        "LANES_MAX": 32,
        "MAX_LANE_RATE_GBPS_204B": _MAX_LANE_RATE_B_GBPS,
        "MAX_LANE_RATE_GBPS_204C": _MAX_LANE_RATE_C_GBPS,
        "LINE_CODING_204B": "8b/10b",
        "LINE_CODING_204C": "64b/66b (optional 64b/80b)",
        "MODULATION": "NRZ differential CML",
        "EMBEDDED_CLOCK": True,
        "FORWARDED_CLOCK": False,
        "K_FRAMES_PER_MULTIFRAME_MIN": 1,
        "K_FRAMES_PER_MULTIFRAME_MAX": 32,
        "OCTETS_PER_MULTIFRAME_MIN": 4,
        "OCTETS_PER_MULTIFRAME_MAX": 1024,
        "N_PRIME_MULTIPLE_OF": 4,
        "SUBCLASSES": list(_SUBCLASSES),
        "SCRAMBLER_POLYNOMIAL": "1 + x^14 + x^15",
        "CONTROL_CHAR_K_COMMA": "K28.5",
        "CONTROL_CHAR_R_START_MF": "K28.0",
        "CONTROL_CHAR_A_END_MF": "K28.3",
        "CONTROL_CHAR_Q_START_CFG": "K28.4",
        "CONTROL_CHAR_F_FRAME": "K28.7",
        "ILAS_MULTIFRAMES": 4,
    })
    d["link_parameter_symbols"] = {
        "L": "lanes per device", "M": "converters per device",
        "F": "octets per frame", "S": "samples per converter per frame",
        "N": "converter resolution (bits)", "N'": "bits per sample",
        "K": "frames per multiframe", "CS": "control bits per sample",
        "CF": "control words per frame", "HD": "high-density flag",
        "SCR": "scrambling enable", "JESDV": "version",
        "SUBCLASSV": "subclass",
    }
    d["lane_rate_formula"] = (
        "lane_rate = (M * S * N' * f_s) * code_overhead / L, where "
        "code_overhead = 10/8 (8b/10b, 204B) or 66/64 (64b/66b, 204C) and "
        "f_s is the converter sample rate.")
    d["control_character_table"] = dict(_CONTROL_CHARS)
    kc = _ensure_dict(d, "key_constants_for_RTL_authoring")
    kc.update({
        "is_serial": True,
        "is_differential": True,
        "embedded_clock": True,
        "forwarded_clock": False,
        "line_coding_204b": "8b/10b",
        "line_coding_204c": "64b/66b",
        "max_lane_rate_Gbps_204b": _MAX_LANE_RATE_B_GBPS,
        "max_lane_rate_Gbps_204c": _MAX_LANE_RATE_C_GBPS,
        "lanes_supported": list(_LANES_SUPPORTED),
        "subclasses": list(_SUBCLASSES),
        "scrambling_optional": True,
        "scrambler_polynomial": "1 + x^14 + x^15",
        "bring_up": "CGS -> ILAS -> DATA",
        "ilas_multiframes": 4,
        "lmfc_period_frames": "F*K",
        "deterministic_latency": "Subclass 1 (SYSREF) / Subclass 2 (SYNC~)",
    })
    d["default_signal_values_when_idle"] = {
        "cgs": "TX streams /K28.5/ commas while SYNC~ asserted.",
        "sync_n": "active-low; asserted (0) to request sync / report error.",
        "sysref": "Subclass 1 timing reference; idle between pulses.",
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
    d["lane_waveform"] = {
        "signaling": "differential CML NRZ, AC-coupled, per lane.",
        "coding": "8b/10b (204B) / 64b/66b (204C).",
        "clocking": "embedded clock recovered by the lane CDR; not "
                    "source-synchronous.",
        "max_lane_rate_Gbps": {"jesd204b": _MAX_LANE_RATE_B_GBPS,
                               "jesd204c": _MAX_LANE_RATE_C_GBPS},
    }
    d["cgs_waveform"] = {
        "description": "RX asserts SYNC~ (low); TX transmits continuous "
        "/K28.5/ commas; RX achieves character alignment; SYNC~ de-asserts.",
        "comma": "K28.5",
    }
    d["ilas_waveform"] = {
        "multiframes": 4,
        "mf1": "/R/(K28.0) ... /A/(K28.3)",
        "mf2": "/R/(K28.0) /Q/(K28.4) <link config octets + FCHK> ... "
               "/A/(K28.3)",
        "mf3": "same as MF1",
        "mf4": "same as MF1",
        "starts_on": "multiframe / LMFC boundary after SYNC~ de-asserts",
    }
    d["data_waveform"] = {
        "framing": "S samples/converter/frame; F octets/frame; K "
                   "frames/multiframe across L lanes.",
        "alignment_chars": "/A/(K28.3) at multiframe boundary, /F/(K28.7) at "
                           "frame boundary (204B).",
        "scrambling": "optional 1+x^14+x^15.",
    }
    d["sysref_waveform"] = {
        "subclass": 1,
        "forms": ["single pulse", "periodic", "gapped-periodic"],
        "sampled_by": "Device Clock (DEVCLK)",
        "purpose": "align the LMFC at TX and RX for deterministic latency.",
    }
    d["lmfc_waveform"] = {
        "period_frames": "F*K",
        "aligned_to": "SYSREF (Subclass 1) / SYNC~ (Subclass 2)",
        "role": "multiframe boundary; elastic-buffer release point.",
    }
    d["general_timing_rule"] = (
        "The lane unit interval is set by the lane bit rate (e.g. 80 ps UI at "
        "12.5 Gbps for 204B, 31.25 ps UI at 32 Gbps for 204C). The frame "
        "clock and LMFC (period F*K frame clocks) are derived from the shared "
        "Device Clock; SYSREF/SYNC~ fix the LMFC phase. ILAS begins on an LMFC "
        "boundary so the converter-to-logic latency is deterministic and "
        "repeatable.")
    d["data_rate_waveform"] = {
        "max_lane_rate_Gbps": {"jesd204b": _MAX_LANE_RATE_B_GBPS,
                               "jesd204c": _MAX_LANE_RATE_C_GBPS},
        "speed_grades_jesd204b_Gbps": dict(_SPEED_GRADES_GBPS),
        "modulation": "NRZ",
        "coding": {"jesd204b": "8b/10b", "jesd204c": "64b/66b"},
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L9 — JESD204 integration spec (converter<->logic link integration).
# ----------------------------------------------------------------------
def _l9(gd: Path) -> None:
    p = gd / "L9_INTEGRATION_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["module_role"] = (
        "Converter-to-logic serial link: maps M-converter samples into the "
        "L/M/F/S/N/N'/K frame structure, optionally scrambles, line-codes "
        "(8b/10b 204B / 64b/66b 204C), and serializes across L lanes, with "
        "CGS->ILAS->data bring-up and Subclass 0/1/2 deterministic latency.")
    d["topology_description"] = (
        "Point-to-point (or point-to-multipoint) link between a Converter "
        "Device (M converters) and a Logic Device over L unidirectional lanes; "
        "a shared Device Clock and (Subclass 1) SYSREF provide common timing; "
        "SYNC~ runs RX->TX for the synchronization request (204B).")
    io = _ensure_dict(d, "integration_overview")
    io.update({
        "jesd204_versions": "B (2011) / C (2017)",
        "lanes_supported": list(_LANES_SUPPORTED),
        "lanes_max": 32,
        "max_lane_rate_Gbps": {"jesd204b": _MAX_LANE_RATE_B_GBPS,
                               "jesd204c": _MAX_LANE_RATE_C_GBPS},
        "line_coding": {"jesd204b": "8b/10b", "jesd204c": "64b/66b"},
        "modulation": "NRZ differential CML",
        "clocking": "embedded clock + shared Device Clock + SYSREF "
                    "(Subclass 1)",
        "link_parameters": list(_LINK_PARAMS),
        "subclasses": list(_SUBCLASSES),
        "bring_up": "CGS -> ILAS -> DATA",
        "scrambling_optional": True,
        "deterministic_latency": "Subclass 1 (SYSREF) / Subclass 2 (SYNC~)",
        "control_interface": "vendor SPI for link parameters + in-band ILAS "
                             "config octets",
    })
    d["interface_categories"] = [
        "Serial lanes (L differential pairs) — line-coded sample payload.",
        "Device Clock (DEVCLK) — shared frame-clock / LMFC source.",
        "SYSREF — Subclass 1 deterministic-latency reference.",
        "SYNC~ — RX->TX sync request / Subclass 2 LMFC reference (204B).",
        "Command channel — in-band control/status (204C, optional).",
        "Device control bus (SPI) — link-parameter configuration.",
    ]
    d["interconnect_topologies_supported"] = [
        "Single converter device to single logic device, L lanes.",
        "Multiple converter devices aligned to one logic device.",
        "One converter device hosting multiple links.",
        "Multi-lane (L=2/4/8) links aligned via ILAS to a common multiframe.",
    ]
    d["default_signal_values_when_omitted"] = (
        "SYNC~ idles de-asserted (high) once synced; SYSREF idles between "
        "pulses; scrambling defaults per the SCR flag. In the idle/CGS state "
        "the TX streams /K28.5/ commas while SYNC~ is asserted.")
    d["soc_dependent_items"] = [
        "Lane count L and per-lane rate (within the speed grade / 204C rate).",
        "Converter count M, resolution N, N', and frame parameters F/S/K.",
        "Subclass selection (0/1/2) and SYSREF/SYNC~ distribution.",
        "Device Clock generation and SYSREF alignment to DEVCLK.",
        "Scrambling enable (SCR) and version (JESDV).",
        "SerDes PHY (CDR, 8b/10b or 64b/66b, optional FEC) implementation.",
        "Vendor SPI register map for link parameters.",
    ]
    d["device_classes_examples"] = [
        "High-speed ADC converter device (transmitter on an ADC link)",
        "High-speed DAC converter device (receiver on a DAC link)",
        "FPGA/ASIC logic device (receiver for ADC, transmitter for DAC)",
        "Clock/SYSREF generation device for Subclass 1",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L10 — JESD204 compliance/test categories.
# ----------------------------------------------------------------------
def _l10(gd: Path) -> None:
    p = gd / "L10_TEST_CASES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_cases_present"] = (
        "partial - the standard defines link behaviors (CGS, ILAS, data, "
        "deterministic latency, error handling) that map to a compliance/"
        "interoperability test plan; the standard itself is not a testbench.")
    d["derived_compliance_test_categories"] = [
        "CGS: RX asserts SYNC~, TX streams /K28.5/ commas, RX achieves "
        "character alignment on all L lanes, SYNC~ de-asserts.",
        "ILAS: four multiframes; MF2 carries the link-config octets between "
        "/Q/(K28.4) and /A/(K28.3); RX verifies FCHK.",
        "Multi-lane alignment to a common multiframe boundary (L=2/4/8).",
        "Data phase framing: S samples/converter/frame, F octets/frame, K "
        "frames/multiframe across L lanes.",
        "Scrambling on/off (SCR) with the 1+x^14+x^15 scrambler.",
        "8b/10b coding (204B): disparity, not-in-table, unexpected-control "
        "detection; /A//F/ alignment.",
        "64b/66b coding (204C): sync-header block alignment, multiblock / "
        "extended-multiblock, optional Reed-Solomon FEC, command channel.",
        "Subclass 0: no deterministic latency (SYNC~ initiates CGS only).",
        "Subclass 1: SYSREF aligns the LMFC; verify deterministic, repeatable "
        "latency across power cycles.",
        "Subclass 2: SYNC~ timing aligns the LMFC.",
        "Lane rates: 204B up to 12.5 Gbps (Grades 1/2/3); 204C up to 32 Gbps.",
        "Error reporting: re-assert SYNC~ on link error (204B); command "
        "channel/CRC status (204C).",
        "Link-parameter set L/M/F/S/N/N'/K/CS/CF/HD coverage.",
        "Device IDs DID/BID/LID and FCHK checksum.",
        "LMFC/multiframe boundary and elastic-buffer release timing.",
        "DAC link direction (logic->converter) vs ADC link "
        "(converter->logic).",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L11 — JESD204 capability / config (no OTP concept).
# ----------------------------------------------------------------------
def _l11(gd: Path) -> None:
    p = gd / "L11_OTP_CONTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    d["otp_present"] = False
    d["otp_equivalent_factory_burned_fields"] = [
        {"field": "JESDV (version)", "width_bits": "implementation-defined",
         "location": "link-config octets / device register",
         "note": "JESD204 version (0=204A, 1=204B, 2=204C)."},
        {"field": "SUBCLASSV (subclass)", "width_bits": 3,
         "location": "link-config octets / device register",
         "note": "Device subclass 0/1/2 capability."},
        {"field": "N / N' (resolution / bits per sample)",
         "width_bits": "implementation-defined",
         "location": "link-config octets / device register",
         "note": "Converter resolution and lane sample-word width; a "
                 "hardware property of the converter."},
        {"field": "Max lane rate / speed grade",
         "width_bits": "implementation-defined",
         "location": "device register",
         "note": "Electrical speed-grade capability of the SerDes."},
        {"field": "DID / BID", "width_bits": "implementation-defined",
         "location": "link-config octets",
         "note": "Device and bank identification."},
    ]
    d["notes"] = (
        "JESD204 does not define OTP/fuse content as a protocol concept. The "
        "interoperability-relevant facts (version, subclass, resolution, lane "
        "rate, device IDs) are configured through the vendor control bus and "
        "transmitted in-band as the ILAS link-configuration octets; an "
        "implementation may back some with fuses, but the standard only "
        "requires they be configured/discoverable.")
    _write(p, d)


# ----------------------------------------------------------------------
# L12 — JESD204 behavioral sequences.
# ----------------------------------------------------------------------
def _l12(gd: Path) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["link_bring_up_sequence"] = [
        "1. Reset; Device Clock running; (Subclass 1) SYSREF establishes the "
        "LMFC phase at TX and RX.",
        "2. Receiver asserts SYNC~ (active-low) to request synchronization.",
        "3. CGS: transmitter streams continuous /K28.5/ commas; receiver CDR "
        "locks and achieves character alignment on all L lanes.",
        "4. Receiver de-asserts SYNC~ once the required consecutive /K/ are "
        "received on all lanes.",
        "5. ILAS: on the next multiframe boundary the transmitter sends four "
        "multiframes; MF2 carries the link-config octets (L/M/F/S/N/N'/K/... "
        "+ FCHK).",
        "6. Receiver verifies the link configuration (FCHK) against its own "
        "settings.",
        "7. Data phase: user converter samples (optionally scrambled) are "
        "transmitted, with /A/ at multiframe and /F/ at frame boundaries "
        "(204B).",
        "8. Deterministic latency holds (Subclass 1/2) via LMFC alignment and "
        "the elastic-buffer release.",
    ]
    d["cgs_sequence"] = [
        "1. RX asserts SYNC~.",
        "2. TX transmits /K28.5/ commas continuously.",
        "3. RX achieves character (code-group) alignment on the comma.",
        "4. After the required consecutive /K/ on all lanes, RX de-asserts "
        "SYNC~.",
    ]
    d["ilas_sequence"] = [
        "1. TX starts ILAS on the first multiframe boundary after SYNC~ "
        "de-asserts.",
        "2. MF1: /R/(K28.0) ... /A/(K28.3).",
        "3. MF2: /R/(K28.0) /Q/(K28.4) <link-config octets + FCHK> ... "
        "/A/(K28.3).",
        "4. MF3, MF4: same as MF1.",
        "5. RX aligns all lanes to the common multiframe and verifies the "
        "config.",
    ]
    d["data_phase_sequence"] = [
        "1. TX maps converter samples into N'-bit words, S/converter/frame.",
        "2. Optional scrambling (1+x^14+x^15) when SCR=1.",
        "3. 8b/10b (204B) or 64b/66b (204C) encode and serialize across L "
        "lanes.",
        "4. RX recovers, decodes, descrambles, deframes, and releases samples "
        "at the LMFC boundary from the elastic buffer.",
    ]
    d["error_resync_sequence"] = [
        "1. RX detects disparity / not-in-table / unexpected-control / "
        "alignment loss.",
        "2. RX re-asserts SYNC~ (204B) with the defined error-reporting "
        "timing.",
        "3. Link restarts CGS -> ILAS -> data (or reports via the command "
        "channel in 204C).",
    ]
    d["reset_sequence"] = [
        "1. Reset asserted; link held; LMFC phase re-established from "
        "SYSREF/SYNC~ on release.",
        "2. RX asserts SYNC~ -> CGS -> ILAS -> data on reset deassertion.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L13 — JESD204 lab/characterization targets.
# ----------------------------------------------------------------------
def _l13(gd: Path) -> None:
    p = gd / "L13_LAB_CALIBRATION.json"
    if not p.is_file():
        return
    d = _read(p)
    d["lab_calibration_present"] = False
    d["lab_measurement_targets_from_spec"] = [
        {"name": "Per-lane data eye", "purpose": "Verify the differential CML "
         "lane meets the eye/jitter budget at the target rate (up to 12.5 "
         "Gbps 204B / 32 Gbps 204C)."},
        {"name": "CDR lock / comma alignment", "purpose": "Confirm the "
         "receiver CDR locks and aligns on /K28.5/ during CGS."},
        {"name": "ILAS / FCHK", "purpose": "Validate the four-multiframe ILAS "
         "content and the configuration checksum."},
        {"name": "Deterministic latency", "purpose": "Measure repeatable "
         "converter-to-logic latency across power cycles in Subclass 1/2 "
         "(SYSREF/SYNC~ aligned LMFC)."},
        {"name": "SYSREF setup/hold vs Device Clock", "purpose": "Verify "
         "SYSREF is sampled correctly by DEVCLK for LMFC alignment."},
        {"name": "Multi-lane skew", "purpose": "Confirm lanes align to a "
         "common multiframe boundary within the elastic-buffer budget."},
        {"name": "Scrambler/descrambler", "purpose": "Verify 1+x^14+x^15 "
         "scrambling and self-synchronizing descrambling."},
    ]
    d["notes"] = (
        "JESD204 characterization centers on the SerDes lane eye and CDR, the "
        "CGS/ILAS bring-up, multi-lane skew within the multiframe/elastic-"
        "buffer budget, and (Subclass 1/2) SYSREF/SYNC~ deterministic-latency "
        "timing. Per-device PHY calibration is done at bring-up.")
    _write(p, d)


# ----------------------------------------------------------------------
# L14 — JESD204 versioning + interop traps.
# ----------------------------------------------------------------------
def _l14(gd: Path) -> None:
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["spec_version"] = (
        "JEDEC JESD204B (July 2011) and JESD204C (December 2017), Serial "
        "Interface for Data Converters")
    f["previous_versions"] = [
        "JESD204 (2006) — single lane, up to 3.125 Gbps, no lane alignment.",
        "JESD204A (2008) — multiple lanes + multi-lane alignment, up to "
        "3.125 Gbps.",
    ]
    f["key_changes"] = [
        {"version": "JESD204B (2011)", "summary": "Up to 12.5 Gbps/lane, "
         "8b/10b coding, deterministic latency via Subclass 0/1/2 "
         "(SYSREF/SYNC~), CGS+ILAS bring-up, LMFC/multiframe alignment, "
         "optional scrambling (1+x^14+x^15), the L/M/F/S/N/N'/K parameter "
         "set."},
        {"version": "JESD204C (2017)", "summary": "Up to 32 Gbps/lane; "
         "64b/66b (optional 64b/80b) link layer (~97% efficiency) replacing "
         "8b/10b; sync-header block / multiblock alignment; optional "
         "Reed-Solomon FEC; in-band command channel; deterministic latency "
         "via SYSREF retained; dual-mode interop with 204B."},
    ]
    f["backward_compat_traps"] = [
        {"trap_name": "Subclass_must_match",
         "rule": "Both ends must use the same subclass (0/1/2) for "
                 "deterministic latency to work.",
         "trap": "Mixing a Subclass 1 (SYSREF) end with a Subclass 0 end "
                 "loses deterministic latency."},
        {"trap_name": "Coding_differs_by_generation",
         "rule": "JESD204B is 8b/10b; JESD204C is 64b/66b.",
         "trap": "A 204C-only (64b/66b) link cannot interoperate with a "
                 "204B (8b/10b) link unless the device is dual-mode."},
        {"trap_name": "Link_parameters_must_agree",
         "rule": "L/M/F/S/N/N'/K/SCR must match at both ends (verified by "
                 "FCHK).",
         "trap": "A mismatch fails the ILAS FCHK check and the link will not "
                 "enter the data phase."},
        {"trap_name": "SYNC_is_active_low",
         "rule": "SYNC~ is active-low (assert = 0) and is the RX->TX request "
                 "in 204B.",
         "trap": "Treating SYNC~ as active-high inverts the bring-up "
                 "handshake."},
        {"trap_name": "Embedded_clock_not_forwarded",
         "rule": "The lane clock is embedded (recovered by CDR); the Device "
                 "Clock is a separate shared reference.",
         "trap": "Assuming a forwarded/source-synchronous lane clock (as in "
                 "DDR or UCIe) is wrong for JESD204."},
        {"trap_name": "Scrambling_must_match",
         "rule": "SCR must be the same at both ends.",
         "trap": "One end scrambling while the other does not yields garbage "
                 "data."},
    ]
    f["future_versions_industry_outline"] = [
        {"version": "JESD204D (in development)", "summary": "Higher lane rates "
         "and 128b/132b-class coding under discussion at JEDEC; same "
         "converter-link model."},
    ]
    f["version_naming_history_note"] = (
        "JESD204 is maintained by the JEDEC JC-16 Committee. JESD204 (2006) "
        "introduced the single-lane converter serial link; JESD204A (2008) "
        "added multi-lane alignment; JESD204B (2011) added deterministic "
        "latency (subclasses, SYSREF/SYNC~), 8b/10b, and up to 12.5 Gbps; "
        "JESD204C (2017) added the 64b/66b link layer, optional FEC, the "
        "command channel, and up to 32 Gbps. Facts here are grounded in the "
        "public JEDEC JESD204B/JESD204C standards.")
    _write(p, d)


# ----------------------------------------------------------------------
# L15 — JESD204 encoding / parameter / control-character tables.
# ----------------------------------------------------------------------
def _l15(gd: Path) -> None:
    p = gd / "L15_ENCODING_TABLES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["link_parameter_table"] = {
        "header_columns": ["Symbol", "Meaning", "Range / Note"],
        "rows": [
            ["L", "Lanes per device", "1,2,4,8 (up to 32)"],
            ["M", "Converters per device", "device-defined"],
            ["F", "Octets per frame", "F*K = 4..1024, multiple of 4"],
            ["S", "Samples per converter per frame", "device-defined"],
            ["N", "Converter resolution (bits)", "e.g. 12/14/16"],
            ["N'", "Bits per sample", "multiple of 4 (>= N)"],
            ["K", "Frames per multiframe", "1..32"],
            ["CS", "Control bits per sample", "0..3"],
            ["CF", "Control words per frame", "device-defined"],
            ["HD", "High-density flag", "0/1"],
            ["SCR", "Scrambling enable", "0/1"],
            ["JESDV", "Version", "0=204A,1=204B,2=204C"],
            ["SUBCLASSV", "Subclass", "0/1/2"],
        ],
    }
    f["control_character_table"] = {
        "header_columns": ["Name", "8b/10b Code", "Role"],
        "rows": [
            ["/K/", "K28.5", "CGS comma / code group synchronization"],
            ["/R/", "K28.0", "start of multiframe (ILAS / data)"],
            ["/A/", "K28.3", "end of multiframe / lane alignment"],
            ["/Q/", "K28.4", "start of link configuration data (ILAS MF2)"],
            ["/F/", "K28.7", "frame alignment character"],
        ],
    }
    f["lane_rate_table"] = {
        "header_columns": ["Generation", "Line Coding", "Max Lane Rate",
                           "Speed Grades"],
        "rows": [
            ["JESD204B", "8b/10b", "12.5 Gbps",
             "G1 0.3125-6.375 / G2 6.375-8 / G3 8-12.5 Gbps"],
            ["JESD204C", "64b/66b (opt 64b/80b)", "32 Gbps",
             "single high-rate grade"],
        ],
    }
    f["subclass_table"] = {
        "header_columns": ["Subclass", "Deterministic Latency",
                           "Alignment Reference"],
        "rows": [
            ["0", "no", "SYNC~ initiates CGS only"],
            ["1", "yes", "SYSREF aligns LMFC"],
            ["2", "yes", "SYNC~ timing aligns LMFC"],
        ],
    }
    f["scrambler_note"] = (
        "Optional self-synchronous scrambler with polynomial 1 + x^14 + x^15; "
        "spreads spectrum and removes data-dependent patterns; the "
        "descrambler is self-synchronizing.")
    f["encoding_note"] = (
        "JESD204B line-codes the lane with 8b/10b (embedded clock, /K/ comma "
        "alignment, /K/R/A/Q/F/ control characters). JESD204C uses a 64b/66b "
        "link layer with a 2-bit sync header for block alignment, ~97% "
        "efficiency, optional Reed-Solomon FEC, and an in-band command "
        "channel.")
    f["tables"] = [
        "Link-parameter table (L/M/F/S/N/N'/K/CS/CF/HD/SCR/JESDV/SUBCLASSV)",
        "Control-character table (/K/R/A/Q/F/ = K28.5/0/3/4/7)",
        "Lane-rate / coding table (204B 8b/10b 12.5G; 204C 64b/66b 32G)",
        "Subclass table (0/1/2 deterministic latency)",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L16 — JESD204 compliance properties.
# ----------------------------------------------------------------------
def _l16(gd: Path) -> None:
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["must_have_properties"] = [
        "A serial link between data converters (ADC/DAC) and a logic device "
        "over L unidirectional differential lanes.",
        "Sample mapping via the L/M/F/S/N/N'/K parameter set into frames and "
        "multiframes.",
        "Line coding: 8b/10b (204B) or 64b/66b (204C) with embedded clock "
        "recovered by the lane CDR.",
        "Three-phase bring-up: CGS (/K28.5/ commas) -> ILAS (four multiframes "
        "with the link config + FCHK) -> data.",
        "A common Device Clock; SYNC~ (active-low) RX->TX sync request "
        "(204B).",
        "Subclass 0/1/2 selection; Subclass 1 uses SYSREF and Subclass 2 uses "
        "SYNC~ to align the LMFC for deterministic latency.",
        "Local MultiFrame Clock (period F*K frames) and multiframe-based lane "
        "alignment with an elastic buffer.",
        "Optional scrambling (1+x^14+x^15) gated by SCR.",
        "Error monitoring: 8b/10b disparity/not-in-table/unexpected-control "
        "and FCHK (204B); CRC/FEC + command channel (204C).",
    ]
    f["must_not_have_properties"] = [
        "A forwarded / source-synchronous lane clock (JESD204 lanes use an "
        "embedded clock recovered by CDR).",
        "An address-based transaction model (JESD204 is a streaming converter "
        "link, ordered by lane/converter/sample position).",
        "Mismatched subclass / coding / link parameters between the two ends.",
        "Active-high SYNC (SYNC~ is active-low).",
        "Reliance on a parallel LVDS/CMOS sample bus (JESD204 serializes the "
        "samples).",
    ]
    f["compliance_failure_modes"] = [
        {"mode": "CGS failure", "trigger": "RX cannot align on /K28.5/ "
         "commas; SYNC~ stays asserted."},
        {"mode": "ILAS / FCHK mismatch", "trigger": "RX link config does not "
         "match the transmitted ILAS octets."},
        {"mode": "Multi-lane skew exceeded", "trigger": "Lane skew exceeds "
         "the elastic-buffer / multiframe budget."},
        {"mode": "Deterministic-latency loss", "trigger": "SYSREF/SYNC~ "
         "misaligned, or subclass mismatch."},
        {"mode": "Coding mismatch", "trigger": "8b/10b vs 64b/66b mismatch "
         "between 204B and 204C ends."},
        {"mode": "Scrambling mismatch", "trigger": "SCR differs between "
         "ends."},
    ]
    f["min_link_constraint"] = (
        "A link must complete CGS on all L lanes, pass ILAS (matching FCHK), "
        "and enter the data phase with lanes aligned to a common multiframe; "
        "for deterministic latency the LMFC must be SYSREF- (Subclass 1) or "
        "SYNC~- (Subclass 2) aligned.")
    f["reset_behavior_compliance"] = (
        "On reset deassertion the Device Clock and (Subclass 1) SYSREF "
        "establish the LMFC phase, the receiver asserts SYNC~, and the link "
        "proceeds CGS -> ILAS -> data, restoring deterministic latency.")
    f["jesd204_distinguishers"] = (
        "JESD204 is identified by ALL of: a serial link specifically between "
        "DATA CONVERTERS (ADC/DAC) and a logic device; the L/M/F/S/N/N'/K "
        "converter-frame parameter set; CGS (/K28.5/ comma) -> ILAS (four "
        "multiframes carrying the link config) -> data bring-up; the Local "
        "MultiFrame Clock / multiframe alignment; Subclass 0/1/2 deterministic "
        "latency via SYSREF or SYNC~; and 8b/10b (204B) or 64b/66b (204C) "
        "line coding. This is distinct from generic SerDes / PCIe / Ethernet "
        "serial links, which carry packets between general logic endpoints "
        "rather than converter samples and have no ILAS / multiframe / "
        "L-M-F-S-K converter framing.")
    _write(p, d)


# ----------------------------------------------------------------------
# L17 — JESD204 channel/signal catalog + dependency graph
# (FORCE-OVERWRITE dependency_graph).
# ----------------------------------------------------------------------
def _l17(gd: Path) -> None:
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["channels"] = [
        {"name": "Serial lanes (L differential pairs)",
         "direction": "unidirectional (converter->logic ADC / "
                      "logic->converter DAC)",
         "purpose": "Carry the line-coded converter-sample payload.",
         "active_levels": "differential CML NRZ, AC-coupled; up to 12.5 Gbps "
         "(204B) / 32 Gbps (204C)",
         "idle_level": "CGS: /K28.5/ commas while SYNC~ asserted"},
        {"name": "Device Clock (DEVCLK)", "direction": "input (both ends)",
         "purpose": "Common master clock; source of frame clock and LMFC.",
         "active_levels": "periodic reference clock", "idle_level": "running"},
        {"name": "SYSREF", "direction": "input (both ends, Subclass 1)",
         "purpose": "Deterministic-latency reference; aligns the LMFC.",
         "active_levels": "single / periodic / gapped-periodic pulse, sampled "
         "by DEVCLK", "idle_level": "low between pulses"},
        {"name": "SYNC~ (active-low)", "direction": "RX -> TX (204B)",
         "purpose": "Synchronization request / error reporting.",
         "active_levels": "asserted = 0 (request CGS)",
         "idle_level": "de-asserted = 1 (synced)"},
        {"name": "Command channel (204C, optional)", "direction": "in-band",
         "purpose": "In-band control/status in the 64b/66b link layer.",
         "active_levels": "embedded in the block stream",
         "idle_level": "idle blocks"},
    ]
    f["logical_signaling_levels"] = [
        {"name": "CGS commas", "meaning": "Continuous /K28.5/ on the lanes "
         "while SYNC~ is asserted."},
        {"name": "ILAS", "meaning": "Four multiframes aligning lanes and "
         "carrying the link config."},
        {"name": "Data", "meaning": "Framed (optionally scrambled) converter "
         "samples with /A//F/ alignment characters."},
    ]
    f["packet_types_summary"] = [
        {"class": "Bring-up phase", "members": ["CGS", "ILAS", "Data"],
         "count": 3},
        {"class": "Control characters",
         "members": ["/K/(K28.5)", "/R/(K28.0)", "/A/(K28.3)", "/Q/(K28.4)",
                     "/F/(K28.7)"], "count": 5},
    ]
    cc = _ensure_dict(f, "channel_counts")
    cc.update({
        "lanes_supported": list(_LANES_SUPPORTED),
        "lanes_max": 32,
        "differential_pairs_per_lane": 1,
        "device_clock_count": 1,
        "sysref_count": 1,
        "sync_n_count": 1,
        "control_character_count": 5,
        "ilas_multiframes": 4,
        "subclass_count": 3,
        "scrambler_taps": "x^14, x^15",
    })
    f["global_signals"] = [
        {"name": "Device Clock", "purpose": "Common clock for the whole "
         "link."},
        {"name": "SYSREF", "purpose": "Subclass 1 LMFC alignment for the "
         "whole link."},
        {"name": "SYNC~", "purpose": "RX->TX synchronization request (204B)."},
    ]
    # FORCE-OVERWRITE the dependency_graph with the JESD204 model.
    f["dependency_graph"] = {
        "common_rule": "All lanes share the Device Clock; the frame clock and "
        "Local MultiFrame Clock (period F*K frames) are derived from it. The "
        "LMFC is aligned to SYSREF (Subclass 1) or SYNC~ (Subclass 2). Lanes "
        "are aligned to a common multiframe boundary during ILAS and "
        "maintained by /A//F/ characters (204B). The link must complete CGS "
        "and ILAS before the data phase.",
        "data_dependency": "Data transmission requires: (1) CGS achieved "
        "(character alignment on /K28.5/ on all lanes), (2) ILAS completed "
        "and FCHK verified, (3) the LMFC aligned for deterministic latency in "
        "Subclass 1/2. The receiver elastic buffer releases aligned data at "
        "the LMFC boundary.",
    }
    f["handshake_pairs"] = [
        {"name": "SYNC~ request", "from": "Receiver", "to": "Transmitter",
         "rule": "RX asserts SYNC~ to request CGS; TX responds with /K28.5/ "
         "commas; RX de-asserts to start ILAS."},
        {"name": "ILAS config exchange", "from": "Transmitter",
         "to": "Receiver", "rule": "TX sends the link-config octets in ILAS "
         "MF2; RX verifies via FCHK."},
        {"name": "SYSREF alignment", "from": "Clock device", "to": "both ends",
         "rule": "SYSREF aligns the LMFC at TX and RX (Subclass 1)."},
        {"name": "Multiframe alignment", "from": "Transmitter",
         "to": "Receiver", "rule": "/A/ at multiframe and /F/ at frame "
         "boundaries maintain alignment (204B)."},
        {"name": "Error resync", "from": "Receiver", "to": "Transmitter",
         "rule": "RX re-asserts SYNC~ on link error to restart CGS (204B)."},
    ]
    f["ordering_rules"] = {
        "bit_order_on_wire": "Line-coded NRZ per lane (8b/10b 204B / 64b/66b "
        "204C); embedded clock recovered by CDR.",
        "sample_order": "Samples ordered by converter / sample position "
        "within the frame, striped across L lanes.",
        "multiframe_order": "Frames grouped into K-frame multiframes; the "
        "multiframe is the lane-alignment unit.",
        "direction": "Unidirectional payload (converter->logic ADC / "
        "logic->converter DAC); SYNC~ is the reverse low-speed control.",
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L18 — JESD204 interconnect topology.
# ----------------------------------------------------------------------
def _l18(gd: Path) -> None:
    p = gd / "L18_INTERCONNECT_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["topology_type"] = (
        "Point-to-point (or point-to-multipoint) serial link between a "
        "Converter Device (M converters) and a Logic Device over L "
        "unidirectional differential lanes. ADC links run converter->logic; "
        "DAC links run logic->converter. A shared Device Clock and "
        "(Subclass 1) SYSREF provide common timing.")
    f["supported_topologies"] = [
        {"name": "Single-lane link", "description": "L=1; one converter "
         "device to one logic device."},
        {"name": "Multi-lane link", "description": "L=2/4/8 (up to 32); lanes "
         "aligned to a common multiframe via ILAS."},
        {"name": "Multiple converters to one logic device",
         "description": "Several converter devices aligned (SYSREF) to one "
         "FPGA/ASIC."},
        {"name": "Multiple links per converter device",
         "description": "One converter device hosting more than one link."},
    ]
    f["master_slave_role_summary"] = [
        {"role": "Converter Device", "description": "Holds the ADC/DAC; "
         "transmitter on an ADC link, receiver on a DAC link."},
        {"role": "Logic Device", "description": "FPGA/ASIC; receiver on an ADC "
         "link, transmitter on a DAC link."},
        {"role": "Clock/SYSREF device", "description": "Provides the common "
         "Device Clock and (Subclass 1) SYSREF."},
        {"role": "Lane", "description": "Unidirectional differential SerDes "
         "pair carrying the line-coded payload."},
    ]
    f["interconnect_role"] = (
        "JESD204 is a converter-to-logic streaming transport: it serializes "
        "converter samples over L lanes with deterministic, repeatable "
        "latency (Subclass 1/2). It is not a packet-routing fabric; the data "
        "is ordered by lane/converter/sample position within the "
        "frame/multiframe.")
    f["ordering_guarantees"] = {
        "sample_order": "Samples are delivered in frame/multiframe order, "
        "striped across L lanes, aligned at the multiframe boundary.",
        "deterministic_latency": "Subclass 1/2 guarantee repeatable "
        "converter-to-logic latency via the SYSREF/SYNC~-aligned LMFC.",
        "lane_alignment": "ILAS aligns all lanes to a common multiframe; "
        "/A//F/ maintain it (204B).",
    }
    f["memory_vs_peripheral_regions"] = (
        "JESD204 is addressless streaming transport; there are no memory or "
        "peripheral address regions. Link parameters are configured via the "
        "vendor control bus (SPI) and the in-band ILAS link-config octets.")
    dc = _ensure_dict(f, "device_classification")
    dc["converter_device"] = "ADC/DAC device (TX for ADC, RX for DAC)."
    dc["logic_device"] = "FPGA/ASIC (RX for ADC, TX for DAC)."
    dc["clock_device"] = "Common Device Clock + SYSREF source (Subclass 1)."
    f["default_signal_values_evidence_tables"] = [
        "JEDEC JESD204B (2011) — subclasses, 8b/10b, CGS/ILAS, SYSREF/SYNC~",
        "JEDEC JESD204C (2017) — 64b/66b, FEC, command channel, 32 Gbps",
        "Link-parameter table (L/M/F/S/N/N'/K/CS/CF/HD)",
        "Control-character table (/K/R/A/Q/F/)",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L19 — JESD204 electrical / lane constraints.
# ----------------------------------------------------------------------
def _l19(gd: Path) -> None:
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["constraints_present"] = True
    f["electrical_channel_constraints"] = {
        "signaling": "differential CML, AC-coupled, NRZ",
        "line_coding": {"jesd204b": "8b/10b", "jesd204c": "64b/66b"},
        "clocking": "embedded clock (CDR) + shared Device Clock + SYSREF "
                    "(Subclass 1)",
        "lanes_supported": list(_LANES_SUPPORTED),
        "lanes_max": 32,
        "max_lane_rate_Gbps_jesd204b": _MAX_LANE_RATE_B_GBPS,
        "max_lane_rate_Gbps_jesd204c": _MAX_LANE_RATE_C_GBPS,
        "speed_grades_jesd204b_Gbps": dict(_SPEED_GRADES_GBPS),
        "k_frames_per_multiframe": {"min": 1, "max": 32},
        "octets_per_multiframe": {"min": 4, "max": 1024, "multiple_of": 4},
        "n_prime_multiple_of": 4,
        "scrambler_polynomial": "1 + x^14 + x^15 (optional)",
        "subclasses": list(_SUBCLASSES),
        "deterministic_latency": "Subclass 1 (SYSREF) / Subclass 2 (SYNC~)",
    }
    f["notes"] = (
        "JESD204 fixes the lane electrical model (differential CML, "
        "AC-coupled, speed grades), the line coding, the framing-parameter "
        "ranges, and the bring-up/alignment timing. It does NOT impose "
        "PDK-specific SDC/floorplan constraints — SerDes PHY characterization "
        "and clock/SYSREF distribution are device/board-integrator concerns.")
    _write(p, d)


# ----------------------------------------------------------------------
# L20 — JESD204 DFT / observability.
# ----------------------------------------------------------------------
def _l20(gd: Path) -> None:
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["dft_present"] = "partial"
    f["in_band_test_facilities"] = [
        {"name": "SYNC~ handshake / error reporting", "purpose": "Controls "
         "CGS and reports link errors (204B); primary in-band control/"
         "observability."},
        {"name": "ILAS link-config + FCHK", "purpose": "In-band link "
         "configuration with a verification checksum."},
        {"name": "8b/10b error monitors", "purpose": "Disparity / "
         "not-in-table / unexpected-control detection and counters (204B)."},
        {"name": "Command channel + CRC/FEC (204C)", "purpose": "In-band "
         "status, integrity, and optional FEC."},
        {"name": "Alignment monitoring (/A//F/)", "purpose": "Continuous "
         "multiframe/frame alignment checking (204B)."},
    ]
    f["internal_diagnostics_observability"] = [
        "Link state (CGS / ILAS / DATA / ERROR).",
        "Per-lane CDR lock and character-alignment status.",
        "Multi-lane skew / elastic-buffer fill.",
        "FCHK checksum result.",
        "8b/10b error counters (204B) / CRC-FEC status (204C).",
        "LMFC phase / SYSREF capture status (Subclass 1).",
    ]
    f["out_of_band_test_facilities"] = [
        "Vendor SerDes PHY bring-up / eye-scan tools (implementation-defined).",
        "Vendor device control bus (SPI) register reads for link status.",
    ]
    f["notes"] = (
        "JESD204's protocol-level DFT surface is the SYNC~ error path, the "
        "ILAS/FCHK, the 8b/10b error monitors (204B) or command-channel/"
        "CRC/FEC (204C), and the /A//F/ alignment monitors. Chip-level JTAG/"
        "scan/BIST remain device-integrator concerns.")
    _write(p, d)


# ----------------------------------------------------------------------
# L21 — JESD204 power/clock intent.
# ----------------------------------------------------------------------
def _l21(gd: Path) -> None:
    p = gd / "L21_POWER_INTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["power_intent_present"] = True
    f["link_power_management_states"] = [
        {"state": "ACTIVE", "name": "Data phase", "description": "Lanes "
         "carrying framed converter samples at the negotiated rate.",
         "exit_latency_estimate": "n/a"},
        {"state": "CGS/ILAS", "name": "Bring-up", "description": "Lanes "
         "carrying commas / ILAS; lower effective payload.",
         "exit_latency_estimate": "bring-up dominated"},
        {"state": "SYNC_REQUESTED", "name": "Re-sync", "description": "SYNC~ "
         "asserted; link re-establishing.",
         "exit_latency_estimate": "CGS+ILAS time"},
    ]
    f["low_power_modes_summary"] = {
        "note": "JESD204 itself does not define link low-power L-states like "
                "PCIe; power management of the SerDes PHY and converter is "
                "device-specific. The standard's energy story is the "
                "pin-count reduction vs parallel LVDS and the coding "
                "efficiency (64b/66b in 204C).",
    }
    f["power_rails"] = [
        {"rail": "VDD (core/PHY)", "purpose": "SerDes and digital logic."},
        {"rail": "VDD_IO / analog", "purpose": "CML lane drivers / receivers "
         "and clock."},
        {"rail": "VSS", "purpose": "Ground."},
    ]
    f["clock_domains"] = [
        "Device Clock (DEVCLK) — frame clock / LMFC source.",
        "Recovered lane bit clock (CDR) per lane.",
        "Frame clock = lane rate / coded bits per octet.",
        "LMFC = frame clock / (F*K).",
    ]
    f["jesd204_power_considerations"] = (
        "JESD204 cuts I/O power and pin count by serializing the converter "
        "interface; JESD204C's 64b/66b coding lowers the coding overhead "
        "(~3% vs 25% for 8b/10b), improving energy per useful bit at high "
        "rates. SerDes PHY power scales with the lane rate.")
    f["notes"] = (
        "Power intent for a JESD204 link is dominated by the SerDes PHY and "
        "is device/implementation-specific; the standard fixes the clocking "
        "(Device Clock, embedded lane clock, LMFC) rather than power states.")
    _write(p, d)


# ----------------------------------------------------------------------
# L22 — JESD204 verification plan.
# ----------------------------------------------------------------------
def _l22(gd: Path) -> None:
    p = gd / "L22_VERIFICATION_PLAN.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["verification_plan_present"] = "implicit"
    f["verification_categories_derived_from_spec"] = [
        "CGS — /K28.5/ comma alignment + SYNC~ handshake on all L lanes.",
        "ILAS — four multiframes, link-config octets, FCHK verification.",
        "Multi-lane alignment to a common multiframe boundary.",
        "Data-phase framing — L/M/F/S/N/N'/K/CS/CF/HD coverage; /A//F/ "
        "alignment.",
        "Scrambling — SCR on/off with 1+x^14+x^15.",
        "8b/10b coding (204B) — disparity / not-in-table / unexpected-control "
        "detection.",
        "64b/66b coding (204C) — sync-header / multiblock alignment, FEC, "
        "command channel.",
        "Subclass 0/1/2 — SYNC~ (S0/S2) and SYSREF (S1) behavior.",
        "Deterministic latency — repeatable across power cycles (S1/S2).",
        "Lane rates — 204B speed grades to 12.5 Gbps; 204C to 32 Gbps.",
        "Error reporting / resync via SYNC~ (204B) or command channel (204C).",
        "Device IDs (DID/BID/LID) and link-config consistency.",
        "ADC vs DAC link direction.",
    ]
    f["notes"] = (
        "JESD204 ships no formal testbench, but the standard implies a "
        "verification plan spanning the PHY (lane eye, CDR), the link layer "
        "(CGS/ILAS/data, 8b/10b or 64b/66b, scrambling, error monitors), "
        "multi-lane alignment, and (Subclass 1/2) deterministic-latency "
        "timing. Interoperability is established by matching the link "
        "parameters (FCHK), subclass, and coding at both ends.")
    _write(p, d)


# ----------------------------------------------------------------------
# L23 — JESD204 integrity / security.
# ----------------------------------------------------------------------
def _l23(gd: Path) -> None:
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["security_requirements_present"] = False
    f["anti_corruption_features"] = [
        "8b/10b disparity and not-in-table error detection (204B).",
        "Unexpected-control-character detection.",
        "ILAS configuration checksum (FCHK).",
        "Multiframe/frame alignment monitoring (/A//F/) and SYNC~ resync "
        "(204B).",
        "JESD204C: CRC and optional Reed-Solomon forward error correction "
        "(FEC) on the payload.",
    ]
    f["anti_tampering_features"] = []
    f["confidentiality_features"] = []
    f["authentication_features"] = []
    f["future_security_pointers"] = [
        "JESD204 is a converter data-path standard; it provides error "
        "detection/correction, not cryptographic confidentiality or "
        "authentication.",
        "System-level security (if required) is layered above the converter "
        "interface by the application, not by JESD204.",
    ]
    f["notes"] = (
        "JESD204's built-in protections are anti-corruption only (8b/10b "
        "error detection + FCHK in 204B; CRC + optional Reed-Solomon FEC in "
        "204C). The lane payload is plaintext converter data; cryptographic "
        "confidentiality / integrity / authentication are NOT part of the "
        "JESD204 data path and are an application/system concern.")
    _write(p, d)


# ======================================================================
# DETECTOR — content-only JESD204 signature with a light SerDes/PCIe MUTEX.
# ======================================================================
def is_jesd204(blob: str) -> bool:
    """JESD204B/C converter-to-logic serial interface — content-only.

    JESD204 is its own data-converter-interface domain. The predicate fires
    on the JESD204 STRUCTURAL signature and applies a light MUTEX so it does
    NOT fire on a generic SerDes / PCIe / Ethernet doc that merely mentions
    "lane" or "8b/10b": it REQUIRES the converter + ILAS/CGS + multiframe +
    converter-frame-parameter vocabulary, none of which a plain
    PCIe/CXL/Ethernet/SerDes spec carries.

    Reads ONLY `blob` (the input_doc-augmented L-doc content blob) — never a
    filename or benchmark-folder name.
    """
    if not blob:
        return False
    low = blob.lower()

    # Explicit standard-name token is the strongest signal.
    named = ("jesd204" in low or "jesd 204" in low)

    # Converter-domain vocabulary (this is the distinguishing domain).
    converter = (
        ("data converter" in low or "data converters" in low)
        or ("converter device" in low and "logic device" in low)
        or ("adc" in low and "dac" in low and "converter" in low)
    )

    # Link-layer bring-up vocabulary unique to JESD204 (8b/10b path).
    ilas = ("ilas" in low or "initial lane alignment" in low)
    cgs = ("code group synchronization" in low or "cgs" in low
           or "k28.5" in low or "/k/" in low)
    multiframe = ("multiframe" in low or "lmfc" in low
                  or "local multiframe clock" in low)

    # Subclass + SYSREF/SYNC~ deterministic-latency vocabulary.
    subclass = "subclass" in low
    sysref_sync = ("sysref" in low or "sync~" in low or "sync_n" in low)

    # The L/M/F/S/K converter-frame parameter vocabulary. Require evidence of
    # the converter-specific framing parameter set (not a generic lane count).
    frame_params = (
        ("octets per frame" in low or "octets/frame" in low)
        or ("samples per converter" in low or "samples/converter" in low)
        or ("frames per multiframe" in low or "frames/multiframe" in low)
        or ("converter resolution" in low and "bits per sample" in low)
        or ("l/m/f/s" in low)
    )

    # Structural core (works even if the name token were absent): converter
    # domain + ILAS + multiframe + the deterministic-latency framework.
    structural = (
        converter
        and ilas
        and multiframe
        and (subclass or sysref_sync)
        and (cgs or frame_params)
    )

    # MUTEX: do NOT fire merely because a generic SerDes/PCIe/Ethernet doc
    # mentions "lane"/"8b/10b". Require the converter-link signature. The
    # named-token path still requires the converter/ILAS/multiframe context so
    # a doc that just cites "JESD204" in passing without the structure does
    # not over-fire.
    named_with_context = named and (converter or (ilas and multiframe))

    return bool(structural or named_with_context)
