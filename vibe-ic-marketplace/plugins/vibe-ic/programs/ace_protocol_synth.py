"""AMBA AXI/ACE coherency-extension protocol synth helper.

ic_class-gated overlay for `bus_interconnect_protocol` specs that exhibit
the AMBA AXI Coherency Extensions (ACE) structural signature. Applies
ARM IHI 0022E ACE-specific content (snoop channels AC/CR/CD, AxDOMAIN,
AxSNOOP, AxBAR, RRESP PassDirty/IsShared, BRESP DataTransfer, CRRESP,
RACK/WACK, 5-state cache model UC/UD/SC/SD/I, DVM, barriers, ACE-Lite)
across L1-L23 + L8 timing + L14-L23.

Doctrine: structural-signature detection IS general within an ic_class
(same approach as ahb_apb / spi / i2c / uart / can / usb / i2s / ddr /
ethernet / nvme / i3c / sdmmc / sata / pcie / jtag / mipi / onewire).
The AXI baseline already exists (arm_aix path via R46-R52 universal
protocol-fact synth). ACE synth fires only when ACE-specific signals
are present: AxBAR + AxDOMAIN + AxSNOOP, OR (ACE keyword + ReadShared
+ ReadUnique), OR (cache coherency + AXI + AMBA), OR (DVM + TLB + AXI).

When ACE synth fires it must FORCE-overwrite any L1/L4 keys that
arm_aix-class AXI synth populates with AXI-only content (ic_name,
purpose, key_features, channel summaries) so the ACE-specific gold
wins. Other keys are setdefault-style (preserve user / upstream).

Public entry: `apply_ace_synth(generated_docs_dir, is_ace, ace_ic_name)`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import l_doc_generator_stamp as _stamp


# v0.1.87 — current detected ACE issue (set by apply_ace_synth before _l*).
# "E" = IHI 0022E (2013) / "H" = IHI 0022H (2020+) / None = unknown
_ACE_ISSUE: Optional[str] = None


# ============================================================
# Generic helpers
# ============================================================
def _empty(v) -> bool:
    return v in (None, {}, []) or (isinstance(v, str) and not v.strip())


def _read(p: Path) -> dict:
    return json.loads(p.read_text())


def _write(p: Path, d: dict) -> None:
    # THE L-document write chokepoint: stamps the producing release onto
    # the document, then serialises it byte-identically to before.
    _stamp.dump(p, d)


def _ensure_dict(d: dict, key: str) -> dict:
    """setdefault is a no-op if key exists with value None — use explicit
    empty-check to handle that case."""
    if d.get(key) in (None, "", []):
        d[key] = {}
    return d[key]


def _ensure_full(d: dict, key: str, value):
    """Force-set when key missing or value empty (None / "" / [] / {})."""
    cur = d.get(key)
    if cur is None or cur == "" or cur == [] or cur == {}:
        d[key] = value
    return d[key]


def _force_set(d: dict, key: str, value) -> None:
    """Unconditional overwrite — used for keys that arm_aix-class AXI
    synth may have written with AXI-only content; ACE gold must win."""
    d[key] = value


def _force_top_if_present(doc: dict, key: str, value) -> None:
    """v0.1.87 — force-overwrite a top-level key ONLY if it already exists
    in the doc. Used to override stale top-level keys written by upstream
    AHB+APB / SPI / R50 synth before ACE synth ran. Does not introduce new
    top-level keys (preserves the arm_aix `fields.*` canonical layout).
    """
    if key in doc:
        doc[key] = value


# ============================================================
# Public entry
# ============================================================
def apply_ace_synth(generated_docs_dir: Path,
                    is_ace: bool,
                    ace_ic_name: Optional[str],
                    issue: Optional[str] = None) -> None:
    """Apply ACE-specific synth when the structural signature matched.

    `issue` (when known) selects the IHI-0022 revision-specific defaults:
    - "E" → IHI 0022E (2013) standalone ACE spec
    - "H" → IHI 0022H (2020+) merged AXI/ACE spec
    - None → unknown issue; use NEUTRAL defaults (no version-specific content)

    fail-open contract: print errors but never raise.
    """
    if not is_ace:
        return
    # v0.1.87 — issue-specific defaults dispatched via module-level dict so
    # downstream helpers (_l1, _l9, _l17, _l21) can pick the right canonical
    # ic_name / document_id / release_history without hardcoding.
    global _ACE_ISSUE
    _ACE_ISSUE = issue
    gd = Path(generated_docs_dir)

    try:
        # Force-overwrite ic_name across all 24 L docs, even if an
        # arm_aix-class AXI synth (or R46-R52 generic protocol-fact synth)
        # has already populated it with the bare-AXI name.
        if ace_ic_name is not None:
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
                    # v0.1.87: also force top-level ic_name when it already
                    # exists (e.g., AHB+APB synth wrote it at top level before
                    # ACE synth ran). Otherwise parity diff reads the stale
                    # AXI-only / AHB-APB ic_name from the top level and treats
                    # the ACE fields.ic_name as duplicate.
                    if "ic_name" in d:
                        d["ic_name"] = ace_ic_name
                    f = _ensure_dict(d, "fields")
                    if isinstance(f, dict):
                        # arm_aix layout uses fields.ic_name
                        f["ic_name"] = ace_ic_name
                        d["fields"] = f
                    else:
                        # Some upstreams may have written ic_name at top level
                        d["ic_name"] = ace_ic_name
                    _write(q, d)

            for n in [
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
                    if "ic_name" in d:
                        d["ic_name"] = ace_ic_name
                    f = _ensure_dict(d, "fields")
                    f["ic_name"] = ace_ic_name
                    d["fields"] = f
                    _write(q, d)

        _l1(gd)
        _l2(gd)
        _l3(gd)
        _l4(gd)
        _l5(gd)
        _l6(gd)
        _l7(gd)
        _l8_rtl_constants(gd)
        _l8_timing_waveform(gd)
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
    except Exception as exc:  # fail-open
        print(f"[ace_protocol_synth] WARN: {exc}")


def _f(d: dict) -> dict:
    """Return d['fields'] dict, creating it if missing/empty."""
    return _ensure_dict(d, "fields")


# ============================================================
# L1 DATASHEET
# ============================================================
def _l1(gd: Path) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _f(d)
    # v0.1.87 — issue-aware document_id / issuer / copyright. For unknown
    # issue or H, do NOT force-set hardcoded 0022E values.
    if _ACE_ISSUE == "E":
        _force_set(f, "document_id", "ARM IHI 0022E (ID022613)")
        _force_set(f, "issuer", "Arm Limited (originally ARM Limited)")
        _force_set(f, "copyright",
            "Copyright (c) 2003, 2004, 2010, 2011, 2013 ARM. All rights reserved.")
        _force_set(f, "confidentiality", "Non-Confidential")
        f.setdefault("issue", "E")
        f.setdefault("issue_date", "22 February 2013")
        f.setdefault("supersedes",
            "ARM IHI 0022D (28 October 2011); ARM IHI 0022D-2c "
            "(03 June 2011 beta) — first inclusion of ACE")
    elif _ACE_ISSUE == "H":
        # IHI 0022H (2020) values — used by arm_aix benchmark.
        f.setdefault("document_id", "ARM IHI 0022H (ID040120)")
        f.setdefault("issuer", "Arm Limited")
        f.setdefault("copyright",
            "Copyright (c) 2003-2020 Arm Limited or its affiliates")
        f.setdefault("confidentiality", "Non-Confidential")
        f.setdefault("issue", "H")
    else:
        # Unknown issue — keep whatever upstream synth wrote, use setdefault.
        f.setdefault("issuer", "Arm Limited")
        f.setdefault("confidentiality", "Non-Confidential")
    # release_history: only emit the E-canonical list when issue=E
    if _ACE_ISSUE == "E":
        f.setdefault("release_history", [
            {"date": "16 June 2003",     "issue": "A",   "change": "First release"},
            {"date": "19 March 2004",    "issue": "B",   "change": "First release of AXI specification v1.0"},
            {"date": "03 March 2010",    "issue": "C",   "change": "First release of AXI specification v2.0"},
            {"date": "03 June 2011",     "issue": "D-2c","change": "Public beta draft of AMBA AXI and ACE Protocol Specification (first ACE description)"},
            {"date": "28 October 2011",  "issue": "D",   "change": "First release of AMBA AXI and ACE Protocol Specification"},
            {"date": "22 February 2013", "issue": "E",   "change": "Second release of AMBA AXI and ACE Protocol Specification"},
        ])
    # v0.1.87 — variants list. Only force-set for issue E (ace_chi gold).
    # For arm_aix / unknown, use setdefault to preserve upstream R50 list.
    if _ACE_ISSUE == "E":
        _force_set(f, "protocol_variants_described", [
            "AXI3 (AMBA 3)",
            "AXI4 (AMBA 4)",
            "AXI4-Lite (AMBA 4)",
            "ACE (AMBA 4) — AXI Coherency Extensions",
            "ACE-Lite (AMBA 4) — coherent reads/writes without local cache",
        ])
        _force_set(f, "purpose",
            "Defines AMBA AXI3, AXI4, AXI4-Lite on-chip bus protocols, plus "
            "the AXI Coherency Extensions (ACE and ACE-Lite). ACE adds "
            "hardware cache-coherency on top of AXI4 for multi-master "
            "systems with caches; ACE-Lite adds coherent reads/writes for "
            "non-cached IOs (DMA / GPU / IO accelerators). Provides a "
            "complete coherency framework: shareability domains, snoop "
            "transactions, distributed virtual memory (DVM) messages, and "
            "barrier transactions.")
    else:
        # arm_aix / unknown: setdefault only — preserve upstream R50 lists.
        f.setdefault("protocol_variants_described", [
            "AXI3 (AMBA 3)",
            "AXI4 (AMBA 4)",
            "AXI4-Lite (AMBA 4)",
            "AXI5 (AMBA 5)",
            "AXI5-Lite (AMBA 5)",
            "ACE (AMBA 4)",
            "ACE-Lite (AMBA 4)",
        ])
        f.setdefault("purpose",
            "Defines the AMBA AXI/ACE on-chip bus protocols for "
            "high-performance, high-frequency master-slave communication, "
            "suitable for high-bandwidth low-latency designs as well as "
            "coherent multi-master systems with caches.")
    f.setdefault("key_features_axi_baseline", [
        "Separate address/control and data phases",
        "Unaligned data transfers via byte strobes",
        "Burst-based transactions with only start address issued",
        "Separate read and write data channels (low-cost DMA)",
        "Multiple outstanding addresses",
        "Out-of-order transaction completion",
        "Easy register stage addition for timing closure",
        "Backward compatible with AHB and APB",
    ])
    f.setdefault("key_features_ace_extensions", [
        "Hardware cache-coherency via snoop transactions",
        "Three new snoop channels: AC (Snoop Address), CR (Snoop "
        "Response), CD (Snoop Data)",
        "5-state cache-line coherency model: UC/UD/SC/SD/I",
        "AxDOMAIN[1:0] — Non-shareable / Inner / Outer / System "
        "shareability domains",
        "AxSNOOP — encodes coherent transaction types",
        "AxBAR — barrier transaction encoding",
        "Extended RRESP[3:0] — PassDirty + IsShared bits",
        "Extended BRESP[2] — DataTransfer for pass-dirty",
        "RACK / WACK acknowledge signals",
        "Distributed Virtual Memory (DVM) for TLB / BP / IC invalidate",
        "ACE-Lite subset for non-cached masters",
    ])
    f.setdefault("new_signals_added_by_ace", {
        "read_address_channel_AR":   ["ARDOMAIN[1:0]", "ARSNOOP[3:0]", "ARBAR[1:0]"],
        "write_address_channel_AW":  ["AWDOMAIN[1:0]", "AWSNOOP[2:0]", "AWBAR[1:0]", "AWUNIQUE (optional)"],
        "read_data_channel_R":       ["RRESP[3:2] PassDirty/IsShared"],
        "write_response_channel_B":  ["BRESP[2] DataTransfer"],
        "snoop_address_channel_AC":  ["ACVALID", "ACREADY", "ACADDR", "ACSNOOP[3:0]", "ACPROT[2:0]"],
        "snoop_response_channel_CR": ["CRVALID", "CRREADY", "CRRESP[4:0]"],
        "snoop_data_channel_CD":     ["CDVALID", "CDREADY", "CDDATA", "CDLAST"],
        "acknowledge_signals":       ["RACK (master->interconnect)",
                                      "WACK (master->interconnect)"],
    })
    f.setdefault("cache_line_states_5state", {
        "UC_UniqueClean": "Only this cache holds a copy; same as main memory.",
        "UD_UniqueDirty": "Only this cache holds a copy; differs from memory; this cache owns write-back.",
        "SC_SharedClean": "Other caches may hold copy; same as main memory.",
        "SD_SharedDirty": "Other caches may hold copy; differs from memory; this cache owns write-back.",
        "I_Invalid":      "This cache does not hold a valid copy.",
    })
    _force_set(f, "five_axi_channels", [
        {"name": "AR (Read Address)",     "direction": "Master -> Slave"},
        {"name": "R  (Read Data)",        "direction": "Slave -> Master"},
        {"name": "AW (Write Address)",    "direction": "Master -> Slave"},
        {"name": "W  (Write Data)",       "direction": "Master -> Slave"},
        {"name": "B  (Write Response)",   "direction": "Slave -> Master"},
    ])
    f.setdefault("three_ace_snoop_channels", [
        {"name": "AC (Snoop Address)",  "direction": "Interconnect -> Master (cached)"},
        {"name": "CR (Snoop Response)", "direction": "Master (cached) -> Interconnect"},
        {"name": "CD (Snoop Data)",     "direction": "Master (cached) -> Interconnect"},
    ])
    f.setdefault("supported_data_bus_widths_bits",
                 [8, 16, 32, 64, 128, 256, 512, 1024])
    f.setdefault("snoop_data_bus_widths_bits",
                 [32, 64, 128, 256, 512, 1024])
    # v0.1.87 — endianness phrased per issue.
    if _ACE_ISSUE == "E":
        f.setdefault("endianness",
            "byte-invariant (inherited from AXI baseline)")
    elif _ACE_ISSUE == "H":
        f.setdefault("endianness",
            "byte-invariant; both little-endian and big-endian components "
            "can coexist in a single memory space")
    else:
        f.setdefault("endianness", "byte-invariant")
    f.setdefault("max_burst_length", {
        "AXI3": 16, "AXI4_INCR": 256, "AXI4_FIXED_WRAP": 16,
        "ACE_cache_line": "implementation-defined cache-line burst"})
    f.setdefault("burst_boundary_rule",
        "A burst must not cross a 4KB address boundary (inherited from AXI).")
    f.setdefault("intended_audience",
        "Hardware and software engineers familiar with AMBA AXI3/AXI4 who "
        "design coherent multi-master systems, processor clusters, "
        "accelerators, or IO bridges.")
    f.setdefault("vendor",
        "Arm Limited, Company 02557590 registered in England, "
        "110 Fulbourn Road, Cambridge, England CB1 9NJ")
    f.setdefault("package_info_present", False)
    f.setdefault("package_info_rationale",
        "AXI/ACE is a bus protocol specification, not a packaged IC. "
        "No package/pinout/electrical-DC data exists in this document.")
    f.setdefault("electrical_specs_present", False)
    f.setdefault("electrical_specs_rationale",
        "Protocol spec defines only logical signal semantics. "
        "No voltage/current/IO-standard information.")
    # v0.1.87 — override TOP-LEVEL keys that upstream AHB+APB / SPI / R50
    # synth wrote with AXI-only or AHB-APB content. ACE gold must win at
    # both `fields.*` AND top-level (parity_diff reads top-level first).
    # Only mirror keys that ACE synth actually populated (avoid KeyError).
    for _k in ("issuer", "purpose", "endianness", "intended_audience",
               "document_id", "confidentiality", "protocol_variants_described",
               "burst_boundary_rule", "package_info_present",
               "electrical_specs_present", "vendor"):
        if _k in f:
            _force_top_if_present(d, _k, f[_k])
    d["fields"] = f
    _write(p, d)


# ============================================================
# L2 FRS — coherency functional requirements
# ============================================================
def _l2(gd: Path) -> None:
    p = gd / "L2_FRS.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _f(d)
    f.setdefault("functional_requirements_axi_baseline_inherited", [
        {"id": "FR-HANDSHAKE-01", "text": "All five AXI transaction channels + three ACE snoop channels use the same VALID/READY handshake.", "source": "A3.2.1 / C3.6 / C3.7 / C3.8"},
        {"id": "FR-CLOCK-01",     "text": "Single ACLK per interface; rising-edge sampled.", "source": "A3.1.1"},
        {"id": "FR-RESET-01",     "text": "ARESETn active-LOW; async assert, sync deassert.", "source": "A3.1.2"},
        {"id": "FR-4KB-BOUNDARY", "text": "A burst must not cross a 4KB address boundary.", "source": "A3.4.1"},
    ])
    f.setdefault("functional_requirements_ace_extensions", [
        {"id": "FR-ACE-DOMAIN-01",   "text": "Every AR/AW must drive ARDOMAIN/AWDOMAIN selecting Non-shareable / Inner / Outer / System.", "source": "C3.1.1"},
        {"id": "FR-ACE-DOMAIN-03",   "text": "A System-domain memory location cannot be held in any cache.", "source": "C3.1.1"},
        {"id": "FR-ACE-SNOOP-01",    "text": "Coherent transactions use ARSNOOP[3:0] / AWSNOOP[2:0]. Permitted encodings depend on ARBAR[0] + AxDOMAIN (Tables C3-7, C3-8).", "source": "C3.1.3"},
        {"id": "FR-ACE-SNOOP-02",    "text": "ReadShared may return shared/unique copy; ReadClean must not return dirty; ReadNotSharedDirty forbids SharedDirty; ReadUnique invalidates others; CleanUnique cleans local+invalidates others; MakeUnique invalidates others without data.", "source": "C4 Coherent transactions"},
        {"id": "FR-ACE-SNOOP-03",    "text": "Cache-maintenance: CleanShared (write-back + retain Shared), CleanInvalid (write-back + invalidate), MakeInvalid (invalidate without write-back).", "source": "C4 Cache maintenance"},
        {"id": "FR-ACE-SNOOP-04",    "text": "Memory-update writes: WriteBack (dirty + invalidate locally), WriteClean (dirty + retain Clean), Evict (cache-line removal notification), WriteEvict (optional, requires AWUNIQUE).", "source": "C3.1.3 / C4"},
        {"id": "FR-ACE-SNOOP-05",    "text": "Coherent writes for non-cached or ACE-Lite masters: WriteUnique (partial) and WriteLineUnique (full line).", "source": "C4 WriteUnique"},
        {"id": "FR-ACE-BAR-01",      "text": "AxBAR[0]=1 indicates a barrier transaction; AxBAR[1] encodes Memory vs Synchronization barrier.", "source": "C3.1.2 / C8"},
        {"id": "FR-ACE-BAR-02",      "text": "Barrier transactions can have any AxDOMAIN; choice of domain selects barrier scope.", "source": "C3.1.2 / C8"},
        {"id": "FR-ACE-DVM-01",      "text": "DVM messages use ARSNOOP=0b1110 (DVMComplete) and 0b1111 (DVMMessage) — TLB / branch-predictor / I-cache invalidate, virtual-address sync.", "source": "C3.1.3 / C12"},
        {"id": "FR-ACE-RRESP-01",    "text": "RRESP extended to [3:0]: [2]=PassDirty (dirty wrt memory), [3]=IsShared (another cache may hold copy).", "source": "C3.2.1"},
        {"id": "FR-ACE-RRESP-02",    "text": "RRESP[3:2] constant for all beats of a single burst.", "source": "C3.2.1"},
        {"id": "FR-ACE-RRESP-03",    "text": "RRESP[3:2] must be 0 for ReadNoSnoop, Barrier, DVM transactions.", "source": "C3.2.1"},
        {"id": "FR-ACE-BRESP-01",    "text": "BRESP extended to [2:0]: [2]=DataTransfer (for WriteUnique/WriteLineUnique pass-dirty completion).", "source": "C3.4"},
        {"id": "FR-ACE-SNOOP-CH-01", "text": "AC channel: interconnect drives ACADDR/ACSNOOP/ACPROT/ACVALID; master drives ACREADY.", "source": "C3.6"},
        {"id": "FR-ACE-SNOOP-CH-02", "text": "CR channel: master drives CRRESP[4:0] (DataTransfer/Error/PassDirty/IsShared/WasUnique) + CRVALID; interconnect drives CRREADY.", "source": "C3.7"},
        {"id": "FR-ACE-SNOOP-CH-03", "text": "CD channel: master drives CDDATA/CDLAST/CDVALID; interconnect drives CDREADY. CD bus width may differ from RDATA/WDATA.", "source": "C3.8"},
        {"id": "FR-ACE-CHANDEP-01",  "text": "Master must wait for ACVALID+ACREADY before asserting CRVALID. Master must wait for ACVALID+ACREADY before asserting CDVALID.", "source": "C3.9 / Figure C3-1"},
        {"id": "FR-ACE-ACK-01",      "text": "RACK pulsed one ACLK after RLAST+RVALID+RREADY; WACK pulsed one ACLK after BVALID+BREADY. Single-cycle pulses.", "source": "C3.5 / C9"},
        {"id": "FR-ACE-STATES-01",   "text": "Cache-line uses 5-state model UC/UD/SC/SD/I (Table C5-4).", "source": "C5.2"},
        {"id": "FR-ACE-INVALIDATE",  "text": "Snoops that invalidate (ReadUnique/CleanInvalid/MakeInvalid) require CRRESP IsShared=0.", "source": "C5.2"},
        {"id": "FR-ACE-PASSDIRTY-01","text": "Dirty->Clean transition requires CRRESP PassDirty=1. Dirty->Invalid (not via MakeInvalid) requires PassDirty=1.", "source": "C5.2"},
        {"id": "FR-ACE-DATATRANSFER-RULE", "text": "PassDirty=1 with DataTransfer=0 is illegal. IsShared=1 for ReadUnique/CleanInvalid/MakeInvalid is illegal.", "source": "C3.7 / Table C3-23"},
        {"id": "FR-ACE-LITE-01",     "text": "ACE-Lite has no AC/CR/CD channels; restricted to ReadOnce/ReadNoSnoop/WriteUnique/WriteLineUnique/WriteNoSnoop/Barrier.", "source": "C1 (ACE-Lite description)"},
    ])
    if _empty(f.get("error_response_conditions")):
        f["error_response_conditions"] = [
            "Inherited AXI: FIFO/buffer overrun, unsupported transfer size, write to read-only, slave timeout, disabled function.",
            "ACE-specific: CRRESP[1] Error — snoop failure in cached master.",
            "Illegal AxDOMAIN/AxSNOOP/AxBAR combinations — must be detected as protocol violation.",
        ]
    # v0.1.87 — FORCE overwrite protocol_overview (R50/AHB+APB synth writes
    # AHB-format keys; both ACE 0022E gold and AXI/ACE 0022H gold need a
    # subset/superset of the same keys). Emit BOTH ACE-specific keys AND
    # AXI-baseline keys (atomicity_modes, wire_count) — extras are OK.
    ace_po = {
        "axi_channel_count": 5,
        "ace_snoop_channel_count": 3,
        "ace_lite_snoop_channel_count": 0,
        "burst_based": True,
        "out_of_order_completion": True,
        "multiple_outstanding": True,
        "cache_coherency_model": "MOESI-derivative 5-state UC/UD/SC/SD/I",
        "shareability_domains": ["Non-shareable", "Inner Shareable",
                                 "Outer Shareable", "System"],
        "snoop_protocol": ("Address-based on AC channel; response on CR; "
                           "optional data on CD"),
        "dvm_supported": True,
        "barriers_supported": True,
        "endianness": "byte-invariant",
        # AXI baseline siblings (arm_aix 0022H gold expects these):
        "atomicity_modes": ["Normal", "Exclusive", "Locked (AXI3 only)"],
        "wire_count":
            "5 independent channels, each with VALID/READY pair",
    }
    _force_set(f, "protocol_overview", ace_po)
    _force_top_if_present(d, "protocol_overview", ace_po)
    d["fields"] = f
    _write(p, d)


# ============================================================
# L3 CMD PROTOCOL — coherent-transaction encodings
# ============================================================
def _l3(gd: Path) -> None:
    p = gd / "L3_CMD_PROTOCOL.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _f(d)
    f.setdefault("rationale",
        "ACE is not an opcode/byte-oriented command protocol. It extends "
        "AXI4 with coherency-specific multi-bit fields on the AR/AW "
        "channels and adds three new snoop channels (AC/CR/CD). "
        "'Commands' are encoded as (AxBAR, AxDOMAIN, AxSNOOP) field "
        "tuples that select a coherent transaction type.")
    _force_set(f, "axi_channels_inherited", [
        {"name": "AR (Read Address)",   "direction": "Master -> Slave",
         "ace_added_signals": ["ARDOMAIN[1:0]", "ARSNOOP[3:0]", "ARBAR[1:0]"]},
        {"name": "R  (Read Data)",      "direction": "Slave -> Master",
         "ace_added_signals": ["RRESP[3:2] PassDirty/IsShared"]},
        {"name": "AW (Write Address)",  "direction": "Master -> Slave",
         "ace_added_signals": ["AWDOMAIN[1:0]", "AWSNOOP[2:0]",
                               "AWBAR[1:0]", "AWUNIQUE (optional)"]},
        {"name": "W  (Write Data)",     "direction": "Master -> Slave",
         "ace_added_signals": []},
        {"name": "B  (Write Response)", "direction": "Slave -> Master",
         "ace_added_signals": ["BRESP[2] DataTransfer"]},
    ])
    f.setdefault("ace_snoop_channels_new", [
        {"name": "AC (Snoop Address)",  "direction": "Interconnect -> Master (cached)",
         "signals": ["ACVALID", "ACREADY", "ACADDR", "ACSNOOP[3:0]", "ACPROT[2:0]"]},
        {"name": "CR (Snoop Response)", "direction": "Master (cached) -> Interconnect",
         "signals": ["CRVALID", "CRREADY", "CRRESP[4:0]"]},
        {"name": "CD (Snoop Data)",     "direction": "Master (cached) -> Interconnect",
         "signals": ["CDVALID", "CDREADY", "CDDATA", "CDLAST"]},
    ])
    f.setdefault("ace_acknowledge_signals", {
        "RACK": "Master -> Interconnect; 1 cycle after RLAST+RVALID+RREADY at rising ACLK.",
        "WACK": "Master -> Interconnect; 1 cycle after BVALID+BREADY at rising ACLK.",
    })
    f.setdefault("AxDOMAIN_encoding", {
        "0b00": "Non-shareable",
        "0b01": "Inner Shareable",
        "0b10": "Outer Shareable",
        "0b11": "System",
    })
    f.setdefault("AxBAR_encoding", {
        "AxBAR[0]": "0 = Normal, 1 = Barrier transaction",
        "AxBAR[1]": "0 = Memory barrier, 1 = Synchronization barrier (when [0]=1)",
        "barrier_types": {
            "0b00": "Normal access",
            "0b01": "Memory Barrier",
            "0b10": "Normal access",
            "0b11": "Synchronization Barrier",
        },
    })
    f.setdefault("ARSNOOP_coherent_read_encodings", {
        "0b0000": "ReadNoSnoop (Non-shareable) / ReadOnce (Shareable)",
        "0b0001": "ReadShared",
        "0b0010": "ReadClean",
        "0b0011": "ReadNotSharedDirty",
        "0b0111": "ReadUnique",
        "0b1000": "CleanShared",
        "0b1001": "CleanInvalid",
        "0b1011": "CleanUnique",
        "0b1100": "MakeUnique",
        "0b1101": "MakeInvalid",
        "0b1110":
            "DVM Complete — completion notification of a DVM message sequence",
        "0b1111":
            "DVM Message — distributed virtual memory message "
            "(TLB inv / BP inv / IC inv / VA sync)",
    })
    # v0.1.87 — RRESP[3:2] combined meaning (gold).
    f.setdefault("RRESP_combined_meaning", {
        "0b0000": "Clean Unique data — line not dirty, no other copy",
        "0b0100":
            "Pass dirty Unique — line dirty, no other copy "
            "(receiver responsible for WB)",
        "0b1000": "Shared Clean — line not dirty, may be shared",
        "0b1100":
            "Shared Dirty — line dirty AND may be shared "
            "(receiver responsible)",
    })
    # v0.1.87 — Canonical ACE sequence walkthroughs (gold). Keys aligned
    # with agent-extracted layout: 6 named sequences covering ReadShared,
    # ReadUnique, MakeUnique, CleanInvalid, WriteBack, DVM TLB invalidate.
    f.setdefault("ace_sequence_examples", {
        "ReadShared_to_shared_clean_line": [
            "Master M0 issues ReadShared (ARDOMAIN=InnerShareable, "
            "ARSNOOP=0b0001).",
            "Interconnect issues snoops on AC channel to other coherent "
            "masters (ACSNOOP=ReadShared).",
            "Other masters respond on CR with CRRESP IsShared/PassDirty "
            "as appropriate; CD provides data if cache hit.",
            "Interconnect returns data on R channel with RRESP[3:2] = "
            "IsShared/PassDirty matching cluster state.",
            "M0 issues RACK after RLAST+RVALID+RREADY.",
            "Line installed in M0 cache as SharedClean (or SharedDirty / "
            "UniqueClean / UniqueDirty per RRESP).",
        ],
        "ReadUnique_invalidate_others": [
            "Master M0 wants exclusive copy: issues ReadUnique.",
            "Interconnect snoops other caches with ACSNOOP=ReadUnique.",
            "Snooped caches invalidate their copy; IsShared in CRRESP must "
            "be 0.",
            "If a snooped cache had dirty line, it returns CRRESP with "
            "PassDirty=1, DataTransfer=1, and dirty line on CD.",
            "Interconnect returns line to M0 with RRESP[3]=0 (not shared); "
            "M0 installs as UniqueClean or UniqueDirty per RRESP[2].",
            "M0 issues RACK.",
        ],
        "MakeUnique_before_full_line_write": [
            "Master plans to overwrite a full cache line — issues "
            "MakeUnique (ARSNOOP=0b1100).",
            "Interconnect snoops other caches with ACSNOOP=MakeUnique.",
            "Snooped caches invalidate without returning data.",
            "Interconnect returns single transfer with RDATA ignored, "
            "RLAST=1.",
            "M0 issues RACK; then writes the new line via "
            "WriteBack/WriteClean.",
        ],
        "CleanInvalid_cache_maintenance": [
            "Master issues CleanInvalid (ARSNOOP=0b1001) — used by "
            "software to flush+invalidate.",
            "Interconnect snoops with ACSNOOP=CleanInvalid.",
            "Snooped dirty caches must write back via CD; clean caches "
            "optionally write back.",
            "All snooped caches transition to Invalid; CRRESP IsShared=0.",
            "Single RDATA transfer (ignored); RLAST=1; M0 issues RACK.",
        ],
        "WriteBack_evict_dirty_line": [
            "Cached master decides to evict a UniqueDirty/SharedDirty line.",
            "Master issues WriteBack (AWSNOOP=0b011, AWDOMAIN appropriate).",
            "Master sends W data over W channel.",
            "Slave returns BRESP OKAY; master issues WACK; line removed "
            "from cache.",
        ],
        "DVM_TLB_invalidate": [
            "Initiator master issues DVMMessage (ARSNOOP=0b1111) with "
            "TLB-invalidate payload encoded in ARADDR/ARLEN/ARPROT.",
            "Interconnect distributes DVM message via AC channel to all "
            "targeted masters.",
            "Each target master invalidates the relevant TLB entries and "
            "acknowledges via CRRESP.",
            "Initiator issues a follow-up DVMComplete (ARSNOOP=0b1110) "
            "once all targets have responded.",
        ],
    })
    f.setdefault("AWSNOOP_coherent_write_encodings", {
        "0b000_NS_or_System": "WriteNoSnoop",
        "0b000_Shareable":    "WriteUnique",
        "0b001":              "WriteLineUnique",
        "0b010":              "WriteClean",
        "0b011":              "WriteBack",
        "0b100":              "Evict",
        "0b101":              "WriteEvict (requires AWUNIQUE)",
    })
    f.setdefault("RRESP_extension", {
        "RRESP[1:0]": "AXI baseline: 00 OKAY, 01 EXOKAY, 10 SLVERR, 11 DECERR",
        "RRESP[2]":   "PassDirty",
        "RRESP[3]":   "IsShared",
    })
    f.setdefault("BRESP_extension", {
        "BRESP[1:0]": "AXI baseline: 00 OKAY, 01 EXOKAY, 10 SLVERR, 11 DECERR",
        "BRESP[2]":   "DataTransfer",
    })
    f.setdefault("CRRESP_snoop_response_encoding", {
        "CRRESP[0]": "DataTransfer",
        "CRRESP[1]": "Error",
        "CRRESP[2]": "PassDirty",
        "CRRESP[3]": "IsShared",
        "CRRESP[4]": "WasUnique",
    })
    f.setdefault("ACSNOOP_encoding",
        "Same encoding as ARSNOOP for the corresponding snoop type. "
        "Interconnect uses ACSNOOP to tell the cached master what kind "
        "of snoop action to take.")
    f.setdefault("valid_ready_handshake_rules_ace", [
        "All AXI + ACE channels use VALID/READY handshake.",
        "VALID must not depend combinationally on READY.",
        "AC channel: interconnect drives ACVALID/ACADDR/ACSNOOP/ACPROT; cached master drives ACREADY.",
        "CR channel: cached master drives CRVALID/CRRESP; interconnect drives CRREADY.",
        "CD channel: cached master drives CDVALID/CDDATA/CDLAST; interconnect drives CDREADY.",
        "Master must wait for ACVALID+ACREADY before CRVALID or CDVALID.",
    ])
    f.setdefault("ace_lite_subset_constraints", [
        "ACE-Lite master has no AC/CR/CD channels.",
        "ACE-Lite can issue ReadOnce/ReadNoSnoop and WriteUnique/WriteLineUnique/WriteNoSnoop only.",
        "ACE-Lite observes RRESP[3:2] but never asserts IsShared/PassDirty.",
        "Typical users: DMA / GPU / IO bridges.",
    ])
    d["fields"] = f
    _write(p, d)


# ============================================================
# L4 REGMAP — bus protocol, no register map
# ============================================================
def _l4(gd: Path) -> None:
    p = gd / "L4_REGMAP.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _f(d)
    _force_set(f, "register_map_present", False)
    f["rationale"] = (
        "ACE is a bus/interconnect protocol that extends AXI4 with "
        "coherency. There is no MMIO register map in this document. "
        "The AW/AR address channels carry an arbitrary slave address "
        "(AxADDR) chosen by system integrators, and the spec only "
        "defines the *signaling* and the (AxBAR, AxDOMAIN, AxSNOOP) "
        "field tuples that encode coherent operations.")
    f["notes"] = (
        "If a future system-integration L4 is required for an ACE-"
        "coherent SoC, the canonical 'address-side fields' to capture "
        "would be: AxADDR width (implementation-defined), AxDOMAIN "
        "(2 bits), AxSNOOP (4 bits for AR, 3 bits for AW), AxBAR "
        "(2 bits), AxCACHE (4 bits), AxPROT (3 bits), AxREGION (4 bits); "
        "plus snoop-channel: ACADDR (matches AxADDR width), ACSNOOP "
        "(4 bits), ACPROT (3 bits).")
    # v0.1.87 — override top-level notes (AHB+APB synth wrote AHB content).
    _force_top_if_present(d, "notes", f["notes"])
    _force_top_if_present(d, "rationale", f["rationale"])
    _force_top_if_present(d, "register_map_present", f["register_map_present"])
    d["fields"] = f
    _write(p, d)


# ============================================================
# L5 ADI — digital protocol, no analog signaling
# ============================================================
def _l5(gd: Path) -> None:
    p = gd / "L5_ADI_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _f(d)
    _force_set(f, "analog_digital_interface_present", False)
    f.setdefault("rationale",
        "AXI/ACE is a purely digital, synchronous on-chip bus protocol. "
        "There are no analog signals, no DC electrical specifications, "
        "no AC timing parameters, no IO standards.")
    f.setdefault("signaling_summary", {
        "clock":  "Single ACLK per ACE interface; rising-edge sampled.",
        "reset":  "Single active-LOW ARESETn. Async assert, sync deassert.",
        "io_count": "All AXI + ACE channels are unidirectional. "
                    "No tri-state, no open-drain, no analog.",
        "default_state_during_reset":
            "Master drives ARVALID/AWVALID/WVALID/CRVALID/CDVALID LOW; "
            "interconnect drives RVALID/BVALID/ACVALID LOW.",
        "combinatorial_path_rule":
            "No combinatorial paths between input and output signals. "
            "Applies equally to AC/CR/CD snoop channels.",
    })
    d["fields"] = f
    _write(p, d)


# ============================================================
# L6 CONTROL LOGIC — cache-line FSM + snoop FSM
# ============================================================
def _l6(gd: Path) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _f(d)
    f.setdefault("fsm_hints_inherited_from_axi", {
        "per_channel_states": [
            "IDLE      (VALID=0)",
            "VALID     (VALID=1, READY=0; data held stable)",
            "HANDSHAKE (VALID=1, READY=1 on rising ACLK -> transfer occurs)",
        ],
        "rule": "Source MUST NOT wait for READY before asserting VALID.",
    })
    f.setdefault("ace_cache_line_fsm_5_state", {
        "states": ["UC UniqueClean", "UD UniqueDirty",
                   "SC SharedClean", "SD SharedDirty", "I Invalid"],
        "rule_match_memory":
            "UC and SC have data matching main memory.",
        "rule_dirty":
            "UD and SD differ from memory; cache owns write-back.",
        "rule_unique":
            "UC and UD are uniquely held by this cache.",
        "rule_shared":
            "SC and SD may also be held by other caches.",
        "store_visibility":
            "Stores to UC/UD visible immediately. Stores to SC/SD "
            "require a CleanUnique/MakeUnique broadcast first.",
        "invalid_rule":
            "An Invalid line is not present in this cache.",
    })
    f.setdefault("ace_cache_line_transitions", {
        "ReadShared_into_empty": "I -> SC / SD / UC / UD per RRESP[3:2]",
        "ReadUnique_into_empty": "I -> UC (PassDirty=0) or UD (PassDirty=1)",
        "ReadClean_into_empty":  "I -> SC or UC (PassDirty must be 0)",
        "MakeUnique_before_store": "(any) -> UD",
        "MakeUnique_into_dirty_store": "(any state) -> UD",
        "CleanShared_local":     "UD -> SC (write back) / UC -> SC / SD -> SC",
        "CleanInvalid_local":
            "(UD/SD/UC/SC) -> I (with WriteBack if dirty)",
        "MakeInvalid_local":     "(any valid) -> I (no write back)",
        "Snoop_ReadShared_hit":  "UD -> SD (PassDirty=1, IsShared=1)",
        "Snoop_ReadUnique_hit":  "(any valid) -> I (PassDirty=1 if was dirty)",
    })
    f.setdefault("ace_per_transaction_master_fsm", [
        "Master drives AR* with ARDOMAIN/ARSNOOP/ARBAR; asserts ARVALID.",
        "Wait for ARREADY handshake.",
        "If coherent: interconnect snoops other caches in parallel.",
        "Interconnect drives R beats with RDATA + RRESP[3:0].",
        "Master asserts RREADY per beat; final beat has RLAST=1.",
        "Master pulses RACK one cycle after RLAST handshake.",
        "Install line in cache per (RRESP[3:2], ARSNOOP).",
    ])
    f.setdefault("ace_per_transaction_snoop_target_fsm", [
        "Interconnect drives ACVALID + ACADDR + ACSNOOP + ACPROT.",
        "Cached master asserts ACREADY (may default HIGH).",
        "Once ACVALID + ACREADY both HIGH, master begins snoop processing.",
        "Master determines cache hit/miss + transition per ACSNOOP.",
        "Master drives CRRESP[4:0] and asserts CRVALID.",
        "If DataTransfer=1: master drives CDDATA beats with CDLAST.",
        "Wait for CRREADY (and CDREADY per beat) handshakes.",
        "Apply state transition per Table C5-4.",
    ])
    f.setdefault("snoop_channel_dependency_rule",
        "Master must wait for both ACVALID and ACREADY to be asserted "
        "before asserting CRVALID. Master must also wait for both "
        "ACVALID and ACREADY before asserting CDVALID. CRVALID/CDVALID "
        "must not depend combinationally on CRREADY/CDREADY.")
    f.setdefault("rack_wack_fsm", {
        "RACK": "Single-cycle pulse one ACLK after RLAST+RVALID+RREADY.",
        "WACK": "Single-cycle pulse one ACLK after BVALID+BREADY.",
        "purpose":
            "Tell the interconnect that the response is committed "
            "so subsequent snoops can be safely ordered.",
    })
    f.setdefault("dvm_message_phases", [
        "Phase 1: initiator broadcasts DVMMessage via AC to all DVM nodes.",
        "Phase 2: each target invalidates the indicated entry and "
        "responds on CR.",
        "Phase 3: initiator issues DVMComplete; aggregated sync done.",
    ])
    f.setdefault("anti_deadlock_rule",
        "Inside the master, VALID for an outgoing AC/CR/CD channel must "
        "not be combinationally dependent on the READY of an incoming "
        "channel. Inside the interconnect, snoop dispatch must not wait "
        "for downstream snoop response combinationally.")
    f.setdefault("exit_from_reset",
        "Earliest VALID HIGH = rising ACLK after ARESETn=HIGH. "
        "Interconnect may drive ACVALID HIGH only once it has snoop "
        "work to do.")
    f.setdefault("default_ready_state_recommendation_ace", {
        "AWREADY": "Default HIGH recommended.",
        "ARREADY": "Default HIGH recommended.",
        "ACREADY": "Default HIGH recommended — accept snoops quickly.",
        "CRREADY": "Default HIGH recommended.",
        "CDREADY": "May default HIGH if interconnect can absorb data.",
        "WREADY":  "May default HIGH if slave can accept W in one cycle.",
        "BREADY":  "May default HIGH if master can accept B in one cycle.",
        "RREADY":  "May default HIGH if master can accept R immediately.",
    })
    d["fields"] = f
    _write(p, d)


# ============================================================
# L7 TEST/DEBUG
# ============================================================
def _l7(gd: Path) -> None:
    p = gd / "L7_TEST_DEBUG.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _f(d)
    _force_set(f, "test_debug_architecture_present", False)
    f.setdefault("rationale",
        "AXI/ACE does not define a JTAG/scan/BIST/MBIST/debug "
        "architecture. Debug visibility must be added by the "
        "integrator (typically via ARM CoreSight components).")
    f.setdefault("spec_provided_observability", [
        {"name": "AxUSER / RUSER / WUSER / BUSER (inherited from AXI4)",
         "purpose": "Implementation-defined; spec recommends avoiding "
                    "due to interop risk."},
        {"name": "CRRESP[1] Error",
         "purpose": "Cached master signals snoop failure."},
        {"name": "RRESP[3:0] full encoding",
         "purpose": "PassDirty + IsShared bits expose coherency state."},
        {"name": "Default-slave DECERR injection",
         "purpose": "Catches out-of-map accesses."},
        {"name": "Coherency monitor (architectural)",
         "purpose": "Implementation-defined point of serialization for "
                    "trace/debug."},
    ])
    f.setdefault("ace_optional_features_via_properties", [
        "Snoop_Filter — interconnect tracks shareability state.",
        "WriteEvict — optional AWSNOOP=0b101, requires AWUNIQUE.",
        "DVM support — DVMMessage / DVMComplete; optional per implementation.",
        "Snoop data bus width — 32/64/128/256/512/1024 bits.",
        "ACE-Lite — subset for non-cached masters.",
    ])
    f.setdefault("boundary_with_AXI5_E_features",
        "AXI5 (AMBA 5) E-series features (cache stashing, deallocating "
        "transactions, atomic transactions, MPAM, tagging) are NOT part "
        "of IHI 0022E — they belong to AXI5/ACE5 successor specs.")
    d["fields"] = f
    _write(p, d)


# ============================================================
# L8 RTL CONSTANTS — widths, encodings
# ============================================================
def _l8_rtl_constants(gd: Path) -> None:
    p = gd / "L8_RTL_CONSTANTS.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _f(d)
    # v0.1.87 — AXI burst encodings (gold for both 0022E and 0022H).
    f.setdefault("burst_size_encoding_AxSIZE_to_bytes", {
        "0b000": 1,    "0b001": 2,    "0b010": 4,    "0b011": 8,
        "0b100": 16,   "0b101": 32,   "0b110": 64,   "0b111": 128,
    })
    f.setdefault("burst_type_encoding_AxBURST", {
        "0b00": "FIXED",  "0b01": "INCR",
        "0b10": "WRAP",   "0b11": "Reserved",
    })
    wp = _ensure_dict(f, "width_parameters_axi_baseline_inherited")
    if isinstance(wp, dict):
        for k, v in {
            "DATA_WIDTH_bits": {"legal_values": [8, 16, 32, 64, 128, 256, 512, 1024]},
            "WSTRB_width_bits": {"formula": "DATA_WIDTH/8"},
            "ADDR_WIDTH_bits": {"value": "implementation-defined"},
            "ID_WIDTH_bits":   {"value": "implementation-defined"},
            "AxLEN_width": {"AXI3": "4 bits", "AXI4": "8 bits"},
            "AxSIZE_width": "3 bits",
            "AxBURST_width": "2 bits",
            "AxLOCK_width": {"AXI3": "2 bits", "AXI4": "1 bit"},
            "AxCACHE_width": "4 bits",
            "AxPROT_width": "3 bits",
            "AxQOS_width": "4 bits (AXI4+)",
            "AxREGION_width": "4 bits (AXI4+)",
            "RRESP_BRESP_baseline_width": "2 bits (AXI baseline)",
        }.items():
            wp.setdefault(k, v)
    wa = _ensure_dict(f, "width_parameters_ace_additions")
    if isinstance(wa, dict):
        for k, v in {
            "AxDOMAIN_width": {"value": 2,
                "applies_to": ["ARDOMAIN", "AWDOMAIN"],
                "encoding_ref": "Table C3-2"},
            "ARSNOOP_width": {"value": 4,
                "encoding_ref": "Table C3-7 (read snoop encodings)"},
            "AWSNOOP_width": {"value": 3,
                "encoding_ref": "Table C3-8 (write snoop encodings)"},
            "AxBAR_width":   {"value": 2,
                "applies_to": ["ARBAR", "AWBAR"],
                "encoding_ref": "Table C3-5"},
            "AWUNIQUE_width": {"value": 1, "optional": True,
                "applies_when": "WriteEvict supported"},
            "RRESP_extended_width": {"value": 4,
                "rationale": "Adds [2] PassDirty + [3] IsShared"},
            "BRESP_extended_width": {"value": 3,
                "rationale": "Adds [2] DataTransfer"},
            "ACSNOOP_width": {"value": 4,
                "rationale": "Same encodings as ARSNOOP coherent reads"},
            "ACPROT_width":  {"value": 3,
                "rationale":
                    "Snoop access protection attributes (mirrors AxPROT)"},
            "CRRESP_width":  {"value": 5,
                "rationale": "[0] DataTransfer, [1] Error, "
                             "[2] PassDirty, [3] IsShared, [4] WasUnique"},
            "CDDATA_width":  {"legal_values": [32, 64, 128, 256, 512, 1024],
                "note": "Snoop data bus may differ from RDATA/WDATA width"},
            "RACK_width":    {"value": 1,
                "purpose": "Single-cycle ack after RLAST"},
            "WACK_width":    {"value": 1,
                "purpose": "Single-cycle ack after BVALID handshake"},
        }.items():
            wa.setdefault(k, v)
    f.setdefault("axsnoop_encoding_ARSNOOP_4bit", {
        "0b0000": "ReadNoSnoop (Non-shareable/System) / ReadOnce (Shareable)",
        "0b0001": "ReadShared",
        "0b0010": "ReadClean",
        "0b0011": "ReadNotSharedDirty",
        "0b0111": "ReadUnique",
        "0b1000": "CleanShared",
        "0b1001": "CleanInvalid",
        "0b1011": "CleanUnique",
        "0b1100": "MakeUnique",
        "0b1101": "MakeInvalid",
        "0b1110": "DVMComplete",
        "0b1111": "DVMMessage",
    })
    f.setdefault("awsnoop_encoding_AWSNOOP_3bit", {
        "0b000": "WriteNoSnoop / WriteUnique / Barrier",
        "0b001": "WriteLineUnique",
        "0b010": "WriteClean",
        "0b011": "WriteBack",
        "0b100": "Evict",
        "0b101": "WriteEvict (requires AWUNIQUE)",
    })
    f.setdefault("AxDOMAIN_encoding_2bit", {
        "0b00": "Non-shareable",
        "0b01": "Inner Shareable",
        "0b10": "Outer Shareable",
        "0b11": "System",
    })
    f.setdefault("AxBAR_encoding_2bit", {
        "0b00": "Normal access (not a barrier)",
        "0b01": "Memory Barrier",
        "0b10": "Normal access (reserved)",
        "0b11": "Synchronization Barrier",
    })
    f.setdefault("RRESP_extended_meaning_4bit", {
        "0b0000": "OKAY  + IsShared=0, PassDirty=0 (UniqueClean)",
        "0b0100": "OKAY  + IsShared=0, PassDirty=1 (UniqueDirty pass)",
        "0b1000": "OKAY  + IsShared=1, PassDirty=0 (SharedClean)",
        "0b1100": "OKAY  + IsShared=1, PassDirty=1 (SharedDirty pass)",
        "0b0001": "EXOKAY",
        "0b0010": "SLVERR",
        "0b0011": "DECERR",
    })
    f.setdefault("BRESP_extended_meaning_3bit", {
        "0b000": "OKAY  + DataTransfer=0",
        "0b100": "OKAY  + DataTransfer=1",
        "0b001": "EXOKAY",
        "0b010": "SLVERR",
        "0b011": "DECERR",
    })
    f.setdefault("CRRESP_bit_meaning_5bit", {
        "CRRESP[0]": "DataTransfer",
        "CRRESP[1]": "Error",
        "CRRESP[2]": "PassDirty",
        "CRRESP[3]": "IsShared",
        "CRRESP[4]": "WasUnique",
    })
    f.setdefault("cache_line_state_codes_5state", {
        "UC": "UniqueClean", "UD": "UniqueDirty",
        "SC": "SharedClean", "SD": "SharedDirty",
        "I":  "Invalid",
    })
    f.setdefault("burst_length_formula_inherited", {
        "AXI3":     "Burst_Length = AxLEN[3:0] + 1",
        "AXI4_ACE": "Burst_Length = AxLEN[7:0] + 1",
    })
    f.setdefault("snoop_data_constraint",
        "All cache-line-size transactions on CD must use the full "
        "CDDATA bus width. Burst length on CD must be one of 1, 2, "
        "4, 8, or 16.")
    f.setdefault("key_constants_for_RTL_authoring_ace", {
        "cache_line_size_typical_bytes": [16, 32, 64, 128],
        "cache_line_size_implementation_defined": True,
        "AxDOMAIN_default_for_non_cached_master":
            "0b00 (Non-shareable) or 0b11 (System)",
        "AWUNIQUE_required_when":
            "WriteEvict (AWSNOOP=0b101) is implemented",
        "snoop_address_width_matches":
            "ACADDR width = master ARADDR width (cache-line-aligned)",
    })
    d["fields"] = f
    _write(p, d)


# ============================================================
# L8 TIMING WAVEFORM
# ============================================================
def _l8_timing_waveform(gd: Path) -> None:
    p = gd / "L8_TIMING_WAVEFORM.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _f(d)
    f.setdefault("clock_and_reset_waveform", {
        "ACLK":     "Single rising-edge clock per ACE interface.",
        "ARESETn":  "Active LOW. Async assert; sync deassert.",
    })
    f.setdefault("handshake_waveforms_inherited_axi", [
        {"case": "VALID before READY (Figure A3-2)",
         "sequence": "Source VALID at T1; READY at T2; Transfer at T3."},
        {"case": "READY before VALID (Figure A3-3)",
         "sequence": "READY at T1; VALID at T2; Transfer at T3."},
        {"case": "VALID with READY same cycle (Figure A3-4)",
         "sequence": "Both at T1; Transfer at T2."},
    ])
    f.setdefault("ace_snoop_channel_dependency_waveform", {
        "figure": "Figure C3-1 Snoop channel dependencies",
        "arrows": [
            "ACVALID -> ACREADY (single-headed)",
            "ACVALID + ACREADY -> CRVALID (double-headed)",
            "ACVALID + ACREADY -> CDVALID (double-headed)",
            "CRVALID -> CRREADY (single-headed)",
            "CDVALID -> CDREADY (single-headed)",
            "ACVALID must not depend on ACREADY",
            "CRVALID/CDVALID must not depend on CRREADY/CDREADY",
        ],
    })
    # v0.1.87 — short-form alias (gold key).
    f.setdefault("ace_snoop_dependency_diagram", {
        "figure": "Figure C3-1",
        "summary":
            "Interconnect drives ACVALID independent of ACREADY. Master may "
            "default ACREADY=HIGH or wait. Master must wait for both "
            "ACVALID + ACREADY before CRVALID and CDVALID. If DataTransfer=1, "
            "master delivers CD beats (CDDATA + CDLAST) gated by CDREADY.",
    })
    f.setdefault("ace_read_transaction_waveform_with_snoops", {
        "sequence": [
            "T0: Master drives AR* + ARDOMAIN/ARSNOOP/ARBAR; ARVALID.",
            "T1: ARREADY HIGH; AR handshake complete.",
            "T2+: Interconnect issues snoops on AC channel.",
            "T3+: Other masters drive ACREADY; deliver CRRESP/CD.",
            "T5+: Interconnect aggregates; drives R + RRESP[3:0].",
            "T9: Master asserts RREADY; RLAST=1 on final beat.",
            "T10: Master pulses RACK for one ACLK cycle.",
            "Install line per (RRESP[3:2], ARSNOOP).",
        ],
    })
    f.setdefault("ace_write_transaction_waveform_with_RACK_WACK", {
        "sequence": [
            "T0: Master drives AW* + AWDOMAIN/AWSNOOP/AWBAR; AWVALID.",
            "T0: Master may drive WDATA + WSTRB + WLAST.",
            "T1+: AW and W handshakes complete (any order).",
            "T5+: Slave drives BRESP[2:0] + BVALID.",
            "T6: Master asserts BREADY; B handshake complete.",
            "T7: Master pulses WACK for one ACLK cycle.",
        ],
    })
    f.setdefault("snoop_response_ordering_rule",
        "Each snoop transaction is fully ordered: response on CR must "
        "be in the same order as addresses on AC. Master may not "
        "reorder snoops issued by the interconnect.")
    f.setdefault("max_outstanding_rules_inherited", {
        "same_AxID_ordering":      "All transactions with the same AXI ID must remain in order.",
        "different_AxID_ordering": "No ordering constraint between different IDs.",
        "ACE_snoop_ordering":      "Snoop responses on CR follow AC address order.",
    })
    f.setdefault("ace_lite_no_snoop_channels",
        "ACE-Lite masters have no AC/CR/CD channels. They observe "
        "RRESP[3:2] / BRESP[2] but do not participate in snoop traffic.")
    d["fields"] = f
    _write(p, d)


# ============================================================
# L9 INTEGRATION SPEC
# ============================================================
def _l9(gd: Path) -> None:
    p = gd / "L9_INTEGRATION_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _f(d)
    f.setdefault("interconnect_topology_options_inherited_axi", [
        "Shared address and data buses",
        "Shared address buses and multiple data buses",
        "Multilayer, with multiple address and data buses",
    ])
    f.setdefault("ace_specific_integration_components", {
        "Point_of_Serialization_POS":
            "System-level cache controller or coherency manager; "
            "orders all coherent operations to a given address.",
        "Point_of_Coherency_PoC":
            "Location of master copy for Non-shareable addresses.",
        "Snoop_Filter":
            "Optional — tracks which masters cache which addresses; "
            "requires accurate Evict / WriteEvict notifications.",
        "ACE_Lite_master_ports":
            "Non-cached ports (DMA / GPU / IO) that issue coherent "
            "reads/writes without owning a snoop port.",
        "Coherency_Manager":
            "Aggregates snoop responses, manages PassDirty propagation, "
            "enforces 5-state invariants.",
    })
    f.setdefault("interconnect_role_in_ace", [
        "Decode (AxDOMAIN + AxSNOOP + AxBAR) -> snoop list.",
        "Issue AC snoops to targets.",
        "Collect CR + CD; aggregate snoop results.",
        "Combine snoop data + memory data; build RRESP[3:2] / BRESP[2].",
        "Wait for RACK / WACK before issuing dependent snoops.",
        "Honor barrier transactions.",
        "Distribute DVM messages.",
    ])
    f.setdefault("default_slave_behavior",
        "When the interconnect cannot decode a slave access, it must "
        "return DECERR.")
    f.setdefault("slave_classification", {
        "Memory_slave":     "Must handle all transaction types correctly.",
        "Peripheral_slave": "Implementation-defined access method.",
        "Snoopable_master": "Cached master with AC/CR/CD channels.",
        "Non_snoopable_master_ACE_Lite":
            "Coherent master without AC/CR/CD channels.",
    })
    f.setdefault("interface_categories", [
        "Full ACE master (AR/R/AW/W/B + AC/CR/CD + RACK/WACK + "
        "AxDOMAIN/AxSNOOP/AxBAR + extended RRESP/BRESP)",
        "ACE-Lite master (no AC/CR/CD)",
        "AXI4 master (treated as ACE-Lite at AxDOMAIN=Non-shareable)",
        "Read-only / Write-only interfaces inherited from AXI",
    ])
    f.setdefault("ace_property_declarations", {
        "Cache_Coherent":             "True if the master maintains a snoop-able cache that can respond to AC snoops on CR/CD.",
        "Supports_DVM":               "True if the master can process DVM messages (TLB invalidate / BP invalidate / IC invalidate / VA sync).",
        "WriteEvict_supported":       "True if the master emits WriteEvict transactions (requires AWUNIQUE).",
        "Snoop_Filter_aware":         "Interconnect property — interconnect tracks shareable allocations and uses Evict to maintain.",
        "Snoop_Data_Bus_Width_bits":  "Configurable 32/64/128/256/512/1024 (may differ from RDATA width).",
        "ReadNotSharedDirty_support": "Master may decline SharedDirty by choosing ReadNotSharedDirty.",
    })
    # v0.1.87 — issue-specific phrasing.
    if _ACE_ISSUE == "E":
        f.setdefault("register_slice_insertion_rule",
            "Register slices may be inserted in any AXI channel and in any "
            "ACE snoop channel at the cost of an additional cycle of "
            "latency. ACE snoop channels may use the same register-slice "
            "insertion rules as the AXI channels.")
    else:
        f.setdefault("register_slice_insertion_rule",
            "A register slice can be inserted at almost any point in any "
            "channel, at the cost of an additional cycle of latency. Each "
            "channel transfers information in only one direction, so a "
            "register slice is just a flop set on that channel; the "
            "architecture does not require a fixed relationship between "
            "channels.")
    f.setdefault("compatibility_with_AXI4_only_masters",
        "AXI4 master on ACE interconnect: treated as ACE-Lite at "
        "AxDOMAIN=Non-shareable (no snooping). ACE master on AXI4 "
        "interconnect: snoop port tied off; Non-shareable only.")
    # v0.1.87 — ABSENT_IN_PROGRAM gold from agent: add interconnect handling
    f.setdefault("interconnect_id_handling_inherited", {
        "id_widening":
            "AXI baseline: interconnect appends bits to ARID/AWID for routing.",
        "id_routing":
            "Inherited from AXI baseline; ACE adds RACK/WACK to confirm "
            "response delivery so the interconnect can drain outstanding "
            "snoops safely.",
        "ace_snoop_id":
            "Snoop traffic on AC/CR/CD is not tagged with AXI IDs; targeting "
            "is per-master-port.",
    })
    f.setdefault("interconnect_ordering_requirements_ace", [
        "All transactions with a given AXI ID must remain in order "
        "(inherited from AXI).",
        "Snoop responses on CR for a given master must be in the same "
        "order as the AC requests that elicited them.",
        "RACK/WACK must be observed by the interconnect before issuing a "
        "dependent snoop or write-back to the same address.",
        "Barrier transactions block reordering within the named domain.",
        "DVMComplete must be returned only after all targeted masters "
        "have acknowledged the corresponding DVMMessage.",
    ])
    # v0.1.87 — force top-level for all L9 substantive keys (R50 / AHB+APB
    # universal extractors may have written garbage spec-text at top-level).
    _force_top_if_present(d, "interface_categories", f["interface_categories"])
    _force_top_if_present(d, "ace_property_declarations",
                          f["ace_property_declarations"])
    _force_top_if_present(d, "register_slice_insertion_rule",
                          f["register_slice_insertion_rule"])
    _force_top_if_present(d, "interconnect_id_handling_inherited",
                          f["interconnect_id_handling_inherited"])
    _force_top_if_present(d, "interconnect_ordering_requirements_ace",
                          f["interconnect_ordering_requirements_ace"])
    _force_top_if_present(d, "compatibility_with_AXI4_only_masters",
                          f["compatibility_with_AXI4_only_masters"])
    _force_top_if_present(d, "interconnect_role_in_ace",
                          f["interconnect_role_in_ace"])
    _force_top_if_present(d, "default_slave_behavior",
                          f["default_slave_behavior"])
    _force_top_if_present(d, "slave_classification",
                          f["slave_classification"])
    _force_top_if_present(d, "ace_specific_integration_components",
                          f["ace_specific_integration_components"])
    _force_top_if_present(d, "interconnect_topology_options_inherited_axi",
                          f["interconnect_topology_options_inherited_axi"])
    d["fields"] = f
    _write(p, d)


# ============================================================
# L10 TEST CASES
# ============================================================
def _l10(gd: Path) -> None:
    p = gd / "L10_TEST_CASES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _f(d)
    # v0.1.87 — FORCE overwrite (R50/AHB+APB synth may have written
    # AHB-baseline test_cases_present text). Agent gold uses em-dash.
    _force_set(f, "test_cases_present",
        "partial — derived from protocol requirements; spec does not "
        "provide a formal test plan.")
    if _empty(f.get("derived_compliance_test_categories_ace")):
        f["derived_compliance_test_categories_ace"] = [
            {"id": "TC-ACE-DOMAIN", "name": "Shareability domain enforcement"},
            {"id": "TC-ACE-SNOOP-ENCODE", "name": "AxSNOOP encoding legality"},
            {"id": "TC-ACE-BAR", "name": "Barrier transaction"},
            {"id": "TC-ACE-DVM", "name": "DVM message + complete handshake"},
            {"id": "TC-ACE-CACHE-STATES", "name": "5-state cache line transitions"},
            {"id": "TC-ACE-SNOOP-CHANNEL", "name": "AC/CR/CD channel handshake"},
            {"id": "TC-ACE-PASSDIRTY", "name": "PassDirty/DataTransfer/IsShared rules"},
            {"id": "TC-ACE-RACK-WACK", "name": "RACK/WACK acknowledge timing"},
            {"id": "TC-ACE-LITE", "name": "ACE-Lite subset behavior"},
            {"id": "TC-ACE-EVICT", "name": "Evict / WriteEvict snoop-filter notification"},
            {"id": "TC-ACE-WRITEBACK", "name": "WriteBack / WriteClean correctness"},
            {"id": "TC-ACE-SNOOP-DATA-WIDTH", "name": "Snoop data bus narrow / wide"},
            {"id": "TC-ACE-SNOOP-DEADLOCK", "name": "Snoop channel anti-deadlock"},
        ]
    # v0.1.87 — derived_compliance_test_categories_axi_baseline (gold).
    if _empty(f.get("derived_compliance_test_categories_axi_baseline")):
        f["derived_compliance_test_categories_axi_baseline"] = [
            {"id": "TC-RESET", "name": "Reset behavior",
             "scenarios": [
                 "ARESETn asserted async; VALIDs LOW.",
                 "Earliest VALID HIGH at rising ACLK after ARESETn=HIGH.",
             ]},
            {"id": "TC-HANDSHAKE", "name": "VALID/READY compliance",
             "scenarios": [
                 "VALID before READY",
                 "READY before VALID",
                 "Same-cycle assertion",
             ]},
            {"id": "TC-4KB-BOUND", "name": "4KB boundary enforcement",
             "scenarios": [
                 "INCR burst crossing 4KB must be rejected/split",
             ]},
            {"id": "TC-WLAST-RLAST", "name": "WLAST/RLAST correctness",
             "scenarios": [
                 "Asserted only on the final beat of a burst",
                 "RLAST per RID-stream burst",
             ]},
            {"id": "TC-ORDERING-SAME-ID",
             "name": "Same-ID transaction ordering",
             "scenarios": [
                 "Two reads with the same ARID must complete in order",
                 "Two writes with the same AWID must complete in order",
             ]},
            {"id": "TC-EXCLUSIVE",
             "name": "Exclusive access (AXI3/AXI4)",
             "scenarios": [
                 "Load-locked / store-conditional pairing",
                 "EXOKAY vs OKAY on success / failure",
             ]},
            {"id": "TC-RESP-CODES",
             "name": "Response code coverage",
             "scenarios": [
                 "OKAY, EXOKAY, SLVERR, DECERR",
             ]},
        ]
    # v0.1.87 — force top-level overrides where AHB+APB synth wrote.
    _force_top_if_present(d, "test_cases_present", f["test_cases_present"])
    d["fields"] = f
    _write(p, d)


# ============================================================
# L11 OTP
# ============================================================
def _l11(gd: Path) -> None:
    p = gd / "L11_OTP_CONTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _f(d)
    d["fields"] = f
    d.setdefault("rationale",
        "ACE is a bus/interconnect protocol; no OTP/fuse content.")
    if "evidence" not in d:
        d["evidence"] = []
    _write(p, d)


# ============================================================
# L12 BEHAVIORAL SEQUENCES
# ============================================================
def _l12(gd: Path) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _f(d)
    f.setdefault("ace_coherent_read_sequence_ReadShared", [
        "Cache miss; M0 issues ReadShared (ARDOMAIN=InnerShareable, ARSNOOP=0b0001).",
        "Interconnect broadcasts AC snoops to Inner-shareable masters.",
        "Each snooped master returns CRRESP; dirty data on CD if hit.",
        "Interconnect aggregates; returns R with RRESP[3:2].",
        "M0 installs as SC/SD/UC/UD per RRESP; pulses RACK.",
    ])
    f.setdefault("ace_coherent_read_sequence_ReadUnique", [
        "M0 wants exclusive copy; issues ReadUnique (ARSNOOP=0b0111).",
        "Interconnect snoops others with ACSNOOP=ReadUnique.",
        "Each invalidates; returns CRRESP IsShared=0; if dirty, "
        "PassDirty=1+DataTransfer=1 with data on CD.",
        "R returns line; M0 installs as UC or UD; pulses RACK.",
    ])
    f.setdefault("ace_make_unique_sequence_full_line_overwrite", [
        "M0 will overwrite full line; issues MakeUnique (ARSNOOP=0b1100).",
        "Interconnect snoops others with ACSNOOP=MakeUnique; invalidate.",
        "R returns single beat (data ignored); M0 pulses RACK.",
        "M0 issues WriteBack with new data.",
    ])
    f.setdefault("ace_clean_invalid_software_flush_sequence", [
        "M0 issues CleanInvalid (ARSNOOP=0b1001).",
        "Snooped dirty caches return PassDirty=1+DataTransfer=1.",
        "Memory updated; all caches transition to I.",
        "R returns single beat; M0 pulses RACK.",
    ])
    f.setdefault("ace_writeback_eviction_sequence", [
        "M0 evicts UD/SD line; issues WriteBack (AWSNOOP=0b011).",
        "Sends dirty data on W; slave returns B OKAY.",
        "M0 pulses WACK; line removed from cache.",
    ])
    f.setdefault("ace_dvm_tlb_invalidate_sequence", [
        "TLB invalidate -> DVMMessage (ARSNOOP=0b1111).",
        "Interconnect distributes on AC to DVM nodes.",
        "Each node invalidates and responds on CR.",
        "After all responses, DVMComplete (ARSNOOP=0b1110).",
    ])
    f.setdefault("ace_barrier_sequence_synchronization", [
        "DSB SY -> Barrier on AR/AW with AxBAR=0b11.",
        "Interconnect blocks reordering across barrier within domain.",
        "B or R returned; master pulses WACK / RACK.",
    ])
    f.setdefault("ace_lite_coherent_write_sequence_WriteLineUnique", [
        "ACE-Lite master issues WriteLineUnique (AWSNOOP=0b001).",
        "Interconnect snoops with MakeUnique-equivalent; invalidate.",
        "Master pushes W data; B returned; WACK pulsed.",
    ])
    f.setdefault("ordering_rules_summary_ace", {
        "same_master_same_ID": "Strictly ordered (inherited from AXI).",
        "snoop_ordering":
            "Each snoop transaction is fully ordered: response on CR must "
            "follow the order of addresses on AC.",
        "RACK_WACK_gating":    "Interconnect must observe RACK/WACK.",
        "barriers":            "Barriers enforce ordering within domain.",
    })
    # v0.1.87 — typical AXI sequences (gold) — inherited baseline.
    f.setdefault("typical_axi_read_sequence_inherited", [
        "1. Master drives AR* fields including ARDOMAIN/ARSNOOP/ARBAR; "
        "asserts ARVALID.",
        "2. Slave (or interconnect) asserts ARREADY; AR handshake completes.",
        "3. Slave drives R channel beats with RID, RDATA, RRESP[3:0] "
        "(RRESP[3:2] = IsShared/PassDirty), RLAST.",
        "4. Master asserts RREADY per beat; final beat RLAST=1.",
        "5. Master pulses RACK one cycle after the final beat's handshake.",
    ])
    f.setdefault("typical_axi_write_sequence_inherited", [
        "1. Master drives AW* fields including AWDOMAIN/AWSNOOP/AWBAR; "
        "asserts AWVALID.",
        "2. Master drives W beats with WDATA/WSTRB/WLAST; asserts WVALID.",
        "3. AW and W handshakes complete (any order).",
        "4. Slave drives BRESP[2:0] (with BRESP[2]=DataTransfer for "
        "pass-dirty cases) + BVALID.",
        "5. Master pulses WACK one cycle after the B handshake.",
    ])
    # v0.1.87 — AXI4 baseline behavioral sequences (gold for arm_aix 0022H
    # which does not have ACE-specific snoop sequences mixed in).
    f.setdefault("typical_read_sequence_AXI4", [
        "1. Master drives ARID, ARADDR, ARLEN, ARSIZE, ARBURST, ARLOCK, "
        "ARCACHE, ARPROT, ARQOS, ARREGION; asserts ARVALID.",
        "2. Slave eventually asserts ARREADY; AR handshake completes at "
        "rising ACLK.",
        "3. Slave drives first beat on RDATA with RID=ARID, RRESP, "
        "RLAST=0 (or 1 if length=1); asserts RVALID.",
        "4. Master asserts RREADY; beat handshake completes.",
        "5. Repeat for each beat with incrementing/wrapping/fixed address "
        "per AxBURST.",
        "6. Slave asserts RLAST=1 on the final beat.",
        "7. Final beat handshake completes the transaction.",
    ])
    f.setdefault("typical_write_sequence_AXI4", [
        "1. Master drives AWID, AWADDR, AWLEN, AWSIZE, AWBURST, AWLOCK, "
        "AWCACHE, AWPROT, AWQOS, AWREGION; asserts AWVALID.",
        "2. Master may concurrently drive WDATA[0], WSTRB, WLAST=0 (or 1 "
        "if single beat); asserts WVALID.",
        "3. AW and W handshakes complete (in any order; W data can lead, "
        "lag, or be concurrent with AW).",
        "4. Master drives subsequent W beats with WLAST=1 on the final "
        "beat.",
        "5. After AWVALID+AWREADY+WVALID+WREADY+WLAST all observed by "
        "slave, slave asserts BVALID with BID=AWID and BRESP.",
        "6. Master asserts BREADY; B handshake completes.",
    ])
    f.setdefault("exclusive_read_modify_write_sequence", [
        "1. Master issues exclusive read: ARLOCK = Exclusive at address X "
        "with ARID=I.",
        "2. Slave records (X, I) in its exclusive monitor; returns EXOKAY.",
        "3. Master later issues exclusive write at X with AWID=I and "
        "AWLOCK=Exclusive.",
        "4. Slave checks monitor: if (X,I) still valid (no intervening "
        "write to X) -> updates memory, returns EXOKAY.",
        "5. If another master wrote X in between -> slave returns OKAY, "
        "write is NOT applied.",
        "6. Master that gets OKAY (instead of EXOKAY) must retry the "
        "exclusive sequence.",
    ])
    f.setdefault("locked_access_sequence_AXI3_only", [
        "1. Master ensures no other outstanding transactions before "
        "starting.",
        "2. Master issues transactions with AxLOCK=Locked (0b10) and same "
        "AxID.",
        "3. Interconnect arbiter blocks all other masters until master "
        "issues a final unlocking transaction (AxLOCK != Locked).",
        "4. Master must complete locked sequence before any further "
        "transactions.",
        "Note: AXI4 removes locked-access support; AXI4 only supports "
        "Normal and Exclusive.",
    ])
    f.setdefault("early_response_rules", {
        "early_read_response":
            "Intermediate can respond with locally-cached read data if "
            "up-to-date wrt all earlier writes to same/overlapping "
            "address. Must observe ID ordering.",
        "early_write_response":
            "Intermediate can send early B-response for Bufferable writes "
            "with no downstream observers. Must propagate downstream "
            "before discarding data; subsequent same-or-overlapping "
            "transactions are ordered after the early-responded write.",
    })
    f.setdefault("narrow_transfer_sequence",
        "When transfer width is narrower than data bus, the address+size "
        "determine which byte lanes are used. INCR/WRAP: different lanes "
        "per beat. FIXED: same lanes per beat.")
    f.setdefault("byte_invariance_sequence",
        "Big-endian and little-endian elements can coexist in one memory; "
        "any byte transfer to address X always passes on the same data "
        "bus wires regardless of element endianness.")
    # v0.1.87 — also add ordering_rules_summary (AXI baseline keys).
    _orsm = f.setdefault("ordering_rules_summary", {})
    if not isinstance(_orsm, dict):
        _orsm = {}
        f["ordering_rules_summary"] = _orsm
    _orsm.setdefault("same_master_same_ID_same_location",
        "Strictly ordered (W1 before W2; W1 before R2; R1 before W2).")
    _orsm.setdefault("same_master_different_IDs",
        "No ordering guarantee from spec.")
    _orsm.setdefault("different_masters",
        "No ordering guarantee from spec.")
    _orsm.setdefault("different_memory_locations",
        "No ordering guarantee unless made coherent via barriers/CMOs "
        "in ACE.")
    _orsm.setdefault("device_transactions_AXI4_same_ID_same_slave",
        "Must be ordered with respect to each other (AXI4 addition over "
        "AXI3).")
    d["fields"] = f
    _write(p, d)


# ============================================================
# L13 LAB CALIBRATION
# ============================================================
def _l13(gd: Path) -> None:
    p = gd / "L13_LAB_CALIBRATION.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _f(d)
    d["fields"] = f
    d.setdefault("rationale",
        "AXI/ACE is a digital bus protocol; no analog calibration.")
    if "evidence" not in d:
        d["evidence"] = []
    _write(p, d)


# ============================================================
# L14 PROTOCOL VERSIONING
# ============================================================
def _l14(gd: Path) -> None:
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _f(d)
    d.setdefault("doc_name", "L14_PROTOCOL_VERSIONING")
    d.setdefault("applicability", "APPLICABLE")
    d.setdefault("ic_class", "bus_interconnect_protocol")
    # Force-override version table so AXI-only synth values get the ACE
    # 2013-02-22 Issue-E narrative.
    _force_set(f, "versions", [
        {"release_date": "16 June 2003",     "issue": "A",   "change": "First release"},
        {"release_date": "19 March 2004",    "issue": "B",   "change": "First release of AXI specification v1.0"},
        {"release_date": "03 March 2010",    "issue": "C",   "change": "First release of AXI specification v2.0"},
        {"release_date": "03 June 2011",     "issue": "D-2c","change": "Public beta draft — first ACE description"},
        {"release_date": "28 October 2011",  "issue": "D",   "change": "First release of AMBA AXI and ACE Protocol Specification"},
        {"release_date": "22 February 2013", "issue": "E",   "change": "Second release of AMBA AXI and ACE Protocol Specification"},
    ])
    f.setdefault("ace_lifecycle", {
        "introduced_in_issue": "D (2011-10-28 baseline, 2011-06-03 beta D-2c)",
        "current_issue_in_this_doc": "E (2013-02-22)",
        "subsequent_releases_outside_this_doc":
            "Issues F (2017) and onwards added AXI5/ACE5 variants in "
            "IHI 0022F/G/H (not covered by IHI 0022E).",
    })
    f.setdefault("deprecated_features", [
        {"feature": "WID", "deprecated_in_version": "AXI4 / ACE",
         "rationale": "AXI4 enforces single-master-ordered write data on W."},
        {"feature": "AxLOCK=0b10 Locked access",
         "deprecated_in_version": "AXI4 / ACE",
         "rationale": "Locked transactions complicate interconnect QoS."},
    ])
    f.setdefault("ace_added_signals_vs_AXI4", [
        "AR channel: ARDOMAIN[1:0], ARSNOOP[3:0], ARBAR[1:0]",
        "AW channel: AWDOMAIN[1:0], AWSNOOP[2:0], AWBAR[1:0], AWUNIQUE",
        "R  channel: RRESP extended from [1:0] to [3:0]",
        "B  channel: BRESP extended from [1:0] to [2:0]",
        "Acknowledge: RACK, WACK",
        "Snoop address channel AC",
        "Snoop response channel CR",
        "Snoop data channel CD",
    ])
    f.setdefault("backward_compat_considerations", [
        {"trap_name": "RRESP_width_extension",
         "axi4": "RRESP[1:0] only",
         "ace":  "RRESP[3:0] adds PassDirty + IsShared"},
        {"trap_name": "BRESP_width_extension",
         "axi4": "BRESP[1:0] only",
         "ace":  "BRESP[2:0] adds DataTransfer"},
        {"trap_name": "AxDOMAIN_AxSNOOP_AxBAR_new",
         "axi4": "Not present",
         "ace":  "Required on AR/AW; AXI4-only masters tie to Non-shareable / 0."},
        {"trap_name": "AC_CR_CD_snoop_channels_new",
         "axi4": "Not present",
         "ace_full": "Required for cached masters; ACE-Lite omits.",
         "axi4_master_on_ace_interconnect": "Snoop port tied off."},
        {"trap_name": "RACK_WACK_new",
         "axi4": "Not present",
         "ace":  "Required; single-cycle pulse after R/B handshake."},
    ])
    f.setdefault("interoperability_matrix", [
        {"master": "AXI4",       "interconnect": "ACE",       "compatible": True,
         "notes": "Master treated as ACE-Lite at AxDOMAIN=Non-shareable."},
        {"master": "ACE-Lite",   "interconnect": "ACE",       "compatible": True,
         "notes": "Coherent reads/writes without snoop port."},
        {"master": "ACE (full)", "interconnect": "ACE",       "compatible": True,
         "notes": "Full coherency."},
        {"master": "ACE (full)", "interconnect": "AXI4-only", "compatible": False,
         "notes": "No snoop infrastructure; cannot maintain coherency."},
    ])
    # v0.1.87 — backward_compat_traps + version_naming_history_note (gold).
    f.setdefault("backward_compat_traps", [
        {"trap_name": "AxLEN_width_change",
         "axi3": "AxLEN[3:0] — Burst_Length = AxLEN[3:0] + 1; burst length "
                 "1-16 transfers for all burst types",
         "axi4": "AxLEN[7:0] — Burst_Length = AxLEN[7:0] + 1; INCR up to "
                 "256 transfers, FIXED/WRAP still 1-16"},
        {"trap_name": "AxLOCK_width_change",
         "axi3": "AxLOCK[1:0] — 0b00 Normal, 0b01 Exclusive, 0b10 Locked, "
                 "0b11 Reserved",
         "axi4": "AxLOCK[0] — 0b0 Normal, 0b1 Exclusive (Locked support "
                 "removed)"},
        {"trap_name": "Write_data_ID_WID",
         "axi3": "WID signal present on W channel; tags each write data "
                 "beat with its AWID",
         "axi4": "WID removed; write data on W channel is strictly in "
                 "address-order, write data interleaving prohibited"},
        {"trap_name": "AxQOS_AxREGION_added",
         "axi3": "Not present",
         "axi4": "ARQOS/AWQOS (4 bits, QoS hint) + ARREGION/AWREGION "
                 "(4 bits, region identifier) added"},
    ])
    f.setdefault("version_naming_history_note",
        "AXI specification versions v1.0 and v2.0 (used in Issues B and C) "
        "have been discontinued to avoid confusion with AXI3 / AXI4. "
        "Issue E.a was originally published as Issue E.")
    d["fields"] = f
    _write(p, d)


# ============================================================
# L15 ENCODING TABLES
# ============================================================
def _l15(gd: Path) -> None:
    p = gd / "L15_ENCODING_TABLES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _f(d)
    d.setdefault("doc_name", "L15_ENCODING_TABLES")
    d.setdefault("applicability", "APPLICABLE")
    d.setdefault("ic_class", "bus_interconnect_protocol")
    # Force-overwrite tables — arm_aix-class synth would have written
    # a bare-AXI encoding table set; the ACE-extended tables must win.
    _force_set(f, "tables", [
        {"table_id": "Table C3-2",
         "name": "AxDOMAIN encoding (shareability domain)",
         "field_bits": "AxDOMAIN[1:0]",
         "encoding": [
            {"value": "2'b00", "name": "Non-shareable",   "semantics": "Single master domain."},
            {"value": "2'b01", "name": "Inner Shareable", "semantics": "Inner domain."},
            {"value": "2'b10", "name": "Outer Shareable", "semantics": "Outer domain (superset of Inner)."},
            {"value": "2'b11", "name": "System",          "semantics": "All masters; not cacheable."},
         ]},
        {"table_id": "Table C3-5",
         "name": "AxBAR encoding (barrier transactions)",
         "field_bits": "AxBAR[1:0]",
         "encoding": [
            {"value": "2'b00", "name": "Normal access",            "semantics": "Not a barrier."},
            {"value": "2'b01", "name": "Memory Barrier",           "semantics": "Orders memory observation."},
            {"value": "2'b10", "name": "Normal access (reserved)", "semantics": "Treated as normal access."},
            {"value": "2'b11", "name": "Synchronization Barrier",  "semantics": "Orders observation AND execution."},
         ]},
        {"table_id": "Table C3-7",
         "name": "ARSNOOP — coherent read encodings",
         "field_bits": "ARSNOOP[3:0]",
         "encoding": [
            {"value": "4'b0000", "name": "ReadNoSnoop / ReadOnce", "semantics": "Per ARDOMAIN."},
            {"value": "4'b0001", "name": "ReadShared",             "semantics": "Coherent shared read."},
            {"value": "4'b0010", "name": "ReadClean",              "semantics": "Coherent clean read."},
            {"value": "4'b0011", "name": "ReadNotSharedDirty",     "semantics": "No SharedDirty allowed."},
            {"value": "4'b0111", "name": "ReadUnique",             "semantics": "Exclusive copy."},
            {"value": "4'b1011", "name": "CleanUnique",            "semantics": "Clean local + invalidate others."},
            {"value": "4'b1100", "name": "MakeUnique",             "semantics": "Invalidate others without data."},
            {"value": "4'b1000", "name": "CleanShared",            "semantics": "Cache maintenance."},
            {"value": "4'b1001", "name": "CleanInvalid",           "semantics": "Cache maintenance + invalidate."},
            {"value": "4'b1101", "name": "MakeInvalid",            "semantics": "Invalidate without WB."},
            {"value": "4'b1110", "name": "DVMComplete",            "semantics": "DVM completion."},
            {"value": "4'b1111", "name": "DVMMessage",             "semantics": "DVM operation."},
         ]},
        {"table_id": "Table C3-8",
         "name": "AWSNOOP — coherent write encodings",
         "field_bits": "AWSNOOP[2:0]",
         "encoding": [
            {"value": "3'b000", "name": "WriteNoSnoop / WriteUnique / Barrier", "semantics": "Per AWBAR[0] + AWDOMAIN."},
            {"value": "3'b001", "name": "WriteLineUnique",                       "semantics": "Full-line coherent write."},
            {"value": "3'b010", "name": "WriteClean",                            "semantics": "Write back + retain Clean."},
            {"value": "3'b011", "name": "WriteBack",                             "semantics": "Write back + invalidate locally."},
            {"value": "3'b100", "name": "Evict",                                 "semantics": "Notify removal of shareable line."},
            {"value": "3'b101", "name": "WriteEvict",                            "semantics": "Optional, requires AWUNIQUE."},
         ]},
        {"table_id": "RRESP[3:0] (extended)",
         "name": "RRESP[3:0] with IsShared + PassDirty",
         "field_bits": "RRESP[3:0]",
         "encoding": [
            {"value": "[1:0]=00 / [3:2]=00", "name": "OKAY UniqueClean",  "semantics": "Line Unique Clean."},
            {"value": "[1:0]=00 / [3:2]=01", "name": "OKAY UniqueDirty",  "semantics": "Line Unique with PassDirty."},
            {"value": "[1:0]=00 / [3:2]=10", "name": "OKAY SharedClean",  "semantics": "Line Shared Clean."},
            {"value": "[1:0]=00 / [3:2]=11", "name": "OKAY SharedDirty",  "semantics": "Line Shared with PassDirty."},
            {"value": "[1:0]=01",            "name": "EXOKAY",            "semantics": "Exclusive success (restricted)."},
            {"value": "[1:0]=10",            "name": "SLVERR",            "semantics": "Slave error."},
            {"value": "[1:0]=11",            "name": "DECERR",            "semantics": "Decode error."},
         ]},
        {"table_id": "BRESP[2:0] (extended)",
         "name": "BRESP[2:0] with DataTransfer",
         "field_bits": "BRESP[2:0]",
         "encoding": [
            {"value": "[1:0]=00 / [2]=0", "name": "OKAY no data",      "semantics": "Standard OKAY."},
            {"value": "[1:0]=00 / [2]=1", "name": "OKAY DataTransfer", "semantics": "WriteUnique pass-dirty completion."},
            {"value": "[1:0]=01",         "name": "EXOKAY",            "semantics": "Exclusive success."},
            {"value": "[1:0]=10",         "name": "SLVERR",            "semantics": "Slave error."},
            {"value": "[1:0]=11",         "name": "DECERR",            "semantics": "Decode error."},
         ]},
        {"table_id": "Table C3-22",
         "name": "CRRESP[4:0] — snoop response",
         "field_bits": "CRRESP[4:0]",
         "encoding": [
            {"value": "CRRESP[0]", "name": "DataTransfer", "semantics": "Data on CD will follow."},
            {"value": "CRRESP[1]", "name": "Error",        "semantics": "Snoop failed."},
            {"value": "CRRESP[2]", "name": "PassDirty",    "semantics": "Dirty responsibility transferred."},
            {"value": "CRRESP[3]", "name": "IsShared",     "semantics": "Snooped cache retains copy."},
            {"value": "CRRESP[4]", "name": "WasUnique",    "semantics": "Cache line was Unique."},
         ]},
        {"table_id": "Table C5-4 (cache-line states)",
         "name": "5-state cache-line model",
         "field_bits": "state codes",
         "encoding": [
            {"value": "UC", "name": "UniqueClean", "semantics": "Only this cache; matches memory."},
            {"value": "UD", "name": "UniqueDirty", "semantics": "Only this cache; differs from memory."},
            {"value": "SC", "name": "SharedClean", "semantics": "Other caches may have copy; matches memory."},
            {"value": "SD", "name": "SharedDirty", "semantics": "Other caches may have copy; differs from memory."},
            {"value": "I",  "name": "Invalid",     "semantics": "Not held."},
         ]},
        {"table_id": "Snoop channel signals",
         "name": "AC / CR / CD signal sets",
         "field_bits": "snoop channel signals",
         "encoding": [
            {"value": "AC channel", "name": "ACVALID, ACREADY, ACADDR, ACSNOOP[3:0], ACPROT[2:0]", "semantics": "Snoop address."},
            {"value": "CR channel", "name": "CRVALID, CRREADY, CRRESP[4:0]",                       "semantics": "Snoop response."},
            {"value": "CD channel", "name": "CDVALID, CDREADY, CDDATA, CDLAST",                    "semantics": "Snoop data."},
         ]},
        {"table_id": "Illegal-response constraints",
         "name": "Illegal CRRESP / RRESP combinations",
         "field_bits": "constraint",
         "encoding": [
            {"value": "PassDirty=1 + DataTransfer=0", "name": "Illegal", "semantics": "Must transfer data."},
            {"value": "IsShared=1 for ReadUnique",    "name": "Illegal", "semantics": "ReadUnique requires exclusive."},
            {"value": "IsShared=1 for CleanInvalid",  "name": "Illegal", "semantics": "CleanInvalid invalidates all."},
            {"value": "IsShared=1 for MakeInvalid",   "name": "Illegal", "semantics": "MakeInvalid invalidates all."},
         ]},
    ])
    f.setdefault("axi_baseline_inherited_tables", [
        "Table A3-2 Burst size encoding",
        "Table A3-3 Burst type encoding",
        "Table A3-5 RRESP/BRESP baseline",
        "Table A4-6 AxPROT",
        "Table A5-1 Channel ID assignment",
    ])
    f.setdefault("burst_address_equations_inherited", {
        "Start_Address":   "AxADDR",
        "Number_Bytes":    "2 ^ AxSIZE",
        "Burst_Length":    "AxLEN + 1",
        "Aligned_Address": "INT(Start_Address / Number_Bytes) * Number_Bytes",
        # v0.1.87 — gold sibling extras.
        "Address_1":       "Start_Address (first transfer)",
        "Address_N_INCR":  "Aligned_Address + (N - 1) * Number_Bytes",
        "Wrap_Boundary":
            "INT(Start_Address / (Number_Bytes * Burst_Length)) * "
            "(Number_Bytes * Burst_Length)",
    })
    # v0.1.87 — short-key alias for arm_aix 0022H gold.
    f.setdefault("burst_address_equations", {
        "Start_Address":   "AxADDR",
        "Number_Bytes":    "2 ^ AxSIZE",
        "Burst_Length":    "AxLEN + 1",
        "Aligned_Address": "INT(Start_Address / Number_Bytes) * Number_Bytes",
        "Address_1":       "Start_Address (first transfer)",
        "Address_N_INCR_or_pre-wrap":
            "Aligned_Address + (N - 1) * Number_Bytes",
        "Wrap_Boundary":
            "INT(Start_Address / (Number_Bytes * Burst_Length)) * "
            "(Number_Bytes * Burst_Length)",
        "WRAP_wrap_condition":
            "If Address_N = Wrap_Boundary + Number_Bytes*Burst_Length then "
            "Address_N := Wrap_Boundary",
    })
    d["fields"] = f
    _write(p, d)


# ============================================================
# L16 COMPLIANCE PROPERTIES
# ============================================================
def _l16(gd: Path) -> None:
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _f(d)
    d.setdefault("doc_name", "L16_COMPLIANCE_PROPERTIES")
    d.setdefault("applicability", "APPLICABLE")
    d.setdefault("ic_class", "bus_interconnect_protocol")
    f.setdefault("properties_axi_baseline_inherited", [
        {"id": "p_valid_stable_until_handshake",
         "scope": "all_5_axi_channels + 3_ace_snoop_channels",
         "english_form": "VALID must remain HIGH until handshake.",
         "citation": "A3.2.1 / C3.7"},
        {"id": "p_valid_not_dependent_on_ready",
         "scope": "all_channels",
         "english_form": "VALID must not be combinationally dependent on READY.",
         "citation": "A3.3.1 / C3.9"},
        {"id": "p_4kb_boundary_inherited",
         "scope": "AR_channel, AW_channel",
         "english_form": "A burst must not cross a 4KB address boundary.",
         "citation": "A3.4.1"},
    ])
    f.setdefault("properties_ace_extensions", [
        {"id": "p_ace_axdomain_legal",
         "scope": "AR_channel, AW_channel",
         "english_form": "AxDOMAIN must be one of 0b00/0b01/0b10/0b11.",
         "citation": "C3.1.1 Table C3-2"},
        {"id": "p_ace_arsnoop_legal_with_arbar_domain",
         "scope": "AR_channel",
         "english_form": "ARSNOOP must match permitted "
                         "(ARBAR[0], ARDOMAIN, ARSNOOP) tuples (Table C3-7).",
         "citation": "C3.1.3 Table C3-7"},
        {"id": "p_ace_awsnoop_legal_with_awbar_domain",
         "scope": "AW_channel",
         "english_form": "AWSNOOP must match permitted "
                         "(AWBAR[0], AWDOMAIN, AWSNOOP) tuples (Table C3-8).",
         "citation": "C3.1.3 Table C3-8"},
        {"id": "p_ace_rresp_constant_per_burst",
         "scope": "R_channel",
         "english_form": "RRESP[3:2] constant across all beats of a burst.",
         "citation": "C3.2.1"},
        {"id": "p_ace_rresp_must_be_low_for_noncoherent",
         "scope": "R_channel",
         "english_form": "RRESP[3:2]=0 for ReadNoSnoop / Barrier / DVM.",
         "citation": "C3.2.1"},
        {"id": "p_ace_isshared_illegal_for_unique_invalidations",
         "scope": "CR_channel",
         "english_form": "CRRESP[3] IsShared=0 for ReadUnique / CleanInvalid / MakeInvalid.",
         "citation": "C3.7"},
        {"id": "p_ace_passdirty_requires_datatransfer",
         "scope": "CR_channel",
         "english_form": "PassDirty=1 implies DataTransfer=1.",
         "citation": "C3.7"},
        {"id": "p_ace_snoop_dep_ac_before_cr",
         "scope": "CR_channel",
         "english_form": "Master waits for ACVALID+ACREADY before asserting CRVALID.",
         "citation": "C3.9 Figure C3-1"},
        {"id": "p_ace_snoop_dep_ac_before_cd",
         "scope": "CD_channel",
         "english_form": "Master waits for ACVALID+ACREADY before asserting CDVALID.",
         "citation": "C3.9 Figure C3-1"},
        {"id": "p_ace_snoop_response_ordered",
         "scope": "AC_channel + CR_channel",
         "english_form": "CR responses follow AC address order.",
         "citation": "C3.7"},
        {"id": "p_ace_rack_one_cycle_after_rlast",
         "scope": "Acknowledge",
         "english_form": "RACK single-cycle pulse one ACLK after RLAST+RVALID+RREADY.",
         "citation": "C3.5 / C9"},
        {"id": "p_ace_wack_one_cycle_after_b_handshake",
         "scope": "Acknowledge",
         "english_form": "WACK single-cycle pulse one ACLK after BVALID+BREADY.",
         "citation": "C3.5 / C9"},
        {"id": "p_ace_state_table_transitions",
         "scope": "Cache_line_FSM",
         "english_form": "Cache-line transitions per Table C5-4.",
         "citation": "C5.2"},
        {"id": "p_ace_cd_burst_length",
         "scope": "CD_channel",
         "english_form": "CD burst length must be 1/2/4/8/16; full cache-line on full CDDATA width.",
         "citation": "C3.8"},
        {"id": "p_ace_writeevict_requires_awunique",
         "scope": "AW_channel",
         "english_form": "WriteEvict (AWSNOOP=0b101) requires AWUNIQUE.",
         "citation": "C3.1.3"},
        {"id": "p_ace_lite_no_snoop_channels",
         "scope": "ACE-Lite_master",
         "english_form": "ACE-Lite masters must not implement AC/CR/CD.",
         "citation": "C1"},
        {"id": "p_ace_dvmcomplete_after_dvmmessage",
         "scope": "AR_channel + DVM",
         "english_form": "DVMComplete after all DVMMessage targets respond.",
         "citation": "C12"},
    ])
    d["fields"] = f
    _write(p, d)


# ============================================================
# L17 CHANNEL SIGNAL CATALOG
# ============================================================
def _l17(gd: Path) -> None:
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _f(d)
    d.setdefault("doc_name", "L17_CHANNEL_SIGNAL_CATALOG")
    d.setdefault("applicability", "APPLICABLE")
    d.setdefault("ic_class", "bus_interconnect_protocol")
    f.setdefault("global_signals", [
        {"name": "ACLK",    "width": "1", "direction": "Clock source -> all",
         "semantics": "Global clock; rising-edge sampled."},
        {"name": "ARESETn", "width": "1", "direction": "Reset source -> all",
         "semantics": "Active-LOW reset."},
    ])
    _force_set(f, "axi_channels_with_ace_additions", [
        {"name": "AW", "full_name": "Write Address Channel (with ACE extensions)",
         "direction": "Master -> Slave",
         "signals_axi_inherited":
             ["AWID", "AWADDR", "AWLEN", "AWSIZE", "AWBURST", "AWLOCK",
              "AWCACHE", "AWPROT", "AWQOS", "AWREGION", "AWUSER",
              "AWVALID", "AWREADY"],
         "signals_ace_added": [
             {"name": "AWDOMAIN", "width": "2",
              "semantics": "Shareability domain."},
             {"name": "AWSNOOP",  "width": "3",
              "semantics": "Coherent write type."},
             {"name": "AWBAR",    "width": "2",
              "semantics": "Barrier encoding."},
             {"name": "AWUNIQUE", "width": "1",
              "semantics": "Optional, for WriteEvict."},
         ]},
        {"name": "W", "full_name": "Write Data Channel (inherited from AXI)",
         "direction": "Master -> Slave",
         "signals_axi_inherited":
             ["WID (AXI3 only)", "WDATA", "WSTRB", "WLAST", "WUSER",
              "WVALID", "WREADY"],
         "signals_ace_added": []},
        {"name": "B", "full_name": "Write Response Channel (with ACE extensions)",
         "direction": "Slave -> Master",
         "signals_axi_inherited":
             ["BID", "BVALID", "BREADY", "BUSER"],
         "signals_ace_added": [
             {"name": "BRESP", "width": "3",
              "semantics": "Extended; [2]=DataTransfer."},
         ]},
        {"name": "AR", "full_name": "Read Address Channel (with ACE extensions)",
         "direction": "Master -> Slave",
         "signals_axi_inherited":
             ["ARID", "ARADDR", "ARLEN", "ARSIZE", "ARBURST", "ARLOCK",
              "ARCACHE", "ARPROT", "ARQOS", "ARREGION", "ARUSER",
              "ARVALID", "ARREADY"],
         "signals_ace_added": [
             {"name": "ARDOMAIN", "width": "2", "semantics": "Shareability domain."},
             {"name": "ARSNOOP",  "width": "4",
              "semantics": "Coherent read / cache-maintenance / DVM type."},
             {"name": "ARBAR",    "width": "2", "semantics": "Barrier encoding."},
         ]},
        {"name": "R", "full_name": "Read Data Channel (with ACE extensions)",
         "direction": "Slave -> Master",
         "signals_axi_inherited":
             ["RID", "RDATA", "RLAST", "RUSER", "RVALID", "RREADY"],
         "signals_ace_added": [
             {"name": "RRESP", "width": "4",
              "semantics": "Extended; [2]=PassDirty, [3]=IsShared."},
         ]},
    ])
    f.setdefault("ace_snoop_channels_new", [
        {"name": "AC", "full_name": "Snoop Address Channel",
         "direction": "Interconnect -> Master (cached)",
         "signals": [
             {"name": "ACVALID", "width": "1", "direction": "Interconnect", "semantics": "Snoop address valid."},
             {"name": "ACREADY", "width": "1", "direction": "Master",       "semantics": "Master accepts snoop."},
             {"name": "ACADDR",  "width": "ADDR_WIDTH", "direction": "Interconnect", "semantics": "Snoop address."},
             {"name": "ACSNOOP", "width": "4", "direction": "Interconnect", "semantics": "Snoop type."},
             {"name": "ACPROT",  "width": "3", "direction": "Interconnect", "semantics": "Snoop protection."},
         ]},
        {"name": "CR", "full_name": "Snoop Response Channel",
         "direction": "Master (cached) -> Interconnect",
         "signals": [
             {"name": "CRVALID", "width": "1", "direction": "Master",       "semantics": "Snoop response valid."},
             {"name": "CRREADY", "width": "1", "direction": "Interconnect", "semantics": "Accept snoop response."},
             {"name": "CRRESP",  "width": "5", "direction": "Master",       "semantics": "DataTransfer/Error/PassDirty/IsShared/WasUnique."},
         ]},
        {"name": "CD", "full_name": "Snoop Data Channel",
         "direction": "Master (cached) -> Interconnect",
         "signals": [
             {"name": "CDVALID", "width": "1", "direction": "Master",       "semantics": "Snoop data valid."},
             {"name": "CDREADY", "width": "1", "direction": "Interconnect", "semantics": "Accept snoop data."},
             {"name": "CDDATA",  "width": "CD_DATA_WIDTH", "direction": "Master", "semantics": "Snoop data payload."},
             {"name": "CDLAST",  "width": "1", "direction": "Master",       "semantics": "Final beat of snoop data burst."},
         ]},
    ])
    f.setdefault("ace_acknowledge_signals", [
        {"name": "RACK", "width": "1", "direction": "Master -> Interconnect",
         "semantics": "Single-cycle pulse one ACLK after RLAST handshake."},
        {"name": "WACK", "width": "1", "direction": "Master -> Interconnect",
         "semantics": "Single-cycle pulse one ACLK after B handshake."},
    ])
    # v0.1.87 — FORCE overwrite (AHB+APB synth pre-populates channel_counts
    # with AHB-format keys; ACE/AXI agents expect protocol-format keys).
    # Emit BOTH AXI-baseline keys (channels/signals_per_channel/totals — used
    # by arm_aix 0022H gold) AND ACE-specific keys (axi_channels/snoop counts
    # — used by ace_chi 0022E gold). Extra keys are OK; walker only flags
    # MISSING keys.
    _force_set(f, "channel_counts", {
        # ACE-additions (0022E / ace_chi gold):
        "axi_channels": 5,
        "ace_snoop_channels": 3,
        "ace_lite_snoop_channels": 0,
        "ack_signals": 2,
        # AXI-baseline (0022H / arm_aix gold):
        "channels": 5,
        "signals_per_channel": {
            "AW": 13, "W": 7, "B": 5, "AR": 13, "R": 7,
        },
        "total_signals_excluding_global": 45,
        "total_signals_including_ACLK_ARESETn": 47,
    })
    f.setdefault("handshake_pairs_summary", {
        "AW": "AWVALID/AWREADY", "W": "WVALID/WREADY", "B": "BVALID/BREADY",
        "AR": "ARVALID/ARREADY", "R": "RVALID/RREADY",
        "AC": "ACVALID/ACREADY", "CR": "CRVALID/CRREADY", "CD": "CDVALID/CDREADY",
    })
    f.setdefault("dependency_graph_ace_snoops", {
        "rule_1": "Interconnect drives ACVALID independent of ACREADY.",
        "rule_2": "Master waits for ACVALID+ACREADY before CRVALID.",
        "rule_3": "Master waits for ACVALID+ACREADY before CDVALID (if DataTransfer=1).",
        "rule_4": "CRVALID/CDVALID must not depend combinationally on CRREADY/CDREADY.",
        "rule_5": "Interconnect may wait for CRVALID/CDVALID before completing snoop.",
    })
    f.setdefault("ordering_rules_ace", {
        "snoop_ordering":         "CR responses follow AC address order.",
        "RACK_required_before":   "Interconnect must observe RACK before dependent snoops.",
        "WACK_required_before":   "Interconnect must observe WACK before dependent snoops.",
        "same_id_ordering":       "Inherited from AXI.",
        "different_id_ordering":  "Inherited from AXI.",
    })
    # v0.1.87 — AXI baseline dependency_graph (arm_aix 0022H gold).
    f.setdefault("dependency_graph", {
        "common_rule":
            "VALID must not depend (combinationally) on READY. A source may "
            "not wait for READY before asserting VALID. A receiver may "
            "assert READY before or after VALID.",
        "AXI_read":
            "ARVALID asserted independently of ARREADY. Slave must wait for "
            "both ARVALID and ARREADY before asserting RVALID. RVALID "
            "independent of RREADY.",
        "AXI3_write":
            "AWVALID and WVALID asserted independently of AWREADY/WREADY. "
            "Slave must wait for WVALID, WREADY, and WLAST before asserting "
            "BVALID. BVALID may be asserted BEFORE AW handshake completes "
            "(AXI3 only).",
        "AXI4_write":
            "AWVALID and WVALID asserted independently of AWREADY/WREADY. "
            "Slave must wait for AWVALID, AWREADY, WVALID, WREADY, AND WLAST "
            "before asserting BVALID. AXI4 adds the AW handshake as a "
            "precondition for BVALID.",
    })
    # v0.1.87 — AXI baseline ordering_rules (arm_aix 0022H gold).
    f.setdefault("ordering_rules", {
        "read_data_ordering":
            "Interconnect must ensure that read data from a sequence of "
            "transactions with the same ARID targeting different slaves is "
            "delivered to the master in the order the addresses were "
            "issued. Read data reordering depth is the static count of "
            "pending addresses in a slave that may be reordered.",
        "write_data_ordering":
            "Master must issue write data in the same order as transaction "
            "addresses. AXI4+ removes WID and prohibits write data "
            "interleaving.",
        "response_ordering":
            "Transaction responses with the same ID are returned in the "
            "same order as the requests were issued. No ordering "
            "guarantees between different IDs, different destinations, or "
            "different channels.",
        "same_id_same_destination":
            "Transaction requests on the same channel, with the same ID "
            "and destination are guaranteed to remain in order.",
    })
    d["fields"] = f
    _write(p, d)


# ============================================================
# L18 INTERCONNECT TOPOLOGY
# ============================================================
def _l18(gd: Path) -> None:
    p = gd / "L18_INTERCONNECT_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _f(d)
    d.setdefault("doc_name", "L18_INTERCONNECT_TOPOLOGY")
    d.setdefault("applicability", "APPLICABLE")
    d.setdefault("ic_class", "bus_interconnect_protocol")
    f.setdefault("typical_topologies_inherited", [
        "Shared address and data buses",
        "Shared address buses and multiple data buses",
        "Multilayer, with multiple address and data buses",
    ])
    f.setdefault("ace_specific_topology_components", [
        "Point of Serialization (POS)",
        "Point of Coherency (PoC)",
        "Snoop Filter (optional)",
        "Cached Master Port (full ACE)",
        "ACE-Lite Master Port (no AC/CR/CD)",
        "Snoop Distributor",
        "DVM Distributor",
    ])
    f.setdefault("interconnect_role_in_ace_summary", [
        "Decode (AxDOMAIN+AxSNOOP+AxBAR+AxADDR) -> snoop list.",
        "Issue AC snoops to targets.",
        "Collect CR + CD; aggregate.",
        "Forward response on R / B with extended RRESP / BRESP.",
        "Wait for RACK / WACK.",
        "Handle barrier transactions.",
        "Distribute DVM messages.",
    ])
    f.setdefault("id_handling_inherited",
        "Inherited from AXI4: interconnect appends master-port bits.")
    f.setdefault("interconnect_ordering_requirements_ace", [
        "Inherited AXI same-ID ordering.",
        "Snoop ordering on CR per master.",
        "RACK/WACK gating before dependent snoops.",
        "Barriers block reordering within named domain.",
        "DVM: DVMComplete after all DVMMessage targets respond.",
    ])
    f.setdefault("default_signal_values_for_ace_additions", {
        "ARDOMAIN_default_for_legacy_axi_masters": "0b00 (Non-shareable)",
        "ARSNOOP_default_for_non_coherent_master":
            "0b0000 (ReadNoSnoop when ARDOMAIN=Non-shareable/System).",
        "ARBAR_default":   "0b00 (Normal access, not a barrier).",
        "AWDOMAIN_default": "0b00 (Non-shareable)",
        "AWSNOOP_default":
            "0b000 (WriteNoSnoop when AWDOMAIN=Non-shareable/System).",
        "AWBAR_default":    "0b00 (Normal access).",
        "RRESP_extended_default":
            "RRESP[3:2]=00 (UniqueClean — for non-coherent reads).",
        "BRESP_extended_default":
            "BRESP[2]=0 (no DataTransfer) for normal AXI writes.",
        "RACK_WACK_for_axi_only_masters":
            "Tie LOW or auto-ack at interconnect boundary.",
    })
    f.setdefault("snoop_filter_optional_requirements", {
        "purpose": "Reduce snoop traffic.",
        "required_notifications": [
            "Evict for Inner/Outer Shareable clean line removal.",
            "WriteEvict + AWUNIQUE for UniqueClean removal.",
            "WriteBack/WriteClean with correct AWDOMAIN.",
        ],
        "without_snoop_filter":
            "Interconnect must broadcast every snoop to every coherent master.",
    })
    f.setdefault("memory_vs_peripheral_regions_inherited", {
        "Memory_location":   "Read returns last value written.",
        "Peripheral_region": "Implementation-defined access method.",
    })
    f.setdefault("barrier_scope_by_domain", {
        "Non_shareable_barrier":   "Orders only within initiator's Non-shareable domain.",
        "Inner_Shareable_barrier": "Orders within Inner-shareable domain.",
        "Outer_Shareable_barrier": "Orders within Outer-shareable domain.",
        "System_barrier":          "Orders across all masters in system.",
    })
    f.setdefault("dvm_distribution_rules", [
        "DVMMessage broadcast on AC of DVM-capable masters in named domain.",
        "Each target invalidates and acks on CR.",
        "DVMComplete issued after all targets ack; interconnect aggregates.",
        "DVMMessage = ARSNOOP=0b1111; DVMComplete = ARSNOOP=0b1110.",
    ])
    d["fields"] = f
    _write(p, d)


# ============================================================
# L19 CONSTRAINTS / PDK
# ============================================================
def _l19(gd: Path) -> None:
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _f(d)
    d.setdefault("doc_name", "L19_CONSTRAINTS_PDK")
    d.setdefault("applicability", "NOT_APPLICABLE")
    d.setdefault("ic_class", "bus_interconnect_protocol")
    f.setdefault("constraints_present", False)
    f["notes"] = (
        "IHI 0022E is a wire-level / cycle-level bus protocol spec. It "
        "defines logical signal semantics and timing rules relative to "
        "ACLK only - no PDK-specific SDC, no floorplan / placement "
        "constraints, no clock-tree budget. ACE adds three snoop "
        "channels (AC/CR/CD) following the same single-clock rule; "
        "timing budgets for AC/CR/CD must be planned at integration.")
    d["fields"] = f
    _write(p, d)


# ============================================================
# L20 DFT SCAN
# ============================================================
def _l20(gd: Path) -> None:
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _f(d)
    d.setdefault("doc_name", "L20_DFT_SCAN_TOPOLOGY")
    d.setdefault("applicability", "NOT_APPLICABLE")
    d.setdefault("ic_class", "bus_interconnect_protocol")
    f.setdefault("dft_present", False)
    f["notes"] = (
        "ACE / IHI 0022E does not specify DFT / scan / BIST / MBIST / "
        "boundary scan. Concrete coherent IP blocks add standard scan "
        "during SoC integration; debug visibility via ARM CoreSight / "
        "JTAG / trace - outside this spec. CRRESP[1] Error and "
        "RRESP[3:2] are the closest functional observability.")
    f.setdefault("closest_protocol_observability", [
        "CRRESP[1] Error.",
        "RRESP[3:2] PassDirty/IsShared visible in trace.",
        "DECERR default-slave for undecoded coherent transactions.",
    ])
    d["fields"] = f
    _write(p, d)


# ============================================================
# L21 POWER INTENT
# ============================================================
def _l21(gd: Path) -> None:
    p = gd / "L21_POWER_INTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _f(d)
    d.setdefault("doc_name", "L21_POWER_INTENT")
    d.setdefault("applicability", "NOT_APPLICABLE")
    d.setdefault("ic_class", "bus_interconnect_protocol")
    f.setdefault("power_intent_present", False)
    # v0.1.87 — FORCE overwrite (AHB+APB synth pre-populates with AHB-format
    # keys; agent gold expects ACE-format keys axi_idle/ace_idle/ace_q_channel).
    _force_set(f, "low_power_modes_summary", {
        "axi_idle":
            "Manager drives no valid xVALIDs; ACLK gating is "
            "implementation-defined.",
        "ace_idle":
            "No outstanding coherent or snoop traffic; snoop channels' "
            "VALIDs LOW; clock gating allowed.",
        "ace_q_channel_intent":
            "Q-Channel (separate AMBA Low Power Interface, ARM IHI 0068) "
            "is typically layered on top of ACE for power-down handshakes; "
            "that's outside IHI 0022E scope.",
    })
    f.setdefault("notes",
        "Power-domain partitioning, voltage-domain crossings, power-"
        "gate sequencing, isolation, retention, and Q-Channel low-"
        "power handshakes are deferred to SoC integration (UPF/CPF) "
        "and other AMBA documents. ACE coherency requires powered-"
        "down masters to drop out of the shareability domain cleanly.")
    d["fields"] = f
    _write(p, d)


# ============================================================
# L22 VERIFICATION PLAN
# ============================================================
def _l22(gd: Path) -> None:
    p = gd / "L22_VERIFICATION_PLAN.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _f(d)
    d.setdefault("doc_name", "L22_VERIFICATION_PLAN")
    d.setdefault("applicability", "APPLICABLE")
    d.setdefault("ic_class", "bus_interconnect_protocol")
    f.setdefault("verification_plan_present", "implicit")
    if _empty(f.get("verification_categories_derived_axi_baseline")):
        f["verification_categories_derived_axi_baseline"] = [
            "Reset behavior (ARESETn).",
            "VALID/READY handshake compliance.",
            "Burst type INCR/WRAP/FIXED + AxSIZE coverage.",
            "4KB boundary enforcement.",
            "Same-ID in-order; diff-ID out-of-order.",
            "Exclusive access (EXOKAY/OKAY).",
            "Error responses (SLVERR/DECERR).",
            "Default-signal substitution.",
        ]
    if _empty(f.get("verification_categories_derived_ace")):
        f["verification_categories_derived_ace"] = [
            "AxDOMAIN encoding coverage.",
            "ARSNOOP encoding coverage (12 valid encodings).",
            "AWSNOOP encoding coverage (7 valid encodings).",
            "AxBAR barrier coverage across all 4 domains.",
            "Reserved AxSNOOP rejected.",
            "Illegal (AxDOMAIN, AxSNOOP, AxBAR) tuples rejected.",
            "Snoop channel handshake (AC/CR/CD).",
            "Snoop ordering.",
            "5-state cache-line transitions.",
            "CRRESP correctness (DataTransfer/Error/PassDirty/IsShared/WasUnique).",
            "Illegal CRRESP combinations.",
            "RACK/WACK timing.",
            "Snoop data bus width variation.",
            "CD burst length 1/2/4/8/16.",
            "DVMMessage + DVMComplete handshake.",
            "Barrier transaction effect.",
            "ACE-Lite subset enforcement.",
            "AXI4 master on ACE interconnect at Non-shareable.",
            "Snoop filter consistency (Evict/WriteEvict).",
            "Multi-master stress.",
            "Single-writer-eventually invariant.",
        ]
    f.setdefault("interoperability_test_matrix", [
        "Full ACE master + ACE interconnect.",
        "ACE-Lite master + ACE interconnect.",
        "AXI4 master + ACE interconnect at Non-shareable.",
        "Mixed cluster: ACE + ACE-Lite + AXI4 + DVM in one interconnect.",
        "Snoop data bus narrower than RDATA/WDATA.",
        "Multi-domain barriers (Inner/Outer/System).",
        "Snoop filter ON vs OFF.",
    ])
    f["notes"] = (
        "IHI 0022E does not provide a formal verification plan; "
        "categories derived from Chapters C3 (Channel Signaling), C4 "
        "(Coherent Transactions), C5 (Snoop Transactions), C8 (Barrier "
        "Transactions), C9 (RACK/WACK), C12 (DVM).")
    d["fields"] = f
    _write(p, d)


# ============================================================
# L23 SECURITY REQUIREMENTS
# ============================================================
def _l23(gd: Path) -> None:
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _f(d)
    d.setdefault("doc_name", "L23_SECURITY_REQUIREMENTS")
    d.setdefault("applicability", "APPLICABLE")
    d.setdefault("ic_class", "bus_interconnect_protocol")
    f["security_requirements_present"] = "partial"
    f.setdefault("axi_baseline_security_inherited", [
        {"name": "AxPROT[0] Privileged",  "purpose": "Privilege-level signaling."},
        {"name": "AxPROT[1] Non-secure",  "purpose": "Secure vs Non-secure access (TrustZone)."},
        {"name": "AxPROT[2] Instruction", "purpose": "Data vs instruction hint."},
        {"name": "Exclusive accesses (AxLOCK)",
         "purpose": "Concurrency-safe RMW primitives."},
    ])
    f.setdefault("ace_extensions_to_security_layer", [
        {"name": "ACPROT[2:0]",
         "purpose": "Snoop-channel equivalent of AxPROT."},
        {"name": "AxDOMAIN",
         "purpose": "Shareability domain partitioning combined with TrustZone."},
        {"name": "AxBAR (Barriers)",
         "purpose": "Ordering across secure / non-secure boundary."},
        {"name": "DVM TLB invalidate scope",
         "purpose": "Must respect shareability domain and Secure/Non-secure."},
    ])
    f.setdefault("what_is_NOT_in_the_spec", [
        "No confidentiality / encryption.",
        "No data-integrity / authentication.",
        "No replay protection.",
        "No anti-rollback.",
        "No attestation.",
        "No key-storage / key-derivation.",
        "No protection against malicious cached masters violating coherency.",
    ])
    f.setdefault("secure_integration_responsibilities", [
        "TrustZone partitioning via AxPROT[1] / ACPROT[1].",
        "Shareability-domain partitioning for security (Secure-only domain).",
        "DVM scope enforcement.",
        "Snoop-data path filtering for cross-security snoops.",
        "WriteBack/WriteClean of Secure lines must not be observable on Non-secure paths.",
        "ACE-Lite IO masters must use correct AxPROT and AxDOMAIN.",
    ])
    f["notes"] = (
        "Security in AMBA AXI/ACE is limited to signaling primitives "
        "(AxPROT / ACPROT / Exclusive Access / Lock + shareability-"
        "domain partitioning) - not cryptographic primitives. ACE's "
        "coherency protocol assumes trusted cached masters within a "
        "domain. End-to-end confidentiality/integrity must be provided "
        "by upper layers (TrustZone, MMU/SMMU, crypto IP, secure boot).")
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
def is_ace(blob: str) -> bool:
    """Content-only `ace` detector (importable, lifted from the runner) WITH a
    FOREIGN-PRIMARY DEFER.

    Empty-safe. Reads ONLY ``blob`` (spec text). Below the defer it is
    byte-for-byte the same boolean the runner used inline.

    The structural ACE signature (AxBAR+AxDOMAIN+AxSNOOP, OR ACE+ReadShared+
    ReadUnique, OR DVM+TLB+AXI/AMBA) is necessary but NOT sufficient. The full
    *AMBA AXI Protocol Specification* (ARM IHI 0022) describes ACE as one
    coherency EXTENSION alongside the AXI baseline, so the document carries the
    ACE signal-name vocabulary in full even though its DOMINANT subject is the
    comprehensive multi-variant AXI bus protocol (AXI3 / AXI4 / AXI4-Lite /
    AXI5 / ACE-Lite), not the standalone ACE coherency layer. Without a guard
    the generic ACE synth FORCE-overwrites those AXI-baseline specs' L-docs
    with ACE-only gold (ic_name, purpose, key_features), which is wrong: the
    AXI baseline is handled by the R46-R52 universal protocol-fact path, not
    the ACE overlay.

    Guard (mirrors `is_mipi`'s foreign-primary defer doctrine and the AHB+APB
    `_axi_primary` doctrine — general, content-only, NO chip/SKU/benchmark-name
    literal as detection logic): if the blob's DOMINANT subject is the
    comprehensive AMBA AXI Protocol Specification document, defer (False) so the
    ACE overlay never fires on an AXI-baseline spec that merely describes ACE as
    an extension. The signature is the dense ARM IHI 0022 / AMBA AXI document
    identity (a real ACE-focused spec cites these only incidentally) combined
    with the COMPLETE AXI baseline: all five AXI channels named AND multiple
    AXI variants enumerated (AXI3 + AXI4 + AXI4-Lite). A standalone ACE spec
    focuses on the snoop/coherency layer and does not carry this dense
    full-baseline AXI-document signature.
    """
    if not blob:
        return False
    low = blob.lower()

    # --- FOREIGN-PRIMARY DEFER (the blob's true subject is the comprehensive
    #     AMBA AXI Protocol Specification, ACE is only an extension chapter). ---
    # Document-identity density: the ARM IHI 0022 AMBA AXI spec repeats its own
    # title/document-id on every page (header/footer). Incidental ACE citation
    # never reaches this density.
    _axi_doc_identity = (
        low.count("amba axi") >= 20
        or low.count("ihi 0022") >= 20
        or low.count("arm ihi") >= 20)
    # Complete AXI baseline channel enumeration (the five AXI channels).
    _axi_five_channels = (
        "write address channel" in low
        and "read address channel" in low
        and "write data channel" in low
        and "read data channel" in low
        and "write response channel" in low)
    # Multiple AXI baseline variants enumerated (a hallmark of the full spec,
    # absent from an extension-only ACE document).
    _axi_multi_variant = (
        "axi3" in low and "axi4" in low and "axi4-lite" in low)
    axi_spec_primary = (
        _axi_doc_identity and _axi_five_channels and _axi_multi_variant)
    if axi_spec_primary:
        return False

    # --- STRUCTURAL ACE coherency-extension signature (unchanged from the
    #     runner's inline detector). ---
    return bool(
        ("AxBAR" in blob and "AxDOMAIN" in blob
            and "AxSNOOP" in blob)
        or ("ACE" in blob and "ReadShared" in blob
            and "ReadUnique" in blob)
        or ("DVM" in blob and "TLB" in blob
            and ("AXI" in blob or "AMBA" in blob)))
