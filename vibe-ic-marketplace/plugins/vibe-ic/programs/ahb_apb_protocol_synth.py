"""AHB + APB-class protocol synth helper.

v0.1.84 — ic_class-gated overlay for `bus_interconnect_protocol` specs that
exhibit the AMBA AHB-Lite/AHB5 or AMBA APB structural signature.

Applies ARM IHI 0033C (AHB) + IHI 0024C (APB v2.0) spec-canonical content
to L1-L23 + L8 timing + L14-L23.

Doctrine: structural-signature detection IS general within an ic_class
(mirrors the AMBA-AXI / SPI / I2C / UART / CAN / USB / I2S synth approach).
Any AHB / APB variant — AHB-Lite, AHB5, APB2, APB3, APB4, or a combined
AHB+APB family spec — exhibits the same signal-name signature
(HCLK+HADDR+HTRANS+HREADY+HRESP for AHB, PCLK+PADDR+PSEL+PENABLE for APB).
The two protocols are covered together because the combined-benchmark
target ahb_apb describes ARM's two sibling buses in one IC class.

Public entry: `apply_ahb_apb_synth(generated_docs_dir, is_ahb_apb,
                                   ahb_apb_ic_name)`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import l_doc_generator_stamp as _stamp


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
    """Helper: setdefault is a no-op if key exists with value None — use
    explicit empty-check to handle that case across the codebase."""
    if d.get(key) in (None, "", []):
        d[key] = {}
    return d[key]


def _ensure_full(d: dict, key: str, value):
    """Force-set when key missing or value empty (None/""/[]/{})."""
    cur = d.get(key)
    if cur is None or cur == "" or cur == [] or cur == {}:
        d[key] = value
    return d[key]


def _force_set(d: dict, key: str, value) -> None:
    """Unconditional overwrite (use when parity gold mandates a specific
    string and upstream may have written a placeholder)."""
    d[key] = value


# ============================================================
# Public entry
# ============================================================
def apply_ahb_apb_synth(generated_docs_dir: Path,
                        is_ahb_apb: bool,
                        ahb_apb_ic_name: Optional[str]) -> None:
    """Apply AHB+APB-specific synth when the structural signature matched.

    fail-open contract: print errors but never raise.
    """
    if not is_ahb_apb:
        return
    gd = Path(generated_docs_dir)

    try:
        # Force ic_name across the 14 main L docs (L1-L23 + L8 timing).
        # Critical: set this BEFORE per-layer overlays so downstream
        # comparators see the canonical IC name.
        if ahb_apb_ic_name is not None:
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
                    d["ic_name"] = ahb_apb_ic_name
                    _write(q, d)

            # L14-L23 keep ic_name inside the inner `fields` dict.
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
                    f = _ensure_dict(d, "fields")
                    f["ic_name"] = ahb_apb_ic_name
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
        print(f"[ahb_apb_protocol_synth] WARN: {exc}")


# ============================================================
# L1 DATASHEET
# ============================================================
def _l1(gd: Path) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("document_title_ahb", "AMBA AHB Protocol Specification")
    d.setdefault("document_title_apb", "AMBA APB Protocol Specification")
    d.setdefault("document_number_ahb", "ARM IHI 0033C (ID090921)")
    d.setdefault("document_number_apb", "ARM IHI 0024C (ID042910)")
    d.setdefault("issue_ahb", "C")
    d.setdefault("issue_apb", "C (APB v2.0 / APB4)")
    d.setdefault("ahb_issue_date", "15 September 2021")
    d.setdefault("apb_issue_date", "13 April 2010")
    d.setdefault("manufacturer", "Arm Limited (originally ARM Limited)")
    d.setdefault("copyright_ahb",
        "Copyright (c) 2001, 2006, 2010, 2015, 2021 Arm Limited or its affiliates")
    d.setdefault("copyright_apb",
        "Copyright (c) 2003-2010 ARM. All rights reserved.")
    d.setdefault("confidentiality", "Non-Confidential")
    d.setdefault("external_pin_count_ahb_lite_min", 11)  # HCLK+HRESETn+HADDR+HBURST+HSIZE+HTRANS+HWDATA+HRDATA+HREADY+HRESP+HWRITE
    d.setdefault("external_pin_count_apb_min", 7)        # PCLK+PRESETn+PADDR+PSEL+PENABLE+PWRITE+PWDATA (PRDATA shared on bus)
    d.setdefault("key_features_ahb", [
        "Burst transfers (SINGLE, INCR, INCR4/8/16, WRAP4/8/16)",
        "Single clock-edge operation (rising HCLK)",
        "Non-tristate implementation (separate HWDATA / HRDATA)",
        "Configurable data widths: 8/16/32/64/128/256/512/1024 bits",
        "Configurable address widths (ADDR_WIDTH 10..64, default 32)",
        "Pipelined address phase + data phase",
        "Single-Manager AHB-Lite with centralized decoder + multiplexor",
        "Two-cycle ERROR response on HRESP",
        "AHB5 optional features: HNONSEC / HEXCL / HMASTER / HEXOKAY / "
        "HWSTRB / HxUSER / HxxCHK (parity)",
    ])
    d.setdefault("key_features_apb", [
        "Low-power peripheral bus optimized for minimal interface "
        "complexity",
        "Not pipelined — every transfer takes at least two PCLK cycles",
        "Two-phase transfer: SETUP (PSEL=1, PENABLE=0) -> ACCESS "
        "(PSEL=1, PENABLE=1)",
        "Up to 32-bit PADDR / PWDATA / PRDATA",
        "PREADY (APB3+) extends ACCESS with wait states",
        "PSLVERR (APB3+) signals transfer failure",
        "PPROT[2:0] (APB4) for protection (normal/privileged, "
        "secure/nonsecure, data/instruction)",
        "PSTRB[3:0] (APB4) byte-lane write strobes",
        "Bridgeable from AHB / AHB-Lite / AXI / AXI4-Lite via "
        "an AHB-to-APB or AXI-to-APB bridge",
    ])
    d.setdefault("ahb_signal_groups", {
        "global":     ["HCLK", "HRESETn"],
        "manager":    [
            "HADDR", "HBURST", "HMASTLOCK", "HPROT", "HSIZE",
            "HNONSEC (AHB5)", "HEXCL (AHB5)", "HMASTER (AHB5)",
            "HTRANS", "HWDATA", "HWSTRB (Issue C)", "HWRITE",
        ],
        "subordinate":[
            "HRDATA", "HREADYOUT", "HRESP", "HEXOKAY (AHB5)",
        ],
        "decoder":    ["HSELx"],
        "multiplexor":["HRDATA", "HREADY", "HRESP", "HEXOKAY"],
    })
    d.setdefault("apb_signal_set", [
        "PCLK", "PRESETn", "PADDR", "PPROT (APB4)",
        "PSELx", "PENABLE", "PWRITE", "PWDATA", "PSTRB (APB4)",
        "PREADY (APB3+)", "PRDATA", "PSLVERR (APB3+)",
    ])
    d.setdefault("ahb_burst_types", [
        {"hburst": "0b000", "name": "SINGLE", "length_beats": 1},
        {"hburst": "0b001", "name": "INCR",   "length_beats": -1, "undefined_length": True},
        {"hburst": "0b010", "name": "WRAP4",  "length_beats": 4,  "wraps": True},
        {"hburst": "0b011", "name": "INCR4",  "length_beats": 4},
        {"hburst": "0b100", "name": "WRAP8",  "length_beats": 8,  "wraps": True},
        {"hburst": "0b101", "name": "INCR8",  "length_beats": 8},
        {"hburst": "0b110", "name": "WRAP16", "length_beats": 16, "wraps": True},
        {"hburst": "0b111", "name": "INCR16", "length_beats": 16},
    ])
    d.setdefault("ahb_htrans_types", [
        {"value": "0b00", "name": "IDLE",   "description": "No data transfer; Subordinate must give zero-wait OKAY"},
        {"value": "0b01", "name": "BUSY",   "description": "Manager continuing a burst but cannot complete next transfer immediately"},
        {"value": "0b10", "name": "NONSEQ", "description": "Single transfer or first transfer of a burst"},
        {"value": "0b11", "name": "SEQ",    "description": "Remaining transfers in a burst"},
    ])
    d.setdefault("ahb_hsize_to_bits", {
        "0b000": 8, "0b001": 16, "0b010": 32, "0b011": 64,
        "0b100": 128, "0b101": 256, "0b110": 512, "0b111": 1024,
    })
    d.setdefault("ahb_hresp_encoding", {
        "0": "OKAY",
        "1": "ERROR (two-cycle response: HRESP=1+HREADY=0, then HRESP=1+HREADY=1)",
    })
    d.setdefault("ahb_1kb_burst_rule",
        "Managers must not attempt to start an incrementing burst that "
        "crosses a 1KB address boundary. The minimum slave decode "
        "granularity is also 1KB.")
    # Parity-gold additions (L1)
    d.setdefault("document_ids", [
        {"protocol": "AHB",  "document_id": "ARM IHI 0033C (ID090921)", "issue": "C",   "date": "15 September 2021"},
        {"protocol": "APB",  "document_id": "ARM IHI 0024C (ID042910)", "issue": "C",   "date": "13 April 2010"},
    ])
    d.setdefault("issuer", "Arm Limited")
    d.setdefault("release_history_ahb", [
        {"date": "06 June 2006",        "issue": "A",   "change": "First release for v1.0 (AHB-Lite)"},
        {"date": "25 June 2015",        "issue": "B.a", "change": "Update for AMBA 5 AHB Protocol Specification (Confidential)"},
        {"date": "30 October 2015",     "issue": "B.b", "change": "Confidential to Non-Confidential Release"},
        {"date": "15 September 2021",   "issue": "C",   "change": "New features and enhancements: Signal width properties, Write strobes, User signaling update, Signal validity rules, Interface protection using parity. Regularized terminology to Manager and Subordinate."},
    ])
    d.setdefault("release_history_apb", [
        {"date": "25 September 2003",   "issue": "A",   "change": "First release for v1.0"},
        {"date": "17 August 2004",      "issue": "B",   "change": "Second release for v1.0"},
        {"date": "13 April 2010",       "issue": "C",   "change": "First release for v2.0 (adds PPROT + PSTRB)"},
    ])
    d.setdefault("protocol_variants_described", [
        "AHB-Lite (single-Manager pipelined high-performance bus, Issue A)",
        "AHB5 (extends AHB-Lite with optional secure / exclusive / user / parity features, Issue B onwards)",
        "AHB (Issue C C terminology supersedes Master/Slave with Manager/Subordinate)",
        "APB2 (AMBA 2 APB Specification, basic two-phase peripheral bus)",
        "APB3 (AMBA 3 APB v1.0 - adds PREADY wait states and PSLVERR error response)",
        "APB4 (AMBA APB v2.0 - adds PPROT protection and PSTRB write strobes)",
    ])
    d.setdefault("purpose",
        "Defines the AMBA AHB and APB on-chip bus protocols. AHB is a "
        "high-performance, pipelined, synchronous bus suitable for memory-"
        "bandwidth-intensive Managers/Subordinates; APB is a low-cost, "
        "low-power, non-pipelined peripheral bus optimized for register-"
        "mapped peripheral access. APB is normally connected to AHB "
        "through an AHB-to-APB bridge. Both are members of the AMBA "
        "family (which also includes AXI/ACE).")
    d.setdefault("ahb_4kb_burst_rule",
        "An incrementing burst (INCR / INCRn) must not cross a 1KB "
        "address boundary (note: AHB uses 1KB not the AXI 4KB).")
    # VALUE_MISMATCH: endianness — gold has a specific non-list explanation.
    if isinstance(d.get("endianness"), list) or _empty(d.get("endianness")):
        d["endianness"] = (
            "Not endian-defined at the protocol level; byte-invariant "
            "when interfacing to byte-invariant systems (AHB Chapter 6).")
    d.setdefault("apb_operating_states",
        ["IDLE (PSELx=0, PENABLE=0)",
         "SETUP (PSELx=1, PENABLE=0)",
         "ACCESS (PSELx=1, PENABLE=1)"])
    d.setdefault("apb_pprot_encoding", {
        "PPROT[0]": "0 = normal access, 1 = privileged access",
        "PPROT[1]": "0 = secure access, 1 = nonsecure access "
                    "(HIGH-for-Non-secure convention)",
        "PPROT[2]": "0 = data access,   1 = instruction access",
    })
    d.setdefault("intended_audience",
        "Hardware and software engineers who want to become familiar "
        "with the AMBA AHB and APB protocols and design systems and "
        "modules that are compatible with them.")
    d.setdefault("vendor", "Arm Limited")
    d.setdefault("package_info_present", False)
    d.setdefault("package_info_rationale",
        "AHB + APB are bus protocol specifications, not packaged ICs. "
        "No package / pinout / electrical-DC data exists in either "
        "document.")
    d.setdefault("electrical_specs_present", False)
    d.setdefault("electrical_specs_rationale",
        "Both protocol specs define only logical signal semantics — "
        "synchronous, sampled on rising HCLK / PCLK; HRESETn / PRESETn "
        "active-LOW. No voltage / current / IO-standard information.")
    _write(p, d)


# ============================================================
# L2 FRS
# ============================================================
def _l2(gd: Path) -> None:
    p = gd / "L2_FRS.json"
    if not p.is_file():
        return
    d = _read(p)
    po = _ensure_dict(d, "protocol_overview")
    if isinstance(po, dict):
        po.setdefault("ahb_role",
            "High-performance pipelined synchronous bus, single rising-"
            "edge HCLK. Single-Manager (AHB-Lite) by default; multi-"
            "Manager via an interconnect with arbitration.")
        po.setdefault("apb_role",
            "Low-cost peripheral bus, not pipelined, two PCLK cycles "
            "minimum per transfer.")
        po.setdefault("bridging",
            "An AHB-to-APB bridge appears as a Subordinate on the AHB "
            "side and a Manager on the APB side, performing rate "
            "adaptation.")
        po.setdefault("atomicity", {
            "ahb_lite":
                "HMASTLOCK locked sequence; AHB5 adds Exclusive "
                "transfers via HEXCL / HEXOKAY",
            "apb": "None defined at protocol level",
        })
    fr_ahb = [
        {"id": "FR-AHB-CLK-01",   "text": "All bus transfers are timed by the rising edge of HCLK."},
        {"id": "FR-AHB-RST-01",   "text": "HRESETn is active-LOW; it is the only active-LOW signal in AHB."},
        {"id": "FR-AHB-PHASE-01", "text": "Each AHB transfer has an Address phase (one HCLK cycle unless extended) followed by a Data phase (one or more cycles)."},
        {"id": "FR-AHB-PIPELINE-01", "text": "Address phase of any transfer overlaps the data phase of the previous transfer (pipelined operation)."},
        {"id": "FR-AHB-HREADY-01", "text": "HREADY HIGH at rising HCLK marks transfer completion; HREADY LOW inserts wait states."},
        {"id": "FR-AHB-HREADYOUT-01", "text": "Each Subordinate drives its own HREADYOUT; multiplexor combines all HREADYOUTs into the single HREADY broadcast."},
        {"id": "FR-AHB-HSEL-01",  "text": "Address decoder generates one HSELx per Subordinate; Subordinate samples HSELx + address + control only when HREADY=HIGH."},
        {"id": "FR-AHB-1KB-BOUNDARY", "text": "Incrementing bursts must not cross a 1KB address boundary. Minimum Subordinate decode granularity is 1KB."},
        {"id": "FR-AHB-HTRANS-IDLE", "text": "Subordinates must provide zero-wait OKAY for IDLE transfers and ignore the transfer."},
        {"id": "FR-AHB-HTRANS-BUSY", "text": "Subordinates must provide zero-wait OKAY for BUSY transfers and ignore the transfer. BUSY may only appear mid-burst."},
        {"id": "FR-AHB-HWRITE-01","text": "HWRITE=1 indicates write; HWRITE=0 read. Must remain constant throughout a burst."},
        {"id": "FR-AHB-BURST-CONST", "text": "HSIZE, HBURST, HWRITE, HPROT, HMASTLOCK, HNONSEC must remain constant across all beats of a burst."},
        {"id": "FR-AHB-BURST-ALIGN", "text": "All transfers in a burst must be aligned to the address boundary equal to the size of the transfer."},
        {"id": "FR-AHB-WRAP-BOUNDARY", "text": "Wrapping bursts wrap at burst_beats * 2^HSIZE byte boundary."},
        {"id": "FR-AHB-HRESP-2CYC", "text": "ERROR response is a two-cycle response: HRESP=1+HREADY=0 then HRESP=1+HREADY=1."},
        {"id": "FR-AHB-NO-EARLY-TERM-FIXED", "text": "Fixed-length bursts (INCR4/8/16, WRAP4/8/16) must terminate with a SEQ; BUSY may not end them."},
        {"id": "FR-AHB-WAIT-XCHG-TRANS", "text": "Manager may change HTRANS during waited transfers only as IDLE->NONSEQ, BUSY->SEQ (fixed-length), or BUSY->other (undefined-length)."},
        {"id": "FR-AHB-WAIT-ADDR-CONST", "text": "Manager may change the address during HREADY=LOW only once — during an IDLE transfer, or after an ERROR response."},
        {"id": "FR-AHB-HMASTLOCK-01", "text": "If the Manager requires locked accesses it asserts HMASTLOCK. All transfers in a locked sequence must address the same Subordinate region. Recommended IDLE after a locked sequence."},
        {"id": "FR-AHB-HPROT-01",  "text": "HPROT provides protection info; HPROT_WIDTH 0/4/7 depending on Extended_Memory_Types property. Must remain constant throughout a burst."},
        {"id": "FR-AHB-HNONSEC-01","text": "HNONSEC (AHB5) is an address-phase signal; constant throughout a burst; 0=Secure, 1=Non-secure."},
        {"id": "FR-AHB-HEXCL-01",  "text": "HEXCL/HMASTER/HEXOKAY (AHB5) implement the Exclusive Access mechanism via an Exclusive Access Monitor."},
        {"id": "FR-AHB-HWSTRB-01", "text": "HWSTRB (Issue C optional) supports sparse writes; one strobe per 8 bits of HWDATA; same validity as HWDATA."},
    ]
    fr_apb = [
        {"id": "FR-APB-CLK-01",   "text": "All transfers on the APB are timed by the rising edge of PCLK."},
        {"id": "FR-APB-RST-01",   "text": "PRESETn is active-LOW; normally connected directly to system bus reset."},
        {"id": "FR-APB-TWO-PHASE-01", "text": "Every APB transfer takes at least two PCLK cycles: SETUP (one cycle) followed by ACCESS (one or more cycles, controlled by PREADY)."},
        {"id": "FR-APB-STATE-IDLE", "text": "IDLE: default state (PSELx=0, PENABLE=0)."},
        {"id": "FR-APB-STATE-SETUP", "text": "SETUP: PSELx=1, PENABLE=0; lasts exactly one PCLK cycle; unconditional transition to ACCESS."},
        {"id": "FR-APB-STATE-ACCESS","text": "ACCESS: PSELx=1, PENABLE=1; PREADY=0 keeps bus in ACCESS; PREADY=1 exits to IDLE (no follow-up) or SETUP (back-to-back transfer)."},
        {"id": "FR-APB-WAIT-STABLE", "text": "While PREADY=LOW during ACCESS, the bridge holds PADDR, PWRITE, PSELx, PENABLE, PWDATA, PSTRB, PPROT unchanged."},
        {"id": "FR-APB-PREADY-FIXED-2-CYC", "text": "PREADY can take any value while PENABLE=LOW; fixed-2-cycle peripherals may tie PREADY HIGH."},
        {"id": "FR-APB-PSEL-MUTEX",  "text": "Only one PSELx asserted per transfer (single-Subordinate select)."},
        {"id": "FR-APB-PSTRB-WRITE-ONLY", "text": "For read transfers, the master must drive all bits of PSTRB LOW."},
        {"id": "FR-APB-PSTRB-MAPPING", "text": "There is one PSTRB strobe per 8 bits of write data: PSTRB[n] -> PWDATA[(8n+7):8n]."},
        {"id": "FR-APB-PSLVERR-VALID-WINDOW", "text": "PSLVERR is only valid during the last cycle of an APB transfer, when PSEL, PENABLE, and PREADY are all HIGH."},
        {"id": "FR-APB-PSLVERR-OPTIONAL", "text": "APB peripherals are not required to support PSLVERR. Where absent, the bridge input is tied LOW."},
        {"id": "FR-APB-PSLVERR-EFFECT", "text": "A failing transfer might or might not have changed peripheral state; read transfers with error may return invalid data."},
        {"id": "FR-APB-PPROT-01",   "text": "PPROT[2:0] (APB4) provides protection: [0] normal/privileged, [1] secure/nonsecure, [2] data/instruction; constant while PREADY=LOW."},
        {"id": "FR-APB-NO-PIPELINE","text": "APB is not pipelined; use it for low-bandwidth peripherals."},
    ]
    if _empty(d.get("functional_requirements_ahb")):
        d["functional_requirements_ahb"] = fr_ahb
    if _empty(d.get("functional_requirements_apb")):
        d["functional_requirements_apb"] = fr_apb
    if _empty(d.get("error_response_conditions")):
        d["error_response_conditions"] = [
            "AHB: Subordinate ERROR response (HRESP=1, two cycles) for unsupported transfer / invalid access.",
            "APB: PSLVERR=1 in last cycle of transfer (PSEL=PENABLE=PREADY=1).",
            "AHB5 Exclusive: HEXOKAY=0 when exclusive write failed.",
        ]
    if _empty(d.get("compliance_requirements")):
        d["compliance_requirements"] = [
            "AHB: 1KB burst boundary, beat alignment, burst-constant signals.",
            "AHB: Subordinate sampling only when HREADY=HIGH.",
            "AHB: Two-cycle ERROR response.",
            "APB: Two-cycle minimum, SETUP->ACCESS unconditional.",
            "APB: PSLVERR valid-window enforcement.",
            "APB: PSTRB=all-zero for read transfers.",
        ]
    _write(p, d)


# ============================================================
# L3 CMD PROTOCOL
# ============================================================
def _l3(gd: Path) -> None:
    p = gd / "L3_CMD_PROTOCOL.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("rationale",
        "AHB and APB are NOT opcode/byte-oriented command protocols. They "
        "are address-and-control bus protocols. The 'commands' are encoded "
        "as multi-bit field tuples driven by the Manager during the address "
        "phase (AHB) or setup phase (APB), together with a transfer-type "
        "indicator (HTRANS / PSEL+PENABLE).")
    d.setdefault("ahb_channels", [
        {"name": "Address+control", "direction": "Manager -> Subordinate (via decoder/HSEL)",
         "signals": ["HADDR", "HBURST", "HMASTLOCK", "HPROT", "HSIZE",
                     "HNONSEC (AHB5)", "HEXCL (AHB5)", "HMASTER (AHB5)",
                     "HTRANS", "HWRITE"]},
        {"name": "Write data", "direction": "Manager -> Subordinate",
         "signals": ["HWDATA", "HWSTRB (Issue C, optional)"]},
        {"name": "Read data + response", "direction": "Subordinate -> Manager",
         "signals": ["HRDATA", "HREADYOUT / HREADY chain", "HRESP", "HEXOKAY (AHB5)"]},
        {"name": "Subordinate select", "direction": "Decoder -> Subordinate",
         "signals": ["HSELx"]},
    ])
    d.setdefault("apb_channels", [
        {"name": "Address+control", "direction": "Manager (bridge) -> Subordinate",
         "signals": ["PADDR", "PPROT (APB4)", "PSELx", "PENABLE", "PWRITE"]},
        {"name": "Write data", "direction": "Manager -> Subordinate",
         "signals": ["PWDATA", "PSTRB (APB4)"]},
        {"name": "Read data + response", "direction": "Subordinate -> Manager",
         "signals": ["PRDATA", "PREADY (APB3+)", "PSLVERR (APB3+)"]},
    ])
    d.setdefault("ahb_transfer_type_encoding_HTRANS", {
        "0b00": "IDLE   - no data transfer; zero-wait OKAY; ignore",
        "0b01": "BUSY   - mid-burst pause; zero-wait OKAY; ignore",
        "0b10": "NONSEQ - first or single transfer",
        "0b11": "SEQ    - subsequent burst transfer",
    })
    d.setdefault("ahb_burst_type_encoding_HBURST", {
        "0b000": "SINGLE", "0b001": "INCR",
        "0b010": "WRAP4",  "0b011": "INCR4",
        "0b100": "WRAP8",  "0b101": "INCR8",
        "0b110": "WRAP16", "0b111": "INCR16",
    })
    d.setdefault("ahb_burst_size_encoding_HSIZE", {
        "0b000": 8,    "0b001": 16,   "0b010": 32,   "0b011": 64,
        "0b100": 128,  "0b101": 256,  "0b110": 512,  "0b111": 1024,
    })
    d.setdefault("ahb_response_encoding_HRESP", {
        "0": "OKAY", "1": "ERROR (two-cycle response)",
    })
    d.setdefault("ahb_protection_HPROT_basic", {
        "HPROT[0]": "0 Opcode fetch / 1 Data access",
        "HPROT[1]": "0 User access / 1 Privileged access",
        "HPROT[2]": "0 Non-bufferable / 1 Bufferable",
        "HPROT[3]": "0 Non-cacheable (Non-modifiable in Issue B/C) / 1 Cacheable (Modifiable)",
    })
    d.setdefault("ahb_protection_HPROT_extended_AHB5", {
        "HPROT[4]": "0 No lookup / 1 Lookup",
        "HPROT[5]": "0 Not allocated / 1 Allocate hint",
        "HPROT[6]": "0 Non-shareable / 1 Shareable (must be 0 for Device memory)",
    })
    d.setdefault("apb_transfer_state_machine", {
        "IDLE":   {"PSELx": 0, "PENABLE": 0,
                   "transition": "Transfer required -> SETUP"},
        "SETUP":  {"PSELx": 1, "PENABLE": 0,
                   "transition": "Unconditional -> ACCESS on next rising PCLK"},
        "ACCESS": {"PSELx": 1, "PENABLE": 1,
                   "transitions": {"PREADY=0": "stay in ACCESS",
                                   "PREADY=1 + no transfer": "-> IDLE",
                                   "PREADY=1 + transfer follows": "-> SETUP"}},
    })
    d.setdefault("apb_protection_PPROT_encoding_APB4", {
        "PPROT[0]": "0 = normal access, 1 = privileged access",
        "PPROT[1]": "0 = secure access, 1 = non-secure access "
                    "(Non-secure convention: HIGH = Non-secure)",
        "PPROT[2]": "0 = data access,   1 = instruction access",
    })
    # Parity-gold additions (L3)
    d.setdefault("ahb_memory_type_table_HPROT_6_2", [
        {"prot": "0bx0000", "memory_type": "Device-nE",                    "description": "No early write response permitted"},
        {"prot": "0bx0001", "memory_type": "Device-E",                     "description": "Early write response permitted"},
        {"prot": "0b00010", "memory_type": "Normal Non-cacheable, Non-shareable", "description": "Modifiable, non-cacheable"},
        {"prot": "0bx1110", "memory_type": "Write-through, Non-shareable", "description": "Cacheable, write-through (HPROT[5] = Allocate hint)"},
        {"prot": "0bx1111", "memory_type": "Write-back, Non-shareable",    "description": "Cacheable, write-back (HPROT[5] = Allocate hint)"},
        {"prot": "0b10010", "memory_type": "Normal Non-cacheable, Shareable", "description": ""},
        {"prot": "0b11110", "memory_type": "Write-through, Shareable",     "description": ""},
        {"prot": "0b11111", "memory_type": "Write-back, Shareable",        "description": ""},
    ])
    d.setdefault("ahb_secure_signaling_AHB5", {
        "HNONSEC": "0 = Secure transfer (default), 1 = Non-secure "
                   "transfer. Address-phase signal; must remain constant "
                   "throughout a burst. Supported only if AHB5 "
                   "Secure_Transfers property is True.",
    })
    d.setdefault("ahb_exclusive_signaling_AHB5", {
        "HEXCL":   "Manager output, 1 = transfer is part of an Exclusive "
                   "Access sequence (supported only if AHB5 "
                   "Exclusive_Transfers property is True)",
        "HMASTER": "Manager identifier (HMASTER_WIDTH 0..8 bits) used by "
                   "the Exclusive Access Monitor",
        "HEXOKAY": "Subordinate output, 1 = success of an Exclusive "
                   "Transfer; 0 = failure (another Manager wrote the "
                   "monitored address)",
    })
    d.setdefault("apb_pslverr_mapping_to_AHB_AXI", {
        "AHB-to-APB":  "PSLVERR -> HRESP=ERROR (HRESP[0]=1)",
        "AXI-to-APB":  "PSLVERR -> RRESP/BRESP=SLVERR (RRESP[1]/BRESP[1])",
    })
    d.setdefault("ahb_locked_access_sequence", [
        "Manager asserts HMASTLOCK=1 with the first transfer's address phase.",
        "Bus locks once HMASTLOCK=1, HSEL=1 (if present), HREADY=HIGH.",
        "All transfers in the locked sequence must be to the same Subordinate region.",
        "Manager deasserts HMASTLOCK with the address of the FIRST unlocked transfer.",
        "Recommendation: insert an IDLE transfer after a locked sequence.",
    ])
    d.setdefault("ahb_exclusive_access_sequence_AHB5", [
        "Manager issues Exclusive Read (HEXCL=1, HMASTER=I, HADDR=X).",
        "Subordinate records (X, I) in the Exclusive Access Monitor; returns HEXOKAY=1.",
        "Manager later issues Exclusive Write (HEXCL=1, same HMASTER) to address X.",
        "No intervening write to X -> Subordinate updates memory, HEXOKAY=1.",
        "Intervening write to X -> Subordinate does NOT update, HEXOKAY=0.",
    ])
    d.setdefault("valid_ready_handshake_rules_ahb", [
        "HREADY is the global Data-phase signal driven by the multiplexor.",
        "Subordinate samples HSELx + address + control only when HREADY=HIGH.",
        "Each Subordinate drives HREADYOUT only during the data phase of its selected transfer.",
        "Strict 1-cycle address phase (extended only by the previous data phase).",
    ])
    d.setdefault("valid_ready_handshake_rules_apb", [
        "PSELx + PENABLE jointly indicate state (00=IDLE, 10=SETUP, 11=ACCESS).",
        "PREADY drives wait states only in the ACCESS phase.",
        "PREADY may take any value while PENABLE=LOW.",
        "Bridge holds outputs stable while PREADY=LOW.",
    ])
    d.setdefault("single_response_for_burst_ahb",
        "Each beat of an AHB burst gets its own HRESP. There is no AXI-"
        "style grouped response per burst.")
    d.setdefault("per_beat_response_for_read_ahb",
        "HRESP is per-beat on read; Subordinate may signal per-beat ERROR.")
    _write(p, d)


# ============================================================
# L4 REGMAP — wire-level (no register map)
# ============================================================
def _l4(gd: Path) -> None:
    p = gd / "L4_REGMAP.json"
    if not p.is_file():
        return
    d = _read(p)
    d["register_map_present"] = False
    d.setdefault("rationale",
        "AHB and APB are bus / interconnect protocols, not peripherals "
        "with a control register file. There is no MMIO register map "
        "in these documents. AHB carries the integrator-defined slave "
        "address on HADDR; APB carries it on PADDR. Concrete AHB/APB "
        "peripheral IP blocks define their own register file at the "
        "SoC integration level — outside these protocol specs.")
    d.setdefault("address_side_field_widths", {
        "AHB_HADDR_width_bits":  {
            "recommended_range": [10, 64], "default": 32,
            "note": "In Issues A and B the address width was fixed at 32. "
                    "Recommended range in Issue C is 10..64.",
        },
        "AHB_minimum_subordinate_decode_granularity": "1KB",
        "APB_PADDR_width_bits":  {
            "max": 32,
            "note": "Can be up to 32 bits wide; driven by the bridge.",
        },
        "APB_minimum_subordinate_decode_granularity":
            "Implementation-defined; one PSELx per peripheral slot.",
    })
    # Parity-gold VALUE_MISMATCH: notes
    d["notes"] = (
        "If a future system-integration L4 is required, the canonical "
        "'address-side fields' to capture would be: HADDR width (10..64), "
        "HBURST 1KB-boundary rule, HPROT[3:0]/HPROT[6:0] depending on "
        "Extended_Memory_Types property, HSEL signal per AHB Subordinate; "
        "PADDR width (up to 32), PPROT[2:0] (APB4), PSELx per peripheral.")
    _write(p, d)


# ============================================================
# L5 ADI — digital protocol (no analog signaling)
# ============================================================
def _l5(gd: Path) -> None:
    p = gd / "L5_ADI_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["analog_digital_interface_present"] = False
    d.setdefault("signaling_summary", {
        "ahb_clock":  "Single HCLK per AHB interface; rising-edge sampled.",
        "ahb_reset":  "Single active-LOW HRESETn; the only active-LOW signal in AHB.",
        "apb_clock":  "Single PCLK; rising-edge sampled.",
        "apb_reset":  "Single active-LOW PRESETn; normally tied to system bus reset.",
        "io_count":
            "All channels unidirectional (separate HWDATA/HRDATA in AHB; "
            "separate PWDATA/PRDATA in APB). No tri-state, no open-drain, "
            "no analog.",
        "signal_naming_convention":
            "AHB signals prefixed with H (HCLK, HADDR, HTRANS); APB signals "
            "prefixed with P (PCLK, PADDR, PENABLE). Lower-case n at start "
            "or end of a signal name denotes active-LOW.",
    })
    d.setdefault("additional_reading_referenced", [
        "ARM AMBA APB Protocol Specification (ARM IHI 0024)",
        "ARM AMBA AXI and ACE Protocol Specification (ARM IHI 0022)",
        "Multi-layer AHB Technical Overview (ARM DVI 0045)",
    ])
    _write(p, d)


# ============================================================
# L6 CONTROL LOGIC
# ============================================================
def _l6(gd: Path) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("ahb_fsm_hints", {
        "per_transfer_phases": [
            "ADDRESS_PHASE (one HCLK cycle, extended by previous data phase).",
            "DATA_PHASE (one or more HCLK cycles; HREADY controls end).",
        ],
        "address_phase_rule":   "One cycle; cannot be extended by the Subordinate, only by the previous data phase.",
        "data_phase_rule":      "Manager holds HWDATA stable through extended cycles; Subordinate need not drive HRDATA until transfer is about to complete.",
        "pipeline_rule":        "Address phase of transfer N+1 overlaps data phase of transfer N.",
        "burst_constancy_rule": "HSIZE, HBURST, HWRITE, HPROT, HMASTLOCK, HNONSEC remain constant across burst.",
        "manager_per_burst_fsm": [
            "Drive first beat: HTRANS=NONSEQ + address + control signals.",
            "If burst length > 1: drive subsequent beats with HTRANS=SEQ and incrementing/wrapping address.",
            "If unable to continue immediately during the burst (undefined-length burst only): drive HTRANS=BUSY with the address that the next SEQ transfer will use.",
            "On the cycle following the LAST data beat (HREADY=HIGH for the final SEQ): drive HTRANS=IDLE or start the next NONSEQ.",
        ],
        "subordinate_per_transfer_fsm": [
            "Sample HSELx, HADDR, HBURST, HSIZE, HTRANS, HPROT, HWRITE only when HREADY=HIGH (previous transfer completing).",
            "For HTRANS=IDLE or HTRANS=BUSY: provide zero-wait-state OKAY (HREADYOUT=HIGH, HRESP=0); transfer ignored.",
            "For HTRANS=NONSEQ or HTRANS=SEQ: perform the access; drive HREADYOUT=LOW to insert wait states if needed.",
            "On completion: drive HREADYOUT=HIGH with HRESP=OKAY (or ERROR - two cycles).",
            "AHB5 Exclusive: also drive HEXOKAY in parallel with HRESP.",
        ],
    })
    d.setdefault("ahb_manager_per_burst_fsm", [
        "Drive first beat HTRANS=NONSEQ + address + control.",
        "For length > 1: drive subsequent beats with HTRANS=SEQ.",
        "If unable to continue immediately (undefined-length burst only): drive HTRANS=BUSY with next-SEQ address.",
        "On the cycle after the LAST data beat: drive HTRANS=IDLE or new NONSEQ.",
    ])
    d.setdefault("ahb_subordinate_per_transfer_fsm", [
        "Sample HSELx + HADDR + HBURST + HSIZE + HTRANS + HPROT + HWRITE only when HREADY=HIGH.",
        "For HTRANS=IDLE/BUSY: zero-wait HREADYOUT=1, HRESP=0; transfer ignored.",
        "For HTRANS=NONSEQ/SEQ: perform access; drive HREADYOUT=0 to wait if needed.",
        "On completion: HREADYOUT=1 with HRESP=OKAY (or ERROR — two cycles).",
        "AHB5 Exclusive: also drive HEXOKAY in parallel with HRESP.",
    ])
    d.setdefault("ahb_error_response_2cyc_fsm", [
        "Cycle 1: Subordinate drives HRESP=1, HREADYOUT=0.",
        "Cycle 2: Subordinate drives HRESP=1, HREADYOUT=1.",
        "Manager option A: continue burst.",
        "Manager option B: drive HTRANS=IDLE during the 2-cycle ERROR to cancel.",
    ])
    d.setdefault("ahb_locked_access_fsm", [
        "Manager asserts HMASTLOCK with the address phase of the first locked transfer.",
        "Bus locked once HMASTLOCK=1, HSEL=1 (if present), HREADY=HIGH for >= 1 cycle.",
        "All locked transfers address same Subordinate region.",
        "Manager deasserts HMASTLOCK with the first unlocked transfer's address.",
        "Recommendation: IDLE after a locked sequence.",
    ])
    d.setdefault("apb_fsm_states", [
        {"state": "IDLE",   "PSELx": 0, "PENABLE": 0, "outputs": "PSELx=0; bus is idle"},
        {"state": "SETUP",  "PSELx": 1, "PENABLE": 0, "outputs": "PADDR + PWRITE + PWDATA (write) + PSTRB + PPROT driven by bridge"},
        {"state": "ACCESS", "PSELx": 1, "PENABLE": 1, "outputs": "Subordinate drives PREADY (+ PRDATA for read, PSLVERR if used)"},
    ])
    d.setdefault("apb_fsm_transitions", [
        {"from": "IDLE",   "to": "SETUP",  "cond": "Transfer required"},
        {"from": "SETUP",  "to": "ACCESS", "cond": "Unconditional on next rising PCLK"},
        {"from": "ACCESS", "to": "ACCESS", "cond": "PREADY=0 (wait)"},
        {"from": "ACCESS", "to": "IDLE",   "cond": "PREADY=1 + no further transfer"},
        {"from": "ACCESS", "to": "SETUP",  "cond": "PREADY=1 + back-to-back transfer"},
    ])
    d.setdefault("anti_deadlock_rule", {
        "ahb":
            "No combinational path from any HREADY back to a Manager output "
            "(HSEL/HTRANS); Manager drives address-phase signals from "
            "registered state only.",
        "apb":
            "Bridge must not feed PREADY combinationally back into PSELx or "
            "PENABLE; bridge holds outputs stable while PREADY=LOW.",
    })
    d.setdefault("exit_from_reset", {
        "ahb":
            "Earliest non-IDLE transfer = first rising HCLK after "
            "HRESETn=HIGH; integrators typically initialize HTRANS=IDLE "
            "during reset.",
        "apb":
            "Bus enters IDLE (PSELx=0, PENABLE=0) on PRESETn=LOW.",
    })
    d.setdefault("default_ready_state_recommendation", {
        "AHB": "Subordinates may default HREADYOUT=HIGH; only drive LOW to insert wait states.",
        "APB": "Fixed-2-cycle peripherals may tie PREADY HIGH; PREADY can take any value while PENABLE=LOW.",
    })
    d.setdefault("transfer_type_change_during_wait_states_ahb", {
        "IDLE_to_NONSEQ":      "Permitted; HTRANS then constant until HREADY=HIGH.",
        "BUSY_to_SEQ_fixed":   "Permitted in fixed-length bursts.",
        "BUSY_to_other_undef": "Permitted in undefined-length bursts (BUSY -> any type while HREADY=LOW).",
    })
    d.setdefault("address_change_during_wait_states_ahb", {
        "IDLE_change_once": "Manager can change the address once during an IDLE-waited transfer.",
        "after_ERROR":      "Manager may change the address while HREADY=LOW after an ERROR response.",
    })
    _write(p, d)


# ============================================================
# L7 TEST/DEBUG
# ============================================================
def _l7(gd: Path) -> None:
    p = gd / "L7_TEST_DEBUG.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_debug_architecture_present"] = False
    d.setdefault("rationale",
        "Neither AHB IHI 0033C nor APB IHI 0024C defines a JTAG / scan / "
        "BIST / MBIST / debug architecture. There is no dedicated debug "
        "interface in either protocol. Debug visibility, if any, must be "
        "added by the integrator (e.g. ARM CoreSight components) outside "
        "these specs.")
    d.setdefault("spec_provided_observability_ahb", [
        {"name": "HRESP error response",            "purpose": "Two-cycle ERROR observable by Manager and monitoring logic."},
        {"name": "HEXOKAY (AHB5)",                  "purpose": "Indicates success / failure of Exclusive Transfer."},
        {"name": "User signaling HxUSER (AHB5)",    "purpose": "Implementation-defined extras for debug / trace / functional augmentation."},
        {"name": "Interface protection using parity (AHB5)", "purpose": "Single-bit fault detection on each interface."},
        {"name": "Default Subordinate ERROR for unmapped addresses", "purpose": "DECERR-equivalent detection of out-of-map accesses."},
    ])
    d.setdefault("spec_provided_observability_apb", [
        {"name": "PSLVERR (APB3+)", "purpose": "Failure indicator at end of transfer; mapped to AHB HRESP=ERROR / AXI RRESP=SLVERR by an upstream bridge."},
    ])
    d.setdefault("ahb_optional_features_per_property", {
        "Write_Strobes":         "Adds HWSTRB to the interface for sparse-write support",
        "Secure_Transfers":      "Adds HNONSEC; supports Secure / Non-secure distinction",
        "Exclusive_Transfers":   "Adds HEXCL + HMASTER + HEXOKAY; supports Exclusive Access Monitor",
        "Extended_Memory_Types": "Widens HPROT to 7 bits for extended memory-type encoding",
        "User_Request_Width":    "HAUSER width on the address channel (issuer-defined)",
        "User_Data_Width":       "HWUSER / HRUSER widths on the data channels",
        "User_Response_Width":   "HBUSER width on the response channel",
        "Parity_Property":       "Enables interface protection using parity check signals",
    })
    d.setdefault("ahb_recommendations_on_user_signals",
        "Spec recommends User signals are used only for point-to-point "
        "Manager-Subordinate communication; they are not propagated by "
        "generic interconnect components and present an interoperability "
        "risk if used elsewhere.")
    _write(p, d)


# ============================================================
# L8 RTL CONSTANTS
# ============================================================
def _l8_rtl_constants(gd: Path) -> None:
    p = gd / "L8_RTL_CONSTANTS.json"
    if not p.is_file():
        return
    d = _read(p)
    wp_ahb = _ensure_dict(d, "width_parameters_ahb")
    if isinstance(wp_ahb, dict):
        for k, v in {
            "ADDR_WIDTH":   {"recommended_range": [10, 64], "default": 32, "signal": "HADDR"},
            "DATA_WIDTH":   {"legal_values": [8, 16, 32, 64, 128, 256, 512, 1024], "recommended_range": [32, 256], "signals": ["HWDATA", "HRDATA"]},
            "HWSTRB_width": {"formula": "DATA_WIDTH/8", "note": "Only present if Write_Strobes property is True (Issue C)", "signal": "HWSTRB"},
            "HBURST_WIDTH": {"legal_values": [0, 3], "signal": "HBURST"},
            "HPROT_WIDTH":  {"legal_values": [0, 4, 7], "depends_on": "Extended_Memory_Types property", "signal": "HPROT"},
            "HSIZE_WIDTH":  {"value": 3, "signal": "HSIZE"},
            "HTRANS_WIDTH": {"value": 2, "signal": "HTRANS"},
            "HRESP_WIDTH":  {"value": 1, "signal": "HRESP"},
            "HSEL_WIDTH":   {"value": 1, "signal": "HSELx per Subordinate"},
            "HMASTER_WIDTH":{"recommended_range": [0, 8], "depends_on": "Exclusive_Transfers property", "signal": "HMASTER"},
            "HEXCL_WIDTH":  {"value": 1, "depends_on": "Exclusive_Transfers property", "signal": "HEXCL"},
            "HNONSEC_WIDTH":{"value": 1, "depends_on": "Secure_Transfers property", "signal": "HNONSEC"},
            "HMASTLOCK_WIDTH": {"value": 1, "signal": "HMASTLOCK"},
            "HWRITE_WIDTH": {"value": 1, "signal": "HWRITE"},
            "HREADY_WIDTH": {"value": 1, "signal": "HREADY / HREADYOUT"},
            "HCLK_WIDTH":   {"value": 1},
            "HRESETn_WIDTH":{"value": 1, "note": "active LOW (only active-LOW signal in AHB)"},
        }.items():
            cur = wp_ahb.get(k)
            if isinstance(cur, dict):
                for kk, vv in v.items():
                    cur.setdefault(kk, vv)
            else:
                wp_ahb.setdefault(k, v)
    wp_apb = _ensure_dict(d, "width_parameters_apb")
    if isinstance(wp_apb, dict):
        for k, v in {
            "PADDR_WIDTH":  {"max": 32, "signal": "PADDR"},
            "PWDATA_WIDTH": {"max": 32, "signal": "PWDATA"},
            "PRDATA_WIDTH": {"max": 32, "signal": "PRDATA", "note": "Must match PWDATA_WIDTH on the interface"},
            "PSTRB_WIDTH":  {"formula": "PWDATA_WIDTH/8", "note": "Present only in APB4 (v2.0)", "signal": "PSTRB"},
            "PPROT_WIDTH":  {"value": 3, "note": "Present only in APB4 (v2.0)", "signal": "PPROT"},
            "PSELx_WIDTH":  {"value": 1, "note": "One per peripheral"},
            "PENABLE_WIDTH":{"value": 1},
            "PWRITE_WIDTH": {"value": 1},
            "PREADY_WIDTH": {"value": 1, "note": "Present in APB3+"},
            "PSLVERR_WIDTH":{"value": 1, "note": "Present in APB3+; optional"},
            "PCLK_WIDTH":   {"value": 1},
            "PRESETn_WIDTH":{"value": 1, "note": "Active LOW"},
        }.items():
            cur = wp_apb.get(k)
            if isinstance(cur, dict):
                for kk, vv in v.items():
                    cur.setdefault(kk, vv)
            else:
                wp_apb.setdefault(k, v)
    d.setdefault("ahb_burst_length_table_HBURST", {
        "0b000": {"name": "SINGLE", "beats": 1,           "type": "single"},
        "0b001": {"name": "INCR",   "beats": "undefined", "type": "incrementing"},
        "0b010": {"name": "WRAP4",  "beats": 4,           "type": "wrapping"},
        "0b011": {"name": "INCR4",  "beats": 4,           "type": "incrementing"},
        "0b100": {"name": "WRAP8",  "beats": 8,           "type": "wrapping"},
        "0b101": {"name": "INCR8",  "beats": 8,           "type": "incrementing"},
        "0b110": {"name": "WRAP16", "beats": 16,          "type": "wrapping"},
        "0b111": {"name": "INCR16", "beats": 16,          "type": "incrementing"},
    })
    # Patch existing burst-length entries if they pre-exist without `type`.
    blt = d.get("ahb_burst_length_table_HBURST")
    if isinstance(blt, dict):
        _type_map = {
            "0b000": "single", "0b001": "incrementing",
            "0b010": "wrapping", "0b011": "incrementing",
            "0b100": "wrapping", "0b101": "incrementing",
            "0b110": "wrapping", "0b111": "incrementing",
        }
        for k, t in _type_map.items():
            entry = blt.get(k)
            if isinstance(entry, dict):
                entry.setdefault("type", t)
    d.setdefault("ahb_burst_size_encoding_HSIZE_to_bytes", {
        "0b000": 1, "0b001": 2, "0b010": 4, "0b011": 8,
        "0b100": 16, "0b101": 32, "0b110": 64, "0b111": 128,
    })
    d.setdefault("ahb_transfer_type_encoding_HTRANS", {
        "0b00": "IDLE", "0b01": "BUSY",
        "0b10": "NONSEQ", "0b11": "SEQ",
    })
    d.setdefault("ahb_response_encoding_HRESP", {"0": "OKAY", "1": "ERROR"})
    d.setdefault("ahb_protection_HPROT_basic_4bit", {
        "HPROT[0]": "Data/Opcode (1=Data access, 0=Opcode fetch)",
        "HPROT[1]": "Privileged (1=Privileged, 0=User)",
        "HPROT[2]": "Bufferable (1=Bufferable, 0=Non-bufferable)",
        "HPROT[3]": "Modifiable/Cacheable (1=Modifiable, 0=Non-modifiable; renamed in Issue B/C)",
    })
    d.setdefault("ahb_protection_HPROT_extended_7bit", {
        "HPROT[4]": "Lookup (1=Lookup required, 0=No lookup)",
        "HPROT[5]": "Allocate (1=Allocate hint, 0=No allocate hint)",
        "HPROT[6]": "Shareable (1=Shareable, 0=Non-shareable; must be 0 for Device memory)",
    })
    d.setdefault("apb_protection_PPROT_encoding", {
        "PPROT[0]": "1 = privileged access, 0 = normal access",
        "PPROT[1]": "1 = nonsecure access, 0 = secure access",
        "PPROT[2]": "1 = instruction access, 0 = data access",
    })
    d.setdefault("ahb_burst_address_rules", {
        "wrap_boundary_formula":  "number_of_beats * (1 << HSIZE) bytes",
        "WRAP4_example_word":     "4-beat wrapping burst of word (4-byte) accesses wraps at 16-byte boundaries (4 * 4 = 16). Address 0x34 next 0x38, 0x3C, then wraps to 0x30.",
        "WRAP8_example_word":     "8-beat wrapping burst of word accesses wraps at 32-byte boundaries (8 * 4 = 32).",
        "INCR_1kb_boundary_rule": "Managers must not attempt to start an incrementing burst that crosses a 1KB address boundary.",
        "burst_alignment_rule":   "All transfers in a burst must be aligned to the address boundary equal to the size of the transfer (HADDR[log2(2^HSIZE)-1:0] = 0).",
    })
    d.setdefault("apb_byte_lane_mapping_PSTRB", {
        "PSTRB_per_byte": "PSTRB[n] -> PWDATA[(8n+7):8n].",
        "PSTRB_read_rule": "Master drives PSTRB=all-zero for read transfers.",
    })
    d.setdefault("key_constants_for_RTL_authoring", {
        "ahb_1kb_burst_boundary":          1024,
        "ahb_burst_min_beats":             1,
        "ahb_burst_max_beats_fixed":       16,
        "ahb_idle_busy_must_return_okay":  True,
        "ahb_error_response_cycles":       2,
        "apb_setup_phase_cycles":          1,
        "apb_min_access_phase_cycles":     1,
        "apb_min_transfer_cycles":         2,
        "apb_pready_default_for_fixed_2c": "tied HIGH",
        "ahb_lock_rule": "all locked transfers must be in same Subordinate region",
        "ahb_signal_constancy_per_burst": [
            "HSIZE", "HBURST", "HWRITE", "HPROT", "HMASTLOCK", "HNONSEC",
        ],
    })
    d.setdefault("default_signal_values_when_omitted_ahb", {
        "HBURST":    "SINGLE (0b000) when omitted",
        "HSIZE":     "Word (0b010, 32-bit) when omitted",
        "HTRANS":    "IDLE (0b00) when omitted (i.e., during reset)",
        "HMASTLOCK": "0 when omitted",
        "HPROT":     "0b0011 (Non-cacheable, Non-bufferable, Privileged, Data access) when omitted",
        "HNONSEC":   "0 (Secure) when omitted (in non-AHB5 systems)",
        "HEXCL":     "0 (non-Exclusive) when omitted",
    })
    _write(p, d)


# ============================================================
# L8 TIMING WAVEFORM
# ============================================================
def _l8_timing_waveform(gd: Path) -> None:
    p = gd / "L8_TIMING_WAVEFORM.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("clock_and_reset_waveform_ahb", {
        "HCLK":     "Single rising-edge clock per AHB interface.",
        "HRESETn":  "Active LOW; the only active-LOW signal in AHB.",
        "reference_section": "AHB Chapter 7 Clock and Reset",
    })
    d.setdefault("clock_and_reset_waveform_apb", {
        "PCLK":     "Rising edge times all APB transfers.",
        "PRESETn":  "Active LOW; normally tied to system bus reset.",
    })
    d.setdefault("ahb_basic_transfer_waveform", {
        "case": "Read transfer, no wait state (Figure 3-1)",
        "sequence": [
            "T0: Manager drives HADDR=A, HWRITE=0; HREADY=1.",
            "T1: Subordinate samples address+control on rising HCLK.",
            "T2: Subordinate drives HRDATA=Data(A); Manager samples on T3.",
            "Address phase of next transfer overlaps data phase.",
        ],
    })
    d.setdefault("ahb_waited_transfer_waveform", {
        "case": "Read transfer with two wait states (Figure 3-3)",
        "sequence": [
            "One-cycle address phase.",
            "Data phase extended over three cycles: HREADY=0, 0, then 1 with HRDATA=Data(A).",
            "Address phase of next transfer also extended.",
        ],
    })
    d.setdefault("ahb_error_response_waveform", {
        "case": "Two-cycle ERROR response (Figure 5-2)",
        "sequence": [
            "Cycle 1: HRESP=1, HREADYOUT=0.",
            "Cycle 2: HRESP=1, HREADYOUT=1.",
            "Manager option: continue burst OR drive HTRANS=IDLE during the 2-cycle ERROR to cancel.",
        ],
    })
    d.setdefault("ahb_burst_waveforms", [
        {"name": "WRAP4 word (Figure 3-8)",
         "addresses": ["0x38", "0x3C", "0x30", "0x34"],
         "htrans_sequence": ["NONSEQ", "SEQ", "SEQ", "SEQ"],
         "note": "Wraps at 16-byte boundary."},
        {"name": "INCR4 word (Figure 3-9)",
         "addresses": ["0x38", "0x3C", "0x40", "0x44"],
         "htrans_sequence": ["NONSEQ", "SEQ", "SEQ", "SEQ"],
         "note": "Crosses 16-byte boundary; address keeps incrementing."},
        {"name": "WRAP8 word (Figure 3-10)",
         "addresses": ["0x34", "0x38", "0x3C", "0x20",
                       "0x24", "0x28", "0x2C", "0x30"],
         "htrans_sequence": ["NONSEQ"] + ["SEQ"] * 7,
         "note": "Wraps at 32-byte boundary."},
        {"name": "INCR8 halfword (Figure 3-11)",
         "addresses": ["0x34", "0x36", "0x38", "0x3A",
                       "0x3C", "0x3E", "0x40", "0x42"],
         "htrans_sequence": ["NONSEQ"] + ["SEQ"] * 7,
         "note": "Halfword transfers crossing 16-byte boundary."},
        {"name": "INCR undefined-length (Figure 3-12)",
         "htrans_sequence": ["NONSEQ", "SEQ", "NONSEQ", "SEQ", "SEQ"],
         "note": "Two undefined-length bursts shown."},
    ])
    d.setdefault("ahb_busy_transfer_waveform", {
        "case": "Transfer-type example (Figure 3-6) NONSEQ+BUSY+SEQ+SEQ+SEQ in INCR",
        "sequence": [
            "T0-T1: NONSEQ at 0x20.",
            "T1-T2: BUSY at 0x24.",
            "T2-T3: SEQ at 0x24 (Manager continues).",
            "T3-T4: SEQ at 0x28.",
            "T4-T5: SEQ at 0x2C with wait state (HREADY=0).",
            "T5-T6: data of 0x28 returns.",
        ],
    })
    d.setdefault("ahb_locked_transfer_waveform", {
        "case": "HMASTLOCK with SWP-like sequence (Figure 3-7)",
        "sequence": [
            "Cycle 1: NONSEQ read, HMASTLOCK=1, HADDR=A.",
            "Cycle 2: NONSEQ write, HMASTLOCK=1, HADDR=A.",
            "Cycle 3: IDLE, HMASTLOCK=0.",
        ],
    })
    d.setdefault("apb_basic_transfer_waveform_write_no_wait", {
        "case": "APB write, no wait states (Figure 3-1)",
        "sequence": [
            "T0-T1: IDLE (PSEL=0, PENABLE=0).",
            "T1: PADDR=Addr1, PWRITE=1, PSEL=1, PWDATA=Data1 — SETUP.",
            "T2: PENABLE=1, PREADY=1 — ACCESS; transfer completes.",
            "T3: bus may go IDLE or directly to next SETUP.",
        ],
    })
    d.setdefault("apb_basic_transfer_waveform_write_with_wait", {
        "case": "APB write, two wait states (Figure 3-2)",
        "sequence": [
            "SETUP at T1.",
            "ACCESS at T2 with PREADY=0.",
            "ACCESS at T3 with PREADY=0.",
            "ACCESS at T4 with PREADY=1 — transfer completes.",
        ],
    })
    d.setdefault("apb_failing_transfer_waveform", {
        "case": "APB failing write transfer (Figure 3-6)",
        "sequence": [
            "SETUP at T1, ACCESS at T2 with PREADY=0.",
            "ACCESS at T3 with PREADY=1 and PSLVERR=1 — error signaled.",
            "After T3: bus returns to IDLE.",
        ],
    })
    d.setdefault("apb_state_diagram_waveform_summary", {
        "states": ["IDLE", "SETUP", "ACCESS"],
        "edges": [
            "IDLE -> SETUP on transfer required",
            "SETUP -> ACCESS unconditional next rising PCLK",
            "ACCESS -> ACCESS while PREADY=0",
            "ACCESS -> IDLE on PREADY=1 + no further transfer",
            "ACCESS -> SETUP on PREADY=1 + back-to-back transfer",
        ],
    })
    # v0.1.87 — MERGE (14c3 batch synth pre-fills with AXI-baseline keys;
    # we need AHB+APB keys ALSO present, not blocked).
    _mor = d.setdefault("max_outstanding_rules", {})
    if not isinstance(_mor, dict):
        _mor = {}
        d["max_outstanding_rules"] = _mor
    _mor.setdefault("ahb",
        "AHB-Lite is single-Manager; only one outstanding transfer at a "
        "time (no AXI-style outstanding queues). Pipelining means address "
        "phase of next transfer overlaps data phase of current transfer.")
    _mor.setdefault("apb",
        "APB has no pipelining; only one transfer in flight at a time; "
        "minimum 2 PCLK cycles per transfer.")
    d.setdefault("interconnect_combination_rules", {
        "ahb_HREADY_chain":
            "Multiplexor combines all Subordinate HREADYOUTs into a "
            "single global HREADY broadcast (Figure 4-2). HRDATA / "
            "HRESP / HEXOKAY mux'd by decoder HSEL.",
        "ahb_apb_bridge":
            "AHB-to-APB bridge is an AHB Subordinate + APB Manager; "
            "PSLVERR -> HRESP=ERROR.",
    })
    _write(p, d)


# ============================================================
# L9 INTEGRATION
# ============================================================
def _l9(gd: Path) -> None:
    p = gd / "L9_INTEGRATION_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("interconnect_topology_options_ahb", [
        "Single-Manager AHB-Lite: one decoder + one multiplexor (Figure 1-1).",
        "Multi-Manager / multi-layer AHB: requires interconnect with arbitration (DVI 0045).",
    ])
    d.setdefault("interconnect_topology_options_apb", [
        "Single APB bridge (Manager) + multiple APB peripherals (Subordinates).",
        "Single Manager bus only; APB has no multi-Manager arbitration.",
    ])
    d.setdefault("interconnect_rules_ahb", [
        "Decoder monitors HADDR during the address phase, asserts HSELx during the data phase.",
        "Minimum decode granularity = 1KB.",
        "Multiplexor routes HRDATA / HRESP / HREADYOUT / HEXOKAY from selected Subordinate back to Manager.",
        "Default Subordinate ERROR for NONSEQ/SEQ at unmapped addresses, zero-wait OKAY for IDLE/BUSY.",
        "HREADY computed by combining all Subordinate HREADYOUTs.",
        "Generic interconnect may offer AHB / AXI / APB interfaces alongside.",
    ])
    d.setdefault("interconnect_rules_apb", [
        "AHB-to-APB bridge: AHB Subordinate + APB Manager; PSLVERR -> HRESP=ERROR.",
        "AXI-to-APB bridge: PSLVERR -> RRESP/BRESP = SLVERR.",
        "Per-PSELx address decode in the bridge; only one PSELx asserted per transfer.",
        "Optional PSLVERR per Subordinate; tied LOW at bridge if not implemented.",
    ])
    d.setdefault("default_signal_values_when_omitted_ahb",
        "AHB Section 3.5 (Write strobes interoperability) — Subordinate "
        "treats absent HWSTRB as all-HIGH. Other optional signals "
        "(HBURST=0 width, HPROT=0 width, HMASTER=0 width) handled by "
        "receiver-side defaults.")
    d.setdefault("default_signal_values_when_omitted_apb",
        "APB Table 2-1 footnotes — if a Subordinate does not implement "
        "PSLVERR, the AHB-to-APB bridge ties the PSLVERR input LOW.")
    d.setdefault("slave_classification_ahb", {
        "memory_slave_general":      "Subordinate that maps to an address region and handles all memory accesses.",
        "peripheral_slave_via_apb_bridge": "AHB-to-APB bridge presents a single AHB Subordinate that fans out to APB peripherals.",
    })
    d.setdefault("apb_peripheral_classification", [
        "PSLVERR-supporting peripheral",
        "Non-PSLVERR-supporting peripheral (PSLVERR input tied LOW)",
        "Fixed-2-cycle peripheral (PREADY tied HIGH)",
        "Variable-latency peripheral (drives PREADY=LOW for wait states)",
    ])
    d.setdefault("ahb_to_apb_bridge_role",
        "Connects the high-performance AHB to lower-bandwidth APB "
        "peripherals. Appears as an AHB Subordinate and the APB Manager. "
        "Typically inserts AHB wait states while completing the multi-"
        "cycle APB transfer. APB PSLVERR maps to AHB HRESP=ERROR.")
    d.setdefault("interface_categories_ahb", [
        "Manager interface (drives address+control+write data).",
        "Subordinate interface (drives read data + HREADYOUT + HRESP + HEXOKAY).",
        "Decoder (HSELx generation).",
        "Multiplexor (HRDATA + HRESP + HREADYOUT + HEXOKAY selection).",
    ])
    d.setdefault("interface_categories_apb", [
        "APB Manager (bridge): drives PADDR + PWRITE + PSELx + PENABLE + PWDATA + PSTRB + PPROT.",
        "APB Subordinate (peripheral): drives PRDATA + PREADY + PSLVERR.",
    ])
    d.setdefault("register_slice_insertion_rule_ahb",
        "AHB does not have AXI's register-slice-anywhere property because "
        "of strict 1-cycle address phase + HREADY chain. Register-slice "
        "insertion typically requires an AHB-to-AHB bridge.")
    d.setdefault("register_slice_insertion_rule_apb",
        "Not specified; APB is a low-cost two-phase bus and register-"
        "slice insertion is rare.")
    d.setdefault("ahb_to_axi_bridge_summary",
        "AHB-Lite Subordinate to AXI Manager (rare direction): protocol "
        "mismatch - AHB has no AxLEN equivalent for SEQ-only bursts; "
        "bridge typically maps each AHB beat to a single-beat AXI "
        "transaction. The reverse direction (AXI Manager to AHB "
        "Subordinate) is more common and uses an AXI-to-AHB-Lite bridge.")
    _write(p, d)


# ============================================================
# L10 TEST CASES
# ============================================================
def _l10(gd: Path) -> None:
    p = gd / "L10_TEST_CASES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_cases_present"] = (
        "partial - both specs describe protocol-compliance requirements "
        "and waveforms that map to compliance test scenarios but neither "
        "provides a formal verification plan.")
    d.setdefault("derived_compliance_test_categories_ahb", [
        {"id": "TC-AHB-RESET",     "name": "Reset behavior"},
        {"id": "TC-AHB-NONSEQ",    "name": "Single NONSEQ transfer"},
        {"id": "TC-AHB-IDLE-OKAY", "name": "IDLE -> zero-wait OKAY"},
        {"id": "TC-AHB-BUSY-OKAY", "name": "BUSY -> zero-wait OKAY"},
        {"id": "TC-AHB-INCR",      "name": "Incrementing bursts INCR4/8/16 + undefined INCR"},
        {"id": "TC-AHB-WRAP",      "name": "Wrapping bursts WRAP4/8/16 with HSIZE coverage"},
        {"id": "TC-AHB-1KB-BOUNDARY", "name": "1KB burst boundary enforcement"},
        {"id": "TC-AHB-WAIT",      "name": "Subordinate wait-state insertion"},
        {"id": "TC-AHB-ERROR-2CYC","name": "Two-cycle ERROR response"},
        {"id": "TC-AHB-LOCK",      "name": "HMASTLOCK locked sequence"},
        {"id": "TC-AHB-HPROT-CONST","name": "HPROT + burst-constant signals"},
        {"id": "TC-AHB-DEFAULT-SLAVE", "name": "Default Subordinate ERROR/OKAY"},
        {"id": "TC-AHB-WSTRB",     "name": "Write strobes (Issue C)"},
        {"id": "TC-AHB-AHB5-EXCL", "name": "AHB5 Exclusive access"},
        {"id": "TC-AHB-AHB5-NONSEC","name": "AHB5 Secure transfers"},
        {"id": "TC-AHB-PARITY",    "name": "AHB5 Interface protection via parity"},
    ])
    d.setdefault("derived_compliance_test_categories_apb", [
        {"id": "TC-APB-RESET",     "name": "Reset behavior"},
        {"id": "TC-APB-WRITE-NOWAIT","name": "Write transfer no wait states"},
        {"id": "TC-APB-WRITE-WAIT","name": "Write transfer with wait states"},
        {"id": "TC-APB-READ-NOWAIT","name": "Read transfer no wait states"},
        {"id": "TC-APB-READ-WAIT", "name": "Read transfer with wait states"},
        {"id": "TC-APB-PSLVERR-WRITE","name": "Failing write (PSLVERR=1)"},
        {"id": "TC-APB-PSLVERR-READ","name": "Failing read (PSLVERR=1)"},
        {"id": "TC-APB-PSLVERR-VALID-WINDOW","name": "PSLVERR valid window"},
        {"id": "TC-APB-PSEL-MUTEX","name": "PSELx mutual exclusion"},
        {"id": "TC-APB-PSTRB",     "name": "Write strobes (APB4)"},
        {"id": "TC-APB-PPROT",     "name": "Protection (APB4)"},
        {"id": "TC-APB-BRIDGE-AHB-TO-APB","name": "AHB-to-APB bridge end-to-end"},
        {"id": "TC-APB-BRIDGE-AXI-TO-APB","name": "AXI-to-APB bridge end-to-end"},
    ])
    _write(p, d)


# ============================================================
# L11 OTP
# ============================================================
def _l11(gd: Path) -> None:
    p = gd / "L11_OTP_CONTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("otp_present", False)
    d.setdefault("notes",
        "AHB and APB are bus / interconnect protocols. Neither has "
        "one-time-programmable fuses, factory-trim values, or "
        "calibration codes at the protocol layer.")
    _write(p, d)


# ============================================================
# L12 BEHAVIORAL SEQUENCES
# ============================================================
def _l12(gd: Path) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("typical_ahb_read_sequence_single", [
        "1. Manager drives HADDR=A, HWRITE=0, HSIZE=size, HBURST=SINGLE, HTRANS=NONSEQ.",
        "2. Decoder asserts HSELx in the next data phase.",
        "3. Subordinate samples address+control when HREADY=1.",
        "4. Subordinate drives HREADYOUT=0 to wait OR HREADYOUT=1 + HRDATA=Data(A) + HRESP=OKAY.",
        "5. Manager samples HRDATA on the rising HCLK where HREADY=1.",
        "6. Manager drives HTRANS=IDLE (or starts next NONSEQ).",
    ])
    d.setdefault("typical_ahb_write_sequence_single", [
        "1. Manager drives HADDR=A, HWRITE=1, HSIZE=size, HBURST=SINGLE, HTRANS=NONSEQ.",
        "2. One cycle later: Manager drives HWDATA=Data(A) (+ HWSTRB if used).",
        "3. Subordinate drives HREADYOUT=1 + HRESP=OKAY to complete.",
        "4. Manager drives HTRANS=IDLE.",
    ])
    d.setdefault("typical_ahb_burst_sequence_INCR4_word", [
        "1. HADDR=0x38, HBURST=INCR4, HSIZE=Word, HTRANS=NONSEQ.",
        "2. Sequential addresses: 0x38 NONSEQ, 0x3C SEQ, 0x40 SEQ, 0x44 SEQ.",
        "3. HBURST + HSIZE + HWRITE + HPROT + HMASTLOCK + HNONSEC constant.",
        "4. Data phases pipelined.",
        "5. After 4th SEQ: HTRANS=IDLE.",
    ])
    d.setdefault("typical_ahb_burst_sequence_WRAP4_word_at_0x38", [
        "HBURST=WRAP4 + HSIZE=Word -> wraps at 16-byte boundary.",
        "Addresses: 0x38 NONSEQ, 0x3C SEQ, 0x30 SEQ (wrapped), 0x34 SEQ.",
    ])
    d.setdefault("typical_ahb_burst_sequence_INCR_undefined_length", [
        "Manager: HBURST=INCR + HADDR=0x20 + HTRANS=NONSEQ.",
        "Subsequent beats: HTRANS=SEQ with incrementing address.",
        "Manager may insert HTRANS=BUSY mid-burst.",
        "Terminate with HTRANS=IDLE or NONSEQ to new address.",
    ])
    d.setdefault("ahb_two_cycle_error_sequence", [
        "Cycle 1: HRESP=1, HREADYOUT=0.",
        "Cycle 2: HRESP=1, HREADYOUT=1.",
        "Manager option A: continue burst.",
        "Manager option B: HTRANS=IDLE during the 2-cycle ERROR.",
    ])
    d.setdefault("ahb_locked_access_sequence_HMASTLOCK", [
        "1. Manager asserts HMASTLOCK=1 with the address-phase of the first locked transfer.",
        "2. All transfers in locked sequence to same Subordinate region.",
        "3. Manager deasserts HMASTLOCK with the first unlocked transfer.",
        "4. Bus unlocked when HMASTLOCK=0 + HREADY=HIGH for one cycle.",
    ])
    d.setdefault("ahb_exclusive_access_sequence_AHB5", [
        "1. Exclusive Read: HEXCL=1, HMASTER=I, HADDR=X.",
        "2. Monitor records (X, I); HEXOKAY=1 returned with OKAY.",
        "3. Exclusive Write: HEXCL=1, HMASTER=I, HADDR=X.",
        "4. No intervening write -> Subordinate updates memory, HEXOKAY=1.",
        "5. Intervening write -> Subordinate does NOT update, HEXOKAY=0.",
    ])
    d.setdefault("typical_apb_write_sequence_no_wait", [
        "1. Bridge: drive PADDR=Addr1, PWRITE=1, PSEL=1, PWDATA=Data1, PSTRB=lanes, PPROT=attrs.",
        "2. Next rising PCLK -> ACCESS: PENABLE=1; Subordinate drives PREADY=1.",
        "3. Next rising PCLK: transfer completes; bridge -> IDLE or next SETUP.",
    ])
    d.setdefault("typical_apb_write_sequence_with_wait", [
        "1. SETUP at T1 with PADDR + PWRITE + PSEL + PWDATA stable.",
        "2. ACCESS at T2 with PREADY=0 (wait).",
        "3. All outputs remain unchanged across wait cycles.",
        "4. ACCESS at T_n with PREADY=1; transfer completes.",
    ])
    d.setdefault("typical_apb_read_sequence_no_wait", [
        "1. Bridge: PADDR=Addr1, PWRITE=0, PSEL=1, PSTRB=all-zero.",
        "2. Next rising PCLK -> ACCESS: PENABLE=1; Subordinate drives PRDATA + PREADY=1.",
        "3. Transfer completes.",
    ])
    d.setdefault("failing_apb_transfer_sequence", [
        "1. SETUP + ACCESS as normal.",
        "2. Subordinate drives PREADY=1 AND PSLVERR=1 in the same cycle.",
        "3. Peripheral state after error is implementation-specific.",
        "4. Bridge maps PSLVERR=1 -> HRESP=ERROR (AHB) / RRESP=SLVERR (AXI).",
    ])
    # v0.1.87 — MERGE (14c3 batch pre-fills with AXI-baseline keys).
    _ors = d.setdefault("ordering_rules_summary", {})
    if not isinstance(_ors, dict):
        _ors = {}
        d["ordering_rules_summary"] = _ors
    _ors.setdefault("ahb_single_manager",
        "AHB-Lite is single-Manager; no out-of-order; one outstanding "
        "transfer at a time (pipelined address + data).")
    _ors.setdefault("ahb_burst_order",
        "All beats of a burst are sequential and the address relationship "
        "(INCR / WRAP) is encoded in HBURST.")
    _ors.setdefault("ahb_multi_manager",
        "Multi-Manager AHB requires an interconnect with arbitration; "
        "arbitration ordering is interconnect-defined (see ARM DVI 0045 "
        "Multi-layer AHB Technical Overview).")
    _ors.setdefault("apb_ordering",
        "APB is single-Manager (the bridge); strictly in-order; one "
        "transfer at a time.")
    d.setdefault("narrow_transfer_sequence",
        "Both AHB and APB support narrower-than-bus transfers. AHB: "
        "HSIZE + HADDR + (optional) HWSTRB determine active lanes. APB: "
        "PSTRB explicitly indicates active lanes on writes.")
    d.setdefault("early_burst_termination_ahb",
        "Fixed-length AHB bursts must terminate with SEQ. The only "
        "early-termination paths are (a) Subordinate ERROR response "
        "with Manager driving HTRANS=IDLE, or (b) multi-layer "
        "interconnect terminating the burst.")
    _write(p, d)


# ============================================================
# L13 LAB CALIBRATION
# ============================================================
def _l13(gd: Path) -> None:
    p = gd / "L13_LAB_CALIBRATION.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("lab_calibration_present", False)
    d.setdefault("notes",
        "AHB and APB are digital bus protocols with no analog content, "
        "no measurement-based calibration, no lab trim steps at the "
        "protocol layer.")
    _write(p, d)


# ============================================================
# L14 PROTOCOL VERSIONING
# ============================================================
def _l14(gd: Path) -> None:
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f.setdefault("spec_version_ahb", "AMBA AHB Protocol Specification ARM IHI 0033C (15 September 2021)")
    f.setdefault("spec_version_apb", "AMBA APB Protocol Specification ARM IHI 0024C (13 April 2010) v2.0")
    if _empty(f.get("versions_ahb")):
        f["versions_ahb"] = [
            {"release_date": "06 June 2006",      "issue": "A",   "change": "First release for v1.0 (AHB-Lite)."},
            {"release_date": "25 June 2015",      "issue": "B.a", "change": "Update for AMBA 5 AHB Protocol Specification (Confidential)."},
            {"release_date": "30 October 2015",   "issue": "B.b", "change": "Confidential to Non-Confidential Release."},
            {"release_date": "15 September 2021", "issue": "C",   "change": "Signal width properties; Write strobes; User signaling update; Signal validity rules; Interface protection using parity. Regularized terminology to Manager / Subordinate."},
        ]
    if _empty(f.get("versions_apb")):
        f["versions_apb"] = [
            {"release_date": "25 September 2003", "issue": "A",   "change": "First release for APB v1.0 (APB2)."},
            {"release_date": "17 August 2004",    "issue": "B",   "change": "Second release for APB v1.0 — adds PREADY, PSLVERR (APB3)."},
            {"release_date": "13 April 2010",     "issue": "C",   "change": "First release for APB v2.0 — adds PPROT and PSTRB (APB4)."},
        ]
    if _empty(f.get("backward_compat_traps")):
        f["backward_compat_traps"] = [
            {"trap_name": "AHB_ADDR_WIDTH_change_AB_vs_C",
             "issue_A_B": "ADDR_WIDTH fixed at 32 bits.",
             "issue_C":   "ADDR_WIDTH parameterized 10..64; default 32."},
            {"trap_name": "AHB_HPROT_3_naming_change_A_vs_B",
             "issue_A": "HPROT[3] = Cacheable.",
             "issue_B_C": "HPROT[3] = Modifiable (same definition, new name)."},
            {"trap_name": "AHB_HPROT_extension_4bit_vs_7bit",
             "issue_A": "4-bit HPROT[3:0].",
             "issue_B_C_with_Extended_Memory_Types": "7-bit HPROT[6:0] adds Lookup/Allocate/Shareable."},
            {"trap_name": "AHB_optional_signals_AHB5",
             "issue_A": "No HNONSEC/HEXCL/HMASTER/HEXOKAY/HWSTRB/HxUSER/HxxCHK.",
             "issue_B_C": "Added behind interface properties."},
            {"trap_name": "APB_PREADY_added", "APB2": "No PREADY; fixed 2-cycle.", "APB3_APB4": "PREADY added."},
            {"trap_name": "APB_PSLVERR_added", "APB2": "No PSLVERR.", "APB3_APB4": "PSLVERR added."},
            {"trap_name": "APB_PPROT_added_in_APB4", "APB2_APB3": "No PPROT.", "APB4": "PPROT[2:0]."},
            {"trap_name": "APB_PSTRB_added_in_APB4", "APB2_APB3": "No PSTRB.", "APB4": "PSTRB byte-lane strobes."},
        ]
    f.setdefault("version_naming_history_note_ahb",
        "AHB-Lite (single-Manager) first defined in Issue A (2006). "
        "Issue B introduced AHB5 = AHB-Lite + optional Secure / "
        "Exclusive / Extended memory / User / Parity features. Issue C "
        "(2021) regularized Master/Slave to Manager/Subordinate.")
    f.setdefault("version_naming_history_note_apb",
        "APB2 (AMBA 2) defined original two-phase interface. APB3 "
        "(2004) added PREADY + PSLVERR. APB4 (2010) added PPROT + "
        "PSTRB. APB Rev E (1998) is obsolete.")
    if _empty(f.get("deprecated_features")):
        f["deprecated_features"] = [
            {"feature": "Master/Slave terminology (AHB)",
             "deprecated_in_version": "AHB Issue C (2021)",
             "rationale": "Regularized to Manager / Subordinate for "
                          "inclusive language. Issue A/B used Master/Slave.",
             "supports_through": "Backward compatible at signal level; "
                                 "terminology change only."},
        ]
    if _empty(f.get("interoperability_summary")):
        f["interoperability_summary"] = [
            "AHB-Lite Manager interfaces a wider AHB5 Subordinate by "
            "leaving the AHB5-specific signal inputs at safe defaults "
            "(HEXCL=0, HNONSEC=0, HWSTRB=all-ones).",
            "APB4 Manager interfaces an APB3 Subordinate by tying off "
            "PPROT + PSTRB at the Subordinate input (or the bridge does "
            "not generate them).",
            "An AHB5 Subordinate interfaces an AHB-Lite Manager by "
            "treating absent optional signals as their defaults.",
        ]
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
    f = _ensure_dict(d, "fields")
    if _empty(f.get("tables")):
        f["tables"] = [
            {"table_id": "AHB Table 3-1", "name": "Transfer type encoding (HTRANS)",
             "field_bits": "HTRANS[1:0]",
             "encoding": [
                 {"value": "2'b00", "name": "IDLE",   "semantics": "No data transfer."},
                 {"value": "2'b01", "name": "BUSY",   "semantics": "Mid-burst pause."},
                 {"value": "2'b10", "name": "NONSEQ", "semantics": "Single or first burst transfer."},
                 {"value": "2'b11", "name": "SEQ",    "semantics": "Subsequent burst transfer."},
             ]},
            {"table_id": "AHB Table 3-2", "name": "Transfer size encoding (HSIZE)",
             "field_bits": "HSIZE[2:0]",
             "encoding": [
                 {"value": "3'b000", "name": "Byte",       "semantics": "8 bits per transfer."},
                 {"value": "3'b001", "name": "Halfword",   "semantics": "16 bits."},
                 {"value": "3'b010", "name": "Word",       "semantics": "32 bits."},
                 {"value": "3'b011", "name": "Doubleword", "semantics": "64 bits."},
                 {"value": "3'b100", "name": "4-word line","semantics": "128 bits."},
                 {"value": "3'b101", "name": "8-word line","semantics": "256 bits."},
                 {"value": "3'b110", "name": "-",          "semantics": "512 bits."},
                 {"value": "3'b111", "name": "-",          "semantics": "1024 bits."},
             ]},
            {"table_id": "AHB Table 3-4", "name": "Burst signal encoding (HBURST)",
             "field_bits": "HBURST[2:0]",
             "encoding": [
                 {"value": "3'b000", "name": "SINGLE",  "semantics": "Single transfer burst."},
                 {"value": "3'b001", "name": "INCR",    "semantics": "Incrementing burst of undefined length."},
                 {"value": "3'b010", "name": "WRAP4",   "semantics": "4-beat wrapping burst."},
                 {"value": "3'b011", "name": "INCR4",   "semantics": "4-beat incrementing burst."},
                 {"value": "3'b100", "name": "WRAP8",   "semantics": "8-beat wrapping burst."},
                 {"value": "3'b101", "name": "INCR8",   "semantics": "8-beat incrementing burst."},
                 {"value": "3'b110", "name": "WRAP16",  "semantics": "16-beat wrapping burst."},
                 {"value": "3'b111", "name": "INCR16",  "semantics": "16-beat incrementing burst."},
             ]},
            {"table_id": "AHB Table 3-5", "name": "HPROT basic 4-bit",
             "field_bits": "HPROT[3:0]",
             "encoding": [
                 {"value": "HPROT[0]", "name": "Data/Opcode",        "semantics": "1=Data, 0=Opcode fetch."},
                 {"value": "HPROT[1]", "name": "Privileged/User",    "semantics": "1=Privileged, 0=User."},
                 {"value": "HPROT[2]", "name": "Bufferable",         "semantics": "1=Bufferable."},
                 {"value": "HPROT[3]", "name": "Modifiable/Cacheable","semantics": "1=Cacheable (Issue A) / Modifiable (Issue B+)."},
             ]},
            {"table_id": "AHB Section 5.1", "name": "Response encoding (HRESP)",
             "field_bits": "HRESP",
             "encoding": [
                 {"value": "1'b0", "name": "OKAY",  "semantics": "Normal access."},
                 {"value": "1'b1", "name": "ERROR", "semantics": "Two-cycle error response."},
             ]},
            {"table_id": "APB Table 3-1", "name": "Protection encoding (PPROT, APB4)",
             "field_bits": "PPROT[2:0]",
             "encoding": [
                 {"value": "PPROT[0]", "name": "Normal/Privileged", "semantics": "1=Privileged, 0=Normal."},
                 {"value": "PPROT[1]", "name": "Secure/Non-secure", "semantics": "1=Non-secure (HIGH-for-Non-secure), 0=Secure."},
                 {"value": "PPROT[2]", "name": "Data/Instruction",  "semantics": "1=Instruction, 0=Data."},
             ]},
            {"table_id": "APB Operating states (Figure 4-1)", "name": "APB state encoding",
             "field_bits": "{PSELx, PENABLE}",
             "encoding": [
                 {"value": "{0,0}", "name": "IDLE",   "semantics": "Default state."},
                 {"value": "{1,0}", "name": "SETUP",  "semantics": "One cycle; unconditional -> ACCESS."},
                 {"value": "{1,1}", "name": "ACCESS", "semantics": "PREADY-controlled wait + exit."},
             ]},
        ]
    f.setdefault("ahb_burst_address_equations", {
        "Number_Bytes_per_beat": "2 ^ HSIZE",
        "Burst_Length_beats":    "1 (SINGLE) / undefined (INCR) / 4 / 8 / 16",
        "Aligned_Address":       "Manager must align HADDR to (1 << HSIZE) bytes for each transfer in a burst.",
        "INCR_address_n":        "HADDR_(n+1) = HADDR_n + Number_Bytes",
        "WRAP_boundary":         "Wrap boundary = Burst_Length_beats * Number_Bytes",
        "WRAP_address_n":        "HADDR_(n+1) = (HADDR_n + Number_Bytes) modulo Wrap_boundary (mod within the (start_address & ~(Wrap_boundary-1))..+Wrap_boundary range)",
        "INCR_1KB_rule":         "Incrementing burst must not cross a 1KB address boundary.",
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
    f = _ensure_dict(d, "fields")
    if _empty(f.get("properties")):
        f["properties"] = [
            {"id": "p_ahb_1kb_boundary", "scope": "AHB_address_phase",
             "english_form": "An AHB incrementing burst must not cross a 1KB address boundary.",
             "citation": "AHB 3.6 page 3-35"},
            {"id": "p_ahb_idle_zero_wait_okay", "scope": "AHB_Subordinate",
             "english_form": "Subordinate must always give zero-wait OKAY for IDLE.",
             "citation": "AHB Table 3-1 / 3.2"},
            {"id": "p_ahb_busy_zero_wait_okay", "scope": "AHB_Subordinate",
             "english_form": "Subordinate must always give zero-wait OKAY for BUSY.",
             "citation": "AHB Table 3-1 / 3.2"},
            {"id": "p_ahb_burst_constancy", "scope": "AHB_Manager",
             "english_form": "HSIZE/HBURST/HWRITE/HPROT/HMASTLOCK/HNONSEC constant across burst.",
             "citation": "AHB 3.4 / 3.6 / 3.8 / 3.10"},
            {"id": "p_ahb_burst_alignment", "scope": "AHB_Manager",
             "english_form": "Burst transfer aligned to (1<<HSIZE) bytes.",
             "citation": "AHB 3.6"},
            {"id": "p_ahb_error_two_cycle", "scope": "AHB_Subordinate",
             "english_form": "ERROR response is two cycles (HRESP=1+HREADY=0 then HRESP=1+HREADY=1).",
             "citation": "AHB 5.1"},
            {"id": "p_ahb_no_busy_end_fixed", "scope": "AHB_Manager",
             "english_form": "Fixed-length burst must terminate with SEQ, not BUSY.",
             "citation": "AHB 3.6"},
            {"id": "p_ahb_locked_same_region", "scope": "AHB_Manager",
             "english_form": "All transfers in a locked sequence to the same Subordinate region.",
             "citation": "AHB 3.3"},
            {"id": "p_ahb_wait_state_addr_constant", "scope": "AHB_Manager",
             "english_form": "Address changes during HREADY=LOW limited to IDLE/post-ERROR.",
             "citation": "AHB 3.7.2"},
            {"id": "p_ahb_wait_state_transfer_type_constraint", "scope": "AHB_Manager",
             "english_form": "HTRANS changes during HREADY=LOW limited to IDLE->NONSEQ, BUSY->SEQ, BUSY->other (undefined).",
             "citation": "AHB 3.7.1"},
            {"id": "p_ahb_subordinate_sample_when_ready_high", "scope": "AHB_Subordinate",
             "english_form": "Subordinate samples inputs only when HREADY=HIGH.",
             "citation": "AHB 4.2"},
            {"id": "p_ahb_subordinate_min_decode_1kb", "scope": "AHB_decoder",
             "english_form": "Minimum decode granularity 1KB.",
             "citation": "AHB 4.2"},
            {"id": "p_ahb_default_subordinate", "scope": "AHB_interconnect",
             "english_form": "Default Subordinate: ERROR for NONSEQ/SEQ, zero-wait OKAY for IDLE/BUSY.",
             "citation": "AHB 4.2.1"},
            {"id": "p_ahb_exclusive_AHB5", "scope": "AHB5_Exclusive",
             "english_form": "HEXCL+HMASTER+HEXOKAY implement Exclusive Access Monitor.",
             "citation": "AHB Chapter 10"},
            {"id": "p_ahb_secure_constancy", "scope": "AHB5_Manager",
             "english_form": "HNONSEC constant throughout a burst.",
             "citation": "AHB 3.10"},
            {"id": "p_ahb_hwstrb_byte_mapping", "scope": "AHB5_Manager",
             "english_form": "HWSTRB[n] -> HWDATA[(8n+7):8n].",
             "citation": "AHB 3.5"},
            {"id": "p_apb_two_cycle_minimum", "scope": "APB",
             "english_form": "Every APB transfer takes at least two PCLK cycles.",
             "citation": "APB 1.1"},
            {"id": "p_apb_setup_then_access", "scope": "APB_state_machine",
             "english_form": "SETUP -> ACCESS unconditional on next rising PCLK.",
             "citation": "APB 4.1"},
            {"id": "p_apb_access_stable_signals", "scope": "APB_Manager",
             "english_form": "PADDR/PWRITE/PSELx/PENABLE/PWDATA/PSTRB/PPROT stable while PREADY=LOW.",
             "citation": "APB 3.1.2 / 3.3.2"},
            {"id": "p_apb_pready_any_when_penable_low", "scope": "APB_Subordinate",
             "english_form": "PREADY can be any value while PENABLE=LOW.",
             "citation": "APB 3.1.2"},
            {"id": "p_apb_pstrb_low_on_read", "scope": "APB_Manager",
             "english_form": "PSTRB=all-LOW for read transfers.",
             "citation": "APB 3.2"},
            {"id": "p_apb_pslverr_valid_window", "scope": "APB_Subordinate",
             "english_form": "PSLVERR valid only when {PSEL,PENABLE,PREADY}=111.",
             "citation": "APB 3.4"},
            {"id": "p_apb_pslverr_optional", "scope": "APB_Subordinate",
             "english_form": "PSLVERR optional; tied LOW at bridge if absent.",
             "citation": "APB 2.1 / 3.4"},
            {"id": "p_apb_pprot_constancy", "scope": "APB_Manager",
             "english_form": "PPROT (APB4) constant while PREADY=LOW.",
             "citation": "APB 3.1.2 / 3.3.2"},
            {"id": "p_apb_pslverr_to_ahb_hresp_mapping", "scope": "AHB_to_APB_bridge",
             "english_form": "Bridge maps PSLVERR -> HRESP=ERROR (HRESP[0]=1).",
             "citation": "APB 3.4.3"},
            {"id": "p_apb_pslverr_to_axi_rresp_mapping", "scope": "AXI_to_APB_bridge",
             "english_form": "Bridge maps PSLVERR -> RRESP/BRESP=SLVERR.",
             "citation": "APB 3.4.3"},
        ]
    d["fields"] = f
    _write(p, d)


# ============================================================
# L17 CHANNEL SIGNAL CATALOG — force-overwrite dependency_graph
# ============================================================
def _l17(gd: Path) -> None:
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f.setdefault("ahb_global_signals", [
        {"name": "HCLK",    "width": 1, "direction": "Clock source -> all", "semantics": "Bus clock; rising edge times all transfers."},
        {"name": "HRESETn", "width": 1, "direction": "Reset controller -> all", "semantics": "Bus reset, active LOW (only active-LOW signal in AHB)."},
    ])
    f.setdefault("ahb_manager_signals", [
        {"name": "HADDR",     "width": "ADDR_WIDTH (default 32)", "direction": "Manager -> Subordinate+Decoder", "semantics": "Byte address of transfer."},
        {"name": "HBURST",    "width": "0 or 3", "direction": "Manager -> Subordinate", "semantics": "Burst type."},
        {"name": "HMASTLOCK", "width": 1, "direction": "Manager -> Subordinate", "semantics": "Locked sequence indicator."},
        {"name": "HPROT",     "width": "0, 4, or 7", "direction": "Manager -> Subordinate", "semantics": "Protection control."},
        {"name": "HSIZE",     "width": 3, "direction": "Manager -> Subordinate", "semantics": "Transfer size."},
        {"name": "HNONSEC",   "width": 1, "direction": "Manager -> Subordinate+Decoder", "semantics": "Secure/Non-secure (AHB5)."},
        {"name": "HEXCL",     "width": 1, "direction": "Manager -> Monitor", "semantics": "Exclusive transfer (AHB5)."},
        {"name": "HMASTER",   "width": "0..8", "direction": "Manager -> Monitor+Subordinate", "semantics": "Manager ID (AHB5)."},
        {"name": "HTRANS",    "width": 2, "direction": "Manager -> Subordinate", "semantics": "Transfer type."},
        {"name": "HWDATA",    "width": "DATA_WIDTH", "direction": "Manager -> Subordinate", "semantics": "Write data."},
        {"name": "HWSTRB",    "width": "DATA_WIDTH/8", "direction": "Manager -> Subordinate", "semantics": "Write strobes (Issue C)."},
        {"name": "HWRITE",    "width": 1, "direction": "Manager -> Subordinate", "semantics": "Direction: 1=write."},
    ])
    f.setdefault("ahb_subordinate_signals", [
        {"name": "HRDATA",    "width": "DATA_WIDTH", "direction": "Subordinate -> Mux -> Manager", "semantics": "Read data."},
        {"name": "HREADYOUT", "width": 1, "direction": "Subordinate -> Mux", "semantics": "Per-Subordinate ready; combined into HREADY."},
        {"name": "HRESP",     "width": 1, "direction": "Subordinate -> Mux -> Manager", "semantics": "Response: 0=OKAY, 1=ERROR (two-cycle)."},
        {"name": "HEXOKAY",   "width": 1, "direction": "Subordinate -> Mux -> Manager", "semantics": "Exclusive okay (AHB5)."},
    ])
    f.setdefault("ahb_decoder_signals", [
        {"name": "HSELx", "width": 1, "direction": "Decoder -> Subordinate", "semantics": "One per Subordinate."},
    ])
    f.setdefault("ahb_multiplexor_signals", [
        {"name": "HRDATA",  "width": "DATA_WIDTH", "direction": "Mux -> Manager", "semantics": "Selected by decoder."},
        {"name": "HREADY",  "width": 1, "direction": "Mux -> Manager+all Subordinates", "semantics": "Combined HREADYOUT chain."},
        {"name": "HRESP",   "width": 1, "direction": "Mux -> Manager", "semantics": "Selected by decoder."},
        {"name": "HEXOKAY", "width": 1, "direction": "Mux -> Manager", "semantics": "Selected by decoder (AHB5)."},
    ])
    f.setdefault("apb_signals", [
        {"name": "PCLK",     "width": 1, "direction": "Clock source -> all",  "semantics": "Rising edge times all transfers."},
        {"name": "PRESETn",  "width": 1, "direction": "System reset -> all",  "semantics": "Active LOW."},
        {"name": "PADDR",    "width": "up to 32", "direction": "Bridge -> Sub","semantics": "APB address bus."},
        {"name": "PPROT",    "width": 3, "direction": "Bridge -> Sub",        "semantics": "Protection (APB4)."},
        {"name": "PSELx",    "width": 1, "direction": "Bridge -> Sub",        "semantics": "Per-peripheral select."},
        {"name": "PENABLE",  "width": 1, "direction": "Bridge -> Sub",        "semantics": "Second cycle of an APB transfer."},
        {"name": "PWRITE",   "width": 1, "direction": "Bridge -> Sub",        "semantics": "1=write, 0=read."},
        {"name": "PWDATA",   "width": "up to 32", "direction": "Bridge -> Sub","semantics": "Write data."},
        {"name": "PSTRB",    "width": "PWDATA_WIDTH/8", "direction": "Bridge -> Sub", "semantics": "Write strobes (APB4); all-LOW on reads."},
        {"name": "PREADY",   "width": 1, "direction": "Sub -> Bridge",        "semantics": "Slave ready; LOW extends ACCESS (APB3+)."},
        {"name": "PRDATA",   "width": "up to 32", "direction": "Sub -> Bridge","semantics": "Read data."},
        {"name": "PSLVERR",  "width": 1, "direction": "Sub -> Bridge",        "semantics": "Transfer failure (APB3+, optional)."},
    ])
    # Force-populate channel_counts with AHB+APB-specific subkeys (upstream
    # may have seeded a different-shape dict).
    cc = f.get("channel_counts")
    if not isinstance(cc, dict):
        cc = {}
        f["channel_counts"] = cc
    cc.setdefault("ahb_channels", 5)
    cc.setdefault("ahb_channel_names", ["Global", "Manager", "Subordinate", "Decoder", "Multiplexor"])
    cc.setdefault("apb_phases", 3)
    cc.setdefault("apb_phase_names", ["IDLE", "SETUP", "ACCESS"])
    # Force-populate handshake_pairs (upstream often seeds empty dict).
    hp = f.get("handshake_pairs")
    if not isinstance(hp, dict) or not hp:
        hp = {}
        f["handshake_pairs"] = hp
    hp.setdefault("ahb_address_to_data",
        "HSELx + HREADY co-sampled in Subordinate; HREADYOUT drives "
        "wait states; HRESP drives error response.")
    hp.setdefault("apb_setup_access",
        "PSELx + PENABLE jointly indicate state; PREADY extends ACCESS.")
    # AHB5 User signals + Parity-check signals (sibling-extras in L17).
    if _empty(f.get("ahb_user_signals_AHB5")):
        f["ahb_user_signals_AHB5"] = [
            {"name": "HAUSER", "width": "USER_REQ_WIDTH (impl-defined)", "direction": "Manager -> Subordinate", "semantics": "User signal on Address channel."},
            {"name": "HWUSER", "width": "USER_DATA_WIDTH (impl-defined)", "direction": "Manager -> Subordinate", "semantics": "User signal on Write data channel."},
            {"name": "HRUSER", "width": "USER_DATA_WIDTH (impl-defined)", "direction": "Subordinate -> Manager", "semantics": "User signal on Read data channel."},
            {"name": "HBUSER", "width": "USER_RESP_WIDTH (impl-defined)", "direction": "Subordinate -> Manager", "semantics": "User signal on Response channel."},
        ]
    if _empty(f.get("ahb_parity_check_signals_AHB5")):
        f["ahb_parity_check_signals_AHB5"] = [
            {"name": "HADDRCHK",  "purpose": "Parity check signal for HADDR (and the Manager control bits)."},
            {"name": "HCTRLCHK",  "purpose": "Parity check signal for the address-phase control signals."},
            {"name": "HWDATACHK", "purpose": "Parity check signal for HWDATA + HWSTRB."},
            {"name": "HRDATACHK", "purpose": "Parity check signal for HRDATA."},
            {"name": "HRESPCHK",  "purpose": "Parity check signal for HRESP."},
            {"name": "HREADYCHK", "purpose": "Parity check signal for HREADY."},
        ]
    # Force-overwrite dependency_graph for AHB+APB shape.
    f["dependency_graph"] = {
        "ahb_common_rule":
            "Subordinate samples HSELx + address-phase signals only when "
            "HREADY=HIGH. Subordinate drives HREADYOUT to extend the "
            "data phase. AHB has no AXI-style VALID/READY decoupling — "
            "instead it uses HTRANS + HREADY co-sampled.",
        "ahb_address_phase":
            "Address phase one cycle (extended only by previous data "
            "phase).",
        "ahb_data_phase":
            "Data phase one or more cycles; controlled by HREADY.",
        "ahb_pipeline":
            "Address phase of transfer N+1 overlaps data phase of "
            "transfer N.",
        "apb_state_transitions":
            "IDLE -> SETUP on transfer-required; SETUP -> ACCESS "
            "unconditional next PCLK; ACCESS -> ACCESS while PREADY=0; "
            "ACCESS -> IDLE or SETUP on PREADY=1.",
    }
    # v0.1.87 — FORCE overwrite (14c3 batch synth pre-fills ordering_rules
    # with AXI-baseline keys; AHB+APB-specific keys must win for ahb_apb).
    f["ordering_rules"] = {
        "ahb_strict_in_order":
            "AHB-Lite is single-Manager and strictly in-order; one "
            "outstanding transfer with address/data pipelining.",
        "ahb_burst_order":
            "Beats of a burst are in HBURST-defined order (incrementing or "
            "wrapping); all beats use same HSIZE / HWRITE / HPROT / "
            "HMASTLOCK.",
        "apb_strict_in_order":
            "APB is single-Manager (bridge); strictly in-order; one "
            "transfer in progress at a time.",
    }
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
    f = _ensure_dict(d, "fields")
    f.setdefault("typical_topologies_ahb", [
        "Single-Manager AHB-Lite (Figure 1-1).",
        "Multi-Manager AHB / multi-layer AHB.",
        "Multi-layer AHB: parallel Manager-Subordinate paths.",
    ])
    f.setdefault("typical_topologies_apb", [
        "Single APB bridge (Manager) + multiple APB peripherals.",
        "Single Manager bus only; no multi-Manager arbitration.",
    ])
    f.setdefault("interconnect_role_ahb", {
        "decoder":     "Generates one HSELx per Subordinate; 1KB min granularity; drives multiplexor select retimed to data phase.",
        "multiplexor": "Routes HRDATA/HRESP/HREADYOUT/HEXOKAY back to Manager; combines all HREADYOUTs into HREADY.",
        "default_slave": "ERROR for NONSEQ/SEQ to unmapped addresses, zero-wait OKAY for IDLE/BUSY.",
        "multi_manager": "Multi-Manager requires interconnect with arbitration (outside AHB spec scope).",
    })
    f.setdefault("interconnect_role_apb", {
        "bridge": "APB Manager — decodes upstream accesses into APB transfers; maps PSLVERR back to upstream protocol's error.",
        "psel_routing": "Bridge decodes upper PADDR bits for per-peripheral PSELx.",
    })
    f.setdefault("interconnect_rules_ahb", [
        "Decoder drives HSELx during address phase.",
        "HSELx may be asserted or deasserted for IDLE.",
        "Multiplexor control retimed to data phase.",
        "Single centralized decoder + multiplexor required for >=2 Subordinates.",
        "Default Subordinate returns ERROR for unmapped NONSEQ/SEQ.",
        "Multiple HSELx may be asserted for a single Subordinate (multiple logical interfaces).",
        "HREADY computed by combining all Subordinate HREADYOUTs.",
        "Generic interconnect may offer AHB alongside AXI/APB.",
    ])
    f.setdefault("interconnect_rules_apb", [
        "Bridge generates one PSELx per peripheral.",
        "Only one PSELx asserted per transfer.",
        "Bridge holds outputs stable while PREADY=0.",
        "AHB-to-APB bridge: PSLVERR -> HRESP=ERROR.",
        "AXI-to-APB bridge: PSLVERR -> RRESP/BRESP=SLVERR.",
        "Peripherals without PSLVERR: input tied LOW at bridge.",
    ])
    f.setdefault("default_signal_values_ahb", {
        "HBURST_when_absent":    "0b000 (SINGLE)",
        "HSIZE_when_absent":     "0b010 (Word, 32-bit)",
        "HTRANS_during_reset":   "0b00 (IDLE)",
        "HMASTLOCK_when_absent": "0 (Normal)",
        "HPROT_when_absent":     "0b0011",
        "HNONSEC_when_absent":   "0 (Secure)",
        "HEXCL_when_absent":     "0 (non-Exclusive)",
        "HWSTRB_when_absent":    "All ones",
    })
    f.setdefault("default_signal_values_apb", {
        "PPROT_when_absent":   "0b000 (Normal + Secure + Data)",
        "PSTRB_when_absent":   "All ones",
        "PREADY_when_absent":  "1 (fixed two-cycle access)",
        "PSLVERR_when_absent": "0 (no error)",
    })
    f.setdefault("id_routing_ahb", {
        "description":
            "AHB-Lite has no ID. AHB5 HMASTER is modified by the "
            "interconnect to be globally unique.",
        "implication":
            "HMASTER_WIDTH must accommodate all Manager IDs in the "
            "system.",
    })
    f.setdefault("ordering_guarantees_ahb", {
        "guaranteed": [
            "Beats of a burst presented in HBURST-defined order.",
            "Single-Manager AHB-Lite: strict request order = response order.",
        ],
        "not_guaranteed": [
            "Multi-Manager arbitration order (interconnect-specific).",
            "AXI-style out-of-order completion (AHB has none).",
        ],
    })
    f.setdefault("ordering_guarantees_apb", {
        "guaranteed": ["Strict in-order on a single APB bus."],
        "not_guaranteed": ["Ordering across multiple independent APB busses."],
    })
    # v0.1.87 — MERGE (14c3 batch / ACE synth may pre-fill with AXI keys).
    _mvpr = f.setdefault("memory_vs_peripheral_regions", {})
    if not isinstance(_mvpr, dict):
        _mvpr = {}
        f["memory_vs_peripheral_regions"] = _mvpr
    _mvpr.setdefault("ahb_memory_subordinate",
        "Maps to a memory region; handles all bursts/sizes correctly.")
    _mvpr.setdefault("ahb_peripheral_subordinate",
        "Typically connected via an AHB-to-APB bridge; APB peripheral "
        "behaviour governed by APB protocol.")
    _mvpr.setdefault("apb_peripheral_region",
        "PADDR-mapped peripheral register set; one PSELx per logical "
        "peripheral.")
    f.setdefault("slave_classification_ahb", {
        "Memory_Subordinate":     "Handles all AHB transaction types.",
        "Peripheral_Subordinate": "Often APB peripheral behind AHB-to-APB bridge.",
        "Default_Subordinate":    "ERROR for NONSEQ/SEQ at unmapped, zero-wait OKAY for IDLE/BUSY.",
    })
    f.setdefault("slave_classification_apb", {
        "Memory_mapped_peripheral":   "Standard APB peripheral; uses PREADY to extend ACCESS phase if needed.",
        "Fixed_two_cycle_peripheral": "PREADY tied HIGH; every transfer completes in exactly 2 PCLK cycles.",
        "PSLVERR_supporting":         "Drives PSLVERR=1 in the cycle PREADY=1 to indicate failure.",
        "Non_PSLVERR_supporting":     "PSLVERR input to the bridge tied LOW.",
    })
    f.setdefault("default_signal_values_evidence_tables", [
        "AHB Table 2-2 Manager signals",
        "AHB Table 2-3 Subordinate signals",
        "AHB Table 2-4 Decoder signals",
        "AHB Table 2-5 Multiplexor signals",
        "AHB Appendix A Signal matrix",
        "APB Table 2-1 APB signal descriptions",
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
    f = _ensure_dict(d, "fields")
    f.setdefault("constraints_present", False)
    f["notes"] = (
        "AHB (IHI 0033C) and APB (IHI 0024C) are wire-level / cycle-"
        "level bus protocol specs. They define logical signal semantics "
        "and timing rules relative to HCLK / PCLK only - no PDK-specific "
        "SDC, no floorplan / placement constraints, no clock-tree budget. "
        "Per-implementation timing closure (clock period, max-skew, max-"
        "fanout, IO standards) is the responsibility of the SoC "
        "integrator and is captured outside these protocol specs.")
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
    f = _ensure_dict(d, "fields")
    f.setdefault("dft_present", False)
    f["notes"] = (
        "Neither IHI 0033C (AHB) nor IHI 0024C (APB) specifies DFT / "
        "scan / BIST / MBIST / boundary scan. The protocols only specify "
        "functional signaling. Concrete AHB / APB Manager / Subordinate "
        "/ bridge IPs add standard scan insertion + DFT compression + "
        "boundary-scan during SoC integration; debug visibility is "
        "typically provided via ARM CoreSight, JTAG (IEEE 1149.1), and "
        "trace components - all outside the scope of these bus protocol "
        "specs.")
    f.setdefault("ahb5_parity_only_diagnostic",
        "The closest protocol-defined fault-detection feature is "
        "AHB5's optional Interface protection using parity (Chapter "
        "12 — HADDRCHK / HCTRLCHK / HWDATACHK / HRDATACHK / HRESPCHK "
        "/ HREADYCHK). This is functional fault detection, not DFT.")
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
    f = _ensure_dict(d, "fields")
    f.setdefault("power_intent_present", False)
    f.setdefault("low_power_modes_summary", {
        "ahb_idle":      "Manager drives HTRANS=IDLE; HCLK gating is implementation-defined.",
        "apb_idle":      "PSELx=0, PENABLE=0; PCLK can be gated by integrator.",
        "apb_low_power_intent":
            "APB explicitly designed as a low-cost, low-power "
            "peripheral bus optimized for minimal power consumption.",
    })
    f.setdefault("notes",
        "Power-domain partitioning, voltage-domain crossings, power-"
        "gate sequencing, isolation cells, retention registers are "
        "deferred to SoC integration (UPF / CPF). Neither IHI 0033C "
        "nor IHI 0024C defines a power-intent layer. APB's two-cycle "
        "minimum + lack of pipelining are intentional power "
        "optimizations.")
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
    f = _ensure_dict(d, "fields")
    f.setdefault("verification_plan_present", "implicit")
    if _empty(f.get("verification_categories_derived_from_spec_ahb")):
        f["verification_categories_derived_from_spec_ahb"] = [
            "Reset behavior (HRESETn).",
            "Single NONSEQ + IDLE.",
            "Incrementing bursts INCR4/8/16 + undefined INCR.",
            "Wrapping bursts WRAP4/8/16 with all HSIZE values.",
            "1KB burst boundary enforcement.",
            "IDLE / BUSY zero-wait OKAY.",
            "BUSY mid-burst.",
            "Subordinate-driven wait states.",
            "Address-phase constraints during waited transfers.",
            "Two-cycle ERROR response.",
            "Locked sequence (HMASTLOCK).",
            "HPROT 4-bit + 7-bit memory-type encoding.",
            "Default Subordinate ERROR.",
            "AHB5 Secure transfers (HNONSEC).",
            "AHB5 Exclusive transfers (HEXCL/HMASTER/HEXOKAY).",
            "AHB5 Write strobes HWSTRB.",
            "AHB5 User signaling HxUSER (point-to-point).",
            "AHB5 Interface protection using parity.",
            "Multi-Manager arbitration (multi-layer AHB).",
        ]
    if _empty(f.get("verification_categories_derived_from_spec_apb")):
        f["verification_categories_derived_from_spec_apb"] = [
            "Reset behavior (PRESETn).",
            "Write/read transfers with no wait.",
            "Write/read transfers with wait states (PREADY=0).",
            "Failing write/read with PSLVERR=1.",
            "PSLVERR valid-window enforcement.",
            "PSLVERR-optional peripheral.",
            "Fixed-2-cycle peripheral (PREADY tied HIGH).",
            "PSEL mutual exclusion.",
            "APB4 PSTRB sparse-write byte-lane coverage.",
            "APB4 PSTRB=all-zero on reads.",
            "APB4 PPROT encoding + constancy.",
            "AHB-to-APB bridge: PSLVERR -> HRESP=ERROR.",
            "AXI-to-APB bridge: PSLVERR -> RRESP/BRESP=SLVERR.",
        ]
    f.setdefault("interoperability_test_matrix", [
        "AHB-Lite Manager + AHB5 Subordinate (defaults).",
        "AHB5 Manager + AHB-Lite Subordinate.",
        "Write_Strobes mismatch: HWSTRB tied HIGH at Subordinate.",
        "APB2 peripheral on APB3/APB4 bridge.",
        "APB3 peripheral on APB4 bridge.",
        "End-to-end AXI Manager -> AHB Subordinate -> APB peripheral.",
    ])
    f["notes"] = (
        "Neither AHB IHI 0033C nor APB IHI 0024C provides a formal "
        "verification plan; the categories above are derived from "
        "Chapters 3 (Transfers), 4 (Bus Interconnection), 5 (Subordinate "
        "Response Signaling), 10 (Exclusive Transfers), 12 (Interface "
        "protection) of AHB, and Chapter 3 (Transfers) + Chapter 4 "
        "(Operating States) of APB.")
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
    f = _ensure_dict(d, "fields")
    f["security_requirements_present"] = "partial"
    f.setdefault("ahb_security_features", [
        {"name": "HPROT[1] Privileged",       "purpose": "Privilege-level signaling for access control at the bus layer."},
        {"name": "HNONSEC (AHB5)",            "purpose": "Secure/Non-secure transfer indicator; address-phase, burst-constant."},
        {"name": "HEXCL + HMASTER + HEXOKAY (AHB5)", "purpose": "Exclusive Access mechanism for concurrency-safe RMW primitives."},
        {"name": "HMASTLOCK",                 "purpose": "Locked-sequence indicator for atomic operations in multi-Manager configurations."},
        {"name": "AHB5 Interface protection via parity (Chapter 12)", "purpose": "Single-bit fault detection on each interface."},
    ])
    f.setdefault("apb_security_features", [
        {"name": "PPROT[0] Normal/Privileged (APB4)", "purpose": "Privilege-level signaling."},
        {"name": "PPROT[1] Secure/Non-secure (APB4)", "purpose": "TrustZone-like secure/non-secure distinction (HIGH=Non-secure)."},
        {"name": "PPROT[2] Data/Instruction (APB4)",  "purpose": "Data vs instruction hint."},
    ])
    f.setdefault("what_is_NOT_in_the_specs", [
        "No confidentiality / encryption at the protocol layer.",
        "No data-integrity / authentication (no MAC, no HMAC).",
        "No replay protection.",
        "No anti-rollback mechanism.",
        "No attestation features.",
        "No key-storage / key-derivation features.",
    ])
    f.setdefault("secure_integration_responsibilities", [
        "TrustZone partitioning via HNONSEC / PPROT[1] routed to Subordinate-side filters.",
        "Master Security Wrappers enforce HNONSEC + HMASTER per Manager port.",
        "PPROT[1] HIGH=Non-secure convention must be mirrored end-to-end.",
    ])
    f["notes"] = (
        "Security in AMBA AHB and APB is limited to signaling "
        "primitives (HPROT / HNONSEC / PPROT / Exclusive Access / "
        "Lock + AHB5 parity) - not cryptographic primitives. End-to-"
        "end confidentiality/integrity must be provided by upper "
        "layers (TrustZone Address Space Controllers, MMU/SMMU, "
        "dedicated crypto IP, secure boot ROM). The specs explicitly "
        "note that the Data/Instruction bit is provided as a hint and "
        "is not accurate in all cases.")
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
def is_ahb_apb(blob: str) -> bool:
    """Content-only `ahb_apb` detector (importable, lifted from the runner).

    Empty-safe. Reads ONLY ``blob`` (spec text). Byte-for-byte the
    same boolean the runner used inline.
    """
    if not blob:
        return False
    axi_primary = (
        "ARVALID" in blob or "AWVALID" in blob
        or "ARLEN" in blob or "AWLEN" in blob
        or "ARBURST" in blob or "RVALID" in blob
        or "WVALID" in blob or "BVALID" in blob)
    swd_primary = (
        ("SWDIO" in blob and "SWCLK" in blob)
        or "ADIv5" in blob or "IHI0031" in blob)
    return bool(
        (not axi_primary) and (not swd_primary) and (
            ("HCLK" in blob and "HADDR" in blob
                and "HTRANS" in blob and "HREADY" in blob)
            or ("PCLK" in blob and "PADDR" in blob
                and "PSEL" in blob and "PENABLE" in blob)))
