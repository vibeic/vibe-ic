"""GDDR6 SGRAM (JEDEC JESD250) protocol synth helper (graphics DDR memory).

ic_class-gated overlay for the GDDR6 structural signature: a high-bandwidth,
point-to-point GRAPHICS DRAM standardized by JEDEC in JESD250, organized as TWO
INDEPENDENT 16-bit channels per device (each with its own CK / WCK / CA / DQ /
EDC), clocked by a quarter-rate command clock CK plus a separate higher-rate
Write Clock WCK (with WCK2CK alignment/training), using a 16n prefetch with
fixed burst length BL16 in NRZ signaling at 16-18 Gb/s per pin, with Data Bus
Inversion (DBI), Command/Address Bus Inversion (CABI), and an 8-bit-per-byte-lane
read/write CRC carried on the Error-Detection (EDC) pins (with a programmable EDC
hold pattern), a bank-group memory array, and mode registers MR0..MR15.
Applies the JEDEC JESD250 GDDR6 spec-canonical content to L1-L23.

Doctrine — GENERAL not keyword: detection uses canonical STRUCTURAL signatures
(graphics SGRAM + two-independent-16-bit-channel + WCK + EDC read/write CRC +
CABI + JESD250) read from the L-doc / input_doc CONTENT blob only. It NEVER
reads the input-document filename or the benchmark folder name.

Sibling disambiguation — the JEDEC memory family. GDDR6 shares the broad DRAM
vocabulary (SDRAM, bank group, mode register, ACTIVATE/PRECHARGE, refresh) with
DDR3/DDR4/DDR5, LPDDR5, and HBM3, so a NAME token alone is never sufficient:

  * DDR3 / DDR4 / DDR5 (JESD79-x): mainstream CK-ONLY DIMM/module memory with a
    shared multi-rank command/data bus, NO separate WCK, NO EDC error-detection
    pins, NO per-byte read/write CRC on EDC, NOT organized as two independent
    graphics channels. The detector DEFERS if the doc is DDR3/4/5-primary
    (JESD79-x / DIMM and no WCK / no EDC-graphics signature).

  * LPDDR5 (JESD209-5): a low-power MOBILE DRAM that ALSO uses a WCK write clock
    — so WCK ALONE does NOT distinguish GDDR6 from LPDDR5. LPDDR5 is low-power /
    mobile, has NO graphics-SGRAM context, NO EDC read/write CRC pins, and is not
    a JESD250 graphics device. The detector REQUIRES the GDDR6-only structural
    vocabulary (graphics SGRAM / JESD250 / EDC read+write CRC pins / CABI /
    two-independent-16-bit-channel) on top of WCK and DEFERS to LPDDR5 when the
    doc is LPDDR5-primary (JESD209-5 / low-power-mobile / no EDC-CRC / no
    JESD250 / no graphics).

  * HBM3 (JESD238): a 3D TSV-stacked DRAM with a 1024-bit-wide interface on a
    silicon interposer (stacked / on-interposer), NOT the point-to-point on-board
    / on-package x16 device GDDR6 is. The detector DEFERS if the doc is
    HBM3-primary (JESD238 / 1024-bit / TSV-stacked / interposer and no JESD250 /
    no graphics-SGRAM / no EDC read+write CRC).

Public entry: ``apply_gddr6_synth(generated_docs_dir, is_gddr6, gddr6_ic_name)``.
Module-level ``is_gddr6(blob)`` is the content-only detector.
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

# Canonical GDDR6 facts (JEDEC JESD250 Graphics DDR6 SGRAM).
_CHANNELS_PER_DEVICE = 2
_CHANNEL_WIDTH_BITS = 16
_PREFETCH = "16n"
_BURST_LENGTH = 16
_PER_PIN_RATE_GBPS = [16, 18]
_CRC_BITS = 8
_NUM_MODE_REGISTERS = 16  # MR0..MR15
_VDD_V = 1.35
_VDDQ_V = 1.35
_VPP_V = 1.8
_SIGNALING = "NRZ"


# ----------------------------------------------------------------------
# Module-level content-only detector with a JEDEC-memory-family MUTEX.
# ----------------------------------------------------------------------
def is_gddr6(blob: str) -> bool:
    """Content-only GDDR6 detector with a DDR3/4/5 + LPDDR5 + HBM3 sibling MUTEX.

    Fire on the GDDR6 structural signature: a JESD250 graphics SGRAM organized as
    two independent 16-bit channels, with a WCK write clock (WCK2CK alignment) on
    top of a quarter-rate CK, EDC read+write CRC pins, CABI, DBI, prefetch 16n /
    BL16. Because WCK alone is shared with LPDDR5, and the broad DRAM vocabulary
    is shared with DDR3/4/5 and HBM3, the detector requires the GDDR6-ONLY
    structural tokens and DEFERS when the doc is DDR/LPDDR5/HBM3-primary. Reads
    ONLY the spec text `blob` — never a filename or benchmark name.
    """
    if not blob:
        return False
    low = blob.lower()

    # --- GDDR6-specific structural tokens. ---
    jesd250 = "jesd250" in low
    name_token = "gddr6" in low
    # Graphics-SGRAM identity must be a TIGHT adjacent phrase — NOT a loose
    # co-occurrence of "graphics" and "sdram" anywhere in the blob, which a
    # mainstream DDR4/DDR5 spec trips when it mentions "graphics" in passing.
    graphics_sgram = (
        "graphics sgram" in low
        or "graphics ddr" in low
        or "graphics double data rate" in low
        or "graphics dram" in low
        or ("graphics memory" in low and ("gddr" in low or "sgram" in low)))
    wck = ("wck" in low or "write clock" in low)
    wck2ck = ("wck2ck" in low or "wck-to-ck" in low
              or "wck to ck" in low)
    # EDC read+write CRC error-detection pins — GDDR6-only (absent in
    # DDR3/4/5, LPDDR5, HBM3). Require the EDC pin AND the per-lane CRC scheme.
    edc_pin = ("edc" in low and ("pin" in low or "hold pattern" in low
                                 or "error detection" in low))
    read_write_crc = (
        ("read crc" in low and "write crc" in low)
        or ("crc" in low and "edc" in low and "byte lane" in low)
        or ("crc" in low and "edc" in low and "per byte" in low))
    cabi = ("cabi" in low
            or "command/address bus inversion" in low
            or "command address bus inversion" in low)
    # Two independent 16-bit channels — the defining GDDR6 organization.
    two_channel = (
        ("two independent" in low and "channel" in low)
        or ("two independent channels" in low)
        or ("two channels" in low and "16-bit" in low)
        or ("channel a" in low and "channel b" in low and "16-bit" in low))
    prefetch16 = ("16n prefetch" in low or "prefetch 16n" in low
                  or "prefetch of 16n" in low)
    bl16 = ("bl16" in low or "burst length 16" in low
            or "burst length of bl16" in low)

    # --- Sibling-primary MUTEX (defer paths). ---
    # DDR3/4/5-primary: JESD79-x / DIMM mainstream DRAM, no WCK, no EDC-graphics.
    ddr_mainstream_primary = (
        ("jesd79" in low or "dimm" in low or "rdimm" in low
         or "lrdimm" in low)
        and not (jesd250 or name_token or graphics_sgram or wck or cabi
                 or (edc_pin and read_write_crc)))
    if ddr_mainstream_primary:
        return False

    # LPDDR5-primary: JESD209-5 / low-power mobile DRAM. Shares WCK, so WCK is
    # NOT a discriminator here — defer only when the GDDR6-only tokens are all
    # absent (no JESD250, no GDDR6 name, no graphics SGRAM, no EDC read+write
    # CRC, no CABI).
    lpddr5_primary = (
        ("lpddr5" in low or "jesd209-5" in low or "jesd209" in low
         or ("low-power" in low and "mobile" in low))
        and not (jesd250 or name_token or graphics_sgram or cabi
                 or (edc_pin and read_write_crc)))
    if lpddr5_primary:
        return False

    # HBM3-primary: JESD238 / 1024-bit TSV-stacked DRAM on an interposer.
    hbm3_primary = (
        ("hbm3" in low or "jesd238" in low or "high bandwidth memory" in low
         or "1024-bit" in low or "1024 bit" in low or "tsv" in low
         or "interposer" in low)
        and not (jesd250 or name_token or graphics_sgram or cabi or wck2ck
                 or (edc_pin and read_write_crc)))
    if hbm3_primary:
        return False

    # --- Positive GDDR6 structural signature. ---
    # A graphics-DRAM identity (JESD250 OR GDDR6 name OR graphics SGRAM) PLUS at
    # least two GDDR6-distinguishing structural features. WCK is necessary but
    # not sufficient (LPDDR5 shares it), so it counts as ONE feature and we
    # require an additional GDDR6-only structural feature (EDC read/write CRC,
    # CABI, two-independent-16-bit-channel, WCK2CK, or 16n/BL16).
    identity = jesd250 or name_token or graphics_sgram
    gddr6_only_features = sum(bool(x) for x in (
        (edc_pin and read_write_crc),
        cabi,
        two_channel,
        wck2ck,
    ))
    structural = (
        identity
        and wck
        and (gddr6_only_features >= 1)
        and (gddr6_only_features + (1 if (prefetch16 or bl16) else 0)
             + (1 if two_channel else 0) >= 2))

    # A very strong identity + EDC read/write CRC alone is also conclusive
    # (the EDC read+write CRC pin scheme is unique to GDDR6 in this family).
    conclusive = identity and edc_pin and read_write_crc and (cabi or wck)

    return bool(structural or conclusive)


# ----------------------------------------------------------------------
# Public entry.
# ----------------------------------------------------------------------
def apply_gddr6_synth(generated_docs_dir: Path, is_gddr6_flag: bool,
                      gddr6_ic_name: Optional[str]) -> None:
    """Apply JEDEC JESD250 GDDR6 synth when the GDDR6 signature matched."""
    if not is_gddr6_flag:
        return
    gd = Path(generated_docs_dir)

    # --- Force ic_name across ALL 24 docs FIRST (main + fields docs). ---
    if gddr6_ic_name is not None:
        for n in _MAIN_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                d["ic_name"] = gddr6_ic_name
                _write(q, d)
        for n in _FIELDS_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                f = _ensure_dict(d, "fields")
                f["ic_name"] = gddr6_ic_name
                d["ic_name"] = gddr6_ic_name
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
# L1 — GDDR6 datasheet header + headline facts.
# ----------------------------------------------------------------------
def _l1(gd: Path) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    d["document_title"] = "GDDR6 SGRAM (Graphics DDR6) Standard"
    d["version"] = "JEDEC JESD250 (GDDR6 SGRAM)"
    d["revised_date"] = "JESD250 (Graphics DDR6 SGRAM)"
    d["manufacturer"] = "JEDEC Solid State Technology Association"
    d["copyright"] = "© JEDEC"
    d["abstract"] = (
        "Graphics Double Data Rate type 6 SGRAM (GDDR6) is a high-bandwidth, "
        "point-to-point graphics memory device standardized by JEDEC in JESD250. "
        "A GDDR6 device is organized as TWO INDEPENDENT 16-bit (x16) channels, "
        "each with its own command clock (CK), Write Clock (WCK), command/address "
        "(CA) bus, data (DQ) bus, and Error-Detection (EDC) pins. GDDR6 clocks "
        "commands on a quarter-rate CK and clocks data on a separate higher-rate "
        "WCK (WCK = 2x CK data rate) that is phase-aligned to CK via WCK2CK "
        "training. It uses a 16n prefetch with a fixed burst length of BL16 and "
        "NRZ signaling at 16-18 Gb/s per pin. Data integrity is provided by an "
        "8-bit read CRC and write CRC per byte lane carried on the EDC pins, with "
        "a programmable EDC hold pattern. Data Bus Inversion (DBI) and "
        "Command/Address Bus Inversion (CABI) limit simultaneous switching. The "
        "memory array is organized into bank groups (tCCD_S / tCCD_L) and "
        "configured by mode registers MR0..MR15. GDDR6 is point-to-point "
        "(on-package / on-board next to a GPU or accelerator), NOT a DIMM module. "
        "Note: this JESD250 standard is NRZ; the Micron GDDR6X PAM4 variant is "
        "out of scope.")
    d["keywords"] = [
        "GDDR6", "Graphics DDR6", "SGRAM", "JESD250", "graphics memory",
        "two independent channels", "x16", "pseudo-channel", "WCK",
        "Write Clock", "WCK2CK", "CK", "quarter-rate", "16n prefetch", "BL16",
        "NRZ", "DBI", "Data Bus Inversion", "CABI",
        "Command/Address Bus Inversion", "EDC", "read CRC", "write CRC",
        "EDC hold pattern", "bank group", "tCCD_S", "tCCD_L", "CA training",
        "CAT", "Vref training", "mode register", "MR0", "POD135", "1.35 V",
        "16 Gb/s", "18 Gb/s", "GPU", "accelerator",
    ]
    d["external_pins"] = [
        "CK_t / CK_c (per channel): differential quarter-rate command clock",
        "WCK_t / WCK_c (per byte / per channel): differential Write Clock "
        "running at 2x the CK data rate; WCK2CK-aligned to CK",
        "CA[9:0] (per channel): double-data-rate command/address bus captured "
        "on CK",
        "CABI_n (per channel): Command/Address Bus Inversion strobe (active low)",
        "DQ[15:0] (per channel): bidirectional data bus, DDR on WCK",
        "DBI_n[1:0] (per channel): Data Bus Inversion, one per byte lane "
        "(active low)",
        "EDC[1:0] (per channel): Error-Detection pins, one per byte lane — "
        "carry the read/write CRC and the EDC hold pattern",
        "RESET_n: asynchronous device reset (active low), common to the device",
        "VDD / VDDQ (1.35 V) / VPP (1.8 V) / VSS supply rails; VREFC / VREFD "
        "internally generated and trained",
    ]
    d["channels_per_device"] = _CHANNELS_PER_DEVICE
    d["channel_width_bits"] = _CHANNEL_WIDTH_BITS
    d["prefetch"] = _PREFETCH
    d["burst_length"] = _BURST_LENGTH
    d["per_pin_data_rate_Gbps"] = list(_PER_PIN_RATE_GBPS)
    d["signaling"] = _SIGNALING
    d["crc_bits_per_byte_lane"] = _CRC_BITS
    d["num_mode_registers"] = _NUM_MODE_REGISTERS
    d["modes_of_operation"] = [
        {"name": "Channel mode (x16)",
         "role": "two independent 16-bit channels",
         "note": "Channel A and Channel B each operate as a full independent "
                 "x16 memory with their own CK / WCK / CA / DQ / EDC."},
        {"name": "Pseudo-channel mode",
         "role": "two 8-bit pseudo-channels per channel",
         "note": "Each 16-bit channel splits into PC0 (DQ[7:0]) and PC1 "
                 "(DQ[15:8]) that share the CA bus and row commands but issue "
                 "independent column (READ/WRITE) commands."},
    ]
    d["key_features"] = [
        "JEDEC JESD250 graphics SGRAM for GPUs / AI accelerators / switches.",
        "Two independent 16-bit channels per device; optional pseudo-channel "
        "mode (two 8-bit pseudo-channels per channel).",
        "Quarter-rate command clock CK plus a separate higher-rate Write Clock "
        "WCK (WCK = 2x CK data rate); WCK2CK alignment/training.",
        "16n prefetch, fixed burst length BL16; NRZ signaling at 16-18 Gb/s "
        "per pin.",
        "Data Bus Inversion (DBI, dc/ac) per byte lane and Command/Address Bus "
        "Inversion (CABI) to limit simultaneous switching.",
        "8-bit read CRC and write CRC per byte lane on the EDC pins for "
        "end-to-end data-integrity error detection, plus a programmable EDC "
        "hold pattern.",
        "Bank-group array (tCCD_S short / tCCD_L long) to sustain back-to-back "
        "column accesses at full rate.",
        "Training flows: CA training (CAT), WCK2CK, read/write training, Vref "
        "training (VREFD / VREFC).",
        "Mode registers MR0..MR15; POD135 I/O at 1.35 V (VDD / VDDQ), VPP 1.8 V.",
        "Point-to-point on-package / on-board (single rank) — not a DIMM.",
    ]
    d["topology_summary"] = (
        "Point-to-point: each GDDR6 device is placed next to the GPU / "
        "accelerator and presents two independent x16 channels. Aggregate "
        "memory bandwidth is scaled by placing many GDDR6 devices around the "
        "host. There is no DIMM, no module, no multi-rank shared bus.")
    d["package_summary"] = (
        "GDDR6 is a discrete point-to-point graphics DRAM mounted on-board (or "
        "on-package) adjacent to the host. Unlike HBM3 it is not a TSV-stacked "
        "on-interposer device, and unlike DDR/LPDDR DIMMs it is not a module.")
    d["use_cases"] = [
        "GPU graphics / frame-buffer memory",
        "AI / ML training and inference accelerator memory",
        "High-end networking switch packet buffers",
        "Automotive ADAS and high-bandwidth compute",
    ]
    d["revision_history"] = [
        {"version": "JESD250", "date": "Graphics DDR6 SGRAM",
         "description": "GDDR6 SGRAM standard: two independent x16 channels, "
                        "WCK + WCK2CK, 16n prefetch / BL16, NRZ 16-18 Gb/s, DBI "
                        "+ CABI, read/write CRC on EDC pins, bank groups, "
                        "MR0..MR15."},
    ]
    d["overview"] = (
        "GDDR6 (JESD250) is a graphics SGRAM that maximizes per-pin bandwidth "
        "for GPUs and accelerators. Each device exposes two fully independent "
        "16-bit channels; in pseudo-channel mode each channel further splits "
        "into two 8-bit pseudo-channels sharing the CA bus. Commands ride a "
        "quarter-rate CK while data rides a separate, faster WCK that is "
        "WCK2CK-aligned. A 16n prefetch delivers BL16 bursts in NRZ at 16-18 "
        "Gb/s per pin. DBI and CABI reduce switching noise; an 8-bit read and "
        "write CRC per byte lane on the EDC pins (with a programmable hold "
        "pattern) detects transfer errors. The array is organized into bank "
        "groups for back-to-back access, and mode registers MR0..MR15 configure "
        "latency, CRC, DBI, CABI, training, and power states.")
    _write(p, d)


# ----------------------------------------------------------------------
# L2 — Functional Requirements Spec.
# ----------------------------------------------------------------------
def _l2(gd: Path) -> None:
    p = gd / "L2_FRS.json"
    if not p.is_file():
        return
    d = _read(p)
    po = _ensure_dict(d, "protocol_overview")
    po["type"] = (
        "Point-to-point graphics DRAM (SGRAM), JEDEC JESD250. Two independent "
        "16-bit channels per device, quarter-rate CK + higher-rate WCK, 16n "
        "prefetch / BL16, NRZ 16-18 Gb/s per pin.")
    po["duplex"] = (
        "Half-duplex bidirectional DQ bus (reads and writes share DQ, "
        "direction-turnaround governed by read/write latency); CK and CA are "
        "host-to-device; EDC carries device-to-host read CRC and host-to-device "
        "write CRC.")
    po["synchronous_serial"] = False
    po["source_synchronous"] = True
    po["forwarded_clock"] = True
    po["embedded_clock"] = False
    po["encoding"] = (
        "Unencoded NRZ (two-level) on DQ and CA. Data integrity is provided by "
        "an 8-bit CRC per byte lane (read CRC + write CRC) on the EDC pins, not "
        "by a DC-balancing line code. DBI (dc/ac) and CABI limit driven-low "
        "lines / transitions.")
    po["modulation"] = "NRZ (two-level). GDDR6X PAM4 is out of scope of JESD250."
    po["per_pin_data_rate_Gbps"] = list(_PER_PIN_RATE_GBPS)
    po["channels_per_device"] = _CHANNELS_PER_DEVICE
    po["channel_width_bits"] = _CHANNEL_WIDTH_BITS
    po["prefetch"] = _PREFETCH
    po["burst_length"] = _BURST_LENGTH
    d["functional_requirements"] = [
        {"id": "FR-CH", "text": "The device shall present two independent 16-bit "
         "channels, each with its own CK, WCK, CA, DQ, DBI, and EDC; the "
         "channels share only RESET_n and the supplies."},
        {"id": "FR-PC", "text": "In pseudo-channel mode each 16-bit channel "
         "shall split into two 8-bit pseudo-channels that share the CA bus and "
         "row commands but issue independent column commands."},
        {"id": "FR-WCK", "text": "Data shall be captured/launched on the Write "
         "Clock WCK (2x the CK data rate); WCK shall be phase-aligned to CK via "
         "WCK2CK training before data transfers."},
        {"id": "FR-PF", "text": "The device shall use a 16n prefetch with a "
         "fixed burst length BL16."},
        {"id": "FR-CRC", "text": "The device shall compute an 8-bit CRC per byte "
         "lane over each BL16 burst: a read CRC driven on EDC during reads and a "
         "write CRC checked from EDC during writes; a write-CRC mismatch shall "
         "be flagged so the controller can replay."},
        {"id": "FR-EDC", "text": "Between CRC transfers each EDC pin shall drive "
         "a programmable EDC hold pattern to keep the controller's CDR/DLL "
         "locked on the EDC lane."},
        {"id": "FR-DBI", "text": "DBI (dc or ac, per MR) shall be supported per "
         "byte lane on DQ; CABI shall be supported on the CA bus."},
        {"id": "FR-BG", "text": "The array shall be organized into bank groups; "
         "back-to-back column accesses to different bank groups use tCCD_S, same "
         "bank group uses tCCD_L."},
        {"id": "FR-TRAIN", "text": "The device shall support CA training (CAT), "
         "WCK2CK training, read/write training, and Vref training (VREFD / "
         "VREFC)."},
        {"id": "FR-MR", "text": "Mode registers MR0..MR15 shall configure CL/WL, "
         "CRC, DBI, CABI, EDC hold pattern, bank-group organization, training, "
         "and power states."},
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L3 — Command / protocol.
# ----------------------------------------------------------------------
def _l3(gd: Path) -> None:
    p = gd / "L3_CMD_PROTOCOL.json"
    if not p.is_file():
        return
    d = _read(p)
    d["command_bus"] = (
        "CA[9:0] double-data-rate command/address bus per channel; each command "
        "is presented over two CK edges and captured on CK_t/CK_c. CABI_n may "
        "invert the CA word to cap driven-low lines.")
    d["commands"] = [
        {"name": "ACTIVATE", "mnemonic": "ACT",
         "desc": "Open a row in a bank (row address on CA)."},
        {"name": "PRECHARGE", "mnemonic": "PRE",
         "desc": "Close a row in a bank / all banks."},
        {"name": "READ", "mnemonic": "RD",
         "desc": "Column read, BL16; data returned on DQ clocked by WCK; read "
                 "CRC on EDC."},
        {"name": "WRITE", "mnemonic": "WR",
         "desc": "Column write, BL16; data on DQ clocked by WCK; write CRC "
                 "checked on EDC."},
        {"name": "REFRESH", "mnemonic": "REF",
         "desc": "All-bank or per-bank refresh (tRFC / tREFI)."},
        {"name": "MODE REGISTER SET", "mnemonic": "MRS",
         "desc": "Load a value into a mode register MR0..MR15."},
        {"name": "SELF REFRESH ENTRY/EXIT", "mnemonic": "SRE/SRX",
         "desc": "Enter/exit self refresh (and hibernate self refresh)."},
        {"name": "POWER DOWN ENTRY/EXIT", "mnemonic": "PDE/PDX",
         "desc": "CKE-controlled clock-gated power-down."},
        {"name": "WCK2CK SYNC", "mnemonic": "WCK2CK",
         "desc": "Initiate WCK-to-CK phase alignment/training."},
        {"name": "NOP / DESELECT", "mnemonic": "NOP",
         "desc": "No operation / device deselect."},
    ]
    d["addressing"] = (
        "Row/column addressing within bank groups and banks (e.g. 4 bank groups "
        "x 4 banks = 16 banks per channel, density dependent). Column accesses "
        "move BL16 per DQ.")
    _write(p, d)


# ----------------------------------------------------------------------
# L4 — Register / mode-register map.
# ----------------------------------------------------------------------
def _l4(gd: Path) -> None:
    p = gd / "L4_REGMAP.json"
    if not p.is_file():
        return
    d = _read(p)
    d["register_model"] = (
        "GDDR6 is configured via mode registers MR0..MR15 (16 mode registers), "
        "loaded with the MODE REGISTER SET (MRS) command.")
    d["mode_registers"] = [
        {"name": "MR0", "function": "CAS latency (CL), WCK ratio"},
        {"name": "MR1", "function": "Write latency (WL), drive strength, "
                                     "termination"},
        {"name": "MR2", "function": "CABI enable, CRC (read/write) enable, DBI "
                                     "mode (dc/ac), EDC hold-pattern enable"},
        {"name": "MR3", "function": "Bank-group / DRAM organization, data/write "
                                     "mask"},
        {"name": "MR4", "function": "EDC hold-pattern value, CRC write-latency "
                                     "adder, refresh management"},
        {"name": "MR5", "function": "Per-DRAM addressability, RDQS, PLL/DLL"},
        {"name": "MR6", "function": "VREFD (DQ reference) training value"},
        {"name": "MR7", "function": "Low-frequency mode, WCK termination, "
                                     "hibernate self refresh, PLL bypass"},
        {"name": "MR8", "function": "Reference-voltage range, VREFC (CA "
                                     "reference) control"},
        {"name": "MR9", "function": "Read/write training pattern"},
        {"name": "MR10", "function": "WCK2CK / WCK termination training control"},
        {"name": "MR11", "function": "Channel / pseudo-channel mode control"},
        {"name": "MR12", "function": "Vendor / training (reserved)"},
        {"name": "MR13", "function": "Vref-fine / training (reserved)"},
        {"name": "MR14", "function": "Vendor (reserved)"},
        {"name": "MR15", "function": "Vendor (reserved)"},
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L5 — Analog / device interface spec (DC/AC operating conditions).
# ----------------------------------------------------------------------
def _l5(gd: Path) -> None:
    p = gd / "L5_ADI_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["electrical_spec"] = {
        "signaling": "NRZ (two-level), POD135 (Pseudo-Open-Drain) referenced to "
                     "VDDQ with on-die termination",
        "VDD_V": _VDD_V,
        "VDDQ_V": _VDDQ_V,
        "VPP_V": _VPP_V,
        "per_pin_data_rate_Gbps": list(_PER_PIN_RATE_GBPS),
        "reference_voltages": "VREFD (DQ) and VREFC (CA), internally generated "
                              "and trained via Vref training",
        "termination": "On-die termination (ODT); WCK termination controlled by "
                       "mode registers",
    }
    d["clocking"] = {
        "CK": "Differential quarter-rate command clock (CK_t/CK_c) per channel",
        "WCK": "Differential Write Clock (WCK_t/WCK_c) at 2x the CK data rate, "
               "one pair per byte group",
        "WCK2CK": "WCK phase aligned to CK per channel via WCK2CK training",
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L6 — Control logic / FSM.
# ----------------------------------------------------------------------
def _l6(gd: Path) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["state_machine"] = {
        "states": [
            "RESET", "INIT", "MR_PROGRAM", "CA_TRAINING", "WCK2CK_TRAINING",
            "READ_WRITE_TRAINING", "VREF_TRAINING", "IDLE", "ACTIVE",
            "READING", "WRITING", "PRECHARGING", "REFRESH",
            "SELF_REFRESH", "POWER_DOWN", "HIBERNATE_SELF_REFRESH",
        ],
        "notes": "After RESET_n release the device programs MR0..MR15, then runs "
                 "CA training (CAT), WCK2CK alignment, read/write training, and "
                 "Vref training before entering normal ACTIVE/READ/WRITE "
                 "operation. Low-power states are entered via SELF REFRESH / "
                 "POWER DOWN commands.",
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L7 — Test / debug.
# ----------------------------------------------------------------------
def _l7(gd: Path) -> None:
    p = gd / "L7_TEST_DEBUG.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_debug_features"] = [
        "CA training (CAT): device captures a known CA pattern and reports it "
        "on DQ/EDC so the controller can center the CA eye.",
        "WCK2CK training: aligns the WCK domain to the CK domain.",
        "Read training / write training: center the read/write data eye with a "
        "programmable training pattern (MR9).",
        "Vref training: trains VREFD (DQ) and VREFC (CA) receiver references.",
        "CRC error reporting: read-CRC mismatch detected by the controller; "
        "write-CRC mismatch flagged by the device (error status / alert).",
        "EDC hold pattern (MR4) keeps EDC-lane CDR/DLL locked during idle.",
        "Boundary / loopback and vendor test modes via reserved mode registers.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L8 — RTL constants.
# ----------------------------------------------------------------------
def _l8_rtl(gd: Path) -> None:
    p = gd / "L8_RTL_CONSTANTS.json"
    if not p.is_file():
        return
    d = _read(p)
    consts = _ensure_dict(d, "constants")
    consts.update({
        "CHANNELS_PER_DEVICE": _CHANNELS_PER_DEVICE,
        "CHANNEL_WIDTH_BITS": _CHANNEL_WIDTH_BITS,
        "PSEUDO_CHANNEL_WIDTH_BITS": 8,
        "PREFETCH": _PREFETCH,
        "BURST_LENGTH": _BURST_LENGTH,
        "CRC_BITS_PER_BYTE_LANE": _CRC_BITS,
        "CA_BUS_WIDTH": 10,
        "DQ_WIDTH_PER_CHANNEL": 16,
        "DBI_PINS_PER_CHANNEL": 2,
        "EDC_PINS_PER_CHANNEL": 2,
        "NUM_MODE_REGISTERS": _NUM_MODE_REGISTERS,
        "WCK_TO_CK_DATA_RATE_MULTIPLIER": 2,
        "PER_PIN_DATA_RATE_GBPS_MIN": _PER_PIN_RATE_GBPS[0],
        "PER_PIN_DATA_RATE_GBPS_MAX": _PER_PIN_RATE_GBPS[1],
        "VDD_V": _VDD_V,
        "VDDQ_V": _VDDQ_V,
        "VPP_V": _VPP_V,
        "SIGNALING": _SIGNALING,
    })
    _write(p, d)


# ----------------------------------------------------------------------
# L8 — Timing / waveform.
# ----------------------------------------------------------------------
def _l8_timing(gd: Path) -> None:
    p = gd / "L8_TIMING_WAVEFORM.json"
    if not p.is_file():
        return
    d = _read(p)
    d["timing_parameters"] = [
        {"name": "tRCD", "desc": "ACTIVATE-to-READ/WRITE delay"},
        {"name": "tRP", "desc": "PRECHARGE period"},
        {"name": "tRAS", "desc": "Row active time"},
        {"name": "tRC", "desc": "Row cycle time (tRAS + tRP)"},
        {"name": "tCCD_S", "desc": "CAS-to-CAS delay, short (different bank "
                                   "group)"},
        {"name": "tCCD_L", "desc": "CAS-to-CAS delay, long (same bank group)"},
        {"name": "tWTR", "desc": "Write-to-read turnaround"},
        {"name": "tFAW", "desc": "Four-activate window"},
        {"name": "tRFC", "desc": "Refresh cycle time"},
        {"name": "tREFI", "desc": "Average refresh interval"},
        {"name": "CL", "desc": "CAS (read) latency"},
        {"name": "WL", "desc": "Write latency"},
        {"name": "WCK2CK", "desc": "WCK-to-CK alignment training interval"},
    ]
    d["clock_domains"] = [
        "CK_t/CK_c — quarter-rate command clock (per channel)",
        "WCK_t/WCK_c — Write Clock at 2x CK data rate (per byte group)",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L9 — Integration / pin spec.
# ----------------------------------------------------------------------
def _l9(gd: Path) -> None:
    p = gd / "L9_INTEGRATION_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["integration"] = (
        "GDDR6 integrates as a point-to-point graphics DRAM placed next to the "
        "GPU/accelerator. Each device exposes two independent x16 channels. The "
        "memory controller drives CK + CA per channel, exchanges data on DQ "
        "clocked by WCK (after WCK2CK alignment), and uses the EDC pins for "
        "read/write CRC. There is no DIMM, no module, and a single rank.")
    d["pin_groups"] = {
        "clock": ["CK_t", "CK_c", "WCK_t", "WCK_c"],
        "command_address": ["CA[9:0]", "CABI_n"],
        "data": ["DQ[15:0]", "DBI_n[1:0]", "EDC[1:0]"],
        "control": ["RESET_n", "CKE"],
        "power": ["VDD", "VDDQ", "VPP", "VSS"],
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L10 — Test cases.
# ----------------------------------------------------------------------
def _l10(gd: Path) -> None:
    p = gd / "L10_TEST_CASES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_cases"] = [
        {"id": "TC-INIT", "name": "Power-up + reset + MR program",
         "desc": "Power rails up, RESET_n release, program MR0..MR15 on both "
                 "channels."},
        {"id": "TC-CAT", "name": "CA training",
         "desc": "Run CA training and verify CA eye centering on each channel."},
        {"id": "TC-WCK2CK", "name": "WCK2CK alignment",
         "desc": "Run WCK2CK training and verify WCK is phase-aligned to CK."},
        {"id": "TC-RW", "name": "Read/write BL16",
         "desc": "Activate, write BL16, read back BL16, compare; verify read "
                 "CRC on EDC."},
        {"id": "TC-WCRC", "name": "Write-CRC error injection",
         "desc": "Inject a bad write CRC on EDC; verify the device flags the "
                 "write-CRC error for replay."},
        {"id": "TC-DBI", "name": "DBI dc/ac",
         "desc": "Exercise DBIdc and DBIac and verify driven-low / transition "
                 "minimization."},
        {"id": "TC-CABI", "name": "CABI",
         "desc": "Exercise CABI on the CA bus."},
        {"id": "TC-BG", "name": "Bank-group tCCD_S / tCCD_L",
         "desc": "Back-to-back column access to different vs same bank group; "
                 "verify tCCD timing."},
        {"id": "TC-LP", "name": "Self refresh / power down",
         "desc": "Enter/exit self refresh, hibernate self refresh, power down."},
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L11 — OTP content (genuine N/A for a JEDEC DRAM device).
# ----------------------------------------------------------------------
def _l11(gd: Path) -> None:
    p = gd / "L11_OTP_CONTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    d["otp_present"] = False
    d["otp_content"] = "N/A"
    d["notes"] = (
        "GDDR6 (JESD250) defines no one-time-programmable fuse array in the "
        "device interface; vendor-specific repair fuses are out of scope of the "
        "JEDEC standard.")
    _write(p, d)


# ----------------------------------------------------------------------
# L12 — Behavioral sequences.
# ----------------------------------------------------------------------
def _l12(gd: Path) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["sequences"] = [
        {"name": "Initialization",
         "steps": ["Apply VDD/VDDQ/VPP in order, hold RESET_n low",
                   "Release RESET_n, wait reset-to-CKE time",
                   "Start CK, program MR0..MR15 (both channels)",
                   "CA training (CAT)",
                   "Start WCK, WCK2CK alignment training",
                   "Read training and write training",
                   "Vref training (VREFD, VREFC)",
                   "Enable CRC/DBI/CABI; device ready"]},
        {"name": "Read transaction",
         "steps": ["ACTIVATE row", "READ (column, BL16)",
                   "Data on DQ clocked by WCK; read CRC on EDC",
                   "Controller checks read CRC", "PRECHARGE"]},
        {"name": "Write transaction",
         "steps": ["ACTIVATE row", "WRITE (column, BL16)",
                   "Data on DQ clocked by WCK; write CRC on EDC",
                   "Device checks write CRC; flag on mismatch (replay)",
                   "PRECHARGE"]},
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L13 — Lab calibration.
# ----------------------------------------------------------------------
def _l13(gd: Path) -> None:
    p = gd / "L13_LAB_CALIBRATION.json"
    if not p.is_file():
        return
    d = _read(p)
    d["calibration"] = [
        "WCK2CK alignment training (per channel, re-run on rate change / drift).",
        "CA training (CAT) to center the command/address eye.",
        "Read/write training (DQ/DBI deskew) to center the data eye.",
        "Vref training of VREFD (DQ) and VREFC (CA) for receiver margin.",
        "ODT / drive-strength calibration via mode registers.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L14 — Protocol versioning.
# ----------------------------------------------------------------------
def _l14(gd: Path) -> None:
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["standard"] = "JEDEC JESD250 (GDDR6 SGRAM)"
    f["generation"] = "GDDR6 (graphics DDR, generation 6)"
    f["predecessors"] = ["GDDR5", "GDDR5X"]
    f["successors"] = ["GDDR6X (Micron PAM4, non-JEDEC)", "GDDR7"]
    f["signaling"] = "NRZ (GDDR6X PAM4 is out of scope of JESD250)"
    _write(p, d)


# ----------------------------------------------------------------------
# L15 — Encoding tables.
# ----------------------------------------------------------------------
def _l15(gd: Path) -> None:
    p = gd / "L15_ENCODING_TABLES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["line_code"] = "Unencoded NRZ (no 8b/10b or scrambling line code)"
    f["dbi"] = {
        "modes": ["DBIdc (DC, minimum-driven-low: invert byte if >4 of 8 bits "
                  "driven low)",
                  "DBIac (AC, transition-minimization: invert byte to reduce "
                  "transitions vs previous byte)"],
        "pins": "DBI_n[1:0] (one per byte lane, active low)",
    }
    f["cabi"] = {
        "desc": "Command/Address Bus Inversion: invert the CA word when too many "
                "CA bits would be driven low",
        "pin": "CABI_n (active low)",
    }
    f["crc"] = {
        "width_bits": _CRC_BITS,
        "scope": "per byte lane over a BL16 burst",
        "directions": ["read CRC (device -> controller, on EDC)",
                       "write CRC (controller -> device, on EDC)"],
        "carrier": "EDC pins; programmable EDC hold pattern between transfers",
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L16 — Compliance properties.
# ----------------------------------------------------------------------
def _l16(gd: Path) -> None:
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["properties"] = [
        "Each channel operates independently with its own CK/WCK/CA/DQ/EDC.",
        "WCK is WCK2CK-aligned before any data transfer.",
        "Every BL16 burst carries an 8-bit CRC per byte lane on EDC (when CRC "
        "enabled).",
        "A write-CRC mismatch is reported by the device so the controller can "
        "replay the write.",
        "DBI/CABI obey the configured dc/ac mode.",
        "Column accesses honor tCCD_S (different bank group) and tCCD_L (same "
        "bank group).",
        "Mode-register writes (MRS) take effect within the specified latency.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L17 — Channel / signal catalog (force-overwrite per the doctrine).
# ----------------------------------------------------------------------
def _l17(gd: Path) -> None:
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["signals"] = [
        {"name": "CK_t / CK_c", "dir": "input", "class": "clock",
         "desc": "Differential quarter-rate command clock (per channel)"},
        {"name": "WCK_t / WCK_c", "dir": "input", "class": "clock",
         "desc": "Differential Write Clock at 2x CK data rate (per byte group), "
                 "WCK2CK-aligned"},
        {"name": "CA[9:0]", "dir": "input", "class": "command_address",
         "desc": "DDR command/address bus captured on CK"},
        {"name": "CABI_n", "dir": "input", "class": "command_address",
         "desc": "Command/Address Bus Inversion strobe (active low)"},
        {"name": "DQ[15:0]", "dir": "bidir", "class": "data",
         "desc": "16-bit data bus per channel, DDR on WCK"},
        {"name": "DBI_n[1:0]", "dir": "bidir", "class": "data",
         "desc": "Data Bus Inversion, one per byte lane (active low)"},
        {"name": "EDC[1:0]", "dir": "bidir", "class": "error_detection",
         "desc": "Error-Detection pins (per byte lane): read/write CRC + EDC "
                 "hold pattern"},
        {"name": "RESET_n", "dir": "input", "class": "control",
         "desc": "Asynchronous device reset (active low)"},
        {"name": "VDD/VDDQ/VPP/VSS", "dir": "power", "class": "power",
         "desc": "1.35 V core/IO, 1.8 V pump, ground"},
    ]
    f["channels"] = [
        {"name": "Channel A", "width_bits": 16, "independent": True},
        {"name": "Channel B", "width_bits": 16, "independent": True},
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L18 — Interconnect topology.
# ----------------------------------------------------------------------
def _l18(gd: Path) -> None:
    p = gd / "L18_INTERCONNECT_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["topology"] = "point-to-point (single rank, on-package / on-board)"
    f["per_device"] = "two independent 16-bit channels (Channel A, Channel B)"
    f["scaling"] = ("aggregate bandwidth scaled by placing many GDDR6 devices "
                    "around the GPU/accelerator; no DIMM / module / multi-rank "
                    "shared bus")
    f["not_like"] = {
        "DDR/LPDDR DIMM": "GDDR6 is not a module memory",
        "HBM3": "GDDR6 is not TSV-stacked on an interposer",
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L19 — Constraints / PDK.
# ----------------------------------------------------------------------
def _l19(gd: Path) -> None:
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["io_standard"] = "POD135 (Pseudo-Open-Drain), VDDQ-referenced, ODT"
    f["per_pin_rate_Gbps"] = list(_PER_PIN_RATE_GBPS)
    f["signaling"] = _SIGNALING
    f["voltages"] = {"VDD": _VDD_V, "VDDQ": _VDDQ_V, "VPP": _VPP_V}
    f["notes"] = ("Per-byte WCK strobe and tight DQ/WCK skew budget; trained "
                  "Vref (VREFD/VREFC); on-die termination configured by mode "
                  "registers.")
    _write(p, d)


# ----------------------------------------------------------------------
# L20 — DFT / scan topology.
# ----------------------------------------------------------------------
def _l20(gd: Path) -> None:
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["dft"] = [
        "Training modes (CAT / WCK2CK / read-write / Vref) double as structural "
        "interface tests.",
        "CRC-on-EDC provides an in-system data-integrity self-check.",
        "Vendor test / loopback modes via reserved mode registers.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L21 — Power intent.
# ----------------------------------------------------------------------
def _l21(gd: Path) -> None:
    p = gd / "L21_POWER_INTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["supplies"] = {"VDD": _VDD_V, "VDDQ": _VDDQ_V, "VPP": _VPP_V}
    f["low_power_states"] = [
        "Self Refresh", "Hibernate Self Refresh", "Power Down",
        "Low-frequency mode (MR7)",
    ]
    f["techniques"] = [
        "Quarter-rate CK to lower command-bus power",
        "DBI / CABI to cap driven-low lines",
        "WCK termination control via mode registers",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L22 — Verification plan.
# ----------------------------------------------------------------------
def _l22(gd: Path) -> None:
    p = gd / "L22_VERIFICATION_PLAN.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["verification_items"] = [
        "Two-independent-channel isolation",
        "Pseudo-channel independent column access",
        "WCK2CK alignment correctness across rates",
        "16n prefetch / BL16 burst integrity",
        "Read-CRC and write-CRC generation/checking on EDC",
        "EDC hold pattern continuity",
        "DBI dc/ac and CABI behavior",
        "Bank-group tCCD_S/tCCD_L timing",
        "Training flows (CAT / read-write / Vref)",
        "Self refresh / hibernate / power-down entry-exit",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L23 — Security requirements (genuine minimal for a DRAM device).
# ----------------------------------------------------------------------
def _l23(gd: Path) -> None:
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["security_model"] = (
        "GDDR6 (JESD250) is a memory device; the JEDEC standard defines no "
        "cryptographic access control. Data-integrity (not confidentiality) is "
        "addressed by the read/write CRC on the EDC pins. Anti-rowhammer / "
        "refresh-management mitigations are configured via mode registers; "
        "memory-encryption is a host/controller concern, out of scope of "
        "JESD250.")
    _write(p, d)
