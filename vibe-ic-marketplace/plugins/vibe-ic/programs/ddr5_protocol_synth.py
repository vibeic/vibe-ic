"""DDR5 SDRAM protocol synth helper (JEDEC JESD79-5).

ic_class-gated overlay for the DDR5 structural signature: the fifth-generation
mainstream double-data-rate synchronous DRAM standardized by JEDEC as JESD79-5.
The DDR5-defining structural signature is the combination of: two INDEPENDENT
32-bit (40-bit with ECC) sub-channels per DIMM (vs DDR4's single 64/72-bit bus),
Decision Feedback Equalization (DFE) on the DQ receivers, On-Die ECC (ODECC) in
every device, same-bank refresh (REFsb), 32 banks in 8 bank groups, native burst
length BL16 (+BL32 burst-chop), a DIMM-level Power Management IC (PMIC) + SPD hub
+ Registering Clock Driver (RCD) module architecture, internal VrefDQ/VrefCA with
read/write/CA training, a 2-cycle CA command protocol, and VDD/VDDQ = 1.1 V.
Applies the JESD79-5 spec-canonical content to L1-L23.

Doctrine — GENERAL not keyword: detection uses canonical STRUCTURAL signatures
(JESD79-5 + two 32-bit sub-channels + DFE + on-die ECC + same-bank refresh +
DIMM-PMIC/SPD-hub) read from the L-doc / input_doc CONTENT blob only. It NEVER
reads the input-document filename or the benchmark folder name. A detector keyed
on the NAME alone ("DDR5" in blob) would mis-fire because the Phase-1 runner
injects a generic memory vocabulary and L9 interface_types into foreign docs;
every True path therefore REQUIRES a DDR5-specific structural feature, not just
the name token.

Sibling disambiguation — the memory family (DDR3 / DDR4 / LPDDR5 / HBM3). All
are JEDEC DRAM specs and share "SDRAM"/"DDR"/"JEDEC"/"mode register"/"bank group"
vocabulary, so the detector REQUIRES the DDR5-only structural cluster and DEFERS
when the doc is:
  - DDR3-primary  (JESD79-3, 1.5 V, DLL, single 64-bit bus, no DFE/sub-channel),
  - DDR4-primary  (JESD79-4, 1.2 V, bank groups WITHOUT DFE/sub-channel/DIMM-PMIC,
                   gear-down mode),
  - LPDDR5-primary (JESD209-5, a separate Write Clock WCK, low-power), or
  - HBM3-primary  (JESD238, 3D-stacked, TSV, 1024-bit, pseudo-channel).
DDR5 legitimately mentions these siblings in its comparative sections, so the
MUTEX defers only when the sibling is the PRIMARY subject (its own spec-id/name
present AND the DDR5-only structural cluster absent).

Public entry: ``apply_ddr5_synth(generated_docs_dir, is_ddr5, ddr5_ic_name)``.
Module-level ``is_ddr5(blob)`` is the content-only detector.
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

# Canonical DDR5 facts (JEDEC JESD79-5).
_VDD = "1.1 V"
_VDDQ = "1.1 V"
_VPP = "1.8 V"
_SUBCHANNELS_PER_DIMM = 2
_SUBCHANNEL_DATA_BITS = 32
_SUBCHANNEL_ECC_BITS = 40
_BANKS_X8 = 32
_BANK_GROUPS_X8 = 8
_BANKS_PER_GROUP = 4
_BANKS_X16 = 16
_BANK_GROUPS_X16 = 4
_BURST_LENGTH = 16
_BURST_CHOP = 32
_CA_BUS_BITS = 14            # CA[13:0]
_CA_COMMAND_CYCLES = 2       # 2-cycle CA command protocol
_MIN_DATA_RATE_MTPS = 3200
_MAX_DATA_RATE_MTPS = 8400
_SPEED_BINS_MTPS = [3200, 3600, 4000, 4400, 4800, 5200, 5600, 6000,
                    6400, 7200, 8000, 8400]
_DEVICE_ORGS = ["x4", "x8", "x16"]
_CORE_COMMANDS = [
    "ACTIVATE", "READ", "WRITE", "PRECHARGE", "PRECHARGE_ALL",
    "REFRESH_ALL_BANK", "REFRESH_SAME_BANK", "SELF_REFRESH_ENTRY",
    "SELF_REFRESH_EXIT", "MODE_REGISTER_WRITE", "MODE_REGISTER_READ",
    "MULTI_PURPOSE_COMMAND",
]
_TRAINING_MODES = [
    "CA training", "Write Leveling", "Read training / read DQ calibration",
    "Write training (DFE tap + write VrefDQ)", "MPC-driven modes",
]


def is_ddr5(blob: str) -> bool:
    """Content-only DDR5 (JESD79-5) detector with a memory-family sibling MUTEX.

    Fire on the DDR5 structural signature — at least one DDR5-only structural
    feature beyond the name token: two independent 32-bit (40-bit ECC)
    sub-channels per DIMM, Decision Feedback Equalization on DQ, on-die ECC,
    same-bank refresh, a DIMM-level PMIC / SPD-hub module architecture, the
    2-cycle CA command protocol, or the JESD79-5 spec-id paired with such a
    feature. DEFER when the doc is DDR3-/DDR4-/LPDDR5-/HBM3-PRIMARY (its own
    spec-id/name present AND the DDR5-only structural cluster absent) so a
    sibling memory spec cannot false-fire. Reads ONLY the spec text `blob` —
    never a filename or benchmark name.
    """
    if not blob:
        return False
    low = blob.lower()

    # --- DDR5-only structural features (absent from DDR3/DDR4 primary specs;
    #     mentioned only comparatively, if at all, in LPDDR5/HBM3 specs). ---
    jesd795 = "jesd79-5" in low
    name_token = "ddr5" in low

    # Two independent 32-bit (40-bit ECC) sub-channels per DIMM — the single
    # most defining DDR5 feature (DDR4 has ONE 64/72-bit bus).
    sub_channel = (
        ("sub-channel" in low or "subchannel" in low or "sub channel" in low)
        and ("independent" in low or "32-bit" in low or "32 bit" in low
             or "two" in low or "40-bit" in low))

    # Decision Feedback Equalization on DQ receivers (new in DDR5).
    dfe = ("decision feedback equalization" in low
           or ("dfe" in low and ("equaliz" in low or "tap" in low
                                  or "receiver" in low)))

    # On-die ECC standard in every device.
    odecc = ("on-die ecc" in low or "on die ecc" in low
             or "odecc" in low)

    # Same-bank refresh (REFsb) — new DDR5 refresh granularity.
    same_bank_refresh = ("same-bank refresh" in low or "same bank refresh" in low
                         or "refsb" in low)

    # DIMM-level PMIC / SPD-hub / RCD on-module power architecture.
    dimm_pmic = (("pmic" in low or "power management ic" in low)
                 and ("dimm" in low or "module" in low or "on-module" in low
                      or "on module" in low))
    spd_hub = "spd hub" in low

    # 2-cycle CA command protocol (DDR4 is single-cycle).
    two_cycle_ca = (("2-cycle" in low or "two-cycle" in low or "two cycle" in low
                     or "2 cycle" in low)
                    and ("ca" in low or "command" in low))

    ddr5_features = [
        sub_channel, dfe, odecc, same_bank_refresh, dimm_pmic, spd_hub,
        two_cycle_ca,
    ]
    n_features = sum(1 for f in ddr5_features if f)

    # The DDR5-only structural cluster: at least two distinct DDR5 features,
    # OR the JESD79-5 spec-id paired with at least one feature.
    ddr5_cluster = (n_features >= 2) or (jesd795 and n_features >= 1)
    if not ddr5_cluster:
        return False

    # ---------------- Sibling MUTEX (defer when a sibling is PRIMARY) -------
    # The Phase-1 runner injects a generic memory vocabulary and L9 interface
    # NAMES into foreign docs, and the memory-family gold legitimately mentions
    # DDR5 in comparison sections, so a sibling spec (DDR3/DDR4/LPDDR5/HBM3) can
    # carry incidental "DDR5"/"sub-channel"/"on-die ECC" tokens AND therefore a
    # spurious DDR5 feature cluster. A bare cluster is thus NOT sufficient.
    #
    # The clean, spec-grounded, content-only discriminator is DOMINANCE of the
    # document SUBJECT: in a genuine DDR5 spec the DDR5 spec-id (JESD79-5) and
    # name token ("DDR5") are the primary subject and DOMINATE every sibling's
    # spec-id / name token; in a sibling spec the sibling's own tokens dominate
    # even when DDR5 appears comparatively. We compare raw token frequencies
    # (no filename / benchmark-name read — only the text blob).
    def _c(tok: str) -> int:
        return low.count(tok)

    ddr5_subject = _c("ddr5") + 3 * _c("jesd79-5")
    ddr3_subject = _c("jesd79-3") + _c("ddr3")
    ddr4_subject = _c("jesd79-4") + _c("ddr4")
    lpddr5_subject = _c("jesd209-5") + _c("lpddr5")
    hbm3_subject = (_c("jesd238") + _c("hbm3")
                    + _c("high bandwidth memory"))

    # DDR5 must be the dominant subject. (LPDDR5 contains the substring "ddr5",
    # so subtract the lpddr5 count from the raw ddr5 count to avoid LPDDR5's
    # name inflating the DDR5 subject — "lpddr5" ends in "ddr5".)
    ddr5_subject_net = ddr5_subject - _c("lpddr5")
    dominant = (
        ddr5_subject_net > ddr3_subject
        and ddr5_subject_net > ddr4_subject
        and ddr5_subject_net > lpddr5_subject
        and ddr5_subject_net > hbm3_subject)
    if not dominant:
        return False

    # Belt-and-suspenders: also require that no sibling is its own PRIMARY
    # subject (its spec-id present as the document number-class marker AND its
    # defining structural feature present) while DDR5's spec-id is absent.
    ddr3_primary = (
        "jesd79-3" in low
        and ("1.5 v" in low or "1.5v" in low or "dll" in low)
        and not jesd795
        and ddr3_subject > ddr5_subject_net)
    lpddr5_primary = (
        "jesd209-5" in low
        and ("wck" in low or "low-power" in low or "low power" in low)
        and not jesd795
        and lpddr5_subject > ddr5_subject_net)
    hbm3_primary = (
        "jesd238" in low
        and ("tsv" in low or "1024-bit" in low or "1024 bit" in low
             or "stacked" in low or "pseudo channel" in low
             or "pseudo-channel" in low)
        and not jesd795
        and hbm3_subject > ddr5_subject_net)
    if ddr3_primary or lpddr5_primary or hbm3_primary:
        return False

    # Fire only on the DDR5-only structural cluster AND DDR5-dominant subject.
    # The bare name token alone is NEVER sufficient (anti-keyword): the cluster
    # plus a DDR5 marker (name or spec-id) is required.
    return bool(ddr5_cluster and (name_token or jesd795))


def apply_ddr5_synth(generated_docs_dir: Path, is_ddr5_flag: bool,
                     ddr5_ic_name: Optional[str]) -> None:
    """Apply JESD79-5 DDR5 synth when the DDR5 signature matched.

    Force-ASSIGNS every key (not setdefault), because a sibling memory synth
    (LPDDR5 / HBM3 / DDR3) may run first and leave its own overlay in place;
    DDR5 is the more-specific generation and must override.
    """
    if not is_ddr5_flag:
        return
    gd = Path(generated_docs_dir)

    # --- Force ic_name across ALL 24 docs FIRST (main + fields docs). ---
    if ddr5_ic_name is not None:
        for n in _MAIN_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                d["ic_name"] = ddr5_ic_name
                _write(q, d)
        for n in _FIELDS_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                f = _ensure_dict(d, "fields")
                f["ic_name"] = ddr5_ic_name
                d["ic_name"] = ddr5_ic_name
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
# L1 — DDR5 datasheet header + headline facts.
# ----------------------------------------------------------------------
def _l1(gd: Path) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    d["document_title"] = "DDR5 SDRAM Standard"
    d["document_number"] = "JESD79-5"
    d["version"] = "JEDEC Standard JESD79-5 (DDR5 SDRAM)"
    d["revised_date"] = "JESD79-5 (DDR5 SDRAM)"
    d["manufacturer"] = "JEDEC Solid State Technology Association"
    d["publisher"] = "JEDEC Solid State Technology Association"
    d["copyright"] = "© JEDEC Solid State Technology Association"
    d["abstract"] = (
        "DDR5 SDRAM (Double Data Rate 5 Synchronous Dynamic Random Access "
        "Memory) is the fifth-generation mainstream double-data-rate DRAM "
        "defined by JEDEC Standard JESD79-5. DDR5 is the successor to DDR4 "
        "(JESD79-4) and targets higher bandwidth, capacity, and channel "
        "efficiency at a lower 1.1 V VDD/VDDQ supply. Its single most defining "
        "architectural change is the split of each DIMM channel into TWO "
        "INDEPENDENT 32-bit (40-bit with ECC) sub-channels, each with its own "
        "command/address (CA) bus, chip-select, and clock — versus DDR4's "
        "single 64/72-bit bus. DDR5 adds Decision Feedback Equalization (DFE) "
        "on the DQ receivers, On-Die ECC (ODECC) in every device, 32 banks in "
        "8 bank groups with same-bank refresh, a native burst length of 16 "
        "(BL16) plus BL32 burst-chop, internal VrefDQ/VrefCA with read/write/CA "
        "training, a 2-cycle CA command protocol, an expanded mode-register "
        "space, and a DIMM-level Power Management IC (PMIC) + SPD hub + "
        "Registering Clock Driver (RCD) module architecture. Speed bins span "
        "DDR5-3200 through DDR5-8400+ MT/s.")
    d["keywords"] = [
        "DDR5", "JESD79-5", "SDRAM", "double data rate", "sub-channel",
        "two sub-channels", "32-bit sub-channel", "Decision Feedback "
        "Equalization", "DFE", "on-die ECC", "ODECC", "bank group",
        "same-bank refresh", "REFsb", "BL16", "burst length 16", "burst chop",
        "DDR5-3200", "DDR5-8400", "MT/s", "1.1 V", "VDD", "VDDQ", "VPP",
        "VrefDQ", "VrefCA", "CA training", "write training", "read training",
        "2-cycle CA", "command/address", "mode register", "MRW", "MRR",
        "DIMM PMIC", "Power Management IC", "SPD hub", "RCD",
        "Registering Clock Driver", "RDIMM", "UDIMM", "LRDIMM", "DQS",
        "CK_t", "CK_c", "ACTIVATE", "PRECHARGE", "REFRESH", "ZQ", "ALERT_n",
    ]
    d["external_pins"] = [
        "CK_t / CK_c: differential clock (command/address timing reference) "
        "per sub-channel",
        "CS_n: chip select per sub-channel",
        "CA[13:0]: command/address bus (2-cycle commands) per sub-channel",
        "DQ[31:0]: data bus, 32 bits per sub-channel (40 with ECC)",
        "DQS_t / DQS_c: differential data strobe (source-synchronous, per byte)",
        "DM_n / DBI_n: data mask / data bus inversion (per byte lane)",
        "CKE: clock enable / power-down control",
        "RESET_n: asynchronous reset",
        "ALERT_n: CRC / command-address parity error alert",
        "ZQ: external calibration reference resistor",
        "VDD / VDDQ: 1.1 V supplies; VPP: 1.8 V wordline-boost supply",
        "Vref: internal (VrefDQ / VrefCA generated on-die)",
    ]
    d["supported_data_rates_MTps"] = list(_SPEED_BINS_MTPS)
    d["max_data_rate_MTps"] = _MAX_DATA_RATE_MTPS
    d["device_organizations"] = list(_DEVICE_ORGS)
    d["supply_voltages"] = {"VDD": _VDD, "VDDQ": _VDDQ, "VPP": _VPP}
    d["modes_of_operation"] = [
        {"name": "Two independent sub-channels",
         "role": "channel concurrency",
         "note": "Each DDR5 DIMM presents two independent 32-bit (40-bit ECC) "
                 "sub-channels, each with its own CA bus, CS_n, and clock; the "
                 "two operate independently, doubling concurrent accesses vs "
                 "DDR4's single 64/72-bit bus."},
        {"name": "BL16 / BL32 burst",
         "role": "data transfer",
         "note": "Native burst length 16 (16 beats x 32 bits = 64-byte cache "
                 "line per sub-channel), plus BL32 burst-chop and on-the-fly "
                 "burst control."},
        {"name": "On-die ECC + Error Check and Scrub (ECS)",
         "role": "reliability",
         "note": "Single-error-correcting on-die ECC in every device, plus an "
                 "internal scrub (ECS) mode."},
    ]
    d["key_features"] = [
        "Fifth-generation mainstream DDR SDRAM; JEDEC JESD79-5.",
        "Two INDEPENDENT 32-bit (40-bit with ECC) sub-channels per DIMM, each "
        "with its own CA bus, CS_n, and CK_t/CK_c (vs DDR4's single 64/72-bit "
        "bus).",
        "Decision Feedback Equalization (DFE) on the DQ receivers to cancel "
        "post-cursor ISI at high data rates.",
        "On-Die ECC (ODECC) standard in every device; Error Check and Scrub "
        "(ECS).",
        "32 banks in 8 bank groups (x8 device; 16 banks / 4 groups for x16); "
        "all-bank refresh (REFab) plus same-bank refresh (REFsb).",
        "Native burst length BL16 (64-byte access per sub-channel) plus BL32 "
        "burst-chop.",
        "Speed bins DDR5-3200 through DDR5-8400+ MT/s (double-data-rate, two "
        "beats per CK period).",
        "VDD = VDDQ = 1.1 V, VPP = 1.8 V (lower than DDR4's 1.2 V VDD/VDDQ).",
        "Internal VrefDQ / VrefCA generation with CA / read / write training.",
        "New 2-cycle CA command protocol (CA[13:0]); greatly expanded mode-"
        "register space (MR0..MRxx).",
        "DIMM-level Power Management IC (PMIC, 12 V -> 1.1 V on module), SPD "
        "hub, and Registering Clock Driver (RCD) for RDIMMs; Duty-Cycle "
        "Adjuster (DCA).",
    ]
    d["topology_summary"] = (
        "Parallel, source-synchronous, double-data-rate DRAM. Each DIMM is "
        "split into two independent 32-bit (40-bit ECC) sub-channels; each "
        "sub-channel drives its DRAMs over CA[13:0] + CS_n (2-cycle commands) "
        "with DQ[31:0] captured on DQS_t/DQS_c. RDIMMs add a Registering Clock "
        "Driver (RCD) and an SPD hub; an on-module PMIC produces the 1.1 V "
        "rails from 12 V.")
    d["density_organization_summary"] = (
        "x4 / x8 devices: 32 banks in 8 bank groups (4 banks per group). x16 "
        "device: 16 banks in 4 bank groups. Each access at BL16 moves a "
        "64-byte cache line per 32-bit sub-channel.")
    d["bandwidth_summary"] = (
        "Per-pin data rate from DDR5-3200 (3200 MT/s) to DDR5-8400+ MT/s, at a "
        "3200 MHz clock for DDR5-6400 (two beats per CK period). The two "
        "independent sub-channels double the number of concurrent accesses per "
        "DIMM relative to DDR4.")
    d["use_cases"] = [
        "Mainstream desktop / laptop / workstation main memory (UDIMM / SODIMM)",
        "Server and data-center main memory (RDIMM / LRDIMM with RCD / DB)",
        "High-bandwidth CPU and accelerator memory subsystems",
        "Capacity-scaled memory with on-die ECC for reliability",
    ]
    d["revision_history"] = [
        {"version": "DDR3 (JESD79-3)", "date": "2007",
         "description": "1.5 V, DLL, single 64/72-bit bus, BL8, no bank "
                        "groups."},
        {"version": "DDR4 (JESD79-4)", "date": "2012",
         "description": "1.2 V, bank groups, single 64/72-bit bus, BL8, "
                        "gear-down; no DFE / sub-channels / on-die-ECC / "
                        "DIMM-PMIC."},
        {"version": "DDR5 (JESD79-5)", "date": "2020",
         "description": "1.1 V, two independent 32-bit sub-channels, BL16, DFE, "
                        "on-die ECC, same-bank refresh, 32 banks / 8 groups, "
                        "DIMM PMIC / SPD-hub / RCD, internal VrefDQ/VrefCA, "
                        "2-cycle CA, expanded mode registers."},
    ]
    d["overview"] = (
        "DDR5 SDRAM (JEDEC JESD79-5) is the fifth-generation mainstream "
        "double-data-rate DRAM. Relative to DDR4 it splits each DIMM channel "
        "into two independent 32-bit (40-bit ECC) sub-channels, lowers "
        "VDD/VDDQ to 1.1 V, raises the per-pin data rate to DDR5-8400+ MT/s, "
        "doubles the native burst length to BL16, adds Decision Feedback "
        "Equalization on the DQ receivers, makes On-Die ECC standard, organizes "
        "32 banks into 8 bank groups with same-bank refresh, moves VrefDQ/"
        "VrefCA on-die with CA/read/write training, uses a 2-cycle CA command "
        "protocol over CA[13:0], greatly expands the mode-register space, and "
        "moves power management onto the DIMM with a PMIC, an SPD hub, and "
        "(for RDIMMs) a Registering Clock Driver. It remains a parallel, "
        "source-synchronous DRAM clocked off CK_t/CK_c with DQS_t/DQS_c data "
        "strobes — not a serial link, not a low-power WCK part (LPDDR5), and "
        "not a 3D-stacked TSV part (HBM3).")
    _write(p, d)


# ----------------------------------------------------------------------
# L2 — FRS / protocol overview.
# ----------------------------------------------------------------------
def _l2(gd: Path) -> None:
    p = gd / "L2_FRS.json"
    if not p.is_file():
        return
    d = _read(p)
    po = _ensure_dict(d, "protocol_overview")
    po["type"] = (
        "Parallel, source-synchronous, double-data-rate synchronous DRAM "
        "(JESD79-5). Each DIMM is split into two independent 32-bit (40-bit "
        "ECC) sub-channels; commands use a 2-cycle CA protocol; data is "
        "double-pumped on DQS strobes.")
    po["duplex"] = (
        "Half-duplex bidirectional DQ bus per sub-channel (reads and writes "
        "share DQ, captured on the bidirectional DQS_t/DQS_c strobe).")
    po["synchronous_serial"] = False
    po["source_synchronous"] = True
    po["embedded_clock"] = False
    po["forwarded_clock"] = True
    po["double_data_rate"] = True
    po["encoding"] = (
        "Unencoded parallel binary on DQ; optional Data Bus Inversion (DBI) "
        "to limit simultaneous switching; write CRC and command/address parity "
        "for integrity. Data is captured on both edges of DQS_t/DQS_c (double "
        "data rate).")
    po["modulation"] = (
        "Single-ended POD-style DQ signaling referenced to internal VrefDQ; "
        "differential CK_t/CK_c clock and DQS_t/DQS_c strobe.")
    po["data_rates_MTps"] = list(_SPEED_BINS_MTPS)
    po["max_data_rate_MTps"] = _MAX_DATA_RATE_MTPS
    po["sub_channels_per_dimm"] = _SUBCHANNELS_PER_DIMM
    po["sub_channel_data_bits"] = _SUBCHANNEL_DATA_BITS
    po["sub_channel_ecc_bits"] = _SUBCHANNEL_ECC_BITS
    po["burst_length"] = _BURST_LENGTH
    po["banks_x8"] = _BANKS_X8
    po["bank_groups_x8"] = _BANK_GROUPS_X8
    po["supply_voltages"] = {"VDD": _VDD, "VDDQ": _VDDQ, "VPP": _VPP}
    po["ca_command_cycles"] = _CA_COMMAND_CYCLES
    po["topology"] = (
        "DIMM -> two independent sub-channels -> bank groups -> banks; RDIMM "
        "adds RCD; module carries PMIC + SPD hub.")
    d["functional_requirements"] = [
        {"id": "FR-SUBCH-01", "text": "Each DDR5 DIMM is partitioned into two "
         "INDEPENDENT 32-bit (40-bit with ECC) sub-channels, each with its own "
         "command/address bus, chip-select, and clock; the two sub-channels "
         "operate independently."},
        {"id": "FR-DFE-02", "text": "The DDR5 SDRAM applies Decision Feedback "
         "Equalization (DFE) on its DQ receivers to cancel post-cursor "
         "inter-symbol interference; DFE tap coefficients are tuned during "
         "write training and stored in mode registers."},
        {"id": "FR-ODECC-03", "text": "Every DDR5 device implements On-Die ECC "
         "(ODECC), a single-error-correcting code computed and checked inside "
         "the die, transparent to the host; an Error Check and Scrub (ECS) mode "
         "scrubs accumulated errors."},
        {"id": "FR-BANK-04", "text": "The array is organized as 32 banks in 8 "
         "bank groups for x4/x8 devices (16 banks / 4 groups for x16); "
         "tCCD_L applies within a bank group and tCCD_S across bank groups."},
        {"id": "FR-REF-05", "text": "DDR5 supports all-bank refresh (REFab) and "
         "same-bank refresh (REFsb), which refreshes the same bank number "
         "across all bank groups while leaving other banks accessible, plus "
         "fine-granularity and temperature-controlled refresh."},
        {"id": "FR-BL-06", "text": "The native burst length is BL16 (16 beats; "
         "64-byte access per 32-bit sub-channel), with BL32 burst-chop and "
         "on-the-fly burst-length control."},
        {"id": "FR-RATE-07", "text": "DDR5 supports speed bins from DDR5-3200 "
         "(3200 MT/s) to DDR5-8400+ MT/s; data is double-data-rate (two beats "
         "per CK period)."},
        {"id": "FR-VOLT-08", "text": "VDD = VDDQ = 1.1 V and VPP = 1.8 V, "
         "lower than DDR4's 1.2 V VDD/VDDQ."},
        {"id": "FR-VREF-09", "text": "VrefDQ and VrefCA are generated and "
         "trimmed inside the DDR5 device and centered during read/write/CA "
         "training (write leveling, read DQ calibration, CA training, "
         "MPC-driven modes)."},
        {"id": "FR-CA-10", "text": "Commands use a 2-cycle CA protocol over "
         "CA[13:0] with a per-sub-channel CS_n; the command set includes "
         "ACTIVATE, READ, WRITE, PRECHARGE, REFRESH (REFab/REFsb), self "
         "refresh, MRW/MRR, and MPC."},
        {"id": "FR-MR-11", "text": "DDR5 greatly expands the mode-register "
         "space (MR0..MRxx) relative to DDR4, covering burst length, CAS "
         "latency, DFE taps, VrefDQ/VrefCA, on-die-ECC control, refresh "
         "management, and equalization, accessed via MRW/MRR."},
        {"id": "FR-PMIC-12", "text": "Power management moves onto the DIMM: an "
         "on-module Power Management IC (PMIC) generates the 1.1 V / 1.8 V "
         "rails from 12 V, an SPD hub holds configuration and buffers the "
         "sideband bus, and RDIMMs add a Registering Clock Driver (RCD)."},
    ]
    d["error_response_conditions"] = [
        "On-die ECC single-bit error — corrected inside the device before the "
        "data leaves the die; counts reportable via mode registers.",
        "Write CRC error — flagged on ALERT_n; the controller retries the "
        "write.",
        "Command/Address parity error — flagged on ALERT_n; the command is "
        "blocked and recovery is initiated.",
        "Refresh/timing violation — a missed refresh or a tRCD/tRP/tRAS "
        "violation risks data loss; the controller must honor the timing "
        "parameters.",
    ]
    d["compliance_requirements"] = [
        "Two independent 32-bit (40-bit ECC) sub-channels per DIMM.",
        "Decision Feedback Equalization (DFE) on the DQ receivers.",
        "On-die ECC (ODECC) in every device; Error Check and Scrub (ECS).",
        "32 banks / 8 bank groups (x8); all-bank and same-bank refresh.",
        "Native BL16 (plus BL32 burst-chop).",
        "VDD = VDDQ = 1.1 V; VPP = 1.8 V.",
        "Internal VrefDQ / VrefCA with CA / read / write training.",
        "2-cycle CA command protocol over CA[13:0]; expanded mode registers.",
        "DIMM PMIC + SPD hub + RCD module architecture.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L3 — command / protocol model.
# ----------------------------------------------------------------------
def _l3(gd: Path) -> None:
    p = gd / "L3_CMD_PROTOCOL.json"
    if not p.is_file():
        return
    d = _read(p)
    d["protocol_type"] = (
        "Synchronous DRAM command/address protocol: 2-cycle commands on "
        "CA[13:0] qualified by a per-sub-channel CS_n and timed to CK_t/CK_c. "
        "A row is ACTIVATEd, columns are READ/WRITTEN (BL16) with data on DQ / "
        "DQS_t/DQS_c, then the row is PRECHARGEd. REFRESH (REFab/REFsb) and "
        "self-refresh maintain the cells; MRW/MRR and MPC configure the "
        "device.")
    d["command_address_bus"] = {
        "ca_bus": "CA[13:0]",
        "ca_bus_bits": _CA_BUS_BITS,
        "chip_select": "CS_n per sub-channel",
        "command_cycles": _CA_COMMAND_CYCLES,
        "note": "DDR5 uses a 2-cycle CA command encoding (a command occupies "
                "two consecutive UI on the CA bus), unlike DDR4's single-cycle "
                "encoding; this widens the command/address space.",
    }
    d["core_commands"] = [
        {"name": "ACTIVATE (ACT)", "purpose": "Open (activate) a row in a "
         "bank; tRCD before a column access."},
        {"name": "READ (RD)", "purpose": "Column read; returns BL16 beats on "
         "DQ aligned to DQS after CAS latency (CL)."},
        {"name": "WRITE (WR)", "purpose": "Column write; BL16 beats captured on "
         "DQ/DQS; tWR write recovery before precharge."},
        {"name": "PRECHARGE (PRE)", "purpose": "Close (precharge) a row; tRP "
         "before the next ACTIVATE."},
        {"name": "PRECHARGE ALL", "purpose": "Precharge all banks."},
        {"name": "REFRESH ALL-BANK (REFab)", "purpose": "Refresh all banks; "
         "tRFC."},
        {"name": "REFRESH SAME-BANK (REFsb)", "purpose": "Refresh the same "
         "bank across all bank groups, leaving other banks accessible."},
        {"name": "SELF REFRESH ENTRY / EXIT", "purpose": "Low-power retention "
         "with internal refresh."},
        {"name": "MODE REGISTER WRITE (MRW)", "purpose": "Write a mode "
         "register (2-cycle CA)."},
        {"name": "MODE REGISTER READ (MRR)", "purpose": "Read a mode "
         "register."},
        {"name": "MULTI-PURPOSE COMMAND (MPC)", "purpose": "Drive training and "
         "feature modes (ZQ cal, DFE, Vref, etc.)."},
    ]
    d["core_command_list"] = list(_CORE_COMMANDS)
    d["addressing"] = {
        "note": "A column access targets a {sub-channel, bank group, bank, "
                "row, column}; the row is opened by ACTIVATE and the column by "
                "READ/WRITE; the two sub-channels are addressed independently.",
        "banks_x8": _BANKS_X8,
        "bank_groups_x8": _BANK_GROUPS_X8,
        "banks_per_group": _BANKS_PER_GROUP,
    }
    d["timing_parameters"] = {
        "tRCD": "ACTIVATE-to-READ/WRITE (RAS-to-CAS) delay",
        "tRP": "row PRECHARGE time",
        "tRAS": "row active time",
        "tRFC": "refresh cycle time",
        "tCCD_L": "column-to-column delay within a bank group",
        "tCCD_S": "column-to-column delay across bank groups",
        "tWR": "write recovery time",
        "CL": "CAS (read) latency",
    }
    d["burst"] = {
        "native_burst_length": _BURST_LENGTH,
        "burst_chop": _BURST_CHOP,
        "note": "BL16 transfers 16 beats (64-byte cache line per 32-bit "
                "sub-channel); BL32 burst-chop and on-the-fly control "
                "supported.",
    }
    d["integrity"] = {
        "on_die_ecc": "single-error-correcting, internal to the die",
        "write_crc": "optional write-data CRC, error on ALERT_n",
        "ca_parity": "command/address parity, error on ALERT_n",
    }
    d["byte_oriented"] = False
    d["command_oriented"] = True
    d["double_data_rate"] = True
    _write(p, d)


# ----------------------------------------------------------------------
# L4 — register / mode-register model.
# ----------------------------------------------------------------------
def _l4(gd: Path) -> None:
    p = gd / "L4_REGMAP.json"
    if not p.is_file():
        return
    d = _read(p)
    d["register_map_present"] = True
    d["notes"] = (
        "DDR5 configuration and status live in a greatly expanded mode-register "
        "(MR) space (MR0..MRxx, dozens of registers vs DDR4's MR0..MR7), "
        "accessed by Mode Register Write (MRW) and Mode Register Read (MRR) "
        "commands over the 2-cycle CA protocol. The groups below summarize the "
        "DDR5 mode-register surface.")
    d["register_access"] = {
        "transport": "MRW (write) / MRR (read) commands on CA[13:0] (2-cycle)",
        "purpose": "Configure burst length, latencies, DFE taps, VrefDQ/VrefCA, "
                   "on-die-ECC, refresh management, and equalization; read "
                   "status and error counts.",
    }
    d["register_groups"] = [
        {"group": "Core timing / burst", "fields": [
            "MR0: burst length, CAS (read) latency",
            "MR2: write latency, 2N command mode",
            "Read / write latency and preamble settings"]},
        {"group": "Signal integrity (DFE / DCA / Vref)", "fields": [
            "DFE tap coefficients (per-DQ decision-feedback equalizer)",
            "VrefDQ (read/write) settings",
            "VrefCA setting",
            "Duty-Cycle Adjuster (DCA); Tx/Rx equalization"]},
        {"group": "Reliability (on-die ECC / ECS)", "fields": [
            "On-die ECC enable / error reporting",
            "Error Check and Scrub (ECS) control and counters",
            "Refresh management (RFM)"]},
        {"group": "Calibration / training", "fields": [
            "ZQ calibration control",
            "CA training, write leveling, read/write training control",
            "MPC (Multi-Purpose Command) feature/training selectors"]},
    ]
    d["protocol_fields"] = {
        "sub_channels_per_dimm": _SUBCHANNELS_PER_DIMM,
        "sub_channel_data_bits": _SUBCHANNEL_DATA_BITS,
        "banks_x8": _BANKS_X8,
        "bank_groups_x8": _BANK_GROUPS_X8,
        "burst_length": _BURST_LENGTH,
        "ca_bus_bits": _CA_BUS_BITS,
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L5 — analog / physical signaling spec.
# ----------------------------------------------------------------------
def _l5(gd: Path) -> None:
    p = gd / "L5_ADI_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["analog_digital_interface_present"] = True
    d["signaling_summary"] = (
        "DDR5 is a parallel, source-synchronous DRAM. Commands/addresses are "
        "captured on CA[13:0] relative to the differential clock CK_t/CK_c; "
        "data is captured on the bidirectional DQ bus on both edges of the "
        "differential data strobe DQS_t/DQS_c (double data rate). DQ uses "
        "POD-style single-ended signaling referenced to an internal VrefDQ. "
        "Decision Feedback Equalization (DFE) on the DQ receivers and a "
        "Duty-Cycle Adjuster (DCA) maintain the eye at high data rates. There "
        "is no embedded/serial clock and no separate Write Clock (WCK).")
    d["modulation"] = (
        "Single-ended POD DQ (VrefDQ-referenced); differential CK_t/CK_c and "
        "DQS_t/DQS_c.")
    d["clocking"] = (
        "Forwarded differential clock CK_t/CK_c times commands; forwarded "
        "differential strobe DQS_t/DQS_c times data (double data rate). DDR5 "
        "has NO WCK (that is an LPDDR5 feature).")
    d["transmitter_specs_canonical"] = {
        "data_rates_MTps": list(_SPEED_BINS_MTPS),
        "max_data_rate_MTps": _MAX_DATA_RATE_MTPS,
        "signaling": "single-ended POD DQ (VrefDQ-referenced)",
        "data_bus_inversion": "DBI supported (per byte lane)",
        "duty_cycle_adjuster": "DCA on the DQ/DQS path",
    }
    d["receiver_specs_canonical"] = {
        "equalization": "Decision Feedback Equalization (DFE) on DQ receivers",
        "vref": "internal VrefDQ (per-DQ trimming in some implementations)",
        "strobe": "DQS_t/DQS_c differential data strobe (double data rate)",
    }
    d["supply_voltages"] = {"VDD": _VDD, "VDDQ": _VDDQ, "VPP": _VPP}
    d["calibration"] = {
        "zq": "ZQ external reference resistor for output-driver / ODT "
              "calibration",
        "training": list(_TRAINING_MODES),
        "vref": "internal VrefDQ / VrefCA generation and centering",
    }
    d["max_data_rate_MTps"] = _MAX_DATA_RATE_MTPS
    d["data_rates_MTps"] = list(_SPEED_BINS_MTPS)
    d["encoding_role_in_analog"] = (
        "DDR5 transmits unencoded parallel binary on DQ (optionally DBI-coded "
        "to limit simultaneous switching) and double-pumps it on DQS_t/DQS_c. "
        "Signal integrity at DDR5 data rates comes from DFE on the DQ "
        "receivers, the Duty-Cycle Adjuster, internal VrefDQ/VrefCA centering "
        "during training, ZQ calibration, and (on RDIMMs) the RCD re-driving "
        "CK/CA.")
    _write(p, d)


# ----------------------------------------------------------------------
# L6 — control logic / DRAM + bring-up FSMs.
# ----------------------------------------------------------------------
def _l6(gd: Path) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["fsm_states_bank"] = [
        {"name": "IDLE / PRECHARGED", "description": "All rows in the bank are "
         "precharged; the bank is ready for ACTIVATE."},
        {"name": "ACTIVATING", "description": "ACTIVATE opens a row; wait tRCD "
         "before a column access."},
        {"name": "ACTIVE", "description": "A row is open; READ / WRITE column "
         "accesses (BL16) proceed."},
        {"name": "PRECHARGING", "description": "PRECHARGE closes the row; wait "
         "tRP before the next ACTIVATE."},
    ]
    d["fsm_states_device"] = [
        {"name": "RESET / INIT", "description": "Power-up, RESET_n, voltage "
         "ramp, then initialization."},
        {"name": "TRAINING", "description": "CA training, write leveling, "
         "read/write training (DFE taps, VrefDQ/VrefCA centering), ZQ "
         "calibration via MPC."},
        {"name": "READY", "description": "Device trained and ready to service "
         "commands on both sub-channels."},
        {"name": "SELF_REFRESH", "description": "Low-power retention with "
         "internal refresh; exit returns to READY."},
        {"name": "POWER_DOWN", "description": "CKE-controlled power-down with "
         "fast exit."},
    ]
    d["fsm_hints"] = {
        "trigger": "Power-up / RESET_n -> voltage ramp -> initialization -> "
        "TRAINING (CA / write-leveling / read / write, DFE, VrefDQ/VrefCA, ZQ) "
        "-> READY. Each access: ACTIVATE (tRCD) -> READ/WRITE (BL16) -> "
        "PRECHARGE (tRP).",
        "rule": "Honor tRCD/tRP/tRAS/tRFC/tCCD/tWR/CL; refresh (REFab/REFsb) "
        "must meet tREFI so cells retain data; the two sub-channels are "
        "scheduled independently.",
        "refresh": "REFab refreshes all banks; REFsb refreshes the same bank "
        "across groups while other banks stay accessible.",
    }
    d["exit_from_reset_or_poweron"] = (
        "On power-up the rails ramp (1.1 V VDD/VDDQ, 1.8 V VPP), RESET_n is "
        "released, the device initializes, then training runs (CA training, "
        "write leveling, read/write training with DFE tap and VrefDQ/VrefCA "
        "centering, ZQ calibration via MPC) per sub-channel before normal "
        "operation.")
    d["default_ready_state_recommendation"] = {
        "idle": "Banks precharged (IDLE); the controller issues REFab/REFsb "
                "within tREFI.",
        "access": "ACTIVATE a row (tRCD), then READ/WRITE columns at BL16, then "
                  "PRECHARGE (tRP).",
    }
    d["configurations"] = [
        {"name": "x4 / x8 device", "description": "32 banks in 8 bank groups."},
        {"name": "x16 device", "description": "16 banks in 4 bank groups."},
        {"name": "UDIMM / SODIMM", "description": "Unbuffered module; two "
         "sub-channels; on-module PMIC + SPD hub; no RCD."},
        {"name": "RDIMM", "description": "Registered module; RCD re-drives "
         "CK/CA to the DRAMs."},
        {"name": "LRDIMM", "description": "Load-reduced module; RCD plus data "
         "buffers (DB)."},
    ]
    d["timing_dependency_rule"] = (
        "A column access requires its row open (ACTIVATE + tRCD); a new row in "
        "the same bank requires PRECHARGE + tRP; tCCD_L gates column-to-column "
        "within a bank group and tCCD_S across groups; tWR must elapse after a "
        "write before precharge; refresh (tRFC) must complete before accessing "
        "refreshed banks.")
    _write(p, d)


# ----------------------------------------------------------------------
# L7 — test / debug / observability.
# ----------------------------------------------------------------------
def _l7(gd: Path) -> None:
    p = gd / "L7_TEST_DEBUG.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_debug_architecture_present"] = True
    d["spec_provided_observability"] = [
        {"name": "Mode Register Read (MRR)", "purpose": "Read configuration "
         "and status registers, including on-die-ECC error counts and ECS "
         "results."},
        {"name": "On-die ECC error reporting", "purpose": "Single-bit error "
         "counts and Error Check and Scrub (ECS) status via mode registers."},
        {"name": "ALERT_n", "purpose": "Signals write-CRC and command/address "
         "parity errors to the controller."},
        {"name": "Training feedback (MPC)", "purpose": "Read training results "
         "(DFE taps, VrefDQ/VrefCA centers, read/write deskew)."},
        {"name": "ZQ calibration status", "purpose": "Output-driver / ODT "
         "calibration against the ZQ reference resistor."},
    ]
    d["error_detection_mechanisms"] = [
        "On-die ECC corrects single-bit errors inside the die.",
        "Error Check and Scrub (ECS) scrubs accumulated single-bit errors.",
        "Write CRC detects write-data corruption (ALERT_n).",
        "Command/Address parity detects CA-bus corruption (ALERT_n).",
        "Refresh-management (RFM) bounds row-hammer / refresh stress.",
    ]
    d["test_modes"] = [
        {"name": "MPC training/feature modes", "purpose": "Exercise DFE, Vref, "
         "ZQ, and read/write training."},
        {"name": "Connectivity / boundary test", "purpose": "Verify the CA / "
         "DQ / DQS / CK wiring on the module."},
        {"name": "Loopback / write-read", "purpose": "Functional verification "
         "of the data path per sub-channel."},
    ]
    d["interrupt_or_event_sources"] = [
        {"event": "On-die ECC error", "trigger": "A single-bit error is "
         "corrected; the count is readable via MRR."},
        {"event": "Write CRC error", "trigger": "Write-data CRC mismatch -> "
         "ALERT_n."},
        {"event": "CA parity error", "trigger": "Command/address parity "
         "mismatch -> ALERT_n."},
        {"event": "Refresh-management alert", "trigger": "RFM threshold "
         "reached."},
    ]
    d["notes"] = (
        "DDR5's protocol-level test/debug surface is the mode registers "
        "(MRR/MRW), on-die-ECC error reporting and ECS, ALERT_n for write-CRC "
        "and CA-parity errors, ZQ calibration, and MPC-driven training "
        "feedback. Chip-level JTAG/scan/BIST remain vendor / DRAM-die "
        "concerns; conformance is established by JEDEC compliance testing.")
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
        "DDR_STANDARD": "JEDEC JESD79-5 (DDR5 SDRAM)",
        "SIGNALING": "parallel source-synchronous double-data-rate",
        "SUB_CHANNELS_PER_DIMM": _SUBCHANNELS_PER_DIMM,
        "SUB_CHANNEL_DATA_BITS": _SUBCHANNEL_DATA_BITS,
        "SUB_CHANNEL_ECC_BITS": _SUBCHANNEL_ECC_BITS,
        "BANKS_X8": _BANKS_X8,
        "BANK_GROUPS_X8": _BANK_GROUPS_X8,
        "BANKS_PER_GROUP": _BANKS_PER_GROUP,
        "BANKS_X16": _BANKS_X16,
        "BANK_GROUPS_X16": _BANK_GROUPS_X16,
        "BURST_LENGTH": _BURST_LENGTH,
        "BURST_CHOP": _BURST_CHOP,
        "CA_BUS_BITS": _CA_BUS_BITS,
        "CA_COMMAND_CYCLES": _CA_COMMAND_CYCLES,
        "MIN_DATA_RATE_MTPS": _MIN_DATA_RATE_MTPS,
        "MAX_DATA_RATE_MTPS": _MAX_DATA_RATE_MTPS,
        "VDD": _VDD,
        "VDDQ": _VDDQ,
        "VPP": _VPP,
        "DECISION_FEEDBACK_EQUALIZATION": True,
        "ON_DIE_ECC": True,
        "SAME_BANK_REFRESH": True,
        "DIMM_PMIC": True,
        "SPD_HUB": True,
        "DOUBLE_DATA_RATE": True,
        "SOURCE_SYNCHRONOUS": True,
        "EMBEDDED_CLOCK": False,
        "HAS_WCK": False,
        "STACKED_TSV": False,
    })
    d["voltage_levels"] = {"VDD": _VDD, "VDDQ": _VDDQ, "VPP": _VPP}
    d["data_rate_constants"] = {
        "speed_bins_MTps": list(_SPEED_BINS_MTPS),
        "min_data_rate_MTps": _MIN_DATA_RATE_MTPS,
        "max_data_rate_MTps": _MAX_DATA_RATE_MTPS,
        "double_data_rate": True,
    }
    d["strobe_constants"] = {
        "clock": "CK_t / CK_c (differential, command timing)",
        "data_strobe": "DQS_t / DQS_c (differential, double data rate)",
        "wck": "none (DDR5 has no Write Clock)",
    }
    d["capacity_organization_constants"] = {
        "banks_x8": _BANKS_X8,
        "bank_groups_x8": _BANK_GROUPS_X8,
        "banks_per_group": _BANKS_PER_GROUP,
        "banks_x16": _BANKS_X16,
        "bank_groups_x16": _BANK_GROUPS_X16,
        "device_organizations": list(_DEVICE_ORGS),
    }
    kc = _ensure_dict(d, "key_constants_for_RTL_authoring")
    kc.update({
        "is_serial": False,
        "is_parallel": True,
        "is_source_synchronous": True,
        "is_double_data_rate": True,
        "embedded_clock": False,
        "forwarded_clock": True,
        "has_wck": False,
        "stacked_tsv": False,
        "sub_channels_per_dimm": _SUBCHANNELS_PER_DIMM,
        "sub_channel_data_bits": _SUBCHANNEL_DATA_BITS,
        "sub_channel_ecc_bits": _SUBCHANNEL_ECC_BITS,
        "banks_x8": _BANKS_X8,
        "bank_groups_x8": _BANK_GROUPS_X8,
        "burst_length": _BURST_LENGTH,
        "burst_chop": _BURST_CHOP,
        "ca_bus_bits": _CA_BUS_BITS,
        "ca_command_cycles": _CA_COMMAND_CYCLES,
        "decision_feedback_equalization": True,
        "on_die_ecc": True,
        "same_bank_refresh": True,
        "dimm_pmic": True,
        "spd_hub": True,
        "rcd_on_rdimm": True,
        "vdd": _VDD,
        "vddq": _VDDQ,
        "vpp": _VPP,
        "max_data_rate_MTps": _MAX_DATA_RATE_MTPS,
        "speed_bins_MTps": list(_SPEED_BINS_MTPS),
        "core_commands": list(_CORE_COMMANDS),
    })
    d["default_signal_values_when_idle"] = {
        "bus_idle": "Banks precharged (IDLE); CKE high; periodic REFab/REFsb "
                    "within tREFI.",
        "no_access": "DQ tri-stated between bursts; commands gated by CS_n.",
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
    d["bit_waveform"] = {
        "signaling": "parallel single-ended POD DQ (VrefDQ-referenced); "
                     "differential CK_t/CK_c and DQS_t/DQS_c",
        "data_rate": "double data rate (two beats per CK period)",
        "strobe": "DQ captured on both edges of DQS_t/DQS_c",
        "equalization": "DFE on DQ receivers; Duty-Cycle Adjuster on the path",
    }
    d["command_waveform"] = {
        "ca_command": "2-cycle command on CA[13:0], qualified by CS_n, timed "
                      "to CK_t/CK_c.",
        "row_cycle": "ACTIVATE (tRCD) -> READ/WRITE (BL16) -> PRECHARGE (tRP).",
        "latency": "Read data returns after CAS latency (CL); writes use the "
                   "write latency.",
    }
    d["burst_waveform"] = {
        "native_burst_length": _BURST_LENGTH,
        "burst_chop": _BURST_CHOP,
        "note": "BL16 = 16 beats = 64-byte cache line per 32-bit sub-channel.",
    }
    d["refresh_waveform"] = {
        "refab": "All-bank refresh (tRFC).",
        "refsb": "Same-bank refresh across bank groups; other banks "
                 "accessible.",
        "interval": "REFab/REFsb issued within tREFI.",
    }
    d["general_timing_rule"] = (
        "After power-up, voltage ramp, initialization, and training (CA / "
        "write-leveling / read / write, DFE, VrefDQ/VrefCA, ZQ), a row must be "
        "ACTIVATEd (tRCD) before a column access, PRECHARGEd (tRP) before "
        "re-activation, and refreshed (tRFC) within tREFI. Data is "
        "double-pumped on DQS_t/DQS_c.")
    d["data_rate_waveform"] = {
        "speed_bins_MTps": list(_SPEED_BINS_MTPS),
        "max_data_rate_MTps": _MAX_DATA_RATE_MTPS,
        "double_data_rate": True,
        "example": "DDR5-6400 = 6400 MT/s at a 3200 MHz CK.",
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L9 — integration spec.
# ----------------------------------------------------------------------
def _l9(gd: Path) -> None:
    p = gd / "L9_INTEGRATION_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["module_role"] = (
        "Mainstream DDR5 SDRAM memory (JESD79-5): a parallel, source-"
        "synchronous, double-data-rate DRAM whose DIMM is split into two "
        "independent 32-bit (40-bit ECC) sub-channels, each driven over "
        "CA[13:0] + CS_n (2-cycle commands) and CK_t/CK_c with DQ[31:0] on "
        "DQS_t/DQS_c. The device provides DFE on DQ, on-die ECC, 32 banks / 8 "
        "bank groups with same-bank refresh, BL16, internal VrefDQ/VrefCA with "
        "training, and an expanded mode-register space; the module adds a PMIC, "
        "SPD hub, and (RDIMM) RCD.")
    d["topology_description"] = (
        "DIMM -> two independent sub-channels -> bank groups -> banks. Each "
        "sub-channel is 32 data bits (40 with ECC) with its own CA bus, CS_n, "
        "and clock. RDIMMs interpose a Registering Clock Driver (RCD) on CK/CA; "
        "LRDIMMs add data buffers (DB). An on-module PMIC supplies 1.1 V / "
        "1.8 V and an SPD hub holds configuration.")
    io = _ensure_dict(d, "integration_overview")
    io.update({
        "ddr_standard": "JEDEC JESD79-5 (DDR5 SDRAM)",
        "max_data_rate_MTps": _MAX_DATA_RATE_MTPS,
        "speed_bins_MTps": list(_SPEED_BINS_MTPS),
        "sub_channels_per_dimm": _SUBCHANNELS_PER_DIMM,
        "sub_channel_data_bits": _SUBCHANNEL_DATA_BITS,
        "sub_channel_ecc_bits": _SUBCHANNEL_ECC_BITS,
        "banks_x8": _BANKS_X8,
        "bank_groups_x8": _BANK_GROUPS_X8,
        "burst_length": _BURST_LENGTH,
        "ca_bus_bits": _CA_BUS_BITS,
        "ca_command_cycles": _CA_COMMAND_CYCLES,
        "supply_voltages": {"VDD": _VDD, "VDDQ": _VDDQ, "VPP": _VPP},
        "signaling": "parallel source-synchronous double-data-rate",
        "clocking": "forwarded CK_t/CK_c + DQS_t/DQS_c (no WCK)",
        "decision_feedback_equalization": True,
        "on_die_ecc": True,
        "same_bank_refresh": True,
        "dimm_pmic": True,
        "spd_hub": True,
        "module_types": ["UDIMM", "SODIMM", "RDIMM", "LRDIMM"],
        "interfaces": {"command_address": "CA[13:0] + CS_n (2-cycle)",
                       "clock": "CK_t/CK_c",
                       "data": "DQ[31:0] + DQS_t/DQS_c (per sub-channel)",
                       "sideband": "SPD hub I2C/I3C to PMIC/RCD/sensors"},
    })
    d["interface_categories"] = [
        "Command/address interface — CA[13:0] + CS_n (2-cycle commands) per "
        "sub-channel.",
        "Clock interface — differential CK_t/CK_c per sub-channel.",
        "Data interface — DQ[31:0] + DQS_t/DQS_c (32 bits, 40 with ECC) per "
        "sub-channel.",
        "Module interface — PMIC (power), SPD hub (config), RCD (RDIMM clock/CA "
        "buffering).",
    ]
    d["interconnect_topologies_supported"] = [
        "Two independent sub-channels per DIMM (each 32/40-bit).",
        "UDIMM / SODIMM (unbuffered).",
        "RDIMM (RCD-buffered CK/CA).",
        "LRDIMM (RCD + data buffers).",
        "Multiple ranks per sub-channel addressed by CS_n.",
    ]
    d["default_signal_values_when_omitted"] = (
        "Banks precharged (IDLE); CKE high; DQ tri-stated between bursts; "
        "refresh (REFab/REFsb) issued within tREFI.")
    d["soc_dependent_items"] = [
        "Memory-controller scheduling of the two independent sub-channels.",
        "Selected speed bin (DDR5-3200 .. DDR5-8400) and timing parameters.",
        "Device organization (x4 / x8 / x16) and module type (U/SO/R/LR-DIMM).",
        "Training schedule (CA / write-leveling / read / write, DFE, VrefDQ/"
        "VrefCA, ZQ).",
        "On-die-ECC / ECS / refresh-management policy.",
        "PMIC / SPD-hub / RCD configuration over the sideband bus.",
    ]
    d["device_classes_examples"] = [
        "DDR5 UDIMM / SODIMM (desktop / laptop main memory)",
        "DDR5 RDIMM / LRDIMM (server main memory)",
        "DDR5 SDRAM component (x4 / x8 / x16)",
        "DDR5 memory controller (host)",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L10 — derived test cases.
# ----------------------------------------------------------------------
def _l10(gd: Path) -> None:
    p = gd / "L10_TEST_CASES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_cases_present"] = (
        "partial - the specification defines device behaviors rather than an "
        "embedded testbench; the categories below are derived from the spec.")
    d["derived_compliance_test_categories"] = [
        "Power-up / initialization / RESET_n sequence at 1.1 V VDD/VDDQ, "
        "1.8 V VPP.",
        "Training: CA training, write leveling, read training, write training "
        "(DFE tap tuning, VrefDQ/VrefCA centering), ZQ calibration via MPC.",
        "Two-sub-channel independence: concurrent unrelated access on "
        "Sub-Channel A and Sub-Channel B.",
        "Row cycle: ACTIVATE (tRCD) -> READ/WRITE (BL16) -> PRECHARGE (tRP); "
        "tRAS / tWR / CL.",
        "Bank-group timing: tCCD_L within a group vs tCCD_S across groups; "
        "32 banks / 8 groups.",
        "Refresh: all-bank (REFab) and same-bank (REFsb); tRFC / tREFI; fine-"
        "granularity and temperature refresh.",
        "Burst: BL16 and BL32 burst-chop; on-the-fly burst control.",
        "On-die ECC: single-bit correction and Error Check and Scrub (ECS).",
        "Integrity: write CRC and command/address parity errors on ALERT_n.",
        "Mode registers: MRW / MRR across the expanded MR space.",
        "Speed-bin sweep: DDR5-3200 .. DDR5-8400; double-data-rate capture on "
        "DQS.",
        "Module: PMIC rail bring-up, SPD-hub configuration, RCD CK/CA "
        "re-drive (RDIMM).",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L11 — OTP / factory-burned equivalents.
# ----------------------------------------------------------------------
def _l11(gd: Path) -> None:
    p = gd / "L11_OTP_CONTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    d["otp_present"] = False
    d["otp_equivalent_factory_burned_fields"] = [
        {"field": "SPD (Serial Presence Detect) contents",
         "location": "on-module SPD hub EEPROM",
         "note": "Module organization, supported speed bins, and timing "
                 "parameters; factory-programmed, read over the sideband bus."},
        {"field": "Mode-register power-on defaults",
         "location": "DDR5 device",
         "note": "Default burst length, CAS latency, and feature settings "
                 "before training overrides them."},
        {"field": "PMIC / RCD configuration defaults",
         "location": "module devices (PMIC, RCD)",
         "note": "On-module power and clock-driver defaults; programmable over "
                 "the SPD-hub sideband bus."},
    ]
    d["notes"] = (
        "DDR5 does not define DRAM-die OTP/fuse content as a protocol concept. "
        "The closest factory-programmed data is the SPD (Serial Presence "
        "Detect) held in the on-module SPD-hub EEPROM (module organization, "
        "speed bins, timings) plus mode-register power-on defaults and PMIC/RCD "
        "configuration; these are read/written over the sideband bus, not "
        "fixed OTP in the DRAM die.")
    _write(p, d)


# ----------------------------------------------------------------------
# L12 — behavioral sequences.
# ----------------------------------------------------------------------
def _l12(gd: Path) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["power_up_init_sequence"] = [
        "1. Ramp VDD/VDDQ to 1.1 V and VPP to 1.8 V (on a DIMM, the PMIC "
        "produces these from 12 V).",
        "2. Release RESET_n and run device initialization.",
        "3. Bring up the SPD hub and (RDIMM) the RCD over the sideband bus.",
    ]
    d["training_sequence"] = [
        "1. CA training: deskew CA[13:0] and center VrefCA per sub-channel.",
        "2. Write leveling: align DQS to CK at the DRAM.",
        "3. Read training: per-DQ read deskew and VrefDQ centering.",
        "4. Write training: tune the DFE tap coefficients and write VrefDQ; "
        "deskew write DQ.",
        "5. ZQ calibration (via MPC) of the output drivers / ODT.",
    ]
    d["read_sequence"] = [
        "1. ACTIVATE the target row (wait tRCD).",
        "2. Issue READ; after CAS latency (CL) the device returns BL16 beats "
        "on DQ aligned to DQS_t/DQS_c (double data rate).",
        "3. On-die ECC corrects any single-bit error before data leaves the "
        "die.",
        "4. PRECHARGE the row (wait tRP) when finished.",
    ]
    d["write_sequence"] = [
        "1. ACTIVATE the target row (wait tRCD).",
        "2. Issue WRITE; drive BL16 beats on DQ with DQS; the device computes "
        "and stores on-die ECC check bits; optional write CRC.",
        "3. Honor tWR (write recovery) before PRECHARGE.",
        "4. PRECHARGE the row (wait tRP).",
    ]
    d["refresh_sequence"] = [
        "1. Within tREFI, issue REFab (all-bank) or REFsb (same-bank across "
        "groups).",
        "2. For REFsb, other banks remain accessible during the refresh.",
        "3. Wait tRFC before accessing refreshed banks.",
    ]
    d["subchannel_concurrency_sequence"] = [
        "1. Sub-Channel A and Sub-Channel B each have their own CA bus, CS_n, "
        "and clock.",
        "2. A read/write on Sub-Channel A proceeds independently of traffic on "
        "Sub-Channel B, doubling concurrent accesses.",
    ]
    d["self_refresh_sequence"] = [
        "1. SELF REFRESH ENTRY places the device in low-power retention with "
        "internal refresh.",
        "2. SELF REFRESH EXIT returns to READY; re-training may be required at "
        "high speed bins.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L13 — lab calibration / measurement targets.
# ----------------------------------------------------------------------
def _l13(gd: Path) -> None:
    p = gd / "L13_LAB_CALIBRATION.json"
    if not p.is_file():
        return
    d = _read(p)
    d["lab_calibration_present"] = True
    d["lab_measurement_targets_from_spec"] = [
        {"name": "DQ eye / DFE", "purpose": "Verify the DQ data eye with "
         "Decision Feedback Equalization across the speed bins (DDR5-3200 .. "
         "DDR5-8400)."},
        {"name": "VrefDQ / VrefCA centering", "purpose": "Confirm the internal "
         "reference voltages center the sampling point during training."},
        {"name": "Duty-Cycle Adjuster", "purpose": "Measure DQ/DQS duty cycle "
         "after DCA correction."},
        {"name": "ZQ calibration", "purpose": "Verify output-driver / ODT "
         "impedance against the ZQ reference resistor."},
        {"name": "Timing parameters", "purpose": "Validate tRCD / tRP / tRAS / "
         "tRFC / tCCD / tWR / CL at the target speed bin."},
        {"name": "Refresh", "purpose": "Confirm REFab / REFsb and tREFI "
         "retention."},
        {"name": "PMIC rails", "purpose": "Measure the on-module 1.1 V / 1.8 V "
         "rails from the 12 V input."},
    ]
    d["notes"] = (
        "DDR5 characterization centers on the DQ eye with DFE, internal "
        "VrefDQ/VrefCA centering, the Duty-Cycle Adjuster, ZQ calibration, the "
        "core timing parameters, refresh retention, and the on-module PMIC "
        "rails. Training (CA / read / write, DFE tap, Vref) is performed at "
        "bring-up; conformance is established by JEDEC DDR5 compliance "
        "testing.")
    _write(p, d)


# ----------------------------------------------------------------------
# L14 — protocol versioning.
# ----------------------------------------------------------------------
def _l14(gd: Path) -> None:
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["spec_version"] = "JEDEC Standard JESD79-5 (DDR5 SDRAM)"
    f["previous_versions"] = [
        "DDR (JESD79) — first double-data-rate SDRAM.",
        "DDR2 (JESD79-2) — 1.8 V, 4n prefetch.",
        "DDR3 (JESD79-3) — 1.5 V, DLL, 8n prefetch, single 64/72-bit bus, BL8.",
        "DDR4 (JESD79-4) — 1.2 V, bank groups, single 64/72-bit bus, BL8, "
        "gear-down.",
    ]
    f["key_changes_vs_ddr4"] = [
        {"area": "Channel", "summary": "Each DIMM is split into two independent "
         "32-bit (40-bit ECC) sub-channels (DDR4: single 64/72-bit bus)."},
        {"area": "Signal integrity", "summary": "Decision Feedback Equalization "
         "(DFE) on DQ receivers and a Duty-Cycle Adjuster (DDR4: none)."},
        {"area": "Reliability", "summary": "On-die ECC standard in every device "
         "plus Error Check and Scrub (DDR4: not standard)."},
        {"area": "Banks / refresh", "summary": "32 banks in 8 bank groups and "
         "same-bank refresh (REFsb) (DDR4: 16 banks / 4 groups, no REFsb)."},
        {"area": "Burst", "summary": "Native BL16 (DDR4: BL8)."},
        {"area": "Voltage", "summary": "1.1 V VDD/VDDQ (DDR4: 1.2 V)."},
        {"area": "Reference / training", "summary": "Internal VrefDQ/VrefCA "
         "with CA/read/write training (DDR4: external VrefDQ in many "
         "configurations)."},
        {"area": "Command bus", "summary": "2-cycle CA protocol (DDR4: "
         "single-cycle)."},
        {"area": "Module / power", "summary": "DIMM-level PMIC, SPD hub, and "
         "RCD (DDR4: motherboard power, simpler SPD)."},
    ]
    f["backward_compat_traps"] = [
        {"trap_name": "Two_sub_channels_not_one",
         "rule": "A DDR5 DIMM has TWO independent 32-bit (40-bit ECC) "
                 "sub-channels.",
         "trap": "Treating a DDR5 DIMM as a single 64/72-bit DDR4 bus is "
                 "wrong."},
        {"trap_name": "BL16_not_BL8",
         "rule": "DDR5 native burst length is 16 (DDR4 is 8).",
         "trap": "Assuming BL8 mis-sizes the 64-byte access on a 32-bit "
                 "sub-channel."},
        {"trap_name": "Internal_Vref",
         "rule": "VrefDQ/VrefCA are generated on-die and trained.",
         "trap": "Supplying an external VrefDQ as in older parts is wrong."},
        {"trap_name": "Two_cycle_CA",
         "rule": "DDR5 commands occupy two CA cycles.",
         "trap": "Decoding DDR5 commands as single-cycle DDR4 commands is "
                 "wrong."},
        {"trap_name": "Not_LPDDR5_not_HBM3",
         "rule": "DDR5 is the mainstream generation timed off CK/DQS with no "
                 "WCK and no TSV stacking; LPDDR5 has a WCK and is low-power, "
                 "HBM3 is 3D-stacked (TSV, 1024-bit, pseudo-channels).",
         "trap": "Applying LPDDR5 WCK or HBM3 stacked/pseudo-channel "
                 "assumptions to DDR5 is wrong."},
    ]
    f["version_naming_history_note"] = (
        "DDR5 SDRAM is standardized by JEDEC as JESD79-5, the fifth generation "
        "in the JESD79 mainstream DDR family (DDR -> DDR2 -> DDR3 -> DDR4 -> "
        "DDR5). Each generation roughly doubles peak data rate while lowering "
        "the supply voltage. DDR5's defining additions over DDR4 (JESD79-4) "
        "are the two independent sub-channels, DFE, on-die ECC, same-bank "
        "refresh, BL16, internal VrefDQ/VrefCA, the 2-cycle CA protocol, and "
        "the DIMM PMIC/SPD-hub/RCD module architecture.")
    _write(p, d)


# ----------------------------------------------------------------------
# L15 — encoding / parameter tables.
# ----------------------------------------------------------------------
def _l15(gd: Path) -> None:
    p = gd / "L15_ENCODING_TABLES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["speed_bin_table"] = {
        "header_columns": ["Speed bin", "Data rate (MT/s)", "Clock (MHz)"],
        "rows": [
            ["DDR5-3200", "3200", "1600"],
            ["DDR5-3600", "3600", "1800"],
            ["DDR5-4000", "4000", "2000"],
            ["DDR5-4400", "4400", "2200"],
            ["DDR5-4800", "4800", "2400"],
            ["DDR5-5200", "5200", "2600"],
            ["DDR5-5600", "5600", "2800"],
            ["DDR5-6000", "6000", "3000"],
            ["DDR5-6400", "6400", "3200"],
            ["DDR5-7200", "7200", "3600"],
            ["DDR5-8000", "8000", "4000"],
            ["DDR5-8400", "8400", "4200"],
        ],
    }
    f["organization_table"] = {
        "header_columns": ["Device", "Banks", "Bank groups", "Banks/group"],
        "rows": [
            ["x4", "32", "8", "4"],
            ["x8", "32", "8", "4"],
            ["x16", "16", "4", "4"],
        ],
    }
    f["sub_channel_table"] = {
        "header_columns": ["Item", "Value"],
        "rows": [
            ["Sub-channels per DIMM", "2 (independent)"],
            ["Data bits per sub-channel", "32"],
            ["With ECC", "40"],
            ["CA bus", "CA[13:0], 2-cycle commands"],
            ["Native burst length", "BL16 (64-byte access)"],
        ],
    }
    f["voltage_table"] = {
        "header_columns": ["Rail", "Voltage"],
        "rows": [
            ["VDD", "1.1 V"],
            ["VDDQ", "1.1 V"],
            ["VPP", "1.8 V"],
        ],
    }
    f["command_table"] = {
        "header_columns": ["Command", "Purpose"],
        "rows": [
            ["ACTIVATE", "open a row (tRCD)"],
            ["READ", "column read (BL16, CL)"],
            ["WRITE", "column write (BL16, tWR)"],
            ["PRECHARGE", "close a row (tRP)"],
            ["REFab", "all-bank refresh (tRFC)"],
            ["REFsb", "same-bank refresh across groups"],
            ["MRW / MRR", "mode register write / read"],
            ["MPC", "multi-purpose / training command"],
        ],
    }
    f["encoding_note"] = (
        "DDR5 transmits unencoded parallel binary on DQ (optionally DBI-coded) "
        "double-pumped on DQS_t/DQS_c; commands use a 2-cycle CA encoding on "
        "CA[13:0]. Integrity is provided by on-die ECC, optional write CRC, and "
        "command/address parity. Speed bins span DDR5-3200 .. DDR5-8400 MT/s at "
        "1.1 V VDD/VDDQ.")
    f["tables"] = [
        "Speed-bin table (DDR5-3200 .. DDR5-8400; MT/s and clock)",
        "Organization table (x4/x8/x16 banks and bank groups)",
        "Sub-channel table (two 32/40-bit sub-channels, CA, BL16)",
        "Voltage table (VDD/VDDQ 1.1 V, VPP 1.8 V)",
        "Command table (ACTIVATE/READ/WRITE/PRECHARGE/REFab/REFsb/MRW/MRR/MPC)",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L16 — compliance properties.
# ----------------------------------------------------------------------
def _l16(gd: Path) -> None:
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["must_have_properties"] = [
        "Two INDEPENDENT 32-bit (40-bit ECC) sub-channels per DIMM, each with "
        "its own CA bus, CS_n, and clock.",
        "Decision Feedback Equalization (DFE) on the DQ receivers.",
        "On-die ECC (ODECC) in every device; Error Check and Scrub (ECS).",
        "32 banks in 8 bank groups (x8); all-bank (REFab) and same-bank "
        "(REFsb) refresh.",
        "Native burst length BL16 (plus BL32 burst-chop).",
        "VDD = VDDQ = 1.1 V; VPP = 1.8 V.",
        "Internal VrefDQ / VrefCA with CA / read / write training.",
        "2-cycle CA command protocol over CA[13:0]; expanded mode registers.",
        "DIMM-level PMIC + SPD hub + RCD (RDIMM) module architecture.",
    ]
    f["must_not_have_properties"] = [
        "A single 64/72-bit DDR4-style data bus per DIMM (DDR5 has two 32/40-"
        "bit sub-channels).",
        "A separate Write Clock (WCK) — that is LPDDR5, not DDR5.",
        "3D stacking with through-silicon vias (TSV), a 1024-bit interface, or "
        "pseudo-channels — that is HBM3, not DDR5.",
        "1.5 V operation with a DLL and BL8 (that is DDR3).",
        "An embedded / serial clock (DDR5 is parallel source-synchronous off "
        "CK_t/CK_c).",
    ]
    f["compliance_failure_modes"] = [
        {"mode": "On-die ECC uncorrectable", "trigger": "A multi-bit error "
         "exceeds the single-error-correcting on-die code."},
        {"mode": "Write CRC error", "trigger": "Write-data CRC mismatch on "
         "ALERT_n; the write is retried."},
        {"mode": "CA parity error", "trigger": "Command/address parity "
         "mismatch on ALERT_n; the command is blocked."},
        {"mode": "Timing violation", "trigger": "tRCD/tRP/tRAS/tRFC/tCCD/tWR/CL "
         "violated; access fails or corrupts data."},
        {"mode": "Refresh violation", "trigger": "A missed REFab/REFsb within "
         "tREFI risks retention loss."},
    ]
    f["min_link_constraint"] = (
        "A DDR5 access requires the device powered at 1.1 V VDD/VDDQ (1.8 V "
        "VPP), initialized and trained (CA / read / write, DFE, VrefDQ/VrefCA, "
        "ZQ), the target row ACTIVATEd (tRCD), and refresh maintained within "
        "tREFI; the two sub-channels operate independently.")
    f["reset_behavior_compliance"] = (
        "On RESET_n / power-up the rails ramp, the device initializes, and "
        "training runs before normal operation; self-refresh retains data in "
        "low power and re-training may be required on exit at high speed bins.")
    f["ddr5_distinguishers"] = (
        "DDR5 (JESD79-5) is identified by ALL of: two independent 32-bit "
        "(40-bit ECC) sub-channels per DIMM; Decision Feedback Equalization on "
        "DQ; on-die ECC; 32 banks / 8 bank groups with same-bank refresh; "
        "native BL16; 1.1 V VDD/VDDQ; internal VrefDQ/VrefCA with training; a "
        "2-cycle CA protocol; and a DIMM PMIC + SPD-hub + RCD module "
        "architecture. This is distinct from DDR3 (1.5 V, DLL, single 64-bit "
        "bus, BL8), DDR4 (1.2 V, single 64/72-bit bus, BL8, bank groups "
        "without DFE/sub-channels/on-die-ECC/DIMM-PMIC), LPDDR5 (a low-power "
        "WCK part, JESD209-5), and HBM3 (a 3D-stacked TSV part with a 1024-bit "
        "interface and pseudo-channels, JESD238).")
    _write(p, d)


# ----------------------------------------------------------------------
# L17 — channel / signal catalog.
# ----------------------------------------------------------------------
def _l17(gd: Path) -> None:
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["channels"] = [
        {"name": "Sub-Channel A / Sub-Channel B",
         "direction": "independent",
         "purpose": "Two independent 32-bit (40-bit ECC) sub-channels per "
                    "DIMM, each with its own CA bus, CS_n, and clock.",
         "active_levels": "N/A", "idle_level": "idle/precharged"},
        {"name": "DQ[31:0] (per sub-channel)",
         "direction": "bidirectional (read/write)",
         "purpose": "32-bit data bus (40 with ECC), double-pumped on DQS.",
         "active_levels": "POD (VrefDQ-referenced)", "idle_level": "tri-state"},
        {"name": "DQS_t / DQS_c (per byte)",
         "direction": "bidirectional strobe",
         "purpose": "Differential data strobe; data captured on both edges "
                    "(double data rate).",
         "active_levels": "differential", "idle_level": "parked"},
        {"name": "CK_t / CK_c (per sub-channel)",
         "direction": "input",
         "purpose": "Differential clock; command/address timing reference.",
         "active_levels": "differential", "idle_level": "running"},
        {"name": "CA[13:0] + CS_n (per sub-channel)",
         "direction": "input",
         "purpose": "Command/address bus (2-cycle commands) and chip select.",
         "active_levels": "CMOS", "idle_level": "deselected"},
    ]
    f["logical_signaling_levels"] = [
        {"name": "Idle / precharged", "meaning": "Banks precharged; CKE high; "
         "refresh within tREFI; DQ tri-stated."},
        {"name": "Active access", "meaning": "Row open; READ/WRITE BL16 bursts "
         "on DQ/DQS."},
    ]
    f["packet_types_summary"] = [
        {"class": "Core command", "members": list(_CORE_COMMANDS),
         "count": len(_CORE_COMMANDS)},
        {"class": "Refresh", "members": ["REFab", "REFsb"], "count": 2},
        {"class": "Training", "members": ["MPC", "MRW", "MRR"], "count": 3},
    ]
    cc = _ensure_dict(f, "channel_counts")
    cc.update({
        "sub_channels_per_dimm": _SUBCHANNELS_PER_DIMM,
        "sub_channel_data_bits": _SUBCHANNEL_DATA_BITS,
        "sub_channel_ecc_bits": _SUBCHANNEL_ECC_BITS,
        "ca_bus_bits": _CA_BUS_BITS,
        "ca_command_cycles": _CA_COMMAND_CYCLES,
        "banks_x8": _BANKS_X8,
        "bank_groups_x8": _BANK_GROUPS_X8,
        "burst_length": _BURST_LENGTH,
        "core_command_count": len(_CORE_COMMANDS),
        "max_data_rate_MTps": _MAX_DATA_RATE_MTPS,
    })
    f["power_pins"] = [
        {"name": "VDD", "voltage": _VDD, "purpose": "Core supply."},
        {"name": "VDDQ", "voltage": _VDDQ, "purpose": "DQ IO supply."},
        {"name": "VPP", "voltage": _VPP, "purpose": "Wordline-boost supply."},
        {"name": "VSS", "voltage": "0 V", "purpose": "Ground."},
    ]
    f["global_signals"] = [
        {"name": "RESET_n", "purpose": "Asynchronous device reset."},
        {"name": "CKE", "purpose": "Clock enable / power-down control."},
        {"name": "ALERT_n", "purpose": "Write-CRC and command/address parity "
         "error alert."},
        {"name": "ZQ", "purpose": "External calibration reference resistor."},
        {"name": "SPD-hub sideband", "purpose": "I2C/I3C to PMIC / RCD / "
         "temperature sensors."},
    ]
    # Force-overwrite the dependency_graph (a sibling memory synth may have
    # left an HBM3 16-channel / LPDDR5 graph here).
    f["dependency_graph"] = {
        "common_rule": "Within a sub-channel, commands are issued as 2-cycle CA "
        "transactions on CA[13:0] qualified by CS_n and timed to CK_t/CK_c. A "
        "row must be ACTIVATEd (tRCD) before a column access and PRECHARGEd "
        "(tRP) before re-activation. The two sub-channels (A and B) are "
        "completely independent — traffic on one has no dependency on the "
        "other.",
        "data_dependency": "A READ/WRITE requires: (1) the device initialized "
        "and trained (CA / read / write, DFE tap, VrefDQ/VrefCA, ZQ), (2) the "
        "target row open in the addressed bank, (3) bank-group spacing (tCCD_L "
        "within a group, tCCD_S across groups). Read data returns after CAS "
        "latency on DQ/DQS (double data rate) with on-die ECC applied; refresh "
        "(REFab/REFsb) must be maintained within tREFI.",
    }
    f["handshake_pairs"] = [
        {"name": "ACTIVATE / column access", "from": "controller",
         "to": "DRAM", "rule": "ACTIVATE opens a row; after tRCD a READ/WRITE "
                 "column access is allowed."},
        {"name": "WRITE / tWR / PRECHARGE", "from": "controller", "to": "DRAM",
         "rule": "tWR must elapse after the last write beat before PRECHARGE."},
        {"name": "MRW / MRR", "from": "controller", "to": "DRAM",
         "rule": "Mode-register write/read over the 2-cycle CA protocol."},
        {"name": "ALERT_n", "from": "DRAM", "to": "controller",
         "rule": "Signals a write-CRC or CA-parity error for retry/recovery."},
    ]
    f["channel_counts_per_x16_channel"] = {
        "note": "DDR5 organizes a DIMM into two independent sub-channels rather "
                "than HBM-style per-die channels; an x16 device has 16 banks in "
                "4 bank groups.",
        "banks_x16": _BANKS_X16,
        "bank_groups_x16": _BANK_GROUPS_X16,
    }
    f["ordering_rules"] = {
        "command_order": "Commands within a sub-channel are ordered to CK; the "
        "controller enforces tRCD/tRP/tRAS/tCCD/tWR/CL/tRFC.",
        "sub_channel": "The two sub-channels are independent and may be "
        "scheduled concurrently.",
        "bank_group": "Back-to-back accesses to different bank groups use "
        "tCCD_S; same-group accesses use the longer tCCD_L.",
        "data_order": "BL16 beats are returned/accepted in burst order on "
        "DQ/DQS (double data rate).",
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L18 — interconnect topology.
# ----------------------------------------------------------------------
def _l18(gd: Path) -> None:
    p = gd / "L18_INTERCONNECT_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["topology_type"] = (
        "Parallel point-to-point memory bus from a controller to the DRAMs of "
        "a DIMM, split into two INDEPENDENT 32-bit (40-bit ECC) sub-channels. "
        "Each sub-channel drives its DRAMs over a shared CA[13:0] + CS_n bus "
        "and CK_t/CK_c, with DQ[31:0] on DQS_t/DQS_c. RDIMMs interpose an RCD "
        "on CK/CA; there is no serial fabric or switch.")
    f["supported_topologies"] = [
        {"name": "Two independent sub-channels", "description": "Each DIMM "
         "presents Sub-Channel A and Sub-Channel B (32/40-bit each), addressed "
         "independently."},
        {"name": "UDIMM / SODIMM", "description": "Unbuffered; controller "
         "drives CK/CA directly to the DRAMs."},
        {"name": "RDIMM", "description": "A Registering Clock Driver (RCD) "
         "re-drives CK/CA to the DRAMs."},
        {"name": "LRDIMM", "description": "RCD plus data buffers (DB) on the DQ "
         "lanes for the highest loading."},
        {"name": "Multi-rank", "description": "Multiple ranks per sub-channel "
         "selected by CS_n."},
    ]
    f["master_slave_role_summary"] = [
        {"role": "Memory controller (host)", "description": "Issues 2-cycle CA "
         "commands, schedules the two sub-channels, and runs training."},
        {"role": "DDR5 SDRAM device", "description": "Stores data; provides "
         "DFE, on-die ECC, banks/bank-groups, and mode registers."},
        {"role": "RCD (RDIMM)", "description": "Registers and re-drives CK/CA "
         "to the DRAMs."},
        {"role": "PMIC / SPD hub", "description": "On-module power generation "
         "and configuration over the sideband bus."},
    ]
    f["interconnect_role"] = (
        "DDR5 is a parallel synchronous memory interface. The controller is the "
        "single master; the DRAMs are slaves. Each DIMM's two sub-channels are "
        "scheduled independently for concurrency. Addressing is by {sub-channel, "
        "rank (CS_n), bank group, bank, row, column}; the RCD buffers CK/CA on "
        "registered modules.")
    f["routing_methods"] = ["fly-by CK/CA routing", "RCD-buffered CK/CA "
                            "(RDIMM)", "point-to-point DQ per byte lane"]
    f["ordering_guarantees"] = {
        "sub_channel": "Each sub-channel orders its own commands to CK; the two "
        "are independent.",
        "bank_group": "tCCD_S/tCCD_L spacing across/within bank groups.",
        "burst": "BL16 beats are ordered within a burst on DQ/DQS.",
    }
    f["memory_vs_peripheral_regions"] = (
        "DDR5 IS the main-memory region: it is directly memory-mapped by the "
        "controller, addressed by {sub-channel, rank, bank group, bank, row, "
        "column}, not by a peripheral register address. Mode registers (MRW/"
        "MRR) configure the device but are not part of the data address space.")
    dc = _ensure_dict(f, "device_classification")
    dc["controller"] = "Memory controller / host (master)."
    dc["dram"] = "DDR5 SDRAM device (x4 / x8 / x16) (slave)."
    dc["rcd"] = "Registering Clock Driver on RDIMM/LRDIMM."
    dc["pmic_spd"] = "On-module PMIC and SPD hub."
    f["default_signal_values_evidence_tables"] = [
        "Two-sub-channel DIMM block diagram",
        "Bank / bank-group organization figure (32 banks / 8 groups)",
        "RDIMM RCD CK/CA buffering figure",
        "Module power figure (PMIC 12 V -> 1.1 V / 1.8 V, SPD hub)",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L19 — constraints / PDK.
# ----------------------------------------------------------------------
def _l19(gd: Path) -> None:
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["constraints_present"] = True
    f["electrical_channel_constraints"] = {
        "signaling": "parallel source-synchronous double-data-rate (single-"
                     "ended POD DQ; differential CK_t/CK_c and DQS_t/DQS_c)",
        "data_rates_MTps": list(_SPEED_BINS_MTPS),
        "max_data_rate_MTps": _MAX_DATA_RATE_MTPS,
        "supply_voltages": {"VDD": _VDD, "VDDQ": _VDDQ, "VPP": _VPP},
        "equalization": "DFE on DQ receivers; Duty-Cycle Adjuster",
        "reference": "internal VrefDQ / VrefCA (trained)",
        "sub_channels_per_dimm": _SUBCHANNELS_PER_DIMM,
        "sub_channel_data_bits": _SUBCHANNEL_DATA_BITS,
        "burst_length": _BURST_LENGTH,
        "ca_command_cycles": _CA_COMMAND_CYCLES,
    }
    f["notes"] = (
        "DDR5 (JESD79-5) is a JEDEC DRAM interface standard: it fixes the "
        "two-sub-channel DIMM architecture, the 1.1 V VDD/VDDQ (1.8 V VPP) "
        "rails, the DFE/Duty-Cycle/VrefDQ/VrefCA signal-integrity model, the "
        "2-cycle CA protocol, BL16, 32 banks / 8 bank groups with same-bank "
        "refresh, on-die ECC, and the mode-register set. It does NOT impose "
        "PDK-specific SDC / floorplan constraints; the SerDes-class DQ "
        "electrical characterization, the module PCB / RCD / PMIC design, and "
        "the controller PHY are board / implementation concerns. The "
        "interoperability-critical constraints are the timing parameters, "
        "training, DFE/Vref, and the refresh schedule.")
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
    f["dft_present"] = "partial"
    f["in_band_test_facilities"] = [
        {"name": "Mode Register Read (MRR)", "purpose": "Read status, on-die-"
         "ECC error counts, and ECS results."},
        {"name": "MPC training/feature modes", "purpose": "Exercise DFE, Vref, "
         "ZQ, and read/write training and read back results."},
        {"name": "ALERT_n", "purpose": "Observe write-CRC and CA-parity "
         "errors."},
        {"name": "On-die-ECC / ECS reporting", "purpose": "Single-bit error "
         "and scrub observability via mode registers."},
        {"name": "ZQ calibration status", "purpose": "Driver / ODT impedance "
         "calibration observability."},
    ]
    f["internal_diagnostics_observability"] = [
        "Per-sub-channel training results (DFE taps, VrefDQ/VrefCA centers, "
        "read/write deskew).",
        "On-die-ECC single-bit error counts and ECS status.",
        "Write-CRC / CA-parity error indications (ALERT_n).",
        "Refresh-management (RFM) state.",
        "ZQ calibration result.",
    ]
    f["out_of_band_test_facilities"] = [
        "JEDEC DDR5 compliance / interoperability testing.",
        "Vendor DRAM-die ATE wafer/package test (implementation-defined).",
        "Module-level SPD-hub / PMIC / RCD bring-up over the sideband bus.",
    ]
    f["notes"] = (
        "DDR5's protocol-level DFT surface is the mode registers (MRR/MRW), "
        "MPC-driven training feedback, on-die-ECC / ECS reporting, ALERT_n for "
        "write-CRC and CA-parity, and ZQ calibration. Chip-level JTAG / scan / "
        "BIST remain DRAM-vendor concerns; conformance is established by JEDEC "
        "compliance testing.")
    _write(p, d)


# ----------------------------------------------------------------------
# L21 — power intent.
# ----------------------------------------------------------------------
def _l21(gd: Path) -> None:
    p = gd / "L21_POWER_INTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["power_intent_present"] = True
    f["power_management_states"] = [
        {"state": "Active", "name": "Active", "description": "Device trained "
         "and servicing commands on both sub-channels."},
        {"state": "Power-down", "name": "Power-down", "description": "CKE-"
         "controlled power-down with fast exit."},
        {"state": "Self-refresh", "name": "Self-refresh", "description": "Low-"
         "power retention with internal refresh."},
    ]
    f["wakeup_mechanism"] = (
        "CKE controls power-down entry/exit; SELF REFRESH ENTRY/EXIT controls "
        "the low-power retention state. Exit returns to active operation; at "
        "high speed bins some re-training may be required.")
    f["power_rails"] = [
        {"rail": "VDD", "voltage": _VDD, "purpose": "Core supply (on a DIMM, "
         "generated by the on-module PMIC from 12 V)."},
        {"rail": "VDDQ", "voltage": _VDDQ, "purpose": "DQ IO supply."},
        {"rail": "VPP", "voltage": _VPP, "purpose": "Wordline-boost supply."},
        {"rail": "VSS", "voltage": "0 V", "purpose": "Ground."},
    ]
    f["dimm_pmic"] = (
        "DDR5 moves power management onto the DIMM: an on-module Power "
        "Management IC (PMIC) regulates the 12 V host supply down to the 1.1 V "
        "VDD/VDDQ and 1.8 V VPP rails locally, improving rail integrity and "
        "per-DIMM power control (DDR4 DIMMs had no on-module PMIC).")
    f["ddr5_power_considerations"] = (
        "Lower 1.1 V VDD/VDDQ (vs DDR4's 1.2 V) reduces dynamic and IO power; "
        "the on-module PMIC, fine-granularity / temperature-controlled "
        "refresh, same-bank refresh, power-down, and self-refresh manage "
        "energy; on-die ECC trades a little power for reliability.")
    f["notes"] = (
        "DDR5's power intent centers on the on-module PMIC generating 1.1 V / "
        "1.8 V rails from 12 V, the 1.1 V VDD/VDDQ operating point, CKE power-"
        "down and self-refresh states, and refresh-management options. "
        "Fine-grained power-domain partitioning of the DRAM die is a vendor "
        "concern.")
    _write(p, d)


# ----------------------------------------------------------------------
# L22 — verification plan.
# ----------------------------------------------------------------------
def _l22(gd: Path) -> None:
    p = gd / "L22_VERIFICATION_PLAN.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["verification_plan_present"] = "implicit"
    f["verification_categories_derived_from_spec"] = [
        "Power-up / init / RESET_n at 1.1 V VDD/VDDQ, 1.8 V VPP.",
        "Training — CA training, write leveling, read/write training (DFE tap, "
        "VrefDQ/VrefCA), ZQ calibration via MPC.",
        "Two-sub-channel independence — concurrent unrelated A/B access.",
        "Row cycle — ACTIVATE/READ/WRITE/PRECHARGE; tRCD/tRP/tRAS/tWR/CL.",
        "Bank groups — tCCD_L vs tCCD_S; 32 banks / 8 groups.",
        "Refresh — REFab and REFsb; tRFC/tREFI; fine-granularity / "
        "temperature.",
        "Burst — BL16 and BL32 burst-chop.",
        "On-die ECC — single-bit correction; Error Check and Scrub (ECS).",
        "Integrity — write CRC and CA parity on ALERT_n.",
        "Mode registers — MRW/MRR across the expanded MR space.",
        "Speed-bin sweep — DDR5-3200 .. DDR5-8400; double-data-rate capture.",
        "Module — PMIC rails, SPD-hub config, RCD CK/CA re-drive (RDIMM).",
    ]
    f["notes"] = (
        "DDR5 does not ship an embedded testbench, but JESD79-5 implies a "
        "verification plan spanning power-up/training, the two independent "
        "sub-channels, the row/column command cycle and timing parameters, "
        "bank-group scheduling, all-bank and same-bank refresh, BL16 bursts, "
        "on-die ECC / ECS, write-CRC / CA-parity integrity, the mode-register "
        "set, the speed-bin range, and the module PMIC/SPD-hub/RCD. JEDEC "
        "compliance testing supplies the formal suite.")
    _write(p, d)


# ----------------------------------------------------------------------
# L23 — security requirements.
# ----------------------------------------------------------------------
def _l23(gd: Path) -> None:
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["security_requirements_present"] = False
    f["anti_corruption_features"] = [
        "On-die ECC corrects single-bit errors inside every DDR5 device.",
        "Error Check and Scrub (ECS) scrubs accumulated single-bit errors.",
        "Optional write-data CRC detects write corruption (ALERT_n).",
        "Command/Address parity detects CA-bus corruption (ALERT_n).",
        "Refresh management (RFM) bounds row-hammer / refresh-stress effects.",
    ]
    f["anti_tampering_features"] = []
    f["confidentiality_features"] = []
    f["authentication_features"] = []
    f["future_security_pointers"] = [
        "DDR5's base data path carries no cryptographic confidentiality or "
        "authentication; on-die ECC, write CRC, and CA parity are anti-"
        "corruption only.",
        "Memory encryption / integrity (e.g. host-side total-memory-encryption "
        "engines) and refresh-management mitigations against row-hammer are "
        "layered above or alongside the DDR5 transport.",
    ]
    f["notes"] = (
        "DDR5 is a JEDEC DRAM interface: its built-in protections are anti-"
        "corruption / reliability (on-die ECC, ECS, write CRC, CA parity, "
        "refresh management) rather than security. Data on the bus is "
        "plaintext; confidentiality and authentication are provided by host-"
        "side memory-encryption engines above the DDR5 transport, not by the "
        "base protocol.")
    _write(p, d)
