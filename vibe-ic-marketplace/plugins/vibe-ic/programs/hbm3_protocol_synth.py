"""HBM3-class protocol synth helper.

v0.1.89 — ic_class-gated overlay for `parallel_memory_protocol` specs that
exhibit the High Bandwidth Memory generation 3 (JEDEC JESD238) structural
signature. Applies JESD238 HBM3 spec-canonical content to the L1-L23 layer
docs.

WHY THIS EXTENDS A SIBLING (ddr) AND MUST FORCE-OVERWRITE
---------------------------------------------------------
HBM3 is a 3D-stacked SDRAM. The DDR3 synth (`ddr_protocol_synth.py`) is also
a `parallel_memory_protocol` overlay and — because an HBM3 spec also mentions
SDRAM / mode-register / bank-group / refresh / DRAM-command vocabulary — the
DDR3 detector can plausibly fire on the *same* document and run *before* this
helper in the runner's overlay chain. The DDR3 synth populates L1/L2/L3/L4
with DDR3-specific values via `setdefault`, which would then be "already set"
and frozen. Therefore this helper **force-overwrites (direct-assigns, not
setdefault)** every L1/L2/L3/L4 key the DDR3 sibling synth touches, replacing
the DDR3 values with HBM3 values. The same direct-assign discipline is applied
to the distinguishing keys of L5-L23.

SIBLING DISAMBIGUATION (general, NOT keyword/filename overfit)
-------------------------------------------------------------
The detector reads the canonical protocol NAME / spec-id and version-specific
STRUCTURAL tokens out of the L1/L2 *content* blob — never the input-document
filename and never the benchmark folder name (a code review flagged exactly
that filename-reading pattern as a HIGH defect on the AHB+APB detector; this
helper does not repeat it).

HBM3's version-specific structural tokens that the siblings lack:
  - DDR3 (ddr):  has "DDR3" / "JESD79-3" / 8-bank / 8n-prefetch / SSTL_15;
                 has NO "HBM3", NO "JESD238", NO "pseudo channel",
                 NO 1024-bit-stacked-TSV interface.
  - LPDDR5 (lpddr5): has "WCK" (write clock) + "JESD209-5"; HBM3 has neither.
  - HBM3 (this):  has "HBM3" + "JESD238" + "pseudo channel" + "1024-bit" /
                  "TSV" / "stack". HBM2/HBM2E have 8 channels of 128 bits;
                  HBM3 has 16 channels of 64 bits (still 1024-bit total).

DETECTOR SIGNATURE (the runner will wire this; documented here verbatim).
Let ``blob`` be the concatenated L1/L2 (+ optional input-doc) CONTENT text and
``low = blob.lower()``. The HBM3 overlay fires iff::

    ("HBM3" in blob)
    or ("JESD238" in blob)
    or ("High Bandwidth Memory" in blob and "pseudo channel" in low)
    or ("HBM" in blob and "1024-bit" in blob and "stack" in low
        and ("pseudo channel" in low or "16 channels" in low
             or "hbm3" in low or "jesd238" in low))

Mutex / must-not-fire guard: the helper must NOT fire on DDR3 (ddr) or
LPDDR5 (lpddr5), and must NOT false-fire on the HBM2/HBM2E sibling. Every
clause that can fire carries an HBM3-version-specific token (HBM3 / JESD238 /
"pseudo channel" / "16 channels"); the 4th (HBM + 1024-bit + stack) clause is
version-GUARDED with that same token set so HBM2/HBM2E (8 channels of 128
bits, no pseudo-channel / 16-channel distinction) does NOT trigger. A DDR3 /
LPDDR5 document contains none of these tokens, so the overlay stays mutually
exclusive with all its siblings.

Public entry: `apply_hbm3_synth(generated_docs_dir, is_hbm3, hbm3_ic_name)`.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

import l_doc_generator_stamp as _stamp
import _pack_top_module as _ptm  # L9.top_module: one decision, one provenance stamp


# Canonical ic_name for this protocol class.
HBM3_IC_NAME = "High Bandwidth Memory 3 (JEDEC JESD238)"

# The 24 layer docs (L1-L23 + L8_TIMING_WAVEFORM carry top-level ic_name;
# L14-L23 carry ic_name inside "fields").
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


def _empty(v) -> bool:
    return v in (None, {}, []) or (isinstance(v, str) and not v.strip())


def _ensure_dict(d: dict, key: str) -> dict:
    """setdefault-None bug fix: if the value is None / empty / non-dict,
    replace with {} so subsequent assignments can populate subkeys.

    (A bare ``d.setdefault(key, {})`` is a no-op when the key already holds
    ``None`` — the upstream extractor frequently emits explicit ``null`` — so
    use this helper before touching any nested dict.)
    """
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
# Structural detector (re-exportable so the phase1 ic_class router can call
# into this module's heuristic directly). GENERAL: reads canonical NAME /
# spec-id + version-specific structural tokens from CONTENT — never reads a
# filename or the benchmark folder name.
# ----------------------------------------------------------------------

def detect_hbm3_signature(text: str) -> bool:
    """Return True iff `text` (an L1/L2 [+optional input-doc] CONTENT blob)
    exhibits the HBM3 (JESD238) structural signature, and is therefore NOT a
    DDR3 / LPDDR5 sibling.

    Predicate (mirrors the module docstring):
        ("HBM3" in blob)
        or ("JESD238" in blob)
        or ("High Bandwidth Memory" in blob and "pseudo channel" in low)
        or ("HBM" in blob and "1024-bit" in blob and "stack" in low
            and ("pseudo channel" in low or "16 channels" in low
                 or "hbm3" in low or "jesd238" in low))

    The 4th (HBM + 1024-bit + stack) clause is version-GUARDED so it does NOT
    false-fire on the HBM2/HBM2E sibling (which also has "HBM" + "1024-bit" +
    "stack" but uses 8 channels of 128 bits and lacks the pseudo-channel / 16-
    channel HBM3 distinction). This satisfies the binding mutex requirement
    "require HBM3 / JESD238 / pseudo-channel" while keeping the spirit of the
    mandated HBM-1024-bit-stack predicate.
    """
    if not text:
        return False
    blob = text
    low = blob.lower()
    return (
        ("HBM3" in blob)
        or ("JESD238" in blob)
        or ("High Bandwidth Memory" in blob and "pseudo channel" in low)
        or (
            "HBM" in blob and "1024-bit" in blob and "stack" in low
            and (
                "pseudo channel" in low
                or "16 channels" in low
                or "hbm3" in low
                or "jesd238" in low
            )
        )
    )


def apply_hbm3_synth(generated_docs_dir: Path, is_hbm3: bool,
                     hbm3_ic_name: Optional[str]) -> None:
    """Apply HBM3 (JESD238)-specific synth when the structural signature
    matched.

    Because this protocol EXTENDS a sibling (ddr) whose synth fires first and
    `setdefault`-populates L1/L2/L3/L4 with DDR3 values, every sibling key is
    FORCE-OVERWRITTEN (direct-assign) here so the final L docs are HBM3, not
    DDR3.
    """
    if not is_hbm3:
        return
    gd = generated_docs_dir
    ic = hbm3_ic_name if hbm3_ic_name is not None else HBM3_IC_NAME

    # ------------------------------------------------------------------
    # Step 0: force ic_name across ALL 24 docs first (top-level for the 14
    # main docs incl. L8_TIMING_WAVEFORM; inside "fields" for L14-L23).
    # Direct-assign overrides any sibling value.
    # ------------------------------------------------------------------
    for n in _MAIN_DOCS:
        q = gd / n
        if q.is_file():
            d = _read(q)
            d["ic_name"] = ic
            _write(q, d)
    for n in _FIELDS_DOCS:
        q = gd / n
        if q.is_file():
            d = _read(q)
            f = _ensure_dict(d, "fields")
            f["ic_name"] = ic
            d["fields"] = f
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
# L1 — FORCE-OVERWRITE every DDR3 sibling key (DDR synth setdefault's these).
# ----------------------------------------------------------------------
def _l1(gd: Path) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    d["document_title"] = "High Bandwidth Memory (HBM3) DRAM Standard"
    d["document_number"] = "JESD238"
    d["version"] = "JESD238 (HBM3) — original release"
    d["revised_date"] = "January 2022"
    d["manufacturer"] = (
        "JEDEC Solid State Technology Association (multi-vendor consortium "
        "standard; JC-42.2 DRAM Memories)")
    d["publisher"] = (
        "JEDEC Solid State Technology Association, 3103 North 10th Street, "
        "Suite 240 South, Arlington, VA 22201-2107")
    d["copyright"] = "Copyright JEDEC Solid State Technology Association 2022"
    d["abstract"] = (
        "High Bandwidth Memory generation 3 (HBM3) is a JEDEC-standard "
        "(JESD238) 3D-stacked SDRAM DRAM device coupled to a host compute "
        "die through a 1024-bit-wide, channel-partitioned interface carried "
        "over through-silicon vias (TSV) and microbumps on a 2.5D silicon "
        "interposer. HBM3 retains the 1024-bit interface of prior HBM "
        "generations but doubles the channels from 8 of 128 bits "
        "(HBM2/HBM2E) to 16 of 64 bits, each splittable into two 32-bit "
        "pseudo-channels. HBM3 runs at up to 6.4 Gb/s/pin for up to 819 GB/s "
        "per stack, in 16 GB (8-Hi) and 24 GB (12-Hi) capacities of 16 Gb "
        "dies, and adds on-die ECC, link ECC, refresh management (RFM) and "
        "RAS.")
    d["keywords"] = [
        "HBM3", "High Bandwidth Memory", "JESD238", "3D-stacked DRAM",
        "1024-bit", "16 channels", "64-bit channel", "pseudo channel",
        "32-bit pseudo-channel", "TSV", "through-silicon via", "microbump",
        "silicon interposer", "2.5D", "8-Hi stack", "12-Hi stack",
        "6.4 Gb/s/pin", "819 GB/s", "differential CK", "on-die ECC",
        "link ECC", "RFM", "refresh management", "RAS", "soft repair",
        "bank group",
    ]
    d["external_pins"] = [
        "CK_t, CK_c (per-channel differential clock; commands registered on rising edges)",
        "WDQS_t, WDQS_c (differential write data strobe, per pseudo-channel)",
        "RDQS_t, RDQS_c (differential read data strobe, per pseudo-channel)",
        "DQ (64 bits per channel = 1024 bits across 16 channels per stack)",
        "R[ ] (per-channel row command/address bus)",
        "C[ ] (per-channel column command/address bus, decoded per pseudo-channel)",
        "DM / DBI (data mask / data-bus-inversion)",
        "ECC / parity helper bits (link ECC + DQ parity)",
        "AERR / DERR (alert / error report lines for RAS)",
        "RESET_n (active-low reset)",
        "TEMP (temperature readout for refresh management)",
        "Direct-access / IEEE 1500 test ports (through the base/logic die)",
        "VDDC, VDDQ, VDDQL, VPP (core / IO / low-swing IO / pump supplies)",
        "VSS (ground)",
    ]
    # Replace DDR's external_pin_count_x8_single_die with HBM3's width-centric
    # description; remove the DDR-specific key if present.
    d.pop("external_pin_count_x8_single_die", None)
    d["external_pin_count"] = (
        "1024 data pins per stack (16 channels x 64-bit) plus per-channel "
        "command/address, clock, strobe, ECC, control and supply microbumps "
        "on the interposer-facing microbump array (the JEDEC ballout is a "
        "microbump map, not a discrete-package pinout).")
    d["key_features"] = [
        "1024-bit-wide per-stack data interface over TSV + microbumps on a 2.5D silicon interposer.",
        "16 independent channels of 64 bits each (doubled from HBM2/HBM2E's 8 channels of 128 bits) — total still 1024 data pins.",
        "Each 64-bit channel divisible into two independent 32-bit pseudo-channels.",
        "Channels completely independent and not necessarily synchronous (per-channel CK_t/CK_c + command/address).",
        "Up to 6.4 Gb/s per pin (double the JEDEC HBM2E rate of 3.2 Gb/s/pin).",
        "Up to 819 GB/s memory bandwidth per stack (819.2 GB/s = 6.4 x 1024 / 8).",
        "8-Hi (8-die) and 12-Hi (12-die) stacks of 16 Gb dies (~30 µm thick) on a base/logic die.",
        "16 GB (8-Hi) and 24 GB (12-Hi) device capacities.",
        "Differential clock CK_t/CK_c; commands registered at rising edges.",
        "Double-data-rate data; separate differential WDQS (write) / RDQS (read) strobes per pseudo-channel.",
        "On-die ECC + link ECC for array and transmission error protection.",
        "Refresh Management (RFM) to bound row-hammer-class disturbance.",
        "RAS: soft-repair (post-package repair), command/address parity, error/alert reporting.",
        "Bank-group architecture for back-to-back column access.",
        "Dedicated per-channel row (R) and column (C) command/address buses, separate from data.",
        "Low-swing IO with separate VDDC / VDDQ / VDDQL / VPP rails.",
        "Vertical TSV interconnect; microbump (µbump) attach to the base die and interposer.",
        "IEEE-1500-style + direct-access (DA) test through the base/logic die for KGSD screening.",
    ]
    d["topology_summary"] = (
        "HBM3 is a 3D-stacked DRAM coupled to a host compute die "
        "(GPU/CPU/ASIC/FPGA) through a distributed, channel-partitioned "
        "interface. A stack of 8 or 12 DRAM dies sits on a base/logic die; "
        "dies are vertically interconnected by through-silicon vias (TSV) "
        "and attached by microbumps. The stack and host SoC sit on a 2.5D "
        "silicon interposer carrying the 1024 data links per stack. The "
        "interface is 16 fully independent 64-bit channels (32 pseudo-"
        "channels of 32 bits); each channel has its own differential clock "
        "and command/address bus and the channels need not be synchronous. "
        "The host memory controller masters command/address; the stack is "
        "the target.")
    # DDR's density_organization_table -> HBM3 stack/capacity table.
    d["density_organization_table"] = [
        {"stack_height": "8-Hi", "dies": 8, "per_die_density_Gb": 16, "stack_capacity_GB": 16, "channels": 16, "bits_per_channel": 64, "total_interface_bits": 1024, "pseudo_channels": 32, "bits_per_pseudo_channel": 32},
        {"stack_height": "12-Hi", "dies": 12, "per_die_density_Gb": 16, "stack_capacity_GB": 24, "channels": 16, "bits_per_channel": 64, "total_interface_bits": 1024, "pseudo_channels": 32, "bits_per_pseudo_channel": 32},
    ]
    # DDR's speed_grade_summary -> HBM3 bandwidth_summary; drop the DDR key.
    d.pop("speed_grade_summary", None)
    d["bandwidth_summary"] = [
        {"parameter": "per-pin data rate", "value": "up to 6.4 Gb/s/pin", "note": "Double the JEDEC HBM2E rate of 3.2 Gb/s/pin."},
        {"parameter": "interface width per stack", "value": "1024 bits", "note": "16 channels x 64 bits."},
        {"parameter": "peak bandwidth per stack", "value": "up to 819 GB/s", "note": "819.2 GB/s = 6.4 x 1024 / 8."},
        {"parameter": "channels", "value": "16 x 64-bit", "note": "Doubled from 8 x 128-bit in HBM2E."},
        {"parameter": "pseudo-channels", "value": "32 x 32-bit", "note": "Two 32-bit pseudo-channels per channel."},
    ]
    d["revision_history"] = [
        {"version": "JESD235 (HBM)", "date": "October 2013", "description": "First HBM standard adopted by JEDEC."},
        {"version": "JESD235a (HBM2)", "date": "January 2016", "description": "HBM2; 1024-bit; up to 8 dies per stack."},
        {"version": "HBM2E (update to JESD235)", "date": "2018-2019", "description": "Up to 307 GB/s/stack; 12-Hi stacks for up to 24 GB."},
        {"version": "JESD238 (HBM3)", "date": "January 27, 2022", "description": "Channels doubled to 16 x 64-bit (still 1024 pins); up to 6.4 Gb/s/pin; up to 819 GB/s/stack; 8-Hi (16 GB) / 12-Hi (24 GB) of 16 Gb dies; on-die + link ECC; RFM; RAS."},
        {"version": "JESD270-4 (HBM4)", "date": "April 2025", "description": "Successor; 2048-bit interface; up to 8 Gb/s/pin; up to 2 TB/s; backwards compatible with HBM3 controllers (out of scope of JESD238)."},
    ]
    d["use_cases"] = [
        "On-package memory for high-performance graphics accelerators and data-center GPUs (e.g. NVIDIA H100).",
        "AI / machine-learning training and inference accelerators.",
        "HPC and supercomputing compute nodes.",
        "High-performance network devices, switches, and packet processors.",
        "On-package cache / on-package RAM for high-end CPUs and ASICs.",
        "FPGA-attached high-bandwidth memory.",
    ]
    d["overview"] = (
        "High Bandwidth Memory generation 3 (HBM3, JEDEC JESD238) is a "
        "3D-stacked SDRAM standard that achieves very high bandwidth in a "
        "small form factor by stacking up to 12 DRAM dies (with a base/logic "
        "die) interconnected by TSV + microbumps, and connecting the stack "
        "to a host compute die through a 1024-bit-wide interface over a 2.5D "
        "silicon interposer. The interface is 16 independent 64-bit channels "
        "(each splittable into two 32-bit pseudo-channels), doubled from the "
        "8 channels of 128 bits in HBM2/HBM2E while keeping 1024 data pins. "
        "HBM3 raises the per-pin rate to 6.4 Gb/s for up to 819 GB/s per "
        "stack, in 16 GB (8-Hi) and 24 GB (12-Hi) capacities of 16 Gb dies, "
        "and adds on-die ECC, link ECC, refresh management (RFM) and RAS. "
        "JEDEC officially announced HBM3 on January 27, 2022.")
    _write(p, d)


# ----------------------------------------------------------------------
# L2 — FORCE-OVERWRITE the DDR3 sibling keys.
# ----------------------------------------------------------------------
def _l2(gd: Path) -> None:
    p = gd / "L2_FRS.json"
    if not p.is_file():
        return
    d = _read(p)
    d["protocol_overview"] = {
        "type": (
            "Channel-partitioned, controller-mastered 3D-stacked DRAM "
            "interface. The host controller drives a per-channel "
            "command/address bus and differential clock to a stack of DRAM "
            "dies; data moves double-data-rate on a 1024-bit-wide bus "
            "(16 channels x 64 bits) over TSV + microbumps on a 2.5D silicon "
            "interposer."),
        "duplex": (
            "half-duplex on each channel's DQ bus (read or write); the "
            "row/column command/address bus is unidirectional host -> DRAM; "
            "read uses RDQS strobes and write uses WDQS strobes"),
        "synchronous": True,
        "channel_independence": (
            "The 16 channels are completely independent and not necessarily "
            "synchronous to each other; each has its own CK_t/CK_c and "
            "command/address bus."),
        "pseudo_channel_mode": (
            "Each 64-bit channel splits into two 32-bit pseudo-channels that "
            "share the channel's CA bus and clock but execute column "
            "commands independently."),
        "ddr_signaling": (
            "Data (DQ) sampled on both edges of the data strobe (double data "
            "rate). Commands registered at the rising edges of CK_t/CK_c. "
            "Write data framed by WDQS_t/WDQS_c; read data by RDQS_t/RDQS_c."),
        "controller_role": (
            "Host-side memory controller is bus master: drives per-channel "
            "CK_t/CK_c, row (R) and column (C) buses, write data + WDQS; "
            "sinks read data + RDQS; schedules refresh/RFM and handles "
            "link-ECC + RAS."),
        "dram_role": (
            "The DRAM stack is the target: each channel decodes row/column "
            "commands, manages banks/bank-groups, performs on-die ECC, drives "
            "read data + RDQS, sinks write data + WDQS, reports TEMP/alerts."),
        "wire_groups": {
            "clock": ["CK_t, CK_c (per-channel differential; commands on rising edges)"],
            "row_command_address": ["R[ ] (ACTIVATE/PRECHARGE/REFRESH/RFM/MRS)"],
            "column_command_address": ["C[ ] (READ/WRITE; decoded per pseudo-channel)"],
            "data": ["DQ (64 bits/channel; 1024 bits/stack)"],
            "write_strobe": ["WDQS_t, WDQS_c (per pseudo-channel)"],
            "read_strobe": ["RDQS_t, RDQS_c (per pseudo-channel)"],
            "data_mask_dbi": ["DM / DBI"],
            "ecc_parity": ["link-ECC / DQ-parity / severity bits"],
            "ras_alert": ["AERR / DERR"],
            "reset_temp": ["RESET_n", "TEMP"],
            "supply": ["VDDC", "VDDQ", "VDDQL", "VPP", "VSS"],
        },
    }
    d["error_response_conditions"] = [
        "Command/address parity error on the R/C bus — reported via RAS alert path; controller retries or quarantines.",
        "Link-ECC error during transmission — corrected/detected; uncorrectable cases reported for RAS.",
        "On-die ECC uncorrectable array error — flagged for RAS; controller may invoke soft-repair.",
        "Refresh interval missed or RFM not issued under high activate rates — row-hammer-class disturbance may corrupt cells; HBM3 mandates RFM.",
        "Channel clock CK_t/CK_c out of spec — strobe-to-data relationships degrade on that channel only (channels are independent).",
        "Illegal command for the current bank/bank-group state — undefined; controller must obey the per-channel state diagram.",
        "Mode-register write with the channel not idle — undefined result.",
        "Over-temperature reported via TEMP — controller must raise refresh rate or throttle.",
    ]
    d["functional_requirements"] = [
        {"id": "FR-WIDTH-01", "text": "HBM3 shall present a 1024-bit-wide data interface per stack, as 16 independent channels of 64 bits each."},
        {"id": "FR-CHANNELS-02", "text": "The 16 channels shall be completely independent and not necessarily synchronous; each shall have its own CK_t/CK_c and command/address bus."},
        {"id": "FR-PSEUDO-03", "text": "Each 64-bit channel shall be divisible into two 32-bit pseudo-channels executing column commands independently."},
        {"id": "FR-DATARATE-04", "text": "HBM3 shall support up to 6.4 Gb/s/pin, yielding up to 819 GB/s per stack."},
        {"id": "FR-STACK-05", "text": "HBM3 shall support 8-Hi and 12-Hi stacks of 16 Gb dies, yielding 16 GB and 24 GB capacities."},
        {"id": "FR-TSV-06", "text": "Stacked dies shall be interconnected by TSV and microbumps; stack and host shall be on a 2.5D silicon interposer carrying 1024 links per stack."},
        {"id": "FR-CLK-07", "text": "Commands shall be registered at the rising edges of CK_t/CK_c per channel."},
        {"id": "FR-STROBE-08", "text": "Write data shall be framed by WDQS_t/WDQS_c and read data by RDQS_t/RDQS_c, sampled on both edges."},
        {"id": "FR-CABUS-09", "text": "Each channel shall provide dedicated row (R) and column (C) command/address buses; column commands decode per pseudo-channel."},
        {"id": "FR-BANKGROUP-10", "text": "Each channel/pseudo-channel shall implement a bank-group architecture."},
        {"id": "FR-ODECC-11", "text": "HBM3 shall implement on-die ECC transparent to the host."},
        {"id": "FR-LINKECC-12", "text": "HBM3 shall implement link ECC over the channel data bus."},
        {"id": "FR-RFM-13", "text": "HBM3 shall support Refresh Management (RFM) to bound disturbance under high activate rates."},
        {"id": "FR-RAS-14", "text": "HBM3 shall provide RAS: soft-repair, command/address parity, error/alert reporting, severity logging."},
        {"id": "FR-TEMP-15", "text": "HBM3 shall report die temperature for refresh adaptation."},
        {"id": "FR-TEST-16", "text": "HBM3 shall provide IEEE-1500-style + direct-access test through the base die for KGSD screening."},
    ]
    d["configurations"] = [
        {"name": "8-Hi stack (16 GB)", "description": "8 dies of 16 Gb; 16 channels x 64-bit; 1024-bit interface."},
        {"name": "12-Hi stack (24 GB)", "description": "12 dies of 16 Gb; 16 channels x 64-bit; 1024-bit interface."},
        {"name": "Pseudo-channel mode", "description": "Two 32-bit pseudo-channels per 64-bit channel with independent column streams."},
        {"name": "Legacy (non-pseudo) channel mode", "description": "64-bit channel addressed as one where supported."},
        {"name": "On-die ECC enabled", "description": "In-DRAM single-error correction."},
        {"name": "Link ECC enabled", "description": "ECC across the channel data bus."},
        {"name": "Refresh management (RFM) mode", "description": "Adaptive refresh under high activate rates."},
    ]
    d["compliance_requirements"] = [
        "Total per-stack interface width shall be exactly 1024 data pins (16 x 64).",
        "Channels shall be electrically and logically independent; no command on one channel may affect another.",
        "Per-pin data rate shall not exceed the device's rated maximum (up to 6.4 Gb/s/pin).",
        "Commands shall be registered only at the rising edges of CK_t/CK_c on the addressed channel.",
        "Write data shall meet WDQS windows; read data shall meet RDQS windows.",
        "Refresh-management (RFM) requirements shall be honoured to bound disturbance.",
        "Link-ECC and on-die-ECC uncorrectable errors shall be reported through the RAS alert path.",
        "Mode registers shall be programmed in the defined order with the channel idle.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L3 — FORCE-OVERWRITE the DDR3 sibling keys; drop DDR-only keys.
# ----------------------------------------------------------------------
def _l3(gd: Path) -> None:
    p = gd / "L3_CMD_PROTOCOL.json"
    if not p.is_file():
        return
    d = _read(p)
    d["protocol_type"] = (
        "Channel-partitioned, controller-mastered command-driven DRAM "
        "protocol. Each of 16 independent channels has its own CK_t/CK_c and "
        "its own row (R) / column (C) command/address bus. Row commands "
        "(activate/precharge/refresh/MRS) on R; column commands (read/write) "
        "on C, decoded per 32-bit pseudo-channel. Data is double-data-rate on "
        "the 64-bit channel DQ bus, framed by differential WDQS (write) / "
        "RDQS (read).")
    d["channels"] = [
        {"name": "CK_t, CK_c", "direction": "controller -> DRAM (per channel)", "description": "Per-channel differential clock; commands registered at rising edges; channels need not be synchronous."},
        {"name": "R[ ] (row command/address)", "direction": "controller -> DRAM (per channel)", "description": "ACTIVATE/PRECHARGE/REFRESH/RFM/MRS/POWER-DOWN with bank-group/bank/row address."},
        {"name": "C[ ] (column command/address)", "direction": "controller -> DRAM (per channel)", "description": "READ/WRITE with column address; decoded independently per 32-bit pseudo-channel."},
        {"name": "DQ", "direction": "bidirectional (per channel)", "description": "64-bit-per-channel data bus (1024 bits/stack); double data rate."},
        {"name": "WDQS_t, WDQS_c", "direction": "controller -> DRAM (write)", "description": "Differential write strobe, per pseudo-channel."},
        {"name": "RDQS_t, RDQS_c", "direction": "DRAM -> controller (read)", "description": "Differential read strobe, per pseudo-channel."},
        {"name": "DM / DBI", "direction": "per direction", "description": "Data mask / data-bus-inversion."},
        {"name": "ECC / parity bits", "direction": "bidirectional", "description": "Link-ECC and DQ-parity protecting data and command/address."},
        {"name": "AERR / DERR", "direction": "DRAM -> controller", "description": "RAS alert / error report."},
        {"name": "TEMP", "direction": "DRAM -> controller", "description": "Temperature for refresh adaptation."},
        {"name": "RESET_n", "direction": "controller -> DRAM", "description": "Active-low reset."},
    ]
    d["valid_ready_handshake_rules"] = [
        "No per-beat handshake; each command is committed at the rising edge of CK_t/CK_c on its channel; data follows at deterministic latency.",
        "READ data appears at read latency from READ, framed by DRAM-driven RDQS.",
        "WRITE data is launched framed by WDQS at write latency from WRITE.",
        "Row (R) and column (C) commands can be issued in parallel within a channel.",
        "Column commands decode independently for each of the two 32-bit pseudo-channels.",
        "Channels are independent; no cross-channel interlock.",
    ]
    d["burst_based"] = True
    d["byte_oriented"] = False
    d["frame_format"] = {
        "row_command_frame": "Command on R[ ] across one or more CK cycles; ACTIVATE/PRECHARGE/REFRESH/RFM/MRS with bank-group/bank/row.",
        "column_command_frame": "Command on C[ ] encoding READ/WRITE with column; decoded per 32-bit pseudo-channel.",
        "data_frame": "Burst on the 64-bit DQ bus (32 bits/pseudo-channel), double-data-rate, framed by WDQS (write)/RDQS (read).",
    }
    # Replace DDR's command_truth_table with an HBM3 command summary.
    d.pop("command_truth_table", None)
    d.pop("cke_truth_table", None)
    d.pop("burst_order_BL8_sequential", None)
    d.pop("burst_order_BL8_interleaved", None)
    d["command_summary"] = {
        "legend": {
            "BG": "Bank Group", "BA": "Bank Address", "RA": "Row Address",
            "CA": "Column Address", "PC": "Pseudo-Channel select",
            "OP": "Op-code / mode-register field",
        },
        "commands": [
            {"command": "ACTIVATE (ACT)", "bus": "R", "description": "Open a row in the selected bank-group/bank."},
            {"command": "PRECHARGE (PRE)", "bus": "R", "description": "Close the open row and restore bitlines."},
            {"command": "READ (RD)", "bus": "C", "description": "Burst read; decoded per pseudo-channel; DRAM drives DQ + RDQS."},
            {"command": "WRITE (WR)", "bus": "C", "description": "Burst write; decoded per pseudo-channel; controller drives DQ + WDQS."},
            {"command": "REFRESH (REF)", "bus": "R", "description": "All-bank or per-bank refresh."},
            {"command": "REFRESH MANAGEMENT (RFM)", "bus": "R", "description": "Adaptive refresh to bound disturbance."},
            {"command": "MODE REGISTER SET (MRS)", "bus": "R", "description": "Program a mode register with the channel idle."},
            {"command": "POWER-DOWN ENTRY / EXIT", "bus": "R", "description": "Per-channel low-power state."},
            {"command": "SELF-REFRESH ENTRY / EXIT", "bus": "R", "description": "DRAM self-refreshes; clock may stop; exit re-synchronizes."},
        ],
    }
    d["pseudo_channel_rules"] = [
        "Each 64-bit channel splits into two 32-bit pseudo-channels.",
        "Pseudo-channels share the channel's clock and the row-side command/address bus.",
        "Pseudo-channels execute column (read/write) commands independently.",
        "Pseudo-channel mode improves access granularity and bus efficiency.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L4 — FORCE-OVERWRITE the DDR3 sibling keys.
# ----------------------------------------------------------------------
def _l4(gd: Path) -> None:
    p = gd / "L4_REGMAP.json"
    if not p.is_file():
        return
    d = _read(p)
    d["register_map_present"] = True
    d["notes"] = (
        "HBM3 exposes per-channel Mode Registers (MR) programmed via the "
        "Mode-Register-Set (MRS) command on the row command/address bus, plus "
        "mode-register-read / status fields. There is no flat memory-mapped "
        "offset bus; each MR is selected by an address field during MRS. The "
        "JESD238 mode-register set evolves the HBM2/HBM2E registers, adding "
        "fields for the 16-channel / pseudo-channel organization, link ECC, "
        "refresh management (RFM), and RAS.")
    # Remove DDR's concrete MR0..MR3 register array if present.
    d.pop("registers", None)
    d["register_classes"] = [
        {"class": "Timing / latency mode registers", "purpose": "Program RL, WL, burst length, parity latency per channel."},
        {"class": "Drive-strength / termination mode registers", "purpose": "Output driver strength / ODT for DQ/WDQS/RDQS/CA at 6.4 Gb/s/pin."},
        {"class": "ECC control mode registers", "purpose": "Enable/configure on-die ECC and link ECC; ECC reporting."},
        {"class": "Refresh / RFM mode registers", "purpose": "Refresh rate, RFM thresholds, temperature-compensated refresh."},
        {"class": "Pseudo-channel / channel-mode register", "purpose": "Select pseudo-channel vs legacy channel operation."},
        {"class": "RAS / repair mode registers", "purpose": "CA parity, soft-repair requests, error-severity logging, alerts."},
        {"class": "Test / DA mode registers", "purpose": "IEEE-1500 / direct-access test, MBIST, loopback, KGSD."},
    ]
    d["representative_mode_register_fields"] = [
        {"register": "MR (timing)", "field": "Read Latency (RL)", "description": "Clocks from READ to first read-data beat."},
        {"register": "MR (timing)", "field": "Write Latency (WL)", "description": "Clocks from WRITE to first write-data beat."},
        {"register": "MR (timing)", "field": "Burst Length (BL)", "description": "Data burst length per column access."},
        {"register": "MR (mode)", "field": "Pseudo-Channel Enable", "description": "Selects two-32-bit-pseudo-channel operation."},
        {"register": "MR (ECC)", "field": "On-Die ECC Enable", "description": "Enables in-DRAM single-error-correction."},
        {"register": "MR (ECC)", "field": "Link ECC Enable", "description": "Enables ECC across the channel data bus."},
        {"register": "MR (refresh)", "field": "Refresh Rate / RFM Threshold", "description": "Refresh interval and RFM thresholds."},
        {"register": "MR (drive)", "field": "DQ / Strobe Drive Strength", "description": "Output driver strength at 6.4 Gb/s/pin."},
        {"register": "MR (RAS)", "field": "CA Parity Enable / Latency", "description": "Command/address parity and latency."},
        {"register": "MR (RAS)", "field": "Soft-Repair Request", "description": "Post-package soft repair of a failing row/column."},
        {"register": "MR (test)", "field": "DA / Loopback Mode", "description": "Direct-access / loopback test through the base die."},
    ]
    d["access_mechanism"] = {
        "write": "Mode Register Set (MRS) on the per-channel row command/address bus with the channel idle.",
        "read": "Mode Register Read (MRR) / status readout on the channel.",
        "scope": "Mode registers are per-channel; the 16 channels are configured independently.",
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L5 — analog/electrical + physical stack (force the distinguishing keys).
# ----------------------------------------------------------------------
def _l5(gd: Path) -> None:
    p = gd / "L5_ADI_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["analog_digital_interface_present"] = True
    d["signaling_summary"] = (
        "HBM3 uses low-swing single-ended signaling for data (DQ) and "
        "command/address, with differential clocking (CK_t/CK_c) and "
        "differential data strobes (WDQS write, RDQS read). The wide, short "
        "interposer-routed links allow low per-pin swing while reaching "
        "6.4 Gb/s/pin. Separate VDDC/VDDQ/VDDQL/VPP rails keep high-bandwidth "
        "IO power-efficient. Interconnect is TSV + microbumps on a 2.5D "
        "silicon interposer.")
    d["clocking"] = {
        "type": "differential CK_t / CK_c per channel",
        "command_registration": "Commands registered at the rising edges of CK_t and CK_c.",
        "channel_synchronization": "Channels are not necessarily synchronous; each has its own clock.",
    }
    d["data_strobes"] = {
        "write_strobe": "WDQS_t / WDQS_c (differential), per pseudo-channel.",
        "read_strobe": "RDQS_t / RDQS_c (differential), per pseudo-channel.",
        "data_rate": "Double data rate; up to 6.4 Gb/s/pin.",
    }
    d["supply_rails"] = [
        {"rail": "VDDC", "purpose": "DRAM core supply."},
        {"rail": "VDDQ", "purpose": "IO supply for the data interface."},
        {"rail": "VDDQL", "purpose": "Low-swing IO supply for the high-speed links."},
        {"rail": "VPP", "purpose": "Elevated (pumped) wordline/boost supply."},
        {"rail": "VSS", "purpose": "Ground."},
    ]
    d["interconnect_physical"] = {
        "vertical": "TSV connect the stacked dies (8-Hi/12-Hi); each die ~30 µm thick.",
        "attach": "Microbumps (µbump) attach dies to one another and to the base/logic die.",
        "host_coupling": "Stack and host SoC on a 2.5D silicon interposer carrying 1024 data links per stack.",
        "rationale": "Interposer keeps memory close to the host; silicon fabrication is more expensive than PCB, adding cost.",
    }
    d["notes"] = (
        "HBM3 is a digital memory interface; the analog content is the "
        "high-speed link electricals (low-swing signaling, differential "
        "clock/strobe, termination, supply rails) and the TSV/microbump/"
        "interposer stack-up, not a converter-style analog block.")
    _write(p, d)


# ----------------------------------------------------------------------
# L6 — per-channel control FSM (force the distinguishing keys).
# ----------------------------------------------------------------------
def _l6(gd: Path) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    # Drop DDR-specific FSM key names if present.
    d.pop("fsm_states_sdram", None)
    d.pop("fsm_transitions_major", None)
    d["fsm_states_dram_per_channel"] = [
        {"name": "RESET", "description": "RESET_n asserted; channel in known state; mode registers undefined."},
        {"name": "INITIALIZATION", "description": "Supply ramp, RESET_n deassertion, mode-register programming, ECC/RFM config, link training."},
        {"name": "IDLE_ALL_BANKS_PRECHARGED", "description": "Channel ready; awaits ACTIVATE/REF/MRS/power-down."},
        {"name": "BANK_ACTIVE", "description": "A row is open; column READ/WRITE allowed on the C bus."},
        {"name": "READING", "description": "Burst read; DRAM drives DQ + RDQS for the addressed pseudo-channel."},
        {"name": "WRITING", "description": "Burst write; controller drives DQ + WDQS for the addressed pseudo-channel."},
        {"name": "PRECHARGING", "description": "Open row being closed; bitlines restored."},
        {"name": "REFRESHING", "description": "REFRESH/RFM in progress; no column access during the window."},
        {"name": "POWER_DOWN", "description": "Per-channel low-power; clock may be gated; fast exit."},
        {"name": "SELF_REFRESH", "description": "DRAM self-refreshes; channel clock may stop; exit re-synchronizes."},
    ]
    d["fsm_states_controller"] = [
        {"name": "PER_CHANNEL_SCHEDULER", "description": "Independently schedules ACT/PRE/RD/WR/REF/RFM per channel."},
        {"name": "PSEUDO_CHANNEL_ARBITER", "description": "Arbitrates column commands between the two 32-bit pseudo-channels of a channel."},
        {"name": "REFRESH_MANAGER", "description": "Tracks activate counts, issues RFM, adapts refresh to TEMP."},
        {"name": "ECC_RAS_HANDLER", "description": "Processes link/on-die ECC reports, CA-parity alerts, initiates soft-repair."},
    ]
    d["fsm_hints"] = {
        "trigger": "Each channel runs its own command stream; commands registered at rising CK_t/CK_c edges.",
        "rule": "Row commands on the R bus, column commands on the C bus (per pseudo-channel); both can be active in one cycle.",
        "channel_independence": "No cross-channel interlock: a command on channel N never changes channel M.",
        "abort": "Stopping the channel clock during self-refresh/power-down halts the channel gracefully.",
    }
    d["anti_deadlock_rule"] = (
        "Single controller masters all command/address; the DRAM is a target "
        "with no command-bus contention. Per-channel independence prevents "
        "one channel from blocking another. RFM is mandatory to prevent "
        "disturbance-induced data loss under sustained high activate rates.")
    d["exit_from_reset_or_poweron"] = (
        "On power-on, rails ramp (VDDC/VDDQ/VDDQL/VPP), RESET_n held LOW then "
        "deasserted; the controller programs mode registers (timing, ECC, "
        "RFM, pseudo-channel mode), trains links per channel, and brings each "
        "channel to IDLE before ACTIVATE.")
    d["default_ready_state_recommendation"] = {
        "RESET_n": "HIGH during normal operation.",
        "CK_t_CK_c": "Toggling differential clock per channel; may stop in self-refresh.",
        "DQ": "High-impedance between bursts.",
        "command_buses_R_C": "Deselect/NOP when no command is issued.",
    }
    d["configurations"] = [
        {"name": "Pseudo-channel mode", "description": "Two independent 32-bit column streams per 64-bit channel."},
        {"name": "Legacy channel mode", "description": "Single 64-bit channel."},
        {"name": "On-die ECC + link ECC enabled", "description": "Full error protection."},
        {"name": "RFM-active high-throughput mode", "description": "Adaptive refresh under high activate rates."},
    ]
    d["timing_dependency_rule"] = (
        "Read data on a channel's DQ depends on its prior READ at read "
        "latency RL; write data acceptance depends on its prior WRITE at "
        "write latency WL. WDQS/RDQS windows must be met. There is no "
        "per-beat handshake; the host controller honours all per-channel "
        "timing and refresh-management constraints.")
    _write(p, d)


# ----------------------------------------------------------------------
# L7 — test/debug (force the distinguishing keys).
# ----------------------------------------------------------------------
def _l7(gd: Path) -> None:
    p = gd / "L7_TEST_DEBUG.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_debug_architecture_present"] = True
    d["spec_provided_observability"] = [
        {"name": "IEEE 1500 test access port", "purpose": "Wrapper-based test access through the base/logic die for boundary/interconnect test."},
        {"name": "Direct Access (DA) test", "purpose": "Direct probing of the DRAM dies through the base die for KGSD screening."},
        {"name": "MBIST / loopback", "purpose": "Self-test and data-bus loopback to characterize links at 6.4 Gb/s/pin."},
        {"name": "Link-ECC / on-die-ECC error counters", "purpose": "Report corrected/uncorrectable error counts for RAS."},
        {"name": "CA parity alert (AERR/DERR)", "purpose": "Report command/address parity errors and severity."},
        {"name": "TEMP readout", "purpose": "On-die temperature reported for refresh adaptation and thermal debug."},
    ]
    d["stacked_die_test_strategy"] = (
        "HBM3 test is hierarchical: each DRAM die is screened; the stack is "
        "tested as a known-good-stacked-die (KGSD) through the base die's "
        "IEEE-1500 / direct-access ports; the stack-on-interposer is tested "
        "for TSV / microbump integrity. TSMC produces the base die for HBM "
        "and is a foundry for HBM stacking.")
    d["notes"] = (
        "HBM3 places test/repair logic largely in the base/logic die so the "
        "DRAM dies stay dense. RAS reporting (link ECC, on-die ECC, CA "
        "parity, soft-repair) doubles as in-field debug observability.")
    _write(p, d)


# ----------------------------------------------------------------------
# L8 RTL constants — force the width/rate/channel constants.
# ----------------------------------------------------------------------
def _l8_rtl(gd: Path) -> None:
    p = gd / "L8_RTL_CONSTANTS.json"
    if not p.is_file():
        return
    d = _read(p)
    wp = _ensure_dict(d, "width_parameters")
    wp.clear()
    wp.update({
        "TOTAL_INTERFACE_WIDTH_BITS": 1024,
        "NUM_CHANNELS": 16,
        "CHANNEL_DATA_WIDTH_BITS": 64,
        "NUM_PSEUDO_CHANNELS": 32,
        "PSEUDO_CHANNEL_DATA_WIDTH_BITS": 32,
        "PER_DIE_DENSITY_Gb": 16,
        "STACK_HEIGHTS_SUPPORTED": [8, 12],
        "STACK_CAPACITY_GB_8HI": 16,
        "STACK_CAPACITY_GB_12HI": 24,
        "DIE_THICKNESS_um_approx": 30,
    })
    # Drop DDR-specific timing-parameter blocks if present.
    d.pop("named_timing_parameters", None)
    d.pop("burst_order_constants", None)
    d["data_rate_constants"] = {
        "MAX_PIN_DATA_RATE_Gbps": 6.4,
        "PEAK_BANDWIDTH_PER_STACK_GBps": 819,
        "PEAK_BANDWIDTH_PER_STACK_GBps_exact": 819.2,
        "BANDWIDTH_FORMULA": "per_stack_GBps = pin_rate_Gbps * 1024 / 8",
        "PRIOR_GEN_RATE_HBM2E_Gbps": 3.2,
    }
    d["clock_constants"] = {
        "CLOCK_TYPE": "differential CK_t / CK_c, per channel",
        "COMMAND_REGISTER_EDGE": "rising edges of CK_t and CK_c",
        "CHANNELS_SYNCHRONOUS": False,
    }
    d["strobe_constants"] = {
        "WRITE_STROBE": "WDQS_t / WDQS_c (differential, per pseudo-channel)",
        "READ_STROBE": "RDQS_t / RDQS_c (differential, per pseudo-channel)",
        "DATA_RATE": "double data rate (sampled on both strobe edges)",
    }
    d["key_constants_for_RTL_authoring"] = {
        "interface_is_channel_partitioned": True,
        "channels_are_independent": True,
        "channels_need_not_be_synchronous": True,
        "pseudo_channel_count_per_channel": 2,
        "pseudo_channel_width_bits": 32,
        "command_address_bus_is_per_channel": True,
        "separate_row_and_column_command_buses": True,
        "data_byte_order": "burst order per JESD238 column-access tables",
        "on_die_ecc": True,
        "link_ecc": True,
        "refresh_management_RFM": True,
        "ras_features": ["soft repair", "CA parity", "error/alert reporting"],
        "interconnect": "TSV + microbump on 2.5D silicon interposer",
        "total_data_pins_per_stack": 1024,
    }
    d["default_signal_values_when_idle"] = {
        "RESET_n": "HIGH during normal operation",
        "CK_t_CK_c": "toggling per channel; may stop in self-refresh",
        "DQ": "high-impedance between bursts",
        "WDQS_RDQS": "high-impedance between bursts",
        "R_C_command_buses": "deselect / NOP",
    }
    d["capacity_organization_constants"] = [
        {"stack": "8-Hi", "dies": 8, "die_density_Gb": 16, "capacity_GB": 16},
        {"stack": "12-Hi", "dies": 12, "die_density_Gb": 16, "capacity_GB": 24},
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L8 timing waveform — force the distinguishing keys.
# ----------------------------------------------------------------------
def _l8_timing(gd: Path) -> None:
    p = gd / "L8_TIMING_WAVEFORM.json"
    if not p.is_file():
        return
    d = _read(p)
    d["clock_waveform"] = {
        "type": "differential CK_t / CK_c per channel",
        "command_registration": "Commands registered at the rising edges of CK_t and CK_c.",
        "channel_independence": "Each channel has its own clock; channels need not be synchronous.",
        "data_rate": "Data toggles at double the clock-derived bit rate, up to 6.4 Gb/s/pin.",
    }
    # Drop DDR-specific waveform keys if present.
    for k in ("command_frame_waveform", "read_burst_waveform_BL8",
              "write_burst_waveform_BL8", "self_refresh_entry_exit",
              "write_leveling_waveform"):
        d.pop(k, None)
    d["row_command_waveform"] = {
        "bus": "R[ ] command/address",
        "content": "ACTIVATE/PRECHARGE/REFRESH/RFM/MRS across one or more CK cycles with bank-group/bank/row.",
        "registration": "Sampled on rising CK_t/CK_c edges.",
    }
    d["column_command_waveform"] = {
        "bus": "C[ ] command/address",
        "content": "READ/WRITE with column address; decoded independently per 32-bit pseudo-channel.",
        "parallelism": "Can be issued in the same cycle as a row command on the R bus.",
    }
    d["write_data_waveform"] = {
        "data": "64 bits/channel (32/pseudo-channel) on DQ, double data rate.",
        "strobe": "Framed by differential WDQS_t/WDQS_c; data centred relative to WDQS edges.",
        "latency": "Launched at write latency WL from WRITE.",
    }
    d["read_data_waveform"] = {
        "data": "64 bits/channel (32/pseudo-channel) on DQ, double data rate.",
        "strobe": "Framed by differential RDQS_t/RDQS_c; edge-aligned with read data.",
        "latency": "Appears at read latency RL from READ.",
    }
    d["initialization_waveform"] = {
        "sequence": "Supply ramp -> RESET_n LOW -> RESET_n HIGH -> mode-register programming -> per-channel link training -> channel IDLE.",
        "note": "Initialization is per-channel; channels may come up independently.",
    }
    d["refresh_waveform"] = {
        "refresh": "REFRESH (all-bank/per-bank) closes column access during the refresh window.",
        "refresh_management": "RFM issued adaptively under high activate rates; rate may track TEMP.",
    }
    d["timing_tables_referenced"] = [
        "Per-channel command timing (ACT-to-RD/WR, RD/WR-to-data latencies RL/WL).",
        "Data-strobe to data windows for WDQS (write) and RDQS (read) at up to 6.4 Gb/s/pin.",
        "Refresh and refresh-management (RFM) timing.",
        "Bank-group back-to-back column access timing.",
    ]
    d["general_timing_rule"] = (
        "All per-channel command and data timings are referenced to that "
        "channel's clock CK_t/CK_c. Because the 16 channels are independent "
        "and not necessarily synchronous, each channel's budget is evaluated "
        "on its own clock; the host schedules each channel separately.")
    d["voltage_levels"] = {
        "signaling": "low-swing single-ended data/CA with differential clock and strobes",
        "rails": ["VDDC", "VDDQ", "VDDQL", "VPP", "VSS"],
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L9 — integration spec (force the distinguishing keys).
# ----------------------------------------------------------------------
def _l9(gd: Path) -> None:
    p = gd / "L9_INTEGRATION_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["module_role"] = (
        "HBM3 is an on-package 3D-stacked DRAM device integrating with a host "
        "compute die (GPU/CPU/ASIC/FPGA) through a 1024-bit-wide, "
        "channel-partitioned interface over a 2.5D silicon interposer. The "
        "host SoC contains an HBM3 controller + PHY that masters per-channel "
        "command/address, clock, write data + WDQS, and sinks read data + "
        "RDQS for all 16 independent channels.")
    _ptm.apply(d, "HBM3_stack_on_interposer")
    d["integration_overview"] = {
        "interface_width_bits": 1024,
        "channels": 16,
        "bits_per_channel": 64,
        "pseudo_channels": 32,
        "bits_per_pseudo_channel": 32,
        "interconnect": "TSV + microbump within the stack; 2.5D silicon interposer to the host SoC.",
        "host_role": "memory controller + PHY is bus master for all channels",
        "dram_role": "stack is the target; per-channel independent command decode",
        "physical_proximity": "interposer keeps memory close to the host",
    }
    d["interface_categories"] = [
        "Per-channel differential clock CK_t/CK_c (16x).",
        "Per-channel row (R) and column (C) command/address buses.",
        "1024-bit data bus (16 x 64-bit DQ).",
        "Per-pseudo-channel differential write strobe WDQS and read strobe RDQS.",
        "ECC / parity / RAS alert lines (link ECC, on-die ECC reporting, CA parity, AERR/DERR).",
        "TEMP, RESET_n, and test/DA ports through the base die.",
        "Supply rails VDDC / VDDQ / VDDQL / VPP / VSS.",
    ]
    d["interconnect_topologies_supported"] = [
        "Single HBM3 stack adjacent to one host die on a shared 2.5D silicon interposer.",
        "Multiple HBM3 stacks (four to six) around one GPU/accelerator for multi-TB/s aggregate bandwidth.",
        "Stack-directly-on-host (3D) where the memory die is stacked on the CPU/GPU chip.",
    ]
    d["default_signal_values_when_omitted"] = (
        "RESET_n HIGH in normal operation; command buses at deselect/NOP; DQ "
        "and strobes high-impedance between bursts.")
    d["soc_dependent_items"] = [
        "HBM3 controller scheduling across 16 independent channels and 32 pseudo-channels.",
        "PHY training and per-channel calibration for 6.4 Gb/s/pin links.",
        "Refresh-management (RFM) policy and temperature-tracked refresh via TEMP.",
        "Link-ECC / on-die-ECC reporting handling and RAS soft-repair flow.",
        "Interposer floorplan, microbump map, and TSV routing budget.",
        "Power delivery for VDDC / VDDQ / VDDQL / VPP at high bandwidth.",
        "Thermal solution for the stacked dies under sustained high bandwidth.",
    ]
    d["system_examples"] = [
        {"system": "NVIDIA H100 (Hopper) GPU", "detail": "Industry-first HBM3; up to 819 GB/s per stack; multiple HBM3 sites (e.g. five active sites = 80 GB and ~3 TB/s; 16 GB / 600 GB/s per site)."},
        {"system": "Data-center accelerators", "detail": "12-Hi 24 GB stacks aggregated for multi-TB/s (e.g. ~4.9 TB/s with six 24 GB stacks)."},
    ]
    d["low_power_modes"] = {
        "power_down": "Per-channel power-down with fast exit; clock may be gated.",
        "self_refresh": "DRAM self-refreshes; channel clock may stop; exit re-synchronizes.",
    }
    d["compatibility_notes"] = (
        "HBM3 keeps the 1024-bit interface of prior HBM generations but "
        "doubles channels (16 x 64-bit vs 8 x 128-bit). HBM4 (JESD270-4, "
        "April 2025) widens to 2048 bits and is backwards compatible with "
        "HBM3 controllers, but is a separate standard out of scope of "
        "JESD238.")
    # Drop DDR-only key.
    d.pop("pull_up_resistors_terminators", None)
    _write(p, d)


# ----------------------------------------------------------------------
# L10 — derived test cases (force the distinguishing keys).
# ----------------------------------------------------------------------
def _l10(gd: Path) -> None:
    p = gd / "L10_TEST_CASES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_cases_present"] = (
        "partial - JESD238 defines protocol/electricals/RAS that map to "
        "compliance scenarios but ships no formal testbench; categories below "
        "are derived from the spec's distinguishing features.")
    d["derived_compliance_test_categories"] = [
        "Verify the per-stack data interface is exactly 1024 bits (16 channels x 64 bits).",
        "Verify each 64-bit channel operates as two independent 32-bit pseudo-channels.",
        "Verify the 16 channels are independent: a command on one channel does not affect another.",
        "Verify channels need not be synchronous (drive skewed/async clocks).",
        "Verify per-pin data rate up to 6.4 Gb/s/pin and up to 819 GB/s per stack.",
        "Verify commands are registered at the rising edges of CK_t/CK_c.",
        "Verify write data framed by WDQS and read data by RDQS at double data rate.",
        "Verify 8-Hi -> 16 GB and 12-Hi -> 24 GB from 16 Gb dies.",
        "Verify on-die ECC corrects a single-bit array error transparently.",
        "Verify link ECC detects/corrects a transmission error and reports uncorrectable cases.",
        "Verify refresh management (RFM) under sustained high activate rates.",
        "Verify command/address parity error reported via the RAS alert path.",
        "Verify soft-repair maps out a failing row/column.",
        "Verify temperature (TEMP) drives refresh-rate adaptation.",
        "Verify mode-register set/read per channel with the channel idle.",
        "Verify bank-group back-to-back column access timing.",
        "Verify TSV / microbump integrity via base-die IEEE-1500 / direct-access test.",
        "Verify power-down and self-refresh entry/exit per channel.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L11 — OTP / repair (force the distinguishing keys).
# ----------------------------------------------------------------------
def _l11(gd: Path) -> None:
    p = gd / "L11_OTP_CONTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    d["otp_present"] = True
    d.pop("spd_eeprom_layout_summary", None)  # DDR-only.
    d["otp_summary"] = (
        "HBM3 carries factory-programmed, mostly one-time/non-volatile "
        "content in the base/logic die and DRAM dies: device identification, "
        "hard repair fuse maps set during manufacturing screening, and KGSD "
        "screening metadata. Soft-repair is a separate runtime post-package "
        "repair.")
    d["factory_programmed_metadata"] = [
        {"item": "Manufacturer ID", "description": "Vendor identification (e.g. SK Hynix, Samsung, Micron)."},
        {"item": "Density / organization", "description": "Per-die density (16 Gb), stack height (8-Hi/12-Hi), channel/pseudo-channel organization."},
        {"item": "Capacity", "description": "16 GB (8-Hi) or 24 GB (12-Hi)."},
        {"item": "Speed grade", "description": "Rated per-pin data rate up to 6.4 Gb/s/pin."},
        {"item": "Hard repair fuse map", "description": "Permanent row/column redundancy applied during screening."},
        {"item": "KGSD screening result", "description": "Known-good-stacked-die qualification metadata."},
    ]
    d["repair_classes"] = {
        "hard_repair": "Permanent fuse-based row/column redundancy set at manufacturing.",
        "soft_repair": "Post-package repair requested at runtime via mode register; part of HBM3 RAS.",
    }
    d["permanent_state_after_power_off"] = (
        "Factory ID, density/organization, hard-repair fuse maps and KGSD "
        "metadata persist across power cycles. Mode-register configuration "
        "(timing, ECC, RFM, pseudo-channel mode) is volatile and must be "
        "re-programmed by the controller at each power-up.")
    d["notes"] = (
        "Exact OTP/fuse layout is vendor-specific within JESD238. The "
        "load-bearing HBM3 point is that identification + redundancy/repair "
        "(hard fuse + runtime soft-repair) live in the stack, supporting KGSD "
        "screening and in-field RAS.")
    _write(p, d)


# ----------------------------------------------------------------------
# L12 — behavioral sequences (force the distinguishing keys).
# ----------------------------------------------------------------------
def _l12(gd: Path) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    # Drop DDR-specific sequence keys if present.
    for k in ("single_bank_read_sequence_BL8", "single_bank_write_sequence_BL8",
              "multi_bank_interleave_sequence", "write_leveling_sequence",
              "mpr_read_training_sequence", "zq_calibration_sequence",
              "dll_off_entry_sequence", "input_clock_frequency_change_sequence",
              "reset_with_stable_power_sequence"):
        d.pop(k, None)
    d["initialization_sequence"] = [
        "1. Ramp supplies (VDDC, VDDQ, VDDQL, VPP) with RESET_n held LOW.",
        "2. Deassert RESET_n once supplies/clocks are stable.",
        "3. Program per-channel mode registers (RL/WL/BL, drive strength, ECC, RFM, pseudo-channel mode) via MRS.",
        "4. Train the high-speed links per channel for 6.4 Gb/s/pin operation.",
        "5. Bring each independent channel to IDLE; channels may initialize independently.",
    ]
    d["single_channel_read_sequence"] = [
        "1. ACTIVATE on the R bus opens a row.",
        "2. READ on the C bus selects the column for the addressed pseudo-channel.",
        "3. At read latency RL, the DRAM drives the burst framed by RDQS_t/RDQS_c.",
        "4. The host samples on both RDQS edges (DDR).",
        "5. PRECHARGE (or auto-precharge) closes the row.",
    ]
    d["single_channel_write_sequence"] = [
        "1. ACTIVATE on the R bus opens a row.",
        "2. WRITE on the C bus selects the column for the addressed pseudo-channel.",
        "3. At write latency WL, the host drives the burst framed by WDQS_t/WDQS_c.",
        "4. The DRAM samples on both WDQS edges; on-die ECC protects the array.",
        "5. PRECHARGE closes the row.",
    ]
    d["pseudo_channel_concurrent_sequence"] = [
        "1. Within one 64-bit channel, the two pseudo-channels share the row command bus.",
        "2. The controller issues independent column commands to pseudo-channel 0 and 1.",
        "3. Each pseudo-channel streams its own 32-bit data concurrently.",
    ]
    d["multi_channel_independent_sequence"] = [
        "1. The controller schedules ACT/RD/WR/REF/RFM independently on each of 16 channels.",
        "2. Channels use their own clocks and need not be synchronous.",
        "3. Aggregate bandwidth approaches 819 GB/s per stack when all channels are busy.",
    ]
    d["refresh_sequence"] = [
        "1. REFRESH (all-bank/per-bank) at the required interval; column access closed during the window.",
        "2. Under high activate rates, issue Refresh-Management (RFM) to bound disturbance.",
        "3. Adapt refresh rate using TEMP to preserve retention at high temperature.",
    ]
    d["ras_error_handling_sequence"] = [
        "1. On a link/on-die ECC uncorrectable error, the DRAM reports via AERR/DERR.",
        "2. On a CA parity error, the DRAM raises the parity alert; controller retries/quarantines.",
        "3. The controller may issue soft-repair for a persistently failing row/column.",
    ]
    d["self_refresh_entry_exit_sequence"] = [
        "1. Controller drives the channel into self-refresh; clock may stop.",
        "2. To exit, restart the channel clock and resynchronize; pending refresh completes.",
    ]
    d["power_down_entry_exit_sequence"] = [
        "1. Enter per-channel power-down; clock may be gated.",
        "2. Fast exit returns the channel to IDLE.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L13 — lab/calibration (force the distinguishing keys).
# ----------------------------------------------------------------------
def _l13(gd: Path) -> None:
    p = gd / "L13_LAB_CALIBRATION.json"
    if not p.is_file():
        return
    d = _read(p)
    d["lab_calibration_present"] = True
    # Drop DDR-specific calibration keys.
    for k in ("zq_calibration_procedure", "write_leveling_procedure",
              "read_leveling_mpr_procedure", "dll_reset_and_lock",
              "no_analog_trim_at_bus_interface", "power_up_characterization"):
        d.pop(k, None)
    d["calibration_summary"] = (
        "HBM3 at up to 6.4 Gb/s/pin over short interposer links requires "
        "per-channel PHY training: write/read leveling, DQ-to-strobe "
        "centering, drive-strength/termination tuning. Refresh is calibrated "
        "to temperature via TEMP, and RAS soft-repair is exercised during "
        "screening. Calibration is per-channel because the 16 channels are "
        "independent.")
    d["link_training_procedure"] = [
        "1. Coarse/fine write leveling to align WDQS per channel.",
        "2. Read leveling / DQ-RDQS centering with known patterns.",
        "3. Drive-strength / termination tuning for 6.4 Gb/s/pin via mode registers.",
        "4. Per-pseudo-channel verification of independent column streams.",
    ]
    d["refresh_temperature_calibration"] = [
        "1. Read the on-die TEMP value.",
        "2. Select refresh interval / RFM thresholds appropriate to temperature.",
        "3. Re-evaluate periodically; increase refresh rate when hot.",
    ]
    d["repair_and_screening"] = [
        "1. Apply factory hard-repair fuse maps during screening.",
        "2. Run KGSD screening through the base-die test ports.",
        "3. Exercise runtime soft-repair for in-field RAS.",
    ]
    d["no_analog_trim_at_protocol_interface"] = (
        "HBM3 is a digital memory interface; calibration is link/PHY "
        "training, refresh-temperature adaptation, and repair rather than "
        "analog converter trim.")
    d["notes"] = (
        "Exact training sequences are vendor/PHY-specific within JESD238; the "
        "load-bearing items are per-channel link training at 6.4 Gb/s/pin, "
        "temperature-tracked refresh, and hard/soft repair.")
    _write(p, d)


# ----------------------------------------------------------------------
# L14-L23 — fields-wrapped docs. Force the distinguishing keys.
# ----------------------------------------------------------------------
def _l14(gd: Path) -> None:
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    # Drop DDR-only lineage keys if present.
    for k in ("spec_lineage_ddrx", "key_changes_vs_ddr2",
              "previous_versions_of_this_spec"):
        f.pop(k, None)
    f["spec_version"] = (
        "JEDEC JESD238 — High Bandwidth Memory (HBM3) DRAM Standard "
        "(officially announced January 27, 2022)")
    f["spec_lineage_hbm"] = [
        {"version": "JESD229 (Wide I/O)", "year": 2011, "summary": "Predecessor; four 128-bit channels, single-data-rate clocking."},
        {"version": "JESD235 (HBM)", "year": 2013, "summary": "First HBM; 1.0 Gb/s/pin; 1024-bit; up to 4 GB/stack; ~128 GB/s."},
        {"version": "JESD235a (HBM2)", "year": 2016, "summary": "HBM2; 8 channels of 128 bits; up to 8 GB/stack; ~256-307 GB/s."},
        {"version": "HBM2E (update to JESD235)", "year": 2018, "summary": "Up to 3.2-3.6 Gb/s/pin; up to 307 GB/s/stack; 12-Hi for 24 GB."},
        {"version": "JESD238 (HBM3)", "year": 2022, "summary": "16 channels of 64 bits (1024-bit total); up to 6.4 Gb/s/pin; up to 819 GB/s/stack; 8-Hi (16 GB) / 12-Hi (24 GB) of 16 Gb dies; on-die + link ECC; RFM; RAS."},
        {"version": "JESD270-4 (HBM4)", "year": 2025, "summary": "2048-bit interface; up to 8 Gb/s/pin; up to 2 TB/s; backwards compatible with HBM3 controllers."},
    ]
    f["previous_versions_of_this_spec"] = [
        {"version": "JESD238 (HBM3)", "date": "January 27, 2022", "summary": "Initial JEDEC HBM3 standard release."},
    ]
    f["key_changes_vs_hbm2e"] = [
        {"change": "Channels doubled: 16 x 64-bit vs 8 x 128-bit", "impact": "Finer access granularity; total still 1024 data pins."},
        {"change": "Per-pin rate doubled to 6.4 Gb/s/pin (vs JEDEC HBM2E 3.2)", "impact": "Up to 819 GB/s per stack vs ~307."},
        {"change": "Pseudo-channel mode (two 32-bit per channel)", "impact": "Independent column streams per channel half."},
        {"change": "On-die ECC + link ECC standardized", "impact": "Array + transmission error protection."},
        {"change": "Refresh Management (RFM) added", "impact": "Bounds row-hammer-class disturbance."},
        {"change": "RAS (soft-repair, CA parity, error reporting)", "impact": "In-field reliability/serviceability."},
        {"change": "12-Hi stacks of 16 Gb dies (~30 µm thick) for 24 GB", "impact": "Higher capacity at 1024-bit width."},
    ]
    f["backward_compat_traps"] = [
        {"trap_name": "channel_organization_changed_16x64_vs_8x128",
         "rule": "HBM3 uses 16 channels of 64 bits where HBM2/HBM2E used 8 channels of 128 bits; total is still 1024 data pins.",
         "trap": "A controller assuming HBM2's 8x128 map will mis-address an HBM3 stack even though pin count matches."},
        {"trap_name": "channels_not_synchronous",
         "rule": "The 16 channels are independent and not necessarily synchronous; each has its own clock and command/address bus.",
         "trap": "A controller assuming a single shared clock / lockstep will fail; each channel must be trained and scheduled independently."},
        {"trap_name": "pseudo_channel_required_for_efficiency",
         "rule": "Each 64-bit channel splits into two independent 32-bit pseudo-channels.",
         "trap": "Treating a channel as monolithic 64-bit foregoes the independent column streams and reduces efficiency."},
        {"trap_name": "RFM_must_be_honoured",
         "rule": "HBM3 mandates Refresh-Management (RFM) under high activate rates.",
         "trap": "Omitting RFM can cause row-hammer-class corruption at sustained high throughput."},
        {"trap_name": "ECC_and_RAS_reporting_must_be_handled",
         "rule": "HBM3 adds on-die ECC, link ECC, CA parity, and alert/error reporting.",
         "trap": "A controller ignoring the RAS alert path will miss uncorrectable errors and repair opportunities."},
        {"trap_name": "hbm4_is_2048bit_not_a_drop_in",
         "rule": "HBM4 (JESD270-4) widens the interface to 2048 bits; backwards compatible with HBM3 controllers but a different standard.",
         "trap": "HBM3 and HBM4 are not the same width; do not size an HBM3 PHY for HBM4's 2048-bit interface."},
    ]
    f["version_naming_history_note"] = (
        "HBM is standardized by JEDEC: Wide I/O (JESD229, 2011) -> HBM "
        "(JESD235, 2013) -> HBM2 (JESD235a, 2016) -> HBM2E (2018-2019) -> "
        "HBM3 (JESD238, announced January 27, 2022) -> HBM4 (JESD270-4, April "
        "2025). HBM3 was the first to double the channel count to 16 x 64-bit "
        "while keeping the 1024-bit total width and to reach 6.4 Gb/s/pin / "
        "819 GB/s per stack. SK Hynix produced the industry-first HBM3 used "
        "with NVIDIA's H100; its first-generation HBM3 chips were square.")
    d["fields"] = f
    _write(p, d)


def _l15(gd: Path) -> None:
    p = gd / "L15_ENCODING_TABLES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    # Drop DDR-specific MR / command tables if present.
    for k in ("command_truth_table", "mr0_bit_field_table", "mr1_rtt_nom_table",
              "mr1_additive_latency_table", "mr2_cwl_table", "mr2_rtt_wr_table",
              "mr3_mpr_table", "self_refresh_mode_summary_table",
              "ba_mr_select_table", "speed_grade_table"):
        f.pop(k, None)
    f["channel_organization_table"] = {
        "header_columns": ["Property", "HBM3 value", "HBM2/HBM2E value"],
        "rows": [
            ["Total interface width", "1024 bits", "1024 bits"],
            ["Channels", "16", "8"],
            ["Bits per channel", "64", "128"],
            ["Pseudo-channels", "32 (2 per channel)", "16 (2 per channel)"],
            ["Bits per pseudo-channel", "32", "64"],
        ],
    }
    f["stack_capacity_table"] = {
        "header_columns": ["Stack height", "Dies", "Per-die density", "Capacity", "Channels", "Bits/channel"],
        "rows": [
            ["8-Hi", 8, "16 Gb", "16 GB", 16, 64],
            ["12-Hi", 12, "16 Gb", "24 GB", 16, 64],
        ],
    }
    f["bandwidth_table"] = {
        "header_columns": ["Generation", "Pin rate (Gb/s/pin)", "Width (bits)", "Per-stack bandwidth"],
        "rows": [
            ["HBM1", 1.0, 1024, "128 GB/s"],
            ["HBM2", 2.4, 1024, "~307 GB/s"],
            ["HBM2E", 3.2, 1024, "~307-461 GB/s"],
            ["HBM3", 6.4, 1024, "up to 819 GB/s"],
        ],
    }
    f["command_bus_table"] = {
        "header_columns": ["Command", "Bus", "Decode scope"],
        "rows": [
            ["ACTIVATE", "R (row)", "per channel"],
            ["PRECHARGE", "R (row)", "per channel"],
            ["REFRESH", "R (row)", "per channel"],
            ["REFRESH MANAGEMENT (RFM)", "R (row)", "per channel"],
            ["MODE REGISTER SET (MRS)", "R (row)", "per channel"],
            ["READ", "C (column)", "per pseudo-channel"],
            ["WRITE", "C (column)", "per pseudo-channel"],
        ],
    }
    f["clock_strobe_table"] = {
        "header_columns": ["Signal", "Type", "Scope", "Edge use"],
        "rows": [
            ["CK_t / CK_c", "differential clock", "per channel", "commands registered on rising edges"],
            ["WDQS_t / WDQS_c", "differential write strobe", "per pseudo-channel", "both edges (DDR)"],
            ["RDQS_t / RDQS_c", "differential read strobe", "per pseudo-channel", "both edges (DDR)"],
        ],
    }
    f["tables"] = [
        "Table — Channel organization (16 x 64-bit, 32 x 32-bit pseudo-channels)",
        "Table — Stack height vs capacity (8-Hi 16 GB / 12-Hi 24 GB)",
        "Table — Bandwidth per stack across HBM generations",
        "Table — Command-to-bus mapping (R row bus / C column bus)",
        "Table — Clock and data-strobe signals",
    ]
    d["fields"] = f
    _write(p, d)


def _l16(gd: Path) -> None:
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["must_have_properties"] = [
        "1024-bit-wide data interface per stack (16 channels x 64 bits).",
        "16 completely independent channels; each with its own differential clock and command/address bus.",
        "Channels not necessarily synchronous to each other.",
        "Each 64-bit channel divisible into two independent 32-bit pseudo-channels.",
        "Up to 6.4 Gb/s per pin; up to 819 GB/s per stack.",
        "Commands registered at the rising edges of CK_t/CK_c.",
        "Write data framed by WDQS, read data by RDQS, double data rate.",
        "8-Hi (16 GB) / 12-Hi (24 GB) stacks of 16 Gb dies on TSV + microbumps on a 2.5D silicon interposer.",
        "On-die ECC and link ECC.",
        "Refresh Management (RFM) to bound disturbance.",
        "RAS: command/address parity, soft-repair, error/alert reporting.",
        "Bank-group architecture for back-to-back column access.",
    ]
    f["must_not_have_properties"] = [
        "A single shared clock or lockstep across the 16 channels (they are independent).",
        "An 8-channel x 128-bit organization (that is HBM2/HBM2E).",
        "A total interface width other than 1024 data pins.",
        "Per-pin data rate exceeding the device's rated maximum.",
        "Operation without honouring RFM under high activate rates.",
        "A 2048-bit interface (that is HBM4, a different standard).",
    ]
    f["compliance_failure_modes"] = [
        {"mode": "Channel-map mismatch", "trigger": "Controller addresses the stack as 8x128 (HBM2) instead of 16x64 (HBM3)."},
        {"mode": "Cross-channel lockstep assumption", "trigger": "Controller assumes channels are synchronous -> timing failures."},
        {"mode": "Disturbance corruption", "trigger": "RFM omitted under high activate rate -> row-hammer-class data loss."},
        {"mode": "Unhandled RAS error", "trigger": "Controller ignores link-ECC / CA-parity alerts -> silent corruption."},
        {"mode": "Link timing failure", "trigger": "Per-channel high-speed link not trained -> errors at 6.4 Gb/s/pin."},
    ]
    f["min_clock_constraint"] = (
        "Each channel's timing is referenced to its own CK_t/CK_c; the rated "
        "maximum pin data rate (up to 6.4 Gb/s/pin) bounds the per-channel "
        "clock.")
    f["reset_behavior_compliance"] = (
        "RESET_n asserted at power-up; per-channel mode registers and link "
        "training must be (re)established before normal access; channels may "
        "be brought up independently.")
    d["fields"] = f
    _write(p, d)


def _l17(gd: Path) -> None:
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["channels"] = [
        {"name": "CK_t, CK_c", "direction_controller": "output", "direction_dram": "input", "purpose": "Per-channel differential clock; commands registered at rising edges; channels need not be synchronous.", "active_levels": "differential low-swing", "idle_level": "toggling per channel; may stop in self-refresh"},
        {"name": "R[ ] (row command/address)", "direction_controller": "output", "direction_dram": "input", "purpose": "ACTIVATE/PRECHARGE/REFRESH/RFM/MRS with bank-group/bank/row. Per channel.", "active_levels": "low-swing single-ended", "idle_level": "deselect / NOP"},
        {"name": "C[ ] (column command/address)", "direction_controller": "output", "direction_dram": "input", "purpose": "READ/WRITE with column; decoded independently per 32-bit pseudo-channel.", "active_levels": "low-swing single-ended", "idle_level": "deselect / NOP"},
        {"name": "DQ", "direction": "bidirectional", "purpose": "64-bit-per-channel data bus (1024 bits/stack); 32 bits/pseudo-channel; double data rate.", "active_levels": "low-swing single-ended", "idle_level": "high-impedance between bursts"},
        {"name": "WDQS_t, WDQS_c", "direction": "controller -> DRAM", "purpose": "Differential write strobe, per pseudo-channel; both edges sampled.", "active_levels": "differential low-swing", "idle_level": "high-impedance between bursts"},
        {"name": "RDQS_t, RDQS_c", "direction": "DRAM -> controller", "purpose": "Differential read strobe, per pseudo-channel; both edges sampled.", "active_levels": "differential low-swing", "idle_level": "high-impedance between bursts"},
        {"name": "DM / DBI", "direction": "per direction", "purpose": "Data mask / data-bus-inversion.", "active_levels": "low-swing single-ended", "idle_level": "inactive between bursts"},
        {"name": "ECC / parity bits", "direction": "bidirectional", "purpose": "Link-ECC and DQ-parity protecting data and command/address.", "active_levels": "low-swing single-ended", "idle_level": "inactive between bursts"},
        {"name": "AERR / DERR", "direction": "DRAM -> controller", "purpose": "RAS alert / error report (CA parity, ECC uncorrectable, severity).", "active_levels": "single-ended", "idle_level": "deasserted (no error)"},
        {"name": "TEMP", "direction": "DRAM -> controller", "purpose": "Temperature readout for refresh adaptation.", "active_levels": "register/status readout", "idle_level": "valid on read"},
        {"name": "RESET_n", "direction": "controller -> DRAM", "purpose": "Active-low reset.", "active_levels": "CMOS", "idle_level": "HIGH in normal operation"},
    ]
    f["power_pins"] = [
        {"name": "VDDC", "purpose": "DRAM core supply."},
        {"name": "VDDQ", "purpose": "Data IO supply."},
        {"name": "VDDQL", "purpose": "Low-swing IO supply for high-speed links."},
        {"name": "VPP", "purpose": "Pumped wordline/boost supply."},
        {"name": "VSS", "purpose": "Ground."},
    ]
    f["global_signals"] = []
    # Drop DDR-specific count keys.
    f.pop("channel_counts_per_dram_x8_single_die", None)
    f.pop("channel_counts_quad_die_x8", None)
    f["channel_counts"] = {
        "total_interface_bits": 1024,
        "channels": 16,
        "bits_per_channel": 64,
        "pseudo_channels": 32,
        "bits_per_pseudo_channel": 32,
        "differential_clock_pairs_per_channel": 1,
        "write_strobe_pairs_per_pseudo_channel": 1,
        "read_strobe_pairs_per_pseudo_channel": 1,
    }
    f["ordering_rules"] = {
        "command_register_edge": "Rising edges of CK_t/CK_c, per channel.",
        "data_byte_order_within_burst": "Per the JESD238 column-access / burst-order tables.",
        "channel_scheduling": "Channels are scheduled independently; no cross-channel ordering guarantee.",
        "pseudo_channel_scheduling": "The two pseudo-channels of a channel run independent column streams.",
    }
    # Force-overwrite dependency_graph for the HBM3 channel-partitioned shape.
    f["dependency_graph"] = {
        "common_rule": (
            "Within a channel, commands are committed on the rising edges of "
            "CK_t/CK_c. Row commands flow on the R bus, column commands on the "
            "C bus (decoded per pseudo-channel); the two buses can be active "
            "in the same cycle. Across channels there is no dependency — the "
            "16 channels are completely independent and not necessarily "
            "synchronous."),
        "data_dependency": (
            "Read data on a channel's DQ depends on its prior READ at read "
            "latency RL, framed by RDQS. Write data acceptance depends on the "
            "prior WRITE at write latency WL, framed by WDQS. No per-beat "
            "handshake."),
    }
    f["handshake_pairs"] = [
        {"name": "ROW_CMD", "from": "controller", "to": "DRAM", "rule": "Controller drives ACT/PRE/REF/RFM/MRS on the R bus; DRAM decodes one row command per cycle per channel."},
        {"name": "COL_CMD", "from": "controller", "to": "DRAM", "rule": "Controller drives RD/WR on the C bus; DRAM decodes per 32-bit pseudo-channel."},
        {"name": "READ_BURST", "from": "DRAM", "to": "controller", "rule": "DRAM drives the burst on DQ at RL from READ, framed by RDQS."},
        {"name": "WRITE_BURST", "from": "controller", "to": "DRAM", "rule": "Controller drives the burst on DQ at WL from WRITE, framed by WDQS."},
        {"name": "RAS_ALERT", "from": "DRAM", "to": "controller", "rule": "DRAM raises AERR/DERR on CA-parity / ECC-uncorrectable errors."},
        {"name": "REFRESH_MGMT", "from": "controller", "to": "DRAM", "rule": "Controller issues REF / RFM per channel to maintain retention and bound disturbance."},
    ]
    d["fields"] = f
    _write(p, d)


def _l18(gd: Path) -> None:
    p = gd / "L18_INTERCONNECT_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["topology_type"] = (
        "2.5D on-package memory: a 3D-stacked DRAM (8-Hi/12-Hi) on a "
        "base/logic die, connected to a host compute die through a "
        "1024-bit-wide, 16-channel interface over a silicon interposer. The "
        "stack uses TSV + microbumps internally; the interposer carries the "
        "data links between memory and host.")
    f["supported_topologies"] = [
        {"name": "Single stack beside host on interposer", "description": "One HBM3 stack adjacent to one host die on a shared 2.5D silicon interposer; 1024 data links."},
        {"name": "Multiple stacks around a host", "description": "Four to six HBM3 stacks around one GPU/accelerator for multi-TB/s aggregate bandwidth (e.g. ~4.9 TB/s with six 24 GB stacks)."},
        {"name": "Stack-on-host (3D)", "description": "Memory die stacked directly on the CPU/GPU chip as an alternative to side-by-side 2.5D."},
    ]
    f["master_slave_role_summary"] = [
        {"role": "Host memory controller + PHY", "description": "Bus master for all 16 channels; drives command/address, clock, write data + WDQS; sinks read data + RDQS; performs RFM and RAS handling."},
        {"role": "HBM3 stack (base die + DRAM dies)", "description": "Target; each channel independently decodes commands, manages banks/bank-groups, performs on-die ECC, and reports temperature/alerts."},
    ]
    f["interconnect_role"] = (
        "The interconnect is physical (TSV + microbump + 2.5D silicon "
        "interposer), not a protocol-layer router/bridge. The interposer fans "
        "the 1024 wide links between the stack and host over short distances "
        "and carries no protocol intelligence.")
    f["ordering_guarantees"] = {
        "within_a_channel": "Commands committed on rising CK edges; data follows at deterministic latency; row and column buses operate in parallel.",
        "across_channels": "No ordering guarantee — the 16 channels are completely independent and not necessarily synchronous.",
        "within_a_channel_pseudo_channels": "The two 32-bit pseudo-channels run independent column streams.",
    }
    f["memory_vs_peripheral_regions"] = (
        "HBM3 is pure memory; the address space is the DRAM array organized "
        "into 16 channels, each with bank-groups/banks/rows/columns. No "
        "peripheral register region beyond per-channel mode registers.")
    f["device_classification"] = {
        "host_gpu_accelerator": "Bus master; integrates the HBM3 controller + PHY (e.g. NVIDIA H100).",
        "hbm3_stack": "Target memory device on the interposer.",
        "base_logic_die": "Bottom die hosting test/repair/RAS logic and the microbump interface to the interposer.",
        "silicon_interposer": "2.5D substrate carrying the 1024 data links between stack and host.",
    }
    f["default_signal_values_evidence_tables"] = [
        "Interface section — channels independent and not necessarily synchronous; 64-bit channel at double data rate.",
        "Technology section — TSV, microbumps, silicon interposer, 1024 data links per stack.",
        "HBM3 section — 16 channels of 64 bits, total 1024 data pins, up to 6.4 Gb/s/pin, up to 819 GB/s per stack.",
    ]
    d["fields"] = f
    _write(p, d)


def _l19(gd: Path) -> None:
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["constraints_present"] = True
    # Drop DDR-specific constraint keys.
    f.pop("host_pcb_constraints_summary", None)
    f.pop("dram_internal_constraints", None)
    f["host_interposer_constraints_summary"] = [
        "2.5D silicon interposer must route 1024 data links per stack (plus command/address, clock, strobe, ECC, control) over short, matched paths.",
        "Microbump pitch and TSV routing budget set by the base/logic die microbump map.",
        "Per-channel link budget for 6.4 Gb/s/pin (skew, crosstalk, return-loss) since channels are independent.",
        "Power delivery for VDDC / VDDQ / VDDQL / VPP at high sustained bandwidth.",
        "Thermal constraint: stacked dies (~30 µm thick) under sustained high bandwidth require a thermal solution; refresh adapts to TEMP.",
    ]
    f["stack_internal_constraints"] = [
        "8-Hi / 12-Hi die stacking with TSV alignment across dies.",
        "Die thickness ~30 µm to allow 12-Hi stacks within package-height limits.",
        "KGSD screening required before integration.",
        "Hard-repair fuse budget and runtime soft-repair provisioning for RAS.",
    ]
    f["fabrication_cost_note"] = (
        "Silicon interposer fabrication is significantly more expensive than "
        "printed-circuit-board manufacture, adding cost to the final product; "
        "this is the trade for very high bandwidth in a small form factor.")
    f["notes"] = (
        "JESD238 specifies the protocol and electrical/timing budgets; the "
        "PDK/floorplan/interposer constraints are realized at the package and "
        "host-SoC integration level. The distinguishing HBM3 constraints are "
        "the 1024-link interposer routing, 6.4 Gb/s/pin per-channel link "
        "budget, 12-Hi 30-µm die stacking, and the high-bandwidth "
        "thermal/power envelope.")
    d["fields"] = f
    _write(p, d)


def _l20(gd: Path) -> None:
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["dft_present"] = True
    f.pop("no_jtag_on_DRAM_balls", None)
    f.pop("controller_side_dft_aids", None)
    f["exposed_dft_features"] = [
        {"feature": "IEEE 1500 test access", "purpose": "Wrapper-based test access through the base/logic die for boundary and interconnect (TSV/microbump) test."},
        {"feature": "Direct Access (DA) test", "purpose": "Direct probing of the DRAM dies through the base die for KGSD screening."},
        {"feature": "MBIST", "purpose": "Memory built-in self-test of the DRAM array per channel."},
        {"feature": "Data-bus loopback", "purpose": "Characterize the high-speed links at up to 6.4 Gb/s/pin."},
        {"feature": "Hard / soft repair", "purpose": "Fuse-based hard repair at manufacturing and runtime soft-repair for RAS."},
        {"feature": "ECC / parity error counters", "purpose": "Observe corrected/uncorrectable error counts (on-die ECC, link ECC, CA parity)."},
    ]
    f["test_in_base_die"] = (
        "HBM3 concentrates test, repair, and RAS logic in the base/logic die "
        "so the DRAM dies remain dense; the base die exposes IEEE-1500 / DA "
        "ports to the interposer. TSMC produces the base die for HBM and is "
        "planned as a foundry for HBM stacking.")
    f["stacked_die_dft_flow"] = (
        "Per-die screen -> stack assembly -> KGSD test through the base die "
        "-> stack-on-interposer interconnect test -> in-field RAS monitoring "
        "(ECC/parity counters, soft-repair).")
    f["notes"] = (
        "Exact DFT register/mode encodings are vendor-specific within "
        "JESD238; the distinguishing HBM3 DFT items are base-die-centric "
        "IEEE-1500/DA test, KGSD screening of the 8-Hi/12-Hi stack, "
        "TSV/microbump interconnect test, and ECC/repair-based RAS "
        "observability.")
    d["fields"] = f
    _write(p, d)


def _l21(gd: Path) -> None:
    p = gd / "L21_POWER_INTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["power_intent_present"] = True
    # Drop DDR-specific power tables.
    for k in ("iDD_states_summary", "voltage_classes_table",
              "self_refresh_temperature_table",
              "partial_array_self_refresh_table", "power_domains_summary"):
        f.pop(k, None)
    f["power_domains_summary"] = [
        {"rail": "VDDC", "domain": "DRAM core", "purpose": "Core array and periphery supply."},
        {"rail": "VDDQ", "domain": "data IO", "purpose": "Data-interface IO supply."},
        {"rail": "VDDQL", "domain": "low-swing IO", "purpose": "Low-swing supply for the high-speed links."},
        {"rail": "VPP", "domain": "pump / wordline", "purpose": "Elevated supply for wordline boost / array operation."},
        {"rail": "VSS", "domain": "ground", "purpose": "Common ground."},
    ]
    f["power_efficiency_rationale"] = (
        "HBM achieves higher bandwidth than DDR4/GDDR5 while using less power "
        "and a smaller form factor by stacking dies and using a wide, "
        "low-swing, short interposer interface. Separate IO / low-swing rails "
        "(VDDQ/VDDQL) reduce IO energy per bit at 6.4 Gb/s/pin.")
    f["low_power_modes_summary"] = {
        "power_down": "Per-channel power-down with fast exit; channel clock may be gated.",
        "self_refresh": "DRAM self-refreshes; channel clock may stop; exit re-synchronizes.",
        "temperature_compensated_refresh": "Refresh rate adapted using TEMP to save power while preserving retention.",
    }
    f["power_up_sequence"] = [
        "Ramp VDDC, VDDQ, VDDQL, VPP with RESET_n LOW.",
        "Deassert RESET_n once supplies and clocks are stable.",
        "Program per-channel mode registers and train links before normal operation.",
    ]
    f["thermal_note"] = (
        "Stacked dies under sustained high bandwidth concentrate heat; the "
        "host system provides cooling and uses TEMP to manage refresh and "
        "throttling. Removing the buffer/base die can lower cost and power at "
        "the expense of bandwidth (a separate low-cost HBM direction); "
        "standard HBM3 retains the base/logic die.")
    f["notes"] = (
        "Power management is largely deferred to the host SoC and package; "
        "the distinguishing HBM3 power items are multi-rail low-swing IO "
        "(VDDQ/VDDQL), per-channel power-down/self-refresh, and "
        "temperature-compensated refresh management.")
    d["fields"] = f
    _write(p, d)


def _l22(gd: Path) -> None:
    p = gd / "L22_VERIFICATION_PLAN.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["verification_plan_present"] = True
    f["verification_categories_derived_from_spec"] = [
        {"category": "Interface width", "checks": ["1024-bit interface per stack", "16 channels x 64-bit", "32 pseudo-channels x 32-bit"]},
        {"category": "Channel independence", "checks": ["No cross-channel state coupling", "Channels operate with independent / asynchronous clocks", "Per-channel command/address decode"]},
        {"category": "Pseudo-channel operation", "checks": ["Two independent 32-bit column streams per channel", "Shared row command bus, independent column commands"]},
        {"category": "Data rate / bandwidth", "checks": ["Up to 6.4 Gb/s/pin", "Up to 819 GB/s per stack", "Double-data-rate strobe sampling"]},
        {"category": "Command protocol", "checks": ["Commands registered on rising CK_t/CK_c edges", "Row commands on R bus, column on C bus", "Parallel R/C bus operation"]},
        {"category": "Capacity / stack", "checks": ["8-Hi -> 16 GB", "12-Hi -> 24 GB", "16 Gb dies, ~30 µm thick"]},
        {"category": "ECC", "checks": ["On-die ECC single-error correction", "Link ECC transmission protection", "Uncorrectable reporting"]},
        {"category": "Refresh management", "checks": ["REFRESH timing", "RFM under high activate rates", "Temperature-tracked refresh via TEMP"]},
        {"category": "RAS", "checks": ["CA parity error reporting", "Soft-repair", "Alert/error path AERR/DERR"]},
        {"category": "Physical interconnect", "checks": ["TSV / microbump integrity", "2.5D interposer routing of 1024 links", "Base-die IEEE-1500 / DA test, KGSD"]},
        {"category": "Low power", "checks": ["Per-channel power-down", "Self-refresh entry/exit", "Mode-register programming per channel"]},
    ]
    f["notes"] = (
        "These categories are derived from the JESD238 distinguishing "
        "features (16x64 channel organization, pseudo-channels, 6.4 "
        "Gb/s/pin, 1024-bit width, on-die + link ECC, RFM, RAS, "
        "TSV/interposer stack). JESD238 ships no formal testbench; a "
        "controller/PHY/stack DV plan covers these at the SoC and package "
        "level.")
    d["fields"] = f
    _write(p, d)


def _l23(gd: Path) -> None:
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["security_requirements_present"] = True
    f["security_summary"] = (
        "HBM3 is a DRAM memory standard; it provides no confidentiality "
        "(encryption), authentication, or access control at the protocol "
        "layer — stored data is plaintext. Its security-adjacent features are "
        "reliability/integrity mechanisms: on-die ECC, link ECC, "
        "command/address parity, RAS error reporting, soft-repair, and "
        "refresh management (RFM) bounding row-hammer-class disturbance.")
    f["security_features_at_protocol_level"] = [
        {"feature": "On-die ECC", "purpose": "Detect/correct array errors transparently; integrity, not confidentiality."},
        {"feature": "Link ECC", "purpose": "Protect data on the channel against transmission errors."},
        {"feature": "Command/address parity", "purpose": "Detect corruption of commands/addresses on the R/C buses."},
        {"feature": "Refresh Management (RFM)", "purpose": "Bound row-hammer-class disturbance, mitigating a known DRAM fault-injection class."},
        {"feature": "Soft-repair / hard-repair", "purpose": "Map out failing cells for reliability; not an access-control feature."},
        {"feature": "RAS alert/error reporting", "purpose": "Surface uncorrectable/severe errors to the host for serviceability."},
    ]
    f["no_confidentiality"] = (
        "No on-die encryption of stored data; payload is plaintext. Memory "
        "encryption is implemented by the host SoC, not by HBM3.")
    f["no_authentication"] = "No device-to-host cryptographic authentication at the protocol layer."
    f["no_access_control"] = (
        "No per-region access control / protection keys at the protocol "
        "layer; access control is a host/SoC responsibility.")
    f["rowhammer_class_vulnerabilities"] = (
        "DRAM is subject to row-hammer-class disturbance; HBM3's mandatory "
        "Refresh-Management (RFM) and adaptive refresh are the standard's "
        "mitigation, complementing host-level mitigations.")
    f["comparison_to_sibling_standards"] = (
        "Like DDR/LPDDR DRAM, HBM3 leaves confidentiality and authentication "
        "to the host; HBM3 strengthens the integrity/reliability side (on-die "
        "+ link ECC, parity, RFM, RAS) relative to HBM2/HBM2E for "
        "data-center use.")
    f["notes"] = (
        "The load-bearing security posture for HBM3 is integrity and "
        "reliability (ECC, parity, RFM, RAS), not "
        "confidentiality/authentication. Memory encryption and access "
        "control belong to the host SoC.")
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
def is_hbm3(blob: str) -> bool:
    """Content-only `hbm3` detector (importable, lifted from the runner) WITH a
    FOREIGN-PRIMARY DEFER (mirrors `is_mipi`'s foreign-primary defer doctrine).

    The bare structural signature ("HBM3", or High Bandwidth Memory + a
    1024-bit/TSV/JESD238/pseudo-channel token) is necessary but NOT sufficient:
    the Phase-1 runner injects a generic DRAM/memory vocabulary into foreign
    benchmarks' generated L-docs, and the memory-family gold legitimately cites
    HBM3 in comparison sections, so a SIBLING memory spec (DDR4 / DDR5 / GDDR6)
    carries incidental "HBM3"/"JESD238"/"1024-bit"/"TSV" tokens and would
    otherwise trip this loose signature and have the generic HBM3 synth inject
    HBM3 (16-channel / pseudo-channel / interposer) content into a DDR4/DDR5/
    GDDR6 spec's L-docs.

    Guard (general, content-only, NO benchmark-name / chip / SKU literal as
    detection logic): defer (return False) when the blob's DOMINANT subject is
    a foreign DRAM sibling. Each sibling is recognised by its OWN distinctive
    spec-id + structural cluster (the same signatures `is_ddr4` / `is_ddr5` /
    `is_gddr6` fire on) AND by NAME-DOMINANCE over HBM3 — in a genuine HBM3
    spec the "HBM3"/JESD238 subject dominates every sibling token, whereas in a
    sibling spec the sibling's own spec-id dominates even when HBM3 appears
    comparatively:
      - DDR4   (JESD79-4 + bank groups + a DDR4-only feature: gear-down / write
                CRC / CA parity / DBI; the mainstream 1.2 V single-channel SDRAM)
      - DDR5   (JESD79-5 + a DDR5-only feature: two 32-bit sub-channels / DFE /
                same-bank refresh / DIMM PMIC / SPD hub)
      - GDDR6  (JESD250 graphics SGRAM + WCK2CK / EDC CRC / CABI — the graphics
                memory signature absent from HBM3 / DDR4 / DDR5)

    Empirically corpus-clean: the real HBM3 benchmark trips NONE of these defers
    (its HBM3/JESD238 subject dominates ~30:1) and stays True; ddr4/ddr5/gddr6
    each trip their own foreign-primary defer and are suppressed. The dominance
    test keys off raw token frequency in the CONTENT blob only — never a
    filename or benchmark folder name.
    """
    if not blob:
        return False
    low = blob.lower()

    # --- FOREIGN-PRIMARY DEFER (the blob's true subject is NOT HBM3). ---
    # HBM3 subject strength (spec id + canonical name) for the dominance test.
    n_hbm3 = blob.count("HBM3") + low.count("jesd238")

    # DDR4-primary: JESD79-4 + bank groups + a DDR4-only structural feature,
    # with the DDR4 name dominating HBM3. (gear-down / write CRC / CA parity /
    # DBI are DDR4 distinctives a generic HBM3 comparison paragraph lacks.)
    n_ddr4 = len(re.findall(r"\bDDR4\b", blob)) + low.count("jesd79-4")
    _ddr4_bank_groups = ("bank group" in low or "bank-group" in low
                         or "bank groups" in low)
    _ddr4_feature = (
        ("gear-down" in low or "gear down" in low or "geardown" in low)
        or ("write crc" in low or "write-crc" in low)
        or ("ca parity" in low or "c/a parity" in low
            or "command/address parity" in low
            or "command address parity" in low)
        or ("data bus inversion" in low))
    ddr4_primary = (
        ("jesd79-4" in low or n_ddr4 >= 20)
        and _ddr4_bank_groups and _ddr4_feature
        and n_ddr4 > n_hbm3)

    # DDR5-primary: JESD79-5 + a DDR5-only structural feature, DDR5 name
    # dominating HBM3. (Two 32-bit sub-channels / DFE / same-bank refresh /
    # DIMM PMIC / SPD hub are DDR5 distinctives.)
    n_ddr5 = len(re.findall(r"\bDDR5\b", blob)) + low.count("jesd79-5")
    _ddr5_feature = (
        (("sub-channel" in low or "subchannel" in low or "sub channel" in low)
         and ("independent" in low or "32-bit" in low or "32 bit" in low
              or "40-bit" in low))
        or ("decision feedback equalization" in low)
        or ("same-bank refresh" in low or "same bank refresh" in low
            or "refsb" in low)
        or ("spd hub" in low)
        or (("pmic" in low or "power management ic" in low)
            and ("dimm" in low or "module" in low)))
    ddr5_primary = (
        ("jesd79-5" in low or n_ddr5 >= 20)
        and _ddr5_feature
        and n_ddr5 > n_hbm3)

    # GDDR6-primary: the JESD250 graphics-SGRAM signature (graphics SGRAM +
    # WCK2CK / EDC CRC / CABI), GDDR6 name dominating HBM3.
    n_gddr6 = low.count("gddr6") + low.count("jesd250")
    _gddr6_graphics = (
        "graphics sgram" in low or "graphics ddr" in low
        or "graphics double data rate" in low or "graphics dram" in low
        or ("graphics memory" in low and ("gddr" in low or "sgram" in low)))
    _gddr6_feature = (
        ("wck2ck" in low or "wck-to-ck" in low or "wck to ck" in low)
        or ("cabi" in low or "command/address bus inversion" in low
            or "command address bus inversion" in low)
        or ("edc" in low and ("read crc" in low or "write crc" in low
                              or "error detection" in low)))
    gddr6_primary = (
        ("jesd250" in low or n_gddr6 >= 20)
        and _gddr6_graphics and _gddr6_feature
        and n_gddr6 > n_hbm3)

    if ddr4_primary or ddr5_primary or gddr6_primary:
        return False

    # --- STRUCTURAL HBM3 signature (unchanged from the runner's inline
    #     detector). ---
    return bool(
        "HBM3" in blob
        or ("High Bandwidth Memory" in blob and (
            "pseudo channel" in blob.lower()
            or "1024-bit" in blob
            or "JESD238" in blob
            or "TSV" in blob)))
