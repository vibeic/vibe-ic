"""DDR4 SDRAM protocol synth helper (JEDEC JESD79-4) — protocol class #58.

ic_class-gated overlay for the DDR4 SDRAM structural signature: the
mainstream commodity double-data-rate fourth-generation synchronous DRAM
standardized by JEDEC as JESD79-4. DDR4 is a single 64-bit (72-bit ECC)
channel per module, x4/x8/x16, at VDD/VDDQ = 1.2 V, that adds — relative
to DDR3 (JESD79-3) — Bank Groups (4 BG x 4 banks = 16 banks for x4/x8),
gear-down (1/2-rate command/address) mode, Data Bus Inversion (DBI),
on-die VrefDQ generation with VrefDQ training, write CRC on the data bus,
command/address (CA) parity with the ALERT_n pin, and the ACT_n-flag
command truth table (RAS_n/A16, CAS_n/A15, WE_n/A14 multiplexed). Burst
length BL8 / BC4 (on-the-fly). Speed bins DDR4-1600 .. DDR4-3200. DLL
based. RDIMM uses an RCD (Registering Clock Driver); LRDIMM adds Data
Buffers (DB). Mode registers MR0..MR6. Applies the JEDEC JESD79-4
spec-canonical content to L1-L23.

Doctrine — GENERAL not keyword: detection uses canonical STRUCTURAL
signatures (JESD79-4 + 1.2 V + bank groups + gear-down + write-CRC + CA
parity + DBI + on-die VrefDQ) read from the L-doc / input_doc CONTENT
blob only. It NEVER reads the input-document filename or the benchmark
folder name. The runner injects protocol NAMES into foreign docs' L-docs
(generic memory vocabulary + L9 interface_types), so a bare ``"DDR4" in
blob`` would mis-fire — every True path therefore requires a DDR4-specific
STRUCTURAL fact, not a name token alone.

Sibling disambiguation — the DDRx / memory family (MUTEX against all):
  * DDR3-primary (JESD79-3, 1.5 V, no bank groups, single-rank DLL,
    external VREFDQ, no write CRC / CA parity / gear-down): DEFER. DDR3
    lacks bank groups, gear-down, write CRC, CA parity, and on-die VrefDQ.
  * DDR5-primary (JESD79-5, two independent 32-bit sub-channels, decision
    feedback equalization / DFE, on-die ECC, on-DIMM PMIC / SPD hub,
    same-bank refresh, 1.1 V): DEFER. DDR4 is a SINGLE 64-bit channel,
    no DFE, no on-die ECC, no DIMM PMIC.
  * LPDDR5-primary (JESD209-5, low-power mobile, dedicated full-speed
    Write Clock WCK): DEFER.
  * HBM3-primary (JESD238, TSV-stacked, 1024-bit-wide): DEFER.

Public entry: ``apply_ddr4_synth(generated_docs_dir, is_ddr4, ddr4_ic_name)``.
Module-level ``is_ddr4(blob)`` is the content-only detector with the MUTEX.
"""
from __future__ import annotations

import json
import re
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

# Canonical DDR4 facts (JEDEC JESD79-4 DDR4 SDRAM).
_DATA_WIDTH_BITS = 64               # single channel, non-ECC
_DATA_WIDTH_BITS_ECC = 72
_VDD_V = 1.2
_VDDQ_V = 1.2
_VPP_V = 2.5
_BANK_GROUPS_X4_X8 = 4
_BANKS_PER_GROUP = 4
_BANKS_X4_X8 = 16                   # 4 BG x 4 banks
_BANK_GROUPS_X16 = 2
_BANKS_X16 = 8
_SPEED_BINS_MTS = [1600, 1866, 2133, 2400, 2666, 2933, 3200]
_MAX_SPEED_MTS = 3200
_WRITE_CRC_BITS = 8
_BURST_LENGTHS = ["BL8", "BC4"]
_MODE_REGISTERS = ["MR0", "MR1", "MR2", "MR3", "MR4", "MR5", "MR6"]
_DEVICE_WIDTHS = ["x4", "x8", "x16"]
_COMMANDS = [
    "ACTIVATE", "READ", "WRITE", "PRECHARGE", "REFRESH", "MRS",
    "ZQ CALIBRATION", "NOP", "DESELECT",
]


# Tokens proving a DDR4-specific structural feature (NOT a bare name).
_RE_JESD79_4 = re.compile(r"\bjesd\s*79[-\s]?4\b", re.I)
_RE_DDR4 = re.compile(r"\bddr4\b", re.I)
_RE_DDR3 = re.compile(r"\bddr3\b", re.I)
_RE_DDR5 = re.compile(r"\bddr5\b", re.I)
_RE_LPDDR5 = re.compile(r"\blpddr5\b", re.I)
_RE_HBM3 = re.compile(r"\bhbm3\b", re.I)
_RE_WCK = re.compile(r"\bwck\b", re.I)


def is_ddr4(blob: str) -> bool:
    """Content-only DDR4 detector with a DDR3/DDR5/LPDDR5/HBM3 sibling MUTEX.

    Fire on the JESD79-4 DDR4 structural signature: a 1.2 V single 64-bit
    channel SDRAM that carries bank groups + (gear-down OR write CRC OR CA
    parity OR Data Bus Inversion OR on-die VrefDQ) — features new in DDR4.
    A bare ``"DDR4"`` name token is NOT sufficient (the runner injects
    memory vocabulary into foreign docs); a DDR4-specific structural fact
    is always required. Defer when the doc is DDR3-primary, DDR5-primary,
    LPDDR5-primary, or HBM3-primary. Reads ONLY the spec text ``blob`` —
    never a filename or benchmark name.
    """
    if not blob:
        return False
    low = blob.lower()

    # ---- DDR4-specific structural features (NEW vs DDR3). ----
    bank_groups = ("bank group" in low or "bank-group" in low
                   or "bank groups" in low or re.search(r"\bbg0\b", low) is not None)
    gear_down = ("gear-down" in low or "gear down" in low or "geardown" in low)
    # write CRC — the DDR4-specific data-bus integrity feature. Require the
    # exact "write crc" phrase; a loose "crc + data bus" fallback wrongly fired
    # on a DDR3 doc's general CRC prose.
    write_crc = ("write crc" in low or "write-crc" in low)
    ca_parity = ("ca parity" in low or "c/a parity" in low
                 or "command/address parity" in low
                 or "command address parity" in low)
    dbi = ("data bus inversion" in low or "dbi_n" in low
           or re.search(r"\bdbi\b", low) is not None)
    vrefdq_internal = (
        ("vrefdq" in low or "vref dq" in low or "vref-dq" in low)
        and ("internal" in low or "training" in low or "on-die" in low
             or "on die" in low))
    act_n_flag = ("act_n" in low and ("ras_n/a16" in low or "ras_n/a"  in low
                  or "ras_n / a16" in low or "activate command flag" in low))

    structural_features = [
        gear_down, write_crc, ca_parity, dbi, vrefdq_internal, act_n_flag,
    ]
    feature_count = sum(1 for f in structural_features if f)

    # Voltage signature: DDR4 is 1.2 V (DDR3 is 1.5 V).
    one_point_two_v = ("1.2 v" in low or "1.2v" in low or "vdd = 1.2" in low
                       or "vddq = 1.2" in low or "1.2-v" in low)
    one_point_five_v = ("1.5 v" in low or "1.5v" in low or "1.5-v" in low)

    jesd79_4 = bool(_RE_JESD79_4.search(blob))
    ddr4_name = bool(_RE_DDR4.search(blob))
    has_ddr4_marker = jesd79_4 or ddr4_name

    # Name-DOMINANCE primary-subject signal. A doc that is primarily ABOUT
    # DDR4 mentions "DDR4" far more often than its siblings; a sibling-primary
    # doc inverts this. This is the general discriminator that separates a
    # DDR4 spec (which references DDR5/DDR3 in comparison sections) from a
    # DDR5 spec (which references DDR4). Counted on the CONTENT blob only.
    n_ddr4 = len(_RE_DDR4.findall(blob))
    n_ddr5 = len(_RE_DDR5.findall(blob))
    n_ddr3 = len(_RE_DDR3.findall(blob))
    ddr4_dominant_over_ddr5 = n_ddr4 >= 2 * max(n_ddr5, 1) and n_ddr4 > n_ddr5

    # ---- DDR4-PRIMARY fast path (evaluated FIRST). ----
    # When DDR4's own spec id is present, the DDR4 STRUCTURAL cluster is met
    # (bank groups + >=2 DDR4-only features + 1.2 V), AND the DDR4 name
    # dominates DDR5, the doc is unambiguously DDR4-primary — even though its
    # comparison sections enumerate DDR5/LPDDR5/HBM3 features. This wins over
    # the sibling MUTEXes below so a DDR4 spec's "must-not-have DDR5 features"
    # list cannot make it defer. (General — DDR4 spec id + DDR4 structural
    # cluster + DDR4 name dominance, never a filename or benchmark name.)
    if (jesd79_4 and bank_groups and feature_count >= 2 and one_point_two_v
            and ddr4_dominant_over_ddr5):
        return True

    # ---- sibling-PRIMARY MUTEXes (with a STRONG cluster + non-dominance). ----
    # A DDR4-primary spec legitimately references its siblings in comparison
    # sections, so a single sibling token (e.g. "sub-channel") is NOT enough
    # to defer. Each MUTEX requires the sibling's spec id AND a STRONG,
    # multi-token structural cluster that a DDR4 comparison paragraph does NOT
    # carry in full. This both (a) lets a true sibling-primary doc win and
    # (b) keeps the DDR4-primary doc from deferring on an incidental mention.
    # General — keys off the sibling's STRUCTURAL cluster + spec id, not a
    # benchmark name.

    # DDR5-PRIMARY: a DDR5 spec carries, as its OWN device, the two-32-bit
    # sub-channel split AND a cluster of DDR5-unique receiver/module features.
    # The strong gate needs the sub-channel split AND >=2 of {DFE, on-die ECC,
    # DIMM PMIC, same-bank refresh} — DDR4-unique-feature tokens ("decision
    # feedback" alone) are deliberately weighted so a DDR4 doc's one-line
    # comparison cannot reach the threshold. (Detector-mutex doctrine: a true
    # DDR5 spec dwells on all of these; a DDR4 spec names at most one or two.)
    ddr5_id = bool(_RE_DDR5.search(blob)) or re.search(r"jesd\s*79[-\s]?5", blob, re.I) is not None
    ddr5_subchannel = ("sub-channel" in low or "sub channel" in low
                       or "subchannel" in low)
    ddr5_other = sum(1 for t in (
        re.search(r"\bdfe\b", low) is not None,
        ("on-die ecc" in low or "on die ecc" in low),
        ("pmic" in low and "dimm" in low),
        ("same-bank refresh" in low or "same bank refresh" in low),
        ("decision feedback equalization" in low),
    ) if t)
    ddr5_strong = ddr5_id and ddr5_subchannel and ddr5_other >= 3
    if ddr5_strong and not ddr4_dominant_over_ddr5:
        return False

    # LPDDR5-PRIMARY: low-power mobile DRAM with a dedicated full-speed WCK.
    lpddr5_primary = (
        (bool(_RE_LPDDR5.search(blob)) or re.search(r"jesd\s*209[-\s]?5", blob, re.I) is not None)
        and (bool(_RE_WCK.search(blob)) or "write clock" in low)
        and ("low-power" in low or "low power mobile" in low or "mobile" in low))
    if lpddr5_primary:
        return False

    # HBM3-PRIMARY: TSV-stacked, 1024-bit-wide stacked 3D DRAM. Requires the
    # stacked-memory id AND the wide-interface / TSV structural signature.
    hbm3_primary = (
        (bool(_RE_HBM3.search(blob)) or re.search(r"jesd\s*238\b", blob, re.I) is not None)
        and ("high bandwidth memory" in low or "1024-bit" in low
             or "1024 bit" in low)
        and ("through-silicon" in low or "through silicon" in low
             or "tsv" in low or "pseudo channel" in low
             or "pseudo-channel" in low or "interposer" in low))
    if hbm3_primary:
        return False

    # ---- DDR4-PRIMARY fast path (after the strong sibling MUTEXes). ----
    # A DDR4-primary spec carries JESD79-4 as its document id AND the full
    # DDR4 structural cluster (bank groups + >=2 DDR4-only features + 1.2 V).
    # Because the strong sibling MUTEXes already returned above, a DDR4 doc
    # that merely references DDR5/LPDDR5/HBM3 reaches here and matches.
    # (General — keys off the DDR4 STRUCTURAL cluster + DDR4's own spec id.)
    ddr4_primary = (
        jesd79_4 and bank_groups and feature_count >= 2 and one_point_two_v)
    if ddr4_primary:
        return True

    # ---- DDR3-PRIMARY MUTEX: a true DDR3 doc lacks DDR4's new features. ----
    # DDR3 (1.5 V, no bank groups, external VREFDQ, no write CRC / CA parity /
    # gear-down / DBI). If the doc names DDR3 AND carries the DDR3 1.5 V rail
    # AND none of DDR4's structural features are present, defer.
    ddr3_name = bool(_RE_DDR3.search(blob)) or re.search(r"jesd\s*79[-\s]?3", blob, re.I) is not None
    ddr3_primary = (
        ddr3_name and not has_ddr4_marker
        and not bank_groups and feature_count == 0)
    if ddr3_primary:
        return False

    # ---- DDR4 True paths. ----
    # Every path requires the DDR4 STRUCTURAL CLUSTER — bank groups + at least
    # TWO DDR4-only features (gear-down / write CRC / CA parity / DBI / on-die
    # VrefDQ / ACT_n flag). One feature is NOT enough: a DDR3 (or other
    # sibling) spec that merely REFERENCES DDR4 in a lineage / comparison
    # section can incidentally carry "JESD79-4" + "bank group" + a single
    # stray feature token (e.g. "VrefDQ training"), and must NOT fire. The
    # >=2-feature gate is the general structural discriminator that the runner
    # superset (input_doc + every generated L-doc) of a DDR3 benchmark cannot
    # meet, because DDR3's OWN device has none of the DDR4-new features.
    # Path 1: explicit JESD79-4 spec id + bank groups + >=2 DDR4 features.
    if jesd79_4 and bank_groups and feature_count >= 2:
        return True
    # Path 2: DDR4 name + bank groups + >=2 DDR4 features.
    if has_ddr4_marker and bank_groups and feature_count >= 2:
        return True
    # Path 3: no name token but the DDR4 structural cluster is unmistakable:
    # bank groups + 1.2 V + two or more DDR4-only features.
    if bank_groups and one_point_two_v and feature_count >= 2:
        return True
    # Path 4: DDR4 name + 1.2 V (not 1.5 V) + two or more DDR4 features.
    if (has_ddr4_marker and one_point_two_v and not one_point_five_v
            and feature_count >= 2):
        return True

    return False


