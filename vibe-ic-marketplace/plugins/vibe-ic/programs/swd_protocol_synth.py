"""swd_protocol_synth.py — ARM Serial Wire Debug (SWD) / ADIv5 deterministic
L1-L23 synth.

R<N>/R<N+1>/R<N+2> — applied AFTER L19-L23 skeleton emit when an inline
structural sub-detector confirms the input docs describe an ARM ADIv5
SWD / SW-DP / SWJ-DP debug interface: (SWDIO + SWCLK + DAP) OR (SWD +
ADIv5 + DP + AP) OR (SWJ-DP + ARM + Debug Port). Doctrine: general
structural detection within ic_class, not benchmark-keyword.

Mirrors UART / SPI / I2C / CAN / USB / I2S / 1-Wire / JTAG synth
approach. Any ADIv5-compliant SW-DP / SWJ-DP (ARM CoreSight DAP, NXP
LPC, ST STM32, Nordic nRF, Microchip SAM, TI MSP432, Silicon Labs
EFM/EFR, Renesas Synergy, Espressif ESP32-S3 ARM-emulating DM, etc.)
exhibits the same protocol signature.

CRITICAL: The SWD spec (ARM IHI 0031C) discusses JTAG/TAP extensively
because ADIv5 supports the SWJ-DP mode-switchable variant. As a result
jtag_protocol_synth may fire first and write JTAG-shaped content into
L1/L3/L4. swd_synth must FORCE-overwrite the L1/L3/L4 ic_name,
protocol_overview, register catalog, and key feature lists so the SWD
shape wins.

Public entry: `apply_swd_synth(generated_docs_dir, is_swd, swd_ic_name)`.
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
    """Helper: setdefault is a no-op if key exists with value None — use
    explicit empty-check to handle that case across the codebase."""
    if d.get(key) in (None, "", []):
        d[key] = {}
    return d[key]


# ============================================================
# Canonical SWD 46-bit transaction format constants (shared)
# ============================================================
_SWD_TRANSACTION_TOTAL_BITS = 46
_SWD_REQUEST_BITS = 8
_SWD_ACK_BITS = 3
_SWD_DATA_BITS = 32
_SWD_PARITY_BITS = 1
_SWD_TURNAROUND_BITS = 1  # × 2 turnaround periods
_SWD_LINE_RESET_MIN_CYCLES = 50

_SWD_ACK_CODES = {"OK": "001", "WAIT": "010", "FAULT": "100"}

_SWJ_DP_JTAG_TO_SWD_HEX = "0xE79E"
_SWJ_DP_SWD_TO_JTAG_HEX = "0xE73C"

_SWD_REQUEST_FIELDS = [
    {"bit": 0, "name": "Start",  "value": "1",                "description": "Always 1 — marks the beginning of a request packet."},
    {"bit": 1, "name": "APnDP",  "value": "0=DP, 1=AP",       "description": "Selects which register space: DP (debug port) or AP (access port)."},
    {"bit": 2, "name": "RnW",    "value": "0=Write, 1=Read",  "description": "Read/write select."},
    {"bit": 3, "name": "A[2]",   "value": "0 or 1",           "description": "Register address bit 2."},
    {"bit": 4, "name": "A[3]",   "value": "0 or 1",           "description": "Register address bit 3."},
    {"bit": 5, "name": "Parity", "value": "even parity of bits 1..4", "description": "Even parity over APnDP + RnW + A[2] + A[3]."},
    {"bit": 6, "name": "Stop",   "value": "0",                "description": "Always 0."},
    {"bit": 7, "name": "Park",   "value": "1",                "description": "Always 1 — drives SWDIO HIGH before Turnaround."},
]

_SWD_MEMAP_REGISTERS = [
    {"name": "CSW",  "offset": "0x00", "purpose": "Control & Status Word — AddrInc[5:4] (Off/Single/Packed), Size[2:0] (8/16/32/64-bit), DbgSwEnable, Prot[6:0], Mode[3:0], TrInProg, DeviceEn."},
    {"name": "TAR",  "offset": "0x04", "purpose": "Transfer Address Register — 32-bit system-bus address used by the next DRW transfer; auto-incremented per CSW.AddrInc."},
    {"name": "DRW",  "offset": "0x0C", "purpose": "Data Read/Write — data conduit; read returns value at TAR (posted), write pushes value to TAR on the system bus."},
    {"name": "BD0",  "offset": "0x10", "purpose": "Banked Data 0 — direct access at TAR[31:4]+0x00."},
    {"name": "BD1",  "offset": "0x14", "purpose": "Banked Data 1 — at TAR[31:4]+0x04."},
    {"name": "BD2",  "offset": "0x18", "purpose": "Banked Data 2 — at TAR[31:4]+0x08."},
    {"name": "BD3",  "offset": "0x1C", "purpose": "Banked Data 3 — at TAR[31:4]+0x0C."},
    {"name": "MBT",  "offset": "0x20", "purpose": "Memory Barrier Transfer (optional)."},
    {"name": "CFG",  "offset": "0xF4", "purpose": "Configuration — Big-endian / Long-address / Large-data support indicators."},
    {"name": "BASE", "offset": "0xF8", "purpose": "ROM Table base address — bits[31:12] point to the 4 KB CoreSight ROM Table."},
    {"name": "IDR",  "offset": "0xFC", "purpose": "Identification Register — Type (0=JTAG-AP, 1=AHB3-AP, 2=APB-AP, 4=AXI-AP), Variant, Class, JEP106 designer."},
]


def apply_swd_synth(generated_docs_dir: Path,
                    is_swd: bool,
                    swd_ic_name: Optional[str]) -> None:
    """Apply SWD-specific synth when the structural signature matched.

    fail-open contract: print errors but never raise.
    """
    if not is_swd:
        return
    gd = Path(generated_docs_dir)

    try:
        # Force ic_name across the 14 main L docs (L1-L23 + L8 timing).
        # This OVERRIDES any JTAG synth that fired earlier — the SWD spec
        # talks about TAP/JTAG extensively because of SWJ-DP.
        if swd_ic_name is not None:
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
                    d["ic_name"] = swd_ic_name  # FORCE overwrite (not setdefault)
                    _write(q, d)

        _l1(gd, swd_ic_name)
        _l2(gd, swd_ic_name)
        _l3(gd, swd_ic_name)
        _l4(gd, swd_ic_name)
        _l5(gd, swd_ic_name)
        _l6(gd, swd_ic_name)
        _l7(gd, swd_ic_name)
        _l8_rtl(gd, swd_ic_name)
        _l8_timing(gd, swd_ic_name)
        _l9(gd, swd_ic_name)
        _l10(gd, swd_ic_name)
        _l11(gd, swd_ic_name)
        _l12(gd, swd_ic_name)
        _l13(gd, swd_ic_name)
        _l14(gd, swd_ic_name)
        _l15(gd, swd_ic_name)
        _l16(gd, swd_ic_name)
        _l17(gd, swd_ic_name)
        _l18(gd, swd_ic_name)
        _l19(gd, swd_ic_name)
        _l20(gd, swd_ic_name)
        _l21(gd, swd_ic_name)
        _l22(gd, swd_ic_name)
        _l23(gd, swd_ic_name)
    except Exception as exc:  # fail-open
        print(f"[swd_protocol_synth] WARN: {exc}")


# ============================================================
# L1 DATASHEET — FORCE overwrite JTAG-shaped keys
# ============================================================
def _l1(gd: Path, ic_name: Optional[str]) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    # FORCE overwrites — JTAG synth may have written TAP-shaped content here.
    d["document_title"] = "ARM Debug Interface v5 Architecture Specification (ADIv5) — Serial Wire Debug Port (SW-DP)"
    d["document_number"] = "ARM IHI 0031C (and successor IHI 0031D / IHI 0074)"
    d["version"] = "ADIv5.0 / ADIv5.1 / ADIv5.2 (ARM IHI 0031C documents the ADIv5 family; later errata add ADIv5.2 features)"
    d["revised_date"] = "2013-2022 (multi-revision)"
    d["original_release_date"] = "2006 (ADIv5.0 first released by ARM as part of CoreSight)"
    d["manufacturer"] = "Arm Limited (specification owner). Implemented by Arm Holdings in CoreSight DAP IP and licensed to all CoreSight-compliant SoC vendors."
    d["copyright"] = "Copyright © 2006-2022 Arm Limited (or its affiliates). All rights reserved."
    d["abstract"] = (
        "ARM Debug Interface v5 (ADIv5) defines the standardized debug-access architecture used by all "
        "Arm Cortex-M, Cortex-R, and Cortex-A SoCs. SWD is the 2-wire variant of the same Debug Access "
        "Port (DAP) — SWDIO (bidirectional data) + SWCLK (host-driven clock) replace the 4-wire JTAG TAP "
        "(TCK/TMS/TDI/TDO) used by ADIv5's JTAG-DP variant. SWJ-DP is a mode-switchable controller that "
        "supports both protocols and selects between them via a 16-bit JTAG-to-SWD (0xE79E) or SWD-to-JTAG "
        "(0xE73C) selection sequence. Above the DP layer, ADIv5 defines an Access Port (AP) bus with up to "
        "256 APs selected via the APSEL register; the most common AP is MEM-AP (memory-mapped access to "
        "the SoC's debug bus). CoreSight ROM Tables published at the MEM-AP BASE address enumerate the "
        "SoC's debug components."
    )
    d["keywords"] = [
        "SWD", "Serial Wire Debug", "ADIv5", "ARM Debug Interface", "DAP", "DP", "AP", "MEM-AP",
        "SWJ-DP", "SW-DP", "JTAG-DP", "CoreSight", "ROM Table", "IDCODE", "DPIDR", "TARGETID",
        "DLPIDR", "Cortex-M debug",
    ]
    d["external_pins"] = [
        "SWCLK (Serial Wire Clock, host → target, input at target)",
        "SWDIO (Serial Wire Data Input/Output, bidirectional, host ↔ target)",
        "(Optional) nTRST — only present when the SWJ-DP variant exposes TRST",
        "(Optional) SWO — Serial Wire Output trace pin (separate from SWD protocol)",
    ]
    d["external_pin_count"] = 4
    d["mandatory_pin_count"] = 2
    d["optional_pin_count"] = 2
    d["key_features"] = [
        "Two-wire reduced-pin debug interface: SWDIO (bidirectional data) + SWCLK (host-driven clock) replace the 4-wire JTAG TAP for resource-constrained MCUs.",
        "SWJ-DP (Serial Wire / JTAG Debug Port) is mode-switchable between SWD and JTAG via a 16-bit selection sequence (JTAG-to-SWD = 0xE79E; SWD-to-JTAG = 0xE73C) on TMS/SWDIO.",
        "Standard 46-bit SWD transaction: 8-bit Request + 1-bit Turnaround + 3-bit ACK (OK=001/WAIT=010/FAULT=100) + 32-bit Data + 1-bit Parity + 1-bit Turnaround.",
        "Half-duplex per cycle: SWDIO is host-driven during Request and Data-Write, target-driven during ACK and Data-Read.",
        "ADIv5 DAP two-layer architecture: Debug Port (DP) layer + Access Port (AP) layer (up to 256 APs).",
        "DP register catalog: ABORT, IDCODE/DPIDR, CTRL/STAT, SELECT, RDBUFF, TARGETID, DLPIDR, EVENTSTAT.",
        "MEM-AP register catalog: CSW, TAR, DRW, BD0-BD3, MBT, CFG, BASE, IDR.",
        "JTAG-AP variant: forwards AP transactions over a downstream legacy JTAG TAP daisy chain.",
        "Auto-increment on TAR (CSW.AddrInc): single-incrementing or packed-incrementing for sequential memory bursts.",
        "WAIT retry: target returns WAIT (010) when busy; host must retry. FAULT (100) signals sticky error; host reads CTRL/STAT, writes ABORT to clear.",
        "Posted reads: read data of transaction N is returned with the ACK of transaction N+1; final read recovered via DP RDBUFF.",
        "32-bit IDCODE/DPIDR register: DP designer (JEP106), DP architecture revision, DP version.",
        "CoreSight ROM Table at MEM-AP BASE address enumerates the SoC's debug components.",
        "Protocol-error escape: 50 consecutive SWCLK cycles with SWDIO=HIGH = line reset.",
    ]
    d["topology_summary"] = (
        "A single debug host (USB-to-SWD probe such as J-Link, ST-Link, CMSIS-DAP) drives SWCLK out and "
        "tri-states/drives SWDIO bidirectionally to the target SoC's SWD-DP or SWJ-DP. The DAP sits "
        "between the wire-level SWD-DP and the on-chip Debug Bus (AXI / AHB / APB) reached via one or "
        "more APs (MEM-AP, JTAG-AP, etc.). Multi-drop SWD (ADIv5.2) allows two or more targets to share "
        "SWDIO/SWCLK with per-target selection via TARGETSEL."
    )
    if _empty(d.get("revision_history")):
        d["revision_history"] = [
            {"version": "ADIv5.0 (initial)",   "date": "2006",        "description": "Initial release of ADIv5 alongside CoreSight; SW-DP / JTAG-DP / SWJ-DP defined; MEM-AP; JTAG-AP."},
            {"version": "ADIv5.1",             "date": "2009",        "description": "Added TARGETID + DLPIDR + EVENTSTAT registers; clarified Posted-Read semantics."},
            {"version": "ADIv5.2",             "date": "2017 onward", "description": "Multi-drop SWD with TARGETSEL-based per-target selection; refined DLPIDR fields."},
            {"version": "ADIv6 (successor)",   "date": "2019+",       "description": "Successor architecture (Arm IHI 0074); ADIv5 remains baseline across all Cortex-M."},
        ]
    d["use_cases"] = [
        "Cortex-M MCU in-system debug: halt/resume, single-step, breakpoints, watchpoints.",
        "Cortex-M flash programming via MEM-AP's AHB-Lite access to the on-chip flash controller.",
        "CoreSight ITM / DWT printf-style trace readout (via separate SWO trace pin).",
        "Power-on debug: reaching halt state before the application's first instruction.",
        "Multi-core SoC debug coordination via per-core MEM-APs and CTI.",
        "Production / factory test of MCUs over the 2-pin SWD connector.",
        "Multi-drop SWD daisy-chain probing of dual-core or multi-die SoCs from a single 2-pin connector (ADIv5.2).",
    ]
    d["overview"] = (
        "ARM Debug Interface v5 (ADIv5) is the universal debug-access architecture that every Arm "
        "Cortex-based SoC implements. The architecture is split into two layers: a wire-level Debug Port "
        "(DP) that brings transactions onto the chip, and an Access Port (AP) bus that fans those "
        "transactions out to one or more system buses on the SoC. JTAG-DP is the 4-pin variant; SW-DP is "
        "the 2-pin variant; SWJ-DP is a mode-switchable controller that supports both, selected at "
        "runtime via 16-bit JTAG-to-SWD (0xE79E) or SWD-to-JTAG (0xE73C) selection sequences. The SWD "
        "protocol uses a strict 46-bit transaction format: an 8-bit host-driven Request packet, a 1-bit "
        "Turnaround, a 3-bit target-driven Acknowledge (OK=001 / WAIT=010 / FAULT=100), a 32-bit Data "
        "field plus 1 parity bit, and a final 1-bit Turnaround. The DP exposes IDCODE/DPIDR, ABORT, "
        "CTRL/STAT, SELECT, RDBUFF, and (ADIv5.1+) TARGETID/DLPIDR/EVENTSTAT registers. The AP layer "
        "supports up to 256 APs selected via SELECT.APSEL; the canonical AP is MEM-AP."
    )
    # FORCE-overwrite block_diagram_components (JTAG would have written TAP-shaped components).
    d["block_diagram_components"] = [
        "Debug Host / SWD Probe (drives SWCLK; bidirectional SWDIO)",
        "SWJ-DP Wire-Level Controller (mode-switchable SWD ↔ JTAG; SWD bit-shift register; 46-bit transaction state machine)",
        "SW-DP / JTAG-DP Debug Port Layer (DPIDR + ABORT + CTRL/STAT + SELECT + RDBUFF + TARGETID + DLPIDR + EVENTSTAT)",
        "Access Port Bus (selects up to 256 APs via SELECT.APSEL[7:0])",
        "MEM-AP Instance(s) (CSW + TAR + DRW + BD0-BD3 + MBT + CFG + BASE + IDR)",
        "JTAG-AP Instance (forwards DAP transactions to a downstream legacy JTAG TAP daisy chain)",
        "CoreSight Debug Bus (AHB / AXI / APB inside the SoC, reached by MEM-AP)",
        "CoreSight ROM Table (publishes the SoC's debug component catalog at the MEM-AP BASE address)",
        "Debug Components reachable via the bus (CPU debug registers, ETM, ITM, DWT, FPB, CTI, TPIU, ROM-of-ROMs)",
        "Optional SWO trace pin output (separate output controlled via the MEM-AP-reachable TPIU)",
    ]
    d["industry_standard_basis"] = (
        "ARM IHI 0031C — ARM Debug Interface v5 Architecture Specification (and later IHI 0031D / "
        "IHI 0074 revisions). Maintained by Arm Limited. SWD is layered on top of ADIv5's Debug Port "
        "architecture and complements the 4-pin JTAG-DP variant defined by the same specification. "
        "CoreSight ROM Table format is defined by the companion CoreSight Architecture Specification "
        "(ARM IHI 0029)."
    )
    _write(p, d)


# ============================================================
# L2 FRS
# ============================================================
def _l2(gd: Path, ic_name: Optional[str]) -> None:
    p = gd / "L2_FRS.json"
    if not p.is_file():
        return
    d = _read(p)
    # FORCE overwrite protocol_overview — JTAG synth fills this with TAP-shaped content.
    d["protocol_overview"] = {
        "type": (
            "Synchronous serial half-duplex 2-wire debug protocol; host-driven SWCLK plus bidirectional "
            "SWDIO; strict 46-bit transaction format (8-bit Request + 1-bit Turnaround + 3-bit ACK + "
            "33-bit Data + 1-bit Turnaround) per AP/DP register access."
        ),
        "duplex": (
            "half-duplex per cycle on SWDIO with explicit 1-bit Turnaround periods between host-driven "
            "and target-driven phases."
        ),
        "synchronous": True,
        "wire_names_mandatory": ["SWCLK", "SWDIO"],
        "wire_names_optional": ["nTRST (only in SWJ-DP variants exposing TRST)", "SWO (separate trace pin)"],
        "wire_count_mandatory": 2,
        "wire_count_with_optional": 4,
        "transaction_total_bits": _SWD_TRANSACTION_TOTAL_BITS,
        "transaction_format_breakdown": {
            "request_bits": _SWD_REQUEST_BITS,
            "turnaround_1_bits": _SWD_TURNAROUND_BITS,
            "acknowledge_bits": _SWD_ACK_BITS,
            "data_bits": _SWD_DATA_BITS,
            "data_parity_bits": _SWD_PARITY_BITS,
            "turnaround_2_bits": _SWD_TURNAROUND_BITS,
        },
        "ack_codes": _SWD_ACK_CODES,
        "controller_role": (
            "Debug host (USB-to-SWD probe such as J-Link / ST-Link / CMSIS-DAP) drives SWCLK out and "
            "bidirectionally drives or tri-states SWDIO; sequences 46-bit transactions; sets SELECT for "
            "AP+bank addressing; reads RDBUFF to recover the final posted read."
        ),
        "target_role": (
            "Target SoC implements SW-DP (or SWJ-DP) at the wire layer + DP register set + one or more "
            "APs (MEM-AP, JTAG-AP, etc.); decodes 8-bit Request, drives the 3-bit ACK, and either drives "
            "the 33-bit read data + parity (for reads) or samples the 33-bit write data + parity (for writes)."
        ),
    }
    fr = [
        {"id": "FR-PINS-01",       "text": "The SWD interface shall provide two dedicated pins: SWCLK (host-driven clock) and SWDIO (bidirectional data). SWJ-DP additionally accepts JTAG-style 4-pin operation via the same pads."},
        {"id": "FR-TXN-02",        "text": "Each SWD transaction shall consist of exactly 46 bits in this order: 8-bit Request + 1-bit Turnaround + 3-bit Acknowledge + 32-bit Data + 1-bit Data Parity + 1-bit Turnaround."},
        {"id": "FR-REQ-03",        "text": "The 8-bit Request packet shall be: bit0=Start=1, bit1=APnDP, bit2=RnW, bit3=A[2], bit4=A[3], bit5=Parity over APnDP+RnW+A[2:3], bit6=Stop=0, bit7=Park=1. Transmitted LSB-first on SWDIO synchronous to SWCLK rising edges."},
        {"id": "FR-ACK-04",        "text": "The 3-bit Acknowledge field shall encode one of: OK=001, WAIT=010, FAULT=100. OK = target accepted; WAIT = target busy (retry); FAULT = sticky error (read CTRL/STAT, write ABORT, retry)."},
        {"id": "FR-DATA-05",       "text": "The 32-bit Data field shall be transmitted LSB-first synchronous to SWCLK rising edges. The 33rd bit shall be the even parity of the 32 data bits."},
        {"id": "FR-TURNAROUND-06", "text": "Two 1-bit Turnaround periods shall be present in every transaction: one before the ACK and one after the Data field. The number of turnaround cycles is governed by CTRL/STAT.TRNCNT and defaults to 1."},
        {"id": "FR-DP-07",         "text": "The Debug Port (DP) shall implement at minimum the registers IDCODE/DPIDR (0x0, read), ABORT (0x0, write), CTRL/STAT (0x4), SELECT (0x8, write), and RDBUFF (0xC, read). ADIv5.1+ adds TARGETID, DLPIDR, EVENTSTAT in higher banks."},
        {"id": "FR-AP-08",         "text": "Up to 256 Access Ports (APs) may be present in a single DAP; the active AP is selected by SELECT.APSEL[31:24]. Each AP exposes 64 bytes (16 × 32-bit registers) banked by SELECT.APBANKSEL[7:4]; IDR and BASE are at fixed offsets 0xFC and 0xF8."},
        {"id": "FR-MEMAP-09",      "text": "The canonical AP shall be MEM-AP, exposing: CSW (0x00), TAR (0x04), DRW (0x0C), BD0-BD3 (0x10-0x1C), MBT (0x20), CFG (0xF4), BASE (0xF8), IDR (0xFC). Reads/writes via DRW use the current TAR value as the system-bus address."},
        {"id": "FR-POSTED-READ-10","text": "AP reads shall be posted: the ACK of read N returns OK/WAIT/FAULT for read N-1 and the host receives the read-N-1 data with the ACK of transaction N+1 (or via DP.RDBUFF if N is the final read)."},
        {"id": "FR-WAIT-11",       "text": "When the target returns WAIT (010), the host shall retry the same request after one or more SWCLK cycles. WAIT retries are not counted against any maximum retry limit at the protocol layer."},
        {"id": "FR-FAULT-12",      "text": "When the target returns FAULT (100), one or more sticky error bits in CTRL/STAT have been set (STICKYORUN, STICKYCMP, STICKYERR, WDATAERR). Host must read CTRL/STAT, write ABORT with the clear bits, then retry."},
        {"id": "FR-LINERESET-13",  "text": "A line-reset sequence — at least 50 consecutive SWCLK cycles with SWDIO held HIGH — shall return the SW-DP to a known reset state. The host shall then perform a fresh DP IDCODE/DPIDR read on the first transaction."},
        {"id": "FR-SWJ-SEL-14",    "text": "An SWJ-DP-equipped target shall accept the JTAG-to-SWD selection sequence (16-bit pattern 0xE79E shifted LSB-first on TMS/SWDIO after ≥ 50 cycles of TMS=1) and the SWD-to-JTAG sequence (16-bit pattern 0xE73C)."},
        {"id": "FR-IDCODE-15",     "text": "The 32-bit IDCODE/DPIDR register (DP offset 0x0 read) shall identify the DP: DPIDR.DESIGNER[31:28] / PARTNO[27:20] / MIN[16] / VERSION[15:12] / REVISION[3:0]. Bit 0 = 1 (RAO). The host's first transaction post-reset shall be an IDCODE/DPIDR read."},
        {"id": "FR-AUTOINC-16",    "text": "MEM-AP shall support auto-increment of TAR controlled by CSW.AddrInc[5:4]: Off, Single (TAR += transfer size after each DRW), Packed (multiple sub-word transfers per DRW). Auto-increment must wrap correctly at 4 KB boundaries."},
        {"id": "FR-MULTIDROP-17",  "text": "ADIv5.2 multi-drop SWD: bus shall support multiple targets sharing SWDIO/SWCLK with per-target selection via DP TARGETSEL after line reset + JTAG-to-SWD sequence."},
    ]
    if _empty(d.get("functional_requirements")):
        d["functional_requirements"] = fr
    # FORCE overwrite configurations (JTAG synth fills with TAP-style daisy-chain)
    d["configurations"] = [
        {"name": "Pure SWD-DP target",   "description": "The SoC implements only the 2-pin SW-DP variant — no JTAG support."},
        {"name": "SWJ-DP target",        "description": "The SoC implements the mode-switchable SWJ-DP — supports both SWD (2-pin) and JTAG (4-pin) on the same pads."},
        {"name": "Multi-drop SWD",       "description": "Two or more SWJ-DP targets share SWDIO/SWCLK on a single 2-wire connector (ADIv5.2+)."},
        {"name": "Single-MEM-AP DAP",    "description": "A DAP with exactly one MEM-AP exposing a single system-bus (typical Cortex-M0/M0+ implementation)."},
        {"name": "Multi-AP DAP",         "description": "A DAP with multiple APs — typical Cortex-A or multi-core SoCs."},
    ]
    d["error_response_conditions"] = [
        "ACK=WAIT (010) — target busy; host must retry. Not a sticky error.",
        "ACK=FAULT (100) — sticky error bits set in CTRL/STAT: STICKYORUN, STICKYCMP, STICKYERR, WDATAERR.",
        "Protocol error — ACK pattern other than OK/WAIT/FAULT. Host should perform 50-cycle line reset.",
        "Data parity error on write — target sets WDATAERR in CTRL/STAT; subsequent transaction returns FAULT.",
        "Data parity error on read — host detects locally; not signaled by target.",
        "TARGETSEL mismatch (multi-drop) — target ignores subsequent transactions until line reset + new TARGETSEL.",
    ]
    d["compliance_requirements"] = [
        "Both mandatory pins SWCLK and SWDIO shall be present, with SWDIO bidirectional.",
        "Every transaction shall be exactly 46 bits in the order Request + Turnaround + ACK + Data + Parity + Turnaround.",
        "The 8-bit Request packet shall have Start=1, Stop=0, Park=1; Parity is even-parity over APnDP+RnW+A[2:3].",
        "The 3-bit ACK shall be OK=001, WAIT=010, FAULT=100 (no other valid encodings).",
        "Data shall be transmitted LSB-first synchronous to SWCLK rising edges; the 33rd bit shall be even parity.",
        "Turnaround periods shall be at least 1 SWCLK cycle each (configurable up to 4 via CTRL/STAT.TRNCNT).",
        "A 50-SWCLK-cycle SWDIO-HIGH line reset shall return the SW-DP to a known state from any state.",
        "Reading IDCODE/DPIDR shall be the host's first transaction post-reset.",
        "MEM-AP shall implement CSW + TAR + DRW + IDR + BASE at minimum.",
        "If SWJ-DP, both 16-bit selection sequences (0xE79E and 0xE73C) shall be recognized.",
    ]
    _write(p, d)


# ============================================================
# L3 CMD PROTOCOL — FORCE overwrite (JTAG synth fills with TAP-shaped data)
# ============================================================
def _l3(gd: Path, ic_name: Optional[str]) -> None:
    p = gd / "L3_CMD_PROTOCOL.json"
    if not p.is_file():
        return
    d = _read(p)
    # Remove any JTAG-specific fields that may have been set (e.g.
    # instructions_mandatory, instructions_optional, post_reset_default_instruction).
    for jtag_only_key in [
        "instructions_mandatory",
        "instructions_optional",
        "post_reset_default_instruction",
        "data_register_catalog",
    ]:
        if jtag_only_key in d:
            d.pop(jtag_only_key, None)

    d["protocol_type"] = (
        "Strict 46-bit transaction protocol over 2-wire half-duplex serial: 8-bit Request (host) + "
        "1-bit Turnaround + 3-bit ACK (target) + 32-bit Data + 1-bit Data Parity + 1-bit Turnaround. "
        "The Request packet's APnDP + RnW + A[2:3] bits select which DP or AP register is being read or "
        "written. AP register banking goes through the DP SELECT register first."
    )
    d["request_packet_format"] = {
        "total_bits": _SWD_REQUEST_BITS,
        "transmit_order": "LSB first on SWDIO synchronous to SWCLK rising edges",
        "field_breakdown": list(_SWD_REQUEST_FIELDS),
    }
    d["ack_packet_format"] = {
        "total_bits": _SWD_ACK_BITS,
        "transmit_order": "LSB first on SWDIO synchronous to SWCLK rising edges (target-driven)",
        "valid_codes": [
            {"code": "001", "name": "OK",    "meaning": "Target accepted the request; data field is valid."},
            {"code": "010", "name": "WAIT",  "meaning": "Target busy. Host must retry. Data field is meaningless."},
            {"code": "100", "name": "FAULT", "meaning": "Sticky error has occurred (read CTRL/STAT, write ABORT, retry). Data field is meaningless."},
        ],
        "invalid_codes": "Any 3-bit pattern other than 001/010/100 is a protocol error. Host should line-reset and re-IDCODE-read.",
    }
    d["data_packet_format"] = {
        "total_bits": _SWD_DATA_BITS + _SWD_PARITY_BITS,
        "data_bits": _SWD_DATA_BITS,
        "parity_bits": _SWD_PARITY_BITS,
        "transmit_order": "LSB first on SWDIO synchronous to SWCLK rising edges",
        "parity_rule": "Single-bit even parity over the 32 data bits. On writes, host generates; target checks. On reads, target generates; host checks.",
        "direction": "Host-driven on writes, target-driven on reads.",
    }
    d["transaction_anatomy_46_bits"] = {
        "phase_1_request":      {"bits": "0..7",   "direction": "host → target",     "description": "8-bit Request packet."},
        "phase_2_turnaround_a": {"bits": "8",      "direction": "transitional",      "description": "1-bit Turnaround period — SWDIO transitions from host-driven to target-driven."},
        "phase_3_ack":          {"bits": "9..11",  "direction": "target → host",     "description": "3-bit Acknowledge packet."},
        "phase_4_data":         {"bits": "12..43", "direction": "write: host → target / read: target → host", "description": "32-bit Data field."},
        "phase_5_parity":       {"bits": "44",     "direction": "same as data field","description": "1-bit Data Parity."},
        "phase_6_turnaround_b": {"bits": "45",     "direction": "transitional",      "description": "1-bit Turnaround period — SWDIO transitions back to host-driven."},
    }
    d["dp_register_catalog"] = [
        {"name": "ABORT",       "address": "0x0", "access": "Write", "purpose": "Write-1-to-clear sticky errors; DAPABORT to cancel in-flight AP transaction."},
        {"name": "IDCODE/DPIDR","address": "0x0", "access": "Read",  "purpose": "Identifies DP: DESIGNER + PARTNO + VERSION + REVISION + MIN."},
        {"name": "CTRL/STAT",   "address": "0x4", "access": "Read/Write", "purpose": "Control + sticky status bits + power-up handshake (CSYSPWRUPREQ/ACK, CDBGPWRUPREQ/ACK)."},
        {"name": "SELECT",      "address": "0x8", "access": "Write", "purpose": "Bank select: APSEL + APBANKSEL + DPBANKSEL."},
        {"name": "RDBUFF",      "address": "0xC", "access": "Read",  "purpose": "Returns data of previous posted AP read."},
        {"name": "TARGETID",    "address": "0x4 (bank 2)", "access": "Read", "purpose": "ADIv5.1+; identifies target SoC."},
        {"name": "DLPIDR",      "address": "0x4 (bank 3)", "access": "Read", "purpose": "ADIv5.1+; multi-drop SWD target instance."},
        {"name": "EVENTSTAT",   "address": "0x4 (bank 4)", "access": "Read", "purpose": "ADIv5.1+; per-target event status."},
    ]
    d["ap_address_decoding"] = {
        "ap_register_window_size_bytes": 64,
        "ap_register_count": 16,
        "ap_address_bits_per_register": "A[3:2]",
        "ap_bank_selection": "SELECT.APBANKSEL[7:4]",
        "ap_index_selection": "SELECT.APSEL[31:24] (8 bits) selects 1 of 256 APs",
    }
    d["memap_register_catalog"] = list(_SWD_MEMAP_REGISTERS)
    # FORCE overwrite channels (JTAG would have written TCK/TMS/TDI/TDO)
    d["channels"] = [
        {"name": "SWCLK", "direction": "host → target", "description": "Serial Wire Clock. Host-driven free-running clock during a transaction."},
        {"name": "SWDIO", "direction": "bidirectional (host ↔ target)", "description": "Serial Wire Data Input/Output. Host-driven during Request and Data-Write phases; target-driven during ACK and Data-Read phases."},
    ]
    d["valid_ready_handshake_rules"] = [
        "Explicit Turnaround: a 1-bit Turnaround SWCLK cycle is mandatory between every host-driven phase and target-driven phase. CTRL/STAT.TRNCNT may extend up to 4 cycles.",
        "Per-transaction ACK: target signals OK/WAIT/FAULT in every transaction.",
        "Posted reads: data of read N is delivered with the ACK of transaction N+1, or via DP.RDBUFF.",
        "No per-byte CRC — single-bit parity over Request fields and over the 32-bit Data field is the only protocol integrity check.",
        "Line reset: 50 SWCLK cycles with SWDIO=HIGH unconditionally returns the SW-DP to a known state.",
    ]
    d["burst_based"] = False
    d["byte_oriented"] = False
    d["bit_oriented"] = True
    # FORCE overwrite frame_format (JTAG synth fills with IR/DR-scan content)
    d["frame_format"] = {
        "transaction_total_bits": _SWD_TRANSACTION_TOTAL_BITS,
        "byte_breakdown": "8-bit Request + 1-bit Turnaround + 3-bit ACK + 32-bit Data + 1-bit Parity + 1-bit Turnaround = 46 bits.",
        "bit_order": "LSB first throughout.",
        "line_reset_sequence": "At least 50 SWCLK cycles with SWDIO held HIGH; resets the SW-DP wire-level state.",
    }
    _write(p, d)


# ============================================================
# L4 REGMAP — FORCE overwrite (JTAG synth fills with IR/Bypass/BSR/IDCODE catalog)
# ============================================================
def _l4(gd: Path, ic_name: Optional[str]) -> None:
    p = gd / "L4_REGMAP.json"
    if not p.is_file():
        return
    d = _read(p)
    d["register_map_present"] = True
    d["register_map_kind"] = (
        "Two-layer register architecture: DP layer (Debug Port, accessed directly via SWD transactions "
        "with APnDP=0) + AP layer (Access Port, accessed with APnDP=1; up to 256 APs selected via "
        "SELECT.APSEL[7:0], each exposing a 64-byte register window banked via SELECT.APBANKSEL[7:4])."
    )
    d["base_address"] = (
        "DP registers are at addresses 0x0/0x4/0x8/0xC (A[2:3] encoded into the Request packet); each AP "
        "exposes 64 bytes (16 registers) at offsets 0x00..0x3C via A[2:3] + APBANKSEL banking; AP IDR is "
        "at fixed offset 0xFC, BASE at 0xF8."
    )
    d["register_count"] = 12
    # FORCE-overwrite registers (JTAG would have written IR/Bypass/BSR/IDCODE).
    d["registers"] = [
        {
            "name": "ABORT",
            "long_name": "DP Abort Register",
            "ap_or_dp": "DP",
            "offset": "0x0 (write)",
            "width_bits": 32,
            "access": "Write-only",
            "reset_value": "N/A (write-1-to-clear)",
            "purpose": "Aborts an in-flight AP transaction and clears sticky error bits in CTRL/STAT.",
            "field_map": [
                {"bits": "0", "name": "DAPABORT",   "description": "Generate a DAP abort."},
                {"bits": "1", "name": "STKCMPCLR",  "description": "Clear CTRL/STAT.STICKYCMP."},
                {"bits": "2", "name": "STKERRCLR",  "description": "Clear CTRL/STAT.STICKYERR."},
                {"bits": "3", "name": "WDERRCLR",   "description": "Clear CTRL/STAT.WDATAERR."},
                {"bits": "4", "name": "ORUNERRCLR", "description": "Clear CTRL/STAT.STICKYORUN."},
            ],
        },
        {
            "name": "IDCODE/DPIDR",
            "long_name": "DP Identification Register",
            "ap_or_dp": "DP",
            "offset": "0x0 (read)",
            "width_bits": 32,
            "access": "Read-only",
            "reset_value": "Hard-wired at silicon mask level",
            "purpose": "Identifies the Debug Port. First transaction post-reset.",
            "field_map": [
                {"bits": "31:28", "name": "REVISION", "description": "Revision number of the DP design."},
                {"bits": "27:20", "name": "PARTNO",   "description": "DP part number."},
                {"bits": "16",    "name": "MIN",      "description": "Min DP version (0=ADIv5; 1=ADIv5.1+)."},
                {"bits": "15:12", "name": "VERSION",  "description": "DP architecture version."},
                {"bits": "11:1",  "name": "DESIGNER", "description": "JEP106 manufacturer ID."},
                {"bits": "0",     "name": "RAO",      "description": "Read-As-One; hard-wired to 1."},
            ],
        },
        {
            "name": "CTRL/STAT",
            "long_name": "DP Control / Status Register",
            "ap_or_dp": "DP",
            "offset": "0x4 (bank 0)",
            "width_bits": 32,
            "access": "Read/Write",
            "reset_value": "0x00000000",
            "purpose": "Sticky error status + power-up handshake + turnaround count.",
            "field_map": [
                {"bits": "0",  "name": "ORUNDETECT",  "description": "Overrun detection enable."},
                {"bits": "1",  "name": "STICKYORUN",  "description": "Sticky overrun bit (RW1C via ABORT.ORUNERRCLR)."},
                {"bits": "3:2","name": "TRNCNT",      "description": "Turnaround SWCLK cycle count (00=1, 11=4)."},
                {"bits": "12", "name": "WDATAERR",   "description": "Write Data Error sticky (RW1C via ABORT.WDERRCLR)."},
                {"bits": "13", "name": "READOK",     "description": "Read-OK status."},
                {"bits": "14", "name": "STICKYERR",  "description": "Sticky AP transfer error (RW1C via ABORT.STKERRCLR)."},
                {"bits": "15", "name": "STICKYCMP",  "description": "Sticky compare-match bit (RW1C via ABORT.STKCMPCLR)."},
                {"bits": "26", "name": "CDBGRSTREQ", "description": "Debug reset request."},
                {"bits": "27", "name": "CDBGRSTACK", "description": "Debug reset acknowledge."},
                {"bits": "28", "name": "CDBGPWRUPREQ","description": "Debug power-up request."},
                {"bits": "29", "name": "CDBGPWRUPACK","description": "Debug power-up acknowledge."},
                {"bits": "30", "name": "CSYSPWRUPREQ","description": "System power-up request."},
                {"bits": "31", "name": "CSYSPWRUPACK","description": "System power-up acknowledge."},
            ],
        },
        {
            "name": "SELECT",
            "long_name": "DP Select Register",
            "ap_or_dp": "DP",
            "offset": "0x8 (write)",
            "width_bits": 32,
            "access": "Write-only",
            "reset_value": "0x00000000",
            "purpose": "Banks the AP layer + DP higher-bank registers.",
            "field_map": [
                {"bits": "3:0",   "name": "DPBANKSEL", "description": "DP bank select."},
                {"bits": "7:4",   "name": "APBANKSEL", "description": "AP bank select."},
                {"bits": "31:24", "name": "APSEL",     "description": "AP select (1 of 256)."},
            ],
        },
        {
            "name": "RDBUFF",
            "long_name": "DP Read Buffer Register",
            "ap_or_dp": "DP",
            "offset": "0xC (read)",
            "width_bits": 32,
            "access": "Read-only",
            "purpose": "Returns the data of the most recent posted AP read.",
        },
        {
            "name": "TARGETID",
            "long_name": "DP Target Identification Register",
            "ap_or_dp": "DP",
            "offset": "0x4 (bank 2 — ADIv5.1+)",
            "width_bits": 32,
            "access": "Read-only",
            "purpose": "Identifies the target SoC.",
            "field_map": [
                {"bits": "31:28", "name": "TREVISION", "description": "Target revision."},
                {"bits": "27:12", "name": "TPARTNO",   "description": "Target part number."},
                {"bits": "11:1",  "name": "TDESIGNER", "description": "Target designer JEP106 ID."},
                {"bits": "0",     "name": "RAO",       "description": "Read-As-One."},
            ],
        },
        {
            "name": "DLPIDR",
            "long_name": "DP Data Link Protocol Identification Register",
            "ap_or_dp": "DP",
            "offset": "0x4 (bank 3 — ADIv5.1+ multi-drop)",
            "width_bits": 32,
            "access": "Read-only",
            "purpose": "Multi-drop SWD target instance.",
            "field_map": [
                {"bits": "31:28", "name": "TINSTANCE", "description": "Target instance number."},
                {"bits": "3:0",   "name": "PROTVSN",   "description": "Protocol version (0001 = ADIv5.2)."},
            ],
        },
        {
            "name": "EVENTSTAT",
            "long_name": "DP Event Status Register",
            "ap_or_dp": "DP",
            "offset": "0x4 (bank 4 — ADIv5.1+)",
            "width_bits": 32,
            "access": "Read-only",
            "purpose": "Per-target event status.",
        },
        {
            "name": "CSW",
            "long_name": "MEM-AP Control & Status Word",
            "ap_or_dp": "AP",
            "offset": "0x00",
            "width_bits": 32,
            "access": "Read/Write",
            "purpose": "MEM-AP transfer mode control.",
            "field_map": [
                {"bits": "2:0",   "name": "Size",        "description": "Transfer size (000=byte, 010=word, etc.)."},
                {"bits": "5:4",   "name": "AddrInc",     "description": "Auto-increment: 00=Off, 01=Single, 10=Packed."},
                {"bits": "7",     "name": "TrInProg",    "description": "Transfer-in-progress."},
                {"bits": "30:24", "name": "Prot",        "description": "Protection bits (HPROT/ARPROT)."},
                {"bits": "31",    "name": "DbgSwEnable", "description": "Software-debug enable."},
            ],
        },
        {
            "name": "TAR",
            "long_name": "MEM-AP Transfer Address Register",
            "ap_or_dp": "AP",
            "offset": "0x04",
            "width_bits": "32 (or 64 with TARLO+TARHI in ADIv5.2)",
            "access": "Read/Write",
            "purpose": "System-bus address used by the next DRW transfer.",
        },
        {
            "name": "DRW",
            "long_name": "MEM-AP Data Read/Write Register",
            "ap_or_dp": "AP",
            "offset": "0x0C",
            "width_bits": 32,
            "access": "Read/Write",
            "purpose": "Data conduit; read returns value at TAR (posted), write pushes value to TAR.",
        },
        {
            "name": "BASE",
            "long_name": "MEM-AP Debug Component ROM Table Base Register",
            "ap_or_dp": "AP",
            "offset": "0xF8",
            "width_bits": 32,
            "access": "Read-only",
            "purpose": "Points to the 4 KB CoreSight ROM Table.",
            "field_map": [
                {"bits": "0",     "name": "Present",  "description": "1 = ROM Table is present."},
                {"bits": "1",     "name": "Format",   "description": "0 = 32-bit; 1 = 64-bit (ADIv6)."},
                {"bits": "31:12", "name": "BASEADDR", "description": "ROM Table address bits[31:12]."},
            ],
        },
        {
            "name": "IDR",
            "long_name": "MEM-AP Identification Register",
            "ap_or_dp": "AP",
            "offset": "0xFC",
            "width_bits": 32,
            "access": "Read-only",
            "purpose": "Identifies the AP type and designer.",
            "field_map": [
                {"bits": "3:0",   "name": "Type",     "description": "AP type code."},
                {"bits": "7:4",   "name": "Variant",  "description": "Variant number."},
                {"bits": "16:13", "name": "Class",    "description": "AP class (8 = MEM-AP)."},
                {"bits": "23:17", "name": "JEP106",   "description": "JEP106 designer."},
                {"bits": "31:28", "name": "Revision", "description": "AP revision."},
            ],
        },
    ]
    d["selection_rule"] = (
        "DP registers are at A[3:2] = 0x0/0x4/0x8/0xC selected via APnDP=0. Higher-bank DP registers "
        "(TARGETID/DLPIDR/EVENTSTAT) are reached by writing SELECT.DPBANKSEL first. AP registers are at "
        "A[3:2] = 0x0/0x4/0x8/0xC selected via APnDP=1; the high 4 bits of the AP register offset come "
        "from SELECT.APBANKSEL; the AP index comes from SELECT.APSEL. AP IDR (0xFC) and BASE (0xF8) are "
        "at fixed high banks."
    )
    d["ap_class_codes_table"] = {
        "0x0": "JTAG-AP — forwards transactions to a downstream JTAG TAP",
        "0x1": "AMBA AHB3 MEM-AP",
        "0x2": "AMBA APB2/3 MEM-AP",
        "0x4": "AMBA AXI3/4 MEM-AP",
        "0x5": "AMBA AHB5 MEM-AP",
        "0x8": "AMBA APB4/5 MEM-AP",
    }
    d["notes"] = (
        "The DP and AP layers are orthogonal in addressing: APnDP=0 selects DP; APnDP=1 selects AP. "
        "DP addresses are not memory-mapped per se — they are encoded by A[3:2] bits in the 8-bit Request. "
        "AP addresses are encoded by SELECT.APSEL + APBANKSEL + A[3:2]. The MEM-AP variant adds an "
        "in-AP 32/64-bit TAR + DRW pair that maps to a wide system-bus address space."
    )
    # Strip any JTAG-leftover user_defined_data_registers / capture_value_in_CaptureIR keys.
    for k in ["user_defined_data_registers", "capture_value_in_CaptureIR"]:
        d.pop(k, None)
    _write(p, d)


# ============================================================
# L5 ADI SPEC
# ============================================================
def _l5(gd: Path, ic_name: Optional[str]) -> None:
    p = gd / "L5_ADI_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("analog_digital_interface_present", False)
    d["signaling_summary"] = (
        "Pure digital protocol. SWCLK and SWDIO are CMOS- or TTL-compatible digital signals at the "
        "target SoC's I/O voltage (typically 1.8 V / 2.5 V / 3.3 V / 5 V tolerant). ADIv5 does not "
        "specify absolute voltage levels at the protocol layer; per-device datasheets define VIH / VIL "
        "/ VOH / VOL. SWDIO is a bidirectional pin (push-pull or open-drain). The optional SWO trace "
        "pin is a target-driven output (asynchronous serial at ~1.8-50 MHz typical) carrying CoreSight "
        "ITM/DWT trace packets — separate from the SWD protocol."
    )
    _write(p, d)


# ============================================================
# L6 CONTROL LOGIC — FORCE overwrite (JTAG synth fills with 16-state TAP FSM)
# ============================================================
def _l6(gd: Path, ic_name: Optional[str]) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    # Remove JTAG-only keys.
    for jtag_key in [
        "fsm_states_tap_controller",
        "fsm_transition_table_tms_driven",
    ]:
        d.pop(jtag_key, None)

    d["fsm_summary"] = (
        "SWD wire-level state machine sequences each 46-bit transaction through 6 phases "
        "(Request → Turnaround → ACK → Data → Parity → Turnaround). SWDIO direction flips at the "
        "Turnaround periods. The SWJ-DP variant adds a mode-select state machine that watches for "
        "the 16-bit JTAG-to-SWD (0xE79E) and SWD-to-JTAG (0xE73C) selection sequences."
    )
    d["fsm_states_swd_transaction"] = [
        {"name": "Idle",            "kind": "stable",       "description": "Between transactions. SWDIO is host-driven HIGH."},
        {"name": "RequestRx",       "kind": "transient (8 SWCLK)", "description": "Target shifts in the 8-bit Request packet."},
        {"name": "RequestDecode",   "kind": "transient (combinational)", "description": "Target validates Start/Stop/Park and parity."},
        {"name": "TurnaroundA",     "kind": "transient (1 SWCLK, configurable 1-4)", "description": "Direction-change cycle."},
        {"name": "ACK_Drive",       "kind": "transient (3 SWCLK)", "description": "Target drives the 3-bit ACK."},
        {"name": "DataDrive_Read",  "kind": "transient (32 SWCLK)", "description": "Read + ACK=OK: target drives 32 data bits."},
        {"name": "DataDrive_Write", "kind": "transient (32 SWCLK)", "description": "Write + ACK=OK: host drives 32 data bits."},
        {"name": "ParityDrive_Read","kind": "transient (1 SWCLK)",  "description": "Read: target drives parity."},
        {"name": "ParityDrive_Write","kind": "transient (1 SWCLK)", "description": "Write: host drives parity; target checks → WDATAERR on mismatch."},
        {"name": "TurnaroundB",     "kind": "transient (1 SWCLK, configurable 1-4)", "description": "Direction-change cycle."},
        {"name": "WaitOrFault",     "kind": "transient", "description": "ACK=WAIT or FAULT: host ignores data."},
        {"name": "LineResetDetect", "kind": "background (always active)", "description": "Detects 50+ SWCLKs with SWDIO=HIGH; forces SW-DP Idle."},
    ]
    d["fsm_states_swj_dp_mode_select"] = [
        {"name": "JTAG_Mode",      "kind": "stable",     "description": "SWJ-DP in JTAG mode."},
        {"name": "WatchSWDSelect", "kind": "background", "description": "After ≥ 50 cycles TMS=1, watches for 0xE79E pattern."},
        {"name": "SWD_Mode",       "kind": "stable",     "description": "SWJ-DP in SWD mode."},
        {"name": "WatchJTAGSelect","kind": "background", "description": "After ≥ 50 cycles SWDIO=1, watches for 0xE73C pattern."},
    ]
    # FORCE overwrite fsm_hints — JTAG synth fills this with TMS/TCK-driven hints.
    d["fsm_hints"] = {
        "clock":           "SWCLK is host-driven and free-running during a transaction.",
        "sampling_edge":   "Target samples SWDIO on SWCLK rising edge during Request and Data-Write phases.",
        "drive_edge":      "Target drives SWDIO on SWCLK falling edge during ACK and Data-Read phases.",
        "abort":           "50 consecutive SWCLK cycles with SWDIO=HIGH = line reset.",
        "transaction_overlap": "Posted reads: data of read N delivered with ACK of read N+1.",
        "instruction_change_path": "Switching from DP to AP transactions requires writing DP.SELECT first.",
    }
    d["anti_deadlock_rule"] = (
        "50-cycle line reset is the universal escape — there is no SWD state from which this sequence "
        "does not return to Idle. Guarantees host can always recover SWD without power-cycling."
    )
    d["exit_from_reset_or_poweron"] = (
        "On power-up, SW-DP starts quiescent; host's first action is a 50-cycle line reset followed by "
        "an IDCODE/DPIDR read. On line reset, SELECT and CTRL/STAT are cleared, AP selection resets to "
        "APSEL=0/APBANKSEL=0, and the posted-read queue is drained. DPIDR is hard-wired and always available."
    )
    # FORCE overwrite default_ready_state_recommendation — JTAG synth uses TCK/TMS/TDI/TDO/TRST.
    d["default_ready_state_recommendation"] = {
        "SWCLK": "Idle level not specified; debug probe drives. Most probes leave SWCLK low between transactions.",
        "SWDIO": "Idle level HIGH (line-reset compatible).",
    }
    # FORCE overwrite configurations
    d["configurations"] = [
        {"name": "Single-target SWD",     "description": "One SoC on the SWD bus; host directly drives SWCLK/SWDIO."},
        {"name": "Multi-drop SWD",        "description": "Multiple SoCs share SWDIO/SWCLK; per-target selection via DP TARGETSEL (ADIv5.2)."},
        {"name": "SWJ-DP mode-switched",  "description": "SoC supports both SWD and JTAG; mode is selected at runtime via 16-bit selection sequences."},
    ]
    d["timing_dependency_rule"] = (
        "All transaction-state-machine transitions are synchronous to SWCLK. Target drives SWDIO on the "
        "falling edge during target-driven phases; host samples on the rising edge."
    )
    d["swd_to_jtag_mode_switching"] = {
        "jtag_to_swd_selection_sequence_hex": _SWJ_DP_JTAG_TO_SWD_HEX,
        "swd_to_jtag_selection_sequence_hex": _SWJ_DP_SWD_TO_JTAG_HEX,
        "selection_sequence_width_bits": 16,
        "selection_sequence_bit_order": "LSB first on SWDIO/TMS",
        "selection_sequence_preconditions": "Both selection sequences must be preceded by ≥ 50 cycles of SWDIO/TMS=HIGH and followed by ≥ 50 cycles of SWDIO/TMS=HIGH.",
    }
    _write(p, d)


# ============================================================
# L7 TEST DEBUG
# ============================================================
def _l7(gd: Path, ic_name: Optional[str]) -> None:
    p = gd / "L7_TEST_DEBUG.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_debug_architecture_present"] = True
    # FORCE-overwrite test_debug_features (JTAG fills with BYPASS/EXTEST/SAMPLE list).
    d["test_debug_features"] = [
        "SWD IS the debug architecture — ADIv5 enables in-system halt/resume, single-step, breakpoints, watchpoints, memory R/W on Arm Cortex SoCs.",
        "Halt / Resume via DHCSR (Debug Halting Control/Status Register) reached via MEM-AP.",
        "Single-step via DHCSR.C_STEP.",
        "Software breakpoints via BKPT instruction writes (raises debug exception caught by DHCSR).",
        "Hardware breakpoints via FPB (Flash Patch & Breakpoint Unit) comparators.",
        "Hardware watchpoints via DWT (Data Watchpoint & Trace Unit) comparators.",
        "CPU register access via DCRSR + DCRDR (Debug Core Register Selector + Data).",
        "Memory read/write via MEM-AP CSW + TAR + DRW.",
        "Flash programming via MEM-AP DRW writes to the flash controller.",
        "ITM trace (Instrumentation Trace Macrocell) — printf-style trace via the SWO pin.",
        "DWT trace — data-watchpoint + PC sampling trace via SWO.",
        "ETM trace (optional) — full instruction-data trace via the TPIU.",
        "CoreSight ROM Table walk from MEM-AP.BASE enumerates all debug components.",
        "CTI (Cross-Trigger Interface) for multi-core debug synchronization.",
        "Power-up / power-down debug via CTRL/STAT power handshake bits.",
    ]
    d["applications_supported_by_swd_adiv5"] = [
        "Cortex-M MCU in-system debug.",
        "Cortex-M flash programming via MEM-AP.",
        "Cortex-R real-time core debug.",
        "Cortex-A application core debug (typically alongside JTAG).",
        "Multi-core SoC debug coordination via CTI.",
        "Production / factory test via the 2-pin SWD connector.",
        "SWO trace capture for printf-style debug.",
        "Multi-drop SWD probing of dual-die packages (ADIv5.2).",
    ]
    d["spec_provided_observability"] = [
        {"name": "DPIDR / IDCODE",                "purpose": "32-bit DP fingerprint."},
        {"name": "CTRL/STAT sticky status bits",  "purpose": "STICKYORUN / STICKYCMP / STICKYERR / WDATAERR diagnostics."},
        {"name": "TARGETID / DLPIDR",             "purpose": "Target SoC identification (ADIv5.1+)."},
        {"name": "AP IDR",                        "purpose": "Identifies each AP's type."},
        {"name": "MEM-AP BASE → CoreSight ROM Table","purpose": "Enumerates debug components."},
        {"name": "DRW posted reads",              "purpose": "Bulk memory readback via TAR auto-increment + RDBUFF."},
        {"name": "DHCSR",                         "purpose": "CPU halted/stepped/locked status."},
        {"name": "ITM trace via SWO",             "purpose": "Printf-style trace packets."},
    ]
    d["spec_provided_controllability"] = [
        "DHCSR.C_HALT/C_STEP/C_DEBUGEN — halt/resume/step the CPU.",
        "MEM-AP DRW writes — write any system-bus address.",
        "FPB comparator writes — configure hardware breakpoints.",
        "DWT comparator writes — configure hardware watchpoints.",
        "DCRSR + DCRDR — read/write any CPU register.",
        "CTRL/STAT.CDBGRSTREQ / CSYSPWRUPREQ — request reset / power-up.",
        "ABORT.DAPABORT — abort an in-flight AP transaction.",
    ]
    d["fault_models_detected_by_swd"] = [
        "Request packet parity error.",
        "Data parity error on write (WDATAERR).",
        "AP transfer error (system-bus DECERR/SLVERR → STICKYERR).",
        "Posted-read overrun (STICKYORUN).",
        "WAIT exhaustion (target persistently busy).",
        "Wrong APSEL / APBANKSEL.",
        "Line drop / connector unseat.",
    ]
    # FORCE-overwrite fault_models that JTAG may have set with board-interconnect content.
    # Also remove jtag-specific keys if present.
    for jtag_key in ["fault_models_detected_by_jtag", "applications_supported_by_jtag_primer"]:
        d.pop(jtag_key, None)
    d["notes"] = (
        "ADIv5 SWD is fundamentally different from JTAG boundary-scan: SWD does NOT implement "
        "boundary-scan cells, does NOT test board interconnect, and does NOT enable EXTEST/INTEST. "
        "The MEM-AP layer is what makes SWD universally useful — it lets the debug host pretend to be a "
        "bus master on the SoC's system bus, so it can read/write any memory or memory-mapped register "
        "including the CPU's own debug-control registers."
    )
    _write(p, d)


# ============================================================
# L8 RTL CONSTANTS — FORCE overwrite TAP-shaped width_parameters
# ============================================================
def _l8_rtl(gd: Path, ic_name: Optional[str]) -> None:
    p = gd / "L8_RTL_CONSTANTS.json"
    if not p.is_file():
        return
    d = _read(p)
    # FORCE-overwrite width_parameters
    d["width_parameters"] = {
        "MANDATORY_PIN_COUNT": 2,
        "OPTIONAL_PIN_COUNT": 2,
        "EXTERNAL_PIN_COUNT_TOTAL": 4,
        "TRANSACTION_TOTAL_BITS": _SWD_TRANSACTION_TOTAL_BITS,
        "REQUEST_PACKET_BITS": _SWD_REQUEST_BITS,
        "TURNAROUND_BITS_PER_DIRECTION_CHANGE": _SWD_TURNAROUND_BITS,
        "TURNAROUND_BITS_CONFIGURABLE_RANGE": "1 to 4 (via CTRL/STAT.TRNCNT)",
        "ACK_PACKET_BITS": _SWD_ACK_BITS,
        "DATA_PACKET_BITS": _SWD_DATA_BITS,
        "DATA_PARITY_BITS": _SWD_PARITY_BITS,
        "TURNAROUND_PERIODS_PER_TRANSACTION": 2,
        "DP_REGISTER_COUNT_BASE_BANK": 4,
        "DP_BANKS_TOTAL": 5,
        "AP_REGISTER_WINDOW_BYTES": 64,
        "AP_REGISTER_COUNT_PER_AP": 16,
        "AP_MAX_COUNT": 256,
        "APSEL_BITS": 8,
        "APBANKSEL_BITS": 4,
        "DPBANKSEL_BITS": 4,
        "IDCODE_WIDTH_BITS": 32,
        "DPIDR_WIDTH_BITS": 32,
        "TARGETID_WIDTH_BITS": 32,
        "DLPIDR_WIDTH_BITS": 32,
        "TAR_WIDTH_BITS": 32,
        "TAR_WIDTH_BITS_ADIV5_2_LONG_ADDR": 64,
        "DRW_WIDTH_BITS": 32,
        "LINE_RESET_MIN_SWCLK_CYCLES": _SWD_LINE_RESET_MIN_CYCLES,
        "BIT_ORDER_IN_SHIFT": "LSB first",
    }
    d["swd_transaction_bit_layout"] = {
        "phases_in_order": [
            "8-bit Request",
            "1-bit Turnaround (configurable 1-4)",
            "3-bit ACK",
            "32-bit Data",
            "1-bit Data Parity",
            "1-bit Turnaround (configurable 1-4)",
        ],
        "request_field_positions": {
            "Start_bit": 0, "APnDP_bit": 1, "RnW_bit": 2, "A2_bit": 3,
            "A3_bit": 4, "Parity_bit": 5, "Stop_bit": 6, "Park_bit": 7,
        },
        "ack_codes_binary_lsb_first": dict(_SWD_ACK_CODES),
    }
    # Drop JTAG-specific keys
    for jtag_key in [
        "tap_state_names_in_canonical_order",
        "tap_state_transition_table_tms_driven",
        "mandatory_instructions",
        "optional_instructions",
        "data_register_widths",
        "device_id_field_layout",
    ]:
        d.pop(jtag_key, None)

    d["voltage_levels"] = {
        "VDD_at_SWD_pins": "Per-device VDD-IO; not specified by ADIv5.",
        "signaling":       "Digital CMOS / TTL — per-device datasheet. Typical 1.8 V / 2.5 V / 3.3 V.",
    }
    d["key_constants_for_RTL_authoring"] = {
        "swd_power_on_default_state":   "Idle (waiting for first Request after a line reset).",
        "swd_unconditional_reset_rule": "50 consecutive SWCLK cycles with SWDIO=HIGH → line reset.",
        "swdio_sample_edge":            "SWCLK rising edge during Request and Data-Write phases.",
        "swdio_drive_edge":             "SWCLK falling edge during ACK and Data-Read phases.",
        "shift_bit_order":              "LSB first throughout.",
        "request_start_bit_value":      1,
        "request_stop_bit_value":       0,
        "request_park_bit_value":       1,
        "request_parity_rule":          "Even parity over APnDP+RnW+A[2]+A[3].",
        "data_parity_rule":             "Even parity over the 32 data bits.",
        "default_turnaround_count":     1,
        "max_turnaround_count":         4,
        "ack_ok_code_binary":           "001",
        "ack_wait_code_binary":         "010",
        "ack_fault_code_binary":        "100",
        "post_reset_first_transaction": "IDCODE/DPIDR read (APnDP=0, RnW=1, A[2:3]=00).",
        "dpidr_lsb_one_rule":           "DPIDR bit 0 = 1 (RAO).",
        "targetid_lsb_one_rule":        "TARGETID bit 0 = 1 (RAO).",
        "swj_dp_jtag_to_swd_selection": _SWJ_DP_JTAG_TO_SWD_HEX,
        "swj_dp_swd_to_jtag_selection": _SWJ_DP_SWD_TO_JTAG_HEX,
        "line_reset_min_cycles":        _SWD_LINE_RESET_MIN_CYCLES,
    }
    d["dp_registers_base_bank"] = [
        "IDCODE/DPIDR (0x0 R)", "ABORT (0x0 W)", "CTRL/STAT (0x4)",
        "SELECT (0x8 W)", "RDBUFF (0xC R)",
    ]
    d["dp_registers_higher_banks"] = ["TARGETID (bank 2)", "DLPIDR (bank 3)", "EVENTSTAT (bank 4)"]
    d["memap_register_offsets"] = {r["name"]: r["offset"] for r in _SWD_MEMAP_REGISTERS}
    d["memap_register_offsets"]["TARHI"] = "0x08 (ADIv5.2 long-address only)"
    d["ap_class_codes"] = {
        "0x0": "JTAG-AP",
        "0x1": "AMBA AHB3 MEM-AP",
        "0x2": "AMBA APB2/3 MEM-AP",
        "0x4": "AMBA AXI3/4 MEM-AP",
        "0x5": "AMBA AHB5 MEM-AP",
        "0x8": "AMBA APB4/5 MEM-AP",
    }
    d["csw_addrinc_codes"] = {
        "00": "Off",
        "01": "Single (TAR += transfer size)",
        "10": "Packed",
        "11": "Reserved",
    }
    d["csw_size_codes"] = {
        "000": "Byte",
        "001": "Halfword",
        "010": "Word",
        "011": "Double-word",
        "100": "128-bit",
    }
    # FORCE overwrite default_signal_values_when_idle (JTAG fills with TCK/TMS/TDI/TDO/TRST)
    d["default_signal_values_when_idle"] = {
        "SWCLK": "Host-driven; idle level not specified.",
        "SWDIO": "Idle level HIGH — line-reset compatible.",
        "nTRST": "Recommended HIGH idle (de-asserted) when present.",
        "SWO":   "Trace pin; idle depends on TPIU configuration.",
    }
    _write(p, d)


# ============================================================
# L8 TIMING WAVEFORM — FORCE overwrite TCK/TMS/TDI/TDO waveform
# ============================================================
def _l8_timing(gd: Path, ic_name: Optional[str]) -> None:
    p = gd / "L8_TIMING_WAVEFORM.json"
    if not p.is_file():
        return
    d = _read(p)
    # Drop JTAG-only keys
    for jtag_key in [
        "tms_tdi_tdo_waveform",
        "ir_scan_waveform_summary",
        "dr_scan_waveform_summary",
    ]:
        d.pop(jtag_key, None)

    d["clock_waveform"] = {
        "SWCLK_role":      "Serial Wire Clock. Generated by the debug host. Free-running during a transaction; may be stopped between transactions.",
        "rising_edge":     "Target samples SWDIO during Request and Data-Write phases.",
        "falling_edge":    "Target drives SWDIO during ACK and Data-Read phases.",
        "duty_cycle":      "Not protocol-mandated; per-probe typically ~50%.",
        "frequency_range": "Typical 1-50 MHz; some probes go to 100 MHz. Implementation-defined per target.",
    }
    d["swdio_waveform"] = {
        "SWDIO_role": "Bidirectional serial data. Host-driven during Request and Data-Write; target-driven during ACK and Data-Read.",
        "drive_direction_table": [
            {"phase": "Request (bits 0..7)",      "driver": "host"},
            {"phase": "Turnaround A (bit 8)",     "driver": "neither (direction change)"},
            {"phase": "ACK (bits 9..11)",         "driver": "target"},
            {"phase": "Data Write (bits 12..43)", "driver": "host (only for writes)"},
            {"phase": "Data Read (bits 12..43)",  "driver": "target (only for reads)"},
            {"phase": "Parity (bit 44)",          "driver": "same as Data phase"},
            {"phase": "Turnaround B (bit 45)",    "driver": "neither (direction change)"},
        ],
        "park_bit_behavior": "Bit 7 of Request (Park=1) drives SWDIO HIGH before the host releases the line.",
        "idle_level": "Recommended HIGH between transactions.",
    }
    d["reset_waveform"] = {
        "line_reset_sequence": "SWDIO held HIGH for ≥ 50 consecutive SWCLK rising edges forces SW-DP Idle.",
        "selection_sequence_swd_to_jtag": f"16-bit pattern {_SWJ_DP_SWD_TO_JTAG_HEX} (LSB first on SWDIO) preceded and followed by ≥ 50 cycles SWDIO=HIGH.",
        "selection_sequence_jtag_to_swd": f"16-bit pattern {_SWJ_DP_JTAG_TO_SWD_HEX} (LSB first on TMS) preceded and followed by ≥ 50 cycles TMS=HIGH.",
    }
    d["transaction_waveform_summary"] = [
        "Host drives SWDIO from idle (HIGH) and begins the Request: bits 0..7 LSB-first on SWCLK rising edges.",
        "Park=1 leaves SWDIO HIGH; host tri-states; Turnaround A (1 SWCLK cycle by default).",
        "Target drives the 3-bit ACK on the falling edges of the next 3 SWCLKs.",
        "If ACK=OK: for a Read, target drives the next 32 SWDIO cycles with the data LSB-first.",
        "If ACK=OK: for a Write, host drives the next 32 SWDIO cycles with the data LSB-first.",
        "If ACK=WAIT or FAULT: host treats the next 32+1 bits as junk and either retries (WAIT) or reads CTRL/STAT + ABORT (FAULT).",
    ]
    d["posted_read_waveform_summary"] = [
        "Host issues Read of AP register N: ACK=OK; data is actually the result of the previous AP read.",
        "Host issues second Read: data is the actual result of read N.",
        "To recover the last read, host reads DP.RDBUFF (APnDP=0, A[3:2]=0xC, RnW=1).",
    ]
    d["timing_parameters_per_device"] = {
        "header": ["Parameter", "Symbol", "Note"],
        "rows": [
            ["SWCLK period",                       "tSWCLK",    "Typical 10-1000 ns (1-100 MHz)."],
            ["SWCLK HIGH time",                    "tSWCLKH",   "Per-device; typically ≥ 0.4 × tSWCLK."],
            ["SWCLK LOW time",                     "tSWCLKL",   "Per-device; typically ≥ 0.4 × tSWCLK."],
            ["SWDIO setup before SWCLK rising",    "tSU(SWDIO)","Per-device datasheet."],
            ["SWDIO hold after SWCLK rising",      "tH(SWDIO)", "Per-device datasheet."],
            ["SWDIO target drive delay (from SWCLK falling)", "tPD(SWDIO)", "Per-device datasheet."],
            ["Line reset cycle count",             "—",         "≥ 50 SWCLK cycles with SWDIO=HIGH."],
            ["Turnaround cycle count",             "TRNCNT",    "1 (default) to 4 (max)."],
        ],
        "notes": "ADIv5 does not specify absolute values; per-device datasheets do.",
    }
    d["voltage_levels"] = {
        "VIH_min": "Per-device datasheet (typically 0.7 × VDD-IO).",
        "VIL_max": "Per-device datasheet (typically 0.3 × VDD-IO).",
        "VOH_min": "Per-device datasheet.",
        "VOL_max": "Per-device datasheet.",
    }
    _write(p, d)


# ============================================================
# L9 INTEGRATION SPEC — FORCE overwrite no-daisy-chain rule
# ============================================================
def _l9(gd: Path, ic_name: Optional[str]) -> None:
    p = gd / "L9_INTEGRATION_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["module_role"] = (
        "Standardized debug-access architecture instantiated inside virtually every Arm Cortex-based "
        "SoC. Each compliant SoC contains a Debug Access Port (DAP) consisting of: (1) a 2-pin (SWD-DP) "
        "or 4-pin (JTAG-DP) or mode-switchable (SWJ-DP) Debug Port at the wire layer, (2) a DP register "
        "file, and (3) one or more Access Ports (MEM-AP variants, JTAG-AP, etc.) selected by SELECT.APSEL."
    )
    # FORCE overwrite integration_overview — JTAG fills with TAP-shaped content.
    d["integration_overview"] = {
        "wire_count_mandatory": 2,
        "wire_count_with_optional": 4,
        "wire_directions":      "SWCLK: host → target. SWDIO: bidirectional with explicit 1-bit Turnaround periods. nTRST (optional SWJ-DP only). SWO (optional trace).",
        "no_chip_select":       "No separate chip-select line. Multi-drop SWD uses TARGETSEL.",
        "addressing_at_protocol_layer": "DP registers via A[2:3] in Request. AP registers via SELECT.APSEL + APBANKSEL + A[2:3].",
        "test_logic_independent_of_functional_logic": "SWD pins are dedicated debug pins.",
        "handshake": "Synchronous shift; target signals OK/WAIT/FAULT per transaction. Implicit posted-read pipeline.",
    }
    d["interface_categories"] = [
        "Debug Host (USB-to-SWD probe).",
        "SWJ-DP Wire-Level Controller (target side).",
        "SW-DP / JTAG-DP Debug Port Layer.",
        "AP Bus.",
        "MEM-AP Instance.",
        "JTAG-AP Instance.",
        "CoreSight ROM Table.",
        "Debug Components (CPUs, FPB, DWT, ITM, ETM, CTI, TPIU).",
    ]
    d["interconnect_topologies_supported"] = [
        "Single target SWD.",
        "Multi-drop SWD (ADIv5.2).",
        "SWJ-DP mode-switched.",
        "SWD + SWO trace.",
    ]
    d["daisy_chain_rules"] = {
        "no_serial_daisy_chain": "Unlike JTAG, SWD does NOT support a serial daisy chain.",
        "multidrop_selection_rule": "After line reset + JTAG-to-SWD sequence + DP TARGETSEL matching the target's TPARTNO+TINSTANCE, only the addressed target drives ACK.",
    }
    d["default_signal_values_when_omitted"] = {
        "SWCLK_pull":  "Recommended pull-down.",
        "SWDIO_pull":  "Recommended pull-up (idle HIGH = line-reset compatible).",
        "nTRST_pull":  "Recommended pull-up (de-asserted) for SWJ-DP variants.",
    }
    d["soc_dependent_items"] = [
        "Number of APs (1 MEM-AP for single-core MCU; multiple for multi-core).",
        "MEM-AP variant (AHB-AP / APB-AP / AXI-AP).",
        "TAR width — 32-bit or 64-bit (ADIv5.2).",
        "Auto-increment support (Off / Single / Packed).",
        "Multi-drop SWD support (ADIv5.2).",
        "SWJ-DP vs SW-DP-only.",
        "Presence of nTRST + SWO pads.",
        "CoreSight ROM Table contents.",
        "DPIDR + TARGETID + DLPIDR field values.",
        "Default TRNCNT.",
        "Debug-probe connector format.",
    ]
    d["low_power_modes"] = {
        "CSYSPWRUPREQ_CDBGPWRUPREQ": "CTRL/STAT power-up handshake brings up debug + system power.",
        "SWCLK_stopped": "SW-DP wire-level FSM holds Idle when SWCLK stops.",
        "TAP_runs_in_chip_sleep": "SW-DP can be in always-on debug-power domain.",
    }
    d["compatibility_notes"] = [
        "ADIv5.0 (2006) base.",
        "ADIv5.1 (2009) adds TARGETID + DLPIDR + EVENTSTAT.",
        "ADIv5.2 (2017+) adds multi-drop SWD + long-address TAR + large-data DRW.",
        "ADIv6 (IHI 0074, 2019+) successor — SWD preserved.",
        "SWD and JTAG-DP share the same DP register model.",
        "CoreSight ROM Tables per IHI 0029.",
    ]
    _write(p, d)


# ============================================================
# L10 TEST CASES
# ============================================================
def _l10(gd: Path, ic_name: Optional[str]) -> None:
    p = gd / "L10_TEST_CASES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_cases_present"] = (
        "partial — ADIv5 / ARM IHI 0031C defines the architectural rules, the 46-bit transaction format, "
        "mandatory DP/AP register sets, and the SWJ-DP mode-switching mechanism, but does not provide a "
        "formal verification testbench."
    )
    d["derived_compliance_test_categories"] = [
        "Line reset — drive ≥ 50 SWCLK cycles with SWDIO=HIGH from each state; verify SW-DP returns to Idle.",
        "IDCODE/DPIDR readback — verify ACK=OK + 32-bit DPIDR with bit 0 = 1.",
        "Request packet parity — corrupted-parity Request shall be ignored or set WDATAERR.",
        "Request Start/Stop/Park — verify Start=0, Stop=1, Park=0 each ignored.",
        "ACK code validation — verify only OK=001 / WAIT=010 / FAULT=100.",
        "Data parity on read — verify the 33rd bit = even parity of 32 data bits.",
        "Data parity on write — bad parity → WDATAERR → FAULT → clear via ABORT.WDERRCLR.",
        "Turnaround — verify 1-cycle default and 4-cycle max.",
        "ABORT register — verify each clear bit clears its CTRL/STAT counterpart.",
        "SELECT register — verify APSEL + APBANKSEL + DPBANKSEL route to correct AP/bank.",
        "RDBUFF — verify posted-read recovery.",
        "AP IDR readback — for each implemented AP, verify non-zero IDR.",
        "AP BASE readback — verify ROM Table base address + Present bit.",
        "MEM-AP TAR + DRW round-trip — write to RAM, read back, verify match.",
        "MEM-AP auto-increment Single — verify TAR += transfer size after each DRW.",
        "MEM-AP auto-increment Packed — multiple sub-word per DRW.",
        "MEM-AP 4K wrap-around — verify auto-increment wraps within 4 KB.",
        "WAIT retry — verify host can retry until OK.",
        "FAULT recovery — read CTRL/STAT, write ABORT, retry.",
        "Sticky overrun — many posted reads → STICKYORUN set; clear via ABORT.ORUNERRCLR.",
        f"SWJ-DP JTAG-to-SWD selection — shift {_SWJ_DP_JTAG_TO_SWD_HEX} → SWD mode.",
        f"SWJ-DP SWD-to-JTAG selection — shift {_SWJ_DP_SWD_TO_JTAG_HEX} → JTAG mode.",
        "Multi-drop SWD — TARGETSEL with matching TPARTNO+TINSTANCE addresses correct target.",
        "CDBGPWRUPREQ / CSYSPWRUPREQ — verify ack handshake.",
        "DAPABORT — verify in-flight AP transaction cancelled.",
        "DHCSR halt — write C_HALT=1 → CPU halts (S_HALT=1).",
        "DHCSR step — verify single-step.",
        "CoreSight ROM Table walk — host enumerates all components.",
        "Cortex-M debug entry — halt before first user-code instruction (DEMCR.VC_CORERESET).",
    ]
    _write(p, d)


# ============================================================
# L11 OTP CONTENT — FORCE overwrite JTAG-style device-id catalog
# ============================================================
def _l11(gd: Path, ic_name: Optional[str]) -> None:
    p = gd / "L11_OTP_CONTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    d["otp_present"] = (
        "functionally — the 32-bit DPIDR + TARGETID + DLPIDR + AP IDR registers are functionally "
        "OTP-equivalent (hard-wired at silicon mask level, read-only via SWD bus). There is no fuse-bank "
        "or programmable OTP at the SWD protocol layer itself; per-vendor extensions add JTAG/SWD-disable "
        "fuses that are programmed at production test."
    )
    # Drop JTAG-specific 'device_identification_register_content' field if present.
    d.pop("device_identification_register_content", None)
    d["dpidr_register_content"] = {
        "width_bits": 32,
        "access": "Read-only via SWD Request(APnDP=0, RnW=1, A[2:3]=0).",
        "field_map": [
            {"bits": "31:28", "name": "REVISION", "width_bits": 4,  "description": "DP revision (mask-set).",   "writability": "ROM"},
            {"bits": "27:20", "name": "PARTNO",   "width_bits": 8,  "description": "DP part number.",            "writability": "ROM"},
            {"bits": "16",    "name": "MIN",      "width_bits": 1,  "description": "Min DP version.",            "writability": "ROM"},
            {"bits": "15:12", "name": "VERSION",  "width_bits": 4,  "description": "DP architecture version.",   "writability": "ROM"},
            {"bits": "11:1",  "name": "DESIGNER", "width_bits": 11, "description": "JEP106 designer ID.",        "writability": "ROM"},
            {"bits": "0",     "name": "RAO",      "width_bits": 1,  "description": "Read-As-One; hard-wired 1.", "writability": "ROM (always 1)"},
        ],
    }
    d["targetid_register_content"] = {
        "applicable_when": "ADIv5.1+ DP",
        "width_bits": 32,
        "access": "Read-only via DP bank 2.",
        "field_map": [
            {"bits": "31:28", "name": "TREVISION", "width_bits": 4,  "description": "Target SoC revision.",   "writability": "ROM"},
            {"bits": "27:12", "name": "TPARTNO",   "width_bits": 16, "description": "Target SoC part number.","writability": "ROM"},
            {"bits": "11:1",  "name": "TDESIGNER", "width_bits": 11, "description": "Target designer JEP106.","writability": "ROM"},
            {"bits": "0",     "name": "RAO",       "width_bits": 1,  "description": "Read-As-One.",           "writability": "ROM (always 1)"},
        ],
    }
    d["dlpidr_register_content"] = {
        "applicable_when": "ADIv5.2+ multi-drop SWD",
        "width_bits": 32,
        "access": "Read-only via DP bank 3.",
        "field_map": [
            {"bits": "31:28", "name": "TINSTANCE", "width_bits": 4, "description": "Multi-drop target instance.", "writability": "ROM"},
            {"bits": "3:0",   "name": "PROTVSN",   "width_bits": 4, "description": "Protocol version (0001=ADIv5.2).","writability": "ROM"},
        ],
    }
    d["ap_idr_register_content"] = {
        "applicable_when": "Each AP implements its own 32-bit IDR (offset 0xFC).",
        "width_bits": 32,
        "access": "Read-only.",
        "field_map": [
            {"bits": "3:0",   "name": "Type",     "width_bits": 4, "description": "AP type code (0=JTAG-AP, 1=AHB3-AP, 2=APB2/3-AP, 4=AXI3/4-AP, etc.)."},
            {"bits": "7:4",   "name": "Variant",  "width_bits": 4, "description": "AP variant."},
            {"bits": "16:13", "name": "Class",    "width_bits": 4, "description": "AP class (8 = MEM-AP)."},
            {"bits": "23:17", "name": "JEP106",   "width_bits": 7, "description": "JEP106 designer."},
            {"bits": "31:28", "name": "Revision", "width_bits": 4, "description": "AP revision."},
        ],
    }
    # Drop JTAG usercode_register_content if it was set with JTAG-shaped data.
    d.pop("usercode_register_content", None)
    d["usercode_or_user_otp_content"] = {
        "applicable_when": "Vendor-specific. Some SoCs implement a USERCODE-like 32-bit register reachable via a vendor-specific MEM-AP system-bus address. ADIv5 does not standardize this.",
        "width_bits": 32,
        "access": "Vendor-defined.",
        "writability": "Vendor-defined; sometimes loaded from on-chip fuses at boot.",
    }
    d["vendor_jtag_swd_disable_fuses"] = {
        "applicable_when": "Many production SoCs implement a one-way fuse (ST RDP, Nordic APPROTECT, NXP DCFG, ESP32 JTAG_DISABLE).",
        "common_behaviors": [
            "Full SWD disable.",
            "ROM-only access.",
            "Mass-erase-only.",
        ],
    }
    d["notes"] = (
        "ADIv5 mandates DPIDR but treats TARGETID, DLPIDR, EVENTSTAT, and AP IDRs as identification "
        "registers — all read-only and effectively ROM at silicon mask level. No protocol-defined "
        "writable OTP at the SWD layer."
    )
    _write(p, d)


# ============================================================
# L12 BEHAVIORAL SEQUENCES — FORCE overwrite JTAG TAP-FSM-shaped sequences
# ============================================================
def _l12(gd: Path, ic_name: Optional[str]) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    # Drop JTAG-specific keys
    for jtag_key in [
        "ir_scan_sequence_to_load_instruction",
        "dr_scan_sequence_to_shift_data",
        "bypass_chain_check_sequence",
        "idcode_readout_sequence",
        "extest_drive_observe_sequence",
        "intest_in_system_test_sequence",
        "multi_device_mixed_instruction_sequence",
    ]:
        d.pop(jtag_key, None)
    d["power_on_sequence"] = [
        "1. Power-up: SWD wire-level state may be indeterminate.",
        "2. Host drives ≥ 50 SWCLK cycles with SWDIO=HIGH (line reset).",
        "3. Host issues IDCODE/DPIDR read; target responds ACK=OK + 32-bit DPIDR + parity.",
        "4. Host requests power-up: write CTRL/STAT with CSYSPWRUPREQ=1 + CDBGPWRUPREQ=1; wait for ACKs.",
        "5. Host clears sticky errors via ABORT.",
        "6. Host walks AP IDR catalog: for APSEL=0..255, write SELECT.APSEL then read AP.IDR.",
    ]
    d["swj_dp_mode_switch_sequence_jtag_to_swd"] = [
        "1. Start in JTAG mode.",
        "2. Drive ≥ 50 SWCLK cycles with TMS=1.",
        f"3. Shift the 16-bit JTAG-to-SWD selection sequence {_SWJ_DP_JTAG_TO_SWD_HEX} LSB-first on TMS.",
        "4. Drive ≥ 50 SWCLK cycles with TMS (=SWDIO) = 1 (SWD line reset in new mode).",
        "5. Issue SWD IDCODE/DPIDR read; verify ACK=OK.",
    ]
    d["swj_dp_mode_switch_sequence_swd_to_jtag"] = [
        "1. Start in SWD mode.",
        "2. Drive ≥ 50 SWCLK cycles with SWDIO=1 (SWD line reset).",
        f"3. Shift the 16-bit SWD-to-JTAG selection sequence {_SWJ_DP_SWD_TO_JTAG_HEX} LSB-first on SWDIO.",
        "4. Drive ≥ 50 SWCLK cycles with TMS=1 (JTAG TestLogicReset).",
        "5. Issue JTAG IR-scan to verify JTAG TAP responds.",
    ]
    d["ap_read_sequence_posted"] = [
        "1. Host writes SELECT with target AP index + bank.",
        "2. Host issues Read AP[N] register X.",
        "3. Target responds ACK=OK + 32-bit data + parity. Data is implementation-defined for first read.",
        "4. Host issues Read AP[N] register Y (or DP.RDBUFF).",
        "5. Target responds ACK=OK + actual data of step 2's read.",
        "6. To recover the last read, host reads DP.RDBUFF.",
    ]
    d["ap_write_sequence"] = [
        "1. Host writes SELECT with target AP index + bank.",
        "2. Host issues Write AP[N] register X + 32-bit data + parity.",
        "3. Target responds ACK=OK (or WAIT if busy; FAULT if sticky error).",
    ]
    d["mem_ap_memory_write_burst_sequence"] = [
        "1. Host configures CSW: AddrInc=Single, Size=Word, DbgSwEnable=1.",
        "2. Host writes TAR with starting system-bus address.",
        "3. Host issues N successive Write DRW; TAR auto-increments by 4.",
        "4. Host issues final RDBUFF read to flush.",
    ]
    d["mem_ap_memory_read_burst_sequence"] = [
        "1. Host configures CSW: AddrInc=Single, Size=Word.",
        "2. Host writes TAR.",
        "3. Host issues N successive Read DRW; each returns previous DRW's result; TAR += 4.",
        "4. Host issues final DP.RDBUFF read to recover the last data.",
    ]
    d["fault_recovery_sequence"] = [
        "1. Target returns ACK=FAULT.",
        "2. Host reads DP.CTRL/STAT to identify STICKYORUN / STICKYCMP / STICKYERR / WDATAERR.",
        "3. Host writes DP.ABORT with corresponding clear bits.",
        "4. Host re-reads CTRL/STAT to confirm cleared.",
        "5. Host retries the failed transaction.",
    ]
    d["wait_recovery_sequence"] = [
        "1. Target returns ACK=WAIT.",
        "2. Host advances 1+ SWCLK cycles and retries.",
        "3. Repeat until ACK=OK.",
    ]
    d["swd_line_reset_recovery_sequence"] = [
        "1. Host detects protocol error.",
        "2. Host drives SWDIO=HIGH for ≥ 50 SWCLKs.",
        "3. Host re-issues IDCODE/DPIDR read.",
        "4. Host re-writes SELECT (line reset cleared it).",
        "5. Host re-clears sticky bits via ABORT.",
    ]
    d["multidrop_target_selection_sequence_adiv5_2"] = [
        "1. Host drives ≥ 50 SWCLK cycles with SWDIO=HIGH (line reset).",
        f"2. Host shifts JTAG-to-SWD 16-bit selection {_SWJ_DP_JTAG_TO_SWD_HEX} LSB-first.",
        "3. Host drives another ≥ 50 SWCLK cycles with SWDIO=HIGH.",
        "4. Host issues Write DP.TARGETSEL with the desired target's TPARTNO + TINSTANCE.",
        "5. Only the matching target drives ACK on subsequent transactions.",
        "6. Host issues Read DP.DPIDR to confirm.",
    ]
    d["cortex_m_halt_sequence_via_swd"] = [
        "1. Power-on sequence + IDCODE + power-up requests.",
        "2. Host walks MEM-AP.BASE ROM Table to locate Cortex-M DCB.",
        "3. Host configures MEM-AP: CSW.Size=Word, AddrInc=Off, DbgSwEnable=1.",
        "4. Host writes TAR=DHCSR; writes DRW=(DBGKEY=0xA05F<<16)|C_DEBUGEN|C_HALT.",
        "5. Target halts; host reads DHCSR via DRW; verifies S_HALT=1.",
    ]
    d["tap_recovery_sequence"] = [
        "Drive SWDIO=HIGH for ≥ 50 SWCLKs → SW-DP line reset.",
        f"If stuck in JTAG: TMS=1 for ≥ 5 TCKs → TestLogicReset; then {_SWJ_DP_JTAG_TO_SWD_HEX}; then SWD line reset.",
        "Assert nTRST=LOW (if available) → SWJ-DP forced to power-on state.",
    ]
    _write(p, d)


# ============================================================
# L13 LAB CALIBRATION
# ============================================================
def _l13(gd: Path, ic_name: Optional[str]) -> None:
    p = gd / "L13_LAB_CALIBRATION.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("lab_calibration_present", False)
    d["notes"] = (
        "ADIv5 SWD is a digital wire-level debug-access protocol; no analog reference / trim / "
        "calibration is part of the architecture. Practical board-bring-up characterizations focus on "
        "SWCLK frequency margin, SWDIO signal integrity, Turnaround timing, SWDIO direction-change "
        "glitches, and (separately) SWO trace pin baud-rate calibration."
    )
    d["board_bring_up_characterizations_typical"] = [
        "SWCLK frequency sweep — increase from 1 MHz until target stops ACKing OK; back off ~50%.",
        "Signal integrity on SWDIO — verify rise/fall times meet tSU/tH.",
        "Turnaround cycle calibration — increase TRNCNT for slow-driver SoCs or stacked level translators.",
        "Pull-up sizing on SWDIO — typical 4.7 kΩ to 10 kΩ.",
        "Pull-down sizing on SWCLK — optional, typical 10 kΩ.",
        "VDD-IO level matching — verify probe matches target VDD-IO (auto-sensing probes handle this).",
        "SWO trace baud-rate calibration (separate from SWD protocol).",
        "Line-reset margin — verify ≥ 50-cycle works at all SWCLK frequencies.",
        "Mode-switch reliability — verify selection sequences succeed across PVT corners.",
        "Multi-drop bus loading — verify total bus capacitance is acceptable.",
    ]
    _write(p, d)


# ============================================================
# L14 PROTOCOL VERSIONING
# ============================================================
def _l14(gd: Path, ic_name: Optional[str]) -> None:
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    if ic_name:
        f["ic_name"] = ic_name
    f["spec_version"] = (
        "ARM IHI 0031C — ARM Debug Interface v5 Architecture Specification (ADIv5). Documents ADIv5.0 + "
        "ADIv5.1 + ADIv5.2 amendments."
    )
    f["previous_versions"] = [
        "ARM Debug Interface v4 (ADIv4) — predates CoreSight; JTAG-only.",
        "ARM IHI 0031A (ADIv5.0 base, 2006).",
        "ARM IHI 0031B (ADIv5.1, 2009).",
        "ARM IHI 0031C (consolidated, ADIv5.0/5.1/5.2).",
    ]
    f["post_adiv5_evolution_industry_note"] = [
        "ARM IHI 0074 — ADIv6 (2019+).",
        "ARM IHI 0029 — CoreSight Architecture Specification.",
        "ARM IHI 0064 — CoreSight ETM v4.",
        "CMSIS-DAP — Arm's open USB-to-SWD/JTAG probe reference firmware.",
    ]
    f["key_changes"] = [
        {"version": "ADIv5.0", "summary": "Base spec: 4-pin JTAG-DP + 2-pin SW-DP + SWJ-DP; DP register set; AP layer; MEM-AP + JTAG-AP."},
        {"version": "ADIv5.1", "summary": "Adds TARGETID + DLPIDR + EVENTSTAT in DP higher banks."},
        {"version": "ADIv5.2", "summary": "Multi-drop SWD; long-address TAR (64-bit); large-data DRW."},
        {"version": "ADIv6 (IHI 0074)", "summary": "Successor: 64-bit address; hierarchical ROM Tables; new AP classes."},
    ]
    f["backward_compat_traps"] = [
        {
            "trap_name": "dpidr_lsb_must_be_RAO",
            "rule": "Bit 0 of DPIDR shall be hard-wired to 1 (RAO).",
            "trap": "If forgotten, host cannot distinguish stuck-at-zero SWDIO from a real DPIDR readout.",
        },
        {
            "trap_name": "targetid_lsb_must_be_RAO",
            "rule": "Bit 0 of TARGETID shall be 1 (RAO).",
            "trap": "Same as DPIDR.",
        },
        {
            "trap_name": "request_start_stop_park_pattern",
            "rule": "Request bit 0=Start=1, bit 6=Stop=0, bit 7=Park=1.",
            "trap": "Custom IPs mishandling Park=1 lose Turnaround margin.",
        },
        {
            "trap_name": "ack_codes_one_hot_only",
            "rule": "ACK shall be OK=001 / WAIT=010 / FAULT=100 (one-hot).",
            "trap": "Returning 000 / 011 / 111 confuses every commercial debug probe.",
        },
        {
            "trap_name": "line_reset_must_be_at_least_50_cycles",
            "rule": "Line reset requires ≥ 50 consecutive SWDIO=HIGH cycles.",
            "trap": "Implementations accepting fewer cycles break hosts that follow spec.",
        },
        {
            "trap_name": "swj_dp_selection_sequence_endian",
            "rule": f"Both SWJ-DP selection sequences ({_SWJ_DP_JTAG_TO_SWD_HEX} and {_SWJ_DP_SWD_TO_JTAG_HEX}) shall be shifted LSB-first.",
            "trap": "MSB-first shift never switches modes — classic CMSIS-DAP port bug.",
        },
        {
            "trap_name": "posted_read_RDBUFF_recovery",
            "rule": "Final read of an AP burst shall be recovered via DP.RDBUFF.",
            "trap": "Forgetting trailing RDBUFF read gives next-to-last result — off-by-one.",
        },
        {
            "trap_name": "tar_auto_increment_4k_wrap",
            "rule": "MEM-AP TAR auto-increment shall wrap within a 4 KB page (or per CFG.LongAddress).",
            "trap": "Ignoring wrap-around boundary corrupts cross-page bursts.",
        },
    ]
    f["version_naming_history_note"] = (
        "SWD is the 2-pin variant of the ARM Debug Interface defined by ADIv5 (ARM IHI 0031C, first "
        "released 2006). CoreSight is the umbrella debug-IP family. ADIv6 (Arm IHI 0074) is the named "
        "successor."
    )
    d["fields"] = f
    _write(p, d)


# ============================================================
# L15 ENCODING TABLES
# ============================================================
def _l15(gd: Path, ic_name: Optional[str]) -> None:
    p = gd / "L15_ENCODING_TABLES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    if ic_name:
        f["ic_name"] = ic_name
    f["swd_transaction_phases_table"] = {
        "header_columns": ["Phase Index", "Phase Name", "Bits", "Direction", "Notes"],
        "rows": [
            [1, "Request",      "8",  "host → target", "Start + APnDP + RnW + A[2] + A[3] + Parity + Stop + Park (LSB first)"],
            [2, "Turnaround A", "1",  "transitional",  "Configurable 1-4 via CTRL/STAT.TRNCNT"],
            [3, "ACK",          "3",  "target → host", "001=OK, 010=WAIT, 100=FAULT (LSB first)"],
            [4, "Data",         "32", "Read: target→host; Write: host→target", "32-bit payload (LSB first)"],
            [5, "Data Parity",  "1",  "same as Data",  "Even parity over the 32 data bits"],
            [6, "Turnaround B", "1",  "transitional",  "Configurable 1-4"],
        ],
    }
    f["request_field_table"] = {
        "header_columns": ["Bit", "Field Name", "Value", "Description"],
        "rows": [[fld["bit"], fld["name"], fld["value"], fld["description"]] for fld in _SWD_REQUEST_FIELDS],
    }
    f["ack_code_table"] = {
        "header_columns": ["ACK Binary (LSB first)", "ACK Value", "Name", "Meaning", "Host Action"],
        "rows": [
            ["001", 1, "OK",    "Transaction accepted",        "Proceed normally"],
            ["010", 2, "WAIT",  "Target busy; data is junk",   "Retry"],
            ["100", 4, "FAULT", "Sticky error",                "Read CTRL/STAT, write ABORT, retry"],
        ],
    }
    f["dp_register_table"] = {
        "header_columns": ["DP Bank", "A[3:2]", "Read Register", "Write Register", "Purpose"],
        "rows": [
            ["0", "0x0", "IDCODE/DPIDR", "ABORT",     "Device ID (R); sticky error clear (W)"],
            ["0", "0x4", "CTRL/STAT",    "CTRL/STAT", "Control + sticky status"],
            ["0", "0x8", "RESEND",       "SELECT",    "Re-send last DRW (R); AP bank select (W)"],
            ["0", "0xC", "RDBUFF",       "(reserved)","Posted-read recovery"],
            ["2", "0x4", "TARGETID",     "—",         "Target SoC identification (ADIv5.1+)"],
            ["3", "0x4", "DLPIDR",       "TARGETSEL", "Multi-drop target instance"],
            ["4", "0x4", "EVENTSTAT",    "—",         "Per-target event status"],
        ],
    }
    f["memap_register_table"] = {
        "header_columns": ["Offset", "Register", "Purpose"],
        "rows": [[r["offset"], r["name"], r["purpose"]] for r in _SWD_MEMAP_REGISTERS],
    }
    f["ap_type_codes_table"] = {
        "header_columns": ["Type Code", "AP Variant"],
        "rows": [
            ["0x0", "JTAG-AP"],
            ["0x1", "AMBA AHB3 MEM-AP"],
            ["0x2", "AMBA APB2/3 MEM-AP"],
            ["0x4", "AMBA AXI3/4 MEM-AP"],
            ["0x5", "AMBA AHB5 MEM-AP"],
            ["0x8", "AMBA APB4/5 MEM-AP"],
        ],
    }
    f["ap_class_codes_table"] = {
        "header_columns": ["Class Code", "AP Class"],
        "rows": [
            ["0x0", "Undefined / Unimplemented"],
            ["0x8", "MEM-AP class"],
        ],
    }
    f["csw_addrinc_table"] = {
        "header_columns": ["CSW.AddrInc[5:4]", "Mode", "Description"],
        "rows": [
            ["00", "Off",      "TAR not modified after DRW transfer"],
            ["01", "Single",   "TAR += transfer size (1/2/4/8/16) after each DRW transfer"],
            ["10", "Packed",   "Multiple sub-word transfers per DRW; TAR auto-increments per sub-word"],
            ["11", "Reserved", "—"],
        ],
    }
    f["csw_size_table"] = {
        "header_columns": ["CSW.Size[2:0]", "Size", "Description"],
        "rows": [
            ["000", "Byte",        "8-bit transfers"],
            ["001", "Halfword",    "16-bit transfers"],
            ["010", "Word",        "32-bit transfers (default)"],
            ["011", "Double-word", "64-bit transfers (requires CFG.LargeData)"],
            ["100", "128-bit",     "128-bit transfers (requires CFG.LargeData)"],
        ],
    }
    f["swj_dp_selection_sequences_table"] = {
        "header_columns": ["Mode Switch", "16-bit Pattern (LSB first on SWDIO/TMS)", "Hex Value"],
        "rows": [
            ["JTAG → SWD", "0111 1001 1110 0111 (LSB first)", _SWJ_DP_JTAG_TO_SWD_HEX],
            ["SWD → JTAG", "0011 1100 1110 0111 (LSB first)", _SWJ_DP_SWD_TO_JTAG_HEX],
        ],
    }
    f["line_reset_table"] = {
        "header_columns": ["Condition", "Minimum SWCLK Cycles", "Effect"],
        "rows": [
            ["SWDIO held HIGH",   str(_SWD_LINE_RESET_MIN_CYCLES), "SW-DP returns to Idle; SELECT and CTRL/STAT cleared"],
            ["After mode-switch", str(_SWD_LINE_RESET_MIN_CYCLES), "Line reset in new mode"],
        ],
    }
    f["ctrl_stat_sticky_bits_table"] = {
        "header_columns": ["Bit", "Name", "Set By", "Cleared By", "Meaning"],
        "rows": [
            [1,  "STICKYORUN", "Posted-read overrun",             "ABORT.ORUNERRCLR", "Too many reads without RDBUFF"],
            [12, "WDATAERR",   "Write Data parity mismatch",       "ABORT.WDERRCLR",   "Write Data bad parity"],
            [14, "STICKYERR",  "AP transfer error (system-bus)",   "ABORT.STKERRCLR",  "Last AP transaction faulted"],
            [15, "STICKYCMP",  "Compare-match in pushed-verify",   "ABORT.STKCMPCLR",  "DLPIDR compare matched"],
        ],
    }
    if _empty(f.get("tables")):
        f["tables"] = [
            "Figure 2-3 — Debug Access Port (DAP) Architecture (ARM IHI 0031C)",
            "Figure 3-1 — SWD Transaction Format (8+1+3+32+1+1 = 46 bits)",
            "Figure 3-2 — SWD Request Packet Layout",
            "Figure 5-3 — DP Register Map",
            "Figure 6-3 — MEM-AP Register Map",
            "Table 5-1 — DP Register Definitions",
            "Table 6-1 — MEM-AP Register Definitions",
            "Section 4.4.5 — Line Reset",
            "Section 5.3 — SWJ-DP Selection Sequences",
        ]
    d["fields"] = f
    _write(p, d)


# ============================================================
# L16 COMPLIANCE PROPERTIES
# ============================================================
def _l16(gd: Path, ic_name: Optional[str]) -> None:
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    if ic_name:
        f["ic_name"] = ic_name
    f["must_have_properties"] = [
        "Two mandatory dedicated pins: SWCLK (host-driven) and SWDIO (bidirectional).",
        "Every transaction is exactly 46 bits: Request + Turnaround + ACK + Data + Parity + Turnaround.",
        "Request packet: Start=1, Stop=0, Park=1; Parity even over APnDP+RnW+A[2:3].",
        "ACK encoding: OK=001, WAIT=010, FAULT=100 (one-hot only).",
        "Data: 32 bits LSB first + 33rd parity bit (even parity).",
        "DPIDR register at A[3:2]=0x0 read; bit 0 hard-wired to 1 (RAO).",
        "ABORT register at A[3:2]=0x0 write; supports DAPABORT + STKCMPCLR + STKERRCLR + WDERRCLR + ORUNERRCLR.",
        "CTRL/STAT register at A[3:2]=0x4.",
        "SELECT register at A[3:2]=0x8 write; APSEL + APBANKSEL + DPBANKSEL fields.",
        "RDBUFF register at A[3:2]=0xC read.",
        "Up to 256 APs addressable via SELECT.APSEL.",
        "MEM-AP register catalog: CSW, TAR, DRW, CFG, BASE, IDR at minimum.",
        "MEM-AP IDR.Class = 8.",
        "Line reset = ≥ 50 consecutive SWCLK cycles with SWDIO=HIGH.",
        "Post-reset host first transaction is IDCODE/DPIDR read.",
        "Posted reads: data of read N returned with ACK of read N+1; final via DP.RDBUFF.",
    ]
    f["must_have_if_swj_dp_present"] = [
        f"16-bit JTAG-to-SWD selection sequence {_SWJ_DP_JTAG_TO_SWD_HEX} (LSB first) shall be recognized.",
        f"16-bit SWD-to-JTAG selection sequence {_SWJ_DP_SWD_TO_JTAG_HEX} (LSB first) shall be recognized.",
        "Both selection sequences shall be preceded and followed by ≥ 50 cycles TMS/SWDIO=HIGH.",
    ]
    f["must_have_if_adiv5_1_plus"] = [
        "TARGETID register at DP bank 2; bit 0 = 1 (RAO).",
        "DLPIDR register at DP bank 3.",
        "EVENTSTAT register at DP bank 4.",
    ]
    f["must_have_if_adiv5_2_multidrop"] = [
        "TARGETSEL transaction routes subsequent transactions only to matching target.",
        "Non-addressed targets shall ignore the bus after TARGETSEL mismatch.",
        "DLPIDR.PROTVSN = 0001 indicates ADIv5.2 multi-drop SWD.",
    ]
    f["must_not_have_properties"] = [
        "Request with Start=0, Stop=1, or Park=0.",
        "ACK code other than 001/010/100.",
        "DPIDR with bit 0 = 0.",
        "TARGETID with bit 0 = 0.",
        "Data parity bit not equal to even parity of the 32 data bits.",
        "Line reset requirement < 50 SWCLK cycles.",
        "SWD pins shared with functional pins.",
        "MEM-AP IDR.Class != 8.",
        "Posted reads where data of read N is returned with ACK of read N.",
    ]
    f["compliance_failure_modes"] = [
        {"mode": "Host cannot detect target presence",   "trigger": "DPIDR bit 0 not RAO."},
        {"mode": "Host cannot detect line reset",         "trigger": "SW-DP does not honor 50-cycle SWDIO=HIGH."},
        {"mode": "Host stuck after FAULT",                "trigger": "ABORT clear bits don't actually clear sticky bits."},
        {"mode": "Posted-read off-by-one",                "trigger": "AP returns data at ACK of read N instead of N+1."},
        {"mode": "SWJ-DP cannot switch JTAG→SWD",         "trigger": f"{_SWJ_DP_JTAG_TO_SWD_HEX} not recognized (MSB-vs-LSB)."},
        {"mode": "SWJ-DP cannot switch SWD→JTAG",         "trigger": f"{_SWJ_DP_SWD_TO_JTAG_HEX} not recognized."},
        {"mode": "Multi-drop bus contention",             "trigger": "DLPIDR.TINSTANCE not unique."},
        {"mode": "AP transfer error masked",              "trigger": "STICKYERR not set on system-bus DECERR/SLVERR."},
        {"mode": "TAR auto-increment wrong",              "trigger": "Wrong wrap-around at 4 KB."},
        {"mode": "Turnaround glitch",                     "trigger": "Target releases SWDIO too early/late vs host."},
    ]
    f["reset_behavior_compliance"] = (
        "After line reset or power-on: SW-DP returns to Idle; DP.SELECT cleared (APSEL=APBANKSEL="
        "DPBANKSEL=0); CTRL/STAT cleared; posted-read queue drained. First host transaction must be "
        "IDCODE/DPIDR read."
    )
    d["fields"] = f
    _write(p, d)


# ============================================================
# L17 CHANNEL SIGNAL CATALOG — FORCE overwrite TCK/TMS/TDI/TDO channels
# ============================================================
def _l17(gd: Path, ic_name: Optional[str]) -> None:
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    if ic_name:
        f["ic_name"] = ic_name
    # FORCE overwrite — JTAG synth writes TCK/TMS/TDI/TDO/TRST here.
    f["channels"] = [
        {"name": "SWCLK", "direction_tester": "output", "direction_device": "input",
         "purpose": "Serial Wire Clock. Host-generated free-running clock.",
         "active_levels": "Per-device VIH / VIL (CMOS / TTL)", "idle_level": "Free-running; idle level not specified"},
        {"name": "SWDIO", "direction_tester": "output (Request, Data-Write); input (ACK, Data-Read)",
         "direction_device": "input (Request, Data-Write); output (ACK, Data-Read)",
         "purpose": "Serial Wire Data Input/Output. Bidirectional 1-wire data line; direction-controlled by SWD wire-level FSM with explicit 1-bit Turnaround periods.",
         "active_levels": "Per-device VIH / VIL / VOH / VOL", "idle_level": "Recommended pulled HIGH"},
        {"name": "nTRST", "direction_tester": "output (optional, SWJ-DP only)", "direction_device": "input (optional)",
         "purpose": "Optional asynchronous TAP reset (active LOW) — present only on SWJ-DP variants exposing TRST.",
         "active_levels": "Active LOW", "idle_level": "Recommended pulled HIGH (de-asserted)"},
        {"name": "SWO", "direction_tester": "input (optional trace)", "direction_device": "output (optional trace)",
         "purpose": "Serial Wire Output. Optional async trace pin carrying ITM/DWT trace packets — separate from SWD protocol.",
         "active_levels": "Per-device VOH / VOL", "idle_level": "TPIU-driven; idle level depends on encoding"},
    ]
    f["global_signals"] = [
        {"name": "VDD-IO (per target)", "purpose": "Drives SWD pins' I/O voltage; per-device datasheet."},
        {"name": "GND",                "purpose": "Common ground reference."},
    ]
    f["channel_counts"] = {
        "channels_mandatory":             2,
        "channels_optional":              2,
        "external_pins_total_mandatory":  2,
        "external_pins_total_with_trst_and_swo": 4,
        "data_lines":                     1,
        "clock_lines":                    1,
        "control_lines":                  0,
        "reset_lines_optional":           1,
        "trace_lines_optional":           1,
    }
    # Drop JTAG-only boundary_scan_cell_catalog
    f.pop("boundary_scan_cell_catalog", None)
    f["ordering_rules"] = {
        "shift_bit_order":             "LSB first on SWDIO for all phases.",
        "request_packet_lsb_order":    "Bit 0 (Start=1) first, bit 7 (Park=1) last.",
        "ack_packet_lsb_order":        "OK = 001 (LSB first: 1, 0, 0 → 0x1). WAIT = 010 → 0x2. FAULT = 100 → 0x4.",
        "data_packet_lsb_order":       "Bit 0 of 32-bit data first; parity at bit 32.",
        "swj_dp_selection_lsb_order":  f"Both {_SWJ_DP_JTAG_TO_SWD_HEX} and {_SWJ_DP_SWD_TO_JTAG_HEX} shifted LSB first.",
    }
    # FORCE-overwrite dependency_graph (JTAG fills with TAP-FSM content)
    f["dependency_graph"] = {
        "common_rule": (
            "Host drives SWCLK + SWDIO during Request and Data-Write phases; reads SWDIO during ACK and "
            "Data-Read phases. SW-DP FSM is driven by SWCLK rising edges + position within the 46-bit "
            "transaction; SWDIO direction-change at explicit Turnaround periods."
        ),
        "data_dependency": (
            "Each transaction's data field (read or write) is at bits 12..43 in the 46-bit transaction; "
            "Request (bits 0..7) identifies target register and direction; ACK (bits 9..11) gates whether "
            "the data field is meaningful. Posted reads compose multiple transactions into a pipeline."
        ),
    }
    # FORCE-overwrite handshake_pairs (JTAG fills with TCK_DRIVE / TMS_FSM / TDI_TDO_SHIFT)
    f["handshake_pairs"] = [
        {"name": "SWCLK_DRIVE",      "from": "host",     "to": "target",        "rule": "Free-running clock during a transaction; one bit per rising edge in host-driven phases."},
        {"name": "REQUEST_DRIVE",    "from": "host",     "to": "target",        "rule": "8-bit Request packet driven on SWDIO during bits 0..7."},
        {"name": "TURNAROUND_A",     "from": "neither",  "to": "neither",       "rule": "1-cycle SWDIO direction-change at bit 8."},
        {"name": "ACK_DRIVE",        "from": "target",   "to": "host",          "rule": "3-bit ACK on SWDIO during bits 9..11."},
        {"name": "DATA_DRIVE_WRITE", "from": "host",     "to": "target",        "rule": "32+1 bits on SWDIO during bits 12..44 for RnW=0."},
        {"name": "DATA_DRIVE_READ",  "from": "target",   "to": "host",          "rule": "32+1 bits on SWDIO during bits 12..44 for RnW=1."},
        {"name": "TURNAROUND_B",     "from": "neither",  "to": "neither",       "rule": "1-cycle SWDIO direction-change at bit 45."},
        {"name": "LINE_RESET",       "from": "host",     "to": "target",        "rule": "≥ 50 SWCLK cycles SWDIO=HIGH forces SW-DP to Idle."},
        {"name": "SWJ_DP_MODE_SELECT","from": "host",    "to": "target",        "rule": "16-bit pattern shifted on SWDIO/TMS switches between SWD and JTAG modes."},
    ]
    d["fields"] = f
    _write(p, d)


# ============================================================
# L18 INTERCONNECT TOPOLOGY — FORCE overwrite daisy-chain content
# ============================================================
def _l18(gd: Path, ic_name: Optional[str]) -> None:
    p = gd / "L18_INTERCONNECT_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    if ic_name:
        f["ic_name"] = ic_name
    f["topology_type"] = (
        "Two-wire host-to-target serial debug bus (no daisy chain). Host drives SWCLK; SWDIO is "
        "bidirectional with explicit Turnaround periods. Multi-drop SWD (ADIv5.2) shares SWDIO/SWCLK "
        "across multiple targets in parallel with per-target selection via TARGETSEL."
    )
    f["supported_topologies"] = [
        {"name": "Single-target SWD",          "description": "One debug host + one target SoC."},
        {"name": "SWJ-DP mode-switched",       "description": "Single target supports both SWD and JTAG."},
        {"name": "Multi-drop SWD (ADIv5.2)",   "description": "Multiple targets share SWDIO/SWCLK; per-target selection via TARGETSEL."},
        {"name": "SWD + SWO trace",            "description": "Single target with dedicated SWO trace pin."},
        {"name": "ARM 10-pin Cortex Debug header","description": "Standard 10-pin Arm Cortex Debug connector."},
        {"name": "ARM 20-pin Cortex+ETM header",   "description": "20-pin connector adding 4-bit parallel trace data."},
        {"name": "TC2050 / Tag-Connect",       "description": "Compact production needle-probe footprint."},
    ]
    f["master_slave_role_summary"] = [
        {"role": "Debug Host (master)",       "description": "USB-to-SWD probe (J-Link, ST-Link, CMSIS-DAP, etc.)."},
        {"role": "Target SoC (slave)",        "description": "Arm Cortex-based SoC implementing SW-DP / SWJ-DP + DP + AP layers."},
        {"role": "Multi-drop target (slave)", "description": "ADIv5.2 — additional SoC with unique TPARTNO+TINSTANCE."},
        {"role": "Debug Authentication Source", "description": "Optional external authentication interface (DBGEN/NIDEN/SPIDEN/SPNIDEN)."},
    ]
    f["interconnect_role"] = (
        "There is NO daisy chain at the SWD wire layer (unlike JTAG). SWD is point-to-point (or "
        "multi-drop in ADIv5.2). On the target side, the DAP fans transactions to up to 256 APs over "
        "an internal AP bus."
    )
    f["ordering_guarantees"] = {
        "bit_order_within_a_phase":   "LSB first on SWDIO.",
        "transaction_order":          "Strict sequential — each 46-bit transaction completes before the next begins. Posted reads pipeline the data return, but the wire-level ordering of transactions is strict.",
        "posted_read_pipelining":     "Read N's data appears with the ACK of transaction N+1 (or RDBUFF).",
        "ap_register_atomicity":      "Each AP register access is atomic from the host's POV.",
    }
    f["memory_vs_peripheral_regions"] = (
        "DP registers are accessed via APnDP=0 + A[3:2] — not memory-mapped. AP registers via "
        "APnDP=1 + APSEL + APBANKSEL + A[3:2]. MEM-AP CSW+TAR+DRW provides a window into the SoC's "
        "memory-mapped system bus."
    )
    f["device_classification"] = {
        "debug_host":             "USB-to-SWD/JTAG probe.",
        "swd_only_target":        "SoC with SW-DP only.",
        "swj_dp_target":          "SoC with SWJ-DP.",
        "multi_drop_target":      "SoC with DLPIDR (ADIv5.2).",
        "non_dap_ic":             "IC without ADIv5 DAP.",
    }
    f["default_signal_values_evidence_tables"] = [
        "Figure 2-3 — Debug Access Port (DAP) Block Diagram (ARM IHI 0031C)",
        "Figure 3-1 — SWD Wire-Level Transaction",
        "Figure 5-3 — DP Register Layout",
        "Figure 6-3 — MEM-AP Register Layout",
        "Figure A-1 — SWJ-DP Mode-Switch State Diagram",
        "Section 4.4 — Connection and Line Reset",
        "Section 5.3 — Multi-drop SWD (ADIv5.2)",
    ]
    d["fields"] = f
    _write(p, d)


# ============================================================
# L19 CONSTRAINTS PDK
# ============================================================
def _l19(gd: Path, ic_name: Optional[str]) -> None:
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    if ic_name:
        f["ic_name"] = ic_name
    f["constraints_present"] = (
        "partial — ADIv5 specifies protocol-level behavior + 2-pin SW-DP / 4-pin JTAG-DP / "
        "mode-switchable SWJ-DP architecture but does not specify PDK / floorplan / SDC constraints."
    )
    f["typical_per_device_constraints"] = [
        "SWD pins (SWCLK + SWDIO + optional nTRST + optional SWO) shall be dedicated debug pins.",
        "Per-target SWCLK max frequency: Cortex-M0+ ~10-24 MHz; Cortex-A ~50-100 MHz.",
        "Per-target tSU/tH/tPD(SWDIO) timing per datasheet.",
        "SWDIO output drive strength sufficient for pull-up + interconnect capacitance.",
        "ESD protection on SWD pins ±2 kV HBM min.",
        "Slew-rate control on SWDIO and SWCLK drivers.",
        "Internal pull-up on SWDIO recommended.",
        "Optional SWO trace pin requires separate TPIU output buffer.",
    ]
    f["typical_per_board_constraints"] = [
        "SWCLK routed as controlled-impedance trace.",
        "SWDIO bidirectional driver — board-level series resistor 0 Ω - 22 Ω.",
        "Pull-up resistor on SWDIO 4.7 kΩ - 10 kΩ.",
        "Pull-down resistor on SWCLK (optional) 10 kΩ.",
        "Pull-up on nTRST if implemented.",
        "Connector pin allocation: Arm 10-pin Cortex Debug, Arm 20-pin Cortex+ETM, or TC2050.",
        "VTREF (target voltage sense) routed to probe.",
        "Multi-drop SWD: shared trace must be controlled-impedance with low bus capacitance (< 25 pF).",
        "SWO trace pin routing: short, impedance-matched.",
    ]
    f["process_technology_independence"] = (
        "ADIv5 is process-independent. Any logic-process technology can implement SW-DP + MEM-AP."
    )
    f["notes"] = (
        "Modern Arm CoreSight DAP IP delivery includes SDC + UPF + scan-insertion files at IP-license "
        "level. SDC false-path on SWCLK→system-clock crossings is the most common per-implementation "
        "constraint."
    )
    d["fields"] = f
    _write(p, d)


# ============================================================
# L20 DFT SCAN TOPOLOGY
# ============================================================
def _l20(gd: Path, ic_name: Optional[str]) -> None:
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    if ic_name:
        f["ic_name"] = ic_name
    f["dft_present"] = True
    f["dft_architecture_summary"] = (
        "ADIv5 SWD is fundamentally a DEBUG-access architecture, not a DFT (manufacturing test) "
        "architecture in the IEEE 1149.1 sense. SWD does not implement boundary-scan cells on every "
        "external I/O pin; it does not enable EXTEST/INTEST/RUNBIST. The 'DFT' SWD provides is "
        "in-system controllability and observability of the CPU + system bus via the MEM-AP."
    )
    # Drop JTAG-specific boundary_scan_register_topology
    f.pop("boundary_scan_register_topology", None)
    f["debug_access_architecture_topology"] = {
        "description": "Host → SW-DP → DP register set → AP bus (up to 256 APs) → MEM-AP (CSW+TAR+DRW) → SoC system bus → memory-mapped resources.",
        "key_components_reached": [
            "Cortex-M Debug Control Block: DHCSR, DCRSR, DCRDR, DEMCR.",
            "Flash Patch & Breakpoint Unit (FPB) — hardware breakpoint comparators.",
            "Data Watchpoint & Trace Unit (DWT) — hardware watchpoint comparators + PC sampling.",
            "Instrumentation Trace Macrocell (ITM) — printf-style trace → SWO.",
            "Embedded Trace Macrocell (ETM) — full instruction-data trace → TPIU.",
            "Cross-Trigger Interface (CTI) — multi-core debug synchronization.",
            "Trace Port Interface Unit (TPIU) — funnels trace to SWO or parallel trace pins.",
            "CoreSight ROM Tables.",
        ],
    }
    f["internal_scan_optional"] = (
        "Beyond ADIv5 SWD, SoCs typically implement traditional internal scan chains accessed via "
        "the SWJ-DP's JTAG mode. These are vendor-specific and orthogonal to SWD."
    )
    f["bist_optional"] = (
        "RUNBIST is a JTAG instruction NOT an SWD feature. SoCs that implement BIST typically initiate "
        "it via vendor-specific MEM-AP-reachable BIST control registers OR via the SWJ-DP's JTAG mode."
    )
    # FORCE overwrite applications (JTAG fills with board-etch / cluster testing)
    f["applications_documented_in_adiv5"] = [
        "Cortex-M CPU debug.",
        "Flash programming via MEM-AP.",
        "Multi-core SoC debug coordination via CTI.",
        "ITM / DWT trace capture via SWO.",
        "ETM trace capture via TPIU trace pins.",
        "Boot ROM / secure boot enrolment via vendor-specific MEM-AP registers.",
        "Debug authentication via DBGEN/NIDEN/SPIDEN/SPNIDEN gating.",
        "Post-production debug-disable via vendor fuse.",
    ]
    f["test_methodologies"] = [
        "Debug Access (not classical DFT).",
        "CoreSight Trace Capture via SWO or TRACEDATA pins.",
        "BIST initiation via vendor MEM-AP registers.",
        "Internal Scan Test orthogonal to ADIv5.",
    ]
    f["design_for_test_flow_relationship_to_adiv5"] = [
        "ADIv5 SWD is layered ABOVE the SoC's classical DFT.",
        "SoCs typically expose both ADIv5 SWD (for debug) AND IEEE 1149.1 JTAG (for boundary-scan + scan-test) via SWJ-DP.",
        "Production test typically: JTAG IDCODE compare → JTAG boundary-scan → JTAG ATPG → BIST → switch to SWD → SWD IDCODE verify → flash program + functional verify.",
        "ADIv5 SWD enables in-system functional verification during production test.",
    ]
    f["data_formats_supported_by_adiv5"] = [
        "CoreSight ROM Table — published at MEM-AP.BASE.",
        "CoreSight Trace formats — ITM / DWT / ETM packets.",
        "CMSIS-DAP protocol — Arm's open USB-side debug-probe protocol.",
        "OpenOCD / pyOCD / probe-rs — open-source host-side libraries.",
        "GDB / LLDB Remote Serial Protocol.",
    ]
    f["notes"] = (
        "ADIv5 SWD is the modern Arm debug-access story. SWD is NOT a boundary-scan architecture — to "
        "get true boundary-scan, the SoC must also implement IEEE 1149.1 JTAG, typically via SWJ-DP's "
        "JTAG mode. ADIv6 (Arm IHI 0074) is the successor."
    )
    d["fields"] = f
    _write(p, d)


# ============================================================
# L21 POWER INTENT
# ============================================================
def _l21(gd: Path, ic_name: Optional[str]) -> None:
    p = gd / "L21_POWER_INTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    if ic_name:
        f["ic_name"] = ic_name
    f["power_intent_present"] = (
        "partial — ADIv5 specifies CSYSPWRUPREQ / CDBGPWRUPREQ / CDBGRSTREQ control bits in CTRL/STAT "
        "but does not formally define UPF / CPF power-domain partitioning."
    )
    f["low_power_modes_summary"] = {
        "CSYSPWRUPREQ_ACK_handshake":  "Host writes CSYSPWRUPREQ=1; reads CTRL/STAT and waits for CSYSPWRUPACK=1.",
        "CDBGPWRUPREQ_ACK_handshake":  "Host writes CDBGPWRUPREQ=1; waits for CDBGPWRUPACK=1. Without it, DHCSR access returns FAULT.",
        "CDBGRSTREQ_ACK_handshake":    "Host writes CDBGRSTREQ=1; waits for CDBGRSTACK=1.",
        "SWCLK_stopped_in_idle":       "SW-DP FSM holds Idle when host stops SWCLK; dynamic current drops to leakage.",
        "DAP_always_on_partitioning":  "SW-DP wire-level FSM + DP register set placed in always-on debug-power domain.",
    }
    f["swd_in_deep_sleep_use_case"] = [
        "Cortex-M MCUs enter WFI/WFE / standby with CPU clock gated. SW-DP can remain alive in always-on.",
        "Host probe asserts CDBGPWRUPREQ + CSYSPWRUPREQ to wake debug + system power domains.",
        "Some MCUs advertise 'debug-during-stop-mode'.",
    ]
    f["wake_on_debug"] = [
        "ARM CoreSight DAP supports 'wake-on-debug'.",
        "Implementation via CDBGPWRUPREQ handshake.",
    ]
    f["isolation_clamps_during_power_gate"] = [
        "Isolation clamps required between MEM-AP and gated system bus.",
        "Host accesses return FAULT (STICKYERR) until system domain powered up.",
    ]
    f["ctrl_stat_power_bits_summary"] = {
        "bit_28": "CDBGPWRUPREQ — debug power-up request.",
        "bit_29": "CDBGPWRUPACK — debug power-up acknowledge.",
        "bit_30": "CSYSPWRUPREQ — system power-up request.",
        "bit_31": "CSYSPWRUPACK — system power-up acknowledge.",
        "bit_26": "CDBGRSTREQ — debug reset request.",
        "bit_27": "CDBGRSTACK — debug reset acknowledge.",
    }
    f["notes"] = (
        "ADIv5 explicitly provides protocol-level handshakes for debug + system power-up. This is more "
        "sophisticated than IEEE 1149.1 JTAG, which has no power-up handshakes. MCU vendors typically "
        "route the DP + SW-DP to an always-on power rail; modern Cortex-M parts advertise < 100 µA "
        "standby including an always-on SW-DP."
    )
    d["fields"] = f
    _write(p, d)


# ============================================================
# L22 VERIFICATION PLAN
# ============================================================
def _l22(gd: Path, ic_name: Optional[str]) -> None:
    p = gd / "L22_VERIFICATION_PLAN.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    if ic_name:
        f["ic_name"] = ic_name
    f["verification_plan_present"] = (
        "implicit — ARM IHI 0031C defines architectural rules, 46-bit transaction format, mandatory "
        "DP/AP register sets, sticky-error and posted-read semantics, line-reset, and SWJ-DP "
        "mode-switching."
    )
    f["verification_categories_derived_from_spec"] = [
        "Line reset conformance — ≥ 50-cycle SWDIO=HIGH from each reachable internal state.",
        "IDCODE/DPIDR readback — valid DPIDR with bit 0 = 1.",
        "Request packet parity — corrupted Request silently dropped.",
        "Request Start/Stop/Park enforcement.",
        "ACK code validation — only OK/WAIT/FAULT.",
        "Data parity on read — 33rd bit = even parity.",
        "Data parity on write — WDATAERR set, clearable via ABORT.WDERRCLR.",
        "Turnaround conformance — default 1-cycle; TRNCNT can extend to 4.",
        "ABORT register — DAPABORT / STKCMPCLR / STKERRCLR / WDERRCLR / ORUNERRCLR.",
        "SELECT register — APSEL + APBANKSEL + DPBANKSEL routing.",
        "RDBUFF — posted-read recovery.",
        "CTRL/STAT sticky bits — set per spec-defined triggers.",
        "CSYSPWRUPREQ / CDBGPWRUPREQ — host write → target ack.",
        "CDBGRSTREQ — debug-domain reset request.",
        "AP IDR readback for each implemented AP.",
        "MEM-AP BASE readback — Present bit + 4 KB-aligned address.",
        "MEM-AP TAR + DRW round-trip.",
        "MEM-AP auto-increment Single — TAR += transfer size.",
        "MEM-AP auto-increment Packed — multiple sub-word per DRW.",
        "MEM-AP 4K wrap-around — TAR wraps at 4 KB.",
        "MEM-AP burst write + RDBUFF flush.",
        "MEM-AP burst read + RDBUFF recovery.",
        "WAIT retry — host can retry until OK.",
        "FAULT recovery — CTRL/STAT + ABORT clear + retry.",
        "Posted-read overrun — STICKYORUN set.",
        f"SWJ-DP JTAG-to-SWD selection ({_SWJ_DP_JTAG_TO_SWD_HEX}).",
        f"SWJ-DP SWD-to-JTAG selection ({_SWJ_DP_SWD_TO_JTAG_HEX}).",
        "Multi-drop SWD (ADIv5.2) — TARGETSEL addressing.",
        "DLPIDR readback — TINSTANCE + PROTVSN fields.",
        "TARGETID readback — TPARTNO + TDESIGNER + TREVISION.",
        "DHCSR halt — write C_HALT=1 + DBGKEY → CPU halts.",
        "DHCSR step — single-instruction step.",
        "DCRSR + DCRDR — read/write any CPU register.",
        "CoreSight ROM Table walk.",
        "SWCLK frequency margin across PVT.",
        "Signal integrity across probe cable lengths.",
        "VDD-IO range — full SoC range.",
        "Concurrent CPU activity — SWD MEM-AP non-interference.",
        "Power-gate isolation — FAULT until CSYSPWRUPACK=1.",
    ]
    f["notes"] = (
        "ARM does not publish an official ADIv5 compliance testbench, but open-source projects "
        "(pyOCD, probe-rs, OpenOCD) plus commercial Arm DesignVerify DAP IP testbenches cover the "
        "categories above. Most common compliance failures historically: (1) DPIDR bit 0 not RAO, "
        "(2) SWJ-DP selection sequence endianness, (3) MEM-AP TAR not wrapping at 4 KB, "
        "(4) posted-read off-by-one."
    )
    d["fields"] = f
    _write(p, d)


# ============================================================
# L23 SECURITY REQUIREMENTS
# ============================================================
def _l23(gd: Path, ic_name: Optional[str]) -> None:
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    if ic_name:
        f["ic_name"] = ic_name
    f["security_requirements_present"] = (
        "partial — ADIv5 itself does not standardize debug-authentication or debug-disable, but ARM "
        "has layered a debug-authentication interface (DBGEN / NIDEN / SPIDEN / SPNIDEN) on top of the "
        "DAP. Per-vendor SoCs add OTP fuse-based debug-disable mechanisms."
    )
    f["notes"] = (
        "ARM IHI 0031C does not require confidentiality, integrity, or authentication features at the "
        "protocol layer. Real-world Arm MCUs always layer some form of debug protection on top — "
        "usually via OTP fuses programmed at production test."
    )
    f["industrial_security_extensions_layered_on_swd_adiv5"] = [
        "ARM CoreSight DBGEN/NIDEN/SPIDEN/SPNIDEN — 4-bit external authentication signal.",
        "ARMv8-M Security Extension (TrustZone) — Secure debug gated by SPIDEN.",
        "ST Read-Out Protection (RDP) — Level 0/1/2.",
        "Nordic UICR.APPROTECT.",
        "NXP DCFG + Secure Boot.",
        "ESP32 efuse JTAG_DISABLE.",
        "Renesas Synergy Security MPU.",
        "Silicon Labs Secure Vault.",
        "Microchip ROM-protected debug.",
        "TI MSP432 JTAGLOCK + CCFG.",
        "Atmel/Microchip CRYPTOAUTHLIB-based debug authentication.",
    ]
    f["threat_model_for_open_swd"] = [
        "Attacker with physical access can read out flash via MEM-AP DRW.",
        "Vendor-specific MEM-AP registers may expose secure-boot keys / OTP / SRAM.",
        "Glitch-injection during SWD power-up handshake can bypass debug-disable.",
        "Side-channel attacks on DBGEN gating logic.",
        "Solder probes onto fine-pitch test pads.",
    ]
    f["common_production_mitigations"] = [
        "Burn debug-disable fuse (RDP Level 2 / APPROTECT / JTAG_DISABLE).",
        "Implement debug authentication via DBGEN/NIDEN/SPIDEN/SPNIDEN.",
        "Use TrustZone-M to isolate Secure code.",
        "Remove SWD header from production boards.",
        "Disable SWO trace pin in production.",
        "Read-out-only firmware disabling SWD MEM-AP at first boot.",
        "Secure Boot ROM mass-erases flash on unauthorized debug attempt.",
        "Tamper-detection mesh + physical countermeasures.",
    ]
    f["tooling_security_considerations"] = [
        "Open-source probes (CMSIS-DAP, Black Magic) easier to audit.",
        "Commercial probes (J-Link, ST-Link) lock firmware; vendor security updates.",
        "OpenOCD / pyOCD / probe-rs open-source host-side libraries.",
        "Validate VDD-IO before connecting.",
    ]
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
def is_swd(blob: str) -> bool:
    """Content-only `swd` detector (importable, lifted from the runner) with a
    FOREIGN-PRIMARY DEFER for its derived-superset sibling ARM CoreSight.

    Empty-safe. Reads ONLY ``blob`` (spec text). Byte-for-byte the same boolean
    the runner used inline, BELOW the defer.

    FOREIGN-PRIMARY DEFER — ARM CoreSight (a genuine derived-CHILD of the SWD
    transport). CoreSight is the on-chip debug-and-TRACE ARCHITECTURE that runs
    ON TOP of an SWD (or JTAG) wire transport: its document names SWD / ADIv5 /
    SWDIO / SWCLK / DAP / DP / AP as the transport layer, so the bare SWD
    structural signature below necessarily fires on a CoreSight spec. The
    correct sibling-MUTEX discriminator (mirrors `is_coresight`'s own
    SWD-defer, inverted) is the structure that is PRESENT in a CoreSight
    trace-architecture doc and ABSENT from a pure SWD/ADIv5 Debug-Port doc: the
    on-chip TRACE FABRIC — an AMBA Trace Bus (ATB) trace transport WITH a trace
    FUNNEL and a trace REPLICATOR, plus at least one trace SINK
    (TPIU/ETB/ETF/ETR) and at least one trace SOURCE (ETM/PTM/ITM/STM). A pure
    SWD/ADIv5 spec describes only the serial-wire Debug Port + MEM-AP + ROM
    table and lacks the ATB-funnel-replicator trace transport, so this defer
    fires ONLY when the blob's DOMINANT subject is the CoreSight trace fabric.
    These are GENERAL protocol-semantic / architectural-block tokens — no
    benchmark-name / chip / SKU literal.
    """
    if not blob:
        return False

    low = blob.lower()
    # --- FOREIGN-PRIMARY DEFER: ARM CoreSight trace architecture (superset). ---
    # ATB used as a TRACE interconnect (parenthetical/standalone forms).
    _cs_atb = ("amba trace bus" in low or " atb " in f" {low} "
               or "atb)" in low or "(atb" in low)
    _cs_funnel = "funnel" in low
    _cs_replicator = "replicator" in low
    # Trace sinks (off-chip TPIU / on-chip ETB/ETF/ETR RAM).
    _cs_sink = sum([
        ("tpiu" in low or "trace port interface unit" in low),
        ("etb" in low or "embedded trace buffer" in low),
        ("etf" in low or "embedded trace fifo" in low),
        ("etr" in low or "embedded trace router" in low),
    ])
    # Trace sources.
    _cs_src = sum([
        ("etm" in low or "embedded trace macrocell" in low),
        ("ptm" in low or "program trace macrocell" in low),
        ("itm" in low or "instrumentation trace" in low),
        ("stm" in low or "system trace macrocell" in low
         or "system trace protocol" in low),
    ])
    _cs_trace_transport = _cs_atb and _cs_funnel and _cs_replicator
    coresight_primary = (
        _cs_trace_transport and _cs_sink >= 1 and _cs_src >= 1)
    if coresight_primary:
        return False

    # --- STRUCTURAL SWD / ADIv5 signature (unchanged from the runner's inline
    #     detector). ---
    return bool(
        ("SWDIO" in blob and "SWCLK" in blob
            and "DAP" in blob)
        or ("SWD" in blob and "ADIv5" in blob
            and "DP" in blob and "AP" in blob)
        or ("SWJ-DP" in blob and "ARM" in blob
            and "Debug Port" in blob))
