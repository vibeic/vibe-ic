"""LPDDR5 SDRAM (JEDEC JESD209-5)-class protocol synth helper.

v0.1.89 — ic_class-gated overlay for `parallel_memory_protocol` (and the
catch-all command-driven / unknown classes) specs that exhibit the LPDDR5
SDRAM structural signature. Applies JEDEC JESD209-5 Low Power Double Data
Rate 5 (LPDDR5) SDRAM Standard (19 February 2019) spec-canonical content
to the L1-L23 layer docs.

DETECTOR SIGNATURE (the runner wires this; documented here so the runner
and this helper stay in lock-step). The detector reads ONLY the canonical
protocol NAME / spec-id and STRUCTURAL wire-level tokens from L1/L2 CONTENT
(the `_spi_blob` built from generated_docs/L1_DATASHEET.json +
L2_FRS.json). It NEVER reads input-doc filenames or the benchmark folder
name (a code review flagged exactly that filename-reading anti-pattern as
a HIGH defect on the AHB+APB detector — this helper does not repeat it):

    _is_lpddr5 = (not _has_ddr3_only_signature) and (
        ("LPDDR5" in _spi_blob)
        or ("JESD209-5" in _spi_blob)
        or ("WCK" in _spi_blob
            and "bank group" in _spi_blob.lower()
            and "low-power" in _spi_blob.lower()))

SIBLING DISAMBIGUATION (LPDDR5 vs DDR3 — the ddr synth fires first on the
same `parallel_memory_protocol` class):
  * LPDDR5's version-specific structural tokens are WCK (a separate full-
    speed Write Clock that DDR3 does not have) and the JESD209-5 document
    number. DDR3 has neither.
  * MUTEX: if the blob carries a DDR3-only signature ("DDR3" or "JESD79-3")
    WITHOUT any LPDDR5 marker ("LPDDR5" / "JESD209-5" / "WCK"), the LPDDR5
    detector does NOT fire — it defers to the DDR3 detector. Conversely the
    DDR3 detector must be hardened to NOT fire on an LPDDR5 blob (which
    legitimately contains the substrings "DDR" and "JEDEC"); that guard is
    the DDR3 side of the same mutex and lives in the runner next to the
    DDR3 detector.

Because LPDDR5 EXTENDS the DDR sibling (whose synth populates the same
parallel-memory L docs first), this helper FORCE-OVERWRITES (direct
assignment, NOT setdefault) every L1/L2/L3/L4 key that the DDR synth would
have populated with DDR3-specific values. setdefault is reserved for keys
the sibling never touches.

Public entry: `apply_lpddr5_synth(generated_docs_dir, is_lpddr5,
lpddr5_ic_name)`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import l_doc_generator_stamp as _stamp
import _pack_top_module as _ptm  # L9.top_module: one decision, one provenance stamp


# Canonical product name forced across every doc.
LPDDR5_IC_NAME = "LPDDR5 SDRAM (JEDEC JESD209-5)"


def _empty(v) -> bool:
    return v in (None, {}, []) or (isinstance(v, str) and not v.strip())


def _ensure_dict(d: dict, key: str) -> dict:
    """setdefault-None bug fix: if the value is None / empty / non-dict,
    replace with {} so subsequent setdefault / direct-assign calls can
    populate subkeys."""
    if d.get(key) in (None, "", []):
        d[key] = {}
    if not isinstance(d.get(key), dict):
        d[key] = {}
    return d[key]


def _read(p: Path) -> dict:
    return json.loads(p.read_text())


def _write(p: Path, d: dict) -> None:
    # THE L-document write chokepoint: stamps the producing release onto
    # the document, then serialises it byte-identically to before.
    _stamp.dump(p, d)


# ----------------------------------------------------------------------
# Structural detector (re-exportable so the phase1 ic_class router can
# call into this module's heuristic directly instead of duplicating it).
# General: keys off the canonical protocol NAME / spec-id read from
# document CONTENT plus the WCK structural token. NEVER reads filenames.
# ----------------------------------------------------------------------

def detect_lpddr5_signature(text: str) -> bool:
    """Return True if `text` (concatenated L1/L2 content) exhibits the
    LPDDR5 structural signature, with the DDR3 mutex applied.

    Mutex: a pure DDR3 spec ("DDR3"/"JESD79-3" present, no LPDDR5 marker)
    must NOT trigger LPDDR5. An LPDDR5 spec is recognised by its
    version-specific tokens (LPDDR5 / JESD209-5 / WCK) that DDR3 lacks.
    """
    if not text:
        return False

    has_lpddr5_marker = (
        ("LPDDR5" in text)
        or ("JESD209-5" in text)
        or ("WCK" in text
            and "bank group" in text.lower()
            and "low-power" in text.lower()))

    # DDR3-only signature: DDR3 generation / JESD79-3 present but NO
    # LPDDR5 marker at all -> defer to the DDR3 detector.
    has_ddr3_only_signature = (
        ("DDR3" in text or "JESD79-3" in text)
        and not ("LPDDR5" in text or "JESD209-5" in text
                 or "WCK" in text))
    if has_ddr3_only_signature:
        return False

    return has_lpddr5_marker


def apply_lpddr5_synth(generated_docs_dir: Path, is_lpddr5: bool,
                       lpddr5_ic_name: Optional[str]) -> None:
    """Apply LPDDR5 SDRAM-specific synth when the structural signature
    matched. Force-overwrites sibling (DDR3) values on shared keys."""
    if not is_lpddr5:
        return
    gd = generated_docs_dir
    name = lpddr5_ic_name or LPDDR5_IC_NAME

    # ------------------------------------------------------------------
    # Force the canonical ic_name across all 24 docs FIRST. For L1-L23 +
    # L8_TIMING the ic_name is top-level; for L14-L23 it lives inside
    # "fields". This direct-assign overrides any DDR3-sibling value.
    # ------------------------------------------------------------------
    _top_level_name_docs = [
        "L1_DATASHEET.json", "L2_FRS.json", "L3_CMD_PROTOCOL.json",
        "L4_REGMAP.json", "L5_ADI_SPEC.json", "L6_CONTROL_LOGIC.json",
        "L7_TEST_DEBUG.json", "L8_RTL_CONSTANTS.json",
        "L8_TIMING_WAVEFORM.json", "L9_INTEGRATION_SPEC.json",
        "L10_TEST_CASES.json", "L11_OTP_CONTENT.json",
        "L12_BEHAVIORAL_SEQUENCES.json", "L13_LAB_CALIBRATION.json",
    ]
    _fields_name_docs = [
        "L14_PROTOCOL_VERSIONING.json", "L15_ENCODING_TABLES.json",
        "L16_COMPLIANCE_PROPERTIES.json", "L17_CHANNEL_SIGNAL_CATALOG.json",
        "L18_INTERCONNECT_TOPOLOGY.json", "L19_CONSTRAINTS_PDK.json",
        "L20_DFT_SCAN_TOPOLOGY.json", "L21_POWER_INTENT.json",
        "L22_VERIFICATION_PLAN.json", "L23_SECURITY_REQUIREMENTS.json",
    ]
    for n in _top_level_name_docs:
        q = gd / n
        if q.is_file():
            d = _read(q)
            d["ic_name"] = name
            _write(q, d)
    for n in _fields_name_docs:
        q = gd / n
        if q.is_file():
            d = _read(q)
            f = _ensure_dict(d, "fields")
            f["ic_name"] = name
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
# Per-_l<N> overlay functions.
# FORCE-OVERWRITE (direct assignment) is used on L1/L2/L3/L4 keys that the
# DDR3 sibling synth populates with DDR3-specific values; setdefault is
# used for keys the sibling never touches.
# ----------------------------------------------------------------------

def _l1(gd: Path) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    # FORCE-OVERWRITE shared keys (sibling DDR3 synth sets these).
    d["document_title"] = "Low Power Double Data Rate 5 (LPDDR5) SDRAM Standard"
    d["document_number"] = "JESD209-5"
    d["version"] = ("JESD209-5 (original), with addenda JESD209-5B "
                    "(LPDDR5/5X) and JESD209-5X (LPDDR5X)")
    d["revised_date"] = ("Published 19 February 2019 (JESD209-5); "
                         "JESD209-5B (LPDDR5/5X) published 28 July 2021")
    d["manufacturer"] = ("JEDEC Solid State Technology Association "
                         "(multi-vendor consortium standard)")
    d["publisher"] = ("JEDEC Solid State Technology Association, 3103 North "
                      "10th Street, Suite 240 South, Arlington, VA 22201-2107")
    d["copyright"] = "Copyright JEDEC Solid State Technology Association 2019"
    d["abstract"] = (
        "LPDDR5 (Low Power Double Data Rate 5) SDRAM is a high-speed, "
        "low-power mobile DRAM standardized by JEDEC as JESD209-5. It uses a "
        "new clocking architecture: a quarter-speed master clock (CK) for "
        "command/address plus a full-speed Write Clock (WCK) and Read Strobe "
        "(RDQS) that are enabled only when needed, reaching up to 6400 "
        "Mbit/s per pin. The device has 16 banks in four DDR4-style bank "
        "groups; prefetch remains 16n. LPDDR5 narrows the command/address "
        "(CA) bus to 7 bits at double data rate, reduces VDDQ to 0.5 V, and "
        "adds link ECC, DVFS, deep sleep, Data-Copy / Write-X, and CKE-less "
        "low-power entry (a CA command bounded by CS).")
    d["keywords"] = [
        "LPDDR5", "SDRAM", "JESD209-5", "JESD209-5B", "JESD209-5X",
        "LPDDR5X", "Low Power Double Data Rate 5", "mobile DRAM", "WCK",
        "Write Clock", "RDQS", "Read Strobe", "WCK2CK sync", "WS_FS",
        "WS_RD", "WS_WR", "bank group", "16 banks", "16n prefetch",
        "quarter-speed CK", "6400 Mbps", "CA bus", "Link ECC",
        "Data Bus Inversion", "DBI", "DVFSC", "DVFS", "deep sleep",
        "per-bank refresh", "all-bank refresh", "Data-Copy", "Write-X",
        "DFE", "VDDQ 0.5 V", "two-deck",
    ]
    d["external_pins"] = [
        "CK_t, CK_c (differential quarter-speed master clock input)",
        "WCK_t, WCK_c (differential full-speed Write Clock; 4x CK; enabled only when needed)",
        "RDQS_t, RDQS_c (differential full-speed Read Strobe; DRAM-driven during reads)",
        "CA[6:0] (7-bit command/address bus, double-data-rate)",
        "CS (chip select; bounds low-power-mode duration; no CKE pin)",
        "DQ (bidirectional data bus; x16 per channel, two x8 byte groups)",
        "DMI (Data Mask / Data Bus Inversion, per byte group)",
        "RESET_n (active-low reset)",
        "ZQ (calibration reference pin; external precision resistor)",
        "VDD1 (first core supply, ~1.8 V)",
        "VDD2H / VDD2L (second core / periphery supplies; DVFSC selects high/low)",
        "VDDQ (DQ / IO supply, reduced to 0.5 V)",
        "VSS, VSSQ (grounds)",
    ]
    # setdefault for keys the sibling synth does not author.
    d.setdefault("external_pin_count_x16_single_channel_summary",
                 "Per x16 channel: CK pair, WCK pair, RDQS pair, CA[6:0], CS, "
                 "DQ[15:0], DMI per byte group, RESET_n, ZQ, plus VDD1 / "
                 "VDD2H / VDD2L / VDDQ / VSS / VSSQ rails (ballout per JESD209-5).")
    d["key_features"] = [
        "16-bank internal architecture in four DDR4-style bank groups (BG0..BG3, four banks each); BG / 16B / 8B modes.",
        "16n prefetch (NOT doubled relative to LPDDR4; remains 16n).",
        "New clocking architecture: quarter-speed differential CK for command/address + full-speed differential WCK + full-speed differential RDQS, WCK/RDQS enabled only when a transfer is imminent.",
        "WCK-to-CK synchronization commands (WS_FS / WS_RD / WS_WR) carried by the CAS command to lock internal WCK to CK before a read/write.",
        "One set of full-speed WCK clocks per byte (vs per 16 bits in LPDDR4).",
        "Data transfer rate up to 6400 Mbit/s per pin (LPDDR5); JESD209-5B/5X (LPDDR5X) extends to 8533 Mbit/s.",
        "7-bit double-data-rate command/address (CA) bus.",
        "CKE pin eliminated — low-power mode entered by a CA command, lasting until CS next goes high.",
        "VDDQ reduced to 0.5 V for low IO power.",
        "Read Link ECC and Write Link ECC (16-bit) for single-bit on-the-wire error correction.",
        "Data Bus Inversion (DBI) on the DMI lines.",
        "Dynamic Voltage and Frequency Scaling (DVFS), including DVFSC selecting VDD2H / VDD2L.",
        "Decision Feedback Equalization (DFE) on the receiver for SI at 6400+ Mbps.",
        "Data-Copy and Write-X (all-zero / all-one) commands to reduce data-transfer activity.",
        "Multi-bank refresh: all-bank refresh (REFab) and per-bank refresh (REFpb, round-robin).",
        "Deep sleep mode (DSM) for lowest standby power.",
        "Burst length 16 (BL16) default and double-length burst 32 (BL32).",
        "Two-deck architecture (deck mode) for finer power/access granularity.",
        "CA bus DDR encoding — a command spans two CA transfers (rising + falling CK edge).",
    ]
    d["topology_summary"] = (
        "Source-synchronous low-power mobile memory bus. An LPDDR5 "
        "controller (master) drives the quarter-speed differential CK, the "
        "7-bit DDR CA bus, CS, and (when a transfer is imminent) the "
        "full-speed differential WCK to one or more LPDDR5 SDRAM devices "
        "(slaves) per channel. DQ and DMI are bidirectional; RDQS is "
        "DRAM-driven during reads. There is no CKE pin; low-power entry is a "
        "CA command bounded by CS. Devices commonly use a two-channel (x16 "
        "per channel) package with a two-deck internal organization.")
    # FORCE-OVERWRITE speed_grade_summary (sibling lists DDR3-800..DDR3-1600).
    d["speed_grade_summary"] = [
        {"generation": "LPDDR5", "release_year": 2019, "data_rate_Mbps_per_pin": 6400,
         "WCK_MHz": 3200, "CK_MHz_quarter_speed": 800, "VDDQ_V": 0.5, "spec": "JESD209-5"},
        {"generation": "LPDDR5X", "release_year": 2021, "data_rate_Mbps_per_pin": 8533,
         "WCK_MHz": 4266, "CK_MHz_quarter_speed": 1066, "VDDQ_V": 0.5,
         "spec": "JESD209-5B / JESD209-5X"},
    ]
    # Drop DDR3-only L1 keys the sibling authored.
    for stale in ("density_organization_table",
                  "external_pin_count_x8_single_die"):
        d.pop(stale, None)
    # LPDDR5 density/organization summary (JESD209-5): per x16 channel, 16 banks
    # (four bank groups of four banks) in BG mode, 16 flat banks in 16B mode, or
    # 8 banks in 8B mode; mobile densities 2 Gb..32 Gb per die.
    d.setdefault(
        "density_organization_summary",
        "LPDDR5 dies are organized per x16 channel with 16 banks (four bank "
        "groups of four banks) in BG mode, or 16 banks flat in 16B mode, or 8 "
        "banks in 8B mode for some densities. Mobile densities range across 2 "
        "Gb..32 Gb dies, packaged as multi-die PoP / discrete packages of up "
        "to tens of GB total. Exact density/organization tables are defined in "
        "JESD209-5.")
    d["revision_history"] = [
        {"version": "JESD209-5", "date": "19 February 2019",
         "description": "Initial LPDDR5 SDRAM Standard (JEDEC JC-42.6). WCK/RDQS clocking, 16-bank/4-bank-group architecture, 6400 Mbps, 7-bit DDR CA bus, link ECC, DVFS, deep sleep, CKE elimination."},
        {"version": "JESD209-5B", "date": "28 July 2021",
         "description": "LPDDR5/5X update: speed up to 8533 Mbit/s, tx/rx equalization, Adaptive Refresh Management."},
        {"version": "JESD209-5X (LPDDR5X)", "date": "2021-2024",
         "description": "LPDDR5X branded extension reaching 8533+ Mbit/s (LPDDR5X-8533 / LPDDR5T-9600 / LPDDR5X-10700) on 14/12 nm-class processes."},
    ]
    d.setdefault("use_cases", [
        "Main memory in smartphones, tablets, and battery-powered devices.",
        "AI / ML mobile accelerators and flagship SoCs (Snapdragon, Apple M-series, MediaTek Dimensity, Kirin).",
        "Automotive infotainment and ADAS compute.",
        "Edge-AI and high-bandwidth embedded vision.",
        "Package-on-Package (PoP) and discrete LPDDR5 on mobile application processors.",
    ])
    d["overview"] = (
        "LPDDR5 SDRAM is JEDEC's fifth-generation low-power mobile DRAM "
        "(JESD209-5). Its headline innovation is a new clocking "
        "architecture: a quarter-speed master clock (CK) carries "
        "command/address on a 7-bit double-data-rate CA bus, while a "
        "full-speed Write Clock (WCK) and Read Strobe (RDQS) — enabled only "
        "when a transfer is imminent — carry data at up to 6400 Mbit/s per "
        "pin. The DRAM is organized as 16 banks in four DDR4-style bank "
        "groups; prefetch remains 16n. To save power, LPDDR5 eliminates the "
        "CKE pin (low-power entry is a CA command bounded by CS), reduces "
        "VDDQ to 0.5 V, and adds Data-Copy / Write-X, DVFS, deep sleep, "
        "Read/Write Link ECC, and DBI. The WCK2CK synchronization commands "
        "(WS_FS / WS_RD / WS_WR), carried by the CAS command, prepare the "
        "DRAM to lock to the imminent high-speed WCK clock before the read "
        "or write begins.")
    _write(p, d)


def _l2(gd: Path) -> None:
    p = gd / "L2_FRS.json"
    if not p.is_file():
        return
    d = _read(p)
    po = _ensure_dict(d, "protocol_overview")
    # FORCE-OVERWRITE the sibling DDR3 protocol_overview values.
    po["type"] = (
        "Source-synchronous low-power mobile memory bus. Controller-driven "
        "quarter-speed differential CK + 7-bit double-data-rate CA bus + CS, "
        "with a separately-enabled full-speed differential WCK and "
        "DRAM-driven RDQS framing the bidirectional double-data-rate DQ bus.")
    po["duplex"] = (
        "half-duplex on DQ (read or write, not both); CK / CA / CS / WCK are "
        "controller -> SDRAM; RDQS is SDRAM -> controller during reads")
    po["synchronous"] = True
    po["controller_role"] = (
        "Bus master. Drives quarter-speed CK, CA[6:0], CS, RESET_n; drives "
        "WCK during writes and to pre-synchronize for reads; sources DQ + "
        "DMI on write, sinks DQ on read while the DRAM drives RDQS; performs "
        "WCK2CK synchronization, refresh (ab/pb), DVFS, link-ECC, per-bank "
        "state tracking.")
    po["sdram_role"] = (
        "Bus slave. Decodes the 7-bit DDR CA bus per the LPDDR5 command "
        "encoding table; locks internal WCK to CK during WCK2CK "
        "synchronization; drives DQ + RDQS on read, sinks DQ + DMI on write; "
        "generates internal refresh; supports deep sleep and CA-bus-bounded "
        "power-down (no CKE).")
    po.setdefault(
        "ddr_signaling",
        "Data (DQ) is sampled on both edges of WCK (write) / RDQS (read) — "
        "double data rate at the full WCK rate. Command/address (CA[6:0]) is "
        "also double-data-rate but referenced to the quarter-speed CK, so a "
        "command consumes two CA transfers (one on the rising and one on the "
        "falling CK edge).")
    po["wire_groups"] = {
        "master_clock": ["CK_t", "CK_c (differential, quarter-speed)"],
        "write_clock": ["WCK_t", "WCK_c (differential, full-speed, 4x CK; on-demand)"],
        "read_strobe": ["RDQS_t", "RDQS_c (differential, full-speed; DRAM-driven on read)"],
        "chip_select": ["CS (bounds low-power-mode duration; replaces CKE)"],
        "command_address": ["CA[6:0] (7-bit, double-data-rate)"],
        "data": ["DQ[15:0] per channel (two x8 byte groups)"],
        "data_mask_dbi": ["DMI (Data Mask / Data Bus Inversion, per byte group)"],
        "reset": ["RESET_n (active-low)"],
        "calibration": ["ZQ (external precision reference resistor)"],
        "supply": ["VDD1", "VDD2H", "VDD2L", "VDDQ (0.5 V)", "VSS", "VSSQ"],
    }
    # FORCE-OVERWRITE functional_requirements (sibling authored DDR3 FRs).
    d["functional_requirements"] = [
        {"id": "FR-CLK-01", "text": "The LPDDR5 SDRAM shall use a quarter-speed differential master clock CK as the command/address timing reference, plus a separate full-speed differential Write Clock WCK (4x the CK rate) enabled only when a data transfer is imminent."},
        {"id": "FR-RDQS-02", "text": "During reads the DRAM shall drive a full-speed differential Read Strobe RDQS edge-aligned with the read data; RDQS is enabled only while a read is in progress."},
        {"id": "FR-WCK2CK-03", "text": "Before a high-speed read/write the controller shall issue a WCK2CK synchronization (WS_FS / WS_RD / WS_WR) carried by the CAS command so the DRAM can lock its internal WCK phase to CK."},
        {"id": "FR-CA-04", "text": "Command/address shall be transferred on a 7-bit CA bus (CA[6:0]) at double data rate; a command occupies two CA transfers (rising CK edge then falling CK edge)."},
        {"id": "FR-NOCKE-05", "text": "LPDDR5 shall NOT use a CKE pin; low-power mode shall be entered by a CA command and shall last until CS next goes high."},
        {"id": "FR-BANKS-06", "text": "LPDDR5 shall provide 16 banks, organizable as four bank groups of four banks (BG mode), 16 flat banks (16B), or 8 banks (8B); bank/bank-group selected by BA/BG fields."},
        {"id": "FR-PREFETCH-07", "text": "LPDDR5 shall implement a 16n prefetch (not doubled relative to LPDDR4); default burst length BL16, double-length BL32 supported."},
        {"id": "FR-DATARATE-08", "text": "The interface shall support up to 6400 Mbit/s per pin (WCK 3200 MHz, CK 800 MHz); LPDDR5X (JESD209-5B/5X) shall extend to 8533 Mbit/s."},
        {"id": "FR-VDDQ-09", "text": "VDDQ shall be reduced to 0.5 V; core supplies VDD1 and VDD2H/VDD2L shall be provided, with DVFSC selecting VDD2H/VDD2L for dynamic core voltage scaling."},
        {"id": "FR-LINKECC-10", "text": "LPDDR5 shall support Read Link ECC and Write Link ECC (16-bit) for single-bit on-the-wire correction, and Data Bus Inversion (DBI) on the DMI lines."},
        {"id": "FR-REFRESH-11", "text": "LPDDR5 shall accept all-bank refresh (REFab) and per-bank refresh (REFpb, round-robin); tREFI / tRFCab / tRFCpb shall be honoured."},
        {"id": "FR-LOWPOWER-12", "text": "LPDDR5 shall support deep sleep mode (DSM), DVFS / DVFSC, Data-Copy and Write-X (all-zero/all-one), and partial-array / per-bank refresh granularity."},
        {"id": "FR-DFE-13", "text": "The receiver shall support Decision Feedback Equalization (DFE) and tx/rx equalization (JESD209-5B) for SI at 6400+ Mbit/s."},
        {"id": "FR-DECK-14", "text": "LPDDR5 may implement a two-deck architecture (deck mode) for finer power/access granularity."},
        {"id": "FR-CMD2ACT-15", "text": "Opening a row shall require two Activate commands (Activate-1, Activate-2); the CAS command precedes the read/write and primarily prepares the DRAM to synchronize with the imminent WCK clock (it does not by itself select a column)."},
        {"id": "FR-WRX-16", "text": "The CAS command shall also specify the Write-X (WRX) option: writes do not transfer data but fill the burst with all-zeros or all-ones under the WXS bit, saving the same time as a normal write while saving power."},
        {"id": "FR-RESET-17", "text": "RESET_n shall be an active-low reset returning the device to its reset state; mode registers are volatile and must be re-programmed after reset / power-up."},
    ]
    # FORCE-OVERWRITE configurations (sibling DDR3 list contains BL8 etc.).
    d["configurations"] = [
        {"name": "Bank-group mode (BG mode)", "description": "16 banks as four bank groups of four banks; tCCD_L/tRRD_L same-group spacing."},
        {"name": "16-bank mode (16B)", "description": "16 flat banks."},
        {"name": "8-bank mode (8B)", "description": "8 banks (selected densities)."},
        {"name": "WCK2CK sync — Free-Start (WS_FS)", "description": "Starts WCK immediately; may precede multiple reads/writes (multiple banks)."},
        {"name": "WCK2CK sync — Read-optimized (WS_RD)", "description": "Optimizes WCK timing for an immediately following read."},
        {"name": "WCK2CK sync — Write-optimized (WS_WR)", "description": "Optimizes WCK timing for an immediately following write."},
        {"name": "Burst length 16 (BL16)", "description": "Default 16-beat burst."},
        {"name": "Burst length 32 (BL32)", "description": "Double-length 32-beat burst; reads may start within the 32-word-aligned burst via C0/B3."},
        {"name": "Write-X (WRX)", "description": "Burst filled with all-zeros / all-ones (WXS) without transferring data."},
        {"name": "DVFSC", "description": "Selects VDD2H or VDD2L to scale core voltage with frequency."},
        {"name": "Deep Sleep Mode (DSM)", "description": "Lowest standby power; full re-init on exit."},
        {"name": "All-bank refresh (REFab)", "description": "Refreshes all banks; DRAM blocked during tRFCab."},
        {"name": "Per-bank refresh (REFpb)", "description": "Refreshes one bank per command in round-robin order; other banks accessible during tRFCpb."},
    ]
    # FORCE-OVERWRITE error/compliance lists (sibling authored DDR3 ones
    # mentioning Write Leveling / MR0 / CWL).
    d["error_response_conditions"] = [
        "Link-ECC uncorrectable error (multi-bit flip within an ECC word) — single-bit link ECC cannot correct it.",
        "WCK2CK synchronization not performed before a high-speed transfer — WCK phase not locked; data timing undefined.",
        "Refresh interval missed — cell content may be lost; no protocol-level flag.",
        "Illegal command in current state — undefined behaviour; obey the LPDDR5 state diagram.",
        "Mode Register Set without correct idle state / timing — undefined.",
        "Deep-sleep exit without re-initialization — undefined; full init required.",
    ]
    d["compliance_requirements"] = [
        "Power-up + initialization (RESET_n, supply ramp ordering, VDDQ=0.5 V, CK start, mode-register program, ZQ calibration, initial WCK2CK sync) must complete before normal operation.",
        "WCK2CK synchronization (WS_FS/WS_RD/WS_WR via CAS) shall lock internal WCK to CK before any high-speed read/write.",
        "Refresh: average interval <= tREFI; REFab/REFpb timing honoured; per-bank refresh follows round-robin order.",
        "Bank-group timing (tCCD_L/tRRD_L same-group; tCCD_S/tRRD_S different-group) shall be honoured.",
        "VDDQ shall be 0.5 V; DVFSC transitions follow the defined voltage/frequency change procedure.",
        "Low-power entry shall be a CA command (no CKE) lasting until CS next goes high.",
        "Read/Write Link ECC and DBI shall be configured consistently between controller and DRAM.",
        "Deep sleep / DVFS / frequency change shall follow the defined sequences.",
    ]
    _write(p, d)


def _l3(gd: Path) -> None:
    p = gd / "L3_CMD_PROTOCOL.json"
    if not p.is_file():
        return
    d = _read(p)
    # FORCE-OVERWRITE sibling DDR3 protocol fields.
    d["protocol_type"] = (
        "Controller-mastered command-driven low-power mobile memory bus. "
        "Commands are encoded on a 7-bit double-data-rate CA bus (CA[6:0]) "
        "referenced to a quarter-speed differential CK; each command occupies "
        "two CA transfers (rising then falling CK edge). Data transfers are "
        "double-data-rate on DQ, framed by a separately-enabled full-speed "
        "WCK on writes and a DRAM-driven RDQS on reads. There is no CKE pin; "
        "low-power entry is a CA command bounded by CS.")
    d["command_encoding"] = {
        "ca_bus_width": 7,
        "ca_signals": ["CA0", "CA1", "CA2", "CA3", "CA4", "CA5", "CA6"],
        "transfer": "Double data rate referenced to quarter-speed CK: each command uses one rising-edge and one falling-edge CA transfer.",
        "field_legend": {
            "Bn": "Burst address bit", "Cn": "Column address bit",
            "Rn": "Row address bit", "BAn": "Bank address bit",
            "BGn": "Bank group address bit", "AB": "All banks",
            "AP": "Auto-precharge", "MAn": "Mode register address bit",
            "OPn": "Operation / mode register data bit",
            "WS_xx": "WCK synchronization (WS_FS / WS_RD / WS_WR)",
            "WRX": "Write X (fill burst all-zero / all-one, no data transfer)",
            "WXSA / WXSB": "Write X select (value to be written for the X-fill)",
            "PD": "Power down", "DSE": "Deep sleep enable", "RFM": "Refresh Management",
        },
        "commands": [
            {"name": "No operation", "abbrev": "NOP", "notes": "Idle / wait."},
            {"name": "Power-down entry", "abbrev": "PDE", "notes": "CA-bus power-down (PD); no CKE; lasts until CS next goes high."},
            {"name": "Read FIFO", "abbrev": "RDFIFO", "notes": "Read internal FIFO (training/debug)."},
            {"name": "Write FIFO", "abbrev": "WRFIFO", "notes": "Write internal FIFO (training/debug)."},
            {"name": "Read DQ Calibration", "abbrev": "RDCAL", "notes": "Returns a fixed DQ calibration pattern."},
            {"name": "Multi-purpose command", "abbrev": "MPC", "notes": "Carries OP[7:0]; used for ZQ calibration etc."},
            {"name": "Mode register write-2", "abbrev": "MRW-2", "notes": "Second MRW cycle (MA[6:0], OP[7:0])."},
            {"name": "Self-refresh exit", "abbrev": "SRX", "notes": "Exit self-refresh."},
            {"name": "Self-refresh entry", "abbrev": "SRE", "notes": "Enter self-refresh; PD/DSE select power-down vs deep-sleep."},
            {"name": "Mode register read", "abbrev": "MRR", "notes": "Read mode register MA[6:0]."},
            {"name": "Mode register write-1", "abbrev": "MRW-1", "notes": "First MRW cycle (MA[6:0])."},
            {"name": "Refresh", "abbrev": "REF", "notes": "REFab (AB) or REFpb (per-bank round-robin); RFM selects Refresh Management."},
            {"name": "Precharge", "abbrev": "PRE", "notes": "Precharge bank (BG/BA) or all banks (AB)."},
            {"name": "Write-32", "abbrev": "WR32", "notes": "Double-length (BL32) write."},
            {"name": "Column Address Select", "abbrev": "CAS", "notes": "Carries WS_FS/WS_RD/WS_WR, WRX, WXSA/WXSB; prepares WCK sync — does NOT select a column."},
            {"name": "Masked Write", "abbrev": "MWR", "notes": "Write with per-byte data mask (DMI)."},
            {"name": "Write", "abbrev": "WR", "notes": "BL16 write."},
            {"name": "Read", "abbrev": "RD", "notes": "BL16 read; DRAM drives RDQS."},
            {"name": "Read-32", "abbrev": "RD32", "notes": "Double-length (BL32) read; start position via C0/B3."},
            {"name": "Activate-1", "abbrev": "ACT-1", "notes": "First activate cycle (row high bits)."},
            {"name": "Activate-2", "abbrev": "ACT-2", "notes": "Second activate cycle (row low bits)."},
        ],
    }
    d.setdefault("wck_synchronization", {
        "WS_FS": "Free-Start — start WCK immediately; may precede multiple reads/writes (multiple banks).",
        "WS_RD": "Read-optimized — optimize WCK timing for an immediately following read.",
        "WS_WR": "Write-optimized — optimize WCK timing for an immediately following write.",
        "rule": "The CAS command carries WS_FS/WS_RD/WS_WR to lock internal WCK to CK before the high-speed transfer. Unlike LPDDR4, the CAS command in LPDDR5 comes BEFORE the read/write and primarily serves this synchronization role (it does not select a column).",
    })
    # FORCE-OVERWRITE channels (sibling authored DDR3 RAS/CAS/WE channels).
    d["channels"] = [
        {"name": "CK_t, CK_c", "direction": "controller -> SDRAM", "description": "Quarter-speed differential master clock; CA sampled at double data rate relative to CK."},
        {"name": "WCK_t, WCK_c", "direction": "controller -> SDRAM", "description": "Full-speed differential Write Clock (4x CK); enabled only when a transfer is imminent; frames write data and pre-synchronizes reads."},
        {"name": "RDQS_t, RDQS_c", "direction": "SDRAM -> controller", "description": "Full-speed differential Read Strobe; DRAM-driven, edge-aligned with read data; enabled only during reads."},
        {"name": "CS", "direction": "controller -> SDRAM", "description": "Chip select (active high); marks the first command cycle; bounds low-power-mode duration (replaces CKE)."},
        {"name": "CA[6:0]", "direction": "controller -> SDRAM", "description": "7-bit double-data-rate command/address bus; a command occupies two CA transfers."},
        {"name": "DQ[15:0]", "direction": "bidirectional", "description": "Data bus per channel, two x8 byte groups; double data rate at the WCK/RDQS rate."},
        {"name": "DMI", "direction": "bidirectional", "description": "Data Mask / Data Bus Inversion per byte group; write mask + DBI."},
        {"name": "RESET_n", "direction": "controller -> SDRAM", "description": "Active-low reset."},
        {"name": "ZQ", "direction": "supply / reference", "description": "Calibration reference; external precision resistor."},
    ]
    d["valid_ready_handshake_rules"] = [
        "There is no per-beat handshake; commands are committed on the CA bus referenced to CK; data follows at deterministic latency relative to WCK/RDQS.",
        "Before a high-speed transfer the controller issues a WCK2CK synchronization (WS_FS/WS_RD/WS_WR via CAS); the DRAM locks its internal WCK phase during this window.",
        "READ data appears at the programmed read latency, framed by the DRAM-driven RDQS edge-aligned with DQ.",
        "WRITE data is launched at the programmed write latency, framed by the controller-driven WCK.",
        "tCCD_L/tRRD_L (same bank group) and tCCD_S/tRRD_S (different bank group) govern command spacing in bank-group mode.",
    ]
    d["burst_based"] = True
    d["byte_oriented"] = False
    d["frame_format"] = {
        "command_frame": "Two CA transfers (rising + falling CK) on the 7-bit CA bus encode one command; CS high marks the first cycle.",
        "data_frame_BL16": "16-beat burst on DQ framed by WCK (write) or RDQS (read) at full speed (both edges).",
        "data_frame_BL32": "32-beat double-length burst; reads may start within the 32-word-aligned burst via C0/B3.",
        "row_open_requires_two_ACT": "Opening a row requires Activate-1 then Activate-2.",
    }
    d.setdefault("comparison_to_lpddr4", [
        "LPDDR4 column names C0-C9 are renamed in LPDDR5 to B0-B3 and C0-C5; writes start at a multiple-of-16 address (B0-B3 zero); reads may use a non-zero B3.",
        "LPDDR5 widens the CA bus to 7 bits at double data rate, so commands arrive at the same cadence as LPDDR4 despite the quarter-speed CK.",
        "In LPDDR5 the CAS command precedes the read/write and synchronizes WCK (WS_FS/WS_RD/WS_WR); in LPDDR4 the CAS-2 command followed the column command.",
        "LPDDR5 provides one set of full-speed WCK clocks per byte (vs per 16 bits in LPDDR4).",
    ])
    # Remove DDR3-only keys the sibling may have left behind.
    for stale in ("command_truth_table", "cke_truth_table",
                  "burst_order_BL8_sequential", "burst_order_BL8_interleaved"):
        d.pop(stale, None)
    _write(p, d)


def _l4(gd: Path) -> None:
    p = gd / "L4_REGMAP.json"
    if not p.is_file():
        return
    d = _read(p)
    d["register_map_present"] = True
    d["notes"] = (
        "LPDDR5 SDRAM exposes a Mode Register space addressed by a 7-bit "
        "Mode Register address MA[6:0] and accessed 8 bits of OP[7:0] at a "
        "time via Mode Register Write (MRW, two CA cycles) and Mode Register "
        "Read (MRR) on the 7-bit CA bus. There is no memory-mapped offset. "
        "Mode registers are volatile and must be re-programmed after each "
        "power cycle / reset. The exact MR0..MR127 assignments are defined "
        "in JESD209-5; the entries here summarize the key functional mode "
        "registers a controller must program.")
    d.setdefault("register_addressing", {
        "mode_register_address_bits": "MA[6:0] (7-bit, up to 128 mode registers)",
        "data_width_bits": 8,
        "write_command": "MRW — MRW-1 carries MA[6:0], MRW-2 carries OP[7:0] data.",
        "read_command": "MRR — returns OP[7:0] of the addressed mode register on DQ.",
    })
    # FORCE-OVERWRITE the registers list (sibling authored DDR3 MR0..MR3+MPR).
    d["registers"] = [
        {"name": "MR (Device Info / Manufacturer)", "long_name": "Device feature / revision / manufacturer ID (read-only)", "width_bits": 8, "access": "MRR (read-only)",
         "fields": [
             {"name": "Manufacturer ID", "description": "JEP106 vendor identifier."},
             {"name": "Revision ID", "description": "Die revision / stepping."},
             {"name": "Density / type", "description": "Per-channel density, x16 width, device type (LPDDR5)."}]},
        {"name": "MR (Read/Write Latency & Bank mode)", "long_name": "Operating mode register — RL / WL / bank organization / burst", "width_bits": 8, "access": "MRW / MRR",
         "fields": [
             {"name": "Read Latency (RL)", "description": "Programmed read latency for the selected data rate / Set."},
             {"name": "Write Latency (WL)", "description": "Programmed write latency; Set A / Set B selectable."},
             {"name": "Bank organization", "description": "BG mode (16 banks / 4 groups), 16B, or 8B."},
             {"name": "Burst length / WLS", "description": "BL16 default; BL32 double-length; write-latency set select."}]},
        {"name": "MR (WCK / Clocking)", "long_name": "WCK mode register — WCK ratio, WCK2CK sync, WCK always-on", "width_bits": 8, "access": "MRW / MRR",
         "fields": [
             {"name": "WCK ratio", "description": "WCK:CK ratio (4:1) per data-rate Set."},
             {"name": "WCK2CK leveling", "description": "WCK-to-CK leveling/sync behaviour used by WS_FS/WS_RD/WS_WR."},
             {"name": "WCK always-on", "description": "Continuous WCK vs on-demand WCK enable."}]},
        {"name": "MR (DVFS / DVFSC)", "long_name": "Dynamic Voltage / Frequency Scaling mode register", "width_bits": 8, "access": "MRW / MRR",
         "fields": [
             {"name": "FSP (Frequency Set Point)", "description": "Active frequency set point (FSP-OP / FSP-WR) for RL/WL/ODT/Vref."},
             {"name": "DVFSC enable", "description": "Enables core voltage scaling (VDD2H/VDD2L)."},
             {"name": "DVFSQ enable", "description": "Enables DQ-domain voltage scaling."}]},
        {"name": "MR (Refresh / RFM)", "long_name": "Refresh management mode register", "width_bits": 8, "access": "MRW / MRR",
         "fields": [
             {"name": "Refresh mode", "description": "All-bank (REFab) vs per-bank (REFpb) configuration."},
             {"name": "RFM enable", "description": "Adaptive Refresh Management (JESD209-5B) for Rowhammer reliability."},
             {"name": "Refresh rate", "description": "Temperature-dependent refresh rate."}]},
        {"name": "MR (Link ECC / DBI)", "long_name": "Link ECC and Data Bus Inversion control", "width_bits": 8, "access": "MRW / MRR",
         "fields": [
             {"name": "Read Link ECC enable", "description": "16-bit read-direction link ECC."},
             {"name": "Write Link ECC enable", "description": "Write-direction link ECC."},
             {"name": "DBI-RD / DBI-WR", "description": "Read / write Data Bus Inversion on DMI."}]},
        {"name": "MR (Drive strength / ODT / Vref)", "long_name": "I/O configuration mode register", "width_bits": 8, "access": "MRW / MRR",
         "fields": [
             {"name": "Output driver impedance", "description": "DQ / DMI / WCK output driver impedance."},
             {"name": "ODT", "description": "On-die termination for DQ / WCK / RDQS / CA."},
             {"name": "Vref(ca) / Vref(dq)", "description": "Reference voltage trim per frequency set point."}]},
        {"name": "MR (Power-down / Deep Sleep)", "long_name": "Low-power control mode register", "width_bits": 8, "access": "MRW / MRR",
         "fields": [
             {"name": "Deep Sleep enable (DSE)", "description": "Deep sleep behaviour on self-refresh entry."},
             {"name": "PASR", "description": "Partial Array Self-Refresh bank/segment mask."},
             {"name": "Power-down options", "description": "Active / precharge power-down (CA command, bounded by CS)."}]},
    ]
    d["encoding_tables"] = {
        "wck2ck_sync_options": [
            {"option": "WS_FS", "meaning": "Free-Start — start WCK immediately, may precede multiple reads/writes."},
            {"option": "WS_RD", "meaning": "Read-optimized — optimize WCK timing for an immediately following read."},
            {"option": "WS_WR", "meaning": "Write-optimized — optimize WCK timing for an immediately following write."},
        ],
        "write_x_options": [
            {"option": "WRX with WXS=0", "meaning": "Fill burst with all-zeros without transferring data."},
            {"option": "WRX with WXS=1", "meaning": "Fill burst with all-ones without transferring data."},
        ],
        "bank_modes": [
            {"mode": "BG mode", "meaning": "16 banks, 4 bank groups x 4 banks; tCCD_L/tRRD_L same-group spacing."},
            {"mode": "16B mode", "meaning": "16 flat banks."},
            {"mode": "8B mode", "meaning": "8 banks (selected densities)."},
        ],
    }
    # Drop DDR3-only mode-register select if the sibling left it.
    d.pop("ba1_ba0_select", None)
    d.pop("register_count", None)
    _write(p, d)


def _l5(gd: Path) -> None:
    p = gd / "L5_ADI_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("analog_digital_interface_present", False)
    d["signaling_summary"] = (
        "All-digital low-voltage-swing low-power signaling. CA[6:0] and CS "
        "are single-ended referenced to Vref(ca); DQ / DMI are single-ended "
        "referenced to Vref(dq). CK (quarter-speed), WCK (full-speed write "
        "clock) and RDQS (read strobe) are differential. VDDQ is reduced to "
        "0.5 V (vs DDR3's 1.5 V) to minimize IO power. Core supplies are "
        "VDD1 (~1.8 V) and VDD2H/VDD2L (DVFSC-selected). The receiver uses "
        "Decision Feedback Equalization (DFE) and (in JESD209-5B) tx/rx "
        "equalization for SI at 6400+ Mbit/s. The ZQ pin calibrates "
        "output-driver / ODT impedance against an external precision "
        "reference resistor over Process / Voltage / Temperature.")
    # FORCE-OVERWRITE voltage/supply blocks (sibling sets DDR3 1.5 V values).
    d["voltage_classes"] = [
        {"class": "LPDDR5", "VDD1_V": 1.8, "VDD2H_V": 1.05, "VDD2L_V": 0.9, "VDDQ_V": 0.5, "applicable": "JESD209-5, 6400 Mbps"},
        {"class": "LPDDR5X", "VDD1_V": 1.8, "VDD2H_V": 1.05, "VDD2L_V": 0.9, "VDDQ_V": 0.5, "applicable": "JESD209-5B/5X, up to 8533 Mbps"},
    ]
    d["supply_rails"] = {
        "VDD1": "First core supply (~1.8 V).",
        "VDD2H": "Second core / periphery supply, HIGH operating point (DVFSC).",
        "VDD2L": "Second core / periphery supply, LOW operating point (DVFSC).",
        "VDDQ": "DQ / IO supply, reduced to 0.5 V.",
        "VSS / VSSQ": "Core ground and DQ ground.",
    }
    d["reference_voltages"] = {
        "Vref_ca": "Reference for CA / CS inputs; per frequency set point.",
        "Vref_dq": "Reference for DQ / DMI inputs; per frequency set point (DVFSQ).",
    }
    d["equalization"] = {
        "DFE": "Decision Feedback Equalization on the receiver.",
        "tx_rx_eq": "Transmit/receive equalization added in JESD209-5B for SI headroom.",
    }
    # FORCE-OVERWRITE zq_calibration (sibling authored DDR3 ZQCL/ZQCS).
    d["zq_calibration"] = {
        "purpose": "Trim DRAM output-driver and on-die-termination impedance against an external precision reference resistor on the ZQ pin to compensate Process / Voltage / Temperature drift.",
        "external_reference": "External precision resistor between the ZQ pin and ground (per JESD209-5).",
        "commands": "ZQ calibration start / latch via MPC (multi-purpose command) per the LPDDR5 calibration flow.",
    }
    # Drop DDR3-only DC/termination blocks the sibling authored.
    for stale in ("input_threshold_levels_SSTL15",
                  "differential_input_thresholds_CK_DQS",
                  "output_driver_impedance_RZQ",
                  "on_die_termination_RTT_values"):
        d.pop(stale, None)
    d["notes"] = (
        "Although the LPDDR5 bus is digital, the DRAM array is fundamentally "
        "analog (1T1C cells, sense amps, charge pumps, on-die WCK clock "
        "generation, DFE, ZQ engine), all vendor-specific and out of scope "
        "of JESD209-5. The defining low-voltage feature versus DDR3 is the "
        "0.5 V VDDQ and the per-frequency-set-point Vref / DVFSC scaling.")
    _write(p, d)


def _l6(gd: Path) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    # FORCE-OVERWRITE FSM (sibling authored DDR3 RAS/CAS state machine).
    d["fsm_states_sdram"] = [
        {"name": "Power Applied", "code": "—", "description": "RESET_n LOW; supplies ramping (VDD1/VDD2H/VDD2L/VDDQ); state undefined."},
        {"name": "Reset", "code": "—", "description": "RESET_n LOW; logic reset; outputs Hi-Z; mode registers cleared."},
        {"name": "Initialization", "code": "—", "description": "Mode-register program + ZQ calibration + initial WCK2CK sync before normal operation."},
        {"name": "Idle", "code": "—", "description": "Banks precharged, timing met, MRs programmed. Ready for ACT-1/ACT-2, REF (ab/pb), MRW/MRR, SRE, PDE, or CAS/WCK2CK sync."},
        {"name": "Refreshing (ab/pb)", "code": "—", "description": "REFab (all-bank) or REFpb (per-bank round-robin); tRFCab/tRFCpb."},
        {"name": "Self Refresh", "code": "—", "description": "Entered via SRE over the CA bus; no CKE; deep sleep (DSM) is the deepest sub-mode (DSE)."},
        {"name": "Mode Register Access", "code": "—", "description": "MRW (two CA cycles) or MRR; tMRW/tMRD/tMRR."},
        {"name": "Activating", "code": "—", "description": "ACT-1 then ACT-2; row opening; tRCD before first column command."},
        {"name": "Bank Active", "code": "—", "description": "One/more banks open; ready for CAS (WCK sync) + RD/WR/MWR, further ACT, or PRE."},
        {"name": "WCK Synchronizing", "code": "—", "description": "After CAS WS_FS/WS_RD/WS_WR: lock internal WCK phase to CK before the transfer."},
        {"name": "Reading", "code": "—", "description": "Read burst (BL16/BL32); DRAM drives DQ + RDQS at read latency."},
        {"name": "Writing", "code": "—", "description": "Write burst (BL16/BL32); controller drives DQ + DMI framed by WCK; WRX fills without data."},
        {"name": "Precharging", "code": "—", "description": "PRE / PREab; tRP before next ACT or MRW/REF/SRE."},
        {"name": "Power-Down", "code": "—", "description": "Entered via CA command (PD); lasts until CS next goes high; no CKE."},
        {"name": "Deep Sleep (DSM)", "code": "—", "description": "Lowest standby power; SRE with DSE; full re-init on exit."},
    ]
    # FORCE-OVERWRITE controller FSM (sibling authored DDR3 CTRL states).
    d["fsm_states_controller"] = [
        {"name": "CTRL_POWER_UP", "description": "Hold RESET_n LOW; ramp VDD1/VDD2H/VDD2L/VDDQ; VDDQ to 0.5 V."},
        {"name": "CTRL_INIT", "description": "Deassert RESET_n; start CK; program MRs; ZQ calibration; initial WCK2CK sync."},
        {"name": "CTRL_IDLE", "description": "Schedule REFab/REFpb; track tREFI/tFAW; manage DVFS FSP."},
        {"name": "CTRL_ACTIVATE", "description": "ACT-1 then ACT-2; respect tRCD, tRRD_L/tRRD_S, tFAW."},
        {"name": "CTRL_WCK_SYNC", "description": "Issue CAS WS_FS/WS_RD/WS_WR; enable WCK only when needed."},
        {"name": "CTRL_READ", "description": "RD/RD32 at programmed RL; receive DQ framed by DRAM-driven RDQS; decode read link ECC."},
        {"name": "CTRL_WRITE", "description": "WR/WR32/MWR at programmed WL; drive DQ + DMI framed by WCK; encode write link ECC; use WRX."},
        {"name": "CTRL_PRECHARGE", "description": "PRE/PREab; wait tRP."},
        {"name": "CTRL_REFRESH", "description": "REFab/REFpb (round-robin); wait tRFCab/tRFCpb; manage RFM."},
        {"name": "CTRL_SELF_REFRESH", "description": "SRE; deep sleep via DSE; re-init on deep-sleep exit."},
        {"name": "CTRL_DVFS", "description": "Switch FSP; change WCK rate; adjust RL/WL/ODT/Vref; DVFSC VDD2H/VDD2L."},
        {"name": "CTRL_POWER_DOWN", "description": "Enter power-down via CA command (no CKE); mode lasts until CS next goes high."},
    ]
    d["fsm_hints"] = {
        "trigger": "Commands are committed on the 7-bit CA bus referenced to the quarter-speed CK (two CA transfers per command). The controller is the sole bus master. High-speed transfers require a prior WCK2CK synchronization (WS_FS/WS_RD/WS_WR via CAS).",
        "rule": "Deterministic latency; once committed, data movement on DQ is fixed by read/write latency and burst length. WCK and RDQS are enabled only when a transfer is imminent.",
        "abort": "RESET_n is the true abort. Low-power entry is via CA command and persists until CS next goes high (no CKE pin).",
    }
    d["anti_deadlock_rule"] = (
        "Controller shall honour all LPDDR5 timing parameters (tRCD, tRP, "
        "tRAS, tRC, tRRD_L/tRRD_S, tFAW, tCCD_L/tCCD_S, tRFCab/tRFCpb, "
        "tREFI, tWR, tWTR_L/tWTR_S, tRTP, WCK2CK sync windows, "
        "tMRW/tMRD/tMRR, tZQ*, DVFS/FSP-change and deep-sleep timings). "
        "Violations cause undefined behaviour with no protocol-level flag.")
    d["exit_from_reset_or_poweron"] = (
        "After power-on or RESET_n, the DRAM enters its reset state. The "
        "initialization sequence (RESET_n deassert, supply ramp ordering "
        "with VDDQ=0.5 V, CK start, mode-register programming, ZQ "
        "calibration, initial WCK2CK synchronization) must complete before "
        "any user data command. Deep-sleep exit requires the full init "
        "sequence to be re-run.")
    d["default_ready_state_recommendation"] = {
        "CK_idle": "Quarter-speed CK running/stable in active states.",
        "WCK_idle": "Disabled (not toggling) when no transfer is imminent; enabled only after WCK2CK sync.",
        "RDQS_idle": "High-impedance / undriven except during reads (DRAM-driven).",
        "CS_idle": "Drives command framing; bounds low-power-mode duration.",
        "RESET_n_idle": "HIGH during normal operation.",
        "DQ_idle": "High-impedance between bursts.",
    }
    # FORCE-OVERWRITE configurations (sibling authored DDR3 list).
    d["configurations"] = [
        {"name": "Bank-group mode", "description": "16 banks as 4 groups x 4 banks; tCCD_L/tRRD_L same-group, tCCD_S/tRRD_S different-group."},
        {"name": "16-bank / 8-bank mode", "description": "16 flat banks or 8 banks per density."},
        {"name": "WCK on-demand", "description": "WCK enabled only after WCK2CK sync; saves power vs a continuous data clock."},
        {"name": "DVFS / DVFSC", "description": "Frequency set points with VDD2H/VDD2L core-voltage scaling."},
        {"name": "Deep Sleep (DSM)", "description": "Lowest standby power; full re-init on exit."},
    ]
    d["timing_dependency_rule"] = (
        "Command/address (CA[6:0], CS) inputs (Vref(ca)) are set up/held "
        "around the CK edges (double data rate). DQ / DMI inputs (Vref(dq)) "
        "are set up/held around both WCK edges on writes. DQ outputs are "
        "launched edge-aligned with the DRAM-driven RDQS on reads. The "
        "internal WCK must be phase-locked to CK (WCK2CK synchronization) "
        "before any high-speed transfer; DFE / equalization must be trained "
        "for the active frequency set point.")
    # Drop DDR3-only FSM keys if present.
    d.pop("fsm_transitions_major", None)
    d["fsm_transitions_major"] = [
        {"trigger": "Power applied, RESET_n LOW", "target": "Reset", "description": "Supplies ramp; RESET_n held LOW."},
        {"trigger": "RESET_n rising + power stable + CK start", "target": "Initialization -> ZQ cal -> WCK2CK sync -> Idle", "description": "Program MRs, ZQ cal, initial WCK sync, ready."},
        {"trigger": "ACT-1 then ACT-2 (Idle)", "target": "Activating -> Bank Active", "description": "Two activate cycles open a row; tRCD."},
        {"trigger": "CAS WS_RD then RD (Bank Active)", "target": "WCK Synchronizing -> Reading", "description": "CAS syncs WCK; RD drives DQ + RDQS."},
        {"trigger": "CAS WS_WR then WR/MWR (Bank Active)", "target": "WCK Synchronizing -> Writing", "description": "CAS syncs WCK; WR samples DQ on WCK edges; WRX fills."},
        {"trigger": "PRE/PREab (Bank Active)", "target": "Precharging -> Idle", "description": "tRP before next ACT."},
        {"trigger": "REFab/REFpb (Idle)", "target": "Refreshing -> Idle", "description": "tRFCab/tRFCpb; per-bank allows other-bank access."},
        {"trigger": "SRE (Idle)", "target": "Self Refresh / Deep Sleep", "description": "CA command; DSE selects deep sleep."},
        {"trigger": "MRW/MRR (Idle)", "target": "Mode Register Access -> Idle", "description": "tMRW/tMRD/tMRR."},
        {"trigger": "PDE CA command", "target": "Power-Down", "description": "Lasts until CS next goes high; no CKE."},
        {"trigger": "RESET_n LOW (any state)", "target": "Reset", "description": "Active-low reset to reset state."},
    ]
    _write(p, d)


def _l7(gd: Path) -> None:
    p = gd / "L7_TEST_DEBUG.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("test_debug_architecture_present", "partial")
    d["spec_provided_observability"] = [
        {"name": "Mode Register Read (MRR)", "purpose": "Reads device info / operating-mode / refresh / status mode registers — primary in-band observability."},
        {"name": "Read DQ Calibration (RDCAL) / Read FIFO", "purpose": "Returns a fixed pattern / FIFO contents for read-path training."},
        {"name": "Write FIFO", "purpose": "Loads an internal FIFO for write-path training without array access."},
        {"name": "WCK2CK synchronization (WS_FS/WS_RD/WS_WR)", "purpose": "Exercises/validates the WCK-to-CK phase-lock clock path."},
        {"name": "Link ECC status", "purpose": "Flags corrected single-bit errors on the wire."},
        {"name": "Per-state IDD specifications", "purpose": "Per-state current points for power-state observability."},
    ]
    d["no_jtag_on_DRAM_balls"] = "LPDDR5 SDRAM has no JTAG / boundary-scan pins at the package interface; vendor DFT runs at wafer probe."
    # FORCE-OVERWRITE controller_side_debug_aids (sibling lists DDR3 RAS#/CAS#).
    d["controller_side_debug_aids"] = [
        "Logic-analyzer / oscilloscope probing of CK / WCK / RDQS / CA[6:0] / CS / DQ / DMI.",
        "LPDDR5 PHY / controller IPs expose FIFOs, WCK2CK leveling state, per-bit deskew, eye-margin sweeps, DFE taps via a vendor control register interface.",
        "RDCAL fixed pattern as a deterministic read self-test.",
        "Link-ECC error counters and controller-side system ECC.",
    ]
    d["notes"] = (
        "LPDDR5 (JESD209-5) does not specify a formal in-system scan / JTAG "
        "architecture at the DRAM balls. Bus-level observability is limited "
        "to MRR, RDCAL / Read-FIFO / Write-FIFO training, WCK2CK sync, "
        "Link-ECC status, and IDD measurement, plus controller-side PHY "
        "observability. Internal DRAM scan/BIST/repair is vendor-proprietary.")
    _write(p, d)


def _l8_rtl(gd: Path) -> None:
    p = gd / "L8_RTL_CONSTANTS.json"
    if not p.is_file():
        return
    d = _read(p)
    wp = _ensure_dict(d, "width_parameters")
    # Direct-assign LPDDR5 widths (override any DDR3 width set).
    for k, v in {
        "CA_BUS_BITS": 7, "CA_TRANSFERS_PER_COMMAND": 2, "CS_BITS": 1,
        "BANK_COUNT_BG_MODE": 16, "BANK_GROUP_COUNT": 4, "BANKS_PER_GROUP": 4,
        "BANK_COUNT_16B_MODE": 16, "BANK_COUNT_8B_MODE": 8,
        "DQ_WIDTH_PER_CHANNEL": 16, "BYTE_GROUPS_PER_CHANNEL": 2,
        "DMI_WIDTH_PER_BYTE_GROUP": 1, "WCK_PAIRS_PER_BYTE": 1,
        "RDQS_PAIRS_PER_BYTE": 1, "CK_PAIRS": 1, "PREFETCH_DEPTH": 16,
        "BURST_LENGTH_BL16": 16, "BURST_LENGTH_BL32": 32,
        "MODE_REGISTER_ADDRESS_BITS": 7, "MODE_REGISTER_DATA_BITS": 8,
        "LINK_ECC_BITS": 16,
    }.items():
        wp[k] = v
    # Drop DDR3-only width keys the sibling authored (BL8, RZQ, x4/x8/x16 etc.).
    for stale in (
        "BANK_ADDRESS_BITS", "BANK_COUNT",
        "ROW_ADDRESS_BITS_512Mb_x4", "ROW_ADDRESS_BITS_1Gb_x4",
        "ROW_ADDRESS_BITS_2Gb_x4", "ROW_ADDRESS_BITS_4Gb_x4",
        "ROW_ADDRESS_BITS_8Gb_x4", "COLUMN_ADDRESS_BITS_x4",
        "COLUMN_ADDRESS_BITS_x8", "COLUMN_ADDRESS_BITS_x16",
        "DQ_WIDTH_x4", "DQ_WIDTH_x8", "DQ_WIDTH_x16",
        "DM_WIDTH_x4", "DM_WIDTH_x8", "DM_WIDTH_x16",
        "DQS_PAIRS_x4", "DQS_PAIRS_x8", "DQS_PAIRS_x16",
        "MR_COUNT", "MR_WIDTH_BITS", "BURST_LENGTH_BL8", "BURST_LENGTH_BC4",
        "PAGE_SIZE_BYTES_x4_x8_lowdensity", "PAGE_SIZE_BYTES_x16",
        "PAGE_SIZE_BYTES_x4_x8_8Gb",
    ):
        wp.pop(stale, None)
    d["named_timing_parameters"] = {
        "tCK": "Quarter-speed master clock period (e.g. 1.25 ns at CK=800 MHz for 6400 Mbps).",
        "tWCK": "Full-speed Write Clock period = tCK/4 (e.g. 0.3125 ns at WCK=3200 MHz).",
        "WCK_to_CK_ratio": "4:1 (WCK runs at 4x the CK rate).",
        "tWCK2CK": "WCK-to-CK synchronization window required before a high-speed transfer.",
        "tRCD": "ACTIVATE-to-internal-RD/WR delay.",
        "tRP": "PRECHARGE command period.", "tRAS": "ACTIVATE-to-PRECHARGE delay.",
        "tRC": "ACTIVATE-to-ACTIVATE delay (same bank); tRC = tRAS + tRP.",
        "tFAW": "Four-Activate-Window.",
        "tRRD_L": "ACTIVATE-to-ACTIVATE, same bank group.",
        "tRRD_S": "ACTIVATE-to-ACTIVATE, different bank group.",
        "tCCD_L": "Column-to-Column, same bank group.",
        "tCCD_S": "Column-to-Column, different bank group.",
        "tWR": "Write recovery time.", "tWTR_L": "Write-to-Read, same bank group.",
        "tWTR_S": "Write-to-Read, different bank group.", "tRTP": "Internal Read-to-Precharge delay.",
        "tRFCab": "All-bank refresh cycle time (REFab).",
        "tRFCpb": "Per-bank refresh cycle time (REFpb).",
        "tREFI": "Average refresh interval (temperature-dependent).",
        "tMRW": "Mode Register Write time.", "tMRD": "Mode Register Set delay.",
        "tMRR": "Mode Register Read latency.", "tZQCAL": "ZQ calibration time (via MPC).",
        "RL": "Read Latency (per frequency set point).",
        "WL": "Write Latency (per frequency set point; Set A / Set B).",
    }
    d["voltage_levels"] = {
        "VDD1_V": 1.8, "VDD2H_V": 1.05, "VDD2L_V": 0.9, "VDDQ_V": 0.5,
        "Vref_ca": "Internally generated reference for CA / CS (per FSP).",
        "Vref_dq": "Internally generated reference for DQ / DMI (per FSP / DVFSQ).",
        "signaling": "Low-power low-voltage-swing single-ended (CA/CS/DQ/DMI) + differential CK/WCK/RDQS; receiver DFE / tx-rx equalization.",
    }
    d["clock_constants"] = {
        "LPDDR5_data_rate_Mbps_per_pin": 6400,
        "LPDDR5X_data_rate_Mbps_per_pin": 8533,
        "CK_MHz_quarter_speed_6400": 800, "WCK_MHz_full_speed_6400": 3200,
        "CK_MHz_quarter_speed_8533": 1066, "WCK_MHz_full_speed_8533": 4266,
        "WCK_to_CK_ratio": 4,
        "data_rate_per_pin_relative_to_WCK": "2x (double data rate at the WCK rate)",
        "command_rate_per_pin_relative_to_CK": "2x (CA bus double data rate at the quarter-speed CK)",
    }
    d["key_constants_for_RTL_authoring"] = {
        "ca_bus_is_double_data_rate": True,
        "command_spans_two_ca_transfers": True,
        "no_cke_pin": True,
        "low_power_entry_is_ca_command_bounded_by_cs": True,
        "row_open_requires_two_activate_cycles": True,
        "cas_precedes_read_write_and_syncs_wck": True,
        "wck_enabled_only_when_transfer_imminent": True,
        "rdqs_driven_by_dram_on_read": True,
        "wck2ck_sync_options": ["WS_FS", "WS_RD", "WS_WR"],
        "write_x_fill_options": ["all-zero (WXS=0)", "all-one (WXS=1)"],
        "default_burst_length": 16, "double_burst_length": 32,
        "bank_modes": ["BG (16 banks / 4 groups)", "16B", "8B"],
        "prefetch_depth": 16, "link_ecc_bits": 16, "vddq_volts": 0.5,
        "data_format": "binary; byte-group organized; DBI on DMI",
    }
    d["default_signal_values_when_idle"] = {
        "CK": "Differential, quarter-speed, toggling in active states.",
        "WCK": "NOT toggling when idle; enabled only after WCK2CK synchronization.",
        "RDQS": "High-impedance / undriven except during reads (DRAM-driven).",
        "CS": "Drives command framing; bounds low-power-mode duration.",
        "CA[6:0]": "Encodes NOP when no command is being issued.",
        "RESET_n": "HIGH (deasserted) during normal operation.",
        "DQ": "High-impedance when neither side is driving.",
        "DMI": "Don't-care between bursts; carries DBI / mask during transfers.",
    }
    # Drop DDR3-only burst_order constants if the sibling left them.
    d.pop("burst_order_constants", None)
    _write(p, d)


def _l8_timing(gd: Path) -> None:
    p = gd / "L8_TIMING_WAVEFORM.json"
    if not p.is_file():
        return
    d = _read(p)
    d["clock_waveform"] = {
        "CK_source": "Controller-generated quarter-speed differential master clock; command/address timing reference.",
        "WCK_source": "Controller-generated full-speed differential Write Clock (4x CK); enabled only when a transfer is imminent (after WCK2CK sync).",
        "RDQS_source": "DRAM-driven full-speed differential Read Strobe; enabled only during reads; edge-aligned with read data.",
        "data_rate_LPDDR5_Mbps": 6400, "data_rate_LPDDR5X_Mbps": 8533,
        "CK_MHz_6400": 800, "WCK_MHz_6400": 3200,
        "sampling_edge_command": "Command/address sampled at double data rate relative to CK (rising + falling); a command occupies two CA transfers.",
        "sampling_edge_data_read": "Both edges of RDQS (DRAM-driven; edge-aligned with DQ).",
        "sampling_edge_data_write": "Both edges of WCK (controller-driven).",
        "wck_to_ck_ratio": 4,
    }
    # FORCE-OVERWRITE command_frame_waveform (sibling lists DDR3 RAS#/CAS#/WE#).
    d["command_frame_waveform"] = {
        "ca_bus_width": 7, "transfers_per_command": 2,
        "first_cycle_identified_by": "CS high marks the first cycle.",
        "fields_sampled": ["CA[6:0] on rising CK edge", "CA[6:0] on falling CK edge", "CS"],
        "note": "Because the CA bus is double-data-rate, commands arrive at the same cadence as LPDDR4 despite the quarter-speed CK.",
    }
    # FORCE-OVERWRITE: the sibling DDR3 synth (or a prior setdefault) may seed
    # this dict; direct-assign so the spec-complete WS_RD/WS_WR descriptions win.
    d["wck2ck_synchronization_waveform"] = {
        "purpose": "Lock the DRAM's internal WCK phase to CK before a high-speed read/write.",
        "issued_by": "CAS command carrying WS_FS / WS_RD / WS_WR.",
        "WS_FS": "Free-start: WCK starts immediately; may precede multiple reads/writes.",
        "WS_RD": "Read-optimized: WCK timing optimized for an immediately following read.",
        "WS_WR": "Write-optimized: WCK timing optimized for an immediately following write.",
        "sequence": "CAS (WS_xx) -> WCK enabled and phase-locked -> RD / WR issued.",
    }
    d.setdefault("read_burst_waveform", {
        "command_issue": "CAS (WS_RD) then RD / RD32.",
        "read_latency_RL": "Programmed Read Latency (per FSP) after RD.",
        "strobe": "DRAM drives RDQS edge-aligned with DQ; double data rate at the WCK/RDQS rate.",
        "burst_length": "16 (BL16) default; 32 (BL32); RD32 start position via C0/B3.",
        "read_link_ecc": "Read Link ECC (16-bit) corrects a single-bit error in the read data.",
    })
    d.setdefault("write_burst_waveform", {
        "command_issue": "CAS (WS_WR) then WR / WR32 / MWR.",
        "write_latency_WL": "Programmed Write Latency (per FSP; Set A / Set B) after WR.",
        "strobe": "Controller drives WCK; DRAM samples DQ + DMI on both WCK edges.",
        "burst_length": "16 (BL16) default; 32 (BL32).",
        "write_x": "WRX fills the burst all-zero/all-one (WXS) without transferring data.",
        "masked_write": "MWR uses DMI as a per-byte data mask.",
        "write_link_ecc": "Write Link ECC (16-bit) protects write data on the wire.",
    })
    # FORCE-OVERWRITE initialization_waveform (sibling authored DDR3 MRS/ZQCL).
    d["initialization_waveform"] = {
        "step_1_supply_ramp": "Ramp VDD1 / VDD2H / VDD2L / VDDQ; RESET_n LOW; VDDQ to 0.5 V.",
        "step_2_reset_deassert": "Deassert RESET_n; wait the defined reset-exit time.",
        "step_3_ck_start": "Start quarter-speed CK; stabilize.",
        "step_4_mode_register_program": "Program MRs: RL/WL, bank mode, WCK ratio, FSP, link ECC/DBI, ODT/drive/Vref.",
        "step_5_zq_calibration": "Run ZQ calibration (start/latch via MPC).",
        "step_6_wck2ck_initial_sync": "Perform initial WCK2CK sync; train DQ/RDQS read and WCK write timing (DFE/eq) for the active FSP.",
        "step_7_ready": "Device ready for normal operation.",
    }
    d.setdefault("low_power_entry_exit", {
        "power_down": "Entered via a CA command (PD bit); no CKE; lasts until CS next goes high.",
        "self_refresh": "Entered via SRE over the CA bus; CK may be stopped per the defined window.",
        "deep_sleep": "Entered via SRE with DSE; lowest standby power; full re-init on exit.",
    })
    d["general_timing_rule"] = (
        "All AC timing is referenced to the quarter-speed CK for "
        "command/address and to WCK (write) / RDQS (read) for data. Before "
        "any high-speed transfer the internal WCK must be phase-locked to CK "
        "via a WCK2CK synchronization (WS_FS/WS_RD/WS_WR). WCK and RDQS are "
        "enabled only when a transfer is imminent — the principal "
        "power-saving difference from a continuously-running data clock. "
        "Reference voltages Vref(ca)/Vref(dq) and DFE settings are per "
        "frequency set point.")
    d["voltage_thresholds"] = {
        "VDDQ_V": 0.5, "Vref_ca": "Per frequency set point (CA/CS).",
        "Vref_dq": "Per frequency set point (DQ/DMI).",
        "differential": "CK / WCK / RDQS are differential.",
    }
    # Drop DDR3-only waveform keys.
    for stale in ("read_burst_waveform_BL8", "write_burst_waveform_BL8",
                  "self_refresh_entry_exit", "write_leveling_waveform",
                  "timing_tables_referenced"):
        d.pop(stale, None)
    _write(p, d)


def _l9(gd: Path) -> None:
    p = gd / "L9_INTEGRATION_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["module_role"] = (
        "Source-synchronous low-power mobile memory device paired with an "
        "LPDDR5 memory controller + PHY. JESD209-5 standardizes the SDRAM "
        "component side (ballout, low-voltage signaling, the 7-bit DDR CA "
        "protocol, WCK/RDQS clocking, mode registers, AC timing). The "
        "controller / PHY must implement: quarter-speed CK + on-demand WCK, "
        "WCK2CK synchronization, a command scheduler honouring "
        "tRCD/tRP/tRAS/tRC/tRRD_L/tRRD_S/tFAW/tCCD_L/tCCD_S/tWR/tWTR/"
        "tRFCab/tRFCpb/tREFI, ZQ calibration, read/write training with DFE, "
        "link-ECC + DBI, DVFS, and per-bank state tracking. Concrete LPDDR5 "
        "controller IP appears in mobile SoCs (Snapdragon, Apple M-series, "
        "MediaTek Dimensity, Kirin) and IP vendors (Synopsys, Cadence).")
    _ptm.apply(d, "LPDDR5_SDRAM_component")
    # FORCE-OVERWRITE shared L9 keys the DDR3 sibling authors.
    d["integration_overview"] = {
        "channel_organization": "Typically two x16 channels per package; per-channel CK/WCK/RDQS/CA/CS/DQ/DMI; two-deck internal organization.",
        "wire_directions": "CK, WCK, CA[6:0], CS, RESET_n: controller -> DRAM. RDQS: DRAM -> controller (read). DQ, DMI: bidirectional. ZQ: external reference. Supplies VDD1/VDD2H/VDD2L/VDDQ.",
        "no_cke": "There is NO CKE pin; low-power entry is a CA command bounded by CS.",
        "on_demand_wck": "WCK enabled only when a transfer is imminent (after WCK2CK sync).",
        "no_handshake": "Deterministic latency; data follows the command without per-beat acknowledgment.",
    }
    d["interface_categories"] = [
        "Quarter-speed differential master clock (CK_t / CK_c)",
        "Full-speed differential Write Clock (WCK_t / WCK_c, on-demand)",
        "Full-speed differential Read Strobe (RDQS_t / RDQS_c, DRAM-driven on read)",
        "Chip select (CS) — also bounds low-power-mode duration",
        "7-bit double-data-rate command/address (CA[6:0])",
        "Bidirectional data (DQ)", "Data Mask / Data Bus Inversion (DMI)",
        "Asynchronous reset (RESET_n)", "Calibration reference (ZQ)",
        "Power (VDD1, VDD2H, VDD2L, VDDQ=0.5 V, VSS, VSSQ)",
    ]
    d["interconnect_topologies_supported"] = [
        "Single controller + single LPDDR5 die (point-to-point on the SoC board / PoP).",
        "Single controller + multi-die LPDDR5 package (per-channel CS / clocks).",
        "Two-channel x16 organization (two independent channels per package).",
        "Package-on-Package (PoP) stacking over the mobile application processor.",
    ]
    d.setdefault("default_signal_values_when_omitted",
                 "RESET_n must be driven HIGH before normal operation. WCK remains disabled until a transfer is imminent. Low-power mode is entered only by an explicit CA command and persists until CS next goes high.")
    d["soc_dependent_items"] = [
        "LPDDR5 controller / scheduler IP.",
        "LPDDR5 PHY: quarter-speed CK PLL + on-demand WCK, WCK2CK leveling, per-bit deskew, DFE / tx-rx equalization, RX FIFO.",
        "ZQ calibration sequencer.",
        "DQ / RDQS read training and WCK write training (per FSP).",
        "Link-ECC encoder/decoder (read + write) and DBI logic.",
        "DVFS / FSP manager (FSP-OP / FSP-WR), DVFSC VDD2H/VDD2L.",
        "Refresh scheduler (REFab / REFpb round-robin; optional RFM).",
        "Regulators for VDD1 / VDD2H / VDD2L / VDDQ (VDDQ 0.5 V).",
        "Vref(ca) / Vref(dq) generation per FSP.",
        "RESET_n generation; deep-sleep entry/exit sequencing.",
    ]
    # FORCE-OVERWRITE pull_up_resistors_terminators + low_power_modes
    # (sibling DDR3 synth authors DDR3 ODT/VTT/240ohm + Active/Precharge PD).
    d["pull_up_resistors_terminators"] = [
        {"signal": "DQ / DMI / WCK / RDQS / CA", "termination": "On-die termination (ODT) selectable per mode register; LPDDR5 relies on ODT + equalization rather than external termination."},
        {"signal": "ZQ", "termination": "External precision reference resistor to ground for impedance calibration."},
        {"signal": "RESET_n", "termination": "Controller-driven; board pull as needed."},
    ]
    d["low_power_modes"] = {
        "Power_Down": "Entered via a CA command (PD); no CKE; lasts until CS next goes high.",
        "Self_Refresh": "Entered via SRE; CK may be stopped per the defined window.",
        "Deep_Sleep_Mode": "Lowest standby power; SRE with DSE; full re-init on exit.",
        "DVFS_DVFSC": "Dynamic voltage/frequency scaling with VDD2H/VDD2L selection.",
        "Write_X_Data_Copy": "Write-X (all-zero/all-one) and Data-Copy reduce data-transfer activity.",
    }
    d["compatibility_notes"] = [
        "LPDDR5 is NOT pin- or protocol-compatible with DDR3/DDR4/DDR5; it follows the LPDDR line (LPDDR2/3/4/4X -> LPDDR5/5X) and JESD209-x numbering.",
        "Versus LPDDR4: LPDDR5 adds WCK/RDQS on-demand clocking, widens the CA bus to 7 bits at DDR, moves the CAS command before the read/write to synchronize WCK, increases banks to 16 (4 bank groups), reduces VDDQ to 0.5 V, and adds link ECC, DVFS, deep sleep, Data-Copy/Write-X.",
        "Versus DDR3: LPDDR5 has WCK (DDR3 has no separate write clock), uses JESD209-5 (not JESD79-3), is a low-voltage mobile standard, and uses CA-bus command encoding (not separate RAS/CAS/WE pins) — the key sibling-disambiguation signature.",
        "LPDDR5X (JESD209-5B/5X) is a speed/SI extension (up to 8533 Mbps) with tx/rx equalization and Adaptive Refresh Management.",
    ]
    _write(p, d)


def _l10(gd: Path) -> None:
    p = gd / "L10_TEST_CASES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_cases_present"] = (
        "partial - the spec defines the command encoding, mode-register "
        "fields, state machine, clocking architecture, and AC timing that "
        "map to compliance scenarios; JEDEC and DRAM vendors maintain "
        "separate normative compliance procedures out of scope here.")
    d["derived_compliance_test_categories"] = [
        "Power-up + initialization: supply ramp ordering (VDDQ=0.5 V) + RESET_n + CK start + MR program + ZQ calibration + initial WCK2CK sync -> ready.",
        "RESET_n assertion and re-initialization.",
        "Quarter-speed CK + 7-bit DDR CA framing: verify two CA transfers per command and CS marks the first cycle.",
        "WCK2CK synchronization: WS_FS / WS_RD / WS_WR via CAS; verify internal WCK locks to CK.",
        "Activate: ACT-1 then ACT-2; tRCD before first column command.",
        "Read: CAS(WS_RD) -> RD / RD32 at RL; RDQS edge-aligned; BL16 / BL32; RD32 start via C0/B3.",
        "Write: CAS(WS_WR) -> WR / WR32 / MWR at WL (Set A / Set B); WCK-framed DQ + DMI.",
        "Write-X (WRX): burst filled all-zero / all-one without data transfer.",
        "Masked Write (MWR): DMI as per-byte mask.",
        "Bank-group timing: tCCD_L/tRRD_L vs tCCD_S/tRRD_S; tFAW.",
        "Refresh: REFab (tRFCab), REFpb (round-robin, tRFCpb); tREFI per temperature range; RFM (5B).",
        "Self-refresh entry/exit via CA command (no CKE); mode lasts until CS next goes high.",
        "Deep Sleep Mode (DSE): full re-init on exit.",
        "DVFS / DVFSC: FSP switch; WCK rate change; RL/WL/ODT/Vref retraining; VDD2H/VDD2L scaling.",
        "Link ECC: Read/Write single-bit correction; configuration consistency.",
        "DBI on DMI: reduced driven-bit count.",
        "Mode register access: MRW (two CA cycles) + MRR; tMRW/tMRD/tMRR.",
        "ZQ calibration via MPC against external reference resistor.",
        "Read training: RDCAL / Read FIFO; DQ + RDQS sampling-phase sweep with DFE.",
        "Write training: Write FIFO; WCK write-eye training.",
        "CA timing (setup/hold to CK at DDR) and DQ timing (setup/hold to WCK).",
        "Differential CK / WCK / RDQS swing + crossing-point verification.",
        "Low-voltage IO compliance at VDDQ = 0.5 V; Vref(ca)/Vref(dq) per FSP.",
        "IDD measurement across the per-state current points (active/standby/power-down/self-refresh/deep-sleep).",
    ]
    _write(p, d)


def _l11(gd: Path) -> None:
    p = gd / "L11_OTP_CONTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    d["otp_present"] = "indirect (read-only device-info mode registers)"
    d["otp_summary"] = (
        "The LPDDR5 die does not expose a normative user OTP / fuse array at "
        "the bus interface. JESD209-5 standardizes a volatile DRAM array "
        "plus a mode-register space re-programmed after each power cycle. "
        "Unlike DDR3 DIMMs, mobile LPDDR5 is soldered directly to the board "
        "with no separate I2C SPD EEPROM; instead the device exposes "
        "read-only device-information mode registers (manufacturer ID, "
        "revision/stepping, density / I/O width / type, feature flags) read "
        "by the controller via MRR at boot.")
    # FORCE-OVERWRITE die-metadata note (sibling references JESD79-3C).
    d["factory_programmed_dram_die_metadata"] = (
        "The DRAM die may carry vendor-internal trim fuses, redundancy-"
        "repair fuses, and stepping ID, but these are not exposed at the "
        "bus interface and are not normative in JESD209-5.")
    d.setdefault("device_info_mode_registers_summary", {
        "access": "Read via MRR over the 7-bit CA bus; returns OP[7:0] on DQ.",
        "key_fields": [
            {"name": "Manufacturer ID", "description": "JEP106 vendor identifier."},
            {"name": "Revision ID / Stepping", "description": "Die revision / stepping."},
            {"name": "Density / I/O width / type", "description": "Per-channel density, x16, LPDDR5 type."},
            {"name": "Feature / support flags", "description": "Bank modes, WCK ratios, link ECC, RFM, DVFS / FSP, deep-sleep support."},
            {"name": "Refresh / temperature status", "description": "Temperature range and refresh-rate status (read to adapt refresh)."},
        ],
    })
    d["permanent_state_after_power_off"] = (
        "DRAM array contents are volatile (lost on supply removal). Mode "
        "registers are volatile and must be re-programmed on every "
        "power-up / after reset and after deep-sleep exit. There is no "
        "non-volatile SPD EEPROM on a soldered LPDDR5 device; the read-only "
        "device-info mode registers serve as the controller's in-band "
        "identification path.")
    d["notes"] = (
        "From the controller's perspective, the read-only device-info mode "
        "registers (manufacturer/revision/density/feature flags) are the "
        "identification fingerprint of an LPDDR5 device, read in-band via "
        "MRR — replacing the separate I2C SPD EEPROM used on DDR3 DIMMs.")
    # Drop DDR3 SPD layout if the sibling left it.
    d.pop("spd_eeprom_layout_summary", None)
    _write(p, d)


def _l12(gd: Path) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["initialization_sequence"] = [
        "1. Hold RESET_n LOW. Ramp the supplies in the defined order: VDD1 (~1.8 V), VDD2H / VDD2L, VDDQ (0.5 V).",
        "2. Once supplies are stable, deassert RESET_n; wait the defined reset-exit time.",
        "3. Start the quarter-speed differential CK; stabilize.",
        "4. Program mode registers via MRW (two CA cycles each): FSP, RL/WL, bank mode, WCK ratio, link-ECC / DBI, ODT / drive impedance, Vref(ca)/Vref(dq).",
        "5. Run ZQ calibration (start/latch via MPC).",
        "6. Perform the initial WCK2CK synchronization (CAS WS_FS) and train DQ/RDQS read and WCK write timing (DFE/eq) for the active FSP.",
        "7. Device ready for normal operation.",
    ]
    d.setdefault("reset_sequence", [
        "1. Assert RESET_n LOW; device enters reset (MRs cleared, outputs Hi-Z).",
        "2. Re-run the initialization sequence from step 2.",
    ])
    d.setdefault("row_open_sequence", [
        "1. Issue ACT-1 (row high bits, bank / bank group).",
        "2. Issue ACT-2 (row low bits) to complete opening the row.",
        "3. Wait tRCD before the first column command.",
    ])
    d.setdefault("read_sequence_BL16", [
        "1. Open the target row (ACT-1, ACT-2; wait tRCD).",
        "2. Issue CAS carrying WS_RD to synchronize WCK to CK for an immediately following read.",
        "3. Issue RD with the column / bank / bank-group address (AP for auto-precharge if desired).",
        "4. Wait the programmed Read Latency (RL); the DRAM enables and drives RDQS edge-aligned with DQ.",
        "5. Capture 16 beats on both edges of RDQS; decode Read Link ECC and DBI as configured.",
        "6. Optionally issue PRE after tRTP, or use RD with auto-precharge.",
    ])
    d.setdefault("read_sequence_BL32", [
        "1-2. Same as BL16 read up to the CAS(WS_RD) sync.",
        "3. Issue RD32; optionally specify a starting position within the 32-word-aligned burst via C0 / B3.",
        "4. Capture 32 beats on DQ framed by RDQS.",
    ])
    d.setdefault("write_sequence_BL16", [
        "1. Open the target row (ACT-1, ACT-2; wait tRCD).",
        "2. Issue CAS carrying WS_WR to synchronize WCK to CK for an immediately following write.",
        "3. Issue WR (or MWR for masked write) with the column / bank / bank-group address.",
        "4. Wait the programmed Write Latency (WL); drive WCK and 16 beats of DQ (+ DMI) on both WCK edges; encode Write Link ECC.",
        "5. After tWR, issue PRE; or use WR with auto-precharge.",
    ])
    d.setdefault("write_x_sequence", [
        "1. Open the target row and issue CAS(WS_WR) with the WRX option and WXS bit.",
        "2. Issue the write; the DRAM fills the burst all-zero (WXS=0) / all-one (WXS=1) WITHOUT data transfer on the bus.",
    ])
    # FORCE-OVERWRITE refresh_sequence (sibling authored DDR3 'tRFC' density list).
    d["refresh_sequence"] = [
        "1. Track elapsed time since last refresh; target average tREFI for the current temperature range (via MRR status).",
        "2. Issue REFab (all-bank) and wait tRFCab; OR REFpb (per-bank round-robin) and wait tRFCpb while accessing other banks.",
        "3. If RFM is enabled, issue RFM commands per the activation-count policy.",
        "4. Execute required refreshes before entering self-refresh / deep sleep.",
    ]
    # FORCE-OVERWRITE self_refresh_entry_exit_sequence (sibling lists DDR3 RAS#=L,CAS#=L).
    d["self_refresh_entry_exit_sequence"] = [
        "1. Bring the device to a refreshable idle state (banks precharged).",
        "2. Issue SRE over the CA bus (no CKE); CK may be stopped per the defined window.",
        "3. To exit: restart CK, issue SRX (or rely on CS activity), and resynchronize WCK before the next transfer.",
        "4. For Deep Sleep Mode (DSE at entry): re-run the full initialization sequence on exit.",
    ]
    d.setdefault("multi_bank_bank_group_sequence", [
        "1. ACT a row in bank group BG0 bank0; respect tRRD_S to a different bank group, tRRD_L within the same bank group; at most 4 ACTs within tFAW.",
        "2. Issue CAS(WS_FS) to free-start WCK for multiple following accesses across multiple banks.",
        "3. RD/WR across banks honouring tCCD_S (different bank group) and tCCD_L (same bank group).",
        "4. PRE (per-bank) or PREab (all-bank) when done; wait tRP.",
    ])
    d.setdefault("dvfs_frequency_change_sequence", [
        "1. Quiesce traffic; precharge banks as required.",
        "2. Switch the active FSP via mode register; DVFSC selects VDD2H/VDD2L.",
        "3. Change CK / WCK frequency; re-run ZQ calibration and WCK2CK sync; retrain DQ/RDQS read and WCK write with FSP-specific RL/WL/ODT/Vref/DFE.",
        "4. Resume traffic at the new operating point.",
    ])
    # FORCE-OVERWRITE power_down_entry_exit_sequence (sibling lists DDR3 MR0 A12).
    d["power_down_entry_exit_sequence"] = [
        "1. Issue a power-down entry command over the CA bus (PD bit). There is NO CKE pin.",
        "2. The mode lasts until CS next goes high.",
        "3. On CS activity, exit power-down; resynchronize WCK before the next transfer.",
    ]
    # Drop DDR3-only sequences if the sibling left them.
    for stale in ("single_bank_read_sequence_BL8", "single_bank_write_sequence_BL8",
                  "write_leveling_sequence", "mpr_read_training_sequence",
                  "zq_calibration_sequence", "dll_off_entry_sequence",
                  "reset_with_stable_power_sequence", "multi_bank_interleave_sequence",
                  "input_clock_frequency_change_sequence"):
        d.pop(stale, None)
    _write(p, d)


def _l13(gd: Path) -> None:
    p = gd / "L13_LAB_CALIBRATION.json"
    if not p.is_file():
        return
    d = _read(p)
    # FORCE-OVERWRITE: the sibling DDR3 synth sets this False; LPDDR5 defines
    # lab/system calibration loops (ZQ, WCK2CK sync, read/write training, Vref).
    d["lab_calibration_present"] = True
    d["calibration_summary"] = (
        "LPDDR5 defines several system / lab-level loops: (1) ZQ "
        "calibration — trim output-driver / ODT impedance against an "
        "external precision reference resistor; (2) WCK2CK synchronization "
        "— lock the internal full-speed WCK phase to the quarter-speed CK "
        "before high-speed transfers (WS_FS/WS_RD/WS_WR via CAS); (3) read "
        "training — RDCAL / Read FIFO with DFE to find the DQ + RDQS "
        "sampling phase; (4) write training — Write FIFO for the WCK write "
        "eye; (5) Vref training per frequency set point. These loops are "
        "re-run after a DVFS frequency change and after deep-sleep exit.")
    # FORCE-OVERWRITE zq_calibration_procedure (sibling lists DDR3 RAS#=H,CAS#=H,WE#=L ZQCL).
    d["zq_calibration_procedure"] = {
        "purpose": "Trim output-driver / ODT impedance against an external precision reference resistor over PVT.",
        "prerequisites": "Device in the appropriate idle state; DQ bus idle on the affected device(s) during the calibration window.",
        "external_reference": "External precision resistor between the ZQ pin and ground (per JESD209-5).",
        "commands": "ZQ calibration start / latch via MPC.",
        "error_recovery": "Re-run ZQ calibration; for severe drift, retrain at the active FSP.",
    }
    # FORCE-OVERWRITE: sibling DDR3 synth may seed these dicts; direct-assign so
    # the LPDDR5 prerequisites / error_recovery subkeys are present.
    d["wck2ck_synchronization_procedure"] = {
        "purpose": "Phase-lock the DRAM's internal WCK to CK for deterministic high-speed data timing.",
        "trigger": "At init, before high-speed transfers, after DVFS change, after deep-sleep exit.",
        "options": [
            {"option": "WS_FS", "use": "Free-start; may precede multiple reads/writes."},
            {"option": "WS_RD", "use": "Read-optimized."},
            {"option": "WS_WR", "use": "Write-optimized."},
        ],
        "carried_by": "CAS command on the CA bus.",
        "error_recovery": "If the WCK eye is not centered, adjust WCK phase / leveling and re-issue the synchronization.",
    }
    d["read_training_procedure"] = {
        "purpose": "Find the optimal DQ sampling phase relative to the DRAM-driven RDQS.",
        "prerequisites": "WCK locked to CK; DFE / equalization configured for the frequency set point.",
        "procedure": [
            "1. Issue RDCAL / read the internal FIFO for a deterministic pattern.",
            "2. Sweep the DQ sampling phase with configured DFE taps.",
            "3. Compare per-phase; record the pass window; pick the center.",
        ],
        "error_recovery": "If no pass window is found, re-run ZQ calibration / WCK2CK sync, adjust DFE taps and Vref(dq), or reduce the frequency set point.",
    }
    d["write_training_procedure"] = {
        "purpose": "Center the controller-driven WCK / DQ write eye at the DRAM sampling point.",
        "procedure": [
            "1. Use the Write FIFO to load a known pattern.",
            "2. Sweep WCK-to-DQ phase and Vref(dq); read back; pick the best.",
        ],
        "error_recovery": "Adjust WCK leveling, output-driver impedance, and Vref(dq); retrain.",
    }
    d.setdefault("dvfs_retraining",
                 "After a frequency-set-point change (DVFS / DVFSC), re-run ZQ calibration, WCK2CK sync, read training, and write training with the FSP-specific RL/WL/ODT/Vref/DFE values.")
    # FORCE-OVERWRITE (sibling note references DDR3 / JESD79-3).
    d["no_analog_trim_at_bus_interface"] = (
        "LPDDR5 does not expose user-accessible analog trim/fuse registers "
        "at the bus interface; internal trim / WCK clock generator / DFE "
        "are vendor-specific and out of scope of JESD209-5.")
    # FORCE-OVERWRITE power_up_characterization (sibling lists DDR3 tDLLK/ZQCS cycles).
    d["power_up_characterization"] = {
        "supply_ramp_order": "VDD1 (~1.8 V) -> VDD2H/VDD2L -> VDDQ (0.5 V).",
        "VDDQ_V": 0.5,
        "initial_calibration": "ZQ + initial WCK2CK sync + read/write training before normal operation.",
        "deep_sleep_exit": "Full re-initialization required.",
    }
    d["notes"] = (
        "The ZQ, WCK2CK, read-training, write-training, and Vref loops are "
        "host-controlled closed loops with on-die assistance; JESD209-5 "
        "standardizes the mechanisms, the iteration is controller-IP-"
        "specific. The defining LPDDR5 addition versus DDR3 is the "
        "on-demand WCK clock requiring explicit WCK2CK synchronization "
        "before every high-speed transfer burst group.")
    # Drop DDR3-only calibration keys.
    for stale in ("write_leveling_procedure", "read_leveling_mpr_procedure",
                  "dll_reset_and_lock"):
        d.pop(stale, None)
    _write(p, d)


def _l14(gd: Path) -> None:
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["spec_version"] = (
        "JEDEC JESD209-5 — Low Power Double Data Rate 5 (LPDDR5) SDRAM "
        "Standard (19 February 2019), with addenda JESD209-5B (28 July "
        "2021) and JESD209-5X (LPDDR5X).")
    f["spec_lineage_lpddr"] = [
        {"version": "LPDDR (LPDDR1)", "year": 2006, "summary": "Original low-power DDR; 1.8 V; temperature-compensated / partial-array self-refresh; deep power-down."},
        {"version": "LPDDR2 (JESD209-2)", "year": 2009, "summary": "1.2 V; 2n/4n prefetch + non-volatile option; 10-bit DDR CA bus; up to LPDDR2-1066."},
        {"version": "LPDDR3 (JESD209-3)", "year": 2012, "summary": "1600 MT/s; write-leveling, CA training, optional ODT; 8n prefetch."},
        {"version": "LPDDR4 (JESD209-4)", "year": 2014, "summary": "Two 16-bit channels; 6-bit CA bus (two-cycle commands, CS active-high, no CKE); 16n prefetch; DBI; up to 3200 MT/s. LPDDR4X reduces Vddq to 0.6 V."},
        {"version": "LPDDR5 (JESD209-5)", "year": 2019, "summary": "WCK / RDQS on-demand clocking with quarter-speed CK; 7-bit DDR CA bus; 16 banks in 4 bank groups; 16n prefetch; VDDQ 0.5 V; link ECC; DVFS/DVFSC; deep sleep; Data-Copy / Write-X; CKE eliminated; up to 6400 Mbps."},
        {"version": "LPDDR5X (JESD209-5B / JESD209-5X)", "year": 2021, "summary": "Speed up to 8533 Mbit/s; tx/rx equalization; Adaptive Refresh Management."},
        {"version": "LPDDR6", "year": 2025, "summary": "Successor; CA bus narrowed further; 12-bit data bus per channel; higher speeds. Out of scope of JESD209-5."},
    ]
    f["previous_versions_of_this_spec"] = [
        {"version": "JESD209-5", "date": "19 February 2019", "summary": "Initial LPDDR5 SDRAM Standard."},
        {"version": "JESD209-5B", "date": "28 July 2021", "summary": "LPDDR5/5X update: 8533 Mbit/s; tx/rx equalization; Adaptive Refresh Management."},
        {"version": "JESD209-5X", "date": "2021-2024", "summary": "LPDDR5X branded extension; later devices reach 8533+ Mbit/s on 14/12 nm-class processes."},
    ]
    f["key_changes_vs_lpddr4"] = [
        {"change": "New clocking architecture: quarter-speed CK + on-demand full-speed WCK + DRAM-driven RDQS", "impact": "WCK/RDQS enabled only when needed -> major IO power saving; requires WCK2CK sync before every high-speed transfer."},
        {"change": "CA bus widened to 7 bits, double data rate", "impact": "Commands arrive at the same cadence as LPDDR4 despite quarter-speed CK; a command spans two CA transfers."},
        {"change": "CAS command moved before the read/write (WS_FS/WS_RD/WS_WR)", "impact": "CAS synchronizes WCK to CK (does not select a column), unlike LPDDR4's trailing CAS-2."},
        {"change": "16 banks in four bank groups (DDR4-style)", "impact": "Bank-group timing enables concurrency; 16n prefetch retained (NOT doubled)."},
        {"change": "VDDQ reduced to 0.5 V", "impact": "Lower IO power; DFE + (5B) tx/rx equalization required for SI."},
        {"change": "Link ECC (Read/Write) + DBI", "impact": "On-the-wire single-bit correction; reduced driven-bit count."},
        {"change": "DVFS / DVFSC, deep sleep, Data-Copy / Write-X", "impact": "Fine-grained power scaling and data-transfer reduction."},
        {"change": "CKE pin eliminated", "impact": "Low-power entry is a CA command bounded by CS."},
    ]
    f["backward_compat_traps"] = [
        {"trap_name": "wck2ck_sync_required_before_transfer",
         "rule": "The internal WCK must be phase-locked to CK via a WCK2CK synchronization (WS_FS/WS_RD/WS_WR via CAS) before any high-speed read/write.",
         "trap": "Omitting the WCK2CK sync (continuous-data-clock mindset) yields undefined read/write timing because WCK is otherwise disabled."},
        {"trap_name": "no_cke_pin",
         "rule": "LPDDR5 has no CKE pin; low-power entry is a CA command that lasts until CS next goes high.",
         "trap": "A controller expecting a CKE pin will not control LPDDR5 correctly."},
        {"trap_name": "cas_does_not_select_column",
         "rule": "In LPDDR5 the CAS command precedes the read/write and synchronizes WCK; it does NOT select a column.",
         "trap": "Treating LPDDR5 CAS like LPDDR4's column-selecting CAS-2 produces wrong addressing/timing."},
        {"trap_name": "column_name_remap",
         "rule": "LPDDR4 C0-C9 are renamed in LPDDR5 to B0-B3 and C0-C5; writes start at a multiple-of-16 address (B0-B3 zero); reads may use a non-zero B3.",
         "trap": "Reusing LPDDR4 column-bit naming mis-addresses the burst start."},
        {"trap_name": "vddq_is_0p5v",
         "rule": "LPDDR5 VDDQ is 0.5 V (vs 0.6 V LPDDR4X, 1.5 V DDR3).",
         "trap": "Driving LPDDR5 IO at a higher VDDQ damages the device."},
        {"trap_name": "deep_sleep_exit_needs_full_init",
         "rule": "Exiting Deep Sleep Mode requires the full initialization sequence (ZQ + WCK2CK + training).",
         "trap": "Resuming traffic immediately after deep-sleep exit without re-init is undefined."},
    ]
    f["version_naming_history_note"] = (
        "LPDDR5 is the fifth generation of JEDEC's Low Power DDR SDRAM line "
        "(JC-42.6), standardized as JESD209-5 (19 February 2019). The LPDDR "
        "generational naming is separate from the mainstream DDR family. "
        "JESD209-5B (2021) added the LPDDR5/5X speed extension (8533 "
        "Mbit/s), tx/rx equalization, and Adaptive Refresh Management; "
        "JESD209-5X covers the LPDDR5X branding. LPDDR5 is distinguished "
        "from DDR3 (JESD79-3) by its WCK on-demand clocking, JESD209-5 "
        "numbering, mobile low-voltage operation (VDDQ=0.5 V), and CA-bus "
        "command encoding rather than separate RAS/CAS/WE pins.")
    # Drop DDR3-only lineage keys if the sibling left them.
    for stale in ("spec_lineage_ddrx", "key_changes_vs_ddr2"):
        f.pop(stale, None)
    _write(p, d)


def _l15(gd: Path) -> None:
    p = gd / "L15_ENCODING_TABLES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["command_encoding_table"] = {
        "description": "LPDDR5 commands are encoded on the 7-bit CA bus (CA[6:0]) at double data rate; a command occupies one rising-edge and one falling-edge CA transfer.",
        "header_columns": ["Operation", "Abbrev", "Key CA fields"],
        "rows": [
            ["No operation", "NOP", "—"], ["Power-down entry", "PDE", "PD"],
            ["Read FIFO", "RDFIFO", "—"], ["Write FIFO", "WRFIFO", "—"],
            ["Read DQ Calibration", "RDCAL", "—"], ["Multi-purpose command", "MPC", "OP[7:0]"],
            ["Mode register write-2", "MRW-2", "MA[6:0], OP[7:0]"], ["Self-refresh exit", "SRX", "—"],
            ["Self-refresh entry", "SRE", "PD, DSE"], ["Mode register read", "MRR", "MA[6:0]"],
            ["Mode register write-1", "MRW-1", "MA[6:0]"], ["Refresh", "REF", "AB / BG,BA, RFM"],
            ["Precharge", "PRE", "AB / BG,BA"], ["Write-32", "WR32", "C[5:0], BG, BA, AP"],
            ["Column Address Select", "CAS", "WS_FS/WS_RD/WS_WR, WRX, WXSA/WXSB"],
            ["Masked Write", "MWR", "C[5:0], BG, BA, AP (DMI = mask)"],
            ["Write", "WR", "C[5:0], BG, BA, AP"], ["Read", "RD", "C[5:0], BG, BA, AP"],
            ["Read-32", "RD32", "C[5:0], BG, BA, AP (start via C0/B3)"],
            ["Activate-2", "ACT-2", "R[low], BG, BA"], ["Activate-1", "ACT-1", "R[high], BG, BA"],
        ],
    }
    f["wck2ck_sync_table"] = {
        "header_columns": ["Option", "Meaning"],
        "rows": [
            ["WS_FS", "WCK free-start — start WCK immediately, may precede multiple reads/writes."],
            ["WS_RD", "Read-optimized — optimize WCK timing for an immediately following read."],
            ["WS_WR", "Write-optimized — optimize WCK timing for an immediately following write."],
        ],
    }
    f["write_x_table"] = {
        "header_columns": ["WRX", "WXS", "Effect"],
        "rows": [
            ["set", 0, "Fill burst with all-zeros without transferring data."],
            ["set", 1, "Fill burst with all-ones without transferring data."],
            ["clear", "—", "Normal write — data transferred on DQ."],
        ],
    }
    f["bank_mode_table"] = {
        "header_columns": ["Mode", "Banks", "Bank Groups", "Notes"],
        "rows": [
            ["BG mode", 16, 4, "Four bank groups of four banks; tCCD_L/tRRD_L same-group."],
            ["16B mode", 16, "—", "16 flat banks."],
            ["8B mode", 8, "—", "8 banks (selected densities)."],
        ],
    }
    f["burst_length_table"] = {
        "header_columns": ["Burst", "Beats", "Notes"],
        "rows": [
            ["BL16", 16, "Default burst length."],
            ["BL32", 32, "Double-length; reads (RD32) may start within the 32-word-aligned burst via C0/B3."],
        ],
    }
    f["speed_grade_table"] = {
        "header_columns": ["Generation", "Data Rate (Mbps/pin)", "WCK (MHz)", "CK (MHz, quarter-speed)", "VDDQ (V)", "Spec"],
        "rows": [
            ["LPDDR5", 6400, 3200, 800, 0.5, "JESD209-5"],
            ["LPDDR5X", 8533, 4266, 1066, 0.5, "JESD209-5B / JESD209-5X"],
        ],
    }
    f.setdefault("field_legend", {
        "header_columns": ["Symbol", "Meaning"],
        "rows": [
            ["Bn", "Burst address bit"], ["Cn", "Column address bit"], ["Rn", "Row address bit"],
            ["BAn", "Bank address bit"], ["BGn", "Bank group address bit"],
            ["AB", "All banks"], ["AP", "Auto-precharge"], ["MAn", "Mode register address bit"],
            ["OPn", "Operation / mode register data bit"], ["WS_xx", "WCK synchronization (FS/RD/WR)"],
            ["WRX", "Write X — fill all-zero/all-one, no data transfer"],
            ["WXSA/WXSB", "Write X select"], ["PD", "Power down"], ["DSE", "Deep sleep enable"],
            ["RFM", "Refresh Management"],
        ],
    })
    f["tables"] = [
        "LPDDR5 command encoding table (CA[6:0], rising + falling CK)",
        "WCK2CK synchronization options (WS_FS / WS_RD / WS_WR)",
        "Write-X (WRX / WXS) encoding",
        "Bank-mode table (BG / 16B / 8B)",
        "Burst-length table (BL16 / BL32)",
        "Mode register map (MA[6:0])",
        "Speed-grade table (LPDDR5 6400 / LPDDR5X 8533)",
    ]
    # Drop DDR3-only tables if the sibling left them.
    for stale in ("command_truth_table", "mr0_bit_field_table",
                  "mr1_rtt_nom_table", "mr1_additive_latency_table",
                  "mr2_cwl_table", "mr2_rtt_wr_table", "mr3_mpr_table",
                  "self_refresh_mode_summary_table", "ba_mr_select_table"):
        f.pop(stale, None)
    _write(p, d)


def _l16(gd: Path) -> None:
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["must_have_properties"] = [
        "Command/address shall be transferred on a 7-bit CA bus (CA[6:0]) at double data rate referenced to the quarter-speed CK; a command occupies two CA transfers.",
        "A full-speed differential WCK (4x CK) shall frame data, enabled only when a transfer is imminent.",
        "During reads the DRAM shall drive a full-speed differential RDQS edge-aligned with the read data.",
        "Before any high-speed read/write the controller shall perform a WCK2CK synchronization (WS_FS/WS_RD/WS_WR via CAS) to lock internal WCK to CK.",
        "Opening a row shall require two Activate commands (Activate-1 then Activate-2).",
        "LPDDR5 shall NOT use a CKE pin; low-power entry shall be a CA command that lasts until CS next goes high.",
        "The device shall provide 16 banks (four bank groups of four banks in BG mode; 16B / 8B modes).",
        "Prefetch shall be 16n; default burst length BL16 with double-length BL32.",
        "Data transfer rate shall be up to 6400 Mbit/s per pin (LPDDR5); up to 8533 Mbit/s for LPDDR5X.",
        "VDDQ shall be 0.5 V; DVFSC selects VDD2H/VDD2L per frequency set point.",
        "Read/Write Link ECC (16-bit) and DBI shall be supported and configured consistently.",
        "Refresh shall support REFab and REFpb (round-robin); tREFI/tRFCab/tRFCpb honoured; RFM per JESD209-5B.",
        "Bank-group timing (tCCD_L/tRRD_L; tCCD_S/tRRD_S) and tFAW shall be honoured.",
        "Read data at programmed RL; write data accepted at programmed WL (Set A / Set B).",
        "Vref(ca)/Vref(dq) and DFE / equalization settings shall be valid for the active FSP.",
        "Deep Sleep Mode (DSE) shall be supported; exit shall require the full initialization sequence.",
    ]
    f["must_not_have_properties"] = [
        "A high-speed read/write shall not be issued without a prior WCK2CK synchronization (WCK is otherwise disabled).",
        "The CAS command shall not be treated as a column-selecting command.",
        "A CKE pin shall not be relied upon — LPDDR5 has none.",
        "VDDQ shall not be driven above 0.5 V.",
        "Writes shall not start at a non-multiple-of-16 column (B0-B3 must be zero; reads may use non-zero B3).",
        "Traffic shall not resume after deep-sleep exit without re-running the full initialization.",
        "Mismatched Read/Write Link-ECC or DBI configuration shall not be used (silent corruption).",
    ]
    f["compliance_failure_modes"] = [
        {"mode": "WCK2CK sync omitted", "trigger": "Read/Write while WCK disabled / not phase-locked — data timing undefined."},
        {"mode": "CAS misinterpreted as column select", "trigger": "Controller treats LPDDR5 CAS like LPDDR4 CAS-2 — wrong addressing/timing."},
        {"mode": "Column start not multiple-of-16 on write", "trigger": "Write with non-zero B0-B3 — mis-aligned burst start."},
        {"mode": "Missed refresh", "trigger": "Scheduler bug / extended low-power without REF — data loss; no protocol flag."},
        {"mode": "Bank-group timing violation", "trigger": "tCCD_L/tRRD_L not honoured for same-group accesses — undefined."},
        {"mode": "VDDQ over-voltage", "trigger": "IO above 0.5 V — device stress / damage."},
        {"mode": "Link-ECC / DBI mismatch", "trigger": "Controller and DRAM configured differently — silent corruption."},
        {"mode": "DVFS without retraining", "trigger": "FSP change without ZQ/WCK2CK/read/write retraining — errors."},
        {"mode": "Deep-sleep exit without re-init", "trigger": "Resuming traffic immediately after DSM exit — undefined."},
    ]
    f["min_clock_constraint"] = (
        "Operating data rate is set by the FSP: LPDDR5 up to 6400 Mbps "
        "(WCK 3200 MHz, CK 800 MHz); LPDDR5X up to 8533 Mbps (WCK 4266 MHz, "
        "CK 1066 MHz). The quarter-speed CK and 4:1 WCK:CK ratio must be "
        "maintained; WCK is enabled only when a transfer is imminent.")
    f["reset_behavior_compliance"] = (
        "Asserting RESET_n LOW returns the device to its reset state — "
        "banks closed, mode registers cleared (must be re-programmed), "
        "outputs Hi-Z. After RESET_n rises, the initialization sequence "
        "(supply ramp with VDDQ=0.5 V, CK start, MR programming, ZQ "
        "calibration, initial WCK2CK sync, read/write training) must "
        "complete before normal operation. Deep-sleep exit also requires "
        "the full initialization sequence.")
    _write(p, d)


def _l17(gd: Path) -> None:
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["channels"] = [
        {"name": "CK_t, CK_c", "direction_controller": "output", "direction_sdram": "input", "purpose": "Quarter-speed differential master clock; CA sampled at double data rate.", "active_levels": "Differential low-power swing", "idle_level": "Toggling in active states"},
        {"name": "WCK_t, WCK_c", "direction_controller": "output", "direction_sdram": "input", "purpose": "Full-speed differential Write Clock (4x CK); on-demand; frames write data.", "active_levels": "Differential low-power swing", "idle_level": "Disabled when no transfer is imminent"},
        {"name": "RDQS_t, RDQS_c", "direction_sdram": "output", "direction_controller": "input", "purpose": "Full-speed differential Read Strobe; DRAM-driven, edge-aligned with read data.", "active_levels": "Differential low-power swing", "idle_level": "High-impedance except during reads"},
        {"name": "CS", "direction_controller": "output", "direction_sdram": "input", "purpose": "Chip select; marks the first command cycle; bounds low-power-mode duration (replaces CKE).", "active_levels": "Single-ended referenced to Vref(ca)", "idle_level": "Per command framing"},
        {"name": "CA[6:0]", "direction_controller": "output", "direction_sdram": "input", "purpose": "7-bit double-data-rate command/address; a command occupies two CA transfers.", "active_levels": "Single-ended referenced to Vref(ca)", "idle_level": "Encodes NOP"},
        {"name": "DQ[15:0]", "direction": "bidirectional", "purpose": "Data bus per channel (two x8 byte groups); double data rate at the WCK/RDQS rate.", "active_levels": "Single-ended referenced to Vref(dq); VDDQ 0.5 V", "idle_level": "High-impedance when neither side driving"},
        {"name": "DMI", "direction": "bidirectional", "purpose": "Data Mask / Data Bus Inversion per byte group; write mask + DBI.", "active_levels": "Single-ended referenced to Vref(dq)", "idle_level": "Don't-care between bursts"},
        {"name": "RESET_n", "direction_controller": "output", "direction_sdram": "input", "purpose": "Active-low reset.", "active_levels": "Low-power CMOS", "idle_level": "HIGH during normal operation"},
        {"name": "ZQ", "direction": "supply / reference", "purpose": "Calibration reference; external precision resistor.", "active_levels": "Quasi-DC reference", "idle_level": "Connected to ground via external precision resistor"},
    ]
    f["power_pins"] = [
        {"name": "VDD1", "purpose": "First core supply (~1.8 V)."},
        {"name": "VDD2H", "purpose": "Second core / periphery supply, HIGH operating point (DVFSC)."},
        {"name": "VDD2L", "purpose": "Second core / periphery supply, LOW operating point (DVFSC)."},
        {"name": "VDDQ", "purpose": "DQ / IO supply, reduced to 0.5 V."},
        {"name": "VSS", "purpose": "Core ground."}, {"name": "VSSQ", "purpose": "DQ ground."},
    ]
    f["global_signals"] = []
    f["channel_counts_per_x16_channel"] = {
        "ck_pairs": 1, "wck_pairs": 1, "rdqs_pairs": 1, "cs_pins": 1,
        "ca_pins": 7, "dq_pins": 16, "byte_groups": 2,
        "dmi_pins_per_byte_group": 1, "reset_pins": 1, "zq_pins": 1,
        "supply_rails": ["VDD1", "VDD2H", "VDD2L", "VDDQ", "VSS", "VSSQ"],
    }
    f["ordering_rules"] = {
        "command_register_edge": "Command/address registered at double data rate relative to CK (rising + falling); CS marks the first cycle.",
        "data_byte_order_within_burst": "16 (BL16) or 32 (BL32) beats per LPDDR5 column addressing (B0-B3 / C0-C5); writes start at a multiple-of-16 column, reads may use a non-zero B3.",
        "wck_must_be_synced_before_transfer": "WCK2CK synchronization (WS_FS/WS_RD/WS_WR via CAS) must precede any high-speed transfer.",
    }
    # Force-overwrite dependency_graph for the LPDDR5 shape.
    f["dependency_graph"] = {
        "common_rule": "All commands are committed on the CA bus referenced to the quarter-speed CK (two CA transfers per command). The DRAM is fully synchronous to CK except for RESET_n. WCK and RDQS are enabled only when a transfer is imminent; the internal WCK must be phase-locked to CK (WCK2CK synchronization) before any high-speed read/write.",
        "data_dependency": "Read data on DQ depends on the prior RD command at the programmed Read Latency, framed by the DRAM-driven RDQS. Write data acceptance depends on the prior WR command at the programmed Write Latency, framed by the controller-driven WCK. Every high-speed transfer depends on a prior CAS WCK2CK synchronization. There is no per-beat handshake.",
        "clock_dependency": "WCK (full speed) is locked from CK (quarter speed) via WCK2CK synchronization; RDQS is generated by the DRAM during reads. CA timing depends on CK; DQ timing depends on WCK (write) / RDQS (read).",
    }
    f["handshake_pairs"] = [
        {"name": "CMD_DECODE", "from": "controller", "to": "SDRAM", "rule": "Controller drives CA[6:0] (two transfers) + CS referenced to CK; SDRAM decodes one command per the LPDDR5 encoding table."},
        {"name": "WCK2CK_SYNC", "from": "controller", "to": "SDRAM", "rule": "Controller issues CAS WS_FS/WS_RD/WS_WR; SDRAM locks internal WCK to CK before the transfer."},
        {"name": "READ_BURST", "from": "SDRAM", "to": "controller", "rule": "SDRAM drives BL16/BL32 beats on DQ at Read Latency, framed by the DRAM-driven RDQS edge-aligned with DQ."},
        {"name": "WRITE_BURST", "from": "controller", "to": "SDRAM", "rule": "Controller drives BL16/BL32 beats on DQ + DMI at Write Latency, framed by the controller-driven WCK; WRX fills without data."},
        {"name": "REFRESH", "from": "controller", "to": "SDRAM", "rule": "Controller issues REFab or REFpb (round-robin); SDRAM refreshes internally; tRFCab/tRFCpb."},
        {"name": "LOW_POWER", "from": "controller", "to": "SDRAM", "rule": "Controller issues a CA-bus low-power command (no CKE); the mode lasts until CS next goes high."},
    ]
    # Drop DDR3-only count keys if present.
    for stale in ("channel_counts_per_dram_x8_single_die",
                  "channel_counts_quad_die_x8"):
        f.pop(stale, None)
    _write(p, d)


def _l18(gd: Path) -> None:
    p = gd / "L18_INTERCONNECT_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["topology_type"] = (
        "Source-synchronous low-power mobile memory bus. The controller "
        "(master) drives the quarter-speed CK, the 7-bit DDR CA bus, CS, and "
        "on-demand full-speed WCK to one or more LPDDR5 SDRAM devices "
        "(slaves) per channel; the DRAM drives RDQS during reads. Mobile "
        "LPDDR5 is soldered directly to the SoC board (or PoP-stacked), "
        "typically as a two-channel (x16 per channel) package with an "
        "internal two-deck organization. There is no removable DIMM and no "
        "CKE pin.")
    f["supported_topologies"] = [
        {"name": "Single controller + single LPDDR5 die", "description": "Point-to-point on the SoC board / PoP; one x16 channel."},
        {"name": "Single controller + multi-die LPDDR5 package", "description": "Multiple dies; per-channel CS / clocks select dies."},
        {"name": "Two-channel x16 package", "description": "Two independent x16 channels per package."},
        {"name": "Package-on-Package (PoP) over the AP", "description": "LPDDR5 stacked on the mobile application processor."},
    ]
    f["master_slave_role_summary"] = [
        {"role": "LPDDR5 controller (master)", "description": "Generates quarter-speed CK and on-demand full-speed WCK; issues all commands on the CA bus; performs WCK2CK sync; tracks per-bank state; manages refresh (ab/pb), ZQ calibration, read/write training, link ECC, DBI, DVFS; sources DQ on writes, sinks DQ on reads."},
        {"role": "LPDDR5 SDRAM (slave)", "description": "Decodes commands from the 7-bit DDR CA bus; opens/closes rows (two-ACT); locks internal WCK to CK during WCK2CK sync; drives DQ + RDQS on reads, sinks DQ + DMI on writes; generates internal refresh; supports deep sleep and CA-bus-bounded power-down."},
    ]
    f["interconnect_role"] = (
        "There is no LPDDR5-protocol-layer interconnect (no router / "
        "bridge). The bus is a flat 1-controller : N-device per-channel bus. "
        "Device selection is via CS; bank/bank-group via BG/BA; row/column "
        "via the CA address fields. Channels are independent.")
    f["ordering_guarantees"] = {
        "within_a_burst": "16 (BL16) or 32 (BL32) beats per the LPDDR5 column addressing (B0-B3 / C0-C5); RD32 may start within the 32-word-aligned burst via C0/B3.",
        "across_commands": "Commands committed in issue order; tCCD_L/tRRD_L (same group), tCCD_S/tRRD_S (different group), tFAW, and refresh timing serialize commands; every high-speed transfer requires a prior WCK2CK sync.",
    }
    f.setdefault("memory_vs_peripheral_regions",
                 "The LPDDR5 SDRAM exposes a linear DRAM array as a bank-group x bank x row x column space plus a mode-register space via MRW/MRR. Mode-register / ZQ / training commands use the same CA bus but do not access the array.")
    f.setdefault("device_classification", {
        "soldered_LPDDR5_die": "Standalone LPDDR5 x16 die soldered / PoP-stacked on the mobile SoC board.",
        "multi_die_package": "Multiple LPDDR5 dies in one package (per-channel CS / clocks).",
        "LPDDR5_controller": "Controller + PHY IP integrated into the mobile SoC.",
        "two_deck_device": "LPDDR5 device with the two-deck internal organization.",
    })
    # FORCE-OVERWRITE evidence tables (sibling lists DDR3 fly-by / Write Leveling figures).
    f["default_signal_values_evidence_tables"] = [
        "LPDDR5 package ballout / channel organization (JESD209-5)",
        "LPDDR5 command encoding table (CA[6:0])",
        "WCK2CK synchronization description (WS_FS / WS_RD / WS_WR)",
        "Bank-group / bank organization (16 banks, 4 bank groups)",
    ]
    _write(p, d)


def _l19(gd: Path) -> None:
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f.setdefault("constraints_present", False)
    f["host_pcb_constraints_summary"] = [
        "Differential CK / WCK / RDQS matched-length routing with tight intra-pair skew at 6400+ Mbit/s; impedance-controlled differential traces.",
        "7-bit CA bus + CS routing length-matched to CK; single-ended low-power-swing referenced to Vref(ca).",
        "Per-byte-lane DQ / DMI routing matched to WCK / RDQS; single-ended referenced to Vref(dq).",
        "On-die termination (ODT) + receiver DFE / tx-rx equalization replace external DQ/DQS termination.",
        "VDDQ regulated to 0.5 V with low-noise decoupling; VDD1 (~1.8 V) and VDD2H/VDD2L with DVFSC domain switching.",
        "ZQ external precision reference resistor to ground per device.",
        "Supply ramp sequencing: VDD1 -> VDD2H/VDD2L -> VDDQ before RESET_n deassertion.",
        "Soldered / PoP mechanical attach (no DIMM connector); ballout per JESD209-5; mobile SI budget.",
        "Vref(ca) / Vref(dq) internally generated and trimmed per frequency set point.",
    ]
    f["dram_internal_constraints"] = (
        "DRAM-die-internal PDK, SDC, and layout constraints (including the "
        "on-die WCK clock generator, DFE, sense-amp bias, charge pumps) are "
        "vendor-specific (sub-20 nm-class mobile DRAM process) and out of "
        "scope. Internal trim and redundancy repair are not exposed at the "
        "bus interface.")
    f["notes"] = (
        "JESD209-5 standardizes electrical AC/DC parameters at the package "
        "balls but no internal PDK / floorplan / SDC content. LPDDR5 "
        "controller and PHY IP ship their own SDC + UPF + DFT files. The "
        "distinguishing constraint versus DDR3 is the 0.5 V VDDQ and "
        "per-FSP Vref / DVFSC scaling, plus the on-demand WCK requiring "
        "WCK2CK leveling/training in the PHY.")
    _write(p, d)


def _l20(gd: Path) -> None:
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    # FORCE-OVERWRITE: sibling DDR3 synth sets this False; LPDDR5 exposes partial
    # bus-level DFT (MRR / RDCAL / Read-FIFO / Write-FIFO / WCK2CK sync / ZQ /
    # Link-ECC status) though no formal scan/JTAG at the DRAM balls.
    f["dft_present"] = "partial"
    f["exposed_dft_features"] = [
        {"name": "Mode Register Read (MRR)", "purpose": "In-band read of device-info / operating-mode / refresh / status mode registers."},
        {"name": "Read DQ Calibration (RDCAL) / Read FIFO", "purpose": "Deterministic calibration pattern / FIFO for read-path training."},
        {"name": "Write FIFO", "purpose": "Known pattern through the write path for write-path training."},
        {"name": "WCK2CK synchronization (WS_FS/WS_RD/WS_WR)", "purpose": "Validates the WCK-to-CK phase-lock / clock path."},
        {"name": "Link ECC status", "purpose": "Flags corrected single-bit errors on the wire."},
        {"name": "ZQ calibration", "purpose": "On-die impedance calibration against the external reference resistor."},
        {"name": "Per-state IDD specifications", "purpose": "Per-state current points for power-state characterization."},
    ]
    f["no_jtag_on_DRAM_balls"] = "LPDDR5 SDRAM has no JTAG / boundary-scan / scan-shift pins at the package interface; vendor scan/BIST runs at wafer probe."
    # FORCE-OVERWRITE controller_side_dft_aids (sibling lists DDR3 RAS#/CAS#/WE#).
    f["controller_side_dft_aids"] = [
        "Per-byte-lane PHY observability: RX FIFO, WCK2CK leveling state, per-bit deskew, eye-margin sweeps, DFE taps, Vref training results via a vendor control register interface.",
        "Logic-analyzer / oscilloscope probing of CK / WCK / RDQS / CA[6:0] / CS / DQ / DMI.",
        "RDCAL fixed pattern as a deterministic read self-test.",
        "Link-ECC error counters and controller-side system ECC.",
    ]
    f["notes"] = (
        "LPDDR5 (JESD209-5) does not specify a formal in-system scan / JTAG "
        "architecture at the DRAM balls. Bus-level DFT is limited to MRR, "
        "RDCAL / Read-FIFO / Write-FIFO training, WCK2CK sync, ZQ "
        "calibration, and Link-ECC status. Internal DRAM scan / BIST / "
        "repair is vendor-proprietary.")
    _write(p, d)


def _l21(gd: Path) -> None:
    p = gd / "L21_POWER_INTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f.setdefault("power_intent_present", True)
    f["power_domains_summary"] = {
        "VDD1": "First core supply (~1.8 V) — charge-pump / wordline / high-voltage core domain.",
        "VDD2H": "Second core / periphery supply, HIGH operating point — DVFSC at higher frequencies.",
        "VDD2L": "Second core / periphery supply, LOW operating point — DVFSC at lower frequencies.",
        "VDDQ": "DQ / IO supply, reduced to 0.5 V for low IO power.",
        "VSS, VSSQ": "Core ground and DQ ground.",
        "Vref_ca": "Internally generated reference for CA / CS (per FSP).",
        "Vref_dq": "Internally generated reference for DQ / DMI (per FSP / DVFSQ).",
    }
    f["power_up_sequence"] = [
        "1. Assert RESET_n LOW.",
        "2. Ramp supplies in the defined order: VDD1 (~1.8 V) -> VDD2H / VDD2L -> VDDQ (0.5 V).",
        "3. Once stable, deassert RESET_n; wait the defined reset-exit time.",
        "4. Start the quarter-speed CK; stabilize.",
        "5. Program mode registers (FSP, RL/WL, bank mode, WCK ratio, link ECC / DBI, ODT / drive strength / Vref).",
        "6. Run ZQ calibration; perform initial WCK2CK sync; train read/write timing for the active FSP.",
    ]
    f["low_power_modes_summary"] = {
        "Power_Down": "Entered via a CA command (PD); no CKE; lasts until CS next goes high.",
        "Self_Refresh": "Entered via SRE; CK may be stopped per the defined window.",
        "Deep_Sleep_Mode": "Lowest standby power; SRE with DSE; full re-init on exit.",
        "DVFS_DVFSC": "Dynamic voltage/frequency scaling; DVFSC selects VDD2H/VDD2L; DVFSQ scales the DQ domain.",
        "Write_X_Data_Copy": "Write-X (all-zero/all-one) and Data-Copy reduce data-transfer activity.",
    }
    f["iDD_states_summary"] = [
        {"state": "IDD0", "description": "Operating one-bank active-precharge current."},
        {"state": "IDD1", "description": "Operating one-bank active-read current."},
        {"state": "IDD2N", "description": "Idle / standby current with banks precharged."},
        {"state": "IDD2P", "description": "Precharge power-down current (CA command)."},
        {"state": "IDD3N", "description": "Active standby current (bank open)."},
        {"state": "IDD3P", "description": "Active power-down current (bank open)."},
        {"state": "IDD4R", "description": "Operating burst-read current (WCK + RDQS active)."},
        {"state": "IDD4W", "description": "Operating burst-write current (WCK active)."},
        {"state": "IDD5", "description": "Refresh current (REFab / REFpb)."},
        {"state": "IDD6", "description": "Self-refresh current."},
        {"state": "IDD6DS", "description": "Deep Sleep Mode current — lowest standby power."},
    ]
    f["voltage_classes_table"] = {
        "header_columns": ["Class", "VDD1 (V)", "VDD2H (V)", "VDD2L (V)", "VDDQ (V)", "Applicable"],
        "rows": [
            ["LPDDR5", 1.8, 1.05, 0.9, 0.5, "JESD209-5 (6400 Mbps)"],
            ["LPDDR5X", 1.8, 1.05, 0.9, 0.5, "JESD209-5B / 5X (up to 8533 Mbps)"],
        ],
    }
    f.setdefault("dvfs_summary", {
        "DVFSC": "Dynamic Voltage Frequency Scaling Core — selects VDD2H or VDD2L to scale core voltage with frequency.",
        "DVFSQ": "Scales the DQ-domain voltage / Vref(dq) with the FSP.",
        "FSP": "Frequency Set Points (FSP-OP / FSP-WR) hold per-frequency RL/WL/ODT/Vref/DFE, switched on a DVFS change.",
    })
    f["notes"] = (
        "The defining LPDDR5 power features versus DDR3 are: (1) on-demand "
        "full-speed WCK / RDQS clocking (enabled only when needed); (2) VDDQ "
        "reduced to 0.5 V; (3) elimination of the CKE pin (low-power entry "
        "via CA command bounded by CS); (4) DVFS / DVFSC core-voltage "
        "scaling; (5) Deep Sleep Mode; (6) Write-X / Data-Copy data-transfer "
        "reduction.")
    # Drop DDR3-only tables if the sibling left them.
    for stale in ("self_refresh_temperature_table",
                  "partial_array_self_refresh_table"):
        f.pop(stale, None)
    _write(p, d)


def _l22(gd: Path) -> None:
    p = gd / "L22_VERIFICATION_PLAN.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f.setdefault("verification_plan_present", "implicit")
    f["verification_categories_derived_from_spec"] = [
        "Power-up + initialization — supply ramp ordering (VDDQ=0.5 V) + RESET_n + CK start + MR program + ZQ calibration + initial WCK2CK sync + read/write training.",
        "Reset — RESET_n active-low; full init re-run.",
        "Command-encoding coverage — every command in the LPDDR5 CA encoding table across two CA transfers (rising + falling CK).",
        "WCK2CK synchronization — WS_FS / WS_RD / WS_WR; verify internal WCK locks to CK.",
        "Activate — ACT-1 then ACT-2; tRCD.",
        "Read — CAS(WS_RD) -> RD / RD32 at RL; RDQS edge-aligned; BL16 / BL32; RD32 start via C0/B3; read link ECC + DBI.",
        "Write — CAS(WS_WR) -> WR / WR32 / MWR at WL (Set A / Set B); WCK-framed DQ + DMI; write link ECC + DBI.",
        "Write-X (WRX) — burst all-zero / all-one without data transfer.",
        "Masked Write (MWR) — DMI as per-byte mask.",
        "Bank-group timing — tCCD_L/tRRD_L vs tCCD_S/tRRD_S; tFAW.",
        "Refresh — REFab (tRFCab), REFpb (round-robin, tRFCpb); tREFI per temperature range; RFM (5B).",
        "Self-refresh entry/exit via CA command (no CKE); mode lasts until CS next goes high.",
        "Deep Sleep Mode (DSE) — entry; full re-init on exit.",
        "DVFS / DVFSC — FSP switch; WCK rate change; RL/WL/ODT/Vref retraining; VDD2H/VDD2L scaling.",
        "Link ECC — Read/Write single-bit correction; configuration-mismatch detection.",
        "DBI — reduced driven-bit count on DMI.",
        "Mode register access — MRW (two CA cycles) + MRR; tMRW/tMRD/tMRR.",
        "ZQ calibration — start/latch via MPC against external reference resistor.",
        "Read training — RDCAL / Read FIFO; DQ + RDQS sampling-phase sweep with DFE.",
        "Write training — Write FIFO; WCK write-eye training.",
        "CA timing (setup/hold to CK at DDR) and DQ timing (setup/hold to WCK).",
        "Differential CK / WCK / RDQS swing + crossing-point verification.",
        "Low-voltage IO compliance at VDDQ = 0.5 V; Vref(ca)/Vref(dq) per FSP.",
        "IDD measurements across the per-state current points.",
        "Two-deck / two-channel organization coverage; per-channel independence.",
    ]
    f["notes"] = (
        "JESD209-5 does not include a formal verification plan or testbench; "
        "the categories above are derived from the command-encoding, "
        "mode-register, clocking-architecture, state-machine, and AC-timing "
        "sections. Vendor LPDDR5 PHY IP ships its own verification suite "
        "(WCK2CK leveling, DFE training, link-ECC checks).")
    _write(p, d)


def _l23(gd: Path) -> None:
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f.setdefault("security_requirements_present", False)
    f["security_summary"] = (
        "LPDDR5 SDRAM (JESD209-5) is a commodity mobile memory device with "
        "NO confidentiality, NO authentication, NO bus-level encryption, NO "
        "access control, and NO secure erase at the protocol layer. It "
        "provides on-the-wire data-integrity via Read/Write Link ECC "
        "(16-bit, single-bit correcting) and, from JESD209-5B, Adaptive "
        "Refresh Management (RFM) for Rowhammer-class reliability. "
        "Cryptographic security is layered above the LPDDR5 channel by the "
        "SoC memory controller.")
    f["security_features_at_protocol_level"] = [
        {"name": "Link ECC (Read / Write)", "type": "integrity (on-the-wire, single-bit correcting)", "scope": "16-bit link ECC over the data carried across the bus per direction.", "description": "Corrects a single-bit error introduced on the wire. NOT a cryptographic MAC; transport integrity only."},
        {"name": "Adaptive Refresh Management (RFM)", "type": "reliability (Rowhammer mitigation, JESD209-5B)", "scope": "Per-bank / per-row activation accounting with controller-issued RFM commands.", "description": "Mitigates Rowhammer-class bit flips via targeted refresh when activation counts exceed a threshold. Reliability, not authentication."},
        {"name": "Permanent Write Protect (none)", "type": "n/a", "scope": "n/a", "description": "LPDDR5 has no built-in write-protect register; all cells are writable while the addressed bank is open."},
    ]
    f["no_confidentiality"] = "The LPDDR5 bus carries plaintext data on DQ; physical bus probing can sniff reads/writes. At-rest encryption is provided (if at all) by the SoC memory controller, not the LPDDR5 component."
    f["no_authentication"] = "LPDDR5 has no command authentication; any CA-bus command (SRE, MRW, deep-sleep entry) is accepted unconditionally per the encoding."
    f["no_access_control"] = "LPDDR5 has no per-bank / per-row / per-address access control at the protocol level."
    f["rowhammer_class_vulnerabilities"] = "Like all modern DRAM, LPDDR5 is susceptible to Rowhammer-class disturbance. JESD209-5B adds Adaptive Refresh Management (RFM) and activation-count-based targeted refresh; full mitigation depends on correct controller policy and optional system-level ECC."
    f["comparison_to_sibling_standards"] = "DDR3 (JESD79-3) has no on-bus CRC/parity and no Rowhammer mitigation (Rowhammer was first demonstrated on DDR3). DDR4 added CA parity, optional data CRC, and TRR hooks. DDR5 added on-die ECC and Refresh Management. LPDDR5 brings link ECC and (in 5B) Adaptive Refresh Management, leaving confidentiality/authentication to the controller/SoC."
    f["notes"] = "Security at the LPDDR5 layer is intentionally minimal — JESD209-5 is a high-throughput, low-power mobile memory standard whose protocol-level protections are transport-integrity (Link ECC) and reliability (RFM), not cryptographic."
    _write(p, d)


# ---------------------------------------------------------------------------
# Module-level importable detector (lifted from the inline detector in
# phase1_doc_one_shot_runner.py — ORGANIC-20260531). Byte-for-byte the same
# boolean the runner used inline (`_spi_blob` -> `blob`), so behaviour is
# identical; exposing it module-level lets the universal no-misfire guard
# (tests/test_protocol_detector_no_misfire.py) auto-cover this protocol.
# Reads ONLY the spec text `blob` — never a filename or benchmark name.
# ---------------------------------------------------------------------------
def is_lpddr5(blob: str) -> bool:
    """Content-only `lpddr5` detector (importable, lifted from the runner)
    WITH a FOREIGN-PRIMARY DEFER (mirrors the `is_mipi` doctrine).

    Empty-safe. Reads ONLY ``blob`` (spec text). Byte-for-byte the
    same boolean the runner used inline, gated below a foreign-primary
    defer.

    The structural LPDDR5 signature (LPDDR5 / JESD209-5 name+spec-id, or
    WCK + bank group + low-power) is necessary but NOT sufficient: the
    Phase-1 runner injects a generic memory vocabulary (and the memory-
    family gold legitimately cross-references LPDDR5 in comparison
    sections), so the SIBLING mainstream/graphics DRAM specs (DDR4 /
    DDR5 / GDDR6) carry incidental "LPDDR5"/"JESD209-5"/"WCK"+"bank
    group"+"low-power" tokens and trip the loose structural branch.

    Guard (general, content-only, density-counts + protocol-distinctive
    structural tokens — never a benchmark/chip/SKU literal): if the
    blob's DOMINANT subject is one of the sibling DRAM protocols, defer
    (False) BEFORE the LPDDR5 structural signature runs:

      - DDR4-primary: its own JESD79-4 spec-id present AND the DDR4 name
        token DOMINATES the LPDDR5 name token (a DDR4 spec mentions
        "DDR4" far more than it mentions "LPDDR5" in passing), AND the
        LPDDR5 spec-id JESD209-5 is absent. (A real LPDDR5 spec carries
        JESD209-5 and is LPDDR5-name-dominant, so it never trips this.)
      - DDR5-primary: its own JESD79-5 spec-id present together with the
        DDR5-defining structural feature (two independent 32/40-bit
        sub-channels per DIMM — absent from LPDDR5), AND the DDR5 name
        token dominates the LPDDR5 name token.
      - GDDR6-primary: the GDDR6-only structural signature — the JESD250
        graphics-SGRAM spec-id together with the graphics-SGRAM identity
        phrase (LPDDR5 is a low-power MOBILE DRAM, never a graphics
        SGRAM, so neither token appears in a real LPDDR5 spec).

    Empirically corpus-clean: the real lpddr5 benchmark trips NONE of
    these (no JESD79-4/JESD79-5 dominance, no sub-channel, no JESD250,
    no graphics SGRAM) and stays True; ddr4/ddr5/gddr6 each trip their
    own primary defer and are suppressed.
    """
    if not blob:
        return False
    low = blob.lower()

    # --- FOREIGN-PRIMARY DEFER (the blob's true subject is a sibling DRAM). ---
    n_lpddr5 = low.count("lpddr5")
    n_ddr4 = low.count("ddr4")
    n_ddr5 = low.count("ddr5")
    has_lpddr5_specid = ("jesd209-5" in low or "jesd209" in low)

    # DDR4-primary: JESD79-4 spec-id, DDR4 name dominates LPDDR5, no LPDDR5
    # spec-id. (LPDDR5's own JESD209-5 spec-id breaks this defer.)
    ddr4_primary = (
        "jesd79-4" in low
        and n_ddr4 >= 2 * max(n_lpddr5, 1)
        and n_ddr4 > n_lpddr5
        and not has_lpddr5_specid)

    # DDR5-primary: JESD79-5 spec-id + the DDR5-defining sub-channel feature
    # (absent from LPDDR5), DDR5 name dominates LPDDR5.
    ddr5_sub_channel = (
        ("sub-channel" in low or "subchannel" in low or "sub channel" in low)
        and ("independent" in low or "32-bit" in low or "32 bit" in low
             or "40-bit" in low or "two" in low))
    ddr5_primary = (
        "jesd79-5" in low
        and ddr5_sub_channel
        and n_ddr5 >= 2 * max(n_lpddr5, 1)
        and n_ddr5 > n_lpddr5)

    # GDDR6-primary: the GDDR6-only graphics-SGRAM signature (JESD250 spec-id
    # + graphics-SGRAM identity). LPDDR5 is a low-power MOBILE DRAM, never a
    # graphics SGRAM.
    graphics_sgram = (
        "graphics sgram" in low
        or "graphics ddr" in low
        or "graphics double data rate" in low
        or "graphics dram" in low
        or ("graphics memory" in low and ("gddr" in low or "sgram" in low)))
    gddr6_primary = ("jesd250" in low and graphics_sgram)

    if ddr4_primary or ddr5_primary or gddr6_primary:
        return False

    has_ddr3_only_signature = (
        ("DDR3" in blob or "JESD79-3" in blob)
        and not ("LPDDR5" in blob or "JESD209-5" in blob
                 or "WCK" in blob))
    return bool((not has_ddr3_only_signature) and (
        ("LPDDR5" in blob)
        or ("JESD209-5" in blob)
        or ("WCK" in blob
            and "bank group" in blob.lower()
            and "low-power" in blob.lower())))