def apply_ddr4_synth(generated_docs_dir: Path, is_ddr4_flag: bool,
                     ddr4_ic_name: Optional[str]) -> None:
    """Apply JEDEC JESD79-4 DDR4 SDRAM synth when the DDR4 signature matched.

    Force-assigns (NOT setdefault) every DDR4 key across L1-L23 so that a
    DDR3-stamped base (the DDR3 synth fires first on a DDR4 doc because DDR4
    extends DDR3's command model) is fully overridden to DDR4 content. The
    ic_name is written across all 24 docs, and L17 is force-overwritten.
    """
    if not is_ddr4_flag:
        return
    gd = Path(generated_docs_dir)

    # --- Force ic_name across ALL 24 docs FIRST (main + fields docs). ---
    if ddr4_ic_name is not None:
        for n in _MAIN_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                d["ic_name"] = ddr4_ic_name
                _write(q, d)
        for n in _FIELDS_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                f = _ensure_dict(d, "fields")
                f["ic_name"] = ddr4_ic_name
                d["ic_name"] = ddr4_ic_name
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
# L1 — DDR4 datasheet header + headline facts.
# ----------------------------------------------------------------------
def _l1(gd: Path) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    d["document_title"] = "DDR4 SDRAM Standard"
    d["document_number"] = "JESD79-4"
    d["version"] = "JEDEC Standard No. 79-4 (JESD79-4) — DDR4 SDRAM"
    d["revised_date"] = "JESD79-4 DDR4 SDRAM"
    d["manufacturer"] = "JEDEC Solid State Technology Association"
    d["publisher"] = "JEDEC Solid State Technology Association"
    d["copyright"] = "© JEDEC"
    d["abstract"] = (
        "DDR4 SDRAM (Double Data Rate fourth-generation Synchronous Dynamic "
        "Random Access Memory), JEDEC Standard JESD79-4, is the mainstream "
        "commodity main-memory DRAM generation that succeeds DDR3 (JESD79-3) "
        "and precedes DDR5 (JESD79-5). A DDR4 SDRAM is a high-speed, clocked, "
        "double-data-rate dynamic memory: commands and addresses are captured "
        "on the rising edge of the differential clock CK_t/CK_c and data DQ is "
        "transferred on both edges of the differential data strobe "
        "DQS_t/DQS_c. DDR4 defines a single 64-bit data channel per module "
        "(72-bit with ECC), in x4/x8/x16 device organizations, at VDD = VDDQ = "
        "1.2 V (VPP = 2.5 V). Relative to DDR3, DDR4 adds Bank Groups, "
        "gear-down (1/2-rate command/address) mode, Data Bus Inversion (DBI), "
        "internal (on-die) VrefDQ generation with VrefDQ training, write CRC "
        "on the data bus, and command/address (CA) parity with the ALERT_n "
        "pin. DDR4 is DLL-based with speed bins DDR4-1600 through DDR4-3200, a "
        "burst length of BL8 / BC4 (on-the-fly), and the MR0..MR6 mode "
        "registers programmed by the MRS command.")
    d["keywords"] = [
        "DDR4", "DDR4 SDRAM", "JESD79-4", "JEDEC", "SDRAM", "double data rate",
        "bank group", "BG0", "BG1", "gear-down mode", "Data Bus Inversion",
        "DBI", "write CRC", "CA parity", "command/address parity", "ALERT_n",
        "VrefDQ training", "internal VREFDQ", "BL8", "BC4", "burst chop",
        "mode register", "MR0", "MR6", "ACT_n", "RAS_n/A16", "CAS_n/A15",
        "WE_n/A14", "DQS_t", "DQS_c", "CK_t", "CK_c", "ODT", "Rtt_PARK",
        "ZQ calibration", "RZQ", "1.2 V", "VPP", "RCD", "data buffer",
        "RDIMM", "LRDIMM", "DDR4-1600", "DDR4-3200", "tRCD", "tRP", "tRAS",
        "tCCD_L", "tCCD_S", "x4", "x8", "x16",
    ]
    d["external_pins"] = [
        "CK_t / CK_c: differential input clock (commands captured on the "
        "rising edge).",
        "DQ[3:0]/[7:0]/[15:0]: bidirectional data (x4/x8/x16); double data "
        "rate on DQS edges.",
        "DQS_t / DQS_c: differential bidirectional data strobe (one pair per "
        "byte; two pairs on x16).",
        "DM_n / DBI_n: data mask / Data Bus Inversion (shared pin per byte on "
        "x8/x16).",
        "ACT_n: Activate command flag; RAS_n/A16, CAS_n/A15, WE_n/A14 "
        "multiplexed command / high address.",
        "BG0, BG1: bank group address; BA0, BA1: bank address.",
        "A[13:0] address; A10/AP auto-precharge; A12/BC_n burst-chop "
        "on-the-fly.",
        "PAR: command/address parity input; ALERT_n: CA-parity / write-CRC / "
        "connectivity alert output.",
        "ODT: on-die termination control; ZQ: external RZQ (240 ohm) "
        "calibration reference; RESET_n.",
        "VDD = 1.2 V, VDDQ = 1.2 V, VPP = 2.5 V, VREFCA; VREFDQ generated "
        "internally (on-die).",
    ]
    d["data_width_bits"] = _DATA_WIDTH_BITS
    d["data_width_bits_ecc"] = _DATA_WIDTH_BITS_ECC
    d["device_widths"] = list(_DEVICE_WIDTHS)
    d["vdd_volts"] = _VDD_V
    d["vddq_volts"] = _VDDQ_V
    d["vpp_volts"] = _VPP_V
    d["speed_bins_MTps"] = list(_SPEED_BINS_MTS)
    d["max_data_rate_MTps"] = _MAX_SPEED_MTS
    d["bank_groups_x4_x8"] = _BANK_GROUPS_X4_X8
    d["banks_x4_x8"] = _BANKS_X4_X8
    d["bank_groups_x16"] = _BANK_GROUPS_X16
    d["banks_x16"] = _BANKS_X16
    d["density_organization_table"] = {
        "header_columns": ["Width", "Bank Groups", "Banks", "DQS pairs",
                           "DM_n/DBI_n"],
        "rows": [
            ["x4", "4 (BG0/BG1)", "16", "1", "no"],
            ["x8", "4 (BG0/BG1)", "16", "1", "yes"],
            ["x16", "2 (BG0)", "8", "2 (LDQS/UDQS)", "yes (2)"],
        ],
    }
    d["speed_grade_summary"] = (
        "DDR4 speed bins (data rate in MT/s, twice the CK frequency): "
        "DDR4-1600, DDR4-1866, DDR4-2133, DDR4-2400, DDR4-2666, DDR4-2933, "
        "DDR4-3200. Each bin defines CL/CWL, tRCD, tRP, and tRAS in the "
        "speed-bin tables; DDR4 is DLL-based.")
    d["key_features"] = [
        "Single 64-bit (72-bit ECC) data channel per module; x4/x8/x16 "
        "device organizations; double data rate on DQS_t/DQS_c edges.",
        "VDD = VDDQ = 1.2 V (VPP = 2.5 V) — reduced from DDR3's 1.5 V.",
        "Bank Groups (4 bank groups x 4 banks = 16 banks for x4/x8; 2 x 4 = 8 "
        "for x16) with short/long bank-group timings (tCCD_S/tCCD_L, "
        "tRRD_S/tRRD_L, tWTR_S/tWTR_L) — new in DDR4.",
        "Gear-down (1/2-rate) command/address mode (MR3) for high speed bins.",
        "Data Bus Inversion (DBI) on DM_n/DBI_n (MR5) to cut I/O power and SSO "
        "noise.",
        "Internal (on-die) VrefDQ generation with controller-directed VrefDQ "
        "training (MR6).",
        "Write CRC (8-bit) on the data bus (MR2) with ALERT_n error "
        "signaling.",
        "Command/Address (CA) parity (PAR pin, MR5) with ALERT_n persistent "
        "error mode.",
        "ACT_n command flag with multiplexed RAS_n/A16, CAS_n/A15, WE_n/A14 "
        "command truth table.",
        "Burst length BL8 / BC4 with on-the-fly selection (A12/BC_n); mode "
        "registers MR0..MR6 via MRS.",
        "On-die termination Rtt_Nom / Rtt_WR / Rtt_PARK (Rtt_PARK new in "
        "DDR4); ZQ calibration against RZQ (240 ohm).",
        "RDIMM uses a Registering Clock Driver (RCD); LRDIMM adds Data "
        "Buffers (DB).",
        "Fine Granularity Refresh (1x/2x/4x), all-bank and per-bank refresh, "
        "self-refresh with Auto Self-Refresh (ASR), Maximum Power Saving "
        "Mode.",
    ]
    d["topology_summary"] = (
        "A DDR4 controller drives a single 64-bit (72-bit ECC) command/"
        "address/data channel to one or more ranks of x4/x8/x16 DDR4 SDRAMs "
        "on a UDIMM/RDIMM/LRDIMM; RDIMM/LRDIMM re-clock the command/address "
        "bus through an RCD (and LRDIMM buffers data through DBs).")
    d["use_cases"] = [
        "Desktop / server / workstation main memory (UDIMM / RDIMM / LRDIMM)",
        "Embedded and networking main memory",
        "FPGA and SoC external DRAM via a DDR4 PHY + controller",
        "High-density ECC server memory (72-bit, RDIMM/LRDIMM)",
    ]
    d["revision_history"] = [
        {"version": "JESD79-4", "date": "DDR4 SDRAM",
         "description": "JEDEC DDR4 SDRAM standard: single 64-bit channel, "
                        "1.2 V, bank groups, gear-down, DBI, write CRC, CA "
                        "parity, on-die VrefDQ training, MR0..MR6, BL8/BC4, "
                        "speed bins DDR4-1600..DDR4-3200."},
    ]
    d["overview"] = (
        "DDR4 SDRAM (JESD79-4) is the fourth-generation JEDEC double-data-rate "
        "synchronous DRAM. It retains the burst-oriented, bank-organized, "
        "mode-register-driven SDRAM command model (ACTIVATE / READ / WRITE / "
        "PRECHARGE / REFRESH, with tRCD / tRP / tRAS / tRC / tRFC / tWR "
        "timings) but adds, over DDR3: a new Bank Group addressing tier "
        "(BG0/BG1) with short vs long bank-group timings; gear-down (1/2-rate) "
        "command/address capture; Data Bus Inversion; on-die VrefDQ generation "
        "with VrefDQ training; write CRC on the data bus; and command/address "
        "parity, both error mechanisms reported on the ALERT_n pin. DDR4 lowers "
        "VDD/VDDQ to 1.2 V (VPP = 2.5 V), multiplexes the legacy RAS_n/CAS_n/"
        "WE_n pins with high address bits behind an ACT_n flag, uses BL8 / BC4 "
        "(on-the-fly) bursts, and is configured through mode registers MR0..MR6. "
        "It is a single 64-bit (72-bit ECC) channel per module — distinct from "
        "DDR5's two 32-bit sub-channels — and is DLL-based across speed bins "
        "DDR4-1600 through DDR4-3200. Registered modules use an RCD; "
        "load-reduced modules add Data Buffers.")
    _write(p, d)


