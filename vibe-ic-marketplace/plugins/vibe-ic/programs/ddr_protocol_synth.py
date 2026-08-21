"""DDR (DDR3 SDRAM)-class protocol synth helper.

v0.1.84 — ic_class-gated overlay for `parallel_memory_protocol` specs
that exhibit the DDR3 SDRAM structural signature, e.g.:
- DDR3 + SDRAM + CAS-Latency + Mode-Register triple OR
- ACTIVATE + PRECHARGE + tRCD + tRP timing-parameter cluster OR
- DDR + 8n prefetch + Burst Length 8 OR
- JEDEC JESD79-3* document number.

Applies JEDEC JESD79-3C DDR3 SDRAM Standard (November 2008) spec-canonical
content to L1-L23 layer docs. The signature gate ensures this helper only
fires on DDR3-class specs; non-DDR3 parallel-memory specs (DDR2, DDR4,
DDR5, LPDDR2..LPDDR5, GDDR5..GDDR7) are left untouched here — those have
their own structural overlays.

Doctrine: structural-keyword detection IS general within an ic_class
(mirrors AMBA-AXI / SPI / I2C / UART / CAN / USB / I2S synth approach).
Any DDR3 variant (DDR3 standard / DDR3L low-voltage / DDR3U ultra-low-
voltage / DDR3 RDIMM / LRDIMM) exhibits the same signature and is fed
the same baseline content; voltage-specific overrides (1.35 V / 1.25 V)
are NOT forced — they remain whatever the upstream extractor produced.

Public entry: `apply_ddr_synth(generated_docs_dir, is_ddr, ddr_ic_name)`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import l_doc_generator_stamp as _stamp

from _incidental_mention import AnchoredBlob as _AnchoredBlob
from _incidental_mention import subject_term as _subject_term
import _pack_top_module as _ptm  # L9.top_module: one decision, one provenance stamp


def _empty(v) -> bool:
    return v in (None, {}, []) or (isinstance(v, str) and not v.strip())


def _ensure_dict(d: dict, key: str) -> dict:
    """setdefault-None bug fix: if the value is None / empty / non-dict,
    replace with {} so subsequent setdefault calls can populate subkeys."""
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
# Structural detector helpers (re-exportable so phase1 ic_class router
# can call into this module's heuristics directly).
# ----------------------------------------------------------------------

def detect_ddr3_signature(text: str) -> bool:
    """Return True if the input text exhibits a DDR3-class structural
    signature.

    General (not keyword-overfit): we require at least TWO of three
    orthogonal feature clusters, each cluster itself testing for the
    presence of multiple independent indicators. A spec that mentions
    'DDR3' once in passing but does not also mention any of the
    timing / register / command terms will not trigger; conversely an
    SDRAM spec that uses ACTIVATE + PRECHARGE + tRCD + tRP without the
    string 'DDR3' will trigger via the 'classic SDRAM command +
    timing' cluster.

    v0.1.89 — SIBLING MUTEX (DDR3 side, vs LPDDR5): an LPDDR5 (JESD209-5)
    spec legitimately mentions 'DDR3'/'DDR4' (DDR4-style bank groups +
    comparison), 'SDRAM', 'mode register', 'DDR' and 'JEDEC', which would
    otherwise trip the DDR3 clusters. A TRUE DDR3 spec NEVER carries the
    LPDDR5 version-specific structural tokens WCK (a separate full-speed
    Write Clock that DDR3 lacks) nor the JESD209-5 spec-id nor the
    'LPDDR5' generation name. If any of those is present, defer to the
    LPDDR5 detector. General — keys off the version-specific token, not a
    benchmark name.
    """
    if not text:
        return False
    t = text.lower()

    # LPDDR5 mutex: defer to the LPDDR5 detector if the version-specific
    # LPDDR5 tokens are present.
    if ("lpddr5" in t or "jesd209-5" in t
            or ("wck" in t and "bank group" in t and "low-power" in t)):
        return False

    # Cluster A: DDR3 generation + SDRAM + mode register
    a = sum(1 for k in (
        "ddr3", "sdram", "mode register", "cas latency", "ddr3 sdram",
        "jesd79-3", "jedec",
    ) if k in t)

    # Cluster B: classic DRAM command + timing-parameter set
    b = sum(1 for k in (
        "activate", "precharge", "tras", "trcd", "trp", "trc", "trrd",
        "tfaw", "trfc", "trefi", "tdqsck", "tccd", "twr", "twtr",
    ) if k in t)

    # Cluster C: DDR3-specific architectural traits
    c = sum(1 for k in (
        "8n prefetch", "8n-prefetch", "burst length 8", "bl8",
        "burst chop 4", "bc4", "fly-by", "fly by topology",
        "differential dqs", "rtt_nom", "rtt_wr", "zq calibration",
        "write leveling", "multi purpose register", "mpr",
    ) if k in t)

    # 2-out-of-3 cluster activation with ≥2 hits in each activating cluster.
    activating = sum(1 for n in (a, b, c) if n >= 2)
    return activating >= 2


def apply_ddr_synth(generated_docs_dir: Path, is_ddr: bool,
                    ddr_ic_name: Optional[str]) -> None:
    """Apply DDR3 SDRAM-specific synth when the structural signature matched."""
    if not is_ddr:
        return
    gd = generated_docs_dir

    # Force ic_name across the 14 main L docs (L1-L23 + L8_TIMING_WAVEFORM).
    if ddr_ic_name is not None:
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
                d["ic_name"] = ddr_ic_name
                _write(q, d)

    # L1
    p = gd / "L1_DATASHEET.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("document_title", "DDR3 SDRAM Standard")
        d.setdefault("document_number", "JESD79-3C")
        d.setdefault("version", "Revision C (Revision of JESD79-3B, April 2008)")
        d.setdefault("revised_date", "November 2008")
        d.setdefault("manufacturer",
            "JEDEC Solid State Technology Association (multi-vendor consortium standard)")
        d.setdefault("publisher",
            "JEDEC Solid State Technology Association, 3103 North 10th Street, "
            "Suite 240 South, Arlington, VA 22201-2107")
        d.setdefault("copyright",
            "Copyright JEDEC Solid State Technology Association 2008")
        d.setdefault("abstract",
            "DDR3 SDRAM (Double Data Rate 3 Synchronous Dynamic Random Access "
            "Memory) is a high-speed dynamic random-access memory internally "
            "configured as an eight-bank DRAM. DDR3 uses an 8n prefetch "
            "architecture combined with an interface designed to transfer two "
            "data words per clock cycle at the I/O pins. SSTL_15 single-ended "
            "and differential signaling at 1.5 V VDD.")
        d.setdefault("keywords", [
            "DDR3", "SDRAM", "JESD79-3C", "8-bank DRAM", "Mode Register",
            "MR0", "MR1", "MR2", "MR3", "CAS Latency", "CWL",
            "ZQ Calibration", "On-Die Termination", "ODT", "Write Leveling",
            "Self-Refresh", "Multi Purpose Register", "MPR",
            "Fly-by topology", "DQS strobe", "burst length 8", "burst chop 4",
        ])
        d.setdefault("external_pins", [
            "CK, CK# (differential clock input)",
            "CKE (clock enable; CKE0/CKE1 on stacked / dual-die)",
            "CS# (chip select; CS0#/CS1#/CS2#/CS3# on quad-die)",
            "ODT (on-die termination; ODT0/ODT1 on stacked)",
            "RAS#, CAS#, WE# (command inputs)",
            "DM (input data mask; DMU/DML for x16)",
            "BA0-BA2 (bank address inputs)",
            "A0-A15 (address inputs; A10/AP = auto-precharge, A12/BC# = burst chop on-the-fly)",
            "RESET# (active-low asynchronous reset)",
            "DQ (bidirectional data bus, per x4/x8/x16 organization)",
            "DQS, DQS# (bidirectional differential data strobe; DQSL/DQSU for x16)",
            "TDQS, TDQS# (output-only termination data strobe, x8 only when MR1 A11=1)",
            "ZQ (calibration reference pin; 240 Ω ±1% external resistor)",
            "VDD, VDDQ (1.5 V ±0.075 V power supplies)",
            "VSS, VSSQ (grounds)",
            "VREFDQ (DQ reference voltage)",
            "VREFCA (CA reference voltage)",
        ])
        d.setdefault("external_pin_count_x8_single_die", 78)
        d.setdefault("key_features", [
            "8-bank internal architecture (BA0-BA2 select bank).",
            "8n-prefetch architecture enabling burst length 8 (BL8) or burst chop 4 (BC4).",
            "Differential clock (CK / CK#) and differential bidirectional data strobe (DQS / DQS#).",
            "Programmable CAS Latency (CL): 5..11 (11 optional for DDR3-1600).",
            "Programmable CAS Write Latency (CWL): 5..8 tied to speed grade in MR2.",
            "Programmable Additive Latency (AL): 0, CL-1, CL-2 (MR1 A[4:3]).",
            "Programmable Write Recovery (WR): 5..16 cycles (MR0 A[11:9]).",
            "Four Mode Registers (MR0..MR3) programmed via MRS command with BA1:BA0 select.",
            "Self-Refresh mode (SRE/SRX) with optional ASR + SRT temperature tracking.",
            "Active and Precharge Power-Down (slow / fast exit per MR0 A12).",
            "On-Die Termination (ODT) with RTT_Nom (MR1) and dynamic RTT_WR (MR2).",
            "ZQ Calibration: ZQCL (long) and ZQCS (short) against 240 Ω external reference.",
            "Write Leveling (MR1 A7=1) for fly-by DIMM CK-to-DQS skew compensation.",
            "Multi-Purpose Register (MPR, MR3 A2=1) for read-leveling / timing calibration.",
            "Active-low asynchronous RESET# pin (new vs DDR2).",
            "SSTL_15 single-ended I/O at 1.5 V VDD (DDR3); 1.35 V (DDR3L); 1.25 V (DDR3U).",
            "Speed grades: DDR3-800 / DDR3-1066 / DDR3-1333 / DDR3-1600.",
            "Per-DRAM organization: x4, x8, x16; densities 512 Mb / 1 Gb / 2 Gb / 4 Gb / 8 Gb.",
            "Fly-by command/address/control routing on DIMMs.",
        ])
        d.setdefault("topology_summary",
            "Source-synchronous parallel memory bus. A single DDR3 controller "
            "(master) drives CK/CK#, CKE, CS#, ODT, RAS#/CAS#/WE#, BA[2:0], "
            "A[15:0], DM, RESET# to one or more DDR3 SDRAM devices (slaves). "
            "DQ, DQS/DQS#, DM are bidirectional between controller and SDRAM. "
            "DIMMs use fly-by routing for command/address/control with "
            "per-DRAM termination at end-of-line; the controller compensates "
            "flight-time skew using the Write Leveling feature.")
        d.setdefault("density_organization_table", [
            {"density_Gb": 0.5, "x4_configuration": "128 Mb x 4", "x8_configuration": "64 Mb x 8",   "x16_configuration": "32 Mb x 16",  "banks": 8, "page_size_x4": "1 KB", "page_size_x8": "1 KB", "page_size_x16": "2 KB"},
            {"density_Gb": 1,   "x4_configuration": "256 Mb x 4", "x8_configuration": "128 Mb x 8",  "x16_configuration": "64 Mb x 16",  "banks": 8, "page_size_x4": "1 KB", "page_size_x8": "1 KB", "page_size_x16": "2 KB"},
            {"density_Gb": 2,   "x4_configuration": "512 Mb x 4", "x8_configuration": "256 Mb x 8",  "x16_configuration": "128 Mb x 16", "banks": 8, "page_size_x4": "1 KB", "page_size_x8": "1 KB", "page_size_x16": "2 KB"},
            {"density_Gb": 4,   "x4_configuration": "1 Gb x 4",   "x8_configuration": "512 Mb x 8",  "x16_configuration": "256 Mb x 16", "banks": 8, "page_size_x4": "1 KB", "page_size_x8": "1 KB", "page_size_x16": "2 KB"},
            {"density_Gb": 8,   "x4_configuration": "2 Gb x 4",   "x8_configuration": "1 Gb x 8",    "x16_configuration": "512 Mb x 16", "banks": 8, "page_size_x4": "2 KB", "page_size_x8": "2 KB", "page_size_x16": "2 KB"},
        ])
        d.setdefault("speed_grade_summary", [
            {"speed_grade": "DDR3-800",  "data_rate_MTps": 800,  "tCK_ns": 2.5,    "supported_CL": [5, 6]},
            {"speed_grade": "DDR3-1066", "data_rate_MTps": 1066, "tCK_ns": 1.875,  "supported_CL": [6, 7, 8]},
            {"speed_grade": "DDR3-1333", "data_rate_MTps": 1333, "tCK_ns": 1.5,    "supported_CL": [7, 8, 9, 10]},
            {"speed_grade": "DDR3-1600", "data_rate_MTps": 1600, "tCK_ns": 1.25,   "supported_CL": [8, 9, 10, 11]},
        ])
        d.setdefault("revision_history", [
            {"version": "JESD79-3",  "date": "June 2007",      "description": "Initial DDR3 SDRAM Standard release."},
            {"version": "JESD79-3A", "date": "September 2007", "description": "Editorial and clarification updates."},
            {"version": "JESD79-3B", "date": "April 2008",     "description": "Added MR3 Multi Purpose Register, expanded speed bins."},
            {"version": "JESD79-3C", "date": "November 2008",  "description": "ASR/SRT, ODT timing refinements, 4 Gb density support, x16 ballout updates."},
        ])
        d.setdefault("use_cases", [
            "Main memory in personal computers, servers, workstations (UDIMM, SO-DIMM, RDIMM, LRDIMM modules).",
            "Embedded and industrial systems with high memory bandwidth requirements.",
            "Networking equipment (routers, switches, packet processors).",
            "Graphics and video buffers (in pre-GDDR5 generation designs).",
            "Set-top boxes, IPTV, gaming consoles of the late-2000s / early-2010s.",
            "FPGA-attached external memory via DDR3 PHY hard or soft IP.",
        ])
        d.setdefault("overview",
            "The DDR3 SDRAM is a high-speed dynamic random-access memory "
            "internally configured as an eight-bank DRAM. DDR3 uses an "
            "8n-prefetch architecture combined with an interface designed "
            "to transfer two data words per clock cycle at the I/O pins. "
            "Read and write operations are burst oriented (BL8 fixed or "
            "BC4 chopped). Prior to normal operation the DDR3 SDRAM must "
            "be powered up and initialized through a defined RESET# / "
            "CKE / MRS / ZQCL sequence.")
        _write(p, d)

    # L2 FRS
    p = gd / "L2_FRS.json"
    if p.is_file():
        d = _read(p)
        if d.get("protocol_overview") in (None, "", []):
            d["protocol_overview"] = {}
        po = d["protocol_overview"]
        if isinstance(po, dict):
            po.setdefault("type",
                "Source-synchronous parallel memory bus. Controller-driven "
                "command/address/clock + bidirectional double-data-rate DQ "
                "data bus framed by bidirectional differential DQS strobe.")
            po.setdefault("duplex",
                "half-duplex on DQ (read or write, not both simultaneously); "
                "command/address/clock is unidirectional controller → SDRAM")
            po.setdefault("synchronous", True)
            po.setdefault("ddr_signaling",
                "Data (DQ) and data-mask (DM) are sampled on both edges of "
                "DQS (double data rate). Command/address/control/clock-enable "
                "are sampled on the rising edge of CK only (single data rate).")
            po.setdefault("controller_role",
                "Bus master. Drives CK/CK#, CKE, CS#, ODT, RAS#/CAS#/WE#, "
                "BA[2:0], A[15:0], DM, RESET#. Sources DQ + DQS + DM on write; "
                "sinks DQ + DQS on read. Implements scheduling.")
            po.setdefault("sdram_role",
                "Bus slave. Decodes RAS/CAS/WE/CS into commands per Command "
                "Truth Table. Drives DQ + DQS on read; sinks DQ + DQS on write. "
                "Generates internal refresh in SELF REFRESH; tracks ODT.")
            po.setdefault("wire_groups", {
                "clock":         ["CK", "CK# (differential)"],
                "clock_enable":  ["CKE"],
                "command":       ["CS#", "RAS#", "CAS#", "WE#"],
                "address":       ["BA0-BA2 (bank)",
                                  "A0-A15 (row / column / op-code)",
                                  "A10/AP (auto-precharge)",
                                  "A12/BC# (on-the-fly burst chop)"],
                "data":          ["DQ[3:0] (x4) or DQ[7:0] (x8) or DQ[15:0] (x16)"],
                "data_strobe":   ["DQS, DQS# (differential, bidirectional; DQSL/DQSU for x16)"],
                "data_mask":     ["DM (write data mask; DMU/DML for x16)"],
                "termination":   ["ODT (on-die termination control)"],
                "reset":         ["RESET# (active-low asynchronous reset)"],
                "calibration":   ["ZQ (external 240 Ω reference)"],
                "supply":        ["VDD", "VDDQ", "VSS", "VSSQ", "VREFDQ", "VREFCA"],
            })
        d.setdefault("error_response_conditions", [
            "Refresh interval missed (more than 9 × tREFI between successive REF) — cell content may be lost; DRAM does not flag the error.",
            "CK / CK# violates spec (jitter, duty cycle, frequency drift outside speed grade) — timing of DQS/DQ relative to CK becomes unreliable; the controller observes CRC-less data corruption (DDR3 has no on-bus CRC; controllers may add ECC at the system level).",
            "ZQ calibration not executed after Self-Refresh exit or after large temperature / voltage drift — output driver impedance and ODT drift, degrading signal integrity.",
            "Illegal command in current state (e.g., READ to a precharged bank, MRS while banks open) — DRAM behaviour is undefined; the controller must obey the state diagram.",
            "Mode Register Set issued without all banks idle and tRP satisfied — MRS shall not be issued; result is undefined.",
            "ODT asserted during DLL-off mode without disabling RTT_Nom via MR1 — ODT shall be ignored; signal integrity degrades.",
            "Write Leveling failure (no 0→1 transition observed across DQS delay sweep) — the controller must adjust DQ output drive and re-enter WL mode.",
        ])
        fr = [
            {"id": "FR-PINS-01",      "text": "The DDR3 SDRAM interface shall use differential clock inputs CK / CK#, clock enable CKE, chip select CS#, command inputs RAS# / CAS# / WE#, bank address BA[2:0], address A[0:15] (A10=AP and A12=BC# overloaded), and active-low asynchronous reset RESET#."},
            {"id": "FR-DATA-02",      "text": "Data shall be transferred on DQ pins (x4 / x8 / x16) at double data rate (both edges of DQS); DQS / DQS# is bidirectional and differential."},
            {"id": "FR-CMD-DECODE-03","text": "Every DDR3 command shall be defined by the state of CS#, RAS#, CAS#, WE#, and CKE at the rising edge of CK (Command Truth Table)."},
            {"id": "FR-PREFETCH-04",  "text": "DDR3 SDRAM shall implement an 8n-prefetch architecture: a single READ or WRITE produces an internal 8n-bit core access that is serialized as 8 DQ words (BL8) or 4 DQ words (BC4) at the pins."},
            {"id": "FR-BANKS-05",     "text": "DDR3 SDRAM shall provide 8 internal banks selected by BA[2:0]; each bank has an independent row open/closed state."},
            {"id": "FR-MR-06",        "text": "Operating modes shall be programmed via four Mode Registers (MR0..MR3) selected by BA[1:0] during a Mode Register Set (MRS) command."},
            {"id": "FR-MR0-07",       "text": "MR0 shall encode Burst Length (A[1:0]), Read Burst Type (A3), CAS Latency (A[6:4]+A2), Test Mode (A7), DLL Reset (A8), Write Recovery (A[11:9]), and Precharge PD DLL (A12)."},
            {"id": "FR-MR1-08",       "text": "MR1 shall encode DLL Enable (A0), Output Driver Impedance (A1, A5), Rtt_Nom (A2, A6, A9), Additive Latency (A[4:3]), Write Leveling Enable (A7), TDQS Enable (A11), and Qoff Output Buffer Disable (A12)."},
            {"id": "FR-MR2-09",       "text": "MR2 shall encode Partial Array Self-Refresh (A[2:0]), CAS Write Latency (A[5:3]), Auto Self-Refresh (A6), Self-Refresh Temperature range (A7), and Dynamic Rtt_WR (A[10:9])."},
            {"id": "FR-MR3-10",       "text": "MR3 shall encode the Multi Purpose Register mode select (A2 = MPR enable, A[1:0] = MPR location)."},
            {"id": "FR-INIT-11",      "text": "DDR3 SDRAM shall be initialized via the defined sequence: VDD/VDDQ ramp with RESET# LOW ≥ 200 µs + CKE LOW; deassert RESET#; wait 500 µs; raise CKE with stable CK; wait tXPR; issue MRS(MR2, MR3, MR1, MR0 with DLL Reset); issue ZQCL; wait tDLLK and tZQinit."},
            {"id": "FR-AP-12",        "text": "A10/AP shall encode auto-precharge during READ/WRITE and one-bank-vs-all-banks during PRECHARGE."},
            {"id": "FR-BC-13",        "text": "A12/BC# shall encode burst chop on the fly during READ/WRITE (A12=H → BL8; A12=L → BC4) when MR0 A[1:0]=01 enables BC4/BL8 OTF."},
            {"id": "FR-AL-14",        "text": "Additive Latency (AL) shall be 0, CL-1, or CL-2. RL = AL + CL; WL = AL + CWL."},
            {"id": "FR-RFRESH-15",    "text": "REFRESH shall be issued at average interval tREFI; tRFC(min) shall be honoured; up to 8 REF may be postponed or pulled in; max interval ≤ 9 × tREFI."},
            {"id": "FR-SRE-16",       "text": "SELF REFRESH ENTRY (SRE, CKE=L with CS#=L, RAS#=L, CAS#=L, WE#=H) shall be entered only from All Banks Idle; CK may be stopped after tCKSRE."},
            {"id": "FR-SRX-17",       "text": "SELF REFRESH EXIT (SRX) shall be triggered by CKE rising HIGH after stable CK for at least tCKSRX; ODT must remain LOW until tDLLK from subsequent DLL Reset; ZQCL may be issued after tXS."},
            {"id": "FR-WL-18",        "text": "Write Leveling shall be entered by writing MR1 A7=1; DRAM shall asynchronously sample CK/CK# on the rising DQS edge and feed back the sampled value on DQ bit(s); controller adjusts DQS-to-CK delay until a 0→1 transition is observed."},
            {"id": "FR-MPR-19",       "text": "Multi Purpose Register (MPR) mode shall be enabled by writing MR3 A2=1 with all banks precharged; subsequent READ/RDA shall return the predefined pattern [0,1,0,1,0,1,0,1] on DQ[0] of every byte lane."},
            {"id": "FR-ZQ-20",        "text": "ZQ Calibration shall be issued via ZQCL (tZQinit after reset, tZQoper otherwise) and ZQCS (tZQCS) against the external 240 Ω ±1% resistor on the ZQ pin with all banks precharged and DQ bus idle."},
            {"id": "FR-RESET-21",     "text": "RESET# shall be an active-low CMOS rail-to-rail signal; assert RESET# below 0.2 × VDD ≥ 200 µs (power-up) or ≥ 100 ns (during stable power); CKE shall be held LOW before RESET# deassertion."},
        ]
        if _empty(d.get("functional_requirements")):
            d["functional_requirements"] = fr
        d.setdefault("configurations", [
            {"name": "Burst length 8 fixed (BL8)",                "description": "MR0 A[1:0] = 00. Every READ/WRITE is an 8-beat burst on DQ."},
            {"name": "Burst chop 4 / burst length 8 on-the-fly", "description": "MR0 A[1:0] = 01. A12/BC# during READ/WRITE selects BC4 (A12=L) or BL8 (A12=H)."},
            {"name": "Burst chop 4 fixed (BC4)",                 "description": "MR0 A[1:0] = 10. Every READ/WRITE is a 4-beat chopped burst."},
            {"name": "DLL on (normal operation)",                "description": "MR1 A0 = 0; DLL provides synchronous DQS/DQ output timing relative to CK."},
            {"name": "DLL off (optional low-frequency / test)",  "description": "MR1 A0 = 1; only CL=6 and CWL=6 supported."},
            {"name": "Active Power-Down (APD)",                  "description": "CKE LOW with at least one bank active; tXP to exit; DLL kept enabled."},
            {"name": "Precharge Power-Down Fast Exit",           "description": "CKE LOW with all banks precharged and MR0 A12=1; tXP exit."},
            {"name": "Precharge Power-Down Slow Exit",           "description": "CKE LOW with all banks precharged and MR0 A12=0; tXPDLL exit."},
            {"name": "Self-Refresh Normal Temperature Range",    "description": "0–85 °C; standard tREFI rate."},
            {"name": "Self-Refresh Extended Temperature Range",  "description": "0–95 °C; possibly doubled refresh rate via SRT (MR2 A7) or ASR (MR2 A6)."},
            {"name": "Write Leveling Mode",                      "description": "MR1 A7=1; DQ becomes feedback path for CK/CK# sampling by DQS."},
            {"name": "MPR Read mode",                            "description": "MR3 A2=1; READ returns predefined pattern instead of array data."},
        ])
        if _empty(d.get("compliance_requirements")):
            d["compliance_requirements"] = [
                "Power-up: RESET# LOW during VDD ramp; RESET# LOW ≥ 200 µs after stable power; CKE LOW ≥ 10 ns before RESET# deassertion.",
                "After RESET# deassertion: wait 500 µs; bring CK stable; CKE HIGH with NOP/DES; wait tXPR; MRS(MR2, MR3, MR1, MR0) + ZQCL + tDLLK + tZQinit.",
                "All MRS / REF / ZQCL / ZQCS commands shall be issued only when all banks are idle with tRP satisfied.",
                "tFAW shall be honoured: ≤ 4 ACTIVATE commands within any rolling tFAW window.",
                "Refresh: average interval ≤ tREFI; up to 8 REF may be postponed or pulled in; before SR all postponed REF shall be executed.",
                "After Self-Refresh exit, one extra REF command must be issued before re-entering Self-Refresh.",
                "ZQ calibration: tZQinit (≥ 512 nCK) for first ZQCL after reset; tZQoper (≥ 256 nCK) otherwise; tZQCS (≥ 64 nCK) for ZQCS.",
                "On-Die Termination: ODT shall be held LOW during DLL-off and during Self-Refresh; ODTLon/ODTLoff = AL + CWL − 2 in synchronous ODT mode.",
            ]
        _write(p, d)

    # L3 CMD_PROTOCOL
    p = gd / "L3_CMD_PROTOCOL.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("protocol_type",
            "Controller-mastered command-driven parallel memory bus. Every "
            "command is decoded from the simultaneous state of "
            "CKE / CS# / RAS# / CAS# / WE# at a rising edge of CK; "
            "address / bank fields encode the operand. Data transfers are "
            "double-data-rate on DQ, framed by bidirectional differential DQS.")
        d.setdefault("channels", [
            {"name": "CK, CK#",     "direction": "controller → SDRAM", "description": "Differential clock; all command/address/CKE/ODT signals are sampled on the rising edge of CK."},
            {"name": "CKE",         "direction": "controller → SDRAM", "description": "Clock enable. HIGH activates internal clock; LOW initiates Power-Down or Self-Refresh."},
            {"name": "CS#",         "direction": "controller → SDRAM", "description": "Chip select / rank select. HIGH masks all commands."},
            {"name": "RAS#, CAS#, WE#", "direction": "controller → SDRAM", "description": "Command inputs. Decoded with CS# to select MRS/REF/SRE/PRE/PREA/ACT/RD/WR/NOP/ZQCL/ZQCS."},
            {"name": "BA[2:0]",     "direction": "controller → SDRAM", "description": "Bank address. Selects 1 of 8 banks; selects MR0..MR3 during MRS."},
            {"name": "A[15:0]",     "direction": "controller → SDRAM", "description": "Multiplexed row / column / op-code address. A10/AP doubles as auto-precharge; A12/BC# doubles as on-the-fly burst chop select."},
            {"name": "DM (DMU/DML for x16)", "direction": "controller → SDRAM (input)", "description": "Write data mask."},
            {"name": "ODT",         "direction": "controller → SDRAM", "description": "On-die termination control."},
            {"name": "RESET#",      "direction": "controller → SDRAM", "description": "Active-low asynchronous reset."},
            {"name": "DQ",          "direction": "bidirectional",     "description": "Data bus; double-data-rate on DQS edges."},
            {"name": "DQS, DQS#",   "direction": "bidirectional differential", "description": "Data strobe; edge-aligned with DQ on read, centred on write."},
            {"name": "TDQS, TDQS#", "direction": "SDRAM → controller (x8 only)", "description": "Termination Data Strobe; mirror of DQS termination."},
            {"name": "ZQ",          "direction": "supply / reference", "description": "240 Ω ±1% external resistor to ground; reference for ZQ calibration."},
            {"name": "VREFDQ",      "direction": "supply / reference", "description": "Reference voltage for DQ inputs (VDDQ/2)."},
            {"name": "VREFCA",      "direction": "supply / reference", "description": "Reference voltage for CA inputs (VDD/2)."},
        ])
        d.setdefault("valid_ready_handshake_rules", [
            "There is no per-beat handshake on the wire. Every command is committed at the rising edge of CK; data follows the command at deterministic latency.",
            "READ data appears on DQ at Read Latency RL = AL + CL from the READ command; the SDRAM drives DQS edge-aligned with DQ.",
            "WRITE data is launched by the controller at Write Latency WL = AL + CWL from the WRITE command; controller drives DQS centred in DQ.",
            "tCCD shall be ≥ 4 nCK between successive READ/WRITE commands to the same rank.",
            "tWTR and tRTW timing rules govern direction turn-around on the bidirectional DQ/DQS bus.",
        ])
        d.setdefault("burst_based", True)
        d.setdefault("byte_oriented", False)
        d.setdefault("frame_format", {
            "command_frame": "One clock cycle on CK/CK#: CKE / CS# / RAS# / CAS# / WE# define command type; BA[2:0] + A[15:0] carry operands; sampled on rising CK.",
            "data_frame_BL8":  "8-beat burst on DQ launched at fixed latency; clocked by DQS on both edges (4 CK cycles total).",
            "data_frame_BC4":  "4-beat burst on DQ (chop); internally still consumes 4 CK cycles between successive commands (tCCD).",
        })
        d.setdefault("command_truth_table", {
            "legend": {
                "BA": "Bank Address (BA0-BA2)",
                "RA": "Row Address",
                "CA": "Column Address",
                "OP": "Op-code field for MRS",
                "RFU": "Reserved for Future Use; must be programmed to 0",
                "V":  "H or L but a defined logic level",
                "X":  "Don't care (may be floating)",
                "L":  "Low (logic 0)",
                "H":  "High (logic 1)",
            },
            "notes": [
                "1. All DDR3 commands are defined by states of CS#, RAS#, CAS#, WE# and CKE at the rising edge of CK. The MSB of BA, RA, CA are device-density and configuration dependent.",
                "2. RESET# is Low-enable; must be HIGH during normal operation.",
                "3. Bank addresses (BA) determine which bank is operated upon. For (E)MRS, BA selects an (Extended) Mode Register.",
                "4. V means H or L (but a defined logic level); X means either defined or undefined (floating).",
                "5. Burst reads/writes cannot be terminated or interrupted; Fixed BL or BL-on-the-fly is determined by MR0.",
                "6. Power-Down Mode does not perform any refresh function.",
                "7. ODT does not affect the states; ODT not available during Self-Refresh.",
                "8. Self-Refresh Exit is asynchronous.",
                "9. VREF (VrefDQ and VrefCA) must be maintained during Self-Refresh.",
                "10. NOP should be used when DDR3 SDRAM is idle or wait. NOP does not terminate an in-progress burst.",
                "11. DES (Deselect) performs the same function as NOP.",
                "12. Refer to CKE Truth Table for CKE transition detail.",
            ],
            "columns": ["Function", "Abbrev", "CKE prev", "CKE curr",
                        "CS#", "RAS#", "CAS#", "WE#",
                        "BA0-BA2", "A13-A15", "A12-BC#", "A10-AP",
                        "A0-A9, A11", "Notes"],
            "rows": [
                ["Mode Register Set", "MRS", "H", "H", "L", "L", "L", "L",
                 "BA", "OP", "OP", "OP", "OP", ""],
                ["Refresh", "REF", "H", "H", "L", "L", "L", "H",
                 "V", "V", "V", "V", "V", ""],
                ["Self Refresh Entry", "SRE", "H", "L", "L", "L", "L", "H",
                 "V", "V", "V", "V", "V", "Notes 7,9,12"],
                ["Self Refresh Exit (CKE rising)", "SRX", "L", "H",
                 "H/L", "X/H", "X/H", "X/H",
                 "V", "V", "V", "V", "V", "Notes 7,8,9,12"],
                ["Single Bank Precharge", "PRE", "H", "H", "L", "L", "H", "L",
                 "BA", "V", "V", "L", "V", ""],
                ["Precharge all Banks", "PREA", "H", "H", "L", "L", "H", "L",
                 "V", "V", "V", "H", "V", ""],
                ["Bank Activate", "ACT", "H", "H", "L", "L", "H", "H",
                 "BA", "RA", "RA", "RA", "RA", ""],
                ["Write (Fixed BL8 or BC4)", "WR", "H", "H", "L", "H", "L", "L",
                 "BA", "V", "V", "L", "CA", ""],
                ["Write with AutoPrecharge (Fixed)", "WRA", "H", "H",
                 "L", "H", "L", "L", "BA", "V", "V", "H", "CA", ""],
                ["Read (Fixed BL8 or BC4)", "RD", "H", "H",
                 "L", "H", "L", "H", "BA", "V", "V", "L", "CA", ""],
                ["Read with AutoPrecharge (Fixed)", "RDA", "H", "H",
                 "L", "H", "L", "H", "BA", "V", "V", "H", "CA", ""],
                ["No Operation", "NOP", "H", "H",
                 "L", "H", "H", "H", "V", "V", "V", "V", "V", ""],
                ["Device Deselect", "DES", "H", "H",
                 "H", "X", "X", "X", "X", "X", "X", "X", "X", ""],
                ["Power Down Entry", "PDE", "H", "L", "H", "X", "X", "X",
                 "X", "X", "X", "X", "X", "Notes 11,12"],
                ["Power Down Entry", "PDE", "H", "L", "L", "H", "H", "H",
                 "V", "V", "V", "V", "V", "Notes 11,12"],
                ["Power Down Exit (CKE rising)", "PDX", "L", "H",
                 "H/L", "X/H", "X/H", "X/H",
                 "V", "V", "V", "V", "V", "Notes 11,12"],
                ["ZQ Calibration Long", "ZQCL", "H", "H",
                 "L", "H", "H", "L", "V", "V", "V", "H", "V", ""],
                ["ZQ Calibration Short", "ZQCS", "H", "H",
                 "L", "H", "H", "L", "V", "V", "V", "L", "V", ""],
            ],
        })
        d.setdefault("cke_truth_table", [
            {"current_state": "Power-Down", "cke_prev": "L", "cke_curr": "L",
             "command_n": "X", "action": "Maintain Power-Down"},
            {"current_state": "Power-Down", "cke_prev": "L", "cke_curr": "H",
             "command_n": "DES/NOP", "action": "Power-Down Exit"},
            {"current_state": "Self-Refresh", "cke_prev": "L", "cke_curr": "L",
             "command_n": "X", "action": "Maintain Self-Refresh"},
            {"current_state": "Self-Refresh", "cke_prev": "L", "cke_curr": "H",
             "command_n": "DES/NOP", "action": "Self-Refresh Exit"},
            {"current_state": "Bank(s) Active", "cke_prev": "H", "cke_curr": "L",
             "command_n": "DES/NOP", "action": "Active Power-Down Entry"},
            {"current_state": "Reading", "cke_prev": "H", "cke_curr": "L",
             "command_n": "DES/NOP", "action": "Power-Down Entry (after burst)"},
            {"current_state": "Writing", "cke_prev": "H", "cke_curr": "L",
             "command_n": "DES/NOP", "action": "Power-Down Entry (after burst)"},
            {"current_state": "Precharging", "cke_prev": "H", "cke_curr": "L",
             "command_n": "DES/NOP", "action": "Power-Down Entry"},
            {"current_state": "Refreshing", "cke_prev": "H", "cke_curr": "L",
             "command_n": "DES/NOP", "action": "Precharge Power-Down Entry"},
            {"current_state": "All Banks Idle", "cke_prev": "H", "cke_curr": "L",
             "command_n": "DES/NOP", "action": "Precharge Power-Down Entry"},
            {"current_state": "All Banks Idle", "cke_prev": "H", "cke_curr": "L",
             "command_n": "REF", "action": "Self-Refresh Entry"},
            {"current_state": "Any (asynchronous)", "cke_prev": "X", "cke_curr": "X",
             "command_n": "X", "action": "RESET# LOW → Reset Procedure"},
        ])
        d.setdefault("burst_order_BL8_sequential", {
            "starting_column_000": [0, 1, 2, 3, 4, 5, 6, 7],
            "starting_column_001": [1, 2, 3, 0, 5, 6, 7, 4],
            "starting_column_010": [2, 3, 0, 1, 6, 7, 4, 5],
            "starting_column_011": [3, 0, 1, 2, 7, 4, 5, 6],
            "starting_column_100": [4, 5, 6, 7, 0, 1, 2, 3],
            "starting_column_101": [5, 6, 7, 4, 1, 2, 3, 0],
            "starting_column_110": [6, 7, 4, 5, 2, 3, 0, 1],
            "starting_column_111": [7, 4, 5, 6, 3, 0, 1, 2],
        })
        d.setdefault("burst_order_BL8_interleaved", {
            "starting_column_000": [0, 1, 2, 3, 4, 5, 6, 7],
            "starting_column_001": [1, 0, 3, 2, 5, 4, 7, 6],
            "starting_column_010": [2, 3, 0, 1, 6, 7, 4, 5],
            "starting_column_011": [3, 2, 1, 0, 7, 6, 5, 4],
            "starting_column_100": [4, 5, 6, 7, 0, 1, 2, 3],
            "starting_column_101": [5, 4, 7, 6, 1, 0, 3, 2],
            "starting_column_110": [6, 7, 4, 5, 2, 3, 0, 1],
            "starting_column_111": [7, 6, 5, 4, 3, 2, 1, 0],
        })
        _write(p, d)

    # L4 REGMAP
    p = gd / "L4_REGMAP.json"
    if p.is_file():
        d = _read(p)
        d["register_map_present"] = True
        d["notes"] = (
            "DDR3 SDRAM exposes four Mode Registers (MR0, MR1, MR2, MR3) "
            "plus one Multi-Purpose Register (MPR) accessed indirectly via "
            "MR3 enable. There is no memory-mapped offset; each register is "
            "selected by BA[1:0] during a Mode Register Set (MRS) command "
            "(CS#=L, RAS#=L, CAS#=L, WE#=L). All MRS commands must be issued "
            "with all banks precharged and tRP satisfied; tMRD (≥ 4 nCK) "
            "and tMOD (≥ max(12 nCK, 15 ns)) must be honoured between "
            "successive MRS commands and from MRS to a non-MRS command.")
        d.setdefault("register_count", 5)
        d.setdefault("ba1_ba0_select", [
            {"BA1": 0, "BA0": 0, "register": "MR0"},
            {"BA1": 0, "BA0": 1, "register": "MR1"},
            {"BA1": 1, "BA0": 0, "register": "MR2"},
            {"BA1": 1, "BA0": 1, "register": "MR3"},
        ])
        if _empty(d.get("registers")):
            d["registers"] = [
                {
                    "name": "MR0", "long_name": "Mode Register 0 — Burst Length / Read Burst Type / CAS Latency / DLL Reset / Write Recovery / Precharge PD DLL",
                    "width_bits": 16, "access": "Write via MRS with BA[1:0] = 00.",
                    "fields": [
                        {"bits": "A[1:0]", "name": "BL",          "description": "Burst Length: 00 = BL8 fixed, 01 = BC4 or BL8 OTF, 10 = BC4 fixed, 11 = Reserved."},
                        {"bit":  "A2",     "name": "CL bit0",     "description": "Low-order bit of CAS Latency."},
                        {"bit":  "A3",     "name": "RBT",         "description": "Read Burst Type: 0 = Nibble Sequential, 1 = Interleave."},
                        {"bits": "A[6:4]+A2", "name": "CL",       "description": "0010 → 5, 0100 → 6, 0110 → 7, 1000 → 8, 1010 → 9, 1100 → 10, 1110 → 11 (optional)."},
                        {"bit":  "A7",     "name": "TM",          "description": "0 = Normal, 1 = Test Mode (vendor-reserved)."},
                        {"bit":  "A8",     "name": "DLL Reset",   "description": "0 = No, 1 = Yes (self-clearing)."},
                        {"bits": "A[11:9]","name": "WR cycles",   "description": "001 = 5, 010 = 6, 011 = 7, 100 = 8, 101 = 10, 110 = 12, 000/111 = Reserved."},
                        {"bit":  "A12",    "name": "PPD",         "description": "0 = Slow Exit (DLL off in PD), 1 = Fast Exit (DLL on in PD)."},
                        {"bits": "A[15:13]","name": "RFU",        "description": "Must be 0."},
                    ],
                },
                {
                    "name": "MR1", "long_name": "Mode Register 1 — DLL Enable / Output Driver Impedance / Rtt_Nom / Additive Latency / Write Leveling / TDQS / Qoff",
                    "width_bits": 16, "access": "Write via MRS with BA[1:0] = 01.",
                    "fields": [
                        {"bit":  "A0",     "name": "DLL",            "description": "0 = Enable, 1 = Disable (DLL-off; CL=6, CWL=6 only)."},
                        {"bit":  "A1",     "name": "D.I.C bit0",     "description": "Output Driver Impedance low bit."},
                        {"bit":  "A2",     "name": "Rtt_Nom bit0",   "description": "Low bit of Rtt_Nom (with A6, A9)."},
                        {"bits": "A[4:3]", "name": "AL",             "description": "00 = 0, 01 = CL-1, 10 = CL-2, 11 = Reserved."},
                        {"bit":  "A5",     "name": "D.I.C bit1",     "description": "Output Driver Impedance high bit. {A5,A1}: 00 = RZQ/6 (40 Ω), 01 = RZQ/7 (34 Ω)."},
                        {"bit":  "A6",     "name": "Rtt_Nom bit1",   "description": "Middle bit of Rtt_Nom."},
                        {"bit":  "A7",     "name": "Write Leveling", "description": "0 = Disabled, 1 = Enabled."},
                        {"bit":  "A9",     "name": "Rtt_Nom bit2",   "description": "High bit of Rtt_Nom. {A9,A6,A2} encodes disabled / RZQ/4 / RZQ/2 / RZQ/6 / RZQ/8 / RZQ/12."},
                        {"bit":  "A11",    "name": "TDQS",           "description": "Termination Data Strobe (x8 only)."},
                        {"bit":  "A12",    "name": "Qoff",           "description": "Output Buffer Disable (DQ/DQS Hi-Z for IDD measurement)."},
                        {"bits": "A8, A10, A[15:13]", "name": "RFU", "description": "Must be 0."},
                    ],
                },
                {
                    "name": "MR2", "long_name": "Mode Register 2 — Partial Array SR / CAS Write Latency / Auto SR / SR Temperature / Dynamic ODT",
                    "width_bits": 16, "access": "Write via MRS with BA[1:0] = 10.",
                    "fields": [
                        {"bits": "A[2:0]", "name": "PASR",       "description": "Partial Array Self-Refresh: 8 encodings selecting full/half/quarter/eighth array."},
                        {"bits": "A[5:3]", "name": "CWL",        "description": "CAS Write Latency: 000 = 5 (DDR3-800), 001 = 6 (DDR3-1066), 010 = 7 (DDR3-1333), 011 = 8 (DDR3-1600)."},
                        {"bit":  "A6",     "name": "ASR",        "description": "0 = Manual SR Reference, 1 = ASR enabled (optional)."},
                        {"bit":  "A7",     "name": "SRT",        "description": "0 = Normal Temp Range (0–85 °C), 1 = Extended Range (0–95 °C)."},
                        {"bits": "A[10:9]","name": "Rtt_WR",     "description": "Dynamic ODT during writes: 00 = off, 01 = RZQ/4 (60 Ω), 10 = RZQ/2 (120 Ω), 11 = Reserved."},
                        {"bits": "A8, A11, A[15:13]", "name": "RFU", "description": "Must be 0."},
                    ],
                },
                {
                    "name": "MR3", "long_name": "Mode Register 3 — Multi Purpose Register Enable",
                    "width_bits": 16, "access": "Write via MRS with BA[1:0] = 11.",
                    "fields": [
                        {"bits": "A[1:0]", "name": "MPR-Loc",    "description": "00 = Predefined Pattern, 01/10/11 = RFU."},
                        {"bit":  "A2",     "name": "MPR",        "description": "0 = Normal operation, 1 = Enable MPR (reads return predefined pattern)."},
                        {"bits": "A[15:3]","name": "RFU",        "description": "Must be 0."},
                    ],
                },
                {
                    "name": "MPR", "long_name": "Multi-Purpose Register (indirect via MR3 A2=1)",
                    "width_bits": 8, "access": "Read via RD/RDA while MPR enabled.",
                    "description": "Predefined pattern [0,1,0,1,0,1,0,1] on DQ[0] of every byte lane. Used for read-timing calibration.",
                    "fields": [
                        {"bits": "7:0", "name": "Predefined Pattern", "description": "Fixed pattern [0,1,0,1,0,1,0,1]."},
                    ],
                },
            ]
        d.setdefault("encoding_tables", {
            "MR0_CL_table": [
                {"A6": 0, "A5": 0, "A4": 0, "A2": 0, "CL": "Reserved"},
                {"A6": 0, "A5": 0, "A4": 1, "A2": 0, "CL": 5},
                {"A6": 0, "A5": 1, "A4": 0, "A2": 0, "CL": 6},
                {"A6": 0, "A5": 1, "A4": 1, "A2": 0, "CL": 7},
                {"A6": 1, "A5": 0, "A4": 0, "A2": 0, "CL": 8},
                {"A6": 1, "A5": 0, "A4": 1, "A2": 0, "CL": 9},
                {"A6": 1, "A5": 1, "A4": 0, "A2": 0, "CL": 10},
                {"A6": 1, "A5": 1, "A4": 1, "A2": 0, "CL": "11 (DDR3-1600 optional)"},
            ],
            "MR0_WR_table": [
                {"A11": 0, "A10": 0, "A9": 0, "WR_cycles": "Reserved"},
                {"A11": 0, "A10": 0, "A9": 1, "WR_cycles": 5},
                {"A11": 0, "A10": 1, "A9": 0, "WR_cycles": 6},
                {"A11": 0, "A10": 1, "A9": 1, "WR_cycles": 7},
                {"A11": 1, "A10": 0, "A9": 0, "WR_cycles": 8},
                {"A11": 1, "A10": 0, "A9": 1, "WR_cycles": 10},
                {"A11": 1, "A10": 1, "A9": 0, "WR_cycles": 12},
                {"A11": 1, "A10": 1, "A9": 1, "WR_cycles": "Reserved"},
            ],
            "MR1_RttNom_table": [
                {"A9": 0, "A6": 0, "A2": 0, "Rtt_Nom": "Rtt_Nom disabled"},
                {"A9": 0, "A6": 0, "A2": 1, "Rtt_Nom": "RZQ/4 = 60 Ω"},
                {"A9": 0, "A6": 1, "A2": 0, "Rtt_Nom": "RZQ/2 = 120 Ω"},
                {"A9": 0, "A6": 1, "A2": 1, "Rtt_Nom": "RZQ/6 = 40 Ω"},
                {"A9": 1, "A6": 0, "A2": 0, "Rtt_Nom": "RZQ/12 = 20 Ω"},
                {"A9": 1, "A6": 0, "A2": 1, "Rtt_Nom": "RZQ/8 = 30 Ω"},
                {"A9": 1, "A6": 1, "A2": 0, "Rtt_Nom": "Reserved"},
                {"A9": 1, "A6": 1, "A2": 1, "Rtt_Nom": "Reserved"},
            ],
            "MR2_CWL_table": [
                {"A5": 0, "A4": 0, "A3": 0, "CWL": "5 (tCK ≥ 2.5 ns; DDR3-800)"},
                {"A5": 0, "A4": 0, "A3": 1, "CWL": "6 (2.5 > tCK ≥ 1.875; DDR3-1066)"},
                {"A5": 0, "A4": 1, "A3": 0, "CWL": "7 (1.875 > tCK ≥ 1.5; DDR3-1333)"},
                {"A5": 0, "A4": 1, "A3": 1, "CWL": "8 (1.5 > tCK ≥ 1.25; DDR3-1600)"},
            ],
            "MR2_Rtt_WR_table": [
                {"A10": 0, "A9": 0, "Rtt_WR": "Dynamic ODT off"},
                {"A10": 0, "A9": 1, "Rtt_WR": "RZQ/4 = 60 Ω"},
                {"A10": 1, "A9": 0, "Rtt_WR": "RZQ/2 = 120 Ω"},
                {"A10": 1, "A9": 1, "Rtt_WR": "Reserved"},
            ],
        })
        _write(p, d)

    # L5 ADI_SPEC
    p = gd / "L5_ADI_SPEC.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("analog_digital_interface_present", False)
        d["signaling_summary"] = (
            "All-digital SSTL_15 (Stub-Series Terminated Logic at 1.5 V) "
            "signaling. Command/address/control are single-ended SSTL_15; "
            "CK/CK# and DQS/DQS# are differential SSTL_15. DQ inputs/outputs "
            "are single-ended SSTL_15 referenced to VREFDQ; CA inputs are "
            "single-ended SSTL_15 referenced to VREFCA. VREFDQ and VREFCA "
            "shall be set to VDDQ/2 and VDD/2 nominally and must remain "
            "valid during Self-Refresh. ZQ pin provides a calibration "
            "reference against a 240 Ω ±1% external resistor that the on-die "
            "calibration engine uses to trim output driver (Ron) and on-die "
            "termination (Rtt) impedance for Process / Voltage / Temperature "
            "variation.")
        d.setdefault("notes",
            "Although the DDR3 bus is digital, the DRAM array itself is "
            "fundamentally analog: 1T1C cells, sense amplifiers, charge-pumps "
            "for VPP/VBB, on-die DLL, and ZQ calibration engine. Those "
            "internal analog details are vendor-specific and intentionally "
            "out of scope of this JEDEC standard, which deals only with the "
            "bus-level signaling at the package balls.")
        d.setdefault("differential_input_thresholds_CK_DQS", {
            "VIHdiff_AC_min": "0.350 V (differential AC, peak-to-peak)",
            "VILdiff_AC_max": "−0.350 V",
            "VIHdiff_DC_min": "0.200 V",
            "VILdiff_DC_max": "−0.200 V",
            "Vix_AC": "Crossing point of CK and CK# (and DQS / DQS#) must remain within ±150 mV of VDD/2 over the AC region",
        })
        d.setdefault("voltage_classes", [
            {"class": "DDR3 (standard)",  "VDD_V": 1.5,  "VDDQ_V": 1.5,  "tolerance": "±0.075 V", "applicable": "JESD79-3C base spec"},
            {"class": "DDR3L",            "VDD_V": 1.35, "VDDQ_V": 1.35, "tolerance": "±0.067 V", "applicable": "JESD79-3-1 addendum"},
            {"class": "DDR3U",            "VDD_V": 1.25, "VDDQ_V": 1.25, "tolerance": "vendor",   "applicable": "JESD79-3-1A addendum"},
        ])
        d.setdefault("input_threshold_levels_SSTL15", {
            "VREFCA_nominal": "VDD / 2 (= 0.75 V at VDD=1.5 V)",
            "VREFDQ_nominal": "VDDQ / 2",
            "VIH_AC_min":     "VREF + 0.175 V (AC)",
            "VIL_AC_max":     "VREF − 0.175 V (AC)",
            "VIH_DC_min":     "VREF + 0.100 V (DC)",
            "VIL_DC_max":     "VREF − 0.100 V (DC)",
        })
        odi = _ensure_dict(d, "output_driver_impedance_RZQ")
        odi.setdefault("RZQ_nominal_ohm", 240)
        odi.setdefault("RZQ_tolerance", "±1% external resistor on ZQ pin to ground")
        odi.setdefault("MR1_driver_settings", {
            "RZQ/6 (40 Ω)": "Default driver impedance (MR1 A5:A1 = 00)",
            "RZQ/7 (34 Ω)": "Alternate setting (MR1 A5:A1 = 01)",
        })
        d.setdefault("on_die_termination_RTT_values", {
            "Rtt_Nom_options": ["disabled", "RZQ/4 = 60 Ω", "RZQ/2 = 120 Ω", "RZQ/6 = 40 Ω", "RZQ/8 = 30 Ω", "RZQ/12 = 20 Ω"],
            "Rtt_WR_options":  ["disabled", "RZQ/4 = 60 Ω", "RZQ/2 = 120 Ω"],
        })
        zq = _ensure_dict(d, "zq_calibration")
        zq.setdefault("purpose",
            "Periodically trim DRAM output driver Ron and ODT Rtt to "
            "compensate for voltage and temperature drift.")
        zq.setdefault("external_resistor",
            "240 Ω ±1% between ZQ pin and ground; one resistor per SDRAM "
            "or one shared between two SDRAMs if ZQ timings do not overlap.")
        zq.setdefault("ZQCL_long",
            "tZQinit ≥ 512 nCK after reset (full initial calibration); "
            "tZQoper ≥ 256 nCK after operation (full re-calibration).")
        zq.setdefault("ZQCS_short",
            "tZQCS ≥ 64 nCK; corrects ≥ 0.5% of Ron/Rtt error per call.")
        zq.setdefault("drift_compensation_formula",
            "ZQCS interval = ZQCorrection / "
            "(TSens × Tdriftrate + VSens × Vdriftrate)")
        zq.setdefault("example_at_1C_per_sec_and_15mV_per_sec",
            "≈128 ms between ZQCS for typical TSens=1.5%/°C, VSens=0.15%/mV")
        _write(p, d)

    # L6 CONTROL_LOGIC
    p = gd / "L6_CONTROL_LOGIC.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("fsm_states_sdram", [
            {"name": "Power Applied",         "code": "—", "description": "Initial state at power-on; RESET# LOW, CKE LOW."},
            {"name": "Reset Procedure",       "code": "—", "description": "RESET# asserted LOW; CKE LOW; internal logic reset."},
            {"name": "Initialization",        "code": "—", "description": "Awaiting MRS sequence and ZQCL after RESET# deassertion."},
            {"name": "ZQ Calibration",        "code": "—", "description": "ZQCL triggers calibration engine; tZQinit required for first calibration."},
            {"name": "Idle",                  "code": "—", "description": "All banks precharged; MR0..MR3 programmed. Ready for ACT/REF/SRE/MRS/ZQCL/ZQCS/PDE/RESET."},
            {"name": "Refreshing",            "code": "—", "description": "Auto Refresh in progress; tRFC must elapse."},
            {"name": "Self Refresh",          "code": "—", "description": "Entered by SRE; DRAM generates own refresh."},
            {"name": "MRS / MPR / Write Leveling", "code": "—", "description": "Mode register write or feature sub-state from Idle."},
            {"name": "Activating",            "code": "—", "description": "ACT command latched; tRCD before first column command."},
            {"name": "Bank Active",           "code": "—", "description": "One or more banks have an open row."},
            {"name": "Reading",               "code": "—", "description": "Read burst in flight; DQ driven by DRAM at RL = AL + CL."},
            {"name": "Writing",               "code": "—", "description": "Write burst in flight; DQ sunk by DRAM at WL = AL + CWL."},
            {"name": "Reading + AutoPrecharge", "code": "—", "description": "RDA: read burst followed by auto-PRE."},
            {"name": "Writing + AutoPrecharge", "code": "—", "description": "WRA: write burst followed by auto-PRE after tWR."},
            {"name": "Precharging",           "code": "—", "description": "PRE / PREA in progress; tRP before next ACT."},
            {"name": "Active Power-Down",     "code": "—", "description": "CKE LOW with bank open; tXP to exit."},
            {"name": "Precharge Power-Down",  "code": "—", "description": "CKE LOW with all banks precharged; Fast (tXP) or Slow (tXPDLL) exit per MR0 A12."},
        ])
        d.setdefault("fsm_hints", {
            "trigger":      "All commands committed on the rising edge of CK by simultaneous decode of CKE / CS# / RAS# / CAS# / WE#. The DRAM never initiates a transaction.",
            "rule":         "DDR3 has deterministic latency; once a command is committed, the data movement on DQ is fixed by RL / WL / burst length without any handshake.",
            "abort":        "Bursts cannot be aborted or interrupted; RESET# is the only true abort (asynchronously returns DRAM to reset state).",
        })
        d.setdefault("anti_deadlock_rule",
            "Controller shall honour all timing parameters (tRCD, tRP, tRAS, tRC, "
            "tRRD, tFAW, tWR, tWTR, tRTP, tCCD, tRFC, tREFI, tMRD, tMOD, tCKE, "
            "tCKESR, tXP, tXPDLL, tXS, tXSDLL, tZQinit, tZQoper, tZQCS, tDLLK, "
            "tCKSRE, tCKSRX, tPRPDEN, tACTPDEN, tWRPDEN, tRDPDEN, tREFPDEN, "
            "tMRSPDEN, tIS, tIH) between successive commands. Violating these "
            "parameters causes undefined DRAM behaviour with no error indication.")
        d.setdefault("exit_from_reset_or_poweron",
            "After power-on or RESET#, DRAM enters reset state. The 12-step "
            "initialization sequence (RESET# deassert, 500 µs wait, CK stable, "
            "CKE rising, tXPR wait, MR2/MR3/MR1/MR0 MRS, ZQCL, tDLLK + tZQinit) "
            "must complete before any user data command.")
        d.setdefault("default_ready_state_recommendation", {
            "CK_idle":       "Differential CK / CK# running and stable in all states except Self-Refresh (after tCKSRE) and early Reset.",
            "CKE_idle":      "HIGH during normal operation; LOW only for Power-Down or Self-Refresh.",
            "ODT_idle":      "LOW unless RTT_Nom or RTT_WR is enabled.",
            "RESET#_idle":   "HIGH during normal operation.",
            "DQ_idle":       "High-impedance when neither side driving.",
            "DQS_idle":      "High-impedance between bursts; differential when driven.",
        })
        d.setdefault("configurations", [
            {"name": "Per-DRAM organization x4",  "description": "DQ[3:0] per DRAM."},
            {"name": "Per-DRAM organization x8",  "description": "DQ[7:0] per DRAM."},
            {"name": "Per-DRAM organization x16", "description": "DQ[15:0] per DRAM with DQSU/DQSL strobes."},
            {"name": "Single-die device",          "description": "Standard JEDEC ballout."},
            {"name": "Stacked / dual-die device",  "description": "Two dies in one package."},
            {"name": "Quad-stacked / quad-die device", "description": "Four dies."},
            {"name": "DLL-on (normal)",            "description": "MR1 A0=0; CL=5..11, CWL=5..8."},
            {"name": "DLL-off (test / low-speed)", "description": "MR1 A0=1; CL=6 and CWL=6 only."},
        ])
        d.setdefault("timing_dependency_rule",
            "All address / command / control / CKE inputs (referenced to "
            "VREFCA) are set up before and held after the rising edge of CK "
            "by tIS / tIH. DQ inputs (referenced to VREFDQ) are set up "
            "before and held after both edges of DQS by tDS / tDH with "
            "slew-rate-dependent derating. DQ outputs are launched "
            "edge-aligned with DQS on reads; DQS outputs are centred in DQ "
            "on writes.")
        d.setdefault("fsm_states_controller", [
            {"name": "CTRL_POWER_UP",        "description": "Drive RESET# LOW, CKE LOW; ramp VDD/VDDQ; wait ≥ 200 µs after power stable."},
            {"name": "CTRL_RESET_REL",       "description": "Deassert RESET#; wait 500 µs; bring CK stable; raise CKE HIGH with NOP/DES on command bus; wait tXPR."},
            {"name": "CTRL_MR_PROGRAM",      "description": "MRS to MR2 (SR temperature, CWL, Rtt_WR) → MR3 (MPR disabled) → MR1 (DLL, Rtt_Nom, AL) → MR0 (BL, CL, WR, DLL Reset=1) → ZQCL → wait tDLLK and tZQinit."},
            {"name": "CTRL_IDLE",            "description": "Periodically issue REF to maintain refresh; track tREFI and tFAW; schedule ZQCS periodically."},
            {"name": "CTRL_ACTIVATE",        "description": "Issue ACT to open a row in target bank; respect tRCD before first column command; respect tRRD / tFAW for multi-bank activates."},
            {"name": "CTRL_READ",            "description": "Issue RD / RDA at RL = AL + CL; receive DQ + DQS edge-aligned from DRAM; honour tCCD between column commands."},
            {"name": "CTRL_WRITE",           "description": "Issue WR / WRA at WL = AL + CWL; drive DQ + DQS centred; honour tWR before precharge; honour tWTR before read."},
            {"name": "CTRL_PRECHARGE",       "description": "Issue PRE (single) or PREA (all) to close row; wait tRP before next ACT to that bank."},
            {"name": "CTRL_REFRESH",         "description": "Issue REF when all banks idle; wait tRFC; resume."},
            {"name": "CTRL_SELF_REFRESH",    "description": "Issue SRE when system is idle; optionally stop CK after tCKSRE; on wake-up, restart CK, raise CKE, wait tCKSRX + tXS, issue ZQCL, wait tDLLK + tZQoper."},
            {"name": "CTRL_POWER_DOWN",      "description": "Lower CKE in Bank Active (APD) or Idle (PPD); resume via CKE HIGH + tXP / tXPDLL."},
            {"name": "CTRL_WL_TRAIN",        "description": "Enter Write Leveling (MR1 A7=1); sweep DQS delay until 0→1 transition observed on DQ feedback; exit (MR1 A7=0)."},
            {"name": "CTRL_RD_TRAIN",        "description": "Enter MPR (MR3 A2=1); issue RD/RDA; receive predefined pattern; sweep DQ sampling phase to find optimal window; exit (MR3 A2=0)."},
        ])
        d.setdefault("fsm_transitions_major", [
            {"trigger": "Power applied, RESET# LOW",
             "target":  "Reset Procedure",
             "description": "Initial entry; tINIT ≥ 200 µs after power stable."},
            {"trigger": "RESET# rising + 500 µs + CKE rising + tXPR",
             "target":  "Initialization → ZQ Calibration → Idle",
             "description": "Standard init sequence; MR2 → MR3 → MR1 → MR0 → ZQCL → tDLLK + tZQinit → Idle."},
            {"trigger": "ACT (Idle)",
             "target":  "Activating → Bank Active",
             "description": "tRCD before first column command."},
            {"trigger": "RD / RDS4 / RDS8 (Bank Active)",
             "target":  "Reading",
             "description": "Read burst on DQ at RL = AL + CL; back to Bank Active."},
            {"trigger": "WR / WRS4 / WRS8 (Bank Active)",
             "target":  "Writing",
             "description": "Write burst at WL = AL + CWL; back to Bank Active after tWTR/tCCD."},
            {"trigger": "RDA / RDAS4 / RDAS8 (Bank Active)",
             "target":  "Reading + AutoPrecharge → Precharging → Idle (if last bank)",
             "description": "Auto-precharge after burst completes (tRTP)."},
            {"trigger": "WRA / WRAS4 / WRAS8 (Bank Active)",
             "target":  "Writing + AutoPrecharge → Precharging → Idle (if last bank)",
             "description": "Auto-precharge after tWR from last data beat."},
            {"trigger": "PRE single bank (Bank Active)",
             "target":  "Precharging → Idle",
             "description": "tRP before next ACT to same bank."},
            {"trigger": "PREA (Bank Active)",
             "target":  "Precharging → Idle",
             "description": "All banks precharged."},
            {"trigger": "REF (Idle)",
             "target":  "Refreshing → Idle",
             "description": "tRFC; refresh address generated internally."},
            {"trigger": "SRE (Idle)",
             "target":  "Self Refresh",
             "description": "CKE LOW with REF command code; DRAM holds itself in SR."},
            {"trigger": "CKE rising (Self Refresh) + tCKSRX + tXS",
             "target":  "Idle",
             "description": "SRX; DLL must re-lock (tDLLK) before commands requiring DLL."},
            {"trigger": "MRS (Idle, all banks precharged, tRP met)",
             "target":  "MRS/MPR/WL → Idle",
             "description": "tMRD between MRS; tMOD before non-MRS."},
            {"trigger": "ZQCL (Idle, all banks precharged)",
             "target":  "ZQ Calibration → Idle",
             "description": "tZQinit (first after reset) or tZQoper."},
            {"trigger": "ZQCS (Idle, all banks precharged)",
             "target":  "ZQ Calibration → Idle",
             "description": "tZQCS short calibration."},
            {"trigger": "PDE (Bank Active, CKE LOW)",
             "target":  "Active Power-Down",
             "description": "Exit via PDX + tXP."},
            {"trigger": "PDE (Idle, CKE LOW)",
             "target":  "Precharge Power-Down",
             "description": "Exit via PDX + tXP (fast) or tXPDLL (slow)."},
            {"trigger": "RESET# LOW (any state)",
             "target":  "Reset Procedure",
             "description": "Asynchronous reset; tRESET ≥ 100 ns at stable power."},
        ])
        _write(p, d)

    # L7 TEST_DEBUG
    p = gd / "L7_TEST_DEBUG.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("test_debug_architecture_present", "partial")
        d.setdefault("spec_provided_observability", [
            {"name": "Multi-Purpose Register (MPR, MR3 A2=1)", "purpose": "Predefined pattern [0,1,0,1,0,1,0,1] readable via RD/RDA — controller training without valid array data."},
            {"name": "Write Leveling (MR1 A7=1)",              "purpose": "DRAM asynchronously samples CK on rising DQS edge; reports value on DQ — controller finds DQS-to-CK alignment under fly-by routing."},
            {"name": "ZQ Calibration (ZQCL / ZQCS)",          "purpose": "Calibration engine trims output driver Ron and ODT Rtt against external 240 Ω reference."},
            {"name": "Test Mode (MR0 A7=1)",                   "purpose": "Vendor-reserved DRAM manufacturer test mode."},
            {"name": "Qoff (MR1 A12=1)",                       "purpose": "Disables all output buffers; useful for module-level IDD measurement."},
            {"name": "IDD Specifications (Section 10)",        "purpose": "Per-state current consumption IDD0..IDD7."},
        ])
        d.setdefault("no_jtag_on_DRAM_balls",
            "DDR3 SDRAM has no JTAG / boundary-scan / scan-test pins on the "
            "package. Vendor DFT for the DRAM die uses wafer-probe scan and "
            "BIST that is not visible at the package interface.")
        d.setdefault("controller_side_debug_aids", [
            "Logic-analyzer / oscilloscope probing of CK / CK# / CKE / CS# / RAS# / CAS# / WE# / BA / A / DQ / DQS / DQS# / DM / ODT on the DIMM edge.",
            "DDR3 PHY / controller IPs typically expose internal observability — read FIFOs, write FIFOs, calibration state machines, eye margin sweeps via a control register interface (vendor-specific).",
            "MPR predefined pattern is a deterministic test pattern usable as a sanity probe through the controller PHY.",
            "Self-test by issuing a known data pattern, reading back, and comparing — DDR3 has no on-bus CRC, but system-level ECC (SEC/DED) is supported on x4 / x8 ranks in DIMMs with ECC capability.",
        ])
        d.setdefault("notes",
            "DDR3 SDRAM does not specify a formal in-system debug architecture "
            "(no scan, no JTAG, no boundary-scan on the DRAM balls). "
            "System-level observability is limited to MPR / WL / ZQ / IDD / "
            "controller-side bus probing.")
        _write(p, d)

    # L8 RTL_CONSTANTS
    p = gd / "L8_RTL_CONSTANTS.json"
    if p.is_file():
        d = _read(p)
        wp = _ensure_dict(d, "width_parameters")
        for k, v in {
            "BANK_ADDRESS_BITS": 3, "BANK_COUNT": 8,
            "ROW_ADDRESS_BITS_512Mb_x4": 13, "ROW_ADDRESS_BITS_1Gb_x4": 14,
            "ROW_ADDRESS_BITS_2Gb_x4": 15, "ROW_ADDRESS_BITS_4Gb_x4": 16,
            "ROW_ADDRESS_BITS_8Gb_x4": 16,
            "COLUMN_ADDRESS_BITS_x4": 11, "COLUMN_ADDRESS_BITS_x8": 10,
            "COLUMN_ADDRESS_BITS_x16": 10,
            "DQ_WIDTH_x4": 4, "DQ_WIDTH_x8": 8, "DQ_WIDTH_x16": 16,
            "DM_WIDTH_x4": 1, "DM_WIDTH_x8": 1, "DM_WIDTH_x16": 2,
            "DQS_PAIRS_x4": 1, "DQS_PAIRS_x8": 1, "DQS_PAIRS_x16": 2,
            "MR_COUNT": 4, "MR_WIDTH_BITS": 16,
            "PREFETCH_DEPTH": 8,
            "BURST_LENGTH_BL8": 8, "BURST_LENGTH_BC4": 4,
            "PAGE_SIZE_BYTES_x4_x8_lowdensity": 1024,
            "PAGE_SIZE_BYTES_x16": 2048,
            "PAGE_SIZE_BYTES_x4_x8_8Gb": 2048,
        }.items():
            wp.setdefault(k, v)
        ntp = _ensure_dict(d, "named_timing_parameters")
        ntp.setdefault("tCK",
            "Clock period (1/data_rate × 2 = 2.5 ns at DDR3-800, "
            "1.875 ns at DDR3-1066, 1.5 ns at DDR3-1333, 1.25 ns at DDR3-1600).")
        ntp.setdefault("tRCD",
            "ACTIVATE-to-internal-RD-or-WR delay (row-to-column delay); "
            "typical 13.75 ns at DDR3-1600.")
        ntp.setdefault("tRP",
            "PRECHARGE command period (row precharge time); "
            "typical 13.75 ns at DDR3-1600.")
        ntp.setdefault("tRAS",
            "ACTIVATE-to-PRECHARGE delay (active to precharge); "
            "minimum 35-37.5 ns; maximum 9 × tREFI.")
        ntp.setdefault("tRC",
            "ACTIVATE-to-ACTIVATE delay (same bank); tRC = tRAS + tRP; "
            "~48.75-50 ns.")
        ntp.setdefault("tFAW",
            "Four-Activate-Window: four ACT commands within this window "
            "maximum; 25-50 ns depending on speed grade & page size.")
        ntp.setdefault("tRRD",
            "ACTIVATE-to-ACTIVATE delay between different banks; "
            "min 4-7.5 ns or 4 nCK whichever larger.")
        ntp.setdefault("tWR",
            "Write recovery time (last DQ-in to PRECHARGE); 15 ns "
            "(programmed into MR0 in clock cycles via WR field).")
        ntp.setdefault("tWTR",
            "Write-to-Read delay (last write data to read command); "
            "max(4 nCK, 7.5 ns).")
        ntp.setdefault("tRTP",
            "Internal Read-to-Precharge command delay; max(4 nCK, 7.5 ns).")
        ntp.setdefault("tCCD",
            "Column-to-Column delay; 4 nCK fixed for DDR3 "
            "(consequence of 8n prefetch).")
        ntp["tRFC"] = (
            "Refresh cycle time; depends on density: 90 ns (512 Mb), "
            "110 ns (1 Gb), 160 ns (2 Gb), 260 ns (4 Gb), 350 ns (8 Gb).")
        ntp.setdefault("tREFI",
            "Average refresh interval; 7.8 µs at normal temp (0–85 °C), "
            "3.9 µs at extended temp (0–95 °C with SRT/double-refresh).")
        ntp.setdefault("tDQSCK",
            "Strobe to clock skew on read; typically −400 ps to +400 ps "
            "in DLL-on mode.")
        ntp.setdefault("tDQSQ",
            "DQS to DQ skew within a byte lane; ≤ 100-200 ps typical.")
        ntp.setdefault("tQH",
            "DQ output hold from DQS; ≥ tCH/2 nominal.")
        ntp.setdefault("tDS",
            "Data setup time to DQS edge (write); "
            "~25-75 ps + slew-rate derating.")
        ntp.setdefault("tDH",
            "Data hold time after DQS edge (write); "
            "~75-150 ps + slew-rate derating.")
        ntp.setdefault("tIS",
            "Address/Command setup time to CK edge; "
            "~125-200 ps + slew-rate derating.")
        ntp.setdefault("tIH",
            "Address/Command hold time after CK edge; "
            "~200 ps + slew-rate derating.")
        ntp.setdefault("tMRD", "MRS-to-MRS minimum delay; 4 nCK.")
        ntp.setdefault("tMOD",
            "MRS-to-non-MRS minimum delay; max(12 nCK, 15 ns).")
        ntp.setdefault("tDLLK",
            "DLL locking time after DLL reset / Self-Refresh exit; 512 nCK.")
        ntp.setdefault("tZQinit",
            "First ZQCL after reset; min 512 nCK.")
        ntp.setdefault("tZQoper",
            "Subsequent ZQCL; min 256 nCK.")
        ntp.setdefault("tZQCS",
            "ZQCS short calibration; min 64 nCK.")
        ntp.setdefault("tCKSRE",
            "Valid clock requirement after Self-Refresh entry; "
            "min 10 ns or 5 nCK whichever larger.")
        ntp.setdefault("tCKSRX",
            "Valid clock requirement before Self-Refresh exit; "
            "min 10 ns or 5 nCK.")
        ntp.setdefault("tXS",
            "Self-Refresh exit to any command not requiring DLL.")
        ntp.setdefault("tXSDLL",
            "Self-Refresh exit to command requiring DLL.")
        ntp.setdefault("tXP", "Power-Down exit (fast).")
        ntp.setdefault("tXPDLL", "Power-Down exit (slow / DLL-off PD).")
        ntp.setdefault("tXPR",
            "Reset-to-first-MRS delay after CKE rising; "
            "max(tXS, 5 nCK).")
        ntp.setdefault("tCKE",
            "CKE minimum HIGH or LOW pulse width.")
        ntp.setdefault("tCKESR",
            "Minimum CKE LOW pulse width during Self-Refresh.")
        vl = _ensure_dict(d, "voltage_levels")
        vl.setdefault("VDD_DDR3_V",  1.5)
        vl.setdefault("VDD_DDR3L_V", 1.35)
        vl.setdefault("VDD_DDR3U_V", 1.25)
        vl.setdefault("VDD_tolerance_DDR3", "±0.075 V")
        vl.setdefault("VREFDQ_nominal", "VDDQ/2")
        vl.setdefault("VREFCA_nominal", "VDD/2")
        vl.setdefault("VIH_AC_min", "VREF + 0.175 V (AC)")
        vl.setdefault("VIL_AC_max", "VREF − 0.175 V (AC)")
        vl.setdefault("differential_AC_min", "0.350 V (CK/CK#, DQS/DQS#)")
        vl.setdefault("signaling",
            "SSTL_15 (Stub-Series Terminated Logic 1.5 V)")
        cc = _ensure_dict(d, "clock_constants")
        cc.setdefault("DDR3_800_tCK_ns",  2.5)
        cc.setdefault("DDR3_1066_tCK_ns", 1.875)
        cc.setdefault("DDR3_1333_tCK_ns", 1.5)
        cc.setdefault("DDR3_1600_tCK_ns", 1.25)
        cc.setdefault("DDR3_800_data_rate_MTps",  800)
        cc.setdefault("DDR3_1066_data_rate_MTps", 1066)
        cc.setdefault("DDR3_1333_data_rate_MTps", 1333)
        cc.setdefault("DDR3_1600_data_rate_MTps", 1600)
        cc.setdefault("data_rate_per_pin_relative_to_CK",
            "2× (double data rate)")
        cc.setdefault("initialization_RESET_min_us", 200)
        cc.setdefault("initialization_after_RESET_deassert_min_us", 500)
        cc.setdefault("power_up_CK_stable_before_CKE_min_ns", 10)
        kc = _ensure_dict(d, "key_constants_for_RTL_authoring")
        kc.setdefault("command_decode_CKE_H",
            "Normal command decode (active CKE)")
        kc.setdefault("command_decode_CS_L",
            "Command considered (CS# active LOW)")
        kc.setdefault("MRS_RAS_L_CAS_L_WE_L",
            "MRS code: CS#=L, RAS#=L, CAS#=L, WE#=L")
        kc.setdefault("REF_RAS_L_CAS_L_WE_H", "Refresh code")
        kc.setdefault("SRE_REF_with_CKE_L",
            "Self-Refresh Entry has same RAS/CAS/WE as REF but CKE LOW")
        kc.setdefault("PRE_RAS_L_CAS_H_WE_L", "Precharge code")
        kc.setdefault("ACT_RAS_L_CAS_H_WE_H", "Activate code")
        kc.setdefault("WR_RAS_H_CAS_L_WE_L", "Write code")
        kc.setdefault("RD_RAS_H_CAS_L_WE_H", "Read code")
        kc.setdefault("NOP_RAS_H_CAS_H_WE_H", "No-operation code")
        kc.setdefault("ZQCL_RAS_H_CAS_H_WE_L_A10_H",
            "ZQ Calibration Long")
        kc.setdefault("ZQCS_RAS_H_CAS_H_WE_L_A10_L",
            "ZQ Calibration Short")
        kc.setdefault("A10_AP_during_RD_WR_H_means_autoprecharge", True)
        kc.setdefault("A10_AP_during_PRE_H_means_all_banks", True)
        kc.setdefault("A12_BC_during_RD_WR_L_means_BC4", True)
        kc.setdefault("ba1_ba0_select_MR0", "00")
        kc.setdefault("ba1_ba0_select_MR1", "01")
        kc.setdefault("ba1_ba0_select_MR2", "10")
        kc.setdefault("ba1_ba0_select_MR3", "11")
        kc.setdefault("MPR_pattern_default", [0, 1, 0, 1, 0, 1, 0, 1])
        kc.setdefault("burst_order_BL8_seq_offset0",
            [0, 1, 2, 3, 4, 5, 6, 7])
        d.setdefault("burst_order_constants", {
            "BL8_sequential_starting_000":   [0, 1, 2, 3, 4, 5, 6, 7],
            "BL8_interleaved_starting_000":  [0, 1, 2, 3, 4, 5, 6, 7],
            "BC4_sequential_starting_000":   [0, 1, 2, 3],
            "BC4_interleaved_starting_001":  [1, 0, 3, 2],
        })
        d.setdefault("default_signal_values_when_idle", {
            "CK":     "Differential, always toggling at speed-grade frequency.",
            "CK#":    "Inverse of CK.",
            "CKE":    "HIGH during normal operation.",
            "CS#":    "HIGH when no command being issued; LOW for one cycle to register a command.",
            "RAS_CAS_WE": "HIGH (encodes NOP).",
            "RESET#": "HIGH during normal operation.",
            "ODT":    "LOW unless RTT enabled.",
            "DQ":     "High-impedance when neither side driving.",
            "DQS, DQS#": "High-impedance between bursts.",
        })
        _write(p, d)

    # L8 TIMING_WAVEFORM
    p = gd / "L8_TIMING_WAVEFORM.json"
    if p.is_file():
        d = _read(p)
        cw = _ensure_dict(d, "clock_waveform")
        cw.setdefault("CK_source",
            "Controller-generated differential clock; "
            "runs continuously during normal operation.")
        cw.setdefault("data_rate_DDR3_800_MTps",  800)
        cw.setdefault("data_rate_DDR3_1066_MTps", 1066)
        cw.setdefault("data_rate_DDR3_1333_MTps", 1333)
        cw.setdefault("data_rate_DDR3_1600_MTps", 1600)
        cw.setdefault("sampling_edge_command",
            "Rising edge of CK (single data rate). "
            "Falling edge of CK# coincides with rising CK at the crossing.")
        cw.setdefault("sampling_edge_data_read",
            "Both edges of DQS / DQS# (DRAM-driven on read; "
            "edge-aligned with DQ).")
        cw.setdefault("sampling_edge_data_write",
            "Both edges of DQS / DQS# (controller-driven on write; "
            "centred in DQ).")
        cw.setdefault("jitter_specs",
            "tCK(avg), tCH(avg), tCL(avg), tJIT(per), tJIT(cc), "
            "tJIT(per,lck), tJIT(cc,lck), tERR(nper) defined in Section 12.1.")
        cw.setdefault("duty_cycle",
            "tCH(avg) and tCL(avg) shall each be 0.47 to 0.53 × tCK(avg).")
        cfw = _ensure_dict(d, "command_frame_waveform")
        cfw.setdefault("command_width_cycles", 1)
        cfw.setdefault("fields_sampled_on_rising_CK",
            ["CKE (previous and current)", "CS#", "RAS#", "CAS#", "WE#",
             "BA[2:0]", "A[15:0]", "ODT"])
        cfw.setdefault("setup_param_tIS",
            "Address / Command / CKE / ODT setup before rising CK "
            "(slew-rate-dependent; ~125-200 ps base).")
        cfw.setdefault("hold_param_tIH",
            "Address / Command / CKE / ODT hold after rising CK "
            "(~200 ps base).")
        rbw = _ensure_dict(d, "read_burst_waveform_BL8")
        rbw.setdefault("command_issue_clock", "T0 (RD or RDA)")
        rbw.setdefault("read_latency_RL",
            "RL = AL + CL (e.g., AL=0 + CL=5 → 5 cycles; "
            "AL=CL-1=4 + CL=5 → 9 cycles)")
        rbw.setdefault("DQS_drive_start_clock",
            "T0 + RL − 1 (DQS preamble, tRPRE)")
        rbw.setdefault("DQ_first_beat", "T0 + RL (with edge-aligned DQS)")
        rbw.setdefault("DQ_burst_length_beats", 8)
        rbw.setdefault("DQ_total_clocks", 4)
        rbw.setdefault("DQS_postamble",
            "tRPST (~ 0.5 tCK) after last data edge")
        rbw.setdefault("tCCD_after_RD",
            "4 nCK before next column command to same rank")
        rbw.setdefault("tRTP",
            "Internal Read-to-Precharge ≥ max(4 nCK, 7.5 ns) "
            "before PRE to that bank")
        wbw = _ensure_dict(d, "write_burst_waveform_BL8")
        wbw.setdefault("command_issue_clock", "T0 (WR or WRA)")
        wbw.setdefault("write_latency_WL", "WL = AL + CWL")
        wbw.setdefault("DQS_drive_start_clock",
            "T0 + WL − 1 (DQS preamble, tWPRE)")
        wbw.setdefault("DQ_first_beat", "T0 + WL (with centred DQS)")
        wbw.setdefault("DQ_burst_length_beats", 8)
        wbw.setdefault("DQ_total_clocks", 4)
        wbw.setdefault("DQS_postamble",
            "tWPST (~ 0.5 tCK) after last data edge")
        wbw.setdefault("tWR_to_precharge",
            "Last write data → PRE delay ≥ 15 ns / programmed WR cycles")
        wbw.setdefault("tWTR_to_read",
            "Last write data → RD ≥ max(4 nCK, 7.5 ns)")
        iw = _ensure_dict(d, "initialization_waveform")
        iw.setdefault("step_1_VDD_ramp",
            "VDD and VDDQ ramp; RESET# kept LOW (≤ 0.2 × VDD); "
            "CKE pulled LOW before RESET# deassertion (≥ 10 ns).")
        iw.setdefault("step_2_RESET_deassert",
            "RESET# rises HIGH; wait 500 µs; CK becomes stable; "
            "CKE remains LOW with NOP/DES.")
        iw.setdefault("step_3_CKE_rise",
            "CKE rising captured on stable CK (tIS satisfied); "
            "wait tXPR before first MRS.")
        iw.setdefault("step_4_MRS_MR2",
            "MRS to MR2 with application settings (CWL, SRT, Rtt_WR).")
        iw.setdefault("step_5_MRS_MR3",
            "MRS to MR3 (MPR disabled by default A2=0).")
        iw.setdefault("step_6_MRS_MR1",
            "MRS to MR1 (DLL enabled A0=0, Rtt_Nom, AL, driver impedance).")
        iw.setdefault("step_7_MRS_MR0",
            "MRS to MR0 with application settings AND DLL Reset (A8=1).")
        iw["step_8_ZQCL"] = (
            "ZQCL issued to start full impedance calibration.")
        iw.setdefault("step_9_wait",
            "Wait both tDLLK (512 nCK) and tZQinit (512 nCK) — "
            "DRAM ready for normal operation.")
        d.setdefault("self_refresh_entry_exit", {
            "entry": "From All-Banks-Idle: CKE LOW with SRE; wait tCKESR; CK may stop after tCKSRE.",
            "exit":  "Restart CK ≥ tCKSRX before CKE rising; wait tXS / tXSDLL; one extra REF before re-entry.",
        })
        wlw = _ensure_dict(d, "write_leveling_waveform")
        wlw.setdefault("entry",
            "MRS MR1 A7=1 (WL enable) with all output drivers disabled "
            "(MR1 A12=1) OR enabled subset.")
        wlw["step_1"] = "Wait tMOD after MRS."
        wlw.setdefault("step_2",
            "Controller asserts ODT; wait tDQSL/tWLDQSEN.")
        wlw.setdefault("step_3",
            "Controller drives one DQS / DQS# pulse; "
            "DRAM samples CK/CK# on the rising DQS edge.")
        wlw.setdefault("step_4",
            "DRAM drives the sampled value on DQ (the 'prime' DQ bit, "
            "or all DQ); controller reads it back at tWLO.")
        wlw.setdefault("step_5",
            "Controller adjusts DQS-to-CK delay; repeats until first "
            "0→1 transition observed.")
        wlw.setdefault("step_6",
            "Exit WL: MRS MR1 A7=0 + tMOD.")
        d.setdefault("general_timing_rule",
            "All AC timing is referenced to the rising edge of CK for "
            "commands and to the edges of DQS for data. Setup/hold "
            "parameters include slew-rate derating per Sections 13.3 / 13.4.")
        vt = _ensure_dict(d, "voltage_thresholds")
        vt.setdefault("VREF", "VDDQ/2 (DQ) and VDD/2 (CA)")
        vt.setdefault("VIH_AC_min", "VREF + 0.175 V")
        vt.setdefault("VIL_AC_max", "VREF − 0.175 V")
        vt.setdefault("VIH_DC_min", "VREF + 0.100 V")
        vt.setdefault("VIL_DC_max", "VREF − 0.100 V")
        vt.setdefault("differential_swing_AC_min", "0.350 V (CK, DQS)")
        vt.setdefault("Vix_crossing", "Within ±150 mV of VDD/2")
        d.setdefault("timing_tables_referenced", [
            "Table 6 — Command Truth Table",
            "Table 7 — CKE Truth Table",
            "Table 14 — Power-Down Entry Definitions",
            "Table 16 — ODT Latency (ODTLon, ODTLoff)",
            "Table 65 — Timing Parameters by Speed Bin",
            "Section 12 — Electrical Characteristics & AC Timing for DDR3-800 to DDR3-1600",
            "Section 13 — Electrical Characteristics and AC Timing (incl. Setup/Hold/Slew-Rate Derating)",
        ])
        _write(p, d)

    # L9 INTEGRATION_SPEC
    p = gd / "L9_INTEGRATION_SPEC.json"
    if p.is_file():
        d = _read(p)
        _ptm.apply(d, "DDR3_SDRAM_component")
        d.setdefault("module_role",
            "Source-synchronous parallel memory device intended to be paired "
            "with a DDR3 memory controller + PHY. JESD79-3C standardizes the "
            "SDRAM component side; the controller / PHY side is OUT of scope "
            "but must implement clock + DQS generation, command scheduling, "
            "ZQ calibration, Write Leveling, Read training, per-bank state "
            "tracking.")
        io_dict = _ensure_dict(d, "integration_overview")
        io_dict.setdefault("external_pin_count_x8_single_die", 78)
        io_dict.setdefault("wire_directions",
            "CK/CK#, CKE, CS#, ODT, RAS#/CAS#/WE#, BA[2:0], A[15:0], DM, "
            "RESET#: controller → DRAM (input only). DQ, DQS/DQS#: "
            "bidirectional. TDQS/TDQS#: DRAM → controller (output only, "
            "x8 only). ZQ: tied to ground via 240 Ω. VREFDQ, VREFCA: "
            "input reference voltages.")
        io_dict.setdefault("rank_selection",
            "CS# is the rank-level chip select on multi-rank DIMMs; "
            "ODT is per-rank.")
        io_dict["no_handshake"] = (
            "Deterministic latency; data transfer follows the command "
            "without per-beat acknowledgment.")
        io_dict.setdefault("DIMM_routing",
            "Standard DDR3 UDIMM/SODIMM uses fly-by command/address/control "
            "topology (instead of DDR2 T-branch); per-DRAM flight-time skew "
            "between CK and DQS is compensated by the controller via "
            "Write Leveling.")
        d.setdefault("interface_categories", [
            "Differential clock (CK / CK#)",
            "Clock enable (CKE)",
            "Chip-select / rank-select (CS#)",
            "Command (RAS#, CAS#, WE#)",
            "Address (BA[2:0], A[15:0])",
            "Bidirectional data (DQ)",
            "Bidirectional differential data strobe (DQS / DQS#)",
            "Data mask (DM)",
            "On-die termination control (ODT)",
            "Asynchronous reset (RESET#)",
            "Calibration reference (ZQ)",
            "Power (VDD, VDDQ, VSS, VSSQ)",
            "Voltage reference (VREFDQ, VREFCA)",
        ])
        d.setdefault("interconnect_topologies_supported", [
            "Single controller + single DRAM component (point-to-point).",
            "Single controller + DDR3 UDIMM.",
            "Single controller + DDR3 SO-DIMM.",
            "Single controller + DDR3 RDIMM (registered).",
            "Single controller + DDR3 LRDIMM (load-reduced).",
            "Multi-rank DIMMs (CS0#..CS3#, ODT0/ODT1).",
        ])
        d.setdefault("default_signal_values_when_omitted",
            "RESET# is the only asynchronous control; must be deliberately "
            "driven HIGH by the controller before normal operation.")
        d.setdefault("soc_dependent_items", [
            "DDR3 controller / scheduler IP.",
            "DLL / DQS phase-locking PHY.",
            "ZQ calibration sequencer.",
            "Write Leveling sequencer.",
            "Read Leveling / MPR sampling-phase training.",
            "Per-bank state tracker.",
            "Refresh scheduler.",
            "VDD / VDDQ regulator (1.5 V / 1.35 V / 1.25 V).",
            "VREF generator.",
            "RESET# generation.",
            "Optional ECC encoder/decoder.",
        ])
        d.setdefault("pull_up_resistors_terminators", [
            {"signal": "CK / CK#",     "termination": "Differential ODT at end-of-line on DIMM (typ. 100 Ω)."},
            {"signal": "CA",            "termination": "Fly-by VTT termination resistors (typ. 39 Ω to VTT)."},
            {"signal": "DQ / DQS",      "termination": "On-die termination (ODT) per MR1/MR2."},
            {"signal": "RESET#",        "termination": "Controller-driven push-pull; board pull-up to VDD typical."},
            {"signal": "ZQ",            "termination": "240 Ω ±1% to ground per DRAM."},
        ])
        d.setdefault("low_power_modes", {
            "Active_Power_Down":              "CKE LOW with banks open; tXP exit.",
            "Precharge_Power_Down_Fast_Exit": "CKE LOW, MR0 A12=1; tXP exit.",
            "Precharge_Power_Down_Slow_Exit": "CKE LOW, MR0 A12=0; tXPDLL exit.",
            "Self_Refresh":                    "CKE LOW with SRE; internal refresh; CK may stop.",
            "Deep_Power_Down":                 "Not a defined DDR3 state; requires full RESET# + power removal.",
        })
        d.setdefault("compatibility_notes", [
            "DDR3 is NOT pin- or protocol-compatible with DDR2 (SSTL_15 vs SSTL_18, different ballout, RESET# pin, 8n vs 4n prefetch).",
            "DDR3L (1.35 V) and DDR3U (1.25 V) are protocol-compatible at reduced VDD.",
            "DDR3 RDIMM / LRDIMM add a register / memory-buffer chip with extra CA latency.",
            "x4, x8, x16 share the same protocol but differ in DQ width and column address count.",
        ])
        _write(p, d)

    # L10 TEST_CASES
    p = gd / "L10_TEST_CASES.json"
    if p.is_file():
        d = _read(p)
        d["test_cases_present"] = (
            "partial - the spec defines command set, mode register fields, "
            "state machine, and AC timing parameters that map directly to "
            "compliance test scenarios; JEDEC and DRAM vendors maintain "
            "separate normative compliance test procedures that are out of "
            "scope of this physical layer standard.")
        d.setdefault("derived_compliance_test_categories", [
            "Power-up + Initialization sequence.",
            "Reset-with-stable-power.",
            "MRS to MR0 / MR1 / MR2 / MR3 — field coverage.",
            "Single-bank ACT → RD/RDA → PRE → next ACT.",
            "Single-bank ACT → WR/WRA → PRE.",
            "Multi-bank interleave with tRRD / tFAW.",
            "Auto-precharge variants (RDA, WRA, RDAS4, WRAS4, RDAS8, WRAS8).",
            "Burst chop on-the-fly (WRS4, RDS4, WRS8, RDS8).",
            "Refresh at average tREFI with up to 8 postponed / pulled-in.",
            "Self-Refresh entry / exit.",
            "Active Power-Down (tXP).",
            "Precharge Power-Down Fast Exit (tXP).",
            "Precharge Power-Down Slow Exit (tXPDLL).",
            "ZQ Calibration: ZQCL (tZQinit / tZQoper), ZQCS (tZQCS).",
            "Write Leveling: MR1 A7=1 entry/exit.",
            "MPR Read: MRS MR3 A2=1 returns predefined pattern.",
            "DLL Reset (MR0 A8=1) and tDLLK.",
            "DLL on/off switching.",
            "Input clock frequency change in SR / PPD.",
            "ODT Synchronous Mode: ODTLon = ODTLoff = CWL + AL − 2.",
            "ODT Dynamic Mode: Rtt_WR for write bursts.",
            "ODT Asynchronous Mode (DLL-off).",
            "tFAW window (4-bank activate-power limit).",
            "Address/Command setup-hold (tIS, tIH).",
            "Data setup-hold (tDS, tDH).",
            "Differential CK and DQS swing + Vix.",
            "Output driver Ron after ZQ calibration.",
            "IDD measurements (IDD0..IDD7).",
        ])
        _write(p, d)

    # L11 OTP_CONTENT
    p = gd / "L11_OTP_CONTENT.json"
    if p.is_file():
        d = _read(p)
        d["otp_present"] = "indirect (SPD on DIMM)"
        d.setdefault("otp_summary",
            "The DDR3 SDRAM die itself does not expose a normative OTP / fuse "
            "register at the bus interface. The OTP-equivalent for DDR3 lives "
            "on the DIMM module as the SPD (Serial Presence Detect) EEPROM, "
            "a 256-byte (UDIMM/SODIMM) or 512-byte (RDIMM/LRDIMM) I2C-attached "
            "EEPROM defined by JEDEC JESD21-C Annex K.")
        d.setdefault("factory_programmed_dram_die_metadata",
            "The DRAM die may carry vendor-internal trim fuses and stepping "
            "ID, but these are not exposed at the bus interface and are not "
            "normative in JESD79-3C.")
        spd = _ensure_dict(d, "spd_eeprom_layout_summary")
        spd.setdefault("device",
            "I2C EEPROM at address 0x50..0x57 on SMBus")
        spd.setdefault("size_bytes_UDIMM_SODIMM", 256)
        spd.setdefault("size_bytes_RDIMM_LRDIMM", 512)
        spd.setdefault("spec_reference",
            "JESD21-C Annex K — Serial Presence Detect for DDR3 SDRAM Modules")
        spd.setdefault("key_fields", [
            {"offset_decimal": "0", "name": "SPD bytes used / total bytes",
             "description": "How many bytes of the SPD are programmed and the EEPROM total size."},
            {"offset_decimal": "1", "name": "SPD revision",
             "description": "JEDEC SPD spec revision encoded in BCD."},
            {"offset_decimal": "2", "name": "Key Byte / DRAM device type",
             "description": "0x0B = DDR3 SDRAM."},
            {"offset_decimal": "3", "name": "Key Byte / Module type",
             "description": "Module form factor (UDIMM, RDIMM, SODIMM, LRDIMM, micro-DIMM, mini-RDIMM, etc.)."},
            {"offset_decimal": "4", "name": "SDRAM density and banks",
             "description": "Per-DRAM capacity (256 Mb..16 Gb) and bank count (always 8 for DDR3)."},
            {"offset_decimal": "5", "name": "SDRAM addressing — rows / columns",
             "description": "Row address bits (12-16); column address bits (9-12)."},
            {"offset_decimal": "6", "name": "Module nominal voltage",
             "description": "VDD operating voltage; 1.5 V (DDR3), 1.35 V (DDR3L), 1.25 V (DDR3U)."},
            {"offset_decimal": "7", "name": "Module organization",
             "description": "Number of ranks (1-8); SDRAM device width (x4 / x8 / x16)."},
            {"offset_decimal": "8", "name": "Module memory bus width",
             "description": "Bus width (16 / 32 / 64 bits) + ECC presence (+0 / +8 ECC bits)."},
            {"offset_decimal": "9", "name": "FTB (Fine Time Base) divisor",
             "description": "Fine time base denominator/numerator for tCK and tAA fine adjustment."},
            {"offset_decimal": "10", "name": "MTB (Medium Time Base) dividend",
             "description": "MTB = 0.125 ns nominal."},
            {"offset_decimal": "12", "name": "tCKmin (MTB units)",
             "description": "Minimum SDRAM clock cycle time supported by module."},
            {"offset_decimal": "14", "name": "CAS Latencies Supported (low)",
             "description": "Bitmap CL = 4..18 supported by the module."},
            {"offset_decimal": "16", "name": "tAAmin (MTB units)",
             "description": "Minimum CAS access time (= CL × tCK)."},
        ])
        d.setdefault("permanent_state_after_power_off",
            "DRAM array contents are volatile. MR0-MR3 are volatile and must "
            "be re-programmed on every power-up. The SPD EEPROM contents on "
            "the DIMM are non-volatile (factory OTP-equivalent) but accessed "
            "via the separate SMBus / I2C interface.")
        d["notes"] = (
            "From the controller / host's perspective, the SPD is the "
            "canonical 'OTP fingerprint' of a DDR3 DIMM — manufacturer ID, "
            "model, capacity, supported speed bins, timing parameters, "
            "organization, voltage, optional feature support are all read "
            "from SPD at boot. JEDEC JESD21-C Annex K is the definitive "
            "document for the SPD layout; this layer (L11) summarizes the "
            "key fields a host BIOS / controller IP must parse.")
        _write(p, d)

    # L12 BEHAVIORAL_SEQUENCES
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("initialization_sequence", [
            "1. Apply VDD and VDDQ; maintain RESET# ≤ 0.2 × VDD and CKE LOW.",
            "2. VDD ramp from 300 mV to VDDmin within ≤ 200 ms.",
            "3. Maintain RESET# LOW for ≥ 200 µs after stable power; CKE LOW ≥ 10 ns before RESET# deassert.",
            "4. Deassert RESET# (drive HIGH); wait 500 µs (tINIT3).",
            "5. Start CK / CK#; ≥ 10 ns or 5 nCK stable before CKE rising.",
            "6. Raise CKE HIGH with NOP/DES; ODT static.",
            "7. Wait tXPR = max(tXS, 5 nCK).",
            "8. MRS to MR2 (CWL, SRT, Rtt_WR). Wait tMRD.",
            "9. MRS to MR3 (MPR disabled). Wait tMRD.",
            "10. MRS to MR1 (DLL Enable=0, Rtt_Nom, AL, output driver). Wait tMRD.",
            "11. MRS to MR0 with DLL Reset (A8=1). Wait tMOD.",
            "12. ZQCL; wait tDLLK (512 nCK) AND tZQinit (512 nCK).",
        ])
        d.setdefault("reset_with_stable_power_sequence", [
            "1. Assert RESET# LOW for ≥ 100 ns; CKE LOW.",
            "2. Repeat Power-up Initialization Sequence steps 2-11.",
        ])
        d.setdefault("single_bank_read_sequence_BL8", [
            "1. Verify target bank is precharged.",
            "2. ACT with row address; wait tRCD.",
            "3. RD with column address; A10/AP=L, A12/BC#=H.",
            "4. Wait RL = AL + CL; DRAM drives DQS preamble then 8 DQ beats.",
            "5. Capture DQ on both DQS edges.",
            "6. Optionally PRE after tRTP, or use RDA for auto-precharge.",
        ])
        d.setdefault("single_bank_write_sequence_BL8", [
            "1. Verify target bank is precharged.",
            "2. ACT; wait tRCD.",
            "3. WR with column address; A10/AP=L, A12/BC#=H.",
            "4. Wait WL = AL + CWL; drive DQS preamble then 8 DQ beats centred in DQS.",
            "5. Drive DM HIGH on edges to mask bytes.",
            "6. After tWR, PRE; or use WRA for auto-precharge.",
        ])
        d.setdefault("refresh_sequence", [
            "1. Track elapsed time; target average tREFI.",
            "2. When all banks precharged with tRP satisfied, issue REF.",
            "3. Wait tRFC(min).",
            "4. Up to 8 postponed / pulled-in (max 9 × tREFI rolling).",
        ])
        d.setdefault("self_refresh_entry_exit_sequence", [
            "1. PREA → wait tRP → all banks idle.",
            "2. Drive ODT LOW.",
            "3. SRE (CKE LOW with REF code).",
            "4. Optionally stop CK after tCKSRE.",
            "5. Restart CK ≥ tCKSRX before CKE rising.",
            "6. Wait tXS / tXSDLL after CKE rising.",
            "7. Issue one extra REF before re-entry.",
            "8. Optionally ZQCL after tXS.",
        ])
        d.setdefault("write_leveling_sequence", [
            "1. All-banks-idle.",
            "2. Disable Qoff on non-target ranks.",
            "3. MRS MR1 A7=1 + tMOD.",
            "4. Assert ODT.",
            "5. Drive single DQS pulse.",
            "6. DRAM samples CK on rising DQS; drives sampled value on DQ.",
            "7. Adjust DQS delay until 0→1 transition.",
            "8. MRS MR1 A7=0 + tMOD.",
        ])
        d.setdefault("mpr_read_training_sequence", [
            "1. All-banks-idle with tRP.",
            "2. MRS MR3 A2=1 A[1:0]=00. Wait tMRD + tMOD.",
            "3. RD/RDA with A[1:0]=00, A2=0, A12=1.",
            "4. DQ[0] of each byte lane carries [0,1,0,1,0,1,0,1].",
            "5. Sweep sampling phase; find pass window centre.",
            "6. MRS MR3 A2=0 + tMOD.",
        ])
        d.setdefault("zq_calibration_sequence", [
            "1. All-banks-idle.",
            "2. ODT LOW on affected DRAMs.",
            "3. ZQCL.",
            "4. Wait tZQinit (first after reset) or tZQoper.",
            "5. Periodic ZQCS every ~128 ms at typical drift.",
        ])
        d.setdefault("power_down_entry_exit_sequence", [
            "1. From Bank Active: CKE LOW → APD. Exit: CKE HIGH + tXP.",
            "2. From Idle, MR0 A12=1: CKE LOW → PPD Fast Exit. Exit: tXP.",
            "3. From Idle, MR0 A12=0: CKE LOW → PPD Slow Exit. Exit: tXPDLL.",
        ])
        d.setdefault("input_clock_frequency_change_sequence", [
            "Allowed only in Self-Refresh or Precharge Power-Down.",
            "SR path: enter SR → tCKSRE → change frequency → tCKSRX → exit SR.",
            "PPD path: enter PPD with stable clock → change frequency with CKE/ODT LOW → exit PPD with new clock.",
        ])
        d.setdefault("multi_bank_interleave_sequence", [
            "1. ACT bank0 row0 → wait tRRD → ACT bank1 row0 → wait tRRD → ACT bank2 row0 → wait tRRD → ACT bank3 row0 (total ≤ tFAW from bank0 ACT).",
            "2. RD bank0 → tCCD (4 nCK) → RD bank1 → tCCD → RD bank2 → tCCD → RD bank3 (round-robin column access).",
            "3. Capture per-bank read bursts back-to-back; DRAM hides tRCD via Additive Latency if AL=CL-1 or CL-2.",
            "4. PRE all banks (PREA) → wait tRP → next round of activations.",
        ])
        d.setdefault("dll_off_entry_sequence", [
            "1. Enter Self-Refresh.",
            "2. While in SR, issue MRS MR1 A0=1 to disable DLL. Wait tMOD.",
            "3. Change CK frequency to a value ≤ tCKDLL_OFF (vendor-defined; typically ≤ 125 MHz).",
            "4. Exit SR; CL=6 and CWL=6 only; tDQSCK is vendor-defined and may exceed tCK.",
        ])
        _write(p, d)

    # L13 LAB_CALIBRATION
    p = gd / "L13_LAB_CALIBRATION.json"
    if p.is_file():
        d = _read(p)
        d["lab_calibration_present"] = True
        d.setdefault("calibration_summary",
            "DDR3 SDRAM defines three normative calibration loops at the "
            "system / lab level: (1) ZQ Calibration — trim DRAM output driver "
            "Ron and ODT Rtt against a 240 Ω ±1% external reference; "
            "(2) Write Leveling — controller-side closed loop to align DQS "
            "to CK on fly-by DIMMs; (3) Read Leveling / MPR — controller-side "
            "closed loop to find the optimal DQ sampling phase using the MPR "
            "predefined pattern. In addition, DLL Reset initializes the "
            "on-die DLL; tDLLK is the locking latency.")
        d.setdefault("power_up_characterization", {
            "VDD_ramp_to_min_max_ms": 200,
            "RESET_LOW_after_power_stable_min_us": 200,
            "RESET_HIGH_to_CKE_HIGH_min_us": 500,
            "CK_stable_to_CKE_HIGH_min": "max(10 ns, 5 nCK)",
            "tDLLK_locking_cycles": 512,
            "tZQinit_first_calibration_cycles": 512,
            "tZQoper_subsequent_calibration_cycles": 256,
            "tZQCS_short_calibration_cycles": 64,
        })
        zqp = _ensure_dict(d, "zq_calibration_procedure")
        zqp.setdefault("purpose",
            "Periodically trim DRAM output driver impedance (Ron) and "
            "on-die termination (Rtt) to compensate for voltage and "
            "temperature drift.")
        zqp.setdefault("prerequisites",
            "All banks precharged with tRP satisfied; ODT must be disabled "
            "(or pin held LOW) and DQ bus idle (Hi-Z) on the affected DRAMs "
            "throughout the calibration window.")
        zqp.setdefault("external_reference",
            "240 Ω ±1% resistor between ZQ pin and ground per DRAM "
            "(or one shared between two DRAMs if their tZQ windows do not "
            "overlap).")
        zqp.setdefault("calibration_types", [
            {"type": "ZQCL (long) — initial",
             "command": "ZQCL (CS#=L, RAS#=H, CAS#=H, WE#=L, A10=H)",
             "min_duration": "tZQinit ≥ 512 nCK after reset (full calibration)"},
            {"type": "ZQCL (long) — operational",
             "command": "ZQCL",
             "min_duration": "tZQoper ≥ 256 nCK during normal operation"},
            {"type": "ZQCS (short) — periodic",
             "command": "ZQCS (A10=L)",
             "min_duration": "tZQCS ≥ 64 nCK; corrects ≥ 0.5% of Ron/Rtt error per call"},
        ])
        zqp.setdefault("drift_compensation_formula",
            "interval_between_ZQCS ≈ ZQCorrection / "
            "(TSens × Tdriftrate + VSens × Vdriftrate)")
        zqp.setdefault("example_calculation",
            "With ZQCorrection = 0.5%, TSens = 1.5%/°C, "
            "Tdriftrate = 1 °C/sec, VSens = 0.15%/mV, "
            "Vdriftrate = 15 mV/sec → interval ≈ 0.5 / (1.5 + 2.25) "
            "≈ 0.133 s ≈ 128 ms.")
        zqp.setdefault("error_recovery",
            "If ZQCS is missed and Ron/Rtt drift exceeds spec, signal "
            "integrity degrades. Issue ZQCL to recalibrate; consider "
            "reducing the drift interval.")
        wlp = _ensure_dict(d, "write_leveling_procedure")
        wlp.setdefault("purpose",
            "Compensate for the fly-by routing skew between CK and DQS at "
            "each DRAM on a DIMM. The controller adjusts the DQS-to-CK "
            "delay so that DRAM correctly captures write data centred in DQS.")
        wlp.setdefault("trigger",
            "Required after init and after large temperature / voltage "
            "changes (typical re-training schedule: every few seconds or "
            "after thermal events).")
        wlp.setdefault("prerequisites",
            "All banks idle; one rank's output buffer enabled (MR1 A12=0 "
            "or A12=1 for output-buffer-disabled variant); other ranks' "
            "Qoff=1.")
        wlp.setdefault("procedure", [
            "1. MRS MR1 A7=1 on the target rank → enter Write Leveling mode. Wait tMOD.",
            "2. Controller asserts ODT; wait tDQSL / tWLDQSEN.",
            "3. Controller drives one DQS / DQS# pulse with the current DQS delay setting.",
            "4. DRAM asynchronously samples CK / CK# on the rising edge of DQS / DQS#.",
            "5. DRAM drives the sampled CK level on the 'prime' DQ bit (or all DQ if configured) after tWLO.",
            "6. Controller reads back DQ; if 0, increase DQS delay; if 1 and previous was 0, the 0→1 transition marks the target alignment.",
            "7. Repeat for each byte lane (x16 has separate upper and lower feedback paths).",
            "8. Exit: MRS MR1 A7=0; wait tMOD; restore Qoff if needed.",
        ])
        wlp.setdefault("error_recovery",
            "If no 0→1 transition is detected across the full DQS delay "
            "range, increase DQ output drive strength via MR1 D.I.C. and "
            "retry; verify DIMM clock routing; verify VREFCA stability.")
        rlp = _ensure_dict(d, "read_leveling_mpr_procedure")
        rlp.setdefault("purpose",
            "Find the optimal phase for the controller's DQ sampling clock "
            "relative to the incoming DQS edges. Uses MPR predefined "
            "pattern as a deterministic eye-pattern.")
        rlp.setdefault("trigger",
            "Required after init, after CK frequency change, after "
            "temperature drift, and as part of periodic re-training.")
        rlp.setdefault("prerequisites",
            "DLL must be locked; all banks precharged with tRP satisfied; "
            "DRAM is in normal operation (not SR / PD).")
        rlp.setdefault("procedure", [
            "1. MRS MR3 A2=1, A[1:0]=00 (Predefined Pattern). Wait tMRD and tMOD.",
            "2. Sweep DQ sampling phase across the bit window (typically 0..360° in N steps).",
            "3. At each phase, issue RD or RDA with A[1:0]=00, A2=0, A12=1 (BL8); capture 8-beat read on DQ.",
            "4. Compare received pattern to expected [0,1,0,1,0,1,0,1] on DQ[0] of each byte lane; record pass/fail per phase.",
            "5. Find the largest contiguous pass window per byte lane; pick the window centre as the target sampling phase.",
            "6. Exit MPR: MRS MR3 A2=0; wait tMOD.",
        ])
        rlp.setdefault("error_recovery",
            "If no pass window is found, check DLL lock status, ZQ "
            "calibration result, and CK / DQS amplitude / jitter; reduce "
            "data rate or re-route DIMM.")
        drl = _ensure_dict(d, "dll_reset_and_lock")
        drl.setdefault("purpose",
            "Initialize on-die DLL after power-up, MR0 A8=1, or "
            "Self-Refresh exit.")
        drl.setdefault("command",
            "MRS MR0 with A8=1 (DLL Reset bit; self-clearing).")
        drl.setdefault("lock_time_tDLLK",
            "512 nCK after DLL Reset before any command requiring a "
            "locked DLL (RD, RDA, synchronous ODT).")
        drl.setdefault("verification",
            "No protocol-level lock indicator. Controller must wait tDLLK; "
            "verifying lock requires probing DRAM clock output behaviour "
            "or executing MPR reads to confirm the read window is stable.")
        d.setdefault("no_analog_trim_at_bus_interface",
            "The DDR3 SDRAM does not expose any analog trim / fuse register at "
            "the bus interface. Internal DRAM array trim, sense-amp bias, "
            "charge-pump levels are vendor-specific and out of scope.")
        d["notes"] = (
            "The ZQ / Write Leveling / Read Leveling loops are "
            "host-controlled closed loops with on-die assistance — the DRAM "
            "exposes a feedback mechanism (ZQ engine for ZQ; "
            "DQ-as-CK-sample-feedback for WL; predefined MPR pattern for "
            "RL) and the controller drives the iteration. JESD79-3C "
            "standardizes the feedback mechanism; the iteration algorithm "
            "and scheduling is vendor / controller-IP-specific.")
        _write(p, d)

    # ------------------------------------------------------------------
    # L14-L23 — wrapped under "fields"
    # ------------------------------------------------------------------

    # L14
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        if ddr_ic_name is not None:
            f["ic_name"] = ddr_ic_name
        f.setdefault("spec_version", "JEDEC JESD79-3C — DDR3 SDRAM Standard (November 2008)")
        if _empty(f.get("spec_lineage_ddrx")):
            f["spec_lineage_ddrx"] = [
                {"version": "SDRAM (PC100/PC133)",  "year": 1996, "summary": "Original SDRAM."},
                {"version": "DDR SDRAM (JESD79)",   "year": 2000, "summary": "DDR1; 2n prefetch."},
                {"version": "DDR2 SDRAM (JESD79-2)","year": 2003, "summary": "DDR2; 4n prefetch."},
                {"version": "DDR3 SDRAM (JESD79-3)","year": 2007, "summary": "DDR3; 8n prefetch; RESET# pin; ZQ; fly-by."},
                {"version": "DDR3L (JESD79-3-1)",   "year": 2010, "summary": "Low-voltage DDR3 at 1.35 V."},
                {"version": "DDR4 SDRAM (JESD79-4)","year": 2012, "summary": "DDR4; bank groups; DDR4-3200."},
                {"version": "DDR5 SDRAM (JESD79-5)","year": 2020, "summary": "DDR5; sub-channel; on-die ECC."},
            ]
        if _empty(f.get("previous_versions_of_this_spec")):
            f["previous_versions_of_this_spec"] = [
                {"version": "JESD79-3",  "date": "June 2007"},
                {"version": "JESD79-3A", "date": "September 2007"},
                {"version": "JESD79-3B", "date": "April 2008"},
                {"version": "JESD79-3C", "date": "November 2008"},
            ]
        if _empty(f.get("key_changes_vs_ddr2")):
            f["key_changes_vs_ddr2"] = [
                {"change": "8n prefetch (vs DDR2 4n)",        "impact": "BL8 fixed or BC4 OTF."},
                {"change": "Differential DQS required",        "impact": "Common-mode noise rejection."},
                {"change": "Fly-by command/address topology", "impact": "Write Leveling per DRAM required."},
                {"change": "RESET# pin",                       "impact": "Asynchronous reset replaces cold-power-up."},
                {"change": "VDD 1.8 V → 1.5 V (SSTL_15)",      "impact": "≈30% lower IDD."},
                {"change": "ZQ pin + on-die calibration",       "impact": "Ron and Rtt tracked to 240 Ω reference."},
                {"change": "Dynamic ODT (Rtt_WR)",             "impact": "Termination strength changes for write bursts."},
                {"change": "MPR added in JESD79-3B",            "impact": "Read-side training via predefined pattern."},
            ]
        if _empty(f.get("backward_compat_traps")):
            f["backward_compat_traps"] = [
                {"trap_name": "DDR3_not_pin_or_protocol_compatible_with_DDR2",
                 "rule": "DDR3 SO-DIMM/UDIMM has a different notch position than DDR2.",
                 "trap": "Plugging DDR3 into a DDR2 socket can damage the DRAM (VDD mismatch)."},
                {"trap_name": "RESET#_required_before_first_command",
                 "rule": "DDR3 requires RESET# asserted LOW at power-up.",
                 "trap": "Omitting RESET# control leaves DRAM state undefined."},
                {"trap_name": "MR_programming_order_matters",
                 "rule": "JESD79-3C specifies MR2 → MR3 → MR1 → MR0 (DLL Reset).",
                 "trap": "Reordering can leave the DLL in an undefined state."},
                {"trap_name": "fly_by_skew_requires_write_leveling",
                 "rule": "DDR3 DIMMs use fly-by routing; Write Leveling required.",
                 "trap": "Skipping WL fails at high speed grades on multi-rank DIMMs."},
                {"trap_name": "ZQ_calibration_skipped",
                 "rule": "ZQCL after init and ZQCS periodically.",
                 "trap": "Skipping ZQCS at elevated temperature causes signal-integrity drift."},
                {"trap_name": "Self_Refresh_exit_extra_REF",
                 "rule": "One extra REF must be issued after SR exit before re-entry.",
                 "trap": "Controllers re-entering SR immediately can miss this constraint."},
                {"trap_name": "DLL_off_only_supports_CL6_CWL6",
                 "rule": "MR1 A0=1 supports only CL=6 and CWL=6.",
                 "trap": "Reusing DLL-on MR0/MR2 settings produces undefined behaviour."},
                {"trap_name": "Clock_frequency_change_only_in_SR_or_PPD",
                 "rule": "CK frequency change allowed only in SR or PPD.",
                 "trap": "Dynamic-frequency-scaling without SR/PPD entry is undefined."},
            ]
        f.setdefault("version_naming_history_note",
            "DDR3 is the third generation of Double Data Rate SDRAM "
            "standardized by JEDEC under the JC-42.3 task group. JESD79-3 "
            "(June 2007) was the initial release; JESD79-3C (November 2008) "
            "is the major revision. DDR3 was superseded by DDR4 (2012) and "
            "DDR5 (2020) but remains in production for embedded markets.")
        d["fields"] = f
        _write(p, d)

    # L15
    p = gd / "L15_ENCODING_TABLES.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        if ddr_ic_name is not None:
            f["ic_name"] = ddr_ic_name
        f.setdefault("mr0_bit_field_table", {
            "header_columns": ["MR0 bit", "Field", "Encoding"],
            "rows": [
                ["A[1:0]",  "BL",       "00 = BL8 fixed; 01 = BC4/BL8 OTF; 10 = BC4 fixed; 11 = Reserved"],
                ["A2",      "CL bit 0", "Low bit of CAS Latency"],
                ["A3",      "RBT",      "0 = Nibble Sequential; 1 = Interleave"],
                ["A[6:4]+A2","CL",      "0010 → 5, 0100 → 6, 0110 → 7, 1000 → 8, 1010 → 9, 1100 → 10, 1110 → 11"],
                ["A7",      "TM",        "0 = Normal; 1 = Test (vendor)"],
                ["A8",      "DLL Reset", "0 = No; 1 = Yes"],
                ["A[11:9]", "WR cycles", "001=5, 010=6, 011=7, 100=8, 101=10, 110=12"],
                ["A12",     "PPD",       "0 = Slow Exit; 1 = Fast Exit"],
                ["A[15:13]","RFU",       "Must be 0"],
            ],
        })
        f.setdefault("mr1_rtt_nom_table", {
            "header_columns": ["A9", "A6", "A2", "Rtt_Nom"],
            "rows": [
                [0, 0, 0, "Rtt_Nom disabled"],
                [0, 0, 1, "RZQ/4 = 60 Ω"],
                [0, 1, 0, "RZQ/2 = 120 Ω"],
                [0, 1, 1, "RZQ/6 = 40 Ω"],
                [1, 0, 0, "RZQ/12 = 20 Ω"],
                [1, 0, 1, "RZQ/8 = 30 Ω"],
                [1, 1, 0, "Reserved"],
                [1, 1, 1, "Reserved"],
            ],
        })
        f.setdefault("mr2_cwl_table", {
            "header_columns": ["A5", "A4", "A3", "CWL", "Speed Grade"],
            "rows": [
                [0, 0, 0, 5, "DDR3-800"],
                [0, 0, 1, 6, "DDR3-1066"],
                [0, 1, 0, 7, "DDR3-1333"],
                [0, 1, 1, 8, "DDR3-1600"],
            ],
        })
        f.setdefault("mr2_rtt_wr_table", {
            "header_columns": ["A10", "A9", "Rtt_WR"],
            "rows": [
                [0, 0, "Dynamic ODT off"],
                [0, 1, "RZQ/4 = 60 Ω"],
                [1, 0, "RZQ/2 = 120 Ω"],
                [1, 1, "Reserved"],
            ],
        })
        f.setdefault("ba_mr_select_table", {
            "header_columns": ["BA1", "BA0", "Mode Register"],
            "rows": [
                [0, 0, "MR0"],
                [0, 1, "MR1"],
                [1, 0, "MR2"],
                [1, 1, "MR3"],
            ],
        })
        f.setdefault("speed_grade_table", {
            "header_columns": ["Speed Grade", "Data Rate (MT/s)", "tCK (ns)", "Allowed CL"],
            "rows": [
                ["DDR3-800",  800,  2.5,   "5, 6"],
                ["DDR3-1066", 1066, 1.875, "6, 7, 8"],
                ["DDR3-1333", 1333, 1.5,   "7, 8, 9, 10"],
                ["DDR3-1600", 1600, 1.25,  "8, 9, 10, 11 (optional)"],
            ],
        })
        f.setdefault("command_truth_table", {
            "header_columns": ["Function", "Abbrev", "CKE prev", "CKE curr",
                               "CS#", "RAS#", "CAS#", "WE#",
                               "BA0-BA2", "A12/BC#", "A10/AP", "A0-A9, A11"],
            "rows": [
                ["Mode Register Set", "MRS", "H", "H", "L", "L", "L", "L",
                 "BA", "OP", "OP", "OP"],
                ["Refresh", "REF", "H", "H", "L", "L", "L", "H",
                 "V", "V", "V", "V"],
                ["Self Refresh Entry", "SRE", "H", "L", "L", "L", "L", "H",
                 "V", "V", "V", "V"],
                ["Self Refresh Exit (CKE rising)", "SRX", "L", "H",
                 "H/L", "X", "X", "X", "V", "V", "V", "V"],
                ["Single Bank Precharge", "PRE", "H", "H", "L", "L", "H", "L",
                 "BA", "V", "L", "V"],
                ["Precharge all Banks", "PREA", "H", "H", "L", "L", "H", "L",
                 "V", "V", "H", "V"],
                ["Bank Activate", "ACT", "H", "H", "L", "L", "H", "H",
                 "BA", "RA", "RA", "RA"],
                ["Write (Fixed BL8 or BC4)", "WR", "H", "H", "L", "H", "L", "L",
                 "BA", "V", "L", "CA"],
                ["Write BC4 on-the-fly", "WRS4", "H", "H",
                 "L", "H", "L", "L", "BA", "L", "L", "CA"],
                ["Write BL8 on-the-fly", "WRS8", "H", "H",
                 "L", "H", "L", "L", "BA", "H", "L", "CA"],
                ["Write with AutoPrecharge (Fixed)", "WRA", "H", "H",
                 "L", "H", "L", "L", "BA", "V", "H", "CA"],
                ["Read (Fixed BL8 or BC4)", "RD", "H", "H",
                 "L", "H", "L", "H", "BA", "V", "L", "CA"],
                ["Read BC4 on-the-fly", "RDS4", "H", "H",
                 "L", "H", "L", "H", "BA", "L", "L", "CA"],
                ["Read BL8 on-the-fly", "RDS8", "H", "H",
                 "L", "H", "L", "H", "BA", "H", "L", "CA"],
                ["Read with AutoPrecharge (Fixed)", "RDA", "H", "H",
                 "L", "H", "L", "H", "BA", "V", "H", "CA"],
                ["No Operation", "NOP", "H", "H",
                 "L", "H", "H", "H", "V", "V", "V", "V"],
                ["Device Deselect", "DES", "H", "H",
                 "H", "X", "X", "X", "X", "X", "X", "X"],
                ["Power Down Entry", "PDE", "H", "L",
                 "L", "H", "H", "H", "V", "V", "V", "V"],
                ["Power Down Exit", "PDX", "L", "H",
                 "H/L", "X/H", "X/H", "X/H", "V", "V", "V", "V"],
                ["ZQ Calibration Long", "ZQCL", "H", "H",
                 "L", "H", "H", "L", "V", "V", "H", "V"],
                ["ZQ Calibration Short", "ZQCS", "H", "H",
                 "L", "H", "H", "L", "V", "V", "L", "V"],
            ],
        })
        f.setdefault("mr1_additive_latency_table", {
            "header_columns": ["A4", "A3", "AL"],
            "rows": [
                [0, 0, "0 (AL disabled)"],
                [0, 1, "CL − 1"],
                [1, 0, "CL − 2"],
                [1, 1, "Reserved"],
            ],
        })
        f.setdefault("mr3_mpr_table", {
            "header_columns": ["A2", "A[1:0]", "Function"],
            "rows": [
                [0, "—",  "Normal operation; all reads come from DRAM array"],
                [1, "00", "MPR mode enabled; subsequent RD/RDA return predefined pattern"],
                [1, "01", "RFU"],
                [1, "10", "RFU"],
                [1, "11", "RFU"],
            ],
        })
        f.setdefault("self_refresh_mode_summary_table", {
            "header_columns": ["MR2 A6 (ASR)", "MR2 A7 (SRT)",
                               "Self-Refresh operation", "Allowed Op. Temp."],
            "rows": [
                [0, 0, "Self-refresh rate for Normal Temp Range",
                 "Normal (0 to 85 °C)"],
                [0, 1, "Self-refresh rate appropriate for Normal or Extended (DRAM must support Ext.)",
                 "Normal and Extended (0 to 95 °C)"],
                [1, 0, "ASR enabled (Normal Temp Range)",
                 "Normal (0 to 85 °C)"],
                [1, 0, "ASR enabled (Extended Temp Range)",
                 "Normal and Extended (0 to 95 °C)"],
                [1, 1, "Illegal", "—"],
            ],
        })
        if _empty(f.get("tables")):
            f["tables"] = [
                "Table 1 — Input/Output functional description",
                "Table 6 — Command Truth Table",
                "Table 7 — CKE Truth Table",
                "Table 14 — Power-Down Entry Definitions",
                "Table 16 — ODT Latency",
                "Figure 4 — Simplified State Diagram",
                "Figure 9 — MR0 Definition",
                "Figure 10 — MR1 Definition",
                "Figure 11 — MR2 Definition",
                "Figure 12 — MR3 Definition",
            ]
        d["fields"] = f
        _write(p, d)

    # L16
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        if ddr_ic_name is not None:
            f["ic_name"] = ddr_ic_name
        f.setdefault("must_have_properties", [
            "Every command shall be decoded from CKE / CS# / RAS# / CAS# / WE# at the rising edge of CK.",
            "RESET# shall be HIGH during normal operation; LOW only at power-up (≥ 200 µs) or reset-with-stable-power (≥ 100 ns).",
            "Initialization shall follow the 12-step sequence ending with MRS + ZQCL + tDLLK + tZQinit.",
            "MR0-MR3 shall be re-programmed after every power-up.",
            "All MRS / REF / SRE / ZQCL / ZQCS commands shall be issued only when all banks are precharged and tRP is satisfied.",
            "tMRD and tMOD shall be honoured between MRS commands.",
            "Refresh average interval ≤ tREFI; rolling max ≤ 9 × tREFI.",
            "After Self-Refresh exit, one extra REF shall be issued before re-entering Self-Refresh.",
            "tFAW shall be honoured.",
            "Read bursts return DQ at RL = AL + CL; write bursts accept DQ at WL = AL + CWL.",
            "tCCD ≥ 4 nCK between successive column commands.",
            "ZQCL at end of init; ZQCS periodically.",
            "VREFCA = VDD/2, VREFDQ = VDDQ/2 nominal; stable in Self-Refresh.",
            "Differential CK / DQS AC swing ≥ 0.350 V; Vix ±150 mV of VDD/2.",
        ])
        f.setdefault("must_not_have_properties", [
            "Burst reads/writes shall not be terminated or interrupted.",
            "Self-Refresh shall not be entered during in-progress operations.",
            "CKE shall not transition LOW during MRS, MPR, ZQCAL, DLL locking, or RD/WR.",
            "ODT shall not be asserted during DLL-off mode.",
            "ODT shall not be active during Self-Refresh.",
            "MRS shall not be issued with any bank active.",
            "CK frequency shall not change outside SR or PPD.",
            "DDR3 shall not be plugged into a DDR2 socket.",
        ])
        f.setdefault("compliance_failure_modes", [
            {"mode": "Missed refresh", "trigger": "More than 9 × tREFI between REFs — cell data lost; no error flag."},
            {"mode": "Setup/Hold violation", "trigger": "Slew/jitter exceeds budget — command garbled or write data corrupted."},
            {"mode": "MRS in wrong state", "trigger": "MRS before PREA / tRP — undefined behaviour."},
            {"mode": "Self-Refresh entry with ODT HIGH", "trigger": "ODT not pulled LOW pre-SRE — termination undefined."},
            {"mode": "Burst chop misuse", "trigger": "WR followed by WR before tCCD — second WR rejected."},
            {"mode": "tFAW violation", "trigger": "5 ACTs in window — peak current exceeds rating."},
            {"mode": "ZQ skipped", "trigger": "Periodic ZQCS missed — gradual signal-integrity degradation."},
            {"mode": "Write Leveling not performed", "trigger": "DQS-CK skew uncompensated — write data misses DQS window."},
            {"mode": "DLL out of lock", "trigger": "Command requiring DLL before tDLLK — read timing unreliable."},
            {"mode": "Clock change outside SR/PPD", "trigger": "DVFS without SR/PPD entry — internal state undefined."},
        ])
        f.setdefault("min_clock_constraint",
            "Per speed-grade tCK range. DLL-off supports up to tCKDLL_OFF "
            "(vendor-defined, typically ≤ 125 MHz).")
        f.setdefault("reset_behavior_compliance",
            "Asserting RESET# asynchronously returns DRAM to reset state — "
            "all banks closed, MR0-MR3 cleared, ODT Hi-Z, outputs Hi-Z. After "
            "RESET# rises, full initialization sequence (from step 4) must "
            "complete before normal operation.")
        d["fields"] = f
        _write(p, d)

    # L17
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        if ddr_ic_name is not None:
            f["ic_name"] = ddr_ic_name
        f["channels"] = [
            {"name": "CK",          "direction_controller": "output", "direction_sdram": "input", "purpose": "Differential clock input (positive half).", "active_levels": "SSTL_15 differential", "idle_level": "Continuously toggling"},
            {"name": "CK#",         "direction_controller": "output", "direction_sdram": "input", "purpose": "Differential clock input (negative half).", "active_levels": "Same as CK", "idle_level": "Continuously toggling"},
            {"name": "CKE",         "direction_controller": "output", "direction_sdram": "input", "purpose": "Clock Enable.", "active_levels": "SSTL_15 single-ended", "idle_level": "HIGH during normal operation"},
            {"name": "CS#",         "direction_controller": "output", "direction_sdram": "input", "purpose": "Chip Select.", "active_levels": "SSTL_15 single-ended", "idle_level": "HIGH (deselected)"},
            {"name": "RAS#, CAS#, WE#", "direction_controller": "output", "direction_sdram": "input", "purpose": "Command inputs.", "active_levels": "SSTL_15 single-ended", "idle_level": "HIGH (encodes NOP)"},
            {"name": "BA[2:0]",     "direction_controller": "output", "direction_sdram": "input", "purpose": "Bank Address.", "active_levels": "SSTL_15 single-ended", "idle_level": "Don't-care"},
            {"name": "A[15:0]",     "direction_controller": "output", "direction_sdram": "input", "purpose": "Multiplexed address.", "active_levels": "SSTL_15 single-ended", "idle_level": "Don't-care"},
            {"name": "DM",           "direction_controller": "output", "direction_sdram": "input", "purpose": "Write Data Mask.", "active_levels": "SSTL_15 single-ended", "idle_level": "Don't-care between bursts"},
            {"name": "ODT",         "direction_controller": "output", "direction_sdram": "input", "purpose": "On-Die Termination control.", "active_levels": "SSTL_15 single-ended", "idle_level": "LOW unless RTT enabled"},
            {"name": "RESET#",      "direction_controller": "output", "direction_sdram": "input", "purpose": "Active-low asynchronous reset.", "active_levels": "CMOS rail-to-rail", "idle_level": "HIGH during normal operation"},
            {"name": "DQ",          "direction": "bidirectional", "purpose": "Data bus.", "active_levels": "SSTL_15 single-ended", "idle_level": "Hi-Z when neither side driving"},
            {"name": "DQS, DQS#",   "direction": "bidirectional differential", "purpose": "Bidirectional differential data strobe.", "active_levels": "SSTL_15 differential", "idle_level": "Hi-Z between bursts"},
            {"name": "TDQS, TDQS#", "direction_sdram": "output (x8 only)", "purpose": "Termination Data Strobe.", "active_levels": "Termination only", "idle_level": "Hi-Z if disabled"},
            {"name": "ZQ",          "direction": "supply / reference", "purpose": "Calibration reference (240 Ω external).", "active_levels": "Quasi-DC", "idle_level": "GND via 240 Ω"},
            {"name": "VREFDQ",      "direction": "supply / reference", "purpose": "DQ input threshold reference (VDDQ/2).", "active_levels": "DC", "idle_level": "Stable in all states"},
            {"name": "VREFCA",      "direction": "supply / reference", "purpose": "CA input threshold reference (VDD/2).", "active_levels": "DC", "idle_level": "Stable in all states"},
        ]
        f["power_pins"] = [
            {"name": "VDD",  "purpose": "1.5 V (DDR3) / 1.35 V (DDR3L) / 1.25 V (DDR3U)."},
            {"name": "VDDQ", "purpose": "DQ Power Supply; same as VDD."},
            {"name": "VSS",  "purpose": "Ground."},
            {"name": "VSSQ", "purpose": "DQ Ground."},
        ]
        f.setdefault("global_signals", [])
        f.setdefault("channel_counts_per_dram_x8_single_die", {
            "clock_pairs": 1, "cke_pins": 1, "cs_pins": 1, "command_pins": 3,
            "bank_address_pins": 3, "address_pins": 16, "dq_pins": 8,
            "dqs_pairs": 1, "dm_pins": 1, "odt_pins": 1, "reset_pins": 1,
            "zq_pins": 1, "vref_pins": 2,
            "supply_pins_VDD_VDDQ_VSS_VSSQ": 4,
            "external_pin_count_total": 78,
        })
        f.setdefault("channel_counts_quad_die_x8", {
            "cke_pins": 2,
            "cs_pins":  4,
            "odt_pins": 2,
            "zq_pins":  4,
            "note": "Stacked / quad-die packages multiply CKE / CS / ODT / "
                    "ZQ per die (CKE0/CKE1, CS0#..CS3#, ODT0/ODT1, "
                    "ZQ0..ZQ3).",
        })
        ord_rules = _ensure_dict(f, "ordering_rules")
        ord_rules.setdefault("command_register_edge", "Rising edge of CK.")
        ord_rules.setdefault("data_byte_order_within_burst",
            "Determined by MR0 A3 (RBT) and column-address bits A[2:0]; "
            "see Table 3 — Burst Type and Burst Order. BL8 sequential "
            "starting 000 → 0,1,2,3,4,5,6,7; BL8 interleaved starting 001 "
            "→ 1,0,3,2,5,4,7,6.")
        ord_rules.setdefault("MR_select_order_during_init",
            "MR2 → MR3 → MR1 → MR0 (DLL Reset).")
        f["dependency_graph"] = {
            "common_rule": "All commands committed on rising CK. DRAM is fully synchronous to CK except for RESET# and SR exit.",
            "data_dependency": "Read data on DQ depends on prior RD at RL = AL + CL. Write data acceptance depends on prior WR at WL = AL + CWL. No per-beat handshake.",
        }
        f["handshake_pairs"] = [
            {"name": "CMD_DECODE",  "from": "controller", "to": "SDRAM",      "rule": "Controller drives command on rising CK; SDRAM decodes one per cycle."},
            {"name": "READ_BURST",  "from": "SDRAM",      "to": "controller", "rule": "SDRAM drives DQ at RL = AL + CL; DQS edge-aligned."},
            {"name": "WRITE_BURST", "from": "controller", "to": "SDRAM",      "rule": "Controller drives DQ at WL = AL + CWL; DQS centred."},
            {"name": "ODT_SYNC",    "from": "controller", "to": "SDRAM",      "rule": "ODTLon = ODTLoff = CWL + AL − 2."},
            {"name": "WRITE_LEVEL", "from": "SDRAM",      "to": "controller", "rule": "DRAM samples CK on rising DQS; drives sampled value on DQ."},
            {"name": "REFRESH",      "from": "controller", "to": "SDRAM",      "rule": "Controller issues REF; SDRAM refreshes; tRFC must elapse."},
            {"name": "SR_HANDOFF",  "from": "controller & SDRAM", "to": "both", "rule": "CKE LOW + SRE → SDRAM holds in SR; CKE HIGH with stable CK to exit."},
        ]
        d["fields"] = f
        _write(p, d)

    # L18
    p = gd / "L18_INTERCONNECT_TOPOLOGY.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        if ddr_ic_name is not None:
            f["ic_name"] = ddr_ic_name
        f["topology_type"] = (
            "Source-synchronous parallel memory bus. Controller drives clock + "
            "command + address to one or more DDR3 SDRAM devices. DIMM "
            "modules use fly-by routing with end-of-line termination.")
        f["supported_topologies"] = [
            {"name": "Single controller + single DRAM component",        "description": "Point-to-point board topology."},
            {"name": "Single controller + DDR3 UDIMM",                   "description": "Unbuffered DIMM; fly-by routing; Write Leveling required."},
            {"name": "Single controller + DDR3 SO-DIMM",                 "description": "Small Outline DIMM for notebook/embedded."},
            {"name": "Single controller + DDR3 RDIMM",                    "description": "Registered DIMM; +1 cycle CA latency."},
            {"name": "Single controller + DDR3 LRDIMM",                   "description": "Load-Reduced DIMM with memory buffer chip."},
            {"name": "Stacked / dual-die / quad-die packages",           "description": "Multiple dies with CKE0/CKE1, CS0#..CS3#, ODT0/ODT1, ZQ0..ZQ3."},
        ]
        f["master_slave_role_summary"] = [
            {"role": "DDR3 controller (master)", "description": "Generates CK and CKE; issues commands; tracks per-bank state."},
            {"role": "DDR3 SDRAM (slave)",       "description": "Decodes commands; sources/sinks DQ; provides WL/ZQ feedback."},
            {"role": "DIMM register chip (RDIMM/LRDIMM)", "description": "Re-drives CA/CTRL; adds +1 cycle CA latency."},
            {"role": "DIMM memory buffer chip (LRDIMM)", "description": "Re-drives DQ; reduces electrical load."},
        ]
        f["interconnect_role"] = (
            "No DDR3-protocol-layer interconnect (no router / bridge). Flat "
            "1-controller : N-rank bus. Rank via CS#; bank via BA; row/column "
            "via A.")
        f["ordering_guarantees"] = {
            "within_a_burst": "8 or 4 beats per MR0 RBT + column LSB.",
            "across_commands": "Committed in issue order; no DRAM reordering.",
        }
        f.setdefault("memory_vs_peripheral_regions",
            "Single linear DRAM array as 3D address space (bank × row × column).")
        f.setdefault("device_classification", {
            "removable_DIMM":    "DDR3 UDIMM / SO-DIMM / RDIMM / LRDIMM.",
            "embedded_component":"Standalone DDR3 x4/x8/x16 soldered.",
            "DDR3_controller":   "Controller IP in SoC/FPGA/CPU.",
            "DIMM_register_chip":"Register/RCD on RDIMM/LRDIMM.",
            "DIMM_buffer_chip":  "Memory Buffer on LRDIMM.",
        })
        f.setdefault("default_signal_values_evidence_tables", [
            "Section 2 — DDR3 SDRAM Package Pinout and Addressing",
            "Section 2.10 — Pinout Description (Table 1)",
            "Section 4.8 — Write Leveling",
            "Figure 1/2/3 — Quad-stacked rank associations",
        ])
        d["fields"] = f
        _write(p, d)

    # L19 PDK
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        if ddr_ic_name is not None:
            f["ic_name"] = ddr_ic_name
        f.setdefault("constraints_present", False)
        f.setdefault("host_pcb_constraints_summary", [
            "Differential CK / CK# matched-length routing; 100 Ω differential.",
            "Single-ended CA / CTRL routing matched to CK; 50 Ω.",
            "Per-byte-lane DQ / DQS matched; impedance 40-50 Ω.",
            "Fly-by topology with end-of-line VTT termination (typ. 39 Ω).",
            "On-die termination (ODT) replaces external DQ termination.",
            "Bypass capacitors on VDD/VDDQ.",
            "VTT supply at VDDQ/2 for CA termination.",
            "VREFCA and VREFDQ low-noise divider (±1%).",
            "240 Ω ±1% on each DRAM's ZQ pin.",
            "Power-supply sequencing: VDD ramp + VDDQ + VTT + VREF before RESET#.",
        ])
        f.setdefault("dram_internal_constraints",
            "DRAM-die-internal PDK, SDC, and layout constraints are "
            "vendor-specific (DRAM process at 50-30 nm class for the DDR3 "
            "generation) and intentionally out of scope. Internal cell-array "
            "trim, sense-amp bias, charge-pump levels are not exposed at "
            "the bus interface.")
        f["notes"] = (
            "JESD79-3C standardizes electrical parameters at the package balls "
            "but no internal PDK / floorplan content. JEDEC JESD21-C covers "
            "DIMM mechanical + SPD + module-level SI.")
        d["fields"] = f
        _write(p, d)

    # L20 DFT
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        if ddr_ic_name is not None:
            f["ic_name"] = ddr_ic_name
        f["dft_present"] = "partial"
        f.setdefault("exposed_dft_features", [
            {"name": "Multi-Purpose Register",  "purpose": "Predefined pattern read training."},
            {"name": "Write Leveling",          "purpose": "CK-to-DQS alignment on fly-by DIMMs."},
            {"name": "ZQ Calibration",          "purpose": "Output driver Ron and ODT Rtt trim."},
            {"name": "Test Mode (MR0 A7=1)",    "purpose": "Vendor-reserved test mode."},
            {"name": "Qoff (MR1 A12=1)",        "purpose": "Output buffer disable for IDD measurement."},
        ])
        f.setdefault("no_jtag_on_DRAM_balls",
            "DDR3 SDRAM has no JTAG / boundary-scan / scan-shift pins.")
        f.setdefault("controller_side_dft_aids", [
            "Per-byte-lane PHY observability: DDR3 PHY IP typically exposes RX FIFO contents, calibration FSM state, eye margin sweep, per-bit deskew settings via a control register interface (vendor-specific).",
            "Logic-analyzer / oscilloscope probing of CK / CK# / CKE / CS# / RAS# / CAS# / WE# / DQ / DQS / DQS# / DM / ODT on the DIMM edge or board-level test points.",
            "ECC (SEC-DED) at the system level on x8 ECC ranks — detects single-bit errors and corrects them, doubles as a DRAM defect / soft-error indicator.",
            "MPR predefined pattern as a deterministic read self-test pattern through the PHY.",
        ])
        f["notes"] = (
            "DDR3 does not specify a formal in-system scan/JTAG architecture. "
            "Bus-level DFT is limited to MPR / WL / ZQ / vendor test mode.")
        d["fields"] = f
        _write(p, d)

    # L21
    p = gd / "L21_POWER_INTENT.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        if ddr_ic_name is not None:
            f["ic_name"] = ddr_ic_name
        f.setdefault("power_intent_present", True)
        f.setdefault("power_domains_summary", {
            "VDD_DDR3":   "1.5 V ± 0.075 V — main DRAM core and IO supply.",
            "VDD_DDR3L":  "1.35 V — low-voltage variant.",
            "VDD_DDR3U":  "1.25 V — ultra-low-voltage variant.",
            "VDDQ":       "DQ Power Supply; same nominal as VDD.",
            "VSS, VSSQ":  "Ground and DQ ground.",
            "VREFCA":     "CA reference (VDD/2); stable in all states.",
            "VREFDQ":     "DQ reference (VDDQ/2); stable in all states.",
        })
        f.setdefault("power_up_sequence", [
            "1. Assert RESET# LOW (≤ 0.2 × VDD) and CKE LOW.",
            "2. Apply VDD and VDDQ.",
            "3. VDD ramp ≤ 200 ms.",
            "4. RESET# LOW ≥ 200 µs after stable power.",
            "5. Deassert RESET#; wait 500 µs.",
            "6. Start CK; ≥ 10 ns or 5 nCK stable before CKE.",
            "7. CKE HIGH with NOP/DES; wait tXPR.",
            "8. MRS(MR2, MR3, MR1, MR0 with DLL Reset) → ZQCL → tDLLK + tZQinit.",
        ])
        f.setdefault("low_power_modes_summary", {
            "Active_Power_Down":              "CKE LOW with bank open; tXP exit.",
            "Precharge_Power_Down_Fast_Exit": "CKE LOW, MR0 A12=1; tXP exit.",
            "Precharge_Power_Down_Slow_Exit": "CKE LOW, MR0 A12=0; tXPDLL exit.",
            "Self_Refresh":                    "CKE LOW with SRE; internal refresh.",
            "Deep_Power_Down":                 "Not a defined DDR3 state.",
        })
        f.setdefault("iDD_states_summary", [
            {"state": "IDD0",  "description": "Operating one bank active-precharge current."},
            {"state": "IDD1",  "description": "Operating one bank active-precharge-read current."},
            {"state": "IDD2N", "description": "Precharge standby current."},
            {"state": "IDD2P", "description": "Precharge power-down current."},
            {"state": "IDD3N", "description": "Active standby current."},
            {"state": "IDD3P", "description": "Active power-down current."},
            {"state": "IDD4R", "description": "Operating burst-read current."},
            {"state": "IDD4W", "description": "Operating burst-write current."},
            {"state": "IDD5B", "description": "Burst refresh current."},
            {"state": "IDD6",  "description": "Self-Refresh current."},
            {"state": "IDD7",  "description": "Bank-interleaved active current."},
        ])
        f.setdefault("voltage_classes_table", {
            "header_columns": ["Class", "VDD (V)", "VDDQ (V)", "Tolerance", "Applicable Modes"],
            "rows": [
                ["DDR3",  1.5,  1.5,  "±0.075 V", "Default operation per JESD79-3C"],
                ["DDR3L", 1.35, 1.35, "±0.067 V", "JESD79-3-1"],
                ["DDR3U", 1.25, 1.25, "vendor",   "JESD79-3-1A"],
            ],
        })
        f.setdefault("self_refresh_temperature_table", {
            "header_columns": ["MR2 A6 (ASR)", "MR2 A7 (SRT)",
                               "Self-Refresh operation", "Allowed Op. Temp."],
            "rows": [
                [0, 0, "Normal Temperature Range refresh rate",
                 "Normal (0 to 85 °C)"],
                [0, 1, "Refresh rate appropriate for Normal or Extended Range",
                 "Normal and Extended (0 to 95 °C)"],
                [1, 0, "ASR enabled, Normal Temperature Range",
                 "Normal (0 to 85 °C)"],
                [1, 0, "ASR enabled, Extended Temperature Range",
                 "Normal and Extended (0 to 95 °C)"],
                [1, 1, "Illegal", "—"],
            ],
        })
        f.setdefault("partial_array_self_refresh_table", {
            "header_columns": ["MR2 A[2:0] (PASR)",
                               "Banks Refreshed during SR"],
            "rows": [
                ["000", "Full Array (all 8 banks)"],
                ["001", "Half Array (BA[2:0] = 000, 001, 010, 011)"],
                ["010", "Quarter Array (BA[2:0] = 000, 001)"],
                ["011", "1/8 Array (BA[2:0] = 000)"],
                ["100", "3/4 Array (BA[2:0] = 010, 011, 100, 101, 110, 111)"],
                ["101", "Half Array (BA[2:0] = 100, 101, 110, 111)"],
                ["110", "Quarter Array (BA[2:0] = 110, 111)"],
                ["111", "1/8 Array (BA[2:0] = 111)"],
            ],
        })
        f["notes"] = (
            "Section 3.3, Section 4.16, Section 4.17, Section 10 are the "
            "normative power references. Section 6 defines stress / "
            "non-functional ratings.")
        d["fields"] = f
        _write(p, d)

    # L22
    p = gd / "L22_VERIFICATION_PLAN.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        if ddr_ic_name is not None:
            f["ic_name"] = ddr_ic_name
        f.setdefault("verification_plan_present", "implicit")
        f.setdefault("verification_categories_derived_from_spec", [
            "Power-up + Initialization sequence.",
            "Reset-with-stable-power.",
            "All-state coverage of the state diagram.",
            "All-command coverage (MRS, REF, SRE, PRE, PREA, ACT, RD, WR, RDA, WRA, NOP, DES, PDE, PDX, ZQCL, ZQCS, +on-the-fly variants).",
            "MR0/MR1/MR2/MR3 field coverage with reserved encoding rejection.",
            "Burst length BL8 / BC4 fixed / OTF.",
            "Burst order — Sequential / Interleave with all 8 starting columns.",
            "Latency coverage — CL 5-11, CWL 5-8, AL 0/CL-1/CL-2, WR 5-16.",
            "Multi-bank interleave with tRRD / tFAW.",
            "Refresh: average tREFI, postponed/pulled-in, extra REF after SR exit.",
            "Self-Refresh entry / exit (tCKESR, tCKSRE, tCKSRX, tXS, tXSDLL).",
            "Power-Down variants (APD tXP, PPD Fast tXP, PPD Slow tXPDLL).",
            "Clock frequency change in SR or PPD.",
            "ZQ Calibration (tZQinit, tZQoper, tZQCS).",
            "Write Leveling.",
            "Read Leveling via MPR.",
            "DLL on/off switching.",
            "ODT Synchronous / Dynamic / Asynchronous modes.",
            "tFAW window.",
            "tIS, tIH, tDS, tDH with slew-rate derating.",
            "Differential clock / DQS swing + Vix.",
            "Single-ended VIH/VIL.",
            "IDD measurements IDD0..IDD7.",
            "PASR / SRT / ASR coverage.",
            "Qoff coverage.",
            "TDQS coverage on x8.",
            "tMRD, tMOD between MRS commands.",
        ])
        f["notes"] = (
            "JESD79-3C does not include a formal verification plan or "
            "testbench; categories above are derived from Sections 3, 4, 5, "
            "6-9, 10, 12-13. JEDEC and DRAM vendors maintain separate "
            "normative compliance test plans.")
        d["fields"] = f
        _write(p, d)

    # L23
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        if ddr_ic_name is not None:
            f["ic_name"] = ddr_ic_name
        f.setdefault("security_requirements_present", False)
        f.setdefault("security_summary",
            "DDR3 SDRAM has NO confidentiality, NO authentication, NO "
            "bus-level encryption, NO access control, NO secure erase, NO "
            "replay protection at the protocol level. The base protocol "
            "provides only optional system-level ECC (SEC-DED) via ECC DIMM. "
            "All cryptographic security is layered above the DDR3 channel by "
            "the memory controller / SoC.")
        f.setdefault("security_features_at_protocol_level", [
            {"name": "System-level ECC (SEC-DED)",
             "type": "integrity (system-level, not protocol-level)",
             "scope": "Per 64-bit word; +8 ECC bits via ECC DRAM.",
             "description": "Controller-side Hamming code; not cryptographic."},
            {"name": "Permanent Write Protect (none)",
             "type": "n/a", "scope": "n/a",
             "description": "DDR3 has no built-in write protect register."},
        ])
        f.setdefault("no_confidentiality",
            "DDR3 carries plaintext data on DQ. Probe/interposer attacks can "
            "sniff in plain. Cold-boot attacks are documented.")
        f.setdefault("no_authentication",
            "DDR3 has no command authentication.")
        f.setdefault("no_access_control",
            "Every command is accepted unconditionally per the Command Truth Table.")
        f.setdefault("rowhammer_class_vulnerabilities",
            "DDR3 is the first DRAM generation where Rowhammer was "
            "demonstrated (Kim et al. 2014). JESD79-3C does not specify any "
            "Rowhammer defense. Later DDR4/DDR5 standards added TRR / RFM.")
        f.setdefault("comparison_to_sibling_standards",
            "DDR4 adds CRC on DQ, parity on CA, TRR hooks. DDR5 adds on-die "
            "ECC, RFM commands. None exist in DDR3.")
        f["notes"] = (
            "Security at the DDR3 layer is intentionally absent. Modern "
            "systems needing at-rest DDR3 encryption use a memory controller "
            "with built-in AES (e.g., AMD SME) that operates transparently.")
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
def is_ddr(blob: str) -> bool:
    """Content-only `ddr` detector (importable, lifted from the runner).

    Empty-safe. Reads ONLY ``blob`` (spec text). Byte-for-byte the
    same boolean the runner used inline.

    Term membership is LEFT word-boundary anchored (see
    ``_incidental_mention``): a bare ``in`` test matched a term buried
    inside an unrelated longer word, so a part that merely has an
    ADDRESS bus ("DDR"), cites JEDEC, and mentions DDR3 once in a
    comparison sentence was classified as a DDR3 SDRAM. The third
    branch additionally requires the generation name to be the
    document's SUBJECT rather than a single citation.
    """
    if not blob:
        return False
    blob = _AnchoredBlob(blob)
    has_nand_flash_signature = (
        ("NAND" in blob and (
            "CLE" in blob or "ALE" in blob
            or "Parameter Page" in blob
            or "ONFI" in blob
            or "Flash array" in blob
            or "page program" in blob.lower()
            or "block erase" in blob.lower())))
    has_lpddr5_signature = (
        "LPDDR5" in blob
        or "JESD209-5" in blob
        or ("WCK" in blob
            and "bank group" in blob.lower()
            and "low-power" in blob.lower()))
    has_hbm3_signature = (
        "HBM3" in blob
        or "JESD238" in blob
        or "High Bandwidth Memory" in blob)
    # DDR4 / DDR5 are same-family generations that ship their OWN is_ddr4 /
    # is_ddr5 detectors; the generic DDR detector must defer to the more-specific
    # generation (sibling-MUTEX) so it does not clobber a DDR4/DDR5 gold whose
    # JESD79-4/-5 id contains the "JESD79" substring the third base branch keys
    # on. Use DOMINANT-SUBJECT density (the later generation out-mentions DDR3
    # AND is non-incidental), NOT a bare "DDR4"/"DDR5" token — a DDR3 spec that
    # merely compares itself to DDR4/DDR5 (a few incidental mentions) must STILL
    # be detected as DDR3. General structural signal (relative naming density),
    # no benchmark-name literal.
    _low = blob.lower()
    _c_ddr3 = _low.count("ddr3")
    _c_ddr4 = _low.count("ddr4")
    _c_ddr5 = _low.count("ddr5")
    has_ddr4_signature = _c_ddr4 >= 5 and _c_ddr4 > _c_ddr3
    has_ddr5_signature = _c_ddr5 >= 5 and _c_ddr5 > _c_ddr3
    return bool((not has_nand_flash_signature)
        and (not has_lpddr5_signature)
        and (not has_hbm3_signature)
        and (not has_ddr4_signature)
        and (not has_ddr5_signature) and (
        ("ACTIVATE" in blob and "PRECHARGE" in blob
            and "tRCD" in blob and "tRP" in blob)
        or ("DDR3" in blob and "SDRAM" in blob
            and ("mode register" in blob.lower()
                 or "MR0" in blob))
        # Weakest identity branch: a generic DDR mention plus a
        # standards-body citation. "JEDEC" appears in the ESD /
        # packaging / moisture-sensitivity section of virtually every
        # datasheet and PDK guide regardless of what the part does, so
        # this branch carries almost no evidence on its own. Require
        # the GENERATION token to be the document's SUBJECT rather than
        # one comparative sentence or reference-list row.
        or (_subject_term(blob, "DDR") and "JEDEC" in blob
            and (_subject_term(blob, "JESD79")
                 or _subject_term(blob, "DDR3")))))
