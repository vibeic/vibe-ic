"""Embedded MultiMediaCard (eMMC, JEDEC JESD84-B51 / eMMC 5.1) protocol synth.

Protocol of the Phase-1 doc-extraction sweep. ic_class-gated overlay for a doc
that exhibits the eMMC structural signature: an EMBEDDED, managed-NAND storage
device DERIVED FROM the MultiMediaCard / SD command protocol (CLK / CMD /
DAT[7:0] + 48-bit commands + R1..R5 responses + the idle/ready/ident/stby/tran/
data/rcv/prg device state machine) that adds the eMMC-SPECIFIC structure that
no removable SD card has — the 8-bit DAT bus (DAT[7:0]), the Data Strobe (DS)
for HS400, the Hardware Reset pin (RST_n), the 512-byte Extended CSD (EXT_CSD)
configuration register, hardware partitions (Boot Area Partition 1/2, RPMB,
General Purpose Partitions selected by PARTITION_CONFIG), the boot operation
(boot mode / alternative boot), the HS200/HS400 speed modes, and the managed-
NAND feature set (HPI, Background Operations, Cache, Sanitize/TRIM/Discard,
Secure Erase, Field Firmware Update, Packed commands, Command Queuing/CMDQ).
Applies JEDEC JESD84-B51 (eMMC 5.1) spec-canonical content to L1-L23.

Doctrine — GENERAL not keyword: detection uses canonical STRUCTURAL eMMC
signatures (8-bit DAT bus / Data Strobe / RST_n / EXT_CSD / boot+RPMB
partitions / HS400 / CMDQ-FFU-HPI managed-NAND features) read from the L-doc
CONTENT blob ONLY. It NEVER reads the input-document filename or the benchmark
folder name. (A prior code review flagged exactly a filename read as a HIGH
defect on the AHB+APB detector; this module does not repeat it.)

------------------------------------------------------------------------------
CHICKEN-AND-EGG MUTEX vs the SD/MMC detector (the hard part — like SMBus-vs-I2C
and I3C-extends-I2C)
------------------------------------------------------------------------------
eMMC DERIVES FROM the MMC/SD card protocol and shares the CLK/CMD/DAT bus, the
48-bit command framing, the OCR/CID/CSD registers and the device state machine.
The existing runner-side ``_is_sdmmc`` predicate (v0.1.84) covers SD/MMC and
fires on one of:
    (a) CMD0 + ACMD41 + CID + CSD + OCR                       (SD init handshake)
    (b) "SD Card" + "CMD line" + "DAT"
    (c) "MultiMediaCard" + "CMD line"
    (d) "SD Memory Card" + (CID or CSD)
All four are SD-PRIMARY: they key on the SD-only init command ACMD41, the
SD-card product names ("SD Card" / "SD Memory Card"), or the removable
"MultiMediaCard" card name. A genuine eMMC datasheet does NOT use ACMD41 (eMMC
uses SEND_OP_COND=CMD1, never the application ACMD41), is NOT an "SD Card" /
"SD Memory Card", and is NOT a removable "MultiMediaCard" — it is an EMBEDDED
device. So on a real eMMC L1+L2 blob ``_is_sdmmc`` stays False (empirically
confirmed at build time: ACMD41 / "SD Card" / "SD Memory Card" /
"MultiMediaCard" are all ABSENT from the generated L1+L2 blob — see the field
report). To avoid cross-firing in BOTH directions:

  (a) ``is_emmc`` REQUIRES eMMC-ONLY structure that a removable SD/MMC card
      spec does NOT contain — the embedded managed-NAND signature: at least
      TWO of {8-bit DAT bus (DAT[7:0]), Data Strobe (DS) for HS400, RST_n
      hardware reset, EXT_CSD 512-byte register, Boot Area Partition, RPMB,
      General Purpose Partition + PARTITION_CONFIG, HS400, CMDQ/Command
      Queuing, FFU/Field Firmware Update, HPI/High Priority Interrupt,
      Background Operations} — AND DEFERS when the doc is SD-PRIMARY (card
      detect, SDIO, 4-bit-only DAT, SD Security/CPRM, card insertion/removal,
      mechanical write-protect switch, ACMD41) WITHOUT the eMMC-only tokens.

  (b) This module is wired to run AFTER the SD/MMC synth and FORCE-ASSIGNS
      (direct assignment, NOT setdefault) every L1/L2/L3/.../L23 key the
      SD/MMC synth would populate with the eMMC-canonical value — the cross-
      protocol force-overwrite doctrine (NVMe-on-PCIe, I3C-extends-I2C,
      SMBus-on-I2C). So even if a future doc phrasing tripped ``_is_sdmmc``,
      its SD output is fully replaced by eMMC-canonical values and cannot leak
      through.

Public entry: ``apply_emmc_synth(generated_docs_dir, is_emmc, emmc_ic_name)``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import l_doc_generator_stamp as _stamp


def _read(p: Path) -> dict:
    return json.loads(p.read_text())


def _write(p: Path, d: dict) -> None:
    # THE L-document write chokepoint: stamps the producing release onto
    # the document, then serialises it byte-identically to before.
    _stamp.dump(p, d)


def _ensure_dict(d: dict, key: str) -> dict:
    """Return d[key] as a dict, replacing a pre-existing None/empty/non-dict."""
    v = d.get(key)
    if not isinstance(v, dict):
        v = {}
        d[key] = v
    return v


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

# Canonical eMMC structural facts (JEDEC JESD84-B51, eMMC 5.1, Feb 2015).
_EMMC_BUS_SIGNALS = [
    "CLK — clock (host-driven; data on both edges in DDR/HS400)",
    "CMD — bidirectional command/response line (48-bit token, CRC7)",
    "DAT[7:0] — up to 8-bit bidirectional data bus (1/4/8-bit selectable)",
    "DS — Data Strobe (device-sourced read strobe, HS400 only)",
    "RST_n — active-low hardware reset input",
    "VCC — NAND core / memory supply",
    "VCCQ — I/O and controller supply",
    "VSS / VSSQ — ground references",
]
_EMMC_SPEED_MODES = [
    {"name": "Backward compatible", "clock_mhz": 26, "rate": "SDR",
     "bus_width": "1/4/8-bit", "io_v": "3.3V", "max_mbps": 26},
    {"name": "High Speed SDR", "clock_mhz": 52, "rate": "SDR",
     "bus_width": "1/4/8-bit", "io_v": "3.3V/1.8V", "max_mbps": 52},
    {"name": "High Speed DDR", "clock_mhz": 52, "rate": "DDR",
     "bus_width": "4/8-bit", "io_v": "3.3V/1.8V", "max_mbps": 104},
    {"name": "HS200", "clock_mhz": 200, "rate": "SDR (single-ended)",
     "bus_width": "8-bit", "io_v": "1.8V/1.2V", "max_mbps": 200},
    {"name": "HS400", "clock_mhz": 200, "rate": "DDR with Data Strobe (DS)",
     "bus_width": "8-bit", "io_v": "1.8V/1.2V", "max_mbps": 400},
]
_EMMC_PARTITIONS = [
    "User Data Area",
    "Boot Area Partition 1",
    "Boot Area Partition 2",
    "Replay Protected Memory Block (RPMB)",
    "General Purpose Partition 1..4 (GPP)",
]
_EMMC_DEVICE_STATES = [
    "Inactive", "Idle", "Ready", "Identification", "Stand-by", "Transfer",
    "Sending-data", "Receive-data", "Programming", "Disconnect",
]
_EMMC_COMMANDS = [
    {"index": "CMD0", "name": "GO_IDLE_STATE",
     "note": "reset to Idle; arg 0xF0F0F0F0/0xFFFFFFFA = boot modes"},
    {"index": "CMD1", "name": "SEND_OP_COND",
     "note": "send/poll OCR (voltage + busy + access mode); eMMC uses CMD1, "
             "NOT the SD application command ACMD41"},
    {"index": "CMD2", "name": "ALL_SEND_CID", "note": "device returns CID"},
    {"index": "CMD3", "name": "SET_RELATIVE_ADDR",
     "note": "host assigns the 16-bit RCA"},
    {"index": "CMD6", "name": "SWITCH",
     "note": "write one Extended CSD byte (bus width, HS_TIMING, "
             "PARTITION_CONFIG, ...)"},
    {"index": "CMD7", "name": "SELECT/DESELECT_CARD",
     "note": "select (stby->tran) or deselect"},
    {"index": "CMD8", "name": "SEND_EXT_CSD",
     "note": "read the 512-byte Extended CSD (eMMC redefines CMD8; SD CMD8 is "
             "SEND_IF_COND)"},
    {"index": "CMD9", "name": "SEND_CSD", "note": "read the 128-bit CSD"},
    {"index": "CMD10", "name": "SEND_CID", "note": "read the 128-bit CID"},
    {"index": "CMD12", "name": "STOP_TRANSMISSION",
     "note": "stop open-ended transfer / HPI"},
    {"index": "CMD13", "name": "SEND_STATUS",
     "note": "read device status (and queue status in CMDQ mode)"},
    {"index": "CMD16", "name": "SET_BLOCKLEN", "note": "default 512 bytes"},
    {"index": "CMD17", "name": "READ_SINGLE_BLOCK", "note": ""},
    {"index": "CMD18", "name": "READ_MULTIPLE_BLOCK", "note": ""},
    {"index": "CMD23", "name": "SET_BLOCK_COUNT",
     "note": "predefined count + Reliable Write + Context ID + Packed flag"},
    {"index": "CMD24", "name": "WRITE_BLOCK", "note": ""},
    {"index": "CMD25", "name": "WRITE_MULTIPLE_BLOCK", "note": ""},
    {"index": "CMD35/36", "name": "ERASE_GROUP_START/END", "note": ""},
    {"index": "CMD38", "name": "ERASE",
     "note": "erase / TRIM / Discard / Secure Erase / Sanitize per argument"},
    {"index": "CMD44/45", "name": "QUEUED_TASK_PARAMS/ADDRESS",
     "note": "Command Queuing task enqueue"},
    {"index": "CMD46/47", "name": "EXECUTE_READ/WRITE_TASK",
     "note": "Command Queuing data transfer"},
    {"index": "CMD48", "name": "CMDQ_TASK_MGMT",
     "note": "discard a queued task / the whole queue"},
]
_EMMC_EXT_CSD_FIELDS = [
    "SEC_COUNT (capacity in 512-byte sectors)",
    "BUS_WIDTH (1/4/8-bit, SDR/DDR)",
    "HS_TIMING (backward / high-speed / HS200 / HS400)",
    "PARTITION_CONFIG (active partition / boot partition select)",
    "BOOT_CONFIG / BOOT_BUS_CONDITIONS",
    "PARTITIONING_SUPPORT / PARTITIONS_ATTRIBUTE / GP_SIZE_MULT / ENH_SIZE_MULT",
    "RPMB_SIZE_MULT",
    "RST_n_FUNCTION (hardware reset enable)",
    "CACHE_CTRL / CACHE_SIZE",
    "BKOPS_EN / BKOPS_START / BKOPS_STATUS",
    "SANITIZE_START",
    "SEC_FEATURE_SUPPORT / SEC_ERASE_MULT",
    "FFU_STATUS / MODE_CONFIG / MODE_OPERATION_CODES",
    "CMDQ_MODE_EN / CMDQ_DEPTH",
]
_EMMC_MANAGED_NAND = [
    "Wear leveling", "Bad-block management", "ECC",
    "High Priority Interrupt (HPI)", "Background Operations (BKOPS)",
    "Cache (with FLUSH_CACHE)", "Sanitize", "TRIM", "Discard",
    "Secure Erase / Secure TRIM", "Field Firmware Update (FFU)",
    "Packed commands", "Command Queuing (CMDQ, up to 32 tasks)",
]


# ----------------------------------------------------------------------
# Module-level CONTENT-ONLY detector (the runner wires this; evaluated on the
# input_doc-augmented L-doc blob, NEVER on a filename).
# ----------------------------------------------------------------------
def is_emmc(blob: str) -> bool:
    """eMMC (JEDEC JESD84) — an EMBEDDED managed-NAND storage device DERIVED
    FROM the MMC/SD command protocol.

    MUTEX vs SD/MMC: a removable SD/MMC card spec carries the SD-PRIMARY
    init/name tokens (ACMD41 / "SD Card" / "SD Memory Card" /
    "MultiMediaCard") but NONE of the eMMC-only embedded managed-NAND
    structure below. Requiring at least TWO eMMC-only structural features
    (8-bit DAT bus / Data Strobe / RST_n / EXT_CSD / boot+RPMB partitions /
    HS400 / CMDQ / FFU / HPI / Background Operations) keeps the predicate False
    on a removable SD/MMC document while firing on a genuine eMMC doc. All
    checks read ``blob`` only — no filename / folder / benchmark-name read.
    """
    if not blob:
        return False
    low = blob.lower()

    # --- eMMC-ONLY structural features (absent from a removable SD/MMC card) ---
    eight_bit_dat = (
        "DAT[7:0]" in blob
        or "8-bit DAT" in blob or "8-bit data bus" in low
        or ("DAT7" in blob and "DAT6" in blob and "DAT5" in blob
            and "DAT4" in blob)
    )
    # Data Strobe is eMMC-specific ONLY in its HS400 context. A bare "Data
    # Strobe" also names HyperBus's RWDS and other parallel memories, so the
    # HS400 qualifier is REQUIRED to keep this an eMMC-only feature.
    data_strobe = ("Data Strobe" in blob and "HS400" in blob)
    # RST_n must be the actual eMMC reset-pin token; the generic phrase
    # "hardware reset" appears on many parallel memories (e.g. HyperBus) and
    # is NOT eMMC-specific, so it is intentionally NOT a fallback here.
    rst_n = ("RST_n" in blob or "RST_N" in blob)
    ext_csd = ("EXT_CSD" in blob or "Extended CSD" in blob)
    boot_part = (
        "Boot Area Partition" in blob
        or ("boot partition" in low and "RPMB" in blob)
        or ("boot mode" in low and "alternative boot" in low)
    )
    rpmb = ("RPMB" in blob or "Replay Protected Memory Block" in blob)
    gpp_cfg = (
        ("General Purpose Partition" in blob and "PARTITION_CONFIG" in blob)
        or "PARTITION_CONFIG" in blob
    )
    hs400 = "HS400" in blob
    cmdq = ("CMDQ" in blob or "Command Queuing" in blob
            or "Command Queueing" in blob)
    ffu = ("FFU" in blob or "Field Firmware Update" in blob)
    hpi = ("HPI" in blob or "High Priority Interrupt" in blob)
    bkops = ("BKOPS" in blob or "Background Operations" in blob)

    emmc_features = [
        eight_bit_dat, data_strobe, rst_n, ext_csd, boot_part, rpmb,
        gpp_cfg, hs400, cmdq, ffu, hpi, bkops,
    ]
    n_emmc = sum(1 for f in emmc_features if f)

    # --- SD-PRIMARY signal: a removable-card doc with NO eMMC structure. ---
    sd_primary_name = (
        "SD Card" in blob or "SD Memory Card" in blob
        or "Secure Digital" in blob
    )
    sd_only_init = "ACMD41" in blob
    sd_removable = (
        "card detect" in low or "card-detect" in low
        or "card insertion" in low or "card removal" in low
        or "write-protect switch" in low or "SDIO" in blob
        or "CPRM" in blob
    )

    # --- UFS-PRIMARY signal: UFS (Universal Flash Storage) is ALSO an
    # embedded managed-NAND device that shares RPMB / boot partition /
    # Command Queuing vocabulary and even references "eMMC" as its
    # predecessor. But UFS is a SERIAL M-PHY / UniPro / SCSI device, NOT the
    # parallel CLK/CMD/DAT command bus — it has NO EXT_CSD, NO 8-bit DAT bus,
    # NO Data Strobe, NO HS400, NO RST_n pin, NO 48-bit CMD token. DEFER to
    # the UFS detector whenever UFS-primary serial-stack signals are present
    # UNLESS the doc ALSO carries an eMMC parallel-bus structural anchor
    # (EXT_CSD / DAT[7:0] / Data Strobe / HS400 / PARTITION_CONFIG) — which a
    # genuine UFS spec never does.
    ufs_primary = (
        "UFS" in blob or "Universal Flash Storage" in blob
        or "UniPro" in blob or "M-PHY" in blob or "MIPI M-PHY" in blob
        or "UTP" in blob or "UTRD" in blob or "UTMRD" in blob
        or ("SCSI" in blob and "JESD220" in blob)
    )

    # eMMC-EXCLUSIVE structural anchor — the hard discriminator. These tokens
    # appear in a genuine eMMC doc and NOT in a UFS / SD-card / ONFI / raw-NAND
    # doc, EVEN in the full superset blob (input_doc + every generated L-doc).
    # NOTE: weaker eMMC features (8-bit DAT bus / HS400 / Data Strobe) are
    # deliberately EXCLUDED from the anchor — a foreign managed-NAND doc
    # (ONFI/UFS/SD) enumerates those as candidate vocabulary in its generated
    # L-docs and would over-fire the anchor on the superset blob (the v0.1.89
    # KEY LESSON). EXT_CSD / RST_n / PARTITION_CONFIG / Boot Area Partition /
    # the embedded-MMC name / the JESD84 number are NOT enumerated by foreign
    # docs, so they uniquely anchor eMMC.
    emmc_exclusive_anchor = (
        ext_csd
        or rst_n
        or "PARTITION_CONFIG" in blob
        or "Boot Area Partition" in blob
        or "Embedded MultiMediaCard" in blob
        or "JESD84" in blob
    )
    emmc_parallel_anchor = emmc_exclusive_anchor

    # Family anchor: it must actually be the eMMC parallel command-bus family,
    # not an unrelated doc that merely references "eMMC" once (e.g. a UFS / SD
    # / ONFI doc citing it as predecessor/sibling). Require an eMMC-EXCLUSIVE
    # structural anchor.
    family = emmc_exclusive_anchor

    # DEFER if SD-primary-only (removable card, ACMD41, SDIO/CPRM) WITHOUT
    # the eMMC managed-NAND structure (need >= 2 eMMC-only features).
    if n_emmc < 2:
        return False

    # DEFER to UFS: a UFS-primary serial-stack doc that lacks the eMMC
    # parallel-bus anchor is UFS, not eMMC (it merely shares managed-NAND
    # vocabulary + an "eMMC" predecessor mention).
    if ufs_primary and not emmc_parallel_anchor:
        return False

    # If the doc is clearly an SD removable card AND carries no eMMC family
    # anchor, defer to the SD/MMC detector.
    if (sd_primary_name or sd_only_init or sd_removable) and not family:
        return False

    return bool(family and emmc_parallel_anchor and n_emmc >= 2)


# ----------------------------------------------------------------------
def apply_emmc_synth(generated_docs_dir: Path, is_emmc: bool,
                     emmc_ic_name: Optional[str]) -> None:
    """Apply JEDEC JESD84-B51 (eMMC 5.1) synth when the signature matched.

    eMMC DERIVES FROM the SD/MMC command protocol; if the SD/MMC synth ran
    first this routine FORCE-OVERWRITES (direct assignment, NOT setdefault)
    every key the SD/MMC synth would populate with the eMMC-canonical value,
    so SD output cannot leak through (cross-protocol force-overwrite doctrine).
    """
    if not is_emmc:
        return
    gd = Path(generated_docs_dir)

    # --- Force ic_name across ALL 24 docs FIRST (main + fields docs). ---
    if emmc_ic_name is not None:
        for n in _MAIN_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                d["ic_name"] = emmc_ic_name
                _write(q, d)
        for n in _FIELDS_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                f = _ensure_dict(d, "fields")
                f["ic_name"] = emmc_ic_name
                d["ic_name"] = emmc_ic_name
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
# L1 — eMMC datasheet header (FORCE-OVERWRITE).
# ----------------------------------------------------------------------
def _l1(gd: Path) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    d["document_title"] = (
        "Embedded MultiMediaCard (eMMC) Electrical Standard (5.1)")
    d["document_number"] = "JESD84-B51"
    d["version"] = "eMMC 5.1 (JESD84-B51)"
    d["revised_date"] = "February 2015"
    d["manufacturer"] = "JEDEC Solid State Technology Association"
    d["copyright"] = "© JEDEC Solid State Technology Association"
    d["abstract"] = (
        "The Embedded MultiMediaCard (eMMC) is an embedded, managed-NAND flash "
        "storage device permanently soldered onto the host board. It "
        "integrates a NAND array with an on-die controller that performs wear "
        "leveling, bad-block management and ECC, presenting a clean "
        "block-addressable device over a CLK/CMD/DAT bus whose 48-bit "
        "command/response/data protocol derives from the MultiMediaCard (MMC) "
        "/ SD protocol. Unlike a removable SD card, eMMC has NO card slot, NO "
        "card-detect, NO mechanical write-protect switch, NO card "
        "insertion/removal sequence and NO SDIO function. eMMC adds an 8-bit "
        "DAT bus (DAT[7:0]), a Data Strobe (DS) for HS400, a hardware reset "
        "pin (RST_n), a 512-byte Extended CSD (EXT_CSD) configuration "
        "register, hardware partitions (Boot Area Partition 1/2, a Replay "
        "Protected Memory Block (RPMB), General Purpose Partitions, and the "
        "User Data Area, selected by PARTITION_CONFIG), a boot operation "
        "(boot mode / alternative boot), the HS200 (200 MB/s) and HS400 "
        "(400 MB/s with Data Strobe) speed modes, and managed-NAND features "
        "(HPI, Background Operations, Cache, Sanitize/TRIM/Discard, Secure "
        "Erase, Field Firmware Update, Packed commands, Command Queuing).")
    d["keywords"] = [
        "eMMC", "Embedded MultiMediaCard", "JESD84-B51", "managed NAND",
        "CLK", "CMD", "DAT[7:0]", "8-bit data bus", "Data Strobe", "DS",
        "RST_n", "hardware reset", "OCR", "CID", "CSD", "EXT_CSD",
        "Extended CSD", "PARTITION_CONFIG", "Boot Area Partition", "RPMB",
        "Replay Protected Memory Block", "General Purpose Partition",
        "boot operation", "alternative boot", "HS200", "HS400", "DDR",
        "HPI", "Background Operations", "BKOPS", "Cache", "Sanitize", "TRIM",
        "Discard", "Secure Erase", "FFU", "Field Firmware Update",
        "Packed commands", "CMDQ", "Command Queuing",
    ]
    d["external_pins"] = list(_EMMC_BUS_SIGNALS)
    d["external_pin_count"] = 13
    d["data_bus_width_bits"] = [1, 4, 8]
    d["supply_voltages"] = {
        "VCC": "3.3V or 1.8V class (NAND core / memory)",
        "VCCQ": "1.8V or 1.2V class (I/O and controller)",
        "note": "HS200/HS400 require 1.8V or 1.2V I/O",
    }
    d["speed_modes"] = list(_EMMC_SPEED_MODES)
    d["registers"] = ["OCR (32-bit)", "CID (128-bit)", "CSD (128-bit)",
                      "EXT_CSD (512-byte)", "RCA (16-bit)", "DSR (16-bit, opt)"]
    d["partitions"] = list(_EMMC_PARTITIONS)
    d["modes_of_operation"] = [
        {"name": "Device identification",
         "description": "CMD0/CMD1/CMD2/CMD3 bring the device through "
         "Idle->Ready->Ident and assign the RCA."},
        {"name": "Data transfer",
         "description": "CMD7 selects the device (Stby->Tran); read/write "
         "block commands cycle Tran<->Data/Rcv<->Prg."},
        {"name": "Boot operation",
         "description": "boot mode / alternative boot streams boot-partition "
         "code before device identification."},
        {"name": "HS200 / HS400 high-speed",
         "description": "200 MB/s SDR (HS200, tuned) and 400 MB/s DDR with "
         "Data Strobe (HS400) on the 8-bit bus."},
        {"name": "Command Queuing (CMDQ)",
         "description": "up to 32 tasks enqueued and executed out of order "
         "(eMMC 5.1)."},
    ]
    d["key_features"] = [
        "Embedded managed-NAND device: soldered down, NO card-detect, NO "
        "mechanical write-protect switch, NO card insert/remove sequence, NO "
        "SDIO function.",
        "Bus: CLK, bidirectional CMD (48-bit, CRC7), DAT[7:0] up to 8-bit "
        "(1/4/8-bit selectable) — the 8-bit DAT bus is a key differentiator "
        "from the SD card's 4-bit DAT bus.",
        "Data Strobe (DS): device-sourced read strobe used in HS400 to latch "
        "DDR read data reliably at 400 MB/s; unique to eMMC.",
        "Hardware Reset (RST_n): active-low device reset without removing "
        "power; enabled via EXT_CSD RST_n_FUNCTION.",
        "512-byte Extended CSD (EXT_CSD): the central configuration/capability "
        "register (read with CMD8, written field-by-field with CMD6/SWITCH).",
        "Hardware partitions: User Data Area, Boot Area Partition 1/2, Replay "
        "Protected Memory Block (RPMB), General Purpose Partitions; selected "
        "by PARTITION_CONFIG.",
        "Boot operation: boot mode and alternative boot (CMD0 arg 0xFFFFFFFA) "
        "stream boot-partition code before device identification.",
        "Speed modes: backward (26 MHz), High Speed (52 MHz SDR / 104 MB/s "
        "DDR), HS200 (200 MB/s SDR), HS400 (400 MB/s DDR with Data Strobe).",
        "Managed-NAND features: wear leveling, bad-block management, ECC, HPI, "
        "Background Operations, Cache, Sanitize/TRIM/Discard, Secure Erase, "
        "Field Firmware Update (FFU), Packed commands, Command Queuing (CMDQ).",
        "Device state machine: Inactive/Idle/Ready/Identification/Stand-by/"
        "Transfer/Sending-data/Receive-data/Programming/Disconnect.",
        "CRC7 on CMD, CRC16 per DAT line for bus data integrity.",
        "RPMB authenticated, replay-protected storage (HMAC-SHA256 + monotonic "
        "write counter).",
    ]
    d["conformance"] = "JEDEC JESD84-B51 (eMMC 5.1)"
    _write(p, d)


# ----------------------------------------------------------------------
# L2 — functional requirements / protocol overview.
# ----------------------------------------------------------------------
def _l2(gd: Path) -> None:
    p = gd / "L2_FRS.json"
    if not p.is_file():
        return
    d = _read(p)
    po = _ensure_dict(d, "protocol_overview")
    po["type"] = (
        "Embedded managed-NAND storage device over a synchronous CLK/CMD/DAT "
        "command bus derived from the MultiMediaCard (MMC) / SD protocol; "
        "48-bit commands, R1..R5 responses, block data with CRC16 per DAT "
        "line.")
    po["duplex"] = (
        "half-duplex on the shared CMD/DAT bus (single embedded device; one "
        "transaction at a time). DAT bus is bidirectional.")
    po["synchronous_serial"] = True
    po["source_synchronous"] = True
    po["clock_line"] = "CLK (host-driven; both edges in DDR/HS400)"
    po["command_line"] = "CMD (bidirectional, 48-bit token, CRC7)"
    po["data_lines"] = "DAT[7:0] (1/4/8-bit selectable; bidirectional)"
    po["data_strobe"] = "DS (device-sourced read strobe; HS400 only)"
    po["hardware_reset"] = "RST_n (active-low; EXT_CSD RST_n_FUNCTION)"
    po["derived_from"] = "MultiMediaCard (MMC) / SD command protocol"
    po["embedded"] = (
        "soldered managed-NAND device: no card-detect, no write-protect "
        "switch, no card insert/remove, no SDIO")
    po["data_bus_width_bits"] = [1, 4, 8]
    po["speed_modes"] = list(_EMMC_SPEED_MODES)
    po["registers"] = {
        "OCR": "32-bit operation-conditions (voltage window + busy + access "
               "mode); polled with CMD1/SEND_OP_COND (eMMC uses CMD1, not the "
               "SD application ACMD41).",
        "CID": "128-bit device identification (MID/OEM/product/serial/date).",
        "CSD": "128-bit device-specific data (timing, CCC, capacity legacy).",
        "EXT_CSD": "512-byte Extended CSD configuration/capability register "
                   "(CMD8 read, CMD6/SWITCH write).",
        "RCA": "16-bit relative device address (assigned by CMD3).",
    }
    po["partitions"] = list(_EMMC_PARTITIONS)
    po["partition_switching"] = (
        "PARTITION_CONFIG (PARTITION_ACCESS bits) via SWITCH/CMD6 selects the "
        "active partition for User-area access and boot.")
    po["device_states"] = list(_EMMC_DEVICE_STATES)
    po["managed_nand_features"] = list(_EMMC_MANAGED_NAND)
    d["protocol_overview"] = po
    d["functional_requirements"] = [
        {"id": "FR-BUS-01", "text": "The eMMC bus is CLK + bidirectional CMD "
         "+ DAT[7:0] (up to 8-bit, selectable 1/4/8-bit), with optional Data "
         "Strobe (DS, HS400) and hardware reset RST_n."},
        {"id": "FR-CMD-02", "text": "Commands are 48-bit tokens (start, "
         "transmission, 6-bit index CMD0..CMD63, 32-bit argument, CRC7, end); "
         "responses are R1/R1b/R2/R3/R4/R5."},
        {"id": "FR-REG-03", "text": "The device exposes OCR, CID, CSD and a "
         "512-byte Extended CSD (EXT_CSD); EXT_CSD is read with SEND_EXT_CSD "
         "(CMD8) and written field-by-field with SWITCH (CMD6)."},
        {"id": "FR-INIT-04", "text": "Initialization polls OCR with "
         "SEND_OP_COND (CMD1) until busy clears, then ALL_SEND_CID (CMD2) and "
         "SET_RELATIVE_ADDR (CMD3) assign the RCA. eMMC uses CMD1, never the "
         "SD application command ACMD41."},
        {"id": "FR-PART-05", "text": "The device presents hardware partitions "
         "(User Data Area, Boot Area Partition 1/2, RPMB, General Purpose "
         "Partitions) selected by PARTITION_CONFIG via SWITCH (CMD6)."},
        {"id": "FR-BOOT-06", "text": "A boot operation (boot mode / "
         "alternative boot, CMD0 arg 0xFFFFFFFA) streams boot-partition code "
         "from BOOT_CONFIG before device identification."},
        {"id": "FR-RPMB-07", "text": "The RPMB partition provides "
         "authenticated, replay-protected reads/writes using an HMAC-SHA256 "
         "MAC, a one-time-programmable key and a monotonic write counter."},
        {"id": "FR-SPEED-08", "text": "Speed modes: backward (26 MHz), High "
         "Speed (52 MHz SDR / 104 MB/s DDR), HS200 (200 MB/s SDR, tuned), "
         "HS400 (400 MB/s DDR with device-sourced Data Strobe)."},
        {"id": "FR-MGMT-09", "text": "Managed-NAND features: wear leveling, "
         "bad-block management, ECC, HPI, Background Operations, Cache, "
         "Sanitize/TRIM/Discard, Secure Erase, Field Firmware Update (FFU), "
         "Packed commands, Command Queuing (CMDQ, up to 32 tasks)."},
        {"id": "FR-INTEG-10", "text": "Bus integrity is protected by CRC7 on "
         "the CMD line and CRC16 per DAT line."},
    ]
    d["fmax_mhz"] = 200
    _write(p, d)


# ----------------------------------------------------------------------
# L3 — command protocol.
# ----------------------------------------------------------------------
def _l3(gd: Path) -> None:
    p = gd / "L3_CMD_PROTOCOL.json"
    if not p.is_file():
        return
    d = _read(p)
    d["command_token_bits"] = 48
    d["command_format"] = (
        "start(1) + transmission(1) + command index(6) + argument(32) + "
        "CRC7(7) + end(1)")
    d["response_formats"] = ["R1", "R1b", "R2 (CID/CSD)", "R3 (OCR)",
                             "R4", "R5"]
    d["crc_parameters"] = {
        "cmd_crc": "CRC7 (x^7+x^3+1) over the 40-bit command/response content",
        "data_crc": "CRC16-CCITT (x^16+x^12+x^5+1) per DAT line per block",
    }
    d["commands"] = list(_EMMC_COMMANDS)
    d["device_states"] = list(_EMMC_DEVICE_STATES)
    d["boot_operation"] = {
        "boot_mode": "host holds CMD low >= 74 CLK cycles (or boot ack) to "
                     "stream BOOT_CONFIG boot partition before identification",
        "alternative_boot": "CMD0 with argument 0xFFFFFFFA",
        "boot_acknowledge": "device sends '010' pattern on DAT0",
        "boot_bus": "width/timing from BOOT_BUS_CONDITIONS",
    }
    d["default_block_length_bytes"] = 512
    _write(p, d)


# ----------------------------------------------------------------------
# L4 — register map (EXT_CSD + core registers).
# ----------------------------------------------------------------------
def _l4(gd: Path) -> None:
    p = gd / "L4_REGMAP.json"
    if not p.is_file():
        return
    d = _read(p)
    d["registers"] = [
        {"name": "OCR", "width_bits": 32,
         "description": "Operation Conditions: VCC voltage window, busy bit, "
         "access-mode (byte vs sector addressing). Read/poll via CMD1."},
        {"name": "CID", "width_bits": 128,
         "description": "Device identification: MID, OEM/App ID, product "
         "name/revision, serial number, manufacturing date. CMD2/CMD10."},
        {"name": "CSD", "width_bits": 128,
         "description": "Device-specific data: TAAC/NSAC, max data rate, "
         "command classes (CCC), block lengths, legacy capacity. CMD9."},
        {"name": "EXT_CSD", "width_bits": 4096,
         "description": "512-byte Extended CSD: Properties (read-only "
         "capabilities) + Modes (host-writable config). CMD8 read / CMD6 "
         "SWITCH write."},
        {"name": "RCA", "width_bits": 16,
         "description": "Relative Device Address assigned by CMD3."},
        {"name": "DSR", "width_bits": 16,
         "description": "Optional Driver Stage Register (output drive)."},
    ]
    d["ext_csd_key_fields"] = list(_EMMC_EXT_CSD_FIELDS)
    _write(p, d)


# ----------------------------------------------------------------------
# L5 — analog/driver interface spec.
# ----------------------------------------------------------------------
def _l5(gd: Path) -> None:
    p = gd / "L5_ADI_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["io_supplies"] = {
        "VCC": "NAND core / memory supply (3.3V or 1.8V class)",
        "VCCQ": "I/O and controller supply (1.8V or 1.2V class)",
        "note": "HS200/HS400 require 1.8V or 1.2V I/O signaling",
    }
    d["signaling"] = (
        "single-ended push-pull CMD/DAT; SDR up to HS200 (200 MHz), DDR "
        "(both CLK edges) for High Speed DDR and HS400; HS400 adds the "
        "device-sourced Data Strobe (DS) as a read strobe.")
    d["drive_strength"] = "selectable I/O driver strength (EXT_CSD DRIVER_STRENGTH)"
    d["tuning"] = ("HS200/HS400 use SEND_TUNING_BLOCK (CMD21) to centre the "
                   "read sampling point.")
    _write(p, d)


# ----------------------------------------------------------------------
# L6 — control logic / FSM.
# ----------------------------------------------------------------------
def _l6(gd: Path) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["device_state_machine"] = {
        "states": list(_EMMC_DEVICE_STATES),
        "init_sequence": "CMD0 (Idle) -> CMD1 poll OCR (Ready) -> CMD2 CID "
                         "(Ident) -> CMD3 RCA (Stand-by)",
        "transfer_sequence": "CMD7 select (Stby->Tran) -> read/write block "
                             "commands cycle Tran<->Data/Rcv<->Prg",
        "reset": "RST_n hardware reset or CMD0 returns the device to Idle",
    }
    d["partition_switch_fsm"] = (
        "PARTITION_CONFIG.PARTITION_ACCESS (via SWITCH/CMD6) routes subsequent "
        "User-area accesses to the selected partition (User / Boot1 / Boot2 / "
        "RPMB / GPP1..4).")
    d["boot_fsm"] = (
        "power-up/RST_n -> (boot mode: CMD held low >=74 clk, or alternative "
        "boot CMD0 arg 0xFFFFFFFA) -> stream boot partition -> terminate -> "
        "normal identification.")
    _write(p, d)


# ----------------------------------------------------------------------
# L7 — test/debug.
# ----------------------------------------------------------------------
def _l7(gd: Path) -> None:
    p = gd / "L7_TEST_DEBUG.json"
    if not p.is_file():
        return
    d = _read(p)
    d["debug_features"] = [
        "SEND_STATUS (CMD13) device status + Queue Status (CMDQ)",
        "SEND_EXT_CSD (CMD8) full 512-byte capability/config dump",
        "SEND_TUNING_BLOCK (CMD21) HS200/HS400 read-path tuning",
        "BKOPS_STATUS / urgency reporting in EXT_CSD",
        "FFU_STATUS field-firmware-update progress",
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
    d["constants"] = {
        "CMD_TOKEN_BITS": 48,
        "CMD_INDEX_BITS": 6,
        "ARG_BITS": 32,
        "CRC7_POLY": "x^7+x^3+1",
        "CRC16_POLY": "x^16+x^12+x^5+1 (CCITT)",
        "DEFAULT_BLOCK_BYTES": 512,
        "EXT_CSD_BYTES": 512,
        "OCR_BITS": 32,
        "CID_BITS": 128,
        "CSD_BITS": 128,
        "RCA_BITS": 16,
        "DAT_BUS_WIDTH_MAX": 8,
        "CMDQ_MAX_TASKS": 32,
        "BOOT_SIZE_MULT_UNIT_KB": 128,
        "ALT_BOOT_ARG": "0xFFFFFFFA",
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L8 — timing/waveform.
# ----------------------------------------------------------------------
def _l8_timing(gd: Path) -> None:
    p = gd / "L8_TIMING_WAVEFORM.json"
    if not p.is_file():
        return
    d = _read(p)
    d["clock_modes"] = list(_EMMC_SPEED_MODES)
    d["timing_notes"] = [
        "Backward: <=26 MHz SDR. High Speed: <=52 MHz SDR or 52 MHz DDR.",
        "HS200: up to 200 MHz SDR, single-ended, tuned (CMD21).",
        "HS400: 200 MHz clock, DDR on 8-bit bus, device-sourced Data Strobe "
        "(DS) returns the read strobe; entered from HS200.",
        "DDR transfers data on both CLK edges (doubles throughput).",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L9 — integration spec.
# ----------------------------------------------------------------------
def _l9(gd: Path) -> None:
    p = gd / "L9_INTEGRATION_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["host_interface"] = (
        "single host controller to a single embedded device over CLK/CMD/"
        "DAT[7:0] (+ DS for HS400, + RST_n). No bus arbitration between "
        "multiple devices (embedded point-to-point).")
    d["integration_notes"] = [
        "Provide VCC (NAND) + VCCQ (I/O) with the I/O voltage matching the "
        "speed mode (HS200/HS400 need 1.8V/1.2V).",
        "Route DS as a device->host source-synchronous read strobe for HS400.",
        "Drive RST_n for hardware reset; enable via EXT_CSD RST_n_FUNCTION.",
        "Pull-ups / terminations per the selected speed mode.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L10 — test cases.
# ----------------------------------------------------------------------
def _l10(gd: Path) -> None:
    p = gd / "L10_TEST_CASES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_cases"] = [
        {"id": "TC-INIT-01", "name": "OCR poll via CMD1 until busy clears, "
         "then CMD2/CMD3 assign RCA (idle->ready->ident->stby)."},
        {"id": "TC-EXTCSD-02", "name": "SEND_EXT_CSD (CMD8) returns 512 bytes; "
         "SWITCH (CMD6) updates a single EXT_CSD field."},
        {"id": "TC-BUS-03", "name": "Switch BUS_WIDTH to 8-bit DDR and verify "
         "block read/write."},
        {"id": "TC-PART-04", "name": "PARTITION_CONFIG switch to Boot1 / RPMB "
         "/ GPP and verify access isolation."},
        {"id": "TC-BOOT-05", "name": "Alternative boot (CMD0 arg 0xFFFFFFFA) "
         "streams boot-partition contents."},
        {"id": "TC-RPMB-06", "name": "Authenticated RPMB write/read with "
         "HMAC-SHA256 + write counter; replay attempt rejected."},
        {"id": "TC-HS400-07", "name": "HS200 tuning then HS400 DDR with Data "
         "Strobe at 400 MB/s; verify read-data integrity."},
        {"id": "TC-CMDQ-08", "name": "Enqueue >1 task (CMD44/45), execute "
         "out-of-order (CMD46/47), verify Queue Status."},
        {"id": "TC-MGMT-09", "name": "TRIM/Discard then Sanitize; verify "
         "purged data unreadable. FFU updates firmware (FFU_STATUS ok)."},
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L11 — OTP content (RPMB key / security provisioning).
# ----------------------------------------------------------------------
def _l11(gd: Path) -> None:
    p = gd / "L11_OTP_CONTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    d["otp_items"] = [
        {"name": "RPMB Authentication Key", "type": "one-time-programmable",
         "description": "256-bit key provisioned once into the RPMB; used for "
         "the HMAC-SHA256 MAC. Read-back is forbidden after programming."},
        {"name": "PARTITION_SETTING_COMPLETED", "type": "one-time",
         "description": "Committing GP/enhanced partition sizes "
         "(GP_SIZE_MULT/PARTITIONS_ATTRIBUTE) is irreversible."},
        {"name": "CID", "type": "factory-programmed",
         "description": "Manufacturer-programmed device identification."},
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L12 — behavioral sequences.
# ----------------------------------------------------------------------
def _l12(gd: Path) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["sequences"] = [
        {"name": "Power-up / initialization",
         "steps": ["RST_n / CMD0 -> Idle", "CMD1 poll OCR until !busy -> Ready",
                   "CMD2 ALL_SEND_CID -> Ident", "CMD3 SET_RELATIVE_ADDR -> "
                   "Stand-by", "CMD9 SEND_CSD", "CMD7 select -> Transfer",
                   "CMD8 SEND_EXT_CSD; CMD6 SWITCH bus width / HS_TIMING"]},
        {"name": "Block read (8-bit DDR)",
         "steps": ["CMD7 select", "CMD17/CMD18 READ_(MULTIPLE_)BLOCK",
                   "DAT[7:0] streams 512-byte blocks + CRC16",
                   "CMD12 STOP for open-ended"]},
        {"name": "HS400 entry",
         "steps": ["switch to HS200 (CMD6 HS_TIMING)", "CMD21 tuning",
                   "CMD6 HS_TIMING=HS400 + BUS_WIDTH=8-bit DDR",
                   "device returns Data Strobe (DS) for reads"]},
        {"name": "Boot operation",
         "steps": ["power-up / RST_n", "boot mode (CMD low >=74 clk) or "
                   "alternative boot (CMD0 arg 0xFFFFFFFA)",
                   "stream BOOT_CONFIG boot partition on DAT",
                   "terminate -> normal identification"]},
        {"name": "Command Queuing",
         "steps": ["CMDQ_MODE_EN", "CMD44/CMD45 enqueue task params/address",
                   "CMD13 Queue Status -> ready tasks",
                   "CMD46/CMD47 EXECUTE_READ/WRITE_TASK",
                   "CMD48 CMDQ_TASK_MGMT discard"]},
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L13 — lab calibration.
# ----------------------------------------------------------------------
def _l13(gd: Path) -> None:
    p = gd / "L13_LAB_CALIBRATION.json"
    if not p.is_file():
        return
    d = _read(p)
    d["calibration_items"] = [
        "HS200/HS400 read-path tuning via SEND_TUNING_BLOCK (CMD21) to centre "
        "the sampling window.",
        "Data Strobe (DS) skew alignment for HS400 DDR reads.",
        "I/O driver strength selection (EXT_CSD DRIVER_STRENGTH) per board "
        "loading.",
    ]
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
    f["standard"] = "JEDEC JESD84-B51"
    f["protocol_version"] = "eMMC 5.1"
    f["release_date"] = "February 2015"
    f["lineage"] = [
        "MMC (MultiMediaCard) -> eMMC 4.x (embedded) -> eMMC 4.5 (HPI, BKOPS, "
        "Cache, Discard) -> eMMC 5.0 (HS400, Data Strobe, FFU) -> eMMC 5.1 "
        "(Command Queuing/CMDQ, enhanced strobe, secure features).",
    ]
    f["derived_from"] = "MultiMediaCard (MMC) / SD command protocol"
    f["key_additions_5_1"] = [
        "Command Queuing (CMDQ, up to 32 tasks)",
        "Enhanced Data Strobe", "Secure Write Protect", "Production State "
        "Awareness",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L15 — encoding tables.
# ----------------------------------------------------------------------
def _l15(gd: Path) -> None:
    p = gd / "L15_ENCODING_TABLES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["command_index_encoding"] = [
        {"index": c["index"], "name": c["name"]} for c in _EMMC_COMMANDS
    ]
    f["response_types"] = ["R1 (normal)", "R1b (busy)", "R2 (CID/CSD 136-bit)",
                           "R3 (OCR)", "R4", "R5"]
    f["hs_timing_encoding"] = {
        "0": "backward compatible (<=26 MHz)", "1": "High Speed (52 MHz)",
        "2": "HS200", "3": "HS400"}
    f["bus_width_encoding"] = {
        "0": "1-bit", "1": "4-bit", "2": "8-bit", "5": "4-bit DDR",
        "6": "8-bit DDR"}
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
    f["properties"] = [
        "Commands are well-formed 48-bit tokens with valid CRC7; bad CRC7 is "
        "ignored / NAK'd.",
        "Data blocks carry a valid CRC16 per DAT line; CRC error is reported "
        "and the block re-transferred.",
        "eMMC uses CMD1/SEND_OP_COND for OCR (never the SD application "
        "command ACMD41).",
        "PARTITION_SETTING_COMPLETED makes GP/enhanced partition definition "
        "irreversible.",
        "RPMB writes require a valid HMAC-SHA256 and a matching monotonic "
        "write counter; replayed/forged packets are rejected.",
        "HS400 requires HS200 tuning first and a valid Data Strobe.",
    ]
    f["standard"] = "JEDEC JESD84-B51 (eMMC 5.1)"
    _write(p, d)


# ----------------------------------------------------------------------
# L17 — channel/signal catalog.
# ----------------------------------------------------------------------
def _l17(gd: Path) -> None:
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["channels"] = [
        {"name": "CLK", "direction": "host -> device",
         "purpose": "bus clock; data on both edges in DDR/HS400.",
         "active_levels": "push-pull; up to 200 MHz",
         "idle_level": "host-controlled"},
        {"name": "CMD", "direction": "bidirectional",
         "purpose": "48-bit command/response line (CRC7).",
         "active_levels": "push-pull, start/transmission/index/arg/CRC7/end",
         "idle_level": "driven high (1)"},
        {"name": "DAT[7:0]", "direction": "bidirectional",
         "purpose": "1/4/8-bit data bus; 512-byte blocks + CRC16 per line.",
         "active_levels": "push-pull; SDR or DDR",
         "idle_level": "driven high (1)"},
        {"name": "DS (Data Strobe)", "direction": "device -> host",
         "purpose": "HS400 read-data strobe (source-synchronous read).",
         "active_levels": "toggles with returned read data (HS400)",
         "idle_level": "inactive outside HS400 reads"},
        {"name": "RST_n", "direction": "host -> device",
         "purpose": "active-low hardware reset (EXT_CSD RST_n_FUNCTION).",
         "active_levels": "asserted low to reset",
         "idle_level": "de-asserted high"},
        {"name": "VCC / VCCQ", "direction": "supply",
         "purpose": "NAND-core supply (VCC) and I/O supply (VCCQ).",
         "active_levels": "3.3V/1.8V (VCC); 1.8V/1.2V (VCCQ)",
         "idle_level": "n/a"},
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
    f["topology"] = (
        "point-to-point: a single host controller to a single embedded eMMC "
        "device (soldered). No multi-drop card bus, no card slot, no "
        "card-detect.")
    f["signals"] = ["CLK", "CMD", "DAT[7:0]", "DS", "RST_n", "VCC", "VCCQ",
                    "VSS", "VSSQ"]
    f["partitions"] = list(_EMMC_PARTITIONS)
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
    f["timing_constraints"] = [
        "CLK up to 200 MHz (HS200/HS400).",
        "HS400 DDR: data valid relative to the device-sourced Data Strobe (DS) "
        "rather than CLK.",
        "Setup/hold tuned via CMD21 in HS200/HS400.",
    ]
    f["io_constraints"] = [
        "VCCQ 1.8V or 1.2V for HS200/HS400; 3.3V allowed for legacy modes.",
        "Selectable driver strength to match board loading.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L20 — DFT/scan.
# ----------------------------------------------------------------------
def _l20(gd: Path) -> None:
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["notes"] = [
        "eMMC is a packaged managed-NAND device; host-side controller DFT "
        "covers the CLK/CMD/DAT/DS/RST_n interface logic and the EXT_CSD "
        "register file.",
        "Device self-test surfaces via SEND_STATUS (CMD13) and EXT_CSD status "
        "fields.",
    ]
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
    f["power_domains"] = [
        {"name": "VCC", "purpose": "NAND core / memory array"},
        {"name": "VCCQ", "purpose": "I/O and controller logic"},
    ]
    f["low_power"] = [
        "Sleep (CMD5 SLEEP_AWAKE) puts the device into a low-power sleep state "
        "with only VCCQ maintained (VCC may be removed).",
        "Background Operations performed in granted idle time.",
    ]
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
    f["coverage_goals"] = [
        "All speed modes (backward / HS / HS200 / HS400) read+write at "
        "1/4/8-bit.",
        "Partition switching across User / Boot1 / Boot2 / RPMB / GPP.",
        "Boot mode + alternative boot streaming.",
        "RPMB authenticated/replay-protected access (good + forged + replay).",
        "Command Queuing enqueue/execute/discard with out-of-order completion.",
        "Managed-NAND ops: TRIM/Discard/Sanitize/Secure Erase/FFU/HPI/BKOPS/"
        "Cache flush.",
        "CRC7/CRC16 error injection and recovery.",
    ]
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
    f["requirements"] = [
        "RPMB (Replay Protected Memory Block): authenticated reads/writes with "
        "HMAC-SHA256, a one-time-programmable 256-bit key, and a monotonic "
        "write counter to defeat replay attacks.",
        "Secure Erase / Secure TRIM guarantee actual erasure of targeted data.",
        "Sanitize physically purges all unmapped/trimmed data.",
        "Secure Write Protect (eMMC 5.1) protects regions from modification.",
        "Field Firmware Update (FFU) installs a vendor-signed firmware image.",
    ]
    _write(p, d)