# ----------------------------------------------------------------------
# L2 — FRS / functional requirements.
# ----------------------------------------------------------------------
def _l2(gd: Path) -> None:
    p = gd / "L2_FRS.json"
    if not p.is_file():
        return
    d = _read(p)
    po = _ensure_dict(d, "protocol_overview")
    po["type"] = (
        "Clocked, double-data-rate, bank-organized synchronous DRAM (JEDEC "
        "JESD79-4). A single 64-bit (72-bit ECC) channel; commands/addresses "
        "captured on the rising CK edge; data on both DQS edges.")
    po["double_data_rate"] = True
    po["channel_width_bits"] = _DATA_WIDTH_BITS
    po["channel_width_bits_ecc"] = _DATA_WIDTH_BITS_ECC
    po["single_channel"] = True
    po["sub_channels"] = 0
    po["vdd_volts"] = _VDD_V
    po["vddq_volts"] = _VDDQ_V
    po["vpp_volts"] = _VPP_V
    po["bank_groups_x4_x8"] = _BANK_GROUPS_X4_X8
    po["banks_x4_x8"] = _BANKS_X4_X8
    po["device_widths"] = list(_DEVICE_WIDTHS)
    po["burst_lengths"] = list(_BURST_LENGTHS)
    po["speed_bins_MTps"] = list(_SPEED_BINS_MTS)
    po["dll_based"] = True
    po["embedded_clock"] = False
    po["forwarded_clock"] = True
    po["clocking"] = (
        "Source-synchronous: a forwarded differential clock CK_t/CK_c carries "
        "commands; a forwarded differential data strobe DQS_t/DQS_c carries "
        "data (double data rate). An on-die DLL aligns output DQS/DQ to CK.")
    po["new_vs_ddr3"] = [
        "Bank Groups (BG0/BG1) with short/long timings (tCCD_S/L, tRRD_S/L, "
        "tWTR_S/L).",
        "Gear-down (1/2-rate) command/address mode.",
        "Data Bus Inversion (DBI).",
        "On-die VrefDQ generation + VrefDQ training.",
        "Write CRC on the data bus + ALERT_n.",
        "Command/Address (CA) parity + ALERT_n.",
        "1.2 V VDD/VDDQ (vs 1.5 V); VPP 2.5 V; Rtt_PARK.",
        "ACT_n command flag with multiplexed RAS_n/A16, CAS_n/A15, WE_n/A14.",
    ]
    d["functional_requirements"] = [
        {"id": "FR-CH-01", "text": "DDR4 presents a single 64-bit (72-bit "
         "ECC) data channel per module; there is no sub-channel split. Devices "
         "are x4/x8/x16."},
        {"id": "FR-DDR-02", "text": "Commands and addresses are captured on "
         "the rising edge of the differential clock CK_t/CK_c; data DQ is "
         "transferred on both edges of the differential strobe DQS_t/DQS_c "
         "(double data rate)."},
        {"id": "FR-VDD-03", "text": "DDR4 operates at VDD = VDDQ = 1.2 V with "
         "VPP = 2.5 V; VREFCA is supplied externally and VREFDQ is generated "
         "internally (on-die)."},
        {"id": "FR-BG-04", "text": "The banks are partitioned into Bank Groups "
         "(BG0/BG1): x4/x8 = 4 bank groups x 4 banks = 16 banks; x16 = 2 bank "
         "groups x 4 banks = 8 banks. Accesses to different bank groups use "
         "tCCD_S (short); same-bank-group accesses use tCCD_L (long)."},
        {"id": "FR-GD-05", "text": "Gear-down mode (MR3) samples command/"
         "address on every other rising CK edge (1/2 rate) with a "
         "synchronization pulse, to ease command-bus timing at high speed "
         "bins."},
        {"id": "FR-DBI-06", "text": "Data Bus Inversion (MR5) repurposes DM_n "
         "as DBI_n per byte to minimize DQ lines driven LOW; DM and write-DBI "
         "are mutually exclusive on the shared pin."},
        {"id": "FR-VREF-07", "text": "Each DDR4 SDRAM generates VREFDQ on-die "
         "(programmable in fine steps via MR6) and the controller runs a "
         "VrefDQ training sequence (Range 1 / Range 2) to center the DQ "
         "reference."},
        {"id": "FR-CRC-08", "text": "Write CRC (MR2) appends an 8-bit CRC to "
         "each BL8 write burst; a detected CRC error is signaled on ALERT_n "
         "and the write is not committed (controller retries)."},
        {"id": "FR-PAR-09", "text": "Command/Address parity (PAR pin, MR5) "
         "covers the command and address inputs; a parity error blocks the "
         "command and asserts ALERT_n for the programmed CA-parity error "
         "window."},
        {"id": "FR-CMD-10", "text": "The command truth table uses the ACT_n "
         "flag: when ACT_n is LOW the command is ACTIVATE; when ACT_n is HIGH, "
         "RAS_n/A16, CAS_n/A15, WE_n/A14 encode READ/WRITE/PRECHARGE/REFRESH/"
         "MRS and carry high address bits."},
        {"id": "FR-BL-11", "text": "Data is transferred in bursts of BL8 "
         "(eight beats) or BC4 (burst chop of four); A12/BC_n selects BL8 vs "
         "BC4 on-the-fly per command. Mode registers MR0..MR6 are written via "
         "MRS."},
        {"id": "FR-ODT-12", "text": "On-die termination supports Rtt_Nom "
         "(MR1), Rtt_WR (MR2), and Rtt_PARK (MR5, new in DDR4); ZQ "
         "calibration (ZQCL/ZQCS) calibrates the output driver and ODT against "
         "the external RZQ (240 ohm) resistor."},
        {"id": "FR-REF-13", "text": "DDR4 supports all-bank and per-bank "
         "REFRESH, Fine Granularity Refresh (1x/2x/4x), self-refresh with Auto "
         "Self-Refresh (ASR), and power-down / Maximum Power Saving Mode."},
    ]
    d["error_response_conditions"] = [
        "Write CRC error — signaled on ALERT_n; the write is not committed and "
        "is retried.",
        "CA parity error — the command is blocked and ALERT_n is asserted for "
        "the CA-parity error window (persistent error mode).",
        "Connectivity / boundary-scan error — reported via ALERT_n.",
        "Refresh / timing violation — data integrity not guaranteed if "
        "tREFI/tRFC are violated.",
    ]
    d["compliance_requirements"] = [
        "Single 64-bit (72-bit ECC) channel at 1.2 V; x4/x8/x16.",
        "Bank Groups with short/long bank-group timings.",
        "Gear-down mode, Data Bus Inversion, on-die VrefDQ training.",
        "Write CRC and CA parity, both reported on ALERT_n.",
        "ACT_n command truth table (RAS_n/A16, CAS_n/A15, WE_n/A14).",
        "BL8 / BC4 (on-the-fly) bursts; MR0..MR6 mode registers.",
        "ODT Rtt_Nom / Rtt_WR / Rtt_PARK; ZQ calibration against RZQ.",
        "Speed bins DDR4-1600 .. DDR4-3200; DLL-based.",
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
        "Clocked SDRAM command protocol (JEDEC JESD79-4). Commands are encoded "
        "on CKE / CS_n / ACT_n / RAS_n-A16 / CAS_n-A15 / WE_n-A14 and captured "
        "on the rising CK edge; a row is opened with ACTIVATE (bank group BG, "
        "bank BA, row), columns are accessed with READ/WRITE after tRCD, and "
        "the row is closed with PRECHARGE after tRP. Data bursts (BL8/BC4) "
        "transfer on DQS edges.")
    d["command_truth_table"] = [
        {"command": "ACTIVATE (ACT)", "encoding": "ACT_n=L",
         "purpose": "Open a row in (bank group BG, bank BA, row); tRCD before "
                    "a column access."},
        {"command": "READ (RD)", "encoding": "ACT_n=H, RAS_n=H, CAS_n=L, WE_n=H",
         "purpose": "Column read; data burst on DQS edges CL after the "
                    "command."},
        {"command": "WRITE (WR)", "encoding": "ACT_n=H, RAS_n=H, CAS_n=L, WE_n=L",
         "purpose": "Column write; data captured on DQS CWL after the "
                    "command."},
        {"command": "PRECHARGE (PRE)", "encoding": "ACT_n=H, RAS_n=L, CAS_n=H, WE_n=L",
         "purpose": "Close a row; tRP before the next ACTIVATE. A10/AP "
                    "precharge-all."},
        {"command": "REFRESH (REF)", "encoding": "ACT_n=H, RAS_n=L, CAS_n=L, WE_n=H",
         "purpose": "Refresh (all banks idle); tRFC. Fine Granularity Refresh "
                    "1x/2x/4x."},
        {"command": "MRS", "encoding": "ACT_n=H, RAS_n=L, CAS_n=L, WE_n=L",
         "purpose": "Mode Register Set (MR0..MR6)."},
        {"command": "ZQ CALIBRATION", "encoding": "ZQCL (long) / ZQCS (short)",
         "purpose": "Calibrate the output driver and ODT against RZQ (240 "
                    "ohm)."},
        {"command": "NOP / DESELECT", "encoding": "NOP / CS_n=H",
         "purpose": "No operation / deselect."},
    ]
    d["act_n_pin_multiplexing"] = {
        "ACT_n": "Activate command flag (LOW = ACTIVATE).",
        "RAS_n/A16": "RAS_n when ACT_n LOW; address A16 when ACT_n HIGH.",
        "CAS_n/A15": "CAS_n when ACT_n LOW; address A15 when ACT_n HIGH.",
        "WE_n/A14": "WE_n when ACT_n LOW; address A14 when ACT_n HIGH.",
    }
    d["addressing"] = {
        "bank_group_pins": ["BG0", "BG1"],
        "bank_pins": ["BA0", "BA1"],
        "bank_groups_x4_x8": _BANK_GROUPS_X4_X8,
        "banks_x4_x8": _BANKS_X4_X8,
        "auto_precharge": "A10/AP issues an automatic PRECHARGE after the "
                          "burst.",
        "burst_chop_otf": "A12/BC_n selects BL8 vs BC4 on-the-fly.",
    }
    d["burst"] = {
        "burst_lengths": list(_BURST_LENGTHS),
        "bl8": "fixed burst length of 8 beats",
        "bc4": "burst chop of 4 beats",
        "otf": "A12/BC_n selects BL8 or BC4 per READ/WRITE command",
        "note": "A BL8 access fills a 64-byte cache line on a 64-bit channel.",
    }
    d["data_integrity"] = {
        "write_crc_bits": _WRITE_CRC_BITS,
        "write_crc": "8-bit CRC appended to each BL8 write burst (MR2); error "
                     "on ALERT_n.",
        "ca_parity": "Even-parity PAR pin over command/address inputs (MR5); "
                     "error blocks the command and asserts ALERT_n.",
    }
    d["mode_registers"] = list(_MODE_REGISTERS)
    d["bank_group_timing"] = {
        "tCCD_S": "column-to-column delay, different bank group (short)",
        "tCCD_L": "column-to-column delay, same bank group (long)",
        "tRRD_S": "ACTIVATE-to-ACTIVATE, different bank group (short)",
        "tRRD_L": "ACTIVATE-to-ACTIVATE, same bank group (long)",
        "tWTR_S": "WRITE-to-READ turnaround, different bank group (short)",
        "tWTR_L": "WRITE-to-READ turnaround, same bank group (long)",
    }
    d["byte_oriented"] = False
    d["burst_oriented"] = True
    d["clocked_synchronous"] = True
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
        "DDR4 configuration state lives in the seven mode registers MR0..MR6, "
        "written by the MRS command. There is no random-access memory-mapped "
        "register file; the mode registers, the Multi-Purpose Register (MPR), "
        "and the temperature/CRC-error status are the DDR4 configuration and "
        "status surfaces.")
    d["register_access"] = {
        "transport": "MRS (Mode Register Set) command writes MR0..MR6; MPR "
                     "(MR3) for read-back; ALERT_n for CRC/CA-parity error "
                     "status.",
        "purpose": "Set burst length, latencies, ODT, DBI, write CRC, CA "
                   "parity, gear-down, VrefDQ training, refresh and power "
                   "modes.",
    }
    d["mode_registers"] = [
        {"name": "MR0", "fields": [
            "Burst Length (BL8 / BC4 / on-the-fly)",
            "Read CAS Latency (CL)", "Burst Type (sequential / interleave)",
            "Write Recovery (tWR) / Read-to-Precharge", "DLL Reset",
            "Test Mode"]},
        {"name": "MR1", "fields": [
            "DLL Enable", "Output Drive Strength (RZQ/6, RZQ/7)",
            "Rtt_Nom (nominal ODT)", "Additive Latency (AL)",
            "Write Leveling enable", "TDQS", "Qoff"]},
        {"name": "MR2", "fields": [
            "Write CAS Latency (CWL)", "Rtt_WR (dynamic ODT)",
            "Write CRC enable", "Auto Self-Refresh (ASR)",
            "LP Auto Self-Refresh"]},
        {"name": "MR3", "fields": [
            "Multi-Purpose Register (MPR) access + page select",
            "Gear-down mode", "Per-DRAM Addressability (PDA)",
            "Write/Read command latency (CRC/DM/gear-down)",
            "Fine Granularity Refresh", "Temperature sensor readout"]},
        {"name": "MR4", "fields": [
            "CAL (Command Address Latency)",
            "Read/Write Preamble (1tCK / 2tCK)", "Self-Refresh Abort",
            "Maximum Power Saving Mode", "Temperature-controlled refresh",
            "Internal VREF monitor", "CS-to-CMD/ADDR latency"]},
        {"name": "MR5", "fields": [
            "CA parity latency / enable", "CRC error status / clear",
            "ODT input buffer power-down", "CA parity persistent error",
            "Data Bus Inversion (read DBI / write DBI)", "Rtt_PARK"]},
        {"name": "MR6", "fields": [
            "tCCD_L programming", "VrefDQ training enable",
            "VrefDQ training range (Range 1 / Range 2)",
            "VrefDQ training value (step)"]},
    ]
    d["protocol_fields"] = {
        "vdd_volts": _VDD_V,
        "vddq_volts": _VDDQ_V,
        "channel_width_bits": _DATA_WIDTH_BITS,
        "bank_groups_x4_x8": _BANK_GROUPS_X4_X8,
        "speed_bins_MTps": list(_SPEED_BINS_MTS),
        "write_crc_bits": _WRITE_CRC_BITS,
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
        "DDR4 uses POD12 (Pseudo Open Drain, 1.2 V) single-ended signaling on "
        "the command/address bus and DQ, with differential CK_t/CK_c and "
        "differential DQS_t/DQS_c. Data is double-data-rate on the DQS edges. "
        "On-die termination (Rtt_Nom / Rtt_WR / Rtt_PARK) terminates to VDDQ; "
        "the DQ reference VREFDQ is generated internally (on-die) and centered "
        "by VrefDQ training. ZQ calibration trims the output driver and ODT "
        "against an external RZQ (240 ohm) resistor.")
    d["signaling_standard"] = "POD12 (Pseudo Open Drain, 1.2 V)"
    d["vdd_volts"] = _VDD_V
    d["vddq_volts"] = _VDDQ_V
    d["vpp_volts"] = _VPP_V
    d["clocking"] = (
        "Source-synchronous: forwarded differential clock CK_t/CK_c (commands "
        "on the rising edge) and forwarded differential strobe DQS_t/DQS_c "
        "(data on both edges). An on-die DLL aligns DQS/DQ output to CK.")
    d["vref"] = {
        "VREFCA": "supplied externally for the command/address bus",
        "VREFDQ": "generated INTERNALLY (on-die) and centered by VrefDQ "
                  "training (MR6, Range 1 / Range 2) — a DDR4 feature; DDR3 "
                  "used an external VREFDQ.",
    }
    d["odt"] = {
        "Rtt_Nom": "nominal ODT controlled by the ODT pin (MR1)",
        "Rtt_WR": "dynamic ODT applied during writes (MR2)",
        "Rtt_PARK": "parked ODT applied when ODT is deasserted (MR5, new in "
                    "DDR4)",
        "values": "fractions of RZQ (e.g. RZQ/4 = 60 ohm); RZQ = 240 ohm.",
    }
    d["transmitter_specs_canonical"] = {
        "signaling": "POD12 single-ended (CA, DQ); differential CK and DQS",
        "data_rate": "double data rate on DQS edges",
        "drive_strength": "RZQ/6 or RZQ/7 (MR1)",
        "data_bus_inversion": "DBI on DM_n/DBI_n (MR5)",
    }
    d["receiver_specs_canonical"] = {
        "vref": "internal VREFDQ (trained); external VREFCA",
        "termination": "on-die Rtt_Nom / Rtt_WR / Rtt_PARK to VDDQ",
        "preamble": "1tCK or 2tCK read/write preamble (MR4)",
    }
    d["zq_calibration"] = (
        "ZQCL (long) / ZQCS (short) calibrate the output-driver impedance and "
        "ODT against the external RZQ (240 ohm) reference at the ZQ pin.")
    d["max_data_rate_MTps"] = _MAX_SPEED_MTS
    # Overwrite DDR3-synth residue keys with DDR4 values.
    d["voltage_classes"] = [
        {"class": "DDR4 (standard)", "vdd_vddq": "1.2 V", "vpp": "2.5 V",
         "applicable": "JESD79-4 DDR4 SDRAM"},
    ]
    d["input_threshold_levels"] = (
        "POD12 (Pseudo Open Drain, 1.2 V) input thresholds referenced to "
        "VREFCA (command/address) and internal VREFDQ (data).")
    d.pop("input_threshold_levels_SSTL15", None)
    d["notes"] = (
        "DDR4 uses POD12 (1.2 V) single-ended CA/DQ signaling with "
        "differential CK_t/CK_c and DQS_t/DQS_c. VREFCA is external; VREFDQ is "
        "internal (on-die) and centered by VrefDQ training. ODT "
        "(Rtt_Nom/Rtt_WR/Rtt_PARK) terminates to VDDQ; ZQ calibration trims "
        "against RZQ (240 ohm).")
    _write(p, d)


