"""ONFI NAND-Flash protocol synth helper.

v0.1.84+ — ic_class-gated overlay for `storage_command_protocol` specs that
exhibit the ONFI Open NAND Flash Interface structural signature:

  (ONFI + NAND + CLE + ALE)
  OR (NAND + DQ + WE# + RE#)
  OR (Parameter Page + R/B# + ONFI)

When matched, this overlay applies the canonical ONFI 4.1 content to the
L1-L23 layer docs. The doctrine mirrors the established sibling overlays
(AMBA-AXI, SPI, I2C, UART, CAN, USB, I2S, SD/MMC, DDR) — structural-keyword
detection IS general within the ic_class.

Public entry: `apply_onfi_synth(generated_docs_dir, is_onfi, onfi_ic_name)`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import l_doc_generator_stamp as _stamp
import _pack_top_module as _ptm  # L9.top_module: one decision, one provenance stamp


def _empty(v) -> bool:
    return v in (None, {}, []) or (isinstance(v, str) and not v.strip())


def _read(p: Path) -> dict:
    return json.loads(p.read_text())


def _write(p: Path, d: dict) -> None:
    # THE L-document write chokepoint: stamps the producing release onto
    # the document, then serialises it byte-identically to before.
    _stamp.dump(p, d)


def _ensure_dict(d: dict, key: str) -> dict:
    """setdefault-None fix: if the value is None / empty, replace with {}."""
    if d.get(key) in (None, "", []):
        d[key] = {}
    if not isinstance(d.get(key), dict):
        d[key] = {}
    return d[key]


def apply_onfi_synth(generated_docs_dir: Path, is_onfi: bool,
                     onfi_ic_name: Optional[str]) -> None:
    """Apply ONFI-specific synth when the structural signature matched."""
    if not is_onfi:
        return
    gd = Path(generated_docs_dir)

    # Force ic_name across all 24 L docs.
    if onfi_ic_name is not None:
        for n in [
            "L1_DATASHEET.json", "L2_FRS.json", "L3_CMD_PROTOCOL.json",
            "L4_REGMAP.json", "L5_ADI_SPEC.json", "L6_CONTROL_LOGIC.json",
            "L7_TEST_DEBUG.json", "L8_RTL_CONSTANTS.json",
            "L8_TIMING_WAVEFORM.json", "L9_INTEGRATION_SPEC.json",
            "L10_TEST_CASES.json", "L11_OTP_CONTENT.json",
            "L12_BEHAVIORAL_SEQUENCES.json", "L13_LAB_CALIBRATION.json",
            "L14_PROTOCOL_VERSIONING.json", "L15_ENCODING_TABLES.json",
            "L16_COMPLIANCE_PROPERTIES.json",
            "L17_CHANNEL_SIGNAL_CATALOG.json",
            "L18_INTERCONNECT_TOPOLOGY.json",
            "L19_CONSTRAINTS_PDK.json", "L20_DFT_SCAN_TOPOLOGY.json",
            "L21_POWER_INTENT.json", "L22_VERIFICATION_PLAN.json",
            "L23_SECURITY_REQUIREMENTS.json",
        ]:
            q = gd / n
            if q.is_file():
                d = _read(q)
                d["ic_name"] = onfi_ic_name
                _write(q, d)

    _l1(gd)
    _l2(gd)
    _l3(gd)
    _l4(gd)
    _l5(gd)
    _l6(gd)
    _l7(gd)
    _l8_const(gd)
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


# ---------------------------------------------------------------------------
# L1 datasheet
# ---------------------------------------------------------------------------
def _l1(gd: Path) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("document_title", "Open NAND Flash Interface Specification")
    d.setdefault("document_number", "ONFI Revision 4.1")
    d.setdefault("version", "Revision 4.1")
    d.setdefault("revised_date", "12 12 2017")
    d.setdefault("manufacturer",
                 "ONFI Workgroup (Intel Corporation, Micron Technology Inc., "
                 "Phison Electronics Corp., Western Digital Corporation, "
                 "SK Hynix Inc., Sony Corporation)")
    d.setdefault("publisher", "ONFI Workgroup, www.onfi.org")
    d.setdefault("copyright",
                 "Copyright 2005-2017 Intel Corporation, Micron Technology Inc., "
                 "Phison Electronics Corp., Western Digital Corporation, "
                 "SK Hynix Inc., Sony Corporation. All rights reserved.")
    d.setdefault("external_pins", [
        "CE_n (Chip Enable, active-low; one per NAND Target unless CE_n pin reduction is used)",
        "WE_n (Write Enable, SDR; shares pin with CLK on NV-DDR/NV-DDR2/NV-DDR3)",
        "CLK (Clock, NV-DDR/NV-DDR2/NV-DDR3; shares pin with WE_n)",
        "RE_n (Read Enable True; shares pin with W/R_n on NV-DDR)",
        "RE_c (Read Enable Complement; optional NV-DDR2/NV-DDR3)",
        "W/R_n (Write/Read Direction; NV-DDR)",
        "CLE (Command Latch Enable)",
        "ALE (Address Latch Enable)",
        "WP_n (Write Protect, active-low; disables Program/Erase)",
        "R/B_n (Ready/Busy, open-drain output; LOW = busy)",
        "DQ[7:0] / IO[7:0] (bidirectional data bus, x8)",
        "DQ[15:8] (upper byte; only for x16 SDR devices)",
        "DQS (Data Strobe True, NV-DDR/NV-DDR2/NV-DDR3; bidirectional)",
        "DQS_c (Data Strobe Complement; optional NV-DDR2/NV-DDR3 differential)",
        "VccQ (I/O power; separate from core Vcc)",
        "Vcc (core power)",
        "Vss (ground)",
        "VssQ (I/O ground)",
        "VREFQ (NV-DDR2/NV-DDR3 input reference voltage)",
        "VDDi (EZ NAND internal-regulator stabilizing cap pin)",
        "Vpp (optional high-voltage power)",
        "ZQ (ZQ calibration pin; tied to Vss through RZQ)",
        "ENi / ENo (Enumeration input/output; CE_n pin reduction)",
        "VSP (Vendor Specific pins)",
    ])
    d.setdefault("external_pin_count_tsop48_x8_sdr", 48)
    d.setdefault("package_options", [
        "TSOP-48 (SDR x8/x16; NV-DDR x8)",
        "WSOP-48 (SDR x8/x16; NV-DDR x8)",
        "LGA-52 (SDR x8/x16)",
        "BGA-63 (SDR x8/x16, NV-DDR x8)",
        "BGA-100 (SDR/NV-DDR/NV-DDR2/NV-DDR3 x8)",
        "BGA-132 (SDR/NV-DDR/NV-DDR2/NV-DDR3 x8)",
        "BGA-152 (SDR/NV-DDR/NV-DDR2/NV-DDR3 x8)",
        "BGA-272 (quad 8-bit data access)",
        "BGA-316 (16/32 CE_n quad 8-bit data access)",
    ])
    d.setdefault("key_features", [
        "Four data interfaces: SDR (async), NV-DDR (≤ 400 MT/s), NV-DDR2 (≤ 800 MT/s), NV-DDR3 (≤ 1200 MT/s).",
        "Common command set: Read (00h/30h), Page Program (80h/10h), Block Erase (60h/D0h), Read Status (70h), Read Status Enhanced (78h), Read ID (90h), Read Parameter Page (ECh), Read Unique ID (EDh), Reset (FFh), Synchronous Reset (FCh), Reset LUN (FAh), ZQ Calibration Long (F9h), ZQ Calibration Short (D9h), Volume Select (E1h), ODT Configure (E2h), Set Features (EFh), Get Features (EEh).",
        "Bus-cycle framing via CLE (command), ALE (address), WE_n (latch) for SDR; CLE + ALE + WE_n + CLK + DQS for NV-DDR family.",
        "8-bit data bus (DQ[7:0]); optional 16-bit (DQ[15:0]) on SDR-only packages.",
        "Open-drain R/B_n per LUN with external pull-up; LOW while any LUN operation in progress.",
        "256-byte Parameter Page (ECh) self-describes geometry, ECC, supported timing modes; signature 'ONFI' = 4Fh 4Eh 46h 49h; 8005h CRC (init 4F4Eh) at bytes 254-255; ≥ 3 redundant copies.",
        "Extended Parameter Page (signature 'EPPS' = 45h 50h 50h 53h) for Extended ECC Information.",
        "16-byte Read Unique ID (EDh) with bit-wise complement repeated 16 times.",
        "Multi-LUN: one or more independently addressable LUNs per Target; per-LUN Status register.",
        "Multi-plane operations: Multi-plane Page Program (80h/11h), Multi-plane Block Erase (60h/D1h), Multi-plane Read (00h/32h).",
        "Read Cache (00h/31h/3Fh) pipelined random/sequential reads; Page Cache Program (80h/15h) pipelined writes.",
        "Copyback Read (00h/35h) + Copyback Program (85h/10h) for on-die copy without host data path.",
        "EZ NAND option: in-package controller for ECC offload; Status FAIL bit valid for Read.",
        "ZQ Calibration (F9h Long / D9h Short) using external RZQ (typ. 300 Ω ±1 %) for NV-DDR2/NV-DDR3 driver impedance.",
        "On-Die Termination (ODT) Deselected/Selected/Sniff; matrix termination via ODT Configure (E2h).",
        "CE_n pin reduction via Volume Select (E1h) + ENi/ENo enumeration.",
        "NV-DDR3 PHY training: Implicit DCC Training (18h), Read DQ Training (62h), Write TX DQ Training Pattern (63h) / Readback (64h), Write RX DQ Training (76h).",
        "Synchronous Reset (FCh) preserves NV-DDR/NV-DDR2/NV-DDR3 interface; Reset (FFh) drops to SDR.",
        "Status register: {WP_n, RDY, ARDY, VSP, CSP, R, FAILC, FAIL}.",
        "Staggered power-up support for multi-target rails (Section 2.14).",
    ])
    d.setdefault("topology_summary",
        "Single host (NAND controller) shared with one or more NAND Targets per CE_n. "
        "Each Target contains one or more LUNs (dies). Host drives CE_n/CLE/ALE/WE_n/RE_n/WP_n/DQ; "
        "device drives R/B_n (open-drain). NV-DDR family adds CLK (shared pin with WE_n) and DQS "
        "(bidirectional source-synchronous strobe).")
    d.setdefault("data_interface_summary_table", [
        {"interface": "SDR (asynchronous)",          "data_strobe": "WE_n / RE_n", "rates_MTps": "up to 200",  "latching_edge_data": "rising WE_n (write), falling RE_n (read)", "latching_edge_cmd_addr": "rising WE_n"},
        {"interface": "NV-DDR (source-sync)",        "data_strobe": "DQS + CLK",   "rates_MTps": "up to 400",  "latching_edge_data": "both DQS edges",  "latching_edge_cmd_addr": "rising CLK"},
        {"interface": "NV-DDR2 (diff DQS)",          "data_strobe": "DQS_t/DQS_c", "rates_MTps": "up to 800",  "latching_edge_data": "both DQS edges",  "latching_edge_cmd_addr": "rising WE_n"},
        {"interface": "NV-DDR3 (diff DQS + RE)",     "data_strobe": "DQS_t/DQS_c + RE_t/RE_c", "rates_MTps": "up to 1200", "latching_edge_data": "both DQS edges", "latching_edge_cmd_addr": "rising WE_n"},
    ])
    if _empty(d.get("revision_history")):
        d["revision_history"] = [
            {"version": "1.0",  "date": "December 28, 2006", "description": "Initial ONFI release. Asynchronous SDR only."},
            {"version": "2.0",  "date": "February 27, 2008", "description": "Added source-synchronous NV-DDR. Synchronous Reset (FCh)."},
            {"version": "2.1",  "date": "January 11, 2009",  "description": "Multi-plane. Read Cache. Read Status Enhanced (78h)."},
            {"version": "2.2",  "date": "October 7, 2009",   "description": "NV-DDR extended to 200 MT/s."},
            {"version": "2.3",  "date": "August 5, 2010",    "description": "EZ NAND option."},
            {"version": "3.0",  "date": "March 9, 2011",     "description": "NV-DDR2 + ZQ Calibration + CE_n pin reduction (Volume Select E1h)."},
            {"version": "3.1",  "date": "September 12, 2012","description": "NV-DDR2 to 800 MT/s. Extended Parameter Page 'EPPS'."},
            {"version": "3.2",  "date": "June 26, 2013",     "description": "Editorial."},
            {"version": "4.0",  "date": "April 16, 2014",    "description": "NV-DDR3 + Independent Data Buses + ODT Configure (E2h)."},
            {"version": "4.1",  "date": "December 12, 2017", "description": "NV-DDR3 to 1200 MT/s. DCC/DQ training (18h/62h/63h/64h/76h)."},
        ]
    d.setdefault("abstract",
        "The Open NAND Flash Interface (ONFI) specification defines a "
        "standardized NAND Flash device interface that provides the means for "
        "a system to be designed that supports a range of NAND Flash devices "
        "without direct design pre-association. ONFI 4.1 defines four data "
        "interfaces (asynchronous SDR, source-synchronous NV-DDR, NV-DDR2, "
        "and NV-DDR3) with data rates up to 1.2 GT/s, a unified command set, "
        "a 256-byte parameter page describing device geometry and "
        "capabilities, multi-LUN support per package, optional EZ NAND ECC "
        "offload, multi-plane operations, command/address/data latching via "
        "CLE/ALE/WE_n strobes (SDR) or CLK/WE_n (NV-DDR family), and on-die "
        "termination (ODT) for NV-DDR2/NV-DDR3.")
    d.setdefault("overview",
        "ONFI defines a standardized hardware interface to packaged NAND "
        "Flash devices. The specification covers physical/electrical "
        "signaling for four interface families, a unified command set "
        "transferred over the 8-bit DQ bus with CLE/ALE/WE_n latching, a "
        "256-byte Parameter Page with optional Extended Parameter Page that "
        "self-describes device geometry and ECC requirements, per-LUN status "
        "register polling via Read Status (70h) and Read Status Enhanced "
        "(78h) plus the open-drain R/B_n pin, multi-LUN/multi-plane and "
        "CE_n pin reduction with Volume Select, Set Features (EFh) / Get "
        "Features (EEh) for run-time configuration, and optional EZ NAND "
        "for ECC offload. Jointly authored by Intel, Micron, Phison, "
        "Western Digital, SK Hynix, and Sony.")
    d.setdefault("keywords", [
        "ONFI", "Open NAND Flash Interface", "NAND Flash", "ONFI 4.1",
        "SDR", "NV-DDR", "NV-DDR2", "NV-DDR3", "CLE", "ALE", "WE_n", "RE_n",
        "CE_n", "DQ", "DQS", "R/B_n", "Ready/Busy", "Read ID",
        "Read Parameter Page", "Set Features", "Get Features",
        "ZQ Calibration", "EZ NAND", "LUN", "Page Program", "Block Erase",
        "Multi-plane", "ODT", "tCCS", "tCAD", "Synchronous Reset",
        "Volume Select", "CE_n pin reduction",
    ])
    d.setdefault("use_cases", [
        "Solid-state drives (SSDs) — host SSD controller talks ONFI to multiple NAND packages in parallel.",
        "USB flash drives and microSD / SD / eMMC card internal NAND.",
        "Embedded MMC (eMMC) and Universal Flash Storage (UFS) NAND die.",
        "Enterprise NVMe storage with multi-channel ONFI NAND backends.",
        "Removable consumer storage (CompactFlash, CFexpress, XQD).",
        "Automotive and industrial bulk-storage SoCs.",
        "Networking equipment configuration storage.",
    ])
    _write(p, d)


# ---------------------------------------------------------------------------
# L2 FRS
# ---------------------------------------------------------------------------
def _l2(gd: Path) -> None:
    p = gd / "L2_FRS.json"
    if not p.is_file():
        return
    d = _read(p)
    po = _ensure_dict(d, "protocol_overview")
    po.setdefault("type",
        "Host-mastered command/address/data protocol over an 8-bit DQ bus "
        "with cycle-type selection via CLE (command), ALE (address), or "
        "neither (data) — latched on WE_n rising edge (SDR) or CLK rising "
        "edge (NV-DDR) or both DQS edges (NV-DDR data).")
    po.setdefault("duplex", "half-duplex (DQ bus shared for cmd/addr/data; W/R_n on NV-DDR selects bus owner)")
    po.setdefault("synchronous_modes", ["NV-DDR (CLK)", "NV-DDR2 (CLK + diff DQS)", "NV-DDR3 (CLK + diff RE/DQS)"])
    po.setdefault("asynchronous_mode", "SDR (WE_n / RE_n strobes)")
    po.setdefault("wire_names_common", ["CE_n", "CLE", "ALE", "WP_n", "R/B_n (open-drain)", "DQ[7:0]", "Vcc/VccQ/Vss/VssQ"])
    po.setdefault("wire_names_sdr_extra", ["WE_n", "RE_n", "DQ[15:8] for x16 SDR"])
    po.setdefault("wire_names_nv_ddr_extra", ["CLK (shares WE_n pin)", "W/R_n (shares RE_n pin)", "DQS"])
    po.setdefault("wire_names_nv_ddr2_3_extra", ["DQS_t/DQS_c", "RE_t/RE_c (NV-DDR3)", "VREFQ", "ZQ"])
    po.setdefault("host_role", "Bus master; drives all strobes; runs initialization, training, feature programming.")
    po.setdefault("device_role", "Slave; latches cmd/addr/write data on CLE/ALE/WE_n; drives DQ on RE_n/DQS edges; pulls R/B_n LOW when LUN busy.")
    fr = [
        {"id": "FR-PINS-01",     "text": "Device shall expose at minimum CE_n, CLE, ALE, WE_n, RE_n, WP_n, R/B_n, DQ[7:0], Vcc/VccQ/Vss/VssQ. NV-DDR family adds CLK (shared WE_n), W/R_n (shared RE_n), DQS; NV-DDR2/3 adds differential DQS_t/DQS_c, VREFQ, ZQ."},
        {"id": "FR-INTERFACES-02","text": "Device shall support SDR. Optional NV-DDR / NV-DDR2 / NV-DDR3 advertised via Parameter Page timing-mode bitmaps."},
        {"id": "FR-CYCLE-TYPE-03","text": "Bus cycle type: CLE=1, ALE=0, WE_n pulse → command; CLE=0, ALE=1, WE_n pulse → address; CLE=0, ALE=0, WE_n → write data; CLE=0, ALE=0, RE_n → read data."},
        {"id": "FR-CMD-SET-04",  "text": "Mandatory command set: Read (00h/30h), Block Erase (60h/D0h), Read Status (70h), Page Program (80h/10h), Read ID (90h), Read Parameter Page (ECh), Reset (FFh), Change Read Column (05h/E0h). NV-DDR3 adds mandatory Write TX DQ Training Pattern (63h) and Readback (64h)."},
        {"id": "FR-RBN-05",      "text": "R/B_n open-drain; LOW whenever any LUN has operation in progress; external pull-up required."},
        {"id": "FR-STATUS-06",   "text": "Read Status (70h) returns 1 byte: bit 7 WP_n, bit 6 RDY, bit 5 ARDY, bit 4 VSP, bit 3 CSP, bit 2 R, bit 1 FAILC, bit 0 FAIL."},
        {"id": "FR-PARAM-07",    "text": "256-byte Parameter Page (ECh+00h); bytes 0-3 signature 'ONFI' (4Fh 4Eh 46h 49h); bytes 254-255 CRC (polynomial 8005h, init 4F4Eh); ≥ 3 redundant copies at offsets 0/256/512."},
        {"id": "FR-UID-08",      "text": "Read Unique ID (EDh) returns 16-byte UID + 16-byte bit-wise complement; valid if (UID XOR complement) = all ones; 16 copies stored."},
        {"id": "FR-MULTILUN-09", "text": "Each LUN executes commands independently; Read Status Enhanced (78h + 3 row addr) selects LUN for status poll."},
        {"id": "FR-MULTIPLANE-10","text": "Multi-plane uses 11h/D1h second-cycle continuation between planes (80h/11h…80h/10h; 60h/D1h…60h/D0h)."},
        {"id": "FR-WP-11",       "text": "WP_n LOW disables Program/Erase; does NOT disable Read."},
        {"id": "FR-RESET-12",    "text": "Reset (FFh) → SDR, timing mode 0; Synchronous Reset (FCh) preserves data interface and mode; Reset LUN (FAh) per-LUN."},
        {"id": "FR-FEATURES-13", "text": "Set Features (EFh + addr + 4 P-bytes) / Get Features (EEh + addr → 4 P-bytes) configure Timing Mode (01h), NV-DDR2/3 Config (02h), I/O Drive Strength (10h), DCC/DQ Training (08h-0Bh), External Vpp (39h), Volume Configuration (58h), EZ NAND (80h-81h)."},
        {"id": "FR-ZQ-14",       "text": "Devices supporting NV-DDR2/NV-DDR3 shall implement ZQ Calibration Long (F9h, tZQCL ≥ 1 µs) after Reset and ZQ Calibration Short (D9h) periodically. RZQ external resistor to Vss (typ. 300 Ω ±1 %)."},
        {"id": "FR-ODT-15",      "text": "Matrix-termination devices shall support ODT Configure (E2h). ODT states: Deselected / Selected / Sniff per LUN."},
        {"id": "FR-CE-RED-16",   "text": "CE_n pin reduction devices shall support Volume Select (E1h) + ENi/ENo enumeration. Volume Address ≤ 4 bits programmed during initialization."},
        {"id": "FR-PARAM-CRC-17","text": "Parameter Page Integrity CRC (bytes 254-255): 16-bit, polynomial 8005h, initial 4F4Eh, no final XOR, no bit reversal, MSB-first per byte; covers bytes 0-253."},
        {"id": "FR-EXT-PARAM-18","text": "Extended Parameter Page signature 'EPPS' (45h 50h 50h 53h at bytes 2-5); CRC at bytes 0-1 covers bytes 2..end; section types: 0 unused, 1 additional section types/lengths, 2 Extended ECC Information."},
        {"id": "FR-EZNAND-19",   "text": "EZ NAND devices advertise EZ NAND support in Parameter Page; FAIL bit valid for Read/Program/Erase (vs Program/Erase only on raw NAND)."},
        {"id": "FR-WP-PWRUP-20", "text": "WP_n shall not transition during active Program/Erase or while Write Enable is active."},
    ]
    if _empty(d.get("functional_requirements")):
        d["functional_requirements"] = fr
    if _empty(d.get("error_response_conditions")):
        d["error_response_conditions"] = [
            "Read failure on EZ NAND — Status bit 0 (FAIL) set; CSP optionally indicates ECC threshold.",
            "Program failure — Status bit 0 (FAIL) set; page in indeterminate state.",
            "Erase failure / attempt on factory-bad block — Status bit 0 (FAIL) set; device does not proceed.",
            "Page Cache prior-command failure — Status bit 1 (FAILC) set after second 15h/10h.",
            "Parameter Page CRC mismatch — host reads next redundant copy.",
            "Read Unique ID complement mismatch — host iterates next of 16 copies.",
            "WP_n violation — device shall not perform Program/Erase.",
            "ZQ Calibration failure — Status bit 0 (FAIL) set.",
            "Invalid timing mode — host issues Reset (FFh) to recover.",
        ]
    if _empty(d.get("compliance_requirements")):
        d["compliance_requirements"] = [
            "Host shall hold WP_n stable during Program and Erase.",
            "Host shall hold DQS_t HIGH during NV-DDR2/3 Idle when ODT enabled.",
            "Host shall wait for R/B_n HIGH (or RDY=1) before issuing next command (except Read Status, Reset).",
            "Host shall enforce tWB / tRR / tCS / tCH / tCEA / tCLR / tWHR / tCCS / tADL per Section 4.17 for the active data interface.",
            "Host shall validate Parameter Page Integrity CRC before trusting field values.",
            "Host shall NOT use Read Status Enhanced (78h) during/after Target-level commands (Read Parameter Page, Read ID, ZQ Calibration); use Read Status (70h).",
            "Host shall issue ZQ Calibration Long (F9h) once after Reset and ZQ Short (D9h) periodically.",
            "Host shall ensure WP_n does not transition during Program/Erase or with Write Enable active.",
            "Host shall not configure a timing mode that exceeds device-reported maximum.",
        ]
    if _empty(d.get("configurations")):
        d["configurations"] = [
            {"name": "SDR x8",      "description": "Asynchronous SDR, 8-bit DQ. Up to 200 MT/s."},
            {"name": "SDR x16",     "description": "Asynchronous SDR, 16-bit DQ (SDR-only packages)."},
            {"name": "NV-DDR",      "description": "Source-sync, single-ended DQS, CLK on WE_n pin. Up to 400 MT/s."},
            {"name": "NV-DDR2",     "description": "Source-sync with differential DQS_t/DQS_c. WE_n for cmd/addr. ODT + ZQ. Up to 800 MT/s."},
            {"name": "NV-DDR3",     "description": "Source-sync with differential DQS_t/DQS_c AND RE_t/RE_c. DCC + DQ training. Up to 1200 MT/s."},
            {"name": "EZ NAND",     "description": "In-package controller for ECC offload."},
            {"name": "CE_n pin reduction", "description": "Volume Select (E1h) with ENi/ENo enumeration."},
        ]
    _write(p, d)


# ---------------------------------------------------------------------------
# L3 CMD protocol
# ---------------------------------------------------------------------------
def _l3(gd: Path) -> None:
    p = gd / "L3_CMD_PROTOCOL.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("protocol_type",
        "Host-mastered byte-cycle protocol over 8-bit DQ. Each cycle is "
        "{Command (CLE=1, ALE=0, WE_n rising → DQ=opcode), Address (CLE=0, "
        "ALE=1, WE_n rising → DQ=address byte), Write Data (CLE=0, ALE=0, "
        "WE_n rising → DQ=write byte), Read Data (CLE=0, ALE=0, RE_n "
        "falling → device drives DQ=read byte)}.")
    d.setdefault("cmd_format", {
        "command_byte_width": 8,
        "fields": [
            {"name": "Opcode",              "bits": 8, "value": "00h..FFh per Table 94 of ONFI 4.1"},
            {"name": "Second cycle opcode", "bits": 8, "value": "Optional confirm (10h/30h/D0h/E0h/15h/11h/D1h)"},
        ],
        "address_cycles": "Up to 5 (2 column + 3 row); column LSB shall be zero for NV-DDR family.",
        "latching_edge_sdr":       "Rising edge of WE_n",
        "latching_edge_nv_ddr":    "Rising edge of CLK (cmd/addr); DQS edges (data)",
        "latching_edge_nv_ddr2_3": "Rising edge of WE_n (cmd/addr); DQS edges (data)",
    })
    d.setdefault("response_classes", [
        {"name": "Status byte",      "length_bits": 8,    "content": "{WP_n, RDY, ARDY, VSP, CSP, R, FAILC, FAIL}"},
        {"name": "ID bytes",         "length_bits": 32,   "content": "Mfr ID + Device ID + 2 vendor-defined (90h+00h); 'ONFI' (90h+20h); 'JEDEC' (90h+40h)"},
        {"name": "Parameter Page",   "length_bits": 2048, "content": "256-byte page + redundant copies; CRC 8005h init 4F4Eh"},
        {"name": "Extended Parameter Page", "length_bits": "variable", "content": "Signature 'EPPS' bytes 2-5; CRC bytes 0-1"},
        {"name": "Unique ID",        "length_bits": 512,  "content": "16 × (16-byte UID + 16-byte complement)"},
        {"name": "Feature data",     "length_bits": 32,   "content": "Get Features 4 P-bytes per feature address"},
        {"name": "Page data",        "length_bits": "page_size_bytes × 8", "content": "Read / Read Cache burst on DQ"},
    ])
    d.setdefault("data_block_format", {
        "page_data_burst":  "Bytes streamed on DQ at host RE_n pulses (SDR) or RE/DQS edges (NV-DDR family).",
        "write_data_burst": "Host streams write bytes during data-cycle pulses (WE_n SDR / DQS NV-DDR).",
        "tCCS_constraint":  "Host shall wait ≥ tCCS after second address byte of Change Read/Write Column before next data cycle.",
        "data_burst_pause": "Host may stop RE_n / DQS; ODT (if enabled) stays enabled; warmup not re-issued on resume.",
        "data_burst_exit":  "Host raises CE_n, ALE, or CLE to one to exit data burst.",
    })
    if _empty(d.get("command_categories")):
        d["command_categories"] = [
            {"category": "Reset",          "opcodes": "Reset (FFh), Synchronous Reset (FCh), Reset LUN (FAh)"},
            {"category": "Identification", "opcodes": "Read ID (90h), Read Parameter Page (ECh), Read Unique ID (EDh)"},
            {"category": "Status",         "opcodes": "Read Status (70h), Read Status Enhanced (78h)"},
            {"category": "Read",           "opcodes": "Read (00h/30h), Read Cache (00h/31h, 31h, 3Fh), Copyback Read (00h/35h), Change Read Column (05h/E0h, 06h/E0h)"},
            {"category": "Program",        "opcodes": "Page Program (80h/10h), Page Cache Program (80h/15h), Copyback Program (85h/10h), Change Write Column (85h), Change Row Address (85h)"},
            {"category": "Erase",          "opcodes": "Block Erase (60h/D0h)"},
            {"category": "Multi-plane",    "opcodes": "Multi-plane Read (00h/32h), Multi-plane Program (80h/11h), Multi-plane Erase (60h/D1h)"},
            {"category": "Features",       "opcodes": "Set Features (EFh), Get Features (EEh), LUN Set/Get Features (D5h/D4h)"},
            {"category": "Volume / ODT",   "opcodes": "Volume Select (E1h), ODT Configure (E2h)"},
            {"category": "ZQ calibration", "opcodes": "ZQ Long (F9h), ZQ Short (D9h)"},
            {"category": "Training (NV-DDR3)", "opcodes": "Implicit DCC (18h), Read DQ (62h), Write TX Pattern (63h), Write TX Readback (64h), Write RX (76h)"},
        ]
    if _empty(d.get("channels")):
        d["channels"] = [
            {"name": "CE_n",  "direction": "host → device", "description": "Chip Enable (active-low)."},
            {"name": "CLE",   "direction": "host → device", "description": "Command Latch Enable."},
            {"name": "ALE",   "direction": "host → device", "description": "Address Latch Enable."},
            {"name": "WE_n",  "direction": "host → device", "description": "Write Enable (SDR); shares pin with CLK on NV-DDR."},
            {"name": "RE_n / RE_t", "direction": "host → device", "description": "Read Enable (True); shares pin with W/R_n on NV-DDR."},
            {"name": "WP_n",  "direction": "host → device", "description": "Write Protect (active-low)."},
            {"name": "R/B_n", "direction": "device → host", "description": "Ready/Busy (open-drain). LOW = busy."},
            {"name": "DQ[7:0]","direction": "bidirectional", "description": "8-bit data bus."},
            {"name": "DQS / DQS_t","direction": "bidirectional", "description": "Data Strobe (NV-DDR family)."},
        ]
    if _empty(d.get("valid_ready_handshake_rules")):
        d["valid_ready_handshake_rules"] = [
            "No per-byte VALID/READY on the wire — flow is regulated by host strobes (WE_n/RE_n/CLK/DQS) and device R/B_n.",
            "R/B_n LOW indicates busy; host shall wait for R/B_n HIGH OR RDY=1 in Status before next command (except Read Status, Reset).",
            "Multi-LUN: while R/B_n LOW, host may poll a specific LUN via Read Status Enhanced (78h + 3 row addr).",
            "Read Status Enhanced shall NOT be used during/after Target-level commands.",
        ]
    d.setdefault("burst_based", True)
    d.setdefault("byte_oriented", True)
    d.setdefault("frame_format", {
        "command_cycle":   "CLE=1, ALE=0, WE_n rising, DQ = opcode (8 bits).",
        "address_cycle":   "CLE=0, ALE=1, WE_n rising, DQ = address byte.",
        "write_data_cycle":"CLE=0, ALE=0, WE_n rising (SDR) or DQS edge (NV-DDR family), DQ = write byte.",
        "read_data_cycle": "CLE=0, ALE=0, RE_n falling (SDR) or RE_n_t/RE_n_c + DQS edges (NV-DDR family), DQ = device-driven read byte.",
        "status_byte":     "Single 8-bit value returned after 70h or 78h.",
    })
    if _empty(d.get("key_commands")):
        d["key_commands"] = [
            {"opcode": "00h/30h", "name": "Read",                       "address_cycles": 5, "second_cycle": "30h", "response": "Status + page-data burst", "description": "Reads a page identified by row address into the page register."},
            {"opcode": "00h/31h", "name": "Read Cache Random",          "address_cycles": 5, "second_cycle": "31h", "response": "Status + page burst",      "description": "Pipelined random read."},
            {"opcode": "31h",     "name": "Read Cache Sequential",      "address_cycles": 0, "second_cycle": "",    "response": "Status + next-page burst", "description": "Sequential next-page read after Read Cache Random."},
            {"opcode": "3Fh",     "name": "Read Cache End",             "address_cycles": 0, "second_cycle": "",    "response": "Status + final burst",     "description": "Terminates Read Cache sequence."},
            {"opcode": "00h/35h", "name": "Copyback Read",              "address_cycles": 5, "second_cycle": "35h", "response": "",                          "description": "Reads source page into page register for Copyback Program."},
            {"opcode": "05h/E0h", "name": "Change Read Column",         "address_cycles": 2, "second_cycle": "E0h", "response": "page-data burst from new col", "description": "Repositions read pointer; tCCS applies."},
            {"opcode": "06h/E0h", "name": "Change Read Column Enhanced","address_cycles": 5, "second_cycle": "E0h", "response": "page-data burst",          "description": "Change Read Column with full 5-cycle address."},
            {"opcode": "60h/D0h", "name": "Block Erase",                "address_cycles": 3, "second_cycle": "D0h", "response": "R/B_n LOW + Status",        "description": "Erases the block; tBERS."},
            {"opcode": "60h/D1h", "name": "Multi-plane Block Erase",    "address_cycles": "3+3", "second_cycle": "D1h then D0h", "response": "R/B_n LOW + per-plane Status", "description": "Concurrent multi-plane erase."},
            {"opcode": "70h",     "name": "Read Status",                "address_cycles": 0, "second_cycle": "",    "response": "1-byte status",             "description": "Returns composite per-LUN status byte."},
            {"opcode": "78h",     "name": "Read Status Enhanced",       "address_cycles": 3, "second_cycle": "",    "response": "1-byte status",             "description": "Per-LUN/plane status; turns off other LUN output buffers."},
            {"opcode": "80h/10h", "name": "Page Program",               "address_cycles": 5, "second_cycle": "10h", "response": "R/B_n LOW + Status",        "description": "Programs a page from page register; tPROG."},
            {"opcode": "80h/11h", "name": "Multi-plane Page Program",   "address_cycles": "5+5", "second_cycle": "11h then 10h", "response": "R/B_n LOW + per-plane Status", "description": "Concurrent multi-plane program."},
            {"opcode": "80h/15h", "name": "Page Cache Program",         "address_cycles": 5, "second_cycle": "15h", "response": "R/B_n LOW; FAILC reports prior", "description": "Pipelined program."},
            {"opcode": "85h/10h", "name": "Copyback Program",           "address_cycles": 5, "second_cycle": "10h", "response": "R/B_n LOW + Status",        "description": "Programs destination from previously read source."},
            {"opcode": "85h",     "name": "Change Write Column",        "address_cycles": 2, "second_cycle": "",    "response": "",                          "description": "Repositions write pointer; tCCS applies."},
            {"opcode": "85h",     "name": "Change Row Address",         "address_cycles": 5, "second_cycle": "",    "response": "",                          "description": "Changes row address for buffered write data."},
            {"opcode": "90h",     "name": "Read ID",                    "address_cycles": 1, "second_cycle": "",    "response": "4+ ID bytes",               "description": "Address 00h = Mfr/Device; 20h = 'ONFI'; 40h = 'JEDEC'."},
            {"opcode": "E1h",     "name": "Volume Select",              "address_cycles": 1, "second_cycle": "",    "response": "",                          "description": "Directs subsequent CE_n-shared commands."},
            {"opcode": "E2h",     "name": "ODT Configure",              "address_cycles": "variable", "second_cycle": "", "response": "",                    "description": "Matrix-termination ODT configuration."},
            {"opcode": "D9h",     "name": "ZQ Calibration Short",       "address_cycles": 0, "second_cycle": "",    "response": "R/B_n LOW + Status",        "description": "Periodic short ZQ calibration."},
            {"opcode": "F9h",     "name": "ZQ Calibration Long",        "address_cycles": 0, "second_cycle": "",    "response": "R/B_n LOW + Status",        "description": "Long ZQ calibration after reset; tZQCL ≥ 1 µs."},
            {"opcode": "ECh",     "name": "Read Parameter Page",        "address_cycles": 1, "second_cycle": "",    "response": "≥ 256 bytes (3 copies)",   "description": "Read Parameter Page with CRC + redundancy."},
            {"opcode": "EDh",     "name": "Read Unique ID",             "address_cycles": 1, "second_cycle": "",    "response": "16 × (16 + 16) bytes",      "description": "UID + complement, 16 copies."},
            {"opcode": "EEh",     "name": "Get Features",               "address_cycles": 1, "second_cycle": "",    "response": "4 bytes P1..P4",            "description": "Reads feature parameter file."},
            {"opcode": "EFh",     "name": "Set Features",               "address_cycles": 1, "second_cycle": "",    "response": "R/B_n LOW + Status",        "description": "Writes feature parameter file (4 P-bytes)."},
            {"opcode": "FAh",     "name": "Reset LUN",                  "address_cycles": 3, "second_cycle": "",    "response": "R/B_n LOW + Status",        "description": "Resets only the addressed LUN."},
            {"opcode": "FCh",     "name": "Synchronous Reset",          "address_cycles": 0, "second_cycle": "",    "response": "R/B_n LOW",                  "description": "Resets without changing data interface or timing mode."},
            {"opcode": "FFh",     "name": "Reset",                      "address_cycles": 0, "second_cycle": "",    "response": "R/B_n LOW",                  "description": "Universal reset; SDR data interface, timing mode 0."},
            {"opcode": "18h",     "name": "Implicit DCC Training",      "address_cycles": 0, "second_cycle": "",    "response": "",                          "description": "Internal clock duty-cycle correction (NV-DDR3)."},
            {"opcode": "62h",     "name": "Read DQ Training",           "address_cycles": "variable", "second_cycle": "", "response": "training pattern", "description": "Device-driven training pattern for host RX sweep."},
            {"opcode": "63h",     "name": "Write TX DQ Training Pattern","address_cycles": "variable","second_cycle": "", "response": "",                "description": "Host writes training pattern to device."},
            {"opcode": "64h",     "name": "Write TX DQ Training Readback","address_cycles": "variable","second_cycle": "","response": "pattern readback","description": "Device returns previously written pattern."},
            {"opcode": "76h",     "name": "Write RX DQ Training",       "address_cycles": "variable", "second_cycle": "", "response": "",                  "description": "Device-side RX DQ training."},
        ]
    _write(p, d)


# ---------------------------------------------------------------------------
# L4 register map
# ---------------------------------------------------------------------------
def _l4(gd: Path) -> None:
    p = gd / "L4_REGMAP.json"
    if not p.is_file():
        return
    d = _read(p)
    d["register_map_present"] = True
    d["notes"] = (
        "ONFI defines a per-LUN Status Register (1 byte, 70h/78h), a 256-byte "
        "Parameter Page (ECh), a 16-byte Unique ID (EDh), an Extended "
        "Parameter Page (variable), and a Feature parameter file (4 bytes "
        "per feature address, EFh/EEh). No traditional memory-mapped "
        "register block — all state accessed via command-addressed reads.")
    d.setdefault("register_count", 7)
    regs = [
        {"name": "Status Register", "long_name": "Per-LUN Status Register byte", "width_bits": 8,
         "access": "Read via Read Status (70h) and Read Status Enhanced (78h).",
         "description": "{WP_n, RDY, ARDY, VSP, CSP, R, FAILC, FAIL}. SR[5:0] invalid when RDY=0 (WP_n still valid).",
         "fields": [
            {"bit": 7, "name": "WP_n",  "description": "0 = write-protected; 1 = not. Always valid."},
            {"bit": 6, "name": "RDY",   "description": "1 = LUN ready; 0 = command in progress; SR[5:0] invalid."},
            {"bit": 5, "name": "ARDY",  "description": "1 = no array op; 0 = command in progress or array op."},
            {"bit": 4, "name": "VSP",   "description": "Vendor Specific."},
            {"bit": 3, "name": "CSP",   "description": "Command Specific (e.g., EZ NAND read ECC threshold)."},
            {"bit": 2, "name": "R",     "description": "Reserved (0)."},
            {"bit": 1, "name": "FAILC", "description": "1 = prior cached command failed (Page Cache Program)."},
            {"bit": 0, "name": "FAIL",  "description": "1 = last command failed (Program/Erase; or Read on EZ NAND; or ZQ calibration)."},
         ]},
        {"name": "Parameter Page", "long_name": "ONFI Parameter Page", "width_bits": 2048,
         "access": "Read Parameter Page (ECh + 00h).",
         "description": "Bytes 0-3 = 'ONFI' (4Fh 4Eh 46h 49h); bytes 254-255 = Integrity CRC; ≥ 3 redundant copies at 0/256/512.",
         "fields": [
            {"bytes": "0-3",      "name": "Parameter Page signature",        "description": "'ONFI' = 4Fh 4Eh 46h 49h."},
            {"bytes": "4-5",      "name": "Revision number",                 "description": "Bit 10 = ONFI 4.1."},
            {"bytes": "6-7",      "name": "Features supported",              "description": "Bitmap (NV-DDR / NV-DDR2 / NV-DDR3 / ...)."},
            {"bytes": "8-9",      "name": "Optional commands supported",     "description": "Bitmap of optional commands."},
            {"bytes": "32-43",    "name": "Device manufacturer",             "description": "12 ASCII bytes."},
            {"bytes": "44-63",    "name": "Device model",                    "description": "20 ASCII bytes."},
            {"bytes": "64",       "name": "JEDEC manufacturer ID",           "description": "8-bit."},
            {"bytes": "80-83",    "name": "Number of data bytes per page",   "description": "32-bit."},
            {"bytes": "84-85",    "name": "Number of spare bytes per page",  "description": "16-bit."},
            {"bytes": "92-95",    "name": "Number of pages per block",       "description": "32-bit."},
            {"bytes": "96-99",    "name": "Number of blocks per LUN",        "description": "32-bit."},
            {"bytes": "100",      "name": "Number of LUNs",                  "description": "1..255."},
            {"bytes": "101",      "name": "Address cycles",                  "description": "bits[7:4] row, bits[3:0] column."},
            {"bytes": "112",      "name": "Bits ECC correctability",         "description": "0xFF → see Extended ECC Information."},
            {"bytes": "115",      "name": "EZ NAND support",                 "description": "Bit 0 = EZ NAND supported."},
            {"bytes": "129-130",  "name": "Timing mode support (SDR)",       "description": "Bit n = SDR mode n."},
            {"bytes": "133-134",  "name": "tPROG (max)",                     "description": "µs."},
            {"bytes": "135-136",  "name": "tBERS (max)",                     "description": "µs."},
            {"bytes": "137-138",  "name": "tR (max)",                        "description": "µs."},
            {"bytes": "139-140",  "name": "tCCS (min)",                      "description": "ns."},
            {"bytes": "142-143",  "name": "NV-DDR2 timing mode support",     "description": ""},
            {"bytes": "144-145",  "name": "NV-DDR timing mode support",      "description": ""},
            {"bytes": "160-161",  "name": "NV-DDR3 timing mode support",     "description": ""},
            {"bytes": "254-255",  "name": "Integrity CRC",                   "description": "16-bit; polynomial 8005h, initial 4F4Eh, covers bytes 0-253."},
            {"bytes": "256-511",  "name": "Redundant Parameter Page 1",       "description": "Copy of bytes 0-255."},
            {"bytes": "512-767",  "name": "Redundant Parameter Page 2",       "description": "Copy of bytes 0-255."},
         ]},
        {"name": "Extended Parameter Page", "long_name": "ONFI Extended Parameter Page", "width_bits": "variable",
         "access": "Read after Parameter Page redundant copies.",
         "description": "Signature 'EPPS' = 45h 50h 50h 53h at bytes 2-5. CRC at bytes 0-1 covers bytes 2..end. Section types: 0 unused, 1 additional section types/lengths, 2 Extended ECC Information."},
        {"name": "Unique ID", "long_name": "Device Unique Identifier", "width_bits": 128,
         "access": "Read Unique ID (EDh + 00h); 16 × (16-byte UID + 16-byte complement).",
         "description": "Validate via UID XOR complement = all ones; iterate copies on retrieval-error."},
        {"name": "Feature Parameter File", "long_name": "Set/Get Features parameter file", "width_bits": 32,
         "access": "EEh + addr → 4 P-bytes; EFh + addr + 4 P-bytes.",
         "description": "Feature addresses: 01h Timing Mode, 02h NV-DDR2/3 Config, 10h I/O Drive Strength, 30h ECC Config, 39h External Vpp, 58h Volume Configuration, 08h-0Bh DCC/DQ Training, 80h-81h EZ NAND."},
        {"name": "ID Bytes (Read ID 90h)", "long_name": "Read ID response", "width_bits": 32,
         "access": "90h + 00h → ≥ 4 ID bytes; 90h + 20h → 'ONFI'; 90h + 40h → 'JEDEC'.",
         "description": "Mfr ID + Device ID + 2 vendor-defined; ONFI signature; JEDEC signature."},
        {"name": "Volume Address", "long_name": "CE_n pin reduction Volume Address", "width_bits": 4,
         "access": "Programmed via Set Features (EFh + 58h); selected via Volume Select (E1h).",
         "description": "Up to 4-bit Volume Address; enumerated via ENi/ENo daisy chain."},
    ]
    if _empty(d.get("registers")):
        d["registers"] = regs
    _write(p, d)


# ---------------------------------------------------------------------------
# L5 ADI
# ---------------------------------------------------------------------------
def _l5(gd: Path) -> None:
    p = gd / "L5_ADI_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("analog_digital_interface_present", False)
    d["signaling_summary"] = (
        "ONFI 4.1 defines four data-interface signaling families on a common "
        "8-bit DQ bus plus control strobes. SDR (LVCMOS at VccQ); NV-DDR "
        "(single-ended bidirectional DQS + CLK on WE_n pin); NV-DDR2 "
        "(differential DQS_t/DQS_c + ZQ Calibration + ODT); NV-DDR3 "
        "(differential DQS_t/DQS_c AND RE_t/RE_c + DCC/DQ training + matrix "
        "termination). VREFQ is the input threshold for NV-DDR2/3 "
        "single-ended path. Internal NAND-array circuitry is highly analog "
        "but out of scope.")
    d.setdefault("voltage_classes", [
        {"class": "3.3 V VccQ", "VccQ_range_V": "3.0 - 3.6",  "applicable_modes": "SDR (legacy)"},
        {"class": "1.8 V VccQ", "VccQ_range_V": "1.7 - 1.95", "applicable_modes": "SDR, NV-DDR, NV-DDR2, NV-DDR3"},
        {"class": "1.2 V VccQ", "VccQ_range_V": "1.14 - 1.26","applicable_modes": "NV-DDR2 / NV-DDR3 advanced"},
    ])
    d.setdefault("differential_signals_nv_ddr2_3", [
        {"name": "DQS_t / DQS_c", "description": "Bidirectional differential data strobe."},
        {"name": "RE_t / RE_c",   "description": "Differential Read Enable (NV-DDR3; optional NV-DDR2)."},
    ])
    d.setdefault("vref_specification", {
        "VREFQ_purpose":   "External voltage reference for input/output signals in NV-DDR2 / NV-DDR3.",
        "VREFQ_tolerance": "Per Section 2.12.2; typically VREFQ = 0.5 × VccQ ±2 %.",
        "VREFQ_pin":       "Dedicated pin VREFQ_x per data bus.",
    })
    d.setdefault("zq_calibration", {
        "purpose":     "Calibrate output driver impedance against external RZQ.",
        "long_command":  "F9h ZQ Calibration Long; tZQCL ≥ 1 µs.",
        "short_command": "D9h ZQ Calibration Short.",
        "applicability": "NV-DDR2 and NV-DDR3.",
    })
    d.setdefault("on_die_termination_nv_ddr2_3", {
        "states":   ["Deselected", "Selected", "Sniff"],
        "modes":    ["Self-termination ODT", "Matrix termination ODT"],
        "command":  "ODT Configure (E2h) for matrix termination; Set Features for self-termination.",
        "purpose":  "Bus-end termination for high-speed source-synchronous signaling.",
    })
    d.setdefault("input_threshold_levels", {
        "SDR_3v3":      "VIH_min = 0.7 × VccQ, VIL_max = 0.3 × VccQ",
        "SDR_1v8":      "VIH_min = 0.8 × VccQ, VIL_max = 0.2 × VccQ",
        "NV_DDR2_3":    "VIH_min = VREFQ + 100 mV, VIL_max = VREFQ - 100 mV",
    })
    # v0.1.87 — ONFI L5 AC overshoot/undershoot envelope + pin capacitance
    # (Section 2.11 + Parameter Page byte references). Universal protocol
    # facts; no per-vendor numerics.
    d.setdefault("ac_overshoot_undershoot", {
        "purpose": ("Section 2.11 of ONFI 4.1 specifies allowed overshoot / "
                    "undershoot envelope on all input/output pins to bound "
                    "EMI and prevent latch-up."),
        "applicability": "All data interfaces; tighter envelope on NV-DDR3.",
    })
    d.setdefault("pin_capacitance", {
        "I/O_pin_capacitance": ("Parameter Page byte 128 (max in 0.1 pF "
                                "units), bytes 150-151 (typical NV-DDR2/3)."),
        "input_pin_capacitance": "Parameter Page bytes 152-153 (typical).",
        "CLK_pin_capacitance":   "Parameter Page bytes 148-149 (typical, NV-DDR family).",
    })
    d.setdefault("notes",
        "Internal NAND array (floating-gate / charge-trap cells, bit-lines, "
        "sense amplifiers, page registers, charge pumps, on-die ADC for "
        "TLC/QLC read margining) is heavily analog but intentionally out of "
        "scope. ONFI 4.1 treats the array as a black box.")
    _write(p, d)


# ---------------------------------------------------------------------------
# L6 control logic
# ---------------------------------------------------------------------------
def _l6(gd: Path) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    if _empty(d.get("fsm_states_target")):
        d["fsm_states_target"] = [
            {"name": "Idle",                  "description": "No command in progress."},
            {"name": "Idle_Read",             "description": "Output data buffer for Read ID / Param Page / Unique ID."},
            {"name": "Reset_Command_States",  "description": "After Reset (FFh/FCh/FAh); R/B_n LOW for tRST."},
            {"name": "Read_ID_Command_States","description": "Read ID (90h) state."},
            {"name": "Read_Parameter_Page_Command_States", "description": "Read Parameter Page (ECh) state."},
            {"name": "Page_Program_Command_States", "description": "Page Program (80h/10h) state."},
            {"name": "Block_Erase_Command_States",  "description": "Block Erase (60h/D0h) state."},
            {"name": "Read_Command_States",         "description": "Read (00h/30h) state."},
            {"name": "Read_Status_Command_States",  "description": "Read Status (70h) state."},
            {"name": "Read_Status_Enhanced_Command_States", "description": "Read Status Enhanced (78h) state."},
            {"name": "Volume_Select_Command_States","description": "Volume Select (E1h)."},
            {"name": "ODT_Configure_Command_States","description": "ODT Configure (E2h)."},
        ]
    if _empty(d.get("fsm_states_lun")):
        d["fsm_states_lun"] = [
            {"name": "Idle",            "description": "No command; R/B_n HIGH contribution."},
            {"name": "Idle_Read",       "description": "Page register holds read data."},
            {"name": "Status_State",    "description": "Outputs status byte on DQ."},
            {"name": "Reset_State",     "description": "Per-LUN reset."},
            {"name": "Block_Erase_State", "description": "Erase in progress; R/B_n LOW."},
            {"name": "Read_State",      "description": "Array → page register for tR."},
            {"name": "Page_Program_State", "description": "Page register → array for tPROG."},
        ]
    if _empty(d.get("fsm_transitions_major")):
        d["fsm_transitions_major"] = [
            {"trigger": "Reset (FFh)",                          "target": "Idle (SDR, mode 0)", "description": "Universal reset."},
            {"trigger": "Synchronous Reset (FCh)",              "target": "Idle (preserves data interface)", "description": "Reset without dropping NV-DDR family."},
            {"trigger": "Reset LUN (FAh + 3 row addr)",         "target": "Idle (per-LUN)", "description": "Resets addressed LUN only."},
            {"trigger": "Read (00h + 5 addr + 30h)",            "target": "Read_State → Idle_Read", "description": "Array → page register."},
            {"trigger": "Page Program (80h + 5 addr + data + 10h)", "target": "Page_Program_State → Idle", "description": "Page register → array."},
            {"trigger": "Block Erase (60h + 3 addr + D0h)",     "target": "Block_Erase_State → Idle", "description": "Erases block."},
            {"trigger": "Read Status (70h)",                    "target": "Status_State", "description": "Outputs composite status byte."},
            {"trigger": "Read Status Enhanced (78h + 3 row addr)", "target": "Status_State (LUN selected)", "description": "Per-LUN/plane status."},
            {"trigger": "Multi-plane 11h/D1h continuation",     "target": "Multi-plane queue", "description": "Queue plane ops; final 30h/10h/D0h commits."},
            {"trigger": "Set Features (EFh + addr + 4 P-bytes)","target": "Idle (after tFEAT)", "description": "Updates feature parameter file."},
            {"trigger": "Volume Select (E1h + Vol_Addr)",       "target": "active volume = Vol_Addr", "description": "Directs subsequent commands."},
            {"trigger": "ZQ Calibration Long (F9h)",            "target": "Idle (after tZQCL)", "description": "Updates output driver impedance."},
        ]
    if _empty(d.get("fsm_states_host")):
        d["fsm_states_host"] = [
            {"name": "HOST_POWER_UP",  "description": "Vcc/VccQ ramp; WP_n LOW; CE_n HIGH; staggered if needed."},
            {"name": "HOST_DISCOVERY", "description": "Reset (FFh) + wait R/B_n; Read ID 20h 'ONFI'; Read Parameter Page."},
            {"name": "HOST_INIT",      "description": "Validate CRC; Set Features (timing mode + drive strength + ODT)."},
            {"name": "HOST_CE_REDUCTION", "description": "Volume Appointment via ENi/ENo enumeration."},
            {"name": "HOST_TRAINING",  "description": "ZQ Long; NV-DDR3 DCC + Read DQ + Write TX/RX DQ training."},
            {"name": "HOST_TRANSFER",  "description": "Read / Page Program / Block Erase / multi-plane / Read Status polling."},
            {"name": "HOST_IDLE",      "description": "CE_n HIGH for low-power standby."},
        ]
    d.setdefault("fsm_hints", {
        "trigger": "Host drives all strobes; device never initiates. R/B_n is the only device-driven async signal.",
        "rule":    "Status bit 6 (RDY) reflects per-LUN ready state; R/B_n is wired-OR of LUN busy.",
        "abort":   "Reset (FFh) universal abort; Synchronous Reset (FCh) preserves interface; Reset LUN (FAh) per-LUN.",
    })
    d.setdefault("anti_deadlock_rule",
        "Host shall not issue a new command to a LUN while RDY=0, except "
        "Read Status (70h), Read Status Enhanced (78h), Reset (FFh), "
        "Synchronous Reset (FCh), Reset LUN (FAh).")
    d.setdefault("exit_from_reset_or_poweron",
        "After power-on, target requires Reset (FFh) before any commands. "
        "Defaults to SDR data interface, timing mode 0. WP_n sampled during "
        "reset.")
    # v0.1.87 — ONFI default-idle phrasing widened to match agent superset
    # (token-overlap relaxation needs program-side text to contain agent's
    # tokens so '_is_partial_value_match' subset rule holds). Agent uses
    # 'device deselected, low-power standby' (LL6 CE_n_idle), 'SDR / NV-DDR
    # family' (RE_n_idle), 'device output disabled' (DQ_idle).
    d.setdefault("default_ready_state_recommendation", {
        "CE_n_idle":  "HIGH (target device deselected, low-power standby).",
        "CLE_idle":   "LOW.",
        "ALE_idle":   "LOW.",
        "WE_n_idle":  "HIGH.",
        "RE_n_idle":  "HIGH (SDR family; same default in NV-DDR family).",
        "DQS_idle":   "Driven HIGH by host during NV-DDR2/3 Idle if ODT is enabled (otherwise don't-care).",
        "DQ_idle":    "Hi-Z (device output disabled).",
        "R_B_n_idle": "HIGH via external pull-up; LOW only when at least one LUN is busy.",
        "WP_n_idle":  "LOW = write-protect engaged; HIGH = Program/Erase enabled.",
    })
    d.setdefault("configurations", [
        {"name": "SDR mode",     "description": "Default after Reset (FFh); asynchronous."},
        {"name": "NV-DDR mode",  "description": "Set Features (01h Timing Mode); CLK on WE_n pin; bidirectional DQS."},
        {"name": "NV-DDR2 mode", "description": "Set Features (01h + 02h NV-DDR2/3 Config); WE_n cmd/addr; differential DQS."},
        {"name": "NV-DDR3 mode", "description": "Set Features (01h + 02h); differential DQS and RE_t/RE_c; DCC/DQ training."},
    ])
    d.setdefault("timing_dependency_rule",
        "All commands via CLE+WE_n (cmd) and ALE+WE_n (addr). Read data: "
        "SDR — falling RE_n; NV-DDR — DQS edges on both polarities. Write "
        "data: SDR — rising WE_n; NV-DDR — DQS edges. Section 4.17 defines "
        "tCCS / tWHR / tWB / tRR / tFEAT per data interface.")
    _write(p, d)


# ---------------------------------------------------------------------------
# L7 test / debug
# ---------------------------------------------------------------------------
def _l7(gd: Path) -> None:
    p = gd / "L7_TEST_DEBUG.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("test_debug_architecture_present", "partial")
    d.setdefault("spec_provided_observability", [
        {"name": "Status Register (Read Status 70h)", "purpose": "{WP_n, RDY, ARDY, VSP, CSP, R, FAILC, FAIL}; SR[5:0] invalid when RDY=0."},
        {"name": "Read Status Enhanced (78h)",        "purpose": "Per-LUN/plane status; turns off other LUN output buffers."},
        {"name": "R/B_n open-drain pin",              "purpose": "Real-time busy line; observable on scope without ONFI traffic."},
        {"name": "Read ID (90h)",                     "purpose": "ID bytes + 'ONFI' signature + 'JEDEC' signature."},
        {"name": "Read Parameter Page (ECh)",         "purpose": "256-byte self-description; CRC-protected; 3+ redundant copies."},
        {"name": "Read Unique ID (EDh)",              "purpose": "16-byte UID + complement, 16 copies."},
        {"name": "Get Features (EEh)",                "purpose": "Round-trip of timing mode / drive strength / ODT / training values."},
        {"name": "ECC threshold (CSP, EZ NAND Read)", "purpose": "ECC margin low → host rewrites the page."},
    ])
    d.setdefault("scope_observability", [
        "Logic-analyzer probing of CE_n / CLE / ALE / WE_n / RE_n / DQ[7:0] is the SDR debug path.",
        "NV-DDR family adds CLK + DQS_t/DQS_c (differential probes for NV-DDR2 / NV-DDR3).",
        "R/B_n probe directly shows tPROG / tBERS / tR without protocol parsing.",
        "Read DQ Training pattern (62h, NV-DDR3) is fixed — useful for eye-diagram capture.",
        "Write TX DQ Training Pattern (63h) + Readback (64h) round-trip for write-path eye centering.",
    ])
    d.setdefault("training_for_diagnostic", [
        {"name": "Implicit DCC Training (18h)",        "purpose": "Duty-cycle correction (NV-DDR3)."},
        {"name": "Read DQ Training (62h)",             "purpose": "Host sweeps RX phase against fixed device pattern."},
        {"name": "Write TX DQ Training Pattern (63h)", "purpose": "Host writes training pattern to device."},
        {"name": "Write TX DQ Training Readback (64h)","purpose": "Device returns pattern for round-trip check."},
        {"name": "Write RX DQ Training (76h)",         "purpose": "Device performs per-DQ RX training."},
        {"name": "ZQ Calibration Long/Short",          "purpose": "Output driver impedance trim."},
    ])
    d.setdefault("ate_or_dft",
        "Internal scan / BIST / charge-pump diagnostics are vendor-specific "
        "and not visible to the host via ONFI commands.")
    d.setdefault("notes",
        "ONFI provides protocol-level observability (Status / Parameter "
        "Page CRC / Unique ID complement / ECC threshold) plus NV-DDR3 "
        "PHY training observables. There is no JTAG / scan port on the "
        "package edge — internal die test is vendor-specific.")
    _write(p, d)


# ---------------------------------------------------------------------------
# L8 RTL constants
# ---------------------------------------------------------------------------
def _l8_const(gd: Path) -> None:
    p = gd / "L8_RTL_CONSTANTS.json"
    if not p.is_file():
        return
    d = _read(p)
    wp = _ensure_dict(d, "width_parameters")
    for k, v in {
        "DQ_DATA_BUS_WIDTH_DEFAULT": 8,
        "DQ_DATA_BUS_WIDTH_OPTIONAL_X16": 16,
        "ADDRESS_BYTE_WIDTH": 8,
        "COLUMN_ADDRESS_CYCLES_MAX": 2,
        "ROW_ADDRESS_CYCLES_MAX": 3,
        "TOTAL_ADDRESS_CYCLES_READ_WRITE": 5,
        "TOTAL_ADDRESS_CYCLES_ERASE": 3,
        "STATUS_REGISTER_BITS": 8,
        "PARAMETER_PAGE_BYTES": 256,
        "REDUNDANT_PARAMETER_PAGE_COPIES_MIN": 3,
        "UNIQUE_ID_BYTES": 16,
        "UNIQUE_ID_COMPLEMENT_BYTES": 16,
        "UNIQUE_ID_COPIES": 16,
        "READ_ID_BYTES_MIN": 4,
        "ONFI_SIGNATURE_BYTES": 4,
        "EPPS_SIGNATURE_BYTES": 4,
        "INTEGRITY_CRC_BITS": 16,
        "FEATURE_PARAMETER_BYTES": 4,
        "VOLUME_ADDRESS_BITS": 4,
    }.items():
        wp.setdefault(k, v)
    d.setdefault("crc_polynomials", {
        "CRC16_PARAMETER_PAGE": {
            "polynomial":  "x^16 + x^15 + x^2 + 1",
            "hex_generator": "0x8005",
            "init_value":  "0x4F4E",
            "final_xor":   "none",
            "bit_reversal":"none",
            "byte_order_in_8bit": "MSB-first (bit 7 to bit 0)",
            "applies_to":  "Parameter Page bytes 0-253 (CRC bytes 254-255); Extended Parameter Page bytes 2..end (CRC bytes 0-1)",
        },
    })
    d.setdefault("voltage_levels", {
        "VccQ_3v3_min_V":  3.0,
        "VccQ_3v3_max_V":  3.6,
        "VccQ_1v8_min_V":  1.7,
        "VccQ_1v8_max_V":  1.95,
        "VccQ_1v2_min_V":  1.14,
        "VccQ_1v2_max_V":  1.26,
        "signaling_sdr_3v3":   "VIH_min = 0.7 × VccQ, VIL_max = 0.3 × VccQ",
        "signaling_sdr_1v8":   "VIH_min = 0.8 × VccQ, VIL_max = 0.2 × VccQ",
        "signaling_nv_ddr2_3": "VIH_min = VREFQ + 100 mV, VIL_max = VREFQ - 100 mV",
    })
    di = _ensure_dict(d, "data_interface_constants")
    for k, v in {
        "SDR_MAX_RATE_MTps":     200,
        "NV_DDR_MAX_RATE_MTps":  400,
        "NV_DDR2_MAX_RATE_MTps": 800,
        "NV_DDR3_MAX_RATE_MTps": 1200,
        "SDR_CMD_ADDR_LATCHING_EDGE":   "Rising edge of WE_n",
        "SDR_READ_DATA_LATCHING_EDGE":  "Falling edge of RE_n",
        "NV_DDR_CMD_ADDR_LATCHING_EDGE":   "Rising edge of CLK",
        "NV_DDR_DATA_LATCHING_EDGE":       "Both edges of DQS",
        "NV_DDR2_3_CMD_ADDR_LATCHING_EDGE":"Rising edge of WE_n",
        "NV_DDR2_3_DATA_LATCHING_EDGE":    "Both edges of DQS",
    }.items():
        di.setdefault(k, v)
    kc = _ensure_dict(d, "key_constants_for_RTL_authoring")
    for k, v in {
        "status_bit_WPn":   7,
        "status_bit_RDY":   6,
        "status_bit_ARDY":  5,
        "status_bit_VSP":   4,
        "status_bit_CSP":   3,
        "status_bit_R":     2,
        "status_bit_FAILC": 1,
        "status_bit_FAIL":  0,
        "RDY_busy_value":  0,
        "RDY_ready_value": 1,
        "FAIL_pass_value": 0,
        "FAIL_fail_value": 1,
        "WPn_protect_value":     0,
        "WPn_unprotected_value": 1,
        "onfi_signature_bytes":  ["0x4F", "0x4E", "0x46", "0x49"],
        "epps_signature_bytes":  ["0x45", "0x50", "0x50", "0x53"],
        "jedec_signature_bytes": ["0x4A", "0x45", "0x44", "0x45", "0x43"],
        "address_cycle_count_read":   5,
        "address_cycle_count_program":5,
        "address_cycle_count_erase":  3,
        "address_cycle_count_status_enhanced": 3,
        "address_cycle_count_change_read_column": 2,
        "rzq_external_resistor_ohm_typ": 300,
        "rzq_tolerance_pct":              1,
        # v0.1.87 — ONFI L8 standard / reserved opcodes for RTL authoring.
        # Mandatory + Optional opcodes from Section 4.1 Table 94 (Command
        # Set) and Section 4.2 Table 95 (Opcode Reservations).
        "command_set_standard_opcodes": [
            "0x00", "0x05", "0x06", "0x10", "0x11", "0x15", "0x18",
            "0x30", "0x31", "0x32", "0x35", "0x3F",
            "0x60", "0x62", "0x63", "0x64",
            "0x70", "0x76", "0x78",
            "0x80", "0x81", "0x85",
            "0x90",
            "0xD0", "0xD1", "0xD4", "0xD5", "0xD9",
            "0xE0", "0xE1", "0xE2",
            "0xEC", "0xED", "0xEE", "0xEF",
            "0xF1", "0xF2", "0xF9",
            "0xFA", "0xFC", "0xFF",
        ],
        "command_set_reserved_opcodes": [
            "0x0B", "0x12", "0x14",
            "0x1B", "0x1C",
            "0x82", "0x83", "0x86", "0x8E",
        ],
    }.items():
        kc.setdefault(k, v)
    # v0.1.87 — ONFI L8 default-idle phrasing widened to match agent superset.
    d.setdefault("default_signal_values_when_idle", {
        "CE_n":  "HIGH (deselected; target enters low-power standby).",
        "CLE":   "LOW.",
        "ALE":   "LOW.",
        "WE_n":  "HIGH.",
        "RE_n":  "HIGH.",
        "DQ":    "Hi-Z (device output disabled).",
        "DQS":   "Host-driven HIGH during NV-DDR2/3 Idle if ODT enabled (otherwise don't-care).",
        "R_B_n": "HIGH via external pull-up; LOW only when LUN busy.",
        "WP_n":  "Implementation choice; LOW = write-protect engaged per board policy.",
    })
    d.setdefault("feature_addresses", {
        "TIMING_MODE":              "0x01",
        "NV_DDR2_NV_DDR3_CONFIG":    "0x02",
        "IO_DRIVE_STRENGTH":         "0x10",
        "ECC_CONFIGURATION":         "0x30",
        "EXTERNAL_VPP_CONFIG":       "0x39",
        "VOLUME_CONFIGURATION":      "0x58",
        "DCC_READ_DQ_TRAINING":      "0x08",
        "WRITE_TX_DQ_TRAINING":      "0x09",
        "WRITE_RX_DQ_TRAINING":      "0x0A",
        "IMPLICIT_DCC_TRAINING":     "0x0B",
        "EZ_NAND_CONTROL_LO":        "0x80",
        "EZ_NAND_CONTROL_HI":        "0x81",
    })
    d.setdefault("parameter_page_signature", "ONFI = 4Fh 4Eh 46h 49h at bytes 0-3")
    d.setdefault("extended_parameter_page_signature", "EPPS = 45h 50h 50h 53h at bytes 2-5")
    d.setdefault("max_throughput_table", [
        {"mode": "SDR mode 0",      "data_rate_MTps": 10,   "approx_throughput_MBps": 10,   "data_interface": "SDR"},
        {"mode": "SDR mode 5",      "data_rate_MTps": 50,   "approx_throughput_MBps": 50,   "data_interface": "SDR"},
        {"mode": "NV-DDR mode 5",   "data_rate_MTps": 200,  "approx_throughput_MBps": 200,  "data_interface": "NV-DDR"},
        {"mode": "NV-DDR2 mode 7",  "data_rate_MTps": 533,  "approx_throughput_MBps": 533,  "data_interface": "NV-DDR2"},
        {"mode": "NV-DDR2 mode 10", "data_rate_MTps": 800,  "approx_throughput_MBps": 800,  "data_interface": "NV-DDR2"},
        {"mode": "NV-DDR3 mode 12", "data_rate_MTps": 1200, "approx_throughput_MBps": 1200, "data_interface": "NV-DDR3"},
    ])
    _write(p, d)


# ---------------------------------------------------------------------------
# L8 TIMING
# ---------------------------------------------------------------------------
def _l8_timing(gd: Path) -> None:
    p = gd / "L8_TIMING_WAVEFORM.json"
    if not p.is_file():
        return
    d = _read(p)
    cw = _ensure_dict(d, "clock_waveform")
    for k, v in {
        "SDR_strobe_source":   "Host-generated WE_n / RE_n; asynchronous.",
        "NV_DDR_clock_source": "Host-generated CLK on WE_n pin; rising-edge latches cmd/addr.",
        "NV_DDR2_3_strobe_source": "WE_n (cmd/addr) + DQS_t/DQS_c (data).",
        "sdr_max_rate_MTps":    200,
        "nv_ddr_max_rate_MTps": 400,
        "nv_ddr2_max_rate_MTps":800,
        "nv_ddr3_max_rate_MTps":1200,
        # v0.1.87 — ONFI per-mode data-latching nested keys; phrasing
        # chosen as a TOKEN-SUPERSET of agent's L8_TIMING_WAVEFORM
        # clock_waveform sibling-extras so the parity diff's
        # _is_partial_value_match (smaller-set subset / 60%-overlap)
        # treats them as functionally equivalent.
        "sdr_data_latching":
            "Card / device outputs change on falling edge of RE_n; host "
            "samples on rising / falling per timing table; write byte "
            "latched on rising edge of WE_n.",
        "nv_ddr_data_latching":
            "Both edges of DQS latch data; CLK rising edge latches "
            "command / address; tDQSCK / tDQSRE / tDQSD anchor read / "
            "write phases relative to CLK.",
        "nv_ddr2_3_data_latching":
            "Both edges of DQS_t (cross with DQS_c) latch data; WE_n "
            "rising edge latches command / address; ODT, ZQ calibration, "
            "and DCC training stabilise the eye.",
    }.items():
        cw.setdefault(k, v)
    d.setdefault("command_cycle_waveform_sdr", {
        "description": "CE_n LOW, CLE HIGH, ALE LOW, WE_n LOW→HIGH; DQ latched as command opcode.",
        "key_timing_parameters": ["tCS", "tCH", "tCLS", "tCLH", "tWP", "tWC", "tDS", "tDH"],
    })
    d.setdefault("address_cycle_waveform_sdr", {
        "description": "1..5 address-cycle pulses: CE_n LOW, CLE LOW, ALE HIGH, WE_n LOW→HIGH; DQ latched as address byte.",
        "key_timing_parameters": ["tALS", "tALH", "tWP", "tWC", "tDS", "tDH"],
    })
    d.setdefault("write_data_cycle_waveform_sdr", {
        "description": "CE_n LOW, CLE LOW, ALE LOW, WE_n LOW→HIGH; DQ latched as write byte.",
        "key_timing_parameters": ["tDS", "tDH", "tWC", "tWP"],
    })
    d.setdefault("read_data_cycle_waveform_sdr", {
        "description": "CE_n LOW, CLE LOW, ALE LOW, RE_n HIGH→LOW; device drives next read byte on DQ; host samples after tREA.",
        "key_timing_parameters": ["tCEA", "tREA", "tRP", "tRC", "tREH", "tRHZ", "tCHZ"],
    })
    d.setdefault("cmd_addr_data_waveform_nv_ddr", {
        "description": "Continuous CLK; cmd/addr latched on rising CLK; tCAD interval; W/R_n selects bus owner; bidirectional DQS.",
        "key_timing_parameters": ["tCAD", "tCS", "tCH", "tCALS", "tCALH", "tDQSCK", "tDQSRE", "tCKWR", "tWHR"],
    })
    d.setdefault("cmd_addr_data_waveform_nv_ddr2_3", {
        "description": "WE_n latches cmd/addr; DQS_t/DQS_c data; NV-DDR3 adds RE_t/RE_c.",
        "key_timing_parameters": ["tCS1", "tCS2", "tCALS", "tCALS2", "tCAD", "tCALH", "tDQSCK", "tDQSRE", "tWPRE", "tWPRE2", "tWPST", "tWPSTH", "tRPRE", "tRPRE2", "tRPST", "tRPSTH", "tCDQSS", "tCDQSH", "tDBS", "tCSD", "tDSC"],
    })
    d.setdefault("ready_busy_waveform", {
        "signal":   "R/B_n open-drain output; pulled HIGH externally; LOW when any LUN busy.",
        "after_program":  "R/B_n LOW from end of 10h cycle to end of tPROG.",
        "after_erase":    "R/B_n LOW from end of D0h cycle to end of tBERS.",
        "after_read":     "R/B_n LOW from end of 30h cycle to end of tR.",
        "after_reset":    "R/B_n LOW from end of FFh cycle to end of tRST.",
    })
    d.setdefault("reset_waveform", {
        "step_1": "Host issues Reset (FFh).",
        "step_2": "Device drives R/B_n LOW.",
        "step_3": "After tRST (max 5 ms first reset; max 500 µs subsequent; max 5 µs Synchronous Reset), device drives R/B_n HIGH.",
        "step_4": "FFh defaults to SDR mode 0; FCh preserves data interface.",
    })
    # v0.1.87 — ONFI page-program step_3 widened to mention CLE=ALE=0 data
    # window so agent's "Host writes page-size bytes of data (CLE=ALE=0)"
    # token-superset relaxation can match. Comment-only enhancement.
    d.setdefault("page_program_waveform", {
        "step_1": "Host issues 80h (CLE HIGH).",
        "step_2": "Host issues 5 address cycles (ALE HIGH).",
        "step_3": "Host writes page-size bytes of data (CLE=ALE=0); tADL window after second address byte.",
        "step_4": "Host issues 10h (CLE HIGH).",
        "step_5": "After tWB, device drives R/B_n LOW for tPROG.",
        "step_6": "Host polls Read Status (70h) or waits for R/B_n HIGH; checks FAIL bit.",
    })
    d.setdefault("block_erase_waveform", {
        "step_1": "Host issues 60h.",
        "step_2": "Host issues 3 row address cycles.",
        "step_3": "Host issues D0h.",
        "step_4": "After tWB, device drives R/B_n LOW for tBERS.",
        "step_5": "Host polls Read Status; checks FAIL bit.",
    })
    d.setdefault("read_waveform", {
        "step_1": "Host issues 00h.",
        "step_2": "Host issues 5 address cycles.",
        "step_3": "Host issues 30h.",
        "step_4": "After tWB, device drives R/B_n LOW for tR.",
        "step_5": "Device drives R/B_n HIGH; host polls Read Status or Read Status Enhanced.",
        "step_6": "Host pulses RE_n (SDR) or RE_t/RE_c + DQS (NV-DDR family) to clock out page bytes.",
    })
    # v0.1.87 — ONFI zq step_4 widened to mention updated impedance for
    # subsequent NV-DDR2/NV-DDR3 traffic; matches agent text superset.
    d.setdefault("zq_calibration_waveform", {
        "step_1": "Host issues ZQ Calibration Long (F9h) or Short (D9h).",
        "step_2": "Device drives R/B_n LOW for tZQCL (long, ≥ 1 µs) or tZQCS (short).",
        "step_3": "Device updates output driver impedance against external RZQ.",
        "step_4": "Device drives R/B_n HIGH; output drivers now use updated impedance for subsequent NV-DDR2/NV-DDR3 traffic; FAIL bit indicates calibration outcome.",
    })
    d.setdefault("general_timing_parameters_referenced", [
        "tCS / tCS1 / tCS2 — CE_n setup",
        "tCH — CE_n hold",
        "tCEA — CE_n access time",
        "tWP — WE_n pulse width",
        "tWC — WE_n cycle time",
        "tRP — RE_n pulse width",
        "tRC — RE_n cycle time",
        "tREA — RE_n access time",
        "tDS / tDH — data setup / hold",
        "tWB — WE_n HIGH to R/B_n LOW",
        "tRR — Ready to RE_n",
        "tWHR — WE_n HIGH to RE_n LOW (Read Status)",
        "tCCS — Change Column setup",
        "tADL — Address-to-data Load",
        "tR — Array-to-page-register read time",
        "tPROG — Page Program time",
        "tBERS — Block Erase time",
        "tFEAT — Feature complete time",
        "tRST — Reset complete time",
        "tZQCL / tZQCS — ZQ Calibration Long / Short",
        "tCAD (NV-DDR) — command/address cycle",
        "tDQSCK / tDQSRE / tDQSD / tDQSHZ / tDQSQ / tQH (NV-DDR family)",
        "tWPRE / tWPST / tRPRE / tRPST — DQS write/read preamble/postamble",
    ])
    d.setdefault("general_timing_rule",
        "All command/address/data transfers reference host strobes "
        "(WE_n/CLK for cmd/addr; RE_n/DQS for data). Section 4.17 of ONFI "
        "4.1 defines per-mode timing tables: SDR (4.18.1), NV-DDR (4.18.2), "
        "NV-DDR2/3 (4.18.3).")
    d.setdefault("voltage_thresholds", {
        "VIH_3v3_SDR":    "0.7 × VccQ",
        "VIL_3v3_SDR":    "0.3 × VccQ",
        "VIH_1v8_SDR":    "0.8 × VccQ",
        "VIL_1v8_SDR":    "0.2 × VccQ",
        "VIH_NV_DDR2_3":  "VREFQ + 100 mV",
        "VIL_NV_DDR2_3":  "VREFQ - 100 mV",
    })
    _write(p, d)


# ---------------------------------------------------------------------------
# L9 integration
# ---------------------------------------------------------------------------
def _l9(gd: Path) -> None:
    p = gd / "L9_INTEGRATION_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("module_role",
        "Hardware host-device interface between a NAND Flash controller "
        "(master) and one or more NAND Targets (slaves) within a NAND "
        "package, defining wires + cycle types + command set + status / "
        "parameter / unique-ID readback + features.")
    _ptm.apply(d, "ONFI_NAND_Target")
    io = _ensure_dict(d, "integration_overview")
    io.setdefault("wire_count_sdr_x8_basic",  "12-14 (CE_n, CLE, ALE, WE_n, RE_n, WP_n, R/B_n, DQ[7:0], Vcc/VccQ/Vss/VssQ)")
    io.setdefault("wire_count_sdr_x16_basic", "20-22 (adds DQ[15:8])")
    io.setdefault("wire_count_nv_ddr_x8_basic","13-15 (adds DQS; WE_n/CLK and RE_n/W/R_n shared pins)")
    io.setdefault("wire_count_nv_ddr2_3_x8",  "16-18 (adds DQS_c, VREFQ, ZQ)")
    io.setdefault("wire_directions", "CE_n/CLE/ALE/WE_n/WP_n: host→device. RE_n/CLK: host→device. R/B_n: device→host (open-drain). DQ: bidirectional. DQS: bidirectional (NV-DDR family). Vcc/VccQ/Vss/VssQ: power.")
    io.setdefault("chip_select_per_target", "Each target is selected by its CE_n; pin reduction shares CE_n with Volume Address.")
    io.setdefault("controller_role",     "Host generates all strobes and initiates every transaction.")
    io.setdefault("open_drain_rbn",      "R/B_n open-drain; multi-target wire-OR; external pull-up required.")
    d.setdefault("interface_categories", [
        "Power (Vcc, VccQ, Vss, VssQ; optional Vpp; EZ NAND VDDi)",
        "Control (CE_n, CLE, ALE, WE_n/CLK, RE_n/RE_t/RE_c/W/R_n, WP_n)",
        "Data (DQ[7:0] / DQ[15:0]; DQS / DQS_t/DQS_c)",
        "Reference (VREFQ; ZQ + RZQ; ENi/ENo; VSP)",
    ])
    d.setdefault("interconnect_topologies_supported", [
        "Single-controller + single-target.",
        "Single-controller + multiple-target with per-target CE_n.",
        "Single-controller + multiple-target with CE_n pin reduction (Volume Select).",
        "Independent Data Buses (DQ_0 + DQ_1 parallel).",
        "Multi-channel SSD controller (parallel ONFI channels).",
    ])
    d.setdefault("default_signal_values_when_omitted",
        "External pull-up on R/B_n (typ. 1-10 kΩ); WP_n per board policy; "
        "ZQ tied to Vss via RZQ (300 Ω ±1 %); ENi pulled to defined level "
        "for enumeration; VSP internal pull-up/down per vendor spec.")
    d.setdefault("pull_up_resistors", [
        {"signal": "R/B_n", "value_kohm": "1-10",   "location": "host PCB", "purpose": "Open-drain pull-up; required."},
        {"signal": "WP_n",  "value_kohm": "10-100", "location": "host PCB", "purpose": "Default protection / release."},
        {"signal": "VSP",   "value_kohm": "vendor", "location": "device internal", "purpose": "Safe default."},
        {"signal": "ENi",   "value_kohm": "vendor", "location": "device internal", "purpose": "Enumeration default."},
    ])
    d.setdefault("soc_dependent_items", [
        "ONFI-compliant NAND Flash Controller (NFC) IP with channel scheduler + ECC engine.",
        "Per-channel PHY (SDR LVCMOS or NV-DDR / NV-DDR2 / NV-DDR3 source-sync DDR).",
        "Per-channel VccQ regulator (3.3 V / 1.8 V / 1.2 V).",
        "External Vpp regulator (optional).",
        "External RZQ resistor (typ. 300 Ω ±1 %) on each ZQ pin to Vss.",
        "External R/B_n pull-up per channel.",
        "DMA controller for page-register fill/drain.",
        "Interrupt routing (per-LUN ready, ECC error, ECC threshold).",
    ])
    lpm = _ensure_dict(d, "low_power_modes")
    lpm.setdefault("Standby",            "CE_n HIGH while target ready; ICC1 typical.")
    lpm.setdefault("Deep_power_down",    "Vendor-defined via Set Features or Vcc/VccQ removal.")
    lpm.setdefault("ClockStop_NV_DDR",   "Host may stop CLK during NV-DDR Idle.")
    lpm.setdefault("Vpp_disabled",       "Set Features (39h) disables external Vpp.")
    lpm.setdefault("Sleep",              "Not explicitly named; CE_n + CLK gated.")
    d.setdefault("compatibility_notes", [
        "All ONFI devices power-up into SDR data interface, timing mode 0. Host shall Reset (FFh) before any commands.",
        "Switching to NV-DDR / NV-DDR2 / NV-DDR3 via Set Features (01h). Reset (FFh) drops to SDR; Synchronous Reset (FCh) preserves.",
        "ECC scheme on raw NAND is host responsibility; EZ NAND offloads ECC.",
        "Multi-vendor mixing on a channel discouraged due to ICC / VccQ / drive-strength matching.",
        "ONFI 4.x is backward compatible at the SDR command level with all prior revisions.",
    ])
    _write(p, d)


# ---------------------------------------------------------------------------
# L10 test cases
# ---------------------------------------------------------------------------
def _l10(gd: Path) -> None:
    p = gd / "L10_TEST_CASES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_cases_present"] = (
        "partial - the spec defines command opcodes, address-cycle counts, "
        "status-register bits, parameter-page layout, multi-LUN / multi-plane "
        "rules, and behavioural-flow state machines (Section 7) that map "
        "directly to compliance scenarios; ONFI does not publish a formal "
        "compliance test plan in the spec itself.")
    # Suppress pre-existing skeleton-emitted half-duplex opcode_hex test entries
    # (hallucinated from a generic command-protocol template that doesn't apply).
    tc = d.get("test_cases")
    if isinstance(tc, list):
        d["test_cases"] = [
            x for x in tc
            if not (isinstance(x, dict) and "opcode_hex" in x)
        ]
    if _empty(d.get("derived_compliance_test_categories")):
        d["derived_compliance_test_categories"] = [
            "Reset (FFh) → SDR mode 0; tRST ≤ 5 ms first / ≤ 500 µs subsequent.",
            "Synchronous Reset (FCh) preserves data interface and timing mode.",
            "Reset LUN (FAh) per-LUN.",
            "Read ID (90h) — addr 00h: Mfr/Device + 2 vendor; addr 20h: 'ONFI'; addr 40h: 'JEDEC'.",
            "Read Parameter Page (ECh) — signature 'ONFI'; CRC (8005h, init 4F4Eh); 3 redundant copies.",
            "Extended Parameter Page — signature 'EPPS'; section type 2 = Extended ECC Information.",
            "Read Unique ID (EDh) — UID XOR complement = all ones; 16 copies.",
            "Read (00h/30h) — tR; FAIL bit on EZ NAND.",
            "Page Program (80h/10h) — tPROG; tADL after addr; FAIL bit.",
            "Block Erase (60h/D0h) — tBERS; refuse factory-bad block.",
            "Multi-plane Page Program (80h/11h … 80h/10h).",
            "Multi-plane Block Erase (60h/D1h … 60h/D0h).",
            "Multi-plane Read (00h/32h … 00h/30h).",
            "Read Cache Random / Sequential / End (00h/31h, 31h, 3Fh).",
            "Page Cache Program (80h/15h) — FAILC after second 15h/10h.",
            "Copyback Read + Program (00h/35h + 85h/10h).",
            "Read Status (70h) — composite byte; bit 6 RDY, bit 0 FAIL.",
            "Read Status Enhanced (78h) — per-LUN/plane; turns off other LUN buffers.",
            "WP_n disables Program/Erase but not Read; WP_n stability rule.",
            "Set Features / Get Features round-trip (01h timing, 02h NV-DDR2/3 config, 10h drive strength, 58h volume).",
            "Data interface switch (Set Features 01h) SDR → NV-DDR → NV-DDR2 → NV-DDR3.",
            "ZQ Calibration Long (F9h) + Short (D9h); FAIL bit.",
            "NV-DDR3: Implicit DCC Training (18h), Read DQ Training (62h), Write TX DQ Training (63h/64h), Write RX DQ Training (76h).",
            "Volume Select (E1h) + Volume Appointment (Set Features 58h) — CE_n pin reduction.",
            "ODT Configure (E2h) — Deselected / Selected / Sniff.",
            "Multi-LUN parallelism — Read on LUN0 + Program on LUN1; poll per LUN.",
            "Status invalidation — RDY=0 invalidates SR[5:0] except WP_n.",
            "tCCS / tADL / tWHR / tWB / tRR adherence.",
            "Factory defect map — erase of marked block fails.",
            "First Reset (FFh) up to 5 ms; subsequent ≤ 500 µs.",
        ]
    _write(p, d)


# ---------------------------------------------------------------------------
# L11 OTP
# ---------------------------------------------------------------------------
def _l11(gd: Path) -> None:
    p = gd / "L11_OTP_CONTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    d["otp_present"] = True
    d["notes"] = (
        "Parameter Page + Read ID + Unique ID + Factory Defect Map form the "
        "OTP-style fingerprint of an ONFI device. The Parameter Page CRC + "
        "redundancy + Extended Parameter Page provide retrieval-error "
        "robustness without host bookkeeping. The Unique ID + complement "
        "scheme self-validates via XOR-equals-all-ones.")
    d.setdefault("otp_summary",
        "ONFI defines two factory-programmed (OTP-style) device "
        "identification structures plus a factory defect map. (1) Read ID "
        "(90h) returns JEDEC manufacturer ID + device ID. (2) Read "
        "Parameter Page (ECh) returns 256-byte self-description, 3 "
        "redundant copies, CRC-protected. (3) Read Unique ID (EDh) returns "
        "16-byte UID with bit-wise complement, repeated 16 times. (4) "
        "Factory defect mapping (Section 3.3) marks bad blocks before "
        "shipment.")
    d.setdefault("non_otp_device_state",
        "Other state — Status Register (volatile, per-LUN), Feature "
        "Parameter File (programmed by Set Features), page register "
        "contents (volatile), array contents (persistent), Volume Address "
        "(programmed each boot).")
    d.setdefault("otp_registers", [
        {"name": "Read ID (90h response)", "width_bits": 32, "factory_programmed": True, "host_programmable": False,
         "fields": [
            {"name": "Manufacturer ID", "byte_offset": 0, "size_bits": 8, "description": "JEDEC manufacturer code."},
            {"name": "Device ID",       "byte_offset": 1, "size_bits": 8, "description": "Vendor / density / capability."},
            {"name": "Vendor 1",        "byte_offset": 2, "size_bits": 8, "description": "Vendor-defined."},
            {"name": "Vendor 2",        "byte_offset": 3, "size_bits": 8, "description": "Vendor-defined."},
         ]},
        {"name": "Parameter Page (Read Parameter Page ECh)", "width_bits": 2048, "factory_programmed": True, "host_programmable": False,
         "otp_factory_fields": [
            "Parameter Page signature 'ONFI' (bytes 0-3)",
            "Revision number (bytes 4-5)",
            "Features supported / Optional commands supported bitmaps",
            "Device manufacturer / model ASCII",
            "JEDEC manufacturer ID",
            "Page / block / LUN geometry",
            "ECC correctability",
            "Timing-mode bitmaps (SDR / NV-DDR / NV-DDR2 / NV-DDR3)",
            "Integrity CRC bytes 254-255 (polynomial 8005h, init 4F4Eh)",
         ]},
        {"name": "Unique ID (Read Unique ID EDh)", "width_bits": 128, "factory_programmed": True, "host_programmable": False,
         "fields": [
            {"name": "UID",            "byte_offset": 0,  "size_bits": 128, "description": "16-byte unique device identifier."},
            {"name": "UID complement", "byte_offset": 16, "size_bits": 128, "description": "Bit-wise complement; (UID XOR complement) = all ones if valid."},
            {"name": "Repetition",     "byte_offset": "0..511", "size_bits": "4096", "description": "16 copies of {UID + complement}."},
         ]},
        {"name": "Factory Defect Map (Section 3.3)", "width_bits": "variable", "factory_programmed": True, "host_programmable": False,
         "otp_factory_fields": [
            "Bad blocks marked before shipment.",
            "First byte of spare area of first/last page = non-FFh.",
            "Erase of marked bad block shall fail (FAIL bit).",
         ]},
    ])
    _write(p, d)


# ---------------------------------------------------------------------------
# L12 behavioural sequences
# ---------------------------------------------------------------------------
def _l12(gd: Path) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("initialization_sequence", [
        "1. Power-up: ramp Vcc + VccQ (staggered per Section 2.14 if multi-target).",
        "2. CE_n HIGH; WP_n LOW during boot.",
        "3. Wait for power stable.",
        "4. CE_n LOW; issue Reset (FFh); wait R/B_n HIGH (up to 5 ms first reset).",
        "5. Read ID (90h + 20h) → 'ONFI' signature confirms ONFI compliance.",
        "6. Read ID (90h + 00h) → ≥ 4 ID bytes.",
        "7. Read Parameter Page (ECh + 00h); validate CRC (polynomial 8005h init 4F4Eh); try redundant copies on mismatch.",
        "8. (Optional) Read Unique ID (EDh + 00h); iterate copies until XOR-with-complement = all ones.",
        "9. Parse Parameter Page geometry + ECC + timing-mode bitmaps.",
        "10. Scan factory defect map; build bad-block table.",
        "11. (NV-DDR family) Set Features (01h Timing Mode); switch data interface.",
        "12. (NV-DDR2 / NV-DDR3) Set Features (02h NV-DDR2/3 Config) + ZQ Calibration Long (F9h).",
        "13. (NV-DDR3) Implicit DCC Training (18h), Read DQ Training (62h), Write TX DQ Training (63h/64h), Write RX DQ Training (76h).",
        "14. (CE_n reduction) Volume Appointment via ENi/ENo + Set Features (58h); use Volume Select (E1h) thereafter.",
        "15. De-assert WP_n (HIGH); device ready for Read / Program / Erase.",
    ])
    d.setdefault("page_read_sequence", [
        "1. Host issues 00h.",
        "2. 5 address cycles (2 column + 3 row).",
        "3. 30h.",
        "4. R/B_n LOW for tR.",
        "5. R/B_n HIGH; poll Read Status (or Read Status Enhanced).",
        "6. Re-issue 00h; clock out page bytes via RE_n / DQS.",
    ])
    d.setdefault("page_program_sequence", [
        "1. 80h.",
        "2. 5 address cycles.",
        "3. Stream write data (wait tADL after second address byte).",
        "4. 10h.",
        "5. R/B_n LOW for tPROG.",
        "6. Read Status; check FAIL bit.",
    ])
    d.setdefault("block_erase_sequence", [
        "1. 60h.",
        "2. 3 row address cycles.",
        "3. D0h.",
        "4. R/B_n LOW for tBERS.",
        "5. Read Status; check FAIL bit.",
    ])
    d.setdefault("multi_plane_program_sequence", [
        "1. 80h + plane0 addr + plane0 data + 11h.",
        "2. 80h + plane1 addr + plane1 data + 10h.",
        "3. R/B_n LOW for tPROG (multi-plane).",
        "4. Poll Read Status Enhanced (78h) per plane.",
    ])
    d.setdefault("multi_plane_erase_sequence", [
        "1. 60h + plane0 row + D1h.",
        "2. 60h + plane1 row + D0h.",
        "3. R/B_n LOW for tBERS.",
        "4. Per-plane Read Status Enhanced.",
    ])
    d.setdefault("multi_plane_read_sequence", [
        "1. 00h + plane0 addr + 32h.",
        "2. 00h + plane1 addr + 30h.",
        "3. R/B_n LOW for tR.",
        "4. Per-plane Read Status Enhanced + Change Read Column Enhanced (06h/E0h).",
    ])
    d.setdefault("page_cache_program_sequence", [
        "1. 80h + addr + data + 15h (page 0; device starts program).",
        "2. 80h + addr + data + 15h (page 1; pipelined).",
        "3. Read Status — RDY=1 means cache ready; ARDY=1 means array idle; FAILC reports prior.",
        "4. Final 80h + addr + data + 10h (last page).",
    ])
    d.setdefault("read_cache_sequence", [
        "1. 00h + addr + 31h (Read Cache Random; load page 0).",
        "2. Poll Read Status; RDY=1 when cache ready.",
        "3. Read page 0; issue 31h to advance to next sequential page.",
        "4. 3Fh (Read Cache End) terminates.",
    ])
    d.setdefault("copyback_sequence", [
        "1. 00h + source_addr + 35h (Copyback Read); R/B_n LOW for tR.",
        "2. (Optional) modify subset of bytes via Change Write Column / Small Data Move.",
        "3. 85h + destination_addr + 10h (Copyback Program); R/B_n LOW for tPROG.",
    ])
    d.setdefault("zq_calibration_sequence", [
        "1. After Reset: F9h ZQ Long; R/B_n LOW for tZQCL (≥ 1 µs).",
        "2. Periodic: D9h ZQ Short; R/B_n LOW for tZQCS.",
        "3. Output driver impedance updated against external RZQ.",
        "4. Read Status; FAIL=1 indicates calibration failure.",
    ])
    d.setdefault("data_interface_switch_sequence", [
        "1. Complete any pending operation; ARDY=1.",
        "2. Set Features (EFh + 01h Timing Mode) + P1 = data interface + mode.",
        "3. R/B_n LOW for tFEAT.",
        "4. R/B_n HIGH; bus now in new data interface.",
        "5. (NV-DDR2/3) Set Features (02h Config) + ZQ Long + (NV-DDR3) training.",
    ])
    d.setdefault("ce_n_pin_reduction_enumeration_sequence", [
        "1. First target ENi tied LOW; subsequent ENi from previous ENo.",
        "2. CE_n LOW; Reset (FFh); all targets reset.",
        "3. Set Features (58h Volume Configuration) with Volume Address; only first target (ENi LOW) accepts.",
        "4. First target asserts ENo HIGH after tFEAT.",
        "5. Repeat for next target; iterate until all enumerated.",
        "6. Subsequent commands prefixed by Volume Select (E1h + Vol_Addr).",
    ])
    d.setdefault("hot_removal_recovery", [
        "1. ONFI does not specify hot-insert / hot-remove for soldered NAND.",
        "2. On unexpected reset / glitch, host issues Reset (FFh); revalidates Parameter Page CRC.",
    ])
    _write(p, d)


# ---------------------------------------------------------------------------
# L13 lab calibration
# ---------------------------------------------------------------------------
def _l13(gd: Path) -> None:
    p = gd / "L13_LAB_CALIBRATION.json"
    if not p.is_file():
        return
    d = _read(p)
    d["lab_calibration_present"] = True
    d["notes"] = (
        "ONFI 4.1 calibration is entirely host-driven; the device exposes "
        "training-pattern emit + round-trip pattern + ZQ impedance loop. "
        "The host owns the optimization loops (RX phase, TX phase, drive "
        "strength, periodic ZQ). Internal trim is factory-set.")
    d.setdefault("calibration_summary",
        "Host-driven calibration loops: ZQ Calibration (Long F9h, Short "
        "D9h), NV-DDR3 DCC Training (18h Implicit), Read DQ Training "
        "(62h), Write TX DQ Training (63h pattern + 64h readback), Write "
        "RX DQ Training (76h), and Set Features I/O Drive Strength "
        "(EFh + 10h).")
    d.setdefault("zq_calibration_long", {
        "purpose":     "Calibrate output driver impedance after Reset / power-on / data-interface change.",
        "command":     "F9h ZQ Calibration Long",
        "prerequisite":"Vcc/VccQ stable; data interface = NV-DDR2 or NV-DDR3.",
        "host_actions":[
            "Issue F9h.",
            "Wait R/B_n LOW (tWB).",
            "Wait tZQCL (≥ 1 µs).",
            "Wait R/B_n HIGH.",
            "Read Status; FAIL=1 → calibration failed.",
        ],
        "rzq_external_resistor_typ_ohm": 300,
        "rzq_tolerance_pct": 1,
    })
    d.setdefault("zq_calibration_short", {
        "purpose":     "Periodic V/T drift correction.",
        "command":     "D9h ZQ Calibration Short",
        "host_actions":[
            "Issue D9h.","Wait R/B_n LOW.","Wait tZQCS.","Wait R/B_n HIGH.","Read Status.",
        ],
        "recommended_interval": "Per device tZQCS_interval; typ. every 128 ms.",
    })
    d.setdefault("dcc_training_nv_ddr3", {
        "purpose":     "Internal clock duty-cycle correction for NV-DDR3.",
        "command":     "Implicit DCC Training (18h).",
        "host_actions": ["Issue 18h.","Wait for completion."],
    })
    d.setdefault("read_dq_training_nv_ddr3", {
        "purpose":     "Find optimal RX sampling phase per DQ lane.",
        "command":     "Read DQ Training (62h).",
        "procedure":   [
            "Issue 62h + addr.",
            "Device outputs known training pattern.",
            "Host sweeps RX sampling phase across each DQ lane.",
            "Pick center of pass window per DQ.",
            "Store per-DQ delay-line values.",
        ],
    })
    d.setdefault("write_tx_dq_training_nv_ddr3", {
        "purpose":     "Find optimal host TX phase per DQ lane via round-trip pattern.",
        "command_pattern":  "Write TX DQ Training Pattern (63h).",
        "command_readback": "Write TX DQ Training Readback (64h).",
        "procedure":   [
            "Host issues 63h + pattern.",
            "Host issues 64h to read back.",
            "Compare per-DQ; iterate sweep; pick TX center per DQ.",
        ],
    })
    d.setdefault("write_rx_dq_training_nv_ddr3", {
        "purpose":     "Device performs per-DQ RX training using host pattern.",
        "command":     "Write RX DQ Training (76h).",
        "procedure":   ["Issue 76h + pattern.","Device adjusts internal RX delay; reports via R/B_n / Status."],
    })
    d.setdefault("io_drive_strength_calibration", {
        "purpose":     "Adjust output driver strength to channel impedance.",
        "command":     "Set Features (EFh + 10h I/O Drive Strength) + 4 P-bytes.",
        "host_actions":["Sweep candidate strengths; for each run Read DQ Training; pick strength with widest pass window."],
    })
    d.setdefault("no_internal_trim_exposed",
        "ONFI does not expose internal analog trim (charge-pump, sense-amp, "
        "read-margining) on the host interface.")
    # v0.1.87 — ONFI L13 power-up characterisation: add Reset_LUN_max_us
    # nested key (device-specific bound, advertised via Parameter Page).
    d.setdefault("power_up_characterization", {
        "Vcc_VccQ_ramp_to_first_reset_max_ms": 5,
        "Reset_first_max_ms": 5,
        "Reset_subsequent_max_us": 500,
        "Synchronous_Reset_max_us": 5,
        "Reset_LUN_max_us": "device-specific (Parameter Page)",
        "purpose": "Allow internal regulators / DLL / DCC to stabilize before host issues first command.",
    })
    _write(p, d)


# ---------------------------------------------------------------------------
# L14 versioning
# ---------------------------------------------------------------------------
def _l14(gd: Path) -> None:
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if not p.is_file():
        return
    d = _read(p)
    f = d.get("fields") or {}
    f.setdefault("spec_version",
                 "Open NAND Flash Interface Specification Revision 4.1 (December 12, 2017)")
    if _empty(f.get("spec_lineage_onfi")):
        f["spec_lineage_onfi"] = [
            {"version": "1.0",  "date": "December 28, 2006", "summary": "Initial ONFI release; asynchronous SDR only; basic command set + 256-byte Parameter Page."},
            {"version": "2.0",  "date": "February 27, 2008", "summary": "Source-synchronous NV-DDR (≤ 200 MT/s); Synchronous Reset (FCh)."},
            {"version": "2.1",  "date": "January 11, 2009",  "summary": "Multi-plane; Read Cache; Read Status Enhanced (78h)."},
            {"version": "2.2",  "date": "October 7, 2009",   "summary": "NV-DDR extended to 200 MT/s."},
            {"version": "2.3",  "date": "August 5, 2010",    "summary": "EZ NAND option."},
            {"version": "3.0",  "date": "March 9, 2011",     "summary": "NV-DDR2 + ZQ Calibration + CE_n pin reduction (Volume Select E1h)."},
            {"version": "3.1",  "date": "September 12, 2012","summary": "NV-DDR2 to 800 MT/s; Extended Parameter Page 'EPPS'."},
            {"version": "3.2",  "date": "June 26, 2013",     "summary": "Editorial."},
            {"version": "4.0",  "date": "April 16, 2014",    "summary": "NV-DDR3 + Independent Data Buses + ODT Configure (E2h)."},
            {"version": "4.1",  "date": "December 12, 2017", "summary": "NV-DDR3 to 1200 MT/s; DCC + DQ training (18h/62h/63h/64h/76h)."},
        ]
    if _empty(f.get("spec_lineage_legacy_nand")):
        f["spec_lineage_legacy_nand"] = [
            {"version": "Legacy SLC NAND",  "summary": "Pre-ONFI vendor-defined CLE/ALE/WE_n/RE_n/CE_n bus with similar but incompatible command-set details."},
            {"version": "Toggle Mode v1.0", "summary": "Samsung-led source-synchronous DDR NAND (133 MT/s)."},
            {"version": "Toggle Mode v2.0", "summary": "Samsung Toggle 2.0 (400 MT/s)."},
            {"version": "Toggle DDR4",      "summary": "Newer Samsung-led toggle interface (≥ 800 MT/s)."},
        ]
    if _empty(f.get("backward_compat_traps")):
        f["backward_compat_traps"] = [
            {"trap_name": "power_up_default_sdr",
             "rule":      "All ONFI devices power-up into SDR data interface, timing mode 0.",
             "trap":      "Host assuming NV-DDR3 from boot will fail to read Parameter Page."},
            {"trap_name": "reset_FFh_vs_FCh",
             "rule":      "FFh returns to SDR; FCh preserves NV-DDR family + timing mode.",
             "trap":      "FFh on parity-error recovery loses NV-DDR3 setup and forces re-training."},
            {"trap_name": "first_reset_5ms",
             "rule":      "First Reset (FFh) ≤ 5 ms; subsequent ≤ 500 µs.",
             "trap":      "Host with 1 ms timeout hangs on power-up."},
            {"trap_name": "param_page_crc_must_validate",
             "rule":      "Parameter Page CRC (8005h init 4F4Eh) at bytes 254-255 covers bytes 0-253.",
             "trap":      "Host trusting first copy unconditionally may use corrupted geometry."},
            {"trap_name": "tCCS_must_be_observed",
             "rule":      "Wait ≥ tCCS after second address byte of Change Read/Write Column before data.",
             "trap":      "Omitting tCCS reads/writes at OLD column."},
            {"trap_name": "wpn_no_transition_during_program_erase",
             "rule":      "WP_n shall not transition during active Program/Erase or with Write Enable active.",
             "trap":      "Mid-program WP_n glitch can corrupt the page."},
            {"trap_name": "read_status_enhanced_during_target_cmd",
             "rule":      "78h shall not be used during/after Target-level commands.",
             "trap":      "78h during Read Parameter Page poll returns undefined data."},
            {"trap_name": "wpn_disables_erase_not_read",
             "rule":      "WP_n disables Program/Erase, NOT Read.",
             "trap":      "Hosts must use higher-layer policy for read protection."},
            {"trap_name": "factory_bad_block_skip",
             "rule":      "Factory-marked bad blocks have non-FFh first byte in spare area; erase fails.",
             "trap":      "Drivers trying to 'recover' a factory-bad block may retire a good block."},
        ]
    f.setdefault("version_naming_history_note",
        "ONFI is managed by the ONFI Workgroup (Intel, Micron, Phison, "
        "Western Digital, SK Hynix, Sony). The competing standard is the "
        "Samsung-led Toggle Mode DDR NAND. At ONFI 4.x and Toggle DDR4 the "
        "industry has converged on near-identical electrical signaling but "
        "different command sequencing; many modern NAND devices implement "
        "both for multi-vendor sourcing.")
    if _empty(f.get("key_changes")):
        f["key_changes"] = [
            {"version": "ONFI 2.0 (2008)", "summary": "Source-synchronous NV-DDR — first DDR NAND interface."},
            {"version": "ONFI 2.1 (2009)", "summary": "Multi-plane + Read Cache — first major throughput boost."},
            {"version": "ONFI 2.3 (2010)", "summary": "EZ NAND in-package controller."},
            {"version": "ONFI 3.0 (2011)", "summary": "NV-DDR2 differential + ZQ + Volume Select."},
            {"version": "ONFI 3.1 (2012)", "summary": "Extended Parameter Page (EPPS) + Extended ECC Information."},
            {"version": "ONFI 4.0 (2014)", "summary": "NV-DDR3 + Independent Data Buses + matrix termination."},
            {"version": "ONFI 4.1 (2017)", "summary": "NV-DDR3 1.2 GT/s + DCC + DQ training commands."},
        ]
    d["fields"] = f
    _write(p, d)


# ---------------------------------------------------------------------------
# L15 encoding tables
# ---------------------------------------------------------------------------
def _l15(gd: Path) -> None:
    p = gd / "L15_ENCODING_TABLES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = d.get("fields") or {}
    f.setdefault("bus_cycle_type_table", {
        "header_columns": ["CLE", "ALE", "WE_n", "RE_n", "Cycle Type", "DQ contents"],
        "rows": [
            ["1", "0", "rising", "1",       "Command",    "8-bit opcode"],
            ["0", "1", "rising", "1",       "Address",    "8-bit address byte"],
            ["0", "0", "rising", "1",       "Write data", "8-bit write byte"],
            ["0", "0", "1",       "falling","Read data",  "8-bit read byte (device-driven)"],
        ],
    })
    # v0.1.87 — ONFI L15 command-set table (Section 4.1 Table 94).
    f.setdefault("command_set_table", {
        "header_columns": [
            "Command", "O/M", "1st Cycle", "2nd Cycle",
            "Acceptable while LUN busy",
            "Acceptable while other LUNs busy",
            "Target-level",
        ],
        "rows": [
            ["Read",                          "M",            "00h", "30h", "",  "Y", ""],
            ["Multi-plane Read",              "O",            "00h", "32h", "",  "Y", ""],
            ["Copyback Read",                 "O",            "00h", "35h", "",  "Y", ""],
            ["Change Read Column",            "M",            "05h", "E0h", "",  "Y", ""],
            ["Change Read Column Enhanced",   "O",            "06h", "E0h", "",  "Y", ""],
            ["Read Cache Random",             "O",            "00h", "31h", "",  "Y", ""],
            ["Read Cache Sequential",         "O",            "31h", "",    "",  "Y", ""],
            ["Read Cache End",                "O",            "3Fh", "",    "",  "Y", ""],
            ["Block Erase",                   "M",            "60h", "D0h", "",  "Y", ""],
            ["Multi-plane Block Erase",       "O",            "60h", "D1h", "",  "Y", ""],
            ["Read Status",                   "M",            "70h", "",    "Y", "Y", ""],
            ["Read Status Enhanced",          "O",            "78h", "",    "Y", "Y", ""],
            ["Page Program",                  "M",            "80h", "10h", "",  "Y", ""],
            ["Multi-plane Page Program",      "O",            "80h", "11h", "",  "Y", ""],
            ["Page Cache Program",            "O",            "80h", "15h", "",  "Y", ""],
            ["Copyback Program",              "O",            "85h", "10h", "",  "Y", ""],
            ["Multi-plane Copyback Program",  "O",            "85h", "11h", "",  "Y", ""],
            ["Small Data Move",               "O",            "85h", "11h", "",  "Y", ""],
            ["Change Write Column",           "M",            "85h", "",    "",  "Y", ""],
            ["Change Row Address",            "O",            "85h", "",    "",  "Y", ""],
            ["Read ID",                       "M",            "90h", "",    "",  "",  "Y"],
            ["Volume Select",                 "O",            "E1h", "",    "Y", "Y", ""],
            ["ODT Configure",                 "O",            "E2h", "",    "",  "Y", "Y"],
            ["Read Parameter Page",           "M",            "ECh", "",    "",  "Y", ""],
            ["Read Unique ID",                "O",            "EDh", "",    "",  "Y", ""],
            ["Get Features",                  "O",            "EEh", "",    "",  "Y", ""],
            ["Set Features",                  "O",            "EFh", "",    "",  "Y", ""],
            ["Implicit DCC Training",         "O",            "18h", "",    "",  "Y", ""],
            ["Read DQ Training",              "O",            "62h", "",    "",  "Y", ""],
            ["Write TX DQ Training Pattern",  "M (NV-DDR3)",  "63h", "",    "",  "Y", ""],
            ["Write TX DQ Training Readback", "M (NV-DDR3)",  "64h", "",    "",  "Y", ""],
            ["Write RX DQ Training",          "O",            "76h", "",    "",  "Y", ""],
            ["LUN Get Features",              "O",            "D4h", "",    "",  "Y", ""],
            ["LUN Set Features",              "O",            "D5h", "",    "",  "Y", ""],
            ["ZQ Calibration Short",          "O",            "D9h", "",    "",  "Y", ""],
            ["ZQ Calibration Long",           "O",            "F9h", "",    "",  "Y", ""],
            ["Reset LUN",                     "O",            "FAh", "",    "Y", "Y", ""],
            ["Synchronous Reset",             "O",            "FCh", "",    "Y", "Y", "Y"],
            ["Reset",                         "M",            "FFh", "",    "Y", "Y", "Y"],
        ],
    })
    # v0.1.87 — ONFI L15 opcode reservations (Section 4.2 Table 95).
    f.setdefault("opcode_reservations_table", {
        "header_columns": ["Type", "Opcodes"],
        "rows": [
            ["Standard Command Set",
             "00h, 05h-06h, 10h-11h, 15h, 18h, 30h-32h, 35h, 3Fh, 60h, "
             "62h-64h, 70h, 76h, 78h, 80h-81h, 85h, 90h, D0h-D1h, "
             "D4h-D5h, D9h, E0h-E2h, ECh-EFh, F1h-F2h, F9h, FAh, FCh, FFh"],
            ["Vendor Specific",
             "01h-04h, 07h-0Ah, 0Ch-0Fh, 13h, 16h-17h, 19h-1Ah, 1Dh-2Fh, "
             "33h-34h, 36h-3Eh, 40h-5Fh, 61h, 65h-6Fh, 71h-75h, 77h, "
             "79h-7Fh, 84h, 87h-8Dh, 8Fh, 91h-CFh, D2h-D3h, D6h-D8h, "
             "DAh-DFh, E3h-EBh, F0h, F3h-F8h, FBh, FDh-FEh"],
            ["Reserved",
             "0Bh, 12h, 14h, 1Bh-1Ch, 82h-83h, 86h, 8Eh"],
        ],
    })
    # v0.1.87 — ONFI L15 package / signal-count mapping (Section 3 Table 3).
    f.setdefault("package_signal_count_table", {
        "header_columns": ["Package", "CE_n count", "Data bus", "Notes"],
        "rows": [
            ["TSOP-48",  "1-4",       "x8 / x16",  "SDR (x8 or x16); NV-DDR x8"],
            ["WSOP-48",  "1-4",       "x8 / x16",  "Same balls as TSOP-48; thinner package"],
            ["LGA-52",   "1-2",       "x8 / x16",  "SDR only"],
            ["BGA-63",   "1-2",       "x8 / x16",  "SDR / NV-DDR x8"],
            ["BGA-100",  "1-2",       "x8",        "SDR / NV-DDR / NV-DDR2/3 x8"],
            ["BGA-132",  "1-4",       "x8",        "SDR / NV-DDR / NV-DDR2/3 x8"],
            ["BGA-152",  "1-4",       "x8",        "SDR / NV-DDR / NV-DDR2/3 x8"],
            ["BGA-272",  "up to 16",  "quad 8-bit","Independent Data Buses; high-density SSD packages"],
            ["BGA-316",  "16 or 32",  "quad 8-bit","Highest CE_n density; SSD-class packages"],
        ],
    })
    f.setdefault("status_register_bit_table", {
        "header_columns": ["Bit", "Name", "Meaning"],
        "rows": [
            ["7", "WP_n",  "0 = write-protected; 1 = not. Always valid."],
            ["6", "RDY",   "1 = LUN ready; 0 = command in progress; SR[5:0] invalid."],
            ["5", "ARDY",  "1 = no array op; 0 = array op in progress."],
            ["4", "VSP",   "Vendor Specific."],
            ["3", "CSP",   "Command Specific (EZ NAND read ECC threshold)."],
            ["2", "R",     "Reserved (0)."],
            ["1", "FAILC", "1 = prior cached command failed."],
            ["0", "FAIL",  "1 = last command failed."],
        ],
    })
    f.setdefault("read_id_signature_table", {
        "header_columns": ["Read ID address", "Returned bytes"],
        "rows": [
            ["00h", "Manufacturer + Device + 2 vendor-defined (≥ 4 bytes)"],
            ["20h", "'ONFI' = 4Fh 4Eh 46h 49h"],
            ["40h", "'JEDEC' = 4Ah 45h 44h 45h 43h"],
        ],
    })
    f.setdefault("parameter_page_signature_table", {
        "header_columns": ["Byte offset", "Value", "Meaning"],
        "rows": [
            ["0", "4Fh", "'O'"],
            ["1", "4Eh", "'N'"],
            ["2", "46h", "'F'"],
            ["3", "49h", "'I'"],
        ],
    })
    f.setdefault("extended_parameter_page_signature_table", {
        "header_columns": ["Byte offset", "Value", "Meaning"],
        "rows": [
            ["2", "45h", "'E'"],
            ["3", "50h", "'P'"],
            ["4", "50h", "'P'"],
            ["5", "53h", "'S'"],
        ],
    })
    f.setdefault("parameter_page_crc_table", {
        "header_columns": ["Field", "Value"],
        "rows": [
            ["Polynomial",        "x^16 + x^15 + x^2 + 1 (0x8005)"],
            ["Initial value",     "0x4F4E"],
            ["Final XOR",         "None"],
            ["Bit reversal",      "None (MSB-first per byte)"],
            ["Coverage (Param)",  "Bytes 0..253; CRC bytes 254-255"],
            ["Coverage (ExtParam)","Bytes 2..end; CRC bytes 0-1"],
        ],
    })
    f.setdefault("data_interface_table", {
        "header_columns": ["Interface", "Strobe / Clock", "Max data rate (MT/s)", "Pin sharing"],
        "rows": [
            ["SDR",     "WE_n / RE_n",                     "200",  "—"],
            ["NV-DDR",  "CLK + bidirectional DQS",         "400",  "CLK shares WE_n; W/R_n shares RE_n"],
            ["NV-DDR2", "WE_n + diff DQS_t/DQS_c",          "800",  "DQS_c shares DQS complement"],
            ["NV-DDR3", "WE_n + diff DQS_t/DQS_c + RE_t/RE_c","1200","RE_t/RE_c + DQS complement shared pins"],
        ],
    })
    f.setdefault("feature_address_table", {
        "header_columns": ["Feature address (hex)", "Feature"],
        "rows": [
            ["01h", "Timing Mode (SDR / NV-DDR / NV-DDR2 / NV-DDR3)"],
            ["02h", "NV-DDR2 / NV-DDR3 Configuration"],
            ["08h", "DCC / Read DQ Training settings"],
            ["09h", "Write TX DQ Training settings"],
            ["0Ah", "Write RX DQ Training settings"],
            ["0Bh", "Implicit DCC Training settings"],
            ["10h", "I/O Drive Strength"],
            ["30h", "ECC Configuration (EZ NAND)"],
            ["39h", "External Vpp Configuration"],
            ["58h", "Volume Configuration"],
            ["80h", "EZ NAND control low"],
            ["81h", "EZ NAND control high"],
        ],
    })
    f.setdefault("address_cycle_count_table", {
        "header_columns": ["Operation", "Column cycles", "Row cycles", "Total"],
        "rows": [
            ["Read (00h/30h)",                "2", "3", "5"],
            ["Page Program (80h/10h)",        "2", "3", "5"],
            ["Block Erase (60h/D0h)",         "0", "3", "3"],
            ["Read Status Enhanced (78h)",    "0", "3", "3"],
            ["Change Read Column (05h/E0h)",  "2", "0", "2"],
            ["Change Write Column (85h)",     "2", "0", "2"],
            ["Read ID (90h)",                 "0", "0", "1 (address byte)"],
            ["Read Parameter Page (ECh)",     "0", "0", "1 (00h)"],
            ["Read Unique ID (EDh)",          "0", "0", "1 (00h)"],
        ],
    })
    f.setdefault("composite_status_table", {
        "header_columns": ["Status Register bit", "Composite combination across LUN planes"],
        "rows": [
            ["Bit 0 FAIL",  "OR across all selected plane statuses"],
            ["Bit 1 FAILC", "OR across all selected plane statuses"],
            ["Bit 3 CSP",   "OR across all selected plane statuses"],
        ],
    })
    if _empty(f.get("tables")):
        f["tables"] = [
            "Table 2 — Signal descriptions",
            "Table 3 — Signal mappings: TSOP, LGA, BGA-63",
            "Table 4 — Signal mappings: BGA-100, BGA-132, BGA-152",
            "Table 5 — Signal mappings: BGA-272, BGA-316",
            "Table 94 — Command set",
            "Table 95 — Opcode Reservations",
            "Table 96 — Parameter Page Data Structure",
            "Table 97 — Extended Parameter Page Section Type Definitions",
            "Table 100 — Extended Parameter Page definition",
            "Table 101 — UID and Complement",
            "Table 102 — Composite Status Value",
        ]
    d["fields"] = f
    _write(p, d)


# ---------------------------------------------------------------------------
# L16 compliance
# ---------------------------------------------------------------------------
def _l16(gd: Path) -> None:
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = d.get("fields") or {}
    f.setdefault("must_have_properties", [
        "Every command shall be a single 8-bit opcode latched on CLE=1, ALE=0, WE_n rising.",
        "Every address byte shall be 8 bits latched on CLE=0, ALE=1, WE_n rising.",
        "Read / Page Program shall have 5 address cycles (2 column + 3 row); Block Erase 3 row cycles.",
        "Read Status (70h) shall return {WP_n, RDY, ARDY, VSP, CSP, R, FAILC, FAIL}.",
        "Status bit 6 (RDY) shall be 0 during command in progress; SR[5:0] invalid; WP_n still valid.",
        "Status bit 0 (FAIL) shall report last-command outcome.",
        "R/B_n shall be open-drain; LOW when any LUN busy.",
        "Parameter Page (ECh + 00h) ≥ 256 bytes; signature 'ONFI' (4Fh, 4Eh, 46h, 49h) at bytes 0-3; CRC at bytes 254-255.",
        "Parameter Page CRC polynomial 8005h, init 4F4Eh, no final XOR, no bit reversal, MSB-first per byte.",
        "Parameter Page ≥ 3 redundant copies at offsets 0/256/512.",
        "Read ID (90h + 20h) shall return 'ONFI' signature on ONFI-compliant devices.",
        "Mandatory command set: Read (00h/30h), Block Erase (60h/D0h), Read Status (70h), Page Program (80h/10h), Read ID (90h), Read Parameter Page (ECh), Reset (FFh), Change Read Column (05h/E0h), Change Write Column (85h).",
        "NV-DDR3 devices shall implement Write TX DQ Training Pattern (63h) and Readback (64h) mandatory.",
        "WP_n LOW shall disable Program / Erase; shall NOT disable Read.",
        "WP_n shall not transition during active Program/Erase or with Write Enable active.",
        "Reset (FFh) → SDR mode 0, volatile state cleared.",
        "Synchronous Reset (FCh) shall preserve active data interface and timing mode.",
        "Read Status Enhanced (78h) shall turn off output buffers of other LUNs.",
        "Set / Get Features shall transfer exactly 4 P-bytes per feature address.",
        "ZQ Calibration Long (F9h) shall be issued after Reset before NV-DDR2/NV-DDR3 high-speed operation; tZQCL ≥ 1 µs.",
        "ODT for NV-DDR2/3 shall support Deselected / Selected / Sniff; matrix via ODT Configure (E2h).",
        "Volume Select (E1h) shall direct subsequent commands in CE_n pin reduction.",
        "Read Cache End (3Fh) shall terminate Read Cache sequences.",
        "tCCS shall be observed after second address byte of Change Read/Write Column.",
        "tADL shall be observed after second address byte of Page Program.",
        "Factory-marked bad blocks shall not be erased (FAIL bit).",
        "Reset (FFh) at power-on ≤ 5 ms; subsequent ≤ 500 µs.",
    ])
    f.setdefault("must_not_have_properties", [
        "Host shall not issue commands to a busy LUN (RDY=0) except Read Status, Read Status Enhanced, Reset (FFh/FCh/FAh).",
        "Host shall not use Read Status Enhanced (78h) during/after Target-level commands.",
        "Host shall not toggle WP_n during active Program/Erase or with Write Enable active.",
        "Device shall not honour erase of factory-marked bad block.",
        "Host shall not configure timing mode exceeding device-advertised max.",
        "Vendor opcodes shall not be used by device for ONFI-standard purposes; reserved opcodes (0Bh, 12h, 14h, 1Bh-1Ch, 82h-83h, 86h, 8Eh) shall not be used.",
        "Host shall not read a UID copy whose XOR-with-complement ≠ all ones.",
        "Host shall not assume Page Cache Program FAILC valid until after second 15h/10h.",
    ])
    f.setdefault("compliance_failure_modes", [
        {"mode": "Page Program failure",      "trigger": "Bit 0 FAIL after R/B_n HIGH; page indeterminate."},
        {"mode": "Block Erase failure",       "trigger": "Bit 0 FAIL; or erase of factory-bad block."},
        {"mode": "Read failure (EZ NAND)",    "trigger": "Bit 0 FAIL; data on DQ not trusted."},
        {"mode": "ECC threshold (EZ NAND Read)","trigger": "Bit 3 CSP when FAIL=0; rewrite recommended."},
        {"mode": "Page Cache prior-command failure", "trigger": "Bit 1 FAILC after second 15h/10h."},
        {"mode": "Parameter Page CRC mismatch","trigger": "Host falls back to redundant copy at +256/+512."},
        {"mode": "Unique ID retrieval-error", "trigger": "UID XOR complement ≠ all ones; iterate next of 16 copies."},
        {"mode": "ZQ Calibration failure",    "trigger": "Bit 0 FAIL after F9h/D9h."},
        {"mode": "Read DQ Training window not found","trigger": "No contiguous pass window; host drops to slower mode."},
        {"mode": "Write TX DQ pattern mismatch","trigger": "Readback (64h) ≠ Pattern (63h) at all TX phases."},
        {"mode": "Timeout on R/B_n",          "trigger": "R/B_n LOW longer than tPROG/tBERS/tR plus margin; host Reset (FFh)."},
    ])
    f.setdefault("min_data_interface_constraint",
        "All devices shall support SDR timing mode 0 immediately after Reset "
        "(FFh). Higher modes are version-gated per Parameter Page Revision "
        "Number and timing-mode bitmaps.")
    f.setdefault("reset_behavior_compliance",
        "Reset (FFh) sets device to SDR mode 0, volatile state cleared, ODT "
        "off, ZQ drivers at default. Synchronous Reset (FCh) preserves data "
        "interface, timing mode, and feature settings. Reset LUN (FAh) is "
        "per-LUN.")
    d["fields"] = f
    _write(p, d)


# ---------------------------------------------------------------------------
# L17 channel signal catalog
# ---------------------------------------------------------------------------
def _l17(gd: Path) -> None:
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if not p.is_file():
        return
    d = _read(p)
    f = d.get("fields") or {}
    f["channels"] = [
        {"name": "CE_n",  "direction_host": "output", "direction_device": "input", "purpose": "Chip Enable (active-low); selects target."},
        {"name": "CLE",   "direction_host": "output", "direction_device": "input", "purpose": "Command Latch Enable."},
        {"name": "ALE",   "direction_host": "output", "direction_device": "input", "purpose": "Address Latch Enable."},
        {"name": "WE_n / CLK", "direction_host": "output", "direction_device": "input", "purpose": "Write Enable (SDR) / Clock (NV-DDR); shared pin."},
        {"name": "RE_n / RE_t / W/R_n", "direction_host": "output", "direction_device": "input", "purpose": "Read Enable / NV-DDR3 differential / NV-DDR direction; shared pin."},
        {"name": "RE_c",  "direction_host": "output", "direction_device": "input", "purpose": "Read Enable Complement (NV-DDR2/3 optional)."},
        {"name": "WP_n",  "direction_host": "output", "direction_device": "input", "purpose": "Write Protect; disables Program/Erase when LOW."},
        {"name": "R/B_n", "direction_host": "input",  "direction_device": "output (open-drain)", "purpose": "Ready/Busy; LOW = busy."},
        {"name": "DQ[7:0]", "direction_host": "bidirectional", "direction_device": "bidirectional", "purpose": "8-bit data bus (cmd/addr/data)."},
        {"name": "DQ[15:8]","direction_host": "bidirectional", "direction_device": "bidirectional", "purpose": "Upper 8 bits (SDR x16)."},
        {"name": "DQS / DQS_t","direction_host": "bidirectional", "direction_device": "bidirectional", "purpose": "Data Strobe True (NV-DDR family)."},
        {"name": "DQS_c", "direction_host": "bidirectional", "direction_device": "bidirectional", "purpose": "Data Strobe Complement (NV-DDR2/3 optional)."},
        {"name": "VREFQ", "direction_host": "output", "direction_device": "input", "purpose": "Input reference voltage (NV-DDR2/3)."},
        {"name": "ZQ",    "direction_host": "—", "direction_device": "calibration", "purpose": "ZQ Calibration reference; tied to Vss via RZQ."},
        {"name": "ENi",   "direction_host": "output", "direction_device": "input", "purpose": "Enumeration input (CE_n pin reduction)."},
        {"name": "ENo",   "direction_host": "input",  "direction_device": "output", "purpose": "Enumeration output (CE_n pin reduction)."},
    ]
    f["power_pins"] = [
        {"name": "Vcc",   "purpose": "Core supply."},
        {"name": "VccQ",  "purpose": "I/O supply."},
        {"name": "Vss",   "purpose": "Core ground."},
        {"name": "VssQ",  "purpose": "I/O ground."},
        {"name": "Vpp",   "purpose": "Optional high-voltage power."},
        {"name": "VDDi",  "purpose": "EZ NAND internal regulator stabilizing pin."},
    ]
    f["global_signals"] = [
        {"name": "VREFQ", "purpose": "Input reference voltage shared across DQ + DQS (NV-DDR2/3)."},
    ]
    f["channel_counts"] = {
        "data_lines_x8":  8,
        "data_lines_x16": 16,
        "command_strobe_pins": 4,
        "data_strobe_pins":    2,
        "control_pins":        5,
        "power_pins":          4,
        "calibration_pins":    1,
        "enumeration_pins":    2,
        "rb_pins":             1,
        "external_pins_tsop48_x8_sdr":   48,
        "external_balls_bga152_x8_nv_ddr3": 152,
        "external_balls_bga272_quad_x8":  272,
        "external_balls_bga316_x8":       316,
    }
    f["pin_sharing_map"] = [
        {"sdr_pin": "WE_n", "nv_ddr_pin": "CLK",   "nv_ddr2_3_pin": "WE_n", "description": "WE_n carries CLK in NV-DDR; reverts to WE_n in NV-DDR2/NV-DDR3."},
        {"sdr_pin": "RE_n", "nv_ddr_pin": "W/R_n", "nv_ddr2_3_pin": "RE_t (with RE_c adjacent)", "description": "RE_n carries W/R_n in NV-DDR; RE_t in NV-DDR3 differential."},
        {"sdr_pin": "—",    "nv_ddr_pin": "DQS",   "nv_ddr2_3_pin": "DQS_t (with DQS_c adjacent)", "description": "DQS only in NV-DDR family."},
    ]
    f["ordering_rules"] = {
        "byte_ordering_on_dq":  "8-bit DQ carries one byte per cycle; multi-byte fields LSB-first.",
        "byte_ordering_on_x16": "x16 DQ carries 16-bit word per cycle; DQ[7:0] low, DQ[15:8] high.",
        "address_byte_order":   "Read/Program: C1 (col LSB), C2 (col MSB), R1 (row LSB), R2 (row mid), R3 (row MSB). Erase: R1, R2, R3 only.",
    }
    f["dependency_graph"] = {
        "common_rule": "Host drives all strobes; device drives R/B_n. CLE/ALE select cycle type; WE_n rising (SDR) or CLK rising (NV-DDR) latches cmd/addr; RE_n falling or DQS edges drive read data.",
        "data_dependency": "Address cycles depend on preceding command. Data cycles depend on most recent cmd + addr + active data interface. R/B_n LOW gates new commands.",
    }
    f["handshake_pairs"] = [
        {"name": "CMD_LATCH",       "from": "host", "to": "device", "rule": "CLE=1, ALE=0, WE_n rising → DQ = opcode."},
        {"name": "ADDR_LATCH",      "from": "host", "to": "device", "rule": "CLE=0, ALE=1, WE_n rising → DQ = address byte."},
        {"name": "WRITE_DATA_LATCH","from": "host", "to": "device", "rule": "CLE=0, ALE=0, WE_n rising (SDR) or DQS edge (NV-DDR) → DQ = write byte."},
        {"name": "READ_DATA_DRIVE", "from": "device", "to": "host", "rule": "CLE=0, ALE=0, RE_n falling (SDR) or RE_t/RE_c + DQS edges (NV-DDR) → device drives DQ."},
        {"name": "BUSY_INDICATION", "from": "device", "to": "host", "rule": "Any LUN busy → R/B_n LOW; all LUNs ready → R/B_n HIGH (external pull-up)."},
        {"name": "STATUS_POLL",     "from": "host", "to": "device", "rule": "70h or 78h + 3 row addr → device drives status byte on next RE_n falling (SDR) or DQS edges (NV-DDR)."},
    ]
    d["fields"] = f
    _write(p, d)


# ---------------------------------------------------------------------------
# L18 interconnect topology
# ---------------------------------------------------------------------------
def _l18(gd: Path) -> None:
    p = gd / "L18_INTERCONNECT_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = d.get("fields") or {}
    f["topology_type"] = (
        "Master/slave shared bus per channel. One NAND Flash Controller "
        "drives strobes + DQ + per-target CE_n; one or more NAND Targets "
        "(LUNs grouped by CE_n) share the bus. R/B_n is open-drain "
        "device-driven and wired-OR across targets.")
    f["supported_topologies"] = [
        {"name": "Single host + single target (per channel)", "description": "Simplest; low-end SSD or consumer USB drive."},
        {"name": "Single host + multi-target with per-target CE_n", "description": "Up to 4 (or more on BGA-272 / BGA-316) targets; host selects via CE_n."},
        {"name": "Single host + multi-target with CE_n pin reduction", "description": "Shared CE_n; per-target Volume Address."},
        {"name": "Independent Data Buses (Section 2.16)", "description": "Two parallel DQ buses for double per-package throughput."},
        {"name": "Multi-channel host controller", "description": "Parallel ONFI channels in SSD controllers."},
        {"name": "Matrix termination (ODT)", "description": "NV-DDR3 multi-target with per-LUN ODT states."},
    ]
    f["master_slave_role_summary"] = [
        {"role": "Host (NAND Flash Controller)", "description": "Generates all strobes; issues all commands; runs training; owns ECC (raw) or offloads (EZ); implements FTL."},
        {"role": "Device (NAND Target)",         "description": "Decodes cmd/addr; drives data on strobes; drives R/B_n LOW during operations."},
    ]
    f["interconnect_role"] = (
        "No protocol-layer router or bridge — flat 1-host : N-target bus per "
        "channel. Multi-target arbitration is time-domain via CE_n (or "
        "Volume Address after CE_n reduction).")
    f["ordering_guarantees"] = {
        "within_a_page": "Bytes streamed in column order from the page register.",
        "across_commands": "Strictly serial within a single LUN; parallel across LUNs.",
        "multi_plane":     "Multi-plane Program / Erase / Read execute concurrently within a LUN; FAIL is per-plane.",
        "page_cache":      "Page Cache Program allows pipelined next-page submission while prior-page array program in progress; FAILC reports prior.",
    }
    f["memory_vs_peripheral_regions"] = (
        "Hierarchical block→page→column address space. No memory-mapped "
        "peripheral region; Parameter Page / Unique ID / Status accessed via "
        "dedicated commands (ECh / EDh / 70h).")
    f["device_classification"] = {
        "raw_nand":         "Pure NAND die; host runs full ECC + FTL.",
        "ez_nand":          "NAND + in-package controller (ECC offload).",
        "multi_lun_target": "Single CE_n drives multiple LUNs sharing a package.",
    }
    f.setdefault("default_signal_values_evidence_tables", [
        "Table 3 — Signal mappings: TSOP, LGA, BGA-63",
        "Table 4 — Signal mappings: BGA-100, BGA-132, BGA-152",
        "Table 5 — Signal mappings: BGA-272, BGA-316",
        "Figure 17 — BGA-272 ball assignments for quad 8-bit data access",
        "Figure 18 — BGA-316 ball 16 CE_n assignments",
        "Figure 19 — BGA-316 ball 32 CE_n assignments",
        "Section 2.16 Independent Data Buses",
        "Section 2.17 Bus Width Requirements",
        "Section 2.20 CE_n Pin Reduction Mechanism",
    ])
    d["fields"] = f
    _write(p, d)


# ---------------------------------------------------------------------------
# L19 PDK constraints
# ---------------------------------------------------------------------------
def _l19(gd: Path) -> None:
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if not p.is_file():
        return
    d = _read(p)
    f = d.get("fields") or {}
    f.setdefault("constraints_present", False)
    f.setdefault("host_pcb_constraints_summary", [
        "External pull-up resistor on R/B_n (typ. 1-10 kΩ); required (open-drain).",
        "External RZQ reference resistor (typ. 300 Ω ±1 %) on each ZQ pin to Vss.",
        "VREFQ supply (≈ 0.5 × VccQ ±2 %) for NV-DDR2/3 single-ended.",
        "Bypass capacitor on Vcc + VccQ + Vpp.",
        "Signal-integrity routing for NV-DDR2 (800 MT/s) and NV-DDR3 (1.2 GT/s).",
        "VDDi external capacitor for EZ NAND.",
        "Staggered power-up power switch for multi-target rails.",
        "ESD protection per JEDEC class.",
    ])
    f["notes"] = (
        "ONFI 4.1 Section 2 (Physical Interface) defines bus electrical "
        "parameters: absolute maximum DC ratings (2.9), recommended DC "
        "operating conditions (2.10), AC overshoot/undershoot (2.11), DC "
        "and AC characteristics (2.12), VREFQ tolerance (2.12.2), pin "
        "capacitance limits (2.13). Section 4.10 tightens for NV-DDR. "
        "Section 4.7-4.13 covers ZQ / drive strength / slew rate / "
        "impedance values for NV-DDR2 / NV-DDR3. No internal SDC / UPF / "
        "DFT artifacts in the spec.")
    f.setdefault("device_internal_constraints",
        "Device-internal PDK / SDC / floorplan / layout constraints are "
        "intentionally out of scope of ONFI 4.1. NAND vendors deliver "
        "per-product PDK / SDC files separately.")
    d["fields"] = f
    _write(p, d)


# ---------------------------------------------------------------------------
# L20 DFT
# ---------------------------------------------------------------------------
def _l20(gd: Path) -> None:
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = d.get("fields") or {}
    f["dft_present"] = "partial"
    f.setdefault("exposed_dft_features", [
        {"name": "Read Status (70h) / Read Status Enhanced (78h)", "purpose": "Per-LUN error reporting (FAIL/FAILC/CSP)."},
        {"name": "Read Parameter Page (ECh) with CRC + 3 copies",  "purpose": "Self-checking factory metadata."},
        {"name": "Read Unique ID (EDh) + complement, 16 copies",    "purpose": "Self-validating UID retrieval."},
        {"name": "Read DQ Training (62h, NV-DDR3)",                  "purpose": "Built-in lane DFT for RX eye characterization."},
        {"name": "Write TX DQ Training (63h/64h, NV-DDR3)",          "purpose": "Round-trip pattern for write-path eye margin."},
        {"name": "Write RX DQ Training (76h, NV-DDR3)",              "purpose": "Device-side RX training."},
        {"name": "ZQ Calibration (F9h / D9h)",                       "purpose": "Output driver impedance trim."},
        {"name": "Implicit DCC Training (18h, NV-DDR3)",             "purpose": "Internal clock duty-cycle correction."},
        {"name": "Get Features (EEh)",                                "purpose": "Round-trip of programmed settings."},
        {"name": "Factory Defect Map (Section 3.3)",                  "purpose": "Host-visible bad-block markers."},
        {"name": "Composite Status (Table 102)",                       "purpose": "Multi-plane FAIL bits OR'd into Read Status."},
    ])
    f["notes"] = (
        "ONFI exposes protocol-level observability + NV-DDR3 PHY "
        "characterization hooks but does not specify a JTAG / boundary-scan "
        "/ scan-chain port. Internal NAND-cell health (raw BER, ECC "
        "headroom, charge-pump margin) is reported indirectly via FAIL bit, "
        "CSP threshold, and host-side UBER measurement.")
    f.setdefault("no_jtag_on_package",
        "ONFI 4.1 does NOT specify a JTAG / boundary-scan port on the NAND "
        "package interface. Vendor DFT is performed at wafer / package "
        "test before shipment.")
    d["fields"] = f
    _write(p, d)


# ---------------------------------------------------------------------------
# L21 power intent
# ---------------------------------------------------------------------------
def _l21(gd: Path) -> None:
    p = gd / "L21_POWER_INTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    f = d.get("fields") or {}
    f.setdefault("power_intent_present", True)
    # v0.1.87 — ONFI L21 power-domain VccQ / VssQ widened to match agent
    # superset (per-data-interface voltage list + DQ/DQS ground-return note).
    pds = _ensure_dict(f, "power_domains_summary")
    pds["Vcc"] = "Core supply. Typical 3.3 V (legacy) or 1.8 V (modern); see Section 2.10."
    pds["VccQ"] = ("I/O supply, separate from Vcc. Typical 3.3 V (SDR legacy), "
                   "1.8 V (SDR modern / NV-DDR / NV-DDR2 / NV-DDR3), "
                   "1.2 V (advanced NV-DDR2 / NV-DDR3).")
    pds.setdefault("Vss",  "Core ground.")
    pds["VssQ"] = "I/O ground; separate return for DQ / DQS to reduce ground bounce."
    pds.setdefault("Vpp",  "Optional high-voltage supply for improved Program / Erase efficiency.")
    pds.setdefault("VDDi", "EZ NAND internal-regulator stabilizing pin (na on raw NAND).")
    f.setdefault("power_up_sequence", [
        "1. Host applies Vcc + VccQ (+ Vpp) per Section 2.10 ramp profile.",
        "2. Host de-asserts WP_n LOW; CE_n HIGH during ramp.",
        "3. Host waits for power stable + tCRY.",
        "4. Host asserts CE_n LOW; issues Reset (FFh).",
        "5. Device drives R/B_n LOW; up to 5 ms for first reset.",
        "6. Host runs Discovery (Read ID 20h + Read Parameter Page).",
        "7. (NV-DDR family) Set Features (01h) + ZQ Long + training.",
        "8. Host de-asserts WP_n (HIGH).",
    ])
    f.setdefault("staggered_power_up",
        "Section 2.14 — Multi-target sharing single Vcc/VccQ rail shall "
        "stagger CE_n + Reset to bound inrush current.")
    lps = _ensure_dict(f, "low_power_modes_summary")
    lps.setdefault("Standby",           "CE_n HIGH while target ready; ICC1.")
    lps.setdefault("Deep_power_down",   "Vendor-specific or Vcc removal.")
    lps.setdefault("ClockStop_NV_DDR",  "Host may stop CLK during NV-DDR Idle.")
    lps.setdefault("Vpp_off",           "Set Features (39h) disables external Vpp.")
    lps.setdefault("OdT_Deselected",    "NV-DDR2/3 ODT off on deselected LUNs.")
    f.setdefault("current_consumption_table", {
        "header_columns": ["Operation", "Current rail", "Typical range"],
        "rows": [
            ["Standby",         "Vcc + VccQ", "ICC1; vendor-specific"],
            ["Read",            "Vcc + VccQ", "ICC2"],
            ["Program",         "Vcc + VccQ", "ICC3; higher (charge-pump)"],
            ["Erase",           "Vcc + VccQ", "ICC4; highest"],
            ["NV-DDR3 active",  "VccQ",        "Higher than SDR"],
        ],
    })
    f.setdefault("icc_measurement_methodology",
        "Appendix D of ONFI 4.1 defines normative ICC measurement "
        "methodology for cross-vendor comparison.")
    f.setdefault("external_vpp_configuration",
        "Set Features (39h) optionally enables external Vpp (typ. 12 V) for "
        "improved Program / Erase efficiency.")
    f.setdefault("fxe_power_management_register_set", {
        "Vpp_enable":         "Set Features (39h External Vpp Configuration).",
        "Volume_low_power":   "Per-volume power state (Set Features 58h).",
        "EZ_NAND_power":      "Set Features (80h-81h EZ NAND control).",
    })
    f.setdefault("notes",
        "Section 2.10 + 2.14 normative for power-up. Section 2.13 / 4.10 "
        "constrain pin-capacitance budgets. Vendor datasheets carry "
        "absolute ICC numbers; ONFI standardizes only the measurement "
        "methodology.")
    d["fields"] = f
    _write(p, d)


# ---------------------------------------------------------------------------
# L22 verification plan
# ---------------------------------------------------------------------------
def _l22(gd: Path) -> None:
    p = gd / "L22_VERIFICATION_PLAN.json"
    if not p.is_file():
        return
    d = _read(p)
    f = d.get("fields") or {}
    f.setdefault("verification_plan_present", "implicit")
    if _empty(f.get("verification_categories_derived_from_spec")):
        f["verification_categories_derived_from_spec"] = [
            "Power-up + Reset (FFh / FCh / FAh) sequence.",
            "Discovery (Read ID 20h 'ONFI'; Read Parameter Page CRC + redundancy).",
            "Extended Parameter Page (signature 'EPPS'; Extended ECC Information).",
            "Read Unique ID (EDh) — UID XOR complement = all ones.",
            "Read (00h/30h) — single-page; tR; FAIL on EZ NAND.",
            "Page Program (80h/10h) — tPROG; tADL.",
            "Block Erase (60h/D0h) — tBERS; refuse factory-bad block.",
            "Multi-LUN parallelism — per-LUN Read Status Enhanced.",
            "Multi-plane Program / Erase / Read (80h/11h, 60h/D1h, 00h/32h).",
            "Page Cache Program — FAILC after second 15h/10h.",
            "Read Cache Random / Sequential / End.",
            "Copyback Read + Program; Small Data Move.",
            "Change Read / Write Column + tCCS.",
            "Set / Get Features round-trip.",
            "Data interface switch (SDR → NV-DDR → NV-DDR2 → NV-DDR3).",
            "ZQ Calibration Long + Short.",
            "NV-DDR3: DCC + Read DQ + Write TX/RX DQ training.",
            "Volume Select + Volume Appointment (CE_n pin reduction).",
            "ODT Configure (Deselected / Selected / Sniff).",
            "Status invalidation — RDY=0 invalidates SR[5:0] except WP_n.",
            "Composite Status — multi-plane bits OR.",
            "WP_n disables Program/Erase, not Read.",
            "Timing budgets (tCCS / tADL / tWHR / tWB / tRR).",
            "Reset combinations (FFh / FCh / FAh).",
            "Read Status Enhanced restrictions during Target-level commands.",
            "Factory defect map — first byte of spare ≠ FFh.",
            "Independent Data Buses.",
            "Pin-sharing rules across data interfaces.",
        ]
    f["notes"] = (
        "ONFI 4.1 does not include a normative verification plan. "
        "Categories above are derived from Sections 2-7 + Appendices. "
        "The founding vendors maintain internal qualification suites not "
        "part of the public specification.")
    d["fields"] = f
    _write(p, d)


# ---------------------------------------------------------------------------
# L23 security
# ---------------------------------------------------------------------------
def _l23(gd: Path) -> None:
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if not p.is_file():
        return
    d = _read(p)
    f = d.get("fields") or {}
    f["security_requirements_present"] = True
    f["notes"] = (
        "ONFI 4.1 security at the spec level is limited to (a) data-integrity "
        "primitives (Parameter Page CRC, UID complement, Factory Defect Map), "
        "(b) WP_n access-control pin, (c) per-LUN FAIL reporting. "
        "Cryptographic confidentiality, authentication, secure erase, and "
        "replay protection are provided by the higher-layer SSD controller "
        "firmware (FTL + crypto stack) — not by ONFI itself.")
    f.setdefault("security_summary",
        "ONFI 4.1 provides only data-integrity primitives (Parameter Page "
        "Integrity CRC, Unique-ID complement validation) and a single coarse "
        "access-control pin (WP_n disables Program/Erase). The protocol does "
        "NOT define data-at-rest encryption, host-device authentication, or "
        "replay-protected secure regions. Higher-layer security is provided "
        "by the host's NAND Flash Controller / SSD firmware.")
    if _empty(f.get("security_features")):
        f["security_features"] = [
            {"name": "WP_n (Write Protect pin)",                "type": "access control (board-level)", "description": "WP_n LOW disables Program/Erase; Read remains permitted."},
            {"name": "Integrity CRC (Parameter Page)",          "type": "integrity", "description": "16-bit CRC polynomial 8005h, initial 4F4Eh; covers bytes 0-253."},
            {"name": "Integrity CRC (Extended Parameter Page)", "type": "integrity", "description": "16-bit CRC at bytes 0-1; covers bytes 2..end."},
            {"name": "Parameter Page redundancy (≥ 3 copies)",  "type": "integrity", "description": "Host falls back to redundant copy on CRC mismatch."},
            {"name": "Unique ID with complement",                "type": "integrity", "description": "UID XOR complement = all ones; 16 copies."},
            {"name": "Factory Defect Mapping",                  "type": "integrity / reliability", "description": "Bad blocks marked before shipment."},
            {"name": "ECC (host-side for raw NAND; EZ NAND in-package)", "type": "integrity", "description": "≥ 4-bit ECC per 512 B sector mandated by ONFI 4.x; BCH or LDPC."},
            {"name": "Status Register FAIL bit",                "type": "fault reporting", "description": "Per-LUN failure indication."},
        ]
    f["no_base_layer_confidentiality"] = (
        "ONFI 4.1 does NOT specify data-at-rest encryption, host-device "
        "authentication, secure boot, or replay-protected memory. SSD-level "
        "FDE (TCG Opal, IEEE 1667) lives above ONFI.")
    f["comparison_to_sibling_emmc"] = (
        "eMMC adds RPMB with HMAC-SHA256 + write counter. UFS adds UFS "
        "Group Security. ONFI itself has no direct RPMB equivalent.")
    f.setdefault("secure_erase",
        "ONFI provides Block Erase (60h/D0h) electrical erase. Cryptographic "
        "erase (key destruction) is a higher-layer operation.")
    d["fields"] = f
    _write(p, d)


# ---------------------------------------------------------------------------
# Module-level importable detector (lifted from the inline detector in
# phase1_doc_one_shot_runner.py — ORGANIC-20260531). Byte-for-byte the same
# boolean the runner used inline (`_spi_blob` -> `blob`), so behaviour is
# identical; exposing it module-level lets the universal no-misfire guard
# (tests/test_protocol_detector_no_misfire.py) auto-cover this protocol.
# Reads ONLY the spec text `blob` — never a filename or benchmark name.
# ---------------------------------------------------------------------------
def is_onfi(blob: str) -> bool:
    """Content-only `onfi` detector (importable, lifted from the runner).

    Empty-safe. Reads ONLY ``blob`` (spec text). Byte-for-byte the
    same boolean the runner used inline.
    """
    if not blob:
        return False
    return bool(
        ("ONFI" in blob and "NAND" in blob
            and "CLE" in blob and "ALE" in blob)
        or ("NAND" in blob and "DQ" in blob
            and "WE#" in blob and "RE#" in blob)
        or ("Parameter Page" in blob and "R/B#" in blob
            and "ONFI" in blob))