# ----------------------------------------------------------------------
# L6 — control logic / state machines.
# ----------------------------------------------------------------------
def _l6(gd: Path) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["fsm_states_bank"] = [
        {"name": "IDLE", "description": "All rows precharged; the bank awaits "
         "an ACTIVATE."},
        {"name": "ACTIVATING", "description": "ACTIVATE issued; the row opens "
         "(bank group BG, bank BA, row); wait tRCD."},
        {"name": "ACTIVE", "description": "A row is open; READ/WRITE column "
         "accesses are allowed."},
        {"name": "PRECHARGING", "description": "PRECHARGE issued; the row "
         "closes; wait tRP before the next ACTIVATE."},
    ]
    d["fsm_states_device"] = [
        {"name": "RESET / INIT", "description": "RESET_n + the JESD79-4 "
         "power-up / initialization sequence; DLL reset; ZQ calibration; MRS "
         "of MR0..MR6."},
        {"name": "VREFDQ_TRAINING", "description": "Controller-directed VrefDQ "
         "training (MR6) centers the on-die DQ reference."},
        {"name": "READY", "description": "Initialized; normal command "
         "operation (ACTIVATE/READ/WRITE/PRECHARGE/REFRESH)."},
        {"name": "SELF_REFRESH", "description": "CKE LOW self-refresh; the DRAM "
         "refreshes itself (ASR / LP modes)."},
        {"name": "POWER_DOWN", "description": "Precharge / active power-down "
         "(CKE LOW); Maximum Power Saving Mode for deep idle."},
    ]
    d["fsm_hints"] = {
        "trigger": "Power-up -> RESET_n -> DLL reset + ZQ calibration + MRS "
        "(MR0..MR6) -> VrefDQ training -> READY.",
        "rule": "A bank must be ACTIVE (row open, tRCD met) before a column "
        "READ/WRITE; PRECHARGE (tRP) closes the row. Bank-group timing "
        "(tCCD_S/L, tRRD_S/L, tWTR_S/L) governs back-to-back accesses.",
        "gear_down": "In gear-down mode (MR3) command/address is sampled at "
        "1/2 rate with a synchronization pulse.",
    }
    d["bank_group_rule"] = (
        "Accesses to DIFFERENT bank groups can issue at the short delay "
        "tCCD_S, while accesses WITHIN the SAME bank group incur the longer "
        "tCCD_L. The bank-group split (tCCD_S/L, tRRD_S/L, tWTR_S/L) lets DDR4 "
        "hide internal array recovery time at high data rates.")
    d["exit_from_reset_or_poweron"] = (
        "RESET_n asserted, then the JESD79-4 power-up sequence: stabilize "
        "supplies (VPP then VDD/VDDQ at 1.2 V), CKE HIGH, DLL reset, ZQ "
        "calibration, MRS of MR0..MR6, and VrefDQ training before the device "
        "is ready for normal commands.")
    d["default_ready_state_recommendation"] = {
        "idle": "Banks precharged (IDLE), DLL locked, ODT parked (Rtt_PARK), "
                "awaiting ACTIVATE; periodic REFRESH within tREFI.",
        "refresh": "Issue all-bank or per-bank REFRESH within tREFI; tRFC "
                   "per Fine Granularity Refresh mode (1x/2x/4x).",
    }
    d["configurations"] = [
        {"name": "x4 / x8 device", "description": "4 bank groups x 4 banks = "
         "16 banks."},
        {"name": "x16 device", "description": "2 bank groups x 4 banks = 8 "
         "banks."},
        {"name": "UDIMM", "description": "Unbuffered DIMM; DRAMs directly on "
         "the host bus."},
        {"name": "RDIMM", "description": "Registered DIMM; an RCD re-clocks "
         "command/address."},
        {"name": "LRDIMM", "description": "Load-reduced DIMM; RCD + Data "
         "Buffers (DB) isolate command/address and data."},
    ]
    d["timing_dependency_rule"] = (
        "tRCD between ACTIVATE and the first column access; tRP after "
        "PRECHARGE before the next ACTIVATE; tRAS minimum row-active time; "
        "tRC = tRAS + tRP same-bank ACTIVATE period; tRFC after REFRESH; tWR "
        "write recovery; bank-group tCCD_S/L, tRRD_S/L, tWTR_S/L; tFAW "
        "four-activate window; tREFI average refresh interval.")
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
        {"name": "ALERT_n", "purpose": "Reports CA-parity errors, write-CRC "
         "errors, and connectivity (boundary-scan) errors."},
        {"name": "Multi-Purpose Register (MPR)", "purpose": "MR3-selected MPR "
         "pages return predefined / training / error / temperature data on "
         "reads."},
        {"name": "CRC error status (MR5)", "purpose": "Latched write-CRC error "
         "status, cleared via MR5."},
        {"name": "Temperature sensor / TCR", "purpose": "On-die temperature "
         "readout for temperature-controlled refresh."},
        {"name": "Connectivity Test (CT) mode", "purpose": "DDR4 boundary "
         "connectivity test using the ALERT_n / TEN pins."},
    ]
    d["error_detection_mechanisms"] = [
        "Write CRC (8-bit) detects write-data corruption -> ALERT_n.",
        "CA parity (even, PAR pin) detects command/address corruption -> "
        "ALERT_n; the command is blocked.",
        "Connectivity Test mode checks DIMM/package connectivity.",
        "VrefDQ training and write leveling detect mistraining at bring-up.",
    ]
    d["test_modes"] = [
        {"name": "MPR read", "purpose": "Read predefined patterns / error / "
         "training data without the array."},
        {"name": "Connectivity Test (CT)", "purpose": "Boundary connectivity "
         "test via TEN / ALERT_n."},
        {"name": "VrefDQ training", "purpose": "Center the on-die DQ "
         "reference."},
        {"name": "Write leveling", "purpose": "Align DQS to CK across a fly-by "
         "command/address routing (MR1)."},
    ]
    d["interrupt_or_event_sources"] = [
        {"event": "CA parity error", "trigger": "PAR mismatch -> ALERT_n; "
         "command blocked."},
        {"event": "Write CRC error", "trigger": "Write-CRC mismatch -> "
         "ALERT_n; write not committed."},
        {"event": "Connectivity error", "trigger": "CT-mode mismatch -> "
         "ALERT_n."},
        {"event": "Temperature crossing", "trigger": "TCR / refresh-rate "
         "change."},
    ]
    d["notes"] = (
        "DDR4's protocol-level observability is the ALERT_n pin (CA parity / "
        "write CRC / connectivity), the Multi-Purpose Register, latched CRC "
        "error status, the on-die temperature sensor, and Connectivity Test "
        "mode. Chip-level scan/BIST of the controller/PHY remain SoC "
        "concerns.")
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
        "DDR_STANDARD": "JEDEC JESD79-4 (DDR4 SDRAM)",
        "CHANNEL_WIDTH_BITS": _DATA_WIDTH_BITS,
        "CHANNEL_WIDTH_BITS_ECC": _DATA_WIDTH_BITS_ECC,
        "DEVICE_WIDTHS": list(_DEVICE_WIDTHS),
        "VDD_V": _VDD_V,
        "VDDQ_V": _VDDQ_V,
        "VPP_V": _VPP_V,
        "BANK_GROUPS_X4_X8": _BANK_GROUPS_X4_X8,
        "BANKS_PER_GROUP": _BANKS_PER_GROUP,
        "BANKS_X4_X8": _BANKS_X4_X8,
        "BANK_GROUPS_X16": _BANK_GROUPS_X16,
        "BANKS_X16": _BANKS_X16,
        "SPEED_BINS_MTPS": list(_SPEED_BINS_MTS),
        "MAX_DATA_RATE_MTPS": _MAX_SPEED_MTS,
        "WRITE_CRC_BITS": _WRITE_CRC_BITS,
        "BURST_LENGTHS": list(_BURST_LENGTHS),
        "MODE_REGISTER_COUNT": len(_MODE_REGISTERS),
        "MODE_REGISTERS": list(_MODE_REGISTERS),
        "DOUBLE_DATA_RATE": True,
        "DLL_BASED": True,
        "FORWARDED_CLOCK": True,
        "SINGLE_CHANNEL": True,
        "SUB_CHANNELS": 0,
    })
    d["feature_flags"] = {
        "bank_groups": True,
        "gear_down_mode": True,
        "data_bus_inversion": True,
        "internal_vrefdq": True,
        "vrefdq_training": True,
        "write_crc": True,
        "ca_parity": True,
        "rtt_park": True,
        "act_n_command_flag": True,
        "decision_feedback_equalization": False,
        "on_die_ecc": False,
        "dimm_pmic": False,
        "write_clock_wck": False,
    }
    d["timing_parameter_names"] = [
        "tRCD", "tRP", "tRAS", "tRC", "tRFC", "tWR", "tCCD_S", "tCCD_L",
        "tRRD_S", "tRRD_L", "tWTR_S", "tWTR_L", "tFAW", "tREFI", "CL", "CWL",
    ]
    kc = _ensure_dict(d, "key_constants_for_RTL_authoring")
    kc.update({
        "ddr_generation": "DDR4",
        "spec_id": "JESD79-4",
        "channel_width_bits": _DATA_WIDTH_BITS,
        "vdd_volts": _VDD_V,
        "double_data_rate": True,
        "forwarded_clock": True,
        "dll_based": True,
        "bank_groups": True,
        "bank_groups_x4_x8": _BANK_GROUPS_X4_X8,
        "banks_x4_x8": _BANKS_X4_X8,
        "burst_lengths": list(_BURST_LENGTHS),
        "mode_registers": list(_MODE_REGISTERS),
        "write_crc_bits": _WRITE_CRC_BITS,
        "ca_parity": True,
        "data_bus_inversion": True,
        "gear_down_mode": True,
        "internal_vrefdq": True,
        "speed_bins_MTps": list(_SPEED_BINS_MTS),
    })
    d["default_signal_values_when_idle"] = {
        "banks": "precharged (IDLE)",
        "odt": "Rtt_PARK when ODT deasserted",
        "refresh": "periodic REFRESH within tREFI",
    }
    # Overwrite DDR3-synth residue dicts with DDR4 values.
    d["voltage_levels"] = {
        "VDD_V": _VDD_V,
        "VDDQ_V": _VDDQ_V,
        "VPP_V": _VPP_V,
        "VDD_tolerance": "±0.06 V (DDR4)",
        "signaling": "POD12 (1.2 V)",
    }
    d["clock_constants"] = {
        "DDR4_1600_tCK_ns": 1.25,
        "DDR4_2133_tCK_ns": 0.938,
        "DDR4_2400_tCK_ns": 0.833,
        "DDR4_2666_tCK_ns": 0.750,
        "DDR4_3200_tCK_ns": 0.625,
        "DDR4_1600_data_rate_MTps": 1600,
        "DDR4_2400_data_rate_MTps": 2400,
        "DDR4_3200_data_rate_MTps": 3200,
        "note": "data rate (MT/s) = 2 / tCK(ns) x 1000 (double data rate).",
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
    d["clock_waveform"] = {
        "ck": "differential CK_t/CK_c; commands captured on the rising edge",
        "dqs": "differential DQS_t/DQS_c; data on both edges (double data "
               "rate)",
        "preamble": "1tCK or 2tCK read/write preamble (MR4)",
        "dll": "on-die DLL aligns DQS/DQ output to CK",
    }
    d["command_waveform"] = {
        "activate": "ACT_n=L opens a row (BG, BA, row); tRCD to a column "
                    "access",
        "read": "ACT_n=H, CAS_n=L, WE_n=H; data burst CL later on DQS edges",
        "write": "ACT_n=H, CAS_n=L, WE_n=L; data captured CWL later on DQS",
        "precharge": "ACT_n=H, RAS_n=L, WE_n=L; tRP before the next ACTIVATE",
    }
    d["burst_waveform"] = {
        "bl8": "8 data beats on 4 DQS clocks",
        "bc4": "burst chop of 4 beats",
        "otf": "A12/BC_n selects BL8 vs BC4 per command",
        "write_crc": "an 8-bit write-CRC frame follows the BL8 write burst "
                     "when enabled (MR2)",
    }
    d["bank_group_waveform"] = {
        "tCCD_S": "back-to-back column accesses to different bank groups "
                  "(short)",
        "tCCD_L": "column accesses to the same bank group (long)",
    }
    d["data_rate_waveform"] = {
        "speed_bins_MTps": list(_SPEED_BINS_MTS),
        "relation": "data rate (MT/s) = 2 x CK frequency (double data rate)",
        "max_data_rate_MTps": _MAX_SPEED_MTS,
    }
    d["general_timing_rule"] = (
        "A bank must be ACTIVE (row open, tRCD met) before a column READ/WRITE; "
        "PRECHARGE (tRP) closes the row; tRAS is the minimum row-active time; "
        "REFRESH occurs within tREFI with tRFC recovery. Bank-group timings "
        "(tCCD_S/L, tRRD_S/L, tWTR_S/L) gate back-to-back accesses.")
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
        "Commodity main-memory DRAM device (JEDEC JESD79-4 DDR4 SDRAM): a "
        "single 64-bit (72-bit ECC) double-data-rate channel that a memory "
        "controller + DDR4 PHY drives with ACTIVATE/READ/WRITE/PRECHARGE/"
        "REFRESH commands over CK_t/CK_c, exchanging data on DQS_t/DQS_c, with "
        "bank groups, gear-down, DBI, on-die VrefDQ training, write CRC, and "
        "CA parity.")
    d["topology_description"] = (
        "Memory controller + DDR4 PHY -> single 64-bit (72-bit ECC) "
        "command/address/data channel -> one or more ranks of x4/x8/x16 DDR4 "
        "SDRAMs on a UDIMM/RDIMM/LRDIMM. RDIMM/LRDIMM re-clock command/address "
        "through an RCD; LRDIMM buffers data through Data Buffers (DB).")
    io = _ensure_dict(d, "integration_overview")
    io.update({
        "ddr_standard": "JEDEC JESD79-4 (DDR4 SDRAM)",
        "channel_width_bits": _DATA_WIDTH_BITS,
        "channel_width_bits_ecc": _DATA_WIDTH_BITS_ECC,
        "single_channel": True,
        "device_widths": list(_DEVICE_WIDTHS),
        "vdd_volts": _VDD_V,
        "vddq_volts": _VDDQ_V,
        "vpp_volts": _VPP_V,
        "speed_bins_MTps": list(_SPEED_BINS_MTS),
        "burst_lengths": list(_BURST_LENGTHS),
        "bank_groups_x4_x8": _BANK_GROUPS_X4_X8,
        "banks_x4_x8": _BANKS_X4_X8,
        "double_data_rate": True,
        "forwarded_clock": True,
        "dll_based": True,
        "module_types": ["UDIMM", "RDIMM", "LRDIMM"],
        "module_components": {"RDIMM": "RCD (Registering Clock Driver)",
                              "LRDIMM": "RCD + Data Buffers (DB)"},
        "interfaces": {"clock": "CK_t/CK_c", "data": "DQ + DQS_t/DQS_c",
                       "command_address": "ACT_n + RAS_n/A16 + CAS_n/A15 + "
                                          "WE_n/A14 + A[13:0] + BG + BA",
                       "alert": "ALERT_n", "parity": "PAR"},
    })
    d["interface_categories"] = [
        "Clock interface — differential CK_t/CK_c (commands on the rising "
        "edge).",
        "Command/Address interface — ACT_n flag + multiplexed RAS_n/A16, "
        "CAS_n/A15, WE_n/A14 + address + BG/BA, with PAR parity.",
        "Data interface — DQ + differential DQS_t/DQS_c (double data rate) + "
        "DM_n/DBI_n.",
        "Control/alert — CKE, CS_n, ODT, RESET_n, ALERT_n, ZQ.",
    ]
    d["interconnect_topologies_supported"] = [
        "Point-to-point controller-to-DRAM (single device / on-package).",
        "UDIMM (unbuffered).",
        "RDIMM (registered command/address via RCD).",
        "LRDIMM (load-reduced: RCD + Data Buffers).",
        "Multi-rank via per-rank CS_n.",
    ]
    d["soc_dependent_items"] = [
        "Number of ranks and DIMM type (UDIMM / RDIMM / LRDIMM).",
        "Device width (x4 / x8 / x16) and channel ECC (64 vs 72 bit).",
        "Target speed bin (DDR4-1600 .. DDR4-3200) and CL/CWL.",
        "DDR4 PHY training (write leveling, read/write training, VrefDQ "
        "training).",
        "ODT scheme (Rtt_Nom / Rtt_WR / Rtt_PARK) and ZQ calibration.",
        "Enabling of DBI / write CRC / CA parity / gear-down.",
    ]
    d["device_classes_examples"] = [
        "DDR4 SDRAM x4 / x8 / x16 component",
        "DDR4 UDIMM / RDIMM / LRDIMM module",
        "DDR4 memory controller + PHY (in an SoC / FPGA)",
        "DDR4 RCD (Registering Clock Driver) / DB (Data Buffer)",
    ]
    # Overwrite DDR3-synth residue keys with DDR4 values.
    d["compatibility_notes"] = [
        "DDR4 is NOT pin- or protocol-compatible with DDR3 (POD12 1.2 V vs "
        "SSTL 1.5 V, ACT_n command flag, bank groups, different ballout).",
        "x4, x8, x16 share the DDR4 protocol but differ in DQ width, bank-"
        "group count, and column-address count.",
        "DDR4 RDIMM adds an RCD (register); LRDIMM adds an RCD plus Data "
        "Buffers with extra CA / data latency.",
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
        "partial - JESD79-4 defines device behavior rather than an embedded "
        "testbench; the categories below are derived from the spec.")
    d["derived_compliance_test_categories"] = [
        "Power-up / initialization: VPP-then-VDD/VDDQ sequence, DLL reset, ZQ "
        "calibration, MRS of MR0..MR6.",
        "VrefDQ training (MR6, Range 1 / Range 2) and write leveling.",
        "ACTIVATE / READ / WRITE / PRECHARGE timing (tRCD / tRP / tRAS / tRC).",
        "Bank-group timing: tCCD_S vs tCCD_L, tRRD_S/L, tWTR_S/L; tFAW.",
        "Burst length BL8 / BC4 and on-the-fly (A12/BC_n) selection.",
        "Gear-down (1/2-rate) command/address mode with the sync pulse.",
        "Data Bus Inversion (read DBI / write DBI) on DM_n/DBI_n.",
        "Write CRC (8-bit) error injection -> ALERT_n; write not committed.",
        "CA parity error injection -> ALERT_n; command blocked (persistent "
        "error mode).",
        "ODT Rtt_Nom / Rtt_WR / Rtt_PARK; ZQ calibration against RZQ.",
        "Refresh: all-bank / per-bank / Fine Granularity (1x/2x/4x); tREFI / "
        "tRFC.",
        "Self-refresh / power-down / Maximum Power Saving Mode entry-exit.",
        "Mode-register read-back via the Multi-Purpose Register (MR3).",
        "Speed-bin sweep DDR4-1600 .. DDR4-3200 (CL/CWL per bin).",
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
        {"field": "Mode Registers MR0..MR6",
         "location": "volatile device configuration (MRS)",
         "note": "DDR4 configuration (BL, CL/CWL, ODT, DBI, write CRC, CA "
                 "parity, gear-down, VrefDQ training) is programmed each "
                 "power-up by MRS, not OTP-fixed."},
        {"field": "Module SPD (Serial Presence Detect)",
         "location": "on-DIMM EEPROM (not in the DRAM)",
         "note": "The DDR4 SPD EEPROM on the module stores timings / "
                 "organization for the BIOS; it is module-level, not DRAM "
                 "OTP."},
        {"field": "Vendor / device identification",
         "location": "MPR / mode-register read-back",
         "note": "Manufacturer ID and device type are readable, typically "
                 "factory-set."},
    ]
    d["notes"] = (
        "DDR4 SDRAM does not define OTP/fuse content as a protocol concept. "
        "Operating configuration lives in the volatile mode registers "
        "(MR0..MR6) set at each power-up; the module's SPD EEPROM (a separate "
        "device) holds the persistent timing/organization data the BIOS reads.")
    # Overwrite DDR3-synth residue keys with DDR4 values.
    d["otp_summary"] = (
        "DDR4 SDRAM exposes no OTP/fuse array as a protocol concept; "
        "configuration is in the volatile mode registers (MR0..MR6).")
    d["factory_programmed_dram_die_metadata"] = (
        "Manufacturer ID and device type are readable (typically "
        "factory-set); the DDR4 SDRAM die itself does not expose an OTP "
        "region.")
    d["spd_eeprom_layout_summary"] = {
        "spec_reference": "JEDEC DDR4 SPD Annex (module-level, not the DRAM)",
        "key_fields": [
            {"field": "Memory type", "description": "DDR4 SDRAM"},
            {"field": "Module organization",
             "description": "ranks, device width (x4/x8/x16), 64/72-bit "
                            "channel"},
            {"field": "Timing parameters",
             "description": "speed bin (DDR4-1600..DDR4-3200), CL/CWL, tRCD, "
                            "tRP, tRAS"},
        ],
        "note": "The SPD EEPROM lives on the DIMM module as a separate I2C "
                "device; it is not part of the DDR4 SDRAM die.",
    }
    d["permanent_state_after_power_off"] = (
        "None in the DRAM: DDR4 mode-register configuration is volatile and "
        "re-established each power-up; persistent module data lives in the "
        "SPD EEPROM.")
    _write(p, d)


# ----------------------------------------------------------------------
# L12 — behavioral sequences.
# ----------------------------------------------------------------------
def _l12(gd: Path) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["power_up_initialization_sequence"] = [
        "1. Apply VPP then VDD/VDDQ (1.2 V); assert RESET_n; hold CKE LOW.",
        "2. Release RESET_n; raise CKE HIGH after the required delay.",
        "3. Issue MRS to MR0..MR6 (set BL, CL/CWL, ODT, DBI, write CRC, CA "
        "parity, gear-down, etc.).",
        "4. Issue DLL Reset (MR0) and ZQ Calibration Long (ZQCL).",
        "5. Run VrefDQ training (MR6) and write leveling; the device is then "
        "ready.",
    ]
    d["read_sequence"] = [
        "1. ACTIVATE the row in (bank group BG, bank BA, row); wait tRCD.",
        "2. Issue READ (ACT_n=H, CAS_n=L, WE_n=H) with the column address; "
        "A12/BC_n selects BL8/BC4.",
        "3. After CL, the data burst returns on DQS_t/DQS_c edges (read DBI "
        "if enabled).",
        "4. PRECHARGE (or auto-precharge A10/AP) closes the row after tRAS / "
        "before the next ACTIVATE (tRP).",
    ]
    d["write_sequence"] = [
        "1. ACTIVATE the row; wait tRCD.",
        "2. Issue WRITE (ACT_n=H, CAS_n=L, WE_n=L) with the column address.",
        "3. After CWL, the controller drives the data burst on DQS edges "
        "(write DBI / data mask via DM_n/DBI_n); a write-CRC frame follows if "
        "enabled.",
        "4. Observe tWR write recovery, then PRECHARGE.",
    ]
    d["refresh_sequence"] = [
        "1. Ensure all banks (all-bank REFRESH) or the target bank (per-bank) "
        "are precharged.",
        "2. Issue REFRESH within the average interval tREFI (Fine Granularity "
        "1x/2x/4x).",
        "3. Wait tRFC before resuming commands.",
    ]
    d["error_sequence"] = [
        "CA parity error -> the DRAM blocks the command and asserts ALERT_n "
        "for the CA-parity error window (persistent error mode), then "
        "recovers.",
        "Write CRC error -> ALERT_n asserted; the write is not committed; the "
        "controller retries.",
    ]
    d["self_refresh_sequence"] = [
        "1. Precharge all banks; drive CKE LOW with the self-refresh command.",
        "2. The DRAM self-refreshes (Auto Self-Refresh / temperature-"
        "controlled / LP).",
        "3. Exit by raising CKE HIGH and waiting the self-refresh exit timing.",
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
        {"name": "DQ / DQS eye per speed bin", "purpose": "Verify the data eye "
         "and timing at DDR4-1600 .. DDR4-3200 (CL/CWL)."},
        {"name": "VrefDQ training", "purpose": "Confirm the on-die VREFDQ "
         "centers within the DQ eye (MR6, Range 1 / Range 2)."},
        {"name": "Write leveling", "purpose": "Align DQS to CK across fly-by "
         "command/address routing."},
        {"name": "ZQ calibration", "purpose": "Trim output-driver impedance "
         "and ODT against RZQ (240 ohm)."},
        {"name": "ODT Rtt_Nom / Rtt_WR / Rtt_PARK", "purpose": "Verify "
         "termination values and parked ODT."},
        {"name": "Write CRC / CA parity", "purpose": "Inject errors and "
         "confirm ALERT_n behavior and command blocking."},
        {"name": "Bank-group timing", "purpose": "Confirm tCCD_S vs tCCD_L "
         "(and tRRD_S/L, tWTR_S/L) back-to-back access behavior."},
    ]
    d["notes"] = (
        "DDR4 bring-up centers on PHY training (write leveling, read/write "
        "training, VrefDQ training), ZQ calibration, ODT (incl. Rtt_PARK), "
        "and the data eye per speed bin, plus verifying write-CRC / CA-parity "
        "ALERT_n behavior and bank-group timing. Conformance is established by "
        "JEDEC JESD79-4 compliance testing.")
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
    f["spec_version"] = "JEDEC JESD79-4 — DDR4 SDRAM"
    f["spec_lineage_ddrx"] = [
        "DDR (JESD79) -> DDR2 (JESD79-2) -> DDR3 (JESD79-3) -> DDR4 "
        "(JESD79-4) -> DDR5 (JESD79-5)."
    ]
    f["previous_versions_of_this_spec"] = [
        "DDR3 SDRAM (JESD79-3) — 1.5 V, 8 banks (no bank groups), external "
        "VREFDQ, no write CRC / CA parity / gear-down / DBI.",
    ]
    f["key_changes_vs_ddr3"] = [
        {"feature": "Voltage", "summary": "VDD/VDDQ lowered to 1.2 V (DDR3 "
         "1.5 V); VPP 2.5 V added."},
        {"feature": "Bank Groups", "summary": "New BG0/BG1 addressing tier "
         "(4 BG x 4 banks = 16 banks for x4/x8) with short/long timings."},
        {"feature": "Gear-down mode", "summary": "1/2-rate command/address "
         "capture for high speed bins."},
        {"feature": "Data Bus Inversion", "summary": "DBI on DM_n/DBI_n to "
         "reduce I/O power and SSO noise."},
        {"feature": "On-die VrefDQ", "summary": "VREFDQ moved on-die with "
         "controller-directed VrefDQ training (MR6)."},
        {"feature": "Write CRC", "summary": "8-bit data-bus write CRC with "
         "ALERT_n."},
        {"feature": "CA parity", "summary": "Command/address parity (PAR) with "
         "ALERT_n persistent error mode."},
        {"feature": "Command truth table", "summary": "ACT_n flag with "
         "multiplexed RAS_n/A16, CAS_n/A15, WE_n/A14."},
        {"feature": "ODT", "summary": "Rtt_PARK added (parked ODT)."},
    ]
    f["future_versions_industry_outline"] = [
        {"version": "DDR5 (JESD79-5)", "summary": "Two independent 32-bit "
         "(40-bit ECC) sub-channels, decision feedback equalization, on-die "
         "ECC, on-DIMM PMIC + SPD hub, same-bank refresh, 1.1 V. DDR4 is a "
         "single 64-bit channel and does NOT have these features."},
    ]
    f["backward_compat_traps"] = [
        {"trap_name": "Voltage_1p2_not_1p5",
         "rule": "DDR4 is 1.2 V; DDR3 is 1.5 V.",
         "trap": "Driving DDR4 at DDR3's 1.5 V rail is wrong."},
        {"trap_name": "Bank_groups_exist",
         "rule": "DDR4 has bank groups (BG0/BG1) with tCCD_S vs tCCD_L; DDR3 "
                 "does not.",
         "trap": "Treating DDR4 as flat-banked (DDR3-style) misses bank-group "
                 "timing."},
        {"trap_name": "ACT_n_flag",
         "rule": "DDR4 multiplexes RAS_n/CAS_n/WE_n with A16/A15/A14 behind "
                 "ACT_n.",
         "trap": "Using DDR3's dedicated RAS_n/CAS_n/WE_n encoding is wrong "
                 "for DDR4."},
        {"trap_name": "Not_DDR5",
         "rule": "DDR4 is a single 64-bit channel with no DFE, no on-die ECC, "
                 "and no DIMM PMIC; those are DDR5.",
         "trap": "Applying DDR5 two-sub-channel / DFE / PMIC assumptions to "
                 "DDR4 is wrong."},
    ]
    f["version_naming_history_note"] = (
        "DDR4 SDRAM is JEDEC Standard JESD79-4, the fourth generation of the "
        "DDRx double-data-rate synchronous DRAM lineage (DDR -> DDR2 -> DDR3 "
        "-> DDR4 -> DDR5). DDR4 succeeds DDR3 (JESD79-3) and precedes DDR5 "
        "(JESD79-5), adding bank groups, gear-down, DBI, on-die VrefDQ "
        "training, write CRC, and CA parity while lowering the supply to "
        "1.2 V.")
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
    f["command_truth_table"] = {
        "header_columns": ["Command", "ACT_n", "RAS_n/A16", "CAS_n/A15",
                           "WE_n/A14"],
        "rows": [
            ["ACTIVATE", "L", "row addr A16", "row addr A15", "row addr A14"],
            ["READ", "H", "H", "L", "H"],
            ["WRITE", "H", "H", "L", "L"],
            ["PRECHARGE", "H", "L", "H", "L"],
            ["REFRESH", "H", "L", "L", "H"],
            ["MRS", "H", "L", "L", "L"],
        ],
    }
    f["speed_bin_table"] = {
        "header_columns": ["Speed Bin", "Data Rate (MT/s)", "CK (MHz)"],
        "rows": [
            ["DDR4-1600", "1600", "800"],
            ["DDR4-1866", "1866", "933"],
            ["DDR4-2133", "2133", "1066"],
            ["DDR4-2400", "2400", "1200"],
            ["DDR4-2666", "2666", "1333"],
            ["DDR4-2933", "2933", "1466"],
            ["DDR4-3200", "3200", "1600"],
        ],
    }
    f["mode_register_table"] = {
        "header_columns": ["MR", "Key contents"],
        "rows": [
            ["MR0", "BL8/BC4/OTF, CL, burst type, tWR, DLL reset"],
            ["MR1", "DLL enable, drive strength, Rtt_Nom, AL, write leveling"],
            ["MR2", "CWL, Rtt_WR, write CRC enable, ASR"],
            ["MR3", "MPR, gear-down, PDA, fine-granularity refresh"],
            ["MR4", "CAL, preamble, self-refresh abort, max power saving"],
            ["MR5", "CA parity, CRC status, DBI (read/write), Rtt_PARK"],
            ["MR6", "tCCD_L, VrefDQ training enable/range/value"],
        ],
    }
    f["burst_length_table"] = {
        "header_columns": ["Burst", "Beats", "Selection"],
        "rows": [
            ["BL8", "8", "fixed or OTF"],
            ["BC4", "4 (chop)", "fixed or OTF (A12/BC_n)"],
        ],
    }
    f["odt_table"] = {
        "header_columns": ["ODT", "Register", "Purpose"],
        "rows": [
            ["Rtt_Nom", "MR1", "nominal ODT (ODT pin)"],
            ["Rtt_WR", "MR2", "dynamic ODT during writes"],
            ["Rtt_PARK", "MR5", "parked ODT when ODT deasserted (new in DDR4)"],
        ],
    }
    f["bank_group_table"] = {
        "header_columns": ["Width", "Bank Groups", "Banks/Group", "Total "
                           "Banks"],
        "rows": [
            ["x4", "4", "4", "16"],
            ["x8", "4", "4", "16"],
            ["x16", "2", "4", "8"],
        ],
    }
    f["encoding_note"] = (
        "DDR4 commands are encoded behind the ACT_n flag (ACT_n LOW = "
        "ACTIVATE; ACT_n HIGH multiplexes RAS_n/A16, CAS_n/A15, WE_n/A14 to "
        "encode READ/WRITE/PRECHARGE/REFRESH/MRS and carry high address bits). "
        "Bursts are BL8 / BC4 (on-the-fly). Mode registers MR0..MR6 hold the "
        "configuration; write CRC (8-bit) and CA parity protect the data and "
        "command buses with ALERT_n.")
    f["tables"] = [
        "Command truth table (ACT_n / RAS_n-A16 / CAS_n-A15 / WE_n-A14)",
        "Speed-bin table (DDR4-1600 .. DDR4-3200)",
        "Mode-register table (MR0..MR6)",
        "Burst-length table (BL8 / BC4)",
        "ODT table (Rtt_Nom / Rtt_WR / Rtt_PARK)",
        "Bank-group table (x4/x8/x16)",
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
        "Single 64-bit (72-bit ECC) double-data-rate channel at VDD/VDDQ = "
        "1.2 V (VPP 2.5 V).",
        "Bank Groups (BG0/BG1; 4 BG x 4 banks = 16 banks for x4/x8) with "
        "short/long bank-group timings (tCCD_S/L, tRRD_S/L, tWTR_S/L).",
        "Gear-down (1/2-rate) command/address mode (MR3).",
        "Data Bus Inversion on DM_n/DBI_n (MR5).",
        "Internal (on-die) VrefDQ generation with VrefDQ training (MR6).",
        "Write CRC (8-bit, MR2) and CA parity (PAR, MR5), both reported on "
        "ALERT_n.",
        "ACT_n command truth table (RAS_n/A16, CAS_n/A15, WE_n/A14 "
        "multiplexed).",
        "BL8 / BC4 (on-the-fly) bursts; MR0..MR6; ODT Rtt_Nom/Rtt_WR/Rtt_PARK; "
        "ZQ calibration against RZQ (240 ohm).",
    ]
    f["must_not_have_properties"] = [
        "Two independent 32-bit sub-channels (that is DDR5, not DDR4).",
        "Decision Feedback Equalization (DFE) in the DQ receiver (DDR5).",
        "On-die ECC or an on-DIMM PMIC / SPD hub (DDR5).",
        "A 1.5 V supply with no bank groups and external VREFDQ (that is "
        "DDR3).",
        "A dedicated full-speed Write Clock (WCK) (that is LPDDR5).",
        "A 1024-bit TSV-stacked interface (that is HBM3).",
    ]
    f["compliance_failure_modes"] = [
        {"mode": "CA parity error", "trigger": "PAR mismatch; the command is "
         "blocked and ALERT_n asserted for the error window."},
        {"mode": "Write CRC error", "trigger": "Write-CRC mismatch; ALERT_n "
         "asserted; the write is not committed."},
        {"mode": "Mistrained VREFDQ", "trigger": "VrefDQ training did not "
         "center the DQ reference; data errors."},
        {"mode": "Timing violation", "trigger": "tRCD/tRP/tRAS/tRFC or "
         "bank-group timing violated."},
    ]
    f["min_constraint"] = (
        "A DDR4 device requires a correct JESD79-4 power-up/init sequence "
        "(VPP-then-VDD/VDDQ at 1.2 V, DLL reset, ZQ calibration, MRS of "
        "MR0..MR6, VrefDQ training) before normal ACTIVATE/READ/WRITE/"
        "PRECHARGE/REFRESH commands.")
    f["ddr4_distinguishers"] = (
        "DDR4 is identified by ALL of: JESD79-4; a single 64-bit (72-bit ECC) "
        "double-data-rate channel at 1.2 V; Bank Groups with short/long "
        "timings; gear-down mode; Data Bus Inversion; on-die VrefDQ training; "
        "write CRC and CA parity reported on ALERT_n; and the ACT_n command "
        "truth table. This is distinct from DDR3 (1.5 V, no bank groups, "
        "external VREFDQ, no write CRC / CA parity / gear-down), from DDR5 "
        "(two 32-bit sub-channels, DFE, on-die ECC, DIMM PMIC, 1.1 V), from "
        "LPDDR5 (dedicated WCK), and from HBM3 (1024-bit TSV-stacked).")
    _write(p, d)


# ----------------------------------------------------------------------
# L17 — channel / signal catalog. (force-overwrite)
# ----------------------------------------------------------------------
def _l17(gd: Path) -> None:
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["channels"] = [
        {"name": "CK_t / CK_c", "direction": "input (differential)",
         "purpose": "Forwarded differential clock; commands captured on the "
                    "rising edge.", "active_levels": "differential",
         "idle_level": "toggling clock"},
        {"name": "DQ[63:0] (module) / [3:0],[7:0],[15:0] (device)",
         "direction": "bidirectional",
         "purpose": "Data bus; double data rate on DQS edges.",
         "active_levels": "POD12", "idle_level": "Hi-Z / terminated to VDDQ"},
        {"name": "DQS_t / DQS_c", "direction": "bidirectional (differential)",
         "purpose": "Data strobe; one pair per byte (two pairs on x16).",
         "active_levels": "differential", "idle_level": "preamble/idle"},
        {"name": "DM_n / DBI_n", "direction": "input/bidirectional",
         "purpose": "Data mask / Data Bus Inversion (shared pin per byte).",
         "active_levels": "POD12", "idle_level": "high"},
        {"name": "ACT_n + RAS_n/A16 + CAS_n/A15 + WE_n/A14 + A[13:0] + BG + BA",
         "direction": "input",
         "purpose": "Command / address bus behind the ACT_n flag.",
         "active_levels": "POD12", "idle_level": "deselected"},
        {"name": "PAR / ALERT_n", "direction": "input / output",
         "purpose": "Command-address parity in; CA-parity / write-CRC / "
                    "connectivity alert out.",
         "active_levels": "POD12", "idle_level": "ALERT_n high (no error)"},
        {"name": "CKE / CS_n / ODT / RESET_n / ZQ",
         "direction": "input",
         "purpose": "Clock enable / chip select / ODT control / reset / "
                    "calibration reference.",
         "active_levels": "POD12", "idle_level": "per state"},
    ]
    f["logical_signaling_levels"] = [
        {"name": "POD12", "meaning": "Pseudo Open Drain at 1.2 V; terminated "
         "to VDDQ via on-die termination."},
        {"name": "Differential CK / DQS", "meaning": "Differential clock and "
         "strobe pairs."},
    ]
    f["packet_types_summary"] = [
        {"class": "Command", "members": list(_COMMANDS),
         "count": len(_COMMANDS)},
        {"class": "Burst", "members": list(_BURST_LENGTHS),
         "count": len(_BURST_LENGTHS)},
        {"class": "Mode register", "members": list(_MODE_REGISTERS),
         "count": len(_MODE_REGISTERS)},
    ]
    cc = _ensure_dict(f, "channel_counts")
    cc.update({
        "channel_width_bits": _DATA_WIDTH_BITS,
        "channel_width_bits_ecc": _DATA_WIDTH_BITS_ECC,
        "device_widths": list(_DEVICE_WIDTHS),
        "bank_groups_x4_x8": _BANK_GROUPS_X4_X8,
        "banks_x4_x8": _BANKS_X4_X8,
        "mode_register_count": len(_MODE_REGISTERS),
        "command_count": len(_COMMANDS),
        "write_crc_bits": _WRITE_CRC_BITS,
        "max_data_rate_MTps": _MAX_SPEED_MTS,
        "single_channel": True,
    })
    f["global_signals"] = [
        {"name": "CK_t/CK_c", "purpose": "Forwarded differential clock."},
        {"name": "RESET_n", "purpose": "Asynchronous device reset."},
        {"name": "ALERT_n", "purpose": "CA-parity / write-CRC / connectivity "
         "error indication."},
        {"name": "ZQ", "purpose": "External RZQ (240 ohm) calibration "
         "reference."},
    ]
    f["dependency_graph"] = {
        "common_rule": "The JESD79-4 power-up/init (DLL reset, ZQ calibration, "
        "MRS of MR0..MR6, VrefDQ training) must complete before normal "
        "commands. A bank must be ACTIVE (tRCD met) before a column "
        "READ/WRITE; PRECHARGE (tRP) closes the row.",
        "data_dependency": "A READ/WRITE requires (1) the device initialized "
        "and trained, (2) the target row ACTIVE, (3) bank-group timing "
        "(tCCD_S/L) satisfied; write CRC / CA parity protect data and "
        "command.",
    }
    f["handshake_pairs"] = [
        {"name": "ACTIVATE/READ", "from": "controller", "to": "DRAM",
         "rule": "ACTIVATE opens the row; READ after tRCD."},
        {"name": "WRITE/CRC", "from": "controller", "to": "DRAM",
         "rule": "WRITE drives data CWL later; a write-CRC frame follows when "
                 "enabled (ALERT_n on error)."},
        {"name": "CA parity", "from": "controller", "to": "DRAM",
         "rule": "PAR covers command/address; ALERT_n on a parity error."},
        {"name": "ODT", "from": "controller", "to": "DRAM",
         "rule": "ODT pin selects Rtt_Nom; Rtt_PARK applies when deasserted."},
    ]
    f["ordering_rules"] = {
        "bit_order_on_wire": "POD12 single-ended CA/DQ; differential CK/DQS; "
        "double data rate on DQS edges; BL8/BC4 burst order.",
        "command_order": "ACTIVATE -> READ/WRITE -> PRECHARGE per bank, "
        "subject to tRCD/tRP/tRAS and bank-group timing.",
        "bank_group": "Different-bank-group accesses run at tCCD_S; same-group "
        "at tCCD_L.",
    }
    # Overwrite DDR3-synth residue keys with DDR4 values.
    f["power_pins"] = [
        {"name": "VDD", "purpose": "1.2 V core supply (DDR4)."},
        {"name": "VDDQ", "purpose": "1.2 V DQ I/O supply."},
        {"name": "VPP", "purpose": "2.5 V wordline / activating pump supply "
         "(new in DDR4)."},
        {"name": "VREFCA", "purpose": "External command/address reference "
         "(VREFDQ is internal)."},
        {"name": "VSS", "purpose": "Ground."},
        {"name": "VSSQ", "purpose": "DQ Ground."},
    ]
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
        "Controller-centric memory bus: a memory controller + DDR4 PHY drives "
        "a single 64-bit (72-bit ECC) command/address/data channel to one or "
        "more ranks of DDR4 SDRAMs on a DIMM. Command/address may be fly-by "
        "routed (write leveling compensates); RDIMM/LRDIMM re-clock it through "
        "an RCD.")
    f["supported_topologies"] = [
        {"name": "Direct / on-package", "description": "Controller to a single "
         "DDR4 device or soldered-down devices."},
        {"name": "UDIMM", "description": "Unbuffered DIMM."},
        {"name": "RDIMM", "description": "Registered DIMM: an RCD re-clocks "
         "command/address."},
        {"name": "LRDIMM", "description": "Load-reduced DIMM: RCD + Data "
         "Buffers (DB)."},
        {"name": "Multi-rank", "description": "Multiple ranks selected by "
         "per-rank CS_n."},
    ]
    f["master_slave_role_summary"] = [
        {"role": "Memory controller (master)", "description": "Issues all "
         "commands, owns timing/training, drives CK/CA and write data."},
        {"role": "DDR4 SDRAM (slave)", "description": "Responds to commands; "
         "returns read data on DQS; reports errors on ALERT_n."},
        {"role": "RCD", "description": "Re-clocks command/address on "
         "RDIMM/LRDIMM."},
        {"role": "Data Buffer (DB)", "description": "Buffers DQ/DQS on "
         "LRDIMM."},
    ]
    f["interconnect_role"] = (
        "DDR4 is a synchronous memory bus: the controller is the single master "
        "of a single 64-bit channel, addressing rows/columns within bank "
        "groups and banks. There is no peer-to-peer or packetized routing; "
        "ordering and timing are governed by the command protocol and the "
        "bank-group timing parameters.")
    f["memory_vs_peripheral_regions"] = (
        "DDR4 is the main-memory region itself: it is addressed by rank / bank "
        "group / bank / row / column, not by a peripheral register address. "
        "Configuration lives in the mode registers (MR0..MR6).")
    dc = _ensure_dict(f, "device_classification")
    for k in [k for k in list(dc.keys()) if "DDR3" in str(k) or "ddr3" in str(k)]:
        dc.pop(k, None)
    dc["controller"] = "Master; issues commands, owns training and timing."
    dc["dram"] = "Slave; single 64-bit channel, x4/x8/x16, bank groups."
    dc["rcd"] = "Registering Clock Driver (RDIMM/LRDIMM)."
    dc["data_buffer"] = "Data Buffer (LRDIMM)."
    f["default_signal_values_evidence_tables"] = [
        "DDR4 channel / rank / bank-group / bank / row / column addressing",
        "DIMM topology figure (UDIMM / RDIMM / LRDIMM)",
        "Fly-by command/address routing + write leveling",
        "Bank-group timing table (tCCD_S / tCCD_L)",
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
        "signaling": "POD12 (Pseudo Open Drain, 1.2 V) single-ended CA/DQ; "
                     "differential CK_t/CK_c and DQS_t/DQS_c",
        "vdd_volts": _VDD_V,
        "vddq_volts": _VDDQ_V,
        "vpp_volts": _VPP_V,
        "data_rate": "double data rate on DQS edges; speed bins DDR4-1600 .. "
                     "DDR4-3200",
        "channel_width_bits": _DATA_WIDTH_BITS,
        "odt": "Rtt_Nom / Rtt_WR / Rtt_PARK to VDDQ; RZQ = 240 ohm",
        "vref": "external VREFCA; internal (on-die) VREFDQ with training",
        "data_bus_inversion": True,
        "single_channel": True,
    }
    f["notes"] = (
        "DDR4 (JESD79-4) fixes the device-level electrical and protocol model "
        "(POD12 1.2 V signaling, differential CK/DQS, double data rate, bank "
        "groups, gear-down, DBI, on-die VrefDQ training, write CRC, CA parity, "
        "ODT incl. Rtt_PARK, ZQ calibration, speed bins). It does NOT impose "
        "PDK-specific SDC/floorplan constraints on a controller; the "
        "interoperability-critical constraints are the speed-bin timings, "
        "training, ODT, and the write-CRC / CA-parity behavior. SI/board "
        "routing (fly-by, RCD/DB) is a module/board concern.")
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
        {"name": "Multi-Purpose Register (MPR)", "purpose": "Read predefined / "
         "training / error / temperature data without the array (MR3)."},
        {"name": "Connectivity Test (CT) mode", "purpose": "Boundary "
         "connectivity test via TEN / ALERT_n."},
        {"name": "ALERT_n", "purpose": "CA-parity / write-CRC / connectivity "
         "error reporting."},
        {"name": "CRC error status (MR5)", "purpose": "Latched write-CRC "
         "error status."},
        {"name": "Temperature sensor", "purpose": "On-die temperature for "
         "TCR."},
    ]
    f["internal_diagnostics_observability"] = [
        "Mode-register read-back via MPR.",
        "ALERT_n error indication (parity / CRC / connectivity).",
        "Latched CRC error status (MR5).",
        "VrefDQ training and write-leveling status.",
        "Temperature readout.",
    ]
    f["out_of_band_test_facilities"] = [
        "JEDEC JESD79-4 device compliance testing.",
        "Module SPD-based configuration and vendor ATE (implementation-"
        "defined).",
    ]
    f["notes"] = (
        "DDR4's protocol-level DFT surface is the Multi-Purpose Register, "
        "Connectivity Test mode, ALERT_n error reporting, latched CRC status, "
        "and the temperature sensor. Controller/PHY scan/BIST remain SoC "
        "concerns; conformance is established by JEDEC JESD79-4 testing.")
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
        {"state": "Active", "name": "Active", "description": "Normal command "
         "operation; banks may be active."},
        {"state": "Precharge power-down", "name": "Precharge PD",
         "description": "CKE LOW with all banks precharged; fast exit."},
        {"state": "Active power-down", "name": "Active PD",
         "description": "CKE LOW with a row open."},
        {"state": "Self-refresh", "name": "Self-Refresh", "description": "CKE "
         "LOW; the DRAM refreshes itself (ASR / temperature-controlled / LP)."},
        {"state": "Maximum Power Saving Mode", "name": "MPSM",
         "description": "Deep idle low-power mode (MR4)."},
    ]
    f["wakeup_mechanism"] = (
        "Power-down and self-refresh are entered/exited via CKE (and the "
        "self-refresh command); exit observes the defined power-down / "
        "self-refresh exit timings before commands resume.")
    f["power_rails"] = [
        {"rail": "VDD = 1.2 V", "purpose": "Core supply."},
        {"rail": "VDDQ = 1.2 V", "purpose": "DQ I/O supply."},
        {"rail": "VPP = 2.5 V", "purpose": "Wordline / activating pump supply "
         "(new in DDR4)."},
        {"rail": "VREFCA", "purpose": "Command/address reference (external)."},
        {"rail": "VSS / VSSQ", "purpose": "Ground."},
    ]
    f["ddr4_power_considerations"] = (
        "DDR4 lowers VDD/VDDQ to 1.2 V (from DDR3's 1.5 V) and adds a separate "
        "VPP = 2.5 V wordline pump rail. Data Bus Inversion, Rtt_PARK, Fine "
        "Granularity Refresh, temperature-controlled refresh, power-down, and "
        "Maximum Power Saving Mode all reduce energy.")
    f["notes"] = (
        "DDR4 power intent is the 1.2 V VDD/VDDQ + 2.5 V VPP rail set with the "
        "CKE-controlled power-down / self-refresh / MPSM states and "
        "ODT/DBI/refresh energy features. Fine-grained controller power "
        "domains are an SoC concern.")
    # Overwrite DDR3-synth residue keys with DDR4 values.
    f["voltage_classes_table"] = {
        "header_columns": ["Class", "VDD", "VDDQ", "VPP", "Applicable"],
        "rows": [
            ["DDR4", "1.2 V", "1.2 V", "2.5 V", "JESD79-4 DDR4 SDRAM"],
        ],
    }
    lpm = f.get("low_power_modes_summary")
    if isinstance(lpm, dict):
        lpm.pop("Deep_Power_Down", None)
        lpm["Maximum_Power_Saving_Mode"] = (
            "Deep idle low-power mode (MR4) for DDR4.")
        lpm["Self_Refresh"] = (
            "CKE LOW self-refresh with Auto Self-Refresh (ASR) and "
            "temperature-controlled / low-power ranges.")
        lpm["Power_Down"] = "Precharge / active power-down (CKE LOW)."
    pds = f.get("power_domains_summary")
    if isinstance(pds, dict):
        for k in [k for k in list(pds.keys()) if "DDR3" in str(k)]:
            pds.pop(k, None)
        pds["VDD"] = "1.2 V core supply (DDR4)."
        pds["VDDQ"] = "1.2 V DQ I/O supply."
        pds["VPP"] = "2.5 V wordline pump supply (new in DDR4)."
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
        "Power-up / initialization (VPP-then-VDD/VDDQ, DLL reset, ZQ "
        "calibration, MRS MR0..MR6).",
        "VrefDQ training and write leveling.",
        "ACTIVATE/READ/WRITE/PRECHARGE timing (tRCD/tRP/tRAS/tRC/tRFC/tWR).",
        "Bank-group timing (tCCD_S/L, tRRD_S/L, tWTR_S/L); tFAW.",
        "Burst BL8/BC4 and on-the-fly selection.",
        "Gear-down (1/2-rate) command/address mode.",
        "Data Bus Inversion (read/write DBI) and data mask.",
        "Write CRC (8-bit) injection -> ALERT_n; write not committed.",
        "CA parity injection -> ALERT_n; command blocked (persistent error).",
        "ODT (Rtt_Nom/Rtt_WR/Rtt_PARK) and ZQ calibration.",
        "Refresh (all-bank/per-bank/fine-granularity); tREFI/tRFC.",
        "Self-refresh / power-down / MPSM entry-exit.",
        "Speed-bin sweep DDR4-1600 .. DDR4-3200 (CL/CWL).",
    ]
    f["notes"] = (
        "DDR4 does not ship an embedded testbench, but JESD79-4 implies a "
        "verification plan spanning init/training, the command/timing model, "
        "bank-group timing, bursts, gear-down, DBI, write CRC and CA parity "
        "(ALERT_n), ODT/ZQ, refresh, and the power-down states. JEDEC "
        "JESD79-4 compliance testing supplies the formal suite.")
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
        "Write CRC (8-bit) on the data bus detects write-data corruption "
        "(ALERT_n).",
        "Command/Address parity (even, PAR pin) detects command corruption "
        "(ALERT_n; command blocked).",
        "Connectivity Test mode detects connectivity faults.",
        "Refresh (incl. fine-granularity / temperature-controlled) preserves "
        "data retention.",
    ]
    f["anti_tampering_features"] = []
    f["confidentiality_features"] = []
    f["authentication_features"] = []
    f["future_security_pointers"] = [
        "DDR4's base protocol provides no cryptographic confidentiality or "
        "authentication; write CRC and CA parity are anti-corruption only.",
        "Memory encryption / RowHammer mitigation (TRR) / Rowhammer-aware "
        "refresh are controller- / system-level features layered above the "
        "DDR4 device protocol.",
    ]
    f["notes"] = (
        "DDR4 is a commodity DRAM transport: its built-in protections are "
        "anti-corruption (write CRC, CA parity, connectivity test) and data "
        "retention (refresh). The bus carries plaintext; cryptographic "
        "confidentiality / authentication and RowHammer mitigation are "
        "provided above the DDR4 device by the memory controller / system.")
    # Overwrite DDR3-synth residue keys with DDR4 values.
    f["security_summary"] = (
        "DDR4 SDRAM has NO confidentiality, authentication, or access-control "
        "features in the device protocol; its protections are anti-corruption "
        "(write CRC, CA parity) and data retention (refresh).")
    f["security_features_at_protocol_level"] = [
        {"feature": "Write CRC", "description": "8-bit data-bus CRC (MR2) with "
         "ALERT_n reporting; anti-corruption only."},
        {"feature": "CA parity", "description": "Even-parity PAR pin (MR5) "
         "over command/address with ALERT_n; anti-corruption only."},
        {"feature": "Connectivity Test", "description": "Boundary connectivity "
         "test via TEN / ALERT_n."},
    ]
    f["no_confidentiality"] = (
        "DDR4 carries plaintext data on DQ; there is no link encryption in "
        "the device protocol.")
    f["no_authentication"] = (
        "DDR4 has no command authentication; any controller driving the bus "
        "can issue commands.")
    f["no_access_control"] = (
        "DDR4 has no built-in write-protect or access-control regions in the "
        "device protocol.")
    f["rowhammer_class_vulnerabilities"] = (
        "DDR4 is subject to RowHammer-class disturbance; mitigation (Target "
        "Row Refresh / refresh-rate management) is a controller / system "
        "feature layered above the DDR4 device.")
    f["comparison_to_sibling_standards"] = (
        "Like DDR3, DDR4 provides no cryptographic security at the device "
        "level; DDR4 adds write CRC and CA parity (anti-corruption) over "
        "DDR3. Memory encryption and RowHammer mitigation remain "
        "controller/system features in both.")
    _write(p, d)
